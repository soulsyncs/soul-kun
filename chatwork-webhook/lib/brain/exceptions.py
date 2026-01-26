# lib/brain/exceptions.py
# Version: v10.29.4 (2026-01-26)
# Codex Review Target: 脳アーキテクチャ全面有効化前レビュー
"""
ソウルくんの脳 - 例外定義

このファイルには、脳アーキテクチャで使用する全ての例外を定義します。
各層で発生しうるエラーを構造化し、適切なエラーハンドリングを可能にします。

設計書: docs/13_brain_architecture.md
"""

from typing import Optional, Dict, Any


class BrainError(Exception):
    """
    脳アーキテクチャの基底例外クラス

    全ての脳関連の例外はこのクラスを継承します。
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        """
        Args:
            message: エラーメッセージ（ユーザーに表示しない内部用）
            error_code: エラーコード（ログ分析用）
            details: 追加の詳細情報
            original_error: 元の例外（ラップする場合）
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "BRAIN_ERROR"
        self.details = details or {}
        self.original_error = original_error

    def to_dict(self) -> Dict[str, Any]:
        """ログ出力用の辞書形式に変換"""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "original_error": str(self.original_error) if self.original_error else None,
        }

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.message}"


# =============================================================================
# 理解層の例外
# =============================================================================


class UnderstandingError(BrainError):
    """
    理解層で発生するエラー

    ユーザーの意図を理解できなかった場合に発生します。
    """

    def __init__(
        self,
        message: str,
        raw_message: Optional[str] = None,
        reason: Optional[str] = None,
        **kwargs,
    ):
        """
        Args:
            message: エラーメッセージ
            raw_message: 理解できなかった元のメッセージ
            reason: 理解できなかった理由
        """
        details = kwargs.pop("details", {})
        details["raw_message"] = raw_message
        details["reason"] = reason
        super().__init__(
            message=message,
            error_code=kwargs.pop("error_code", "UNDERSTANDING_ERROR"),
            details=details,
            **kwargs,
        )


class AmbiguityError(UnderstandingError):
    """
    曖昧性が解決できなかった場合のエラー

    「あれ」「それ」などの代名詞が解決できない場合に発生します。
    """

    def __init__(
        self,
        message: str,
        ambiguous_term: str,
        candidates: Optional[list] = None,
        **kwargs,
    ):
        """
        Args:
            message: エラーメッセージ
            ambiguous_term: 曖昧な表現
            candidates: 解決候補のリスト
        """
        details = kwargs.pop("details", {})
        details["ambiguous_term"] = ambiguous_term
        details["candidates"] = candidates or []
        super().__init__(
            message=message,
            error_code="AMBIGUITY_ERROR",
            details=details,
            **kwargs,
        )


class IntentNotFoundError(UnderstandingError):
    """
    意図が特定できなかった場合のエラー

    ユーザーのメッセージから意図を推論できなかった場合に発生します。
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            error_code="INTENT_NOT_FOUND",
            **kwargs,
        )


# =============================================================================
# 判断層の例外
# =============================================================================


class DecisionError(BrainError):
    """
    判断層で発生するエラー

    アクションを決定できなかった場合に発生します。
    """

    def __init__(
        self,
        message: str,
        intent: Optional[str] = None,
        candidates: Optional[list] = None,
        **kwargs,
    ):
        """
        Args:
            message: エラーメッセージ
            intent: 理解した意図
            candidates: アクション候補のリスト
        """
        details = kwargs.pop("details", {})
        details["intent"] = intent
        details["candidates"] = candidates or []
        super().__init__(
            message=message,
            error_code=kwargs.pop("error_code", "DECISION_ERROR"),
            details=details,
            **kwargs,
        )


class NoMatchingActionError(DecisionError):
    """
    適合するアクションが見つからなかった場合のエラー

    SYSTEM_CAPABILITIESに該当する機能がない場合に発生します。
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            error_code="NO_MATCHING_ACTION",
            **kwargs,
        )


class MultipleMatchError(DecisionError):
    """
    複数のアクションが同じスコアでマッチした場合のエラー

    どのアクションを実行すべきか判断できない場合に発生します。
    """

    def __init__(self, message: str, actions: list, **kwargs):
        details = kwargs.pop("details", {})
        details["matched_actions"] = actions
        super().__init__(
            message=message,
            error_code="MULTIPLE_MATCH",
            details=details,
            **kwargs,
        )


# =============================================================================
# 実行層の例外
# =============================================================================


class ExecutionError(BrainError):
    """
    実行層で発生するエラー

    ハンドラーの実行に失敗した場合に発生します。
    """

    def __init__(
        self,
        message: str,
        action: Optional[str] = None,
        handler: Optional[str] = None,
        **kwargs,
    ):
        """
        Args:
            message: エラーメッセージ
            action: 実行しようとしたアクション
            handler: 実行しようとしたハンドラー
        """
        details = kwargs.pop("details", {})
        details["action"] = action
        details["handler"] = handler
        super().__init__(
            message=message,
            error_code=kwargs.pop("error_code", "EXECUTION_ERROR"),
            details=details,
            **kwargs,
        )


class HandlerNotFoundError(ExecutionError):
    """
    ハンドラーが見つからなかった場合のエラー

    指定されたアクションに対応するハンドラーが存在しない場合に発生します。
    """

    def __init__(self, message: str, action: str, **kwargs):
        super().__init__(
            message=message,
            action=action,
            error_code="HANDLER_NOT_FOUND",
            **kwargs,
        )


