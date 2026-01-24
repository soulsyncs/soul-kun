#!/usr/bin/env python3
"""
Phase 2.5 v1.6 マイグレーション実行スクリプト
目標設定対話機能のテーブルを作成

使用方法:
    python migrations/run_migration.py
"""

import os
import sys

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

# lib/ の共通モジュールを使用
from lib.db import get_db_pool


def run_migration():
    """マイグレーションを実行"""
    print("=" * 60)
    print("Phase 2.5 v1.6 マイグレーション開始")
    print("=" * 60)

    # SQLファイルを読み込み
    migration_file = os.path.join(
        os.path.dirname(__file__),
        "20260124_goal_setting_tables.sql"
    )

    with open(migration_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    print(f"📄 マイグレーションファイル: {migration_file}")
    print()

    # DB接続
    print("🔌 Cloud SQLに接続中...")
    pool = get_db_pool()

    with pool.connect() as conn:
        print("✅ 接続成功")
        print()

        # トランザクション内で実行
        print("🚀 マイグレーション実行中...")

        # SQLを実行（複数のステートメントを分割して実行）
        # pg8000は複数ステートメントを一度に実行できないため、分割する
        statements = []
        current_statement = []
        in_function = False
        in_do_block = False

        for line in sql_content.split('\n'):
            # コメント行をスキップ（ただし関数内のコメントは保持）
            stripped = line.strip()

            # 関数定義の開始/終了を検出
            if 'CREATE OR REPLACE FUNCTION' in line or 'CREATE FUNCTION' in line:
                in_function = True
            if 'DO $$' in line:
                in_do_block = True

            current_statement.append(line)

            # 関数定義の終了を検出
            if in_function and stripped == '$$ LANGUAGE plpgsql;':
                in_function = False
                statements.append('\n'.join(current_statement))
                current_statement = []
            elif in_do_block and stripped == 'END $$;':
                in_do_block = False
                statements.append('\n'.join(current_statement))
                current_statement = []
            elif not in_function and not in_do_block and stripped.endswith(';') and stripped != ';':
                statements.append('\n'.join(current_statement))
                current_statement = []

        # 各ステートメントを実行
        executed_count = 0
        error_count = 0

        for i, stmt in enumerate(statements):
            stmt = stmt.strip()
            if not stmt or stmt.startswith('--'):
                continue

            try:
                conn.execute(text(stmt))
                conn.commit()
                executed_count += 1

                # 主要なステートメントをログ出力
                if 'CREATE TABLE' in stmt:
                    table_name = stmt.split('CREATE TABLE')[1].split('(')[0].strip().replace('IF NOT EXISTS ', '')
                    print(f"  ✅ テーブル作成: {table_name}")
                elif 'CREATE INDEX' in stmt:
                    pass  # インデックスは省略
                elif 'INSERT INTO' in stmt:
                    table_name = stmt.split('INSERT INTO')[1].split('(')[0].strip()
                    print(f"  ✅ 初期データ投入: {table_name}")
                elif 'CREATE OR REPLACE VIEW' in stmt:
                    view_name = stmt.split('CREATE OR REPLACE VIEW')[1].split(' AS')[0].strip()
                    print(f"  ✅ ビュー作成: {view_name}")
                elif 'CREATE OR REPLACE FUNCTION' in stmt:
                    func_name = stmt.split('CREATE OR REPLACE FUNCTION')[1].split('(')[0].strip()
                    print(f"  ✅ 関数作成: {func_name}")
                elif 'CREATE TRIGGER' in stmt:
                    trigger_name = stmt.split('CREATE TRIGGER')[1].split('\n')[0].strip()
                    print(f"  ✅ トリガー作成: {trigger_name}")

            except Exception as e:
                error_msg = str(e)
                # トランザクションをロールバック
                conn.rollback()
                # 既に存在するエラーは無視（ロールバック後にcontinue）
                if 'already exists' in error_msg or 'duplicate key' in error_msg:
                    continue
                else:
                    print(f"  ⚠️ エラー: {error_msg[:200]}")
                    error_count += 1
                    # 致命的なエラーの場合、ステートメントの一部を表示
                    if '42P01' in error_msg:  # relation does not exist
                        print(f"     SQLの一部: {stmt[:150]}...")

        print()
        print("=" * 60)
        print(f"✅ マイグレーション完了")
        print(f"   実行: {executed_count} ステートメント")
        if error_count > 0:
            print(f"   エラー: {error_count} 件")
        print("=" * 60)

        # 確認クエリ
        print()
        print("📊 作成されたテーブルの確認:")

        tables_to_check = [
            'goal_setting_sessions',
            'goal_setting_patterns',
            'goal_setting_logs'
        ]

        for table in tables_to_check:
            result = conn.execute(text(f"""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = '{table}'
            """)).fetchone()

            if result and result[0] > 0:
                # レコード数も確認
                count_result = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()
                print(f"  ✅ {table}: 存在 ({count_result[0]} レコード)")
            else:
                print(f"  ❌ {table}: 存在しません")

        # パターンマスタの内容を表示
        print()
        print("📋 パターンマスタの内容:")
        patterns = conn.execute(text("""
            SELECT pattern_code, pattern_name, pattern_category
            FROM goal_setting_patterns
            ORDER BY pattern_category, pattern_code
        """)).fetchall()

        for pattern in patterns:
            print(f"  - {pattern[0]}: {pattern[1]} ({pattern[2]})")


if __name__ == "__main__":
    run_migration()
