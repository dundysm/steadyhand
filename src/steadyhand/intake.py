"""Draft a protocol file from plain text with a language model.

This is the only place steadyhand uses a model. The model reads notes, a kit manual or a
sentence and writes a protocol file. steadyhand then reads that file exactly as it would read
one written by hand; if it does not hold up, the problems go back to the model for another
try. Nothing the model writes reaches a plan or a robot without passing `check`.

A model here is any function that takes a list of messages and returns text. Three ready-made
ones are provided: a shell command, the Anthropic API and any OpenAI-compatible API.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shlex
import shutil
import subprocess
import urllib.error
import urllib.request
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .planner import carrier_refusal
from .protocol import Check, Problem, ProtocolError, check, loads

Message = Dict[str, str]  # {"role": "system" | "user" | "assistant", "content": ...}
Model = Callable[[List[Message]], str]

GUIDE = """\
You write protocol files for steadyhand, a tool that checks and rehearses liquid-handling
protocols. Read the text the user gives you and write the protocol it describes.

Reply with one YAML document and nothing else.

RULES
- Every amount carries a unit: "100 uL", "20 mL", "5 min", "10 ng/uL". Never a bare number.
- Use only the fields listed below. Any other field is an error.
- Wells are written labware/well, such as plate/A1. A range such as plate/A1:H1 runs from its
  top-left well to its bottom-right well. On a 96-well plate, A1:H1 is column 1 (8 wells) and
  A1:A12 is row A (12 wells).
- Declare under `liquids` every liquid in a well before the first step that the steps draw
  from, add to or mix, with the wells it starts in and the volume in each. Leave out liquid
  that no step touches: declaring it is an error.
  Use the volume the text gives. When it gives none for a liquid the steps draw from, supply
  about 20% more than they use, and at least 10 uL more in a plate well or 2 mL more in a
  trough or reservoir, because a tip cannot reach the last of a shallow liquid. When it gives none for what is already in wells the steps add
  to or empty, treat those wells as empty and say so in `notes`.
- Labware types must come from the LABWARE list, spelled exactly. When the text does not name
  the labware, choose one whose wells hold the largest volume any well reaches with room to spare.
  For wells a tip draws from or mixes in while they hold 50 uL or less, choose a V- or
  U-bottom plate: in a flat-bottom well that little liquid is too shallow for a tip to reach.
- To throw liquid away, transfer it `to: waste`. Waste is not labware: do not declare it.
- There are no loops. Write a repeated action out as repeated steps.
- Do not invent steps the text does not describe.
- Leave out what a pipetting robot cannot do (vortexing, a magnet, heating, sealing, storage)
  and say so in `notes`, one sentence each. A timed step becomes a `wait` of that length, even on
  equipment the robot lacks (shake 30 s, incubate 2 h). For "at least" a time, use that time;
  for "overnight", use 16 h; a step with no time at all gets no wait.
- When the text leaves out something you need (a volume, a plate type, where a reagent
  starts), choose the most conventional option and record that choice as one sentence under
  `notes`. Every choice you made that the text did not state must appear there. A mix volume
  the text does not give is about two thirds of what the well holds at that point.
- When the text asks for something the format cannot say exactly (such as new tips per
  column), use the nearest stricter option and say so in `notes`.
- Use `normalize` only when the text asks to bring samples to a common concentration and a
  samples file is offered with the text. If the text asks for it and no file is offered, write
  the step with `samples.file: samples.csv` and say in `notes` that the file is needed.
- Never change an amount the text states. If what the text describes cannot work (a well
  would overflow, a source would run dry), write it as stated and say so in `notes`.
- When you are told about a problem that only a person can settle (the text itself cannot work,
  a samples file is missing), send the same file again. That ends the drafting and hands the
  problem to them.

SECTIONS
steadyhand: 0.1            (required, exactly this)
name: <title>            (required)
description: <text>      (optional)
notes: [<sentence>, ...] (optional; see above)
labware:                 (required) one entry per plate or reservoir
  <name>: {type: <definition from LABWARE>}
liquids:                 (optional)
  <name>: {in: <wells>, volume: <volume in each well>}
samples:                 (optional; only with a normalize step, and only for a samples file offered to you)
  {file: <its name>, labware: <labware the samples are in>, well: <column of well names>, concentration: <column of concentrations>, unit: <their unit, such as ng/uL>}
