#!/usr/bin/env bash
# dev.sh — Local development helper for an Ajna app (GENERIC: derives the app name from the folder)
#
# Run from inside {app}-backend/ (this repo):
#   ./dev.sh setup                  — first-time setup (copy .env, check SDK + UI repo)
#   ./dev.sh start   [backend|ui]   — build & start (all services or one)
#   ./dev.sh stop    [backend|ui]   — stop (all or one)
#   ./dev.sh restart [backend|ui]   — stop + start
#   ./dev.sh logs    [backend|ui]   — tail logs (all or one)
#   ./dev.sh status                 — show running containers + ports
#   ./dev.sh build   [backend|ui]   — rebuild image(s) without starting

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Derive a stable project name from the backend folder (strips -backend suffix)
PROJECT_NAME="$(basename "$SCRIPT_DIR" | sed 's/-backend$//')"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.local.yml"
PORTS_FILE="$SCRIPT_DIR/.dev_ports"
# Marker that db-setup has run. Survives 'stop' (unlike .dev_ports) so setup runs once,
# not on every restart. Removed by 'reset-db' to force a fresh setup.
SETUP_MARKER="$SCRIPT_DIR/.db_setup_done"
# .env lives alongside dev.sh inside {app}-backend/
BACKEND_ENV="$SCRIPT_DIR/.env"
BACKEND_ENV_EXAMPLE="$SCRIPT_DIR/.env.example"
# UI repo is expected as a sibling directory
UI_DIR="$SCRIPT_DIR/../${PROJECT_NAME}-ui"
# Derived from the app name (PROJECT_NAME strips -backend) → the "{app}-plugins" convention,
# so this stays generic across apps (no hard-coded app name). Override PLUGINS_DIR to relocate.
PLUGINS_DIR="${PLUGINS_DIR:-$SCRIPT_DIR/../${PROJECT_NAME}-plugins}"
UI_ENV="$UI_DIR/.env"
UI_ENV_EXAMPLE="$UI_DIR/.env.example"

# ── Sibling-repo base directory ───────────────────────────────────────────────
# ALWAYS resolved relative to THIS backend — no dependency on a ~/ajna folder, so a new
# developer can clone {app}-backend anywhere and it just works. Layout:
#   <root>/ibex/                              ← SDK + IbexDB stack (auto-cloned here)
#   <root>/<workspace>/{app}-backend  ← this repo (dev.sh runs here)
#   <root>/india_qr_code_ibex/${PROJECT_NAME}-ui
# SCRIPT_DIR is .../<workspace>/{app}-backend, so ../../ is <root>.
# Override with the IBEX_BASE env var only if you keep the ibex repos elsewhere.
_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IBEX_BASE="${IBEX_BASE:-$_REPO_ROOT/ibex}"

# SDK path resolution (checked in order):
#   1. AJNA_SDK_PATH env var (explicit override)
#   2. $IBEX_BASE/ajna-cloud-sdk   (standard team clone location)
#   3. ../ajna-cloud-sdk           (sibling directory of this repo)
if [ -z "${AJNA_SDK_PATH:-}" ]; then
  if [ -d "$IBEX_BASE/ajna-cloud-sdk" ]; then
    AJNA_SDK_PATH="$IBEX_BASE/ajna-cloud-sdk"
  elif [ -d "$SCRIPT_DIR/../ajna-cloud-sdk" ]; then
    AJNA_SDK_PATH="$(cd "$SCRIPT_DIR/../ajna-cloud-sdk" && pwd)"
  else
    AJNA_SDK_PATH="$IBEX_BASE/ajna-cloud-sdk"  # show this path in error message
  fi
fi

# Read the FastAPI host port directly from ibex-db-lambda's compose file (e.g. "9000:8000" → 9000)
# Falls back to 9000 if the compose file is absent or the pattern isn't found.
_ibex_port() {
  grep -A5 'container_name: ibex-local-fastapi' "$IBEX_COMPOSE_FILE" 2>/dev/null \
    | grep -o '"[0-9]*:8000"' | head -1 | tr -d '"' | cut -d: -f1
}

# Read the local IbexDB admin key from ibex-db-lambda's compose (IBEX_ADMIN_KEY).
# The local stack authenticates against THIS key — NOT the dev-cluster developer key
# baked into .env.example. So when dev.sh points the backend at the local stack it must
# swap the key too, else the local IbexDB rejects every request with 401. Falls back to
# the known local default if the compose file/pattern is absent.
_ibex_key() {
  grep -E '^[[:space:]]*IBEX_ADMIN_KEY:' "$IBEX_COMPOSE_FILE" 2>/dev/null \
    | head -1 | sed -E 's/.*IBEX_ADMIN_KEY:[[:space:]]*//; s/[[:space:]]*$//' | tr -d '"'
}

# IbexDB local stack path resolution:  env var override → derived path → empty.
# Defined as a function so it can be re-run after an auto-clone makes the repo appear.
# When present, IbexDB runs locally (MinIO + Iceberg + FastAPI) for zero-latency dev.
resolve_ibex_paths() {
  if [ -n "${IBEX_LAMBDA_PATH:-}" ]; then
    :  # explicit override — keep as set
  elif [ -d "$IBEX_BASE/ibex-db-lambda" ]; then
    IBEX_LAMBDA_PATH="$IBEX_BASE/ibex-db-lambda"
  else
    IBEX_LAMBDA_PATH=""
  fi
  IBEX_COMPOSE_FILE="${IBEX_LAMBDA_PATH}/docker-compose.local.yml"
  local p
  p=$( [ -f "$IBEX_COMPOSE_FILE" ] && _ibex_port || true )
  # IBEX_LOCAL_URL: used by dev.sh itself (health checks from the host)
  IBEX_LOCAL_URL="http://localhost:${p:-9000}"
  # IBEX_CONTAINER_URL: used inside the backend container to reach the ibex stack on the host
  IBEX_CONTAINER_URL="http://host.docker.internal:${p:-9000}"
  # IBEX_LOCAL_KEY: the local stack's admin key, swapped into .env alongside the URL.
  IBEX_LOCAL_KEY="$( [ -f "$IBEX_COMPOSE_FILE" ] && _ibex_key || true )"
  IBEX_LOCAL_KEY="${IBEX_LOCAL_KEY:-ibx_local_admin_dev}"
}
resolve_ibex_paths

