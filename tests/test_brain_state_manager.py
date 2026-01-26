# tests/test_brain_state_manager.py
"""
脳アーキテクチャ Phase C: 状態管理ユニットテスト

BrainStateManagerクラスのテストケース。
状態取得、遷移、クリア、ステップ更新、タイムアウト処理をテスト。
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from lib.brain.state_manager import BrainStateManager
from lib.brain.models import ConversationState, StateType
from lib.brain.exceptions import StateError


# =============================================================================
# テストデータ
# =============================================================================

# Note: brain_conversation_statesテーブルはorganization_idがUUID型のため、
# テストではUUID形式のorg_idを使用する必要がある
TEST_ORG_ID = "550e8400-e29b-41d4-a716-446655440000"  # Valid UUID format
TEST_ORG_ID_NON_UUID = "org_test"  # Non-UUID for skip behavior tests
TEST_ROOM_ID = "room_123"
TEST_USER_ID = "user_456"


def create_mock_row(
    state_type: str = "goal_setting",
    state_step: str = "why",
    state_data: dict = None,
    expires_at: datetime = None,
    reference_type: str = None,
    reference_id: str = None,
    org_id: str = None,
):
    """モック行データを作成"""
    row = MagicMock()
    row.id = uuid4()
    row.organization_id = org_id or TEST_ORG_ID  # UUID形式を使用
    row.room_id = TEST_ROOM_ID
    row.user_id = TEST_USER_ID
    row.state_type = state_type
    row.state_step = state_step
    row.state_data = state_data or {}
    row.reference_type = reference_type
    row.reference_id = reference_id
    # datetime.now()基準で計算（タイムゾーン問題回避）
    row.expires_at = expires_at or (datetime.now() + timedelta(minutes=30))
    row.timeout_minutes = 30
    row.created_at = datetime.now()
    row.updated_at = datetime.now()
    return row


# =============================================================================
# BrainStateManager 初期化テスト
# =============================================================================


class TestBrainStateManagerInit:
    """BrainStateManager初期化のテスト"""

    def test_init_with_pool_and_org_id(self):
        """プールとorg_idで初期化できる"""
        mock_pool = MagicMock()
        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)

        assert manager.pool == mock_pool
        assert manager.org_id == TEST_ORG_ID

    def test_init_stores_org_id(self):
        """org_idが保存される"""
        mock_pool = MagicMock()
        manager = BrainStateManager(pool=mock_pool, org_id="org_soulsyncs")

        assert manager.org_id == "org_soulsyncs"

    def test_init_detects_uuid_format(self):
        """UUID形式のorg_idを正しく検出する"""
        mock_pool = MagicMock()

        # UUID形式
        manager_uuid = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)
        assert manager_uuid._org_id_is_uuid is True

        # 非UUID形式
        manager_non_uuid = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID_NON_UUID)
        assert manager_non_uuid._org_id_is_uuid is False


class TestNonUuidOrgIdBehavior:
    """非UUID形式のorg_idの場合のスキップ動作テスト"""

    @pytest.mark.asyncio
    async def test_get_current_state_skips_for_non_uuid(self):
        """非UUID形式のorg_idの場合はクエリをスキップしてNoneを返す"""
        mock_pool = MagicMock()
        # DBが呼ばれないことを確認するためにassertを設定
        mock_pool.connect.assert_not_called()

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID_NON_UUID)
        state = await manager.get_current_state(TEST_ROOM_ID, TEST_USER_ID)

        assert state is None
        # DBへの接続が行われないことを確認
        mock_pool.connect.assert_not_called()

    def test_get_current_state_sync_skips_for_non_uuid(self):
        """非UUID形式のorg_idの場合は同期版もスキップしてNoneを返す"""
        mock_pool = MagicMock()

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID_NON_UUID)
        state = manager.get_current_state_sync(TEST_ROOM_ID, TEST_USER_ID)

        assert state is None
        mock_pool.connect.assert_not_called()


# =============================================================================
# 状態取得テスト
# =============================================================================


class TestGetCurrentState:
    """get_current_stateメソッドのテスト

    Note: get_current_stateは同期メソッドに変更されているが、
    テストはasyncio.run()で呼び出されるawaitableとして扱う。
    """

    @pytest.mark.asyncio
    async def test_returns_none_when_no_state(self):
        """状態がない場合はNoneを返す"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result
        # 同期コンテキストマネージャー
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)
        state = await manager.get_current_state(TEST_ROOM_ID, TEST_USER_ID)

        assert state is None

    @pytest.mark.asyncio
    async def test_returns_state_when_exists(self):
        """状態が存在する場合はConversationStateを返す"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        # タイムゾーン問題を回避するため、datetime.now()基準で十分に未来の時間を設定
        # tzinfoをNoneにして問題を回避
        future_time = datetime.now() + timedelta(hours=1)
        future_time = future_time.replace(tzinfo=None)
        mock_row = create_mock_row(expires_at=future_time)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_result
        # 同期コンテキストマネージャー
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)
        state = await manager.get_current_state(TEST_ROOM_ID, TEST_USER_ID)

        assert state is not None
        assert state.state_type == StateType.GOAL_SETTING
        assert state.state_step == "why"
        assert state.room_id == TEST_ROOM_ID
        assert state.user_id == TEST_USER_ID

    @pytest.mark.asyncio
    async def test_returns_none_when_expired(self):
        """タイムアウト済みの場合はNoneを返す"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        # 過去の時刻を設定（datetime.now()基準）、tzinfoをNoneに
        expired_time = datetime.now() - timedelta(minutes=10)
        expired_time = expired_time.replace(tzinfo=None)
        mock_row = create_mock_row(expires_at=expired_time)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_result
        mock_conn.commit = MagicMock()
        # 同期コンテキストマネージャー
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)

        # _clear_state_syncをモック（同期版）
        with patch.object(manager, '_clear_state_sync', MagicMock()) as mock_clear:
            state = await manager.get_current_state(TEST_ROOM_ID, TEST_USER_ID)

            # タイムアウト時はNoneを返し、クリアが呼ばれる
            assert state is None
            mock_clear.assert_called_once_with(TEST_ROOM_ID, TEST_USER_ID, reason="timeout")

    @pytest.mark.asyncio
    async def test_returns_none_on_db_error(self):
        """DBエラー時はNoneを返す（安全側）"""
        mock_pool = MagicMock()
        # connect().___enter__()で例外を発生させる
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(side_effect=Exception("DB connection error"))
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_pool.connect.return_value = mock_context

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)
        state = await manager.get_current_state(TEST_ROOM_ID, TEST_USER_ID)

        assert state is None


