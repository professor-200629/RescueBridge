"""Private helper IPC over a Windows named pipe.

Protections:
- The pipe DACL grants access to the current user's SID only (no Everyone/Anonymous read ACE).
- PIPE_REJECT_REMOTE_CLIENTS: no SMB/network access. Browsers cannot open named pipes.
- FILE_FLAG_FIRST_PIPE_INSTANCE: the helper refuses to start if another process already owns the name,
  which also prevents a second helper (or a squatter) from silently sharing it.
- Mutual HMAC-SHA256 challenge using a random per-start key stored in a current-user-only file.
- One connection per call, so a Stop fence never waits behind an in-flight write on a shared connection.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

import ntsecuritycon
import pywintypes
import win32api
import win32con
import win32event
import win32file
import win32pipe
import win32security
import winerror

from rescuebridge.host.engine import HelperEngine

log = logging.getLogger("rescuebridge.helper.pipe")

MAX_MESSAGE = 1 << 20
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000  # not exported by pywin32


class HelperUnavailable(Exception):
    """The helper could not be reached or authenticated. Says nothing about the OS state."""


class HelperTimeout(HelperUnavailable):
    """A request was sent but no response arrived in time: the outcome is UNKNOWN."""


def _current_user_sid() -> Any:
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    return win32security.GetTokenInformation(token, win32security.TokenUser)[0]


def _user_only_sd() -> Any:
    sid = _current_user_sid()
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, sid)
    sd = win32security.SECURITY_DESCRIPTOR()
    sd.SetSecurityDescriptorOwner(sid, False)
    sd.SetSecurityDescriptorDacl(True, dacl, False)
    return sd


def write_private_file(path: Path, data: bytes) -> None:
    """Write a file readable only by the current user (protected DACL, no inherited ACEs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    win32security.SetFileSecurity(
        str(tmp),
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        _user_only_sd(),
    )
    os.replace(tmp, path)


def _mac(key: bytes, label: bytes, nonce: bytes) -> str:
    return hmac.new(key, label + nonce, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------------------------
# server
# ---------------------------------------------------------------------------------------------
def _read_msg_blocking(h: Any) -> dict[str, Any]:
    chunks: list[bytes] = []
    total = 0
    while True:
        hr, data = win32file.ReadFile(h, 65536)
        chunks.append(bytes(data))
        total += len(data)
        if total > MAX_MESSAGE:
            raise ValueError("message too large")
        if hr == 0:
            break
        if hr != winerror.ERROR_MORE_DATA:
            raise pywintypes.error(hr, "ReadFile", "unexpected result")
    return json.loads(b"".join(chunks).decode("utf-8"))


def _write_msg_blocking(h: Any, msg: dict[str, Any]) -> None:
    win32file.WriteFile(h, json.dumps(msg, separators=(",", ":")).encode("utf-8"))


class PipeServer:
    def __init__(self, engine: HelperEngine, pipe_name: str, key: bytes) -> None:
        self.engine = engine
        self.pipe_name = pipe_name
        self.key = key
        self._stop = threading.Event()
        self._sa = win32security.SECURITY_ATTRIBUTES()
        self._sa.SECURITY_DESCRIPTOR = _user_only_sd()
        self._first = True
        self.connections_served = 0

    def _create_instance(self) -> Any:
        flags = win32pipe.PIPE_ACCESS_DUPLEX
        if self._first:
            flags |= FILE_FLAG_FIRST_PIPE_INSTANCE
        mode = (win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT
                | PIPE_REJECT_REMOTE_CLIENTS)
        h = win32pipe.CreateNamedPipe(self.pipe_name, flags, mode, win32pipe.PIPE_UNLIMITED_INSTANCES,
                                      65536, 65536, 0, self._sa)
        self._first = False
        return h

    def serve_forever(self, ready: threading.Event | None = None) -> None:
        h = self._create_instance()  # raises if the name is already owned (first-instance flag)
        if ready:
            ready.set()
        while not self._stop.is_set():
            try:
                win32pipe.ConnectNamedPipe(h, None)
            except pywintypes.error as exc:
                if exc.winerror != winerror.ERROR_PIPE_CONNECTED:
                    win32file.CloseHandle(h)
                    h = self._create_instance()
                    continue
            if self._stop.is_set():
                win32file.CloseHandle(h)
                break
            connected = h
            h = self._create_instance()  # next listener exists BEFORE this connection can finish and close
            threading.Thread(target=self._serve_conn, args=(connected,), daemon=True).start()

    def shutdown(self) -> None:
        self._stop.set()
        with contextlib.suppress(pywintypes.error):  # wake the blocking ConnectNamedPipe
            hc = win32file.CreateFile(self.pipe_name, win32con.GENERIC_READ | win32con.GENERIC_WRITE, 0, None,
                                      win32con.OPEN_EXISTING, 0, None)
            win32file.CloseHandle(hc)

    def _serve_conn(self, h: Any) -> None:
        self.connections_served += 1
        try:
            nonce = os.urandom(32)
            _write_msg_blocking(h, {"type": "challenge", "nonce": nonce.hex()})
            auth = _read_msg_blocking(h)
            client_nonce = bytes.fromhex(str(auth.get("client_nonce", "")))[:64]
            if auth.get("type") != "auth" or len(client_nonce) < 16 or not hmac.compare_digest(
                str(auth.get("mac", "")), _mac(self.key, b"client:", nonce)
            ):
                _write_msg_blocking(h, {"type": "auth_failed"})
                return
            _write_msg_blocking(h, {"type": "auth_ok", "mac": _mac(self.key, b"server:", client_nonce),
                                    "helper_pid": os.getpid()})
            while not self._stop.is_set():
                req = _read_msg_blocking(h)
                _write_msg_blocking(h, self.engine.handle(req))
        except (pywintypes.error, ValueError, UnicodeDecodeError):
            pass  # client closed the connection or sent garbage
        finally:
            with contextlib.suppress(pywintypes.error):
                win32pipe.DisconnectNamedPipe(h)
            with contextlib.suppress(pywintypes.error):
                win32file.CloseHandle(h)


# ---------------------------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------------------------
class _OverlappedPipe:
    def __init__(self, pipe_name: str, connect_timeout_s: float) -> None:
        deadline_ms = int(connect_timeout_s * 1000)
        not_found_retries = 3  # tolerate the brief gap while the server re-creates a listening instance
        while True:
            try:
                self.h = win32file.CreateFile(pipe_name, win32con.GENERIC_READ | win32con.GENERIC_WRITE, 0, None,
                                              win32con.OPEN_EXISTING, win32file.FILE_FLAG_OVERLAPPED, None)
                break
            except pywintypes.error as exc:
                if exc.winerror == winerror.ERROR_PIPE_BUSY and deadline_ms > 0:
                    with contextlib.suppress(pywintypes.error):
                        win32pipe.WaitNamedPipe(pipe_name, min(deadline_ms, 1000))
                    deadline_ms -= 1000
                    continue
                if exc.winerror in (winerror.ERROR_FILE_NOT_FOUND, winerror.ERROR_PATH_NOT_FOUND):
                    if not_found_retries > 0:
                        not_found_retries -= 1
                        win32api.Sleep(50)
                        continue
                    raise HelperUnavailable("helper is not running (pipe not found)") from exc
                if exc.winerror == winerror.ERROR_ACCESS_DENIED:
                    raise HelperUnavailable("access denied to helper pipe (different user?)") from exc
                raise HelperUnavailable(f"cannot open helper pipe (Win32 error {exc.winerror})") from exc
        win32pipe.SetNamedPipeHandleState(self.h, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        self.event = win32event.CreateEvent(None, True, False, None)

    def close(self) -> None:
        with contextlib.suppress(pywintypes.error):
            win32file.CloseHandle(self.h)
        with contextlib.suppress(pywintypes.error):
            win32file.CloseHandle(self.event)

    def _ov(self) -> Any:
        ov = pywintypes.OVERLAPPED()
        win32event.ResetEvent(self.event)
        ov.hEvent = self.event
        return ov

    def _wait(self, ov: Any, timeout_ms: int) -> int:
        rc = win32event.WaitForSingleObject(self.event, timeout_ms)
        if rc == win32event.WAIT_TIMEOUT:
            with contextlib.suppress(pywintypes.error):
                win32file.CancelIo(self.h)
            raise HelperTimeout("helper did not respond in time")
        return win32file.GetOverlappedResult(self.h, ov, False)

    def write(self, msg: dict[str, Any], timeout_ms: int) -> None:
        ov = self._ov()
        win32file.WriteFile(self.h, json.dumps(msg, separators=(",", ":")).encode("utf-8"), ov)
        self._wait(ov, timeout_ms)

    def read(self, timeout_ms: int) -> dict[str, Any]:
        chunks: list[bytes] = []
        while True:
            buf = win32file.AllocateReadBuffer(65536)
            ov = self._ov()
            try:
                win32file.ReadFile(self.h, buf, ov)
                n = self._wait(ov, timeout_ms)
                chunks.append(bytes(buf[:n]))
                break
            except pywintypes.error as exc:
                if exc.winerror == winerror.ERROR_MORE_DATA:
                    chunks.append(bytes(buf))
                    if sum(len(c) for c in chunks) > MAX_MESSAGE:
                        raise HelperUnavailable("helper response too large") from exc
                    continue
                if exc.winerror in (winerror.ERROR_BROKEN_PIPE, winerror.ERROR_PIPE_NOT_CONNECTED):
                    raise HelperUnavailable("helper closed the connection") from exc
                raise
        return json.loads(b"".join(chunks).decode("utf-8"))


def pipe_call(pipe_name: str, key_path: Path, request: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    """Synchronous single request over a fresh authenticated connection."""
    try:
        key = key_path.read_bytes()
    except OSError as exc:
        raise HelperUnavailable("helper key file missing (helper not started?)") from exc
    conn = _OverlappedPipe(pipe_name, connect_timeout_s=2.0)
    sent = False
    try:
        hs_ms = 3000
        challenge = conn.read(hs_ms)
        nonce = bytes.fromhex(str(challenge.get("nonce", "")))
        client_nonce = os.urandom(32)
        conn.write({"type": "auth", "mac": _mac(key, b"client:", nonce), "client_nonce": client_nonce.hex()}, hs_ms)
        reply = conn.read(hs_ms)
        if reply.get("type") != "auth_ok" or not hmac.compare_digest(
            str(reply.get("mac", "")), _mac(key, b"server:", client_nonce)
        ):
            raise HelperUnavailable("helper authentication failed")
        sent = True  # from here on the request may reach the helper
        conn.write(request, 3000)
        return conn.read(int(timeout_s * 1000))
    except HelperTimeout as exc:
        if sent:
            raise
        raise HelperUnavailable(f"helper handshake timed out: {exc}") from exc
    except (pywintypes.error, HelperUnavailable, ValueError) as exc:
        if sent:  # the helper may have acted on the request: never report this as "not attempted"
            raise HelperTimeout(f"connection lost after the request was sent: {exc}") from exc
        if isinstance(exc, HelperUnavailable):
            raise
        raise HelperUnavailable(f"helper IPC error: {exc}") from exc
    finally:
        conn.close()
