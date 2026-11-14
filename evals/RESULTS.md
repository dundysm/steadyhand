# Intake, measured

The tool was called drybench when every run below was made. The prompts a model sees now differ from
those runs only in that one word; no run has been repeated under the new name.

All runs are on 13 Nov 2026 with Claude models. The first five sections are the only tests on text the guide
was not tuned on. Of the rest, the latest is the one that counts: the guide and the checks changed
between runs.

## Five bead kits, with a magnet (0.29.0)

Until 0.29.0 a bead cleanup was refused: nothing here had a magnet. 0.29.0 adds a `magnet` step
(`- magnet: {plate: beads, state: on}`). On the Opentrons OT-2 the plate stands on a Magnetic Module
GEN2 for the whole run, the rehearsal has it 82.25 mm up on the module, and the protocol that is
written calls `engage` and `disengage`, which Opentrons' simulator checks. The Hamilton and the Flex
refuse the step at plan: there the plate would have to be carried onto the magnet. The guide tells
the model to write magnet steps for a bead cleanup and never a wait in their place. Committed before
any of these manuals was read by a model.

**The set.** `MANUALS_5` in [evals/heldout/fetch.py](heldout/fetch.py): Roche KAPA Pure Beads
(cleanup) and four Zymo kits (Direct-zol-96 MagBead RNA, Quick-RNA MagBead, Quick-DNA/RNA Viral
MagBead, ZymoBIOMICS 96 MagBead DNA). Two Claude Opus 5.5 agents: one drafting for the OT-2, one
for the Flex.

| | OT-2 | Flex |
|---|---|---|
| Reach a rehearsed protocol, no hand edits | 5 of 5 | 0 |
| at the first attempt | 3 | |
| at the second | 2 | |
| Refused: no magnet on this robot | | 5 of 5 |

- **On the OT-2 all five pass** the physics replay with the plate on the module and Opentrons'
  simulator, run again here on the accepted files. The magnet goes on twice in the KAPA cleanup and
  six times in each Zymo kit.
- What sent two drafts back: mixing the bead reagent in its trough left the next draw short
  (`quickrna_magbead`), and a 10 uL bead volume beside larger ones needed a third pipette
  (`viral_magbead`). Both passed at the second attempt.
- **On the Flex all five are refused** with "steadyhand has no magnet for the Opentrons Flex yet",
  four in round 1. The fifth first put a second plate on the magnet, as its manual moves the beads
  to a new plate; a run has one magnet, and it used fresh wells of the same plate instead.

**Read against the manuals.** Every draft was traced step by step with the state of the magnet. In
all five, on the OT-2: liquid is taken off the beads only while the magnet is on; beads are
resuspended only while it is off; the eluate is drawn with the magnet on. No draft has a wait where
a magnet should be. The KAPA draft was compared line by line with its page and follows steps 1.2 to
1.17: beads at 3X, 10 min, magnet, two 80% ethanol washes on the magnet, dry, off the magnet, elute,
magnet, transfer.

**What this does not show.**
- That beads behave. The rehearsal knows where the liquid is, not where the beads are: whether
  2 min clears the liquid, whether a tip 1 mm above the floor takes beads with it, whether the
  ring of beads sits where this magnet height puts it. That needs a robot.
- The optional DNase steps were left out of the three kits that offer them, and noted.
- Heated elution, heated drying and steps before the first pipetting step (bead beating) were
  written as a wait, an air-dry or left out, each noted. The guide does not say which of two
  offered alternatives to take.
- Five kits, one run each, four of them from one maker, one agent per robot. The Hamilton was not
  drafted for; it refuses the step the same way.
- As far as the stored runs show, this is the first time drafts were written for the OT-2 directly;
  before, Flex drafts were re-planned for it. Its two-pipette limit is not in the guide: the model
  met it as a plan problem.

## A fourth, small set: spin plates and heat in mid-run (0.28.1)

The third set (next section) left two rules untested, because of the pages chosen and because its
heated steps all came last. This set of six is aimed at them: two Zymo spin-plate kits with their
purification pages (Quick-RNA 96, Quick-DNA Fungal/Bacterial 96), three Cayman assays with heat or
cold between pipetting steps (glycogen, free fatty acid, an 8-isoprostane ELISA), and a COX activity
assay. `MANUALS_4` in [evals/heldout/fetch.py](heldout/fetch.py). 0.28.1 added one sentence to the
guide (off a pellet, a height where the surface cannot be followed) and was committed first. Two
Claude Opus 5.5 agents, one per robot.

| | Hamilton | Flex |
|---|---|---|
| Reach a rehearsed protocol, first attempt | 3 | 2 |
| Refused for what it needs (a centrifuge to drain a spin plate) | 2 | 2 |
| Handed back to a person for a reason that is not good enough | 0 | 2 |
| Crashed steadyhand | 1 | 0 |

- **Spin-plate kits are refused, on both robots.** All four drafts name the centrifuge that drains
  the filter plate under `needs`. Three stop in round 1. The fourth (`quickrna96_full` on the Flex)
  also got two overflow problems, because the stand-in plate never drains in the ledger; it sent
  the file again and went to a person in round 2.
- **Heat and cold in mid-run are pauses, on both robots.** "Cover the plate, incubate it for 30 min
  at 37 C, then return it uncovered to the deck" in `glycogen` and `ffa`; 18 h at 4 C in the ELISA.
  In the second set the same kind of step was a wait on the deck.
- **A crash.** `cox_activity` on the Hamilton put 300 uL in `Eppendorf_96_wellplate_250ul_Vb`. The
  labware list said that plate holds 585 uL, which is what PyLabRobot states; its own height
  function stops at 262. `check` and `plan` passed and the rehearsal raised an error. Eight
  PyLabRobot plates state more than their height function accepts.
- **Two refusals for a trace of air.** `glycogen` and `ffa` on the Flex have a manual that uses all
  500 uL of a reagent. The last of a well is out of reach, and the rehearsal failed the run for
  0.09 to 1.8 uL of air in a 500 uL draw. The model could do nothing about it and both went to a
  person. On the Hamilton the same drafts pass, because the shape of that plate is not known there.
- The five accepted drafts pass `steadyhand rehearse` on their robots; the two Flex drafts pass
  Opentrons' simulator on the Flex and the OT-2.

**Fixed after this set (0.28.2), and checked on the stored drafts, not by drafting again.**
- A well's capacity is the lesser of what PyLabRobot states and what its height function accepts,
  in `check` and in the labware list, and a height function that refuses a volume no longer stops
  the rehearsal. The stored `cox_activity` draft is now refused at `check` for overfilling, which
  the model would have been sent.
- A draw that empties a well is noted, not failed, when the air is under 1% of the draw: less than
  a pipette can be held to. The first-round `glycogen` and `ffa` Flex drafts now pass on the Flex,
  with the trace of air listed.
- Taking those two to the OT-2 turned up a third fault: a transfer split into equal parts was
  rounded so that three parts of 16.6667 uL made 50.0001, and a well filled to exactly its capacity
  refused the last ten-thousandth. The last part now takes up the rounding, on every robot. Both
  drafts pass the replay and Opentrons' simulator on the OT-2.
- Drafting stops at once when a file names a need, whatever else is wrong with it.

**Caveats.** Six protocols, one run each per robot, one agent per robot. Chosen by the project to
exercise two rules, so not a sample of anything. Read at the level of outcomes and pauses only: the
steps of the five accepted drafts were not compared with their pages line by line. Nothing has run
on a robot.

## A third set from outside: refusing what cannot work (0.28.0)

The second set (next section) showed that the serious faults pass rehearsal. 0.28.0 answers with
`needs`, a list a protocol file can carry of what it cannot work without and no robot here gives (a
magnet under the plate, a filter plate drained by a spin, glass); `check` refuses such a file with
that reason, and drafting hands it to a person at once. The guide now tells the model to use it,
makes a step that does not happen on the deck a `pause` that names the temperature and the time,
turns a vortex mix of a liquid that is then drawn from into a pipette mix, and has smaller rules for
time ranges, quoted notes and fixed volumes in troughs. Committed before any of these 11 manuals was
read by a model; nothing changed until this was written.

**The set.** `MANUALS_3` in [evals/heldout/fetch.py](heldout/fetch.py): seven Cayman kits (glucose,
cholesterol, triglyceride, protein carbonyl, a COX inhibitor screen, a glycolysis cell assay, BCA),
Promega Dual-Glo and Steady-Glo, and two Zymo kits (Quick-DNA HMW MagBead, Quick-RNA 96). Four
Claude Opus 5.5 agents, two per robot, told this time to run no tool on a reply before handing it in.

| | Hamilton | Flex |
|---|---|---|
| Reach a rehearsed protocol, no hand edits | 10 of 11 | 10 of 11 |
| at the first attempt | 10 | 10 |
| Refused in round 1 for what it needs | 1 | 1 |

- No draft was sent back for a second attempt on either robot.
- The 10 Flex drafts pass the physics replay and Opentrons' simulator on the Flex. Nine pass on the
  OT-2; `glucose` is refused at plan there (three pipettes, and an OT-2 holds two). 19 simulator
  runs. The 10 Hamilton drafts pass `steadyhand rehearse`.

**Did the fixes do their work?**
- **The bead kit is refused, for its real reason, on both robots.** `hmw_magbead` came back in round
  1 with "needs a magnet under the plate while the supernatant is taken off the beads", where the
  bead kit of the second set rehearsed clean. None of the other 20 drafts was refused: no false
  alarm in this set.
- **Hand steps are pauses.** `protein_carbonyl` (an hour in the dark, ice, six spins, a spatula) has
  10 pauses on the Hamilton and 8 on the Flex, each saying what to do, with the robot doing every
  addition and every supernatant between them. `dualglo` pauses for the first reading between its
  two reagents; a draft of the first set ran straight through a step like that. `glycolysis` pauses
  for its spin and then draws from the surface.
