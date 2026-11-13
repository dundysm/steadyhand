"""Run `drybench draft` on every note in evals/intake with a real model, then plan and rehearse what it wrote.

  python evals/run_intake.py --model-command "claude -p"
  python evals/run_intake.py --provider anthropic --model NAME      (reads ANTHROPIC_API_KEY)
  python evals/run_intake.py --provider openai --model NAME         (reads OPENAI_API_KEY)

Writes each drafted file and a results table to evals/out/. A drafted file that passes here was still
written by a model: this measures whether the output is usable, not whether it matches the notes.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from drybench.intake import ModelError, anthropic_model, command_model, draft, openai_model
from drybench.planner import plan, rehearse_plan

HERE = Path(__file__).parent


def one(note: Path, model, rounds: int, out: Path) -> dict:
  row = {"case": note.stem, "draft": "error", "rounds": 0, "plan": "-", "rehearse": "-", "seconds": 0.0, "problems": [], "fixed": []}
  started = time.time()
  try:
    result = draft(note.read_text(encoding="utf-8"), model, max_rounds=rounds)
  except ModelError as error:
    row["problems"] = [str(error)]
    row["seconds"] = round(time.time() - started, 1)
    return row
  (out / f"{note.stem}.yaml").write_text(result.text, encoding="utf-8")
  row["rounds"] = result.rounds
  row["draft"] = "pass" if result.ok else "fail"
  row["problems"] = [str(problem) for problem in result.problems]
  # what the model got wrong on the way, round by round: this is what the prompt should be tuned against
  row["fixed"] = [[str(problem) for problem in found] for found in result.history[:-1]] if result.ok else []
  if result.ok:
    planned = plan(result.checked)
    row["plan"] = "pass" if planned.ok else "fail"
    row["problems"] += [str(problem) for problem in planned.problems]
    if planned.ok:
      rehearsal = asyncio.run(rehearse_plan(planned))
      row["rehearse"] = "pass" if rehearsal.ok else f"fail ({len(rehearsal.collisions)} collisions)"
  row["seconds"] = round(time.time() - started, 1)
  return row


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--provider", choices=("anthropic", "openai"))
  parser.add_argument("--model")
  parser.add_argument("--model-command")
  parser.add_argument("--rounds", type=int, default=3)
  parser.add_argument("--out", default=str(HERE / "out"))
  args = parser.parse_args()
  if args.model_command:
    model, label = command_model(args.model_command), args.model_command
  elif args.provider and args.model:
    model = (anthropic_model if args.provider == "anthropic" else openai_model)(args.model)
    label = f"{args.provider} {args.model}"
  else:
    parser.error("say which model to use, with --model-command CMD or --provider NAME --model NAME")
  out = Path(args.out)
  out.mkdir(parents=True, exist_ok=True)

  rows = []
  for note in sorted((HERE / "intake").glob("*.txt")):
    print(f"{note.stem} ...", flush=True)
    rows.append(one(note, model, args.rounds, out))
    print(f"  draft {rows[-1]['draft']} after {rows[-1]['rounds']} round(s); plan {rows[-1]['plan']}; "
          f"rehearse {rows[-1]['rehearse']}; {rows[-1]['seconds']} s", flush=True)

  lines = [f"model: {label}", "", "| case | draft | rounds | plan | rehearse | seconds |", "|---|---|---|---|---|---|"]
  lines += [f"| {r['case']} | {r['draft']} | {r['rounds']} | {r['plan']} | {r['rehearse']} | {r['seconds']} |" for r in rows]
  for r in rows:
    if r["problems"]:
      lines += ["", f"{r['case']}, still wrong at the end:"] + [f"- {problem}" for problem in r["problems"]]
    for number, found in enumerate(r["fixed"], start=1):
      lines += ["", f"{r['case']}, wrong after round {number} and later fixed:"] + [f"- {problem}" for problem in found]
  (out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
  (out / "results.json").write_text(json.dumps({"model": label, "cases": rows}, indent=2), encoding="utf-8")
  print("\n" + "\n".join(lines))
  return 0 if all(r["rehearse"] == "pass" for r in rows) else 1


if __name__ == "__main__":
  sys.exit(main())
