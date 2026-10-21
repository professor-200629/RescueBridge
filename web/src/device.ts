// Paired-device recovery screen (phone or desktop browser).
import { api, ApiError, setCsrf } from "./api";
import { fmtTime, h, preserveFocus, replace, secondsLeft } from "./dom";
import { icon } from "./icons";
import { AppCardHost } from "./mcpapp";
import { Voice } from "./voice";

export interface Session {
  paired: boolean;
  role?: string;
  device_name?: string;
  csrf_token?: string;
  host_name: string;
  model_provider?: string;
  model?: string;
  model_data_destination?: string;
  host_adapter?: string;
  agent_limits?: { model_turns: number; tool_calls: number; timeout_s: number };
  lan_url?: string | null;
}

const KIND_TITLE: Record<string, string> = {
  MOUSE_BUTTONS: "Mouse buttons",
  AUDIO_OUTPUT: "Sound",
  OFFSCREEN_WINDOW: "Missing window",
  UNSUPPORTED: "Not supported",
};

const KIND_ICON: Record<string, string> = {
  MOUSE_BUTTONS: "mouse", AUDIO_OUTPUT: "speaker", OFFSCREEN_WINDOW: "window", UNSUPPORTED: "question",
};

const STATE_TEXT: Record<string, string> = {
  REPORTED: "Reported",
  INSPECTING: "Checking",
  NEEDS_CLARIFICATION: "Question for you",
  PROPOSED: "Waiting for your approval",
  APPROVED: "Approved",
  APPLYING: "Applying",
  VERIFYING: "Checking the result",
  AWAITING_USER_CONFIRMATION: "Please check it yourself",
  RESOLVED: "Resolved — you confirmed",
  UNRESOLVED: "Not resolved",
  FAILED: "Failed",
  STOPPED: "Stopped",
  UNSUPPORTED: "Not supported",
};

const OUTCOME_TEXT: Record<string, string> = {
  APPLIED_STATE_VERIFIED: "Change made and the new state was observed",
  APPLIED_STATE_NOT_VERIFIED: "Change sent, but the result was NOT observed",
  NO_CHANGE_NEEDED: "No change needed (already in the requested state)",
  REJECTED_OR_EXPIRED: "Not applied (state changed, expired, or permission revoked)",
  FAILED: "Windows reported a failure",
  OUTCOME_UNKNOWN: "Outcome unknown",
  NOT_ATTEMPTED: "Not attempted",
};

const PROPOSAL_KIND: Record<string, string> = { REPAIR: "Proposed change", TEST: "Proposed test", UNDO: "Proposed undo" };
// Found on a real phone: in fixture mode the prompts asked the person to look for a target or listen for a tone
// that do not exist. Say so instead of letting them search.
const SIMULATION_NOTE = "Simulation mode: no real click-test target, window, or sound appears on the laptop. "
  + "Answer for the scenario you are testing.";

// The trust model as a visible path: nothing is "fixed" until the person confirms it.
const STEPS = ["Heard", "Checked", "Approval", "Verified", "Your check"];
const SUGGESTIONS = ["I can't hear anything", "My clicks are wrong", "My notes window disappeared"];
const GREETING = "Hi. Tell me what's wrong with your laptop: tap the orb and speak, or type below. "
  + "I'll check the laptop first and nothing changes until you approve it here.";

export function header(session: Session, status?: HTMLElement): HTMLElement {
  return h("header", { class: "top" }, h("div", { class: "top-inner" },
    h("div", { class: "brand" }, h("span", { class: "logo" }, icon("logo")),
      h("div", null, h("h1", null, "RescueBridge"),
        h("p", { class: "sim-label" }, "Independent Alexa+ concept simulator · not an Amazon product"))),
    status ?? h("p", { class: "conn" }, h("span", { class: "chip" }, icon("laptop"), session.host_name))));
}

/** [steps done, active step (-1 none), halted] for the progress rail. */
function progress(i: any): [number, number, boolean] {
  const verified = (i.operations ?? []).some((o: any) => o.kind === "REPAIR"
    && ["APPLIED_STATE_VERIFIED", "NO_CHANGE_NEEDED"].includes(o.outcome));
  switch (i.state) {
    case "REPORTED": case "INSPECTING": return [1, 1, false];
    case "NEEDS_CLARIFICATION": case "PROPOSED": return [2, 2, false];
    case "APPROVED": case "APPLYING": case "VERIFYING": return [3, 3, false];
    case "AWAITING_USER_CONFIRMATION": return [4, 4, false];
    case "RESOLVED": return [5, -1, false];
    case "UNSUPPORTED": return [1, 1, true];
    default: return verified ? [4, 4, true] : [2, 2, true]; // UNRESOLVED / FAILED / STOPPED
  }
}

// ------------------------------------------------------------------------------------------ recovery app
export type Caller = <T = any>(path: string, opts?: { method?: string; body?: unknown; timeoutMs?: number }) => Promise<T>;

type ErrorAction = { label: string; run: () => void; primary?: boolean };
type UiError = { title: string; detail: string; actions: ErrorAction[] };
type Failure = { kind: "timeout" | "disconnected" | "session" | "busy" | "conflict" | "server" | "rejected" | "preview"; message: string };

