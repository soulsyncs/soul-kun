"""api/app/deps/auth.py - JWT認証依存モジュール

Task 1-2: CLAUDE.md 鉄則#4「APIは必ず認証必須」に準拠。
Bearer tokenからユーザーコンテキストを取得する。
"""

import os
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.services.knowledge_search import UserContext

# JWT設定
JWT_SECRET_KEY = os.getenv("SOULKUN_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"

_bearer_scheme = HTTPBearer(auto_error=False)

# 遅延初期化キャッシュ（Cold Start後の環境変数設定に対応）
_cached_secret: Optional[str] = None


def _get_jwt_secret() -> str:
    """JWT秘密鍵を取得。環境変数→Secret Manager の優先順位。

    遅延評価: Cloud Run Cold Start後に環境変数が設定されるケースに対応。
    一度取得した秘密鍵はキャッシュする。
    """
    global _cached_secret
    if _cached_secret:
        return _cached_secret

    # 環境変数を毎回チェック（モジュールレベルのキャッシュに依存しない）
    secret = os.getenv("SOULKUN_JWT_SECRET", "") or JWT_SECRET_KEY
    if secret:
        _cached_secret = secret
        return secret

    # Secret Managerからのフォールバック（デプロイ時に設定）
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        project_id = os.getenv("GCP_PROJECT_ID", "")
        if not project_id:
            raise ValueError("GCP_PROJECT_ID not set")
        name = f"projects/{project_id}/secrets/SOULKUN_JWT_SECRET/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret = response.payload.data.decode("utf-8")
        _cached_secret = secret
        return secret
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to retrieve JWT secret: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT secret key is not configured",
        )


def decode_jwt(token: str) -> dict:
    """JWTトークンをデコード・検証する。

    Args:
        token: Bearer token文字列

    Returns:
        dict: JWT claims (sub, org_id, dept_id, role, exp, iat)

    Raises:
        HTTPException: トークンが無効・期限切れの場合
    """
    secret = _get_jwt_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 必須claimsの検証
    if not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required claim: sub",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not payload.get("org_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required claim: org_id",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> UserContext:
    """JWT Bearer tokenからユーザーコンテキストを取得する。

    Claims:
        sub: user_id (UUID)
        org_id: organization_id (UUID)
        dept_id: department_id (UUID, optional)
        role: admin|manager|member (optional)

    Returns:
        UserContext: 認証済みユーザーコンテキスト

    Raises:
        HTTPException(401): トークンなし/無効/期限切れ
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_jwt(credentials.credentials)

    # roleに応じたアクセス可能な機密区分を設定
    role = payload.get("role", "member")
    if role in ("admin", "executive"):
        accessible_classifications = ["public", "internal", "confidential", "restricted"]
    elif role in ("manager", "leader"):
        accessible_classifications = ["public", "internal", "confidential"]
    else:
        accessible_classifications = ["public", "internal"]

    dept_id = payload.get("dept_id")

    return UserContext(
        user_id=payload["sub"],
        organization_id=payload["org_id"],
        department_id=dept_id,
        accessible_classifications=accessible_classifications,
        accessible_department_ids=[dept_id] if dept_id else [],
    )


def create_access_token(
    user_id: str,
    organization_id: str,
    department_id: Optional[str] = None,
    role: str = "member",
    expires_minutes: int = 60,
) -> str:
    """JWTアクセストークンを生成する（テスト・内部利用）。

    Args:
        user_id: ユーザーID
        organization_id: 組織ID
        department_id: 部署ID（オプション）
        role: ロール（admin, manager, member）
        expires_minutes: 有効期限（分）

    Returns:
        str: JWT token
    """
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_id,
        "org_id": organization_id,
        "role": role,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=expires_minutes),
    }
    if department_id:
        payload["dept_id"] = department_id

    secret = _get_jwt_secret()
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)
