"""Plan a checked protocol for an Opentrons Flex or OT-2 and write it as an Opentrons protocol.

These robots are driven through Opentrons' own Python API, not through PyLabRobot. The plan is
a flat list of actions for one or two pipettes, and it is used two ways:

* `emit` writes it as a protocol file the Opentrons App or `opentrons_execute` runs;
* `simulate` hands that file to Opentrons' own simulator and reports what it said.

Choices this planner makes, all deterministic:

* **Pipettes.** Up to two, one per mount: the pair that moves every volume in the fewest draws.
  Each tip's work goes to the smallest pipette that does it without extra draws.
* **Eight channels.** Eight moves in a row that fill or empty one whole column of an 8-row plate
  with the same volume are one move of an 8-channel pipette, when the pair has one. Its source
  may be a column too, or one well of a reservoir wide enough for all eight tips. Anything else
  (part of a column, unequal volumes, a 384-well plate) stays with a single channel.
* **Tips.** Filter tips. Each tip is the smallest that holds the most it will carry; a volume
  above the largest tip is split into equal parts.
* **Order.** One pipette holds one tip, so work that the protocol interleaves across tips is put
  back together tip by tip where that cannot change any well. Where it could, the order is kept
  and a tip that has to make way is replaced by a fresh one.
* **Deck.** Plates go in the first free slots in file order, tip racks after them.
* **Waste and tip reloads.** As on the Hamilton: reservoirs named `waste`, `waste_2`, ..., and
  a pause for a person to swap in full racks when the deck cannot hold enough.
* **A tight deck.** When everything does not fit in the slots, room is made in this order: a
  pair of pipettes that needs fewer kinds of tip; one size of tip for each pipette; fewer waste
  reservoirs, with a pause to empty them; fewer tip racks, with pauses to reload.

What it does not use yet: part of an 8-channel pipette's tips, modules, the gripper.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .protocol import EPS, Check, Labware, Problem, Protocol

# ---------------------------------------------------------------- the robots


@dataclass(frozen=True)
class Pipette:
  name: str  # what Opentrons calls it
  low: float  # the least it moves, uL
  high: float  # the most it moves, uL
  tips: Tuple[Tuple[float, str], ...]  # (uL a tip holds, tip rack), smallest first
  channels: int = 1  # 8 for a pipette that works a whole column at once


@dataclass(frozen=True)
class Profile:
  name: str
  title: str
  robot_type: str  # what the protocol's `requirements` say
  api_level: str
  slots: Tuple[str, ...]  # the deck slots labware may use, in the order they are filled
  trash_slot: Optional[str]  # where a trash bin is loaded; None when the robot has one built in
  pipettes: Tuple[Pipette, ...]


WASTE_TYPE = "nest_1_reservoir_195ml"
WASTE_CAPACITY = 195_000.0
RACK = 96  # tips in a rack
ROWS = "ABCDEFGH"

FLEX = Profile(
  name="opentrons-flex",
  title="Opentrons Flex",
  robot_type="Flex",
  api_level="2.19",
  slots=("D1", "D2", "D3", "C1", "C2", "C3", "B1", "B2", "B3", "A1", "A2"),
  trash_slot="A3",
  pipettes=(
    Pipette("flex_1channel_50", 1.0, 50.0, ((50.0, "opentrons_flex_96_filtertiprack_50ul"),)),
    Pipette(
      "flex_1channel_1000",
      5.0,
      1000.0,
      ((200.0, "opentrons_flex_96_filtertiprack_200ul"), (1000.0, "opentrons_flex_96_filtertiprack_1000ul")),
    ),
    Pipette("flex_8channel_50", 1.0, 50.0, ((50.0, "opentrons_flex_96_filtertiprack_50ul"),), channels=8),
    Pipette(
      "flex_8channel_1000",
      5.0,
      1000.0,
      ((200.0, "opentrons_flex_96_filtertiprack_200ul"), (1000.0, "opentrons_flex_96_filtertiprack_1000ul")),
      channels=8,
    ),
  ),
)

OT2 = Profile(
  name="opentrons-ot2",
  title="Opentrons OT-2",
  robot_type="OT-2",
  api_level="2.19",
  slots=tuple(str(n) for n in range(1, 12)),
  trash_slot=None,  # slot 12 is the fixed trash
  pipettes=(
    Pipette("p20_single_gen2", 1.0, 20.0, ((20.0, "opentrons_96_filtertiprack_20ul"),)),
    Pipette("p300_single_gen2", 20.0, 300.0, ((200.0, "opentrons_96_filtertiprack_200ul"),)),
    Pipette("p1000_single_gen2", 100.0, 1000.0, ((1000.0, "opentrons_96_filtertiprack_1000ul"),)),
    Pipette("p20_multi_gen2", 1.0, 20.0, ((20.0, "opentrons_96_filtertiprack_20ul"),), channels=8),
    Pipette("p300_multi_gen2", 20.0, 300.0, ((200.0, "opentrons_96_filtertiprack_200ul"),), channels=8),
  ),
)

PROFILES = {profile.name: profile for profile in (FLEX, OT2)}

# ---------------------------------------------------------------- labware

# PyLabRobot plate -> (the same product in Opentrons' library, uL a well holds there).
# Only pairs whose wells sit in the same places are listed; tests/test_opentrons.py compares them.
TWINS: Dict[str, Tuple[str, float]] = {
  "nest_1_troughplate_195000uL_Vb": ("nest_1_reservoir_195ml", 195_000.0),
  "nest_12_troughplate_15000uL_Vb": ("nest_12_reservoir_15ml", 15_000.0),
  "Cor_96_wellplate_360ul_Fb": ("corning_96_wellplate_360ul_flat", 360.0),
  "cor_96_wellplate_360uL_Fb": ("corning_96_wellplate_360ul_flat", 360.0),
}

_SHIPPED: Dict[str, Optional[Dict[str, Any]]] = {}
_BOTTOMS: Dict[str, str] = {}  # load name -> "flat", "round" or "V", where the definition says
# Filter plates and resin tips cannot stand in a deck slot on their own, and the Millipore
# collection plate that goes under them is missing from the last release that simulates an OT-2.
_NOT_ALONE = ("filter", "tips", "millipore")


def _definitions() -> Optional[Path]:
  """The folder of labware definitions that comes with Opentrons' software, when it is installed."""
  try:
    import opentrons_shared_data
  except ImportError:
    return None
  return Path(opentrons_shared_data.__file__).parent / "data" / "labware" / "definitions" / "2"


def opentrons_installed() -> bool:
  """Whether Opentrons' labware definitions can be read here."""
  return _definitions() is not None


def shipped_labware(load_name: str) -> Optional[Dict[str, Any]]:
  """Rows, columns, well capacity and well order of a plate or reservoir Opentrons ships; None otherwise."""
  if load_name not in _SHIPPED:
    _SHIPPED[load_name] = None
    root = _definitions()
    if root is not None and re.fullmatch(r"[a-z0-9_.]+", load_name) and (root / load_name).is_dir():
      versions = sorted((p for p in (root / load_name).glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem))
      body = json.loads(versions[-1].read_text()) if versions else {}
      columns = body.get("ordering") or []
      kind = body.get("parameters", {}).get("format")
      sizes = {len(column) for column in columns}
      holds = body.get("metadata", {}).get("displayCategory") in ("wellPlate", "reservoir")
      alone = not any(word in load_name for word in _NOT_ALONE)
      if holds and alone and kind != "irregular" and len(sizes) == 1:
        order = [well for column in columns for well in column]
        _SHIPPED[load_name] = {
          "rows": sizes.pop(),
          "columns": len(columns),
          "capacity": float(min(body["wells"][well]["totalLiquidVolume"] for well in order)),
          "order": order,
        }
        shapes = {group.get("metadata", {}).get("wellBottomShape") for group in body.get("groups", [])}
        _BOTTOMS[load_name] = {"flat": "flat", "u": "round", "v": "V"}.get(shapes.pop() if len(shapes) == 1 else "", "")
  return _SHIPPED[load_name]


def shipped_names() -> List[str]:
  """Every plate and reservoir Opentrons ships that a protocol file may name."""
  root = _definitions()
  if root is None:
    return []
  return [p.name for p in sorted(root.iterdir()) if p.is_dir() and shipped_labware(p.name) is not None]


def catalogue() -> str:
  """Every plate and reservoir a draft may name for an Opentrons robot, one per line."""
  lines = []
  for name in shipped_names():
    found = shipped_labware(name)
    bottom = f", {_BOTTOMS[name]} bottom" if _BOTTOMS.get(name) else ""
    lines.append(
      f"{name}: {len(found['order'])} wells ({found['rows']} rows x {found['columns']} columns), "
      f"{found['capacity']:g} uL each{bottom}{out_of_reach(name)}"
    )
  return "\n".join(lines)


def out_of_reach(name: str, height: float = 1.0) -> str:
  """What a labware list line says about the liquid under a tip that stops `height` mm above the floor.

  Empty where Opentrons gives no inside shape for the well, so the amount is not known.
  """
  from .opentrons_scene import inside_shapes, well_volume
  from .replay import LIQUID_TOLERANCE
  from .scene import two_figures_up

  height += LIQUID_TOLERANCE  # the replay wants the tip that far under the surface

  shapes = inside_shapes(name)
  if not shapes:
    return ""
  volume = two_figures_up(max(well_volume(sections, height) for sections in shapes.values()))
  return f", last {volume:g} uL out of reach" if volume else ""


def load_name(labware: Labware) -> Optional[Tuple[str, float]]:
  """What to load on an Opentrons deck for this labware, and what a well holds there; None when unknown."""
  if labware.library == "opentrons":
    return labware.type, labware.capacity
  if labware.type in TWINS:
    return TWINS[labware.type]
  found = shipped_labware(labware.type)  # the same name in both libraries
  return (labware.type, found["capacity"]) if found else None


# ---------------------------------------------------------------- the plan


@dataclass(frozen=True)
class Action:
  kind: str  # "pick_up", "aspirate", "dispense", "drop", "wait", "reload" or "empty"
  mount: str = ""  # "left" or "right"; empty for "wait" and "reload"
  labware: str = ""
  well: str = ""
  amount: float = 0.0  # uL per channel, or seconds for "wait"
  racks: Tuple[str, ...] = ()  # for "reload", the tip racks a person swaps; for "empty", the waste reservoirs
  surface: bool = False  # an aspirate that stays just under the liquid as it falls
  height: float = 0.0  # for such an aspirate, mm above the well floor; 0 for the usual pipetting height
  step: int = -1
  wells: Tuple[str, ...] = ()  # every well or tip the action touches: one, or eight for an 8-channel pipette


@dataclass
class OpentronsPlan:
  profile: Profile
  protocol: Protocol
  labware: Dict[str, str]  # every plate and tip rack on the deck -> Opentrons load name
  slots: Dict[str, str]  # labware name -> deck slot
  pipettes: Dict[str, str]  # mount -> pipette
  actions: List[Action]
  tips: Dict[str, int]  # tip rack load name -> tips used
  problems: List[Problem] = field(default_factory=list)
  pipetting_height: float = 1.0  # mm above the well floor for every aspirate and dispense
  notes: List[str] = field(default_factory=list)

  @property
  def ok(self) -> bool:
    return not self.problems

  def report(self) -> str:
    lines = [f"steadyhand plan: {'OK' if self.ok else 'FAIL'}  {self.protocol.name}  ({self.profile.title})"]
    for mount, pipette in self.pipettes.items():
      lines.append(f"  {mount:<5} mount: {pipette}")
    for name, slot in self.slots.items():
      lines.append(f"  slot {slot:>2}  {name} ({self.labware[name]})")
    for rack, count in self.tips.items():
      lines.append(f"  tips: {count} x {rack}")
    kinds = [a.kind for a in self.actions]
    if "reload" in kinds:
      lines.append(f"  tip reloads: {kinds.count('reload')} (the run pauses for a person to swap in full racks)")
    if "empty" in kinds:
      lines.append(f"  waste emptied: {kinds.count('empty')} times (the run pauses for a person to empty it)")
    if "wait" in kinds:
      waited = sum(a.amount for a in self.actions if a.kind == "wait")
      lines.append(f"  waits: {kinds.count('wait')} ({waited / 60:g} min in all)")
    followed = [a.height for a in self.actions if a.height]
    if followed:
      lines.append(
        f"  draws that follow the surface: {len(followed)}, the tip {min(followed):g} to {max(followed):g} mm above the well floor"
      )
    eight = any(len(a.wells) == 8 for a in self.actions)
    lines.append(
      f"  commands: {len(self.actions)} ({kinds.count('aspirate')} aspirates, "
      f"{kinds.count('dispense')} dispenses), "
      + ("eight channels at once where a whole column moves together" if eight else "one channel at a time")
    )
    lines += [f"  note: {text}" for text in self.notes]
    if self.problems:
      lines.append(f"  problems: {len(self.problems)}")
      lines += [f"    - {p}" for p in self.problems]
    return "\n".join(lines)


@dataclass
class _Fit:
  """How one pipette would do one tip's work."""

  pipette: Pipette
  capacity: float  # of the tip it would use
  rack: str
  draws: int


def _fit(pipette: Pipette, volumes: Sequence[float], mixes: Sequence[float], one_size: bool = False) -> Optional[_Fit]:
  """How `pipette` would do this work, or None when it cannot. With `one_size` it only has its largest tip."""
  carried = max(list(volumes) + list(mixes))
  options = [(min(capacity, pipette.high), rack) for capacity, rack in pipette.tips]
  if one_size:
    options = options[-1:]
  holding = [option for option in options if option[0] + EPS >= carried]
  capacity, rack = holding[0] if holding else options[-1]
  if any(mix > capacity + EPS or mix < pipette.low - EPS for mix in mixes):
    return None
  draws = 0
  for volume in volumes:
    parts = max(1, math.ceil((volume - EPS) / capacity))
    if volume / parts < pipette.low - EPS:
      return None
    draws += parts
  return _Fit(pipette, capacity, rack, draws + len(mixes))


def _reach(wells: Sequence[Any], rows: Dict[str, int]) -> Optional[str]:
  """Where an 8-channel pipette goes to reach these eight wells at once, or None when it cannot.

  That is a whole column of a plate with eight rows, given top to bottom, or one well of labware
  with a single row (a reservoir), which takes all eight tips.
  """
  first = wells[0]
  if any(well.labware != first.labware for well in wells):
    return None
  if rows.get(first.labware) == 1:
    return first.well if all(well.well == first.well for well in wells) else None
  if rows.get(first.labware) == 8:
    column = first.well[1:]
    return first.well if [well.well for well in wells] == [f"{row}{column}" for row in ROWS] else None
  return None


def _tip_by_tip(units: list, waits: Dict[int, Tuple[float, int]], sinks: Sequence[str]) -> list:
  """Put each tip's work together where no well can tell the difference; otherwise keep the order.

  Work is only moved inside one step, and never across a wait. Two pieces of work may swap
  places unless one of them adds to, or mixes in, a well the other one touches. The waste
  reservoirs in `sinks` only ever take liquid, so the order they are filled in is free.
  """
  bounds = sorted(set(waits) | {0, len(units)} | {i for i in range(1, len(units)) if units[i].step != units[i - 1].step})
  ordered: list = []
  for start, end in zip(bounds, bounds[1:]):
    part = units[start:end]
    first: Dict[int, int] = {}
    for index, unit in enumerate(part):
      first.setdefault(unit.tip, index)
    together = sorted(range(len(part)), key=lambda i: (first[part[i].tip], i))
    place = {old: new for new, old in enumerate(together)}
    latest_any: Dict[Any, int] = {}  # well -> the latest new place of anything that touched it
    latest_added: Dict[Any, int] = {}  # well -> the latest new place of anything that added to it
    safe = True
    for old, unit in enumerate(part):
      new = place[old]
      adds = unit.destination  # a transfer adds to it; a mix on its own stirs it
      draws = unit.source if unit.volume else None
      if adds.labware in sinks:
        adds = None
      if (adds is not None and latest_any.get(adds, -1) > new) or (draws is not None and latest_added.get(draws, -1) > new):
        safe = False
        break
      if adds is not None:
        latest_any[adds] = max(latest_any.get(adds, -1), new)
        latest_added[adds] = max(latest_added.get(adds, -1), new)
      if draws is not None:
        latest_any[draws] = max(latest_any.get(draws, -1), new)
    ordered += [part[i] for i in together] if safe else part
  return ordered


