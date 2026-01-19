"""
api/app/services/knowledge_search.py のテスト

ナレッジ検索サービスのユニットテスト
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from api.app.services.knowledge_search import (
    KnowledgeSearchService,
    UserContext,
)
from api.app.schemas.knowledge import (
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeFeedbackRequest,
    KnowledgeFeedbackResponse,
)
from lib.pinecone_client import SearchResult, SearchResponse


class TestUserContext:
    """UserContext のテスト"""

    def test_default_classifications(self):
        """デフォルトの機密区分"""
        ctx = UserContext(
            user_id="user1",
            organization_id="org1",
        )

        assert "public" in ctx.accessible_classifications
        assert "internal" in ctx.accessible_classifications
        assert len(ctx.accessible_department_ids) == 0

    def test_custom_classifications(self):
        """カスタム機密区分"""
        ctx = UserContext(
            user_id="user1",
            organization_id="org1",
            accessible_classifications=["public", "internal", "confidential"],
        )

        assert len(ctx.accessible_classifications) == 3
        assert "confidential" in ctx.accessible_classifications


class TestKnowledgeSearchService:
    """KnowledgeSearchService のテスト"""

    @pytest.fixture
    def mock_services(self, mock_async_db_conn, mock_openai_embedding, mock_pinecone):
        """サービスのモック"""
        from lib.embedding import EmbeddingClient
        from lib.pinecone_client import PineconeClient

        embedding_client = EmbeddingClient(api_key="test")
        pinecone_client = PineconeClient(api_key="test")

        return {
            'db_conn': mock_async_db_conn,
            'embedding_client': embedding_client,
            'pinecone_client': pinecone_client,
        }

    @pytest.mark.asyncio
    async def test_search_basic(
        self,
        mock_services,
        sample_user_context,
        mock_openai_embedding,
        mock_pinecone
    ):
        """基本的な検索のテスト"""
        service = KnowledgeSearchService(
            db_conn=mock_services['db_conn'],
            embedding_client=mock_services['embedding_client'],
            pinecone_client=mock_services['pinecone_client'],
        )

        # DBクエリの結果をモック
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (
                "chunk_id_1",  # chunk_id
                "org_test_doc1_v1_chunk0",  # pinecone_id
                "テスト内容",  # content
                1,  # page_number
                "1章",  # section_title
                "doc_id_1",  # document_id
                "テストドキュメント",  # title
                "test.pdf",  # file_name
                "B",  # category
                "internal",  # classification
                None,  # department_id
                "https://drive.google.com/test"  # google_drive_web_view_link
            )
        ]
        mock_services['db_conn'].execute = AsyncMock(return_value=mock_result)

        request = KnowledgeSearchRequest(
            query="テスト",
            top_k=5,
        )

        response = await service.search(sample_user_context, request)

        assert isinstance(response, KnowledgeSearchResponse)
        assert response.query == "テスト"
        assert response.search_time_ms >= 0
        assert response.total_time_ms >= 0

    @pytest.mark.asyncio
    async def test_search_with_category_filter(
        self,
        mock_services,
        sample_user_context,
        mock_openai_embedding,
        mock_pinecone
    ):
        """カテゴリフィルタ付き検索"""
        service = KnowledgeSearchService(
            db_conn=mock_services['db_conn'],
            embedding_client=mock_services['embedding_client'],
            pinecone_client=mock_services['pinecone_client'],
        )

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_services['db_conn'].execute = AsyncMock(return_value=mock_result)

        request = KnowledgeSearchRequest(
            query="経費精算",
            categories=["B"],
            top_k=3,
        )

        response = await service.search(sample_user_context, request)

        assert response.total_results == 0

    @pytest.mark.asyncio
    async def test_search_answer_refused_on_no_results(
        self,
        mock_services,
        sample_user_context,
        mock_openai_embedding,
    ):
        """結果なしで回答拒否"""
        # Pineconeが空の結果を返すようにモック
        with patch('lib.pinecone_client.Pinecone') as mock_pc:
            pc_instance = MagicMock()
            index = MagicMock()
            query_response = MagicMock()
            query_response.matches = []
            index.query.return_value = query_response
            pc_instance.Index.return_value = index
            mock_pc.return_value = pc_instance

            from lib.pinecone_client import PineconeClient
            pinecone_client = PineconeClient(api_key="test")

            service = KnowledgeSearchService(
                db_conn=mock_services['db_conn'],
                embedding_client=mock_services['embedding_client'],
                pinecone_client=pinecone_client,
            )

            mock_result = MagicMock()
            mock_result.fetchall.return_value = []
            mock_services['db_conn'].execute = AsyncMock(return_value=mock_result)

            request = KnowledgeSearchRequest(
                query="存在しない情報",
                top_k=5,
            )

            response = await service.search(sample_user_context, request)

            assert response.answer_refused is True
            assert response.refused_reason == "no_results"

    def test_build_metadata_filter_with_classifications(
        self,
        mock_services,
        sample_user_context,
    ):
        """機密区分フィルタの構築"""
        service = KnowledgeSearchService(
            db_conn=mock_services['db_conn'],
        )

        filter = service._build_metadata_filter(
            user_context=sample_user_context,
            categories=None,
        )

        assert "classification" in filter
        assert filter["classification"]["$in"] == ["public", "internal"]

    def test_build_metadata_filter_with_categories(
        self,
        mock_services,
        sample_user_context,
    ):
        """カテゴリフィルタの構築"""
        service = KnowledgeSearchService(
            db_conn=mock_services['db_conn'],
        )

        filter = service._build_metadata_filter(
            user_context=sample_user_context,
            categories=["A", "B"],
        )

        assert "$and" in filter
        # フィルタにカテゴリが含まれる
        category_filter = next(
            f for f in filter["$and"]
            if "category" in f
        )
        assert category_filter["category"]["$in"] == ["A", "B"]


class TestKnowledgeFeedback:
    """フィードバック機能のテスト"""

    @pytest.fixture
    def mock_services(self, mock_async_db_conn):
        """サービスのモック"""
        return {
            'db_conn': mock_async_db_conn,
        }

    @pytest.mark.asyncio
    async def test_submit_feedback_helpful(
        self,
        mock_services,
        sample_user_context,
    ):
        """役に立ったフィードバック"""
        service = KnowledgeSearchService(
            db_conn=mock_services['db_conn'],
        )

        mock_services['db_conn'].execute = AsyncMock()

        request = KnowledgeFeedbackRequest(
            search_log_id="log_123",
            feedback_type="helpful",
            rating=5,
            comment="とても役立ちました",
        )

        response = await service.submit_feedback(sample_user_context, request)

        assert isinstance(response, KnowledgeFeedbackResponse)
        assert response.status == "received"
        assert response.feedback_id is not None

    @pytest.mark.asyncio
    async def test_submit_feedback_with_suggestions(
        self,
        mock_services,
        sample_user_context,
    ):
        """改善提案付きフィードバック"""
        service = KnowledgeSearchService(
            db_conn=mock_services['db_conn'],
        )

        mock_services['db_conn'].execute = AsyncMock()

        request = KnowledgeFeedbackRequest(
            search_log_id="log_123",
            feedback_type="wrong",
            comment="情報が古いです",
            suggested_answer="最新の情報は...",
            suggested_source="2026年版マニュアル",
        )

        response = await service.submit_feedback(sample_user_context, request)

        assert response.status == "received"

    @pytest.mark.asyncio
    async def test_submit_feedback_with_target_chunks(
        self,
        mock_services,
        sample_user_context,
    ):
        """特定チャンクへのフィードバック"""
        service = KnowledgeSearchService(
            db_conn=mock_services['db_conn'],
        )

        mock_services['db_conn'].execute = AsyncMock()

        request = KnowledgeFeedbackRequest(
            search_log_id="log_123",
            feedback_type="incomplete",
            target_chunk_ids=["chunk_1", "chunk_2"],
        )

        response = await service.submit_feedback(sample_user_context, request)

        assert response.status == "received"
