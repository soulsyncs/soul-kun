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
import json
import logging
from contextlib import contextmanager, asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from uuid import UUID

from sqlalchemy import text

from lib.brain.models import ConversationState, StateType
from lib.brain.constants import SESSION_TIMEOUT_MINUTES
from lib.brain.exceptions import StateError

logger = logging.getLogger(__name__)


class SafeJSONEncoder(json.JSONEncoder):
    """
    安全なJSONエンコーダー

    シリアライズ不可能なオブジェクト（dataclass、datetime等）を
    安全にJSON形式に変換する。

    v10.54.1: ConfidenceScoresシリアライズエラー対策
    """

    def default(self, obj):
        # to_dict()メソッドを持つオブジェクト（dataclass等）
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()

        # datetime
        if isinstance(obj, datetime):
            return obj.isoformat()

        # UUID
        if isinstance(obj, UUID):
            return str(obj)

        # Enum
        if hasattr(obj, 'value'):
            return obj.value

        # その他のオブジェクトは文字列化
        try:
            return str(obj)
        except Exception:
            return f"<non-serializable: {type(obj).__name__}>"


def _safe_json_dumps(data: Any) -> str:
    """
    安全なJSON文字列化

    Args:
        data: シリアライズ対象データ

    Returns:
        JSON文字列
    """
    return json.dumps(data or {}, cls=SafeJSONEncoder, ensure_ascii=False)


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
        """org_idがUUID形式かどうかをチェック（クエリスキップ判定用）"""
        if not org_id:
            return False
        try:
            UUID(org_id)
            return True
        except (ValueError, TypeError):
            return False

    @contextmanager
    def _connect_with_org_context(self):
        """
        organization_idコンテキスト付きでDB接続を取得（RLS対応）

        brain_*テーブルのRLSポリシーはapp.current_organization_idを
        参照するため、接続時に必ず設定する。

        注意:
        - 必ずSETを実行し、前の接続の値が残らないようにする（データ漏洩防止）
        - 終了時にRESETで値をクリア

        Yields:
            conn: organization_idが設定されたDB接続
        """
        with self.pool.connect() as conn:
            # pg8000ドライバはSET文でパラメータを使えないため、set_config()を使用
            conn.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                {"org_id": self.org_id}
            )
            try:
                yield conn
            finally:
                conn.execute(text("SELECT set_config('app.current_organization_id', '', false)"))

    @asynccontextmanager
    async def _connect_with_org_context_async(self):
        """
        organization_idコンテキスト付きでDB接続を取得（非同期版）

        注意:
        - 必ずSETを実行し、前の接続の値が残らないようにする（データ漏洩防止）
        - 終了時にRESETで値をクリア
        """
        async with self.pool.connect() as conn:
            # pg8000ドライバはSET文でパラメータを使えないため、set_config()を使用
            await conn.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                {"org_id": self.org_id}
            )
            try:
                yield conn
            finally:
                await conn.execute(text("SELECT set_config('app.current_organization_id', '', false)"))

    def _execute_sync(self, query, params: dict):
        """同期的にクエリを実行"""
        with self._connect_with_org_context() as conn:
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
            with self._connect_with_org_context() as conn:
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
            with self._connect_with_org_context() as conn:
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
                    "state_data": _safe_json_dumps(data),
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
        with self._connect_with_org_context() as conn:
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

            # 同期poolの場合は同期メソッドを使用
            if not self._is_async_pool:
                return self._update_step_sync(room_id, user_id, new_step, additional_data, now)

            async with self._connect_with_org_context_async() as conn:
                async with conn.begin():
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
                    result = await conn.execute(select_query, {
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

                    # 履歴に記録
                    await self._record_history(
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
                    await conn.execute(update_query, {
                        "org_id": self.org_id,
                        "room_id": room_id,
                        "user_id": user_id,
                        "new_step": new_step,
                        "state_data": _safe_json_dumps(merged_data),
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

    def _update_step_sync(
        self,
        room_id: str,
        user_id: str,
        new_step: str,
        additional_data: Optional[Dict[str, Any]],
        now: datetime,
    ) -> ConversationState:
        """update_stepの同期版"""
        with self._connect_with_org_context() as conn:
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
                "state_data": _safe_json_dumps(merged_data),
                "expires_at": new_expires,
                "now": now,
            })
            conn.commit()

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
            f"State step updated (sync): room={room_id}, user={user_id}, "
            f"step={row.state_step} → {new_step}"
        )

        return updated_state

    # =========================================================================
    # クリーンアップ
    # =========================================================================

    async def cleanup_expired_states(self) -> int:
        """
        期限切れの状態をクリーンアップ

        Returns:
            int: クリーンアップした状態の数
        """
        try:
            async with self._connect_with_org_context_async() as conn:
                async with conn.begin():
                    # DB関数を呼び出し
                    result = await conn.execute(
                        text("SELECT cleanup_expired_brain_states()")
                    )
                    row = result.fetchone()
                    deleted_count = row[0] if row else 0

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired brain states")

            return int(deleted_count) if deleted_count is not None else 0

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
        from_type: Optional[str]
        from_step: Optional[str]
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

            with self._connect_with_org_context() as conn:
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
            with self._connect_with_org_context() as conn:
                with conn.begin():
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
                        "state_data": _safe_json_dumps(data),
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
            with self._connect_with_org_context() as conn:
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


# =============================================================================
# LLM Brain用の拡張（設計書: 25章 セクション5.1.5）
# =============================================================================

from enum import Enum as PyEnum
from dataclasses import dataclass, field
import uuid


class LLMSessionMode(PyEnum):
    """
    LLM Brainのセッションモード

    設計書: docs/25_llm_native_brain_architecture.md セクション5.1.5
    """
    NORMAL = "normal"                    # 通常モード
    CONFIRMATION_PENDING = "confirmation_pending"  # 確認待ち
    MULTI_STEP_FLOW = "multi_step_flow"  # 複数ステップのフロー中
    ERROR_RECOVERY = "error_recovery"    # エラーからの回復中


@dataclass
class LLMPendingAction:
    """
    確認待ちの操作

    設計書: docs/25_llm_native_brain_architecture.md セクション5.1.5

    設計意図:
    - Guardian Layerが確認を要求した操作を保持
    - ユーザーの応答に基づいて実行/キャンセルを判断
    """
    # === 識別情報 ===
    action_id: str                       # アクションID（UUID）
    tool_name: str                       # 実行しようとしているTool名
    parameters: Dict[str, Any]           # パラメータ

    # === 確認情報 ===
    confirmation_question: str           # ユーザーに送った確認質問
    confirmation_type: str               # 確認の種類（danger/ambiguous/high_value/low_confidence）
    original_message: str                # 元のユーザーメッセージ

    # === 思考過程 ===
    original_reasoning: str = ""         # LLMが出力した思考過程
    confidence: float = 0.0              # 元の確信度

    # === タイムスタンプ ===
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None  # 有効期限（デフォルト: 10分）

    def is_expired(self) -> bool:
        """有効期限切れかどうか"""
        if self.expires_at is None:
            return datetime.utcnow() > self.created_at + timedelta(minutes=10)
        return datetime.utcnow() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "action_id": self.action_id,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "confirmation_question": self.confirmation_question,
            "confirmation_type": self.confirmation_type,
            "original_message": self.original_message,
            "original_reasoning": self.original_reasoning,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LLMPendingAction':
        """辞書から生成"""
        return cls(
            action_id=data.get("action_id", str(uuid.uuid4())),
            tool_name=data.get("tool_name", ""),
            parameters=data.get("parameters", {}),
            confirmation_question=data.get("confirmation_question", ""),
            confirmation_type=data.get("confirmation_type", "unknown"),
            original_message=data.get("original_message", ""),
            original_reasoning=data.get("original_reasoning", ""),
            confidence=data.get("confidence", 0.0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
        )

    def to_string(self) -> str:
        """LLMプロンプト用の文字列表現"""
        params_str = json.dumps(self.parameters, cls=SafeJSONEncoder, ensure_ascii=False, indent=2)
        return f"""
操作: {self.tool_name}
パラメータ: {params_str}
確認質問: {self.confirmation_question}
元のメッセージ: {self.original_message}
確信度: {self.confidence:.0%}
""".strip()


@dataclass
class LLMSessionState:
    """
    LLM Brainのセッション状態

    設計書: docs/25_llm_native_brain_architecture.md セクション5.1.5

    設計意図:
    - 確認フロー中の状態を保持
    - 連続した会話の文脈を維持
    - エラーからの復旧状態を管理
    """
    # === 識別情報 ===
    session_id: str                      # セッションID（UUID）
    user_id: str                         # ユーザーID
    room_id: str                         # ChatWorkルームID
    organization_id: str                 # 組織ID

    # === 状態 ===
    mode: LLMSessionMode = LLMSessionMode.NORMAL  # 現在のモード
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None   # 有効期限（デフォルト: 30分）

    # === pending操作（確認待ち） ===
    pending_action: Optional[LLMPendingAction] = None

    # === 会話コンテキスト ===
    conversation_context: Dict[str, Any] = field(default_factory=dict)
    last_intent: Optional[str] = None       # 最後に認識した意図
    last_tool_called: Optional[str] = None  # 最後に呼び出したTool

    # === エラー状態 ===
    last_error: Optional[str] = None
    error_count: int = 0

    def is_expired(self) -> bool:
        """セッションが期限切れかどうか"""
        if self.expires_at is None:
            # デフォルトは30分
            return datetime.utcnow() > self.created_at + timedelta(minutes=30)
        return datetime.utcnow() > self.expires_at

    def to_string(self) -> str:
        """LLMプロンプト用の文字列表現"""
        lines = [f"セッションモード: {self.mode.value}"]
        if self.pending_action:
            lines.append(f"確認待ち操作: {self.pending_action.tool_name}")
        if self.last_intent:
            lines.append(f"直前の意図: {self.last_intent}")
        if self.last_error:
            lines.append(f"直前のエラー: {self.last_error}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "room_id": self.room_id,
            "organization_id": self.organization_id,
            "mode": self.mode.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "pending_action": self.pending_action.to_dict() if self.pending_action else None,
            "conversation_context": self.conversation_context,
            "last_intent": self.last_intent,
            "last_tool_called": self.last_tool_called,
            "last_error": self.last_error,
            "error_count": self.error_count,
        }


class LLMStateManager:
    """
    LLM Brain用の状態管理

    設計書: docs/25_llm_native_brain_architecture.md セクション5.1.5

    【責務】
    - LLMセッション状態の作成・取得・更新・削除
    - pending操作の管理
    - 確認フローの状態遷移

    【注意】
    既存のBrainStateManagerと共存する。
    LLMSessionStateは既存のConversationStateとは別のデータモデル。
    ただし、DBテーブルは同じbrain_conversation_statesを使用し、
    state_dataフィールドにLLMセッション情報を格納する。
    """

    # 確認応答のキーワード
    APPROVAL_KEYWORDS = ["はい", "yes", "ok", "いいよ", "お願い", "実行", "1", "うん"]
    DENIAL_KEYWORDS = ["いいえ", "no", "やめ", "キャンセル", "だめ", "2", "ストップ"]

    def __init__(self, brain_state_manager: BrainStateManager):
        """
        Args:
            brain_state_manager: 既存のBrainStateManagerインスタンス
        """
        self.brain_state_manager = brain_state_manager

    async def get_current_state(
        self,
        room_id: str,
        user_id: str,
    ) -> Optional[ConversationState]:
        """
        現在の状態を取得（ContextBuilder互換）

        BrainStateManagerの同名メソッドへのラッパー。
        ContextBuilderが統一的なインターフェースで状態を取得できるようにする。

        Args:
            room_id: ChatWorkルームID
            user_id: ユーザーのアカウントID

        Returns:
            ConversationState: 現在の状態（存在しない場合はNone）
        """
        return await self.brain_state_manager.get_current_state(room_id, user_id)

    async def get_llm_session(
        self,
        user_id: str,
        room_id: str,
    ) -> Optional[LLMSessionState]:
        """
        LLMセッション状態を取得

        Returns:
            LLMSessionState: 有効なセッションがあれば返す、なければNone
        """
        # 既存のstate_managerから状態を取得
        state = await self.brain_state_manager.get_current_state(room_id, user_id)

        if not state:
            return None

        # state_dataからLLMセッション情報を復元
        state_data = state.state_data or {}
        llm_data = state_data.get("llm_session")

        if not llm_data:
            return None

        # pending_actionを復元
        pending_action = None
        if llm_data.get("pending_action"):
            pending_action = LLMPendingAction.from_dict(llm_data["pending_action"])
            if pending_action.is_expired():
                pending_action = None

        return LLMSessionState(
            session_id=llm_data.get("session_id", str(uuid.uuid4())),
            user_id=user_id,
            room_id=room_id,
            organization_id=state.organization_id,
            mode=LLMSessionMode(llm_data.get("mode", "normal")),
            pending_action=pending_action,
            conversation_context=llm_data.get("conversation_context", {}),
            last_intent=llm_data.get("last_intent"),
            last_tool_called=llm_data.get("last_tool_called"),
            last_error=llm_data.get("last_error"),
            error_count=llm_data.get("error_count", 0),
        )

    async def set_pending_action(
        self,
        user_id: str,
        room_id: str,
        pending_action: LLMPendingAction,
    ) -> LLMSessionState:
        """
        確認待ち操作を設定
        """
        session = await self.get_llm_session(user_id, room_id)

        if session is None:
            session = LLMSessionState(
                session_id=str(uuid.uuid4()),
                user_id=user_id,
                room_id=room_id,
                organization_id=self.brain_state_manager.org_id,
            )

        session.mode = LLMSessionMode.CONFIRMATION_PENDING
        session.pending_action = pending_action
        session.updated_at = datetime.utcnow()

        await self._save_llm_session(session)

        return session

    async def clear_pending_action(
        self,
        user_id: str,
        room_id: str,
    ) -> Optional[LLMSessionState]:
        """
        確認待ち操作をクリア
        """
        session = await self.get_llm_session(user_id, room_id)

        if session is None:
            return None

        session.mode = LLMSessionMode.NORMAL
        session.pending_action = None
        session.updated_at = datetime.utcnow()

        await self._save_llm_session(session)

        return session

    async def handle_confirmation_response(
        self,
        user_id: str,
        room_id: str,
        response: str,
    ) -> tuple[bool, Optional[LLMPendingAction]]:
        """
        確認応答を処理

        Returns:
            (approved, pending_action): 承認されたか、元の操作
        """
        session = await self.get_llm_session(user_id, room_id)

        if session is None or session.pending_action is None:
            return (False, None)

        pending = session.pending_action

        # 応答を解析
        approved = self._is_approval_response(response)

        # 状態をクリア
        await self.clear_pending_action(user_id, room_id)

        logger.info(f"Confirmation response: approved={approved}, tool={pending.tool_name}")

        return (approved, pending)

    def _is_approval_response(self, response: str) -> bool:
        """承認応答かどうかを判定"""
        response_lower = response.lower().strip()

        for keyword in self.APPROVAL_KEYWORDS:
            if keyword in response_lower:
                return True

        for keyword in self.DENIAL_KEYWORDS:
            if keyword in response_lower:
                return False

        # 不明な場合は否認として扱う（安全側に倒す）
        return False

    def is_confirmation_response(self, message: str) -> bool:
        """
        メッセージが確認応答かどうかを判定

        確認待ち中に別の意図のメッセージが来た場合の判定に使用
        """
        message_lower = message.lower().strip()

        # 明確な応答キーワードがあるかチェック
        all_keywords = self.APPROVAL_KEYWORDS + self.DENIAL_KEYWORDS
        return any(kw in message_lower for kw in all_keywords)

    async def _save_llm_session(self, session: LLMSessionState) -> None:
        """LLMセッションを保存（既存のstate_managerを通じて）"""
        llm_data = {
            "session_id": session.session_id,
            "mode": session.mode.value,
            "pending_action": session.pending_action.to_dict() if session.pending_action else None,
            "conversation_context": session.conversation_context,
            "last_intent": session.last_intent,
            "last_tool_called": session.last_tool_called,
            "last_error": session.last_error,
            "error_count": session.error_count,
        }

        # 既存のstate_managerを通じて保存
        await self.brain_state_manager.transition_to(
            room_id=session.room_id,
            user_id=session.user_id,
            state_type=StateType.CONFIRMATION if session.mode == LLMSessionMode.CONFIRMATION_PENDING else StateType.NORMAL,
            step=f"llm_{session.mode.value}",
            data={"llm_session": llm_data},
            timeout_minutes=30,
        )
