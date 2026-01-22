"""
lib/goal_notification.py のテスト

Phase 2.5 目標通知サービスのユニットテスト
"""

import pytest
from unittest.mock import patch, MagicMock, call
from datetime import date, datetime, timedelta
from decimal import Decimal

from lib.goal_notification import (
    GoalNotificationType,
    sanitize_error,
    build_daily_check_message,
    build_daily_reminder_message,
    build_morning_feedback_message,
    build_team_summary_message,
    send_daily_check_to_user,
    send_daily_reminder_to_user,
    send_morning_feedback_to_user,
    send_team_summary_to_leader,
    scheduled_daily_check,
    scheduled_daily_reminder,
    scheduled_morning_feedback,
)


class TestGoalNotificationType:
    """GoalNotificationType Enumのテスト"""

    def test_daily_check_value(self):
        """DAILY_CHECKの値"""
        assert GoalNotificationType.DAILY_CHECK.value == "goal_daily_check"

    def test_daily_reminder_value(self):
        """DAILY_REMINDERの値"""
        assert GoalNotificationType.DAILY_REMINDER.value == "goal_daily_reminder"

    def test_morning_feedback_value(self):
        """MORNING_FEEDBACKの値"""
        assert GoalNotificationType.MORNING_FEEDBACK.value == "goal_morning_feedback"

    def test_team_summary_value(self):
        """TEAM_SUMMARYの値"""
        assert GoalNotificationType.TEAM_SUMMARY.value == "goal_team_summary"


class TestSanitizeError:
    """sanitize_error のテスト"""

    def test_sanitize_file_path(self):
        """ファイルパスのサニタイズ"""
        error = Exception("/Users/kaz/soul-kun/lib/goal.py line 123: error")
        result = sanitize_error(error)
        assert "/Users/kaz" not in result
        assert "[PATH]" in result

    def test_sanitize_uuid(self):
        """UUIDのサニタイズ"""
        error = Exception("User 550e8400-e29b-41d4-a716-446655440000 not found")
        result = sanitize_error(error)
        assert "550e8400-e29b-41d4-a716-446655440000" not in result
        assert "[UUID]" in result

    def test_sanitize_email(self):
        """メールアドレスのサニタイズ"""
        error = Exception("User test@example.com exceeded rate limit")
        result = sanitize_error(error)
        assert "test@example.com" not in result
        assert "[EMAIL]" in result

    def test_sanitize_api_key(self):
        """APIキーのサニタイズ"""
        error = Exception("key=sk-abc123def456 is invalid")
        result = sanitize_error(error)
        assert "sk-abc123def456" not in result
        assert "[REDACTED]" in result

    def test_sanitize_ip_address(self):
        """IPアドレスのサニタイズ"""
        error = Exception("Connection to 192.168.1.100 failed")
        result = sanitize_error(error)
        assert "192.168.1.100" not in result
        assert "[IP]" in result

    def test_sanitize_truncates_long_messages(self):
        """長いメッセージの切り詰め"""
        long_message = "x" * 1000
        error = Exception(long_message)
        result = sanitize_error(error)
        assert len(result) <= 520  # 500 + "[TRUNCATED]"
        assert "[TRUNCATED]" in result

    def test_sanitize_preserves_safe_content(self):
        """安全なコンテンツは保持"""
        error = Exception("rate_limit")
        result = sanitize_error(error)
        assert result == "rate_limit"


