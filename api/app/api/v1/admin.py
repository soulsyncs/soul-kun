"""
Admin Dashboard API

管理ダッシュボード用APIエンドポイント。
認証、KPIサマリー、Brain分析、コスト管理、メンバー管理を提供。

セキュリティ:
    - 全エンドポイントにJWT認証必須
    - 権限レベル5以上（管理部/取締役/代表）のみアクセス可能
    - 全クエリにorganization_idフィルタ（鉄則#1）
    - SQLは全てパラメータ化（鉄則#9）
    - PII（個人情報）は集計値のみ返却、生メッセージは返さない
"""

import hashlib
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import get_logger, log_audit_event
from app.deps.auth import get_current_user, create_access_token, decode_jwt
from app.services.access_control import get_user_role_level_sync
from app.services.knowledge_search import UserContext

# Google OAuth Client ID（audience検証用）
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")


def _escape_like(value: str) -> str:
    """ILIKE/LIKEメタ文字をエスケープする。"""
    return re.sub(r"([%_\\])", r"\\\1", value)
from app.schemas.admin import (
    # Auth
    GoogleAuthRequest,
    TokenLoginRequest,
    AuthTokenResponse,
    AuthMeResponse,
    # Dashboard
    DashboardSummaryResponse,
    DashboardKPIs,
    AlertSummary,
    InsightSummary,
    # Brain
    BrainMetricsResponse,
    BrainDailyMetric,
    BrainLogsResponse,
    BrainLogEntry,
    # Costs
    CostMonthlyResponse,
    CostMonthlyEntry,
    CostDailyResponse,
    CostDailyEntry,
    CostBreakdownResponse,
    CostModelBreakdown,
    CostTierBreakdown,
    # Members
    MembersListResponse,
    MemberResponse,
    # Errors
    AdminErrorResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])
logger = get_logger(__name__)

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

# 管理者に必要な最低権限レベル
ADMIN_MIN_LEVEL = 5

# ソウルシンクス組織ID（シングルテナント）
DEFAULT_ORG_ID = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"


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


# =============================================================================
# 認証エンドポイント
# =============================================================================


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
async def auth_google(request: GoogleAuthRequest):
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
            request.id_token,
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

            # 4. department_id取得（org_idフィルタ追加: 3AI合意 MEDIUM-2）
            dept_result = conn.execute(
                text("""
                    SELECT department_id
                    FROM user_departments
                    WHERE user_id = :user_id
                      AND organization_id = :org_id
                      AND ended_at IS NULL
                    LIMIT 1
                """),
                {"user_id": user_id, "org_id": organization_id},
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

    # httpOnly cookieでJWTを返す（3AI合意 CRITICAL-2）
    response = JSONResponse(content={
        "status": "success",
        "token_type": "bearer",
        "expires_in": expires_minutes * 60,
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
async def auth_token_login(request: TokenLoginRequest):
    """CLIで発行したJWTを検証してcookieにセット"""

    # 1. JWT検証（署名・有効期限・必須claims）
    payload = decode_jwt(request.token)
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
        value=request.token,
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


# =============================================================================
# ダッシュボードエンドポイント
# =============================================================================


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummaryResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="ダッシュボードKPIサマリー取得",
    description="""
全KPIを1リクエストで返すバッチエンドポイント。

## データソース
- ai_usage_logs: 会話数、応答時間、エラー率、コスト
- ai_monthly_cost_summary: 月間予算
- bottleneck_alerts: アクティブアラート数

## パラメータ
- period: 集計期間（today/7d/30d）
    """,
)
async def get_dashboard_summary(
    period: str = Query(
        "today",
        pattern="^(today|7d|30d)$",
        description="集計期間（today/7d/30d）",
    ),
    user: UserContext = Depends(require_admin),
):
    """ダッシュボードKPIサマリーを取得"""

    organization_id = user.organization_id
    now = datetime.now(JST)

    # 集計期間の計算
    if period == "today":
        start_date = now.date()
    elif period == "7d":
        start_date = (now - timedelta(days=7)).date()
    else:  # 30d
        start_date = (now - timedelta(days=30)).date()

    logger.info(
        "Get dashboard summary",
        organization_id=organization_id,
        period=period,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # --- KPI: 会話数・平均応答時間・エラー率・コスト ---
            usage_result = conn.execute(
                text("""
                    SELECT
                        COUNT(*) as total_conversations,
                        COALESCE(AVG(response_time_ms), 0) as avg_response_time_ms,
                        CASE
                            WHEN COUNT(*) > 0
                            THEN COALESCE(SUM(CASE WHEN is_error = TRUE THEN 1 ELSE 0 END)::float / COUNT(*), 0)
                            ELSE 0
                        END as error_rate,
                        COALESCE(SUM(cost_usd), 0) as total_cost
                    FROM ai_usage_logs
                    WHERE organization_id = :org_id
                      AND created_at >= :start_date
                """),
                {"org_id": organization_id, "start_date": start_date},
            )
            usage_row = usage_result.fetchone()

            total_conversations = int(usage_row[0]) if usage_row else 0
            avg_response_time_ms = float(usage_row[1]) if usage_row else 0.0
            error_rate = float(usage_row[2]) if usage_row else 0.0
            total_cost = float(usage_row[3]) if usage_row else 0.0

            # --- 今日のコスト（period問わず常にtodayを返す） ---
            today_cost_result = conn.execute(
                text("""
                    SELECT COALESCE(SUM(cost_usd), 0) as cost_today
                    FROM ai_usage_logs
                    WHERE organization_id = :org_id
                      AND created_at >= :today
                """),
                {"org_id": organization_id, "today": now.date()},
            )
            today_cost_row = today_cost_result.fetchone()
            cost_today = float(today_cost_row[0]) if today_cost_row else 0.0

            # --- 月間予算残 ---
            current_month = now.strftime("%Y-%m")
            budget_result = conn.execute(
                text("""
                    SELECT
                        COALESCE(budget_usd, 0) as budget,
                        COALESCE(total_cost_usd, 0) as spent
                    FROM ai_monthly_cost_summary
                    WHERE organization_id = :org_id
                      AND year_month = :year_month
                    LIMIT 1
                """),
                {"org_id": organization_id, "year_month": current_month},
            )
            budget_row = budget_result.fetchone()
            if budget_row:
                monthly_budget_remaining = float(budget_row[0]) - float(budget_row[1])
            else:
                monthly_budget_remaining = 0.0

            # --- アクティブアラート数 ---
            alerts_count_result = conn.execute(
                text("""
                    SELECT COUNT(*) as active_count
                    FROM bottleneck_alerts
                    WHERE organization_id::text = :org_id
                      AND status = 'active'
                """),
                {"org_id": organization_id},
            )
            alerts_count_row = alerts_count_result.fetchone()
            active_alerts_count = int(alerts_count_row[0]) if alerts_count_row else 0

            # --- 最近のアラート（最大5件） ---
            recent_alerts_result = conn.execute(
                text("""
                    SELECT id, bottleneck_type, risk_level, target_name, created_at, status
                    FROM bottleneck_alerts
                    WHERE organization_id::text = :org_id
                    ORDER BY created_at DESC
                    LIMIT 5
                """),
                {"org_id": organization_id},
            )
            recent_alerts = []
            for row in recent_alerts_result.fetchall():
                recent_alerts.append(
                    AlertSummary(
                        id=str(row[0]),
                        alert_type=row[1] or "unknown",
                        severity=row[2] or "info",
                        message=row[3] or "",
                        created_at=row[4],
                        is_resolved=(row[5] != "active") if row[5] else False,
                    )
                )

            # --- 最近のインサイト（最大5件） ---
            recent_insights_result = conn.execute(
                text("""
                    SELECT id, insight_type, title, summary, created_at
                    FROM brain_insights
                    WHERE organization_id = :org_id
                    ORDER BY created_at DESC
                    LIMIT 5
                """),
                {"org_id": organization_id},
            )
            recent_insights = []
            for row in recent_insights_result.fetchall():
                recent_insights.append(
                    InsightSummary(
                        id=str(row[0]),
                        insight_type=row[1] or "general",
                        title=row[2] or "",
                        summary=row[3] or "",
                        created_at=row[4],
                    )
                )

        # 監査ログ
        log_audit_event(
            logger=logger,
            action="get_dashboard_summary",
            resource_type="dashboard",
            resource_id=organization_id,
            user_id=user.user_id,
            details={"period": period},
        )

        return DashboardSummaryResponse(
            status="success",
            period=period,
            kpis=DashboardKPIs(
                total_conversations=total_conversations,
                avg_response_time_ms=round(avg_response_time_ms, 2),
                error_rate=round(error_rate, 4),
                total_cost_today=round(cost_today, 4),
                monthly_budget_remaining=round(monthly_budget_remaining, 4),
                active_alerts_count=active_alerts_count,
            ),
            recent_alerts=recent_alerts,
            recent_insights=recent_insights,
            generated_at=now,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get dashboard summary error",
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


# =============================================================================
# Brain分析エンドポイント
# =============================================================================


@router.get(
    "/brain/metrics",
    response_model=BrainMetricsResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="Brain日次メトリクス取得",
    description="""
Brain決定ログから日次メトリクス（時系列）を返す。

## 集計内容
- 会話数、平均レイテンシ、エラー率、コスト（日次）
- brain_decision_logsとai_usage_logsから集計

## パラメータ
- days: 集計日数（7/14/30）
    """,
)
async def get_brain_metrics(
    days: int = Query(
        7,
        ge=1,
        le=90,
        description="集計日数（デフォルト7日）",
    ),
    user: UserContext = Depends(require_admin),
):
    """Brain日次メトリクスを取得"""

    organization_id = user.organization_id
    now = datetime.now(JST)
    start_date = (now - timedelta(days=days)).date()

    logger.info(
        "Get brain metrics",
        organization_id=organization_id,
        days=days,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        DATE(created_at) as metric_date,
                        COUNT(*) as conversations,
                        COALESCE(AVG(total_time_ms), 0) as avg_latency_ms,
                        CASE
                            WHEN COUNT(*) > 0
                            THEN COALESCE(
                                SUM(CASE WHEN selected_action = 'error' THEN 1 ELSE 0 END)::float
                                / COUNT(*), 0
                            )
                            ELSE 0
                        END as error_rate,
                        COALESCE(SUM(cost_usd), 0) as cost
                    FROM brain_decision_logs
                    WHERE organization_id = :org_id
                      AND created_at >= :start_date
                    GROUP BY DATE(created_at)
                    ORDER BY DATE(created_at) ASC
                """),
                {"org_id": organization_id, "start_date": start_date},
            )
            rows = result.fetchall()

        metrics = []
        for row in rows:
            metrics.append(
                BrainDailyMetric(
                    date=row[0],
                    conversations=int(row[1]),
                    avg_latency_ms=round(float(row[2]), 2),
                    error_rate=round(float(row[3]), 4),
                    cost=round(float(row[4]), 6),
                )
            )

        log_audit_event(
            logger=logger,
            action="get_brain_metrics",
            resource_type="brain",
            resource_id=organization_id,
            user_id=user.user_id,
            details={"days": days, "data_points": len(metrics)},
        )

        return BrainMetricsResponse(
            status="success",
            days=days,
            metrics=metrics,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get brain metrics error",
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


@router.get(
    "/brain/logs",
    response_model=BrainLogsResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="Brain決定ログ取得（PII除去済み）",
    description="""
最近のBrain決定ログを返す（ページネーション対応）。

## PII保護
- user_messageフィールドは返却しない
- id, created_at, selected_action, confidence, total_time_msのみ

## パラメータ
- limit: 取得件数（デフォルト50、最大200）
- offset: オフセット
    """,
)
async def get_brain_logs(
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description="取得件数（最大200）",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="オフセット",
    ),
    user: UserContext = Depends(require_admin),
):
    """Brain決定ログを取得（PII除去済み）"""

    organization_id = user.organization_id

    logger.info(
        "Get brain logs",
        organization_id=organization_id,
        limit=limit,
        offset=offset,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # ログ取得（user_messageは取得しない - PII保護）
            result = conn.execute(
                text("""
                    SELECT
                        id,
                        created_at,
                        selected_action,
                        decision_confidence,
                        total_time_ms
                    FROM brain_decision_logs
                    WHERE organization_id = :org_id
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"org_id": organization_id, "limit": limit, "offset": offset},
            )
            rows = result.fetchall()

            # 総件数カウント
            count_result = conn.execute(
                text("""
                    SELECT COUNT(*) as total
                    FROM brain_decision_logs
                    WHERE organization_id = :org_id
                """),
                {"org_id": organization_id},
            )
            total_count = int(count_result.fetchone()[0])

        logs = []
        for row in rows:
            logs.append(
                BrainLogEntry(
                    id=str(row[0]),
                    created_at=row[1],
                    selected_action=row[2] or "unknown",
                    decision_confidence=float(row[3]) if row[3] is not None else None,
                    total_time_ms=float(row[4]) if row[4] is not None else None,
                )
            )

        log_audit_event(
            logger=logger,
            action="get_brain_logs",
            resource_type="brain",
            resource_id=organization_id,
            user_id=user.user_id,
            details={
                "limit": limit,
                "offset": offset,
                "returned_count": len(logs),
                "total_count": total_count,
            },
        )

        return BrainLogsResponse(
            status="success",
            logs=logs,
            total_count=total_count,
            offset=offset,
            limit=limit,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get brain logs error",
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


# =============================================================================
# コスト管理エンドポイント
# =============================================================================


@router.get(
    "/costs/monthly",
    response_model=CostMonthlyResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="月次コストサマリー取得",
    description="""
過去6ヶ月分の月次コストサマリーを返す。

## データソース
- ai_monthly_cost_summary テーブル
    """,
)
async def get_costs_monthly(
    user: UserContext = Depends(require_admin),
):
    """月次コストサマリーを取得"""

    organization_id = user.organization_id

    logger.info(
        "Get costs monthly",
        organization_id=organization_id,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        year_month,
                        COALESCE(total_cost_usd, 0) as total_cost,
                        COALESCE(total_requests, 0) as requests,
                        budget_usd,
                        CASE
                            WHEN budget_usd IS NOT NULL AND total_cost_usd > budget_usd
                                THEN 'exceeded'
                            WHEN budget_usd IS NOT NULL AND total_cost_usd > budget_usd * 0.8
                                THEN 'warning'
                            ELSE 'normal'
                        END as cost_status
                    FROM ai_monthly_cost_summary
                    WHERE organization_id = :org_id
                    ORDER BY year_month DESC
                    LIMIT 6
                """),
                {"org_id": organization_id},
            )
            rows = result.fetchall()

        months = []
        for row in rows:
            months.append(
                CostMonthlyEntry(
                    year_month=row[0],
                    total_cost=round(float(row[1]), 4),
                    requests=int(row[2]),
                    budget=round(float(row[3]), 2) if row[3] is not None else None,
                    status=row[4] or "normal",
                )
            )

        log_audit_event(
            logger=logger,
            action="get_costs_monthly",
            resource_type="cost",
            resource_id=organization_id,
            user_id=user.user_id,
            details={"months_returned": len(months)},
        )

        return CostMonthlyResponse(
            status="success",
            months=months,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get costs monthly error",
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


@router.get(
    "/costs/daily",
    response_model=CostDailyResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="日次コスト取得",
    description="""
過去N日間の日次コストを返す。

## データソース
- ai_usage_logs テーブルから日次集計

## パラメータ
- days: 集計日数（デフォルト30、最大90）
    """,
)
async def get_costs_daily(
    days: int = Query(
        30,
        ge=1,
        le=90,
        description="集計日数（デフォルト30日）",
    ),
    user: UserContext = Depends(require_admin),
):
    """日次コストを取得"""

    organization_id = user.organization_id
    now = datetime.now(JST)
    start_date = (now - timedelta(days=days)).date()

    logger.info(
        "Get costs daily",
        organization_id=organization_id,
        days=days,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        DATE(created_at) as cost_date,
                        COALESCE(SUM(cost_usd), 0) as cost,
                        COUNT(*) as requests
                    FROM ai_usage_logs
                    WHERE organization_id = :org_id
                      AND created_at >= :start_date
                    GROUP BY DATE(created_at)
                    ORDER BY DATE(created_at) ASC
                """),
                {"org_id": organization_id, "start_date": start_date},
            )
            rows = result.fetchall()

        daily = []
        for row in rows:
            daily.append(
                CostDailyEntry(
                    date=row[0],
                    cost=round(float(row[1]), 6),
                    requests=int(row[2]),
                )
            )

        log_audit_event(
            logger=logger,
            action="get_costs_daily",
            resource_type="cost",
            resource_id=organization_id,
            user_id=user.user_id,
            details={"days": days, "data_points": len(daily)},
        )

        return CostDailyResponse(
            status="success",
            days=days,
            daily=daily,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get costs daily error",
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


@router.get(
    "/costs/breakdown",
    response_model=CostBreakdownResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="コスト内訳取得",
    description="""
モデル別・ティア別のコスト内訳を返す。

## 集計内容
- by_model: モデル名ごとのコスト・リクエスト数・割合
- by_tier: ティア（brain/assistant/embedding等）ごとのコスト・リクエスト数・割合

## パラメータ
- days: 集計日数（デフォルト30、最大90）
    """,
)
async def get_costs_breakdown(
    days: int = Query(
        30,
        ge=1,
        le=90,
        description="集計日数（デフォルト30日）",
    ),
    user: UserContext = Depends(require_admin),
):
    """コスト内訳を取得"""

    organization_id = user.organization_id
    now = datetime.now(JST)
    start_date = (now - timedelta(days=days)).date()

    logger.info(
        "Get costs breakdown",
        organization_id=organization_id,
        days=days,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # --- モデル別 ---
            model_result = conn.execute(
                text("""
                    SELECT
                        COALESCE(model_name, 'unknown') as model,
                        COALESCE(SUM(cost_usd), 0) as cost,
                        COUNT(*) as requests
                    FROM ai_usage_logs
                    WHERE organization_id = :org_id
                      AND created_at >= :start_date
                    GROUP BY model_name
                    ORDER BY cost DESC
                """),
                {"org_id": organization_id, "start_date": start_date},
            )
            model_rows = model_result.fetchall()

            # 全体コスト（割合計算用）
            total_cost = sum(float(r[1]) for r in model_rows) if model_rows else 0.0

            by_model = []
            for row in model_rows:
                cost = float(row[1])
                pct = (cost / total_cost * 100) if total_cost > 0 else 0.0
                by_model.append(
                    CostModelBreakdown(
                        model=row[0],
                        cost=round(cost, 6),
                        requests=int(row[2]),
                        pct=round(pct, 2),
                    )
                )

            # --- ティア別 ---
            tier_result = conn.execute(
                text("""
                    SELECT
                        COALESCE(usage_tier, 'unknown') as tier,
                        COALESCE(SUM(cost_usd), 0) as cost,
                        COUNT(*) as requests
                    FROM ai_usage_logs
                    WHERE organization_id = :org_id
                      AND created_at >= :start_date
                    GROUP BY usage_tier
                    ORDER BY cost DESC
                """),
                {"org_id": organization_id, "start_date": start_date},
            )
            tier_rows = tier_result.fetchall()

            by_tier = []
            for row in tier_rows:
                cost = float(row[1])
                pct = (cost / total_cost * 100) if total_cost > 0 else 0.0
                by_tier.append(
                    CostTierBreakdown(
                        tier=row[0],
                        cost=round(cost, 6),
                        requests=int(row[2]),
                        pct=round(pct, 2),
                    )
                )

        log_audit_event(
            logger=logger,
            action="get_costs_breakdown",
            resource_type="cost",
            resource_id=organization_id,
            user_id=user.user_id,
            details={
                "days": days,
                "models_count": len(by_model),
                "tiers_count": len(by_tier),
            },
        )

        return CostBreakdownResponse(
            status="success",
            days=days,
            by_model=by_model,
            by_tier=by_tier,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get costs breakdown error",
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


# =============================================================================
# メンバー管理エンドポイント
# =============================================================================


@router.get(
    "/members",
    response_model=MembersListResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="メンバー一覧取得",
    description="""
組織内のメンバー一覧を返す（検索・フィルタ・ページネーション対応）。

## パラメータ
- search: 名前またはメールで部分一致検索
- dept_id: 部署IDでフィルタ
- limit: 取得件数（デフォルト50、最大200）
- offset: オフセット
    """,
)
async def get_members(
    search: Optional[str] = Query(
        None,
        max_length=100,
        description="名前/メール部分一致検索",
    ),
    dept_id: Optional[str] = Query(
        None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="部署IDでフィルタ（UUID形式）",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description="取得件数（最大200）",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="オフセット",
    ),
    user: UserContext = Depends(require_admin),
):
    """メンバー一覧を取得"""

    organization_id = user.organization_id

    logger.info(
        "Get members",
        organization_id=organization_id,
        has_search=bool(search),
        dept_id=dept_id,
        limit=limit,
        offset=offset,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # ベースクエリ
            query = """
                SELECT
                    u.id as user_id,
                    u.name,
                    u.email,
                    r.name as role_name,
                    r.level as role_level,
                    d.name as department_name,
                    ud.department_id,
                    u.created_at
                FROM users u
                LEFT JOIN user_departments ud
                    ON u.id = ud.user_id AND ud.ended_at IS NULL
                LEFT JOIN roles r
                    ON ud.role_id = r.id
                LEFT JOIN departments d
                    ON ud.department_id = d.id
                WHERE u.organization_id = :org_id
            """
            params = {"org_id": organization_id}

            # 検索フィルタ
            if search:
                query += """
                    AND (
                        u.name ILIKE :search_pattern
                        OR u.email ILIKE :search_pattern
                    )
                """
                params["search_pattern"] = f"%{_escape_like(search)}%"

            # 部署フィルタ
            if dept_id:
                query += " AND ud.department_id = :dept_id"
                params["dept_id"] = dept_id

            # ソート + ページネーション
            query += " ORDER BY u.created_at DESC LIMIT :limit OFFSET :offset"
            params["limit"] = limit
            params["offset"] = offset

            result = conn.execute(text(query), params)
            rows = result.fetchall()

            # 総件数カウント
            count_query = """
                SELECT COUNT(DISTINCT u.id) as total
                FROM users u
                LEFT JOIN user_departments ud
                    ON u.id = ud.user_id AND ud.ended_at IS NULL
                WHERE u.organization_id = :org_id
            """
            count_params = {"org_id": organization_id}

            if search:
                count_query += """
                    AND (
                        u.name ILIKE :search_pattern
                        OR u.email ILIKE :search_pattern
                    )
                """
                count_params["search_pattern"] = f"%{_escape_like(search)}%"

            if dept_id:
                count_query += " AND ud.department_id = :dept_id"
                count_params["dept_id"] = dept_id

            count_result = conn.execute(text(count_query), count_params)
            total_count = int(count_result.fetchone()[0])

        members = []
        for row in rows:
            members.append(
                MemberResponse(
                    user_id=str(row[0]),
                    name=row[1],
                    email=row[2],
                    role=row[3],
                    role_level=int(row[4]) if row[4] is not None else None,
                    department=row[5],
                    department_id=str(row[6]) if row[6] else None,
                    created_at=row[7],
                )
            )

        log_audit_event(
            logger=logger,
            action="get_members",
            resource_type="member",
            resource_id=organization_id,
            user_id=user.user_id,
            details={
                "has_search": bool(search),
                "dept_id": dept_id,
                "returned_count": len(members),
                "total_count": total_count,
            },
        )

        return MembersListResponse(
            status="success",
            members=members,
            total_count=total_count,
            offset=offset,
            limit=limit,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get members error",
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


@router.get(
    "/members/{user_id}",
    response_model=MemberResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        404: {"model": AdminErrorResponse, "description": "メンバーが見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="メンバー詳細取得",
    description="指定したユーザーIDのメンバー詳細情報を返す。",
)
async def get_member_detail(
    user_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="UUID形式のユーザーID",
    ),
    user: UserContext = Depends(require_admin),
):
    """メンバー詳細を取得"""

    organization_id = user.organization_id

    logger.info(
        "Get member detail",
        organization_id=organization_id,
        target_user_id=user_id,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        u.id as user_id,
                        u.name,
                        u.email,
                        r.name as role_name,
                        r.level as role_level,
                        d.name as department_name,
                        ud.department_id,
                        u.created_at
                    FROM users u
                    LEFT JOIN user_departments ud
                        ON u.id = ud.user_id AND ud.ended_at IS NULL
                    LEFT JOIN roles r
                        ON ud.role_id = r.id
                    LEFT JOIN departments d
                        ON ud.department_id = d.id
                    WHERE u.id = :target_user_id
                      AND u.organization_id = :org_id
                    LIMIT 1
                """),
                {"target_user_id": user_id, "org_id": organization_id},
            )
            row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failed",
                    "error_code": "MEMBER_NOT_FOUND",
                    "error_message": "指定されたメンバーが見つかりません",
                },
            )

        log_audit_event(
            logger=logger,
            action="get_member_detail",
            resource_type="member",
            resource_id=user_id,
            user_id=user.user_id,
            details={},
        )

        return MemberResponse(
            user_id=str(row[0]),
            name=row[1],
            email=row[2],
            role=row[3],
            role_level=int(row[4]) if row[4] is not None else None,
            department=row[5],
            department_id=str(row[6]) if row[6] else None,
            created_at=row[7],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get member detail error",
            organization_id=organization_id,
            target_user_id=user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )
