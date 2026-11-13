"""Run the `steadyhand draft` conversation one turn at a time, for a model that is driven by hand or by an agent.

  python evals/step_intake.py prompt CASE          print what the model is sent next
  python evals/step_intake.py submit CASE REPLY    hand in the model's reply (a file); it is checked as draft checks it

Set STEADYHAND_EVAL_ROBOT to draft for another robot, such as opentrons-flex. A draft that passes is
then planned for that robot and run through whatever rehearses it.

The messages, the checking and the limit of three rounds are the ones `steadyhand.intake.draft` uses.
State is kept in evals/out/agents/CASE/, or evals/out/agents-ROBOT/CASE/ for a named robot.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from steadyhand.intake import _problems_of, extract_yaml, feedback, messages_for
from steadyhand.planner import RunRefused, plan, rehearse_plan

HERE = Path(__file__).parent
ROUNDS = 3
ROBOT = os.environ.get("STEADYHAND_EVAL_ROBOT", "")


def state_of(case: str):
  folder = HERE / "out" / (f"agents-{ROBOT}" if ROBOT else "agents") / case
  folder.mkdir(parents=True, exist_ok=True)
  path = folder / "state.json"
  if path.exists():
    return folder, json.loads(path.read_text(encoding="utf-8"))
  # a case is a note in evals/intake or evals/acceptance
  note = next(path for path in (HERE / "intake" / f"{case}.txt", HERE / "acceptance" / f"{case}.txt") if path.exists())
  source = note.read_text(encoding="utf-8")
  table = note.with_suffix(".csv")  # a samples file beside the note is offered with it
  return folder, {
    "case": case,
    "samples": str(table) if table.exists() else "",
    "messages": messages_for(source, table if table.exists() else None, ROBOT),
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
  checked, problems = _problems_of(text, Path(state["samples"]).parent if state.get("samples") else None, ROBOT)
  number = len(state["history"]) + 1
  (folder / f"round_{number}.yaml").write_text(text, encoding="utf-8")
  state["messages"].append({"role": "assistant", "content": reply})
  state["history"].append([str(problem) for problem in problems])
  if not problems:
    state["done"], state["draft"] = True, "pass"
    try:
      if ROBOT and ROBOT != "hamilton-starlet":
        from steadyhand import opentrons_robots

        planned = opentrons_robots.plan(checked, opentrons_robots.PROFILES[ROBOT])
        state["plan"] = "pass" if planned.ok else "fail"
        state["plan_problems"] = [str(problem) for problem in planned.problems]
        if planned.ok:
          result = opentrons_robots.simulate(opentrons_robots.emit(planned), planned.profile)
          state["rehearse"] = "pass" if result.ok else f"fail ({result.error or result.why_not})"
      else:
        planned = plan(checked)
        state["plan"] = "pass" if planned.ok else "fail"
        state["plan_problems"] = [str(problem) for problem in planned.problems]
        if planned.ok:
          rehearsal = asyncio.run(rehearse_plan(planned))
          state["rehearse"] = "pass" if rehearsal.ok else f"fail ({len(rehearsal.collisions)} collisions)"
    except RunRefused as refused:  # PyLabRobot's own checks said no: a clean failure
      state["rehearse"] = f"fail ({refused})"
    except Exception as error:  # a crash here is a steadyhand bug, and worth recording as one
      state["rehearse"] = f"crash ({type(error).__name__}: {error})"
    state["notes"] = list(checked.protocol.notes)
    print(f"FINISHED: draft passed in round {number}; plan {state['plan']}; rehearse {state['rehearse']}")
    for problem in state.get("plan_problems", []):
      print(f"  plan problem: {problem}")
  else:
    listed = "\n".join(f"- {problem}" for problem in problems)
    same = number > 1 and text.strip() == (folder / f"round_{number - 1}.yaml").read_text(encoding="utf-8").strip()
    state["messages"].append({"role": "user", "content": feedback(problems)})
    if same:  # as in draft(): the same file again hands the problem to a person
      state["done"], state["draft"] = True, "left for a person"
      print(f"FINISHED: the same file was sent again in round {number}; left for a person to decide:\n{listed}")
    elif number >= ROUNDS:
      state["done"], state["draft"] = True, "fail"
      print(f"FINISHED: draft still has problems after {ROUNDS} rounds:\n{listed}")
    else:
      print(f"ROUND {number} HAS PROBLEMS. Run `prompt` again for the next message. They are:\n{listed}")
  (folder / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
  return 0


if __name__ == "__main__":
  sys.exit(main())
