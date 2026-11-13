# The drybench protocol file (draft 0.1)

A protocol file says **what** to do: which labware, where the liquids start, and the steps.
It says nothing about **how** a robot does it. Deck positions, tip types and channels are chosen
by the planner (`drybench plan FILE`). An editable plan file for overriding those choices is not built yet.

The file is YAML so that a person can read it, a language model can write it, and everything
after it can be exact. `drybench check FILE` reads it and follows the liquid through every move.

This is a draft. Nothing here is frozen.

## Five rules

1. **Every amount carries a unit.** `100 uL`, `20 mL`, `5 min`, `10 ng/uL`. A bare number is an error.
2. **Unknown fields are errors.** A misspelt field is reported, never ignored.
3. **Every problem is reported at once**, each with its place in the file, such as `steps[2].transfer.volume`.
4. **Steps state intent.** `serial_dilution` and `normalize` expand into plain transfers and
   mixes by fixed rules. `drybench check FILE --moves` shows the expansion.
5. **The same file always gives the same moves.** Nothing in reading or expanding is random.

## Sections

| Section | Required | Holds |
| --- | --- | --- |
| `drybench` | yes | The format version, `0.1` |
| `name` | yes | A title |
| `description` | no | Free text |
| `labware` | yes | A name for each plate and its PyLabRobot definition, e.g. `plate: {type: Cor_96_wellplate_360ul_Fb}` |
| `liquids` | no | Where each liquid starts and how much is in each well, e.g. `buffer: {in: reservoir/A1, volume: 20 mL}` |
| `samples` | no | A CSV of per-sample values: `file`, `labware`, the `well` column, the `concentration` column and its `unit` |
| `limits` | no | `min_volume`, the smallest volume a move may have. Default `1 uL` |
| `steps` | yes | The steps, in order |

Wells are written `labware/well`. A range is `plate/A1:H1`, from its top-left well to its
bottom-right well, read down each column and then across, as PyLabRobot does.

## Steps

| Step | Fields | Expands to |
| --- | --- | --- |
| `transfer` | `from`, `to`, `volume`; optional `tips`, `mix_after` | One source to many wells, many to one, or pairs of equal count |
| `mix` | `wells`, `volume`, `times` | One mix per well |
| `serial_dilution` | `start`, `steps`, `direction`, `volume`; optional `mix`, `discard`, `tips` | For each start well, a chain of transfers in that direction, then a discard |
| `normalize` | `from`, `to`, `diluent`, `target`, `final_volume`; optional `mix` | Diluent first, then each sample, with volumes worked out from the samples table |
| `wait` | `duration` | A pause |

`tips` is `fresh` (the default: a new tip for every transfer) or `reuse` (one tip per source well).
`mix` and `mix_after` are `{times: 3, volume: 80 uL}`. `direction` is `right`, `left`, `down` or `up`.

## What `check` catches today

- A well asked for more liquid than it holds at that point in the protocol.
- A well filled past the capacity PyLabRobot gives for that labware.
- A move below `limits.min_volume`.
- A sample too dilute to reach the `normalize` target, or so concentrated that its volume is too small to pipette.
- A serial dilution that runs off the plate.
- Labware, wells, units and fields that do not exist.

## Examples

- [`examples/serial_dilution.yaml`](../examples/serial_dilution.yaml): two steps become 184 transfers and 88 mixes.
- [`examples/normalization.yaml`](../examples/normalization.yaml): one step, with volumes from a CSV.

## Not in 0.1

- Steps for other instruments: `seal`, `spin`, `incubate` at a temperature, `read`, `move`.
- Labware chosen by requirement ("any 96-well plate that holds 200 uL") in place of an exact definition.
- Tube racks and other labware that is not a plate.
- Dead volume, the liquid a well cannot give up.

## Open questions

1. Should `normalize` and `serial_dilution` stay built in, or should the format offer a general
   way to define such steps?
2. Is YAML the right surface, or should the same model also be writable as a small Python API?
3. Should an export to an existing format such as Autoprotocol be a goal, so other tools can read drybench protocols?
