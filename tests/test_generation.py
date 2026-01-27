# tests/test_generation.py
"""
Phase G1: 文書生成能力のテスト

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from uuid import uuid4, UUID
from datetime import datetime

# テスト対象のインポート
from lib.capabilities.generation.constants import (
    GenerationType,
    DocumentType,
    GenerationStatus,
    OutputFormat,
    SectionType,
    ConfirmationLevel,
    QualityLevel,
    ToneStyle,
    SUPPORTED_DOCUMENT_TYPES,
    SUPPORTED_OUTPUT_FORMATS,
    MAX_DOCUMENT_SECTIONS,
    MAX_TITLE_LENGTH,
    DEFAULT_GENERATION_MODEL,
    DOCUMENT_TYPE_DEFAULT_SECTIONS,
    DOCUMENT_TYPE_KEYWORDS,
    ERROR_MESSAGES,
)
from lib.capabilities.generation.exceptions import (
    GenerationBaseException,
    ValidationError,
    EmptyTitleError,
    TitleTooLongError,
    InvalidDocumentTypeError,
    InvalidOutputFormatError,
    TooManySectionsError,
    InsufficientContextError,
    GenerationError,
    OutlineGenerationError,
    SectionGenerationError,
    DocumentGenerationError,
    GoogleAPIError,
    GoogleAuthError,
    GoogleDocsCreateError,
    GoogleDocsUpdateError,
    GoogleDriveUploadError,
    GenerationTimeoutError,
    OutlineTimeoutError,
    SectionTimeoutError,
    FullDocumentTimeoutError,
    FeatureDisabledError,
    TemplateNotFoundError,
    LLMError,
    LLMRateLimitError,
)
from lib.capabilities.generation.models import (
    GenerationMetadata,
    ReferenceDocument,
    SectionOutline,
    SectionContent,
    DocumentOutline,
    DocumentRequest,
    DocumentResult,
    GenerationInput,
    GenerationOutput,
)
from lib.capabilities.generation.base import (
    LLMClient,
    BaseGenerator,
)
from lib.capabilities.generation.document_generator import (
    DocumentGenerator,
    create_document_generator,
)
from lib.capabilities.generation.google_docs_client import (
    GoogleDocsClient,
    create_google_docs_client,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def org_id():
    """テスト用組織ID"""
    return uuid4()


@pytest.fixture
def user_id():
    """テスト用ユーザーID"""
    return uuid4()


@pytest.fixture
def mock_pool():
    """モックDBプール"""
    pool = Mock()
    pool.acquire = AsyncMock()
    return pool


@pytest.fixture
def document_request(org_id, user_id):
    """テスト用文書リクエスト"""
    return DocumentRequest(
        title="テスト報告書",
        organization_id=org_id,
        document_type=DocumentType.REPORT,
        purpose="テスト目的",
        instruction="テストの進捗をまとめてください",
        user_id=user_id,
    )


@pytest.fixture
def document_generator(mock_pool, org_id):
    """テスト用文書ジェネレーター"""
    return DocumentGenerator(
        pool=mock_pool,
        organization_id=org_id,
        api_key="test-api-key",
    )


@pytest.fixture
def sample_outline():
    """テスト用アウトライン"""
    sections = [
        SectionOutline(
            section_id=0,
            title="概要",
            description="報告の概要",
            section_type=SectionType.HEADING1,
            estimated_length=300,
            order=0,
        ),
        SectionOutline(
            section_id=1,
            title="詳細",
            description="詳細な内容",
            section_type=SectionType.HEADING1,
            estimated_length=500,
            order=1,
        ),
        SectionOutline(
            section_id=2,
            title="まとめ",
            description="結論",
            section_type=SectionType.HEADING1,
            estimated_length=200,
            order=2,
        ),
    ]
    return DocumentOutline(
        title="テスト報告書",
        document_type=DocumentType.REPORT,
        sections=sections,
    )


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_generation_types(self):
        """生成タイプの定義"""
        assert GenerationType.DOCUMENT.value == "document"
        assert GenerationType.IMAGE.value == "image"
        assert GenerationType.RESEARCH.value == "research"

    def test_document_types(self):
        """文書タイプの定義"""
        assert DocumentType.PROPOSAL.value == "proposal"
        assert DocumentType.REPORT.value == "report"
        assert DocumentType.MINUTES.value == "minutes"
        assert DocumentType.MANUAL.value == "manual"

    def test_generation_status(self):
        """生成ステータスの定義"""
        assert GenerationStatus.PENDING.value == "pending"
        assert GenerationStatus.GENERATING.value == "generating"
        assert GenerationStatus.COMPLETED.value == "completed"
        assert GenerationStatus.FAILED.value == "failed"

    def test_output_format(self):
        """出力フォーマットの定義"""
        assert OutputFormat.GOOGLE_DOCS.value == "google_docs"
        assert OutputFormat.PDF.value == "pdf"
        assert OutputFormat.MARKDOWN.value == "markdown"

    def test_section_type(self):
        """セクションタイプの定義"""
        assert SectionType.TITLE.value == "title"
        assert SectionType.HEADING1.value == "heading1"
        assert SectionType.PARAGRAPH.value == "paragraph"
        assert SectionType.BULLET_LIST.value == "bullet_list"

    def test_quality_level(self):
        """品質レベルの定義"""
        assert QualityLevel.DRAFT.value == "draft"
        assert QualityLevel.STANDARD.value == "standard"
        assert QualityLevel.HIGH_QUALITY.value == "high_quality"
        assert QualityLevel.PREMIUM.value == "premium"

    def test_tone_style(self):
        """トーンスタイルの定義"""
        assert ToneStyle.FORMAL.value == "formal"
        assert ToneStyle.PROFESSIONAL.value == "professional"
        assert ToneStyle.CASUAL.value == "casual"

    def test_supported_document_types(self):
        """サポート文書タイプ"""
        assert "report" in SUPPORTED_DOCUMENT_TYPES
        assert "proposal" in SUPPORTED_DOCUMENT_TYPES
        assert "minutes" in SUPPORTED_DOCUMENT_TYPES

    def test_supported_output_formats(self):
        """サポート出力フォーマット"""
        assert "google_docs" in SUPPORTED_OUTPUT_FORMATS
        assert "pdf" in SUPPORTED_OUTPUT_FORMATS
        assert "markdown" in SUPPORTED_OUTPUT_FORMATS

    def test_size_limits(self):
        """サイズ制限"""
        assert MAX_DOCUMENT_SECTIONS == 50
        assert MAX_TITLE_LENGTH == 200

    def test_default_sections(self):
        """デフォルトセクション"""
        assert "report" in DOCUMENT_TYPE_DEFAULT_SECTIONS
        assert "proposal" in DOCUMENT_TYPE_DEFAULT_SECTIONS
        report_sections = DOCUMENT_TYPE_DEFAULT_SECTIONS["report"]
        assert "概要" in report_sections
        assert "結果" in report_sections

    def test_document_type_keywords(self):
        """文書タイプキーワード"""
        assert "proposal" in DOCUMENT_TYPE_KEYWORDS
        assert "提案" in DOCUMENT_TYPE_KEYWORDS["proposal"]


# =============================================================================
# 例外テスト
# =============================================================================


class TestExceptions:
    """例外のテスト"""

    def test_generation_base_exception(self):
        """基底例外"""
        exc = GenerationBaseException(
            message="テストエラー",
            error_code="TEST_ERROR",
        )
        assert exc.message == "テストエラー"
        assert exc.error_code == "TEST_ERROR"
        assert "テストエラー" in exc.to_user_message()

    def test_empty_title_error(self):
        """タイトル未指定エラー"""
        exc = EmptyTitleError()
        assert exc.error_code == "EMPTY_TITLE"
        assert "タイトル" in exc.to_user_message()

    def test_title_too_long_error(self):
        """タイトル長超過エラー"""
        exc = TitleTooLongError(actual_length=250, max_length=200)
        assert exc.error_code == "TITLE_TOO_LONG"
        assert exc.actual_length == 250
        assert exc.max_length == 200
        assert "250" in exc.to_user_message()
        assert "200" in exc.to_user_message()

    def test_invalid_document_type_error(self):
        """無効な文書タイプエラー"""
        exc = InvalidDocumentTypeError(document_type="invalid_type")
        assert exc.error_code == "INVALID_DOCUMENT_TYPE"
        assert exc.document_type == "invalid_type"

    def test_too_many_sections_error(self):
        """セクション数超過エラー"""
        exc = TooManySectionsError(actual_count=60, max_count=50)
        assert exc.error_code == "TOO_MANY_SECTIONS"
        assert exc.actual_count == 60
        assert exc.max_count == 50

    def test_insufficient_context_error(self):
        """コンテキスト不足エラー"""
        exc = InsufficientContextError(missing_fields=["purpose", "context"])
        assert exc.error_code == "INSUFFICIENT_CONTEXT"
        assert "purpose" in exc.missing_fields

    def test_outline_generation_error(self):
        """アウトライン生成エラー"""
        exc = OutlineGenerationError()
        assert exc.error_code == "OUTLINE_GENERATION_FAILED"
        assert "構成案" in exc.to_user_message()

    def test_section_generation_error(self):
        """セクション生成エラー"""
        exc = SectionGenerationError(section_title="概要", section_index=0)
        assert exc.error_code == "SECTION_GENERATION_FAILED"
        assert exc.section_title == "概要"
        assert "概要" in exc.to_user_message()

    def test_document_generation_error(self):
        """文書生成エラー"""
        exc = DocumentGenerationError(document_title="テスト文書")
        assert exc.error_code == "DOCUMENT_GENERATION_FAILED"
        assert exc.document_title == "テスト文書"

    def test_google_auth_error(self):
        """Google認証エラー"""
        exc = GoogleAuthError()
        assert exc.error_code == "GOOGLE_AUTH_FAILED"
        assert "Google" in exc.to_user_message()

    def test_google_docs_create_error(self):
        """Google Docs作成エラー"""
        exc = GoogleDocsCreateError(document_title="テスト")
        assert exc.error_code == "GOOGLE_DOCS_CREATE_FAILED"

    def test_google_docs_update_error(self):
        """Google Docs更新エラー"""
        exc = GoogleDocsUpdateError(document_id="doc123")
        assert exc.error_code == "GOOGLE_DOCS_UPDATE_FAILED"
        assert exc.document_id == "doc123"

    def test_google_drive_upload_error(self):
        """Google Driveアップロードエラー"""
        exc = GoogleDriveUploadError(file_name="test.pdf")
        assert exc.error_code == "GOOGLE_DRIVE_UPLOAD_FAILED"

    def test_outline_timeout_error(self):
        """アウトライン生成タイムアウト"""
        exc = OutlineTimeoutError(timeout_seconds=60)
        assert exc.error_code == "OUTLINE_TIMEOUT"
        assert exc.timeout_seconds == 60

    def test_section_timeout_error(self):
        """セクション生成タイムアウト"""
        exc = SectionTimeoutError(timeout_seconds=120, section_title="概要")
        assert exc.error_code == "SECTION_TIMEOUT"
        assert "概要" in exc.to_user_message()

    def test_full_document_timeout_error(self):
        """全文書生成タイムアウト"""
        exc = FullDocumentTimeoutError(timeout_seconds=600)
        assert exc.error_code == "FULL_DOCUMENT_TIMEOUT"

    def test_feature_disabled_error(self):
        """機能無効エラー"""
        exc = FeatureDisabledError(feature_name="画像生成")
        assert exc.error_code == "FEATURE_DISABLED"
        assert "画像生成" in exc.to_user_message()

    def test_template_not_found_error(self):
        """テンプレート未発見エラー"""
        exc = TemplateNotFoundError(template_id="tpl123")
        assert exc.error_code == "TEMPLATE_NOT_FOUND"
        assert exc.template_id == "tpl123"

    def test_llm_error(self):
        """LLMエラー"""
        exc = LLMError(message="API error", model="gpt-4")
        assert exc.error_code == "LLM_ERROR"
        assert exc.model == "gpt-4"

    def test_llm_rate_limit_error(self):
        """LLMレート制限エラー"""
        exc = LLMRateLimitError(model="claude", retry_after=60)
        assert exc.error_code == "LLM_RATE_LIMIT"
        assert exc.retry_after == 60
        assert "60秒" in exc.to_user_message()

    def test_exception_to_dict(self):
        """例外の辞書変換"""
        exc = SectionGenerationError(section_title="テスト", section_index=1)
        d = exc.to_dict()
        assert d["error_code"] == "SECTION_GENERATION_FAILED"
        assert d["message"] is not None
        assert "section_title" in d["details"]


# =============================================================================
# モデルテスト
# =============================================================================


class TestModels:
    """モデルのテスト"""

    def test_generation_metadata(self, org_id, user_id):
        """生成メタデータ"""
        metadata = GenerationMetadata(
            organization_id=org_id,
            user_id=user_id,
        )
        assert metadata.organization_id == org_id
        assert metadata.user_id == user_id
        assert metadata.request_id is not None
        assert metadata.started_at is not None

    def test_generation_metadata_complete(self, org_id):
        """メタデータの完了処理"""
        metadata = GenerationMetadata(organization_id=org_id)
        metadata.complete(success=True)
        assert metadata.completed_at is not None
        assert metadata.processing_time_ms is not None

    def test_generation_metadata_to_dict(self, org_id):
        """メタデータの辞書変換"""
        metadata = GenerationMetadata(organization_id=org_id)
        d = metadata.to_dict()
        assert "request_id" in d
        assert "organization_id" in d
        assert "started_at" in d

    def test_reference_document(self):
        """参照文書"""
        ref = ReferenceDocument(
            document_id="doc123",
            title="参考資料",
            source_type="google_docs",
            content="参考内容",
        )
        assert ref.document_id == "doc123"
        assert ref.title == "参考資料"

    def test_reference_document_to_dict(self):
        """参照文書の辞書変換"""
        ref = ReferenceDocument(
            document_id="doc123",
            title="参考資料",
        )
        d = ref.to_dict()
        assert d["document_id"] == "doc123"
        assert d["title"] == "参考資料"

    def test_section_outline(self):
        """セクションアウトライン"""
        outline = SectionOutline(
            section_id=0,
            title="概要",
            description="報告の概要",
            section_type=SectionType.HEADING1,
            estimated_length=500,
        )
        assert outline.section_id == 0
        assert outline.title == "概要"
        assert outline.section_type == SectionType.HEADING1

    def test_section_outline_to_dict(self):
        """セクションアウトラインの辞書変換"""
        outline = SectionOutline(
            section_id=0,
            title="概要",
        )
        d = outline.to_dict()
        assert d["section_id"] == 0
        assert d["title"] == "概要"

    def test_section_content(self):
        """セクションコンテンツ"""
        content = SectionContent(
            section_id=0,
            title="概要",
            content="これは概要です。",
            section_type=SectionType.HEADING1,
        )
        assert content.section_id == 0
        assert content.title == "概要"
        assert content.content == "これは概要です。"
        assert content.word_count == len("これは概要です。")

    def test_section_content_to_markdown(self):
        """セクションのMarkdown変換"""
        content = SectionContent(
            section_id=0,
            title="概要",
            content="これは概要です。",
            section_type=SectionType.HEADING1,
        )
        md = content.to_markdown()
        assert "## 概要" in md
        assert "これは概要です。" in md

    def test_document_outline(self, sample_outline):
        """文書アウトライン"""
        assert sample_outline.title == "テスト報告書"
        assert sample_outline.document_type == DocumentType.REPORT
        assert len(sample_outline.sections) == 3
        assert sample_outline.estimated_total_length == 1000  # 300 + 500 + 200

    def test_document_outline_to_user_display(self, sample_outline):
        """アウトラインのユーザー表示"""
        display = sample_outline.to_user_display()
        assert "テスト報告書" in display
        assert "概要" in display
        assert "詳細" in display
        assert "まとめ" in display
        assert "1,000" in display  # 想定文字数

    def test_document_request(self, document_request, org_id):
        """文書リクエスト"""
        assert document_request.title == "テスト報告書"
        assert document_request.organization_id == org_id
        assert document_request.document_type == DocumentType.REPORT

    def test_document_request_to_dict(self, document_request):
        """リクエストの辞書変換"""
        d = document_request.to_dict()
        assert d["title"] == "テスト報告書"
        assert d["document_type"] == "report"

    def test_document_result_pending(self, sample_outline):
        """保留中の文書結果"""
        result = DocumentResult(
            status=GenerationStatus.PENDING,
            success=True,
            document_title="テスト",
            outline=sample_outline,
        )
        assert result.status == GenerationStatus.PENDING
        assert "構成で進めていい" in result.to_user_message()

    def test_document_result_completed(self):
        """完了した文書結果"""
        result = DocumentResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            document_id="doc123",
            document_url="https://docs.google.com/document/d/doc123",
            document_title="テスト報告書",
            total_word_count=1000,
            metadata=GenerationMetadata(estimated_cost_jpy=45.0),
        )
        msg = result.to_user_message()
        assert "完成" in msg
        assert "テスト報告書" in msg
        assert "https://docs.google.com" in msg

    def test_document_result_failed(self):
        """失敗した文書結果"""
        result = DocumentResult(
            status=GenerationStatus.FAILED,
            success=False,
            document_title="テスト",
            error_message="タイムアウト",
        )
        msg = result.to_user_message()
        assert "失敗" in msg
        assert "タイムアウト" in msg

    def test_document_result_to_brain_context(self):
        """脳コンテキスト用文字列"""
        result = DocumentResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            document_url="https://docs.google.com/document/d/doc123",
            document_title="テスト",
            total_word_count=1000,
        )
        ctx = result.to_brain_context()
        assert "テスト" in ctx
        assert "completed" in ctx

    def test_generation_input(self, org_id, document_request):
        """生成入力"""
        input_data = GenerationInput(
            generation_type=GenerationType.DOCUMENT,
            organization_id=org_id,
            document_request=document_request,
        )
        assert input_data.generation_type == GenerationType.DOCUMENT
        assert input_data.get_request() == document_request

    def test_generation_output(self):
        """生成出力"""
        result = DocumentResult(
            status=GenerationStatus.COMPLETED,
            success=True,
        )
        output = GenerationOutput(
            generation_type=GenerationType.DOCUMENT,
            success=True,
            status=GenerationStatus.COMPLETED,
            document_result=result,
        )
        assert output.generation_type == GenerationType.DOCUMENT
        assert output.get_result() == result


# =============================================================================
# LLMクライアントテスト
# =============================================================================


class TestLLMClient:
    """LLMクライアントのテスト"""

    def test_init(self):
        """初期化"""
        client = LLMClient(api_key="test-key")
        assert client._api_key == "test-key"
        assert client._default_model == DEFAULT_GENERATION_MODEL

    def test_get_model_for_quality_draft(self):
        """ドラフト品質のモデル"""
        client = LLMClient(api_key="test-key")
        model = client.get_model_for_quality(QualityLevel.DRAFT)
        assert "haiku" in model.lower()

    def test_get_model_for_quality_premium(self):
        """プレミアム品質のモデル"""
        client = LLMClient(api_key="test-key")
        model = client.get_model_for_quality(QualityLevel.PREMIUM)
        assert "opus" in model.lower()

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """正常な生成"""
        client = LLMClient(api_key="test-key")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "テスト応答"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await client.generate("テストプロンプト")

            assert result["text"] == "テスト応答"
            assert result["total_tokens"] == 30

    @pytest.mark.asyncio
    async def test_generate_json_success(self):
        """JSON生成の成功"""
        client = LLMClient(api_key="test-key")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"key": "value"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await client.generate_json("JSONで出力")

            assert result["parsed"] == {"key": "value"}


# =============================================================================
# DocumentGeneratorテスト
# =============================================================================


class TestDocumentGenerator:
    """DocumentGeneratorのテスト"""

    def test_init(self, mock_pool, org_id):
        """初期化"""
        generator = DocumentGenerator(
            pool=mock_pool,
            organization_id=org_id,
            api_key="test-key",
        )
        assert generator._organization_id == org_id
        assert generator._generation_type == GenerationType.DOCUMENT

    def test_validate_success(self, document_generator, document_request, org_id):
        """検証成功"""
        input_data = GenerationInput(
            generation_type=GenerationType.DOCUMENT,
            organization_id=org_id,
            document_request=document_request,
        )
        # 例外が発生しなければ成功
        document_generator.validate(input_data)

    def test_validate_no_request(self, document_generator, org_id):
        """リクエストなしエラー"""
        input_data = GenerationInput(
            generation_type=GenerationType.DOCUMENT,
            organization_id=org_id,
        )
        with pytest.raises(ValidationError):
            document_generator.validate(input_data)

    def test_validate_empty_title(self, document_generator, org_id):
        """空タイトルエラー"""
        request = DocumentRequest(
            title="",
            organization_id=org_id,
        )
        input_data = GenerationInput(
            generation_type=GenerationType.DOCUMENT,
            organization_id=org_id,
            document_request=request,
        )
        with pytest.raises(EmptyTitleError):
            document_generator.validate(input_data)

    def test_validate_title_too_long(self, document_generator, org_id):
        """タイトル長超過エラー"""
        request = DocumentRequest(
            title="あ" * 300,  # 300文字
            organization_id=org_id,
        )
        input_data = GenerationInput(
            generation_type=GenerationType.DOCUMENT,
            organization_id=org_id,
            document_request=request,
        )
        with pytest.raises(TitleTooLongError):
            document_generator.validate(input_data)

    def test_detect_document_type_proposal(self, document_generator):
        """提案書タイプの検出"""
        doc_type = document_generator.detect_document_type("来週の提案書を作成して")
        assert doc_type == DocumentType.PROPOSAL

    def test_detect_document_type_report(self, document_generator):
        """報告書タイプの検出"""
        doc_type = document_generator.detect_document_type("進捗レポートを作って")
        assert doc_type == DocumentType.REPORT

    def test_detect_document_type_minutes(self, document_generator):
        """議事録タイプの検出"""
        doc_type = document_generator.detect_document_type("今日の議事録を作成")
        assert doc_type == DocumentType.MINUTES

    def test_detect_document_type_unknown(self, document_generator):
        """不明な文書タイプ"""
        doc_type = document_generator.detect_document_type("何か作って")
        assert doc_type == DocumentType.CUSTOM

    @pytest.mark.asyncio
    async def test_generate_outline_with_custom(
        self, document_generator, document_request, sample_outline
    ):
        """カスタムアウトラインでの生成"""
        document_request.custom_outline = sample_outline
        outline = await document_generator._generate_outline(document_request)
        assert outline == sample_outline

    @pytest.mark.asyncio
    async def test_generate_outline_with_defaults(
        self, document_generator, org_id
    ):
        """デフォルトセクションでの生成"""
        request = DocumentRequest(
            title="テスト報告書",
            organization_id=org_id,
            document_type=DocumentType.REPORT,
            # instruction なし → デフォルト使用
        )
        outline = await document_generator._generate_outline(request)
        assert outline.title == "テスト報告書"
        assert len(outline.sections) > 0

    @pytest.mark.asyncio
    async def test_generate_pending(
        self, document_generator, document_request, org_id, sample_outline
    ):
        """確認待ちの生成"""
        document_request.require_confirmation = True
        document_request.custom_outline = sample_outline

        input_data = GenerationInput(
            generation_type=GenerationType.DOCUMENT,
            organization_id=org_id,
            document_request=document_request,
        )

        output = await document_generator.generate(input_data)

        assert output.status == GenerationStatus.PENDING
        assert output.success
        assert output.document_result.outline is not None

    @pytest.mark.asyncio
    async def test_generate_full_document(
        self, document_generator, document_request, org_id, sample_outline
    ):
        """全文書生成"""
        document_request.require_confirmation = False
        document_request.custom_outline = sample_outline

        input_data = GenerationInput(
            generation_type=GenerationType.DOCUMENT,
            organization_id=org_id,
            document_request=document_request,
        )

        # Google Docsモック
        with patch.object(
            document_generator._google_client,
            "create_document",
            new_callable=AsyncMock,
            return_value={
                "document_id": "doc123",
                "document_url": "https://docs.google.com/document/d/doc123",
            },
        ):
            with patch.object(
                document_generator._google_client,
                "update_document",
                new_callable=AsyncMock,
                return_value=True,
            ):
                # LLMモック
                with patch.object(
                    document_generator,
                    "_call_llm",
                    new_callable=AsyncMock,
                    return_value={
                        "text": "テストコンテンツ",
                        "model": "claude-sonnet",
                        "total_tokens": 100,
                    },
                ):
                    output = await document_generator.generate(input_data)

        assert output.success
        assert output.status == GenerationStatus.COMPLETED
        assert output.document_result.document_url == "https://docs.google.com/document/d/doc123"


# =============================================================================
# GoogleDocsClientテスト
# =============================================================================


class TestGoogleDocsClient:
    """GoogleDocsClientのテスト"""

    def test_init(self):
        """初期化"""
        client = GoogleDocsClient(credentials_path="/path/to/creds.json")
        assert client._credentials_path == "/path/to/creds.json"

    def test_get_heading_style(self):
        """見出しスタイルの取得"""
        client = GoogleDocsClient()
        assert client._get_heading_style(SectionType.TITLE) == "TITLE"
        assert client._get_heading_style(SectionType.HEADING1) == "HEADING_1"
        assert client._get_heading_style(SectionType.HEADING2) == "HEADING_2"

    def test_markdown_to_requests_heading(self):
        """Markdown見出しの変換"""
        client = GoogleDocsClient()
        requests = client._markdown_to_requests("# タイトル\n\n本文")
        assert len(requests) > 0
        # 見出しと本文のリクエストがある
        insert_requests = [r for r in requests if "insertText" in r]
        assert len(insert_requests) >= 2

    def test_markdown_to_requests_bullet(self):
        """Markdown箇条書きの変換"""
        client = GoogleDocsClient()
        requests = client._markdown_to_requests("- アイテム1\n- アイテム2")
        bullet_requests = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullet_requests) == 2

    def test_markdown_to_requests_numbered(self):
        """Markdown番号付きリストの変換"""
        client = GoogleDocsClient()
        requests = client._markdown_to_requests("1. 項目1\n2. 項目2")
        bullet_requests = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullet_requests) == 2


# =============================================================================
# ファクトリ関数テスト
# =============================================================================


class TestFactoryFunctions:
    """ファクトリ関数のテスト"""

    def test_create_document_generator(self, mock_pool, org_id):
        """DocumentGenerator作成"""
        generator = create_document_generator(
            pool=mock_pool,
            organization_id=org_id,
        )
        assert isinstance(generator, DocumentGenerator)
        assert generator._organization_id == org_id

    def test_create_google_docs_client(self):
        """GoogleDocsClient作成"""
        client = create_google_docs_client(
            credentials_path="/path/to/creds.json"
        )
        assert isinstance(client, GoogleDocsClient)


# =============================================================================
# パッケージインポートテスト
# =============================================================================


class TestPackageImports:
    """パッケージインポートのテスト"""

    def test_import_generation_types(self):
        """生成タイプのインポート"""
        from lib.capabilities.generation import (
            GenerationType,
            DocumentType,
            GenerationStatus,
        )
        assert GenerationType.DOCUMENT.value == "document"
        assert DocumentType.REPORT.value == "report"

    def test_import_constants(self):
        """定数のインポート"""
        from lib.capabilities.generation import (
            MAX_DOCUMENT_SECTIONS,
            MAX_TITLE_LENGTH,
            DEFAULT_GENERATION_MODEL,
        )
        assert MAX_DOCUMENT_SECTIONS == 50
        assert MAX_TITLE_LENGTH == 200

    def test_import_exceptions(self):
        """例外のインポート"""
        from lib.capabilities.generation import (
            GenerationBaseException,
            EmptyTitleError,
            OutlineGenerationError,
            GoogleDocsCreateError,
        )
        assert issubclass(EmptyTitleError, GenerationBaseException)

    def test_import_models(self):
        """モデルのインポート"""
        from lib.capabilities.generation import (
            DocumentRequest,
            DocumentResult,
            DocumentOutline,
            GenerationInput,
            GenerationOutput,
        )
        assert DocumentRequest is not None
        assert DocumentResult is not None

    def test_import_generator(self):
        """ジェネレーターのインポート"""
        from lib.capabilities.generation import (
            DocumentGenerator,
            create_document_generator,
        )
        assert DocumentGenerator is not None
        assert create_document_generator is not None

    def test_import_google_client(self):
        """Googleクライアントのインポート"""
        from lib.capabilities.generation import (
            GoogleDocsClient,
            create_google_docs_client,
        )
        assert GoogleDocsClient is not None


# =============================================================================
# 統合テスト
# =============================================================================


class TestIntegration:
    """統合テスト"""

    @pytest.mark.asyncio
    async def test_full_workflow(self, mock_pool, org_id, user_id):
        """全体ワークフロー"""
        # リクエスト作成
        request = DocumentRequest(
            title="週次報告書",
            organization_id=org_id,
            user_id=user_id,
            document_type=DocumentType.REPORT,
            purpose="週次の進捗を報告する",
            instruction="今週の成果と来週の予定をまとめてください",
            require_confirmation=True,
        )

        # 入力構築
        input_data = GenerationInput(
            generation_type=GenerationType.DOCUMENT,
            organization_id=org_id,
            document_request=request,
        )

        # ジェネレーター作成
        generator = create_document_generator(
            pool=mock_pool,
            organization_id=org_id,
            api_key="test-key",
        )

        # アウトライン生成（LLMをモック）
        with patch.object(
            generator._llm_client,
            "generate_json",
            new_callable=AsyncMock,
            return_value={
                "text": '{"sections": [{"title": "概要"}, {"title": "詳細"}]}',
                "parsed": {
                    "sections": [
                        {"title": "概要", "description": "概要説明"},
                        {"title": "詳細", "description": "詳細説明"},
                    ]
                },
                "total_tokens": 50,
            },
        ):
            output = await generator.generate(input_data)

        # 確認待ち状態
        assert output.status == GenerationStatus.PENDING
        assert output.document_result.outline is not None
        assert len(output.document_result.outline.sections) == 2

        # ユーザー表示
        display = output.document_result.outline.to_user_display()
        assert "週次報告書" in display
        assert "概要" in display
