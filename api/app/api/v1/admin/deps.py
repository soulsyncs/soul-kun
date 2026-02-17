"""
Admin Dashboard - Shared Dependencies

全adminルートファイルで共有する依存関数・定数・インポートを集約。
"""

import hashlib
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import get_logger, log_audit_event
from lib.text_utils import clean_chatwork_tags
from app.deps.auth import get_current_user, create_access_token, decode_jwt
from app.services.access_control import get_user_role_level_sync
from app.services.knowledge_search import UserContext

# Google OAuth Client ID（audience検証用）
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

# 管理者に必要な最低権限レベル
ADMIN_MIN_LEVEL = 5

# 編集権限（Level 6以上）
EDITOR_MIN_LEVEL = 6

# ソウルシンクス組織ID（シングルテナント）
DEFAULT_ORG_ID = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"

logger = get_logger(__name__)


def _escape_like(value: str) -> str:
    """ILIKE/LIKEメタ文字をエスケープする。"""
    return re.sub(r"([%_\\])", r"\\\1", value)


# =============================================================================
# 管理者権限チェック依存関数
# =============================================================================


def require_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
    """
    管理者権限（Level 5以上）を要求する依存関数。

    全ての/adminエンドポイントで使用する。
    JWTから取得したuser_idでDBの権限レベルを確認し、
    Level 5未満の場合は403を返す。

    Args:
        user: JWT認証済みユーザーコンテキスト

    Returns:
        UserContext: 認証・認可済みユーザーコンテキスト

    Raises:
        HTTPException(403): 権限レベル不足
    """
    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            role_level = get_user_role_level_sync(conn, user.user_id)
    except Exception as e:
        logger.error(
            "Failed to check admin permission",
            user_id=user.user_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "PERMISSION_CHECK_ERROR",
                "error_message": "権限確認中にエラーが発生しました",
            },
        )

    if role_level < ADMIN_MIN_LEVEL:
        logger.warning(
            "Admin access denied: insufficient role level",
            user_id=user.user_id,
            role_level=role_level,
            required_level=ADMIN_MIN_LEVEL,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "status": "failed",
                "error_code": "INSUFFICIENT_PERMISSION",
                "error_message": "管理者権限（Level 5以上）が必要です",
            },
        )

    return user


def require_editor(user: UserContext = Depends(get_current_user)) -> UserContext:
    """
    編集権限（Level 6以上 = 代表/CFO）を要求する依存関数。

    部署の作成/更新/削除、メンバー情報の更新など、
    書き込み操作を伴うエンドポイントで使用する。
    """
    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            role_level = get_user_role_level_sync(conn, user.user_id)
    except Exception as e:
        logger.error(
            "Failed to check editor permission",
            user_id=user.user_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "PERMISSION_CHECK_ERROR",
                "error_message": "権限確認中にエラーが発生しました",
            },
        )

    if role_level < EDITOR_MIN_LEVEL:
        logger.warning(
            "Editor access denied: insufficient role level",
            user_id=user.user_id,
            role_level=role_level,
            required_level=EDITOR_MIN_LEVEL,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "status": "failed",
                "error_code": "INSUFFICIENT_PERMISSION",
                "error_message": "編集権限（Level 6以上）が必要です",
            },
        )

    return user
