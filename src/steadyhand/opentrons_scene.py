"""Replay an Opentrons plan in the physics scene.

The scene and the replay were written for PyLabRobot decks. To reuse them, this builds the deck
an Opentrons plan describes out of PyLabRobot resources, from the labware definitions Opentrons
ships, and sends the plan's actions to a recording backend the way the Hamilton plan is sent.
The replay then checks the same things as on the Hamilton: collisions, where each tip stops
against the liquid, and PyLabRobot's own tip and volume tracking.

What is taken from Opentrons' definitions: every well and tip position, well depth and width,
bottom shape, labware height, tip length and how far a tip slides onto the pipette. What is
not: the pipette itself. A channel is the same nominal 8 mm barrel as on the Hamilton, an
8-channel pipette is eight of them 9 mm apart, and travel is straight up, across above
everything on the deck, and straight down. The Flex's trash bin is a box of its nominal height
in its slot.
"""

from __future__ import annotations

import json
import warnings
from typing import Any, Dict, List, Optional, Tuple

from .opentrons_robots import ROWS, OpentronsPlan, Profile, _definitions
from .record import RecordingBackend, Step
from .replay import Rehearsal, rehearse

SLOT = (127.76, 85.48)  # mm: the footprint of a deck slot
DECK_THICKNESS = 10.0  # mm of deck drawn below the labware
CLEARANCE = 10.0  # mm kept between a travelling tip and the tallest thing on the deck
PITCH = 9.0  # mm between the channels of an 8-channel pipette

# Where each robot's trash stands and how big it is: (x, y), (size x, size y, size z), all in mm.
_TRASH: Dict[str, Tuple[Tuple[float, float], Tuple[float, float, float]]] = {
  "OT-2": ((265.0, 271.5), (172.86, 165.86, 82.0)),  # the fixed trash, slot 12
  "Flex": ((328.0, 321.0), (SLOT[0], SLOT[1], 40.0)),  # a trash bin in slot A3
}


class Refused(RuntimeError):
  """PyLabRobot's own tracking said no to one action of an Opentrons plan."""

  def __init__(self, number: int, action: Any, reason: str):
    where = f"{action.labware}/{action.well}" if action.labware else action.mount
    super().__init__(f"action {number} ({action.kind} at {where}): {reason}")
    self.number, self.action, self.reason = number, action, reason


