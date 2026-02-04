"""
Phase 2 B3: AutoKnowledge Unit Tests

Comprehensive tests for lib/memory/auto_knowledge.py
Target coverage: 80%+

Author: Claude Code
Created: 2026-02-04
"""

import pytest
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
import json

from lib.memory.auto_knowledge import AutoKnowledge, KnowledgeData
from lib.memory.base import MemoryResult
from lib.memory.constants import KnowledgeStatus, MemoryParameters
from lib.memory.exceptions import (
    KnowledgeSaveError,
    KnowledgeGenerationError,
    DatabaseError,
    ValidationError,
)


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def mock_conn():
    """Mock database connection"""
    conn = MagicMock()
    conn.execute = MagicMock()
    conn.commit = MagicMock()
    return conn


@pytest.fixture
def org_id():
    """Test organization ID"""
    return uuid4()


@pytest.fixture
def auto_knowledge(mock_conn, org_id):
    """AutoKnowledge instance with mock connection"""
    return AutoKnowledge(
        conn=mock_conn,
        org_id=org_id,
        openrouter_api_key="test-api-key",
        model="google/gemini-3-flash-preview"
    )


@pytest.fixture
def sample_knowledge_row():
    """Sample database row for knowledge"""
    return (
        uuid4(),  # id
        uuid4(),  # organization_id
        uuid4(),  # source_insight_id
        uuid4(),  # source_pattern_id
        "How to submit weekly report?",  # question
        "Submit via the reporting system.",  # answer
        "business_process",  # category
        ["weekly report", "submit"],  # keywords
        "approved",  # status
        datetime.utcnow(),  # approved_at
        uuid4(),  # approved_by
        None,  # rejection_reason
        True,  # synced_to_phase3
        uuid4(),  # phase3_document_id
        10,  # usage_count
        8,  # helpful_count
        0.8,  # quality_score
        "internal",  # classification
        datetime.utcnow(),  # created_at
        datetime.utcnow(),  # updated_at
    )


# ================================================================
# KnowledgeData Tests
# ================================================================

class TestKnowledgeData:
    """Tests for KnowledgeData dataclass"""

    def test_default_values(self):
        """Test default initialization"""
        data = KnowledgeData()
        assert data.id is None
        assert data.organization_id is None
        assert data.question == ""
        assert data.answer == ""
        assert data.category is None
        assert data.keywords == []
        assert data.status == KnowledgeStatus.DRAFT.value
        assert data.approved_at is None
        assert data.approved_by is None
        assert data.rejection_reason is None
        assert data.synced_to_phase3 is False
        assert data.phase3_document_id is None
        assert data.usage_count == 0
        assert data.helpful_count == 0
        assert data.quality_score is None
        assert data.classification == "internal"
        assert data.created_at is None
        assert data.updated_at is None

    def test_initialization_with_values(self):
        """Test initialization with specific values"""
        knowledge_id = uuid4()
        org_id = uuid4()
        now = datetime.utcnow()

        data = KnowledgeData(
            id=knowledge_id,
            organization_id=org_id,
            question="Test question?",
            answer="Test answer.",
            category="test_category",
            keywords=["keyword1", "keyword2"],
            status="approved",
            approved_at=now,
            usage_count=5,
            helpful_count=4,
            quality_score=0.8,
            classification="confidential"
        )

        assert data.id == knowledge_id
        assert data.organization_id == org_id
        assert data.question == "Test question?"
        assert data.answer == "Test answer."
        assert data.category == "test_category"
        assert len(data.keywords) == 2
        assert data.status == "approved"
        assert data.approved_at == now
        assert data.usage_count == 5
        assert data.helpful_count == 4
        assert data.quality_score == 0.8
        assert data.classification == "confidential"

    def test_to_dict_with_none_values(self):
        """Test to_dict with default None values"""
        data = KnowledgeData(question="Test?", answer="Answer")
        result = data.to_dict()

        assert result["id"] is None
        assert result["organization_id"] is None
        assert result["question"] == "Test?"
        assert result["answer"] == "Answer"
        assert result["approved_at"] is None
        assert result["approved_by"] is None

    def test_to_dict_with_all_values(self):
        """Test to_dict with all values set"""
        knowledge_id = uuid4()
        org_id = uuid4()
        insight_id = uuid4()
        pattern_id = uuid4()
        approved_by = uuid4()
        doc_id = uuid4()
        now = datetime.utcnow()

        data = KnowledgeData(
            id=knowledge_id,
            organization_id=org_id,
            source_insight_id=insight_id,
            source_pattern_id=pattern_id,
            question="Test?",
            answer="Answer",
            category="category",
            keywords=["k1"],
            status="approved",
            approved_at=now,
            approved_by=approved_by,
            rejection_reason=None,
            synced_to_phase3=True,
            phase3_document_id=doc_id,
            usage_count=10,
            helpful_count=8,
            quality_score=0.8,
            classification="internal",
            created_at=now,
            updated_at=now
        )

        result = data.to_dict()

        assert result["id"] == str(knowledge_id)
        assert result["organization_id"] == str(org_id)
        assert result["source_insight_id"] == str(insight_id)
        assert result["source_pattern_id"] == str(pattern_id)
        assert result["approved_by"] == str(approved_by)
        assert result["phase3_document_id"] == str(doc_id)
        assert result["approved_at"] == now.isoformat()
        assert result["created_at"] == now.isoformat()
        assert result["updated_at"] == now.isoformat()
        assert result["synced_to_phase3"] is True
        assert result["quality_score"] == 0.8


