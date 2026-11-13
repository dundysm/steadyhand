"""Write a rehearsal as one HTML file that plays it back.

The file needs nothing else: no network, no server, no install. It draws the deck from above
and a cross-section through the wells being worked on, and steps through every command with
the liquid moving and each collision marked where it happened.

What it draws is the rehearsal's own data, with two simplifications. Liquid height is drawn in
proportion to volume, and a well is drawn as the box the physics scene uses for it. Timing is
schematic: every command takes the same time on screen.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Dict, List

from pylabrobot.resources import Container, Resource, TipSpot

from .scene import bounds, cavity_floor_z, collect_boxes, is_cavity

if TYPE_CHECKING:
  from .replay import Rehearsal


def layout(root: Resource) -> dict:
  """Where every solid and every cavity under `root` is, as plain numbers for the viewer.

  Call it after the run: tip spots and wells are read in their final state, and the viewer
  works backwards from the recorded steps to how they started.
  """
  solids = [
    [round(v, 2) for v in (box.lo[0], box.lo[1], box.hi[0], box.hi[1], box.lo[2], box.hi[2])] + [box.colour, box.resource]
    for box in collect_boxes(root)
    if box.kind == "solid"
  ]
  cavities: Dict[str, dict] = {}

  def walk(resource: Resource) -> None:
    if is_cavity(resource):
      lo, hi = bounds(resource)
      parent = resource.parent
      entry = {
        "box": [round(v, 2) for v in (lo[0], lo[1], hi[0], hi[1])],
        "floor": round(cavity_floor_z(resource), 2),
        "top": round(hi[2], 2),
        "parent": parent.name if parent is not None else "",
        "id": getattr(resource, "get_identifier", lambda: resource.name)(),
      }
      if isinstance(resource, TipSpot):
        has = bool(resource.tracker.has_tip)
        entry.update(kind="tip", has=has, length=0.0)
        if has:
          try:
            entry["length"] = round(float(resource.tracker.get_tip().total_tip_length), 2)
          except Exception:
            pass
      elif isinstance(resource, Container):
        entry.update(
          kind="well",
          max=round(float(getattr(resource, "max_volume", 0.0) or 0.0), 3),
          volume=round(float(resource.tracker.get_used_volume()), 4),
        )
      cavities[resource.name] = entry
    for child in resource.children:
      walk(child)

  walk(root)
  return {"solids": solids, "cavities": cavities}


def replay_data(rehearsal: "Rehearsal", *, title: str = "") -> dict:
  """Everything the viewer needs, as one JSON-ready dictionary."""
  commands: List[dict] = []
  index_of: Dict[int, int] = {}
  for step in rehearsal.steps:
    if not step.simulated or step.reference is None:
      continue
    if step.command not in index_of:
      index_of[step.command] = len(commands)
      commands.append({"kind": step.kind, "channels": []})
    commands[index_of[step.command]]["channels"].append(
      [
        step.channel,
        round(step.reference[0], 2),
        round(step.reference[1], 2),
        round(step.reference[2], 2),
        round(step.reach, 2),
        step.resource,
        round(step.volume, 4) if step.volume is not None else None,
      ]
    )
  by_index = {step.index: step for step in rehearsal.steps}
  cavity_parent = {name: c["parent"] for name, c in rehearsal.layout.get("cavities", {}).items()}
  collisions = [
    {
      "command": index_of.get(by_index[c.step].command, 0),
      "channel": c.channel,
      "kind": c.kind,
      "part": c.part,
      "resource": c.resource,
      "depth": c.depth,
      "phase": c.phase,
      "at": list(c.at),
    }
    for c in rehearsal.collisions
    if c.step in by_index
  ]
  return {
    "title": title,
    "ok": rehearsal.ok,
    "traverse": rehearsal.traverse_z,
    "steps": len(rehearsal.steps),
    "skipped": len(rehearsal.not_rehearsed),
    "path_m": round(rehearsal.path_length / 1000.0, 2),
    "commands": commands,
    "collisions": collisions,
    "liquid": [
      {
        "command": index_of.get(by_index[i.step].command, 0),
        "channel": i.channel,
        "labware": cavity_parent.get(i.resource, i.resource),
        "text": i.describe().split(": ", 1)[1],
      }
      for i in rehearsal.liquid_failures
      if i.step in by_index
    ],
    **rehearsal.layout,
  }


def replay_html(rehearsal: "Rehearsal", *, title: str = "") -> str:
  """The rehearsal as a self-contained HTML page."""
  data = json.dumps(replay_data(rehearsal, title=title), separators=(",", ":"))
  # "</" inside a script block would end it early; JSON allows the escaped form.
  return _PAGE.replace("__TITLE__", _escape(title or "drybench replay")).replace("__DATA__", data.replace("</", "<\\/"))


def _escape(text: str) -> str:
  return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #f6f5f1; --panel: #ffffff; --ink: #1d1f23; --soft: #6b6f76; --line: #d9d7d0;
    --deck: #c9ccd1; --carrier: #8e949c; --plate: #f3f1e7; --rack: #7da6cf; --other: #c2b59b;
    --well: #ffffff; --liquid: #2f8fe0; --tip: #9aa1a9; --channel: #1d1f23; --active: #e08a00;
    --pass: #1f8a4c; --fail: #c8322b; --hit: #c8322b;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #17181b; --panel: #202226; --ink: #e9e8e4; --soft: #9a9ea6; --line: #34373d;
      --deck: #2b2e33; --carrier: #4a4f57; --plate: #5d5c55; --rack: #2f5d8a; --other: #5e5646;
      --well: #26282c; --liquid: #4aa8ff; --tip: #b9bfc7; --channel: #e9e8e4; --active: #ffb020;
      --pass: #4cc47e; --fail: #ff6b63; --hit: #ff6b63;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 1180px; margin: 0 auto; padding: 18px 18px 28px; }
  header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 14px; margin-bottom: 12px; }
  h1 { font-size: 19px; font-weight: 650; margin: 0; }
  .badge { font-weight: 700; font-size: 12px; letter-spacing: .04em; padding: 2px 9px; border-radius: 10px; color: #fff; }
  .badge.pass { background: var(--pass); } .badge.fail { background: var(--fail); }
  .facts { color: var(--soft); font-variant-numeric: tabular-nums; }
  .views { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 12px; align-items: start; }
  @media (max-width: 820px) { .views { grid-template-columns: 1fr; } }
  figure { margin: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px; }
  figcaption { color: var(--soft); font-size: 12px; margin-bottom: 6px; display: flex; justify-content: space-between; gap: 8px; }
  canvas { display: block; width: 100%; }
  .bar { margin-top: 12px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
  .controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  button, select { font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 4px 10px; cursor: pointer; }
  button:hover { border-color: var(--soft); }
  #play { min-width: 64px; font-weight: 600; }
  #seek { flex: 1 1 180px; min-width: 0; accent-color: var(--active); }
  #marks { height: 8px; margin: 0 0 2px; }
  #now { margin-top: 8px; font-variant-numeric: tabular-nums; min-height: 3em; }
  #now b { font-weight: 650; }
  #now .hit { color: var(--hit); font-weight: 600; }
  .count { color: var(--soft); font-variant-numeric: tabular-nums; white-space: nowrap; }
  #hits { margin: 12px 0 0; padding: 0; list-style: none; }
  #hits li { padding: 5px 8px; border-left: 3px solid var(--hit); background: var(--panel); margin-bottom: 4px; cursor: pointer; border-radius: 0 6px 6px 0; }
  #hits li:hover { outline: 1px solid var(--line); }
  h2 { font-size: 14px; margin: 16px 0 6px; }
  footer { color: var(--soft); font-size: 12px; margin-top: 14px; }
</style>
</head>
<body>
<main>
  <header>
    <h1 id="title"></h1>
    <span id="badge" class="badge"></span>
    <span id="facts" class="facts"></span>
  </header>
  <div class="views">
    <figure>
      <figcaption><span>Deck from above (back of the robot at the top)</span><span>rings are channels</span></figcaption>
      <canvas id="top"></canvas>
    </figure>
    <figure>
      <figcaption><span id="sidecap">Cross-section</span><span>mm</span></figcaption>
      <canvas id="side"></canvas>
    </figure>
  </div>
  <div class="bar">
    <canvas id="marks"></canvas>
    <div class="controls">
      <button id="prev" title="Previous command (left arrow)">&#9664;</button>
      <button id="play" title="Play or pause (space)">Play</button>
      <button id="next" title="Next command (right arrow)">&#9654;</button>
      <input id="seek" type="range" min="0" step="1" value="0" aria-label="Position in the run">
      <span id="count" class="count"></span>
      <select id="speed" aria-label="Speed">
        <option value="1">1 command/s</option><option value="3" selected>3 commands/s</option>
        <option value="8">8 commands/s</option><option value="25">25 commands/s</option>
      </select>
    </div>
    <div id="now"></div>
  </div>
  <div id="hitbox"></div>
  <footer>Written by drybench. Liquid height is drawn in proportion to volume, wells as the boxes the physics scene uses, and every command takes the same time on screen.</footer>
</main>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const N = D.commands.length, SUB = 100;

// ---- how the deck started: undo every recorded step from its final state
const cav = D.cavities;
const startVolume = {}, startTip = {};
for (const [name, c] of Object.entries(cav)) {
  if (c.kind === "well") startVolume[name] = c.volume; else startTip[name] = c.has;
}
const tipLength = {};
for (const command of D.commands) for (const ch of command.channels) {
  const [, , , , reach, name, volume] = ch;
  if (!(name in cav)) continue;
  if (command.kind === "aspirate") startVolume[name] += volume || 0;
  if (command.kind === "dispense") startVolume[name] -= volume || 0;
  if (command.kind === "pick_up_tip") { startTip[name] = true; tipLength[name] = reach; }
}
for (const name in startVolume) startVolume[name] = Math.max(0, startVolume[name]);
// a tip that was picked up and dropped back keeps its place; one dropped into an empty spot leaves it empty at the start
for (const command of D.commands) if (command.kind === "drop_tip")
  for (const ch of command.channels) if (ch[5] in startTip && !(ch[5] in tipLength)) startTip[ch[5]] = false;

// ---- state at a moment t in [0, N]: whole part = commands finished, fraction = progress in the next
const channelsUsed = [...new Set(D.commands.flatMap(c => c.channels.map(ch => ch[0])))].sort((a, b) => a - b);
function stateAt(t) {
  const done = Math.min(N, Math.floor(t)), part = t - done;
  const volume = {...startVolume}, tip = {...startTip};
  const chan = {};
  for (const c of channelsUsed) chan[c] = {x: null, y: null, z: null, reach: 0, held: 0, active: false};
  for (const command of D.commands) for (const ch of command.channels)   // park each above its first target
    if (chan[ch[0]].x === null) { chan[ch[0]].x = ch[1]; chan[ch[0]].y = ch[2]; }
  const apply = command => {
    for (const [c, x, y, z, reach, name, vol] of command.channels) {
      const s = chan[c];
      s.x = x; s.y = y;
      if (command.kind === "pick_up_tip") {
        // picking from a spot that is already empty means the racks were swapped for full ones in between
        if (name in tip && !tip[name]) for (const other in tip) if (cav[other].parent === cav[name].parent) tip[other] = true;
        s.reach = reach; if (name in tip) tip[name] = false;
      }
      else if (command.kind === "drop_tip") { s.reach = 0; s.held = 0; if (name in tip) tip[name] = true; }
      else if (command.kind === "aspirate") { s.held += vol || 0; if (name in volume) volume[name] -= vol || 0; }
      else if (command.kind === "dispense") { s.held = Math.max(0, s.held - (vol || 0)); if (name in volume) volume[name] += vol || 0; }
    }
  };
  for (let i = 0; i < done; i++) apply(D.commands[i]);
  for (const c of channelsUsed) chan[c].z = D.traverse + chan[c].reach;
  let current = null;
  if (done < N) {
    current = D.commands[done];
    const acted = part >= 0.7 - 1e-6;   // 0.7 into a command is the bottom of its move, where it acts
    const before = {};
    for (const ch of current.channels) before[ch[0]] = {...chan[ch[0]]};
    if (acted) apply(current);
    for (const [c, x, y, z, reach] of current.channels) {
      const s = chan[c], b = before[c];
      s.active = true;
      const carried = current.kind === "pick_up_tip" ? (acted ? reach : 0) : current.kind === "drop_tip" ? (acted ? 0 : b.reach) : b.reach;
      s.reach = carried;
      const cruise = D.traverse + (current.kind === "pick_up_tip" ? 0 : b.reach), after = D.traverse + carried;
      const ease = u => u * u * (3 - 2 * u);
      if (acted) { s.x = x; s.y = y; s.z = z + (after - z) * ease(Math.max(0, part - 0.7) / 0.3); }
      else if (part < 0.4) { const u = ease(part / 0.4); s.x = b.x + (x - b.x) * u; s.y = b.y + (y - b.y) * u; s.z = cruise; }
      else { s.x = x; s.y = y; s.z = cruise + (z - cruise) * ease((part - 0.4) / 0.3); }
    }
  }
  return {done, part, volume, tip, chan, current};
}

// ---- drawing
function fit(canvas, ratio) {
  const width = canvas.clientWidth, height = Math.round(width * ratio), scale = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * scale) || canvas.height !== Math.round(height * scale)) {
    canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale); canvas.style.height = height + "px";
  }
  const g = canvas.getContext("2d");
  g.setTransform(scale, 0, 0, scale, 0, 0);
  g.clearRect(0, 0, width, height);
  return [g, width, height];
}
const used = Object.values(cav);
const B = (() => {       // the labware the run touches or that holds liquid, and every place a channel goes
  const touched = new Set(D.commands.flatMap(c => c.channels.map(ch => cav[ch[5]] ? cav[ch[5]].parent : null)));
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  const grow = (a, b, c, d) => { x0 = Math.min(x0, a); y0 = Math.min(y0, b); x1 = Math.max(x1, c); y1 = Math.max(y1, d); };
  for (const [name, c] of Object.entries(cav)) if (touched.has(c.parent) || startVolume[name] > 0) grow(...c.box);
  for (const command of D.commands) for (const ch of command.channels) if (cav[ch[5]]) grow(ch[1] - 5, ch[2] - 5, ch[1] + 5, ch[2] + 5);
  if (x0 > x1) for (const c of used) grow(...c.box);
  if (x0 > x1) grow(0, 0, 100, 100);
  return [x0 - 18, y0 - 18, x1 + 18, y1 + 18];
})();
const solidsByHeight = D.solids.slice().sort((a, b) => a[5] - b[5]);
const colourOf = {deck: "--deck", carrier: "--carrier", plate: "--plate", tip_rack: "--rack", other: "--other"};

function drawTop(state) {
  const ratio = (B[3] - B[1]) / (B[2] - B[0]);
  const [g, width, height] = fit($("top"), Math.min(1.3, Math.max(0.62, ratio)));
  const k = Math.min(width / (B[2] - B[0]), height / (B[3] - B[1]));
  const ox = (width - k * (B[2] - B[0])) / 2, oy = (height - k * (B[3] - B[1])) / 2;
  const X = x => ox + (x - B[0]) * k, Y = y => height - oy - (y - B[1]) * k;
  g.fillStyle = css("--deck"); g.fillRect(0, 0, width, height);
  for (const s of solidsByHeight) {
    if (s[6] === "deck") continue;
    g.fillStyle = css(colourOf[s[6]] || "--other");
    g.fillRect(X(s[0]), Y(s[3]), (s[2] - s[0]) * k, (s[3] - s[1]) * k);
  }
  const liquid = css("--liquid"), well = css("--well"), tipColour = css("--tip");
  for (const [name, c] of Object.entries(cav)) {
    const x = X(c.box[0]), y = Y(c.box[3]), w = (c.box[2] - c.box[0]) * k, h = (c.box[3] - c.box[1]) * k;
    if (c.kind === "well") {
      g.fillStyle = well; g.fillRect(x, y, w, h);
      const fill = c.max > 0 ? Math.min(1, Math.max(0, state.volume[name] / c.max)) : 0;
      if (fill > 0.0005) { g.globalAlpha = 0.25 + 0.75 * fill; g.fillStyle = liquid; g.fillRect(x, y, w, h); g.globalAlpha = 1; }
    } else {
      g.fillStyle = well; g.beginPath(); g.arc(x + w / 2, y + h / 2, Math.min(w, h) * 0.42, 0, 7); g.fill();
      if (state.tip[name]) { g.fillStyle = tipColour; g.beginPath(); g.arc(x + w / 2, y + h / 2, Math.min(w, h) * 0.26, 0, 7); g.fill(); }
    }
  }
  const hit = css("--hit");
  g.strokeStyle = hit; g.lineWidth = 2;
  for (const c of D.collisions) {
    if (c.command > state.done) continue;
    const x = X(c.at[0]), y = Y(c.at[1]);
    g.beginPath(); g.moveTo(x - 6, y - 6); g.lineTo(x + 6, y + 6); g.moveTo(x + 6, y - 6); g.lineTo(x - 6, y + 6); g.stroke();
  }
  const ink = css("--channel"), active = css("--active");
  for (const c of channelsUsed) {
    const s = state.chan[c];
    if (s.x === null) continue;
    const r = Math.max(3.2, 3.6 * k);
    g.beginPath(); g.arc(X(s.x), Y(s.y), r, 0, 7);
    g.fillStyle = s.held > 0 ? liquid : (s.reach > 0 ? tipColour : "transparent"); g.fill();
    g.lineWidth = s.active ? 2.4 : 1.4; g.strokeStyle = s.active ? active : ink; g.stroke();
  }
}

function drawSide(state) {
  const [g, width, height] = fit($("side"), 0.78);
  const command = state.current || D.commands[N - 1];
  if (!command) return;
  const first = command.channels[0], target = cav[first[5]];
  let labware = null;
  if (target) labware = target.parent;
  // the wells in the target's column; the slice itself is at the channels' x, which a bad offset can put over a wall
  const column = Object.entries(cav).filter(([, c]) => target && c.parent === labware && c.box[0] < target.box[2] - 0.01 && target.box[0] < c.box[2] - 0.01);
  const off = target ? (first[1] < target.box[0] - 0.01 ? first[1] - target.box[0] : first[1] > target.box[2] + 0.01 ? first[1] - target.box[2] : 0) : 0;
  const ys = command.channels.map(ch => ch[2]);
  let y0 = Math.min(...ys) - 12, y1 = Math.max(...ys) + 12, floor = first[3] - first[4] - 5, top = floor + 30;
  if (column.length) {
    y0 = Math.min(...column.map(([, c]) => c.box[1])) - 6; y1 = Math.max(...column.map(([, c]) => c.box[3])) + 6;
    floor = Math.min(...column.map(([, c]) => c.floor)); top = Math.max(...column.map(([, c]) => c.top));
  }
  const k = Math.min((width - 46) / (y1 - y0), 9);
  const z0 = floor - 4, z1 = z0 + (height - 14) / k;
  const left = 40 + (width - 46 - k * (y1 - y0)) / 2;
  const Yp = y => left + (y1 - y) * k;          // row A (the back) on the left
  const Z = z => height - 8 - (z - z0) * k;
  const ink = css("--ink"), soft = css("--soft"), line = css("--line"), liquid = css("--liquid"), tipColour = css("--tip"), active = css("--active");

  g.font = "11px system-ui, sans-serif"; g.fillStyle = soft; g.strokeStyle = line; g.lineWidth = 1; g.textAlign = "right"; g.textBaseline = "middle";
  const tick = (z1 - z0) > 60 ? 10 : 5;
  for (let z = floor; z <= z1; z += tick) {
    g.beginPath(); g.moveTo(34, Z(z) + 0.5); g.lineTo(width, Z(z) + 0.5); g.globalAlpha = 0.5; g.stroke(); g.globalAlpha = 1;
    g.fillText(String(Math.round(z - floor)), 30, Z(z));
  }
  if (off !== 0 && column.length) {      // over the wall: what is under the channels is solid up to the top of the labware
    const wall = Math.max(top, ...D.solids.filter(s => s[7] === labware).map(s => s[5]));
    g.fillStyle = soft; g.globalAlpha = 0.45; g.fillRect(Yp(y1 - 6), Z(wall), (y1 - y0 - 12) * k, (wall - floor) * k); g.globalAlpha = 1;
  }
  for (const [name, c] of column) {
    const a = Yp(c.box[3]), b = Yp(c.box[1]), w = b - a;
    if (off !== 0) g.setLineDash([3, 3]);
    if (off !== 0) { /* the wells are beside the slice: outline only */ }
    else if (c.kind === "well") {
      const fill = c.max > 0 ? Math.min(1, Math.max(0, state.volume[name] / c.max)) : 0;
      if (fill > 0.0005) { g.fillStyle = liquid; g.globalAlpha = 0.8; g.fillRect(a + 1, Z(c.floor + fill * (c.top - c.floor)), w - 2, fill * (c.top - c.floor) * k); g.globalAlpha = 1; }
    } else if (state.tip[name]) {
      const reach = tipLength[name] || c.length || 50;
      drawTip(g, (a + b) / 2, Z(c.floor + reach), Z(c.floor), tipColour, k, false);
    }
    g.strokeStyle = ink; g.lineWidth = 1.5; g.beginPath();
    g.moveTo(a + 0.5, Z(c.top)); g.lineTo(a + 0.5, Z(c.floor)); g.lineTo(b - 0.5, Z(c.floor)); g.lineTo(b - 0.5, Z(c.top)); g.stroke();
    g.setLineDash([]);
    if (w > 15) { g.fillStyle = soft; g.textAlign = "center"; g.textBaseline = "top"; g.fillText(c.id, (a + b) / 2, Z(c.floor) + 2 > height - 12 ? height - 12 : Z(c.floor) + 2); }
  }
  for (const ch of command.channels) {
    const s = state.chan[ch[0]];
    const x = Yp(s.y), nose = Z(s.z);
    if (s.reach > 0) drawTip(g, x, nose, Z(s.z - s.reach), s.held > 0 ? liquid : tipColour, k, s.held > 0);
    g.fillStyle = css("--channel"); g.fillRect(x - 3.2 * k / 2, nose - 400, 3.2 * k, 400);
    g.fillStyle = active; g.fillRect(x - 3.2 * k / 2, nose - 3, 3.2 * k, 3);
  }
  g.strokeStyle = css("--hit"); g.lineWidth = 2;
  for (const c of D.collisions) {
    if (c.command !== state.done || state.part < 0.4) continue;
    const reach = state.chan[c.channel] ? state.chan[c.channel].reach : 0;
    const x = Yp(c.at[1]), z = Z(c.at[2] - (c.part === "tip" ? reach : 0));
    g.beginPath(); g.arc(x, z, 7, 0, 7); g.stroke();
  }
  const what = target ? labware + (column.length && column[0][1].id ? ", column of " + column[0][1].id : "") : "no wells under the channels";
  const beside = off === 0 ? "" : ", " + Math.abs(Math.round(off * 10) / 10) + " mm outside the wells' " + (off > 0 ? "right" : "left") + " edge, over solid plate";
  $("sidecap").textContent = "Cross-section: " + what + beside + " (height above the well floor)";
}
function drawTip(g, x, zTop, zEnd, colour, k, full) {
  const wide = Math.max(2.2, 2.6 * k), thin = Math.max(0.8, 0.5 * k);
  g.beginPath(); g.moveTo(x - wide / 2, zTop); g.lineTo(x + wide / 2, zTop); g.lineTo(x + thin / 2, zEnd); g.lineTo(x - thin / 2, zEnd); g.closePath();
  g.fillStyle = colour; g.globalAlpha = full ? 0.95 : 0.8; g.fill(); g.globalAlpha = 1;
  g.strokeStyle = css("--ink"); g.lineWidth = 0.8; g.stroke();
}
function drawMarks() {
  const canvas = $("marks"), scale = window.devicePixelRatio || 1, g = canvas.getContext("2d");
  canvas.width = Math.round(canvas.clientWidth * scale); canvas.height = Math.round(8 * scale);
  g.setTransform(scale, 0, 0, scale, 0, 0);
  const seek = $("seek").getBoundingClientRect(), box = canvas.getBoundingClientRect();
  g.fillStyle = css("--hit");
  for (const c of grouped) g.fillRect(seek.left - box.left + 8 + (seek.width - 16) * (c.command + 0.7) / Math.max(1, N) - 1.5, 0, 3, 8);
}

// ---- words for the current command
const names = {pick_up_tip: "pick up tips", aspirate: "aspirate", dispense: "dispense", drop_tip: "drop tips"};
function describe(index) {
  if (index >= N) return "<b>End of the run.</b>";
  const command = D.commands[index], channels = command.channels;
  const where = channels.map(ch => cav[ch[5]] ? cav[ch[5]].id : ch[5]);
  const labware = [...new Set(channels.map(ch => cav[ch[5]] ? cav[ch[5]].parent : ch[5]))].join(", ");
  const wells = [...new Set(where)];
  const span = wells.length > 2 ? wells[0] + " to " + wells[wells.length - 1] : wells.join(", ");
  const volumes = [...new Set(channels.map(ch => ch[6]).filter(v => v !== null))];
  const amount = volumes.length === 0 ? "" : volumes.length === 1 ? ", " + volumes[0] + " uL each" : ", " + Math.min(...volumes) + " to " + Math.max(...volumes) + " uL";
  let text = "<b>" + (names[command.kind] || command.kind) + "</b> with " + channels.length + (channels.length === 1 ? " channel" : " channels") + " at " + labware + (labware === span ? "" : " " + span) + amount;
  for (const hit of grouped.filter(h => h.command === index)) text += "<br><span class='hit'>Stopped: " + hit.text + ".</span>";
  return text;
}
// collisions that differ only in the channel are told as one
const grouped = [];
for (const c of D.collisions) {
  const same = grouped.find(h => h.command === c.command && h.part === c.part && h.resource === c.resource && h.phase === c.phase);
  if (same) { same.channels.push(c.channel); same.depth = Math.max(same.depth, c.depth); }
  else grouped.push({command: c.command, part: c.part, resource: c.resource, phase: c.phase, channels: [c.channel], depth: c.depth});
}
const runOf = ch => ch.length > 1 && ch[ch.length - 1] - ch[0] === ch.length - 1 ? ch[0] + " to " + ch[ch.length - 1] : ch.join(", ");
for (const hit of grouped) {
  const ch = hit.channels.sort((a, b) => a - b), many = ch.length > 1;
  const run = runOf(ch);
  hit.text = "the " + hit.part + (many ? "s on channels " : " on channel ") + run + (many ? " go " : " goes ") + (Math.round(hit.depth * 100) / 100) +
    " mm into " + hit.resource + " on the way " + (hit.phase === "descend" ? "down" : hit.phase === "ascend" ? "up" : "across");
}

// tips out of the liquid or the well: one line per command and labware, with the first channel's numbers
const liquidGroups = [];
for (const i of D.liquid || []) {
  const same = liquidGroups.find(h => h.command === i.command && h.labware === i.labware);
  if (same) same.channels.push(i.channel); else liquidGroups.push({command: i.command, labware: i.labware, channels: [i.channel], first: i.text});
}
for (const hit of liquidGroups) {
  const ch = hit.channels.sort((a, b) => a - b);
  grouped.push({command: hit.command, text: "in " + hit.labware + ", " + hit.first + (ch.length > 1 ? " (channels " + runOf(ch) + ")" : " (channel " + ch[0] + ")")});
}
grouped.sort((a, b) => a.command - b.command);

// ---- controls
let t = 0, playing = false, last = 0;
function show() {
  const state = stateAt(t);
  drawTop(state); drawSide(state);
  $("seek").value = Math.round(t * SUB);
  $("count").textContent = Math.min(N, Math.floor(t) + 1) + " / " + N;
  $("now").innerHTML = describe(Math.floor(t));
}
function frame(now) {
  if (!playing) return;
  t = Math.min(N, t + (now - last) / 1000 * Number($("speed").value)); last = now;
  if (t >= N) { playing = false; $("play").textContent = "Replay"; }
  show();
  if (playing) requestAnimationFrame(frame);
}
function setPlaying(on) {
  playing = on;
  if (on && t >= N) t = 0;
  $("play").textContent = on ? "Pause" : "Play";
  if (on) { last = performance.now(); requestAnimationFrame(frame); }
}
function jump(to) { setPlaying(false); t = Math.max(0, Math.min(N, to)); show(); }
$("play").onclick = () => setPlaying(!playing);
$("prev").onclick = () => jump(Math.ceil(t - 0.7 - 1e-6) - 1 + 0.7);   // 0.7 into a command is the bottom of its move
$("next").onclick = () => jump(Math.floor(t - 0.7 + 1e-6) + 1 + 0.7);
$("seek").max = N * SUB;
$("seek").oninput = event => { setPlaying(false); t = Number(event.target.value) / SUB; show(); };
document.addEventListener("keydown", event => {
  if (event.target.tagName === "SELECT") return;
  if (event.key === " ") { event.preventDefault(); setPlaying(!playing); }
  if (event.key === "ArrowLeft") $("prev").onclick();
  if (event.key === "ArrowRight") $("next").onclick();
});

$("title").textContent = D.title || "drybench replay";
$("badge").textContent = D.ok ? "PASS" : "FAIL"; $("badge").className = "badge " + (D.ok ? "pass" : "fail");
$("facts").textContent = N + " commands, " + D.steps + " channel moves, " + D.path_m + " m travelled, " +
  D.collisions.length + (D.collisions.length === 1 ? " collision" : " collisions") + ", " + (D.liquid || []).length + " tips out of the liquid" + (D.skipped ? ", " + D.skipped + " moves not rehearsed" : "");
if (grouped.length) {
  const list = grouped.map((hit, i) => "<li data-i='" + i + "'>Command " + (hit.command + 1) + ": " + hit.text + "</li>").join("");
  $("hitbox").innerHTML = "<h2>What stopped the run (select one to go there)</h2><ul id='hits'>" + list + "</ul>";
  $("hits").onclick = event => { const item = event.target.closest("li"); if (item) jump(grouped[Number(item.dataset.i)].command + 0.7); };
}
window.addEventListener("resize", () => { drawMarks(); show(); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { drawMarks(); show(); });
drawMarks();
jump(grouped.length ? grouped[0].command + 0.7 : 0);
</script>
</body>
</html>
"""
