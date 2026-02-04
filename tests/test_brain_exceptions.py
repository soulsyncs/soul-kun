"""
lib/brain/exceptions.py のテスト
"""

import pytest

from lib.brain.exceptions import (
    BrainError,
    UnderstandingError,
    AmbiguityError,
    IntentNotFoundError,
    DecisionError,
    NoMatchingActionError,
    MultipleMatchError,
    ExecutionError,
    StateError,
    InvalidStateTransitionError,
    MemoryAccessError,
)


class TestBrainError:
    """BrainErrorのテスト"""

    def test_basic_error(self):
        """基本的なエラー作成テスト"""
        error = BrainError("Test error message")
        assert str(error) == "[BRAIN_ERROR] Test error message"
        assert error.message == "Test error message"
        assert error.error_code == "BRAIN_ERROR"
        assert error.details == {}
        assert error.original_error is None

    def test_error_with_code(self):
        """エラーコード付きエラーテスト"""
        error = BrainError("Custom error", error_code="CUSTOM_001")
        assert error.error_code == "CUSTOM_001"
        assert "[CUSTOM_001]" in str(error)

    def test_error_with_details(self):
        """詳細付きエラーテスト"""
        details = {"key1": "value1", "key2": 123}
        error = BrainError("Error with details", details=details)
        assert error.details == details

    def test_error_with_original_error(self):
        """元の例外付きエラーテスト"""
        original = ValueError("Original error")
        error = BrainError("Wrapped error", original_error=original)
        assert error.original_error == original

    def test_to_dict(self):
        """辞書変換テスト"""
        original = ValueError("Original")
        error = BrainError(
            "Test",
            error_code="TEST_001",
            details={"foo": "bar"},
            original_error=original,
        )
        
        result = error.to_dict()
        
        assert result["error_type"] == "BrainError"
        assert result["error_code"] == "TEST_001"
        assert result["message"] == "Test"
        assert result["details"] == {"foo": "bar"}
        assert "Original" in result["original_error"]


class TestUnderstandingError:
    """UnderstandingErrorのテスト"""

    def test_basic_understanding_error(self):
        """基本的な理解エラーテスト"""
        error = UnderstandingError("Cannot understand")
        assert error.error_code == "UNDERSTANDING_ERROR"

    def test_with_raw_message(self):
        """元メッセージ付きエラーテスト"""
        error = UnderstandingError(
            "Cannot understand", 
            raw_message="asdfghjkl"
        )
        assert error.details["raw_message"] == "asdfghjkl"

    def test_with_reason(self):
        """理由付きエラーテスト"""
        error = UnderstandingError(
            "Cannot understand",
            reason="No matching intent"
        )
        assert error.details["reason"] == "No matching intent"


class TestAmbiguityError:
    """AmbiguityErrorのテスト"""

    def test_ambiguity_error(self):
        """曖昧性エラーテスト"""
        error = AmbiguityError(
            "Ambiguous reference",
            ambiguous_term="それ",
            candidates=["タスクA", "タスクB"],
        )
        assert isinstance(error, UnderstandingError)
        assert error.details["ambiguous_term"] == "それ"
        assert error.details["candidates"] == ["タスクA", "タスクB"]


class TestIntentNotFoundError:
    """IntentNotFoundErrorのテスト"""

    def test_intent_not_found_error(self):
        """意図見つからないエラーテスト"""
        error = IntentNotFoundError("No intent found")
        assert isinstance(error, UnderstandingError)


class TestDecisionError:
    """DecisionErrorのテスト"""

    def test_decision_error(self):
        """判断エラーテスト"""
        error = DecisionError("Cannot decide")
        assert isinstance(error, BrainError)


class TestNoMatchingActionError:
    """NoMatchingActionErrorのテスト"""

    def test_no_matching_action_error(self):
        """マッチするアクションなしエラーテスト"""
        error = NoMatchingActionError("No action matches")
        assert isinstance(error, DecisionError)


class TestExecutionError:
    """ExecutionErrorのテスト"""

    def test_execution_error(self):
        """実行エラーテスト"""
        error = ExecutionError("Execution failed")
        assert isinstance(error, BrainError)


class TestStateError:
    """StateErrorのテスト"""

    def test_state_error(self):
        """状態エラーテスト"""
        error = StateError("State error")
        assert isinstance(error, BrainError)


class TestInvalidStateTransitionError:
    """InvalidStateTransitionErrorのテスト"""

    def test_invalid_state_transition_error(self):
        """無効な状態遷移エラーテスト"""
        error = InvalidStateTransitionError(
            "Invalid transition",
            from_state="idle",
            to_state="completed",
        )
        assert isinstance(error, StateError)
        assert error.details["from_state"] == "idle"
        assert error.details["to_state"] == "completed"


class TestMemoryAccessError:
    """MemoryAccessErrorのテスト"""

    def test_memory_access_error(self):
        """メモリアクセスエラーテスト"""
        error = MemoryAccessError("Memory access failed")
        assert isinstance(error, BrainError)
