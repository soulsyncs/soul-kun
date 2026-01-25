"""
タスク管理ハンドラーのテスト

chatwork-webhook/handlers/task_handler.py のテスト
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import sys
import os

# chatwork-webhookのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))

from handlers.task_handler import TaskHandler


class TestTaskHandlerInit:
    """TaskHandlerの初期化テスト"""

    def test_init_minimal(self):
        """最小限のパラメータで初期化できること"""
        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )
        assert handler.get_pool is not None
        assert handler.get_secret is not None
        assert handler.call_chatwork_api_with_retry is not None
        assert handler.extract_task_subject is None
        assert handler.use_text_utils is False

    def test_init_full(self):
        """全パラメータで初期化できること"""
        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            extract_task_subject=MagicMock(),
            clean_chatwork_tags=MagicMock(),
            prepare_task_display_text=MagicMock(),
            validate_summary=MagicMock(),
            get_user_primary_department=MagicMock(),
            use_text_utils=True
        )
        assert handler.extract_task_subject is not None
        assert handler.clean_chatwork_tags is not None
        assert handler.use_text_utils is True


class TestCreateChatworkTask:
    """create_chatwork_task関数のテスト"""

    def test_create_task_success(self):
        """タスク作成が成功すること"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"task_id": 12345}
        mock_response.text = '{"task_id": 12345}'

        mock_api = MagicMock(return_value=(mock_response, True))

        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test_token"),
            call_chatwork_api_with_retry=mock_api
        )

        result = handler.create_chatwork_task(
            room_id="123",
            task_body="テストタスク",
            assigned_to_account_id="456"
        )

        assert result == {"task_id": 12345}
        mock_api.assert_called_once()

    def test_create_task_with_limit(self):
        """期限付きタスク作成"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"task_id": 12345}
        mock_response.text = '{"task_id": 12345}'

        mock_api = MagicMock(return_value=(mock_response, True))

        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test_token"),
            call_chatwork_api_with_retry=mock_api
        )

        result = handler.create_chatwork_task(
            room_id="123",
            task_body="テストタスク",
            assigned_to_account_id="456",
            limit=1704067200
        )

        assert result is not None
        # data引数にlimitが含まれていることを確認
        call_args = mock_api.call_args
        assert "limit" in call_args.kwargs["data"]

    def test_create_task_api_error(self):
        """API エラー時はNoneを返すこと"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        mock_api = MagicMock(return_value=(mock_response, False))

        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test_token"),
            call_chatwork_api_with_retry=mock_api
        )

        result = handler.create_chatwork_task(
            room_id="123",
            task_body="テストタスク",
            assigned_to_account_id="456"
        )

        assert result is None

    def test_create_task_no_response(self):
        """レスポンスがない場合はNoneを返すこと"""
        mock_api = MagicMock(return_value=(None, False))

        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test_token"),
            call_chatwork_api_with_retry=mock_api
        )

        result = handler.create_chatwork_task(
            room_id="123",
            task_body="テストタスク",
            assigned_to_account_id="456"
        )

        assert result is None


class TestCompleteChatworkTask:
    """complete_chatwork_task関数のテスト"""

    def test_complete_task_success(self):
        """タスク完了が成功すること"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"task_id": 12345}
        mock_response.text = '{"task_id": 12345}'

        mock_api = MagicMock(return_value=(mock_response, True))

        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test_token"),
            call_chatwork_api_with_retry=mock_api
        )

        result = handler.complete_chatwork_task(
            room_id="123",
            task_id="456"
        )

        assert result == {"task_id": 12345}

    def test_complete_task_error(self):
        """タスク完了エラー時はNoneを返すこと"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        mock_api = MagicMock(return_value=(mock_response, False))

        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test_token"),
            call_chatwork_api_with_retry=mock_api
        )

        result = handler.complete_chatwork_task(
            room_id="123",
            task_id="456"
        )

        assert result is None


