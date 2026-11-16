# Changelog

Releases since 0.26.0, newest first, as their release notes were written. Earlier versions are in the
commit log, and the measurements behind every claim are in [evals/RESULTS.md](evals/RESULTS.md).

## 0.44.0 (2026-11-16)

**who makes what in a kit manual**

the guide now says who makes a kit's reagents; tested on an eighteenth set from outside: eight manuals from five makers (promega, thermo fisher, cell biolabs, biovision, sciencell), each drafted five ways by five agents at once

- result: 38 of 40 drafts reach a rehearsed protocol, 37 at the first attempt, and the 38 do the manual's assay; 2 were handed back to a person (a 100-assay kit asked to fill 162 wells)
- guide: what the reagent preparation makes is a person's, before the run; standards, sample dilutions and what the numbered steps make are the robot's
- guide, after the write-up: a mix a numbered step makes is the robot's also when the text wants it fresh; a kit's contents list is not what stands on the deck, and a run that needs more than one kit says how many; wells asked for only under a condition are left out; a sample range made up to a total is half the total; an amount too small to pipette is diluted on the deck first
- after the fixes, the five manuals they touched were drafted again all five ways (not an outside test): 25 of 25 pass at the first attempt
- my mistake in this set: two sheets were registered with one page of two; the ten drafts from the cut text are void and were redone from the whole text
- totals: 232 of 267 drafts from 108 manuals stand as rehearsed programs with no hand edits; 218 tests
- caveats: five agents agreeing is one reading of one text, not five tests; nobody who has run these kits has read the drafts; details in evals/RESULTS.md

## 0.43.0 (2026-11-16)

**eight manuals drafted five ways**

the widest test so far: eight kit manuals of different kinds, each drafted for the Flex, the OT-2 and the Hamilton with nothing decided, and for the Hamilton and the Flex with 24 samples in triplicate; forty drafts, by five agents at once

- result: all 40 reach a rehearsed protocol, 34 at the first attempt; 31 do the manual's assay; 9 did only its first half, because a rule of the guide cut two assays in two
- guide: alternatives (plate reader or flow cytometry) take the first; stages of one assay (a reaction and the ELISA that reads it) are written in full; culture over days happens before the run; a timed incubation at 37 C is a pause, however short
- guide: how much a deck holds (19 plates and troughs on the Hamilton, 9 on an Opentrons deck, each checked against its planner); when the samples need more, the file is written for as many whole plates as fit and says how many runs that makes
- check: a step that empties a range passes over wells that hold nothing, as long as another well of the step holds some; that one case cost six second rounds
- after the fixes, the three kits they touched were drafted again all five ways (not an outside test): 15 of 15 pass at the first attempt, and all write the whole assay
- totals: 194 of 227 drafts from 100 manuals stand as rehearsed programs with no hand edits; 217 tests
- caveats: one maker; five agents agreeing is one reading of one text, not five tests; nobody who has run these kits has read the drafts; details in evals/RESULTS.md

## 0.42.0 (2026-11-16)

**one step over several ranges or plates**

wherever a protocol asks for wells it now takes a list of wells and ranges, in the order written: `[plate_1/A1:D6, plate_2/A1:D2]`; a wash of three plates is one step, and 8 wells of a 12-well plate are one line

- format: lists of wells for liquids, transfers and mixes; no well twice in a list; a dilution series still starts from one range
- examples: `cell_staining.yaml`, fixing and staining cells on two 24-well plates; plans for all three robots
- intake: a rehearsal problem names the step of the file it is about, and for liquid that is thrown away it offers a lower draw height; the Hamilton's deck refusal says when the plates alone fill the deck
- measured on a sixteenth set (four staining kits from ScienCell, Cosmo Bio and Wako): 4 of 8 drafts reach a rehearsed protocol (Flex 3 of 4, Hamilton 1 of 4); every draft that needed a list wrote one step over it
- the four handed back: two because 72 wells on 6- and 24-well plates do not fit a STARlet deck (my test sentence, not the format), two because a 1 mm layer of stain could not be taken off from the surface and the feedback did not say how; with the new feedback that kit passes on both robots in the second round
- totals: 154 of 187 drafts from 92 manuals stand as rehearsed programs with no hand edits; 215 tests
- details and caveats in evals/RESULTS.md

