# tests/test_state_manager_coverage.py
"""
BrainStateManager / LLM State Manager - カバレッジ向上テスト

state_manager.py の未カバー行 (113, 140-141, 155-156, 162-174,
190-191, 201-207, 212-224, 228-231, 297-298, 443-445, 475-476,
574, 646, 684, 693, 699-741, 754-771, 794-795, 872-897, 986-988,
1023-1024, 1116-1117, 1164-1167, 1171-1178, 1247, 1271, 1278, 1332)
を対象とした補完テスト。
"""

import json
import uuid
import pytest
from datetime import datetime, timedelta
from unittest.mock import (
    AsyncMock,
    MagicMock,
    Mock,
    patch,
    PropertyMock,
)
from contextlib import contextmanager

from lib.brain.state_manager import (
    BrainStateManager,
    SafeJSONEncoder,
    _safe_json_dumps,
    LLMSessionMode,
    LLMSessionState,
    LLMPendingAction,
    LLMStateManager,
)
from lib.brain.models import ConversationState, StateType
from lib.brain.exceptions import StateError


# =============================================================================
# テスト用定数・ヘルパー
# =============================================================================

TEST_UUID_ORG_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_ROOM_ID = "room_cov"
TEST_USER_ID = "user_cov"


def _make_sync_pool():
    """同期プール用のモックを構築する。
    connect() がコンテキストマネージャーを返し、
    内部でSET/RESET (execute) とrollback/commit/invalidateが呼べる。
    """
    pool = MagicMock()
    conn = MagicMock()
    # result stub
    result = MagicMock()
    result.fetchone.return_value = None
    conn.execute.return_value = result
    conn.commit.return_value = None
    conn.rollback.return_value = None
    conn.invalidate.return_value = None

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=conn)
    ctx.__exit__ = MagicMock(return_value=False)
    pool.connect.return_value = ctx

    return pool, conn, result


def _make_mock_row(**overrides):
    """DBから返される行のモックを作成"""
    row = MagicMock()
    row.id = overrides.get("id", uuid.uuid4())
    row.organization_id = overrides.get("organization_id", TEST_UUID_ORG_ID)
    row.room_id = overrides.get("room_id", TEST_ROOM_ID)
    row.user_id = overrides.get("user_id", TEST_USER_ID)
    row.state_type = overrides.get("state_type", "goal_setting")
    row.state_step = overrides.get("state_step", "why")
    row.state_data = overrides.get("state_data", {})
    row.reference_type = overrides.get("reference_type", None)
    row.reference_id = overrides.get("reference_id", None)
    row.expires_at = overrides.get(
        "expires_at", datetime.now() + timedelta(minutes=30)
    )
    row.timeout_minutes = overrides.get("timeout_minutes", 30)
    row.created_at = overrides.get("created_at", datetime.now())
    row.updated_at = overrides.get("updated_at", datetime.now())
    return row


# =============================================================================
# Line 113: _check_uuid_format with empty org_id
# =============================================================================


class TestCheckUuidFormat:
    """_check_uuid_format の未カバー分岐テスト"""

    def test_empty_org_id_returns_false(self):
        """空文字列のorg_idはFalseを返す (line 113)"""
        pool, _, _ = _make_sync_pool()
        mgr = BrainStateManager(pool=pool, org_id="")
        assert mgr._org_id_is_uuid is False

    def test_none_like_empty_returns_false(self):
        """空の org_id を直接呼ぶ"""
        pool, _, _ = _make_sync_pool()
        mgr = BrainStateManager(pool=pool, org_id="not-a-uuid")
        assert mgr._check_uuid_format("") is False

    def test_valid_uuid_returns_true(self):
        """正しいUUIDはTrue"""
        pool, _, _ = _make_sync_pool()
        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        assert mgr._check_uuid_format(TEST_UUID_ORG_ID) is True


# =============================================================================
# Lines 140-141: sync _connect_with_org_context — initial rollback exception
# =============================================================================


class TestConnectWithOrgContextSync:
    """同期版 _connect_with_org_context の例外パス"""

    def test_initial_rollback_exception_is_ignored(self):
        """初期rollback が例外を投げても無視される (lines 140-141)"""
        pool, conn, result = _make_sync_pool()
        conn.rollback.side_effect = Exception("rollback failed")

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        # 正常に通過することを確認
        with mgr._connect_with_org_context() as c:
            assert c is conn

    def test_error_in_body_triggers_rollback_and_reraise(self):
        """ボディ内で例外が発生すると rollback→re-raise (lines 155-156)"""
        pool, conn, result = _make_sync_pool()
        # 2回目のrollback（エラー時）が失敗しても例外が上に飛ぶ
        call_count = 0
        original_rollback = conn.rollback.side_effect

        def side_effect_rollback():
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("rollback in error path failed")

        conn.rollback.side_effect = side_effect_rollback

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        with pytest.raises(ValueError, match="body error"):
            with mgr._connect_with_org_context() as c:
                raise ValueError("body error")

    def test_reset_failure_triggers_rollback_retry(self):
        """RESET失敗時にrollback+再試行 (lines 162-167)"""
        pool, conn, result = _make_sync_pool()

        execute_call_count = 0

        def execute_side_effect(*args, **kwargs):
            nonlocal execute_call_count
            execute_call_count += 1
            # 1st call: SET (ok), 2nd call: RESET (fail), 3rd call: RESET retry (ok)
            if execute_call_count == 2:
                raise Exception("RESET failed")
            return result

        conn.execute.side_effect = execute_side_effect

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        with mgr._connect_with_org_context() as c:
            pass  # normal exit

        # rollback が呼ばれた (finally retry path)
        assert conn.rollback.call_count >= 1

    def test_reset_retry_also_fails_invalidates_connection(self):
        """RESET再試行も失敗→接続無効化 (lines 168-174)"""
        pool, conn, result = _make_sync_pool()

        execute_call_count = 0

        def execute_side_effect(*args, **kwargs):
            nonlocal execute_call_count
            execute_call_count += 1
            if execute_call_count == 1:
                return result  # SET ok
            raise Exception("execute always fails")

        conn.execute.side_effect = execute_side_effect

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        with mgr._connect_with_org_context() as c:
            pass

        # invalidate が呼ばれた
        conn.invalidate.assert_called()

    def test_invalidate_itself_fails_silently(self):
        """invalidate自体のエラーも無視 (line 173-174)"""
        pool, conn, result = _make_sync_pool()

        execute_call_count = 0

        def execute_side_effect(*args, **kwargs):
            nonlocal execute_call_count
            execute_call_count += 1
            if execute_call_count == 1:
                return result
            raise Exception("always fail")

        conn.execute.side_effect = execute_side_effect
        conn.invalidate.side_effect = Exception("invalidate failed too")

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        # Should not raise
        with mgr._connect_with_org_context() as c:
            pass


# =============================================================================
# Lines 190-191, 201-207, 212-224: async _connect_with_org_context_async
# =============================================================================


class TestConnectWithOrgContextAsync:
    """非同期版 _connect_with_org_context_async の例外パス"""

    def _make_async_pool(self):
        """非同期プール用モック"""
        pool = MagicMock()
        pool.begin = AsyncMock()  # async pool として検出される

        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.rollback = AsyncMock()
        conn.invalidate = AsyncMock()

        # connect() が async context manager を返す
        async_ctx = AsyncMock()
        async_ctx.__aenter__ = AsyncMock(return_value=conn)
        async_ctx.__aexit__ = AsyncMock(return_value=False)
        pool.connect = MagicMock(return_value=async_ctx)

        return pool, conn

    @pytest.mark.asyncio
    async def test_initial_rollback_exception_ignored(self):
        """初期rollbackの例外は無視 (lines 190-191)"""
        pool, conn = self._make_async_pool()
        conn.rollback.side_effect = Exception("async rollback fail")

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        async with mgr._connect_with_org_context_async() as c:
            assert c is conn

    @pytest.mark.asyncio
    async def test_body_error_triggers_rollback_and_reraise(self):
        """ボディ内例外 → rollback → re-raise (lines 201-207)"""
        pool, conn = self._make_async_pool()
        conn.rollback.side_effect = Exception("rollback in error path failed")

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        with pytest.raises(RuntimeError, match="async body error"):
            async with mgr._connect_with_org_context_async() as c:
                raise RuntimeError("async body error")

    @pytest.mark.asyncio
    async def test_reset_failure_triggers_rollback_retry(self):
        """RESET失敗 → rollback + 再試行 (lines 212-217)"""
        pool, conn = self._make_async_pool()

        call_count = 0

        async def exec_side(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # RESET (first attempt)
                raise Exception("RESET fail")
            return MagicMock()

        conn.execute = AsyncMock(side_effect=exec_side)

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        async with mgr._connect_with_org_context_async() as c:
            pass

    @pytest.mark.asyncio
    async def test_reset_retry_fails_invalidates_connection(self):
        """RESET再試行失敗 → 接続無効化 (lines 218-224)"""
        pool, conn = self._make_async_pool()

        call_count = 0

        async def exec_side(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock()  # SET ok
            raise Exception("always fail")

        conn.execute = AsyncMock(side_effect=exec_side)

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        async with mgr._connect_with_org_context_async() as c:
            pass

        conn.invalidate.assert_called()

    @pytest.mark.asyncio
    async def test_invalidate_fails_silently_async(self):
        """invalidate自体の失敗も無視 (line 223-224)"""
        pool, conn = self._make_async_pool()

        call_count = 0

        async def exec_side(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock()
            raise Exception("always fail")

        conn.execute = AsyncMock(side_effect=exec_side)
        conn.invalidate.side_effect = Exception("invalidate failed too")

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        async with mgr._connect_with_org_context_async() as c:
            pass


# =============================================================================
# Lines 228-231: _execute_sync
# =============================================================================


class TestExecuteSync:
    """_execute_sync メソッドのテスト"""

    def test_execute_sync_returns_result(self):
        """_execute_sync がクエリを実行しcommitする (lines 228-231)"""
        pool, conn, result = _make_sync_pool()
        result.fetchone.return_value = MagicMock(count=5)

        from sqlalchemy import text

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        ret = mgr._execute_sync(text("SELECT 1"), {"a": "b"})
        # execute が呼ばれた（SET + query + RESET = 3回）
        assert conn.execute.call_count == 3
        conn.commit.assert_called()
        assert ret is result


# =============================================================================
# Lines 297-298: get_current_state — expired state auto-clear failure
# =============================================================================


class TestGetCurrentStateExpiredClearFails:
    """get_current_state の期限切れクリア失敗パス"""

    @pytest.mark.asyncio
    async def test_expired_state_clear_failure_returns_none(self):
        """期限切れ状態のクリアが失敗してもNoneを返す (lines 297-298)"""
        pool, conn, result = _make_sync_pool()

        expired_time = datetime.now() - timedelta(minutes=10)
        expired_time = expired_time.replace(tzinfo=None)
        row = _make_mock_row(expires_at=expired_time)
        result.fetchone.return_value = row

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)

        with patch.object(
            mgr, "_clear_state_sync", side_effect=Exception("clear failed")
        ):
            state = await mgr.get_current_state(TEST_ROOM_ID, TEST_USER_ID)
            assert state is None


# =============================================================================
# Lines 443-445: transition_to — exception → StateError
# =============================================================================


class TestTransitionToError:
    """transition_to の例外パス"""

    @pytest.mark.asyncio
    async def test_transition_to_raises_state_error_on_failure(self):
        """DBエラー時にStateErrorを発生 (lines 443-445)"""
        pool, conn, result = _make_sync_pool()
        # get_current_state をモックして None 返す
        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)

        with patch.object(mgr, "get_current_state", new_callable=AsyncMock, return_value=None):
            # connect のコンテキストマネージャー内でエラー
            conn.execute.side_effect = Exception("UPSERT failed")

            with pytest.raises(StateError):
                await mgr.transition_to(
                    room_id=TEST_ROOM_ID,
                    user_id=TEST_USER_ID,
                    state_type=StateType.GOAL_SETTING,
                    step="why",
                )

    @pytest.mark.asyncio
    async def test_transition_to_error_includes_old_state_type(self):
        """既存状態がある場合、エラーにcurrent_stateが含まれる"""
        pool, conn, result = _make_sync_pool()
        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)

        old_state = ConversationState(
            state_type=StateType.CONFIRMATION,
            state_step="waiting",
        )

        with patch.object(
            mgr, "get_current_state", new_callable=AsyncMock, return_value=old_state
        ):
            conn.execute.side_effect = Exception("UPSERT failed")

            with pytest.raises(StateError) as exc_info:
                await mgr.transition_to(
                    room_id=TEST_ROOM_ID,
                    user_id=TEST_USER_ID,
                    state_type=StateType.GOAL_SETTING,
                )

            assert "confirmation" in str(exc_info.value.details.get("current_state", ""))


# =============================================================================
# Lines 475-476: clear_state — exception logging
# =============================================================================


class TestClearStateError:
    """clear_state の例外パス"""

    @pytest.mark.asyncio
    async def test_clear_state_logs_error_on_failure(self):
        """_clear_state_sync が例外を投げても握り潰す (lines 475-476)"""
        pool, conn, result = _make_sync_pool()
        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)

        with patch.object(
            mgr, "_clear_state_sync", side_effect=Exception("clear boom")
        ):
            # 例外が外に出ないことを確認
            await mgr.clear_state(TEST_ROOM_ID, TEST_USER_ID, reason="test")


# =============================================================================
# Line 574: async update_step — no state → StateError (async path)
# Line 646: update_step — re-raise StateError
# =============================================================================


