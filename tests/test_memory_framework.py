"""
Phase 2 B: 記憶基盤（Memory Framework）テスト

B1〜B4の記憶機能をテストします。
目標: 80件以上のテストケース

Author: Claude Code
Created: 2026-01-24
"""

import pytest
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from decimal import Decimal
import json


# ================================================================
# 定数テスト
# ================================================================

class TestMemoryParameters:
    """MemoryParametersのテスト"""

    def test_summary_trigger_count_default(self):
        from lib.memory.constants import MemoryParameters
        assert MemoryParameters.SUMMARY_TRIGGER_COUNT == 10

    def test_summary_max_length_default(self):
        from lib.memory.constants import MemoryParameters
        assert MemoryParameters.SUMMARY_MAX_LENGTH == 500

    def test_summary_retention_days_default(self):
        from lib.memory.constants import MemoryParameters
        assert MemoryParameters.SUMMARY_RETENTION_DAYS == 90

    def test_preference_initial_confidence_default(self):
        from lib.memory.constants import MemoryParameters
        assert MemoryParameters.PREFERENCE_INITIAL_CONFIDENCE == 0.5

    def test_preference_max_confidence_default(self):
        from lib.memory.constants import MemoryParameters
        assert MemoryParameters.PREFERENCE_MAX_CONFIDENCE == 0.95

    def test_knowledge_auto_generate_threshold(self):
        from lib.memory.constants import MemoryParameters
        assert MemoryParameters.KNOWLEDGE_AUTO_GENERATE_THRESHOLD == 5

    def test_search_default_limit(self):
        from lib.memory.constants import MemoryParameters
        assert MemoryParameters.SEARCH_DEFAULT_LIMIT == 10

    def test_search_max_limit(self):
        from lib.memory.constants import MemoryParameters
        assert MemoryParameters.SEARCH_MAX_LIMIT == 100


class TestPreferenceType:
    """PreferenceTypeのテスト"""

    def test_response_style_value(self):
        from lib.memory.constants import PreferenceType
        assert PreferenceType.RESPONSE_STYLE.value == "response_style"

    def test_feature_usage_value(self):
        from lib.memory.constants import PreferenceType
        assert PreferenceType.FEATURE_USAGE.value == "feature_usage"

    def test_communication_value(self):
        from lib.memory.constants import PreferenceType
        assert PreferenceType.COMMUNICATION.value == "communication"

    def test_schedule_value(self):
        from lib.memory.constants import PreferenceType
        assert PreferenceType.SCHEDULE.value == "schedule"

    def test_emotion_trend_value(self):
        from lib.memory.constants import PreferenceType
        assert PreferenceType.EMOTION_TREND.value == "emotion_trend"

    def test_all_preference_types_count(self):
        from lib.memory.constants import PreferenceType
        assert len(PreferenceType) == 5


class TestKnowledgeStatus:
    """KnowledgeStatusのテスト"""

    def test_draft_value(self):
        from lib.memory.constants import KnowledgeStatus
        assert KnowledgeStatus.DRAFT.value == "draft"

    def test_approved_value(self):
        from lib.memory.constants import KnowledgeStatus
        assert KnowledgeStatus.APPROVED.value == "approved"

    def test_rejected_value(self):
        from lib.memory.constants import KnowledgeStatus
        assert KnowledgeStatus.REJECTED.value == "rejected"

    def test_archived_value(self):
        from lib.memory.constants import KnowledgeStatus
        assert KnowledgeStatus.ARCHIVED.value == "archived"


class TestMessageType:
    """MessageTypeのテスト"""

    def test_user_value(self):
        from lib.memory.constants import MessageType
        assert MessageType.USER.value == "user"

    def test_assistant_value(self):
        from lib.memory.constants import MessageType
        assert MessageType.ASSISTANT.value == "assistant"


class TestLearnedFrom:
    """LearnedFromのテスト"""

    def test_auto_value(self):
        from lib.memory.constants import LearnedFrom
        assert LearnedFrom.AUTO.value == "auto"

    def test_explicit_value(self):
        from lib.memory.constants import LearnedFrom
        assert LearnedFrom.EXPLICIT.value == "explicit"

    def test_a4_emotion_value(self):
        from lib.memory.constants import LearnedFrom
        assert LearnedFrom.A4_EMOTION.value == "a4_emotion"


