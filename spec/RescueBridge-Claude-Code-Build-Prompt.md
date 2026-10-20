# RescueBridge — Complete Claude Code Build Prompt

Prepared for Balu on 20 October 2026. This is an implementation specification, not a claim that the prototype already exists or that it will win a prize.

## How to use this file

Paste the entire section from "MASTER PROMPT" through "END MASTER PROMPT" into Claude Code. Alternatively, give Claude Code this file's absolute path and tell it to read and implement the entire specification. Use a dedicated RescueBridge project directory. Keep the original specification so later work can be checked against it.

# MASTER PROMPT

You are my principal engineer, product designer, and verification lead. Build RescueBridge, a serious working prototype of a voice-first Windows recovery assistant. Do the implementation, run the appropriate checks, repair failures, and deliver reproducible evidence. Do not stop after a plan, scaffolding, a polished landing page, or a simulated success.

I am Balu, a solo developer in India using a Windows laptop with 16 GB RAM and a Samsung phone. I have Claude Max for development and a very limited cash budget. I have previously experienced a mouse problem that made normal interaction difficult. That experience is the product's starting point. Do not invent additional personal stories, users, testimonials, partnerships, or impact numbers.

Aim for a product that a demanding engineering team could evaluate. Do not promise first prize, acquisition, production readiness, universal repair, or a world's-first invention.

## 1. Product goal and boundaries

The product helps a person recover access to an existing Windows work session through a second interaction channel when normal input, audio, or window access is impaired.

Example mission: "My interview starts soon. My clicks are wrong, I cannot hear anything, and my notes disappeared. Help me get ready while keeping my work open."

The system investigates, asks focused questions, proposes supported changes, obtains approval, applies the changes through fixed Windows adapters, observes the actual resulting state, and asks the person to confirm the symptom is resolved.

A clear distinction must exist among:
- The person reported a symptom.
- A diagnostic observation was obtained.
- A possible explanation is supported by that observation.
- A repair was proposed.
- Permission was granted for that exact proposal.
- A repair was attempted.
- The resulting system state was observed.
- The person confirmed the symptom was resolved.

An API returning success is not sufficient proof of repair. An unmuted endpoint does not prove a physical speaker is audible. A window intersecting a display does not prove the user can see and use it.

Initial target: an ordinary Windows user, including someone who needs help using settings. Do not claim disability-specific effectiveness without appropriate real-user evaluation.

This prototype requires prior installation/pairing, a responsive Windows session, a running helper, and a working phone-to-laptop connection. It cannot recover a powered-off machine, bypass the lock screen, repair all hardware, or operate when every communication path is unavailable.

## 2. Contest context and source verification

Target the Alexa+ track of Build, Ship, Shape: Amazon Developer Hackathon. Deadline: 23 October 2026, noon PDT; 24 October, 00:30 IST. Target submission by 23 October, 21:00 IST.

At the researched rules revision:
- A self-hosted MCP server uses Streamable HTTP and protocol 2025-11-25 or an accepted later version.
- A custom simulated Alexa+ experience is permitted; gated Alexa+ tools are unavailable to participants.
- Supply GitHub source, license/access, setup instructions, English materials, product feedback, and a public YouTube/Vimeo demo under three minutes.
- Genuine friction entries can earn a bonus.
- AWS hosting is not necessary for this plan.

Recheck the official pages before final packaging. Record retrieval date and any changes. Label our interface "Independent Alexa+ concept simulator"; do not imply native certification, official access, endorsement, or actual Alexa deployment.

Use official SDK documentation and installed types to select supported APIs. Pin compatible dependencies and commit lockfiles. Do not invent packages such as a gated Alexa CLI or guess an SDK's API from old examples.

Sources are listed at the end. Competition facts must remain separate from our design choices.

## 3. Product weaknesses and required responses

Address these in implementation and evidence, not marketing alone.

