"""Audit changelog and record history endpoints."""
import os
from ajna_cloud.auth import require_roles
from ajna_cloud.handlers.audit import make_audit_handlers
from ajna_cloud.cognito import CognitoProvisioner
from src.config.roles import ORG_ADMIN_ROLES, ALL_ROLES

_cognito_provisioner = None
if os.environ.get("AUTH_MODE", "local").lower() == "cognito":
    _cognito_provisioner = CognitoProvisioner(
        user_pool_id=os.environ["COGNITO_USER_POOL_ID"],
        app_prefix=os.environ.get("APP_PREFIX", "{{app-name}}"),
        roles=ALL_ROLES,
        region=os.environ.get("COGNITO_REGION", "ap-south-1"),
    )

_handlers = make_audit_handlers(
    roles=ORG_ADMIN_ROLES,
    cognito_provisioner=_cognito_provisioner,
)

list_changelog = require_roles(ORG_ADMIN_ROLES)(_handlers.list_changelog)
get_record_history = require_roles(ORG_ADMIN_ROLES)(_handlers.get_record_history)
