#!/usr/bin/env bash
# {{app-name}} — Tenant Onboarding Script
#
# Usage (non-interactive / CI):
#   bash scripts/onboard_tenant.sh \
#     --tenant   acme \
#     --company  "Acme Inc" \
#     --email    admin@acme.com \
#     --plan     standard
#
# Usage (interactive):
#   bash scripts/onboard_tenant.sh
#
# What this script does:
#   1. Validate inputs
#   2. Create Cognito groups for all roles (scoped to this tenant)
#   3. Create Cognito admin user with temporary password
#   4. Call backend POST /v1/admin/tenants → creates tenant record + bootstraps IbexDB RBAC
#   5. Print ready-to-use credentials and next steps
#
# Prerequisites:
#   - aws CLI configured with credentials for COGNITO_REGION
#   - curl, jq installed
#   - Backend running at $BACKEND_URL (default: http://localhost:8000)
#   - Super admin credentials (SUPER_ADMIN_USER / SUPER_ADMIN_PASS or --admin-user / --admin-pass)

set -euo pipefail

# ── Constants ──────────────────────────────────────────────────────────────────

REGION="{{aws-region}}"
COGNITO_POOL_ID="{{cognito-user-pool-id}}"
COGNITO_CLIENT_ID="{{cognito-client-id}}"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
APP_PREFIX="{{app-name}}"

# Roles defined in the app (src/config/roles.py) — each becomes a Cognito group
ROLES=("super_admin" "admin" "user")

role_desc() {
    case "$1" in
        super_admin) echo "{{app-name}} — Super Admin (cross-tenant platform access)" ;;
        admin)       echo "{{app-name}} — Admin (full tenant access)" ;;
        user)        echo "{{app-name}} — User (standard access)" ;;
        *)           echo "{{app-name}} — $1" ;;
    esac
}

# ── Helpers ────────────────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}✓${RESET} $*"; }
info() { echo -e "${CYAN}→${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
die()  { echo -e "${RED}✗ $*${RESET}" >&2; exit 1; }

require() { command -v "$1" &>/dev/null || die "Required tool not found: $1"; }
to_lower() { echo "$1" | tr '[:upper:]' '[:lower:]'; }
to_slug()  { echo "$1" | tr '[:upper:]' '[:lower:]' | tr ' ' '_' | tr -cd '[:alnum:]_'; }

prompt() {
    local var_name="$1" prompt_text="$2" default="${3:-}"
    if [ -n "$default" ]; then
        read -rp "  $prompt_text [$default]: " _val
        eval "$var_name=\"${_val:-$default}\""
    else
        read -rp "  $prompt_text: " _val
        eval "$var_name=\"$_val\""
    fi
}

# Generate a random temporary password that satisfies Cognito policy
gen_temp_password() {
    echo "Tmp$(openssl rand -base64 12 | tr -d '=/+' | head -c 10)!7"
}

# ── Parse CLI args ─────────────────────────────────────────────────────────────

TENANT_ID=""
COMPANY_NAME=""
ADMIN_EMAIL=""
PLAN="standard"
SUPER_ADMIN_USER="${SUPER_ADMIN_USER:-admin}"
SUPER_ADMIN_PASS="${SUPER_ADMIN_PASS:-password123}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tenant)     TENANT_ID="$2";       shift 2 ;;
        --company)    COMPANY_NAME="$2";    shift 2 ;;
        --email)      ADMIN_EMAIL="$2";     shift 2 ;;
        --plan)       PLAN="$2";            shift 2 ;;
        --admin-user) SUPER_ADMIN_USER="$2"; shift 2 ;;
        --admin-pass) SUPER_ADMIN_PASS="$2"; shift 2 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

# ── Preflight ──────────────────────────────────────────────────────────────────

require aws
require jq
require curl

echo ""
echo "========================================================"
echo "  {{app-name}} — Tenant Onboarding"
echo "========================================================"
echo ""

info "Checking AWS credentials..."
CALLER=$(aws sts get-caller-identity --region "$REGION" --output text --query 'Arn' 2>&1) \
    || die "AWS credentials not configured. Run: aws configure"
