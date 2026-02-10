#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# validate_sql_columns.sh - SQLカラム参照をDBスキーマと照合
#
# git diff内のPythonファイルからSQL文を抽出し、
# db_schema.json と照合してカラム名の不一致を検出する。
#
# Usage:
#   scripts/validate_sql_columns.sh              # diff内の変更ファイルを検証
#   scripts/validate_sql_columns.sh --all        # lib/配下の全ファイルを検証
#   SCHEMA_FILE=path/to/schema.json scripts/validate_sql_columns.sh
#
# Exit codes:
#   0 = PASS (不一致なし)
#   1 = FAIL (不一致あり)
#   2 = SKIP (db_schema.json が存在しない)
# =============================================================================

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SCHEMA_FILE="${SCHEMA_FILE:-${REPO_ROOT}/db_schema.json}"

if [[ ! -f "$SCHEMA_FILE" ]]; then
  echo "⚠️  db_schema.json not found. Run 'scripts/dump_db_schema.sh' first."
  echo "   Skipping SQL column validation."
  exit 2
fi

# Check schema freshness (warn if older than 7 days)
SCHEMA_MAX_AGE_DAYS=7
if [[ "$(uname)" == "Darwin" ]]; then
  schema_mtime=$(stat -f%m "$SCHEMA_FILE")
else
  schema_mtime=$(stat -c%Y "$SCHEMA_FILE")
fi
now=$(date +%s)
schema_age_days=$(( (now - schema_mtime) / 86400 ))
if [[ "$schema_age_days" -ge "$SCHEMA_MAX_AGE_DAYS" ]]; then
  echo "⚠️  db_schema.json is ${schema_age_days} days old (max: ${SCHEMA_MAX_AGE_DAYS})."
  echo "   Run 'scripts/dump_db_schema.sh' to refresh."
  echo "   Continuing with stale schema (results may be inaccurate)."
  echo ""
fi

CHECK_ALL=0
if [[ "${1:-}" == "--all" ]]; then
  CHECK_ALL=1
fi

# Get Python files to check
if [[ "$CHECK_ALL" -eq 1 ]]; then
  FILES=$(find "$REPO_ROOT/lib" "$REPO_ROOT/chatwork-webhook" "$REPO_ROOT/proactive-monitor" -name '*.py' -not -path '*/test*' 2>/dev/null)
else
  # Get changed .py files from diff (committed changes vs origin/main)
  base_ref="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo 'origin/main')"
  FILES=$(git diff --name-only "$base_ref"...HEAD -- '*.py' 2>/dev/null || git diff --name-only HEAD -- '*.py' 2>/dev/null || true)
  # Also include staged files
  STAGED=$(git diff --cached --name-only -- '*.py' 2>/dev/null || true)
  FILES=$(printf "%s\n%s" "$FILES" "$STAGED" | sort -u | grep -v '^$' || true)

  if [[ -z "$FILES" ]]; then
    echo "✅ No Python files changed. Skipping SQL validation."
    exit 0
  fi
fi

# Run Python validator
python3 - "$SCHEMA_FILE" "$REPO_ROOT" "$CHECK_ALL" <<'PYTHON_SCRIPT' $FILES
import sys
import json
import re
import os

schema_file = sys.argv[1]
repo_root = sys.argv[2]
check_all = sys.argv[3] == "1"
files = sys.argv[4:]

# Load schema
with open(schema_file) as f:
    schema = json.load(f)
tables = schema["tables"]

