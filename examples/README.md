# Examples

Each of these rehearses as it stands on the Hamilton STARlet, and the dilution on the Opentrons robots too:

```bash
steadyhand rehearse examples/serial_dilution.yaml
steadyhand rehearse examples/serial_dilution.yaml --robot opentrons-flex
```

| File | What it shows |
| --- | --- |
| [serial_dilution.yaml](serial_dilution.yaml) | A two-fold dilution across a 96-well plate: one transfer that reuses its tip, and a `serial_dilution` step with mixing and a discard |
| [pcr_setup.yaml](pcr_setup.yaml) | 24 PCR reactions: master mix and template into a PCR plate, mixed after the template goes in |
| [normalization.yaml](normalization.yaml) | A `normalize` step that works out each sample's volume from the concentrations in [normalization_samples.csv](normalization_samples.csv) |

The fields are described in [docs/protocol-format.md](../docs/protocol-format.md).
