"""
遅延管理ハンドラーのテスト

chatwork-webhook/handlers/overdue_handler.py のテスト
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import sys
import os

# chatwork-webhookのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))

from handlers.overdue_handler import OverdueHandler, JST


class TestOverdueHandlerInit:
    """OverdueHandlerの初期化テスト"""

    def test_init_minimal(self):
        """最小限のパラメータで初期化できること"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock()
        )
        assert handler.get_pool is not None
        assert handler.get_secret is not None
        assert handler.get_direct_room is not None
        assert handler.admin_room_id is None
        assert handler.escalation_days == 3

    def test_init_full(self):
        """全パラメータで初期化できること"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock(),
            get_overdue_days_func=MagicMock(return_value=5),
            admin_room_id="123456",
            escalation_days=5
        )
        assert handler.admin_room_id == "123456"
        assert handler.escalation_days == 5


class TestGetOverdueDays:
    """get_overdue_days関数のテスト"""

    def test_with_custom_func(self):
        """カスタム関数が設定されている場合はそれを使用"""
        mock_func = MagicMock(return_value=10)
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock(),
            get_overdue_days_func=mock_func
        )

        result = handler.get_overdue_days(1704067200)

        assert result == 10
        mock_func.assert_called_once_with(1704067200)

    def test_fallback_none(self):
        """limit_timeがNoneの場合は0を返す"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock()
        )

        result = handler.get_overdue_days(None)

        assert result == 0

    def test_fallback_valid_timestamp(self):
        """有効なタイムスタンプの場合は超過日数を計算"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock()
        )

        # 7日前のタイムスタンプを作成
        seven_days_ago = datetime.now(JST) - timedelta(days=7)
        timestamp = int(seven_days_ago.timestamp())

        result = handler.get_overdue_days(timestamp)

        # 7日前なので7日超過
        assert result >= 6 and result <= 8  # 時差による誤差を許容


class TestEnsureOverdueTables:
    """ensure_overdue_tables関数のテスト"""

    def test_create_tables(self):
        """テーブル作成が実行されること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler = OverdueHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            get_direct_room=MagicMock()
        )

        handler.ensure_overdue_tables()

        # executeが複数回呼ばれることを確認（テーブル・インデックス作成）
        assert mock_conn.execute.call_count >= 4


class TestProcessOverdueTasks:
    """process_overdue_tasks関数のテスト"""

    def test_no_overdue_tasks(self):
        """期限超過タスクがない場合"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        handler = OverdueHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            get_direct_room=MagicMock()
        )

        # エラーが発生しないことを確認
        handler.process_overdue_tasks()

    def test_with_overdue_tasks(self):
        """期限超過タスクがある場合（エラーなく処理が完了すること）"""
        mock_pool = MagicMock()

        # begin用のモック（テーブル作成用）
        mock_begin_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_begin_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        # connect用のモック（タスク取得用）
        mock_connect_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_connect_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        # 遅延タスク取得結果（1件あり）
        overdue_result = MagicMock()
        overdue_result.fetchall.return_value = [
            ("task1", "room1", "acc1", "acc2", "タスク1", 1704067200, "担当者A", "依頼者B")
        ]

        # 督促履歴確認結果（未督促）
        reminder_result = MagicMock()
        reminder_result.fetchall.return_value = []

        # connect().execute()の結果を設定
        mock_connect_conn.execute.side_effect = [overdue_result, reminder_result]

        mock_get_dm = MagicMock(return_value="dm_room_1")

        handler = OverdueHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(return_value="test_token"),
            get_direct_room=mock_get_dm,
            get_overdue_days_func=MagicMock(return_value=2),
            admin_room_id="123456",
            escalation_days=3
        )

        # v10.24.9: 営業日判定をモックして常にTrue（営業日）にする
        with patch('handlers.overdue_handler.is_business_day', return_value=True):
            with patch('httpx.post') as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_post.return_value = mock_response

                # エラーなく処理が完了することを確認
                handler.process_overdue_tasks()

                # DMルーム取得が呼ばれたことを確認
                mock_get_dm.assert_called()


class TestSendOverdueReminderToDm:
    """send_overdue_reminder_to_dm関数のテスト"""

    def test_empty_tasks(self):
        """タスクが空の場合は何もしない"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock()
        )

        handler.send_overdue_reminder_to_dm("acc1", [], datetime.now(JST).date())

    def test_no_dm_room(self):
        """DMルームが取得できない場合はバッファに追加"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock(return_value=None),
            admin_room_id="123456"
        )

        tasks = [{"task_id": "1", "body": "テスト", "limit_time": 1704067200, "assigned_to_name": "担当者"}]
        handler.send_overdue_reminder_to_dm("acc1", tasks, datetime.now(JST).date())

        # バッファに追加されたことを確認
        assert len(handler._dm_unavailable_buffer) == 1

    def test_already_reminded(self):
        """今日既に督促済みの場合はスキップ"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [("task1",)]  # 既に督促済み

        handler = OverdueHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            get_direct_room=MagicMock(return_value="dm_room_1")
        )

        tasks = [{"task_id": "task1", "body": "テスト", "limit_time": 1704067200, "assigned_to_name": "担当者"}]

        # エラーが発生しないことを確認
        handler.send_overdue_reminder_to_dm("acc1", tasks, datetime.now(JST).date())


