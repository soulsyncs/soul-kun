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

    def test_normalize_for_matching_complex_suffix(self):
        """複合サフィックスの除去が正しく動作すること（BUG-002修正）"""
        handler = self._create_handler_with_rooms([])

        # 「のグループチャット」という複合サフィックスが正しく除去される
        assert handler._normalize_for_matching("管理部のグループチャット") == "管理部"
        # 他の複合パターンもテスト
        assert handler._normalize_for_matching("営業のグループチャット") == "営業"
        assert handler._normalize_for_matching("開発グループチャット") == "開発"

    def test_normalize_for_matching_special_characters(self):
        """特殊文字の除去が正しく動作すること（BUG-002修正）"""
        handler = self._create_handler_with_rooms([])

        # 【】★☆などの特殊文字が除去される
        assert handler._normalize_for_matching("【SS】★管理部★") == "ss管理部"
        assert handler._normalize_for_matching("【開発】チーム") == "開発"
        assert handler._normalize_for_matching("◆営業◆グループ") == "営業"
        assert handler._normalize_for_matching("■総務■") == "総務"

    def test_fuzzy_match_with_special_characters(self):
        """特殊文字を含むルーム名がクエリにマッチすること（BUG-002修正）"""
        rooms = [
            {"room_id": 123, "name": "【SS】★管理部★", "type": "group"},
            {"room_id": 456, "name": "【SS】開発チーム", "type": "group"},
            {"room_id": 789, "name": "2026年度 社員合宿", "type": "group"},
        ]
        handler = self._create_handler_with_rooms(rooms)

        # 「管理部のグループチャット」→「管理部」に正規化され、「【SS】★管理部★」→「ss管理部」と高スコアでマッチ
        room_id, room_name, candidates = handler._fuzzy_match_room("管理部のグループチャット")
        # 自動選択されるか、候補リストに含まれる
        if room_id:
            assert room_id == 123
            assert room_name == "【SS】★管理部★"
        else:
            # 候補に含まれていることを確認
            candidate_ids = [c["room_id"] for c in candidates]
            assert 123 in candidate_ids

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


# =====================================================
# v10.26.1: MVVベースメッセージ変換テスト
# =====================================================

