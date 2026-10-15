"""Password hashing and expiring in-memory FeimRemote access tokens."""

import hashlib
import hmac
import secrets
import threading
import time
from typing import Any


PBKDF2_ITERATIONS = 310_000
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30


def hash_password(password: str, salt: bytes | None = None) -> dict[str, str | int]:
    if len(password) < 12:
        raise ValueError("Passwords must contain at least 12 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return {
        "algorithm": "pbkdf2_sha256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": salt.hex(),
        "hash": digest.hex(),
    }


def verify_password(password: str, stored: Any) -> bool:
    if not isinstance(stored, dict) or stored.get("algorithm") != "pbkdf2_sha256":
        return False
    try:
        iterations = int(stored["iterations"])
        salt = bytes.fromhex(stored["salt"])
        expected = bytes.fromhex(stored["hash"])
    except (KeyError, TypeError, ValueError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


class TokenStore:
    def __init__(self, users: dict[str, Any], ttl_seconds: int = TOKEN_TTL_SECONDS):
        self.users = users
        self.ttl_seconds = ttl_seconds
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def login(self, username: str, password: str) -> str | None:
        user = self.users.get(username)
        if not isinstance(user, dict) or not verify_password(password, user.get("password")):
            return None
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens[hashlib.sha256(token.encode()).hexdigest()] = (
                username, time.monotonic() + self.ttl_seconds)
        return token

    def username_for(self, token: str) -> str | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = time.monotonic()
        with self._lock:
            for key, (_, expiry) in list(self._tokens.items()):
                if expiry <= now:
                    del self._tokens[key]
            session = self._tokens.get(token_hash)
        return session[0] if session else None

    def revoke(self, token: str) -> None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            self._tokens.pop(token_hash, None)
