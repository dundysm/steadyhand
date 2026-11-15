"""Write CHANGELOG.md from the release notes on GitHub.

  gh api "repos/dundysm/steadyhand/releases?per_page=100" --paginate \
    --jq '.[] | [.tag_name, (.published_at[0:10]), .name, (.body // "")] | @json' | python tools/make_changelog.py

Not part of the package.
"""

import json
import re
import sys
from pathlib import Path


def main() -> None:
  rows = [json.loads(line) for line in sys.stdin if line.strip()]
  rows.sort(key=lambda row: tuple(int(n) for n in re.findall(r"\d+", row[0])), reverse=True)
  oldest = rows[-1][0].lstrip("v")
  out = [
    "# Changelog",
    "",
    f"Releases since {oldest}, newest first, as their release notes were written. Earlier versions are in the",
    "commit log, and the measurements behind every claim are in [evals/RESULTS.md](evals/RESULTS.md).",
    "",
  ]
  for tag, date, name, body in rows:
    title = re.sub(r"^v?\d+\.\d+\.\d+:?\s*", "", name or "").strip()
    out += [f"## {tag.lstrip('v')} ({date})", ""]
    if title:
      out += [f"**{title}**", ""]
    body = body.replace("\r\n", "\n").strip()
    if body:
      out += [body, ""]
  Path(__file__).resolve().parent.parent.joinpath("CHANGELOG.md").write_text("\n".join(out).rstrip() + "\n")
  print(f"wrote CHANGELOG.md: {len(rows)} releases")


if __name__ == "__main__":
  main()
