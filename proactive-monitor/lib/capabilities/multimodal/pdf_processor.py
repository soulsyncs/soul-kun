# lib/capabilities/multimodal/pdf_processor.py
"""
Phase M1: Multimodal入力能力 - PDF処理プロセッサー

このモジュールは、PDFの解析・テキスト抽出機能を提供します。

処理フロー:
1. テキストベースPDF → PyPDF2でテキスト抽出
2. スキャンPDF（画像）→ ページごとに画像化 → Vision APIでOCR
3. 混合PDF → テキスト抽出 + 必要な部分のみOCR

ユースケース:
- 契約書の読み取り → 重要条項の抽出
- マニュアルの読み込み → ナレッジDBへの登録
- レポートの分析 → 要約作成

設計書: docs/20_next_generation_capabilities.md セクション5.4
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import logging
import io
import json
import re

from .constants import (
    InputType,
    ProcessingStatus,
    PDFType,
    ContentConfidenceLevel,
    MAX_PDF_SIZE_BYTES,
    MAX_PDF_PAGES,
    PDF_OCR_DPI,
    PDF_PROCESSING_TIMEOUT_SECONDS,
    MAX_EXTRACTED_TEXT_LENGTH,
    MAX_SUMMARY_LENGTH,
)
from .exceptions import (
    ValidationError,
    FileTooLargeError,
    TooManyPagesError,
    PDFProcessingError,
    PDFDecodeError,
    PDFEncryptedError,
    PDFOCRError,
    VisionAPIError,
    wrap_multimodal_error,
)
from .models import (
    ProcessingMetadata,
    ExtractedEntity,
    PDFPageContent,
    PDFMetadata,
    PDFAnalysisResult,
    MultimodalInput,
    MultimodalOutput,
)
from .base import BaseMultimodalProcessor


logger = logging.getLogger(__name__)


# =============================================================================
# PDFProcessor
# =============================================================================


class PDFProcessor(BaseMultimodalProcessor):
    """
    PDF処理プロセッサー

    PDFを解析し、テキスト抽出・構造解析・要約生成を行う。

    使用例:
        processor = PDFProcessor(pool, org_id)
        result = await processor.process(MultimodalInput(
            input_type=InputType.PDF,
            organization_id=org_id,
            pdf_data=pdf_bytes,
            save_to_knowledge=True,
        ))
        print(result.pdf_result.summary)
    """

    def __init__(
        self,
        pool,
        organization_id: str,
        api_key: Optional[str] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            api_key: OpenRouter API Key
        """
        super().__init__(
            pool=pool,
            organization_id=organization_id,
            api_key=api_key,
            input_type=InputType.PDF,
        )

    # =========================================================================
    # 公開API
    # =========================================================================

    @wrap_multimodal_error
    async def process(self, input_data: MultimodalInput) -> MultimodalOutput:
        """
        PDFを処理

        処理フロー:
        1. 入力検証
        2. PDFメタデータ抽出
        3. PDFタイプ判定
        4. テキスト抽出（タイプに応じて）
        5. 構造解析
        6. 要約生成
        7. エンティティ抽出
        8. ナレッジDB保存（オプション）

        Args:
            input_data: 入力データ

        Returns:
            MultimodalOutput: 処理結果
        """
        # メタデータ初期化
        metadata = self._create_processing_metadata()
        self._log_processing_start("pdf")

        try:
            # Step 1: 入力検証
            self.validate(input_data)

            # PDFデータ取得
            pdf_data = await self._get_pdf_data(input_data)

            # Step 2: PDFメタデータ抽出
            pdf_metadata = self._extract_pdf_metadata(pdf_data)
            logger.debug(
                f"PDF metadata: {pdf_metadata.page_count} pages, "
                f"title={pdf_metadata.title}"
            )

            # Step 3: ページ数検証
            if pdf_metadata.page_count > MAX_PDF_PAGES:
                raise TooManyPagesError(
                    actual_pages=pdf_metadata.page_count,
                    max_pages=MAX_PDF_PAGES,
                )

            # Step 4: PDFタイプ判定
            pdf_type = self._detect_pdf_type(pdf_data)
            logger.debug(f"PDF type: {pdf_type.value}")

            # Step 5: テキスト抽出
            pages = await self._extract_text(pdf_data, pdf_type, pdf_metadata.page_count)

            # 全テキスト結合
            full_text = "\n\n".join([p.text for p in pages if p.text])
            if len(full_text) > MAX_EXTRACTED_TEXT_LENGTH:
                full_text = full_text[:MAX_EXTRACTED_TEXT_LENGTH]

            # Step 6: 構造解析
            all_headings = self._extract_all_headings(pages)
            all_tables = self._extract_all_tables(pages)
            toc = self._generate_table_of_contents(all_headings)

            # Step 7: 要約生成
            summary, key_points = await self._generate_summary(
                full_text,
                pdf_metadata,
                input_data.instruction,
            )

            # Step 8: エンティティ抽出
            entities = self._extract_entities_from_text(full_text)

            # Step 9: 確信度計算
            confidence = self._calculate_overall_confidence(pages, pdf_type)
            confidence_level = self._calculate_confidence_level(confidence)

            # Step 10: メタデータ更新
            metadata.api_calls_count = sum(1 for p in pages if p.ocr_used) + 1  # OCR + 要約

            # Step 11: ナレッジDB保存（オプション）
            saved_to_knowledge = False
            knowledge_document_id = None
            if input_data.save_to_knowledge:
                saved_to_knowledge, knowledge_document_id = await self._save_to_knowledge(
                    pdf_data=pdf_data,
                    pdf_metadata=pdf_metadata,
                    full_text=full_text,
                    summary=summary,
                )

            # Step 12: 結果構築
            pdf_result = PDFAnalysisResult(
                success=True,
                pdf_type=pdf_type,
                pdf_metadata=pdf_metadata,
                full_text=full_text,
                pages=pages,
                table_of_contents=toc,
                all_headings=all_headings,
                all_tables=all_tables,
                entities=entities,
                summary=summary,
                key_points=key_points,
                overall_confidence=confidence,
                confidence_level=confidence_level,
                metadata=self._complete_processing_metadata(metadata, success=True),
                saved_to_knowledge=saved_to_knowledge,
                knowledge_document_id=knowledge_document_id,
            )

            # ログ
            self._log_processing_complete(
                success=True,
                processing_time_ms=pdf_result.metadata.processing_time_ms,
                details={
                    "pdf_type": pdf_type.value,
                    "page_count": pdf_metadata.page_count,
                    "text_length": len(full_text),
                    "entities_count": len(entities),
                },
            )

            # 処理ログ保存
            await self._save_processing_log(
                metadata=pdf_result.metadata,
                input_hash=self._compute_hash(pdf_data),
                output_summary=summary[:200] if summary else None,
            )

            return MultimodalOutput(
                success=True,
                input_type=InputType.PDF,
                pdf_result=pdf_result,
                summary=summary,
                extracted_text=full_text,
                entities=entities,
                metadata=pdf_result.metadata,
            )

        except Exception as e:
            # エラーハンドリング
            error_message = str(e)
            error_code = getattr(e, 'error_code', 'UNKNOWN_ERROR')

            self._log_processing_complete(
                success=False,
                processing_time_ms=int((datetime.now() - metadata.started_at).total_seconds() * 1000),
                details={"error": error_message},
            )

            return MultimodalOutput(
                success=False,
                input_type=InputType.PDF,
                error_message=error_message,
                error_code=error_code,
                metadata=self._complete_processing_metadata(
                    metadata,
                    success=False,
                    error_message=error_message,
                    error_code=error_code,
                ),
            )

    def validate(self, input_data: MultimodalInput) -> None:
        """
        入力を検証

        Args:
            input_data: 入力データ

        Raises:
            ValidationError: 検証に失敗した場合
        """
        # 組織ID検証
        self._validate_organization_id()

        # 入力タイプ検証
        if input_data.input_type != InputType.PDF:
            raise ValidationError(
                message=f"Invalid input type: expected PDF, got {input_data.input_type.value}",
                field="input_type",
                input_type=InputType.PDF,
            )

        # データ存在検証
        if input_data.pdf_data is None and input_data.file_path is None:
            raise ValidationError(
                message="Either pdf_data or file_path must be provided",
                field="pdf_data",
                input_type=InputType.PDF,
            )

        # ファイルサイズ検証
        if input_data.pdf_data:
            if len(input_data.pdf_data) > MAX_PDF_SIZE_BYTES:
                raise FileTooLargeError(
                    actual_size_bytes=len(input_data.pdf_data),
                    max_size_bytes=MAX_PDF_SIZE_BYTES,
                    input_type=InputType.PDF,
                )

    # =========================================================================
    # 内部メソッド
    # =========================================================================

    async def _get_pdf_data(self, input_data: MultimodalInput) -> bytes:
        """PDFデータを取得"""
        if input_data.pdf_data:
            return input_data.pdf_data

        if input_data.file_path:
            try:
                with open(input_data.file_path, 'rb') as f:
                    data = f.read()

                if len(data) > MAX_PDF_SIZE_BYTES:
                    raise FileTooLargeError(
                        actual_size_bytes=len(data),
                        max_size_bytes=MAX_PDF_SIZE_BYTES,
                        input_type=InputType.PDF,
                    )

                return data
            except IOError as e:
                raise PDFDecodeError(f"Failed to read PDF file: {e}")

        raise ValidationError(
            message="No PDF data provided",
            field="pdf_data",
            input_type=InputType.PDF,
        )

    def _extract_pdf_metadata(self, pdf_data: bytes) -> PDFMetadata:
        """PDFメタデータを抽出"""
        try:
            import pypdf

            with io.BytesIO(pdf_data) as buffer:
                reader = pypdf.PdfReader(buffer)

                # 暗号化チェック
                if reader.is_encrypted:
                    raise PDFEncryptedError()

                # メタデータ取得
                info = reader.metadata or {}

                return PDFMetadata(
                    title=info.get('/Title'),
                    author=info.get('/Author'),
                    subject=info.get('/Subject'),
                    creator=info.get('/Creator'),
                    producer=info.get('/Producer'),
                    page_count=len(reader.pages),
                    file_size_bytes=len(pdf_data),
                    is_encrypted=False,
                )

        except PDFEncryptedError:
            raise
        except ImportError:
            # pypdfがない場合は最小限の情報
            logger.warning("pypdf not available, using basic PDF parsing")
            return PDFMetadata(
                page_count=self._count_pages_basic(pdf_data),
                file_size_bytes=len(pdf_data),
            )
        except Exception as e:
            raise PDFDecodeError(f"Failed to extract PDF metadata: {e}")

    def _count_pages_basic(self, pdf_data: bytes) -> int:
        """基本的なページ数カウント"""
        # /Count パターンを探す
        count_pattern = rb'/Count\s+(\d+)'
        matches = re.findall(count_pattern, pdf_data)
        if matches:
            return max(int(m) for m in matches)
        return 1

    def _detect_pdf_type(self, pdf_data: bytes) -> PDFType:
        """PDFタイプを判定"""
        try:
            import pypdf

            with io.BytesIO(pdf_data) as buffer:
                reader = pypdf.PdfReader(buffer)

                # サンプルページでテキスト抽出を試行
                text_pages = 0
                image_pages = 0

                for i, page in enumerate(reader.pages[:5]):  # 最初の5ページをサンプル
                    text = page.extract_text() or ""
                    if len(text.strip()) > 50:  # 有意なテキストがある
                        text_pages += 1
                    else:
                        image_pages += 1

                if text_pages > 0 and image_pages > 0:
                    return PDFType.MIXED
                elif text_pages > 0:
                    return PDFType.TEXT_BASED
                else:
                    return PDFType.SCANNED

        except Exception as e:
            logger.warning(f"PDF type detection failed: {e}")
            return PDFType.TEXT_BASED  # デフォルト

    async def _extract_text(
        self,
        pdf_data: bytes,
        pdf_type: PDFType,
        page_count: int,
    ) -> List[PDFPageContent]:
        """テキストを抽出"""
        pages = []

        if pdf_type == PDFType.TEXT_BASED:
            pages = self._extract_text_pypdf(pdf_data)
        elif pdf_type == PDFType.SCANNED:
            pages = await self._extract_text_ocr(pdf_data, page_count)
        else:  # MIXED
            # テキスト抽出を試み、不十分なページはOCR
            text_pages = self._extract_text_pypdf(pdf_data)
            for i, page in enumerate(text_pages):
                if len(page.text.strip()) < 50:
                    # OCRが必要
                    try:
                        ocr_page = await self._ocr_page(pdf_data, i)
                        text_pages[i] = ocr_page
                    except Exception as e:
                        logger.warning(f"OCR failed for page {i}: {e}")
            pages = text_pages

        return pages

    def _extract_text_pypdf(self, pdf_data: bytes) -> List[PDFPageContent]:
        """PyPDF2でテキスト抽出"""
        pages = []

        try:
            import pypdf

            with io.BytesIO(pdf_data) as buffer:
                reader = pypdf.PdfReader(buffer)

                for i, page in enumerate(reader.pages):
                    text = page.extract_text() or ""

                    # 見出し抽出
                    headings = self._extract_headings_from_text(text)

                    pages.append(PDFPageContent(
                        page_number=i + 1,
                        text=text,
                        has_images=self._page_has_images(page),
                        image_count=self._count_page_images(page),
                        ocr_used=False,
                        headings=headings,
                    ))

        except Exception as e:
            raise PDFProcessingError(f"Failed to extract text: {e}")

        return pages

    async def _extract_text_ocr(
        self,
        pdf_data: bytes,
        page_count: int,
    ) -> List[PDFPageContent]:
        """OCRでテキスト抽出"""
        pages = []

        for i in range(min(page_count, MAX_PDF_PAGES)):
            try:
                page = await self._ocr_page(pdf_data, i)
                pages.append(page)
            except Exception as e:
                logger.warning(f"OCR failed for page {i}: {e}")
                pages.append(PDFPageContent(
                    page_number=i + 1,
                    text="",
                    ocr_used=True,
                    ocr_confidence=0.0,
                ))

        return pages

    async def _ocr_page(self, pdf_data: bytes, page_index: int) -> PDFPageContent:
        """単一ページをOCR"""
        try:
            # PDFページを画像に変換
            image_data = self._pdf_page_to_image(pdf_data, page_index)

            if not image_data:
                raise PDFOCRError(page_number=page_index + 1)

            # Vision APIでOCR
            prompt = """このPDFページの画像からテキストを正確に抽出してください。

回答形式:
```json
{
    "text": "抽出されたテキスト全文",
    "confidence": 0.0-1.0,
    "headings": ["見出し1", "見出し2"]
}
```"""

            result = await self._vision_client.analyze_with_fallback(
                image_data=image_data,
                prompt=prompt,
            )

            # 結果パース
            parsed = self._parse_ocr_result(result["content"])

            return PDFPageContent(
                page_number=page_index + 1,
                text=parsed.get("text", ""),
                has_images=True,
                ocr_used=True,
                ocr_confidence=parsed.get("confidence", 0.7),
                headings=parsed.get("headings", []),
            )

        except Exception as e:
            raise PDFOCRError(page_number=page_index + 1)

    def _pdf_page_to_image(self, pdf_data: bytes, page_index: int) -> Optional[bytes]:
        """PDFページを画像に変換"""
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=pdf_data, filetype="pdf")
            page = doc[page_index]

            # 画像としてレンダリング
            mat = fitz.Matrix(PDF_OCR_DPI / 72, PDF_OCR_DPI / 72)
            pix = page.get_pixmap(matrix=mat)

            # PNGとして出力
            return pix.tobytes("png")

        except ImportError:
            logger.warning("PyMuPDF not available for PDF rendering")
            return None
        except Exception as e:
            logger.warning(f"PDF page to image conversion failed: {e}")
            return None

    def _parse_ocr_result(self, content: str) -> Dict[str, Any]:
        """OCR結果をパース"""
        try:
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))

            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1:
                return json.loads(content[start:end + 1])

        except Exception:
            pass

        return {"text": content, "confidence": 0.5}

    def _page_has_images(self, page) -> bool:
        """ページに画像があるかチェック"""
        try:
            resources = page.get("/Resources", {})
            xobject = resources.get("/XObject", {})
            return len(xobject) > 0
        except Exception:
            return False

    def _count_page_images(self, page) -> int:
        """ページの画像数をカウント"""
        try:
            resources = page.get("/Resources", {})
            xobject = resources.get("/XObject", {})
            return len(xobject)
        except Exception:
            return 0

    def _extract_headings_from_text(self, text: str) -> List[str]:
        """テキストから見出しを抽出"""
        headings = []

        # 一般的な見出しパターン
        patterns = [
            r'^(\d+[\.\s]+.+?)$',  # 1. 見出し
            r'^(第\d+[章節項].+?)$',  # 第1章 見出し
            r'^([■●▪▶].+?)$',  # 記号付き見出し
            r'^([A-Z][A-Z\s]+:)$',  # 大文字の見出し
        ]

        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue

            for pattern in patterns:
                match = re.match(pattern, line, re.MULTILINE)
                if match:
                    headings.append(match.group(1))
                    break

        return headings[:20]  # 最大20件

    def _extract_all_headings(self, pages: List[PDFPageContent]) -> List[str]:
        """全ページから見出しを収集"""
        all_headings = []
        for page in pages:
            all_headings.extend(page.headings)
        return all_headings

    def _extract_all_tables(self, pages: List[PDFPageContent]) -> List[Dict[str, Any]]:
        """全ページから表を収集"""
        all_tables = []
        for page in pages:
            all_tables.extend(page.tables)
        return all_tables

    def _generate_table_of_contents(self, headings: List[str]) -> List[Dict[str, Any]]:
        """目次を生成"""
        toc = []
        for i, heading in enumerate(headings[:30]):
            toc.append({
                "index": i + 1,
                "title": heading,
            })
        return toc

    async def _generate_summary(
        self,
        full_text: str,
        pdf_metadata: PDFMetadata,
        instruction: Optional[str] = None,
    ) -> Tuple[str, List[str]]:
        """要約を生成"""
        if not full_text.strip():
            return "", []

        # テキストを制限
        text_for_summary = full_text[:20000]

        prompt = f"""以下のPDFドキュメントを分析し、要約と重要ポイントを抽出してください。

ドキュメント情報:
- タイトル: {pdf_metadata.title or '不明'}
- ページ数: {pdf_metadata.page_count}

コンテンツ:
{text_for_summary}

回答はJSON形式で:
```json
{{
    "summary": "3-5文の要約",
    "key_points": ["重要ポイント1", "重要ポイント2", "重要ポイント3"]
}}
```"""

        if instruction:
            prompt += f"\n\n追加の指示: {instruction}"

        try:
            result = await self._vision_client.analyze_with_fallback(
                image_data=b"",  # テキストのみ
                prompt=prompt,
            )

            # 結果パース
            parsed = self._parse_ocr_result(result["content"])
            summary = parsed.get("summary", "")
            key_points = parsed.get("key_points", [])

            if len(summary) > MAX_SUMMARY_LENGTH:
                summary = summary[:MAX_SUMMARY_LENGTH]

            return summary, key_points

        except Exception as e:
            logger.warning(f"Summary generation failed: {e}")
            # フォールバック: 最初の数文を要約として使用
            sentences = re.split(r'[。．\n]', full_text)
            summary = "。".join(sentences[:3]) + "。"
            return summary[:MAX_SUMMARY_LENGTH], []

    def _calculate_overall_confidence(
        self,
        pages: List[PDFPageContent],
        pdf_type: PDFType,
    ) -> float:
        """全体の確信度を計算"""
        if not pages:
            return 0.5

        if pdf_type == PDFType.TEXT_BASED:
            return 0.9  # テキストベースは高信頼

        # OCRの平均確信度
        ocr_pages = [p for p in pages if p.ocr_used]
        if ocr_pages:
            avg_confidence = sum(p.ocr_confidence for p in ocr_pages) / len(ocr_pages)
            return avg_confidence

        return 0.7

    async def _save_to_knowledge(
        self,
        pdf_data: bytes,
        pdf_metadata: PDFMetadata,
        full_text: str,
        summary: str,
    ) -> Tuple[bool, Optional[str]]:
        """ナレッジDBに保存"""
        # TODO: ナレッジDB連携の実装
        logger.info("Knowledge DB save requested (not implemented yet)")
        return False, None


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_pdf_processor(
    pool,
    organization_id: str,
    api_key: Optional[str] = None,
) -> PDFProcessor:
    """
    PDFProcessorを作成するファクトリー関数

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        api_key: OpenRouter API Key

    Returns:
        PDFProcessor
    """
    return PDFProcessor(
        pool=pool,
        organization_id=organization_id,
        api_key=api_key,
    )
