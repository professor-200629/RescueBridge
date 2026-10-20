"""SQLite persistence for sessions, missions, issues, observations, proposals, approvals, operations, evidence.

The store is deliberately thin: it persists rows and enforces uniqueness constraints that the authority
logic relies on (one approval per proposal, one operation per proposal/idempotency key). All decisions are
made by `RecoveryService` and `AuthService`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

JSON_COLUMNS = frozenset(
    {
        "clarification",
        "preference",
        "facts",
        "model_facts",
        "params",
        "target",
        "observation_ids",
        "preconditions",
        "requested",
        "execution_result",
        "original_state",
        "expected_post_state",
        "meta",
        "scope",
        "snapshot",
        "latency",
        "findings",
    }
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta_kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS hosts (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, permission_revision INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, user_agent TEXT,
    created_at INTEGER NOT NULL, revoked_at INTEGER
);

CREATE TABLE IF NOT EXISTS pairing_codes (
    id TEXT PRIMARY KEY, code_hash TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
    used_at INTEGER, failed_attempts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pairing_requests (
    id TEXT PRIMARY KEY, code_id TEXT NOT NULL, request_secret_hash TEXT NOT NULL UNIQUE,
    device_name TEXT NOT NULL, user_agent TEXT, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
    status TEXT NOT NULL, device_id TEXT, decided_at INTEGER
);

CREATE TABLE IF NOT EXISTS pairing_failures (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS browser_sessions (
    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, device_id TEXT, role TEXT NOT NULL,
    csrf_token TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
    revoked_at INTEGER, last_seen_at INTEGER
);

CREATE TABLE IF NOT EXISTS mcp_tokens (
    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, device_id TEXT NOT NULL, session_id TEXT,
    created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER
);

CREATE TABLE IF NOT EXISTS host_bootstrap (
    id TEXT PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL, used_at INTEGER
);

CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY, host_id TEXT NOT NULL, device_id TEXT NOT NULL, goal TEXT NOT NULL,
    state TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
    stop_state TEXT NOT NULL DEFAULT 'NONE', stop_requested_at INTEGER, stop_confirmed_at INTEGER,
    stop_detail TEXT
);

CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, kind TEXT NOT NULL, category TEXT NOT NULL,
    user_words TEXT NOT NULL, app_hint TEXT, state TEXT NOT NULL, clarification TEXT, preference TEXT,
    findings TEXT, next_manual_step TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS issue_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL,
    reason TEXT NOT NULL, at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, host_id TEXT NOT NULL, issue_id TEXT, kind TEXT NOT NULL,
    adapter_mode TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL, observed_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL, facts TEXT NOT NULL, model_facts TEXT NOT NULL, error TEXT
);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, issue_id TEXT NOT NULL, host_id TEXT NOT NULL,
    approver_device_id TEXT NOT NULL, kind TEXT NOT NULL, version INTEGER NOT NULL, action TEXT NOT NULL,
    params TEXT NOT NULL, target TEXT NOT NULL, observation_ids TEXT NOT NULL, preconditions TEXT NOT NULL,
    permission_revision INTEGER NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE, description TEXT NOT NULL, digest TEXT NOT NULL,
    status TEXT NOT NULL, status_reason TEXT, undo_of_operation_id TEXT, supersedes_id TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE, proposal_digest TEXT NOT NULL,
    device_id TEXT NOT NULL, session_id TEXT NOT NULL, permission_revision INTEGER NOT NULL,
    approved_at INTEGER NOT NULL, consumed_at INTEGER, consumed_by_operation_id TEXT
);

CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE, idempotency_key TEXT NOT NULL UNIQUE,
    mission_id TEXT NOT NULL, issue_id TEXT NOT NULL, host_id TEXT NOT NULL, kind TEXT NOT NULL,
    action TEXT NOT NULL, requested TEXT NOT NULL, adapter_mode TEXT, phase TEXT NOT NULL,
    outcome TEXT NOT NULL, intent_at INTEGER NOT NULL, started_at INTEGER, finished_at INTEGER,
    before_observation_id TEXT, after_observation_id TEXT, execution_result TEXT,
    original_state TEXT, expected_post_state TEXT, reconcile_note TEXT, error TEXT
);

CREATE TABLE IF NOT EXISTS user_results (
    id TEXT PRIMARY KEY, issue_id TEXT NOT NULL, operation_id TEXT, result TEXT NOT NULL,
    source TEXT NOT NULL, utterance_id TEXT, device_id TEXT NOT NULL, test_kind TEXT, at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, mission_id TEXT, device_id TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL,
    input_mode TEXT, created_at INTEGER NOT NULL, meta TEXT
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY, device_id TEXT NOT NULL, mission_id TEXT, utterance_id TEXT, provider TEXT NOT NULL,
    model TEXT, started_at INTEGER NOT NULL, finished_at INTEGER, model_turns INTEGER NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0, timed_out INTEGER NOT NULL DEFAULT 0, blocked_claims INTEGER NOT NULL DEFAULT 0,
    latency TEXT, error TEXT
);

CREATE INDEX IF NOT EXISTS idx_issues_mission ON issues(mission_id);
CREATE INDEX IF NOT EXISTS idx_obs_mission ON observations(mission_id);
CREATE INDEX IF NOT EXISTS idx_prop_issue ON proposals(issue_id);
CREATE INDEX IF NOT EXISTS idx_ops_issue ON operations(issue_id);
CREATE INDEX IF NOT EXISTS idx_msgs_mission ON messages(mission_id);
"""


def _encode(col: str, value: Any) -> Any:
    if col in JSON_COLUMNS and value is not None:
        return json.dumps(value, sort_keys=True, allow_nan=False)
    return value


def _decode_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key in JSON_COLUMNS and value is not None:
            value = json.loads(value)
        out[key] = value
    return out


class Store:
    """Single-connection SQLite store guarded by a re-entrant lock (one backend process)."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._lock = threading.RLock()
        self._depth = 0
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta_kv(k, v) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),)
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[Store]:
        """Write transaction. Nested calls join the outer transaction (BEGIN IMMEDIATE once)."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self._conn.execute("COMMIT")

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"  # noqa: S608
        self.execute(sql, [_encode(c, row[c]) for c in cols])
        return row

    def update(self, table: str, row_id: str, changes: dict[str, Any], *, where_extra: str = "",
               extra_params: tuple[Any, ...] = ()) -> int:
        if not changes:
            return 0
        cols = list(changes.keys())
        sql = f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ? {where_extra}"  # noqa: S608
        cur = self.execute(sql, [*[_encode(c, changes[c]) for c in cols], row_id, *extra_params])
        return cur.rowcount

    def get(self, table: str, row_id: str) -> dict[str, Any] | None:
        cur = self.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,))  # noqa: S608
        return _decode_row(cur.fetchone())

    def one(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> dict[str, Any] | None:
        return _decode_row(self.execute(sql, params).fetchone())

    def all(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[dict[str, Any]]:
        return [r for r in (_decode_row(x) for x in self.execute(sql, params).fetchall()) if r is not None]
