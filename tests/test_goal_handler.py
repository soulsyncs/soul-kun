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


def create_mock_pool(dialogue_completed: bool = False, user_data: tuple = None):
    """モックプールを作成するヘルパー

    Args:
        dialogue_completed: Trueの場合、対話完了済みとして振る舞う
        user_data: ユーザーデータ (user_id, org_id, name) のタプル。
                   None の場合はユーザー未登録として振る舞う。

    Note:
        v10.40.0 で対話フロー必須化が導入されたため、
        _check_dialogue_completed が2つのクエリを実行する:
        1. users テーブルから organization_id を取得
        2. brain_conversation_states から対話完了を確認

        dialogue_completed=True の場合、両方のクエリに適切な応答を返す必要がある。
    """
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

    if dialogue_completed:
        # 対話完了済みの場合: _check_dialogue_completed が True を返すようモック
        # クエリ1: users テーブルから org_id 取得 → org_id を返す
        # クエリ2: brain_conversation_states から完了確認 → 行を返す（完了済み）
        # クエリ3以降: 登録処理のためのユーザーデータ取得
        mock_results = []

        # クエリ1: _check_dialogue_completed 内の users テーブル検索
        org_result = MagicMock()
        org_result.fetchone.return_value = ("org-uuid",)  # org_id のみ
        mock_results.append(org_result)

        # クエリ2: _check_dialogue_completed 内の brain_conversation_states 検索
        dialogue_result = MagicMock()
        dialogue_result.fetchone.return_value = MagicMock()  # 行が存在 = 完了済み
        mock_results.append(dialogue_result)

        # クエリ3以降: 登録処理のためのユーザーデータ取得
        if user_data:
            user_result = MagicMock()
            user_result.fetchone.return_value = user_data
            mock_results.append(user_result)
        else:
            # ユーザー未登録
            user_result = MagicMock()
            user_result.fetchone.return_value = None
            mock_results.append(user_result)

        mock_conn.execute.side_effect = mock_results
    else:
        # 対話未完了の場合: _check_dialogue_completed が False を返すようモック
        # クエリ1: users テーブル → None（ユーザー未登録）または org_id なし
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
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
        """具体的な目標だがユーザーが見つからない

        v10.40.0: 対話フロー必須化により、dialogue_completed=True が必要
        """
        # dialogue_completed=True, user_data=None でユーザー未登録をテスト
        mock_pool, mock_conn = create_mock_pool(dialogue_completed=True, user_data=None)

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
        """例外処理（対話完了確認時のDBエラー）

        v10.40.0: 対話完了確認時に例外が発生した場合、
        安全側に倒して対話未完了として扱い、対話フローへ誘導する。
        """
        def raise_error():
            raise Exception("DB接続エラー")

        handler = GoalHandler(get_pool=raise_error)
        params = {"goal_title": "テスト目標"}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        # DBエラー時は安全側に倒して対話フローへ誘導
        assert result["success"] is False
        assert "対話形式" in result["message"] or "目標設定したい" in result["message"]


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
    """目標タイトルと対話フロー必須化のテスト

    v10.40.0: 対話フロー必須化により、漠然/具体的に関わらず、
    対話が完了していなければ対話フローへ誘導される。
    """

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
        """漠然とした目標タイトルは対話フローへ誘導

        v10.40.0: 対話未完了の場合は対話フローへ誘導される。
        """
        mock_pool, _ = create_mock_pool(dialogue_completed=False)
        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"goal_title": title}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        # v10.40.0: 対話フロー必須化により対話開始を促す
        assert "対話形式" in result["message"] or "目標設定したい" in result["message"]

    @pytest.mark.parametrize("title", [
        "粗利300万円達成",
        "毎日日報を書く",
        "資格試験に合格する",
        "新規顧客10社獲得",
        "プロジェクト完了",
    ])
    def test_specific_goal_titles(self, title):
        """具体的な目標でも対話未完了なら対話フローへ誘導

        v10.40.0: 対話フロー必須化により、具体的な目標タイトルでも
        対話が完了していなければ対話フローへ誘導される。
        """
        mock_pool, _ = create_mock_pool(dialogue_completed=False)

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"goal_title": title}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        assert result["success"] is False
        # v10.40.0: 対話フロー必須化により対話開始を促す
        assert "対話形式" in result["message"] or "目標設定したい" in result["message"]

    @pytest.mark.parametrize("title", [
        "粗利300万円達成",
        "毎日日報を書く",
        "資格試験に合格する",
        "新規顧客10社獲得",
        "プロジェクト完了",
    ])
    def test_specific_goal_titles_with_dialogue_completed(self, title):
        """具体的な目標（対話完了済み）は登録処理に進む

        v10.40.0: 対話が完了していれば登録処理に進む。
        ユーザー未登録の場合はエラー。
        """
        # dialogue_completed=True, user_data=None でユーザー未登録をテスト
        mock_pool, _ = create_mock_pool(dialogue_completed=True, user_data=None)

        handler = GoalHandler(get_pool=lambda: mock_pool)
        params = {"goal_title": title}

        result = handler.handle_goal_registration(
            params, "room_123", "account_456", "テストユーザー"
        )

        # 対話完了済みなので登録処理に進む → ユーザー未登録でエラー
        assert result["success"] is False
        assert "登録されていない" in result["message"]