/** Sort a failed request into what the person can do about it. A timeout is never treated as "it failed". */
export function classify(e: unknown): Failure {
  if (e instanceof ApiError) {
    if (e.code === "PREVIEW") return { kind: "preview", message: e.message };
    if (e.code === "TIMEOUT") return { kind: "timeout", message: e.message };
    if (e.code === "NETWORK" || e.status === 0) return { kind: "disconnected", message: e.message };
    if (e.status === 401) return { kind: "session", message: e.message };
    if (e.code === "BUSY") return { kind: "busy", message: e.message };
    if (e.status === 409) return { kind: "conflict", message: e.message };
    if (e.status >= 500) return { kind: "server", message: e.message };
    return { kind: "rejected", message: e.message };
  }
  return { kind: "server", message: (e as Error)?.message || "Unexpected error" };
}

export class RecoveryApp {
  private payload: any = null;
  private lastOk = 0;
  private sending = false;
  private sendStarted = 0;
  private speakReplies = true;
  private voiceText = "";
  private voice: Voice;
  private cardHost: AppCardHost | null = null;
  private call: Caller;
  private preview: boolean;
  // Snapshot ordering: only snapshots at least as new as the last one shown are accepted.
  private lastSeq = -1;
  private deviceId: string | null = null;
  private staleDiscarded = 0;
  private polling = false;
  // Speech: the first snapshot is history (captioned, never spoken); each reply id is spoken at most once.
  private historyLoaded = false;
  private handledReplies = new Set<string>();
  // Requests in flight, by control: a pending control stays disabled across re-renders.
  private pending = new Set<string>();
  private error: UiError | null = null;
  private els!: {
    status: HTMLElement; connHelp: HTMLElement; hero: HTMLElement; caption: HTMLElement; convo: HTMLElement;
    issues: HTMLElement; actions: HTMLElement; mic: HTMLButtonElement; micLabel: HTMLElement; micState: HTMLElement;
    input: HTMLTextAreaElement; send: HTMLButtonElement; stopSpeak: HTMLButtonElement; stopBtn: HTMLButtonElement;
    stopStatus: HTMLElement; diag: HTMLDetailsElement; diagBody: HTMLElement; working: HTMLElement; errorBox: HTMLElement;
  };

  constructor(private root: HTMLElement, private session: Session, opts: { call?: Caller; preview?: boolean } = {}) {
    this.call = opts.call ?? api;
    this.preview = Boolean(opts.preview);
    setCsrf(session.csrf_token ?? "");
    this.voice = new Voice({
      onTranscript: (text, final) => {
        this.els.input.value = text;
        this.voiceText = text;
        if (final) {
          this.els.micState.textContent = "Heard you. Check the text, edit it if needed, then press Send.";
          this.els.send.focus();
        }
      },
      onState: (state, detail) => {
        const listening = state === "listening";
        this.els.mic.setAttribute("aria-pressed", String(listening));
        this.els.mic.classList.toggle("listening", listening);
        this.els.micLabel.textContent = listening ? "Listening… tap to finish" : "Tap to talk";
        this.els.micState.textContent = listening ? "Listening — speak now." : detail ?? "";
        this.orb(listening ? "listening" : this.sending ? "thinking" : "idle");
      },
      onSpeaking: (speaking) => {
        this.els.stopSpeak.hidden = !speaking;
        if (speaking) this.els.micState.textContent = "Speaking the reply… (Stop speaking only silences this device)";
        else if (this.els.micState.textContent?.startsWith("Speaking")) this.els.micState.textContent = "";
        if (!this.voice.isListening && !this.sending) this.orb(speaking ? "speaking" : "idle");
      },
    });
    this.build();
    void this.refresh();
    window.setInterval(() => void this.refresh(), 2000);
    window.setInterval(() => this.tick(), 1000);
  }

  private orb(state: "idle" | "listening" | "thinking" | "speaking"): void {
    this.els.hero.dataset.state = state;
  }

