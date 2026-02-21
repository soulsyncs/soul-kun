# lib/capabilities/multimodal/exceptions.py
"""
Phase M1: Multimodal入力能力 - 例外クラス

このモジュールは、Multimodal入力処理で使用する例外クラスを定義します。

設計書: docs/20_next_generation_capabilities.md セクション5
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from typing import Optional, Dict, Any
from functools import wraps

from .constants import InputType


# =============================================================================
# 基底例外クラス
# =============================================================================


class MultimodalBaseException(Exception):
    """
    Multimodal処理の基底例外クラス

    全てのMultimodal関連例外はこのクラスを継承します。
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        input_type: Optional[InputType] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        初期化

        Args:
            message: エラーメッセージ
            error_code: エラーコード
            input_type: 入力タイプ
            details: 追加の詳細情報
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "MULTIMODAL_ERROR"
        self.input_type = input_type
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """例外を辞書形式で返す"""
        result: Dict[str, Any] = {
            "error": self.error_code,
            "message": self.message,
        }
        if self.input_type:
            result["input_type"] = self.input_type.value
        if self.details:
            result["details"] = self.details
        return result

    def to_user_message(self) -> str:
        """
        ユーザー向けメッセージを生成

        ソウルくん口調でエラーを伝える。
        """
        return f"ごめんウル... {self.message}"


# =============================================================================
# 入力検証エラー
# =============================================================================


class ValidationError(MultimodalBaseException):
    """入力検証エラー"""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        input_type: Optional[InputType] = None,
    ):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            input_type=input_type,
            details={"field": field} if field else {},
        )
        self.field = field


class UnsupportedFormatError(ValidationError):
    """サポートされていないフォーマット"""

    def __init__(
        self,
        format_name: str,
        supported_formats: list,
        input_type: Optional[InputType] = None,
    ):
        message = f"フォーマット '{format_name}' はサポートされていないウル"
        super().__init__(
            message=message,
            field="format",
            input_type=input_type,
        )
        self.details["format"] = format_name
        self.details["supported_formats"] = supported_formats
        self.format_name = format_name


class FileTooLargeError(ValidationError):
    """ファイルサイズ超過"""

    def __init__(
        self,
        actual_size_bytes: int,
        max_size_bytes: int,
        input_type: Optional[InputType] = None,
    ):
        actual_mb = actual_size_bytes / (1024 * 1024)
        max_mb = max_size_bytes / (1024 * 1024)
        message = f"ファイルが大きすぎるウル（{actual_mb:.1f}MB / 最大{max_mb:.1f}MB）"
        super().__init__(
            message=message,
            field="file_size",
            input_type=input_type,
        )
        self.details["actual_size_bytes"] = actual_size_bytes
        self.details["max_size_bytes"] = max_size_bytes
        self.actual_size_bytes = actual_size_bytes
        self.max_size_bytes = max_size_bytes


class TooManyPagesError(ValidationError):
    """ページ数超過（PDF）"""

    def __init__(
        self,
        actual_pages: int,
        max_pages: int,
    ):
        message = f"ページ数が多すぎるウル（{actual_pages}ページ / 最大{max_pages}ページ）"
        super().__init__(
            message=message,
            field="page_count",
            input_type=InputType.PDF,
        )
        self.details["actual_pages"] = actual_pages
        self.details["max_pages"] = max_pages
        self.actual_pages = actual_pages
        self.max_pages = max_pages


# =============================================================================
# 画像処理エラー
# =============================================================================


class ImageProcessingError(MultimodalBaseException):
    """画像処理エラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "IMAGE_PROCESSING_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            input_type=InputType.IMAGE,
            details=details,
        )


class ImageDecodeError(ImageProcessingError):
    """画像デコードエラー"""

    def __init__(self, message: str = "画像を読み込めなかったウル"):
        super().__init__(
            message=message,
            error_code="IMAGE_DECODE_ERROR",
        )


class ImageDimensionError(ImageProcessingError):
    """画像サイズエラー"""

    def __init__(
        self,
        width: int,
        height: int,
        max_dimension: int,
    ):
        message = f"画像サイズが大きすぎるウル（{width}x{height} / 最大{max_dimension}px）"
        super().__init__(
            message=message,
            error_code="IMAGE_DIMENSION_ERROR",
            details={
                "width": width,
                "height": height,
                "max_dimension": max_dimension,
            },
        )


# =============================================================================
# PDF処理エラー
# =============================================================================


class PDFProcessingError(MultimodalBaseException):
    """PDF処理エラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "PDF_PROCESSING_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            input_type=InputType.PDF,
            details=details,
        )


class PDFDecodeError(PDFProcessingError):
    """PDFデコードエラー"""

    def __init__(self, message: str = "PDFを読み込めなかったウル"):
        super().__init__(
            message=message,
            error_code="PDF_DECODE_ERROR",
        )


class PDFEncryptedError(PDFProcessingError):
    """PDF暗号化エラー"""

    def __init__(self):
        super().__init__(
            message="PDFが暗号化されていて読めないウル",
            error_code="PDF_ENCRYPTED",
        )


