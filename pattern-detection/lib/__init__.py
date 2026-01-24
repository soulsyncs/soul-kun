"""
Phase 2 A1/A2/A3: パターン検知・属人化検出・ボトルネック検出用 lib モジュール

このモジュールは pattern-detection Cloud Function で使用される
共通ライブラリです。
"""

# detection モジュール
from lib.detection import (
    PatternDetector,
    PersonalizationDetector,
    BottleneckDetector,
    BaseDetector,
    DetectionResult,
    DetectionContext,
    InsightData,
    PersonalizationRiskLevel,
    PersonalizationStatus,
    BottleneckType,
    BottleneckRiskLevel,
    BottleneckStatus,
)

# insights モジュール
from lib.insights import (
    InsightService,
    WeeklyReportService,
)

__all__ = [
    "PatternDetector",
    "PersonalizationDetector",
    "BottleneckDetector",
    "BaseDetector",
    "DetectionResult",
    "DetectionContext",
    "InsightData",
    "PersonalizationRiskLevel",
    "PersonalizationStatus",
    "BottleneckType",
    "BottleneckRiskLevel",
    "BottleneckStatus",
    "InsightService",
    "WeeklyReportService",
]
