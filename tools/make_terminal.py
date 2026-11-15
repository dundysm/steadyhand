"""Draw a run of `steadyhand rehearse` as it looks in a terminal, for the README.

  python tools/make_terminal.py docs/terminal.svg

Needs `rich`. Not part of the package.
"""

import os
import subprocess
import sys

from rich.console import Console
from rich.terminal_theme import TerminalTheme
from rich.text import Text

COMMAND = ["steadyhand", "rehearse", "examples/serial_dilution.yaml", "--no-render"]
THEME = TerminalTheme(
  (23, 24, 27), (233, 232, 228),
  [(52, 55, 61), (255, 107, 99), (76, 196, 126), (255, 176, 32), (74, 168, 255), (190, 150, 255), (86, 200, 210), (233, 232, 228)],
  [(107, 111, 118), (255, 107, 99), (76, 196, 126), (255, 176, 32), (74, 168, 255), (190, 150, 255), (86, 200, 210), (255, 255, 255)],
)


def main(target: str) -> None:
  ran = subprocess.run(COMMAND, capture_output=True, text=True, env={**os.environ, "FORCE_COLOR": "1"})
  console = Console(record=True, width=92, file=open(os.devnull, "w"), force_terminal=True, color_system="truecolor")
  console.print(Text("$ " + " ".join(COMMAND[:-1]), style="bold"))
  console.print(Text.from_ansi(ran.stdout.rstrip()))
  console.save_svg(target, title="steadyhand", theme=THEME)
  print(f"wrote {target}")


if __name__ == "__main__":
  main(sys.argv[1])