def plan(
  checked: Check, profile: Profile, *, pipetting_height: float = 1.0, waste_reservoirs: Optional[int] = None
) -> OpentronsPlan:
  """Plan a protocol that has passed `check` for the robot `profile` describes.

  `waste_reservoirs` caps how many waste reservoirs stand on the deck; the planner sets it
  itself, by planning again, when the deck is too small for all of them.
  """
  from .planner import _Unit, _units, send_waste

  protocol = checked.protocol
  problems: List[Problem] = []
  notes: List[str] = []

  def failed() -> OpentronsPlan:
    return OpentronsPlan(profile, protocol, labware, {}, {}, [], {}, problems, pipetting_height, notes)

  labware: Dict[str, str] = {}
  for name, item in protocol.labware.items():
    found = load_name(item)
    if found is None:
      twins = ", ".join(sorted(set(TWINS)))
      problems.append(
        Problem(
          f"labware.{name}.type",
          f"{item.type} is a PyLabRobot definition and steadyhand knows no Opentrons one for the same plate. "
          f"Name an Opentrons load name here, or one of: {twins}",
        )
      )
      continue
    labware[name] = found[0]
    # The check counted volumes against the other library's figure; hold the start to this one's.
    for liquid, (wells, volume) in protocol.liquids.items():
      if volume > found[1] + EPS and any(well.labware == name for well in wells):
        problems.append(
          Problem(f"liquids.{liquid}", f"{volume:g} uL is more than a well of {found[0]} holds ({found[1]:g} uL)")
        )
    for well, volume in checked.volumes.items():
      if well.labware == name and volume > found[1] + EPS:
        problems.append(
          Problem(f"labware.{name}", f"{well} ends with {volume:g} uL; a well of {found[0]} holds {found[1]:g} uL")
        )
  if problems:
    return failed()

  units, waits = _units(checked.moves)
  reservoirs, refused, empties = send_waste(units, labware, WASTE_CAPACITY, waste_reservoirs)
  if refused is not None:
    problems.append(refused)
    return failed()
  labware.update({name: WASTE_TYPE for name in reservoirs})

  singles = [p for p in profile.pipettes if p.channels == 1]
  eights = [p for p in profile.pipettes if p.channels == 8]

  # What each tip carries, and which pipettes could do it.
  def carried(by: list) -> Dict[int, Tuple[List[float], List[float], int]]:
    work: Dict[int, Tuple[List[float], List[float], int]] = {}
    for unit in by:
      volumes, mixes, _ = work.setdefault(unit.tip, ([], [], unit.step))
      if unit.volume:
        volumes.append(unit.volume)
      if unit.mix:
        mixes.append(unit.mix[1])
    return work

  def fitting(work: Dict[int, Tuple[List[float], List[float], int]]) -> Dict[int, Dict[str, _Fit]]:
    return {
      tip: {p.name: fit for p in singles if (fit := _fit(p, volumes, mixes)) is not None}
      for tip, (volumes, mixes, _) in work.items()
    }

  work = carried(units)
  fits = fitting(work)
  stuck = {tip for tip in work if not fits[tip]}
  if stuck:
    # No one pipette does everything this tip was given. A fresh tip is always safe, so give each
    # move and each mix its own, and let each go to the pipette that suits it.
    fresh = max(work) + 1
    apart: list = []
    moved: Dict[int, int] = {}  # where each old unit starts in the new list
    for index, unit in enumerate(units):
      moved[index] = len(apart)
      if unit.tip not in stuck:
        apart.append(unit)
        continue
      if unit.volume:
        apart.append(_Unit(unit.step, fresh, unit.source, unit.destination, unit.volume, None))
        fresh += 1
      if unit.mix:
        apart.append(_Unit(unit.step, fresh, unit.destination, unit.destination, 0.0, unit.mix))
        fresh += 1
    moved[len(units)] = len(apart)
    extra = len({unit.tip for unit in apart}) - len(work)
    waits = {moved[index]: wait for index, wait in waits.items()}
    units = apart
    work = carried(units)
    fits = fitting(work)
    if extra:
      notes.append(
        f"{extra} more tips than the check counted: where no one pipette could do everything a tip was "
        "given, each move and each mix gets a fresh tip"
      )
  lowest = min(p.low for p in singles)
  highest = max(min(capacity, p.high) for p in singles for capacity, _ in p.tips)
  for tip, (volumes, mixes, step) in work.items():
    if not fits[tip]:
      amounts = volumes + mixes
      if min(amounts) < lowest - EPS:
        reason = f"{min(amounts):g} uL is less than any pipette on the {profile.title} moves ({lowest:g} uL)"
      elif mixes and max(mixes) > highest + EPS:
        reason = f"mixing {max(mixes):g} uL is more than the largest tip on the {profile.title} holds ({highest:g} uL)"
      else:
        reason = f"no pipette on the {profile.title} moves {min(amounts):g} uL"
      problems.append(Problem(f"steps[{step}]", reason))
  if problems:
    return failed()

  # Runs of eight moves that an 8-channel pipette could do as one: the same volume and mix,
  # down one column or into one reservoir well, with nothing between them.
  rows = {name: item.rows for name, item in protocol.labware.items()}
  rows.update({name: 1 for name in reservoirs})
  columns: Dict[int, Tuple[Optional[str], str]] = {}  # index of the first unit -> where the pipette draws and delivers
  index = 0
  while index + 8 <= len(units):
    group = units[index : index + 8]
    first = group[0]
    alike = all(
      u.step == first.step and abs(u.volume - first.volume) < EPS and u.mix == first.mix for u in group
    ) and not any(i in waits or i in empties for i in range(index + 1, index + 8))
    delivers = _reach([u.destination for u in group], rows) if alike else None
    draws = _reach([u.source for u in group], rows) if alike and first.volume else None
    if delivers is not None and (draws is not None or not first.volume):
      columns[index] = (draws, delivers)
      index += 8
    else:
      index += 1
  sets: Dict[Tuple[int, ...], Tuple[List[float], List[float]]] = {}  # the eight tips of a column -> what they carry
  for index in columns:
    first = units[index]
    volumes, mixes = sets.setdefault(tuple(u.tip for u in units[index : index + 8]), ([], []))
    if first.volume:
      volumes.append(first.volume)
    if first.mix:
      mixes.append(first.mix[1])

  def assign(
    pair: Tuple[Pipette, ...], one_size: bool
  ) -> Optional[Tuple[Dict[int, _Fit], Dict[Tuple[int, ...], _Fit]]]:
    """Who does what with this pair: a pipette for each set of eight tips, and one for each tip left over."""
    by_set: Dict[Tuple[int, ...], _Fit] = {}
    for tips, (volumes, mixes) in sets.items():
      able = [fit for p in pair if p.channels == 8 and (fit := _fit(p, volumes, mixes, one_size)) is not None]
      if able:
        by_set[tips] = min(able, key=lambda fit: (fit.draws, fit.pipette.high))
    left = [
      unit
      for index, unit in enumerate(units)
      if not any(start <= index < start + 8 and tuple(u.tip for u in units[start : start + 8]) in by_set for start in near(index))
    ]
    by_tip: Dict[int, _Fit] = {}
    for tip, (volumes, mixes, _) in carried(left).items():
      able = [fit for p in pair if p.channels == 1 and (fit := _fit(p, volumes, mixes, one_size)) is not None]
      if not able:
        return None
      by_tip[tip] = min(able, key=lambda fit: (fit.draws, fit.pipette.high))
    return by_tip, by_set

  starts = sorted(columns)

  def near(index: int) -> List[int]:
    """The column, if any, that the unit at `index` is part of."""
    import bisect

    at = bisect.bisect_right(starts, index) - 1
    return [starts[at]] if at >= 0 and starts[at] <= index < starts[at] + 8 else []

  # The pair that moves everything in the fewest draws, among those the deck has room for: every
  # plate, one waste reservoir if any is needed, and one rack of each kind of tip. Each pair is
  # tried twice: with the best tip for each job, and with each pipette held to its largest tip,
  # which needs fewer kinds of rack. Where both fit and draw as often, the best tips win.
  fixed = len(labware) - len(reservoirs) + (1 if reservoirs else 0)
  best: Optional[Tuple[Tuple[int, int, int, int, float], Tuple[Pipette, ...], Dict[int, _Fit], Dict[Tuple[int, ...], _Fit]]] = None
  for one_size in (False, True):
    for size in (1, 2):
      for pair in combinations(profile.pipettes, size):
        assigned = assign(pair, one_size)
        if assigned is not None:
          by_tip, by_set = assigned
          fits_used = list(by_tip.values()) + list(by_set.values())
          used_by = tuple(p for p in pair if any(fit.pipette is p for fit in fits_used))
          kinds = len({(fit.pipette.name, fit.rack) for fit in fits_used})
          crowded = int(fixed + kinds > len(profile.slots))
          draws = sum(fit.draws for fit in fits_used)
          score = (crowded, draws, int(one_size), len(used_by), sum(p.high for p in used_by))
          if best is None or score < best[0]:
            best = (score, used_by, by_tip, by_set)
  if best is not None and best[0][2]:
    notes.append("the deck is tight, so each pipette uses one size of tip")
  if best is None and work:
    wanted = sorted({min(by, key=lambda n: by[n].draws) for by in fits.values()})
    problems.append(
      Problem(
        "steps",
        f"the volumes here need {len(wanted)} pipettes ({', '.join(wanted)}) and the {profile.title} holds two",
      )
    )
    return failed()
  pair, chosen, chosen_sets = (best[1], best[2], best[3]) if best else ((), {}, {})
  mounts = {p.name: mount for p, mount in zip(pair, ("left", "right"))}

  # The order of work. Columns stay where they are; the single moves between them are put together
  # tip by tip where that is safe. Each entry is a wait, one unit, or the eight units of a column.
  sequence: List[Tuple[str, Any]] = []  # also ("empty", (the waste reservoirs, step))
  run: list = []

  def flush() -> None:
    sequence.extend(("one", unit) for unit in _tip_by_tip(run, {}, reservoirs))
    run.clear()

  index = 0
  while index < len(units):
    if index in empties:
      flush()
      sequence.append(("empty", (tuple(reservoirs), units[index].step)))
    if index in waits:
      flush()
      sequence.append(("wait", waits[index]))
    tips = tuple(u.tip for u in units[index : index + 8])
    if index in columns and tips in chosen_sets:
      flush()
      sequence.append(("eight", (index, tips)))
      index += 8
    else:
      run.append(units[index])
      index += 1
  flush()
  if len(units) in waits:
    sequence.append(("wait", waits[len(units)]))

  # One pass to see when each pipette takes and drops its tips.
  def job(entry: Tuple[str, Any]) -> Tuple[_Fit, Any, int]:
    """The pipette for an entry, what it must be holding, and the step it belongs to."""
    if entry[0] == "one":
      return chosen[entry[1].tip], ("tip", entry[1].tip), entry[1].step
    start, tips = entry[1]
    return chosen_sets[tips], ("set", tips), units[start].step

  last_use: Dict[Tuple[str, Any], int] = {}
  for place, entry in enumerate(sequence):
    if entry[0] not in ("wait", "empty"):
      fit, key, _ = job(entry)
      last_use[(mounts[fit.pipette.name], key)] = place
  holding: Dict[str, Any] = {}  # mount -> what is on it
  replaced = 0  # tips put down while their work was unfinished
  used: Dict[Tuple[str, str], int] = {}  # (pipette, tip rack) -> tips taken
  drafts: List[Tuple[str, Any]] = []  # ("pick_up", entry), ("drop", (mount, step)), ("work", entry), ("wait", ...)
  for place, entry in enumerate(sequence):
    if entry[0] in ("wait", "empty"):
      drafts.append(entry)
      continue
    fit, key, step = job(entry)
    mount = mounts[fit.pipette.name]
    if holding.get(mount) != key:
      if mount in holding:
        replaced += fit.pipette.channels
        drafts.append(("drop", (mount, step)))
      drafts.append(("pick_up", entry))
      used[(fit.pipette.name, fit.rack)] = used.get((fit.pipette.name, fit.rack), 0) + fit.pipette.channels
      holding[mount] = key
    drafts.append(("work", entry))
    if last_use[(mount, key)] == place:
      drafts.append(("drop", (mount, step)))
      del holding[mount]
  if replaced:
    notes.append(
      f"{replaced} tips are replaced by fresh ones: one pipette holds one set of tips, and the order "
      "of this work could not be changed without changing a well"
    )

  # Tip racks: as many as it takes, or what fits beside the plates with pauses to reload. A single
  # and an 8-channel pipette never share a rack: one takes tips singly, the other a column at a time.
  order = [(p.name, rack) for p in profile.pipettes for _, rack in p.tips if (p.name, rack) in used]
  racks = {key: math.ceil(used[key] / RACK) for key in order}
  free = len(profile.slots) - len(labware)
  limit = dict(racks)
  if sum(racks.values()) > free and waste_reservoirs is None and len(reservoirs) > 1:
    # Not everything fits. Emptying a reservoir is less work than swapping tip racks, so give up
    # waste reservoirs first: keep as many as still leave room for every rack, and at least one.
    plates = len(labware) - len(reservoirs)
    keep = max(1, min(len(reservoirs) - 1, len(profile.slots) - plates - sum(racks.values())))
    return plan(checked, profile, pipetting_height=pipetting_height, waste_reservoirs=keep)
  if free < len(racks):
    problems.append(
      Problem(
        "labware",
        f"{len(labware)} plates and reservoirs and {len(racks)} kinds of tip need {len(labware) + len(racks)} slots; "
        f"the {profile.title} has {len(profile.slots)} for labware",
      )
    )
    return failed()
  if sum(racks.values()) > free:
    limit = {key: 1 for key in racks}
    spare = free - len(racks)
    total = sum(racks.values())
    for key in sorted(racks, key=lambda k: -racks[k]):  # share the rest by need, biggest first
      extra = min(spare, max(0, round(free * racks[key] / total) - 1), racks[key] - 1)
      limit[key] += extra
      spare -= extra
    for key in sorted(racks, key=lambda k: -racks[k]):  # hand out what rounding left over
      extra = min(spare, racks[key] - limit[key])
      limit[key] += extra
      spare -= extra

  eight = {p.name for p in eights}

  def rack_name(key: Tuple[str, str], number: int) -> str:
    capacity = next(c for p in profile.pipettes for c, r in p.tips if r == key[1])
    return f"tips_{capacity:g}{'x8' if key[0] in eight else ''}_{number}"

  for key in order:
    for number in range(1, limit[key] + 1):
      labware[rack_name(key, number)] = key[1]
  slots = dict(zip(labware, profile.slots))

  def reached(well: Any, at: Optional[str], channels: int) -> Tuple[str, ...]:
    """Every well a pipette touches when it is sent to `at`."""
    if channels == 1:
      return (at,)
    if rows.get(well.labware) == 1:
      return (at,) * 8
    return tuple(f"{row}{at[1:]}" for row in ROWS)

  actions: List[Action] = []
  taken: Dict[Tuple[str, str], int] = {}
  for kind, body in drafts:
    if kind == "wait":
      actions.append(Action("wait", amount=body[0], step=body[1]))
      continue
    if kind == "empty":
      actions.append(Action("empty", racks=body[0], step=body[1]))
      continue
    if kind == "drop":
      actions.append(Action("drop", body[0], step=body[1]))
      continue
    fit, _, step = job(body)
    mount, channels = mounts[fit.pipette.name], fit.pipette.channels
    key = (fit.pipette.name, fit.rack)
    if kind == "pick_up":
      count = taken.get(key, 0)
      on_deck = limit[key] * RACK
      if count and count % on_deck == 0:  # every rack of this kind on the deck is used up
        names = tuple(rack_name(key, n) for n in range(1, limit[key] + 1))
        actions.append(Action("reload", racks=names, step=step))
      spot = count % on_deck
      column, row = (spot % RACK) // 8, (spot % RACK) % 8
      tips = tuple(f"{ROWS[r]}{column + 1}" for r in range(row, row + channels))
      actions.append(Action("pick_up", mount, rack_name(key, spot // RACK + 1), tips[0], step=step, wells=tips))
      taken[key] = count + channels
      continue
    if body[0] == "one":
      first, draws, delivers = body[1], body[1].source.well, body[1].destination.well
    else:
      first = units[body[1][0]]
      draws, delivers = columns[body[1][0]]
    source, destination = first.source, first.destination
    if first.volume:
      parts = max(1, math.ceil((first.volume - EPS) / fit.capacity))
      for _ in range(parts):
        amount = round(first.volume / parts, 4)
        actions.append(
          Action(
            "aspirate", mount, source.labware, draws, amount, step=step, wells=reached(source, draws, channels),
            surface=first.surface,
          )
        )
        actions.append(
          Action(
            "dispense", mount, destination.labware, delivers, amount, step=step, wells=reached(destination, delivers, channels)
          )
        )
    if first.mix:
      times, volume = first.mix
      for _ in range(times):
        for action in ("aspirate", "dispense"):
          actions.append(
            Action(action, mount, destination.labware, delivers, volume, step=step, wells=reached(destination, delivers, channels))
          )

  if not problems and any(a.surface for a in actions):
    actions, cannot = _follow_surface(actions, protocol, labware, pipetting_height)
    problems += cannot

  tips_used: Dict[str, int] = {}
  for key in order:
    tips_used[key[1]] = tips_used.get(key[1], 0) + used[key]
  return OpentronsPlan(
    profile=profile,
    protocol=protocol,
    labware=labware,
    slots=slots,
    pipettes={mount: name for name, mount in mounts.items()},
    actions=actions,
    tips=tips_used,
    problems=problems,
    pipetting_height=pipetting_height,
    notes=notes,
  )


def _follow_surface(
  actions: List[Action], protocol, labware: Dict[str, str], pipetting_height: float
) -> Tuple[List[Action], List[Problem]]:
  """Give every aspirate that follows the surface its height above the well floor.

  The tip stops `SUBMERGED` mm under where the liquid stands once the action has drawn, and
  never lower than the usual pipetting height. With eight channels the lowest surface decides.
  """
  from dataclasses import replace

  from .opentrons_scene import inside_shapes, well_height
  from .planner import SUBMERGED

  held: Dict[Tuple[str, str], float] = {}
  for wells, volume in protocol.liquids.values():
    for well in wells:
      held[(well.labware, well.well)] = volume
  problems: List[Problem] = []
  refused = set()
  out: List[Action] = []
  for action in actions:
    if action.kind in ("aspirate", "dispense"):
      sign = -1 if action.kind == "aspirate" else 1
      for well in action.wells:
        held[(action.labware, well)] = held.get((action.labware, well), 0.0) + sign * action.amount
    if action.kind == "aspirate" and action.surface:
      shapes = inside_shapes(labware[action.labware])
      if not shapes:
        if (action.step, action.labware) not in refused:
          refused.add((action.step, action.labware))
          problems.append(
            Problem(
              f"steps[{action.step}].draw_from",
              f"cannot follow the surface in {action.labware} ({labware[action.labware]}): Opentrons gives no inside "
              "shape for its wells, so the height of the liquid is not known",
            )
          )
      else:
        lowest = min(well_height(shapes[well], max(0.0, held[(action.labware, well)])) for well in action.wells)
        action = replace(action, height=round(max(pipetting_height, lowest - SUBMERGED), 2))
    out.append(action)
  return out, problems


# ---------------------------------------------------------------- writing a protocol

_COLOURS = ("#4477aa", "#ee6677", "#228833", "#ccbb44", "#66ccee", "#aa3377", "#bbbbbb")


def emit(planned: OpentronsPlan, *, source: str = "") -> str:
  """The plan as an Opentrons protocol file."""
  from . import __version__

  profile, protocol = planned.profile, planned.protocol
  lines = [
    f'"""{protocol.name}',
    "",
    f"Written by steadyhand {__version__}" + (f" from {source}" if source else "") + f" for an {profile.title}.",
    "Change the protocol file and write this again; edits made here are lost.",
    '"""',
    "",
    "from opentrons import protocol_api",
    "",
    f'metadata = {{"protocolName": {json.dumps(protocol.name)}, "author": "steadyhand {__version__}"}}',
    f'requirements = {{"robotType": "{profile.robot_type}", "apiLevel": "{profile.api_level}"}}',
    "",
    f"HEIGHT = {planned.pipetting_height!r}  # mm above the well floor for every aspirate and dispense",
    "",
    "",
    "def run(protocol: protocol_api.ProtocolContext):",
  ]
  if profile.trash_slot:
    lines.append(f'  protocol.load_trash_bin("{profile.trash_slot}")')
  lines.append("  deck = {}")
  for name, slot in planned.slots.items():
    lines.append(
      f'  deck[{json.dumps(name)}] = protocol.load_labware("{planned.labware[name]}", "{slot}", label={json.dumps(name)})'
    )
  for mount, pipette in planned.pipettes.items():
    lines.append(f'  {mount} = protocol.load_instrument("{pipette}", "{mount}")')
  if protocol.liquids:
    lines += ["", "  # What a person puts on the deck before the run."]
  for number, (liquid, (wells, volume)) in enumerate(protocol.liquids.items()):
    colour = _COLOURS[number % len(_COLOURS)]
    lines.append(
      f"  liquid = protocol.define_liquid({json.dumps(liquid)}, description={json.dumps(liquid)}, "
      f'display_color="{colour}")'
    )
    by_labware: Dict[str, List[str]] = {}
    for well in wells:
      by_labware.setdefault(well.labware, []).append(well.well)
    for name, names in by_labware.items():
      lines.append(f'  for well in "{" ".join(names)}".split():')
      lines.append(f"    deck[{json.dumps(name)}][well].load_liquid(liquid, {round(volume, 4)!r})")
  lines.append("")
  step = None
  for action in planned.actions:
    if action.step != step:
      step = action.step
      lines.append(f"  # step {step}")
    if action.kind == "wait":
      lines.append(f"  protocol.delay(seconds={action.amount:g})  # {action.amount / 60:g} min")
    elif action.kind == "reload":
      where = ", ".join(f"{name} in slot {planned.slots[name]}" for name in action.racks)
      lines.append(f"  protocol.pause({json.dumps('Swap in full tip racks: ' + where)})")
      lines += [f"  deck[{json.dumps(name)}].reset()" for name in action.racks]
    elif action.kind == "empty":
      where = ", ".join(f"{name} in slot {planned.slots[name]}" for name in action.racks)
      lines.append(f"  protocol.pause({json.dumps('Empty the waste: ' + where)})")
    elif action.kind == "drop":
      lines.append(f"  {action.mount}.drop_tip()")
    elif action.kind == "pick_up":
      lines.append(f'  {action.mount}.pick_up_tip(deck[{json.dumps(action.labware)}]["{action.well}"])')
    else:
      height = f"{action.height!r}))  # just under the surface" if action.height else "HEIGHT))"
      lines.append(
        f"  {action.mount}.{action.kind}({action.amount!r}, "
        f'deck[{json.dumps(action.labware)}]["{action.well}"].bottom({height}'
      )
  return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- Opentrons' own simulator

OT2_SIMULATOR = "STEADYHAND_OT2_SIMULATE"  # environment variable: an opentrons_simulate that still takes OT-2 files


@dataclass
class Simulation:
  """What Opentrons' simulator made of an emitted protocol."""

  title: str  # the robot
  ran: bool  # False when no simulator here could take the file
  log: List[str] = field(default_factory=list)  # one line for everything the robot would do
  error: str = ""  # why the simulator stopped
  why_not: str = ""  # why it could not be run
  by: str = ""  # which simulator ran it

  @property
  def ok(self) -> bool:
    return self.ran and not self.error

  def report(self) -> str:
    if not self.ran:
      return "\n".join([f"Opentrons' simulator: NOT RUN  ({self.title})", f"  {self.why_not}"])
    lines = [f"Opentrons' simulator: {'PASS' if self.ok else 'FAIL'}  ({self.title}, {self.by})"]
    if self.error:
      lines.append(f"  stopped: {self.error}")
    else:
      lines.append(f"  robot actions simulated: {len(self.log)}")
    return "\n".join(lines)

  def to_dict(self) -> Dict[str, Any]:
    return {
      "robot": self.title,
      "ran": self.ran,
      "pass": self.ok,
      "simulated_by": self.by,
      "actions": len(self.log),
      "error": self.error,
      "why_not": self.why_not,
    }


_AT_LINE = re.compile(r"\[line (\d+)\]: (.*?)(?:['\"], errorInfo|$)", re.S)


def _reason(text: str, script: str) -> str:
  """The simulator's own sentence, and the line of the protocol it was on."""
  found = _AT_LINE.search(text)
  if not found:
    return " ".join(text.split())[:400]
  number, said = int(found.group(1)), found.group(2)
  said = re.sub(r"^Error \d+ \w+ \(\w+\): ", "", " ".join(said.split()))
  lines = script.splitlines()
  at = lines[number - 1].strip() if 0 < number <= len(lines) else ""
  return f"{said} (line {number}: {at})" if at else said


def simulate(script: str, profile: Profile) -> Simulation:
  """Run an emitted protocol through Opentrons' simulator, here or in the one the environment names."""
  import contextlib

  result = Simulation(title=profile.title, ran=False)
  will_not_load = ""
  try:
    import opentrons
    from opentrons import simulate as simulator
  except ImportError:
    simulator = None
  except Exception as error:  # installed, but it will not load here: on Python 3.10 its own models refuse to build
    simulator = None
    will_not_load = " ".join(str(error).split())[:200]
  if simulator is not None:
    result.by = f"opentrons {opentrons.__version__}"
    try:
      with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        log, _ = simulator.simulate(io.StringIO(script), "protocol.py")
      result.ran = True
      result.log = [line for line in simulator.format_runlog(log).splitlines() if line.strip()]
      return result
    except RuntimeError as error:
      if "designed for an OT-2" not in str(error):  # anything else is the protocol's fault
        result.ran, result.error = True, _reason(str(error), script)
        return result
    except Exception as error:
      result.ran, result.error = True, _reason(str(error), script)
      return result

  command = os.environ.get(OT2_SIMULATOR if profile is OT2 else "", "")
  if command:
    with tempfile.TemporaryDirectory() as folder:
      path = Path(folder) / "protocol.py"
      path.write_text(script)
      try:
        done = subprocess.run([command, str(path)], capture_output=True, text=True, timeout=1800)
      except (OSError, subprocess.TimeoutExpired) as error:
        result.why_not = f"could not run {command}: {error}"
        return result
    result.ran, result.by = True, command
    result.log = [line for line in done.stdout.splitlines() if line.strip()]
    if done.returncode != 0:
      result.error = _reason(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else "it stopped", script)
    return result

  if will_not_load:
    result.why_not = f"Opentrons' software is installed but its simulator will not load on this Python: {will_not_load}"
  elif simulator is None:
    result.why_not = (
      "Opentrons' software is not installed here, so nothing simulated the protocol. "
      "Install it with: pip install 'steadyhand[opentrons]'"
    )
  else:
    result.why_not = (
      f"{result.by} no longer simulates OT-2 protocols; Opentrons moved the OT-2 to its own software. "
      f"Install opentrons==9.0.0 in a separate environment and set {OT2_SIMULATOR} to its opentrons_simulate."
    )
  return result
