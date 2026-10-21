# Privacy

## What is collected (all stored locally on the laptop)

| Data | Where | Shown to the language model? |
|---|---|---|
| Your words (typed or recognized) | `messages` table | Yes (local model only, when `--provider ollama`) |
| Mouse: effective/saved primary-button setting, button count | observations | Yes |
| Audio: endpoint names, mute, volume; endpoint ids | observations | Names/mute/volume yes; ids **no** |
| Windows: executable name (e.g. `notepad`), geometry, integrity level, PID, process start time | observations | App label, off-screen flag, visible % only; PIDs/rects **no** |
| Window **titles** | stay inside the helper process memory | **Never** stored, sent to the backend, browser, or model |
| WorkPad text | never leaves WorkPad; only a SHA-256 fingerprint and length are published | No |
| Approvals, operations, results, timings | SQLite | Status summaries only |

Backend and helper output goes to `%LOCALAPPDATA%\RescueBridge\logs` (overwritten at each start): startup
lines, warnings, and error tracebacks only. No tokens, pairing codes, or access lines are written there; a
traceback can contain a fragment of what was typed if that request failed. In USB mode only the phone's
model name is shown; its serial number is not logged.

Raw microphone audio is never recorded by RescueBridge. Speech recognition is performed by your browser;
in Chrome/Edge this may send audio to an online service operated by the browser vendor (not to RescueBridge).

## Credentials

Session cookies (HttpOnly), MCP tokens, pairing/bootstrap codes are random and stored only as SHA-256
digests. The helper key, the host link file, the lab arming record, and the LAN TLS private key are files
readable only by your Windows account (`%LOCALAPPDATA%\RescueBridge`).

## Language model data flow

- `rules`: no model; nothing leaves the laptop.
- `ollama`: your words (and the pending question) go to the Ollama server at `RB_OLLAMA_URL`
  (default `http://127.0.0.1:11434`, on this laptop). RescueBridge does not call any cloud model.
- There is no silent switch to another provider.

## Retention and deletion

Everything lives in `%LOCALAPPDATA%\RescueBridge`. To delete all RescueBridge data: run
`scripts\stop.ps1`, then delete that folder. Revoking a device in the host console invalidates its sessions
and tokens immediately. There is no cloud copy. Evidence files committed to this repository come from
fixture simulations or redacted runs only and contain no personal data, tokens, or window titles.
