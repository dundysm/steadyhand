"""Write the logo and the pipeline drawing, each for a light and a dark page.

  python tools/make_art.py

Not part of the package.
"""

from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
FONT = "Inter, 'Segoe UI', system-ui, -apple-system, Helvetica, Arial, sans-serif"
THEMES = {
  "light": {"ink": "#1d1f23", "soft": "#5b6068", "line": "#b9bcc2", "card": "#ffffff", "accent": "#2f8fe0", "warm": "#e08a00"},
  "dark": {"ink": "#e9e8e4", "soft": "#a3a8b0", "line": "#4a4f57", "card": "#202226", "accent": "#4aa8ff", "warm": "#ffb020"},
}

LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 430 96" width="430" height="96" role="img" aria-label="steadyhand">
  <rect x="27" y="6" width="26" height="9" rx="2.5" fill="{ink}"/>
  <path d="M31 17 H49 L43.2 60 H36.8 Z" fill="{ink}"/>
  <path d="M40 66 C45.5 74 47 78.5 40 84 C33 78.5 34.5 74 40 66 Z" fill="{accent}"/>
  <path d="M12 90 H68" stroke="{line}" stroke-width="2.5" stroke-linecap="round"/>
  <text x="88" y="64" font-family="{font}" font-size="50" font-weight="650" letter-spacing="-1.4" fill="{ink}">steady<tspan fill="{accent}">hand</tspan></text>
</svg>
"""

STAGES = [
  ("notes.txt", "a note or a kit manual", None),
  ("protocol.yaml", "names no robot", "draft"),
  ("checked", "the liquid adds up", "check"),
  ("planned", "tips, channels, deck", "plan"),
  ("rehearsed", "every move replayed", "rehearse"),
  ("robot program", "what was rehearsed", "emit"),
]


def pipeline(theme: dict) -> str:
  width, box, gap, top = 980, 132, 37, 34
  parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 118" width="{width}" height="118" role="img" '
    'aria-label="notes, then a protocol file, checked, planned, rehearsed, and the robot program">',
    f'<defs><marker id="a" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">'
    f'<path d="M0 0 L8 4 L0 8 Z" fill="{theme["soft"]}"/></marker></defs>',
  ]
  for i, (name, caption, verb) in enumerate(STAGES):
    x = 2 + i * (box + gap)
    last = i == len(STAGES) - 1
    stroke = theme["accent"] if last else theme["line"]
    parts.append(
      f'<rect x="{x}" y="{top}" width="{box}" height="46" rx="9" fill="{theme["card"]}" stroke="{stroke}" stroke-width="{2 if last else 1.5}"/>'
      f'<text x="{x + box / 2}" y="{top + 29}" text-anchor="middle" font-family="{FONT}" font-size="15" font-weight="650" fill="{theme["ink"]}">{name}</text>'
      f'<text x="{x + box / 2}" y="{top + 68}" text-anchor="middle" font-family="{FONT}" font-size="11.5" fill="{theme["soft"]}">{caption}</text>'
    )
    if verb:
      x0 = x - gap + 4
      parts.append(
        f'<path d="M{x0} {top + 23} H{x - 5}" stroke="{theme["soft"]}" stroke-width="1.5" marker-end="url(#a)"/>'
        f'<text x="{x - gap / 2}" y="{top - 9}" text-anchor="middle" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="11.5" font-weight="600" fill="{theme["warm"]}">{verb}</text>'
      )
  parts.append("</svg>\n")
  return "\n".join(parts)


def main() -> None:
  for name, theme in THEMES.items():
    (DOCS / f"logo-{name}.svg").write_text(LOGO.format(font=FONT, **theme))
    (DOCS / f"pipeline-{name}.svg").write_text(pipeline(theme))
    print(f"wrote docs/logo-{name}.svg, docs/pipeline-{name}.svg")


if __name__ == "__main__":
  main()
