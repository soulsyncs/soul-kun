"""
Soul-kun 共通ライブラリ

このモジュールは以下を提供します:
- config: 環境変数・設定管理
- secrets: GCP Secret Manager
- db: データベース接続（sync/async両対応）
- chatwork: Chatwork APIクライアント
- logging: 構造化ログ
- tenant: テナントコンテキスト管理
- google_drive: Googleドライブ連携（Phase 3）
- document_processor: ドキュメント処理（Phase 3）
- pinecone_client: Pineconeベクター検索（Phase 3）
- embedding: エンベディング生成（Phase 3）
- detection: 検出基盤（Phase 2進化版 A1）
- insights: インサイト管理（Phase 2進化版 A1）

使用例（Flask/Cloud Functions）:
    from lib import get_secret, get_db_pool, ChatworkClient

使用例（FastAPI）:
    from lib import get_secret, get_async_db_pool, ChatworkAsyncClient

Phase 3 ナレッジ検索:
    from lib import GoogleDriveClient, DocumentProcessor, PineconeClient, EmbeddingClient

Phase 2進化版 A1 パターン検出:
    from lib.detection import PatternDetector, DetectionContext
    from lib.insights import InsightService, WeeklyReportService

Phase 4対応:
    - 全モジュールがorganization_id（テナントID）を認識
    - sync/async両方をサポート
    - Cloud Run 100インスタンス対応のコネクションプール設計

v10.51.0: Lazy Import Pattern
    - 依存関係のカスケード問題を解決
    - 起動時間の短縮
    - 必要な時にのみモジュールをインポート
"""

__version__ = "1.10.0"  # v10.51.0: Lazy Import Pattern導入

import sys
from typing import Any

# =============================================================================
# 即座にインポートするモジュール（コア機能）
# =============================================================================
# これらは起動時に必ず必要なため、eager importを維持

# 設定
from lib.config import (
    Settings,
    get_settings,
)

# シークレット管理
from lib.secrets import (
    get_secret,
    get_secret_cached,
)

# データベース
from lib.db import (
    # Sync（Flask/Cloud Functions用）
    get_db_pool,
    get_db_connection,
    # Async（FastAPI用）
    get_async_db_pool,
    get_async_db_session,
)

# Chatwork（pattern-detection等では不要なためオプショナル）
try:
    from lib.chatwork import (
        # Sync
        ChatworkClient,
        # Async
        ChatworkAsyncClient,
    )
except ImportError:
    pass

# テナント管理（pattern-detection等では不要なためオプショナル）
try:
    from lib.tenant import (
        TenantContext,
        get_current_tenant,
        set_current_tenant,
    )
except ImportError:
    pass

# =============================================================================
# Lazy Import定義（必要な時にのみインポート）
# =============================================================================
# これらのモジュールは依存関係が重いため、使用時にのみインポート

