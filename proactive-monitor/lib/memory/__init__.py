"""
Phase 2 進化版: 記憶基盤（Memory Framework）

このパッケージは、ソウルくんの「覚える能力」を提供する
記憶機能の共通基盤です。

実装済みの記憶機能:
- ConversationSummary (B1): 会話サマリー記憶
- UserPreference (B2): ユーザー嗜好学習
- AutoKnowledge (B3): 組織知識自動蓄積
- ConversationSearch (B4): 会話検索

関連するAグループ機能:
- A1 パターン検出 → B3で頻出Q&Aを自動ナレッジ化
- A4 感情変化検出 → B2で感情傾向を学習

設計書: docs/10_phase2_b_memory_framework.md

使用例:
    >>> from lib.memory import ConversationSummary, UserPreference
    >>>
    >>> # 会話サマリーを生成
    >>> summary = ConversationSummary(conn, org_id)
    >>> result = await summary.generate_and_save(user_id)
    >>>
    >>> # ユーザー嗜好を取得
    >>> pref = UserPreference(conn, org_id)
    >>> prefs = await pref.get_preferences(user_id)

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-24
Version: 1.0
"""

# ================================================================
# バージョン情報
# ================================================================

__version__ = "1.0.0"
__author__ = "Claude Code"

# ================================================================
# 定数のエクスポート
# ================================================================

from .constants import (
    # パラメータ
    MemoryParameters,
    # 嗜好タイプ
    PreferenceType,
    # ステータス
    KnowledgeStatus,
    # その他
    MessageType,
)

# ================================================================
# 例外のエクスポート
# ================================================================

from .exceptions import (
    MemoryBaseException,
    MemoryError,
    SummarySaveError,
    PreferenceSaveError,
    KnowledgeSaveError,
    SearchError,
)

# ================================================================
# 基底クラスのエクスポート
# ================================================================

from .base import (
    BaseMemory,
    MemoryResult,
)

# ================================================================
# 記憶機能のエクスポート
# ================================================================

from .conversation_summary import (
    ConversationSummary,
    SummaryData,
)

from .user_preference import (
    UserPreference,
    PreferenceData,
)

from .auto_knowledge import (
    AutoKnowledge,
    KnowledgeData,
)

from .conversation_search import (
    ConversationSearch,
    SearchResult,
)

# ================================================================
# Phase 2.5統合のエクスポート
# ================================================================

from .goal_integration import (
    GoalSettingContextEnricher,
)

# ================================================================
# __all__ 定義
# ================================================================

__all__ = [
    # バージョン
    "__version__",
    "__author__",
    # 定数
    "MemoryParameters",
    "PreferenceType",
    "KnowledgeStatus",
    "MessageType",
    # 例外
    "MemoryBaseException",
    "MemoryError",
    "SummarySaveError",
    "PreferenceSaveError",
    "KnowledgeSaveError",
    "SearchError",
    # 基底クラス
    "BaseMemory",
    "MemoryResult",
    # B1 会話サマリー
    "ConversationSummary",
    "SummaryData",
    # B2 ユーザー嗜好
    "UserPreference",
    "PreferenceData",
    # B3 組織知識
    "AutoKnowledge",
    "KnowledgeData",
    # B4 会話検索
    "ConversationSearch",
    "SearchResult",
    # Phase 2.5統合
    "GoalSettingContextEnricher",
]
