# lib/brain/state_manager.py
"""
ソウルくんの脳 - 状態管理層

このファイルには、マルチステップ対話の状態を統一管理するクラスを定義します。
脳の7つの鉄則のうち「6. 状態管理は脳が統一管理」を実現します。

設計書: docs/13_brain_architecture.md 第9章

【管理する状態タイプ】
- normal: 通常状態（状態なし）
- goal_setting: 目標設定対話中
- announcement: アナウンス確認中
- confirmation: 確認待ち
- task_pending: タスク作成待ち
- multi_action: 複数アクション実行中
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from uuid import UUID

from sqlalchemy import text

from lib.brain.models import ConversationState, StateType
from lib.brain.constants import SESSION_TIMEOUT_MINUTES
from lib.brain.exceptions import StateError

logger = logging.getLogger(__name__)


class BrainStateManager:
    """
    脳の状態管理クラス

    マルチステップ対話（目標設定、アナウンス確認、確認待ち等）の状態を
    統一的に管理する。

    使用例:
        state_manager = BrainStateManager(pool=db_pool, org_id="org_soulsyncs")

        # 状態取得
        state = await state_manager.get_current_state(room_id, user_id)

        # 状態遷移
        new_state = await state_manager.transition_to(
            room_id=room_id,
            user_id=user_id,
            state_type=StateType.GOAL_SETTING,
            step="why",
            data={"retry_count": 0},
            timeout_minutes=30,
        )

        # 状態クリア
        await state_manager.clear_state(room_id, user_id, reason="completed")
    """

    def __init__(self, pool, org_id: str):
        """
        Args:
            pool: データベース接続プール（SQLAlchemy Engine or AsyncEngine）
            org_id: 組織ID
        """
        self.pool = pool
        self.org_id = org_id
        # プールが同期か非同期かを検出
        self._is_async_pool = hasattr(pool, 'begin') and asyncio.iscoroutinefunction(getattr(pool, 'begin', None))

        # org_idがUUID形式かどうかを判定
        # brain_conversation_statesテーブルはorganization_idがUUID型
        # 'org_soulsyncs'などのテキスト形式の場合はクエリをスキップ
        self._org_id_is_uuid = self._check_uuid_format(org_id)

        logger.debug(f"BrainStateManager initialized for org_id={org_id}, async_pool={self._is_async_pool}, uuid_org={self._org_id_is_uuid}")

    def _check_uuid_format(self, org_id: str) -> bool:
        """org_idがUUID形式かどうかをチェック"""
        if not org_id:
            return False
        try:
            UUID(org_id)
            return True
        except (ValueError, TypeError):
            return False

    def _execute_sync(self, query, params: dict):
        """同期的にクエリを実行"""
        with self.pool.connect() as conn:
            result = conn.execute(query, params)
            conn.commit()
            return result

    # =========================================================================
    # 状態取得
    # =========================================================================

    async def get_current_state(
        self,
        room_id: str,
        user_id: str,
    ) -> Optional[ConversationState]:
        """
        現在の状態を取得

        タイムアウトしている場合は自動的にクリアしてNoneを返す。

        Args:
            room_id: ChatWorkルームID
            user_id: ユーザーのアカウントID（ChatWork account_id）

        Returns:
            ConversationState: 現在の状態（存在しない場合はNone）
        """
        # org_idがUUID形式でない場合はスキップ
        # brain_conversation_statesテーブルはorganization_idがUUID型のため
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping brain_conversation_states query: org_id={self.org_id} is not UUID format")
            return None

        try:
            query = text("""
                SELECT
                    id, organization_id, room_id, user_id,
                    state_type, state_step, state_data,
                    reference_type, reference_id,
                    expires_at, timeout_minutes,
                    created_at, updated_at
                FROM brain_conversation_states
                WHERE organization_id = :org_id
                  AND room_id = :room_id
                  AND user_id = :user_id
            """)

            # 同期プールの場合は同期的に実行
            with self.pool.connect() as conn:
                result = conn.execute(query, {
                    "org_id": self.org_id,
                    "room_id": room_id,
                    "user_id": user_id,
                })
                row = result.fetchone()

            if row is None:
                return None

            # タイムアウト判定
            expires_at = row.expires_at
            if expires_at and datetime.now(expires_at.tzinfo if expires_at.tzinfo else None) > expires_at:
                # タイムアウト → 自動クリア（同期的に実行）
                logger.info(f"State expired, auto-clearing: room={room_id}, user={user_id}")
                try:
                    self._clear_state_sync(room_id, user_id, reason="timeout")
                except Exception as clear_err:
                    logger.warning(f"Failed to clear expired state: {clear_err}")
                return None

            # ConversationStateに変換
            state = ConversationState(
                state_id=str(row.id),
                organization_id=str(row.organization_id),
                room_id=row.room_id,
                user_id=row.user_id,
                state_type=StateType(row.state_type),
                state_step=row.state_step,
                state_data=row.state_data or {},
                reference_type=row.reference_type,
                reference_id=str(row.reference_id) if row.reference_id else None,
                expires_at=row.expires_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

            logger.debug(
                f"State retrieved: room={room_id}, user={user_id}, "
                f"type={state.state_type.value}, step={state.state_step}"
            )

            return state

        except Exception as e:
            logger.error(f"Error getting current state: {e}")
            # エラー時は状態なしとして扱う（安全側）
            return None

    # =========================================================================
    # 状態遷移
    # =========================================================================

    async def transition_to(
        self,
        room_id: str,
        user_id: str,
        state_type: StateType,
        step: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        timeout_minutes: int = SESSION_TIMEOUT_MINUTES,
    ) -> ConversationState:
        """
        状態を遷移（UPSERT）

        既存の状態がある場合は上書きする。
        遷移履歴をbrain_state_historyに記録する。

        Args:
            room_id: ChatWorkルームID
            user_id: ユーザーのアカウントID
            state_type: 新しい状態タイプ
            step: 状態内のステップ（例: why, what, how）
            data: 状態固有のデータ
            reference_type: 参照先タイプ（goal_session, announcement等）
            reference_id: 参照先ID
            timeout_minutes: タイムアウト時間（分）

        Returns:
            ConversationState: 新しい状態
        """
        now = datetime.utcnow()
        expires_at = now + timedelta(minutes=timeout_minutes)

        old_state = None
        state_id = None

        try:
            # 既存状態を取得（履歴記録用）
            old_state = await self.get_current_state(room_id, user_id)

            # 同期プールの場合は同期的に実行
            import json
            with self.pool.connect() as conn:
                # UPSERT
                upsert_query = text("""
                    INSERT INTO brain_conversation_states (
                        organization_id, room_id, user_id,
                        state_type, state_step, state_data,
                        reference_type, reference_id,
                        expires_at, timeout_minutes,
                        created_at, updated_at
                    ) VALUES (
                        :org_id, :room_id, :user_id,
                        :state_type, :state_step, CAST(:state_data AS jsonb),
                        :reference_type, :reference_id,
                        :expires_at, :timeout_minutes,
                        :now, :now
                    )
                    ON CONFLICT (organization_id, room_id, user_id)
                    DO UPDATE SET
                        state_type = EXCLUDED.state_type,
                        state_step = EXCLUDED.state_step,
                        state_data = EXCLUDED.state_data,
                        reference_type = EXCLUDED.reference_type,
                        reference_id = EXCLUDED.reference_id,
                        expires_at = EXCLUDED.expires_at,
                        timeout_minutes = EXCLUDED.timeout_minutes,
                        updated_at = EXCLUDED.updated_at
                    RETURNING id
                """)

                result = conn.execute(upsert_query, {
                    "org_id": self.org_id,
                    "room_id": room_id,
                    "user_id": user_id,
                    "state_type": state_type.value,
                    "state_step": step,
                    "state_data": json.dumps(data or {}),
                    "reference_type": reference_type,
                    "reference_id": reference_id,
                    "expires_at": expires_at,
                    "timeout_minutes": timeout_minutes,
                    "now": now,
                })
                row = result.fetchone()
                state_id = str(row.id) if row else None
                conn.commit()

            # 新しい状態を構築
            new_state = ConversationState(
                state_id=state_id,
                organization_id=self.org_id,
                room_id=room_id,
                user_id=user_id,
                state_type=state_type,
                state_step=step,
                state_data=data or {},
                reference_type=reference_type,
                reference_id=reference_id,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )

            logger.info(
                f"State transition: room={room_id}, user={user_id}, "
                f"type={state_type.value}, step={step}"
            )

            return new_state

        except Exception as e:
            logger.error(f"Error in state transition: {e}")
            raise StateError(
                message=f"Failed to transition state: {e}",
                room_id=room_id,
                user_id=user_id,
                current_state=old_state.state_type.value if old_state else None,
                target_state=state_type.value,
            )

    # =========================================================================
    # 状態クリア
    # =========================================================================

    async def clear_state(
        self,
        room_id: str,
        user_id: str,
        reason: str = "user_cancel",
    ) -> None:
        """
        状態をクリア（通常状態に戻す）

        履歴をbrain_state_historyに記録してから削除。

        Args:
            room_id: ChatWorkルームID
            user_id: ユーザーのアカウントID
            reason: クリア理由（user_cancel, timeout, completed, error）
        """
        try:
            self._clear_state_sync(room_id, user_id, reason)
        except Exception as e:
            logger.error(f"Error clearing state: {e}")

    def _clear_state_sync(
        self,
        room_id: str,
        user_id: str,
        reason: str = "user_cancel",
    ) -> None:
        """状態クリアの同期版"""
        with self.pool.connect() as conn:
            # 既存状態を取得
            select_query = text("""
                SELECT id, state_type, state_step
                FROM brain_conversation_states
                WHERE organization_id = :org_id
                  AND room_id = :room_id
                  AND user_id = :user_id
            """)
            result = conn.execute(select_query, {
                "org_id": self.org_id,
                "room_id": room_id,
                "user_id": user_id,
            })
            row = result.fetchone()

            if row is None:
                return

            # 削除
            delete_query = text("""
                DELETE FROM brain_conversation_states
                WHERE organization_id = :org_id
                  AND room_id = :room_id
                  AND user_id = :user_id
            """)
            conn.execute(delete_query, {
                "org_id": self.org_id,
                "room_id": room_id,
                "user_id": user_id,
            })
            conn.commit()

        logger.info(f"State cleared: room={room_id}, user={user_id}, reason={reason}")
            # クリアエラーは致命的ではないのでログのみ

    # =========================================================================
    # ステップ更新
    # =========================================================================

    async def update_step(
        self,
        room_id: str,
        user_id: str,
        new_step: str,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> ConversationState:
        """
        現在の状態内でステップを進める

        例: goal_settingの why → what

        v10.48.1: 同期プール対応（Cloud Functions互換性）
        - async with → with に変更
        - await conn.execute → conn.execute に変更

        Args:
            room_id: ChatWorkルームID
            user_id: ユーザーのアカウントID
            new_step: 新しいステップ
            additional_data: 追加のデータ（既存のstate_dataにマージ）

        Returns:
            ConversationState: 更新後の状態
        """
        try:
            now = datetime.utcnow()
            import json

            with self.pool.connect() as conn:
                with conn.begin():
                    # 既存状態を取得
                    select_query = text("""
                        SELECT id, state_type, state_step, state_data,
                               reference_type, reference_id, expires_at,
                               timeout_minutes, created_at
                        FROM brain_conversation_states
                        WHERE organization_id = :org_id
                          AND room_id = :room_id
                          AND user_id = :user_id
                        FOR UPDATE
                    """)
                    result = conn.execute(select_query, {
                        "org_id": self.org_id,
                        "room_id": room_id,
                        "user_id": user_id,
                    })
                    row = result.fetchone()

                    if row is None:
                        raise StateError(
                            message="No active state to update",
                            room_id=room_id,
                            user_id=user_id,
                        )

                    # 履歴に記録（同期版）
                    self._record_history_sync(
                        conn=conn,
                        room_id=room_id,
                        user_id=user_id,
                        from_state_type=row.state_type,
                        from_state_step=row.state_step,
                        to_state_type=row.state_type,
                        to_state_step=new_step,
                        reason="user_action",
                        state_id=str(row.id),
                    )

                    # state_dataをマージ
                    merged_data = row.state_data or {}
                    if additional_data:
                        merged_data.update(additional_data)

                    # タイムアウトを延長
                    new_expires = now + timedelta(minutes=row.timeout_minutes)

                    # 更新
                    update_query = text("""
                        UPDATE brain_conversation_states
                        SET state_step = :new_step,
                            state_data = CAST(:state_data AS jsonb),
                            expires_at = :expires_at,
                            updated_at = :now
                        WHERE organization_id = :org_id
                          AND room_id = :room_id
                          AND user_id = :user_id
                    """)
                    conn.execute(update_query, {
                        "org_id": self.org_id,
                        "room_id": room_id,
                        "user_id": user_id,
                        "new_step": new_step,
                        "state_data": json.dumps(merged_data),
                        "expires_at": new_expires,
                        "now": now,
                    })

            # 更新後の状態を構築
            updated_state = ConversationState(
                state_id=str(row.id),
                organization_id=self.org_id,
                room_id=room_id,
                user_id=user_id,
                state_type=StateType(row.state_type),
                state_step=new_step,
                state_data=merged_data,
                reference_type=row.reference_type,
                reference_id=str(row.reference_id) if row.reference_id else None,
                expires_at=new_expires,
                created_at=row.created_at,
                updated_at=now,
            )

            logger.info(
                f"State step updated: room={room_id}, user={user_id}, "
                f"step={row.state_step} → {new_step}"
            )

            return updated_state

        except StateError:
            raise
        except Exception as e:
            logger.error(f"Error updating step: {e}")
            raise StateError(
                message=f"Failed to update step: {e}",
                room_id=room_id,
                user_id=user_id,
            )

    # =========================================================================
    # クリーンアップ
    # =========================================================================

    async def cleanup_expired_states(self) -> int:
        """
        期限切れの状態をクリーンアップ

        v10.48.1: 同期プール対応（Cloud Functions互換性）

        Returns:
            int: クリーンアップした状態の数
        """
        try:
            with self.pool.connect() as conn:
                with conn.begin():
                    # DB関数を呼び出し
                    result = conn.execute(
                        text("SELECT cleanup_expired_brain_states()")
                    )
                    row = result.fetchone()
                    deleted_count = row[0] if row else 0

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired brain states")

            return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning up expired states: {e}")
            return 0

    # =========================================================================
    # ヘルパーメソッド
    # =========================================================================

    async def _record_history(
        self,
        conn,
        room_id: str,
        user_id: str,
        from_state: Optional[ConversationState] = None,
        from_state_type: Optional[str] = None,
        from_state_step: Optional[str] = None,
        to_state_type: Optional[StateType] = None,
        to_state_step: Optional[str] = None,
        reason: str = "user_action",
        state_id: Optional[str] = None,
    ) -> None:
        """状態遷移履歴を記録"""
        if from_state:
            from_type = from_state.state_type.value
            from_step = from_state.state_step
        else:
            from_type = from_state_type
            from_step = from_state_step

        to_type = to_state_type.value if isinstance(to_state_type, StateType) else to_state_type

        history_query = text("""
            INSERT INTO brain_state_history (
                organization_id, room_id, user_id,
                from_state_type, from_state_step,
                to_state_type, to_state_step,
                transition_reason, state_id
            ) VALUES (
                :org_id, :room_id, :user_id,
                :from_type, :from_step,
                :to_type, :to_step,
                :reason, :state_id
            )
        """)
        await conn.execute(history_query, {
            "org_id": self.org_id,
            "room_id": room_id,
            "user_id": user_id,
            "from_type": from_type,
            "from_step": from_step,
            "to_type": to_type,
            "to_step": to_state_step,
            "reason": reason,
            "state_id": state_id,
        })

    def _record_history_sync(
        self,
        conn,
        room_id: str,
        user_id: str,
        from_state: Optional[ConversationState] = None,
        from_state_type: Optional[str] = None,
        from_state_step: Optional[str] = None,
        to_state_type: Optional[StateType] = None,
        to_state_step: Optional[str] = None,
        reason: str = "user_action",
        state_id: Optional[str] = None,
    ) -> None:
        """
        状態遷移履歴を記録（同期版）

        v10.48.1: Cloud Functions互換性のために追加
        """
        if from_state:
            from_type = from_state.state_type.value
            from_step = from_state.state_step
        else:
            from_type = from_state_type
            from_step = from_state_step

        to_type = to_state_type.value if isinstance(to_state_type, StateType) else to_state_type

        history_query = text("""
            INSERT INTO brain_state_history (
                organization_id, room_id, user_id,
                from_state_type, from_state_step,
                to_state_type, to_state_step,
                transition_reason, state_id
            ) VALUES (
                :org_id, :room_id, :user_id,
                :from_type, :from_step,
                :to_type, :to_step,
                :reason, :state_id
            )
        """)
        conn.execute(history_query, {
            "org_id": self.org_id,
            "room_id": room_id,
            "user_id": user_id,
            "from_type": from_type,
            "from_step": from_step,
            "to_type": to_type,
            "to_step": to_state_step,
            "reason": reason,
            "state_id": state_id,
        })

    # =========================================================================
    # 同期版メソッド（互換性のため）
    # =========================================================================

    def get_current_state_sync(
        self,
        room_id: str,
        user_id: str,
    ) -> Optional[ConversationState]:
        """
        現在の状態を取得（同期版）

        既存のFlask/Cloud Functionsとの互換性のため。
        """
        # org_idがUUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping brain_conversation_states query (sync): org_id={self.org_id} is not UUID format")
            return None

        try:
            query = text("""
                SELECT
                    id, organization_id, room_id, user_id,
                    state_type, state_step, state_data,
                    reference_type, reference_id,
                    expires_at, timeout_minutes,
                    created_at, updated_at
                FROM brain_conversation_states
                WHERE organization_id = :org_id
                  AND room_id = :room_id
                  AND user_id = :user_id
            """)

            with self.pool.connect() as conn:
                result = conn.execute(query, {
                    "org_id": self.org_id,
                    "room_id": room_id,
                    "user_id": user_id,
                })
                row = result.fetchone()

            if row is None:
                return None

            # タイムアウト判定
            expires_at = row.expires_at
            if expires_at and datetime.utcnow() > expires_at.replace(tzinfo=None):
                logger.info(f"State expired, will be auto-cleared: room={room_id}, user={user_id}")
                # 同期版ではクリアは行わず、Noneを返すのみ
                return None

            state = ConversationState(
                state_id=str(row.id),
                organization_id=str(row.organization_id),
                room_id=row.room_id,
                user_id=row.user_id,
                state_type=StateType(row.state_type),
                state_step=row.state_step,
                state_data=row.state_data or {},
                reference_type=row.reference_type,
                reference_id=str(row.reference_id) if row.reference_id else None,
                expires_at=row.expires_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

            return state

        except Exception as e:
            logger.error(f"Error getting current state (sync): {e}")
            return None

    def transition_to_sync(
        self,
        room_id: str,
        user_id: str,
        state_type: StateType,
        step: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        timeout_minutes: int = SESSION_TIMEOUT_MINUTES,
    ) -> ConversationState:
        """
        状態を遷移（同期版）

        既存のFlask/Cloud Functionsとの互換性のため。
        """
        now = datetime.utcnow()
        expires_at = now + timedelta(minutes=timeout_minutes)

        try:
            with self.pool.connect() as conn:
                with conn.begin():
                    import json
                    upsert_query = text("""
                        INSERT INTO brain_conversation_states (
                            organization_id, room_id, user_id,
                            state_type, state_step, state_data,
                            reference_type, reference_id,
                            expires_at, timeout_minutes,
                            created_at, updated_at
                        ) VALUES (
                            :org_id, :room_id, :user_id,
                            :state_type, :state_step, CAST(:state_data AS jsonb),
                            :reference_type, :reference_id,
                            :expires_at, :timeout_minutes,
                            :now, :now
                        )
                        ON CONFLICT (organization_id, room_id, user_id)
                        DO UPDATE SET
                            state_type = EXCLUDED.state_type,
                            state_step = EXCLUDED.state_step,
                            state_data = EXCLUDED.state_data,
                            reference_type = EXCLUDED.reference_type,
                            reference_id = EXCLUDED.reference_id,
                            expires_at = EXCLUDED.expires_at,
                            timeout_minutes = EXCLUDED.timeout_minutes,
                            updated_at = EXCLUDED.updated_at
                        RETURNING id
                    """)

                    result = conn.execute(upsert_query, {
                        "org_id": self.org_id,
                        "room_id": room_id,
                        "user_id": user_id,
                        "state_type": state_type.value,
                        "state_step": step,
                        "state_data": json.dumps(data or {}),
                        "reference_type": reference_type,
                        "reference_id": reference_id,
                        "expires_at": expires_at,
                        "timeout_minutes": timeout_minutes,
                        "now": now,
                    })
                    row = result.fetchone()
                    state_id = str(row.id) if row else None

            new_state = ConversationState(
                state_id=state_id,
                organization_id=self.org_id,
                room_id=room_id,
                user_id=user_id,
                state_type=state_type,
                state_step=step,
                state_data=data or {},
                reference_type=reference_type,
                reference_id=reference_id,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )

            logger.info(
                f"State transition (sync): room={room_id}, user={user_id}, "
                f"type={state_type.value}, step={step}"
            )

            return new_state

        except Exception as e:
            logger.error(f"Error in state transition (sync): {e}")
            raise StateError(
                message=f"Failed to transition state: {e}",
                room_id=room_id,
                user_id=user_id,
                target_state=state_type.value,
            )

    def clear_state_sync(
        self,
        room_id: str,
        user_id: str,
        reason: str = "user_cancel",
    ) -> None:
        """
        状態をクリア（同期版）

        既存のFlask/Cloud Functionsとの互換性のため。
        """
        try:
            with self.pool.connect() as conn:
                with conn.begin():
                    delete_query = text("""
                        DELETE FROM brain_conversation_states
                        WHERE organization_id = :org_id
                          AND room_id = :room_id
                          AND user_id = :user_id
                    """)
                    conn.execute(delete_query, {
                        "org_id": self.org_id,
                        "room_id": room_id,
                        "user_id": user_id,
                    })

            logger.info(f"State cleared (sync): room={room_id}, user={user_id}, reason={reason}")

        except Exception as e:
            logger.error(f"Error clearing state (sync): {e}")
