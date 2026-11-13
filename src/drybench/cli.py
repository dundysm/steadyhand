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


def _write(result: Rehearsal, out: Path, kept: dict, render: bool, title: str = "") -> None:
  out.mkdir(parents=True, exist_ok=True)
  (out / "scene.xml").write_text(result.scene_xml)
  (out / "report.json").write_text(json.dumps(result.to_dict(), indent=2) + "\n")
  (out / "report.txt").write_text(result.report() + "\n")
  (out / "replay.html").write_text(result.replay_html(title), encoding="utf-8")
  print(f"wrote {out / 'scene.xml'}, {out / 'report.json'}, {out / 'report.txt'}")
  print(f"open {out / 'replay.html'} in a browser to watch the run")
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
  _write(result, Path(args.out), kept, not args.no_render, f"drybench demo: {FAULTS[args.fault]}")
  return 0 if result.ok else 1


def _faults(args: argparse.Namespace) -> int:
  from .faults import run_suite

  print("planting mistakes in a short dilution; this takes about half a minute")
  report = run_suite()
  print(report.text())
  if args.output:
    Path(args.output).write_text(report.markdown(), encoding="utf-8")
    print(f"wrote {args.output}")
  return 0 if not report.clean.caught else 1


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


def _planned(path: str, choices_path: Optional[str] = None):
  """Check and plan a protocol file. Prints both reports; returns the plan, or None when either fails."""
  from .planner import load_choices, plan
  from .protocol import ProtocolError

  checked = _load_checked(path)
  if checked is None:
    return None
  print(checked.report())
  if not checked.ok:
    return None
  choices = None
  if choices_path:
    try:
      choices = load_choices(choices_path)
    except FileNotFoundError:
      print(f"drybench: cannot find {choices_path}")
      return None
    except ProtocolError as error:
      print(f"drybench plan: FAIL  {choices_path} cannot be read as a plan file")
      print(f"  problems: {len(error.problems)}")
      for problem in error.problems:
        print(f"    - {problem}")
      return None
  planned = plan(checked, choices)
  print(planned.report())
  if choices_path:
    print(f"  using choices from {choices_path}")
  return planned if planned.ok else None


def _plan(args: argparse.Namespace) -> int:
  from .planner import dump_choices

  planned = _planned(args.file, args.plan)
  if planned is None:
    return 1
  if args.output:
    Path(args.output).write_text(dump_choices(planned, source=args.file), encoding="utf-8")
    print(f"wrote {args.output}; edit it and pass it back with --plan")
  return 0


def _rehearse(args: argparse.Namespace) -> int:
  from .planner import RunRefused, emit, rehearse_plan

  planned = _planned(args.file, args.plan)
  if planned is None:
    return 1
  kept, keep = _keeper()
  try:
    result = asyncio.run(rehearse_plan(planned, on_sample=None if args.no_render else keep))
  except RunRefused as refused:
    print("drybench rehearsal: FAIL")
    print(f"  {refused}")
    print("  Nothing was replayed: the run stops at the first command PyLabRobot will not accept.")
    return 1
  print(result.report())
  out = Path(args.out)
  _write(result, out, kept, not args.no_render, planned.protocol.name)
  if result.ok:
    (out / "protocol.py").write_text(emit(planned, source=args.file))
    print(f"wrote {out / 'protocol.py'}")
  return 0 if result.ok else 1


def _emit(args: argparse.Namespace) -> int:
  from .planner import emit

  planned = _planned(args.file, args.plan)
  if planned is None:
    return 1
  script = emit(planned, source=args.file)
  if args.output:
    Path(args.output).write_text(script)
    print(f"wrote {args.output}")
  else:
    print(script)
  return 0


