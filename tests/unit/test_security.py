"""Unit tests for password hashing + JWT issue/verify + email tokens."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from app.api.security import (
    InvalidTokenError,
    decode_token,
    email_tokens_equal,
    generate_email_token,
    hash_email_token,
    hash_password,
    issue_access_token,
    issue_refresh_token,
    verify_password,
)


def test_hash_then_verify_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong", h) is False
    # bcrypt salt → distinct hashes for the same password.
    assert hash_password("x") != hash_password("x")


def test_verify_password_returns_false_for_garbage_hash() -> None:
    assert verify_password("anything", "not a valid bcrypt hash") is False


def test_issue_and_decode_access_token() -> None:
    tok = issue_access_token(user_id="u1", firm_id="f1", role="admin")
    payload = decode_token(tok, expected_type="access")
    assert payload.sub == "u1"
    assert payload.firm_id == "f1"
    assert payload.role == "admin"
    assert payload.typ == "access"
    assert payload.exp > payload.iat


def test_token_type_mismatch_rejected() -> None:
    access = issue_access_token(user_id="u1", firm_id="f1", role="staff")
    with pytest.raises(InvalidTokenError):
        decode_token(access, expected_type="refresh")


def test_refresh_token_lives_longer_than_access() -> None:
    a = decode_token(issue_access_token(user_id="u", firm_id="f", role="staff"), expected_type="access")
    r = decode_token(issue_refresh_token(user_id="u", firm_id="f", role="staff"), expected_type="refresh")
    assert (r.exp - r.iat) > (a.exp - a.iat)


def test_garbage_token_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_token("not.a.jwt")


def test_email_token_roundtrip() -> None:
    plain, h = generate_email_token()
    assert len(plain) > 20
    assert h == hash_email_token(plain)
    assert email_tokens_equal(h, hash_email_token(plain))
    assert not email_tokens_equal(h, hash_email_token("other"))


def test_two_generated_tokens_differ() -> None:
    a, _ = generate_email_token()
    b, _ = generate_email_token()
    assert a != b
