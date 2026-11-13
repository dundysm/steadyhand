"""Draft a protocol file from plain text with a language model.

This is the only place drybench uses a model. The model reads notes, a kit manual or a
sentence and writes a protocol file. drybench then reads that file exactly as it would read
one written by hand; if it does not hold up, the problems go back to the model for another
try. Nothing the model writes reaches a plan or a robot without passing `check`.

A model here is any function that takes a list of messages and returns text. Three ready-made
ones are provided: a shell command, the Anthropic API and any OpenAI-compatible API.
"""

from __future__ import annotations

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
from typing import Callable, Dict, List, Optional

from .planner import carrier_refusal
from .protocol import Check, Problem, ProtocolError, check, loads

Message = Dict[str, str]  # {"role": "system" | "user" | "assistant", "content": ...}
Model = Callable[[List[Message]], str]

GUIDE = """\
You write protocol files for drybench, a tool that checks and rehearses liquid-handling
protocols. Read the text the user gives you and write the protocol it describes.

Reply with one YAML document and nothing else.

RULES
- Every amount carries a unit: "100 uL", "20 mL", "5 min", "10 ng/uL". Never a bare number.
- Use only the fields listed below. Any other field is an error.
- Wells are written labware/well, such as plate/A1. A range such as plate/A1:H1 runs from its
  top-left well to its bottom-right well. On a 96-well plate, A1:H1 is column 1 (8 wells) and
  A1:A12 is row A (12 wells).
- Declare under `liquids` every liquid that is in a well before the first step, whether the
  steps draw from it, add to it or mix it, with the wells it starts in and the volume in each.
  Use the volume the text gives. When it gives none, supply about 20% more than the steps use.
- Labware types must come from the LABWARE list, spelled exactly. When the text does not name
  the labware, choose one whose wells hold the largest volume any well reaches.
- To throw liquid away, transfer it `to: waste`. Waste is not labware: do not declare it.
- There are no loops. Write a repeated action out as repeated steps.
- Do not invent steps the text does not describe.
- Leave out what a pipetting robot cannot do (vortexing, a magnet, heating, sealing, storage)
  and say so in `notes`, one sentence each. A timed hold becomes a `wait`.
- When the text leaves out something you need (a volume, a plate type, where a reagent
  starts), choose the most conventional option and record that choice as one sentence under
  `notes`. Every choice you made that the text did not state must appear there. A mix volume
  the text does not give is about two thirds of what the well holds at that point.
- When the text asks for something the format cannot say exactly (such as new tips per
  column), use the nearest stricter option and say so in `notes`.
- Never change an amount the text states. If what the text describes cannot work (a well
  would overflow, a source would run dry), write it as stated and say so in `notes`. If you
  are then told about that problem, send the same file again; a person has to decide.

SECTIONS
drybench: 0.1            (required, exactly this)
name: <title>            (required)
description: <text>      (optional)
notes: [<sentence>, ...] (optional; see above)
labware:                 (required) one entry per plate or reservoir
  <name>: {type: <definition from LABWARE>}
liquids:                 (optional)
  <name>: {in: <wells>, volume: <volume in each well>}
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
- wait: {duration: <time>}

EXAMPLE 1
drybench: 0.1
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
drybench: 0.1
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


def labware_catalogue() -> str:
  """Every PyLabRobot plate the deck can hold, one per line, with its shape and well capacity."""
  import inspect

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
  start = re.search(r"^drybench\s*:", reply, flags=re.MULTILINE)
  return (reply[start.start() :] if start else reply).strip() + "\n"


@dataclass
class Draft:
  text: str  # the protocol file as last written by the model
  checked: Optional[Check]  # None when the file could not even be read
  problems: List[Problem]
  rounds: int  # how many times the model was asked
  messages: List[Message] = field(default_factory=list, repr=False)
  history: List[List[Problem]] = field(default_factory=list, repr=False)  # the problems found after each round

  @property
  def ok(self) -> bool:
    return self.checked is not None and not self.problems


def _problems_of(text: str, base: Optional[Path]) -> tuple:
  try:
    protocol = loads(text, base=base)
  except ProtocolError as error:
    return None, list(error.problems)
  checked = check(protocol)
  return checked, list(checked.problems)


def draft(source: str, model: Model, *, base: Optional[Path] = None, max_rounds: int = 3) -> Draft:
  """Ask `model` to write a protocol for `source`, sending problems back until it checks out.

  Args:
    source: the plain text to turn into a protocol.
    model: a function from a list of messages to the model's reply.
    base: folder to resolve a samples file against, if the protocol names one.
    max_rounds: how many times the model may be asked before giving up.
  """
  messages: List[Message] = [
    {"role": "system", "content": GUIDE + "\nLABWARE\n" + labware_catalogue() + "\n"},
    {"role": "user", "content": "Write the drybench protocol file for this:\n\n" + source.strip() + "\n"},
  ]
  text, checked, problems = "", None, [Problem("draft", "the model was never asked")]
  history: List[List[Problem]] = []
  for round_number in range(1, max_rounds + 1):
    reply = model(messages)
    text = extract_yaml(reply)
    checked, problems = _problems_of(text, base)
    messages.append({"role": "assistant", "content": reply})
    history.append(list(problems))
    if not problems:
      return Draft(text, checked, [], round_number, messages, history)
    listed = "\n".join(f"- {problem}" for problem in problems)
    messages.append(
      {
        "role": "user",
        "content": "That file has these problems:\n" + listed + "\n\nWrite the whole file again with them fixed. "
        "Reply with the YAML only.",
      }
    )
  return Draft(text, checked, problems, max_rounds, messages, history)


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
