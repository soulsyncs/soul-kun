# tests/test_brain_validation.py
"""
lib/brain/validation.py のユニットテスト

v10.30.0: SYSTEM_CAPABILITIESとハンドラーの整合性チェック機能のテスト
"""

import pytest
from lib.brain.validation import (
    ValidationResult,
    ValidationError,
    validate_capabilities_handlers,
    validate_brain_metadata,
    check_capabilities_coverage,
)


# =============================================================================
# テスト用データ
# =============================================================================


VALID_BRAIN_METADATA = {
    "decision_keywords": {
        "primary": ["タスク作成", "タスク追加"],
        "secondary": ["タスク", "仕事"],
        "negative": ["検索", "完了"],
    },
    "intent_keywords": {
        "primary": ["タスク作成", "タスク追加"],
        "secondary": ["タスク"],
        "modifiers": ["作成", "追加"],
        "negative": [],
        "confidence_boost": 0.85,
    },
    "risk_level": "low",
    "priority": 3,
}


VALID_CAPABILITIES = {
    "chatwork_task_create": {
        "name": "ChatWorkタスク作成",
        "enabled": True,
        "brain_metadata": VALID_BRAIN_METADATA,
    },
    "chatwork_task_search": {
        "name": "ChatWorkタスク検索",
        "enabled": True,
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["タスク検索"],
                "secondary": ["タスク"],
                "negative": [],
            },
            "intent_keywords": {
                "primary": ["タスク検索"],
                "secondary": [],
                "modifiers": [],
                "negative": [],
                "confidence_boost": 0.8,
            },
            "risk_level": "low",
            "priority": 5,
        },
    },
    "disabled_action": {
        "name": "無効化されたアクション",
        "enabled": False,
        # brain_metadataがなくてもOK（無効化されているため）
    },
}


VALID_HANDLERS = {
    "chatwork_task_create": lambda: None,
    "chatwork_task_search": lambda: None,
}


# =============================================================================
# ValidationResult テスト
# =============================================================================


class TestValidationResult:
    """ValidationResultクラスのテスト"""

    def test_initial_state(self):
        """初期状態のテスト"""
        result = ValidationResult()
        assert result.is_valid is True
        assert len(result.errors) == 0
        assert len(result.warnings) == 0
        assert len(result.info) == 0

    def test_add_error(self):
        """エラー追加のテスト"""
        result = ValidationResult()
        error = ValidationError(
            action="test_action",
            error_type="test_error",
            message="Test message",
            severity="error",
        )
        result.add_error(error)

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert result.errors[0].action == "test_action"

    def test_add_warning(self):
        """警告追加のテスト"""
        result = ValidationResult()
        warning = ValidationError(
            action="test_action",
            error_type="test_warning",
            message="Test warning",
            severity="warning",
        )
        result.add_error(warning)

        assert result.is_valid is True  # 警告はis_validに影響しない
        assert len(result.warnings) == 1

    def test_add_info(self):
        """情報追加のテスト"""
        result = ValidationResult()
        info = ValidationError(
            action="test_action",
            error_type="test_info",
            message="Test info",
            severity="info",
        )
        result.add_error(info)

        assert result.is_valid is True
        assert len(result.info) == 1

    def test_summary(self):
        """サマリー生成のテスト"""
        result = ValidationResult()
        result.total_capabilities = 10
        result.enabled_capabilities = 8
        result.capabilities_with_metadata = 6
        result.capabilities_with_handlers = 8

        summary = result.summary()
        assert "PASSED" in summary
        assert "Total capabilities: 10" in summary
        assert "Enabled: 8" in summary


# =============================================================================
# validate_brain_metadata テスト
# =============================================================================


