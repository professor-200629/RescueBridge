// Laptop host console: pairing codes, accepting devices, revocation, helper/lab status, Stop all.
import { api, ApiError, setCsrf } from "./api";
import { fmtTime, h, preserveFocus, replace, secondsLeft } from "./dom";
import { icon } from "./icons";

const LAUNCHER = "powershell -ExecutionPolicy Bypass -File scripts\\host-console.ps1";

/** Where the host console comes from, and what to do now. Shown instead of the console when there is no session. */
function hostGate(root: HTMLElement, problem: string | null): void {
  // A fresh link opened into this already-open tab changes only the fragment: load it properly.
  window.addEventListener("hashchange", () => { if (location.hash.startsWith("#b=")) location.reload(); }, { once: true });
  replace(root, h("main", { id: "main", class: "host" }, h("div", { class: "card guide" },
    h("h1", null, "RescueBridge host console"),
    problem ? h("p", { class: "field-error", role: "alert" }, problem) : null,
    h("p", null, "The host console runs only on the laptop being rescued. It opens through a one-time link (works once, "
      + "expires after 10 minutes) that RescueBridge creates on this laptop, so nobody else can open it."),
    h("ol", { class: "steps" },
      h("li", null, "On this laptop, open PowerShell in the RescueBridge folder."),
      h("li", null, "Run ", h("code", { class: "cmd" }, LAUNCHER), ". It opens this console in your browser."),
      h("li", null, "Not running yet? Start it first: ", h("code", { class: "cmd" }, "powershell -ExecutionPolicy Bypass -File scripts\\start.ps1 -Usb"),
        " (phone on a USB cable) or ", h("code", { class: "cmd" }, "-Lan"), " (same Wi-Fi).")),
    h("p", { class: "hint" }, "On a phone? You do not need this page: open the RescueBridge address on the phone and enter the pairing code shown here on the laptop."))));
}

const BOOTSTRAP_ERRORS: Record<string, string> = {
  BOOTSTRAP_EXPIRED: "That host-console link expired (links last 10 minutes).",
  BOOTSTRAP_USED: "That host-console link was already used (each link works once).",
  BAD_BOOTSTRAP: "That host-console link is not valid.",
  LOCAL_ONLY: "The host console can only be opened on the laptop itself, not from another device.",
};

export async function startHost(root: HTMLElement): Promise<void> {
  const frag = new URLSearchParams(location.hash.slice(1));
  const boot = frag.get("b");
  if (location.hash) history.replaceState(null, "", location.pathname);
  if (boot) {
    try {
      await api("/api/host/bootstrap", { body: { code: boot }, timeoutMs: 10000 });
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      hostGate(root, (BOOTSTRAP_ERRORS[code] ?? `Could not open the host console: ${(e as Error).message}`) + " Open a fresh link as shown below.");
      return;
    }
  }
  let sess: any;
  try {
    sess = await api("/api/session", { timeoutMs: 10000 });
  } catch (e) {
    hostGate(root, `RescueBridge is not answering on this laptop (${(e as Error).message}). Start it as shown below.`);
    return;
  }
  if (!sess.paired || sess.role !== "host_console") {
    hostGate(root, null);
    return;
  }
  setCsrf(sess.csrf_token);
  const body = h("div", { class: "host-body" });
  replace(root, h("header", { class: "top" }, h("div", { class: "top-inner host" }, h("div", { class: "brand" },
    h("span", { class: "logo" }, icon("logo")),
    h("div", null, h("h1", null, `Host console — ${sess.host_name}`),
      h("p", { class: "sim-label" }, "Runs on the laptop only · pair your phone here while the laptop still works"))))),
    h("main", { id: "main", class: "host" }, body));
  let lastKey = "";
  const load = async () => {
    try {
      const s = await api("/api/host/state");
      const key = JSON.stringify(s);
      if (key === lastKey) return; // only re-render on real changes (keeps focus and screen-reader position)
      lastKey = key;
      preserveFocus(() => render(body, s, load));
    } catch (e) {
      lastKey = "";
      replace(body, h("p", { class: "warn-text" }, (e as Error).message));
    }
  };
  await load();
  window.setInterval(load, 3000);
  window.setInterval(() => {
    body.querySelectorAll<HTMLElement>("[data-expires]").forEach((el) => {
      el.textContent = `expires in ${secondsLeft(Number(el.dataset.expires))}`;
    });
  }, 1000);
}

function render(body: HTMLElement, s: any, reload: () => Promise<void>): void {
  const act = async (path: string) => {
    await api(path, { body: {} });
    await reload();
  };
  const helper = s.helper;
  replace(body,
    h("section", { class: "card" }, h("h2", null, "Status"),
      h("ul", null,
        h("li", null, "Windows helper: ", helper.reachable ? h("span", { class: "dot ok" }, `● running (${helper.mode}, pid ${helper.pid})`)
          : h("span", { class: "dot bad" }, `● not reachable — ${helper.error ?? ""}. Nothing can be checked or changed until it runs: `
            + "stop RescueBridge (scripts\\stop.ps1) and start it again (scripts\\start.ps1).")),
        h("li", null, `Host adapter: ${s.host_adapter} · Language: ${s.model_provider} · Permission revision: ${s.revision}`),
        h("li", null, s.lan_url ? `Phone address (LAN HTTPS): ${s.lan_url}` : "LAN mode off (Wi-Fi phones cannot connect; start with -Lan for that)."),
        s.usb ? h("li", null, "Phone by USB cable: ", s.usb.state === "linked"
          ? h("span", { class: "dot ok" }, `● linked${s.usb.model ? ` (${s.usb.model})` : ""}: the phone can open ${location.origin}/`)
          : h("span", { class: "dot bad" }, `● not linked: ${s.usb.detail}`)) : null,
        h("li", null, "Live lab: ", s.lab && !s.lab.disarmed_at && s.lab.expires_at * 1000 > Date.now()
          ? h("strong", null, `ARMED for "${s.lab.session}" (${(s.lab.allow ?? []).join(", ")}) until ${fmtTime(s.lab.expires_at * 1000)}`)
          : "not armed"))),
    h("section", { class: "card" }, h("h2", null, "Pair a phone"),
      s.pairing ? h("div", { class: "pair-code" },
        h("p", { class: "code", "aria-label": "Pairing code" }, s.pairing.code),
        h("p", { class: "small" }, h("span", { dataset: { expires: String(s.pairing.expires_at) } }, `expires in ${secondsLeft(s.pairing.expires_at)}`), " · works once"),
        qr(s.pairing.qr_data_uri),
        h("p", { class: "small" }, `On the phone open ${s.pairing.url}/ and enter the code (or scan).`),
        s.lan_url || s.usb?.state === "linked" ? null
          : h("p", { class: "warn-text" }, "This QR code points at this laptop's own address, so a phone cannot open it yet. "
            + "Plug the phone in by USB and restart with -Usb, or restart with -Lan for Wi-Fi."))
        : h("button", { id: "create-code", class: "primary", type: "button", onclick: () => void act("/api/host/pairing-code") }, "Create pairing code"),
      s.pending_requests.length ? h("div", null, h("h3", null, "Waiting for your decision"),
        s.pending_requests.map((r: any) => h("div", { class: "pending" },
          h("p", null, h("strong", null, r.device_name), ` asked at ${fmtTime(r.created_at)}`),
          h("p", { class: "small" }, r.user_agent ?? ""),
          h("button", { id: `accept-${r.id}`, class: "primary", type: "button", onclick: () => void act(`/api/host/requests/${r.id}/accept`) }, "Accept this device"),
          h("button", { id: `reject-${r.id}`, class: "secondary", type: "button", onclick: () => void act(`/api/host/requests/${r.id}/reject`) }, "Reject")))) : null),
    h("section", { class: "card" }, h("h2", null, "Paired devices"),
      s.devices.length ? h("ul", null, s.devices.map((d: any) => h("li", null, `${d.name} — paired ${fmtTime(d.created_at)}`,
        d.revoked_at ? " (revoked)" : [` · last seen ${fmtTime(d.last_seen_at)} `,
          h("button", { id: `revoke-${d.id}`, class: "secondary small-btn", type: "button", onclick: () => void act(`/api/host/devices/${d.id}/revoke`) }, "Revoke")])))
        : h("p", { class: "hint" }, "No devices yet.")),
    h("section", { class: "card" }, h("h2", null, "Recent recovery sessions"),
      s.missions.length ? h("ul", null, s.missions.map((m: any) => h("li", null, `${fmtTime(m.created_at)} · ${m.device_name ?? "?"} · ${m.state} · stop: ${m.stop_state}`)))
        : h("p", { class: "hint" }, "None.")),
    h("section", { class: "card" }, h("button", { id: "host-stop", class: "stop", type: "button", onclick: () => void act("/api/host/stop") }, "■ STOP all changes")));
}

function qr(dataUri: string): HTMLElement {
  // Server-generated SVG as a data: image (allowed by the CSP img-src); never injected as markup.
  if (!dataUri || !dataUri.startsWith("data:image/svg+xml")) return h("span");
  return h("div", { class: "qr" }, h("img", { src: dataUri, width: "220", height: "220", alt: "QR code containing the pairing link and code" }));
}
