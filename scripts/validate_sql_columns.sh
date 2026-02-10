#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# validate_sql_columns.sh - SQLカラム参照をDBスキーマと照合
#
# git diff内のPythonファイルからSQL文を抽出し、
# db_schema.json と照合してカラム名の不一致を検出する。
#
# 対応SQL文: SELECT, INSERT, UPDATE SET, WHERE, JOIN ON
# 対応パターン: text(), sql_text(), sqlalchemy.text(), raw execute()
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

# Check schema freshness
# - 7 days: warning (results may be inaccurate)
# - 14 days: hard block (exit 1)
SCHEMA_WARN_DAYS=7
SCHEMA_BLOCK_DAYS=14
if [[ "$(uname)" == "Darwin" ]]; then
  schema_mtime=$(stat -f%m "$SCHEMA_FILE")
else
  schema_mtime=$(stat -c%Y "$SCHEMA_FILE")
fi
now=$(date +%s)
schema_age_days=$(( (now - schema_mtime) / 86400 ))
if [[ "$schema_age_days" -ge "$SCHEMA_BLOCK_DAYS" ]]; then
  echo "❌ db_schema.json is ${schema_age_days} days old (limit: ${SCHEMA_BLOCK_DAYS})."
  echo "   Run 'scripts/dump_db_schema.sh' to refresh."
  echo "   Validation BLOCKED: schema too stale for reliable checking."
  exit 1
elif [[ "$schema_age_days" -ge "$SCHEMA_WARN_DAYS" ]]; then
  echo "⚠️  db_schema.json is ${schema_age_days} days old (warn: ${SCHEMA_WARN_DAYS}, block: ${SCHEMA_BLOCK_DAYS})."
  echo "   Run 'scripts/dump_db_schema.sh' to refresh."
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

# =============================================================================
# Ignore lists (B-3 fix: separated SQL keywords from parameter placeholders)
# =============================================================================

# SQL keywords/functions - these are NEVER column names
SQL_KEYWORDS = {
    "true", "false", "null", "not", "and", "or", "as", "on",
    "is", "in", "set", "all", "asc", "desc", "case", "when", "then",
    "else", "end", "limit", "offset", "order", "by", "group", "having",
    "from", "where", "join", "left", "right", "inner", "outer", "cross",
    "select", "insert", "into", "update", "delete", "values", "exists",
    "between", "like", "ilike", "cast", "coalesce", "greatest", "least",
    "current_timestamp", "now", "count", "sum", "avg", "min", "max",
    "distinct", "returning", "conflict", "do", "nothing", "interval",
    "extract", "epoch", "date_trunc", "to_char", "lower", "upper",
    "trim", "length", "substring", "replace", "concat", "string_agg",
    "array_agg", "jsonb_build_object", "row_number", "over", "partition",
}

# Parameter placeholder names (appear as :param in SQL)
# Only ignored in unqualified context (not when table.column)
PARAM_PLACEHOLDERS = {
    "org_id", "user_id", "room_id", "message_id", "person_id",
    "learning_id", "query", "date_start", "date_end",
    "memory_id", "attr_type", "attr_value", "pid",
    "session_id", "chunk_id", "doc_id", "task_id", "goal_id",
}

def is_sql_keyword(col_name):
    """Check if a name is a SQL keyword (always ignore)"""
    return col_name.lower() in SQL_KEYWORDS

def is_param_placeholder(col_name):
    """Check if a name is a known parameter placeholder"""
    return col_name.lower() in PARAM_PLACEHOLDERS

def should_ignore(col_name, is_qualified=False):
    """Determine if a column reference should be ignored.

    Args:
        col_name: The column name
        is_qualified: True if this is a table.column reference (more reliable)
    """
    if is_sql_keyword(col_name):
        return True
    # Parameter placeholders are only ignored in unqualified context
    # If someone writes table.org_id, we should still validate it exists
    if not is_qualified and is_param_placeholder(col_name):
        return True
    return False


# =============================================================================
# SQL extraction (B-2 fix: added raw SQL patterns)
# =============================================================================

