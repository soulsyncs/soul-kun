# lib/capabilities/apps/meeting_minutes/__init__.py
"""
App1: 議事録自動生成アプリ

M2（音声入力）とG1（文書生成）を統合し、
音声ファイルから議事録を自動生成する。

使用例:
    from lib.capabilities.apps.meeting_minutes import (
        MeetingMinutesGenerator,
        MeetingMinutesRequest,
        MeetingMinutesResult,
        MeetingType,
    )

    # リクエスト作成
    request = MeetingMinutesRequest(
        organization_id=org_id,
        audio_data=audio_bytes,
        meeting_title="週次定例会議",
    )

    # 議事録生成
    generator = MeetingMinutesGenerator(pool, org_id)
    result = await generator.generate(request)

    if result.success:
        print(f"議事録URL: {result.document_url}")

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
    MeetingType,
    MinutesStatus,
    MinutesSection,

    # デフォルト設定
    DEFAULT_MINUTES_SECTIONS,
    MEETING_TYPE_SECTIONS,
    MEETING_TYPE_KEYWORDS,

    # プロンプト
    MINUTES_ANALYSIS_PROMPT,
    MINUTES_GENERATION_PROMPT,

    # サイズ制限
    MAX_ATTENDEES,
    MAX_ACTION_ITEMS,
    MAX_DECISIONS,
    MAX_MINUTES_LENGTH,

    # タイムアウト
    TRANSCRIPTION_TIMEOUT,
    ANALYSIS_TIMEOUT,
    GENERATION_TIMEOUT,

    # Feature Flag
    FEATURE_FLAG_MEETING_MINUTES,

    # エラーメッセージ
    ERROR_MESSAGES,
)


# =============================================================================
# データモデル
# =============================================================================

from .models import (
    # 入力
    MeetingMinutesRequest,

    # 中間
    ActionItem,
    Decision,
    DiscussionTopic,
    MeetingAnalysis,

    # 出力
    MeetingMinutesResult,
)


# =============================================================================
# ジェネレーター
# =============================================================================

from .meeting_minutes_generator import (
    MeetingMinutesGenerator,
    create_meeting_minutes_generator,
)


# =============================================================================
# 公開API
# =============================================================================

__all__ = [
    # バージョン
    "__version__",

    # 定数 - 列挙型
    "MeetingType",
    "MinutesStatus",
    "MinutesSection",

    # 定数 - デフォルト設定
    "DEFAULT_MINUTES_SECTIONS",
    "MEETING_TYPE_SECTIONS",
    "MEETING_TYPE_KEYWORDS",

    # 定数 - プロンプト
    "MINUTES_ANALYSIS_PROMPT",
    "MINUTES_GENERATION_PROMPT",

    # 定数 - サイズ制限
    "MAX_ATTENDEES",
    "MAX_ACTION_ITEMS",
    "MAX_DECISIONS",
    "MAX_MINUTES_LENGTH",

    # 定数 - タイムアウト
    "TRANSCRIPTION_TIMEOUT",
    "ANALYSIS_TIMEOUT",
    "GENERATION_TIMEOUT",

    # 定数 - Feature Flag
    "FEATURE_FLAG_MEETING_MINUTES",

    # 定数 - エラーメッセージ
    "ERROR_MESSAGES",

    # モデル - 入力
    "MeetingMinutesRequest",

    # モデル - 中間
    "ActionItem",
    "Decision",
    "DiscussionTopic",
    "MeetingAnalysis",

    # モデル - 出力
    "MeetingMinutesResult",

    # ジェネレーター
    "MeetingMinutesGenerator",
    "create_meeting_minutes_generator",
]