limits: {min_volume: <volume>}   (optional; default 1 uL)
steps:                   (required) a list; each item is exactly one of the steps below

STEPS
- transfer: {from: <wells>, to: <wells>|waste, volume: <volume>, tips: fresh|reuse, mix_after: {times: <n>, volume: <volume>}}
    from/to pair up as: one source to many wells, many sources to one well, or equal counts.
    volume is the amount per destination. tips defaults to fresh (a new tip per transfer);
    reuse keeps one tip per source well and suits clean liquid going into empty wells.
    tips and mix_after are optional; without mix_after nothing is mixed.
- mix: {wells: <wells>, volume: <volume>, times: <n>}
- serial_dilution: {start: <wells>, steps: <n>, direction: right|left|down|up, volume: <volume>, mix: {times: <n>, volume: <volume>}, discard: true|false, tips: fresh|reuse}
    Each start well begins a chain: move `volume` to the next well in `direction`, mix, repeat
    `steps` times. discard (default true) throws away `volume` from the last well. tips
    defaults to fresh (a new tip for every move down the chain); reuse keeps one per chain.
    The wells being diluted into must already hold diluent: add that with a transfer first.
    mix, discard and tips are optional.
- normalize: {from: <labware>, to: <labware>, diluent: <one well>, target: <concentration>, final_volume: <volume>, mix: {times: <n>, volume: <volume>}}
    Brings every sample listed in the samples file to `target` in `final_volume`, in the same
    well of `to`: diluent first, then sample. steadyhand works both volumes out from the file, so
    never copy concentrations into the protocol. `from` and `to` are labware names, not wells.
    Needs the `samples` section, and the samples declared under `liquids` like any other
    liquid. mix is optional.
- wait: {duration: <time>}

EXAMPLE 1 (for a text that states every plate, volume and mix)
steadyhand: 0.1
name: Two-fold serial dilution across a 96-well plate
labware:
  plate:     {type: Cor_96_wellplate_360ul_Fb}
  reservoir: {type: nest_1_troughplate_195000uL_Vb}
liquids:
  buffer: {in: reservoir/A1, volume: 20 mL}
  sample: {in: plate/A1:H1, volume: 200 uL}
steps:
  - transfer: {from: reservoir/A1, to: plate/A2:H12, volume: 100 uL, tips: reuse}
  - serial_dilution:
      start: plate/A1:H1
      steps: 11
      direction: right
      volume: 100 uL
      mix: {times: 3, volume: 80 uL}

EXAMPLE 2 (for the text: "wash the 8 samples in column 1 once with buffer, 1 mL plate")
steadyhand: 0.1
name: One wash of column 1
notes:
  - The text does not name the plate, so a 2 mL deep-well plate was chosen to hold 1 mL wells.
  - The wash volume is not stated; 500 uL was chosen.
  - The text does not say how long to leave the buffer on; 1 min was chosen.
labware:
  plate:  {type: Cor_96_wellplate_2mL_Vb}
  trough: {type: nest_1_troughplate_195000uL_Vb}
liquids:
  sample: {in: plate/A1:H1, volume: 1 mL}
  wash:   {in: trough/A1, volume: 5 mL}
steps:
  - transfer: {from: plate/A1:H1, to: waste, volume: 1 mL}
  - transfer: {from: trough/A1, to: plate/A1:H1, volume: 500 uL}
  - wait: {duration: 1 min}
  - transfer: {from: plate/A1:H1, to: waste, volume: 500 uL}