# モジュール名 → (モジュールパス, エクスポート名リスト)
_LAZY_IMPORTS = {
    # Phase 3: Googleドライブ連携
    "GoogleDriveClient": ("lib.google_drive", "GoogleDriveClient"),
    "DriveFile": ("lib.google_drive", "DriveFile"),
    "DriveChange": ("lib.google_drive", "DriveChange"),
    "SyncResult": ("lib.google_drive", "SyncResult"),
    "FolderMapper": ("lib.google_drive", "FolderMapper"),
    "FolderMappingConfig": ("lib.google_drive", "FolderMappingConfig"),

    # Phase 3: ドキュメント処理
    "DocumentProcessor": ("lib.document_processor", "DocumentProcessor"),
    "TextChunker": ("lib.document_processor", "TextChunker"),
    "Chunk": ("lib.document_processor", "Chunk"),
    "ExtractedDocument": ("lib.document_processor", "ExtractedDocument"),
    "extract_text": ("lib.document_processor", "extract_text"),
    "extract_with_metadata": ("lib.document_processor", "extract_with_metadata"),

    # Phase 3: Pinecone連携
    "PineconeClient": ("lib.pinecone_client", "PineconeClient"),
    "SearchResult": ("lib.pinecone_client", "SearchResult"),
    "SearchResponse": ("lib.pinecone_client", "SearchResponse"),

    # Phase 3: エンベディング（google-genaiに依存）
    "EmbeddingClient": ("lib.embedding", "EmbeddingClient"),
    "EmbeddingResult": ("lib.embedding", "EmbeddingResult"),
    "BatchEmbeddingResult": ("lib.embedding", "BatchEmbeddingResult"),
    "embed_text": ("lib.embedding", "embed_text"),
    "embed_text_sync": ("lib.embedding", "embed_text_sync"),
    "get_embedding_client": ("lib.embedding", "get_embedding_client"),

    # v10.14.1: テキスト処理ユーティリティ
    "GREETING_PATTERNS": ("lib.text_utils", "GREETING_PATTERNS"),
    "CLOSING_PATTERNS": ("lib.text_utils", "CLOSING_PATTERNS"),
    "GREETING_STARTS": ("lib.text_utils", "GREETING_STARTS"),
    "TRUNCATION_INDICATORS": ("lib.text_utils", "TRUNCATION_INDICATORS"),
    "remove_greetings": ("lib.text_utils", "remove_greetings"),
    "extract_task_subject": ("lib.text_utils", "extract_task_subject"),
    "is_greeting_only": ("lib.text_utils", "is_greeting_only"),
    "validate_summary": ("lib.text_utils", "validate_summary"),
    "clean_chatwork_tags": ("lib.text_utils", "clean_chatwork_tags"),
    "validate_and_get_reason": ("lib.text_utils", "validate_and_get_reason"),
    "prepare_task_display_text": ("lib.text_utils", "prepare_task_display_text"),

    # v10.14.1: 監査ログ
    "AuditAction": ("lib.audit", "AuditAction"),
    "AuditResourceType": ("lib.audit", "AuditResourceType"),
    "log_audit": ("lib.audit", "log_audit"),
    "log_audit_batch": ("lib.audit", "log_audit_batch"),

    # v10.15.0: Phase 2.5 目標管理
    "GoalLevel": ("lib.goal", "GoalLevel"),
    "GoalType": ("lib.goal", "GoalType"),
    "GoalStatus": ("lib.goal", "GoalStatus"),
    "PeriodType": ("lib.goal", "PeriodType"),
    "Classification": ("lib.goal", "Classification"),
    "ReminderType": ("lib.goal", "ReminderType"),
    "Goal": ("lib.goal", "Goal"),
    "GoalProgress": ("lib.goal", "GoalProgress"),
    "GoalService": ("lib.goal", "GoalService"),
    "get_goal_service": ("lib.goal", "get_goal_service"),
    "parse_goal_type_from_text": ("lib.goal", "parse_goal_type_from_text"),
    "calculate_period_from_type": ("lib.goal", "calculate_period_from_type"),

    # v10.15.0: Phase 2.5 目標通知サービス（pytzに依存）
    "GoalNotificationType": ("lib.goal_notification", "GoalNotificationType"),
    "sanitize_error": ("lib.goal_notification", "sanitize_error"),
    "build_daily_check_message": ("lib.goal_notification", "build_daily_check_message"),
    "build_daily_reminder_message": ("lib.goal_notification", "build_daily_reminder_message"),
    "build_morning_feedback_message": ("lib.goal_notification", "build_morning_feedback_message"),
    "build_team_summary_message": ("lib.goal_notification", "build_team_summary_message"),
    "build_consecutive_unanswered_alert_message": ("lib.goal_notification", "build_consecutive_unanswered_alert_message"),
    "send_daily_check_to_user": ("lib.goal_notification", "send_daily_check_to_user"),
    "send_daily_reminder_to_user": ("lib.goal_notification", "send_daily_reminder_to_user"),
    "send_morning_feedback_to_user": ("lib.goal_notification", "send_morning_feedback_to_user"),
    "send_team_summary_to_leader": ("lib.goal_notification", "send_team_summary_to_leader"),
    "send_consecutive_unanswered_alert_to_leader": ("lib.goal_notification", "send_consecutive_unanswered_alert_to_leader"),
    "scheduled_daily_check": ("lib.goal_notification", "scheduled_daily_check"),
    "scheduled_daily_reminder": ("lib.goal_notification", "scheduled_daily_reminder"),
    "scheduled_morning_feedback": ("lib.goal_notification", "scheduled_morning_feedback"),
    "scheduled_consecutive_unanswered_check": ("lib.goal_notification", "scheduled_consecutive_unanswered_check"),
    "check_consecutive_unanswered_users": ("lib.goal_notification", "check_consecutive_unanswered_users"),
    "can_view_goal": ("lib.goal_notification", "can_view_goal"),
    "get_viewable_user_ids": ("lib.goal_notification", "get_viewable_user_ids"),

    # v10.18.0: Phase 2進化版 A1 検出基盤
    "DetectionParameters": ("lib.detection", "DetectionParameters"),
    "QuestionCategory": ("lib.detection", "QuestionCategory"),
    "CATEGORY_KEYWORDS": ("lib.detection", "CATEGORY_KEYWORDS"),
    "PatternStatus": ("lib.detection", "PatternStatus"),
    "InsightStatus": ("lib.detection", "InsightStatus"),
    "WeeklyReportStatus": ("lib.detection", "WeeklyReportStatus"),
    "InsightType": ("lib.detection", "InsightType"),
    "SourceType": ("lib.detection", "SourceType"),
    "NotificationType": ("lib.detection", "NotificationType"),
    "Importance": ("lib.detection", "Importance"),
    "ErrorCode": ("lib.detection", "ErrorCode"),
    "IdempotencyKeyPrefix": ("lib.detection", "IdempotencyKeyPrefix"),
    "LogMessages": ("lib.detection", "LogMessages"),
    "DetectionBaseException": ("lib.detection", "DetectionBaseException"),
    "DetectionError": ("lib.detection", "DetectionError"),
    "PatternSaveError": ("lib.detection", "PatternSaveError"),
    "InsightCreateError": ("lib.detection", "InsightCreateError"),
    "NotificationError": ("lib.detection", "NotificationError"),
    "DatabaseError": ("lib.detection", "DatabaseError"),
    "ValidationError": ("lib.detection", "ValidationError"),
    "AuthenticationError": ("lib.detection", "AuthenticationError"),
    "AuthorizationError": ("lib.detection", "AuthorizationError"),
    "wrap_database_error": ("lib.detection", "wrap_database_error"),
    "wrap_detection_error": ("lib.detection", "wrap_detection_error"),
    "InsightData": ("lib.detection", "InsightData"),
    "DetectionContext": ("lib.detection", "DetectionContext"),
    "DetectionResult": ("lib.detection", "DetectionResult"),
    "PatternData": ("lib.detection", "PatternData"),
    "BaseDetector": ("lib.detection", "BaseDetector"),
    "PatternDetector": ("lib.detection", "PatternDetector"),
    "validate_uuid": ("lib.detection", "validate_uuid"),
    "truncate_text": ("lib.detection", "truncate_text"),

    # v10.18.0: Phase 2進化版 A1 インサイト管理
    "InsightFilter": ("lib.insights", "InsightFilter"),
    "InsightSummary": ("lib.insights", "InsightSummary"),
    "InsightRecord": ("lib.insights", "InsightRecord"),
    "InsightService": ("lib.insights", "InsightService"),
    "WeeklyReportRecord": ("lib.insights", "WeeklyReportRecord"),
    "ReportInsightItem": ("lib.insights", "ReportInsightItem"),
    "GeneratedReport": ("lib.insights", "GeneratedReport"),
    "WeeklyReportService": ("lib.insights", "WeeklyReportService"),

    # v10.18.1: ユーザー関連ユーティリティ（Phase 3.5対応）
    "get_user_primary_department": ("lib.user_utils", "get_user_primary_department"),

    # v10.19.0: Phase 2.5 目標設定対話フロー
    "GOAL_SETTING_STEPS": ("lib.goal_setting", "STEPS"),
    "GOAL_SETTING_STEP_ORDER": ("lib.goal_setting", "STEP_ORDER"),
    "GOAL_SETTING_MAX_RETRY": ("lib.goal_setting", "MAX_RETRY_COUNT"),
    "GOAL_SETTING_TEMPLATES": ("lib.goal_setting", "TEMPLATES"),
    "GOAL_SETTING_PATTERN_KEYWORDS": ("lib.goal_setting", "PATTERN_KEYWORDS"),
    "GoalSettingDialogue": ("lib.goal_setting", "GoalSettingDialogue"),
    "has_active_goal_session": ("lib.goal_setting", "has_active_goal_session"),
    "process_goal_setting_message": ("lib.goal_setting", "process_goal_setting_message"),

    # v10.24.9: 営業日判定（土日祝日リマインドスキップ）
    "is_business_day": ("lib.business_day", "is_business_day"),
    "is_weekend": ("lib.business_day", "is_weekend"),
    "is_holiday": ("lib.business_day", "is_holiday"),
    "get_holiday_name": ("lib.business_day", "get_holiday_name"),
    "get_non_business_day_reason": ("lib.business_day", "get_non_business_day_reason"),

    # v10.31.0: Feature Flags一元管理（Phase C）
    "FeatureFlags": ("lib.feature_flags", "FeatureFlags"),
    "FlagCategory": ("lib.feature_flags", "FlagCategory"),
    "FlagType": ("lib.feature_flags", "FlagType"),
    "FlagInfo": ("lib.feature_flags", "FlagInfo"),
    "FLAG_DEFINITIONS": ("lib.feature_flags", "FLAG_DEFINITIONS"),
    "get_flags": ("lib.feature_flags", "get_flags"),
    "reset_flags": ("lib.feature_flags", "reset_flags"),
    "init_flags": ("lib.feature_flags", "init_flags"),
    "is_handler_enabled": ("lib.feature_flags", "is_handler_enabled"),
    "is_library_available": ("lib.feature_flags", "is_library_available"),
    "is_feature_enabled": ("lib.feature_flags", "is_feature_enabled"),
    "get_brain_mode": ("lib.feature_flags", "get_brain_mode"),
    "is_dry_run": ("lib.feature_flags", "is_dry_run"),
}

