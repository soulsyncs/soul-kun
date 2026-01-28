"""
神経接続修理の回帰テスト（v10.40.1）

テスト対象:
1. 新規目標設定フローがbrain_conversation_statesに保存されること
2. セッション継続がbrain_conversation_statesから正しく動作すること
3. 対話ログがbrain_dialogue_logsに保存されること
4. 脳がgoal_setting_sessionsにフォールバックしないこと
5. コードベースに旧テーブル参照が残っていないこと

実行方法:
    pytest tests/test_neural_connection_repair.py -v
"""

import pytest
import sys
import os
import subprocess
from unittest.mock import MagicMock, patch
from uuid import uuid4

# libディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))


class TestGoalSettingUsesBrainConversationStates:
    """goal_setting.py が brain_conversation_states を使用することを確認"""

    @pytest.fixture
    def mock_conn(self):
        """モックDB接続"""
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        return conn

    @pytest.fixture
    def mock_pool(self, mock_conn):
        """モックDB接続プール"""
        pool = MagicMock()
        pool.connect.return_value.__enter__.return_value = mock_conn
        pool.connect.return_value.__exit__.return_value = None
        return pool

    def test_get_active_session_queries_brain_conversation_states(self, mock_pool, mock_conn):
        """
        _get_active_session() が brain_conversation_states を参照することを確認
        goal_setting_sessions は参照しない
        """
        from lib.goal_setting import GoalSettingDialogue

        dialogue = GoalSettingDialogue(mock_pool, "12345", "67890")
        dialogue.org_id = str(uuid4())
        dialogue.account_id = "67890"

        # セッション取得を試みる
        result = dialogue._get_active_session(mock_conn)

        # 実行されたSQLを確認
        executed_sql = mock_conn.execute.call_args[0][0].text
        assert "brain_conversation_states" in executed_sql
        assert "goal_setting_sessions" not in executed_sql
        assert "state_type = 'goal_setting'" in executed_sql

    def test_create_session_inserts_into_brain_conversation_states(self, mock_pool, mock_conn):
        """
        _create_session() が brain_conversation_states に INSERT することを確認
        goal_setting_sessions には INSERT しない
        """
        from lib.goal_setting import GoalSettingDialogue

        # RETURNING id のモック
        mock_conn.execute.return_value.fetchone.return_value = (uuid4(),)

        dialogue = GoalSettingDialogue(mock_pool, "12345", "67890")
        dialogue.org_id = str(uuid4())
        dialogue.account_id = "67890"

        # セッション作成
        session_id = dialogue._create_session(mock_conn)

        # 実行されたSQLを確認
        executed_sql = mock_conn.execute.call_args_list[0][0][0].text
        assert "brain_conversation_states" in executed_sql
        assert "goal_setting_sessions" not in executed_sql
        assert "state_type" in executed_sql
        assert session_id is not None

    def test_update_session_updates_brain_conversation_states(self, mock_pool, mock_conn):
        """
        _update_session() が brain_conversation_states を UPDATE することを確認
        """
        from lib.goal_setting import GoalSettingDialogue

        # 現在のstate_dataを返すモック
        mock_conn.execute.return_value.fetchone.return_value = ({},)

        dialogue = GoalSettingDialogue(mock_pool, "12345", "67890")
        dialogue.org_id = str(uuid4())

        session_id = str(uuid4())

        # セッション更新
        dialogue._update_session(
            mock_conn,
            session_id,
            current_step="what",
            why_answer="テスト回答"
        )

        # 実行されたSQLを確認（2回目のexecuteがUPDATE）
        executed_sql = mock_conn.execute.call_args_list[1][0][0].text
        assert "brain_conversation_states" in executed_sql
        assert "goal_setting_sessions" not in executed_sql