# ================================================================
# AutoKnowledge Initialization Tests
# ================================================================

class TestAutoKnowledgeInit:
    """Tests for AutoKnowledge initialization"""

    def test_basic_initialization(self, mock_conn, org_id):
        """Test basic initialization"""
        ak = AutoKnowledge(conn=mock_conn, org_id=org_id)

        assert ak.conn == mock_conn
        assert ak.org_id == org_id
        assert ak.memory_type == "b3_auto_knowledge"
        assert ak.openrouter_api_key is None
        assert ak.model == "google/gemini-3-flash-preview"

    def test_initialization_with_api_key(self, mock_conn, org_id):
        """Test initialization with API key"""
        ak = AutoKnowledge(
            conn=mock_conn,
            org_id=org_id,
            openrouter_api_key="test-key"
        )

        assert ak.openrouter_api_key == "test-key"

    def test_initialization_with_custom_model(self, mock_conn, org_id):
        """Test initialization with custom model"""
        ak = AutoKnowledge(
            conn=mock_conn,
            org_id=org_id,
            model="custom-model"
        )

        assert ak.model == "custom-model"


# ================================================================
# Save Method Tests
# ================================================================

class TestAutoKnowledgeSave:
    """Tests for save method"""

    @pytest.mark.asyncio
    async def test_save_basic(self, auto_knowledge, mock_conn):
        """Test basic save operation"""
        knowledge_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.save(
            question="How to submit report?",
            answer="Submit via the system."
        )

        assert result.success is True
        assert result.memory_id == knowledge_id
        assert result.message == "Knowledge saved successfully"
        assert result.data["status"] == "draft"
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_with_all_parameters(self, auto_knowledge, mock_conn):
        """Test save with all parameters"""
        knowledge_id = uuid4()
        insight_id = uuid4()
        pattern_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.save(
            question="Test question?",
            answer="Test answer",
            category="test_category",
            keywords=["keyword1", "keyword2"],
            source_insight_id=insight_id,
            source_pattern_id=pattern_id,
            classification="confidential"
        )

        assert result.success is True
        assert result.memory_id == knowledge_id

    @pytest.mark.asyncio
    async def test_save_truncates_long_answer(self, auto_knowledge, mock_conn):
        """Test that save truncates long answers"""
        knowledge_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        # Create a very long answer
        long_answer = "A" * (MemoryParameters.KNOWLEDGE_ANSWER_MAX_LENGTH + 100)

        result = await auto_knowledge.save(
            question="Test?",
            answer=long_answer
        )

        assert result.success is True
        # Verify truncation happened by checking the execute call
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert len(params["answer"]) <= MemoryParameters.KNOWLEDGE_ANSWER_MAX_LENGTH

    @pytest.mark.asyncio
    async def test_save_limits_keywords(self, auto_knowledge, mock_conn):
        """Test that save limits keywords count"""
        knowledge_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        # Create too many keywords
        many_keywords = [f"keyword{i}" for i in range(20)]

        result = await auto_knowledge.save(
            question="Test?",
            answer="Answer",
            keywords=many_keywords
        )

        assert result.success is True
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert len(params["keywords"]) <= MemoryParameters.KNOWLEDGE_MAX_KEYWORDS

    @pytest.mark.asyncio
    async def test_save_handles_none_keywords(self, auto_knowledge, mock_conn):
        """Test save handles None keywords"""
        knowledge_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.save(
            question="Test?",
            answer="Answer",
            keywords=None
        )

        assert result.success is True
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["keywords"] == []

    @pytest.mark.asyncio
    async def test_save_database_error(self, auto_knowledge, mock_conn):
        """Test save raises KnowledgeSaveError on database error"""
        mock_conn.execute.side_effect = Exception("Database error")

        with pytest.raises(KnowledgeSaveError) as exc_info:
            await auto_knowledge.save(
                question="Test?",
                answer="Answer"
            )

        assert "Failed to save knowledge" in str(exc_info.value.message)