## 0.41.0 (2026-11-15)

**defaults for small plates, measured on five staining kits**

the guide's defaults were written for 96 wells; three of them now cover plates with fewer than eight rows, and a fifteenth set tests them on kits from five makers

- guide: 8 samples go from A1 down each column in turn, or as many as the plate holds; a choice the text leaves between two ("in duplicate or triplicate") takes the first; liquid already in a well is what the text gives per well, else 500 uL, 1 mL or 2 mL by plate size; a volume worked out from a ratio is listed under `chose`
- measured on a fifteenth set (senescence and Oil Red O staining kits from Cayman, BioVision, Cell Biolabs, Abcam and Cosmo Bio, on 6-, 12- and 24-well plates): 7 of 10 drafts reach a rehearsed protocol on the Flex and the Hamilton, 5 at the first attempt; 3 were handed back to a person
- one of those three and both second rounds were the guide's, and are fixed: how much a text says to make or have ready ("prepare 3 ml per well") is not the amount on the deck, and a pause is under 200 characters; the two Flex drafts pass at the first attempt when done again
- totals: 150 of 179 drafts from 88 manuals stand as rehearsed programs with no hand edits; 209 tests
- caveats: staining kits are one kind of protocol; 8 wells on a 12-well plate are two ranges, so every step is written twice (next); details in evals/RESULTS.md

## 0.40.0 (2026-11-15)

**small plates on an Opentrons deck**

6-, 12-, 24- and 48-well plates can now stand on a Flex or an OT-2; they were left out because Opentrons marks their spacing as irregular, but they are pipetted one well at a time, where spacing does not matter

- opentrons: five plates with fewer than eight rows are on the list (51 plates and reservoirs now)
- the four corning costar plates are the same product as the Hamilton's, so one file that names them plans for all three robots; a test compares every well
- measured on a fourteenth set of one (oxidized LDL uptake, microscopy protocol on a 24-well plate): passes at the first attempt on the Flex, the OT-2 and the Hamilton; the apoptosis kit drafted again for the Opentrons robots now uses a 24-well plate, not a 96-well one
- totals: 143 of 169 drafts from 83 manuals stand as rehearsed programs with no hand edits; 208 tests
- caveat: one manual; 6-, 12- and 48-well plates were only run from a hand-written file; details in evals/RESULTS.md

## 0.39.0 (2026-11-15)

**take all of it**

a transfer to waste can now say `volume: all`; steadyhand works out what each well holds when the step comes, so nobody (and no model) does the arithmetic for a removal; a well that holds nothing by then is reported with the step named

- format: `volume: all` on a transfer `to: waste`; refused for liquid that is moved on
- guide: removals are written with it; drawn from the surface over cells or a pellet, else from 0.5 mm
- measured on a thirteenth set (4 cayman manuals that empty wells again and again): 8 of 8 drafts reach a rehearsed protocol at the first attempt on the Flex and the Hamilton; all 46 removals use `volume: all`
- totals: 140 of 166 drafts from 82 manuals stand as rehearsed programs with no hand edits
- caveat: `all` is what the model of the well holds, not a sensed level; 4 manuals from one maker; details in evals/RESULTS.md

## 0.38.0 (2026-11-15)

**drafting for the OT-2's two pipettes, and cells put in a new medium**

the OT-2 guide now says the robot holds two pipettes, with ranges taken from the planner's own table, so a draft keeps its mixes within what two can do; a file that still needs three is told which step ties it to each; cells put "in" a new medium have the old one taken off first, also where the text does not say so; measured on seven fresh manuals: on the first five, nine of ten drafts rehearse (Hamilton 5 of 5, OT-2 4 of 5); the tenth was refused three times because the first version of the pipette note gave a wrong range; with that corrected, two more fresh manuals and both redone ones pass at the first attempt; details in evals/RESULTS.md

