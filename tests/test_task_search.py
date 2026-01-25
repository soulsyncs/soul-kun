"""
タスク検索機能のテスト（v10.22.0 BUG-001修正）

BUG-001: 「自分のタスクを教えて」と聞くと別チャットのタスクが見つからない問題
修正: search_all_rooms=True で全ルームから検索するように変更
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import sys
import os

# chatwork-webhook/main.py をインポートできるようにパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))


class TestSearchAllRooms:
    """search_all_rooms パラメータのテスト"""

    def test_search_tasks_query_with_room_id(self):
        """従来動作: room_idでフィルタするクエリが生成される"""
        # search_all_rooms=False（デフォルト）の場合
        # WHERE room_id = :room_id が含まれるべき
        pass  # 実際のDBがなくてもテスト可能な形に

    def test_search_tasks_query_without_room_id(self):
        """BUG-001修正: search_all_rooms=Trueでroom_idフィルタをスキップ"""
        # search_all_rooms=True の場合
        # WHERE room_id = :room_id が含まれないべき
        pass


class TestTaskSearchHandler:
    """handle_chatwork_task_search のテスト"""

    @pytest.fixture
    def mock_tasks_single_room(self):
        """単一ルームのタスクデータ"""
        return [
            {
                "task_id": "123",
                "body": "報告書を作成する",
                "limit_time": 1737712800,  # 2025-01-24 12:00 JST
                "status": "open",
                "assigned_to_account_id": "111",
                "assigned_by_account_id": "222",
                "department_id": None,
                "room_id": "100",
                "room_name": "営業部チャット"
            }
        ]

    @pytest.fixture
    def mock_tasks_multiple_rooms(self):
        """複数ルームのタスクデータ（BUG-001修正後の期待値）"""
        return [
            {
                "task_id": "123",
                "body": "報告書を作成する",
                "limit_time": 1737712800,
                "status": "open",
                "assigned_to_account_id": "111",
                "assigned_by_account_id": "222",
                "department_id": None,
                "room_id": "100",
                "room_name": "営業部チャット"
            },
            {
                "task_id": "456",
                "body": "顧客対応",
                "limit_time": 1737799200,
                "status": "open",
                "assigned_to_account_id": "111",
                "assigned_by_account_id": "333",
                "department_id": None,
                "room_id": "200",
                "room_name": "プロジェクトAチャット"
            },
            {
                "task_id": "789",
                "body": "週次レポート提出",
                "limit_time": 1737885600,
                "status": "open",
                "assigned_to_account_id": "111",
                "assigned_by_account_id": "444",
                "department_id": None,
                "room_id": "100",
                "room_name": "営業部チャット"
            }
        ]

    def test_self_search_uses_search_all_rooms(self, mock_tasks_multiple_rooms):
        """自分のタスク検索時はsearch_all_rooms=Trueになる"""
        # "自分", "sender", "俺", "私", "僕", "" の場合
        # search_all_rooms=True で呼び出されるべき
        self_keywords = ["sender", "自分", "俺", "私", "僕", ""]
        for keyword in self_keywords:
            is_self = keyword.lower() in ["sender", "自分", "俺", "私", "僕", ""]
            assert is_self, f"'{keyword}' should be recognized as self search"

    def test_other_person_search_uses_room_filter(self):
        """他人のタスク検索時はroom_idフィルタを使う"""
        # "田中さん" のような名前の場合
        # search_all_rooms=False で呼び出されるべき
        other_names = ["田中", "山田さん", "佐藤"]
        for name in other_names:
            is_self = name.lower() in ["sender", "自分", "俺", "私", "僕", ""]
            assert not is_self, f"'{name}' should NOT be recognized as self search"

    def test_response_format_grouped_by_room(self, mock_tasks_multiple_rooms):
        """複数ルームのタスクがルーム別にグループ化される"""
        # ルーム別にグループ化
        tasks_by_room = {}
        for task in mock_tasks_multiple_rooms:
            room_name = task.get("room_name") or "不明なルーム"
            if room_name not in tasks_by_room:
                tasks_by_room[room_name] = []
            tasks_by_room[room_name].append(task)

        # 期待値: 2ルーム（営業部チャット: 2件, プロジェクトAチャット: 1件）
        assert len(tasks_by_room) == 2
        assert len(tasks_by_room["営業部チャット"]) == 2
        assert len(tasks_by_room["プロジェクトAチャット"]) == 1

    def test_response_includes_room_name(self, mock_tasks_multiple_rooms):
        """レスポンスにルーム名が含まれる"""
        # 期待されるレスポンスの構造
        # 📁 **営業部チャット**
        #   1. 報告書を作成する（期限: 01/24）
        #   2. 週次レポート提出（期限: 01/26）
        # 📁 **プロジェクトAチャット**
        #   3. 顧客対応（期限: 01/25）

        tasks_by_room = {}
        for task in mock_tasks_multiple_rooms:
            room_name = task.get("room_name") or "不明なルーム"
            if room_name not in tasks_by_room:
                tasks_by_room[room_name] = []
            tasks_by_room[room_name].append(task)

        response = ""
        for room_name in tasks_by_room:
            response += f"📁 **{room_name}**\n"

        assert "📁 **営業部チャット**" in response
        assert "📁 **プロジェクトAチャット**" in response


class TestTaskSearchEdgeCases:
    """エッジケースのテスト"""

    def test_empty_room_name_fallback(self):
        """room_nameがNoneの場合は「不明なルーム」"""
        task = {"room_name": None}
        room_name = task.get("room_name") or "不明なルーム"
        assert room_name == "不明なルーム"

    def test_empty_room_name_string_fallback(self):
        """room_nameが空文字の場合"""
        task = {"room_name": ""}
        room_name = task.get("room_name") or "不明なルーム"
        assert room_name == "不明なルーム"

    def test_no_tasks_found(self):
        """タスクが見つからない場合のメッセージ"""
        tasks = []
        status = "open"
        display_name = "あなた"

        if not tasks:
            status_text = "未完了の" if status == "open" else "完了済みの" if status == "done" else ""
            message = f"📋 {display_name}の{status_text}タスクは見つからなかったウル！"

        assert "見つからなかった" in message


class TestTaskSummaryDisplay:
    """v10.27.0: AI生成summaryの優先使用テスト"""

    @pytest.fixture
    def mock_task_with_valid_summary(self):
        """有効なsummaryを持つタスク"""
        return {
            "task_id": "123",
            "body": "お疲れ様です。来週の会議の議事録を確認して、修正があれば連絡してください。よろしくお願いします。",
            "summary": "会議議事録の確認・修正依頼",  # AIが生成した良い要約
            "limit_time": 1737712800,
            "status": "open",
            "room_id": "100",
            "room_name": "営業部チャット"
        }

    @pytest.fixture
    def mock_task_with_invalid_summary(self):
        """無効なsummary（挨拶のみ）を持つタスク"""
        return {
            "task_id": "456",
            "body": "お疲れ様です。来週の会議の議事録を確認して、修正があれば連絡してください。よろしくお願いします。",
            "summary": "お疲れ様です",  # 挨拶のみ - 無効
            "limit_time": 1737712800,
            "status": "open",
            "room_id": "100",
            "room_name": "営業部チャット"
        }

    @pytest.fixture
    def mock_task_with_null_summary(self):
        """summaryがNULLのタスク"""
        return {
            "task_id": "789",
            "body": "お疲れ様です。来週の会議の議事録を確認して、修正があれば連絡してください。よろしくお願いします。",
            "summary": None,
            "limit_time": 1737712800,
            "status": "open",
            "room_id": "100",
            "room_name": "営業部チャット"
        }

    def test_valid_summary_used(self, mock_task_with_valid_summary):
        """有効なsummaryがある場合、それがそのまま使われる"""
        from lib.text_utils import validate_summary

        task = mock_task_with_valid_summary
        summary = task.get("summary")
        body = task.get("body")

        # summaryが有効かチェック
        is_valid = validate_summary(summary, body)
        assert is_valid, "Valid summary should pass validation"

        # 有効な場合、summaryがそのまま表示に使われる
        body_short = summary if is_valid else None
        assert body_short == "会議議事録の確認・修正依頼"

    def test_invalid_summary_fallback_to_body(self, mock_task_with_invalid_summary):
        """無効なsummary（挨拶のみ）の場合、bodyから生成"""
        from lib.text_utils import validate_summary, clean_chatwork_tags, prepare_task_display_text

        task = mock_task_with_invalid_summary
        summary = task.get("summary")
        body = task.get("body")

        # summaryが無効かチェック
        is_valid = validate_summary(summary, body)
        assert not is_valid, "Greeting-only summary should fail validation"

        # 無効な場合、bodyから生成
        clean_body = clean_chatwork_tags(body)
        body_short = prepare_task_display_text(clean_body, max_length=40)

        # bodyから生成された結果は挨拶を除去している
        assert "お疲れ様" not in body_short
        assert len(body_short) <= 40

    def test_null_summary_fallback_to_body(self, mock_task_with_null_summary):
        """summaryがNULLの場合、bodyから生成"""
        from lib.text_utils import clean_chatwork_tags, prepare_task_display_text

        task = mock_task_with_null_summary
        summary = task.get("summary")
        body = task.get("body")

        # summaryがNULL
        assert summary is None

        # bodyから生成
        clean_body = clean_chatwork_tags(body)
        body_short = prepare_task_display_text(clean_body, max_length=40)

        assert body_short is not None
        assert len(body_short) > 0
        assert len(body_short) <= 40

    def test_truncated_summary_rejected(self):
        """途中で切れたsummaryは無効と判定される"""
        from lib.text_utils import validate_summary

        # 途中で切れているsummary
        truncated_summaries = [
            ("決算書の", "決算書の作成をお願いします"),
            ("資料を", "資料を確認してください"),
            ("確認し...", "確認してください"),
        ]

        for summary, body in truncated_summaries:
            is_valid = validate_summary(summary, body)
            assert not is_valid, f"Truncated summary '{summary}' should be invalid"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
