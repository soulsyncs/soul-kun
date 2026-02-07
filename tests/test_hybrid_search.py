# tests/test_hybrid_search.py
"""
ハイブリッド検索のユニットテスト

Phase 1-B: OpenClawから学んだ「Hybrid Search」のsoul-kun実装テスト
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from lib.brain.hybrid_search import (
    HybridSearcher,
    HybridSearchResult,
    HybridSearchResponse,
    compute_rrf_score,
    merge_results_rrf,
    RRF_K,
    VECTOR_WEIGHT,
    KEYWORD_WEIGHT,
    MIN_VECTOR_SCORE,
    DEFAULT_TOP_K,
    MAX_QUERY_LENGTH,
    escape_ilike,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_pool():
    """データベース接続プールのモック"""
    pool = Mock()
    conn = MagicMock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=False)
    pool.connect.return_value = conn
    return pool


@pytest.fixture
def mock_pinecone():
    """Pineconeクライアントのモック"""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_embedding():
    """Embeddingクライアントのモック"""
    client = AsyncMock()
    # embed_queryの戻り値
    embed_result = Mock()
    embed_result.vector = [0.1] * 768
    client.embed_query.return_value = embed_result
    return client


@pytest.fixture
def searcher(mock_pool):
    """HybridSearcherインスタンス（クライアントなし）"""
    return HybridSearcher(
        pool=mock_pool,
        org_id="org_test",
    )


@pytest.fixture
def searcher_full(mock_pool, mock_pinecone, mock_embedding):
    """HybridSearcherインスタンス（全クライアントあり）"""
    return HybridSearcher(
        pool=mock_pool,
        org_id="org_test",
        pinecone_client=mock_pinecone,
        embedding_client=mock_embedding,
    )


# =============================================================================
# RRFスコア計算テスト
# =============================================================================


class TestComputeRRFScore:
    """RRFスコア計算のテスト"""

    def test_rank_1(self):
        """1位のRRFスコア"""
        score = compute_rrf_score(1)
        assert score == pytest.approx(1.0 / (RRF_K + 1))

    def test_rank_2(self):
        """2位のRRFスコア"""
        score = compute_rrf_score(2)
        assert score == pytest.approx(1.0 / (RRF_K + 2))

    def test_higher_rank_lower_score(self):
        """順位が高いほどスコアが高い"""
        score_1 = compute_rrf_score(1)
        score_5 = compute_rrf_score(5)
        score_10 = compute_rrf_score(10)
        assert score_1 > score_5 > score_10

    def test_custom_k(self):
        """カスタムk値"""
        score = compute_rrf_score(1, k=10)
        assert score == pytest.approx(1.0 / 11)


# =============================================================================
# ILIKEエスケープテスト
# =============================================================================


class TestEscapeIlike:
    """ILIKEメタキャラクタエスケープのテスト"""

    def test_escape_percent(self):
        """%がエスケープされる"""
        assert escape_ilike("100%完了") == "100\\%完了"

    def test_escape_underscore(self):
        """_がエスケープされる"""
        assert escape_ilike("user_name") == "user\\_name"

    def test_escape_backslash(self):
        """バックスラッシュがエスケープされる"""
        assert escape_ilike("path\\file") == "path\\\\file"

    def test_escape_all_metacharacters(self):
        """全メタキャラクタが同時にエスケープされる"""
        assert escape_ilike("50%_done\\ok") == "50\\%\\_done\\\\ok"

    def test_no_escape_needed(self):
        """通常テキストはそのまま"""
        assert escape_ilike("田中さんは部長") == "田中さんは部長"

    def test_empty_string(self):
        """空文字列"""
        assert escape_ilike("") == ""


# =============================================================================
# クエリ長制限テスト
# =============================================================================


class TestQueryLengthLimit:
    """クエリ長制限のテスト"""

    @pytest.mark.asyncio
    async def test_long_query_is_truncated(self, searcher, mock_pool):
        """MAX_QUERY_LENGTH超過クエリが切り詰められる"""
        long_query = "テスト" * 300  # 900文字
        assert len(long_query) > MAX_QUERY_LENGTH

        conn = mock_pool.connect.return_value
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = []
        chunks_result = MagicMock()
        chunks_result.fetchall.return_value = []
        conn.execute.side_effect = [knowledge_result, chunks_result]

        result = await searcher.search(long_query)
        # エラーなく実行される
        assert result.total_count == 0


# =============================================================================
# RRF統合テスト
# =============================================================================


class TestMergeResultsRRF:
    """RRFスコア統合のテスト"""

    def test_vector_only_results(self):
        """ベクトル検索のみの結果"""
        vector = [
            {"id": "v1", "content": "doc1", "title": "Title1", "score": 0.9},
            {"id": "v2", "content": "doc2", "title": "Title2", "score": 0.8},
        ]
        merged = merge_results_rrf(vector, [], top_k=5)
        assert len(merged) == 2
        assert merged[0].id == "v1"
        assert merged[0].source == "vector"
        assert merged[0].hybrid_score > merged[1].hybrid_score

    def test_keyword_only_results(self):
        """キーワード検索のみの結果"""
        keyword = [
            {"id": "k1", "content": "doc1", "title": "Title1"},
            {"id": "k2", "content": "doc2", "title": "Title2"},
        ]
        merged = merge_results_rrf([], keyword, top_k=5)
        assert len(merged) == 2
        assert merged[0].id == "k1"
        assert merged[0].source == "keyword"

    def test_both_sources_boost(self):
        """両方で見つかった結果はブーストされる"""
        vector = [
            {"id": "common", "content": "doc1", "title": "Title1", "score": 0.9},
            {"id": "v_only", "content": "doc2", "title": "Title2", "score": 0.85},
        ]
        keyword = [
            {"id": "common", "content": "doc1", "title": "Title1"},
            {"id": "k_only", "content": "doc3", "title": "Title3"},
        ]
        merged = merge_results_rrf(vector, keyword, top_k=5)
        # "common"は両方にあるのでブースト
        common = next(r for r in merged if r.id == "common")
        assert common.source == "both"
        assert common.hybrid_score > merged[1].hybrid_score

    def test_respects_top_k(self):
        """top_kを超えない"""
        vector = [
            {"id": f"v{i}", "content": f"doc{i}", "title": f"T{i}", "score": 0.9 - i * 0.01}
            for i in range(10)
        ]
        merged = merge_results_rrf(vector, [], top_k=3)
        assert len(merged) == 3

    def test_empty_both(self):
        """両方空"""
        merged = merge_results_rrf([], [])
        assert len(merged) == 0

    def test_weight_ratio(self):
        """重みの比率が反映される"""
        # ベクトル1位とキーワード1位が別のドキュメント
        vector = [{"id": "v1", "content": "v", "title": "V", "score": 0.9}]
        keyword = [{"id": "k1", "content": "k", "title": "K"}]
        merged = merge_results_rrf(vector, keyword, vector_weight=0.7, keyword_weight=0.3)
        v1 = next(r for r in merged if r.id == "v1")
        k1 = next(r for r in merged if r.id == "k1")
        # ベクトルの方が重みが大きいので高スコア
        assert v1.hybrid_score > k1.hybrid_score


# =============================================================================
# データクラステスト
# =============================================================================


class TestDataClasses:
    """データクラスのテスト"""

    def test_search_result_to_dict(self):
        """HybridSearchResultのシリアライズ"""
        result = HybridSearchResult(
            id="test1",
            content="テスト内容",
            title="テストタイトル",
            category="A",
            source="vector",
            vector_score=0.9,
            hybrid_score=0.85,
        )
        d = result.to_dict()
        assert d["id"] == "test1"
        assert d["content"] == "テスト内容"
        assert d["vector_score"] == 0.9

    def test_search_response_to_dict(self):
        """HybridSearchResponseのシリアライズ"""
        response = HybridSearchResponse(
            results=[
                HybridSearchResult(id="1", content="c", title="t", hybrid_score=0.5),
            ],
            vector_count=3,
            keyword_count=2,
            total_count=1,
            search_time_ms=42.5,
        )
        d = response.to_dict()
        assert d["vector_count"] == 3
        assert d["keyword_count"] == 2
        assert d["search_time_ms"] == 42.5
        assert len(d["results"]) == 1


# =============================================================================
# ベクトル検索テスト
# =============================================================================


class TestVectorSearch:
    """ベクトル検索のテスト"""

    @pytest.mark.asyncio
    async def test_returns_empty_without_clients(self, searcher):
        """クライアントなしでは空リスト"""
        results = await searcher._vector_search("テスト")
        assert results == []

    @pytest.mark.asyncio
    async def test_embeds_query_and_searches(self, searcher_full, mock_pinecone, mock_embedding):
        """クエリをEmbedding化してPinecone検索"""
        # Pineconeの戻り値を設定
        search_result = Mock()
        search_result.id = "chunk_1"
        search_result.score = 0.85
        search_result.metadata = {"content": "テスト内容", "title": "テストDoc", "category": "A"}
        response = Mock()
        response.results = [search_result]
        mock_pinecone.search.return_value = response

        results = await searcher_full._vector_search("テストクエリ")
        assert len(results) == 1
        assert results[0]["id"] == "chunk_1"
        assert results[0]["score"] == 0.85
        mock_embedding.embed_query.assert_called_once_with("テストクエリ")

    @pytest.mark.asyncio
    async def test_filters_low_score(self, searcher_full, mock_pinecone, mock_embedding):
        """MIN_VECTOR_SCORE未満は除外"""
        high = Mock(id="high", score=0.8, metadata={"content": "h", "title": "H"})
        low = Mock(id="low", score=0.1, metadata={"content": "l", "title": "L"})
        response = Mock(results=[high, low])
        mock_pinecone.search.return_value = response

        results = await searcher_full._vector_search("テスト")
        assert len(results) == 1
        assert results[0]["id"] == "high"

    @pytest.mark.asyncio
    async def test_handles_pinecone_error(self, searcher_full, mock_pinecone, mock_embedding):
        """Pineconeエラー時は空リスト"""
        mock_pinecone.search.side_effect = Exception("Pinecone error")
        results = await searcher_full._vector_search("テスト")
        assert results == []


# =============================================================================
# キーワード検索テスト
# =============================================================================


class TestKeywordSearch:
    """キーワード検索のテスト"""

    @pytest.mark.asyncio
    async def test_searches_knowledge_table(self, searcher, mock_pool):
        """soulkun_knowledgeからの検索"""
        conn = mock_pool.connect.return_value
        # 2回のexecute呼び出し（knowledge + chunks）
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = [
            ("1", "営業部", "営業部の情報", "department"),
        ]
        chunks_result = MagicMock()
        chunks_result.fetchall.return_value = []
        conn.execute.side_effect = [knowledge_result, chunks_result]

        results = await searcher._keyword_search("営業")
        assert len(results) == 1
        assert results[0]["id"] == "knowledge_1"
        assert results[0]["title"] == "営業部"

    @pytest.mark.asyncio
    async def test_searches_document_chunks(self, searcher, mock_pool):
        """document_chunksからの検索"""
        conn = mock_pool.connect.return_value
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = []
        chunks_result = MagicMock()
        chunks_result.fetchall.return_value = [
            ("uuid-1", "経費精算マニュアル", "経費の申請方法", "B", "org_test_doc1_v1_chunk0"),
        ]
        conn.execute.side_effect = [knowledge_result, chunks_result]

        results = await searcher._keyword_search("経費")
        assert len(results) == 1
        # pinecone_idがあればそちらがIDになる
        assert results[0]["id"] == "org_test_doc1_v1_chunk0"
        assert results[0]["source_table"] == "document_chunks"

    @pytest.mark.asyncio
    async def test_searches_document_chunks_no_pinecone_id(self, searcher, mock_pool):
        """pinecone_idがない場合はchunk_プレフィックス"""
        conn = mock_pool.connect.return_value
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = []
        chunks_result = MagicMock()
        chunks_result.fetchall.return_value = [
            ("uuid-1", "タイトル", "内容", "A", None),
        ]
        conn.execute.side_effect = [knowledge_result, chunks_result]

        results = await searcher._keyword_search("テスト")
        assert len(results) == 1
        assert results[0]["id"] == "chunk_uuid-1"

    @pytest.mark.asyncio
    async def test_combines_both_tables(self, searcher, mock_pool):
        """両テーブルの結果を結合"""
        conn = mock_pool.connect.return_value
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = [("1", "key", "value", "cat")]
        chunks_result = MagicMock()
        chunks_result.fetchall.return_value = [("uuid-1", "title", "content", "A", "pinecone_id_1")]
        conn.execute.side_effect = [knowledge_result, chunks_result]

        results = await searcher._keyword_search("テスト")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_handles_db_error(self, searcher, mock_pool):
        """DBエラー時は空リスト"""
        conn = mock_pool.connect.return_value
        conn.execute.side_effect = Exception("DB error")
        results = await searcher._keyword_search("テスト")
        assert results == []


# =============================================================================
# ハイブリッド検索統合テスト
# =============================================================================


class TestHybridSearch:
    """ハイブリッド検索の統合テスト"""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, searcher):
        """空クエリは空結果"""
        result = await searcher.search("")
        assert result.total_count == 0

    @pytest.mark.asyncio
    async def test_keyword_only_without_pinecone(self, searcher, mock_pool):
        """Pineconeなしではキーワード検索のみ"""
        conn = mock_pool.connect.return_value
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = [
            ("1", "テスト", "テスト内容", "cat"),
        ]
        chunks_result = MagicMock()
        chunks_result.fetchall.return_value = []
        conn.execute.side_effect = [knowledge_result, chunks_result]

        result = await searcher.search("テスト")
        assert result.total_count == 1
        assert result.vector_count == 0
        assert result.keyword_count == 1

    @pytest.mark.asyncio
    async def test_full_hybrid_search(self, searcher_full, mock_pool, mock_pinecone, mock_embedding):
        """ベクトル + キーワードのフルハイブリッド検索"""
        # Pinecone結果
        vec_result = Mock(id="vec1", score=0.9, metadata={"content": "ベクトル結果", "title": "VT"})
        mock_pinecone.search.return_value = Mock(results=[vec_result])

        # PostgreSQL結果
        conn = mock_pool.connect.return_value
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = [
            ("1", "キーワード結果", "キーワード内容", "cat"),
        ]
        chunks_result = MagicMock()
        chunks_result.fetchall.return_value = []
        conn.execute.side_effect = [knowledge_result, chunks_result]

        result = await searcher_full.search("テスト", top_k=5)
        assert result.total_count == 2
        assert result.vector_count == 1
        assert result.keyword_count == 1
        assert result.search_time_ms > 0

    @pytest.mark.asyncio
    async def test_vector_failure_falls_back(self, searcher_full, mock_pool, mock_pinecone, mock_embedding):
        """ベクトル検索失敗時はキーワードのみ"""
        mock_pinecone.search.side_effect = Exception("Pinecone down")

        conn = mock_pool.connect.return_value
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = [("1", "key", "value", "cat")]
        chunks_result = MagicMock()
        chunks_result.fetchall.return_value = []
        conn.execute.side_effect = [knowledge_result, chunks_result]

        result = await searcher_full.search("テスト")
        # ベクトル失敗でもキーワード結果は返る
        assert result.total_count >= 1
        assert result.keyword_count >= 1