| Weakness | Required response |
| --- | --- |
| Three setting changes can look trivial | Demonstrate investigation, clarification, combined symptoms, approval, observed outcomes, and unresolved-case handling in one work-recovery session. |
| Repair assistants and remote support already exist | Position around a second interaction channel, preserving the current work session, and inspectable recovery evidence. No absolute novelty claims. |
| The user may be unable to install software during a failure | Make prior installation and pairing explicit. Provide a short setup and a connectivity/voice check while the PC works. |
| A model may invent a cause or say "fixed" prematurely | Require observation references, controlled transitions, server-generated status, and user confirmation. |
| Remote control can be abused | Enforce authenticated pairing, limited capabilities, exact approval, expiration, revocation, and per-device scope in code. |
| Local voice/model performance may be poor | Benchmark on this hardware early; disclose providers and unsupported paths. Keep text and touch available. |
| Demo success can be hardcoded | Separate fixture, real Windows, and controlled live-lab modes. Test unseen wording and combinations. |
| A broad build will miss the deadline | Finish a complete vertical slice first. Add scope only after its gate passes. |

## 4. Initial recovery workflows — exactly three

Implement these narrow workflows well. Treat every other repair as unsupported until deliberately added and validated.

### A. Unexpected mouse-button reversal

Observe the Windows button mapping and ask the user's intended preference. A swapped mapping may be an intentional left-handed configuration, not a fault.

If the observed setting conflicts with the user's confirmed preference, propose the exact correction. After approval, set it using a supported Windows API and read it again. Offer a visible test-click target and record the user's result.

Do not infer hardware health from SM_MOUSEPRESENT or a single setting. If the mouse cannot physically move, this workflow may not explain the problem; keep that symptom unresolved and explain the next manual check.

### B. Muted default playback endpoint

Read endpoint identity, mute state, and current volume through Windows Core Audio. Propose unmuting the identified endpoint and an explicitly stated bounded volume, only when relevant to the symptom. Default suggested test level: 20%, adjustable by the user within a sensible bound.

Bind approval to that endpoint and the observed state. If the default endpoint or relevant state changes before execution, re-observe and revise the proposal.

Read the state again after the operation. With approval, play a brief bounded test tone, then ask whether the person heard it. If not, the symptom remains unresolved. The MVP may report other endpoints and suggest a manual next step; automatic output-device switching is a later feature unless fully validated.

### C. Recover an off-screen window

Enumerate eligible top-level windows in the current user's session and active monitor bounds, accounting for DPI and multiple monitors. Identify plausible off-screen candidates. Ask which app if ambiguous.

Use a helper-issued short-lived target reference that binds HWND, process identity/creation time, and relevant window state. Avoid raw arbitrary handles supplied by the model.

Propose repositioning the selected eligible window onto an active display while preserving its content and reasonable dimensions. Revalidate the target and monitor state immediately before changing it. Observe the new bounds, check display intersection, and obtain user confirmation.

Elevated/system windows and unsupported desktops must be reported as unsupported. Do not bypass Windows integrity boundaries.

Use our own small "WorkPad" demo application for reproducible window tests with unsaved text. Demonstrate that its document remains intact. Do not claim preservation of arbitrary app content beyond what was observed.

## 5. Architecture and default implementation choices

Keep the architecture understandable and small:
1. Responsive browser client for phone and desktop.
2. Backend-for-frontend that authenticates sessions and acts as a real MCP client.
3. MCP server exposing goal-oriented recovery tools.
4. Separate Windows helper process with a narrow local interface.
5. SQLite for session, proposal, observation, operation, and evidence records.
6. One model adapter for language understanding and explanation.

Prefer a TypeScript browser app and Python backend/MCP/helper if the installed tooling supports them cleanly. A small alternative is acceptable if it reduces dependencies without weakening the contracts. Avoid microservices, queues, vector databases, Kubernetes, agent councils, and speculative abstraction layers.

The web client must reach recovery tools through a real MCP client over Streamable HTTP. Do not implement a parallel fake web route that bypasses the authority and state logic. UI approval, Stop, pairing, and session-management endpoints may be separate, but they must call the same underlying authorization/state service.

Treat MCP transport session IDs as transport state, not authentication or recovery-session ownership. Persist application sessions independently, bind them to authenticated devices, and test reconnect/transport-session replacement without losing or crossing user state.

