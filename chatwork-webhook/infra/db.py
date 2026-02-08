"""infra/db.py - DB接続・シークレット管理基盤

Phase 11-1a: main.pyから抽出されたDB接続プール・シークレット管理機能。
全モジュールの最下層に位置し、他のinfra/モジュールからも参照される。

提供する関数:
- get_pool(): Cloud SQL接続プール取得
- get_secret(): Secret Manager からシークレット取得
- get_db_connection(): DB接続取得
"""

from functools import lru_cache

from lib.db import get_db_pool as _lib_get_db_pool, get_db_connection as _lib_get_db_connection
from lib.secrets import get_secret_cached as _lib_get_secret
from lib.config import get_settings  # noqa: F401

# =====================================================
# プロジェクト定数
# =====================================================
PROJECT_ID = "soulkun-production"


def get_db_connection():
    """DB接続を取得"""
    return _lib_get_db_connection()


def get_pool():
    """Cloud SQL接続プールを取得"""
    return _lib_get_db_pool()


@lru_cache(maxsize=32)
def get_secret(secret_id):
    """Secret Managerからシークレットを取得（キャッシュ付き）"""
    return _lib_get_secret(secret_id)
