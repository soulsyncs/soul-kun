"""
Phase 2 B: 記憶基盤 例外クラス

このモジュールは、記憶機能で使用する例外クラスを定義します。

Author: Claude Code
Created: 2026-01-24
"""

from typing import Optional, Any
from functools import wraps


# ================================================================
# 基底例外
# ================================================================

class MemoryBaseException(Exception):
    """記憶機能の基底例外クラス"""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[dict] = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "MEMORY_ERROR"
        self.details = details or {}

    def to_dict(self) -> dict:
        """例外を辞書形式で返す"""
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details
        }


# ================================================================
# 具体的な例外クラス
# ================================================================

class MemoryError(MemoryBaseException):
    """一般的な記憶エラー"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            error_code="MEMORY_ERROR",
            details=details
        )


class SummarySaveError(MemoryBaseException):
    """B1: サマリー保存エラー"""

    def __init__(self, message: str, user_id: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="SUMMARY_SAVE_ERROR",
            details={"user_id": user_id} if user_id else {}
        )


class SummaryGenerationError(MemoryBaseException):
    """B1: サマリー生成エラー"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            error_code="SUMMARY_GENERATION_ERROR",
            details=details
        )


class PreferenceSaveError(MemoryBaseException):
    """B2: 嗜好保存エラー"""

    def __init__(
        self,
        message: str,
        user_id: Optional[str] = None,
        preference_type: Optional[str] = None
    ):
        super().__init__(
            message=message,
            error_code="PREFERENCE_SAVE_ERROR",
            details={
                "user_id": user_id,
                "preference_type": preference_type
            }
        )


class PreferenceNotFoundError(MemoryBaseException):
    """B2: 嗜好が見つからないエラー"""

    def __init__(self, user_id: str, preference_type: Optional[str] = None):
        super().__init__(
            message=f"Preference not found for user {user_id}",
            error_code="PREFERENCE_NOT_FOUND",
            details={
                "user_id": user_id,
                "preference_type": preference_type
            }
        )


class KnowledgeSaveError(MemoryBaseException):
    """B3: 知識保存エラー"""

    def __init__(self, message: str, source_id: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="KNOWLEDGE_SAVE_ERROR",
            details={"source_id": source_id} if source_id else {}
        )


class KnowledgeGenerationError(MemoryBaseException):
    """B3: 知識生成エラー"""

    def __init__(self, message: str, question: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="KNOWLEDGE_GENERATION_ERROR",
            details={"question": question} if question else {}
        )


class SearchError(MemoryBaseException):
    """B4: 検索エラー"""

    def __init__(self, message: str, query: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="SEARCH_ERROR",
            details={"query": query} if query else {}
        )


class IndexError(MemoryBaseException):
    """B4: インデックスエラー"""

    def __init__(self, message: str, message_id: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="INDEX_ERROR",
            details={"message_id": message_id} if message_id else {}
        )


class DatabaseError(MemoryBaseException):
    """データベースエラー"""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        details = {}
        if original_error:
            details["original_error"] = str(original_error)
        super().__init__(
            message=message,
            error_code="DATABASE_ERROR",
            details=details
        )


class ValidationError(MemoryBaseException):
    """バリデーションエラー"""

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            details={"field": field} if field else {}
        )


class LLMError(MemoryBaseException):
    """LLM APIエラー"""

    def __init__(self, message: str, model: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="LLM_ERROR",
            details={"model": model} if model else {}
        )


# ================================================================
# デコレータ
# ================================================================

def wrap_memory_error(func):
    """記憶機能のエラーをラップするデコレータ"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except MemoryBaseException:
            raise
        except Exception as e:
            raise MemoryError(
                message=f"Unexpected error in {func.__name__}: {str(e)}",
                details={"original_error": str(e)}
            )
    return wrapper


def wrap_database_error(func):
    """データベースエラーをラップするデコレータ"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except MemoryBaseException:
            raise
        except Exception as e:
            raise DatabaseError(
                message=f"Database error in {func.__name__}: {str(e)}",
                original_error=e
            )
    return wrapper
