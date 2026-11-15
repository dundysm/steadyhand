"""Draw the animation at the top of the README: a rehearsal, seen from beside the deck.

  python tools/make_media.py examples/serial_dilution.yaml docs/rehearsal.gif

Needs ffmpeg on the path and a machine MuJoCo can render offscreen on. Not part of the package.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

from steadyhand import _gl  # noqa: F401  (before mujoco)

import mujoco  # noqa: E402

from steadyhand.cli import _planned  # noqa: E402
from steadyhand.planner import rehearse_plan  # noqa: E402

WIDTH, HEIGHT = 880, 540
EVERY = 4  # one frame for this many 1 mm samples
FRAMES = 420
FPS = 25


class _Enough(Exception):
  pass


def main(source: str, target: str, lead: int = 150) -> None:
  with contextlib.redirect_stdout(io.StringIO()):
    found = _planned(source, None, "hamilton-starlet")
  if found is None:
    raise SystemExit(f"{source} does not plan")
  _, planned = found
  # First pass: where the pipetting happens, and when the first draw begins.
  spots, first = [], []
  count = {"seen": 0}

  def look(model, data, steps, phase):
    count["seen"] += 1
    if steps[0].kind in ("aspirate", "dispense"):
      spots.extend(step.tip_end for step in steps)
      if not first and phase == "descend":
        first.append(count["seen"])

  asyncio.run(rehearse_plan(planned, on_sample=look))
  centre = [sum(spot[i] for spot in spots) / len(spots) * 1e-3 for i in range(3)]
  skip = max(0, first[0] - lead) if first else 0

  state = {"seen": 0, "frames": 0, "renderer": None, "camera": None}
  raw = tempfile.NamedTemporaryFile(suffix=".rgb", delete=False)

  def on_sample(model, data, steps, phase):
    state["seen"] += 1
    if state["seen"] <= skip or state["seen"] % EVERY:
      return
    if state["renderer"] is None:
      state["renderer"] = mujoco.Renderer(model, height=HEIGHT, width=WIDTH)
      camera = mujoco.MjvCamera()
      camera.type = mujoco.mjtCamera.mjCAMERA_FREE
      camera.lookat[:] = [centre[0], centre[1], centre[2] + 0.045]
      camera.distance = 0.40
      camera.azimuth = 118.0
      camera.elevation = -30.0
      state["camera"] = camera
    mujoco.mj_forward(model, data)
    state["renderer"].update_scene(data, camera=state["camera"])
    raw.write(state["renderer"].render().tobytes())
    state["frames"] += 1
    if state["frames"] >= FRAMES:
      raise _Enough

  with contextlib.suppress(_Enough):
    asyncio.run(rehearse_plan(planned, on_sample=on_sample))
  raw.close()
  size = f"{WIDTH}x{HEIGHT}"
  source_args = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", size, "-r", str(FPS), "-i", raw.name]
  palette = raw.name + ".png"
  subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *source_args, "-vf", "palettegen=max_colors=96", palette], check=True)
  subprocess.run(
    ["ffmpeg", "-y", "-loglevel", "error", *source_args, "-i", palette, "-lavfi", "paletteuse=dither=bayer:bayer_scale=4", target],
    check=True,
  )
  Path(raw.name).unlink()
  Path(palette).unlink()
  print(f"wrote {target}: {state['frames']} frames, {Path(target).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
  main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 150)
