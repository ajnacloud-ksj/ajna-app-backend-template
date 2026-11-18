"""The app's declared service users (Ajna Access Design, ajna-app-infra#1554 sections 5-6).

The SDK is token only: every data call acts for one actor, never with a key. A person acts
through their own sign-in. Work that no person starts acts as a SERVICE USER that
``ajna.manifest.json`` (repo root) declares, with its level and its tables. The data service
enforces the REGISTERED manifest (the cockpit reads it from the deployed commit), and
``tests/test_manifest.py`` keeps these names, the manifest and the code in step.

* ``JOB_USER`` (level ``job``): the scheduled jobs (``@scheduled(..., service_user=JOB_USER)``).
  The template's example job is ``src/handlers/housekeeping.py``.
* ``SEED_USER`` (level ``job``): db-setup's seed. In token-only mode the deploy actor writes no
  rows, so the SDK runs ``seed_fn`` as a one-shot job as this user, after each deploy and each
  org added. It may read and upsert only the tables it seeds.
* ``EVENT_USER`` (level ``event``): webhook receivers. Append-only (``WRITE``) on the webhook
  inbox, nothing else (``ajna_cloud.webhook_inbox``).

There is no public service user yet: declare one (level ``public`` plus the manifest's
``public`` section) only when the app serves data without a sign-in.

Add a table to a user only when its code reads or writes that table. Never give a service user
``app_users`` or role tables.
"""

JOB_USER = "app-jobs"
SEED_USER = "app-seed"
EVENT_USER = "app-events"
