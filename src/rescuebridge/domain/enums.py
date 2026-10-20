"""Closed enumerations for the recovery domain."""

from __future__ import annotations

from enum import StrEnum


class SymptomCategory(StrEnum):
    MOUSE_BUTTONS_WRONG = "mouse_buttons_wrong"
    NO_SOUND = "no_sound"
    WINDOW_MISSING = "window_missing"
    MOUSE_NOT_MOVING = "mouse_not_moving"
    OTHER = "other"


class IssueKind(StrEnum):
    MOUSE_BUTTONS = "MOUSE_BUTTONS"
    AUDIO_OUTPUT = "AUDIO_OUTPUT"
    OFFSCREEN_WINDOW = "OFFSCREEN_WINDOW"
    UNSUPPORTED = "UNSUPPORTED"


SYMPTOM_TO_KIND: dict[SymptomCategory, IssueKind] = {
    SymptomCategory.MOUSE_BUTTONS_WRONG: IssueKind.MOUSE_BUTTONS,
    SymptomCategory.NO_SOUND: IssueKind.AUDIO_OUTPUT,
    SymptomCategory.WINDOW_MISSING: IssueKind.OFFSCREEN_WINDOW,
    SymptomCategory.MOUSE_NOT_MOVING: IssueKind.UNSUPPORTED,
    SymptomCategory.OTHER: IssueKind.UNSUPPORTED,
}


class IssueState(StrEnum):
    REPORTED = "REPORTED"
    INSPECTING = "INSPECTING"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLYING = "APPLYING"
    VERIFYING = "VERIFYING"
    AWAITING_USER_CONFIRMATION = "AWAITING_USER_CONFIRMATION"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"
    UNSUPPORTED = "UNSUPPORTED"


TERMINAL_ISSUE_STATES = frozenset({IssueState.RESOLVED, IssueState.UNSUPPORTED})


class MissionState(StrEnum):
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    CLOSED = "CLOSED"


class ActionKind(StrEnum):
    SET_MOUSE_PRIMARY = "SET_MOUSE_PRIMARY"
    SET_AUDIO_ENDPOINT = "SET_AUDIO_ENDPOINT"
    PLAY_TEST_TONE = "PLAY_TEST_TONE"
    MOVE_WINDOW = "MOVE_WINDOW"


class ProposalKind(StrEnum):
    REPAIR = "REPAIR"
    TEST = "TEST"
    UNDO = "UNDO"


class ProposalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CONSUMED = "CONSUMED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class OperationOutcome(StrEnum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    APPLIED_STATE_VERIFIED = "APPLIED_STATE_VERIFIED"
    APPLIED_STATE_NOT_VERIFIED = "APPLIED_STATE_NOT_VERIFIED"
    NO_CHANGE_NEEDED = "NO_CHANGE_NEEDED"
    REJECTED_OR_EXPIRED = "REJECTED_OR_EXPIRED"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


class OperationPhase(StrEnum):
    INTENT_RECORDED = "INTENT_RECORDED"
    EXECUTING = "EXECUTING"
    FINISHED = "FINISHED"


class AdapterMode(StrEnum):
    REAL_WINDOWS = "real_windows"
    FIXTURE = "fixture_simulation"
    LIVE_LAB = "controlled_live_lab"


ADAPTER_MODE_LABEL = {
    AdapterMode.REAL_WINDOWS: "Real Windows",
    AdapterMode.FIXTURE: "Fixture Simulation",
    AdapterMode.LIVE_LAB: "Controlled Live Lab",
}


class ObservationKind(StrEnum):
    MOUSE = "mouse"
    AUDIO = "audio"
    WINDOWS = "windows"
    WORKPAD = "workpad"
    CLICK_TEST = "click_test"


class ObservationStatus(StrEnum):
    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"  # communication or adapter unavailable: NOT a negative finding
    ERROR = "ERROR"
    UNSUPPORTED = "UNSUPPORTED"


class UserResult(StrEnum):
    WORKS = "works"
    STILL_BROKEN = "still_broken"
    UNSURE = "unsure"


class UserResultSource(StrEnum):
    UI_BUTTON = "ui_button"
    MODEL_INTERPRETED_UTTERANCE = "model_interpreted_utterance"


class StopState(StrEnum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"  # helper acknowledged its execution fence
    HELPER_UNREACHABLE = "HELPER_UNREACHABLE"  # recorded locally; OS-side stop status unknown
