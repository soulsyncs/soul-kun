"""
目標達成支援ハンドラーのテスト

handlers/goal_handler.py の単体テスト
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))

from handlers.goal_handler import GoalHandler


def create_mock_pool(dialogue_completed: bool = False):
    """モックプールを作成するヘルパー

    Args:
        dialogue_completed: Trueの場合、対話完了済みとして振る舞う
    """
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

    # _check_dialogue_completed のDB応答をモック
    # dialogue_completed=False の場合、fetchone() は None を返す（対話未完了）
    mock_result = MagicMock()
    mock_result.fetchone.return_value = MagicMock() if dialogue_completed else None
    mock_conn.execute.return_value = mock_result

    return mock_pool, mock_conn


class TestGoalHandlerInit:
    """初期化のテスト"""

    def test_init_minimal(self):
        """最小限の初期化"""
        mock_pool = MagicMock()
        handler = GoalHandler(get_pool=mock_pool)

        assert handler.get_pool == mock_pool
        assert handler.process_goal_setting_message_func is None
        assert handler.use_goal_setting_lib is False

    def test_init_with_goal_setting_lib(self):
        """目標設定ライブラリ付きの初期化"""
        mock_pool = MagicMock()
        mock_process = MagicMock()

        handler = GoalHandler(
            get_pool=mock_pool,
            process_goal_setting_message_func=mock_process,
            use_goal_setting_lib=True
        )

        assert handler.get_pool == mock_pool
        assert handler.process_goal_setting_message_func == mock_process
        assert handler.use_goal_setting_lib is True


class TestHandleGoalRegistration:
    """目標登録ハンドラーのテスト"""

    def test_vague_goal_without_lib(self):
        """漠然とした目標タイトル（ライブラリなし）→ 対話フローへ誘導"""
        mock_pool, _ = create_mock_pool(dialogue_completed=False)
        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"goal_title": "目標を設定したい"}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        # 対話フロー未完了の場合は対話開始を促す
        assert result["success"] is False
        assert "対話形式" in result["message"] or "目標設定したい" in result["message"]

    def test_vague_goal_with_lib(self):
        """漠然とした目標タイトル（ライブラリあり）"""
        mock_pool, _ = create_mock_pool()
        mock_process = MagicMock(return_value={"success": True, "message": "対話開始"})
        handler = GoalHandler(
            get_pool=lambda: mock_pool,
            process_goal_setting_message_func=mock_process,
            use_goal_setting_lib=True
        )
        params = {"goal_title": "目標設定"}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー",
            context={"original_message": "目標を設定したい"}
        )

        assert result["success"] is True
        mock_process.assert_called_once()

    def test_empty_goal_title(self):
        """空の目標タイトル"""
        mock_pool, _ = create_mock_pool()
        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"goal_title": ""}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False

    def test_short_goal_title(self):
        """極端に短い目標タイトル"""
        mock_pool, _ = create_mock_pool()
        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"goal_title": "ab"}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False

    def test_specific_goal_user_not_found(self):
        """具体的な目標だがユーザーが見つからない"""
        mock_pool, mock_conn = create_mock_pool()

        # fetchoneがNoneを返す（ユーザー未登録）
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"goal_title": "粗利300万円達成する"}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        assert "登録されていない" in result["message"]

    def test_specific_goal_no_organization(self):
        """具体的な目標だがorganization_idがNULL"""
        mock_pool, mock_conn = create_mock_pool()

        # ユーザーはいるがorg_idがNone
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("user-uuid", None, "テストユーザー")
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"goal_title": "粗利300万円達成する"}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        assert "組織情報が設定されていない" in result["message"]

    def test_specific_goal_success(self):
        """具体的な目標の登録成功"""
        mock_pool, mock_conn = create_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {
            "goal_title": "粗利300万円達成する",
            "goal_type": "numeric",
            "target_value": 3000000,
            "unit": "円"
        }

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "目標を登録した" in result["message"]
        assert "粗利300万円達成する" in result["message"]

    def test_deadline_goal_success(self):
        """期限型目標の登録成功"""
        mock_pool, mock_conn = create_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {
            "goal_title": "資格取得",
            "goal_type": "deadline",
            "deadline": "2026-03-31"
        }

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "期限:" in result["message"]

    def test_action_goal_success(self):
        """行動型目標の登録成功"""
        mock_pool, mock_conn = create_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {
            "goal_title": "毎日日報を書く",
            "goal_type": "action"
        }

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "行動目標" in result["message"]

    def test_weekly_period(self):
        """週間期間の計算"""
        mock_pool, mock_conn = create_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {
            "goal_title": "週次目標",
            "period_type": "weekly"
        }

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True

    def test_quarterly_period(self):
        """四半期期間の計算"""
        mock_pool, mock_conn = create_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {
            "goal_title": "四半期目標",
            "period_type": "quarterly"
        }

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True

    def test_yearly_period(self):
        """年間期間の計算"""
        mock_pool, mock_conn = create_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {
            "goal_title": "年間目標",
            "period_type": "yearly"
        }

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True

    def test_exception_handling(self):
        """例外処理"""
        def raise_error():
            raise Exception("DB接続エラー")

        handler = GoalHandler(get_pool=raise_error)
        params = {"goal_title": "テスト目標"}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        assert "失敗した" in result["message"]


class TestHandleGoalProgressReport:
    """目標進捗報告ハンドラーのテスト"""

    def test_user_not_found(self):
        """ユーザーが見つからない"""
        mock_pool, mock_conn = create_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"progress_value": 100000}

        result = handler.handle_goal_progress_report(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        assert "目標を登録していない" in result["message"]

    def test_no_organization(self):
        """organization_idがNULL"""
        mock_pool, mock_conn = create_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("user-uuid", None, "テストユーザー")
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"progress_value": 100000}

        result = handler.handle_goal_progress_report(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        assert "組織情報が設定されていない" in result["message"]

    def test_no_active_goal(self):
        """アクティブな目標がない"""
        mock_pool, mock_conn = create_mock_pool()

        # 複数回のexecute呼び出しに対応
        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # 1回目: ユーザー情報
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            else:
                # 2回目: 目標検索（空）
                result.fetchone.return_value = None
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"progress_value": 100000}

        result = handler.handle_goal_progress_report(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is False
        assert "アクティブな目標が見つからない" in result["message"]

    def test_numeric_progress_success(self):
        """数値型目標の進捗報告成功"""
        mock_pool, mock_conn = create_mock_pool()

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # ユーザー情報
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            elif call_count[0] == 2:
                # 目標情報
                result.fetchone.return_value = (
                    "goal-uuid", "粗利300万", "numeric",
                    Decimal("3000000"), Decimal("0"), "円",
                    date.today()
                )
            elif call_count[0] == 3:
                # 前回累計
                result.fetchone.return_value = (Decimal("500000"),)
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"progress_value": 100000}

        result = handler.handle_goal_progress_report(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "進捗を記録した" in result["message"]
        assert "今日の実績" in result["message"]

    def test_goal_achieved(self):
        """目標達成の場合"""
        mock_pool, mock_conn = create_mock_pool()

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            elif call_count[0] == 2:
                result.fetchone.return_value = (
                    "goal-uuid", "粗利300万", "numeric",
                    Decimal("3000000"), Decimal("0"), "円",
                    date.today()
                )
            elif call_count[0] == 3:
                result.fetchone.return_value = (Decimal("2900000"),)
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"progress_value": 200000}  # これで300万超え

        result = handler.handle_goal_progress_report(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "目標達成おめでとう" in result["message"]

    def test_near_achievement(self):
        """目標達成まであと少し（80%以上）"""
        mock_pool, mock_conn = create_mock_pool()

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            elif call_count[0] == 2:
                result.fetchone.return_value = (
                    "goal-uuid", "粗利300万", "numeric",
                    Decimal("3000000"), Decimal("0"), "円",
                    date.today()
                )
            elif call_count[0] == 3:
                result.fetchone.return_value = (Decimal("2300000"),)
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"progress_value": 100000}  # 80%

        result = handler.handle_goal_progress_report(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "もう少し" in result["message"]

    def test_halfway_progress(self):
        """半分超えた場合"""
        mock_pool, mock_conn = create_mock_pool()

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            elif call_count[0] == 2:
                result.fetchone.return_value = (
                    "goal-uuid", "粗利300万", "numeric",
                    Decimal("3000000"), Decimal("0"), "円",
                    date.today()
                )
            elif call_count[0] == 3:
                result.fetchone.return_value = (Decimal("1400000"),)
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"progress_value": 200000}  # 53%

        result = handler.handle_goal_progress_report(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "半分超えた" in result["message"]

    def test_action_goal_with_note(self):
        """行動型目標の進捗報告（ノート付き）"""
        mock_pool, mock_conn = create_mock_pool()

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            elif call_count[0] == 2:
                result.fetchone.return_value = (
                    "goal-uuid", "毎日日報", "action",
                    None, None, "",
                    date.today()
                )
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"daily_note": "今日も頑張った"}

        result = handler.handle_goal_progress_report(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "今日も頑張った" in result["message"]

    def test_exception_handling(self):
        """例外処理"""
        def raise_error():
            raise Exception("DB接続エラー")

        handler = GoalHandler(get_pool=raise_error)
        params = {"progress_value": 100000}

        result = handler.handle_goal_progress_report(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        assert "失敗した" in result["message"]


class TestHandleGoalStatusCheck:
    """目標確認ハンドラーのテスト"""

    def test_user_not_found(self):
        """ユーザーが見つからない"""
        mock_pool, mock_conn = create_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {}

        result = handler.handle_goal_status_check(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        assert "目標を登録していない" in result["message"]

    def test_no_organization(self):
        """organization_idがNULL"""
        mock_pool, mock_conn = create_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("user-uuid", None, "テストユーザー")
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {}

        result = handler.handle_goal_status_check(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        assert "組織情報が設定されていない" in result["message"]

    def test_no_active_goals(self):
        """アクティブな目標がない"""
        mock_pool, mock_conn = create_mock_pool()

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            result.fetchall.return_value = []
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {}

        result = handler.handle_goal_status_check(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is False
        assert "まだ目標を登録していない" in result["message"]

    def test_single_numeric_goal(self):
        """数値型目標の確認"""
        mock_pool, mock_conn = create_mock_pool()

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            result.fetchall.return_value = [
                (
                    "goal-uuid", "粗利300万", "numeric",
                    Decimal("3000000"), Decimal("1500000"), "円",
                    date.today(), date.today() + timedelta(days=30), "active"
                )
            ]
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {}

        result = handler.handle_goal_status_check(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "粗利300万" in result["message"]
        assert "達成率" in result["message"]
        assert "50.0%" in result["message"]

    def test_deadline_goal_remaining_days(self):
        """期限型目標（残り日数あり）"""
        mock_pool, mock_conn = create_mock_pool()

        future_date = date.today() + timedelta(days=10)

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            result.fetchall.return_value = [
                (
                    "goal-uuid", "資格取得", "deadline",
                    None, None, "",
                    date.today(), future_date, "active"
                )
            ]
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {}

        result = handler.handle_goal_status_check(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "あと10日" in result["message"]

    def test_deadline_goal_today(self):
        """期限型目標（今日まで）"""
        mock_pool, mock_conn = create_mock_pool()

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            result.fetchall.return_value = [
                (
                    "goal-uuid", "資格取得", "deadline",
                    None, None, "",
                    date.today(), date.today(), "active"
                )
            ]
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {}

        result = handler.handle_goal_status_check(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "今日まで" in result["message"]

    def test_deadline_goal_overdue(self):
        """期限型目標（期限切れ）"""
        mock_pool, mock_conn = create_mock_pool()

        past_date = date.today() - timedelta(days=5)

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            result.fetchall.return_value = [
                (
                    "goal-uuid", "資格取得", "deadline",
                    None, None, "",
                    date.today() - timedelta(days=30), past_date, "active"
                )
            ]
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {}

        result = handler.handle_goal_status_check(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "期限切れ" in result["message"]

    def test_action_goal(self):
        """行動型目標の確認"""
        mock_pool, mock_conn = create_mock_pool()

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            result.fetchall.return_value = [
                (
                    "goal-uuid", "毎日日報を書く", "action",
                    None, None, "",
                    date.today(), date.today() + timedelta(days=30), "active"
                )
            ]
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {}

        result = handler.handle_goal_status_check(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "毎日日報を書く" in result["message"]
        assert "期間:" in result["message"]

    def test_multiple_goals(self):
        """複数目標の確認"""
        mock_pool, mock_conn = create_mock_pool()

        call_count = [0]
        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.fetchone.return_value = ("user-uuid", "org-uuid", "田中太郎")
            result.fetchall.return_value = [
                (
                    "goal-uuid-1", "粗利300万", "numeric",
                    Decimal("3000000"), Decimal("1500000"), "円",
                    date.today(), date.today() + timedelta(days=30), "active"
                ),
                (
                    "goal-uuid-2", "毎日日報を書く", "action",
                    None, None, "",
                    date.today(), date.today() + timedelta(days=30), "active"
                ),
            ]
            return result

        mock_conn.execute.side_effect = mock_execute

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {}

        result = handler.handle_goal_status_check(
            params, "room_123", "account_456", "田中太郎"
        )

        assert result["success"] is True
        assert "【目標1】" in result["message"]
        assert "【目標2】" in result["message"]
        assert "2個の目標を追いかけてる" in result["message"]

    def test_exception_handling(self):
        """例外処理"""
        def raise_error():
            raise Exception("DB接続エラー")

        handler = GoalHandler(get_pool=raise_error)
        params = {}

        result = handler.handle_goal_status_check(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        assert "失敗した" in result["message"]


class TestVagueGoalDetection:
    """漠然とした目標タイトル検出のテスト"""

    @pytest.mark.parametrize("title", [
        "目標を設定したい",
        "目標を登録したい",
        "目標設定",
        "KPI設定",
        "新規目標の設定",
        "新規目標",
        "目標の設定",
        "目標登録",
        "今月の目標",
        "個人目標",
        "目標を立てたい",
        "目標を決めたい",
        "未定（相談中）",
        "未定",
        "相談中",
        "目標相談",
        "目標の相談",
        "目標について相談",
        "検討中",
        "未定義",
    ])
    def test_vague_goal_titles(self, title):
        """漠然とした目標タイトルのリスト"""
        mock_pool, _ = create_mock_pool()
        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"goal_title": title}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        assert "目標の内容を教えて" in result["message"]

    @pytest.mark.parametrize("title", [
        "粗利300万円達成",
        "毎日日報を書く",
        "資格試験に合格する",
        "新規顧客10社獲得",
        "プロジェクト完了",
    ])
    def test_specific_goal_titles(self, title):
        """具体的な目標タイトルは対話に入らない（ユーザー未登録でエラー）"""
        mock_pool, mock_conn = create_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None  # ユーザー未登録
        mock_conn.execute.return_value = mock_result

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"goal_title": title}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        # 具体的な目標は登録処理に進む（ユーザー未登録でエラー）
        assert "登録されていない" in result["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
