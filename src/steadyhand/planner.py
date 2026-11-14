"""Turn a checked protocol into commands a Hamilton STARlet can run.

The protocol says what to do. The plan adds how: which tips, which channels move together,
where every plate and tip rack sits on the deck. A plan is a flat list of commands (pick up
tips, aspirate, dispense, discard tips, wait, reload tips), and the same list is used three ways:

* `run` executes it on any PyLabRobot `LiquidHandler`;
* `rehearse_plan` executes it on a recording backend and replays it in the physics scene;
* `emit` writes it out as a PyLabRobot script.

Choices this planner makes, all deterministic:

* **Tips.** Each tip is the smallest filter tip that holds the largest volume it will carry.
  A transfer bigger than the largest tip is split into equal parts.
* **Channels.** Consecutive moves share an 8-channel command when their wells sit in one
  column at least 9 mm apart, or when they all draw from one well wide enough to take them.
* **Deck.** Tip carriers go on the left from rail 1, plate carriers after them, in file order.
* **Waste.** Discarded liquid goes to a reservoir named `waste`, which the planner adds; when it
  is nearly full the planner adds `waste_2`, and so on.
* **Tip reloads.** If the run needs more tip racks than fit beside the plates, the plan keeps what
  fits and stops for a person to swap in full racks each time a tip type runs out.

Three of these can be overridden. `dump_choices` writes the tips, the deck layout and the
pipetting height of a plan as a small YAML file; edit it and hand it back through
`load_choices` and `plan(checked, choices)`. Which channels move together is not a choice.
"""

from __future__ import annotations

import json
import math
import re
import warnings
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from .protocol import EPS, WASTE, Check, Move, Problem, Protocol, ProtocolError, Well, check
from .record import RecordingBackend
from .replay import Rehearsal, rehearse

CHANNELS = 8
CHANNEL_PITCH = 9.0  # mm; the closest two STAR channels can sit
CARRIER_RAILS = 6
DECK_RAILS = 30
SITES = 5
TIP_CARRIER = "TIP_CAR_480_A00"
PLATE_CARRIER = "PLT_CAR_L5AC_A00"
WASTE_TYPE = "nest_1_troughplate_195000uL_Vb"
CHANNEL_WIDTH = 8.0  # mm; a well narrower than this cannot take the channel itself, only the tip
PLATE_ADAPTER = "thermo_AB_96_plateadapter_MicroAmp"  # a base that holds PCR plates with no skirt

# Working volume in uL and the PyLabRobot definition, smallest first.
TIP_TYPES: List[Tuple[float, str]] = [
  (10.0, "hamilton_96_tiprack_10uL_filter"),
  (50.0, "hamilton_96_tiprack_50uL_filter"),
  (300.0, "hamilton_96_tiprack_300uL_filter"),
  (1000.0, "hamilton_96_tiprack_1000uL_filter"),
]


@dataclass(frozen=True)
class Command:
  kind: str  # "pick_up", "aspirate", "dispense", "discard", "wait", "pause" or "reload"
  channels: Tuple[int, ...]
  resource: str = ""  # the plate or tip rack; empty for "discard", "wait" and "reload"
  wells: Tuple[str, ...] = ()  # for "reload", the tip racks a person swaps for full ones
  volumes: Tuple[float, ...] = ()  # for "wait", the one number is seconds
  step: int = -1
  text: str = ""  # for "pause", what the person does
  surface: bool = False  # an aspirate that stays just under the liquid as it falls
  heights: Tuple[float, ...] = ()  # mm above the well floor for each channel, for an aspirate that follows the
  # surface or that the protocol gives a height of its own; empty for the usual pipetting height


SUBMERGED = 1.0  # mm a tip that follows the surface stays under it, measured when the draw is over


@dataclass(frozen=True)
class Placement:
  carrier: str  # resource name
  carrier_type: str
  rails: int
  sites: Tuple[Optional[str], ...]  # labware name on each site, front to back


@dataclass
class Choices:
  """What a person may decide in place of the planner. The defaults are the planner's own choices."""

  pipetting_height: float = 1.0  # mm above the well floor for every aspirate and dispense
  tip_types: List[Tuple[float, str]] = field(default_factory=lambda: list(TIP_TYPES))  # smallest first
  deck: Optional[List[Placement]] = None  # None lets the planner lay the deck out


@dataclass
class Plan:
  protocol: Protocol
  labware: Dict[str, str]  # every plate and tip rack on the deck -> PyLabRobot definition
  placements: List[Placement]
  commands: List[Command]
  tips: Dict[str, int]  # tip rack definition -> tips used
  problems: List[Problem] = field(default_factory=list)
  pipetting_height: float = 1.0  # mm above the well floor for every aspirate and dispense
  tip_types: List[Tuple[float, str]] = field(default_factory=lambda: list(TIP_TYPES))  # what it could choose from
  assumptions: List[str] = field(default_factory=list)  # what has to be true on the bench for the plan to hold
  longer_tips: List[str] = field(default_factory=list)  # where a longer tip was chosen than the volume alone asks for

  @property
  def ok(self) -> bool:
    return not self.problems

  def report(self) -> str:
    lines = [f"steadyhand plan: {'OK' if self.ok else 'FAIL'}  {self.protocol.name}"]
    for placement in self.placements:
      held = ", ".join(s for s in placement.sites if s)
      lines.append(f"  rails {placement.rails:>2}  {placement.carrier_type}: {held}")
    for definition, count in self.tips.items():
      lines.append(f"  tips: {count} x {definition}")
    kinds = [c.kind for c in self.commands]
    if "reload" in kinds:
      lines.append(f"  tip reloads: {kinds.count('reload')} (the run stops for a person to swap in full racks)")
    if "wait" in kinds:
      waited = sum(c.volumes[0] for c in self.commands if c.kind == "wait")
      lines.append(f"  waits: {kinds.count('wait')} ({waited / 60:g} min in all)")
    if "pause" in kinds:
      lines.append(f"  pauses: {kinds.count('pause')} (the run stops for a person to do a step by hand)")
    followed = [h for c in self.commands for h in c.heights]
    if followed:
      lines.append(
        f"  draws at a height of their own: {len(followed)}, the tip {min(followed):g} to {max(followed):g} mm above the well floor"
      )
    widest = max((len(c.channels) for c in self.commands), default=0)
    lines.append(
      f"  commands: {len(self.commands)} ({kinds.count('aspirate')} aspirates, "
      f"{kinds.count('dispense')} dispenses), up to {widest} channels at once"
    )
    lines += [f"  longer tips: {text}" for text in self.longer_tips]
    lines += [f"  assumes: {text}" for text in self.assumptions]
    if self.problems:
      lines.append(f"  problems: {len(self.problems)}")
      lines += [f"    - {p}" for p in self.problems]
    return "\n".join(lines)