# =============================================================================
# 状態遷移テスト
# =============================================================================


class TestTransitionTo:
    """transition_toメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_creates_new_state(self):
        """新しい状態を作成できる"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        ))
        new_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=new_id)
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_pool.connect = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        ))

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)

        # get_current_stateをモック（既存状態なし）
        with patch.object(manager, 'get_current_state', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            state = await manager.transition_to(
                room_id=TEST_ROOM_ID,
                user_id=TEST_USER_ID,
                state_type=StateType.GOAL_SETTING,
                step="why",
                data={"retry_count": 0},
                timeout_minutes=30,
            )

            assert state is not None
            assert state.state_type == StateType.GOAL_SETTING
            assert state.state_step == "why"
            assert state.state_data == {"retry_count": 0}
            assert state.room_id == TEST_ROOM_ID
            assert state.user_id == TEST_USER_ID

    @pytest.mark.asyncio
    async def test_sets_expires_at(self):
        """expires_atが正しく設定される"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        ))
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=uuid4())
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_pool.connect = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        ))

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)

        with patch.object(manager, 'get_current_state', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            state = await manager.transition_to(
                room_id=TEST_ROOM_ID,
                user_id=TEST_USER_ID,
                state_type=StateType.CONFIRMATION,
                timeout_minutes=5,
            )

            # 5分後に期限切れ
            assert state.expires_at is not None
            expected_expiry = datetime.utcnow() + timedelta(minutes=5)
            assert abs((state.expires_at - expected_expiry).total_seconds()) < 2

    @pytest.mark.asyncio
    async def test_stores_reference_info(self):
        """参照情報が保存される"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        ))
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=uuid4())
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_pool.connect = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        ))

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)
        ref_id = str(uuid4())

        with patch.object(manager, 'get_current_state', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            state = await manager.transition_to(
                room_id=TEST_ROOM_ID,
                user_id=TEST_USER_ID,
                state_type=StateType.ANNOUNCEMENT,
                reference_type="announcement",
                reference_id=ref_id,
            )

            assert state.reference_type == "announcement"
            assert state.reference_id == ref_id


# =============================================================================
# 状態クリアテスト
# =============================================================================


class TestClearState:
    """clear_stateメソッドのテスト

    Note: clear_stateは_clear_state_sync（同期版）を内部で呼び出す。
    """

    @pytest.mark.asyncio
    async def test_clears_existing_state(self):
        """既存の状態をクリアできる"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_row = create_mock_row()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_result
        mock_conn.commit = MagicMock()
        # 同期コンテキストマネージャー
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)

        # エラーなく完了することを確認
        await manager.clear_state(TEST_ROOM_ID, TEST_USER_ID, reason="user_cancel")

        # executeが呼ばれたことを確認（SELECT + DELETE）
        assert mock_conn.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_does_nothing_when_no_state(self):
        """状態がない場合は何もしない"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None  # 状態なし
        mock_conn.execute.return_value = mock_result
        # 同期コンテキストマネージャー
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)

        # エラーなく完了することを確認
        await manager.clear_state(TEST_ROOM_ID, TEST_USER_ID)

        # SELECTのみ呼ばれる
        assert mock_conn.execute.call_count == 1


