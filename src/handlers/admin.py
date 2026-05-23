"""
Tenant & RBAC Administration for {{app-name}}.

Thin wrapper around ajna_cloud SDK handlers. All auth enforcement,
RBAC helpers, and handler logic lives in the SDK.

Routes registered in src/app.py:
  POST   /v1/admin/tenants
  GET    /v1/admin/tenants
  GET    /v1/admin/tenants/{tenant_id}
  PUT    /v1/admin/tenants/{tenant_id}
  POST   /v1/admin/tenants/{tenant_id}/bootstrap
  POST   /v1/admin/rbac/roles
  GET    /v1/admin/rbac/roles
  POST   /v1/admin/rbac/assign
"""
import os
from ajna_cloud import make_tenant_admin_handlers, make_rbac_handlers
from ajna_cloud.cognito import CognitoProvisioner

from src.config.roles import ALL_ROLES, PLATFORM_ADMIN_ROLES, ORG_ADMIN_ROLES
from src.config.tables import (
    TABLE_PREFIX, TENANT_CONFIG_TABLE, ESSENTIAL_TABLES, SCHEMA_DIR, physical,
    ITEMS, TENANT_CONFIG, TENANT_FIELD_CONFIG, USERS, SETTINGS,
)

_NS = os.environ.get("DB_NAMESPACE", "api")

# No default fallback — COGNITO_USER_POOL_ID must be set when AUTH_MODE=cognito.
COGNITO_REGION = os.environ.get("COGNITO_REGION", "ap-south-1")
APP_PREFIX = os.environ.get("APP_PREFIX", "{{app-name}}")
COGNITO_ROLES = ALL_ROLES


def _grants(access_by_table: dict) -> dict:
    """{'items': 'rw', ...} -> {'ibex:{ns}.app_items': 'rw', ...}."""
    return {f"ibex:{_NS}.{physical(t)}": access for t, access in access_by_table.items()}


# Per-tier table access (logical table name -> 'r' | 'rw'). One place to edit grants.
_ADMIN_ACCESS = {
    ITEMS: "rw", TENANT_CONFIG: "rw", TENANT_FIELD_CONFIG: "rw", USERS: "rw", SETTINGS: "rw",
}
_USER_ACCESS = {
    ITEMS: "r", TENANT_FIELD_CONFIG: "r",
}

# Define the default RBAC roles for your application.
# Adjust role_id, role_name, default_access, and table_access to match your domain.
DEFAULT_ROLES = [
    {"role_id": "super_admin", "role_name": "Super Admin",   "default_access": "rw",
     "table_access": _grants(_ADMIN_ACCESS), "column_mask": {}, "row_filters": [], "is_default": False},
    {"role_id": "admin",       "role_name": "Administrator", "default_access": "rw",
     "table_access": _grants(_ADMIN_ACCESS), "column_mask": {}, "row_filters": [], "is_default": False},
    {"role_id": "user",        "role_name": "User",          "default_access": "r",
     "table_access": _grants(_USER_ACCESS),  "column_mask": {}, "row_filters": [], "is_default": True},
]

_cognito_provisioner: CognitoProvisioner | None = None

if os.environ.get("AUTH_MODE", "local").lower() == "cognito":
    _cognito_provisioner = CognitoProvisioner(
        user_pool_id=os.environ["COGNITO_USER_POOL_ID"],
        app_prefix=APP_PREFIX,
        roles=COGNITO_ROLES,
        region=COGNITO_REGION,
    )

_tenant_admin = make_tenant_admin_handlers(
    table=TENANT_CONFIG_TABLE,
    namespace=_NS,
    default_roles=DEFAULT_ROLES,
    cognito_provisioner=_cognito_provisioner,
    essential_tables=ESSENTIAL_TABLES,
    table_prefix=TABLE_PREFIX,
    schemas_dir=SCHEMA_DIR,
    platform_admin_roles=PLATFORM_ADMIN_ROLES,
    org_admin_roles=ORG_ADMIN_ROLES,
)

_rbac = make_rbac_handlers()

# Tenant management
create_tenant = _tenant_admin.create_tenant
list_tenants = _tenant_admin.list_tenants
get_tenant = _tenant_admin.get_tenant
update_tenant = _tenant_admin.update_tenant
bootstrap_tenant = _tenant_admin.bootstrap_tenant

# RBAC management
create_role = _rbac.create_role
list_roles = _rbac.list_roles
assign_role = _rbac.assign_role
