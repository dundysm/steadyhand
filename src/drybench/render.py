"""Render a scene to a PNG without opening a window."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Optional, Sequence, Union

from . import _gl  # noqa: F401  (must come before mujoco is imported)

import mujoco  # noqa: E402


def _write_png(path: Path, pixels) -> None:
  """Write an HxWx3 uint8 array as a PNG, with no imaging library needed."""
  height, width, _ = pixels.shape
  raw = b"".join(b"\x00" + pixels[row].tobytes() for row in range(height))

  def chunk(tag: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

  header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
  path.write_bytes(
    b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
  )


def close_up(look_at_mm: Sequence[float], distance_mm: float = 330.0) -> mujoco.MjvCamera:
  """A free camera looking at a point given in mm, from the front left and a little above."""
  camera = mujoco.MjvCamera()
  camera.type = mujoco.mjtCamera.mjCAMERA_FREE
  camera.lookat[:] = [v * 1e-3 for v in look_at_mm]
  camera.distance = distance_mm * 1e-3
  camera.azimuth = 55.0
  camera.elevation = -24.0
  return camera


def render_model(
  model: mujoco.MjModel,
  data: mujoco.MjData,
  path: Union[str, Path],
  *,
  width: int = 1600,
  height: int = 1000,
  camera: Union[str, mujoco.MjvCamera, None] = "overview",
) -> Path:
  """Render a compiled model in the state `data` holds. Raises RuntimeError if it cannot."""
  path = Path(path)
  try:
    mujoco.mj_forward(model, data)
    renderer = mujoco.Renderer(model, height=height, width=width)
    try:
      renderer.update_scene(data, camera=camera if camera is not None else -1)
      pixels = renderer.render()
    finally:
      renderer.close()
  except Exception as error:  # no GPU or GL library on this machine
    raise RuntimeError(f"could not render offscreen ({type(error).__name__}: {error})") from error
  _write_png(path, pixels)
  return path


def render_png(
  xml: str,
  path: Union[str, Path],
  *,
  width: int = 1600,
  height: int = 1000,
  camera: Optional[str] = "overview",
) -> Path:
  """Render MuJoCo XML to `path`. Raises RuntimeError when no offscreen renderer is available."""
  model = mujoco.MjModel.from_xml_string(xml)
  return render_model(model, mujoco.MjData(model), path, width=width, height=height, camera=camera)
