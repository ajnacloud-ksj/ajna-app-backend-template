"""Bulk record import handlers (CSV/Excel or JSON) — generated from the registry.

Add a table to ``IMPORTABLE_TABLES`` to expose its import endpoint; no new
boilerplate. Handlers are keyed by logical table name in ``handlers`` and wired
to ``POST /v1/{url-segment}/import`` in app.py.

  POST /v1/items/import  — bulk import items
"""
from ajna_cloud import make_import_handlers
from src.config.tables import TABLE_PREFIX, ITEMS

IMPORTABLE_TABLES = (ITEMS,)
MAX_RECORDS = 5000

# logical table name -> bound import handler
handlers = {
    table: make_import_handlers(
        table_prefix=TABLE_PREFIX, default_table=table, max_records=MAX_RECORDS
    ).import_records
    for table in IMPORTABLE_TABLES
}
