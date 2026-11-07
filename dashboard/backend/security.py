from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import timedelta

from .timeutil import to_iso, utc_now

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32

SESSION_COOKIE = "sb_session"
CSRF_HEADER = "x-csrf-token"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            dklen=SCRYPT_DKLEN, maxmem=64 * 1024 * 1024)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        n_i, r_i, p_i = int(n), int(r), int(p)
        if not (2**10 <= n_i <= 2**17 and 1 <= r_i <= 16 and 1 <= p_i <= 4):
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n_i, r=r_i, p=p_i,
                                dklen=len(expected), maxmem=128 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def verify_password_or_dummy(password: str, stored: str | None) -> bool:
    if stored is None:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, stored)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def lookup_key(token: str, table: dict[str, str]) -> str | None:
    digest = sha256_hex(token)
    found = None
    for known, device_id in table.items():
        if hmac.compare_digest(known, digest):
            found = device_id
    return found


@dataclass
class SessionUser:
    user_id: int
    username: str
    role: str
    csrf_token: str
    session_id: int

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def create_session(conn: sqlite3.Connection, user_id: int, hours: float) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = utc_now()
    conn.execute(
        "INSERT INTO sessions (token_hash, csrf_token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (sha256_hex(token), csrf, user_id, to_iso(now), to_iso(now + timedelta(hours=hours))),
    )
    return token, csrf


def load_session(conn: sqlite3.Connection, token: str | None) -> SessionUser | None:
    if not token or len(token) > 128:
        return None
    row = conn.execute(
        "SELECT s.id AS sid, s.csrf_token, s.expires_at, s.revoked, u.id AS uid, u.username, u.role "
        "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (sha256_hex(token),),
    ).fetchone()
    if row is None or row["revoked"] or row["expires_at"] <= to_iso(utc_now()):
        return None
    return SessionUser(row["uid"], row["username"], row["role"], row["csrf_token"], row["sid"])


def revoke_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (session_id,))


def purge_sessions(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM sessions WHERE revoked = 1 OR expires_at <= ?", (to_iso(utc_now()),))


def csrf_ok(user: SessionUser, header_value: str | None) -> bool:
    return bool(header_value) and hmac.compare_digest(user.csrf_token, header_value or "")


class RateLimiter:
    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float]:
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > self.window_s:
            q.popleft()
        return q

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._trim(key, now)
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 10_000:
                self._hits = {k: v for k, v in self._hits.items() if v}
            return True

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return len(self._trim(key, now)) >= self.limit

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
