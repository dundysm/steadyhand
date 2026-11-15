# Contributing

steadyhand is pre-alpha and moves quickly. Reports are worth more than code right now, above all a
protocol that passes here and fails, or would fail, on a real robot: open an issue with the file.

## Setting up

```bash
git clone https://github.com/dundysm/steadyhand && cd steadyhand
pip install -e ".[dev]"
pytest
```

The tests take a few minutes. Those that need Opentrons' software or its simulator are skipped
when it is not installed.

## What a change needs

- **A test** that fails without it. Tests are named as sentences that say what holds.
- **Nothing claimed that was not measured.** A number in the README or in
  [evals/RESULTS.md](evals/RESULTS.md) comes from a run that is written up there, with its caveats.
- **The fault pages regenerated** when a check changes:
  `steadyhand faults --robot hamilton-starlet -o docs/faults.md`, and the same for
  `opentrons-flex` and `opentrons-ot2`. A test pins the counts.
- **The drafting guide frozen before it is measured.** A change to the instructions in
  `src/steadyhand/intake.py` is committed before any text it will be tried on is read by a model,
  and a set of texts is used once.

## Style

Two-space indents, type hints, and comments that say why. Commit messages are
`area: short lowercase description`, for example `planner: split a transfer so its parts add up`.

## Pictures

The pictures in the README are drawn by the scripts in `tools/`: `make_media.py` for the
animation, `make_terminal.py` for the terminal, `make_art.py` for the logo and the diagram.
