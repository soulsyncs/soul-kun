"""
Tasks API

Phase 1-B: タスク自動検知・監視API
Phase 3.5: 組織階層連携（アクセス制御）
"""

from datetime import date, datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Header, Query

from sqlalchemy import text

from lib.db import get_db_pool, get_async_db_pool
from lib.logging import get_logger, log_audit_event
from lib.tenant import get_current_or_default_tenant, DEFAULT_TENANT_ID
from app.schemas.task import (
    OverdueTaskResponse,
    OverdueTaskListResponse,
    OverdueSummary,
    TaskAssigneeInfo,
    TaskRequesterInfo,
    TaskErrorResponse,
)
from app.services.access_control import (
    AccessControlService,
    compute_accessible_departments_sync,
    get_user_role_level_sync,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = get_logger(__name__)

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

# 組織IDデフォルト（Phase 3.5: 社内専用）
DEFAULT_ORG_ID = DEFAULT_TENANT_ID


def classify_severity(days_overdue: int) -> tuple[str, str]:
    """
    超過日数から重度を判定

    Args:
        days_overdue: 超過日数

    Returns:
        (severity, severity_label) のタプル
    """
    if days_overdue >= 7:
        return ("severe", "🔴重度遅延")
    elif days_overdue >= 3:
        return ("moderate", "🟠中度遅延")
    else:
        return ("mild", "🟡軽度遅延")


@router.get(
    "/overdue",
    response_model=OverdueTaskListResponse,
    responses={
        400: {"model": TaskErrorResponse, "description": "バリデーションエラー"},
        403: {"model": TaskErrorResponse, "description": "権限エラー"},
        500: {"model": TaskErrorResponse, "description": "サーバーエラー"},
    },
    summary="期限超過タスク一覧取得",
    description="""
期限超過タスクの一覧を取得します。

## 機能概要
- 期限を過ぎたopenステータスのタスクを一覧で返します
- 3段階の重度分類（🔴重度/🟠中度/🟡軽度）を含みます
- ページネーション対応（limit/offset）
- Phase 3.5: 組織階層ベースのアクセス制御

## 重度分類
- 🔴 severe（重度）: 7日以上超過
- 🟠 moderate（中度）: 3-6日超過
- 🟡 mild（軽度）: 1-2日超過

## アクセス制御（Phase 3.5）
- X-User-ID ヘッダーが指定された場合、ユーザーの権限に基づきフィルタ
- Level 5-6: 全タスク閲覧可能
- Level 3-4: 自部署＋配下部署のタスクのみ
- Level 1-2: 自部署のタスクのみ
- department_id未設定タスクは全員閲覧可能（後方互換性）

## パラメータ
- **organization_id**: 組織ID（必須）
- **grace_days**: 猶予日数（デフォルト0、1を指定すると翌日から超過とみなす）
- **severity**: 重度フィルタ（severe/moderate/mild）
- **assigned_to_account_id**: 担当者でフィルタ
- **department_id**: 部署でフィルタ（Phase 3.5）
- **limit**: 取得件数（デフォルト100、最大1000）
- **offset**: オフセット（デフォルト0）
    """,
)
async def get_overdue_tasks(
    organization_id: str = Query(
        ...,
        description="組織ID",
        example="org_soulsyncs",
    ),
    grace_days: int = Query(
        0,
        ge=0,
        le=30,
        description="猶予日数（0=当日から超過、1=翌日から超過）",
    ),
    severity: Optional[str] = Query(
        None,
        pattern="^(severe|moderate|mild)$",
        description="重度フィルタ（severe/moderate/mild）",
    ),
    assigned_to_account_id: Optional[int] = Query(
        None,
        description="担当者のChatWork account_idでフィルタ",
    ),
    department_id: Optional[str] = Query(
        None,
        description="部署IDでフィルタ（Phase 3.5）",
    ),
    include_no_department: bool = Query(
        True,
        description="部署未設定タスクを含むか（デフォルトTrue）",
    ),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="取得件数（最大1000）",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="オフセット",
    ),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """
    期限超過タスク一覧を取得

    Phase 1-B: タスク自動検知APIの中核機能
    Phase 3.5: 組織階層ベースのアクセス制御

    設計書: docs/05_phase_1b_task_detection.md Step 2-1

    Args:
        organization_id: 組織ID
        grace_days: 猶予日数（デフォルト0）
        severity: 重度フィルタ（オプション）
        assigned_to_account_id: 担当者フィルタ（オプション）
        department_id: 部署フィルタ（オプション）
        include_no_department: 部署未設定タスクを含むか
        limit: 取得件数
        offset: オフセット

    Returns:
        期限超過タスクのリスト
    """
    logger.info(
        "Get overdue tasks started",
        organization_id=organization_id,
        grace_days=grace_days,
        severity=severity,
        department_id=department_id,
        user_id=x_user_id,
        limit=limit,
        offset=offset,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 現在日時（JST）
            now = datetime.now(JST)
            today = now.date()

            # 猶予日数を考慮した期限閾値
            cutoff_date = today - timedelta(days=grace_days)
            cutoff_timestamp = int(
                datetime.combine(cutoff_date, datetime.min.time())
                .replace(tzinfo=JST)
                .timestamp()
            )

            # Phase 3.5: ユーザーのアクセス可能部署を取得
            accessible_departments: Optional[List[str]] = None
            user_role_level = 2  # デフォルト: 一般社員

            if x_user_id:
                try:
                    user_role_level = get_user_role_level_sync(conn, x_user_id)
                    logger.info(f"User role level: {user_role_level}", user_id=x_user_id)

                    # Level 5以上は全部署アクセス可能
                    if user_role_level < 5:
                        accessible_departments = compute_accessible_departments_sync(
                            conn, x_user_id, organization_id
                        )
                        logger.info(
                            f"Accessible departments: {len(accessible_departments) if accessible_departments else 0}",
                            user_id=x_user_id,
                        )
                except Exception as e:
                    logger.warning(f"Failed to compute accessible departments: {e}")
                    # アクセス制御失敗時はフィルタなし（全タスク表示）

            # 期限超過タスクを取得
            query = """
                SELECT
                    task_id,
                    room_id,
                    room_name,
                    body,
                    summary,
                    limit_time,
                    assigned_to_account_id,
                    assigned_to_name,
                    assigned_by_account_id,
                    assigned_by_name,
                    status,
                    created_at,
                    department_id
                FROM chatwork_tasks
                WHERE status = 'open'
                  AND skip_tracking = FALSE
                  AND limit_time IS NOT NULL
                  AND limit_time < :cutoff_timestamp
            """
            params = {"cutoff_timestamp": cutoff_timestamp}

            # 担当者フィルタ
            if assigned_to_account_id:
                query += " AND assigned_to_account_id = :assigned_to_account_id"
                params["assigned_to_account_id"] = assigned_to_account_id

            # 部署フィルタ（明示的に指定された場合）
            if department_id:
                if include_no_department:
                    query += " AND (department_id = :department_id OR department_id IS NULL)"
                else:
                    query += " AND department_id = :department_id"
                params["department_id"] = department_id

            # Phase 3.5: アクセス制御による部署フィルタ
            elif accessible_departments is not None:
                if accessible_departments:
                    # アクセス可能な部署のタスク + 部署未設定タスク（後方互換性）
                    dept_placeholders = ", ".join(
                        f":dept_{i}" for i in range(len(accessible_departments))
                    )
                    query += f" AND (department_id IN ({dept_placeholders}) OR department_id IS NULL)"
                    for i, dept in enumerate(accessible_departments):
                        params[f"dept_{i}"] = dept
                else:
                    # アクセス可能部署なし → 部署未設定タスクのみ表示
                    query += " AND department_id IS NULL"

            # ソート: 超過日数の多い順（期限の古い順）
            query += " ORDER BY limit_time ASC"

            # ページネーション
            query += " LIMIT :limit OFFSET :offset"
            params["limit"] = limit
            params["offset"] = offset

            result = conn.execute(text(query), params)
            rows = result.fetchall()

            # 件数カウント（ページネーション用）
            count_query = """
                SELECT COUNT(*) as total
                FROM chatwork_tasks
                WHERE status = 'open'
                  AND skip_tracking = FALSE
                  AND limit_time IS NOT NULL
                  AND limit_time < :cutoff_timestamp
            """
            count_params = {"cutoff_timestamp": cutoff_timestamp}

            if assigned_to_account_id:
                count_query += " AND assigned_to_account_id = :assigned_to_account_id"
                count_params["assigned_to_account_id"] = assigned_to_account_id

            if department_id:
                if include_no_department:
                    count_query += " AND (department_id = :department_id OR department_id IS NULL)"
                else:
                    count_query += " AND department_id = :department_id"
                count_params["department_id"] = department_id
            elif accessible_departments is not None:
                if accessible_departments:
                    dept_placeholders = ", ".join(
                        f":dept_{i}" for i in range(len(accessible_departments))
                    )
                    count_query += f" AND (department_id IN ({dept_placeholders}) OR department_id IS NULL)"
                    for i, dept in enumerate(accessible_departments):
                        count_params[f"dept_{i}"] = dept
                else:
                    count_query += " AND department_id IS NULL"

            count_result = conn.execute(text(count_query), count_params)
            total_count = count_result.fetchone()[0]

        # レスポンス整形
        tasks = []
        severe_count = 0
        moderate_count = 0
        mild_count = 0

        for row in rows:
            task_id = row[0]
            room_id = row[1]
            room_name = row[2]
            body = row[3]
            summary = row[4]
            limit_time = row[5]
            assigned_to_account_id_val = row[6]
            assigned_to_name = row[7]
            assigned_by_account_id_val = row[8]
            assigned_by_name = row[9]
            status = row[10]
            created_at = row[11]
            task_department_id = row[12] if len(row) > 12 else None  # Phase 3.5

            # limit_timeをdateに変換
            if isinstance(limit_time, (int, float)):
                limit_datetime = datetime.fromtimestamp(int(limit_time), tz=JST)
                limit_date_val = limit_datetime.date()
            elif hasattr(limit_time, "date"):
                limit_datetime = limit_time
                limit_date_val = limit_time.date()
            else:
                continue

            # 超過日数計算
            days_overdue = (today - limit_date_val).days

            if days_overdue < 1:
                continue

            # 重度判定
            sev, sev_label = classify_severity(days_overdue)

            # 重度フィルタ
            if severity and sev != severity:
                continue

            # カウント
            if sev == "severe":
                severe_count += 1
            elif sev == "moderate":
                moderate_count += 1
            else:
                mild_count += 1

            task_response = OverdueTaskResponse(
                task_id=task_id,
                room_id=room_id,
                room_name=room_name,
                body=body or "",
                summary=summary,
                limit_date=limit_date_val,
                limit_time=limit_datetime if isinstance(limit_time, (int, float)) else None,
                days_overdue=days_overdue,
                severity=sev,
                severity_label=sev_label,
                assigned_to=TaskAssigneeInfo(
                    account_id=assigned_to_account_id_val,
                    name=assigned_to_name,
                ),
                assigned_by=TaskRequesterInfo(
                    account_id=assigned_by_account_id_val,
                    name=assigned_by_name,
                ),
                department_id=str(task_department_id) if task_department_id else None,
                status=status,
                created_at=created_at,
            )
            tasks.append(task_response)

        # 監査ログ
        log_audit_event(
            logger=logger,
            action="get_overdue_tasks",
            resource_type="task",
            resource_id=organization_id,
            user_id=x_user_id,
            details={
                "total_count": total_count,
                "returned_count": len(tasks),
                "severity_filter": severity,
                "grace_days": grace_days,
                "department_filter": department_id,
                "user_role_level": user_role_level,
                "accessible_departments_count": len(accessible_departments) if accessible_departments else None,
            },
        )

        logger.info(
            "Get overdue tasks completed",
            organization_id=organization_id,
            total_count=total_count,
            returned_count=len(tasks),
            department_filter=department_id,
            user_role_level=user_role_level,
        )

        return OverdueTaskListResponse(
            status="success",
            summary=OverdueSummary(
                total=len(tasks),
                severe_count=severe_count,
                moderate_count=moderate_count,
                mild_count=mild_count,
            ),
            tasks=tasks,
            checked_at=now,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(
            "Get overdue tasks error",
            organization_id=organization_id,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )


@router.get(
    "/overdue/summary",
    response_model=OverdueSummary,
    summary="期限超過タスクサマリー取得",
    description="期限超過タスクの件数サマリーのみを取得します（軽量API）",
)
async def get_overdue_tasks_summary(
    organization_id: str = Query(
        ...,
        description="組織ID",
        example="org_soulsyncs",
    ),
    grace_days: int = Query(
        0,
        ge=0,
        le=30,
        description="猶予日数",
    ),
):
    """
    期限超過タスクのサマリー（件数のみ）を取得

    軽量版API: ダッシュボード表示用
    """
    logger.info(
        "Get overdue tasks summary",
        organization_id=organization_id,
        grace_days=grace_days,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            now = datetime.now(JST)
            today = now.date()

            cutoff_date = today - timedelta(days=grace_days)
            cutoff_timestamp = int(
                datetime.combine(cutoff_date, datetime.min.time())
                .replace(tzinfo=JST)
                .timestamp()
            )

            # 重度別カウント
            query = """
                SELECT
                    limit_time,
                    COUNT(*) as cnt
                FROM chatwork_tasks
                WHERE status = 'open'
                  AND skip_tracking = FALSE
                  AND limit_time IS NOT NULL
                  AND limit_time < :cutoff_timestamp
                GROUP BY limit_time
            """
            result = conn.execute(text(query), {"cutoff_timestamp": cutoff_timestamp})
            rows = result.fetchall()

        severe_count = 0
        moderate_count = 0
        mild_count = 0

        for row in rows:
            limit_time = row[0]
            count = row[1]

            if isinstance(limit_time, (int, float)):
                limit_date_val = datetime.fromtimestamp(int(limit_time), tz=JST).date()
            elif hasattr(limit_time, "date"):
                limit_date_val = limit_time.date()
            else:
                continue

            days_overdue = (today - limit_date_val).days

            if days_overdue < 1:
                continue

            if days_overdue >= 7:
                severe_count += count
            elif days_overdue >= 3:
                moderate_count += count
            else:
                mild_count += count

        total = severe_count + moderate_count + mild_count

        return OverdueSummary(
            total=total,
            severe_count=severe_count,
            moderate_count=moderate_count,
            mild_count=mild_count,
        )

    except Exception as e:
        logger.exception(
            "Get overdue tasks summary error",
            organization_id=organization_id,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )
