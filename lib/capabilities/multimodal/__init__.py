# lib/capabilities/multimodal/__init__.py
"""
Phase M1: Multimodal入力能力パッケージ

ソウルくんに「目」と「耳」を与える。
テキスト以外の入力（画像、PDF、URL）を理解できるようにする。

設計書: docs/20_next_generation_capabilities.md セクション5

使用例:
    from lib.capabilities.multimodal import (
        ImageProcessor,
        PDFProcessor,
        URLProcessor,
        MultimodalInput,
        InputType,
    )

    # 画像処理
    processor = ImageProcessor(pool, org_id)
    result = await processor.process(MultimodalInput(
        input_type=InputType.IMAGE,
        organization_id=org_id,
        image_data=image_bytes,
        instruction="領収書の内容を読み取って",
    ))

    # PDF処理
    processor = PDFProcessor(pool, org_id)
    result = await processor.process(MultimodalInput(
        input_type=InputType.PDF,
        organization_id=org_id,
        pdf_data=pdf_bytes,
        save_to_knowledge=True,
    ))

    # URL処理
    processor = URLProcessor(pool, org_id)
    result = await processor.process(MultimodalInput(
        input_type=InputType.URL,
        organization_id=org_id,
        url="https://example.com/article",
    ))

Author: Claude Opus 4.5
Created: 2026-01-27
"""

__version__ = "1.0.0"
__author__ = "Claude Opus 4.5"


# =============================================================================
# 定数
# =============================================================================

from .constants import (
    # 列挙型
    InputType,
    ProcessingStatus,
    ImageType,
    PDFType,
    URLType,
    ContentConfidenceLevel,

    # サポートフォーマット
    SUPPORTED_IMAGE_FORMATS,
    SUPPORTED_PDF_FORMATS,
    SUPPORTED_URL_PROTOCOLS,

    # サイズ制限
    MAX_IMAGE_SIZE_BYTES,
    MAX_PDF_SIZE_BYTES,
    MAX_PDF_PAGES,
    MAX_URL_CONTENT_SIZE_BYTES,

    # タイムアウト
    VISION_API_TIMEOUT_SECONDS,
    PDF_PROCESSING_TIMEOUT_SECONDS,
    URL_FETCH_TIMEOUT_SECONDS,

    # Vision APIモデル
    VISION_MODELS,
    DEFAULT_VISION_MODEL,

    # Feature Flag
    FEATURE_FLAG_NAME,
    FEATURE_FLAG_IMAGE,
    FEATURE_FLAG_PDF,
    FEATURE_FLAG_URL,
)


# =============================================================================
# 例外
# =============================================================================

from .exceptions import (
    # 基底例外
    MultimodalBaseException,

    # 検証エラー
    ValidationError,
    UnsupportedFormatError,
    FileTooLargeError,
    TooManyPagesError,

    # 画像エラー
    ImageProcessingError,
    ImageDecodeError,
    ImageDimensionError,

    # PDFエラー
    PDFProcessingError,
    PDFDecodeError,
    PDFEncryptedError,
    PDFOCRError,

    # URLエラー
    URLProcessingError,
    URLBlockedError,
    URLFetchError,
    URLTimeoutError,
    URLParseError,
    URLContentExtractionError,

    # Vision APIエラー
    VisionAPIError,
    VisionAPITimeoutError,
    VisionAPIRateLimitError,

    # 汎用エラー
    ContentExtractionError,
    ProcessingTimeoutError,

    # デコレータ
    wrap_multimodal_error,
    wrap_sync_multimodal_error,
)


# =============================================================================
# データモデル
# =============================================================================

from .models import (
    # 共通モデル
    ProcessingMetadata,
    ExtractedEntity,

    # 画像モデル
    ImageMetadata,
    ImageAnalysisResult,

    # PDFモデル
    PDFPageContent,
    PDFMetadata,
    PDFAnalysisResult,

    # URLモデル
    URLMetadata,
    URLAnalysisResult,

    # 統合モデル
    MultimodalInput,
    MultimodalOutput,
)


# =============================================================================
# プロセッサー
# =============================================================================

from .base import (
    BaseMultimodalProcessor,
    VisionAPIClient,
)

from .image_processor import (
    ImageProcessor,
    create_image_processor,
)