The LLM cannot access a shell, arbitrary Python, arbitrary PowerShell, arbitrary HTTP targets, filesystem mutations, process termination, or direct Windows APIs. It can request only validated application operations.

The helper executes as the current Windows user and accepts only a fixed operation schema. Private helper IPC must be inaccessible to the browser and protected using an appropriate current-user-only mechanism. If using local HTTP, bind loopback, authenticate it separately, validate Host/Origin, and do not assume localhost alone is authorization.

Create real adapters and fixture adapters behind the same domain interfaces. Keep evidence of which adapter produced each observation. Do not make every platform run by silently replacing Windows operations with mocks.

## 6. Tool contracts, observations, and state

A practical starting tool surface:
- start_recovery: create/resume a bounded mission.
- inspect_recovery: gather supported diagnostics relevant to symptoms.
- propose_recovery: create an immutable, validated proposal.
- apply_recovery: execute a currently approved proposal.
- verify_recovery: obtain fresh outcome observations.
- record_user_result: record a person-confirmed functional result.
- get_recovery_status: return current status and evidence.
- stop_recovery: revoke pending authority and stop further work.
- undo_recovery: request a guarded inverse operation.

Adjust names if helpful; avoid redundant tool proliferation. Stop must also be available through a direct authenticated UI path so it never depends on a model turn.

Model input references observations by ID. Every observation includes device/session ID, source, timestamp, freshness/expiration, status, and normalized facts. Separate observed facts, user-reported facts, and hypotheses. Do not expose sensitive window titles or unrelated diagnostic data to the model by default.

Use validated schemas with bounded fields and closed enumerations. Reject unknown tools, unknown properties where appropriate, malformed targets, non-finite numbers, invalid bounds, and observations from another session/device.

Per-issue state can follow:
REPORTED -> INSPECTING -> NEEDS_CLARIFICATION or PROPOSED -> APPROVED -> APPLYING -> VERIFYING -> AWAITING_USER_CONFIRMATION -> RESOLVED.

Include explicit UNRESOLVED, FAILED, STOPPED, and UNSUPPORTED states. Do not encode communication loss as a negative observation such as "not muted" or "no problem found."

Prefer one issue record per symptom plus a mission summary. The mission can be partially recovered: one issue resolved, another unresolved. Never collapse partial results into "all fixed."

Freshness must come from fresh adapter observations, not copying a model's earlier statement.

## 7. Approval, identity, and revocation must be enforced

Pair the phone while the laptop is working. The laptop shows an expiring one-use pairing code/QR; the user explicitly accepts the requesting phone locally. Rate-limit attempts. Generate proper random session credentials. Codes are not long-lived bearer tokens.

Keep browser credentials out of URLs, logs, and model context. Prefer secure HttpOnly same-site cookies for browser sessions. Enforce allowed origins and CSRF protections. MCP and helper credentials remain server-side. Document the limits of the prototype's device identity.

The approved proposal must bind:
- User session and device.
- Exact action, parameters, and target.
- Observation references and required preconditions.
- Proposal version and current permission revision.
- Expiration and an idempotency key.
- The description shown to the user.

The model cannot grant approval by calling a tool with approved=true or by generating a sentence saying the user agreed. The first release should use a clear approve control on the paired phone for the exact displayed proposal. Voice can request approval; voice-only authorization is optional later and must not be inferred from a stray "yes."

A deterministic authority service records authenticated approval. apply_recovery validates it independently.

If the target, relevant precondition, or proposal changes, the previous approval is invalid. Serialize mutations per device and make approval consumption/retry behavior atomic. A model-controlled field cannot disable validation.

Stop increments a permission revision or equivalent fence, revokes unused proposals, and prevents queued or delayed operations from executing. Explain that Stop cannot undo an action that has already completed; report that action and offer a guarded Undo when possible.

Define Stop acknowledgement honestly across processes. Show "Stop requested" immediately; show a confirmed stop only after the helper acknowledges its execution fence. A bounded atomic Windows call already in progress may finish and must be recorded. The helper must reject queued writes under the old authority before acknowledging Stop. If the helper is unreachable, report remote-stop status as unknown instead of claiming the OS worker has stopped. Avoid detached tasks that can perform later writes outside this control.