class PDFOCRError(PDFProcessingError):
    """PDF OCRエラー"""

    def __init__(self, page_number: Optional[int] = None):
        message = "PDFのOCR処理に失敗したウル"
        if page_number is not None:
            message = f"PDFの{page_number}ページ目のOCR処理に失敗したウル"
        super().__init__(
            message=message,
            error_code="PDF_OCR_ERROR",
            details={"page_number": page_number} if page_number else {},
        )


# =============================================================================
# URL処理エラー
# =============================================================================


class URLProcessingError(MultimodalBaseException):
    """URL処理エラーの基底クラス"""

    def __init__(
        self,
        message: str,
        url: Optional[str] = None,
        error_code: str = "URL_PROCESSING_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        details = details or {}
        if url:
            # セキュリティ: URLの詳細は部分的にマスク
            details["url_domain"] = self._extract_domain(url)
        super().__init__(
            message=message,
            error_code=error_code,
            input_type=InputType.URL,
            details=details,
        )
        self.url = url

    @staticmethod
    def _extract_domain(url: str) -> str:
        """URLからドメインを抽出（セキュリティのため）"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc or "unknown"
        except Exception:
            return "unknown"


class URLBlockedError(URLProcessingError):
    """URLブロックエラー（セキュリティ）"""

    def __init__(self, url: str, reason: str = "セキュリティ上の理由"):
        super().__init__(
            message=f"セキュリティ上の理由でアクセスできないURLウル（{reason}）",
            url=url,
            error_code="URL_BLOCKED",
        )


class URLFetchError(URLProcessingError):
    """URL取得エラー"""

    def __init__(
        self,
        url: str,
        status_code: Optional[int] = None,
        reason: Optional[str] = None,
    ):
        if status_code == 404:
            message = "URLが見つからないウル（404）"
        elif status_code == 403:
            message = "URLへのアクセスが禁止されてるウル（403）"
        elif status_code == 401:
            message = "URLへのアクセスには認証が必要ウル（401）"
        elif status_code and status_code >= 500:
            message = f"URLのサーバーでエラーが発生したウル（{status_code}）"
        elif reason:
            message = f"URLにアクセスできなかったウル（{reason}）"
        else:
            message = "URLにアクセスできなかったウル"

        super().__init__(
            message=message,
            url=url,
            error_code="URL_FETCH_ERROR",
            details={"status_code": status_code} if status_code else {},
        )
        self.status_code = status_code


class URLTimeoutError(URLProcessingError):
    """URLタイムアウトエラー"""

    def __init__(self, url: str, timeout_seconds: int):
        super().__init__(
            message=f"URLへのアクセスがタイムアウトしたウル（{timeout_seconds}秒）",
            url=url,
            error_code="URL_TIMEOUT",
            details={"timeout_seconds": timeout_seconds},
        )


class URLParseError(URLProcessingError):
    """URL解析エラー"""

    def __init__(self, url: str):
        super().__init__(
            message="URLの形式が正しくないウル",
            url=url,
            error_code="URL_PARSE_ERROR",
        )


class URLContentExtractionError(URLProcessingError):
    """URLコンテンツ抽出エラー"""

    def __init__(self, url: str, reason: Optional[str] = None):
        message = "URLからコンテンツを抽出できなかったウル"
        if reason:
            message = f"{message}（{reason}）"
        super().__init__(
            message=message,
            url=url,
            error_code="URL_CONTENT_EXTRACTION_ERROR",
        )


# =============================================================================
# Vision API エラー
# =============================================================================


class VisionAPIError(MultimodalBaseException):
    """Vision APIエラー"""

    def __init__(
        self,
        message: str,
        model: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        details = {}
        if model:
            details["model"] = model
        if original_error:
            details["original_error"] = str(original_error)
        super().__init__(
            message=message,
            error_code="VISION_API_ERROR",
            details=details,
        )
        self.model = model
        self.original_error = original_error


class VisionAPITimeoutError(VisionAPIError):
    """Vision APIタイムアウトエラー"""

    def __init__(self, model: Optional[str] = None, timeout_seconds: int = 60):
        super().__init__(
            message=f"画像解析がタイムアウトしたウル（{timeout_seconds}秒）",
            model=model,
        )
        self.details["timeout_seconds"] = timeout_seconds


class VisionAPIRateLimitError(VisionAPIError):
    """Vision APIレート制限エラー"""

    def __init__(self, model: Optional[str] = None, retry_after: Optional[int] = None):
        message = "画像解析APIのレート制限に達したウル"
        if retry_after:
            message = f"{message}（{retry_after}秒後に再試行してほしいウル）"
        super().__init__(message=message, model=model)
        if retry_after:
            self.details["retry_after"] = retry_after


# =============================================================================
# 汎用エラー
# =============================================================================


class ContentExtractionError(MultimodalBaseException):
    """コンテンツ抽出エラー"""

    def __init__(
        self,
        message: str,
        input_type: Optional[InputType] = None,
    ):
        super().__init__(
            message=message,
            error_code="CONTENT_EXTRACTION_ERROR",
            input_type=input_type,
        )


class ProcessingTimeoutError(MultimodalBaseException):
    """処理タイムアウトエラー"""

    def __init__(
        self,
        message: str,
        input_type: Optional[InputType] = None,
        timeout_seconds: Optional[int] = None,
    ):
        details = {}
        if timeout_seconds:
            details["timeout_seconds"] = timeout_seconds
        super().__init__(
            message=message,
            error_code="PROCESSING_TIMEOUT",
            input_type=input_type,
            details=details,
        )


# =============================================================================
# デコレータ
# =============================================================================


def wrap_multimodal_error(func):
    """
    Multimodal処理のエラーをラップするデコレータ

    予期せぬエラーをMultimodalBaseExceptionに変換します。
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except MultimodalBaseException:
            # すでにMultimodal例外の場合はそのまま再送出
            raise
        except Exception as e:
            # 予期せぬエラーはラップ
            raise MultimodalBaseException(
                message=f"予期せぬエラーが発生しました（{type(e).__name__}）。管理者にお問い合わせください",
                error_code="UNEXPECTED_ERROR",
                details={"error_type": type(e).__name__},
            )
    return wrapper


def wrap_sync_multimodal_error(func):
    """
    Multimodal処理のエラーをラップするデコレータ（同期版）
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except MultimodalBaseException:
            raise
        except Exception as e:
            raise MultimodalBaseException(
                message=f"予期せぬエラーが発生しました（{type(e).__name__}）。管理者にお問い合わせください",
                error_code="UNEXPECTED_ERROR",
                details={"error_type": type(e).__name__},
            )
    return wrapper


# =============================================================================
# Phase M2: 音声処理エラー
# =============================================================================


class AudioProcessingError(MultimodalBaseException):
    """音声処理エラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "AUDIO_PROCESSING_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            input_type=InputType.AUDIO,
            details=details,
        )