from .pdf_processor import (
    PDFProcessor,
    create_pdf_processor,
)

from .url_processor import (
    URLProcessor,
    create_url_processor,
)

from .coordinator import (
    MultimodalCoordinator,
    create_multimodal_coordinator,
    AttachmentType,
    AttachmentInfo,
    ProcessedAttachment,
    EnrichedMessage,
)

from .brain_integration import (
    MultimodalBrainContext,
    process_message_with_multimodal,
    create_multimodal_context,
    should_process_as_multimodal,
    extract_instruction_from_message,
    format_multimodal_response,
    handle_chatwork_message_with_attachments,
)


# =============================================================================
# 公開API
# =============================================================================

__all__ = [
    # バージョン
    "__version__",

    # 定数 - 列挙型
    "InputType",
    "ProcessingStatus",
    "ImageType",
    "PDFType",
    "URLType",
    "ContentConfidenceLevel",

    # 定数 - サポートフォーマット
    "SUPPORTED_IMAGE_FORMATS",
    "SUPPORTED_PDF_FORMATS",
    "SUPPORTED_URL_PROTOCOLS",

    # 定数 - サイズ制限
    "MAX_IMAGE_SIZE_BYTES",
    "MAX_PDF_SIZE_BYTES",
    "MAX_PDF_PAGES",
    "MAX_URL_CONTENT_SIZE_BYTES",

    # 定数 - タイムアウト
    "VISION_API_TIMEOUT_SECONDS",
    "PDF_PROCESSING_TIMEOUT_SECONDS",
    "URL_FETCH_TIMEOUT_SECONDS",

    # 定数 - Vision API
    "VISION_MODELS",
    "DEFAULT_VISION_MODEL",

    # 定数 - Feature Flag
    "FEATURE_FLAG_NAME",
    "FEATURE_FLAG_IMAGE",
    "FEATURE_FLAG_PDF",
    "FEATURE_FLAG_URL",

    # 例外 - 基底
    "MultimodalBaseException",

    # 例外 - 検証
    "ValidationError",
    "UnsupportedFormatError",
    "FileTooLargeError",
    "TooManyPagesError",

    # 例外 - 画像
    "ImageProcessingError",
    "ImageDecodeError",
    "ImageDimensionError",

    # 例外 - PDF
    "PDFProcessingError",
    "PDFDecodeError",
    "PDFEncryptedError",
    "PDFOCRError",

    # 例外 - URL
    "URLProcessingError",
    "URLBlockedError",
    "URLFetchError",
    "URLTimeoutError",
    "URLParseError",
    "URLContentExtractionError",

    # 例外 - Vision API
    "VisionAPIError",
    "VisionAPITimeoutError",
    "VisionAPIRateLimitError",

    # 例外 - 汎用
    "ContentExtractionError",
    "ProcessingTimeoutError",

    # 例外 - デコレータ
    "wrap_multimodal_error",
    "wrap_sync_multimodal_error",

    # モデル - 共通
    "ProcessingMetadata",
    "ExtractedEntity",

    # モデル - 画像
    "ImageMetadata",
    "ImageAnalysisResult",

    # モデル - PDF
    "PDFPageContent",
    "PDFMetadata",
    "PDFAnalysisResult",

    # モデル - URL
    "URLMetadata",
    "URLAnalysisResult",

    # モデル - 統合
    "MultimodalInput",
    "MultimodalOutput",

    # プロセッサー - 基盤
    "BaseMultimodalProcessor",
    "VisionAPIClient",

    # プロセッサー - 画像
    "ImageProcessor",
    "create_image_processor",

    # プロセッサー - PDF
    "PDFProcessor",
    "create_pdf_processor",

    # プロセッサー - URL
    "URLProcessor",
    "create_url_processor",

    # コーディネーター
    "MultimodalCoordinator",
    "create_multimodal_coordinator",
    "AttachmentType",
    "AttachmentInfo",
    "ProcessedAttachment",
    "EnrichedMessage",

    # 脳統合
    "MultimodalBrainContext",
    "process_message_with_multimodal",
    "create_multimodal_context",
    "should_process_as_multimodal",
    "extract_instruction_from_message",
    "format_multimodal_response",
    "handle_chatwork_message_with_attachments",
]
