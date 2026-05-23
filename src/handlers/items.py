"""
Items Handler — dedicated CRUD for the example ``items`` table.

This is the reference RICH-entity pattern for {{app-name}}: rename ``items`` to
your domain entity (or add more handlers modelled on this one).

Uses make_crud_handlers with the items schema for validation, timestamps, and
write-role enforcement. Each SDK bound handler is wrapped with @require_roles so
the SDK's _check_write_role can read event['_auth'].

Bound handlers (registered via router.add() in app.py):
  list_items    → GET    /v1/items
  create_item   → POST   /v1/items
  get_item      → GET    /v1/items/{item_id}
  update_item   → PUT    /v1/items/{item_id}
  delete_item   → DELETE /v1/items/{item_id}
  query_items   → POST   /v1/items/query  (rich filter/sort/pagination)
"""
import json
import os
from typing import Any, Dict

from ajna_cloud import make_crud_handlers
from ajna_cloud.auth import require_roles
from ajna_cloud.http import respond
from ajna_cloud.logger import log_handler, logger
from src.lib.sanitize import sanitize
from src.config.roles import READ_ROLES, MASTER_DATA_WRITE_ROLES
from src.config.tables import TABLE_PREFIX, ITEMS, ITEM_TABLE

# Load items schema once and attach write_roles for SDK enforcement
_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), '..', 'schemas', f'{ITEMS}.json')
with open(_SCHEMA_PATH) as _f:
    _ITEM_SCHEMA = json.load(_f)
_ITEM_SCHEMA['write_roles'] = MASTER_DATA_WRITE_ROLES

_crud = make_crud_handlers(
    table_prefix=TABLE_PREFIX,
    schemas={ITEMS: _ITEM_SCHEMA},
    default_write_roles=MASTER_DATA_WRITE_ROLES,
)

# ── Bound handlers ─────────────────────────────────────────────────────────────
# @require_roles is applied first so it sets event['_auth'] before the SDK's
# _check_write_role reads it. This is the correct SDK composition pattern.

list_items  = require_roles(READ_ROLES)(_crud.list(ITEMS))
get_item    = require_roles(READ_ROLES)(_crud.get(ITEMS, id_param='item_id'))
create_item = require_roles(MASTER_DATA_WRITE_ROLES)(_crud.create(ITEMS))
update_item = require_roles(MASTER_DATA_WRITE_ROLES)(_crud.update(ITEMS, id_param='item_id'))
delete_item = require_roles(MASTER_DATA_WRITE_ROLES)(_crud.delete(ITEMS, id_param='item_id'))


# ── Rich query handler ─────────────────────────────────────────────────────────

@log_handler
@require_roles(READ_ROLES)
def query_items(event: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """POST /v1/items/query — rich filter/sort/pagination query."""
    db = context['db']
    body: Dict[str, Any] = {}
    if event.get('body'):
        try:
            body = json.loads(event['body'])
        except json.JSONDecodeError:
            return respond(400, {"error": "Invalid JSON"}, event=event)

    limit  = min(int(body.get('limit', 50)), 1000)
    offset = int(body.get('offset', 0))

    try:
        kwargs: Dict[str, Any] = {"limit": limit, "use_cache": False}
        if body.get('filters'):
            kwargs['filters'] = body['filters']
        if body.get('sort'):
            kwargs['sort'] = body['sort']
        if body.get('projection'):
            kwargs['projection'] = body['projection']
        if offset > 0:
            kwargs['offset'] = offset

        result = db.query(ITEM_TABLE, **kwargs)
        if result and result.get('success'):
            records = [sanitize(r) for r in result.get('data', {}).get('records', [])]
            return respond(200, {"success": True, "data": records, "count": len(records)}, event=event)

        return respond(500, {"error": "Failed to retrieve items"}, event=event)

    except Exception as e:
        logger.error(f"query_items error: {e}")
        return respond(500, {"error": str(e)}, event=event)