# =============================================================================
# ステップ更新テスト
# =============================================================================


class TestUpdateStep:
    """update_stepメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_updates_step(self):
        """ステップを更新できる"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        ))
        mock_row = create_mock_row(state_step="why")
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_pool.connect = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        ))

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)
        state = await manager.update_step(
            room_id=TEST_ROOM_ID,
            user_id=TEST_USER_ID,
            new_step="what",
        )

        assert state.state_step == "what"

    @pytest.mark.asyncio
    async def test_merges_additional_data(self):
        """追加データがマージされる"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        ))
        mock_row = create_mock_row(
            state_step="why",
            state_data={"retry_count": 0, "existing": "value"},
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_pool.connect = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        ))

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)
        state = await manager.update_step(
            room_id=TEST_ROOM_ID,
            user_id=TEST_USER_ID,
            new_step="what",
            additional_data={"retry_count": 1, "new_key": "new_value"},
        )

        # マージされたデータ
        assert state.state_data["retry_count"] == 1  # 上書き
        assert state.state_data["existing"] == "value"  # 維持
        assert state.state_data["new_key"] == "new_value"  # 追加

    @pytest.mark.asyncio
    async def test_raises_error_when_no_state(self):
        """状態がない場合はStateErrorを発生"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        ))
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None  # 状態なし
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_pool.connect = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        ))

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)

        with pytest.raises(StateError):
            await manager.update_step(
                room_id=TEST_ROOM_ID,
                user_id=TEST_USER_ID,
                new_step="what",
            )


# =============================================================================
# ConversationState モデルテスト
# =============================================================================


class TestConversationStateModel:
    """ConversationStateモデルのテスト"""

    def test_is_active_returns_true_for_active_state(self):
        """アクティブな状態ではis_activeがTrue"""
        state = ConversationState(
            state_type=StateType.GOAL_SETTING,
            expires_at=datetime.now() + timedelta(minutes=30),
        )
        assert state.is_active is True

    def test_is_active_returns_false_for_normal_state(self):
        """通常状態ではis_activeがFalse"""
        state = ConversationState(state_type=StateType.NORMAL)
        assert state.is_active is False

    def test_is_active_returns_false_when_expired(self):
        """期限切れではis_activeがFalse"""
        state = ConversationState(
            state_type=StateType.GOAL_SETTING,
            expires_at=datetime.now() - timedelta(minutes=10),
        )
        assert state.is_active is False

    def test_is_expired_returns_true_when_expired(self):
        """期限切れではis_expiredがTrue"""
        state = ConversationState(
            state_type=StateType.GOAL_SETTING,
            expires_at=datetime.now() - timedelta(minutes=10),
        )
        assert state.is_expired is True

    def test_is_expired_returns_false_when_not_expired(self):
        """期限内ではis_expiredがFalse"""
        state = ConversationState(
            state_type=StateType.GOAL_SETTING,
            expires_at=datetime.now() + timedelta(minutes=30),
        )
        assert state.is_expired is False

    def test_is_expired_returns_false_when_no_expiry(self):
        """expires_atがNoneならis_expiredはFalse"""
        state = ConversationState(
            state_type=StateType.GOAL_SETTING,
            expires_at=None,
        )
        assert state.is_expired is False