# ── Per-repo tracking branches ────────────────────────────────────────────────
# NOTE: ibex-policy and ibex-query-engine-lib are main-only (no develop branch).
# Override any of these via env vars before running dev.sh.
SDK_BRANCH="${SDK_BRANCH:-main}"
IBEX_DB_BRANCH="${IBEX_DB_BRANCH:-main}"
IBEX_POLICY_BRANCH="${IBEX_POLICY_BRANCH:-main}"
IBEX_QE_BRANCH="${IBEX_QE_BRANCH:-main}"
UI_BRANCH="${UI_BRANCH:-develop}"
PLUGINS_BRANCH="${PLUGINS_BRANCH:-main}"
SELF_BRANCH="${SELF_BRANCH:-develop}"

# Repos required for the local IbexDB stack — auto-cloned when missing.
# Each entry: "<local-path>|<git-remote>|<branch>". ibex-policy and
# ibex-query-engine-lib are bind-mounted by ibex-db-lambda's compose file.
IBEX_REPOS=(
  "$IBEX_BASE/ibex-db-lambda|git@github.com:ajnacloud-ksj/ibex-db-lambda.git|$IBEX_DB_BRANCH"
  "$IBEX_BASE/ibex-policy|git@github.com:ajnacloud-ksj/ibex-policy-lib.git|$IBEX_POLICY_BRANCH"
  "$IBEX_BASE/ibex-query-engine-lib|git@github.com:ajnacloud-ksj/ibex-query-engine-lib.git|$IBEX_QE_BRANCH"
)

# App repos needed regardless of DB mode — auto-cloned on every 'start':
#   SDK is bind-mounted into the backend (editable install); UI is its own service.
APP_REPOS=(
  "$AJNA_SDK_PATH|git@github.com:ajnacloud-ksj/ajna-cloud-sdk.git|$SDK_BRANCH"
  "$UI_DIR|git@github.com:ajnacloud-ksj/${PROJECT_NAME}-ui.git|$UI_BRANCH"
  # Per-app tenant-plugins repo ({app}-plugins, HTTPS, derived from PROJECT_NAME → generic).
  # Bind-mounted into the backend as /app/local-plugins for hot-reloaded local dev;
  # edit here → commit → CI publishes to /v1/plugins.
  "$PLUGINS_DIR|https://github.com/ajnacloud-ksj/${PROJECT_NAME}-plugins.git|$PLUGINS_BRANCH"
)

# Everything './dev.sh setup' clones, so a fresh machine bootstraps in one command.
SETUP_REPOS=(
  "${IBEX_REPOS[@]}"
  "${APP_REPOS[@]}"
)

# Repos that './dev.sh pull' / 'update' refresh — the setup set plus this repo itself.
PULL_REPOS=(
  "${SETUP_REPOS[@]}"
  "$SCRIPT_DIR|git@github.com:ajnacloud-ksj/${PROJECT_NAME}-backend.git|$SELF_BRANCH"
)

# Default preferred ports (will find next free one if taken)
DEFAULT_BACKEND=8000
DEFAULT_UI=5173

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[dev]${NC} $*"; }
warn()    { echo -e "${YELLOW}[dev]${NC} $*"; }
error()   { echo -e "${RED}[dev]${NC} $*" >&2; }
section() { echo -e "\n${CYAN}── $* ──${NC}"; }

# ── Port detection ────────────────────────────────────────────────────────────
find_free_port() {
  local port=$1
  while lsof -iTCP:"$port" -sTCP:LISTEN -t &>/dev/null 2>&1; do
    port=$((port + 1))
  done
  echo "$port"
}

# Deterministic per-app port offset (0-99) derived from the app name. Two different apps get
# different offsets, so they run SIDE BY SIDE without colliding; the SAME app always gets the same
# ports, so each app's URLs stay consistent across runs. (cksum is POSIX — same on macOS + Linux.)
_app_port_offset() {
  local h; h=$(printf '%s' "$PROJECT_NAME" | cksum | cut -d' ' -f1)
  echo $(( h % 100 ))
}

resolve_ports() {
  # Fixed, predictable ports — no auto-shifting. The team wants consistent URLs
  # (backend :8000, UI :5173) every run. dev.sh recreates its OWN containers on these
  # ports without conflict (same compose project). If a FOREIGN process holds one, warn
  # clearly rather than silently shifting (which previously persisted into .dev_ports).
  # Override with PORT_BACKEND_OVERRIDE / PORT_UI_OVERRIDE if you truly need to.
  local off; off=$(_app_port_offset)
  PORT_BACKEND=${PORT_BACKEND_OVERRIDE:-$(( DEFAULT_BACKEND + off ))}
  PORT_UI=${PORT_UI_OVERRIDE:-$(( DEFAULT_UI + off ))}

  for pair in "backend:$PORT_BACKEND" "UI:$PORT_UI"; do
    local nm=${pair%%:*} pt=${pair##*:}
    if lsof -iTCP:"$pt" -sTCP:LISTEN -t &>/dev/null 2>&1 \
       && ! docker ps --format '{{.Ports}}' 2>/dev/null | grep -q ":$pt->"; then
      warn "Port $pt ($nm) is held by a non-dev.sh process — free it (or set PORT_BACKEND_OVERRIDE / PORT_UI_OVERRIDE)."
    fi
  done

  cat > "$PORTS_FILE" <<EOF
PORT_BACKEND=$PORT_BACKEND
PORT_UI=$PORT_UI
EOF
}

load_ports() {
  if [ -f "$PORTS_FILE" ]; then
    # shellcheck source=/dev/null
    source "$PORTS_FILE"
  else
    PORT_BACKEND=$DEFAULT_BACKEND
    PORT_UI=$DEFAULT_UI
  fi
}

# Free dev.sh's published ports from leftover/stale containers before bringing
# services up. After a crashed run or a wedged OrbStack/Docker daemon, an old
# container can keep a port reserved, so `docker compose up` fails with
# "Bind for :::8000 failed: port is already allocated". We remove our own and
# any *stale* (non-running) container holding the port (volumes/data untouched);
# a RUNNING container from another compose project is reported by name, not killed.
preflight_free_ports() {
  command -v docker &>/dev/null || return 0
  local pair nm pt cid cname cstate cproj nm_uc
  for pair in "backend:$PORT_BACKEND" "UI:$PORT_UI"; do
    nm=${pair%%:*}; pt=${pair##*:}
    # Uppercase via tr (NOT ${nm^^}) — macOS ships bash 3.2 where ^^ is a "bad substitution".
    nm_uc=$(printf '%s' "$nm" | tr '[:lower:]' '[:upper:]')
    for cid in $(docker ps -aq --filter "publish=${pt}" 2>/dev/null); do
      cname=$(docker inspect -f '{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##')
      cstate=$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null)
      cproj=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$cid" 2>/dev/null)
      if [ "$cproj" = "$PROJECT_NAME" ] || [ "$cstate" != "running" ]; then
        warn "Freeing port ${pt} (${nm}): removing ${cstate:-stale} container '${cname:-$cid}'"
        docker rm -f "$cid" &>/dev/null || true
      else
        warn "Port ${pt} (${nm}) is held by RUNNING container '${cname}' (compose project '${cproj:-none}')."
        warn "  → stop it:  docker stop ${cname}    — or set PORT_${nm_uc}_OVERRIDE to use a different port."
      fi
    done
  done
}

# ── Helpers ───────────────────────────────────────────────────────────────────
check_docker() {
  if ! command -v docker &>/dev/null; then
    error "Docker not found. Install Docker Desktop: https://docs.docker.com/get-docker/"
    exit 1
  fi
  # Liveness check via `docker ps` (lighter than `docker info`, which can hang for
  # minutes on a stalled OrbStack/Docker Desktop). Wrap it in a timeout WHEN one is
  # available — stock macOS has neither `timeout` nor `gtimeout` (they're GNU
  # coreutils), so we must NOT hard-depend on them: otherwise the check would
  # falsely report "daemon not responding" on every machine without coreutils.
  local _to=""
  if command -v timeout &>/dev/null; then _to="timeout 20"
  elif command -v gtimeout &>/dev/null; then _to="gtimeout 20"; fi
  if ! $_to docker ps &>/dev/null; then
    error "Docker daemon not responding. Start/restart OrbStack (or Docker Desktop) and retry."
    exit 1
  fi
}

# Log Docker into ghcr.io so the PRIVATE ajna-lambda-base image can be pulled for the
# local build. The base is pushed to both ECR (deploy) and ghcr.io (local-dev,
# GitHub-token auth); docker-compose.local.yml pulls the ghcr mirror (build.target: dev). Idempotent + best-effort:
# if you can already pull (already logged in), it does nothing. Image ref is read from
# the compose BASE_IMAGE arg so this stays correct across tag bumps (and no-ops if you move off ghcr).
ensure_ghcr_login() {
  local img
  img="$(awk '/BASE_IMAGE:[[:space:]]*ghcr\.io/{print $2; exit}' "$SCRIPT_DIR/docker-compose.local.yml" 2>/dev/null)"
  [ -n "$img" ] || return 0                                   # local base isn't on ghcr → nothing to do
  docker manifest inspect "$img" &>/dev/null && return 0      # already pullable → already authed
  if command -v gh &>/dev/null; then
    local tok user
    tok="$(gh auth token 2>/dev/null || true)"
    user="$(gh api user --jq .login 2>/dev/null || true)"
    if [ -n "$tok" ] && [ -n "$user" ]; then
      docker logout ghcr.io &>/dev/null || true   # clear any stale entry so the fresh token saves cleanly
      echo "$tok" | docker login ghcr.io -u "$user" --password-stdin &>/dev/null || true
      if docker manifest inspect "$img" &>/dev/null; then
        info "Authenticated to ghcr.io as $user (base image pull)"
        return 0
      fi
    fi
  fi
  warn "Cannot pull the private base image from ghcr.io: $img"
  warn "Log Docker into GHCR once (your GitHub token needs the 'read:packages' scope):"
  warn "  gh auth refresh -h github.com -s read:packages"
  warn "  gh auth token | docker login ghcr.io -u <your-github-username> --password-stdin"
}

check_env() {
  local missing=0

  if [ ! -f "$BACKEND_ENV" ]; then
    warn ".env not found — creating from .env.example ..."
    cp "$BACKEND_ENV_EXAMPLE" "$BACKEND_ENV"
    missing=1
  fi

  if [ ! -f "$UI_ENV" ]; then
    if [ -f "$UI_ENV_EXAMPLE" ]; then
      info "../${PROJECT_NAME}-ui/.env not found — creating from .env.example ..."
      cp "$UI_ENV_EXAMPLE" "$UI_ENV"
    else
      warn "../${PROJECT_NAME}-ui not found — UI service will be skipped."
      warn "Clone it: git clone git@github.com:ajnacloud-ksj/${PROJECT_NAME}-ui.git ../${PROJECT_NAME}-ui"
    fi
  fi

  if [ "$missing" -eq 1 ]; then
    error "Fix the above before starting. Run './dev.sh setup' for guided setup."
    exit 1
  fi
}

check_sdk() {
  if [ ! -d "$AJNA_SDK_PATH" ]; then
    warn "ajna-cloud-sdk not found at: $AJNA_SDK_PATH"
    warn "Clone it with:"
    warn "  git clone git@github.com:ajnacloud-ksj/ajna-cloud-sdk.git $AJNA_SDK_PATH"
    warn "Or set AJNA_SDK_PATH to your existing clone."
    warn "Continuing anyway — SDK will be installed from PyPI (no hot-reload for SDK changes)."
  else
    info "SDK found at: $AJNA_SDK_PATH"
  fi
}

# ── IbexDB local stack helpers ────────────────────────────────────────────────
# When ibex-db-lambda is cloned alongside (see IBEX_BASE), IbexDB runs locally
# (MinIO + Iceberg + FastAPI) so the backend talks to a zero-latency local DB
# instead of the remote dev cluster. Falls back to remote when not present.
ibex_available() {
  [ -n "$IBEX_LAMBDA_PATH" ] && [ -f "$IBEX_COMPOSE_FILE" ]
}

# Run docker compose against the ibex-db-lambda stack
dc_ibex() {
  docker compose -p ibex-db-local -f "$IBEX_COMPOSE_FILE" "$@"
}

# Decide whether to use the local IbexDB stack. Honors IBEX_MODE (auto|local|remote):
#   remote → never use local (always the remote IBEX_API_URL from .env)
#   local  → force local (auto-clone the stack if missing)
#   auto   → use/auto-clone local (default); falls back to remote if clone fails
ibex_use_local() {
  [ "${IBEX_MODE:-auto}" != "remote" ]
}

# Clone one or more "<path>|<remote>|<branch>" repo entries that aren't present yet.
# Quiet about repos already cloned. Returns the number cloned via $_CLONED.
clone_repos() {
  _CLONED=0
  local entry repo_path remote branch name
  for entry in "$@"; do
    IFS='|' read -r repo_path remote branch <<< "$entry"
    name="$(basename "$repo_path")"
    if [ -d "$repo_path/.git" ]; then
      continue
    fi
    info "Cloning $name ($branch) from $remote ..."
    mkdir -p "$(dirname "$repo_path")"
    # Clone the target branch; fall back to the default branch if it doesn't exist.
    if git clone -b "$branch" "$remote" "$repo_path" 2>/dev/null \
       || git clone "$remote" "$repo_path"; then
      _CLONED=$((_CLONED + 1))
    else
      warn "Could not clone $remote — check your SSH key / GitHub access."
    fi
  done
}

# Generate the local file-mode binding shim from the per-app plugins repo's plugins.json.
# The repo is the single source of truth (plugins.json = hook→file); the SDK dev-loader reads
# bindings.dev.json, so we derive it here. Plugins bind under the LOCAL tenant (TENANT_ID) so
# they fire for the dev's own login, regardless of the manifest's production target tenant.
# bindings.dev.json is a generated, gitignored dev artifact — never committed to the plugins repo.
sync_local_plugins() {
  local manifest="$PLUGINS_DIR/plugins.json"
  if [ ! -f "$manifest" ]; then
    warn "No plugins.json in $PLUGINS_DIR — skipping plugin sync (is ${PROJECT_NAME}-plugins cloned?)"
    return
  fi
  python3 - "$manifest" "$PLUGINS_DIR/bindings.dev.json" "$SCRIPT_DIR/.env" "$PROJECT_NAME" <<'PY' && info "Synced local plugins from ${PROJECT_NAME}-plugins/plugins.json"
import json, os, re, sys
manifest, out, envfile, proj = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
tenant = proj.replace("-", "")  # default = app name w/o hyphens; TENANT_ID in .env overrides
if os.path.exists(envfile):
    for line in open(envfile):
        m = re.match(r"\s*TENANT_ID\s*=\s*(.+)", line)
        if m:
            tenant = m.group(1).strip().strip('"').strip("'"); break
data = json.load(open(manifest))
mapping = {p["hook"]: p["file"] for p in data.get("plugins", []) if p.get("hook") and p.get("file")}
json.dump({tenant: mapping}, open(out, "w"), indent=2)
print(f"  {len(mapping)} plugin(s) -> bindings.dev.json (tenant={tenant})")
PY
  # keep the generated shim out of the plugins repo's git status
  local gi="$PLUGINS_DIR/.gitignore"
  grep -qxF 'bindings.dev.json' "$gi" 2>/dev/null || echo 'bindings.dev.json' >> "$gi"
}

# Auto-clone the IbexDB stack repos if missing, then re-resolve paths so the
# stack becomes usable within this same invocation.
ibex_clone_if_missing() {
  clone_repos "${IBEX_REPOS[@]}"
  [ "${_CLONED:-0}" -gt 0 ] && resolve_ibex_paths || true
}

ibex_start() {
  # Auto-clone the stack first so a fresh checkout "just works" (request: like SDK/UI).
  ibex_clone_if_missing
  if ! ibex_available; then
    warn "IbexDB local stack unavailable — using remote IBEX_API_URL from .env"
    warn "  (clone failed or repos missing — check SSH access to github.com:ajnacloud-ksj)"
    return
  fi
  # Self-heal (general, not service-specific): the shared IbexDB stack must NEVER
  # publish a host port that an app needs (PORT_BACKEND/PORT_UI) — its services
  # live on 9000/9005/9006/8181/8100. If ANY ibex-local-* container is squatting
  # on one of our app ports (e.g. an older DynamoDB still on :8000 before it moved
  # to :8100), evict it and let `up` recreate it on its own compose port. Runs
  # BEFORE the "reuse if healthy" shortcut, which would otherwise pin the stale
  # mapping forever. Keyed off the app's ports, so it covers any such collision.
  local _p _squat=""
  for _p in "$PORT_BACKEND" "$PORT_UI"; do
    _squat="$_squat $(docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null \
      | awk -v pat=":${_p}->" '$0 ~ pat && $1 ~ /^ibex-local-/ {print $1}')"
  done
  _squat=$(echo $_squat | xargs 2>/dev/null)
  if [ -n "$_squat" ]; then
    warn "IbexDB container(s) on an app port: $_squat — evicting + recreating on their own ports ..."
    docker rm -f $_squat >/dev/null 2>&1 || true
    dc_ibex up -d fastapi minio minio-init iceberg-rest dynamodb-local >/dev/null 2>&1 || true
  fi
  # Idempotent: if the stack is already healthy, reuse it as-is. Recreating the
  # fixed-name containers (container_name in the compose) would otherwise conflict.
  if curl -sf "$IBEX_LOCAL_URL/health" &>/dev/null; then
    info "IbexDB local stack already running at $IBEX_LOCAL_URL (reusing)"
    return
  fi
  # Clear any stale ibex-local-* containers (left by an interrupted run, or started
  # outside this compose project) so 'up' creates cleanly without a name conflict.
  local stale
  stale=$(docker ps -aq --filter "name=ibex-local-" 2>/dev/null || true)
  [ -n "$stale" ] && docker rm -f $stale >/dev/null 2>&1 || true
  info "Starting IbexDB local stack (MinIO + Iceberg + FastAPI) ..."
  dc_ibex up -d --build fastapi minio minio-init iceberg-rest
  # Wait for FastAPI to be healthy
  local retries=0
  until curl -sf "$IBEX_LOCAL_URL/health" &>/dev/null || [ $retries -ge 30 ]; do
    sleep 2; retries=$((retries+1))
  done
  if curl -sf "$IBEX_LOCAL_URL/health" &>/dev/null; then
    info "IbexDB local stack ready at $IBEX_LOCAL_URL"
  else
    warn "IbexDB local stack did not become healthy in time — check: docker compose -p ibex-db-local logs"
  fi
}

ibex_stop() {
  info "Stopping IbexDB local stack ..."
  ibex_available && dc_ibex down --remove-orphans 2>/dev/null || true
  # Belt-and-suspenders: remove any ibex-local-* containers even if they were started
  # outside this compose project (fixed container_names otherwise linger and block the
  # next start). This is what makes `stop` then `start --local` switch cleanly.
  local stale
  stale=$(docker ps -aq --filter "name=ibex-local-" 2>/dev/null || true)
  [ -n "$stale" ] && docker rm -f $stale >/dev/null 2>&1 || true
}

# Point the backend at the local ibex stack by overriding IBEX_API_URL in .env.
# The backend runs inside Docker, so it must use host.docker.internal to reach
# the ibex stack on the host — not localhost (which is the container itself).
# Set a single .env key to a value, creating the line if absent. Marks IBEX_ENV_CHANGED=1
# only when the value actually changed — so callers can force a backend recreate (Docker
# Compose does NOT recreate a running container when env_file *contents* change, so a stale
# container would otherwise keep the old value until a manual stop/start).
_set_env_kv() {
  local key="$1" val="$2" cur
  cur=$(grep "^${key}=" "$BACKEND_ENV" 2>/dev/null | cut -d= -f2-)
  [ "$cur" = "$val" ] && return 0
  if grep -q "^${key}=" "$BACKEND_ENV" 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${val}|" "$BACKEND_ENV" && rm -f "$BACKEND_ENV.bak"
  else
    echo "${key}=${val}" >> "$BACKEND_ENV"
  fi
  IBEX_ENV_CHANGED=1
}

ibex_inject_env() {
  if ! ibex_available; then return; fi
  _set_env_kv IBEX_API_URL "$IBEX_CONTAINER_URL"
  info "IBEX_API_URL → $IBEX_CONTAINER_URL (local stack via host.docker.internal)"
  # The local stack uses its own admin key — swap it in too, or it 401s every request.
  _set_env_kv IBEX_API_KEY "$IBEX_LOCAL_KEY"
  info "IBEX_API_KEY → local stack key"
}

# Restore the remote IBEX_API_URL from .env.example so stopping the local stack
# (or switching to --remote) doesn't leave .env pointing at host.docker.internal.
# Safe to call unconditionally: only rewrites when .env holds the container URL.
ibex_restore_env() {
  local remote_url remote_key
  remote_url=$(grep "^IBEX_API_URL=" "$BACKEND_ENV_EXAMPLE" 2>/dev/null | cut -d= -f2-)
  remote_key=$(grep "^IBEX_API_KEY=" "$BACKEND_ENV_EXAMPLE" 2>/dev/null | cut -d= -f2-)
  if [ -n "$remote_url" ] && grep -q "^IBEX_API_URL=$IBEX_CONTAINER_URL" "$BACKEND_ENV" 2>/dev/null; then
    _set_env_kv IBEX_API_URL "$remote_url"
    info "IBEX_API_URL restored to remote: $remote_url"
    # Restore the matching remote key swapped out by ibex_inject_env.
    if [ -n "$remote_key" ]; then
      _set_env_kv IBEX_API_KEY "$remote_key"
      info "IBEX_API_KEY restored to remote dev key"
    fi
  fi
}

# Keep the UI's VITE_API_URL pointed at the ACTUAL backend port. dev.sh shifts the backend
# off :8000 when it's busy, so without this the UI would call a dead port. Runs on every
# start so switching ports/modes needs no manual .env edits.
ui_sync_api_url() {
  [ -f "$UI_ENV" ] || return 0
  local base="http://localhost:${PORT_BACKEND}"
  if grep -q "^VITE_API_URL=" "$UI_ENV" 2>/dev/null; then
    local cur suffix want
    cur=$(grep "^VITE_API_URL=" "$UI_ENV" | head -1 | cut -d= -f2-)
    # Preserve whatever path suffix the app expects (e.g. "/v1" or "") — only
    # swap the host:port. Some UIs put /v1 in baseURL, others put it
    # in each request path (green-box-telemetry) → never assume a suffix here.
    suffix=$(printf '%s' "$cur" | sed -E 's#^https?://[^/]+##')
    want="${base}${suffix}"
    [ "$cur" = "$want" ] && return 0
    sed -i.bak "s|^VITE_API_URL=.*|VITE_API_URL=$want|" "$UI_ENV" && rm -f "$UI_ENV.bak"
    info "UI VITE_API_URL → $want (synced to backend port)"
  else
    # Ensure the file ends with a newline before appending — otherwise the new
    # line glues onto the last entry (e.g. VITE_AWS_REGION) and corrupts both.
    [ -n "$(tail -c1 "$UI_ENV" 2>/dev/null)" ] && echo >> "$UI_ENV"
    echo "VITE_API_URL=${base}/v1" >> "$UI_ENV"
    info "UI VITE_API_URL → ${base}/v1 (synced to backend port)"
  fi
}

# Local UI URL INCLUDING the tenant subdomain. The app derives the tenant from the first
# host label (resolveTenant), so plain localhost:PORT won't resolve a tenant — devs must
# open {tenant}.{app}.localhost. *.localhost resolves to 127.0.0.1 automatically.
ui_local_url() {
  local tenant app
  tenant=$(grep "^TENANT_ID=" "$BACKEND_ENV" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' ')
  app=$(printf '%s' "$PROJECT_NAME" | tr -d '-')   # hyphen-free app label
  echo "http://${tenant:-default}.${app}.localhost:${PORT_UI}"
}

# Run docker compose with dynamic port + SDK env vars
# Project name is pinned so it's stable regardless of which directory dev.sh is invoked from.
dc() {
  load_ports
  # Bind-mount the per-app plugins repo as /app/local-plugins (normalized to an absolute path);
  # fall back to the in-repo ./local-plugins if the plugins repo isn't cloned.
  local lp="$PLUGINS_DIR"
  [ -d "$lp" ] && lp="$(cd "$lp" && pwd)" || lp="./local-plugins"
  AJNA_SDK_PATH="$AJNA_SDK_PATH" \
  LOCAL_PLUGINS_DIR="$lp" \
  UI_DIR="$UI_DIR" \
  PORT_BACKEND=$PORT_BACKEND \
  PORT_UI=$PORT_UI \
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

# ── Commands ──────────────────────────────────────────────────────────────────
cmd_setup() {
  section "First-time Setup"

  echo "1. Cloning missing repositories (SDK, UI, IbexDB local stack) ..."
  clone_repos "${SETUP_REPOS[@]}"
  # ibex-db-lambda may have just appeared — re-resolve so its paths/ports are known.
  resolve_ibex_paths
  for entry in "${SETUP_REPOS[@]}"; do
    repo_path="${entry%%|*}"
    [ -d "$repo_path/.git" ] && info "  $(basename "$repo_path") ✓" \
      || warn "  $(basename "$repo_path") — not cloned (check SSH access)"
  done

  echo ""
  echo "2. Setting up .env files ..."
  if [ ! -f "$BACKEND_ENV" ]; then
    cp "$BACKEND_ENV_EXAMPLE" "$BACKEND_ENV"
    info "Created .env from .env.example"
  else
    info ".env already exists ✓"
  fi

  if [ -d "$UI_DIR" ]; then
    if [ ! -f "$UI_ENV" ] && [ -f "$UI_ENV_EXAMPLE" ]; then
      cp "$UI_ENV_EXAMPLE" "$UI_ENV"
      info "Created ../${PROJECT_NAME}-ui/.env from .env.example"
    else
      info "../${PROJECT_NAME}-ui/.env already exists ✓"
    fi
  else
    warn "../${PROJECT_NAME}-ui not cloned yet — UI service won't start until you clone it:"
    warn "  git clone git@github.com:ajnacloud-ksj/${PROJECT_NAME}-ui.git $UI_DIR"
  fi

  echo ""
  info "Setup complete. Next steps:"
  echo "  1. Run: ./dev.sh start"
  echo "  2. First run only: curl -X POST http://localhost:8000/v1/admin/database/setup"
  echo ""
  echo "  The .env.example includes a shared dev IBEX_API_KEY for the triviz.cloud"
  echo "  dev cluster. Do NOT use this key in production."
}

# Pull one repo onto its target branch, stashing local changes if the tree is dirty.
# Never discards work: dirty changes are stashed and popped back (conflicts left in
# the stash with a warning). Increments $_PULL_FAILED on a failed pull.
pull_repo() {
  local dir="$1" branch="$2" stashed=0 cur
  cur="$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"

  # Stash local changes (including untracked) if the working tree is dirty
  if [ -n "$(git -C "$dir" status --porcelain 2>/dev/null)" ]; then
    info "  Stashing local changes ..."
    git -C "$dir" stash push -u -m "dev.sh auto-stash $(date +%F_%T)" >/dev/null 2>&1 && stashed=1
  fi

  # Switch to the target branch if not already on it
  if [ "$cur" != "$branch" ]; then
    info "  Switching $cur → $branch ..."
    if ! git -C "$dir" checkout "$branch" >/dev/null 2>&1; then
      warn "  Could not checkout '$branch' (does it exist?) — staying on '$cur'"
      branch="$cur"
    fi
  fi

  # Fast-forward pull (won't create surprise merge commits)
  if git -C "$dir" pull --ff-only origin "$branch" >/dev/null 2>&1; then
    info "  Pulled origin/$branch ✓"
  else
    warn "  Pull failed for '$branch' (diverged or no upstream?) — check: git -C $dir status"
    _PULL_FAILED=$((_PULL_FAILED + 1))
  fi

  # Restore stashed changes
  if [ "$stashed" = "1" ]; then
    if git -C "$dir" stash pop >/dev/null 2>&1; then
      info "  Restored stashed changes ✓"
    else
      warn "  Stash pop hit conflicts — your changes are safe: git -C $dir stash list"
      _PULL_FAILED=$((_PULL_FAILED + 1))
    fi
  fi
}

# Pull latest code for every repo onto its configured branch.
cmd_pull() {
  section "Pulling Latest Code"
  _PULL_FAILED=0
  local entry repo_path remote branch name
  for entry in "${PULL_REPOS[@]}"; do
    IFS='|' read -r repo_path remote branch <<< "$entry"
    name="$(basename "$repo_path")"
    if [ ! -d "$repo_path/.git" ]; then
      warn "  $name — not cloned (run './dev.sh setup')"
      continue
    fi
    printf "${CYAN}── %s (→ %s) ──${NC}\n" "$name" "$branch"
    pull_repo "$repo_path" "$branch"
    echo ""
  done
  [ "${_PULL_FAILED:-0}" -eq 0 ] \
    && info "All repos up to date." \
    || warn "$_PULL_FAILED issue(s) — see warnings above (work is stashed, never lost)."
}

# Pull all repos then rebuild + restart services.
cmd_update() {
  cmd_pull
  echo ""
  section "Restarting Services"
  cmd_restart "$@"
}

cmd_start() {
  # Parse args: an optional service name plus optional --local / --remote DB flag.
  local svc="" arg
  for arg in "$@"; do
    case "$arg" in
      --local)  IBEX_MODE=local ;;
      --remote) IBEX_MODE=remote ;;
      *)        svc="$arg" ;;
    esac
  done
  check_docker
  ensure_ghcr_login   # auth to ghcr.io so the private base image is pullable for the build
  # Auto-clone the SDK + UI if missing (the IbexDB stack is cloned by ibex_start),
  # so 'start' works even without a prior 'setup'. Run before check_env/check_sdk
  # so they see the freshly cloned directories.
  clone_repos "${APP_REPOS[@]}"
  sync_local_plugins   # derive bindings.dev.json from the plugins repo's plugins.json
  check_env
  check_sdk
  # Auto-run db setup only when it has NOT been done yet — tracked by a dedicated marker
  # that 'stop' never deletes (the old check used .dev_ports, which stop removes, so it
  # re-ran setup on every restart).
  [ ! -f "$SETUP_MARKER" ] && _FIRST_START=1 || _FIRST_START=0
  resolve_ports
  load_ports

  # Choose IbexDB backend: local stack (default/auto) or remote dev cluster.
  # IBEX_ENV_CHANGED is set by the inject/restore helpers when .env actually changes,
  # so we can force-recreate the backend below (Compose ignores env_file content changes).
  IBEX_ENV_CHANGED=0
  if [ -z "$svc" ] || [ "$svc" = "backend" ]; then
    if ibex_use_local; then
      ibex_start        # auto-clones + boots the stack; no-op falls back to remote
      ibex_inject_env   # points IBEX_API_URL + key at the local stack (only if it came up)
    else
      info "IBEX_MODE=remote — using remote IbexDB from .env"
      ibex_restore_env  # ensure .env points at the remote dev cluster
    fi
  fi

  ui_sync_api_url   # point the UI at the actual backend port (no manual .env edits)

  preflight_free_ports   # clear leftover/stale containers holding our ports (self-heal)

  info "Starting ${svc:-all services} ..."
  info "SDK path: $AJNA_SDK_PATH"

  # Force-recreate so the backend picks up an .env that ibex_inject/restore just changed
  # (Docker Compose does NOT recreate a running container when only env_file contents change).
  local recreate=""
  [ "${IBEX_ENV_CHANGED:-0}" = "1" ] && { recreate="--force-recreate"; info "IbexDB env changed — recreating backend to apply it"; }
  if [ -n "$svc" ]; then
    dc up -d --build $recreate "$svc"
  else
    dc up -d --build $recreate
  fi

  echo ""
  info "Services running:"
  echo "  Backend  →  http://localhost:$PORT_BACKEND"
  echo "  UI       →  $(ui_local_url)"
  echo "  API docs →  http://localhost:$PORT_BACKEND/docs"
  if ibex_available; then
    echo "  IbexDB   →  $IBEX_LOCAL_URL  (local — zero latency)"
    echo "  MinIO    →  http://localhost:9005  (console: http://localhost:9006)"
  fi
  echo ""
  echo -e "${CYAN}── Dev login ──${NC}"
  echo "  UI       →  $(ui_local_url)"
  echo "  (open the tenant subdomain above — NOT plain localhost — so the app resolves your tenant)"
  echo "  Email    →  dev@ajna.cloud"
  echo "  Password →  \$AjnaDev@2026\$   (shared dev admin)"
  echo ""

  # Auto-run db setup only the first time (no setup marker yet). cmd_db_setup creates the
  # marker, so subsequent restarts skip this.
  if [ "${_FIRST_START:-0}" = "1" ]; then
    info "First start (no db-setup marker) — running database setup ..."
    # Wait for backend to be healthy before hitting setup
    local retries=0
    until curl -sf "http://localhost:$PORT_BACKEND/v1/health" &>/dev/null || [ $retries -ge 15 ]; do
      sleep 1; retries=$((retries+1))
    done
    cmd_db_setup
    echo ""
    info "Database ready. You can re-run anytime: ./dev.sh db-setup"
  fi

  info "Commands:"
  echo "  Tail logs:   ./dev.sh logs [backend|ui]"
  echo "  Stop all:    ./dev.sh stop"
  echo "  Rebuild:     ./dev.sh restart backend"
  echo "  DB setup:    ./dev.sh db-setup"
}