class TestBuildDailyCheckMessage:
    """build_daily_check_message のテスト"""

    def test_basic_numeric_goal(self):
        """数値目標の基本メッセージ"""
        goals = [
            {
                "id": "goal_001",
                "title": "粗利目標",
                "goal_type": "numeric",
                "target_value": 3000000,
                "current_value": 1800000,
                "unit": "円",
            }
        ]
        message = build_daily_check_message("山田さん", goals)

        # 基本要素の確認
        assert "山田さん" in message
        assert "お疲れ様ウル🐺" in message
        assert "粗利目標" in message
        assert "300万" in message  # 目標値のフォーマット
        assert "180万" in message  # 現在値のフォーマット
        assert "60%" in message    # 達成率
        assert "今日の実績は" in message

    def test_deadline_goal(self):
        """期限目標のメッセージ"""
        goals = [
            {
                "id": "goal_002",
                "title": "プロジェクト完了",
                "goal_type": "deadline",
                "deadline": date(2026, 1, 31),
            }
        ]
        message = build_daily_check_message("鈴木さん", goals)

        assert "プロジェクト完了" in message
        assert "期限" in message
        assert "01/31" in message

    def test_action_goal(self):
        """行動目標のメッセージ"""
        goals = [
            {
                "id": "goal_003",
                "title": "毎日朝礼で発言",
                "goal_type": "action",
            }
        ]
        message = build_daily_check_message("田中さん", goals)

        assert "毎日朝礼で発言" in message
        assert "できたウル" in message

    def test_multiple_goals(self):
        """複数目標のメッセージ"""
        goals = [
            {
                "id": "goal_001",
                "title": "粗利目標",
                "goal_type": "numeric",
                "target_value": 3000000,
                "current_value": 1500000,
                "unit": "円",
            },
            {
                "id": "goal_002",
                "title": "獲得件数",
                "goal_type": "numeric",
                "target_value": 10,
                "current_value": 5,
                "unit": "件",
            },
        ]
        message = build_daily_check_message("佐藤さん", goals)

        assert "粗利目標" in message
        assert "獲得件数" in message
        assert "今日の選択" in message

    def test_includes_daily_choice_section(self):
        """「今日の選択」セクションが含まれる"""
        goals = [{"id": "g1", "title": "目標", "goal_type": "numeric", "target_value": 100, "current_value": 50, "unit": "件"}]
        message = build_daily_check_message("テストユーザー", goals)

        assert "今日の選択" in message
        assert "どんな行動を選んだウル" in message


class TestBuildDailyReminderMessage:
    """build_daily_reminder_message のテスト"""

    def test_basic_reminder_message(self):
        """基本リマインドメッセージ"""
        message = build_daily_reminder_message("山田さん")

        assert "山田さん" in message
        assert "まだ今日の振り返りができてないウル🐺" in message
        assert "17時に送った進捗確認" in message
        assert "1分だけ時間をもらえると嬉しいウル" in message

    def test_includes_encouragement(self):
        """励ましの言葉が含まれる"""
        message = build_daily_reminder_message("テストさん")

        assert "忙しい1日だったかもしれないけど" in message
        assert "明日の朝フィードバックするウル" in message


class TestBuildMorningFeedbackMessage:
    """build_morning_feedback_message のテスト"""

    def test_basic_feedback_message(self):
        """基本フィードバックメッセージ"""
        goals = [
            {
                "id": "goal_001",
                "title": "粗利目標",
                "goal_type": "numeric",
                "target_value": 3000000,
                "current_value": 1950000,
                "unit": "円",
            }
        ]
        progress_data = {
            "goal_001": {
                "value": 150000,
                "cumulative_value": 1950000,
                "daily_note": "新規契約を獲得",
                "daily_choice": "積極的に提案",
            }
        }
        message = build_morning_feedback_message("山田", goals, progress_data)

        assert "山田さん、おはようウル🐺" in message
        assert "昨日の振り返り" in message
        assert "+15万" in message  # 昨日の実績
        assert "195万" in message  # 月累計
        assert "65%" in message   # 達成率

    def test_includes_today_question(self):
        """「今日への問い」が含まれる"""
        goals = [
            {
                "id": "goal_001",
                "title": "粗利目標",
                "goal_type": "numeric",
                "target_value": 3000000,
                "current_value": 1950000,
                "unit": "円",
            }
        ]
        progress_data = {"goal_001": {"value": 150000}}
        message = build_morning_feedback_message("山田", goals, progress_data)

        assert "今日への問い" in message
        assert "あと" in message
        assert "ソウルシンクスの行動指針" in message

    def test_includes_encouragement(self):
        """励ましのメッセージが含まれる"""
        goals = [{"id": "g1", "title": "目標", "goal_type": "numeric", "target_value": 100, "current_value": 50, "unit": "件"}]
        message = build_morning_feedback_message("テスト", goals, {})

        assert "絶対できるって" in message
        assert "信じてるウル" in message

    def test_goal_achieved_message(self):
        """目標達成時のメッセージ"""
        goals = [
            {
                "id": "goal_001",
                "title": "粗利目標",
                "goal_type": "numeric",
                "target_value": 3000000,
                "current_value": 3500000,  # 目標超過
                "unit": "円",
            }
        ]
        progress_data = {"goal_001": {"value": 500000}}
        message = build_morning_feedback_message("山田", goals, progress_data)

        assert "おめでとう" in message or "次の挑戦" in message


