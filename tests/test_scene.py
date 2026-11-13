"""The exported scene has to agree with PyLabRobot's own numbers."""

import mujoco
import numpy as np
import pytest

from steadyhand.demo import build_deck
from steadyhand.scene import MM, boxes_to_mjcf, collect_boxes, export_scene, liquid_height


@pytest.fixture(scope="module")
def deck():
  return build_deck()


@pytest.fixture(scope="module")
def boxes(deck):
  return collect_boxes(deck)


def solids_at(boxes, point):
  x, y, z = point
  return [
    b
    for b in boxes
    if b.collides and b.lo[0] < x < b.hi[0] and b.lo[1] < y < b.hi[1] and b.lo[2] < z < b.hi[2]
  ]


def test_wells_are_open_space(deck, boxes):
  for name in ("A1", "D6", "H12"):
    well = deck.get_resource("source").get_item(name)
    floor = well.get_absolute_location("c", "c", "cavity_bottom")
    top = well.get_absolute_location("c", "c", "t")
    for z in (floor.z + 0.1, (floor.z + top.z) / 2, top.z - 0.1):
      assert solids_at(boxes, (floor.x, floor.y, z)) == [], f"well {name} is blocked at z={z}"


def test_plate_floor_is_solid_under_a_well(deck, boxes):
  well = deck.get_resource("source").get_item("A1")
  floor = well.get_absolute_location("c", "c", "cavity_bottom")
  hit = solids_at(boxes, (floor.x, floor.y, floor.z - 0.2))
  assert [b.resource for b in hit] == ["source"]


def test_wall_between_wells_is_solid(deck, boxes):
  plate = deck.get_resource("source")
  a1 = plate.get_item("A1").get_absolute_location("c", "c", "t")
  a2 = plate.get_item("A2").get_absolute_location("c", "c", "t")
  between = ((a1.x + a2.x) / 2, a1.y, a1.z - 1.0)
  assert any(b.resource == "source" for b in solids_at(boxes, between))


def test_carrier_body_stops_below_its_plates(deck, boxes):
  plate_bottom = deck.get_resource("source").get_absolute_location().z
  carrier = [b for b in boxes if b.resource == "plate_carrier" and b.collides]
  assert carrier, "the carrier has no solid body"
  assert max(b.hi[2] for b in carrier) <= plate_bottom + 1e-9


def test_deck_surface_sits_under_the_carriers(deck, boxes):
  carrier_bottom = deck.get_resource("plate_carrier").get_absolute_location().z
  deck_body = next(b for b in boxes if b.name == "deck/body")
  assert deck_body.hi[2] == pytest.approx(carrier_bottom)


def test_names_are_unique(boxes):
  names = [b.name for b in boxes]
  assert len(names) == len(set(names))


def test_mjcf_geoms_match_the_boxes(boxes):
  model = mujoco.MjModel.from_xml_string(boxes_to_mjcf(boxes))
  assert model.ngeom == len(boxes)
  for box in boxes:
    geom = model.geom(box.name)
    np.testing.assert_allclose(geom.pos, np.array(box.centre) * MM, atol=1e-9)
    np.testing.assert_allclose(geom.size, np.array(box.half_size) * MM, atol=1e-9)
    assert bool(geom.contype[0]) == box.collides


def test_liquid_is_drawn_at_the_labware_height():
  deck = build_deck()
  well = deck.get_resource("source").get_item("A1")
  well.tracker.set_liquids([(None, 200.0)])
  liquid = next(b for b in collect_boxes(deck) if b.name == f"{well.name}/liquid")
  floor = well.get_absolute_location("c", "c", "cavity_bottom").z
  assert liquid.lo[2] == pytest.approx(floor)
  assert liquid.hi[2] - liquid.lo[2] == pytest.approx(well.compute_height_from_volume(200.0))
  assert liquid_height(well, 200.0) == pytest.approx(well.compute_height_from_volume(200.0))
  assert not liquid.collides


def test_export_scene_compiles(deck):
  model = mujoco.MjModel.from_xml_string(export_scene(deck))
  assert model.ngeom > 50


def test_an_offscreen_backend_is_only_named_when_its_library_is_on_the_machine(monkeypatch):
  import ctypes.util

  from steadyhand import _gl

  monkeypatch.setattr("sys.platform", "linux")
  for name in ("MUJOCO_GL", "DISPLAY", "WAYLAND_DISPLAY"):
    monkeypatch.delenv(name, raising=False)
  have = set()
  monkeypatch.setattr(ctypes.util, "find_library", lambda name: f"lib{name}.so" if name in have else None)
  assert _gl.choose() == ""  # naming a missing one would make `import mujoco` fail
  have.add("OSMesa")
  assert _gl.choose() == "osmesa"
  have.add("EGL")
  assert _gl.choose() == "egl"
  monkeypatch.setenv("DISPLAY", ":0")
  assert _gl.choose() == ""  # a display is there: MuJoCo's default is right
  monkeypatch.delenv("DISPLAY")
  monkeypatch.setenv("MUJOCO_GL", "osmesa")
  assert _gl.choose() == ""  # what the user set is never changed
