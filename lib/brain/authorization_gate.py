# lib/brain/authorization_gate.py
"""
認可ゲート（Authorization Gate）

実行前の権限チェックを統括するレイヤー。
Guardian Gate、Value Authority、Memory Authority、ExecutionExcellenceの評価を一元管理。

設計書: docs/25_llm_native_brain_architecture.md（LLM常駐型脳アーキテクチャ）
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum

from lib.brain.models import (
    BrainContext,
    DecisionResult,
    HandlerResult,
)
from lib.brain.guardian import (
    GuardianService,
    GuardianActionResult,
    GuardianActionType,
)
from lib.brain.value_authority import (
    ValueAuthority,
    ValueAuthorityResult,
    ValueDecision,
    create_value_authority,
)
from lib.brain.memory_authority import (
    MemoryAuthority,
    MemoryAuthorityResult,
    MemoryDecision,
    create_memory_authority,
)
from lib.brain.execution_excellence import (
    ExecutionExcellence,
)
from lib.brain.memory_authority_logger import get_memory_authority_logger

logger = logging.getLogger(__name__)


class AuthorizationDecision(Enum):
    """認可判定結果"""
    APPROVE = "approve"  # 承認（実行を許可）
    BLOCK = "block"  # ブロック（代替メッセージを返す）
    CONFIRM = "confirm"  # 確認が必要
    FORCE_MODE_SWITCH = "force_mode_switch"  # 強制モード遷移


@dataclass
class AuthorizationResult:
    """認可評価の結果"""
    decision: AuthorizationDecision
    blocked: bool = False
    response: Optional[HandlerResult] = None
    soft_conflict_logged: bool = False
    execution_excellence_used: bool = False
    execution_excellence_result: Optional[Any] = None

    # デバッグ情報
    guardian_result: Optional[GuardianActionResult] = None
    value_authority_result: Optional[ValueAuthorityResult] = None
    memory_authority_result: Optional[MemoryAuthorityResult] = None


class AuthorizationGate:
    """
    実行前の権限チェックを統括

    責務:
    - Guardian Gate: 価値観評価（NGパターン検出）
    - Value Authority: 人生軸との整合性チェック
    - Memory Authority: 長期記憶との矛盾検出
    - ExecutionExcellence: 複合タスクの判定
    """

    def __init__(
        self,
        guardian: GuardianService,
        execution_excellence: Optional[ExecutionExcellence] = None,
        organization_id: str = "",
    ):
        """
        Args:
            guardian: GuardianService インスタンス
            execution_excellence: ExecutionExcellence インスタンス（オプション）
            organization_id: 組織ID
        """
        self.guardian = guardian
        self.execution_excellence = execution_excellence
        self.organization_id = organization_id

    async def evaluate(
        self,
        decision: DecisionResult,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> AuthorizationResult:
        """
        全ての権限チェックを実行

        Args:
            decision: 判断層からの決定
            context: コンテキスト
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            sender_name: 送信者名

        Returns:
            AuthorizationResult: 認可評価の結果
        """
        # 元のメッセージを取得
        original_message = self._get_original_message(context)

        # 1. Guardian Gate評価
        guardian_result = await self._evaluate_guardian(
            decision, original_message, room_id, account_id
        )
        if guardian_result.blocked:
            return guardian_result

        # 2. Value Authority評価
        value_result = await self._evaluate_value_authority(
            decision, context, original_message, room_id, account_id, sender_name
        )
        if value_result.blocked:
            return value_result

        # 3. Memory Authority評価
        memory_result = await self._evaluate_memory_authority(
            decision, context, original_message, room_id, account_id, sender_name
        )
        if memory_result.blocked:
            return memory_result

        # 4. ExecutionExcellence判定（複合タスクの場合）
        ee_result = await self._evaluate_execution_excellence(
            decision, context, original_message
        )
        if ee_result.execution_excellence_used:
            return ee_result

        # 全てのチェックを通過
        return AuthorizationResult(
            decision=AuthorizationDecision.APPROVE,
            blocked=False,
            soft_conflict_logged=memory_result.soft_conflict_logged,
        )

    def _get_original_message(self, context: BrainContext) -> str:
        """コンテキストから元のメッセージを取得"""
        if context.recent_conversation:
            for msg in reversed(context.recent_conversation):
                if msg.role == "user":
                    return msg.content
        return ""

    async def _evaluate_guardian(
        self,
        decision: DecisionResult,
        original_message: str,
        room_id: str,
        account_id: str,
    ) -> AuthorizationResult:
        """Guardian Gate評価（価値観チェック）"""
        if not original_message:
            return AuthorizationResult(decision=AuthorizationDecision.APPROVE)

        guardian_result = self.guardian.evaluate_action(
            user_message=original_message,
            action=decision.action,
            context={"room_id": room_id, "account_id": account_id},
        )

        # BLOCK_AND_SUGGEST: 実行ブロック + 代替メッセージ返却
        if guardian_result.action_type == GuardianActionType.BLOCK_AND_SUGGEST:
            logger.warning(
                f"🛑 [Guardian Gate] Action blocked: {decision.action}, "
                f"reason={guardian_result.blocked_reason}"
            )
            return AuthorizationResult(
                decision=AuthorizationDecision.BLOCK,
                blocked=True,
                response=HandlerResult(
                    success=True,
                    message=guardian_result.alternative_message or (
                        "🐺 ちょっと気になることがあるウル。話を聞かせてほしいウル"
                    ),
                ),
                guardian_result=guardian_result,
            )

        # FORCE_MODE_SWITCH: 強制モード遷移
        if guardian_result.action_type == GuardianActionType.FORCE_MODE_SWITCH:
            logger.warning(
                f"🚨 [Guardian Gate] Force mode switch: {decision.action} → {guardian_result.force_mode}, "
                f"reason={guardian_result.blocked_reason}"
            )
            return AuthorizationResult(
                decision=AuthorizationDecision.FORCE_MODE_SWITCH,
                blocked=True,
                response=HandlerResult(
                    success=True,
                    message=guardian_result.alternative_message or (
                        "🐺 大事な話ウルね。ゆっくり聞かせてほしいウル"
                    ),
                ),
                guardian_result=guardian_result,
            )

        # APPROVE: 通過
        if guardian_result.ng_pattern_type:
            logger.debug(
                f"[Guardian Gate] Approved with caution: {decision.action}, "
                f"ng_pattern={guardian_result.ng_pattern_type}"
            )

        return AuthorizationResult(
            decision=AuthorizationDecision.APPROVE,
            guardian_result=guardian_result,
        )

    async def _evaluate_value_authority(
        self,
        decision: DecisionResult,
        context: BrainContext,
        original_message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> AuthorizationResult:
        """Value Authority評価（人生軸との整合性）"""
        if not context.user_life_axis:
            return AuthorizationResult(decision=AuthorizationDecision.APPROVE)

        value_authority = create_value_authority(
            user_life_axis=context.user_life_axis,
            user_name=sender_name,
            organization_id=context.organization_id,
        )

        # NGパターン結果を構築
        ng_pattern_result = None
        if original_message:
            guardian_result = self.guardian.evaluate_action(
                user_message=original_message,
                action=decision.action,
                context={"room_id": room_id, "account_id": account_id},
            )
            if guardian_result.ng_pattern_type:
                ng_pattern_result = {
                    "risk_level": self._get_risk_level(guardian_result),
                    "pattern_type": guardian_result.ng_pattern_type,
                    "original_action": decision.action,
                }

        va_result = value_authority.evaluate_action(
            action=decision.action,
            action_params=decision.params,
            user_message=original_message,
            ng_pattern_result=ng_pattern_result,
        )

        # BLOCK_AND_SUGGEST
        if va_result.decision == ValueDecision.BLOCK_AND_SUGGEST:
            logger.info(
                f"🛡️ [ValueAuthority] Action blocked: {decision.action}, "
                f"reason={va_result.reason}, violation={va_result.violation_type}"
            )
            return AuthorizationResult(
                decision=AuthorizationDecision.BLOCK,
                blocked=True,
                response=HandlerResult(
                    success=True,
                    message=va_result.alternative_message or (
                        f"🐺 {sender_name}さんの価値観と少しずれがありそうウル。"
                        "一緒に考えようウル🐺"
                    ),
                ),
                value_authority_result=va_result,
            )

        # FORCE_MODE_SWITCH
        if va_result.decision == ValueDecision.FORCE_MODE_SWITCH:
            logger.warning(
                f"🚨 [ValueAuthority] Force mode switch: {decision.action} → {va_result.forced_mode}, "
                f"reason={va_result.reason}"
            )
            return AuthorizationResult(
                decision=AuthorizationDecision.FORCE_MODE_SWITCH,
                blocked=True,
                response=HandlerResult(
                    success=True,
                    message=va_result.alternative_message or (
                        "🐺 大事な話ウルね。ゆっくり聞かせてほしいウル"
                    ),
                ),
                value_authority_result=va_result,
            )

        # APPROVE
        logger.debug(f"✅ [ValueAuthority] Action approved: {decision.action}")
        return AuthorizationResult(
            decision=AuthorizationDecision.APPROVE,
            value_authority_result=va_result,
        )

    def _get_risk_level(self, guardian_result: GuardianActionResult) -> str:
        """Guardian結果からリスクレベルを取得"""
        if guardian_result.action_type == GuardianActionType.FORCE_MODE_SWITCH:
            if "mental_health" in (guardian_result.ng_pattern_type or ""):
                return "CRITICAL"
            return "HIGH"
        if guardian_result.action_type == GuardianActionType.BLOCK_AND_SUGGEST:
            return "MEDIUM"
        return "LOW"

    async def _evaluate_memory_authority(
        self,
        decision: DecisionResult,
        context: BrainContext,
        original_message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> AuthorizationResult:
        """Memory Authority評価（長期記憶との整合性）"""
        if not context.user_life_axis:
            return AuthorizationResult(decision=AuthorizationDecision.APPROVE)

        memory_authority = create_memory_authority(
            long_term_memory=context.user_life_axis,
            user_name=sender_name,
            organization_id=context.organization_id,
        )

        ma_result = memory_authority.evaluate(
            message=original_message,
            action=decision.action,
            action_params=decision.params,
            context={"room_id": room_id, "account_id": account_id},
        )

        # BLOCK_AND_SUGGEST: HARD CONFLICTを検出
        if ma_result.decision == MemoryDecision.BLOCK_AND_SUGGEST:
            logger.info(
                f"🛡️ [MemoryAuthority] Action blocked: {decision.action}, "
                f"reasons={ma_result.reasons}, conflicts={len(ma_result.conflicts)}"
            )
            return AuthorizationResult(
                decision=AuthorizationDecision.BLOCK,
                blocked=True,
                response=HandlerResult(
                    success=True,
                    message=ma_result.alternative_message or (
                        f"🐺 {sender_name}さんが以前決めた方針と矛盾してるかもウル。"
                        "確認してほしいウル🐺"
                    ),
                ),
                memory_authority_result=ma_result,
            )

        # REQUIRE_CONFIRMATION: SOFT CONFLICTを検出
        if ma_result.decision == MemoryDecision.REQUIRE_CONFIRMATION:
            logger.info(
                f"⚠️ [MemoryAuthority] Confirmation required: {decision.action}, "
                f"reasons={ma_result.reasons}"
            )

            # SOFT_CONFLICTを非同期でログ保存
            asyncio.create_task(
                self._log_soft_conflict(
                    action=decision.action,
                    ma_result=ma_result,
                    room_id=room_id,
                    account_id=account_id,
                    organization_id=context.organization_id,
                    message_excerpt=original_message,
                )
            )

            return AuthorizationResult(
                decision=AuthorizationDecision.CONFIRM,
                blocked=True,
                response=HandlerResult(
                    success=True,
                    message=ma_result.confirmation_message or (
                        f"🐺 {sender_name}さん、ちょっと確認させてウル。"
                        "本当に進めていいウル？🐺"
                    ),
                ),
                memory_authority_result=ma_result,
                soft_conflict_logged=True,
            )

        # FORCE_MODE_SWITCH
        if ma_result.decision == MemoryDecision.FORCE_MODE_SWITCH:
            logger.warning(
                f"🚨 [MemoryAuthority] Force mode switch: {decision.action} → {ma_result.forced_mode}, "
                f"reasons={ma_result.reasons}"
            )
            return AuthorizationResult(
                decision=AuthorizationDecision.FORCE_MODE_SWITCH,
                blocked=True,
                response=HandlerResult(
                    success=True,
                    message=ma_result.alternative_message or (
                        "🐺 大事な話ウルね。ゆっくり聞かせてほしいウル"
                    ),
                ),
                memory_authority_result=ma_result,
            )

        # APPROVE
        logger.debug(
            f"✅ [MemoryAuthority] Action approved: {decision.action}, "
            f"confidence={ma_result.confidence:.2f}"
        )
        return AuthorizationResult(
            decision=AuthorizationDecision.APPROVE,
            memory_authority_result=ma_result,
        )

    async def _log_soft_conflict(
        self,
        action: str,
        ma_result: MemoryAuthorityResult,
        room_id: str,
        account_id: str,
        organization_id: str,
        message_excerpt: str,
    ) -> None:
        """SOFT_CONFLICTをログ保存"""
        try:
            ma_logger = get_memory_authority_logger()

            detected_memory_reference = ""
            if ma_result.conflicts:
                excerpts = [c.get("excerpt", "") for c in ma_result.conflicts]
                detected_memory_reference = " | ".join(excerpts[:3])

            conflict_reason = ""
            if ma_result.reasons:
                conflict_reason = " / ".join(ma_result.reasons[:3])

            conflict_details = [
                {
                    "memory_type": c.get("memory_type", ""),
                    "excerpt": c.get("excerpt", ""),
                    "why_conflict": c.get("why_conflict", ""),
                    "severity": c.get("severity", ""),
                }
                for c in ma_result.conflicts
            ]

            await ma_logger.log_soft_conflict_async(
                action=action,
                detected_memory_reference=detected_memory_reference,
                conflict_reason=conflict_reason,
                room_id=room_id,
                account_id=account_id,
                organization_id=organization_id,
                message_excerpt=message_excerpt,
                conflict_details=conflict_details,
                confidence=ma_result.confidence,
            )
        except Exception as e:
            logger.warning(f"Error logging soft conflict: {e}")

    async def _evaluate_execution_excellence(
        self,
        decision: DecisionResult,
        context: BrainContext,
        original_message: str,
    ) -> AuthorizationResult:
        """ExecutionExcellence判定（複合タスク検出）"""
        if not self.execution_excellence or not original_message:
            return AuthorizationResult(decision=AuthorizationDecision.APPROVE)

        # 複合タスク判定
        if not self.execution_excellence.should_use_workflow(original_message, context):
            return AuthorizationResult(decision=AuthorizationDecision.APPROVE)

        logger.info(f"🔄 Using ExecutionExcellence for complex request: {original_message[:50]}...")

        try:
            ee_result = await self.execution_excellence.execute_request(
                request=original_message,
                context=context,
            )

            # 単一タスク判定（ExecutionExcellenceが分解不要と判断した場合）
            if ee_result.plan_id == "single_task":
                logger.debug("ExecutionExcellence: Single task detected, falling back to normal execution")
                return AuthorizationResult(decision=AuthorizationDecision.APPROVE)

            # ExecutionExcellenceの結果を使用
            return AuthorizationResult(
                decision=AuthorizationDecision.APPROVE,
                blocked=False,
                execution_excellence_used=True,
                execution_excellence_result=ee_result,
                response=HandlerResult(
                    success=ee_result.success,
                    message=ee_result.message,
                    suggestions=ee_result.suggestions,
                ),
            )
        except Exception as e:
            logger.warning(f"ExecutionExcellence failed, falling back to normal execution: {e}")
            return AuthorizationResult(decision=AuthorizationDecision.APPROVE)
