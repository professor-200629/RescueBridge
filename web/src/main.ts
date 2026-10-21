import "./styles.css";
import { api } from "./api";
import { header, RecoveryApp, type Session } from "./device";
import { h, replace } from "./dom";
import { startHost } from "./host";
import { renderPairing } from "./pairing";
import { startPreview } from "./preview";

function unreachable(root: HTMLElement, message: string): void {
  const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname);
  replace(root, h("main", { id: "main" }, h("div", { class: "card" }, h("h1", null, "RescueBridge"),
    h("p", { role: "alert" }, `Cannot reach the laptop at ${location.origin}: ${message}`),
    h("ul", null,
      loopback
        ? h("li", null, "127.0.0.1 means “this device”. On a phone it reaches the laptop only while the USB link is on: check the cable and that RescueBridge was started with -Usb.")
        : h("li", null, "Check that this phone and the laptop are on the same Wi-Fi (guest networks often block this)."),
      h("li", null, "On the laptop, check that RescueBridge is running: powershell -ExecutionPolicy Bypass -File scripts\\start.ps1"),
      h("li", null, "Then reload this page.")),
    h("button", { type: "button", class: "secondary", onclick: () => location.reload() }, "Reload"),
    h("button", { type: "button", class: "secondary", onclick: () => { location.hash = "preview"; location.reload(); } },
      "Try a simulated recovery instead"))));
}

async function boot(): Promise<void> {
  const root = document.getElementById("app")!;
  if (location.hash === "#preview") {
    startPreview(root); // fully local: no request reaches the laptop
    return;
  }
  if (location.pathname === "/host") {
    await startHost(root);
    return;
  }
  let session: Session;
  try {
    session = await api<Session>("/api/session", { timeoutMs: 10000 });
  } catch (e) {
    unreachable(root, (e as Error).message);
    return;
  }
  if (!session.paired || session.role !== "device") {
    renderPairing(root, session, header);
    return;
  }
  new RecoveryApp(root, session);
}

void boot();