"""


# The plates the guide's examples use, and the same or the nearest one in Opentrons' library.
_OPENTRONS_EXAMPLES = (
  ("Cor_96_wellplate_360ul_Fb", "corning_96_wellplate_360ul_flat"),
  ("nest_1_troughplate_195000uL_Vb", "nest_1_reservoir_195ml"),
  ("Cor_96_wellplate_2mL_Vb", "nest_96_wellplate_2ml_deep"),
)


def guide_for(robot: str = "") -> str:
  """The guide a model is given: the Hamilton's as it stands, or one that names an Opentrons robot.

  For an Opentrons robot the examples use Opentrons labware and every file carries a `robot` line.
  """
  if not robot or robot == "hamilton-starlet":
    return GUIDE
  text = GUIDE
  swaps = list(_OPENTRONS_EXAMPLES) + [
    ("name: <title>            (required)\n", f"name: <title>            (required)\nrobot: {robot}   (required, exactly this)\n"),
    (
      "name: Two-fold serial dilution across a 96-well plate\n",
      f"name: Two-fold serial dilution across a 96-well plate\nrobot: {robot}\n",
    ),
    ("name: One wash of column 1\n", f"name: One wash of column 1\nrobot: {robot}\n"),
  ]
  for old, new in swaps:
    if old not in text:
      raise ValueError(f"the guide no longer contains {old!r}")
    text = text.replace(old, new)
  return text


def labware_catalogue(robot: str = "") -> str:
  """Every plate a draft may name for the robot, one per line, with its shape and well capacity.

  For the Hamilton these are the PyLabRobot plates its carrier holds; for an Opentrons robot,
  the plates and reservoirs Opentrons ships.
  """
  import inspect

  if robot and robot != "hamilton-starlet":
    from .opentrons_robots import catalogue

    return catalogue()

  import pylabrobot.resources as resources
  from pylabrobot.resources import Plate

  lines = []
  seen = set()
  for name in sorted(dir(resources)):
    maker = getattr(resources, name)
    if not inspect.isfunction(maker) or list(inspect.signature(maker).parameters)[:1] != ["name"]:
      continue
    try:
      with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plate = maker(name="probe")
    except Exception:
      continue
    if not isinstance(plate, Plate) or name.lower() in seen or carrier_refusal(name):
      continue  # not a plate, a second spelling of one, or one the deck's carrier cannot hold
    seen.add(name.lower())  # some definitions exist under two spellings; one is enough
    wells = plate.get_all_items()
    if wells[0].max_volume < 1.0:
      continue  # under 1 uL a well is a mistake in the definition, not a plate to offer
    lines.append(
      f"{name}: {len(wells)} wells ({plate.num_items_y} rows x {plate.num_items_x} columns), "
      f"{wells[0].max_volume:g} uL each"
    )
  return "\n".join(lines)


def extract_yaml(reply: str) -> str:
  """The YAML in a model's reply, with any code fence or surrounding chatter removed."""
  fenced = re.search(r"```(?:yaml|yml)?\s*\n(.*?)```", reply, flags=re.DOTALL)
  if fenced:
    return fenced.group(1).strip() + "\n"
  start = re.search(r"^steadyhand\s*:", reply, flags=re.MULTILINE)
  return (reply[start.start() :] if start else reply).strip() + "\n"


@dataclass
class Draft:
  text: str  # the protocol file as last written by the model
  checked: Optional[Check]  # None when the file could not even be read
  problems: List[Problem]
  rounds: int  # how many times the model was asked
  messages: List[Message] = field(default_factory=list, repr=False)
  history: List[List[Problem]] = field(default_factory=list, repr=False)  # the problems found after each round
  left_for_a_person: bool = False  # the model sent the same file back: it will not change what the text says

  @property
  def ok(self) -> bool:
    return self.checked is not None and not self.problems


def _problems_of(text: str, base: Optional[Path], robot: str = "") -> tuple:
  try:
    protocol = loads(text, base=base)
  except ProtocolError as error:
    return None, list(error.problems)
  checked = check(protocol)
  problems = list(checked.problems)
  if robot and robot != "hamilton-starlet" and protocol.robot != robot:
    # Without the line the file would be planned for the Hamilton, which lacks this labware.
    problems.append(Problem("robot", f"the file must say `robot: {robot}` after its name"))
  return checked, problems


MAX_SOURCE = 60_000  # characters; a whole kit manual is more than a model needs and reads worse


class SourceError(ValueError):
  """The text to draft from could not be read."""


def pages_from(spec: str, count: int) -> List[int]:
  """Page numbers, counted from 1, named by a spec such as "3-5,8"."""
  wanted: List[int] = []
  for part in spec.split(","):
    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
    if match is None:
      raise SourceError(f"cannot read pages {spec!r}; write them like 3-5,8")
    first, last = int(match.group(1)), int(match.group(2) or match.group(1))
    if not 1 <= first <= last <= count:
      raise SourceError(f"pages {part.strip()} are not in a document of {count} pages")
    wanted += [n for n in range(first, last + 1) if n not in wanted]
  return wanted


def read_source(path: Path, pages: Optional[str] = None) -> str:
  """The text of a notes file or of a PDF, ready to draft from.

  A PDF needs the `pypdf` package (`pip install steadyhand[pdf]`). Its text is taken as the file
  stores it: tables come out as runs of words, and a scanned page has no text at all. Give
  `pages` to send only the pages with the protocol on them.
  """
  path = Path(path)
  if path.suffix.lower() != ".pdf":
    if pages:
      raise SourceError("--pages only applies to a PDF")
    return path.read_text(encoding="utf-8")
  try:
    from pypdf import PdfReader
  except ImportError as error:
    raise SourceError("reading a PDF needs the pypdf package: pip install steadyhand[pdf]") from error
  try:
    reader = PdfReader(str(path))
    numbers = pages_from(pages, len(reader.pages)) if pages else list(range(1, len(reader.pages) + 1))
    texts = [(n, (reader.pages[n - 1].extract_text() or "").strip()) for n in numbers]
  except SourceError:
    raise
  except Exception as error:  # pypdf raises many kinds of error on a damaged file
    raise SourceError(f"cannot read {path.name} as a PDF: {error}") from error
  empty = [n for n, text in texts if not text]
  if len(empty) == len(texts):
    raise SourceError(f"{path.name} has no text on {'those pages' if pages else 'any page'}; a scanned PDF needs OCR first")
  text = "\n\n".join(f"[page {n}]\n{text}" for n, text in texts if text)
  if len(text) > MAX_SOURCE:
    raise SourceError(
      f"{path.name} gives {len(text):,} characters from {len(texts)} pages, more than the {MAX_SOURCE:,} steadyhand sends; "
      "name the pages with the protocol on them, for example --pages 4-6"
    )
  return text


def describe_samples(path: Path, rows: int = 4) -> str:
  """What a model needs to know about a samples file: its name, its columns and its first rows.

  The model is shown a few rows so it can tell which column is which and in what unit; the
  protocol it writes names the file, and steadyhand reads the numbers from the file itself.
  """
  with Path(path).open(newline="", encoding="utf-8") as handle:
    table = list(csv.reader(handle))
  header, body = (table[0], table[1:]) if table else ([], [])
  lines = [
    f"A samples file is offered with this text. Its name is {Path(path).name}, it has {len(body)} rows, "
    f"and its columns are: {', '.join(header)}.",
    "Its first rows:",
    *[", ".join(row) for row in [header] + body[:rows]],
  ]
  return "\n".join(lines)


def messages_for(source: str, samples: Optional[Path] = None, robot: str = "") -> List[Message]:
  """The conversation a model is sent first: the guide and the text, with any samples file described."""
  offered = "\n" + describe_samples(samples) + "\n" if samples is not None else ""
  return [
    {"role": "system", "content": guide_for(robot) + "\nLABWARE\n" + labware_catalogue(robot) + "\n"},
    {"role": "user", "content": "Write the steadyhand protocol file for this:\n\n" + source.strip() + "\n" + offered},
  ]


def draft(
  source: str,
  model: Model,
  *,
  base: Optional[Path] = None,
  samples: Optional[Path] = None,
  max_rounds: int = 3,
  robot: str = "",
) -> Draft:
  """Ask `model` to write a protocol for `source`, sending problems back until it checks out.

  Args:
    source: the plain text to turn into a protocol.
    model: a function from a list of messages to the model's reply.
    base: folder to resolve a samples file against, if the protocol names one. Defaults to the
      folder `samples` is in.
    samples: a CSV of per-sample concentrations to offer the model, for `normalize` steps.
    max_rounds: how many times the model may be asked before giving up.
    robot: the robot to draft for. It decides which labware the model is offered; left empty,
      the Hamilton STARlet's.
  """
  if base is None and samples is not None:
    base = Path(samples).parent
  messages = messages_for(source, samples, robot)
  text, checked, problems = "", None, [Problem("draft", "the model was never asked")]
  history: List[List[Problem]] = []
  previous = ""
  for round_number in range(1, max_rounds + 1):
    reply = model(messages)
    text = extract_yaml(reply)
    checked, problems = _problems_of(text, base, robot)
    messages.append({"role": "assistant", "content": reply})
    history.append(list(problems))
    if not problems:
      return Draft(text, checked, [], round_number, messages, history)
    if text.strip() == previous.strip():
      # The same file again is the model's way of saying the problem is in the text, not the file.
      return Draft(text, checked, problems, round_number, messages, history, left_for_a_person=True)
    previous = text
    messages.append({"role": "user", "content": feedback(problems)})
  return Draft(text, checked, problems, max_rounds, messages, history)


def feedback(problems: Sequence[Problem]) -> str:
  """What the model is told when the file it wrote does not hold up."""
  listed = "\n".join(f"- {problem}" for problem in problems)
  return (
    "That file has these problems:\n" + listed + "\n\nWrite the whole file again with them fixed. "
    "If a problem can only be fixed by changing something the text states, or by something only a "
    "person can supply, send the same file again instead. Reply with the YAML only."
  )


# ---------------------------------------------------------------- ready-made models


class ModelError(RuntimeError):
  """The model could not be reached or gave nothing usable."""


def command_model(command: str, *, timeout: float = 300.0) -> Model:
  """A model that is a shell command: the conversation goes in on stdin, the reply comes out on stdout.

  Works with any command-line tool that answers a prompt, for example a local model runner.
  """

  def ask(messages: List[Message]) -> str:
    prompt = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages)
    # On Windows, keep backslashes in paths and let .cmd and .bat launchers be found by name.
    argv = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
      argv = [part.strip('"') for part in argv]
    argv[0] = shutil.which(argv[0]) or argv[0]
    try:
      done = subprocess.run(
        argv, input=prompt, capture_output=True, text=True, timeout=timeout, check=False, encoding="utf-8"
      )
    except (OSError, subprocess.TimeoutExpired) as error:
      raise ModelError(f"could not run {command!r}: {error}") from error
    if done.returncode != 0:
      # Some tools print their error on stdout, so fall back to it when stderr is empty.
      said = done.stderr.strip() or done.stdout.strip() or "it printed nothing"
      raise ModelError(f"{command!r} exited with status {done.returncode}: {said[:300]}")
    return done.stdout

  return ask


def _post(url: str, headers: Dict[str, str], body: dict, timeout: float) -> dict:
  request = urllib.request.Request(
    url, data=json.dumps(body).encode(), headers={"content-type": "application/json", **headers}, method="POST"
  )
  try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
      return json.loads(response.read().decode())
  except urllib.error.HTTPError as error:
    detail = error.read().decode(errors="replace")[:300]
    raise ModelError(f"{url} answered {error.code}: {detail}") from error
  except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
    raise ModelError(f"could not reach {url}: {error}") from error


def anthropic_model(
  name: str,
  *,
  api_key: Optional[str] = None,
  base_url: str = "https://api.anthropic.com",
  max_tokens: int = 8000,
  timeout: float = 300.0,
) -> Model:
  """A model served by the Anthropic Messages API. The key comes from ANTHROPIC_API_KEY if not given."""
  key = api_key or os.environ.get("ANTHROPIC_API_KEY")
  if not key:
    raise ModelError("set ANTHROPIC_API_KEY to use an Anthropic model")

  def ask(messages: List[Message]) -> str:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    reply = _post(
      base_url.rstrip("/") + "/v1/messages",
      {"x-api-key": key, "anthropic-version": "2023-06-01"},
      {"model": name, "max_tokens": max_tokens, "system": system, "messages": turns},
      timeout,
    )
    try:
      return "".join(block["text"] for block in reply["content"] if block.get("type") == "text")
    except (KeyError, TypeError) as error:
      raise ModelError(f"unexpected reply from the Anthropic API: {str(reply)[:300]}") from error

  return ask


def openai_model(
  name: str,
  *,
  api_key: Optional[str] = None,
  base_url: Optional[str] = None,
  timeout: float = 300.0,
) -> Model:
  """A model behind any OpenAI-compatible chat API, including local servers.

  The key comes from OPENAI_API_KEY and the address from OPENAI_BASE_URL when not given.
  """
  key = api_key or os.environ.get("OPENAI_API_KEY", "")
  url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

  def ask(messages: List[Message]) -> str:
    headers = {"authorization": f"Bearer {key}"} if key else {}
    reply = _post(url + "/chat/completions", headers, {"model": name, "messages": messages}, timeout)
    try:
      return reply["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
      raise ModelError(f"unexpected reply from {url}: {str(reply)[:300]}") from error

  return ask
