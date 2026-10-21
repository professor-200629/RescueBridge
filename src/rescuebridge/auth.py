"""Device pairing, browser sessions, CSRF, host-console bootstrap, and MCP bearer tokens.

Credential rules:
- Every credential is 256-bit random and stored only as a SHA-256 digest.
- Browser credentials travel only in HttpOnly SameSite=Strict cookies (Secure on HTTPS), never in URLs,
  logs, or model context. State-changing requests also need the per-session CSRF header.
- A pairing code is one-use, short-lived, rate-limited, and only creates a *request*: a person at the
  laptop must accept the requesting device in the host console before any session exists.
- MCP bearer tokens are minted server-side for a paired device session and never reach the browser.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from rescuebridge.config import Settings
from rescuebridge.domain.store import Store
from rescuebridge.ids import constant_time_equal, hash_secret, new_id, new_secret, now_ms

PAIRING_MAX_ATTEMPTS_PER_CODE = 5
PAIRING_GLOBAL_FAILURES_PER_10MIN = 20
PAIRING_REQUEST_TTL_MS = 5 * 60_000
HOST_BOOTSTRAP_TTL_MS = 10 * 60_000
MCP_TOKEN_TTL_MS = 60 * 60_000


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int = 403) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    device_id: str | None
    role: str  # "device" | "host_console"
    csrf_token: str
    device_name: str | None


def _format_code(raw: str) -> str:
    return f"{raw[:4]}-{raw[4:]}"


def normalize_code(code: str) -> str | None:
    """Exactly eight digits after removing spaces and dashes; anything else is malformed (None)."""
    compact = "".join(ch for ch in str(code) if ch not in " -\t")
    return compact if len(compact) == 8 and compact.isascii() and compact.isdigit() else None


class AuthService:
    def __init__(self, store: Store, settings: Settings, *, on_permission_change: Any = None) -> None:
        self.store = store
        self.settings = settings
        self._on_permission_change = on_permission_change

    # ------------------------------------------------------------------------------ pairing codes
    def create_pairing_code(self) -> dict[str, Any]:
        """New one-use code; any previous unused code is invalidated."""
        raw = "".join(secrets.choice("0123456789") for _ in range(8))
        t = now_ms()
        with self.store.tx():
            self.store.execute("UPDATE pairing_codes SET used_at = ? WHERE used_at IS NULL", (t,))
            row = {"id": new_id("pc"), "code_hash": hash_secret(raw), "created_at": t,
                   "expires_at": t + self.settings.pairing_code_ttl_s * 1000, "used_at": None, "failed_attempts": 0}
            self.store.insert("pairing_codes", row)
        return {"code": _format_code(raw), "expires_at": row["expires_at"], "code_id": row["id"]}

    def request_pairing(self, code: str, device_name: str, user_agent: str | None) -> dict[str, Any]:
        t = now_ms()
        recent = self.store.one("SELECT COUNT(*) AS n FROM pairing_failures WHERE at > ?", (t - 600_000,))
        if recent and recent["n"] >= PAIRING_GLOBAL_FAILURES_PER_10MIN:
            raise AuthError("RATE_LIMITED", "Too many wrong codes. Wait 10 minutes and create a new code on the laptop.", 429)
        digits = normalize_code(code)
        if digits is None:  # format is public: rejecting it reveals nothing and is not counted as a guess
            raise AuthError("MALFORMED_CODE", "Enter the 8-digit code shown on the laptop (spaces and dashes are fine).", 400)
        active = self.store.one("SELECT * FROM pairing_codes WHERE used_at IS NULL AND expires_at > ? "
                                "ORDER BY created_at DESC LIMIT 1", (t,))
        if active is None:
            self.store.insert("pairing_failures", {"at": t})
            latest = self.store.one("SELECT used_at, expires_at FROM pairing_codes ORDER BY created_at DESC LIMIT 1")
            if latest and latest["used_at"] is None and latest["expires_at"] <= t:
                raise AuthError("CODE_EXPIRED", "That pairing code has expired (codes last 5 minutes). Create a new one "
                                "on the laptop's host console.", 400)
            raise AuthError("NO_ACTIVE_CODE", "No pairing code is active on the laptop. On the laptop's host console, "
                            "tap Create pairing code.", 400)
        if not constant_time_equal(hash_secret(digits), active["code_hash"]):
            with self.store.tx():
                self.store.insert("pairing_failures", {"at": t})
                n = active["failed_attempts"] + 1
                self.store.update("pairing_codes", active["id"], {"failed_attempts": n,
                                                                 "used_at": t if n >= PAIRING_MAX_ATTEMPTS_PER_CODE else None})
            raise AuthError("WRONG_CODE", "That code is not correct.", 400)
        secret = new_secret()
        name = (device_name or "Phone").strip()[:60] or "Phone"
        with self.store.tx():
            # one-use: the code is consumed by the first correct request
            if self.store.update("pairing_codes", active["id"], {"used_at": t}, where_extra="AND used_at IS NULL") != 1:
                raise AuthError("NO_ACTIVE_CODE", "That code was already used.", 400)
            req = {"id": new_id("prq"), "code_id": active["id"], "request_secret_hash": hash_secret(secret),
                   "device_name": name, "user_agent": (user_agent or "")[:200], "created_at": t,
                   "expires_at": t + PAIRING_REQUEST_TTL_MS, "status": "PENDING", "device_id": None, "decided_at": None}
            self.store.insert("pairing_requests", req)
        return {"request_id": req["id"], "request_secret": secret, "expires_at": req["expires_at"]}

    def pending_requests(self) -> list[dict[str, Any]]:
        t = now_ms()
        rows = self.store.all("SELECT id, device_name, user_agent, created_at, expires_at FROM pairing_requests "
                              "WHERE status = 'PENDING' AND expires_at > ? ORDER BY created_at", (t,))
        return rows

    def decide(self, request_id: str, accept: bool) -> dict[str, Any]:
        t = now_ms()
        req = self.store.get("pairing_requests", request_id)
        if not req or req["status"] != "PENDING" or req["expires_at"] < t:
            raise AuthError("NOT_PENDING", "No such pending pairing request.", 404)
        with self.store.tx():
            if not accept:
                self.store.update("pairing_requests", request_id, {"status": "REJECTED", "decided_at": t})
                return {"accepted": False}
            device_id = new_id("dev")
            self.store.insert("devices", {"id": device_id, "name": req["device_name"], "kind": "phone",
                                          "user_agent": req["user_agent"], "created_at": t, "revoked_at": None})
            self.store.update("pairing_requests", request_id, {"status": "ACCEPTED", "decided_at": t, "device_id": device_id})
        return {"accepted": True, "device_id": device_id}

    def claim(self, request_secret: str) -> tuple[dict[str, Any], str | None]:
        """Phone polls with its pairing-request cookie; on acceptance a session is issued exactly once."""
        if not request_secret:
            raise AuthError("NO_REQUEST", "No pairing request in progress.", 400)
        req = self.store.one("SELECT * FROM pairing_requests WHERE request_secret_hash = ?", (hash_secret(request_secret),))
        if not req:
            raise AuthError("NO_REQUEST", "Unknown pairing request.", 400)
        if req["status"] == "PENDING":
            if req["expires_at"] < now_ms():
                self.store.update("pairing_requests", req["id"], {"status": "EXPIRED"})
                raise AuthError("EXPIRED", "The laptop did not accept in time. Start again.", 400)
            return {"status": "PENDING"}, None
        if req["status"] != "ACCEPTED":
            raise AuthError(req["status"], f"Pairing {req['status'].lower()}.", 400)
        with self.store.tx():
            if self.store.update("pairing_requests", req["id"], {"status": "CLAIMED"}, where_extra="AND status = 'ACCEPTED'") != 1:
                raise AuthError("CLAIMED", "This pairing was already completed.", 400)
            token = self._new_session(req["device_id"], "device")
        return {"status": "PAIRED", "device_id": req["device_id"]}, token

    # ------------------------------------------------------------------------------ sessions
    def _new_session(self, device_id: str | None, role: str) -> str:
        token = new_secret()
        t = now_ms()
        self.store.insert("browser_sessions", {"id": new_id("ses"), "token_hash": hash_secret(token), "device_id": device_id,
                                               "role": role, "csrf_token": secrets.token_urlsafe(24), "created_at": t,
                                               "expires_at": t + self.settings.session_ttl_s * 1000, "revoked_at": None,
                                               "last_seen_at": t})
        return token

    def session(self, token: str | None) -> SessionInfo | None:
        if not token or len(token) > 200:
            return None
        s = self.store.one("SELECT * FROM browser_sessions WHERE token_hash = ?", (hash_secret(token),))
        t = now_ms()
        if not s or s["revoked_at"] or s["expires_at"] < t:
            return None
        name = None
        if s["device_id"]:
            d = self.store.get("devices", s["device_id"])
            if not d or d["revoked_at"]:
                return None
            name = d["name"]
        if t - (s["last_seen_at"] or 0) > 5_000:
            self.store.update("browser_sessions", s["id"], {"last_seen_at": t})
        return SessionInfo(session_id=s["id"], device_id=s["device_id"], role=s["role"], csrf_token=s["csrf_token"],
                           device_name=name)

    def logout(self, session_id: str) -> None:
        self.store.update("browser_sessions", session_id, {"revoked_at": now_ms()})
        self.store.execute("UPDATE mcp_tokens SET revoked_at = ? WHERE session_id = ? AND revoked_at IS NULL",
                           (now_ms(), session_id))

    def devices(self) -> list[dict[str, Any]]:
        rows = self.store.all("SELECT id, name, kind, created_at, revoked_at FROM devices ORDER BY created_at")
        for r in rows:
            last = self.store.one("SELECT MAX(last_seen_at) AS t FROM browser_sessions WHERE device_id = ? AND revoked_at IS NULL",
                                  (r["id"],))
            r["last_seen_at"] = last["t"] if last else None
        return rows

    def revoke_device(self, device_id: str) -> None:
        t = now_ms()
        with self.store.tx():
            if self.store.update("devices", device_id, {"revoked_at": t}, where_extra="AND revoked_at IS NULL") != 1:
                raise AuthError("NOT_FOUND", "No such active device.", 404)
            self.store.execute("UPDATE browser_sessions SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL", (t, device_id))
            self.store.execute("UPDATE mcp_tokens SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL", (t, device_id))
        if self._on_permission_change:
            self._on_permission_change(f"device {device_id} revoked")

    # ------------------------------------------------------------------------------ host console
    def create_host_bootstrap(self) -> str:
        code = new_secret()
        t = now_ms()
        with self.store.tx():
            self.store.execute("UPDATE host_bootstrap SET used_at = ? WHERE used_at IS NULL", (t,))
            self.store.insert("host_bootstrap", {"id": new_id("hb"), "code_hash": hash_secret(code), "created_at": t,
                                                 "expires_at": t + HOST_BOOTSTRAP_TTL_MS, "used_at": None})
        return code

    def consume_host_bootstrap(self, code: str) -> str:
        t = now_ms()
        row = self.store.one("SELECT * FROM host_bootstrap WHERE code_hash = ?", (hash_secret(code or ""),))
        again = "On this laptop run scripts\\host-console.ps1 to open a fresh one."
        if not row:
            raise AuthError("BAD_BOOTSTRAP", f"This host-console link is not valid. {again}", 403)
        if row["used_at"]:
            raise AuthError("BOOTSTRAP_USED", f"This one-time host-console link was already used. {again}", 403)
        if row["expires_at"] < t:
            raise AuthError("BOOTSTRAP_EXPIRED", f"This host-console link expired (links last 10 minutes). {again}", 403)
        with self.store.tx():
            if self.store.update("host_bootstrap", row["id"], {"used_at": t}, where_extra="AND used_at IS NULL") != 1:
                raise AuthError("BAD_BOOTSTRAP", "Already used.", 403)
            return self._new_session(None, "host_console")

    # ------------------------------------------------------------------------------ MCP tokens
    def mint_mcp_token(self, session: SessionInfo) -> str:
        if session.role != "device" or not session.device_id:
            raise AuthError("FORBIDDEN", "Only a paired device session can use recovery tools.")
        token = new_secret()
        t = now_ms()
        self.store.insert("mcp_tokens", {"id": new_id("mct"), "token_hash": hash_secret(token), "device_id": session.device_id,
                                         "session_id": session.session_id, "created_at": t, "expires_at": t + MCP_TOKEN_TTL_MS,
                                         "revoked_at": None})
        return token

    def mint_mcp_token_for_device(self, device_id: str) -> str:
        """For an operator-run external MCP host (CLI). Bound to the device, not a browser session."""
        d = self.store.get("devices", device_id)
        if not d or d["revoked_at"]:
            raise AuthError("NOT_FOUND", "No such active device.", 404)
        token = new_secret()
        t = now_ms()
        self.store.insert("mcp_tokens", {"id": new_id("mct"), "token_hash": hash_secret(token), "device_id": device_id,
                                         "session_id": None, "created_at": t, "expires_at": t + MCP_TOKEN_TTL_MS,
                                         "revoked_at": None})
        return token

    def verify_mcp_token(self, token: str) -> tuple[str, str | None] | None:
        if not token or len(token) > 200:
            return None
        row = self.store.one("SELECT * FROM mcp_tokens WHERE token_hash = ?", (hash_secret(token),))
        t = now_ms()
        if not row or row["revoked_at"] or row["expires_at"] < t:
            return None
        d = self.store.get("devices", row["device_id"])
        if not d or d["revoked_at"]:
            return None
        if row["session_id"]:
            s = self.store.get("browser_sessions", row["session_id"])
            if not s or s["revoked_at"] or s["expires_at"] < t:
                return None
        return row["device_id"], row["session_id"]