  private build(): void {
    const status = h("div", { class: "conn", role: "status" }, h("span", { class: "chip" }, "Connecting…"));
    const connHelp = h("div", { class: "conn-help", hidden: true });
    const micLabel = h("span", { class: "orb-label" }, "Tap to talk");
    const mic = h("button", { class: "orb", type: "button", "aria-pressed": "false",
      onclick: () => (this.voice.isListening ? this.voice.stopListening() : this.voice.start()) },
      h("span", { class: "orb-visual", "aria-hidden": "true" },
        h("span", { class: "orb-rings" }, h("span"), h("span"), h("span")),
        h("span", { class: "orb-core" }, icon("mic", "orb-ico"))),
      micLabel);
    const micState = h("p", { class: "hint mic-state", role: "status", "aria-live": "polite" },
      this.voice.recognitionSupported ? "Voice uses this browser's speech recognition, which may send audio to an online service. You can always type."
        : "Voice input is not available here (needs a supported browser and a secure https or localhost page). Type instead.");
    const caption = h("div", { class: "caption" });
    const input = h("textarea", { id: "say", rows: "2", maxlength: "500", placeholder: "Or type it here, e.g. My clicks are wrong and I can't hear anything",
      "aria-label": "What is happening? (editable transcript)" });
    const send = h("button", { class: "primary send", type: "submit" }, icon("send"), "Send");
    const stopSpeak = h("button", { type: "button", class: "secondary", hidden: true,
      onclick: () => this.voice.stopSpeaking() }, "Stop speaking (does not stop repairs)");
    const speakToggle = h("input", { type: "checkbox", id: "speak", class: "switch", checked: true,
      onchange: (e: Event) => { this.speakReplies = (e.target as HTMLInputElement).checked; if (!this.speakReplies) this.voice.stopSpeaking(); } });
    const working = h("p", { class: "working", role: "status", "aria-live": "polite" });
    // Errors live in their own alert region: progress text and re-renders never overwrite them.
    const errorBox = h("div", { class: "error-box", role: "alert", hidden: true });
    const suggestions = h("div", { class: "suggest", role: "group", "aria-label": "Example phrases" },
      SUGGESTIONS.map((s) => h("button", { type: "button", class: "chip-btn", onclick: () => { input.value = s; this.voiceText = ""; input.focus(); } }, s)));
    const form = h("form", { class: "talk", onsubmit: (e: Event) => { e.preventDefault(); void this.send(); } },
      h("h2", { class: "sr-only" }, "Tell me what's wrong"), input,
      h("div", { class: "row" }, send, stopSpeak), suggestions,
      h("div", { class: "row small toggle" }, speakToggle, h("label", { for: "speak" }, "Speak replies aloud on this device")),
      working, errorBox);
    const hero = h("section", { class: "hero card", "aria-label": "Talk to RescueBridge", dataset: { state: "idle" } },
      mic, micState, caption, form);
    const convo = h("section", { class: "convo card", "aria-label": "Conversation captions" });
    const issues = h("section", { class: "issues", "aria-label": "Issues" });
    const actions = h("section", { class: "actions" });
    const diagBody = h("div", { class: "diag-body" }, "Open to load.");
    const diag = h("details", { class: "card diag", ontoggle: () => { if (diag.open) void this.loadDiagnostics(); } },
      h("summary", null, "Diagnostics (for developers)"), diagBody);
    const stopStatus = h("span", { class: "stop-status", role: "status", "aria-live": "assertive" });
    const stopBtn = h("button", { class: "stop", type: "button", onclick: () => void this.stop() }, icon("stop"), "STOP all changes");
    const appSlot = h("div", { class: "app-slot" });
    const appCard = h("details", { class: "card appcard", ontoggle: () => {
      if (appCard.open && !this.cardHost) {
        this.cardHost = new AppCardHost();
        appSlot.append(this.cardHost.el);
      }
    } },
      h("summary", null, icon("spark", "ico inline"), " Alexa+ card view ", h("span", { class: "badge s-proposed" }, "MCP App")),
      h("p", { class: "hint" }, "Not drawn by this page: the MCP server ships this card as an MCP App (ui://rescuebridge/recovery-card) "
        + "attached to get_recovery_status, so any MCP Apps host can show it. Read-only: approvals stay on this phone."),
      appSlot);
    const intro = h("details", { class: "card intro", open: true },
      h("summary", null, "What this can do"),
      h("div", { class: "tiles" },
        h("div", { class: "tile" }, icon("mouse"), h("span", null, "Swapped mouse buttons")),
        h("div", { class: "tile" }, icon("speaker"), h("span", null, "Muted or silent sound")),
        h("div", { class: "tile" }, icon("window"), h("span", null, "Window lost off-screen"))),
      h("p", { class: "hint" }, icon("shield", "ico inline"), " Nothing changes on the laptop unless you tap Approve. Anything else is reported as unsupported. "
        + "Your laptop must be on, unlocked, and running RescueBridge."));
    const banner = this.preview ? h("div", { class: "preview-banner", role: "note" },
      h("strong", null, "Simulated preview"),
      " — a recorded conversation from RescueBridge's fixture engine. Nothing on any laptop is read or changed, nothing is paired, and no approval leaves this page. ",
      h("button", { type: "button", class: "secondary small-btn", onclick: () => { location.hash = ""; location.reload(); } }, "Exit preview")) : null;
    replace(this.root, banner, header(this.session, h("div", null, status, connHelp)),
      h("main", { id: "main" }, hero, issues, this.preview ? null : appCard, intro, convo, actions, this.preview ? null : diag),
      h("footer", { class: "stop-bar" }, stopBtn, stopStatus));
    this.els = { status, connHelp, hero, caption, convo, issues, actions, mic, micLabel, micState, input, send, stopSpeak, stopBtn,
      stopStatus, diag, diagBody, working, errorBox };
    this.renderCaption(null);
  }

  private lastKey = "";
  private introCollapsed = false;

  /**
   * The single gate for every snapshot (poll or action response). Rejects snapshots older than the last one shown,
   * so a delayed response can never bring back a state from before a newer action (for example ACTIVE after Stop).
   */
  private accept(p: any, ownReplyId?: string): boolean {
    const snap = p?.snapshot;
    if (snap) {
      if (this.deviceId && snap.device_id && snap.device_id !== this.deviceId) {
        location.reload(); // a different device session took over this browser: start clean
        return false;
      }
      this.deviceId = this.deviceId ?? snap.device_id ?? null;
      if (typeof snap.seq === "number") {
        if (snap.seq < this.lastSeq) {
          this.staleDiscarded += 1;
          return false;
        }
        this.lastSeq = snap.seq;
      }
    }
    this.payload = p;
    this.lastOk = Date.now();
    this.noteReplies(p.messages ?? [], ownReplyId);
    return true;
  }

