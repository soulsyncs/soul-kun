# lib/capabilities/generation/exceptions.py
"""
Phase G1: 文書生成能力 - 例外定義

このモジュールは、文書生成に関する例外クラスを定義します。

設計書: docs/20_next_generation_capabilities.md セクション6
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from typing import Optional, Dict, Any, List
from functools import wraps

from .constants import GenerationType, ERROR_MESSAGES, IMAGE_ERROR_MESSAGES, RESEARCH_ERROR_MESSAGES


# =============================================================================
# 基底例外
# =============================================================================


class GenerationBaseException(Exception):
    """
    Generation機能の基底例外

    全ての生成関連例外の親クラス。
    統一的なエラー情報とユーザーフレンドリーなメッセージを提供。
    """

    def __init__(
        self,
        message: str,
        error_code: str = "GENERATION_ERROR",
        generation_type: GenerationType = GenerationType.DOCUMENT,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        """
        初期化

        Args:
            message: エラーメッセージ
            error_code: エラーコード（ログ・追跡用）
            generation_type: 生成タイプ
            details: 追加詳細情報
            original_error: 元の例外（ラップ時）
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.generation_type = generation_type
        self.details = details or {}
        self.original_error = original_error

    def to_user_message(self) -> str:
        """
        ユーザーフレンドリーなメッセージを生成

        Returns:
            日本語のエラーメッセージ
        """
        return f"生成エラー: {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        """
        辞書形式に変換（ログ・API応答用）

        Returns:
            エラー情報の辞書
        """
        return {
            "error_code": self.error_code,
            "message": self.message,
            "generation_type": self.generation_type.value,
            "details": self.details,
            "has_original_error": self.original_error is not None,
        }


# =============================================================================
# 検証エラー
# =============================================================================


class ValidationError(GenerationBaseException):
    """入力検証エラー"""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            details={
                "field": field,
                "value": str(value)[:100] if value else None,
                **(details or {}),
            },
        )
        self.field = field
        self.value = value


class EmptyTitleError(ValidationError):
    """タイトル未指定エラー"""

    def __init__(self):
        super().__init__(
            message=ERROR_MESSAGES["EMPTY_TITLE"],
            field="title",
        )
        self.error_code = "EMPTY_TITLE"

    def to_user_message(self) -> str:
        return "タイトルを指定してください。"


class TitleTooLongError(ValidationError):
    """タイトル長超過エラー"""

    def __init__(self, actual_length: int, max_length: int):
        super().__init__(
            message=ERROR_MESSAGES["TITLE_TOO_LONG"].format(max=max_length),
            field="title",
            value=f"length={actual_length}",
            details={
                "actual_length": actual_length,
                "max_length": max_length,
            },
        )
        self.error_code = "TITLE_TOO_LONG"
        self.actual_length = actual_length
        self.max_length = max_length

    def to_user_message(self) -> str:
        return f"タイトルが長すぎます（{self.actual_length}文字）。{self.max_length}文字以内にしてください。"


class InvalidDocumentTypeError(ValidationError):
    """無効な文書タイプエラー"""

    def __init__(self, document_type: str):
        super().__init__(
            message=ERROR_MESSAGES["INVALID_DOCUMENT_TYPE"].format(type=document_type),
            field="document_type",
            value=document_type,
        )
        self.error_code = "INVALID_DOCUMENT_TYPE"
        self.document_type = document_type

    def to_user_message(self) -> str:
        return f"「{self.document_type}」は対応していない文書タイプです。"


class InvalidOutputFormatError(ValidationError):
    """無効な出力フォーマットエラー"""

    def __init__(self, output_format: str):
        super().__init__(
            message=ERROR_MESSAGES["INVALID_OUTPUT_FORMAT"].format(format=output_format),
            field="output_format",
            value=output_format,
        )
        self.error_code = "INVALID_OUTPUT_FORMAT"
        self.output_format = output_format

    def to_user_message(self) -> str:
        return f"「{self.output_format}」は対応していない出力フォーマットです。"


class TooManySectionsError(ValidationError):
    """セクション数超過エラー"""

    def __init__(self, actual_count: int, max_count: int):
        super().__init__(
            message=ERROR_MESSAGES["TOO_MANY_SECTIONS"].format(max=max_count),
            field="sections",
            value=f"count={actual_count}",
            details={
                "actual_count": actual_count,
                "max_count": max_count,
            },
        )
        self.error_code = "TOO_MANY_SECTIONS"
        self.actual_count = actual_count
        self.max_count = max_count

    def to_user_message(self) -> str:
        return f"セクション数が多すぎます（{self.actual_count}件）。{self.max_count}件以内にしてください。"


class InsufficientContextError(ValidationError):
    """コンテキスト不足エラー"""

    def __init__(self, missing_fields: Optional[list] = None):
        super().__init__(
            message=ERROR_MESSAGES["INSUFFICIENT_CONTEXT"],
            field="context",
            details={"missing_fields": missing_fields or []},
        )
        self.error_code = "INSUFFICIENT_CONTEXT"
        self.missing_fields = missing_fields or []

    def to_user_message(self) -> str:
        if self.missing_fields:
            fields = "、".join(self.missing_fields)
            return f"文書を作成するための情報が不足しています（{fields}）。"
        return "文書を作成するための情報が不足しています。もう少し詳しく教えてください。"


# =============================================================================
# 生成エラー
# =============================================================================


class GenerationError(GenerationBaseException):
    """生成処理エラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "GENERATION_ERROR",
        generation_type: GenerationType = GenerationType.DOCUMENT,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            generation_type=generation_type,
            details=details,
            original_error=original_error,
        )


