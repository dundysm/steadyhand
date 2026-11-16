"""Build the held-out notes: the protocol pages of manufacturers' manuals, exactly as `steadyhand draft` reads them.

  python evals/heldout/fetch.py

Each manual is downloaded from its maker, the pages named below are read with the same code
`steadyhand draft manual.pdf --pages ...` uses, and the text is written to evals/out/heldout/CASE.txt
(the second set to evals/out/heldout2).
Nothing is edited. The text belongs to the makers, so it is not kept in this repository: this
script and the list below are what is kept, and they rebuild it.

The pages were chosen from the manuals' own headings ("Assay Procedure", "Performing the Assay",
"Test Protocol"), before any of them was drafted.
"""

import sys
import urllib.request
from pathlib import Path

from steadyhand.intake import read_source

THERMO = "https://assets.thermofisher.com/TFS-Assets/LSG/manuals/"
PROMEGA = "https://www.promega.com/-/media/files/resources/protocols/technical-manuals/"
CAYMAN = "https://cdn.caymanchem.com/cdn/insert/"

# case, what it is, where the manual is, the pages with the protocol
MANUALS = [
  ("accugreen", "Biotium AccuGreen High Sensitivity dsDNA quantitation", "https://biotium.com/wp-content/uploads/2016/10/PI-31068.pdf", "1"),
  ("ribogreen", "Thermo Fisher Quant-iT RiboGreen RNA assay", THERMO + "mp11490.pdf", "2-5"),
  ("cyquant", "Thermo Fisher CyQUANT cell proliferation assay", THERMO + "mp07026.pdf", "4-5"),
  ("nanoorange", "Thermo Fisher NanoOrange protein quantitation", THERMO + "mp06666.pdf", "3-4"),
  ("brightglo", "Promega Bright-Glo luciferase assay", PROMEGA + "0/bright-glo-luciferase-assay-system-protocol.pdf", "5"),
  ("adpglo", "Promega ADP-Glo kinase assay", PROMEGA + "0/adp-glo-kinase-assay-protocol.pdf", "14-15"),
  ("adpglo_ic50", "Promega ADP-Glo, IC50 of a kinase inhibitor", PROMEGA + "0/adp-glo-kinase-assay-protocol.pdf", "14-15,17"),
  ("celltox", "Promega CellTox Green cytotoxicity assay, endpoint method", PROMEGA + "101/celltox-green-cytotoxicity-assay-protocol.pdf", "12-13"),
  ("gsh", "Cayman glutathione assay kit", CAYMAN + "703002.pdf", "8-10"),
  ("sod", "Cayman superoxide dismutase assay kit", CAYMAN + "706002.pdf", "8-10"),
  ("catalase", "Cayman catalase assay kit", CAYMAN + "707002.pdf", "7-10"),
  ("nitrate", "Cayman nitrate/nitrite colorimetric assay kit", CAYMAN + "780001.pdf", "7-10"),
  ("ssiv", "Thermo Fisher SuperScript IV first-strand synthesis", THERMO + "SSIV_First_Strand_Synthesis_System_UG.pdf", "3"),
  ("elisa_il6", "Thermo Fisher human IL-6 ELISA", THERMO + "213-2CE.pdf", "13-15"),
]

ZYMO = "https://files.zymoresearch.com/protocols/"

# The second set, chosen after the first had been drafted and the guide changed in answer to it (0.27.0).
MANUALS_2 = [
  ("oneglo", "Promega ONE-Glo luciferase assay", PROMEGA + "0/one-glo-luciferase-assay-system-protocol.pdf", "4-5"),
  ("lipo3000", "Thermo Fisher Lipofectamine 3000 transfection", THERMO + "lipofectamine3000_protocol.pdf", "1-2"),
  ("quickdna96", "Zymo Quick-DNA 96 kit (spin plate)", ZYMO + "_d3010_d3011_d3012_quick-dna_96_kit.pdf", "6"),
  ("magbead_dna", "Zymo Quick-DNA MagBead Plus kit", ZYMO + "_d4081_d4082_quick-dna_magbead_plus_kit.pdf", "8-9"),
  ("dna_cleanup96", "Zymo ZR-96 DNA Clean-up kit (spin plate)", ZYMO + "_d4017_d4018_zr-96_dna_clean-up_kit.pdf", "6"),
  ("tbars", "Cayman TBARS assay kit", CAYMAN + "10009055.pdf", "7-8"),
  ("antioxidant", "Cayman antioxidant assay kit", CAYMAN + "709001.pdf", "8-9"),
  ("camp_elisa", "Cayman cyclic AMP ELISA kit (competitive)", CAYMAN + "581001.pdf", "9-14"),
  ("pge2_elisa", "Cayman prostaglandin E2 ELISA kit (competitive)", CAYMAN + "514010.pdf", "10-13"),
  ("lpo", "Cayman lipid hydroperoxide assay kit", CAYMAN + "705002.pdf", "7-8"),
  ("gpx", "Cayman glutathione peroxidase assay kit", CAYMAN + "703102.pdf", "7-8"),
]
# The third set, chosen after the second had been drafted and the guide changed again (0.28.0).
MANUALS_3 = [
  ("glucose", "Cayman glucose colorimetric assay kit", CAYMAN + "10009582.pdf", "6-7"),
  ("cholesterol", "Cayman cholesterol fluorometric/colorimetric assay kit", CAYMAN + "10007640.pdf", "13-17"),
  ("triglyceride", "Cayman triglyceride colorimetric assay kit", CAYMAN + "10010303.pdf", "8-10"),
  ("protein_carbonyl", "Cayman protein carbonyl colorimetric assay kit", CAYMAN + "10005020.pdf", "7-8"),
  ("cox_screen", "Cayman COX fluorescent inhibitor screening assay kit", CAYMAN + "700100.pdf", "6-7"),
  ("glycolysis", "Cayman glycolysis cell-based assay kit", CAYMAN + "600450.pdf", "5-6"),
  ("bca_cayman", "Cayman protein determination (BCA) kit", CAYMAN + "701780.pdf", "5-6"),
  ("dualglo", "Promega Dual-Glo luciferase assay", PROMEGA + "0/dual-glo-luciferase-assay-system-protocol.pdf", "8-9"),
  ("steadyglo", "Promega Steady-Glo luciferase assay", PROMEGA + "0/steady-glo-luciferase-assay-system-protocol.pdf", "6-7"),
  ("hmw_magbead", "Zymo Quick-DNA HMW MagBead kit", ZYMO + "d6060_quick-dna_hmw_magbead_kit.pdf", "8-9"),
  ("quickrna96", "Zymo Quick-RNA 96 kit (spin plate)", ZYMO + "_r1052_r1053_quick-rna_96_kit.pdf", "7-8"),
]
# A fourth, small set aimed at what the third left untested: spin plates and heat or cold in mid-run (0.28.1).
MANUALS_4 = [
  ("quickrna96_full", "Zymo Quick-RNA 96 kit, with its purification page", ZYMO + "_r1052_r1053_quick-rna_96_kit.pdf", "7-9"),
  ("fungal96", "Zymo Quick-DNA Fungal/Bacterial 96 kit (bead beating, spin plate)", ZYMO + "_d6006_quick-dna_fungal-bacterial_96_kit.pdf", "7-8"),
  ("glycogen", "Cayman glycogen assay kit", CAYMAN + "700480.pdf", "7-9"),
  ("ffa", "Cayman free fatty acid fluorometric assay kit", CAYMAN + "700310.pdf", "8-9"),
  ("isoprostane_elisa", "Cayman 8-isoprostane ELISA kit (competitive)", CAYMAN + "516351.pdf", "10-13"),
  ("cox_activity", "Cayman COX activity assay kit", CAYMAN + "760151.pdf", "7-8"),
]
# A fifth set, bead kits only, for the magnet step (0.29.0).
MANUALS_5 = [
  ("kapa_pure_beads", "Roche KAPA Pure Beads, cleanup", "https://rochesequencingstore.com/wp-content/uploads/2022/07/KAPA-Pure-Beads-Technical-Data-Sheet.pdf", "4-5"),
  ("directzol_magbead", "Zymo Direct-zol-96 MagBead RNA", ZYMO + "_r2100_r2101_r2102_r2103_r2104_r2105_direct-zol-96_magbead_rna.pdf", "9"),
  ("quickrna_magbead", "Zymo Quick-RNA MagBead", ZYMO + "_r2132_r2133_quick-rna_magbead.pdf", "12"),
  ("viral_magbead", "Zymo Quick-DNA/RNA Viral MagBead", ZYMO + "_r2140_r2141_quick-dna-rna_viral_magbead.pdf", "8"),
  ("zymobiomics_magbead", "Zymo ZymoBIOMICS 96 MagBead DNA kit", ZYMO + "_d4302_d4306_d4308_zymobiomics-96_magbead_dna_kit.pdf", "10-11"),
]
# A sixth set, for the defaults and the person's own decisions (0.32.0).
MANUALS_6 = [
  ("h2o2", "Cayman hydrogen peroxide assay kit", CAYMAN + "600050.pdf", "6-8"),
  ("mpo_screen", "Cayman myeloperoxidase inhibitor screening assay kit", CAYMAN + "700170.pdf", "6-8"),
  ("g6p", "Cayman glucose-6-phosphate fluorometric assay kit", CAYMAN + "700750.pdf", "6-8"),
  ("lactate", "Cayman L-lactate assay kit", CAYMAN + "700510.pdf", "9-11"),
  ("ascorbate", "Cayman ascorbate assay kit", CAYMAN + "700420.pdf", "7-9"),
  ("betaglo", "Promega Beta-Glo assay", PROMEGA + "0/beta-glo-assay-system-protocol.pdf", "8-9"),
]
# A seventh set, read after five rules came out of reading the sixth set's drafts against their pages.
MANUALS_7 = [
  ("pad4", "Cayman PAD4 inhibitor screening assay kit (ammonia)", CAYMAN + "700560.pdf", "5-6"),
  ("catalase_nohp", "Cayman catalase assay kit (without hydrogen peroxide)", CAYMAN + "700910.pdf", "7-8"),
  ("autotaxin", "Cayman autotaxin inhibitor screening assay kit", CAYMAN + "700580.pdf", "6-7"),
  ("bhb", "Cayman beta-hydroxybutyrate fluorometric assay kit", CAYMAN + "700740.pdf", "9-11"),
  ("mdr", "Cayman multidrug resistance assay kit (calcein AM)", CAYMAN + "600370.pdf", "5-6"),
]
# An eighth set, after the glass, large-mix, suggested-control, own-plate and cell-seeding rules of 0.34.0.
MANUALS_8 = [
  ("uric_acid", "Cayman uric acid assay kit", CAYMAN + "700320.pdf", "8-10"),
  ("alt", "Cayman alanine transaminase colorimetric activity assay kit", CAYMAN + "700260.pdf", "6-7"),
  ("ldh_cyto", "Cayman LDH cytotoxicity assay kit", CAYMAN + "601170.pdf", "8-9"),
  ("xo", "Cayman xanthine oxidase fluorometric assay kit", CAYMAN + "10010895.pdf", "7-8"),
  ("hemoglobin", "Cayman hemoglobin colorimetric assay kit", CAYMAN + "700540.pdf", "6-7"),
]
# A ninth set, after the shaking, split-liquid, magnet-wait and before-the-run rules of 0.36.0.
MANUALS_9 = [
  ("nadglo", "Promega NAD/NADH-Glo assay", PROMEGA + "101/nad-nadh-glo-assay-protocol.pdf", "8-10"),
  ("rosglo", "Promega ROS-Glo H2O2 assay, cell-based", PROMEGA + "101/ros-glo-h2o2-assay-protocol.pdf", "7-8"),
  ("gr", "Cayman glutathione reductase assay kit", CAYMAN + "703202.pdf", "5-6"),
  ("ldl_uptake", "Cayman LDL uptake cell-based assay kit", CAYMAN + "10011125.pdf", "4-5"),
  ("netosis", "Cayman NETosis assay kit, elastase activity", CAYMAN + "601010.pdf", "9"),
]
# A tenth set, all assays on cells in a plate, after the rule for wells the text empties (after 0.36.0).
MANUALS_10 = [
  ("mtt_cayman", "Cayman MTT cell proliferation assay kit", CAYMAN + "10009365.pdf", "3"),
  ("glucose_uptake", "Cayman glucose uptake cell-based assay kit", CAYMAN + "600470.pdf", "4"),
  ("jc1", "Cayman JC-1 mitochondrial membrane potential assay kit, plate reader", CAYMAN + "10009172.pdf", "5"),
  ("ros_dhe", "Cayman ROS detection cell-based assay kit (DHE), adherent cells", CAYMAN + "601290.pdf", "5"),
  ("mc4r", "Cayman melanocortin-4 receptor reporter assay kit", CAYMAN + "600190.pdf", "5-6"),
]
# An eleventh set, cell assays again, after "cells put in a new medium" joined the rule on emptied wells
# and the OT-2 guide learned that the robot holds two pipettes (after 0.37.1).
MANUALS_11 = [
  ("cholesterol_uptake", "Cayman cholesterol uptake cell-based assay kit", CAYMAN + "600440.pdf", "4"),
  ("nadh_cell", "Cayman NAD/NADH cell-based assay kit", CAYMAN + "600480.pdf", "6-7"),
  ("seap", "Cayman secreted alkaline phosphatase reporter gene assay kit", CAYMAN + "600260.pdf", "9-10"),
  ("cyp3a4", "Cayman CYP3A4 induction reporter assay kit", CAYMAN + "600270.pdf", "5-6"),
  ("glutathione_cell", "Cayman glutathione cell-based detection kit", CAYMAN + "600360.pdf", "6"),
]
# Two more reporter kits, for the OT-2 only, after its guide was corrected: the eleventh set showed
# the note on its two pipettes gave a range the planner does not have.
MANUALS_12 = [
  ("ep2", "Cayman EP2 receptor (rat) reporter assay kit", CAYMAN + "600340.pdf", "4-5"),
  ("ox1r", "Cayman orexin 1 receptor reporter assay kit", CAYMAN + "600240.pdf", "4-5"),
]
# A thirteenth set, for `volume: all`: three manuals that take everything off a well again and again,
# and one that never does (0.39.0).
MANUALS_13 = [
  ("annexin", "Cayman annexin V FITC assay kit, flow cytometry and microscopy in a plate", CAYMAN + "600300.pdf", "10-11"),
  ("apoptosis", "Cayman multi-parameter apoptosis assay kit, adherent cells", CAYMAN + "601280.pdf", "5"),
  ("cell_staining", "Cayman cell-based immunofluorescence staining kit", CAYMAN + "600060.pdf", "4"),
  ("wst1", "Cayman WST-1 cell proliferation assay kit", CAYMAN + "10008883.pdf", "3"),
]
# A fourteenth set of one, for plates with fewer than eight rows on an Opentrons deck: a manual whose
# microscopy protocol is written for a 24-well plate (0.40.0).
MANUALS_14 = [
  ("oxldl_uptake", "Cayman oxidized LDL uptake assay kit, flow cytometry and fluorescence microscopy", CAYMAN + "601180.pdf", "5"),
]
# A fifteenth set, for plates with fewer than eight rows: five staining kits from five makers, written
# for 6-, 12- and 24-well plates (0.41.0).
MANUALS_15 = [
  ("sagal_cayman", "Cayman senescence-associated beta-galactosidase staining kit, 12-well plate", CAYMAN + "602010.pdf", "4-6"),
  ("oil_red_o", "Cosmo Bio lipid assay kit (Oil Red O), 24-well plate", "https://cosmobiousa.com/content/document/cosmo-bio-ltd/pmc-ak09f-cos_lipid-assay-kit_datasheet.pdf", "1"),
  ("sagal_cbl", "Cell Biolabs cellular senescence assay kit (SA-beta-gal staining), 35 mm wells", "https://www.cellbiolabs.com/sites/default/files/520894CF-3048-812A-2EBE544F97DF1280.pdf", "3-4"),
  ("bgal_abcam", "Abcam beta galactosidase assay kit (senescence), 24-well plate", "https://content.abcam.com/content/dam/abcam/product/documents/228/ab228562/Beta-Galactosidase-Assay-protocol-book-v3b-ab228562%20(website).pdf", "7-9"),
  ("senescence_bv", "BioVision senescence detection kit, 12-well plate", "https://store.genprice.com/content/biovision/datasheet/K320.pdf", "1"),
]
# A sixteenth set, for steps that name several ranges or plates at once: four more staining kits from
# three makers, on 6-, 12- and 24-well plates (0.42.0).
MANUALS_16 = [
  ("alizarin_sc", "ScienCell Alizarin Red S staining quantification assay, 6-well plate", "https://sciencellonline.com/PS/8678.pdf", "2-3"),
  ("nodule_cosmo", "Cosmo Bio calcified nodule staining kit, 24-well plate", "https://cosmobiousa.com/content/document/cosmo-bio-ltd/pmc-ak21-cos_calcified-nodule-staining-kit_datasheet.pdf", "1"),
  ("alp_cosmo", "Cosmo Bio alkaline phosphatase staining kit, 12-well plate", "https://cosmobiousa.com/content/document/cosmo-bio-ltd/pmc-ak20-cos_alkaline-phosphatase-staining-kit_datasheet.pdf", "1"),
  ("trap_alp_wako", "Wako TRAP/ALP stain kit, cultured cells in a 24-well plate", "https://labchem-wako.fujifilm.com/sc/07/294-67001.pdf", "2-3"),
]
SETS = {
  "heldout": MANUALS, "heldout2": MANUALS_2, "heldout3": MANUALS_3, "heldout4": MANUALS_4, "heldout5": MANUALS_5,
  "heldout6": MANUALS_6, "heldout7": MANUALS_7, "heldout8": MANUALS_8, "heldout9": MANUALS_9,
  "heldout10": MANUALS_10, "heldout11": MANUALS_11, "heldout12": MANUALS_12,
  "heldout13": MANUALS_13, "heldout14": MANUALS_14, "heldout15": MANUALS_15, "heldout16": MANUALS_16,
}


def main() -> int:
  for name, manuals in SETS.items():
    build(Path(__file__).parents[1] / "out" / name, manuals)
  return 0


def build(out: Path, manuals: list) -> None:
  (out / "pdf").mkdir(parents=True, exist_ok=True)
  for case, _, url, pages in manuals:
    pdf = out / "pdf" / (url.rsplit("/", 1)[1])
    if not pdf.exists():
      request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
      with urllib.request.urlopen(request, timeout=60) as reply:
        pdf.write_bytes(reply.read())
    text = read_source(pdf, pages)
    (out / f"{case}.txt").write_text(text, encoding="utf-8")
    print(f"{case:14} pages {pages:9} {len(text):6,} characters")


if __name__ == "__main__":
  sys.exit(main())