# =============================================================================
# v10.56.0: 目標削除・整理ハンドラーのテスト
# =============================================================================

def create_mock_pool_for_delete(goals_data=None, user_data=None):
    """削除・整理テスト用のモックプールを作成"""
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

    # デフォルトのユーザーデータ
    if user_data is None:
        user_data = ("user-uuid", "org-uuid", "テストユーザー")

    # 呼び出しごとの結果を設定
    mock_results = []

    # クエリ1: ユーザー情報取得
    user_result = MagicMock()
    user_result.fetchone.return_value = user_data
    mock_results.append(user_result)

    # クエリ2: 目標一覧取得
    goals_result = MagicMock()
    if goals_data:
        goals_result.fetchall.return_value = goals_data
    else:
        goals_result.fetchall.return_value = []
    mock_results.append(goals_result)

    mock_conn.execute.side_effect = mock_results

    return mock_pool, mock_conn


class TestGoalDeleteHandler:
    """handle_goal_delete のテスト"""

    def test_delete_shows_list_when_no_numbers(self):
        """番号未指定時は一覧を表示"""
        goals_data = [
            (str(uuid4()), "粗利300万円", 3000000, "円", date(2026, 1, 31)),
            (str(uuid4()), "新規顧客10件", 10, "件", date(2026, 1, 31)),
        ]
        mock_pool, _ = create_mock_pool_for_delete(goals_data=goals_data)

        handler = GoalHandler(get_pool=lambda: mock_pool)

        result = handler.handle_goal_delete(
            params={},
            room_id="room_123",
            account_id="account_456",
            sender_name="テストユーザー"
        )

        assert result["success"] is True
        assert "番号で教えて" in result["message"]
        assert "awaiting_input" in result

    def test_delete_requires_confirmation(self):
        """削除前に確認を求める"""
        goal_id = str(uuid4())
        goals_data = [
            (goal_id, "粗利300万円", 3000000, "円", date(2026, 1, 31)),
        ]
        mock_pool, _ = create_mock_pool_for_delete(goals_data=goals_data)

        handler = GoalHandler(get_pool=lambda: mock_pool)

        result = handler.handle_goal_delete(
            params={"goal_numbers": [1], "confirmed": False},
            room_id="room_123",
            account_id="account_456",
            sender_name="テストユーザー"
        )

        assert result["success"] is True
        assert "間違いない" in result["message"]
        assert "awaiting_confirmation" in result

    def test_delete_user_not_found(self):
        """ユーザー未登録時はエラー"""
        mock_pool, mock_conn = create_mock_pool_for_delete(user_data=None)
        # user_data=Noneの時の振る舞いを設定
        user_result = MagicMock()
        user_result.fetchone.return_value = None
        mock_conn.execute.side_effect = [user_result]

        handler = GoalHandler(get_pool=lambda: mock_pool)

        result = handler.handle_goal_delete(
            params={},
            room_id="room_123",
            account_id="account_456",
            sender_name="テストユーザー"
        )

        assert result["success"] is False

    def test_delete_exclude_numbers_pattern(self):
        """「X以外削除」パターンのテスト（v10.56.1）"""
        # 5件の目標を準備
        goals_data = [
            (str(uuid4()), "目標1", 100, "件", date(2026, 1, 31)),
            (str(uuid4()), "目標2", 200, "件", date(2026, 1, 31)),
            (str(uuid4()), "目標3", 300, "件", date(2026, 1, 31)),
            (str(uuid4()), "目標4", 400, "件", date(2026, 1, 31)),
            (str(uuid4()), "目標5", 500, "件", date(2026, 1, 31)),
        ]
        mock_pool, _ = create_mock_pool_for_delete(goals_data=goals_data)

        handler = GoalHandler(get_pool=lambda: mock_pool)

        # 「1,4,5以外削除」を original_message から解析
        result = handler.handle_goal_delete(
            params={},
            room_id="room_123",
            account_id="account_456",
            sender_name="テストユーザー",
            context={"original_message": "1,4,5以外削除して"}
        )

        assert result["success"] is True
        # 確認メッセージのフォーマットをチェック
        assert "1,4,5を残して" in result["message"]
        assert "2,3を削除" in result["message"]
        assert "実行していい？" in result["message"]
        # 削除対象が2,3であることを確認
        assert "目標2" in result["message"]
        assert "目標3" in result["message"]
        # 残す目標は削除対象に含まれない
        assert "削除対象" in result["message"]

    def test_delete_exclude_numbers_full_width(self):
        """「X以外削除」パターン（全角数字対応）"""
        goals_data = [
            (str(uuid4()), "目標1", 100, "件", date(2026, 1, 31)),
            (str(uuid4()), "目標2", 200, "件", date(2026, 1, 31)),
            (str(uuid4()), "目標3", 300, "件", date(2026, 1, 31)),
        ]
        mock_pool, _ = create_mock_pool_for_delete(goals_data=goals_data)

        handler = GoalHandler(get_pool=lambda: mock_pool)

        # 全角数字でのテスト
        result = handler.handle_goal_delete(
            params={},
            room_id="room_123",
            account_id="account_456",
            sender_name="テストユーザー",
            context={"original_message": "１以外を全部消して"}
        )

        assert result["success"] is True
        assert "1を残して" in result["message"]
        # 2,3が削除対象
        assert "2,3を削除" in result["message"]

    def test_delete_exclude_with_various_separators(self):
        """「X以外削除」パターン（様々な区切り文字）"""
        goals_data = [
            (str(uuid4()), "目標1", 100, "件", date(2026, 1, 31)),
            (str(uuid4()), "目標2", 200, "件", date(2026, 1, 31)),
            (str(uuid4()), "目標3", 300, "件", date(2026, 1, 31)),
            (str(uuid4()), "目標4", 400, "件", date(2026, 1, 31)),
        ]
        mock_pool, _ = create_mock_pool_for_delete(goals_data=goals_data)

        handler = GoalHandler(get_pool=lambda: mock_pool)

        # 中黒・読点での区切り
        result = handler.handle_goal_delete(
            params={},
            room_id="room_123",
            account_id="account_456",
            sender_name="テストユーザー",
            context={"original_message": "1・2以外削除"}
        )

        assert result["success"] is True
        assert "1,2を残して" in result["message"]


