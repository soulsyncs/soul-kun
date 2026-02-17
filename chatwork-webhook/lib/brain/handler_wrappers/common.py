# lib/brain/handler_wrappers/common.py
"""
共通のインポート・ユーティリティ関数

handler_wrappersパッケージ内の全モジュールから参照される。
"""

from typing import Dict, Any, Callable, Optional
import re
import logging

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


# =====================================================
# ユーティリティ関数
# =====================================================

def _extract_handler_result(result: Any, default_message: str) -> HandlerResult:
    """
    ハンドラーの戻り値からHandlerResultを生成する

    v10.54.5: 辞書型の戻り値を正しく処理

    Args:
        result: ハンドラーの戻り値（文字列、辞書、またはNone）
        default_message: resultがNone/空の場合のデフォルトメッセージ

    Returns:
        HandlerResult: 正しく構築されたハンドラー結果

    Examples:
        # 文字列が返された場合
        >>> _extract_handler_result("タスク一覧です", "デフォルト")
        HandlerResult(success=True, message="タスク一覧です")

        # 辞書が返された場合
        >>> _extract_handler_result({"success": True, "message": "目標一覧"}, "デフォルト")
        HandlerResult(success=True, message="目標一覧")

        # Noneが返された場合
        >>> _extract_handler_result(None, "デフォルトメッセージ")
        HandlerResult(success=True, message="デフォルトメッセージ")
    """
    if result is None:
        return HandlerResult(success=True, message=default_message)

    if isinstance(result, dict):
        # 辞書の場合はmessageフィールドを抽出
        message = result.get("message", default_message)
        success = result.get("success", True)

        # messageがNoneの場合はデフォルトメッセージを使用
        if message is None:
            message = default_message

        # 追加のフィールドをdataとして保持（fallback_to_general等）
        data = {k: v for k, v in result.items() if k not in ("success", "message")}

        return HandlerResult(success=success, message=message, data=data if data else None)

    # 文字列またはその他の場合
    return HandlerResult(success=True, message=str(result) if result else default_message)
