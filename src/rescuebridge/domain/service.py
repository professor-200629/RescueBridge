"""RecoveryService: the deterministic authority and state engine.

Both the MCP tools and the browser's direct endpoints (approve, decline, Stop, user result) call THIS
service, so authorization and state rules exist in exactly one place.

Key guarantees enforced here (not by the model, not by the UI):
- Missions, issues, proposals and operations are scoped to the authenticated device; other devices get
  NOT_FOUND.
- A proposal is immutable; its digest binds mission, issue, approver device, action, parameters, target,
  observation references, preconditions, permission revision, expiry, idempotency key and the description.
- Approval exists only via `approve()` (authenticated UI path) for the exact digest the UI displayed.
- `apply()` re-validates the approval, re-observes fresh state, checks preconditions, records intent
  before execution, consumes the approval atomically, and executes once per proposal (idempotent retrieval
  on retries). Mutations are serialized per host.
- `stop()` bumps the host permission revision (fence), revokes unused proposals, and asks the helper to
  fence; it does not wait for the mutation lock.
- Issue resolution requires a person-confirmed functional result. API success alone never resolves.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import anyio

from rescuebridge.config import Settings
from rescuebridge.domain import recipes
from rescuebridge.domain.enums import (
    ADAPTER_MODE_LABEL,
    SYMPTOM_TO_KIND,
    ActionKind,
    AdapterMode,
    IssueKind,
    IssueState,
    MissionState,
    ObservationStatus,
    OperationOutcome,
    OperationPhase,
    ProposalKind,
    ProposalStatus,
    StopState,
    SymptomCategory,
    UserResult,
    UserResultSource,
)
from rescuebridge.domain.store import Store
from rescuebridge.domain.transitions import TransitionError, check
from rescuebridge.host.client import HelperTimeoutError, HelperUnavailableError, HostClient
from rescuebridge.ids import digest, new_id, now_ms

log = logging.getLogger("rescuebridge.service")

MAX_ISSUES_PER_MISSION = 8
OPEN_STATES = {s for s in IssueState} - {IssueState.RESOLVED, IssueState.UNSUPPORTED}
REVISABLE_ERRORS = {"PRECONDITION_FAILED", "ENDPOINT_CHANGED", "TARGET_CHANGED", "MONITORS_CHANGED", "TARGET_INVALID"}

UNSUPPORTED_TEXT = {
    SymptomCategory.MOUSE_NOT_MOVING: (
        "A pointer that does not move is usually a hardware, battery, receiver or connection problem. "
        "RescueBridge cannot repair that and will not change anything for it. Next manual checks: try the "
        "touchpad, re-seat the USB receiver or cable in another port, replace batteries, or check "
        "Settings > Bluetooth & devices with the keyboard (Win+I)."),
    SymptomCategory.OTHER: (
        "This is not one of the three supported recovery workflows (mouse button mapping, muted playback "
        "device, off-screen window). No changes will be made for it."),
}

AFFIRM = re.compile(r"\b(yes|yeah|yep|yup|heard|hear it|i can hear|works|working|it worked|can see|i see it|"
                    r"visible|fine now|correct|right one)\b", re.I)
NEGATE = re.compile(r"\b(no|nope|not|didn'?t|did not|don'?t|can'?t|cannot|still|nothing|never|wrong|broken)\b", re.I)


class DomainError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}


@dataclass(frozen=True)
class Principal:
    device_id: str
    session_id: str | None
    via: str  # "mcp" | "ui" | "host_console" | "system"

    @property
    def is_host_console(self) -> bool:
        return self.via == "host_console"


def _pct(v: float) -> int:
    return round(v * 100)


def describe_facts(kind: str, facts: dict[str, Any]) -> str:
    """Short plain-language summary of observed facts (for evidence and the model)."""
    if not facts:
        return "no facts (observation unavailable)"
    if kind == "mouse":
        return (f"primary button: {'RIGHT (swapped)' if facts.get('swap_effective') else 'LEFT (default)'}; "
                f"saved setting swapped={facts.get('swap_saved')}")
    if kind == "audio":
        d = facts.get("default")
        if not d:
            return "no default playback device"
        return f"default '{d['name']}': {'muted' if d['muted'] else 'unmuted'}, volume {_pct(d['volume_scalar'])}%"
    if kind == "windows":
        off = [c for c in facts.get("candidates", []) if c.get("offscreen")]
        return f"{facts.get('eligible_count', 0)} eligible windows, {len(off)} off-screen"
    if kind == "workpad":
        if not facts.get("running"):
            return "WorkPad not running"
        return f"WorkPad running, {facts.get('text_chars')} chars of unsaved text, text hash {str(facts.get('text_sha256'))[:12]}"
    if kind == "click_test":
        return f"click test: {facts.get('status', 'no result yet')}"
    return "observed"


def model_facts(kind: str, facts: dict[str, Any]) -> dict[str, Any]:
    """Redacted facts for the language model: no endpoint IDs, PIDs, rectangles or window titles."""
    if not facts:
        return {}
    if kind == "mouse":
        return {k: facts.get(k) for k in ("swap_effective", "swap_saved", "button_count")}
    if kind == "audio":
        def ep(e: dict[str, Any]) -> dict[str, Any]:
            return {"name": e["name"], "muted": e["muted"], "volume_percent": _pct(e["volume_scalar"]),
                    "is_default": e["is_default"]}
        d = facts.get("default")
        return {"default": ep(d) if d else None, "other_outputs": [ep(e) for e in facts.get("endpoints", [])
                                                                  if not e["is_default"]][:4]}
    if kind == "windows":
        return {"display_count": len(facts.get("monitors", [])), "eligible_windows": facts.get("eligible_count", 0),
                "excluded_counts": facts.get("excluded_counts", {}),
                "candidates": [{"target_ref": c["target_ref"], "app": c["app_label"], "offscreen": c["offscreen"],
                                "visible_percent": round(c["visible_fraction"] * 100),
                                "title_bar_reachable": c["caption_reachable"], "supported": c["supported"],
                                "unsupported_reason": c["unsupported_reason"]}
                               for c in facts.get("candidates", []) if c["offscreen"] or c["is_workpad"]][:8]}
    if kind == "workpad":
        return {"running": facts.get("running"), "unsaved_text_chars": facts.get("text_chars")}
    if kind == "click_test":
        return {"status": facts.get("status"), "primary_clicks": facts.get("primary_clicks"),
                "secondary_clicks": facts.get("secondary_clicks")}
    return {}


class RecoveryService:
    def __init__(self, store: Store, host: HostClient, settings: Settings, *, host_id: str,
                 lab_armed: Any = None) -> None:
        self.store = store
        self.host = host
        self.settings = settings
        self.host_id = host_id
        self._mutation_lock = anyio.Lock()  # one host per backend: serialize all mutations
        self._lab_armed = lab_armed or (lambda: False)
        self.execute_timeout_s = 10.0
        self.last_helper_health: dict[str, Any] = {"reachable": None, "checked_at": None}

    # ===================================================================================== helpers
    def _host(self) -> dict[str, Any]:
        h = self.store.get("hosts", self.host_id)
        if h is None:
            raise DomainError("NOT_FOUND", "host not registered")
        return h

    def revision(self) -> int:
        return int(self._host()["permission_revision"])

    def adapter_mode(self, raw_mode: str | None) -> AdapterMode:
        if raw_mode == AdapterMode.REAL_WINDOWS.value:
            return AdapterMode.LIVE_LAB if self._lab_armed() else AdapterMode.REAL_WINDOWS
        return AdapterMode.FIXTURE

    def _mission(self, principal: Principal, *, active_only: bool = True) -> dict[str, Any] | None:
        sql = "SELECT * FROM missions WHERE device_id = ? AND host_id = ?"
        if active_only:
            sql += " AND state = 'ACTIVE'"
        return self.store.one(sql + " ORDER BY created_at DESC LIMIT 1", (principal.device_id, self.host_id))

    def _issue_for(self, principal: Principal, issue_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(issue_id, str) or len(issue_id) > 80:
            raise DomainError("BAD_INPUT", "malformed issue id")
        issue = self.store.get("issues", issue_id)
        mission = self.store.get("missions", issue["mission_id"]) if issue else None
        if not issue or not mission or mission["device_id"] != principal.device_id or mission["host_id"] != self.host_id:
            raise DomainError("NOT_FOUND", "no such issue for this device")
        return issue, mission

    def _proposal_for(self, principal: Principal, proposal_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(proposal_id, str) or len(proposal_id) > 80:
            raise DomainError("BAD_INPUT", "malformed proposal id")
        p = self.store.get("proposals", proposal_id)
        mission = self.store.get("missions", p["mission_id"]) if p else None
        if not p or not mission or mission["device_id"] != principal.device_id or p["host_id"] != self.host_id:
            raise DomainError("NOT_FOUND", "no such proposal for this device")
        return p, mission

    def _set_state(self, issue: dict[str, Any], new: IssueState, reason: str, **changes: Any) -> dict[str, Any]:
        cur = IssueState(issue["state"])
        if cur != new:
            try:
                check(cur, new)
            except TransitionError as exc:
                raise DomainError("INVALID_STATE", str(exc), state=cur.value) from exc
        if new == IssueState.INSPECTING:
            changes.setdefault("next_manual_step", None)  # a fresh inspection supersedes earlier advice
        changes.update({"state": new.value, "updated_at": now_ms()})
        with self.store.tx():
            self.store.update("issues", issue["id"], changes)
            self.store.insert("issue_events", {"issue_id": issue["id"], "from_state": cur.value, "to_state": new.value,
                                               "reason": reason[:300], "at": now_ms()})
        issue.update(changes)
        return issue

    # ===================================================================================== observe
    async def _observe(self, mission: dict[str, Any], issue_id: str | None, kind: str,
                       test_id: str | None = None) -> dict[str, Any]:
        t = now_ms()
        facts: dict[str, Any] = {}
        status, error, raw_mode, source = ObservationStatus.OK, None, None, "windows_helper"
        try:
            resp = await self.host.observe(kind, test_id=test_id)
            raw_mode = resp.get("mode")
            if resp.get("ok"):
                facts = resp["result"]
            else:
                code = resp.get("error", {}).get("code", "OS_ERROR")
                status = ObservationStatus.UNAVAILABLE if code == "UNOBSERVABLE" else ObservationStatus.ERROR
                error = f"{code}: {resp.get('error', {}).get('message', '')}"
            self.last_helper_health = {"reachable": True, "checked_at": now_ms(), "mode": raw_mode}
        except HelperUnavailableError as exc:
            status, error, source = ObservationStatus.UNAVAILABLE, f"helper unreachable: {exc}", "backend"
            self.last_helper_health = {"reachable": False, "checked_at": now_ms(), "error": str(exc)}
        mode = self.adapter_mode(raw_mode) if raw_mode else AdapterMode.FIXTURE if self.settings.host_adapter == "fixture" else AdapterMode.REAL_WINDOWS
        obs = {
            "id": new_id("obs"), "mission_id": mission["id"], "host_id": self.host_id, "issue_id": issue_id,
            "kind": kind, "adapter_mode": mode.value, "source": source, "status": status.value, "observed_at": t,
            "expires_at": t + self.settings.observation_ttl_s * 1000, "facts": facts,
            "model_facts": model_facts(kind, facts), "error": error,
        }
        self.store.insert("observations", obs)
        return obs

    async def _observe_kinds(self, mission: dict[str, Any], issue_id: str | None,
                             kinds: list[str]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[str]]:
        facts: dict[str, dict[str, Any]] = {}
        observations, problems = [], []
        for kind in kinds:
            obs = await self._observe(mission, issue_id, kind)
            observations.append(obs)
            if obs["status"] == ObservationStatus.OK.value:
                facts[kind] = obs["facts"]
            elif kind != "workpad":  # workpad facts are optional context
                problems.append(f"{kind}: {obs['error']}")
        return facts, observations, problems

    def _obs_view(self, obs: dict[str, Any]) -> dict[str, Any]:
        return {"observation_id": obs["id"], "kind": obs["kind"], "status": obs["status"],
                "source": ADAPTER_MODE_LABEL[AdapterMode(obs["adapter_mode"])], "observed_at": obs["observed_at"],
                "fresh_until": obs["expires_at"], "summary": describe_facts(obs["kind"], obs["facts"]),
                "facts": obs["model_facts"], "error": obs["error"]}

    # ===================================================================================== missions
    def start_recovery(self, principal: Principal, goal: str, symptoms: list[dict[str, Any]]) -> dict[str, Any]:
        goal = (goal or "").strip()[:300] or "Recover my laptop session"
        if not isinstance(symptoms, list) or len(symptoms) > 5:
            raise DomainError("BAD_INPUT", "symptoms must be a list of at most 5 items")
        mission = self._mission(principal)
        t = now_ms()
        with self.store.tx():
            if mission is None:
                mission = {"id": new_id("msn"), "host_id": self.host_id, "device_id": principal.device_id, "goal": goal,
                           "state": MissionState.ACTIVE.value, "created_at": t, "updated_at": t,
                           "stop_state": StopState.NONE.value}
                self.store.insert("missions", mission)
            issues = self.store.all("SELECT * FROM issues WHERE mission_id = ?", (mission["id"],))
            created = []
            for s in symptoms:
                cat = SymptomCategory(s["category"])
                words = str(s.get("user_words") or "")[:200]
                hint = (str(s.get("app_hint") or "")[:40]) or None
                open_same = next((i for i in issues if i["category"] == cat.value and i["state"] in OPEN_STATES), None)
                if open_same is not None:
                    if hint and not open_same.get("app_hint"):
                        self.store.update("issues", open_same["id"], {"app_hint": hint})
                    continue
                if len(issues) >= MAX_ISSUES_PER_MISSION:
                    raise DomainError("LIMIT", "too many issues in this recovery session")
                kind = SYMPTOM_TO_KIND[cat]
                state = IssueState.UNSUPPORTED if kind == IssueKind.UNSUPPORTED else IssueState.REPORTED
                issue = {"id": new_id("iss"), "mission_id": mission["id"], "kind": kind.value, "category": cat.value,
                         "user_words": words, "app_hint": hint, "state": state.value, "clarification": None,
                         "preference": {}, "findings": None,
                         "next_manual_step": UNSUPPORTED_TEXT.get(cat), "created_at": t, "updated_at": t}
                self.store.insert("issues", issue)
                self.store.insert("issue_events", {"issue_id": issue["id"], "from_state": None, "to_state": state.value,
                                                   "reason": "reported by the person", "at": t})
                issues.append(issue)
                created.append(issue["id"])
        return {"mission_id": mission["id"], "created_issue_ids": created, **self.status(principal, for_model=True)}

    # ===================================================================================== inspect
    async def inspect(self, principal: Principal, issue_id: str) -> dict[str, Any]:
        issue, mission = self._issue_for(principal, issue_id)
        if mission["state"] != MissionState.ACTIVE.value:
            raise DomainError("STOPPED", "this recovery session was stopped; use Continue to resume")
        state = IssueState(issue["state"])
        if state in (IssueState.UNSUPPORTED, IssueState.RESOLVED):
            return self._issue_result(issue, note=f"Issue is {state.value}; nothing to inspect.")
        if state in (IssueState.APPROVED, IssueState.APPLYING, IssueState.VERIFYING, IssueState.AWAITING_USER_CONFIRMATION):
            return self._issue_result(issue, note=f"Issue is {state.value}; inspection not repeated.")
        self._set_state(issue, IssueState.INSPECTING, "inspection started")
        return await self._analyze_and_route(issue, mission)

    async def _analyze_and_route(self, issue: dict[str, Any], mission: dict[str, Any],
                                 answers: recipes.Answers | None = None) -> dict[str, Any]:
        kind = IssueKind(issue["kind"])
        facts, observations, problems = await self._observe_kinds(mission, issue["id"], recipes.OBSERVE_KINDS[kind])
        obs_ids = [o["id"] for o in observations]
        if problems:
            self.store.update("issues", issue["id"], {"findings": {"observed": [], "problems": problems,
                                                                  "observation_ids": obs_ids}})
            issue = self.store.get("issues", issue["id"]) or issue
            return self._issue_result(issue, observations=observations,
                                      note=("Inspection could not complete because the Windows helper could not "
                                            "observe the state. This says NOTHING about whether the setting is wrong."))
        pref = issue.get("preference") or {}
        ans = answers or recipes.Answers()
        if ans.primary_button is None and pref.get("primary_button"):
            ans.primary_button = pref["primary_button"]
        if kind == IssueKind.MOUSE_BUTTONS:
            analysis = recipes.analyze_mouse(facts, ans)
        elif kind == IssueKind.AUDIO_OUTPUT:
            analysis = recipes.analyze_audio(facts, ans)
        elif kind == IssueKind.OFFSCREEN_WINDOW:
            analysis = recipes.analyze_window(facts, ans, issue.get("app_hint"))
        else:
            raise DomainError("UNSUPPORTED", "unsupported issue kind")
        findings = {"observed": analysis.findings, "explanation": analysis.explanation, "observation_ids": obs_ids}
        self.store.update("issues", issue["id"], {"findings": findings})
        issue["findings"] = findings
        proposal = None
        if analysis.outcome == "clarify":
            self._set_state(issue, IssueState.NEEDS_CLARIFICATION, "focused question",
                            clarification={"question": analysis.question, "options": analysis.options})
        elif analysis.outcome == "no_supported_cause":
            self._supersede_open_proposals(issue["id"], "no supported cause on fresh observation")
            self._set_state(issue, IssueState.UNRESOLVED, "no supported cause", clarification=None,
                            next_manual_step=analysis.next_manual_step)
        elif analysis.outcome == "propose" and analysis.plan is not None:
            proposal = self._create_proposal(mission, issue, analysis.plan, obs_ids)
            self._set_state(issue, IssueState.PROPOSED, f"proposal v{proposal['version']} created", clarification=None)
        issue = self.store.get("issues", issue["id"]) or issue
        return self._issue_result(issue, observations=observations, proposal=proposal)

    # ===================================================================================== propose
    async def propose(self, principal: Principal, issue_id: str, *, primary_button: str | None = None,
                      target_ref: str | None = None, volume_percent: int | None = None,
                      basis_observation_ids: list[str] | None = None) -> dict[str, Any]:
        issue, mission = self._issue_for(principal, issue_id)
        if mission["state"] != MissionState.ACTIVE.value:
            raise DomainError("STOPPED", "this recovery session was stopped; use Continue to resume")
        for oid in basis_observation_ids or []:
            obs = self.store.get("observations", oid) if isinstance(oid, str) else None
            if not obs or obs["mission_id"] != mission["id"] or obs["host_id"] != self.host_id:
                raise DomainError("BAD_INPUT", "observation reference does not belong to this session/device")
            if obs["expires_at"] < now_ms():
                raise DomainError("STALE", "observation reference has expired; inspect again")
        state = IssueState(issue["state"])
        if state not in (IssueState.NEEDS_CLARIFICATION, IssueState.PROPOSED, IssueState.INSPECTING,
                         IssueState.UNRESOLVED, IssueState.REPORTED):
            raise DomainError("INVALID_STATE", f"cannot propose while issue is {state.value}", state=state.value)
        if primary_button is not None and primary_button not in ("left", "right"):
            raise DomainError("BAD_INPUT", "primary_button must be 'left' or 'right'")
        if volume_percent is not None and not (recipes.MIN_TEST_VOLUME_PERCENT <= int(volume_percent) <= recipes.MAX_TEST_VOLUME_PERCENT):
            raise DomainError("BAD_INPUT", f"volume_percent must be {recipes.MIN_TEST_VOLUME_PERCENT}-{recipes.MAX_TEST_VOLUME_PERCENT}")
        if target_ref is not None and not re.fullmatch(r"wt_[0-9a-f]{16}", str(target_ref)):
            raise DomainError("BAD_INPUT", "malformed window target reference")
        if primary_button:
            self.store.update("issues", issue["id"], {"preference": {**(issue.get("preference") or {}),
                                                                     "primary_button": primary_button}})
            issue = self.store.get("issues", issue["id"]) or issue
        if state != IssueState.INSPECTING:
            self._set_state(issue, IssueState.INSPECTING, "re-observing before proposal")
        answers = recipes.Answers(primary_button=primary_button, target_ref=target_ref, volume_percent=volume_percent)  # type: ignore[arg-type]
        return await self._analyze_and_route(issue, mission, answers)

    def _supersede_open_proposals(self, issue_id: str, reason: str) -> None:
        self.store.execute(
            "UPDATE proposals SET status = ?, status_reason = ? WHERE issue_id = ? AND status IN ('PENDING','APPROVED')",
            (ProposalStatus.SUPERSEDED.value, reason, issue_id))

    @staticmethod
    def proposal_digest(p: dict[str, Any]) -> str:
        bound = {k: p[k] for k in ("id", "mission_id", "issue_id", "host_id", "approver_device_id", "kind", "version",
                                   "action", "params", "target", "observation_ids", "preconditions",
                                   "permission_revision", "expires_at", "idempotency_key", "description",
                                   "undo_of_operation_id")}
        return digest(bound)

    def _create_proposal(self, mission: dict[str, Any], issue: dict[str, Any], plan: recipes.ProposalPlan,
                         obs_ids: list[str], undo_of: str | None = None) -> dict[str, Any]:
        t = now_ms()
        with self.store.tx():
            if plan.kind in (ProposalKind.REPAIR, ProposalKind.UNDO):
                prev = self.store.one("SELECT id FROM proposals WHERE issue_id = ? AND status IN ('PENDING','APPROVED') "
                                      "AND kind IN ('REPAIR','UNDO') ORDER BY version DESC LIMIT 1", (issue["id"],))
                self.store.execute("UPDATE proposals SET status = ?, status_reason = ? WHERE issue_id = ? AND "
                                   "status IN ('PENDING','APPROVED') AND kind IN ('REPAIR','UNDO')",
                                   (ProposalStatus.SUPERSEDED.value, "replaced by a newer proposal", issue["id"]))
            else:
                prev = None
                self.store.execute("UPDATE proposals SET status = ?, status_reason = ? WHERE issue_id = ? AND "
                                   "status = 'PENDING' AND kind = 'TEST'",
                                   (ProposalStatus.SUPERSEDED.value, "replaced by a newer test", issue["id"]))
            version = int((self.store.one("SELECT MAX(version) AS v FROM proposals WHERE issue_id = ?",
                                          (issue["id"],)) or {}).get("v") or 0) + 1
            p = {
                "id": new_id("prop"), "mission_id": mission["id"], "issue_id": issue["id"], "host_id": self.host_id,
                "approver_device_id": mission["device_id"], "kind": plan.kind.value, "version": version,
                "action": plan.action.value, "params": plan.params, "target": plan.target, "observation_ids": obs_ids,
                "preconditions": {**plan.preconditions, "_original_state": plan.original_state,
                                  "_expected_post_state": plan.expected_post_state},
                "permission_revision": self.revision(), "created_at": t,
                "expires_at": t + self.settings.proposal_ttl_s * 1000, "idempotency_key": new_id("idem"),
                "description": plan.description, "status": ProposalStatus.PENDING.value, "status_reason": None,
                "undo_of_operation_id": undo_of, "supersedes_id": prev["id"] if prev else None,
            }
            p["digest"] = self.proposal_digest(p)
            self.store.insert("proposals", p)
        return p

    # ===================================================================================== approval (UI only)
    def approve(self, principal: Principal, proposal_id: str, displayed_digest: str) -> dict[str, Any]:
        if principal.via != "ui" or not principal.session_id:
            raise DomainError("FORBIDDEN", "approval is only accepted from the paired device's approve control")
        p, mission = self._proposal_for(principal, proposal_id)
        t = now_ms()
        with self.store.tx():
            p = self.store.get("proposals", proposal_id) or p
            if p["approver_device_id"] != principal.device_id:
                raise DomainError("NOT_FOUND", "no such proposal for this device")
            if mission["state"] != MissionState.ACTIVE.value:
                raise DomainError("STOPPED", "recovery session is stopped")
            if p["status"] != ProposalStatus.PENDING.value:
                raise DomainError("NOT_PENDING", f"proposal is {p['status']}", status=p["status"])
            if p["expires_at"] < t:
                self.store.update("proposals", p["id"], {"status": ProposalStatus.EXPIRED.value, "status_reason": "expired before approval"})
                raise DomainError("EXPIRED", "proposal expired before approval; inspect again")
            if p["digest"] != self.proposal_digest(p) or not isinstance(displayed_digest, str) or displayed_digest != p["digest"]:
                raise DomainError("STALE", "the displayed proposal does not match the current proposal")
            if p["permission_revision"] != self.revision():
                self.store.update("proposals", p["id"], {"status": ProposalStatus.REVOKED.value, "status_reason": "permission revision changed"})
                raise DomainError("REVOKED", "permission was revoked (Stop or pairing change) after this proposal")
            self.store.insert("approvals", {"id": new_id("apr"), "proposal_id": p["id"], "proposal_digest": p["digest"],
                                            "device_id": principal.device_id, "session_id": principal.session_id,
                                            "permission_revision": p["permission_revision"], "approved_at": t,
                                            "consumed_at": None, "consumed_by_operation_id": None})
            self.store.update("proposals", p["id"], {"status": ProposalStatus.APPROVED.value})
            if p["kind"] in (ProposalKind.REPAIR.value, ProposalKind.UNDO.value):
                issue = self.store.get("issues", p["issue_id"])
                assert issue is not None
                self._set_state(issue, IssueState.APPROVED, f"approved on paired device ({p['kind'].lower()})")
        return {"approved": True, "proposal_id": p["id"], "approved_at": t}

    def decline(self, principal: Principal, proposal_id: str) -> dict[str, Any]:
        if principal.via != "ui":
            raise DomainError("FORBIDDEN", "decline is a UI action")
        p, _ = self._proposal_for(principal, proposal_id)
        if p["status"] not in (ProposalStatus.PENDING.value, ProposalStatus.APPROVED.value):
            raise DomainError("NOT_PENDING", f"proposal is {p['status']}")
        with self.store.tx():
            self.store.update("proposals", p["id"], {"status": ProposalStatus.DECLINED.value, "status_reason": "declined by person"})
            issue = self.store.get("issues", p["issue_id"])
            if issue and p["kind"] == ProposalKind.REPAIR.value and issue["state"] in (IssueState.PROPOSED.value, IssueState.APPROVED.value):
                self._set_state(issue, IssueState.UNRESOLVED, "person declined the proposal",
                                next_manual_step="You declined the change, so nothing was modified.")
        return {"declined": True, "proposal_id": p["id"]}

    # ===================================================================================== apply
    def _validate_approval(self, p: dict[str, Any], mission: dict[str, Any]) -> dict[str, Any]:
        if mission["state"] != MissionState.ACTIVE.value:
            raise DomainError("STOPPED", "recovery session is stopped; nothing was attempted")
        if p["status"] != ProposalStatus.APPROVED.value:
            raise DomainError("NOT_APPROVED", f"proposal is {p['status']}; it needs approval on the paired device",
                              status=p["status"])
        apr = self.store.one("SELECT * FROM approvals WHERE proposal_id = ?", (p["id"],))
        if apr is None or apr["consumed_at"] is not None:
            raise DomainError("NOT_APPROVED", "no unused approval exists for this proposal")
        if apr["device_id"] != p["approver_device_id"]:
            raise DomainError("APPROVAL_INVALID", "approval came from a different device")
        if apr["proposal_digest"] != p["digest"] or p["digest"] != self.proposal_digest(p):
            raise DomainError("APPROVAL_INVALID", "approval does not match the proposal")
        if apr["permission_revision"] != self.revision() or p["permission_revision"] != self.revision():
            raise DomainError("REVOKED", "permission revision changed (Stop or revocation)")
        if p["expires_at"] < now_ms():
            raise DomainError("EXPIRED", "proposal expired; inspect again")
        return apr

    def _kinds_for_action(self, action: str) -> list[str]:
        return {"SET_MOUSE_PRIMARY": ["mouse"], "SET_AUDIO_ENDPOINT": ["audio"], "PLAY_TEST_TONE": ["audio"],
                "MOVE_WINDOW": ["windows", "workpad"]}[action]

    def _precondition_problem(self, p: dict[str, Any], facts: dict[str, dict[str, Any]]) -> str | None:
        pre = p["preconditions"]
        a = p["action"]
        if a == ActionKind.SET_MOUSE_PRIMARY.value:
            if bool(facts["mouse"]["swap_effective"]) != bool(pre["swap_effective"]):
                return "button mapping changed since the proposal"
        elif a in (ActionKind.SET_AUDIO_ENDPOINT.value, ActionKind.PLAY_TEST_TONE.value):
            d = facts["audio"].get("default")
            if not d or d["endpoint_id"] != pre["default_endpoint_id"]:
                return "default playback device changed since the proposal"
            if d["muted"] != pre["muted"]:
                return "mute state changed since the proposal"
            if "volume_scalar" in pre and abs(d["volume_scalar"] - pre["volume_scalar"]) > 0.02:
                return "volume changed since the proposal"
        elif a == ActionKind.MOVE_WINDOW.value:
            w = facts["windows"]
            if w["monitors_fingerprint"] != pre["monitors_fingerprint"]:
                return "display configuration changed since the proposal"
            cand = next((c for c in w["candidates"] if c["target_ref"] == pre["target_ref"]), None)
            if cand is None:
                return "the selected window is no longer present (or now belongs to a different process)"
            if cand["rect"] != pre["rect"]:
                return "the selected window moved since the proposal"
        return None

    def _state_matches(self, action: str, expected: dict[str, Any], facts: dict[str, dict[str, Any]]) -> bool:
        if not expected:
            return False
        if action == ActionKind.SET_MOUSE_PRIMARY.value:
            return recipes.mouse_matches(expected, facts)
        if action == ActionKind.SET_AUDIO_ENDPOINT.value:
            return recipes.audio_matches(expected, facts)
        if action == ActionKind.MOVE_WINDOW.value:
            return recipes.window_matches(expected, facts)[0]
        return False

    async def apply(self, principal: Principal, proposal_id: str) -> dict[str, Any]:
        async with self._mutation_lock:
            p, mission = self._proposal_for(principal, proposal_id)
            existing = self.store.one("SELECT * FROM operations WHERE proposal_id = ?", (p["id"],))
            if existing is not None:
                return {"duplicate_request": True,
                        "note": "This proposal was already executed once; returning the recorded operation. "
                                "It is never executed twice.",
                        "operation": self.operation_view(existing)}
            self._validate_approval(p, mission)
            issue = self.store.get("issues", p["issue_id"])
            assert issue is not None
            expected = p["preconditions"].get("_expected_post_state") or {}
            facts, before_obs, problems = await self._observe_kinds(mission, issue["id"], self._kinds_for_action(p["action"]))
            if problems:
                raise DomainError("HELPER_UNAVAILABLE", "could not observe fresh state before the change; nothing was "
                                  "attempted and the approval remains unused", problems=problems)
            before_id = before_obs[0]["id"]
            no_change = p["kind"] != ProposalKind.TEST.value and self._state_matches(p["action"], expected, facts)
            problem = None if no_change else self._precondition_problem(p, facts)
            t = now_ms()
            with self.store.tx():
                p = self.store.get("proposals", p["id"]) or p
                mission = self.store.get("missions", mission["id"]) or mission
                apr = self._validate_approval(p, mission)  # re-check inside the transaction (races with Stop)
                op = {
                    "id": new_id("op"), "proposal_id": p["id"], "idempotency_key": p["idempotency_key"],
                    "mission_id": mission["id"], "issue_id": issue["id"], "host_id": self.host_id, "kind": p["kind"],
                    "action": p["action"], "requested": p["params"], "adapter_mode": before_obs[0]["adapter_mode"],
                    "phase": OperationPhase.INTENT_RECORDED.value, "outcome": OperationOutcome.OUTCOME_UNKNOWN.value,
                    "intent_at": t, "started_at": None, "finished_at": None, "before_observation_id": before_id,
                    "after_observation_id": None, "execution_result": None,
                    "original_state": p["preconditions"].get("_original_state"), "expected_post_state": expected,
                    "reconcile_note": None, "error": None,
                }
                self.store.insert("operations", op)
                self.store.update("approvals", apr["id"], {"consumed_at": t, "consumed_by_operation_id": op["id"]})
                self.store.update("proposals", p["id"], {"status": ProposalStatus.CONSUMED.value})
                if problem or no_change:
                    outcome = OperationOutcome.REJECTED_OR_EXPIRED if problem else OperationOutcome.NO_CHANGE_NEEDED
                    self.store.update("operations", op["id"], {"phase": OperationPhase.FINISHED.value, "outcome": outcome.value,
                                                               "finished_at": t, "error": problem,
                                                               "after_observation_id": before_id})
                elif p["kind"] != ProposalKind.TEST.value:
                    self._set_state(issue, IssueState.APPLYING, f"executing {p['action']}")
            if problem:
                return await self._after_rejection(principal, issue, mission, op["id"], problem)
            if no_change:
                if p["kind"] == ProposalKind.REPAIR.value:
                    self._set_state(issue, IssueState.APPLYING, "no change needed")
                    self._set_state(issue, IssueState.VERIFYING, "requested state already present")
                elif p["kind"] == ProposalKind.UNDO.value:
                    self._set_state(issue, IssueState.APPLYING, "no change needed")
                    self._set_state(issue, IssueState.UNRESOLVED, "undo target state already present",
                                    next_manual_step="The original setting was already back in place; nothing changed.")
                return {"operation": self.operation_view(self.store.get("operations", op["id"]) or op),
                        "note": "The requested state was already present on fresh observation; nothing was changed."}
            return await self._execute(op, p, mission, issue)

    async def _after_rejection(self, principal: Principal, issue: dict[str, Any], mission: dict[str, Any],
                               op_id: str, problem: str) -> dict[str, Any]:
        """State changed between proposal and execution: re-observe and revise (new approval required)."""
        issue = self.store.get("issues", issue["id"]) or issue
        revised: dict[str, Any] | None = None
        if issue["kind"] != IssueKind.UNSUPPORTED.value and issue["state"] in (IssueState.APPROVED.value, IssueState.APPLYING.value):
            self._set_state(issue, IssueState.INSPECTING, f"precondition failed: {problem}")
            revised = await self._analyze_and_route(issue, mission)
        return {"operation": self.operation_view(self.store.get("operations", op_id) or {}),
                "rejected_because": problem,
                "note": "Nothing was changed. The state changed after the proposal, so it was re-observed; any "
                        "revised proposal needs a new approval.",
                "revised": revised}

    async def _execute(self, op: dict[str, Any], p: dict[str, Any], mission: dict[str, Any],
                       issue: dict[str, Any]) -> dict[str, Any]:
        self.store.update("operations", op["id"], {"phase": OperationPhase.EXECUTING.value, "started_at": now_ms()})
        helper_params = {k: v for k, v in p["params"].items()}
        try:
            resp = await self.host.execute(action=p["action"], params=helper_params, revision=p["permission_revision"],
                                           operation_id=op["id"], timeout_s=self.execute_timeout_s)
        except HelperTimeoutError as exc:
            return await self._unknown_outcome(op, p, mission, issue, f"no response from helper: {exc}")
        except HelperUnavailableError as exc:
            self.store.update("operations", op["id"], {"phase": OperationPhase.FINISHED.value, "finished_at": now_ms(),
                                                       "outcome": OperationOutcome.NOT_ATTEMPTED.value, "error": str(exc)})
            if p["kind"] != ProposalKind.TEST.value:
                self._set_state(issue, IssueState.FAILED, "helper unreachable before execution")
            return {"operation": self.operation_view(self.store.get("operations", op["id"]) or op),
                    "note": "The helper could not be reached, so the change was not attempted."}
        if not resp.get("ok"):
            code = resp.get("error", {}).get("code", "OS_ERROR")
            msg = resp.get("error", {}).get("message", "")
            outcome = OperationOutcome.REJECTED_OR_EXPIRED if code in REVISABLE_ERRORS | {"FENCED", "UNSUPPORTED"} else OperationOutcome.FAILED
            self.store.update("operations", op["id"], {"phase": OperationPhase.FINISHED.value, "finished_at": now_ms(),
                                                       "outcome": outcome.value, "error": f"{code}: {msg}",
                                                       "execution_result": resp.get("error")})
            if p["kind"] == ProposalKind.TEST.value:
                return {"operation": self.operation_view(self.store.get("operations", op["id"]) or op)}
            if code == "FENCED":
                issue = self.store.get("issues", issue["id"]) or issue
                if issue["state"] != IssueState.STOPPED.value:
                    self._set_state(issue, IssueState.STOPPED, "helper fence rejected the write (Stop)")
                return {"operation": self.operation_view(self.store.get("operations", op["id"]) or op),
                        "note": "Stopped: the helper rejected this change because permission was revoked."}
            if code in REVISABLE_ERRORS:
                return await self._after_rejection(Principal(mission["device_id"], None, "system"), issue, mission, op["id"],
                                                   f"helper rejected: {msg}")
            if code == "UNSUPPORTED":
                self._set_state(issue, IssueState.UNRESOLVED, f"unsupported at execution: {msg}",
                                next_manual_step=f"RescueBridge cannot do this safely: {msg}. Nothing was changed.")
            else:
                self._set_state(issue, IssueState.FAILED, f"OS operation failed: {code}")
            return {"operation": self.operation_view(self.store.get("operations", op["id"]) or op)}
        # executed: observe the resulting state FRESH (do not trust the helper's own echo alone)
        result = resp["result"]
        facts, after_obs, problems = await self._observe_kinds(mission, issue["id"], self._kinds_for_action(p["action"]))
        after_id = after_obs[0]["id"]
        extra: dict[str, Any] = {}
        if p["kind"] == ProposalKind.TEST.value:
            outcome = OperationOutcome.APPLIED_STATE_NOT_VERIFIED  # audibility cannot be observed by an API
            extra["note"] = "Tone playback call returned. Whether it was audible needs the person's answer."
        elif problems:
            outcome = OperationOutcome.APPLIED_STATE_NOT_VERIFIED
            extra["note"] = "The helper reported success but the result could not be observed."
        elif self._state_matches(p["action"], op["expected_post_state"], facts):
            outcome = OperationOutcome.APPLIED_STATE_VERIFIED
        else:
            outcome = OperationOutcome.APPLIED_STATE_NOT_VERIFIED
            extra["note"] = "The OS call returned success but the observed state did not change as requested."
        if p["action"] == ActionKind.MOVE_WINDOW.value and p["target"].get("is_workpad") and "workpad" in facts:
            before_hash = p["preconditions"].get("workpad_text_sha256")
            extra["workpad_text_unchanged"] = bool(before_hash and facts["workpad"].get("text_sha256") == before_hash)
        if (p["action"] == ActionKind.SET_MOUSE_PRIMARY.value and p["kind"] == ProposalKind.REPAIR.value
                and outcome == OperationOutcome.APPLIED_STATE_VERIFIED):
            test_id = new_id("ct")
            try:
                ct = await self.host.execute(action="SHOW_CLICK_TEST", params={"test_id": test_id},
                                             revision=p["permission_revision"], operation_id=op["id"])
                extra["click_test_id"] = test_id if ct.get("ok") else None
            except HelperUnavailableError:
                extra["click_test_id"] = None
        self.store.update("operations", op["id"], {
            "phase": OperationPhase.FINISHED.value, "finished_at": now_ms(), "outcome": outcome.value,
            "after_observation_id": after_id, "execution_result": {**result, **extra}})
        if p["kind"] == ProposalKind.REPAIR.value:
            if outcome == OperationOutcome.APPLIED_STATE_VERIFIED:
                self._set_state(issue, IssueState.VERIFYING, "state change observed")
            else:
                self._set_state(issue, IssueState.VERIFYING, "state change NOT observed")
        elif p["kind"] == ProposalKind.UNDO.value:
            self._set_state(issue, IssueState.UNRESOLVED, "repair undone at the person's request",
                            next_manual_step="The earlier repair was undone, so the original symptom may return.")
        return {"operation": self.operation_view(self.store.get("operations", op["id"]) or op), **extra}

    async def _unknown_outcome(self, op: dict[str, Any], p: dict[str, Any], mission: dict[str, Any],
                               issue: dict[str, Any], why: str) -> dict[str, Any]:
        """Request sent, no reply. Never repeat blindly: reconcile from a fresh observation."""
        self.store.update("operations", op["id"], {"error": why})
        note = await self._reconcile_operation(self.store.get("operations", op["id"]) or op, p, mission, issue)
        return {"operation": self.operation_view(self.store.get("operations", op["id"]) or op), "note": note}

    async def _reconcile_operation(self, op: dict[str, Any], p: dict[str, Any], mission: dict[str, Any],
                                   issue: dict[str, Any]) -> str:
        if p["kind"] == ProposalKind.TEST.value:
            self.store.update("operations", op["id"], {"phase": OperationPhase.FINISHED.value, "finished_at": now_ms(),
                                                       "reconcile_note": "test outcome unknown"})
            return "Tone outcome unknown."
        facts, obs, problems = await self._observe_kinds(mission, issue["id"], self._kinds_for_action(p["action"]))
        if problems:
            note = "Outcome unknown and the current state cannot be observed. Nothing will be retried automatically."
            self.store.update("operations", op["id"], {"reconcile_note": note})
            return note
        if self._state_matches(p["action"], op["expected_post_state"] or {}, facts):
            note = ("Outcome unknown, but a fresh observation shows the requested state is present. Whether this "
                    "operation or something else made the change is unknown.")
            self.store.update("operations", op["id"], {"phase": OperationPhase.FINISHED.value, "finished_at": now_ms(),
                                                       "reconcile_note": note, "after_observation_id": obs[0]["id"]})
            issue = self.store.get("issues", issue["id"]) or issue
            if issue["state"] == IssueState.APPLYING.value:
                self._set_state(issue, IssueState.VERIFYING, "reconciled: requested state present")
            return note
        note = ("Outcome unknown and the requested state is NOT present. It was not retried automatically; inspect "
                "again to get a new proposal.")
        self.store.update("operations", op["id"], {"phase": OperationPhase.FINISHED.value, "finished_at": now_ms(),
                                                   "reconcile_note": note, "after_observation_id": obs[0]["id"]})
        issue = self.store.get("issues", issue["id"]) or issue
        if issue["state"] == IssueState.APPLYING.value:
            self._set_state(issue, IssueState.FAILED, "reconciled: requested state absent")
        return note

    # ===================================================================================== verify
    async def verify(self, principal: Principal, issue_id: str) -> dict[str, Any]:
        issue, mission = self._issue_for(principal, issue_id)
        state = IssueState(issue["state"])
        if state not in (IssueState.VERIFYING, IssueState.AWAITING_USER_CONFIRMATION):
            raise DomainError("INVALID_STATE", f"nothing to verify while issue is {state.value}", state=state.value)
        op = self.store.one("SELECT * FROM operations WHERE issue_id = ? AND kind = 'REPAIR' ORDER BY intent_at DESC LIMIT 1",
                            (issue["id"],))
        if op is None:
            raise DomainError("INVALID_STATE", "no repair operation to verify")
        kinds = self._kinds_for_action(op["action"])
        facts, observations, problems = await self._observe_kinds(mission, issue["id"], kinds)
        if problems:
            return self._issue_result(issue, observations=observations,
                                      note="Verification could not observe the state (helper unavailable). Status unknown.")
        ok = self._state_matches(op["action"], op["expected_post_state"] or {}, facts)
        proposal = None
        confirmation: dict[str, Any]
        if not ok:
            self._set_state(issue, IssueState.UNRESOLVED, "fresh verification: requested state not present",
                            next_manual_step="The requested state is not present on fresh observation. Inspect again or "
                                             "use the manual Windows setting.")
            return self._issue_result(issue, observations=observations)
        if op["action"] == ActionKind.SET_AUDIO_ENDPOINT.value:
            plan = recipes.tone_plan(facts)
            if plan:
                proposal = self._create_proposal(mission, issue, plan, [o["id"] for o in observations])
            confirmation = {"test_kind": "tone", "question": "Approve the test tone, then tell me: did you hear it?"}
        elif op["action"] == ActionKind.SET_MOUSE_PRIMARY.value:
            test_id = (op.get("execution_result") or {}).get("click_test_id")
            confirmation = {"test_kind": "click", "click_test_id": test_id,
                            "question": "Click the green target on the laptop screen with your normal click. Did it "
                                        "register as a normal click?"}
            if test_id:
                ct = await self._observe(mission, issue["id"], "click_test", test_id=test_id)
                observations.append(ct)
        else:
            confirmation = {"test_kind": "visible", "question": "Can you see and use the window on your laptop screen now?"}
            ok_w, cand = recipes.window_matches(op["expected_post_state"], facts)
            if cand and cand.get("is_workpad") and "workpad" in facts:
                confirmation["workpad_text_chars"] = facts["workpad"].get("text_chars")
        self._set_state(issue, IssueState.AWAITING_USER_CONFIRMATION, "observed state matches; awaiting the person",
                        clarification={"confirmation": confirmation})
        issue = self.store.get("issues", issue["id"]) or issue
        return self._issue_result(issue, observations=observations, proposal=proposal,
                                  note="The setting is observed as requested. That does not yet prove the problem is "
                                       "solved: the person must confirm.")

    # ===================================================================================== user result
    def record_user_result(self, principal: Principal, issue_id: str, result: str, *, source: UserResultSource,
                           utterance_id: str | None = None) -> dict[str, Any]:
        issue, mission = self._issue_for(principal, issue_id)
        try:
            value = UserResult(result)
        except ValueError as exc:
            raise DomainError("BAD_INPUT", "result must be works, still_broken or unsure") from exc
        if issue["state"] != IssueState.AWAITING_USER_CONFIRMATION.value:
            raise DomainError("INVALID_STATE", f"no confirmation is pending (issue is {issue['state']})")
        if source == UserResultSource.MODEL_INTERPRETED_UTTERANCE:
            msg = self.store.get("messages", utterance_id) if isinstance(utterance_id, str) else None
            entered = self.store.one("SELECT MAX(at) AS at FROM issue_events WHERE issue_id = ? AND to_state = ?",
                                     (issue["id"], IssueState.AWAITING_USER_CONFIRMATION.value)) or {}
            if (not msg or msg["role"] != "user" or msg["device_id"] != principal.device_id
                    or msg["mission_id"] not in (mission["id"], None) or msg["created_at"] < (entered.get("at") or 0)):
                raise DomainError("BAD_INPUT", "the result must cite the person's own utterance made after the question")
            text = msg["text"]
            pos, neg = bool(AFFIRM.search(text)), bool(NEGATE.search(text))
            if value == UserResult.WORKS and (not pos or neg):
                raise DomainError("AMBIGUOUS", "the utterance does not clearly confirm success; ask the person to use "
                                  "the Yes/No buttons")
            if value == UserResult.STILL_BROKEN and not neg:
                raise DomainError("AMBIGUOUS", "the utterance does not clearly report failure; ask again")
        op = self.store.one("SELECT id FROM operations WHERE issue_id = ? AND kind = 'REPAIR' ORDER BY intent_at DESC LIMIT 1",
                            (issue["id"],))
        test_kind = ((issue.get("clarification") or {}).get("confirmation") or {}).get("test_kind")
        self.store.insert("user_results", {"id": new_id("usr"), "issue_id": issue["id"], "operation_id": op["id"] if op else None,
                                           "result": value.value, "source": source.value, "utterance_id": utterance_id,
                                           "device_id": principal.device_id, "test_kind": test_kind, "at": now_ms()})
        if value == UserResult.WORKS:
            self._set_state(issue, IssueState.RESOLVED, f"person confirmed ({source.value})")
        elif value == UserResult.STILL_BROKEN:
            step = {
                "tone": ("The setting is correct but you could not hear the tone. Next checks: headphones or "
                         "speakers connected and switched on, physical volume keys, or another output device in "
                         "Settings > System > Sound > Output."),
                "click": "The mapping is as requested but clicks still misbehave. Try another mouse or the touchpad.",
                "visible": "The window is on the display by measurement but you cannot see it. Try Alt+Tab.",
            }.get(str(test_kind), "The person reports the symptom remains.")
            self._set_state(issue, IssueState.UNRESOLVED, f"person reports still broken ({source.value})",
                            next_manual_step=step)
        return self._issue_result(self.store.get("issues", issue["id"]) or issue)

    # ===================================================================================== stop / continue
    async def stop(self, principal: Principal, reason: str = "person pressed Stop") -> dict[str, Any]:
        t = now_ms()
        with self.store.tx():
            host = self._host()
            new_rev = int(host["permission_revision"]) + 1
            self.store.update("hosts", self.host_id, {"permission_revision": new_rev})
            revoked = self.store.execute(
                "UPDATE proposals SET status = 'REVOKED', status_reason = ? WHERE host_id = ? AND status IN ('PENDING','APPROVED')",
                (f"Stop: {reason[:80]}", self.host_id)).rowcount
            if principal.is_host_console:
                missions = self.store.all("SELECT * FROM missions WHERE host_id = ? AND state = 'ACTIVE'", (self.host_id,))
            else:
                m = self._mission(principal)
                missions = [m] if m else []
            for m in missions:
                self.store.update("missions", m["id"], {"state": MissionState.STOPPED.value, "stop_state": StopState.REQUESTED.value,
                                                        "stop_requested_at": t, "updated_at": t, "stop_detail": reason[:200]})
                for issue in self.store.all("SELECT * FROM issues WHERE mission_id = ?", (m["id"],)):
                    if issue["state"] in OPEN_STATES and issue["state"] not in (IssueState.APPLYING.value, IssueState.STOPPED.value):
                        self._set_state(issue, IssueState.STOPPED, "Stop requested")
        stop_state, detail = StopState.HELPER_UNREACHABLE, "helper unreachable: OS-side stop status unknown"
        in_flight = None
        try:
            ack = await self.host.fence(new_rev)
            if ack.get("ok"):
                stop_state = StopState.CONFIRMED
                in_flight = ack["result"].get("in_flight_operation_id")
                detail = f"helper fence {ack['result']['fence']} acknowledged" + (
                    f"; operation {in_flight} was already inside its OS call and may complete" if in_flight else "")
        except HelperUnavailableError as exc:
            detail = f"helper unreachable ({exc}); OS-side stop status unknown"
        for m in missions:
            self.store.update("missions", m["id"], {"stop_state": stop_state.value, "stop_detail": detail,
                                                    "stop_confirmed_at": now_ms() if stop_state == StopState.CONFIRMED else None})
        completed = []
        for m in missions:
            for op in self.store.all("SELECT * FROM operations WHERE mission_id = ? AND outcome IN "
                                     "('APPLIED_STATE_VERIFIED','APPLIED_STATE_NOT_VERIFIED','OUTCOME_UNKNOWN') AND kind != 'TEST'",
                                     (m["id"],)):
                completed.append(self.operation_view(op))
        return {"stop_state": stop_state.value, "detail": detail, "permission_revision": new_rev,
                "revoked_proposals": revoked, "in_flight_operation_id": in_flight,
                "already_completed_operations": completed,
                "note": "Stop prevents further changes. It cannot reverse changes that already completed; those are "
                        "listed and can be undone with a separate, approved Undo where available."}

    async def bump_revision(self, reason: str) -> dict[str, Any]:
        """Invalidate all outstanding authority (e.g. a paired device was revoked) and fence the helper."""
        with self.store.tx():
            new_rev = self.revision() + 1
            self.store.update("hosts", self.host_id, {"permission_revision": new_rev})
            revoked = self.store.execute(
                "UPDATE proposals SET status = 'REVOKED', status_reason = ? WHERE host_id = ? AND status IN ('PENDING','APPROVED')",
                (reason[:100], self.host_id)).rowcount
        try:
            ack = await self.host.fence(new_rev)
            fenced = bool(ack.get("ok"))
        except HelperUnavailableError:
            fenced = False
        return {"permission_revision": new_rev, "revoked_proposals": revoked, "helper_fenced": fenced}

    def continue_mission(self, principal: Principal) -> dict[str, Any]:
        m = self._mission(principal, active_only=False)
        if not m or m["state"] != MissionState.STOPPED.value:
            raise DomainError("INVALID_STATE", "no stopped recovery session to continue")
        with self.store.tx():
            self.store.update("missions", m["id"], {"state": MissionState.ACTIVE.value, "stop_state": StopState.NONE.value,
                                                    "updated_at": now_ms()})
            for issue in self.store.all("SELECT * FROM issues WHERE mission_id = ? AND state = 'STOPPED'", (m["id"],)):
                self._set_state(issue, IssueState.REPORTED, "continued after Stop: fresh inspection required")
        return self.status(principal)

    # ===================================================================================== undo
    async def request_undo(self, principal: Principal, operation_id: str) -> dict[str, Any]:
        if not isinstance(operation_id, str) or len(operation_id) > 80:
            raise DomainError("BAD_INPUT", "malformed operation id")
        op = self.store.get("operations", operation_id)
        mission = self.store.get("missions", op["mission_id"]) if op else None
        if not op or not mission or mission["device_id"] != principal.device_id:
            raise DomainError("NOT_FOUND", "no such operation for this device")
        if mission["state"] != MissionState.ACTIVE.value:
            raise DomainError("STOPPED", "recovery session is stopped; Continue first")
        if op["kind"] != ProposalKind.REPAIR.value or op["outcome"] not in (
                OperationOutcome.APPLIED_STATE_VERIFIED.value, OperationOutcome.APPLIED_STATE_NOT_VERIFIED.value,
                OperationOutcome.OUTCOME_UNKNOWN.value):
            raise DomainError("UNDO_UNAVAILABLE", "only an applied repair can be undone")
        if op["action"] == ActionKind.MOVE_WINDOW.value:
            raise DomainError("UNDO_UNAVAILABLE", "Undo is not offered for window recovery: restoring the old position "
                              "would hide the window again.")
        issue = self.store.get("issues", op["issue_id"])
        assert issue is not None
        facts, observations, problems = await self._observe_kinds(mission, issue["id"], self._kinds_for_action(op["action"]))
        if problems:
            raise DomainError("HELPER_UNAVAILABLE", "cannot observe current state; Undo not proposed")
        if not self._state_matches(op["action"], op["expected_post_state"] or {}, facts):
            obs_summary = describe_facts(observations[0]["kind"], observations[0]["facts"])
            return {"blocked": True, "reason": "The setting changed after the repair (now: " + obs_summary + "). Automatic "
                    "rollback is blocked so a later choice is not overwritten. Change it manually if needed.",
                    "observation": self._obs_view(observations[0])}
        plan = recipes.undo_mouse(op, facts) if op["action"] == ActionKind.SET_MOUSE_PRIMARY.value else recipes.undo_audio(op, facts)
        p = self._create_proposal(mission, issue, plan, [o["id"] for o in observations], undo_of=op["id"])
        return {"blocked": False, "proposal": self.proposal_view(p), "note": "Undo needs approval on the paired device."}

    # ===================================================================================== restart
    async def reconcile_on_startup(self) -> list[str]:
        notes = []
        with self.store.tx():
            n1 = self.store.execute("UPDATE proposals SET status = 'REVOKED', status_reason = 'backend restarted: approvals "
                                    "are not resumed' WHERE host_id = ? AND status = 'APPROVED'", (self.host_id,)).rowcount
            n2 = self.store.execute("UPDATE proposals SET status = 'EXPIRED', status_reason = 'backend restarted: "
                                    "re-inspection required' WHERE host_id = ? AND status = 'PENDING'", (self.host_id,)).rowcount
            for issue in self.store.all("SELECT i.* FROM issues i JOIN missions m ON m.id = i.mission_id WHERE m.host_id = ? "
                                        "AND i.state IN ('PROPOSED','APPROVED','NEEDS_CLARIFICATION')", (self.host_id,)):
                self._set_state(issue, IssueState.REPORTED, "backend restarted: inspect again before any change",
                                clarification=None)
        if n1 or n2:
            notes.append(f"revoked {n1} approved and expired {n2} pending proposals after restart")
        try:
            await self.host.fence(self.revision())
        except HelperUnavailableError:
            notes.append("helper unreachable at startup; fence not sent")
        for op in self.store.all("SELECT * FROM operations WHERE host_id = ? AND phase != 'FINISHED'", (self.host_id,)):
            p = self.store.get("proposals", op["proposal_id"])
            mission = self.store.get("missions", op["mission_id"])
            op_issue = self.store.get("issues", op["issue_id"])
            if not (p and mission and op_issue):
                continue
            note = await self._reconcile_operation(op, p, mission, op_issue)
            notes.append(f"{op['id']}: {note}")
        return notes

    # ===================================================================================== views
    def proposal_view(self, p: dict[str, Any], *, for_model: bool = False) -> dict[str, Any]:
        view = {"proposal_id": p["id"], "issue_id": p["issue_id"], "kind": p["kind"], "version": p["version"],
                "action": p["action"], "description": p["description"], "status": p["status"],
                "status_reason": p["status_reason"], "expires_at": p["expires_at"],
                "target": {k: v for k, v in p["target"].items() if k in ("endpoint_name", "app_label", "setting")},
                "basis_observation_ids": p["observation_ids"],
                "requires_approval_on_paired_device": p["status"] == ProposalStatus.PENDING.value}
        if not for_model:
            view["digest"] = p["digest"]
            view["params"] = p["params"]
        return view

    def operation_view(self, op: dict[str, Any]) -> dict[str, Any]:
        if not op:
            return {}
        before = self.store.get("observations", op["before_observation_id"]) if op.get("before_observation_id") else None
        after = self.store.get("observations", op["after_observation_id"]) if op.get("after_observation_id") else None
        er = op.get("execution_result") or {}
        return {"operation_id": op["id"], "proposal_id": op["proposal_id"], "kind": op["kind"], "action": op["action"],
                "outcome": op["outcome"], "phase": op["phase"],
                "adapter": ADAPTER_MODE_LABEL[AdapterMode(op["adapter_mode"])] if op.get("adapter_mode") else None,
                "intent_at": op["intent_at"], "finished_at": op["finished_at"],
                "observed_before": describe_facts(before["kind"], before["facts"]) if before else None,
                "observed_after": describe_facts(after["kind"], after["facts"]) if after else None,
                "after_observed_at": after["observed_at"] if after else None,
                "workpad_text_unchanged": er.get("workpad_text_unchanged"), "note": er.get("note"),
                "reconcile_note": op.get("reconcile_note"), "error": op.get("error"),
                "undo_available": (op["kind"] == "REPAIR" and op["action"] in ("SET_MOUSE_PRIMARY", "SET_AUDIO_ENDPOINT")
                                   and op["outcome"] in ("APPLIED_STATE_VERIFIED", "APPLIED_STATE_NOT_VERIFIED"))}

    def _issue_result(self, issue: dict[str, Any], *, observations: list[dict[str, Any]] | None = None,
                      proposal: dict[str, Any] | None = None, note: str | None = None) -> dict[str, Any]:
        out = self.issue_view(issue, for_model=True)
        if observations is not None:
            out["fresh_observations"] = [self._obs_view(o) for o in observations]
        if proposal is not None:
            out["new_proposal"] = self.proposal_view(proposal, for_model=True)
        if note:
            out["note"] = note
        return out

    def issue_view(self, issue: dict[str, Any], *, for_model: bool = False) -> dict[str, Any]:
        clar = issue.get("clarification") or {}
        findings = issue.get("findings") or {}
        props = self.store.all("SELECT * FROM proposals WHERE issue_id = ? AND status IN ('PENDING','APPROVED') ORDER BY created_at",
                               (issue["id"],))
        ops = self.store.all("SELECT * FROM operations WHERE issue_id = ? ORDER BY intent_at", (issue["id"],))
        results = self.store.all("SELECT result, source, test_kind, at FROM user_results WHERE issue_id = ? ORDER BY at",
                                 (issue["id"],))
        return {
            "issue_id": issue["id"], "kind": issue["kind"], "category": issue["category"], "state": issue["state"],
            "reported_words": issue["user_words"], "observed_facts": findings.get("observed", []),
            "supported_explanation": findings.get("explanation"), "inspection_problems": findings.get("problems"),
            "question": clar.get("question"), "options": clar.get("options"),
            "confirmation": clar.get("confirmation"), "next_manual_step": issue.get("next_manual_step"),
            "open_proposals": [self.proposal_view(p, for_model=for_model) for p in props],
            "operations": [self.operation_view(o) for o in ops],
            "person_results": results,
        }

    def status(self, principal: Principal, *, for_model: bool = False) -> dict[str, Any]:
        mission = self._mission(principal, active_only=False)
        mode = self.adapter_mode(self.last_helper_health.get("mode")) if self.last_helper_health.get("mode") else (
            AdapterMode.FIXTURE if self.settings.host_adapter == "fixture" else None)
        base: dict[str, Any] = {"adapter": ADAPTER_MODE_LABEL[mode] if mode else "unknown",
                                "helper_reachable": self.last_helper_health.get("reachable")}
        if mission is None:
            return {**base, "mission": None, "issues": []}
        issues = self.store.all("SELECT * FROM issues WHERE mission_id = ? ORDER BY created_at", (mission["id"],))
        views = [self.issue_view(i, for_model=for_model) for i in issues]
        resolved = sum(1 for i in issues if i["state"] == IssueState.RESOLVED.value)
        open_n = sum(1 for i in issues if i["state"] in OPEN_STATES)
        if not issues:
            summary = "No issues recorded yet."
        elif resolved == len(issues):
            summary = f"All {resolved} reported issue(s) confirmed resolved by the person."
        else:
            summary = (f"{resolved} of {len(issues)} issue(s) confirmed resolved; {open_n} still open"
                       + (f"; {len(issues) - resolved - open_n} unsupported" if len(issues) - resolved - open_n else "") + ".")
        return {**base, "mission": {"mission_id": mission["id"], "goal": mission["goal"], "state": mission["state"],
                                    "stop_state": mission["stop_state"], "stop_detail": mission["stop_detail"],
                                    "created_at": mission["created_at"], "server_summary": summary},
                "issues": views}
