# tests/test_multimodal.py
"""
Phase M1: Multimodal入力能力 テスト

このモジュールは、Multimodal入力処理のユニットテストを定義します。

テスト対象:
- 定数・列挙型
- 例外クラス
- データモデル
- ImageProcessor
- PDFProcessor
- URLProcessor

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
import json
import io


# =============================================================================
# テスト対象のインポート
# =============================================================================

from lib.capabilities.multimodal import (
    # 定数
    InputType,
    ProcessingStatus,
    ImageType,
    PDFType,
    URLType,
    ContentConfidenceLevel,
    SUPPORTED_IMAGE_FORMATS,
    MAX_IMAGE_SIZE_BYTES,
    MAX_PDF_PAGES,

    # 例外
    MultimodalBaseException,
    ValidationError,
    FileTooLargeError,
    TooManyPagesError,
    ImageDecodeError,
    PDFEncryptedError,
    URLBlockedError,
    URLFetchError,
    VisionAPIError,

    # モデル
    ProcessingMetadata,
    ExtractedEntity,
    ImageMetadata,
    ImageAnalysisResult,
    PDFMetadata,
    PDFAnalysisResult,
    URLMetadata,
    URLAnalysisResult,
    MultimodalInput,
    MultimodalOutput,

    # プロセッサー
    ImageProcessor,
    PDFProcessor,
    URLProcessor,
    VisionAPIClient,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_pool():
    """DBプールのモック"""
    return MagicMock()


@pytest.fixture
def organization_id():
    """テスト用組織ID"""
    return "org_test_multimodal"


@pytest.fixture
def sample_image_bytes():
    """サンプル画像バイト（PILで生成した有効なPNG）"""
    from PIL import Image

    # 10x10ピクセルの赤い画像を生成
    img = Image.new('RGB', (10, 10), color='red')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()


@pytest.fixture
def sample_pdf_bytes():
    """サンプルPDFバイト（最小限のPDF）"""
    return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
trailer
<< /Size 4 /Root 1 0 R >>
startxref
196
%%EOF"""


