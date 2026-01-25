"""
アナウンス機能ハンドラーのテスト

chatwork-webhook/handlers/announcement_handler.py のテスト
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timedelta
import sys
import os
import json

# chatwork-webhookのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))

from handlers.announcement_handler import (
    AnnouncementHandler,
    ParsedAnnouncementRequest,
    ScheduleType,
    AnnouncementStatus,
    PATTERN_THRESHOLD,
    ROOM_MATCH_AUTO_SELECT_THRESHOLD,
)


# =====================================================
# 初期化テスト
# =====================================================

class TestAnnouncementHandlerInit:
    """AnnouncementHandlerの初期化テスト"""

    def test_init_minimal(self):
        """最小限のパラメータで初期化できること"""
        handler = AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )
        assert handler.get_pool is not None
        assert handler.get_secret is not None
        assert handler._admin_account_id == "1728974"
        assert handler._organization_id == "org_soulsyncs"

    def test_init_with_custom_authorized_rooms(self):
        """カスタム認可ルームで初期化できること"""
        custom_rooms = {123456, 789012}
        handler = AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
            authorized_room_ids=custom_rooms,
        )
        assert handler._authorized_room_ids == custom_rooms

    def test_init_with_kazu_dm_room(self):
        """カズさんDMルームIDが追加されること"""
        handler = AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
            kazu_dm_room_id=999999,
        )
        assert 999999 in handler._authorized_room_ids


# =====================================================
# 認可テスト
# =====================================================

class TestAuthorization:
    """認可チェックのテスト"""

    def _create_handler(self, authorized_rooms=None):
        return AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
            authorized_room_ids=authorized_rooms or {405315911},
            admin_account_id="1728974",
        )

    def test_admin_authorized_from_authorized_room(self):
        """管理者は認可ルームから認可されること"""
        handler = self._create_handler()
        authorized, reason = handler.is_authorized_request("405315911", "1728974")
        assert authorized is True
        assert reason == ""

    def test_admin_authorized_from_any_room(self):
        """管理者はどのルームからでも認可されること（個人チャット含む）"""
        handler = self._create_handler()
        # 認可リストにないルームからでもカズさんはOK
        authorized, reason = handler.is_authorized_request("123456789", "1728974")
        assert authorized is True
        assert reason == ""

    def test_non_admin_from_authorized_room(self):
        """管理者以外は認可ルームからでも拒否されること（現時点）"""
        handler = self._create_handler()
        authorized, reason = handler.is_authorized_request("405315911", "9999999")
        assert authorized is False
        assert "管理者" in reason

    def test_non_admin_from_wrong_room(self):
        """管理者以外が認可されていないルームからは拒否されること"""
        handler = self._create_handler()
        authorized, reason = handler.is_authorized_request("123456789", "9999999")
        assert authorized is False
        assert "管理部チャット" in reason

    def test_admin_in_custom_authorized_room(self):
        """カスタム認可ルームでも管理者は許可されること"""
        handler = self._create_handler({123456, 789012})
        authorized, reason = handler.is_authorized_request("123456", "1728974")
        assert authorized is True


# =====================================================
# ルームマッチングテスト
# =====================================================

class TestRoomMatching:
    """ルーム曖昧マッチングのテスト"""

    def _create_handler_with_rooms(self, rooms):
        mock_get_all_rooms = MagicMock(return_value=rooms)
        return AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=mock_get_all_rooms,
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

    def test_normalize_for_matching(self):
        """正規化処理が正しく動作すること"""
        handler = self._create_handler_with_rooms([])

        assert handler._normalize_for_matching("合宿のチャット") == "合宿"
        assert handler._normalize_for_matching("開発グループ") == "開発"
        assert handler._normalize_for_matching("営業チーム") == "営業"
        assert handler._normalize_for_matching("テスト ルーム") == "テスト"

    def test_exact_match(self):
        """完全一致の場合"""
        rooms = [
            {"room_id": 123, "name": "開発チーム", "type": "group"},
            {"room_id": 456, "name": "営業チーム", "type": "group"},
        ]
        handler = self._create_handler_with_rooms(rooms)

        room_id, room_name, candidates = handler._fuzzy_match_room("開発")
        assert room_id == 123
        assert room_name == "開発チーム"
        assert candidates == []

    def test_partial_match(self):
        """部分一致の場合"""
        rooms = [
            {"room_id": 123, "name": "2026年度 社員合宿", "type": "group"},
            {"room_id": 456, "name": "合宿準備委員会", "type": "group"},
        ]
        handler = self._create_handler_with_rooms(rooms)

        room_id, room_name, candidates = handler._fuzzy_match_room("合宿")
        # 高スコアなら自動選択、低スコアなら候補
        if room_id:
            assert room_id in [123, 456]
        else:
            assert len(candidates) == 2

    def test_no_match(self):
        """マッチしない場合"""
        rooms = [
            {"room_id": 123, "name": "開発チーム", "type": "group"},
        ]
        handler = self._create_handler_with_rooms(rooms)

        room_id, room_name, candidates = handler._fuzzy_match_room("存在しないルーム")
        assert room_id is None
        assert room_name is None
        assert candidates == []

    def test_skip_my_room(self):
        """マイチャットはスキップされること"""
        rooms = [
            {"room_id": 123, "name": "マイチャット", "type": "my"},
            {"room_id": 456, "name": "開発チーム", "type": "group"},
        ]
        handler = self._create_handler_with_rooms(rooms)

        room_id, room_name, candidates = handler._fuzzy_match_room("マイ")
        # マイチャットはスキップされるのでマッチしない
        assert room_id is None or room_id == 456

    def test_score_calculation(self):
        """スコア計算が正しく動作すること"""
        handler = self._create_handler_with_rooms([])

        # 完全一致
        assert handler._calculate_room_match_score("開発", "開発") == 1.0

        # クエリがルーム名に含まれる
        score = handler._calculate_room_match_score("合宿", "2026年度 社員合宿")
        assert score >= 0.8

        # 部分マッチ
        score = handler._calculate_room_match_score("営業", "営業部グループ")
        assert score > 0.3


# =====================================================
# ParsedAnnouncementRequestテスト
# =====================================================

class TestParsedAnnouncementRequest:
    """ParsedAnnouncementRequestのテスト"""

    def test_default_values(self):
        """デフォルト値が正しく設定されること"""
        parsed = ParsedAnnouncementRequest(raw_message="テスト")
        assert parsed.raw_message == "テスト"
        assert parsed.target_room_query == ""
        assert parsed.target_room_id is None
        assert parsed.create_tasks is False
        assert parsed.schedule_type == ScheduleType.IMMEDIATE
        assert parsed.skip_holidays is True
        assert parsed.skip_weekends is True
        assert parsed.needs_clarification is False

    def test_with_task_settings(self):
        """タスク設定が正しく保持されること"""
        parsed = ParsedAnnouncementRequest(
            raw_message="テスト",
            create_tasks=True,
            task_assign_all=True,
            task_exclude_names=["田中", "佐藤"],
        )
        assert parsed.create_tasks is True
        assert parsed.task_assign_all is True
        assert parsed.task_exclude_names == ["田中", "佐藤"]

    def test_with_schedule_settings(self):
        """スケジュール設定が正しく保持されること"""
        scheduled_at = datetime.now()
        parsed = ParsedAnnouncementRequest(
            raw_message="テスト",
            schedule_type=ScheduleType.RECURRING,
            cron_expression="0 9 * * 1",
            cron_description="毎週月曜9時",
            scheduled_at=scheduled_at,
        )
        assert parsed.schedule_type == ScheduleType.RECURRING
        assert parsed.cron_expression == "0 9 * * 1"
        assert parsed.scheduled_at == scheduled_at


# =====================================================
# 確認メッセージ生成テスト
# =====================================================

class TestConfirmationGeneration:
    """確認メッセージ生成のテスト"""

    def _create_handler(self):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("test-uuid",)
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_pool.connect.return_value = mock_conn

        return AnnouncementHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

    def test_basic_confirmation(self):
        """基本的な確認メッセージ"""
        handler = self._create_handler()
        parsed = ParsedAnnouncementRequest(
            raw_message="テスト",
            target_room_id=123,
            target_room_name="テストルーム",
            message_content="テストメッセージです",
        )

        # _save_pending_announcement をモック
        with patch.object(handler, '_save_pending_announcement', return_value="test-id"):
            result = handler._generate_confirmation(parsed, "123", "456", "テスト太郎")

        assert "テストルーム" in result
        assert "テストメッセージ" in result
        assert "OK" in result
        assert "キャンセル" in result

    def test_confirmation_with_tasks(self):
        """タスク付きの確認メッセージ"""
        handler = self._create_handler()
        parsed = ParsedAnnouncementRequest(
            raw_message="テスト",
            target_room_id=123,
            target_room_name="テストルーム",
            message_content="テストメッセージです",
            create_tasks=True,
            task_assign_all=True,
            task_exclude_names=["田中"],
        )

        with patch.object(handler, '_save_pending_announcement', return_value="test-id"):
            result = handler._generate_confirmation(parsed, "123", "456", "テスト太郎")

        assert "タスク作成" in result
        assert "全員" in result
        assert "田中" in result

    def test_confirmation_with_recurring(self):
        """繰り返し設定の確認メッセージ"""
        handler = self._create_handler()
        parsed = ParsedAnnouncementRequest(
            raw_message="テスト",
            target_room_id=123,
            target_room_name="テストルーム",
            message_content="テストメッセージです",
            schedule_type=ScheduleType.RECURRING,
            cron_description="毎週月曜9時",
            skip_holidays=True,
        )

        with patch.object(handler, '_save_pending_announcement', return_value="test-id"):
            result = handler._generate_confirmation(parsed, "123", "456", "テスト太郎")

        assert "繰り返し" in result
        assert "毎週月曜9時" in result
        assert "祝日" in result


# =====================================================
# メインハンドラーテスト
# =====================================================

class TestHandleAnnouncementRequest:
    """handle_announcement_request のテスト"""

    def _create_handler(self, authorized=True):
        handler = AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test-api-key"),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(return_value=[]),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
            authorized_room_ids={405315911} if authorized else set(),
            admin_account_id="1728974",
        )
        return handler

    def test_admin_can_use_from_any_room(self):
        """管理者はどのルームからでも使用可能"""
        handler = self._create_handler(authorized=True)
        result = handler.handle_announcement_request(
            params={"raw_message": "テスト"},
            room_id="999999",  # 認可リストにないルーム
            account_id="1728974",  # でもカズさんなのでOK
            sender_name="カズ",
        )
        # 拒否されない（確認フローが始まる）
        assert "🚫" not in result

    def test_non_admin_from_wrong_room_rejected(self):
        """非管理者が認可されていないルームからは拒否"""
        handler = self._create_handler(authorized=True)
        result = handler.handle_announcement_request(
            params={"raw_message": "テスト"},
            room_id="999999",  # 認可されていないルーム
            account_id="999999",  # 非管理者
            sender_name="テスト太郎",
        )
        assert "🚫" in result

    def test_unauthorized_user(self):
        """認可されていないユーザーからは拒否"""
        handler = self._create_handler(authorized=True)
        result = handler.handle_announcement_request(
            params={"raw_message": "テスト"},
            room_id="405315911",
            account_id="999999",  # 認可されていない
            sender_name="テスト太郎",
        )
        assert "🚫" in result


# =====================================================
# 定数テスト
# =====================================================

class TestConstants:
    """定数のテスト"""

    def test_pattern_threshold(self):
        """パターン閾値が正しいこと"""
        assert PATTERN_THRESHOLD == 3

    def test_room_match_threshold(self):
        """ルームマッチ閾値が正しいこと"""
        assert ROOM_MATCH_AUTO_SELECT_THRESHOLD == 0.8

    def test_schedule_types(self):
        """スケジュールタイプが正しいこと"""
        assert ScheduleType.IMMEDIATE.value == "immediate"
        assert ScheduleType.ONE_TIME.value == "one_time"
        assert ScheduleType.RECURRING.value == "recurring"

    def test_announcement_statuses(self):
        """アナウンスステータスが正しいこと"""
        assert AnnouncementStatus.PENDING.value == "pending"
        assert AnnouncementStatus.CONFIRMED.value == "confirmed"
        assert AnnouncementStatus.COMPLETED.value == "completed"
        assert AnnouncementStatus.CANCELLED.value == "cancelled"


# =====================================================
# パターン記録テスト
# =====================================================

class TestPatternRecording:
    """パターン記録（A1連携）のテスト"""

    def test_normalize_request_for_pattern(self):
        """パターン正規化が正しく動作すること"""
        handler = AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

        parsed = ParsedAnnouncementRequest(
            raw_message="テスト依頼",
            target_room_name="開発チーム",
            message_content="これはテストメッセージです。",
        )

        normalized = handler._normalize_request_for_pattern(parsed)

        assert "開発チーム" in normalized.lower()
        assert "テスト" in normalized.lower()


# =====================================================
# エッジケーステスト
# =====================================================

class TestEdgeCases:
    """エッジケースのテスト"""

    def test_empty_message(self):
        """空のメッセージ"""
        handler = AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test-key"),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(return_value=[]),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
            authorized_room_ids={405315911},
            admin_account_id="1728974",
        )

        # LLMをモック
        with patch('httpx.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "choices": [{
                    "message": {
                        "content": '{"needs_clarification": true, "clarification_questions": ["何を送りますか？"]}'
                    }
                }]
            }
            mock_post.return_value = mock_response

            result = handler.handle_announcement_request(
                params={"raw_message": ""},
                room_id="405315911",
                account_id="1728974",
                sender_name="テスト太郎",
            )

        # 空メッセージでも処理されること
        assert result is not None

    def test_no_rooms_available(self):
        """ルームが存在しない場合"""
        handler = AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(return_value=[]),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

        room_id, room_name, candidates = handler._fuzzy_match_room("テスト")
        assert room_id is None
        assert candidates == []


# =====================================================
# 実行テスト（モック）
# =====================================================

class TestAnnouncementExecution:
    """アナウンス実行のテスト（モック使用）"""

    def _create_handler_with_db_mock(self, announcement_data):
        """DBモック付きハンドラーを作成"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()

        # fetchone のモック
        mock_result = MagicMock()
        mock_result.fetchone.return_value = tuple(announcement_data.values())
        mock_result.keys.return_value = list(announcement_data.keys())
        mock_conn.execute.return_value = mock_result
        mock_conn.commit = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_pool.connect.return_value = mock_conn

        return AnnouncementHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(return_value=[
                {"account_id": 111, "name": "田中"},
                {"account_id": 222, "name": "佐藤"},
            ]),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(return_value={"task_ids": ["t1"]}),
            send_chatwork_message=MagicMock(return_value={"message_id": "m1"}),
            is_business_day=MagicMock(return_value=True),
        )

    def test_execute_announcement_not_found(self):
        """存在しないアナウンス"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_pool.connect.return_value = mock_conn

        handler = AnnouncementHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

        result = handler.execute_announcement("non-existent-id")
        assert result["success"] is False
        assert "見つかりません" in result["errors"][0]


# =====================================================
# 期限解析テスト
# =====================================================

class TestParseDeadline:
    """_parse_deadline のテスト"""

    def _create_handler(self):
        return AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

    def test_parse_next_week_friday(self):
        """来週金曜のパース"""
        handler = self._create_handler()
        result = handler._parse_deadline("来週金曜まで")
        assert result is not None
        assert result.weekday() == 4  # 金曜日

    def test_parse_tomorrow(self):
        """明日のパース"""
        handler = self._create_handler()
        result = handler._parse_deadline("明日まで")
        assert result is not None
        # 明日であることを確認
        from datetime import datetime, timedelta
        import pytz
        JST = pytz.timezone('Asia/Tokyo')
        now = datetime.now(JST)
        tomorrow = now + timedelta(days=1)
        assert result.date() == tomorrow.date()

    def test_parse_days_later(self):
        """〇日後のパース"""
        handler = self._create_handler()
        result = handler._parse_deadline("3日後")
        assert result is not None
        from datetime import datetime, timedelta
        import pytz
        JST = pytz.timezone('Asia/Tokyo')
        now = datetime.now(JST)
        expected = now + timedelta(days=3)
        assert result.date() == expected.date()

    def test_parse_date_format(self):
        """月日形式のパース"""
        handler = self._create_handler()
        result = handler._parse_deadline("1/31まで")
        assert result is not None
        assert result.month == 1
        assert result.day == 31

    def test_parse_no_deadline(self):
        """期限指定なし"""
        handler = self._create_handler()
        result = handler._parse_deadline("タスクも作って")
        assert result is None


# =====================================================
# 確認メッセージのタスク質問テスト
# =====================================================

class TestConfirmationTaskQuestion:
    """確認メッセージでタスク作成を聞くテスト"""

    def _create_handler(self):
        return AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

    def test_confirmation_without_tasks_shows_hint(self):
        """タスク指定なしの場合、ヒントが表示されること"""
        handler = self._create_handler()
        parsed = ParsedAnnouncementRequest(
            raw_message="テスト",
            target_room_id=123,
            target_room_name="テストルーム",
            message_content="テストメッセージです",
            create_tasks=False,  # タスク作成なし
        )

        with patch.object(handler, '_save_pending_announcement', return_value="test-id"):
            result = handler._generate_confirmation(parsed, "123", "456", "テスト太郎")

        assert "タスク作成**: なし" in result
        assert "タスクも作って" in result
        assert "全員にタスク" in result

    def test_confirmation_with_tasks_no_hint(self):
        """タスク指定ありの場合、ヒントが表示されないこと"""
        handler = self._create_handler()
        parsed = ParsedAnnouncementRequest(
            raw_message="テスト",
            target_room_id=123,
            target_room_name="テストルーム",
            message_content="テストメッセージです",
            create_tasks=True,  # タスク作成あり
            task_assign_all=True,
        )

        with patch.object(handler, '_save_pending_announcement', return_value="test-id"):
            result = handler._generate_confirmation(parsed, "123", "456", "テスト太郎")

        assert "タスク作成**: はい" in result
        assert "タスクも作って" not in result