class TestUpdateStepAsyncErrors:
    """update_step (async path) の例外パス"""

    def _make_async_pool_for_update(self, row=None):
        """async update_step 用プール"""
        pool = MagicMock()
        pool.begin = AsyncMock()

        conn = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = row
        conn.execute = AsyncMock(return_value=result)
        conn.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        ))
        conn.rollback = AsyncMock()

        async_ctx = AsyncMock()
        async_ctx.__aenter__ = AsyncMock(return_value=conn)
        async_ctx.__aexit__ = AsyncMock(return_value=False)
        pool.connect = MagicMock(return_value=async_ctx)

        return pool, conn

    @pytest.mark.asyncio
    async def test_update_step_async_no_state_raises(self):
        """async path: 状態なし → StateError (line 574)"""
        pool, conn = self._make_async_pool_for_update(row=None)
        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)

        with pytest.raises(StateError, match="No active state"):
            await mgr.update_step(
                room_id=TEST_ROOM_ID,
                user_id=TEST_USER_ID,
                new_step="what",
            )

    @pytest.mark.asyncio
    async def test_update_step_reraises_state_error(self):
        """StateErrorはそのまま再送出 (line 646)"""
        pool, conn = self._make_async_pool_for_update(row=None)
        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)

        with pytest.raises(StateError):
            await mgr.update_step(
                room_id=TEST_ROOM_ID,
                user_id=TEST_USER_ID,
                new_step="what",
            )

    @pytest.mark.asyncio
    async def test_update_step_generic_error_wraps_in_state_error(self):
        """汎用例外はStateErrorにラップされる (line 648-653)"""
        pool, conn = self._make_async_pool_for_update(row=None)
        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)

        # execute 自体が RuntimeError を投げる
        conn.execute.side_effect = RuntimeError("unexpected DB error")

        with pytest.raises(StateError, match="Failed to update step"):
            await mgr.update_step(
                room_id=TEST_ROOM_ID,
                user_id=TEST_USER_ID,
                new_step="what",
            )


# =============================================================================
# Lines 684, 693, 699-741: _update_step_sync
# =============================================================================


class TestUpdateStepSync:
    """_update_step_sync のテスト (同期プール)"""

    def test_update_step_sync_no_state_raises(self):
        """状態なし → StateError (line 684)"""
        pool, conn, result = _make_sync_pool()
        result.fetchone.return_value = None

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)

        with pytest.raises(StateError, match="No active state"):
            mgr._update_step_sync(
                TEST_ROOM_ID, TEST_USER_ID, "what", None, datetime.utcnow()
            )

    def test_update_step_sync_merges_additional_data(self):
        """追加データがマージされる (line 693)"""
        pool, conn, result = _make_sync_pool()
        row = _make_mock_row(state_data={"existing": "val"})
        result.fetchone.return_value = row

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        state = mgr._update_step_sync(
            TEST_ROOM_ID,
            TEST_USER_ID,
            "what",
            {"new_key": "new_val"},
            datetime.utcnow(),
        )

        assert state.state_data["existing"] == "val"
        assert state.state_data["new_key"] == "new_val"

    def test_update_step_sync_returns_conversation_state(self):
        """正常パスでConversationStateを返す (lines 699-741)"""
        pool, conn, result = _make_sync_pool()
        row_id = uuid.uuid4()
        row = _make_mock_row(
            id=row_id,
            state_type="goal_setting",
            state_step="why",
            state_data={"retry": 0},
            reference_type="goal_session",
            reference_id=str(uuid.uuid4()),
        )
        result.fetchone.return_value = row

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        now = datetime.utcnow()
        state = mgr._update_step_sync(
            TEST_ROOM_ID, TEST_USER_ID, "what", None, now
        )

        assert isinstance(state, ConversationState)
        assert state.state_step == "what"
        assert state.state_type == StateType.GOAL_SETTING
        assert state.room_id == TEST_ROOM_ID
        assert state.user_id == TEST_USER_ID
        assert state.state_id == str(row_id)
        assert state.reference_type == "goal_session"
        # expires_at はtimeout_minutes分延長
        expected_expires = now + timedelta(minutes=row.timeout_minutes)
        assert abs((state.expires_at - expected_expires).total_seconds()) < 2

    def test_update_step_sync_no_additional_data(self):
        """additional_data=None でもstate_dataが維持される"""
        pool, conn, result = _make_sync_pool()
        row = _make_mock_row(state_data={"keep": "me"})
        result.fetchone.return_value = row

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        state = mgr._update_step_sync(
            TEST_ROOM_ID, TEST_USER_ID, "how", None, datetime.utcnow()
        )
        assert state.state_data["keep"] == "me"

    def test_update_step_sync_none_state_data_uses_empty(self):
        """row.state_data が None の場合は空dictを使う"""
        pool, conn, result = _make_sync_pool()
        row = _make_mock_row(state_data=None)
        result.fetchone.return_value = row

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        state = mgr._update_step_sync(
            TEST_ROOM_ID, TEST_USER_ID, "how", {"added": "data"}, datetime.utcnow()
        )
        assert state.state_data == {"added": "data"}

    def test_update_step_sync_reference_id_none_handling(self):
        """reference_id が None の場合"""
        pool, conn, result = _make_sync_pool()
        row = _make_mock_row(reference_id=None)
        result.fetchone.return_value = row

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        state = mgr._update_step_sync(
            TEST_ROOM_ID, TEST_USER_ID, "how", None, datetime.utcnow()
        )
        assert state.reference_id is None


# =============================================================================
# Lines 754-771: cleanup_expired_states (async)
# =============================================================================


