# tests/test_pdf_processor.py
"""
PDF処理プロセッサーのテスト

lib/capabilities/multimodal/pdf_processor.py のカバレッジ80%以上を目指す。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import io

from lib.capabilities.multimodal.pdf_processor import (
    PDFProcessor,
    create_pdf_processor,
)
from lib.capabilities.multimodal.constants import (
    InputType,
    PDFType,
    ContentConfidenceLevel,
    MAX_PDF_SIZE_BYTES,
    MAX_PDF_PAGES,
)
from lib.capabilities.multimodal.models import (
    MultimodalInput,
    PDFMetadata,
    PDFPageContent,
)
from lib.capabilities.multimodal.exceptions import (
    ValidationError,
    FileTooLargeError,
    TooManyPagesError,
    PDFProcessingError,
    PDFDecodeError,
    PDFEncryptedError,
    PDFOCRError,
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
    """テスト用PDFProcessor"""
    return PDFProcessor(
        pool=mock_pool,
        organization_id="test-org-123",
        api_key="test-api-key",
    )


@pytest.fixture
def sample_pdf_data():
    """サンプルPDFデータ（最小限の有効なPDF）"""
    # 最小限のPDF構造
    return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT
/F1 12 Tf
100 700 Td
(Hello World) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000206 00000 n
trailer
<< /Size 5 /Root 1 0 R >>
startxref
300
%%EOF"""


@pytest.fixture
def sample_input(sample_pdf_data):
    """サンプル入力"""
    return MultimodalInput(
        input_type=InputType.PDF,
        organization_id="test-org-123",
        pdf_data=sample_pdf_data,
    )


# =============================================================================
# TestPDFProcessorInit - 初期化テスト
# =============================================================================


class TestPDFProcessorInit:
    """PDFProcessor初期化のテスト"""

    def test_init_with_params(self, mock_pool):
        """パラメータ指定で初期化"""
        processor = PDFProcessor(
            pool=mock_pool,
            organization_id="org-123",
            api_key="api-key",
        )
        assert processor._organization_id == "org-123"
        assert processor._api_key == "api-key"

    def test_init_without_api_key(self, mock_pool):
        """API Keyなしで初期化"""
        processor = PDFProcessor(pool=mock_pool, organization_id="org-123")
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
            pdf_data=b"test",
        )
        with pytest.raises(ValidationError) as exc_info:
            processor.validate(input_data)
        assert "input_type" in str(exc_info.value.field)

    def test_validate_missing_data(self, processor):
        """データなしでエラー"""
        input_data = MultimodalInput(
            input_type=InputType.PDF,
            organization_id="test-org-123",
            pdf_data=None,
            file_path=None,
        )
        with pytest.raises(ValidationError):
            processor.validate(input_data)

    def test_validate_file_too_large(self, processor):
        """大きすぎるファイルでエラー"""
        large_data = b"x" * (MAX_PDF_SIZE_BYTES + 1)
        input_data = MultimodalInput(
            input_type=InputType.PDF,
            organization_id="test-org-123",
            pdf_data=large_data,
        )
        with pytest.raises(FileTooLargeError):
            processor.validate(input_data)


# =============================================================================
# TestGetPdfData - PDFデータ取得テスト
# =============================================================================


