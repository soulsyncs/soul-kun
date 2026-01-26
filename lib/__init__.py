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
"""

__version__ = "1.9.0"  # v10.31.0: Feature Flags一元管理追加

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

# Chatwork
from lib.chatwork import (
    # Sync
    ChatworkClient,
    # Async
    ChatworkAsyncClient,
)

# テナント管理
from lib.tenant import (
    TenantContext,
    get_current_tenant,
    set_current_tenant,
)

# Phase 3: Googleドライブ連携
from lib.google_drive import (
    GoogleDriveClient,
    DriveFile,
    DriveChange,
    SyncResult,
    FolderMapper,
    FolderMappingConfig,
)

# Phase 3: ドキュメント処理
from lib.document_processor import (
    DocumentProcessor,
    TextChunker,
    Chunk,
    ExtractedDocument,
    extract_text,
    extract_with_metadata,
)

# Phase 3: Pinecone連携
from lib.pinecone_client import (
    PineconeClient,
    SearchResult,
    SearchResponse,
)

# Phase 3: エンベディング
from lib.embedding import (
    EmbeddingClient,
    EmbeddingResult,
    BatchEmbeddingResult,
    embed_text,
    embed_text_sync,
    get_embedding_client,
)

# v10.14.1: テキスト処理ユーティリティ
# v10.17.0: prepare_task_display_text追加
from lib.text_utils import (
    # パターン定義
    GREETING_PATTERNS,
    CLOSING_PATTERNS,
    GREETING_STARTS,
    TRUNCATION_INDICATORS,
    # 関数
    remove_greetings,
    extract_task_subject,
    is_greeting_only,
    validate_summary,
    clean_chatwork_tags,
    validate_and_get_reason,
    prepare_task_display_text,  # v10.17.0追加
)

# v10.14.1: 監査ログ
from lib.audit import (
    AuditAction,
    AuditResourceType,
    log_audit,
    log_audit_batch,
)

# v10.15.0: Phase 2.5 目標管理
from lib.goal import (
    # 定数
    GoalLevel,
    GoalType,
    GoalStatus,
    PeriodType,
    Classification,
    ReminderType,
    # データクラス
    Goal,
    GoalProgress,
    # サービス
    GoalService,
    get_goal_service,
    # ヘルパー
    parse_goal_type_from_text,
    calculate_period_from_type,
)

# v10.15.0: Phase 2.5 目標通知サービス
from lib.goal_notification import (
    # 通知タイプ
    GoalNotificationType,
    # エラーサニタイズ
    sanitize_error,
    # メッセージビルダー
    build_daily_check_message,
    build_daily_reminder_message,
    build_morning_feedback_message,
    build_team_summary_message,
    build_consecutive_unanswered_alert_message,
    # 通知送信関数
    send_daily_check_to_user,
    send_daily_reminder_to_user,
    send_morning_feedback_to_user,
    send_team_summary_to_leader,
    send_consecutive_unanswered_alert_to_leader,
    # スケジュール関数
    scheduled_daily_check,
    scheduled_daily_reminder,
    scheduled_morning_feedback,
    scheduled_consecutive_unanswered_check,
    # 連続未回答チェック
    check_consecutive_unanswered_users,
    # アクセス権限
    can_view_goal,
    get_viewable_user_ids,
)

# v10.18.0: Phase 2進化版 A1 検出基盤
from lib.detection import (
    # 定数
    DetectionParameters,
    QuestionCategory,
    CATEGORY_KEYWORDS,
    PatternStatus,
    InsightStatus,
    WeeklyReportStatus,
    InsightType,
    SourceType,
    NotificationType,
    Importance,
    ErrorCode,
    IdempotencyKeyPrefix,
    LogMessages,
    # 例外
    DetectionBaseException,
    DetectionError,
    PatternSaveError,
    InsightCreateError,
    NotificationError,
    DatabaseError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    wrap_database_error,
    wrap_detection_error,
    # データクラス
    InsightData,
    DetectionContext,
    DetectionResult,
    PatternData,
    # 基底クラス
    BaseDetector,
    # 検出器
    PatternDetector,
    # ユーティリティ
    validate_uuid,
    truncate_text,
)

# v10.18.0: Phase 2進化版 A1 インサイト管理
from lib.insights import (
    # InsightService関連
    InsightFilter,
    InsightSummary,
    InsightRecord,
    InsightService,
    # WeeklyReportService関連
    WeeklyReportRecord,
    ReportInsightItem,
    GeneratedReport,
    WeeklyReportService,
)

# v10.18.1: ユーザー関連ユーティリティ（Phase 3.5対応）
from lib.user_utils import (
    get_user_primary_department,
)

# v10.19.0: Phase 2.5 目標設定対話フロー
from lib.goal_setting import (
    # 定数
    STEPS as GOAL_SETTING_STEPS,
    STEP_ORDER as GOAL_SETTING_STEP_ORDER,
    MAX_RETRY_COUNT as GOAL_SETTING_MAX_RETRY,
    TEMPLATES as GOAL_SETTING_TEMPLATES,
    PATTERN_KEYWORDS as GOAL_SETTING_PATTERN_KEYWORDS,
    # クラス
    GoalSettingDialogue,
    # ヘルパー関数
    has_active_goal_session,
    process_goal_setting_message,
)

# v10.24.9: 営業日判定（土日祝日リマインドスキップ）
from lib.business_day import (
    is_business_day,
    is_weekend,
    is_holiday,
    get_holiday_name,
    get_non_business_day_reason,
)

# v10.31.0: Feature Flags一元管理（Phase C）
from lib.feature_flags import (
    # クラス
    FeatureFlags,
    FlagCategory,
    FlagType,
    FlagInfo,
    # 定数
    FLAG_DEFINITIONS,
    # 関数
    get_flags,
    reset_flags,
    init_flags,
    # ヘルパー
    is_handler_enabled,
    is_library_available,
    is_feature_enabled,
    get_brain_mode,
    is_dry_run,
)

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
    # Phase 3: Google Drive
    "GoogleDriveClient",
    "DriveFile",
    "DriveChange",
    "SyncResult",
    "FolderMapper",
    "FolderMappingConfig",
    # Phase 3: Document Processing
    "DocumentProcessor",
    "TextChunker",
    "Chunk",
    "ExtractedDocument",
    "extract_text",
    "extract_with_metadata",
    # Phase 3: Pinecone
    "PineconeClient",
    "SearchResult",
    "SearchResponse",
    # Phase 3: Embedding
    "EmbeddingClient",
    "EmbeddingResult",
    "BatchEmbeddingResult",
    "embed_text",
    "embed_text_sync",
    "get_embedding_client",
    # v10.14.1: Text Utils
    # v10.17.0: prepare_task_display_text追加
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
    "prepare_task_display_text",  # v10.17.0追加
    # v10.14.1: Audit
    "AuditAction",
    "AuditResourceType",
    "log_audit",
    "log_audit_batch",
    # v10.15.0: Phase 2.5 Goal
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
    # v10.15.0: Phase 2.5 Goal Notification
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
    # v10.18.0: Phase 2進化版 A1 Detection
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
    # v10.18.0: Phase 2進化版 A1 Insights
    "InsightFilter",
    "InsightSummary",
    "InsightRecord",
    "InsightService",
    "WeeklyReportRecord",
    "ReportInsightItem",
    "GeneratedReport",
    "WeeklyReportService",
    # v10.18.1: User Utils（Phase 3.5対応）
    "get_user_primary_department",
    # v10.19.0: Phase 2.5 目標設定対話フロー
    "GOAL_SETTING_STEPS",
    "GOAL_SETTING_STEP_ORDER",
    "GOAL_SETTING_MAX_RETRY",
    "GOAL_SETTING_TEMPLATES",
    "GOAL_SETTING_PATTERN_KEYWORDS",
    "GoalSettingDialogue",
    "has_active_goal_session",
    "process_goal_setting_message",
    # v10.24.9: 営業日判定
    "is_business_day",
    "is_weekend",
    "is_holiday",
    "get_holiday_name",
    "get_non_business_day_reason",
    # v10.31.0: Feature Flags（Phase C）
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
