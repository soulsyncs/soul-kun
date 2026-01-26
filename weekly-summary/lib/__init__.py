"""
weekly-summary/lib - Cloud Functions用ローカルライブラリ

このディレクトリにはデプロイ時にsoul-kun/lib/からコピーされた
モジュールが配置されます。

v10.31.1: Phase D - 新規作成（接続設定集約）
"""

# =============================================================================
# Phase D: 接続設定集約（v10.31.1）
# =============================================================================
from .config import get_settings, Settings, settings
from .secrets import get_secret, get_secret_cached
from .db import (
    get_db_pool,
    get_db_connection,
    get_db_session,
    close_all_connections,
    health_check,
)

__all__ = [
    # Phase D: 接続設定集約
    "get_settings",
    "Settings",
    "settings",
    "get_secret",
    "get_secret_cached",
    "get_db_pool",
    "get_db_connection",
    "get_db_session",
    "close_all_connections",
    "health_check",
]
