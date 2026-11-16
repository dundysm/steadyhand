[steadyhand](../README.md) · [Commands](commands.md) · [Protocol file](protocol-format.md) · [Robots](robots.md) · [Drafting](drafting.md) · [PyLabRobot](pylabrobot.md) · [Limits](limits.md) · [Measurements](../evals/RESULTS.md)

# What it does not do yet

- **A proven intake.** `draft` has been measured only with Claude models, by agents playing the
  model one turn at a time. Eighteen sets from outside, on the protocol pages of 108 manufacturers'
  manuals read straight from the PDFs, each with the guide frozen beforehand and changed only
  after the write-up. Of 267 drafts for the three robots, 232 stand as rehearsed programs with
  no hand edits; 11 are refused for a reason that is true (spin-plate kits, and bead kits
  before there was a magnet); 14 were handed back to a person; 1 was still refused after three rounds, because a note in the OT-2's guide gave a pipette a
  range it does not have (corrected in 0.38.0); 3 passed while adding to wells the manual says, or means, to empty
  first, and said so in their notes; 5 passed by overfilling a plate
  the Hamilton's labware list overstated, fixed in 0.30.1; 1 crashed steadyhand, fixed. Of those that
  stand, 9 in the seventeenth set wrote only the first of an assay's two procedures, by a rule of
  the guide that was changed in 0.43.0.
- **A draft you can run without reading it.** A pass means the file runs, not that it does what
  the manual asks, so the drafts were read against their pages. In the second set every serious
  fault passed rehearsal: heat and cold written as waits on the deck, a bead cleanup with no
  magnet, spin-plate kits cut down to their first step, chloroform in plastic. 0.28.0 answers
  the first three (see `pause` and `needs`), and in the third set the bead kit was refused and
  the hand steps came back as pauses. That is one set. Still yours to check in any draft: the
  `chose` list, about ten things a manual leaves open and the model decided (the number of
  samples, replicates, a dilution, where reagents stand); whatever the `notes` say was left
  out; a draw over a pellet; what the plates are made of. The sets are
  small, were run once and were read by the project itself, not by someone who has run these
  kits. On the 31 notes the guide was first tuned on, 28 reach a rehearsed program on both
  robots at 0.35, as at 0.26, all but one at the first attempt; the other three cannot work as written. All of it, with the manuals and the
  notes, is in [evals](../evals/RESULTS.md).
- **A fully editable plan.** Tips, deck layout and pipetting height can be overridden for the
  whole run. Per-step heights, speeds and liquid classes cannot, and only the two carrier types
  the planner uses are accepted.
- **Washers, shakers and lids.** There is no plate washer, shaker, heater or centrifuge:
  a timed step at room temperature becomes a wait, a step off the deck (heat, cold, a spin, a read) becomes
  a pause for a person, washes are done tip by tip, and a plate that ships with a
  lid is planned with the lid assumed off. When a run needs more tips than fit on the deck, the
  plan stops for a person to swap in full racks; nothing loads them automatically.
- **A magnet, by hand on two of the three robots.** A bead cleanup needs a magnet under the
  plate while the liquid is taken off. A `magnet` step does that. On the Opentrons OT-2 the
  plate stands on a Magnetic Module GEN2 and the step raises and lowers its magnets. On the Flex
  the run stops and a person carries the plate onto a Magnetic Block and back; on the Hamilton,
  onto a magnet adapter on the plate carrier and back. On the Flex, `--gripper` has the Flex Gripper carry it instead (its own path is not
  rehearsed; Opentrons' simulator checks the moves are allowed). The rehearsal
  has the plate at the right height in each place and carries its contents with it, and on the
  Opentrons robots their simulator checks the module and the moves. On the Hamilton no deep-well
  plate fits: on the adapter it stands higher than the channels travel, and the plan says so. Five bead-kit manuals drafted for each robot: all five reach a rehearsed program on the
  OT-2 and the Hamilton and four on the Flex, with the magnet on and off where the manual has it. The
  rehearsal knows where the liquid is, not where the beads are, and no bead protocol has run on
  a real magnet.
- **Filters and solvents.** A spin or filter plate needs a centrifuge or vacuum to drain it;
  some chemistry needs glass. Neither is here. A protocol file can say so under `needs`, and
  `check` then refuses it with that reason. `draft` is told to use it, so such a text comes
  back as "this cannot run here, because", not as a file cut down to what could run.
- **Adapters beyond one.** A PCR plate with no skirt is planned standing in PyLabRobot's
  MicroAmp 96-well base, and the plan says so. That is the only adapter the planner knows; four
  of PyLabRobot's plate definitions need it. Whether your plate really fits that base is yours
  to check.
- **Liquid behaviour.** The liquid-level check assumes the tip stays at one height (no liquid
  following or level detection) and knows the liquid height only in flat-bottom wells. Nothing
  models dead volume, viscosity, droplets or carry-over. The planner pipettes 1 mm above the
  floor everywhere, which is too high for a few microlitres in a flat-bottom well.
- **Other robots.** Three are planned for: a Hamilton STARlet, an Opentrons Flex and an OT-2,
  the last two with the gaps listed under [Robots](robots.md). The physics rehearsal alone works
  on any PyLabRobot deck.
- **PyLabRobot 1.0.** steadyhand targets the 0.2 line, the current stable release.
- **Exact shapes.** Round wells are treated as square, tip-rack holes are not modelled, and a
  tip's width is a nominal cone because PyLabRobot stores tip length but not width.
- **The 96-channel head, plate moves and other instruments.** A rehearsal lists such steps as
  "not rehearsed" instead of skipping them silently.
- **A changing deck.** The scene is the deck as it stood at the end of the run.
- **A real robot's motion.** Channels go straight up, across at a fixed height and straight
  down. There is no timing estimate and no check against a particular robot's reach.
- **Fluid physics.** Volumes are accounting. Nothing here simulates how liquid flows.
- **Comparison with a real run.** Nothing has been checked against hardware yet.
