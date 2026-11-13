"""The drybench protocol file: what to do, with no word about how a robot does it.

A protocol file is YAML. It names the labware, says where liquids start, and lists steps.
Loading one checks every field strictly and reports every problem it finds, each with the
place in the file it came from. `expand` then turns the steps into the plain aspirate-and-
dispense moves they stand for, and `check` follows the liquid through those moves.

Draft format 0.1. See docs/protocol-format.md.
"""

from __future__ import annotations

import csv
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

FORMAT_VERSION = "0.1"
EPS = 1e-6

_VOLUME_UNITS = {"nL": 1e-3, "uL": 1.0, "µL": 1.0, "μL": 1.0, "mL": 1e3, "L": 1e6}
_TIME_UNITS = {"s": 1.0, "min": 60.0, "h": 3600.0}
_QUANTITY = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(\S+)\s*$")
_WELLS = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)/([A-Z]+[0-9]+)(?::([A-Z]+[0-9]+))?$")
_DIRECTIONS = {"right": (1, 0), "left": (-1, 0), "down": (0, 1), "up": (0, -1)}


@dataclass(frozen=True)
class Problem:
  where: str  # the place in the file, such as "steps[2].transfer.volume"
  message: str

  def __str__(self) -> str:
    return f"{self.where}: {self.message}"


class ProtocolError(Exception):
  """The file cannot be read as a protocol. `problems` lists every reason found."""

  def __init__(self, problems: List[Problem]):
    self.problems = problems
    super().__init__("\n".join(str(p) for p in problems))


@dataclass(frozen=True)
class Well:
  labware: str
  well: str  # "A1"

  def __str__(self) -> str:
    return f"{self.labware}/{self.well}"


WASTE = Well("waste", "-")


@dataclass
class Labware:
  name: str
  type: str  # a PyLabRobot definition name
  rows: int
  columns: int
  capacity: float  # uL per well
  order: List[str]  # every well name, in PyLabRobot's order

  def at(self, column: int, row: int) -> Optional[str]:
    if 0 <= column < self.columns and 0 <= row < self.rows:
      return self.order[column * self.rows + row]
    return None

  def position(self, well: str) -> Tuple[int, int]:
    index = self.order.index(well)
    return index // self.rows, index % self.rows


@dataclass(frozen=True)
class Transfer:
  source: List[Well]
  destination: List[Well]
  volume: float
  tips: str  # "fresh" or "reuse"
  mix_after: Optional[Tuple[int, float]]  # (times, volume)


@dataclass(frozen=True)
class Mix:
  wells: List[Well]
  volume: float
  times: int


@dataclass(frozen=True)
class SerialDilution:
  start: List[Well]
  steps: int
  direction: str
  volume: float
  mix: Optional[Tuple[int, float]]
  discard: bool
  tips: str


@dataclass(frozen=True)
class Normalize:
  source: str  # labware name
  destination: str  # labware name
  diluent: Well
  target: float
  unit: str
  final_volume: float
  mix: Optional[Tuple[int, float]]


@dataclass(frozen=True)
class Wait:
  seconds: float


Step = Union[Transfer, Mix, SerialDilution, Normalize, Wait]


@dataclass
class Protocol:
  name: str
  description: str
  labware: Dict[str, Labware]
  liquids: Dict[str, Tuple[List[Well], float]]  # name -> (wells, uL in each)
  concentrations: Dict[Well, float]  # from the samples table
  concentration_unit: str
  min_volume: float
  steps: List[Step]
  path: Optional[Path] = None
  notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------- moves


@dataclass(frozen=True)
class Move:
  """One thing a pipette does. `tip` numbers the tip it uses, counting from 0."""

  step: int
  kind: str  # "transfer", "mix" or "wait"
  source: Optional[Well] = None
  destination: Optional[Well] = None
  volume: float = 0.0
  times: int = 1
  tip: int = -1
  seconds: float = 0.0


