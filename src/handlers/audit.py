"""Audit changelog and record history endpoints."""
import os
from ajna_cloud.auth import require_roles
from ajna_cloud.handlers.audit import make_audit_handlers
from ajna_cloud.ports import user_admin
from ajna_cloud.user_provisioning import TenantUserProvisioner
from src.config.roles import ORG_ADMIN_ROLES, ALL_ROLES

# User ids in the trail are resolved to emails through the SDK user-admin brick, so
# this works on any login provider and carries no AWS region.
_cognito_provisioner = None
if os.environ.get("AUTH_MODE", "local").lower() != "local":
    _cognito_provisioner = TenantUserProvisioner(
        user_admin.provider(),
        app_prefix=os.environ.get("APP_PREFIX", "{{app-name}}"),
        roles=ALL_ROLES,
    )

_handlers = make_audit_handlers(
    roles=ORG_ADMIN_ROLES,
    cognito_provisioner=_cognito_provisioner,
)

list_changelog = require_roles(ORG_ADMIN_ROLES)(_handlers.list_changelog)
get_record_history = require_roles(ORG_ADMIN_ROLES)(_handlers.get_record_history)