cmd_stop() {
  local svc="${1:-}"
  check_docker
  if [ -n "$svc" ]; then
    info "Stopping $svc ..."
    dc stop "$svc"
  else
    info "Stopping all services ..."
    dc down
    rm -f "$PORTS_FILE"
    ibex_stop
    ibex_restore_env
  fi
}

cmd_restart() {
  # Extract the service (first non-flag arg) for stop; forward all args to start
  # so --local / --remote are honored.
  local svc="" arg
  for arg in "$@"; do
    case "$arg" in --local|--remote) ;; *) svc="$arg" ;; esac
  done
  cmd_stop "$svc" || true
  cmd_start "$@"
}

cmd_logs() {
  local svc="${1:-}"
  check_docker
  if [ -n "$svc" ]; then
    dc logs -f "$svc"
  else
    dc logs -f
  fi
}

cmd_status() {
  check_docker
  load_ports
  dc ps
  if [ -f "$PORTS_FILE" ]; then
    echo ""
    info "Ports:"
    echo "  Backend  →  http://localhost:$PORT_BACKEND"
    echo "  UI       →  $(ui_local_url)"
  fi
  if ibex_available; then
    echo ""
    info "IbexDB local stack:"
    dc_ibex ps
    echo "  IbexDB FastAPI  →  $IBEX_LOCAL_URL"
    echo "  MinIO API       →  http://localhost:9005"
    echo "  MinIO Console   →  http://localhost:9006"
  fi
}

