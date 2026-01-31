"""
Phase 2 進化版: インサイト管理（Insights Management）

このパッケージは、ソウルくんの「気づき」を管理するための
サービスクラスを提供します。

提供するサービス:
- InsightService: インサイトのCRUD操作
- WeeklyReportService: 週次レポートの生成・送信

設計書: docs/06_phase2_a1_pattern_detection.md

使用例:
    >>> from lib.insights import InsightService, InsightFilter
    >>>
    >>> # インサイトサービスを初期化
    >>> service = InsightService(conn, org_id)
    >>>
    >>> # 未対応のインサイトを取得
    >>> insights = await service.get_insights(
    ...     filter=InsightFilter(
    ...         organization_id=org_id,
    ...         statuses=[InsightStatus.NEW, InsightStatus.ACKNOWLEDGED]
    ...     )
    ... )
    >>>
    >>> # インサイトを確認済みに更新
    >>> await service.acknowledge(insight_id, user_id)

    >>> from lib.insights import WeeklyReportService
    >>>
    >>> # 週次レポートサービスを初期化
    >>> report_service = WeeklyReportService(conn, org_id)
    >>>
    >>> # 今週のレポートを生成
    >>> report_id = await report_service.generate_weekly_report()

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
# InsightServiceのエクスポート
# ================================================================

from lib.insights.insight_service import (
    # データクラス
    InsightFilter,
    InsightSummary,
    InsightRecord,
    # サービスクラス
    InsightService,
)

# ================================================================
# WeeklyReportServiceのエクスポート
# ================================================================

from lib.insights.weekly_report_service import (
    # データクラス
    WeeklyReportRecord,
    ReportInsightItem,
    GeneratedReport,
    # サービスクラス
    WeeklyReportService,
)

# ================================================================
# __all__ 定義
# ================================================================

__all__ = [
    # バージョン
    "__version__",
    "__author__",
    # InsightService関連
    "InsightFilter",
    "InsightSummary",
    "InsightRecord",
    "InsightService",
    # WeeklyReportService関連
    "WeeklyReportRecord",
    "ReportInsightItem",
    "GeneratedReport",
    "WeeklyReportService",
]
