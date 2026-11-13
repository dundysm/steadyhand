# drybench

Rehearse a lab-robot protocol in a physics scene before it touches a real bench.

Write what you want done in a short protocol file. drybench checks that the liquid adds up,
chooses tips, channels and a deck layout, replays every move in a [MuJoCo](https://mujoco.org)
scene built from the same deck, and writes a [PyLabRobot](https://github.com/PyLabRobot/pylabrobot)
script that does exactly what was rehearsed.

![Eight channels drawing buffer from a reservoir on a Hamilton STARlet deck, next to a 96-well plate](docs/reservoir.png)

**Status: pre-alpha.** The whole path runs for pipetting protocols on a Hamilton STARlet deck.
Nothing has been compared with a real robot yet, so it is not a tool to trust with a real run.
See [What it does not do yet](#what-it-does-not-do-yet).

## Try it

```bash
pip install -e .
drybench rehearse examples/serial_dilution.yaml
```

```
drybench check: PASS  Two-fold serial dilution across a 96-well plate
  moves: 184 transfers, 88 mixes, 89 tips
  buffer: uses 8800 uL of 20000 uL supplied
  sample: uses 800 uL of 1600 uL supplied
  discarded: 800 uL
  problems: 0
drybench plan: OK  Two-fold serial dilution across a 96-well plate
  rails  1  TIP_CAR_480_A00: tips_300_1
  rails  7  PLT_CAR_L5AC_A00: plate, reservoir, waste
  tips: 96 x hamilton_96_tiprack_300uL_filter
  commands: 136 (56 aspirates, 56 dispenses), up to 8 channels at once
drybench rehearsal: PASS
  steps rehearsed: 1088 (path 269.44 m, 33857 samples)
  collisions: 0
wrote drybench-out/protocol.py
```

`drybench-out/` then holds `protocol.py` (the PyLabRobot script), `scene.xml` (open it with
`python -m mujoco.viewer --mjcf drybench-out/scene.xml`), a report as text and JSON, and two
pictures when the machine can render offscreen. Every command exits with status 1 when
something is wrong, so it can gate a script or a CI job.

## The protocol file

The protocol in the run above is this file:

```yaml
drybench: 0.1
name: Two-fold serial dilution across a 96-well plate
labware:
  plate:     {type: Cor_96_wellplate_360ul_Fb}
  reservoir: {type: nest_1_troughplate_195000uL_Vb}
liquids:
  buffer: {in: reservoir/A1, volume: 20 mL}
  sample: {in: plate/A1:H1, volume: 200 uL}
steps:
  - transfer: {from: reservoir/A1, to: plate/A2:H12, volume: 100 uL, tips: reuse}
  - serial_dilution:
      start: plate/A1:H1
      steps: 11
      direction: right
      volume: 100 uL
      mix: {times: 3, volume: 80 uL}
```

It says what to do and nothing about how a robot does it. Every amount carries a unit, unknown
fields are errors, and every problem is reported at once with its place in the file. The format
is a draft: see [docs/protocol-format.md](docs/protocol-format.md).

## The five commands

| Command | What it does |
| --- | --- |
| `drybench draft NOTES -o FILE` | Has a language model write the protocol file from plain text. See below. |
| `drybench check FILE` | Reads the file and follows the liquid through every move. Add `--moves` to list them. |
| `drybench plan FILE` | Also chooses tips, groups moves into 8-channel commands and lays out the deck. |
| `drybench rehearse FILE` | Also replays the plan in the physics scene and, if nothing collides, writes the script. |
| `drybench emit FILE -o script.py` | Writes the PyLabRobot script without rehearsing. |

### What `check` catches

- A well asked for more liquid than it holds at that point.
- A well filled past the capacity PyLabRobot gives for that labware.
- A volume too small to pipette.
- A sample too dilute to normalize, or a dilution series that runs off the plate.

### What `plan` decides

- **Tips.** The smallest filter tip that holds the largest volume it will carry. A transfer bigger
  than the largest tip is split into equal parts.
- **Channels.** Consecutive moves share one 8-channel command when their wells sit in one column
  at least 9 mm apart, or all draw from one well wide enough to take them.
- **Deck.** Tip carriers from rail 1, plate carriers after them. Discarded liquid goes to a
  `waste` reservoir the planner adds.

### What `rehearse` checks

Whether a channel or its tip would be driven into the deck, a carrier, a plate's floor or the
walls between wells. A test also confirms that PyLabRobot's own volume trackers end the run
with the same volume in every well that `check` predicted.

## Draft a protocol from plain text

`draft` is the only place a language model is used. It writes the protocol file; drybench then
reads and checks that file exactly as if you had written it, and sends any problems back to the
model, up to three times. Nothing a model writes reaches a plan without passing `check`.

```bash
# any command that reads a prompt on stdin and prints a reply
drybench draft notes.txt -o protocol.yaml --model-command "my-local-model"

# or an API, with the key in ANTHROPIC_API_KEY or OPENAI_API_KEY
drybench draft notes.txt -o protocol.yaml --provider anthropic --model MODEL_NAME
drybench draft notes.txt -o protocol.yaml --provider openai --model MODEL_NAME
```

`--provider openai` works with any OpenAI-compatible server; point `OPENAI_BASE_URL` at it.
When the text leaves something out, the model is told to choose the conventional option and
record the choice under `notes` in the file. Read the file against your source before you use it.

## Rehearse a PyLabRobot protocol you already have

Swap your backend for `RecordingBackend`, run the protocol, then rehearse what it recorded.

```python
import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from drybench import RecordingBackend, rehearse

async def main():
    deck = build_my_deck()                      # your usual PyLabRobot deck
    backend = RecordingBackend(num_channels=8)
    lh = LiquidHandler(backend=backend, deck=deck)
    await lh.setup()

    await my_protocol(lh)                       # unchanged

    result = rehearse(deck, backend.steps)
    print(result.report())

asyncio.run(main())
```

`drybench demo` runs a built-in example of this, and `drybench demo --fault offset` or
`--fault depth` plants a mistake to show a failing rehearsal.

## How the scene is built

PyLabRobot describes a deck as a tree of resources, each with a position and a bounding box.
A bounding box is not a solid: a carrier's box reaches above the plates standing on it, and a
plate's box contains its wells. drybench keeps only what the tree lets it know is solid.

| Resource | Becomes |
| --- | --- |
| Nothing inside it (a lid, a gripper block) | A solid box |
| A grid of cavities (a plate, a tip rack) | A floor under the cavities, plus the walls between and around them |
| Anything else with children (a carrier, the deck) | Solid from its bottom up to the lowest thing inside it |
| A cavity (a well, a tube, a tip spot) | Empty space. Liquid and tips are drawn but never collide |

Heights follow the Hamilton STAR backend in PyLabRobot: a tip is picked up at its top minus its
fitting depth, and liquid is moved with the tip's end at the cavity floor plus the liquid height.

## What it does not do yet

- **A proven intake.** `draft` is tested against stand-in models and stub APIs only. It has not
  yet been run with a real model, so how well models follow the format is unmeasured. It does
  not write `normalize` steps or read PDFs.
- **An editable plan.** The planner's choices are printed, but cannot yet be overridden.
- **Other robots.** The planner targets a Hamilton STARlet. The rehearsal alone works on any
  PyLabRobot deck.
- **PyLabRobot 1.0.** drybench targets the 0.2 line, the current stable release.
- **Exact shapes.** Round wells are treated as square, tip-rack holes are not modelled, and a
  tip's width is a nominal cone because PyLabRobot stores tip length but not width.
- **The 96-channel head, plate moves and other instruments.** A rehearsal lists such steps as
  "not rehearsed" instead of skipping them silently.
- **A changing deck.** The scene is the deck as it stood at the end of the run.
- **A real robot's motion.** Channels go straight up, across at a fixed height and straight
  down. There is no timing estimate and no check against a particular robot's reach.
- **Fluid physics.** Volumes are accounting. Nothing here simulates how liquid flows.
- **Comparison with a real run.** Nothing has been checked against hardware yet.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

Apache-2.0. See [LICENSE](LICENSE).
