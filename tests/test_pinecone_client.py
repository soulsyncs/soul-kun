"""
lib/pinecone_client.py のテスト

Pineconeベクターデータベース連携のユニットテスト
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from lib.pinecone_client import (
    PineconeClient,
    SearchResult,
    SearchResponse,
)


class TestPineconeClient:
    """PineconeClient のテスト"""

    def test_init_with_api_key(self, mock_pinecone):
        """APIキー指定での初期化"""
        client = PineconeClient(api_key="test-key")
        assert client._api_key == "test-key"

    def test_init_with_custom_index(self, mock_pinecone):
        """カスタムインデックス指定での初期化"""
        client = PineconeClient(api_key="test-key", index_name="custom-index")
        assert client.index_name == "custom-index"

    def test_get_namespace(self, mock_pinecone):
        """namespace生成のテスト"""
        client = PineconeClient(api_key="test-key")
        namespace = client.get_namespace("org_soulsyncs")
        assert namespace == "org_org_soulsyncs"

    def test_generate_pinecone_id(self, mock_pinecone):
        """Pinecone ID生成のテスト"""
        client = PineconeClient(api_key="test-key")
        pinecone_id = client.generate_pinecone_id(
            organization_id="org_soulsyncs",
            document_id="doc_manual001",
            version=1,
            chunk_index=0
        )
        assert pinecone_id == "org_soulsyncs_doc_manual001_v1_chunk0"

    def test_parse_pinecone_id(self, mock_pinecone):
        """Pinecone IDパースのテスト"""
        client = PineconeClient(api_key="test-key")
        parsed = client.parse_pinecone_id("org_soulsyncs_doc_manual001_v1_chunk0")

        assert parsed["organization_id"] == "org_soulsyncs"
        assert parsed["document_id"] == "doc_manual001"
        assert parsed["version"] == 1
        assert parsed["chunk_index"] == 0

    def test_parse_pinecone_id_invalid(self, mock_pinecone):
        """無効なPinecone IDのパース"""
        client = PineconeClient(api_key="test-key")
        parsed = client.parse_pinecone_id("invalid_id")
        assert "raw" in parsed

    def test_parse_pinecone_id_with_underscores_in_doc_id(self, mock_pinecone):
        """document_idにアンダースコアが含まれる場合のパース"""
        client = PineconeClient(api_key="test-key")
        # document_id = "doc_manual_001_v2"（アンダースコアを含む）
        parsed = client.parse_pinecone_id("org_soulsyncs_doc_manual_001_v2_v1_chunk0")

        assert parsed["organization_id"] == "org_soulsyncs"
        assert parsed["document_id"] == "doc_manual_001_v2"
        assert parsed["version"] == 1
        assert parsed["chunk_index"] == 0

    def test_parse_pinecone_id_simple_org(self, mock_pinecone):
        """シンプルなorganization_idの場合のパース"""
        client = PineconeClient(api_key="test-key")
        parsed = client.parse_pinecone_id("soulsyncs_doc_001_v1_chunk0")

        assert parsed["organization_id"] == "soulsyncs"
        assert parsed["document_id"] == "doc_001"
        assert parsed["version"] == 1
        assert parsed["chunk_index"] == 0

    @pytest.mark.asyncio
    async def test_search(self, mock_pinecone):
        """検索のテスト"""
        client = PineconeClient(api_key="test-key")
        query_vector = [0.1] * 768  # Gemini Embedding 768次元

        response = await client.search(
            organization_id="org_test",
            query_vector=query_vector,
            top_k=5,
            filters={"classification": {"$in": ["internal"]}},
        )

        assert isinstance(response, SearchResponse)
        assert len(response.results) == 2
        assert response.results[0].score == 0.95
        assert response.top_score == 0.95

    @pytest.mark.asyncio
    async def test_search_with_access_control(self, mock_pinecone):
        """アクセス制御付き検索のテスト"""
        client = PineconeClient(api_key="test-key")
        query_vector = [0.1] * 768  # Gemini Embedding 768次元

        response = await client.search_with_access_control(
            organization_id="org_test",
            query_vector=query_vector,
            accessible_classifications=["public", "internal"],
            top_k=5,
        )

        assert isinstance(response, SearchResponse)

    @pytest.mark.asyncio
    async def test_upsert_vectors(self, mock_pinecone):
        """ベクターupsertのテスト"""
        client = PineconeClient(api_key="test-key")

        vectors = [
            {
                "id": "test_vector_1",
                "values": [0.1] * 768,  # Gemini Embedding 768次元
                "metadata": {"category": "B"}
            }
        ]

        count = await client.upsert_vectors(
            organization_id="org_test",
            vectors=vectors
        )

        assert count == 1

    @pytest.mark.asyncio
    async def test_delete_vectors(self, mock_pinecone):
        """ベクター削除のテスト"""
        client = PineconeClient(api_key="test-key")

        count = await client.delete_vectors(
            organization_id="org_test",
            vector_ids=["vector_1", "vector_2"]
        )

        assert count == 2

    @pytest.mark.asyncio
    async def test_delete_document_vectors(self, mock_pinecone):
        """ドキュメントベクター削除のテスト"""
        client = PineconeClient(api_key="test-key")

        await client.delete_document_vectors(
            organization_id="org_test",
            document_id="doc_123",
            version=1
        )

        # delete_by_filterが呼ばれることを確認
        mock_pinecone['index'].delete.assert_called()


class TestDepartmentFilterConstruction:
    """search_with_access_control のフィルタ構築テスト"""

    @pytest.mark.asyncio
    async def test_search_dept_filter_non_confidential_only(self, mock_pinecone):
        """non-confidentialのみ + dept_ids指定 → classification.$inのみ（$or不要）"""
        client = PineconeClient(api_key="test-key")
        query_vector = [0.1] * 768

        await client.search_with_access_control(
            organization_id="org_test",
            query_vector=query_vector,
            accessible_classifications=["public", "internal"],
            accessible_department_ids=["dept_1"],
            top_k=5,
        )

        call_kwargs = mock_pinecone['index'].query.call_args
        actual_filter = call_kwargs.kwargs.get('filter') or call_kwargs[1].get('filter')

        assert actual_filter == {"classification": {"$in": ["public", "internal"]}}

    @pytest.mark.asyncio
    async def test_search_dept_filter_with_confidential(self, mock_pinecone):
        """confidential含む + dept_ids指定 → $or: [non-conf, $and:[conf, dept]]"""
        client = PineconeClient(api_key="test-key")
        query_vector = [0.1] * 768

        await client.search_with_access_control(
            organization_id="org_test",
            query_vector=query_vector,
            accessible_classifications=["public", "internal", "confidential"],
            accessible_department_ids=["dept_1", "dept_2"],
            top_k=5,
        )

        call_kwargs = mock_pinecone['index'].query.call_args
        actual_filter = call_kwargs.kwargs.get('filter') or call_kwargs[1].get('filter')

        expected = {
            "$or": [
                {"classification": {"$in": ["public", "internal"]}},
                {"$and": [
                    {"classification": "confidential"},
                    {"department_id": {"$in": ["dept_1", "dept_2"]}},
                ]},
            ]
        }
        assert actual_filter == expected

    @pytest.mark.asyncio
    async def test_search_dept_filter_empty_dept_ids(self, mock_pinecone):
        """confidential含む + dept_ids空 → confidential除外（non-confidentialのみ）"""
        client = PineconeClient(api_key="test-key")
        query_vector = [0.1] * 768

        await client.search_with_access_control(
            organization_id="org_test",
            query_vector=query_vector,
            accessible_classifications=["public", "internal", "confidential"],
            accessible_department_ids=[],
            top_k=5,
        )

        call_kwargs = mock_pinecone['index'].query.call_args
        actual_filter = call_kwargs.kwargs.get('filter') or call_kwargs[1].get('filter')

        # confidentialアクセス不可 → public/internalのみ
        assert actual_filter == {"classification": {"$in": ["public", "internal"]}}

    @pytest.mark.asyncio
    async def test_search_dept_filter_none_dept_ids(self, mock_pinecone):
        """dept_ids=None → レガシー動作（classification.$inのみ）"""
        client = PineconeClient(api_key="test-key")
        query_vector = [0.1] * 768

        await client.search_with_access_control(
            organization_id="org_test",
            query_vector=query_vector,
            accessible_classifications=["public", "internal", "confidential"],
            accessible_department_ids=None,
            top_k=5,
        )

        call_kwargs = mock_pinecone['index'].query.call_args
        actual_filter = call_kwargs.kwargs.get('filter') or call_kwargs[1].get('filter')

        assert actual_filter == {
            "classification": {"$in": ["public", "internal", "confidential"]}
        }

    @pytest.mark.asyncio
    async def test_search_dept_filter_with_category(self, mock_pinecone):
        """部署フィルタ + カテゴリフィルタ → $andで結合"""
        client = PineconeClient(api_key="test-key")
        query_vector = [0.1] * 768

        await client.search_with_access_control(
            organization_id="org_test",
            query_vector=query_vector,
            accessible_classifications=["public", "internal", "confidential"],
            accessible_department_ids=["dept_1"],
            category_filter=["A", "B"],
            top_k=5,
        )

        call_kwargs = mock_pinecone['index'].query.call_args
        actual_filter = call_kwargs.kwargs.get('filter') or call_kwargs[1].get('filter')

        # 部署フィルタ + カテゴリ → $andで結合
        assert "$and" in actual_filter
        # カテゴリフィルタが含まれる
        category_part = next(
            f for f in actual_filter["$and"]
            if "category" in f
        )
        assert category_part == {"category": {"$in": ["A", "B"]}}
        # アクセス制御フィルタの完全な構造を検証
        access_part = next(
            f for f in actual_filter["$and"]
            if "$or" in f
        )
        assert access_part == {
            "$or": [
                {"classification": {"$in": ["public", "internal"]}},
                {"$and": [
                    {"classification": "confidential"},
                    {"department_id": {"$in": ["dept_1"]}},
                ]},
            ]
        }

    @pytest.mark.asyncio
    async def test_search_dept_filter_confidential_only(self, mock_pinecone):
        """confidentialのみ + dept_ids指定 → $and:[conf, dept]（$or不要）"""
        client = PineconeClient(api_key="test-key")
        query_vector = [0.1] * 768

        await client.search_with_access_control(
            organization_id="org_test",
            query_vector=query_vector,
            accessible_classifications=["confidential"],
            accessible_department_ids=["dept_1"],
            top_k=5,
        )

        call_kwargs = mock_pinecone['index'].query.call_args
        actual_filter = call_kwargs.kwargs.get('filter') or call_kwargs[1].get('filter')

        expected = {
            "$and": [
                {"classification": "confidential"},
                {"department_id": {"$in": ["dept_1"]}},
            ]
        }
        assert actual_filter == expected


class TestSearchResult:
    """SearchResult のテスト"""

    def test_chunk_id_property(self):
        """chunk_idプロパティのテスト"""
        result = SearchResult(
            id="test_id",
            score=0.9,
            metadata={"document_id": "doc123"}
        )
        assert result.chunk_id == "test_id"

    def test_document_id_property(self):
        """document_idプロパティのテスト"""
        result = SearchResult(
            id="test_id",
            score=0.9,
            metadata={"document_id": "doc123"}
        )
        assert result.document_id == "doc123"

    def test_document_id_missing(self):
        """document_idがない場合"""
        result = SearchResult(id="test_id", score=0.9, metadata={})
        assert result.document_id is None


class TestSearchResponse:
    """SearchResponse のテスト"""

    def test_top_score(self):
        """top_scoreプロパティのテスト"""
        response = SearchResponse(
            results=[
                SearchResult(id="1", score=0.9, metadata={}),
                SearchResult(id="2", score=0.8, metadata={}),
            ],
            total_count=2,
            namespace="test"
        )
        assert response.top_score == 0.9

    def test_average_score(self):
        """average_scoreプロパティのテスト"""
        response = SearchResponse(
            results=[
                SearchResult(id="1", score=0.9, metadata={}),
                SearchResult(id="2", score=0.7, metadata={}),
            ],
            total_count=2,
            namespace="test"
        )
        assert response.average_score == pytest.approx(0.8, rel=1e-6)

    def test_empty_results(self):
        """空の結果のテスト"""
        response = SearchResponse(
            results=[],
            total_count=0,
            namespace="test"
        )
        assert response.top_score is None
        assert response.average_score is None