Do not expose the Windows helper or a write-capable unauthenticated MCP endpoint to the public internet. Do not create firewall exemptions, install a root certificate, enable startup persistence, or raise privileges silently.

## 8. Operation evidence, retries, restart, and Undo

Each operation record needs a unique ID, proposal ID, adapter mode, timestamps, before observation, requested action, execution result, after observation, and separate user confirmation.

Use outcome categories such as:
- NOT_ATTEMPTED
- APPLIED_STATE_VERIFIED
- APPLIED_STATE_NOT_VERIFIED
- NO_CHANGE_NEEDED
- REJECTED_OR_EXPIRED
- FAILED
- OUTCOME_UNKNOWN

These are operation outcomes; issue resolution still needs the appropriate functional confirmation.

Do not claim exactly-once execution across crashes without a real mechanism. Record intent before execution, identify duplicate requests, and reconcile ambiguous operations using current state after restart. Do not blindly repeat an action whose outcome is unknown.

If Windows changed state but the client timed out, a retry should retrieve/reconcile the existing operation rather than create a second uncontrolled action. Distinguish expected desired-state idempotency from an evidence guarantee.

On restart, restore the session without automatically resuming stale approvals. Reinspect before any new mutation.

Undo must be an explicit, authorized guarded inverse operation. Store the original state, but do not overwrite a setting another actor subsequently changed. Compare current state with the expected post-repair state; if it differs, block automatic rollback and explain. Report partial rollback honestly.

Do not silently "undo" a person's later choices. Do not describe this as operating-system-level transactional rollback.

## 9. Language model and voice

Inspect installed Ollama models without downloading a large model automatically. Choose a tool-capable model that fits this laptop only after a small local latency/correctness check.

Do not assume Claude Max supplies Anthropic API credits. Default to a local runtime; optional paid services require explicit configuration. Record provider/model/version and data destination. No silent provider fallback.

Use the model for paraphrase understanding, focused clarification, selecting supported inspections, summarizing evidence, and explaining validated proposals. Deterministic code decides authorization, applicability, state transitions, and completion labels.

Bound the model loop: default at most 4 model turns and 8 tool calls per user request, with a configurable wall-clock limit and a visible timeout. Store useful progress and allow continuation. Do not let it retry forever.

Use real microphone input and spoken output. Test voice in the actual target browser. Browser speech recognition may depend on a remote service and vary across devices; do not advertise it as offline. An optional local speech path can use an available lightweight recognizer only if installation, latency, and accuracy are measured.

While the laptop is muted, speech must remain available on the phone. Display captions, the recognized transcript, and a clear listening/speaking state. Let the user edit a misrecognized transcript before consequential interpretation.

A dedicated Stop button and text/touch input are mandatory. Interrupting spoken output should be possible; cancelling speech must not be confused with revoking repair permission. Make those states understandable.

Never claim that native Alexa was tested if the input comes from our own browser simulator.

## 10. Phone setup and transport are an early feasibility gate

Do not leave phone connectivity to the last day.

First support desktop localhost for development. Then provide an explicit LAN mode with authentication and appropriate HTTPS for phone microphone access. Use a documented local development certificate/trust process confined to the task; ask before trust-store or firewall changes. Do not silently expose the helper, and do not depend on an unprotected public tunnel.

Show hostname/address, connection state, pairing status, and actionable setup errors. Check common causes such as different Wi-Fi networks and client isolation without inventing diagnoses. Never disable security software to make a connection work.

If mobile HTTPS/voice is blocked, keep implementing the desktop simulator and domain engine while reporting the precise mobile blocker. Do not mark the phone experience complete based on a desktop test.

Provide a setup doctor for supported OS/runtime, dependencies, helper health, model reachability, available voice mode, pairing connectivity, and permission requirements. It should be read-only by default. Log timings for an actual fresh setup; treat "under ten minutes" as a target, not an unmeasured claim.

Do not require an administrator account for the three core recovery operations. Detect and report unsupported privilege contexts.

## 11. Product interface

Build a usable tool, not a marketing landing page.

