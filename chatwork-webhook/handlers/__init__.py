"""
chatwork-webhook ハンドラーモジュール

各機能のハンドラー関数を管理するモジュール。
main.pyから分割された機能ごとのハンドラーを提供する。
"""

__version__ = "1.1.0"  # v10.26.0: アナウンス機能追加

# AnnouncementHandler（v10.26.0追加）
try:
    from .announcement_handler import (
        AnnouncementHandler,
        ParsedAnnouncementRequest,
        ScheduleType,
        AnnouncementStatus,
    )
except ImportError:
    AnnouncementHandler = None
    ParsedAnnouncementRequest = None
    ScheduleType = None
    AnnouncementStatus = None
