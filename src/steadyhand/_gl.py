"""Pick an offscreen OpenGL backend on a Linux machine with no display.

MuJoCo reads MUJOCO_GL once, when it is first imported, so this has to run before that.
A value the user has set is never changed.

Only a backend whose library is on the machine is chosen. Naming one that is missing makes
`import mujoco` itself fail, and nothing here needs OpenGL except the two pictures `rehearse`
draws: with no backend they are skipped and everything else runs.
"""

import ctypes.util
import os
import sys


def choose() -> str:
  """The backend to ask MuJoCo for, or an empty string to leave its default alone."""
  if not sys.platform.startswith("linux") or "MUJOCO_GL" in os.environ:
    return ""
  if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
    return ""
  if ctypes.util.find_library("EGL"):
    return "egl"
  if ctypes.util.find_library("OSMesa"):
    return "osmesa"
  return ""


_backend = choose()
if _backend:
  os.environ["MUJOCO_GL"] = _backend