class HandlerTimeoutError(ExecutionError):
    """
    ハンドラーがタイムアウトした場合のエラー

    ハンドラーの実行が制限時間を超過した場合に発生します。
    """

    def __init__(
        self,
        message: str,
        action: str,
        timeout_seconds: int,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        details["timeout_seconds"] = timeout_seconds
        super().__init__(
            message=message,
            action=action,
            error_code="HANDLER_TIMEOUT",
            details=details,
            **kwargs,
        )


class ParameterValidationError(ExecutionError):
    """
    パラメータの検証に失敗した場合のエラー

    ハンドラーに渡すパラメータが不正な場合に発生します。
    """

    def __init__(
        self,
        message: str,
        missing_params: Optional[list] = None,
        invalid_params: Optional[dict] = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        details["missing_params"] = missing_params or []
        details["invalid_params"] = invalid_params or {}
        super().__init__(
            message=message,
            error_code="PARAMETER_VALIDATION",
            details=details,
            **kwargs,
        )


# =============================================================================
# 状態管理の例外
# =============================================================================


class StateError(BrainError):
    """
    状態管理で発生するエラー

    状態の遷移や取得に失敗した場合に発生します。
    """

    def __init__(
        self,
        message: str,
        room_id: Optional[str] = None,
        user_id: Optional[str] = None,
        state_type: Optional[str] = None,
        current_state: Optional[str] = None,
        target_state: Optional[str] = None,
        **kwargs,
    ):
        """
        Args:
            message: エラーメッセージ
            room_id: ルームID
            user_id: ユーザーID
            state_type: 状態タイプ
            current_state: 現在の状態
            target_state: 遷移先の状態
        """
        details = kwargs.pop("details", {})
        details["room_id"] = room_id
        details["user_id"] = user_id
        details["state_type"] = state_type
        details["current_state"] = current_state
        details["target_state"] = target_state
        super().__init__(
            message=message,
            error_code=kwargs.pop("error_code", "STATE_ERROR"),
            details=details,
            **kwargs,
        )


class InvalidStateTransitionError(StateError):
    """
    無効な状態遷移が発生した場合のエラー

    許可されていない状態遷移を試みた場合に発生します。
    """

    def __init__(
        self,
        message: str,
        from_state: str,
        to_state: str,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        details["from_state"] = from_state
        details["to_state"] = to_state
        super().__init__(
            message=message,
            error_code="INVALID_STATE_TRANSITION",
            details=details,
            **kwargs,
        )


class StateNotFoundError(StateError):
    """
    状態が見つからなかった場合のエラー

    期待する状態が存在しない場合に発生します。
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            error_code="STATE_NOT_FOUND",
            **kwargs,
        )


class StateTimeoutError(StateError):
    """
    状態がタイムアウトした場合のエラー

    セッションの有効期限が切れた場合に発生します。
    """

    def __init__(
        self,
        message: str,
        expired_at: str,
        **kwargs,
    ):
        details = kwargs.pop("details", {})
        details["expired_at"] = expired_at
        super().__init__(
            message=message,
            error_code="STATE_TIMEOUT",
            details=details,
            **kwargs,
        )


# =============================================================================
# 記憶アクセスの例外
# =============================================================================


class MemoryAccessError(BrainError):
    """
    記憶アクセスで発生するエラー

    記憶の取得や更新に失敗した場合に発生します。
    """

    def __init__(
        self,
        message: str,
        memory_type: Optional[str] = None,
        **kwargs,
    ):
        """
        Args:
            message: エラーメッセージ
            memory_type: 記憶の種類
        """
        details = kwargs.pop("details", {})
        details["memory_type"] = memory_type
        super().__init__(
            message=message,
            error_code=kwargs.pop("error_code", "MEMORY_ACCESS_ERROR"),
            details=details,
            **kwargs,
        )


class MemoryNotFoundError(MemoryAccessError):
    """
    記憶が見つからなかった場合のエラー

    指定した記憶が存在しない場合に発生します。
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            error_code="MEMORY_NOT_FOUND",
            **kwargs,
        )


class MemoryConnectionError(MemoryAccessError):
    """
    記憶ストレージへの接続に失敗した場合のエラー

    DBやFirestoreへの接続エラー。
    """

    def __init__(self, message: str, storage_type: str, **kwargs):
        details = kwargs.pop("details", {})
        details["storage_type"] = storage_type
        super().__init__(
            message=message,
            error_code="MEMORY_CONNECTION_ERROR",
            details=details,
            **kwargs,
        )


# =============================================================================
# 確認モードの例外
# =============================================================================


class ConfirmationTimeoutError(BrainError):
    """
    確認がタイムアウトした場合のエラー

    ユーザーが確認に応答しなかった場合に発生します。
    """

    def __init__(
        self,
        message: str,
        pending_action: str,
        timeout_minutes: int,
        **kwargs,
    ):
        """
        Args:
            message: エラーメッセージ
            pending_action: 確認待ちだったアクション
            timeout_minutes: タイムアウト時間（分）
        """
        details = kwargs.pop("details", {})
        details["pending_action"] = pending_action
        details["timeout_minutes"] = timeout_minutes
        super().__init__(
            message=message,
            error_code="CONFIRMATION_TIMEOUT",
            details=details,
            **kwargs,
        )


class ConfirmationRejectedError(BrainError):
    """
    確認が拒否された場合のエラー

    ユーザーが確認を拒否した場合に発生します。
    """

    def __init__(self, message: str, pending_action: str, **kwargs):
        details = kwargs.pop("details", {})
        details["pending_action"] = pending_action
        super().__init__(
            message=message,
            error_code="CONFIRMATION_REJECTED",
            details=details,
            **kwargs,
        )