class OutlineGenerationError(GenerationError):
    """アウトライン生成エラー"""

    def __init__(
        self,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message or ERROR_MESSAGES["OUTLINE_GENERATION_FAILED"],
            error_code="OUTLINE_GENERATION_FAILED",
            details=details,
            original_error=original_error,
        )

    def to_user_message(self) -> str:
        return "構成案の作成に失敗しました。もう一度お試しください。"


class SectionGenerationError(GenerationError):
    """セクション生成エラー"""

    def __init__(
        self,
        section_title: str,
        section_index: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=ERROR_MESSAGES["SECTION_GENERATION_FAILED"].format(section=section_title),
            error_code="SECTION_GENERATION_FAILED",
            details={
                "section_title": section_title,
                "section_index": section_index,
                **(details or {}),
            },
            original_error=original_error,
        )
        self.section_title = section_title
        self.section_index = section_index

    def to_user_message(self) -> str:
        return f"「{self.section_title}」セクションの作成に失敗しました。"


class DocumentGenerationError(GenerationError):
    """文書生成エラー"""

    def __init__(
        self,
        message: Optional[str] = None,
        document_title: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message or ERROR_MESSAGES["DOCUMENT_GENERATION_FAILED"],
            error_code="DOCUMENT_GENERATION_FAILED",
            details={
                "document_title": document_title,
                **(details or {}),
            },
            original_error=original_error,
        )
        self.document_title = document_title

    def to_user_message(self) -> str:
        if self.document_title:
            return f"「{self.document_title}」の作成に失敗しました。"
        return "文書の作成に失敗しました。"


# =============================================================================
# Google APIエラー
# =============================================================================


class GoogleAPIError(GenerationBaseException):
    """Google API エラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "GOOGLE_API_ERROR",
        api_name: str = "Google API",
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            details={"api_name": api_name, **(details or {})},
            original_error=original_error,
        )
        self.api_name = api_name


class GoogleAuthError(GoogleAPIError):
    """Google認証エラー"""

    def __init__(
        self,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=ERROR_MESSAGES["GOOGLE_AUTH_FAILED"],
            error_code="GOOGLE_AUTH_FAILED",
            api_name="Google Auth",
            details=details,
            original_error=original_error,
        )

    def to_user_message(self) -> str:
        return "Googleサービスへの接続に失敗しました。しばらく待ってから再試行してください。"


class GoogleDocsCreateError(GoogleAPIError):
    """Google Docs作成エラー"""

    def __init__(
        self,
        document_title: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=ERROR_MESSAGES["GOOGLE_DOCS_CREATE_FAILED"],
            error_code="GOOGLE_DOCS_CREATE_FAILED",
            api_name="Google Docs",
            details={"document_title": document_title, **(details or {})},
            original_error=original_error,
        )
        self.document_title = document_title

    def to_user_message(self) -> str:
        return "Google Docsの作成に失敗しました。"


class GoogleDocsUpdateError(GoogleAPIError):
    """Google Docs更新エラー"""

    def __init__(
        self,
        document_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=ERROR_MESSAGES["GOOGLE_DOCS_UPDATE_FAILED"],
            error_code="GOOGLE_DOCS_UPDATE_FAILED",
            api_name="Google Docs",
            details={"document_id": document_id, **(details or {})},
            original_error=original_error,
        )
        self.document_id = document_id

    def to_user_message(self) -> str:
        return "文書の更新に失敗しました。"


class GoogleDriveUploadError(GoogleAPIError):
    """Google Driveアップロードエラー"""

    def __init__(
        self,
        file_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=ERROR_MESSAGES["GOOGLE_DRIVE_UPLOAD_FAILED"],
            error_code="GOOGLE_DRIVE_UPLOAD_FAILED",
            api_name="Google Drive",
            details={"file_name": file_name, **(details or {})},
            original_error=original_error,
        )
        self.file_name = file_name

    def to_user_message(self) -> str:
        return "ファイルのアップロードに失敗しました。"


# =============================================================================
# タイムアウトエラー
# =============================================================================


class GenerationTimeoutError(GenerationBaseException):
    """生成タイムアウトエラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "GENERATION_TIMEOUT",
        timeout_seconds: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            details={"timeout_seconds": timeout_seconds, **(details or {})},
        )
        self.timeout_seconds = timeout_seconds