class TestSearchTasksFromDb:
    """search_tasks_from_db関数のテスト"""

    def test_search_tasks_basic(self):
        """基本的なタスク検索"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            ("task1", "タスク1", None, "open", "acc1", "acc2", None, "room1", "Room 1"),
            ("task2", "タスク2", 1704067200, "open", "acc1", "acc3", "dept1", "room1", "Room 1"),
        ]

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler.search_tasks_from_db(
            room_id="room1",
            assigned_to_account_id="acc1"
        )

        assert len(result) == 2
        assert result[0]["task_id"] == "task1"
        assert result[1]["task_id"] == "task2"
        assert result[1]["department_id"] == "dept1"

    def test_search_tasks_all_rooms(self):
        """全ルームからのタスク検索（search_all_rooms=True）"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            ("task1", "タスク1", None, "open", "acc1", "acc2", None, "room1", "Room 1"),
            ("task2", "タスク2", None, "open", "acc1", "acc2", None, "room2", "Room 2"),
        ]

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler.search_tasks_from_db(
            room_id="room1",
            assigned_to_account_id="acc1",
            search_all_rooms=True
        )

        assert len(result) == 2
        # SQLにroom_idフィルタが含まれていないことを確認
        call_args = mock_conn.execute.call_args
        query_text = str(call_args[0][0])
        assert "WHERE 1=1" in query_text

    def test_search_tasks_by_status(self):
        """ステータスによるタスク検索"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        handler.search_tasks_from_db(
            room_id="room1",
            status="done"
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["status"] == "done"

    def test_search_tasks_all_status(self):
        """全ステータス検索（status="all"）"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        handler.search_tasks_from_db(
            room_id="room1",
            status="all"
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert "status" not in params

    def test_search_tasks_error(self):
        """エラー時は空リストを返すこと"""
        mock_pool = MagicMock()
        mock_pool.connect.side_effect = Exception("DB Error")

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler.search_tasks_from_db(room_id="room1")

        assert result == []

    def test_search_tasks_with_dept_filter(self):
        """部署フィルタ有効時のタスク検索"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        mock_get_user_id = MagicMock(return_value="user1")
        mock_get_accessible_depts = MagicMock(return_value=["dept1", "dept2"])

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        handler.search_tasks_from_db(
            room_id="room1",
            assigned_to_account_id="acc1",
            enable_dept_filter=True,
            organization_id="org1",
            get_user_id_func=mock_get_user_id,
            get_accessible_departments_func=mock_get_accessible_depts
        )

        # 部署フィルタ関数が呼ばれていることを確認
        mock_get_user_id.assert_called_once()
        mock_get_accessible_depts.assert_called_once()


class TestUpdateTaskStatusInDb:
    """update_task_status_in_db関数のテスト"""

    def test_update_status_success(self):
        """ステータス更新が成功すること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler.update_task_status_in_db(
            task_id="task1",
            status="done"
        )

        assert result is True
        mock_conn.execute.assert_called_once()

    def test_update_status_error(self):
        """エラー時はFalseを返すこと"""
        mock_pool = MagicMock()
        mock_pool.begin.side_effect = Exception("DB Error")

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler.update_task_status_in_db(
            task_id="task1",
            status="done"
        )

        assert result is False


class TestSaveChatworkTaskToDb:
    """save_chatwork_task_to_db関数のテスト"""

    def test_save_task_success(self):
        """タスク保存が成功すること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler.save_chatwork_task_to_db(
            task_id="task1",
            room_id="room1",
            assigned_by_account_id="acc1",
            assigned_to_account_id="acc2",
            body="テストタスク本文"
        )

        assert result is True
        mock_conn.execute.assert_called_once()

    def test_save_task_with_limit(self):
        """期限付きタスク保存"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler.save_chatwork_task_to_db(
            task_id="task1",
            room_id="room1",
            assigned_by_account_id="acc1",
            assigned_to_account_id="acc2",
            body="テストタスク本文",
            limit_time=1704067200
        )

        assert result is True

    def test_save_task_with_department(self):
        """部署ID付きタスク保存"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_dept = MagicMock(return_value="dept1")

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_user_primary_department=mock_get_dept
        )

        result = handler.save_chatwork_task_to_db(
            task_id="task1",
            room_id="room1",
            assigned_by_account_id="acc1",
            assigned_to_account_id="acc2",
            body="テストタスク本文"
        )

        assert result is True
        mock_get_dept.assert_called_once()

    def test_save_task_error(self):
        """エラー時はFalseを返すこと"""
        mock_pool = MagicMock()
        mock_pool.begin.side_effect = Exception("DB Error")

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler.save_chatwork_task_to_db(
            task_id="task1",
            room_id="room1",
            assigned_by_account_id="acc1",
            assigned_to_account_id="acc2",
            body="テストタスク本文"
        )

        assert result is False


class TestGenerateTaskSummary:
    """_generate_task_summary関数のテスト"""

    def test_generate_summary_no_body(self):
        """本文がない場合はNoneを返すこと"""
        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler._generate_task_summary("")

        assert result is None

    def test_generate_summary_fallback(self):
        """text_utils未使用時はフォールバック"""
        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            use_text_utils=False
        )

        body = "これは長いタスク本文です。40文字を超える場合は切り詰められます。あいうえおかきくけこさしすせそ"
        result = handler._generate_task_summary(body)

        assert result is not None
        assert len(result) <= 40

    def test_generate_summary_short_body(self):
        """短い本文はそのまま返す"""
        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            use_text_utils=False
        )

        body = "短いタスク"
        result = handler._generate_task_summary(body)

        assert result == body

    def test_generate_summary_with_text_utils(self):
        """text_utils使用時は件名抽出を試みる"""
        mock_extract = MagicMock(return_value="抽出された件名")
        mock_prepare = MagicMock(return_value="準備されたテキスト")

        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            extract_task_subject=mock_extract,
            prepare_task_display_text=mock_prepare,
            use_text_utils=True
        )

        result = handler._generate_task_summary("【件名】テストタスク\n本文です")

        assert result == "抽出された件名"
        mock_extract.assert_called_once()

    def test_generate_summary_subject_too_long(self):
        """件名が長すぎる場合はprepare_task_display_textを使用"""
        long_subject = "A" * 50  # 40文字超
        mock_extract = MagicMock(return_value=long_subject)
        mock_prepare = MagicMock(return_value="短縮されたテキスト")

        handler = TaskHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            extract_task_subject=mock_extract,
            prepare_task_display_text=mock_prepare,
            use_text_utils=True
        )

        result = handler._generate_task_summary("【件名】" + long_subject)

        assert result == "短縮されたテキスト"
        mock_prepare.assert_called_once()


class TestLogAnalyticsEvent:
    """log_analytics_event関数のテスト"""

    def test_log_event_success(self):
        """イベントログ記録が成功すること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        handler.log_analytics_event(
            event_type="task_created",
            actor_account_id="123",
            actor_name="Test User",
            room_id="456",
            event_data={"key": "value"}
        )

        mock_conn.execute.assert_called_once()

    def test_log_event_with_error(self):
        """エラー付きイベントログ記録"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        handler.log_analytics_event(
            event_type="task_created",
            actor_account_id="123",
            actor_name="Test User",
            room_id="456",
            event_data=None,
            success=False,
            error_message="Something went wrong"
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["success"] is False
        assert params["error_message"] == "Something went wrong"

    def test_log_event_with_subtype(self):
        """サブタイプ付きイベントログ記録"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        handler.log_analytics_event(
            event_type="task_created",
            actor_account_id="123",
            actor_name="Test User",
            room_id="456",
            event_data=None,
            event_subtype="via_dialog"
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["event_subtype"] == "via_dialog"

    def test_log_event_error_does_not_raise(self):
        """エラー時も例外を投げないこと"""
        mock_pool = MagicMock()
        mock_pool.begin.side_effect = Exception("DB Error")

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        # 例外が発生しないことを確認
        handler.log_analytics_event(
            event_type="task_created",
            actor_account_id="123",
            actor_name="Test User",
            room_id="456",
            event_data=None
        )


class TestGetTaskById:
    """get_task_by_id関数のテスト"""

    def test_get_task_found(self):
        """タスクが見つかること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (
            "task1", "room1", "タスク本文", 1704067200, "open", "acc1", "acc2", "dept1", "要約テキスト"
        )

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler.get_task_by_id("task1")

        assert result is not None
        assert result["task_id"] == "task1"
        assert result["room_id"] == "room1"
        assert result["body"] == "タスク本文"
        assert result["status"] == "open"
        assert result["summary"] == "要約テキスト"

    def test_get_task_not_found(self):
        """タスクが見つからない場合はNoneを返すこと"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler.get_task_by_id("nonexistent")

        assert result is None

    def test_get_task_error(self):
        """エラー時はNoneを返すこと"""
        mock_pool = MagicMock()
        mock_pool.connect.side_effect = Exception("DB Error")

        handler = TaskHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock()
        )

        result = handler.get_task_by_id("task1")

        assert result is None
