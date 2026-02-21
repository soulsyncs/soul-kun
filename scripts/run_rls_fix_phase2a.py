#!/usr/bin/env python3
"""Phase 2-A RLSポリシー修正（brain-reviewer W1+W2対応）"""
import os, sys
sys.path.insert(0, '/workspace')
from lib.db import get_db_pool
from sqlalchemy import text

sql = open('/workspace/migrations/20260221_form_employee_tables_rls_fix.sql').read()

# Split by semicolon, strip leading comment lines from each chunk
def clean_stmt(s):
    lines = [l for l in s.split('\n') if not l.strip().startswith('--')]
    return '\n'.join(lines).strip()

statements = [clean_stmt(s) for s in sql.split(';') if clean_stmt(s)]

pool = get_db_pool()
with pool.connect() as conn:
    for i, stmt in enumerate(statements):
        if not stmt.strip():
            continue
        try:
            conn.execute(text(stmt))
            print(f"✅ {i+1}: {stmt.split(chr(10))[0][:70]}")
        except Exception as e:
            print(f"❌ {i+1} FAILED: {e}")
            sys.exit(1)
    conn.commit()
print("✅ RLS fix applied!")