- **Dilutions are mixed** wherever a stock or standard is made and drawn from (`glucose`,
  `triglyceride`, `cholesterol`, `glycolysis`, the BCA working reagent), on both robots.
- **Not tested by this set:** a heated step in the middle of a run. The 37 C incubations here
  (`glucose`, `bca_cayman`) are the last step before the read, and are left out and noted, as the
  guide says for anything after the last pipetting step. The spin-plate rule is not tested either:
  see the caveats.

**Read against the manuals.** Steps and volumes of all 20 accepted drafts were compared with the
procedure section of their pages, by the project.

- All 20 follow the pipetting of the pages they were given.
- **A pellet drawn from the bottom.** `protein_carbonyl` on the Hamilton discards each supernatant
  from 1 mm above the floor, where the pellet is. `draw_from: surface` is not available in a
  deep-well plate there (its inside shape is not known), and the model did not think to give a
  height instead; the guide does not suggest it. The Flex draft draws from the surface. It passes
  rehearsal on both.
- Layouts, sample counts and which of two offered methods to run are still the model's choice in
  every draft, and are noted.

**What this shows.**
- Over the three outside sets, 68 of 72 drafts reach a rehearsed program, 59 at the first attempt,
  and 2 more are refused for a reason that is true. First attempts were 23 of 28, then 16 of 22,
  then 20 of the 20 not refused; the sets differ, so that is not a trend to lean on.
- The refusal works the one time it was called for. One bead kit is one bead kit.
- What a reader of a passing draft still has to check by hand: the layout and counts, anything
  the notes say was left out, and whether a draw over a pellet stays off it.

**Caveats.**
- **Two of the eleven excerpts were cut short by the pages the project chose.** `quickrna96` stops
  before the spin-plate purification and `cholesterol` stops at "prepare the reaction mix". Both
  drafts end where the text ends and pass. So this set says nothing about spin-plate kits, and
  those two passes are passes on a fragment.
- 11 protocols, one run each per robot, five or six per agent in a row. One agent saved the prompts
  to compare their guide sections.
- The reading is the project's, at the level of steps and volumes.
- Claude Opus 5.5 only. Nothing here has run on a robot.

## A second set from outside, after the fixes: 11 protocols (0.27.0)

The first outside set (next section) was spent once the guide was changed in answer to it. 0.27.0
holds those changes: a `pause` step for what a person does by hand, a tip long enough for a narrow
deep well, a hint for a labware name wrong only in its capital letters, and three guide rules (a
dilution the robot makes and then draws from is mixed; a mix is never more than a tip holds; a
necessary hand step between robot steps is a pause). It was committed before any of these 11 manuals
was read by a model, and nothing was changed until this was written.

**The set.** 11 manuals from four makers, read from the PDFs as before; the list is `MANUALS_2` in
[evals/heldout/fetch.py](heldout/fetch.py). It was chosen to reach past plate assays.

| Case | Manual | Pages |
|---|---|---|
| `oneglo` | Promega ONE-Glo luciferase assay | 4-5 |
| `lipo3000` | Thermo Fisher Lipofectamine 3000 transfection | 1-2 |
| `quickdna96` | Zymo Quick-DNA 96 kit (spin plate) | 6 |
| `magbead_dna` | Zymo Quick-DNA MagBead Plus kit | 8-9 |
| `dna_cleanup96` | Zymo ZR-96 DNA Clean-up kit (spin plate) | 6 |
| `tbars` | Cayman TBARS assay kit | 7-8 |
| `antioxidant` | Cayman antioxidant assay kit | 8-9 |
| `camp_elisa` | Cayman cyclic AMP ELISA kit (competitive) | 9-14 |
| `pge2_elisa` | Cayman prostaglandin E2 ELISA kit (competitive) | 10-13 |
| `lpo` | Cayman lipid hydroperoxide assay kit | 7-8 |
| `gpx` | Cayman glutathione peroxidase assay kit | 7-8 |

Drafted for both robots by four Claude Opus 5.5 agents, two per robot.

| | Hamilton | Flex |
|---|---|---|
| Reach a rehearsed protocol, no hand edits | 10 of 11 | 11 of 11 |
| at the first attempt | 7 | 9 |
| at the second | 3 | 2 |
| Handed back to a person | 1 | 0 |

- The 11 Flex drafts pass the physics replay and Opentrons' simulator on the Flex and, with the robot
  line changed, on the OT-2: 22 simulator runs. The 10 Hamilton drafts pass `steadyhand rehearse`.
