// Paired-device recovery screen (phone or desktop browser).
import { api, ApiError, setCsrf } from "./api";
import { fmtTime, h, preserveFocus, replace, secondsLeft } from "./dom";
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

// ------------------------------------------------------------------------------------------ pairing
export function renderPairing(root: HTMLElement, session: Session): void {
  const frag = new URLSearchParams(location.hash.slice(1));
  const preset = frag.get("pair") ?? "";
  if (location.hash) history.replaceState(null, "", location.pathname);
  const code = h("input", { id: "code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "9", value: preset,
    "aria-describedby": "code-help", placeholder: "1234-5678" });
  const name = h("input", { id: "devname", maxlength: "60", value: guessDeviceName() });
  const msg = h("p", { class: "notice", role: "status", "aria-live": "polite" });
  const btn = h("button", { class: "primary big", type: "submit" }, "Request pairing");
  let polling = 0;
  const form = h("form", {
    class: "card",
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
    h("h2", null, "Pair this device with your laptop"),
    h("p", null, `Do this while the laptop (${session.host_name}) is still working normally. On the laptop, open the `,
      h("strong", null, "RescueBridge host console"), ", create a pairing code, then enter it here."),
    h("label", { for: "code" }, "Pairing code (8 digits)"), code,
    h("p", { id: "code-help", class: "hint" }, "The code works once and expires in 5 minutes. After you send it, accept this device on the laptop."),
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
  return h("header", { class: "top" },
    h("div", { class: "brand" }, h("span", { class: "logo", "aria-hidden": "true" }, "⛑"), h("h1", null, "RescueBridge")),
    h("p", { class: "sim-label" }, "Independent Alexa+ concept simulator · not an Amazon product"),
    status ?? h("p", { class: "conn" }, `Laptop: ${session.host_name}`));
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
  private els!: {
    status: HTMLElement; convo: HTMLElement; issues: HTMLElement; actions: HTMLElement; mic: HTMLButtonElement;
    micState: HTMLElement; input: HTMLTextAreaElement; send: HTMLButtonElement; stopSpeak: HTMLButtonElement;
    stopBtn: HTMLButtonElement; stopStatus: HTMLElement; diag: HTMLDetailsElement; diagBody: HTMLElement; working: HTMLElement;
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
        this.els.mic.setAttribute("aria-pressed", String(state === "listening"));
        this.els.mic.classList.toggle("listening", state === "listening");
        this.els.mic.textContent = state === "listening" ? "Listening… tap to finish" : "Tap to talk";
        this.els.micState.textContent = state === "listening" ? "Listening — speak now." : detail ?? "";
      },
      onSpeaking: (speaking) => {
        this.els.stopSpeak.hidden = !speaking;
        if (speaking) this.els.micState.textContent = "Speaking the reply… (Stop speaking only silences this device)";
        else if (this.els.micState.textContent?.startsWith("Speaking")) this.els.micState.textContent = "";
      },
    });
    this.build();
    void this.refresh();
    window.setInterval(() => void this.refresh(), 2000);
    window.setInterval(() => this.tick(), 1000);
  }

  private build(): void {
    const status = h("p", { class: "conn", role: "status" }, "Connecting…");
    const mic = h("button", { class: "mic big", type: "button", "aria-pressed": "false",
      onclick: () => (this.voice.isListening ? this.voice.stopListening() : this.voice.start()) }, "Tap to talk");
    const micState = h("p", { class: "hint", role: "status", "aria-live": "polite" },
      this.voice.recognitionSupported ? "Voice input uses this browser's speech recognition, which may send audio to an online service. You can always type."
        : "Voice input is not available here (needs a supported browser and a secure https or localhost page). Type instead.");
    const input = h("textarea", { id: "say", rows: "3", maxlength: "500", placeholder: "e.g. My clicks are wrong and I can't hear anything",
      "aria-label": "What is happening? (editable transcript)" });
    const send = h("button", { class: "primary", type: "submit" }, "Send");
    const stopSpeak = h("button", { type: "button", class: "secondary", hidden: true,
      onclick: () => this.voice.stopSpeaking() }, "Stop speaking (does not stop repairs)");
    const speakToggle = h("input", { type: "checkbox", id: "speak", checked: true,
      onchange: (e: Event) => { this.speakReplies = (e.target as HTMLInputElement).checked; if (!this.speakReplies) this.voice.stopSpeaking(); } });
    const working = h("p", { class: "working", role: "status", "aria-live": "polite" });
    const form = h("form", { class: "talk card", onsubmit: (e: Event) => { e.preventDefault(); void this.send(); } },
      h("h2", null, "Tell me what's wrong"), mic, micState,
      h("label", { for: "say" }, "Your words (edit before sending)"), input,
      h("div", { class: "row" }, send, stopSpeak),
      h("div", { class: "row small" }, speakToggle, h("label", { for: "speak" }, "Speak replies aloud on this device")),
      working);
    const convo = h("section", { class: "convo card", "aria-label": "Conversation captions" });
    const issues = h("section", { class: "issues", "aria-label": "Issues" });
    const actions = h("section", { class: "actions" });
    const diagBody = h("div", { class: "diag-body" }, "Open to load.");
    const diag = h("details", { class: "card diag", ontoggle: () => { if (diag.open) void this.loadDiagnostics(); } },
      h("summary", null, "Diagnostics (for developers)"), diagBody);
    const stopStatus = h("span", { class: "stop-status", role: "status", "aria-live": "assertive" });
    const stopBtn = h("button", { class: "stop", type: "button", onclick: () => void this.stop() }, "■ STOP all changes");
    const intro = h("details", { class: "card intro", open: true },
      h("summary", null, "What this can do"),
      h("ul", null,
        h("li", null, "Mouse buttons swapped against your preference → put them back (after you approve)."),
        h("li", null, "Muted or silent default speaker → unmute it and let you test it (after you approve)."),
        h("li", null, "An app window moved off-screen → bring it back without closing it (after you approve).")),
      h("p", { class: "hint" }, "Anything else is reported as unsupported. Nothing changes on the laptop unless you tap Approve. Your laptop must be on, unlocked, and running RescueBridge."));
    replace(this.root, header(this.session, status),
      h("main", { id: "main" }, intro, form, convo, issues, actions, diag),
      h("footer", { class: "stop-bar" }, stopBtn, stopStatus));
    this.els = { status, convo, issues, actions, mic, micState, input, send, stopSpeak, stopBtn, stopStatus, diag, diagBody, working };
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

  private renderConnection(): void {
    const age = (Date.now() - this.lastOk) / 1000;
    const helper = this.payload?.helper ?? {};
    const adapter = this.payload?.status?.adapter ?? "unknown";
    let conn: HTMLElement;
    if (this.lastOk && age < 6) conn = h("span", { class: "dot ok" }, "● Connected");
    else if (this.lastOk && age < 20) conn = h("span", { class: "dot warn" }, "● Reconnecting…");
    else conn = h("span", { class: "dot bad" }, this.lastOk ? `● Disconnected since ${fmtTime(this.lastOk)}` : "● Not connected yet");
    const helperText = helper.reachable === false ? "Laptop helper: NOT reachable" : helper.reachable ? "Laptop helper: reachable" : "Laptop helper: not checked yet";
    replace(this.els.status, conn, ` to ${this.session.host_name} · `, h("span", { class: `mode mode-${adapter.replace(/\s+/g, "-").toLowerCase()}` }, adapter),
      ` · ${helperText} · ${this.session.device_name ?? ""}`);
  }

  private render(): void {
    preserveFocus(() => this.renderInner());
  }

  private renderInner(): void {
    this.renderConnection();
    const p = this.payload;
    if (!p) return;
    this.lastKey = JSON.stringify([p.status, p.messages, Boolean(p.busy_since), p.helper?.reachable]);
    // conversation captions (last 12)
    const msgs: any[] = p.messages ?? [];
    replace(this.els.convo, h("h2", null, "Conversation"),
      msgs.length ? h("ol", { class: "msgs" }, msgs.slice(-12).map((m) =>
        h("li", { class: `msg ${m.role}` }, h("span", { class: "who" }, m.role === "user" ? "You" : m.role === "assistant" ? "RescueBridge" : "Note"),
          h("span", { class: "text" }, m.text)))) : h("p", { class: "hint" }, "No messages yet."));
    const last = msgs.filter((m) => m.role === "assistant").slice(-1)[0];
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
    replace(this.els.issues,
      st?.mission ? h("p", { class: "summary" }, h("strong", null, "Server status: "), st.mission.server_summary,
        st.mission.state === "STOPPED" ? h("span", { class: "badge bad" }, `Stopped (${st.mission.stop_state})`) : null) : null,
      issues.map((i) => this.issueCard(i)));
    // actions
    const stopped = st?.mission?.state === "STOPPED";
    replace(this.els.actions,
      stopped ? h("button", { id: "continue-btn", class: "secondary", type: "button", onclick: () => void this.post("/api/continue", {}) }, "Continue (everything is re-checked first)") : null,
      st?.mission ? h("button", { id: "handoff-btn", class: "secondary", type: "button", onclick: () => void this.handoff() }, "Prepare handoff summary") : null,
      h("div", { id: "handoff" }));
    if (p.busy_since && !this.sending) this.els.working.textContent = "The laptop is still working on a previous request…";
    else if (!this.sending) this.els.working.textContent = "";
  }

  private issueCard(i: any): HTMLElement {
    const conf = i.confirmation;
    return h("article", { class: `card issue state-${i.state.toLowerCase()}`, "aria-label": KIND_TITLE[i.kind] ?? i.category },
      h("div", { class: "issue-head" }, h("h3", null, KIND_TITLE[i.kind] ?? i.category),
        h("span", { class: `badge s-${i.state.toLowerCase()}` }, STATE_TEXT[i.state] ?? i.state)),
      i.reported_words ? h("p", { class: "said" }, h("span", { class: "label" }, "You reported: "), `“${i.reported_words}”`) : null,
      i.observed_facts?.length ? h("div", { class: "facts" }, h("span", { class: "label" }, "Inspection observed on the laptop:"),
        h("ul", null, i.observed_facts.map((f: string) => h("li", null, f)))) : null,
      i.supported_explanation ? h("p", null, h("span", { class: "label" }, "Possible cause supported by that observation: "), i.supported_explanation) : null,
      i.inspection_problems?.length ? h("p", { class: "warn-text" }, "Could not observe: ", i.inspection_problems.join("; "), ". This is not evidence that the setting is fine.") : null,
      i.state === "NEEDS_CLARIFICATION" && i.question ? h("div", { class: "question" }, h("p", { class: "q" }, i.question),
        h("div", { class: "options" }, (i.options ?? []).map((o: any) =>
          h("button", { id: `opt-${i.issue_id}-${o.value}`, type: "button", class: "option", onclick: () => void this.answer(i, o) }, o.label)))) : null,
      (i.open_proposals ?? []).map((pr: any) => this.proposalCard(pr)),
      i.state === "AWAITING_USER_CONFIRMATION" ? h("div", { class: "confirm" },
        h("p", { class: "q" }, conf?.question ?? "Does it work now?"),
        conf?.test_kind === "click" ? h("p", { class: "hint" }, "A green click-test target should be on the laptop screen.") : null,
        h("div", { class: "options" },
          h("button", { id: `res-${i.issue_id}-works`, type: "button", class: "primary", onclick: () => void this.result(i, "works") }, "Yes, it works"),
          h("button", { id: `res-${i.issue_id}-broken`, type: "button", class: "secondary", onclick: () => void this.result(i, "still_broken") }, "No, still broken"),
          h("button", { id: `res-${i.issue_id}-unsure`, type: "button", class: "secondary", onclick: () => void this.result(i, "unsure") }, "Not sure"))) : null,
      (i.operations?.length || i.person_results?.length) ? h("div", { class: "evidence" }, h("h4", null, "Evidence"),
        h("ul", null,
          (i.operations ?? []).map((o: any) => h("li", null,
            h("span", { class: "label" }, `${o.kind === "TEST" ? "Test tone" : o.kind === "UNDO" ? "Undo" : "System result"} (${o.adapter ?? "unknown adapter"}, ${fmtTime(o.after_observed_at ?? o.finished_at)}): `),
            o.kind === "TEST" && o.outcome === "APPLIED_STATE_NOT_VERIFIED" ? "played (the playback call returned); only your answer shows whether it was audible" : (OUTCOME_TEXT[o.outcome] ?? o.outcome),
            o.observed_before ? h("div", { class: "small" }, `Before: ${o.observed_before}`) : null,
            o.observed_after ? h("div", { class: "small" }, `After: ${o.observed_after}`) : null,
            o.workpad_text_unchanged === true ? h("div", { class: "small" }, "WorkPad's unsaved text: unchanged (same content fingerprint)") : null,
            o.workpad_text_unchanged === false ? h("div", { class: "small warn-text" }, "WorkPad's text fingerprint differs from before") : null,
            o.note || o.reconcile_note ? h("div", { class: "small" }, o.reconcile_note ?? o.note) : null,
            o.undo_available && i.state !== "STOPPED" ? h("button", { id: `undo-${o.operation_id}`, type: "button", class: "secondary small-btn", onclick: () => void this.undo(o) }, "Undo this change…") : null)),
          (i.person_results ?? []).map((r: any) => h("li", null, h("span", { class: "label" }, "Your result: "),
            r.result === "works" ? "works" : r.result === "still_broken" ? "still broken" : "not sure",
            h("span", { class: "small" }, ` (${r.source === "ui_button" ? "tapped" : "said, interpreted"} at ${fmtTime(r.at)})`))))) : null,
      i.next_manual_step ? h("p", { class: "next" }, h("span", { class: "label" }, "Next step: "), i.next_manual_step) : null);
  }

  private proposalCard(pr: any): HTMLElement {
    return h("div", { class: `proposal kind-${pr.kind.toLowerCase()}`, role: "group", "aria-label": PROPOSAL_KIND[pr.kind] },
      h("p", { class: "label" }, `${PROPOSAL_KIND[pr.kind] ?? "Proposal"} (version ${pr.version})`),
      h("p", { class: "desc" }, pr.description),
      h("p", { class: "small" }, h("span", { dataset: { expires: String(pr.expires_at) } }, `valid for ${secondsLeft(pr.expires_at)}`),
        " · approves exactly this text, for this laptop, until Stop"),
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
      this.els.send.removeAttribute("disabled");
      this.render();
    }
  }

  private async post(path: string, body: unknown): Promise<void> {
    try {
      const r = await api(path, { body });
      if (r.status) this.payload = r;
      this.render();
    } catch (e) {
      this.els.working.textContent = (e as Error).message;
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
