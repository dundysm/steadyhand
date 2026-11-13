"""Plant known mistakes in a protocol that works, and see which ones steadyhand stops.

A rehearsal that passes says little unless you know what it would have failed on. Each fault
here is one specific mistake, made to a short dilution that otherwise runs clean. The suite
runs every one through the same stages a real protocol goes through (read, check, plan, run on
PyLabRobot's trackers, rehearse in the physics scene) and records the first stage that stops
it, or that nothing did.

Faults that nothing stops are kept in the list on purpose. They are the honest edge of what a
dry run can tell you today, and each one is a check waiting to be written.

Three levels of fault:

* **protocol**: the protocol file itself is wrong.
* **deck**: the file is right, but what is on the robot differs from what the plan assumed. The
  moves are recorded on the planned deck and replayed on the different one.
* **motion**: the file and the deck are right, but the moves are off, as after a bad
  calibration or a hand-edited script.
"""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional, Sequence

from .planner import PLATE_CARRIER, Plan, RunRefused, build_deck, plan, record_plan
from .protocol import ProtocolError, check, loads
from .record import Step
from .replay import rehearse, volumes
from .scene import bounds

BASE = """\
steadyhand: 0.1
name: Fault-suite base, a short dilution
labware:
  plate:     {type: Cor_96_wellplate_360ul_Fb}
  reservoir: {type: nest_1_troughplate_195000uL_Vb}
liquids:
  buffer: {in: reservoir/A1, volume: 20 mL}
  sample: {in: plate/A1:H1, volume: 200 uL}
steps:
  - transfer: {from: reservoir/A1, to: plate/A2:H4, volume: 100 uL, tips: reuse}
  - serial_dilution:
      start: plate/A1:H1
      steps: 3
      direction: right
      volume: 100 uL
      mix: {times: 2, volume: 80 uL}
"""


@dataclass(frozen=True)
class Outcome:
  caught: bool
  stage: str  # "read", "check", "plan", "run", "rehearse", or "-" when nothing stopped it
  detail: str


@dataclass(frozen=True)
class Fault:
  name: str
  level: str  # "protocol", "deck" or "motion"
  what: str  # the mistake, in a sentence
  seed: Callable[[], Outcome]


# ---------------------------------------------------------------- running one case


def _first(problems: Sequence) -> str:
  more = f" (and {len(problems) - 1} more)" if len(problems) > 1 else ""
  return f"{problems[0]}{more}"


def _planned(text: str = BASE):
  """Read, check and plan `text`. Returns the plan, or the Outcome of the stage that refused it."""
  try:
    protocol = loads(text)
  except ProtocolError as error:
    return Outcome(True, "read", _first(error.problems))
  checked = check(protocol)
  if not checked.ok:
    return Outcome(True, "check", _first(checked.problems))
  planned = plan(checked)
  if not planned.ok:
    return Outcome(True, "plan", _first(planned.problems))
  return planned


def _motion(
  planned: Plan,
  *,
  prepare: Optional[Callable] = None,
  mutate: Optional[Callable[[List[Step]], List[Step]]] = None,
  replay_on: Optional[Plan] = None,
  options: Optional[Callable[[object], dict]] = None,
) -> Outcome:
  """Record the plan, optionally change the steps or the deck, and replay it."""
  try:
    deck, steps = asyncio.run(record_plan(planned, prepare=prepare))
  except RunRefused as refused:  # PyLabRobot's own trackers and checks refused a command
    return Outcome(True, "run", str(refused)[:150])
  if mutate is not None:
    steps = mutate(list(steps))
  start = None
  if replay_on is not None:
    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      deck = build_deck(replay_on)
    start = volumes(deck)  # this deck never ran, so what it holds now is where it starts
  result = rehearse(deck, steps, start_volumes=start, **(options(deck) if options else {}))
  if result.collisions:
    hit = result.collisions[0]
    return Outcome(
      True, "rehearse", f"{len(result.collisions)} collisions; first: the {hit.part} into {hit.resource} on {hit.phase}"
    )
  if result.liquid_failures:
    first = result.liquid_failures[0]
    return Outcome(True, "rehearse", f"{len(result.liquid_failures)} tips out of the liquid; first: {first.describe()}")
  return Outcome(False, "-", "ran clean")


def _text(old: str, new: str) -> Callable[[], Outcome]:
  """A fault made by changing the protocol file's text."""

  def seed() -> Outcome:
    assert old in BASE, old
    planned = _planned(BASE.replace(old, new))
    return planned if isinstance(planned, Outcome) else _motion(planned)

  return seed


def _whole_text(text: str) -> Outcome:
  planned = _planned(text)
  return planned if isinstance(planned, Outcome) else _motion(planned)


def _on_plan(**how) -> Callable[[], Outcome]:
  """A fault made after planning the unchanged protocol. `how` values are called with the plan."""

  def seed() -> Outcome:
    planned = _planned()
    assert isinstance(planned, Plan), planned
    return _motion(planned, **{key: (value(planned) if key == "replay_on" else value) for key, value in how.items()})

  return seed


# ---------------------------------------------------------------- changes to the deck


def _carrier_moved(planned: Plan) -> Plan:
  return replace(
    planned,
    placements=[replace(p, rails=p.rails + 1) if p.carrier_type == PLATE_CARRIER else p for p in planned.placements],
  )


def _sites_swapped(planned: Plan) -> Plan:
  swap = {"plate": "reservoir", "reservoir": "plate"}
  return replace(
    planned, placements=[replace(p, sites=tuple(swap.get(s, s) if s else s for s in p.sites)) for p in planned.placements]
  )


def _plate_is(definition: str) -> Callable[[Plan], Plan]:
  return lambda planned: replace(planned, labware={**planned.labware, "plate": definition})


def _lid_on(deck) -> None:
  from pylabrobot.resources import Lid

  plate = deck.get_resource("plate")
  plate.assign_child_resource(
    Lid(name="plate_lid", size_x=plate.get_size_x(), size_y=plate.get_size_y(), size_z=8.0, nesting_z_height=6.0)
  )


def _tips_missing(deck) -> None:
  for spot in deck.get_resource("tips_300_1").get_all_items()[:8]:  # the first column
    spot.tracker.remove_tip()


# ---------------------------------------------------------------- changes to the moves


def _shift(dx: float = 0.0, dy: float = 0.0, dz: float = 0.0, *, kinds: Sequence[str], on: str = "") -> Callable:
  def mutate(steps: List[Step]) -> List[Step]:
    return [
      replace(s, reference=(s.reference[0] + dx, s.reference[1] + dy, s.reference[2] + dz))
      if s.kind in kinds and s.reference is not None and s.resource.startswith(on)
      else s
      for s in steps
    ]

  return mutate


def _tips_are(definition: str) -> Callable:
  """The tips on the channels are this kind, not the kind the plan picked up."""

  def mutate(steps: List[Step]) -> List[Step]:
    import pylabrobot.resources as resources

    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      tip = getattr(resources, definition)(name="probe").get_item("A1").get_tip()
    return [
      replace(s, tip_length=float(tip.total_tip_length), fitting_depth=float(tip.fitting_depth))
      if s.kind in ("aspirate", "dispense", "drop_tip")
      else s
      for s in steps
    ]

  return mutate


def _channels_squeezed(steps: List[Step]) -> List[Step]:
  """Channel 1 sits 4 mm from channel 0 in the reservoir; the head cannot bring them closer than 9 mm."""
  backs: Dict[int, float] = {s.command: s.reference[1] for s in steps if s.channel == 0 and s.reference is not None}
  return [
    replace(s, reference=(s.reference[0], backs[s.command] - 4.0, s.reference[2]))
    if s.channel == 1 and s.kind == "aspirate" and s.resource.startswith("reservoir") and s.command in backs
    else s
    for s in steps
  ]


def _below_the_plate_top(deck) -> dict:
  return {"traverse_z": bounds(deck.get_resource("plate"))[1][2] - 5.0}


# ---------------------------------------------------------------- the faults

FAULTS: List[Fault] = [
  # the protocol file is wrong
  Fault("source-runs-dry", "protocol", "The buffer reservoir is declared with 2 mL; the steps draw 2.4 mL from it.",
        _text("buffer: {in: reservoir/A1, volume: 20 mL}", "buffer: {in: reservoir/A1, volume: 2 mL}")),
  Fault("well-overflows", "protocol", "300 uL of buffer goes into wells that then take another 100 uL; they hold 360 uL.",
        _text("to: plate/A2:H4, volume: 100 uL", "to: plate/A2:H4, volume: 300 uL")),
  Fault("volume-too-small", "protocol", "The dilution moves 0.5 uL, below the 1 uL the file allows by default.",
        _text("      volume: 100 uL\n", "      volume: 0.5 uL\n")),
  Fault("mix-more-than-the-well-holds", "protocol", "The mix draws 250 uL from wells that hold 200 uL.",
        _text("mix: {times: 2, volume: 80 uL}", "mix: {times: 2, volume: 250 uL}")),
  Fault("well-not-on-the-plate", "protocol", "The transfer names column 13 of a 12-column plate.",
        _text("to: plate/A2:H4", "to: plate/A2:H13")),
  Fault("amount-without-a-unit", "protocol", "A volume is written as a bare number.",
        _text("to: plate/A2:H4, volume: 100 uL", "to: plate/A2:H4, volume: 100")),
  Fault("labware-named-waste", "protocol", "The plate is named waste, a name the planner keeps for its own waste reservoirs.",
        lambda: _whole_text(BASE.replace("  plate:  ", "  waste:  ").replace("plate/", "waste/"))),
  Fault("no-diluent", "protocol", "The step that fills the wells with buffer is missing, so the series is not diluted at all.",
        _text("  - transfer: {from: reservoir/A1, to: plate/A2:H4, volume: 100 uL, tips: reuse}\n", "")),
  Fault("dilution-starts-in-the-wrong-column", "protocol", "The series starts in column 2, not column 1 where the sample is.",
        _text("start: plate/A1:H1", "start: plate/A2:H2")),
  Fault("one-tip-down-the-series", "protocol", "The same tip is carried down each dilution series, so sample carries over.",
        _text("      volume: 100 uL\n", "      volume: 100 uL\n      tips: reuse\n")),
  # the deck is not what the plan assumed
  Fault("carrier-one-rail-off", "deck", "The plate carrier sits one rail (22.5 mm) to the right of where the plan put it.",
        _on_plan(replay_on=_carrier_moved)),
  Fault("plate-and-reservoir-swapped", "deck", "The plate and the reservoir are on each other's carrier sites.",
        _on_plan(replay_on=_sites_swapped)),
  Fault("384-plate-loaded", "deck", "A 384-well plate is on the deck where the plan expects the 96-well plate.",
        _on_plan(replay_on=_plate_is("Greiner_384_wellplate_28ul_Fb"))),
  Fault("deep-well-plate-loaded", "deck", "A 2 mL deep-well plate is on the deck where the plan expects the shallow plate.",
        _on_plan(replay_on=_plate_is("Cor_96_wellplate_2mL_Vb"))),
  Fault("lid-left-on", "deck", "The plate still has its lid on.", _on_plan(prepare=_lid_on)),
  Fault("tips-missing", "deck", "The first column of the tip rack is empty.", _on_plan(prepare=_tips_missing)),
  Fault("longer-tips-loaded", "deck", "1000 uL tips are in the rack where the plan expects 300 uL tips; they are 35 mm longer.",
        _on_plan(mutate=_tips_are("hamilton_96_tiprack_1000uL_filter"))),
  Fault("shorter-tips-loaded", "deck", "50 uL tips are in the rack where the plan expects 300 uL tips; they are 9.5 mm shorter.",
        _on_plan(mutate=_tips_are("hamilton_96_tiprack_50uL_filter"))),
  # the moves are off
  Fault("x-offset-onto-the-wall", "motion", "Every move into the plate is 4.5 mm to the right, over the wall between wells.",
        _on_plan(mutate=_shift(dx=4.5, kinds=("aspirate", "dispense"), on="plate"))),
  Fault("too-deep", "motion", "Every aspirate stops 4 mm lower than planned, 3 mm under the well floor.",
        _on_plan(mutate=_shift(dz=-4.0, kinds=("aspirate",)))),
  Fault("travel-too-low", "motion", "Channels travel 5 mm below the top of the plate instead of well above the deck.",
        _on_plan(options=_below_the_plate_top)),
  Fault("aspirate-above-the-liquid", "motion", "Every aspirate from the plate stops 9 mm above the well floor, in air.",
        _on_plan(mutate=_shift(dz=8.0, kinds=("aspirate",), on="plate"))),
  Fault("dispense-from-high-up", "motion", "Every dispense is released 30 mm above the well, so it would splash.",
        _on_plan(mutate=_shift(dz=30.0, kinds=("dispense",)))),
  Fault("channels-too-close", "motion", "Two channels are 4 mm apart in the reservoir; the head cannot bring them closer than 9 mm.",
        _on_plan(mutate=_channels_squeezed)),
]


