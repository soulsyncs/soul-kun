# lib/brain/handler_wrappers/external_tool_handlers.py
"""
外部ツールハンドラー

Web検索、Googleカレンダー、Googleドライブ、データ集計・検索、
レポート生成、CSVエクスポート、ファイル作成のハンドラー。
"""

import os
import logging
from typing import Dict, Any

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


# =====================================================
# Step A-1: Web検索ハンドラー
# =====================================================

async def _brain_handle_web_search(params, room_id, account_id, sender_name, context):
    """
    Web検索ハンドラー

    Step A-1: Tavily APIを使ったWeb検索。
    検索結果はBrain層が合成回答に使う（needs_answer_synthesis=True）。

    NOTE: Tavily SDKはrequestsベースの同期I/O。
    asyncio.to_thread()で包んでイベントループをブロックしない（CLAUDE.md §3-2 #6）。
    """
    try:
        import asyncio
        from lib.brain.web_search import get_web_search_client, format_search_results

        query = params.get("query", "")
        if not query:
            return HandlerResult(
                success=False,
                message="検索クエリが指定されていないウル🐺 何を調べたいか教えてほしいウル！",
            )

        max_results = params.get("max_results", 5)
        client = get_web_search_client()
        # CLAUDE.md §3-2 #6: sync I/Oをasyncでブロックしないようにオフロード
        search_result = await asyncio.to_thread(
            client.search, query=query, max_results=max_results
        )

        if not search_result.get("success"):
            error_msg = search_result.get("error", "検索に失敗しました")
            return HandlerResult(
                success=False,
                message=f"ウェブ検索でエラーが発生したウル🐺 ({error_msg})",
            )

        # 検索結果をフォーマットしてBrain合成用データとして返す
        formatted = format_search_results(search_result)
        return HandlerResult(
            success=True,
            message=formatted,
            data={
                "needs_answer_synthesis": True,
                "search_results": search_result.get("results", []),
                "search_answer": search_result.get("answer"),
                "search_query": query,
                "result_count": search_result.get("result_count", 0),
            },
        )
    except Exception as e:
        logger.error("web_search handler error: %s", e, exc_info=True)
        return HandlerResult(
            success=False,
            message="ウェブ検索でエラーが発生したウル🐺 もう一度試してほしいウル！",
        )


# =====================================================
# Step A-3: Googleカレンダー読み取りハンドラー
# =====================================================

async def _brain_handle_calendar_read(params, room_id, account_id, sender_name, context):
    """
    Googleカレンダー予定読み取りハンドラー

    Step A-3: 管理画面で接続済みのGoogleカレンダーから予定を取得。
    CLAUDE.md §3-2 #6: sync I/Oは asyncio.to_thread() でオフロード。
    """
    try:
        import asyncio
        import sys
        from lib.brain.calendar_tool import list_calendar_events, format_calendar_events

        main = sys.modules.get('main')
        if not main:
            return HandlerResult(
                success=False,
                message="システムエラーが発生したウル🐺",
            )

        pool = getattr(main, 'get_pool', lambda: None)()
        if not pool:
            return HandlerResult(
                success=False,
                message="データベースに接続できないウル🐺",
            )

        # organization_idの取得
        org_id = ""
        if hasattr(context, 'organization_id'):
            org_id = context.organization_id
        elif isinstance(context, dict):
            org_id = context.get('organization_id', '')

        if not org_id:
            # contextから取れなければ環境変数にフォールバック
            org_id = os.environ.get("ORGANIZATION_ID", "")

        if not org_id:
            return HandlerResult(
                success=False,
                message="組織情報が取得できなかったウル🐺",
            )

        date_from = params.get("date_from")
        date_to = params.get("date_to")

        # CLAUDE.md §3-2 #6: sync I/Oをasyncでブロックしないようにオフロード
        result = await asyncio.to_thread(
            list_calendar_events,
            pool=pool,
            organization_id=org_id,
            date_from=date_from,
            date_to=date_to,
        )

        if not result.get("success"):
            error_msg = result.get("error", "カレンダー取得に失敗しました")
            return HandlerResult(
                success=False,
                message=f"カレンダーの確認でエラーが発生したウル🐺 ({error_msg})",
            )

        formatted = format_calendar_events(result)
        return HandlerResult(
            success=True,
            message=formatted,
            data={
                "needs_answer_synthesis": True,
                "calendar_events": result.get("events", []),
                "date_range": result.get("date_range", ""),
                "event_count": result.get("event_count", 0),
            },
        )
    except Exception as e:
        logger.error("calendar_read handler error: %s", e, exc_info=True)
        return HandlerResult(
            success=False,
            message="カレンダーの確認でエラーが発生したウル🐺 もう一度試してほしいウル！",
        )


