"""
Phase 2 進化版: 検出基盤（Detection Framework）

このパッケージは、ソウルくんの「気づく能力」を提供する
検出機能の共通基盤です。

現在実装済みの検出器:
- PatternDetector (A1): 頻出質問パターンの検出

将来実装予定の検出器:
- PersonalizationDetector (A2): 属人化リスクの検出
- BottleneckDetector (A3): ボトルネックの検出
- EmotionDetector (A4): 感情変化の検出

設計書: docs/06_phase2_a1_pattern_detection.md

使用例:
    >>> from lib.detection import PatternDetector, DetectionContext
    >>>
    >>> # 検出器を初期化
    >>> detector = PatternDetector(conn, org_id)
    >>>
    >>> # 質問を分析
    >>> result = await detector.detect(
    ...     question="週報の出し方を教えてください",
    ...     user_id=user_id
    ... )
    >>>
    >>> if result.insight_created:
    ...     print(f"Insight created: {result.insight_id}")

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-23
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

from lib.detection.constants import (
    # 検出パラメータ
    DetectionParameters,
    # カテゴリ
    QuestionCategory,
    CATEGORY_KEYWORDS,
    # ステータス
    PatternStatus,
    InsightStatus,
    WeeklyReportStatus,
    # タイプ
    InsightType,
    SourceType,
    NotificationType,
    # 重要度・機密区分
    Importance,
    Classification,
    # A2属人化検出
    PersonalizationRiskLevel,
    PersonalizationStatus,
    # その他
    ErrorCode,
    IdempotencyKeyPrefix,
    LogMessages,
)

# ================================================================
# 例外のエクスポート
# ================================================================

from lib.detection.exceptions import (
    # 基底例外
    DetectionBaseException,
    # 具体的な例外
    DetectionError,
    PatternSaveError,
    InsightCreateError,
    NotificationError,
    DatabaseError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    # ユーティリティ
    wrap_database_error,
    wrap_detection_error,
)

# ================================================================
# 基底クラスのエクスポート
# ================================================================

from lib.detection.base import (
    # データクラス
    InsightData,
    DetectionContext,
    DetectionResult,
    # 基底クラス
    BaseDetector,
    # ユーティリティ
    validate_uuid,
    truncate_text,
)

# ================================================================
# 検出器のエクスポート
# ================================================================

from lib.detection.pattern_detector import (
    # データクラス
    PatternData,
    # 検出器
    PatternDetector,
)

from lib.detection.personalization_detector import (
    # 検出器
    PersonalizationDetector,
)

# ================================================================
# __all__ 定義
# ================================================================

__all__ = [
    # バージョン
    "__version__",
    "__author__",
    # 定数
    "DetectionParameters",
    "QuestionCategory",
    "CATEGORY_KEYWORDS",
    "PatternStatus",
    "InsightStatus",
    "WeeklyReportStatus",
    "InsightType",
    "SourceType",
    "NotificationType",
    "Importance",
    "Classification",
    # A2属人化検出
    "PersonalizationRiskLevel",
    "PersonalizationStatus",
    # その他定数
    "ErrorCode",
    "IdempotencyKeyPrefix",
    "LogMessages",
    # 例外
    "DetectionBaseException",
    "DetectionError",
    "PatternSaveError",
    "InsightCreateError",
    "NotificationError",
    "DatabaseError",
    "ValidationError",
    "AuthenticationError",
    "AuthorizationError",
    "wrap_database_error",
    "wrap_detection_error",
    # データクラス
    "InsightData",
    "DetectionContext",
    "DetectionResult",
    "PatternData",
    # 基底クラス
    "BaseDetector",
    # 検出器
    "PatternDetector",
    "PersonalizationDetector",
    # ユーティリティ
    "validate_uuid",
    "truncate_text",
]
