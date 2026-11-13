"""Where the tip is relative to the liquid when it aspirates or dispenses."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from steadyhand.planner import plan_file, record_plan, rehearse_plan
from steadyhand.replay import rehearse

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(scope="module")
def dilution():
  return plan_file(EXAMPLES / "serial_dilution.yaml")[1]


def test_the_clean_dilution_keeps_every_tip_in_the_liquid(dilution):
  result = asyncio.run(rehearse_plan(dilution))
  assert result.ok and result.liquid == []
  assert "tips out of the liquid or the well: 0" in result.report()


def test_pipetting_above_the_liquid_fails_without_any_collision(dilution):
  result = asyncio.run(rehearse_plan(replace(dilution, pipetting_height=9.0)))
  assert not result.ok and result.collisions == []
  failures = result.liquid_failures
  assert failures and {i.kind for i in failures} == {"air"}
  in_plate = [i for i in failures if i.resource.startswith("plate_")]
  from steadyhand import opentrons_robots

  # 200 uL stands 6.19 mm high in a straight-walled well; Opentrons' definition of the same plate has a
  # slight taper, which puts it at 6.04 mm
  stands = 6.04 if opentrons_robots.opentrons_installed() else 6.19
  assert in_plate[0].gap == pytest.approx(9.0 - stands, abs=0.05)
  assert result.to_dict()["liquid"][0]["kind"] == "air"

  in_reservoir = [i for i in result.liquid if i.resource.startswith("reservoir")]
  if opentrons_robots.opentrons_installed():
    # Opentrons ships the same reservoir with its inside shape, so 20 mL standing under 4 mm is a sure failure
    assert in_reservoir and all(i.sure and i.fails for i in in_reservoir)
  else:
    # a V bottom of unknown shape: its liquid height is an estimate, reported but not failed
    assert in_reservoir and all(not i.sure and not i.fails for i in in_reservoir)
    assert "possibly out of the liquid" in result.report()


def test_a_tapered_well_of_unknown_shape_is_reported_as_possible_not_failed():
  from steadyhand.planner import plan
  from steadyhand.protocol import check, loads

  planned = plan(check(loads("""
steadyhand: 0.1
name: from a V-bottom plate
labware:
  source: {type: Azenta4titudeFrameStar_96_wellplate_200ul_Vb}
  plate: {type: Cor_96_wellplate_360ul_Fb}
liquids:
  sample: {in: source/A1:H1, volume: 150 uL}
steps:
  - transfer: {from: source/A1:H1, to: plate/A1:H1, volume: 100 uL}
""")))
  result = asyncio.run(rehearse_plan(replace(planned, pipetting_height=14.0)))
  unsure = [i for i in result.liquid if i.kind == "air" and not i.sure]
  assert unsure and all(i.resource.startswith("source") and not i.fails for i in unsure)
  assert "possibly out of the liquid" in result.report()


def test_a_dispense_from_above_the_rim_fails(dilution):
  deck, steps = asyncio.run(record_plan(dilution))
  lifted = [
    replace(s, reference=(s.reference[0], s.reference[1], s.reference[2] + 30.0)) if s.kind == "dispense" else s for s in steps
  ]
  result = rehearse(deck, lifted)
  assert not result.ok and {i.kind for i in result.liquid_failures} == {"outside"}
  assert result.liquid_failures[0].gap > 15


def test_the_normalization_example_never_draws_a_well_below_the_tip():
  checked, planned = plan_file(EXAMPLES / "normalization.yaml")
  result = asyncio.run(rehearse_plan(planned))
  assert result.ok and result.liquid == []


def test_a_draw_that_empties_a_well_below_the_tip_fails_when_the_liquid_is_delivered_not_thrown_away():
  from steadyhand.planner import plan
  from steadyhand.protocol import check, loads

  def run(to, volume="100 uL"):
    planned = plan(check(loads(f"""
steadyhand: 0.1
name: the last of a well
labware:
  source: {{type: Cor_96_wellplate_360ul_Fb}}
  plate: {{type: Cor_96_wellplate_360ul_Fb}}
liquids:
  sample: {{in: source/A1:H1, volume: 110 uL}}
steps:
  - transfer: {{from: source/A1:H1, to: {to}, volume: {volume}}}
""")))
    return asyncio.run(rehearse_plan(planned))

  kept = run("plate/A1:H1")
  short = [i for i in kept.liquid if i.kind == "short"]
  assert not kept.ok and len(short) == 8 and all(i.fails for i in short)
  # the tip stops 1 mm up; what stands under it cannot be drawn, so that much of the 100 uL is air
  assert all(20 < i.short < 26 for i in short)
  assert "of what it delivers is air" in kept.report()
  # thrown away, the same draw only leaves a little behind
  wasted = run("waste")
  assert wasted.ok and {i.kind for i in wasted.liquid} == {"ends_in_air"}
  assert "finish with the liquid below the tip" in wasted.report()
  # and a draw that leaves the tip covered is clean
  assert run("plate/A1:H1", "70 uL").liquid == []


def test_channels_closer_than_the_head_allows_are_a_collision(dilution):
  deck, steps = asyncio.run(record_plan(dilution))
  first = next(s.command for s in steps if s.kind == "aspirate")
  back = next(s for s in steps if s.command == first and s.channel == 0)
  squeezed = [
    replace(s, reference=(s.reference[0], back.reference[1] - 4.0, s.reference[2])) if s.command == first and s.channel == 1 else s
    for s in steps
  ]
  result = rehearse(deck, squeezed)
  spacing = [c for c in result.collisions if c.geom == "spacing"]
  assert len(spacing) == 1 and spacing[0].channel == 1 and spacing[0].depth == pytest.approx(5.0)
  assert "closer to channel 0 than the head allows" in spacing[0].describe()
  assert rehearse(deck, squeezed, min_channel_pitch=None).collisions == []


def test_on_the_hamilton_a_plate_opentrons_also_ships_gets_its_real_inside_shape():
  import asyncio

  import pytest

  from steadyhand import opentrons_robots
  from steadyhand.planner import build_deck, plan, rehearse_plan
  from steadyhand.protocol import check, loads
  from steadyhand.scene import liquid_height, liquid_height_is_known

  if not opentrons_robots.opentrons_installed():
    pytest.skip("Opentrons' labware definitions are not installed")

  def planned(volume, trough="nest_12_troughplate_15000uL_Vb"):
    return plan(check(loads(f"""
steadyhand: 0.1
name: master mix from a trough
labware:
  trough: {{type: {trough}}}
  plate: {{type: Azenta4titudeFrameStar_96_wellplate_200ul_Vb}}
liquids:
  mix: {{in: trough/A1, volume: {volume}}}
steps:
  - transfer: {{from: trough/A1, to: plate/A1:H1, volume: 18 uL}}
""")))

  deck = build_deck(planned("180 uL"))
  well = deck.get_resource("trough").get_item("A1")
  assert liquid_height_is_known(well)  # a V bottom, but the same reservoir Opentrons describes inside
  # PyLabRobot's own figure for it is a straight-walled estimate: 0.31 mm for 180 uL. The floor tapers, so it stands higher.
  assert 0.8 < liquid_height(well, 180.0) < 1.0 < liquid_height(well, 500.0)
  assert not liquid_height_is_known(deck.get_resource("plate").get_item("A1"))  # no twin: still unsure

  thin = asyncio.run(rehearse_plan(planned("180 uL")))
  assert not thin.ok and len(thin.liquid_failures) == 8 and "draws air" in thin.report()
  assert asyncio.run(rehearse_plan(planned("2 mL"))).ok
