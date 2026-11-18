"""Nightly housekeeping: the template's example ``@scheduled`` job. Replace or extend it.

It runs once a day per org, as the declared job service user ``JOB_USER`` (``ajna.manifest.json``,
level ``job``). The SDK is token only: the scheduler gives each run a job grant, and
``context['db']`` acts as that job for the run's org. There is no person and no key.

What it does: it hard-deletes webhook-inbox rows (``app_webhook_inbox``, written append-only by
the ``EVENT_USER`` through ``ajna_cloud.webhook_inbox``) that are older than
``INBOX_RETENTION_DAYS``. The manifest grants exactly that: ``hard_delete`` on that one table.
With no webhook receiver yet, the table is empty and the run is one filtered delete.

If your app processes inbox rows (a drain job), delete only processed rows here, or move this
retention into the drain (see plant-manager-backend ``src/handlers/webhook_inbox_drain.py``).

To add a job: write a function ``(event, context) -> dict``, decorate it with
``@scheduled(<5-field UTC cron>, name=<job name>, service_user=JOB_USER)``, import its module in
``src/app.py``, and add the tables it uses to the job user in ``ajna.manifest.json``.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from ajna_cloud.app import scheduled
from ajna_cloud.logger import logger

from src.config.service_users import JOB_USER
from src.config.tables import WEBHOOK_INBOX_TABLE

HOUSEKEEPING_JOB = "nightly-housekeeping"
#: 03:15 UTC every day.
HOUSEKEEPING_CRON = "15 3 * * *"
INBOX_RETENTION_DAYS = 30


def retention_cutoff(now: datetime) -> str:
    """The oldest ``received_at`` that is kept. Same text format as the SDK writes
    (``datetime.now(timezone.utc).isoformat()``), so the string compare orders correctly."""
    return (now.astimezone(timezone.utc) - timedelta(days=INBOX_RETENTION_DAYS)).isoformat()


def prune_inbox(db: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Hard-delete inbox rows received before the cutoff. RAISES when the delete is refused or
    fails, so the scheduler reports the run failed and the next run retries it."""
    cutoff = retention_cutoff(now or datetime.now(timezone.utc))
    filters = [{"field": "received_at", "operator": "lt", "value": cutoff}]
    try:
        result = db.hard_delete(WEBHOOK_INBOX_TABLE, filters=filters, confirm=True)
    except Exception as exc:  # noqa: BLE001 - re-raised with the type only, never the detail
        raise RuntimeError(f"webhook inbox retention failed ({type(exc).__name__})") from None
    if not (isinstance(result, dict) and result.get("success") is True):
        code = (result or {}).get("error") if isinstance(result, dict) else None
        raise RuntimeError(f"webhook inbox retention refused ({code or 'no answer'})")
    deleted = int(((result.get("data") or {}).get("deleted")) or 0)
    logger.info(f"housekeeping: pruned {deleted} webhook inbox row(s) received before {cutoff}")
    return {"table": WEBHOOK_INBOX_TABLE, "cutoff": cutoff, "deleted": deleted}


@scheduled(HOUSEKEEPING_CRON, name=HOUSEKEEPING_JOB, service_user=JOB_USER)
def housekeeping_worker(event: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """The scheduled entry point. ``context['db']`` acts as the job for the run's org."""
    return prune_inbox(context["db"])