class TestCleanupExpiredStates:
    """cleanup_expired_states のテスト"""

    @pytest.mark.asyncio
    async def test_cleanup_returns_count(self):
        """正常時にクリーンアップ件数を返す (lines 754-767)"""
        pool = MagicMock()
        pool.begin = AsyncMock()

        conn = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = MagicMock(__getitem__=lambda self, idx: 5)
        conn.execute = AsyncMock(return_value=result)
        conn.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        ))

        async_ctx = AsyncMock()
        async_ctx.__aenter__ = AsyncMock(return_value=conn)
        async_ctx.__aexit__ = AsyncMock(return_value=False)
        pool.connect = MagicMock(return_value=async_ctx)

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        count = await mgr.cleanup_expired_states()
        assert count == 5

    @pytest.mark.asyncio
    async def test_cleanup_returns_zero_on_no_results(self):
        """結果行なしの場合は0を返す"""
        pool = MagicMock()
        pool.begin = AsyncMock()

        conn = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = None
        conn.execute = AsyncMock(return_value=result)
        conn.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        ))

        async_ctx = AsyncMock()
        async_ctx.__aenter__ = AsyncMock(return_value=conn)
        async_ctx.__aexit__ = AsyncMock(return_value=False)
        pool.connect = MagicMock(return_value=async_ctx)

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        count = await mgr.cleanup_expired_states()
        assert count == 0

    @pytest.mark.asyncio
    async def test_cleanup_returns_zero_on_error(self):
        """例外時は0を返す (lines 769-771)"""
        pool = MagicMock()
        pool.begin = AsyncMock()
        pool.connect = MagicMock(side_effect=Exception("connection error"))

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        count = await mgr.cleanup_expired_states()
        assert count == 0

    @pytest.mark.asyncio
    async def test_cleanup_zero_count_no_log(self):
        """0件の場合はinfoログが出ない (line 764)"""
        pool = MagicMock()
        pool.begin = AsyncMock()

        conn = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = MagicMock(__getitem__=lambda self, idx: 0)
        conn.execute = AsyncMock(return_value=result)
        conn.begin = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        ))

        async_ctx = AsyncMock()
        async_ctx.__aenter__ = AsyncMock(return_value=conn)
        async_ctx.__aexit__ = AsyncMock(return_value=False)
        pool.connect = MagicMock(return_value=async_ctx)

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        count = await mgr.cleanup_expired_states()
        assert count == 0


# =============================================================================
# Lines 794-795: _record_history with from_state
# =============================================================================


class TestRecordHistory:
    """_record_history のfrom_state分岐テスト"""

    @pytest.mark.asyncio
    async def test_record_history_with_from_state_object(self):
        """from_stateオブジェクトが渡された場合 (lines 793-795)"""
        conn = AsyncMock()
        conn.execute = AsyncMock()

        from_state = ConversationState(
            state_type=StateType.GOAL_SETTING,
            state_step="why",
        )

        pool, _, _ = _make_sync_pool()
        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)

        await mgr._record_history(
            conn=conn,
            room_id=TEST_ROOM_ID,
            user_id=TEST_USER_ID,
            from_state=from_state,
            to_state_type=StateType.GOAL_SETTING,
            to_state_step="what",
            reason="user_action",
            state_id="some-id",
        )

        conn.execute.assert_called_once()
        call_params = conn.execute.call_args[0][1]
        assert call_params["from_type"] == "goal_setting"
        assert call_params["from_step"] == "why"


# =============================================================================
# Lines 872-897: get_current_state_sync — expired state path + normal return
# =============================================================================


class TestGetCurrentStateSyncCoverage:
    """get_current_state_sync の未カバーパス"""

    def test_sync_returns_state_when_not_expired(self):
        """有効な状態を返す (lines 878-893)"""
        pool, conn, result = _make_sync_pool()
        future_time = datetime.utcnow() + timedelta(hours=1)
        row = _make_mock_row(expires_at=future_time)
        result.fetchone.return_value = row

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        state = mgr.get_current_state_sync(TEST_ROOM_ID, TEST_USER_ID)

        assert state is not None
        assert isinstance(state, ConversationState)
        assert state.state_type == StateType.GOAL_SETTING
        assert state.state_step == "why"

    def test_sync_returns_none_when_expired(self):
        """期限切れ状態はNoneを返す (lines 872-876)"""
        pool, conn, result = _make_sync_pool()
        past_time = datetime.utcnow() - timedelta(minutes=10)
        row = _make_mock_row(expires_at=past_time)
        result.fetchone.return_value = row

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        state = mgr.get_current_state_sync(TEST_ROOM_ID, TEST_USER_ID)
        assert state is None

    def test_sync_returns_none_on_db_error(self):
        """DBエラー時はNoneを返す (lines 895-897)"""
        pool, conn, result = _make_sync_pool()
        conn.execute.side_effect = Exception("DB down")

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        state = mgr.get_current_state_sync(TEST_ROOM_ID, TEST_USER_ID)
        assert state is None

    def test_sync_state_reference_id_conversion(self):
        """reference_idの文字列変換"""
        pool, conn, result = _make_sync_pool()
        future = datetime.utcnow() + timedelta(hours=1)
        ref_uuid = uuid.uuid4()
        row = _make_mock_row(
            expires_at=future,
            reference_type="goal",
            reference_id=ref_uuid,
        )
        result.fetchone.return_value = row

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        state = mgr.get_current_state_sync(TEST_ROOM_ID, TEST_USER_ID)

        assert state.reference_id == str(ref_uuid)
        assert state.reference_type == "goal"


