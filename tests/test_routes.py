"""Route-table contract tests for src/app.py.

The edge (the SDK's DEFAULT_PUBLIC_ROUTES and every stack's publicRouteKeys) advertises
the /v1/auth/* routes as public. A route advertised there but not registered here 404s at
the Lambda — which is how POST /v1/auth/logout 404'd fleet-wide and sign-out left the
access token valid (ajna-cloud-sdk#270). These tests pin the served auth surface to the
SDK's canonical map so a hand-written list cannot drift from it again.
"""
import json

import pytest

from src.app import router
from src.handlers import auth


def _auth_route_keys(table):
    return {key for key in table if key[1].startswith('/v1/auth/')}


def test_every_sdk_auth_route_is_served():
    served = _auth_route_keys(router.route_table)
    assert served == set(auth.routes), (
        "src/app.py must serve exactly the SDK's auth_routes(); "
        f"missing={set(auth.routes) - served} extra={served - set(auth.routes)}"
    )


def test_auth_routes_map_to_the_sdk_handlers():
    table = router.route_table
    for key, handler in auth.routes.items():
        assert table[key] == handler, f"{key} is not wired to the SDK handler"


@pytest.mark.parametrize("key", [
    ('POST', '/v1/auth/login'),
    ('POST', '/v1/auth/refresh'),
    ('POST', '/v1/auth/logout'),
    ('GET',  '/v1/auth/me'),
    ('GET',  '/v1/auth/permissions'),
])
def test_core_auth_route_is_registered(key):
    assert key in router.route_table


def test_logout_is_public_at_the_router():
    assert router.is_public('POST', '/v1/auth/logout')


def test_post_logout_dispatches_instead_of_404():
    """No bearer token: the SDK logout clears the refresh cookie and returns 200."""
    event = {
        "httpMethod": "POST",
        "resource": "/v1/auth/logout",
        "path": "/v1/auth/logout",
        "headers": {},
        "queryStringParameters": None,
        "pathParameters": None,
        "body": None,
    }
    resp = router.route(event, {})
    assert resp["statusCode"] == 200, resp
    assert json.loads(resp["body"]).get("ok") is True
