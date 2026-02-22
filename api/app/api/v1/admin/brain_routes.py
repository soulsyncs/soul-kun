"""
Admin Dashboard - Brain Metrics/Logs Endpoints

Brain日次メトリクス、Brain決定ログ取得。
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
    BrainMetricsResponse,
    BrainDailyMetric,
    BrainLogsResponse,
    BrainLogEntry,
    LearningPatternEntry,
    LearningPatternsResponse,
    ValidatePatternRequest,
    ValidatePatternResponse,
    AdminErrorResponse,
)

router = APIRouter()


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
                        bdl.metric_date,
                        bdl.conversations,
                        bdl.avg_latency_ms,
                        bdl.error_rate,
                        COALESCE(al.total_cost, 0) as cost
                    FROM (
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
                            END as error_rate
                        FROM brain_decision_logs
                        WHERE organization_id = :org_id
                          AND created_at >= :start_date
                        GROUP BY DATE(created_at)
                    ) bdl
                    LEFT JOIN (
                        SELECT
                            DATE(created_at) as cost_date,
                            SUM(cost_jpy) as total_cost
                        FROM ai_usage_logs
                        WHERE organization_id = :org_id
                          AND created_at >= :start_date
                        GROUP BY DATE(created_at)
                    ) al ON bdl.metric_date = al.cost_date
                    ORDER BY bdl.metric_date ASC
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


@router.get(
    "/brain/learning/patterns",
    response_model=LearningPatternsResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="学習パターン一覧取得（Human-in-the-loop確認用）",
    description="""
ソウルくんが自動抽出した学習パターンを返す。

## 管理者確認フロー（Human-in-the-loop）
- is_validated=false のパターンが「未確認」
- 管理者は PATCH /brain/learning/patterns/{id}/validate で承認/却下できる
- 承認: is_validated=true → 本番の判断に反映
- 却下: is_active=false → パターン無効化

## パラメータ
- unvalidated_only: true（デフォルト）で未確認のみ取得
- limit/offset: ページネーション
    """,
)
async def get_learning_patterns(
    unvalidated_only: bool = Query(
        True,
        description="未確認のみ取得（デフォルト: true）",
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
    """学習パターン一覧を取得"""

    organization_id = user.organization_id

    logger.info(
        "Get learning patterns",
        organization_id=organization_id,
        unvalidated_only=unvalidated_only,
        limit=limit,
        offset=offset,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            where_clause = "WHERE organization_id = :org_id AND is_active = true"
            if unvalidated_only:
                where_clause += " AND is_validated = false"

            result = conn.execute(
                text(f"""
                    SELECT
                        id,
                        pattern_type,
                        pattern_category,
                        scope,
                        sample_count,
                        success_count,
                        failure_count,
                        success_rate,
                        confidence_score,
                        is_active,
                        is_validated,
                        validated_at,
                        created_at
                    FROM brain_outcome_patterns
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"org_id": organization_id, "limit": limit, "offset": offset},
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"""
                    SELECT COUNT(*) as total
                    FROM brain_outcome_patterns
                    {where_clause}
                """),
                {"org_id": organization_id},
            )
            total_count = int(count_result.fetchone()[0])

        patterns = []
        for row in rows:
            patterns.append(
                LearningPatternEntry(
                    id=str(row[0]),
                    pattern_type=row[1] or "unknown",
                    pattern_category=row[2],
                    scope=row[3],
                    sample_count=int(row[4]) if row[4] is not None else 0,
                    success_count=int(row[5]) if row[5] is not None else 0,
                    failure_count=int(row[6]) if row[6] is not None else 0,
                    success_rate=float(row[7]) if row[7] is not None else None,
                    confidence_score=float(row[8]) if row[8] is not None else None,
                    is_active=bool(row[9]),
                    is_validated=bool(row[10]),
                    validated_at=row[11],
                    created_at=row[12],
                )
            )

        log_audit_event(
            logger=logger,
            action="get_learning_patterns",
            resource_type="brain_outcome_patterns",
            resource_id=organization_id,
            user_id=user.user_id,
            details={
                "unvalidated_only": unvalidated_only,
                "limit": limit,
                "offset": offset,
                "returned_count": len(patterns),
                "total_count": total_count,
            },
        )

        return LearningPatternsResponse(
            status="success",
            patterns=patterns,
            total_count=total_count,
            offset=offset,
            limit=limit,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get learning patterns error",
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


@router.patch(
    "/brain/learning/patterns/{pattern_id}/validate",
    response_model=ValidatePatternResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        404: {"model": AdminErrorResponse, "description": "パターンが見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="学習パターンを承認または却下",
    description="""
管理者が学習パターンを確認し、承認または却下する。

## 動作
- 承認（approved=true）: is_validated=true, validated_at=now() に更新
- 却下（approved=false）: is_active=false, is_validated=false に更新（パターン無効化）

## 権限
Level 5（管理部/取締役）以上が実行可能。
    """,
)
async def validate_learning_pattern(
    pattern_id: str,
    body: ValidatePatternRequest,
    user: UserContext = Depends(require_admin),
):
    """学習パターンを承認または却下する（Human-in-the-loop）"""

    organization_id = user.organization_id
    now = datetime.now()

    logger.info(
        "Validate learning pattern",
        organization_id=organization_id,
        pattern_id=pattern_id,
        approved=body.approved,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # パターンの存在確認（organization_idフィルタ必須 - 鉄則#1）
            check_result = conn.execute(
                text("""
                    SELECT id FROM brain_outcome_patterns
                    WHERE id = :pattern_id
                      AND organization_id = :org_id
                """),
                {"pattern_id": pattern_id, "org_id": organization_id},
            )
            if check_result.fetchone() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "NOT_FOUND",
                        "error_message": "パターンが見つかりません",
                    },
                )

            if body.approved:
                # 承認: 確認済みとしてマーク
                conn.execute(
                    text("""
                        UPDATE brain_outcome_patterns
                        SET is_validated = true,
                            validated_at = :now,
                            updated_at = :now
                        WHERE id = :pattern_id
                          AND organization_id = :org_id
                    """),
                    {"pattern_id": pattern_id, "org_id": organization_id, "now": now},
                )
            else:
                # 却下: パターンを無効化
                conn.execute(
                    text("""
                        UPDATE brain_outcome_patterns
                        SET is_active = false,
                            is_validated = false,
                            updated_at = :now
                        WHERE id = :pattern_id
                          AND organization_id = :org_id
                    """),
                    {"pattern_id": pattern_id, "org_id": organization_id, "now": now},
                )
            conn.commit()

        log_audit_event(
            logger=logger,
            action="validate_learning_pattern",
            resource_type="brain_outcome_patterns",
            resource_id=pattern_id,
            user_id=user.user_id,
            details={"approved": body.approved},
        )

        return ValidatePatternResponse(
            status="success",
            pattern_id=pattern_id,
            approved=body.approved,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Validate learning pattern error",
            organization_id=organization_id,
            pattern_id=pattern_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )
