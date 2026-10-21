# Controlled live lab

The live lab creates **real, reversible faults on this laptop** so the real Windows adapters can be tested
end to end. It is opt-in, separately armed by the person for a named session, a short duration, and an
exact scope. Automated tests never use it.

## Allowed faults (nothing else exists in the code)

| Fault (`lab inject …`) | Scope | What it does | Reverts how |
|---|---|---|---|
| `mouse-swap` | mouse | `SwapMouseButton(TRUE)` — swaps the **effective** mapping only; the saved setting is untouched | `lab restore`, watchdog at expiry, or signing out of Windows |
| `audio-mute` | audio | mutes the default playback endpoint recorded at arming | `lab restore` / watchdog |
| `audio-mute-silent` | audio | mutes it and sets volume 0 | `lab restore` / watchdog (restores the recorded volume) |
| `workpad-offscreen` | workpad | moves RescueBridge's **own WorkPad** window off the right edge of all displays | `lab restore` / watchdog |

Not allowed: disabling input devices, blocking input, driver changes, networking, reboots, killing apps,
touching any app other than WorkPad.

## Safe rehearsal (exact steps)

Keyboard recovery is always available: with swapped buttons, Tab/Enter/Alt+Tab still work.

1. Start RescueBridge normally (real Windows):
   `powershell -ExecutionPolicy Bypass -File scripts\start.ps1` and pair the phone (or a second browser).
2. Optional for the window workflow: open WorkPad in a new terminal:
   `.venv\Scripts\python.exe -m rescuebridge.cli workpad`
3. **Arm** in a new terminal and keep it open (it is the watchdog):
   `.venv\Scripts\python.exe -m rescuebridge.cli lab arm --session rehearsal-1 --minutes 10 --allow audio,workpad`
   It prints the recorded clean state. Add `mouse` to `--allow` only if you are comfortable using the
   keyboard for a few minutes.
4. While armed, the app labels observations **Controlled Live Lab**.
5. **Inject** from another terminal, one fault at a time:
   `.venv\Scripts\python.exe -m rescuebridge.cli lab inject audio-mute`
   `.venv\Scripts\python.exe -m rescuebridge.cli lab inject workpad-offscreen`
6. On the phone: say or type the symptom ("I can't hear anything", "my notes disappeared"), review the
   proposal, approve, play the tone, answer honestly.
7. **Restore** at any time: `.venv\Scripts\python.exe -m rescuebridge.cli lab restore`.
   Ctrl+C in the arming window restores and disarms. At expiry the watchdog restores automatically.
8. Check: `.venv\Scripts\python.exe -m rescuebridge.cli lab status`.

## Recovery and cleanup guarantees (and limits)

- Restore only reverts what the lab injected, and only if the current state still differs from the recorded
  snapshot; changes you made yourself are left alone and reported.
- The arming record, snapshot and ground-truth list of injected faults are in
  `%LOCALAPPDATA%\RescueBridge\lab\arming.json` (current-user-only file). MCP tools and the language model
  cannot read it.
- **Not guaranteed:** cleanup after power loss, a killed watchdog, or a crash before restore. The temporary
  mouse swap reverts at sign-out; audio and WorkPad need `lab restore` (or by hand: Settings > System > Sound;
  for WorkPad, Alt+Tab to it, then Alt+Space → Move → arrow keys, or simply close and reopen WorkPad — its
  text is synthetic).

## Status of live-lab evidence

One live-lab session so far: `rehearsal-1` on 2026-10-21, scope workpad, run by Claude at the owner's request
(`VALIDATION.md` 5f): WorkPad pushed off-screen, recovered from the phone, verified, disarmed. Outside the lab,
the owner muted the laptop by hand and repaired it from the phone (5e). Mouse swap and the click-test window
are still unverified on real Windows.

Note: lab commands must use the same data directory as the running backend, e.g.
`rescuebridge.cli --data-dir <dir> lab arm …`, or the app will not show "Controlled Live Lab".