class OutlineTimeoutError(GenerationTimeoutError):
    """アウトライン生成タイムアウト"""

    def __init__(self, timeout_seconds: int):
        super().__init__(
            message=ERROR_MESSAGES["OUTLINE_TIMEOUT"],
            error_code="OUTLINE_TIMEOUT",
            timeout_seconds=timeout_seconds,
        )

    def to_user_message(self) -> str:
        return "構成案の作成に時間がかかりすぎています。もう一度お試しください。"


class SectionTimeoutError(GenerationTimeoutError):
    """セクション生成タイムアウト"""

    def __init__(self, timeout_seconds: int, section_title: Optional[str] = None):
        super().__init__(
            message=ERROR_MESSAGES["SECTION_TIMEOUT"],
            error_code="SECTION_TIMEOUT",
            timeout_seconds=timeout_seconds,
            details={"section_title": section_title},
        )
        self.section_title = section_title

    def to_user_message(self) -> str:
        if self.section_title:
            return f"「{self.section_title}」の作成に時間がかかりすぎています。"
        return "セクションの作成に時間がかかりすぎています。"


class FullDocumentTimeoutError(GenerationTimeoutError):
    """全文書生成タイムアウト"""

    def __init__(self, timeout_seconds: int):
        super().__init__(
            message=ERROR_MESSAGES["FULL_DOCUMENT_TIMEOUT"],
            error_code="FULL_DOCUMENT_TIMEOUT",
            timeout_seconds=timeout_seconds,
        )

    def to_user_message(self) -> str:
        return "文書の作成に時間がかかりすぎています。セクションを減らすか、もう一度お試しください。"


# =============================================================================
# その他のエラー
# =============================================================================


class FeatureDisabledError(GenerationBaseException):
    """機能無効エラー"""

    def __init__(self, feature_name: str = "文書生成"):
        super().__init__(
            message=ERROR_MESSAGES["FEATURE_DISABLED"],
            error_code="FEATURE_DISABLED",
            details={"feature_name": feature_name},
        )
        self.feature_name = feature_name

    def to_user_message(self) -> str:
        return f"{self.feature_name}機能は現在ご利用いただけません。"


class TemplateNotFoundError(GenerationBaseException):
    """テンプレート未発見エラー"""

    def __init__(self, template_id: str):
        super().__init__(
            message=ERROR_MESSAGES["TEMPLATE_NOT_FOUND"].format(template_id=template_id),
            error_code="TEMPLATE_NOT_FOUND",
            details={"template_id": template_id},
        )
        self.template_id = template_id

    def to_user_message(self) -> str:
        return "指定されたテンプレートが見つかりません。"


class LLMError(GenerationBaseException):
    """LLM呼び出しエラー"""

    def __init__(
        self,
        message: str,
        model: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code="LLM_ERROR",
            details={"model": model, **(details or {})},
            original_error=original_error,
        )
        self.model = model

    def to_user_message(self) -> str:
        return "AI処理中にエラーが発生しました。もう一度お試しください。"


class LLMRateLimitError(LLMError):
    """LLMレート制限エラー"""

    def __init__(
        self,
        model: Optional[str] = None,
        retry_after: Optional[int] = None,
    ):
        super().__init__(
            message=f"LLM rate limit exceeded{f' for {model}' if model else ''}",
            model=model,
            details={"retry_after": retry_after},
        )
        self.error_code = "LLM_RATE_LIMIT"
        self.retry_after = retry_after

    def to_user_message(self) -> str:
        if self.retry_after:
            return f"AIが混み合っています。{self.retry_after}秒後に再試行してください。"
        return "AIが混み合っています。しばらく待ってから再試行してください。"


# =============================================================================
# デコレータ
# =============================================================================


def wrap_generation_error(func):
    """
    非同期関数の例外をGeneration例外にラップするデコレータ

    使用例:
        @wrap_generation_error
        async def generate_document():
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except GenerationBaseException:
            raise
        except Exception as e:
            raise GenerationError(
                message=f"Unexpected error: {str(e)}",
                error_code="UNEXPECTED_ERROR",
                original_error=e,
            )
    return wrapper


def wrap_sync_generation_error(func):
    """
    同期関数の例外をGeneration例外にラップするデコレータ

    使用例:
        @wrap_sync_generation_error
        def validate_request():
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except GenerationBaseException:
            raise
        except Exception as e:
            raise GenerationError(
                message=f"Unexpected error: {str(e)}",
                error_code="UNEXPECTED_ERROR",
                original_error=e,
            )
    return wrapper


# =============================================================================
# Phase G2: 画像生成エラー
# =============================================================================


