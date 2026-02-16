# lib/brain/approval_gate.py
"""
承認ゲート（Approval Gate） — Step 0-1: 安全の土台

Tool実行前に3段階のリスク判定を行い、承認レベルを返す。
既存の ToolMetadataRegistry / is_dangerous_operation() / requires_confirmation() を
実際の実行フローに接続する。

【3段階の判定】
- AUTO_APPROVE: 低リスク → そのまま実行OK
- REQUIRE_CONFIRMATION: 中リスク → 社長（またはLevel 5+）に確認
- REQUIRE_DOUBLE_CHECK: 高リスク → 社長承認 + 番人ダブルチェック

【設計原則】
- 同期処理のみ（DB呼び出しなし）→ 高速・テスト容易
- 未知のToolは安全側（確認必須）に倒す
- 既存のGuardian Layer判定の後に実行される（guardian_check.pyから呼ばれる）
- 既存27機能の動作を変えない（低リスクはAUTO_APPROVE）

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional

from lib.brain.constants import RISK_LEVELS, CONFIRMATION_REQUIRED_RISK_LEVELS

logger = logging.getLogger(__name__)


# =============================================================================
# Enum & データクラス
# =============================================================================


class ApprovalLevel(Enum):
    """承認レベル"""
    AUTO_APPROVE = "auto_approve"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REQUIRE_DOUBLE_CHECK = "require_double_check"


@dataclass
class ApprovalCheckResult:
    """承認チェックの結果"""
    level: ApprovalLevel
    risk_level: str  # "low", "medium", "high", "critical", "unknown"
    tool_name: str
    reason: str
    confirmation_message: Optional[str] = None


# =============================================================================
# ApprovalGate 本体
# =============================================================================


class ApprovalGate:
    """
    3段階リスク判定ゲート

    ToolMetadataRegistryのrisk_levelとrequires_confirmationを参照し、
    実行前の承認レベルを判定する。
    """

    def check(self, tool_name: str, parameters: Optional[Dict[str, Any]] = None) -> ApprovalCheckResult:
        """
        Tool名とパラメータからリスク判定を行う。

        Args:
            tool_name: Tool名（SYSTEM_CAPABILITIESのキー）
            parameters: Toolに渡すパラメータ

        Returns:
            ApprovalCheckResult
        """
        if parameters is None:
            parameters = {}

        # 1. risk_level を取得（複数のソースから統合）
        risk_level = self._get_risk_level(tool_name)

        # 2. requires_confirmation フラグを確認
        needs_confirmation = self._check_requires_confirmation(tool_name)

        # 3. パラメータベースのエスカレーション
        risk_level = self._check_parameter_escalation(risk_level, parameters)

        # 4. 承認レベルを決定
        level = self._determine_approval_level(risk_level, needs_confirmation)

        # 5. 確認メッセージを生成（確認が必要な場合のみ）
        confirmation_message = None
        if level != ApprovalLevel.AUTO_APPROVE:
            confirmation_message = self._build_confirmation_message(
                tool_name, risk_level, parameters
            )

        reason = self._build_reason(tool_name, risk_level, needs_confirmation)

        logger.info(
            "ApprovalGate: tool=%s risk=%s level=%s",
            tool_name, risk_level, level.value,
        )

        return ApprovalCheckResult(
            level=level,
            risk_level=risk_level,
            tool_name=tool_name,
            reason=reason,
            confirmation_message=confirmation_message,
        )

    def _get_risk_level(self, tool_name: str) -> str:
        """risk_level を取得（constants.py → SYSTEM_CAPABILITIES の優先順）"""
        # まず constants.py の RISK_LEVELS を参照
        if tool_name in RISK_LEVELS:
            return RISK_LEVELS[tool_name]

        # 次に SYSTEM_CAPABILITIES の brain_metadata を参照
        try:
            from lib.brain.tool_converter import get_tool_metadata
            metadata = get_tool_metadata(tool_name)
            if metadata:
                brain_metadata = metadata.get("brain_metadata", {})
                risk: str = brain_metadata.get("risk_level", "low")
                return risk
        except (ImportError, Exception) as e:
            logger.warning("ApprovalGate: metadata lookup failed for %s: %s", tool_name, e)

        # 不明なToolは安全側に倒す
        return "medium"

    def _check_requires_confirmation(self, tool_name: str) -> bool:
        """requires_confirmation フラグを確認"""
        try:
            from lib.brain.tool_converter import requires_confirmation
            return requires_confirmation(tool_name)
        except (ImportError, Exception):
            return True  # 不明な場合は安全側

    def _check_parameter_escalation(self, risk_level: str, parameters: Dict[str, Any]) -> str:
        """パラメータに基づくリスクエスカレーション"""
        # 高額操作の検出
        for key in ("amount", "budget", "cost"):
            value = parameters.get(key)
            if value is not None:
                try:
                    if float(value) >= 100000:
                        return max(risk_level, "high", key=self._risk_order)
                except (ValueError, TypeError):
                    pass

        # 大量送信の検出
        recipients = parameters.get("recipients", parameters.get("assigned_to_list", []))
        if isinstance(recipients, list) and len(recipients) >= 10:
            return max(risk_level, "high", key=self._risk_order)

        return risk_level

    def _determine_approval_level(self, risk_level: str, needs_confirmation: bool) -> ApprovalLevel:
        """リスクレベルとフラグから承認レベルを決定"""
        if risk_level in ("high", "critical"):
            return ApprovalLevel.REQUIRE_DOUBLE_CHECK

        if risk_level in CONFIRMATION_REQUIRED_RISK_LEVELS or needs_confirmation:
            return ApprovalLevel.REQUIRE_CONFIRMATION

        return ApprovalLevel.AUTO_APPROVE

    def _build_confirmation_message(
        self, tool_name: str, risk_level: str, parameters: Dict[str, Any]
    ) -> str:
        """確認メッセージを生成"""
        # Tool名を人間が読める形にする
        readable_name = tool_name.replace("_", " ").title()

        if risk_level in ("high", "critical"):
            return (
                f"⚠️ 高リスク操作の確認\n"
                f"「{readable_name}」を実行しようとしています。\n"
                f"この操作は取り消しが困難です。実行してよろしいですか？"
            )
        else:
            return (
                f"確認: 「{readable_name}」を実行します。よろしいですか？"
            )

    def _build_reason(self, tool_name: str, risk_level: str, needs_confirmation: bool) -> str:
        """判定理由を生成"""
        parts = [f"tool={tool_name}", f"risk={risk_level}"]
        if needs_confirmation:
            parts.append("requires_confirmation=True")
        return ", ".join(parts)

    @staticmethod
    def _risk_order(level: str) -> int:
        """リスクレベルの順序（比較用）"""
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3, "unknown": 1}
        return order.get(level, 1)


# =============================================================================
# シングルトンアクセス
# =============================================================================

_approval_gate: Optional[ApprovalGate] = None


def get_approval_gate() -> ApprovalGate:
    """ApprovalGateのシングルトンインスタンスを取得"""
    global _approval_gate
    if _approval_gate is None:
        _approval_gate = ApprovalGate()
    return _approval_gate
