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
# Every deployed app has APP_PREFIX (the Pulumi AppStack injects it), and both the
# app (src/handlers/auth.py) and the SDK's Cognito provider read it. Pin it here so
# the tests build Cognito group names from the same value the code parses them with.
os.environ.setdefault("APP_PREFIX", "{{app-name}}")
APP_PREFIX = os.environ["APP_PREFIX"]

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


# A test RSA key pair stands in for the Cognito user pool's signing key. /v1/auth/me
# VERIFIES the bearer token (signature, issuer, expiry, client_id) through the SDK's
# CognitoAuthProvider, so the tokens must be real RS256 JWTs that the pool's JWKS
# (served by the patched requests.get below) can verify.
_TEST_KID = "test-kid"
_TEST_ISSUER = (
    f"https://cognito-idp.{os.environ['COGNITO_REGION']}.amazonaws.com/"
    f"{os.environ['COGNITO_USER_POOL_ID']}"
)
_TEST_JWKS_URL = f"{_TEST_ISSUER}/.well-known/jwks.json"


def _make_test_signing_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwk

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    public_jwk = {**jwk.construct(public_pem, "RS256").to_dict(), "kid": _TEST_KID, "use": "sig"}
    return private_pem, {"keys": [public_jwk]}


_TEST_PRIVATE_PEM, _TEST_JWKS = _make_test_signing_key()


@contextmanager
def mock_cognito_login():
    """
    Patches boto3 and the JWKS fetch so the SDK's Cognito auth path works without a real pool.

    Login (ajna_cloud.handlers.auth) reads role+tenant from the ``cognito:groups``
    claim of the AccessToken, which Cockpit provisions as ``{APP_PREFIX}-{tenant_id}-{role}``.
    /me then verifies that AccessToken against the pool's JWKS before it trusts any
    claim, so the mock returns RS256 tokens signed by the test key, with the pool
    issuer, ``token_use=access`` and the app client id — the claims a real Cognito
    AccessToken carries.
    """
    import time

    from jose import jwt as jose_jwt

    def _jwt(claims: Dict[str, Any]) -> str:
        now = int(time.time())
        base = {"iss": _TEST_ISSUER, "iat": now, "exp": now + 3600}
        return jose_jwt.encode({**base, **claims}, _TEST_PRIVATE_PEM, algorithm="RS256",
                               headers={"kid": _TEST_KID})

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
        # Plain concatenation, not an f-string literal: in an f-string the template
        # placeholder's doubled braces collapse to single ones, so the group would no
        # longer match the prefix that src/handlers/auth.py parses with.
        group = "-".join([APP_PREFIX, user["tenant_id"], user["role"]])
        access_token = _jwt({
            "sub": username,
            "username": username,
            "token_use": "access",
            "client_id": os.environ["COGNITO_CLIENT_ID"],
            "cognito:groups": [group],
        })
        id_token = _jwt({
            "sub": username,
            # The SDK reports user.username from the IdToken email claim (_build_result),
            # and test_login_returns_token_for_all_roles expects the login name there.
            "email": username,
            "cognito:username": username,
            "token_use": "id",
            "aud": os.environ["COGNITO_CLIENT_ID"],
        })
        return {"AuthenticationResult": {"AccessToken": access_token, "IdToken": id_token, "ExpiresIn": 3600}}

    def fake_requests_get(url, *args, **kwargs):
        # Only the user pool's JWKS is served. Any other URL fails the test loudly
        # instead of reaching the network.
        if url != _TEST_JWKS_URL:
            raise AssertionError(f"unexpected HTTP GET in auth tests: {url}")
        response = MagicMock()
        response.json.return_value = _TEST_JWKS
        response.raise_for_status.return_value = None
        return response

    mock_client = MagicMock()
    mock_client.initiate_auth.side_effect = fake_initiate_auth
    # me() and the provider look up the email best-effort (admin_get_user / get_user);
    # let both fail so the SDK takes its no-email fallback (auth tests do not assert on email).
    mock_client.admin_get_user.side_effect = Exception("admin_get_user not mocked")
    mock_client.get_user.side_effect = Exception("get_user not mocked")

    with patch("boto3.client", return_value=mock_client), \
            patch("requests.get", side_effect=fake_requests_get):
        yield


# ── Minimum valid item payload ────────────────────────────────────────────────
ITEM_PAYLOAD = {
    "name": "Widget",
    "code": "ITM-001",
    "category": "general",
    "description": "A generic example item",
}