_ONE_WELL = re.compile(r"(?<![\w/])([A-Za-z_][\w-]*)/([A-Z]{1,2}[0-9]{1,2})(?![\w:])")


def _merged(problems: List[Problem]) -> List[Problem]:
  """Fold a problem that repeats well after well into one line that names the wells."""
  merged: List[Problem] = []
  groups: Dict[Tuple[str, str], Tuple[int, List[str]]] = {}
  for problem in problems:
    found = _ONE_WELL.findall(problem.message)
    if len(found) != 1:
      merged.append(problem)
      continue
    labware, well = found[0]
    key = (problem.where, problem.message.replace(f"{labware}/{well}", f"{labware}/*"))
    if key in groups:
      groups[key][1].append(well)
    else:
      groups[key] = (len(merged), [])
      merged.append(problem)
  for position, others in groups.values():
    if others:
      shown = ", ".join(others) if len(others) <= 4 else f"{others[0]}, {others[1]}, ... {others[-1]}"
      first = merged[position]
      plural = "well" if len(others) == 1 else "wells"
      merged[position] = Problem(first.where, f"{first.message}; the same in {len(others)} more {plural} ({shown})")
  return merged


# ---------------------------------------------------------------- reading


class _Reader:
  def __init__(self, base: Optional[Path]):
    self.base = base
    self.problems: List[Problem] = []
    self.labware: Dict[str, Labware] = {}

  def fail(self, where: str, message: str) -> None:
    self.problems.append(Problem(where, message))

  def keys(self, value: Any, where: str, required: Tuple[str, ...], optional: Tuple[str, ...] = ()) -> dict:
    """Check that `value` is a mapping with exactly the allowed keys. Returns it, or {}."""
    if not isinstance(value, dict):
      self.fail(where, f"expected a mapping with {', '.join(required + optional)}")
      return {}
    for key in value:
      if key not in required + optional:
        self.fail(f"{where}.{key}", f"unknown field; allowed here: {', '.join(required + optional)}")
    for key in required:
      if key not in value:
        self.fail(where, f"missing required field '{key}'")
    return value

  def quantity(self, value: Any, where: str, units: Dict[str, float], kind: str) -> Optional[float]:
    match = _QUANTITY.match(value) if isinstance(value, str) else None
    if match is None or match.group(2) not in units:
      self.fail(where, f"expected a {kind} such as '{'100 uL' if kind == 'volume' else '5 min'}', got {value!r}")
      return None
    return float(match.group(1)) * units[match.group(2)]

  def volume(self, value: Any, where: str) -> Optional[float]:
    return self.quantity(value, where, _VOLUME_UNITS, "volume")

  def concentration(self, value: Any, where: str) -> Optional[Tuple[float, str]]:
    match = _QUANTITY.match(value) if isinstance(value, str) else None
    if match is None or "/" not in match.group(2):
      self.fail(where, f"expected a concentration such as '10 ng/uL', got {value!r}")
      return None
    return float(match.group(1)), match.group(2)

  def count(self, value: Any, where: str) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
      self.fail(where, f"expected a whole number of 1 or more, got {value!r}")
      return None
    return value

  def wells(self, value: Any, where: str) -> List[Well]:
    match = _WELLS.match(value) if isinstance(value, str) else None
    if match is None:
      self.fail(where, f"expected wells such as 'plate/A1' or 'plate/A1:H1', got {value!r}")
      return []
    name, first, last = match.groups()
    labware = self.labware.get(name)
    if labware is None:
      self.fail(where, f"no labware called '{name}'; declared: {', '.join(self.labware) or 'none'}")
      return []
    for well in (first, last):
      if well is not None and well not in labware.order:
        self.fail(where, f"{name} ({labware.type}) has no well {well}")
        return []
    if last is None:
      return [Well(name, first)]
    (c0, r0), (c1, r1) = labware.position(first), labware.position(last)
    if c1 < c0 or r1 < r0:
      self.fail(where, f"a range runs from its top-left well to its bottom-right well; got {first}:{last}")
      return []
    return [Well(name, labware.at(c, r)) for c in range(c0, c1 + 1) for r in range(r0, r1 + 1)]  # type: ignore[arg-type]

  def one_well(self, value: Any, where: str) -> Optional[Well]:
    wells = self.wells(value, where)
    if len(wells) > 1:
      self.fail(where, f"expected a single well, got {len(wells)}")
      return None
    return wells[0] if wells else None

  def mixing(self, value: Any, where: str) -> Optional[Tuple[int, float]]:
    if value is None:
      return None
    body = self.keys(value, where, ("times", "volume"))
    times = self.count(body.get("times"), f"{where}.times") if "times" in body else None
    volume = self.volume(body.get("volume"), f"{where}.volume") if "volume" in body else None
    return (times, volume) if times is not None and volume is not None else None

  def tips(self, value: Any, where: str) -> str:
    if value not in ("fresh", "reuse"):
      self.fail(where, f"expected 'fresh' or 'reuse', got {value!r}")
      return "fresh"
    return value

  # ---- sections

  def read_labware(self, section: Any) -> None:
    import pylabrobot.resources as resources
    from pylabrobot.resources import Plate

    if not isinstance(section, dict) or not section:
      self.fail("labware", "expected at least one piece of labware")
      return
    for name, body in section.items():
      where = f"labware.{name}"
      body = self.keys(body, where, ("type",))
      maker = getattr(resources, str(body.get("type")), None)
      plate = None
      if callable(maker):
        try:
          with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            plate = maker(name=str(name))
        except Exception:
          plate = None
      if not isinstance(plate, Plate):
        if "type" in body:
          self.fail(f"{where}.type", f"{body.get('type')!r} is not a plate definition in PyLabRobot")
        continue
      wells = plate.get_all_items()
      self.labware[str(name)] = Labware(
        name=str(name),
        type=str(body["type"]),
        rows=plate.num_items_y,
        columns=plate.num_items_x,
        capacity=float(wells[0].max_volume),
        order=[w.get_identifier() for w in wells],
      )

  def read_liquids(self, section: Any) -> Dict[str, Tuple[List[Well], float]]:
    liquids: Dict[str, Tuple[List[Well], float]] = {}
    if section is None:
      return liquids
    if not isinstance(section, dict):
      self.fail("liquids", "expected a mapping of liquid names")
      return liquids
    for name, body in section.items():
      where = f"liquids.{name}"
      body = self.keys(body, where, ("in", "volume"))
      wells = self.wells(body.get("in"), f"{where}.in") if "in" in body else []
      volume = self.volume(body.get("volume"), f"{where}.volume") if "volume" in body else None
      if wells and volume is not None:
        liquids[str(name)] = (wells, volume)
    return liquids

  def read_samples(self, section: Any) -> Tuple[Dict[Well, float], str]:
    if section is None:
      return {}, ""
    body = self.keys(section, "samples", ("file", "labware", "well", "concentration", "unit"))
    if not all(k in body for k in ("file", "labware", "well", "concentration", "unit")):
      return {}, ""
    path = Path(str(body["file"]))
    if not path.is_absolute() and self.base is not None:
      path = self.base / path
    if not path.is_file():
      self.fail("samples.file", f"cannot find {body['file']} next to the protocol file")
      return {}, str(body["unit"])
    table: Dict[Well, float] = {}
    with path.open(newline="") as handle:
      rows = list(csv.DictReader(handle))
    for number, row in enumerate(rows, start=2):  # row 1 is the header
      where = f"samples.file row {number}"
      for column in (body["well"], body["concentration"]):
        if column not in row:
          self.fail("samples", f"{body['file']} has no column '{column}'")
          return {}, str(body["unit"])
      found = self.wells(f"{body['labware']}/{row[body['well']].strip()}", where)
      try:
        value = float(row[body["concentration"]])
      except ValueError:
        self.fail(where, f"concentration {row[body['concentration']]!r} is not a number")
        continue
      if found:
        table[found[0]] = value
    return table, str(body["unit"])

  def read_step(self, raw: Any, index: int) -> Optional[Step]:
    where = f"steps[{index}]"
    kinds = ("transfer", "mix", "serial_dilution", "normalize", "wait")
    if not isinstance(raw, dict) or len(raw) != 1 or next(iter(raw)) not in kinds:
      self.fail(where, f"expected exactly one of: {', '.join(kinds)}")
      return None
    kind, body = next(iter(raw.items()))
    where = f"{where}.{kind}"
    before = len(self.problems)

    if kind == "transfer":
      body = self.keys(body, where, ("from", "to", "volume"), ("tips", "mix_after"))
      source = self.wells(body.get("from"), f"{where}.from") if "from" in body else []
      if body.get("to") == "waste":  # thrown away: no labware or well to name
        destination = [WASTE]
        if "mix_after" in body:
          self.fail(f"{where}.mix_after", "liquid sent to waste cannot be mixed afterwards")
      else:
        destination = self.wells(body.get("to"), f"{where}.to") if "to" in body else []
      volume = self.volume(body.get("volume"), f"{where}.volume") if "volume" in body else None
      if source and destination and len(source) != 1 and len(destination) != 1 and len(source) != len(destination):
        self.fail(
          where,
          f"{len(source)} source wells and {len(destination)} destination wells do not pair up; "
          "use one source, one destination, or the same number of each",
        )
      step: Step = Transfer(
        source,
        destination,
        volume or 0.0,
        self.tips(body.get("tips", "fresh"), f"{where}.tips"),
        self.mixing(body.get("mix_after"), f"{where}.mix_after"),
      )
    elif kind == "mix":
      body = self.keys(body, where, ("wells", "volume", "times"))
      step = Mix(
        self.wells(body.get("wells"), f"{where}.wells") if "wells" in body else [],
        (self.volume(body.get("volume"), f"{where}.volume") if "volume" in body else None) or 0.0,
        (self.count(body.get("times"), f"{where}.times") if "times" in body else None) or 1,
      )
    elif kind == "serial_dilution":
      body = self.keys(body, where, ("start", "steps", "direction", "volume"), ("mix", "discard", "tips"))
      direction = body.get("direction")
      if "direction" in body and direction not in _DIRECTIONS:
        self.fail(f"{where}.direction", f"expected one of {', '.join(_DIRECTIONS)}, got {direction!r}")
      discard = body.get("discard", True)
      if not isinstance(discard, bool):
        self.fail(f"{where}.discard", f"expected true or false, got {discard!r}")
      step = SerialDilution(
        self.wells(body.get("start"), f"{where}.start") if "start" in body else [],
        (self.count(body.get("steps"), f"{where}.steps") if "steps" in body else None) or 1,
        direction if direction in _DIRECTIONS else "right",
        (self.volume(body.get("volume"), f"{where}.volume") if "volume" in body else None) or 0.0,
        self.mixing(body.get("mix"), f"{where}.mix"),
        bool(discard),
        self.tips(body.get("tips", "fresh"), f"{where}.tips"),
      )
    elif kind == "normalize":
      body = self.keys(body, where, ("from", "to", "diluent", "target", "final_volume"), ("mix",))
      for key in ("from", "to"):
        if key in body and body[key] not in self.labware:
          self.fail(f"{where}.{key}", f"no labware called {body[key]!r}")
      target = self.concentration(body.get("target"), f"{where}.target") if "target" in body else None
      diluent = self.one_well(body.get("diluent"), f"{where}.diluent") if "diluent" in body else None
      step = Normalize(
        str(body.get("from")),
        str(body.get("to")),
        diluent or WASTE,
        target[0] if target else 0.0,
        target[1] if target else "",
        (self.volume(body.get("final_volume"), f"{where}.final_volume") if "final_volume" in body else None) or 0.0,
        self.mixing(body.get("mix"), f"{where}.mix"),
      )
    else:  # wait
      body = self.keys(body, where, ("duration",))
      seconds = (
        self.quantity(body.get("duration"), f"{where}.duration", _TIME_UNITS, "duration")
        if "duration" in body
        else None
      )
      step = Wait(seconds or 0.0)

    return step if len(self.problems) == before else None


