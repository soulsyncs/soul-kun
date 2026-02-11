"""
結合テスト用フィクスチャ

本物のPostgreSQLデータベースに接続してテストする。
TEST_DATABASE_URL 環境変数が設定されていない場合、全テストをスキップ。

CI環境: cloudbuild.yaml で Docker PostgreSQL コンテナを起動して接続。
ローカル: Cloud SQL Proxy (127.0.0.1:5432) または Docker Compose。

使い方:
  # ローカル（Cloud SQL Proxy起動済み）
  TEST_DATABASE_URL="postgresql+pg8000://soulkun_user:PASSWORD@127.0.0.1:5432/soulkun_tasks" \
    python3 -m pytest tests/integration/ -v

  # Docker Compose
  docker compose -f tests/integration/docker-compose.yml up -d
  TEST_DATABASE_URL="postgresql+pg8000://test_user:test_pass@localhost:15432/test_db" \
    python3 -m pytest tests/integration/ -v
"""

import os
import pytest
import sqlalchemy
from sqlalchemy import text
from sqlalchemy.pool import QueuePool


# TEST_DATABASE_URL が設定されていなければ全テストスキップ
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set. Integration tests require a real PostgreSQL database."
)


@pytest.fixture(scope="session")
def db_engine():
    """
    セッション全体で共有するDBエンジン（本番と同じ設定）

    本番の lib/db.py と同じプール設定を使用:
    - pool_size=5
    - max_overflow=2
    - pool_timeout=30
    - pool_recycle=1800
    - pool_pre_ping=True
    """
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")

    engine = sqlalchemy.create_engine(
        TEST_DATABASE_URL,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=2,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
    )

    yield engine

    engine.dispose()


@pytest.fixture(scope="session")
def setup_test_schema(db_engine):
    """
    テスト用の最小スキーマを作成（テストに必要なテーブルのみ）

    本番テーブルをそのまま使わず、テスト用テーブルを作成して
    テスト終了後にクリーンアップする。
    """
    with db_engine.connect() as conn:
        # テスト用テーブル作成
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS integration_test_table (
                id SERIAL PRIMARY KEY,
                organization_id VARCHAR(255) NOT NULL,
                name VARCHAR(255),
                value TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.commit()

    yield

    # クリーンアップ
    with db_engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS integration_test_table"))
        conn.commit()


@pytest.fixture
def db_conn(db_engine, setup_test_schema):
    """
    各テスト用のDB接続（テストごとにロールバック）
    """
    with db_engine.connect() as conn:
        # テスト前にクリーン
        conn.execute(text("DELETE FROM integration_test_table"))
        conn.commit()
        yield conn
