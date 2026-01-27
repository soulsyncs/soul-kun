# tests/test_research_engine.py
"""
Phase G3: ディープリサーチ能力 - テスト

このモジュールは、リサーチエンジンの単体テストを提供します。

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import pytest
from uuid import uuid4
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# テスト対象のインポート
from lib.capabilities.generation import (
    # 定数
    ResearchDepth,
    ResearchType,
    SourceType,
    ReportFormat,
    GenerationType,
    GenerationStatus,
    QualityLevel,
    PERPLEXITY_DEFAULT_MODEL,
    PERPLEXITY_PRO_MODEL,
    RESEARCH_DEPTH_CONFIG,
    RESEARCH_TYPE_DEFAULT_SECTIONS,
    MAX_RESEARCH_QUERY_LENGTH,
    # モデル
    ResearchRequest,
    ResearchResult,
    ResearchPlan,
    ResearchSource,
    GenerationInput,
    GenerationOutput,
    GenerationMetadata,
    # 例外
    ResearchError,
    ResearchQueryEmptyError,
    ResearchQueryTooLongError,
    ResearchNoResultsError,
    PerplexityAPIError,
    PerplexityRateLimitError,
    PerplexityTimeoutError,
    ResearchFeatureDisabledError,
    # エンジン
    ResearchEngine,
    PerplexityClient,
    create_research_engine,
    create_perplexity_client,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def organization_id():
    """テスト用組織ID"""
    return uuid4()


@pytest.fixture
def user_id():
    """テスト用ユーザーID"""
    return uuid4()


@pytest.fixture
def mock_pool():
    """モックのDBプール"""
    return MagicMock()


@pytest.fixture
def research_request(organization_id, user_id):
    """テスト用リサーチリクエスト"""
    return ResearchRequest(
        organization_id=organization_id,
        query="競合A社について詳しく調べて",
        research_type=ResearchType.COMPETITOR,
        depth=ResearchDepth.STANDARD,
        user_id=user_id,
    )


@pytest.fixture
def research_engine(mock_pool, organization_id):
    """テスト用リサーチエンジン"""
    return ResearchEngine(
        pool=mock_pool,
        organization_id=organization_id,
        api_key="test-api-key",
        perplexity_api_key="test-perplexity-key",
    )


# =============================================================================
# 定数テスト
# =============================================================================


class TestResearchConstants:
    """リサーチ定数のテスト"""

    def test_research_depth_enum(self):
        """ResearchDepth列挙型のテスト"""
        assert ResearchDepth.QUICK.value == "quick"
        assert ResearchDepth.STANDARD.value == "standard"
        assert ResearchDepth.DEEP.value == "deep"
        assert ResearchDepth.COMPREHENSIVE.value == "comprehensive"

    def test_research_type_enum(self):
        """ResearchType列挙型のテスト"""
        assert ResearchType.COMPANY.value == "company"
        assert ResearchType.COMPETITOR.value == "competitor"
        assert ResearchType.MARKET.value == "market"
        assert ResearchType.TECHNOLOGY.value == "technology"
        assert ResearchType.TOPIC.value == "topic"

    def test_source_type_enum(self):
        """SourceType列挙型のテスト"""
        assert SourceType.WEB.value == "web"
        assert SourceType.NEWS.value == "news"
        assert SourceType.ACADEMIC.value == "academic"
        assert SourceType.INTERNAL.value == "internal"

    def test_report_format_enum(self):
        """ReportFormat列挙型のテスト"""
        assert ReportFormat.EXECUTIVE_SUMMARY.value == "executive_summary"
        assert ReportFormat.FULL_REPORT.value == "full_report"
        assert ReportFormat.COMPARISON.value == "comparison"

    def test_research_depth_config(self):
        """リサーチ深度設定のテスト"""
        config = RESEARCH_DEPTH_CONFIG[ResearchDepth.STANDARD.value]
        assert "max_sources" in config
        assert "max_queries" in config
        assert "timeout_minutes" in config
        assert config["max_sources"] == 15
        assert config["max_queries"] == 5

    def test_research_type_default_sections(self):
        """リサーチタイプ別デフォルトセクションのテスト"""
        company_sections = RESEARCH_TYPE_DEFAULT_SECTIONS[ResearchType.COMPANY.value]
        assert "企業概要" in company_sections
        assert "事業内容" in company_sections

        competitor_sections = RESEARCH_TYPE_DEFAULT_SECTIONS[ResearchType.COMPETITOR.value]
        assert "サービス比較" in competitor_sections
        assert "うちとの比較" in competitor_sections


# =============================================================================
# モデルテスト
# =============================================================================


class TestResearchModels:
    """リサーチモデルのテスト"""

    def test_research_source_creation(self):
        """ResearchSourceの作成テスト"""
        source = ResearchSource(
            source_type=SourceType.WEB,
            title="テスト記事",
            url="https://example.com/article",
            content="これはテストコンテンツです。",
            snippet="テストスニペット",
            credibility_score=0.8,
            relevance_score=0.9,
        )
        assert source.source_type == SourceType.WEB
        assert source.title == "テスト記事"
        assert source.credibility_score == 0.8
        assert source.relevance_score == 0.9

    def test_research_source_to_dict(self):
        """ResearchSource.to_dictのテスト"""
        source = ResearchSource(
            source_type=SourceType.NEWS,
            title="ニュース記事",
            url="https://news.example.com",
            snippet="ニューススニペット",
        )
        data = source.to_dict()
        assert data["source_type"] == "news"
        assert data["title"] == "ニュース記事"
        assert data["url"] == "https://news.example.com"

    def test_research_source_to_citation(self):
        """ResearchSource.to_citationのテスト"""
        source = ResearchSource(
            title="参考文献タイトル",
            author="著者名",
            url="https://example.com",
        )
        citation = source.to_citation(1)
        assert "[1]" in citation
        assert "参考文献タイトル" in citation
        assert "(著者名)" in citation
        assert "https://example.com" in citation

    def test_research_plan_creation(self):
        """ResearchPlanの作成テスト"""
        plan = ResearchPlan(
            query="AIについて調べて",
            research_type=ResearchType.TECHNOLOGY,
            depth=ResearchDepth.DEEP,
            search_queries=["AI 概要", "AI 最新動向"],
            expected_sections=["概要", "トレンド"],
            estimated_time_minutes=15,
            estimated_cost_jpy=300.0,
        )
        assert plan.query == "AIについて調べて"
        assert len(plan.search_queries) == 2
        assert plan.estimated_time_minutes == 15

    def test_research_plan_to_dict(self):
        """ResearchPlan.to_dictのテスト"""
        plan = ResearchPlan(
            query="市場調査",
            research_type=ResearchType.MARKET,
            depth=ResearchDepth.STANDARD,
        )
        data = plan.to_dict()
        assert data["query"] == "市場調査"
        assert data["research_type"] == "market"
        assert data["depth"] == "standard"

    def test_research_plan_to_user_display(self):
        """ResearchPlan.to_user_displayのテスト"""
        plan = ResearchPlan(
            query="競合調査",
            research_type=ResearchType.COMPETITOR,
            depth=ResearchDepth.STANDARD,
            search_queries=["競合A 概要", "競合A 価格"],
            expected_sections=["企業概要", "サービス比較"],
            estimated_time_minutes=10,
            estimated_cost_jpy=200.0,
        )
        display = plan.to_user_display()
        assert "競合調査" in display
        assert "competitor" in display
        assert "競合A 概要" in display
        assert "¥200" in display

    def test_research_request_creation(self, organization_id, user_id):
        """ResearchRequestの作成テスト"""
        request = ResearchRequest(
            organization_id=organization_id,
            query="AIチャットボットの市場調査",
            research_type=ResearchType.MARKET,
            depth=ResearchDepth.DEEP,
            user_id=user_id,
            instruction="特に日本市場に焦点を当てて",
        )
        assert request.query == "AIチャットボットの市場調査"
        assert request.research_type == ResearchType.MARKET
        assert request.depth == ResearchDepth.DEEP
        assert request.instruction == "特に日本市場に焦点を当てて"

    def test_research_request_to_dict(self, organization_id):
        """ResearchRequest.to_dictのテスト"""
        request = ResearchRequest(
            organization_id=organization_id,
            query="テストクエリ",
        )
        data = request.to_dict()
        assert data["query"] == "テストクエリ"
        assert data["research_type"] == "topic"
        assert data["depth"] == "standard"

    def test_research_result_creation(self):
        """ResearchResultの作成テスト"""
        result = ResearchResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            sources_count=10,
            executive_summary="これはサマリーです。",
            key_findings=["発見1", "発見2"],
            confidence_score=0.8,
            actual_cost_jpy=250.0,
        )
        assert result.status == GenerationStatus.COMPLETED
        assert result.success is True
        assert result.sources_count == 10
        assert len(result.key_findings) == 2

    def test_research_result_to_dict(self):
        """ResearchResult.to_dictのテスト"""
        result = ResearchResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            executive_summary="サマリー",
            confidence_score=0.85,
        )
        data = result.to_dict()
        assert data["status"] == "completed"
        assert data["success"] is True
        assert data["confidence_score"] == 0.85

    def test_research_result_to_user_message_completed(self):
        """ResearchResult.to_user_message（完了時）のテスト"""
        result = ResearchResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            executive_summary="競合A社は2020年設立のAIスタートアップです。",
            key_findings=["シリーズBで10億円調達", "従業員50名"],
            sources_count=15,
            confidence_score=0.85,
            actual_cost_jpy=320.0,
            document_url="https://docs.google.com/document/d/xxx",
        )
        message = result.to_user_message()
        assert "ディープリサーチ完了" in message
        assert "サマリー" in message
        assert "主要な発見" in message
        assert "15件" in message
        assert "85%" in message

    def test_research_result_to_user_message_pending(self):
        """ResearchResult.to_user_message（保留時）のテスト"""
        plan = ResearchPlan(
            query="テスト調査",
            research_type=ResearchType.TOPIC,
            search_queries=["クエリ1", "クエリ2"],
        )
        result = ResearchResult(
            status=GenerationStatus.PENDING,
            plan=plan,
        )
        message = result.to_user_message()
        assert "調査計画" in message
        assert "調査を開始していいウル" in message

    def test_research_result_to_user_message_failed(self):
        """ResearchResult.to_user_message（失敗時）のテスト"""
        result = ResearchResult(
            status=GenerationStatus.FAILED,
            success=False,
            error_message="検索結果が見つかりませんでした",
        )
        message = result.to_user_message()
        assert "失敗" in message
        assert "検索結果が見つかりませんでした" in message

    def test_research_result_get_citations(self):
        """ResearchResult.get_citationsのテスト"""
        sources = [
            ResearchSource(title="記事1", url="https://example.com/1"),
            ResearchSource(title="記事2", url="https://example.com/2"),
        ]
        result = ResearchResult(sources=sources)
        citations = result.get_citations()
        assert "参考文献" in citations
        assert "[1]" in citations
        assert "[2]" in citations


# =============================================================================
# 例外テスト
# =============================================================================


class TestResearchExceptions:
    """リサーチ例外のテスト"""

    def test_research_error(self):
        """ResearchErrorのテスト"""
        error = ResearchError(
            message="テストエラー",
            error_code="TEST_ERROR",
        )
        assert error.message == "テストエラー"
        assert error.error_code == "TEST_ERROR"
        assert error.generation_type == GenerationType.RESEARCH

    def test_research_query_empty_error(self):
        """ResearchQueryEmptyErrorのテスト"""
        error = ResearchQueryEmptyError()
        assert error.error_code == "EMPTY_QUERY"
        message = error.to_user_message()
        assert "何について調べたいか" in message

    def test_research_query_too_long_error(self):
        """ResearchQueryTooLongErrorのテスト"""
        error = ResearchQueryTooLongError(actual_length=1500, max_length=1000)
        assert error.actual_length == 1500
        assert error.max_length == 1000
        message = error.to_user_message()
        assert "1500文字" in message
        assert "1000文字以内" in message

    def test_research_no_results_error(self):
        """ResearchNoResultsErrorのテスト"""
        error = ResearchNoResultsError(query="存在しない会社")
        assert error.query == "存在しない会社"
        message = error.to_user_message()
        assert "見つかりませんでした" in message

    def test_perplexity_api_error(self):
        """PerplexityAPIErrorのテスト"""
        error = PerplexityAPIError(
            message="API呼び出し失敗",
            model="llama-3.1-sonar-small-128k-online",
        )
        assert error.model == "llama-3.1-sonar-small-128k-online"

    def test_perplexity_rate_limit_error(self):
        """PerplexityRateLimitErrorのテスト"""
        error = PerplexityRateLimitError(retry_after=60)
        assert error.retry_after == 60
        message = error.to_user_message()
        assert "60秒後" in message

    def test_perplexity_timeout_error(self):
        """PerplexityTimeoutErrorのテスト"""
        error = PerplexityTimeoutError(timeout_seconds=120)
        assert error.timeout_seconds == 120
        message = error.to_user_message()
        assert "タイムアウト" in message


# =============================================================================
# PerplexityClientテスト
# =============================================================================


class TestPerplexityClient:
    """PerplexityClientのテスト"""

    def test_create_perplexity_client(self):
        """create_perplexity_clientのテスト"""
        client = create_perplexity_client(api_key="test-key")
        assert isinstance(client, PerplexityClient)

    def test_client_initialization(self):
        """クライアント初期化のテスト"""
        client = PerplexityClient(
            api_key="test-api-key",
            timeout_seconds=60,
            max_retries=5,
        )
        assert client._api_key == "test-api-key"
        assert client._timeout_seconds == 60
        assert client._max_retries == 5

    @pytest.mark.asyncio
    async def test_search_without_api_key(self):
        """APIキーなしでの検索テスト"""
        client = PerplexityClient(api_key=None)
        # 環境変数もない場合
        with patch.dict("os.environ", {}, clear=True):
            client._api_key = None
            result = await client.search("テスト")
            assert result["success"] is False
            assert "API key not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_search_success(self):
        """検索成功のテスト"""
        client = PerplexityClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "検索結果"}}],
            "citations": ["https://example.com"],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await client.search("テストクエリ")
            assert result["success"] is True
            assert result["response"] == "検索結果"
            assert result["total_tokens"] == 300


# =============================================================================
# ResearchEngineテスト
# =============================================================================


class TestResearchEngine:
    """ResearchEngineのテスト"""

    def test_create_research_engine(self, mock_pool, organization_id):
        """create_research_engineのテスト"""
        engine = create_research_engine(
            pool=mock_pool,
            organization_id=organization_id,
            api_key="test-key",
            perplexity_api_key="test-perplexity-key",
        )
        assert isinstance(engine, ResearchEngine)

    def test_engine_initialization(self, research_engine):
        """エンジン初期化のテスト"""
        assert research_engine._generation_type == GenerationType.RESEARCH
        assert research_engine._perplexity_client is not None

    def test_validate_empty_query(self, research_engine, organization_id):
        """空クエリの検証テスト"""
        request = ResearchRequest(
            organization_id=organization_id,
            query="",
        )
        with pytest.raises(ResearchQueryEmptyError):
            research_engine._validate_request(request)

    def test_validate_query_too_long(self, research_engine, organization_id):
        """長すぎるクエリの検証テスト"""
        request = ResearchRequest(
            organization_id=organization_id,
            query="あ" * (MAX_RESEARCH_QUERY_LENGTH + 1),
        )
        with pytest.raises(ResearchQueryTooLongError):
            research_engine._validate_request(request)

    def test_validate_valid_request(self, research_engine, research_request):
        """有効なリクエストの検証テスト"""
        # 例外が発生しないことを確認
        research_engine._validate_request(research_request)

    def test_generate_fallback_queries_company(self, research_engine, organization_id):
        """企業調査用フォールバッククエリ生成テスト"""
        request = ResearchRequest(
            organization_id=organization_id,
            query="株式会社テスト",
            research_type=ResearchType.COMPANY,
        )
        queries = research_engine._generate_fallback_queries(request)
        assert "株式会社テスト" in queries
        assert any("企業概要" in q for q in queries)
        assert any("事業内容" in q for q in queries)

    def test_generate_fallback_queries_competitor(self, research_engine, organization_id):
        """競合調査用フォールバッククエリ生成テスト"""
        request = ResearchRequest(
            organization_id=organization_id,
            query="競合A社",
            research_type=ResearchType.COMPETITOR,
        )
        queries = research_engine._generate_fallback_queries(request)
        assert any("サービス" in q for q in queries)
        assert any("価格" in q for q in queries)

    def test_generate_fallback_queries_market(self, research_engine, organization_id):
        """市場調査用フォールバッククエリ生成テスト"""
        request = ResearchRequest(
            organization_id=organization_id,
            query="AIチャットボット市場",
            research_type=ResearchType.MARKET,
        )
        queries = research_engine._generate_fallback_queries(request)
        assert any("市場規模" in q for q in queries)
        assert any("トレンド" in q for q in queries)

    def test_calculate_confidence_no_sources(self, research_engine):
        """ソースなしの信頼度計算テスト"""
        confidence = research_engine._calculate_confidence([])
        assert confidence == 0.0

    def test_calculate_confidence_with_sources(self, research_engine):
        """ソースありの信頼度計算テスト"""
        sources = [
            ResearchSource(credibility_score=0.8),
            ResearchSource(credibility_score=0.9),
            ResearchSource(credibility_score=0.7),
        ]
        confidence = research_engine._calculate_confidence(sources)
        assert 0.7 < confidence <= 1.0

    def test_calculate_coverage(self, research_engine):
        """網羅性計算テスト"""
        plan = ResearchPlan(
            search_queries=["クエリA", "クエリB", "クエリC"],
        )
        sources = [
            ResearchSource(content="クエリAについての情報"),
            ResearchSource(content="クエリBに関連するデータ"),
        ]
        coverage = research_engine._calculate_coverage(sources, plan)
        assert 0 < coverage <= 1.0

    def test_estimate_cost(self, research_engine):
        """コスト推定テスト"""
        cost = research_engine._estimate_cost(
            num_queries=5,
            depth=ResearchDepth.STANDARD,
        )
        assert cost > 0
        assert cost < 100  # 妥当な範囲内

    @pytest.mark.asyncio
    async def test_generate_missing_request(self, research_engine, organization_id):
        """リクエストなしでの生成テスト"""
        input_data = GenerationInput(
            generation_type=GenerationType.RESEARCH,
            organization_id=organization_id,
            research_request=None,
        )
        with pytest.raises(ResearchError) as exc_info:
            await research_engine.generate(input_data)
        assert "research_request is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_generate_with_plan_confirmation(
        self, research_engine, organization_id, user_id
    ):
        """計画確認ありの生成テスト"""
        request = ResearchRequest(
            organization_id=organization_id,
            query="テスト調査",
            user_id=user_id,
            require_plan_confirmation=True,
        )

        # LLM呼び出しをモック
        with patch.object(
            research_engine,
            "_call_llm_json",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = {
                "parsed": {
                    "search_queries": ["クエリ1", "クエリ2"],
                    "key_questions": ["質問1"],
                    "expected_sections": ["セクション1"],
                    "estimated_time_minutes": 5,
                },
                "total_tokens": 100,
            }

            input_data = GenerationInput(
                generation_type=GenerationType.RESEARCH,
                organization_id=organization_id,
                research_request=request,
            )

            result = await research_engine.generate(input_data)

            assert result.success is True
            assert result.status == GenerationStatus.PENDING
            assert result.research_result.plan is not None
            assert len(result.research_result.plan.search_queries) == 2


# =============================================================================
# 統合テスト
# =============================================================================


class TestResearchIntegration:
    """統合テスト"""

    def test_generation_input_with_research(self, organization_id):
        """GenerationInputにリサーチリクエストを含むテスト"""
        request = ResearchRequest(
            organization_id=organization_id,
            query="テスト",
        )
        input_data = GenerationInput(
            generation_type=GenerationType.RESEARCH,
            organization_id=organization_id,
            research_request=request,
        )
        assert input_data.get_request() == request

    def test_generation_output_with_research(self):
        """GenerationOutputにリサーチ結果を含むテスト"""
        result = ResearchResult(
            status=GenerationStatus.COMPLETED,
            success=True,
        )
        output = GenerationOutput(
            generation_type=GenerationType.RESEARCH,
            success=True,
            status=GenerationStatus.COMPLETED,
            research_result=result,
        )
        assert output.get_result() == result

    def test_generation_output_to_user_message(self):
        """GenerationOutput.to_user_messageのテスト"""
        result = ResearchResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            executive_summary="サマリー",
            key_findings=["発見1"],
            sources_count=5,
            confidence_score=0.8,
            actual_cost_jpy=100,
        )
        output = GenerationOutput(
            generation_type=GenerationType.RESEARCH,
            success=True,
            research_result=result,
        )
        message = output.to_user_message()
        assert "サマリー" in message

    def test_generation_output_to_brain_context(self):
        """GenerationOutput.to_brain_contextのテスト"""
        plan = ResearchPlan(query="テスト調査")
        result = ResearchResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            plan=plan,
            sources_count=10,
            key_findings=["発見1", "発見2"],
        )
        output = GenerationOutput(
            generation_type=GenerationType.RESEARCH,
            success=True,
            research_result=result,
        )
        context = output.to_brain_context()
        assert "ディープリサーチ" in context
        assert "テスト調査" in context
