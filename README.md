# {{app-name}} — Backend

Python Lambda backend (FastAPI shim for local dev) for the **{{app-name}}** app on the
Ajna platform. Data is stored in IbexDB via the `ajna-cloud-sdk`; auth is AWS Cognito.

The local stack runs the **real Lambda handler** (`src/app.py`) wrapped by a FastAPI
hot-reload server, plus the UI, both in Docker.

---

## Prerequisites

- **Docker Desktop** (or OrbStack) running.
- **ajna-cloud-sdk** cloned (the local stack installs it editable):
  ```bash
  git clone git@github.com:ajnacloud-ksj/ajna-cloud-sdk.git ~/ajna/ibex/ajna-cloud-sdk
  ```
  `dev.sh` auto-detects it at `~/ajna/ibex/ajna-cloud-sdk` or `../ajna-cloud-sdk`
  (override with `AJNA_SDK_PATH`).
- The **UI repo** cloned as a sibling directory:
  ```bash
  git clone git@github.com:{{github-org}}/{{app-name}}-ui.git ../{{app-name}}-ui
  ```

Expected layout:
```
parent/
├── {{app-name}}-backend/   ← this repo (run dev.sh from here)
├── {{app-name}}-ui/        ← UI (sibling)
└── ../ajna-cloud-sdk    or  ~/ajna/ibex/ajna-cloud-sdk
```

---

## Quick start

```bash
# 1. From this directory:
cp .env.example .env
#    Edit .env and set the Cognito values for your app. There is NO IbexDB key: the SDK
#    (ajna-cloud 4.x) is token only (see "Data access: token only" below).

# 2. Start the full stack (backend + UI, hot-reload):
./dev.sh start
```

`dev.sh` picks the first free ports (defaults backend `8000`, UI `5173`), prints them,
and on first start runs the database setup automatically:

```
Backend  →  http://localhost:8000
UI       →  http://localhost:5173
API docs →  http://localhost:8000/docs
```

Sign in at the UI with your own dev Cognito user. Get the login from the team
password manager, or ask an admin to create a user for you in the dev Cognito pool.
Never commit a login to this repo.

| User | Password | Role |
|------|----------|------|
| `<your-dev-email>` | `<your-dev-password>` | super_admin (or the role you need) |

### Commands

```bash
./dev.sh setup               # first-time guided setup (.env files, SDK check)
./dev.sh status              # running containers + ports
./dev.sh logs [backend|ui]   # tail logs
./dev.sh restart backend     # rebuild + restart one service
./dev.sh stop                # stop everything
./dev.sh db-setup            # (re)create tables — idempotent
```

---

## Do I need AWS credentials?

**No — not for normal local development.** Login and all data CRUD work with **no AWS
credentials**:

- **Login** uses Cognito `initiate_auth` (USER_PASSWORD_AUTH), an *unsigned* API.
- **Token verification** fetches Cognito's public JWKS over HTTPS and verifies locally.
- **Data CRUD** goes to IbexDB over HTTPS with a short session token per actor, never a key
  (see "Data access: token only" below).

The **only** features that need AWS credentials are the **User Management** admin screens
(create / list / disable users), which call signed Cognito `admin_*` APIs. If you use those,
configure dev-account credentials in `~/.aws` (the local stack mounts it read-only).

---

## Choosing a tenant

Which tenant's data the app reads/writes is resolved per request in this order:

1. `X-Tenant-ID` request header (super_admin acting on behalf of a tenant), then
2. the logged-in user's Cognito group (`{{app-name}}-{tenant}-{role}`), then
3. the `TENANT_ID` env var (fallback).

To scope local dev to one tenant, set `TENANT_ID` in `.env` and restart. The app does not
create tenants: `POST /v1/admin/tenants` returns 410. Add a customer in the cockpit
(Organizations -> add org to app). The cockpit creates the org and the tenant, then
provisions this app. The deploy-time db-setup creates the tables and the roles of every org.

---

## Data access: token only

The SDK (ajna-cloud 4.x) sends no IbexDB key. Each data call carries a short session token for
ONE actor, issued by the data service against the app's AWS workload proof:

| Actor | Who | Where in this repo |
|-------|-----|--------------------|
| A person | the signed-in user (their roles apply) | every route |
| The deploy actor | the backend build: db-setup (tables, role catalog) | `make_database_admin_handlers` in `src/app.py` |
| `app-seed` (job) | db-setup's seed, a one-shot job after each deploy and each org added | `src/seed.py` |
| `app-jobs` (job) | scheduled jobs | `src/handlers/housekeeping.py` (the example to replace) |
| `app-events` (event) | webhook receivers: append-only on `app_webhook_inbox` | none yet (`ajna_cloud.webhook_inbox`) |

