#!/usr/bin/env python3
"""
雇用形態（employment_type）マイグレーション実行スクリプト
users テーブルに employment_type カラムを追加する。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from lib.db import get_db_pool


def run_migration():
    print("=" * 60)
    print("employment_type マイグレーション開始")
    print("=" * 60)

    migration_file = os.path.join(
        os.path.dirname(__file__),
        "20260220_employment_type.sql"
    )

    with open(migration_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    print(f"📄 マイグレーションファイル: {migration_file}")

    print("🔌 Cloud SQLに接続中...")
    pool = get_db_pool()

    with pool.connect() as conn:
        print("✅ 接続成功")
        print("🚀 マイグレーション実行中...")

        # 各SQL文を個別に実行
        statements = [s.strip() for s in sql_content.split(";") if s.strip() and not s.strip().startswith("--")]
        for stmt in statements:
            if stmt:
                conn.execute(text(stmt))
        conn.commit()

        print("✅ マイグレーション完了")

        # 確認クエリ
        result = conn.execute(text("""
            SELECT column_name, data_type, character_maximum_length, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'users'
              AND column_name = 'employment_type'
        """))
        row = result.fetchone()
        if row:
            print(f"✅ カラム確認: employment_type {row[1]}({row[2]}) NULLABLE={row[3]}")
        else:
            print("❌ カラムが見つかりません")


if __name__ == "__main__":
    run_migration()