class TestValidateBrainMetadata:
    """validate_brain_metadata関数のテスト"""

    def test_valid_metadata(self):
        """有効なメタデータのテスト"""
        errors = validate_brain_metadata("test_action", VALID_BRAIN_METADATA)
        assert len(errors) == 0

    def test_invalid_risk_level(self):
        """無効なrisk_levelのテスト"""
        metadata = {
            **VALID_BRAIN_METADATA,
            "risk_level": "invalid_level",
        }
        errors = validate_brain_metadata("test_action", metadata)

        assert len(errors) > 0
        assert any(e.error_type == "invalid_value" for e in errors)

    def test_invalid_priority_range(self):
        """無効なpriorityのテスト"""
        metadata = {
            **VALID_BRAIN_METADATA,
            "priority": 100,  # 最大は10
        }
        errors = validate_brain_metadata("test_action", metadata)

        assert len(errors) > 0
        assert any(e.error_type == "value_out_of_range" for e in errors)

    def test_invalid_confidence_boost(self):
        """無効なconfidence_boostのテスト"""
        metadata = {
            "intent_keywords": {
                "primary": [],
                "secondary": [],
                "modifiers": [],
                "negative": [],
                "confidence_boost": 1.5,  # 最大は1.0
            },
        }
        errors = validate_brain_metadata("test_action", metadata)

        assert len(errors) > 0
        assert any(e.error_type == "value_out_of_range" for e in errors)

    def test_invalid_type(self):
        """無効な型のテスト"""
        metadata = {
            "risk_level": 123,  # strであるべき
        }
        errors = validate_brain_metadata("test_action", metadata)

        assert len(errors) > 0
        assert any(e.error_type == "invalid_type" for e in errors)

    def test_empty_metadata(self):
        """空のメタデータのテスト"""
        errors = validate_brain_metadata("test_action", {})
        # 空でもエラーにならない（フィールドは必須ではない）
        assert len(errors) == 0


# =============================================================================
# validate_capabilities_handlers テスト
# =============================================================================


class TestValidateCapabilitiesHandlers:
    """validate_capabilities_handlers関数のテスト"""

    def test_valid_capabilities_and_handlers(self):
        """有効なcapabilitiesとhandlersのテスト"""
        result = validate_capabilities_handlers(
            capabilities=VALID_CAPABILITIES,
            handlers=VALID_HANDLERS,
        )

        assert result.is_valid is True
        assert result.total_capabilities == 3
        assert result.enabled_capabilities == 2
        assert result.capabilities_with_metadata == 2
        assert result.capabilities_with_handlers == 2

    def test_missing_brain_metadata_warning(self):
        """brain_metadataがない場合の警告テスト"""
        capabilities = {
            "action_without_metadata": {
                "name": "メタデータなしのアクション",
                "enabled": True,
                # brain_metadataがない
            },
        }
        result = validate_capabilities_handlers(
            capabilities=capabilities,
            handlers={},
            strict=False,
        )

        assert result.is_valid is True  # strict=Falseなので警告のみ
        assert len(result.warnings) > 0
        assert any(w.error_type == "missing_brain_metadata" for w in result.warnings)

    def test_missing_brain_metadata_strict(self):
        """strict=Trueでbrain_metadataがない場合のエラーテスト"""
        capabilities = {
            "action_without_metadata": {
                "name": "メタデータなしのアクション",
                "enabled": True,
            },
        }
        result = validate_capabilities_handlers(
            capabilities=capabilities,
            handlers={},
            strict=True,
        )

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert any(e.error_type == "missing_brain_metadata" for e in result.errors)

    def test_missing_handler_warning(self):
        """ハンドラーがない場合の警告テスト"""
        capabilities = {
            "action_with_metadata": {
                "name": "アクション",
                "enabled": True,
                "brain_metadata": VALID_BRAIN_METADATA,
            },
        }
        result = validate_capabilities_handlers(
            capabilities=capabilities,
            handlers={},  # ハンドラーがない
        )

        assert len(result.warnings) > 0
        assert any(w.error_type == "missing_handler" for w in result.warnings)

    def test_orphan_handler_warning(self):
        """capabilitiesにないハンドラーの警告テスト"""
        result = validate_capabilities_handlers(
            capabilities={},
            handlers={"orphan_handler": lambda: None},
        )

        assert len(result.warnings) > 0
        assert any(w.error_type == "orphan_handler" for w in result.warnings)

    def test_disabled_capabilities_ignored(self):
        """無効化されたcapabilitiesは検証されないことをテスト"""
        capabilities = {
            "disabled_action": {
                "name": "無効化されたアクション",
                "enabled": False,
                # brain_metadataがなくても無視される
            },
        }
        result = validate_capabilities_handlers(
            capabilities=capabilities,
            handlers={},
        )

        assert result.is_valid is True
        assert result.enabled_capabilities == 0
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_special_actions_no_handler_required(self):
        """特殊アクションはハンドラー不要テスト"""
        capabilities = {
            "general_conversation": {
                "name": "一般会話",
                "enabled": True,
                "brain_metadata": VALID_BRAIN_METADATA,
            },
            "api_limitation": {
                "name": "API制限",
                "enabled": True,
                "brain_metadata": VALID_BRAIN_METADATA,
            },
        }
        result = validate_capabilities_handlers(
            capabilities=capabilities,
            handlers={},  # ハンドラーなし
        )

        # 特殊アクションなのでmissing_handler警告は出ない
        missing_handler_warnings = [
            w for w in result.warnings
            if w.error_type == "missing_handler"
        ]
        assert len(missing_handler_warnings) == 0


