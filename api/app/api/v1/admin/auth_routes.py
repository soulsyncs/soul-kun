"""
Admin Dashboard - Authentication Endpoints

Google認証、トークンログイン、ログアウト、ユーザー情報取得。
"""

import hashlib
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.limiter import limiter
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import log_audit_event

from .deps import (
    ADMIN_MIN_LEVEL,
    DEFAULT_ORG_ID,
    GOOGLE_CLIENT_ID,
    logger,
    require_admin,
    get_current_user,
    create_access_token,
    decode_jwt,
    get_user_role_level_sync,
    UserContext,
)
from app.schemas.admin import (
    GoogleAuthRequest,
    TokenLoginRequest,
    AuthTokenResponse,
    AuthMeResponse,
    AdminErrorResponse,
)

router = APIRouter()


@router.post(
    "/auth/google",
    response_model=AuthTokenResponse,
    responses={
        401: {"model": AdminErrorResponse, "description": "認証失敗"},
        403: {"model": AdminErrorResponse, "description": "権限不足"},
    },
    summary="Google認証によるログイン",
    description="""
Google ID Tokenを検証し、ユーザーが存在しかつ権限レベル5以上であればJWTを発行する。

## フロー
1. Google ID Tokenの署名検証
2. emailでusersテーブルを検索
3. ユーザー存在確認 + 権限レベル5以上を確認
4. JWTアクセストークンを発行
    """,
)
@limiter.limit("10/minute")
async def auth_google(request: Request, body: GoogleAuthRequest):
    """Google ID Tokenを検証してJWTを発行"""

    # 0. GOOGLE_CLIENT_IDが未設定なら即エラー（3AIレビュー MEDIUM-5）
    if not GOOGLE_CLIENT_ID:
        logger.error("GOOGLE_CLIENT_ID not configured — auth disabled")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "CONFIG_ERROR",
                "error_message": "認証が設定されていません",
            },
        )

    # 1. Google ID Tokenの検証（audience必須: 3AI合意 CRITICAL-1）
    try:
        idinfo = google_id_token.verify_oauth2_token(
            body.id_token,
            google_requests.Request(),
            audience=GOOGLE_CLIENT_ID if GOOGLE_CLIENT_ID else None,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status": "failed",
                "error_code": "INVALID_GOOGLE_TOKEN",
                "error_message": "Google ID Tokenが無効です",
            },
        )

    email = idinfo.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status": "failed",
                "error_code": "NO_EMAIL_IN_TOKEN",
                "error_message": "トークンにメールアドレスが含まれていません",
            },
        )

    # 2. ユーザー検索（org_idフィルタ: 3AI合意 CRITICAL-3）
    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, organization_id, name
                    FROM users
                    WHERE email = :email
                      AND organization_id = :expected_org_id
                    LIMIT 1
                """),
                {"email": email, "expected_org_id": DEFAULT_ORG_ID},
            )
            user_row = result.fetchone()

            if not user_row:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "status": "failed",
                        "error_code": "USER_NOT_FOUND",
                        "error_message": "登録されていないユーザーです",
                    },
                )

            user_id = str(user_row[0])
            organization_id = str(user_row[1])

            # 3. 権限レベルチェック
            role_level = get_user_role_level_sync(conn, user_id)

            if role_level < ADMIN_MIN_LEVEL:
                logger.warning(
                    "Admin Google auth denied: insufficient role level",
                    email_hash=hashlib.sha256(email.encode()).hexdigest()[:12],
                    role_level=role_level,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "status": "failed",
                        "error_code": "INSUFFICIENT_PERMISSION",
                        "error_message": "管理者権限（Level 5以上）が必要です",
                    },
                )

            # 4. department_id取得（user_idで既にorg_idスコープ済み）
            dept_result = conn.execute(
                text("""
                    SELECT department_id
                    FROM user_departments
                    WHERE user_id = :user_id
                      AND ended_at IS NULL
                    LIMIT 1
                """),
                {"user_id": user_id},
            )
            dept_row = dept_result.fetchone()
            department_id = str(dept_row[0]) if dept_row and dept_row[0] else None

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Google auth DB error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )

    # 5. JWT発行
    expires_minutes = 480  # 8時間
    token = create_access_token(
        user_id=user_id,
        organization_id=organization_id,
        department_id=department_id,
        role="admin",
        expires_minutes=expires_minutes,
    )

    log_audit_event(
        logger=logger,
        action="admin_google_auth",
        resource_type="auth",
        resource_id=user_id,
        user_id=user_id,
        details={"method": "google", "role_level": role_level},
    )

    # JWTをレスポンスボディ + httpOnly cookieで返す
    response = JSONResponse(content={
        "status": "success",
        "token_type": "bearer",
        "expires_in": expires_minutes * 60,
        "access_token": token,
    })
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=os.getenv("ENVIRONMENT") == "production",
        samesite="strict",
        max_age=expires_minutes * 60,
        path="/api/v1/admin",
    )
    return response


@router.post(
    "/auth/token-login",
    response_model=AuthTokenResponse,
    responses={
        401: {"model": AdminErrorResponse, "description": "無効なトークン"},
        403: {"model": AdminErrorResponse, "description": "権限不足"},
    },
    summary="トークンによるログイン（暫定認証）",
    description="""
