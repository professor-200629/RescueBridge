// "Try a simulated recovery": replays one conversation recorded from RescueBridge's fixture engine
// (scripts/make_preview_data.py). It runs entirely in this page: no request reaches any laptop, nothing is paired,
// and no approval or credential leaves the browser. Real device control still requires pairing.
import { ApiError } from "./api";
import { type Caller, RecoveryApp, type Session } from "./device";
import data from "./preview-data.json";

const SESSION: Session = {
  paired: true, role: "device", device_name: "Preview", csrf_token: "", host_name: "Demo laptop (simulated)",
  model_provider: "rules", model: "keyword interpreter (no language model)", model_data_destination: "none (preview)",
  host_adapter: "fixture", agent_limits: { model_turns: 0, tool_calls: 0, timeout_s: 60 }, lan_url: null,
};

/** Shift recorded timestamps so they read as "now" (proposal countdowns would otherwise show expired). */
function rebase<T>(value: T, delta: number): T {
  if (Array.isArray(value)) return value.map((v) => rebase(v, delta)) as T;
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = typeof v === "number" && (k === "at" || k.endsWith("_at") || k === "server_time") && v > 1e12 ? v + delta : rebase(v, delta);
    }
    return out as T;
  }
  return value;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function previewCaller(): Caller {
  const delta = Date.now() - data.recorded_at;
  let done = -1; // index of the last step the visitor completed
  const current = () => rebase(done < 0 ? data.initial : data.steps[done].response, delta);
  const call = async (path: string, opts: { body?: unknown } = {}): Promise<any> => {
    if (path === "/api/state") return current();
    await sleep(400); // a little time, like a real request
    if (path === "/api/stop") return { ...current(), stop: { stop_state: "PREVIEW" } };
    if (path === "/api/handoff") {
      return { text: "Simulated preview: no laptop was inspected or changed. On a real laptop this summary lists the observed facts, "
        + "each change with before/after evidence, and your own confirmations, without passwords or window titles." };
    }
    const next = data.steps[done + 1];
    if (next && path === next.path) {
      const text = String((opts.body as { text?: string } | undefined)?.text ?? "");
      if (path === "/api/utterance" && !/hear|sound|audio|mute|speaker|volume/i.test(text)) {
        throw new ApiError("PREVIEW", "This preview has one recorded conversation about sound. Tap “I can't hear anything”, then Send.", 409);
      }
      done += 1;
      return rebase(next.response, delta);
    }
    throw new ApiError("PREVIEW", next
      ? "This recorded preview follows one path. Use the highlighted next step on the card."
      : "That was the whole recorded recovery. Exit the preview to see how to set up a real laptop.", 409);
  };
  return call as Caller;
}

export function startPreview(root: HTMLElement): void {
  new RecoveryApp(root, SESSION, { call: previewCaller(), preview: true });
}
