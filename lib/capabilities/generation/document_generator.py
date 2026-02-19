# lib/capabilities/generation/document_generator.py
"""
Phase G1: 文書生成能力 - 文書ジェネレーター

このモジュールは、文書生成のメインロジックを提供します。

設計書: docs/20_next_generation_capabilities.md セクション6
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from typing import Optional, Dict, Any, List, TYPE_CHECKING
from uuid import UUID
import logging
import json
import asyncio
import time

from .constants import (
    GenerationType,
    DocumentType,
    GenerationStatus,
    OutputFormat,
    SectionType,
    QualityLevel,
    ToneStyle,
    MAX_DOCUMENT_SECTIONS,
    MAX_SECTION_LENGTH,
    MAX_TITLE_LENGTH,
    OUTLINE_GENERATION_PROMPT,
    SECTION_GENERATION_PROMPT,
    DOCUMENT_TYPE_DEFAULT_SECTIONS,
    DOCUMENT_TYPE_KEYWORDS,
    OUTLINE_GENERATION_TIMEOUT,
    SECTION_GENERATION_TIMEOUT,
)
from .exceptions import (
    ValidationError,
    EmptyTitleError,
    TitleTooLongError,
    InvalidDocumentTypeError,
    TooManySectionsError,
    InsufficientContextError,
    OutlineGenerationError,
    OutlineTimeoutError,
    SectionGenerationError,
    SectionTimeoutError,
    DocumentGenerationError,
)
from .models import (
    DocumentRequest,
    DocumentResult,
    DocumentOutline,
    SectionOutline,
    SectionContent,
    GenerationMetadata,
    GenerationInput,
    GenerationOutput,
    ReferenceDocument,
)
from .base import BaseGenerator
from .google_docs_client import GoogleDocsClient, create_google_docs_client

if TYPE_CHECKING:
    from asyncpg import Pool


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# 文書ジェネレーター
# =============================================================================


class DocumentGenerator(BaseGenerator):
    """
    文書ジェネレーター

    文書の構成案生成、セクション生成、Google Docs出力を行う。
    """

    def __init__(
        self,
        pool: "Pool",
        organization_id: UUID,
        api_key: Optional[str] = None,
        google_credentials_path: Optional[str] = None,
        google_credentials_json: Optional[Dict[str, Any]] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            api_key: LLM API Key
            google_credentials_path: Google認証情報パス
            google_credentials_json: Google認証情報（JSON）
        """
        super().__init__(pool, organization_id, api_key)
        self._generation_type = GenerationType.DOCUMENT
        self._google_client = create_google_docs_client(
            credentials_path=google_credentials_path,
            credentials_json=google_credentials_json,
        )

    async def generate(self, input_data: GenerationInput) -> GenerationOutput:
        """
        文書を生成

        Args:
            input_data: 入力データ

        Returns:
            生成結果
        """
        request = input_data.document_request
        if not request:
            raise ValidationError(
                message="DocumentRequestが必要です",
                field="document_request",
            )

        # 入力検証
        self.validate(input_data)

        # メタデータ初期化
        metadata = self._create_metadata(user_id=request.user_id)
        self._log_generation_start(
            "document",
            details={
                "title": request.title,
                "document_type": request.document_type.value,
            },
        )

        try:
            # 1. アウトライン生成
            outline = await self._generate_outline(request)

            # 確認が必要な場合は一旦返す
            if request.require_confirmation:
                result = DocumentResult(
                    status=GenerationStatus.PENDING,
                    success=True,
                    document_title=request.title,
                    outline=outline,
                    metadata=metadata,
                )
                return GenerationOutput(
                    generation_type=GenerationType.DOCUMENT,
                    success=True,
                    status=GenerationStatus.PENDING,
                    document_result=result,
                    metadata=metadata,
                )

            # 2. 全文生成
            return await self._generate_full_document(request, outline, metadata)

        except Exception as e:
            logger.error(f"Document generation failed: {str(e)}")
            metadata.complete(
                success=False,
                error_message=str(e),
                error_code=getattr(e, "error_code", "GENERATION_ERROR"),
            )

            result = DocumentResult(
                status=GenerationStatus.FAILED,
                success=False,
                document_title=request.title,
                error_message=str(e),
                error_code=getattr(e, "error_code", "GENERATION_ERROR"),
                metadata=metadata,
            )

            return GenerationOutput(
                generation_type=GenerationType.DOCUMENT,
                success=False,
                status=GenerationStatus.FAILED,
                document_result=result,
                metadata=metadata,
                error_message=str(e),
            )

    async def generate_from_outline(
        self,
        request: DocumentRequest,
        outline: DocumentOutline,
    ) -> GenerationOutput:
        """
        承認済みアウトラインから文書を生成

        Args:
            request: 文書リクエスト
            outline: 承認済みアウトライン

        Returns:
            生成結果
        """
        metadata = self._create_metadata(user_id=request.user_id)
        return await self._generate_full_document(request, outline, metadata)

    def validate(self, input_data: GenerationInput) -> None:
        """
        入力を検証

        Args:
            input_data: 入力データ

        Raises:
            ValidationError: 検証エラー
        """
        request = input_data.document_request

        if not request:
            raise ValidationError(
                message="DocumentRequestが必要です",
                field="document_request",
            )

        # タイトル検証
        if not request.title or not request.title.strip():
            raise EmptyTitleError()

        if len(request.title) > MAX_TITLE_LENGTH:
            raise TitleTooLongError(
                actual_length=len(request.title),
                max_length=MAX_TITLE_LENGTH,
            )

        # 文書タイプ検証
        if request.document_type not in DocumentType:
            raise InvalidDocumentTypeError(document_type=str(request.document_type))

        # カスタムアウトライン検証
        if request.custom_outline:
            if len(request.custom_outline.sections) > MAX_DOCUMENT_SECTIONS:
                raise TooManySectionsError(
                    actual_count=len(request.custom_outline.sections),
                    max_count=MAX_DOCUMENT_SECTIONS,
                )

    # =========================================================================
    # 内部メソッド
    # =========================================================================

    async def _generate_outline(self, request: DocumentRequest) -> DocumentOutline:
        """
        アウトラインを生成

        Args:
            request: 文書リクエスト

        Returns:
            生成されたアウトライン
        """
        # カスタムアウトラインがある場合はそれを使用
        if request.custom_outline:
            return request.custom_outline

        # デフォルトセクションがある場合
        default_sections = DOCUMENT_TYPE_DEFAULT_SECTIONS.get(request.document_type.value)
        if default_sections and not request.instruction:
            sections = [
                SectionOutline(
                    section_id=i,
                    title=title,
                    section_type=SectionType.HEADING1,
                    order=i,
                )
                for i, title in enumerate(default_sections)
            ]
            return DocumentOutline(
                title=request.title,
                document_type=request.document_type,
                sections=sections,
            )

        # LLMでアウトライン生成
        context = self._build_context(request)

        prompt = OUTLINE_GENERATION_PROMPT.format(
            document_type=request.document_type.value,
            title=request.title,
            purpose=request.purpose or "（指定なし）",
            context=context,
            instruction=request.instruction or "適切な構成を提案してください",
        )

        try:
            result = await asyncio.wait_for(
                self._call_llm_json(
                    prompt=prompt,
                    system_prompt="あなたは優秀な文書作成アシスタントです。日本語で文書の構成案を作成してください。",
                    temperature=0.5,
                    task_type="outline",
                    quality_level=request.quality_level,
                ),
                timeout=OUTLINE_GENERATION_TIMEOUT,
            )

            parsed = result.get("parsed")
            if not parsed:
                # パース失敗時はデフォルト構成を使用
                logger.warning("Outline parse failed, using default structure")
                return self._create_default_outline(request)

            # アウトラインを構築
            sections = []
            for i, section_data in enumerate(parsed.get("sections", [])):
                sections.append(SectionOutline(
                    section_id=i,
                    title=section_data.get("title", f"セクション {i + 1}"),
                    description=section_data.get("description", ""),
                    section_type=SectionType.HEADING1,
                    estimated_length=self._parse_estimated_length(
                        section_data.get("estimated_length", "500")
                    ),
                    order=i,
                ))

            return DocumentOutline(
                title=request.title,
                document_type=request.document_type,
                sections=sections,
                notes=parsed.get("notes", ""),
                model_used=result.get("model"),
                tokens_used=result.get("total_tokens", 0),
            )

        except asyncio.TimeoutError:
            logger.error(f"Outline generation timed out after {OUTLINE_GENERATION_TIMEOUT}s")
            raise OutlineTimeoutError(timeout_seconds=OUTLINE_GENERATION_TIMEOUT)
        except Exception as e:
            logger.error(f"Outline generation failed: {str(e)}")
            raise OutlineGenerationError(original_error=e)

    async def _generate_full_document(
        self,
        request: DocumentRequest,
        outline: DocumentOutline,
        metadata: GenerationMetadata,
    ) -> GenerationOutput:
        """
        全文書を生成

        Args:
            request: 文書リクエスト
            outline: アウトライン
            metadata: メタデータ

        Returns:
            生成結果
        """
        # 各セクションを生成
        sections = []
        total_tokens = outline.tokens_used
        context = self._build_context(request)

        for i, section_outline in enumerate(outline.sections):
            try:
                previous_section = outline.sections[i - 1].title if i > 0 else "（なし）"
                next_section = (
                    outline.sections[i + 1].title
                    if i < len(outline.sections) - 1
                    else "（なし）"
                )

                section_content = await self._generate_section(
                    document_title=request.title,
                    document_type=request.document_type,
                    section_outline=section_outline,
                    previous_section=previous_section,
                    next_section=next_section,
                    context=context,
                    tone=request.tone_style,
                    quality_level=request.quality_level,
                )

                sections.append(section_content)
                total_tokens += section_content.tokens_used

            except Exception as e:
                logger.error(f"Section generation failed: {section_outline.title}, {str(e)}")
                raise SectionGenerationError(
                    section_title=section_outline.title,
                    section_index=i,
                    original_error=e,
                )

        # Google Docsに保存を試行、失敗時はGCSフォールバック
        document_id = None
        document_url = None
        try:
            doc_info = await self._google_client.create_document(
                title=request.title,
                folder_id=request.target_folder_id,
            )
            document_id = doc_info["document_id"]
            document_url = doc_info["document_url"]

            await self._google_client.update_document(
                document_id=document_id,
                sections=sections,
            )

            if request.share_with:
                await self._google_client.share_document(
                    document_id=document_id,
                    email_addresses=request.share_with,
                    role="writer",
                )
        except Exception as e:
            logger.warning("Google Docs unavailable, falling back to GCS: %s", str(e)[:200])
            document_id, document_url = await self._save_to_gcs_fallback(
                request.title, sections,
            )

        # 全文を結合
        full_content = "\n\n".join([s.to_markdown() for s in sections])
        total_word_count = sum(s.word_count for s in sections)

        # コスト計算
        estimated_cost = self._calculate_cost(
            input_tokens=total_tokens // 2,
            output_tokens=total_tokens // 2,
            model=metadata.model_used or "claude-sonnet-4-20250514",
        )

        # メタデータを完了
        metadata.total_tokens_used = total_tokens
        metadata.estimated_cost_jpy = estimated_cost
        metadata.complete(success=True)

        self._log_generation_complete(
            success=True,
            processing_time_ms=metadata.processing_time_ms,
            details={
                "document_id": document_id,
                "sections": len(sections),
                "word_count": total_word_count,
            },
        )

        result = DocumentResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            document_id=document_id,
            document_url=document_url,
            document_title=request.title,
            outline=outline,
            sections=sections,
            full_content=full_content,
            total_word_count=total_word_count,
            total_sections=len(sections),
            metadata=metadata,
        )

        return GenerationOutput(
            generation_type=GenerationType.DOCUMENT,
            success=True,
            status=GenerationStatus.COMPLETED,
            document_result=result,
            metadata=metadata,
        )

    async def _generate_section(
        self,
        document_title: str,
        document_type: DocumentType,
        section_outline: SectionOutline,
        previous_section: str,
        next_section: str,
        context: str,
        tone: ToneStyle,
        quality_level: QualityLevel,
    ) -> SectionContent:
        """
        セクションを生成

        Args:
            document_title: 文書タイトル
            document_type: 文書タイプ
            section_outline: セクションアウトライン
            previous_section: 前のセクション名
            next_section: 次のセクション名
            context: コンテキスト
            tone: トーン
            quality_level: 品質レベル

        Returns:
            生成されたセクション
        """
        prompt = SECTION_GENERATION_PROMPT.format(
            document_title=document_title,
            document_type=document_type.value,
            section_title=section_outline.title,
            section_description=section_outline.description or "適切な内容を作成",
            previous_section=previous_section,
            next_section=next_section,
            context=context,
            tone=tone.value,
        )

        start_time = time.time()

        try:
            result = await asyncio.wait_for(
                self._call_llm(
                    prompt=prompt,
                    system_prompt="あなたは優秀な文書作成アシスタントです。指示に従って日本語でセクションの内容を作成してください。",
                    temperature=0.3,
                    task_type="content",
                    quality_level=quality_level,
                ),
                timeout=SECTION_GENERATION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"Section generation timed out after {SECTION_GENERATION_TIMEOUT}s: "
                f"{section_outline.title}"
            )
            raise SectionTimeoutError(
                timeout_seconds=SECTION_GENERATION_TIMEOUT,
                section_title=section_outline.title,
            )

        generation_time_ms = int((time.time() - start_time) * 1000)
        content = result.get("text", "")

        # 長すぎる場合はトリミング
        if len(content) > MAX_SECTION_LENGTH:
            content = content[:MAX_SECTION_LENGTH] + "\n\n（以下省略）"

        return SectionContent(
            section_id=section_outline.section_id,
            title=section_outline.title,
            content=content,
            section_type=section_outline.section_type,
            tokens_used=result.get("total_tokens", 0),
            generation_time_ms=generation_time_ms,
            model_used=result.get("model"),
        )

    def _build_context(self, request: DocumentRequest) -> str:
        """
        コンテキスト情報を構築

        Args:
            request: 文書リクエスト

        Returns:
            コンテキスト文字列
        """
        parts = []

        if request.context:
            parts.append(f"【追加コンテキスト】\n{request.context}")

        if request.keywords:
            parts.append(f"【キーワード】\n{', '.join(request.keywords)}")

        if request.reference_documents:
            ref_parts = ["【参照文書】"]
            for ref in request.reference_documents[:5]:
                ref_parts.append(f"- {ref.title}")
                if ref.content:
                    ref_parts.append(f"  {ref.content[:500]}...")
            parts.append("\n".join(ref_parts))

        return "\n\n".join(parts) if parts else "（コンテキストなし）"

    def _create_default_outline(self, request: DocumentRequest) -> DocumentOutline:
        """デフォルトアウトラインを作成"""
        default_sections = DOCUMENT_TYPE_DEFAULT_SECTIONS.get(
            request.document_type.value,
            ["概要", "内容", "まとめ"],
        )

        sections = [
            SectionOutline(
                section_id=i,
                title=title,
                section_type=SectionType.HEADING1,
                order=i,
            )
            for i, title in enumerate(default_sections)
        ]

        return DocumentOutline(
            title=request.title,
            document_type=request.document_type,
            sections=sections,
        )

    def _parse_estimated_length(self, value: str) -> int:
        """推定文字数をパース"""
        try:
            # "500文字" -> 500, "1,000" -> 1000 など
            import re
            numbers = re.findall(r'\d+', value.replace(",", ""))
            if numbers:
                return int(numbers[0])
        except Exception:
            pass
        return 500  # デフォルト

    async def _save_to_gcs_fallback(
        self,
        title: str,
        sections: list,
    ) -> tuple:
        """Google Docs失敗時にGCSにMarkdownとして保存する"""
        try:
            import os
            import asyncio
            from datetime import datetime, timezone, timedelta
            from google.cloud import storage

            bucket_name = os.getenv("OPERATIONS_GCS_BUCKET", "")
            if not bucket_name:
                logger.warning("OPERATIONS_GCS_BUCKET not set, skipping GCS fallback")
                return "local", ""

            full_content = "\n\n".join([s.to_markdown() for s in sections])
            md_content = f"# {title}\n\n{full_content}"

            jst = timezone(timedelta(hours=9))
            now = datetime.now(jst)
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(c for c in title if c.isalnum() or c in "_ -")[:50]
            blob_path = f"{self._organization_id}/documents/{timestamp}_{safe_title}.md"

            def _upload():
                client = storage.Client()
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(blob_path)
                blob.upload_from_string(md_content, content_type="text/markdown; charset=utf-8")
                return f"gs://{bucket_name}/{blob_path}"

            gcs_path = await asyncio.to_thread(_upload)
            logger.info("Document saved to GCS fallback: %s", gcs_path)
            return f"gcs:{blob_path}", gcs_path

        except Exception as e:
            logger.error("GCS fallback also failed: %s: %s", type(e).__name__, str(e)[:200])
            return "local", ""

    def detect_document_type(self, instruction: str) -> DocumentType:
        """
        指示から文書タイプを推測

        Args:
            instruction: ユーザーの指示

        Returns:
            推測された文書タイプ
        """
        instruction_lower = instruction.lower()

        for doc_type, keywords in DOCUMENT_TYPE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in instruction_lower:
                    return DocumentType(doc_type)

        return DocumentType.CUSTOM


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_document_generator(
    pool: "Pool",
    organization_id: UUID,
    api_key: Optional[str] = None,
    google_credentials_path: Optional[str] = None,
    google_credentials_json: Optional[Dict[str, Any]] = None,
) -> DocumentGenerator:
    """
    DocumentGeneratorを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        api_key: LLM API Key
        google_credentials_path: Google認証情報パス
        google_credentials_json: Google認証情報（JSON）

    Returns:
        DocumentGenerator
    """
    return DocumentGenerator(
        pool=pool,
        organization_id=organization_id,
        api_key=api_key,
        google_credentials_path=google_credentials_path,
        google_credentials_json=google_credentials_json,
    )
