"""Command line for drybench."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .demo import FAULTS, run_demo
from .replay import rehearse


def _demo(args: argparse.Namespace) -> int:
  deck, backend = asyncio.run(run_demo(args.fault))

  # Keep the moment the channels reach the bottom of the first aspirate, for a close-up picture.
  kept: dict = {}

  def keep(model, data, steps, phase):
    if phase == "descend" and steps[0].kind == "aspirate" and kept.get("command", steps[0].command) == steps[0].command:
      kept.update(
        command=steps[0].command, model=model, qpos=data.qpos.copy(), rgba=model.geom_rgba.copy(), steps=steps
      )

  result = rehearse(deck, backend.steps, on_sample=None if args.no_render else keep)

  out = Path(args.out)
  out.mkdir(parents=True, exist_ok=True)
  (out / "scene.xml").write_text(result.scene_xml)
  (out / "report.json").write_text(json.dumps(result.to_dict(), indent=2) + "\n")
  (out / "report.txt").write_text(result.report() + "\n")

  print(f"demo: {FAULTS[args.fault]}")
  print(result.report())
  print(f"wrote {out / 'scene.xml'}, {out / 'report.json'}, {out / 'report.txt'}")

  if not args.no_render:
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
  return 0 if result.ok else 1


def _check(args: argparse.Namespace) -> int:
  from .protocol import ProtocolError, check, load

  try:
    protocol = load(args.file)
  except FileNotFoundError:
    print(f"drybench check: cannot find {args.file}")
    return 1
  except ProtocolError as error:
    print(f"drybench check: FAIL  {args.file} cannot be read as a protocol")
    print(f"  problems: {len(error.problems)}")
    for problem in error.problems:
      print(f"    - {problem}")
    return 1

  result = check(protocol)
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


def main(argv: Optional[List[str]] = None) -> int:
  parser = argparse.ArgumentParser(
    prog="drybench", description="Rehearse a lab-robot protocol in a physics scene."
  )
  parser.add_argument("--version", action="version", version=f"drybench {__version__}")
  commands = parser.add_subparsers(dest="command", required=True)

  demo = commands.add_parser("demo", help="rehearse a built-in transfer on a Hamilton STARlet deck")
  demo.add_argument("--fault", choices=sorted(FAULTS), default="none", help="a mistake to plant in the protocol")
  demo.add_argument("--out", default="drybench-out", help="folder for the scene and the report")
  demo.add_argument("--no-render", action="store_true", help="skip the PNG picture")
  demo.set_defaults(run=_demo)

  check = commands.add_parser("check", help="read a protocol file and follow its liquid through every move")
  check.add_argument("file", help="a drybench protocol file (YAML)")
  check.add_argument("--moves", action="store_true", help="also list every move the steps expand into")
  check.set_defaults(run=_check)

  args = parser.parse_args(argv)
  return args.run(args)


if __name__ == "__main__":
  sys.exit(main())
