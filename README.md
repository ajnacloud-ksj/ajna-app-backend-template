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
#    Edit .env and set IBEX_API_KEY (+ Cognito values) for your app.
#    Generate these from Cockpit → app → Local Dev Setup (https://cockpit.triviz.cloud).

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

Sign in at the UI with a dev Cognito user:

| User | Password | Role |
|------|----------|------|
| `dev@ajna.cloud` | `$AjnaDev@2026$` | super_admin |

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
- **Data CRUD** goes to IbexDB over HTTPS using `IBEX_API_KEY`.

The **only** features that need AWS credentials are the **User Management** admin screens
(create / list / disable users), which call signed Cognito `admin_*` APIs. If you use those,
configure dev-account credentials in `~/.aws` (the local stack mounts it read-only).

---

## Choosing a tenant

The dev `IBEX_API_KEY` is app-scoped and works for **any** {{app-name}} tenant. Which
tenant's data the app reads/writes is resolved per request in this order:

1. `X-Tenant-ID` request header (super_admin acting on behalf of a tenant), then
2. the logged-in user's Cognito group (`{{app-name}}-{tenant}-{role}`), then
3. the `TENANT_ID` env var (fallback).

To scope local dev to one tenant, set `TENANT_ID` in `.env` and restart. Onboard new
tenants with `scripts/onboard_tenant.sh` (creates Cognito groups + admin user + IbexDB RBAC).

---

## Project structure

```
src/
├── app.py                  # Lambda entry point + route table
├── config/
│   ├── roles.py            # RBAC role constants (super_admin / admin / user)
│   ├── settings.py         # App-specific config (env-driven)
│   └── tables.py           # Single source of truth for IbexDB table names
├── lib/
│   ├── logger.py           # Structured logging helper
│   └── sanitize.py         # Input sanitisation helpers
├── handlers/
│   ├── health.py           # /health, /ready, /status
│   ├── auth.py             # login / me / permissions
│   ├── admin.py            # tenant & RBAC management
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
    └── tenant_field_config.json
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
| `IBEX_API_KEY` | App-level dev key (works for all tenants of this app) |
| `TENANT_ID` | Default/fallback tenant slug |
| `DB_NAMESPACE` | IbexDB namespace (`default`) |
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
