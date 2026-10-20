"""Click-test target shown on the laptop after a mouse-button repair.

Records which LOGICAL button Windows delivered (Button-1 = primary, Button-3 = secondary) when the person
clicks the target with the physical button they use for normal clicking. Writes only counts; closes itself
after two minutes. It changes no settings.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import time
import tkinter as tk
from pathlib import Path
from typing import Any

TIMEOUT_MS = 120_000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-id", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,80}", a.test_id):
        raise SystemExit("bad test id")
    out = Path(a.out) / f"{a.test_id}.json"
    state: dict[str, Any] = {"status": "waiting", "primary_clicks": 0, "secondary_clicks": 0,
                             "started_at": int(time.time() * 1000)}

    def write() -> None:
        state["updated_at"] = int(time.time() * 1000)
        tmp = out.with_suffix(".tmp")
        with contextlib.suppress(OSError):
            tmp.write_text(json.dumps(state), encoding="utf-8")
            os.replace(tmp, out)

    root = tk.Tk()
    root.title("RescueBridge click test")
    root.attributes("-topmost", True)
    w, h = 420, 300
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    msg = tk.Label(root, text="Click the green area with the button you use for NORMAL clicks.",
                   wraplength=380, font=("Segoe UI", 12), pady=8)
    msg.pack(fill="x")
    target = tk.Label(root, text="Click here", bg="#1e8e3e", fg="white", font=("Segoe UI", 20, "bold"))
    target.pack(fill="both", expand=True, padx=16, pady=16)

    def primary(_e: object) -> None:
        state["primary_clicks"] += 1
        state["status"] = "primary_click_received"
        msg.config(text="Received as a NORMAL (primary) click. Tell RescueBridge on your phone whether that matches.")
        write()

    def secondary(_e: object) -> None:
        state["secondary_clicks"] += 1
        state["status"] = "secondary_click_received"
        msg.config(text="Received as a RIGHT-CLICK (secondary). If you pressed your normal button, it is still wrong.")
        write()

    target.bind("<Button-1>", primary)
    target.bind("<Button-3>", secondary)

    def finish() -> None:
        if state["status"] == "waiting":
            state["status"] = "timed_out"
        write()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", finish)
    root.after(TIMEOUT_MS, finish)
    write()
    root.mainloop()


if __name__ == "__main__":
    main()
