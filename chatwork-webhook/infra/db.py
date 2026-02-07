"""infra/db.py - DB接続・シークレット管理基盤

Phase 11-1a: main.pyから抽出されたDB接続プール・シークレット管理機能。
全モジュールの最下層に位置し、他のinfra/モジュールからも参照される。

提供する関数:
- get_pool(): Cloud SQL接続プール取得
- get_secret(): Secret Manager からシークレット取得
- get_connector(): Cloud SQL Connector取得
- get_db_connection(): DB接続取得（pg8000）
- get_db_password(): DBパスワード取得
"""

from google.cloud import secretmanager
import pg8000  # noqa: F401 (get_db_connection fallback)
import sqlalchemy
from google.cloud.sql.connector import Connector
from functools import lru_cache

# =====================================================
# プロジェクト定数
# =====================================================
PROJECT_ID = "soulkun-production"

# =====================================================
# v10.31.1: Phase D - 接続設定集約
# =====================================================
try:
    from lib.db import get_db_pool as _lib_get_db_pool, get_db_connection as _lib_get_db_connection
    from lib.secrets import get_secret_cached as _lib_get_secret
    from lib.config import get_settings  # noqa: F401
    USE_LIB_DB = True
except ImportError:
    USE_LIB_DB = False

# Cloud SQL設定（フォールバック用）
if not USE_LIB_DB:
    INSTANCE_CONNECTION_NAME = "soulkun-production:asia-northeast1:soulkun-db"
    DB_NAME = "soulkun_tasks"
    DB_USER = "soulkun_user"

# Cloud SQL接続プール
_pool = None
_connector = None


def get_connector():
    """グローバルConnectorを取得（接続リーク防止）"""
    global _connector
    if _connector is None:
        _connector = Connector()
    return _connector


def get_db_connection():
    """DB接続を取得"""
    if USE_LIB_DB:
        return _lib_get_db_connection()
    else:
        connector = get_connector()
        conn = connector.connect(
            INSTANCE_CONNECTION_NAME,
            "pg8000",
            user=DB_USER,
            password=get_db_password(),
            db=DB_NAME,
        )
        return conn


def get_db_password():
    return get_secret("cloudsql-password")


def get_pool():
    """Cloud SQL接続プールを取得"""
    if USE_LIB_DB:
        return _lib_get_db_pool()
    else:
        global _pool
        if _pool is None:
            connector = get_connector()
            def getconn():
                return connector.connect(
                    INSTANCE_CONNECTION_NAME, "pg8000",
                    user=DB_USER, password=get_db_password(), db=DB_NAME,
                )
            _pool = sqlalchemy.create_engine(
                "postgresql+pg8000://", creator=getconn,
                pool_size=5, max_overflow=2, pool_timeout=30, pool_recycle=1800,
            )
        return _pool


@lru_cache(maxsize=32)
def get_secret(secret_id):
    """Secret Managerからシークレットを取得（キャッシュ付き）"""
    if USE_LIB_DB:
        return _lib_get_secret(secret_id)
    else:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
