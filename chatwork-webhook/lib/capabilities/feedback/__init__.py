# lib/capabilities/feedback/__init__.py
"""
Phase F1: CEOフィードバックシステム パッケージ

ソウルくんに「内省」能力を与える。
事実に基づいてCEOにフィードバックを提供する。

設計書: docs/20_next_generation_capabilities.md セクション8

フィードバックの種類:
    - デイリーダイジェスト（毎朝8:00）
    - ウィークリーレビュー（毎週月曜9:00）
    - マンスリーインサイト（毎月1日9:00）
    - リアルタイムアラート（随時）
    - オンデマンド分析（「最近どう？」）

フィードバックの原則:
    1. 事実ファースト - 「〜と思います」ではなく「〜というデータがあります」
    2. 数字で語る - 具体的な数値変化を提示
    3. 比較を入れる - 先週比、先月比、過去パターンとの比較
    4. 仮説は仮説と明示 - 「〜かもしれません」と断定しない
    5. アクション提案 - 問題提起だけでなく「こうしては？」まで
    6. ポジティブも伝える - 良いことも報告

使用例:
    from lib.capabilities.feedback import (
        CEOFeedbackEngine,
        create_ceo_feedback_engine,
        CEOFeedbackSettings,
    )

    # エンジン作成
    engine = create_ceo_feedback_engine(
        conn=conn,
        organization_id=org_id,
        recipient_user_id=ceo_user_id,
        recipient_name="カズさん",
        chatwork_room_id=room_id,
    )

    # デイリーダイジェスト生成・配信
    feedback, result = await engine.generate_daily_digest()

    # リアルタイムアラート送信
    feedback, result = await engine.send_realtime_alert(anomaly)

    # オンデマンド分析
    feedback, _ = await engine.analyze_on_demand("最近チームの様子どう？")

Author: Claude Opus 4.5
Created: 2026-01-27
"""

__version__ = "1.0.0"
__author__ = "Claude Opus 4.5"


# =============================================================================
# 定数
# =============================================================================

from .constants import (
    # 列挙型
    FeedbackType,
    FeedbackPriority,
    FeedbackStatus,
    InsightCategory,
    TrendDirection,
    ComparisonPeriod,

    # パラメータクラス
    DeliveryParameters,
    AnalysisParameters,

    # テンプレート
    FeedbackTemplates,
    FeedbackIcons,

    # Feature Flags
    FEATURE_FLAG_NAME,
    FEATURE_FLAG_DAILY_DIGEST,
    FEATURE_FLAG_WEEKLY_REVIEW,
    FEATURE_FLAG_MONTHLY_INSIGHT,
    FEATURE_FLAG_REALTIME_ALERT,
    FEATURE_FLAG_ON_DEMAND,
)


# =============================================================================
# データモデル
# =============================================================================

from .models import (
    # ファクトモデル
    TaskFact,
    GoalFact,
    CommunicationFact,
    TeamFact,
    DailyFacts,

    # 分析結果モデル
    Anomaly,
    Trend,
    AnalysisResult,

    # フィードバックモデル
    FeedbackItem,
    CEOFeedback,
    DeliveryResult,
)


# =============================================================================
# ファクト収集
# =============================================================================

from .fact_collector import (
    FactCollector,
    create_fact_collector,
    FactCollectionError,
    UserInfo,
)


# =============================================================================
# 分析
# =============================================================================

from .analyzer import (
    Analyzer,
    create_analyzer,
    AnalysisError,
)


# =============================================================================
# フィードバック生成
# =============================================================================

from .feedback_generator import (
    FeedbackGenerator,
    create_feedback_generator,
    FeedbackGenerationError,
)


# =============================================================================
# 配信
# =============================================================================

from .delivery import (
    FeedbackDelivery,
    create_feedback_delivery,
    DeliveryConfig,
    DeliveryError,
    CooldownError,
    DailyLimitError,
)


# =============================================================================
# メインエンジン
# =============================================================================

from .ceo_feedback_engine import (
    CEOFeedbackEngine,
    create_ceo_feedback_engine,
    get_ceo_feedback_engine_for_organization,
    CEOFeedbackSettings,
    CEOFeedbackEngineError,
    FeatureDisabledError,
)


# =============================================================================
# 公開API
# =============================================================================

__all__ = [
    # バージョン
    "__version__",

    # 定数 - 列挙型
    "FeedbackType",
    "FeedbackPriority",
    "FeedbackStatus",
    "InsightCategory",
    "TrendDirection",
    "ComparisonPeriod",

    # 定数 - パラメータ
    "DeliveryParameters",
    "AnalysisParameters",

    # 定数 - テンプレート
    "FeedbackTemplates",
    "FeedbackIcons",

    # 定数 - Feature Flags
    "FEATURE_FLAG_NAME",
    "FEATURE_FLAG_DAILY_DIGEST",
    "FEATURE_FLAG_WEEKLY_REVIEW",
    "FEATURE_FLAG_MONTHLY_INSIGHT",
    "FEATURE_FLAG_REALTIME_ALERT",
    "FEATURE_FLAG_ON_DEMAND",

    # モデル - ファクト
    "TaskFact",
    "GoalFact",
    "CommunicationFact",
    "TeamFact",
    "DailyFacts",

    # モデル - 分析
    "Anomaly",
    "Trend",
    "AnalysisResult",

    # モデル - フィードバック
    "FeedbackItem",
    "CEOFeedback",
    "DeliveryResult",

    # ファクト収集
    "FactCollector",
    "create_fact_collector",
    "FactCollectionError",
    "UserInfo",

    # 分析
    "Analyzer",
    "create_analyzer",
    "AnalysisError",

    # フィードバック生成
    "FeedbackGenerator",
    "create_feedback_generator",
    "FeedbackGenerationError",

    # 配信
    "FeedbackDelivery",
    "create_feedback_delivery",
    "DeliveryConfig",
    "DeliveryError",
    "CooldownError",
    "DailyLimitError",

    # メインエンジン
    "CEOFeedbackEngine",
    "create_ceo_feedback_engine",
    "get_ceo_feedback_engine_for_organization",
    "CEOFeedbackSettings",
    "CEOFeedbackEngineError",
    "FeatureDisabledError",
]