class TestGetPdfData:
    """_get_pdf_data()メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_pdf_data_from_bytes(self, processor, sample_pdf_data):
        """バイトデータから取得"""
        input_data = MultimodalInput(
            input_type=InputType.PDF,
            organization_id="test-org-123",
            pdf_data=sample_pdf_data,
        )
        data = await processor._get_pdf_data(input_data)
        assert data == sample_pdf_data

    @pytest.mark.asyncio
    async def test_get_pdf_data_from_file(self, processor, sample_pdf_data, tmp_path):
        """ファイルから取得"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(sample_pdf_data)

        input_data = MultimodalInput(
            input_type=InputType.PDF,
            organization_id="test-org-123",
            file_path=str(pdf_file),
        )
        data = await processor._get_pdf_data(input_data)
        assert data == sample_pdf_data

    @pytest.mark.asyncio
    async def test_get_pdf_data_file_too_large(self, processor, tmp_path):
        """ファイルが大きすぎる場合"""
        pdf_file = tmp_path / "large.pdf"
        pdf_file.write_bytes(b"x" * (MAX_PDF_SIZE_BYTES + 1))

        input_data = MultimodalInput(
            input_type=InputType.PDF,
            organization_id="test-org-123",
            file_path=str(pdf_file),
        )
        with pytest.raises(FileTooLargeError):
            await processor._get_pdf_data(input_data)

    @pytest.mark.asyncio
    async def test_get_pdf_data_file_not_found(self, processor):
        """ファイルが見つからない場合"""
        input_data = MultimodalInput(
            input_type=InputType.PDF,
            organization_id="test-org-123",
            file_path="/nonexistent/file.pdf",
        )
        with pytest.raises(PDFDecodeError):
            await processor._get_pdf_data(input_data)

    @pytest.mark.asyncio
    async def test_get_pdf_data_no_data(self, processor):
        """データなしの場合"""
        input_data = MultimodalInput(
            input_type=InputType.PDF,
            organization_id="test-org-123",
        )
        with pytest.raises(ValidationError):
            await processor._get_pdf_data(input_data)


# =============================================================================
# TestExtractPdfMetadata - メタデータ抽出テスト
# =============================================================================


class TestExtractPdfMetadata:
    """_extract_pdf_metadata()メソッドのテスト"""

    def test_extract_metadata_basic(self, processor, sample_pdf_data):
        """基本的なメタデータ抽出"""
        # pypdfがインストールされていれば正常にメタデータ抽出、なければフォールバック
        metadata = processor._extract_pdf_metadata(sample_pdf_data)
        assert metadata.page_count >= 1
        assert metadata.file_size_bytes == len(sample_pdf_data)

    def test_count_pages_basic(self, processor):
        """基本的なページ数カウント"""
        pdf_data = b"/Count 5 /Type /Pages"
        count = processor._count_pages_basic(pdf_data)
        assert count == 5

    def test_count_pages_basic_multiple_counts(self, processor):
        """複数のCount値がある場合"""
        pdf_data = b"/Count 3 /Pages /Count 10"
        count = processor._count_pages_basic(pdf_data)
        assert count == 10  # 最大値を返す

    def test_count_pages_basic_no_count(self, processor):
        """Countがない場合"""
        pdf_data = b"no count here"
        count = processor._count_pages_basic(pdf_data)
        assert count == 1  # デフォルト


# =============================================================================
# TestDetectPdfType - PDFタイプ検出テスト
# =============================================================================


class TestDetectPdfType:
    """_detect_pdf_type()メソッドのテスト"""

    def test_detect_pdf_type_fallback(self, processor, sample_pdf_data):
        """PDFタイプ検出（フォールバック）"""
        pdf_type = processor._detect_pdf_type(sample_pdf_data)
        # デフォルトまたは検出されたタイプ
        assert pdf_type in [PDFType.TEXT_BASED, PDFType.SCANNED, PDFType.MIXED]


# =============================================================================
# TestExtractHeadings - 見出し抽出テスト
# =============================================================================


class TestExtractHeadingsFromText:
    """_extract_headings_from_text()メソッドのテスト"""

    def test_extract_numbered_headings(self, processor):
        """番号付き見出しを抽出"""
        text = """
1. はじめに
これは本文です。
2. 概要
これも本文です。
"""
        headings = processor._extract_headings_from_text(text)
        assert len(headings) >= 2
        assert any("はじめに" in h for h in headings)

    def test_extract_chapter_headings(self, processor):
        """章見出しを抽出"""
        text = """
第1章 導入
これは導入部分です。
第2章 本論
これは本論です。
"""
        headings = processor._extract_headings_from_text(text)
        assert len(headings) >= 2

    def test_extract_symbol_headings(self, processor):
        """記号付き見出しを抽出"""
        text = """
■ 重要事項
これは重要です。
● ポイント
これがポイントです。
"""
        headings = processor._extract_headings_from_text(text)
        assert len(headings) >= 2

    def test_extract_no_headings(self, processor):
        """見出しがない場合"""
        text = "これは普通のテキストです。見出しはありません。"
        headings = processor._extract_headings_from_text(text)
        assert len(headings) == 0


