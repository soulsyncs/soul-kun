# lib/brain/core/pipeline.py
"""
SoulkunBrain 処理パイプライン層

理解層（_understand）、判断層（_decide）、実行層（_execute）、
Phase 2F Outcome Learning（_record_outcome_event）を含む。
"""

import asyncio
import logging
from typing import Optional, Dict, Any

from lib.brain.models import (
    BrainContext,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
)

logger = logging.getLogger(__name__)


class PipelineMixin:
    """SoulkunBrain処理パイプライン関連メソッドを提供するMixin"""

    # =========================================================================
    # 理解層
    # =========================================================================

    async def _understand(
        self,
        message: str,
        context: BrainContext,
        thought_chain=None,
    ) -> UnderstandingResult:
        """
        ユーザーの入力から意図を推論

        BrainUnderstandingクラスに委譲。
        省略の補完、代名詞解決、曖昧性の解消、感情の検出等を行う。

        v10.28.3: LLM理解層に強化（Phase D完了）
        - LLMベースの意図推論（フォールバック: キーワードマッチング）
        - 代名詞解決: 「あれ」「それ」「あの人」→ 具体的な対象
        - 省略補完: 「完了にして」→ 直近のタスク
        - 感情検出: ポジティブ/ネガティブ/ニュートラル
        - 緊急度検出: 「至急」「急いで」等
        - 確認モード: 確信度0.7未満で発動

        v10.34.0: Ultimate Brain Phase 1
        - thought_chain: 思考連鎖の結果（あれば活用）
        """
        # 思考連鎖の結果がある場合、コンテキストに追加
        if thought_chain:
            # 思考連鎖で低確信度（<0.7）なら確認モードを促す
            if thought_chain.confidence < 0.7:
                logger.debug(
                    f"Thought chain suggests confirmation: "
                    f"confidence={thought_chain.confidence:.2f}"
                )

        return await self.understanding.understand(message, context)

    # =========================================================================
    # 判断層
    # =========================================================================

    async def _decide(
        self,
        understanding: UnderstandingResult,
        context: BrainContext,
    ) -> DecisionResult:
        """
        BrainDecisionクラスに委譲。
        v10.28.4: 判断層に強化（Phase E完了）

        理解した意図に基づいてアクションを決定する。
        - SYSTEM_CAPABILITIESから適切な機能を選択
        - 確信度・リスクレベルに基づく確認要否判断
        - MVV整合性チェック
        - 複数アクション検出
        """
        return await self.decision.decide(understanding, context)

    # =========================================================================
    # 実行層
    # =========================================================================

    async def _execute(
        self,
        decision: DecisionResult,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> HandlerResult:
        """
        BrainExecutionクラスに委譲。
        v10.47.0: authorization_gateに権限チェックを統合

        判断層からの指令に基づいてハンドラーを呼び出し、結果を統合する。
        """
        # =================================================================
        # 権限チェック（authorization_gateに委譲）
        # =================================================================
        auth_result = await self.authorization_gate.evaluate(
            decision=decision,
            context=context,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )

        # ブロック/確認が必要な場合は早期リターン
        if auth_result.blocked and auth_result.response:
            return auth_result.response

        # ExecutionExcellenceが使用された場合
        if auth_result.execution_excellence_used and auth_result.execution_excellence_result:
            ee_result = auth_result.execution_excellence_result
            suggestions_raw = getattr(ee_result, 'suggestions', None)
            return HandlerResult(
                success=ee_result.success,
                message=ee_result.message,
                suggestions=list(suggestions_raw) if suggestions_raw else [],
            )

        # =================================================================
        # 従来の実行フロー
        # =================================================================
        result = await self.execution.execute(
            decision=decision,
            context=context,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )
        return result.to_handler_result()

    # =========================================================================
    # Phase 2F: Outcome Learning
    # =========================================================================

    async def _record_outcome_event(
        self,
        action: str,
        target_account_id: str,
        target_room_id: str,
        action_params: Optional[Dict[str, Any]] = None,
        context_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Phase 2F: アクション結果を非同期で記録（fire-and-forget）

        Note: asyncio.to_thread()で同期DB呼び出しをオフロードし、
        イベントループをブロックしない。
        """
        try:
            # PII保護: message/body/contentキーを除外してからDB保存
            safe_params = {
                k: v for k, v in (action_params or {}).items()
                if k not in ("message", "body", "content", "text")
            } if action_params else None

            def _sync_record():
                with self.pool.connect() as conn:
                    self.outcome_learning.record_action(
                        conn=conn,
                        action=action,
                        target_account_id=target_account_id,
                        target_room_id=target_room_id,
                        action_params=safe_params,
                        context_snapshot=context_snapshot,
                    )
            await asyncio.to_thread(_sync_record)
        except Exception as e:
            logger.warning("Phase 2F outcome recording failed: %s", type(e).__name__)
