# lib/brain/validation.py
"""
ソウルくんの脳 - バリデーション層

SYSTEM_CAPABILITIESとハンドラーの整合性をチェックする機能を提供します。

設計書: docs/13_brain_architecture.md
設計書: docs/14_brain_refactoring_plan.md（Phase B: SYSTEM_CAPABILITIES拡張）

【v10.30.0 新規作成】
- validate_capabilities_handlers(): 整合性チェック
- validate_brain_metadata(): brain_metadataの構造検証
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set

logger = logging.getLogger(__name__)


# =============================================================================
# 検証結果データクラス
# =============================================================================


@dataclass
class ValidationError:
    """検証エラー"""
    action: str
    error_type: str
    message: str
    severity: str = "error"  # "error", "warning", "info"


@dataclass
class ValidationResult:
    """検証結果"""
    is_valid: bool = True
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    info: List[ValidationError] = field(default_factory=list)

    # 統計情報
    total_capabilities: int = 0
    enabled_capabilities: int = 0
    capabilities_with_metadata: int = 0
    capabilities_with_handlers: int = 0

    def add_error(self, error: ValidationError) -> None:
        """エラーを追加"""
        if error.severity == "error":
            self.errors.append(error)
            self.is_valid = False
        elif error.severity == "warning":
            self.warnings.append(error)
        else:
            self.info.append(error)

    def summary(self) -> str:
        """結果のサマリーを返す"""
        parts = [
            f"Validation {'PASSED' if self.is_valid else 'FAILED'}:",
            f"  - Total capabilities: {self.total_capabilities}",
            f"  - Enabled: {self.enabled_capabilities}",
            f"  - With brain_metadata: {self.capabilities_with_metadata}",
            f"  - With handlers: {self.capabilities_with_handlers}",
        ]

        if self.errors:
            parts.append(f"  - Errors: {len(self.errors)}")
        if self.warnings:
            parts.append(f"  - Warnings: {len(self.warnings)}")
        if self.info:
            parts.append(f"  - Info: {len(self.info)}")

        return "\n".join(parts)


# =============================================================================
# brain_metadataの期待される構造
# =============================================================================


BRAIN_METADATA_SCHEMA = {
    "decision_keywords": {
        "required": False,  # 設定を推奨するが必須ではない
        "type": "dict",
        "fields": {
            "primary": {"type": "list", "item_type": "str"},
            "secondary": {"type": "list", "item_type": "str"},
            "negative": {"type": "list", "item_type": "str"},
        },
    },
    "intent_keywords": {
        "required": False,
        "type": "dict",
        "fields": {
            "primary": {"type": "list", "item_type": "str"},
            "secondary": {"type": "list", "item_type": "str"},
            "modifiers": {"type": "list", "item_type": "str"},
            "negative": {"type": "list", "item_type": "str"},
            "confidence_boost": {"type": "float", "min": 0.0, "max": 1.0},
        },
    },
    "risk_level": {
        "required": False,
        "type": "str",
        "allowed_values": ["low", "medium", "high"],
    },
    "priority": {
        "required": False,
        "type": "int",
        "min": 1,
        "max": 10,
    },
}


# =============================================================================
# バリデーション関数
# =============================================================================


def validate_brain_metadata(
    action: str,
    metadata: Dict[str, Any],
) -> List[ValidationError]:
    """
    brain_metadataの構造を検証

    Args:
        action: アクション名
        metadata: brain_metadataの内容

    Returns:
        List[ValidationError]: 検出されたエラーのリスト
    """
    errors = []

    for field_name, field_schema in BRAIN_METADATA_SCHEMA.items():
        value = metadata.get(field_name)

        # 必須フィールドのチェック
        if field_schema.get("required", False) and value is None:
            errors.append(ValidationError(
                action=action,
                error_type="missing_required_field",
                message=f"Required field '{field_name}' is missing in brain_metadata",
                severity="error",
            ))
            continue

        if value is None:
            continue

        # 型チェック
        expected_type = field_schema.get("type")
        if expected_type == "dict" and not isinstance(value, dict):
            errors.append(ValidationError(
                action=action,
                error_type="invalid_type",
                message=f"Field '{field_name}' should be dict, got {type(value).__name__}",
                severity="error",
            ))
        elif expected_type == "str" and not isinstance(value, str):
            errors.append(ValidationError(
                action=action,
                error_type="invalid_type",
                message=f"Field '{field_name}' should be str, got {type(value).__name__}",
                severity="error",
            ))
        elif expected_type == "int" and not isinstance(value, int):
            errors.append(ValidationError(
                action=action,
                error_type="invalid_type",
                message=f"Field '{field_name}' should be int, got {type(value).__name__}",
                severity="error",
            ))
        elif expected_type == "float" and not isinstance(value, (int, float)):
            errors.append(ValidationError(
                action=action,
                error_type="invalid_type",
                message=f"Field '{field_name}' should be float, got {type(value).__name__}",
                severity="error",
            ))

        # 許可された値のチェック
        allowed_values_raw = field_schema.get("allowed_values")
        allowed_values: Optional[List[Any]] = allowed_values_raw if isinstance(allowed_values_raw, list) else None
        if allowed_values and value not in allowed_values:
            errors.append(ValidationError(
                action=action,
                error_type="invalid_value",
                message=f"Field '{field_name}' has invalid value '{value}'. Allowed: {allowed_values}",
                severity="error",
            ))

        # 数値範囲のチェック
        if isinstance(value, (int, float)):
            min_val_raw = field_schema.get("min")
            max_val_raw = field_schema.get("max")
            min_val: Optional[float] = float(min_val_raw) if isinstance(min_val_raw, (int, float)) else None
            max_val: Optional[float] = float(max_val_raw) if isinstance(max_val_raw, (int, float)) else None
            if min_val is not None and value < min_val:
                errors.append(ValidationError(
                    action=action,
                    error_type="value_out_of_range",
                    message=f"Field '{field_name}' value {value} is less than minimum {min_val}",
                    severity="warning",
                ))
            if max_val is not None and value > max_val:
                errors.append(ValidationError(
                    action=action,
                    error_type="value_out_of_range",
                    message=f"Field '{field_name}' value {value} is greater than maximum {max_val}",
                    severity="warning",
                ))

        # ネストされたフィールドのチェック
        nested_fields_raw = field_schema.get("fields")
        nested_fields: Optional[Dict[str, Any]] = nested_fields_raw if isinstance(nested_fields_raw, dict) else None
        if nested_fields and isinstance(value, dict):
            for nested_name, nested_schema in nested_fields.items():
                nested_value = value.get(nested_name)
                if nested_value is not None:
                    expected_nested_type = nested_schema.get("type")

                    # 型チェック
                    if expected_nested_type == "list" and not isinstance(nested_value, list):
                        errors.append(ValidationError(
                            action=action,
                            error_type="invalid_nested_type",
                            message=f"Field '{field_name}.{nested_name}' should be list",
                            severity="error",
                        ))
                    elif expected_nested_type == "float" and not isinstance(nested_value, (int, float)):
                        errors.append(ValidationError(
                            action=action,
                            error_type="invalid_nested_type",
                            message=f"Field '{field_name}.{nested_name}' should be float",
                            severity="error",
                        ))

                    # 数値範囲チェック（ネストされたフィールド用）
                    if isinstance(nested_value, (int, float)):
                        nested_min_raw = nested_schema.get("min")
                        nested_max_raw = nested_schema.get("max")
                        nested_min: Optional[float] = float(nested_min_raw) if isinstance(nested_min_raw, (int, float)) else None
                        nested_max: Optional[float] = float(nested_max_raw) if isinstance(nested_max_raw, (int, float)) else None
                        if nested_min is not None and nested_value < nested_min:
                            errors.append(ValidationError(
                                action=action,
                                error_type="value_out_of_range",
                                message=f"Field '{field_name}.{nested_name}' value {nested_value} "
                                        f"is less than minimum {nested_min}",
                                severity="warning",
                            ))
                        if nested_max is not None and nested_value > nested_max:
                            errors.append(ValidationError(
                                action=action,
                                error_type="value_out_of_range",
                                message=f"Field '{field_name}.{nested_name}' value {nested_value} "
                                        f"is greater than maximum {nested_max}",
                                severity="warning",
                            ))

    return errors


def validate_capabilities_handlers(
    capabilities: Dict[str, Dict],
    handlers: Optional[Dict[str, Any]] = None,
    strict: bool = False,
) -> ValidationResult:
    """
    SYSTEM_CAPABILITIESとハンドラーの整合性をチェック

    設計書7.3準拠: SYSTEM_CAPABILITIESにbrain_metadataが含まれているかを検証。
    新機能追加時にSYSTEM_CAPABILITIESへの追加のみで対応可能かを確認する。

    Args:
        capabilities: SYSTEM_CAPABILITIES辞書
        handlers: ハンドラー辞書（オプション）
        strict: 厳格モード（brain_metadataがないアクションをエラーにする）

    Returns:
        ValidationResult: 検証結果

    使用例:
        from lib.brain.validation import validate_capabilities_handlers

        result = validate_capabilities_handlers(
            capabilities=SYSTEM_CAPABILITIES,
            handlers=handlers,
            strict=False,
        )

        if not result.is_valid:
            for error in result.errors:
                print(f"ERROR: {error.action}: {error.message}")

        print(result.summary())
    """
    result = ValidationResult()
    result.total_capabilities = len(capabilities)

    # 有効な機能をカウント
    enabled_actions: Set[str] = set()
    for action, cap in capabilities.items():
        if cap.get("enabled", True):
            enabled_actions.add(action)
    result.enabled_capabilities = len(enabled_actions)

    # 各アクションを検証
    for action, cap in capabilities.items():
        is_enabled = cap.get("enabled", True)

        if not is_enabled:
            # 無効化されているアクションはスキップ
            continue

        # brain_metadataの存在チェック
        brain_metadata = cap.get("brain_metadata")

        if brain_metadata:
            result.capabilities_with_metadata += 1

            # brain_metadataの構造を検証
            metadata_errors = validate_brain_metadata(action, brain_metadata)
            for error in metadata_errors:
                result.add_error(error)
        else:
            # brain_metadataがないアクション
            severity = "error" if strict else "warning"
            result.add_error(ValidationError(
                action=action,
                error_type="missing_brain_metadata",
                message=f"Action '{action}' is missing brain_metadata. "
                        "Consider adding brain_metadata for better intent detection.",
                severity=severity,
            ))

        # ハンドラーの存在チェック（オプション）
        if handlers is not None:
            if action in handlers:
                result.capabilities_with_handlers += 1
            else:
                # 特殊なアクションはハンドラー不要
                special_actions = {
                    "general_conversation",
                    "api_limitation",
                }
                if action not in special_actions:
                    result.add_error(ValidationError(
                        action=action,
                        error_type="missing_handler",
                        message=f"Action '{action}' is defined in capabilities but has no handler",
                        severity="warning",
                    ))

    # ハンドラーがあるがcapabilitiesにないアクションをチェック
    if handlers is not None:
        for handler_action in handlers.keys():
            if handler_action not in capabilities:
                result.add_error(ValidationError(
                    action=handler_action,
                    error_type="orphan_handler",
                    message=f"Handler '{handler_action}' exists but is not defined in capabilities",
                    severity="warning",
                ))

    # 結果をログ出力
    logger.info(result.summary())

    if result.errors:
        for error in result.errors:
            logger.error(f"Validation error: {error.action}: {error.message}")

    if result.warnings:
        for warning in result.warnings:
            logger.warning(f"Validation warning: {warning.action}: {warning.message}")

    return result


def check_capabilities_coverage(
    capabilities: Dict[str, Dict],
) -> Dict[str, Any]:
    """
    SYSTEM_CAPABILITIESのbrain_metadataカバレッジを計算

    Args:
        capabilities: SYSTEM_CAPABILITIES辞書

    Returns:
        Dict[str, Any]: カバレッジ情報

    使用例:
        coverage = check_capabilities_coverage(SYSTEM_CAPABILITIES)
        print(f"Coverage: {coverage['percentage']:.1f}%")
    """
    total_enabled = 0
    with_decision_keywords = 0
    with_intent_keywords = 0
    with_risk_level = 0
    with_priority = 0
    missing_metadata = []

    for action, cap in capabilities.items():
        if not cap.get("enabled", True):
            continue

        total_enabled += 1
        brain_metadata = cap.get("brain_metadata", {})

        if not brain_metadata:
            missing_metadata.append(action)
            continue

        if brain_metadata.get("decision_keywords"):
            with_decision_keywords += 1
        if brain_metadata.get("intent_keywords"):
            with_intent_keywords += 1
        if brain_metadata.get("risk_level"):
            with_risk_level += 1
        if brain_metadata.get("priority"):
            with_priority += 1

    percentage = ((total_enabled - len(missing_metadata)) / total_enabled * 100) if total_enabled > 0 else 0

    return {
        "total_enabled": total_enabled,
        "with_brain_metadata": total_enabled - len(missing_metadata),
        "with_decision_keywords": with_decision_keywords,
        "with_intent_keywords": with_intent_keywords,
        "with_risk_level": with_risk_level,
        "with_priority": with_priority,
        "missing_metadata": missing_metadata,
        "percentage": percentage,
    }