class TestBuildTeamSummaryMessage:
    """build_team_summary_message のテスト"""

    def test_basic_team_summary(self, sample_team_members):
        """基本チームサマリーメッセージ"""
        message = build_team_summary_message(
            leader_name="佐藤リーダー",
            department_name="営業部",
            team_members=sample_team_members,
            summary_date=date(2026, 1, 22)
        )

        assert "佐藤リーダーさん、おはようウル🐺" in message
        assert "チーム進捗サマリー" in message
        assert "01/22" in message
        assert "山田太郎" in message
        assert "鈴木花子" in message
        assert "田中一郎" in message

    def test_includes_status_icons(self, sample_team_members):
        """ステータスアイコンが含まれる"""
        message = build_team_summary_message(
            leader_name="リーダー",
            department_name="部署",
            team_members=sample_team_members,
            summary_date=date.today()
        )

        # 達成率に応じたアイコン
        assert "📈" in message or "➡️" in message or "⚠️" in message

    def test_includes_team_total(self, sample_team_members):
        """チーム合計が含まれる"""
        message = build_team_summary_message(
            leader_name="リーダー",
            department_name="営業部",
            team_members=sample_team_members,
            summary_date=date.today()
        )

        assert "チーム合計" in message

    def test_includes_follow_up_points(self):
        """フォローポイントが含まれる（進捗遅れの場合）"""
        team_members = [
            {
                "user_id": "user_001",
                "user_name": "進捗遅れさん",
                "goals": [
                    {
                        "id": "goal_001",
                        "title": "粗利目標",
                        "goal_type": "numeric",
                        "target_value": 3000000,
                        "current_value": 900000,  # 30%
                        "unit": "円",
                    }
                ]
            }
        ]
        message = build_team_summary_message(
            leader_name="リーダー",
            department_name="営業部",
            team_members=team_members,
            summary_date=date.today()
        )

        assert "気になるポイント" in message
        assert "進捗遅れさん" in message
        assert "声かけを検討" in message


class TestSendDailyCheckToUser:
    """send_daily_check_to_user のテスト"""

    def test_sends_message_successfully(self, mock_goal_db_conn, mock_chatwork_send):
        """メッセージ送信成功"""
        # 既存の通知ログなし
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_goal_db_conn.execute.return_value = mock_result

        goals = [{"id": "g1", "title": "目標", "goal_type": "numeric", "target_value": 100, "current_value": 50, "unit": "件"}]

        status, error = send_daily_check_to_user(
            conn=mock_goal_db_conn,
            user_id="user_001",
            org_id="org_test",
            user_name="山田さん",
            chatwork_room_id="12345",
            goals=goals,
            send_message_func=mock_chatwork_send,
            dry_run=False,
        )

        assert status == "success"
        assert error is None

    def test_skips_if_already_sent(self, mock_goal_db_conn, mock_chatwork_send):
        """送信済みの場合はスキップ"""
        # 既存の成功ログあり
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("log_id", "success")
        mock_goal_db_conn.execute.return_value = mock_result

        goals = [{"id": "g1", "title": "目標", "goal_type": "numeric", "target_value": 100, "current_value": 50, "unit": "件"}]

        status, error = send_daily_check_to_user(
            conn=mock_goal_db_conn,
            user_id="user_001",
            org_id="org_test",
            user_name="山田さん",
            chatwork_room_id="12345",
            goals=goals,
            send_message_func=mock_chatwork_send,
            dry_run=False,
        )

        assert status == "skipped"
        assert error == "already_sent"

    def test_dry_run_mode(self, mock_goal_db_conn):
        """ドライランモードでは実際に送信しない"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_goal_db_conn.execute.return_value = mock_result

        send_called = []

        def mock_send(room_id, message):
            send_called.append(True)
            return True

        goals = [{"id": "g1", "title": "目標", "goal_type": "numeric", "target_value": 100, "current_value": 50, "unit": "件"}]

        status, error = send_daily_check_to_user(
            conn=mock_goal_db_conn,
            user_id="user_001",
            org_id="org_test",
            user_name="山田さん",
            chatwork_room_id="12345",
            goals=goals,
            send_message_func=mock_send,
            dry_run=True,
        )

        assert status == "skipped"
        assert error == "dry_run"
        assert len(send_called) == 0  # 送信関数は呼ばれない

    def test_handles_send_error(self, mock_goal_db_conn):
        """送信エラーのハンドリング"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_goal_db_conn.execute.return_value = mock_result

        def mock_send_error(room_id, message):
            raise Exception("Connection timeout")

        goals = [{"id": "g1", "title": "目標", "goal_type": "numeric", "target_value": 100, "current_value": 50, "unit": "件"}]

        status, error = send_daily_check_to_user(
            conn=mock_goal_db_conn,
            user_id="user_001",
            org_id="org_test",
            user_name="山田さん",
            chatwork_room_id="12345",
            goals=goals,
            send_message_func=mock_send_error,
            dry_run=False,
        )

        assert status == "failed"
        assert "timeout" in error.lower()


class TestSendDailyReminderToUser:
    """send_daily_reminder_to_user のテスト"""

    def test_sends_reminder_to_unanswered_user(self, mock_goal_db_conn, mock_chatwork_send):
        """未回答ユーザーへのリマインド送信"""
        # 通知ログなし、進捗なし
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_goal_db_conn.execute.return_value = mock_result

        status, error = send_daily_reminder_to_user(
            conn=mock_goal_db_conn,
            user_id="user_001",
            org_id="org_test",
            user_name="山田さん",
            chatwork_room_id="12345",
            send_message_func=mock_chatwork_send,
            dry_run=False,
        )

        assert status == "success"

    def test_skips_if_already_answered(self, mock_goal_db_conn, mock_chatwork_send):
        """回答済みの場合はスキップ"""
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                # 1回目: 通知ログチェック → なし
                mock_result.fetchone.return_value = None
            else:
                # 2回目: 進捗チェック → あり
                mock_result.fetchone.return_value = ("progress_id",)
            return mock_result

        mock_goal_db_conn.execute.side_effect = side_effect

        status, error = send_daily_reminder_to_user(
            conn=mock_goal_db_conn,
            user_id="user_001",
            org_id="org_test",
            user_name="山田さん",
            chatwork_room_id="12345",
            send_message_func=mock_chatwork_send,
            dry_run=False,
        )

        assert status == "skipped"
        assert error == "already_answered"


class TestSendMorningFeedbackToUser:
    """send_morning_feedback_to_user のテスト"""

    def test_sends_feedback_successfully(self, mock_goal_db_conn, mock_chatwork_send):
        """フィードバック送信成功"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_goal_db_conn.execute.return_value = mock_result

        goals = [{"id": "g1", "title": "目標", "goal_type": "numeric", "target_value": 100, "current_value": 80, "unit": "件"}]
        progress_data = {"g1": {"value": 10}}

        status, error = send_morning_feedback_to_user(
            conn=mock_goal_db_conn,
            user_id="user_001",
            org_id="org_test",
            user_name="山田さん",
            chatwork_room_id="12345",
            goals=goals,
            progress_data=progress_data,
            send_message_func=mock_chatwork_send,
            dry_run=False,
        )

        assert status == "success"


class TestSendTeamSummaryToLeader:
    """send_team_summary_to_leader のテスト"""

    def test_sends_summary_successfully(self, mock_goal_db_conn, mock_chatwork_send, sample_team_members):
        """サマリー送信成功"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_goal_db_conn.execute.return_value = mock_result

        status, error = send_team_summary_to_leader(
            conn=mock_goal_db_conn,
            recipient_id="leader_001",
            org_id="org_test",
            leader_name="佐藤リーダー",
            department_id="dept_001",
            department_name="営業部",
            chatwork_room_id="12345",
            team_members=sample_team_members,
            send_message_func=mock_chatwork_send,
            dry_run=False,
        )

        assert status == "success"

    def test_idempotency_by_recipient(self, mock_goal_db_conn, mock_chatwork_send, sample_team_members):
        """受信者単位での冪等性"""
        # 既に送信済み
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("log_id", "success")
        mock_goal_db_conn.execute.return_value = mock_result

        status, error = send_team_summary_to_leader(
            conn=mock_goal_db_conn,
            recipient_id="leader_001",
            org_id="org_test",
            leader_name="佐藤リーダー",
            department_id="dept_001",
            department_name="営業部",
            chatwork_room_id="12345",
            team_members=sample_team_members,
            send_message_func=mock_chatwork_send,
            dry_run=False,
        )

        assert status == "skipped"
        assert error == "already_sent"


class TestScheduledDailyCheck:
    """scheduled_daily_check のテスト"""

    def test_processes_all_users(self, mock_goal_db_conn, mock_chatwork_send):
        """全ユーザーを処理"""
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                # ユーザー一覧取得
                mock_result.fetchall.return_value = [
                    ("user_001", "山田太郎", "12345"),
                    ("user_002", "鈴木花子", "12346"),
                ]
            elif call_count[0] in [2, 5]:
                # 目標取得
                mock_result.fetchall.return_value = [
                    ("g1", "目標", "numeric", 100, 50, "件", None)
                ]
            else:
                # その他のクエリ
                mock_result.fetchone.return_value = None
            return mock_result

        mock_goal_db_conn.execute.side_effect = side_effect

        results = scheduled_daily_check(
            conn=mock_goal_db_conn,
            org_id="org_test",
            send_message_func=mock_chatwork_send,
            dry_run=True,  # ドライランでテスト
        )

        assert "success" in results or "skipped" in results


