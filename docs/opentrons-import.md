[steadyhand](../README.md) · [Commands](commands.md) · [Protocol file](protocol-format.md) · [Robots](robots.md) · [Drafting](drafting.md) · [PyLabRobot](pylabrobot.md) · [Opentrons protocols](opentrons-import.md) · [Limits](limits.md) · [Measurements](../evals/RESULTS.md)

# Rehearse an Opentrons protocol you already have

```bash
pip install 'steadyhand[opentrons]'
steadyhand rehearse my_protocol.py
```

The file is any Python protocol for an Opentrons Flex or OT-2: one you wrote, one exported from
Protocol Designer, one a model wrote. steadyhand does not need to have planned it, and does not
change it.

## What happens

1. **Opentrons' software analyses the protocol.** This is the analysis its app runs when you
   import a file. It gives back every command the robot would be sent, the labware and pipettes
   the protocol loads, and any liquid it declares with `load_liquid`. If the analysis objects,
   that is reported and nothing else is claimed.
2. **The liquid is followed through every command.** What each well holds, what each tip draws
   and where it ends up.
3. **The commands are replayed in the physics scene**, on a deck built from the labware
   definitions the analysis names, with the tip at the height the protocol sends it to.

Opentrons' analysis answers "will the robot accept this file?". It does not track liquid unless
the protocol asks it to, so a protocol can pass it and still do the things below.

## What it finds that the analysis lets through

[examples/opentrons/three_mistakes.py](../examples/opentrons/three_mistakes.py) passes Opentrons'
analysis with no error. `steadyhand rehearse` says:

```
steadyhand import: FAIL  Three mistakes Opentrons' analysis lets through  (Opentrons Flex, API 2.19, analysed by opentrons 10.1.0)
  left  mount: p1000_single_flex
  slot C1  opentrons_flex_96_tiprack_200ul (opentrons_flex_96_tiprack_200ul)
  slot D1  assay_plate (corning_96_wellplate_360ul_flat)
  slot D2  reagents (nest_12_reservoir_15ml)
  commands: 34, of which 11 draws and 11 deliveries of liquid, 2 tip pick-ups
  liquid the protocol declares: 1 well
  wells drawn from with no liquid declared: 1. Each was given the least that keeps every draw under the liquid, 995 uL in all:
    reagents/A2: 994.7 uL
  problems: 3
    - draws 2 uL with the p1000_single_flex, 1 time; that pipette is specified for no less than 5 uL
    - command 18 draws 100 uL from reagents/A1, which holds 0.0 uL then
    - command 28 fills assay_plate/A1 to 400.0 uL, and the well holds 360 uL
steadyhand rehearsal: FAIL
  steps rehearsed: 26 (path 9.57 m, 2157 samples)
  collisions: 0
  tips out of the liquid or the well: 1
    - step 11 (aspirate, channel 0) in reagents_well_A1: the tip stops 1 mm above the liquid, so it draws air
```

| Found | How |
| --- | --- |
| A well asked for more than it holds | Followed from what the protocol declares, command by command |
| A well filled past its capacity | The same, against the capacity in the labware definition |
| A draw with the tip above the liquid, or one the liquid falls away from | The replay, from the well's shape and the height the protocol sends the tip to |
| A volume below what the pipette is specified for | A table of the pipettes' lower limits |
| A tip or a channel that runs into something | The replay |

## Wells with no liquid declared

Most protocols do not say what their reagent wells start with. For every well that is drawn from
and has nothing declared, steadyhand works out the least it must hold for every draw to stay
under the liquid at the height the protocol draws from, and lists it. That number includes what
stands below the tip and cannot be reached, so it is the volume to load, not the volume used:
the 995 uL above is 400 uL of draws and what a 15 mL trough well holds below a tip 1 mm off its
floor.

A well the protocol does declare is held to what it declares.

## What the replay does with the rest

- **Air gaps** are air: a draw with the tip at or above the rim of a well, or over the trash,
  takes no liquid, and the air leaves first at the next dispense.
- **The trash.** Liquid dispensed or blown out into the trash goes to a waste reservoir that
  stands beside the deck in the replay. Labware the protocol itself names waste or trash is
  treated as waste too, so a draw that ends there is a removal and may empty a well.
- **Eight channels** reach a column of an 8-row plate, every other row of a 384-well plate, or
  one trough well together.
- **Custom labware.** Pass the definitions with `--labware`, a file or a folder, as many times
  as needed. They go to Opentrons' analysis and to the replay.
- **A saved analysis.** `steadyhand rehearse analysis.json` reads an analysis you already have,
  such as the output of `python -m opentrons.cli analyze --json-output`.
- **OT-2 protocols.** Current Opentrons releases analyse Flex protocols only. Set
  `STEADYHAND_OT2_SIMULATE` as [docs/robots.md](robots.md) describes and OT-2 protocols are
  analysed by that release.

## What it does not do yet

Said in the report, by name, every time:

- **Moving labware, the 96-channel pipette and partial tip pick-up.** The replay follows the
  commands up to the first of these, says which command stopped it, and the run is not called
  clean.
- **Modules.** Labware on a heater-shaker, a temperature module, a thermocycler or an adapter is
  drawn at deck height. Module commands, waits and pauses are counted and passed over.
- **Touch tip, liquid probing, flow rates and delays** are not modelled.
- **Analysing a protocol runs its Python.** That is how Opentrons' analysis works, in the app
  too. Rehearse files you would be willing to import there.

The exit status is 1 when anything is found, when the analysis objects, or when the commands
could only be followed part of the way.