  /** Speak replies that are new since this page loaded; never history, never twice, only when enabled. */
  private noteReplies(msgs: any[], ownReplyId?: string): void {
    const replies = msgs.filter((m) => m.role === "assistant");
    if (!this.historyLoaded) {
      replies.forEach((m) => { if (m.id !== ownReplyId) this.handledReplies.add(m.id); });
      this.historyLoaded = true;
    }
    const fresh = replies.filter((m) => !this.handledReplies.has(m.id));
    fresh.forEach((m) => this.handledReplies.add(m.id));
    if (fresh.length && this.speakReplies) this.voice.speak(fresh.map((m) => m.text).join(" "));
  }

  private async fetchState(): Promise<boolean> {
    const p = await this.call("/api/state", { timeoutMs: 8000 });
    return this.accept(p);
  }

  private async refresh(): Promise<void> {
    if (this.polling) return; // never two polls in flight
    this.polling = true;
    try {
      const accepted = await this.fetchState();
      const p = this.payload;
      const key = JSON.stringify([p?.status, p?.messages, Boolean(p?.busy_since), p?.helper?.reachable]);
      if (!accepted || key === this.lastKey) {
        this.renderConnection(); // nothing new: keep focus and screen-reader position
        return;
      }
      this.render();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        location.reload();
        return;
      }
      this.renderConnection();
    } finally {
      this.polling = false;
    }
  }

  private tick(): void {
    this.renderConnection();
    if (this.sending) {
      this.els.working.textContent = `Working on it… ${Math.round((Date.now() - this.sendStarted) / 1000)} s (limit ${this.session.agent_limits?.timeout_s ?? 60} s). Stop still works.`;
    }
    this.root.querySelectorAll<HTMLElement>("[data-expires]").forEach((el) => {
      const ms = Number(el.dataset.expires);
      el.textContent = ms > Date.now() ? `valid for ${secondsLeft(ms)}` : "expired — ask again";
    });
  }

  private simulated(): boolean {
    return this.payload?.status?.adapter === "Fixture Simulation";
  }

  private renderConnection(): void {
    const age = (Date.now() - this.lastOk) / 1000;
    const helper = this.payload?.helper ?? {};
    const adapter = this.payload?.status?.adapter ?? "unknown";
    let conn: HTMLElement;
    if (this.lastOk && age < 6) conn = h("span", { class: "chip dot ok" }, "Connected");
    else if (this.lastOk && age < 20) conn = h("span", { class: "chip dot warn" }, "Reconnecting…");
    else conn = h("span", { class: "chip dot bad" }, this.lastOk ? `Disconnected since ${fmtTime(this.lastOk)}` : "Not connected yet");
    const helperText = helper.reachable === false ? "Laptop helper: NOT reachable" : helper.reachable ? "Helper ready" : "Helper not checked yet";
    replace(this.els.status, conn,
      h("span", { class: "chip" }, icon("laptop"), this.session.host_name),
      h("span", { class: `chip mode mode-${adapter.replace(/\s+/g, "-").toLowerCase()}` }, this.preview ? "Simulated preview" : adapter),
      this.preview ? null : h("span", { class: `chip ${helper.reachable === false ? "bad" : ""}` }, helperText));
    let help: string | null = null;
    if (!this.preview && (!this.lastOk || age >= 20)) {
      help = /^(127\.0\.0\.1|localhost)$/.test(location.hostname)
        ? "Cannot reach the laptop. On a phone, 127.0.0.1 works only while the USB link is on: check the cable and that RescueBridge was started with -Usb. On the laptop itself, check that RescueBridge is still running."
        : "Cannot reach the laptop. Check that both are on the same Wi-Fi and that RescueBridge is still running on the laptop.";
    } else if (!this.preview && helper.reachable === false) {
      help = "The laptop helper is not running, so nothing can be checked or changed right now. On the laptop, run scripts\\start.ps1 again. Stop still records your request.";
    }
    this.els.connHelp.hidden = !help;
    if ((this.els.connHelp.textContent || null) !== help) this.els.connHelp.textContent = help ?? "";
  }

  private render(): void {
    preserveFocus(() => this.renderInner());
  }

  private renderCaption(last: any | null): void {
    replace(this.els.caption, h("span", { class: "who" }, icon("spark", "ico inline"), this.preview ? " RescueBridge (simulated)" : " RescueBridge"),
      h("p", { class: "caption-text" }, last?.text ?? (this.preview
        ? "This is a recorded simulation. Tap “I can't hear anything” below, then Send, and follow the buttons."
        : GREETING)));
  }

  private renderError(): void {
    const box = this.els.errorBox;
    const err = this.error;
    box.hidden = !err;
    if (!err) {
      replace(box);
      return;
    }
    replace(box, h("p", { class: "err-title" }, err.title), h("p", { class: "err-detail" }, err.detail),
      h("div", { class: "row" },
        err.actions.map((a) => h("button", { type: "button", class: a.primary ? "primary" : "secondary", onclick: a.run }, a.label)),
        h("button", { type: "button", class: "secondary", onclick: () => this.showError(null) }, "Dismiss")));
  }

  private showError(err: UiError | null): void {
    this.error = err;
    this.renderError();
  }

  private renderInner(): void {
    this.renderConnection();
    const p = this.payload;
    if (!p) return;
    this.lastKey = JSON.stringify([p.status, p.messages, Boolean(p.busy_since), p.helper?.reachable]);
    // conversation captions (last 12) as chat bubbles; the newest reply is also the big caption under the orb
    const msgs: any[] = p.messages ?? [];
    const list = h("ol", { class: "msgs" }, msgs.slice(-12).map((m) =>
      h("li", { class: `msg ${m.role}` }, h("span", { class: "who" }, m.role === "user" ? (m.input_mode === "voice" ? "You (voice)" : "You") : m.role === "assistant" ? "RescueBridge" : "Note"),
        h("span", { class: "text" }, m.text))));
    replace(this.els.convo, h("h2", null, "Conversation"), msgs.length ? list : h("p", { class: "hint" }, "No messages yet."));
    list.scrollTop = list.scrollHeight;
    this.renderCaption(msgs.filter((m) => m.role === "assistant").slice(-1)[0] ?? null);
    // issues
    const st = p.status;
    if (st?.mission && !this.introCollapsed) {
      this.introCollapsed = true; // once a session exists, give the space to the issues (still expandable)
      (this.root.querySelector("details.intro") as HTMLDetailsElement | null)?.removeAttribute("open");
    }
    const issues: any[] = st?.issues ?? [];
    const resolved = issues.filter((i) => i.state === "RESOLVED").length;
    const bar = h("span");
    bar.style.setProperty("--p", issues.length ? `${Math.round((100 * resolved) / issues.length)}%` : "0%");
    replace(this.els.issues,
      st?.mission ? h("div", { class: "mission card" },
        h("div", { class: "mission-top" }, h("span", { class: "eyebrow" }, "Recovery session"),
          h("span", { class: "count" }, `${resolved}/${issues.length} confirmed`),
          st.mission.state === "STOPPED" ? h("span", { class: "badge bad" }, `Stopped (${st.mission.stop_state})`) : null),
        h("p", { class: "summary" }, h("strong", null, "Server status: "), st.mission.server_summary),
        h("div", { class: "meter", role: "progressbar", "aria-label": "Issues confirmed resolved", "aria-valuemin": "0",
          "aria-valuemax": String(issues.length), "aria-valuenow": String(resolved) }, bar)) : null,
      issues.map((i) => this.issueCard(i)));
    void this.cardHost?.push(); // keep the MCP App card in step with the server
    // actions
    const stopped = st?.mission?.state === "STOPPED";
    replace(this.els.actions,
      stopped ? this.button("continue-btn", "secondary", "Continue (everything is re-checked first)",
        (b) => this.act("continue", b, "/api/continue", {}, "action")) : null,
      st?.mission ? h("button", { id: "handoff-btn", class: "secondary", type: "button", onclick: () => void this.handoff() }, "Prepare handoff summary") : null,
      h("div", { id: "handoff" }));
    if (p.busy_since && !this.sending) this.els.working.textContent = "The laptop is still working on a previous request…";
    else if (!this.sending) this.els.working.textContent = "";
  }

  /** A button bound to a request: disabled at once when tapped and while its request is pending. */
  private button(id: string, cls: string, label: string, run: (btn: HTMLButtonElement) => Promise<void>): HTMLButtonElement {
    const busy = this.pending.has(id);
    return h("button", { id, type: "button", class: cls, disabled: busy, "aria-busy": busy ? "true" : null,
      onclick: (e: Event) => void run(e.currentTarget as HTMLButtonElement) }, label);
  }

  private rail(i: any): HTMLElement {
    const [done, active, halted] = progress(i);
    return h("ol", { class: `rail${halted ? " halted" : ""}`, "aria-label": `Progress: ${done} of ${STEPS.length} steps` },
      STEPS.map((s, k) => h("li", { class: k < done ? "done" : k === active ? (halted ? "stuck" : "active") : "" },
        h("span", { class: "node", "aria-hidden": "true" }, k < done ? icon("check", "ico tiny") : null), h("span", { class: "step" }, s))));
  }

  private issueCard(i: any): HTMLElement {
    const conf = i.confirmation;
    const iid = i.issue_id;
    return h("article", { class: `card issue state-${i.state.toLowerCase()}`, "aria-label": KIND_TITLE[i.kind] ?? i.category },
      h("div", { class: "issue-head" }, h("span", { class: "kind-ico" }, icon(KIND_ICON[i.kind] ?? "question")),
        h("h3", null, KIND_TITLE[i.kind] ?? i.category),
        h("span", { class: `badge s-${i.state.toLowerCase()}` }, STATE_TEXT[i.state] ?? i.state)),
      this.rail(i),
      i.reported_words ? h("p", { class: "said" }, h("span", { class: "label" }, "You reported: "), `“${i.reported_words}”`) : null,
      i.observed_facts?.length ? h("div", { class: "facts" }, h("span", { class: "eyebrow" }, icon("laptop", "ico inline"), " Observed on the laptop"),
        h("ul", null, i.observed_facts.map((f: string) => h("li", null, f)))) : null,
      i.supported_explanation ? h("p", { class: "cause" }, h("span", { class: "label" }, "Possible cause supported by that observation: "), i.supported_explanation) : null,
      i.inspection_problems?.length ? h("p", { class: "warn-text" }, "Could not observe: ", i.inspection_problems.join("; "), ". This is not evidence that the setting is fine.") : null,
      i.state === "NEEDS_CLARIFICATION" && i.question ? h("div", { class: "question" }, h("p", { class: "q" }, i.question),
        h("div", { class: "options" }, (i.options ?? []).map((o: any) =>
          this.button(`opt-${iid}-${o.value}`, "option", o.label, (b) => this.answer(i, o, b))))) : null,
      (i.open_proposals ?? []).map((pr: any) => this.proposalCard(pr)),
      i.state === "AWAITING_USER_CONFIRMATION" ? h("div", { class: "confirm" },
        h("p", { class: "q" }, conf?.question ?? "Does it work now?"),
        this.simulated() ? h("p", { class: "warn-text" }, SIMULATION_NOTE)
          : conf?.test_kind === "click" ? h("p", { class: "hint" }, "A green click-test target should be on the laptop screen.") : null,
        h("div", { class: "options three" },
          this.button(`res-${iid}-works`, "approve", "Yes, it works", (b) => this.result(i, "works", b)),
          this.button(`res-${iid}-broken`, "secondary", "No, still broken", (b) => this.result(i, "still_broken", b)),
          this.button(`res-${iid}-unsure`, "secondary", "Not sure", (b) => this.result(i, "unsure", b)))) : null,
      (i.operations?.length || i.person_results?.length) ? h("div", { class: "evidence" }, h("h4", null, "Evidence"),
        h("ul", null,
          (i.operations ?? []).map((o: any) => h("li", { class: `ev ev-${(o.kind ?? "repair").toLowerCase()}` },
            h("span", { class: "label" }, `${o.kind === "TEST" ? "Test tone" : o.kind === "UNDO" ? "Undo" : "System result"} (${o.adapter ?? "unknown adapter"}, ${fmtTime(o.after_observed_at ?? o.finished_at)}): `),
            o.kind === "TEST" && o.outcome === "APPLIED_STATE_NOT_VERIFIED" ? "played (the playback call returned); only your answer shows whether it was audible" : (OUTCOME_TEXT[o.outcome] ?? o.outcome),
            o.observed_before ? h("div", { class: "ba" }, h("span", { class: "tag before" }, "Before"), h("span", null, o.observed_before)) : null,
            o.observed_after ? h("div", { class: "ba" }, h("span", { class: "tag after" }, "After"), h("span", null, o.observed_after)) : null,
            o.workpad_text_unchanged === true ? h("div", { class: "small ok-text" }, icon("check", "ico inline"), " WorkPad's unsaved text: unchanged (same content fingerprint)") : null,
            o.workpad_text_unchanged === false ? h("div", { class: "small warn-text" }, "WorkPad's text fingerprint differs from before") : null,
            o.note || o.reconcile_note ? h("div", { class: "small" }, o.reconcile_note ?? o.note) : null,
            o.undo_available && i.state !== "STOPPED"
              ? this.button(`undo-${o.operation_id}`, "secondary small-btn", "Undo this change…",
                (b) => this.act(`undo-${o.operation_id}`, b, `/api/operations/${o.operation_id}/undo`, {}, "action")) : null)),
          (i.person_results ?? []).map((r: any) => h("li", { class: "ev ev-person" }, h("span", { class: "label" }, "Your result: "),
            r.result === "works" ? "works" : r.result === "still_broken" ? "still broken" : "not sure",
            h("span", { class: "small" }, ` (${r.source === "ui_button" ? "tapped" : "said, interpreted"} at ${fmtTime(r.at)})`))))) : null,
      i.next_manual_step ? h("p", { class: "next" }, h("span", { class: "label" }, "Next step: "), i.next_manual_step) : null,
      ["UNRESOLVED", "FAILED", "REPORTED"].includes(i.state) && this.payload?.status?.mission?.state === "ACTIVE"
        ? this.button(`recheck-${iid}`, "secondary", "Check again (fresh observation)",
          (b) => this.act(`recheck-${iid}`, b, `/api/issues/${iid}/inspect`, {}, "action")) : null);
  }

  private proposalCard(pr: any): HTMLElement {
    const pid = pr.proposal_id;
    return h("div", { class: `proposal kind-${pr.kind.toLowerCase()}`, role: "group", "aria-label": PROPOSAL_KIND[pr.kind] },
      h("div", { class: "proposal-head" }, icon(pr.kind === "TEST" ? "speaker" : "shield", "ico"),
        h("span", { class: "label" }, `${PROPOSAL_KIND[pr.kind] ?? "Proposal"} · version ${pr.version}`),
        h("span", { class: "timer", dataset: { expires: String(pr.expires_at) } }, `valid for ${secondsLeft(pr.expires_at)}`)),
      h("p", { class: "desc" }, pr.description),
      pr.kind === "TEST" && this.simulated() ? h("p", { class: "warn-text" }, SIMULATION_NOTE) : null,
      h("p", { class: "small" }, "Approves exactly this text, for this laptop, until Stop."),
      pr.status === "PENDING" ? h("div", { class: "options" },
        this.button(`approve-${pid}`, "approve big", pr.kind === "TEST" ? "Approve and play" : "Approve and apply", (b) => this.approve(pr, b)),
        this.button(`decline-${pid}`, "secondary", "Decline", (b) => this.act(`decline-${pid}`, b, `/api/proposals/${pid}/decline`, {}, "action"))) :
        h("p", { class: "small" }, `Status: ${pr.status}`));
  }

  // ---------------------------------------------------------------------------------- actions
  private async send(retryText?: string): Promise<void> {
    const text = (retryText ?? this.els.input.value).trim();
    if (!text || this.sending) return;
    this.voice.stopListening();
    this.sending = true;
    this.sendStarted = Date.now();
    this.orb("thinking");
    this.els.send.setAttribute("disabled", "");
    const mode = this.voiceText && text === this.voiceText ? "voice" : "text";
    const known = new Set<string>((this.payload?.messages ?? []).map((m: any) => m.id));
    try {
      const r = await this.call("/api/utterance", { body: { text, input_mode: mode } });
      if (this.els.input.value.trim() === text) this.els.input.value = ""; // keep anything typed meanwhile
      this.voiceText = "";
      this.showError(null);
      this.accept(r, r.reply?.id);
    } catch (e) {
      await this.sendFailed(e, text, known);
    } finally {
      this.sending = false;
      this.orb("idle");
      this.els.send.removeAttribute("disabled");
      this.render();
    }
  }

  private async sendFailed(e: unknown, text: string, known: Set<string>): Promise<void> {
    const f = classify(e);
    const retry: ErrorAction = { label: "Retry", primary: true, run: () => void this.send(text) };
    const kept = "Your words are still in the box.";
    if (f.kind === "preview") {
      this.showError({ title: "Simulated preview", detail: f.message, actions: [] });
      return;
    }
    if (f.kind === "session") {
      this.showError({ title: "This phone's session with the laptop has ended.", detail: "Pair it again with a new code from the laptop's host console. Your message was not sent.",
        actions: [{ label: "Pair again", primary: true, run: () => location.reload() }] });
      return;
    }
    if (f.kind === "timeout" || f.kind === "disconnected") {
      // Did the message reach the laptop before the connection failed? Check before offering to send it again.
      const head = f.kind === "timeout" ? "The laptop did not answer in time." : "This phone lost the connection to the laptop.";
      let delivered = false;
      try {
        await this.fetchState();
        delivered = (this.payload?.messages ?? []).some((m: any) => m.role === "user" && m.text === text && !known.has(m.id));
      } catch {
        delivered = false;
      }
      if (delivered) {
        if (this.els.input.value.trim() === text) this.els.input.value = "";
        this.showError({ title: head, detail: "Your message did reach the laptop and was not sent twice. Its answer appears below when it is ready.", actions: [] });
      } else {
        this.showError({ title: head, detail: `Your message was not delivered. ${kept} Tap Retry when the connection is back.`, actions: [retry] });
      }
      return;
    }
    if (f.kind === "busy") {
      this.showError({ title: "The laptop is still working on your previous request.", detail: `Wait a moment, then tap Retry. ${kept}`, actions: [retry] });
      return;
    }
    if (f.kind === "server") {
      this.showError({ title: "RescueBridge on the laptop hit a server error.", detail: `${f.message}. ${kept} Tap Retry; if it keeps failing, use Stop and restart RescueBridge on the laptop.`, actions: [retry] });
      return;
    }
    this.showError({ title: "The laptop did not accept that.", detail: `${f.message} ${kept}`, actions: [retry] });
  }

  /**
   * One request bound to one control. kind "change" may change Windows (an approval): after a timeout or lost
   * connection it is never re-sent; the laptop's recorded state is fetched first and shown.
   */
  private async act(key: string, btn: HTMLButtonElement | null, path: string, body: unknown, kind: "change" | "action"): Promise<void> {
    if (this.pending.has(key)) return;
    this.pending.add(key);
    btn?.setAttribute("disabled", "");
    btn?.setAttribute("aria-busy", "true");
    this.orb("thinking");
    try {
      const r = await this.call(path, { body });
      this.showError(null);
      this.accept(r, r.reply?.id);
    } catch (e) {
      await this.actionFailed(e, kind, () => void this.act(key, null, path, body, kind));
    } finally {
      this.pending.delete(key);
      if (!this.voice.isListening) this.orb("idle");
      this.render();
    }
  }

  private async actionFailed(e: unknown, kind: "change" | "action", retry: () => void): Promise<void> {
    const f = classify(e);
    if (f.kind === "preview") {
      this.showError({ title: "Simulated preview", detail: f.message, actions: [] });
      return;
    }
    if (f.kind === "session") {
      this.showError({ title: "This phone's session with the laptop has ended.", detail: "Pair it again with a new code from the laptop.",
        actions: [{ label: "Pair again", primary: true, run: () => location.reload() }] });
      return;
    }
    if (f.kind === "timeout" || f.kind === "disconnected") {
      const head = f.kind === "timeout" ? "The laptop did not answer in time." : "This phone lost the connection to the laptop.";
      if (kind === "change") {
        const title = `${head} The change may or may not have happened.`;
        this.showError({ title, detail: "Checking what the laptop recorded before anything else is tried…", actions: [] });
        let checked = false;
        try {
          checked = await this.fetchState();
        } catch {
          checked = false;
        }
        this.render();
        this.showError({ title, detail: checked
          ? "Checked: the cards below show what the laptop recorded. Nothing was sent again; approve again only if the proposal is still waiting."
          : "The laptop could not be checked yet. Nothing was sent again. Tap Check again when the connection is back.",
        actions: [{ label: "Check again", primary: true, run: () => void this.recheck(title) }] });
        return;
      }
      this.showError({ title: head, detail: "Tap Retry when the connection is back.", actions: [{ label: "Retry", primary: true, run: retry }] });
      return;
    }
    if (f.kind === "server") {
      this.showError({ title: "RescueBridge on the laptop hit a server error.", detail: `${f.message}.`, actions: [{ label: "Retry", primary: true, run: retry }] });
      return;
    }
    // conflict / rejected / busy: the server refused; show why and the current state
    this.showError({ title: "The laptop did not accept that.", detail: f.message, actions: [] });
    try {
      await this.fetchState();
    } catch {
      // keep the current view
    }
  }

  private async recheck(title: string): Promise<void> {
    try {
      await this.fetchState();
      this.render();
      this.showError({ title, detail: "Checked again: the cards below show what the laptop recorded.", actions: [] });
    } catch {
      this.showError({ title, detail: "Still cannot reach the laptop. Nothing was sent again.",
        actions: [{ label: "Check again", primary: true, run: () => void this.recheck(title) }] });
    }
  }

  private async approve(pr: any, btn: HTMLButtonElement): Promise<void> {
    if (this.pending.has(`approve-${pr.proposal_id}`)) return;
    this.els.working.textContent = "Approved. Applying on the laptop and checking the result…";
    await this.act(`approve-${pr.proposal_id}`, btn, `/api/proposals/${pr.proposal_id}/approve`, { digest: pr.digest }, "change");
  }

  private async answer(issue: any, o: any, btn: HTMLButtonElement): Promise<void> {
    const field = issue.kind === "MOUSE_BUTTONS" ? "primary_button" : issue.kind === "OFFSCREEN_WINDOW" ? "target_ref" : "volume_percent";
    await this.act(`opt-${issue.issue_id}-${o.value}`, btn, `/api/issues/${issue.issue_id}/answer`, { field, value: o.value, label: o.label }, "action");
  }

  private async result(issue: any, result: string, btn: HTMLButtonElement): Promise<void> {
    await this.act(`res-${issue.issue_id}-${result}`, btn, `/api/issues/${issue.issue_id}/result`, { result }, "action");
  }

  private async stop(): Promise<void> {
    // Stop is never blocked by other pending requests, and its acknowledged result is authoritative: snapshots
    // older than the Stop response are rejected by accept().
    this.voice.stopSpeaking();
    this.els.stopStatus.textContent = "Stop requested…";
    this.els.stopBtn.setAttribute("aria-busy", "true");
    try {
      const r = await this.call("/api/stop", { body: {}, timeoutMs: 15000 });
      this.els.stopStatus.textContent = r.stop?.stop_state === "CONFIRMED"
        ? "Stopped — the laptop helper confirmed it will reject further changes."
        : r.stop?.stop_state === "PREVIEW"
          ? "Preview: on a real laptop, Stop is confirmed by the laptop helper. Nothing is running here."
          : "Stop recorded — but the laptop helper was unreachable, so whether it stopped is UNKNOWN.";
      this.accept(r);
      this.render();
    } catch (e) {
      this.els.stopStatus.textContent = "Stop requested, but this device could not reach the laptop: status UNKNOWN. " + (e as Error).message;
    } finally {
      this.els.stopBtn.removeAttribute("aria-busy");
    }
  }

  private async handoff(): Promise<void> {
    try {
      const r = await this.call("/api/handoff");
      const box = h("textarea", { readonly: true, rows: "10", "aria-label": "Handoff summary" });
      box.value = r.text;
      replace(document.getElementById("handoff")!, h("div", { class: "card" }, h("p", { class: "hint" },
        "Share this with someone helping you. It contains no passwords or window titles."), box,
        h("button", { type: "button", class: "secondary", onclick: () => void navigator.clipboard?.writeText(r.text) }, "Copy")));
    } catch (e) {
      this.showError({ title: "Could not prepare the handoff summary.", detail: (e as Error).message, actions: [] });
    }
  }

  private async loadDiagnostics(): Promise<void> {
    try {
      const d = await this.call("/api/diagnostics");
      const s = this.session;
      replace(this.els.diagBody,
        h("p", null, `Language: ${s.model} (${s.model_provider}); data goes to: ${s.model_data_destination}.`),
        h("p", null, `Limits per request: ${s.agent_limits?.model_turns} model turns, ${s.agent_limits?.tool_calls} tool calls, ${s.agent_limits?.timeout_s} s.`),
        h("p", null, `Host adapter: ${s.host_adapter}; MCP: ${d.settings.mcp_url}; snapshot ${this.lastSeq}, stale snapshots ignored: ${this.staleDiscarded}`),
        h("h4", null, "Recent agent runs"),
        h("ul", null, d.agent_runs.map((r: any) => h("li", null,
          `${fmtTime(r.started_at)} · ${r.provider}${r.model ? " " + r.model : ""} · ${r.latency?.total_ms ?? "?"} ms · turns ${r.model_turns} · tools ${r.tool_calls} · ${r.latency?.stop_reason}` +
          (r.blocked_claims ? ` · blocked claims ${r.blocked_claims}` : "") + (r.error ? ` · error: ${r.error}` : ""),
          h("pre", null, JSON.stringify(r.latency?.trace ?? [], null, 1))))),
        h("h4", null, "Recent observations (redacted facts)"),
        h("pre", null, JSON.stringify(d.observations, null, 1)));
    } catch (e) {
      replace(this.els.diagBody, (e as Error).message);
    }
  }
}
