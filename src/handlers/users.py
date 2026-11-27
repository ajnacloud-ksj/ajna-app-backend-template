"""
User Management for {{app-name}} — the SDK's canonical user routes.

`routes` is the SDK's `user_routes()` map (ajna-cloud >= 4.9.0), spread into app.py, so a new
SDK route arrives with the next base image instead of being hand-listed here. After a
successful invite or remove, the SDK syncs app_users in IbexDB automatically.

Served (see the SDK for each body and answer):
    GET    /v1/users                          POST   /v1/users/invite
    PUT    /v1/users/{username}/role          DELETE /v1/users/{username}
    POST   /v1/users/{username}/suspend       POST   /v1/users/{username}/restore
    POST   /v1/users/{username}/cancel-invite POST   /v1/users/{username}/resend-invitation
    GET    /v1/users/me/capabilities          POST   /v1/admin/users/sync
    POST   /v1/users/{username}/lock|unlock   (DEPRECATED SDK aliases of suspend / restore,
                                               kept while the UI calls them)

No route here sets or resets a sign-in: people sign in at the platform portal. The SDK's
reset-password and password-policy routes stay in the map, as in the apps (Plant Manager, Green
Box, Taksha), and answer 410: the SDK switch (`password_sign_in=False`, here and in
handlers/auth.py) closes them (ajna-cloud-sdk#647).
"""
import os

from ajna_cloud import make_user_management_handlers

from src.config.roles import ALL_ROLES

_handlers = make_user_management_handlers(
    app_prefix=os.environ.get("APP_PREFIX", "{{app-name}}"),
    tenant_roles=ALL_ROLES,  # canonical: super_admin, admin, user
    sync_to_ibex=True,
    # Invites are email invitations only, whatever AJNA_ADMIN_SET_PASSWORD says: an admin never
    # chooses, sees or makes permanent a member's sign-in secret.
    allow_admin_set_password=False,
    # The password door is closed (handlers/auth.py): the SDK's password user routes answer 410.
    password_sign_in=False,
)

#: The SDK routes that set or read a sign-in secret: served only as 410 (#647).
PASSWORD_USER_ROUTES = frozenset({
    ("POST", "/v1/users/{username}/reset-password"),
    ("GET", "/v1/users/password-policy"),
})

routes = _handlers.user_routes()