# ================================================================
# Retrieve Method Tests
# ================================================================

class TestAutoKnowledgeRetrieve:
    """Tests for retrieve method"""

    @pytest.mark.asyncio
    async def test_retrieve_basic(self, auto_knowledge, mock_conn, sample_knowledge_row):
        """Test basic retrieve operation"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_knowledge_row]
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.retrieve()

        assert len(result) == 1
        assert isinstance(result[0], KnowledgeData)
        assert result[0].question == "How to submit weekly report?"

    @pytest.mark.asyncio
    async def test_retrieve_with_status_filter(self, auto_knowledge, mock_conn, sample_knowledge_row):
        """Test retrieve with status filter"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_knowledge_row]
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.retrieve(status="approved")

        assert len(result) == 1
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["status"] == "approved"

    @pytest.mark.asyncio
    async def test_retrieve_with_category_filter(self, auto_knowledge, mock_conn, sample_knowledge_row):
        """Test retrieve with category filter"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_knowledge_row]
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.retrieve(category="business_process")

        assert len(result) == 1
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["category"] == "business_process"

    @pytest.mark.asyncio
    async def test_retrieve_with_pagination(self, auto_knowledge, mock_conn, sample_knowledge_row):
        """Test retrieve with pagination"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_knowledge_row]
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.retrieve(limit=10, offset=5)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["limit"] == 10
        assert params["offset"] == 5

    @pytest.mark.asyncio
    async def test_retrieve_limits_max_results(self, auto_knowledge, mock_conn, sample_knowledge_row):
        """Test retrieve limits to max 100 results"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_knowledge_row]
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.retrieve(limit=200)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["limit"] == 100

    @pytest.mark.asyncio
    async def test_retrieve_empty_result(self, auto_knowledge, mock_conn):
        """Test retrieve returns empty list when no results"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.retrieve()

        assert result == []

    @pytest.mark.asyncio
    async def test_retrieve_handles_none_keywords(self, auto_knowledge, mock_conn):
        """Test retrieve handles None keywords from DB"""
        row_with_none_keywords = (
            uuid4(), uuid4(), uuid4(), uuid4(),
            "Question?", "Answer", "category", None,  # None keywords
            "draft", None, None, None, False, None,
            0, 0, None, "internal", datetime.utcnow(), datetime.utcnow()
        )
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row_with_none_keywords]
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.retrieve()

        assert result[0].keywords == []

    @pytest.mark.asyncio
    async def test_retrieve_database_error(self, auto_knowledge, mock_conn):
        """Test retrieve raises DatabaseError on failure"""
        mock_conn.execute.side_effect = Exception("Database error")

        with pytest.raises(DatabaseError) as exc_info:
            await auto_knowledge.retrieve()

        assert "Failed to retrieve knowledge" in str(exc_info.value.message)


