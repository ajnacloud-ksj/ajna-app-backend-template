"""New apps are born with the password door closed: people sign in only at the platform portal.

Owner decision: sign-in is a platform feature. People arrive through the portal hand-off and the
SDK's org-door sign-in (``/v1/auth/oidc/*``, cookie session). An app built from this template
serves no password sign-in, MFA, new-password, change-password, reset-password or password-policy
route. Two layers close them:

* the SDK switch, set explicitly in ``src/handlers/auth.py`` (SDK >= 4.7.0): the six password
  sign-in routes answer 410;
* ``src/handlers/password_door.py`` around the whole route table: every route whose path names a
  password, including the users reset-password and password-policy routes that the SDK still
  leaves open (ajna-cloud-sdk#647).

The checks walk the REAL route table (``src.app.router``), not a hand list, so a password route
that a later SDK or a later app change adds fails here until it is closed.

The template check at the end fails when password-era sign-in comes back into the template's
source, scripts, CI, dev.sh, .env.example, README or docs.
"""
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from src import app as app_module

CLOSED_CODE = "PASSWORD_SIGN_IN_CLOSED"
REPO = Path(__file__).resolve().parent.parent
ROUTES = app_module.router.route_table

#: The SDK's password sign-in routes (ajna_cloud.password_sign_in.PASSWORD_ROUTES, SDK >= 4.7.0).
SDK_PASSWORD_ROUTES = frozenset({
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/refresh"),
    ("POST", "/v1/auth/mfa"),
    ("POST", "/v1/auth/new-password"),
    ("POST", "/v1/auth/mfa/enroll"),
    ("POST", "/v1/auth/mfa/verify"),
})

#: Every route that must answer 410 when the app mounts it.
MUST_CLOSE = SDK_PASSWORD_ROUTES | {
    ("POST", "/v1/me/change-password"),
    # ajna-cloud-sdk#647: an app admin could set a member's PERMANENT portal password.
    ("POST", "/v1/users/{username}/reset-password"),
    ("GET", "/v1/users/password-policy"),
}

#: The org-door sign-in and the session reads stay the SDK's own handlers.
KEPT_ROUTES = frozenset({
    ("POST", "/v1/auth/logout"),
    ("GET", "/v1/auth/me"),
    ("GET", "/v1/auth/permissions"),
    ("GET", "/v1/auth/config"),
    ("POST", "/v1/auth/oidc/token"),
    ("POST", "/v1/auth/oidc/refresh"),
    ("GET", "/v1/auth/oidc/start"),
    ("GET", "/v1/auth/oidc/callback"),
})

#: User management that stays until the platform Members block replaces it; the UI uses it.
KEPT_USER_ROUTES = frozenset({
    ("GET", "/v1/users"),
    ("POST", "/v1/users/invite"),
    ("PUT", "/v1/users/{username}/role"),
    ("POST", "/v1/users/{username}/lock"),
    ("POST", "/v1/users/{username}/unlock"),
    ("DELETE", "/v1/users/{username}"),
    ("POST", "/v1/admin/users/sync"),
    ("POST", "/v1/admin/rbac/roles"),
    ("GET", "/v1/admin/rbac/roles"),
    ("POST", "/v1/admin/rbac/roles/{role_id}/assign"),
})

# Built at run time: never a word-like literal in the source.
SECRET = "x" * 12
EVENT = {
    "httpMethod": "POST",
    "headers": {"origin": "http://localhost:5173"},
    "pathParameters": {"username": "a@example.com"},
    "body": json.dumps({"username": "a@example.com", "permanent": True, "code": "123456",
                        **{field: SECRET for field in ("password", "new_password")}}),
}


def _is_password_route(route) -> bool:
    _, path = route
    return route in MUST_CLOSE or "password" in path.lower()


def _password_routes_in_the_table():
    return sorted(r for r in ROUTES if _is_password_route(r))


def _answer(handler):
    with patch("boto3.client", side_effect=AssertionError("Cognito was called")), \
         patch("boto3.session.Session.client", side_effect=AssertionError("Cognito was called")):
        return handler(dict(EVENT), {})


# ── Every password route in the real table answers 410 ───────────────────────────────────────

def test_the_table_has_the_password_routes_to_close():
    # Guards the scan below: the SDK auth map keeps its six password keys, so the loop is not vacuous.
    assert SDK_PASSWORD_ROUTES <= set(_password_routes_in_the_table())


@pytest.mark.parametrize("route", _password_routes_in_the_table(), ids=" ".join)
def test_every_password_route_answers_410_before_any_cognito_call(route):
    resp = _answer(ROUTES[route])
    assert resp["statusCode"] == 410, f"{route} answered {resp['statusCode']}"
    body = json.loads(resp["body"])
    assert body["code"] == CLOSED_CODE
    assert "portal" in body["error"]
    assert SECRET not in resp["body"]


def test_no_other_route_is_closed():
    closed = {r for r, h in ROUTES.items() if not _is_password_route(r)
              and getattr(h, "__name__", "") == "password_sign_in_closed"}
    assert closed == set()


def test_the_users_password_handlers_are_gone():
    from src.handlers import users

    assert not hasattr(users, "reset_password")
    assert not hasattr(users, "password_policy")


def test_the_sdk_switch_is_set_in_the_auth_map():
    # Layer one: the SDK itself closes its six routes (explicit argument in src/handlers/auth.py).
    sdk = pytest.importorskip("ajna_cloud.password_sign_in",
                              reason="SDK < 4.7.0 has no password sign-in switch")
    from src.handlers import auth

    for route in SDK_PASSWORD_ROUTES:
        assert auth.routes[route] is sdk.closed, f"{route} is open in the SDK auth map"


# ── What stays open ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", sorted(KEPT_ROUTES | KEPT_USER_ROUTES), ids=" ".join)
def test_a_kept_route_is_served_and_not_closed(route):
    assert route in ROUTES, f"{route} is no longer served"
    assert not _is_password_route(route)
    assert getattr(ROUTES[route], "__name__", "") != "password_sign_in_closed"


def test_the_org_door_sign_in_stays_the_sdk_handlers():
    from ajna_cloud.handlers import oidc_bff, oidc_session

    assert ROUTES[("GET", "/v1/auth/oidc/start")] is oidc_bff.oidc_start
    assert ROUTES[("GET", "/v1/auth/oidc/callback")] is oidc_bff.oidc_callback
    assert ROUTES[("POST", "/v1/auth/oidc/token")] is oidc_session.oidc_token
    assert ROUTES[("POST", "/v1/auth/oidc/refresh")] is oidc_session.oidc_refresh


def test_logout_me_and_permissions_stay_the_sdk_handlers():
    from src.handlers import auth

    sdk = auth._auth.auth_routes()
    for route in [("POST", "/v1/auth/logout"), ("GET", "/v1/auth/me"),
                  ("GET", "/v1/auth/permissions")]:
        assert ROUTES[route] == sdk[route]


def test_auth_config_reports_no_password_login():
    resp = ROUTES[("GET", "/v1/auth/config")]({"headers": {}}, {})
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["password_login"] is False
    assert "provider" in body and "client_id" in body


def test_the_local_list_matches_the_sdk_when_it_has_one():
    sdk = pytest.importorskip("ajna_cloud.password_sign_in",
                              reason="SDK < 4.7.0 has no ajna_cloud.password_sign_in")
    from src.handlers import password_door

    assert password_door.PASSWORD_ROUTES == sdk.PASSWORD_ROUTES == SDK_PASSWORD_ROUTES
    assert KEPT_ROUTES == sdk.KEPT_ROUTES


# ── No file in the template teaches or calls password sign-in ────────────────────────────────

FORBIDDEN = re.compile(
    r"DEV_LOGIN_EMAIL|DEV_LOGIN_PASSWORD|/v1/auth/login|cognito-idp|initiate_auth|InitiateAuth"
    r"|USER_PASSWORD_AUTH|admin_set_user_password|AdminSetUserPassword|set_password\("
)

#: The only allowed hits, as {(relative path, matched text): reason}. A reviewer agrees to each.
#: This guard file is outside the scanned paths (tests/), so it needs no entry.
ALLOWED_HITS: dict = {
    # The module that CLOSES the route lists it in PASSWORD_ROUTES; it serves nothing there.
    ("src/handlers/password_door.py", "/v1/auth/login"): "the closed-route list",
}

SCANNED_DIRS = ("src", "scripts", "ci", "docs")
SCANNED_FILES = ("dev.sh", ".env.example", "README.md")


def _scanned_files():
    for top in SCANNED_DIRS:
        root = REPO / top
        if root.is_dir():
            yield from (p for p in sorted(root.rglob("*")) if p.is_file()
                        and "__pycache__" not in p.parts)
    for name in SCANNED_FILES:
        if (REPO / name).is_file():
            yield REPO / name


def _hits(text: str, rel: str):
    for n, line in enumerate(text.splitlines(), 1):
        for m in FORBIDDEN.finditer(line):
            if (rel, m.group(0)) not in ALLOWED_HITS:
                yield f"{rel}:{n}: {m.group(0)}"


def test_the_template_has_no_password_sign_in():
    hits = []
    for path in _scanned_files():
        rel = str(path.relative_to(REPO))
        hits.extend(_hits(path.read_text(encoding="utf-8", errors="replace"), rel))
    assert not hits, "password sign-in in the template:\n" + "\n".join(hits)


def test_every_allowed_hit_is_still_there():
    # A stale allow-list entry would quietly allow a later hit in that file.
    for (rel, token), _reason in ALLOWED_HITS.items():
        assert token in (REPO / rel).read_text(encoding="utf-8"), f"stale entry {rel}"


@pytest.mark.parametrize("sample", [
    "c = boto3.client('cognito-idp')",
    "idp.initiate_auth(AuthFlow='USER_PASSWORD_AUTH')",
    "admin.set_password(u, p, permanent=True)",
    "idp.admin_set_user_password(UserPoolId=p, Username=u, Permanent=True)",
    'curl -X POST "$URL/v1/auth/login"',
    "_".join(["DEV", "LOGIN", "EMAIL"]),
    "_".join(["DEV", "LOGIN", "PASSWORD"]),
])
def test_the_scan_finds_a_planted_password_flow(sample):
    assert list(_hits(sample, "planted.py"))


# ── The override itself ──────────────────────────────────────────────────────────────────────

def test_close_password_door_does_not_change_its_input():
    from src.handlers import password_door

    login, me = object(), object()
    routes = {("POST", "/v1/auth/login"): login, ("GET", "/v1/auth/me"): me}
    before = dict(routes)
    out = password_door.close_password_door(routes)
    assert routes == before
    assert out[("POST", "/v1/auth/login")] is password_door.password_sign_in_closed
    assert out[("GET", "/v1/auth/me")] is me


def test_a_new_route_that_names_a_password_is_closed():
    from src.handlers import password_door

    out = password_door.close_password_door({("PUT", "/v1/admin/users/{u}/set-password"): object()})
    assert out[("PUT", "/v1/admin/users/{u}/set-password")] is password_door.password_sign_in_closed


def test_config_passes_a_non_json_answer_through_unchanged():
    from src.handlers import password_door

    raw = {"statusCode": 503, "headers": {}, "body": "not json"}
    wrapped = password_door.close_password_door({("GET", "/v1/auth/config"): lambda e, c: raw})
    assert wrapped[("GET", "/v1/auth/config")]({}, {}) == raw


def test_an_invite_never_takes_an_admin_chosen_secret(monkeypatch):
    # The SDK invite can set a permanent secret when AJNA_ADMIN_SET_PASSWORD is on; the template
    # pins it off in code, so the setting cannot turn it back on.
    from src.handlers import users

    monkeypatch.setenv("AJNA_ADMIN_SET_PASSWORD", "true")
    assert users._handlers._admin_set_password_enabled() is False