- What sent drafts back. Two were the model's own YAML: a note that begins with a quoted phrase, and
  a note with a colon in it. Three were liquid out of reach: both ELISAs on the Hamilton put the
  20 mL of developing reagent the manual fixes in a one-well trough that keeps 1.6 mL from the tip
  (the guide's own trough rule points there), and on the Flex a two-thirds mix of the bead well left
  the next draw short. All five passed at the second attempt.
- `quickdna96` on the Hamilton was handed back. The draft wrote the whole kit; the wells of the
  filter plate overflow, because nothing in the format says that a spin empties them. The model
  sent the same file again and the harness stopped.

**Did the fixes do their work?**
- Dilutions: in the first set five drafts left standards unmixed. Here every stock and standard the
  text says to dilute or prepare is mixed, on both robots (`tbars`, `antioxidant`, both ELISAs,
  `lipo3000`). Where the text says "vortex", the mix is still dropped: the `lpo` standards on both
  robots, the binding mix of `dna_cleanup96` on the Flex.
- `pause`: used once per robot, for the centrifuge in `tbars`, and used correctly; the draw after it
  is from the surface, off the pellet.
- The mix cap was used once (1000 uL in `lpo` on the Hamilton). The longer tip and the capital-letter
  hint were never triggered.

**Read against the manuals.** The spin kits, the bead kit and `tbars` were read in full, both
drafts beside the pages. For the other seven the steps and volumes were checked against the
procedure section and the notes were read. By the project, as before.

- Follow the manual's pipetting on both robots: `oneglo`, `antioxidant`, `gpx`, `tbars`, `lpo`,
  `lipo3000` (scaled up, since it lists 0.15 uL per well), both ELISAs (standards by serial
  dilution, the pipetting table, five rinses, developing reagent, tracer to the total-activity
  wells). The Flex ELISAs are in an ELISA plate this time.
- **A pass that covers a sliver of the protocol.** Three of the four spin-kit drafts stop after the
  first one or two additions and leave every spin, wash and elution to a person. They say so in
  their notes, and they pass. The one draft that wrote the whole kit was refused.
- **Heat and cold become waits on the deck.** 1 h at 95 C (`tbars`), 18 h at 4 C (both ELISAs) and
  2 days at 37 C (`lipo3000`) are written as waits, as the guide tells the model to. Each draft
  says the robot cannot heat or cool. Run as written, none of them does what the manual asks. Two
  of the four agents named this as a clash between the wait rule and the new pause.
- **A bead cleanup with no magnet.** `magbead_dna` follows all 19 steps in liquid terms on both
  robots, with a 2 min wait where the plate should stand on a magnet. There is no magnet. On a real
  robot each "remove the supernatant" would take the beads with it. It rehearses clean. The same
  holds for `ampure_cleanup` in the tuned set.
- **Solvent in plastic.** `lpo` runs in chloroform; the manual asks for glass tubes and a glass
  plate and warns that the solvent dissolves plastic covers. Both drafts use plastic plates, and
  note only that glass is not in the list. Nothing in steadyhand knows what a plate is made of.
- A reagent the manual makes fresh after an 18 h incubation is declared at the start, because the
  format cannot add a liquid in the middle of a run. Both ELISAs note it.

**What this shows.**
- Reaching a program that rehearses held up on a second outside set: 21 of 22, 16 at the first
  attempt. Over both sets, 48 of 50.
- The mixing fix held where it applies. The pause is used where the guide points to it, and not
  where it is needed most: the guide still turns heat, cold and a magnet into a wait.
- The serious failures in this set all pass rehearsal. A program that rehearses is not yet a
  protocol that works: the checks see liquid and collisions, not temperature, magnets, filters or
  materials. The drafts' notes say most of it; a reader has to read them.
- Next, none of it done yet: a timed step that needs heat, cold or a device becomes a pause that
  names the time; a pause that can say which wells a spin empties and which a person fills; "mix
  by vortexing" a liquid that is then drawn from becomes a pipette mix; a bead cleanup is refused,
  or said plainly not to work, until a magnet is supported; the trough rule and the rehearsal's
  hint disagree; time ranges ("10-15 min") have no rule.

**Caveats.**
- 11 protocols, one run each per robot, five or six per agent in a row.
- One Flex agent, after its YAML slip, parsed each later draft itself before handing it in. A
  model inside `steadyhand draft` cannot. No later draft of that agent needed it as far as the
  record shows, but its first-attempt count is not as clean as the others'.
- Two agents saved or compared the guide text across cases; none read another case's manual early.
- The pages and the reading are the project's. Seven of the eleven were read at the level of steps
  and volumes, not line by line.
- Claude Opus 5.5 only. Nothing here has run on a robot.

## The first test from outside: 14 protocols from manufacturers' manuals (0.26.1)

Everything below this section was measured on 31 notes that also guided the guide. This run is on
text the guide had never seen. The guide, the checks and the code were frozen at 0.26.1 before the
first manual was downloaded, and nothing was changed until this was written.

**The set.** 13 manuals from four makers, 14 protocols (one manual is drafted twice, the second time
with its dose-response page). Each PDF is downloaded from its maker and the protocol pages are read
by the same code `steadyhand draft manual.pdf --pages ...` uses: no retyping, no tidying. The pages
were chosen from the manuals' own headings before anything was drafted.
[evals/heldout/fetch.py](heldout/fetch.py) holds the list and rebuilds the text; the makers' text is
not kept here.

| Case | Manual | Pages |
|---|---|---|
| `accugreen` | Biotium AccuGreen High Sensitivity dsDNA quantitation | 1 |
| `ribogreen` | Thermo Fisher Quant-iT RiboGreen RNA assay | 2-5 |
| `cyquant` | Thermo Fisher CyQUANT cell proliferation assay | 4-5 |
| `nanoorange` | Thermo Fisher NanoOrange protein quantitation | 3-4 |
| `brightglo` | Promega Bright-Glo luciferase assay | 5 |
| `adpglo` | Promega ADP-Glo kinase assay | 14-15 |
| `adpglo_ic50` | the same manual, with the IC50 page | 14-15, 17 |
| `celltox` | Promega CellTox Green cytotoxicity assay, endpoint method | 12-13 |
| `gsh` | Cayman glutathione assay kit | 8-10 |
| `sod` | Cayman superoxide dismutase assay kit | 8-10 |
| `catalase` | Cayman catalase assay kit | 7-10 |
| `nitrate` | Cayman nitrate/nitrite colorimetric assay kit | 7-10 |
| `ssiv` | Thermo Fisher SuperScript IV first-strand synthesis | 3 |
| `elisa_il6` | Thermo Fisher human IL-6 ELISA | 13-15 |

Drafted for both robots by four Claude Opus 5.5 agents, two per robot, seven protocols each.

| | Hamilton | Flex |
|---|---|---|
| Reach a rehearsed protocol, no hand edits | 14 of 14 | 13 of 14 |
| at the first attempt | 10 | 13 |
| at the second | 3 | 0 |
| at the third | 1 | 0 |
| Handed back to a person after three attempts | 0 | 1 |

- The 13 Flex drafts pass the physics replay and Opentrons' simulator on the Flex. With the robot
  line changed, 12 of them pass on the OT-2 as well; `nanoorange` is refused at plan there, because
  its volumes need three pipettes and an OT-2 holds two. 25 simulator runs. The 14 Hamilton drafts
  pass `steadyhand rehearse`.
- What sent the four Hamilton drafts back: a labware name typed in the wrong letter case (`ribogreen`,
  `nitrate`); a mix of 11 mL where the largest tip holds 1 mL (`gsh`); tips hitting a deep-well plate
  used for standards, 56 times (`sod`, and `nitrate` on its second attempt). All four were put right
  by the model from the message.
- `ssiv` on the Flex was handed back. The manual moves the whole 7 uL of reaction mix out of its
  well. A tip cannot take the last of a well, and at the lowest height the format allows (0.2 mm)
  about 0.1 uL of the draw would still be air. The model was shown the height hint, new in 0.26.0,
  and used it; it was not enough. On the Hamilton the same protocol passes only because the inside
  shape of that PCR plate is not known there, so the check cannot say.

**Read against the manuals.** A pass means the file runs. All 27 accepted drafts were then read
against their pages by the project, step by step.

- Follow the manual on both robots: `brightglo`, `adpglo`, `adpglo_ic50`, `ribogreen`, `accugreen`,
  `celltox`, `elisa_il6`, and the volumes, tables and order of `gsh`, `sod`, `catalase` and
  `nitrate`. Small differences, each noted in the draft: the Hamilton `accugreen` leaves out the
  vortex mix; the Hamilton `celltox` ends its no-cell column at 150 uL where the others hold 200.
- **Dilutions made without mixing.** On the Flex, `gsh`, `sod`, `catalase` and `nitrate` dilute their
  stocks and standards and do not mix them (one of them 10 uL into 9.99 mL); on the Hamilton
  `nanoorange` does the same with 30 uL into 5.97 mL. The manuals say "dilute" and leave the mixing
  unsaid, and the guide tells the model not to invent steps. Each draft says so in its notes. The
  Hamilton agent added a mix to the same four kits and said so. Run as written, the unmixed
  standards would give a wrong curve. Rehearsal cannot see this.
- **One draft departs from its manual.** `cyquant` on the Flex seeds the cells, waits, takes the
  medium off and lyses in one run. That skips the freeze the manual calls important, and leaves
  34 uL of medium in each well where the manual blots the plate dry. Both are in the draft's notes.
  The Hamilton draft starts from the thawed plate instead: a part of the manual's procedure,
  followed as written.
- `nanoorange`: the Hamilton draft keeps the manual's 2.5 mL assays in a deep-well plate; the Flex
  draft scales to a tenth, which the manual offers for microplates.
- Neither `elisa_il6` draft is planned in an ELISA plate. The kit's 400 uL wash is more than the
  one ELISA plate in the lists holds, and the guide puts size first. The Flex draft says the coated
  strips must be used on the real run.

**What this shows.**
- A model drafting from real manual pages reaches a program that rehearses 27 times in 28. That
  part held up outside the notes it was tuned on. First attempts held up on the Flex (13 of 13
  that passed) and less well on the Hamilton (10 of 14).
- The real gap is not whether the file runs. It is what the manuals leave out: none of the 13 says
  how many samples a run has, so every layout is the model's choice, and most leave mixing unsaid.
- Things to fix, none touched yet: whether a dilution made on the robot is mixed unless the text
  says otherwise; a labware name that is wrong only in its letter case gets no hint; the two-thirds
  mix rule asks for more than a tip holds in a reservoir; the collision in the deep-well standards
  plate on the Hamilton is not yet explained (`catalase` passed with the same plate); a transfer
  that must empty a well cannot pass on the Flex; the lists have no white or black plates, which
  luminescence and fluorescence assays are read in.

**Caveats.**
- 14 protocols, one run each per robot. Each agent drafted seven in a row, so later ones may have
  gained from earlier ones.
- The set leans to plate assays. No bead cleanup: the one manual tried could not be downloaded. One
  ELISA, from the second maker tried; the first refused the download.
- The pages were chosen by the project. A person choosing other pages, or more of them, would get
  other text.
- The reading was done by the project itself, not by an outside reader, and not by someone who has
  run these kits.
- Claude Opus 5.5 only, agents playing the model one turn at a time.
- Nothing here has run on a robot.

## A draw can name its height, and every note drafted again (0.26.0)

- A transfer can give `draw_from` a height above the floor of the well (`0.5 mm`; nothing under
  0.2 mm): lower than the usual 1 mm to take nearly all of a small volume, higher to stay off what has
  settled. It needs no knowledge of the well's shape. The rehearsal's message for a draw that takes air
  now names it as a way out.
- The guide: size comes before the kind of plate; a trough the list gives no amount for counts as
  2 mL; a wait asked for in words includes "until clear"; a mix with no count includes "mix briefly";
  `reuse` into wells that hold another liquid is refused.

All 31 notes were drafted again for both robots by four Claude Opus 5.5 agents.

| | Hamilton | Flex |
|---|---|---|
| Reach a rehearsed protocol, no hand edits | 28 of 31 | 28 of 31 |
| at the first attempt | 28 | 28 |
| Refused, as they should be | 3 | 3 |

- The 28 Flex drafts pass the physics replay and Opentrons' simulator on the Flex and, with the robot
  line changed, on the OT-2: 56 runs. The 28 Hamilton drafts pass `steadyhand rehearse`.
- `ampure_cleanup`, handed back to a person in 0.24.0, passes on both robots: the model gave the
  38 uL eluate transfer `draw_from: 0.5 mm` in its first reply. `kit_manual` on the Hamilton did the
  same for its 20 uL of 22 uL. `ldh_release` uses `draw_from: surface` on both, as before.
- `sandwich_elisa` passes at the first attempt on the Flex again, in a 450 uL plate.
- The ELISA on the Flex pauses 14 times for tips and 3 for waste this time (7 and 3 on the OT-2).
- Read against the notes: every step that differs from the 0.24.0 and 0.25.0 drafts was read. None
  contradicts its note. The models now add a wait they choose where a note says "cool" or "bring to
  room temperature" (10 and 30 minutes), and say so in their notes.

**Caveats.**
- **This is a fit, not a test.** The guide has been changed four times in answer to these same 31
  notes. 28 of 28 at the first attempt says the guide now suits them. It says little about a note
  the guide has not seen.
- One run per note and robot; 15 or 16 notes per agent in one session. One agent printed the prompts
  of its later cases early, to compare their instruction sections, and says it did not read the notes
  in them then.
- No message from the new tip check or the new height hint was ever shown to a model in this run:
  nothing triggered them.
- Still unclear to the agents: whether "cool" or "back on the magnet" is a wait; what to do with a
  liquid too big for one reservoir (they split it, three or five ways); a "PCR plate" in the Hamilton
  list that holds 1240 uL; that emptying a flat well to waste passes although some of it is out of
  reach (it is noted, not failed); that a normalize note with no file gives no column names.

## A reused tip that carries liquid back is refused at check (0.25.0)

The reading under 0.24.0 found one draft that adds reagent with one reused tip to wells already
holding sample. `check` now refuses that: a reused tip may not go back into the well it draws from
after it has been in wells that held another liquid. The first message to the model is unchanged.

- Run over all 167 drafts accepted in the last three runs, the check stops exactly one: that draft.
  The shipped examples pass.
- That note (`pierce_660` on the Flex) was drafted again by one Claude Opus 5.5 agent. It passed at
  the first attempt, this time with fresh tips, so the new message was never shown to a model. The
  Flex count stays 27 of 31, 26 at the first attempt.
- It is a new planted mistake in all three suites: 24 of 26 stopped on the Hamilton, 18 of 21 on each
  Opentrons robot.
- What it does not see: liquids are told apart by the names they are declared under, so two different
  samples under one name are the same to it; a well emptied to nothing counts as clean; and a tip
  carried down a dilution series is not counted, since every well of the series holds the same
  liquids. That last one is still a planted mistake that gets through.

## Drawing near the surface, clearer rules, and every note drafted again (0.24.0)

What changed in the first message, following the reading below:

- A transfer can say `draw_from: surface`: the tip stays 1 mm under where the liquid stands once the
  draw is over. Both planners work the height out from the volume in the well; the replay checks it.
- A time given only in words gets a wait the model chooses and notes; a step that mentions no time
  gets none. The worked example that contradicted this was changed to fit.
- A timed action on something other than the plate ("vortex the reagent 30 s") is left out.
- A mix with no count is 3 times. A plate is chosen by the kind the text asks for. An undescribed
  trough is the one with the least out of reach. Plate colour is not in the list.

All 31 notes were then drafted again for both robots by four Claude Opus 5.5 agents, as in 0.22.0.

| | Hamilton | Flex |
|---|---|---|
| Reach a rehearsed protocol, no hand edits | 28 of 31 | 27 of 31 |
| at the first attempt | 28 | 26 |
| at the second | 0 | 1 (`sandwich_elisa`) |
| Refused, as they should be | 3 | 3 |
| Handed back to a person | 0 | 1 (`ampure_cleanup`) |

- The 27 Flex drafts pass the physics replay and Opentrons' simulator on the Flex and, with the robot
  line changed, on the OT-2: 54 runs. The 28 Hamilton drafts pass `steadyhand rehearse`.
- **The Flex lost a note, and the reason is real.** `ampure_cleanup` moves 38 uL of a 40 uL eluate to a
  fresh plate. In the PCR plate the model chose, 3.1 uL sits under a tip that stops 1 mm above the
  floor, so the last 0.9 uL of the draw is air. That is the check added in 0.23.0. Both amounts are
  stated in the note, so the model could not change them and handed the file to a person, which is
  what the guide asks. In 0.22.0 the same note passed in a wider plate, before that check existed.
  On the Hamilton the same transfer passes only because the shape of that PCR plate is not known there.
  The honest fix is a lower tip for that draw, which the format cannot ask for yet.
- **The ELISA needed a second attempt on the Flex because of a rule added in this version.** "Choose
  one of the kind the text asks for" led the model to the list's ELISA plate, which holds 350 uL; the
  note's 400 uL wash overflows it. It switched to a 450 uL plate after the check said so.
- `ldh_release` now uses `draw_from: surface` on both robots, and it is the only note that does. In
  that plate the tip ends 1.17 mm above the floor instead of 1 mm: taking 50 uL out of 120 uL leaves
  a liquid 2.2 mm deep. The instruction is followed; what it buys in a well that shallow is small.
- `vague` now has the wait on both robots (1 minute, noted). `kit_manual` no longer turns "vortex
  30 s" into a wait.

**Read against the notes.** Every step that differs from the 0.22.0 drafts (12 Hamilton drafts,
13 Flex drafts) was read against its note; the unchanged steps were read in the section below. No
draft contradicts its note. Two things a reader should still know:

- `pierce_660` on the Flex adds the assay reagent with one reused tip to wells that already hold
  sample. The note says nothing about tips. The tip goes back into the reagent between wells, so
  sample is carried into it. Nothing in steadyhand checks what a tip has touched; this is the same
  gap as the planted mistake "one tip down the series", and it is next.
- The Hamilton ELISA draft chose a U-bottom plate so that the wells empty fully. A plate reader
  wants a flat bottom. The guide's remarks about what a tip cannot reach pushed it there.

**Caveats.**
- One run per note and robot; 15 or 16 notes per agent in one session.
- The 31 notes have now been used to change the guide three times. They are a development set, not a
  test of it. A set the guide has never seen is needed, best of all from real manuals.
- What the agents found unclear this time: whether a trough the list gives no out-of-reach amount
  for counts as none or as 2 mL; "whose wells hold the largest volume any well reaches" can be read
  as "the biggest plate"; "until clear" and "mix briefly" are neither times in words nor steps with
  no time; whether the kind of plate or its capacity wins when they clash.

## All 56 accepted drafts read against their notes (after 0.23.0)

A pass says the file runs. To see whether it says what the note says, every draft accepted in the
0.22.0 run (28 for the Hamilton, 28 for the Flex) was read line by line against its note: wells,
volumes, order, times, mixes, tip changes. The reading was done by the same assistant that builds the
tool, with the note and the draft side by side; it is not an independent review, and it does not check
what the planner then does with the file.

**53 of 56 carry every stated step, volume, well and order. 3 depart from the note, in one place each:**

- `ldh_release`, both robots. The note says to take the supernatant from near the top of the liquid so
  the cells are not disturbed. The format has no way to say where in the liquid a tip draws, so the
  program draws 1 mm above the floor of the well, which is where the cells are. Both drafts say in
  their notes that they could not express it; the Hamilton draft adds that it is "left to the robot's
  liquid-class settings", which is not true of the script steadyhand writes.
- `vague`, Hamilton. The note says "wait a bit" between adding and removing the wash. The draft leaves
  the wait out and says so; the Flex draft chose 1 minute. The guide says both: "a step with no time at
  all gets no wait", and a worked example that picks 1 minute for an unstated wash time.

**Where the two robots' drafts differ and the note leaves it open** (none of these contradicts a note):

- A drying time of "a few minutes": 5 minutes on one, 3 on the other.
- "Trough" taken as one well of a 12-well reservoir or as a single-well reservoir, which changes the
  amount supplied (240 uL or 1.6 mL out of reach) but not the steps.
- "Vortex 30 s" kept as a 30 second wait in both, although a wait does not vortex.
- A black or white plate asked for where the Opentrons list has only clear ones: a clear plate, noted.
- "New tips for every column" written as a fresh tip for every well, the stricter choice.
- A mix with no count is 3 times in every draft; a mix with no volume is two thirds of the well.

What follows from it: the format needs a way to draw near the surface, and the guide needs one rule
for a time given only in words.

## A delivered draw that takes air now fails (0.23.0)

The gap named under 0.22.0 is closed. A draw that starts in the liquid and takes it below the tip
fails the rehearsal when that liquid is then delivered to a well or mixed back; thrown away, it is
still only noted. The first message to the model is byte for byte the one 0.22.0 measured, so nothing
was drafted again.

- All 28 accepted drafts on the Hamilton and all 28 on the Flex were rehearsed again under the
  stricter check, and the Flex drafts planned again for the OT-2: every one still passes. None of them
  had such a draw: the 2,016 (Hamilton) and 2,160 (Flex) draws that end below the tip all go to waste.
- On the Hamilton, 48 more such draws are in wells whose shape is not known exactly. They are reported
  as possible and do not fail.
- The check did stop one thing: the project's own `examples/normalization.yaml`, which mixed 25 uL in
  50 uL in a flat well and drew samples down to a few microlitres. On a real robot both would have
  taken air. The example now starts with more sample and mixes less.

## Every note drafted again, with a labware list that says what a tip cannot reach (0.22.0)

Two changes to the first message, then all 31 notes drafted again from the start for the Hamilton and
for the Flex, by four Claude Opus 5.5 agents through `evals/step_intake.py` (two per robot, 15 or 16
notes each).

- **The labware list now says how much liquid is out of a tip's reach** in every well whose inside
  shape is known ("last 240 uL out of reach"): 45 of 46 lines for the Opentrons robots, 26 of 79 for
  the Hamilton. The guide's rule for an unstated volume became: 20% more than the steps use, plus that
  amount. Where the list says nothing, the old allowance stays (10 uL in a plate well, 2 mL in a trough).
- **The guide now says** that an amount given only as enough for some number of uses is not a stated
  volume. This rule was written after `pcr_setup` showed the need, so that note does not test it
  independently.
- The amount quoted is what the rehearsal enforces: the tip stops 1 mm above the floor and has to be
  0.05 mm under the surface. Before this the message after a failed rehearsal quoted the volume at
  1 mm exactly (230 uL where 240 uL is needed). A test now holds the two together on all three robots.

| | Hamilton | Flex |
|---|---|---|
| Reach a rehearsed protocol, no hand edits | 28 of 31 | 28 of 31 |
| at the first attempt | 27 | 28 |
| at the second | 1 (`vague`: the model's first file was not valid YAML) | 0 |
| Refused, as they should be | 3 | 3 |

- The 28 Flex drafts were then run through `steadyhand rehearse` on the Flex and, with the robot line
  changed, on the OT-2: all 56 runs pass the physics replay and Opentrons' simulator.
- `pcr_setup` passed at the first attempt on both robots with 420 uL of master mix (144 uL used,
  plus 20%, plus 240 uL out of reach). In 0.20.0 the same note ended with 2.2 mL on the Flex.
- Two drafts were read line by line against their notes (`pcr_setup` on the Hamilton,
  `griess_nitrite` on the Flex) and matched. All 56 were read later; see the section above.
- The ELISA draft for the Flex now pauses 18 times for tips and 3 times for waste (9 and 3 on the
  OT-2). The draft differs from the last one, so the pauses do too.

**Caveats.**
- One run per note and robot. Each agent drafted its notes one after another in one session, so a
  later note may have gained from an earlier one, although no agent on the Flex was ever sent a
  problem other than the three refusals.
- **The replay does not enforce the "out of reach" amount on a draw that starts in the liquid.** A
  draw that begins with the tip under the surface and takes the well below the tip is noted, not
  failed. That is right for emptying a well to waste and wrong for a transfer whose volume matters:
  a real tip would take air for the last part. One agent noticed that the checker lets through what
  the prompt implies it would stop. Fixed in 0.23.0, above.
- What the agents found unclear in the first message, none of it changed yet: "a few minutes" and
  "wait a bit" are neither a stated time nor no time; "vortex 30 s" falls under both "leave out
  vortexing" and "a timed step becomes a wait"; "room to spare" has no number; a mix with no count;
  "trough" can mean one well or twelve, which changes the amount supplied by a lot; the water for a
  normalize step depends on the file; the column names of a samples file that was not offered; no
  black or white plates in the list.

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
