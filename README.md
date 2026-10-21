# RescueBridge

**A second interaction channel for recovering an existing Windows work session.** When the mouse clicks
the wrong way, the speaker has gone silent, or a window has drifted off-screen, you talk to RescueBridge
from a phone (or another browser). It inspects the laptop, asks one focused question at a time, proposes an
exact change, and changes nothing until you tap **Approve** on your paired device. After a change it
observes the new state again and asks you whether the problem is actually gone. A big **Stop** button
works throughout.

> **Independent Alexa+ concept simulator.** The browser app simulates an Alexa+-style voice experience that
> reaches a self-hosted MCP server. It is not an Amazon product, not certified, and not connected to Alexa.

Status: working prototype built for the *Build, Ship, Shape: Amazon Developer Hackathon* (Alexa+ track).
Read [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) before relying on it. What was actually tested
is in [`docs/VALIDATION.md`](docs/VALIDATION.md).

## What it can repair (exactly three things)

| Workflow | Observes | Proposes (only after a fresh observation) | Then verifies |
|---|---|---|---|
| A. Mouse buttons | effective + saved primary-button setting | swap back **only if it conflicts with the preference you state**, so left-handed setups are respected | re-reads the setting; on-screen click-test target; your answer |
| B. Sound | default playback endpoint, mute, volume (Core Audio) | unmute that exact endpoint; set a bounded test volume (default 20%, range 5–50%) only if it is effectively silent | re-reads endpoint state; optional approved test tone; your answer |
| C. Off-screen window | eligible top-level windows, monitors, DPI | move the chosen window back onto the main display (same size if it fits); asks which app if ambiguous | re-measures the window; WorkPad text fingerprint unchanged; your answer |

Anything else (frozen pointer, Wi-Fi, printers, crashes…) is recorded as **unsupported** with a manual next
step. No change is made for it.

## Requirements

- Windows 10/11, a standard (non-administrator) user account. Tested on Windows 11 Home 10.0.26300.
- Python 3.13 and [uv](https://docs.astral.sh/uv/) (tested: uv 0.12.9). `uv` installs the pinned Python
  packages into `.venv`. Nothing is installed system-wide.
- Node.js (tested: 24.14.0) — only to build the web app once.
- Optional: [Ollama](https://ollama.com) with a tool-capable small model already installed (tested:
  `qwen2.5:3b-instruct`). RescueBridge never downloads models.
- For the phone, either a USB data cable with USB debugging on and [Android platform-tools](https://developer.android.com/tools/releases/platform-tools)
  (`adb`, installed by you) — see "Phone over USB cable" — or the same Wi-Fi network as the laptop — see
  "Phone over LAN". Speech input needs a browser with speech recognition (design target: Chrome on Android).

## Setup (one time, while the laptop works normally)

```powershell
git clone <REPO_URL — pending publication>  RescueBridge
cd RescueBridge
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

`setup.ps1` runs `uv sync --frozen`, `npm ci`, `npm run build`, and the read-only `doctor`, then writes
timings to `evidence\setup_timing_*.json`. `-ExecutionPolicy Bypass` applies to that one PowerShell process
only; no system setting is changed.

## Run

```powershell
# Real Windows, keyword interpreter (no language model), this laptop's browser only:
powershell -ExecutionPolicy Bypass -File scripts\start.ps1

# Real Windows + local language model for understanding phrasings (~5–6 s per request on the test laptop):
powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Provider ollama -Model qwen2.5:3b-instruct

# Phone plugged in by USB cable (adb reverse; nothing listens on Wi-Fi):
powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Usb

# Allow a paired phone on the same Wi-Fi (HTTPS on the laptop's LAN address):
powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Lan

# Simulation only — nothing on Windows is read or changed:
powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Fixture -Scenario interview

# Stop everything RescueBridge started (verifies PIDs belong to RescueBridge first):
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
```

`start.ps1` starts the helper (current user, named pipe) and the backend without windows (output in
`%LOCALAPPDATA%\RescueBridge\logs`), then opens the **host console** on the laptop with a one-time link. In the host console: **Create pairing code** → on the phone open the
shown address and enter the code (or scan the QR) → back on the laptop **Accept this device**. The phone
now shows the recovery screen.

Equivalent manual commands (two terminals):

```powershell
.venv\Scripts\python.exe -m rescuebridge.cli helper
.venv\Scripts\python.exe -m rescuebridge.cli serve --provider rules
```

### Phone over USB cable

Without `-Lan` or `-Usb` the backend listens only on `127.0.0.1`, and the pairing QR code encodes
`http://127.0.0.1:8740/#pair=…` — on a phone that address is the phone itself, so the link does not open
(the host console now says so under the QR code). With `-Usb`, RescueBridge runs
`adb reverse tcp:8740 tcp:8740`: the phone's own `127.0.0.1:8740` becomes a tunnel over the cable to the
laptop, so the same QR code opens on the phone. Nothing listens on Wi-Fi, no firewall prompt or certificate
is involved, and the phone browser treats `http://127.0.0.1` as a secure context (microphone allowed). The
host console shows **Phone by USB cable: linked (model)** and re-adds the mapping within 10 s after a replug.
`start.ps1 -Usb` also checks from the phone's side (`curl` on the phone through `adb shell`) that the backend
answers. Needs: USB debugging on (Settings → Developer options), the "Allow USB debugging?" prompt accepted,
and `adb` on PATH (or `RB_ADB=<path to adb.exe>`); RescueBridge never downloads adb or changes phone settings.
Any app on the phone can reach the tunnel while it exists; it still needs a pairing code and your approval
on the laptop. `stop.ps1` removes the mapping. Manual control: `rescuebridge.cli usb-link [--remove]`.

### Phone over LAN

`-Lan` serves HTTPS on the laptop's Wi-Fi address with a **self-signed certificate** generated locally
(`%LOCALAPPDATA%\RescueBridge\certs`). Nothing is added to any trust store, so the phone shows a certificate
warning for that address that you may choose to accept. Windows may ask whether Python may use the network:
choose **Private networks** only. RescueBridge never edits firewall rules. Guest/hotel Wi-Fi often blocks
device-to-device traffic (client isolation); use a home/hotspot network. **The phone path has not yet been
tested on a real phone** — see `docs/VALIDATION.md`.

### Voice

The Talk button uses the browser's speech recognition, which in Chrome/Edge may send audio to an online
service; it is not offline. Recognized words go into an editable box: check them and press **Send**.
Replies are spoken with the browser's speech synthesis ("Stop speaking" does not stop repairs). Typing
always works.

## Language understanding providers (chosen explicitly; no silent fallback)

| `--provider` | What it is | Measured on this laptop (see VALIDATION) |
|---|---|---|
| `rules` (default) | deterministic keyword interpreter, **no language model** | instant; misses many paraphrases (held-out symptoms 11/20) |
| `ollama` | local LLM fills a closed JSON schema; deterministic code calls the MCP tools; answers need LLM/keyword agreement | `qwen2.5:3b-instruct`: held-out symptoms 20/20 (v1) and 9/10 (v2); ~5.4 s median per request warm; first request 7–67 s depending on whether the model was already loaded and free RAM |
| `ollama-tools` | experimental: the LLM picks MCP tools itself | 0/8 correct first tool calls for both installed 3B models — not recommended |

If the configured provider is unavailable, the request fails visibly ("couldn't interpret … nothing was
changed"); it never switches provider silently.

## MCP server

- Streamable HTTP at `http://127.0.0.1:8765/mcp` (loopback only), protocol **2025-11-25** via the initialize
  handshake (the SDK also speaks 2026-07-28).
- Every request needs a bearer token bound to a paired device. The backend mints tokens per browser
  session. For an external MCP client (e.g. an AI assistant on this laptop) a 1-hour token can be printed with
  `.venv\Scripts\python.exe -m rescuebridge.cli mcp-token --device <device id from the host console>`.
- Tools: `start_recovery`, `inspect_recovery`, `propose_recovery`, `apply_recovery`, `verify_recovery`,
  `record_user_result`, `get_recovery_status`, `stop_recovery`, `undo_recovery`. **There is no approve
  tool**: approval exists only on the paired device's screen.

## Testing

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1        # ruff, mypy, pytest, web typecheck
.venv\Scripts\python.exe -m rescuebridge.cli eval --sets fixture,heldout --provider rules   # scenario evaluation
.venv\Scripts\python.exe -m rescuebridge.cli bench-interpret --models qwen2.5:3b-instruct    # interpreter accuracy
.venv\Scripts\python.exe -m rescuebridge.cli doctor                                       # read-only setup check
```

Modes are labelled everywhere: **Fixture Simulation** (in-memory OS), **Real Windows** (the helper on this
laptop), **Controlled Live Lab** (real Windows while a lab session you armed is active; see
`docs/LIVE_LAB.md`). Default tests never change Windows settings; the `windows_readonly` tests read real
mouse/audio/window state without changing it.

## Troubleshooting

| Symptom | Check |
|---|---|
| "Laptop helper: NOT reachable" | The helper window was closed or crashed: `scripts\stop.ps1`, then `scripts\start.ps1`. Stop is then recorded with status *unknown*, never "stopped". |
| Host console says the link is invalid | One-time link already used or older than 10 minutes: `.venv\Scripts\python.exe -m rescuebridge.cli host-link`, then open the URL stored in the printed file. |
| Scanned QR code / link does not open on the phone | Started without `-Usb` or `-Lan`, so the QR points at `127.0.0.1` (the phone itself). Plug in the cable and restart with `-Usb`, or use `-Lan`. |
| Host console: "Phone by USB cable: not linked" | Follow the message: cable must carry data, USB debugging on, tap **Allow** on the phone, only one phone attached. `doctor` shows the adb state. |
| Phone cannot open the LAN address | Same Wi-Fi? Guest network isolation? Windows network prompt answered "Private"? `doctor` shows the LAN address. |
| Microphone button says unavailable | Needs a supported browser and https (LAN mode) or `127.0.0.1` (this laptop, or a phone in USB mode). Type instead. |
| Something stopped working | Read `%LOCALAPPDATA%\RescueBridge\logs\backend.log` and `helper.log` (overwritten at each start; no tokens or pairing codes). |
| `ollama` provider replies "couldn't interpret" | `ollama list` must show the model; first request after idle can take ~1 minute while the model loads. |
| Lab still armed after a crash | `.venv\Scripts\python.exe -m rescuebridge.cli lab restore` (keyboard works even with swapped buttons). |

## Documents

[Product](docs/PRODUCT.md) · [Architecture](docs/ARCHITECTURE.md) · [Threat model](docs/THREAT_MODEL.md) ·
[Validation](docs/VALIDATION.md) · [Privacy](docs/PRIVACY.md) · [Live lab](docs/LIVE_LAB.md) ·
[Known limitations](docs/KNOWN_LIMITATIONS.md) · [Demo script](docs/DEMO_SCRIPT.md) ·
[Submission](docs/SUBMISSION.md) · [Product feedback](docs/PRODUCT_FEEDBACK.md) ·
[Friction log](docs/FRICTION_LOG.md) · [Human trial protocol](docs/HUMAN_TRIAL_PROTOCOL.md) ·
[Checkpoint / next steps](NEXT.md)

License: Apache-2.0. Third-party notices: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
