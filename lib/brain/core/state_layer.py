# lib/brain/core/state_layer.py
"""
SoulkunBrain 状態管理層

会話状態の取得・遷移・クリア・ステップ更新メソッドを含む。
BrainStateManagerへの委譲層。
"""

import asyncio
import logging
from typing import Optional, Dict

from sqlalchemy import text

from lib.brain.models import (
    ConversationState,
    StateType,
)
from lib.brain.constants import SESSION_TIMEOUT_MINUTES

logger = logging.getLogger(__name__)


class StateLayerMixin:
    """SoulkunBrain状態管理層関連メソッドを提供するMixin"""

    # =========================================================================
    # 状態管理層
    # =========================================================================

    async def _get_current_state(
        self,
        room_id: str,
        user_id: str,
    ) -> Optional[ConversationState]:
        """
        現在の状態を取得（v10.40.1: 神経接続修理 - brain_conversation_statesのみ参照）

        v10.40.1: goal_setting_sessionsへのフォールバックを削除
        - goal_setting.py が brain_conversation_states を使用するように書き換えられたため
        - 全ての状態は brain_conversation_states で一元管理
        - 旧テーブル（goal_setting_sessions）は参照しない

        タイムアウトしている場合は自動的にクリアしてNoneを返す。
        """
        # brain_conversation_statesのみをチェック（goal_setting_sessionsは参照しない）
        return await self.state_manager.get_current_state(room_id, user_id)

    async def _get_current_state_with_user_org(
        self,
        room_id: str,
        user_id: str,
    ) -> Optional[ConversationState]:
        """
        ユーザーのorganization_idを使用して状態を取得（v10.56.6: マルチテナント対応）

        状態保存時にユーザーのorg_idを使用しているため、
        取得時も同じorg_idを使用する必要がある。

        Args:
            room_id: ChatWorkルームID
            user_id: ユーザーのアカウントID

        Returns:
            ConversationState: 現在の状態（存在しない場合はNone）
        """
        try:
            from lib.brain.state_manager import BrainStateManager

            # ユーザーのorganization_idを取得
            user_org_id = await self._get_user_organization_id(user_id)
            if not user_org_id:
                logger.debug("[状態取得] ユーザーのorg_id取得失敗")
                return None

            logger.debug("[状態取得] ユーザーorg_id使用")

            # ユーザーのorg_idで一時的なBrainStateManagerを作成
            user_state_manager = BrainStateManager(pool=self.pool, org_id=user_org_id)
            return await user_state_manager.get_current_state(room_id, user_id)

        except Exception as e:
            logger.error(f"❌ [状態取得] エラー: {type(e).__name__}")
            return None

    async def _get_user_organization_id(self, user_id: str) -> Optional[str]:
        """
        ユーザーのorganization_idを取得（v10.56.6: マルチテナント対応）

        Args:
            user_id: ユーザーのアカウントID（ChatWork account_id）

        Returns:
            str: ユーザーのorganization_id（取得失敗時はNone）
        """
        try:
            query = text("""
                SELECT organization_id FROM users
                WHERE chatwork_account_id = :account_id
                LIMIT 1
            """)

            def _sync():
                with self.pool.connect() as conn:
                    result = conn.execute(query, {"account_id": str(user_id)})
                    return result.fetchone()

            row = await asyncio.to_thread(_sync)

            if row and row[0]:
                return str(row[0])
            return None

        except Exception as e:
            logger.warning(f"⚠️ [org_id取得] エラー: {type(e).__name__}")
            return None

    async def _transition_to_state(
        self,
        room_id: str,
        user_id: str,
        state_type: StateType,
        step: Optional[str] = None,
        data: Optional[Dict] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        timeout_minutes: int = SESSION_TIMEOUT_MINUTES,
    ) -> ConversationState:
        """
        状態を遷移

        BrainStateManagerに委譲してDBにUPSERT。
        """
        return await self.state_manager.transition_to(
            room_id=room_id,
            user_id=user_id,
            state_type=state_type,
            step=step,
            data=data,
            reference_type=reference_type,
            reference_id=reference_id,
            timeout_minutes=timeout_minutes,
        )

    async def _clear_state(
        self,
        room_id: str,
        user_id: str,
        reason: str = "user_cancel",
    ) -> None:
        """
        状態をクリア（通常状態に戻す）

        BrainStateManagerに委譲してDBから削除。
        """
        await self.state_manager.clear_state(room_id, user_id, reason)

    async def _update_state_step(
        self,
        room_id: str,
        user_id: str,
        new_step: str,
        additional_data: Optional[Dict] = None,
    ) -> ConversationState:
        """
        現在の状態内でステップを進める

        BrainStateManagerに委譲してDBを更新。
        """
        return await self.state_manager.update_step(
            room_id=room_id,
            user_id=user_id,
            new_step=new_step,
            additional_data=additional_data,
        )