CLIで生成したJWTトークンを検証し、httpOnly cookieにセットする。
Google OAuth Client ID未設定時の暫定認証手段。

## セキュリティ
- JWTの署名・有効期限を検証
- DBでユーザー存在確認 + organization_idフィルタ
- 権限レベル5以上を確認
    """,
)
@limiter.limit("10/minute")
async def auth_token_login(request: Request, body: TokenLoginRequest):
    """CLIで発行したJWTを検証してcookieにセット"""

    # 1. JWT検証（署名・有効期限・必須claims）
    payload = decode_jwt(body.token)
    user_id = payload.get("sub")
    org_id = payload.get("org_id")

    # 2. DBでユーザー存在確認（org_idフィルタ: 鉄則#1）
    pool = get_db_pool()
    try:
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, organization_id
                    FROM users
                    WHERE id::text = :user_id
                      AND organization_id = :org_id
                    LIMIT 1
                """),
                {"user_id": user_id, "org_id": org_id},
            )
            user_row = result.fetchone()

            if not user_row:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "status": "failed",
                        "error_code": "USER_NOT_FOUND",
                        "error_message": "登録されていないユーザーです",
                    },
                )

            # 3. 権限レベルチェック
            role_level = get_user_role_level_sync(conn, user_id)
            if role_level < ADMIN_MIN_LEVEL:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "status": "failed",
                        "error_code": "INSUFFICIENT_PERMISSION",
                        "error_message": "管理者権限（Level 5以上）が必要です",
                    },
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Token login DB error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )

    log_audit_event(
        logger=logger,
        action="admin_token_login",
        resource_type="auth",
        resource_id=user_id,
        user_id=user_id,
        details={"method": "token", "role_level": role_level},
    )

    # httpOnly cookieでトークンをセット
    expires_in = payload.get("exp", 0) - payload.get("iat", 0)
    response = JSONResponse(content={
        "status": "success",
        "token_type": "bearer",
        "expires_in": max(expires_in, 3600),
    })
    response.set_cookie(
        key="access_token",
        value=body.token,
        httponly=True,
        secure=os.getenv("ENVIRONMENT") == "production",
        samesite="strict",
        max_age=max(expires_in, 3600),
        path="/api/v1/admin",
    )
    return response


@router.post(
    "/auth/logout",
    summary="ログアウト",
    description="httpOnly cookieを削除してセッションを終了する。",
)
async def auth_logout(
    user: UserContext = Depends(get_current_user),
):
    """cookieをクリアしてログアウト（認証済みユーザーのみ）"""
    log_audit_event(
        logger=logger,
        action="admin_logout",
        user_id=user.user_id,
    )
    response = JSONResponse(content={"status": "success"})
    response.delete_cookie(
        key="access_token",
        path="/api/v1/admin",
        httponly=True,
        secure=os.getenv("ENVIRONMENT") == "production",
        samesite="strict",
    )
    return response


@router.get(
    "/auth/me",
    response_model=AuthMeResponse,
    responses={
        401: {"model": AdminErrorResponse, "description": "認証失敗"},
        403: {"model": AdminErrorResponse, "description": "権限不足"},
    },
    summary="現在のユーザー情報取得",
    description="JWT Tokenから現在のユーザー情報と権限レベルを返す。",
)
async def auth_me(user: UserContext = Depends(require_admin)):
    """現在のユーザー情報を返す"""

    organization_id = user.organization_id
    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT u.name, u.email,
                           COALESCE(MAX(r.level), 2) as role_level,
                           MAX(r.name) as role_name,
                           MAX(ud.department_id::text) as department_id
                    FROM users u
                    LEFT JOIN user_departments ud
                        ON u.id = ud.user_id AND ud.ended_at IS NULL
                    LEFT JOIN roles r
                        ON ud.role_id = r.id
                    WHERE u.id = :user_id
                      AND u.organization_id = :org_id
                    GROUP BY u.id, u.name, u.email
                """),
                {"user_id": user.user_id, "org_id": organization_id},
            )
            row = result.fetchone()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "status": "failed",
                        "error_code": "USER_NOT_FOUND",
                        "error_message": "ユーザーが見つかりません",
                    },
                )

            return AuthMeResponse(
                user_id=user.user_id,
                organization_id=organization_id,
                name=row[0],
                email=row[1],
                role_level=row[2] if row[2] else 2,
                role=row[3],
                department_id=str(row[4]) if row[4] else None,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Auth me error",
            user_id=user.user_id,
            organization_id=organization_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )
