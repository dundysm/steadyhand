"""Colour for the terminal: the verdict of each stage stands out, the rest stays as it is.

Only when the output is a terminal. Pipes, files and CI logs get the plain text, and so does
anyone who sets NO_COLOR (https://no-color.org).
"""

from __future__ import annotations

import os
import re
import sys
from typing import TextIO

RESET, BOLD, DIM, RED, GREEN, YELLOW = "\033[0m", "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m"

_VERDICT = re.compile(r"^(steadyhand [\w ']+: )(PASS|OK|FAIL|REFUSED)\b(.*)$")
_STOPPED = re.compile(r"^(\s+(?:problems|collisions|tips out of the liquid or the well): )([1-9]\d*)(.*)$")
_QUIET = re.compile(r"^(wrote |open |to look around )")


def paint(line: str) -> str:
  """One line of output, with its verdict coloured. Lines that carry none come back unchanged."""
  verdict = _VERDICT.match(line)
  if verdict:
    head, word, rest = verdict.groups()
    colour = GREEN if word in ("PASS", "OK") else RED
    return f"{BOLD}{head}{colour}{word}{RESET}{BOLD}{rest}{RESET}"
  stopped = _STOPPED.match(line)
  if stopped:
    head, count, rest = stopped.groups()
    return f"{head}{BOLD}{RED}{count}{RESET}{rest}"
  if _QUIET.match(line):
    return f"{DIM}{line}{RESET}"
  return line


def wanted(stream: TextIO) -> bool:
  if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
    return False
  return bool(os.environ.get("FORCE_COLOR")) or (hasattr(stream, "isatty") and stream.isatty())


class Painted:
  """A stand-in for stdout that paints whole lines as they are written."""

  def __init__(self, stream: TextIO) -> None:
    self._stream = stream
    self._held = ""

  def write(self, text: str) -> int:
    self._held += text
    *lines, self._held = self._held.split("\n")
    for line in lines:
      self._stream.write(paint(line) + "\n")
    return len(text)

  def flush(self) -> None:
    if self._held:
      self._stream.write(paint(self._held))
      self._held = ""
    self._stream.flush()

  def __getattr__(self, name: str):
    return getattr(self._stream, name)


def install() -> None:
  """Paint what the commands print, when stdout is a terminal that takes colour."""
  if wanted(sys.stdout) and not isinstance(sys.stdout, Painted):
    sys.stdout = Painted(sys.stdout)  # type: ignore[assignment]