def load(source: Union[str, Path]) -> Protocol:
  """Read a protocol file. Raises ProtocolError listing every problem in it."""
  path = Path(source)
  return loads(path.read_text(), base=path.parent, path=path)


def loads(text: str, *, base: Optional[Path] = None, path: Optional[Path] = None) -> Protocol:
  """Read a protocol from YAML text. `base` is where a samples file is looked for."""
  reader = _Reader(base)
  try:
    raw = yaml.safe_load(text)
  except yaml.YAMLError as error:
    raise ProtocolError([Problem("file", f"not valid YAML: {error}")]) from error

  top = reader.keys(
    raw, "file", ("drybench", "name", "labware", "steps"), ("description", "notes", "liquids", "samples", "limits")
  )
  notes = top.get("notes", [])
  if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
    reader.fail("notes", "expected a list of sentences")
    notes = []
  if str(top.get("drybench")) != FORMAT_VERSION and "drybench" in top:
    reader.fail("drybench", f"this reader understands format {FORMAT_VERSION}, the file says {top['drybench']!r}")

  reader.read_labware(top.get("labware"))
  liquids = reader.read_liquids(top.get("liquids"))
  concentrations, unit = reader.read_samples(top.get("samples"))

  min_volume = 1.0
  if "limits" in top:
    limits = reader.keys(top["limits"], "limits", (), ("min_volume",))
    if "min_volume" in limits:
      min_volume = reader.volume(limits["min_volume"], "limits.min_volume") or min_volume

  steps: List[Step] = []
  if not isinstance(top.get("steps"), list) or not top.get("steps"):
    if "steps" in top:
      reader.fail("steps", "expected a list with at least one step")
  else:
    for index, raw_step in enumerate(top["steps"]):
      step = reader.read_step(raw_step, index)
      if step is not None:
        steps.append(step)

  if reader.problems:
    raise ProtocolError(reader.problems)
  return Protocol(
    name=str(top["name"]),
    description=str(top.get("description", "")),
    labware=reader.labware,
    liquids=liquids,
    concentrations=concentrations,
    concentration_unit=unit,
    min_volume=min_volume,
    steps=steps,
    path=path,
    notes=list(notes),
  )


