"""The physics replay on an Opentrons deck built from Opentrons' own labware definitions."""

import asyncio
import json
from pathlib import Path

import pytest

from steadyhand import opentrons_robots as ot
from steadyhand.protocol import Well, check, load

pytestmark = pytest.mark.skipif(ot._definitions() is None, reason="Opentrons' software is not installed")

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def scene():
  from steadyhand import opentrons_scene

  return opentrons_scene


def planned_example(name, profile):
  checked = check(load(EXAMPLES / name))
  return checked, ot.plan(checked, profile)


def test_slot_corners_are_where_opentrons_deck_definitions_put_them():
  import opentrons_shared_data

  root = Path(opentrons_shared_data.__file__).parent / "data" / "deck" / "definitions" / "3"
  for profile, file in ((ot.OT2, "ot2_standard.json"), (ot.FLEX, "ot3_standard.json")):
    slots = {s["id"]: s["position"] for s in json.loads((root / file).read_text())["locations"]["orderedSlots"]}
    for slot in profile.slots + ((profile.trash_slot,) if profile.trash_slot else ("12",)):
      assert list(scene().slot_origin(profile, slot)) == [float(v) for v in slots[slot][:2]], (profile.name, slot)
    (x, y), _ = scene()._TRASH[profile.robot_type]
    assert [x, y] == [float(v) for v in slots[profile.trash_slot or "12"][:2]]


def test_a_plate_is_built_with_every_well_where_its_definition_says():
  from pylabrobot.resources import Plate
  from pylabrobot.resources.well import CrossSectionType, WellBottomType

  for load_name in ("corning_96_wellplate_360ul_flat", "nest_12_reservoir_15ml", "biorad_96_wellplate_200ul_pcr"):
    body = scene()._body(load_name)
    plate = scene().labware_resource(load_name, "plate")
    assert isinstance(plate, Plate) and plate.get_size_z() == body["dimensions"]["zDimension"]
    assert len(plate.get_all_items()) == len(body["wells"])
    for name, spec in body["wells"].items():
      well = plate.get_item(name)
      assert well.name == f"plate_well_{name}"
      floor = well.get_absolute_location("c", "c", "cavity_bottom")
      assert abs(floor.x - spec["x"]) < 1e-6 and abs(floor.y - spec["y"]) < 1e-6 and abs(floor.z - spec["z"]) < 1e-6
      assert abs(well.get_size_z() - spec["depth"]) < 1e-6 and well.max_volume == spec["totalLiquidVolume"]
  flat = scene().labware_resource("corning_96_wellplate_360ul_flat", "p").get_item("A1")
  assert flat.bottom_type == WellBottomType.FLAT and flat.cross_section_type == CrossSectionType.CIRCLE
  trough = scene().labware_resource("nest_12_reservoir_15ml", "p").get_item("A1")
  assert trough.bottom_type == WellBottomType.V and trough.cross_section_type == CrossSectionType.RECTANGLE


def test_a_tip_hangs_from_the_top_of_its_rack_whatever_shape_the_hole_is():
  from pylabrobot.resources import TipRack

  # In an OT-2 rack the definition's hole is the tip; in a Flex rack it is the whole rack deep.
  for load_name in ("opentrons_96_filtertiprack_20ul", "opentrons_flex_96_filtertiprack_200ul"):
    body = scene()._body(load_name)
    rack = scene().labware_resource(load_name, "tips")
    assert isinstance(rack, TipRack) and len(rack.get_all_items()) == 96
    spot = rack.get_item("A1")
    tip = spot.get_tip()
    assert tip.total_tip_length == body["parameters"]["tipLength"]
    assert tip.fitting_depth == body["parameters"]["tipOverlap"] and tip.has_filter
    top = spot.get_absolute_location("c", "c", "b").z + tip.total_tip_length
    assert abs(top - (body["wells"]["A1"]["z"] + body["wells"]["A1"]["depth"])) < 1e-6
    assert abs(top - body["dimensions"]["zDimension"]) < 0.01


def test_the_examples_replay_clean_and_end_with_the_volumes_the_check_predicted():
  for name in ("serial_dilution.yaml", "normalization.yaml"):
    for profile in (ot.FLEX, ot.OT2):
      checked, planned = planned_example(name, profile)
      result = asyncio.run(scene().rehearse_plan(planned))
      assert result.ok, result.report()
      assert not result.collisions and not result.not_rehearsed
      size = {mount: next(p.channels for p in profile.pipettes if p.name == name) for mount, name in planned.pipettes.items()}
      moved = [a for a in planned.actions if a.kind in ("pick_up", "aspirate", "dispense", "drop")]
      assert len(result.steps) == sum(size[a.mount] for a in moved)  # one step for every channel of every action
      for well, volume in checked.volumes.items():
        assert abs(result.volumes.get(f"{well.labware}_well_{well.well}", 0.0) - volume) < 1e-3, (name, profile.name, well)


def test_eight_channels_in_one_reservoir_well_stand_nine_mm_apart_along_it():
  _, planned = planned_example("serial_dilution.yaml", ot.FLEX)
  deck, steps = asyncio.run(scene().record_plan(planned))
  first = [s for s in steps if s.kind == "aspirate" and s.command == steps[8].command]
  assert len(first) == 8 and {s.resource for s in first} == {"reservoir_well_A1"}
  ys = [s.reference[1] for s in first]
  assert all(abs((a - b) - 9.0) < 1e-6 for a, b in zip(ys, ys[1:]))  # channel 0 at the back
  centre = deck.get_resource("reservoir").get_item("A1").get_absolute_location("c", "c", "b")
  assert abs(sum(ys) / 8 - centre.y) < 1e-6 and {round(s.reference[0], 6) for s in first} == {round(centre.x, 6)}
  # A tip stops 1 mm above the floor of the well.
  assert {round(s.tip_end[2] - centre.z, 6) for s in first} == {1.0}


def test_the_replay_stops_what_the_deck_would_stop():
  from pylabrobot.resources import Coordinate

  _, planned = planned_example("serial_dilution.yaml", ot.OT2)

  def not_seated(deck):
    plate = deck.get_resource("plate")
    plate.location = plate.location + Coordinate(0, 4.5, 0)

  deck, steps = asyncio.run(scene().record_plan(planned))
  not_seated(deck)
  from steadyhand.replay import rehearse

  moved = rehearse(deck, steps, traverse_z=scene().tallest(planned) + 10, start_volumes=scene().start_volumes(planned))
  assert not moved.ok and moved.collisions and moved.collisions[0].resource == "plate"

  def no_tips(deck):
    for spot in deck.get_resource("tips_200x8_1").get_all_items()[:8]:
      spot.tracker.remove_tip()

  with pytest.raises(scene().Refused) as refused:
    asyncio.run(scene().record_plan(planned, prepare=no_tips))
  assert "action 1 (pick_up at tips_200x8_1/A1)" in str(refused.value)


def test_a_pause_to_empty_the_waste_or_reload_tips_is_followed_by_the_trackers():
  import sys

  sys.path.insert(0, str(Path(__file__).parent))
  from test_opentrons import EMPTY_IT, checked_from, crowded

  planned = ot.plan(checked_from(crowded(7, EMPTY_IT)), ot.FLEX)
  assert [a.kind for a in planned.actions].count("empty") == 1
  result = asyncio.run(scene().rehearse_plan(planned))  # without the emptying the reservoir's tracker would refuse
  assert result.ok, result.report()
  assert 0 < result.volumes["waste_well_A1"] <= 0.9 * ot.WASTE_CAPACITY
