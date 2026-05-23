"""Shared fixtures for {{app-name}} backend tests."""

import json
import sys
import os
from contextlib import contextmanager
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock

import pytest

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force cognito auth mode for tests. The SDK auth handler defaults AUTH_MODE to
# 'local' (handlers/auth.py), which bypasses password validation and returns a
# fixed local user — so the mock_cognito_login() path (which patches boto3 +
# AuthFactory) is only exercised in cognito mode. pytest does not load .env, so
# we set it here before any handler module is imported. The COGNITO_* values are
# placeholders; boto3 and the auth provider are mocked, so they are never used
# for real calls — they only need to be present.
os.environ["AUTH_MODE"] = "cognito"
os.environ.setdefault("COGNITO_REGION", "ap-south-1")
os.environ.setdefault("COGNITO_CLIENT_ID", "test-client-id")
os.environ.setdefault("COGNITO_USER_POOL_ID", "test-pool-id")

# ── Fake IbexDB ────────────────────────────────────────────────────────────────

class FakeIbexDB:
    def __init__(self):
        self._tables: Dict[str, List[Dict]] = {}
        self._roles: Dict[str, List] = {}
        self._user_context = None

    def write(self, table, records, tenant_id=None, **kw):
        self._tables.setdefault(table, []).extend(records)
        return {"success": True, "data": {"records": records}}

    def query(self, table, filters=None, sort=None, limit=50, use_cache=True,
              tenant_id=None, offset=0, **kw):
        rows = list(self._tables.get(table, []))
        if filters:
            for f in filters:
                field, op, val = f["field"], f.get("operator", "eq"), f["value"]
                if op == "eq":
                    rows = [r for r in rows if r.get(field) == val]
        return {"success": True, "data": {"records": rows[offset:offset + limit]}}

    def update(self, table, filters, updates, tenant_id=None, **kw):
        for row in self._tables.get(table, []):
            if all(row.get(f["field"]) == f["value"] for f in filters if f.get("operator", "eq") == "eq"):
                row.update(updates)
        return {"success": True}

    def delete(self, table, filters, tenant_id=None, **kw):
        rows = self._tables.get(table, [])
        before = len(rows)
        self._tables[table] = [
            r for r in rows
            if not all(r.get(f["field"]) == f["value"] for f in filters if f.get("operator", "eq") == "eq")
        ]
        return {"success": True, "data": {"deleted": before - len(self._tables[table])}}

    def rbac_bootstrap(self, tenant_id=None):
        self._roles.setdefault(tenant_id, [])
        return {"success": True}

    def rbac_list_roles(self, tenant_id=None):
        return {"success": True, "data": {"roles": self._roles.get(tenant_id, [])}}

    def rbac_create_role(self, role_id, role_name, tenant_id=None, **kw):
        self._roles.setdefault(tenant_id, []).append({"role_id": role_id})
        return {"success": True}

    def rbac_assign_role(self, user_id, role_id, tenant_id=None, **kw):
        return {"success": True}


@pytest.fixture
def fake_db():
    return FakeIbexDB()


# ── Auth context builders ─────────────────────────────────────────────────────

def ctx(db, role, tenant_id="acme", user_id="u-test"):
    return {
        "db": db,
        "auth": {
            "user_id": user_id,
            "role": role,
            "tenant_id": tenant_id,
            "groups": [],
        },
    }


def event(method="POST", body=None, path_params=None, query_params=None, headers=None):
    return {
        "httpMethod": method,
        "body": json.dumps(body) if body else "{}",
        "pathParameters": path_params or {},
        "queryStringParameters": query_params or {},
        "headers": headers or {},
    }


@contextmanager
def as_role(role: str, tenant_id: str = "acme", user_id: str = "u-test"):
    """Context manager that patches AuthFactory so @require_roles sees the given role."""
    auth_info = {
        "user_id": user_id,
        "email": f"{role}@test.local",
        "role": role,
        "tenant_id": tenant_id,
        "groups": [],
        "auth_mode": "test",
    }
    mock_provider = type("MockProvider", (), {
        "authenticate": staticmethod(lambda ev: auth_info),
        "get_user_id": staticmethod(lambda ev: user_id),
    })()
    with patch("ajna_cloud.auth.AuthFactory.get_provider", return_value=mock_provider):
        yield


# ── Cognito mock for auth tests ───────────────────────────────────────────────
# Maps username → {role, tenant_id, email}. Used by mock_cognito_login context.
_COGNITO_USERS = {
    "admin":      {"role": "super_admin", "tenant_id": "acme", "email": "admin@localhost"},
    "org_admin":  {"role": "admin",       "tenant_id": "acme", "email": "org_admin@localhost"},
    "member":     {"role": "user",        "tenant_id": "acme", "email": "member@localhost"},
}
_VALID_PASSWORD = "password123"


@contextmanager
def mock_cognito_login():
    """
    Patches boto3 so the SDK's Cognito auth path works without a real pool.

    The SDK (ajna_cloud.handlers.auth) decodes the Cognito AccessToken/IdToken
    with jose and derives role+tenant from the ``cognito:groups`` claim, which
    Cockpit provisions in the form ``{app_prefix}-{tenant_id}-{role}`` (app_prefix
    defaults to '{{app-name}}'). So the mock must return real, decodable JWTs whose
    AccessToken carries the right group — not a hand-rolled token with a bare role.
    """
    from jose import jwt as jose_jwt

    def _jwt(claims: Dict[str, Any]) -> str:
        # get_unverified_claims() only base64url-decodes the payload, so any
        # signing secret works — the SDK never verifies the signature.
        return jose_jwt.encode(claims, "test-secret", algorithm="HS256")

    def fake_initiate_auth(**kwargs):
        params = kwargs.get("AuthParameters", {})
        username = params.get("USERNAME", "")
        password = params.get("PASSWORD", "")
        if username not in _COGNITO_USERS or password != _VALID_PASSWORD:
            from botocore.exceptions import ClientError
            raise ClientError(
                {"Error": {"Code": "NotAuthorizedException", "Message": "Incorrect username or password."}},
                "InitiateAuth",
            )
        user = _COGNITO_USERS[username]
        group = f"{{app-name}}-{user['tenant_id']}-{user['role']}"
        access_token = _jwt({"sub": username, "username": username, "cognito:groups": [group]})
        id_token = _jwt({"sub": username, "email": username, "cognito:username": username})
        return {"AuthenticationResult": {"AccessToken": access_token, "IdToken": id_token, "ExpiresIn": 3600}}

    mock_client = MagicMock()
    mock_client.initiate_auth.side_effect = fake_initiate_auth
    # me() best-effort calls admin_get_user for the email; let it fail so the SDK
    # falls back to the token's username claim (auth tests don't assert on email).
    mock_client.admin_get_user.side_effect = Exception("admin_get_user not mocked")

    with patch("boto3.client", return_value=mock_client):
        yield


# ── Minimum valid item payload ────────────────────────────────────────────────
ITEM_PAYLOAD = {
    "name": "Widget",
    "code": "ITM-001",
    "category": "general",
    "description": "A generic example item",
}
