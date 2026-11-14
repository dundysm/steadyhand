"""The seeded-fault suite for the Opentrons robots: the same idea as `faults`, on their decks.

Each fault is one specific mistake made to the short dilution `faults.BASE` describes, which
runs clean on a Flex and an OT-2. The stages are the same (read, check, plan, run on
PyLabRobot's trackers, rehearse in the physics scene), with the Opentrons planner and a deck
built from Opentrons' labware definitions.

Opentrons' own simulator is not a stage here. It takes the protocol file, and no fault at the
deck or motion level changes that file.
"""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import replace
from typing import Callable, List, Optional, Sequence

from . import opentrons_robots as robots
from .faults import BASE, Fault, Outcome, Report, Result, _first, _shift
from .opentrons_scene import CLEARANCE, Refused, _body, build_deck, record_plan, start_volumes, tallest
from .protocol import ProtocolError, check, loads
from .record import Step
from .replay import rehearse
from .scene import bounds

Plan = robots.OpentronsPlan


def suite(profile: robots.Profile) -> List[Fault]:
  """The faults, bound to one robot."""

  def planned_from(text: str = BASE):
    """Read, check and plan `text`. Returns the plan, or the Outcome of the stage that refused it."""
    try:
      protocol = loads(text)
    except ProtocolError as error:
      return Outcome(True, "read", _first(error.problems))
    checked = check(protocol)
    if not checked.ok:
      return Outcome(True, "check", _first(checked.problems))
    planned = robots.plan(checked, profile)
    if not planned.ok:
      return Outcome(True, "plan", _first(planned.problems))
    return planned

  def motion(
    planned: Plan,
    *,
    prepare: Optional[Callable] = None,
    mutate: Optional[Callable[[Plan, List[Step]], List[Step]]] = None,
    replay_on: Optional[Callable[[Plan], Plan]] = None,
    moved: Optional[Callable] = None,
    options: Optional[Callable[[object], dict]] = None,
  ) -> Outcome:
    """Record the plan, optionally change the steps or the deck, and replay it."""
    try:
      deck, steps = asyncio.run(record_plan(planned, prepare=prepare))
    except Refused as refused:  # PyLabRobot's own trackers and checks refused an action
      return Outcome(True, "run", str(refused)[:150])
    if mutate is not None:
      steps = mutate(planned, list(steps))
    if replay_on is not None or moved is not None:
      with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        deck = build_deck(replay_on(planned) if replay_on else planned)
      if moved is not None:
        moved(deck)
    settings = {"traverse_z": tallest(planned) + CLEARANCE, "start_volumes": start_volumes(planned)}
    settings.update(options(deck) if options else {})
    result = rehearse(deck, steps, **settings)
    if result.collisions:
      hit = result.collisions[0]
      return Outcome(
        True, "rehearse", f"{len(result.collisions)} collisions; first: the {hit.part} into {hit.resource} on {hit.phase}"
      )
    if result.liquid_failures:
      first = result.liquid_failures[0]
      return Outcome(True, "rehearse", f"{len(result.liquid_failures)} tips out of the liquid; first: {first.describe()}")
    return Outcome(False, "-", "ran clean")

  def text(*changes: str) -> Callable[[], Outcome]:
    """A fault made by changing the protocol file's text: pairs of old and new."""

    def seed() -> Outcome:
      changed = BASE
      for old, new in zip(changes[::2], changes[1::2]):
        assert old in changed, old
        changed = changed.replace(old, new)
      planned = planned_from(changed)
      return planned if isinstance(planned, Outcome) else motion(planned)

    return seed

  def on_plan(**how) -> Callable[[], Outcome]:
    """A fault made after planning the unchanged protocol."""

    def seed() -> Outcome:
      planned = planned_from()
      assert isinstance(planned, Plan), planned
      return motion(planned, **how)

    return seed

  # changes to the deck
  def slots_swapped(planned: Plan) -> Plan:
    swap = {"plate": "reservoir", "reservoir": "plate"}
    return replace(planned, slots={swap.get(name, name): slot for name, slot in planned.slots.items()})

  def plate_is(load_name: str) -> Callable[[Plan], Plan]:
    return lambda planned: replace(planned, labware={**planned.labware, "plate": load_name})

  def plate_not_seated(deck) -> None:
    from pylabrobot.resources import Coordinate

    plate = deck.get_resource("plate")
    plate.location = plate.location + Coordinate(0, 4.5, 0)

  def tips_missing(deck) -> None:
    rack = next(child for child in deck.children if child.name.startswith("tips_"))
    for spot in rack.get_all_items()[:8]:  # the first column
      spot.tracker.remove_tip()

  # changes to the moves
  def tips_are(capacity: float) -> Callable:
    """The tips on the pipette are the robot's tips of this size, not the ones the plan picked up."""
    rack = next(r for p in profile.pipettes for c, r in p.tips if c == capacity)
    parameters = _body(rack)["parameters"]

    def mutate(planned: Plan, steps: List[Step]) -> List[Step]:
      return [
        replace(s, tip_length=float(parameters["tipLength"]), fitting_depth=float(parameters.get("tipOverlap", 0.0)))
        if s.kind in ("aspirate", "dispense", "drop_tip")
        else s
        for s in steps
      ]

    return mutate

  def shift(**how) -> Callable:
    return lambda planned, steps: _shift(**how)(steps)

  def below_the_plate_top(deck) -> dict:
    return {"traverse_z": bounds(deck.get_resource("plate"))[1][2] - 5.0}

  title = profile.title
  big = max(c for p in profile.pipettes for c, _ in p.tips)
  return [
    # the protocol file is wrong
    Fault("source-runs-dry", "protocol", "The buffer reservoir is declared with 2 mL; the steps draw 2.4 mL from it.",
          text("buffer: {in: reservoir/A1, volume: 20 mL}", "buffer: {in: reservoir/A1, volume: 2 mL}")),
    Fault("well-overflows", "protocol", "300 uL of buffer goes into wells that then take another 100 uL; they hold 360 uL.",
          text("to: plate/A2:H4, volume: 100 uL", "to: plate/A2:H4, volume: 300 uL")),
    Fault("well-not-on-the-plate", "protocol", "The transfer names column 13 of a 12-column plate.",
          text("to: plate/A2:H4", "to: plate/A2:H13")),
    Fault("smaller-than-any-pipette-moves", "protocol",
          f"The file allows 0.5 uL moves and the dilution asks for one; no pipette on the {title} moves less than 1 uL.",
          text("steps:\n", "limits: {min_volume: 0.5 uL}\nsteps:\n", "      volume: 100 uL\n", "      volume: 0.5 uL\n",
               "mix: {times: 2, volume: 80 uL}", "mix: {times: 2, volume: 50 uL}")),
    Fault("more-plates-than-slots", "protocol", f"Ten more plates are declared; with tips they need more slots than the {title} has.",
          text("  reservoir: ", "".join(f"  extra{n}: {{type: corning_96_wellplate_360ul_flat}}\n" for n in range(10)) + "  reservoir: ")),
    Fault("too-shallow-to-reach", "protocol",
          "The sample wells hold 25 uL in a flat-bottom plate: under 1 mm of liquid, below where the tip stops.",
          text("sample: {in: plate/A1:H1, volume: 200 uL}", "sample: {in: plate/A1:H1, volume: 25 uL}",
               "      volume: 100 uL\n", "      volume: 20 uL\n")),
    Fault("source-drawn-below-the-tip", "protocol",
          "The sample wells hold 110 uL and the series takes 100 uL: the last of each draw is under the tip, so it is air.",
          text("sample: {in: plate/A1:H1, volume: 200 uL}", "sample: {in: plate/A1:H1, volume: 110 uL}")),
    Fault("reused-tip-into-samples", "protocol",
        "The buffer is topped up into wells that now hold sample, with one reused tip: it goes back into the reservoir carrying sample.",
          text("      mix: {times: 2, volume: 80 uL}\n",
                "      mix: {times: 2, volume: 80 uL}\n  - transfer: {from: reservoir/A1, to: plate/A1:H4, volume: 20 uL, tips: reuse}\n")),
    Fault("one-tip-down-the-series", "protocol", "The same tip is carried down each dilution series, so sample carries over.",
          text("      volume: 100 uL\n", "      volume: 100 uL\n      tips: reuse\n")),
    # the deck is not what the plan assumed
    Fault("plate-and-reservoir-swapped", "deck", "The plate and the reservoir are in each other's slots.",
          on_plan(replay_on=slots_swapped)),
    Fault("plate-not-seated", "deck", "The plate sits 4.5 mm towards the back of its slot, half a well off.",
          on_plan(moved=plate_not_seated)),
    Fault("384-plate-loaded", "deck", "A 384-well plate is on the deck where the plan expects the 96-well plate.",
          on_plan(replay_on=plate_is("corning_384_wellplate_112ul_flat"))),
    Fault("deep-well-plate-loaded", "deck", "A 2 mL deep-well plate is on the deck where the plan expects the shallow plate.",
          on_plan(replay_on=plate_is("nest_96_wellplate_2ml_deep"))),
    Fault("pcr-plate-loaded", "deck", "A 200 uL PCR plate is on the deck where the plan expects the flat-bottom plate.",
          on_plan(replay_on=plate_is("biorad_96_wellplate_200ul_pcr"))),
    Fault("tips-missing", "deck", "The first column of the tip rack is empty.", on_plan(prepare=tips_missing)),
    Fault("longer-tips-loaded", "deck", f"{big:g} uL tips are in the rack where the plan expects 200 uL tips.",
          on_plan(mutate=tips_are(big))),
    # the moves are off
    Fault("x-offset-onto-the-wall", "motion", "Every move into the plate is 4.5 mm to the right, over the wall between wells.",
          on_plan(mutate=shift(dx=4.5, kinds=("aspirate", "dispense"), on="plate"))),
    Fault("too-deep", "motion", "Every aspirate stops 4 mm lower than planned, 3 mm under the well floor.",
          on_plan(mutate=shift(dz=-4.0, kinds=("aspirate",)))),
    Fault("travel-too-low", "motion", "The pipette travels 5 mm below the top of the plate instead of above everything on the deck.",
          on_plan(options=below_the_plate_top)),
    Fault("aspirate-above-the-liquid", "motion", "Every aspirate from the plate stops 9 mm above the well floor, in air.",
          on_plan(mutate=shift(dz=8.0, kinds=("aspirate",), on="plate"))),
    Fault("dispense-from-high-up", "motion", "Every dispense is released 30 mm above the well, so it would splash.",
          on_plan(mutate=shift(dz=30.0, kinds=("dispense",)))),
  ]


def run_suite(profile: robots.Profile = robots.FLEX) -> Report:
  """Run every fault on one robot. The unchanged protocol has to run clean for the rest to mean anything."""
  return Report(
    clean=_clean(profile), results=[Result(fault, fault.seed()) for fault in suite(profile)], robot=profile.title
  )


def _clean(profile: robots.Profile) -> Outcome:
  checked = check(loads(BASE))
  planned = robots.plan(checked, profile)
  if not planned.ok:
    return Outcome(True, "plan", _first(planned.problems))
  try:
    deck, steps = asyncio.run(record_plan(planned))
  except Refused as refused:
    return Outcome(True, "run", str(refused)[:150])
  result = rehearse(deck, steps, traverse_z=tallest(planned) + CLEARANCE, start_volumes=start_volumes(planned))
  return Outcome(not result.ok, "rehearse" if not result.ok else "-", result.report() if not result.ok else "ran clean")
