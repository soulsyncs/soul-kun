"""
Phase 2 A1: パターン検知用 lib モジュール

このモジュールは pattern-detection Cloud Function で使用される
共通ライブラリです。
"""

# detection モジュール
from lib.detection import (
    PatternDetector,
    BaseDetector,
    DetectionResult,
    DetectionContext,
    InsightData,
)

# insights モジュール
from lib.insights import (
    InsightService,
    WeeklyReportService,
)

__all__ = [
    "PatternDetector",
    "BaseDetector",
    "DetectionResult",
    "DetectionContext",
    "InsightData",
    "InsightService",
    "WeeklyReportService",
]
