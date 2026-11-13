"""Command line for drybench."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import __version__
from .demo import FAULTS, run_demo
from .replay import Rehearsal, rehearse


def _keeper() -> Tuple[dict, Callable]:
  """Remember the moment the channels reach the bottom of the first aspirate, for a close-up."""
  kept: dict = {}

  def keep(model, data, steps, phase):
    if phase == "descend" and steps[0].kind == "aspirate" and kept.get("command", steps[0].command) == steps[0].command:
      kept.update(
        command=steps[0].command, model=model, qpos=data.qpos.copy(), rgba=model.geom_rgba.copy(), steps=steps
      )

  return kept, keep


def _write(result: Rehearsal, out: Path, kept: dict, render: bool) -> None:
  out.mkdir(parents=True, exist_ok=True)
  (out / "scene.xml").write_text(result.scene_xml)
  (out / "report.json").write_text(json.dumps(result.to_dict(), indent=2) + "\n")
  (out / "report.txt").write_text(result.report() + "\n")
  print(f"wrote {out / 'scene.xml'}, {out / 'report.json'}, {out / 'report.txt'}")
  if render:
    import mujoco

    from .render import close_up, render_model, render_png

    try:
      print(f"wrote {render_png(result.scene_xml, out / 'scene.png')}")
      if kept:
        model = kept["model"]
        model.geom_rgba[:] = kept["rgba"]
        data = mujoco.MjData(model)
        data.qpos[:] = kept["qpos"]
        ends = [s.tip_end for s in kept["steps"]]
        middle = [sum(e[i] for e in ends) / len(ends) for i in range(3)]
        middle[2] += 25.0
        print(f"wrote {render_model(model, data, out / 'aspirate.png', camera=close_up(middle))}")
    except RuntimeError as error:
      print(f"no picture: {error}")
  print(f"to look around the scene: python -m mujoco.viewer --mjcf {out / 'scene.xml'}")


def _demo(args: argparse.Namespace) -> int:
  deck, backend = asyncio.run(run_demo(args.fault))
  kept, keep = _keeper()
  result = rehearse(deck, backend.steps, on_sample=None if args.no_render else keep)
  print(f"demo: {FAULTS[args.fault]}")
  print(result.report())
  _write(result, Path(args.out), kept, not args.no_render)
  return 0 if result.ok else 1


def _load_checked(path: str):
  """Read and check a protocol file. Prints what is wrong and returns None when it cannot be read."""
  from .protocol import ProtocolError, check, load

  try:
    protocol = load(path)
  except FileNotFoundError:
    print(f"drybench: cannot find {path}")
    return None
  except ProtocolError as error:
    print(f"drybench check: FAIL  {path} cannot be read as a protocol")
    print(f"  problems: {len(error.problems)}")
    for problem in error.problems:
      print(f"    - {problem}")
    return None
  return check(protocol)


def _check(args: argparse.Namespace) -> int:
  result = _load_checked(args.file)
  if result is None:
    return 1
  print(result.report())
  if args.moves:
    print("  moves, in order:")
    for move in result.moves:
      if move.kind == "transfer":
        print(f"    step {move.step}  tip {move.tip:<3}  {move.volume:>7g} uL  {move.source} -> {move.destination}")
      elif move.kind == "mix":
        print(f"    step {move.step}  tip {move.tip:<3}  mix {move.times} x {move.volume:g} uL in {move.source}")
      else:
        print(f"    step {move.step}  wait {move.seconds / 60:g} min")
  return 0 if result.ok else 1


def _planned(path: str):
  """Check and plan a protocol file. Prints both reports; returns the plan, or None when either fails."""
  from .planner import plan

  checked = _load_checked(path)
  if checked is None:
    return None
  print(checked.report())
  if not checked.ok:
    return None
  planned = plan(checked)
  print(planned.report())
  return planned if planned.ok else None


def _plan(args: argparse.Namespace) -> int:
  return 0 if _planned(args.file) is not None else 1


def _rehearse(args: argparse.Namespace) -> int:
  from .planner import emit, rehearse_plan

  planned = _planned(args.file)
  if planned is None:
    return 1
  kept, keep = _keeper()
  result = asyncio.run(rehearse_plan(planned, on_sample=None if args.no_render else keep))
  print(result.report())
  out = Path(args.out)
  _write(result, out, kept, not args.no_render)
  if result.ok:
    (out / "protocol.py").write_text(emit(planned, source=args.file))
    print(f"wrote {out / 'protocol.py'}")
  return 0 if result.ok else 1


def _emit(args: argparse.Namespace) -> int:
  from .planner import emit

  planned = _planned(args.file)
  if planned is None:
    return 1
  script = emit(planned, source=args.file)
  if args.output:
    Path(args.output).write_text(script)
    print(f"wrote {args.output}")
  else:
    print(script)
  return 0


def main(argv: Optional[List[str]] = None) -> int:
  parser = argparse.ArgumentParser(
    prog="drybench", description="Rehearse a lab-robot protocol in a physics scene."
  )
  parser.add_argument("--version", action="version", version=f"drybench {__version__}")
  commands = parser.add_subparsers(dest="command", required=True)

  check = commands.add_parser("check", help="read a protocol file and follow its liquid through every move")
  check.add_argument("file", help="a drybench protocol file (YAML)")
  check.add_argument("--moves", action="store_true", help="also list every move the steps expand into")
  check.set_defaults(run=_check)

  plan = commands.add_parser("plan", help="check a protocol, then choose tips, channels and a deck layout")
  plan.add_argument("file", help="a drybench protocol file (YAML)")
  plan.set_defaults(run=_plan)

  rehearse_ = commands.add_parser("rehearse", help="check and plan a protocol, then replay it in the physics scene")
  rehearse_.add_argument("file", help="a drybench protocol file (YAML)")
  rehearse_.add_argument("--out", default="drybench-out", help="folder for the scene, the report and the script")
  rehearse_.add_argument("--no-render", action="store_true", help="skip the PNG pictures")
  rehearse_.set_defaults(run=_rehearse)

  emit = commands.add_parser("emit", help="check and plan a protocol, then write it as a PyLabRobot script")
  emit.add_argument("file", help="a drybench protocol file (YAML)")
  emit.add_argument("-o", "--output", help="where to write the script; printed when left out")
  emit.set_defaults(run=_emit)

  demo = commands.add_parser("demo", help="rehearse a built-in transfer on a Hamilton STARlet deck")
  demo.add_argument("--fault", choices=sorted(FAULTS), default="none", help="a mistake to plant in the protocol")
  demo.add_argument("--out", default="drybench-out", help="folder for the scene and the report")
  demo.add_argument("--no-render", action="store_true", help="skip the PNG picture")
  demo.set_defaults(run=_demo)

  args = parser.parse_args(argv)
  return args.run(args)


if __name__ == "__main__":
  sys.exit(main())
