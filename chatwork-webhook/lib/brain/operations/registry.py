# lib/brain/operations/registry.py
"""
操作レジストリ — Step C-1: 事前登録方式の操作管理

ソウルくんが実行可能な「操作メニュー」を管理する。
レジストリに登録されていない操作は実行不可。

【設計原則】
- 全操作はPython関数として事前定義・レビュー済み
- シェルコマンドの直接実行は行わない
- パラメータは型付きスキーマで検証
- 出力は10KB上限、30秒タイムアウト
- CLAUDE.md §1: 全入出力はBrainを通る

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypedDict

logger = logging.getLogger(__name__)


# =============================================================================
# CapabilityContract — 全Capabilityが満たすべき契約インターフェース（TASK-14）
# =============================================================================


class CapabilityContract(TypedDict, total=False):
    """
    Capability定義の標準契約インターフェース

    SYSTEM_CAPABILITIES（handlers/registry.py）と OPERATION_CAPABILITIES の
    両方がこの契約を満たすことを保証する。

    【必須フィールド】
    - name:                 機能名（日本語表示）
    - description:          AIが読む機能説明（意図理解・Tool選択に使われる）
    - category:             カテゴリ（task/goal/operations/message 等）
    - enabled:              有効/無効フラグ（False のものはBrainに渡さない）
    - params_schema:        パラメータスキーマ（各パラメータのtype/required/description）
    - handler:              ハンドラー名（HANDLERS辞書のキー）
    - requires_confirmation: 確認ダイアログが必要か

    【任意フィールド】
    - trigger_examples:     トリガー例（AIの意図理解精度向上）
    - required_data:        実行に必要なデータソース名のリスト
    - brain_metadata:       脳アーキテクチャ用メタデータ（risk_level/intent_keywords）
    - required_level:       必要な権限レベル（1〜6、デフォルト:1）

    【新機能追加手順】
    1. handlers/xxx_handler.py を作成（ChatWork系）
       または lib/brain/operations/data_ops.py 等を更新（データ操作系）
    2. OPERATION_CAPABILITIES または SYSTEM_CAPABILITIES に CapabilityContract を1エントリ追加
    3. HANDLERS dict に関数を登録
    4. main.py は変更不要（ToolMetadataRegistry が自動ロード）

    設計書: CLAUDE.md §1（脳がすべて）、§8（権限レベル）
    """
    # 必須フィールド（required=True は呼び出し元で validate_capability_contract() を使い保証）
    name: str
    description: str
    category: str
    enabled: bool
    params_schema: Dict[str, Any]
    handler: str
    requires_confirmation: bool
    # 任意フィールド
    trigger_examples: List[str]
    required_data: List[str]
    brain_metadata: Dict[str, Any]
    required_level: int


# 必須フィールド一覧（validate_capability_contract() で使用）
REQUIRED_CAPABILITY_FIELDS: tuple = (
    "name",
    "description",
    "category",
    "enabled",
    "params_schema",
    "handler",
    "requires_confirmation",
)


def validate_capability_contract(
    cap_name: str,
    cap: Dict[str, Any],
) -> Optional[str]:
    """
    Capability定義が CapabilityContract 契約を満たしているか検証する。

    新機能追加時・テストで呼び出して、必須フィールドの漏れを早期に検出する。

    Args:
        cap_name: Capability名（エラーメッセージ用、例: "data_aggregate"）
        cap:      Capability定義 dict

    Returns:
        契約違反がある場合はエラーメッセージ文字列。
        問題なければ None。

    Example:
        error = validate_capability_contract("my_new_cap", my_cap_def)
        if error:
            raise ValueError(f"Capability契約違反: {error}")
    """
    for required_field in REQUIRED_CAPABILITY_FIELDS:
        if required_field not in cap:
            return (
                f"Capability '{cap_name}' は必須フィールド '{required_field}' が不足しています。"
                f" CapabilityContract の必須フィールド: {REQUIRED_CAPABILITY_FIELDS}"
            )
    return None


# 操作の制約
OPERATION_TIMEOUT_SECONDS = 30
OPERATION_MAX_OUTPUT_BYTES = 10 * 1024  # 10KB
OPERATION_DAILY_QUOTA_READ = 50
OPERATION_DAILY_QUOTA_WRITE = 20
OPERATION_RATE_LIMIT_PER_MINUTE = 5
OPERATION_BURST_LIMIT_PER_10SEC = 3


@dataclass
class OperationResult:
    """操作の実行結果"""

    success: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    execution_time_ms: int = 0
    truncated: bool = False


@dataclass
class OperationDefinition:
    """操作の定義"""

    name: str
    description: str
    handler: Callable
    risk_level: str  # "low", "medium", "high"
    requires_confirmation: bool
    category: str  # "read", "write"
    params_schema: Dict[str, Any] = field(default_factory=dict)


# 操作レジストリ（登録済み操作の一覧）
_registry: Dict[str, OperationDefinition] = {}


def register_operation(definition: OperationDefinition) -> None:
    """操作をレジストリに登録する"""
    if definition.name in _registry:
        logger.warning(f"操作 '{definition.name}' は既に登録済み。上書きします。")
    _registry[definition.name] = definition
    logger.info(f"操作登録: {definition.name} (risk={definition.risk_level}, category={definition.category})")


def get_operation(name: str) -> Optional[OperationDefinition]:
    """レジストリから操作を取得する"""
    return _registry.get(name)


def is_registered(name: str) -> bool:
    """操作が登録済みかチェックする"""
    return name in _registry


def list_operations(category: Optional[str] = None) -> List[str]:
    """登録済み操作名の一覧を返す"""
    if category:
        return [name for name, op in _registry.items() if op.category == category]
    return list(_registry.keys())


def validate_params(name: str, params: Dict[str, Any]) -> Optional[str]:
    """
    パラメータをスキーマに基づいて検証する。

    Returns:
        エラーメッセージ。問題なければNone。
    """
    op = get_operation(name)
    if op is None:
        return f"未登録の操作: {name}"

    schema = op.params_schema
    for param_name, param_def in schema.items():
        is_required = param_def.get("required", False)
        if is_required and param_name not in params:
            return f"必須パラメータ '{param_name}' が不足しています"

        if param_name in params:
            value = params[param_name]
            expected_type = param_def.get("type", "string")

            # パストラバーサル検証
            if expected_type == "string" and isinstance(value, str):
                if ".." in value or value.startswith("/"):
                    return f"パラメータ '{param_name}' に不正なパスが含まれています"

            # 長さ制限（200文字）
            if isinstance(value, str) and len(value) > 200:
                return f"パラメータ '{param_name}' が長すぎます（最大200文字）"

    return None


async def execute_operation(
    name: str,
    params: Dict[str, Any],
    organization_id: str,
    account_id: str,
) -> OperationResult:
    """
    登録済み操作を実行する。

    タイムアウト・出力サイズ制限を適用。

    Args:
        name: 操作名
        params: パラメータ
        organization_id: 組織ID（CLAUDE.md §3 鉄則#1）
        account_id: 実行者のアカウントID

    Returns:
        OperationResult
    """
    # 1. レジストリチェック
    op = get_operation(name)
    if op is None:
        return OperationResult(
            success=False,
            message=f"未登録の操作です: {name}",
        )

    # 2. パラメータ検証
    error = validate_params(name, params)
    if error:
        return OperationResult(
            success=False,
            message=f"パラメータエラー: {error}",
        )

    # 3. 実行（タイムアウト付き）
    start_time = time.monotonic()
    try:
        result = await asyncio.wait_for(
            op.handler(
                params=params,
                organization_id=organization_id,
                account_id=account_id,
            ),
            timeout=OPERATION_TIMEOUT_SECONDS,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # OperationResult以外の戻り値を正規化
        if isinstance(result, dict):
            result = OperationResult(
                success=result.get("success", True),
                message=result.get("message", "完了"),
                data=result.get("data", result),
            )
        elif isinstance(result, str):
            result = OperationResult(success=True, message=result)

        result.execution_time_ms = elapsed_ms

        # 4. 出力サイズ制限
        output_str = str(result.data)
        if len(output_str.encode("utf-8")) > OPERATION_MAX_OUTPUT_BYTES:
            result.data = {"truncated_message": output_str[:2000] + "...（出力が10KBを超えたため切り詰めました）"}
            result.truncated = True

        return result

    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.warning(f"操作 '{name}' がタイムアウト ({OPERATION_TIMEOUT_SECONDS}秒)")
        return OperationResult(
            success=False,
            message=f"操作がタイムアウトしました（{OPERATION_TIMEOUT_SECONDS}秒制限）",
            execution_time_ms=elapsed_ms,
        )
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.error(f"操作 '{name}' でエラー: {e}", exc_info=True)
        return OperationResult(
            success=False,
            message="操作の実行中にエラーが発生しました",
            execution_time_ms=elapsed_ms,
        )


# =========================================================================
# OPERATION_CAPABILITIES — データ操作系Capability定義（CapabilityContract準拠）
#
# 新しいデータ操作系機能を追加する場合はここに CapabilityContract を追加し、
# あわせて handlers/registry.py の SYSTEM_CAPABILITIES にも同じエントリを追加する。
# ToolMetadataRegistry（lib/brain/tool_converter.py）は SYSTEM_CAPABILITIES と
# OPERATION_CAPABILITIES の両方を自動ロードするため、Brain側は変更不要。
# =========================================================================

OPERATION_CAPABILITIES: Dict[str, CapabilityContract] = {
    # -----------------------------------------------------------------
    # 読み取り系操作（Step C-2 Phase 1）
    # -----------------------------------------------------------------
    "data_aggregate": {
        "name": "データ集計",
        "description": "CSVやデータの集計・合計・平均・件数カウントなどを計算する。「売上データを合計して」「先月の件数を教えて」などに対応。",
        "category": "operations",
        "enabled": True,
        "trigger_examples": [
            "売上データを合計して",
            "先月の件数を教えて",
            "平均単価を計算して",
            "部署ごとの集計を出して",
        ],
        "params_schema": {
            "data_source": {
                "type": "string",
                "description": "集計対象のデータ名またはファイル名",
                "required": True,
                "note": "DBテーブル名、CSVファイル名、GCSパスのいずれか",
            },
            "operation": {
                "type": "string",
                "description": "集計方法（sum, avg, count, min, max, group_by）",
                "required": True,
            },
            "filters": {
                "type": "string",
                "description": "フィルタ条件（例: 「先月」「営業部」「100万以上」）",
                "required": False,
            },
        },
        "handler": "data_aggregate",
        "requires_confirmation": False,
        "required_data": [],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["集計", "合計", "平均", "カウント", "件数"],
                "secondary": ["データ", "売上", "数字", "統計"],
                "negative": ["検索", "ファイル探して", "予定"],
            },
            "intent_keywords": {
                "primary": ["データ集計", "集計して", "合計して", "平均を"],
                "secondary": ["計算", "数えて", "統計"],
                "modifiers": ["教えて", "出して", "見せて"],
                "negative": ["ファイル", "ドライブ", "カレンダー"],
                "confidence_boost": 0.80,
            },
            "risk_level": "low",
            "priority": 5,
        },
    },

    "data_search": {
        "name": "データ検索",
        "description": "データベースやCSVから条件に合うデータを検索・一覧表示する。「先月の案件一覧」「売上トップ10」などに対応。",
        "category": "operations",
        "enabled": True,
        "trigger_examples": [
            "先月の案件を一覧にして",
            "売上トップ10を見せて",
            "未完了のタスクを一覧にして",
            "今月の新規案件は？",
        ],
        "params_schema": {
            "data_source": {
                "type": "string",
                "description": "検索対象のデータ名またはテーブル名",
                "required": True,
            },
            "query": {
                "type": "string",
                "description": "検索条件（自然言語）",
                "required": True,
                "note": "ユーザーの意図を反映した検索条件を生成すること",
            },
            "limit": {
                "type": "integer",
                "description": "最大件数（デフォルト: 20）",
                "required": False,
                "default": 20,
            },
        },
        "handler": "data_search",
        "requires_confirmation": False,
        "required_data": [],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["一覧", "リスト", "トップ", "ランキング"],
                "secondary": ["データ", "案件", "見せて", "表示"],
                "negative": ["集計", "合計", "平均"],
            },
            "intent_keywords": {
                "primary": ["データ検索", "一覧にして", "リストを"],
                "secondary": ["探して", "見せて", "表示して"],
                "modifiers": ["教えて", "出して"],
                "negative": ["集計", "カレンダー"],
                "confidence_boost": 0.75,
            },
            "risk_level": "low",
            "priority": 5,
        },
    },

    # -----------------------------------------------------------------
    # 書き込み系操作（Step C-5 Phase 2）
    # -----------------------------------------------------------------
    "report_generate": {
        "name": "レポート生成",
        "description": "集計データや分析結果をレポートにまとめてGCSに保存する。",
        "category": "operations",
        "enabled": True,
        "params_schema": {
            "title": {"type": "string", "required": True},
            "content": {"type": "string", "required": True},
            "format": {"type": "string", "required": False, "default": "text"},
        },
        "handler": "report_generate",
        "requires_confirmation": True,
        "brain_metadata": {"risk_level": "medium", "priority": 5},
    },

    "csv_export": {
        "name": "CSVエクスポート",
        "description": "タスクや目標データをCSVファイルとしてGCSにエクスポートする。",
        "category": "operations",
        "enabled": True,
        "params_schema": {
            "data_source": {"type": "string", "required": True},
            "filters": {"type": "string", "required": False, "default": ""},
        },
        "handler": "csv_export",
        "requires_confirmation": True,
        "brain_metadata": {"risk_level": "medium", "priority": 5},
    },

    "file_create": {
        "name": "ファイル作成",
        "description": "テキストファイルやメモを作成してGCSに保存する。",
        "category": "operations",
        "enabled": True,
        "params_schema": {
            "filename": {"type": "string", "required": True},
            "content": {"type": "string", "required": True},
        },
        "handler": "file_create",
        "requires_confirmation": True,
        "brain_metadata": {"risk_level": "medium", "priority": 5},
    },
}
