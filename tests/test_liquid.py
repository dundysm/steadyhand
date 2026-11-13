"""Where the tip is relative to the liquid when it aspirates or dispenses."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from drybench.planner import plan_file, record_plan, rehearse_plan
from drybench.replay import rehearse

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
  assert failures and {i.kind for i in failures} == {"air"} and all(i.resource.startswith("plate_") for i in failures)
  assert failures[0].gap == pytest.approx(9.0 - 6.19, abs=0.05)  # 200 uL stands 6.19 mm high in this well
  # the reservoir has a V bottom, so its liquid height is an estimate: reported, but it does not fail the run
  unsure = [i for i in result.liquid if not i.sure]
  assert unsure and all(i.resource.startswith("reservoir") and not i.fails for i in unsure)
  assert "possibly out of the liquid" in result.report()
  assert result.to_dict()["liquid"][0]["kind"] == "air"


def test_a_dispense_from_above_the_rim_fails(dilution):
  deck, steps = asyncio.run(record_plan(dilution))
  lifted = [
    replace(s, reference=(s.reference[0], s.reference[1], s.reference[2] + 30.0)) if s.kind == "dispense" else s for s in steps
  ]
  result = rehearse(deck, lifted)
  assert not result.ok and {i.kind for i in result.liquid_failures} == {"outside"}
  assert result.liquid_failures[0].gap > 15


def test_emptying_a_well_is_noted_but_does_not_fail():
  checked, planned = plan_file(EXAMPLES / "normalization.yaml")
  result = asyncio.run(rehearse_plan(planned))
  assert result.ok
  low = [i for i in result.liquid if i.kind == "ends_in_air"]
  assert low and not any(i.fails for i in low)
  assert "finish with the liquid below the tip" in result.report()


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
