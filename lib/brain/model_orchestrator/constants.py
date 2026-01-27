"""
Model Orchestrator 定数定義

Phase 0: 次世代能力設計書
設計書: docs/20_next_generation_capabilities.md セクション4
"""

from enum import Enum
from typing import Dict, List, Set
from decimal import Decimal


# ============================================================================
# ティア定義
# ============================================================================

class Tier(str, Enum):
    """AIモデルのティア（品質/コストレベル）"""
    ECONOMY = "economy"      # 軽量タスク向け
    STANDARD = "standard"    # 標準タスク向け
    PREMIUM = "premium"      # 重要タスク向け


# ============================================================================
# タスクタイプ → ティア マッピング
# ============================================================================

TASK_TYPE_TIERS: Dict[str, Tier] = {
    # ============================================
    # Economy Tier（軽量タスク）
    # ============================================
    "simple_qa": Tier.ECONOMY,
    "sentiment_analysis": Tier.ECONOMY,
    "keyword_extraction": Tier.ECONOMY,
    "simple_classification": Tier.ECONOMY,
    "emotion_detection": Tier.ECONOMY,
    "reminder": Tier.ECONOMY,
    "task_list": Tier.ECONOMY,
    "status_check": Tier.ECONOMY,
    "greeting": Tier.ECONOMY,

    # ============================================
    # Standard Tier（標準タスク）
    # ============================================
    "general": Tier.STANDARD,
    "conversation": Tier.STANDARD,
    "chat": Tier.STANDARD,
    "summarization": Tier.STANDARD,
    "understanding": Tier.STANDARD,
    "analysis": Tier.STANDARD,
    "email_draft": Tier.STANDARD,
    "image_analysis": Tier.STANDARD,
    "knowledge_search": Tier.STANDARD,
    "goal_support": Tier.STANDARD,

    # ============================================
    # Premium Tier（重要タスク）
    # ============================================
    "complex_reasoning": Tier.PREMIUM,
    "coding": Tier.PREMIUM,
    "decision_making": Tier.PREMIUM,
    "ceo_learning": Tier.PREMIUM,
    "document_generation": Tier.PREMIUM,
    "proposal_creation": Tier.PREMIUM,
    "deep_research": Tier.PREMIUM,
    "important_decision": Tier.PREMIUM,
    "strategy": Tier.PREMIUM,
}

# デフォルトティア（タスクタイプが不明な場合）
DEFAULT_TIER = Tier.STANDARD


# ============================================================================
# キーワードによるティア調整
# ============================================================================

# Premiumにアップグレードするキーワード
TIER_UPGRADE_KEYWORDS: Set[str] = {
    # 重要度
    "重要", "大事", "大切", "クリティカル", "緊急",
    # ビジネス
    "経営", "戦略", "提案書", "企画書", "クライアント向け",
    # 品質
    "ちゃんと", "しっかり", "本気で", "丁寧に", "詳しく",
    # 相手
    "社長", "CEO", "役員", "お客様", "クライアント",
}

# Economyにダウングレードするキーワード
TIER_DOWNGRADE_KEYWORDS: Set[str] = {
    # 簡易度
    "ざっくり", "簡単に", "とりあえず", "さくっと", "概要だけ",
    # 内部用
    "メモ", "覚え書き", "自分用", "テスト",
    # 優先度低
    "暇な時", "時間あれば", "余裕あれば",
}


# ============================================================================
# コスト閾値（円）
# ============================================================================

class CostThreshold:
    """コスト閾値（日次）"""
    # 通常動作
    NORMAL_MAX = Decimal("100")

    # 警告（ログ出力、管理者通知）
    WARNING_MAX = Decimal("500")

    # 注意（自動ダウングレード）
    CAUTION_MAX = Decimal("2000")

    # 制限（AI停止、人間へ相談）
    LIMIT = Decimal("2000")


class MonthlyBudget:
    """月間予算のデフォルト値"""
    DEFAULT_JPY = Decimal("30000")  # 3万円/月


# ============================================================================
# 予算状態
# ============================================================================

class BudgetStatus(str, Enum):
    """予算状態"""
    NORMAL = "normal"      # 通常（残予算50%以上）
    WARNING = "warning"    # 警告（残予算50%以下）
    CAUTION = "caution"    # 注意（残予算20%以下）
    LIMIT = "limit"        # 制限（残予算0以下）


# 予算残高に対する閾値
BUDGET_STATUS_THRESHOLDS = {
    BudgetStatus.WARNING: Decimal("0.50"),   # 残予算50%でwarning
    BudgetStatus.CAUTION: Decimal("0.20"),   # 残予算20%でcaution
    BudgetStatus.LIMIT: Decimal("0.00"),     # 残予算0%でlimit
}


# ============================================================================
# フォールバックチェーン
# ============================================================================

# ティアごとのフォールバック順序（model_id）
FALLBACK_CHAINS: Dict[Tier, List[str]] = {
    Tier.PREMIUM: [
        "anthropic/claude-opus-4-5-20251101",
        "openai/o1",
        "google/gemini-2.0-ultra",
        "openai/gpt-4o",  # 最終fallbackはstandardへ
    ],
    Tier.STANDARD: [
        "google/gemini-2.5-pro-preview",
        "openai/gpt-4o",
        "anthropic/claude-3-5-sonnet-latest",
        "openai/gpt-4o-mini",  # 最終fallbackはeconomyへ
    ],
    Tier.ECONOMY: [
        "google/gemini-2.0-flash-lite",
        "openai/gpt-4o-mini",
    ],
}

# リトライ設定
MAX_RETRIES = 3
RETRY_DELAY_BASE_SECONDS = 1.0  # 指数バックオフの基底秒数
RETRY_DELAY_MAX_SECONDS = 10.0  # 最大リトライ待機秒数


# ============================================================================
# リトライ可能なエラー
# ============================================================================

# HTTPステータスコードでリトライ可能なもの
RETRIABLE_HTTP_CODES: Set[int] = {
    429,  # Rate Limit
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}

# リトライ不可（即座にフォールバック）
NON_RETRIABLE_HTTP_CODES: Set[int] = {
    400,  # Bad Request
    401,  # Unauthorized
    403,  # Forbidden
    404,  # Not Found
}


# ============================================================================
# 為替レート
# ============================================================================

DEFAULT_USD_TO_JPY_RATE = Decimal("150.00")


# ============================================================================
# ログ設定
# ============================================================================

# 利用ログの保持期間（日）
USAGE_LOG_RETENTION_DAYS = 90

# 月次サマリーの保持期間（月）
MONTHLY_SUMMARY_RETENTION_MONTHS = 24


# ============================================================================
# タイムアウト設定
# ============================================================================

# API呼び出しのタイムアウト（秒）
API_TIMEOUT_SECONDS = 60

# Premiumモデルは長めのタイムアウト
PREMIUM_API_TIMEOUT_SECONDS = 120


# ============================================================================
# トークン推定
# ============================================================================

# 日本語1文字あたりの推定トークン数
TOKENS_PER_CHAR_JP = 0.5

# 英語1文字あたりの推定トークン数
TOKENS_PER_CHAR_EN = 0.25

# デフォルトの出力トークン推定
DEFAULT_OUTPUT_TOKENS_ESTIMATE = 500


# ============================================================================
# コスト計算用定数
# ============================================================================

# 100万トークンあたりの単位
TOKENS_PER_MILLION = 1_000_000


# ============================================================================
# 機能フラグ名
# ============================================================================

FEATURE_FLAG_NAME = "USE_MODEL_ORCHESTRATOR"
