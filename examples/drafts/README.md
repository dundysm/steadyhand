# Drafts to read

Four protocol files a model drafted from manufacturers' kit manuals, exactly as they came: no
hand edits. Each passes `steadyhand rehearse` on an Opentrons Flex, and Opentrons' simulator.
None has been read by someone who has run the kit. If you have, see
[docs/read-a-draft.md](../../docs/read-a-draft.md).

| Draft | Kit | Manual, protocol pages |
| --- | --- | --- |
| [calcium.yaml](calcium.yaml) | ScienCell calcium assay (8128) | [manual](https://sciencellonline.com/PS/8128.pdf), pp. 2-3 |
| [lactate.yaml](lactate.yaml) | BioVision lactate colorimetric/fluorometric assay kit (K607) | [manual](https://store.genprice.com/content/biovision/datasheet/K607.pdf), pp. 1-2 |
| [antioxidant_capacity.yaml](antioxidant_capacity.yaml) | Cell Biolabs OxiSelect total antioxidant capacity assay kit (STA-360) | [manual](https://www.cellbiolabs.com/sites/default/files/STA-360-total-antioxidant-capacity-assay-kit.pdf), pp. 4-6 |
| [glutathione_cells.yaml](glutathione_cells.yaml) | Promega GSH-Glo glutathione assay | [manual](https://www.promega.com/-/media/files/resources/protocols/technical-bulletins/101/gsh-glo-glutathione-assay-protocol.pdf), pp. 7-10 |

Nothing was decided for the model beforehand, so each draft chose eight samples and says so
under `chose`. They come from the eighteenth set in [evals/RESULTS.md](../../evals/RESULTS.md),
where the other drafts of the same manuals are described. The manuals belong to their makers
and are not copied here.
