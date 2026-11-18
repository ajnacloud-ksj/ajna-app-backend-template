"""The template's example scheduled job: nightly webhook-inbox retention (src/handlers/housekeeping.py)."""
from datetime import datetime, timedelta, timezone

import pytest

from src.handlers import housekeeping

NOW = datetime(2026, 11, 18, 3, 15, tzinfo=timezone.utc)


class _Db:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.tenant_id = "acme"

    def hard_delete(self, table, filters, confirm=False, **kw):
        self.calls.append((table, filters, confirm))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_prunes_only_inbox_rows_older_than_the_retention():
    db = _Db({"success": True, "data": {"deleted": 3}})
    out = housekeeping.prune_inbox(db, now=NOW)
    cutoff = (NOW - timedelta(days=housekeeping.INBOX_RETENTION_DAYS)).isoformat()
    assert db.calls == [("app_webhook_inbox",
                         [{"field": "received_at", "operator": "lt", "value": cutoff}], True)]
    assert out == {"table": "app_webhook_inbox", "cutoff": cutoff, "deleted": 3}


def test_cutoff_compares_with_the_sdk_received_at_format():
    """inbox_row writes received_at as an aware UTC isoformat; a string compare must order it."""
    from ajna_cloud.webhook_inbox import inbox_row

    received = inbox_row("conn12345", "example", "hmac", {}, b"{}")["received_at"]
    cutoff = housekeeping.retention_cutoff(datetime.now(timezone.utc))
    assert received[-6:] == cutoff[-6:] == "+00:00"
    assert cutoff < received


@pytest.mark.parametrize("answer", [
    {"success": False, "error": "AUTH_SCOPE"},
    None,
    RuntimeError("network"),
])
def test_a_refused_delete_fails_the_run(answer):
    """Raised, so the scheduler reports the run failed and the next night retries it."""
    with pytest.raises(RuntimeError):
        housekeeping.prune_inbox(_Db(answer), now=NOW)


def test_worker_uses_the_job_client_from_the_context():
    db = _Db({"success": True, "data": {}})
    out = housekeeping.housekeeping_worker({}, {"db": db})
    assert db.calls and out["deleted"] == 0
