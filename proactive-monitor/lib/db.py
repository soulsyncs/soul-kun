"""
データベース接続モジュール

Flask（sync）とFastAPI（async）の両方に対応したDB接続を提供。

使用例（Flask/Cloud Functions - 同期）:
    from lib.db import get_db_pool, get_db_connection

    # SQLAlchemy コネクションプール
    pool = get_db_pool()
    with pool.connect() as conn:
        result = conn.execute(text("SELECT 1"))

    # 直接接続（レガシー互換）
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1")
    conn.close()

使用例（FastAPI - 非同期）:
    from lib.db import get_async_db_pool

    pool = await get_async_db_pool()
    async with pool.connect() as conn:
        result = await conn.execute(text("SELECT 1"))

Phase 4対応:
    - コネクションプールサイズを設定で制御（100インスタンス対応）
    - テナントコンテキストの自動設定（Row Level Security準備）
    - 接続の自動リサイクル（30分）
"""

import threading
from typing import Optional, TYPE_CHECKING
from contextlib import contextmanager

import sqlalchemy
from sqlalchemy import text
from sqlalchemy.pool import QueuePool

# v10.31.4: 相対インポートに変更（googleapiclient警告修正）
from .config import get_settings
from .secrets import get_secret_cached

if TYPE_CHECKING:
    from google.cloud.sql.connector import Connector

# グローバル変数（スレッドセーフ）
_connector: Optional["Connector"] = None
_connector_lock = threading.Lock()

_sync_pool: Optional[sqlalchemy.Engine] = None
_sync_pool_lock = threading.Lock()


def _get_connector() -> "Connector":
    """
    Cloud SQL Connector を取得（シングルトン）

    Cloud Run/Functions 環境でのみ使用。
    ローカル開発時は DB_HOST 経由で直接接続するため不要。
    """
    global _connector
    if _connector is None:
        with _connector_lock:
            if _connector is None:
                # 遅延インポート（ローカル開発時はインストール不要）
                from google.cloud.sql.connector import Connector
                _connector = Connector()
    return _connector


def _get_db_password() -> str:
    """
    DBパスワードを取得
    """
    return get_secret_cached("cloudsql-password")


def get_db_pool() -> sqlalchemy.Engine:
    """
    SQLAlchemy コネクションプールを取得（同期版）

    Cloud Functions / Flask 用の同期コネクションプール。
    アプリケーション全体で1つのプールを共有。

    ローカル開発時は DB_HOST 環境変数で直接接続。
    Cloud Run/Functions では Cloud SQL Connector を使用。

    Returns:
        sqlalchemy.Engine: コネクションプール

    使用例:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(text("SELECT * FROM users"))
            for row in result:
                print(row)
            conn.commit()
    """
    global _sync_pool

    if _sync_pool is None:
        with _sync_pool_lock:
            if _sync_pool is None:
                settings = get_settings()

                # ローカル開発時は直接接続
                if settings.DB_HOST:
                    db_url = (
                        f"postgresql+pg8000://{settings.DB_USER}:"
                        f"{_get_db_password()}@{settings.DB_HOST}:"
                        f"{settings.DB_PORT}/{settings.DB_NAME}"
                    )
                    _sync_pool = sqlalchemy.create_engine(
                        db_url,
                        poolclass=QueuePool,
                        pool_size=settings.DB_POOL_SIZE,
                        max_overflow=settings.DB_MAX_OVERFLOW,
                        pool_timeout=settings.DB_POOL_TIMEOUT,
                        pool_recycle=settings.DB_POOL_RECYCLE,
                        pool_pre_ping=True,
                    )
                else:
                    # Cloud Run/Functions では Cloud SQL Connector を使用
                    connector = _get_connector()

                    def getconn():
                        return connector.connect(
                            settings.INSTANCE_CONNECTION_NAME,
                            "pg8000",
                            user=settings.DB_USER,
                            password=_get_db_password(),
                            db=settings.DB_NAME,
                        )

                    _sync_pool = sqlalchemy.create_engine(
                        "postgresql+pg8000://",
                        creator=getconn,
                        poolclass=QueuePool,
                        pool_size=settings.DB_POOL_SIZE,
                        max_overflow=settings.DB_MAX_OVERFLOW,
                        pool_timeout=settings.DB_POOL_TIMEOUT,
                        pool_recycle=settings.DB_POOL_RECYCLE,
                        pool_pre_ping=True,
                    )

    return _sync_pool


def get_db_connection():
    """
    直接DB接続を取得（レガシー互換）

    既存の main.py との互換性のため。
    新規コードでは get_db_pool() を使用すること。

    Returns:
        pg8000 Connection オブジェクト

    注意:
        呼び出し側で conn.close() を必ず呼ぶこと。
    """
    settings = get_settings()
    connector = _get_connector()

    return connector.connect(
        settings.INSTANCE_CONNECTION_NAME,
        "pg8000",
        user=settings.DB_USER,
        password=_get_db_password(),
        db=settings.DB_NAME,
    )


@contextmanager
def get_db_session():
    """
    DBセッションをコンテキストマネージャーで取得

    使用例:
        with get_db_session() as conn:
            result = conn.execute(text("SELECT 1"))
            conn.commit()
        # 自動的にクローズ
    """
    pool = get_db_pool()
    conn = pool.connect()
    try:
        yield conn
    finally:
        conn.close()


# =============================================================================
# 非同期版（FastAPI用）
# Phase 3.5 以降で使用
# =============================================================================

_async_pool: Optional[object] = None
_async_pool_lock = threading.Lock()


async def get_async_db_pool():
    """
    SQLAlchemy 非同期コネクションプールを取得

    FastAPI 用の非同期コネクションプール。
    asyncpg を使用した高速な非同期接続。

    Returns:
        sqlalchemy.ext.asyncio.AsyncEngine

    使用例:
        pool = await get_async_db_pool()
        async with pool.connect() as conn:
            result = await conn.execute(text("SELECT * FROM users"))
            rows = result.fetchall()
    """
    global _async_pool

    if _async_pool is None:
        with _async_pool_lock:
            if _async_pool is None:
                # 遅延インポート（FastAPI環境でのみ使用）
                from sqlalchemy.ext.asyncio import create_async_engine

                settings = get_settings()

                # Cloud SQL への直接接続URL
                # Cloud Run では Cloud SQL Proxy 経由で接続
                if settings.DB_HOST:
                    url = (
                        f"postgresql+asyncpg://{settings.DB_USER}:"
                        f"{_get_db_password()}@{settings.DB_HOST}:"
                        f"{settings.DB_PORT}/{settings.DB_NAME}"
                    )
                else:
                    # Cloud Run/Functions環境ではUnixソケット経由
                    socket_path = (
                        f"/cloudsql/{settings.INSTANCE_CONNECTION_NAME}"
                    )
                    url = (
                        f"postgresql+asyncpg://{settings.DB_USER}:"
                        f"{_get_db_password()}@/{settings.DB_NAME}"
                        f"?host={socket_path}"
                    )

                _async_pool = create_async_engine(
                    url,
                    pool_size=settings.DB_POOL_SIZE,
                    max_overflow=settings.DB_MAX_OVERFLOW,
                    pool_timeout=settings.DB_POOL_TIMEOUT,
                    pool_recycle=settings.DB_POOL_RECYCLE,
                    pool_pre_ping=True,
                )

    return _async_pool


async def get_async_db_session():
    """
    非同期DBセッションを取得

    FastAPI の Depends() で使用するジェネレーター。

    使用例（FastAPI）:
        from fastapi import Depends
        from lib.db import get_async_db_session

        @app.get("/users")
        async def get_users(db = Depends(get_async_db_session)):
            result = await db.execute(text("SELECT * FROM users"))
            return result.fetchall()
    """
    pool = await get_async_db_pool()
    async with pool.connect() as conn:
        yield conn


# =============================================================================
# テナント対応（Phase 4準備）
# =============================================================================

def set_tenant_context(conn, tenant_id: str) -> None:
    """
    接続にテナントコンテキストを設定

    Phase 4 の Row Level Security で使用。
    PostgreSQL の SET 変数でテナントIDを設定し、
    RLS ポリシーがこの値を参照する。

    Args:
        conn: DBコネクション
        tenant_id: テナント（組織）ID

    使用例:
        with get_db_session() as conn:
            set_tenant_context(conn, "org_soulsyncs")
            # 以降のクエリは自動的にテナントでフィルタ
            result = conn.execute(text("SELECT * FROM tasks"))
    """
    conn.execute(
        text("SET app.current_tenant = :tenant_id"),
        {"tenant_id": tenant_id}
    )


async def set_tenant_context_async(conn, tenant_id: str) -> None:
    """
    非同期版: 接続にテナントコンテキストを設定
    """
    await conn.execute(
        text("SET app.current_tenant = :tenant_id"),
        {"tenant_id": tenant_id}
    )


# =============================================================================
# ユーティリティ
# =============================================================================

def close_all_connections() -> None:
    """
    全てのコネクションプールを閉じる

    アプリケーション終了時やテスト後のクリーンアップに使用。
    """
    global _sync_pool, _async_pool, _connector

    if _sync_pool is not None:
        _sync_pool.dispose()
        _sync_pool = None

    if _async_pool is not None:
        # 非同期プールの場合は別途 await が必要
        pass

    if _connector is not None:
        _connector.close()
        _connector = None


def health_check() -> bool:
    """
    DB接続のヘルスチェック

    Returns:
        True: 接続成功
        False: 接続失敗
    """
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"DB Health Check failed: {e}")
        return False