# キャッシュ（一度インポートしたモジュールを再利用）
_LAZY_CACHE: dict[str, Any] = {}


def __getattr__(name: str) -> Any:
    """
    Lazy Import実装

    このモジュールに存在しない属性にアクセスされた時に呼ばれる。
    _LAZY_IMPORTSに定義されている場合、その時点で初めてインポートする。
    """
    if name in _LAZY_CACHE:
        return _LAZY_CACHE[name]

    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        try:
            import importlib
            module = importlib.import_module(module_path)
            value = getattr(module, attr_name)
            _LAZY_CACHE[name] = value
            return value
        except ImportError as e:
            raise ImportError(
                f"Cannot import '{name}' from '{module_path}': {e}. "
                f"Make sure the required dependencies are installed."
            ) from e
        except AttributeError as e:
            raise AttributeError(
                f"Module '{module_path}' has no attribute '{attr_name}': {e}"
            ) from e

    raise AttributeError(f"module 'lib' has no attribute '{name}'")


# =============================================================================
# __all__ 定義（IDEサポート・型ヒント用）
# =============================================================================

__all__ = [
    # Config
    "Settings",
    "get_settings",
    # Secrets
    "get_secret",
    "get_secret_cached",
    # Database
    "get_db_pool",
    "get_db_connection",
    "get_async_db_pool",
    "get_async_db_session",
    # Chatwork
    "ChatworkClient",
    "ChatworkAsyncClient",
    # Tenant
    "TenantContext",
    "get_current_tenant",
    "set_current_tenant",
    # Phase 3: Google Drive (lazy)
    "GoogleDriveClient",
    "DriveFile",
    "DriveChange",
    "SyncResult",
    "FolderMapper",
    "FolderMappingConfig",
    # Phase 3: Document Processing (lazy)
    "DocumentProcessor",
    "TextChunker",
    "Chunk",
    "ExtractedDocument",
    "extract_text",
    "extract_with_metadata",
    # Phase 3: Pinecone (lazy)
    "PineconeClient",
    "SearchResult",
    "SearchResponse",
    # Phase 3: Embedding (lazy)
    "EmbeddingClient",
    "EmbeddingResult",
    "BatchEmbeddingResult",
    "embed_text",
    "embed_text_sync",
    "get_embedding_client",
    # v10.14.1: Text Utils (lazy)
    "GREETING_PATTERNS",
    "CLOSING_PATTERNS",
    "GREETING_STARTS",
    "TRUNCATION_INDICATORS",
    "remove_greetings",
    "extract_task_subject",
    "is_greeting_only",
    "validate_summary",
    "clean_chatwork_tags",
    "validate_and_get_reason",
    "prepare_task_display_text",
    # v10.14.1: Audit (lazy)
    "AuditAction",
    "AuditResourceType",
    "log_audit",
    "log_audit_batch",
    # v10.15.0: Phase 2.5 Goal (lazy)
    "GoalLevel",
    "GoalType",
    "GoalStatus",
    "PeriodType",
    "Classification",
    "ReminderType",
    "Goal",
    "GoalProgress",
    "GoalService",
    "get_goal_service",
    "parse_goal_type_from_text",
    "calculate_period_from_type",
    # v10.15.0: Phase 2.5 Goal Notification (lazy)
    "GoalNotificationType",
    "sanitize_error",
    "build_daily_check_message",
    "build_daily_reminder_message",
    "build_morning_feedback_message",
    "build_team_summary_message",
    "build_consecutive_unanswered_alert_message",
    "send_daily_check_to_user",
    "send_daily_reminder_to_user",
    "send_morning_feedback_to_user",
    "send_team_summary_to_leader",
    "send_consecutive_unanswered_alert_to_leader",
    "scheduled_daily_check",
    "scheduled_daily_reminder",
    "scheduled_morning_feedback",
    "scheduled_consecutive_unanswered_check",
    "check_consecutive_unanswered_users",
    "can_view_goal",
    "get_viewable_user_ids",
    # v10.18.0: Phase 2進化版 A1 Detection (lazy)
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
    "ErrorCode",
    "IdempotencyKeyPrefix",
    "LogMessages",
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
    "InsightData",
    "DetectionContext",
    "DetectionResult",
    "PatternData",
    "BaseDetector",
    "PatternDetector",
    "validate_uuid",
    "truncate_text",
    # v10.18.0: Phase 2進化版 A1 Insights (lazy)
    "InsightFilter",
    "InsightSummary",
    "InsightRecord",
    "InsightService",
    "WeeklyReportRecord",
    "ReportInsightItem",
    "GeneratedReport",
    "WeeklyReportService",
    # v10.18.1: User Utils（Phase 3.5対応）(lazy)
    "get_user_primary_department",
    # v10.19.0: Phase 2.5 目標設定対話フロー (lazy)
    "GOAL_SETTING_STEPS",
    "GOAL_SETTING_STEP_ORDER",
    "GOAL_SETTING_MAX_RETRY",
    "GOAL_SETTING_TEMPLATES",
    "GOAL_SETTING_PATTERN_KEYWORDS",
    "GoalSettingDialogue",
    "has_active_goal_session",
    "process_goal_setting_message",
    # v10.24.9: 営業日判定 (lazy)
    "is_business_day",
    "is_weekend",
    "is_holiday",
    "get_holiday_name",
    "get_non_business_day_reason",
    # v10.31.0: Feature Flags（Phase C）(lazy)
    "FeatureFlags",
    "FlagCategory",
    "FlagType",
    "FlagInfo",
    "FLAG_DEFINITIONS",
    "get_flags",
    "reset_flags",
    "init_flags",
    "is_handler_enabled",
    "is_library_available",
    "is_feature_enabled",
    "get_brain_mode",
    "is_dry_run",
]