# ---------------------------------------------------------------- geometry of labware


class _Geometry:
  """Row positions and well widths, read once from PyLabRobot for each labware definition."""

  def __init__(self) -> None:
    self._cache: Dict[str, Tuple[Dict[str, Tuple[int, float]], float]] = {}
    self._shared: Dict[str, int] = {}
    self._wells: Dict[str, Tuple[float, float]] = {}

  def _load(self, definition: str) -> Tuple[Dict[str, Tuple[int, float]], float]:
    if definition not in self._cache:
      import pylabrobot.resources as resources

      with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plate = getattr(resources, definition)(name="probe")
      rows = plate.num_items_y
      wells = {
        w.get_identifier(): (i // rows, w.get_absolute_location("c", "c", "b").y)
        for i, w in enumerate(plate.get_all_items())
      }
      self._cache[definition] = (wells, plate.get_all_items()[0].get_size_y())
    return self._cache[definition]

  def column_and_y(self, definition: str, well: str) -> Tuple[int, float]:
    return self._load(definition)[0][well]

  def depth_and_width(self, definition: str) -> Tuple[float, float]:
    """How deep a well of this labware is and how wide at its narrowest, in mm."""
    if definition not in self._wells:
      import pylabrobot.resources as resources

      with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        well = getattr(resources, definition)(name="probe").get_all_items()[0]
      self._wells[definition] = (well.get_size_z(), min(well.get_size_x(), well.get_size_y()))
    return self._wells[definition]

  def channels_in_one_well(self, definition: str) -> int:
    """How many channels PyLabRobot will put side by side in one well of this labware."""
    if definition not in self._shared:
      import pylabrobot.resources as resources
      from pylabrobot.liquid_handling.channel_positioning import compute_channel_offsets

      with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        well = getattr(resources, definition)(name="probe").get_all_items()[0]
        fits = 1
        for count in range(CHANNELS, 1, -1):
          try:
            compute_channel_offsets(well, count, spread="wide", channel_spacings=[CHANNEL_PITCH] * count)
          except Exception:
            continue
          fits = count
          break
      self._shared[definition] = fits
    return self._shared[definition]


_REFUSALS: Dict[str, Optional[str]] = {}
_LIDDED: Dict[str, bool] = {}
_ADAPTED: Dict[str, bool] = {}


class RunRefused(Exception):
  """PyLabRobot's own checks refused one of the plan's commands."""

  def __init__(self, number: int, command: "Command", reason: str):
    self.number, self.command, self.reason = number, command, reason
    where = f" at {command.resource}" if command.resource else ""
    super().__init__(f"PyLabRobot refused command {number} ({command.kind}{where}): {reason}")


def comes_with_lid(definition: str) -> bool:
  """Whether PyLabRobot builds this plate with its lid on."""
  if definition not in _LIDDED:
    import pylabrobot.resources as resources

    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      try:
        plate = getattr(resources, definition)(name="probe")
        _LIDDED[definition] = bool(getattr(plate, "has_lid", lambda: False)())
      except Exception:
        _LIDDED[definition] = False
  return _LIDDED[definition]


def carrier_refusal(definition: str) -> Optional[str]:
  """Why this PyLabRobot plate cannot go on the plate carrier, even on an adapter; None when it can."""
  if definition not in _REFUSALS:
    import pylabrobot.resources as resources
    from pylabrobot.resources import hamilton

    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      _ADAPTED[definition] = False
      try:
        carrier = getattr(hamilton, PLATE_CARRIER)(name="probe_carrier")
        carrier[0] = getattr(resources, definition)(name="probe")
        _REFUSALS[definition] = None
      except Exception as error:  # PyLabRobot says why in the message
        _REFUSALS[definition] = str(error)
        try:  # a plate with no skirt can still stand in an adapter that sits on the carrier
          adapter = getattr(resources, PLATE_ADAPTER)(name="probe_adapter")
          adapter.assign_child_resource(getattr(resources, definition)(name="probe"))
          getattr(hamilton, PLATE_CARRIER)(name="probe_carrier")[0] = adapter
          _REFUSALS[definition], _ADAPTED[definition] = None, True
        except Exception:
          pass
  return _REFUSALS[definition]


def needs_adapter(definition: str) -> bool:
  """Whether this plate goes on the carrier in a plate adapter because it has no skirt to stand on."""
  carrier_refusal(definition)
  return _ADAPTED[definition]


def _waste_capacity() -> float:
  """Microlitres the waste reservoir's one well holds, as PyLabRobot states it."""
  if "waste" not in _CAPACITY:
    import pylabrobot.resources as resources

    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      _CAPACITY["waste"] = float(getattr(resources, WASTE_TYPE)(name="probe").get_all_items()[0].max_volume)
  return _CAPACITY["waste"]


_CAPACITY: Dict[str, float] = {}


# ---------------------------------------------------------------- units of work


@dataclass
class _Unit:
  """One tip's worth of work on one channel: a transfer with its mixes, or a mix on its own."""

  step: int
  tip: int
  source: Well
  destination: Well  # the same as `source` for a mix on its own
  volume: float  # 0 for a mix on its own
  mix: Optional[Tuple[int, float]]  # (times, volume), done in `destination`
  surface: bool = False  # the transfer is drawn from just under the surface
  height: float = 0.0  # the transfer is drawn this many mm above the well floor; 0 for the usual height


def _units(moves: Sequence[Move]) -> Tuple[List[_Unit], Dict[int, List[Tuple[float, int, str]]]]:
  """The work, one tip's worth at a time, and the stops: unit index they come before -> waits and pauses in order.

  A stop is (seconds, step, text): a timed wait has no text, a pause for a person has no seconds.
  """
  units: List[_Unit] = []
  waits: Dict[int, List[Tuple[float, int, str]]] = {}
  for move in moves:
    if move.kind == "wait":
      here = waits.setdefault(len(units), [])
      if here and not move.text and not here[-1][2]:  # two timed waits in a row are one
        here[-1] = (here[-1][0] + move.seconds, here[-1][1], "")
      else:
        here.append((move.seconds, move.step, move.text))
      continue
    if move.kind == "transfer":
      assert move.source is not None and move.destination is not None
      units.append(
        _Unit(move.step, move.tip, move.source, move.destination, move.volume, None, move.surface, move.height)
      )
    elif move.kind == "mix":
      assert move.source is not None
      last = units[-1] if units else None
      joins = last and last.tip == move.tip and last.destination == move.source and last.mix is None and last.volume
      if joins and len(units) not in waits:  # a mix that comes after a wait stays after it
        last.mix = (move.times, move.volume)
      else:
        units.append(_Unit(move.step, move.tip, move.source, move.source, 0.0, (move.times, move.volume)))
  return units, waits


def send_waste(
  units: List[_Unit], taken, capacity: float, limit: Optional[int] = None
) -> Tuple[List[str], Optional[Problem], List[int]]:
  """Point every discarded volume at a waste reservoir: `waste`, then `waste_2` and so on.

  Each reservoir takes 90% of the `capacity` its one well holds. With a `limit`, no more than
  that many reservoirs are used: when the last is full they are all emptied by a person and
  filled again from the first.

  Returns the reservoirs to add, a problem when the protocol already uses one of those names,
  and the indexes of the units before which the reservoirs must be emptied.
  """
  if not any(unit.destination == WASTE for unit in units):
    return [], None, []
  if any(name == "waste" or name.startswith("waste_") for name in taken):
    problem = Problem("labware.waste", "names starting with 'waste' are kept for the planner's waste reservoirs")
    return [], problem, []
  room = 0.9 * capacity
  filled, fills, empties = 0.0, 1, []  # `fills` counts reservoirs filled so far, this one included
  along = 0  # how far into a run of discards from one step this unit is
  for index, unit in enumerate(units):
    if unit.destination != WASTE:
      along = 0
      continue
    if index and (units[index - 1].step != unit.step or units[index - 1].destination.labware[:5] != "waste"):
      along = 0
    ahead = unit.volume
    if along % 8 == 0:
      # Eight discards in a row can go down eight channels at once, but only into one reservoir:
      # start the next reservoir before such a group, not part-way through it.
      group = 0.0
      for other in units[index : index + 8]:
        if other.destination != WASTE or other.step != unit.step:
          break
        group += other.volume
      if group <= room:
        ahead = group
    if filled + ahead > room:
      fills += 1
      filled = 0.0
      if limit and (fills - 1) % limit == 0:
        empties.append(index)
    filled += unit.volume
    along += 1
    number = (fills - 1) % limit + 1 if limit else fills
    unit.destination = Well("waste" if number == 1 else f"waste_{number}", "A1")
  on_deck = min(fills, limit) if limit else fills
  return ["waste"] + [f"waste_{number}" for number in range(2, on_deck + 1)], None, empties


def plan(checked: Check, choices: Optional[Choices] = None) -> Plan:
  """Plan a protocol that has passed `check`. `choices` overrides the tips, the deck and the height."""
  protocol = checked.protocol
  choices = choices or Choices()
  tip_types = sorted(choices.tip_types)
  problems: List[Problem] = []
  geometry = _Geometry()
  units, waits = _units(checked.moves)

  labware = {name: item.type for name, item in protocol.labware.items()}
  for name, item in protocol.labware.items():
    if item.library != "pylabrobot":  # named the Opentrons way: use the same plate from PyLabRobot, if there is one
      from .opentrons_robots import TWINS

      same = [plr for plr, (opentrons, _) in TWINS.items() if opentrons == item.type]
      if same:
        labware[name] = same[0]
      else:
        problems.append(
          Problem(
            f"labware.{name}.type",
            f"{item.type} is an Opentrons definition and steadyhand knows no PyLabRobot one for the same plate; "
            "the Hamilton STARlet needs a PyLabRobot definition here",
          )
        )
  if problems:
    return Plan(protocol=protocol, labware=labware, placements=[], commands=[], tips={}, problems=problems)
  reservoirs, refused, _ = send_waste(units, labware, _waste_capacity())
  if refused is not None:
    return Plan(protocol=protocol, labware=labware, placements=[], commands=[], tips={}, problems=[refused])
  labware.update({name: WASTE_TYPE for name in reservoirs})

  for name, definition in labware.items():
    refusal = carrier_refusal(definition)
    if refusal:
      problems.append(Problem(f"labware.{name}", f"{definition} cannot sit on a {PLATE_CARRIER}: {refusal}"))

  def place(well: Well) -> Tuple[str, str]:
    return ("waste", "A1") if well == WASTE else (well.labware, well.well)

  # Tip type for every tip: the smallest that holds the most it will carry.
  largest: Dict[int, float] = {}
  for unit in units:
    carried = max(unit.volume, unit.mix[1] if unit.mix else 0.0)
    largest[unit.tip] = max(largest.get(unit.tip, 0.0), carried)
  # A tip also has to reach. The channel is wider than a narrow well, so in one the tip alone has to
  # span from the rim down to where it pipettes: a 10 uL tip cannot reach the floor of a deep well.
  reach = [_tip_reach(definition) for _, definition in tip_types]
  deepest: Dict[int, Tuple[float, str]] = {}  # tip -> how far below a narrow well's rim it goes, and where
  for unit in units:
    drawn = unit.height or choices.pipetting_height
    for well, height in ((unit.source, drawn), (unit.destination, choices.pipetting_height)):
      name = place(well)[0]
      if not hasattr(resources_module(), labware.get(name, "")):
        continue
      depth, width = geometry.depth_and_width(labware[name])
      if width + EPS >= CHANNEL_WIDTH:
        continue
      # The channel's end is rounded, as in the replay, so it sinks a little into the mouth of the well.
      sinks = CHANNEL_WIDTH / 2 - math.sqrt((CHANNEL_WIDTH / 2) ** 2 - (width / 2) ** 2)
      span = round(depth - height - sinks, 2)
      if span > deepest.get(unit.tip, (0.0, ""))[0]:
        deepest[unit.tip] = (span, name)
  tip_type: Dict[int, int] = {}
  stepped: Dict[Tuple[int, int, str], int] = {}  # (tip by volume, tip chosen, labware) -> tips
  out_of_reach: Dict[str, float] = {}
  for tip, volume in largest.items():
    fits = [i for i, (capacity, _) in enumerate(tip_types) if capacity + EPS >= volume]
    by_volume = fits[0] if fits else len(tip_types) - 1
    need, where = deepest.get(tip, (0.0, ""))
    reaches = [i for i in range(by_volume, len(tip_types)) if reach[i] is None or reach[i] + EPS >= need]
    tip_type[tip] = reaches[0] if reaches else len(tip_types) - 1
    if not reaches:
      out_of_reach[where] = max(out_of_reach.get(where, 0.0), need)
    elif reaches[0] != by_volume:
      key = (by_volume, reaches[0], where)
      stepped[key] = stepped.get(key, 0) + 1
  for where, need in out_of_reach.items():
    longest = max(length for length in reach if length is not None)
    problems.append(
      Problem(
        f"labware.{where}",
        f"no tip reaches: a tip has to span {need:g} mm in a well of {labware[where]}, which is narrower than "
        f"the channel, and the longest tip is {longest:g} mm below the channel. Use a shallower or wider plate",
      )
    )
  into = {name: max(depth for depth, where in deepest.values() if where == name) for _, name in deepest.values()}
  longer_tips = [
    f"{count} tip{'s are' if count > 1 else ' is'} {tip_types[chosen][0]:g} uL where {tip_types[by_volume][0]:g} uL "
    f"would hold the volume: a {tip_types[by_volume][0]:g} uL tip is {reach[by_volume]:g} mm long below the channel "
    f"and has to span {into[where]:g} mm in {where}, whose wells are narrower than the channel"
    for (by_volume, chosen, where), count in sorted(stepped.items())
  ]
  for unit in units:
    capacity = tip_types[tip_type[unit.tip]][0]
    if unit.mix and unit.mix[1] > capacity + EPS:
      problems.append(
        Problem(f"steps[{unit.step}]", f"mixing {unit.mix[1]:g} uL is more than the largest tip holds ({capacity:g} uL)")
      )

  last_use = {unit.tip: index for index, unit in enumerate(units)}

  def together(batch: List[_Unit], unit: _Unit) -> bool:
    """Can `unit` join `batch` as its next channel?"""
    first = batch[0]
    if len(batch) >= CHANNELS or unit.step != first.step or unit.mix != first.mix:
      return False
    if tip_type[unit.tip] != tip_type[first.tip] or bool(unit.volume) != bool(first.volume):
      return False
    for side in ("source", "destination"):
      wells = [place(getattr(u, side)) for u in batch + [unit]]
      if len({name for name, _ in wells}) != 1:
        return False
      definition = labware[wells[0][0]]
      if len(set(wells)) == 1:  # every channel in one well: it has to be wide enough
        if len(wells) > geometry.channels_in_one_well(definition):
          return False
        continue
      if len(set(wells)) != len(wells):
        return False
      spots = [geometry.column_and_y(definition, well) for _, well in wells]
      if len({column for column, _ in spots}) != 1:
        return False
      # Channel 0 is at the back, so each later well must be at least one pitch nearer the front.
      if any(a[1] - b[1] < CHANNEL_PITCH - 0.01 for a, b in zip(spots, spots[1:])):
        return False
    # No well may be filled by one channel and drawn from by another in the same command.
    sources = {place(u.source) for u in batch + [unit] if u.volume}
    destinations = {place(u.destination) for u in batch + [unit] if u.volume}
    return not (sources & destinations)

  batches: List[List[_Unit]] = []
  for unit in units:
    if batches and together(batches[-1], unit):
      batches[-1].append(unit)
    else:
      batches.append([unit])

  def build(limit: Optional[Dict[int, int]]) -> Tuple[List[Command], Dict[int, int], Dict[int, int]]:
    """The commands, with at most `limit` racks of each tip type on the deck; None for no limit."""
    # Tips are handed out down each column of a rack. A command that needs k tips takes k
    # neighbouring rows of one column, so a column's leftovers are skipped when too few remain.
    racks: Dict[int, int] = {}  # tip type -> the rack being used
    most: Dict[int, int] = {}  # tip type -> racks on the deck
    cursor: Dict[int, Tuple[int, int]] = {}  # tip type -> (column, row) of the next free tip
    used: Dict[int, int] = {}
    commands: List[Command] = []

    def take(kind: int, count: int) -> Tuple[str, Tuple[str, ...]]:
      column, row = cursor.get(kind, (0, 0))
      if kind not in racks:
        racks[kind] = 1
      if row + count > 8:
        column, row = column + 1, 0
      if column >= 12:
        if limit is not None and racks[kind] >= limit[kind]:
          # Every rack of this kind on the deck is used up: stop for a person to swap in full ones.
          names = tuple(f"tips_{tip_types[kind][0]:g}_{n}" for n in range(1, limit[kind] + 1))
          commands.append(Command("reload", (), wells=names))
          racks[kind] = 1
        else:
          racks[kind] += 1
        column, row = 0, 0
      cursor[kind] = (column, row + count)
      used[kind] = used.get(kind, 0) + count
      most[kind] = max(most.get(kind, 0), racks[kind])
      name = f"tips_{tip_types[kind][0]:g}_{racks[kind]}"
      return name, tuple(f"{'ABCDEFGH'[row + i]}{column + 1}" for i in range(count))

    holding: Dict[int, int] = {}  # channel -> the tip number it has on
    position = 0
    for batch in batches:
      commands.extend(_stops(waits.get(position, [])))
      channels = tuple(range(len(batch)))
      kind = tip_type[batch[0].tip]
      step = batch[0].step

      # A channel gives up its tip only when this command needs a different one on it. A channel
      # that sits this command out keeps its tip for later.
      stale = tuple(c for c in channels if c in holding and holding[c] != batch[c].tip)
      if stale:
        commands.append(Command("discard", stale, step=step))
        for c in stale:
          del holding[c]
      need = tuple(c for c in channels if c not in holding)
      if need:
        rack, spots = take(kind, len(need))
        commands.append(Command("pick_up", need, rack, spots, step=step))
        for c in need:
          holding[c] = batch[c].tip

      capacity = tip_types[kind][0]
      if batch[0].volume:
        parts = [max(1, math.ceil((u.volume - EPS) / capacity)) for u in batch]
        for cycle in range(max(parts)):
          active = [c for c in channels if cycle < parts[c]]
          volumes = tuple(_share(batch[c].volume, parts[c], cycle) for c in active)
          source, destination = place(batch[0].source)[0], place(batch[0].destination)[0]
          commands.append(
            Command(
              "aspirate", tuple(active), source, tuple(place(batch[c].source)[1] for c in active), volumes, step,
              surface=batch[0].surface,
              heights=(batch[0].height,) * len(active) if batch[0].height else (),
            )
          )
          commands.append(
            Command(
              "dispense", tuple(active), destination, tuple(place(batch[c].destination)[1] for c in active), volumes, step
            )
          )
      if batch[0].mix:
        times, volume = batch[0].mix
        resource = place(batch[0].destination)[0]
        wells = tuple(place(u.destination)[1] for u in batch)
        for _ in range(times):
          commands.append(Command("aspirate", channels, resource, wells, (volume,) * len(batch), step))
          commands.append(Command("dispense", channels, resource, wells, (volume,) * len(batch), step))

      position += len(batch)
      done = tuple(sorted(c for c in holding if last_use[holding[c]] < position))
      if done:
        commands.append(Command("discard", done, step=step))
        for c in done:
          del holding[c]

    commands.extend(_stops(waits.get(position, [])))  # after the last move
    return commands, most, used

  # First with as many racks as it takes. If they do not fit beside the plates, plan again with
  # what does fit and a stop to reload whenever a tip type runs out.
  commands, racks, used = build(None)
  plate_count = len(labware)
  sites = SITES * ((DECK_RAILS - CARRIER_RAILS * math.ceil(plate_count / SITES)) // CARRIER_RAILS)
  if sum(racks.values()) > sites >= len(racks):
    limit = {kind: 1 for kind in racks}
    spare = sites - len(racks)
    total = sum(racks.values())
    for kind in sorted(racks, key=lambda k: -racks[k]):  # share the rest by need, biggest first
      extra = min(spare, max(0, round(sites * racks[kind] / total) - 1), racks[kind] - 1)
      limit[kind] += extra
      spare -= extra
    for kind in sorted(racks, key=lambda k: -racks[k]):  # hand out what rounding left over
      extra = min(spare, racks[kind] - limit[kind])
      limit[kind] += extra
      spare -= extra
    commands, racks, used = build(limit)

  # Deck: tip carriers from rail 1, then plate carriers.
  tip_racks: List[str] = []
  for kind in sorted(racks):
    for number in range(1, racks[kind] + 1):
      name = f"tips_{tip_types[kind][0]:g}_{number}"
      labware[name] = tip_types[kind][1]
      tip_racks.append(name)
  plates = [name for name in labware if name not in tip_racks]

  placements: List[Placement] = []
  if choices.deck is not None:
    placements = list(choices.deck)
    problems += _deck_problems(placements, tip_racks, plates)
  else:
    rails = 1
    for label, carrier_type, items in (("tip_carrier", TIP_CARRIER, tip_racks), ("plate_carrier", PLATE_CARRIER, plates)):
      for number, start in enumerate(range(0, len(items), SITES), start=1):
        sites = tuple(items[start : start + SITES]) + (None,) * (SITES - len(items[start : start + SITES]))
        placements.append(Placement(f"{label}_{number}", carrier_type, rails, sites))
        rails += CARRIER_RAILS
    if rails - 1 > DECK_RAILS:
      tip_carriers = sum(1 for p in placements if p.carrier_type == TIP_CARRIER)
      problems.append(
        Problem(
          "labware",
          f"{tip_carriers} tip carriers ({len(tip_racks)} racks for {sum(used.values())} tips) and "
          f"{len(placements) - tip_carriers} plate carriers need {rails - 1} rails; a STARlet deck has {DECK_RAILS}. "
          "The planner cannot reload tips during a run",
        )
      )

  if not problems and any(c.surface for c in commands):
    commands, cannot = _follow_surface(
      Plan(protocol, labware, placements, commands, {}, [], choices.pipetting_height, tip_types), protocol
    )
    problems += cannot

  return Plan(
    protocol=protocol,
    labware=labware,
    placements=placements,
    commands=commands,
    tips={tip_types[kind][1]: count for kind, count in sorted(used.items())},
    problems=problems,
    pipetting_height=choices.pipetting_height,
    tip_types=tip_types,
    longer_tips=longer_tips,
    assumptions=[
      f"the lid is off {name} ({definition} comes with one)"
      for name, definition in labware.items()
      if comes_with_lid(definition)
    ]
    + [
      f"{name} stands in a {PLATE_ADAPTER} ({definition} has no skirt)"
      for name, definition in labware.items()
      if needs_adapter(definition)
    ],
  )


def _deck_problems(placements: List[Placement], tip_racks: List[str], plates: List[str]) -> List[Problem]:
  """What is wrong with a deck layout a person wrote, given the labware this plan needs on it."""
  problems: List[Problem] = []
  placed: Dict[str, str] = {}
  taken: Dict[int, str] = {}  # rail -> the carrier on it
  for index, placement in enumerate(placements):
    where = f"deck[{index}]"
    if placement.carrier in tip_racks or placement.carrier in plates:
      problems.append(Problem(f"{where}.carrier", f"'{placement.carrier}' is also the name of labware in this plan"))
    wanted = tip_racks if placement.carrier_type == TIP_CARRIER else plates
    for site, name in enumerate(placement.sites):
      if name is None:
        continue
      if name in placed:
        problems.append(Problem(f"{where}.sites[{site}]", f"'{name}' is already on {placed[name]}"))
      elif name not in tip_racks and name not in plates:
        problems.append(Problem(f"{where}.sites[{site}]", f"this plan has no labware named '{name}'"))
      elif name not in wanted:
        kind = "tip rack" if name in tip_racks else "plate"
        problems.append(Problem(f"{where}.sites[{site}]", f"'{name}' is a {kind}; it cannot sit on a {placement.carrier_type}"))
      placed.setdefault(name, placement.carrier)
    last = placement.rails + CARRIER_RAILS - 1
    if placement.rails < 1 or last > DECK_RAILS:
      problems.append(
        Problem(f"{where}.rails", f"a carrier is {CARRIER_RAILS} rails wide; from rail {placement.rails} it does not fit on rails 1 to {DECK_RAILS}")
      )
    for rail in range(placement.rails, last + 1):
      if rail in taken and taken[rail] != placement.carrier:
        problems.append(Problem(f"{where}.rails", f"overlaps {taken[rail]}, which covers rail {rail}"))
        break
      taken.setdefault(rail, placement.carrier)
  missing = [name for name in tip_racks + plates if name not in placed]
  if missing:
    problems.append(
      Problem("deck", f"nothing places {', '.join(missing)}; add them, or delete the deck section to have it laid out again")
    )
  return problems


# ---------------------------------------------------------------- choices a person can edit

CHOICES_VERSION = "0.1"
_LENGTH = re.compile(r"^\s*(-?[0-9]+(?:\.[0-9]+)?)\s*mm\s*$")
_VOLUME = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(uL|µL|μL|mL)\s*$")


def dump_choices(planned: Plan, *, source: str = "") -> str:
  """The tips, deck and pipetting height of a plan as a YAML file a person can edit."""
  lines = [
    f"# Choices steadyhand made for {source or planned.protocol.name}.",
    "# Edit this file and hand it back with --plan FILE. Delete a section to have it chosen again.",
    f'steadyhand_plan: "{CHOICES_VERSION}"',
    "",
    "# How far above the well floor the tip stops for every aspirate and dispense.",
    f"pipetting_height: {planned.pipetting_height:g} mm",
    "",
    "# Tip racks the planner may use. It takes the smallest that holds each volume.",
    "tips:",
    *[f"  - {{type: {definition}, capacity: {capacity:g} uL}}" for capacity, definition in planned.tip_types],
    "",
    "# Where everything sits. Rails count from the left; a carrier is 6 rails wide; sites run front to back.",
    "deck:",
  ]
  for placement in planned.placements:
    sites = ", ".join(name or "null" for name in placement.sites)
    lines += [
      f"  - carrier: {placement.carrier}",
      f"    type: {placement.carrier_type}",
      f"    rails: {placement.rails}",
      f"    sites: [{sites}]",
    ]
  return "\n".join(lines) + "\n"


def loads_choices(text: str) -> Choices:
  """Read a choices file. Raises ProtocolError listing everything wrong with it."""
  problems: List[Problem] = []

  def fail(where: str, message: str) -> None:
    problems.append(Problem(where, message))

  def keys(value: Any, where: str, required: Tuple[str, ...], optional: Tuple[str, ...] = ()) -> dict:
    if not isinstance(value, dict):
      fail(where, f"expected a mapping with {', '.join(required + optional)}")
      return {}
    for key in value:
      if key not in required + optional:
        fail(f"{where}.{key}", f"unknown field; allowed here: {', '.join(required + optional)}")
    for key in required:
      if key not in value:
        fail(where, f"missing required field '{key}'")
    return value

  try:
    data = yaml.safe_load(text)
  except yaml.YAMLError as error:
    raise ProtocolError([Problem("plan file", f"not valid YAML: {error}")]) from error
  top = keys(data, "plan file", ("steadyhand_plan",), ("pipetting_height", "tips", "deck"))
  if "steadyhand_plan" in top and str(top["steadyhand_plan"]) != CHOICES_VERSION:
    fail("steadyhand_plan", f"this steadyhand reads plan files of version {CHOICES_VERSION}, got {top['steadyhand_plan']!r}")
  choices = Choices()

  if "pipetting_height" in top:
    match = _LENGTH.match(top["pipetting_height"]) if isinstance(top["pipetting_height"], str) else None
    if match is None:
      fail("pipetting_height", f"expected a height such as '1 mm', got {top['pipetting_height']!r}")
    elif float(match.group(1)) < 0:
      fail("pipetting_height", "a height below the well floor would drive the tip into the plate")
    else:
      choices.pipetting_height = float(match.group(1))

  if "tips" in top:
    tip_types: List[Tuple[float, str]] = []
    if not isinstance(top["tips"], list) or not top["tips"]:
      fail("tips", "expected a list with at least one tip rack")
    else:
      for index, entry in enumerate(top["tips"]):
        where = f"tips[{index}]"
        body = keys(entry, where, ("type", "capacity"))
        match = _VOLUME.match(body["capacity"]) if isinstance(body.get("capacity"), str) else None
        if "capacity" in body and match is None:
          fail(f"{where}.capacity", f"expected a volume such as '300 uL', got {body['capacity']!r}")
        capacity = float(match.group(1)) * (1000.0 if match.group(2) == "mL" else 1.0) if match else None
        holds = _tip_rack_holds(body.get("type")) if "type" in body else None
        if "type" in body and holds is None:
          fail(f"{where}.type", f"{body['type']!r} is not a 96-tip rack PyLabRobot knows")
        if capacity is not None and holds is not None:
          if capacity <= 0 or capacity > holds + EPS:
            fail(f"{where}.capacity", f"PyLabRobot says this tip holds at most {holds:g} uL")
          elif any(abs(capacity - other) < EPS for other, _ in tip_types):
            fail(f"{where}.capacity", f"another tip rack in this list already has capacity {capacity:g} uL")
          else:
            tip_types.append((capacity, body["type"]))
      if tip_types:
        choices.tip_types = sorted(tip_types)

  if "deck" in top:
    deck: List[Placement] = []
    names: List[str] = []
    if not isinstance(top["deck"], list) or not top["deck"]:
      fail("deck", "expected a list with at least one carrier")
    else:
      for index, entry in enumerate(top["deck"]):
        where = f"deck[{index}]"
        body = keys(entry, where, ("carrier", "type", "rails", "sites"))
        name, kind, rails, sites = body.get("carrier"), body.get("type"), body.get("rails"), body.get("sites")
        if "carrier" in body and (not isinstance(name, str) or not name.isidentifier() or name in names):
          fail(f"{where}.carrier", "expected a name of letters, digits and _ that no other carrier has")
        if "type" in body and kind not in (TIP_CARRIER, PLATE_CARRIER):
          fail(f"{where}.type", f"expected {TIP_CARRIER} or {PLATE_CARRIER}, got {kind!r}")
        if "rails" in body and (not isinstance(rails, int) or isinstance(rails, bool)):
          fail(f"{where}.rails", f"expected a whole number, got {rails!r}")
        if "sites" in body and not (
          isinstance(sites, list) and len(sites) <= SITES and all(s is None or isinstance(s, str) for s in sites)
        ):
          fail(f"{where}.sites", f"expected up to {SITES} labware names, with null for an empty site")
          sites = None
        names.append(name if isinstance(name, str) else "")
        if isinstance(sites, list) and isinstance(rails, int):
          deck.append(Placement(str(name), str(kind), rails, tuple(sites) + (None,) * (SITES - len(sites))))
      choices.deck = deck

  if problems:
    raise ProtocolError(problems)
  return choices


def load_choices(path) -> Choices:
  from pathlib import Path

  return loads_choices(Path(path).read_text(encoding="utf-8"))


def _share(volume: float, parts: int, part: int) -> float:
  """One of `parts` equal shares of `volume`; the last takes up the rounding, so they add up to it exactly."""
  each = round(volume / parts, 4)
  return each if part < parts - 1 else round(volume - each * (parts - 1), 4)


def _stops(stops: Sequence[Tuple[float, int, str]]) -> List[Command]:
  return [
    Command("pause", (), text=text, step=step) if text else Command("wait", (), volumes=(seconds,), step=step)
    for seconds, step, text in stops
  ]


def resources_module() -> Any:
  import pylabrobot.resources as resources

  return resources


_REACH: Dict[str, Optional[float]] = {}


def _tip_reach(definition: str) -> Optional[float]:
  """How many mm of a tip of this PyLabRobot rack hang below the channel, or None when that is not known."""
  if definition not in _REACH:
    maker = getattr(resources_module(), definition, None)
    try:
      with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tip = maker(name="probe").get_item("A1").get_tip()
      _REACH[definition] = round(float(tip.total_tip_length - tip.fitting_depth), 2)
    except Exception:
      _REACH[definition] = None
  return _REACH[definition]


def _tip_rack_holds(definition: Any) -> Optional[float]:
  """The most one tip of this PyLabRobot rack holds in uL, or None when it is not a 96-tip rack."""
  import pylabrobot.resources as resources

  maker = getattr(resources, definition, None) if isinstance(definition, str) else None
  if not callable(maker):
    return None
  try:
    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      rack = maker(name="probe")
      if not isinstance(rack, resources.TipRack) or (rack.num_items_x, rack.num_items_y) != (12, 8):
        return None
      return float(rack.get_item("A1").get_tip().maximal_volume)
  except Exception:
    return None


# ---------------------------------------------------------------- running a plan


def _real_shape(plate, definition: str) -> None:
  """Where Opentrons ships the same plate with its inside shape, use that shape for liquid height.

  PyLabRobot's own height for a tapered well is often a straight-walled estimate. This needs
  Opentrons' labware definitions; without them the plate is left as it is.
  """
  from .opentrons_robots import TWINS, opentrons_installed

  if definition in TWINS and opentrons_installed():
    from .opentrons_scene import give_real_shape

    give_real_shape(plate, TWINS[definition][0])


def build_deck(planned: Plan):
  """The PyLabRobot deck the plan describes, with the protocol's starting liquids in place."""
  import pylabrobot.resources as resources
  from pylabrobot.resources import hamilton

  with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    deck = hamilton.STARLetDeck()
    for placement in planned.placements:
      carrier = getattr(hamilton, placement.carrier_type)(name=placement.carrier)
      for site, name in enumerate(placement.sites):
        if name is not None:
          item = getattr(resources, planned.labware[name])(name=name)
          if getattr(item, "has_lid", lambda: False)():  # the plan assumes lids are off; it cannot move them
            item.unassign_child_resource(item.lid)
          _real_shape(item, planned.labware[name])
          if needs_adapter(planned.labware[name]):
            adapter = getattr(resources, PLATE_ADAPTER)(name=f"{name}_adapter")
            adapter.assign_child_resource(item)
            item = adapter
          carrier[site] = item
      deck.assign_child_resource(carrier, rails=placement.rails)
  for wells, volume in planned.protocol.liquids.values():
    for well in wells:
      deck.get_resource(well.labware).get_item(well.well).tracker.set_liquids([(None, volume)])
  return deck


def _follow_surface(planned: Plan, protocol) -> Tuple[List[Command], List[Problem]]:
  """Give every aspirate that follows the surface its height above the well floor, channel by channel.

  The tip stops `SUBMERGED` mm under where the liquid stands once the whole command has drawn,
  and never lower than the usual pipetting height. That takes the liquid height, so the inside
  shape of the well has to be known.
  """
  from .scene import liquid_height, liquid_height_is_known

  deck = build_deck(planned)
  held: Dict[Tuple[str, str], float] = {}
  for wells, volume in protocol.liquids.values():
    for well in wells:
      held[(well.labware, well.well)] = volume
  problems: List[Problem] = []
  refused = set()
  commands: List[Command] = []
  for command in planned.commands:
    if command.kind in ("aspirate", "dispense"):
      sign = -1 if command.kind == "aspirate" else 1
      for well, volume in zip(command.wells, command.volumes):
        held[(command.resource, well)] = held.get((command.resource, well), 0.0) + sign * volume
    if command.kind == "aspirate" and command.surface:
      heights = []
      for well in command.wells:
        container = deck.get_resource(command.resource).get_item(well)
        if not liquid_height_is_known(container):
          if (command.step, command.resource) not in refused:
            refused.add((command.step, command.resource))
            problems.append(
              Problem(
                f"steps[{command.step}].draw_from",
                f"cannot follow the surface in {command.resource} ({planned.labware[command.resource]}): the inside "
                "shape of its wells is not known, so neither is the height of the liquid. Use a flat-bottom plate there",
              )
            )
          heights.append(planned.pipetting_height)
          continue
        after = liquid_height(container, max(0.0, held[(command.resource, well)]))
        heights.append(round(max(planned.pipetting_height, after - SUBMERGED), 2))
      command = replace(command, heights=tuple(heights))
    commands.append(command)
  return commands, problems


async def run(planned: Plan, handler, *, on_reload=None, on_wait=None) -> None:
  """Send every command in the plan to a PyLabRobot LiquidHandler.

  At a tip reload, `on_reload` is called with the names of the racks to swap; give one that
  waits for the operator when running on a robot. The racks are then counted as full again.
  At a wait, `on_wait` is awaited with the seconds to wait; with none given the run does not
  pause, which is what a rehearsal wants.
  """
  deck = handler.deck
  height = planned.pipetting_height
  for number, command in enumerate(planned.commands, start=1):
    if command.kind == "reload":
      if on_reload is not None:
        on_reload(command.wells)
      for name in command.wells:
        deck.get_resource(name).fill()
      continue
    if command.kind == "wait":
      if on_wait is not None:
        await on_wait(command.volumes[0])
      continue
    if command.kind == "pause":
      continue
    try:
      await _send(command, handler, deck, height)
    except Exception as error:  # a tracker or a check inside PyLabRobot said no
      raise RunRefused(number, command, str(error)) from error


async def _send(command: Command, handler, deck, height: float) -> None:
  channels = list(command.channels)
  if command.kind == "discard":
    await handler.discard_tips(use_channels=channels)
    return
  resource = deck.get_resource(command.resource)
  items = [resource.get_item(well) for well in command.wells]
  if command.kind == "pick_up":
    await handler.pick_up_tips(items, use_channels=channels)
  elif command.kind == "aspirate":
    await handler.aspirate(
      items,
      vols=list(command.volumes),
      use_channels=channels,
      liquid_height=list(command.heights) if command.heights else [height] * len(items),
    )
  else:
    await handler.dispense(
      items, vols=list(command.volumes), use_channels=channels, liquid_height=[height] * len(items)
    )


async def record_plan(planned: Plan, *, prepare=None):
  """Run the plan on a recording backend. Returns the deck it ran on and the steps it recorded.

  `prepare`, if given, is called with the deck before the run, to change what is on it.
  """
  from pylabrobot.liquid_handling import LiquidHandler
  from pylabrobot.resources import set_tip_tracking, set_volume_tracking

  set_volume_tracking(True)
  set_tip_tracking(True)
  deck = build_deck(planned)
  if prepare is not None:
    prepare(deck)
  backend = RecordingBackend(num_channels=CHANNELS)
  with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    handler = LiquidHandler(backend=backend, deck=deck)
    await handler.setup()
    await run(planned, handler)
    await handler.stop()
  return deck, backend.steps


async def rehearse_plan(planned: Plan, **options) -> Rehearsal:
  """Run the plan on a recording backend and replay it in the physics scene."""
  deck, steps = await record_plan(planned)
  return rehearse(deck, steps, **options)


# ---------------------------------------------------------------- writing a script


def emit(planned: Plan, *, source: str = "") -> str:
  """The plan as a PyLabRobot script that runs on its own."""
  from . import __version__

  definitions = sorted(set(planned.labware.values()) | ({PLATE_ADAPTER} if any(map(needs_adapter, planned.labware.values())) else set()))
  carriers = sorted({p.carrier_type for p in planned.placements})
  lines = [
    f'"""{planned.protocol.name}',
    "",
    f"Written by steadyhand {__version__}" + (f" from {source}." if source else "."),
    "Change the protocol file and write this again; edits made here are lost.",
    '"""',
    "",
    "import asyncio",
    "",
    "from pylabrobot.liquid_handling import LiquidHandler",
    "from pylabrobot.liquid_handling.backends import LiquidHandlerChatterboxBackend",
    "from pylabrobot.resources import (",
    *[f"  {name}," for name in definitions],
    ")",
    f"from pylabrobot.resources.hamilton import {', '.join(carriers + ['STARLetDeck'])}",
    "",
    f"HEIGHT = {planned.pipetting_height!r}  # mm above the well floor for every aspirate and dispense",
    "",
    "",
    "def in_adapter(plate):",
    "  # A plate with no skirt stands in an adapter, and the adapter goes on the carrier.",
    f'  adapter = {PLATE_ADAPTER}(name=plate.name + "_adapter")',
    "  adapter.assign_child_resource(plate)",
    "  return adapter",
    "",
    "",
    "def lid_off(plate):",
    "  # The plan assumes lids are off before the run; it cannot move them.",
    "  if plate.has_lid():",
    "    plate.unassign_child_resource(plate.lid)",
    "  return plate",
    "",
    "",
    "def build_deck():",
    "  deck = STARLetDeck()",
  ]
  for placement in planned.placements:
    lines.append(f'  {placement.carrier} = {placement.carrier_type}(name="{placement.carrier}")')
    for site, name in enumerate(placement.sites):
      if name is not None:
        made = f'{planned.labware[name]}(name="{name}")'
        if comes_with_lid(planned.labware[name]):
          made = f"lid_off({made})"
        if needs_adapter(planned.labware[name]):
          made = f"in_adapter({made})"
        lines.append(f"  {placement.carrier}[{site}] = {made}")
    lines.append(f"  deck.assign_child_resource({placement.carrier}, rails={placement.rails})")
  lines += [
    "  return deck",
    "",
    "",
    "def reload(deck, names):",
    "  # The deck does not hold enough tips for the whole run, so it stops here for full racks.",
    '  input(f"Swap in full tip racks for {names}, then press Enter. ")',
    "  for name in names.split():",
    "    deck.get_resource(name).fill()",
    "",
    "",
    "async def wait(lh, seconds):",
    "  # A timed step. Kept on a robot; skipped when this only prints what it would do.",
    "  if not isinstance(lh.backend, LiquidHandlerChatterboxBackend):",
    "    await asyncio.sleep(seconds)",
    "",
    "",
    "def pause(lh, text):",
    "  # A step a person does by hand. Skipped when this only prints what it would do.",
    "  if not isinstance(lh.backend, LiquidHandlerChatterboxBackend):",
    '    input(f"{text} Then press Enter. ")',
    "",
    "",
    "def wells(deck, resource, names):",
    "  return [deck.get_resource(resource).get_item(name) for name in names.split()]",
    "",
    "",
    "async def protocol(lh):",
    "  deck = lh.deck",
  ]
  step = None
  for command in planned.commands:
    if command.step != step:
      step = command.step
      lines.append(f"  # step {step}")
    channels = list(command.channels)
    if command.kind == "reload":
      lines.append(f'  reload(deck, "{" ".join(command.wells)}")')
      continue
    if command.kind == "wait":
      lines.append(f"  await wait(lh, {command.volumes[0]:g})  # {command.volumes[0] / 60:g} min")
      continue
    if command.kind == "pause":
      lines.append(f"  pause(lh, {json.dumps(command.text)})")
      continue
    if command.kind == "discard":
      lines.append(f"  await lh.discard_tips(use_channels={channels})")
      continue
    picked = f'wells(deck, "{command.resource}", "{" ".join(command.wells)}")'
    if command.kind == "pick_up":
      lines.append(f"  await lh.pick_up_tips({picked}, use_channels={channels})")
    else:
      if command.heights:
        why = "just under the surface" if command.surface else "the height this step asks for"
        height = f"liquid_height={list(command.heights)})  # {why}"
      else:
        height = f"liquid_height=[HEIGHT] * {len(channels)})"
      lines.append(
        f"  await lh.{command.kind}({picked}, vols={list(command.volumes)}, use_channels={channels}, {height}"
      )
  lines += [
    "",
    "",
    "async def main(backend=None):",
    "  # With no backend given this only prints what it would do. To run on a robot, pass the",
    "  # backend for it, for example STAR() from pylabrobot.liquid_handling.backends.",
    "  backend = backend or LiquidHandlerChatterboxBackend(num_channels=8)",
    "  lh = LiquidHandler(backend=backend, deck=build_deck())",
    "  await lh.setup()",
    "  await protocol(lh)",
    "  await lh.stop()",
    "",
    "",
    'if __name__ == "__main__":',
    "  asyncio.run(main())",
    "",
  ]
  return "\n".join(lines)


def plan_file(path, choices=None) -> Tuple[Check, Optional[Plan]]:
  """Read, check and plan a protocol file. `choices` is a plan file to apply. The plan is None when the check fails."""
  from .protocol import load

  checked = check(load(path))
  chosen = load_choices(choices) if choices is not None else None
  return checked, (plan(checked, chosen) if checked.ok else None)
