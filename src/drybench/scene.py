"""Turn a PyLabRobot resource tree into a MuJoCo scene.

PyLabRobot describes a deck as a tree of resources, each with a position and a bounding box.
A bounding box is not a solid: a carrier's box reaches above the plates standing on it, and a
plate's box contains its wells. So this module does not turn every box into a solid. It keeps
only what the tree lets us know is solid:

* a resource with nothing inside it is a solid box (a lid, a gripper block);
* a resource that holds a grid of cavities (a plate, a tip rack) becomes a floor under the
  cavities plus the walls between and around them;
* any other resource with children is solid from its own bottom up to the lowest thing inside
  it (the body of a carrier under its plates, the deck surface under its carriers).

Cavities themselves (wells, tubes, tip spots) are empty space. Liquid and tips are drawn in
them but never collide.

Everything here is in millimetres, as in PyLabRobot. Conversion to metres happens only when
the MuJoCo XML is written.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

from pylabrobot.resources import Container, Resource, TipSpot

Vec3 = Tuple[float, float, float]

MM = 1e-3  # millimetres to metres
EPS = 1e-6  # mm; anything thinner is treated as having no extent

# Collision bits. Scene solids and the pipetting probe collide with each other; probes do not
# collide with probes, and scene solids are static so MuJoCo never tests them against each other.
SCENE_CONTYPE, SCENE_CONAFFINITY = 1, 2
PROBE_CONTYPE, PROBE_CONAFFINITY = 2, 1

_COLOURS = {
  "deck": (0.55, 0.57, 0.60, 1.0),
  "carrier": (0.30, 0.32, 0.36, 1.0),
  "plate": (0.92, 0.92, 0.88, 1.0),
  "tip_rack": (0.20, 0.45, 0.70, 1.0),
  "other": (0.65, 0.60, 0.50, 1.0),
  "liquid": (0.15, 0.55, 0.95, 0.85),
  "tip": (0.85, 0.85, 0.85, 0.9),
}


@dataclass(frozen=True)
class Box:
  """One axis-aligned box in the scene, in mm, in the root resource's frame."""

  name: str
  resource: str
  kind: str  # "solid", "liquid" or "tip"
  lo: Vec3
  hi: Vec3
  colour: str = "other"

  @property
  def centre(self) -> Vec3:
    return tuple((a + b) / 2 for a, b in zip(self.lo, self.hi))  # type: ignore[return-value]

  @property
  def half_size(self) -> Vec3:
    return tuple((b - a) / 2 for a, b in zip(self.lo, self.hi))  # type: ignore[return-value]

  @property
  def collides(self) -> bool:
    return self.kind == "solid"


def bounds(resource: Resource) -> Tuple[Vec3, Vec3]:
  """The resource's bounding box as (low corner, high corner), in mm, absolute.

  Read from two opposite anchors so that a resource rotated by a multiple of 90 degrees still
  gives a correct box.
  """
  a = resource.get_absolute_location("l", "f", "b")
  b = resource.get_absolute_location("r", "b", "t")
  lo = (min(a.x, b.x), min(a.y, b.y), min(a.z, b.z))
  hi = (max(a.x, b.x), max(a.y, b.y), max(a.z, b.z))
  return lo, hi


def is_cavity(resource: Resource) -> bool:
  """True for the empty spaces a tip goes into: wells, tubes, troughs and tip spots."""
  return isinstance(resource, (Container, TipSpot))


def cavity_floor_z(resource: Resource) -> float:
  """The z of the lowest point a tip can reach inside a cavity, in mm, absolute."""
  if isinstance(resource, Container):
    try:
      return resource.get_absolute_location("c", "c", "cavity_bottom").z
    except Exception:  # a container that does not state its wall thickness
      return bounds(resource)[0][2]
  return bounds(resource)[0][2]


def _descendants(resource: Resource) -> Iterator[Resource]:
  for child in resource.children:
    yield child
    yield from _descendants(child)


def _colour_for(resource: Resource) -> str:
  category = (resource.category or "").lower()
  if "deck" in category:
    return "deck"
  if "carrier" in category:
    return "carrier"
  if "tip_rack" in category:
    return "tip_rack"
  if "plate" in category:
    return "plate"
  return "other"


def _merged(intervals: Iterable[Tuple[float, float]]) -> List[Tuple[float, float]]:
  """Sort intervals and merge the ones that touch or overlap."""
  merged: List[Tuple[float, float]] = []
  for start, end in sorted(intervals):
    if merged and start <= merged[-1][1] + EPS:
      merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    else:
      merged.append((start, end))
  return merged


def _gaps(low: float, high: float, taken: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
  """The parts of [low, high] that no interval in `taken` covers."""
  gaps: List[Tuple[float, float]] = []
  cursor = low
  for start, end in taken:
    if start - cursor > EPS:
      gaps.append((cursor, start))
    cursor = max(cursor, end)
  if high - cursor > EPS:
    gaps.append((cursor, high))
  return gaps


class _Collector:
  def __init__(self) -> None:
    self.boxes: List[Box] = []
    self._names: dict = {}

  def add(self, resource: Resource, part: str, kind: str, lo: Vec3, hi: Vec3, colour: str) -> None:
    if any(h - l <= EPS for l, h in zip(lo, hi)):
      return
    base = f"{resource.name}/{part}"
    count = self._names.get(base, 0)
    self._names[base] = count + 1
    name = base if count == 0 else f"{base}#{count}"
    self.boxes.append(Box(name=name, resource=resource.name, kind=kind, lo=lo, hi=hi, colour=colour))

  def visit(self, resource: Resource) -> None:
    lo, hi = bounds(resource)

    if is_cavity(resource):
      self._contents(resource, lo, hi)
      return

    children = list(resource.children)
    if not children:
      self.add(resource, "body", "solid", lo, hi, _colour_for(resource))
      return

    if all(is_cavity(child) for child in children):
      self._grid(resource, children, lo, hi)
    else:
      floor = min(bounds(d)[0][2] for d in _descendants(resource))
      self.add(resource, "body", "solid", lo, (hi[0], hi[1], min(floor, hi[2])), _colour_for(resource))

    for child in children:
      self.visit(child)

  def _grid(self, resource: Resource, cavities: Sequence[Resource], lo: Vec3, hi: Vec3) -> None:
    """A floor under the cavities, plus the walls between and around them."""
    colour = _colour_for(resource)
    floor = min(cavity_floor_z(c) for c in cavities)
    wall_bottom = min(max(floor, lo[2]), hi[2])
    self.add(resource, "floor", "solid", lo, (hi[0], hi[1], wall_bottom), colour)

    spans = [bounds(c) for c in cavities]
    xs = _merged((c_lo[0], c_hi[0]) for c_lo, c_hi in spans)
    ys = _merged((c_lo[1], c_hi[1]) for c_lo, c_hi in spans)
    for x0, x1 in _gaps(lo[0], hi[0], xs):
      self.add(resource, "wall_x", "solid", (x0, lo[1], wall_bottom), (x1, hi[1], hi[2]), colour)
    for y0, y1 in _gaps(lo[1], hi[1], ys):
      self.add(resource, "wall_y", "solid", (lo[0], y0, wall_bottom), (hi[0], y1, hi[2]), colour)

  def _contents(self, resource: Resource, lo: Vec3, hi: Vec3) -> None:
    """Draw what is in a cavity: liquid in a container, a tip in a tip spot."""
    if isinstance(resource, Container):
      volume = resource.tracker.get_used_volume()
      if volume <= 0:
        return
      height = liquid_height(resource, volume)
      floor = cavity_floor_z(resource)
      inset = min(0.2, (hi[0] - lo[0]) / 10)
      self.add(
        resource,
        "liquid",
        "liquid",
        (lo[0] + inset, lo[1] + inset, floor),
        (hi[0] - inset, hi[1] - inset, min(floor + height, hi[2])),
        "liquid",
      )
    elif isinstance(resource, TipSpot) and resource.has_tip():
      tip = resource.get_tip()
      cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
      self.add(
        resource,
        "tip",
        "tip",
        (cx - 1.5, cy - 1.5, lo[2]),
        (cx + 1.5, cy + 1.5, lo[2] + tip.total_tip_length),
        "tip",
      )


def liquid_height(container: Container, volume: float) -> float:
  """Height of `volume` microlitres in a container, in mm.

  Uses the labware's own volume-to-height function when it has one, and a straight-walled
  estimate from the cavity's footprint when it does not.
  """
  if container.supports_compute_height_volume_functions():
    return float(container.compute_height_from_volume(volume))
  lo, hi = bounds(container)
  area = (hi[0] - lo[0]) * (hi[1] - lo[1])
  if str(getattr(getattr(container, "cross_section_type", None), "value", "")).lower() == "circle":
    area *= math.pi / 4
  return volume / area if area > EPS else 0.0


def liquid_height_is_known(container: Container) -> bool:
  """Whether `liquid_height` can be trusted to a fraction of a millimetre for this container.

  Only for a flat bottom, where straight walls are the real shape. In a round or V bottom,
  shallow liquid stands higher than a straight-walled estimate says, and some of PyLabRobot's
  own volume-to-height functions for such labware are that same estimate.
  """
  return str(getattr(getattr(container, "bottom_type", None), "value", "")).lower() == "flat"


def collect_boxes(root: Resource) -> List[Box]:
  """Every box the scene is made of, for the tree under `root`."""
  collector = _Collector()
  collector.visit(root)
  return collector.boxes


def _fmt(values: Iterable[float]) -> str:
  return " ".join(f"{v:.6g}" for v in values)


def boxes_to_mjcf(
  boxes: Sequence[Box],
  *,
  model_name: str = "drybench",
  extra_bodies: Optional[Sequence[ET.Element]] = None,
) -> str:
  """Write the boxes as a MuJoCo XML document (MJCF), in metres."""
  mujoco = ET.Element("mujoco", model=model_name)
  ET.SubElement(mujoco, "compiler", angle="degree", autolimits="true")
  option = ET.SubElement(mujoco, "option", gravity="0 0 0")
  # MuJoCo's mid-phase tree is built once from the geoms that collide at compile time. Tips are
  # switched on and off while a rehearsal runs, and the tree would never see them, so every
  # pair is tested directly instead.
  ET.SubElement(option, "flag", midphase="disable")

  solids = [b for b in boxes if b.collides] or list(boxes)
  if solids:
    lo = [min(b.lo[i] for b in solids) for i in range(3)]
    hi = [max(b.hi[i] for b in solids) for i in range(3)]
  else:
    lo, hi = [0.0, 0.0, 0.0], [1000.0, 1000.0, 1000.0]
  centre = [(a + b) / 2 * MM for a, b in zip(lo, hi)]
  extent = max(b - a for a, b in zip(lo, hi)) * MM

  ET.SubElement(mujoco, "statistic", center=_fmt(centre), extent=f"{extent:.6g}")
  visual = ET.SubElement(mujoco, "visual")
  ET.SubElement(visual, "global", offwidth="1600", offheight="1000")
  ET.SubElement(visual, "headlight", ambient="0.45 0.45 0.45", diffuse="0.6 0.6 0.6")
  ET.SubElement(visual, "map", znear="0.01", zfar="50")

  asset = ET.SubElement(mujoco, "asset")
  ET.SubElement(
    asset, "texture", type="skybox", builtin="gradient", rgb1="0.93 0.95 0.97", rgb2="0.78 0.82 0.86",
    width="64", height="384",
  )

  world = ET.SubElement(mujoco, "worldbody")
  ET.SubElement(
    world, "light", pos=_fmt((centre[0], centre[1], centre[2] + 2.0)), dir="0 0 -1", diffuse="0.5 0.5 0.5"
  )
  ET.SubElement(
    world,
    "camera",
    name="overview",
    pos=_fmt((centre[0] - 0.08 * extent, centre[1] - 0.92 * extent, centre[2] + 0.76 * extent)),
    xyaxes="1 0 0 0 0.64 0.77",
  )

  for box in boxes:
    attributes = {
      "name": box.name,
      "type": "box",
      "pos": _fmt(c * MM for c in box.centre),
      "size": _fmt(h * MM for h in box.half_size),
      "rgba": _fmt(_COLOURS[box.colour]),
    }
    if box.collides:
      attributes.update(contype=str(SCENE_CONTYPE), conaffinity=str(SCENE_CONAFFINITY))
    else:
      attributes.update(contype="0", conaffinity="0", group="1")
    ET.SubElement(world, "geom", attributes)

  for body in extra_bodies or ():
    world.append(body)

  ET.indent(mujoco, space="  ")
  return ET.tostring(mujoco, encoding="unicode") + "\n"


def export_scene(root: Resource, *, model_name: str = "drybench") -> str:
  """The MuJoCo XML for the resource tree under `root`, as it stands right now."""
  return boxes_to_mjcf(collect_boxes(root), model_name=model_name)
