"""
Tenant & RBAC Administration for {{app-name}}.

Thin wrapper around ajna_cloud SDK handlers. All auth enforcement,
RBAC helpers, and handler logic lives in the SDK.

Routes registered in src/app.py:
  POST   /v1/admin/tenants          (410 Gone: customers are added in the cockpit)
  GET    /v1/admin/tenants
  GET    /v1/admin/tenants/{tenant_id}
  PUT    /v1/admin/tenants/{tenant_id}
  POST   /v1/admin/rbac/roles
  GET    /v1/admin/rbac/roles
  POST   /v1/admin/rbac/roles/{role_id}/assign

Token only (SDK 4, ajna-app-infra#1554): the app does not create, bootstrap or provision orgs.
The cockpit adds an org to the app ("add org to app"), creates its login groups and runs the
deploy-time db-setup, which creates the tables and reconciles ``DEFAULT_ROLES`` for every org
(``make_database_admin_handlers(default_roles=...)`` in src/app.py). The old
``POST /v1/admin/tenants/{tenant_id}/bootstrap`` route is gone: it created tables at runtime
(never allowed under tokens), wrote another org's roles with a person's token (refused: a token
acts for its own org only) and created login groups (the cockpit's job).
"""
import os
from ajna_cloud import make_tenant_admin_handlers, make_rbac_handlers
from ajna_cloud.data_area import grant_namespace
from ajna_cloud.http import respond

from src.config.roles import PLATFORM_ADMIN_ROLES, ORG_ADMIN_ROLES
from src.config.tables import (
    TENANT_CONFIG_TABLE, physical,
    ITEMS, TENANT_CONFIG, TENANT_FIELD_CONFIG, USERS, SETTINGS,
)

_NS = os.environ.get("DB_NAMESPACE", "api")


def _grants(access_by_table: dict) -> dict:
    """{'items': 'rw', ...} -> {'ibex:{ns}.app_items': 'rw', ...}.

    ``ns`` is the SDK's grant namespace, so the keys follow the effective data area: in
    per-app mode (``AJNA_DATA_AREA=per-app``) a shared ``_NS`` (``default``/``api``) becomes
    the app namespace. Do not use ``_NS`` directly here: it bypasses that rewrite."""
    ns = grant_namespace(_NS)
    return {f"ibex:{ns}.{physical(t)}": access for t, access in access_by_table.items()}


# Per-tier table access (logical table name -> 'r' | 'rw'). One place to edit grants.
_ADMIN_ACCESS = {
    ITEMS: "rw", TENANT_CONFIG: "rw", TENANT_FIELD_CONFIG: "rw", USERS: "rw", SETTINGS: "rw",
}
_USER_ACCESS = {
    ITEMS: "r", TENANT_FIELD_CONFIG: "r",
}

# Define the default RBAC roles for your application.
# Adjust role_id, role_name, default_access, and table_access to match your domain.
# Keep bare role ids here: in per-app mode the SDK client stores them app-scoped
# (``<app namespace>.admin``), and never seeds or scopes ``super_admin`` (org-wide, platform).
DEFAULT_ROLES = [
    {"role_id": "super_admin", "role_name": "Super Admin",   "default_access": "rw",
     "table_access": _grants(_ADMIN_ACCESS), "column_mask": {}, "row_filters": [], "is_default": False},
    {"role_id": "admin",       "role_name": "Administrator", "default_access": "rw",
     "table_access": _grants(_ADMIN_ACCESS), "column_mask": {}, "row_filters": [], "is_default": False},
    {"role_id": "user",        "role_name": "User",          "default_access": "r",
     "table_access": _grants(_USER_ACCESS),  "column_mask": {}, "row_filters": [], "is_default": True},
]

# Read and update only (create is 410 below). No cognito provisioner and no default roles:
# both served only the removed bootstrap route.
_tenant_admin = make_tenant_admin_handlers(
    table=TENANT_CONFIG_TABLE,
    namespace=_NS,
    platform_admin_roles=PLATFORM_ADMIN_ROLES,
    org_admin_roles=ORG_ADMIN_ROLES,
)

# default_roles: list_roles heals an org that misses a declared role, and custom roles may only
# grant the tables these roles name.
_rbac = make_rbac_handlers(default_roles=DEFAULT_ROLES)

TENANT_CREATE_GONE = (
    "Tenants are not created by the app. Add the customer in the cockpit: "
    "Organizations -> add org to app. The cockpit creates the org and the tenant, "
    "then provisions this app."
)


def create_tenant(event, context):
    """POST /v1/admin/tenants: disabled, always 410.

    A tenant created here had no cockpit tenant row and no org, so the cockpit could
    not see it and its login gate reported the tenant as 'unknown'. The cockpit's
    "add org to app" is the only create path; it provisions this app through the
    `_provision` Lambda event, not through this route (ajna-app-backend-template#13).
    """
    return respond(410, {"error": TENANT_CREATE_GONE, "status": "gone"}, event=event)


# Tenant management (read and update only; see create_tenant above)
list_tenants = _tenant_admin.list_tenants
get_tenant = _tenant_admin.get_tenant
update_tenant = _tenant_admin.update_tenant

# RBAC management
create_role = _rbac.create_role
list_roles = _rbac.list_roles
assign_role = _rbac.assign_role
