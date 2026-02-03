# tests/test_url_processor.py
"""
URL処理プロセッサーのテスト

lib/capabilities/multimodal/url_processor.py のカバレッジ80%以上を目指す。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import socket
import httpx

from lib.capabilities.multimodal.url_processor import (
    URLProcessor,
    create_url_processor,
)
from lib.capabilities.multimodal.constants import (
    InputType,
    URLType,
    ContentConfidenceLevel,
    SUPPORTED_URL_PROTOCOLS,
)
from lib.capabilities.multimodal.models import (
    MultimodalInput,
    URLMetadata,
)
from lib.capabilities.multimodal.exceptions import (
    ValidationError,
    URLBlockedError,
    URLFetchError,
    URLTimeoutError,
    URLParseError,
    URLContentExtractionError,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_pool():
    """モックDB接続プール"""
    return MagicMock()


@pytest.fixture
def processor(mock_pool):
    """テスト用URLProcessor"""
    return URLProcessor(
        pool=mock_pool,
        organization_id="test-org-123",
        api_key="test-api-key",
    )


@pytest.fixture
def sample_html():
    """サンプルHTML"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Article</title>
        <meta name="description" content="Test description">
        <meta property="og:title" content="OG Title">
    </head>
    <body>
        <script>console.log('test');</script>
        <style>.test { color: red; }</style>
        <nav>Navigation</nav>
        <main>
            <article>
                <h1>Main Title</h1>
                <h2>Section 1</h2>
                <p>This is the main content of the article. It contains important information.</p>
                <p>Another paragraph with more details about the topic.</p>
                <a href="https://example.com/link1">Link 1</a>
                <img src="https://example.com/image.png" alt="Test Image">
            </article>
        </main>
        <footer>Footer content</footer>
    </body>
    </html>
    """


@pytest.fixture
def sample_input():
    """サンプル入力"""
    return MultimodalInput(
        input_type=InputType.URL,
        organization_id="test-org-123",
        url="https://example.com/article",
        instruction="この記事を要約して",
    )


# =============================================================================
# TestURLProcessorInit - 初期化テスト
# =============================================================================


class TestURLProcessorInit:
    """URLProcessor初期化のテスト"""

    def test_init_with_params(self, mock_pool):
        """パラメータ指定で初期化"""
        processor = URLProcessor(
            pool=mock_pool,
            organization_id="org-123",
            api_key="api-key",
        )
        assert processor._organization_id == "org-123"
        assert processor._api_key == "api-key"

    def test_init_without_api_key(self, mock_pool):
        """API Keyなしで初期化"""
        processor = URLProcessor(pool=mock_pool, organization_id="org-123")
        assert processor._api_key is None


# =============================================================================
# TestValidate - 入力検証テスト
# =============================================================================


class TestValidate:
    """validate()メソッドのテスト"""

    def test_validate_valid_input(self, processor, sample_input):
        """正常な入力を検証"""
        # 例外が発生しなければOK
        processor.validate(sample_input)

    def test_validate_wrong_input_type(self, processor):
        """間違った入力タイプでエラー"""
        input_data = MultimodalInput(
            input_type=InputType.IMAGE,
            organization_id="test-org-123",
            url="https://example.com",
        )
        with pytest.raises(ValidationError) as exc_info:
            processor.validate(input_data)
        assert "input_type" in str(exc_info.value.field)

    def test_validate_missing_url(self, processor):
        """URLなしでエラー"""
        input_data = MultimodalInput(
            input_type=InputType.URL,
            organization_id="test-org-123",
            url=None,
        )
        with pytest.raises(ValidationError) as exc_info:
            processor.validate(input_data)
        assert "url" in str(exc_info.value.field)

    def test_validate_empty_url(self, processor):
        """空URLでエラー"""
        input_data = MultimodalInput(
            input_type=InputType.URL,
            organization_id="test-org-123",
            url="",
        )
        with pytest.raises(ValidationError):
            processor.validate(input_data)

    def test_validate_invalid_url_format(self, processor):
        """無効なURL形式でエラー"""
        input_data = MultimodalInput(
            input_type=InputType.URL,
            organization_id="test-org-123",
            url="not-a-valid-url",
        )
        with pytest.raises(URLParseError):
            processor.validate(input_data)

    def test_validate_unsupported_protocol(self, processor):
        """サポートされていないプロトコルでエラー"""
        input_data = MultimodalInput(
            input_type=InputType.URL,
            organization_id="test-org-123",
            url="ftp://example.com/file",
        )
        with pytest.raises(ValidationError) as exc_info:
            processor.validate(input_data)
        assert "protocol" in str(exc_info.value).lower()


# =============================================================================
# TestCheckUrlSecurity - セキュリティチェックテスト
# =============================================================================


class TestCheckUrlSecurity:
    """_check_url_security()メソッドのテスト"""

    def test_check_url_security_valid(self, processor):
        """正常なURLをチェック"""
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            processor._check_url_security("https://example.com/page")

    def test_check_url_security_blocked_domain(self, processor):
        """ブロックされたドメイン"""
        with pytest.raises(URLBlockedError) as exc_info:
            processor._check_url_security("https://localhost/admin")
        assert "ブロック" in str(exc_info.value)

    def test_check_url_security_private_ip(self, processor):
        """プライベートIPアドレス"""
        with patch("socket.gethostbyname", return_value="192.168.1.1"):
            with pytest.raises(URLBlockedError) as exc_info:
                processor._check_url_security("https://internal.example.com")
            assert "プライベート" in str(exc_info.value)

    def test_check_url_security_loopback(self, processor):
        """ループバックアドレス"""
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            with pytest.raises(URLBlockedError):
                processor._check_url_security("https://loopback.test")

    def test_check_url_security_dns_failure(self, processor):
        """DNS解決失敗（許容）"""
        with patch("socket.gethostbyname", side_effect=socket.gaierror("DNS error")):
            # DNS解決失敗は許容される
            processor._check_url_security("https://nonexistent.example.com")

    def test_check_url_security_with_port(self, processor):
        """ポート付きURL"""
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            processor._check_url_security("https://example.com:8080/page")


# =============================================================================
# TestGetDomain - ドメイン取得テスト
# =============================================================================


class TestGetDomain:
    """_get_domain()メソッドのテスト"""

    def test_get_domain_valid(self, processor):
        """正常なURLからドメイン取得"""
        domain = processor._get_domain("https://example.com/path")
        assert domain == "example.com"

    def test_get_domain_with_port(self, processor):
        """ポート付きURL"""
        domain = processor._get_domain("https://example.com:8080/path")
        assert "example.com" in domain

    def test_get_domain_none(self, processor):
        """Noneの場合"""
        domain = processor._get_domain(None)
        assert domain == "unknown"

    def test_get_domain_empty(self, processor):
        """空文字の場合はunknownを返す"""
        domain = processor._get_domain("")
        # 空文字は"unknown"として扱われる（実装の仕様）
        assert domain == "unknown"

    def test_get_domain_invalid(self, processor):
        """無効なURLの場合"""
        domain = processor._get_domain("not-a-url")
        # urlparseはパースはするがnetlocが空になる
        assert domain == ""


# =============================================================================
# TestFetchContent - コンテンツ取得テスト
# =============================================================================


class TestFetchContent:
    """_fetch_content()メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_fetch_content_success(self, processor, sample_html):
        """正常にコンテンツを取得"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = sample_html
        mock_response.url = "https://example.com/article"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.history = []

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            html, metadata = await processor._fetch_content("https://example.com/article")

        assert html == sample_html
        assert metadata.url == "https://example.com/article"
        assert metadata.status_code == 200

    @pytest.mark.asyncio
    async def test_fetch_content_redirect(self, processor, sample_html):
        """リダイレクトを処理"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = sample_html
        mock_response.url = "https://example.com/final"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.history = [MagicMock(), MagicMock()]  # 2回リダイレクト

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            html, metadata = await processor._fetch_content("https://example.com/old")

        assert metadata.redirected is True
        assert metadata.redirect_count == 2

    @pytest.mark.asyncio
    async def test_fetch_content_404(self, processor):
        """404エラー"""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            with pytest.raises(URLFetchError) as exc_info:
                await processor._fetch_content("https://example.com/notfound")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_fetch_content_timeout(self, processor):
        """タイムアウト"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )
            with pytest.raises(URLTimeoutError):
                await processor._fetch_content("https://slow.example.com")

    @pytest.mark.asyncio
    async def test_fetch_content_http_error(self, processor):
        """HTTPエラー"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.HTTPError("Connection failed")
            )
            with pytest.raises(URLFetchError):
                await processor._fetch_content("https://error.example.com")

    @pytest.mark.asyncio
    async def test_fetch_content_too_large_header(self, processor):
        """Content-Lengthで大きすぎるコンテンツを検出"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-length": "100000000"}  # 100MB

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            with pytest.raises(URLFetchError) as exc_info:
                await processor._fetch_content("https://huge.example.com")

        # URLFetchErrorが発生し、URLが含まれていることを確認
        assert "huge.example.com" in str(exc_info.value) or exc_info.value.url == "https://huge.example.com"


# =============================================================================
# TestExtractContent - コンテンツ抽出テスト
# =============================================================================


class TestExtractContent:
    """_extract_content()メソッドのテスト"""

    def test_extract_content_with_beautifulsoup(self, processor, sample_html):
        """BeautifulSoupでコンテンツ抽出"""
        main_content, headings, links, images = processor._extract_content(sample_html)

        # 本文が抽出されていることを確認
        assert len(main_content) > 0
        assert "Main Title" in main_content or "main content" in main_content.lower()
        # サンプルHTMLには見出し、リンク、画像が含まれている
        assert isinstance(headings, list)
        assert isinstance(links, list)
        assert isinstance(images, list)

    def test_extract_content_basic_fallback(self, processor, sample_html):
        """BeautifulSoupなしの基本抽出"""
        main_content, headings, links, images = processor._extract_content_basic(sample_html)

        # スクリプトとスタイルが除去されていること
        assert "console.log" not in main_content
        assert "color: red" not in main_content
        # 本文テキストが含まれること
        assert "Main Title" in main_content or len(main_content) > 0


# =============================================================================
# TestDetermineUrlType - URLタイプ判定テスト
# =============================================================================


class TestDetermineUrlType:
    """_determine_url_type()メソッドのテスト"""

    def test_determine_url_type_news(self, processor):
        """ニュースサイト"""
        metadata = URLMetadata(url="", final_url="", domain="news.yahoo.co.jp")
        url_type = processor._determine_url_type(
            "https://news.yahoo.co.jp/article",
            metadata,
            "記事内容",
        )
        assert url_type == URLType.NEWS

    def test_determine_url_type_blog(self, processor):
        """ブログサイト"""
        metadata = URLMetadata(url="", final_url="", domain="note.com")
        url_type = processor._determine_url_type(
            "https://note.com/user/article",
            metadata,
            "ブログ内容",
        )
        assert url_type == URLType.BLOG

    def test_determine_url_type_video(self, processor):
        """動画サイト"""
        metadata = URLMetadata(url="", final_url="", domain="youtube.com")
        url_type = processor._determine_url_type(
            "https://youtube.com/watch?v=123",
            metadata,
            "動画説明",
        )
        assert url_type == URLType.VIDEO

    def test_determine_url_type_social(self, processor):
        """SNS"""
        metadata = URLMetadata(url="", final_url="", domain="twitter.com")
        url_type = processor._determine_url_type(
            "https://twitter.com/user/status/123",
            metadata,
            "ツイート内容",
        )
        assert url_type == URLType.SOCIAL

    def test_determine_url_type_document(self, processor):
        """ドキュメント"""
        metadata = URLMetadata(url="", final_url="", domain="notion.so")
        url_type = processor._determine_url_type(
            "https://notion.so/page",
            metadata,
            "ドキュメント内容",
        )
        assert url_type == URLType.DOCUMENT

    def test_determine_url_type_news_by_path(self, processor):
        """パスでニュース判定"""
        metadata = URLMetadata(url="", final_url="", domain="example.com")
        url_type = processor._determine_url_type(
            "https://example.com/news/article123",
            metadata,
            "記事内容",
        )
        assert url_type == URLType.NEWS

    def test_determine_url_type_blog_by_path(self, processor):
        """パスでブログ判定"""
        metadata = URLMetadata(url="", final_url="", domain="example.com")
        url_type = processor._determine_url_type(
            "https://example.com/blog/post123",
            metadata,
            "ブログ内容",
        )
        assert url_type == URLType.BLOG

    def test_determine_url_type_generic(self, processor):
        """一般的なWebページ"""
        metadata = URLMetadata(url="", final_url="", domain="example.com")
        url_type = processor._determine_url_type(
            "https://example.com/about",
            metadata,
            "会社概要",
        )
        assert url_type == URLType.WEBPAGE


# =============================================================================
# TestCalculateUrlConfidence - 確信度計算テスト
# =============================================================================


class TestCalculateUrlConfidence:
    """_calculate_url_confidence()メソッドのテスト"""

    def test_calculate_confidence_high_content(self, processor):
        """高いコンテンツ量で確信度向上"""
        metadata = URLMetadata(url="", final_url="", domain="", redirect_count=0)
        confidence = processor._calculate_url_confidence(metadata, "x" * 6000)
        # 0.7ベース + 0.1（高コンテンツ）= 0.8、浮動小数点誤差を考慮
        assert confidence >= 0.79

    def test_calculate_confidence_low_content(self, processor):
        """低いコンテンツ量で確信度低下"""
        metadata = URLMetadata(url="", final_url="", domain="", redirect_count=0)
        confidence = processor._calculate_url_confidence(metadata, "x" * 100)
        assert confidence <= 0.6

    def test_calculate_confidence_many_redirects(self, processor):
        """多くのリダイレクトで確信度低下"""
        metadata = URLMetadata(url="", final_url="", domain="", redirect_count=5)
        confidence = processor._calculate_url_confidence(metadata, "x" * 3000)
        assert confidence < 0.7


# =============================================================================
# TestMergeUrlEntities - エンティティマージテスト
# =============================================================================


class TestMergeUrlEntities:
    """_merge_url_entities()メソッドのテスト"""

    def test_merge_entities_no_duplicates(self, processor):
        """重複なしでマージ"""
        from lib.capabilities.multimodal.models import ExtractedEntity

        analysis = [
            ExtractedEntity(entity_type="person", value="田中太郎"),
        ]
        pattern = [
            ExtractedEntity(entity_type="email", value="test@example.com"),
        ]
        merged = processor._merge_url_entities(analysis, pattern)

        assert len(merged) == 2

    def test_merge_entities_with_duplicates(self, processor):
        """重複ありでマージ"""
        from lib.capabilities.multimodal.models import ExtractedEntity

        analysis = [
            ExtractedEntity(entity_type="person", value="田中太郎"),
        ]
        pattern = [
            ExtractedEntity(entity_type="person", value="田中太郎"),
            ExtractedEntity(entity_type="email", value="test@example.com"),
        ]
        merged = processor._merge_url_entities(analysis, pattern)

        # 重複は除外される
        assert len(merged) == 2
        values = [e.value for e in merged]
        assert values.count("田中太郎") == 1


# =============================================================================
# TestParseAnalysisResult - 分析結果パーステスト
# =============================================================================


class TestParseAnalysisResult:
    """_parse_analysis_result()メソッドのテスト"""

    def test_parse_json_in_code_block(self, processor):
        """コードブロック内のJSON"""
        content = """
        Here is the analysis:
        ```json
        {"summary": "Test summary", "key_points": ["Point 1", "Point 2"]}
        ```
        """
        result = processor._parse_analysis_result(content)

        assert result["summary"] == "Test summary"
        assert len(result["key_points"]) == 2

    def test_parse_raw_json(self, processor):
        """生のJSON"""
        content = '{"summary": "Direct JSON", "key_points": []}'
        result = processor._parse_analysis_result(content)

        assert result["summary"] == "Direct JSON"

    def test_parse_invalid_json(self, processor):
        """無効なJSONでフォールバック"""
        content = "This is just plain text without any JSON structure."
        result = processor._parse_analysis_result(content)

        assert "summary" in result
        assert result["summary"] == content[:500]


# =============================================================================
# TestFindCompanyRelevance - 会社関連性テスト
# =============================================================================


class TestFindCompanyRelevance:
    """_find_company_relevance()メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_find_company_relevance_default(self, processor):
        """デフォルト実装（簡易版）"""
        relevance, score = await processor._find_company_relevance(
            content="テスト内容",
            summary="テスト要約",
            context=None,
        )

        assert relevance is None
        assert score == 0.0