# ---------------------------------------------------------------- expanding


def expand(protocol: Protocol) -> Tuple[List[Move], List[Problem]]:
  """Turn steps into plain moves. Returns the moves and any problem met while doing so."""
  moves: List[Move] = []
  problems: List[Problem] = []
  tip = -1

  def fresh() -> int:
    nonlocal tip
    tip += 1
    return tip

  def mix(index: int, well: Well, mixing: Optional[Tuple[int, float]], with_tip: int) -> None:
    if mixing is not None:
      moves.append(Move(index, "mix", source=well, volume=mixing[1], times=mixing[0], tip=with_tip))

  for index, step in enumerate(protocol.steps):
    where = f"steps[{index}]"

    if isinstance(step, Transfer):
      count = max(len(step.source), len(step.destination))
      sources = step.source * count if len(step.source) == 1 else step.source
      destinations = step.destination * count if len(step.destination) == 1 else step.destination
      by_source: Dict[Well, int] = {}
      for source, destination in zip(sources, destinations):
        if step.tips == "reuse":
          use = by_source.setdefault(source, fresh() if source not in by_source else by_source[source])
        else:
          use = fresh()
        moves.append(Move(index, "transfer", source, destination, step.volume, tip=use))
        mix(index, destination, step.mix_after, use)

    elif isinstance(step, Mix):
      for well in step.wells:
        moves.append(Move(index, "mix", source=well, volume=step.volume, times=step.times, tip=fresh()))

    elif isinstance(step, SerialDilution):
      # All series advance one dilution at a time, so that neighbouring rows can share a
      # multi-channel move. Each series keeps its own tip numbering.
      dx, dy = _DIRECTIONS[step.direction]
      series = []
      for start in step.start:
        labware = protocol.labware[start.labware]
        column, row = labware.position(start.well)
        if labware.at(column + dx * step.steps, row + dy * step.steps) is None:
          problems.append(
            Problem(f"{where}.serial_dilution", f"{step.steps} steps {step.direction} from {start} runs off the plate")
          )
          continue
        series.append({"labware": labware, "column": column, "row": row, "current": start, "tip": fresh()})
      for n in range(1, step.steps + 1):
        for one in series:
          name = one["labware"].at(one["column"] + dx * n, one["row"] + dy * n)
          following = Well(one["current"].labware, name)
          if step.tips == "fresh" and n > 1:
            one["tip"] = fresh()
          moves.append(Move(index, "transfer", one["current"], following, step.volume, tip=one["tip"]))
          mix(index, following, step.mix, one["tip"])
          one["current"] = following
      if step.discard:
        for one in series:
          moves.append(Move(index, "transfer", one["current"], WASTE, step.volume, tip=one["tip"]))

    elif isinstance(step, Normalize):
      if step.unit != protocol.concentration_unit:
        problems.append(
          Problem(
            f"{where}.normalize.target",
            f"the target is in {step.unit} but the samples table is in {protocol.concentration_unit or 'no unit'}",
          )
        )
        continue
      samples = [(well, c) for well, c in protocol.concentrations.items() if well.labware == step.source]
      if not samples:
        problems.append(Problem(f"{where}.normalize.from", f"the samples table has no rows for {step.source}"))
        continue
      plan = []
      for well, concentration in samples:
        target_well = Well(step.destination, well.well)
        if well.well not in protocol.labware[step.destination].order:
          problems.append(Problem(f"{where}.normalize.to", f"{step.destination} has no well {well.well}"))
          continue
        if concentration < step.target - EPS:
          problems.append(
            Problem(
              f"{where}.normalize",
              f"{well} is at {concentration:g} {step.unit}, below the target of {step.target:g}; "
              "it cannot be diluted up",
            )
          )
          continue
        sample = round(step.target * step.final_volume / concentration, 2)
        plan.append((well, target_well, sample, round(step.final_volume - sample, 2)))
      diluent_tip = fresh()  # diluent goes first into empty wells, so one tip serves them all
      for _, target_well, _, diluent in plan:
        if diluent > EPS:
          moves.append(Move(index, "transfer", step.diluent, target_well, diluent, tip=diluent_tip))
      for well, target_well, sample, _ in plan:
        use = fresh()
        moves.append(Move(index, "transfer", well, target_well, sample, tip=use))
        mix(index, target_well, step.mix, use)

    elif isinstance(step, Wait):
      moves.append(Move(index, "wait", seconds=step.seconds))

  return moves, problems