Primary screen:
- Short description of what this recovery session can do.
- Device name and trustworthy connected/disconnected state.
- Large talk control, transcript, concise spoken/captioned responses.
- Current issue and one focused question at a time.
- Proposed action card with exact effect and approval control.
- Large persistent Stop.
- Recovery evidence with observed system result and user result shown separately.
- Continue, try supported next check, Undo, or prepare handoff as appropriate.

Keep developer logs in an expandable diagnostic view. Do not make a person understand MCP, hashes, model routing, or API schemas to recover their laptop.

Use high contrast, keyboard operation, visible focus, readable touch targets, reduced motion, and responsive layout. Say exactly what was tested; automated accessibility checks are not proof of usability for every disability.

Display source/mode labels clearly: Real Windows, Fixture Simulation, and Controlled Live Lab. The independent Alexa+ simulator label is separate: the interface can simulate an Alexa+ host while Windows effects are real.

## 12. Controlled recovery lab

Build a reproducible test lab, not a fake success generator.

Default automated tests use in-memory/fixture adapters and must not mutate the developer's Windows settings.

Include a small owned WorkPad app whose position and unsaved text can be controlled and observed. Use it for window demonstrations instead of disrupting personal work apps.

Live lab mode is opt-in and separately armed by the user for a named session, a short duration, and exact allowed changes. Show the snapshot and scope. Use a manual recovery control and a cleanup/watchdog strategy appropriate to reversible settings; do not promise cleanup after power loss or total process failure.

Without that live authorization, implement and test the adapter contracts but report real-host behavior as unverified. Continue useful work without repeatedly asking to run live mutations.

Allowed live faults: temporary unexpected button mapping, temporary mute/volume state, and positioning our owned WorkPad window off-screen. Do not disable input devices, block user input, change drivers, alter networking, force reboots, or kill apps.

The harness knows the injected condition and retains a ground-truth manifest; the agent does not receive that manifest or the fault seed. The agent may inspect only its ordinary diagnostic tools. Reset to a clean recorded state between trials.

Test individual faults, combinations, no-fault conditions, and symptoms unsupported by the three recipes. Keep fixture-evaluation evidence separate from live-Windows and human-use evidence.

## 13. Validation that matters

Create behavioral tests capable of catching real failures. Do not pad counts with tests that restate constants or simply assert our implementation's structure.

Cover at least:
- Supported successful flows and combined symptoms.
- Intentional left-handed mapping is not changed without an explicit preference.
- Ambiguous app/target requires clarification.
- No permission, denied permission, expired permission, cross-device permission, and stale proposal.
- Default audio endpoint or active monitor changes between proposal and execution.
- A window handle is reused by a different process.
- OS action fails, returns success without an observed state change, or becomes unobservable.
- Muted=false but the user still cannot hear: unresolved symptom.
- Stop while work is queued; delayed callbacks cannot apply revoked work.
- Duplicate request, client timeout after application, process restart, and unknown outcome.
- Guarded Undo after an intervening user change.
- Unsupported hardware symptom and unavailable helper.
- Malformed model calls and untrusted text attempting to authorize an action.
- Foreign origin, unauthenticated access, pairing reuse, and session separation.

Run protocol-level MCP tests through the real client, not only direct Python function calls. Verify initialize, tools/list, and tools/call, with an accepted protocol version and actual Streamable HTTP.

Use fresh-clone setup, lint/type checks, meaningful unit/integration tests, and a real browser smoke path appropriate to the implemented stack.

Measure end-to-end recovery time, model/voice latency, incorrect changes, false completion claims, and unresolved outcomes on a recorded scenario set. A useful initial target is roughly 20-30 varied scenarios; only report the number actually executed. Report fixture and live results separately.

Use a small held-out set of user phrasings/condition combinations that was not used to tune the flow. The harness must not leak fault IDs to the agent.

For human trials, prepare a short script and recording sheet. Do not fabricate participants or results. If none were run, say "zero human participants" and provide the ready-to-run protocol.

Do not claim superiority to ChatGPT, Copilot, Quick Assist, or Alexa without an appropriate actual comparison. A comparison to a deliberately simple command-success baseline must be labelled as such.

## 14. Build gates and sequencing