# =============================================================================
# TestCreateUrlProcessor - ファクトリ関数テスト
# =============================================================================


class TestCreateUrlProcessor:
    """create_url_processor()のテスト"""

    def test_create_with_params(self, mock_pool):
        """パラメータ指定で作成"""
        processor = create_url_processor(
            pool=mock_pool,
            organization_id="org-123",
            api_key="api-key",
        )
        assert isinstance(processor, URLProcessor)
        assert processor._organization_id == "org-123"

    def test_create_without_api_key(self, mock_pool):
        """API Keyなしで作成"""
        processor = create_url_processor(
            pool=mock_pool,
            organization_id="org-123",
        )
        assert processor._api_key is None


# =============================================================================
# TestProcess - 統合テスト
# =============================================================================


class TestProcess:
    """process()メソッドの統合テスト"""

    @pytest.mark.asyncio
    async def test_process_success(self, processor, sample_input, sample_html):
        """正常な処理フロー"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = sample_html
        mock_response.url = "https://example.com/article"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.history = []

        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                    return_value=mock_response
                )
                with patch.object(
                    processor, "_call_text_llm", new=AsyncMock(return_value='{"summary": "Test summary", "key_points": ["Point 1"], "entities": []}')
                ):
                    with patch.object(processor, "_save_processing_log", new=AsyncMock()):
                        result = await processor.process(sample_input)

        assert result.success is True
        assert result.input_type == InputType.URL
        assert result.summary is not None

    @pytest.mark.asyncio
    async def test_process_blocked_url(self, processor):
        """ブロックされたURLでエラー"""
        input_data = MultimodalInput(
            input_type=InputType.URL,
            organization_id="test-org-123",
            url="https://localhost/admin",
        )

        result = await processor.process(input_data)

        assert result.success is False
        assert "ブロック" in result.error_message

    @pytest.mark.asyncio
    async def test_process_fetch_error(self, processor, sample_input):
        """取得エラー"""
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                    side_effect=httpx.TimeoutException("Timeout")
                )
                result = await processor.process(sample_input)

        assert result.success is False
        assert "TIMEOUT" in result.error_code or "timeout" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_process_empty_content(self, processor, sample_input):
        """空コンテンツでエラー"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body></body></html>"
        mock_response.url = "https://example.com/empty"
        mock_response.headers = {}
        mock_response.history = []

        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                    return_value=mock_response
                )
                result = await processor.process(sample_input)

        assert result.success is False
        assert "抽出" in result.error_message or "EXTRACTION" in result.error_code
