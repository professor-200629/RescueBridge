import "./styles.css";
import { api } from "./api";
import { h, replace } from "./dom";
import { RecoveryApp, renderPairing, type Session } from "./device";
import { startHost } from "./host";

async function boot(): Promise<void> {
  const root = document.getElementById("app")!;
  if (location.pathname === "/host") {
    await startHost(root);
    return;
  }
  let session: Session;
  try {
    session = await api<Session>("/api/session");
  } catch (e) {
    replace(root, h("main", { id: "main" }, h("div", { class: "card" }, h("h1", null, "RescueBridge"),
      h("p", null, `Cannot reach the laptop: ${(e as Error).message}`),
      h("p", { class: "hint" }, "Check that the laptop is on, RescueBridge is running, and this device is on the same Wi-Fi network."))));
    return;
  }
  if (!session.paired || session.role !== "device") {
    renderPairing(root, session);
    return;
  }
  new RecoveryApp(root, session);
}

void boot();
