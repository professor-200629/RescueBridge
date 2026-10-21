# Known limitations

Status as of 2026-10-20 (see `VALIDATION.md` for evidence). "Verified" means observed at runtime, not just
code inspection.

## Real (verified at runtime on the test laptop)

- Real Windows **observation** through the separate helper process over the named pipe: mouse mapping
  (effective + saved), default playback endpoint (name, mute, volume) via Core Audio, monitors with DPI, and
  eligible top-level windows. Observed in the browser flow and in `tests/test_windows_readonly.py`.
- Browser → BFF → real MCP client (initialize/tools-list/tools-call, protocol 2025-11-25, Streamable HTTP) →
  MCP server → helper, in a real browser (Claude desktop app's built-in Chromium pane), against both the
  fixture and the real helper.
- Pairing, host console, Stop with helper fence acknowledgement against the real helper.
- Named-pipe DACL (current user only), helper first-instance protection, HMAC authentication, fence rejection
  in a separate helper process (fixture-backed).

## Simulated (fixture) only

- **Every repair** (unmute/volume, mouse primary button, window move), test tone, click test, Undo, endpoint
  switch / monitor unplug / HWND reuse races, OS failures, success-without-change, timeouts, restart
  reconciliation. These ran through the full stack with the fixture OS adapter, not on real Windows.
- The 30 evaluation scenarios use a **simulated person** (scripted answers), not real people.

## Unverified (code exists, not yet run for real)

- Real Windows **changes** not yet run: `SystemParametersInfoW(SPI_SETMOUSEBUTTONSWAP)`, Core Audio
  `SetMasterVolumeLevelScalar`, the click-test window, real Undo. (Ran once each on real Windows: Core Audio
  `SetMute` and the `winsound.PlaySound` tone, approved by the owner on the phone, `VALIDATION.md` 5e; and
  `SetWindowPos` on WorkPad under the live lab, 5f.) The rest needs a real fault — the opt-in live lab.
- **Phone over Wi-Fi**: LAN HTTPS mode and self-signed certificate acceptance were not tested on a real phone.
  LAN mode was not started on this laptop because Windows may show a firewall prompt that is the owner's
  decision.
- **Phone over USB cable** (`-Usb`, added 2026-10-21): the transport was verified on the owner's Samsung
  SM-A366E (Android 16): the phone's own `curl` fetched `/api/health` through `adb reverse` (HTTP 200), and the
  mapping was restored automatically 10 s after it was removed. See `VALIDATION.md` for what the owner then did
  on the phone. USB mode needs a cable, USB debugging, and adb installed by the person, so it is a demo and
  setup transport, not the end-state product channel.
- **Microphone and speech** on a real phone (Samsung/Chrome speech recognition) — see `VALIDATION.md`.
- **Voice in a real browser**: SpeechRecognition / speechSynthesis paths were not exercised (the automated
  browser has no microphone). Typing paths were.
- Per-monitor DPI with mixed-DPI multi-monitor setups (only one 120-DPI display available).
- Setup time for a fresh user (target < 10 minutes): only this developer machine was measured.
- Accessibility: keyboard focus preservation and contrast were checked manually in one browser; no screen
  reader or assistive-technology user testing; no automated accessibility audit.

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
- Free tool-calling by the 3B models (`ollama-tools`) is unreliable (0/8 correct first calls).

## Known defects / rough edges

- Spoken replies for several issues at once are long; the cards are clearer than the speech.
- Host console polls every 3 s; phone polls every 2 s (no push).
- The helper key and pipe name are fixed per user; two Windows users on one laptop would need separate pipe
  names (`RB_HELPER_PIPE`).
- Evaluation and benchmark JSON files are machine-specific (timings from this laptop only); host names are redacted.
