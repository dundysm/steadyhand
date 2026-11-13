# Intake, measured

The tool was called drybench when every run below was made. The prompts a model sees now differ from
those runs only in that one word; no run has been repeated under the new name.

All runs are on 13 Nov 2026 with Claude models. The latest is the one that counts: the guide and the
checks changed between runs.

## Real well shapes on the Hamilton deck, and one worked example corrected (0.21.0)

On a Hamilton deck the three plates and reservoirs that Opentrons also ships now take their inside shape
from Opentrons' definition, so the liquid height in them is exact and a tip above it fails the run.

- **The 28 drafts that passed on the Hamilton were rehearsed again, not drafted again.** 27 still pass.
  The one that no longer does is `pcr_setup`: 180 uL of master mix in a 15 mL reservoir is too shallow
  for the tip, the same finding as on the Flex. Before this it was only reported as possible.
- **`pcr_setup` was drafted again from the start** by one Claude Opus 5.5 agent. Round 1: 180 uL, told
  the well "needs about 230 uL left in it". Round 2: **it passes check, plan and rehearsal** with 400 uL
  of master mix, and a note saying so. (On the Flex run the model chose 2.2 mL; this time it added only
  what the message asked for. One run each, so this is not a measured difference.)
- So on the Hamilton, 28 of 31 notes reach a rehearsed script with no hand edits: 27 at the first
  attempt, 1 at the second. The other 3 cannot work as written.
- **The first message to the model changed by one number**, for all three robots. The guide's second
  worked example left 1 mL in a 195 mL reservoir, which stands 0.84 mm deep: under the tip. On an
  Opentrons deck that example has failed rehearsal since 0.18.0 and no test caught it; it now starts
  with 6 mL, and a test rehearses every worked example on every robot. No note other than `pcr_setup`
  was drafted again with the corrected example.
- The agent that drafted `pcr_setup` reported that the first message does not say whether "enough for
  10 reactions" is a stated amount, and that the guide's rule for a reservoir (2 mL extra) and the
  rehearsal's message point to very different volumes. Both are open.

## The master-mix note once more, with better feedback (0.20.0)

The rehearsal's message to the model now says how much liquid the well needs for a tip to stay under the
surface, and that an amount given only as "enough for N uses" is left open. The first message to the
model is still unchanged. `pcr_setup` on the Flex was run again from the start by one Claude Opus 5.5 agent.

- **Round 1:** the same draft, 180 uL of master mix. It was told the tip draws air and that the well
  "needs about 230 uL left in it".
- **Round 2: it passes check, plan and rehearsal**, on the Flex and, planned again, on the OT-2. The
  model raised the master mix to 2.2 mL and rewrote its note to say so.
- **That is more than the run needs.** The steps use 144 uL; about 375 uL would have passed. The model
  followed the guide's rule for a reservoir (2 mL more than is used). The file runs, but a person has to
  read the notes to see that it asks for twelve times the master mix the note implied.
- With this, 28 of the 31 notes drafted for a Flex reach a rehearsed protocol with no hand edits: 27 at
  the first attempt, 1 at the second. The other 3 cannot work as written.

## Drafting that rehearses: the one draft the replay stopped, asked again (0.19.0)

`draft` now plans and rehearses each file that passes `check` and sends what stops it back to the model.
The first message to the model is unchanged, so the 27 drafts that rehearse clean would come out as before
and were not asked again. The one the replay stopped, `pcr_setup` on the Flex, was run again from the
start by one Claude Opus 5.5 agent through `evals/step_intake.py`.

- **Round 1:** the same draft as before, with 180 uL of master mix in a 15 mL reservoir. This time it
  was told: "in trough/A1 the tip stops up to 0.65 mm above the liquid and draws air".
- **Round 2:** it sent the same file again, which hands the problem to a person. Its reason: the note
  says the master mix is "enough for 10 reactions", which it read as a stated amount it may not change.
- So the result for that note is no longer a protocol that would draw air, but a draft returned with
  the reason. Whether "enough for 10 reactions" should count as a stated amount is a fair question the
  guide does not settle.
- The agent also noted that the labware list gives no well widths, so it could not tell which reservoir
  has narrower wells, which the feedback suggests as one way out.

## The Flex drafts with the liquid height known in every well (0.18.0)

No model was asked again. On an Opentrons deck the height of a volume now comes from the inside shape of
each well, so a tip above the liquid in a tapered well is a failure and no longer a "possibly".

- **27 of the 28 Flex drafts pass the replay on both robots, and none carries a "possibly" note now**
  (12 did at 0.17.0).
- **1 is now stopped at the replay, for a real reason: `pcr_setup`.** Its note says the master mix is
  "enough for 10 reactions" in a 12-column trough, and the draft declares 180 uL there. In that 15 mL
  reservoir 180 uL is under 1 mm deep, below where the tips stop, so all eight aspirates draw air.
  The same draft passes on the Hamilton, where the floor of that reservoir is not known.
- So of the 31 notes, drafted for a Flex: 27 reach a rehearsed protocol with no hand edits, 3 are
  refused at `check` because they cannot work as written, and 1 is stopped at the replay.
- The drafting loop only sends `check` problems back to the model. It was not told about the replay's
  finding, so it had no chance to add more master mix.

## The Flex drafts replayed in the physics scene (0.17.0)

No model was asked again. The 28 Flex drafts that pass `check` were planned for both robots, replayed in
the physics scene on a deck built from Opentrons' labware definitions, and run through Opentrons' simulator.

- **All 28 pass the replay and the simulator on both robots**: no collisions, no tip certainly out of
  the liquid, and PyLabRobot's trackers end with the volumes `check` predicted in every well.
- **12 of the 28 carry a "possibly out of the liquid" note** on each robot. Those are aspirates from
  V- or round-bottom wells, where the liquid height is not known exactly, so they are reported and do
  not fail.
- The replay is not just agreeing with itself: the fault suite for these robots stops 16 of 19 planted
  mistakes (`docs/faults-opentrons-flex.md`).

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
