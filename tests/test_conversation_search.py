"""
lib/memory/conversation_search.py のテスト

対象:
- SearchResult.to_dict
- save/retrieve/search/batch_index/cleanup_old_index
- _simple_keyword_extraction
- _get_context
"""

import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from lib.memory.conversation_search import ConversationSearch, SearchResult
from lib.memory.constants import MessageType
from lib.memory.exceptions import ValidationError, SearchError


class TestSearchResult:
    def test_to_dict_serializes_ids_and_time(self):
        now = datetime(2026, 2, 2, 12, 0, 0)
        result = SearchResult(
            id=None,
            organization_id=None,
            user_id=None,
            message_id="m1",
            room_id="r1",
            message_text="hello",
            message_type=MessageType.USER.value,
            keywords=["タスク"],
            entities={"k": "v"},
            message_time=now,
            classification="internal",
            context=[],
        )
        payload = result.to_dict()
        assert payload["message_id"] == "m1"
        assert payload["message_time"] == now.isoformat()
        assert payload["keywords"] == ["タスク"]


class TestConversationSearchSave:
    @pytest.mark.asyncio
    async def test_save_defaults_invalid_message_type(self):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("id-1",)
        mock_conn.execute.return_value = mock_result

        search = ConversationSearch(conn=mock_conn, org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)

        result = await search.save(
            user_id="22222222-2222-2222-2222-222222222222",
            message_text="hello",
            message_type="invalid",
            message_time=datetime.utcnow(),
        )

        assert result.success is True
        assert result.data["keywords"] == []
        # message_type が USER に丸められることを確認
        args, kwargs = mock_conn.execute.call_args
        params = args[1] if len(args) > 1 else kwargs
        assert params["message_type"] == MessageType.USER.value
        mock_conn.commit.assert_called_once()


class TestConversationSearchRetrieve:
    @pytest.mark.asyncio
    async def test_retrieve_parses_entities_json(self):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (
                "id-1",
                "org-1",
                "user-1",
                "m1",
                "room-1",
                "text",
                MessageType.USER.value,
                ["タスク"],
                '{"a": 1}',
                datetime(2026, 2, 2, 10, 0, 0),
                "internal",
            )
        ]
        mock_conn.execute.return_value = mock_result

        search = ConversationSearch(conn=mock_conn, org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)
        results = await search.retrieve(user_id="22222222-2222-2222-2222-222222222222", limit=5)

        assert len(results) == 1
        assert results[0].entities == {"a": 1}
        assert results[0].keywords == ["タスク"]


class TestConversationSearchSearch:
    @pytest.mark.asyncio
    async def test_search_with_context(self, monkeypatch):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (
                "id-1",
                "org-1",
                "user-1",
                "m1",
                "room-1",
                "text",
                MessageType.USER.value,
                ["タスク"],
                {"a": 1},
                datetime(2026, 2, 2, 10, 0, 0),
                "internal",
            )
        ]
        mock_conn.execute.return_value = mock_result

        search = ConversationSearch(conn=mock_conn, org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)

        async def fake_context(*args, **kwargs):
            return [{"message_text": "before"}, {"message_text": "after"}]

        monkeypatch.setattr(search, "_get_context", fake_context)

        results = await search.search(query="タスク", user_id="22222222-2222-2222-2222-222222222222", include_context=True)
        assert results[0].context
        assert results[0].context[0]["message_text"] == "before"

    @pytest.mark.asyncio
    async def test_search_invalid_uuid_raises(self):
        search = ConversationSearch(conn=MagicMock(), org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)
        with pytest.raises(ValidationError):
            await search.search(query="x", user_id="not-a-uuid")


class TestConversationSearchBatchAndCleanup:
    @pytest.mark.asyncio
    async def test_batch_index_counts_success(self, monkeypatch):
        search = ConversationSearch(conn=MagicMock(), org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)

        async def fake_save(*args, **kwargs):
            return SimpleNamespace(success=True)

        monkeypatch.setattr(search, "save", fake_save)

        count = await search.batch_index(
            user_id="22222222-2222-2222-2222-222222222222",
            messages=[
                {"content": "a", "timestamp": datetime.utcnow()},
                {"message": "b", "created_at": datetime.utcnow()},
            ],
        )
        assert count == 2

    @pytest.mark.asyncio
    async def test_cleanup_old_index_commits(self):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_conn.execute.return_value = mock_result

        search = ConversationSearch(conn=mock_conn, org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)
        deleted = await search.cleanup_old_index(retention_days=30)

        assert deleted == 3
        mock_conn.commit.assert_called_once()


class TestConversationSearchKeywords:
    def test_simple_keyword_extraction(self):
        search = ConversationSearch(conn=MagicMock(), org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)
        result = search._simple_keyword_extraction("週報のタスクを確認して")

        assert "週報" in result["keywords"]
        assert "タスク" in result["keywords"]
