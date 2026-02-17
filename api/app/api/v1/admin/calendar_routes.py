"""
Admin Dashboard - Google Calendar Integration Endpoints

Googleカレンダー連携状態取得、接続、コールバック、切断。
"""

import hashlib
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import log_audit_event

from .deps import (
    logger,
    get_current_user,
)
from app.schemas.admin import (
    GoogleCalendarStatusResponse,
    GoogleCalendarConnectResponse,
    GoogleCalendarDisconnectResponse,
)

router = APIRouter()

# OAuth設定（環境変数 or Secret Manager）
_GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
_GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
_GOOGLE_OAUTH_REDIRECT_URI = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URI",
    "",
)
_GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "openid",
    "email",
]
# トークン暗号化キー（Secret Manager推奨）
_TOKEN_ENCRYPTION_KEY = os.getenv("GOOGLE_OAUTH_ENCRYPTION_KEY", "")

# 管理画面URL（コールバック後のリダイレクト先）
_ADMIN_DASHBOARD_URL = os.getenv("ADMIN_DASHBOARD_URL", "https://admin.soulsyncs.jp")


def _encrypt_token(token: str) -> str:
    """トークンをAES暗号化する。キー未設定時は平文のまま返す（開発用）。"""
    if not _TOKEN_ENCRYPTION_KEY:
        return token
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_TOKEN_ENCRYPTION_KEY.encode() if len(_TOKEN_ENCRYPTION_KEY) == 44 else Fernet.generate_key())
        return f.encrypt(token.encode()).decode()
    except Exception:
        logger.warning("Token encryption failed, storing plaintext")
        return token


def _decrypt_token(encrypted: str) -> str:
    """暗号化トークンを復号する。キー未設定時はそのまま返す。"""
    if not _TOKEN_ENCRYPTION_KEY:
        return encrypted
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_TOKEN_ENCRYPTION_KEY.encode())
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        # 暗号化前のトークン or キー不一致
        return encrypted


@router.get(
    "/integrations/google-calendar/status",
    response_model=GoogleCalendarStatusResponse,
)
async def google_calendar_status(
    user=Depends(get_current_user),
):
    """Googleカレンダー連携状態を取得"""
    organization_id = user.organization_id
    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            conn.execute(text("SELECT set_config('app.current_organization_id', :org_id, true)"), {"org_id": organization_id})
            row = conn.execute(
                text("""
                    SELECT google_email, connected_at, token_expiry, is_active
                    FROM google_oauth_tokens
                    WHERE organization_id = :org_id
                      AND service_name = 'google_calendar'
                      AND is_active = TRUE
                    LIMIT 1
                """),
                {"org_id": organization_id},
            ).fetchone()

        if not row:
            return GoogleCalendarStatusResponse(is_connected=False)

        token_valid = row[2] > datetime.now(timezone.utc) if row[2] else False
        return GoogleCalendarStatusResponse(
            is_connected=True,
            google_email=row[0],
            connected_at=str(row[1]) if row[1] else None,
            token_valid=token_valid,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Google Calendar status error")
        raise HTTPException(status_code=500, detail="内部エラー")


@router.get(
    "/integrations/google-calendar/connect",
    response_model=GoogleCalendarConnectResponse,
)
async def google_calendar_connect(
    user=Depends(get_current_user),
):
    """GoogleカレンダーOAuth認可URLを生成"""
    if not _GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )

    import secrets
    import urllib.parse

    # CSRF対策: stateにorg_id + nonce + user_idを含める（署名付き）
    nonce = secrets.token_urlsafe(32)
    state_data = f"{user.organization_id}:{user.user_id}:{nonce}"

    # stateをHMAC署名（改ざん防止）
    import hmac
    secret_key = (_GOOGLE_OAUTH_CLIENT_SECRET or "fallback-key").encode()
    signature = hmac.new(secret_key, state_data.encode(), hashlib.sha256).hexdigest()[:16]
    state = f"{state_data}:{signature}"

    params = {
        "client_id": _GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": _GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(_GOOGLE_CALENDAR_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

    log_audit_event(
        logger=logger, action="google_calendar_connect_initiated",
        resource_type="integration", resource_id="google_calendar",
        user_id=user.user_id, details={"org_id": user.organization_id},
    )

    return GoogleCalendarConnectResponse(auth_url=auth_url)


@router.get("/integrations/google-calendar/callback")
async def google_calendar_callback(
    code: str = Query(...),
    state: str = Query(""),
):
    """GoogleからのOAuthコールバックを処理"""
    import httpx

    if not _GOOGLE_OAUTH_CLIENT_ID or not _GOOGLE_OAUTH_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="OAuth not configured")

    # state検証（CSRF対策）
    state_parts = state.split(":")
    if len(state_parts) != 4:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    org_id, user_id, nonce, provided_sig = state_parts

    # HMAC検証
    import hmac as hmac_mod
    secret_key = (_GOOGLE_OAUTH_CLIENT_SECRET or "fallback-key").encode()
    expected_data = f"{org_id}:{user_id}:{nonce}"
    expected_sig = hmac_mod.new(secret_key, expected_data.encode(), hashlib.sha256).hexdigest()[:16]

    if not hmac_mod.compare_digest(provided_sig, expected_sig):
        raise HTTPException(status_code=400, detail="State verification failed")

    # auth codeをトークンに交換
    async with httpx.AsyncClient(timeout=30) as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": _GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": _GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": _GOOGLE_OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )

    if token_response.status_code != 200:
        logger.error("Google token exchange failed: %d", token_response.status_code)
        raise HTTPException(status_code=502, detail="Token exchange failed")

    token_data = token_response.json()
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token or not refresh_token:
        raise HTTPException(status_code=502, detail="Incomplete token response")

    # ユーザー情報取得（google_email）
    google_email = None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            userinfo = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if userinfo.status_code == 200:
            google_email = userinfo.json().get("email")
    except Exception:
        pass  # email取得失敗は致命的ではない

    # トークンをDBに保存（暗号化）
    from datetime import timedelta as td
    token_expiry = datetime.now(timezone.utc) + td(seconds=expires_in)
    encrypted_access = _encrypt_token(access_token)
    encrypted_refresh = _encrypt_token(refresh_token)

    pool = get_db_pool()
    try:
        with pool.connect() as conn:
            conn.execute(text("SELECT set_config('app.current_organization_id', :org_id, true)"), {"org_id": org_id})
            conn.execute(
                text("""
                    INSERT INTO google_oauth_tokens
                        (organization_id, service_name, google_email,
                         access_token, refresh_token, token_expiry, scopes,
                         connected_by, connected_at, updated_at, is_active)
                    VALUES
                        (CAST(:org_id AS UUID), 'google_calendar', :email,
                         :access_token, :refresh_token, :expiry, :scopes,
                         CAST(:user_id AS UUID), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, TRUE)
                    ON CONFLICT (organization_id, service_name)
                    DO UPDATE SET
                        google_email = EXCLUDED.google_email,
                        access_token = EXCLUDED.access_token,
                        refresh_token = EXCLUDED.refresh_token,
                        token_expiry = EXCLUDED.token_expiry,
                        scopes = EXCLUDED.scopes,
                        connected_by = EXCLUDED.connected_by,
                        connected_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP,
                        is_active = TRUE
                """),
                {
                    "org_id": org_id,
                    "email": google_email,
                    "access_token": encrypted_access,
                    "refresh_token": encrypted_refresh,
                    "expiry": token_expiry,
                    "scopes": " ".join(_GOOGLE_CALENDAR_SCOPES),
                    "user_id": user_id,
                },
            )
            conn.commit()

        log_audit_event(
            logger=logger, action="google_calendar_connected",
            resource_type="integration", resource_id="google_calendar",
            user_id=user_id, details={"org_id": org_id},
        )

    except Exception as e:
        logger.exception("Failed to save Google OAuth tokens")
        raise HTTPException(status_code=500, detail="Token save failed")

    # 管理画面にリダイレクト
    redirect_url = f"{_ADMIN_DASHBOARD_URL}/integrations?connected=true"
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post(
    "/integrations/google-calendar/disconnect",
    response_model=GoogleCalendarDisconnectResponse,
)
async def google_calendar_disconnect(
    user=Depends(get_current_user),
):
    """Googleカレンダー連携を解除"""
    organization_id = user.organization_id
    pool = get_db_pool()

    try:
        # まずrefresh_tokenを取得してGoogleに失効通知
        with pool.connect() as conn:
            conn.execute(text("SELECT set_config('app.current_organization_id', :org_id, true)"), {"org_id": organization_id})
            row = conn.execute(
                text("""
                    SELECT refresh_token FROM google_oauth_tokens
                    WHERE organization_id = :org_id
                      AND service_name = 'google_calendar'
                      AND is_active = TRUE
                """),
                {"org_id": organization_id},
            ).fetchone()

        # Googleのトークン無効化エンドポイントを呼ぶ
        if row and row[0]:
            try:
                import httpx
                decrypted = _decrypt_token(row[0])
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": decrypted},
                    )
            except Exception:
                pass  # 失効通知失敗は致命的ではない

        # DBの接続を無効化
        with pool.connect() as conn:
            conn.execute(text("SELECT set_config('app.current_organization_id', :org_id, true)"), {"org_id": organization_id})
            conn.execute(
                text("""
                    UPDATE google_oauth_tokens
                    SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                    WHERE organization_id = :org_id
                      AND service_name = 'google_calendar'
                """),
                {"org_id": organization_id},
            )
            conn.commit()

        log_audit_event(
            logger=logger, action="google_calendar_disconnected",
            resource_type="integration", resource_id="google_calendar",
            user_id=user.user_id, details={"org_id": organization_id},
        )
        return GoogleCalendarDisconnectResponse()

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Google Calendar disconnect error")
        raise HTTPException(status_code=500, detail="内部エラー")
