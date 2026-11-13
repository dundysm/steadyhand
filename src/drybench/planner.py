"""Turn a checked protocol into commands a Hamilton STARlet can run.

The protocol says what to do. The plan adds how: which tips, which channels move together,
where every plate and tip rack sits on the deck. A plan is a flat list of four commands
(pick up tips, aspirate, dispense, discard tips), and the same list is used three ways:

* `run` executes it on any PyLabRobot `LiquidHandler`;
* `rehearse_plan` executes it on a recording backend and replays it in the physics scene;
* `emit` writes it out as a PyLabRobot script.

Choices this planner makes, all deterministic:

* **Tips.** Each tip is the smallest filter tip that holds the largest volume it will carry.
  A transfer bigger than the largest tip is split into equal parts.
* **Channels.** Consecutive moves share an 8-channel command when their wells sit in one
  column at least 9 mm apart, or when they all draw from one well wide enough to take them.
* **Deck.** Tip carriers go on the left from rail 1, plate carriers after them, in file order.
* **Waste.** Discarded liquid goes to a reservoir named `waste`, which the planner adds.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .protocol import EPS, WASTE, Check, Move, Problem, Protocol, Well, check
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

# Working volume in uL and the PyLabRobot definition, smallest first.
TIP_TYPES: List[Tuple[float, str]] = [
  (10.0, "hamilton_96_tiprack_10uL_filter"),
  (50.0, "hamilton_96_tiprack_50uL_filter"),
  (300.0, "hamilton_96_tiprack_300uL_filter"),
  (1000.0, "hamilton_96_tiprack_1000uL_filter"),
]


@dataclass(frozen=True)
class Command:
  kind: str  # "pick_up", "aspirate", "dispense" or "discard"
  channels: Tuple[int, ...]
  resource: str = ""  # the plate or tip rack; empty for "discard"
  wells: Tuple[str, ...] = ()
  volumes: Tuple[float, ...] = ()
  step: int = -1


@dataclass(frozen=True)
class Placement:
  carrier: str  # resource name
  carrier_type: str
  rails: int
  sites: Tuple[Optional[str], ...]  # labware name on each site, front to back


@dataclass
class Plan:
  protocol: Protocol
  labware: Dict[str, str]  # every plate and tip rack on the deck -> PyLabRobot definition
  placements: List[Placement]
  commands: List[Command]
  tips: Dict[str, int]  # tip rack definition -> tips used
  problems: List[Problem] = field(default_factory=list)
  pipetting_height: float = 1.0  # mm above the well floor for every aspirate and dispense

  @property
  def ok(self) -> bool:
    return not self.problems

  def report(self) -> str:
    lines = [f"drybench plan: {'OK' if self.ok else 'FAIL'}  {self.protocol.name}"]
    for placement in self.placements:
      held = ", ".join(s for s in placement.sites if s)
      lines.append(f"  rails {placement.rails:>2}  {placement.carrier_type}: {held}")
    for definition, count in self.tips.items():
      lines.append(f"  tips: {count} x {definition}")
    kinds = [c.kind for c in self.commands]
    widest = max((len(c.channels) for c in self.commands), default=0)
    lines.append(
      f"  commands: {len(self.commands)} ({kinds.count('aspirate')} aspirates, "
      f"{kinds.count('dispense')} dispenses), up to {widest} channels at once"
    )
    if self.problems:
      lines.append(f"  problems: {len(self.problems)}")
      lines += [f"    - {p}" for p in self.problems]
    return "\n".join(lines)


# ---------------------------------------------------------------- geometry of labware


class _Geometry:
  """Row positions and well widths, read once from PyLabRobot for each labware definition."""

  def __init__(self) -> None:
    self._cache: Dict[str, Tuple[Dict[str, Tuple[int, float]], float]] = {}

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

  def well_width(self, definition: str) -> float:
    return self._load(definition)[1]


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


def _units(moves: Sequence[Move]) -> List[_Unit]:
  units: List[_Unit] = []
  for move in moves:
    if move.kind == "transfer":
      assert move.source is not None and move.destination is not None
      units.append(_Unit(move.step, move.tip, move.source, move.destination, move.volume, None))
    elif move.kind == "mix":
      assert move.source is not None
      last = units[-1] if units else None
      if last and last.tip == move.tip and last.destination == move.source and last.mix is None and last.volume:
        last.mix = (move.times, move.volume)
      else:
        units.append(_Unit(move.step, move.tip, move.source, move.source, 0.0, (move.times, move.volume)))
  return units


def plan(checked: Check) -> Plan:
  """Plan a protocol that has passed `check`."""
  protocol = checked.protocol
  problems: List[Problem] = []
  geometry = _Geometry()
  units = _units(checked.moves)

  labware = {name: item.type for name, item in protocol.labware.items()}
  if any(u.destination == WASTE for u in units):
    if "waste" in labware:
      problems.append(Problem("labware.waste", "the name 'waste' is kept for the planner's waste reservoir"))
    labware["waste"] = WASTE_TYPE

  def place(well: Well) -> Tuple[str, str]:
    return ("waste", "A1") if well == WASTE else (well.labware, well.well)

  # Tip type for every tip: the smallest that holds the most it will carry.
  largest: Dict[int, float] = {}
  for unit in units:
    carried = max(unit.volume, unit.mix[1] if unit.mix else 0.0)
    largest[unit.tip] = max(largest.get(unit.tip, 0.0), carried)
  tip_type: Dict[int, int] = {}
  for tip, volume in largest.items():
    fits = [i for i, (capacity, _) in enumerate(TIP_TYPES) if capacity + EPS >= volume]
    tip_type[tip] = fits[0] if fits else len(TIP_TYPES) - 1
  for unit in units:
    capacity = TIP_TYPES[tip_type[unit.tip]][0]
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
        if geometry.well_width(definition) < CHANNEL_PITCH * len(wells):
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

  # Tips are handed out down each column of a rack. A command that needs k tips takes k
  # neighbouring rows of one column, so a column's leftovers are skipped when too few remain.
  racks: Dict[int, int] = {}  # tip type -> racks opened
  cursor: Dict[int, Tuple[int, int]] = {}  # tip type -> (column, row) of the next free tip
  used: Dict[int, int] = {}

  def take(kind: int, count: int) -> Tuple[str, Tuple[str, ...]]:
    column, row = cursor.get(kind, (0, 0))
    if kind not in racks:
      racks[kind] = 1
    if row + count > 8:
      column, row = column + 1, 0
    if column >= 12:
      racks[kind] += 1
      column, row = 0, 0
    cursor[kind] = (column, row + count)
    used[kind] = used.get(kind, 0) + count
    name = f"tips_{TIP_TYPES[kind][0]:g}_{racks[kind]}"
    return name, tuple(f"{'ABCDEFGH'[row + i]}{column + 1}" for i in range(count))

  commands: List[Command] = []
  holding: Dict[int, int] = {}  # channel -> the tip number it has on
  position = 0
  for batch in batches:
    channels = tuple(range(len(batch)))
    kind = tip_type[batch[0].tip]
    step = batch[0].step

    stale = tuple(c for c in holding if c >= len(batch) or holding[c] != batch[c].tip)
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

    capacity = TIP_TYPES[kind][0]
    if batch[0].volume:
      parts = [max(1, math.ceil((u.volume - EPS) / capacity)) for u in batch]
      for cycle in range(max(parts)):
        active = [c for c in channels if cycle < parts[c]]
        volumes = tuple(round(batch[c].volume / parts[c], 4) for c in active)
        source, destination = place(batch[0].source)[0], place(batch[0].destination)[0]
        commands.append(
          Command("aspirate", tuple(active), source, tuple(place(batch[c].source)[1] for c in active), volumes, step)
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
    done = tuple(c for c in channels if last_use[batch[c].tip] < position)
    if done:
      commands.append(Command("discard", done, step=step))
      for c in done:
        del holding[c]

  # Deck: tip carriers from rail 1, then plate carriers.
  tip_racks: List[str] = []
  for kind in sorted(racks):
    for number in range(1, racks[kind] + 1):
      name = f"tips_{TIP_TYPES[kind][0]:g}_{number}"
      labware[name] = TIP_TYPES[kind][1]
      tip_racks.append(name)
  plates = [name for name in labware if name not in tip_racks]

  placements: List[Placement] = []
  rails = 1
  for label, carrier_type, items in (("tip_carrier", TIP_CARRIER, tip_racks), ("plate_carrier", PLATE_CARRIER, plates)):
    for number, start in enumerate(range(0, len(items), SITES), start=1):
      sites = tuple(items[start : start + SITES]) + (None,) * (SITES - len(items[start : start + SITES]))
      placements.append(Placement(f"{label}_{number}", carrier_type, rails, sites))
      rails += CARRIER_RAILS
  if rails - 1 > DECK_RAILS:
    problems.append(
      Problem("labware", f"{len(placements)} carriers need {rails - 1} rails; a STARlet deck has {DECK_RAILS}")
    )

  return Plan(
    protocol=protocol,
    labware=labware,
    placements=placements,
    commands=commands,
    tips={TIP_TYPES[kind][1]: count for kind, count in sorted(used.items())},
    problems=problems,
  )


# ---------------------------------------------------------------- running a plan


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
          carrier[site] = getattr(resources, planned.labware[name])(name=name)
      deck.assign_child_resource(carrier, rails=placement.rails)
  for wells, volume in planned.protocol.liquids.values():
    for well in wells:
      deck.get_resource(well.labware).get_item(well.well).tracker.set_liquids([(None, volume)])
  return deck


async def run(planned: Plan, handler) -> None:
  """Send every command in the plan to a PyLabRobot LiquidHandler."""
  deck = handler.deck
  height = planned.pipetting_height
  for command in planned.commands:
    channels = list(command.channels)
    if command.kind == "discard":
      await handler.discard_tips(use_channels=channels)
      continue
    resource = deck.get_resource(command.resource)
    items = [resource.get_item(well) for well in command.wells]
    if command.kind == "pick_up":
      await handler.pick_up_tips(items, use_channels=channels)
    elif command.kind == "aspirate":
      await handler.aspirate(
        items, vols=list(command.volumes), use_channels=channels, liquid_height=[height] * len(items)
      )
    else:
      await handler.dispense(
        items, vols=list(command.volumes), use_channels=channels, liquid_height=[height] * len(items)
      )


async def rehearse_plan(planned: Plan, **options) -> Rehearsal:
  """Run the plan on a recording backend and replay it in the physics scene."""
  from pylabrobot.liquid_handling import LiquidHandler
  from pylabrobot.resources import set_tip_tracking, set_volume_tracking

  set_volume_tracking(True)
  set_tip_tracking(True)
  deck = build_deck(planned)
  backend = RecordingBackend(num_channels=CHANNELS)
  with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    handler = LiquidHandler(backend=backend, deck=deck)
    await handler.setup()
    await run(planned, handler)
    await handler.stop()
  return rehearse(deck, backend.steps, **options)


# ---------------------------------------------------------------- writing a script


def emit(planned: Plan, *, source: str = "") -> str:
  """The plan as a PyLabRobot script that runs on its own."""
  from . import __version__

  definitions = sorted(set(planned.labware.values()))
  carriers = sorted({p.carrier_type for p in planned.placements})
  lines = [
    f'"""{planned.protocol.name}',
    "",
    f"Written by drybench {__version__}" + (f" from {source}." if source else "."),
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
    "def build_deck():",
    "  deck = STARLetDeck()",
  ]
  for placement in planned.placements:
    lines.append(f'  {placement.carrier} = {placement.carrier_type}(name="{placement.carrier}")')
    for site, name in enumerate(placement.sites):
      if name is not None:
        lines.append(f'  {placement.carrier}[{site}] = {planned.labware[name]}(name="{name}")')
    lines.append(f"  deck.assign_child_resource({placement.carrier}, rails={placement.rails})")
  lines += [
    "  return deck",
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
    if command.kind == "discard":
      lines.append(f"  await lh.discard_tips(use_channels={channels})")
      continue
    picked = f'wells(deck, "{command.resource}", "{" ".join(command.wells)}")'
    if command.kind == "pick_up":
      lines.append(f"  await lh.pick_up_tips({picked}, use_channels={channels})")
    else:
      lines.append(
        f"  await lh.{command.kind}({picked}, vols={list(command.volumes)}, use_channels={channels}, "
        f"liquid_height=[HEIGHT] * {len(channels)})"
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


def plan_file(path) -> Tuple[Check, Optional[Plan]]:
  """Read, check and plan a protocol file. The plan is None when the check fails."""
  from .protocol import load

  checked = check(load(path))
  return checked, (plan(checked) if checked.ok else None)
