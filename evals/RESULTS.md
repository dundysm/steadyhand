# Intake, measured

The tool was called drybench when every run below was made. The prompts a model sees now differ from
those runs only in that one word; no run has been repeated under the new name.

All runs are on 13 Nov 2026 with Claude models. The latest is the one that counts: the guide and the
checks changed between runs.

## The Flex drafts planned again once a tight deck makes room (0.16.0)

No model was asked again.

- **All 28 Flex drafts that pass `check` now plan and pass Opentrons' simulator on both robots**, the
  ELISA included.
- **The ELISA needs a person standing by**: 14 tip reloads and 3 stops to empty the waste on the Flex,
  7 and 3 on the OT-2. No other draft pauses.
- So of the 31 notes, 28 now reach a simulated Opentrons protocol with no hand edits; the other 3 cannot
  work as written. The drafts are the ones from the 0.13.0 run; only the planner changed.

## The Flex drafts planned again with 8-channel pipettes (0.15.0)

No model was asked again. The 28 Flex drafts below that pass `check` were planned again once the planner
could use 8-channel pipettes.

- **The same 27 plan and pass Opentrons' simulator on both robots**; `sandwich_elisa` is still refused for
  deck room.
- **24 of the 27 Flex plans use eight channels somewhere** (23 on the OT-2).
- **Commands across the 27 fall from 17,986 to 4,686 on the Flex** and from 18,122 to 5,038 on the OT-2.

## Drafted for an Opentrons Flex (31 notes), on the code released as 0.13.0

Two Claude Opus 5.5 agents played the model through `evals/step_intake.py` with
`STEADYHAND_EVAL_ROBOT=opentrons-flex`, on the same 31 notes as the full run below. The model was offered
Opentrons' labware in place of PyLabRobot's. Nothing it wrote was edited by hand.

- **27 of 31 passed draft, check, plan and Opentrons' simulator at the first attempt.**
- **The same 27 drafts also plan for an OT-2 and pass its simulator** (opentrons 9.0.0), with only the
  robot changed on the command line.
- **3 cannot work as written and were refused for the right reason**, each left for a person in round 2:
  `too_much`, `normalize_too_dilute`, `normalize_no_file`.
- **1 was refused at the plan: `sandwich_elisa`.** The draft passes `check`. Its seven plates and
  reservoirs plus four waste reservoirs fill all 11 slots, so there is none for tips. The same note
  runs on the Hamilton, whose deck is larger. The guide does not tell the model how many slots a robot has.

What this does and does not show:

- A pass means Opentrons' simulator ran the protocol. On these robots nothing checks collisions or
  whether a tip reaches the liquid.
- One draft, `bradford_assay`, was read against its note and matched. The others were not read.
- The agents kept to the two commands. After their first cases both read only the part of each prompt
  that differed from the last, having confirmed the guide was the same.
- Black and white assay plates are not in Opentrons' list; the model used the clear Corning plate.

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
| Opus agents, run 1 | 8 | 7; 1 crashed steadyhand | unskirted plates refused at plan, `to: waste`, repeated problems folded, fuller guide |
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