class AudioDecodeError(AudioProcessingError):
    """音声デコードエラー"""

    def __init__(self, message: str = "音声ファイルを読み込めなかったウル"):
        super().__init__(
            message=message,
            error_code="AUDIO_DECODE_ERROR",
        )


class AudioTooLongError(AudioProcessingError):
    """音声時間超過エラー"""

    def __init__(
        self,
        actual_duration_seconds: float,
        max_duration_seconds: int,
    ):
        actual_min = actual_duration_seconds / 60
        max_min = max_duration_seconds // 60
        message = f"音声が長すぎるウル（{actual_min:.1f}分 / 最大{max_min}分）"
        super().__init__(
            message=message,
            error_code="AUDIO_TOO_LONG",
            details={
                "actual_duration_seconds": actual_duration_seconds,
                "max_duration_seconds": max_duration_seconds,
            },
        )
        self.actual_duration_seconds = actual_duration_seconds
        self.max_duration_seconds = max_duration_seconds


class AudioTranscriptionError(AudioProcessingError):
    """文字起こしエラー"""

    def __init__(
        self,
        message: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        if message is None:
            if reason:
                message = f"音声の文字起こしに失敗したウル（{reason}）"
            else:
                message = "音声の文字起こしに失敗したウル"
        super().__init__(
            message=message,
            error_code="AUDIO_TRANSCRIPTION_ERROR",
            details={"reason": reason} if reason else None,
        )


class NoSpeechDetectedError(AudioProcessingError):
    """音声検出エラー"""

    def __init__(self):
        super().__init__(
            message="音声が検出されなかったウル（無音または音声なし）",
            error_code="NO_SPEECH_DETECTED",
        )


class SpeakerDetectionError(AudioProcessingError):
    """話者検出エラー"""

    def __init__(self, message: str = "話者の識別に失敗したウル"):
        super().__init__(
            message=message,
            error_code="SPEAKER_DETECTION_ERROR",
        )


# =============================================================================
# Phase M2: Whisper API エラー
# =============================================================================


class WhisperAPIError(MultimodalBaseException):
    """Whisper APIエラー"""

    def __init__(
        self,
        message: str,
        model: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        details = {}
        if model:
            details["model"] = model
        if original_error:
            details["original_error"] = str(original_error)
        super().__init__(
            message=message,
            error_code="WHISPER_API_ERROR",
            input_type=InputType.AUDIO,
            details=details,
        )
        self.model = model
        self.original_error = original_error


class WhisperAPITimeoutError(WhisperAPIError):
    """Whisper APIタイムアウトエラー"""

    def __init__(self, model: Optional[str] = None, timeout_seconds: int = 300):
        super().__init__(
            message=f"音声の文字起こしがタイムアウトしたウル（{timeout_seconds}秒）",
            model=model,
        )
        self.details["timeout_seconds"] = timeout_seconds


class WhisperAPIRateLimitError(WhisperAPIError):
    """Whisper APIレート制限エラー"""

    def __init__(self, model: Optional[str] = None, retry_after: Optional[int] = None):
        message = "文字起こしAPIのレート制限に達したウル"
        if retry_after:
            message = f"{message}（{retry_after}秒後に再試行してほしいウル）"
        super().__init__(message=message, model=model)
        if retry_after:
            self.details["retry_after"] = retry_after