def slot_origin(profile: Profile, slot: str) -> Tuple[float, float]:
  """The front-left corner of a deck slot, in mm."""
  if profile.robot_type == "OT-2":
    number = int(slot) - 1
    return 132.5 * (number % 3), 90.5 * (number // 3)
  return 164.0 * (int(slot[1]) - 1), 107.0 * "DCBA".index(slot[0])


def _body(load_name: str) -> Dict[str, Any]:
  root = _definitions()
  if root is None:
    raise RuntimeError("Opentrons' labware definitions are needed for the physics replay: pip install 'steadyhand[opentrons]'")
  versions = sorted((p for p in (root / load_name).glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem))
  return json.loads(versions[-1].read_text())


def labware_resource(load_name: str, name: str):
  """A plate, reservoir or tip rack Opentrons ships, as a PyLabRobot resource called `name`.

  Wells are named `<name>_well_<A1>`, as PyLabRobot's own plates name them.
  """
  from pylabrobot.resources import Coordinate, Plate, Tip, TipRack, TipSpot, Well
  from pylabrobot.resources.well import CrossSectionType, WellBottomType

  body = _body(load_name)
  size = body["dimensions"]
  parameters = body["parameters"]
  bottoms = {
    well: {"flat": WellBottomType.FLAT, "u": WellBottomType.U, "v": WellBottomType.V}.get(
      group.get("metadata", {}).get("wellBottomShape", ""), WellBottomType.UNKNOWN
    )
    for group in body.get("groups", [])
    for well in group["wells"]
  }
  items: Dict[str, Any] = {}
  for column in body["ordering"]:
    for well in column:
      spec = body["wells"][well]
      if parameters.get("isTiprack"):
        length, overlap = float(parameters["tipLength"]), float(parameters.get("tipOverlap", 0.0))
        capacity = float(spec["totalLiquidVolume"])

        def make_tip(length=length, overlap=overlap, capacity=capacity):
          return Tip(
            has_filter="filter" in load_name, total_tip_length=length, maximal_volume=capacity, fitting_depth=overlap
          )

        # A tip hangs from the top of its hole. The spot is as wide as the pitch, so the frame
        # between tips, which the definitions do not describe, is not drawn as a wall.
        item = TipSpot(f"tipspot_{well}", PITCH, PITCH, make_tip=make_tip)  # the rack puts its own name in front
        item.location = Coordinate(spec["x"] - PITCH / 2, spec["y"] - PITCH / 2, spec["z"] + spec["depth"] - length)
      else:
        round_ = spec["shape"] == "circular"
        wide, long = (spec["diameter"], spec["diameter"]) if round_ else (spec["xDimension"], spec["yDimension"])
        item = Well(
          f"well_{well}",  # the plate puts its own name in front
          wide,
          long,
          spec["depth"],
          material_z_thickness=0,
          bottom_type=bottoms.get(well, WellBottomType.UNKNOWN),
          max_volume=float(spec["totalLiquidVolume"]),
          cross_section_type=CrossSectionType.CIRCLE if round_ else CrossSectionType.RECTANGLE,
        )
        item.location = Coordinate(spec["x"] - wide / 2, spec["y"] - long / 2, spec["z"])
      items[well] = item
  kind = TipRack if parameters.get("isTiprack") else Plate
  return kind(name, size["xDimension"], size["yDimension"], size["zDimension"], ordered_items=items, model=load_name)


def build_deck(planned: OpentronsPlan):
  """The deck the plan describes, as PyLabRobot resources, with the protocol's starting liquids in place."""
  from pylabrobot.resources import Coordinate, Deck, Trash

  profile = planned.profile
  (trash_x, trash_y), trash_size = _TRASH[profile.robot_type]
  with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    deck = Deck(
      size_x=trash_x + trash_size[0] if profile.robot_type == "OT-2" else 328.0 + SLOT[0],
      size_y=trash_y + trash_size[1] if profile.robot_type == "OT-2" else 321.0 + SLOT[1],
      size_z=DECK_THICKNESS,
      origin=Coordinate(0, 0, -DECK_THICKNESS),
    )
    deck.assign_child_resource(Trash("trash", *trash_size), location=Coordinate(trash_x, trash_y, DECK_THICKNESS))
    for name, slot in planned.slots.items():
      x, y = slot_origin(profile, slot)
      deck.assign_child_resource(labware_resource(planned.labware[name], name), location=Coordinate(x, y, DECK_THICKNESS))
  for wells, volume in planned.protocol.liquids.values():
    for well in wells:
      deck.get_resource(well.labware).get_item(well.well).tracker.set_liquids([(None, volume)])
  return deck


def start_volumes(planned: OpentronsPlan) -> Dict[str, float]:
  """Microlitres in every well before the first action, by the name its PyLabRobot resource has."""
  return {
    f"{well.labware}_well_{well.well}": float(volume)
    for wells, volume in planned.protocol.liquids.values()
    for well in wells
  }


def tallest(planned: OpentronsPlan) -> float:
  """The height of the tallest thing on the deck, in mm."""
  heights = [_TRASH[planned.profile.robot_type][1][2]]
  heights += [_body(load_name)["dimensions"]["zDimension"] for load_name in set(planned.labware.values())]
  return max(heights)


async def record_plan(planned: OpentronsPlan, *, prepare=None) -> Tuple[Any, List[Step]]:
  """Run the plan on a recording backend. Returns the deck it ran on and the steps it recorded.

  `prepare`, if given, is called with the deck before the run, to change what is on it.
  The left pipette's channels come first, then the right's.
  """
  from pylabrobot.liquid_handling import LiquidHandler
  from pylabrobot.resources import Coordinate, set_tip_tracking, set_volume_tracking

  set_volume_tracking(True)
  set_tip_tracking(True)
  deck = build_deck(planned)
  if prepare is not None:
    prepare(deck)
  sizes = {p.name: p.channels for p in planned.profile.pipettes}
  channels: Dict[str, List[int]] = {}
  for mount in ("left", "right"):
    if mount in planned.pipettes:
      first = sum(len(c) for c in channels.values())
      channels[mount] = list(range(first, first + sizes[planned.pipettes[mount]]))
  backend = RecordingBackend(num_channels=max(1, sum(len(c) for c in channels.values())))
  height = planned.pipetting_height
  with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    handler = LiquidHandler(backend=backend, deck=deck)
    await handler.setup()
    for number, action in enumerate(planned.actions, start=1):
      if action.kind == "wait":
        continue
      if action.kind == "reload":
        for name in action.racks:
          deck.get_resource(name).fill()
        continue
      if action.kind == "empty":
        for name in action.racks:
          for well in deck.get_resource(name).get_all_items():
            well.tracker.set_liquids([])
        continue
      use = channels[action.mount]
      try:
        if action.kind == "drop":
          await handler.discard_tips(use_channels=use)
          continue
        resource = deck.get_resource(action.labware)
        items = [resource.get_item(well) for well in action.wells]
        if action.kind == "pick_up":
          await handler.pick_up_tips(items, use_channels=use)
          continue
        # Eight channels in one reservoir well stand 9 mm apart along it, the back one first.
        together = len(items) > 1 and len(set(action.wells)) == 1
        offsets = [Coordinate(0, (3.5 - i) * PITCH if together else 0, 0) for i in range(len(items))]
        send = handler.aspirate if action.kind == "aspirate" else handler.dispense
        await send(
          items,
          vols=[action.amount] * len(items),
          use_channels=use,
          liquid_height=[height] * len(items),
          offsets=offsets,
          spread="custom",
        )
      except Exception as error:  # a tracker or a check inside PyLabRobot said no
        raise Refused(number, action, str(error)) from error
    await handler.stop()
  return deck, backend.steps


async def rehearse_plan(planned: OpentronsPlan, *, prepare=None, **options) -> Rehearsal:
  """Run the plan on a recording backend and replay it in the physics scene."""
  deck, steps = await record_plan(planned, prepare=prepare)
  options.setdefault("traverse_z", tallest(planned) + CLEARANCE)
  options.setdefault("start_volumes", start_volumes(planned))
  return rehearse(deck, steps, **options)


__all__ = ["Refused", "ROWS", "build_deck", "labware_resource", "record_plan", "rehearse_plan", "slot_origin"]
