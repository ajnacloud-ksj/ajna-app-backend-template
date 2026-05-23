"""Single source of truth for IbexDB table names.

Hybrid registry:
- **Logical names** are the schema file stems in ``src/schemas/`` (the SDK keys
  ``context['schemas']`` on these). Typed constants are exported for handlers
  and IDE support.
- **Physical names** prepend :data:`TABLE_PREFIX` (e.g. ``items`` ->
  ``app_items``) and are what ``db.*`` calls use directly.
- :data:`ESSENTIAL_TABLES` is *discovered* by scanning the schema directory, so
  dropping a ``<name>.json`` file there auto-registers the table for db setup.

Change the prefix or add a table in exactly one place.
"""
import os

TABLE_PREFIX = 'app_'

SCHEMA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'schemas'))


def physical(name: str) -> str:
    """Logical -> physical table name (idempotent): ``items`` -> ``app_items``."""
    if not name:
        return name
    return name if name.startswith(TABLE_PREFIX) else f'{TABLE_PREFIX}{name}'


def url_segment(name: str) -> str:
    """Logical table name -> kebab-case URL path segment: ``tenant_config`` -> ``tenant-config``."""
    return name.replace('_', '-')


def discover_tables() -> list:
    """All logical table names = schema file stems in :data:`SCHEMA_DIR`."""
    if not os.path.isdir(SCHEMA_DIR):
        return []
    return sorted(f[:-len('.json')] for f in os.listdir(SCHEMA_DIR) if f.endswith('.json'))


# ── Logical names (schema stems) — for SDK factories that take table_prefix ──
ITEMS = 'items'
TENANT_CONFIG = 'tenant_config'
TENANT_FIELD_CONFIG = 'tenant_field_config'
USERS = 'users'
SETTINGS = 'settings'  # app_settings is RBAC-granted but has no schema file

# ── Physical names — for direct db.query / db.write / db.update calls ─────────
ITEM_TABLE = physical(ITEMS)
TENANT_CONFIG_TABLE = physical(TENANT_CONFIG)

# Tables created during tenant/db setup — discovered from the schema directory.
ESSENTIAL_TABLES = discover_tables()
