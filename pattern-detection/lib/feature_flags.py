"""
Feature Flags 一元管理モジュール (v10.31.0)

Phase C: 15+個のFeature Flagを1つのファイルに集約

設計書: docs/14_brain_refactoring_plan.md

使用例:
    from lib.feature_flags import flags, FeatureFlags

    # 基本的な使い方
    if flags.use_brain_architecture:
        brain.process(message)

    # フラグの一覧表示
    flags.print_status()

    # 特定カテゴリのフラグ取得
    handler_flags = flags.get_handler_flags()

作成日: 2026-01-26
作成者: Claude Code
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Tuple
from functools import cached_property
import json


# =====================================================
# 定数定義
# =====================================================

class FlagCategory(str, Enum):
    """Feature Flagのカテゴリ"""
    HANDLER = "handler"           # ハンドラー系（proposal, task, memory等）
    LIBRARY = "library"           # ライブラリ系（text_utils, user_utils等）
    FEATURE = "feature"           # 機能系（brain, announcement, mvv等）
    DETECTION = "detection"       # 検出系（pattern, emotion等）
    INFRASTRUCTURE = "infra"      # インフラ系（dry_run, department_access等）


class FlagType(str, Enum):
    """Feature Flagの決定タイプ"""
    ENV_ONLY = "env_only"                  # 環境変数のみで決定
    IMPORT_ONLY = "import_only"            # インポート成否のみで決定
    ENV_AND_IMPORT = "env_and_import"      # 環境変数チェック後、インポート成否で決定
    COMPLEX = "complex"                    # 複雑なロジック（モード等）


# 環境変数名 → (デフォルト値, カテゴリ, 説明)
FLAG_DEFINITIONS: Dict[str, Tuple[str, FlagCategory, str]] = {
    # ハンドラー系 (デフォルト: true)
    "USE_NEW_PROPOSAL_HANDLER": ("true", FlagCategory.HANDLER, "提案管理ハンドラー"),
    "USE_NEW_MEMORY_HANDLER": ("true", FlagCategory.HANDLER, "メモリ管理ハンドラー"),
    "USE_NEW_TASK_HANDLER": ("true", FlagCategory.HANDLER, "タスク管理ハンドラー"),
    "USE_NEW_OVERDUE_HANDLER": ("true", FlagCategory.HANDLER, "遅延管理ハンドラー"),
    "USE_NEW_GOAL_HANDLER": ("true", FlagCategory.HANDLER, "目標達成支援ハンドラー"),
    "USE_NEW_KNOWLEDGE_HANDLER": ("true", FlagCategory.HANDLER, "ナレッジ管理ハンドラー"),

    # ユーティリティ系 (デフォルト: true)
    "USE_NEW_DATE_UTILS": ("true", FlagCategory.LIBRARY, "日付処理ユーティリティ"),
    "USE_NEW_CHATWORK_UTILS": ("true", FlagCategory.LIBRARY, "ChatWork APIユーティリティ"),

    # 機能系
    "USE_ANNOUNCEMENT_FEATURE": ("true", FlagCategory.FEATURE, "アナウンス機能"),
    "USE_BRAIN_ARCHITECTURE": ("false", FlagCategory.FEATURE, "脳アーキテクチャ"),
    "DISABLE_MVV_CONTEXT": ("false", FlagCategory.FEATURE, "MVV無効化フラグ"),
    "ENABLE_PHASE3_KNOWLEDGE": ("true", FlagCategory.FEATURE, "Phase 3 ナレッジ検索"),

    # 検出系
    "USE_DYNAMIC_DEPARTMENT_MAPPING": ("true", FlagCategory.DETECTION, "動的部署マッピング"),
    "ENABLE_UNMATCHED_FOLDER_ALERT": ("true", FlagCategory.DETECTION, "未マッチフォルダアラート"),

    # インフラ系
    "DRY_RUN": ("false", FlagCategory.INFRASTRUCTURE, "テストモード（送信なし）"),
    "ENABLE_DEPARTMENT_ACCESS_CONTROL": ("false", FlagCategory.INFRASTRUCTURE, "部署アクセス制御"),
}


# =====================================================
# データクラス定義
# =====================================================

@dataclass
class FlagInfo:
    """個別フラグの情報"""
    name: str
    value: bool
    env_name: str
    default: str
    category: FlagCategory
    description: str
    flag_type: FlagType
    import_available: Optional[bool] = None  # インポート系のみ
    mode: Optional[str] = None  # モードがある場合（brain等）


@dataclass(frozen=False)
class FeatureFlags:
    """
    Feature Flags 一元管理クラス

    全てのFeature Flagをこのクラスで管理し、
    散在していたフラグを一箇所に集約する。

    Attributes:
        # ハンドラー系
        use_new_proposal_handler: 提案管理ハンドラー使用
        use_new_memory_handler: メモリ管理ハンドラー使用
        use_new_task_handler: タスク管理ハンドラー使用
        use_new_overdue_handler: 遅延管理ハンドラー使用
        use_new_goal_handler: 目標達成支援ハンドラー使用
        use_new_knowledge_handler: ナレッジ管理ハンドラー使用

        # ライブラリ系
        use_admin_config: 管理者設定ライブラリ使用
        use_text_utils: テキスト処理ライブラリ使用
        use_user_utils: ユーザーユーティリティ使用
        use_business_day: 営業日判定ライブラリ使用
        use_goal_setting: 目標設定ライブラリ使用
        use_memory_framework: Memory Framework使用
        use_mvv_context: MVVコンテキスト使用
        use_new_date_utils: 日付処理ユーティリティ使用
        use_new_chatwork_utils: ChatWork APIユーティリティ使用

        # 機能系
        use_announcement_feature: アナウンス機能使用
        use_brain_architecture: 脳アーキテクチャ使用
        brain_mode: 脳アーキテクチャのモード
        enable_phase3_knowledge: Phase 3 ナレッジ検索有効

        # 検出系
        use_dynamic_department_mapping: 動的部署マッピング使用
        enable_unmatched_folder_alert: 未マッチフォルダアラート有効

        # インフラ系
        dry_run: テストモード（実際に送信しない）
        enable_department_access_control: 部署アクセス制御有効
    """

    # =====================================================
    # ハンドラー系（環境変数+インポート）
    # =====================================================
    use_new_proposal_handler: bool = field(default=True)
    use_new_memory_handler: bool = field(default=True)
    use_new_task_handler: bool = field(default=True)
    use_new_overdue_handler: bool = field(default=True)
    use_new_goal_handler: bool = field(default=True)
    use_new_knowledge_handler: bool = field(default=True)

    # =====================================================
    # ライブラリ系（インポート成否で決定）
    # =====================================================
    use_admin_config: bool = field(default=False)
    use_text_utils: bool = field(default=False)
    use_user_utils: bool = field(default=False)
    use_business_day: bool = field(default=False)
    use_goal_setting: bool = field(default=False)
    use_memory_framework: bool = field(default=False)
    use_mvv_context: bool = field(default=False)
    use_new_date_utils: bool = field(default=True)
    use_new_chatwork_utils: bool = field(default=True)

    # =====================================================
    # 機能系
    # =====================================================
    use_announcement_feature: bool = field(default=True)
    use_brain_architecture: bool = field(default=False)
    brain_mode: str = field(default="false")  # false, true, shadow, gradual
    enable_phase3_knowledge: bool = field(default=True)

    # =====================================================
    # 検出系
    # =====================================================
    use_dynamic_department_mapping: bool = field(default=True)
    enable_unmatched_folder_alert: bool = field(default=True)

    # =====================================================
    # インフラ系
    # =====================================================
    dry_run: bool = field(default=False)
    enable_department_access_control: bool = field(default=False)

    # =====================================================
    # 内部状態（インポート成否の追跡用）
    # =====================================================
    _import_results: Dict[str, bool] = field(default_factory=dict, repr=False)
    _env_overrides: Dict[str, bool] = field(default_factory=dict, repr=False)
    _initialized: bool = field(default=False, repr=False)

    # =====================================================
    # クラスメソッド
    # =====================================================

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        """
        環境変数からFeatureFlagsを構築

        インポート成否はこの時点では判定せず、
        環境変数のみで初期値を設定する。

        Returns:
            FeatureFlags: 環境変数から構築されたインスタンス
        """
        instance = cls()
        instance._load_from_env()
        instance._initialized = True
        return instance

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FeatureFlags":
        """
        辞書からFeatureFlagsを構築（テスト用）

        Args:
            data: フラグ名→値の辞書

        Returns:
            FeatureFlags: 辞書から構築されたインスタンス
        """
        instance = cls()
        for key, value in data.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        instance._initialized = True
        return instance

    # =====================================================
    # 環境変数読み込み
    # =====================================================

    def _load_from_env(self) -> None:
        """環境変数からフラグ値を読み込む"""

        # ハンドラー系（デフォルト: true）
        self.use_new_proposal_handler = self._get_env_bool(
            "USE_NEW_PROPOSAL_HANDLER", True
        )
        self.use_new_memory_handler = self._get_env_bool(
            "USE_NEW_MEMORY_HANDLER", True
        )
        self.use_new_task_handler = self._get_env_bool(
            "USE_NEW_TASK_HANDLER", True
        )
        self.use_new_overdue_handler = self._get_env_bool(
            "USE_NEW_OVERDUE_HANDLER", True
        )
        self.use_new_goal_handler = self._get_env_bool(
            "USE_NEW_GOAL_HANDLER", True
        )
        self.use_new_knowledge_handler = self._get_env_bool(
            "USE_NEW_KNOWLEDGE_HANDLER", True
        )

        # ユーティリティ系
        self.use_new_date_utils = self._get_env_bool(
            "USE_NEW_DATE_UTILS", True
        )
        self.use_new_chatwork_utils = self._get_env_bool(
            "USE_NEW_CHATWORK_UTILS", True
        )

        # 機能系
        self.use_announcement_feature = self._get_env_bool(
            "USE_ANNOUNCEMENT_FEATURE", True
        )

        # 脳アーキテクチャ（特殊: モード対応）
        brain_mode_str = os.environ.get("USE_BRAIN_ARCHITECTURE", "false").lower()
        self.brain_mode = brain_mode_str
        self.use_brain_architecture = brain_mode_str in ("true", "shadow", "gradual")

        # MVV（特殊: DISABLE_で無効化）
        mvv_disabled = self._get_env_bool("DISABLE_MVV_CONTEXT", False)
        if mvv_disabled:
            self.use_mvv_context = False
            self._env_overrides["use_mvv_context"] = False
        # インポート成否は後で設定

        # Phase 3 ナレッジ
        self.enable_phase3_knowledge = self._get_env_bool(
            "ENABLE_PHASE3_KNOWLEDGE", True
        )

        # 検出系
        self.use_dynamic_department_mapping = self._get_env_bool(
            "USE_DYNAMIC_DEPARTMENT_MAPPING", True
        )
        self.enable_unmatched_folder_alert = self._get_env_bool(
            "ENABLE_UNMATCHED_FOLDER_ALERT", True
        )

        # インフラ系
        self.dry_run = self._get_env_bool("DRY_RUN", False)
        self.enable_department_access_control = self._get_env_bool(
            "ENABLE_DEPARTMENT_ACCESS_CONTROL", False
        )

    def _get_env_bool(self, key: str, default: bool) -> bool:
        """環境変数からbool値を取得"""
        value = os.environ.get(key, "").lower()
        if value in ("true", "1", "yes"):
            return True
        elif value in ("false", "0", "no"):
            return False
        return default

    # =====================================================
    # インポート結果の設定（main.py等から呼び出す）
    # =====================================================

    def set_import_result(self, flag_name: str, available: bool) -> None:
        """
        インポート結果を設定

        Args:
            flag_name: フラグ名（例: "use_admin_config"）
            available: インポートが成功したか
        """
        self._import_results[flag_name] = available

        # 環境変数で無効化されていなければ、インポート結果を反映
        if flag_name not in self._env_overrides or self._env_overrides[flag_name]:
            if hasattr(self, flag_name):
                setattr(self, flag_name, available)

    def set_import_results(self, results: Dict[str, bool]) -> None:
        """
        複数のインポート結果を一括設定

        Args:
            results: フラグ名→インポート成否の辞書
        """
        for flag_name, available in results.items():
            self.set_import_result(flag_name, available)

    # =====================================================
    # フラグ取得ユーティリティ
    # =====================================================

    def get_handler_flags(self) -> Dict[str, bool]:
        """ハンドラー系フラグを取得"""
        return {
            "use_new_proposal_handler": self.use_new_proposal_handler,
            "use_new_memory_handler": self.use_new_memory_handler,
            "use_new_task_handler": self.use_new_task_handler,
            "use_new_overdue_handler": self.use_new_overdue_handler,
            "use_new_goal_handler": self.use_new_goal_handler,
            "use_new_knowledge_handler": self.use_new_knowledge_handler,
        }

    def get_library_flags(self) -> Dict[str, bool]:
        """ライブラリ系フラグを取得"""
        return {
            "use_admin_config": self.use_admin_config,
            "use_text_utils": self.use_text_utils,
            "use_user_utils": self.use_user_utils,
            "use_business_day": self.use_business_day,
            "use_goal_setting": self.use_goal_setting,
            "use_memory_framework": self.use_memory_framework,
            "use_mvv_context": self.use_mvv_context,
            "use_new_date_utils": self.use_new_date_utils,
            "use_new_chatwork_utils": self.use_new_chatwork_utils,
        }

    def get_feature_flags(self) -> Dict[str, Any]:
        """機能系フラグを取得"""
        return {
            "use_announcement_feature": self.use_announcement_feature,
            "use_brain_architecture": self.use_brain_architecture,
            "brain_mode": self.brain_mode,
            "enable_phase3_knowledge": self.enable_phase3_knowledge,
        }

    def get_detection_flags(self) -> Dict[str, bool]:
        """検出系フラグを取得"""
        return {
            "use_dynamic_department_mapping": self.use_dynamic_department_mapping,
            "enable_unmatched_folder_alert": self.enable_unmatched_folder_alert,
        }

    def get_infra_flags(self) -> Dict[str, bool]:
        """インフラ系フラグを取得"""
        return {
            "dry_run": self.dry_run,
            "enable_department_access_control": self.enable_department_access_control,
        }

    def get_all_flags(self) -> Dict[str, Any]:
        """全フラグを取得"""
        result = {}
        result.update(self.get_handler_flags())
        result.update(self.get_library_flags())
        result.update(self.get_feature_flags())
        result.update(self.get_detection_flags())
        result.update(self.get_infra_flags())
        return result

    def get_enabled_count(self) -> Tuple[int, int]:
        """有効なフラグ数と総数を取得"""
        all_flags = self.get_all_flags()
        # brain_modeは文字列なので除外
        bool_flags = {k: v for k, v in all_flags.items() if isinstance(v, bool)}
        enabled = sum(1 for v in bool_flags.values() if v)
        return enabled, len(bool_flags)

    # =====================================================
    # 表示・デバッグ
    # =====================================================

    def print_status(self) -> None:
        """フラグの状態をコンソールに表示"""
        print("=" * 60)
        print("Feature Flags Status")
        print("=" * 60)

        sections = [
            ("Handler Flags", self.get_handler_flags()),
            ("Library Flags", self.get_library_flags()),
            ("Feature Flags", self.get_feature_flags()),
            ("Detection Flags", self.get_detection_flags()),
            ("Infrastructure Flags", self.get_infra_flags()),
        ]

        for section_name, flags in sections:
            print(f"\n{section_name}:")
            print("-" * 40)
            for name, value in flags.items():
                status = "✅" if value else "❌"
                print(f"  {status} {name}: {value}")

        enabled, total = self.get_enabled_count()
        print(f"\nTotal: {enabled}/{total} enabled")
        print("=" * 60)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で出力"""
        return self.get_all_flags()

    def to_json(self, indent: int = 2) -> str:
        """JSON形式で出力"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def __repr__(self) -> str:
        enabled, total = self.get_enabled_count()
        return f"FeatureFlags({enabled}/{total} enabled)"


# =====================================================
# シングルトンインスタンス
# =====================================================

# グローバルインスタンス（遅延初期化）
_flags_instance: Optional[FeatureFlags] = None


def get_flags() -> FeatureFlags:
    """
    Feature Flagsのシングルトンインスタンスを取得

    Returns:
        FeatureFlags: グローバルインスタンス
    """
    global _flags_instance
    if _flags_instance is None:
        _flags_instance = FeatureFlags.from_env()
    return _flags_instance


def reset_flags() -> None:
    """
    Feature Flagsをリセット（テスト用）
    """
    global _flags_instance
    _flags_instance = None


def init_flags(custom_flags: Optional[Dict[str, Any]] = None) -> FeatureFlags:
    """
    Feature Flagsを初期化

    Args:
        custom_flags: カスタムフラグ値（テスト用）

    Returns:
        FeatureFlags: 初期化されたインスタンス
    """
    global _flags_instance
    if custom_flags:
        _flags_instance = FeatureFlags.from_dict(custom_flags)
    else:
        _flags_instance = FeatureFlags.from_env()
    return _flags_instance


# 便利なエイリアス
flags = property(lambda self: get_flags())


# =====================================================
# 後方互換性のためのヘルパー関数
# =====================================================

def is_handler_enabled(handler_name: str) -> bool:
    """
    特定のハンドラーが有効かチェック

    Args:
        handler_name: ハンドラー名（例: "proposal", "task"）

    Returns:
        bool: ハンドラーが有効か
    """
    flag_name = f"use_new_{handler_name}_handler"
    return getattr(get_flags(), flag_name, False)


def is_library_available(lib_name: str) -> bool:
    """
    特定のライブラリが利用可能かチェック

    Args:
        lib_name: ライブラリ名（例: "text_utils", "admin_config"）

    Returns:
        bool: ライブラリが利用可能か
    """
    flag_name = f"use_{lib_name}"
    return getattr(get_flags(), flag_name, False)


def is_feature_enabled(feature_name: str) -> bool:
    """
    特定の機能が有効かチェック

    Args:
        feature_name: 機能名（例: "brain_architecture", "announcement_feature"）

    Returns:
        bool: 機能が有効か
    """
    flag_name = f"use_{feature_name}"
    if hasattr(get_flags(), flag_name):
        return getattr(get_flags(), flag_name, False)

    flag_name = f"enable_{feature_name}"
    return getattr(get_flags(), flag_name, False)


def get_brain_mode() -> str:
    """
    脳アーキテクチャのモードを取得

    Returns:
        str: モード（"false", "true", "shadow", "gradual"）
    """
    return get_flags().brain_mode


def is_dry_run() -> bool:
    """
    DRY_RUNモードかチェック

    Returns:
        bool: DRY_RUNモードか
    """
    return get_flags().dry_run


# =====================================================
# エクスポート
# =====================================================

__all__ = [
    # クラス
    "FeatureFlags",
    "FlagCategory",
    "FlagType",
    "FlagInfo",

    # 定数
    "FLAG_DEFINITIONS",

    # 関数
    "get_flags",
    "reset_flags",
    "init_flags",

    # ヘルパー
    "is_handler_enabled",
    "is_library_available",
    "is_feature_enabled",
    "get_brain_mode",
    "is_dry_run",
]
