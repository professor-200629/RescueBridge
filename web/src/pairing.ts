// First-run screen of an unpaired browser: connect this phone, set up the laptop, or try the simulated preview.
import { api, ApiError } from "./api";
import { h, replace } from "./dom";
import { icon } from "./icons";
import type { Session } from "./device";

const START_USB = "powershell -ExecutionPolicy Bypass -File scripts\\start.ps1 -Usb";
const START_LAN = "powershell -ExecutionPolicy Bypass -File scripts\\start.ps1 -Lan";
const HOST_CONSOLE = "powershell -ExecutionPolicy Bypass -File scripts\\host-console.ps1";

/** Exactly eight digits after removing spaces and dashes, or null (same rule as the server). */
export function normalizeCode(raw: string): string | null {
  const compact = raw.replace(/[\s-]/g, "");
  return /^[0-9]{8}$/.test(compact) ? compact : null;
}

/** Plain-language message for a pairing failure; distinct per cause. */
export function pairingError(e: unknown): string {
  const code = e instanceof ApiError ? e.code : "";
  switch (code) {
    case "MALFORMED_CODE": return "That is not an 8-digit code. Type the 8 digits shown on the laptop (spaces are fine).";
    case "WRONG_CODE": return "That code does not match the one on the laptop. Check the digits, or create a new code on the laptop.";
    case "CODE_EXPIRED": return "That code has expired (codes last 5 minutes). Create a new one on the laptop's host console.";
    case "NO_ACTIVE_CODE": return "No pairing code is active on the laptop. On the laptop's host console, tap Create pairing code.";
    case "RATE_LIMITED": return "Too many wrong codes. Wait 10 minutes, then create a new code on the laptop.";
    case "TIMEOUT": return "The laptop did not answer in time. Check it is on and RescueBridge is running, then try again.";
    case "NETWORK": return "Cannot reach the laptop from this device. See “How this phone reaches the laptop” below.";
    default: return (e as Error)?.message || "Pairing failed. Try again.";
  }
}

function isPhone(): boolean {
  return /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent);
}

function isLoopback(): boolean {
  return ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname);
}

function cmd(text: string): HTMLElement {
  return h("code", { class: "cmd" }, text);
}

