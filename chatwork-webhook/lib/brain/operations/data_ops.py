# lib/brain/operations/data_ops.py
"""
データ操作ハンドラー — Step C-2: 読み取り系操作

データの集計・検索を行う事前登録済み操作関数。

【設計原則】
- 読み取り専用（書き込みなし）→ リスクレベルは"low"
- organization_idフィルタ必須（CLAUDE.md §3 鉄則#1）
- パストラバーサル防止: ファイルパスは許可ディレクトリ内のみ
- 出力はOperationResult形式で統一

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import logging
from typing import Any, Dict

from lib.brain.operations.registry import OperationResult

logger = logging.getLogger(__name__)


async def handle_data_aggregate(
    params: Dict[str, Any],
    organization_id: str,
    account_id: str,
) -> OperationResult:
    """
    データ集計操作

    CSVやDBデータの集計（合計、平均、件数など）を行う。

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

    # TODO: Step C-2で実装
    # 現時点ではスタブを返す（レジストリ基盤のみの構築）
    return OperationResult(
        success=True,
        message=(
            f"データ集計の準備ができています。\n"
            f"対象: {data_source}\n"
            f"集計方法: {operation}\n"
            f"フィルタ: {filters or 'なし'}\n\n"
            f"※ この機能はStep C-2で実装予定です。"
        ),
        data={
            "data_source": data_source,
            "operation": operation,
            "filters": filters,
            "status": "stub",
        },
    )


async def handle_data_search(
    params: Dict[str, Any],
    organization_id: str,
    account_id: str,
) -> OperationResult:
    """
    データ検索操作

    DBやCSVから条件に合うデータを検索・一覧表示する。

    Args:
        params: {data_source, query, limit(optional)}
        organization_id: 組織ID（必須フィルタ）
        account_id: 実行者ID
    """
    data_source = params.get("data_source", "")
    query = params.get("query", "")
    limit = params.get("limit", 20)

    logger.info(
        f"データ検索: source={data_source}, query_len={len(query)}, "
        f"limit={limit}, org_id={organization_id}"
    )

    # TODO: Step C-2で実装
    return OperationResult(
        success=True,
        message=(
            f"データ検索の準備ができています。\n"
            f"対象: {data_source}\n"
            f"検索条件: {query}\n"
            f"最大件数: {limit}\n\n"
            f"※ この機能はStep C-2で実装予定です。"
        ),
        data={
            "data_source": data_source,
            "query": query,
            "limit": limit,
            "status": "stub",
        },
    )
