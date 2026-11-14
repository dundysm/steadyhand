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
  assert "steps[0].transfer.draw_from: expected 'bottom' or 'surface', got 'top'" in str(refused.value)


def test_on_the_hamilton_the_tip_stops_under_where_the_liquid_ends_up():
  planned = plan(check(loads(supernatant())))
  assert planned.ok, planned.report()
  draws = [c for c in planned.commands if c.kind == "aspirate"]
  # 200 uL stands about 6.2 mm deep in this well and 100 uL about 3.1 mm: the tip stops 1 mm under that
  assert draws and all(len(c.heights) == 8 for c in draws)
  heights = {h for c in draws for h in c.heights}
  assert len(heights) == 1 and 2.0 < heights.pop() < 2.2
  assert "draws that follow the surface: 16" in planned.report()
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
  assert "draws that follow the surface" in planned.report()
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