# =====================================================
# Step A-5: Googleドライブ ファイル検索ハンドラー
# =====================================================

async def _brain_handle_drive_search(params, room_id, account_id, sender_name, context):
    """
    Googleドライブ ファイル検索ハンドラー

    Step A-5: documentsテーブルからファイル名検索。
    CLAUDE.md §3-2 #6: sync I/Oは asyncio.to_thread() でオフロード。
    """
    try:
        import asyncio
        import sys
        from lib.brain.drive_tool import search_drive_files, format_drive_files

        main = sys.modules.get('main')
        if not main:
            return HandlerResult(
                success=False,
                message="システムエラーが発生したウル🐺",
            )

        pool = getattr(main, 'get_pool', lambda: None)()
        if not pool:
            return HandlerResult(
                success=False,
                message="データベースに接続できないウル🐺",
            )

        # organization_idの取得
        org_id = ""
        if hasattr(context, 'organization_id'):
            org_id = context.organization_id
        elif isinstance(context, dict):
            org_id = context.get('organization_id', '')

        if not org_id:
            org_id = os.environ.get("ORGANIZATION_ID", "")

        if not org_id:
            return HandlerResult(
                success=False,
                message="組織情報が取得できなかったウル🐺",
            )

        query = params.get("query", "")
        max_results = params.get("max_results", 10)

        # CLAUDE.md §3-2 #6: sync I/Oをasyncでブロックしないようにオフロード
        result = await asyncio.to_thread(
            search_drive_files,
            pool=pool,
            organization_id=org_id,
            query=query if query else None,
            max_results=max_results,
        )

        if not result.get("success"):
            error_msg = result.get("error", "ドライブ検索に失敗しました")
            return HandlerResult(
                success=False,
                message=f"ドライブの検索でエラーが発生したウル🐺 ({error_msg})",
            )

        formatted = format_drive_files(result)
        return HandlerResult(
            success=True,
            message=formatted,
            data={
                "needs_answer_synthesis": True,
                "drive_files": result.get("files", []),
                "search_query": query,
                "file_count": result.get("file_count", 0),
            },
        )
    except Exception as e:
        logger.error("drive_search handler error: %s", e, exc_info=True)
        return HandlerResult(
            success=False,
            message="ドライブの検索でエラーが発生したウル🐺 もう一度試してほしいウル！",
        )


# =====================================================
# Step C-1: 操作系ハンドラー（手足を与える）
# =====================================================


async def _brain_handle_data_aggregate(
    params: Dict[str, Any],
    room_id: str = "",
    account_id: str = "",
    sender_name: str = "",
    context: Any = None,
) -> HandlerResult:
    """データ集計操作のBrainハンドラー"""
    try:
        from lib.brain.operations.data_ops import handle_data_aggregate

        org_id = ""
        if hasattr(context, 'organization_id'):
            org_id = context.organization_id
        elif isinstance(context, dict):
            org_id = context.get('organization_id', '')
        if not org_id:
            org_id = os.environ.get("ORGANIZATION_ID", "")

        result = await handle_data_aggregate(
            params=params,
            organization_id=org_id,
            account_id=account_id,
        )
        return HandlerResult(
            success=result.success,
            message=result.message,
            data=result.data,
        )
    except Exception as e:
        logger.error(f"データ集計エラー: {e}", exc_info=True)
        return HandlerResult(
            success=False,
            message="データの集計でエラーが発生したウル🐺",
        )


