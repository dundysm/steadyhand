"""Rehearse an Opentrons protocol somebody already has.

steadyhand's own path starts from a protocol file and plans it. This one starts from the other
end: a Python protocol written for an Opentrons Flex or OT-2 by a person, by Protocol Designer
or by a model. Opentrons' software analyses it (the same analysis its app runs when a protocol
is imported), which gives every command the robot would be sent. Those commands are then

* followed for liquid: what each well holds, what a tip draws and where it ends up, and
* replayed in the physics scene, on a deck built from the labware definitions the analysis names.

Opentrons' analysis says whether the robot would accept the protocol. It does not say whether a
well is asked for more than it holds, is filled past its rim, or is drawn from with the tip above
the liquid. That is what this adds.

Nothing here changes the protocol. What is not rehearsed is said by name: see `Imported.report`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .opentrons_robots import FLEX, OT2, OT2_SIMULATOR, Profile, _definitions
from .record import RecordingBackend, Step
from .replay import Rehearsal, rehearse

WASTE = "waste"  # the stand-in for the trash in the replay: a reservoir beside the deck
WASTE_TYPE = "nest_1_reservoir_195ml"
ROWS = "ABCDEFGHIJKLMNOP"

# The least each pipette is specified to move, in uL, by the start of the name Opentrons' analysis gives it.
_LEAST: Tuple[Tuple[str, float], ...] = (
  ("p10_", 1.0), ("p20_", 1.0), ("p50_single_flex", 1.0), ("p50_multi_flex", 1.0), ("p50_", 5.0),
  ("p300_single_gen2", 20.0), ("p300_multi_gen2", 20.0), ("p300_", 30.0),
  ("p1000_single_flex", 5.0), ("p1000_multi_flex", 5.0), ("p1000_", 100.0),
)  # fmt: skip

# Commands that move no liquid and need no place in the replay.
_PASSED_OVER = {
  "comment", "custom", "savePosition", "setRailLights", "setStatusBar", "prepareToAspirate", "configureForVolume",
  "touchTip", "loadLiquidClass", "verifyTipPresence", "getTipPresence", "getNextTip", "liquidProbe",
  "tryLiquidProbe", "reloadLabware", "loadLid", "loadLidStack", "setTipState",
}  # fmt: skip
# Commands that take a tip away from the well it was in: to the trash, to a point in space, or home.
_ELSEWHERE = {
  "home", "moveRelative", "moveToCoordinates", "moveToAddressableArea", "moveToAddressableAreaForDropTip", "retractAxis",
}  # fmt: skip


class ImportFailed(RuntimeError):
  """The protocol could not be analysed, or the analysis could not be read."""


@dataclass
class Placed:
  name: str  # what the replay calls it
  load_name: str
  slot: str
  body: Dict[str, Any]
  on: str = ""  # what stands between it and the deck: a module, an adapter, or both
  tips: bool = False
  trash: bool = False  # an OT-2's fixed trash, loaded as labware by older API levels


@dataclass(frozen=True)
class Act:
  kind: str  # "pick_up", "aspirate", "dispense", "drop", "return"
  mount: str
  labware: str = ""
  wells: Tuple[str, ...] = ()
  volume: float = 0.0  # uL of liquid per channel; air is left out
  height: float = 0.0  # mm the tip's end is above the well floor
  command: int = 0  # the command's place in the analysis, counting from 1


@dataclass
class Imported:
  """An Opentrons protocol as its analysis describes it, and what following its liquid found."""

  name: str
  profile: Profile
  api: str
  analysed_by: str
  labware: Dict[str, Placed]
  pipettes: Dict[str, Tuple[str, int]]  # mount -> (pipette, channels)
  acts: List[Act]
  commands: int
  counts: Counter
  declared: Dict[Tuple[str, str], float]  # (labware, well) -> uL the protocol says it starts with
  assumed: Dict[Tuple[str, str], float] = field(default_factory=dict)  # wells drawn from with no liquid declared
  problems: List[str] = field(default_factory=list)
  notes: List[str] = field(default_factory=list)
  errors: List[str] = field(default_factory=list)  # what Opentrons' analysis itself objected to
  stopped: str = ""  # why the commands were followed only part of the way, if so
  followed: int = 0  # how many commands were followed
  final: Dict[Tuple[str, str], float] = field(default_factory=dict)  # what every well holds after the run

  @property
  def ok(self) -> bool:
    return not (self.problems or self.errors or self.stopped)

  def start_volumes(self) -> Dict[str, float]:
    """Microlitres in every well before the first command, by the name its resource has in the replay."""
    start = {f"{labware}_well_{well}": volume for (labware, well), volume in self.assumed.items()}
    start.update({f"{labware}_well_{well}": volume for (labware, well), volume in self.declared.items()})
    return start

  def report(self) -> str:
    verdict = "OK" if self.ok else "FAIL"
    lines = [f"steadyhand import: {verdict}  {self.name}  ({self.profile.title}, API {self.api}, analysed by {self.analysed_by})"]
    for mount, (pipette, channels) in self.pipettes.items():
      lines.append(f"  {mount:<5} mount: {pipette}" + (f" ({channels} channels)" if channels > 1 else ""))
    for item in self.labware.values():
      lines.append(f"  slot {item.slot:>2}  {item.name} ({item.load_name})" + (f", on {item.on}" if item.on else ""))
    kinds = Counter(a.kind for a in self.acts)
    lines.append(
      f"  commands: {self.commands}, of which {kinds['aspirate']} draws and {kinds['dispense']} deliveries of liquid, "
      f"{kinds['pick_up']} tip pick-ups"
    )
    wells = len(self.declared)
    lines.append(f"  liquid the protocol declares: {wells} well{'s' if wells != 1 else ''}")
    if self.assumed:
      total = sum(self.assumed.values())
      lines.append(
        f"  wells drawn from with no liquid declared: {len(self.assumed)}. Each was given the least that keeps "
        f"every draw under the liquid, {total:,.0f} uL in all:"
      )
      shown = sorted(self.assumed.items(), key=lambda kv: -kv[1])[:8]
      lines += [f"    {labware}/{well}: {volume:,.1f} uL" for (labware, well), volume in shown]
      if len(self.assumed) > len(shown):
        lines.append(f"    and {len(self.assumed) - len(shown)} more, in report.json")
    lines += [f"  note: {text}" for text in self.notes]
    if self.stopped:
      lines.append(f"  followed {self.followed} of {self.commands} commands: {self.stopped}")
    if self.errors:
      lines.append(f"  Opentrons' analysis objects ({len(self.errors)}):")
      lines += [f"    - {text}" for text in self.errors]
    lines.append(f"  problems: {len(self.problems)}")
    lines += [f"    - {text}" for text in self.problems]
    return "\n".join(lines)

  def to_dict(self) -> Dict[str, Any]:
    return {
      "name": self.name,
      "robot": self.profile.title,
      "api": self.api,
      "analysed_by": self.analysed_by,
      "ok": self.ok,
      "commands": self.commands,
      "followed": self.followed,
      "stopped": self.stopped,
      "labware": [{"name": i.name, "load_name": i.load_name, "slot": i.slot, "on": i.on} for i in self.labware.values()],
      "pipettes": {mount: {"name": name, "channels": channels} for mount, (name, channels) in self.pipettes.items()},
      "declared": {f"{labware}/{well}": volume for (labware, well), volume in self.declared.items()},
      "assumed": {f"{labware}/{well}": round(volume, 2) for (labware, well), volume in self.assumed.items()},
      "problems": self.problems,
      "notes": self.notes,
      "errors": self.errors,
    }


# ---------------------------------------------------------------- Opentrons' analysis


def _interpreters() -> List[Tuple[str, str]]:
  """The Pythons that can analyse a protocol: this one, then the one kept for OT-2 protocols."""
  found = []
  if _definitions() is not None:
    found.append((sys.executable, "this environment"))
  older = os.environ.get(OT2_SIMULATOR, "")
  if older:
    beside = Path(older).parent / "python"
    if beside.exists():
      found.append((str(beside), f"the environment {OT2_SIMULATOR} names"))
  return found


def analyse(path: Path, labware: Sequence[Path] = (), timeout: float = 900.0) -> Tuple[Dict[str, Any], str]:
  """Have Opentrons' software analyse a protocol. Returns the analysis and the release that made it.

  `labware` is custom labware definitions the protocol loads, as files or folders.
  """
  interpreters = _interpreters()
  if not interpreters:
    raise ImportFailed("Opentrons' software is needed to analyse a protocol: pip install 'steadyhand[opentrons]'")
  said = ""
  path, labware = Path(path).resolve(), [Path(item).resolve() for item in labware]  # the analysis runs in a folder of its own
  if not path.exists():
    raise ImportFailed(f"{path} does not exist")
  for python, where in interpreters:
    with tempfile.TemporaryDirectory() as folder:
      out = Path(folder) / "analysis.json"
      command = [python, "-m", "opentrons.cli", "analyze", "--json-output", str(out), str(path), *map(str, labware)]
      try:
        ran = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=folder)
      except subprocess.TimeoutExpired:
        raise ImportFailed(f"Opentrons' analysis did not finish in {timeout:g} s") from None
      if out.exists() and out.stat().st_size:
        version = subprocess.run(
          [python, "-c", "import opentrons; print(opentrons.__version__)"], capture_output=True, text=True, cwd=folder
        ).stdout.strip()
        return json.loads(out.read_text()), f"opentrons {version}" if version else where
      said = (ran.stderr or ran.stdout).strip().splitlines()[-1] if (ran.stderr or ran.stdout).strip() else ""
      if "OT-2" not in said:
        break
  if "OT-2" in said:
    raise ImportFailed(
      "This is an OT-2 protocol, and current Opentrons releases analyse Flex protocols only. Install "
      f"opentrons==9.0.0 in a separate environment and set {OT2_SIMULATOR} to its opentrons_simulate."
    )
  raise ImportFailed(f"Opentrons' analysis gave nothing back: {said or 'no reason given'}")


# ---------------------------------------------------------------- reading it


def _slug(text: str) -> str:
  return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "labware"


def _definition(uri: str, custom: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
  """The labware definition a `namespace/load name/version` names: custom first, then what Opentrons ships."""
  if uri in custom:
    return custom[uri]
  namespace, load_name, version = (uri.split("/") + ["", "", ""])[:3]
  root = _definitions()
  if root is None or not re.fullmatch(r"[A-Za-z0-9_.\-]+", load_name):
    return None
  for schema in (root, root.parent / "3"):
    file = schema / load_name / f"{version}.json"
    if file.exists():
      return json.loads(file.read_text())
  return None


def custom_definitions(files: Sequence[Path]) -> Dict[str, Dict[str, Any]]:
  """Custom labware definitions found in `files` (files or folders), by `namespace/load name/version`."""
  found: Dict[str, Dict[str, Any]] = {}
  for given in files:
    for file in sorted(given.rglob("*.json")) if given.is_dir() else [given]:
      try:
        body = json.loads(file.read_text())
        uri = f"{body['namespace']}/{body['parameters']['loadName']}/{body['version']}"
      except (ValueError, KeyError, TypeError, OSError):
        continue
      found[uri] = body
  return found


def _channels(pipette: str) -> int:
  if "96" in pipette:
    return 96
  return 8 if ("multi" in pipette or "8channel" in pipette) else 1


def _least(pipette: str) -> float:
  return next((least for start, least in _LEAST if pipette.startswith(start)), 0.0)


def _wells_reached(body: Dict[str, Any], well: str, channels: int) -> Optional[Tuple[str, ...]]:
  """The wells an action at `well` reaches with this many channels; None when they do not fit the labware."""
  if channels == 1:
    return (well,)
  column = next((c for c in body["ordering"] if well in c), None)
  if column is None:
    return None
  rows = len(column)
  if rows == 1:
    return (well,) * 8  # eight channels in one trough well
  start = column.index(well)
  stride = {8: 1, 16: 2}.get(rows)
  if stride is None:
    return None
  reached = column[start::stride][:8]
  return tuple(reached) if len(reached) == 8 else None


def read(
  doc: Dict[str, Any], analysed_by: str = "Opentrons' analysis", custom: Optional[Dict[str, Dict[str, Any]]] = None
) -> Imported:
  """Turn an analysis into the actions the replay takes, and follow the liquid through them."""
  custom = custom or {}
  robot = doc.get("robotType") or ""
  profile = OT2 if "OT-2" in robot else FLEX
  metadata = doc.get("metadata") or {}
  api = str((doc.get("config") or {}).get("apiVersion") or metadata.get("apiLevel") or "")
  if isinstance((doc.get("config") or {}).get("apiVersion"), list):
    api = ".".join(str(n) for n in doc["config"]["apiVersion"])
  files = [f.get("name", "") for f in doc.get("files") or [] if f.get("role") == "main"]
  name = str(metadata.get("protocolName") or (files[0] if files else "an Opentrons protocol"))
  commands = doc.get("commands") or []
  result = Imported(
    name=name, profile=profile, api=api or "?", analysed_by=analysed_by, labware={}, pipettes={}, acts=[],
    commands=len(commands), counts=Counter(c.get("commandType", "?") for c in commands), declared={},
  )  # fmt: skip
  for error in doc.get("errors") or []:
    detail = error.get("detail") or error.get("errorType") or "an error with no description"
    result.errors.append(str(detail).strip().splitlines()[-1][:300])

  by_id: Dict[str, Placed] = {}
  modules: Dict[str, Tuple[str, str]] = {}  # module id -> (model, slot)
  adapters: Dict[str, Tuple[str, str, str]] = {}  # labware id of an adapter or of anything not built -> (what, slot, on)
  pipettes: Dict[str, Tuple[str, str, int]] = {}  # pipette id -> (mount, name, channels)
  state: Dict[str, Dict[str, Any]] = {}  # pipette id -> what its tips hold and where they are
  passed = Counter()
  air_draws = 0
  small: Counter = Counter()

  def stop(number: int, why: str) -> None:
    result.stopped = why
    result.followed = number - 1

  def place(location: Any) -> Optional[Tuple[str, str]]:
    """The deck slot a location comes down to, and what stands between it and the deck."""
    if not isinstance(location, dict):
      return None
    if "slotName" in location:
      return str(location["slotName"]), ""
    if "addressableAreaName" in location:
      return str(location["addressableAreaName"]), ""
    if "moduleId" in location and location["moduleId"] in modules:
      model, slot = modules[location["moduleId"]]
      return slot, model
    if "labwareId" in location and location["labwareId"] in adapters:
      what, slot, on = adapters[location["labwareId"]]
      return slot, f"{what} on {on}" if on else what
    return None

  def height(params: Dict[str, Any], item: Placed, well: str) -> float:
    where = params.get("wellLocation") or {}
    depth = float(item.body["wells"][well]["depth"])
    z = float((where.get("offset") or {}).get("z", 0.0))
    origin = where.get("origin", "top")
    if origin == "bottom":
      return z
    if origin == "center":
      return depth / 2 + z
    if origin == "meniscus":
      return -1.0  # worked out against the liquid when the action is recorded
    return depth + z

  for number, command in enumerate(commands, start=1):
    kind = command.get("commandType", "?")
    params = command.get("params") or {}
    made = command.get("result") or {}
    if command.get("status") == "failed" or (command.get("error") and not made):
      continue  # the analysis's own errors are reported above
    if kind == "loadModule":
      slot = str((params.get("location") or {}).get("slotName", "?"))
      modules[made.get("moduleId", "")] = (str(params.get("model", "a module")), slot)
      continue
    if kind == "loadPipette":
      channels = _channels(str(params.get("pipetteName", "")))
      pipettes[made.get("pipetteId", "")] = (str(params.get("mount", "left")), str(params.get("pipetteName", "")), channels)
      result.pipettes[str(params.get("mount", "left"))] = (str(params.get("pipetteName", "")), channels)
      state[made.get("pipetteId", "")] = {"tip": False, "liquid": 0.0, "air": 0.0, "at": None}
      continue
    if kind == "loadLabware":
      found = place(params.get("location"))
      identity = made.get("labwareId", "")
      if found is None:  # off the deck, or somewhere this does not follow
        adapters[identity] = (str(params.get("loadName", "labware")), "", "")
        continue
      slot, on = found
      uri = made.get("definitionUri") or f"{params.get('namespace')}/{params.get('loadName')}/{params.get('version')}"
      body = (made.get("definition") if isinstance(made.get("definition"), dict) else None) or _definition(uri, custom)
      load_name = str(params.get("loadName", ""))
      if body is None:
        adapters[identity] = (load_name, slot, on)
        result.notes.append(
          f"{load_name} in slot {slot} is not labware Opentrons ships; pass its definition with --labware to rehearse it"
        )
        continue
      category = (body.get("metadata") or {}).get("displayCategory", "")
      if category in ("adapter", "lid") or "adapter" in (body.get("allowedRoles") or []):
        adapters[identity] = (load_name, slot, on)
        continue
      label = _slug(str(params.get("displayName") or load_name))
      taken = {item.name for item in by_id.values()}
      if not body["parameters"].get("isTiprack") and re.search(r"waste|trash", label):
        # What the protocol calls waste is waste to the replay too: a draw that ends there is a removal.
        label = next(f"{WASTE}_{n}" for n in range(2, 99) if f"{WASTE}_{n}" not in taken)
      if label in taken:
        label = f"{label}_{_slug(slot)}"
      while label in taken:
        label += "_"
      by_id[identity] = Placed(
        label, load_name, slot, body, on,
        tips=bool(body["parameters"].get("isTiprack")), trash=category == "trash" or "trash" in load_name,
      )  # fmt: skip
      adapters[identity] = (load_name, slot, on)
      continue
    if kind == "loadLiquid":
      item = by_id.get(params.get("labwareId", ""))
      if item is not None:
        for well, volume in (params.get("volumeByWell") or {}).items():
          result.declared[(item.name, well)] = result.declared.get((item.name, well), 0.0) + float(volume)
      continue
    if result.stopped:
      continue
    if kind in _ELSEWHERE:  # the tip leaves whatever well it was in
      for held in state.values() if kind == "home" else [state.get(params.get("pipetteId", ""), {})]:
        held["at"] = None
      continue
    if kind in _PASSED_OVER:
      continue
    if kind in ("waitForDuration", "waitForResume", "delay", "pause"):
      passed["waits and pauses"] += 1
      continue
    if "/" in kind:  # a module's command: heaterShaker/..., thermocycler/..., temperatureModule/...
      passed[f"{kind.split('/')[0]} commands"] += 1
      continue
    if kind in ("moveLabware", "moveLid", "configureNozzleLayout", "flexStacker/retrieve", "flexStacker/store"):
      stop(number, f"command {number} is {kind}, which the replay does not follow yet")
      continue
    tool = pipettes.get(params.get("pipetteId", ""))
    if tool is None:
      passed[kind] += 1
      continue
    mount, pipette, channels = tool
    held = state[params["pipetteId"]]
    if channels == 96:
      stop(number, f"command {number} uses the 96-channel {pipette}, which the replay does not follow yet")
      continue

    def target() -> Optional[Tuple[Placed, str, Tuple[str, ...]]]:
      item = by_id.get(params.get("labwareId", ""))
      well = str(params.get("wellName", ""))
      if item is None or well not in item.body["wells"]:
        what = adapters.get(params.get("labwareId", ""), ("labware that was not loaded",))[0]
        stop(number, f"command {number} ({kind}) goes to {what}, which is not on the deck the replay built")
        return None
      reached = _wells_reached(item.body, well, channels)
      if reached is None:
        stop(number, f"command {number} ({kind}) sends {channels} channels to {item.name}/{well}, where they do not fit")
        return None
      return item, well, reached

    if kind == "pickUpTip":
      found = target()
      if found:
        item, well, reached = found
        result.acts.append(Act("pick_up", mount, item.name, reached, command=number))
        held.update(tip=True, liquid=0.0, air=0.0, at=None)
      continue
    if kind in ("dropTip", "dropTipInPlace"):
      item = by_id.get(params.get("labwareId", "")) if kind == "dropTip" else None
      if item is not None and item.tips:
        reached = _wells_reached(item.body, str(params.get("wellName", "")), channels)
        result.acts.append(Act("return", mount, item.name, reached or (), command=number))
      else:
        result.acts.append(Act("drop", mount, command=number))
      held.update(tip=False, liquid=0.0, air=0.0, at=None)
      continue
    if kind == "moveToWell":
      item = by_id.get(params.get("labwareId", ""))
      well = str(params.get("wellName", ""))
      held["at"] = None
      if item is not None and well in item.body["wells"] and not item.tips:
        reached = _wells_reached(item.body, well, channels)
        if reached is not None:
          held["at"] = (item, reached, height(params, item, well), item.trash)
      continue
    if kind in ("aspirate", "dispense", "blowout", "blowOut"):
      found = target()
      if not found:
        continue
      item, well, reached = found
      held["at"] = (item, reached, height(params, item, well), item.trash)
    elif kind in ("aspirateInPlace", "dispenseInPlace", "blowOutInPlace", "airGapInPlace"):
      pass  # wherever the tip already is; `at` is None over the trash
    else:
      passed[kind] += 1
      continue

    volume = float(params.get("volume", 0.0) or 0.0)
    at = held["at"]
    if kind == "airGapInPlace":
      held["air"] += volume
      continue
    if kind in ("aspirate", "aspirateInPlace"):
      depth = float(at[0].body["wells"][at[1][0]]["depth"]) if at else 0.0
      if at is None or at[3] or at[2] >= depth:  # over the trash, or at or above the rim of a well: air
        held["air"] += volume
        air_draws += 1
        continue
      if 0.0 < volume < _least(pipette):
        small[(pipette, volume)] += 1
      held["liquid"] += volume
      result.acts.append(Act("aspirate", mount, at[0].name, at[1], volume, at[2], number))
      continue
    # a dispense or a blow-out: the air under the liquid leaves first
    if kind in ("blowout", "blowOut", "blowOutInPlace"):
      out, held["air"] = held["liquid"], 0.0
    else:
      air = min(held["air"], volume)
      held["air"] -= air
      out = min(held["liquid"], volume - air)
    held["liquid"] -= out
    if out <= 1e-9:
      continue
    if at is None or at[3]:
      result.acts.append(Act("dispense", mount, WASTE, ("A1",) * channels, out, 0.0, number))
    else:
      result.acts.append(Act("dispense", mount, at[0].name, at[1], out, at[2], number))

  result.labware = {item.name: item for item in by_id.values() if not item.trash}
  if not result.stopped:
    result.followed = len(commands)
  for (pipette, volume), times in sorted(small.items()):
    result.problems.append(
      f"draws {volume:g} uL with the {pipette}, {times} time{'s' if times != 1 else ''}; that pipette is specified "
      f"for no less than {_least(pipette):g} uL"
    )
  if air_draws:
    result.notes.append(f"air gaps: {air_draws} draws of air, with the tip at or above the rim of a well or over the trash")
  if any(a.labware == WASTE for a in result.acts):
    result.notes.append(
      "liquid sent into the trash is shown going to a waste reservoir that stands beside the deck in the replay"
    )
  on_things = sorted({f"{item.name} on {item.on}" for item in result.labware.values() if item.on})
  if on_things:
    result.notes.append(
      "stands on a module or an adapter, which the replay draws at deck height and does not model: " + ", ".join(on_things)
    )
  if passed:
    result.notes.append("passed over, not rehearsed: " + ", ".join(f"{n} {what}" for what, n in sorted(passed.items())))
  return result


# ---------------------------------------------------------------- the deck, and the liquid


def build_deck(imported: Imported):
  """The deck the analysis describes, as PyLabRobot resources."""
  from pylabrobot.resources import Coordinate, Deck, Trash

  from .opentrons_scene import _TRASH, DECK_THICKNESS, SLOT, labware_resource, slot_origin

  profile = imported.profile
  (trash_x, trash_y), trash_size = _TRASH[profile.robot_type]
  wide = trash_x + trash_size[0] if profile.robot_type == "OT-2" else 328.0 + SLOT[0]
  with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    deck = Deck(
      size_x=wide,
      size_y=trash_y + trash_size[1] if profile.robot_type == "OT-2" else 321.0 + SLOT[1],
      size_z=DECK_THICKNESS,
      origin=Coordinate(0, 0, -DECK_THICKNESS),
    )
    deck.assign_child_resource(Trash("trash", *trash_size), location=Coordinate(trash_x, trash_y, DECK_THICKNESS))
    for item in imported.labware.values():
      x, y = slot_origin(profile, _slot(profile, item.slot))
      deck.assign_child_resource(
        labware_resource(item.load_name, item.name, item.body), location=Coordinate(x, y, DECK_THICKNESS)
      )
    if any(a.labware == WASTE for a in imported.acts):
      deck.assign_child_resource(
        labware_resource(WASTE_TYPE, WASTE), location=Coordinate(wide + 30.0, 0.0, DECK_THICKNESS)
      )
  return deck


def _slot(profile: Profile, slot: str) -> str:
  """A slot name the scene knows: a Flex staging or trash slot, or a slot the profile does not list, is used as it is."""
  if profile.robot_type == "OT-2":
    return slot if slot.isdigit() else "12"
  slot = slot[:2].upper() if len(slot) >= 2 else "A1"
  return slot if slot[0] in "ABCD" and slot[1] in "1234" else "A1"


def follow_liquid(imported: Imported, deck) -> None:
  """Follow every well's volume through the run, and say where the numbers do not add up.

  A well the protocol declares no liquid for and then draws from is given the least that keeps
  every draw under the liquid at the height the protocol draws from. A well it does declare is
  held to what was declared.
  """
  from .scene import liquid_height, liquid_volume

  def container(labware: str, well: str):
    return deck.get_resource(labware).get_item(well)

  # What each undeclared well needs: at every draw, what has left it so far, and what must stand under the tip.
  net: Dict[Tuple[str, str], float] = {}
  need: Dict[Tuple[str, str], float] = {}
  drawn = set()
  for act in imported.acts:
    if act.kind not in ("aspirate", "dispense") or act.labware == WASTE:
      continue
    for well in act.wells:
      key = (act.labware, well)
      if act.kind == "dispense":
        net[key] = net.get(key, 0.0) + act.volume
        continue
      drawn.add(key)
      net[key] = net.get(key, 0.0) - act.volume
      under = liquid_volume(container(*key), max(act.height, 0.0)) if act.height >= 0 else 0.0
      need[key] = max(need.get(key, 0.0), under - net[key])
  for key in sorted(drawn):
    if key in imported.declared:
      continue
    least = need.get(key, 0.0)
    if least > 1e-6:
      imported.assumed[key] = least * 1.01 + 1.0  # a little over, so a tip at the surface is under it

  held = {key: volume for key, volume in imported.assumed.items()}
  held.update(imported.declared)
  over, dry, full = set(), set(), set()
  for key, volume in sorted(held.items()):
    capacity = float(imported.labware[key[0]].body["wells"][key[1]]["totalLiquidVolume"])
    if volume > capacity * 1.005 and key not in full:
      full.add(key)
      what = "is declared to hold" if key in imported.declared else "would have to start with"
      imported.problems.append(f"{key[0]}/{key[1]} {what} {volume:,.1f} uL, and the well holds {capacity:,.0f} uL")
  resolved: List[Act] = []
  for act in imported.acts:
    if act.kind not in ("aspirate", "dispense") or act.labware == WASTE:
      resolved.append(act)
      continue
    tall = act.height
    for well in dict.fromkeys(act.wells):
      key = (act.labware, well)
      share = act.volume * act.wells.count(well)
      before = held.get(key, 0.0)
      if tall < 0:  # at the liquid's surface, as the analysis leaves it to the robot
        tall = max(0.1, liquid_height(container(*key), max(before - (share if act.kind == "aspirate" else 0.0), 0.0)))
      if act.kind == "aspirate":
        if share > before + 1e-6 and key not in dry:
          dry.add(key)
          imported.problems.append(
            f"command {act.command} draws {share:g} uL from {key[0]}/{key[1]}, which holds {max(before, 0.0):,.1f} uL then"
          )
        held[key] = before - share
      else:
        capacity = float(imported.labware[key[0]].body["wells"][key[1]]["totalLiquidVolume"])
        held[key] = before + share
        if held[key] > capacity * 1.005 and key not in over and key not in full:
          over.add(key)
          imported.problems.append(
            f"command {act.command} fills {key[0]}/{key[1]} to {held[key]:,.1f} uL, and the well holds {capacity:,.0f} uL"
          )
    resolved.append(act if tall == act.height else Act(act.kind, act.mount, act.labware, act.wells, act.volume, tall, act.command))
  imported.acts = resolved
  imported.final = held


async def record(imported: Imported, deck) -> List[Step]:
  """Send the actions to a recording backend on `deck`. Returns the steps it recorded."""
  from pylabrobot.liquid_handling import LiquidHandler
  from pylabrobot.resources import Coordinate, set_tip_tracking, set_volume_tracking

  from .opentrons_scene import PITCH

  # The liquid is followed by `follow_liquid` and by the replay, which report every place the
  # numbers do not add up. PyLabRobot's own tracking would stop at the first.
  set_volume_tracking(False)
  set_tip_tracking(True)
  channels: Dict[str, List[int]] = {}
  for mount in ("left", "right"):
    if mount in imported.pipettes:
      first = sum(len(c) for c in channels.values())
      channels[mount] = list(range(first, first + imported.pipettes[mount][1]))
  backend = RecordingBackend(num_channels=max(1, sum(len(c) for c in channels.values())))
  try:
    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      handler = LiquidHandler(backend=backend, deck=deck)
      await handler.setup()
      for act in imported.acts:
        use = channels[act.mount]
        try:
          if act.kind == "drop":
            await handler.discard_tips(use_channels=use)
            continue
          resource = deck.get_resource(act.labware)
          items = [resource.get_item(well) for well in act.wells]
          if act.kind == "pick_up":
            await handler.pick_up_tips(items, use_channels=use)
            continue
          if act.kind == "return":
            await handler.drop_tips(items, use_channels=use)
            continue
          together = len(items) > 1 and len(set(act.wells)) == 1
          offsets = [Coordinate(0, (3.5 - i) * PITCH if together else 0, 0) for i in range(len(items))]
          send = handler.aspirate if act.kind == "aspirate" else handler.dispense
          tall = max(act.height, 0.05) if act.labware != WASTE else 5.0
          await send(
            items, vols=[act.volume] * len(items), use_channels=use, liquid_height=[tall] * len(items),
            offsets=offsets, spread="custom",
          )  # fmt: skip
        except Exception as error:  # PyLabRobot's tip tracking said no
          imported.problems.append(f"command {act.command} ({act.kind} at {act.labware}): {error}")
          imported.stopped = f"the replay stops at command {act.command}, which PyLabRobot's tip tracking refuses"
          break
      await handler.stop()
  finally:
    set_volume_tracking(True)
  return backend.steps


def tallest(imported: Imported) -> float:
  from .opentrons_scene import _TRASH

  heights = [_TRASH[imported.profile.robot_type][1][2]]
  heights += [float(item.body["dimensions"]["zDimension"]) for item in imported.labware.values()]
  return max(heights)


async def rehearse_imported(imported: Imported, **options) -> Rehearsal:
  """Follow the liquid, then replay the actions in the physics scene."""
  from .opentrons_scene import CLEARANCE

  deck = build_deck(imported)
  follow_liquid(imported, deck)
  steps = await record(imported, deck)
  for (labware, well), volume in imported.final.items():  # so the report says what every well ends with
    item = deck.get_resource(labware).get_item(well)
    kept = min(max(volume, 0.0), float(item.max_volume))
    item.tracker.set_liquids([(None, kept)] if kept > 1e-9 else [])
  options.setdefault("traverse_z", tallest(imported) + CLEARANCE)
  options.setdefault("start_volumes", imported.start_volumes())
  return rehearse(deck, steps, **options)


def load(path: Path, labware: Sequence[Path] = ()) -> Imported:
  """Analyse a Python protocol, or read an analysis saved as JSON, and turn it into what the replay takes."""
  path = Path(path)
  custom = custom_definitions(list(labware))
  if path.suffix == ".json":
    try:
      doc = json.loads(path.read_text())
    except ValueError as error:
      raise ImportFailed(f"{path} is not JSON: {error}") from None
    if not isinstance(doc, dict) or "commands" not in doc or "robotType" not in doc:
      raise ImportFailed(f"{path} is not an analysis from Opentrons' software: it has no commands or no robotType")
    return read(doc, "a saved analysis", custom)
  doc, by = analyse(path, labware)
  return read(doc, by, custom)


__all__ = [
  "Act", "ImportFailed", "Imported", "Placed", "analyse", "build_deck", "custom_definitions", "follow_liquid",
  "load", "read", "record", "rehearse_imported",
]
