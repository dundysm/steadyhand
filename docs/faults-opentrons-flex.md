# What steadyhand stops, and what it does not: Opentrons Flex

Written by `steadyhand faults`, version 0.26.0. Each row is one mistake planted in a short
dilution that otherwise runs clean. "Stopped at" is the first stage that refused it.

**18 of 21 planted mistakes stopped.** The unchanged protocol ran clean.

| mistake | level | stopped at | what happened |
|---|---|---|---|
| The buffer reservoir is declared with 2 mL; the steps draw 2.4 mL from it. | protocol | check | steps[0]: takes 100 uL from reservoir/A1, which holds 0 uL at that point; and 3 more times after that |
| 300 uL of buffer goes into wells that then take another 100 uL; they hold 360 uL. | protocol | check | steps[1]: fills plate/A2 to 400 uL, over its 360 uL capacity; the same in 23 more wells (B2, C2, ... H4) |
| The transfer names column 13 of a 12-column plate. | protocol | read | steps[0].transfer.to: plate (Cor_96_wellplate_360ul_Fb) has no well H13 |
| The file allows 0.5 uL moves and the dilution asks for one; no pipette on the Opentrons Flex moves less than 1 uL. | protocol | plan | steps[1]: 0.5 uL is less than any pipette on the Opentrons Flex moves (1 uL) (and 31 more) |
| Ten more plates are declared; with tips they need more slots than the Opentrons Flex has. | protocol | plan | labware: 13 plates and reservoirs and 1 kinds of tip need 14 slots; the Opentrons Flex has 11 for labware |
| The sample wells hold 25 uL in a flat-bottom plate: under 1 mm of liquid, below where the tip stops. | protocol | rehearse | 8 tips out of the liquid; first: step 72 (aspirate, channel 0) in plate_well_A1: the tip stops 0.22 mm above the liquid, so it draws air |
| The sample wells hold 110 uL and the series takes 100 uL: the last of each draw is under the tip, so it is air. | protocol | rehearse | 8 tips out of the liquid; first: step 72 (aspirate, channel 0) in plate_well_A1: the liquid falls 0.68 mm below the tip before the aspirate ends, so about 21.9 uL of what it delivers is air |
| The buffer is topped up into wells that now hold sample, with one reused tip: it goes back into the reservoir carrying sample. | protocol | check | steps[2]: a reused tip goes back into reservoir/A1 after it has been in plate/A1, which held sample; it carries that into reservoir/A1. Use tips: fresh for this step, or do it while those wells are still empty |
| The same tip is carried down each dilution series, so sample carries over. | protocol | **not stopped** | ran clean |
| The plate and the reservoir are in each other's slots. | deck | rehearse | 24 collisions; first: the tip into plate on descend |
| The plate sits 4.5 mm towards the back of its slot, half a well off. | deck | rehearse | 176 collisions; first: the tip into plate on descend |
| A 384-well plate is on the deck where the plan expects the 96-well plate. | deck | rehearse | 352 collisions; first: the tip into plate on descend |
| A 2 mL deep-well plate is on the deck where the plan expects the shallow plate. | deck | **not stopped** | ran clean |
| A 200 uL PCR plate is on the deck where the plan expects the flat-bottom plate. | deck | **not stopped** | ran clean |
| The first column of the tip rack is empty. | deck | run | action 1 (pick_up at tips_200x8_1/A1): Tip spot does not have a tip. |
| 1000 uL tips are in the rack where the plan expects 200 uL tips. | deck | rehearse | 416 collisions; first: the tip into deck on descend |
| Every move into the plate is 4.5 mm to the right, over the wall between wells. | motion | rehearse | 176 collisions; first: the tip into plate on descend |
| Every aspirate stops 4 mm lower than planned, 3 mm under the well floor. | motion | rehearse | 104 collisions; first: the tip into reservoir on descend |
| The pipette travels 5 mm below the top of the plate instead of above everything on the deck. | motion | rehearse | 1157 collisions; first: the channel into tips_200x8_1 on descend |
| Every aspirate from the plate stops 9 mm above the well floor, in air. | motion | rehearse | 80 tips out of the liquid; first: step 72 (aspirate, channel 0) in plate_well_A1: the tip stops 2.96 mm above the liquid, so it draws air |
| Every dispense is released 30 mm above the well, so it would splash. | motion | rehearse | 104 tips out of the liquid; first: step 16 (dispense, channel 0) in plate_well_A2: the tip is 20.33 mm above the rim of the well |

Stages: `read` (the file is not a valid protocol), `check` (the liquid ledger), `plan` (tips, channels,
deck), `run` (PyLabRobot's own tip and volume trackers refused a command), `rehearse` (a collision in
the physics scene, or a tip out of the liquid).

A mistake that is not stopped runs to the end with every stage passing. Those rows are the checks
steadyhand does not have yet.
