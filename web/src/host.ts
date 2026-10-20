// Laptop host console: pairing codes, accepting devices, revocation, helper/lab status, Stop all.
import { api, setCsrf } from "./api";
import { fmtTime, h, preserveFocus, replace, secondsLeft } from "./dom";

export async function startHost(root: HTMLElement): Promise<void> {
  const frag = new URLSearchParams(location.hash.slice(1));
  const boot = frag.get("b");
  if (location.hash) history.replaceState(null, "", location.pathname);
  if (boot) {
    try {
      await api("/api/host/bootstrap", { body: { code: boot } });
    } catch (e) {
      replace(root, h("main", { id: "main", class: "host" }, h("div", { class: "card" }, h("h1", null, "RescueBridge host console"),
        h("p", null, (e as Error).message))));
      return;
    }
  }
  const sess = await api("/api/session");
  if (!sess.paired || sess.role !== "host_console") {
    replace(root, h("main", { id: "main", class: "host" }, h("div", { class: "card" }, h("h1", null, "RescueBridge host console"),
      h("p", null, "Open the host console with the one-time link from scripts\\start.ps1 (or run `rescuebridge host-link`). "
        + "The link only works on this laptop."))));
    return;
  }
  setCsrf(sess.csrf_token);
  const body = h("div", { class: "host-body" });
  replace(root, h("header", { class: "top" }, h("div", { class: "brand" }, h("span", { class: "logo", "aria-hidden": "true" }, "⛑"),
    h("h1", null, `Host console — ${sess.host_name}`)), h("p", { class: "sim-label" }, "Runs on the laptop only. Pair your phone here while the laptop still works.")),
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
          : h("span", { class: "dot bad" }, `● not reachable — ${helper.error ?? ""}`)),
        h("li", null, `Host adapter: ${s.host_adapter} · Language: ${s.model_provider} · Permission revision: ${s.revision}`),
        h("li", null, s.lan_url ? `Phone address (LAN HTTPS): ${s.lan_url}` : "LAN mode off: only this laptop can open the app (start with -Lan for the phone)."),
        h("li", null, "Live lab: ", s.lab && !s.lab.disarmed_at && s.lab.expires_at * 1000 > Date.now()
          ? h("strong", null, `ARMED for "${s.lab.session}" (${(s.lab.allow ?? []).join(", ")}) until ${fmtTime(s.lab.expires_at * 1000)}`)
          : "not armed"))),
    h("section", { class: "card" }, h("h2", null, "Pair a phone"),
      s.pairing ? h("div", { class: "pair-code" },
        h("p", { class: "code", "aria-label": "Pairing code" }, s.pairing.code),
        h("p", { class: "small" }, h("span", { dataset: { expires: String(s.pairing.expires_at) } }, `expires in ${secondsLeft(s.pairing.expires_at)}`), " · works once"),
        qr(s.pairing.qr_data_uri),
        h("p", { class: "small" }, `On the phone open ${s.pairing.url}/ and enter the code (or scan).`))
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
