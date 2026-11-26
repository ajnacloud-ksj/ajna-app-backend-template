"""
User Management for {{app-name}} — thin wrapper around ajna_cloud SDK.

Delegates to ajna_cloud SDK tenant-scoped user management. After a successful
invite or remove, the SDK syncs app_users in IbexDB automatically.

Routes (wired in app.py):
    POST   /v1/admin/users/sync
    GET    /v1/users
    POST   /v1/users/invite
    PUT    /v1/users/{username}/role
    POST   /v1/users/{username}/lock
    POST   /v1/users/{username}/unlock
    DELETE /v1/users/{username}

No route here sets or resets a sign-in: people sign in at the platform portal, and the
SDK's reset-password and password-policy handlers are not exported (ajna-cloud-sdk#647).
These routes move to the platform Members block later; the UI still uses them.
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
)

list_users = _handlers.list_users
invite_user = _handlers.invite_user
update_user_role = _handlers.update_user_role
lock_user = _handlers.lock_user
unlock_user = _handlers.unlock_user
remove_user = _handlers.remove_user
sync_users = _handlers.sync_users
