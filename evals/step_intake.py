"""Run the `steadyhand draft` conversation one turn at a time, for a model that is driven by hand or by an agent.

  python evals/step_intake.py prompt CASE          print what the model is sent next
  python evals/step_intake.py submit CASE REPLY    hand in the model's reply (a file); it is checked as draft checks it

Set STEADYHAND_EVAL_ROBOT to draft for another robot, such as opentrons-flex. As in
`steadyhand draft`, a file that passes the check is planned and rehearsed for that robot, and what
stops it is sent back to the model like any other problem.

The messages, the checking and the limit of three rounds are the ones `steadyhand.intake.draft` uses.
State is kept in evals/out/agents/CASE/, or evals/out/agents-ROBOT/CASE/ for a named robot.
"""

import json
import os
import sys
from pathlib import Path

from steadyhand.intake import _problems_of, extract_yaml, feedback, messages_for, rehearsal_problems

HERE = Path(__file__).parent
ROUNDS = 3
ROBOT = os.environ.get("STEADYHAND_EVAL_ROBOT", "")


def state_of(case: str):
  folder = HERE / "out" / (f"agents-{ROBOT}" if ROBOT else "agents") / case
  folder.mkdir(parents=True, exist_ok=True)
  path = folder / "state.json"
  if path.exists():
    return folder, json.loads(path.read_text(encoding="utf-8"))
  # a case is a note in evals/intake or evals/acceptance, or manual pages fetched by evals/heldout/fetch.py
  places = (HERE / "intake", HERE / "acceptance", HERE / "out" / "heldout", HERE / "out" / "heldout2")
  note = next(path for path in (place / f"{case}.txt" for place in places) if path.exists())
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
    # as draft(rehearse=True) does: a file that passes the check is planned and rehearsed, and what
    # stops it goes back to the model like any other problem
    state["notes"] = list(checked.protocol.notes)
    try:
      problems = rehearsal_problems(checked, ROBOT)
      state["history"][-1] = [str(problem) for problem in problems]
    except Exception as error:  # a crash here is a steadyhand bug, and worth recording as one
      state["done"], state["draft"], state["rehearse"] = True, "pass", f"crash ({type(error).__name__}: {error})"
      print(f"FINISHED: draft passed in round {number}; rehearse {state['rehearse']}")
      problems = []
  if not problems and not state["done"]:
    state["done"], state["draft"], state["plan"], state["rehearse"] = True, "pass", "pass", "pass"
    print(f"FINISHED: draft passed in round {number}; plan pass; rehearse pass")
  elif state["done"]:
    pass
  else:
    listed = "\n".join(f"- {problem}" for problem in problems)
    same = number > 1 and text.strip() == (folder / f"round_{number - 1}.yaml").read_text(encoding="utf-8").strip()
    needs = all(getattr(problem, "where", "") == "needs" for problem in problems)
    state["messages"].append({"role": "user", "content": feedback(problems)})
    if same or needs:  # as in draft(): the same file again, or a file that says what it needs, goes to a person
      state["done"], state["draft"] = True, "left for a person"
      why = "the file names what it cannot do without" if needs else "the same file was sent again"
      print(f"FINISHED: {why} in round {number}; left for a person to decide:\n{listed}")
    elif number >= ROUNDS:
      state["done"], state["draft"] = True, "fail"
      print(f"FINISHED: draft still has problems after {ROUNDS} rounds:\n{listed}")
    else:
      print(f"ROUND {number} HAS PROBLEMS. Run `prompt` again for the next message. They are:\n{listed}")
  (folder / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
  return 0


if __name__ == "__main__":
  sys.exit(main())