# =============================================================================
# check_capabilities_coverage テスト
# =============================================================================


class TestCheckCapabilitiesCoverage:
    """check_capabilities_coverage関数のテスト"""

    def test_full_coverage(self):
        """100%カバレッジのテスト"""
        coverage = check_capabilities_coverage(VALID_CAPABILITIES)

        assert coverage["total_enabled"] == 2  # disabled_actionは除外
        assert coverage["with_brain_metadata"] == 2
        assert coverage["percentage"] == 100.0
        assert len(coverage["missing_metadata"]) == 0

    def test_partial_coverage(self):
        """部分的カバレッジのテスト"""
        capabilities = {
            "with_metadata": {
                "name": "メタデータあり",
                "enabled": True,
                "brain_metadata": VALID_BRAIN_METADATA,
            },
            "without_metadata": {
                "name": "メタデータなし",
                "enabled": True,
                # brain_metadataなし
            },
        }
        coverage = check_capabilities_coverage(capabilities)

        assert coverage["total_enabled"] == 2
        assert coverage["with_brain_metadata"] == 1
        assert coverage["percentage"] == 50.0
        assert "without_metadata" in coverage["missing_metadata"]

    def test_empty_capabilities(self):
        """空のcapabilitiesのテスト"""
        coverage = check_capabilities_coverage({})

        assert coverage["total_enabled"] == 0
        assert coverage["percentage"] == 0
        assert len(coverage["missing_metadata"]) == 0

    def test_all_disabled(self):
        """全て無効化されている場合のテスト"""
        capabilities = {
            "disabled1": {"name": "無効1", "enabled": False},
            "disabled2": {"name": "無効2", "enabled": False},
        }
        coverage = check_capabilities_coverage(capabilities)

        assert coverage["total_enabled"] == 0
        assert coverage["percentage"] == 0

    def test_coverage_detail_fields(self):
        """カバレッジ詳細フィールドのテスト"""
        coverage = check_capabilities_coverage(VALID_CAPABILITIES)

        # 各フィールドの存在確認
        assert "total_enabled" in coverage
        assert "with_brain_metadata" in coverage
        assert "with_decision_keywords" in coverage
        assert "with_intent_keywords" in coverage
        assert "with_risk_level" in coverage
        assert "with_priority" in coverage
        assert "missing_metadata" in coverage
        assert "percentage" in coverage

        # 値の確認
        assert coverage["with_decision_keywords"] == 2
        assert coverage["with_intent_keywords"] == 2
        assert coverage["with_risk_level"] == 2
        assert coverage["with_priority"] == 2


# =============================================================================
# 統合テスト
# =============================================================================


class TestIntegration:
    """統合テスト"""

    def test_validate_and_coverage(self):
        """検証とカバレッジの両方をテスト"""
        # 検証
        result = validate_capabilities_handlers(
            capabilities=VALID_CAPABILITIES,
            handlers=VALID_HANDLERS,
        )
        assert result.is_valid is True

        # カバレッジ
        coverage = check_capabilities_coverage(VALID_CAPABILITIES)
        assert coverage["percentage"] == 100.0

    def test_invalid_metadata_detected(self):
        """無効なメタデータが検出されることをテスト"""
        capabilities = {
            "invalid_action": {
                "name": "無効なメタデータ",
                "enabled": True,
                "brain_metadata": {
                    "risk_level": "invalid",  # 無効な値
                    "priority": 100,  # 範囲外
                },
            },
        }
        result = validate_capabilities_handlers(
            capabilities=capabilities,
            handlers={},
        )

        # エラーが検出される
        assert len(result.errors) > 0

        # 期待するエラータイプが含まれる
        error_types = [e.error_type for e in result.errors]
        assert "invalid_value" in error_types