Maintain short durable checkpoints in the repository: current status, files changed, actual checks, outstanding blockers, and next action. After context compaction, read the checkpoint and continue; do not restart from scaffolding.

Gate 0: inspect the working directory and applicable instructions.
- Preserve existing code and user changes.
- Prefer a new dedicated RescueBridge folder if there is no existing RescueBridge project.
- Inspect OS, Python/Node versions, available tools, and local model options.
- Recheck official dependencies and produce a small plan.
- Start implementing immediately after the plan.

Gate 1: prove the vertical slice before polish.
- Browser -> real MCP client -> MCP server -> helper -> fresh diagnostic observation.
- Exact proposal -> authenticated approval -> bounded operation -> fresh verification.
- Start with audio and a fixture adapter, then validate the real adapter in an authorized lab.
- Test phone connectivity and microphone early.
- Report specific blockers; continue independent work.

Gate 2: implement the domain engine and remaining two adapters.
- SQLite state, proposals, evidence, per-device mutation control.
- Mouse preference clarification and window target validation.
- Combined symptoms, partial results, guarded Undo, and restart reconciliation.

Gate 3: complete the user experience and model/voice path.
- Actual microphone, captions, spoken responses, Stop, pairing, and session continuation.
- Use the real domain service and MCP path throughout.
- Measure performance and adjust within scope.

Gate 4: validate and prepare submission.
- Run meaningful tests, fresh setup, browser checks, and authorized live trials.
- Correct failures before expanding scope.
- Produce reproducible evidence, documentation, and a short demo plan.
- Freeze features before the final recording.

Do not spend the first day choosing colors or building a large agent framework. If time is short, cut optional features while preserving one complete, honest recovery experience.

## 15. Required repository deliverables

Use a simple structure appropriate to the chosen stack. Include:
- Runnable browser app, backend/MCP server, and Windows helper.
- Domain schemas, authorization/state engine, real/fixture adapters.
- WorkPad and controlled-lab tooling.
- Reproducible tests and scenario manifests.
- Windows-native setup/start/stop scripts with safe process cleanup.
- Dependency lockfiles and configuration examples without secrets.
- A recognized open-source license appropriate to original code and dependency notices.
- A README with exact setup, commands, supported versions, supported repairs, testing modes, limitations, and troubleshooting.

Write these documents, concise and specific:
- PRODUCT.md: problem, target user, proposed differentiation, known alternatives, and validation assumptions.
- ARCHITECTURE.md: process boundaries, contracts, data flow, and the authority model.
- THREAT_MODEL.md: meaningful threats, trust assumptions, implemented controls, and residual gaps.
- VALIDATION.md: exact commands, environment, timestamp, measured results, failures, and evidence paths.
- PRIVACY.md: diagnostic fields, retention, credentials, provider data flow, and deletion controls.
- LIVE_LAB.md: scope, arming, recovery/cleanup, and exact safe rehearsal steps.
- KNOWN_LIMITATIONS.md: what is real, simulated, unsupported, or unverified.
- DEMO_SCRIPT.md: a proposed recording script under 3 minutes with real effects and mode labels.
- SUBMISSION.md: project description, testing instructions, source/demo placeholders, and track fit.
- PRODUCT_FEEDBACK.md and FRICTION_LOG.md: only genuine tools used and problems actually encountered.
- NEXT.md or equivalent: current checkpoint and outstanding work.

Evidence artifacts must be redacted. Do not save personal screenshots, unrelated window titles, tokens, private documents, or raw microphone recordings by default. Use the owned WorkPad document and synthetic identities for shareable demos.

## 16. Demonstration and pitch requirements

Lead with a real problem and a working recovery early in the recording. A proposed sequence:
- 0:00-0:15: my actual motivation and the visible impaired workflow.
- 0:15-0:45: phone voice request, inspection, focused clarification.
- 0:45-1:35: exact approval, real recovery, observed result, user confirmation.
- 1:35-2:10: another symptom or a combined case; demonstrate preserved work.
- 2:10-2:35: a failure/unsupported case handled without false success.
- 2:35-2:55: architecture, measured evidence, limitations, and practical next step.