## 0.37.1 (2026-11-15)

**a removal split into small draws is judged like one draw**

on the OT-2 a single well is emptied by the 20 uL pipette in parts; the last part found the liquid already below the tip and failed as drawing air, where one draw of the same amount is only noted as leaving a little behind; both are noted now; found by carrying a Flex draft from the tenth set over to the OT-2

## 0.37.0 (2026-11-15)

**five assays on cells, read against their manuals**

the rule behind the two wrong passes of the last set (wells the text empties are not treated as empty) is in this release, and was tried on a tenth set: five fresh manuals, all assays on cells in a plate; ten of ten drafts rehearse, eight at the first attempt; nine do what the manual asks; one adds a glucose-free treatment on top of the old medium, where the text only implies taking it off, and says so; also found: on the OT-2 a removal split into 20 uL draws fails where the same removal in one draw is only noted; details in evals/RESULTS.md

## 0.36.0 (2026-11-15)

**the rules the drafting kept tripping on, said once each**

shaking and timed mixing are one rule now: a short shake is a pipette mix, also as the last step, and a long one is an incubation; a liquid no trough holds is split into named parts; every time on the magnet gets its wait, and a draw that empties a well goes down to 0.5 mm; a premix you make yourself is not made by the robot; warming to room temperature happens before the run; measured on a ninth set of five fresh manuals: ten of ten drafts rehearse at the first attempt, eight match their pages, and two add to wells the manual says to empty first (they say so in their notes; that rule is next); details in evals/RESULTS.md

## 0.35.0 (2026-11-15)

**a new front page, colour in the terminal, and the first 31 notes drafted again**

the readme is now a front page: a logo, an animation of a rehearsal, a picture of the pipeline, what each robot gets and what was measured; the long sections moved to their own pages under docs; `check`, `plan` and `rehearse` colour their verdicts in a terminal (not in pipes, and NO_COLOR turns it off); a changelog, a contributing guide and issue forms; the 31 notes the guide was first tuned on were drafted again after eight sets of changes: 28 of 31 reach a rehearsed program on both robots, as at 0.26; details in evals/RESULTS.md

## 0.34.0 (2026-11-14)

**glass only where plastic will not do, and a text that cannot work is handed back**

six drafting rules made plainer after the seventh set: glass tubes named for a dilution in buffer become a plate with a note; a large volume is mixed once per mix volume, up to 10 times; controls the text recommends are included; a larger plate is never chosen to make a manual's volumes fit, so a misprinted step goes back to a person; cells seeded before the assay day start on the plate; measured on an eighth set of five fresh manuals: ten of ten drafts stand at the first attempt and match their pages; details in evals/RESULTS.md

## 0.33.0 (2026-11-14)

**five drafting rules from reading the drafts against their manuals**

the sixth set's twelve drafts were read step by step against their manual pages; every volume and well matched, and five rules came out of it: a reagent made just before use gets a `pause` before its first use; a file never ends on a wait; 20 to 25 C is room temperature; blanks and controls go on a second plate instead of being dropped; a solvent that can drip gets a note; measured on a seventh set of five fresh manuals: nine of ten drafts stand at the first attempt, one is handed back over glass tubes; details in evals/RESULTS.md

## 0.32.0 (2026-11-14)

**a draft lists what it decided, and --decide lets you settle it first**

a draft now lists what the text left open and it decided under `chose`, apart from `notes`; the guide fixes defaults for what manuals always leave open (8 samples in column 1, the first complete protocol, optional steps out); `draft --decide "24 samples; include the DNase step"` sends your own decisions; measured on six fresh manuals, details in evals/RESULTS.md

## 0.31.0 (2026-11-14)

**the flex gripper carries the plate to the magnet**

