# lib/brain/memory_manager.py
"""
脳メモリマネージャー

記憶更新、判断ログ記録、CEO教え管理を統括。
core.pyから分離して責務を明確化。

設計書: docs/13_brain_architecture.md
"""

import logging
from typing import Optional, List

from lib.brain.models import (
    BrainContext,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
    CEOTeachingContext,
)
from lib.brain.learning import BrainLearning
from lib.brain.ceo_learning import (
    CEOLearningService,
    CEO_ACCOUNT_IDS,
)
from lib.brain.memory_authority import MemoryAuthorityResult
from lib.brain.memory_authority_logger import get_memory_authority_logger

logger = logging.getLogger(__name__)


class BrainMemoryManager:
    """
    記憶更新・学習・CEO教えを統括するマネージャー

    責務:
    - 記憶の安全な更新
    - 判断ログの記録
    - SOFT_CONFLICTのログ記録
    - CEO教えの抽出と取得
    """

    def __init__(
        self,
        learning: BrainLearning,
        ceo_learning: CEOLearningService,
        organization_id: str = "",
    ):
        """
        Args:
            learning: BrainLearning インスタンス
            ceo_learning: CEOLearningService インスタンス
            organization_id: 組織ID
        """
        self.learning = learning
        self.ceo_learning = ceo_learning
        self.organization_id = organization_id

    # =========================================================================
    # 記憶更新
    # =========================================================================

    async def update_memory_safely(
        self,
        message: str,
        result: HandlerResult,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> None:
        """
        記憶を安全に更新（エラーを無視）

        BrainLearningクラスに委譲。
        """
        try:
            await self.learning.update_memory(
                message=message,
                result=result,
                context=context,
                room_id=room_id,
                account_id=account_id,
                sender_name=sender_name,
            )
        except Exception as e:
            logger.warning(f"Error updating memory: {type(e).__name__}")

    # =========================================================================
    # 判断ログ
    # =========================================================================

    async def log_decision_safely(
        self,
        message: str,
        understanding: UnderstandingResult,
        decision: DecisionResult,
        result: HandlerResult,
        room_id: str,
        account_id: str,
        understanding_time_ms: int = 0,
        execution_time_ms: int = 0,
        total_time_ms: int = 0,
    ) -> None:
        """
        判断ログを安全に記録（エラーを無視）

        BrainLearningクラスに委譲。
        """
        try:
            await self.learning.log_decision(
                message=message,
                understanding=understanding,
                decision=decision,
                result=result,
                room_id=room_id,
                account_id=account_id,
                understanding_time_ms=understanding_time_ms,
                execution_time_ms=execution_time_ms,
                total_time_ms=total_time_ms,
            )
        except Exception as e:
            logger.warning(f"Error logging decision: {type(e).__name__}")

    # =========================================================================
    # SOFT_CONFLICTログ
    # =========================================================================

    async def log_soft_conflict_safely(
        self,
        action: str,
        ma_result: MemoryAuthorityResult,
        room_id: str,
        account_id: str,
        organization_id: str,
        message_excerpt: str,
    ) -> None:
        """
        v10.43.1: SOFT_CONFLICTを観測モードログに非同期保存

        実行速度に影響を与えないよう、エラーは無視して処理を続行。

        Args:
            action: 実行しようとしたアクション
            ma_result: MemoryAuthorityの判定結果
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            organization_id: 組織ID
            message_excerpt: 元メッセージの抜粋
        """
        try:
            ma_logger = get_memory_authority_logger()

            # 検出された記憶参照を構築
            detected_memory_reference = ""
            if ma_result.conflicts:
                excerpts = [c.get("excerpt", "") for c in ma_result.conflicts]
                detected_memory_reference = " | ".join(excerpts[:3])

            # 矛盾理由を構築
            conflict_reason = ""
            if ma_result.reasons:
                conflict_reason = " / ".join(ma_result.reasons[:3])

            # 詳細な矛盾情報
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
            logger.warning(f"Error logging soft conflict: {type(e).__name__}")

    # =========================================================================
    # CEO Learning層
    # =========================================================================

    def is_ceo_user(self, account_id: str) -> bool:
        """
        CEOユーザーかどうかを判定

        Args:
            account_id: ユーザーのアカウントID

        Returns:
            bool: CEOユーザーならTrue
        """
        return account_id in CEO_ACCOUNT_IDS

    async def process_ceo_message_safely(
        self,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> None:
        """
        CEOメッセージから教えを抽出（エラーを無視）

        非同期で実行され、メイン処理をブロックしない。
        抽出された教えはCEOLearningServiceで処理・保存される。

        Args:
            message: CEOのメッセージ
            room_id: ChatWorkルームID
            account_id: CEOのアカウントID
            sender_name: CEOの名前
        """
        try:
            logger.info(f"🎓 Processing CEO message from {sender_name}")

            # CEOLearningServiceで教えを抽出・保存
            result = await self.ceo_learning.process_ceo_message(
                message=message,
                room_id=room_id,
                account_id=account_id,
            )

            if result.success and result.teachings_saved > 0:
                logger.info(
                    f"📚 Saved {result.teachings_saved} teachings from CEO message"
                )
            elif result.teachings_extracted == 0:
                logger.debug("No teachings detected in CEO message")

        except Exception as e:
            logger.warning(f"Error processing CEO message: {type(e).__name__}")

    async def get_ceo_teachings_context(
        self,
        message: str,
        account_id: Optional[str] = None,
    ) -> Optional[CEOTeachingContext]:
        """
        関連するCEO教えをコンテキストに追加

        現在のメッセージに関連する教えを取得し、
        CEOTeachingContextとして返す。

        Args:
            message: 現在のメッセージ
            account_id: ユーザーのアカウントID（CEOかどうかの判定用）

        Returns:
            Optional[CEOTeachingContext]: 関連するCEO教えのコンテキスト
        """
        try:
            # CEOLearningServiceのget_ceo_teaching_contextを使用
            is_ceo = self.is_ceo_user(account_id) if account_id else False

            ceo_context = self.ceo_learning.get_ceo_teaching_context(
                query=message,
                is_ceo=is_ceo,
            )

            # 関連する教えがなければNoneを返す
            if not ceo_context.relevant_teachings:
                return None

            return ceo_context

        except Exception as e:
            logger.warning(f"Error getting CEO teachings context: {type(e).__name__}")
            return None
