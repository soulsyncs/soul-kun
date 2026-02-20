"""
Admin Dashboard - Cost Management Endpoints

月次コストサマリー、日次コスト、コスト内訳。
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import log_audit_event

from .deps import (
    JST,
    logger,
    require_admin,
    UserContext,
)
from app.schemas.admin import (
    CostMonthlyResponse,
    CostMonthlyEntry,
    CostDailyResponse,
    CostDailyEntry,
    CostBreakdownResponse,
    CostModelBreakdown,
    CostTierBreakdown,
    AiRoiResponse,
    AiRoiTierBreakdown,
    BudgetUpdateRequest,
    BudgetUpdateResponse,
    AdminErrorResponse,
)

router = APIRouter()


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
                        COALESCE(total_cost_jpy, 0) as total_cost,
                        COALESCE(total_requests, 0) as requests,
                        budget_jpy,
                        CASE
                            WHEN budget_jpy IS NOT NULL AND total_cost_jpy > budget_jpy
                                THEN 'exceeded'
                            WHEN budget_jpy IS NOT NULL AND total_cost_jpy > budget_jpy * 0.8
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
                        COALESCE(SUM(cost_jpy), 0) as cost,
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
                        COALESCE(model_id, 'unknown') as model,
                        COALESCE(SUM(cost_jpy), 0) as cost,
                        COUNT(*) as requests
                    FROM ai_usage_logs
                    WHERE organization_id = :org_id
                      AND created_at >= :start_date
                    GROUP BY model_id
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
                        COALESCE(tier, 'unknown') as tier,
                        COALESCE(SUM(cost_jpy), 0) as cost,
                        COUNT(*) as requests
                    FROM ai_usage_logs
                    WHERE organization_id = :org_id
                      AND created_at >= :start_date
                    GROUP BY tier
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


# ROI換算係数（ティアごとの「1リクエストあたり削減時間（分）」）
# 人手で同じことをやるのに何分かかるかの推定値
_ROI_MINUTES_PER_REQUEST: dict[str, float] = {
    "brain": 10.0,       # 思考・判断：会話整理・次アクション決定
    "assistant": 5.0,    # 回答・要約：メール返答・情報収集
    "generation": 15.0,  # 文書生成：議事録・提案書
    "embedding": 0.5,    # ベクトル検索：情報分類
    "unknown": 3.0,      # 不明
}
_LABOR_COST_PER_HOUR_JPY = 3_000.0  # ナレッジワーカー平均時給（円）


@router.get(
    "/costs/ai-roi",
    response_model=AiRoiResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="AI費用対効果（ROI）取得",
    description="""
AIへの投資費用と、それによって削減できた人件費・工数を比較したROIレポート。

## 計算方法
- ティアごとに「1リクエストあたり削減時間（分）」の係数を掛けて工数を算出
- 削減工数 × 時給（3,000円）＝ 削減人件費
- ROI倍率 = 削減人件費 ÷ AI費用

## データソース
- ai_usage_logs テーブル（ティア別リクエスト数・コスト）
    """,
)
async def get_ai_roi(
    days: int = Query(
        30,
        ge=1,
        le=90,
        description="集計日数（デフォルト30日）",
    ),
    user: UserContext = Depends(require_admin),
):
    """AI費用対効果（ROI）を取得"""

    organization_id = user.organization_id
    now = datetime.now(JST)
    start_date = (now - timedelta(days=days)).date()

    logger.info(
        "Get AI ROI",
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
                        COALESCE(tier, 'unknown') as tier,
                        COUNT(*) as requests,
                        COALESCE(SUM(cost_jpy), 0) as cost
                    FROM ai_usage_logs
                    WHERE organization_id = :org_id
                      AND created_at >= :start_date
                    GROUP BY tier
                    ORDER BY cost DESC
                """),
                {"org_id": organization_id, "start_date": start_date},
            )
            rows = result.fetchall()

        by_tier = []
        total_cost = 0.0
        total_requests = 0
        total_time_saved_hours = 0.0
        total_labor_saved = 0.0

        for row in rows:
            tier = str(row[0])
            requests = int(row[1])
            cost = float(row[2])
            minutes_per_req = _ROI_MINUTES_PER_REQUEST.get(tier, _ROI_MINUTES_PER_REQUEST["unknown"])
            time_saved_hours = (requests * minutes_per_req) / 60.0
            labor_saved = time_saved_hours * _LABOR_COST_PER_HOUR_JPY

            by_tier.append(
                AiRoiTierBreakdown(
                    tier=tier,
                    requests=requests,
                    cost_jpy=round(cost, 2),
                    time_saved_hours=round(time_saved_hours, 2),
                    labor_saved_jpy=round(labor_saved, 0),
                )
            )
            total_cost += cost
            total_requests += requests
            total_time_saved_hours += time_saved_hours
            total_labor_saved += labor_saved

        roi_multiplier = (total_labor_saved / total_cost) if total_cost > 0 else 0.0

        log_audit_event(
            logger=logger,
            action="get_ai_roi",
            resource_type="cost",
            resource_id=organization_id,
            user_id=user.user_id,
            details={"days": days, "roi_multiplier": round(roi_multiplier, 2)},
        )

        return AiRoiResponse(
            status="success",
            days=days,
            total_cost_jpy=round(total_cost, 2),
            total_requests=total_requests,
            time_saved_hours=round(total_time_saved_hours, 2),
            labor_saved_jpy=round(total_labor_saved, 0),
            roi_multiplier=round(roi_multiplier, 2),
            by_tier=by_tier,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get AI ROI error",
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
    "/costs/budget",
    response_model=BudgetUpdateResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="月間予算設定",
    description="""
指定した年月の月間予算（円）を設定する。
行が存在しない場合は新規作成し、存在する場合は budget_jpy を更新する。

## データソース
- ai_monthly_cost_summary テーブル
    """,
)
async def update_monthly_budget(
    body: BudgetUpdateRequest,
    user: UserContext = Depends(require_admin),
):
    """月間予算を設定"""

    organization_id = user.organization_id

    logger.info(
        "Update monthly budget",
        organization_id=organization_id,
        year_month=body.year_month,
        budget_jpy=body.budget_jpy,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO ai_monthly_cost_summary
                        (id, organization_id, year_month,
                         total_cost_jpy, total_requests,
                         budget_jpy, budget_remaining_jpy,
                         created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), :org_id, :year_month,
                         0, 0,
                         :budget_jpy, :budget_jpy,
                         NOW(), NOW())
                    ON CONFLICT (organization_id, year_month) DO UPDATE SET
                        budget_jpy = :budget_jpy,
                        budget_remaining_jpy = :budget_jpy - COALESCE(ai_monthly_cost_summary.total_cost_jpy, 0),
                        updated_at = NOW()
                """),
                {
                    "org_id": organization_id,
                    "year_month": body.year_month,
                    "budget_jpy": body.budget_jpy,
                },
            )
            conn.commit()

        log_audit_event(
            logger=logger,
            action="update_monthly_budget",
            resource_type="cost",
            resource_id=organization_id,
            user_id=user.user_id,
            details={"year_month": body.year_month, "budget_jpy": body.budget_jpy},
        )

        return BudgetUpdateResponse(
            status="success",
            year_month=body.year_month,
            budget_jpy=body.budget_jpy,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Update monthly budget error",
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
