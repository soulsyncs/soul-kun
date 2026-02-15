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
    # Departments / Org Chart
    DepartmentTreeNode,
    DepartmentsTreeResponse,
    DepartmentResponse,
    DepartmentDetailResponse,
    DepartmentMember,
    CreateDepartmentRequest,
    UpdateDepartmentRequest,
    DepartmentMutationResponse,
    MemberDetailResponse,
    MemberDepartmentInfo,
    UpdateMemberRequest,
    UpdateMemberDepartmentsRequest,
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


# 編集権限（Level 6以上）を要求する依存関数
EDITOR_MIN_LEVEL = 6


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
            # ベースクエリ（DISTINCT ON で各ユーザー1行に制限、主所属を優先）
            query = """
                SELECT DISTINCT ON (u.id)
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

            # DISTINCT ON (u.id) + ソート（主所属を優先）
            # サブクエリでDISTINCT ON処理し、外側でcreated_at DESCソート + ページネーション
            query = f"""
                SELECT * FROM (
                    {query}
                    ORDER BY u.id, ud.is_primary DESC NULLS LAST, ud.created_at ASC
                ) sub
                ORDER BY sub.created_at DESC
                LIMIT :limit OFFSET :offset
            """
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


# =============================================================================
# 組織図・部署管理エンドポイント
# =============================================================================


def _build_department_tree(
    departments: list, member_counts: dict
) -> list[DepartmentTreeNode]:
    """フラットな部署リストからツリー構造を構築する。"""
    nodes = {}
    for dept in departments:
        dept_id = str(dept[0])
        nodes[dept_id] = DepartmentTreeNode(
            id=dept_id,
            name=dept[1] or "",
            parent_department_id=str(dept[2]) if dept[2] else None,
            level=int(dept[3]) if dept[3] is not None else 0,
            display_order=int(dept[4]) if dept[4] is not None else 0,
            description=dept[5],
            is_active=bool(dept[6]) if dept[6] is not None else True,
            member_count=member_counts.get(dept_id, 0),
            children=[],
        )

    roots = []
    for dept_id, node in nodes.items():
        parent_id = node.parent_department_id
        if parent_id and parent_id in nodes:
            nodes[parent_id].children.append(node)
        else:
            roots.append(node)

    # Sort children by display_order at each level
    def sort_children(node: DepartmentTreeNode):
        node.children.sort(key=lambda n: n.display_order)
        for child in node.children:
            sort_children(child)

    roots.sort(key=lambda n: n.display_order)
    for root in roots:
        sort_children(root)

    return roots


@router.get(
    "/departments",
    response_model=DepartmentsTreeResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="部署ツリー取得",
    description="組織の全部署をツリー構造で返す。各部署に所属メンバー数を含む。",
)
async def get_departments_tree(
    user: UserContext = Depends(require_admin),
):
    """部署ツリーを取得"""

    organization_id = user.organization_id

    logger.info(
        "Get departments tree",
        organization_id=organization_id,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 全部署取得
            dept_result = conn.execute(
                text("""
                    SELECT
                        d.id, d.name, d.parent_id,
                        d.level, d.display_order, d.description,
                        d.is_active
                    FROM departments d
                    WHERE d.organization_id = :org_id
                    ORDER BY d.display_order ASC, d.name ASC
                """),
                {"org_id": organization_id},
            )
            departments = dept_result.fetchall()

            # 部署ごとのメンバー数
            count_result = conn.execute(
                text("""
                    SELECT
                        ud.department_id::text,
                        COUNT(DISTINCT ud.user_id) as cnt
                    FROM user_departments ud
                    JOIN departments d ON ud.department_id = d.id
                    WHERE d.organization_id = :org_id
                      AND ud.ended_at IS NULL
                    GROUP BY ud.department_id
                """),
                {"org_id": organization_id},
            )
            member_counts = {
                str(row[0]): int(row[1]) for row in count_result.fetchall()
            }

        tree = _build_department_tree(departments, member_counts)

        log_audit_event(
            logger=logger,
            action="get_departments_tree",
            resource_type="department",
            resource_id=organization_id,
            user_id=user.user_id,
            details={"total_departments": len(departments)},
        )

        return DepartmentsTreeResponse(
            status="success",
            departments=tree,
            total_count=len(departments),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get departments tree error",
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
    "/departments/{dept_id}",
    response_model=DepartmentDetailResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        404: {"model": AdminErrorResponse, "description": "部署が見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="部署詳細取得",
    description="指定した部署の詳細情報と所属メンバーリストを返す。",
)
async def get_department_detail(
    dept_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="部署ID（UUID）",
    ),
    user: UserContext = Depends(require_admin),
):
    """部署詳細を取得"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 部署情報
            dept_result = conn.execute(
                text("""
                    SELECT
                        d.id, d.name, d.parent_id,
                        d.level, d.display_order, d.description,
                        d.is_active, d.created_at, d.updated_at
                    FROM departments d
                    WHERE d.id = :dept_id
                      AND d.organization_id = :org_id
                    LIMIT 1
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            dept_row = dept_result.fetchone()

            if not dept_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "DEPARTMENT_NOT_FOUND",
                        "error_message": "指定された部署が見つかりません",
                    },
                )

            # 所属メンバー取得
            members_result = conn.execute(
                text("""
                    SELECT
                        u.id, u.name,
                        r.name as role_name, r.level as role_level,
                        ud.is_primary
                    FROM user_departments ud
                    JOIN users u ON ud.user_id = u.id
                    LEFT JOIN roles r ON ud.role_id = r.id
                    WHERE ud.department_id = :dept_id
                      AND ud.ended_at IS NULL
                      AND u.organization_id = :org_id
                    ORDER BY r.level DESC NULLS LAST, u.name ASC
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            member_rows = members_result.fetchall()

        department = DepartmentResponse(
            id=str(dept_row[0]),
            name=dept_row[1] or "",
            parent_department_id=str(dept_row[2]) if dept_row[2] else None,
            level=int(dept_row[3]) if dept_row[3] is not None else 0,
            display_order=int(dept_row[4]) if dept_row[4] is not None else 0,
            description=dept_row[5],
            is_active=bool(dept_row[6]) if dept_row[6] is not None else True,
            member_count=len(member_rows),
            created_at=dept_row[7],
            updated_at=dept_row[8],
        )

        members = [
            DepartmentMember(
                user_id=str(row[0]),
                name=row[1],
                role=row[2],
                role_level=int(row[3]) if row[3] is not None else None,
                is_primary=bool(row[4]) if row[4] is not None else False,
            )
            for row in member_rows
        ]

        log_audit_event(
            logger=logger,
            action="get_department_detail",
            resource_type="department",
            resource_id=dept_id,
            user_id=user.user_id,
        )

        return DepartmentDetailResponse(
            status="success",
            department=department,
            members=members,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get department detail error",
            organization_id=organization_id,
            dept_id=dept_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )


@router.post(
    "/departments",
    response_model=DepartmentMutationResponse,
    status_code=201,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足（Level 6必要）"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="部署作成（Level 6+）",
    description="新しい部署を作成する。編集権限（Level 6以上）が必要。",
)
async def create_department(
    request: CreateDepartmentRequest,
    user: UserContext = Depends(require_editor),
):
    """部署を作成する"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 親部署の存在確認（指定時）
            parent_level = 0
            if request.parent_department_id:
                parent_result = conn.execute(
                    text("""
                        SELECT id, level, path
                        FROM departments
                        WHERE id = :parent_id
                          AND organization_id = :org_id
                        LIMIT 1
                    """),
                    {
                        "parent_id": request.parent_department_id,
                        "org_id": organization_id,
                    },
                )
                parent_row = parent_result.fetchone()
                if not parent_row:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "status": "failed",
                            "error_code": "PARENT_NOT_FOUND",
                            "error_message": "指定された親部署が見つかりません",
                        },
                    )
                parent_level = int(parent_row[1]) if parent_row[1] is not None else 0

            new_level = parent_level + 1

            # 部署作成
            result = conn.execute(
                text("""
                    INSERT INTO departments (
                        organization_id, name, parent_id,
                        level, display_order, description,
                        is_active, created_by
                    ) VALUES (
                        :org_id, :name, :parent_id,
                        :level, :display_order, :description,
                        TRUE, :created_by
                    )
                    RETURNING id
                """),
                {
                    "org_id": organization_id,
                    "name": request.name,
                    "parent_id": request.parent_department_id,
                    "level": new_level,
                    "display_order": request.display_order,
                    "description": request.description,
                    "created_by": user.user_id,
                },
            )
            new_id = str(result.fetchone()[0])
            conn.commit()

        log_audit_event(
            logger=logger,
            action="create_department",
            resource_type="department",
            resource_id=new_id,
            user_id=user.user_id,
            details={
                "name": request.name,
                "parent_id": request.parent_department_id,
            },
        )

        return DepartmentMutationResponse(
            status="success",
            department_id=new_id,
            message=f"部署「{request.name}」を作成しました",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Create department error",
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


@router.put(
    "/departments/{dept_id}",
    response_model=DepartmentMutationResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足（Level 6必要）"},
        404: {"model": AdminErrorResponse, "description": "部署が見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="部署更新（Level 6+）",
    description="部署情報を更新する。編集権限（Level 6以上）が必要。",
)
async def update_department(
    request: UpdateDepartmentRequest,
    dept_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="部署ID（UUID）",
    ),
    user: UserContext = Depends(require_editor),
):
    """部署情報を更新する"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 対象部署の存在確認
            exists_result = conn.execute(
                text("""
                    SELECT id FROM departments
                    WHERE id = :dept_id AND organization_id = :org_id
                    LIMIT 1
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            if not exists_result.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "DEPARTMENT_NOT_FOUND",
                        "error_message": "指定された部署が見つかりません",
                    },
                )

            # 動的にSETクエリを組み立て
            set_clauses = []
            params = {"dept_id": dept_id, "org_id": organization_id}

            if request.name is not None:
                set_clauses.append("name = :name")
                params["name"] = request.name
            if request.parent_department_id is not None:
                # 循環参照チェック: 自分自身を親に設定できない
                if request.parent_department_id == dept_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "status": "failed",
                            "error_code": "CIRCULAR_REFERENCE",
                            "error_message": "部署を自身の子にすることはできません",
                        },
                    )
                # 循環参照チェック: 子孫を親に設定できない
                ancestor_check = conn.execute(
                    text("""
                        WITH RECURSIVE ancestors AS (
                            SELECT id, parent_id FROM departments
                            WHERE id = :proposed_parent AND organization_id = :org_id
                            UNION ALL
                            SELECT d.id, d.parent_id FROM departments d
                            JOIN ancestors a ON d.id = a.parent_id
                        )
                        SELECT 1 FROM ancestors WHERE id = :dept_id LIMIT 1
                    """),
                    {
                        "proposed_parent": request.parent_department_id,
                        "org_id": organization_id,
                        "dept_id": dept_id,
                    },
                )
                if ancestor_check.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "status": "failed",
                            "error_code": "CIRCULAR_REFERENCE",
                            "error_message": "子孫の部署を親に設定することはできません（循環参照）",
                        },
                    )
                set_clauses.append("parent_id = :parent_id")
                params["parent_id"] = request.parent_department_id
            if request.description is not None:
                set_clauses.append("description = :description")
                params["description"] = request.description
            if request.display_order is not None:
                set_clauses.append("display_order = :display_order")
                params["display_order"] = request.display_order

            if not set_clauses:
                return DepartmentMutationResponse(
                    status="success",
                    department_id=dept_id,
                    message="更新項目がありません",
                )

            set_clauses.append("updated_by = :updated_by")
            params["updated_by"] = user.user_id
            set_clauses.append("updated_at = NOW()")

            query = f"""
                UPDATE departments
                SET {', '.join(set_clauses)}
                WHERE id = :dept_id AND organization_id = :org_id
            """
            conn.execute(text(query), params)
            conn.commit()

        log_audit_event(
            logger=logger,
            action="update_department",
            resource_type="department",
            resource_id=dept_id,
            user_id=user.user_id,
            details={"updated_fields": [c.split(" = ")[0] for c in set_clauses[:-2]]},
        )

        return DepartmentMutationResponse(
            status="success",
            department_id=dept_id,
            message="部署情報を更新しました",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Update department error",
            organization_id=organization_id,
            dept_id=dept_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )


@router.delete(
    "/departments/{dept_id}",
    response_model=DepartmentMutationResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足（Level 6必要）"},
        404: {"model": AdminErrorResponse, "description": "部署が見つからない"},
        409: {"model": AdminErrorResponse, "description": "子部署またはメンバーが存在"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="部署削除（ソフト削除, Level 6+）",
    description="部署をソフト削除（is_active=false）する。子部署またはメンバーがいる場合は拒否。",
)
async def delete_department(
    dept_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="部署ID（UUID）",
    ),
    user: UserContext = Depends(require_editor),
):
    """部署をソフト削除する"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 対象部署の存在確認
            exists_result = conn.execute(
                text("""
                    SELECT id, name FROM departments
                    WHERE id = :dept_id
                      AND organization_id = :org_id
                      AND is_active = TRUE
                    LIMIT 1
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            dept_row = exists_result.fetchone()
            if not dept_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "DEPARTMENT_NOT_FOUND",
                        "error_message": "指定された部署が見つかりません",
                    },
                )

            # 子部署の存在チェック
            children_result = conn.execute(
                text("""
                    SELECT COUNT(*) FROM departments
                    WHERE parent_id = :dept_id
                      AND organization_id = :org_id
                      AND is_active = TRUE
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            if int(children_result.fetchone()[0]) > 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "status": "failed",
                        "error_code": "HAS_CHILDREN",
                        "error_message": "子部署が存在するため削除できません。先に子部署を移動または削除してください",
                    },
                )

            # 所属メンバーの存在チェック（org_id防御）
            members_result = conn.execute(
                text("""
                    SELECT COUNT(*) FROM user_departments ud
                    JOIN users u ON ud.user_id = u.id
                    WHERE ud.department_id = :dept_id
                      AND ud.ended_at IS NULL
                      AND u.organization_id = :org_id
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            if int(members_result.fetchone()[0]) > 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "status": "failed",
                        "error_code": "HAS_MEMBERS",
                        "error_message": "所属メンバーが存在するため削除できません。先にメンバーを異動させてください",
                    },
                )

            # ソフト削除
            conn.execute(
                text("""
                    UPDATE departments
                    SET is_active = FALSE, updated_by = :updated_by, updated_at = NOW()
                    WHERE id = :dept_id AND organization_id = :org_id
                """),
                {
                    "dept_id": dept_id,
                    "org_id": organization_id,
                    "updated_by": user.user_id,
                },
            )
            conn.commit()

        dept_name = dept_row[1] or dept_id

        log_audit_event(
            logger=logger,
            action="delete_department",
            resource_type="department",
            resource_id=dept_id,
            user_id=user.user_id,
            details={"department_name": dept_name},
        )

        return DepartmentMutationResponse(
            status="success",
            department_id=dept_id,
            message=f"部署「{dept_name}」を削除しました",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Delete department error",
            organization_id=organization_id,
            dept_id=dept_id,
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
# メンバー詳細・更新エンドポイント（組織図統合）
# =============================================================================


@router.get(
    "/members/{user_id}/detail",
    response_model=MemberDetailResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        404: {"model": AdminErrorResponse, "description": "メンバーが見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="メンバー詳細取得（全属性）",
    description="メンバーの全属性（所属部署リスト、ChatWorkアカウント等）を返す。",
)
async def get_member_full_detail(
    user_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="UUID形式のユーザーID",
    ),
    user: UserContext = Depends(require_admin),
):
    """メンバーの全詳細情報を取得"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # ユーザー基本情報
            user_result = conn.execute(
                text("""
                    SELECT
                        u.id, u.name, u.email,
                        u.chatwork_account_id, u.is_active,
                        u.created_at, u.updated_at
                    FROM users u
                    WHERE u.id = :user_id
                      AND u.organization_id = :org_id
                    LIMIT 1
                """),
                {"user_id": user_id, "org_id": organization_id},
            )
            user_row = user_result.fetchone()

            if not user_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "MEMBER_NOT_FOUND",
                        "error_message": "指定されたメンバーが見つかりません",
                    },
                )

            # 所属部署リスト
            dept_result = conn.execute(
                text("""
                    SELECT
                        ud.department_id, d.name as dept_name,
                        r.name as role_name, r.level as role_level,
                        ud.is_primary
                    FROM user_departments ud
                    JOIN departments d ON ud.department_id = d.id
                    LEFT JOIN roles r ON ud.role_id = r.id
                    WHERE ud.user_id = :user_id
                      AND ud.ended_at IS NULL
                      AND d.organization_id = :org_id
                    ORDER BY ud.is_primary DESC, d.name ASC
                """),
                {"user_id": user_id, "org_id": organization_id},
            )
            dept_rows = dept_result.fetchall()

        departments = [
            MemberDepartmentInfo(
                department_id=str(row[0]),
                department_name=row[1] or "",
                role=row[2],
                role_level=int(row[3]) if row[3] is not None else None,
                is_primary=bool(row[4]) if row[4] is not None else False,
            )
            for row in dept_rows
        ]

        # 最高ロールレベルを取得
        max_role_level = max(
            (d.role_level for d in departments if d.role_level is not None),
            default=None,
        )
        primary_role = next(
            (d.role for d in departments if d.is_primary and d.role),
            departments[0].role if departments else None,
        )

        log_audit_event(
            logger=logger,
            action="get_member_full_detail",
            resource_type="member",
            resource_id=user_id,
            user_id=user.user_id,
        )

        return MemberDetailResponse(
            status="success",
            user_id=str(user_row[0]),
            name=user_row[1],
            email=user_row[2],
            role=primary_role,
            role_level=max_role_level,
            departments=departments,
            chatwork_account_id=user_row[3],
            is_active=bool(user_row[4]) if user_row[4] is not None else True,
            created_at=user_row[5],
            updated_at=user_row[6],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get member full detail error",
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


@router.put(
    "/members/{user_id}",
    response_model=DepartmentMutationResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足（Level 6必要）"},
        404: {"model": AdminErrorResponse, "description": "メンバーが見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="メンバー情報更新（Level 6+）",
    description="メンバーの基本情報（名前、メール、ChatWorkアカウント）を更新する。",
)
async def update_member(
    request: UpdateMemberRequest,
    user_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="UUID形式のユーザーID",
    ),
    user: UserContext = Depends(require_editor),
):
    """メンバー情報を更新する"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 存在確認
            exists_result = conn.execute(
                text("""
                    SELECT id FROM users
                    WHERE id = :user_id AND organization_id = :org_id
                    LIMIT 1
                """),
                {"user_id": user_id, "org_id": organization_id},
            )
            if not exists_result.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "MEMBER_NOT_FOUND",
                        "error_message": "指定されたメンバーが見つかりません",
                    },
                )

            set_clauses = []
            params = {"user_id": user_id, "org_id": organization_id}

            if request.name is not None:
                set_clauses.append("name = :name")
                params["name"] = request.name
            if request.email is not None:
                set_clauses.append("email = :email")
                params["email"] = request.email
            if request.chatwork_account_id is not None:
                set_clauses.append("chatwork_account_id = :cw_id")
                params["cw_id"] = request.chatwork_account_id

            if not set_clauses:
                return DepartmentMutationResponse(
                    status="success",
                    department_id=user_id,
                    message="更新項目がありません",
                )

            set_clauses.append("updated_at = NOW()")

            query = f"""
                UPDATE users
                SET {', '.join(set_clauses)}
                WHERE id = :user_id AND organization_id = :org_id
            """
            conn.execute(text(query), params)
            conn.commit()

        log_audit_event(
            logger=logger,
            action="update_member",
            resource_type="member",
            resource_id=user_id,
            user_id=user.user_id,
            details={"updated_fields": [c.split(" = ")[0] for c in set_clauses[:-1]]},
        )

        return DepartmentMutationResponse(
            status="success",
            department_id=user_id,
            message="メンバー情報を更新しました",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Update member error",
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


@router.put(
    "/members/{user_id}/departments",
    response_model=DepartmentMutationResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足（Level 6必要）"},
        404: {"model": AdminErrorResponse, "description": "メンバーが見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="メンバー所属部署更新（Level 6+）",
    description="メンバーの所属部署を一括更新する。既存の所属は終了日を設定して新しい所属に置き換える。",
)
async def update_member_departments(
    request: UpdateMemberDepartmentsRequest,
    user_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="UUID形式のユーザーID",
    ),
    user: UserContext = Depends(require_editor),
):
    """メンバーの所属部署を更新する"""

    organization_id = user.organization_id
    now = datetime.now(timezone.utc)

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # ユーザー存在確認
            exists_result = conn.execute(
                text("""
                    SELECT id FROM users
                    WHERE id = :user_id AND organization_id = :org_id
                    LIMIT 1
                """),
                {"user_id": user_id, "org_id": organization_id},
            )
            if not exists_result.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "MEMBER_NOT_FOUND",
                        "error_message": "指定されたメンバーが見つかりません",
                    },
                )

            # 指定された部署が全て存在するか確認（バッチ検証でN+1回避）
            dept_ids = [d.department_id for d in request.departments]
            valid_result = conn.execute(
                text("""
                    SELECT id::text FROM departments
                    WHERE id = ANY(:dept_ids::uuid[])
                      AND organization_id = :org_id
                      AND is_active = TRUE
                """),
                {"dept_ids": dept_ids, "org_id": organization_id},
            )
            valid_ids = {str(row[0]) for row in valid_result.fetchall()}
            missing = set(dept_ids) - valid_ids
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "failed",
                        "error_code": "DEPARTMENT_NOT_FOUND",
                        "error_message": f"部署 {', '.join(missing)} が見つかりません",
                    },
                )

            # 既存の所属を終了（org_id防御）
            conn.execute(
                text("""
                    UPDATE user_departments ud
                    SET ended_at = :now, updated_at = :now
                    FROM departments d
                    WHERE ud.user_id = :user_id
                      AND ud.ended_at IS NULL
                      AND ud.department_id = d.id
                      AND d.organization_id = :org_id
                """),
                {"user_id": user_id, "now": now, "org_id": organization_id},
            )

            # 新しい所属を作成
            for assignment in request.departments:
                conn.execute(
                    text("""
                        INSERT INTO user_departments (
                            user_id, department_id, role_id,
                            is_primary, started_at, created_at
                        ) VALUES (
                            :user_id, :dept_id, :role_id,
                            :is_primary, :now, :now
                        )
                    """),
                    {
                        "user_id": user_id,
                        "dept_id": assignment.department_id,
                        "role_id": assignment.role_id,
                        "is_primary": assignment.is_primary,
                        "now": now,
                    },
                )

            conn.commit()

        log_audit_event(
            logger=logger,
            action="update_member_departments",
            resource_type="member",
            resource_id=user_id,
            user_id=user.user_id,
            details={
                "new_departments": [d.department_id for d in request.departments],
            },
        )

        return DepartmentMutationResponse(
            status="success",
            department_id=user_id,
            message=f"所属部署を{len(request.departments)}件に更新しました",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Update member departments error",
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


# =============================================
# Phase 2: Goals endpoints
# =============================================


@router.get(
    "/goals",
    summary="目標一覧取得",
    description="全目標をフィルタ付きで取得（Level 5+）",
)
async def get_goals_list(
    user: UserContext = Depends(require_admin),
    status_filter: Optional[str] = Query(None, alias="status", description="ステータスフィルタ"),
    department_id: Optional[str] = Query(None, description="部署IDフィルタ"),
    period_type: Optional[str] = Query(None, description="期間種別フィルタ"),
    limit: int = Query(50, ge=1, le=200, description="取得件数"),
    offset: int = Query(0, ge=0, description="オフセット"),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            where_clauses = ["g.organization_id = :org_id"]
            params: dict = {"org_id": organization_id, "limit": limit, "offset": offset}

            if status_filter:
                where_clauses.append("g.status = :status")
                params["status"] = status_filter
            if department_id:
                where_clauses.append("g.department_id = :dept_id")
                params["dept_id"] = department_id
            if period_type:
                where_clauses.append("g.period_type = :period_type")
                params["period_type"] = period_type

            where_sql = " AND ".join(where_clauses)

            result = conn.execute(
                text(f"""
                    SELECT g.id, g.user_id, u.name AS user_name,
                           d.name AS department_name,
                           g.title, g.goal_type, g.goal_level, g.status,
                           g.period_type, g.period_start, g.period_end,
                           g.deadline, g.target_value, g.current_value, g.unit
                    FROM goals g
                    LEFT JOIN users u ON g.user_id = u.id
                    LEFT JOIN departments d ON g.department_id = d.id
                    WHERE {where_sql}
                    ORDER BY g.created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM goals g WHERE {where_sql}"),
                params,
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import GoalSummary, GoalsListResponse

        goals = []
        for row in rows:
            target = float(row[12]) if row[12] is not None else None
            current = float(row[13]) if row[13] is not None else None
            progress = (current / target * 100) if target and current is not None and target > 0 else None
            goals.append(GoalSummary(
                id=str(row[0]), user_id=str(row[1]),
                user_name=row[2], department_name=row[3],
                title=row[4], goal_type=row[5], goal_level=row[6],
                status=row[7], period_type=row[8],
                period_start=str(row[9]) if row[9] else None,
                period_end=str(row[10]) if row[10] else None,
                deadline=str(row[11]) if row[11] else None,
                target_value=target, current_value=current,
                unit=row[14], progress_pct=round(progress, 1) if progress is not None else None,
            ))

        log_audit_event(
            logger=logger, action="get_goals_list",
            resource_type="goals", resource_id="list",
            user_id=user.user_id, details={"count": len(goals)},
        )
        return GoalsListResponse(goals=goals, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get goals list error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/goals/stats",
    summary="目標達成率サマリー",
    description="全社/部署別の目標達成率を取得（Level 5+）",
)
async def get_goals_stats(
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'active') AS active,
                        COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                        COUNT(*) FILTER (WHERE status = 'active' AND deadline < CURRENT_DATE) AS overdue
                    FROM goals
                    WHERE organization_id = :org_id
                """),
                {"org_id": organization_id},
            )
            stats = result.fetchone()
            total = int(stats[0])
            completed = int(stats[2])
            rate = (completed / total * 100) if total > 0 else 0.0

            dept_result = conn.execute(
                text("""
                    SELECT d.name,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE g.status = 'completed') AS completed
                    FROM goals g
                    JOIN departments d ON g.department_id = d.id
                    WHERE g.organization_id = :org_id
                    GROUP BY d.name
                    ORDER BY total DESC
                """),
                {"org_id": organization_id},
            )
            by_dept = [
                {"department": r[0], "total": int(r[1]), "completed": int(r[2]),
                 "rate": round(int(r[2]) / int(r[1]) * 100, 1) if int(r[1]) > 0 else 0.0}
                for r in dept_result.fetchall()
            ]

        from app.schemas.admin import GoalStatsResponse

        log_audit_event(
            logger=logger, action="get_goals_stats",
            resource_type="goals", resource_id="stats",
            user_id=user.user_id, details={},
        )
        return GoalStatsResponse(
            total_goals=total, active_goals=int(stats[1]),
            completed_goals=completed, overdue_goals=int(stats[3]),
            completion_rate=round(rate, 1), by_department=by_dept,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get goals stats error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/goals/{goal_id}",
    summary="目標詳細取得",
    description="目標の詳細と進捗履歴を取得（Level 5+）",
)
async def get_goal_detail(
    goal_id: str = Path(..., pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT g.id, g.user_id, u.name AS user_name,
                           d.name AS department_name,
                           g.title, g.goal_type, g.goal_level, g.status,
                           g.period_type, g.period_start, g.period_end,
                           g.deadline, g.target_value, g.current_value, g.unit
                    FROM goals g
                    LEFT JOIN users u ON g.user_id = u.id
                    LEFT JOIN departments d ON g.department_id = d.id
                    WHERE g.id = :goal_id AND g.organization_id = :org_id
                """),
                {"goal_id": goal_id, "org_id": organization_id},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"status": "failed", "error_code": "GOAL_NOT_FOUND", "error_message": "目標が見つかりません"},
                )

            target = float(row[12]) if row[12] is not None else None
            current = float(row[13]) if row[13] is not None else None
            progress = (current / target * 100) if target and current is not None and target > 0 else None

            from app.schemas.admin import GoalSummary, GoalProgressEntry, GoalDetailResponse

            goal = GoalSummary(
                id=str(row[0]), user_id=str(row[1]),
                user_name=row[2], department_name=row[3],
                title=row[4], goal_type=row[5], goal_level=row[6],
                status=row[7], period_type=row[8],
                period_start=str(row[9]) if row[9] else None,
                period_end=str(row[10]) if row[10] else None,
                deadline=str(row[11]) if row[11] else None,
                target_value=target, current_value=current,
                unit=row[14], progress_pct=round(progress, 1) if progress is not None else None,
            )

            progress_result = conn.execute(
                text("""
                    SELECT id, progress_date, value, cumulative_value, daily_note
                    FROM goal_progress
                    WHERE goal_id = :goal_id AND organization_id = :org_id
                    ORDER BY progress_date DESC
                    LIMIT 90
                """),
                {"goal_id": goal_id, "org_id": organization_id},
            )
            progress_entries = [
                GoalProgressEntry(
                    id=str(p[0]), progress_date=str(p[1]),
                    value=float(p[2]) if p[2] is not None else None,
                    cumulative_value=float(p[3]) if p[3] is not None else None,
                    daily_note=p[4],
                )
                for p in progress_result.fetchall()
            ]

        log_audit_event(
            logger=logger, action="get_goal_detail",
            resource_type="goal", resource_id=goal_id,
            user_id=user.user_id, details={},
        )
        return GoalDetailResponse(goal=goal, progress=progress_entries)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get goal detail error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


# =============================================
# Phase 2: Wellness / Emotion endpoints
# =============================================


@router.get(
    "/wellness/alerts",
    summary="感情アラート一覧",
    description="アクティブな感情アラートを取得（Level 5+）",
)
async def get_emotion_alerts(
    user: UserContext = Depends(require_admin),
    risk_level: Optional[str] = Query(None, description="リスクレベルフィルタ"),
    alert_status: Optional[str] = Query(None, alias="status", description="ステータスフィルタ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            where_clauses = ["ea.organization_id = :org_id"]
            params: dict = {"org_id": organization_id, "limit": limit, "offset": offset}

            if risk_level:
                where_clauses.append("ea.risk_level = :risk_level")
                params["risk_level"] = risk_level
            if alert_status:
                where_clauses.append("ea.status = :alert_status")
                params["alert_status"] = alert_status

            where_sql = " AND ".join(where_clauses)

            result = conn.execute(
                text(f"""
                    SELECT ea.id, ea.user_id, ea.user_name,
                           d.name AS department_name,
                           ea.alert_type, ea.risk_level,
                           ea.baseline_score, ea.current_score, ea.score_change,
                           ea.consecutive_negative_days, ea.status,
                           ea.first_detected_at, ea.last_detected_at
                    FROM emotion_alerts ea
                    LEFT JOIN departments d ON ea.department_id = d.id
                    WHERE {where_sql}
                    ORDER BY ea.last_detected_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM emotion_alerts ea WHERE {where_sql}"),
                params,
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import EmotionAlertSummary, EmotionAlertsResponse

        alerts = [
            EmotionAlertSummary(
                id=str(r[0]), user_id=str(r[1]),
                user_name=r[2], department_name=r[3],
                alert_type=r[4], risk_level=r[5],
                baseline_score=float(r[6]) if r[6] is not None else None,
                current_score=float(r[7]) if r[7] is not None else None,
                score_change=float(r[8]) if r[8] is not None else None,
                consecutive_negative_days=r[9],
                status=r[10],
                first_detected_at=str(r[11]) if r[11] else None,
                last_detected_at=str(r[12]) if r[12] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_emotion_alerts",
            resource_type="emotion_alerts", resource_id="list",
            user_id=user.user_id, details={"count": len(alerts)},
        )
        return EmotionAlertsResponse(alerts=alerts, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get emotion alerts error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/wellness/trends",
    summary="感情トレンド取得",
    description="組織全体の感情スコア推移を取得（Level 5+）",
)
async def get_emotion_trends(
    user: UserContext = Depends(require_admin),
    days: int = Query(30, ge=7, le=90, description="取得期間（日数）"),
    department_id: Optional[str] = Query(None, description="部署IDフィルタ"),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            extra_join = ""
            extra_where = ""
            params: dict = {"org_id": organization_id, "days": days}

            if department_id:
                extra_join = """
                    JOIN user_departments ud ON es.user_id = ud.user_id AND ud.ended_at IS NULL
                """
                extra_where = "AND ud.department_id = :dept_id"
                params["dept_id"] = department_id

            result = conn.execute(
                text(f"""
                    SELECT
                        DATE(es.message_time) AS date,
                        AVG(es.sentiment_score) AS avg_score,
                        COUNT(*) AS message_count,
                        COUNT(*) FILTER (WHERE es.sentiment_label IN ('negative', 'very_negative')) AS negative_count,
                        COUNT(*) FILTER (WHERE es.sentiment_label IN ('positive', 'very_positive')) AS positive_count
                    FROM emotion_scores es
                    {extra_join}
                    WHERE es.organization_id = :org_id
                      AND es.message_time >= CURRENT_DATE - (INTERVAL '1 day' * :days)
                      {extra_where}
                    GROUP BY DATE(es.message_time)
                    ORDER BY date
                """),
                params,
            )
            rows = result.fetchall()

        from app.schemas.admin import EmotionTrendEntry, EmotionTrendsResponse

        trends = [
            EmotionTrendEntry(
                date=str(r[0]), avg_score=round(float(r[1]), 3),
                message_count=int(r[2]), negative_count=int(r[3]), positive_count=int(r[4]),
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_emotion_trends",
            resource_type="emotion_scores", resource_id="trends",
            user_id=user.user_id, details={"days": days},
        )
        return EmotionTrendsResponse(
            trends=trends,
            period_start=str(rows[0][0]) if rows else None,
            period_end=str(rows[-1][0]) if rows else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get emotion trends error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


# =============================================
# Phase 2: Tasks endpoints
# =============================================


@router.get(
    "/tasks/overview",
    summary="タスク全体サマリー",
    description="ChatWork/自律/検出タスクの全体サマリー（Level 5+）",
)
async def get_tasks_overview(
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            # ChatWork tasks
            cw_result = conn.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'open') AS open,
                        COUNT(*) FILTER (WHERE status = 'done') AS done,
                        COUNT(*) FILTER (WHERE status = 'open' AND limit_time IS NOT NULL
                                         AND to_timestamp(limit_time) < NOW()) AS overdue
                    FROM chatwork_tasks
                    WHERE organization_id = :org_id
                """),
                {"org_id": organization_id},
            )
            cw = cw_result.fetchone()

            # Autonomous tasks (table may not exist yet)
            try:
                at_result = conn.execute(
                    text("""
                        SELECT
                            COUNT(*) AS total,
                            COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                            COUNT(*) FILTER (WHERE status = 'running') AS running,
                            COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                            COUNT(*) FILTER (WHERE status = 'failed') AS failed
                        FROM autonomous_tasks
                        WHERE organization_id = :org_id
                    """),
                    {"org_id": organization_id},
                )
                at = at_result.fetchone()
            except Exception:
                conn.rollback()
                at = (0, 0, 0, 0, 0)

            # Detected tasks
            dt_result = conn.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'processed') AS processed,
                        COUNT(*) FILTER (WHERE status != 'processed' OR status IS NULL) AS unprocessed
                    FROM detected_tasks
                    WHERE organization_id = :org_id
                """),
                {"org_id": organization_id},
            )
            dt = dt_result.fetchone()

        from app.schemas.admin import TaskOverviewStats

        log_audit_event(
            logger=logger, action="get_tasks_overview",
            resource_type="tasks", resource_id="overview",
            user_id=user.user_id, details={},
        )
        return TaskOverviewStats(
            chatwork_tasks={"total": int(cw[0]), "open": int(cw[1]), "done": int(cw[2]), "overdue": int(cw[3])},
            autonomous_tasks={"total": int(at[0]), "pending": int(at[1]), "running": int(at[2]),
                              "completed": int(at[3]), "failed": int(at[4])},
            detected_tasks={"total": int(dt[0]), "processed": int(dt[1]), "unprocessed": int(dt[2])},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get tasks overview error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/tasks/list",
    summary="タスク一覧取得",
    description="全タスクソースを統合した一覧（Level 5+）",
)
async def get_tasks_list(
    user: UserContext = Depends(require_admin),
    source: Optional[str] = Query(None, description="ソースフィルタ（chatwork/autonomous/detected）"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            tasks = []

            if source is None or source == "chatwork":
                cw_result = conn.execute(
                    text("""
                        SELECT task_id::text, summary, body, status,
                               assigned_to_name, limit_time, created_at
                        FROM chatwork_tasks
                        WHERE organization_id = :org_id
                        ORDER BY created_at DESC
                        LIMIT :limit OFFSET :offset
                    """),
                    {"org_id": organization_id, "limit": limit, "offset": offset},
                )
                for r in cw_result.fetchall():
                    title = r[1] or (r[2][:80] + "..." if r[2] and len(r[2]) > 80 else r[2] or "")
                    deadline = None
                    if r[5]:
                        from datetime import datetime as dt_mod
                        deadline = dt_mod.utcfromtimestamp(int(r[5])).strftime("%Y-%m-%d")
                    tasks.append({"id": r[0], "source": "chatwork", "title": title,
                                  "status": r[3] or "unknown", "assignee_name": r[4],
                                  "deadline": deadline,
                                  "created_at": str(r[6]) if r[6] else None})

            if source is None or source == "autonomous":
                try:
                    at_result = conn.execute(
                        text("""
                            SELECT id::text, title, status, requested_by, scheduled_at, created_at
                            FROM autonomous_tasks
                            WHERE organization_id = :org_id
                            ORDER BY created_at DESC
                            LIMIT :limit OFFSET :offset
                        """),
                        {"org_id": organization_id, "limit": limit, "offset": offset},
                    )
                    for r in at_result.fetchall():
                        tasks.append({"id": r[0], "source": "autonomous", "title": r[1],
                                      "status": r[2], "assignee_name": r[3],
                                      "deadline": str(r[4]) if r[4] else None,
                                      "created_at": str(r[5]) if r[5] else None})
                except Exception:
                    conn.rollback()

            if source is None or source == "detected":
                dt_result = conn.execute(
                    text("""
                        SELECT id::text, task_content, status, account_id, NULL, detected_at
                        FROM detected_tasks
                        WHERE organization_id = :org_id
                        ORDER BY detected_at DESC
                        LIMIT :limit OFFSET :offset
                    """),
                    {"org_id": organization_id, "limit": limit, "offset": offset},
                )
                for r in dt_result.fetchall():
                    tasks.append({"id": r[0], "source": "detected", "title": r[1] or "",
                                  "status": r[2] or "detected", "assignee_name": r[3],
                                  "deadline": r[4],
                                  "created_at": str(r[5]) if r[5] else None})

        # Sort by created_at descending
        tasks.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        tasks = tasks[:limit]

        from app.schemas.admin import TaskItem, TaskListResponse

        task_items = [TaskItem(**t) for t in tasks]

        log_audit_event(
            logger=logger, action="get_tasks_list",
            resource_type="tasks", resource_id="list",
            user_id=user.user_id, details={"count": len(task_items), "source": source},
        )
        return TaskListResponse(tasks=task_items, total_count=len(task_items))

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get tasks list error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


# =============================================
# Phase 3: Insights endpoints
# =============================================


@router.get(
    "/insights",
    summary="インサイト一覧取得",
    description="AI生成インサイトの一覧（Level 5+）",
)
async def get_insights_list(
    user: UserContext = Depends(require_admin),
    importance: Optional[str] = Query(None, description="重要度フィルタ"),
    insight_status: Optional[str] = Query(None, alias="status", description="ステータスフィルタ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            where_clauses = ["si.organization_id = :org_id"]
            params: dict = {"org_id": organization_id, "limit": limit, "offset": offset}

            if importance:
                where_clauses.append("si.importance = :importance")
                params["importance"] = importance
            if insight_status:
                where_clauses.append("si.status = :insight_status")
                params["insight_status"] = insight_status

            where_sql = " AND ".join(where_clauses)

            result = conn.execute(
                text(f"""
                    SELECT si.id, si.insight_type, si.source_type, si.importance,
                           si.title, si.description, si.recommended_action,
                           si.status, d.name AS department_name, si.created_at
                    FROM soulkun_insights si
                    LEFT JOIN departments d ON si.department_id = d.id
                    WHERE {where_sql}
                    ORDER BY si.created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM soulkun_insights si WHERE {where_sql}"),
                params,
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import InsightSummary, InsightsListResponse

        insights = [
            InsightSummary(
                id=str(r[0]), insight_type=r[1], source_type=r[2],
                importance=r[3], title=r[4], description=r[5],
                recommended_action=r[6], status=r[7],
                department_name=r[8],
                created_at=str(r[9]) if r[9] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_insights_list",
            resource_type="insights", resource_id="list",
            user_id=user.user_id, details={"count": len(insights)},
        )
        return InsightsListResponse(insights=insights, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get insights list error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/insights/patterns",
    summary="質問パターン一覧",
    description="よくある質問パターンの一覧（Level 5+）",
)
async def get_question_patterns(
    user: UserContext = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, question_category, normalized_question,
                           occurrence_count, last_asked_at, status
                    FROM question_patterns
                    WHERE organization_id = :org_id
                    ORDER BY occurrence_count DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"org_id": organization_id, "limit": limit, "offset": offset},
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text("SELECT COUNT(*) FROM question_patterns WHERE organization_id = :org_id"),
                {"org_id": organization_id},
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import QuestionPatternSummary, QuestionPatternsResponse

        patterns = [
            QuestionPatternSummary(
                id=str(r[0]), question_category=r[1],
                normalized_question=r[2], occurrence_count=int(r[3]),
                last_asked_at=str(r[4]) if r[4] else None, status=r[5],
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_question_patterns",
            resource_type="question_patterns", resource_id="list",
            user_id=user.user_id, details={"count": len(patterns)},
        )
        return QuestionPatternsResponse(patterns=patterns, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get question patterns error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/insights/weekly-reports",
    summary="週次レポート一覧",
    description="週次レポートの一覧（Level 5+）",
)
async def get_weekly_reports(
    user: UserContext = Depends(require_admin),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, week_start, week_end, status, sent_at, sent_via
                    FROM soulkun_weekly_reports
                    WHERE organization_id = :org_id
                    ORDER BY week_start DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"org_id": organization_id, "limit": limit, "offset": offset},
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text("SELECT COUNT(*) FROM soulkun_weekly_reports WHERE organization_id = :org_id"),
                {"org_id": organization_id},
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import WeeklyReportSummary, WeeklyReportsResponse

        reports = [
            WeeklyReportSummary(
                id=str(r[0]), week_start=str(r[1]), week_end=str(r[2]),
                status=r[3], sent_at=str(r[4]) if r[4] else None, sent_via=r[5],
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_weekly_reports",
            resource_type="weekly_reports", resource_id="list",
            user_id=user.user_id, details={"count": len(reports)},
        )
        return WeeklyReportsResponse(reports=reports, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get weekly reports error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


# =============================================
# Phase 3: Meetings endpoints
# =============================================


@router.get(
    "/meetings",
    summary="ミーティング一覧",
    description="ミーティングの一覧（Level 5+）",
)
async def get_meetings_list(
    user: UserContext = Depends(require_admin),
    meeting_status: Optional[str] = Query(None, alias="status", description="ステータスフィルタ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            where_clauses = ["m.organization_id = :org_id"]
            params: dict = {"org_id": organization_id, "limit": limit, "offset": offset}

            if meeting_status:
                where_clauses.append("m.status = :meeting_status")
                params["meeting_status"] = meeting_status

            where_sql = " AND ".join(where_clauses)

            result = conn.execute(
                text(f"""
                    SELECT m.id, m.title, m.meeting_type, m.meeting_date,
                           m.duration_seconds, m.status, m.source,
                           EXISTS(SELECT 1 FROM meeting_transcripts mt
                                  WHERE mt.meeting_id = m.id
                                    AND mt.organization_id = :org_id
                                    AND mt.deleted_at IS NULL) AS has_transcript,
                           EXISTS(SELECT 1 FROM meeting_recordings mr
                                  WHERE mr.meeting_id = m.id
                                    AND mr.organization_id = :org_id
                                    AND mr.deleted_at IS NULL) AS has_recording
                    FROM meetings m
                    WHERE {where_sql}
                    ORDER BY m.meeting_date DESC NULLS LAST
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM meetings m WHERE {where_sql}"),
                params,
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import MeetingSummary, MeetingsListResponse

        meetings = [
            MeetingSummary(
                id=str(r[0]), title=r[1], meeting_type=r[2],
                meeting_date=str(r[3]) if r[3] else None,
                duration_seconds=float(r[4]) if r[4] else None,
                status=r[5], source=r[6],
                has_transcript=bool(r[7]), has_recording=bool(r[8]),
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_meetings_list",
            resource_type="meetings", resource_id="list",
            user_id=user.user_id, details={"count": len(meetings)},
        )
        return MeetingsListResponse(meetings=meetings, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get meetings list error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/meetings/{meeting_id}",
    summary="ミーティング詳細",
    description="ミーティングの詳細（議事録・録音含む）（Level 5+）",
)
async def get_meeting_detail(
    meeting_id: str,
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            # ミーティング基本情報
            m_result = conn.execute(
                text("""
                    SELECT m.id, m.title, m.meeting_type, m.meeting_date,
                           m.duration_seconds, m.status, m.source
                    FROM meetings m
                    WHERE m.id = :meeting_id AND m.organization_id = :org_id
                """),
                {"meeting_id": meeting_id, "org_id": organization_id},
            )
            m_row = m_result.fetchone()
            if not m_row:
                raise HTTPException(status_code=404, detail={"status": "failed", "error_message": "ミーティングが見つかりません"})

            # 議事録
            transcript_text = None
            try:
                t_result = conn.execute(
                    text("""
                        SELECT mt.transcript_text
                        FROM meeting_transcripts mt
                        WHERE mt.meeting_id = :meeting_id
                          AND mt.organization_id = :org_id
                          AND mt.deleted_at IS NULL
                        ORDER BY mt.created_at DESC LIMIT 1
                    """),
                    {"meeting_id": meeting_id, "org_id": organization_id},
                )
                t_row = t_result.fetchone()
                if t_row:
                    transcript_text = t_row[0]
            except Exception:
                pass  # meeting_transcripts テーブルがない場合はスキップ

            log_audit_event(
                logger=logger, action="get_meeting_detail",
                resource_type="meetings", resource_id=meeting_id,
                user_id=user.user_id, details={},
            )
            return {
                "status": "success",
                "meeting": {
                    "id": str(m_row[0]),
                    "title": m_row[1],
                    "meeting_type": m_row[2],
                    "meeting_date": str(m_row[3]) if m_row[3] else None,
                    "duration_seconds": float(m_row[4]) if m_row[4] else None,
                    "status": m_row[5],
                    "source": m_row[6],
                },
                "transcript": transcript_text,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get meeting detail error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


# =============================================
# Phase 3: Proactive endpoints
# =============================================


@router.get(
    "/proactive/actions",
    summary="プロアクティブアクション一覧",
    description="プロアクティブアクションの一覧（Level 5+）",
)
async def get_proactive_actions(
    user: UserContext = Depends(require_admin),
    trigger_type: Optional[str] = Query(None, description="トリガータイプフィルタ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            where_clauses = ["pa.organization_id = :org_id"]
            params: dict = {"org_id": organization_id, "limit": limit, "offset": offset}

            if trigger_type:
                where_clauses.append("pa.trigger_type = :trigger_type")
                params["trigger_type"] = trigger_type

            where_sql = " AND ".join(where_clauses)

            result = conn.execute(
                text(f"""
                    SELECT pa.id, pa.user_id, pa.trigger_type, pa.priority,
                           pa.message_type, pa.user_response_positive, pa.created_at
                    FROM proactive_action_logs pa
                    WHERE {where_sql}
                    ORDER BY pa.created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM proactive_action_logs pa WHERE {where_sql}"),
                params,
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import ProactiveActionSummary, ProactiveActionsResponse

        actions = [
            ProactiveActionSummary(
                id=str(r[0]), user_id=str(r[1]),
                trigger_type=r[2], priority=r[3],
                message_type=r[4],
                user_response_positive=r[5],
                created_at=str(r[6]) if r[6] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_proactive_actions",
            resource_type="proactive_actions", resource_id="list",
            user_id=user.user_id, details={"count": len(actions)},
        )
        return ProactiveActionsResponse(actions=actions, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get proactive actions error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/proactive/stats",
    summary="プロアクティブ統計",
    description="プロアクティブアクションの統計（Level 5+）",
)
async def get_proactive_stats(
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE user_response_positive = TRUE) AS positive,
                        COUNT(*) FILTER (WHERE user_response_positive IS NOT NULL) AS responded
                    FROM proactive_action_logs
                    WHERE organization_id = :org_id
                """),
                {"org_id": organization_id},
            )
            stats = result.fetchone()
            total = int(stats[0])
            positive = int(stats[1])
            responded = int(stats[2])

            by_type_result = conn.execute(
                text("""
                    SELECT trigger_type,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE user_response_positive = TRUE) AS positive
                    FROM proactive_action_logs
                    WHERE organization_id = :org_id
                    GROUP BY trigger_type
                    ORDER BY total DESC
                """),
                {"org_id": organization_id},
            )
            by_type = [
                {"trigger_type": r[0], "total": int(r[1]), "positive": int(r[2])}
                for r in by_type_result.fetchall()
            ]

        from app.schemas.admin import ProactiveStatsResponse

        log_audit_event(
            logger=logger, action="get_proactive_stats",
            resource_type="proactive_actions", resource_id="stats",
            user_id=user.user_id, details={},
        )
        return ProactiveStatsResponse(
            total_actions=total,
            positive_responses=positive,
            response_rate=round(positive / responded * 100, 1) if responded > 0 else 0.0,
            by_trigger_type=by_type,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get proactive stats error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


# =============================================
# Phase 4: Teachings endpoints
# =============================================


@router.get(
    "/teachings",
    summary="CEO教え一覧",
    description="CEO教えの一覧（Level 5+）",
)
async def get_teachings_list(
    user: UserContext = Depends(require_admin),
    category: Optional[str] = Query(None, description="カテゴリフィルタ"),
    active_only: bool = Query(False, description="有効なもののみ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            where_clauses = ["organization_id = :org_id"]
            params: dict = {"org_id": organization_id, "limit": limit, "offset": offset}

            if category:
                where_clauses.append("category = :category")
                params["category"] = category
            if active_only:
                where_clauses.append("is_active = TRUE")

            where_sql = " AND ".join(where_clauses)

            result = conn.execute(
                text(f"""
                    SELECT id, category, subcategory, statement,
                           validation_status, priority, is_active,
                           usage_count, helpful_count, last_used_at
                    FROM ceo_teachings
                    WHERE {where_sql}
                    ORDER BY priority ASC NULLS LAST, usage_count DESC NULLS LAST
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM ceo_teachings WHERE {where_sql}"),
                params,
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import TeachingSummary, TeachingsListResponse

        teachings = [
            TeachingSummary(
                id=str(r[0]), category=r[1], subcategory=r[2],
                statement=r[3], validation_status=r[4],
                priority=r[5], is_active=r[6],
                usage_count=r[7], helpful_count=r[8],
                last_used_at=str(r[9]) if r[9] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_teachings_list",
            resource_type="teachings", resource_id="list",
            user_id=user.user_id, details={"count": len(teachings)},
        )
        return TeachingsListResponse(teachings=teachings, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get teachings list error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/teachings/conflicts",
    summary="教え矛盾一覧",
    description="検出された教え間の矛盾一覧（Level 5+）",
)
async def get_teaching_conflicts(
    user: UserContext = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, teaching_id, conflict_type, severity,
                           description, conflicting_teaching_id, created_at
                    FROM ceo_teaching_conflicts
                    WHERE organization_id = :org_id
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"org_id": organization_id, "limit": limit, "offset": offset},
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text("SELECT COUNT(*) FROM ceo_teaching_conflicts WHERE organization_id = :org_id"),
                {"org_id": organization_id},
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import TeachingConflictSummary, TeachingConflictsResponse

        conflicts = [
            TeachingConflictSummary(
                id=str(r[0]), teaching_id=str(r[1]),
                conflict_type=r[2], severity=r[3],
                description=r[4],
                conflicting_teaching_id=str(r[5]) if r[5] else None,
                created_at=str(r[6]) if r[6] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_teaching_conflicts",
            resource_type="teaching_conflicts", resource_id="list",
            user_id=user.user_id, details={"count": len(conflicts)},
        )
        return TeachingConflictsResponse(conflicts=conflicts, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get teaching conflicts error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/teachings/usage-stats",
    summary="教え利用統計",
    description="教えの利用統計（Level 5+）",
)
async def get_teaching_usage_stats(
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE was_helpful = TRUE) AS helpful,
                        COUNT(*) FILTER (WHERE was_helpful IS NOT NULL) AS responded
                    FROM teaching_usage_logs
                    WHERE organization_id = :org_id
                """),
                {"org_id": organization_id},
            )
            stats = result.fetchone()
            total = int(stats[0])
            helpful = int(stats[1])
            responded = int(stats[2])

            by_cat_result = conn.execute(
                text("""
                    SELECT t.category, COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE ul.was_helpful = TRUE) AS helpful
                    FROM teaching_usage_logs ul
                    JOIN ceo_teachings t ON ul.teaching_id = t.id
                    WHERE ul.organization_id = :org_id
                    GROUP BY t.category
                    ORDER BY total DESC
                """),
                {"org_id": organization_id},
            )
            by_category = [
                {"category": r[0], "usage_count": int(r[1]), "helpful_count": int(r[2])}
                for r in by_cat_result.fetchall()
            ]

        from app.schemas.admin import TeachingUsageStatsResponse

        log_audit_event(
            logger=logger, action="get_teaching_usage_stats",
            resource_type="teaching_usage", resource_id="stats",
            user_id=user.user_id, details={},
        )
        return TeachingUsageStatsResponse(
            total_usages=total,
            helpful_rate=round(helpful / responded * 100, 1) if responded > 0 else 0.0,
            by_category=by_category,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get teaching usage stats error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


# =============================================
# Phase 4: System Health endpoints
# =============================================


@router.get(
    "/system/health",
    summary="システムヘルスサマリー",
    description="最新日のシステムヘルスサマリー（Level 5+）",
)
async def get_system_health(
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT metric_date, total_conversations, unique_users,
                           avg_response_time_ms, p95_response_time_ms,
                           success_count, error_count, avg_confidence
                    FROM brain_daily_metrics
                    WHERE organization_id = :org_id
                    ORDER BY metric_date DESC
                    LIMIT 1
                """),
                {"org_id": organization_id},
            )
            row = result.fetchone()

        from app.schemas.admin import SystemHealthSummary

        if not row:
            return SystemHealthSummary()

        total = (int(row[5] or 0) + int(row[6] or 0))
        success_rate = round(int(row[5] or 0) / total * 100, 1) if total > 0 else 0.0

        log_audit_event(
            logger=logger, action="get_system_health",
            resource_type="system", resource_id="health",
            user_id=user.user_id, details={},
        )
        return SystemHealthSummary(
            latest_date=str(row[0]),
            total_conversations=int(row[1] or 0),
            unique_users=int(row[2] or 0),
            avg_response_time_ms=row[3],
            p95_response_time_ms=row[4],
            success_rate=success_rate,
            error_count=int(row[6] or 0),
            avg_confidence=round(float(row[7]), 3) if row[7] else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get system health error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/system/metrics",
    summary="システムメトリクス推移",
    description="日次メトリクスの推移（Level 5+）",
)
async def get_system_metrics(
    user: UserContext = Depends(require_admin),
    days: int = Query(30, ge=7, le=90, description="取得期間"),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT metric_date, total_conversations, unique_users,
                           avg_response_time_ms, success_count, error_count,
                           avg_confidence
                    FROM brain_daily_metrics
                    WHERE organization_id = :org_id
                      AND metric_date >= CURRENT_DATE - :days
                    ORDER BY metric_date
                """),
                {"org_id": organization_id, "days": days},
            )
            rows = result.fetchall()

        from app.schemas.admin import DailyMetricEntry, SystemMetricsResponse

        metrics = [
            DailyMetricEntry(
                metric_date=str(r[0]),
                total_conversations=int(r[1] or 0),
                unique_users=int(r[2] or 0),
                avg_response_time_ms=r[3],
                success_count=int(r[4] or 0),
                error_count=int(r[5] or 0),
                avg_confidence=round(float(r[6]), 3) if r[6] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_system_metrics",
            resource_type="system", resource_id="metrics",
            user_id=user.user_id, details={"days": days},
        )
        return SystemMetricsResponse(metrics=metrics)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get system metrics error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/system/diagnoses",
    summary="自己診断一覧",
    description="Brain自己診断の一覧（Level 5+）",
)
async def get_self_diagnoses(
    user: UserContext = Depends(require_admin),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        rows = []
        total = 0
        with pool.connect() as conn:
            try:
                result = conn.execute(
                    text("""
                        SELECT id, diagnosis_type, period_start, period_end,
                               overall_score, total_interactions,
                               successful_interactions, identified_weaknesses
                        FROM brain_self_diagnoses
                        WHERE organization_id = :org_id
                        ORDER BY period_end DESC
                        LIMIT :limit OFFSET :offset
                    """),
                    {"org_id": organization_id, "limit": limit, "offset": offset},
                )
                rows = result.fetchall()

                count_result = conn.execute(
                    text("SELECT COUNT(*) FROM brain_self_diagnoses WHERE organization_id = :org_id"),
                    {"org_id": organization_id},
                )
                total = int(count_result.fetchone()[0])
            except Exception:
                conn.rollback()

        from app.schemas.admin import SelfDiagnosisSummary, SelfDiagnosesResponse

        diagnoses = [
            SelfDiagnosisSummary(
                id=str(r[0]), diagnosis_type=r[1],
                period_start=str(r[2]) if r[2] else None,
                period_end=str(r[3]) if r[3] else None,
                overall_score=round(float(r[4]), 1),
                total_interactions=int(r[5]),
                successful_interactions=int(r[6]),
                identified_weaknesses=list(r[7]) if r[7] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_self_diagnoses",
            resource_type="system", resource_id="diagnoses",
            user_id=user.user_id, details={"count": len(diagnoses)},
        )
        return SelfDiagnosesResponse(diagnoses=diagnoses, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get self diagnoses error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )
