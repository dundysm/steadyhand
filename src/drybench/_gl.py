"""Pick an offscreen OpenGL backend on a Linux machine with no display.

MuJoCo reads MUJOCO_GL once, when it is first imported, so this has to run before that.
A value the user has set is never changed.
"""

import os
import sys

if (
  sys.platform.startswith("linux")
  and "MUJOCO_GL" not in os.environ
  and not os.environ.get("DISPLAY")
  and not os.environ.get("WAYLAND_DISPLAY")
):
  os.environ["MUJOCO_GL"] = "egl"