cmd_build() {
  local svc="${1:-}"
  check_docker
  ensure_ghcr_login   # auth to ghcr.io so the private base image is pullable for the build
  load_ports
  if [ -n "$svc" ]; then
    info "Building $svc ..."
    dc build "$svc"
  else
    info "Building all images ..."
    dc build
  fi
}

cmd_db_setup() {
  load_ports
  local url="http://localhost:$PORT_BACKEND/v1/admin/database/setup"
  local login_url="http://localhost:$PORT_BACKEND/v1/auth/login"
  local tenant
  tenant=$(grep "^TENANT_ID=" "$BACKEND_ENV" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' ')
  local -a tenant_header=()
  if [ -n "$tenant" ]; then
    tenant_header=(-H "X-Tenant-ID: $tenant")
    info "Using tenant context for db-setup: $tenant"
  else
    warn "TENANT_ID not found in .env — db-setup will use token-derived tenant context"
  fi
  info "Running database setup at $url ..."
  if ! command -v curl &>/dev/null; then
    warn "curl not found — run manually: curl -X POST $url"
    return
  fi
  # Authenticate with the shared dev admin to get a Bearer token.
  local token
  token=$(curl -s -X POST "$login_url" \
    -H "Content-Type: application/json" \
    -d '{"username":"dev@ajna.cloud","password":"$AjnaDev@2026$"}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
  if [ -z "$token" ]; then
    warn "Could not obtain auth token — calling setup without auth (will fail if auth is enforced)."
    curl -s -X POST "$url" "${tenant_header[@]}" | (command -v python3 &>/dev/null && python3 -m json.tool || cat)
  else
    curl -s -X POST "$url" -H "Authorization: Bearer $token" "${tenant_header[@]}" | (command -v python3 &>/dev/null && python3 -m json.tool || cat)
  fi
  touch "$SETUP_MARKER"   # mark setup done so it isn't re-run on every restart
}

# Wipe local IbexDB data (MinIO warehouse + Iceberg catalog) and rebuild a fresh DB.
# Local-only — does NOT touch the remote dev cluster. Volumes are named ibex-db-local_*.
cmd_reset_db() {
  check_docker
  warn "RESET: deleting ALL local IbexDB data (MinIO warehouse + Iceberg catalog)."
  warn "       This is local-only — the remote dev cluster is untouched."
  ibex_stop   # frees the volumes
  local removed=0 v
  for v in ibex-db-local_minio_data ibex-db-local_iceberg_catalog; do
    if docker volume rm "$v" >/dev/null 2>&1; then info "removed volume $v"; removed=$((removed+1)); fi
  done
  [ "$removed" -eq 0 ] && info "no local IbexDB volumes present (already clean)"
  rm -f "$SETUP_MARKER"       # force a fresh db-setup on the next start
  info "Rebooting local stack on a fresh DB ..."
  cmd_start --local           # recreates the stack + empty volumes, then auto-runs db-setup
  info "Local IbexDB reset complete."
}

# ── Entry point ───────────────────────────────────────────────────────────────
CMD="${1:-help}"
shift || true
case "$CMD" in
  setup)    cmd_setup ;;
  pull)     cmd_pull ;;
  update)   cmd_update   "$@" ;;
  start)    cmd_start    "$@" ;;
  stop)     cmd_stop     "${1:-}" ;;
  restart)  cmd_restart  "$@" ;;
  logs)     cmd_logs     "${1:-}" ;;
  status)   cmd_status ;;
  build)    cmd_build    "${1:-}" ;;
  db-setup) cmd_db_setup ;;
  reset-db) cmd_reset_db ;;
  help|*)
    echo ""
    echo "Usage: $0 <command> [service] [--local|--remote]"
    echo ""
    echo "Commands:"
    echo "  setup              First-time setup: clone all repos (SDK, UI, IbexDB stack), copy .env"
    echo "  pull               Pull latest code in all repos onto their configured branches"
    echo "  update [svc]       Pull all repos + rebuild & restart services"
    echo "  start  [svc]       Build and start (all, or: backend | ui)"
    echo "  stop   [svc]       Stop (all or one service)"
    echo "  restart [svc]      Stop + start"
    echo "  logs   [svc]       Tail logs"
    echo "  status             Show running containers and URLs"
    echo "  build  [svc]       Rebuild image(s) without starting"
    echo "  db-setup           Run database setup (idempotent — safe to re-run)"
    echo "  reset-db           Wipe local IbexDB data (volumes) + rebuild fresh — local only"
    echo ""
    echo "IbexDB backend selection (start/restart/update):"
    echo "  --local            Force the local IbexDB stack (auto-clones it if missing)"
    echo "  --remote           Force the remote dev cluster (IBEX_API_URL from .env)"
    echo "  (default 'auto')   Use the local stack when present/cloneable, else remote"
    echo ""
    echo "Per-repo branches for pull/update (override via env var):"
    echo "  ajna-cloud-sdk → \$SDK_BRANCH (main)         ibex-db-lambda → \$IBEX_DB_BRANCH (develop)"
    echo "  ibex-policy → \$IBEX_POLICY_BRANCH (main)     ibex-query-engine-lib → \$IBEX_QE_BRANCH (main)"
    echo "  ${PROJECT_NAME}-ui → \$UI_BRANCH (develop)          ${PROJECT_NAME}-backend → \$SELF_BRANCH (develop)"
    echo "  pull stashes local changes before pulling and pops them back afterwards."
    echo ""
    echo "Environment variables:"
    echo "  IBEX_MODE          auto (default) | local | remote — same as the flags above"
    echo "  AJNA_SDK_PATH      Path to ajna-cloud-sdk clone (default: <root>/ibex/ajna-cloud-sdk)"
    echo "  IBEX_LAMBDA_PATH   Override path to ibex-db-lambda clone"
    echo "                     When used locally, dev.sh boots MinIO + Iceberg + FastAPI and"
    echo "                     points IBEX_API_URL at the local stack (zero latency)."
    echo ""
    ;;
esac