class TestGoalCleanupHandler:
    """handle_goal_cleanup のテスト"""

    def test_cleanup_user_not_found(self):
        """ユーザー未登録時はエラー"""
        mock_pool, mock_conn = create_mock_pool_for_delete(user_data=None)
        user_result = MagicMock()
        user_result.fetchone.return_value = None
        mock_conn.execute.side_effect = [user_result]

        handler = GoalHandler(get_pool=lambda: mock_pool)

        result = handler.handle_goal_cleanup(
            params={},
            room_id="room_123",
            account_id="account_456",
            sender_name="テストユーザー"
        )

        assert result["success"] is False

    def test_cleanup_no_org_id(self):
        """組織情報がない場合はエラー"""
        # org_idがNoneのユーザー
        mock_pool, mock_conn = create_mock_pool_for_delete(
            user_data=("user-uuid", None, "テストユーザー")
        )

        handler = GoalHandler(get_pool=lambda: mock_pool)

        result = handler.handle_goal_cleanup(
            params={},
            room_id="room_123",
            account_id="account_456",
            sender_name="テストユーザー"
        )

        assert result["success"] is False
        assert "組織情報" in result["message"]


class TestFormatNumberRange:
    """_format_number_range ヘルパーのテスト（v10.56.1）"""

    def test_single_number(self):
        """単一の番号"""
        handler = GoalHandler(get_pool=lambda: None)
        assert handler._format_number_range([5]) == "5"

    def test_non_consecutive_numbers(self):
        """連続しない番号"""
        handler = GoalHandler(get_pool=lambda: None)
        assert handler._format_number_range([1, 3, 5]) == "1,3,5"

    def test_consecutive_two_numbers(self):
        """2つの連続する番号（レンジ化しない）"""
        handler = GoalHandler(get_pool=lambda: None)
        assert handler._format_number_range([1, 2]) == "1,2"

    def test_consecutive_three_or_more(self):
        """3つ以上の連続する番号（レンジ化する）"""
        handler = GoalHandler(get_pool=lambda: None)
        assert handler._format_number_range([1, 2, 3]) == "1-3"

    def test_mixed_ranges_and_singles(self):
        """レンジと単独の混合"""
        handler = GoalHandler(get_pool=lambda: None)
        # [2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] -> "2,3,6-15"
        numbers = [2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
        assert handler._format_number_range(numbers) == "2,3,6-15"

    def test_unordered_input(self):
        """順不同の入力（ソートされる）"""
        handler = GoalHandler(get_pool=lambda: None)
        assert handler._format_number_range([5, 1, 3]) == "1,3,5"

    def test_empty_list(self):
        """空のリスト"""
        handler = GoalHandler(get_pool=lambda: None)
        assert handler._format_number_range([]) == ""


class TestNextActionInHandlers:
    """次の一手の提示テスト"""

    def test_progress_report_includes_next_action(self):
        """進捗報告後に次の一手が含まれる"""
        mock_pool, mock_conn = MagicMock(), MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        # ユーザーと目標のモック
        user_result = MagicMock()
        user_result.fetchone.return_value = ("user-uuid", "org-uuid", "テストユーザー")

        goal_result = MagicMock()
        goal_result.fetchone.return_value = (
            str(uuid4()), "粗利300万円", "numeric", 3000000, 1500000, "円", date(2026, 1, 31)
        )

        prev_result = MagicMock()
        prev_result.fetchone.return_value = (0,)

        mock_conn.execute.side_effect = [user_result, goal_result, prev_result, MagicMock(), MagicMock()]

        handler = GoalHandler(get_pool=lambda: mock_pool)

        result = handler.handle_goal_progress_report(
            params={"progress_value": 100000},
            room_id="room_123",
            account_id="account_456",
            sender_name="テストユーザー"
        )

        assert result["success"] is True
        assert "次の一手" in result["message"]
        assert "next_action" in result


class TestBrainContinueListContext:
    """_brain_continue_list_context ハンドラーのテスト（v10.56.2）"""

    @pytest.fixture(autouse=True)
    def setup_module_path(self):
        """テスト用のモジュールパスを設定"""
        # キャッシュをクリアしてフレッシュインポートを保証
        if 'handler_wrappers' in sys.modules:
            del sys.modules['handler_wrappers']
        if 'lib.brain.handler_wrappers' in sys.modules:
            del sys.modules['lib.brain.handler_wrappers']
        brain_path = os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook', 'lib', 'brain')
        if brain_path not in sys.path:
            sys.path.insert(0, brain_path)

    def test_expiration_check(self):
        """期限切れの場合はセッション完了"""
        import importlib
        handler_wrappers = importlib.import_module('handler_wrappers')
        _brain_continue_list_context = handler_wrappers._brain_continue_list_context

        # 過去の有効期限
        past_time = (datetime.utcnow() - timedelta(minutes=10)).isoformat()
        state_data = {
            "list_type": "goals",
            "action": "goal_delete",
            "step": "goal_delete_numbers",
            "expires_at": past_time,
        }

        result = _brain_continue_list_context(
            message="1,2,3",
            room_id="room_123",
            account_id="account_456",
            sender_name="テスト",
            state_data=state_data
        )

        assert result["session_completed"] is True
        assert "古くなった" in result["message"]

    def test_cancel_keywords(self):
        """キャンセルキーワードでセッション完了"""
        import importlib
        handler_wrappers = importlib.import_module('handler_wrappers')
        _brain_continue_list_context = handler_wrappers._brain_continue_list_context

        # 有効な期限
        future_time = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
        state_data = {
            "list_type": "goals",
            "action": "goal_delete",
            "step": "goal_delete_numbers",
            "expires_at": future_time,
        }

        for cancel_word in ["やめて", "キャンセル", "取り消し"]:
            result = _brain_continue_list_context(
                message=cancel_word,
                room_id="room_123",
                account_id="account_456",
                sender_name="テスト",
                state_data=state_data
            )

            assert result["session_completed"] is True
            assert "キャンセル" in result["message"]

    def test_no_main_module_error(self):
        """mainモジュールがない場合のエラーハンドリング"""
        import importlib
        # mainモジュールを一時的に削除
        original_main = sys.modules.get('main')
        if 'main' in sys.modules:
            del sys.modules['main']

        try:
            handler_wrappers = importlib.import_module('handler_wrappers')
            _brain_continue_list_context = handler_wrappers._brain_continue_list_context

            state_data = {
                "list_type": "goals",
                "action": "goal_delete",
                "step": "goal_delete_numbers",
                "expires_at": (datetime.utcnow() + timedelta(minutes=5)).isoformat(),
            }

            result = _brain_continue_list_context(
                message="1,2,3",
                room_id="room_123",
                account_id="account_456",
                sender_name="テスト",
                state_data=state_data
            )

            assert result["success"] is False
            assert "システムエラー" in result["message"]
        finally:
            # 元に戻す
            if original_main:
                sys.modules['main'] = original_main


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