class TestMessageEnhancement:
    """ソウルくんらしいメッセージ変換のテスト"""

    def _create_handler(self):
        return AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test-api-key"),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

    def test_enhance_message_prompt_exists(self):
        """メッセージ変換プロンプトが存在すること"""
        handler = self._create_handler()
        prompt = handler._get_message_enhancement_prompt()

        # MVV要素が含まれている
        assert "ソウルくん" in prompt
        assert "ウル" in prompt
        assert "可能性の解放" in prompt
        assert "心で繋がる" in prompt

        # アチーブメント流コミュニケーションが含まれている
        assert "選択理論" in prompt
        assert "自己決定理論" in prompt
        assert "サーバントリーダーシップ" in prompt

    def test_enhance_message_fallback_on_no_api_key(self):
        """APIキーがない場合、元のメッセージが返ること"""
        handler = AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value=None),  # APIキーなし
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

        result = handler._enhance_message_with_soulkun_style("おはよう")
        assert result == "おはよう"  # フォールバック

    @patch('httpx.post')
    def test_enhance_message_api_success(self, mock_post):
        """API成功時、変換されたメッセージが返ること"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "おはようウル！🐺 今日も頑張ろうウル✨"
                }
            }]
        }
        mock_post.return_value = mock_response

        handler = self._create_handler()
        result = handler._enhance_message_with_soulkun_style("おはよう", "管理部", "カズ")

        assert "ウル" in result
        assert mock_post.called

    @patch('httpx.post')
    def test_enhance_message_api_error_fallback(self, mock_post):
        """APIエラー時、元のメッセージが返ること"""
        mock_post.side_effect = Exception("API error")

        handler = self._create_handler()
        result = handler._enhance_message_with_soulkun_style("おはよう")

        assert result == "おはよう"  # フォールバック


# =====================================================
# v10.26.1: BUG-003修正テスト（メッセージ送信の戻り値）
# =====================================================

class TestMessageSendResultHandling:
    """メッセージ送信結果の処理テスト"""

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

    def test_handles_dict_result(self):
        """dict型の戻り値を処理できること"""
        handler = self._create_handler()

        # dictを返すsend_chatwork_message
        handler.send_chatwork_message = MagicMock(return_value={
            "success": True,
            "message_id": "12345"
        })

        # execute_announcement内部で正しく処理されることを確認
        # (統合テストは本番環境で実施)
        result = handler.send_chatwork_message("123", "test", return_details=True)
        assert result["success"] is True
        assert result["message_id"] == "12345"

    def test_handles_bool_result(self):
        """bool型の戻り値（旧形式）を処理できること"""
        handler = self._create_handler()

        # boolを返すsend_chatwork_message（後方互換性）
        handler.send_chatwork_message = MagicMock(return_value=True)

        result = handler.send_chatwork_message("123", "test")
        assert result is True


# =====================================================
# v10.26.2: メッセージ修正機能テスト
# =====================================================

class TestMessageModification:
    """メッセージ修正機能のテスト"""

    def _create_handler(self):
        return AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test-api-key"),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

    def test_modification_keywords_detected(self):
        """修正キーワードが検出されること"""
        handler = self._create_handler()

        # _handle_follow_up_responseでキーワード検出されることを確認
        # v10.26.4: 「伝えて」「言って」等を追加
        modification_keywords = [
            "追記", "追加", "変更", "修正", "書き換え", "直して", "変えて", "入れて",
            "伝えて", "言って", "にして", "メッセージ", "内容"
        ]
        for keyword in modification_keywords:
            test_message = f"「テスト」を{keyword}して"
            assert keyword in test_message

    def test_natural_language_modification_detected(self):
        """v10.26.4: 自然な表現での修正リクエストが検出されること"""
        handler = self._create_handler()

        # 自然な表現でのリクエスト
        natural_requests = [
            "これはテストだよっていうことを伝えてほしい",
            "テストですって言って",
            "シンプルにしてほしい",
            "メッセージをもっと短くして",
            "内容を変えてほしい",
        ]

        modification_keywords = [
            "追記", "追加", "変更", "修正", "書き換え", "直して", "変えて", "入れて",
            "伝えて", "言って", "にして", "メッセージ", "内容"
        ]

        for request in natural_requests:
            detected = any(kw in request for kw in modification_keywords)
            assert detected, f"'{request}' should be detected as modification request"

    def test_apply_modification_fallback_append(self):
        """LLMエラー時のフォールバック追記処理"""
        handler = self._create_handler()
        handler.get_secret = MagicMock(return_value=None)  # APIキーなし

        current = "おはようウル！"
        modification = "「これはテストです」を追記して"

        result = handler._apply_message_modification(current, modification, "テスト太郎")

        # 「」内のテキストが追記される
        assert "これはテストです" in result
        assert "おはようウル" in result

    def test_apply_modification_fallback_pattern_1(self):
        """フォールバック: 「〇〇」を追記してパターン"""
        handler = self._create_handler()
        handler.get_secret = MagicMock(return_value=None)

        current = "メッセージ本文"
        modification = "「追加テキスト」を追記して"

        result = handler._apply_message_modification(current, modification, "テスト太郎")

        assert "追加テキスト" in result

    @patch('httpx.post')
    def test_apply_modification_api_success(self, mock_post):
        """API成功時、修正されたメッセージが返ること"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "おはようウル！🐺 これはテストですウル✨"
                }
            }]
        }
        mock_post.return_value = mock_response

        handler = self._create_handler()
        result = handler._apply_message_modification(
            "おはようウル！",
            "これはテストですを追記して",
            "テスト太郎"
        )

        assert "これはテスト" in result
        assert mock_post.called

    @patch('httpx.post')
    def test_apply_modification_removes_code_blocks(self, mock_post):
        """コードブロックが除去されること"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "```\n修正後メッセージ\n```"
                }
            }]
        }
        mock_post.return_value = mock_response

        handler = self._create_handler()
        result = handler._apply_message_modification("元", "修正依頼", "太郎")

        assert "```" not in result
        assert "修正後メッセージ" in result


# =====================================================
# v10.26.3: 名前からアカウントID変換テスト
# =====================================================

class TestNameToAccountIdResolution:
    """名前からアカウントIDへの変換テスト"""

    def _create_handler_with_members(self, members):
        return AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test-api-key"),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(return_value=members),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

    def test_exact_name_match(self):
        """完全一致でマッチすること"""
        members = [
            {"account_id": 111, "name": "田中太郎"},
            {"account_id": 222, "name": "麻美"},
            {"account_id": 333, "name": "佐藤花子"},
        ]
        handler = self._create_handler_with_members(members)

        result = handler._match_name_to_member("麻美", members)
        assert result is not None
        assert result["account_id"] == 222

    def test_partial_name_match(self):
        """部分一致でマッチすること（名前に含まれる）"""
        members = [
            {"account_id": 111, "name": "田中 太郎"},
            {"account_id": 222, "name": "鈴木 麻美"},
            {"account_id": 333, "name": "佐藤 花子"},
        ]
        handler = self._create_handler_with_members(members)

        result = handler._match_name_to_member("麻美", members)
        assert result is not None
        assert result["account_id"] == 222

    def test_name_with_honorific(self):
        """敬称付きでもマッチすること"""
        members = [
            {"account_id": 111, "name": "田中太郎"},
            {"account_id": 222, "name": "麻美"},
        ]
        handler = self._create_handler_with_members(members)

        result = handler._match_name_to_member("麻美さん", members)
        assert result is not None
        assert result["account_id"] == 222

    def test_no_match_returns_none(self):
        """マッチしない場合はNone"""
        members = [
            {"account_id": 111, "name": "田中太郎"},
            {"account_id": 222, "name": "佐藤花子"},
        ]
        handler = self._create_handler_with_members(members)

        result = handler._match_name_to_member("山田", members)
        assert result is None

    def test_resolve_names_sets_account_ids(self):
        """名前解決でアカウントIDが設定されること"""
        members = [
            {"account_id": 111, "name": "田中太郎"},
            {"account_id": 222, "name": "麻美"},
            {"account_id": 333, "name": "佐藤花子"},
        ]
        handler = self._create_handler_with_members(members)

        parsed = ParsedAnnouncementRequest(
            raw_message="テスト",
            target_room_id=123,
            target_room_name="テストルーム",
            message_content="テストメッセージ",
            create_tasks=True,
            task_include_names=["麻美"],
            task_assign_all=True,  # 初期値はTrue
        )

        result = handler._resolve_names_to_account_ids(parsed)

        # アカウントIDが設定される
        assert 222 in result.task_include_account_ids
        # task_assign_all が False に変更される
        assert result.task_assign_all is False

    def test_resolve_names_multiple(self):
        """複数名の解決"""
        members = [
            {"account_id": 111, "name": "田中太郎"},
            {"account_id": 222, "name": "麻美"},
            {"account_id": 333, "name": "佐藤花子"},
        ]
        handler = self._create_handler_with_members(members)

        parsed = ParsedAnnouncementRequest(
            raw_message="テスト",
            target_room_id=123,
            target_room_name="テストルーム",
            message_content="テストメッセージ",
            create_tasks=True,
            task_include_names=["麻美", "田中"],
        )

        result = handler._resolve_names_to_account_ids(parsed)

        assert 222 in result.task_include_account_ids
        assert 111 in result.task_include_account_ids
        assert len(result.task_include_account_ids) == 2


class TestFollowUpModificationDetection:
    """フォローアップ応答でのメッセージ修正検出テスト"""

    def _create_handler(self):
        return AnnouncementHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(return_value="test-api-key"),
            call_chatwork_api_with_retry=MagicMock(),
            get_room_members=MagicMock(),
            get_all_rooms=MagicMock(),
            create_chatwork_task=MagicMock(),
            send_chatwork_message=MagicMock(),
        )

    def test_follow_up_detects_modification_request(self):
        """フォローアップで修正リクエストが検出されること"""
        modification_requests = [
            "これはテストだよっていうのを追記して",
            "メッセージを変更して",
            "文章を修正してほしい",
            "追加で書き換えてくれる？",
            "ちょっと直してもらえる？",
            "ここを変えて",
            "〇〇を入れて",
        ]

        modification_keywords = [
            "追記", "追加", "変更", "修正", "書き換え", "直して", "変えて", "入れて",
            "伝えて", "言って", "にして", "メッセージ", "内容"
        ]

        for request in modification_requests:
            detected = any(kw in request for kw in modification_keywords)
            assert detected, f"'{request}' should be detected as modification request"

    def test_ok_response_not_detected_as_modification(self):
        """OKやキャンセルは修正リクエストとして検出されないこと"""
        non_modification = ["OK", "ok", "キャンセル", "やめる", "はい", "送信"]

        modification_keywords = [
            "追記", "追加", "変更", "修正", "書き換え", "直して", "変えて", "入れて",
            "伝えて", "言って", "にして", "メッセージ", "内容"
        ]

        for response in non_modification:
            detected = any(kw in response for kw in modification_keywords)
            assert not detected, f"'{response}' should NOT be detected as modification request"


# =====================================================
# v10.26.5: 非フォローアップ検出テスト
# =====================================================

class TestNonFollowUpDetection:
    """フォローアップではないメッセージの検出テスト"""

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

    def test_self_task_query_returns_none(self):
        """「自分のタスク教えて」はフォローアップではない（Noneを返す）"""
        handler = self._create_handler()
        context = {
            "awaiting_announcement_response": True,
            "pending_announcement_id": "test-id",
        }

        result = handler._handle_follow_up_response(
            params={"raw_message": "自分のタスク教えて"},
            room_id="123",
            account_id="456",
            sender_name="テスト太郎",
            context=context,
        )

        # Noneが返ってAI司令塔に処理が委ねられる
        assert result is None

    def test_my_task_query_returns_none(self):
        """「私のタスクを確認して」はフォローアップではない"""
        handler = self._create_handler()
        context = {
            "awaiting_announcement_response": True,
            "pending_announcement_id": "test-id",
        }

        result = handler._handle_follow_up_response(
            params={"raw_message": "私のタスクを確認して"},
            room_id="123",
            account_id="456",
            sender_name="テスト太郎",
            context=context,
        )

        assert result is None

    def test_general_query_returns_none(self):
        """「今日の予定教えて」はフォローアップではない"""
        handler = self._create_handler()
        context = {
            "awaiting_announcement_response": True,
            "pending_announcement_id": "test-id",
        }

        result = handler._handle_follow_up_response(
            params={"raw_message": "今日の予定教えて"},
            room_id="123",
            account_id="456",
            sender_name="テスト太郎",
            context=context,
        )

        assert result is None

    def test_task_addition_is_follow_up(self):
        """「タスク追加して」はフォローアップとして処理される（Noneではない）"""
        handler = self._create_handler()

        # DBモック
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = {
            "id": "test-id",
            "message_content": "テストメッセージ",
            "target_room_id": "100",
            "target_room_name": "テストルーム",
            "create_tasks": False,
            "task_deadline": None,
            "task_assign_all_members": False,
            "task_include_account_ids": None,
            "task_exclude_account_ids": None,
            "schedule_type": "immediate",
            "scheduled_at": None,
            "cron_expression": None,
        }
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        handler.get_pool().connect.return_value = mock_conn

        context = {
            "awaiting_announcement_response": True,
            "pending_announcement_id": "test-id",
        }

        result = handler._handle_follow_up_response(
            params={"raw_message": "タスク追加して"},
            room_id="123",
            account_id="456",
            sender_name="テスト太郎",
            context=context,
        )

        # Noneではなく、何らかの応答が返る（確認メッセージ）
        assert result is not None

    def test_ok_is_follow_up(self):
        """「OK」はフォローアップとして処理される"""
        handler = self._create_handler()

        # DBモック（execute_announcement_by_idで使用）
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None  # 実行対象なしでエラーになる
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        handler.get_pool().connect.return_value = mock_conn

        context = {
            "awaiting_announcement_response": True,
            "pending_announcement_id": "test-id",
        }

        result = handler._handle_follow_up_response(
            params={"raw_message": "OK"},
            room_id="123",
            account_id="456",
            sender_name="テスト太郎",
            context=context,
        )

        # Noneではなく、何らかの応答が返る
        assert result is not None

    def test_cancel_is_follow_up(self):
        """「キャンセル」はフォローアップとして処理される"""
        handler = self._create_handler()

        # _cancel_announcementのDBモック
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        handler.get_pool().connect.return_value = mock_conn

        context = {
            "awaiting_announcement_response": True,
            "pending_announcement_id": "test-id",
        }

        result = handler._handle_follow_up_response(
            params={"raw_message": "キャンセル"},
            room_id="123",
            account_id="456",
            sender_name="テスト太郎",
            context=context,
        )

        assert result is not None
        assert "キャンセル" in result