@pytest.fixture
def mock_vision_response():
    """Vision APIレスポンスのモック"""
    return {
        "content": json.dumps({
            "image_type": "document",
            "description": "領収書の画像",
            "extracted_text": "スターバックス\n2026/01/27\n¥1,280",
            "entities": [
                {"type": "organization", "value": "スターバックス", "confidence": 0.9},
                {"type": "date", "value": "2026/01/27", "confidence": 0.95},
                {"type": "amount", "value": "¥1,280", "confidence": 0.9},
            ],
            "structured_data": {
                "store_name": "スターバックス",
                "date": "2026/01/27",
                "amount": "¥1,280",
            },
            "confidence": 0.85,
        }),
        "input_tokens": 500,
        "output_tokens": 200,
        "model": "google/gemini-2.0-flash-001",
    }


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数・列挙型のテスト"""

    def test_input_type_values(self):
        """InputTypeの値が正しいこと"""
        assert InputType.IMAGE.value == "image"
        assert InputType.PDF.value == "pdf"
        assert InputType.URL.value == "url"
        assert InputType.AUDIO.value == "audio"
        assert InputType.VIDEO.value == "video"

    def test_processing_status_values(self):
        """ProcessingStatusの値が正しいこと"""
        assert ProcessingStatus.PENDING.value == "pending"
        assert ProcessingStatus.PROCESSING.value == "processing"
        assert ProcessingStatus.COMPLETED.value == "completed"
        assert ProcessingStatus.FAILED.value == "failed"

    def test_image_type_values(self):
        """ImageTypeの値が正しいこと"""
        assert ImageType.PHOTO.value == "photo"
        assert ImageType.DOCUMENT.value == "document"
        assert ImageType.DIAGRAM.value == "diagram"

    def test_pdf_type_values(self):
        """PDFTypeの値が正しいこと"""
        assert PDFType.TEXT_BASED.value == "text_based"
        assert PDFType.SCANNED.value == "scanned"
        assert PDFType.MIXED.value == "mixed"
        assert PDFType.ENCRYPTED.value == "encrypted"

    def test_url_type_values(self):
        """URLTypeの値が正しいこと"""
        assert URLType.WEBPAGE.value == "webpage"
        assert URLType.NEWS.value == "news"
        assert URLType.BLOG.value == "blog"

    def test_confidence_level_from_score(self):
        """確信度スコアからレベル変換が正しいこと"""
        assert ContentConfidenceLevel.from_score(0.95) == ContentConfidenceLevel.VERY_HIGH
        assert ContentConfidenceLevel.from_score(0.8) == ContentConfidenceLevel.HIGH
        assert ContentConfidenceLevel.from_score(0.6) == ContentConfidenceLevel.MEDIUM
        assert ContentConfidenceLevel.from_score(0.4) == ContentConfidenceLevel.LOW
        assert ContentConfidenceLevel.from_score(0.2) == ContentConfidenceLevel.VERY_LOW

    def test_supported_image_formats(self):
        """サポートする画像フォーマットが定義されていること"""
        assert "jpg" in SUPPORTED_IMAGE_FORMATS
        assert "jpeg" in SUPPORTED_IMAGE_FORMATS
        assert "png" in SUPPORTED_IMAGE_FORMATS
        assert "gif" in SUPPORTED_IMAGE_FORMATS
        assert "webp" in SUPPORTED_IMAGE_FORMATS

    def test_max_size_constants(self):
        """サイズ制限定数が定義されていること"""
        assert MAX_IMAGE_SIZE_BYTES == 20 * 1024 * 1024  # 20MB
        assert MAX_PDF_PAGES == 100


# =============================================================================
# 例外テスト
# =============================================================================


class TestExceptions:
    """例外クラスのテスト"""

    def test_base_exception(self):
        """基底例外の動作確認"""
        exc = MultimodalBaseException(
            message="Test error",
            error_code="TEST_ERROR",
            input_type=InputType.IMAGE,
            details={"key": "value"},
        )

        assert exc.message == "Test error"
        assert exc.error_code == "TEST_ERROR"
        assert exc.input_type == InputType.IMAGE
        assert exc.details == {"key": "value"}

        d = exc.to_dict()
        assert d["error"] == "TEST_ERROR"
        assert d["message"] == "Test error"
        assert d["input_type"] == "image"

    def test_validation_error(self):
        """ValidationErrorの動作確認"""
        exc = ValidationError(
            message="Invalid input",
            field="image_data",
            input_type=InputType.IMAGE,
        )

        assert exc.error_code == "VALIDATION_ERROR"
        assert exc.field == "image_data"

    def test_file_too_large_error(self):
        """FileTooLargeErrorの動作確認"""
        exc = FileTooLargeError(
            actual_size_bytes=30 * 1024 * 1024,
            max_size_bytes=20 * 1024 * 1024,
            input_type=InputType.IMAGE,
        )

        assert exc.error_code == "VALIDATION_ERROR"
        assert "30.0MB" in exc.message
        assert "20.0MB" in exc.message

    def test_too_many_pages_error(self):
        """TooManyPagesErrorの動作確認"""
        exc = TooManyPagesError(actual_pages=150, max_pages=100)

        assert exc.error_code == "VALIDATION_ERROR"
        assert "150ページ" in exc.message
        assert "100ページ" in exc.message

    def test_url_blocked_error(self):
        """URLBlockedErrorの動作確認"""
        exc = URLBlockedError("http://localhost/secret", "ローカルホスト")

        assert exc.error_code == "URL_BLOCKED"
        assert "セキュリティ" in exc.message

    def test_url_fetch_error_404(self):
        """URLFetchError 404の動作確認"""
        exc = URLFetchError("https://example.com/notfound", status_code=404)

        assert exc.error_code == "URL_FETCH_ERROR"
        assert "404" in exc.message

    def test_url_fetch_error_403(self):
        """URLFetchError 403の動作確認"""
        exc = URLFetchError("https://example.com/forbidden", status_code=403)

        assert "403" in exc.message

    def test_vision_api_error(self):
        """VisionAPIErrorの動作確認"""
        original = Exception("API failed")
        exc = VisionAPIError(
            message="Vision API error",
            model="gpt-4o",
            original_error=original,
        )

        assert exc.error_code == "VISION_API_ERROR"
        assert exc.model == "gpt-4o"
        assert exc.original_error == original

    def test_user_message_generation(self):
        """ユーザー向けメッセージ生成の確認"""
        exc = MultimodalBaseException(message="エラーが発生しました")
        user_msg = exc.to_user_message()

        assert "ごめんウル" in user_msg
        assert "エラーが発生しました" in user_msg


# =============================================================================
# モデルテスト
# =============================================================================


class TestModels:
    """データモデルのテスト"""

    def test_processing_metadata(self):
        """ProcessingMetadataの動作確認"""
        metadata = ProcessingMetadata(
            processing_id="proc_001",
            organization_id="org_test",
            input_type=InputType.IMAGE,
            status=ProcessingStatus.COMPLETED,
        )

        assert metadata.is_successful
        d = metadata.to_dict()
        assert d["processing_id"] == "proc_001"
        assert d["input_type"] == "image"
        assert d["status"] == "completed"

    def test_extracted_entity(self):
        """ExtractedEntityの動作確認"""
        entity = ExtractedEntity(
            entity_type="amount",
            value="¥1,280",
            confidence=0.9,
            context="金額: ¥1,280",
        )

        d = entity.to_dict()
        assert d["entity_type"] == "amount"
        assert d["value"] == "¥1,280"
        assert d["confidence"] == 0.9
        assert d["context"] == "金額: ¥1,280"

    def test_image_analysis_result(self):
        """ImageAnalysisResultの動作確認"""
        result = ImageAnalysisResult(
            success=True,
            image_type=ImageType.DOCUMENT,
            description="領収書",
            extracted_text="テスト",
            overall_confidence=0.85,
        )

        assert result.success
        d = result.to_dict()
        assert d["image_type"] == "document"

        ctx = result.to_brain_context()
        assert "画像解析結果" in ctx
        assert "document" in ctx

    def test_pdf_analysis_result(self):
        """PDFAnalysisResultの動作確認"""
        metadata = PDFMetadata(page_count=10, title="テストPDF")
        result = PDFAnalysisResult(
            success=True,
            pdf_type=PDFType.TEXT_BASED,
            pdf_metadata=metadata,
            summary="PDFの要約",
            key_points=["ポイント1", "ポイント2"],
        )

        assert result.success
        d = result.to_dict()
        assert d["pdf_type"] == "text_based"
        assert d["page_count"] == 10

    def test_url_analysis_result(self):
        """URLAnalysisResultの動作確認"""
        metadata = URLMetadata(
            url="https://example.com",
            domain="example.com",
            title="Example Page",
        )
        result = URLAnalysisResult(
            success=True,
            url_type=URLType.WEBPAGE,
            url_metadata=metadata,
            summary="ページの要約",
        )

        assert result.success
        d = result.to_dict()
        assert d["url_type"] == "webpage"
        assert d["domain"] == "example.com"

    def test_multimodal_input_validation(self):
        """MultimodalInputのバリデーション"""
        # 有効な入力
        valid_input = MultimodalInput(
            input_type=InputType.IMAGE,
            organization_id="org_test",
            image_data=b"fake_image_data",
        )
        assert valid_input.validate()

        # 無効な入力（データなし）
        invalid_input = MultimodalInput(
            input_type=InputType.IMAGE,
            organization_id="org_test",
        )
        assert not invalid_input.validate()

        # 無効な入力（organization_idなし）
        invalid_input2 = MultimodalInput(
            input_type=InputType.IMAGE,
            organization_id="",
            image_data=b"fake",
        )
        assert not invalid_input2.validate()

    def test_multimodal_output(self):
        """MultimodalOutputの動作確認"""
        image_result = ImageAnalysisResult(success=True)
        output = MultimodalOutput(
            success=True,
            input_type=InputType.IMAGE,
            image_result=image_result,
            summary="テスト",
        )

        assert output.get_result() == image_result
        d = output.to_dict()
        assert d["success"]
        assert d["input_type"] == "image"


# =============================================================================
# ImageProcessorテスト
# =============================================================================


class TestImageProcessor:
    """ImageProcessorのテスト"""

    def test_init(self, mock_pool, organization_id):
        """初期化の確認"""
        processor = ImageProcessor(mock_pool, organization_id)

        assert processor._organization_id == organization_id
        assert processor._input_type == InputType.IMAGE

    def test_validate_success(self, mock_pool, organization_id, sample_image_bytes):
        """有効な入力の検証成功"""
        processor = ImageProcessor(mock_pool, organization_id)
        input_data = MultimodalInput(
            input_type=InputType.IMAGE,
            organization_id=organization_id,
            image_data=sample_image_bytes,
        )

        # 例外が発生しないこと
        processor.validate(input_data)

    def test_validate_wrong_input_type(self, mock_pool, organization_id):
        """入力タイプが間違っている場合"""
        processor = ImageProcessor(mock_pool, organization_id)
        input_data = MultimodalInput(
            input_type=InputType.PDF,
            organization_id=organization_id,
            pdf_data=b"fake",
        )

        with pytest.raises(ValidationError) as exc_info:
            processor.validate(input_data)

        assert "expected IMAGE" in str(exc_info.value)

    def test_validate_no_data(self, mock_pool, organization_id):
        """データがない場合"""
        processor = ImageProcessor(mock_pool, organization_id)
        input_data = MultimodalInput(
            input_type=InputType.IMAGE,
            organization_id=organization_id,
        )

        with pytest.raises(ValidationError) as exc_info:
            processor.validate(input_data)

        assert "must be provided" in str(exc_info.value)

    def test_validate_file_too_large(self, mock_pool, organization_id):
        """ファイルサイズ超過の場合"""
        processor = ImageProcessor(mock_pool, organization_id)

        # 21MBのデータ
        large_data = b"x" * (21 * 1024 * 1024)
        input_data = MultimodalInput(
            input_type=InputType.IMAGE,
            organization_id=organization_id,
            image_data=large_data,
        )

        with pytest.raises(FileTooLargeError):
            processor.validate(input_data)

    @pytest.mark.asyncio
    async def test_process_success(self, mock_pool, organization_id, sample_image_bytes, mock_vision_response):
        """正常な処理の確認"""
        processor = ImageProcessor(mock_pool, organization_id)

        with patch.object(processor._vision_client, 'analyze_with_fallback', new_callable=AsyncMock) as mock_analyze:
            mock_analyze.return_value = mock_vision_response

            input_data = MultimodalInput(
                input_type=InputType.IMAGE,
                organization_id=organization_id,
                image_data=sample_image_bytes,
                instruction="領収書を読み取って",
            )

            result = await processor.process(input_data)

            assert result.success
            assert result.input_type == InputType.IMAGE
            assert result.image_result is not None
            assert result.image_result.image_type == ImageType.DOCUMENT
            assert len(result.entities) > 0

    @pytest.mark.asyncio
    async def test_process_vision_api_error(self, mock_pool, organization_id, sample_image_bytes):
        """Vision APIエラー時の処理"""
        processor = ImageProcessor(mock_pool, organization_id)

        with patch.object(processor._vision_client, 'analyze_with_fallback', new_callable=AsyncMock) as mock_analyze:
            mock_analyze.side_effect = VisionAPIError("API failed")

            input_data = MultimodalInput(
                input_type=InputType.IMAGE,
                organization_id=organization_id,
                image_data=sample_image_bytes,
            )

            result = await processor.process(input_data)

            assert not result.success
            assert result.error_message is not None


# =============================================================================
# PDFProcessorテスト
# =============================================================================


class TestPDFProcessor:
    """PDFProcessorのテスト"""

    def test_init(self, mock_pool, organization_id):
        """初期化の確認"""
        processor = PDFProcessor(mock_pool, organization_id)

        assert processor._organization_id == organization_id
        assert processor._input_type == InputType.PDF

    def test_validate_success(self, mock_pool, organization_id, sample_pdf_bytes):
        """有効な入力の検証成功"""
        processor = PDFProcessor(mock_pool, organization_id)
        input_data = MultimodalInput(
            input_type=InputType.PDF,
            organization_id=organization_id,
            pdf_data=sample_pdf_bytes,
        )

        processor.validate(input_data)

    def test_validate_wrong_input_type(self, mock_pool, organization_id):
        """入力タイプが間違っている場合"""
        processor = PDFProcessor(mock_pool, organization_id)
        input_data = MultimodalInput(
            input_type=InputType.IMAGE,
            organization_id=organization_id,
            image_data=b"fake",
        )

        with pytest.raises(ValidationError) as exc_info:
            processor.validate(input_data)

        assert "expected PDF" in str(exc_info.value)


# =============================================================================
# URLProcessorテスト
# =============================================================================


class TestURLProcessor:
    """URLProcessorのテスト"""

    def test_init(self, mock_pool, organization_id):
        """初期化の確認"""
        processor = URLProcessor(mock_pool, organization_id)

        assert processor._organization_id == organization_id
        assert processor._input_type == InputType.URL

    def test_validate_success(self, mock_pool, organization_id):
        """有効なURLの検証成功"""
        processor = URLProcessor(mock_pool, organization_id)
        input_data = MultimodalInput(
            input_type=InputType.URL,
            organization_id=organization_id,
            url="https://example.com/article",
        )

        processor.validate(input_data)

    def test_validate_no_url(self, mock_pool, organization_id):
        """URLがない場合"""
        processor = URLProcessor(mock_pool, organization_id)
        input_data = MultimodalInput(
            input_type=InputType.URL,
            organization_id=organization_id,
        )

        with pytest.raises(ValidationError) as exc_info:
            processor.validate(input_data)

        assert "must be provided" in str(exc_info.value)

    def test_validate_invalid_url(self, mock_pool, organization_id):
        """無効なURL形式の場合"""
        processor = URLProcessor(mock_pool, organization_id)
        input_data = MultimodalInput(
            input_type=InputType.URL,
            organization_id=organization_id,
            url="not-a-valid-url",
        )

        with pytest.raises((ValidationError, Exception)):
            processor.validate(input_data)

    def test_validate_unsupported_protocol(self, mock_pool, organization_id):
        """サポートしていないプロトコルの場合"""
        processor = URLProcessor(mock_pool, organization_id)
        input_data = MultimodalInput(
            input_type=InputType.URL,
            organization_id=organization_id,
            url="ftp://example.com/file",
        )

        with pytest.raises(ValidationError) as exc_info:
            processor.validate(input_data)

        assert "Unsupported protocol" in str(exc_info.value)

    def test_security_check_localhost(self, mock_pool, organization_id):
        """localhostがブロックされること"""
        processor = URLProcessor(mock_pool, organization_id)

        with pytest.raises(URLBlockedError):
            processor._check_url_security("http://localhost/secret")

    def test_security_check_127_0_0_1(self, mock_pool, organization_id):
        """127.0.0.1がブロックされること"""
        processor = URLProcessor(mock_pool, organization_id)

        with pytest.raises(URLBlockedError):
            processor._check_url_security("http://127.0.0.1/secret")

    def test_determine_url_type_news(self, mock_pool, organization_id):
        """ニュースサイトの判定"""
        processor = URLProcessor(mock_pool, organization_id)
        metadata = URLMetadata(domain="news.yahoo.co.jp")

        url_type = processor._determine_url_type(
            "https://news.yahoo.co.jp/article/123",
            metadata,
            "記事の内容",
        )

        assert url_type == URLType.NEWS

    def test_determine_url_type_blog(self, mock_pool, organization_id):
        """ブログサイトの判定"""
        processor = URLProcessor(mock_pool, organization_id)
        metadata = URLMetadata(domain="note.com")

        url_type = processor._determine_url_type(
            "https://note.com/user/n/abc123",
            metadata,
            "ブログの内容",
        )

        assert url_type == URLType.BLOG


# =============================================================================
# VisionAPIClientテスト
# =============================================================================


class TestVisionAPIClient:
    """VisionAPIClientのテスト"""

    def test_detect_image_format_png(self):
        """PNGフォーマット検出"""
        client = VisionAPIClient()
        png_header = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100

        assert client._detect_image_format(png_header) == "png"

    def test_detect_image_format_jpeg(self):
        """JPEGフォーマット検出"""
        client = VisionAPIClient()
        jpeg_header = b'\xff\xd8' + b'\x00' * 100

        assert client._detect_image_format(jpeg_header) == "jpeg"

    def test_detect_image_format_gif(self):
        """GIFフォーマット検出"""
        client = VisionAPIClient()
        gif_header = b'GIF89a' + b'\x00' * 100

        assert client._detect_image_format(gif_header) == "gif"

    def test_detect_image_format_webp(self):
        """WebPフォーマット検出"""
        client = VisionAPIClient()
        webp_header = b'RIFF\x00\x00\x00\x00WEBP' + b'\x00' * 100

        assert client._detect_image_format(webp_header) == "webp"

    def test_detect_image_format_unknown(self):
        """不明なフォーマットはjpegを返す"""
        client = VisionAPIClient()
        unknown_header = b'\x00\x00\x00\x00' + b'\x00' * 100

        # デフォルトでjpegを返す
        assert client._detect_image_format(unknown_header) == "jpeg"


# =============================================================================
# エンティティ抽出テスト
# =============================================================================


class TestEntityExtraction:
    """エンティティ抽出のテスト"""

    def test_extract_amount(self, mock_pool, organization_id):
        """金額の抽出"""
        processor = ImageProcessor(mock_pool, organization_id)
        text = "合計金額: ¥1,280円"

        entities = processor._extract_entities_from_text(text)

        amount_entities = [e for e in entities if e.entity_type == "amount"]
        assert len(amount_entities) > 0

    def test_extract_date(self, mock_pool, organization_id):
        """日付の抽出"""
        processor = ImageProcessor(mock_pool, organization_id)
        text = "発行日: 2026年1月27日"

        entities = processor._extract_entities_from_text(text)

        date_entities = [e for e in entities if e.entity_type == "date"]
        assert len(date_entities) > 0

    def test_extract_email(self, mock_pool, organization_id):
        """メールアドレスの抽出"""
        processor = ImageProcessor(mock_pool, organization_id)
        text = "連絡先: test@example.com"

        entities = processor._extract_entities_from_text(text)

        email_entities = [e for e in entities if e.entity_type == "email"]
        assert len(email_entities) == 1
        assert email_entities[0].value == "test@example.com"

    def test_extract_url(self, mock_pool, organization_id):
        """URLの抽出"""
        processor = ImageProcessor(mock_pool, organization_id)
        text = "詳細はこちら: https://example.com/page"

        entities = processor._extract_entities_from_text(text)

        url_entities = [e for e in entities if e.entity_type == "url"]
        assert len(url_entities) == 1
        assert "example.com" in url_entities[0].value

    def test_extract_phone(self, mock_pool, organization_id):
        """電話番号の抽出"""
        processor = ImageProcessor(mock_pool, organization_id)
        text = "TEL: 03-1234-5678"

        entities = processor._extract_entities_from_text(text)

        phone_entities = [e for e in entities if e.entity_type == "phone"]
        assert len(phone_entities) > 0


# =============================================================================
# 統合テスト
# =============================================================================


class TestIntegration:
    """統合テスト"""

    def test_factory_functions(self, mock_pool, organization_id):
        """ファクトリー関数の動作確認"""
        from lib.capabilities.multimodal import (
            create_image_processor,
            create_pdf_processor,
            create_url_processor,
        )

        image_processor = create_image_processor(mock_pool, organization_id)
        pdf_processor = create_pdf_processor(mock_pool, organization_id)
        url_processor = create_url_processor(mock_pool, organization_id)

        assert isinstance(image_processor, ImageProcessor)
        assert isinstance(pdf_processor, PDFProcessor)
        assert isinstance(url_processor, URLProcessor)

    def test_package_exports(self):
        """パッケージエクスポートの確認"""
        from lib.capabilities.multimodal import __version__, __all__

        assert __version__ == "1.0.0"
        assert "ImageProcessor" in __all__
        assert "PDFProcessor" in __all__
        assert "URLProcessor" in __all__
        assert "MultimodalInput" in __all__
        assert "MultimodalOutput" in __all__
        # 新しいエクスポートの確認
        assert "MultimodalCoordinator" in __all__
        assert "MultimodalBrainContext" in __all__


# =============================================================================
# コーディネーターテスト
# =============================================================================


class TestMultimodalCoordinator:
    """MultimodalCoordinatorのテスト"""

    def test_init(self, mock_pool, organization_id):
        """初期化の確認"""
        from lib.capabilities.multimodal import MultimodalCoordinator

        coordinator = MultimodalCoordinator(mock_pool, organization_id)

        assert coordinator.pool == mock_pool
        assert coordinator.org_id == organization_id
        assert coordinator.image_processor is not None
        assert coordinator.pdf_processor is not None
        assert coordinator.url_processor is not None

    def test_detect_attachment_type_image_by_extension(self, mock_pool, organization_id):
        """拡張子による画像タイプ判定"""
        from lib.capabilities.multimodal import MultimodalCoordinator, AttachmentType

        coordinator = MultimodalCoordinator(mock_pool, organization_id)

        assert coordinator.detect_attachment_type(filename="photo.jpg") == AttachmentType.IMAGE
        assert coordinator.detect_attachment_type(filename="image.png") == AttachmentType.IMAGE
        assert coordinator.detect_attachment_type(filename="image.gif") == AttachmentType.IMAGE
        assert coordinator.detect_attachment_type(filename="image.webp") == AttachmentType.IMAGE

    def test_detect_attachment_type_pdf_by_extension(self, mock_pool, organization_id):
        """拡張子によるPDFタイプ判定"""
        from lib.capabilities.multimodal import MultimodalCoordinator, AttachmentType

        coordinator = MultimodalCoordinator(mock_pool, organization_id)

        assert coordinator.detect_attachment_type(filename="document.pdf") == AttachmentType.PDF

    def test_detect_attachment_type_by_mime(self, mock_pool, organization_id):
        """MIMEタイプによるタイプ判定"""
        from lib.capabilities.multimodal import MultimodalCoordinator, AttachmentType

        coordinator = MultimodalCoordinator(mock_pool, organization_id)

        assert coordinator.detect_attachment_type(mime_type="image/jpeg") == AttachmentType.IMAGE
        assert coordinator.detect_attachment_type(mime_type="application/pdf") == AttachmentType.PDF
        assert coordinator.detect_attachment_type(mime_type="audio/mpeg") == AttachmentType.AUDIO
        assert coordinator.detect_attachment_type(mime_type="video/mp4") == AttachmentType.VIDEO

    def test_detect_attachment_type_by_magic_bytes_png(self, mock_pool, organization_id):
        """マジックバイトによるPNG判定"""
        from lib.capabilities.multimodal import MultimodalCoordinator, AttachmentType

        coordinator = MultimodalCoordinator(mock_pool, organization_id)
        png_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100

        assert coordinator.detect_attachment_type(data=png_data) == AttachmentType.IMAGE

    def test_detect_attachment_type_by_magic_bytes_pdf(self, mock_pool, organization_id):
        """マジックバイトによるPDF判定"""
        from lib.capabilities.multimodal import MultimodalCoordinator, AttachmentType

        coordinator = MultimodalCoordinator(mock_pool, organization_id)
        pdf_data = b'%PDF-1.4' + b'\x00' * 100

        assert coordinator.detect_attachment_type(data=pdf_data) == AttachmentType.PDF

    def test_detect_url_in_text(self, mock_pool, organization_id):
        """テキストからのURL検出"""
        from lib.capabilities.multimodal import MultimodalCoordinator

        coordinator = MultimodalCoordinator(mock_pool, organization_id)

        text = "こちらを確認してください: https://example.com/page と http://test.com"
        urls = coordinator.detect_url_in_text(text)

        assert len(urls) == 2
        assert "https://example.com/page" in urls
        assert "http://test.com" in urls

    def test_detect_url_in_text_no_urls(self, mock_pool, organization_id):
        """URL無しのテキスト"""
        from lib.capabilities.multimodal import MultimodalCoordinator

        coordinator = MultimodalCoordinator(mock_pool, organization_id)

        text = "これは普通のテキストです"
        urls = coordinator.detect_url_in_text(text)

        assert len(urls) == 0

    def test_get_supported_formats(self, mock_pool, organization_id):
        """サポートフォーマット取得"""
        from lib.capabilities.multimodal import MultimodalCoordinator

        coordinator = MultimodalCoordinator(mock_pool, organization_id)
        formats = coordinator.get_supported_formats()

        assert "image" in formats
        assert "pdf" in formats
        assert "url" in formats
        assert "jpg" in formats["image"]
        assert "pdf" in formats["pdf"]

    def test_get_size_limits(self, mock_pool, organization_id):
        """サイズ制限取得"""
        from lib.capabilities.multimodal import MultimodalCoordinator

        coordinator = MultimodalCoordinator(mock_pool, organization_id)
        limits = coordinator.get_size_limits()

        assert "image" in limits
        assert "pdf" in limits
        assert limits["image"] > 0
        assert limits["pdf"] > 0


# =============================================================================
# Processed Attachmentテスト
# =============================================================================


class TestProcessedAttachment:
    """ProcessedAttachmentのテスト"""

    def test_to_context_text_success(self, mock_pool, organization_id):
        """成功時のコンテキストテキスト生成"""
        from lib.capabilities.multimodal import (
            ProcessedAttachment,
            AttachmentInfo,
            AttachmentType,
            MultimodalOutput,
            InputType,
            ProcessingMetadata,
        )

        attachment_info = AttachmentInfo(
            filename="receipt.jpg",
            attachment_type=AttachmentType.IMAGE,
        )

        output = MultimodalOutput(
            success=True,
            input_type=InputType.IMAGE,
            summary="領収書の画像（スターバックス）",
            extracted_text="スターバックス\n¥1,280",
            entities=[],
            metadata=ProcessingMetadata(
                processing_id="test",
                organization_id=organization_id,
            ),
        )

        processed = ProcessedAttachment(
            attachment_info=attachment_info,
            success=True,
            output=output,
        )

        context_text = processed.to_context_text()

        assert "画像" in context_text
        assert "receipt.jpg" in context_text
        assert "スターバックス" in context_text

    def test_to_context_text_failure(self, mock_pool, organization_id):
        """失敗時のコンテキストテキスト生成"""
        from lib.capabilities.multimodal import (
            ProcessedAttachment,
            AttachmentInfo,
            AttachmentType,
        )

        attachment_info = AttachmentInfo(
            filename="broken.jpg",
            attachment_type=AttachmentType.IMAGE,
        )

        processed = ProcessedAttachment(
            attachment_info=attachment_info,
            success=False,
            error_message="画像の読み込みに失敗しました",
        )

        context_text = processed.to_context_text()

        assert "失敗" in context_text
        assert "broken.jpg" in context_text


# =============================================================================
# EnrichedMessageテスト
# =============================================================================


class TestEnrichedMessage:
    """EnrichedMessageのテスト"""

    def test_get_full_context(self, mock_pool, organization_id):
        """フルコンテキストの生成"""
        from lib.capabilities.multimodal import (
            EnrichedMessage,
            ProcessedAttachment,
            AttachmentInfo,
            AttachmentType,
            MultimodalOutput,
            InputType,
            ProcessingMetadata,
        )

        attachment_info = AttachmentInfo(
            filename="doc.pdf",
            attachment_type=AttachmentType.PDF,
        )

        output = MultimodalOutput(
            success=True,
            input_type=InputType.PDF,
            summary="契約書のPDF",
            extracted_text="契約内容...",
            entities=[],
            metadata=ProcessingMetadata(
                processing_id="test",
                organization_id=organization_id,
            ),
        )

        processed = ProcessedAttachment(
            attachment_info=attachment_info,
            success=True,
            output=output,
        )

        enriched = EnrichedMessage(
            original_text="この書類を確認して",
            processed_attachments=[processed],
        )

        full_context = enriched.get_full_context()

        assert "この書類を確認して" in full_context
        assert "契約書のPDF" in full_context
        assert "添付ファイル情報" in full_context

    def test_stats_calculation(self, mock_pool, organization_id):
        """統計情報の計算"""
        from lib.capabilities.multimodal import (
            EnrichedMessage,
            ProcessedAttachment,
            AttachmentInfo,
            AttachmentType,
        )

        processed1 = ProcessedAttachment(
            attachment_info=AttachmentInfo(filename="a.jpg", attachment_type=AttachmentType.IMAGE),
            success=True,
            processing_time_ms=100,
        )

        processed2 = ProcessedAttachment(
            attachment_info=AttachmentInfo(filename="b.pdf", attachment_type=AttachmentType.PDF),
            success=False,
            processing_time_ms=50,
        )

        enriched = EnrichedMessage(
            original_text="テスト",
            processed_attachments=[processed1, processed2],
        )

        assert enriched.has_multimodal_content is True
        assert enriched.successful_count == 1
        assert enriched.failed_count == 1
        assert enriched.total_processing_time_ms == 150


# =============================================================================
# 脳統合テスト
# =============================================================================


class TestMultimodalBrainContext:
    """MultimodalBrainContextのテスト"""

    def test_init_empty(self):
        """空のコンテキスト"""
        from lib.capabilities.multimodal import MultimodalBrainContext

        context = MultimodalBrainContext()

        assert context.has_multimodal_content is False
        assert context.attachment_count == 0
        assert context.primary_type is None

    def test_has_multimodal_content(self):
        """マルチモーダルコンテンツの有無"""
        from lib.capabilities.multimodal import MultimodalBrainContext

        context = MultimodalBrainContext(
            attachment_count=2,
            successful_count=2,
            has_image=True,
        )

        assert context.has_multimodal_content is True
        assert context.all_successful is True
        assert context.primary_type == "image"

    def test_primary_type_priority(self):
        """プライマリタイプの優先順位"""
        from lib.capabilities.multimodal import MultimodalBrainContext

        # 画像が最優先
        context1 = MultimodalBrainContext(has_image=True, has_pdf=True, attachment_count=2)
        assert context1.primary_type == "image"

        # PDFが次
        context2 = MultimodalBrainContext(has_pdf=True, has_url=True, attachment_count=2)
        assert context2.primary_type == "pdf"

        # URLが次
        context3 = MultimodalBrainContext(has_url=True, attachment_count=1)
        assert context3.primary_type == "url"

    def test_to_prompt_context(self):
        """プロンプトコンテキスト生成"""
        from lib.capabilities.multimodal import MultimodalBrainContext

        context = MultimodalBrainContext(
            has_image=True,
            attachment_count=1,
            successful_count=1,
            summaries=["領収書の画像です"],
        )

        prompt_context = context.to_prompt_context()

        assert "添付ファイル分析結果" in prompt_context
        assert "1件成功" in prompt_context
        assert "画像" in prompt_context
        assert "領収書" in prompt_context


# =============================================================================
# ヘルパー関数テスト
# =============================================================================


class TestHelperFunctions:
    """ヘルパー関数のテスト"""

    def test_should_process_as_multimodal_with_attachments(self):
        """添付ファイルありの場合はTrue"""
        from lib.capabilities.multimodal import should_process_as_multimodal

        result = should_process_as_multimodal(
            message_text="確認して",
            attachments=[{"data": b"test", "filename": "test.jpg"}],
        )

        assert result is True

    def test_should_process_as_multimodal_with_url(self):
        """URL含むテキストの場合はTrue"""
        from lib.capabilities.multimodal import should_process_as_multimodal

        result = should_process_as_multimodal(
            message_text="https://example.com を確認して",
            attachments=[],
        )

        assert result is True

    def test_should_process_as_multimodal_text_only(self):
        """テキストのみの場合はFalse"""
        from lib.capabilities.multimodal import should_process_as_multimodal

        result = should_process_as_multimodal(
            message_text="普通のテキストです",
            attachments=[],
        )

        assert result is False

    def test_extract_instruction_from_message(self):
        """指示の抽出"""
        from lib.capabilities.multimodal import extract_instruction_from_message

        # URLを除去して指示を抽出
        instruction = extract_instruction_from_message(
            "https://example.com この記事を要約して"
        )

        assert "要約" in instruction
        assert "https" not in instruction

    def test_extract_instruction_from_message_no_text(self):
        """テキストがない場合"""
        from lib.capabilities.multimodal import extract_instruction_from_message

        instruction = extract_instruction_from_message(
            "https://example.com",
            default_instruction="内容を確認してください",
        )

        assert instruction == "内容を確認してください"

    def test_format_multimodal_response_no_failures(self):
        """失敗なしの応答フォーマット"""
        from lib.capabilities.multimodal import (
            format_multimodal_response,
            MultimodalBrainContext,
        )

        context = MultimodalBrainContext(
            attachment_count=1,
            successful_count=1,
            failed_count=0,
        )

        formatted = format_multimodal_response(
            brain_response="処理完了しました",
            multimodal_context=context,
        )

        assert formatted == "処理完了しました"
        assert "失敗" not in formatted

    def test_format_multimodal_response_with_failures(self):
        """失敗ありの応答フォーマット"""
        from lib.capabilities.multimodal import (
            format_multimodal_response,
            MultimodalBrainContext,
        )

        context = MultimodalBrainContext(
            attachment_count=2,
            successful_count=1,
            failed_count=1,
        )

        formatted = format_multimodal_response(
            brain_response="処理完了しました",
            multimodal_context=context,
        )

        assert "処理完了しました" in formatted
        assert "1件" in formatted
        assert "失敗" in formatted