# Known aliases/expressions to ignore (not real column names)
IGNORE_COLUMNS = {
    # SQL keywords/expressions
    "id", "true", "false", "null", "not", "and", "or", "as", "on",
    "is", "in", "set", "all", "asc", "desc", "case", "when", "then",
    "else", "end", "limit", "offset", "order", "by", "group", "having",
    "from", "where", "join", "left", "right", "inner", "outer", "cross",
    "select", "insert", "into", "update", "delete", "values", "exists",
    "between", "like", "ilike", "cast", "coalesce", "greatest",
    "current_timestamp", "now", "count", "sum", "avg", "min", "max",
    # Parameter placeholders
    "org_id", "user_id", "room_id", "message_id", "person_id",
    "learning_id", "limit", "query", "key", "value", "category",
    "date_start", "date_end", "now", "confidence", "source",
    "memory_id", "attr_type", "attr_value", "interval",
    "pid", "name", "updated_at", "processed_at",
}

# Extract SQL strings from Python source
def extract_sql_strings(content):
    """Extract SQL from text('...') and text(\"\"\"...\"\"\") patterns"""
    sqls = []
    # Triple-quoted strings after text( or sql_text(
    pattern = r'(?:text|sql_text)\s*\(\s*(?:f\s*)?"""(.*?)"""'
    for match in re.finditer(pattern, content, re.DOTALL):
        sql = match.group(1)
        # Strip f-string interpolation {variable} to avoid false positives
        sql = re.sub(r'\{[^}]+\}', '', sql)
        sqls.append(sql)
    # Single-quoted strings
    pattern2 = r'(?:text|sql_text)\s*\(\s*(?:f\s*)?"(.*?)"'
    for match in re.finditer(pattern2, content, re.DOTALL):
        sql = match.group(1)
        sql = re.sub(r'\{[^}]+\}', '', sql)
        sqls.append(sql)
    return sqls

def extract_insert_columns(sql):
    """Extract table and columns from INSERT INTO table (col1, col2, ...)"""
    results = []
    pattern = r'INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)'
    for match in re.finditer(pattern, sql, re.IGNORECASE):
        table = match.group(1).strip()
        cols = [c.strip() for c in match.group(2).split(',')]
        for col in cols:
            parts = col.strip().split()
            if not parts:
                continue
            col = parts[-1]  # Handle "col_name" vs just col
            col = re.sub(r'[^a-zA-Z0-9_]', '', col)
            if col and col.lower() not in IGNORE_COLUMNS:
                results.append((table, col))
    return results

def extract_select_columns(sql):
    """Extract table and columns from SELECT col1, col2 FROM table"""
    results = []
    # Find FROM clause to get table names
    from_match = re.search(r'\bFROM\s+(\w+)', sql, re.IGNORECASE)
    if not from_match:
        return results
    main_table = from_match.group(1).strip()

    # Build alias map: alias -> real table name
    alias_map = {main_table: main_table}
    # JOIN table alias ON ...
    for jm in re.finditer(r'JOIN\s+(\w+)\s+(\w+)\s+ON', sql, re.IGNORECASE):
        alias_map[jm.group(2)] = jm.group(1)
    # FROM table alias
    fm2 = re.search(r'\bFROM\s+(\w+)\s+(\w+)\s', sql, re.IGNORECASE)
    if fm2 and fm2.group(2).upper() not in ('WHERE', 'ORDER', 'GROUP', 'LIMIT', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'ON', 'AS'):
        alias_map[fm2.group(2)] = fm2.group(1)

    # Find qualified column references: table.column or alias.column
    for qm in re.finditer(r'\b(\w+)\.(\w+)\b', sql):
        prefix = qm.group(1)
        col = qm.group(2)
        if prefix in alias_map and col.lower() not in IGNORE_COLUMNS:
            real_table = alias_map[prefix]
            results.append((real_table, col))

    return results

def extract_where_columns(sql):
    """Extract column references from WHERE/AND/SET clauses"""
    results = []
    # table.column = or table.column ILIKE etc
    for wm in re.finditer(r'\b(\w+)\.(\w+)\s*(?:=|!=|<>|>=|<=|>|<|ILIKE|LIKE|IS|IN)\b', sql, re.IGNORECASE):
        prefix = wm.group(1)
        col = wm.group(2)
        if col.lower() not in IGNORE_COLUMNS:
            results.append((prefix, col))
    return results

def extract_cast_types(sql):
    """Extract CAST type mismatches: column = CAST(:param AS type)"""
    results = []
    # Pattern: table.column = CAST(:param AS type) or column = CAST(:param AS type)
    for cm in re.finditer(
        r'\b(\w+)\.(\w+)\s*=\s*CAST\s*\([^)]*\s+AS\s+(\w+)\)',
        sql, re.IGNORECASE
    ):
        table = cm.group(1)
        col = cm.group(2)
        cast_type = cm.group(3).lower()
        if col.lower() not in IGNORE_COLUMNS:
            results.append((table, col, cast_type))
    return results

# Map SQL CAST types to PostgreSQL actual types
CAST_TYPE_MAP = {
    'uuid': {'uuid'},
    'text': {'text', 'character varying', 'character', 'varchar'},
    'integer': {'integer', 'bigint', 'smallint', 'int'},
    'bigint': {'bigint', 'integer'},
    'boolean': {'boolean'},
    'date': {'date', 'timestamp without time zone', 'timestamp with time zone'},
    'timestamp': {'timestamp without time zone', 'timestamp with time zone'},
}

def validate_cast_type(table_name, column_name, cast_type, tables):
    """Check if CAST type is compatible with actual column type"""
    if table_name not in tables:
        return True, None  # Can't validate alias
    if column_name not in tables[table_name]:
        return True, None  # Column validation handled elsewhere
    actual_type = tables[table_name][column_name]
    compatible = CAST_TYPE_MAP.get(cast_type, set())
    if compatible and actual_type not in compatible:
        return False, f"CAST type mismatch: {table_name}.{column_name} is '{actual_type}' but CAST AS {cast_type}. These are incompatible."
    return True, None

def validate_column(table_name, column_name, tables):
    """Check if column exists in schema"""
    # Try exact table match
    if table_name in tables:
        if column_name in tables[table_name]:
            return True, None
        # Check for common aliases
        return False, f"Column '{column_name}' not found in table '{table_name}'. Available: {sorted(tables[table_name].keys())}"

    # Table might be an alias - can't validate
    return True, None

errors = []
checked_files = 0
checked_sqls = 0

for filepath in files:
    if not filepath.strip():
        continue
    full_path = filepath if os.path.isabs(filepath) else os.path.join(repo_root, filepath)
    if not os.path.exists(full_path):
        continue
    if '/test' in filepath or filepath.startswith('tests/'):
        continue

    try:
        with open(full_path) as f:
            content = f.read()
    except Exception:
        continue

    sqls = extract_sql_strings(content)
    if not sqls:
        continue

    checked_files += 1
    for sql in sqls:
        checked_sqls += 1
        refs = []
        refs.extend(extract_insert_columns(sql))
        refs.extend(extract_select_columns(sql))
        refs.extend(extract_where_columns(sql))

        for table, col in refs:
            ok, msg = validate_column(table, col, tables)
            if not ok:
                short_path = filepath.replace(repo_root + '/', '')
                errors.append(f"  {short_path}: {msg}")

        # CAST type validation
        cast_refs = extract_cast_types(sql)
        for table, col, cast_type in cast_refs:
            ok, msg = validate_cast_type(table, col, cast_type, tables)
            if not ok:
                short_path = filepath.replace(repo_root + '/', '')
                errors.append(f"  {short_path}: {msg}")

# Output results
if errors:
    # Deduplicate
    unique_errors = sorted(set(errors))
    print(f"❌ SQL Column Validation FAIL: {len(unique_errors)} issue(s) found")
    print()
    for err in unique_errors:
        print(err)
    print()
    print(f"Checked: {checked_files} files, {checked_sqls} SQL statements")
    sys.exit(1)
else:
    print(f"✅ SQL Column Validation PASS ({checked_files} files, {checked_sqls} SQL statements)")
    sys.exit(0)
PYTHON_SCRIPT
