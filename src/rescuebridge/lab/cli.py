"""`rescuebridge lab ...` commands (operator-run; never exposed through MCP)."""

from __future__ import annotations

import argparse
import json
import time

from rescuebridge.config import Settings
from rescuebridge.lab import live
from rescuebridge.lab.arming import read_arming


def run(settings: Settings, args: argparse.Namespace) -> int:
    cmd = args.lab_cmd
    if cmd == "status":
        rec = read_arming(settings)
        if not rec:
            print("live lab: never armed")
            return 0
        active = not rec.get("disarmed_at") and rec["expires_at"] > time.time()
        print(json.dumps({"active": active, "session": rec["session"], "allow": rec["allow"],
                          "expires_in_s": int(rec["expires_at"] - time.time()),
                          "injected": [e["fault"] for e in rec.get("injected", [])]}, indent=2))
        return 0
    lops = live.LiveOps.create(settings)
    try:
        if cmd == "arm":
            allow = [a.strip() for a in args.allow.split(",") if a.strip()]
            rec = live.arm(settings, lops, args.session, args.minutes, allow)
            snap = rec["snapshot"]
            print(f"ARMED live lab '{rec['session']}' for {args.minutes} min, scope: {', '.join(allow)}")
            print("Recorded clean state:")
            if snap.get("mouse"):
                print(f"  mouse: swapped={snap['mouse']['swap_effective']} (saved={snap['mouse']['swap_saved']})")
            if snap.get("audio"):
                a = snap["audio"]
                print(f"  audio: '{a['name']}' muted={a['muted']} volume={round(a['volume_scalar'] * 100)}%")
            print(f"  workpad: {'running' if snap.get('workpad') else 'not running'}")
            print("Keep this window open: it restores automatically at expiry or when you press Ctrl+C.")
            print("Manual recovery any time (keyboard works even with swapped buttons): rescuebridge lab restore")
            report = live.watchdog(settings, lops, getattr(args, "poll", 2.0))
            print("\nrestored:", json.dumps(report, indent=2))
            return 0
        if cmd == "inject":
            print(json.dumps(live.inject(settings, lops, args.fault), indent=2))
            return 0
        if cmd == "restore":
            print(json.dumps(live.restore(settings, lops), indent=2))
            return 0
        if cmd == "disarm":
            print(json.dumps(live.disarm(settings, lops), indent=2))
            return 0
        if cmd == "watchdog":
            print(json.dumps(live.watchdog(settings, lops, args.poll), indent=2))
            return 0
    except live.LabError as exc:
        print(f"lab: {exc}")
        return 2
    return 1
