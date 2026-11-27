"""Tests for src/handlers/auth.py — /me across all roles.

The app has no password sign-in (people sign in at the platform portal), so there is no login
test: tests/test_password_door_closed.py proves every password route answers 410. Here a test
pool key signs the AccessToken the portal sign-in would give, and mock_cognito_pool() serves its
JWKS, so the real SDK verification path runs without a live pool.
"""

import json
import pytest

from src.handlers.auth import me
from tests.conftest import access_token, event, mock_cognito_pool


# ── /me ───────────────────────────────────────────────────────────────────────

def _get_token(username="admin"):
    return access_token(username)


def test_me_returns_correct_user_for_super_admin():
    token = _get_token("admin")
    with mock_cognito_pool():
        resp = me(event(method="GET", headers={"Authorization": f"Bearer {token}"}), {})

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["role"] == "super_admin"
    assert body["tenant_id"] == "acme"


@pytest.mark.parametrize("username,expected_role", [
    ("org_admin", "admin"),
    ("member",    "user"),
])
def test_me_returns_correct_role(username, expected_role):
    token = _get_token(username)
    with mock_cognito_pool():
        resp = me(event(method="GET", headers={"Authorization": f"Bearer {token}"}), {})

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["role"] == expected_role


def test_me_rejects_missing_token():
    with mock_cognito_pool():
        resp = me(event(method="GET"), {})
    assert resp["statusCode"] == 401


def test_me_rejects_invalid_token():
    with mock_cognito_pool():
        resp = me(event(method="GET", headers={"Authorization": "Bearer invalid.token.here"}), {})
    assert resp["statusCode"] == 401


def test_me_rejects_token_not_signed_by_the_pool():
    """/me must verify the signature: a well-formed token with valid-looking claims,
    signed by a key that is not in the pool's JWKS, is a forgery and gets 401."""
    import time
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwt as jose_jwt
    from tests.conftest import APP_PREFIX, _TEST_ISSUER, _TEST_KID

    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ).decode()
    now = int(time.time())
    forged = jose_jwt.encode(
        {
            "iss": _TEST_ISSUER, "iat": now, "exp": now + 3600, "sub": "attacker",
            "token_use": "access", "client_id": "test-client-id",
            "cognito:groups": [f"{APP_PREFIX}-acme-super_admin"],
        },
        other_key, algorithm="RS256", headers={"kid": _TEST_KID},
    )
    with mock_cognito_pool():
        resp = me(event(method="GET", headers={"Authorization": f"Bearer {forged}"}), {})
    assert resp["statusCode"] == 401
