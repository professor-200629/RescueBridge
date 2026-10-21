// Minimal MCP Apps host (ui protocol 2026-01-26) for the Alexa+ concept simulator.
// The view is NOT drawn by this page: get_recovery_status declares a ui:// resource in its tool _meta, the backend
// reads that resource from the MCP server over MCP, and it runs here in a sandboxed, opaque-origin iframe that can
// only talk JSON-RPC over postMessage. Simplification vs. the spec's web-host guidance: one sandboxed frame instead
// of a separate-origin sandbox proxy (the view needs no same-origin rights).
import { api } from "./api";
import { h } from "./dom";

const PROTOCOL = "2026-01-26";

export class AppCardHost {
  readonly el: HTMLElement;
  private frame: HTMLIFrameElement;
  private ready = false;

  constructor() {
    this.frame = h("iframe", { class: "app-frame", src: "/mcp-app/recovery-card", sandbox: "allow-scripts",
      title: "RescueBridge status card (MCP App from the server)" });
    this.el = h("div", { class: "app-host" }, this.frame);
    window.addEventListener("message", (ev) => void this.onMessage(ev));
  }

  private post(msg: unknown): void {
    this.frame.contentWindow?.postMessage(msg, "*"); // opaque-origin frame: "*" is the only possible target
  }

  private async onMessage(ev: MessageEvent): Promise<void> {
    if (ev.source !== this.frame.contentWindow) return; // only our own frame
    const m = ev.data;
    if (!m || m.jsonrpc !== "2.0" || typeof m.method !== "string") return;
    const reply = (result: unknown) => this.post({ jsonrpc: "2.0", id: m.id, result });
    const fail = (code: number, message: string) => this.post({ jsonrpc: "2.0", id: m.id, error: { code, message } });
    switch (m.method) {
      case "ui/initialize":
        reply({
          protocolVersion: PROTOCOL,
          hostInfo: { name: "rescuebridge-alexa-simulator", version: "0.1.0" },
          hostCapabilities: { serverTools: {} },
          hostContext: { theme: "dark", displayMode: "inline", availableDisplayModes: ["inline"], platform: "web",
            locale: navigator.language },
        });
        return;
      case "ui/notifications/initialized":
        this.ready = true; // nothing is sent to the view before this notification
        this.post({ jsonrpc: "2.0", method: "ui/notifications/tool-input", params: { arguments: {} } });
        await this.push();
        return;
      case "ui/notifications/size-changed": {
        const height = Number(m.params?.height);
        if (Number.isFinite(height)) this.frame.style.height = `${Math.min(Math.max(height, 80), 2000)}px`;
        return;
      }
      case "tools/call":
        try {
          reply(await api("/api/mcp-app/tools-call", { body: { name: String(m.params?.name ?? "") } }));
        } catch (e) {
          fail(-32000, (e as Error).message);
        }
        return;
      default:
        if (m.id !== undefined) fail(-32601, `not supported by this host: ${String(m.method).slice(0, 60)}`);
    }
  }

  /** Call get_recovery_status through MCP and deliver the result to the view. */
  async push(): Promise<void> {
    if (!this.ready) return;
    try {
      const result = await api("/api/mcp-app/tools-call", { body: { name: "get_recovery_status" } });
      this.post({ jsonrpc: "2.0", method: "ui/notifications/tool-result", params: result });
    } catch {
      // the view keeps showing its last result
    }
  }
}
