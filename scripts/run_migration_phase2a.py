#!/usr/bin/env python3
"""Phase 2-A マイグレーション実行（Cloud Build環境で実行）"""
import os
import sys

sys.path.insert(0, '/workspace')

from lib.db import get_db_pool
from sqlalchemy import text

sql = open('/workspace/migrations/20260221_form_employee_tables.sql').read()

# Split statements (pg8000 requires one at a time)
def split_sql(sql_content):
    statements = []
    current = []
    for line in sql_content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('--') and not current:
            continue
        current.append(line)
        if stripped.endswith(';'):
            stmt = '\n'.join(current).strip().rstrip(';').strip()
            if stmt and not all(l.strip().startswith('--') for l in stmt.split('\n') if l.strip()):
                statements.append(stmt)
            current = []
    return statements

pool = get_db_pool()
statements = split_sql(sql)

print(f"Total statements: {len(statements)}")

with pool.connect() as conn:
    for i, stmt in enumerate(statements):
        if not stmt.strip():
            continue
        try:
            conn.execute(text(stmt))
            first_line = stmt.split('\n')[0][:80]
            print(f"✅ {i+1}/{len(statements)}: {first_line}")
        except Exception as e:
            print(f"❌ {i+1}/{len(statements)} FAILED: {e}")
            print(f"   SQL: {stmt[:200]}")
            sys.exit(1)
    conn.commit()

print("✅ Phase 2-A migration complete!")

# Verify tables exist
with pool.connect() as conn:
    result = conn.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN (
            'supabase_employee_mapping',
            'form_employee_skills',
            'form_employee_work_prefs',
            'form_employee_contact_prefs'
        )
        ORDER BY table_name
    """))
    tables = [row[0] for row in result]
    print(f"✅ Verified tables: {tables}")
    if len(tables) == 4:
        print("✅ All 4 tables created successfully!")
    else:
        print(f"⚠️  Expected 4 tables, found {len(tables)}: {tables}")
