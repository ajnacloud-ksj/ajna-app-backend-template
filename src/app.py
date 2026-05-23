"""Lambda entry point for {{app-name}} backend."""
import json
import os
from ajna_cloud import (
    create_lambda_app, Router,
    make_database_admin_handlers, make_crud_handlers,
    make_tenant_config_handlers,
)
from ajna_cloud.app import make_tenant_db_factory
from src.config.roles import MASTER_DATA_WRITE_ROLES
from src.config.settings import settings
from src.config.tables import (
    TABLE_PREFIX, ESSENTIAL_TABLES, SCHEMA_DIR, url_segment,
    ITEMS, USERS,
)
from src.handlers import health, items, admin, users, storage, audit, auth, field_config
from src.handlers import imports, exports

_SCHEMA_DIR = SCHEMA_DIR


def _load_schema(name: str) -> dict:
    path = os.path.join(_SCHEMA_DIR, f'{name}.json')
    with open(path) as f:
        return json.load(f)


# Schemas the CRUD factory validates against (keyed by logical table name)
_SCHEMAS = {name: _load_schema(name) for name in (ITEMS, USERS)}

# Attach write-role enforcement to schemas so make_crud_handlers can enforce them
_SCHEMAS[ITEMS]['write_roles'] = MASTER_DATA_WRITE_ROLES

_db_admin = make_database_admin_handlers(
    essential_tables=ESSENTIAL_TABLES,
    table_prefix=TABLE_PREFIX,
    confirm_token='DELETE_{{APP_NAME}}',
    schemas_dir=_SCHEMA_DIR,
)

# Schema-aware CRUD — handles validation, timestamps, and write-role checks
_crud = make_crud_handlers(
    table_prefix=TABLE_PREFIX,
    schemas=_SCHEMAS,
    default_write_roles=MASTER_DATA_WRITE_ROLES,
)

_tenant_config = make_tenant_config_handlers(
    cockpit_url=settings.config.cockpit_api_url or 'https://cockpit-api.triviz.cloud',
    app_name='{{app-name}}',
)

router = Router({
    # ── Health ─────────────────────────────────────────────────────────────────
    ('GET',  '/health'):  health.check,
    ('GET',  '/ready'):   health.ready,
    ('GET',  '/status'):  health.status,

    # ── Public — tenant branding (no auth required) ────────────────────────────
    ('GET',  '/v1/public/tenant/{slug}/config'):  _tenant_config.get_config,

    # ── Auth ───────────────────────────────────────────────────────────────────
    ('POST', '/v1/auth/login'):        auth.login,
    ('GET',  '/v1/auth/me'):           auth.me,
    ('GET',  '/v1/auth/permissions'):  auth.permissions,

    # ── User Sync ──────────────────────────────────────────────────────────────
    ('POST', '/v1/admin/users/sync'):  users.sync_users,

    # ── Database Admin ─────────────────────────────────────────────────────────
    ('POST',   '/v1/admin/database/setup'):        _db_admin.setup_database,
    ('DELETE', '/v1/admin/database/cleanup'):      _db_admin.cleanup_database,
    ('POST',   '/v1/admin/database/reset'):        _db_admin.reset_database,
    ('GET',    '/v1/admin/database/health'):       _db_admin.database_health,
    ('GET',    '/v1/admin/database/tables'):       _db_admin.list_tables,
    ('POST',   '/v1/admin/database/reset-table'):  _db_admin.reset_table,
    ('POST',   '/v1/admin/database/optimize'):     _db_admin.optimize_table,
    ('POST',   '/v1/admin/database/optimize-all'): _db_admin.optimize_all_tables,
    ('POST',   '/v1/admin/database/query'):        _db_admin.execute_query,

    # ── Tenant Management ──────────────────────────────────────────────────────
    ('POST',   '/v1/admin/tenants'):                       admin.create_tenant,
    ('GET',    '/v1/admin/tenants'):                       admin.list_tenants,
    ('GET',    '/v1/admin/tenants/{tenant_id}'):           admin.get_tenant,
    ('PUT',    '/v1/admin/tenants/{tenant_id}'):           admin.update_tenant,
    ('POST',   '/v1/admin/tenants/{tenant_id}/bootstrap'): admin.bootstrap_tenant,

    # ── RBAC Management ────────────────────────────────────────────────────────
    ('POST',   '/v1/admin/rbac/roles'):                  admin.create_role,
    ('GET',    '/v1/admin/rbac/roles'):                  admin.list_roles,
    ('POST',   '/v1/admin/rbac/roles/{role_id}/assign'): admin.assign_role,

    # ── User Management (tenant-scoped) ────────────────────────────────────────
    ('GET',    '/v1/users'):                          users.list_users,
    ('POST',   '/v1/users/invite'):                   users.invite_user,
    ('PUT',    '/v1/users/{username}/role'):           users.update_user_role,
    ('POST',   '/v1/users/{username}/lock'):           users.lock_user,
    ('POST',   '/v1/users/{username}/unlock'):         users.unlock_user,
    ('POST',   '/v1/users/{username}/reset-password'): users.reset_password,
    ('DELETE', '/v1/users/{username}'):               users.remove_user,

    # ── Field Config (per-tenant custom fields) ────────────────────────────────
    ('GET',    '/v1/field-config/{entity_type}'):              field_config.get_field_config,
    ('POST',   '/v1/field-config/{entity_type}'):              field_config.upsert_field_config,
    ('DELETE', '/v1/field-config/{entity_type}/{field_key}'):  field_config.delete_field_config,

    # ── Items (rich query via dedicated handler; standard CRUD via _crud below) ──
    # This is the example RICH-entity feature. Rename `items` to your domain entity.
    ('POST',   '/v1/items/query'):  items.query_items,

    # ── Export / Import routes are registered below from the handler registries ─

    # ── Audit ──────────────────────────────────────────────────────────────────
    ('GET', '/v1/audit/changelog'):       audit.list_changelog,
    ('GET', '/v1/audit/record-history'):  audit.get_record_history,

    # ── Storage ────────────────────────────────────────────────────────────────
    ('POST', '/v1/storage/upload-url'):   storage.get_upload_url,
    ('POST', '/v1/storage/download-url'): storage.get_download_url,
})

# ── Schema-aware CRUD (validates required fields + enforces write roles) ───────
_CRUD_METHODS = ('list', 'create', 'get', 'update', 'delete')
router.crud('/v1/items', ITEMS, _crud, id_param='item_id', methods=_CRUD_METHODS)

# ── Bulk export/import — one POST route per table, from the handler registries ─
# URL segment is derived from the table name (tenant_config -> tenant-config),
# so there is nothing to keep in sync.
for _table, _handler in exports.handlers.items():
    router.add('POST', f'/v1/{url_segment(_table)}/export', _handler)
for _table, _handler in imports.handlers.items():
    router.add('POST', f'/v1/{url_segment(_table)}/import', _handler)

lambda_handler = create_lambda_app(
    router=router,
    settings=settings,
    schema_dir=_SCHEMA_DIR,
    service_name='{{app-name}}',
    db_factory=make_tenant_db_factory(settings),
    db_admin=_db_admin,
)