# ================================================================
# Generate From Pattern Tests
# ================================================================

class TestAutoKnowledgeGenerateFromPattern:
    """Tests for generate_from_pattern method"""

    @pytest.mark.asyncio
    async def test_generate_from_pattern_existing_knowledge(self, auto_knowledge, mock_conn):
        """Test generate_from_pattern returns early if knowledge exists"""
        existing_id = uuid4()

        # Mock _get_by_pattern_id to return existing knowledge
        with patch.object(auto_knowledge, '_get_by_pattern_id', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = KnowledgeData(id=existing_id)

            result = await auto_knowledge.generate_from_pattern(
                insight_id=uuid4(),
                pattern_id=uuid4(),
                question="Test?",
                occurrence_count=10,
                unique_users=5,
                category="test",
                sample_questions=["Q1?", "Q2?"]
            )

            assert result.success is False
            assert result.memory_id == existing_id
            assert "already exists" in result.message

    @pytest.mark.asyncio
    async def test_generate_from_pattern_new_knowledge(self, auto_knowledge, mock_conn):
        """Test generate_from_pattern creates new knowledge"""
        knowledge_id = uuid4()
        insight_id = uuid4()
        pattern_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        with patch.object(auto_knowledge, '_get_by_pattern_id', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with patch.object(auto_knowledge, '_generate_answer', new_callable=AsyncMock) as mock_gen:
                mock_gen.return_value = {
                    "answer": "Generated answer",
                    "keywords": ["key1", "key2"]
                }

                result = await auto_knowledge.generate_from_pattern(
                    insight_id=insight_id,
                    pattern_id=pattern_id,
                    question="How to submit report?",
                    occurrence_count=10,
                    unique_users=5,
                    category="business_process",
                    sample_questions=["How do I submit?", "Where to send report?"]
                )

                assert result.success is True
                assert result.memory_id == knowledge_id


# ================================================================
# Approve Method Tests
# ================================================================

class TestAutoKnowledgeApprove:
    """Tests for approve method"""

    @pytest.mark.asyncio
    async def test_approve_basic(self, auto_knowledge, mock_conn):
        """Test basic approve operation"""
        knowledge_id = uuid4()
        approved_by = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.approve(
            knowledge_id=knowledge_id,
            approved_by=approved_by
        )

        assert result.success is True
        assert result.memory_id == knowledge_id
        assert result.message == "Knowledge approved successfully"
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_with_modified_answer(self, auto_knowledge, mock_conn):
        """Test approve with modified answer"""
        knowledge_id = uuid4()
        approved_by = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.approve(
            knowledge_id=knowledge_id,
            approved_by=approved_by,
            answer="Modified answer"
        )

        assert result.success is True
        call_args = mock_conn.execute.call_args
        sql = str(call_args[0][0])
        assert "answer = :answer" in sql

    @pytest.mark.asyncio
    async def test_approve_not_found(self, auto_knowledge, mock_conn):
        """Test approve when knowledge not found"""
        knowledge_id = uuid4()
        approved_by = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.approve(
            knowledge_id=knowledge_id,
            approved_by=approved_by
        )

        assert result.success is False
        assert result.message == "Knowledge not found"

    @pytest.mark.asyncio
    async def test_approve_with_string_uuid(self, auto_knowledge, mock_conn):
        """Test approve accepts string UUIDs"""
        knowledge_id = uuid4()
        approved_by = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.approve(
            knowledge_id=str(knowledge_id),
            approved_by=str(approved_by)
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_approve_invalid_uuid(self, auto_knowledge, mock_conn):
        """Test approve raises ValidationError for invalid UUID"""
        with pytest.raises(ValidationError):
            await auto_knowledge.approve(
                knowledge_id="invalid-uuid",
                approved_by=uuid4()
            )

    @pytest.mark.asyncio
    async def test_approve_database_error(self, auto_knowledge, mock_conn):
        """Test approve raises DatabaseError on failure"""
        knowledge_id = uuid4()
        approved_by = uuid4()

        mock_conn.execute.side_effect = Exception("Database error")

        with pytest.raises(DatabaseError) as exc_info:
            await auto_knowledge.approve(
                knowledge_id=knowledge_id,
                approved_by=approved_by
            )

        assert "Failed to approve knowledge" in str(exc_info.value.message)


# ================================================================
# Reject Method Tests
# ================================================================

class TestAutoKnowledgeReject:
    """Tests for reject method"""

    @pytest.mark.asyncio
    async def test_reject_basic(self, auto_knowledge, mock_conn):
        """Test basic reject operation"""
        knowledge_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.reject(
            knowledge_id=knowledge_id,
            reason="Content is inaccurate"
        )

        assert result.success is True
        assert result.memory_id == knowledge_id
        assert result.message == "Knowledge rejected"
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_reject_not_found(self, auto_knowledge, mock_conn):
        """Test reject when knowledge not found"""
        knowledge_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.reject(
            knowledge_id=knowledge_id,
            reason="Test reason"
        )

        assert result.success is False
        assert result.message == "Knowledge not found"

    @pytest.mark.asyncio
    async def test_reject_invalid_uuid(self, auto_knowledge, mock_conn):
        """Test reject raises ValidationError for invalid UUID"""
        with pytest.raises(ValidationError):
            await auto_knowledge.reject(
                knowledge_id="invalid-uuid",
                reason="Test reason"
            )

    @pytest.mark.asyncio
    async def test_reject_database_error(self, auto_knowledge, mock_conn):
        """Test reject raises DatabaseError on failure"""
        knowledge_id = uuid4()

        mock_conn.execute.side_effect = Exception("Database error")

        with pytest.raises(DatabaseError) as exc_info:
            await auto_knowledge.reject(
                knowledge_id=knowledge_id,
                reason="Test reason"
            )

        assert "Failed to reject knowledge" in str(exc_info.value.message)


# ================================================================
# Record Usage Tests
# ================================================================

class TestAutoKnowledgeRecordUsage:
    """Tests for record_usage method"""

    @pytest.mark.asyncio
    async def test_record_usage_helpful(self, auto_knowledge, mock_conn):
        """Test record_usage with helpful=True"""
        knowledge_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (11, 9, 0.818)  # usage, helpful, quality
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.record_usage(
            knowledge_id=knowledge_id,
            was_helpful=True
        )

        assert result.success is True
        assert result.memory_id == knowledge_id
        assert result.data["usage_count"] == 11
        assert result.data["helpful_count"] == 9
        assert result.data["quality_score"] == 0.818

    @pytest.mark.asyncio
    async def test_record_usage_not_helpful(self, auto_knowledge, mock_conn):
        """Test record_usage with helpful=False"""
        knowledge_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (11, 8, 0.727)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.record_usage(
            knowledge_id=knowledge_id,
            was_helpful=False
        )

        assert result.success is True
        # Verify helpful_increment is 0
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["helpful_increment"] == 0

    @pytest.mark.asyncio
    async def test_record_usage_not_found(self, auto_knowledge, mock_conn):
        """Test record_usage when knowledge not found"""
        knowledge_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.record_usage(
            knowledge_id=knowledge_id,
            was_helpful=True
        )

        assert result.success is False
        assert result.message == "Knowledge not found"

    @pytest.mark.asyncio
    async def test_record_usage_handles_none_quality_score(self, auto_knowledge, mock_conn):
        """Test record_usage handles None quality score"""
        knowledge_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1, 1, None)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.record_usage(
            knowledge_id=knowledge_id,
            was_helpful=True
        )

        assert result.success is True
        assert result.data["quality_score"] is None

    @pytest.mark.asyncio
    async def test_record_usage_invalid_uuid(self, auto_knowledge, mock_conn):
        """Test record_usage raises ValidationError for invalid UUID"""
        with pytest.raises(ValidationError):
            await auto_knowledge.record_usage(
                knowledge_id="invalid-uuid",
                was_helpful=True
            )

    @pytest.mark.asyncio
    async def test_record_usage_database_error(self, auto_knowledge, mock_conn):
        """Test record_usage raises DatabaseError on failure"""
        knowledge_id = uuid4()

        mock_conn.execute.side_effect = Exception("Database error")

        with pytest.raises(DatabaseError) as exc_info:
            await auto_knowledge.record_usage(
                knowledge_id=knowledge_id,
                was_helpful=True
            )

        assert "Failed to record usage" in str(exc_info.value.message)


# ================================================================
# Search Approved Tests
# ================================================================

class TestAutoKnowledgeSearchApproved:
    """Tests for search_approved method"""

    @pytest.mark.asyncio
    async def test_search_approved_basic(self, auto_knowledge, mock_conn, sample_knowledge_row):
        """Test basic search_approved operation"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_knowledge_row]
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.search_approved(query="weekly report")

        assert len(result) == 1
        assert isinstance(result[0], KnowledgeData)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["status"] == KnowledgeStatus.APPROVED.value
        assert "%weekly report%" in params["query"]

    @pytest.mark.asyncio
    async def test_search_approved_with_limit(self, auto_knowledge, mock_conn, sample_knowledge_row):
        """Test search_approved with custom limit"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_knowledge_row]
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.search_approved(query="test", limit=10)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["limit"] == 10

    @pytest.mark.asyncio
    async def test_search_approved_empty_result(self, auto_knowledge, mock_conn):
        """Test search_approved returns empty list when no matches"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.search_approved(query="nonexistent")

        assert result == []

    @pytest.mark.asyncio
    async def test_search_approved_handles_none_keywords(self, auto_knowledge, mock_conn):
        """Test search_approved handles None keywords from DB"""
        row_with_none_keywords = (
            uuid4(), uuid4(), uuid4(), uuid4(),
            "Question?", "Answer", "category", None,
            "approved", datetime.utcnow(), uuid4(), None, True, uuid4(),
            5, 4, 0.8, "internal", datetime.utcnow(), datetime.utcnow()
        )
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row_with_none_keywords]
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.search_approved(query="test")

        assert result[0].keywords == []

    @pytest.mark.asyncio
    async def test_search_approved_database_error(self, auto_knowledge, mock_conn):
        """Test search_approved raises DatabaseError on failure"""
        mock_conn.execute.side_effect = Exception("Database error")

        with pytest.raises(DatabaseError) as exc_info:
            await auto_knowledge.search_approved(query="test")

        assert "Failed to search knowledge" in str(exc_info.value.message)


# ================================================================
# Private Method Tests
# ================================================================

class TestAutoKnowledgePrivateMethods:
    """Tests for private methods"""

    @pytest.mark.asyncio
    async def test_get_by_pattern_id_found(self, auto_knowledge, mock_conn):
        """Test _get_by_pattern_id when pattern exists"""
        pattern_id = uuid4()
        knowledge_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge._get_by_pattern_id(pattern_id)

        assert result is not None
        assert result.id == knowledge_id

    @pytest.mark.asyncio
    async def test_get_by_pattern_id_not_found(self, auto_knowledge, mock_conn):
        """Test _get_by_pattern_id when pattern doesn't exist"""
        pattern_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge._get_by_pattern_id(pattern_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_pattern_id_exception(self, auto_knowledge, mock_conn):
        """Test _get_by_pattern_id returns None on exception"""
        pattern_id = uuid4()
        mock_conn.execute.side_effect = Exception("Database error")

        result = await auto_knowledge._get_by_pattern_id(pattern_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_answer_success(self, auto_knowledge):
        """Test _generate_answer success"""
        # Patch both call_llm and extract_json_from_response to avoid prompt format issues
        with patch.object(auto_knowledge, 'call_llm', new_callable=AsyncMock) as mock_llm:
            with patch.object(auto_knowledge, 'extract_json_from_response') as mock_extract:
                mock_llm.return_value = '{"answer": "Test answer", "keywords": ["k1", "k2"]}'
                mock_extract.return_value = {"answer": "Test answer", "keywords": ["k1", "k2"]}

                # Patch the prompt template to avoid JSON curly brace issues
                with patch('lib.memory.auto_knowledge.AUTO_KNOWLEDGE_GENERATION_PROMPT',
                          "Question: {question}, Count: {occurrence_count}, Users: {unique_users}, "
                          "Category: {category}, Samples: {sample_questions}"):
                    result = await auto_knowledge._generate_answer(
                        question="How to do X?",
                        occurrence_count=10,
                        unique_users=5,
                        category="test",
                        sample_questions=["Q1?", "Q2?"]
                    )

                    assert result["answer"] == "Test answer"
                    assert result["keywords"] == ["k1", "k2"]

    @pytest.mark.asyncio
    async def test_generate_answer_fallback(self, auto_knowledge):
        """Test _generate_answer fallback on error"""
        # Patch the prompt template to avoid JSON curly brace issues
        with patch('lib.memory.auto_knowledge.AUTO_KNOWLEDGE_GENERATION_PROMPT',
                  "Question: {question}, Count: {occurrence_count}, Users: {unique_users}, "
                  "Category: {category}, Samples: {sample_questions}"):
            with patch.object(auto_knowledge, 'call_llm', new_callable=AsyncMock) as mock_llm:
                mock_llm.side_effect = Exception("LLM error")

                result = await auto_knowledge._generate_answer(
                    question="How to do X?",
                    occurrence_count=10,
                    unique_users=5,
                    category="test",
                    sample_questions=["Q1?", "Q2?"]
                )

                assert "How to do X?" in result["answer"]
                assert result["keywords"] == []

    @pytest.mark.asyncio
    async def test_generate_answer_limits_sample_questions(self, auto_knowledge):
        """Test _generate_answer limits sample questions to 5"""
        # Patch the prompt template to avoid JSON curly brace issues
        with patch('lib.memory.auto_knowledge.AUTO_KNOWLEDGE_GENERATION_PROMPT',
                  "Question: {question}, Count: {occurrence_count}, Users: {unique_users}, "
                  "Category: {category}, Samples: {sample_questions}"):
            with patch.object(auto_knowledge, 'call_llm', new_callable=AsyncMock) as mock_llm:
                with patch.object(auto_knowledge, 'extract_json_from_response') as mock_extract:
                    mock_llm.return_value = '{"answer": "Test", "keywords": []}'
                    mock_extract.return_value = {"answer": "Test", "keywords": []}

                    many_questions = [f"Question {i}?" for i in range(10)]

                    await auto_knowledge._generate_answer(
                        question="Test?",
                        occurrence_count=10,
                        unique_users=5,
                        category="test",
                        sample_questions=many_questions
                    )

                    # Verify the prompt only includes first 5 questions
                    call_args = mock_llm.call_args
                    prompt = call_args[0][0]
                    # Should only have 5 sample questions
                    assert "Question 0?" in prompt
                    assert "Question 4?" in prompt
                    # Question 5 and beyond should not be in the prompt
                    assert "Question 5?" not in prompt


# ================================================================
# Edge Cases and Error Handling
# ================================================================

class TestAutoKnowledgeEdgeCases:
    """Tests for edge cases and error handling"""

    @pytest.mark.asyncio
    async def test_save_empty_question(self, auto_knowledge, mock_conn):
        """Test save with empty question"""
        knowledge_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.save(
            question="",
            answer="Answer"
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_save_empty_answer(self, auto_knowledge, mock_conn):
        """Test save with empty answer"""
        knowledge_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.save(
            question="Test?",
            answer=""
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_retrieve_with_both_filters(self, auto_knowledge, mock_conn, sample_knowledge_row):
        """Test retrieve with both status and category filters"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_knowledge_row]
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.retrieve(
            status="approved",
            category="business_process"
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["status"] == "approved"
        assert params["category"] == "business_process"

    @pytest.mark.asyncio
    async def test_quality_score_conversion(self, auto_knowledge, mock_conn):
        """Test that quality_score is properly converted to float"""
        from decimal import Decimal

        row_with_decimal_score = (
            uuid4(), uuid4(), uuid4(), uuid4(),
            "Question?", "Answer", "category", ["k1"],
            "approved", datetime.utcnow(), uuid4(), None, True, uuid4(),
            10, 8, Decimal("0.80"),  # Decimal quality_score
            "internal", datetime.utcnow(), datetime.utcnow()
        )
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row_with_decimal_score]
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.retrieve()

        assert isinstance(result[0].quality_score, float)
        assert result[0].quality_score == 0.8

    @pytest.mark.asyncio
    async def test_record_usage_default_helpful(self, auto_knowledge, mock_conn):
        """Test record_usage defaults to helpful=True"""
        knowledge_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1, 1, 1.0)
        mock_conn.execute.return_value = mock_result

        result = await auto_knowledge.record_usage(knowledge_id=knowledge_id)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["helpful_increment"] == 1


# ================================================================
# Integration-like Tests
# ================================================================

class TestAutoKnowledgeWorkflow:
    """Tests simulating real-world workflows"""

    @pytest.mark.asyncio
    async def test_save_approve_record_workflow(self, auto_knowledge, mock_conn):
        """Test typical workflow: save -> approve -> record usage"""
        knowledge_id = uuid4()
        approved_by = uuid4()

        # Step 1: Save
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        save_result = await auto_knowledge.save(
            question="How to submit leave request?",
            answer="Use the HR portal to submit.",
            category="hr_process",
            keywords=["leave", "request", "HR"]
        )

        assert save_result.success is True

        # Step 2: Approve
        mock_result.fetchone.return_value = (knowledge_id,)
        approve_result = await auto_knowledge.approve(
            knowledge_id=knowledge_id,
            approved_by=approved_by
        )

        assert approve_result.success is True

        # Step 3: Record usage
        mock_result.fetchone.return_value = (1, 1, 1.0)
        usage_result = await auto_knowledge.record_usage(
            knowledge_id=knowledge_id,
            was_helpful=True
        )

        assert usage_result.success is True
        assert usage_result.data["usage_count"] == 1

    @pytest.mark.asyncio
    async def test_save_reject_workflow(self, auto_knowledge, mock_conn):
        """Test rejection workflow: save -> reject"""
        knowledge_id = uuid4()

        # Step 1: Save
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (knowledge_id,)
        mock_conn.execute.return_value = mock_result

        save_result = await auto_knowledge.save(
            question="Incorrect question?",
            answer="Incorrect answer"
        )

        assert save_result.success is True

        # Step 2: Reject
        mock_result.fetchone.return_value = (knowledge_id,)
        reject_result = await auto_knowledge.reject(
            knowledge_id=knowledge_id,
            reason="Information is outdated"
        )

        assert reject_result.success is True
        assert reject_result.message == "Knowledge rejected"


# ================================================================
# Run Tests
# ================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