# =============================================================================
# Lines 986-988: transition_to_sync — error path → StateError
# =============================================================================


class TestTransitionToSyncError:
    """transition_to_sync の例外パス"""

    def test_transition_to_sync_raises_state_error(self):
        """DBエラー時にStateErrorを発生 (lines 986-988)"""
        pool, conn, result = _make_sync_pool()
        conn.execute.side_effect = Exception("sync UPSERT failed")

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)

        with pytest.raises(StateError, match="Failed to transition state"):
            mgr.transition_to_sync(
                room_id=TEST_ROOM_ID,
                user_id=TEST_USER_ID,
                state_type=StateType.GOAL_SETTING,
            )


# =============================================================================
# Lines 1023-1024: clear_state_sync — error path
# =============================================================================


class TestClearStateSyncError:
    """clear_state_sync の例外パス"""

    def test_clear_state_sync_logs_error(self):
        """例外を握り潰してログのみ (lines 1023-1024)"""
        pool, conn, result = _make_sync_pool()
        conn.execute.side_effect = Exception("delete failed")

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        # 例外が外に出ないことを確認
        mgr.clear_state_sync(TEST_ROOM_ID, TEST_USER_ID, reason="test")


# =============================================================================
# Lines 1116-1117: LLMPendingAction.to_string
# =============================================================================


class TestLLMPendingActionToString:
    """LLMPendingAction.to_string のテスト"""

    def test_to_string_format(self):
        """to_stringが期待するフォーマットを返す (lines 1116-1117)"""
        action = LLMPendingAction(
            action_id="act-001",
            tool_name="chatwork_task_create",
            parameters={"body": "テスト", "room_id": "123"},
            confirmation_question="タスクを作成しますか？",
            confirmation_type="low_confidence",
            original_message="タスク追加して",
            confidence=0.6,
        )
        s = action.to_string()
        assert "chatwork_task_create" in s
        assert "テスト" in s
        assert "タスクを作成しますか？" in s
        assert "タスク追加して" in s
        assert "60%" in s

    def test_to_string_with_empty_params(self):
        """空パラメータでも動作する"""
        action = LLMPendingAction(
            action_id="act-002",
            tool_name="simple_tool",
            parameters={},
            confirmation_question="proceed?",
            confirmation_type="danger",
            original_message="do it",
            confidence=0.95,
        )
        s = action.to_string()
        assert "simple_tool" in s
        assert "95%" in s


# =============================================================================
# Lines 1164-1167: LLMSessionState.is_expired
# =============================================================================


