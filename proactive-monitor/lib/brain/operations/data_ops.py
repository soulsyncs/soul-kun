# lib/brain/operations/data_ops.py
"""
データ操作ハンドラー — Step C-2: 読み取り系操作

データの集計・検索を行う事前登録済み操作関数。

【設計原則】
- 読み取り専用（書き込みなし）→ リスクレベルは"low"
- organization_idフィルタ必須（CLAUDE.md §3 鉄則#1）
- パラメータ化SQL必須（CLAUDE.md §3 鉄則#9）
- PII除去: ユーザー名・メールは返さない
- 出力はOperationResult形式で統一

【対応データソース】
- tasks: ChatWorkタスク（chatwork_tasksテーブル）
- goals: スタッフ目標（staff_goalsテーブル）

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from lib.brain.operations.registry import OperationResult

logger = logging.getLogger(__name__)

# サポートするデータソース → テーブル名のマッピング
SUPPORTED_DATA_SOURCES = {
    "tasks": "chatwork_tasks",
    "タスク": "chatwork_tasks",
    "task": "chatwork_tasks",
    "goals": "staff_goals",
    "目標": "staff_goals",
    "goal": "staff_goals",
}

# 集計操作のマッピング
AGGREGATE_OPERATIONS = {
    "count": "COUNT(*)",
    "件数": "COUNT(*)",
    "sum": "COUNT(*)",  # タスクにはamountがないのでcountにフォールバック
    "合計": "COUNT(*)",
    "avg": "COUNT(*)",  # 同上
    "平均": "COUNT(*)",
}


def _resolve_data_source(data_source: str) -> Optional[str]:
    """データソース名をテーブル名に解決する"""
    ds_lower = data_source.lower().strip()
    for key, table in SUPPORTED_DATA_SOURCES.items():
        if key in ds_lower:
            return table
    return None


def _build_task_filter(filters: str) -> tuple:
    """
    フィルタ文字列からSQLのWHERE句とパラメータを生成する。

    Returns:
        (where_clause, params_dict)
    """
    where_parts = []
    params = {}

    if not filters:
        return "", params

    filters_lower = filters.lower()

    # ステータスフィルタ
    if "完了" in filters_lower or "done" in filters_lower:
        where_parts.append("status = :status")
        params["status"] = "done"
    elif "未完了" in filters_lower or "open" in filters_lower or "未着手" in filters_lower:
        where_parts.append("status = :status")
        params["status"] = "open"

    # 時期フィルタ
    now = datetime.utcnow()
    if "今月" in filters_lower or "今月" in filters:
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        where_parts.append("created_at >= :date_from")
        params["date_from"] = first_of_month.isoformat()
    elif "先月" in filters_lower or "先月" in filters:
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        first_of_last_month = (first_of_this_month - timedelta(days=1)).replace(day=1)
        where_parts.append("created_at >= :date_from AND created_at < :date_to")
        params["date_from"] = first_of_last_month.isoformat()
        params["date_to"] = first_of_this_month.isoformat()
    elif "今日" in filters_lower:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        where_parts.append("created_at >= :date_from")
        params["date_from"] = today.isoformat()

    if where_parts:
        return " AND ".join(where_parts), params
    return "", params


async def handle_data_aggregate(
    params: Dict[str, Any],
    organization_id: str,
    account_id: str,
) -> OperationResult:
    """
    データ集計操作

    DBデータの集計（件数、ステータス別集計など）を行う。

    Args:
        params: {data_source, operation, filters(optional)}
        organization_id: 組織ID（必須フィルタ）
        account_id: 実行者ID
    """
    data_source = params.get("data_source", "")
    operation = params.get("operation", "count")
    filters = params.get("filters", "")

    logger.info(
        f"データ集計: source={data_source}, op={operation}, "
        f"org_id={organization_id}"
    )

    # 1. データソース解決
    table = _resolve_data_source(data_source)
    if table is None:
        supported = ", ".join(sorted(set(SUPPORTED_DATA_SOURCES.values())))
        return OperationResult(
            success=False,
            message=(
                f"データソース '{data_source}' は対応していません。\n"
                f"対応しているデータ: タスク（tasks）、目標（goals）"
            ),
        )

    # 2. DB接続 & クエリ実行
    try:
        from lib.db import get_db_pool
        from sqlalchemy import text

        pool = get_db_pool()

        # CLAUDE.md §3-2 #6: sync I/Oをasyncでブロックしない
        result_data = await asyncio.to_thread(
            _execute_aggregate, pool, table, operation, filters, organization_id
        )

        return OperationResult(
            success=True,
            message=result_data["message"],
            data=result_data,
        )

    except Exception as e:
        logger.error(f"データ集計エラー: {type(e).__name__}", exc_info=True)
        return OperationResult(
            success=False,
            message="データの集計中にエラーが発生しました。",
        )


def _execute_aggregate(
    pool, table: str, operation: str, filters: str, organization_id: str
) -> Dict[str, Any]:
    """同期的にDB集計クエリを実行する"""
    from sqlalchemy import text

    with pool.connect() as conn:
        # CLAUDE.md §3 鉄則#1: organization_idフィルタ必須
        base_where = "organization_id = :org_id"
        base_params = {"org_id": organization_id}

        # フィルタ追加
        extra_where, extra_params = _build_task_filter(filters)
        all_params = {**base_params, **extra_params}

        where_clause = base_where
        if extra_where:
            where_clause += f" AND {extra_where}"

        if table == "chatwork_tasks":
            # ステータス別集計
            query = text(f"""
                SELECT status, COUNT(*) as cnt
                FROM chatwork_tasks
                WHERE {where_clause}
                GROUP BY status
                ORDER BY cnt DESC
            """)
            rows = conn.execute(query, all_params).fetchall()

            total = sum(row[1] for row in rows)
            status_breakdown = {row[0]: row[1] for row in rows}

            # わかりやすいメッセージ生成
            filter_desc = f"（{filters}）" if filters else ""
            parts = []
            for status, cnt in status_breakdown.items():
                status_ja = {"open": "未完了", "done": "完了"}.get(status, status)
                parts.append(f"  - {status_ja}: {cnt}件")

            message = f"タスク集計{filter_desc}:\n合計: {total}件\n" + "\n".join(parts)

            return {
                "message": message,
                "total": total,
                "breakdown": status_breakdown,
                "data_source": "chatwork_tasks",
                "filters": filters,
            }

        elif table == "staff_goals":
            query = text(f"""
                SELECT COUNT(*) as cnt
                FROM staff_goals
                WHERE {where_clause}
            """)
            row = conn.execute(query, all_params).fetchone()
            total = row[0] if row else 0

            filter_desc = f"（{filters}）" if filters else ""
            message = f"目標集計{filter_desc}:\n合計: {total}件"

            return {
                "message": message,
                "total": total,
                "data_source": "staff_goals",
                "filters": filters,
            }

        return {"message": "集計完了", "total": 0}


async def handle_data_search(
    params: Dict[str, Any],
    organization_id: str,
    account_id: str,
) -> OperationResult:
    """
    データ検索操作

    DBから条件に合うデータを検索・一覧表示する。

    Args:
        params: {data_source, query, limit(optional)}
        organization_id: 組織ID（必須フィルタ）
        account_id: 実行者ID
    """
    data_source = params.get("data_source", "")
    query_text = params.get("query", "")
    limit = min(params.get("limit", 20), 50)  # 最大50件

    logger.info(
        f"データ検索: source={data_source}, query_len={len(query_text)}, "
        f"limit={limit}, org_id={organization_id}"
    )

    # 1. データソース解決
    table = _resolve_data_source(data_source)
    if table is None:
        return OperationResult(
            success=False,
            message=(
                f"データソース '{data_source}' は対応していません。\n"
                f"対応しているデータ: タスク（tasks）、目標（goals）"
            ),
        )

    # 2. DB接続 & クエリ実行
    try:
        from lib.db import get_db_pool

        pool = get_db_pool()

        result_data = await asyncio.to_thread(
            _execute_search, pool, table, query_text, limit, organization_id
        )

        return OperationResult(
            success=True,
            message=result_data["message"],
            data=result_data,
        )

    except Exception as e:
        logger.error(f"データ検索エラー: {type(e).__name__}", exc_info=True)
        return OperationResult(
            success=False,
            message="データの検索中にエラーが発生しました。",
        )


def _execute_search(
    pool, table: str, query_text: str, limit: int, organization_id: str
) -> Dict[str, Any]:
    """同期的にDB検索クエリを実行する"""
    from sqlalchemy import text

    with pool.connect() as conn:
        # CLAUDE.md §3 鉄則#1: organization_idフィルタ必須
        base_where = "organization_id = :org_id"
        base_params: Dict[str, Any] = {"org_id": organization_id, "limit": limit}

        # フィルタ解析
        extra_where, extra_params = _build_task_filter(query_text)
        all_params = {**base_params, **extra_params}

        where_clause = base_where
        if extra_where:
            where_clause += f" AND {extra_where}"

        if table == "chatwork_tasks":
            # テキスト検索: bodyまたはsummaryにキーワードを含む
            # フィルタで使われなかった部分をキーワード検索に
            keywords = _extract_keywords(query_text)
            if keywords:
                where_clause += " AND (body ILIKE :keyword OR summary ILIKE :keyword)"
                all_params["keyword"] = f"%{keywords}%"

            query = text(f"""
                SELECT task_id, body, status, limit_time, room_name, summary
                FROM chatwork_tasks
                WHERE {where_clause}
                ORDER BY created_at DESC NULLS LAST
                LIMIT :limit
            """)
            rows = conn.execute(query, all_params).fetchall()

            # PII除去: ユーザー名は返さない（CLAUDE.md §3-2 #8）
            results = []
            for row in rows:
                task_body = (row[1] or "")[:100]  # 本文は100文字まで
                summary = row[5] or task_body
                status_ja = {"open": "未完了", "done": "完了"}.get(row[2], row[2] or "不明")
                deadline = ""
                if row[3]:
                    try:
                        dt = datetime.utcfromtimestamp(int(row[3]))
                        deadline = dt.strftime("%Y-%m-%d")
                    except (ValueError, TypeError, OSError):
                        deadline = ""

                results.append({
                    "task_id": str(row[0]),
                    "summary": summary[:100],
                    "status": status_ja,
                    "deadline": deadline,
                    "room": row[4] or "",
                })

            # わかりやすいメッセージ
            if results:
                lines = [f"タスク検索結果: {len(results)}件"]
                for i, r in enumerate(results[:10], 1):  # 表示は10件まで
                    deadline_str = f"（期限: {r['deadline']}）" if r['deadline'] else ""
                    lines.append(f"  {i}. [{r['status']}] {r['summary']}{deadline_str}")
                if len(results) > 10:
                    lines.append(f"  ...他{len(results) - 10}件")
                message = "\n".join(lines)
            else:
                message = "該当するタスクが見つかりませんでした。"

            return {
                "message": message,
                "results": results,
                "total": len(results),
                "data_source": "chatwork_tasks",
            }

        elif table == "staff_goals":
            query = text(f"""
                SELECT goal_id, staff_account_id, goal_month, sessions_target
                FROM staff_goals
                WHERE {where_clause}
                ORDER BY goal_month DESC
                LIMIT :limit
            """)
            rows = conn.execute(query, all_params).fetchall()

            results = []
            for row in rows:
                results.append({
                    "goal_id": str(row[0]) if row[0] else "",
                    "month": str(row[2]) if row[2] else "",
                    "target": row[3] if row[3] else 0,
                })

            if results:
                lines = [f"目標検索結果: {len(results)}件"]
                for i, r in enumerate(results[:10], 1):
                    lines.append(f"  {i}. {r['month']} — 目標: {r['target']}")
                message = "\n".join(lines)
            else:
                message = "該当する目標が見つかりませんでした。"

            return {
                "message": message,
                "results": results,
                "total": len(results),
                "data_source": "staff_goals",
            }

        return {"message": "検索完了", "results": [], "total": 0}


def _extract_keywords(query_text: str) -> str:
    """
    クエリテキストからフィルタ語を除いたキーワードを抽出する。

    「先月の未完了タスク」→ ""（フィルタ語のみなので空）
    「営業の報告タスク」→ "営業の報告"
    """
    # フィルタ語を除去
    filter_words = [
        "完了", "未完了", "done", "open", "未着手",
        "今月", "先月", "今日", "今週", "来週",
        "タスク", "目標", "tasks", "goals",
        "の", "を", "で", "に", "が", "は",
        "一覧", "リスト", "検索", "表示", "見せて",
        "教えて", "出して",
    ]
    result = query_text
    for word in filter_words:
        result = result.replace(word, "")
    return result.strip()
