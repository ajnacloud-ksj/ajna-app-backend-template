"""The app's own password door, closed: people sign in only at the platform portal.

Owner decision: sign-in is a platform feature. People arrive through the portal hand-off and the
SDK's org-door sign-in (``/v1/auth/oidc/{start,callback,token,refresh}``, cookie session), which
stay open together with ``/v1/auth/{logout,me,permissions,config}``.

CLOSED (410 ``PASSWORD_SIGN_IN_CLOSED``, before any Cognito call, the request never echoed):

* the SDK's password sign-in routes (:data:`PASSWORD_ROUTES`, the same set as
  ``ajna_cloud.password_sign_in.PASSWORD_ROUTES`` in SDK >= 4.7.0) and
  ``POST /v1/me/change-password``;
* ``POST /v1/users/{username}/reset-password`` and ``GET /v1/users/password-policy``
  (ajna-cloud-sdk#647: an app admin could set a member's PERMANENT portal password), if mounted;
* an app's own ``POST /v1/admin/users/{username}/reset-password``, if an app adds one;
* any other route whose path names a password, so a route that a later SDK adds is closed too.

Why this module as well as the SDK switch: the template sets the SDK's ``password_sign_in``
argument to False in ``src/handlers/auth.py`` (SDK >= 4.7.0), which closes the six sign-in
routes. Even 4.8.0 leaves the two users routes open, and an app on an older base image has no
switch. This override closes them all, on 4.6.0 and on 4.7+/4.8. The same module is in the app
backends (green-box-telemetry-backend#123).

When the SDK ships the #647 fix, the users-route part of this module can go.

``GET /v1/auth/config`` keeps the SDK handler but reports that the password door is off, so no
UI offers a password form.
"""
import json
from collections.abc import Callable
from typing import Any

from ajna_cloud.http import respond

Route = tuple[str, str]
Handler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

#: The SDK's password sign-in routes (ajna_cloud.password_sign_in.PASSWORD_ROUTES).
PASSWORD_ROUTES: frozenset = frozenset({
    ('POST', '/v1/auth/login'),
    ('POST', '/v1/auth/refresh'),
    ('POST', '/v1/auth/mfa'),
    ('POST', '/v1/auth/new-password'),
    ('POST', '/v1/auth/mfa/enroll'),
    ('POST', '/v1/auth/mfa/verify'),
})

#: Every route this app closes when it is mounted.
CLOSED_ROUTES: frozenset = PASSWORD_ROUTES | {
    ('POST', '/v1/me/change-password'),
    ('POST', '/v1/users/{username}/reset-password'),
    ('GET', '/v1/users/password-policy'),
    ('POST', '/v1/admin/users/{username}/reset-password'),
}

PASSWORD_SIGN_IN_CLOSED = "PASSWORD_SIGN_IN_CLOSED"
_CLOSED_BODY = {
    "error": "Password sign-in is closed. Sign in through your organisation's portal.",
    "code": PASSWORD_SIGN_IN_CLOSED,
}

_CONFIG_ROUTE: Route = ('GET', '/v1/auth/config')


def password_sign_in_closed(event: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """A closed password route: 410 Gone, before any Cognito call, with no credential echoed."""
    return respond(410, dict(_CLOSED_BODY), event=event)


def is_closed_route(route: Route) -> bool:
    """True for a route this app closes: a listed one, or any path that names a password."""
    _, path = route
    return route in CLOSED_ROUTES or 'password' in path.lower()


def _without_password_login(config_handler: Handler) -> Handler:
    """``GET /v1/auth/config`` that says the password door is off: no UI offers a password form."""

    def get_login_config(event: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        resp = config_handler(event, context)
        try:
            body = json.loads(resp.get("body") or "{}")
        except (TypeError, ValueError):
            return resp
        if not isinstance(body, dict) or "password_login" not in body:
            return resp
        return {**resp, "body": json.dumps({**body, "password_login": False})}

    return get_login_config


def close_password_door(routes: dict[Route, Handler]) -> dict[Route, Handler]:
    """``routes`` with the password door closed (a new dict; the input is kept)."""
    closed = {
        key: (password_sign_in_closed if is_closed_route(key) else handler)
        for key, handler in routes.items()
    }
    if _CONFIG_ROUTE in closed:
        return {**closed, _CONFIG_ROUTE: _without_password_login(closed[_CONFIG_ROUTE])}
    return closed
