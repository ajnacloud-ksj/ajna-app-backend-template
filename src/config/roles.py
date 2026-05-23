"""
Role constants for {{app-name}} RBAC system.

Standard platform roles are imported from the SDK — do not redefine them as strings.
Apps may add domain-specific roles and insert them between the standard tiers.

Permission matrix (default — adjust per app):
  Action                         | super_admin | admin | user
  -------------------------------|-------------|-------|------
  Read data                      |      ✓      |   ✓   |   ✓
  Write data                     |      ✓      |   ✓   |   ✗
  Manage users & org settings    |      ✓      |   ✓   |   ✗
  Cross-tenant / platform ops    |      ✓      |   ✗   |   ✗

To add domain-specific roles, define them here and insert into ALL_ROLES:
  ANALYST = 'analyst'
  ALL_ROLES = [SUPER_ADMIN, ADMIN, ANALYST, USER]
"""
from ajna_cloud.roles import SUPER_ADMIN, ADMIN, USER  # noqa: F401 — re-exported for convenience

# Full ordered role list — highest privilege first.
# SUPER_ADMIN, ADMIN, USER are reserved and provisioned by Cockpit.
# Insert app-specific roles between them as needed.
ALL_ROLES = [SUPER_ADMIN, ADMIN, USER]

READ_ROLES        = [SUPER_ADMIN, ADMIN, USER]
WRITE_ROLES       = [SUPER_ADMIN, ADMIN]
ORG_ADMIN_ROLES   = [SUPER_ADMIN, ADMIN]
PLATFORM_ADMIN_ROLES = [SUPER_ADMIN]

# Alias for handlers/factories that enforce master-data write access.
MASTER_DATA_WRITE_ROLES = WRITE_ROLES
