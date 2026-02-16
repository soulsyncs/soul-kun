# lib/brain/audit_bridge.py
"""
監査ログ橋渡し（Audit Bridge） — Step 0-2: 安全の土台

グラフノード（execute_tool等）から監査ログシステム（lib/audit.py）への
橋渡しモジュール。PIIを除去してからログに記録する。

【設計原則】
- fire-and-forget（非ブロッキング）→ ログ障害がTool実行を止めない
- PII除去はlib/brain/pii.pyのmask_piiを利用
- CLAUDE.md §9-3: 記録する=ユーザーID, アクション, 日時 / 記録しない=名前, メール, メッセージ本文

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import logging
from typing import Any, Dict, Optional

from lib.audit import log_audit_async

logger = logging.getLogger(__name__)


def _sanitize_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    パラメータからPIIを除去する。

    メッセージ本文、名前、メールアドレスなどを除去し、
    アクション種別やIDのみを残す。
    """
    if not params:
        return {}

    # PIIを含みうるキーを除去
    pii_keys = {
        "message", "body", "content", "text", "description",
        "name", "email", "phone", "address",
        "sender_name", "user_name", "display_name",
    }

    sanitized = {}
    for key, value in params.items():
        if key in pii_keys:
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, str) and len(value) > 200:
            # 長い文字列は本文の可能性があるので切り詰め
            sanitized[key] = value[:50] + "...[TRUNCATED]"
        else:
            sanitized[key] = value

    return sanitized


async def log_tool_execution(
    organization_id: str,
    tool_name: str,
    account_id: str,
    success: bool,
    risk_level: str = "low",
    reasoning: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    error_code: Optional[str] = None,
) -> bool:
    """
    Tool実行の監査ログを記録する。

    execute_toolノードから呼ばれる。fire-and-forget設計。

    Args:
        organization_id: 組織ID
        tool_name: 実行されたTool名
        account_id: 実行を要求したユーザーのアカウントID
        success: 実行成功/失敗
        risk_level: リスクレベル（承認ゲートの判定結果）
        reasoning: LLMの判断理由（PIIマスキング後）
        parameters: Toolパラメータ（PII除去後）
        error_code: エラーコード（失敗時のみ）

    Returns:
        True: ログ記録成功, False: 失敗
    """
    try:
        # PIIマスキング
        sanitized_params = _sanitize_params(parameters)
        sanitized_reasoning = None
        if reasoning:
            try:
                from lib.brain.pii import mask_pii
                sanitized_reasoning = mask_pii(reasoning)
            except (ImportError, Exception):
                # mask_piiが利用できない場合はreasoningを切り詰め
                sanitized_reasoning = reasoning[:100] + "..." if len(reasoning) > 100 else reasoning

        details = {
            "tool_name": tool_name,
            "success": success,
            "risk_level": risk_level,
        }
        if sanitized_params:
            details["parameters"] = sanitized_params
        if sanitized_reasoning:
            details["reasoning"] = sanitized_reasoning
        if error_code:
            details["error_code"] = error_code

        return await log_audit_async(
            organization_id=organization_id,
            action=f"tool_execute_{tool_name}",
            resource_type="brain_tool",
            resource_id=tool_name,
            user_id=account_id,
            classification="confidential",
            details=details,
        )

    except Exception as e:
        logger.warning("audit_bridge: log_tool_execution failed: %s", e)
        return False