# =============================================================================
# TestExtractAllHeadings - 全見出し収集テスト
# =============================================================================


class TestExtractAllHeadings:
    """_extract_all_headings()メソッドのテスト"""

    def test_extract_all_headings(self, processor):
        """複数ページから見出しを収集"""
        pages = [
            PDFPageContent(page_number=1, text="", headings=["見出し1", "見出し2"]),
            PDFPageContent(page_number=2, text="", headings=["見出し3"]),
        ]
        all_headings = processor._extract_all_headings(pages)
        assert len(all_headings) == 3

    def test_extract_all_headings_empty(self, processor):
        """見出しがない場合"""
        pages = [
            PDFPageContent(page_number=1, text=""),
            PDFPageContent(page_number=2, text=""),
        ]
        all_headings = processor._extract_all_headings(pages)
        assert len(all_headings) == 0


# =============================================================================
# TestExtractAllTables - 全テーブル収集テスト
# =============================================================================


class TestExtractAllTables:
    """_extract_all_tables()メソッドのテスト"""

    def test_extract_all_tables(self, processor):
        """複数ページからテーブルを収集"""
        pages = [
            PDFPageContent(page_number=1, text="", tables=[{"id": 1}]),
            PDFPageContent(page_number=2, text="", tables=[{"id": 2}, {"id": 3}]),
        ]
        all_tables = processor._extract_all_tables(pages)
        assert len(all_tables) == 3

    def test_extract_all_tables_empty(self, processor):
        """テーブルがない場合"""
        pages = [
            PDFPageContent(page_number=1, text=""),
            PDFPageContent(page_number=2, text=""),
        ]
        all_tables = processor._extract_all_tables(pages)
        assert len(all_tables) == 0


# =============================================================================
# TestGenerateTableOfContents - 目次生成テスト
# =============================================================================


class TestGenerateTableOfContents:
    """_generate_table_of_contents()メソッドのテスト"""

    def test_generate_toc(self, processor):
        """目次を生成"""
        headings = ["第1章 はじめに", "第2章 概要", "第3章 まとめ"]
        toc = processor._generate_table_of_contents(headings)

        assert len(toc) == 3
        assert toc[0]["index"] == 1
        assert toc[0]["title"] == "第1章 はじめに"

    def test_generate_toc_limit(self, processor):
        """目次の件数制限"""
        headings = [f"見出し{i}" for i in range(50)]
        toc = processor._generate_table_of_contents(headings)

        assert len(toc) <= 30  # 最大30件

    def test_generate_toc_empty(self, processor):
        """見出しがない場合"""
        toc = processor._generate_table_of_contents([])
        assert len(toc) == 0


# =============================================================================
# TestCalculateOverallConfidence - 確信度計算テスト
# =============================================================================


class TestCalculateOverallConfidence:
    """_calculate_overall_confidence()メソッドのテスト"""

    def test_confidence_text_based(self, processor):
        """テキストベースPDFの確信度"""
        pages = [PDFPageContent(page_number=1, text="テスト")]
        confidence = processor._calculate_overall_confidence(pages, PDFType.TEXT_BASED)
        assert confidence == 0.9

    def test_confidence_ocr_pages(self, processor):
        """OCRページの確信度"""
        pages = [
            PDFPageContent(page_number=1, text="", ocr_used=True, ocr_confidence=0.8),
            PDFPageContent(page_number=2, text="", ocr_used=True, ocr_confidence=0.6),
        ]
        confidence = processor._calculate_overall_confidence(pages, PDFType.SCANNED)
        assert confidence == 0.7  # (0.8 + 0.6) / 2

    def test_confidence_empty_pages(self, processor):
        """ページがない場合"""
        confidence = processor._calculate_overall_confidence([], PDFType.TEXT_BASED)
        assert confidence == 0.5

    def test_confidence_mixed_no_ocr(self, processor):
        """OCRなしの混合PDFの場合"""
        pages = [
            PDFPageContent(page_number=1, text="テスト", ocr_used=False),
        ]
        confidence = processor._calculate_overall_confidence(pages, PDFType.MIXED)
        assert confidence == 0.7


# =============================================================================
# TestParseOcrResult - OCR結果パーステスト
# =============================================================================


class TestParseOcrResult:
    """_parse_ocr_result()メソッドのテスト"""

    def test_parse_json_in_code_block(self, processor):
        """コードブロック内のJSON"""
        content = """
        OCR結果:
        ```json
        {"text": "抽出されたテキスト", "confidence": 0.9, "headings": ["見出し1"]}
        ```
        """
        result = processor._parse_ocr_result(content)
        assert result["text"] == "抽出されたテキスト"
        assert result["confidence"] == 0.9

    def test_parse_raw_json(self, processor):
        """生のJSON"""
        content = '{"text": "テスト", "confidence": 0.8}'
        result = processor._parse_ocr_result(content)
        assert result["text"] == "テスト"

    def test_parse_invalid_json(self, processor):
        """無効なJSONでフォールバック"""
        content = "これは普通のテキストです"
        result = processor._parse_ocr_result(content)
        assert result["text"] == content
        assert result["confidence"] == 0.5


# =============================================================================
# TestPageHasImages - 画像チェックテスト
# =============================================================================


class TestPageHasImages:
    """_page_has_images()メソッドのテスト"""

    def test_page_has_images_true(self, processor):
        """画像があるページ"""
        page = MagicMock()
        page.get.return_value = {"/XObject": {"/Im0": MagicMock()}}
        assert processor._page_has_images(page) is True

    def test_page_has_images_false(self, processor):
        """画像がないページ"""
        page = MagicMock()
        page.get.return_value = {"/XObject": {}}
        assert processor._page_has_images(page) is False

    def test_page_has_images_no_resources(self, processor):
        """リソースがないページ"""
        page = MagicMock()
        page.get.return_value = {}
        assert processor._page_has_images(page) is False

    def test_page_has_images_error(self, processor):
        """エラー時"""
        page = MagicMock()
        page.get.side_effect = Exception("Error")
        assert processor._page_has_images(page) is False


# =============================================================================
# TestCountPageImages - 画像数カウントテスト
# =============================================================================


class TestCountPageImages:
    """_count_page_images()メソッドのテスト"""

    def test_count_page_images(self, processor):
        """画像数をカウント"""
        page = MagicMock()
        page.get.return_value = {"/XObject": {"/Im0": None, "/Im1": None, "/Im2": None}}
        assert processor._count_page_images(page) == 3

    def test_count_page_images_zero(self, processor):
        """画像なし"""
        page = MagicMock()
        page.get.return_value = {"/XObject": {}}
        assert processor._count_page_images(page) == 0

    def test_count_page_images_error(self, processor):
        """エラー時"""
        page = MagicMock()
        page.get.side_effect = Exception("Error")
        assert processor._count_page_images(page) == 0


# =============================================================================
# TestSaveToKnowledge - ナレッジ保存テスト
# =============================================================================


