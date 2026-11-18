"""db-setup's seed (src/seed.py): runs as the seed job (SEED_USER), idempotent, fails loud."""
import pytest

from src import seed


class _Db:
    def __init__(self, rows=None, read_ok=True, upsert_ok=True, tenant_id="acme"):
        self.rows = list(rows or [])
        self.read_ok = read_ok
        self.upsert_ok = upsert_ok
        self.tenant_id = tenant_id
        self.upserts = []

    def query(self, table, filters=None, limit=50, use_cache=True, **kw):
        assert use_cache is False, "a read that gates a write must not use the cache"
        if not self.read_ok:
            return {"success": False, "error": "METADATA_ERROR"}
        return {"success": True, "data": {"records": self.rows}}

    def upsert(self, table, records, filters=None, **kw):
        self.upserts.append((table, records, filters))
        return {"success": self.upsert_ok}


def test_seeds_the_tenant_config_row_when_missing():
    db = _Db()
    seed.seed_defaults(db, {})
    [(table, records, filters)] = db.upserts
    assert table == "app_tenant_config"
    row = records[0]
    assert row["id"] == "tenant-config-acme"          # stable id: a re-run cannot double it
    assert row["tenant_id"] == "acme" and row["company_name"] == "acme"
    assert row["status"] == "active" and row["created_at"]
    assert filters == [{"field": "id", "operator": "in", "value": ["tenant-config-acme"]}]


def test_an_existing_row_is_left_alone():
    db = _Db(rows=[{"tenant_id": "acme", "company_name": "Acme Ltd"}])
    seed.seed_defaults(db, {})
    assert db.upserts == []


@pytest.mark.parametrize("db", [
    _Db(read_ok=False),      # unreadable is not empty: never write blind
    _Db(upsert_ok=False),    # a refused write is a failed seed
    _Db(tenant_id=""),       # the job client always acts for one tenant
])
def test_a_failed_step_fails_the_seed_job(db):
    """Raised, so the one-shot seed job is reported failed and fires again."""
    with pytest.raises(seed.SeedFailed):
        seed.seed_defaults(db, {})


def test_the_seed_never_reads_a_person():
    """The seed job has no context['auth']; seed_fn must not need one."""
    db = _Db()
    seed.seed_defaults(db, {"auth": None})
    assert db.upserts