def _draft(args: argparse.Namespace) -> int:
  from .intake import ModelError, anthropic_model, command_model, draft, openai_model

  try:
    source = sys.stdin.read() if args.source == "-" else Path(args.source).read_text()
  except OSError as error:
    print(f"drybench draft: cannot read {args.source}: {error}")
    return 1
  try:
    if args.model_command:
      model = command_model(args.model_command)
    elif args.provider and args.model:
      model = (anthropic_model if args.provider == "anthropic" else openai_model)(args.model)
    else:
      print("drybench draft: say which model to use, with --model-command CMD or --provider NAME --model NAME")
      return 1
    samples = Path(args.samples) if args.samples else None
    if samples is not None and not samples.is_file():
      print(f"drybench draft: cannot find {samples}")
      return 1
    if samples is not None and samples.resolve().parent != Path(args.output).resolve().parent:
      print(f"drybench draft: the protocol names its samples file by name, so write it next to {samples}")
      print(f"  for example: -o {samples.parent / Path(args.output).name}")
      return 1
    result = draft(source, model, samples=samples, max_rounds=args.rounds)
  except ModelError as error:
    print(f"drybench draft: {error}")
    return 1

  Path(args.output).write_text(result.text)
  asked = "once" if result.rounds == 1 else f"{result.rounds} times"
  print(f"drybench draft: {'PASS' if result.ok else 'FAIL'}  the model was asked {asked}")
  if result.checked is not None:
    print(result.checked.report())
  else:
    print(f"  problems: {len(result.problems)}")
    for problem in result.problems:
      print(f"    - {problem}")
  print(f"wrote {args.output}")
  if result.ok:
    print("A model wrote this file. Read it against your source before you rehearse or run it.")
  elif result.left_for_a_person:
    print("The model kept the file as it is: fixing these problems means changing what your text says,")
    print("or supplying something it does not have. Decide what to change, then run drybench check.")
  else:
    print("The file still has problems after the last try. Fix it by hand, then run drybench check.")
  return 0 if result.ok else 1


def main(argv: Optional[List[str]] = None) -> int:
  parser = argparse.ArgumentParser(
    prog="drybench", description="Rehearse a lab-robot protocol in a physics scene."
  )
  parser.add_argument("--version", action="version", version=f"drybench {__version__}")
  commands = parser.add_subparsers(dest="command", required=True)

  draft = commands.add_parser("draft", help="have a language model write a protocol file from plain text")
  draft.add_argument("source", help="a text file with notes, a kit manual or a description; '-' reads stdin")
  draft.add_argument("-o", "--output", required=True, help="where to write the protocol file")
  draft.add_argument("--provider", choices=("anthropic", "openai"), help="an API to call; needs --model")
  draft.add_argument("--model", help="the model's name at that provider")
  draft.add_argument("--model-command", help="a shell command that reads a prompt on stdin and prints a reply")
  draft.add_argument("--samples", help="a CSV of per-sample concentrations, for normalizing; kept next to the output")
  draft.add_argument("--rounds", type=int, default=3, help="how many times the model may be asked (default 3)")
  draft.set_defaults(run=_draft)

  check = commands.add_parser("check", help="read a protocol file and follow its liquid through every move")
  check.add_argument("file", help="a drybench protocol file (YAML)")
  check.add_argument("--moves", action="store_true", help="also list every move the steps expand into")
  check.set_defaults(run=_check)

  plan = commands.add_parser("plan", help="check a protocol, then choose tips, channels and a deck layout")
  plan.add_argument("file", help="a drybench protocol file (YAML)")
  plan.add_argument("-o", "--output", help="write the tips, deck and pipetting height to a plan file you can edit")
  plan.add_argument("--plan", help="a plan file whose choices replace the planner's own")
  plan.set_defaults(run=_plan)

  rehearse_ = commands.add_parser("rehearse", help="check and plan a protocol, then replay it in the physics scene")
  rehearse_.add_argument("file", help="a drybench protocol file (YAML)")
  rehearse_.add_argument("--out", default="drybench-out", help="folder for the scene, the report and the script")
  rehearse_.add_argument("--no-render", action="store_true", help="skip the PNG pictures")
  rehearse_.add_argument("--plan", help="a plan file whose choices replace the planner's own")
  rehearse_.set_defaults(run=_rehearse)

  emit = commands.add_parser("emit", help="check and plan a protocol, then write it as a PyLabRobot script")
  emit.add_argument("file", help="a drybench protocol file (YAML)")
  emit.add_argument("-o", "--output", help="where to write the script; printed when left out")
  emit.add_argument("--plan", help="a plan file whose choices replace the planner's own")
  emit.set_defaults(run=_emit)

  demo = commands.add_parser("demo", help="rehearse a built-in transfer on a Hamilton STARlet deck")
  demo.add_argument("--fault", choices=sorted(FAULTS), default="none", help="a mistake to plant in the protocol")
  demo.add_argument("--out", default="drybench-out", help="folder for the scene and the report")
  demo.add_argument("--no-render", action="store_true", help="skip the PNG picture")
  demo.set_defaults(run=_demo)

  faults = commands.add_parser("faults", help="plant known mistakes in a working protocol and list which are stopped")
  faults.add_argument("-o", "--output", help="also write the table as Markdown")
  faults.set_defaults(run=_faults)

  args = parser.parse_args(argv)
  return args.run(args)


if __name__ == "__main__":
  sys.exit(main())
