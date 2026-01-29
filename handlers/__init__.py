"""
chatwork-webhook ハンドラーモジュール

各機能のハンドラー関数を管理するモジュール。
main.pyから分割された機能ごとのハンドラーを提供する。

v10.47.0: handlers/registry.py 追加
  - SYSTEM_CAPABILITIES: AIが認識する機能カタログ
  - HANDLER_ALIASES: 旧名→新名のマッピング
  - 「新機能追加 = handlers/xxx_handler.py作成 + registry.pyに追加」
"""

__version__ = "1.2.0"  # v10.47.0: registry.py追加

# Registry（v10.47.0追加）- 機能カタログの一元管理
try:
    from .registry import (
        SYSTEM_CAPABILITIES,
        HANDLER_ALIASES,
        get_enabled_capabilities,
        get_capability_info,
        generate_capabilities_prompt,
    )
except ImportError:
    SYSTEM_CAPABILITIES = {}
    HANDLER_ALIASES = {}
    get_enabled_capabilities = None
    get_capability_info = None
    generate_capabilities_prompt = None

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
