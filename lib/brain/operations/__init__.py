# lib/brain/operations/__init__.py
"""
Step C: 安全な操作機能 — 操作レジストリ

ソウルくんに「手足」を与える操作関数パッケージ。
既存のSYSTEM_CAPABILITIESと同じパターンで、
事前登録済みのPython関数のみ実行可能。

【設計原則】
- 全操作は事前にコードレビュー済みのPython関数
- 任意のシェルコマンド実行は行わない（3AIレビューで決定）
- 既存の3層アーキテクチャ（Guardian→Approval→Authorization）をそのまま活用
- 詳細: docs/step_c_command_execution_design.md v2

Author: Claude Opus 4.6
Created: 2026-02-17
"""

from lib.brain.operations.registry import (
    OPERATION_CAPABILITIES,
    OperationResult,
    CapabilityContract,
    validate_capability_contract,
    REQUIRED_CAPABILITY_FIELDS,
)

__all__ = [
    "OPERATION_CAPABILITIES",
    "OperationResult",
    "CapabilityContract",
    "validate_capability_contract",
    "REQUIRED_CAPABILITY_FIELDS",
]
