# Intake, measured

All runs are on 13 Nov 2026 with Claude models. The latest is the one that counts: the guide and the
checks changed between runs.

## The same drafts on the Opentrons robots (0.12.0)

No model was asked again. The 28 drafts below that rehearse on the Hamilton were planned as written
for an Opentrons Flex and an OT-2, and each plan that came out was run through Opentrons' simulator
(opentrons 10.1.0 for the Flex, 9.0.0 for the OT-2).

- **4 of 28 plan for both robots, and all 4 pass the simulator on both**: `mtt_assay`, `reagent_add`,
  `serial_dilution`, `vague`.
- **24 are refused at the plan, all for the same reason**: they name PyLabRobot plates with no known
  Opentrons twin. The drafting guide only offers PyLabRobot labware, so this measures the labware gap,
  not the planner. Drafting for an Opentrons robot is not built yet.

## Full run (31 notes), on the code released as 0.10.0

Two Claude Opus 5.5 agents played the model through `evals/step_intake.py`: the 20 kit-protocol notes in
`acceptance/`, the 8 notes in `intake/`, and 3 notes that ask to normalize samples. Nothing the model
wrote was edited by hand.

- **28 of 31 passed draft, check, plan and rehearse at the first attempt.**
- The other 3 are notes that cannot work as written, and each was refused for the right reason:
  - `too_much`: 450 uL into a plate the note names as 360 uL. The model kept the stated volumes and
    flagged the overflow; `check` refused it.
  - `normalize_too_dilute`: one library at 3.1 ng/uL cannot be brought to 4 ng/uL. `check` named the well.
  - `normalize_no_file`: the note asks to normalize but gives no readings file. The draft names a
    samples file and says it is needed; reading it fails because the file is not there.
- In those three the model sent the same file back until the rounds ran out, as the guide told it to.
  Since this run, sending the same file again ends the drafting at once and the output says the problem
  is for a person to settle.

## Earlier runs

| run | notes | first-attempt pass | what it led to |
|---|---|---|---|
| `claude -p`, through `run_intake.py` | 4 | 4 drafted, 2 after a second round | the first proof that a real model can follow the format |
| Opus agents, run 1 | 8 | 7; 1 crashed drybench | unskirted plates refused at plan, `to: waste`, repeated problems folded, fuller guide |
| Opus agents, run 2 | 8 | 8 | small guide fixes |
| Opus agents, acceptance (0.6.0) | 20 | 17; 2 crashed, 1 would not plan | lids assumed off, tip reloads, extra waste reservoirs; see `acceptance/RESULTS.md` |

## What these numbers do and do not show

- A pass means the file runs through every check with no collision and no tip clearly out of the liquid.
  It does not mean the file matches the note. Two drafts were read against their notes by hand and
  matched; the rest were not.
- The agents drive the conversation by hand, one turn at a time, and are told not to read anything else
  in the repository. That is close to a bare API call but not the same thing.
- One model family. Nothing here says how a smaller or a different model does.
- The acceptance notes are our own descriptions of the manuals' pipetting steps, with layouts we chose.
- No robot has run any of these.