class TestLLMSessionStateIsExpired:
    """LLMSessionState.is_expired のテスト"""

    def test_is_expired_no_expires_at_new_session(self):
        """expires_at=None で30分以内 → 期限切れでない (line 1164-1166)"""
        session = LLMSessionState(
            session_id="s1",
            user_id="u1",
            room_id="r1",
            organization_id="o1",
            created_at=datetime.utcnow(),
        )
        assert session.is_expired() is False

    def test_is_expired_no_expires_at_old_session(self):
        """expires_at=None で30分超過 → 期限切れ (line 1164-1166)"""
        session = LLMSessionState(
            session_id="s1",
            user_id="u1",
            room_id="r1",
            organization_id="o1",
            created_at=datetime.utcnow() - timedelta(minutes=35),
        )
        assert session.is_expired() is True

    def test_is_expired_with_custom_expires_at_future(self):
        """カスタム expires_at 未来 → 期限切れでない (line 1167)"""
        session = LLMSessionState(
            session_id="s1",
            user_id="u1",
            room_id="r1",
            organization_id="o1",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        assert session.is_expired() is False

    def test_is_expired_with_custom_expires_at_past(self):
        """カスタム expires_at 過去 → 期限切れ (line 1167)"""
        session = LLMSessionState(
            session_id="s1",
            user_id="u1",
            room_id="r1",
            organization_id="o1",
            expires_at=datetime.utcnow() - timedelta(minutes=1),
        )
        assert session.is_expired() is True


# =============================================================================
# Lines 1171-1178: LLMSessionState.to_string
# =============================================================================


class TestLLMSessionStateToString:
    """LLMSessionState.to_string のテスト"""

    def test_to_string_normal_mode(self):
        """通常モードの文字列表現 (line 1171)"""
        session = LLMSessionState(
            session_id="s1",
            user_id="u1",
            room_id="r1",
            organization_id="o1",
        )
        s = session.to_string()
        assert "normal" in s

    def test_to_string_with_pending_action(self):
        """pending_actionがある場合 (line 1172-1173)"""
        action = LLMPendingAction(
            action_id="a1",
            tool_name="my_tool",
            parameters={},
            confirmation_question="?",
            confirmation_type="test",
            original_message="msg",
        )
        session = LLMSessionState(
            session_id="s1",
            user_id="u1",
            room_id="r1",
            organization_id="o1",
            mode=LLMSessionMode.CONFIRMATION_PENDING,
            pending_action=action,
        )
        s = session.to_string()
        assert "my_tool" in s

    def test_to_string_with_last_intent(self):
        """last_intentがある場合 (line 1174-1175)"""
        session = LLMSessionState(
            session_id="s1",
            user_id="u1",
            room_id="r1",
            organization_id="o1",
            last_intent="search_tasks",
        )
        s = session.to_string()
        assert "search_tasks" in s

    def test_to_string_with_last_error(self):
        """last_errorがある場合 (line 1176-1177)"""
        session = LLMSessionState(
            session_id="s1",
            user_id="u1",
            room_id="r1",
            organization_id="o1",
            last_error="DB connection timeout",
        )
        s = session.to_string()
        assert "DB connection timeout" in s

    def test_to_string_all_fields(self):
        """全フィールドが含まれる"""
        action = LLMPendingAction(
            action_id="a1",
            tool_name="tool_x",
            parameters={},
            confirmation_question="?",
            confirmation_type="t",
            original_message="m",
        )
        session = LLMSessionState(
            session_id="s1",
            user_id="u1",
            room_id="r1",
            organization_id="o1",
            mode=LLMSessionMode.CONFIRMATION_PENDING,
            pending_action=action,
            last_intent="create_task",
            last_error="something failed",
        )
        s = session.to_string()
        assert "confirmation_pending" in s
        assert "tool_x" in s
        assert "create_task" in s
        assert "something failed" in s


# =============================================================================
# Line 1247: LLMStateManager.get_current_state delegation
# =============================================================================


class TestLLMStateManagerGetCurrentState:
    """LLMStateManager.get_current_state のテスト"""

    @pytest.mark.asyncio
    async def test_delegates_to_brain_state_manager(self):
        """brain_state_manager.get_current_state に委譲 (line 1247)"""
        mock_bsm = MagicMock(spec=BrainStateManager)
        expected_state = ConversationState(
            state_type=StateType.CONFIRMATION,
            state_step="waiting",
        )
        mock_bsm.get_current_state = AsyncMock(return_value=expected_state)

        lsm = LLMStateManager(brain_state_manager=mock_bsm)
        result = await lsm.get_current_state("room_1", "user_1")

        assert result is expected_state
        mock_bsm.get_current_state.assert_called_once_with("room_1", "user_1")


# =============================================================================
# Lines 1271, 1278: get_llm_session — no llm_data / expired pending_action
# =============================================================================


class TestGetLLMSessionEdgeCases:
    """get_llm_session の未カバー分岐"""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_llm_session_in_data(self):
        """state_dataにllm_sessionがない場合はNone (line 1271)"""
        mock_bsm = MagicMock(spec=BrainStateManager)
        mock_state = MagicMock()
        mock_state.state_data = {"some_other_key": "value"}  # no llm_session
        mock_state.organization_id = "org_test"
        mock_bsm.get_current_state = AsyncMock(return_value=mock_state)

        lsm = LLMStateManager(brain_state_manager=mock_bsm)
        result = await lsm.get_llm_session("user_1", "room_1")
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_pending_action_becomes_none(self):
        """期限切れのpending_actionはNoneにクリアされる (line 1278)"""
        mock_bsm = MagicMock(spec=BrainStateManager)
        mock_state = MagicMock()
        mock_state.state_data = {
            "llm_session": {
                "session_id": "sess_001",
                "mode": "confirmation_pending",
                "pending_action": {
                    "action_id": "act_old",
                    "tool_name": "expired_tool",
                    "parameters": {},
                    "confirmation_question": "?",
                    "confirmation_type": "test",
                    "original_message": "old message",
                    # created_at 15 min ago, no expires_at → expired
                    "created_at": (datetime.utcnow() - timedelta(minutes=15)).isoformat(),
                },
                "conversation_context": {},
                "last_intent": None,
                "last_tool_called": None,
                "last_error": None,
                "error_count": 0,
            }
        }
        mock_state.organization_id = "org_test"
        mock_bsm.get_current_state = AsyncMock(return_value=mock_state)

        lsm = LLMStateManager(brain_state_manager=mock_bsm)
        result = await lsm.get_llm_session("user_1", "room_1")
        assert result is not None
        # pending_action は期限切れなので None
        assert result.pending_action is None

    @pytest.mark.asyncio
    async def test_valid_pending_action_preserved(self):
        """有効なpending_actionは保持される"""
        mock_bsm = MagicMock(spec=BrainStateManager)
        mock_state = MagicMock()
        mock_state.state_data = {
            "llm_session": {
                "session_id": "sess_002",
                "mode": "confirmation_pending",
                "pending_action": {
                    "action_id": "act_new",
                    "tool_name": "valid_tool",
                    "parameters": {"key": "val"},
                    "confirmation_question": "proceed?",
                    "confirmation_type": "low_confidence",
                    "original_message": "do something",
                    "created_at": datetime.utcnow().isoformat(),
                },
                "conversation_context": {},
                "last_intent": "create_task",
                "last_tool_called": None,
                "last_error": None,
                "error_count": 0,
            }
        }
        mock_state.organization_id = "org_test"
        mock_bsm.get_current_state = AsyncMock(return_value=mock_state)

        lsm = LLMStateManager(brain_state_manager=mock_bsm)
        result = await lsm.get_llm_session("user_1", "room_1")
        assert result is not None
        assert result.pending_action is not None
        assert result.pending_action.tool_name == "valid_tool"


# =============================================================================
# Line 1332: clear_pending_action — no session
# =============================================================================


class TestClearPendingActionNoSession:
    """clear_pending_action でセッションがない場合"""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_session(self):
        """セッションなし → None (line 1332)"""
        mock_bsm = MagicMock(spec=BrainStateManager)
        mock_bsm.get_current_state = AsyncMock(return_value=None)
        mock_bsm.org_id = "org_test"

        lsm = LLMStateManager(brain_state_manager=mock_bsm)
        result = await lsm.clear_pending_action("user_1", "room_1")
        assert result is None


# =============================================================================
# SafeJSONEncoder / _safe_json_dumps 追加テスト
# =============================================================================


class TestSafeJSONEncoder:
    """SafeJSONEncoder のテスト"""

    def test_safe_json_dumps_with_none(self):
        """None入力時は空dict JSON"""
        result = _safe_json_dumps(None)
        assert result == "{}"

    def test_safe_json_dumps_with_dict(self):
        """通常のdict"""
        result = _safe_json_dumps({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result

    def test_safe_json_dumps_ensure_ascii_false(self):
        """日本語がエスケープされない"""
        result = _safe_json_dumps({"msg": "日本語テスト"})
        assert "日本語テスト" in result

    def test_safe_json_encoder_default_delegates(self):
        """SafeJSONEncoderがtype_safety.safe_to_dictに委譲する"""
        encoder = SafeJSONEncoder()
        # datetime はtype_safetyでISO形式文字列になるはず
        with patch("lib.brain.state_manager.SafeJSONEncoder.default") as mock_default:
            mock_default.return_value = "mocked"
            result = json.dumps({"key": datetime.utcnow()}, cls=SafeJSONEncoder)
            # default was called
            mock_default.assert_called()


# =============================================================================
# update_step が同期プールの場合 _update_step_sync を呼ぶテスト
# =============================================================================


class TestUpdateStepDispatchToSync:
    """update_step が _is_async_pool=False の場合に
    _update_step_sync を呼ぶことを確認"""

    @pytest.mark.asyncio
    async def test_dispatches_to_sync_version(self):
        """同期プールの場合、_update_step_syncに委譲する"""
        pool, conn, result = _make_sync_pool()
        row = _make_mock_row()
        result.fetchone.return_value = row

        mgr = BrainStateManager(pool=pool, org_id=TEST_UUID_ORG_ID)
        assert mgr._is_async_pool is False

        with patch.object(mgr, "_update_step_sync") as mock_sync:
            expected = ConversationState(state_type=StateType.GOAL_SETTING)
            mock_sync.return_value = expected

            state = await mgr.update_step(
                room_id=TEST_ROOM_ID,
                user_id=TEST_USER_ID,
                new_step="what",
            )

            mock_sync.assert_called_once()
            assert state is expected


# =============================================================================
# LLMPendingAction.from_dict 補完テスト
# =============================================================================


class TestLLMPendingActionFromDict:
    """LLMPendingAction.from_dict のテスト"""

    def test_from_dict_minimal(self):
        """最小限のデータからの生成"""
        action = LLMPendingAction.from_dict({})
        assert action.tool_name == ""
        assert action.parameters == {}
        assert action.confirmation_type == "unknown"

    def test_from_dict_with_timestamps(self):
        """タイムスタンプ付きデータからの生成"""
        now = datetime.utcnow()
        expires = now + timedelta(minutes=10)
        data = {
            "action_id": "act-123",
            "tool_name": "my_tool",
            "parameters": {"p": 1},
            "confirmation_question": "ok?",
            "confirmation_type": "danger",
            "original_message": "do it",
            "original_reasoning": "because",
            "confidence": 0.85,
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
        }
        action = LLMPendingAction.from_dict(data)
        assert action.action_id == "act-123"
        assert action.tool_name == "my_tool"
        assert action.confidence == 0.85
        assert action.expires_at is not None
