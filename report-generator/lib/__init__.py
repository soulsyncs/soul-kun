"""
report-generator用 最小限のlib パッケージ
v10.23.2: Phase 2.5 + MVV統合
"""

from lib.db import get_db_pool
from lib.chatwork import ChatworkClient
from lib.report_generator import (
    GoalProgress,
    GoalProgressFetcher,
    EncouragementGenerator,
    DailyReportGenerator,
    WeeklyReportGenerator,
    ReportDistributor,
    run_daily_report_generation,
    run_weekly_report_generation,
)

__all__ = [
    "get_db_pool",
    "ChatworkClient",
    "GoalProgress",
    "GoalProgressFetcher",
    "EncouragementGenerator",
    "DailyReportGenerator",
    "WeeklyReportGenerator",
    "ReportDistributor",
    "run_daily_report_generation",
    "run_weekly_report_generation",
]
