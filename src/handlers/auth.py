"""
Auth Handler — the SDK's canonical /v1/auth/* surface.

Thin wrapper around the ajna_cloud SDK AuthHandlers. All login logic,
token parsing, RBAC lookup, revocation, and fallback behaviour live in the SDK.

``routes`` is the SDK's canonical auth route map (``AuthHandlers.auth_routes()``,
SDK >= 1.53.1): login, refresh, logout, mfa, new-password, mfa/enroll,
mfa/verify, me and permissions. src/app.py spreads it into the router.

Never hand-list /v1/auth routes. The edge (the SDK's DEFAULT_PUBLIC_ROUTES and
every stack's publicRouteKeys) advertises logout/refresh as public, so a route
missing from a hand-written list 404s at the Lambda — sign-out then leaves the
access token valid until expiry (ajna-cloud-sdk#270, ajna-app-infra#337).

To wrap one of these handlers, override its key AFTER the spread in src/app.py
(``{**auth.routes, ('POST', '/v1/auth/login'): my_login}``); spreading alone
serves the SDK's bare handler and silently drops the wrapper.
"""
import os
from ajna_cloud import make_auth_handlers
from src.config.roles import ALL_ROLES

_auth = make_auth_handlers(
    app_prefix=os.environ.get("APP_PREFIX", "{{app-name}}"),
    roles=ALL_ROLES,
)

routes = _auth.auth_routes()

login       = _auth.login
me          = _auth.me
permissions = _auth.permissions
