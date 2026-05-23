"""Tests for src/handlers/auth.py — login and /me across all roles.

Uses mock_cognito_login() to simulate Cognito without a live pool, while
keeping the real boto3 + AuthFactory code path active in auth.py.
"""

import json
import pytest

from src.handlers.auth import login, me
from tests.conftest import event, mock_cognito_login


# ── Login ─────────────────────────────────────────────────────────────────────

ROLES_AND_USERS = [
    ("admin",     "super_admin", "acme"),
    ("org_admin", "admin",       "acme"),
    ("member",    "user",        "acme"),
]


@pytest.mark.parametrize("username,expected_role,expected_tenant", ROLES_AND_USERS)
def test_login_returns_token_for_all_roles(username, expected_role, expected_tenant):
    with mock_cognito_login():
        resp = login(event(body={"username": username, "password": "password123"}), {})

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "access_token" in body
    assert body["user"]["role"] == expected_role
    assert body["user"]["tenant_id"] == expected_tenant
    assert body["user"]["username"] == username


def test_login_rejects_wrong_password():
    with mock_cognito_login():
        resp = login(event(body={"username": "admin", "password": "wrong!"}), {})
    assert resp["statusCode"] == 401


def test_login_rejects_unknown_user():
    with mock_cognito_login():
        resp = login(event(body={"username": "ghost", "password": "password123"}), {})
    assert resp["statusCode"] == 401


def test_login_rejects_missing_fields():
    with mock_cognito_login():
        resp = login(event(body={"username": "admin"}), {})
    assert resp["statusCode"] == 400

    with mock_cognito_login():
        resp = login(event(body={"password": "password123"}), {})
    assert resp["statusCode"] == 400


def test_login_rejects_invalid_json():
    ev = event()
    ev["body"] = "not-json"
    with mock_cognito_login():
        resp = login(ev, {})
    assert resp["statusCode"] == 400


# ── /me ───────────────────────────────────────────────────────────────────────

def _get_token(username="admin"):
    with mock_cognito_login():
        resp = login(event(body={"username": username, "password": "password123"}), {})
    return json.loads(resp["body"])["access_token"]


def test_me_returns_correct_user_for_super_admin():
    token = _get_token("admin")
    with mock_cognito_login():
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
    with mock_cognito_login():
        resp = me(event(method="GET", headers={"Authorization": f"Bearer {token}"}), {})

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["role"] == expected_role


def test_me_rejects_missing_token():
    with mock_cognito_login():
        resp = me(event(method="GET"), {})
    assert resp["statusCode"] == 401


def test_me_rejects_invalid_token():
    with mock_cognito_login():
        resp = me(event(method="GET", headers={"Authorization": "Bearer invalid.token.here"}), {})
    assert resp["statusCode"] == 401
