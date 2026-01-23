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

使用例（Flask/Cloud Functions）:
    from lib import get_secret, get_db_pool, ChatworkClient

使用例（FastAPI）:
    from lib import get_secret, get_async_db_pool, ChatworkAsyncClient

Phase 3 ナレッジ検索:
    from lib import GoogleDriveClient, DocumentProcessor, PineconeClient, EmbeddingClient

Phase 4対応:
    - 全モジュールがorganization_id（テナントID）を認識
    - sync/async両方をサポート
    - Cloud Run 100インスタンス対応のコネクションプール設計
"""

__version__ = "1.5.0"  # v10.17.0: prepare_task_display_text追加

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
]