async def _brain_handle_data_search(
    params: Dict[str, Any],
    room_id: str = "",
    account_id: str = "",
    sender_name: str = "",
    context: Any = None,
) -> HandlerResult:
    """データ検索操作のBrainハンドラー"""
    try:
        from lib.brain.operations.data_ops import handle_data_search

        org_id = ""
        if hasattr(context, 'organization_id'):
            org_id = context.organization_id
        elif isinstance(context, dict):
            org_id = context.get('organization_id', '')
        if not org_id:
            org_id = os.environ.get("ORGANIZATION_ID", "")

        result = await handle_data_search(
            params=params,
            organization_id=org_id,
            account_id=account_id,
        )
        return HandlerResult(
            success=result.success,
            message=result.message,
            data=result.data,
        )
    except Exception as e:
        logger.error(f"データ検索エラー: {e}", exc_info=True)
        return HandlerResult(
            success=False,
            message="データの検索でエラーが発生したウル🐺",
        )


# Step C-5: 書き込み系操作ハンドラー（手足を与える — Phase 2）


async def _brain_handle_report_generate(
    params: Dict[str, Any],
    room_id: str,
    account_id: str,
    sender_name: str,
    context: Any,
) -> "HandlerResult":
    """レポート生成ハンドラーラッパー"""
    from lib.brain.operations.report_ops import handle_report_generate

    org_id = getattr(context, "organization_id", None) or os.environ.get("ORGANIZATION_ID", "")
    try:
        result = await handle_report_generate(
            params=params,
            organization_id=org_id,
            account_id=account_id,
        )
        return HandlerResult(
            success=result.success,
            message=result.message,
            data=result.data,
        )
    except Exception as e:
        logger.error(f"レポート生成エラー: {e}", exc_info=True)
        return HandlerResult(
            success=False,
            message="レポートの生成でエラーが発生したウル🐺",
        )


async def _brain_handle_csv_export(
    params: Dict[str, Any],
    room_id: str,
    account_id: str,
    sender_name: str,
    context: Any,
) -> "HandlerResult":
    """CSVエクスポートハンドラーラッパー"""
    from lib.brain.operations.report_ops import handle_csv_export

    org_id = getattr(context, "organization_id", None) or os.environ.get("ORGANIZATION_ID", "")
    try:
        result = await handle_csv_export(
            params=params,
            organization_id=org_id,
            account_id=account_id,
        )
        return HandlerResult(
            success=result.success,
            message=result.message,
            data=result.data,
        )
    except Exception as e:
        logger.error(f"CSVエクスポートエラー: {e}", exc_info=True)
        return HandlerResult(
            success=False,
            message="CSVの出力でエラーが発生したウル🐺",
        )


async def _brain_handle_file_create(
    params: Dict[str, Any],
    room_id: str,
    account_id: str,
    sender_name: str,
    context: Any,
) -> "HandlerResult":
    """ファイル作成ハンドラーラッパー"""
    from lib.brain.operations.report_ops import handle_file_create

    org_id = getattr(context, "organization_id", None) or os.environ.get("ORGANIZATION_ID", "")
    try:
        result = await handle_file_create(
            params=params,
            organization_id=org_id,
            account_id=account_id,
        )
        return HandlerResult(
            success=result.success,
            message=result.message,
            data=result.data,
        )
    except Exception as e:
        logger.error(f"ファイル作成エラー: {e}", exc_info=True)
        return HandlerResult(
            success=False,
            message="ファイルの作成でエラーが発生したウル🐺",
        )