def extract_sql_strings(content):
    """Extract SQL from text()/sql_text()/sqlalchemy.text() and raw SQL strings"""
    sqls = []

    # Pattern 1: Triple-quoted strings after text( or sql_text(
    pattern = r'(?:text|sql_text)\s*\(\s*(?:f\s*)?"""(.*?)"""'
    for match in re.finditer(pattern, content, re.DOTALL):
        sql = match.group(1)
        sql = re.sub(r'\{[^}]+\}', '', sql)  # Strip f-string interpolation
        sqls.append(sql)

    # Pattern 2: Single-quoted strings after text( or sql_text(
    pattern2 = r'(?:text|sql_text)\s*\(\s*(?:f\s*)?"(.*?)"'
    for match in re.finditer(pattern2, content, re.DOTALL):
        sql = match.group(1)
        sql = re.sub(r'\{[^}]+\}', '', sql)
        sqls.append(sql)

    # Pattern 3: Raw SQL in triple-quoted strings passed to execute() without text()
    pattern3 = r'\.execute\s*\(\s*(?:f\s*)?"""(.*?)"""'
    for match in re.finditer(pattern3, content, re.DOTALL):
        sql = match.group(1)
        if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE)\b', sql, re.IGNORECASE):
            sql = re.sub(r'\{[^}]+\}', '', sql)
            sqls.append(sql)

    # Pattern 4: Raw SQL in single-quoted strings passed to execute()
    pattern4 = r'\.execute\s*\(\s*(?:f\s*)?"(.*?)"'
    for match in re.finditer(pattern4, content, re.DOTALL):
        sql = match.group(1)
        if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE)\b', sql, re.IGNORECASE):
            sql = re.sub(r'\{[^}]+\}', '', sql)
            sqls.append(sql)

    return sqls


# =============================================================================
# Alias map builder (B-6 fix: handles ALL FROM/JOIN clauses, not just first)
# =============================================================================

def build_alias_map(sql):
    """Build alias -> real table name map from all FROM/JOIN clauses in SQL"""
    alias_map = {}
    reserved = {'WHERE', 'ORDER', 'GROUP', 'LIMIT', 'JOIN', 'LEFT', 'RIGHT',
                'INNER', 'ON', 'AS', 'HAVING', 'UNION', 'EXCEPT', 'INTERSECT',
                'SET', 'INTO', 'VALUES', 'RETURNING', 'AND', 'OR', 'NOT',
                'CROSS', 'OUTER', 'FULL', 'NATURAL', 'USING', 'OFFSET',
                'FETCH', 'FOR', 'UPDATE', 'DELETE', 'INSERT', 'SELECT'}

    # All FROM table [AS] [alias] patterns
    for fm in re.finditer(r'\bFROM\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?', sql, re.IGNORECASE):
        table = fm.group(1)
        alias = fm.group(2)
        if table.upper() not in reserved:
            alias_map[table] = table
        if alias and alias.upper() not in reserved:
            alias_map[alias] = table

    # All JOIN table [AS] alias ON patterns
    for jm in re.finditer(r'JOIN\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?\s+ON', sql, re.IGNORECASE):
        table = jm.group(1)
        alias = jm.group(2)
        if table.upper() not in reserved:
            alias_map[table] = table
        if alias and alias.upper() not in reserved:
            alias_map[alias] = table

    # UPDATE table pattern
    for um in re.finditer(r'\bUPDATE\s+(\w+)\s+SET\b', sql, re.IGNORECASE):
        table = um.group(1)
        if table.upper() not in reserved:
            alias_map[table] = table

    return alias_map


# =============================================================================
# Column extraction from SQL
# =============================================================================

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
            col = parts[-1]
            col = re.sub(r'[^a-zA-Z0-9_]', '', col)
            if col and not should_ignore(col, is_qualified=False):
                results.append((table, col))
    return results


def strip_sql_comments(sql):
    """Strip SQL single-line comments (-- to end of line)"""
    return re.sub(r'--[^\n]*', '', sql)


def extract_update_set_columns(sql):
    """Extract table and columns from UPDATE table SET col1 = ..., col2 = ...

    B-1 fix: Previously UPDATE SET columns were not validated at all.
    """
    results = []
    # Strip SQL comments to prevent comment text bleeding into column names
    clean_sql = strip_sql_comments(sql)
    # Match UPDATE table SET ... WHERE (or RETURNING or end of string)
    # Use \s* instead of \s+ to handle f-string-stripped empty SET clauses
    update_match = re.search(
        r'UPDATE\s+(\w+)\s+SET\s*(.*?)(?:\s*\bWHERE\b|\s*\bRETURNING\b|\s*$)',
        clean_sql, re.IGNORECASE | re.DOTALL
    )
    if not update_match:
        # Also handle ON CONFLICT ... DO UPDATE SET
        conflict_match = re.search(
            r'DO\s+UPDATE\s+SET\s*(.*?)(?:\s*\bWHERE\b|\s*\bRETURNING\b|\s*$)',
            clean_sql, re.IGNORECASE | re.DOTALL
        )
        if not conflict_match:
            return results
        # For ON CONFLICT DO UPDATE SET, get table from INSERT INTO
        table_match = re.search(r'INSERT\s+INTO\s+(\w+)', clean_sql, re.IGNORECASE)
        if not table_match:
            return results
        table = table_match.group(1).strip()
        set_clause = conflict_match.group(1)
    else:
        table = update_match.group(1).strip()
        set_clause = update_match.group(2)

    # Extract column names from SET clause
    # Handle nested parens: SET col = COALESCE(:val, col), col2 = :val2
    depth = 0
    current_col = ""
    in_col = True
    for char in set_clause:
        if char == '(':
            depth += 1
            in_col = False
        elif char == ')':
            depth -= 1
        elif char == '=' and depth == 0 and in_col:
            col = current_col.strip()
            col = re.sub(r'[^a-zA-Z0-9_]', '', col)
            if col and not should_ignore(col, is_qualified=False):
                results.append((table, col))
            current_col = ""
            in_col = False
        elif char == ',' and depth == 0:
            current_col = ""
            in_col = True
        elif in_col:
            current_col += char

    return results


