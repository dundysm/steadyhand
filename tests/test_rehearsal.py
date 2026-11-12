"""A clean protocol passes; planted mistakes are caught; the same input gives the same output."""

import asyncio

import pytest

from drybench import Step, rehearse
from drybench.cli import main
from drybench.demo import run_demo


def run(fault):
  deck, backend = asyncio.run(run_demo(fault))
  return deck, backend, rehearse(deck, backend.steps)


@pytest.fixture(scope="module")
def clean():
  return run("none")


def test_clean_transfer_passes(clean):
  _, backend, result = clean
  assert result.ok, result.report()
  # 8 channels x (pick up, aspirate, dispense, return tip)
  assert [s.kind for s in backend.steps].count("aspirate") == 8
  assert len(result.steps) == 32
  assert result.not_rehearsed == []
  assert result.samples > 300


def test_volumes_follow_the_transfer(clean):
  _, _, result = clean
  for row in "ABCDEFGH":
    assert result.volumes[f"source_well_{row}1"] == pytest.approx(100.0)
    assert result.volumes[f"destination_well_{row}1"] == pytest.approx(100.0)
  assert sum(result.volumes.values()) == pytest.approx(1600.0)


def test_recorded_heights_follow_the_star_backend(clean):
  deck, backend, _ = clean
  aspirate = next(s for s in backend.steps if s.kind == "aspirate" and s.resource == "source_well_A1")
  floor = deck.get_resource("source").get_item("A1").get_absolute_location("c", "c", "cavity_bottom")
  assert aspirate.tip_end == pytest.approx((floor.x, floor.y, floor.z))

  pick_up = next(s for s in backend.steps if s.kind == "pick_up_tip" and s.channel == 0)
  spot = deck.get_resource("tips").get_item("A1")
  tip = spot.get_tip()
  bottom = spot.get_absolute_location("c", "c", "b")
  assert pick_up.reference[2] == pytest.approx(bottom.z + tip.total_tip_length - tip.fitting_depth)


def test_off_centre_aspirate_hits_the_wall_between_wells():
  _, _, result = run("offset")
  assert not result.ok
  assert len(result.collisions) == 8
  for collision in result.collisions:
    assert collision.kind == "aspirate"
    assert collision.part == "tip"
    assert collision.resource == "source"
    assert collision.geom.startswith("source/wall_x")
    assert collision.phase == "descend"


def test_too_deep_aspirate_hits_the_plate_floor():
  deck, _, result = run("depth")
  assert not result.ok
  assert {c.geom for c in result.collisions} == {"source/floor"}
  assert len(result.collisions) == 8
  # The overlap starts within one sample of the floor, not at the bottom of the move.
  floor_z = deck.get_resource("source").get_item("A1").get_absolute_location("c", "c", "cavity_bottom").z
  first = result.collisions[0]
  step = result.steps[first.step]
  tip_end_at_contact = first.at[2] - step.reach
  assert floor_z - 1.2 <= tip_end_at_contact <= floor_z


def test_same_protocol_gives_the_same_result_twice(clean):
  _, _, first = clean
  _, _, second = run("none")
  assert first.to_dict() == second.to_dict()
  assert first.scene_xml == second.scene_xml


def test_steps_that_are_not_rehearsed_are_reported(clean):
  deck, backend, _ = clean
  extra = Step(
    index=len(backend.steps), command=99, kind="unsimulated:aspirate96", channel=-1, resource="", reference=None
  )
  result = rehearse(deck, list(backend.steps) + [extra])
  assert [s.kind for s in result.not_rehearsed] == ["unsimulated:aspirate96"]
  assert "not rehearsed (1 steps): aspirate96" in result.report()


def test_command_line_exit_code(tmp_path, capsys):
  assert main(["demo", "--out", str(tmp_path / "ok"), "--no-render"]) == 0
  assert main(["demo", "--fault", "depth", "--out", str(tmp_path / "bad"), "--no-render"]) == 1
  assert (tmp_path / "ok" / "scene.xml").exists()
  assert "FAIL" in (tmp_path / "bad" / "report.txt").read_text()
  capsys.readouterr()
