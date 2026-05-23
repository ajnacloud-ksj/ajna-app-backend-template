"""
Field config for {{app-name}} — thin wrapper around ajna_cloud SDK.

Per-tenant custom field definitions for entities (e.g. ``items``).

Routes (wired in app.py):
    GET    /v1/field-config/{entity_type}
    POST   /v1/field-config/{entity_type}
    DELETE /v1/field-config/{entity_type}/{field_key}
"""
from ajna_cloud import make_field_config_handlers
from src.config.roles import READ_ROLES, MASTER_DATA_WRITE_ROLES

_h = make_field_config_handlers(read_roles=READ_ROLES, write_roles=MASTER_DATA_WRITE_ROLES)

get_field_config = _h.list_field_config
upsert_field_config = _h.upsert_field_config
delete_field_config = _h.delete_field_config
