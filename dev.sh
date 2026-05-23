#!/usr/bin/env bash
# dev.sh — Local development helper for {{app-name}}
#
# Run from inside {{app-name}}-backend/ (this repo):
#   ./dev.sh setup                  — first-time setup (copy .env, check SDK + UI repo)
#   ./dev.sh start   [backend|ui]   — build & start (all services or one)
#   ./dev.sh stop    [backend|ui]   — stop (all or one)
#   ./dev.sh restart [backend|ui]   — stop + start
#   ./dev.sh logs    [backend|ui]   — tail logs (all or one)
#   ./dev.sh status                 — show running containers + ports
#   ./dev.sh build   [backend|ui]   — rebuild image(s) without starting
#   ./dev.sh db-setup               — run database setup (idempotent)
#
# The UI repo ({{app-name}}-ui) is expected as a SIBLING directory of this repo:
#   parent/
#   ├── {{app-name}}-backend/   ← this repo (run dev.sh from here)
#   └── {{app-name}}-ui/        ← clone it next to this repo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Derive a stable project name from the backend folder (strips -backend suffix)
PROJECT_NAME="$(basename "$SCRIPT_DIR" | sed 's/-backend$//')"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.local.yml"
PORTS_FILE="$SCRIPT_DIR/.dev_ports"
# .env lives alongside dev.sh inside {{app-name}}-backend/
BACKEND_ENV="$SCRIPT_DIR/.env"
BACKEND_ENV_EXAMPLE="$SCRIPT_DIR/.env.example"
# UI repo is expected as a sibling directory
UI_DIR="$SCRIPT_DIR/../{{app-name}}-ui"
UI_ENV="$UI_DIR/.env"
UI_ENV_EXAMPLE="$UI_DIR/.env.example"

# SDK path resolution (checked in order):
#   1. AJNA_SDK_PATH env var (explicit override)
#   2. ~/ajna/ibex/ajna-cloud-sdk  (standard team clone location)
#   3. ../ajna-cloud-sdk           (sibling directory of this repo)
if [ -z "${AJNA_SDK_PATH:-}" ]; then
  if [ -d "$HOME/ajna/ibex/ajna-cloud-sdk" ]; then
    AJNA_SDK_PATH="$HOME/ajna/ibex/ajna-cloud-sdk"
  elif [ -d "$SCRIPT_DIR/../ajna-cloud-sdk" ]; then
    AJNA_SDK_PATH="$(cd "$SCRIPT_DIR/../ajna-cloud-sdk" && pwd)"
  else
    AJNA_SDK_PATH="$HOME/ajna/ibex/ajna-cloud-sdk"  # show this path in error message
  fi
fi

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

resolve_ports() {
  PORT_BACKEND=$(find_free_port $DEFAULT_BACKEND)
  PORT_UI=$(find_free_port $DEFAULT_UI)
  [ "$PORT_UI" -eq "$PORT_BACKEND" ] && PORT_UI=$((PORT_UI + 1))
  PORT_UI=$(find_free_port $PORT_UI)

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

# ── Helpers ───────────────────────────────────────────────────────────────────
check_docker() {
  if ! command -v docker &>/dev/null; then
    error "Docker not found. Install Docker Desktop: https://docs.docker.com/get-docker/"
    exit 1
  fi
  if ! docker info &>/dev/null; then
    error "Docker daemon is not running. Start OrbStack (or Docker Desktop) first."
    exit 1
  fi
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
      info "../{{app-name}}-ui/.env not found — creating from .env.example ..."
      cp "$UI_ENV_EXAMPLE" "$UI_ENV"
    else
      warn "../{{app-name}}-ui not found — UI service will be skipped."
      warn "Clone it: git clone git@github.com:{{github-org}}/{{app-name}}-ui.git ../{{app-name}}-ui"
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

# Run docker compose with dynamic port + SDK env vars
# Project name is pinned so it's stable regardless of which directory dev.sh is invoked from.
dc() {
  load_ports
  AJNA_SDK_PATH="$AJNA_SDK_PATH" \
  PORT_BACKEND=$PORT_BACKEND \
  PORT_UI=$PORT_UI \
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

# ── Commands ──────────────────────────────────────────────────────────────────
cmd_setup() {
  section "First-time Setup"

  echo "1. Checking SDK clone ..."
  if [ ! -d "$AJNA_SDK_PATH" ]; then
    warn "SDK not found at $AJNA_SDK_PATH"
    echo ""
    echo "  Clone it to the standard team location:"
    echo "    git clone git@github.com:ajnacloud-ksj/ajna-cloud-sdk.git $HOME/ajna/ibex/ajna-cloud-sdk"
    echo "  Or set AJNA_SDK_PATH to your existing clone before running dev.sh:"
    echo "    export AJNA_SDK_PATH=/your/path/ajna-cloud-sdk"
    echo ""
  else
    info "SDK found ✓"
  fi

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
      info "Created ../{{app-name}}-ui/.env from .env.example"
    else
      info "../{{app-name}}-ui/.env already exists ✓"
    fi
  else
    warn "../{{app-name}}-ui not cloned yet — UI service won't start until you clone it:"
    warn "  git clone git@github.com:{{github-org}}/{{app-name}}-ui.git $UI_DIR"
  fi

  echo ""
  info "Setup complete. Next steps:"
  echo "  1. Edit .env and set IBEX_API_KEY (and Cognito values) for your app."
  echo "  2. Run: ./dev.sh start"
  echo "  3. First run only: database setup runs automatically (or ./dev.sh db-setup)."
  echo ""
}

cmd_start() {
  local svc="${1:-}"
  check_docker
  check_env
  check_sdk
  # Detect first-ever start (no .dev_ports yet) to auto-run db setup
  [ ! -f "$PORTS_FILE" ] && _FIRST_START=1 || _FIRST_START=0
  resolve_ports
  load_ports

  info "Starting ${svc:-all services} ..."
  info "SDK path: $AJNA_SDK_PATH"

  if [ -n "$svc" ]; then
    dc up -d --build "$svc"
  else
    dc up -d --build
  fi

  echo ""
  info "Services running:"
  echo "  Backend  →  http://localhost:$PORT_BACKEND"
  echo "  UI       →  http://localhost:$PORT_UI"
  echo "  API docs →  http://localhost:$PORT_BACKEND/docs"
  echo ""
  echo -e "${CYAN}── Dev login (shared dev Cognito pool) ──${NC}"
  echo "  UI       →  http://localhost:$PORT_UI"
  echo "  Email    →  dev@ajna.cloud"
  echo "  Password →  \$AjnaDev@2026\$   (shared dev super_admin)"
  echo ""

  # Auto-run db setup on first start (when .dev_ports didn't exist before)
  if [ "${_FIRST_START:-0}" = "1" ]; then
    info "First start detected — running database setup ..."
    # Wait for backend to be healthy before hitting setup
    local retries=0
    until curl -sf "http://localhost:$PORT_BACKEND/health" &>/dev/null || [ $retries -ge 15 ]; do
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
  fi
}

cmd_restart() {
  local svc="${1:-}"
  cmd_stop "$svc" || true
  cmd_start "$svc"
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
    echo "  UI       →  http://localhost:$PORT_UI"
  fi
}

cmd_build() {
  local svc="${1:-}"
  check_docker
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
  info "Running database setup at $url ..."
  if command -v curl &>/dev/null; then
    curl -s -X POST "$url" | (command -v python3 &>/dev/null && python3 -m json.tool || cat)
  else
    warn "curl not found — run manually: curl -X POST $url"
  fi
}

# ── Entry point ───────────────────────────────────────────────────────────────
CMD="${1:-help}"
shift || true
case "$CMD" in
  setup)    cmd_setup ;;
  start)    cmd_start    "${1:-}" ;;
  stop)     cmd_stop     "${1:-}" ;;
  restart)  cmd_restart  "${1:-}" ;;
  logs)     cmd_logs     "${1:-}" ;;
  status)   cmd_status ;;
  build)    cmd_build    "${1:-}" ;;
  db-setup) cmd_db_setup ;;
  help|*)
    echo ""
    echo "Usage: $0 <command> [service]"
    echo ""
    echo "Commands:"
    echo "  setup              First-time setup (copy .env files, check SDK)"
    echo "  start  [svc]       Build and start (all, or: backend | ui)"
    echo "  stop   [svc]       Stop (all or one service)"
    echo "  restart [svc]      Stop + start"
    echo "  logs   [svc]       Tail logs"
    echo "  status             Show running containers and URLs"
    echo "  build  [svc]       Rebuild image(s) without starting"
    echo "  db-setup           Run database setup (idempotent — safe to re-run)"
    echo ""
    echo "Environment variables:"
    echo "  AJNA_SDK_PATH      Path to ajna-cloud-sdk clone (default: ~/ajna/ibex/ajna-cloud-sdk)"
    echo ""
    ;;
esac
