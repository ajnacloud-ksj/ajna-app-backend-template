"""
Auth Handler — the SDK's canonical /v1/auth/* surface, with the password door closed.

Thin wrapper around the ajna_cloud SDK AuthHandlers. Token parsing, RBAC lookup, revocation,
and fallback behaviour live in the SDK.

Sign-in is a platform feature: people sign in at the platform portal and arrive through the
portal hand-off and the SDK's org-door sign-in (``/v1/auth/oidc/{start,callback,token,refresh}``,
cookie session). The app never sees a password.

``routes`` is the SDK's canonical auth route map (``AuthHandlers.auth_routes()``): the org-door
sign-in, logout, me, permissions and config, plus the SDK's six password sign-in keys. The
explicit SDK switch below makes those six answer 410 ``PASSWORD_SIGN_IN_CLOSED``. Since SDK 4.9.0
it is ONE switch: it also closes ``/v1/me/change-password`` and the users reset-password and
password-policy routes (ajna-cloud-sdk#647, #661), and ``/v1/auth/config`` reports
``password_login: false``. src/app.py spreads the map into the router.

Never hand-list /v1/auth routes. The edge (the SDK's DEFAULT_PUBLIC_ROUTES and every stack's
publicRouteKeys) advertises logout as public, so a route missing from a hand-written list 404s
at the Lambda — sign-out then leaves the access token valid until expiry (ajna-cloud-sdk#270,
ajna-app-infra#337).

To wrap one of these handlers, override its key AFTER the spread in src/app.py
(``{**auth.routes, ('GET', '/v1/auth/me'): my_me}``); spreading alone serves the SDK's bare
handler and silently drops the wrapper.
"""
import os
from ajna_cloud import make_auth_handlers
from src.config.roles import ALL_ROLES

_auth = make_auth_handlers(
    app_prefix=os.environ.get("APP_PREFIX", "{{app-name}}"),
    roles=ALL_ROLES,
    # The SDK switch, set explicitly: the password sign-in routes answer 410 whatever the
    # AJNA_PASSWORD_SIGN_IN setting says. People sign in at the platform portal.
    password_sign_in=False,
)

routes = _auth.auth_routes()

me          = _auth.me
permissions = _auth.permissions
