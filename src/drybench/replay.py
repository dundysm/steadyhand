"""Replay recorded steps in the physics scene and report what the pipetting channels hit.

Each channel is a small rigid body: a barrel, and a tapered tip once it has picked one up. The
channels named in one PyLabRobot call move together: they travel at a safe height to above
their targets, go straight down, and come straight back up. The path is sampled about every
millimetre; at each sample MuJoCo is asked which solids overlap.

What this checks: whether the channel or its tip would be driven into the deck, a carrier, a
plate's floor or the walls between wells.

What it does not check yet: timing, forces, the motion limits of a particular robot, plates
being moved, or the 96-channel head. Steps of those kinds are listed as not rehearsed.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

import mujoco
from pylabrobot.resources import Container, Resource

from .record import Step
from .scene import (
  MM,
  PROBE_CONAFFINITY,
  PROBE_CONTYPE,
  Box,
  bounds,
  boxes_to_mjcf,
  cavity_floor_z,
  collect_boxes,
  liquid_height,
  liquid_height_is_known,
)
from .viewer import layout

Vec3 = Tuple[float, float, float]

RIM_ALLOWANCE = 2.0  # mm a tip may sit above the rim of a well and still count as in it
SPACING_TOLERANCE = 0.1  # mm; PyLabRobot's own spread of channels in a wide well rounds to about 0.01
LIQUID_TOLERANCE = 0.05  # mm; a tip closer to the surface than this counts as touching it

BARREL_RADIUS = 4.0  # mm; STAR channels sit 9 mm apart
BARREL_LENGTH = 80.0  # mm


@dataclass(frozen=True)
class TipProfile:
  """The outside shape assumed for a tip, since PyLabRobot stores a tip's length but not its width.

  The tip is treated as a cone from `end_radius` at its opening to `top_radius` at its top.
  The defaults are nominal values for a standard-volume tip, not measurements.
  """

  end_radius: float = 0.4  # mm
  top_radius: float = 3.0  # mm
  segments: int = 4


@dataclass(frozen=True)
class Collision:
  step: int
  kind: str
  channel: int
  part: str  # "tip" or "channel"
  resource: str  # the PyLabRobot resource that was hit
  geom: str  # which piece of it
  depth: float  # mm; the deepest overlap MuJoCo reported along the path
  at: Vec3  # mm; the channel's reference point where the overlap began
  phase: str  # "travel", "descend" or "ascend", when the overlap began

  def describe(self) -> str:
    if self.geom == "spacing":
      return (
        f"step {self.step} ({self.kind}, channel {self.channel}): asked to sit {self.depth:.2f} mm closer to "
        f"{self.resource} than the head allows"
      )
    return (
      f"step {self.step} ({self.kind}, channel {self.channel}): the {self.part} runs into "
      f"{self.resource} [{self.geom}] during {self.phase}, starting at "
      f"x={self.at[0]:.1f} y={self.at[1]:.1f} z={self.at[2]:.1f} (deepest overlap {self.depth:.2f} mm)"
    )


@dataclass(frozen=True)
class LiquidIssue:
  """A tip in the wrong place relative to the liquid when it aspirates or dispenses.

  kind is "air" (an aspirate starts with the tip above the liquid), "outside" (the tip is
  above the rim of the well) or "ends_in_air" (the liquid falls below the tip before the
  aspirate is over). `gap` is how far, in mm. `sure` is False when the well's shape is not
  known well enough to trust the liquid height; those are reported but do not fail the run.
  """

  step: int
  kind: str
  action: str  # "aspirate" or "dispense"
  channel: int
  resource: str
  gap: float
  sure: bool = True

  @property
  def fails(self) -> bool:
    return self.sure and self.kind in ("air", "outside")

  def describe(self) -> str:
    where = f"step {self.step} ({self.action}, channel {self.channel}) in {self.resource}"
    if self.kind == "outside":
      return f"{where}: the tip is {self.gap:g} mm above the rim of the well"
    height = f"{self.gap:g} mm above" if self.gap > 0 else "at the surface of"
    if self.kind == "air" and self.sure:
      return f"{where}: the tip stops {height} the liquid, so it draws air"
    if self.kind == "air":
      return f"{where}: by a straight-walled estimate the tip stops {height} the liquid; a tapered bottom holds it higher"
    return f"{where}: the liquid falls {self.gap:g} mm below the tip before the aspirate ends"


@dataclass
class Rehearsal:
  steps: List[Step]
  collisions: List[Collision]
  not_rehearsed: List[Step]
  path_length: float  # mm travelled by all channels
  samples: int
  volumes: Dict[str, float]  # microlitres in every container that holds liquid, after the run
  scene_xml: str = field(repr=False, default="")
  layout: dict = field(repr=False, default_factory=dict)  # where every solid and cavity is, for the HTML replay
  traverse_z: float = 245.0
  liquid: List[LiquidIssue] = field(default_factory=list)

  @property
  def liquid_failures(self) -> List[LiquidIssue]:
    return [issue for issue in self.liquid if issue.fails]

  @property
  def ok(self) -> bool:
    return not self.collisions and not self.liquid_failures

  def replay_html(self, title: str = "") -> str:
    """The rehearsal as one self-contained HTML page that plays it back."""
    from .viewer import replay_html

    return replay_html(self, title=title)

  def to_dict(self) -> dict:
    return {
      "ok": self.ok,
      "steps": [asdict(s) for s in self.steps],
      "collisions": [asdict(c) for c in self.collisions],
      "liquid": [{**asdict(i), "fails": i.fails} for i in self.liquid],
      "not_rehearsed": [asdict(s) for s in self.not_rehearsed],
      "path_length_mm": round(self.path_length, 3),
      "samples": self.samples,
      "volumes_ul": self.volumes,
    }

  def report(self) -> str:
    rehearsed = [s for s in self.steps if s.simulated]
    lines = [
      f"drybench rehearsal: {'PASS' if self.ok else 'FAIL'}",
      f"  steps rehearsed: {len(rehearsed)} (path {self.path_length / 1000:.2f} m, {self.samples} samples)",
      f"  collisions: {len(self.collisions)}",
    ]
    lines += [f"    - {c.describe()}" for c in self.collisions]
    failures = self.liquid_failures
    lines.append(f"  tips out of the liquid or the well: {len(failures)}")
    lines += [f"    - {text}" for text in _told_once(failures)]
    unsure = [i for i in self.liquid if i.kind in ("air", "outside") and not i.sure]
    if unsure:
      lines.append(f"  possibly out of the liquid, in wells whose shape is not known exactly ({len(unsure)}):")
      lines += [f"    - {text}" for text in _told_once(unsure)]
    low = [i for i in self.liquid if i.kind == "ends_in_air"]
    if low:
      lines.append(f"  aspirates that finish with the liquid below the tip, so the last of it is air ({len(low)}):")
      lines += [f"    - {text}" for text in _told_once(low)]
    if self.not_rehearsed:
      kinds = sorted({s.kind.split(":", 1)[1] for s in self.not_rehearsed})
      lines.append(f"  not rehearsed ({len(self.not_rehearsed)} steps): {', '.join(kinds)}")
    return "\n".join(lines)


def _told_once(issues: Sequence[LiquidIssue], limit: int = 6) -> List[str]:
  """One line per command and kind, not one per channel, and no more than `limit` lines."""
  lines: List[str] = []
  seen: Dict[Tuple[str, str, str], int] = {}
  for issue in issues:
    labware = issue.resource.rsplit("_well_", 1)[0]
    key = (issue.kind, issue.action, labware)
    seen[key] = seen.get(key, 0) + 1
    if seen[key] == 1:
      lines.append(issue.describe())
  for index, (key, count) in enumerate(seen.items()):
    if count > 1:
      lines[index] += f"; the same {count - 1} more times in {key[2]}"
  if len(lines) > limit:
    lines = lines[:limit] + [f"and {len(lines) - limit} more kinds"]
  return lines


def volumes(root: Resource) -> Dict[str, float]:
  """Microlitres in every container under `root` that holds any liquid."""
  found: Dict[str, float] = {}

  def walk(resource: Resource) -> None:
    if isinstance(resource, Container):
      volume = resource.tracker.get_used_volume()
      if volume > 0:
        found[resource.name] = round(float(volume), 6)
    for child in resource.children:
      walk(child)

  walk(root)
  return found


def _tip_key(step: Step) -> Tuple[float, float]:
  return (round(step.tip_length, 4), round(step.fitting_depth, 4))


def _fmt(*values: float) -> str:
  return " ".join(f"{v * MM:.6g}" for v in values)


def _probe_body(
  channel: int, tips: Sequence[Tuple[float, float]], profile: TipProfile, home: Vec3
) -> ET.Element:
  """The body for one channel: three sliding joints, a barrel, and one hidden tip per tip type.

  The body starts at `home`, so a scene opened in a viewer shows the channels parked above
  their first target instead of piled at the origin.
  """
  name = f"channel{channel}"
  body = ET.Element("body", name=name, pos=_fmt(*home))
  for axis, vector in (("x", "1 0 0"), ("y", "0 1 0"), ("z", "0 0 1")):
    ET.SubElement(body, "joint", name=f"{name}/{axis}", type="slide", axis=vector, limited="false")
  ET.SubElement(
    body,
    "geom",
    name=f"{name}/barrel",
    type="capsule",
    fromto=f"{_fmt(0, 0, BARREL_RADIUS)} {_fmt(0, 0, BARREL_LENGTH)}",
    size=f"{BARREL_RADIUS * MM:.6g}",
    rgba="0.15 0.15 0.18 1",
    contype=str(PROBE_CONTYPE),
    conaffinity=str(PROBE_CONAFFINITY),
  )
  for index, (length, fitting_depth) in enumerate(tips):
    reach = length - fitting_depth
    step = reach / profile.segments
    for segment in range(profile.segments):
      z0 = -reach + segment * step
      z1 = z0 + step
      # Radius of the cone at the middle of this segment.
      fraction = (segment + 0.5) * step / length
      radius = profile.end_radius + (profile.top_radius - profile.end_radius) * fraction
      radius = min(radius, step / 2.5)
      ET.SubElement(
        body,
        "geom",
        name=f"{name}/tip{index}/{segment}",
        type="capsule",
        # Start one radius up, so the rounded end finishes exactly at z0.
        fromto=f"{_fmt(0, 0, z0 + radius)} {_fmt(0, 0, z1)}",
        size=f"{radius * MM:.6g}",
        rgba="0.9 0.9 0.9 0",
        contype="0",
        conaffinity="0",
      )
  return body


class _Channel:
  def __init__(
    self, model: mujoco.MjModel, channel: int, tips: Sequence[Tuple[float, float]], segments: int, home: Vec3
  ):
    self.channel = channel
    self.home = home
    name = f"channel{channel}"
    self.qpos = [model.joint(f"{name}/{axis}").qposadr[0] for axis in "xyz"]
    self.tip_geoms = {
      key: [model.geom(f"{name}/tip{index}/{segment}").id for segment in range(segments)]
      for index, key in enumerate(tips)
    }
    self.position: Optional[Vec3] = None
    self.tip: Optional[Tuple[float, float]] = None

  def set_tip(self, model: mujoco.MjModel, key: Optional[Tuple[float, float]]) -> None:
    for tip, geoms in self.tip_geoms.items():
      on = tip == key
      for gid in geoms:
        model.geom_contype[gid] = PROBE_CONTYPE if on else 0
        model.geom_conaffinity[gid] = PROBE_CONAFFINITY if on else 0
        model.geom_rgba[gid][3] = 1.0 if on else 0.0
    self.tip = key

  @property
  def reach(self) -> float:
    return (self.tip[0] - self.tip[1]) if self.tip else 0.0


def build_model(
  root: Resource,
  steps: Sequence[Step],
  profile: TipProfile = TipProfile(),
  traverse_z: float = 245.0,
) -> Tuple[mujoco.MjModel, str, List[Box], Dict[int, Vec3], List[Tuple[float, float]]]:
  """Compile the scene plus one probe per channel the steps use.

  Returns the model, its XML, the scene's boxes, each channel's parking position and the tip
  types the steps use.
  """
  rehearsed = [s for s in steps if s.simulated and s.reference is not None]
  tips = sorted({_tip_key(s) for s in rehearsed if s.tip_length > 0})
  homes: Dict[int, Vec3] = {}
  for step in rehearsed:  # park each channel above the first place it is sent
    assert step.reference is not None
    homes.setdefault(step.channel, (step.reference[0], step.reference[1], traverse_z))
  homes = dict(sorted(homes.items()))
  boxes = collect_boxes(root)
  bodies = [_probe_body(c, tips, profile, home) for c, home in homes.items()]
  xml = boxes_to_mjcf(boxes, extra_bodies=bodies)
  return mujoco.MjModel.from_xml_string(xml), xml, boxes, homes, tips


def rehearse(
  root: Resource,
  steps: Sequence[Step],
  *,
  start_volumes: Optional[Dict[str, float]] = None,
  traverse_z: float = 245.0,
  sample_mm: float = 1.0,
  tolerance_mm: float = 0.05,
  min_channel_pitch: Optional[float] = 9.0,
  profile: TipProfile = TipProfile(),
  on_sample: Optional[Callable[[mujoco.MjModel, mujoco.MjData, List[Step], str], None]] = None,
) -> Rehearsal:
  """Replay `steps` over the resource tree under `root` and report collisions.

  Args:
    root: the deck (or any resource) the steps were recorded on.
    steps: what `RecordingBackend.steps` holds after the protocol ran.
    start_volumes: microlitres in each container before the first step, by resource name. Leave
      it out when `root` is the deck the steps just ran on; it is then worked out backwards.
    traverse_z: height, in mm, that the lowest point of a channel keeps while travelling. 245 mm
      is the Hamilton STAR backend's default.
    sample_mm: distance between collision checks along the path.
    tolerance_mm: overlaps shallower than this are ignored, so that a tip resting exactly on a
      well's floor does not count as a collision.
    min_channel_pitch: the closest two neighbouring channels can sit along y, in mm; 9 mm on a
      STAR. Channel 0 is at the back. A command that asks for less is reported as a collision
      with the other channel. None turns the check off.
    profile: the outside shape assumed for tips.
    on_sample: called after every collision check with the model, its data, the steps being
      replayed together and the phase ("travel", "descend" or "ascend"). Use it to draw frames
      or to log.
  """
  steps = list(steps)
  model, xml, boxes, homes, tips = build_model(root, steps, profile, traverse_z)
  data = mujoco.MjData(model)
  by_geom = {box.name: box for box in boxes}
  channels = {c: _Channel(model, c, tips, profile.segments, home) for c, home in homes.items()}

  worst: Dict[Tuple[int, int, str], Collision] = {}
  path_length = 0.0
  samples = 0
  reused = 0

  # One sample of the scene: every overlap between a moving channel and something solid.
  Hit = Tuple[int, str, str, float, Vec3]  # channel, solid geom, "tip" or "channel", depth, where

  def check(moving: Sequence[int]) -> List[Hit]:
    nonlocal samples
    samples += 1
    mujoco.mj_fwdPosition(model, data)
    hits: List[Hit] = []
    for i in range(data.ncon):
      contact = data.contact[i]
      depth = -contact.dist / MM
      if depth <= tolerance_mm:
        continue
      names = [model.geom(int(g)).name for g in contact.geom]
      probe = next((n for n in names if n.startswith("channel")), None)
      solid = next((n for n in names if n in by_geom), None)
      if probe is None or solid is None:
        continue
      channel = int(probe.split("/")[0][len("channel") :])
      if channel not in moving:  # a parked channel; it has not moved since it was last checked
        continue
      position = channels[channel].position
      assert position is not None
      hits.append((channel, solid, "tip" if "/tip" in probe else "channel", depth, position))
    return hits

  def place(channel: _Channel, position: Vec3) -> None:
    channel.position = position
    for address, value, origin in zip(channel.qpos, position, channel.home):
      data.qpos[address] = (value - origin) * MM

  # The scene never changes, so a move made before (same channels, same tips, same start and
  # end) hits the same things. A long protocol repeats most of its moves; each is simulated once.
  seen: Dict[tuple, List[Hit]] = {}
  ceiling = max((box.hi[2] for box in boxes if box.collides), default=0.0) + 1.0  # mm; clear above this

  def move(group: Dict[int, Step], targets: Dict[int, Vec3], phase: str) -> None:
    """Move every channel in the group to its target together, checking along the way."""
    nonlocal path_length, reused
    starts = {c: channels[c].position for c in targets}
    distances = {c: math.dist(starts[c], targets[c]) for c in targets}  # type: ignore[arg-type]
    longest = max(distances.values())
    if longest < 1e-9:
      return
    path_length += sum(distances.values())
    key = tuple(
      (c, channels[c].tip, tuple(round(v, 3) for v in starts[c]), tuple(round(v, 3) for v in targets[c]))  # type: ignore[union-attr]
      for c in sorted(targets)
    )
    clear = phase == "travel" and all(
      min(starts[c][2], targets[c][2]) - channels[c].reach > ceiling for c in targets  # type: ignore[index]
    )
    if clear and on_sample is None:
      # Every moving channel stays above the tallest solid in the scene: nothing to run into.
      for c, target in targets.items():
        place(channels[c], target)
      found: List[Hit] = []
    elif key in seen and on_sample is None:
      reused += 1
      for c, target in targets.items():
        place(channels[c], target)
      found = seen[key]
    else:
      first: Dict[Tuple[int, str, str], Hit] = {}
      count = max(1, math.ceil(longest / sample_mm))
      for i in range(1, count + 1):
        t = i / count
        for c, target in targets.items():
          start = starts[c]
          place(channels[c], tuple(a + (b - a) * t for a, b in zip(start, target)))  # type: ignore[arg-type]
        for hit in check(list(targets)):
          where = (hit[0], hit[1], hit[2])
          if where not in first:
            first[where] = hit
          elif hit[3] > first[where][3]:  # keep where the overlap began; only the depth grows
            first[where] = (*first[where][:3], hit[3], first[where][4])
        if on_sample is not None:
          on_sample(model, data, list(group.values()), phase)
      found = seen[key] = list(first.values())
    for channel, solid, part, depth, position in found:
      step = group.get(channel)
      if step is None:
        continue
      at = (step.index, channel, solid)
      if at in worst:
        if depth > worst[at].depth:
          worst[at] = replace(worst[at], depth=round(depth, 4))
        continue
      worst[at] = Collision(
        step=step.index,
        kind=step.kind,
        channel=channel,
        part=part,
        resource=by_geom[solid].resource,
        geom=solid,
        depth=round(depth, 4),
        at=tuple(round(v, 3) for v in position),  # type: ignore[arg-type]
        phase=phase,
      )

  # Every channel starts parked above its first target, with no tip.
  for channel in channels.values():
    channel.set_tip(model, None)
    place(channel, channel.home)

  # Channels named in one PyLabRobot call move together, as they do on the robot.
  commands: Dict[int, Dict[int, Step]] = {}
  for step in steps:
    if step.simulated and step.reference is not None:
      commands.setdefault(step.command, {})[step.channel] = step

  for group in commands.values():
    # The head cannot bring two channels closer than its pitch, or let one pass another.
    if min_channel_pitch:
      ordered = sorted(group)
      for a, b in zip(ordered, ordered[1:]):
        gap = group[a].reference[1] - group[b].reference[1]  # type: ignore[index]
        short = min_channel_pitch * (b - a) - gap
        if short > SPACING_TOLERANCE:
          worst[(group[b].index, b, f"channel{a}")] = Collision(
            step=group[b].index,
            kind=group[b].kind,
            channel=b,
            part="channel",
            resource=f"channel {a}",
            geom="spacing",
            depth=round(short, 4),
            at=tuple(round(v, 3) for v in group[b].reference),  # type: ignore[arg-type,union-attr]
            phase="descend",
          )

    # A tip is on for the whole of every step except the way down to pick one up.
    for c, step in group.items():
      channels[c].set_tip(model, None if step.kind == "pick_up_tip" else _tip_key(step))

    def cruise(c: int) -> float:
      return traverse_z + channels[c].reach

    move(group, {c: (*channels[c].position[:2], cruise(c)) for c in group}, "travel")  # type: ignore[index]
    move(group, {c: (s.reference[0], s.reference[1], cruise(c)) for c, s in group.items()}, "travel")  # type: ignore[index]
    move(group, {c: s.reference for c, s in group.items()}, "descend")  # type: ignore[misc]

    for c, step in group.items():
      if step.kind == "pick_up_tip":
        channels[c].set_tip(model, _tip_key(step))
      elif step.kind == "drop_tip":
        channels[c].set_tip(model, None)
    move(group, {c: (s.reference[0], s.reference[1], cruise(c)) for c, s in group.items()}, "ascend")  # type: ignore[index]

  collisions = sorted(worst.values(), key=lambda c: (c.step, c.channel, c.geom))
  return Rehearsal(
    steps=steps,
    collisions=collisions,
    not_rehearsed=[s for s in steps if not s.simulated],
    path_length=path_length,
    samples=samples,
    volumes=volumes(root),
    scene_xml=xml,
    layout=layout(root),
    traverse_z=traverse_z,
    liquid=liquid_issues(root, steps, start_volumes),
  )


def liquid_issues(
  root: Resource, steps: Sequence[Step], start_volumes: Optional[Dict[str, float]] = None
) -> List[LiquidIssue]:
  """Where each aspirate and dispense leaves the tip relative to the liquid and the rim.

  The liquid is followed through the steps in order. `start_volumes` is what every container
  held before the first step; when it is not given it is worked out backwards from what the
  containers under `root` hold now, which is right when `root` is the deck the steps ran on.
  """
  containers: Dict[str, Container] = {}

  def walk(resource: Resource) -> None:
    if isinstance(resource, Container):
      containers[resource.name] = resource
    for child in resource.children:
      walk(child)

  walk(root)
  acting = [s for s in steps if s.kind in ("aspirate", "dispense") and s.reference is not None and s.resource in containers]
  if start_volumes is None:
    held = {name: float(c.tracker.get_used_volume()) for name, c in containers.items()}
    for s in acting:
      held[s.resource] += (s.volume or 0.0) if s.kind == "aspirate" else -(s.volume or 0.0)
  else:
    held = {name: float(start_volumes.get(name, 0.0)) for name in containers}

  issues: List[LiquidIssue] = []
  for s in acting:
    container = containers[s.resource]
    floor, rim = cavity_floor_z(container), bounds(container)[1][2]
    end = s.tip_end[2]  # type: ignore[index]
    volume = s.volume or 0.0
    before = max(0.0, held[s.resource])
    sure = liquid_height_is_known(container) or before <= 0.0  # an empty well is empty whatever its shape

    def issue(kind: str, gap: float, certain: bool = True) -> None:
      issues.append(LiquidIssue(s.index, kind, s.kind, s.channel, s.resource, round(gap, 2), certain))

    if end > rim + RIM_ALLOWANCE:
      issue("outside", end - rim)
    elif s.kind == "aspirate":
      surface = floor + liquid_height(container, before)
      after = floor + liquid_height(container, max(0.0, before - volume))
      if end > surface - LIQUID_TOLERANCE:
        issue("air", end - surface, sure)
      elif end > after + LIQUID_TOLERANCE:
        issue("ends_in_air", end - after, sure)
    held[s.resource] = before - volume if s.kind == "aspirate" else before + volume
  return issues
