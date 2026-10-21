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

// ------------------------------------------------------------------------------------------ pairing
export function renderPairing(root: HTMLElement, session: Session): void {
  const frag = new URLSearchParams(location.hash.slice(1));
  const preset = frag.get("pair") ?? "";
  if (location.hash) history.replaceState(null, "", location.pathname);
  const code = h("input", { id: "code", class: "code-input", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "9",
    value: preset, "aria-describedby": "code-help", placeholder: "1234 5678" });
  const name = h("input", { id: "devname", maxlength: "60", value: guessDeviceName() });
  const msg = h("p", { class: "notice", role: "status", "aria-live": "polite" });
  const btn = h("button", { class: "primary big", type: "submit" }, icon("link"), "Request pairing");
  let polling = 0;
  const form = h("form", {
    class: "card pair",
    onsubmit: async (e: Event) => {
      e.preventDefault();
      btn.setAttribute("disabled", "");
      msg.textContent = "Sending request…";
      try {
        const r = await api("/api/pair/request", { body: { code: code.value, device_name: name.value } });
        msg.textContent = r.message;
        polling = window.setInterval(async () => {
          try {
            const c = await api("/api/pair/claim", { body: {} });
            if (c.status === "PAIRED") {
              clearInterval(polling);
              location.reload();
            }
          } catch (err) {
            clearInterval(polling);
            msg.textContent = (err as Error).message;
            btn.removeAttribute("disabled");
          }
        }, 2000);
      } catch (err) {
        msg.textContent = (err as Error).message;
        btn.removeAttribute("disabled");
      }
    },
  },
    h("div", { class: "pair-hero", "aria-hidden": "true" }, h("span", { class: "pair-node" }, icon("phone")),
      h("span", { class: "pair-beam" }), h("span", { class: "pair-node" }, icon("laptop"))),
    h("h2", null, "Pair this phone with your laptop"),
    h("ol", { class: "steps" },
      h("li", null, h("strong", null, "On the laptop"), ` (${session.host_name}): open the RescueBridge host console and create a pairing code.`),
      h("li", null, h("strong", null, "Here"), ": scan its QR code or type the 8 digits."),
      h("li", null, h("strong", null, "On the laptop"), ": tap Accept this device.")),
    h("label", { for: "code" }, "Pairing code (8 digits)"), code,
    h("p", { id: "code-help", class: "hint" }, "Works once, expires in 5 minutes. Do this while the laptop still works normally."),
    h("label", { for: "devname" }, "Name for this device"), name,
    btn, msg);
  replace(root, header(session), h("main", { id: "main" }, form));
  code.focus();
  // A QR scan or link may change only the fragment of an already-open page: pick the code up then too.
  window.addEventListener("hashchange", () => {
    const next = new URLSearchParams(location.hash.slice(1)).get("pair");
    if (next) {
      code.value = next;
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

function header(session: Session, status?: HTMLElement): HTMLElement {
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
export class RecoveryApp {
  private payload: any = null;
  private lastOk = 0;
  private sending = false;
  private sendStarted = 0;
  private speakReplies = true;
  private voiceText = "";
  private lastSpokenId = "";
  private voice: Voice;
  private cardHost: AppCardHost | null = null;
  private els!: {
    status: HTMLElement; hero: HTMLElement; caption: HTMLElement; convo: HTMLElement; issues: HTMLElement;
    actions: HTMLElement; mic: HTMLButtonElement; micLabel: HTMLElement; micState: HTMLElement;
    input: HTMLTextAreaElement; send: HTMLButtonElement; stopSpeak: HTMLButtonElement; stopBtn: HTMLButtonElement;
    stopStatus: HTMLElement; diag: HTMLDetailsElement; diagBody: HTMLElement; working: HTMLElement;
  };

  constructor(private root: HTMLElement, private session: Session) {
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
    const suggestions = h("div", { class: "suggest", role: "group", "aria-label": "Example phrases" },
      SUGGESTIONS.map((s) => h("button", { type: "button", class: "chip-btn", onclick: () => { input.value = s; this.voiceText = ""; input.focus(); } }, s)));
    const form = h("form", { class: "talk", onsubmit: (e: Event) => { e.preventDefault(); void this.send(); } },
      h("h2", { class: "sr-only" }, "Tell me what's wrong"), input,
      h("div", { class: "row" }, send, stopSpeak), suggestions,
      h("div", { class: "row small toggle" }, speakToggle, h("label", { for: "speak" }, "Speak replies aloud on this device")),
      working);
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
    replace(this.root, header(this.session, status),
      h("main", { id: "main" }, hero, issues, appCard, intro, convo, actions, diag),
      h("footer", { class: "stop-bar" }, stopBtn, stopStatus));
    this.els = { status, hero, caption, convo, issues, actions, mic, micLabel, micState, input, send, stopSpeak, stopBtn,
      stopStatus, diag, diagBody, working };
    this.renderCaption(null);
  }

  private lastKey = "";
  private introCollapsed = false;

  private async refresh(): Promise<void> {
    try {
      const p = await api("/api/state", { timeoutMs: 8000 });
      this.payload = p;
      this.lastOk = Date.now();
      const key = JSON.stringify([p.status, p.messages, Boolean(p.busy_since), p.helper?.reachable]);
      if (key === this.lastKey) {
        this.renderConnection(); // nothing changed: keep focus and screen-reader position
        return;
      }
      this.render();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        location.reload();
        return;
      }
      this.renderConnection();
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
      h("span", { class: `chip mode mode-${adapter.replace(/\s+/g, "-").toLowerCase()}` }, adapter),
      h("span", { class: `chip ${helper.reachable === false ? "bad" : ""}` }, helperText));
  }

  private render(): void {
    preserveFocus(() => this.renderInner());
  }

  private renderCaption(last: any | null): void {
    replace(this.els.caption, h("span", { class: "who" }, icon("spark", "ico inline"), " RescueBridge"),
      h("p", { class: "caption-text" }, last?.text ?? GREETING));
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
    const last = msgs.filter((m) => m.role === "assistant").slice(-1)[0];
    this.renderCaption(last ?? null);
    if (last && last.id !== this.lastSpokenId) {
      if (this.lastSpokenId && this.speakReplies) this.voice.speak(last.text);
      this.lastSpokenId = last.id;
    }
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
      stopped ? h("button", { id: "continue-btn", class: "secondary", type: "button", onclick: () => void this.post("/api/continue", {}) }, "Continue (everything is re-checked first)") : null,
      st?.mission ? h("button", { id: "handoff-btn", class: "secondary", type: "button", onclick: () => void this.handoff() }, "Prepare handoff summary") : null,
      h("div", { id: "handoff" }));
    if (p.busy_since && !this.sending) this.els.working.textContent = "The laptop is still working on a previous request…";
    else if (!this.sending) this.els.working.textContent = "";
  }

  private rail(i: any): HTMLElement {
    const [done, active, halted] = progress(i);
    return h("ol", { class: `rail${halted ? " halted" : ""}`, "aria-label": `Progress: ${done} of ${STEPS.length} steps` },
      STEPS.map((s, k) => h("li", { class: k < done ? "done" : k === active ? (halted ? "stuck" : "active") : "" },
        h("span", { class: "node", "aria-hidden": "true" }, k < done ? icon("check", "ico tiny") : null), h("span", { class: "step" }, s))));
  }

  private issueCard(i: any): HTMLElement {
    const conf = i.confirmation;
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
          h("button", { id: `opt-${i.issue_id}-${o.value}`, type: "button", class: "option", onclick: () => void this.answer(i, o) }, o.label)))) : null,
      (i.open_proposals ?? []).map((pr: any) => this.proposalCard(pr)),
      i.state === "AWAITING_USER_CONFIRMATION" ? h("div", { class: "confirm" },
        h("p", { class: "q" }, conf?.question ?? "Does it work now?"),
        this.simulated() ? h("p", { class: "warn-text" }, SIMULATION_NOTE)
          : conf?.test_kind === "click" ? h("p", { class: "hint" }, "A green click-test target should be on the laptop screen.") : null,
        h("div", { class: "options three" },
          h("button", { id: `res-${i.issue_id}-works`, type: "button", class: "approve", onclick: () => void this.result(i, "works") }, "Yes, it works"),
          h("button", { id: `res-${i.issue_id}-broken`, type: "button", class: "secondary", onclick: () => void this.result(i, "still_broken") }, "No, still broken"),
          h("button", { id: `res-${i.issue_id}-unsure`, type: "button", class: "secondary", onclick: () => void this.result(i, "unsure") }, "Not sure"))) : null,
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
            o.undo_available && i.state !== "STOPPED" ? h("button", { id: `undo-${o.operation_id}`, type: "button", class: "secondary small-btn", onclick: () => void this.undo(o) }, "Undo this change…") : null)),
          (i.person_results ?? []).map((r: any) => h("li", { class: "ev ev-person" }, h("span", { class: "label" }, "Your result: "),
            r.result === "works" ? "works" : r.result === "still_broken" ? "still broken" : "not sure",
            h("span", { class: "small" }, ` (${r.source === "ui_button" ? "tapped" : "said, interpreted"} at ${fmtTime(r.at)})`))))) : null,
      i.next_manual_step ? h("p", { class: "next" }, h("span", { class: "label" }, "Next step: "), i.next_manual_step) : null,
      ["UNRESOLVED", "FAILED", "REPORTED"].includes(i.state) && this.payload?.status?.mission?.state === "ACTIVE"
        ? h("button", { id: `recheck-${i.issue_id}`, type: "button", class: "secondary",
            onclick: () => void this.post(`/api/issues/${i.issue_id}/inspect`, {}) }, "Check again (fresh observation)") : null);
  }

  private proposalCard(pr: any): HTMLElement {
    return h("div", { class: `proposal kind-${pr.kind.toLowerCase()}`, role: "group", "aria-label": PROPOSAL_KIND[pr.kind] },
      h("div", { class: "proposal-head" }, icon(pr.kind === "TEST" ? "speaker" : "shield", "ico"),
        h("span", { class: "label" }, `${PROPOSAL_KIND[pr.kind] ?? "Proposal"} · version ${pr.version}`),
        h("span", { class: "timer", dataset: { expires: String(pr.expires_at) } }, `valid for ${secondsLeft(pr.expires_at)}`)),
      h("p", { class: "desc" }, pr.description),
      pr.kind === "TEST" && this.simulated() ? h("p", { class: "warn-text" }, SIMULATION_NOTE) : null,
      h("p", { class: "small" }, "Approves exactly this text, for this laptop, until Stop."),
      pr.status === "PENDING" ? h("div", { class: "options" },
        h("button", { id: `approve-${pr.proposal_id}`, type: "button", class: "approve big", onclick: () => void this.approve(pr) }, pr.kind === "TEST" ? "Approve and play" : "Approve and apply"),
        h("button", { id: `decline-${pr.proposal_id}`, type: "button", class: "secondary", onclick: () => void this.post(`/api/proposals/${pr.proposal_id}/decline`, {}) }, "Decline")) :
        h("p", { class: "small" }, `Status: ${pr.status}`));
  }

  // ---------------------------------------------------------------------------------- actions
  private async send(): Promise<void> {
    const text = this.els.input.value.trim();
    if (!text || this.sending) return;
    this.voice.stopListening();
    this.sending = true;
    this.sendStarted = Date.now();
    this.orb("thinking");
    this.els.send.setAttribute("disabled", "");
    const mode = this.voiceText && text === this.voiceText ? "voice" : "text";
    try {
      const r = await api("/api/utterance", { body: { text, input_mode: mode } });
      this.els.input.value = "";
      this.voiceText = "";
      this.payload = r;
      this.lastOk = Date.now();
    } catch (e) {
      this.els.working.textContent = (e as Error).message;
    } finally {
      this.sending = false;
      this.orb("idle");
      this.els.send.removeAttribute("disabled");
      this.render();
    }
  }

  private async post(path: string, body: unknown): Promise<void> {
    this.orb("thinking");
    try {
      const r = await api(path, { body });
      if (r.status) this.payload = r;
      this.render();
    } catch (e) {
      this.els.working.textContent = (e as Error).message;
    } finally {
      if (!this.voice.isListening) this.orb("idle");
    }
  }

  private async approve(pr: any): Promise<void> {
    this.els.working.textContent = "Approved. Applying on the laptop and checking the result…";
    await this.post(`/api/proposals/${pr.proposal_id}/approve`, { digest: pr.digest });
  }

  private async answer(issue: any, o: any): Promise<void> {
    const field = issue.kind === "MOUSE_BUTTONS" ? "primary_button" : issue.kind === "OFFSCREEN_WINDOW" ? "target_ref" : "volume_percent";
    await this.post(`/api/issues/${issue.issue_id}/answer`, { field, value: o.value, label: o.label });
  }

  private async result(issue: any, result: string): Promise<void> {
    await this.post(`/api/issues/${issue.issue_id}/result`, { result });
  }

  private async undo(op: any): Promise<void> {
    await this.post(`/api/operations/${op.operation_id}/undo`, {});
  }

  private async stop(): Promise<void> {
    this.voice.stopSpeaking();
    this.els.stopStatus.textContent = "Stop requested…";
    this.els.stopBtn.setAttribute("aria-busy", "true");
    try {
      const r = await api("/api/stop", { body: {}, timeoutMs: 15000 });
      this.els.stopStatus.textContent = r.stop.stop_state === "CONFIRMED"
        ? "Stopped — the laptop helper confirmed it will reject further changes."
        : "Stop recorded — but the laptop helper was unreachable, so whether it stopped is UNKNOWN.";
      this.payload = r;
      this.render();
    } catch (e) {
      this.els.stopStatus.textContent = "Stop requested, but this device could not reach the laptop: status UNKNOWN. " + (e as Error).message;
    } finally {
      this.els.stopBtn.removeAttribute("aria-busy");
    }
  }

  private async handoff(): Promise<void> {
    try {
      const r = await api("/api/handoff");
      const box = h("textarea", { readonly: true, rows: "10", "aria-label": "Handoff summary" });
      box.value = r.text;
      replace(document.getElementById("handoff")!, h("div", { class: "card" }, h("p", { class: "hint" },
        "Share this with someone helping you. It contains no passwords or window titles."), box,
        h("button", { type: "button", class: "secondary", onclick: () => void navigator.clipboard?.writeText(r.text) }, "Copy")));
    } catch (e) {
      this.els.working.textContent = (e as Error).message;
    }
  }

  private async loadDiagnostics(): Promise<void> {
    try {
      const d = await api("/api/diagnostics");
      const s = this.session;
      replace(this.els.diagBody,
        h("p", null, `Language: ${s.model} (${s.model_provider}); data goes to: ${s.model_data_destination}.`),
        h("p", null, `Limits per request: ${s.agent_limits?.model_turns} model turns, ${s.agent_limits?.tool_calls} tool calls, ${s.agent_limits?.timeout_s} s.`),
        h("p", null, `Host adapter: ${s.host_adapter}; MCP: ${d.settings.mcp_url}`),
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