# ---------------------------------------------------------------- the report


@dataclass(frozen=True)
class Result:
  fault: Fault
  outcome: Outcome


@dataclass
class Report:
  clean: Outcome  # the unchanged protocol; it has to run clean for the rest to mean anything
  results: List[Result]
  robot: str = "Hamilton STARlet"

  @property
  def caught(self) -> List[Result]:
    return [r for r in self.results if r.outcome.caught]

  @property
  def missed(self) -> List[Result]:
    return [r for r in self.results if not r.outcome.caught]

  def text(self) -> str:
    lines = [
      f"steadyhand faults: {len(self.caught)} of {len(self.results)} planted mistakes stopped  ({self.robot})",
      f"  the unchanged protocol: {'ran clean' if not self.clean.caught else 'FAILED at ' + self.clean.stage + ': ' + self.clean.detail}",
    ]
    width = max(len(r.fault.name) for r in self.results)
    for level in ("protocol", "deck", "motion"):
      lines.append(f"  {level}:")
      for r in (r for r in self.results if r.fault.level == level):
        where = f"stopped at {r.outcome.stage}" if r.outcome.caught else "NOT STOPPED"
        lines.append(f"    {r.fault.name:<{width}}  {where:<19}  {r.outcome.detail if r.outcome.caught else r.fault.what}")
    return "\n".join(lines)

  def markdown(self) -> str:
    from . import __version__

    lines = [
      f"# What steadyhand stops, and what it does not: {self.robot}",
      "",
      f"Written by `steadyhand faults`, version {__version__}. Each row is one mistake planted in a short",
      "dilution that otherwise runs clean. \"Stopped at\" is the first stage that refused it.",
      "",
      f"**{len(self.caught)} of {len(self.results)} planted mistakes stopped.** The unchanged protocol "
      + ("ran clean." if not self.clean.caught else f"FAILED at {self.clean.stage}."),
      "",
      "| mistake | level | stopped at | what happened |",
      "|---|---|---|---|",
    ]
    for r in self.results:
      stage = r.outcome.stage if r.outcome.caught else "**not stopped**"
      lines.append(f"| {r.fault.what} | {r.fault.level} | {stage} | {r.outcome.detail.replace('|', '/')} |")
    lines += [
      "",
      "Stages: `read` (the file is not a valid protocol), `check` (the liquid ledger), `plan` (tips, channels,",
      "deck), `run` (PyLabRobot's own tip and volume trackers refused a command), `rehearse` (a collision in",
      "the physics scene, or a tip out of the liquid).",
      "",
      "A mistake that is not stopped runs to the end with every stage passing. Those rows are the checks",
      "steadyhand does not have yet.",
      "",
    ]
    return "\n".join(lines)


def run_suite(faults: Sequence[Fault] = FAULTS) -> Report:
  planned = _planned()
  clean = planned if isinstance(planned, Outcome) else _motion(planned)
  return Report(clean=clean, results=[Result(fault, fault.seed()) for fault in faults])
