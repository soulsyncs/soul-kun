#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Pre-Deploy Check Script (Layer 3)
# =============================================================================
#
# Purpose: Verify production DB is ready before deploying new code.
# Run after merge, before deploy.
#
# Usage:
#   scripts/pre_deploy_check.sh                    # Full check (requires DB access)
#   scripts/pre_deploy_check.sh --dry-run          # Show what would be checked (no DB)
#   scripts/pre_deploy_check.sh --skip-db          # Skip DB checks, only check code
#
# Requirements:
#   - cloud-sql-proxy installed
#   - gcloud authenticated with soulkun-production project
#   - DB_PASSWORD secret accessible
#
# Env:
#   PROXY_PORT=15432
#   PROJECT_ID=soulkun-production
#   INSTANCE=soulkun-production:asia-northeast1:soulkun-db
#   DB_NAME=soulkun_tasks
#   DB_USER=soulkun_user
# =============================================================================

PROXY_PORT="${PROXY_PORT:-15432}"
PROJECT_ID="${PROJECT_ID:-soulkun-production}"
INSTANCE="${INSTANCE:-soulkun-production:asia-northeast1:soulkun-db}"
DB_NAME="${DB_NAME:-soulkun_tasks}"
DB_USER="${DB_USER:-soulkun_user}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

DRY_RUN=0
SKIP_DB=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --skip-db) SKIP_DB=1 ;;
    *) echo "Unknown option: $arg"; echo "Usage: $0 [--dry-run] [--skip-db]"; exit 1 ;;
  esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

pass() {
  echo -e "  ${GREEN}PASS${NC} $1"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  echo -e "  ${RED}FAIL${NC} $1"
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

warn() {
  echo -e "  ${YELLOW}WARN${NC} $1"
  WARN_COUNT=$((WARN_COUNT + 1))
}

run_sql() {
  local sql="$1"
  PGPASSWORD="$DB_PASS" psql -h 127.0.0.1 -p "$PROXY_PORT" -U "$DB_USER" -d "$DB_NAME" -t -A -c "$sql" 2>/dev/null
}

# =============================================================================
# Check 1: Code-level checks (no DB required)
# =============================================================================

echo ""
echo "=== Pre-Deploy Check ==="
echo ""

echo "[1/4] Code-level checks..."

# 1a. lib/ sync check
echo "  Checking lib/ sync..."
SYNC_ISSUES=0
while IFS= read -r lib_file; do
  rel_path="${lib_file#"$REPO_ROOT"/lib/}"
  cw_file="$REPO_ROOT/chatwork-webhook/lib/$rel_path"
  pm_file="$REPO_ROOT/proactive-monitor/lib/$rel_path"

  if [[ -f "$cw_file" ]]; then
    if ! diff -q "$lib_file" "$cw_file" >/dev/null 2>&1; then
      fail "Out of sync: lib/$rel_path vs chatwork-webhook/lib/$rel_path"
      SYNC_ISSUES=$((SYNC_ISSUES + 1))
    fi
  fi
  if [[ -f "$pm_file" ]]; then
    if ! diff -q "$lib_file" "$pm_file" >/dev/null 2>&1; then
      fail "Out of sync: lib/$rel_path vs proactive-monitor/lib/$rel_path"
      SYNC_ISSUES=$((SYNC_ISSUES + 1))
    fi
  fi
done < <(find "$REPO_ROOT/lib" -name "*.py" -type f 2>/dev/null)

if [[ "$SYNC_ISSUES" -eq 0 ]]; then
  pass "All lib/ copies in sync"
fi

# 1b. Migration rollback check
echo "  Checking migration rollbacks..."
ROLLBACK_ISSUES=0
while IFS= read -r migration; do
  basename_file="$(basename "$migration")"
  # Skip rollback files themselves
  if [[ "$basename_file" == *"rollback"* ]]; then
    continue
  fi
  # Check if corresponding rollback exists
  rollback_name="${basename_file%.sql}_rollback.sql"
  dir="$(dirname "$migration")"
  if [[ ! -f "$dir/$rollback_name" ]]; then
    # Also check with date prefix pattern
    date_prefix="${basename_file%%_*}"
    if ! ls "$dir"/*rollback*"${basename_file#*_}" 2>/dev/null | head -1 >/dev/null 2>&1; then
      # Check for generic rollback comment in the file
      if ! grep -q "ロールバック\|rollback\|ROLLBACK" "$migration" 2>/dev/null; then
        warn "No rollback found for: $basename_file"
        ROLLBACK_ISSUES=$((ROLLBACK_ISSUES + 1))
      fi
    fi
  fi
done < <(find "$REPO_ROOT/migrations" -name "*.sql" -type f 2>/dev/null | grep -v rollback)

if [[ "$ROLLBACK_ISSUES" -eq 0 ]]; then
  pass "All migrations have rollback info"
fi

# 1b-2. Required environment variables check (v11.2.0: ALERT_ROOM_ID)
# These env vars must be set in production Cloud Run; absence causes silent monitoring failure
echo "  Checking required environment variables (gcloud)..."
REQUIRED_ENV_VARS=("ALERT_ROOM_ID")
ENV_VAR_ISSUES=0
if command -v gcloud &>/dev/null; then
  for service in chatwork-webhook proactive-monitor; do
    deployed_env=$(gcloud run services describe "$service" \
      --project="${PROJECT_ID}" \
      --region=asia-northeast1 \
      --format="value(spec.template.spec.containers[0].env[].name)" 2>/dev/null || echo "")
    for var in "${REQUIRED_ENV_VARS[@]}"; do
      if [[ -z "$deployed_env" ]]; then
        warn "Could not retrieve env vars for $service (gcloud auth required)"
        ENV_VAR_ISSUES=$((ENV_VAR_ISSUES + 1))
      elif ! echo "$deployed_env" | grep -q "^${var}$"; then
        fail "Required env var $var is NOT set in Cloud Run service: $service"
        ENV_VAR_ISSUES=$((ENV_VAR_ISSUES + 1))
      fi
    done
  done
else
  warn "gcloud not available — skipping required env var check (ALERT_ROOM_ID etc.)"
  ENV_VAR_ISSUES=1
fi
if [[ "$ENV_VAR_ISSUES" -eq 0 ]]; then
  pass "All required env vars present in Cloud Run"
fi

# 1c. Hardcoded secrets check
echo "  Checking for hardcoded secrets..."
SECRET_ISSUES=0
# Search for potential hardcoded API keys, passwords (excluding test files, docs, .env.example)
while IFS= read -r match; do
  if [[ -n "$match" ]]; then
    fail "Potential hardcoded secret: $match"
    SECRET_ISSUES=$((SECRET_ISSUES + 1))
  fi
done < <(grep -rn --include="*.py" \
  -E "(api_key|password|secret|token)\s*=\s*['\"][a-zA-Z0-9]{20,}" \
  "$REPO_ROOT/lib/" "$REPO_ROOT/chatwork-webhook/" "$REPO_ROOT/api/" 2>/dev/null \
  | grep -v "test_\|tests/\|example\|mock\|fake\|dummy\|placeholder\|your-" || true)

if [[ "$SECRET_ISSUES" -eq 0 ]]; then
  pass "No hardcoded secrets detected"
fi

# =============================================================================
# Check 2-4: DB checks (require connection)
# =============================================================================

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo ""
  echo "[DRY RUN] Skipping DB checks. Would check:"
  echo "  - Table existence (all tables referenced in code)"
  echo "  - RLS policies on all tables with organization_id"
  echo "  - RLS cast type correctness"
  echo ""
  echo "=== Results: $PASS_COUNT passed, $FAIL_COUNT failed, $WARN_COUNT warnings ==="
  exit 0
fi

if [[ "$SKIP_DB" -eq 1 ]]; then
  echo ""
  echo "[SKIP-DB] Skipping DB checks."
  echo ""
  echo "=== Results: $PASS_COUNT passed, $FAIL_COUNT failed, $WARN_COUNT warnings ==="
  if [[ "$FAIL_COUNT" -gt 0 ]]; then
    exit 1
  fi
  exit 0
fi

# Start Cloud SQL Proxy
echo ""
echo "[2/4] Starting Cloud SQL Proxy..."
PROXY_PID=""

cleanup_proxy() {
  if [[ -n "$PROXY_PID" ]]; then
    kill "$PROXY_PID" 2>/dev/null || true
    wait "$PROXY_PID" 2>/dev/null || true
  fi
}
trap cleanup_proxy EXIT

# Check if proxy is already running on the port
if lsof -i :"$PROXY_PORT" >/dev/null 2>&1; then
  echo "  Proxy already running on port $PROXY_PORT"
else
  cloud-sql-proxy "$INSTANCE" --port="$PROXY_PORT" &
  PROXY_PID=$!
  sleep 3
  if ! lsof -i :"$PROXY_PORT" >/dev/null 2>&1; then
    fail "Could not start Cloud SQL Proxy"
    echo "=== Results: $PASS_COUNT passed, $FAIL_COUNT failed, $WARN_COUNT warnings ==="
    exit 1
  fi
  pass "Cloud SQL Proxy started"
fi

# Get DB password
DB_PASS="$(gcloud secrets versions access latest --secret=DB_PASSWORD --project="$PROJECT_ID" 2>/dev/null)"
if [[ -z "$DB_PASS" ]]; then
  fail "Could not retrieve DB password from Secret Manager"
  echo "=== Results: $PASS_COUNT passed, $FAIL_COUNT failed, $WARN_COUNT warnings ==="
  exit 1
fi

# =============================================================================
# Check 3: Table existence
# =============================================================================

echo ""
echo "[3/4] Checking table existence..."

# Get all tables from production DB
PROD_TABLES="$(run_sql "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;")"

# Extract table names referenced in code (FROM/INTO/UPDATE/JOIN/CREATE TABLE)
CODE_TABLES="$(grep -rohn --include="*.py" \
  -E '(FROM|INTO|UPDATE|JOIN|CREATE TABLE IF NOT EXISTS|CREATE TABLE)\s+([a-z_]+)' \
  "$REPO_ROOT/lib/" "$REPO_ROOT/chatwork-webhook/" 2>/dev/null \
  | sed -E 's/.*(FROM|INTO|UPDATE|JOIN|CREATE TABLE IF NOT EXISTS|CREATE TABLE)\s+//' \
  | sed 's/[^a-z_].*//' \
  | sort -u \
  | grep -v -E '^(select|where|set|and|or|as|on|not|null|true|false|exists|if|in)$' \
  | grep -v -E '^.{0,2}$' || true)"

MISSING_TABLES=0
while IFS= read -r table; do
  [[ -z "$table" ]] && continue
  if ! echo "$PROD_TABLES" | grep -qx "$table"; then
    fail "Table missing in production: $table"
    MISSING_TABLES=$((MISSING_TABLES + 1))
  fi
done <<< "$CODE_TABLES"

if [[ "$MISSING_TABLES" -eq 0 ]]; then
  pass "All referenced tables exist in production"
else
  fail "$MISSING_TABLES table(s) missing in production DB"
fi

# =============================================================================
# Check 4: RLS policy check
# =============================================================================

echo ""
echo "[4/4] Checking RLS policies..."

# Get tables with organization_id column
TABLES_WITH_ORG_ID="$(run_sql "
  SELECT table_name
  FROM information_schema.columns
  WHERE column_name = 'organization_id'
    AND table_schema = 'public'
  ORDER BY table_name;
")"

# Get tables with RLS enabled
TABLES_WITH_RLS="$(run_sql "
  SELECT tablename
  FROM pg_tables
  WHERE schemaname = 'public' AND rowsecurity = true
  ORDER BY tablename;
")"

# Check: every table with org_id should have RLS
RLS_ISSUES=0
while IFS= read -r table; do
  [[ -z "$table" ]] && continue
  if ! echo "$TABLES_WITH_RLS" | grep -qx "$table"; then
    fail "RLS not enabled on table with organization_id: $table"
    RLS_ISSUES=$((RLS_ISSUES + 1))
  fi
done <<< "$TABLES_WITH_ORG_ID"

if [[ "$RLS_ISSUES" -eq 0 ]]; then
  pass "All tables with organization_id have RLS enabled"
fi

# Check RLS cast types match column types
echo "  Checking RLS cast type correctness..."
CAST_ISSUES=0

# Get policies with their qual expressions
POLICIES="$(run_sql "
  SELECT t.tablename, p.policyname, p.qual
  FROM pg_policies p
  JOIN pg_tables t ON t.tablename = p.tablename AND t.schemaname = p.schemaname
  WHERE t.schemaname = 'public'
    AND p.qual LIKE '%current_setting%organization_id%'
  ORDER BY t.tablename;
")"

while IFS='|' read -r table policy qual; do
  [[ -z "$table" ]] && continue
  table="$(echo "$table" | xargs)"
  # Get actual column type
  col_type="$(run_sql "
    SELECT udt_name FROM information_schema.columns
    WHERE table_name = '$table' AND column_name = 'organization_id' AND table_schema = 'public';
  " | xargs)"

  if [[ "$col_type" == "uuid" ]] && ! echo "$qual" | grep -q "::uuid"; then
    fail "RLS cast mismatch on $table: column is UUID but policy missing ::uuid cast"
    CAST_ISSUES=$((CAST_ISSUES + 1))
  elif [[ "$col_type" == "varchar" || "$col_type" == "text" ]] && echo "$qual" | grep -q "::uuid"; then
    fail "RLS cast mismatch on $table: column is $col_type but policy uses ::uuid (WILL CRASH)"
    CAST_ISSUES=$((CAST_ISSUES + 1))
  fi
done <<< "$POLICIES"

if [[ "$CAST_ISSUES" -eq 0 ]]; then
  pass "All RLS policy casts match column types"
fi

# Check for tables with RLS but no policy
echo "  Checking for RLS-enabled tables without policies..."
ORPHAN_RLS=0
while IFS= read -r table; do
  [[ -z "$table" ]] && continue
  policy_count="$(run_sql "SELECT count(*) FROM pg_policies WHERE tablename = '$table' AND schemaname = 'public';")"
  if [[ "$policy_count" -eq 0 ]]; then
    fail "RLS enabled but NO policy defined on: $table (all queries will return empty!)"
    ORPHAN_RLS=$((ORPHAN_RLS + 1))
  fi
done <<< "$TABLES_WITH_RLS"

if [[ "$ORPHAN_RLS" -eq 0 ]]; then
  pass "All RLS-enabled tables have policies"
fi

# =============================================================================
# Summary
# =============================================================================

echo ""
echo "==========================================="
echo -e "  Results: ${GREEN}$PASS_COUNT passed${NC}, ${RED}$FAIL_COUNT failed${NC}, ${YELLOW}$WARN_COUNT warnings${NC}"
echo "==========================================="
echo ""

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo -e "${RED}DEPLOY BLOCKED: Fix $FAIL_COUNT issue(s) before deploying.${NC}"
  exit 1
fi

if [[ "$WARN_COUNT" -gt 0 ]]; then
  echo -e "${YELLOW}DEPLOY OK with $WARN_COUNT warning(s). Review before deploying.${NC}"
  exit 0
fi

echo -e "${GREEN}DEPLOY OK: All checks passed.${NC}"
exit 0
