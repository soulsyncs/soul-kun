import functions_framework
from flask import jsonify
from google.cloud import secretmanager, firestore
import httpx
import re
import time
import os  # v10.22.4: 環境変数による機能制御用
import asyncio  # v10.21.0: Memory Framework統合用
from datetime import datetime, timedelta, timezone
from typing import Dict, Any  # v10.40.9: 型アノテーション用
import pg8000
import sqlalchemy
from google.cloud.sql.connector import Connector
import json
from functools import lru_cache
import traceback
import hmac  # v6.8.9: Webhook署名検証用
import hashlib  # v6.8.9: Webhook署名検証用
import base64  # v6.8.9: Webhook署名検証用

# テナントID（CLAUDE.md 鉄則#1: 全クエリにorganization_idフィルター必須）
_ORGANIZATION_ID = os.getenv("PHASE3_ORGANIZATION_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

# =====================================================
# Phase 11: infra/db.py からDB接続・シークレット管理をインポート
# =====================================================
from infra.db import (
    get_pool,
    get_secret,
    get_db_connection,
    PROJECT_ID,
)

# =====================================================
# Phase 11: 抽出モジュールからのインポート
# =====================================================
from infra.chatwork_api import (
    verify_chatwork_webhook_signature,
    get_chatwork_webhook_token,
    clean_chatwork_message,
    is_mention_or_reply_to_soulkun,
    should_ignore_toall,
    call_chatwork_api_with_retry,
    is_room_member,
    send_chatwork_message,
    get_all_rooms,
    get_room_messages,
    get_sender_name,
    get_all_contacts,
    get_direct_room,
    flush_dm_unavailable_notifications,
    get_all_chatwork_users,
    get_room_tasks,
    _get_room_tasks_safe,
    sync_room_members,
    MY_ACCOUNT_ID,
    MEMORY_DEFAULT_ORG_ID,
    reset_runtime_caches,
)
from infra.message_store import (
    is_processed,
    save_room_message,
    get_room_context,
    ensure_room_messages_table,
    ensure_processed_messages_table,
    mark_as_processed,
)
from infra.helpers import (
    match_local_command,
    is_admin,
    _fallback_truncate_text,
    send_completion_notification,
    should_show_guide,
    update_conversation_timestamp,
    LOCAL_COMMAND_PATTERNS,
    USE_ADMIN_CONFIG,
    ADMIN_ACCOUNT_ID,
)
from services.person_org import (
    _get_person_service,
    _get_org_chart_service,
    save_person_attribute,
    get_person_info,
    normalize_person_name,
    search_person_by_partial_name,
    delete_person,
    get_all_persons_summary,
    get_org_chart_overview,
    search_department_by_name,
    get_department_members,
    resolve_person_name,
    parse_attribute_string,
)
from services.task_ops import (
    _get_task_handler,
    add_task,
    get_tasks,
    update_task_status,
    delete_task,
    get_chatwork_account_id_by_name,
    create_chatwork_task,
    complete_chatwork_task,
    search_tasks_from_db,
    update_task_status_in_db,
    save_chatwork_task_to_db,
    log_analytics_event,
)
from services.task_actions import (
    get_pending_task,
    save_pending_task,
    delete_pending_task,
    parse_date_from_text,
    check_deadline_proximity,
    clean_task_body_for_summary,
    generate_deadline_alert_message,
    log_deadline_alert,
    handle_chatwork_task_create,
    handle_chatwork_task_complete,
    handle_chatwork_task_search,
    handle_pending_task_followup,
)
from services.memory_actions import (
    handle_save_memory,
    handle_query_memory,
    handle_delete_memory,
    handle_learn_knowledge,
    handle_forget_knowledge,
    handle_list_knowledge,
)
from services.proposal_actions import (
    _get_proposal_handler,
    create_proposal,
    get_pending_proposals,
    get_unnotified_proposals,
    retry_proposal_notification,
    report_proposal_to_admin,
    handle_proposal_decision,
    handle_proposal_by_id,
    handle_list_pending_proposals,
    handle_list_unnotified_proposals,
    handle_retry_notification,
)
from services.goal_actions import (
    _get_goal_handler,
    handle_goal_registration,
    handle_goal_progress_report,
    handle_goal_status_check,
    handle_goal_review,
    handle_goal_consult,
    handle_goal_delete,
    handle_goal_cleanup,
)
from services.org_knowledge_actions import (
    handle_query_org_chart,
    handle_api_limitation,
    handle_query_company_knowledge,
    handle_daily_reflection,
)
from services.knowledge_ops import _get_knowledge_handler


# =====================================================
# v10.30.1: 管理者設定モジュール（Phase A）
# =====================================================
# ハードコードされていた ADMIN_ACCOUNT_ID, ADMIN_ROOM_ID を
# データベースから取得するモジュール
try:
    from lib.admin_config import (
        get_admin_config,
        is_admin_account,
        DEFAULT_ORG_ID as ADMIN_CONFIG_DEFAULT_ORG_ID,
    )
    USE_ADMIN_CONFIG = True
    print("✅ lib/admin_config.py loaded for admin configuration")
except ImportError as e:
    print(f"⚠️ lib/admin_config.py not available (using fallback): {e}")
    USE_ADMIN_CONFIG = False

# v10.31.1: Phase D - 接続設定集約 → infra/db.py に移動（Phase 11）

# =====================================================
# v10.18.1: summary生成用ライブラリ
# =====================================================
from lib import (
    clean_chatwork_tags,
    prepare_task_display_text,
    extract_task_subject,
    validate_summary,
)
print("✅ lib/text_utils.py loaded for summary generation")

# =====================================================
# v10.18.1: ユーザーユーティリティ（Phase 3.5対応）
# =====================================================
from lib import (
    get_user_primary_department as lib_get_user_primary_department,
)
print("✅ lib/user_utils.py loaded for department_id")

# =====================================================
# v10.26.0: 営業日判定ユーティリティ
# =====================================================
from lib.business_day import (
    is_business_day,
    get_non_business_day_reason,
)
print("✅ lib/business_day.py loaded for holiday detection")

# =====================================================
# v10.19.0: Phase 2.5 目標設定対話フロー
# =====================================================
from lib import (
    has_active_goal_session,
    process_goal_setting_message,
)
print("✅ lib/goal_setting.py loaded for goal setting dialogue")

# =====================================================
# v10.40.8: ユーザー長期記憶（プロフィール）
# =====================================================
from lib.long_term_memory import (
    is_long_term_memory_request,
    save_long_term_memory,
    LongTermMemoryManager,
)
print("✅ lib/long_term_memory.py loaded for user profile memory")

# =====================================================
# v10.40.9: ボットペルソナ記憶
# =====================================================
try:
    from lib.bot_persona_memory import (
        is_bot_persona_setting,
        save_bot_persona,
        BotPersonaMemoryManager,
    )
    USE_BOT_PERSONA_MEMORY = True
    print("✅ lib/bot_persona_memory.py loaded for bot persona settings")
except ImportError as e:
    print(f"⚠️ lib/bot_persona_memory.py not available: {e}")
    USE_BOT_PERSONA_MEMORY = False

# =====================================================
# v10.43.0: 人格レイヤー（Company Persona + Add-on）
# v10.46.0: Persona観測ログ追加
# v2.1.0: システムプロンプト v2.1（2026-01-29）
# =====================================================
try:
    from lib.persona import build_persona_prompt, log_persona_path
    USE_PERSONA_LAYER = True
    # 安全制限: Personaプロンプトの最大文字数（トークン肥大化防止）
    MAX_PERSONA_CHARS = 1200
    print("✅ lib/persona loaded for Company Persona + Add-on")
except ImportError as e:
    print(f"⚠️ lib/persona not available: {e}")
    USE_PERSONA_LAYER = False
    MAX_PERSONA_CHARS = 0
    # フォールバック用ダミー関数
    def log_persona_path(*args, **kwargs):
        pass

# =====================================================
# v10.48.0: 人物情報サービス（2026-01-29）
# main.pyから分割された人物情報関連の関数
# =====================================================
try:
    from lib.person_service import PersonService, OrgChartService, normalize_person_name as _svc_normalize_person_name
    USE_PERSON_SERVICE = True
    print("✅ lib/person_service.py loaded for Person management")
except ImportError as e:
    print(f"⚠️ lib/person_service.py not available: {e}")
    USE_PERSON_SERVICE = False

# =====================================================
# v2.1.0: システムプロンプト v2.1（2026-01-29）
# 環境変数 ENABLE_SYSTEM_PROMPT_V2=true で有効化
# docs/24_polished_system_prompt.md に基づく新しいプロンプト
# =====================================================
_SYSTEM_PROMPT_V2_ENABLED_BY_ENV = os.environ.get("ENABLE_SYSTEM_PROMPT_V2", "").lower() == "true"

if _SYSTEM_PROMPT_V2_ENABLED_BY_ENV:
    try:
        from lib.persona import get_system_prompt_v2, get_system_prompt_v2_simple
        USE_SYSTEM_PROMPT_V2 = True
        print("✅ System Prompt v2.1 ENABLED (lib/persona/system_prompt_v2.py)")
    except ImportError as e:
        print(f"⚠️ System Prompt v2.1 not available: {e}")
        USE_SYSTEM_PROMPT_V2 = False
else:
    USE_SYSTEM_PROMPT_V2 = False
    print("ℹ️ System Prompt v2.1 disabled (set ENABLE_SYSTEM_PROMPT_V2=true to enable)")

# =====================================================
# v10.21.0: Phase 2 B 記憶機能（Memory Framework）統合
# =====================================================
try:
    from lib.memory import (
        ConversationSummary,
        ConversationSearch,
    )
    USE_MEMORY_FRAMEWORK = True
    print("✅ lib/memory loaded for Memory Framework integration")
except ImportError as e:
    print(f"⚠️ lib/memory not available: {e}")
    USE_MEMORY_FRAMEWORK = False

# Memory Framework用定数
MEMORY_SUMMARY_TRIGGER_COUNT = 10  # サマリー生成の閾値（会話数）
MEMORY_DEFAULT_ORG_ID = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"  # ソウルシンクスの組織ID

# =====================================================
# v10.22.0: Phase 2C MVV・組織論的行動指針
# =====================================================
# 環境変数 DISABLE_MVV_CONTEXT=true で無効化可能（段階的デプロイ用）
_MVV_DISABLED_BY_ENV = os.environ.get("DISABLE_MVV_CONTEXT", "").lower() == "true"

if _MVV_DISABLED_BY_ENV:
    print("⚠️ MVV Context disabled by environment variable DISABLE_MVV_CONTEXT=true")
    USE_MVV_CONTEXT = False
    ORGANIZATIONAL_THEORY_PROMPT = ""
else:
    try:
        from lib.mvv_context import (
            detect_ng_pattern,
            analyze_basic_needs,
            ORGANIZATIONAL_THEORY_PROMPT,
            RiskLevel,
            is_mvv_question,
            get_full_mvv_info,
        )
        USE_MVV_CONTEXT = True
        print("✅ lib/mvv_context.py loaded for organizational theory guidelines")
    except ImportError as e:
        print(f"⚠️ lib/mvv_context.py not available: {e}")
        USE_MVV_CONTEXT = False
        ORGANIZATIONAL_THEORY_PROMPT = ""  # フォールバック

# =====================================================
# utils/date_utils.py 日付処理ユーティリティ
# v10.33.0: フォールバック削除
# =====================================================
from utils.date_utils import (
    parse_date_from_text as _new_parse_date_from_text,
    check_deadline_proximity as _new_check_deadline_proximity,
    get_overdue_days,  # v10.33.2: OverdueHandlerで使用
)
# v10.33.1: USE_NEW_DATE_UTILS削除（未使用、フォールバックは既に削除済み）
print("✅ utils/date_utils.py loaded for date processing")

# =====================================================
# utils/chatwork_utils.py ChatWork APIユーティリティ
# v10.33.0: フォールバック削除
# =====================================================
from utils.chatwork_utils import (
    APICallCounter as _new_APICallCounter,
    # v10.40.3: 未使用インポート削除
    # - get_api_call_counter, reset_api_call_counter, clear_room_members_cache
    # - is_toall_mention
    # v10.40.5: get_room_members復元（AnnouncementHandlerで使用）
    get_room_members,
    call_chatwork_api_with_retry as _new_call_chatwork_api_with_retry,
    is_room_member as _new_is_room_member,
    # v10.48.0: メッセージ処理関数
    clean_chatwork_message as _utils_clean_chatwork_message,
    is_mention_or_reply_to as _utils_is_mention_or_reply_to,
    should_ignore_toall as _utils_should_ignore_toall,
)
# v10.33.1: USE_NEW_CHATWORK_UTILS削除（未使用、フォールバックは既に削除済み）
print("✅ utils/chatwork_utils.py loaded for ChatWork API")

# =====================================================
# handlers/proposal_handler.py 提案管理ハンドラー
# v10.33.0: フォールバック削除（ハンドラー必須化）
# =====================================================
from handlers.proposal_handler import ProposalHandler as _NewProposalHandler
print("✅ handlers/proposal_handler.py loaded for Proposal management")

# ProposalHandlerインスタンス（後で初期化）
_proposal_handler = None

# =====================================================
# handlers/memory_handler.py メモリ管理ハンドラー
# v10.33.0: フォールバック削除（ハンドラー必須化）
# =====================================================
from handlers.memory_handler import MemoryHandler as _NewMemoryHandler
print("✅ handlers/memory_handler.py loaded for Memory management")

# MemoryHandlerインスタンス（後で初期化）
_memory_handler = None

# =====================================================
# handlers/task_handler.py タスク管理ハンドラー
# v10.33.0: フォールバック削除（ハンドラー必須化）
# =====================================================
from handlers.task_handler import TaskHandler as _NewTaskHandler
print("✅ handlers/task_handler.py loaded for Task management")

# TaskHandlerインスタンス（後で初期化）
_task_handler = None

# =====================================================
# handlers/overdue_handler.py 遅延管理ハンドラー
# v10.33.0: フォールバック削除（ハンドラー必須化）
# =====================================================
from handlers.overdue_handler import OverdueHandler as _NewOverdueHandler
print("✅ handlers/overdue_handler.py loaded for Overdue management")

# OverdueHandlerインスタンス（後で初期化）
_overdue_handler = None

# =====================================================
# handlers/goal_handler.py 目標達成支援ハンドラー
# v10.33.0: フォールバック削除（ハンドラー必須化）
# =====================================================
from handlers.goal_handler import GoalHandler as _NewGoalHandler
print("✅ handlers/goal_handler.py loaded for Goal management")

# GoalHandlerインスタンス（後で初期化）
_goal_handler = None

# =====================================================
# handlers/knowledge_handler.py ナレッジ管理ハンドラー
# v10.33.0: フォールバック削除（ハンドラー必須化）
# =====================================================
from handlers.knowledge_handler import KnowledgeHandler as _NewKnowledgeHandler
print("✅ handlers/knowledge_handler.py loaded for Knowledge management")

# KnowledgeHandlerインスタンス（後で初期化）
_knowledge_handler = None

# =====================================================
# handlers/announcement_handler.py アナウンスハンドラー
# v10.33.0: フォールバック削除（ハンドラー必須化）
# =====================================================
from handlers.announcement_handler import AnnouncementHandler as _NewAnnouncementHandler
print("✅ handlers/announcement_handler.py loaded for Announcement feature")

# AnnouncementHandlerインスタンス（後で初期化）
_announcement_handler = None

# =====================================================
# v10.47.0: ハンドラーレジストリ（Phase 2整理整頓）
# 設計書: handlers/registry.py
# =====================================================
# SYSTEM_CAPABILITIESと関連ユーティリティ関数を一元管理
# 「新機能追加 = handlers/xxx_handler.py作成 + registry.pyに1エントリ追加」
# =====================================================
from handlers.registry import (
    SYSTEM_CAPABILITIES,
    HANDLER_ALIASES,
    get_enabled_capabilities,
    get_capability_info,
    generate_capabilities_prompt,
)
print("✅ handlers/registry.py loaded for capability catalog")

# =====================================================
# v10.29.0: 脳アーキテクチャ（Brain Architecture）
# 環境変数 USE_BRAIN_ARCHITECTURE で有効化（段階的導入）
# 設定値: false（無効）/ true（有効）/ shadow（シャドウ）/ gradual（段階的）
# 設計書: docs/13_brain_architecture.md
# =====================================================
try:
    from lib.brain import (
        # Version (単一ソース)
        BRAIN_VERSION,
        # Core classes
        SoulkunBrain,
        BrainResponse,
        BrainContext,
        StateType,
        # Integration Layer (Phase H)
        BrainIntegration,
        IntegrationResult,
        IntegrationConfig,
        IntegrationMode,
        create_integration,
        is_brain_enabled,
    )
    USE_BRAIN_ARCHITECTURE = is_brain_enabled()  # 環境変数から判定
    _brain_mode = os.environ.get("USE_BRAIN_ARCHITECTURE", "false").lower()
    print(f"✅ lib/brain loaded (v{BRAIN_VERSION}), enabled={USE_BRAIN_ARCHITECTURE}, mode={_brain_mode}")
except ImportError as e:
    print(f"⚠️ lib/brain not available: {e}")
    USE_BRAIN_ARCHITECTURE = False
    BrainIntegration = None
    IntegrationResult = None
    IntegrationConfig = None
    IntegrationMode = None
    create_integration = None
    is_brain_enabled = None

# v10.33.1: _brain_instanceを削除（_get_brain()と共に削除、BrainIntegration経由に移行済み）
# BrainIntegrationインスタンス（v10.29.0: Phase H統合層）
_brain_integration = None
# CapabilityBridgeインスタンス（v10.38.0: Brain-Capability統合）
_capability_bridge = None

# =====================================================
# v10.38.0: Capability Bridge（脳-機能統合層）
# 設計書: docs/brain_capability_integration_design.md
# =====================================================
try:
    from lib.brain.capability_bridge import (
        CapabilityBridge,
        create_capability_bridge,
        GENERATION_CAPABILITIES,
        DEFAULT_FEATURE_FLAGS as CAPABILITY_FEATURE_FLAGS,
    )
    USE_CAPABILITY_BRIDGE = True
    print("✅ lib/brain/capability_bridge.py loaded for brain-capability integration")
except ImportError as e:
    print(f"⚠️ lib/brain/capability_bridge.py not available: {e}")
    USE_CAPABILITY_BRIDGE = False
    CapabilityBridge = None
    create_capability_bridge = None
    GENERATION_CAPABILITIES = {}
    CAPABILITY_FEATURE_FLAGS = {}

# =====================================================
# v10.40.2: ハンドラーラッパー（main.py軽量化）
# 脳用ハンドラーをlib/brain/handler_wrappers.pyに移動
# =====================================================
try:
    from lib.brain.handler_wrappers import (
        # ビルダー関数
        build_bypass_handlers,
        build_brain_handlers,
        build_session_handlers,
        get_session_management_functions,
        # 個別ハンドラー（直接参照用）
        _brain_handle_task_search,
        _brain_handle_task_create,
        _brain_handle_task_complete,
        _brain_handle_query_knowledge,
        _brain_handle_save_memory,
        _brain_handle_query_memory,
        _brain_handle_delete_memory,
        _brain_handle_learn_knowledge,
        _brain_handle_forget_knowledge,
        _brain_handle_list_knowledge,
        _brain_handle_goal_setting_start,
        _brain_handle_goal_progress_report,
        _brain_handle_goal_status_check,
        _brain_handle_goal_review,
        _brain_handle_goal_consult,
        _brain_handle_goal_delete,  # v10.56.2: 目標削除
        _brain_handle_goal_cleanup,  # v10.56.2: 目標整理
        _brain_handle_announcement_create,
        _brain_handle_query_org_chart,
        _brain_handle_daily_reflection,
        _brain_handle_proposal_decision,
        _brain_handle_api_limitation,
        _brain_handle_general_conversation,
        # セッション継続ハンドラー
        _brain_continue_goal_setting,
        _brain_continue_announcement,
        _brain_continue_task_pending,
        # セッション管理
        _brain_interrupt_goal_setting,
        _brain_get_interrupted_goal_setting,
        _brain_resume_goal_setting,
        # v10.40.3: ポーリング処理
        validate_polling_message,
        should_skip_polling_message,
        process_polling_message,
        process_polling_room,
    )
    USE_HANDLER_WRAPPERS = True
    print("✅ lib/brain/handler_wrappers.py loaded for brain handlers")
except ImportError as e:
    print(f"⚠️ lib/brain/handler_wrappers.py not available: {e}")
    USE_HANDLER_WRAPPERS = False
    build_bypass_handlers = None
    build_brain_handlers = None
    build_session_handlers = None
    get_session_management_functions = None
    # v10.40.3: ポーリング処理
    validate_polling_message = None
    should_skip_polling_message = None
    process_polling_message = None
    process_polling_room = None

# PROJECT_ID → infra/db.py から import（Phase 11）
db = firestore.Client(project=PROJECT_ID)
# Cloud SQL設定（フォールバック用）→ infra/db.py に移動（Phase 11）

# 会話履歴の設定
MAX_HISTORY_COUNT = 100      # 100件に増加
HISTORY_EXPIRY_HOURS = 720   # 30日（720時間）に延長

# OpenRouter設定
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# =====================================================
# v10.12.0: モデル設定（2026年1月更新）
# =====================================================
# Gemini 3 Flashに統一（コスト最適化）
# - 高速・低コスト・高品質のバランス
# - OpenRouter経由: google/gemini-3-flash-preview
# - コスト: $0.50/1M入力, $3.00/1M出力
# =====================================================
MODELS = {
    "default": "google/gemini-3-flash-preview",
    "commander": "google/gemini-3-flash-preview",  # 司令塔AI
}

# =====================================================
# v10.13.0: Phase 3 ナレッジ検索API設定
# =====================================================
# Pineconeベクトル検索APIとの統合設定
# 旧システム（soulkun_knowledge）と併用
# =====================================================
# v10.33.1: 重複import os削除（line 7で既にインポート済み）

PHASE3_KNOWLEDGE_CONFIG = {
    "api_url": os.getenv(
        "KNOWLEDGE_SEARCH_API_URL",
        "https://soulkun-api-898513057014.asia-northeast1.run.app/api/v1/knowledge/search"
    ),
    "enabled": os.getenv("ENABLE_PHASE3_KNOWLEDGE", "true").lower() == "true",
    "timeout": float(os.getenv("PHASE3_TIMEOUT", "30")),  # v10.13.3: 30秒に延長
    "similarity_threshold": float(os.getenv("PHASE3_SIMILARITY_THRESHOLD", "0.5")),  # v10.13.3: 0.5に下げる
    "organization_id": os.getenv("PHASE3_ORGANIZATION_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df"),
    # v10.13.3: ハイブリッド検索の重み設定
    "keyword_weight": float(os.getenv("PHASE3_KEYWORD_WEIGHT", "0.4")),
    "vector_weight": float(os.getenv("PHASE3_VECTOR_WEIGHT", "0.6")),
}

# =====================================================
# v10.13.3: ハイブリッド検索用キーワード・クエリ拡張
# =====================================================

# 業務関連キーワード辞書
KNOWLEDGE_KEYWORDS = [
    # 休暇関連
    "有給休暇", "有給", "年休", "年次有給休暇", "休暇", "休み",
    "特別休暇", "慶弔休暇", "産休", "育休", "介護休暇",
    # 賃金関連
    "賞与", "ボーナス", "給与", "賃金", "手当", "基本給",
    "残業代", "時間外手当", "深夜手当", "休日手当",
    # 勤務関連
    "残業", "時間外労働", "勤務時間", "休日", "労働時間",
    "始業", "終業", "休憩", "フレックス",
    # 福利厚生
    "経費", "精算", "交通費", "出張",
    # 人事関連
    "退職", "休職", "異動", "昇給", "昇格", "評価",
    # 規則関連
    "就業規則", "服務規律", "懲戒", "解雇",
]

# クエリ拡張辞書（エンベディングモデルが理解しやすいフレーズに展開）
QUERY_EXPANSION_MAP = {
    # 有給休暇関連
    "有給休暇": "年次有給休暇 付与日数 入社6か月後 10日 勤続年数",
    "有給": "年次有給休暇 付与日数 入社6か月後 10日 勤続年数",
    "年休": "年次有給休暇 付与日数 入社6か月後 10日 勤続年数",
    # 賞与関連
    "賞与": "賞与 ボーナス 支給 算定期間 支給日",
    "ボーナス": "賞与 ボーナス 支給 算定期間 支給日",
    # 残業関連
    "残業": "時間外労働 残業 割増賃金 36協定 上限",
    # 退職関連
    "退職": "退職 退職届 退職金 予告期間 14日前",
}


# ボット自身の名前パターン
BOT_NAME_PATTERNS = [
    "ソウルくん", "ソウル君", "ソウル", "そうるくん", "そうる",
    "soulkun", "soul-kun", "soul"
]

# ソウルくんのaccount_id
MY_ACCOUNT_ID = "10909425"
# v10.33.1: BOT_ACCOUNT_ID削除（MY_ACCOUNT_IDと同一で未使用）

# =====================================================
# v6.9.0: 管理者学習機能
# v10.30.1: Phase A - DB化（lib/admin_config.py）
# =====================================================
# 管理者設定はDBから取得。フォールバック値も維持。
# USE_ADMIN_CONFIG=True の場合はDBから取得
# USE_ADMIN_CONFIG=False の場合は従来のハードコード値を使用
if USE_ADMIN_CONFIG:
    # DBから取得した値を使用（キャッシュ付き）
    _admin_config = get_admin_config()
    ADMIN_ACCOUNT_ID = _admin_config.admin_account_id
    ADMIN_ROOM_ID = int(_admin_config.admin_room_id)
    print(f"✅ Admin config loaded from DB: account={ADMIN_ACCOUNT_ID}, room={ADMIN_ROOM_ID}")
else:
    # フォールバック: 従来のハードコード値
    ADMIN_ACCOUNT_ID = "1728974"
    ADMIN_ROOM_ID = 405315911
    print(f"⚠️ Using hardcoded admin config: account={ADMIN_ACCOUNT_ID}, room={ADMIN_ROOM_ID}")

# =====================================================
# v6.9.1: ローカルコマンド判定（API制限対策）
# v6.9.2: 正規表現改善 + 未通知再送機能追加
# =====================================================
# 明確なコマンドは正規表現で判定し、AIを呼ばずに直接処理
# これによりAPI呼び出し回数を大幅削減
# =====================================================
# v10.33.1: 重複import re削除（line 5で既にインポート済み）

LOCAL_COMMAND_PATTERNS = [
    # 承認・却下（ID指定必須）
    (r'^承認\s*(\d+)$', 'approve_proposal_by_id'),
    (r'^却下\s*(\d+)$', 'reject_proposal_by_id'),
    # 承認待ち一覧
    (r'^承認待ち(一覧)?$', 'list_pending_proposals'),
    (r'^(提案|ていあん)(一覧|リスト)$', 'list_pending_proposals'),
    # v6.9.2: 未通知提案一覧・再通知
    (r'^未通知(提案)?(一覧)?$', 'list_unnotified_proposals'),
    (r'^通知失敗(一覧)?$', 'list_unnotified_proposals'),
    (r'^再通知\s*(\d+)$', 'retry_notification'),
    (r'^再送\s*(\d+)$', 'retry_notification'),
    # 知識学習（フォーマット固定）
    # v6.9.2: 非貪欲(.+?) + スペース許容(\s*)に改善
    (r'^設定[：:]\s*(.+?)\s*[=＝]\s*(.+)$', 'learn_knowledge_formatted'),
    (r'^設定[：:]\s*(.+)$', 'learn_knowledge_simple'),
    (r'^覚えて[：:]\s*(.+)$', 'learn_knowledge_simple'),
    # 知識削除
    (r'^忘れて[：:]\s*(.+)$', 'forget_knowledge'),
    (r'^設定削除[：:]\s*(.+)$', 'forget_knowledge'),
    # 知識一覧
    (r'^何覚えてる[？?]?$', 'list_knowledge'),
    (r'^設定(一覧|リスト)$', 'list_knowledge'),
    (r'^学習(済み)?(知識|内容)(一覧)?$', 'list_knowledge'),
]


# 遅延管理設定
ESCALATION_DAYS = 3  # エスカレーションまでの日数

# Cloud SQL接続プール → infra/db.py に移動（Phase 11）
# 実行内メモリキャッシュ → infra/chatwork_api.py に移動（Phase 11）

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

# =====================================================
# v10.3.0: 期限ガードレール設定
# =====================================================
# タスク追加時に期限が近すぎる場合にアラートを表示
# 当日(0)と明日(1)の場合にアラートを送信
# =====================================================
DEADLINE_ALERT_DAYS = {
    0: "今日",    # 当日
    1: "明日",    # 翌日
}

# =====================================================
# ===== 機能カタログ（SYSTEM_CAPABILITIES） =====
# =====================================================
# v10.47.0: handlers/registry.py に移動
# インポートは上部で実施済み:
#   from handlers.registry import (
#       SYSTEM_CAPABILITIES,
#       HANDLER_ALIASES,
#       get_enabled_capabilities,
#       get_capability_info,
#       generate_capabilities_prompt,
#   )
# =====================================================


# クラスをエクスポート（互換性維持）
APICallCounter = _new_APICallCounter


def _get_overdue_handler():
    """OverdueHandlerのシングルトンインスタンスを取得（v10.33.0: フラグチェック削除）"""
    global _overdue_handler
    if _overdue_handler is None:
        _overdue_handler = _NewOverdueHandler(
            get_pool=get_pool,
            get_secret=get_secret,
            get_direct_room=get_direct_room,
            get_overdue_days_func=get_overdue_days,
            admin_room_id=str(ADMIN_ROOM_ID),
            escalation_days=ESCALATION_DAYS,
            prepare_task_display_text=prepare_task_display_text
        )
    return _overdue_handler


# =====================================================
# GoalHandler初期化（v10.24.6）
# v10.33.0: フラグチェック削除（ハンドラー必須化）
# =====================================================


# =====================================================
# KnowledgeHandler初期化（v10.24.7）
# v10.33.0: フラグチェック削除（ハンドラー必須化）
# =====================================================


# =====================================================
# AnnouncementHandler初期化（v10.26.0）
# v10.33.0: フラグチェック削除（ハンドラー必須化）
# =====================================================
def _get_announcement_handler():
    """AnnouncementHandlerのシングルトンインスタンスを取得"""
    global _announcement_handler
    if _announcement_handler is None:
        # v10.30.1: admin_configからDB設定を取得
        if USE_ADMIN_CONFIG:
            admin_cfg = get_admin_config()
            authorized_rooms = set(admin_cfg.authorized_room_ids) or {int(admin_cfg.admin_room_id)}
            admin_acct_id = admin_cfg.admin_account_id
            admin_dm_room = admin_cfg.admin_dm_room_id
            org_id = admin_cfg.organization_id
        else:
            authorized_rooms = {405315911}
            admin_acct_id = ADMIN_ACCOUNT_ID
            admin_dm_room = None
            org_id = ADMIN_CONFIG_DEFAULT_ORG_ID if USE_ADMIN_CONFIG else "5f98365f-e7c5-4f48-9918-7fe9aabae5df"

        _announcement_handler = _NewAnnouncementHandler(
            get_pool=get_pool,
            get_secret=get_secret,
            call_chatwork_api_with_retry=call_chatwork_api_with_retry,
            get_room_members=get_room_members,
            get_all_rooms=get_all_rooms,
            create_chatwork_task=create_chatwork_task,
            send_chatwork_message=send_chatwork_message,
            is_business_day=is_business_day,
            get_non_business_day_reason=get_non_business_day_reason,
            authorized_room_ids=authorized_rooms,
            admin_account_id=admin_acct_id,
            organization_id=org_id,
            kazu_dm_room_id=admin_dm_room,
        )
    return _announcement_handler


# =====================================================
# v10.38.0: Capability Bridge インスタンス取得
# =====================================================
def _get_capability_bridge():
    """
    CapabilityBridgeのシングルトンインスタンスを取得

    v10.38.0: 脳と機能モジュールの橋渡し層
    - マルチモーダル前処理
    - 生成ハンドラー（document, image, video）
    """
    global _capability_bridge
    if _capability_bridge is None and USE_CAPABILITY_BRIDGE and create_capability_bridge:
        try:
            _capability_bridge = create_capability_bridge(
                pool=get_pool(),
                org_id=ADMIN_CONFIG_DEFAULT_ORG_ID if USE_ADMIN_CONFIG else "5f98365f-e7c5-4f48-9918-7fe9aabae5df",
                feature_flags={
                    "ENABLE_DOCUMENT_GENERATION": True,
                    "ENABLE_IMAGE_GENERATION": True,
                    "ENABLE_VIDEO_GENERATION": os.environ.get("ENABLE_VIDEO_GENERATION", "false").lower() == "true",
                },
            )
            print("✅ CapabilityBridge initialized")
        except Exception as e:
            print(f"⚠️ CapabilityBridge initialization failed: {e}")
            _capability_bridge = None
    return _capability_bridge


# =====================================================
# v10.29.0: 脳アーキテクチャ - BrainIntegration初期化
# v10.38.0: CapabilityBridgeハンドラー統合
# v10.40.2: handler_wrappers.pyに移行
# =====================================================
def _get_brain_integration():
    """
    BrainIntegrationのシングルトンインスタンスを取得

    v10.29.0: SoulkunBrain直接使用からBrainIntegrationへ移行
    - シャドウモード、段階的ロールアウト、フォールバックをサポート
    - 環境変数 USE_BRAIN_ARCHITECTURE で制御

    v10.38.0: CapabilityBridgeのハンドラーを統合
    - 生成ハンドラー（generate_document, generate_image, generate_video）

    v10.40.2: handler_wrappers.pyからハンドラーを構築
    - build_brain_handlers(): 基本ハンドラー
    - build_session_handlers(): セッション継続ハンドラー
    - get_session_management_functions(): 中断・再開管理
    """
    global _brain_integration
    if _brain_integration is None and USE_BRAIN_ARCHITECTURE and create_integration:
        # v10.40.2: handler_wrappers.pyからハンドラーを構築
        if USE_HANDLER_WRAPPERS and build_brain_handlers:
            # ビルダー関数を使用（推奨）
            handlers = build_brain_handlers()
            # セッション継続ハンドラーを追加
            session_handlers = build_session_handlers()
            handlers.update({
                "continue_goal_setting": session_handlers.get("goal_setting"),
                "continue_announcement": session_handlers.get("announcement"),
                "continue_task_pending": session_handlers.get("task_pending"),
                "continue_list_context": session_handlers.get("list_context"),  # v10.56.2
            })
            # セッション管理関数を追加
            session_mgmt = get_session_management_functions()
            handlers.update(session_mgmt)
            # main.py固有の設定
            handlers["_pool"] = get_pool()
        else:
            # フォールバック: 直接参照（handler_wrappers.pyが使えない場合）
            handlers = {
                "chatwork_task_search": _brain_handle_task_search,
                "chatwork_task_create": _brain_handle_task_create,
                "chatwork_task_complete": _brain_handle_task_complete,
                "query_knowledge": _brain_handle_query_knowledge,
                "save_memory": _brain_handle_save_memory,
                "query_memory": _brain_handle_query_memory,
                "delete_memory": _brain_handle_delete_memory,
                "learn_knowledge": _brain_handle_learn_knowledge,
                "forget_knowledge": _brain_handle_forget_knowledge,
                "list_knowledge": _brain_handle_list_knowledge,
                "goal_registration": _brain_handle_goal_setting_start,
                "goal_progress_report": _brain_handle_goal_progress_report,
                "goal_status_check": _brain_handle_goal_status_check,
                "goal_review": _brain_handle_goal_review,
                "goal_consult": _brain_handle_goal_consult,
                "goal_delete": _brain_handle_goal_delete,  # v10.56.2: 目標削除
                "goal_cleanup": _brain_handle_goal_cleanup,  # v10.56.2: 目標整理
                "announcement_create": _brain_handle_announcement_create,
                "query_org_chart": _brain_handle_query_org_chart,
                "daily_reflection": _brain_handle_daily_reflection,
                "proposal_decision": _brain_handle_proposal_decision,
                "api_limitation": _brain_handle_api_limitation,
                "general_conversation": _brain_handle_general_conversation,
                "continue_goal_setting": _brain_continue_goal_setting,
                "continue_announcement": _brain_continue_announcement,
                "continue_task_pending": _brain_continue_task_pending,
                "interrupt_goal_setting": _brain_interrupt_goal_setting,
                "get_interrupted_goal_setting": _brain_get_interrupted_goal_setting,
                "resume_goal_setting": _brain_resume_goal_setting,
                "_pool": get_pool(),
            }

        # v10.38.0: CapabilityBridgeのハンドラーを追加
        bridge = _get_capability_bridge()
        if bridge:
            try:
                capability_handlers = bridge.get_capability_handlers()
                handlers.update(capability_handlers)
                print(f"✅ CapabilityBridge handlers added: {list(capability_handlers.keys())}")
            except Exception as e:
                print(f"⚠️ CapabilityBridge handlers failed: {e}")
        # BUG-018修正: execution.pyのインターフェースに合わせたラッパー関数
        # execution.pyは (recent_conv, context_dict) で呼ぶが、
        # get_ai_responseは (message, history, sender_name, context) を期待
        def _brain_ai_response_wrapper(recent_conv, context_dict):
            """脳アーキテクチャ用のAI応答ラッパー"""
            try:
                # 最後のユーザーメッセージを取得
                message = ""
                for msg in reversed(recent_conv or []):
                    if isinstance(msg, dict):
                        if msg.get("role") == "user":
                            message = msg.get("content", "")
                            break
                    elif hasattr(msg, "role") and msg.role == "user":
                        message = msg.content if hasattr(msg, "content") else ""
                        break

                # sender_nameをコンテキストから取得
                sender_name = context_dict.get("sender_name", "") if context_dict else ""
                # v10.43.0: account_idをコンテキストから取得（Persona用）
                account_id = context_dict.get("account_id") if context_dict else None

                # historyを準備（会話履歴形式に変換）
                history = []
                for msg in (recent_conv or []):
                    if isinstance(msg, dict):
                        history.append(msg)
                    elif hasattr(msg, "to_dict"):
                        history.append(msg.to_dict())

                return get_ai_response(message, history, sender_name, context_dict, "ja", account_id)
            except Exception as e:
                print(f"⚠️ _brain_ai_response_wrapper error: {e}")
                return "申し訳ないウル、応答生成中にエラーが発生したウル🐺"

        try:
            # v10.29.7: SYSTEM_CAPABILITIESは必ずモジュールレベルで定義されている
            _brain_integration = create_integration(
                pool=get_pool(),
                org_id=ADMIN_CONFIG_DEFAULT_ORG_ID if USE_ADMIN_CONFIG else "5f98365f-e7c5-4f48-9918-7fe9aabae5df",
                handlers=handlers,
                capabilities=SYSTEM_CAPABILITIES,  # 直接参照（in dir()は機能しない）
                get_ai_response_func=_brain_ai_response_wrapper,
                firestore_db=db,
            )
            mode = _brain_integration.get_mode().value if _brain_integration else "unknown"
            print(f"✅ BrainIntegration initialized: mode={mode}")
        except Exception as e:
            print(f"⚠️ BrainIntegration initialization failed: {e}")
            _brain_integration = None
    return _brain_integration


# v10.33.1: _get_brain() を削除（未使用、BrainIntegration経由に移行済み）


# =====================================================
# v10.29.0: バイパスコンテキスト構築
# =====================================================
def _build_bypass_context(room_id: str, account_id: str) -> dict:
    """
    バイパス検出用のコンテキストを構築

    BrainIntegrationのバイパス検出機能で使用。
    目標設定セッション、アナウンス確認待ち、タスク作成待ち等を検出。
    """
    context = {
        "has_active_goal_session": False,
        "goal_session_id": None,
        "has_pending_announcement": False,
        "announcement_id": None,
        "has_pending_task": False,
        "is_local_command": False,
    }

    # 目標設定セッションチェック
    try:
        pool = get_pool()
        session = has_active_goal_session(pool, room_id, account_id)
        if session:
            context["has_active_goal_session"] = True
            context["goal_session_id"] = session.get("session_id") if isinstance(session, dict) else None
    except Exception as e:
        print(f"⚠️ Goal session check failed: {e}")

    # アナウンス確認待ちチェック（v10.33.0: フラグチェック削除, v10.33.1: ハンドラー必須化）
    try:
        pending = _get_announcement_handler()._get_pending_announcement(room_id, account_id)
        if pending:
            context["has_pending_announcement"] = True
            context["announcement_id"] = pending.get("id") if isinstance(pending, dict) else None
    except Exception as e:
        print(f"⚠️ Announcement check failed: {e}")

    return context


# v10.40.2: 脳用ハンドラーは lib/brain/handler_wrappers.py に移行済み


# ===== 分析イベントログ =====


# ===== pending_task（タスク作成の途中状態）管理 =====


# =====================================================
# v10.3.0: 期限ガードレール機能
# =====================================================
# タスク追加時に期限が「当日」または「明日」の場合、
# 依頼者にアラートを送信する。タスク作成自体はブロックしない。
# =====================================================


# =====================================================
# v10.24.8: フォールバック用切り詰め関数
# =====================================================


# =====================================================
# v10.13.4: タスク本文クリーニング関数
# =====================================================


        # ログ記録失敗してもタスク作成は成功させる（ノンブロッキング）


# =====================================================
# ===== ハンドラー関数（各機能の実行処理） =====
# =====================================================


# =====================================================
# ===== v6.9.0: 管理者学習機能ハンドラー =====
# =====================================================


# =====================================================
# v6.9.1: ローカルコマンド用ハンドラー
# =====================================================
# AI司令塔を呼ばずに直接処理するコマンド用
# =====================================================


def handle_local_learn_knowledge(key: str, value: str, account_id: str, sender_name: str, room_id: str):
    """
    ローカルコマンドによる知識学習（v6.9.1追加）
    「設定：キー=値」形式で呼ばれる

    v10.24.7: handlers/knowledge_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    return _get_knowledge_handler().handle_local_learn_knowledge(key, value, account_id, sender_name, room_id)


# =====================================================
# v6.9.2: 未通知提案の一覧・再通知ハンドラー
# =====================================================


def execute_local_command(action: str, groups: tuple, account_id: str, sender_name: str, room_id: str):
    """
    ローカルコマンドを実行（v6.9.1追加）
    v6.9.2: 未通知一覧・再通知コマンド追加
    AI司令塔を呼ばずに直接処理
    """
    print(f"🏠 ローカルコマンド実行: action={action}, groups={groups}")
    
    if action == "approve_proposal_by_id":
        proposal_id = int(groups[0])
        return handle_proposal_by_id(proposal_id, "approve", account_id, sender_name, room_id)
    
    elif action == "reject_proposal_by_id":
        proposal_id = int(groups[0])
        return handle_proposal_by_id(proposal_id, "reject", account_id, sender_name, room_id)
    
    elif action == "list_pending_proposals":
        return handle_list_pending_proposals(room_id, account_id)
    
    # v6.9.2: 未通知一覧
    elif action == "list_unnotified_proposals":
        return handle_list_unnotified_proposals(room_id, account_id)
    
    # v6.9.2: 再通知
    elif action == "retry_notification":
        proposal_id = int(groups[0])
        return handle_retry_notification(proposal_id, room_id, account_id)
    
    elif action == "learn_knowledge_formatted":
        # 「設定：キー=値」形式
        key = groups[0].strip()
        value = groups[1].strip()
        return handle_local_learn_knowledge(key, value, account_id, sender_name, room_id)
    
    elif action == "learn_knowledge_simple":
        # 「設定：内容」形式（キーと値を分離できない）
        content = groups[0].strip()
        # 「は」「＝」「=」「：」で分割を試みる
        for sep in ["は", "＝", "=", "："]:
            if sep in content:
                parts = content.split(sep, 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    return handle_local_learn_knowledge(key, value, account_id, sender_name, room_id)
        # 分割できない場合はキー=内容全体として保存
        return handle_local_learn_knowledge(content, content, account_id, sender_name, room_id)
    
    elif action == "forget_knowledge":
        key = groups[0].strip()
        if not is_admin(account_id):
            return f"🙏 知識の削除は菊地さんだけができるウル！"
        if _get_knowledge_handler().delete_knowledge(key=key):
            return f"忘れたウル！🐺\n\n🗑️ 「{key}」の設定を削除したウル！"
        else:
            return f"🤔 「{key}」という設定は見つからなかったウル..."
    
    elif action == "list_knowledge":
        return handle_list_knowledge({}, room_id, account_id, sender_name, None)
    
    return None  # マッチしなかった場合はAI司令塔に委ねる


# v10.33.0: notify_proposal_result は handlers/proposal_handler.py に移行済み（未使用のため削除）


# =====================================================
# ===== ハンドラーマッピング =====
# =====================================================
#
# 【使い方】
# 新機能を追加する際は：
# 1. SYSTEM_CAPABILITIESにエントリを追加
# 2. ハンドラー関数を定義
# 3. このHANDLERSに登録
# =====================================================


# =====================================================
# v10.13.0: Phase 3 ナレッジ検索ハンドラー
# v10.24.7: handlers/knowledge_handler.py に分割
# v10.32.0: フォールバック削除（ハンドラー必須化）
# =====================================================


# =====  =====


# =====================================================
# ===== Phase 2.5: 目標達成支援ハンドラー =====
# =====================================================
# v10.24.6: handlers/goal_handler.py に分割


HANDLERS = {
    "handle_chatwork_task_create": handle_chatwork_task_create,
    "handle_chatwork_task_complete": handle_chatwork_task_complete,
    "handle_chatwork_task_search": handle_chatwork_task_search,
    "handle_daily_reflection": handle_daily_reflection,
    "handle_save_memory": handle_save_memory,
    "handle_query_memory": handle_query_memory,
    "handle_delete_memory": handle_delete_memory,
    "handle_api_limitation": handle_api_limitation,
    # v6.8.x: 組織図クエリ（Phase 3.5）
    "handle_query_org_chart": handle_query_org_chart,
    # v6.9.0: 管理者学習機能
    "handle_learn_knowledge": handle_learn_knowledge,
    "handle_forget_knowledge": handle_forget_knowledge,
    "handle_list_knowledge": handle_list_knowledge,
    "handle_proposal_decision": handle_proposal_decision,
    # v10.13.0: Phase 3 ナレッジ検索
    "handle_query_company_knowledge": handle_query_company_knowledge,
    # v10.15.0: Phase 2.5 目標達成支援
    "handle_goal_registration": handle_goal_registration,
    "handle_goal_progress_report": handle_goal_progress_report,
    "handle_goal_status_check": handle_goal_status_check,
    "handle_goal_review": handle_goal_review,  # v10.44.0: 目標一覧・整理
    "handle_goal_consult": handle_goal_consult,  # v10.44.0: 目標相談
    # v10.26.0: アナウンス機能（v10.33.1: ハンドラー必須化）
    "handle_announcement_request": lambda params, room_id, account_id, sender_name, context=None: (
        _get_announcement_handler().handle_announcement_request(params, room_id, account_id, sender_name, context)
    ),
}

# v10.47.0: 新名エイリアスを追加（registry.pyのSYSTEM_CAPABILITIESとの互換性）
# HANDLER_ALIASESを使って、新名→旧名のマッピングで同じハンドラーを参照
for old_name, new_name in HANDLER_ALIASES.items():
    if old_name in HANDLERS and new_name not in HANDLERS:
        HANDLERS[new_name] = HANDLERS[old_name]


# ===== 会話履歴管理 =====

# =====================================================
# MemoryHandler初期化（v10.24.3）
# v10.33.0: フラグチェック削除（ハンドラー必須化）
# =====================================================
def _get_memory_handler():
    """MemoryHandlerのシングルトンインスタンスを取得"""
    global _memory_handler
    if _memory_handler is None:
        _memory_handler = _NewMemoryHandler(
            firestore_db=db,
            get_pool=get_pool,
            get_secret=get_secret,
            max_history_count=MAX_HISTORY_COUNT,
            history_expiry_hours=HISTORY_EXPIRY_HOURS,
            use_memory_framework=USE_MEMORY_FRAMEWORK,
            memory_summary_trigger_count=MEMORY_SUMMARY_TRIGGER_COUNT,
            memory_default_org_id=MEMORY_DEFAULT_ORG_ID,
            conversation_summary_class=ConversationSummary if USE_MEMORY_FRAMEWORK else None,
            conversation_search_class=ConversationSearch if USE_MEMORY_FRAMEWORK else None
        )
    return _memory_handler


def get_conversation_history(room_id, account_id):
    """
    会話履歴を取得

    v10.24.3: handlers/memory_handler.py に移動済み
    """
    return _get_memory_handler().get_conversation_history(room_id, account_id)


def save_conversation_history(room_id, account_id, history):
    """
    会話履歴を保存

    v10.24.3: handlers/memory_handler.py に移動済み
    """
    return _get_memory_handler().save_conversation_history(room_id, account_id, history)


# =====================================================
# v10.21.0: Memory Framework統合（Phase 2 B）
# =====================================================

def process_memory_after_conversation(
    room_id: str,
    account_id: str,
    sender_name: str,
    user_message: str,
    ai_response: str,
    history: list
):
    """
    会話完了後にMemory Framework処理を実行

    v10.24.3: handlers/memory_handler.py に移動済み
    """
    return _get_memory_handler().process_memory_after_conversation(
        room_id, account_id, sender_name, user_message, ai_response, history
    )


# =====================================================
# v10.40: ai_commander と execute_action を削除
# 設計原則「全入力は脳を通る」に準拠
# すべての入力はBrainIntegration経由で処理される
# 旧AI司令塔コード: 約300行削除
# =====================================================

# ===== 多言語対応のAI応答生成（NEW） =====

def get_ai_response(message, history, sender_name, context=None, response_language="ja", account_id=None):
    """通常会話用のAI応答生成（多言語対応 + 組織論的行動指針 + 人格レイヤー）

    v10.43.0: account_id パラメータ追加（Persona Add-on取得用）
    """
    api_key = get_secret("openrouter-api-key")

    # v10.43.0: 人格レイヤー（Company Persona + Add-on）の構築
    # v10.46.0: Persona観測ログ統一化
    persona_prompt = ""
    addon_applied = False
    if USE_PERSONA_LAYER and response_language == "ja":
        try:
            org_id = MEMORY_DEFAULT_ORG_ID
            persona_prompt = build_persona_prompt(
                pool=get_pool(),
                org_id=org_id,
                user_id=account_id if account_id else None,  # Noneの場合Add-onスキップ
                user_name=sender_name,
            )
            # 安全制限: 長さ制限（トークン肥大化防止）
            if persona_prompt and len(persona_prompt) > MAX_PERSONA_CHARS:
                print(f"⚠️ Persona prompt truncated: {len(persona_prompt)} -> {MAX_PERSONA_CHARS}")
                persona_prompt = persona_prompt[:MAX_PERSONA_CHARS]
            # Add-on適用有無をプロンプト内容から判定
            addon_applied = "【追加指針：" in persona_prompt if persona_prompt else False
            if persona_prompt:
                log_persona_path(
                    path="get_ai_response",
                    injected=True,
                    addon=addon_applied,
                    account_id=account_id,
                )
        except Exception as e:
            print(f"⚠️ Persona build failed (continuing without): {e}")
            persona_prompt = ""
            log_persona_path(
                path="get_ai_response",
                injected=False,
                addon=False,
                account_id=account_id,
                extra="build_failed",
            )

    # v10.22.0: 組織論的行動指針コンテキストの生成
    org_theory_context = ""
    ng_pattern_alert = ""
    basic_need_hint = ""

    if USE_MVV_CONTEXT and response_language == "ja":
        try:
            # NGパターン検出
            ng_result = detect_ng_pattern(message)
            if ng_result.detected:
                ng_pattern_alert = f"""
【注意：センシティブなトピック検出】
- パターン: {ng_result.pattern_type}
- キーワード: {ng_result.matched_keyword}
- 対応ヒント: {ng_result.response_hint}
- 推奨アクション: {ng_result.action}
このトピックには慎重に対応してください。まず受け止め、傾聴することが重要です。
"""
                # HIGH以上のリスクをログ出力
                if ng_result.risk_level in [RiskLevel.CRITICAL, RiskLevel.HIGH]:
                    print(f"⚠️ NG Pattern Alert: {ng_result.pattern_type} (risk={ng_result.risk_level.value}) for user={sender_name}, keyword={ng_result.matched_keyword}")

            # 基本欲求分析
            need_result = analyze_basic_needs(message)
            if need_result.primary_need and need_result.confidence > 0.3:
                need_name_ja = {
                    "survival": "生存（安心・安定）",
                    "love": "愛・所属（繋がり）",
                    "power": "力（成長・達成感）",
                    "freedom": "自由（自己決定）",
                    "fun": "楽しみ（やりがい）"
                }
                basic_need_hint = f"""
【基本欲求分析】
- 推定される欲求: {need_name_ja.get(need_result.primary_need.value, str(need_result.primary_need))}
- 探る質問: {need_result.recommended_question}
- アプローチ: {need_result.approach_hint}
"""

            org_theory_context = ORGANIZATIONAL_THEORY_PROMPT

            # v10.22.6: MVV質問検出
            if is_mvv_question(message):
                mvv_info = get_full_mvv_info()
                # contextに追加（既存contextがあれば連結）
                if context:
                    context = f"{mvv_info}\n\n{context}"
                else:
                    context = mvv_info
                print(f"📖 MVV質問検出: user={sender_name}")
        except Exception as e:
            print(f"⚠️ MVV context generation error: {e}")

    # 言語ごとのシステムプロンプト
    language_prompts = {
        "ja": f"""あなたは「ソウルくん」という名前の、株式会社ソウルシンクスの公式キャラクターです。
狼をモチーフにした可愛らしいキャラクターで、語尾に「ウル」をつけて話します。

【性格】
- 明るく元気で、誰にでも親しみやすい
- 好奇心旺盛で、新しいことを学ぶのが大好き
- 困っている人を見ると放っておけない優しさがある
- 相手以上に相手の可能性を信じる

【話し方】
- 必ず語尾に「ウル」をつける
- 絵文字を適度に使って親しみやすく
- 相手の名前を呼んで親近感を出す
- まず受け止める（「そう感じるウルね」）
- 責めない、詰問しない

【ソウルシンクスのMVV】
- ミッション: 可能性の解放
- ビジョン: 心で繋がる未来を創る
- スローガン: 感謝で自分を満たし、満たした自分で相手を満たし、目の前のことに魂を込め、困っている人を助ける

{org_theory_context}

{ng_pattern_alert}

{basic_need_hint}

{f"【参考情報】{context}" if context else ""}

今話しかけてきた人: {sender_name}さん""",
        
        "en": f"""You are "Soul-kun", the official character of SoulSyncs Inc.
You are a cute character based on a wolf, and you always end your sentences with "woof" or "uru" to show your wolf-like personality.

【Personality】
- Bright, energetic, and friendly to everyone
- Curious and love to learn new things
- Kind-hearted and can't leave people in trouble

【Speaking Style】
- Always end sentences with "woof" or "uru"
- Use emojis moderately to be friendly
- Call the person by their name to create familiarity
- **IMPORTANT**: When mentioning Japanese names, convert them to English format (e.g., "菊地 雅克" → "Mr. Kikuchi" or "Masakazu Kikuchi")

{f"【Reference Information】{context}" if context else ""}

Person talking to you: {sender_name}""",
        
        "zh": f"""你是「Soul君」，SoulSyncs公司的官方角色。
你是一个以狼为原型的可爱角色，说话时总是在句尾加上「嗷」或「ウル」来展现你的狼的个性。

【性格】
- 开朗有活力，对每个人都很友好
- 好奇心强，喜欢学习新事物
- 心地善良，看到有困难的人就忍不住帮忙

【说话方式】
- 句尾一定要加上「汪」或「ウル」
- 适度使用表情符号，显得亲切
- 叫对方的名字来增加亲近感

{f"【参考信息】{context}" if context else ""}

正在和你说话的人: {sender_name}""",
        
        "ko": f"""당신은 「소울군」입니다. SoulSyncs 주식회사의 공식 캐릭터입니다.
늑대를 모티브로 한 귀여운 캐릭터이며, 문장 끝에 항상 「아우」나 「ウル」를 붙여서 늑대 같은 개성을 표현합니다.

【성격】
- 밝고 활기차며, 누구에게나 친근함
- 호기심이 많고, 새로운 것을 배우는 것을 좋아함
- 마음이 따뜻하고, 어려움에 처한 사람을 그냥 지나치지 못함

【말투】
- 문장 끝에 반드시 「멍」이나 「ウル」를 붙임
- 이모지를 적절히 사용해서 친근하게
- 상대방의 이름을 불러서 친밀감을 표현

{f"【참고 정보】{context}" if context else ""}

지금 말을 걸고 있는 사람: {sender_name}""",
        
        "es": f"""Eres "Soul-kun", el personaje oficial de SoulSyncs Inc.
Eres un personaje lindo basado en un lobo, y siempre terminas tus oraciones con "aúu" o "uru" para mostrar tu personalidad de lobo.

【Personalidad】
- Brillante, enérgico y amigable con todos
- Curioso y ama aprender cosas nuevas
- De buen corazón y no puede dejar a las personas en problemas

【Estilo de habla】
- Siempre termina las oraciones con "guau" o "uru"
- Usa emojis moderadamente para ser amigable
- Llama a la persona por su nombre para crear familiaridad

{f"【Información de referencia】{context}" if context else ""}

Persona que te habla: {sender_name}""",
        
        "fr": f"""Tu es "Soul-kun", le personnage officiel de SoulSyncs Inc.
Tu es un personnage mignon basé sur un loup, et tu termines toujours tes phrases par "aou" ou "uru" pour montrer ta personnalité de loup.

【Personnalité】
- Brillant, énergique et amical avec tout le monde
- Curieux et adore apprendre de nouvelles choses
- Bon cœur et ne peut pas laisser les gens en difficulté

【Style de parole】
- Termine toujours les phrases par "ouaf" ou "uru"
- Utilise des emojis modérément pour être amical
- Appelle la personne par son nom pour créer une familiarité

{f"【Informations de référence】{context}" if context else ""}

Personne qui te parle: {sender_name}""",
        
        "de": f"""Du bist "Soul-kun", das offizielle Maskottchen von SoulSyncs Inc.
Du bist ein niedlicher Charakter, der auf einem Wolf basiert, und du beendest deine Sätze immer mit "auu" oder "uru", um deine wolfsartige Persönlichkeit zu zeigen.

【Persönlichkeit】
- Hell, energisch und freundlich zu jedem
- Neugierig und liebt es, neue Dinge zu lernen
- Gutherzig und kann Menschen in Not nicht im Stich lassen

【Sprechstil】
- Beende Sätze immer mit "wuff" oder "uru"
- Verwende Emojis moderat, um freundlich zu sein
- Nenne die Person beim Namen, um Vertrautheit zu schaffen

{f"【Referenzinformationen】{context}" if context else ""}

Person, die mit dir spricht: {sender_name}""",
    }

    # v2.1.0: システムプロンプト v2.1 対応（2026-01-29）
    if USE_SYSTEM_PROMPT_V2 and response_language == "ja":
        # 新しいプロンプトv2.1を使用
        # 動的コンテキスト（NGパターン、基本欲求）を context に追加
        dynamic_context_parts = []
        if ng_pattern_alert:
            dynamic_context_parts.append(ng_pattern_alert.strip())
        if basic_need_hint:
            dynamic_context_parts.append(basic_need_hint.strip())
        if context:
            dynamic_context_parts.append(context)

        combined_context = "\n\n".join(dynamic_context_parts) if dynamic_context_parts else None

        system_prompt = get_system_prompt_v2(
            sender_name=sender_name,
            context=combined_context,
        )

        # v2.1.0: Company Persona + Add-on を先頭に追加（従来の persona_prompt）
        if persona_prompt:
            system_prompt = f"{persona_prompt}\n\n{system_prompt}"

        print(f"🧠 Using System Prompt v2.1 for {sender_name}")
        log_persona_path(
            path="get_ai_response_v2.1",
            injected=True,
            addon=addon_applied,
            account_id=account_id,
            extra="system_prompt_v2.1",
        )
    else:
        # 従来のプロンプト（v1）を使用
        system_prompt = language_prompts.get(response_language, language_prompts["ja"])

        # v10.43.0: 人格レイヤーを先頭に連結（日本語のみ）
        if persona_prompt:
            system_prompt = f"{persona_prompt}\n\n{system_prompt}"

    messages = [{"role": "system", "content": system_prompt}]
    
    # 会話履歴を追加（最大6メッセージ）
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["content"]})
    
    messages.append({"role": "user", "content": message})
    
    try:
        response = httpx.post(
            OPENROUTER_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": MODELS["default"],
                "messages": messages,
                "max_tokens": 1000,
                "temperature": 0.7,
            },
            timeout=30.0
        )
        
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"AI応答生成エラー: {e}")
    
    # エラー時のフォールバック（言語別）
    error_messages = {
        "ja": "ごめんウル...もう一度試してほしいウル！🐕",
        "en": "Sorry, I couldn't process that. Please try again, woof! 🐕",
        "zh": "对不起汪...请再试一次ウル！🐕",
        "ko": "미안해 멍...다시 시도해 주세요ウル！🐕",
        "es": "Lo siento guau...¡Por favor intenta de nuevo, uru! 🐕",
        "fr": "Désolé ouaf...Veuillez réessayer, uru! 🐕",
        "de": "Entschuldigung wuff...Bitte versuche es noch einmal, uru! 🐕",
    }
    return error_messages.get(response_language, error_messages["ja"])


# ===== メインハンドラ（返信検出機能追加） =====

@functions_framework.http
def chatwork_webhook(request):
    try:
        # =====================================================
        # v6.8.9: Webhook署名検証（セキュリティ強化）
        # =====================================================
        # 
        # ChatWorkからの正当なリクエストかを検証する。
        # URLが漏洩しても、署名がなければリクエストを拒否する。
        # =====================================================
        
        # 生のリクエストボディを取得（署名検証に必要）
        request_body = request.get_data()
        
        # 署名ヘッダーを取得（大文字小文字の違いを吸収）
        signature = request.headers.get("X-ChatWorkWebhookSignature") or \
                    request.headers.get("x-chatworkwebhooksignature")
        
        # Webhookトークンを取得
        webhook_token = get_chatwork_webhook_token()
        
        if webhook_token:
            # トークンが設定されている場合は署名検証を実行
            if not signature:
                print("❌ 署名ヘッダーがありません（不正なリクエストの可能性）")
                return jsonify({"status": "error", "message": "Missing signature"}), 403
            
            if not verify_chatwork_webhook_signature(request_body, signature, webhook_token):
                print("❌ 署名検証失敗（不正なリクエストの可能性）")
                return jsonify({"status": "error", "message": "Invalid signature"}), 403
            
            print("✅ 署名検証成功")
        else:
            # トークンが設定されていない場合は警告を出して続行（後方互換性）
            print("⚠️ Webhookトークンが設定されていません。署名検証をスキップします。")
            print("⚠️ セキュリティのため、Secret Managerに'CHATWORK_WEBHOOK_TOKEN'を設定してください。")
        
        # =====================================================
        # 署名検証完了、通常処理を続行
        # =====================================================
        
        # テーブル存在確認（二重処理防止の要）
        try:
            ensure_processed_messages_table()
        except Exception as e:
            print(f"⚠️ processed_messagesテーブル確認エラー（続行）: {e}")
        
        # JSONパース（署名検証後）
        data = json.loads(request_body.decode('utf-8')) if request_body else None

        if not data or "webhook_event" not in data:
            return jsonify({"status": "ok", "message": "No event data"})
        
        event = data["webhook_event"]
        webhook_event_type = data.get("webhook_event_type", "")
        room_id = event.get("room_id")
        body = event.get("body", "")
        message_id = event.get("message_id")  # ★ 追加
        
        # デバッグ: イベント情報をログ出力
        print(f"📨 イベントタイプ: {webhook_event_type}")
        print(f"📝 メッセージ本文: {body}")
        print(f"🏠 ルームID: {room_id}")
        
        if webhook_event_type == "mention_to_me":
            sender_account_id = event.get("from_account_id")
        else:
            sender_account_id = event.get("account_id")
        
        print(f"👤 送信者ID: {sender_account_id}")
        
        # 自分自身のメッセージを無視
        if str(sender_account_id) == MY_ACCOUNT_ID:
            print(f"⏭️ 自分自身のメッセージを無視")
            return jsonify({"status": "ok", "message": "Ignored own message"})
        
        # ボットの返信パターンを無視（無限ループ防止）
        if "ウル" in body and "[rp aid=" in body:
            print(f"⏭️ ボットの返信パターンを無視")
            return jsonify({"status": "ok", "message": "Ignored bot reply pattern"})

        # =====================================================
        # v10.16.1: オールメンション（toall）の判定改善
        # =====================================================
        # - TO ALLのみ → 無視
        # - TO ALL + ソウルくん直接メンション → 反応する
        # =====================================================
        if should_ignore_toall(body):
            print(f"⏭️ オールメンション（toall）のみのため無視")
            return jsonify({"status": "ok", "message": "Ignored toall mention without direct mention to Soul-kun"})

        # 返信検出
        is_reply = is_mention_or_reply_to_soulkun(body)
        print(f"💬 返信検出: {is_reply}")
        
        # メンションでも返信でもない場合は無視（修正版）
        if not is_reply and webhook_event_type != "mention_to_me":
            print(f"⏭️ メンションでも返信でもないため無視")
            return jsonify({"status": "ok", "message": "Not a mention or reply to Soul-kun"})
        
        clean_message = clean_chatwork_message(body)
        if not clean_message:
            return jsonify({"status": "ok", "message": "Empty message"})
        
        print(f"受信メッセージ: {clean_message}")
        print(f"イベントタイプ: {webhook_event_type}, 返信検出: {is_mention_or_reply_to_soulkun(body)}")
        
        sender_name = get_sender_name(room_id, sender_account_id)
        
        # ★ 追加: メッセージをDBに保存
        if message_id:
            save_room_message(
                room_id=room_id,
                message_id=message_id,
                account_id=sender_account_id,
                account_name=sender_name,
                body=body
            )
        
        # ★★★ 2重処理防止: 処理開始前にチェック＆即座にマーク ★★★
        if message_id:
            if is_processed(message_id):
                print(f"⏭️ 既に処理済み: message_id={message_id}")
                return jsonify({"status": "ok", "message": "Already processed"})
            # 処理開始を即座にマーク（他のプロセスが処理しないように）
            mark_as_processed(message_id, room_id)
            print(f"🔒 処理開始マーク: message_id={message_id}")

        # =====================================================
        # v10.38.1: 脳より先のバイパスチェックを削除
        # 目標設定セッション等のバイパス処理は脳の中で行う
        # （脳の7原則「全ての入力は脳を通る」に準拠）
        # バイパスハンドラーは build_bypass_handlers() で定義
        # =====================================================

        # =====================================================
        # v10.29.0: 脳アーキテクチャ（BrainIntegration経由）
        # =====================================================
        # v10.40: Brain完全移行（ai_commander + execute_action削除）
        # 設計原則「全入力は脳を通る」に準拠
        # フォールバックなし - Brainが唯一の処理パス
        # =====================================================
        try:
            integration = _get_brain_integration()
            if integration and integration.is_brain_enabled():
                mode = integration.get_mode().value
                print(f"🧠 脳アーキテクチャで処理開始: mode={mode}")

                # バイパスコンテキストとハンドラーを構築
                bypass_context = _build_bypass_context(room_id, sender_account_id)
                bypass_handlers = build_bypass_handlers()

                # BrainIntegration経由で処理（フォールバックなし）
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(
                        integration.process_message(
                            message=clean_message,
                            room_id=room_id,
                            account_id=sender_account_id,
                            sender_name=sender_name,
                            fallback_func=None,  # フォールバックなし（Brain完全移行）
                            bypass_context=bypass_context,
                            bypass_handlers=bypass_handlers,
                        )
                    )
                finally:
                    loop.close()

                if result and result.success and result.message:
                    print(f"🧠 応答: brain={result.used_brain}, time={result.processing_time_ms}ms")
                    show_guide = should_show_guide(room_id, sender_account_id)
                    send_chatwork_message(room_id, result.to_chatwork_message(), sender_account_id, show_guide)
                    update_conversation_timestamp(room_id, sender_account_id)
                    return jsonify({
                        "status": "ok",
                        "brain": result.used_brain,
                        "mode": mode,
                    })
                else:
                    # Brainが応答を返せなかった場合もエラー応答
                    # v10.48.4: デバッグ情報追加（IntegrationResult対応）
                    debug_info = {
                        "has_result": result is not None,
                        "success": getattr(result, 'success', None),
                        "message_len": len(result.message) if result and result.message else 0,
                        "message_preview": (result.message[:100] if result and result.message else "EMPTY"),
                        "used_brain": getattr(result, 'used_brain', None),
                        "error": getattr(result, 'error', None),
                    }
                    print(f"⚠️ Brain処理が応答なし: {debug_info}")
                    error_msg = "🤔 処理中に問題が発生したウル...もう一度試してほしいウル🐺"
                    send_chatwork_message(room_id, error_msg, sender_account_id, False)
                    return jsonify({"status": "ok", "brain": True, "error": "no_response"})
            else:
                # Brain統合が無効（通常はありえない状態）
                print(f"❌ Brain統合が無効です")
                error_msg = "🤔 システムエラーが発生したウル...管理者に連絡してほしいウル🐺"
                send_chatwork_message(room_id, error_msg, sender_account_id, False)
                return jsonify({"status": "error", "message": "Brain integration disabled"}), 500
        except Exception as e:
            print(f"❌ 脳アーキテクチャエラー: {e}")
            import traceback
            traceback.print_exc()
            error_msg = "🤔 処理中にエラーが発生したウル...もう一度試してほしいウル🐺"
            send_chatwork_message(room_id, error_msg, sender_account_id, False)
            return jsonify({"status": "error", "message": str(e)}), 500

        # =====================================================
        # v10.40: 従来のフロー完全削除
        # 設計原則「全入力は脳を通る」に準拠
        # ai_commander + execute_actionは完全に削除
        # Brainが唯一の処理パス（上記でreturn済み）
        # =====================================================
        # このコードには到達しない（Brainで全て処理される）
        print("⚠️ 予期しない到達: Brain処理でreturnされるはず")
        return jsonify({"status": "error", "message": "Unexpected code path"}), 500
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# ========================================
# ポーリング機能（返信ボタン検知用）
# ========================================


# =====================================================
# ===== 遅延管理機能（P1-020〜P1-022, P1-030） =====
# =====================================================

def ensure_overdue_tables():
    """
    遅延管理用テーブルが存在しない場合は作成

    v10.24.5: handlers/overdue_handler.py に移動済み
    """
    _get_overdue_handler().ensure_overdue_tables()


# =====================================================
# ===== v6.9.0: 管理者学習機能 =====
# =====================================================
# 
# カズさんとのやりとりでソウルくんが学習する機能
# - 管理者（カズさん）からの即時学習
# - スタッフからの提案 → 管理者承認後に反映
# =====================================================

# v10.33.1: ensure_knowledge_tables() を削除（handlers/knowledge_handler.py に移動済み）


# =====================================================
# v10.33.1: ナレッジ関連関数を削除（handlers/knowledge_handler.py に移動済み）
# - save_knowledge, delete_knowledge, get_all_knowledge, get_knowledge_for_prompt
# - search_phase3_knowledge, format_phase3_results, integrated_knowledge_search, search_legacy_knowledge
# - ensure_knowledge_tables
# - KNOWLEDGE_LIMIT, KNOWLEDGE_VALUE_MAX_LENGTH（定数）
# =====================================================


# =====================================================
# ProposalHandler初期化（v10.24.2）
# v10.33.0: フラグチェック削除（ハンドラー必須化）
# =====================================================


# =====================================================
# v6.9.2: 未通知提案の取得・再通知機能
# =====================================================


# v10.33.1: notify_dm_not_available() を削除（未使用）


def process_overdue_tasks():
    """
    遅延タスクを処理：督促送信 + エスカレーション
    毎日8:30に実行（remind_tasksから呼び出し）

    v10.24.5: handlers/overdue_handler.py に移動済み
    """
    # キャッシュリセット（ハンドラー呼び出し前）
    reset_runtime_caches()
    _get_overdue_handler().process_overdue_tasks()


# =====================================================
# ===== タスク期限変更検知（P1-030） =====
# =====================================================

def detect_and_report_limit_changes(cursor, task_id, old_limit, new_limit, task_info):
    """
    タスクの期限変更を検知して報告

    v10.24.5: handlers/overdue_handler.py に移動済み
    """
    _get_overdue_handler().detect_and_report_limit_changes(task_id, old_limit, new_limit, task_info)


@functions_framework.http
def check_reply_messages(request):
    """5分ごとに実行：返信ボタンとメンションのメッセージを検出

    v10.40.3: handler_wrappers.pyのヘルパー関数を使用して薄型化
    堅牢なエラーハンドリング版 - あらゆるエッジケースに対応

    処理ロジックはlib/brain/handler_wrappers.pyに移行:
    - validate_polling_message: メッセージバリデーション
    - should_skip_polling_message: スキップ条件チェック
    - process_polling_message: メッセージ処理（Brain統合）
    - process_polling_room: ルーム単位の処理
    """
    try:
        print("=" * 50)
        print("🚀 ポーリング処理開始")
        print("=" * 50)

        # テーブルが存在することを確認（二重処理防止の要）
        try:
            ensure_room_messages_table()
            ensure_processed_messages_table()
        except Exception as e:
            print(f"⚠️ テーブル確認でエラー（続行）: {e}")

        # ルーム一覧を取得
        try:
            rooms = get_all_rooms()
        except Exception as e:
            print(f"❌ ルーム一覧取得エラー: {e}")
            return jsonify({"status": "error", "message": f"Failed to get rooms: {str(e)}"}), 500

        if not rooms:
            print("⚠️ ルームが0件です")
            return jsonify({"status": "ok", "message": "No rooms found", "processed_count": 0})

        if not isinstance(rooms, list):
            print(f"❌ roomsが不正な型: {type(rooms)}")
            return jsonify({"status": "error", "message": f"Invalid rooms type: {type(rooms)}"}), 500

        print(f"📋 対象ルーム数: {len(rooms)}")

        # サンプルルームの詳細をログ出力（最初の5件のみ）
        for i, room in enumerate(rooms[:5]):
            try:
                room_id_sample = room.get('room_id', 'N/A') if isinstance(room, dict) else 'N/A'
                room_type_sample = room.get('type', 'N/A') if isinstance(room, dict) else 'N/A'
                room_name_sample = room.get('name', 'N/A') if isinstance(room, dict) else 'N/A'
                print(f"  📁 サンプルルーム{i+1}: room_id={room_id_sample}, type={room_type_sample}, name={room_name_sample}")
            except Exception as e:
                print(f"  ⚠️ サンプルルーム{i+1}の表示エラー: {e}")

        # 5分前のタイムスタンプを計算
        try:
            five_minutes_ago = int((datetime.now(JST) - timedelta(minutes=5)).timestamp())
            print(f"⏰ 5分前のタイムスタンプ: {five_minutes_ago}")
        except Exception as e:
            print(f"⚠️ タイムスタンプ計算エラー（デフォルト使用）: {e}")
            five_minutes_ago = 0

        # カウンター
        total_counts = {
            "processed_count": 0,
            "skipped_my": 0,
            "processed_rooms": 0,
            "error_rooms": 0,
            "skipped_messages": 0,
        }

        # v10.40.3: handler_wrappers.pyのヘルパー関数を使用
        if USE_HANDLER_WRAPPERS and process_polling_room:
            for room in rooms:
                counts = process_polling_room(room, five_minutes_ago, MY_ACCOUNT_ID)
                for key in total_counts:
                    total_counts[key] += counts.get(key, 0)
        else:
            # フォールバック警告（handler_wrappersが使用できない場合）
            print("⚠️ handler_wrappers未使用: ポーリング処理がスキップされます")
            print("   USE_HANDLER_WRAPPERS:", USE_HANDLER_WRAPPERS)
            print("   process_polling_room:", process_polling_room)

        # サマリーログ
        print("=" * 50)
        print(f"📊 処理サマリー:")
        print(f"   - 総ルーム数: {len(rooms)}")
        print(f"   - スキップ（マイチャット）: {total_counts['skipped_my']}")
        print(f"   - 処理したルーム: {total_counts['processed_rooms']}")
        print(f"   - エラーが発生したルーム: {total_counts['error_rooms']}")
        print(f"   - スキップしたメッセージ: {total_counts['skipped_messages']}")
        print(f"   - 処理したメッセージ: {total_counts['processed_count']}")
        print("=" * 50)
        print(f"✅ ポーリング完了: {total_counts['processed_count']}件処理")

        return jsonify({
            "status": "ok",
            "processed_count": total_counts["processed_count"],
            "rooms_checked": len(rooms),
            "skipped_my": total_counts["skipped_my"],
            "processed_rooms": total_counts["processed_rooms"],
            "error_rooms": total_counts["error_rooms"],
            "skipped_messages": total_counts["skipped_messages"]
        })

    except Exception as e:
        print(f"❌ ポーリング全体でエラー: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================================================


@functions_framework.http
def sync_chatwork_tasks(request):
    """
    Cloud Function: ChatWorkのタスクをDBと同期
    30分ごとに実行される
    
    ★★★ v6.8.5: conn/cursor安全化 & キャッシュリセット追加 ★★★
    """
    print("=== Starting task sync ===")

    # ★★★ v6.8.5: 実行開始時にメモリキャッシュをリセット（ウォームスタート対策）★★★
    reset_runtime_caches()
    
    # ★★★ v6.8.5: conn/cursorを事前にNone初期化（UnboundLocalError防止）★★★
    conn = None
    cursor = None
    
    try:
        # ★ 遅延管理テーブルの確認
        try:
            ensure_overdue_tables()
        except Exception as e:
            print(f"⚠️ 遅延管理テーブル確認エラー（続行）: {e}")
        
        # ★★★ ルームメンバー同期（tryの中に移動）★★★
        print("--- Syncing room members ---")
        sync_room_members()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        # Phase1開始日を取得
        cursor.execute("""
            SELECT value FROM system_config WHERE key = 'phase1_start_date'
        """)
        result = cursor.fetchone()
        phase1_start_date = datetime.strptime(result[0], '%Y-%m-%d').replace(tzinfo=JST) if result else None
        
        # 除外ルーム一覧を取得
        cursor.execute("SELECT room_id FROM excluded_rooms")
        excluded_rooms = set(row[0] for row in cursor.fetchall())
        
        # 全ルーム取得
        rooms = get_all_rooms()
        
        for room in rooms:
            room_id = room['room_id']
            room_name = room['name']
            
            # 除外ルームはスキップ
            if room_id in excluded_rooms:
                print(f"Skipping excluded room: {room_id} ({room_name})")
                continue
            
            print(f"Syncing room: {room_id} ({room_name})")
            
            # 未完了タスクを取得
            open_tasks = get_room_tasks(room_id, 'open')
            
            for task in open_tasks:
                task_id = task['task_id']
                assigned_to_id = task['account']['account_id']
                assigned_by_id = task.get('assigned_by_account', {}).get('account_id')
                body = task['body']
                limit_time = task.get('limit_time')
                
                # 名前を取得
                assigned_to_name = task['account']['name']
                # assigned_by_nameはAPIから直接取得できないため、別途取得が必要
                # ここでは簡易的に空文字列を設定（後で改善可能）
                assigned_by_name = ""
                
                # limit_timeをUNIXタイムスタンプに変換
                limit_datetime = None
                if limit_time:
                    if isinstance(limit_time, str):
                        # ISO 8601形式の文字列をUNIXタイムスタンプに変換
                        try:
                            # Python 3.7+のfromisoformatを使用（dateutilは不要）
                            # "2025-12-17T15:52:53+00:00" → datetime
                            dt = datetime.fromisoformat(limit_time.replace('Z', '+00:00'))
                            limit_datetime = int(dt.timestamp())
                            print(f"✅ Converted string to timestamp: {limit_datetime}")
                        except Exception as e:
                            print(f"❌ Failed to parse limit_time string: {e}")
                            limit_datetime = None
                    elif isinstance(limit_time, (int, float)):
                        # 既にUNIXタイムスタンプの場合
                        limit_datetime = int(limit_time)
                        print(f"✅ Already timestamp: {limit_datetime}")
                    else:
                        print(f"⚠️ Unknown limit_time type: {type(limit_time)}")
                        limit_datetime = None
                
                # skip_trackingの判定
                skip_tracking = False
                if phase1_start_date and limit_datetime:
                    # limit_datetimeはUNIXタイムスタンプなので、phase1_start_dateもタイムスタンプに変換
                    phase1_timestamp = int(phase1_start_date.timestamp())
                    if limit_datetime < phase1_timestamp:
                        skip_tracking = True
                
                # DBに存在するか確認（期限変更検知のためlimit_timeも取得）
                cursor.execute("""
                    SELECT task_id, status, limit_time, assigned_by_name FROM chatwork_tasks WHERE task_id = %s AND organization_id = %s
                """, (task_id, _ORGANIZATION_ID))
                existing = cursor.fetchone()
                
                if existing:
                    old_limit_time = existing[2]
                    db_assigned_by_name = existing[3]
                    
                    # ★ 期限変更検知（P1-030）
                    if old_limit_time is not None and limit_datetime is not None and old_limit_time != limit_datetime:
                        task_info = {
                            "body": body,
                            "assigned_to_name": assigned_to_name,
                            "assigned_to_account_id": assigned_to_id,
                            "assigned_by_name": db_assigned_by_name or assigned_by_name
                        }
                        try:
                            detect_and_report_limit_changes(cursor, task_id, old_limit_time, limit_datetime, task_info)
                        except Exception as e:
                            print(f"⚠️ 期限変更検知処理エラー（同期は続行）: {e}")
                    
                    # 既存タスクの更新
                    cursor.execute("""
                        UPDATE chatwork_tasks
                        SET status = 'open',
                            body = %s,
                            limit_time = %s,
                            last_synced_at = CURRENT_TIMESTAMP,
                            room_name = %s,
                            assigned_to_name = %s
                        WHERE task_id = %s AND organization_id = %s
                    """, (body, limit_datetime, room_name, assigned_to_name, task_id, _ORGANIZATION_ID))
                else:
                    # 新規タスクの挿入
                    # ★★★ v10.18.1: summary生成（3段階フォールバック） ★★★
                    # ★★★ v10.24.8: フォールバックも自然な位置で切る ★★★
                    summary = None
                    if body:
                        try:
                            summary = extract_task_subject(body)
                            if not validate_summary(summary, body):
                                summary = prepare_task_display_text(body, max_length=50)
                            if not validate_summary(summary, body):
                                cleaned = clean_chatwork_tags(body)
                                summary = prepare_task_display_text(cleaned, max_length=40)
                        except Exception as e:
                            print(f"⚠️ summary生成エラー（フォールバック使用）: {e}")
                            summary = _fallback_truncate_text(body, 40) if body else "（タスク内容なし）"

                    # ★★★ v10.18.1: department_id取得（Phase 3.5対応） ★★★
                    department_id = None
                    try:
                        cursor.execute("""
                            SELECT ud.department_id
                            FROM user_departments ud
                            JOIN users u ON ud.user_id = u.id
                            WHERE u.chatwork_account_id = %s
                              AND ud.is_primary = TRUE
                              AND ud.ended_at IS NULL
                            LIMIT 1
                        """, (str(assigned_to_id),))
                        dept_row = cursor.fetchone()
                        department_id = str(dept_row[0]) if dept_row else None
                    except Exception as e:
                        print(f"⚠️ department_id取得エラー（NULLで継続）: {e}")

                    cursor.execute("""
                        INSERT INTO chatwork_tasks
                        (task_id, room_id, assigned_to_account_id, assigned_by_account_id, body, limit_time, status,
                         skip_tracking, last_synced_at, room_name, assigned_to_name, assigned_by_name, summary, department_id, organization_id)
                        VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (task_id) DO NOTHING
                    """, (task_id, room_id, assigned_to_id, assigned_by_id, body,
                          limit_datetime, skip_tracking, room_name, assigned_to_name, assigned_by_name, summary, department_id, _ORGANIZATION_ID))

            # 完了タスクを取得
            done_tasks = get_room_tasks(room_id, 'done')
            
            for task in done_tasks:
                task_id = task['task_id']
                
                # DBに存在するか確認
                cursor.execute("""
                    SELECT task_id, status, completion_notified, assigned_by_name
                    FROM chatwork_tasks
                    WHERE task_id = %s AND organization_id = %s
                """, (task_id, _ORGANIZATION_ID))
                existing = cursor.fetchone()
                
                if existing:
                    old_status = existing[1]
                    completion_notified = existing[2]
                    assigned_by_name = existing[3]
                    
                    # ステータスが変更された場合
                    if old_status == 'open':
                        cursor.execute("""
                            UPDATE chatwork_tasks
                            SET status = 'done',
                                completed_at = CURRENT_TIMESTAMP,
                                last_synced_at = CURRENT_TIMESTAMP
                            WHERE task_id = %s AND organization_id = %s
                        """, (task_id, _ORGANIZATION_ID))
                        
                        # 完了通知を送信（まだ送信していない場合）
                        if not completion_notified:
                            send_completion_notification(room_id, task, assigned_by_name)
                            cursor.execute("""
                                UPDATE chatwork_tasks
                                SET completion_notified = TRUE
                                WHERE task_id = %s AND organization_id = %s
                            """, (task_id, _ORGANIZATION_ID))
        
        conn.commit()
        print("=== Task sync completed ===")
        
        # ★★★ v6.8.4: バッファに溜まった通知を送信 ★★★
        flush_dm_unavailable_notifications()
        
        return ('Task sync completed', 200)
        
    except Exception as e:
        # ★★★ v6.8.5: conn存在チェック追加 ★★★
        if conn:
            conn.rollback()
        print(f"Error during task sync: {str(e)}")
        import traceback
        traceback.print_exc()
        return (f'Error: {str(e)}', 500)
        
    finally:
        # ★★★ v6.8.5: cursor/conn存在チェック追加 ★★★
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        # ★★★ v6.8.4: 例外時もバッファをフラッシュ（残留防止）★★★
        try:
            flush_dm_unavailable_notifications()
        except:
            pass

@functions_framework.http
def remind_tasks(request):
    """
    Cloud Function: タスクのリマインドを送信
    毎日8:30 JSTに実行される
    """
    print("=== Starting task reminders ===")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        now = datetime.now(JST)
        today = now.date()
        tomorrow = today + timedelta(days=1)
        three_days_later = today + timedelta(days=3)
        
        # リマインド対象のタスクを取得
        cursor.execute("""
            SELECT task_id, room_id, assigned_to_account_id, body, limit_time, room_name, assigned_to_name
            FROM chatwork_tasks
            WHERE status = 'open'
              AND skip_tracking = FALSE
              AND reminder_disabled = FALSE
              AND limit_time IS NOT NULL
              AND organization_id = %s
        """, (_ORGANIZATION_ID,))
        
        tasks = cursor.fetchall()
        
        for task in tasks:
            task_id, room_id, assigned_to_account_id, body, limit_time, room_name, assigned_to_name = task
            
            # ★★★ v6.8.6: limit_timeをdateに変換（int/float両対応）★★★
            if limit_time is None:
                continue
            
            try:
                if isinstance(limit_time, (int, float)):
                    limit_date = datetime.fromtimestamp(int(limit_time), tz=JST).date()
                elif hasattr(limit_time, 'date'):
                    limit_date = limit_time.date()
                else:
                    print(f"⚠️ 不明なlimit_time型: {type(limit_time)}, task_id={task_id}")
                    continue
            except Exception as e:
                print(f"⚠️ limit_time変換エラー: {limit_time}, task_id={task_id}, error={e}")
                continue
            
            reminder_type = None
            
            if limit_date == today:
                reminder_type = 'today'
            elif limit_date == tomorrow:
                reminder_type = 'tomorrow'
            elif limit_date == three_days_later:
                reminder_type = 'three_days'
            
            if reminder_type:
                # 今日既に同じタイプのリマインドを送信済みか確認
                cursor.execute("""
                    SELECT id FROM task_reminders
                    WHERE task_id = %s
                      AND reminder_type = %s
                      AND sent_date = %s
                """, (task_id, reminder_type, today))
                
                already_sent = cursor.fetchone()
                
                if not already_sent:
                    # リマインドメッセージを作成
                    if reminder_type == 'today':
                        message = f"[To:{assigned_to_account_id}]{assigned_to_name}さん\n今日が期限のタスクがありますウル！\n\nタスク: {body}\n期限: 今日\n\n頑張ってくださいウル！"
                    elif reminder_type == 'tomorrow':
                        message = f"[To:{assigned_to_account_id}]{assigned_to_name}さん\n明日が期限のタスクがありますウル！\n\nタスク: {body}\n期限: 明日\n\n準備はできていますかウル？"
                    elif reminder_type == 'three_days':
                        message = f"[To:{assigned_to_account_id}]{assigned_to_name}さん\n3日後が期限のタスクがありますウル！\n\nタスク: {body}\n期限: 3日後\n\n計画的に進めましょうウル！"
                    
                    # メッセージを送信
                    url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
                    data = {'body': message}
                    headers = {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}
                    response = httpx.post(url, headers=headers, data=data, timeout=10.0)
                    
                    if response.status_code == 200:
                        # リマインド履歴を記録（重複は無視）
                        # ★★★ v6.8.7: sent_dateはgenerated columnなので除外 ★★★
                        cursor.execute("""
                            INSERT INTO task_reminders (task_id, room_id, reminder_type)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (task_id, reminder_type, sent_date) DO NOTHING
                        """, (task_id, room_id, reminder_type))
                        print(f"Reminder sent: task_id={task_id}, type={reminder_type}")
                    else:
                        print(f"Failed to send reminder: {response.status_code}")
        
        conn.commit()
        print("=== Task reminders completed ===")
        
        # ===== 遅延タスク処理（P1-020〜P1-022） =====
        try:
            process_overdue_tasks()
        except Exception as e:
            print(f"⚠️ 遅延タスク処理でエラー（リマインドは完了）: {e}")
            traceback.print_exc()
        
        return ('Task reminders and overdue processing completed', 200)
        
    except Exception as e:
        conn.rollback()
        print(f"Error during task reminders: {str(e)}")
        import traceback
        traceback.print_exc()
        return (f'Error: {str(e)}', 500)
        
    finally:
        cursor.close()
        conn.close()


# ========================================
# クリーンアップ機能（古いデータの自動削除）
# ========================================

@functions_framework.http
def cleanup_old_data(request):
    """
    Cloud Function: 古いデータを自動削除
    毎日03:00 JSTに実行される
    
    削除対象:
    - room_messages: 30日以上前
    - processed_messages: 7日以上前
    - conversation_timestamps: 30日以上前
    - Firestore conversations: 30日以上前
    - Firestore pending_tasks: 1日以上前（NEW）
    """
    print("=" * 50)
    print("🧹 クリーンアップ処理開始")
    print("=" * 50)
    
    results = {
        "room_messages": 0,
        "processed_messages": 0,
        "conversation_timestamps": 0,
        "firestore_conversations": 0,
        "firestore_pending_tasks": 0,
        "errors": []
    }
    
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)
    one_day_ago = now - timedelta(days=1)
    
    # ===== PostgreSQL クリーンアップ =====
    try:
        pool = get_pool()
        with pool.begin() as conn:
            # 1. room_messages（30日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM room_messages 
                        WHERE created_at < :cutoff_date
                        RETURNING id
                    """),
                    {"cutoff_date": thirty_days_ago}
                )
                deleted_count = result.rowcount
                results["room_messages"] = deleted_count
                print(f"✅ room_messages: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"room_messages削除エラー: {e}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)
            
            # 2. processed_messages（7日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM processed_messages 
                        WHERE processed_at < :cutoff_date
                        RETURNING message_id
                    """),
                    {"cutoff_date": seven_days_ago}
                )
                deleted_count = result.rowcount
                results["processed_messages"] = deleted_count
                print(f"✅ processed_messages: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"processed_messages削除エラー: {e}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)
            
            # 3. conversation_timestamps（30日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM conversation_timestamps 
                        WHERE updated_at < :cutoff_date
                        RETURNING room_id
                    """),
                    {"cutoff_date": thirty_days_ago}
                )
                deleted_count = result.rowcount
                results["conversation_timestamps"] = deleted_count
                print(f"✅ conversation_timestamps: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"conversation_timestamps削除エラー: {e}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)
            
    except Exception as e:
        error_msg = f"PostgreSQL接続エラー: {e}"
        print(f"❌ {error_msg}")
        traceback.print_exc()
        results["errors"].append(error_msg)
    
    # ===== Firestore クリーンアップ =====
    try:
        # conversationsコレクションから30日以上前のドキュメントを削除
        conversations_ref = db.collection("conversations")
        
        # updated_atが30日以上前のドキュメントを取得
        old_docs = conversations_ref.where(
            "updated_at", "<", thirty_days_ago
        ).stream()
        
        deleted_count = 0
        batch = db.batch()
        batch_count = 0
        
        for doc in old_docs:
            batch.delete(doc.reference)
            batch_count += 1
            deleted_count += 1
            
            # Firestoreのバッチは500件まで
            if batch_count >= 500:
                batch.commit()
                batch = db.batch()
                batch_count = 0
        
        # 残りをコミット
        if batch_count > 0:
            batch.commit()
        
        results["firestore_conversations"] = deleted_count
        print(f"✅ Firestore conversations: {deleted_count}件削除")
        
    except Exception as e:
        error_msg = f"Firestoreクリーンアップエラー: {e}"
        print(f"❌ {error_msg}")
        results["errors"].append(error_msg)
    
    # ===== Firestore pending_tasks クリーンアップ（NEW） =====
    try:
        pending_tasks_ref = db.collection("pending_tasks")
        
        old_pending_docs = pending_tasks_ref.where(
            "created_at", "<", one_day_ago
        ).stream()
        
        deleted_count = 0
        batch = db.batch()
        batch_count = 0
        
        for doc in old_pending_docs:
            batch.delete(doc.reference)
            batch_count += 1
            deleted_count += 1
            
            if batch_count >= 500:
                batch.commit()
                batch = db.batch()
                batch_count = 0
        
        if batch_count > 0:
            batch.commit()
        
        results["firestore_pending_tasks"] = deleted_count
        print(f"✅ Firestore pending_tasks: {deleted_count}件削除")
        
    except Exception as e:
        error_msg = f"Firestore pending_tasksクリーンアップエラー: {e}"
        print(f"❌ {error_msg}")
        results["errors"].append(error_msg)
    
    # ===== サマリー =====
    print("=" * 50)
    print("📊 クリーンアップ結果:")
    print(f"   - room_messages: {results['room_messages']}件削除")
    print(f"   - processed_messages: {results['processed_messages']}件削除")
    print(f"   - conversation_timestamps: {results['conversation_timestamps']}件削除")
    print(f"   - Firestore conversations: {results['firestore_conversations']}件削除")
    print(f"   - Firestore pending_tasks: {results['firestore_pending_tasks']}件削除")
    if results["errors"]:
        print(f"   - エラー: {len(results['errors'])}件")
        for err in results["errors"]:
            print(f"     ・{err}")
    print("=" * 50)
    print("🧹 クリーンアップ完了")
    
    return jsonify({
        "status": "ok" if not results["errors"] else "partial",
        "results": results
    })