`--gripper` on plan, rehearse and emit: on an opentrons flex the gripper carries the plate onto the magnetic block and back; opentrons' simulator checks the moves; the gripper's own path is not rehearsed; guide: on a magnet the liquid is taken from the bottom, all of it

## 0.30.2 (2026-11-14)

**a magnet on all three robots, and plate capacities corrected**

a magnet step on the flex (magnetic block) and the hamilton (magnet adapter), the plate carried by hand; the rehearsal follows the plate and what it holds; fix: a plate holds no more than the volume in its name, pylabrobot overstated fifteen on the hamilton list; details and corrected numbers in evals/RESULTS.md

## 0.29.0 (2026-11-14)

**a magnet on the OT-2**

a `magnet` step; on the OT-2 the plate stands on a magnetic module and bead cleanups can be planned and rehearsed; the hamilton and the flex refuse the step for now; five bead-kit manuals drafted for the OT-2 all pass; nothing has run on a real magnet; details in evals/RESULTS.md

## 0.28.2 (2026-11-14)

**three faults found by a fourth outside set**

fixes; a crash on plates whose stated capacity is wrong, a run failed for a trace of air, split transfers that did not add up; details in evals/RESULTS.md

## 0.28.0 (2026-11-14)

**refusing what cannot work**

a protocol can now say what it cannot do without, and be refused for it;

- `needs`: a list of what a protocol cannot work without and no robot here gives (a magnet under the plate, a filter plate drained by a spin, glass); `check` refuses the file with that reason, and `draft` hands it to a person at once
- drafting guide: a step that does not happen on the deck (heat, cold, a spin, a read) is a `pause` that names the temperature and the time, not a wait; a vortex mix of a liquid that is then drawn from becomes a pipette mix
- why: in the second outside test every serious fault passed rehearsal; a bead cleanup with no magnet, an hour at 95 C written as a wait
- measured on a third set of 11 manuals: the bead kit is refused on both robots for the magnet it needs; the other 20 drafts pass at the first attempt
- over three outside sets, 35 manuals: 68 of 72 drafts reach a rehearsed program, 59 at the first attempt
- still yours to check in a draft: the layout and sample count, what the notes say was left out, a draw over a pellet; details in evals/RESULTS.md

## 0.27.0 (2026-11-14)

**a pause step, tips that reach, two outside tests**

a pause step, tips that reach, and two tests from outside;

- `pause`: the run stops for a person to do one thing by hand (spin, freeze and thaw, read) and goes on when they say; hamilton, flex and OT-2
- hamilton planner: when the tip the volume asks for cannot reach the floor of a narrow deep well, the plan takes the next one up and says so
- a labware name wrong only in its capital letters gets the right one named
- drafting guide: a dilution the robot makes and then draws from is mixed; a mix is never more than a tip holds
- measured on 25 protocols from manufacturers' manuals the guide had never seen: 48 of 50 drafts reach a rehearsed program, 39 at the first attempt
- what that does not mean: heat, cold, magnets, spin filters and solvent-safe plates are not checked; read a draft's notes before trusting it; details in evals/RESULTS.md

## 0.26.1 (2026-11-14)

**steadyhand 0.26.1**

first release on PyPI: `pip install steadyhand`, then `steadyhand demo`

steadyhand turns a written lab protocol into a robot program and rehearses it in simulation; three robots so far: Hamilton STARlet, Opentrons Flex, Opentrons OT-2

pre-alpha; everything is measured in simulation and nothing has run on a real robot yet; what it stops and what it misses is in the README and in docs/faults.md

0.26.0 was tagged but never reached PyPI: a link label in the package metadata had a comma and the upload was refused; this release fixes that and changes nothing else

## 0.26.0 (2026-11-14)

**steadyhand 0.26.0**

tagged but never published to PyPI: a link label in the package metadata had a comma and the upload was refused; use 0.26.1, which fixes that and changes nothing else: `pip install steadyhand`