export function renderPairing(root: HTMLElement, session: Session, header: (s: Session) => HTMLElement): void {
  const frag = new URLSearchParams(location.hash.slice(1));
  const preset = frag.get("pair") ?? "";
  if (location.hash) history.replaceState(null, "", location.pathname);
  const code = h("input", { id: "code", class: "code-input", type: "text", inputmode: "numeric", autocomplete: "one-time-code",
    pattern: "[0-9 \\-]*", maxlength: "12", value: preset, "aria-describedby": "code-help code-error", placeholder: "1234 5678",
    "aria-invalid": "false" });
  const codeError = h("p", { id: "code-error", class: "field-error", "aria-live": "polite" });
  const name = h("input", { id: "devname", maxlength: "60", value: guessDeviceName() });
  const msg = h("p", { class: "notice", role: "status", "aria-live": "polite" });
  const btn = h("button", { class: "primary big", type: "submit" }, icon("link"), "Request pairing");
  const setInvalid = (text: string) => {
    code.setAttribute("aria-invalid", text ? "true" : "false");
    codeError.textContent = text;
  };
  code.addEventListener("input", () => { if (code.getAttribute("aria-invalid") === "true" && normalizeCode(code.value)) setInvalid(""); });
  let polling = 0;
  const form = h("form", {
    class: "card pair", novalidate: true,
    onsubmit: async (e: Event) => {
      e.preventDefault();
      const digits = normalizeCode(code.value);
      if (!digits) { // checked here first: a malformed code never reaches the laptop
        setInvalid(code.value.trim() ? "That is not an 8-digit code. Type the 8 digits shown on the laptop (spaces are fine)."
          : "Enter the 8 digits shown on the laptop's host console.");
        code.focus();
        return;
      }
      setInvalid("");
      btn.setAttribute("disabled", "");
      msg.textContent = "Sending request…";
      try {
        const r = await api("/api/pair/request", { body: { code: digits, device_name: name.value }, timeoutMs: 15000 });
        msg.textContent = r.message;
        polling = window.setInterval(async () => {
          try {
            const c = await api("/api/pair/claim", { body: {}, timeoutMs: 10000 });
            if (c.status === "PAIRED") {
              clearInterval(polling);
              location.reload();
            }
          } catch (err) {
            clearInterval(polling);
            msg.textContent = pairingError(err);
            btn.removeAttribute("disabled");
          }
        }, 2000);
      } catch (err) {
        const text = pairingError(err);
        if (err instanceof ApiError && ["MALFORMED_CODE", "WRONG_CODE", "CODE_EXPIRED", "NO_ACTIVE_CODE"].includes(err.code)) {
          setInvalid(text);
          msg.textContent = "";
        } else {
          msg.textContent = text;
        }
        btn.removeAttribute("disabled");
      }
    },
  },
    h("div", { class: "pair-hero", "aria-hidden": "true" }, h("span", { class: "pair-node" }, icon("phone")),
      h("span", { class: "pair-beam" }), h("span", { class: "pair-node" }, icon("laptop"))),
    h("h2", null, "Connect this phone"),
    h("ol", { class: "steps" },
      h("li", null, h("strong", null, "On the laptop"), ` (${session.host_name}): open the host console (see “Set up this laptop”) and tap Create pairing code.`),
      h("li", null, h("strong", null, "Here"), ": scan its QR code, or type the 8 digits below."),
      h("li", null, h("strong", null, "On the laptop"), ": tap Accept this device.")),
    h("label", { for: "code" }, "Pairing code (8 digits)"), code, codeError,
    h("p", { id: "code-help", class: "hint" }, "Works once and expires after 5 minutes. Pair while the laptop still works normally."),
    h("label", { for: "devname" }, "Name for this device"), name,
    btn, msg);

  const here = location.origin;
  const reach = h("details", { class: "card guide", open: !isLoopback() || isPhone() },
    h("summary", null, "How this phone reaches the laptop"),
    h("p", null, "You opened ", h("strong", null, here), ". ",
      isLoopback()
        ? "127.0.0.1 (localhost) always means “the device that opens it”. On the laptop it is the laptop itself; on a phone it reaches the laptop only while the USB link is on."
        : "That is the laptop's Wi-Fi address."),
    h("ul", null,
      h("li", null, h("strong", null, "USB cable (most reliable): "), "plug the phone in, turn on USB debugging, start RescueBridge on the laptop with ",
        cmd(START_USB), ", then open ", h("strong", null, "http://127.0.0.1:8740/"), " on the phone or scan the QR code."),
      h("li", null, h("strong", null, "Same Wi-Fi: "), "start with ", cmd(START_LAN),
        ". The host console shows an https://…:8743 address; open it on the phone and accept the certificate warning for that address only.")));

  const setup = h("details", { class: "card guide", open: !isPhone() },
    h("summary", null, "Set up this laptop"),
    h("ol", { class: "steps" },
      h("li", null, "Install once (README): ", cmd("powershell -ExecutionPolicy Bypass -File scripts\\setup.ps1")),
      h("li", null, "Start RescueBridge: ", cmd(START_USB), " (phone on USB) or ", cmd(START_LAN), " (same Wi-Fi). The host console opens by itself."),
      h("li", null, "To open the host console again later, run ", cmd(HOST_CONSOLE),
        ". It opens a one-time link (works once, 10 minutes) on this laptop only; the host console never opens from a phone.")));

  const preview = h("section", { class: "card preview-cta" },
    h("h2", null, "Just looking?"),
    h("p", { class: "hint" }, "Walk through one recorded recovery from RescueBridge's simulator. Nothing is paired and no laptop is read or changed."),
    h("button", { type: "button", id: "try-preview", class: "secondary", onclick: () => { location.hash = "preview"; location.reload(); } },
      icon("spark"), "Try a simulated recovery"));

  const order = isPhone() ? [form, reach, setup, preview] : [setup, form, reach, preview];
  replace(root, header(session), h("main", { id: "main" }, ...order));
  if (preset || isPhone()) code.focus();
  // A QR scan or link may change only the fragment of an already-open page: pick the code up then too.
  window.addEventListener("hashchange", () => {
    const next = new URLSearchParams(location.hash.slice(1)).get("pair");
    if (next) {
      code.value = next;
      setInvalid("");
      history.replaceState(null, "", location.pathname);
    }
  });
}

function guessDeviceName(): string {
  const ua = navigator.userAgent;
  if (/SM-|Samsung/i.test(ua)) return "Samsung phone";
  if (/Android/i.test(ua)) return "Android phone";
  if (/iPhone/i.test(ua)) return "iPhone";
  return "This browser";
}