def extract_select_columns(sql):
    """Extract qualified table.column references using alias map"""
    results = []
    alias_map = build_alias_map(sql)
    if not alias_map:
        return results

    # Find qualified column references: prefix.column
    for qm in re.finditer(r'\b(\w+)\.(\w+)\b', sql):
        prefix = qm.group(1)
        col = qm.group(2)
        if prefix in alias_map and not should_ignore(col, is_qualified=True):
            real_table = alias_map[prefix]
            results.append((real_table, col))

    return results


def extract_where_columns(sql):
    """Extract qualified column references from WHERE/AND conditions"""
    results = []
    alias_map = build_alias_map(sql)

    for wm in re.finditer(r'\b(\w+)\.(\w+)\s*(?:=|!=|<>|>=|<=|>|<|ILIKE|LIKE|IS|IN)\b', sql, re.IGNORECASE):
        prefix = wm.group(1)
        col = wm.group(2)
        if not should_ignore(col, is_qualified=True):
            if prefix in alias_map:
                results.append((alias_map[prefix], col))
            else:
                results.append((prefix, col))
    return results


def extract_cast_types(sql):
    """Extract CAST type references for type compatibility checking"""
    results = []
    alias_map = build_alias_map(sql)

    for cm in re.finditer(
        r'\b(\w+)\.(\w+)\s*=\s*CAST\s*\([^)]*\s+AS\s+(\w+)\)',
        sql, re.IGNORECASE
    ):
        prefix = cm.group(1)
        col = cm.group(2)
        cast_type = cm.group(3).lower()
        if not should_ignore(col, is_qualified=True):
            table = alias_map.get(prefix, prefix)
            results.append((table, col, cast_type))
    return results


# =============================================================================
# Validation
# =============================================================================

CAST_TYPE_MAP = {
    'uuid': {'uuid'},
    'text': {'text', 'character varying', 'character', 'varchar'},
    'integer': {'integer', 'bigint', 'smallint', 'int'},
    'bigint': {'bigint', 'integer'},
    'boolean': {'boolean'},
    'date': {'date', 'timestamp without time zone', 'timestamp with time zone'},
    'timestamp': {'timestamp without time zone', 'timestamp with time zone'},
    'jsonb': {'jsonb', 'json'},
    'json': {'json', 'jsonb'},
}

def validate_cast_type(table_name, column_name, cast_type, tables):
    """Check if CAST type is compatible with actual column type"""
    if table_name not in tables:
        return True, None
    if column_name not in tables[table_name]:
        return True, None
    actual_type = tables[table_name][column_name]
    compatible = CAST_TYPE_MAP.get(cast_type, set())
    if compatible and actual_type not in compatible:
        return False, f"CAST type mismatch: {table_name}.{column_name} is '{actual_type}' but CAST AS {cast_type}"
    return True, None

def validate_column(table_name, column_name, tables):
    """Check if column exists in schema"""
    if table_name in tables:
        if column_name in tables[table_name]:
            return True, None
        return False, f"Column '{column_name}' not found in table '{table_name}'. Available: {sorted(tables[table_name].keys())}"
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
        refs.extend(extract_update_set_columns(sql))
        refs.extend(extract_select_columns(sql))
        refs.extend(extract_where_columns(sql))

        for table, col in refs:
            ok, msg = validate_column(table, col, tables)
            if not ok:
                short_path = filepath.replace(repo_root + '/', '')
                errors.append(f"  {short_path}: {msg}")

        cast_refs = extract_cast_types(sql)
        for table, col, cast_type in cast_refs:
            ok, msg = validate_cast_type(table, col, cast_type, tables)
            if not ok:
                short_path = filepath.replace(repo_root + '/', '')
                errors.append(f"  {short_path}: {msg}")

# Output results
if errors:
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
