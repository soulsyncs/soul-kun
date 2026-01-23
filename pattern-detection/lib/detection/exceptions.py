"""
Phase 2 進化版 A1: パターン検出 - カスタム例外

このモジュールは、検出基盤（Detection Framework）で使用する
カスタム例外クラスを定義します。

設計書: docs/06_phase2_a1_pattern_detection.md

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-23
Version: 1.0
"""

from typing import Any, Optional

from lib.detection.constants import ErrorCode


class DetectionBaseException(Exception):
    """
    検出基盤の基底例外クラス

    全ての検出関連例外はこのクラスを継承する

    Attributes:
        error_code: エラーコード（ErrorCode Enum）
        message: エラーメッセージ
        details: 追加の詳細情報（辞書形式）
        original_exception: 元の例外（ラップする場合）
    """

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        details: Optional[dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ) -> None:
        """
        例外を初期化

        Args:
            error_code: エラーコード
            message: エラーメッセージ
            details: 追加の詳細情報（オプション）
            original_exception: 元の例外（オプション）
        """
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        self.original_exception = original_exception

        # 機密情報をサニタイズしたメッセージを作成
        sanitized_message = self._sanitize_message(message)
        super().__init__(sanitized_message)

    def _sanitize_message(self, message: str) -> str:
        """
        エラーメッセージから機密情報を除去

        CLAUDE.md 鉄則8: エラーメッセージに機密情報を含めない

        Args:
            message: 元のメッセージ

        Returns:
            サニタイズされたメッセージ
        """
        # 機密情報のパターンを除去
        # 注意: 本番環境ではより厳密なサニタイズが必要
        import re

        # UUIDをマスク（最初の8文字のみ表示）
        message = re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            lambda m: m.group()[:8] + '...',
            message,
            flags=re.IGNORECASE
        )

        # メールアドレスをマスク
        message = re.sub(
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
            '[EMAIL]',
            message
        )

        # IPアドレスをマスク
        message = re.sub(
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}',
            '[IP]',
            message
        )

        return message

    def to_dict(self) -> dict[str, Any]:
        """
        例外を辞書形式に変換

        APIレスポンスやログ出力に使用

        Returns:
            例外情報の辞書
        """
        result = {
            "error_code": self.error_code.value,
            "message": str(self),
        }

        if self.details:
            # 詳細情報もサニタイズ
            result["details"] = self._sanitize_details(self.details)

        return result

    def _sanitize_details(self, details: dict[str, Any]) -> dict[str, Any]:
        """
        詳細情報から機密情報を除去

        Args:
            details: 元の詳細情報

        Returns:
            サニタイズされた詳細情報
        """
        sanitized = {}
        sensitive_keys = {
            "password", "token", "secret", "api_key", "apikey",
            "credential", "auth", "authorization"
        }

        for key, value in details.items():
            if key.lower() in sensitive_keys:
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, str):
                sanitized[key] = self._sanitize_message(value)
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_details(value)
            else:
                sanitized[key] = value

        return sanitized

    def __repr__(self) -> str:
        """
        デバッグ用の文字列表現
        """
        return (
            f"{self.__class__.__name__}("
            f"error_code={self.error_code.value!r}, "
            f"message={self.message!r})"
        )


class DetectionError(DetectionBaseException):
    """
    検出処理中のエラー

    パターン検出処理の実行中に発生するエラー

    Example:
        >>> raise DetectionError(
        ...     message="Failed to detect patterns",
        ...     details={"org_id": org_id, "reason": "Database timeout"}
        ... )
    """

    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ) -> None:
        super().__init__(
            error_code=ErrorCode.DETECTION_ERROR,
            message=message,
            details=details,
            original_exception=original_exception
        )


