# Changelog

Releases since 0.26.0, newest first, as their release notes were written. Earlier versions are in the
commit log, and the measurements behind every claim are in [evals/RESULTS.md](evals/RESULTS.md).

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