# ---------------------------------------------------------------- checking


@dataclass
class Check:
  protocol: Protocol
  moves: List[Move]
  problems: List[Problem]
  volumes: Dict[Well, float]  # uL in every well that holds liquid at the end
  drawn: Dict[Well, float]  # uL taken out of every well that a declared liquid started in
  tips: int
  wait_seconds: float = 0.0
  wasted: float = 0.0
  _liquid_of: Dict[Well, str] = field(default_factory=dict, repr=False)

  @property
  def ok(self) -> bool:
    return not self.problems

  def report(self) -> str:
    transfers = sum(1 for m in self.moves if m.kind == "transfer")
    mixes = sum(1 for m in self.moves if m.kind == "mix")
    lines = [
      f"drybench check: {'PASS' if self.ok else 'FAIL'}  {self.protocol.name}",
      f"  moves: {transfers} transfers, {mixes} mixes, {self.tips} tips",
    ]
    if self.wait_seconds:
      lines.append(f"  waiting: {self.wait_seconds / 60:g} min")
    by_liquid: Dict[str, float] = {}
    for well, volume in self.drawn.items():
      name = self._liquid_of.get(well)
      if name is not None:
        by_liquid[name] = by_liquid.get(name, 0.0) + volume
    for name, volume in by_liquid.items():
      wells, each = self.protocol.liquids[name]
      lines.append(f"  {name}: uses {volume:g} uL of {each * len(wells):g} uL supplied")
    if self.wasted:
      lines.append(f"  discarded: {self.wasted:g} uL")
    for note in self.protocol.notes:
      lines.append(f"  note: {note}")
    lines.append(f"  problems: {len(self.problems)}")
    lines += [f"    - {p}" for p in self.problems]
    return "\n".join(lines)


