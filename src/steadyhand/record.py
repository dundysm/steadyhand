"""Record what a PyLabRobot protocol asks a liquid handler to do.

`RecordingBackend` is a drop-in PyLabRobot backend. Run a protocol against it and it keeps one
`Step` per channel per command, with the position each channel has to reach, worked out the
same way the Hamilton STAR backend works it out:

* picking up a tip: the channel goes down to the tip's top minus its fitting depth;
* aspirating or dispensing: the tip's end goes to the cavity floor plus the liquid height the
  protocol gave (zero if it gave none), plus the protocol's offset.

Positions are absolute, in mm, in the deck's frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from pylabrobot.liquid_handling.backends import LiquidHandlerChatterboxBackend
from pylabrobot.liquid_handling.standard import (
  Drop,
  Pickup,
  SingleChannelAspiration,
  SingleChannelDispense,
)
from pylabrobot.resources import Container, Resource, TipSpot

Vec3 = Tuple[float, float, float]


@dataclass(frozen=True)
class Step:
  """One channel doing one thing.

  `reference` is where the channel's reference point is at the bottom of the move. With a tip
  on, the tip's end is `reach` below it, where `reach = tip_length - fitting_depth`.
  """

  index: int
  command: int  # steps recorded from the same PyLabRobot call share a command number
  kind: str  # "pick_up_tip", "aspirate", "dispense", "drop_tip" or "unsimulated:<name>"
  channel: int
  resource: str
  reference: Optional[Vec3]
  tip_length: float = 0.0
  fitting_depth: float = 0.0
  volume: Optional[float] = None
  liquid_height: Optional[float] = None

  @property
  def reach(self) -> float:
    """How far below the channel's reference point the tip's end is, in mm."""
    return self.tip_length - self.fitting_depth

  @property
  def tip_end(self) -> Optional[Vec3]:
    if self.reference is None:
      return None
    x, y, z = self.reference
    return (x, y, z - self.reach)

  @property
  def simulated(self) -> bool:
    return not self.kind.startswith("unsimulated:")


def _centre_bottom(resource: Resource) -> Vec3:
  c = resource.get_absolute_location("c", "c", "b")
  return (c.x, c.y, c.z)


def _cavity_floor(resource: Resource) -> Vec3:
  if isinstance(resource, Container):
    try:
      c = resource.get_absolute_location("c", "c", "cavity_bottom")
      return (c.x, c.y, c.z)
    except Exception:
      pass
  return _centre_bottom(resource)


class RecordingBackend(LiquidHandlerChatterboxBackend):
  """A PyLabRobot backend that records steps instead of moving anything."""

  def __init__(self, num_channels: int = 8):
    super().__init__(num_channels=num_channels)
    self.steps: List[Step] = []
    self._command = 0

  async def setup(self):
    # Skip the chatterbox's printing; keep the base class bookkeeping.
    await super(LiquidHandlerChatterboxBackend, self).setup()

  async def stop(self):
    pass

  def _add(self, **fields) -> None:
    self.steps.append(Step(index=len(self.steps), command=self._command, **fields))

  async def pick_up_tips(self, ops: List[Pickup], use_channels: List[int], **backend_kwargs):
    self._command += 1
    for op, channel in zip(ops, use_channels):
      x, y, z = _centre_bottom(op.resource)
      tip = op.tip
      reach = tip.total_tip_length - tip.fitting_depth
      self._add(
        kind="pick_up_tip",
        channel=channel,
        resource=op.resource.name,
        reference=(x + op.offset.x, y + op.offset.y, z + op.offset.z + reach),
        tip_length=tip.total_tip_length,
        fitting_depth=tip.fitting_depth,
      )

  async def drop_tips(self, ops: List[Drop], use_channels: List[int], **backend_kwargs):
    self._command += 1
    for op, channel in zip(ops, use_channels):
      tip = op.tip
      reach = tip.total_tip_length - tip.fitting_depth
      if isinstance(op.resource, TipSpot):
        x, y, z = _centre_bottom(op.resource)
      else:  # a trash: let go with the tip's end at the top of it
        c = op.resource.get_absolute_location("c", "c", "t")
        x, y, z = c.x, c.y, c.z
      self._add(
        kind="drop_tip",
        channel=channel,
        resource=op.resource.name,
        reference=(x + op.offset.x, y + op.offset.y, z + op.offset.z + reach),
        tip_length=tip.total_tip_length,
        fitting_depth=tip.fitting_depth,
      )

  def _pipette(self, kind: str, ops, use_channels: List[int]) -> None:
    self._command += 1
    for op, channel in zip(ops, use_channels):
      x, y, z = _cavity_floor(op.resource)
      tip = op.tip
      reach = tip.total_tip_length - tip.fitting_depth
      height = op.liquid_height or 0.0
      self._add(
        kind=kind,
        channel=channel,
        resource=op.resource.name,
        reference=(x + op.offset.x, y + op.offset.y, z + op.offset.z + height + reach),
        tip_length=tip.total_tip_length,
        fitting_depth=tip.fitting_depth,
        volume=op.volume,
        liquid_height=op.liquid_height,
      )

  async def aspirate(self, ops: List[SingleChannelAspiration], use_channels: List[int], **backend_kwargs):
    self._pipette("aspirate", ops, use_channels)

  async def dispense(self, ops: List[SingleChannelDispense], use_channels: List[int], **backend_kwargs):
    self._pipette("dispense", ops, use_channels)

  # Everything below is recorded so a report can say plainly that it was not rehearsed.

  def _unsimulated(self, name: str, resource: str = "") -> None:
    self._command += 1
    self._add(kind=f"unsimulated:{name}", channel=-1, resource=resource, reference=None)

  async def pick_up_tips96(self, pickup, **backend_kwargs):
    self._unsimulated("pick_up_tips96", pickup.resource.name)

  async def drop_tips96(self, drop, **backend_kwargs):
    self._unsimulated("drop_tips96", drop.resource.name)

  async def aspirate96(self, aspiration, **backend_kwargs):
    self._unsimulated("aspirate96")

  async def dispense96(self, dispense, **backend_kwargs):
    self._unsimulated("dispense96")

  async def pick_up_resource(self, pickup, **backend_kwargs):
    self._unsimulated("pick_up_resource", pickup.resource.name)

  async def move_picked_up_resource(self, move, **backend_kwargs):
    self._unsimulated("move_picked_up_resource")

  async def drop_resource(self, drop, **backend_kwargs):
    self._unsimulated("drop_resource", drop.resource.name)