# ================================================================
# 例外テスト
# ================================================================

class TestMemoryExceptions:
    """例外クラスのテスト"""

    def test_memory_base_exception_message(self):
        from lib.memory.exceptions import MemoryBaseException
        exc = MemoryBaseException("Test error")
        assert exc.message == "Test error"

    def test_memory_base_exception_error_code(self):
        from lib.memory.exceptions import MemoryBaseException
        exc = MemoryBaseException("Test", error_code="TEST_ERROR")
        assert exc.error_code == "TEST_ERROR"

    def test_memory_base_exception_to_dict(self):
        from lib.memory.exceptions import MemoryBaseException
        exc = MemoryBaseException("Test error", error_code="TEST", details={"key": "value"})
        result = exc.to_dict()
        assert result["error"] == "TEST"
        assert result["message"] == "Test error"
        assert result["details"]["key"] == "value"

    def test_summary_save_error(self):
        from lib.memory.exceptions import SummarySaveError
        exc = SummarySaveError("Save failed", user_id="user123")
        assert exc.error_code == "SUMMARY_SAVE_ERROR"
        assert exc.details["user_id"] == "user123"

    def test_preference_save_error(self):
        from lib.memory.exceptions import PreferenceSaveError
        exc = PreferenceSaveError("Save failed", user_id="user123", preference_type="style")
        assert exc.error_code == "PREFERENCE_SAVE_ERROR"
        assert exc.details["preference_type"] == "style"

    def test_knowledge_save_error(self):
        from lib.memory.exceptions import KnowledgeSaveError
        exc = KnowledgeSaveError("Save failed", source_id="source123")
        assert exc.error_code == "KNOWLEDGE_SAVE_ERROR"
        assert exc.details["source_id"] == "source123"

    def test_search_error(self):
        from lib.memory.exceptions import SearchError
        exc = SearchError("Search failed", query="test query")
        assert exc.error_code == "SEARCH_ERROR"
        assert exc.details["query"] == "test query"

    def test_database_error(self):
        from lib.memory.exceptions import DatabaseError
        original = ValueError("Original error")
        exc = DatabaseError("DB error", original_error=original)
        assert exc.error_code == "DATABASE_ERROR"
        assert "Original error" in exc.details["original_error"]

    def test_validation_error(self):
        from lib.memory.exceptions import ValidationError
        exc = ValidationError("Invalid value", field="user_id")
        assert exc.error_code == "VALIDATION_ERROR"
        assert exc.details["field"] == "user_id"

    def test_llm_error(self):
        from lib.memory.exceptions import LLMError
        exc = LLMError("LLM failed", model="gpt-4")
        assert exc.error_code == "LLM_ERROR"
        assert exc.details["model"] == "gpt-4"


# ================================================================
# データクラステスト
# ================================================================