class TestScheduledDailyReminder:
    """scheduled_daily_reminder のテスト"""

    def test_processes_unanswered_users(self, mock_goal_db_conn, mock_chatwork_send):
        """未回答ユーザーを処理"""
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                # ユーザー一覧取得
                mock_result.fetchall.return_value = [
                    ("user_001", "山田太郎", "12345"),
                ]
            else:
                mock_result.fetchone.return_value = None
            return mock_result

        mock_goal_db_conn.execute.side_effect = side_effect

        results = scheduled_daily_reminder(
            conn=mock_goal_db_conn,
            org_id="org_test",
            send_message_func=mock_chatwork_send,
            dry_run=True,
        )

        assert "success" in results or "skipped" in results


class TestScheduledMorningFeedback:
    """scheduled_morning_feedback のテスト"""

    def test_sends_individual_feedback_and_team_summary(self, mock_goal_db_conn, mock_chatwork_send):
        """個人フィードバックとチームサマリーの両方を送信"""
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                # 進捗報告したユーザー一覧
                mock_result.fetchall.return_value = [
                    ("user_001", "山田太郎", "12345"),
                ]
            elif call_count[0] == 2:
                # 目標取得
                mock_result.fetchall.return_value = [
                    ("g1", "目標", "numeric", 100, 80, "件", None)
                ]
            elif call_count[0] == 3:
                # 進捗データ取得
                mock_result.fetchall.return_value = [
                    ("g1", 10, 80, "ノート", "選択")
                ]
            else:
                mock_result.fetchone.return_value = None
                mock_result.fetchall.return_value = []
            return mock_result

        mock_goal_db_conn.execute.side_effect = side_effect

        results = scheduled_morning_feedback(
            conn=mock_goal_db_conn,
            org_id="org_test",
            send_message_func=mock_chatwork_send,
            dry_run=True,
        )

        assert "success" in results or "skipped" in results


class TestCurrencyFormatting:
    """金額フォーマットのテスト"""

    def test_format_yen_to_man(self):
        """円を万単位でフォーマット"""
        goals = [
            {
                "id": "g1",
                "title": "粗利目標",
                "goal_type": "numeric",
                "target_value": 3000000,
                "current_value": 1500000,
                "unit": "円",
            }
        ]
        message = build_daily_check_message("テスト", goals)

        # 3000000円 → 300万
        assert "300万" in message
        # 1500000円 → 150万
        assert "150万" in message

    def test_format_small_amount(self):
        """少額のフォーマット（万円未満）"""
        goals = [
            {
                "id": "g1",
                "title": "経費削減",
                "goal_type": "numeric",
                "target_value": 5000,
                "current_value": 3000,
                "unit": "円",
            }
        ]
        message = build_daily_check_message("テスト", goals)

        # 5000円 → 5,000
        assert "5,000" in message or "5000" in message


class TestSoulkunCharacter:
    """ソウルくんキャラクターのテスト"""

    def test_uses_wolf_emoji(self):
        """オオカミ絵文字を使用"""
        message = build_daily_check_message("テスト", [{"id": "g1", "title": "目標", "goal_type": "action"}])
        assert "🐺" in message

    def test_uses_uru_suffix(self):
        """「ウル」語尾を使用"""
        message = build_daily_check_message("テスト", [{"id": "g1", "title": "目標", "goal_type": "action"}])
        assert "ウル" in message

    def test_encouraging_tone(self):
        """励ましのトーン"""
        goals = [{"id": "g1", "title": "目標", "goal_type": "numeric", "target_value": 100, "current_value": 50, "unit": "件"}]
        progress_data = {"g1": {"value": 10}}
        message = build_morning_feedback_message("テスト", goals, progress_data)

        # 励ましの表現が含まれる
        assert "信じてる" in message or "できる" in message

    def test_no_blame_language(self):
        """責める言葉を使わない"""
        message = build_daily_reminder_message("テスト")

        # 責める表現が含まれない
        assert "なぜ" not in message
        assert "ダメ" not in message
        assert "できなかった" not in message