class TestProcessEscalations:
    """process_escalations関数のテスト"""

    def test_no_escalation_needed(self):
        """エスカレーション対象がない場合"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock(),
            get_overdue_days_func=MagicMock(return_value=2),  # 2日超過 < 3日
            escalation_days=3
        )

        overdue_tasks = [
            ("task1", "room1", "acc1", "acc2", "タスク1", 1704067200, "担当者A", "依頼者B")
        ]

        # エラーが発生しないことを確認
        handler.process_escalations(overdue_tasks, datetime.now(JST).date())

    def test_escalation_needed(self):
        """エスカレーション対象がある場合"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []  # 未エスカレーション

        handler = OverdueHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(return_value="test_token"),
            get_direct_room=MagicMock(return_value="dm_room_1"),
            get_overdue_days_func=MagicMock(return_value=5),  # 5日超過 >= 3日
            admin_room_id="123456",
            escalation_days=3
        )

        overdue_tasks = [
            ("task1", "room1", "acc1", "acc2", "タスク1", 1704067200, "担当者A", "依頼者B")
        ]

        with patch('httpx.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            handler.process_escalations(overdue_tasks, datetime.now(JST).date())


class TestSendEscalationToRequester:
    """send_escalation_to_requester関数のテスト"""

    def test_empty_tasks(self):
        """タスクが空の場合はFalseを返す"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock()
        )

        result = handler.send_escalation_to_requester("req1", [])

        assert result is False

    def test_no_dm_room(self):
        """DMルームが取得できない場合はFalseを返す"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock(return_value=None),
            admin_room_id="123456"
        )

        tasks = [{"body": "テスト", "limit_time": 1704067200, "assigned_to_name": "担当者", "overdue_days": 5}]
        result = handler.send_escalation_to_requester("req1", tasks)

        assert result is False

    def test_success(self):
        """送信成功の場合はTrueを返す"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test_token"),
            get_direct_room=MagicMock(return_value="dm_room_1")
        )

        tasks = [{"body": "テスト", "limit_time": 1704067200, "assigned_to_name": "担当者", "overdue_days": 5}]

        with patch('httpx.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            result = handler.send_escalation_to_requester("req1", tasks)

            assert result is True


class TestSendEscalationToAdmin:
    """send_escalation_to_admin関数のテスト"""

    def test_empty_tasks(self):
        """タスクが空の場合はFalseを返す"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock(),
            admin_room_id="123456"
        )

        result = handler.send_escalation_to_admin([])

        assert result is False

    def test_no_admin_room(self):
        """admin_room_idが設定されていない場合はFalseを返す"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock(),
            admin_room_id=None
        )

        tasks = [{"body": "テスト", "limit_time": 1704067200, "assigned_to_name": "担当者", "assigned_by_name": "依頼者", "overdue_days": 5}]
        result = handler.send_escalation_to_admin(tasks)

        assert result is False

    def test_success(self):
        """送信成功の場合はTrueを返す"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test_token"),
            get_direct_room=MagicMock(),
            admin_room_id="123456"
        )

        tasks = [{"body": "テスト", "limit_time": 1704067200, "assigned_to_name": "担当者", "assigned_by_name": "依頼者", "overdue_days": 5}]

        with patch('httpx.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            result = handler.send_escalation_to_admin(tasks)

            assert result is True


class TestDetectAndReportLimitChanges:
    """detect_and_report_limit_changes関数のテスト"""

    def test_same_limit(self):
        """期限が同じ場合は何もしない"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock()
        )

        # エラーが発生しないことを確認
        handler.detect_and_report_limit_changes("task1", 1704067200, 1704067200, {"body": "テスト"})

    def test_none_limit(self):
        """期限がNoneの場合は何もしない"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock()
        )

        handler.detect_and_report_limit_changes("task1", None, 1704067200, {"body": "テスト"})
        handler.detect_and_report_limit_changes("task1", 1704067200, None, {"body": "テスト"})

    def test_with_change(self):
        """期限変更がある場合は報告"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler = OverdueHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(return_value="test_token"),
            get_direct_room=MagicMock(return_value="dm_room_1"),
            admin_room_id="123456"
        )

        task_info = {
            "body": "テストタスク",
            "assigned_to_name": "担当者",
            "assigned_to_account_id": "acc1",
            "assigned_by_name": "依頼者"
        }

        with patch('httpx.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            handler.detect_and_report_limit_changes("task1", 1704067200, 1704153600, task_info)

            # httpx.postが呼ばれたことを確認（管理部+担当者）
            assert mock_post.call_count >= 1


class TestReportUnassignedOverdueTasks:
    """report_unassigned_overdue_tasks関数のテスト"""

    def test_empty_tasks(self):
        """タスクが空の場合は何もしない"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock(),
            admin_room_id="123456"
        )

        handler.report_unassigned_overdue_tasks([])

    def test_no_admin_room(self):
        """admin_room_idが設定されていない場合は何もしない"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock(),
            admin_room_id=None
        )

        tasks = [{"body": "テスト", "limit_time": 1704067200, "assigned_by_name": "依頼者"}]
        handler.report_unassigned_overdue_tasks(tasks)


class TestNotifyDmNotAvailable:
    """notify_dm_not_available関数のテスト"""

    def test_add_to_buffer(self):
        """バッファに追加されること"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock()
        )

        handler.notify_dm_not_available("担当者A", "acc1", [{"body": "テスト"}], "督促")

        assert len(handler._dm_unavailable_buffer) == 1
        assert handler._dm_unavailable_buffer[0]["person_name"] == "担当者A"


class TestFlushDmUnavailableNotifications:
    """flush_dm_unavailable_notifications関数のテスト"""

    def test_empty_buffer(self):
        """バッファが空の場合は何もしない"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            get_direct_room=MagicMock(),
            admin_room_id="123456"
        )

        handler.flush_dm_unavailable_notifications()

        # バッファは空のまま
        assert len(handler._dm_unavailable_buffer) == 0

    def test_with_items(self):
        """バッファにアイテムがある場合は送信"""
        handler = OverdueHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test_token"),
            get_direct_room=MagicMock(),
            admin_room_id="123456"
        )

        handler._dm_unavailable_buffer = [
            {"person_name": "担当者A", "account_id": "acc1", "tasks": [{"body": "テスト"}], "action_type": "督促"}
        ]

        with patch('httpx.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            handler.flush_dm_unavailable_notifications()

            # 送信されたことを確認
            mock_post.assert_called_once()

            # バッファがクリアされたことを確認
            assert len(handler._dm_unavailable_buffer) == 0
