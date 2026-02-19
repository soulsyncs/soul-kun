"""
Admin Dashboard - Teachings Endpoints

CEO教え一覧、教え矛盾一覧、教え利用統計。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import log_audit_event

from .deps import (
    DEFAULT_ORG_ID,
    logger,
    require_admin,
    UserContext,
)

router = APIRouter()


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


@router.get(
    "/teachings/penetration",
    summary="理念浸透度メーター",
    description="社長の教えがソウルくんの判断にどれだけ活用されているかを数値化（Level 5+）",
)
async def get_teaching_penetration(
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            # 全教えとそのusage_countを取得
            teachings_result = conn.execute(
                text("""
                    SELECT id, category, statement, COALESCE(usage_count, 0) AS usage_count
                    FROM ceo_teachings
                    WHERE organization_id = :org_id AND is_active = TRUE
                    ORDER BY usage_count DESC NULLS LAST
                """),
                {"org_id": organization_id},
            )
            all_teachings = teachings_result.fetchall()

        total_teachings = len(all_teachings)
        used_teachings = sum(1 for r in all_teachings if int(r[3]) > 0)
        total_usages = sum(int(r[3]) for r in all_teachings)
        overall_pct = round(used_teachings / total_teachings * 100, 1) if total_teachings > 0 else 0.0

        # カテゴリ別集計
        category_map: dict = {}
        for row in all_teachings:
            cat = str(row[1])
            cnt = int(row[3])
            if cat not in category_map:
                category_map[cat] = {"total": 0, "used": 0, "usages": 0}
            category_map[cat]["total"] += 1
            category_map[cat]["usages"] += cnt
            if cnt > 0:
                category_map[cat]["used"] += 1

        from app.schemas.admin import (
            TeachingPenetrationResponse,
            TeachingPenetrationCategory,
            TeachingPenetrationItem,
        )

        by_category = [
            TeachingPenetrationCategory(
                category=cat,
                total_teachings=v["total"],
                used_teachings=v["used"],
                total_usages=v["usages"],
                penetration_pct=round(v["used"] / v["total"] * 100, 1) if v["total"] > 0 else 0.0,
            )
            for cat, v in sorted(category_map.items(), key=lambda x: -x[1]["usages"])
        ]

        # TOP5 使われている教え
        top_teachings = [
            TeachingPenetrationItem(
                id=str(r[0]),
                statement=str(r[2])[:60],
                category=str(r[1]),
                usage_count=int(r[3]),
                penetration_pct=round(int(r[3]) / total_usages * 100, 1) if total_usages > 0 else 0.0,
            )
            for r in all_teachings[:5]
            if int(r[3]) > 0
        ]

        # 未使用の教え（上限10件）
        unused_teachings = [
            TeachingPenetrationItem(
                id=str(r[0]),
                statement=str(r[2])[:60],
                category=str(r[1]),
                usage_count=0,
                penetration_pct=0.0,
            )
            for r in all_teachings
            if int(r[3]) == 0
        ][:10]

        log_audit_event(
            logger=logger, action="get_teaching_penetration",
            resource_type="teachings", resource_id="penetration",
            user_id=user.user_id,
            details={"total": total_teachings, "used": used_teachings},
        )
        return TeachingPenetrationResponse(
            status="success",
            total_teachings=total_teachings,
            used_teachings=used_teachings,
            total_usages=total_usages,
            overall_penetration_pct=overall_pct,
            by_category=by_category,
            top_teachings=top_teachings,
            unused_teachings=unused_teachings,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get teaching penetration error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )
