"""Build the held-out notes: the protocol pages of manufacturers' manuals, exactly as `steadyhand draft` reads them.

  python evals/heldout/fetch.py

Each manual is downloaded from its maker, the pages named below are read with the same code
`steadyhand draft manual.pdf --pages ...` uses, and the text is written to evals/out/heldout/CASE.txt.
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


def main() -> int:
  out = Path(__file__).parents[1] / "out" / "heldout"
  (out / "pdf").mkdir(parents=True, exist_ok=True)
  for case, _, url, pages in MANUALS:
    pdf = out / "pdf" / (url.rsplit("/", 1)[1])
    if not pdf.exists():
      request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
      with urllib.request.urlopen(request, timeout=60) as reply:
        pdf.write_bytes(reply.read())
    text = read_source(pdf, pages)
    (out / f"{case}.txt").write_text(text, encoding="utf-8")
    print(f"{case:12} pages {pages:9} {len(text):6,} characters")
  return 0


if __name__ == "__main__":
  sys.exit(main())