class ImageGenerationError(GenerationBaseException):
    """画像生成エラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "IMAGE_GENERATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            generation_type=GenerationType.IMAGE,
            details=details,
            original_error=original_error,
        )

    def to_user_message(self) -> str:
        return f"画像生成エラー: {self.message}"


class ImagePromptEmptyError(ImageGenerationError):
    """プロンプト空エラー"""

    def __init__(self):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["EMPTY_PROMPT"],
            error_code="EMPTY_PROMPT",
        )

    def to_user_message(self) -> str:
        return "どんな画像を作りたいか教えてください。"


class ImagePromptTooLongError(ImageGenerationError):
    """プロンプト長すぎエラー"""

    def __init__(self, actual_length: int, max_length: int):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["PROMPT_TOO_LONG"].format(max=max_length),
            error_code="PROMPT_TOO_LONG",
            details={"actual_length": actual_length, "max_length": max_length},
        )
        self.actual_length = actual_length
        self.max_length = max_length

    def to_user_message(self) -> str:
        return f"プロンプトが長すぎます（{self.actual_length}文字）。{self.max_length}文字以内にしてください。"


class ImageInvalidSizeError(ImageGenerationError):
    """無効なサイズエラー"""

    def __init__(self, size: str, provider: str, supported_sizes: list):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["SIZE_NOT_SUPPORTED_BY_PROVIDER"].format(
                provider=provider, size=size
            ),
            error_code="INVALID_SIZE",
            details={"size": size, "provider": provider, "supported_sizes": supported_sizes},
        )
        self.size = size
        self.provider = provider
        self.supported_sizes = supported_sizes

    def to_user_message(self) -> str:
        return f"サイズ「{self.size}」は{self.provider}でサポートされていません。"


class ImageInvalidQualityError(ImageGenerationError):
    """無効な品質エラー"""

    def __init__(self, quality: str, provider: str):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["INVALID_QUALITY"].format(quality=quality),
            error_code="INVALID_QUALITY",
            details={"quality": quality, "provider": provider},
        )
        self.quality = quality
        self.provider = provider

    def to_user_message(self) -> str:
        return f"品質「{self.quality}」は{self.provider}でサポートされていません。"


class ContentPolicyViolationError(ImageGenerationError):
    """コンテンツポリシー違反エラー"""

    def __init__(self, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["CONTENT_POLICY_VIOLATION"],
            error_code="CONTENT_POLICY_VIOLATION",
            details=details,
        )

    def to_user_message(self) -> str:
        return "申し訳ありませんが、そのような画像は生成できません。別の内容でお試しください。"


class SafetyFilterTriggeredError(ImageGenerationError):
    """安全フィルター発動エラー"""

    def __init__(self, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["SAFETY_FILTER_TRIGGERED"],
            error_code="SAFETY_FILTER_TRIGGERED",
            details=details,
        )

    def to_user_message(self) -> str:
        return "安全フィルターが作動しました。プロンプトを修正してください。"


# -----------------------------------------------------------------------------
# DALL-E API エラー
# -----------------------------------------------------------------------------


class DALLEAPIError(ImageGenerationError):
    """DALL-E API エラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "DALLE_API_ERROR",
        model: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            details={"model": model, **(details or {})},
            original_error=original_error,
        )
        self.model = model

    def to_user_message(self) -> str:
        return "画像生成サービスでエラーが発生しました。もう一度お試しください。"


class DALLERateLimitError(DALLEAPIError):
    """DALL-E レート制限エラー"""

    def __init__(
        self,
        model: Optional[str] = None,
        retry_after: Optional[int] = None,
    ):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["DALLE_RATE_LIMIT"],
            error_code="DALLE_RATE_LIMIT",
            model=model,
            details={"retry_after": retry_after},
        )
        self.retry_after = retry_after

    def to_user_message(self) -> str:
        if self.retry_after:
            return f"画像生成サービスが混み合っています。{self.retry_after}秒後に再試行してください。"
        return "画像生成サービスが混み合っています。しばらく待ってから再試行してください。"


class DALLETimeoutError(DALLEAPIError):
    """DALL-E タイムアウトエラー"""

    def __init__(
        self,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["DALLE_TIMEOUT"],
            error_code="DALLE_TIMEOUT",
            model=model,
            details={"timeout_seconds": timeout_seconds},
        )
        self.timeout_seconds = timeout_seconds

    def to_user_message(self) -> str:
        return "画像生成がタイムアウトしました。もう一度お試しください。"


class DALLEQuotaExceededError(DALLEAPIError):
    """DALL-E クォータ超過エラー"""

    def __init__(self, model: Optional[str] = None):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["DALLE_QUOTA_EXCEEDED"],
            error_code="DALLE_QUOTA_EXCEEDED",
            model=model,
        )

    def to_user_message(self) -> str:
        return "画像生成の利用上限に達しました。管理者にお問い合わせください。"


# -----------------------------------------------------------------------------
# 画像保存エラー
# -----------------------------------------------------------------------------


class ImageSaveError(ImageGenerationError):
    """画像保存エラー"""

    def __init__(
        self,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["SAVE_FAILED"],
            error_code="IMAGE_SAVE_FAILED",
            details=details,
            original_error=original_error,
        )

    def to_user_message(self) -> str:
        return "画像の保存に失敗しました。"


