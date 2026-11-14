"""A transfer that draws from just under the surface, not from the bottom of the well."""

import asyncio
import re

import pytest

from steadyhand import opentrons_robots as ot
from steadyhand.planner import SUBMERGED, emit, plan, rehearse_plan
from steadyhand.protocol import ProtocolError, check, loads

needs_opentrons = pytest.mark.skipif(not ot.opentrons_installed(), reason="needs the opentrons package")


def supernatant(draw="draw_from: surface", source="Cor_96_wellplate_360ul_Fb", volume="100 uL", holds="200 uL", robot=""):
  option = f", {draw}" if draw else ""
  return (
    "steadyhand: 0.1\nname: supernatant off cells\n" + (f"robot: {robot}\n" if robot else "")
    + f"labware:\n  culture: {{type: {source}}}\n  assay: {{type: {'corning_96_wellplate_360ul_flat' if robot else 'Cor_96_wellplate_360ul_Fb'}}}\n"
    + f"liquids:\n  medium: {{in: culture/A1:H2, volume: {holds}}}\n"
    + f"steps:\n  - transfer: {{from: culture/A1:H2, to: assay/A1:H2, volume: {volume}{option}}}\n"
  )


def test_the_format_takes_bottom_or_surface_and_nothing_else():
  assert check(loads(supernatant())).protocol.steps[0].draw_from == "surface"
  assert check(loads(supernatant(""))).protocol.steps[0].draw_from == "bottom"
  assert check(loads(supernatant("draw_from: bottom"))).protocol.steps[0].draw_from == "bottom"
  with pytest.raises(ProtocolError) as refused:
    loads(supernatant("draw_from: top"))
  assert (
    "steps[0].transfer.draw_from: expected 'bottom', 'surface' or a height above the well floor such as '0.5 mm', got 'top'"
    in str(refused.value)
  )


def test_on_the_hamilton_the_tip_stops_under_where_the_liquid_ends_up():
  planned = plan(check(loads(supernatant())))
  assert planned.ok, planned.report()
  draws = [c for c in planned.commands if c.kind == "aspirate"]
  # 200 uL stands about 6.2 mm deep in this well and 100 uL about 3.1 mm: the tip stops 1 mm under that
  assert draws and all(len(c.heights) == 8 for c in draws)
  heights = {h for c in draws for h in c.heights}
  assert len(heights) == 1 and 2.0 < heights.pop() < 2.2
  assert "draws at a height of their own: 16" in planned.report()
  # the dispense, and a plan that does not ask for it, keep the usual height
  assert all(not c.heights for c in planned.commands if c.kind != "aspirate")
  assert all(not c.heights for c in plan(check(loads(supernatant("")))).commands)

  result = asyncio.run(rehearse_plan(planned))
  assert result.ok and result.liquid == []
  # what was recorded for the replay has the tip that much higher than a draw from the bottom
  from steadyhand.planner import record_plan

  def lowest(a_plan):
    _, steps = asyncio.run(record_plan(a_plan))
    return min(s.reference[2] for s in steps if s.kind == "aspirate")

  assert lowest(planned) - lowest(plan(check(loads(supernatant(""))))) == pytest.approx(draws[0].heights[0] - 1.0, abs=0.01)
  script = emit(planned)
  assert re.search(r"lh\.aspirate\(.*liquid_height=\[2\.\d+, .*\]\)  # just under the surface", script)
  assert "lh.dispense(" in script and "liquid_height=[HEIGHT] * 8)" in script


def test_a_draw_that_leaves_too_little_goes_no_lower_than_the_usual_height_and_is_still_caught():
  # 110 uL drawn down to 10 uL: under the surface would be under the usual height, so the tip stays at 1 mm
  planned = plan(check(loads(supernatant(holds="110 uL"))))
  assert planned.ok and {h for c in planned.commands for h in c.heights} == {planned.pipetting_height}
  result = asyncio.run(rehearse_plan(planned))
  assert not result.ok and {i.kind for i in result.liquid_failures} == {"short"}


def test_a_well_whose_shape_is_not_known_cannot_be_followed():
  planned = plan(check(loads(supernatant(source="Azenta4titudeFrameStar_96_wellplate_200ul_Vb", holds="150 uL", volume="50 uL"))))
  assert not planned.ok and len(planned.problems) == 1
  assert str(planned.problems[0]).startswith("steps[0].draw_from: cannot follow the surface in culture")
  assert "Use a flat-bottom plate there" in str(planned.problems[0])


@needs_opentrons
@pytest.mark.parametrize("profile", [ot.FLEX, ot.OT2])
def test_on_an_opentrons_robot_the_height_goes_into_the_protocol_and_the_replay(profile):
  from steadyhand.opentrons_scene import rehearse_plan as rehearse_opentrons

  planned = ot.plan(check(loads(supernatant(source="corning_96_wellplate_360ul_flat", robot=profile.name))), profile)
  assert planned.ok, planned.report()
  draws = [a for a in planned.actions if a.kind == "aspirate"]
  assert draws and all(2.0 < a.height < 2.2 for a in draws)
  assert all(a.height == 0 for a in planned.actions if a.kind != "aspirate")
  assert "draws at a height of their own" in planned.report()
  script = ot.emit(planned)
  assert re.search(r'aspirate\(100\.0, deck\["culture"\]\["A1"\]\.bottom\(2\.\d+\)\)  # just under the surface', script)
  assert 'deck["assay"]["A1"].bottom(HEIGHT))' in script
  result = asyncio.run(rehearse_opentrons(planned))
  assert result.ok and result.liquid == []
  simulated = ot.simulate(script, profile)
  if simulated.ran:
    assert simulated.ok, simulated.report()


@needs_opentrons
def test_on_an_opentrons_robot_a_v_bottom_well_can_be_followed_because_its_shape_is_known():
  planned = ot.plan(
    check(loads(supernatant(source="nest_96_wellplate_2ml_deep", holds="1 mL", volume="300 uL", robot="opentrons-flex"))), ot.FLEX
  )
  assert planned.ok, planned.report()
  assert all(a.height > 5 for a in planned.actions if a.kind == "aspirate")


def test_submerged_is_a_millimetre():
  assert SUBMERGED == 1.0


# ---------------------------------------------------------------- a height the protocol names


def eluate(draw, robot="", plate=""):
  plate = plate or ("opentrons_96_wellplate_200ul_pcr_full_skirt" if robot else "Cor_96_wellplate_360ul_Fb")
  holds, takes = ("40 uL", "38 uL") if robot else ("110 uL", "100 uL")
  option = f", draw_from: {draw}" if draw else ""
  return (
    "steadyhand: 0.1\nname: nearly all of a well\n" + (f"robot: {robot}\n" if robot else "")
    + f"labware:\n  first: {{type: {plate}}}\n  second: {{type: {plate}}}\n"
    + f"liquids:\n  eluate: {{in: first/A1:H2, volume: {holds}}}\n"
    + f"steps:\n  - transfer: {{from: first/A1:H2, to: second/A1:H2, volume: {takes}{option}}}\n"
  )


def test_a_height_is_read_and_one_too_close_to_the_floor_is_refused():
  step = check(loads(eluate("0.3 mm"))).protocol.steps[0]
  assert (step.draw_from, step.draw_height) == ("height", 0.3)
  for bad, why in (("0.1 mm", "0.1 mm is closer to the floor of the well than a tip should draw (0.2 mm)"), ("3", "expected 'bottom'")):
    with pytest.raises(ProtocolError) as refused:
      loads(eluate(bad))
    assert why in str(refused.value)


def test_on_the_hamilton_a_lower_tip_reaches_what_the_usual_height_leaves():
  usual = asyncio.run(rehearse_plan(plan(check(loads(eluate(""))))))
  assert not usual.ok and {i.kind for i in usual.liquid_failures} == {"short"}
  planned = plan(check(loads(eluate("0.25 mm"))))
  draws = [c for c in planned.commands if c.kind == "aspirate"]
  assert planned.ok and all(c.heights == (0.25,) * 8 for c in draws)
  assert "draws at a height of their own: 16, the tip 0.25 to 0.25 mm" in planned.report()
  result = asyncio.run(rehearse_plan(planned))
  assert result.ok and result.liquid == []
  assert "liquid_height=[0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25])  # the height this step asks for" in emit(planned)


def test_a_height_needs_no_knowledge_of_the_well_and_a_higher_one_can_miss_the_liquid():
  # the shape of this V-bottom plate is not known, which stops a draw that follows the surface but not a height
  text = eluate("3 mm").replace("Cor_96_wellplate_360ul_Fb", "Azenta4titudeFrameStar_96_wellplate_200ul_Vb")
  assert plan(check(loads(text.replace("110 uL", "150 uL").replace("100 uL", "50 uL")))).ok
  # in a flat well 110 uL stands about 3.4 mm deep: a tip 5 mm up starts in air
  high = asyncio.run(rehearse_plan(plan(check(loads(eluate("5 mm"))))))
  assert not high.ok and "air" in {i.kind for i in high.liquid_failures}


@needs_opentrons
@pytest.mark.parametrize("profile", [ot.FLEX, ot.OT2])
def test_on_an_opentrons_robot_a_lower_tip_takes_38_of_40_microlitres(profile):
  from steadyhand.intake import rehearsal_problems
  from steadyhand.opentrons_scene import rehearse_plan as rehearse_opentrons

  usual = rehearsal_problems(check(loads(eluate("", robot=profile.name))), profile.name)
  assert len(usual) == 1 and "of what it moves on is air" in usual[0].message
  assert "A tip stops 1 mm above the floor" in usual[0].message
  assert "can draw lower: give it draw_from with a height, such as 0.5 mm, and no less than 0.2 mm" in usual[0].message

  planned = ot.plan(check(loads(eluate("0.5 mm", robot=profile.name))), profile)
  assert planned.ok and all(a.height == 0.5 for a in planned.actions if a.kind == "aspirate")
  script = ot.emit(planned)
  assert '.bottom(0.5))  # the height this step asks for' in script
  result = asyncio.run(rehearse_opentrons(planned))
  assert result.ok and result.liquid == []
  simulated = ot.simulate(script, profile)
  if simulated.ran:
    assert simulated.ok, simulated.report()
