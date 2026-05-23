"""CSV export handlers — one per exportable table, generated from the registry.

Add a table to ``EXPORTABLE_TABLES`` to expose its export endpoint; no new
boilerplate. Handlers are keyed by logical table name in ``handlers`` and wired
to ``POST /v1/{url-segment}/export`` in app.py.
"""
from ajna_cloud import make_export_handlers
from src.config.tables import physical, ITEMS

_export = make_export_handlers()

EXPORTABLE_TABLES = (ITEMS,)


def _make_exporter(table: str):
    """Bind the SDK export_table handler to a fixed physical table name."""
    physical_table = physical(table)

    def handler(event, context):
        event = dict(event)
        params = dict(event.get("pathParameters") or {})
        params["table"] = physical_table
        event["pathParameters"] = params
        return _export.export_table(event, context)

    return handler


# logical table name -> bound export handler
handlers = {table: _make_exporter(table) for table in EXPORTABLE_TABLES}
