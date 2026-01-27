# lib/capabilities/generation/exceptions.py
"""
Phase G1: 文書生成能力 - 例外定義

このモジュールは、文書生成に関する例外クラスを定義します。

設計書: docs/20_next_generation_capabilities.md セクション6
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from typing import Optional, Dict, Any
from functools import wraps

from .constants import GenerationType, ERROR_MESSAGES


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
