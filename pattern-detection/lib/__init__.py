"""
Phase 2 A1/A2/A3: パターン検知・属人化検出・ボトルネック検出用 lib モジュール

このモジュールは pattern-detection Cloud Function で使用される
共通ライブラリです。

v10.31.1: Phase D - db, config, secrets追加（接続設定集約）
"""

# =============================================================================
# Phase D: 接続設定集約（v10.31.1）
# =============================================================================
from .config import get_settings, Settings, settings
from .secrets import get_secret, get_secret_cached
from .db import (
    get_db_pool,
    get_db_connection,
    get_db_session,
    close_all_connections,
    health_check,
)

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
    # Phase D: 接続設定集約
    "get_settings",
    "Settings",
    "settings",
    "get_secret",
    "get_secret_cached",
    "get_db_pool",
    "get_db_connection",
    "get_db_session",
    "close_all_connections",
    "health_check",
    # Detection
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
