# A first run on a real robot

Nothing here has been compared with a real robot yet. This page is how to do that with water
and food dye, in about half an hour, and tell the project what happened. One such report is
worth more to steadyhand right now than any number of simulated runs.

> [!WARNING]
> steadyhand is pre-alpha. Read the program before you run it, use water only, stay by the robot
> with a hand near the stop, and watch the first moves. If anything on the deck is not
> what the plan says, do not start.

## What the run does

[examples/bench_test.yaml](../examples/bench_test.yaml) puts 100 uL of water into columns 2 to
12 of a 96-well plate, 200 uL of dye into column 1, and dilutes the dye two-fold, eleven times,
left to right. If it goes as rehearsed the plate ends as an even fade from column 1 to column
12, every well holds 100 uL, and the last 100 uL of each row is thrown away.

## What you need

| | Opentrons Flex | Opentrons OT-2 | Hamilton STARlet |
| --- | --- | --- | --- |
| Pipette | 8-channel 1000 uL | 8-channel P300 GEN2 | 8 channels |
| Tips | 2 racks, 200 uL filter | 2 racks, 200 uL filter | 2 racks, 300 uL filter |
| Plate | Corning 96-well 360 uL flat | the same | the same |
| Reservoirs | NEST 12-well 15 mL, and a NEST 1-well 195 mL for waste | the same | the same, on a plate carrier |
| Program | an Opentrons Python protocol | an Opentrons Python protocol | a [PyLabRobot](https://github.com/PyLabRobot/pylabrobot) script |

`steadyhand plan` prints the exact deck, slot by slot. If your labware differs, change the two
`type:` lines in the file to what you have and rehearse again: the plan is rebuilt around them.

In the 12-well reservoir, well A1 gets 12 mL of water and well A2 gets 4 mL of water with enough
food dye to see.

## Run it

```bash
pip install 'steadyhand[opentrons]'      # plain `pip install steadyhand` is enough for the Hamilton
git clone https://github.com/dundysm/steadyhand && cd steadyhand
steadyhand rehearse examples/bench_test.yaml --robot opentrons-flex   # or opentrons-ot2, or leave --robot out for the Hamilton
```

For the OT-2, [docs/robots.md](robots.md) says which Opentrons release still simulates it.

That writes `steadyhand-out/`. Open `replay.html` to watch what the robot is about to do, and
keep `report.txt`: it is the prediction your run is compared with.

- **Opentrons.** Import `steadyhand-out/protocol.py` in the Opentrons App like any Python
  protocol, set the deck up as the app shows it, and check it matches the plan steadyhand
  printed. Run your usual labware checks before you start.
- **Hamilton.** `protocol.py` is a PyLabRobot script, so the STARlet has to be set up to be
  driven by PyLabRobot and not by Venus. If it is not, this run is not a quick one, and a
  report from an Opentrons robot is just as useful.

## What to watch

1. Does every tip pick-up, aspirate and dispense land where the replay shows it?
2. Does anything touch that should not: a tip on a well wall, the head on labware?
3. Do the tips reach the liquid every time, in the reservoir and in the plate?
4. Does the run stop anywhere the rehearsal did not say it would, or carry on where it should have stopped?
5. At the end: an even fade left to right, the same level in every well, and nothing dripped on the deck?

If you have a plate reader, read the plate at a wavelength your dye absorbs. Each column should
read about half of the one to its left, and the eight rows should agree.

## Tell the project

Open a [real-robot run report](https://github.com/dundysm/steadyhand/issues/new?template=robot_run.yml).
It asks for the robot, the protocol file, what matched and what did not. A run that went wrong
is the most useful kind: say what happened and it becomes a test.
