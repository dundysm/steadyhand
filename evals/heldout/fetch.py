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
SETS = {"heldout": MANUALS, "heldout2": MANUALS_2, "heldout3": MANUALS_3}


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