class ImageUploadError(ImageGenerationError):
    """画像アップロードエラー"""

    def __init__(
        self,
        destination: str = "Google Drive",
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["UPLOAD_FAILED"],
            error_code="IMAGE_UPLOAD_FAILED",
            details={"destination": destination, **(details or {})},
            original_error=original_error,
        )
        self.destination = destination

    def to_user_message(self) -> str:
        return f"{self.destination}へのアップロードに失敗しました。"


class ImageDailyLimitExceededError(ImageGenerationError):
    """日次上限超過エラー"""

    def __init__(self, limit: int):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["DAILY_LIMIT_EXCEEDED"].format(limit=limit),
            error_code="DAILY_LIMIT_EXCEEDED",
            details={"limit": limit},
        )
        self.limit = limit

    def to_user_message(self) -> str:
        return f"本日の画像生成上限（{self.limit}枚）に達しました。明日また試してください。"


class ImageFeatureDisabledError(ImageGenerationError):
    """画像生成機能無効エラー"""

    def __init__(self):
        super().__init__(
            message=IMAGE_ERROR_MESSAGES["FEATURE_DISABLED"],
            error_code="IMAGE_FEATURE_DISABLED",
        )

    def to_user_message(self) -> str:
        return "画像生成機能は現在ご利用いただけません。"


def wrap_image_generation_error(func):
    """
    非同期関数の例外を画像生成例外にラップするデコレータ

    使用例:
        @wrap_image_generation_error
        async def generate_image():
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ImageGenerationError:
            raise
        except GenerationBaseException:
            raise
        except Exception as e:
            raise ImageGenerationError(
                message=f"Unexpected error: {str(e)}",
                error_code="UNEXPECTED_IMAGE_ERROR",
                original_error=e,
            )
    return wrapper


# =============================================================================
# Phase G3: ディープリサーチエラー
# =============================================================================


class ResearchError(GenerationBaseException):
    """リサーチエラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "RESEARCH_ERROR",
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            generation_type=GenerationType.RESEARCH,
            details=details,
            original_error=original_error,
        )

    def to_user_message(self) -> str:
        return f"リサーチエラー: {self.message}"


class ResearchQueryEmptyError(ResearchError):
    """クエリ空エラー"""

    def __init__(self):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["EMPTY_QUERY"],
            error_code="EMPTY_QUERY",
        )

    def to_user_message(self) -> str:
        return "何について調べたいか教えてください。"


class ResearchQueryTooLongError(ResearchError):
    """クエリ長すぎエラー"""

    def __init__(self, actual_length: int, max_length: int):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["QUERY_TOO_LONG"].format(max=max_length),
            error_code="QUERY_TOO_LONG",
            details={"actual_length": actual_length, "max_length": max_length},
        )
        self.actual_length = actual_length
        self.max_length = max_length

    def to_user_message(self) -> str:
        return f"クエリが長すぎます（{self.actual_length}文字）。{self.max_length}文字以内にしてください。"


class ResearchInvalidDepthError(ResearchError):
    """無効なリサーチ深度エラー"""

    def __init__(self, depth: str):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["INVALID_DEPTH"].format(depth=depth),
            error_code="INVALID_DEPTH",
            details={"depth": depth},
        )
        self.depth = depth

    def to_user_message(self) -> str:
        return f"リサーチ深度「{self.depth}」はサポートされていません。"


class ResearchInvalidTypeError(ResearchError):
    """無効なリサーチタイプエラー"""

    def __init__(self, research_type: str):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["INVALID_TYPE"].format(type=research_type),
            error_code="INVALID_TYPE",
            details={"research_type": research_type},
        )
        self.research_type = research_type

    def to_user_message(self) -> str:
        return f"リサーチタイプ「{self.research_type}」はサポートされていません。"


class ResearchNoResultsError(ResearchError):
    """検索結果なしエラー"""

    def __init__(self, query: str):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["NO_RESULTS"],
            error_code="NO_RESULTS",
            details={"query": query},
        )
        self.query = query

    def to_user_message(self) -> str:
        return "該当する情報が見つかりませんでした。検索キーワードを変えてお試しください。"


class ResearchInsufficientSourcesError(ResearchError):
    """情報源不足エラー"""

    def __init__(self, found_count: int, required_count: int):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["INSUFFICIENT_SOURCES"],
            error_code="INSUFFICIENT_SOURCES",
            details={"found_count": found_count, "required_count": required_count},
        )
        self.found_count = found_count
        self.required_count = required_count

    def to_user_message(self) -> str:
        return "十分な情報源が見つかりませんでした。検索条件を広げてお試しください。"


class ResearchAnalysisError(ResearchError):
    """分析エラー"""

    def __init__(
        self,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["ANALYSIS_FAILED"],
            error_code="ANALYSIS_FAILED",
            details=details,
            original_error=original_error,
        )

    def to_user_message(self) -> str:
        return "情報の分析に失敗しました。もう一度お試しください。"