class TestSaveToKnowledge:
    """_save_to_knowledge()メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_save_to_knowledge_not_implemented(self, processor):
        """未実装の状態をテスト"""
        saved, doc_id = await processor._save_to_knowledge(
            pdf_data=b"test",
            pdf_metadata=PDFMetadata(page_count=1),
            full_text="テスト",
            summary="要約",
        )
        assert saved is False
        assert doc_id is None


# =============================================================================
# TestCreatePdfProcessor - ファクトリ関数テスト
# =============================================================================


class TestCreatePdfProcessor:
    """create_pdf_processor()のテスト"""

    def test_create_with_params(self, mock_pool):
        """パラメータ指定で作成"""
        processor = create_pdf_processor(
            pool=mock_pool,
            organization_id="org-123",
            api_key="api-key",
        )
        assert isinstance(processor, PDFProcessor)
        assert processor._organization_id == "org-123"

    def test_create_without_api_key(self, mock_pool):
        """API Keyなしで作成"""
        processor = create_pdf_processor(
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
    async def test_process_validation_error(self, processor):
        """検証エラー"""
        input_data = MultimodalInput(
            input_type=InputType.IMAGE,  # 間違ったタイプ
            organization_id="test-org-123",
            pdf_data=b"test",
        )
        result = await processor.process(input_data)
        assert result.success is False
        assert "input_type" in result.error_message.lower() or "VALIDATION" in result.error_code

    @pytest.mark.asyncio
    async def test_process_too_many_pages(self, processor):
        """ページ数が多すぎる場合"""
        # メタデータを返すようにモック
        mock_metadata = PDFMetadata(page_count=MAX_PDF_PAGES + 10)
        with patch.object(processor, "_extract_pdf_metadata", return_value=mock_metadata):
            input_data = MultimodalInput(
                input_type=InputType.PDF,
                organization_id="test-org-123",
                pdf_data=b"test pdf data",
            )
            result = await processor.process(input_data)

        assert result.success is False
        assert "PAGES" in result.error_code or "ページ" in result.error_message


# =============================================================================
# TestExtractTextPypdf - PyPDFテキスト抽出テスト
# =============================================================================


class TestExtractTextPypdf:
    """_extract_text_pypdf()メソッドのテスト"""

    def test_extract_text_pypdf_invalid_pdf(self, processor, sample_pdf_data):
        """無効なPDFデータでエラーが発生することを確認"""
        # 無効なPDFデータを渡すとPDFProcessingErrorが発生する
        with pytest.raises(PDFProcessingError):
            processor._extract_text_pypdf(b"invalid pdf data")


# =============================================================================
# TestExtractText - テキスト抽出テスト
# =============================================================================


class TestExtractText:
    """_extract_text()メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_extract_text_text_based(self, processor):
        """テキストベースPDFのテキスト抽出"""
        mock_pages = [
            PDFPageContent(page_number=1, text="ページ1のテキスト"),
            PDFPageContent(page_number=2, text="ページ2のテキスト"),
        ]
        with patch.object(processor, "_extract_text_pypdf", return_value=mock_pages):
            pages = await processor._extract_text(b"pdf", PDFType.TEXT_BASED, 2)

        assert len(pages) == 2

    @pytest.mark.asyncio
    async def test_extract_text_scanned(self, processor):
        """スキャンPDFのOCR抽出"""
        mock_page = PDFPageContent(page_number=1, text="OCRテキスト", ocr_used=True)
        with patch.object(processor, "_ocr_page", new=AsyncMock(return_value=mock_page)):
            pages = await processor._extract_text(b"pdf", PDFType.SCANNED, 1)

        assert len(pages) == 1
        assert pages[0].ocr_used is True

    @pytest.mark.asyncio
    async def test_extract_text_scanned_ocr_failure(self, processor):
        """スキャンPDFのOCR失敗"""
        with patch.object(processor, "_ocr_page", new=AsyncMock(side_effect=Exception("OCR failed"))):
            pages = await processor._extract_text(b"pdf", PDFType.SCANNED, 1)

        assert len(pages) == 1
        assert pages[0].text == ""
        assert pages[0].ocr_confidence == 0.0

    @pytest.mark.asyncio
    async def test_extract_text_mixed(self, processor):
        """混合PDFのテキスト抽出"""
        mock_text_pages = [
            PDFPageContent(page_number=1, text="十分なテキスト" * 10),  # 十分なテキスト
            PDFPageContent(page_number=2, text="短い"),  # OCR必要
        ]
        mock_ocr_page = PDFPageContent(page_number=2, text="OCRテキスト", ocr_used=True)

        with patch.object(processor, "_extract_text_pypdf", return_value=mock_text_pages):
            with patch.object(processor, "_ocr_page", new=AsyncMock(return_value=mock_ocr_page)):
                pages = await processor._extract_text(b"pdf", PDFType.MIXED, 2)

        assert len(pages) == 2


# =============================================================================
# TestExtractPdfMetadataWithPypdf - PyPDFメタデータ抽出テスト
# =============================================================================


class TestExtractPdfMetadataWithPypdf:
    """_extract_pdf_metadata() pypdfでのテスト"""

    def test_extract_metadata_invalid_pdf(self, processor):
        """無効なPDFでメタデータ抽出を試行"""
        # 無効なデータでは例外が発生するか、フォールバック処理される
        try:
            metadata = processor._extract_pdf_metadata(b"invalid pdf")
            # フォールバック処理された場合
            assert metadata.file_size_bytes == len(b"invalid pdf")
        except (PDFDecodeError, PDFEncryptedError):
            pass  # 期待通り


