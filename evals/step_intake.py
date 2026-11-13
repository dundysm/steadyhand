"""Run the `drybench draft` conversation one turn at a time, for a model that is driven by hand or by an agent.

  python evals/step_intake.py prompt CASE          print what the model is sent next
  python evals/step_intake.py submit CASE REPLY    hand in the model's reply (a file); it is checked as draft checks it

The messages, the checking and the limit of three rounds are the ones `drybench.intake.draft` uses.
State is kept in evals/out/agents/CASE/.
"""

import asyncio
import json
import sys
from pathlib import Path

from drybench.intake import GUIDE, _problems_of, extract_yaml, labware_catalogue
from drybench.planner import RunRefused, plan, rehearse_plan

HERE = Path(__file__).parent
ROUNDS = 3


def state_of(case: str):
  folder = HERE / "out" / "agents" / case
  folder.mkdir(parents=True, exist_ok=True)
  path = folder / "state.json"
  if path.exists():
    return folder, json.loads(path.read_text(encoding="utf-8"))
  # a case is a note in evals/intake or evals/acceptance
  note = next(path for path in (HERE / "intake" / f"{case}.txt", HERE / "acceptance" / f"{case}.txt") if path.exists())
  source = note.read_text(encoding="utf-8")
  return folder, {
    "case": case,
    "messages": [
      {"role": "system", "content": GUIDE + "\nLABWARE\n" + labware_catalogue() + "\n"},
      {"role": "user", "content": "Write the drybench protocol file for this:\n\n" + source.strip() + "\n"},
    ],
    "history": [],
    "done": False,
    "draft": "-",
    "plan": "-",
    "rehearse": "-",
  }


def main() -> int:
  if len(sys.argv) < 3 or sys.argv[1] not in ("prompt", "submit"):
    print(__doc__)
    return 2
  folder, state = state_of(sys.argv[2])
  if sys.argv[1] == "prompt":
    if state["done"]:
      print(f"FINISHED: {state['case']} needs nothing more.")
      return 0
    print("\n\n".join(f"[{m['role']}]\n{m['content']}" for m in state["messages"]))
    return 0

  if state["done"]:
    print(f"FINISHED: {state['case']} needs nothing more.")
    return 0
  reply = Path(sys.argv[3]).read_text(encoding="utf-8")
  text = extract_yaml(reply)
  checked, problems = _problems_of(text, None)
  number = len(state["history"]) + 1
  (folder / f"round_{number}.yaml").write_text(text, encoding="utf-8")
  state["messages"].append({"role": "assistant", "content": reply})
  state["history"].append([str(problem) for problem in problems])
  if not problems:
    state["done"], state["draft"] = True, "pass"
    try:
      planned = plan(checked)
      state["plan"] = "pass" if planned.ok else "fail"
      state["plan_problems"] = [str(problem) for problem in planned.problems]
      if planned.ok:
        rehearsal = asyncio.run(rehearse_plan(planned))
        state["rehearse"] = "pass" if rehearsal.ok else f"fail ({len(rehearsal.collisions)} collisions)"
    except RunRefused as refused:  # PyLabRobot's own checks said no: a clean failure
      state["rehearse"] = f"fail ({refused})"
    except Exception as error:  # a crash here is a drybench bug, and worth recording as one
      state["rehearse"] = f"crash ({type(error).__name__}: {error})"
    state["notes"] = list(checked.protocol.notes)
    print(f"FINISHED: draft passed in round {number}; plan {state['plan']}; rehearse {state['rehearse']}")
    for problem in state.get("plan_problems", []):
      print(f"  plan problem: {problem}")
  else:
    listed = "\n".join(f"- {problem}" for problem in problems)
    feedback = "That file has these problems:\n" + listed + "\n\nWrite the whole file again with them fixed. Reply with the YAML only."
    state["messages"].append({"role": "user", "content": feedback})
    if number >= ROUNDS:
      state["done"], state["draft"] = True, "fail"
      print(f"FINISHED: draft still has problems after {ROUNDS} rounds:\n{listed}")
    else:
      print(f"ROUND {number} HAS PROBLEMS. Run `prompt` again for the next message. They are:\n{listed}")
  (folder / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
  return 0


if __name__ == "__main__":
  sys.exit(main())
