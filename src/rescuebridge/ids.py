"""Identifiers, secrets, and time helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any


def new_id(prefix: str) -> str:
    """Opaque random identifier, e.g. `prop_3kq...`. Not a credential."""
    return f"{prefix}_{secrets.token_urlsafe(9).replace('-', 'x').replace('_', 'y')}"


def new_secret() -> str:
    """256-bit credential suitable for cookies / bearer tokens."""
    return secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    """Credentials are stored only as SHA-256 digests (they are high-entropy, so no KDF is needed)."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def now_ms() -> int:
    return int(time.time() * 1000)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
