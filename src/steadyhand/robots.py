"""The robots steadyhand can plan for, and the software each one is driven through.

A protocol file says what to do. A robot here says how that becomes a program: `plan` makes the
choices, `emit` writes the program, and `rehearse` runs the plan through whatever can check it
without the machine. Adding a robot means adding one entry to `ROBOTS`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from .protocol import Check


@dataclass(frozen=True)
class Robot:
  name: str  # what a protocol file or --robot says
  title: str
  through: str  # the software the emitted program talks to
  program: str  # what `emit` writes
  rehearsal: Tuple[str, ...]  # what `rehearse` checks on this robot
  plan: Callable[..., Any]  # (checked, choices) -> a plan with .ok, .problems and .report()
  emit: Callable[..., str]  # (plan, source=) -> the program
  takes_plan_file: bool = False  # whether `--plan` can override the planner's choices


def _hamilton_plan(checked: Check, choices=None):
  from .planner import plan

  return plan(checked, choices)


def _hamilton_emit(planned, *, source: str = "") -> str:
  from .planner import emit

  return emit(planned, source=source)


def _opentrons(profile_name: str) -> Tuple[Callable[..., Any], Callable[..., str]]:
  def plan(checked: Check, choices=None):
    from . import opentrons_robots

    return opentrons_robots.plan(checked, opentrons_robots.PROFILES[profile_name])

  def emit(planned, *, source: str = "") -> str:
    from . import opentrons_robots

    return opentrons_robots.emit(planned, source=source)

  return plan, emit


_PHYSICS = (
  "PyLabRobot's own tip and volume tracking",
  "collisions, in a physics replay of every move",
  "tip depth against the liquid in each well",
  "spacing between channels",
)
_SIMULATOR = ("Opentrons' own simulator: labware, slots, pipettes and tip capacity",)

DEFAULT = "hamilton-starlet"

ROBOTS: Dict[str, Robot] = {
  "hamilton-starlet": Robot(
    "hamilton-starlet",
    "Hamilton STARlet",
    "PyLabRobot",
    "a PyLabRobot script",
    _PHYSICS,
    _hamilton_plan,
    _hamilton_emit,
    takes_plan_file=True,
  ),
  "opentrons-flex": Robot(
    "opentrons-flex", "Opentrons Flex", "Opentrons' Python API", "an Opentrons protocol", _SIMULATOR, *_opentrons("opentrons-flex")
  ),
  "opentrons-ot2": Robot(
    "opentrons-ot2", "Opentrons OT-2", "Opentrons' Python API", "an Opentrons protocol", _SIMULATOR, *_opentrons("opentrons-ot2")
  ),
}


def choose(asked: Optional[str], in_file: str = "") -> Robot:
  """The robot to plan for: what was asked for, else what the file says, else the Hamilton."""
  name = asked or in_file or DEFAULT
  if name not in ROBOTS:
    raise KeyError(f"no robot called {name!r}; known: {', '.join(ROBOTS)}")
  return ROBOTS[name]