class TestDialogueLogsUseBrainDialogueLogs:
    """対話ログが brain_dialogue_logs に保存されることを確認"""

    @pytest.fixture
    def mock_conn(self):
        """モックDB接続"""
        conn = MagicMock()
        return conn

    def test_log_interaction_inserts_into_brain_dialogue_logs(self, mock_conn):
        """
        _log_interaction() が brain_dialogue_logs に INSERT することを確認
        goal_setting_logs には INSERT しない
        """
        from lib.goal_setting import GoalSettingDialogue

        dialogue = GoalSettingDialogue(None, "12345", "67890")
        dialogue.org_id = str(uuid4())
        dialogue.account_id = "67890"
        dialogue.room_id = "12345"

        session_id = str(uuid4())

        # ログ記録
        dialogue._log_interaction(
            mock_conn,
            session_id,
            step="why",
            user_message="テスト",
            ai_response="テスト応答"
        )

        # 実行されたSQLを確認
        executed_sql = mock_conn.execute.call_args[0][0].text
        assert "brain_dialogue_logs" in executed_sql
        assert "goal_setting_logs" not in executed_sql
        assert "chatwork_account_id" in executed_sql

    def test_get_step_attempt_count_queries_brain_dialogue_logs(self, mock_conn):
        """
        _get_step_attempt_count() が brain_dialogue_logs を参照することを確認
        """
        from lib.goal_setting import GoalSettingDialogue

        mock_conn.execute.return_value.fetchone.return_value = (3,)

        dialogue = GoalSettingDialogue(None, "12345", "67890")
        dialogue.org_id = str(uuid4())
        dialogue.account_id = "67890"
        dialogue.room_id = "12345"

        # カウント取得
        count = dialogue._get_step_attempt_count(mock_conn, str(uuid4()), "why")

        # 実行されたSQLを確認
        executed_sql = mock_conn.execute.call_args[0][0].text
        assert "brain_dialogue_logs" in executed_sql
        assert "goal_setting_logs" not in executed_sql
        assert count == 4  # 3 + 1


class TestHasActiveGoalSessionUsesBrainStates:
    """has_active_goal_session() が brain_conversation_states を使用することを確認"""

    def test_has_active_goal_session_queries_brain_conversation_states(self):
        """
        has_active_goal_session() が brain_conversation_states を参照することを確認
        """
        from lib.goal_setting import has_active_goal_session

        mock_conn = MagicMock()
        # users テーブルからの org_id 取得
        mock_conn.execute.return_value.fetchone.side_effect = [
            (str(uuid4()),),  # organization_id
            (0,),  # COUNT(*) from brain_conversation_states
        ]

        mock_pool = MagicMock()
        mock_pool.connect.return_value.__enter__.return_value = mock_conn
        mock_pool.connect.return_value.__exit__.return_value = None

        # チェック実行
        result = has_active_goal_session(mock_pool, "12345", "67890")

        # 2回目のexecuteがbrain_conversation_statesへのクエリ
        executed_sql = mock_conn.execute.call_args_list[1][0][0].text
        assert "brain_conversation_states" in executed_sql
        assert "goal_setting_sessions" not in executed_sql
        assert "state_type = 'goal_setting'" in executed_sql


class TestBrainCoreNoLongerUsesGoalSettingSessions:
    """脳のcore.pyがgoal_setting_sessionsを参照しないことを確認"""

    def test_get_current_state_does_not_check_goal_setting_sessions(self):
        """
        _get_current_state() が goal_setting_sessions をチェックしないことを確認
        _check_goal_setting_session メソッドが削除されていること
        """
        from lib.brain.core import SoulkunBrain

        # _check_goal_setting_session メソッドが存在しないことを確認
        assert not hasattr(SoulkunBrain, '_check_goal_setting_session'), \
            "_check_goal_setting_session method should be removed"


