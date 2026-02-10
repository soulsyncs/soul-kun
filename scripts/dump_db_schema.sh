#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# dump_db_schema.sh - 本番DBスキーマをJSONでダンプ
#
# 用途: validate_sql_columns.sh や Codex レビューで参照するスキーマ情報を生成
# 出力: db_schema.json（リポジトリルート）
#
# Usage:
#   scripts/dump_db_schema.sh              # 通常実行（Proxy自動起動）
#   scripts/dump_db_schema.sh --use-proxy  # 既存Proxyを使用
#
# Env:
#   PROXY_PORT=15432
#   PROJECT_ID=soulkun-production
#   INSTANCE=soulkun-production:asia-northeast1:soulkun-db
#   SCHEMA_OUTPUT=db_schema.json
# =============================================================================

PROXY_PORT="${PROXY_PORT:-15432}"
PROJECT_ID="${PROJECT_ID:-soulkun-production}"
INSTANCE="${INSTANCE:-soulkun-production:asia-northeast1:soulkun-db}"
DB_USER="${DB_USER:-soulkun_user}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SCHEMA_OUTPUT="${SCHEMA_OUTPUT:-${REPO_ROOT}/db_schema.json}"

PROXY_PID=""

cleanup_proxy() {
  if [[ -n "$PROXY_PID" ]]; then
    kill "$PROXY_PID" 2>/dev/null || true
    wait "$PROXY_PID" 2>/dev/null || true
  fi
}
trap cleanup_proxy EXIT

# Start proxy if not already running
if lsof -i :"$PROXY_PORT" >/dev/null 2>&1; then
  echo "Proxy already running on port $PROXY_PORT"
else
  echo "Starting Cloud SQL Proxy..."
  cloud-sql-proxy "$INSTANCE" --port="$PROXY_PORT" &
  PROXY_PID=$!
  sleep 3
  if ! lsof -i :"$PROXY_PORT" >/dev/null 2>&1; then
    echo "ERROR: Could not start Cloud SQL Proxy" >&2
    exit 1
  fi
fi

# Get DB password
DB_PASS="$(gcloud secrets versions access latest --secret=DB_PASSWORD --project="$PROJECT_ID" 2>/dev/null)"
if [[ -z "$DB_PASS" ]]; then
  echo "ERROR: Could not retrieve DB password" >&2
  exit 1
fi

run_sql() {
  local db="$1"
  local sql="$2"
  PGPASSWORD="$DB_PASS" psql -h 127.0.0.1 -p "$PROXY_PORT" -U "$DB_USER" -d "$db" -t -A -c "$sql" 2>/dev/null
}

echo "Dumping schema from soulkun and soulkun_tasks..."

# Dump schema from both databases as JSON
# Format: {"database.table": {"column_name": "data_type", ...}, ...}
python3 -c "
import subprocess, json, sys

def get_columns(db):
    sql = '''
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    '''
    cmd = [
        'psql', '-h', '127.0.0.1', '-p', '${PROXY_PORT}',
        '-U', '${DB_USER}', '-d', db,
        '-t', '-A', '-F', '|', '-c', sql
    ]
    env = dict(__import__('os').environ)
    env['PGPASSWORD'] = '''${DB_PASS}'''
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(f'Warning: Could not query {db}: {result.stderr}', file=sys.stderr)
        return {}

    tables = {}
    for line in result.stdout.strip().split('\n'):
        if not line or '|' not in line:
            continue
        parts = line.split('|')
        if len(parts) < 4:
            continue
        table, col, dtype, nullable = parts[0], parts[1], parts[2], parts[3]
        key = f'{db}.{table}'
        if key not in tables:
            tables[key] = {}
        tables[key][col] = {
            'type': dtype,
            'nullable': nullable == 'YES'
        }
    return tables

schema = {}
for db in ['soulkun', 'soulkun_tasks']:
    schema.update(get_columns(db))

# Also create a simplified lookup: table_name -> {col: type}
# (without db prefix, for easier matching in validation)
simple = {}
for full_key, cols in schema.items():
    table = full_key.split('.', 1)[1]
    if table not in simple:
        simple[table] = {}
    # Merge columns (soulkun_tasks takes priority if both have same table)
    simple[table].update({c: v['type'] for c, v in cols.items()})

output = {
    'generated_at': __import__('datetime').datetime.now().isoformat(),
    'databases': schema,
    'tables': simple,
}
print(json.dumps(output, indent=2, ensure_ascii=False))
" > "$SCHEMA_OUTPUT"

table_count=$(python3 -c "import json; d=json.load(open('${SCHEMA_OUTPUT}')); print(len(d['tables']))")
echo "Done: ${table_count} tables dumped to ${SCHEMA_OUTPUT}"
