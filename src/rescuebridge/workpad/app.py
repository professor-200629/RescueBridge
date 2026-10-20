"""WorkPad: RescueBridge's own small demo editor with UNSAVED synthetic text.

Used for reproducible off-screen-window tests instead of disturbing personal apps. It never writes its
text to disk. Once a second it publishes only a status record (process id, top-level window handle,
SHA-256 fingerprint and length of the text) so the helper can show that the document was not altered.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

from rescuebridge.config import Settings
from rescuebridge.host.fixture_ops import WORKPAD_TEXT

TITLE = "RescueBridge WorkPad (demo, unsaved)"


def run_workpad(settings: Settings) -> None:
    status_dir: Path = settings.workpad_dir
    status_dir.mkdir(parents=True, exist_ok=True)
    status_path = status_dir / "status.json"
    root = tk.Tk()
    root.title(TITLE)
    root.geometry("800x600+200+150")
    base = tkfont.nametofont("TkDefaultFont").actual()["family"]
    banner = tk.Label(root, text="Demo document — synthetic interview notes. Not saved anywhere.", anchor="w",
                      font=(base, 11), padx=8, pady=6)
    banner.pack(fill="x")
    text = tk.Text(root, wrap="word", font=(base, 13), undo=True, padx=10, pady=10)
    text.pack(fill="both", expand=True)
    text.insert("1.0", WORKPAD_TEXT)
    text.focus_set()

    def publish() -> None:
        content = text.get("1.0", "end-1c")
        try:
            hwnd = int(root.wm_frame(), 16)
        except (tk.TclError, ValueError):
            hwnd = 0
        record = {"pid": os.getpid(), "hwnd": hwnd, "text_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                  "text_chars": len(content), "unsaved": True}
        tmp = status_path.with_suffix(".tmp")
        with contextlib.suppress(OSError):
            tmp.write_text(json.dumps(record), encoding="utf-8")
            os.replace(tmp, status_path)
        root.after(1000, publish)

    def on_close() -> None:
        with contextlib.suppress(OSError):
            status_path.unlink()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(300, publish)
    root.mainloop()