class ResearchReportGenerationError(ResearchError):
    """レポート生成エラー"""

    def __init__(
        self,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["REPORT_GENERATION_FAILED"],
            error_code="REPORT_GENERATION_FAILED",
            details=details,
            original_error=original_error,
        )

    def to_user_message(self) -> str:
        return "レポートの生成に失敗しました。もう一度お試しください。"


# -----------------------------------------------------------------------------
# Perplexity API エラー
# -----------------------------------------------------------------------------


class PerplexityAPIError(ResearchError):
    """Perplexity API エラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "PERPLEXITY_API_ERROR",
        model: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            details={"model": model, **(details or {})},
            original_error=original_error,
        )
        self.model = model

    def to_user_message(self) -> str:
        return "リサーチサービスでエラーが発生しました。もう一度お試しください。"


class PerplexityRateLimitError(PerplexityAPIError):
    """Perplexity レート制限エラー"""

    def __init__(
        self,
        model: Optional[str] = None,
        retry_after: Optional[int] = None,
    ):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["PERPLEXITY_RATE_LIMIT"],
            error_code="PERPLEXITY_RATE_LIMIT",
            model=model,
            details={"retry_after": retry_after},
        )
        self.retry_after = retry_after

    def to_user_message(self) -> str:
        if self.retry_after:
            return f"リサーチサービスが混み合っています。{self.retry_after}秒後に再試行してください。"
        return "リサーチサービスが混み合っています。しばらく待ってから再試行してください。"


class PerplexityTimeoutError(PerplexityAPIError):
    """Perplexity タイムアウトエラー"""

    def __init__(
        self,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["PERPLEXITY_TIMEOUT"],
            error_code="PERPLEXITY_TIMEOUT",
            model=model,
            details={"timeout_seconds": timeout_seconds},
        )
        self.timeout_seconds = timeout_seconds

    def to_user_message(self) -> str:
        return "リサーチがタイムアウトしました。もう一度お試しください。"


class SearchAPIError(ResearchError):
    """検索API エラー"""

    def __init__(
        self,
        api_name: str = "Search API",
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["SEARCH_API_ERROR"].format(error=api_name),
            error_code="SEARCH_API_ERROR",
            details={"api_name": api_name, **(details or {})},
            original_error=original_error,
        )
        self.api_name = api_name

    def to_user_message(self) -> str:
        return "検索サービスでエラーが発生しました。もう一度お試しください。"


# -----------------------------------------------------------------------------
# リサーチ制限エラー
# -----------------------------------------------------------------------------


class ResearchDailyLimitExceededError(ResearchError):
    """日次上限超過エラー"""

    def __init__(self, limit: int):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["DAILY_LIMIT_EXCEEDED"].format(limit=limit),
            error_code="DAILY_LIMIT_EXCEEDED",
            details={"limit": limit},
        )
        self.limit = limit

    def to_user_message(self) -> str:
        return f"本日のリサーチ上限（{self.limit}回）に達しました。明日また試してください。"


class ResearchConcurrentLimitExceededError(ResearchError):
    """同時実行上限超過エラー"""

    def __init__(self, limit: int):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["CONCURRENT_LIMIT_EXCEEDED"],
            error_code="CONCURRENT_LIMIT_EXCEEDED",
            details={"limit": limit},
        )
        self.limit = limit

    def to_user_message(self) -> str:
        return "現在、複数のリサーチが実行中です。しばらく待ってから再試行してください。"


class ResearchFeatureDisabledError(ResearchError):
    """リサーチ機能無効エラー"""

    def __init__(self):
        super().__init__(
            message=RESEARCH_ERROR_MESSAGES["FEATURE_DISABLED"],
            error_code="RESEARCH_FEATURE_DISABLED",
        )

    def to_user_message(self) -> str:
        return "ディープリサーチ機能は現在ご利用いただけません。"


def wrap_research_error(func):
    """
    非同期関数の例外をリサーチ例外にラップするデコレータ

    使用例:
        @wrap_research_error
        async def research():
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ResearchError:
            raise
        except GenerationBaseException:
            raise
        except Exception as e:
            raise ResearchError(
                message=f"Unexpected error: {str(e)}",
                error_code="UNEXPECTED_RESEARCH_ERROR",
                original_error=e,
            )
    return wrapper


# =============================================================================
# Phase G5: 動画生成例外
# =============================================================================


# 遅延インポート
def _get_video_error_messages():
    from .constants import VIDEO_ERROR_MESSAGES
    return VIDEO_ERROR_MESSAGES


class VideoGenerationError(GenerationBaseException):
    """
    動画生成エラーの基底クラス

    すべての動画生成関連例外の親クラス。
    """

    def __init__(
        self,
        message: str,
        error_code: str = "VIDEO_GENERATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            generation_type=GenerationType.VIDEO,
            details=details,
            original_error=original_error,
        )


# -----------------------------------------------------------------------------
# 検証エラー
# -----------------------------------------------------------------------------


