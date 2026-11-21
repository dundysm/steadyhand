"""Rehearse every protocol in a checkout of Opentrons' public protocol library.

    python evals/library/run.py /path/to/Protocols /path/to/out --jobs 8

The library (github.com/Opentrons/Protocols) is not copied here. Each protocol there reads its
parameters through `get_values`, which the library's own build supplies from `fields.json`; this
does the same, with every parameter at its default, analyses the protocol with Opentrons'
software and rehearses the commands that come back. One JSON file per protocol goes to the
output folder, and `summary.json` counts them.

Analysing a protocol runs its Python. Run this only where running other people's code is
acceptable: a container or a machine with nothing on it you would mind losing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def defaults(fields_file: Path) -> dict:
  """Every parameter at its default, as the library's own build fills them in."""
  values = {}
  if not fields_file.exists():
    return values
  for item in json.loads(fields_file.read_text()):
    if item.get("type") == "dropDown":
      values[item["name"]] = item["options"][0]["value"]
    elif item.get("type") == "textFile":
      values[item["name"]] = item.get("default", "")
    else:
      values[item["name"]] = item.get("default")
  return values


def with_values(text: str, values: dict) -> str:
  """The protocol with a `get_values` in front of it that hands back `values`."""
  prefix = (
    "def get_values(*names):\n"
    "    import json\n"
    f"    _all_values = json.loads({json.dumps(values)!r})\n"
    "    return [_all_values[n] for n in names]\n\n"
  )
  if text.startswith("from __future__"):
    first, _, rest = text.partition("\n")
    return first + "\n" + prefix + rest
  return prefix + text


def one(folder: Path, out: Path) -> dict:
  """Analyse and rehearse the protocol in `folder`. Runs in a process of its own."""
  from steadyhand.opentrons_import import ImportFailed, load, rehearse_imported

  sources = sorted(folder.glob("*.py"))
  record = {"id": folder.name, "status": "", "file": sources[0].name if sources else ""}
  if not sources:
    return {**record, "status": "no protocol file"}
  work = out / "work" / folder.name
  work.mkdir(parents=True, exist_ok=True)
  protocol = work / "protocol.py"
  text = sources[0].read_text(encoding="utf-8", errors="replace")
  protocol.write_text(with_values(text, defaults(folder / "fields.json")), encoding="utf-8")
  labware = [folder / "labware"] if (folder / "labware").is_dir() else []
  started = time.time()
  try:
    imported = load(protocol, labware)
  except ImportFailed as error:
    return {**record, "status": "not analysed", "why": str(error)[:300]}
  record.update(
    name=imported.name, robot=imported.profile.title, api=imported.api, commands=imported.commands,
    followed=imported.followed, stopped=imported.stopped, errors=imported.errors, notes=imported.notes,
    declared=len(imported.declared),
  )  # fmt: skip
  if imported.errors:
    return {**record, "status": "analysis objects", "seconds": round(time.time() - started, 1)}
  try:
    result = asyncio.run(rehearse_imported(imported))
  except Exception as error:
    return {**record, "status": "deck not built", "why": " ".join(str(error).split())[:300], "problems": imported.problems}
  failures = result.liquid_failures
  record.update(
    problems=imported.problems, assumed=len(imported.assumed), stopped=imported.stopped,
    steps=len(result.steps), collisions=len(result.collisions),
    collision_text=[str(c) for c in result.collisions[:5]],
    liquid_failures=len(failures), liquid_text=[i.describe() for i in failures[:8]],
    liquid_kinds=dict(Counter(i.kind for i in failures)),
    seconds=round(time.time() - started, 1),
  )  # fmt: skip
  if imported.stopped:
    record["status"] = "followed in part"
  elif imported.problems or not result.ok:
    record["status"] = "findings"
  else:
    record["status"] = "clean"
  return record


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("library", help="a checkout of github.com/Opentrons/Protocols")
  parser.add_argument("out", help="folder for the results")
  parser.add_argument("--jobs", type=int, default=4)
  parser.add_argument("--only", type=int, default=0, help="the first N protocols only")
  parser.add_argument("--timeout", type=float, default=1200.0, help="seconds allowed for one protocol")
  parser.add_argument("--one", help=argparse.SUPPRESS)
  args = parser.parse_args()
  out = Path(args.out)
  if args.one:
    record = one(Path(args.one), out)
    (out / "results" / f"{record['id']}.json").write_text(json.dumps(record, indent=1) + "\n")
    return 0
  (out / "results").mkdir(parents=True, exist_ok=True)
  folders = sorted(p for p in (Path(args.library) / "protocols").iterdir() if p.is_dir())
  if args.only:
    folders = folders[: args.only]

  def run(folder: Path) -> None:
    done = out / "results" / f"{folder.name}.json"
    if done.exists():
      return
    command = [sys.executable, __file__, args.library, args.out, "--one", str(folder)]
    try:
      ran = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
      if not done.exists():
        last = (ran.stderr or ran.stdout).strip().splitlines()[-1:] or ["no output"]
        done.write_text(json.dumps({"id": folder.name, "status": "crashed", "why": last[0][:300]}) + "\n")
    except subprocess.TimeoutExpired:
      done.write_text(json.dumps({"id": folder.name, "status": "timed out"}) + "\n")

  with ThreadPoolExecutor(max_workers=args.jobs) as pool:
    list(pool.map(run, folders))
  records = [json.loads(p.read_text()) for p in sorted((out / "results").glob("*.json"))]
  summary = {"protocols": len(records), "status": dict(Counter(r["status"] for r in records))}
  (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
  print(json.dumps(summary, indent=1))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
