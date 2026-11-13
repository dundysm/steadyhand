# What steadyhand stops, and what it does not: Hamilton STARlet

Written by `steadyhand faults`, version 0.19.0. Each row is one mistake planted in a short
dilution that otherwise runs clean. "Stopped at" is the first stage that refused it.

**22 of 24 planted mistakes stopped.** The unchanged protocol ran clean.

| mistake | level | stopped at | what happened |
|---|---|---|---|
| The buffer reservoir is declared with 2 mL; the steps draw 2.4 mL from it. | protocol | check | steps[0]: takes 100 uL from reservoir/A1, which holds 0 uL at that point; and 3 more times after that |
| 300 uL of buffer goes into wells that then take another 100 uL; they hold 360 uL. | protocol | check | steps[1]: fills plate/A2 to 400 uL, over its 360 uL capacity; the same in 23 more wells (B2, C2, ... H4) |
| The dilution moves 0.5 uL, below the 1 uL the file allows by default. | protocol | check | steps[1]: plate/A1 to plate/A2: 0.5 uL is below the smallest volume allowed (1 uL) (and 24 more) |
| The mix draws 250 uL from wells that hold 200 uL. | protocol | check | steps[1]: mixing 250 uL in plate/A2, which holds 200 uL; the same in 23 more wells (B2, C2, ... H4) |
| The transfer names column 13 of a 12-column plate. | protocol | read | steps[0].transfer.to: plate (Cor_96_wellplate_360ul_Fb) has no well H13 |
| A volume is written as a bare number. | protocol | read | steps[0].transfer.volume: expected a volume such as '100 uL', got 100 |
| The plate is named waste, a name the planner keeps for its own waste reservoirs. | protocol | plan | labware.waste: names starting with 'waste' are kept for the planner's waste reservoirs |
| The step that fills the wells with buffer is missing, so the series is not diluted at all. | protocol | check | liquids.buffer: no step draws from, adds to or mixes this liquid; remove it, or fix the step that should use it |
| The series starts in column 2, not column 1 where the sample is. | protocol | check | liquids.sample: no step draws from, adds to or mixes this liquid; remove it, or fix the step that should use it |
| The same tip is carried down each dilution series, so sample carries over. | protocol | **not stopped** | ran clean |
| The plate carrier sits one rail (22.5 mm) to the right of where the plan put it. | deck | rehearse | 168 collisions; first: the tip into plate on descend |
| The plate and the reservoir are on each other's carrier sites. | deck | rehearse | 24 collisions; first: the tip into plate on descend |
| A 384-well plate is on the deck where the plan expects the 96-well plate. | deck | rehearse | 528 collisions; first: the tip into plate on descend |
| A 2 mL deep-well plate is on the deck where the plan expects the shallow plate. | deck | **not stopped** | ran clean |
| The plate still has its lid on. | deck | run | PyLabRobot refused command 3 (dispense at plate): Cannot dispense to 'plate_well_A2': its enclosing resource 'plate' has a lid. Remove the lid first. |
| The first column of the tip rack is empty. | deck | run | PyLabRobot refused command 1 (pick_up at tips_300_1): Tip spot does not have a tip. |
| 1000 uL tips are in the rack where the plan expects 300 uL tips; they are 35 mm longer. | deck | rehearse | 416 collisions; first: the tip into plate_carrier_1 on descend |
| 50 uL tips are in the rack where the plan expects 300 uL tips; they are 9.5 mm shorter. | deck | rehearse | 80 tips out of the liquid; first: step 72 (aspirate, channel 0) in plate_well_A1: the tip stops 4.31 mm above the liquid, so it draws air |
| Every move into the plate is 4.5 mm to the right, over the wall between wells. | motion | rehearse | 176 collisions; first: the tip into plate on descend |
| Every aspirate stops 4 mm lower than planned, 3 mm under the well floor. | motion | rehearse | 104 collisions; first: the tip into reservoir on descend |
| Channels travel 5 mm below the top of the plate instead of well above the deck. | motion | rehearse | 1054 collisions; first: the tip into reservoir on travel |
| Every aspirate from the plate stops 9 mm above the well floor, in air. | motion | rehearse | 80 tips out of the liquid; first: step 72 (aspirate, channel 0) in plate_well_A1: the tip stops 2.81 mm above the liquid, so it draws air |
| Every dispense is released 30 mm above the well, so it would splash. | motion | rehearse | 104 tips out of the liquid; first: step 16 (dispense, channel 0) in plate_well_A2: the tip is 20.83 mm above the rim of the well |
| Two channels are 4 mm apart in the reservoir; the head cannot bring them closer than 9 mm. | motion | rehearse | 3 collisions; first: the channel into channel 0 on descend |

Stages: `read` (the file is not a valid protocol), `check` (the liquid ledger), `plan` (tips, channels,
deck), `run` (PyLabRobot's own tip and volume trackers refused a command), `rehearse` (a collision in
the physics scene, or a tip out of the liquid).

A mistake that is not stopped runs to the end with every stage passing. Those rows are the checks
steadyhand does not have yet.
