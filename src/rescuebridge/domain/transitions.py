"""Controlled per-issue state transitions. Any transition not listed here is rejected."""

from __future__ import annotations

from rescuebridge.domain.enums import IssueState as S

ALLOWED: dict[S, frozenset[S]] = {
    S.REPORTED: frozenset({S.INSPECTING, S.STOPPED, S.UNSUPPORTED}),
    S.INSPECTING: frozenset({S.NEEDS_CLARIFICATION, S.PROPOSED, S.UNRESOLVED, S.FAILED, S.STOPPED, S.INSPECTING}),
    # -> REPORTED: after a backend restart, stale proposals/approvals are dropped and re-inspection is required.
    S.NEEDS_CLARIFICATION: frozenset({S.INSPECTING, S.PROPOSED, S.UNRESOLVED, S.STOPPED, S.REPORTED}),
    S.PROPOSED: frozenset({S.APPROVED, S.INSPECTING, S.PROPOSED, S.UNRESOLVED, S.STOPPED, S.NEEDS_CLARIFICATION,
                           S.REPORTED}),
    S.APPROVED: frozenset({S.APPLYING, S.INSPECTING, S.PROPOSED, S.STOPPED, S.REPORTED}),
    S.APPLYING: frozenset({S.VERIFYING, S.FAILED, S.INSPECTING, S.PROPOSED, S.STOPPED, S.UNRESOLVED}),
    S.VERIFYING: frozenset({S.AWAITING_USER_CONFIRMATION, S.UNRESOLVED, S.FAILED, S.STOPPED, S.VERIFYING,
                            S.APPROVED}),  # APPROVED: an approved Undo right after a repair
    S.AWAITING_USER_CONFIRMATION: frozenset({S.RESOLVED, S.UNRESOLVED, S.STOPPED, S.VERIFYING,
                                             S.AWAITING_USER_CONFIRMATION, S.APPROVED}),
    S.RESOLVED: frozenset({S.APPROVED, S.UNRESOLVED}),  # APPROVED: an approved Undo
    S.UNRESOLVED: frozenset({S.INSPECTING, S.APPROVED, S.STOPPED, S.UNRESOLVED}),
    S.FAILED: frozenset({S.INSPECTING, S.STOPPED}),
    S.STOPPED: frozenset({S.REPORTED}),
    S.UNSUPPORTED: frozenset(),
}


class TransitionError(Exception):
    pass


def check(current: S, new: S) -> None:
    if new not in ALLOWED[current]:
        raise TransitionError(f"illegal issue transition {current} -> {new}")