# =============================================================================
# TestDetectPdfTypeWithPypdf - PyPDFタイプ検出テスト
# =============================================================================


class TestDetectPdfTypeWithPypdf:
    """_detect_pdf_type() pypdfでのテスト"""

    def test_detect_with_invalid_pdf(self, processor):
        """無効なPDFでタイプ検出（フォールバック）"""
        # 無効なデータではフォールバック処理される
        pdf_type = processor._detect_pdf_type(b"invalid pdf data")
        # デフォルトにフォールバック
        assert pdf_type == PDFType.TEXT_BASED


# =============================================================================
# TestPdfPageToImage - ページ画像変換テスト
# =============================================================================


class TestPdfPageToImage:
    """_pdf_page_to_image()メソッドのテスト"""

    def test_pdf_page_to_image_success(self, processor):
        """ページを画像に変換"""
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"png image data"

        mock_page = MagicMock()
        mock_page.get_pixmap.return_value = mock_pix

        mock_doc = MagicMock()
        mock_doc.__getitem__.return_value = mock_page

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc
        mock_fitz.Matrix.return_value = MagicMock()

        with patch.dict("sys.modules", {"fitz": mock_fitz}):
            image_data = processor._pdf_page_to_image(b"pdf", 0)

        assert image_data == b"png image data"

    def test_pdf_page_to_image_no_fitz(self, processor):
        """fitzがない場合"""
        # fitzモジュールがない場合をシミュレート
        with patch.dict("sys.modules", {"fitz": None}):
            image_data = processor._pdf_page_to_image(b"pdf", 0)

        # ImportErrorの場合Noneを返す
        assert image_data is None

    def test_pdf_page_to_image_error(self, processor):
        """変換エラー"""
        mock_fitz = MagicMock()
        mock_fitz.open.side_effect = Exception("Error")

        with patch.dict("sys.modules", {"fitz": mock_fitz}):
            image_data = processor._pdf_page_to_image(b"pdf", 0)

        assert image_data is None


# =============================================================================
# TestGenerateSummary - 要約生成テスト
# =============================================================================


class TestGenerateSummary:
    """_generate_summary()メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_generate_summary_empty_text(self, processor):
        """空テキストの場合"""
        summary, key_points = await processor._generate_summary(
            full_text="",
            pdf_metadata=PDFMetadata(page_count=1),
        )
        assert summary == ""
        assert key_points == []

    @pytest.mark.asyncio
    async def test_generate_summary_success(self, processor):
        """正常に要約を生成"""
        mock_result = {
            "content": '{"summary": "これは要約です", "key_points": ["ポイント1", "ポイント2"]}'
        }
        processor._vision_client = MagicMock()
        processor._vision_client.analyze_with_fallback = AsyncMock(return_value=mock_result)

        summary, key_points = await processor._generate_summary(
            full_text="これはテストテキストです。" * 100,
            pdf_metadata=PDFMetadata(page_count=5, title="テストPDF"),
        )

        assert summary == "これは要約です"
        assert len(key_points) == 2

    @pytest.mark.asyncio
    async def test_generate_summary_with_instruction(self, processor):
        """指示付きで要約を生成"""
        mock_result = {
            "content": '{"summary": "指示に基づく要約", "key_points": []}'
        }
        processor._vision_client = MagicMock()
        processor._vision_client.analyze_with_fallback = AsyncMock(return_value=mock_result)

        summary, key_points = await processor._generate_summary(
            full_text="これはテストテキストです。",
            pdf_metadata=PDFMetadata(page_count=1),
            instruction="重要なポイントを抽出して",
        )

        assert "要約" in summary

    @pytest.mark.asyncio
    async def test_generate_summary_fallback(self, processor):
        """LLMエラー時のフォールバック"""
        processor._vision_client = MagicMock()
        processor._vision_client.analyze_with_fallback = AsyncMock(
            side_effect=Exception("API error")
        )

        summary, key_points = await processor._generate_summary(
            full_text="最初の文。2番目の文。3番目の文。4番目の文。",
            pdf_metadata=PDFMetadata(page_count=1),
        )

        # フォールバックで最初の数文が返される
        assert len(summary) > 0
        assert key_points == []
