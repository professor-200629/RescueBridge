# Known limitations

Status as of 2026-10-23 (evidence: `VALIDATION.md`, summary in its section 6). "Verified" means observed at
runtime, not just code inspection. All real-device checks were on **one laptop and one phone, both the owner's**,
done by the owner or by Claude at the owner's request. **No independent participant has used RescueBridge.**

## Verified on the owner's real laptop and phone

- Real Windows **observation** through the separate helper process over the named pipe: mouse mapping
  (effective + saved), default playback endpoint (name, mute, volume) via Core Audio, monitors with DPI, and
  eligible top-level windows (`tests/test_windows_readonly.py` and the phone flows).
- Real Windows **changes**, each approved on the phone: unmute (`SetMute`), the test tone (`PlaySound`, played
  once), a guarded **Undo** of the unmute, and moving the off-screen WorkPad window back (`SetWindowPos`, text
  unchanged) — `VALIDATION.md` 5e, 5f, 5j. The window move and the Undo ran under the Controlled Live Lab.
- Browser → BFF → real MCP client (initialize/tools-list/tools-call, protocol 2025-11-25, Streamable HTTP) →
  MCP server → helper, against both the fixture and the real helper.
- Phone over **USB cable** (`-Usb`) on the owner's Samsung SM-A366E (Android 16): QR pairing, the owner's spoken
  requests through Chrome speech recognition, approvals, spoken replies (5c, 5e). The review repairs (persistent
  errors, first-reply speech, stale-snapshot rejection, pairing validation, setup guidance) were checked in the
  phone's real Chrome **driven by Claude over DevTools**, not by a person using the phone (5j). USB mode needs a
  cable, USB debugging and adb installed by the person: a demo and setup transport, not the end-state channel.
- Pairing, host console, Stop with the real helper's fence acknowledgement.
- Named-pipe DACL (current user only), helper first-instance protection, HMAC authentication, fence rejection
  in a separate helper process (fixture-backed helper over the real pipe).

## Fixture (simulated) only

- Mouse primary-button repair and its click test, volume changes, endpoint switch / monitor unplug / HWND reuse
  races, OS failures, success-without-change, timeouts, restart reconciliation, and every Stop/fence race
  (`tests/test_stop_fence.py`). They ran through the full stack with the fixture OS adapter.
- The 2026-10-23 audit fixes (`VALIDATION.md` 5k): the Stop admission gate, the confirmation rule and the tone
  volume binding are proven on the fixture adapter. On real Windows only the audio gate was exercised, with a
  call that writes nothing; no real change, tone or window move was made with the new code.
- The 30 evaluation scenarios use a **simulated person** (scripted answers), not real people.
- **Simulated preview** is a replay of one recorded fixture conversation (sound only), not a live engine; other
  phrasings are answered with a hint. Regenerate with `scripts\make_preview_data.py` when replies change (a test
  fails if the recording no longer matches the fixture engine).

## Unverified (code exists, not run for real)

- Real Windows `SystemParametersInfoW(SPI_SETMOUSEBUTTONSWAP)`, Core Audio `SetMasterVolumeLevelScalar`, and the
  click-test window. The mouse repair needs a person at the laptop for its click test.
- **Phone over Wi-Fi**: LAN HTTPS mode and self-signed certificate acceptance were not tested on a real phone.
  LAN mode was not started on this laptop because Windows may show a firewall prompt that is the owner's
  decision.
- **MCP App card in other hosts:** verified only in RescueBridge's own simulator host (a single sandboxed
  iframe, a simplification of the spec's separate-origin sandbox proxy). Not opened in a third-party MCP Apps
  host; the MCP endpoint is loopback-only and needs a device token (`rescuebridge.cli mcp-token`).
- Speech recognition accuracy across speakers and accents (one owner, a few utterances, one misrecognised).
- Per-monitor DPI with mixed-DPI multi-monitor setups (only one 120-DPI display available).
- Setup time for a fresh user (target < 10 minutes): only this developer machine was measured, with warm caches.
- Accessibility: keyboard focus and contrast checked in one browser; no screen reader or assistive-technology
  user testing; no automated accessibility audit.
- **Demo video:** planned in `DEMO_SCRIPT.md`, not recorded; no URL exists.

## Operational notes

- The live lab refuses to push a **minimized** WorkPad off-screen (that would create no real fault). Launching
  WorkPad from a hidden process starts it minimized; start it from a normal terminal.
- Stop cannot interrupt an OS call that was already admitted (for example a running `PlaySound`, 1.2 s):
  it finishes, and the fence acknowledgement names it as in flight.
- A tone approved at one volume is never played at another: if the volume, mute or device changed, nothing
  plays and a fresh test proposal must be approved.

## Unsupported by design

- Anything outside the three workflows: frozen/unplugged mouse, Wi-Fi, Bluetooth pairing, printers,
  crashes, black screen, drivers, sign-in, lock screen.
- Switching the default audio output device (only reported, never changed).
- Minimized or maximized off-screen windows, windows on other virtual desktops (cloaked), and windows of
  elevated/protected processes.
- Locked, sleeping, or powered-off laptops; a laptop without the helper running; no network or USB path
  between phone and laptop.
- Undo for window moves (restoring an off-screen position would hide the window again).

## Language and interpretation

- `rules` provider misses many paraphrases (held-out symptoms 11/20). `ollama` with qwen2.5:3b-instruct
  scored 20/20 on held-out v1 symptoms but takes ~5–6 s per request warm and up to ~1 min cold on this laptop.
- Answer interpretation for the LLM path uses an agreement policy (designed after seeing held-out v1
  failures). When interpreters disagree the person is asked to use the buttons.
- English only. Claim guard and polarity checks are English keyword rules.
- The confirmation rule is deliberately conservative: a question, hedge ("maybe", "I think"), condition,
  "sometimes", or a yes-and-no answer is treated as unclear and asked again, so some genuine answers need a
  second "yes"/"no" or a button tap. Answers in words the rule does not know ("absolutely") are not counted;
  the issue keeps waiting for a recognised answer or a button.
- Free tool-calling by the 3B models (`ollama-tools`) is unreliable (0/8 correct first calls).

## Known defects / rough edges

- Spoken replies for several issues at once are long; the cards are clearer than the speech.
- Host console polls every 3 s; phone polls every 2 s (no push).
- The helper key and pipe name are fixed per user; two Windows users on one laptop would need separate pipe
  names (`RB_HELPER_PIPE`).
- Evaluation and benchmark JSON files are machine-specific (timings from this laptop only); host names are redacted.