This is a target script; adjust to real measured latency. Do not edit footage to imply a faster or more autonomous interaction than occurred. Label cuts, simulated time, recorded commands, synthetic narration, and controlled faults where used.

Frame the product around recovering access to work through an available second channel. Do not center the pitch on the number of agents, test count, or fashionable framework names.

Keep commercial possibilities as hypotheses. Potential later directions include family support and bounded helpdesk workflows. Do not invent an enterprise sales pipeline or claim that Amazon will buy the project.

## 17. Optional work only after the primary experience passes

Potential later work:
- A real MCP Apps view if the host and available SDK support it.
- A genuinely reusable additional open-source recovery-contracts or fault-lab contribution.
- Additional diagnosed audio routing cases.
- A local voice mode after measuring performance.
- Explicitly enabled, user-controlled startup behavior or a signed installer.
- A privacy-preserving human handoff bundle with diagnostics and attempted actions.

Do not let optional work block the prototype. Do not add general remote mouse control, autonomous driver updates, broad shell access, boot repair, malware cleanup, a multi-tenant cloud fleet, or self-modifying recovery recipes to this first release.

## 18. Working expectations and final report

You are authorized to write project files, install ordinary project-scoped dependencies where allowed, and run non-mutating/local fixture checks. Make routine reversible implementation decisions without repeatedly asking me to choose.

Live host setting changes, privileged setup, external publishing, paid resources, and access to private accounts require their appropriate explicit authorization. Do not assume permission merely from an enthusiastic product goal. If blocked, explain the exact issue, continue other work, and clearly mark affected evidence unverified.

Do not contact organizers, users, companies, or other people; create accounts; send email; deploy publicly; or submit the hackathon entry without a separate instruction.

Before calling the build complete, provide:
1. What actually works and which adapter/provider was used.
2. Exact setup/start commands for me.
3. Tests actually executed with summarized results and evidence paths.
4. Real phone, microphone, and Windows behaviors tested; separate them from fixtures.
5. Known defects, incomplete gates, and unsupported cases.
6. A safe, specific next action to run the prototype.
7. Submission-ready files, with uncreated URLs clearly marked pending.

Never invent terminal output, benchmarks, test passes, recordings, user feedback, or completion. Code inspection is not runtime validation. A screenshot of a green UI is not proof of a real OS change.

Begin now: inspect the workspace, record the minimal plan, and implement Gate 1. Continue through the remaining gates within the actual available environment.

# END MASTER PROMPT

## Official references for implementation and submission

Checked for the research brief on 20 October 2026. Recheck before implementation or submission when an API/rule may have changed.

- Amazon official rules: https://amazonappdev2026.devpost.com/rules
- Amazon official FAQ: https://amazonappdev2026.devpost.com/details/faqs
- Amazon resources: https://amazonappdev2026.devpost.com/resources
- MCP Streamable HTTP specification: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- MCP official Python SDK: https://github.com/modelcontextprotocol/python-sdk
- MCP official TypeScript SDK: https://github.com/modelcontextprotocol/typescript-sdk
- Ollama tool calling: https://docs.ollama.com/capabilities/tool-calling
- Windows GetSystemMetrics: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getsystemmetrics
- Windows SwapMouseButton: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-swapmousebutton
- Windows IAudioEndpointVolume: https://learn.microsoft.com/en-us/windows/win32/api/endpointvolume/nn-endpointvolume-iaudioendpointvolume
- Windows GetWindowRect: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowrect
- Windows SetWindowPos: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos
- Windows MonitorFromRect: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-monitorfromrect
- Python Core Audio Windows library: https://github.com/AndreMiras/pycaw
- Browser SpeechRecognition compatibility/privacy considerations: https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition

## Research notes for honest positioning

The idea combines existing technologies; no exclusive novelty or patentability assessment was performed. Windows Get Help, Quick Assist, and computer-use agents are relevant alternatives. Investigate them rather than claiming that automated troubleshooting or remote recovery has never existed.

Publicly described hackathon entries include case-chasing, household consent, and verification systems. Our differentiation must be shown through the actual user experience and evidence, not ownership of the general idea of approval or verification. The complete event gallery was unpublished during the initial research, so this is not a comprehensive competitor assessment.

