"""Password hashing, JWT issuance/verification, single-use email tokens.

Pure-function module — no DB I/O. Caller persists the tokens (hashed) and
checks expiry.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import get_settings


@dataclass(frozen=True)
class TokenPayload:
    sub: str          # user_id (UUID hex)
    firm_id: str      # UUID hex
    role: str
    typ: str          # "access" | "refresh"
    exp: int          # unix seconds
    iat: int


# ──────────────── bcrypt passwords ────────────────


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# ──────────────── JWT ────────────────


def _now() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


def issue_access_token(*, user_id: str, firm_id: str, role: str) -> str:
    settings = get_settings()
    now = _now()
    payload: dict[str, Any] = {
        "sub": user_id,
        "firm_id": firm_id,
        "role": role,
        "typ": "access",
        "iat": now,
        "exp": now + settings.jwt_access_ttl_seconds,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def issue_refresh_token(*, user_id: str, firm_id: str, role: str) -> str:
    settings = get_settings()
    now = _now()
    payload: dict[str, Any] = {
        "sub": user_id,
        "firm_id": firm_id,
        "role": role,
        "typ": "refresh",
        "iat": now,
        "exp": now + settings.jwt_refresh_ttl_seconds,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


class InvalidTokenError(Exception):
    """Raised when a JWT fails to decode or has the wrong type."""


def decode_token(token: str, *, expected_type: str | None = None) -> TokenPayload:
    settings = get_settings()
    try:
        raw = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if expected_type is not None and raw.get("typ") != expected_type:
        raise InvalidTokenError(f"expected token type {expected_type!r}, got {raw.get('typ')!r}")

    return TokenPayload(
        sub=str(raw["sub"]),
        firm_id=str(raw["firm_id"]),
        role=str(raw["role"]),
        typ=str(raw["typ"]),
        exp=int(raw["exp"]),
        iat=int(raw["iat"]),
    )


# ──────────────── single-use email tokens ────────────────


def generate_email_token() -> tuple[str, str]:
    """Return ``(plaintext, hash)`` for a one-shot email verify/reset link.

    The plaintext is what we email; the hash is what we store in the DB. We
    compare by ``hmac.compare_digest`` on the hash.
    """
    plaintext = secrets.token_urlsafe(32)
    digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return plaintext, digest


def hash_email_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def email_tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def expiry(seconds: int) -> datetime:
    return datetime.now(tz=timezone.utc) + timedelta(seconds=seconds)
