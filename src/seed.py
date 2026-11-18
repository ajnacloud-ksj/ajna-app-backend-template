"""db-setup's seed: the default rows every org of this app starts with. Extend it for your app.

Token only (SDK 4): db-setup runs as the DEPLOY actor, which may create tables but write no rows.
So the SDK runs ``seed_defaults`` as a one-shot job, as the declared seed service user
``SEED_USER`` (``ajna.manifest.json``), after each deploy and each org added. Its client acts for
that one org; there is no person (no ``context['auth']``) and no key.

Rules for every seed step:

* idempotent: db-setup runs on every deploy, so a step reads first and writes only what is
  missing, with a STABLE id (an upsert keyed on ``id``), so a re-run or a race never doubles a row;
* fail loud: an unreadable table is not an empty one, and a refused write is a failure. Raise
  ``SeedFailed``: the seed job is then reported failed and fires again;
* only the tables the seed user declares in the manifest (today: ``app_tenant_config``).
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ajna_cloud.logger import logger

from src.config.tables import TENANT_CONFIG_TABLE


class SeedFailed(RuntimeError):
    """A seed step did not land. Raised so the seed JOB is reported failed and runs again."""


def _records(result: Any) -> Optional[List[Dict[str, Any]]]:
    """The rows of a read, or None when the read did not succeed."""
    if not (isinstance(result, dict) and result.get("success") is True):
        return None
    return list((result.get("data") or {}).get("records") or [])


def _upsert_by_id(db: Any, table: str, rows: List[Dict[str, Any]]) -> None:
    """Insert ``rows`` keyed on ``id``: an existing id is merged, never doubled."""
    ids = [r["id"] for r in rows]
    result = db.upsert(table, rows, filters=[{"field": "id", "operator": "in", "value": ids}])
    if not (isinstance(result, dict) and result.get("success") is True):
        raise SeedFailed(f"upsert into {table} was refused")


def _seed_tenant_config(db: Any, tenant_id: str, now: str) -> None:
    """The org's own ``app_tenant_config`` row (company name, status), if it has none."""
    existing = _records(db.query(
        TENANT_CONFIG_TABLE,
        filters=[{"field": "tenant_id", "operator": "eq", "value": tenant_id}],
        limit=1, use_cache=False))
    if existing is None:
        raise SeedFailed(f"{TENANT_CONFIG_TABLE} could not be read")
    if existing:
        return
    _upsert_by_id(db, TENANT_CONFIG_TABLE, [{
        "id": f"tenant-config-{tenant_id}",
        "tenant_id": tenant_id,
        "company_name": tenant_id,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }])
    logger.info(f"seed: created the tenant config row for {tenant_id}")


def seed_defaults(db: Any, context: Dict[str, Any]) -> None:
    """``seed_fn`` for ``make_database_admin_handlers``: runs as the seed job."""
    tenant_id = str(getattr(db, "tenant_id", "") or "").strip()
    if not tenant_id:
        raise SeedFailed("the seed job client has no tenant")
    now = datetime.now(timezone.utc).isoformat()
    _seed_tenant_config(db, tenant_id, now)
