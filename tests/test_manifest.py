"""ajna.manifest.json: valid by the SDK's own validator, rendered for a generated app, and in
step with the code (ajna-app-infra#1554 sections 5, 6 and 13).

The cockpit reads the manifest from the deployed commit and registers it; the data service
enforces only that version. An invalid manifest, or one that drifts from the code, would fail
there. These tests make it fail here instead.
"""
import json
import re

import pytest

from ajna_cloud.manifest import load_manifest, parse_manifest_json

from src.config import service_users as SU
from tests.conftest import (
    APP_NAME_PLACEHOLDER, MANIFEST_FILE, MANIFEST_PATH, REPO_ROOT, TEMPLATE_TEST_APP,
)

SCHEMAS = REPO_ROOT / "src" / "schemas"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# The top-level keys every SDK 4.x accepts. "jobs" is NOT one of them before ajna-cloud 4.3.0:
# an older SDK refuses an unknown top-level key, so the app would not start.
_SDK4_TOP_KEYS = {"app", "version", "service_users", "public", "platform_ops"}


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(MANIFEST_PATH, required=True)


def _raw() -> dict:
    return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))


def _schema_fields(table: str) -> set:
    data = json.loads((SCHEMAS / f"{table[len('app_'):]}.json").read_text(encoding="utf-8"))
    return set(data["fields"])


# ── the file and its placeholder ──────────────────────────────────────────────

def test_app_is_the_placeholder_or_a_slug():
    """Template: the cockpit's repo seed renders "{{app-name}}" (ajna-app-infra github_seed.py,
    every .json file). Generated app: the app's own slug, which the cockpit checks against the
    app it installs."""
    app = _raw()["app"]
    assert app == APP_NAME_PLACEHOLDER or _SLUG.fullmatch(app), app


def test_the_placeholder_renders_to_a_valid_manifest():
    text = MANIFEST_FILE.read_text(encoding="utf-8")
    rendered = parse_manifest_json(text.replace(APP_NAME_PLACEHOLDER, TEMPLATE_TEST_APP))
    if APP_NAME_PLACEHOLDER in text:
        assert rendered.app == TEMPLATE_TEST_APP


def test_tests_read_the_one_manifest(manifest):
    """The test copy is the real file with only the placeholder rendered: one source."""
    text = MANIFEST_FILE.read_text(encoding="utf-8")
    expected = parse_manifest_json(text.replace(APP_NAME_PLACEHOLDER, TEMPLATE_TEST_APP))
    assert manifest.digest() == expected.digest()


def test_only_keys_every_sdk4_accepts():
    """No "jobs" key until the SDK 4.3.0 bump (docs/MANIFEST_JOBS.md in ajna-cloud-sdk)."""
    assert set(_raw()) <= _SDK4_TOP_KEYS


def test_the_image_ships_it_next_to_the_handler():
    """The SDK reads ./ajna.manifest.json; Lambda's cwd is /var/task (LAMBDA_TASK_ROOT)."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY ajna.manifest.json ${LAMBDA_TASK_ROOT}/ajna.manifest.json" in dockerfile


# ── service users ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,level", [
    (SU.JOB_USER, "job"), (SU.SEED_USER, "job"), (SU.EVENT_USER, "event"),
])
def test_every_service_user_the_code_names_is_declared(manifest, name, level):
    user = manifest.service_user(name)
    assert user is not None and user.level == level


def test_no_other_users_and_no_public_user(manifest):
    assert {u.name for u in manifest.service_users} == {SU.JOB_USER, SU.SEED_USER, SU.EVENT_USER}
    assert not manifest.public
    assert not manifest.platform_ops


def test_every_declared_table_is_a_table_db_setup_creates(manifest):
    from src.config.tables import ESSENTIAL_TABLES

    essential = {f"app_{t}" for t in ESSENTIAL_TABLES}
    tables = {t for u in manifest.service_users for t in u.tables}
    assert tables <= essential, sorted(tables - essential)


def test_grants_stay_minimal(manifest):
    from ajna_cloud.webhook_inbox import INBOX_TABLE
    from src.config.tables import TENANT_CONFIG_TABLE, WEBHOOK_INBOX_TABLE

    assert WEBHOOK_INBOX_TABLE == INBOX_TABLE
    jobs = manifest.service_user(SU.JOB_USER)
    seed = manifest.service_user(SU.SEED_USER)
    event = manifest.service_user(SU.EVENT_USER)
    # The housekeeping job: reads and prunes the webhook inbox only.
    assert jobs.tables == (INBOX_TABLE,) and jobs.hard_delete == (INBOX_TABLE,)
    assert jobs.ops == ("QUERY",)
    # The seed: reads and upserts the tenant config row only; never deletes.
    assert seed.tables == (TENANT_CONFIG_TABLE,)
    assert set(seed.ops) == {"QUERY", "UPSERT"} and seed.hard_delete == ()
    # The event user: append-only on the inbox.
    assert event.tables == (INBOX_TABLE,) and event.ops == ("WRITE",)
    for user in manifest.service_users:
        assert "app_users" not in user.tables, user.name


def test_the_inbox_schema_holds_every_column_the_sdk_writes():
    from ajna_cloud.webhook_inbox import inbox_row

    row = inbox_row("conn12345", "example", "hmac", {}, b"{}")
    assert set(row) == _schema_fields("app_webhook_inbox")


# ── the code runs as the declared users ───────────────────────────────────────

def test_scheduled_jobs_run_as_the_job_user():
    import src.app  # noqa: F401 - registers the @scheduled jobs
    from ajna_cloud import app as A
    from src.handlers import housekeeping

    intents = {i["name"]: i for i in A._scheduled_intents}
    assert intents[housekeeping.HOUSEKEEPING_JOB]["opts"]["service_user"] == SU.JOB_USER
    for intent in A._scheduled_intents:
        assert intent["opts"].get("service_user"), intent["name"]


def test_the_seed_runs_as_the_seed_user():
    import src.app as app_module

    assert app_module._db_admin.seed_fn is not None
    assert app_module._db_admin.seed_service_user == SU.SEED_USER


def test_an_undeclared_user_is_refused_at_import():
    """The SDK checks a job's service user against this manifest when the module is imported."""
    from ajna_cloud.scheduler import check_service_user

    with pytest.raises(ValueError):
        check_service_user("not-declared", target="self", job="x")
    with pytest.raises(ValueError):
        check_service_user(SU.EVENT_USER, target="self", job="x")   # an event user is no job
    assert check_service_user(SU.JOB_USER, target="self", job="x") == SU.JOB_USER
