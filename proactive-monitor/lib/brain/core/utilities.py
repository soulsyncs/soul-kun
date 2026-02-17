# lib/brain/core/utilities.py
"""
SoulkunBrain ユーティリティメソッド

キャンセル判定、思考連鎖分析、自己批判、経過時間計算、
確認応答パース、確認応答ハンドリングを含む。

また、create_brain ファクトリー関数も定義。
"""

import logging
import time
from typing import Optional, Dict, Any, List, Callable, Union

from lib.brain.models import (
    BrainContext,
    BrainResponse,
    ConversationState,
)
from lib.brain.constants import CANCEL_KEYWORDS

logger = logging.getLogger(__name__)


class UtilitiesMixin:
    """SoulkunBrainユーティリティ関連メソッドを提供するMixin"""

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def _is_cancel_request(self, message: str) -> bool:
        """キャンセルリクエストかどうかを判定"""
        normalized = message.strip().lower()
        return any(kw in normalized for kw in CANCEL_KEYWORDS)

    # =========================================================================
    # Ultimate Brain - Phase 1: 思考連鎖 & 自己批判
    # =========================================================================

    def _analyze_with_thought_chain(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ):
        """
        思考連鎖で入力を事前分析

        Args:
            message: ユーザーメッセージ
            context: コンテキスト情報

        Returns:
            ThoughtChain: 思考連鎖の結果
        """
        try:
            return self.chain_of_thought.analyze(message, context)
        except Exception as e:
            logger.warning(f"Chain-of-thought analysis failed: {type(e).__name__}")
            # 失敗してもNoneを返すだけで処理は続行
            return None

    def _critique_and_refine_response(
        self,
        response: str,
        original_message: str,
        context: Optional[Dict[str, Any]] = None,
    ):
        """
        自己批判で回答を評価・改善

        Args:
            response: 生成された回答
            original_message: 元のユーザーメッセージ
            context: コンテキスト情報

        Returns:
            RefinedResponse: 改善された回答
        """
        try:
            return self.self_critique.evaluate_and_refine(
                response, original_message, context
            )
        except Exception as e:
            logger.warning(f"Self-critique failed: {type(e).__name__}")
            # 失敗した場合は元の回答をそのまま返す
            from lib.brain.self_critique import RefinedResponse
            return RefinedResponse(
                original=response,
                refined=response,
                improvements=[],
                refinement_applied=False,
                refinement_time_ms=0,
            )

    def _elapsed_ms(self, start_time: float) -> int:
        """経過時間をミリ秒で取得"""
        return int((time.time() - start_time) * 1000)

    def _parse_confirmation_response(
        self,
        message: str,
        options: List[str],
    ) -> Optional[Union[int, str]]:
        """
        確認応答をパースする（session_orchestratorへの委譲）

        Args:
            message: ユーザーの応答メッセージ
            options: 選択肢リスト

        Returns:
            int: 選択されたオプションのインデックス（0始まり）
            "cancel": キャンセル
            None: 解析不能
        """
        result: Union[int, str, None] = self.session_orchestrator._parse_confirmation_response(message, options)
        return result

    async def _handle_confirmation_response(
        self,
        message: str,
        state: ConversationState,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
        start_time: float,
    ) -> BrainResponse:
        """
        確認への応答を処理（session_orchestratorへの委譲）

        Args:
            message: ユーザーの応答メッセージ
            state: 現在の会話状態
            context: コンテキスト情報
            room_id: ルームID
            account_id: アカウントID
            sender_name: 送信者名
            start_time: 処理開始時刻

        Returns:
            BrainResponse: 処理結果
        """
        return await self.session_orchestrator._handle_confirmation_response(
            message=message,
            state=state,
            context=context,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            start_time=start_time,
        )


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_brain(
    pool,
    org_id: str,
    handlers: Optional[Dict[str, Callable]] = None,
    capabilities: Optional[Dict[str, Dict]] = None,
    get_ai_response_func: Optional[Callable] = None,
) -> "SoulkunBrain":
    """
    SoulkunBrainのインスタンスを作成

    使用例:
        brain = create_brain(
            pool=db_pool,
            org_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
            handlers=HANDLERS,
            capabilities=SYSTEM_CAPABILITIES,
        )
    """
    # 循環インポート回避のため遅延インポート
    from lib.brain.core.brain_class import SoulkunBrain

    return SoulkunBrain(
        pool=pool,
        org_id=org_id,
        handlers=handlers,
        capabilities=capabilities,
        get_ai_response_func=get_ai_response_func,
    )
