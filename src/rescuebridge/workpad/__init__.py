"""RescueBridge's own small Tk windows: WorkPad and the click-test target."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def point_tk_at_base_install(base_prefix: str | None = None) -> None:
    """Inside a virtual environment on Windows, Tcl searches for init.tcl relative to the venv, which has no
    Tcl library, so Tk fails with "Can't find a usable init.tcl" (seen on the owner's laptop, uv venv on a
    python.org 3.13 install). Point Tcl/Tk at the base install's libraries when they exist. An explicit
    TCL_LIBRARY / TK_LIBRARY is left alone."""
    root = Path(base_prefix or sys.base_prefix) / "tcl"
    for var, pattern, marker in (("TCL_LIBRARY", "tcl8*", "init.tcl"), ("TK_LIBRARY", "tk8*", "tk.tcl")):
        if os.environ.get(var):
            continue
        found = sorted(p for p in root.glob(pattern) if (p / marker).is_file())
        if found:
            os.environ[var] = str(found[-1])


point_tk_at_base_install()  # runs before rescuebridge.workpad.app / .clicktest create any Tk window