class VideoPromptEmptyError(VideoGenerationError):
    """プロンプト空エラー"""

    def __init__(self):
        super().__init__(
            message=_get_video_error_messages()["EMPTY_PROMPT"],
            error_code="VIDEO_PROMPT_EMPTY",
        )

    def to_user_message(self) -> str:
        return "どんな動画を作りたいか教えてほしいウル！"


class VideoPromptTooLongError(VideoGenerationError):
    """プロンプト長すぎエラー"""

    def __init__(self, actual_length: int, max_length: int):
        super().__init__(
            message=_get_video_error_messages()["PROMPT_TOO_LONG"].format(
                actual=actual_length, max=max_length
            ),
            error_code="VIDEO_PROMPT_TOO_LONG",
            details={"actual_length": actual_length, "max_length": max_length},
        )
        self.actual_length = actual_length
        self.max_length = max_length

    def to_user_message(self) -> str:
        return f"プロンプトが長すぎるウル（{self.actual_length}文字）。{self.max_length}文字以内にしてほしいウル！"


class VideoInvalidResolutionError(VideoGenerationError):
    """無効な解像度エラー"""

    def __init__(self, resolution: str, provider: str, supported_resolutions: List[str]):
        super().__init__(
            message=_get_video_error_messages()["INVALID_RESOLUTION"].format(
                resolution=resolution
            ),
            error_code="VIDEO_INVALID_RESOLUTION",
            details={
                "resolution": resolution,
                "provider": provider,
                "supported": supported_resolutions,
            },
        )
        self.resolution = resolution
        self.provider = provider
        self.supported_resolutions = supported_resolutions

    def to_user_message(self) -> str:
        return f"解像度 {self.resolution} は {self.provider} でサポートされていません。"


class VideoInvalidDurationError(VideoGenerationError):
    """無効な動画長エラー"""

    def __init__(self, duration: str, provider: str, supported_durations: List[str]):
        super().__init__(
            message=_get_video_error_messages()["INVALID_DURATION"].format(
                duration=duration
            ),
            error_code="VIDEO_INVALID_DURATION",
            details={
                "duration": duration,
                "provider": provider,
                "supported": supported_durations,
            },
        )
        self.duration = duration
        self.provider = provider
        self.supported_durations = supported_durations

    def to_user_message(self) -> str:
        return f"動画長 {self.duration}秒 は {self.provider} でサポートされていません。"


class VideoInvalidImageError(VideoGenerationError):
    """無効な入力画像エラー"""

    def __init__(self, reason: str = ""):
        super().__init__(
            message=_get_video_error_messages()["INVALID_IMAGE"],
            error_code="VIDEO_INVALID_IMAGE",
            details={"reason": reason},
        )
        self.reason = reason

    def to_user_message(self) -> str:
        return "入力画像が無効です。別の画像を試してみてください。"


# -----------------------------------------------------------------------------
# コンテンツポリシーエラー
# -----------------------------------------------------------------------------


class VideoContentPolicyViolationError(VideoGenerationError):
    """コンテンツポリシー違反エラー"""

    def __init__(self, reason: str = ""):
        super().__init__(
            message=_get_video_error_messages()["CONTENT_POLICY_VIOLATION"],
            error_code="VIDEO_CONTENT_POLICY_VIOLATION",
            details={"reason": reason},
        )
        self.reason = reason

    def to_user_message(self) -> str:
        return "コンテンツポリシーに違反するため、この動画は生成できません。別の内容でお試しください。"


class VideoSafetyFilterTriggeredError(VideoGenerationError):
    """安全フィルター発動エラー"""

    def __init__(self, filter_type: str = ""):
        super().__init__(
            message=_get_video_error_messages()["SAFETY_FILTER_TRIGGERED"],
            error_code="VIDEO_SAFETY_FILTER_TRIGGERED",
            details={"filter_type": filter_type},
        )
        self.filter_type = filter_type

    def to_user_message(self) -> str:
        return "安全フィルターにより生成がブロックされました。別の内容でお試しください。"


# -----------------------------------------------------------------------------
# API エラー
# -----------------------------------------------------------------------------


class RunwayAPIError(VideoGenerationError):
    """Runway API エラー"""

    def __init__(
        self,
        message: str = "",
        model: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=_get_video_error_messages()["RUNWAY_API_ERROR"].format(
                error=message or "Unknown error"
            ),
            error_code="RUNWAY_API_ERROR",
            details={"model": model, **(details or {})},
            original_error=original_error,
        )
        self.model = model

    def to_user_message(self) -> str:
        return "動画生成サービスでエラーが発生しました。もう一度お試しください。"


class RunwayRateLimitError(VideoGenerationError):
    """Runway レート制限エラー"""

    def __init__(self, retry_after: Optional[int] = None):
        super().__init__(
            message=_get_video_error_messages()["RUNWAY_RATE_LIMIT"].format(
                retry_after=retry_after or 60
            ),
            error_code="RUNWAY_RATE_LIMIT",
            details={"retry_after": retry_after},
        )
        self.retry_after = retry_after

    def to_user_message(self) -> str:
        if self.retry_after:
            return f"動画生成サービスが混み合っています。{self.retry_after}秒後にもう一度お試しください。"
        return "動画生成サービスが混み合っています。しばらく待ってからお試しください。"


