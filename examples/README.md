# Examples

Each of these rehearses as it stands on the Hamilton STARlet, and the dilution, the bench test and the cell staining on the Opentrons robots too:

```bash
steadyhand rehearse examples/serial_dilution.yaml
steadyhand rehearse examples/serial_dilution.yaml --robot opentrons-flex
```

| File | What it shows |
| --- | --- |
| [serial_dilution.yaml](serial_dilution.yaml) | A two-fold dilution across a 96-well plate: one transfer that reuses its tip, and a `serial_dilution` step with mixing and a discard |
| [pcr_setup.yaml](pcr_setup.yaml) | 24 PCR reactions: master mix and template into a PCR plate, mixed after the template goes in |
| [cell_staining.yaml](cell_staining.yaml) | Washing, fixing and staining cells on two 24-well plates: each step names both plates in a list, and every removal is `to: waste` with `volume: all`, drawn from the surface |
| [normalization.yaml](normalization.yaml) | A `normalize` step that works out each sample's volume from the concentrations in [normalization_samples.csv](normalization_samples.csv) |
| [bench_test.yaml](bench_test.yaml) | A first run on a real robot with water and food dye: dye diluted two-fold across a plate, so the result can be judged by eye. See [docs/bench-test.md](../docs/bench-test.md) |

The fields are described in [docs/protocol-format.md](../docs/protocol-format.md).

[drafts/](drafts/README.md) holds four protocol files a model drafted from kit manuals, unedited, for someone who has run those kits to read.