ok "AWS identity: $CALLER"

info "Checking backend at $BACKEND_URL..."
HEALTH=$(curl -sf "$BACKEND_URL/health" 2>/dev/null | jq -r '.status' 2>/dev/null || echo "unreachable")
[ "$HEALTH" = "healthy" ] || die "Backend not reachable at $BACKEND_URL — start it first: ./dev.sh start"
ok "Backend is healthy"
echo ""

# ── Step 1: Collect details ────────────────────────────────────────────────────

echo "--- Step 1/4: Tenant Details ---"
echo ""

if [ -z "$TENANT_ID" ]; then
    prompt COMPANY_NAME "Company name (e.g. 'Acme Inc')"
    TENANT_ID=$(to_slug "$COMPANY_NAME")
    prompt TENANT_ID "Tenant ID (slug)" "$TENANT_ID"
else
    [ -z "$COMPANY_NAME" ] && prompt COMPANY_NAME "Company name" "$(echo "$TENANT_ID" | tr '_' ' ' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2)); print}')"
fi

[ -z "$TENANT_ID" ]    && die "Tenant ID is required"
[ -z "$COMPANY_NAME" ] && die "Company name is required"

[[ "$TENANT_ID" =~ ^[a-z0-9_]+$ ]] \
    || die "Tenant ID must be lowercase alphanumeric with underscores. Got: '$TENANT_ID'"

if [ -z "$ADMIN_EMAIL" ]; then
    prompt ADMIN_EMAIL "Admin email for $COMPANY_NAME"
fi
[ -z "$ADMIN_EMAIL" ] && die "Admin email is required"

TEMP_PASSWORD=$(gen_temp_password)
# Pool requires email format for username
ADMIN_USERNAME="$ADMIN_EMAIL"

echo ""
echo "  Tenant ID:    $TENANT_ID"
echo "  Company:      $COMPANY_NAME"
echo "  Admin email:  $ADMIN_EMAIL"
echo "  Admin user:   $ADMIN_EMAIL (Cognito username = email)"
echo "  Plan:         $PLAN"
echo ""

if [ -t 0 ]; then
    read -rp "  Proceed? [y/N]: " _confirm
    [[ "$(to_lower "$_confirm")" == "y" ]] || { echo "Aborted."; exit 0; }
    echo ""
fi

# ── Step 2: Cognito groups ─────────────────────────────────────────────────────

echo "--- Step 2/4: Cognito Groups ---"
echo ""

for role in "${ROLES[@]}"; do
    GROUP_NAME="${APP_PREFIX}-${TENANT_ID}-${role}"
    EXISTING=$(aws cognito-idp get-group \
        --user-pool-id "$COGNITO_POOL_ID" \
        --group-name "$GROUP_NAME" \
        --region "$REGION" \
        --output text 2>/dev/null || echo "")

    if [ -n "$EXISTING" ]; then
        warn "Group already exists: $GROUP_NAME (skipped)"
    else
        aws cognito-idp create-group \
            --user-pool-id "$COGNITO_POOL_ID" \
            --group-name "$GROUP_NAME" \
            --description "$(role_desc "$role")" \
            --region "$REGION" \
            --output json > /dev/null
        ok "Created group: $GROUP_NAME"
    fi
done
echo ""

# ── Step 3: Cognito admin user ─────────────────────────────────────────────────

echo "--- Step 3/4: Cognito Admin User ---"
echo ""

EXISTING_USER=$(aws cognito-idp admin-get-user \
    --user-pool-id "$COGNITO_POOL_ID" \
    --username "$ADMIN_USERNAME" \
    --region "$REGION" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_USER" ]; then
    warn "User already exists: $ADMIN_USERNAME (skipped creation)"
else
    aws cognito-idp admin-create-user \
        --user-pool-id "$COGNITO_POOL_ID" \
        --username "$ADMIN_USERNAME" \
        --user-attributes \
            Name=email,Value="$ADMIN_EMAIL" \
            Name=email_verified,Value=true \
            "Name=custom:role,Value=admin" \
            "Name=custom:tenant_id,Value=$TENANT_ID" \
        --temporary-password "$TEMP_PASSWORD" \
        --message-action SUPPRESS \
        --region "$REGION" \
        --output json > /dev/null
    ok "Created Cognito user: $ADMIN_USERNAME"

    # Add user to the admin group for this tenant
    ADMIN_GROUP="${APP_PREFIX}-${TENANT_ID}-admin"
    aws cognito-idp admin-add-user-to-group \
        --user-pool-id "$COGNITO_POOL_ID" \
        --username "$ADMIN_USERNAME" \
        --group-name "$ADMIN_GROUP" \
        --region "$REGION" 2>/dev/null || true
    ok "Added $ADMIN_USERNAME → $ADMIN_GROUP"
fi
echo ""

# ── Step 4: Backend tenant record + IbexDB RBAC ────────────────────────────────

echo "--- Step 4/4: Backend Tenant Record + RBAC Bootstrap ---"
echo ""

info "Authenticating as super admin ($SUPER_ADMIN_USER)..."
AUTH_RESP=$(curl -s -X POST "$BACKEND_URL/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$SUPER_ADMIN_USER\",\"password\":\"$SUPER_ADMIN_PASS\"}")

TOKEN=$(echo "$AUTH_RESP" | jq -r '.access_token // empty')
[ -n "$TOKEN" ] || {
    echo "Auth response: $AUTH_RESP"
    die "Failed to authenticate as super admin. Check SUPER_ADMIN_USER / SUPER_ADMIN_PASS."
}
ok "Authenticated"

info "Creating tenant record..."
TENANT_RESP=$(curl -s -X POST "$BACKEND_URL/v1/admin/tenants" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$(jq -n \
        --arg tid  "$TENANT_ID" \
        --arg name "$COMPANY_NAME" \
        --arg mail "$ADMIN_EMAIL" \
        --arg plan "$PLAN" \
        '{tenant_id:$tid, company_name:$name, contact_email:$mail, plan:$plan}')")

TENANT_SUCCESS=$(echo "$TENANT_RESP" | jq -r '.success // false')

if [ "$TENANT_SUCCESS" = "true" ]; then
    ok "Tenant record created in IbexDB"
    ROLES_CREATED=$(echo "$TENANT_RESP" | jq -r '.data.rbac_bootstrap.roles_created | join(", ")')
    ok "IbexDB RBAC roles bootstrapped: $ROLES_CREATED"
else
    ERROR=$(echo "$TENANT_RESP" | jq -r '.data.error // .error // "unknown"')
    # If tenant already exists, that's OK
    if echo "$ERROR" | grep -qi "already\|duplicate\|exist"; then
        warn "Tenant record already exists in DB (skipped)"
    else
        echo "Response: $TENANT_RESP"
        die "Failed to create tenant: $ERROR"
    fi
fi
echo ""

# ── Summary ────────────────────────────────────────────────────────────────────

echo "========================================================"
echo "  Onboarding Complete: $COMPANY_NAME"
echo "========================================================"
echo ""
echo "  Tenant ID:       $TENANT_ID"
echo "  Company:         $COMPANY_NAME"
echo "  Plan:            $PLAN"
echo ""
echo "  Cognito groups:"
for role in "${ROLES[@]}"; do
    echo "    ${APP_PREFIX}-${TENANT_ID}-${role}"
done
echo ""
echo -e "  ${YELLOW}Admin credentials (first login):${RESET}"
echo "    Username:  $ADMIN_USERNAME"
echo "    Password:  $TEMP_PASSWORD"
echo "    Email:     $ADMIN_EMAIL"
echo ""
echo -e "${YELLOW}  ⚠  User must change password on first login.${RESET}"
echo ""
echo "--- Next steps ---"
echo "  1. Give the admin their credentials: $ADMIN_USERNAME / $TEMP_PASSWORD"
echo "  2. They log in at the deployed frontend URL"
echo "  3. They'll be prompted to set a permanent password"
echo "  4. Portal is live at: /$TENANT_ID"
echo ""
