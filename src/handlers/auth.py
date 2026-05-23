"""
Auth Handler — login, /me, and /permissions.

Thin wrapper around the ajna_cloud SDK AuthHandlers. All login logic,
token parsing, RBAC lookup, and fallback behaviour live in the SDK.

Routes registered in src/app.py:
  POST /v1/auth/login        — authenticate via Cognito USER_PASSWORD_AUTH
  GET  /v1/auth/me           — return the authenticated user's profile
  GET  /v1/auth/permissions  — return the caller's RBAC RoleDefinition
"""
import os
from ajna_cloud import make_auth_handlers
from src.config.roles import ALL_ROLES

_auth = make_auth_handlers(
    app_prefix=os.environ.get("APP_PREFIX", "{{app-name}}"),
    roles=ALL_ROLES,
)

login       = _auth.login
me          = _auth.me
permissions = _auth.permissions