def check(protocol: Protocol) -> Check:
  """Follow the liquid through every move and report what does not add up."""
  moves, problems = expand(protocol)
  volumes: Dict[Well, float] = {}
  liquid_of: Dict[Well, str] = {}
  for name, (wells, volume) in protocol.liquids.items():
    for well in wells:
      volumes[well] = volumes.get(well, 0.0) + volume
      liquid_of[well] = name
  for name, (wells, volume) in protocol.liquids.items():
    for well in wells:
      capacity = protocol.labware[well.labware].capacity
      if volumes[well] > capacity + EPS:
        problems.append(
          Problem(f"liquids.{name}", f"{well} starts with {volumes[well]:g} uL but holds only {capacity:g} uL")
        )

  drawn: Dict[Well, float] = {}
  wasted = 0.0
  waiting = 0.0
  for move in moves:
    where = f"steps[{move.step}]"
    if move.kind == "wait":
      waiting += move.seconds
      continue
    assert move.source is not None
    if move.volume < protocol.min_volume - EPS:
      what = f"{move.source} to {move.destination}" if move.kind == "transfer" else f"mixing {move.source}"
      problems.append(
        Problem(where, f"{what}: {move.volume:g} uL is below the smallest volume allowed ({protocol.min_volume:g} uL)")
      )
      continue
    held = volumes.get(move.source, 0.0)
    if move.kind == "mix":
      if move.volume > held + EPS:
        problems.append(Problem(where, f"mixing {move.volume:g} uL in {move.source}, which holds {held:g} uL"))
      continue
    if move.volume > held + EPS:
      problems.append(
        Problem(where, f"takes {move.volume:g} uL from {move.source}, which holds {held:g} uL at that point")
      )
      continue
    volumes[move.source] = held - move.volume
    if move.source in liquid_of:
      drawn[move.source] = drawn.get(move.source, 0.0) + move.volume
    assert move.destination is not None
    if move.destination == WASTE:
      wasted += move.volume
      continue
    after = volumes.get(move.destination, 0.0) + move.volume
    capacity = protocol.labware[move.destination.labware].capacity
    if after > capacity + EPS:
      problems.append(
        Problem(where, f"fills {move.destination} to {after:g} uL, over its {capacity:g} uL capacity")
      )
    volumes[move.destination] = after

  problems = _merged(problems)
  tips = len({m.tip for m in moves if m.tip >= 0})
  return Check(
    protocol=protocol,
    moves=moves,
    problems=problems,
    volumes={w: round(v, 4) for w, v in volumes.items() if v > EPS},
    drawn=drawn,
    tips=tips,
    wait_seconds=waiting,
    wasted=wasted,
    _liquid_of=liquid_of,
  )