class PatternSaveError(DetectionBaseException):
    """
    パターン保存エラー

    question_patternsテーブルへの保存中に発生するエラー

    Example:
        >>> raise PatternSaveError(
        ...     message="Failed to save pattern",
        ...     details={"pattern_hash": hash_value}
        ... )
    """

    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ) -> None:
        super().__init__(
            error_code=ErrorCode.PATTERN_SAVE_ERROR,
            message=message,
            details=details,
            original_exception=original_exception
        )


class InsightCreateError(DetectionBaseException):
    """
    インサイト作成エラー

    soulkun_insightsテーブルへの保存中に発生するエラー

    Example:
        >>> raise InsightCreateError(
        ...     message="Failed to create insight",
        ...     details={"insight_type": "pattern_detected"}
        ... )
    """

    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ) -> None:
        super().__init__(
            error_code=ErrorCode.INSIGHT_CREATE_ERROR,
            message=message,
            details=details,
            original_exception=original_exception
        )


class NotificationError(DetectionBaseException):
    """
    通知送信エラー

    ChatWork等への通知送信中に発生するエラー

    Example:
        >>> raise NotificationError(
        ...     message="Failed to send notification",
        ...     details={"room_id": room_id, "status_code": 429}
        ... )
    """

    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ) -> None:
        super().__init__(
            error_code=ErrorCode.NOTIFICATION_ERROR,
            message=message,
            details=details,
            original_exception=original_exception
        )


class DatabaseError(DetectionBaseException):
    """
    データベースエラー

    DB接続やクエリ実行中に発生するエラー

    Example:
        >>> raise DatabaseError(
        ...     message="Database connection failed",
        ...     original_exception=e
        ... )
    """

    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ) -> None:
        super().__init__(
            error_code=ErrorCode.DATABASE_ERROR,
            message=message,
            details=details,
            original_exception=original_exception
        )


class ValidationError(DetectionBaseException):
    """
    バリデーションエラー

    入力値の検証中に発生するエラー

    Example:
        >>> raise ValidationError(
        ...     message="Invalid organization_id",
        ...     details={"field": "organization_id", "value": "invalid"}
        ... )
    """

    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ) -> None:
        super().__init__(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=message,
            details=details,
            original_exception=original_exception
        )


class AuthenticationError(DetectionBaseException):
    """
    認証エラー

    APIトークン等の認証に失敗した場合のエラー

    Example:
        >>> raise AuthenticationError(
        ...     message="Invalid API token"
        ... )
    """

    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ) -> None:
        super().__init__(
            error_code=ErrorCode.AUTHENTICATION_ERROR,
            message=message,
            details=details,
            original_exception=original_exception
        )


class AuthorizationError(DetectionBaseException):
    """
    認可エラー

    権限不足の場合のエラー

    Example:
        >>> raise AuthorizationError(
        ...     message="Insufficient permissions to view insights"
        ... )
    """

    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ) -> None:
        super().__init__(
            error_code=ErrorCode.AUTHORIZATION_ERROR,
            message=message,
            details=details,
            original_exception=original_exception
        )


# ================================================================
# 例外ハンドリングユーティリティ
# ================================================================

def wrap_database_error(e: Exception, operation: str) -> DatabaseError:
    """
    データベース例外をDatabaseErrorにラップ

    Args:
        e: 元の例外
        operation: 実行中だった操作の説明

    Returns:
        DatabaseError: ラップされた例外
    """
    return DatabaseError(
        message=f"Database operation failed: {operation}",
        details={"operation": operation, "error_type": type(e).__name__},
        original_exception=e
    )


def wrap_detection_error(e: Exception, detector_type: str) -> DetectionError:
    """
    検出処理例外をDetectionErrorにラップ

    Args:
        e: 元の例外
        detector_type: 検出器の種類（例: "a1_pattern"）

    Returns:
        DetectionError: ラップされた例外
    """
    return DetectionError(
        message=f"Detection failed in {detector_type}",
        details={"detector_type": detector_type, "error_type": type(e).__name__},
        original_exception=e
    )