class TestNoOldTableReferencesInCode:
    """
    コードベースに旧テーブル（goal_setting_sessions, goal_setting_logs）への
    実行時参照が残っていないことを確認
    """

    def test_goal_setting_py_no_runtime_references_to_goal_setting_sessions(self):
        """
        goal_setting.py に goal_setting_sessions への実行時参照がないことを確認
        （docstring/コメントは除く）
        """
        result = subprocess.run(
            ['grep', '-n', 'goal_setting_sessions',
             'chatwork-webhook/lib/goal_setting.py'],
            capture_output=True,
            text=True,
            cwd=os.path.join(os.path.dirname(__file__), '..')
        )

        # マッチした行を確認
        for line in result.stdout.strip().split('\n'):
            if line:
                # docstring/コメント内の参照は許容
                assert '#' in line or '"""' in line or "'''" in line or \
                    '依存を削除' in line, \
                    f"Unexpected runtime reference to goal_setting_sessions: {line}"

    def test_goal_setting_py_no_runtime_references_to_goal_setting_logs(self):
        """
        goal_setting.py に goal_setting_logs への実行時参照がないことを確認
        """
        result = subprocess.run(
            ['grep', '-n', 'goal_setting_logs',
             'chatwork-webhook/lib/goal_setting.py'],
            capture_output=True,
            text=True,
            cwd=os.path.join(os.path.dirname(__file__), '..')
        )

        for line in result.stdout.strip().split('\n'):
            if line:
                assert '#' in line or '"""' in line or "'''" in line or \
                    '依存を削除' in line, \
                    f"Unexpected runtime reference to goal_setting_logs: {line}"

    def test_brain_core_no_runtime_references_to_goal_setting_sessions(self):
        """
        lib/brain/core.py に goal_setting_sessions への実行時参照がないことを確認
        """
        result = subprocess.run(
            ['grep', '-n', 'goal_setting_sessions',
             'lib/brain/core.py'],
            capture_output=True,
            text=True,
            cwd=os.path.join(os.path.dirname(__file__), '..')
        )

        for line in result.stdout.strip().split('\n'):
            if line:
                # コメント内の参照は許容
                assert '#' in line or '"""' in line or "'''" in line or \
                    'フォールバックを削除' in line or '参照しない' in line, \
                    f"Unexpected runtime reference to goal_setting_sessions in core.py: {line}"


class TestUseBrainArchitectureForcedInProduction:
    """本番環境でUSE_BRAIN_ARCHITECTUREがtrueに強制されることを確認"""

    def test_brain_architecture_forced_true_in_production(self):
        """
        本番環境でUSE_BRAIN_ARCHITECTURE=falseでも、trueに強制されることを確認
        """
        # 環境変数を直接設定してテスト
        original_env = os.environ.get("ENVIRONMENT")
        original_brain = os.environ.get("USE_BRAIN_ARCHITECTURE")

        try:
            os.environ["ENVIRONMENT"] = "production"
            os.environ["USE_BRAIN_ARCHITECTURE"] = "false"

            # シングルトンをリセットして新しいインスタンスを作成
            from lib.feature_flags import reset_flags, FeatureFlags
            reset_flags()

            # from_env() を使用して環境変数から読み込む
            flags = FeatureFlags.from_env()
            assert flags.use_brain_architecture is True, \
                f"Expected True but got {flags.use_brain_architecture}, brain_mode={flags.brain_mode}"
            assert flags.brain_mode == "true"
        finally:
            # 環境変数を復元
            if original_env is not None:
                os.environ["ENVIRONMENT"] = original_env
            elif "ENVIRONMENT" in os.environ:
                del os.environ["ENVIRONMENT"]

            if original_brain is not None:
                os.environ["USE_BRAIN_ARCHITECTURE"] = original_brain
            elif "USE_BRAIN_ARCHITECTURE" in os.environ:
                del os.environ["USE_BRAIN_ARCHITECTURE"]

            # シングルトンをリセット
            reset_flags()

    def test_brain_architecture_not_forced_in_development(self):
        """
        開発環境ではUSE_BRAIN_ARCHITECTURE=falseのままであることを確認
        """
        original_env = os.environ.get("ENVIRONMENT")
        original_brain = os.environ.get("USE_BRAIN_ARCHITECTURE")

        try:
            os.environ["ENVIRONMENT"] = "development"
            os.environ["USE_BRAIN_ARCHITECTURE"] = "false"

            from lib.feature_flags import reset_flags, FeatureFlags
            reset_flags()

            # from_env() を使用して環境変数から読み込む
            flags = FeatureFlags.from_env()
            assert flags.use_brain_architecture is False
            assert flags.brain_mode == "false"
        finally:
            if original_env is not None:
                os.environ["ENVIRONMENT"] = original_env
            elif "ENVIRONMENT" in os.environ:
                del os.environ["ENVIRONMENT"]

            if original_brain is not None:
                os.environ["USE_BRAIN_ARCHITECTURE"] = original_brain
            elif "USE_BRAIN_ARCHITECTURE" in os.environ:
                del os.environ["USE_BRAIN_ARCHITECTURE"]

            reset_flags()
