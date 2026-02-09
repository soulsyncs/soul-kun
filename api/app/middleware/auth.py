# api/app/middleware/auth.py
"""
Phase 3.6: Firebase Authentication Middleware

組織図SaaS化のための認証基盤。
Firebase Authentication でJWTトークンを検証し、
テナント/組織スコープのアクセス制御を提供する。

設計書: docs/06_phase_3-5_org_hierarchy.md
CLAUDE.md §3 鉄則#4: APIは必ず認証必須
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# セキュリティスキーム
security = HTTPBearer()


# =========================================================================
# データモデル
# =========================================================================


class TenantRole(str, Enum):
    """テナント内の役割"""
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


@dataclass
class AuthenticatedUser:
    """認証済みユーザー情報"""
    firebase_uid: str
    email: str
    display_name: Optional[str] = None
    tenant_id: Optional[str] = None
    organization_id: Optional[str] = None
    role: TenantRole = TenantRole.VIEWER


# =========================================================================
# トークン検証
# =========================================================================


async def verify_firebase_token(token: str) -> dict:
    """
    Firebase IDトークンを検証する

    Args:
        token: Firebase ID Token (JWT)

    Returns:
        デコード済みトークンのペイロード

    Raises:
        HTTPException: トークンが無効な場合
    """
    # TODO Phase 3.6: Firebase Admin SDK でトークン検証
    # from firebase_admin import auth
    # decoded = auth.verify_id_token(token)
    # return decoded
    raise HTTPException(
        status_code=501,
        detail="Firebase authentication not yet implemented",
    )


# =========================================================================
# 依存性注入用関数
# =========================================================================


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = None,
) -> AuthenticatedUser:
    """
    FastAPI Depends用: 現在の認証済みユーザーを取得

    Usage:
        @app.get("/api/v1/org-chart")
        async def get_org_chart(user: AuthenticatedUser = Depends(get_current_user)):
            ...

    Args:
        request: FastAPIリクエスト
        credentials: Bearerトークン

    Returns:
        AuthenticatedUser

    Raises:
        HTTPException 401: 未認証
        HTTPException 403: 権限不足
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="認証が必要です")

    token_data = await verify_firebase_token(credentials.credentials)

    return AuthenticatedUser(
        firebase_uid=token_data.get("uid", ""),
        email=token_data.get("email", ""),
        display_name=token_data.get("name"),
    )


async def require_role(
    user: AuthenticatedUser,
    required_role: TenantRole,
) -> None:
    """
    指定された役割以上の権限を要求する

    Args:
        user: 認証済みユーザー
        required_role: 必要な役割

    Raises:
        HTTPException 403: 権限不足
    """
    role_hierarchy = {
        TenantRole.VIEWER: 0,
        TenantRole.EDITOR: 1,
        TenantRole.ADMIN: 2,
        TenantRole.OWNER: 3,
    }

    user_level = role_hierarchy.get(user.role, 0)
    required_level = role_hierarchy.get(required_role, 0)

    if user_level < required_level:
        logger.warning(
            "Permission denied: user role=%s, required=%s",
            user.role.value, required_role.value,
        )
        raise HTTPException(
            status_code=403,
            detail=f"この操作には{required_role.value}以上の権限が必要です",
        )