class RunwayTimeoutError(VideoGenerationError):
    """Runway タイムアウトエラー"""

    def __init__(self, timeout_seconds: int = 300):
        super().__init__(
            message=_get_video_error_messages()["RUNWAY_TIMEOUT"],
            error_code="RUNWAY_TIMEOUT",
            details={"timeout_seconds": timeout_seconds},
        )
        self.timeout_seconds = timeout_seconds

    def to_user_message(self) -> str:
        return "動画生成がタイムアウトしました。もう一度お試しください。"


class RunwayQuotaExceededError(VideoGenerationError):
    """Runway クォータ超過エラー"""

    def __init__(self):
        super().__init__(
            message=_get_video_error_messages()["RUNWAY_QUOTA_EXCEEDED"],
            error_code="RUNWAY_QUOTA_EXCEEDED",
        )

    def to_user_message(self) -> str:
        return "動画生成のクォータに達しました。管理者にお問い合わせください。"


class RunwayServerError(VideoGenerationError):
    """Runway サーバーエラー"""

    def __init__(self, status_code: int = 500, message: str = ""):
        super().__init__(
            message=_get_video_error_messages()["RUNWAY_SERVER_ERROR"],
            error_code="RUNWAY_SERVER_ERROR",
            details={"status_code": status_code, "message": message},
        )
        self.status_code = status_code

    def to_user_message(self) -> str:
        return "動画生成サービスで一時的な障害が発生しています。しばらく待ってからお試しください。"


# -----------------------------------------------------------------------------
# その他のエラー
# -----------------------------------------------------------------------------


class VideoSaveError(VideoGenerationError):
    """動画保存エラー"""

    def __init__(self, path: Optional[str] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=_get_video_error_messages()["SAVE_FAILED"],
            error_code="VIDEO_SAVE_FAILED",
            details={"path": path},
            original_error=original_error,
        )
        self.path = path

    def to_user_message(self) -> str:
        return "動画の保存に失敗しました。もう一度お試しください。"


class VideoUploadError(VideoGenerationError):
    """動画アップロードエラー"""

    def __init__(self, destination: str = "", original_error: Optional[Exception] = None):
        super().__init__(
            message=_get_video_error_messages()["UPLOAD_FAILED"],
            error_code="VIDEO_UPLOAD_FAILED",
            details={"destination": destination},
            original_error=original_error,
        )
        self.destination = destination

    def to_user_message(self) -> str:
        return "動画のアップロードに失敗しました。もう一度お試しください。"


class VideoDailyLimitExceededError(VideoGenerationError):
    """日次上限超過エラー"""

    def __init__(self, limit: int):
        super().__init__(
            message=_get_video_error_messages()["DAILY_LIMIT_EXCEEDED"].format(limit=limit),
            error_code="VIDEO_DAILY_LIMIT_EXCEEDED",
            details={"limit": limit},
        )
        self.limit = limit

    def to_user_message(self) -> str:
        return f"本日の動画生成上限（{self.limit}本）に達しました。明日また試してください。"


class VideoConcurrentLimitExceededError(VideoGenerationError):
    """同時生成上限超過エラー"""

    def __init__(self, limit: int):
        super().__init__(
            message=_get_video_error_messages()["CONCURRENT_LIMIT_EXCEEDED"],
            error_code="VIDEO_CONCURRENT_LIMIT_EXCEEDED",
            details={"limit": limit},
        )
        self.limit = limit

    def to_user_message(self) -> str:
        return "現在、複数の動画を生成中です。しばらく待ってから再試行してください。"


class VideoFeatureDisabledError(VideoGenerationError):
    """動画生成機能無効エラー"""

    def __init__(self):
        super().__init__(
            message=_get_video_error_messages()["FEATURE_DISABLED"],
            error_code="VIDEO_FEATURE_DISABLED",
        )

    def to_user_message(self) -> str:
        return "動画生成機能は現在ご利用いただけません。"


class VideoGenerationCancelledError(VideoGenerationError):
    """動画生成キャンセルエラー"""

    def __init__(self, reason: str = ""):
        super().__init__(
            message=_get_video_error_messages()["GENERATION_CANCELLED"],
            error_code="VIDEO_GENERATION_CANCELLED",
            details={"reason": reason},
        )
        self.reason = reason

    def to_user_message(self) -> str:
        return "動画生成がキャンセルされました。"


def wrap_video_generation_error(func):
    """
    非同期関数の例外を動画生成例外にラップするデコレータ

    使用例:
        @wrap_video_generation_error
        async def generate_video():
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except VideoGenerationError:
            raise
        except GenerationBaseException:
            raise
        except Exception as e:
            raise VideoGenerationError(
                message=f"Unexpected error: {str(e)}",
                error_code="UNEXPECTED_VIDEO_ERROR",
                original_error=e,
            )
    return wrapper
