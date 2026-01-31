# lib/capabilities/generation/__init__.py
"""
Phase G1: 文書生成能力パッケージ

ソウルくんに「手」を与える。
テキスト文書（報告書、提案書、議事録等）を生成できるようにする。

設計書: docs/20_next_generation_capabilities.md セクション6

使用例:
    from lib.capabilities.generation import (
        DocumentGenerator,
        DocumentRequest,
        DocumentResult,
        DocumentType,
        GenerationStatus,
    )

    # 文書生成リクエスト
    request = DocumentRequest(
        title="週次報告書",
        organization_id=org_id,
        document_type=DocumentType.REPORT,
        instruction="今週の進捗をまとめて",
    )

    # 入力を構築
    input_data = GenerationInput(
        generation_type=GenerationType.DOCUMENT,
        organization_id=org_id,
        document_request=request,
    )

    # 生成
    generator = DocumentGenerator(pool, org_id)
    result = await generator.generate(input_data)

    if result.document_result.status == GenerationStatus.PENDING:
        # アウトラインの確認を待つ
        print(result.document_result.outline.to_user_display())
    elif result.document_result.status == GenerationStatus.COMPLETED:
        # 完成
        print(result.document_result.document_url)

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
    GenerationType,
    DocumentType,
    GenerationStatus,
    OutputFormat,
    SectionType,
    ConfirmationLevel,
    QualityLevel,
    ToneStyle,

    # サポートフォーマット
    SUPPORTED_DOCUMENT_TYPES,
    SUPPORTED_OUTPUT_FORMATS,

    # サイズ制限
    MAX_DOCUMENT_SECTIONS,
    MAX_SECTION_LENGTH,
    MAX_DOCUMENT_LENGTH,
    MAX_TITLE_LENGTH,
    MAX_OUTLINE_ITEMS,
    MAX_REQUEST_CONTEXT_LENGTH,
    MAX_REFERENCE_DOCUMENTS,
    MAX_TEMPLATE_SIZE_BYTES,

    # タイムアウト
    OUTLINE_GENERATION_TIMEOUT,
    SECTION_GENERATION_TIMEOUT,
    FULL_DOCUMENT_GENERATION_TIMEOUT,
    GOOGLE_DOCS_API_TIMEOUT,
    INFO_GATHERING_TIMEOUT,

    # LLM設定
    DEFAULT_GENERATION_MODEL,
    HIGH_QUALITY_MODEL,
    FAST_MODEL,
    TEMPERATURE_SETTINGS,

    # Google API設定
    GOOGLE_DOCS_API_VERSION,
    GOOGLE_DOCS_SCOPES,
    GOOGLE_DRIVE_API_VERSION,
    GOOGLE_DRIVE_SCOPES,

    # Feature Flag
    FEATURE_FLAG_NAME,
    FEATURE_FLAG_DOCUMENT,
    FEATURE_FLAG_IMAGE,
    FEATURE_FLAG_RESEARCH,

    # テンプレート設定
    DEFAULT_TEMPLATE_ID,
    DOCUMENT_TYPE_DEFAULT_SECTIONS,

    # プロンプトテンプレート
    OUTLINE_GENERATION_PROMPT,
    SECTION_GENERATION_PROMPT,

    # エラーメッセージ
    ERROR_MESSAGES,

    # 文書タイプキーワード
    DOCUMENT_TYPE_KEYWORDS,

    # コスト設定
    COST_PER_1K_TOKENS,
    OUTPUT_COST_MULTIPLIER,

    # G2: 画像生成定数
    ImageProvider,
    ImageSize,
    ImageQuality,
    ImageStyle,
    DEFAULT_IMAGE_PROVIDER,
    DEFAULT_IMAGE_SIZE,
    DEFAULT_IMAGE_QUALITY,
    DEFAULT_IMAGE_STYLE,
    DEFAULT_IMAGE_MODEL,
    MAX_PROMPT_LENGTH,
    IMAGE_COST_JPY,
    IMAGE_ERROR_MESSAGES,

    # G3: ディープリサーチ定数
    ResearchDepth,
    ResearchType,
    SourceType,
    ReportFormat,
    PERPLEXITY_API_URL,
    PERPLEXITY_DEFAULT_MODEL,
    PERPLEXITY_PRO_MODEL,
    RESEARCH_DEPTH_CONFIG,
    RESEARCH_TYPE_DEFAULT_SECTIONS,
    RESEARCH_COST_PER_QUERY,
    MAX_RESEARCH_QUERY_LENGTH,
    RESEARCH_ERROR_MESSAGES,

    # G5: 動画生成定数
    VideoProvider,
    VideoResolution,
    VideoDuration,
    VideoAspectRatio,
    VideoStyle,
    RUNWAY_API_URL,
    RUNWAY_GEN3_MODEL,
    RUNWAY_GEN3_TURBO_MODEL,
    DEFAULT_VIDEO_PROVIDER,
    DEFAULT_VIDEO_RESOLUTION,
    DEFAULT_VIDEO_DURATION,
    DEFAULT_VIDEO_ASPECT_RATIO,
    DEFAULT_VIDEO_STYLE,
    MAX_VIDEO_PROMPT_LENGTH,
    VIDEO_COST_JPY,
    VIDEO_ERROR_MESSAGES,
    VIDEO_STYLE_PROMPT_MODIFIERS,
    SUPPORTED_RESOLUTIONS_BY_PROVIDER,
    SUPPORTED_DURATIONS_BY_PROVIDER,
    FEATURE_FLAG_VIDEO,
)


# =============================================================================
# 例外
# =============================================================================

from .exceptions import (
    # 基底例外
    GenerationBaseException,

    # 検証エラー
    ValidationError,
    EmptyTitleError,
    TitleTooLongError,
    InvalidDocumentTypeError,
    InvalidOutputFormatError,
    TooManySectionsError,
    InsufficientContextError,

    # 生成エラー
    GenerationError,
    OutlineGenerationError,
    SectionGenerationError,
    DocumentGenerationError,

    # Google APIエラー
    GoogleAPIError,
    GoogleAuthError,
    GoogleDocsCreateError,
    GoogleDocsUpdateError,
    GoogleDriveUploadError,

    # タイムアウトエラー
    GenerationTimeoutError,
    OutlineTimeoutError,
    SectionTimeoutError,
    FullDocumentTimeoutError,

    # その他のエラー
    FeatureDisabledError,
    TemplateNotFoundError,
    LLMError,
    LLMRateLimitError,

    # デコレータ
    wrap_generation_error,
    wrap_sync_generation_error,

    # G2: 画像生成例外
    ImageGenerationError,
    ImagePromptEmptyError,
    ImagePromptTooLongError,
    ImageInvalidSizeError,
    ImageInvalidQualityError,
    ContentPolicyViolationError,
    SafetyFilterTriggeredError,
    DALLEAPIError,
    DALLERateLimitError,
    DALLETimeoutError,
    DALLEQuotaExceededError,
    ImageSaveError,
    ImageUploadError,
    ImageDailyLimitExceededError,
    ImageFeatureDisabledError,
    wrap_image_generation_error,

    # G3: ディープリサーチ例外
    ResearchError,
    ResearchQueryEmptyError,
    ResearchQueryTooLongError,
    ResearchInvalidDepthError,
    ResearchInvalidTypeError,
    ResearchNoResultsError,
    ResearchInsufficientSourcesError,
    ResearchAnalysisError,
    ResearchReportGenerationError,
    PerplexityAPIError,
    PerplexityRateLimitError,
    PerplexityTimeoutError,
    SearchAPIError,
    ResearchDailyLimitExceededError,
    ResearchConcurrentLimitExceededError,
    ResearchFeatureDisabledError,
    wrap_research_error,

    # G5: 動画生成例外
    VideoGenerationError,
    VideoPromptEmptyError,
    VideoPromptTooLongError,
    VideoInvalidResolutionError,
    VideoInvalidDurationError,
    VideoInvalidImageError,
    VideoContentPolicyViolationError,
    VideoSafetyFilterTriggeredError,
    RunwayAPIError,
    RunwayRateLimitError,
    RunwayTimeoutError,
    RunwayQuotaExceededError,
    RunwayServerError,
    VideoSaveError,
    VideoUploadError,
    VideoDailyLimitExceededError,
    VideoConcurrentLimitExceededError,
    VideoFeatureDisabledError,
    VideoGenerationCancelledError,
    wrap_video_generation_error,
)


# =============================================================================
# データモデル
# =============================================================================

from .models import (
    # 共通モデル
    GenerationMetadata,
    ReferenceDocument,

    # セクションモデル
    SectionOutline,
    SectionContent,

    # アウトラインモデル
    DocumentOutline,

    # リクエスト/結果モデル
    DocumentRequest,
    DocumentResult,

    # G2: 画像生成モデル
    ImageRequest,
    ImageResult,
    OptimizedPrompt,

    # G3: ディープリサーチモデル
    ResearchRequest,
    ResearchResult,
    ResearchPlan,
    ResearchSource,

    # G5: 動画生成モデル
    VideoRequest,
    VideoResult,
    VideoOptimizedPrompt,

    # 統合モデル
    GenerationInput,
    GenerationOutput,
)


# =============================================================================
# 基底クラス
# =============================================================================

from .base import (
    LLMClient,
    BaseGenerator,
)


# =============================================================================
# ジェネレーター
# =============================================================================

from .document_generator import (
    DocumentGenerator,
    create_document_generator,
)


# =============================================================================
# Google APIクライアント
# =============================================================================

from .google_docs_client import (
    GoogleDocsClient,
    create_google_docs_client,
)

from .google_sheets_client import (
    GoogleSheetsClient,
    GoogleSheetsError,
    GoogleSheetsCreateError,
    GoogleSheetsReadError,
    GoogleSheetsUpdateError,
    create_google_sheets_client,
)

from .google_slides_client import (
    GoogleSlidesClient,
    GoogleSlidesError,
    GoogleSlidesCreateError,
    GoogleSlidesReadError,
    GoogleSlidesUpdateError,
    create_google_slides_client,
    # レイアウト定数
    LAYOUT_BLANK,
    LAYOUT_TITLE,
    LAYOUT_TITLE_AND_BODY,
    LAYOUT_SECTION_HEADER,
    LAYOUT_TITLE_ONLY,
    LAYOUT_ONE_COLUMN_TEXT,
    LAYOUT_TITLE_AND_TWO_COLUMNS,
    LAYOUT_BIG_NUMBER,
)


# =============================================================================
# G2: 画像ジェネレーター
# =============================================================================

from .image_generator import (
    ImageGenerator,
    create_image_generator,
)


# =============================================================================
# G2: DALL-E クライアント
# =============================================================================

from .dalle_client import (
    DALLEClient,
    create_dalle_client,
)


# =============================================================================
# G3: リサーチエンジン
# =============================================================================

from .research_engine import (
    ResearchEngine,
    PerplexityClient,
    create_research_engine,
    create_perplexity_client,
)


# =============================================================================
# G5: 動画ジェネレーター
# =============================================================================

from .video_generator import (
    VideoGenerator,
    create_video_generator,
)


# =============================================================================
# G5: Runway クライアント
# =============================================================================

from .runway_client import (
    RunwayClient,
    create_runway_client,
)


# =============================================================================
# 公開API
# =============================================================================

__all__ = [
    # バージョン
    "__version__",

    # 定数 - 列挙型
    "GenerationType",
    "DocumentType",
    "GenerationStatus",
    "OutputFormat",
    "SectionType",
    "ConfirmationLevel",
    "QualityLevel",
    "ToneStyle",

    # 定数 - サポートフォーマット
    "SUPPORTED_DOCUMENT_TYPES",
    "SUPPORTED_OUTPUT_FORMATS",

    # 定数 - サイズ制限
    "MAX_DOCUMENT_SECTIONS",
    "MAX_SECTION_LENGTH",
    "MAX_DOCUMENT_LENGTH",
    "MAX_TITLE_LENGTH",
    "MAX_OUTLINE_ITEMS",
    "MAX_REQUEST_CONTEXT_LENGTH",
    "MAX_REFERENCE_DOCUMENTS",
    "MAX_TEMPLATE_SIZE_BYTES",

    # 定数 - タイムアウト
    "OUTLINE_GENERATION_TIMEOUT",
    "SECTION_GENERATION_TIMEOUT",
    "FULL_DOCUMENT_GENERATION_TIMEOUT",
    "GOOGLE_DOCS_API_TIMEOUT",
    "INFO_GATHERING_TIMEOUT",

    # 定数 - LLM設定
    "DEFAULT_GENERATION_MODEL",
    "HIGH_QUALITY_MODEL",
    "FAST_MODEL",
    "TEMPERATURE_SETTINGS",

    # 定数 - Google API設定
    "GOOGLE_DOCS_API_VERSION",
    "GOOGLE_DOCS_SCOPES",
    "GOOGLE_DRIVE_API_VERSION",
    "GOOGLE_DRIVE_SCOPES",

    # 定数 - Feature Flag
    "FEATURE_FLAG_NAME",
    "FEATURE_FLAG_DOCUMENT",
    "FEATURE_FLAG_IMAGE",
    "FEATURE_FLAG_RESEARCH",

    # 定数 - テンプレート設定
    "DEFAULT_TEMPLATE_ID",
    "DOCUMENT_TYPE_DEFAULT_SECTIONS",

    # 定数 - プロンプトテンプレート
    "OUTLINE_GENERATION_PROMPT",
    "SECTION_GENERATION_PROMPT",

    # 定数 - エラーメッセージ
    "ERROR_MESSAGES",

    # 定数 - 文書タイプキーワード
    "DOCUMENT_TYPE_KEYWORDS",

    # 定数 - コスト設定
    "COST_PER_1K_TOKENS",
    "OUTPUT_COST_MULTIPLIER",

    # G3: ディープリサーチ定数
    "ResearchDepth",
    "ResearchType",
    "SourceType",
    "ReportFormat",
    "PERPLEXITY_API_URL",
    "PERPLEXITY_DEFAULT_MODEL",
    "PERPLEXITY_PRO_MODEL",
    "RESEARCH_DEPTH_CONFIG",
    "RESEARCH_TYPE_DEFAULT_SECTIONS",
    "RESEARCH_COST_PER_QUERY",
    "MAX_RESEARCH_QUERY_LENGTH",
    "RESEARCH_ERROR_MESSAGES",

    # G5: 動画生成定数
    "VideoProvider",
    "VideoResolution",
    "VideoDuration",
    "VideoAspectRatio",
    "VideoStyle",
    "RUNWAY_API_URL",
    "RUNWAY_GEN3_MODEL",
    "RUNWAY_GEN3_TURBO_MODEL",
    "DEFAULT_VIDEO_PROVIDER",
    "DEFAULT_VIDEO_RESOLUTION",
    "DEFAULT_VIDEO_DURATION",
    "DEFAULT_VIDEO_ASPECT_RATIO",
    "DEFAULT_VIDEO_STYLE",
    "MAX_VIDEO_PROMPT_LENGTH",
    "VIDEO_COST_JPY",
    "VIDEO_ERROR_MESSAGES",
    "VIDEO_STYLE_PROMPT_MODIFIERS",
    "SUPPORTED_RESOLUTIONS_BY_PROVIDER",
    "SUPPORTED_DURATIONS_BY_PROVIDER",
    "FEATURE_FLAG_VIDEO",

    # 例外 - 基底
    "GenerationBaseException",

    # 例外 - 検証
    "ValidationError",
    "EmptyTitleError",
    "TitleTooLongError",
    "InvalidDocumentTypeError",
    "InvalidOutputFormatError",
    "TooManySectionsError",
    "InsufficientContextError",

    # 例外 - 生成
    "GenerationError",
    "OutlineGenerationError",
    "SectionGenerationError",
    "DocumentGenerationError",

    # 例外 - Google API
    "GoogleAPIError",
    "GoogleAuthError",
    "GoogleDocsCreateError",
    "GoogleDocsUpdateError",
    "GoogleDriveUploadError",

    # 例外 - タイムアウト
    "GenerationTimeoutError",
    "OutlineTimeoutError",
    "SectionTimeoutError",
    "FullDocumentTimeoutError",

    # 例外 - その他
    "FeatureDisabledError",
    "TemplateNotFoundError",
    "LLMError",
    "LLMRateLimitError",

    # 例外 - デコレータ
    "wrap_generation_error",
    "wrap_sync_generation_error",

    # G2: 画像生成例外
    "ImageGenerationError",
    "ImagePromptEmptyError",
    "ImagePromptTooLongError",
    "ImageInvalidSizeError",
    "ImageInvalidQualityError",
    "ContentPolicyViolationError",
    "SafetyFilterTriggeredError",
    "DALLEAPIError",
    "DALLERateLimitError",
    "DALLETimeoutError",
    "DALLEQuotaExceededError",
    "ImageSaveError",
    "ImageUploadError",
    "ImageDailyLimitExceededError",
    "ImageFeatureDisabledError",
    "wrap_image_generation_error",

    # G3: ディープリサーチ例外
    "ResearchError",
    "ResearchQueryEmptyError",
    "ResearchQueryTooLongError",
    "ResearchInvalidDepthError",
    "ResearchInvalidTypeError",
    "ResearchNoResultsError",
    "ResearchInsufficientSourcesError",
    "ResearchAnalysisError",
    "ResearchReportGenerationError",
    "PerplexityAPIError",
    "PerplexityRateLimitError",
    "PerplexityTimeoutError",
    "SearchAPIError",
    "ResearchDailyLimitExceededError",
    "ResearchConcurrentLimitExceededError",
    "ResearchFeatureDisabledError",
    "wrap_research_error",

    # G5: 動画生成例外
    "VideoGenerationError",
    "VideoPromptEmptyError",
    "VideoPromptTooLongError",
    "VideoInvalidResolutionError",
    "VideoInvalidDurationError",
    "VideoInvalidImageError",
    "VideoContentPolicyViolationError",
    "VideoSafetyFilterTriggeredError",
    "RunwayAPIError",
    "RunwayRateLimitError",
    "RunwayTimeoutError",
    "RunwayQuotaExceededError",
    "RunwayServerError",
    "VideoSaveError",
    "VideoUploadError",
    "VideoDailyLimitExceededError",
    "VideoConcurrentLimitExceededError",
    "VideoFeatureDisabledError",
    "VideoGenerationCancelledError",
    "wrap_video_generation_error",

    # モデル - 共通
    "GenerationMetadata",
    "ReferenceDocument",

    # モデル - セクション
    "SectionOutline",
    "SectionContent",

    # モデル - アウトライン
    "DocumentOutline",

    # モデル - リクエスト/結果
    "DocumentRequest",
    "DocumentResult",

    # G2: 画像生成モデル
    "ImageRequest",
    "ImageResult",
    "OptimizedPrompt",

    # G3: ディープリサーチモデル
    "ResearchRequest",
    "ResearchResult",
    "ResearchPlan",
    "ResearchSource",

    # G5: 動画生成モデル
    "VideoRequest",
    "VideoResult",
    "VideoOptimizedPrompt",

    # モデル - 統合
    "GenerationInput",
    "GenerationOutput",

    # 基底クラス
    "LLMClient",
    "BaseGenerator",

    # ジェネレーター
    "DocumentGenerator",
    "create_document_generator",

    # G2: 画像ジェネレーター
    "ImageGenerator",
    "create_image_generator",

    # Google APIクライアント
    "GoogleDocsClient",
    "create_google_docs_client",
    "GoogleSheetsClient",
    "GoogleSheetsError",
    "GoogleSheetsCreateError",
    "GoogleSheetsReadError",
    "GoogleSheetsUpdateError",
    "create_google_sheets_client",
    "GoogleSlidesClient",
    "GoogleSlidesError",
    "GoogleSlidesCreateError",
    "GoogleSlidesReadError",
    "GoogleSlidesUpdateError",
    "create_google_slides_client",
    # レイアウト定数
    "LAYOUT_BLANK",
    "LAYOUT_TITLE",
    "LAYOUT_TITLE_AND_BODY",
    "LAYOUT_SECTION_HEADER",
    "LAYOUT_TITLE_ONLY",
    "LAYOUT_ONE_COLUMN_TEXT",
    "LAYOUT_TITLE_AND_TWO_COLUMNS",
    "LAYOUT_BIG_NUMBER",

    # G2: DALL-E クライアント
    "DALLEClient",
    "create_dalle_client",

    # G3: リサーチエンジン
    "ResearchEngine",
    "PerplexityClient",
    "create_research_engine",
    "create_perplexity_client",

    # G5: 動画ジェネレーター
    "VideoGenerator",
    "create_video_generator",

    # G5: Runway クライアント
    "RunwayClient",
    "create_runway_client",
]