Service users are declared in `ajna.manifest.json` (repo root, shipped in the image). The cockpit
registers the version at the deployed commit; the data service enforces only that version. A
service user gets ONLY the tables listed for it. When you add a job or a seed step, add its
tables to its user in the manifest. `tests/test_manifest.py` checks the manifest with the SDK's
own validator. The manifest says `"app": "{{app-name}}"` in the template: the cockpit's repo seed
replaces it with the app's name, and the template's own tests render a temporary copy
(`tests/conftest.py`).

Per-app data area (`AJNA_DATA_AREA=per-app`): the app's tables live in its own namespace, and its
roles are stored app-scoped (`<app>.admin`, `<app>.user`). The code keeps bare role ids;
`super_admin` stays org-wide.

**Local dev:** the local IbexDB stack cannot issue a token to a laptop yet (it needs the app's
AWS role), so data calls from `./dev.sh start` are refused (`AUTH_PROOF_UNAVAILABLE` or
`AUTH_ACTOR_REQUIRED`). Test data behaviour with the unit tests, and end to end on the deployed
dev app.

---

## Project structure

```
src/
├── app.py                  # Lambda entry point + route table
├── seed.py                 # db-setup's seed (runs as the app-seed job)
├── config/
│   ├── roles.py            # RBAC role constants (super_admin / admin / user)
│   ├── service_users.py    # service user names declared in ajna.manifest.json
│   ├── settings.py         # App-specific config (env-driven)
│   └── tables.py           # Single source of truth for IbexDB table names
├── lib/
│   ├── logger.py           # Structured logging helper
│   └── sanitize.py         # Input sanitisation helpers
├── handlers/
│   ├── health.py           # /health, /ready, /status
│   ├── auth.py             # login / me / permissions
│   ├── admin.py            # tenant read/update + RBAC management, DEFAULT_ROLES
│   ├── housekeeping.py     # EXAMPLE @scheduled job (webhook inbox retention)
│   ├── users.py            # tenant-scoped user management + sync
│   ├── audit.py            # changelog + record history
│   ├── field_config.py     # per-tenant custom fields
│   ├── storage.py          # S3 upload/download presigned URLs
│   ├── items.py            # EXAMPLE rich entity — rich query handler
│   ├── exports.py          # CSV/Excel export registry
│   └── imports.py          # CSV/Excel import registry
└── schemas/
    ├── items.json          # EXAMPLE entity schema — copy & rename for your domain
    ├── users.json
    ├── tenant_config.json
    ├── tenant_field_config.json
    └── webhook_inbox.json  # append-only webhook deliveries (event user)
tests/
Dockerfile                  # Production ARM64 Lambda image
Dockerfile.local            # Local dev with hot-reload
docker-compose.local.yml    # Local stack (backend + sibling UI)
dev.sh                      # Start/stop/logs helper
```

`items` is the worked example of a "rich" domain entity: schema-validated CRUD (via the
SDK CRUD factory), a dedicated rich query endpoint (`POST /v1/items/query`), and
CSV/Excel export/import. Copy `items` to add your own entities — see the workspace
README one level up for the full add-an-entity cycle.

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `IBEX_API_URL` | IbexDB cluster URL |
| `TENANT_ID` | Default/fallback tenant slug |
| `DB_NAMESPACE` | IbexDB namespace (`default`); in per-app mode the SDK uses the app namespace instead |
| `AJNA_DATA_AREA` | `per-app` — tenant data in `{tenant}_{app namespace}` (the default for new apps, same as the deployed app) |
| `APP_NAME` | `{{app-name}}` — the cockpit app name; gives the per-app namespace |
| `AUTH_MODE` | `cognito` |
| `COGNITO_USER_POOL_ID` / `COGNITO_CLIENT_ID` / `COGNITO_REGION` | Cognito pool |
| `APP_PREFIX` | `{{app-name}}` — resolves tenant from a user's Cognito group |
| `IBEX_RBAC_ENABLED` / `IBEX_AUDIT_ENABLED` | RBAC + audit logging |

> **Never commit `.env`.** `.env.example` holds non-secret placeholders only.

---

## Deploying

Push to `main` (prod) or `develop` (dev) — GitHub Actions builds the ARM64 Docker image,
pushes to ECR, and updates the Lambda. Configure the repo's environment **Variables**
(`AWS_REGION`, `LAMBDA_FUNCTION_NAME`, `LAMBDA_ROLE_ARN`, `COGNITO_*`, `S3_PATH`, etc.)
and bump `sdk-version` in `.github/workflows/deploy-backend.yml` to upgrade the SDK.

---

## Troubleshooting

- **Port already in use** — `dev.sh` auto-shifts to the next free port; check the printed URLs.
- **SDK not found** — clone it (see Prerequisites) or set `AJNA_SDK_PATH`.
- **401 on data calls** — sign in first; the dev stack uses real Cognito auth.
- **CORS errors** — leave `CORS_ALLOWED_ORIGINS` unset locally; the SDK reflects the UI origin.