class TestMemoryResult:
    """MemoryResultのテスト"""

    def test_success_result(self):
        from lib.memory.base import MemoryResult
        result = MemoryResult(success=True, message="OK")
        assert result.success is True
        assert result.message == "OK"

    def test_failure_result(self):
        from lib.memory.base import MemoryResult
        result = MemoryResult(success=False, error="Failed")
        assert result.success is False
        assert result.error == "Failed"

    def test_result_with_memory_id(self):
        from lib.memory.base import MemoryResult
        memory_id = uuid4()
        result = MemoryResult(success=True, memory_id=memory_id)
        assert result.memory_id == memory_id

    def test_result_to_dict(self):
        from lib.memory.base import MemoryResult
        memory_id = uuid4()
        result = MemoryResult(
            success=True,
            memory_id=memory_id,
            message="OK",
            data={"key": "value"}
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["memory_id"] == str(memory_id)
        assert d["data"]["key"] == "value"


class TestSummaryData:
    """SummaryDataのテスト"""

    def test_summary_data_defaults(self):
        from lib.memory.conversation_summary import SummaryData
        data = SummaryData()
        assert data.summary_text == ""
        assert data.key_topics == []
        assert data.message_count == 0

    def test_summary_data_with_values(self):
        from lib.memory.conversation_summary import SummaryData
        now = datetime.utcnow()
        data = SummaryData(
            summary_text="Test summary",
            key_topics=["topic1", "topic2"],
            message_count=10,
            conversation_start=now,
            conversation_end=now
        )
        assert data.summary_text == "Test summary"
        assert len(data.key_topics) == 2
        assert data.message_count == 10

    def test_summary_data_to_dict(self):
        from lib.memory.conversation_summary import SummaryData
        user_id = uuid4()
        data = SummaryData(
            user_id=user_id,
            summary_text="Test",
            key_topics=["topic1"]
        )
        d = data.to_dict()
        assert d["user_id"] == str(user_id)
        assert d["summary_text"] == "Test"


class TestPreferenceData:
    """PreferenceDataのテスト"""

    def test_preference_data_defaults(self):
        from lib.memory.user_preference import PreferenceData
        data = PreferenceData()
        assert data.preference_type == ""
        assert data.confidence == 0.5
        assert data.sample_count == 1

    def test_preference_data_with_values(self):
        from lib.memory.user_preference import PreferenceData
        data = PreferenceData(
            preference_type="response_style",
            preference_key="length",
            preference_value={"preference": "detailed"},
            confidence=0.8
        )
        assert data.preference_type == "response_style"
        assert data.confidence == 0.8

    def test_preference_data_to_dict(self):
        from lib.memory.user_preference import PreferenceData
        data = PreferenceData(
            preference_type="feature_usage",
            preference_key="task_create",
            preference_value={"count": 5}
        )
        d = data.to_dict()
        assert d["preference_type"] == "feature_usage"
        assert d["preference_value"]["count"] == 5


class TestKnowledgeData:
    """KnowledgeDataのテスト"""

    def test_knowledge_data_defaults(self):
        from lib.memory.auto_knowledge import KnowledgeData
        data = KnowledgeData()
        assert data.question == ""
        assert data.answer == ""
        assert data.status == "draft"
        assert data.usage_count == 0

    def test_knowledge_data_with_values(self):
        from lib.memory.auto_knowledge import KnowledgeData
        data = KnowledgeData(
            question="週報の出し方は？",
            answer="週報は〇〇から提出できます。",
            category="business_process",
            keywords=["週報", "提出"]
        )
        assert data.question == "週報の出し方は？"
        assert len(data.keywords) == 2

    def test_knowledge_data_to_dict(self):
        from lib.memory.auto_knowledge import KnowledgeData
        data = KnowledgeData(
            question="テスト質問",
            answer="テスト回答",
            status="approved"
        )
        d = data.to_dict()
        assert d["status"] == "approved"


class TestSearchResult:
    """SearchResultのテスト"""

    def test_search_result_defaults(self):
        from lib.memory.conversation_search import SearchResult
        data = SearchResult()
        assert data.message_text == ""
        assert data.message_type == "user"
        assert data.keywords == []
        assert data.context == []

    def test_search_result_with_values(self):
        from lib.memory.conversation_search import SearchResult
        now = datetime.utcnow()
        data = SearchResult(
            message_text="Test message",
            message_type="assistant",
            keywords=["keyword1"],
            message_time=now
        )
        assert data.message_text == "Test message"
        assert data.message_type == "assistant"

    def test_search_result_to_dict(self):
        from lib.memory.conversation_search import SearchResult
        data = SearchResult(
            message_text="Test",
            room_id="room123"
        )
        d = data.to_dict()
        assert d["room_id"] == "room123"


# ================================================================
# 基底クラステスト
# ================================================================

class TestBaseMemory:
    """BaseMemoryのテスト"""

    def test_validate_uuid_with_valid_uuid(self):
        from lib.memory.base import BaseMemory
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        memory = type('TestMemory', (BaseMemory,), {
            'save': lambda self, **kwargs: None,
            'retrieve': lambda self, **kwargs: []
        })(conn, org_id)

        valid_uuid = uuid4()
        result = memory.validate_uuid(valid_uuid)
        assert result == valid_uuid

    def test_validate_uuid_with_string(self):
        from lib.memory.base import BaseMemory
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        memory = type('TestMemory', (BaseMemory,), {
            'save': lambda self, **kwargs: None,
            'retrieve': lambda self, **kwargs: []
        })(conn, org_id)

        uuid_str = str(uuid4())
        result = memory.validate_uuid(uuid_str)
        assert isinstance(result, UUID)

    def test_validate_uuid_with_invalid_string(self):
        from lib.memory.base import BaseMemory
        from lib.memory.exceptions import ValidationError
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        memory = type('TestMemory', (BaseMemory,), {
            'save': lambda self, **kwargs: None,
            'retrieve': lambda self, **kwargs: []
        })(conn, org_id)

        with pytest.raises(ValidationError):
            memory.validate_uuid("invalid-uuid")

    def test_truncate_text_short(self):
        from lib.memory.base import BaseMemory
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        memory = type('TestMemory', (BaseMemory,), {
            'save': lambda self, **kwargs: None,
            'retrieve': lambda self, **kwargs: []
        })(conn, org_id)

        text = "Short text"
        result = memory.truncate_text(text, 100)
        assert result == "Short text"

    def test_truncate_text_long(self):
        from lib.memory.base import BaseMemory
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        memory = type('TestMemory', (BaseMemory,), {
            'save': lambda self, **kwargs: None,
            'retrieve': lambda self, **kwargs: []
        })(conn, org_id)

        text = "A" * 100
        result = memory.truncate_text(text, 50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_extract_json_from_response_code_block(self):
        from lib.memory.base import BaseMemory
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        memory = type('TestMemory', (BaseMemory,), {
            'save': lambda self, **kwargs: None,
            'retrieve': lambda self, **kwargs: []
        })(conn, org_id)

        response = '```json\n{"key": "value"}\n```'
        result = memory.extract_json_from_response(response)
        assert result["key"] == "value"

    def test_extract_json_from_response_direct(self):
        from lib.memory.base import BaseMemory
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        memory = type('TestMemory', (BaseMemory,), {
            'save': lambda self, **kwargs: None,
            'retrieve': lambda self, **kwargs: []
        })(conn, org_id)

        response = '{"key": "value"}'
        result = memory.extract_json_from_response(response)
        assert result["key"] == "value"

    def test_extract_json_from_response_invalid(self):
        from lib.memory.base import BaseMemory
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        memory = type('TestMemory', (BaseMemory,), {
            'save': lambda self, **kwargs: None,
            'retrieve': lambda self, **kwargs: []
        })(conn, org_id)

        response = "No JSON here"
        with pytest.raises(ValueError):
            memory.extract_json_from_response(response)


# ================================================================
# プロンプトテンプレートテスト
# ================================================================

class TestPromptTemplates:
    """プロンプトテンプレートのテスト"""

    def test_conversation_summary_prompt_has_placeholder(self):
        from lib.memory.constants import CONVERSATION_SUMMARY_PROMPT
        assert "{conversation_history}" in CONVERSATION_SUMMARY_PROMPT

    def test_auto_knowledge_prompt_has_placeholders(self):
        from lib.memory.constants import AUTO_KNOWLEDGE_GENERATION_PROMPT
        assert "{question}" in AUTO_KNOWLEDGE_GENERATION_PROMPT
        assert "{occurrence_count}" in AUTO_KNOWLEDGE_GENERATION_PROMPT
        assert "{category}" in AUTO_KNOWLEDGE_GENERATION_PROMPT

    def test_keyword_extraction_prompt_has_placeholder(self):
        from lib.memory.constants import KEYWORD_EXTRACTION_PROMPT
        assert "{message}" in KEYWORD_EXTRACTION_PROMPT


# ================================================================
# 会話検索テスト（シンプルキーワード抽出）
# ================================================================

class TestSimpleKeywordExtraction:
    """シンプルキーワード抽出のテスト"""

    def test_extract_katakana(self):
        from lib.memory.conversation_search import ConversationSearch
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        search = ConversationSearch(conn, org_id)

        result = search._simple_keyword_extraction("タスクを確認してください")
        assert "タスク" in result["keywords"]

    def test_extract_business_terms(self):
        from lib.memory.conversation_search import ConversationSearch
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        search = ConversationSearch(conn, org_id)

        result = search._simple_keyword_extraction("週報を提出して承認をもらってください")
        assert "週報" in result["keywords"]
        assert "承認" in result["keywords"]

    def test_extract_kanji_words(self):
        from lib.memory.conversation_search import ConversationSearch
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        search = ConversationSearch(conn, org_id)

        result = search._simple_keyword_extraction("有給休暇を申請します")
        assert any("有給" in k for k in result["keywords"])

    def test_extract_empty_message(self):
        from lib.memory.conversation_search import ConversationSearch
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        search = ConversationSearch(conn, org_id)

        result = search._simple_keyword_extraction("")
        assert result["keywords"] == []


# ================================================================
# エクスポートテスト
# ================================================================

class TestModuleExports:
    """モジュールエクスポートのテスト"""

    def test_import_memory_parameters(self):
        from lib.memory import MemoryParameters
        assert hasattr(MemoryParameters, "SUMMARY_TRIGGER_COUNT")

    def test_import_preference_type(self):
        from lib.memory import PreferenceType
        assert hasattr(PreferenceType, "RESPONSE_STYLE")

    def test_import_knowledge_status(self):
        from lib.memory import KnowledgeStatus
        assert hasattr(KnowledgeStatus, "DRAFT")

    def test_import_message_type(self):
        from lib.memory import MessageType
        assert hasattr(MessageType, "USER")

    def test_import_memory_result(self):
        from lib.memory import MemoryResult
        result = MemoryResult(success=True)
        assert result.success

    def test_import_conversation_summary(self):
        from lib.memory import ConversationSummary
        assert ConversationSummary is not None

    def test_import_user_preference(self):
        from lib.memory import UserPreference
        assert UserPreference is not None

    def test_import_auto_knowledge(self):
        from lib.memory import AutoKnowledge
        assert AutoKnowledge is not None

    def test_import_conversation_search(self):
        from lib.memory import ConversationSearch
        assert ConversationSearch is not None

    def test_import_summary_data(self):
        from lib.memory import SummaryData
        assert SummaryData is not None

    def test_import_preference_data(self):
        from lib.memory import PreferenceData
        assert PreferenceData is not None

    def test_import_knowledge_data(self):
        from lib.memory import KnowledgeData
        assert KnowledgeData is not None

    def test_import_search_result(self):
        from lib.memory import SearchResult
        assert SearchResult is not None

    def test_import_exceptions(self):
        from lib.memory import (
            MemoryBaseException,
            MemoryError,
            SummarySaveError,
            PreferenceSaveError,
            KnowledgeSaveError,
            SearchError,
        )
        assert all([
            MemoryBaseException,
            MemoryError,
            SummarySaveError,
            PreferenceSaveError,
            KnowledgeSaveError,
            SearchError,
        ])


# ================================================================
# バージョン情報テスト
# ================================================================

class TestVersionInfo:
    """バージョン情報のテスト"""

    def test_version_defined(self):
        from lib.memory import __version__
        assert __version__ == "1.0.0"

    def test_author_defined(self):
        from lib.memory import __author__
        assert __author__ == "Claude Code"


# ================================================================
# 統合テスト（モック使用）
# ================================================================

class TestConversationSummaryIntegration:
    """ConversationSummaryの統合テスト"""

    def test_format_conversation_history(self):
        from lib.memory.conversation_summary import ConversationSummary
        from unittest.mock import MagicMock

        conn = MagicMock()
        org_id = uuid4()
        summary = ConversationSummary(conn, org_id)

        history = [
            {"role": "user", "content": "こんにちは"},
            {"role": "assistant", "content": "お疲れ様です"}
        ]
        result = summary._format_conversation_history(history)
        assert "user: こんにちは" in result
        assert "assistant: お疲れ様です" in result


class TestUserPreferenceValidation:
    """UserPreferenceのバリデーションテスト"""

    def test_invalid_preference_type(self):
        from lib.memory.user_preference import UserPreference
        from lib.memory.exceptions import ValidationError
        from unittest.mock import MagicMock
        import asyncio

        conn = MagicMock()
        org_id = uuid4()
        pref = UserPreference(conn, org_id)

        async def test():
            with pytest.raises(ValidationError):
                await pref.save(
                    user_id=uuid4(),
                    preference_type="invalid_type",
                    preference_key="test",
                    preference_value="value"
                )

        asyncio.run(test())


# ================================================================
# 実行
# ================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