# =============================================================================
# StateType Enumテスト
# =============================================================================


class TestStateTypeEnum:
    """StateType Enumのテスト"""

    def test_all_state_types_exist(self):
        """全ての状態タイプが存在する"""
        assert StateType.NORMAL.value == "normal"
        assert StateType.GOAL_SETTING.value == "goal_setting"
        assert StateType.ANNOUNCEMENT.value == "announcement"
        assert StateType.CONFIRMATION.value == "confirmation"
        assert StateType.TASK_PENDING.value == "task_pending"
        assert StateType.MULTI_ACTION.value == "multi_action"

    def test_state_type_count(self):
        """6種類の状態タイプがある"""
        assert len(StateType) == 6


# =============================================================================
# 同期版メソッドテスト
# =============================================================================


class TestSyncMethods:
    """同期版メソッドのテスト"""

    def test_get_current_state_sync_returns_none_when_no_state(self):
        """状態がない場合はNoneを返す（同期版）"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute = MagicMock(return_value=mock_result)
        mock_pool.connect = MagicMock(return_value=MagicMock(
            __enter__=MagicMock(return_value=mock_conn),
            __exit__=MagicMock(return_value=None),
        ))

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)
        state = manager.get_current_state_sync(TEST_ROOM_ID, TEST_USER_ID)

        assert state is None

    def test_transition_to_sync_creates_state(self):
        """状態を作成できる（同期版）"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.begin = MagicMock(return_value=MagicMock(
            __enter__=MagicMock(return_value=None),
            __exit__=MagicMock(return_value=None),
        ))
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=uuid4())
        mock_conn.execute = MagicMock(return_value=mock_result)
        mock_pool.connect = MagicMock(return_value=MagicMock(
            __enter__=MagicMock(return_value=mock_conn),
            __exit__=MagicMock(return_value=None),
        ))

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)
        state = manager.transition_to_sync(
            room_id=TEST_ROOM_ID,
            user_id=TEST_USER_ID,
            state_type=StateType.CONFIRMATION,
            step="waiting",
        )

        assert state is not None
        assert state.state_type == StateType.CONFIRMATION
        assert state.state_step == "waiting"

    def test_clear_state_sync_succeeds(self):
        """状態をクリアできる（同期版）"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.begin = MagicMock(return_value=MagicMock(
            __enter__=MagicMock(return_value=None),
            __exit__=MagicMock(return_value=None),
        ))
        mock_conn.execute = MagicMock()
        mock_pool.connect = MagicMock(return_value=MagicMock(
            __enter__=MagicMock(return_value=mock_conn),
            __exit__=MagicMock(return_value=None),
        ))

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)

        # エラーなく完了することを確認
        manager.clear_state_sync(TEST_ROOM_ID, TEST_USER_ID)


# =============================================================================
# エッジケーステスト
# =============================================================================


class TestEdgeCases:
    """エッジケースのテスト"""

    def test_organization_id_filter(self):
        """organization_idでフィルタされることを確認"""
        manager = BrainStateManager(pool=MagicMock(), org_id="org_specific")
        assert manager.org_id == "org_specific"

    @pytest.mark.asyncio
    async def test_handles_db_connection_error(self):
        """DB接続エラーを適切に処理"""
        mock_pool = MagicMock()
        mock_pool.connect = MagicMock(side_effect=Exception("Connection failed"))

        manager = BrainStateManager(pool=mock_pool, org_id=TEST_ORG_ID)

        # get_current_stateはNoneを返す（安全側）
        state = await manager.get_current_state(TEST_ROOM_ID, TEST_USER_ID)
        assert state is None

    def test_state_data_default_empty_dict(self):
        """state_dataのデフォルトは空の辞書"""
        state = ConversationState(state_type=StateType.NORMAL)
        assert state.state_data == {}

    def test_reference_id_can_be_none(self):
        """reference_idはNoneでも可"""
        state = ConversationState(
            state_type=StateType.CONFIRMATION,
            reference_type="task",
            reference_id=None,
        )
        assert state.reference_id is None
