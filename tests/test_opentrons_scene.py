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


# ---------------------------------------------------------------- how high liquid stands in a well


def test_liquid_height_comes_from_the_inside_shape_of_the_well():
  import math

  cone = [{"shape": "conical", "bottomDiameter": 2.0, "topDiameter": 6.0, "bottomHeight": 1.0, "topHeight": 4.0}]
  cap = [{"shape": "spherical", "radiusOfCurvature": 3.0, "bottomHeight": 0.0, "topHeight": 1.0}]
  box = [{"shape": "cuboidal", "bottomXDimension": 2.0, "bottomYDimension": 4.0, "topXDimension": 4.0,
          "topYDimension": 4.0, "bottomHeight": 0.0, "topHeight": 3.0, "xCount": 2}]
  # A frustum, a spherical cap and a wedge, by their textbook formulas.
  assert abs(scene().well_volume(cone, 4.0) - math.pi * 3 / 3 * (1 + 3 + 9)) < 1e-9
  assert scene().well_volume(cone, 1.0) == 0.0 and scene().well_volume(cone, 9.0) == scene().well_volume(cone, 4.0)
  assert abs(scene().well_volume(cap, 1.0) - math.pi * 1 * (9 - 1) / 3) < 1e-9
  assert abs(scene().well_volume(box, 3.0) - 2 * 3 * 4 * 3.0) < 1e-9  # mean width 3, twice over
  for sections in (cone, cap, box, cap + cone):
    top = max(s["topHeight"] for s in sections)
    for part in (0.1, 0.5, 0.9):
      height = scene().well_height(sections, scene().well_volume(sections, top * part))
      assert abs(scene().well_volume(sections, height) - scene().well_volume(sections, top * part)) < 1e-6
    assert scene().well_height(sections, 1e9) == top  # more than it holds stands at the top


def test_the_same_volumes_as_opentrons_own_maths_for_every_labware_offered():
  try:
    from opentrons.protocol_engine.state import inner_well_math_utils as theirs
    from opentrons_shared_data.labware.labware_definition import InnerWellGeometry
  except Exception:
    pytest.skip("Opentrons' software will not load on this Python")
  compared, left_out = 0, []
  for load_name in ot.shipped_names():
    for geometry in scene()._body(load_name).get("innerLabwareGeometry", {}).values():
      sections = geometry["sections"]
      if any(section["shape"] not in scene()._SHAPES for section in sections):
        left_out.append(load_name)
        continue
      model = InnerWellGeometry.model_validate(geometry)
      top = max(section["topHeight"] for section in sections)
      for part in (0.02, 0.1, 0.25, 0.5, 0.75, 0.99):
        mine = scene().well_volume(sections, top * part)
        expected = theirs.find_volume_inner_well_geometry(target_height=top * part, well_geometry=model)
        assert abs(mine - expected) <= 1e-9 * max(1.0, expected), (load_name, part)
        compared += 1
  assert compared >= 250 and sorted(set(left_out)) == ["usascientific_12_reservoir_22ml"]


def test_a_film_of_liquid_in_a_tapered_reservoir_is_a_sure_failure_not_a_maybe():
  from steadyhand.protocol import loads
  from steadyhand.scene import liquid_height, liquid_height_is_known

  trough = scene().labware_resource("nest_12_reservoir_15ml", "trough").get_item("A1")
  assert liquid_height_is_known(trough)  # a V bottom, but its real shape is known
  assert liquid_height(trough, 180.0) < 1.0 < liquid_height(trough, 500.0)
  odd = scene().labware_resource("usascientific_12_reservoir_22ml", "trough").get_item("A1")
  assert not liquid_height_is_known(odd)  # its floor is a shape this does not work out

  def planned(volume):
    return ot.plan(check(loads(f"""
steadyhand: 0.1
name: master mix from a trough
labware:
  trough: {{type: nest_12_reservoir_15ml}}
  plate: {{type: opentrons_96_wellplate_200ul_pcr_full_skirt}}
liquids:
  mix: {{in: trough/A1, volume: {volume}}}
steps:
  - transfer: {{from: trough/A1, to: plate/A1:H1, volume: 18 uL}}
""")), ot.FLEX)

  thin = asyncio.run(scene().rehearse_plan(planned("180 uL")))
  assert not thin.ok and not thin.collisions and len(thin.liquid_failures) == 8
  assert "above the liquid, so it draws air" in thin.report()
  assert asyncio.run(scene().rehearse_plan(planned("2 mL"))).ok


# ---------------------------------------------------------------- drafting that rehearses


THIN = """steadyhand: 0.1
name: master mix
robot: opentrons-flex
labware:
  trough: {type: nest_12_reservoir_15ml}
  plate: {type: opentrons_96_wellplate_200ul_pcr_full_skirt}
liquids:
  mix: {in: trough/A1, volume: VOLUME}
steps:
  - transfer: {from: trough/A1, to: plate/A1:H1, volume: 18 uL}
"""


def test_a_draft_that_passes_the_check_but_not_the_rehearsal_is_sent_back_with_the_reason():
  from steadyhand.intake import draft, messages_for

  replies = iter([THIN.replace("VOLUME", "180 uL"), THIN.replace("VOLUME", "2 mL")])
  sent = []

  def model(messages):
    sent.append([dict(m) for m in messages])
    return next(replies)

  result = draft("18 uL of master mix into column 1.", model, robot="opentrons-flex", rehearse=True)
  assert result.ok and result.rehearsed and result.rounds == 2
  # The first message is what it always was; only the feedback is new.
  assert sent[0] == messages_for("18 uL of master mix into column 1.", None, "opentrons-flex")
  told = sent[1][-1]["content"]
  assert "- rehearsal: in trough/A1 the tip stops up to" in told and "draws air" in told
  assert "starting with more of a liquid whose amount the text leaves open" in told
  assert [str(p)[:10] for p in result.history[0]] == ["rehearsal:"] and result.history[1] == []

  # Without rehearsing, the first file is accepted as it was before.
  once = draft("18 uL of master mix into column 1.", lambda messages: THIN.replace("VOLUME", "180 uL"), robot="opentrons-flex")
  assert once.ok and once.rounds == 1 and not once.rehearsed

  # The same file sent again hands a rehearsal problem to a person, like any other.
  stuck = draft("x", lambda messages: THIN.replace("VOLUME", "180 uL"), robot="opentrons-flex", rehearse=True)
  assert not stuck.ok and stuck.left_for_a_person and stuck.rounds == 2 and stuck.problems[0].where == "rehearsal"


def test_what_stops_a_plan_is_sent_back_too():
  from steadyhand.intake import rehearsal_problems

  crowded = THIN.replace("VOLUME", "2 mL").replace(
    "liquids:", "".join(f"  extra{n}: {{type: corning_96_wellplate_360ul_flat}}\n" for n in range(9)) + "liquids:"
  )
  found = rehearsal_problems(check(__import__("steadyhand.protocol", fromlist=["loads"]).loads(crowded)), "opentrons-flex")
  assert len(found) == 1 and found[0].where == "labware" and "has 11 for labware" in found[0].message
