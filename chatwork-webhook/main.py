import functions_framework
from flask import jsonify
from google.cloud import secretmanager, firestore
import httpx
import re
import time
import os  # v10.22.4: 環境変数による機能制御用
import asyncio  # v10.21.0: Memory Framework統合用
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional  # v10.40.9: 型アノテーション用
import pg8000
import sqlalchemy
from sqlalchemy import bindparam  # v6.8.3: expanding IN対応
from google.cloud.sql.connector import Connector
import json
from functools import lru_cache
import traceback
import hmac  # v6.8.9: Webhook署名検証用
import hashlib  # v6.8.9: Webhook署名検証用
import base64  # v6.8.9: Webhook署名検証用

# =====================================================
# v10.30.1: 管理者設定モジュール（Phase A）
# =====================================================
# ハードコードされていた ADMIN_ACCOUNT_ID, ADMIN_ROOM_ID を
# データベースから取得するモジュール
try:
    from lib.admin_config import (
        get_admin_config,
        get_admin_account_id,
        get_admin_room_id,
        is_admin_account,
        clear_admin_config_cache,
        AdminConfig,
        DEFAULT_ORG_ID as ADMIN_CONFIG_DEFAULT_ORG_ID,
    )
    USE_ADMIN_CONFIG = True
    print("✅ lib/admin_config.py loaded for admin configuration")
except ImportError as e:
    print(f"⚠️ lib/admin_config.py not available (using fallback): {e}")
    USE_ADMIN_CONFIG = False

# =====================================================
# v10.31.1: Phase D - 接続設定集約
# =====================================================
# DB接続設定（INSTANCE_CONNECTION_NAME, DB_NAME, DB_USER）を
# lib/db.py + lib/config.py で一元管理
try:
    from lib.db import get_db_pool as _lib_get_db_pool, get_db_connection as _lib_get_db_connection
    from lib.secrets import get_secret_cached as _lib_get_secret
    from lib.config import get_settings
    USE_LIB_DB = True
    print("✅ lib/db.py loaded for database connection (Phase D)")
except ImportError as e:
    print(f"⚠️ lib/db.py not available (using fallback): {e}")
    USE_LIB_DB = False

# =====================================================
# v10.18.1: summary生成用ライブラリ
# =====================================================
try:
    from lib import (
        clean_chatwork_tags,
        prepare_task_display_text,
        extract_task_subject,
        validate_summary,
    )
    USE_TEXT_UTILS_LIB = True
    print("✅ lib/text_utils.py loaded for summary generation")
except ImportError as e:
    print(f"⚠️ lib/text_utils.py not available: {e}")
    USE_TEXT_UTILS_LIB = False

# =====================================================
# v10.18.1: ユーザーユーティリティ（Phase 3.5対応）
# =====================================================
try:
    from lib import (
        get_user_primary_department as lib_get_user_primary_department,
    )
    USE_USER_UTILS_LIB = True
    print("✅ lib/user_utils.py loaded for department_id")
except ImportError as e:
    print(f"⚠️ lib/user_utils.py not available: {e}")
    USE_USER_UTILS_LIB = False

# =====================================================
# v10.26.0: 営業日判定ユーティリティ
# =====================================================
try:
    from lib.business_day import (
        is_business_day,
        get_non_business_day_reason,
    )
    USE_BUSINESS_DAY_LIB = True
    print("✅ lib/business_day.py loaded for holiday detection")
except ImportError as e:
    print(f"⚠️ lib/business_day.py not available: {e}")
    USE_BUSINESS_DAY_LIB = False
    is_business_day = None
    get_non_business_day_reason = None

# =====================================================
# v10.19.0: Phase 2.5 目標設定対話フロー
# =====================================================
try:
    from lib import (
        GoalSettingDialogue,
        has_active_goal_session,
        process_goal_setting_message,
    )
    USE_GOAL_SETTING_LIB = True
    print("✅ lib/goal_setting.py loaded for goal setting dialogue")
except ImportError as e:
    print(f"⚠️ lib/goal_setting.py not available: {e}")
    USE_GOAL_SETTING_LIB = False

# =====================================================
# v10.40.8: ユーザー長期記憶（プロフィール）
# =====================================================
try:
    from lib.long_term_memory import (
        is_long_term_memory_request,
        save_long_term_memory,
        get_user_life_why,
        LongTermMemoryManager,
        MemoryScope,  # v10.40.9: アクセススコープ
    )
    USE_LONG_TERM_MEMORY = True
    print("✅ lib/long_term_memory.py loaded for user profile memory")
except ImportError as e:
    print(f"⚠️ lib/long_term_memory.py not available: {e}")
    USE_LONG_TERM_MEMORY = False

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
# v10.21.0: Phase 2 B 記憶機能（Memory Framework）統合
# =====================================================
try:
    from lib.memory import (
        ConversationSummary,
        UserPreference,
        ConversationSearch,
        MemoryParameters,
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
            MVVContext,
            detect_ng_pattern,
            analyze_basic_needs,
            get_mvv_context,
            should_flag_for_review,
            ORGANIZATIONAL_THEORY_PROMPT,
            RiskLevel,
            AlertType,
            is_mvv_question,
            get_full_mvv_info,
            ensure_soul_os_compliant,  # v10.41.0: 社長の魂OSガードレール
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
    get_overdue_days as _new_get_overdue_days,
    JST as _utils_JST,
    DEADLINE_ALERT_DAYS as _utils_DEADLINE_ALERT_DAYS,
)
USE_NEW_DATE_UTILS = True
print("✅ utils/date_utils.py loaded for date processing")

# =====================================================
# utils/chatwork_utils.py ChatWork APIユーティリティ
# v10.33.0: フォールバック削除
# =====================================================
from utils.chatwork_utils import (
    APICallCounter as _new_APICallCounter,
    get_api_call_counter as _new_get_api_call_counter,
    reset_api_call_counter as _new_reset_api_call_counter,
    clear_room_members_cache as _new_clear_room_members_cache,
    call_chatwork_api_with_retry as _new_call_chatwork_api_with_retry,
    get_room_members as _new_get_room_members,
    get_room_members_cached as _new_get_room_members_cached,
    is_room_member as _new_is_room_member,
)
USE_NEW_CHATWORK_UTILS = True
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
# v10.29.0: 脳アーキテクチャ（Brain Architecture）
# 環境変数 USE_BRAIN_ARCHITECTURE で有効化（段階的導入）
# 設定値: false（無効）/ true（有効）/ shadow（シャドウ）/ gradual（段階的）
# 設計書: docs/13_brain_architecture.md
# =====================================================
try:
    from lib.brain import (
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
    print(f"✅ lib/brain loaded (v10.29.0), enabled={USE_BRAIN_ARCHITECTURE}, mode={_brain_mode}")
except ImportError as e:
    print(f"⚠️ lib/brain not available: {e}")
    USE_BRAIN_ARCHITECTURE = False
    BrainIntegration = None
    IntegrationResult = None
    IntegrationConfig = None
    IntegrationMode = None
    create_integration = None
    is_brain_enabled = None

# SoulkunBrainインスタンス（後方互換用）
_brain_instance = None
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

PROJECT_ID = "soulkun-production"
db = firestore.Client(project=PROJECT_ID)

# Cloud SQL設定（フォールバック用）
# v10.31.1: USE_LIB_DB=True の場合は lib/config.py から取得
if not USE_LIB_DB:
    INSTANCE_CONNECTION_NAME = "soulkun-production:asia-northeast1:soulkun-db"
    DB_NAME = "soulkun_tasks"
    DB_USER = "soulkun_user"

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
import os

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
BOT_ACCOUNT_ID = "10909425"  # Phase 1-B用

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
import re

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

def match_local_command(message: str):
    """
    ローカルで処理可能なコマンドかどうかを判定
    
    Returns:
        (action, groups) - マッチした場合
        (None, None) - マッチしない場合
    """
    message = message.strip()
    for pattern, action in LOCAL_COMMAND_PATTERNS:
        match = re.match(pattern, message)
        if match:
            return action, match.groups()
    return None, None

# 遅延管理設定
ESCALATION_DAYS = 3  # エスカレーションまでの日数

# Cloud SQL接続プール
_pool = None
_connector = None  # グローバルConnector（接続リーク防止）

# ★★★ v6.8.2: 実行内メモリキャッシュ（N+1問題対策）★★★
_runtime_dm_cache = {}  # {account_id: room_id} - 実行中のDMルームキャッシュ
_runtime_direct_rooms = None  # get_all_rooms()の結果キャッシュ（v6.8.3では未使用だが互換性のため残す）
_runtime_contacts_cache = None  # ★★★ v6.8.3: /contacts APIの結果キャッシュ ★★★
_runtime_contacts_fetched_ok = None  # ★★★ v6.8.4: /contacts API成功フラグ（True=成功, False=失敗, None=未取得）★★★
_dm_unavailable_buffer = []  # ★★★ v6.8.3: DM不可通知のバッファ（まとめ送信用）★★★

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
# 
# 【設計思想】
# - 新機能追加時はこのカタログに1エントリ追加するだけ
# - AI司令塔はこのカタログを読んで、自分の能力を把握する
# - execute_actionはカタログを参照して動的に機能を実行
#
# 【将来の拡張】
# - enabled=False の機能は実装後にTrueに変更
# - 新機能はこのカタログに追加するだけでAIが認識
# =====================================================

SYSTEM_CAPABILITIES = {
    # ===== タスク管理 =====
    "chatwork_task_create": {
        "name": "ChatWorkタスク作成",
        "description": "ChatWorkで指定した担当者にタスクを作成する。タスクの追加、作成、依頼、お願いなどの要望に対応。",
        "category": "task",
        "enabled": True,
        "trigger_examples": [
            "〇〇さんに△△のタスクを追加して",
            "〇〇に△△をお願いして、期限は明日",
            "俺に△△のタスク作成して",
            "タスク依頼：〇〇さんに△△",
        ],
        "params_schema": {
            "assigned_to": {
                "type": "string",
                "description": "担当者名（ChatWorkユーザー一覧から正確な名前を選択）",
                "required": True,
                "source": "chatwork_users",
                "note": "「俺」「自分」「私」「僕」の場合は「依頼者自身」と出力"
            },
            "task_body": {
                "type": "string",
                "description": "タスクの内容",
                "required": True
            },
            "limit_date": {
                "type": "date",
                "description": "期限日（YYYY-MM-DD形式）",
                "required": True,
                "note": "「明日」→翌日、「明後日」→2日後、「来週金曜」→該当日に変換。期限の指定がない場合は必ずユーザーに確認"
            },
            "limit_time": {
                "type": "time",
                "description": "期限時刻（HH:MM形式）",
                "required": False
            }
        },
        "handler": "handle_chatwork_task_create",
        "requires_confirmation": False,
        "required_data": ["chatwork_users", "sender_name"],
        # v10.30.0: 脳アーキテクチャ用メタデータ（設計書7.3準拠）
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["タスク作成", "タスク追加", "タスク作って", "依頼して", "お願いして"],
                "secondary": ["タスク", "仕事", "やること", "依頼", "お願い"],
                "negative": ["検索", "一覧", "教えて", "完了"],
            },
            "intent_keywords": {
                "primary": ["タスク作成", "タスク追加", "タスク作って", "依頼して", "お願い"],
                "secondary": ["タスク", "仕事", "やること"],
                "modifiers": ["作成", "追加", "作って", "お願い", "依頼"],
                "negative": [],
                "confidence_boost": 0.85,
            },
            "risk_level": "low",
            "priority": 3,
        },
    },
    # ===== 振り返り =====
    "daily_reflection": {
        "name": "日次振り返り",
        "description": "今日一日の振り返りを行う。選択理論に基づいた内省を促す。",
        "category": "reflection",
        "enabled": True,
        "trigger_examples": ["振り返りをしたい", "今日の反省"],
        "params_schema": {
            "reflection_text": {
                "type": "string",
                "description": "振り返りの内容",
                "required": True
            }
        },
        "handler": "handle_daily_reflection",
        "requires_confirmation": False,
        "required_data": [],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["振り返り", "反省", "日報"],
                "secondary": ["今日一日", "1日を振り返る"],
                "negative": [],
            },
            "intent_keywords": {
                "primary": ["振り返り", "日報"],
                "secondary": ["今日一日", "反省"],
                "modifiers": [],
                "negative": [],
                "confidence_boost": 0.75,
            },
            "risk_level": "low",
            "priority": 7,
        },
    },

    
    "chatwork_task_complete": {
        "name": "ChatWorkタスク完了",
        "description": "タスクを完了状態にする。「完了にして」「終わった」などの要望に対応。番号指定またはタスク内容で特定。",
        "category": "task",
        "enabled": True,
        "trigger_examples": [
            "1のタスクを完了にして",
            "タスク1を完了",
            "資料作成のタスク完了にして",
            "さっきのタスク終わった",
        ],
        "params_schema": {
            "task_identifier": {
                "type": "string",
                "description": "タスクを特定する情報（番号、タスク内容の一部、または「さっきの」など）",
                "required": True
            }
        },
        "handler": "handle_chatwork_task_complete",
        "requires_confirmation": False,
        "required_data": ["recent_tasks_context"],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["タスク完了", "完了にして", "終わった", "できた"],
                "secondary": ["完了", "終わり", "done"],
                "negative": ["作成", "追加", "検索"],
            },
            "intent_keywords": {
                "primary": ["タスク完了", "タスク終わった", "タスクできた"],
                "secondary": ["タスク", "仕事"],
                "modifiers": ["完了", "終わった", "できた", "done", "済み"],
                "negative": [],
                "confidence_boost": 0.85,
            },
            "risk_level": "low",
            "priority": 3,
        },
    },
    
    "chatwork_task_search": {
        "name": "タスク検索",
        "description": "特定の人のタスクや、自分のタスクを検索して表示する。「〇〇のタスク」「自分のタスク」「未完了のタスク」などの要望に対応。",
        "category": "task",
        "enabled": True,
        "trigger_examples": [
            "崇樹のタスク教えて",
            "自分のタスク教えて",
            "俺のタスク何がある？",
            "未完了のタスク一覧",
            "〇〇さんが抱えてるタスク",
        ],
        "params_schema": {
            "person_name": {
                "type": "string",
                "description": "タスクを検索する人物名。「自分」「俺」「私」の場合は「sender」と出力",
                "required": False
            },
            "status": {
                "type": "string",
                "description": "タスクの状態（open/done/all）",
                "required": False,
                "default": "open"
            },
            "assigned_by": {
                "type": "string",
                "description": "タスクを依頼した人物名（〇〇から振られたタスク）",
                "required": False
            }
        },
        "handler": "handle_chatwork_task_search",
        "requires_confirmation": False,
        "required_data": ["chatwork_users", "sender_name"],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["タスク検索", "タスク教えて", "タスク一覧", "タスク確認"],
                "secondary": ["タスク", "何がある", "抱えてる"],
                "negative": ["作成", "追加", "作って", "完了"],
            },
            "intent_keywords": {
                "primary": ["タスク検索", "タスク確認", "タスク教えて", "タスク一覧"],
                "secondary": ["タスク", "仕事", "やること"],
                "modifiers": ["検索", "教えて", "見せて", "一覧", "確認"],
                "negative": [],
                "confidence_boost": 0.85,
            },
            "risk_level": "low",
            "priority": 3,
        },
    },
    
    # ===== 記憶機能 =====
    "save_memory": {
        "name": "人物情報を記憶",
        "description": "人物の情報（部署、役職、趣味、特徴など）を記憶する。「〇〇さんは△△です」のような情報を覚える。",
        "category": "memory",
        "enabled": True,
        "trigger_examples": [
            "〇〇さんは営業部の部長です",
            "〇〇さんの趣味はゴルフだよ",
            "〇〇さんを覚えて、△△担当の人",
            "〇〇は□□出身だって",
        ],
        "params_schema": {
            "attributes": {
                "type": "array",
                "description": "記憶する属性のリスト",
                "required": True,
                "items_schema": {
                    "person": "人物名",
                    "type": "属性タイプ（部署/役職/趣味/住所/特徴/メモ/読み/あだ名/その他）",
                    "value": "属性の値"
                }
            }
        },
        "handler": "handle_save_memory",
        "requires_confirmation": False,
        "required_data": [],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["覚えて", "記憶して", "メモして"],
                "secondary": ["は〜です", "さんは", "の人"],
                "negative": ["忘れて", "削除", "教えて"],
            },
            "intent_keywords": {
                "primary": ["人を覚えて", "社員を記憶"],
                "secondary": ["覚えて", "記憶して", "メモして"],
                "modifiers": ["人", "さん", "社員"],
                "negative": [],
                "confidence_boost": 0.85,
            },
            "risk_level": "low",
            "priority": 5,
        },
    },
    
    "query_memory": {
        "name": "人物情報を検索",
        "description": "記憶している人物の情報を検索・表示する。特定の人について聞かれた時や、覚えている人全員を聞かれた時に使用。",
        "category": "memory",
        "enabled": True,
        "trigger_examples": [
            "〇〇さんについて教えて",
            "〇〇さんのこと知ってる？",
            "誰を覚えてる？",
            "覚えている人を全員教えて",
        ],
        "params_schema": {
            "persons": {
                "type": "array",
                "description": "検索したい人物名のリスト",
                "required": False
            },
            "is_all_persons": {
                "type": "boolean",
                "description": "全員の情報を取得するかどうか",
                "required": False,
                "default": False
            }
        },
        "handler": "handle_query_memory",
        "requires_confirmation": False,
        "required_data": ["all_persons"],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["覚えてる", "知ってる", "について教えて"],
                "secondary": ["誰", "情報"],
                "negative": ["覚えて", "記憶して", "忘れて"],
            },
            "intent_keywords": {
                "primary": ["について教えて", "のこと知ってる"],
                "secondary": ["誰", "人物"],
                "modifiers": ["教えて", "知ってる"],
                "negative": ["覚えて", "忘れて"],
                "confidence_boost": 0.8,
            },
            "risk_level": "low",
            "priority": 5,
        },
    },

    "delete_memory": {
        "name": "人物情報を削除",
        "description": "記憶している人物の情報を削除する。忘れてほしいと言われた時に使用。",
        "category": "memory",
        "enabled": True,
        "trigger_examples": [
            "〇〇さんのことを忘れて",
            "〇〇さんの記憶を削除して",
            "〇〇の情報を消して",
        ],
        "params_schema": {
            "persons": {
                "type": "array",
                "description": "削除したい人物名のリスト",
                "required": True
            }
        },
        "handler": "handle_delete_memory",
        "requires_confirmation": False,
        "required_data": [],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["忘れて", "削除して", "消して"],
                "secondary": ["記憶", "情報"],
                "negative": ["覚えて", "教えて"],
            },
            "intent_keywords": {
                "primary": ["忘れて", "削除して"],
                "secondary": ["記憶", "情報"],
                "modifiers": ["消して", "削除"],
                "negative": ["覚えて"],
                "confidence_boost": 0.8,
            },
            "risk_level": "medium",
            "priority": 6,
        },
    },
    
    # ===== v6.9.0: 管理者学習機能 =====
    "learn_knowledge": {
        "name": "知識を学習",
        "description": "ソウルくん自身についての設定や知識を学習する。「設定：〇〇」「覚えて：〇〇」などの要望に対応。管理者（菊地さん）からは即時反映、他のスタッフからは提案として受け付ける。",
        "category": "learning",
        "enabled": True,
        "trigger_examples": [
            "設定：ソウルくんは狼がモチーフ",
            "覚えて：ソウルくんは元気な性格",
            "ルール：タスクの期限は必ず確認する",
            "ソウルくんは柴犬じゃなくて狼だよ",
        ],
        "params_schema": {
            "category": {
                "type": "string",
                "description": "知識のカテゴリ（character=キャラ設定/rules=業務ルール/other=その他）",
                "required": True
            },
            "key": {
                "type": "string",
                "description": "何についての知識か（例：モチーフ、性格、口調）",
                "required": True
            },
            "value": {
                "type": "string",
                "description": "知識の内容（例：狼、元気で明るい）",
                "required": True
            }
        },
        "handler": "handle_learn_knowledge",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "sender_name", "room_id"],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["ナレッジ追加", "知識を覚えて", "教えておくね"],
                "secondary": ["ナレッジ", "知識", "情報"],
                "negative": ["検索", "教えて", "忘れて"],
            },
            "intent_keywords": {
                "primary": ["知識を覚えて", "ナレッジ追加"],
                "secondary": ["覚えて", "記憶して", "メモして"],
                "modifiers": [],
                "negative": ["検索", "教えて"],
                "confidence_boost": 0.8,
            },
            "risk_level": "low",
            "priority": 5,
        },
    },

    "forget_knowledge": {
        "name": "知識を削除",
        "description": "学習した知識を削除する。「忘れて：〇〇」などの要望に対応。管理者のみ実行可能。",
        "category": "learning",
        "enabled": True,
        "trigger_examples": [
            "忘れて：ソウルくんのモチーフ",
            "設定削除：〇〇",
            "〇〇の設定を消して",
        ],
        "params_schema": {
            "key": {
                "type": "string",
                "description": "削除する知識のキー",
                "required": True
            },
            "category": {
                "type": "string",
                "description": "知識のカテゴリ（省略可）",
                "required": False
            }
        },
        "handler": "handle_forget_knowledge",
        "requires_confirmation": False,
        "required_data": ["sender_account_id"],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["ナレッジ削除", "知識を忘れて"],
                "secondary": ["削除", "忘れて"],
                "negative": ["追加", "検索", "教えて"],
            },
            "intent_keywords": {
                "primary": ["知識を忘れて", "ナレッジ削除"],
                "secondary": ["忘れて", "削除して", "消して"],
                "modifiers": [],
                "negative": ["追加", "検索"],
                "confidence_boost": 0.8,
            },
            "risk_level": "medium",
            "priority": 6,
        },
    },

    "list_knowledge": {
        "name": "学習した知識を一覧表示",
        "description": "ソウルくんが学習した知識の一覧を表示する。「何覚えてる？」「設定一覧」などの要望に対応。",
        "category": "learning",
        "enabled": True,
        "trigger_examples": [
            "何覚えてる？",
            "設定一覧",
            "学習した知識を教えて",
            "ソウルくんの設定を見せて",
        ],
        "params_schema": {},
        "handler": "handle_list_knowledge",
        "requires_confirmation": False,
        "required_data": [],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["設定一覧", "何覚えてる", "知識一覧"],
                "secondary": ["設定", "知識", "学習"],
                "negative": [],
            },
            "intent_keywords": {
                "primary": ["設定一覧", "知識一覧"],
                "secondary": ["何覚えてる", "設定を見せて"],
                "modifiers": ["一覧", "リスト"],
                "negative": [],
                "confidence_boost": 0.75,
            },
            "risk_level": "low",
            "priority": 6,
        },
    },

    # v10.29.9: approve_proposal → proposal_decision（handlers/brain層と統一）
    "proposal_decision": {
        "name": "提案を承認",
        "description": "スタッフからの知識提案を承認する。管理者のみ実行可能。",
        "category": "learning",
        "enabled": True,
        "trigger_examples": [
            "承認",
            "OK",
            "いいよ",
            "反映して",
        ],
        "params_schema": {
            "decision": {
                "type": "string",
                "description": "承認=approve / 却下=reject",
                "required": True
            }
        },
        "handler": "handle_proposal_decision",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "room_id"],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["承認", "却下", "反映して"],
                "secondary": ["OK", "いいよ", "ダメ", "やめて"],
                "negative": [],
            },
            "intent_keywords": {
                "primary": ["承認", "却下"],
                "secondary": ["OK", "反映して"],
                "modifiers": ["いいよ", "ダメ"],
                "negative": [],
                "confidence_boost": 0.8,
            },
            "risk_level": "medium",
            "priority": 4,
        },
    },

    # ===== 組織図クエリ（Phase 3.5） =====
    "query_org_chart": {
        "name": "組織図・部署情報検索",
        "description": "組織図の全体構造、部署のメンバー、部署の詳細情報を検索して表示する。",
        "category": "organization",
        "enabled": True,
        "trigger_examples": [
            "組織図を教えて",
            "会社の組織を見せて",
            "営業部の人は誰？",
            "管理部のメンバーを教えて",
            "開発部について教えて",
        ],
        "params_schema": {
            "query_type": {
                "type": "string",
                "description": "検索タイプ（overview=組織全体, members=部署メンバー, detail=部署詳細）",
                "required": True
            },
            "department": {
                "type": "string",
                "description": "部署名（members/detailの場合は必須）",
                "required": False
            }
        },
        "handler": "handle_query_org_chart",
        "requires_confirmation": False,
        "required_data": [],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["組織図", "部署", "誰がいる"],
                "secondary": ["組織", "構造", "チーム"],
                "negative": [],
            },
            "intent_keywords": {
                "primary": ["組織図", "部署一覧"],
                "secondary": ["組織", "部署", "チーム", "誰が", "担当者", "上司", "部下"],
                "modifiers": [],
                "negative": [],
                "confidence_boost": 0.75,
            },
            "risk_level": "low",
            "priority": 6,
        },
    },

    # ===== 一般会話 =====
    # v10.29.9: general_chat → general_conversation（handlers/brain層と統一）
    "general_conversation": {
        "name": "一般会話",
        "description": "上記のどの機能にも当てはまらない一般的な会話、質問、雑談、挨拶などに対応。",
        "category": "chat",
        "enabled": True,
        "trigger_examples": [
            "こんにちは",
            "ありがとう",
            "〇〇について教えて",
            "どう思う？",
        ],
        "params_schema": {},
        "handler": "handle_general_chat",
        "requires_confirmation": False,
        "required_data": [],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": [],
                "secondary": ["こんにちは", "ありがとう", "どう思う"],
                "negative": [],
            },
            "intent_keywords": {
                "primary": [],
                "secondary": [],
                "modifiers": [],
                "negative": [],
                "confidence_boost": 0.5,
            },
            "risk_level": "low",
            "priority": 10,  # 最低優先度（他に該当しない場合のフォールバック）
        },
    },
    
    # ===== v10.38.0: 生成機能（Brain-Capability統合） =====
    # 設計書: docs/brain_capability_integration_design.md

    "generate_document": {
        "name": "文書生成",
        "description": "Google Docsで文書（レポート、議事録、提案書、マニュアル等）を生成する。資料作成、ドキュメント作成、レポート作成などの要望に対応。",
        "category": "generation",
        "enabled": True,  # v10.38.0: Brain-Capability統合で有効化
        "trigger_examples": [
            "〇〇の資料を作成して",
            "議事録を作って",
            "報告書を書いて",
            "〇〇についてのレポートを作成して",
            "提案書を作って",
            "マニュアルを作成して",
        ],
        "params_schema": {
            "topic": {
                "type": "string",
                "description": "文書のトピック・内容",
                "required": True,
                "note": "【必須】何についての文書か"
            },
            "document_type": {
                "type": "string",
                "description": "文書タイプ: report（報告書）, summary（要約）, proposal（提案書）, minutes（議事録）, manual（マニュアル）",
                "required": False,
                "default": "report",
                "note": "省略時はreport"
            },
            "outline": {
                "type": "string",
                "description": "アウトライン（章立て）",
                "required": False,
                "note": "ユーザーが指定した場合のみ"
            },
        },
        "handler": "generate_document",  # CapabilityBridgeのハンドラー名
        "requires_confirmation": True,
        "required_data": [],
        # v10.38.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["資料作成", "ドキュメント作成", "レポート作成", "議事録作成", "提案書作成"],
                "secondary": ["資料", "ドキュメント", "レポート", "議事録", "書いて"],
                "negative": ["画像", "動画", "検索", "教えて"],
            },
            "intent_keywords": {
                "primary": ["資料作成", "文書生成", "ドキュメント作成"],
                "secondary": ["レポート", "議事録", "提案書", "マニュアル"],
                "modifiers": ["作って", "作成", "書いて", "生成"],
                "negative": [],
                "confidence_boost": 0.85,
            },
            "risk_level": "medium",  # コストがかかるため
            "priority": 4,
        },
    },

    # v10.38.0: 旧create_documentはgenerate_documentのエイリアス
    "create_document": {
        "name": "資料作成（エイリアス）",
        "description": "generate_documentのエイリアス。「資料を作成して」等の要望に対応。",
        "category": "generation",
        "enabled": True,
        "trigger_examples": ["〇〇の資料を作成して"],
        "params_schema": {},
        "handler": "generate_document",  # generate_documentと同じハンドラー
        "requires_confirmation": True,
        "required_data": [],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["資料作成"],
                "secondary": [],
                "negative": [],
            },
            "intent_keywords": {
                "primary": ["資料作成"],
                "secondary": [],
                "modifiers": [],
                "negative": [],
                "confidence_boost": 0.8,
            },
            "risk_level": "medium",
            "priority": 5,  # generate_documentより低い
        },
    },
    
    # v10.29.9: query_company_knowledge → query_knowledge（handlers/brain層と統一）
    "query_knowledge": {
        "name": "会社知識の参照",
        "description": "就業規則、マニュアル、社内ルールなど会社の知識ベースを参照して回答する。有給休暇、経費精算、各種手続きなどの質問に対応。",
        "category": "knowledge",
        "enabled": True,  # v10.13.0: Phase 3統合で有効化
        "trigger_examples": [
            "有給休暇は何日？",
            "有休って何日もらえる？",
            "就業規則を教えて",
            "経費精算のルールは？",
            "残業の申請方法は？",
            "うちの会社の理念って何？",
        ],
        "params_schema": {
            "query": {
                "type": "string",
                "description": "検索したい内容（質問文そのまま）",
                "required": True
            },
        },
        "handler": "handle_query_company_knowledge",
        "requires_confirmation": False,
        "required_data": [],  # Phase 3 APIを使用するため外部データ不要
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["ナレッジ検索", "知識を教えて", "会社について"],
                "secondary": ["どうやって", "方法", "やり方"],
                "negative": ["追加", "覚えて", "忘れて"],
            },
            "intent_keywords": {
                "primary": ["教えて", "知りたい"],
                "secondary": ["就業規則", "規則", "ルール", "マニュアル", "手順", "方法"],
                "modifiers": [],
                "negative": ["追加", "覚えて"],
                "confidence_boost": 0.8,
            },
            "risk_level": "low",
            "priority": 5,
        },
    },
    
    "generate_image": {
        "name": "画像生成",
        "description": "DALL-Eで画像を生成する。イラスト作成、図の作成、画像作成などの要望に対応。",
        "category": "generation",
        "enabled": True,  # v10.38.0: Brain-Capability統合で有効化
        "trigger_examples": [
            "〇〇の画像を作って",
            "こんなイメージの絵を描いて",
            "〇〇のイラストを作成して",
            "図を描いて",
        ],
        "params_schema": {
            "prompt": {
                "type": "string",
                "description": "画像の説明",
                "required": True,
                "note": "【必須】どんな画像を生成するか"
            },
            "style": {
                "type": "string",
                "description": "スタイル: realistic（写実的）, anime（アニメ風）, watercolor（水彩画風）等",
                "required": False,
                "note": "省略時は自動判定"
            },
            "size": {
                "type": "string",
                "description": "サイズ: 1024x1024（正方形）, 1792x1024（横長）, 1024x1792（縦長）",
                "required": False,
                "default": "1024x1024",
            },
        },
        "handler": "generate_image",  # CapabilityBridgeのハンドラー名
        "requires_confirmation": True,  # v10.38.0: コストがかかるため確認必須
        "required_data": [],
        # v10.38.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["画像作成", "イラスト作成", "画像を作って", "絵を描いて"],
                "secondary": ["画像", "イラスト", "図", "絵"],
                "negative": ["資料", "文書", "動画", "検索"],
            },
            "intent_keywords": {
                "primary": ["画像作成", "画像生成", "イラスト作成"],
                "secondary": ["画像", "イラスト", "絵", "図"],
                "modifiers": ["作って", "作成", "描いて", "生成"],
                "negative": [],
                "confidence_boost": 0.85,
            },
            "risk_level": "medium",  # コストがかかるため
            "priority": 4,
        },
    },

    "generate_video": {
        "name": "動画生成",
        "description": "Runway Gen-3で動画を生成する。動画作成、ムービー作成などの要望に対応。コストが高いため慎重に使用。",
        "category": "generation",
        "enabled": False,  # v10.38.0: コストが高いためデフォルト無効（環境変数で有効化可能）
        "trigger_examples": [
            "〇〇の動画を作って",
            "ムービーを作成して",
            "〇〇のPRビデオを作って",
        ],
        "params_schema": {
            "prompt": {
                "type": "string",
                "description": "動画の説明",
                "required": True,
                "note": "【必須】どんな動画を生成するか"
            },
            "duration": {
                "type": "number",
                "description": "長さ（秒）: 5または10",
                "required": False,
                "default": 5,
            },
        },
        "handler": "generate_video",  # CapabilityBridgeのハンドラー名
        "requires_confirmation": True,
        "required_data": [],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["動画作成", "ムービー作成", "動画を作って"],
                "secondary": ["動画", "ムービー", "ビデオ"],
                "negative": ["画像", "資料", "文書"],
            },
            "intent_keywords": {
                "primary": ["動画作成", "動画生成"],
                "secondary": ["動画", "ムービー", "ビデオ"],
                "modifiers": ["作って", "作成", "生成"],
                "negative": [],
                "confidence_boost": 0.85,
            },
            "risk_level": "high",  # コストが非常に高い
            "priority": 3,
        },
    },
    
    "schedule_management": {
        "name": "スケジュール管理",
        "description": "Googleカレンダーと連携してスケジュールを管理する",
        "category": "schedule",
        "enabled": False,  # 将来実装
        "trigger_examples": [
            "明日の予定を教えて",
            "〇〇の会議を入れて",
            "来週の空いてる時間は？",
        ],
        "params_schema": {
            "action": {"type": "string", "description": "操作（view/create/update/delete）"},
            "date": {"type": "date", "description": "日付"},
            "title": {"type": "string", "description": "予定のタイトル"},
        },
        "handler": "handle_schedule_management",
        "requires_confirmation": True,
        "required_data": ["google_calendar_api"]
    },
    
    # ===== API制約により実装不可能な機能 =====
    # ※ユーザーが要求した場合に適切な説明を返す
    
    "chatwork_task_edit": {
        "name": "タスク編集（API制約により不可）",
        "description": "タスクの期限変更や内容変更を行う。「期限を変更して」「タスクを編集して」などの要望に対応。※ChatWork APIにタスク編集機能がないため、ソウルくんでは対応不可。",
        "category": "task",
        "enabled": True,  # ユーザーの要求を検知するためTrue
        "api_limitation": True,  # API制約フラグ
        "trigger_examples": [
            "タスクの期限を変更して",
            "〇〇のタスクを編集して",
            "期限を明日に変えて",
            "タスクの内容を修正して",
        ],
        "params_schema": {},
        "handler": "handle_api_limitation",
        "requires_confirmation": False,
        "required_data": [],
        "limitation_message": "タスクの編集（期限変更・内容変更）"
    },
    
    "chatwork_task_delete": {
        "name": "タスク削除（API制約により不可）",
        "description": "タスクを削除する。「タスクを削除して」「タスクを消して」などの要望に対応。※ChatWork APIにタスク削除機能がないため、ソウルくんでは対応不可。",
        "category": "task",
        "enabled": True,  # ユーザーの要求を検知するためTrue
        "api_limitation": True,  # API制約フラグ
        "trigger_examples": [
            "タスクを削除して",
            "このタスクを消して",
            "〇〇のタスクを取り消して",
            "間違えて作ったタスクを消して",
        ],
        "params_schema": {},
        "handler": "handle_api_limitation",
        "requires_confirmation": False,
        "required_data": [],
        "limitation_message": "タスクの削除"
    },

    # =====================================================
    # ===== Phase 2.5: 目標達成支援 =====
    # =====================================================

    "goal_registration": {
        "name": "目標登録",
        "description": "今月の目標や個人目標を登録する。「〇〇を達成したい」「今月の目標は△△」「目標を設定したい」などの要望に対応。数値目標（粗利300万円）、期限目標（月末までに完了）、行動目標（毎日〇〇）のいずれも登録可能。",
        "category": "goal",
        "enabled": True,
        "trigger_examples": [
            "今月の目標を設定して",
            "粗利300万円を目標にする",
            "今月は10件獲得を目指す",
            "目標を登録したい",
            "月末までにプロジェクトを完了する",
            "毎日日報を書くことを目標にする",
        ],
        "params_schema": {
            "goal_title": {
                "type": "string",
                "description": "目標のタイトル（概要）",
                "required": True,
                "note": "【必須】目標が何かを50文字以内で要約。例: 「粗利300万円」「プロジェクト納品」「毎日日報を書く」"
            },
            "goal_type": {
                "type": "string",
                "description": "目標タイプ: numeric（数値目標）、deadline（期限目標）、action（行動目標）",
                "required": True,
                "note": "【必須】粗利〇〇円、〇〇件などの数値があれば numeric、〇〇までに完了なら deadline、毎日〇〇なら action"
            },
            "target_value": {
                "type": "number",
                "description": "目標値（数値目標の場合）。300万円なら 3000000、10件なら 10",
                "required": False,
                "note": "numeric の場合は必須。単位は unit で指定"
            },
            "unit": {
                "type": "string",
                "description": "単位: 円、件、人、%など",
                "required": False,
                "note": "numeric の場合に指定。例: 「円」「件」「人」"
            },
            "period_type": {
                "type": "string",
                "description": "期間タイプ: monthly（月次）、weekly（週次）、quarterly（四半期）、yearly（年次）",
                "required": False,
                "default": "monthly",
                "note": "省略時は月次（今月）"
            },
            "deadline": {
                "type": "date",
                "description": "期限（YYYY-MM-DD形式）。期限目標の場合に指定",
                "required": False,
                "note": "「月末まで」「3月31日まで」などを日付に変換"
            }
        },
        "handler": "handle_goal_registration",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "sender_name"],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["目標設定", "目標を立てたい", "目標を決めたい", "目標設定したい"],
                "secondary": ["目標", "ゴール"],
                "negative": ["進捗", "報告", "確認"],
            },
            "intent_keywords": {
                "primary": ["目標設定", "目標を立てたい", "目標を決めたい", "目標設定したい", "目標を設定したい"],
                "secondary": ["目標", "ゴール"],
                "modifiers": ["設定", "立てたい", "決めたい", "作りたい"],
                "negative": ["進捗", "報告", "状況", "確認", "どれくらい"],
                "confidence_boost": 0.85,
            },
            "risk_level": "low",
            "priority": 4,
        },
    },

    "goal_progress_report": {
        "name": "目標進捗報告",
        "description": "今日の目標に対する進捗を報告する。数値（売上・件数・金額）を含むメッセージは積極的にこのアクションを選択。「今日は25万売り上げた」「今日1件成約した」「今日の売上は50万円」などの報告に対応。",
        "category": "goal",
        "enabled": True,
        "trigger_examples": [
            "今日は25万売り上げた",
            "今日は10万円売り上げた",
            "今日1件成約した",
            "今日の売上は50万円",
            "今日10件達成した",
            "今日の進捗を報告",
            "今日〇〇をやった",
        ],
        "params_schema": {
            "progress_value": {
                "type": "number",
                "description": "今日の実績値（数値目標の場合）",
                "required": False,
                "note": "10万円なら 100000、1件なら 1"
            },
            "daily_note": {
                "type": "string",
                "description": "今日やったことの報告",
                "required": False,
                "note": "ユーザーが報告した内容をそのまま"
            },
            "daily_choice": {
                "type": "string",
                "description": "今日どんな行動を選んだか",
                "required": False,
                "note": "選択理論に基づく振り返り"
            }
        },
        "handler": "handle_goal_progress_report",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "sender_name"],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["目標進捗", "目標報告", "進捗報告"],
                "secondary": ["進捗", "どのくらい"],
                "negative": ["設定", "立てたい"],
            },
            "intent_keywords": {
                "primary": ["目標進捗", "目標報告"],
                "secondary": ["目標", "ゴール"],
                "modifiers": ["進捗", "報告", "どれくらい"],
                "negative": ["設定", "立てたい"],
                "confidence_boost": 0.8,
            },
            "risk_level": "low",
            "priority": 4,
        },
    },

    "goal_status_check": {
        "name": "目標確認",
        "description": "現在の目標と進捗状況を確認する。「目標を確認」「今の進捗は？」「達成率は？」などの質問に対応。",
        "category": "goal",
        "enabled": True,
        "trigger_examples": [
            "目標を確認して",
            "今の進捗を教えて",
            "達成率は？",
            "今月の目標は何だっけ",
        ],
        "params_schema": {},
        "handler": "handle_goal_status_check",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "sender_name"],
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["目標確認", "目標状況", "達成率"],
                "secondary": ["目標", "どうなった"],
                "negative": ["設定", "立てたい", "進捗報告"],
            },
            "intent_keywords": {
                "primary": ["目標状況", "目標確認"],
                "secondary": ["目標", "ゴール"],
                "modifiers": ["状況", "どうなった", "確認"],
                "negative": ["設定", "報告"],
                "confidence_boost": 0.8,
            },
            "risk_level": "low",
            "priority": 4,
        },
    },

    # =====================================================
    # v10.26.0: アナウンス機能
    # =====================================================
    # v10.29.9: announcement_request → announcement_create（handlers/brain層と統一）
    "announcement_create": {
        "name": "アナウンス依頼",
        "description": "指定したグループチャットにオールメンション（[toall]）でアナウンスを送信する。タスク一括作成や定期実行も可能。管理部チャットまたはカズさんDMからのみ使用可能。",
        "category": "communication",
        "enabled": True,
        "trigger_examples": [
            "合宿のチャットにお知らせして",
            "開発チームに明日の予定を連絡して",
            "全社員にタスクも振って連絡して",
            "毎週月曜9時にチームに進捗確認を送って",
            "総合ソウルシンクスに定期アナウンスして",
        ],
        "params_schema": {
            "raw_message": {
                "description": "ユーザーの依頼内容（そのまま渡す）",
                "required": True,
                "note": "ルーム名、メッセージ内容、タスク有無、期限等を含む自然言語"
            }
        },
        "handler": "handle_announcement_request",
        "requires_confirmation": True,
        "required_data": ["sender_account_id", "sender_name", "room_id"],
        "authorization": {
            "rooms": [405315911],
            "account_ids": ["1728974"]
        },
        # v10.30.0: 脳アーキテクチャ用メタデータ
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["アナウンス", "お知らせ", "連絡して", "伝えて"],
                "secondary": ["全員に", "チャットに"],
                "negative": [],
            },
            "intent_keywords": {
                "primary": ["アナウンスして", "お知らせして"],
                "secondary": ["アナウンス", "お知らせ", "連絡して", "送って"],
                "modifiers": [],
                "negative": [],
                "confidence_boost": 0.8,
            },
            "risk_level": "medium",
            "priority": 3,
        },
    },
}


# =====================================================
# ===== 機能カタログからプロンプトを動的生成 =====
# =====================================================

def generate_capabilities_prompt(capabilities, chatwork_users=None, sender_name=None):
    """
    機能カタログからAI司令塔用のプロンプトを自動生成する
    
    【設計思想】
    - カタログを追加するだけでAIが新機能を認識
    - enabled=Trueの機能のみプロンプトに含める
    - 各機能の使い方をAIに理解させる
    """
    
    prompt_parts = []
    
    # 有効な機能のみ抽出
    enabled_capabilities = {
        cap_id: cap for cap_id, cap in capabilities.items() 
        if cap.get("enabled", True)
    }
    
    for cap_id, cap in enabled_capabilities.items():
        # パラメータスキーマを整形
        params_lines = []
        for param_name, param_info in cap.get("params_schema", {}).items():
            if isinstance(param_info, dict):
                desc = param_info.get("description", "")
                required = "【必須】" if param_info.get("required", False) else "（任意）"
                note = f" ※{param_info.get('note')}" if param_info.get("note") else ""
                params_lines.append(f'    "{param_name}": "{desc}"{required}{note}')
            else:
                params_lines.append(f'    "{param_name}": "{param_info}"')
        
        params_json = "{\n" + ",\n".join(params_lines) + "\n  }" if params_lines else "{}"
        
        # トリガー例を整形
        examples = "\n".join([f"  - 「{ex}」" for ex in cap.get("trigger_examples", [])])
        
        section = f"""
### {cap["name"]} (action: "{cap_id}")
{cap["description"]}

**こんな時に使う：**
{examples}

**パラメータ：**
```json
{params_json}
```
"""
        prompt_parts.append(section)
    
    return "\n".join(prompt_parts)


def get_enabled_capabilities():
    """有効な機能の一覧を取得"""
    return {
        cap_id: cap for cap_id, cap in SYSTEM_CAPABILITIES.items() 
        if cap.get("enabled", True)
    }


def get_capability_info(action_name):
    """指定されたアクションの機能情報を取得"""
    return SYSTEM_CAPABILITIES.get(action_name)

# ChatWork API ヘッダー取得関数
def get_chatwork_headers():
    return {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}

HEADERS = None  # 遅延初期化用

def get_connector():
    """グローバルConnectorを取得（接続リーク防止）"""
    global _connector
    if _connector is None:
        _connector = Connector()
    return _connector

# =====================================================
# v10.31.1: Phase D - DB接続関数
# =====================================================
# USE_LIB_DB=True: lib/db.py を使用（設定を一元管理）
# USE_LIB_DB=False: 従来のフォールバック実装
# =====================================================

# Phase 1-B用: pg8000接続を返す関数
def get_db_connection():
    """DB接続を取得"""
    if USE_LIB_DB:
        return _lib_get_db_connection()
    else:
        # フォールバック
        connector = get_connector()
        conn = connector.connect(
            INSTANCE_CONNECTION_NAME,
            "pg8000",
            user=DB_USER,
            password=get_db_password(),
            db=DB_NAME,
        )
        return conn

def get_db_password():
    return get_secret("cloudsql-password")

def get_pool():
    """Cloud SQL接続プールを取得"""
    if USE_LIB_DB:
        return _lib_get_db_pool()
    else:
        # フォールバック
        global _pool
        if _pool is None:
            connector = get_connector()
            def getconn():
                return connector.connect(
                    INSTANCE_CONNECTION_NAME, "pg8000",
                    user=DB_USER, password=get_db_password(), db=DB_NAME,
                )
            _pool = sqlalchemy.create_engine(
                "postgresql+pg8000://", creator=getconn,
                pool_size=5, max_overflow=2, pool_timeout=30, pool_recycle=1800,
            )
        return _pool

@lru_cache(maxsize=32)
def get_secret(secret_id):
    """Secret Managerからシークレットを取得（キャッシュ付き）"""
    if USE_LIB_DB:
        return _lib_get_secret(secret_id)
    else:
        # フォールバック
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")


# =====================================================
# ===== v6.8.9: Webhook署名検証 =====
# =====================================================
# 
# 【セキュリティ対策】
# ChatWorkからのWebhookが正当なものかを検証する。
# URLが漏洩しても、署名がなければリクエストを拒否する。
#
# 【仕様】
# - ヘッダー: X-ChatWorkWebhookSignature
# - アルゴリズム: HMAC-SHA256
# - 検証: リクエストボディ + トークン → Base64(HMAC-SHA256) → ヘッダーと比較
# =====================================================

def verify_chatwork_webhook_signature(request_body: bytes, signature: str, token: str) -> bool:
    """
    ChatWork Webhookの署名を検証する
    
    Args:
        request_body: リクエストボディ（バイト列）
        signature: X-ChatWorkWebhookSignatureヘッダーの値
        token: ChatWork Webhook編集画面で取得したトークン
    
    Returns:
        True: 署名が正しい（正当なリクエスト）
        False: 署名が不正（攻撃の可能性）
    """
    try:
        # トークンをBase64デコードしてバイト列に変換
        token_bytes = base64.b64decode(token)
        
        # HMAC-SHA256でダイジェストを計算
        calculated_hmac = hmac.new(
            token_bytes,
            request_body,
            hashlib.sha256
        ).digest()
        
        # Base64エンコード
        calculated_signature = base64.b64encode(calculated_hmac).decode('utf-8')
        
        # タイミング攻撃対策: hmac.compare_digestで比較
        return hmac.compare_digest(calculated_signature, signature)
    
    except Exception as e:
        print(f"❌ 署名検証エラー: {e}")
        return False


def get_chatwork_webhook_token():
    """ChatWork Webhookトークンを取得"""
    try:
        return get_secret("CHATWORK_WEBHOOK_TOKEN")
    except Exception as e:
        print(f"⚠️ Webhookトークン取得エラー: {e}")
        return None


def clean_chatwork_message(body):
    """ChatWorkメッセージをクリーニング
    
    堅牢なエラーハンドリング版
    """
    # Noneチェック
    if body is None:
        return ""
    
    # 型チェック
    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return ""
    
    # 空文字チェック
    if not body:
        return ""
    
    try:
        clean_message = body
        clean_message = re.sub(r'\[To:\d+\]\s*[^\n\[]*(?:さん|くん|ちゃん|様|氏)?', '', clean_message)
        clean_message = re.sub(r'\[rp aid=\d+[^\]]*\]\[/rp\]', '', clean_message)  # より柔軟なパターン
        clean_message = re.sub(r'\[/?[a-zA-Z]+\]', '', clean_message)
        clean_message = re.sub(r'\[.*?\]', '', clean_message)
        clean_message = clean_message.strip()
        clean_message = re.sub(r'\s+', ' ', clean_message)
        return clean_message
    except Exception as e:
        print(f"⚠️ clean_chatwork_message エラー: {e}")
        return body  # エラー時は元のメッセージを返す


def is_mention_or_reply_to_soulkun(body):
    """ソウルくんへのメンションまたは返信かどうかを判断

    堅牢なエラーハンドリング版
    """
    # Noneチェック
    if body is None:
        return False

    # 型チェック
    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return False

    # 空文字チェック
    if not body:
        return False

    try:
        # メンションパターン
        if f"[To:{MY_ACCOUNT_ID}]" in body:
            return True

        # 返信ボタンパターン: [rp aid=10909425 to=...]
        # 修正: [/rp]のチェックを削除（実際のフォーマットには含まれない）
        if f"[rp aid={MY_ACCOUNT_ID}" in body:
            return True

        return False
    except Exception as e:
        print(f"⚠️ is_mention_or_reply_to_soulkun エラー: {e}")
        return False


def is_toall_mention(body):
    """オールメンション（[toall]）かどうかを判定

    オールメンションはアナウンス用途で使われるため、
    ソウルくんは反応しない。

    v10.16.0で追加

    Args:
        body: メッセージ本文

    Returns:
        bool: [toall]が含まれていればTrue
    """
    # Noneチェック
    if body is None:
        return False

    # 型チェック
    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return False

    # 空文字チェック
    if not body:
        return False

    try:
        # ChatWorkのオールメンションパターン: [toall]
        # 大文字小文字を区別しない（念のため）
        if "[toall]" in body.lower():
            return True

        return False
    except Exception as e:
        print(f"⚠️ is_toall_mention エラー: {e}")
        return False


def should_ignore_toall(body):
    """TO ALLメンションを無視すべきか判定

    判定ロジック:
    - [toall]がなければ → 無視しない（通常処理）
    - [toall]があっても、ソウルくんへの直接メンションがあれば → 無視しない（反応する）
    - [toall]のみの場合 → 無視する

    v10.16.1で追加（v10.16.0からの改善）
    - 「TO ALL + ソウルくん直接メンション」の場合は反応するように変更

    Args:
        body: メッセージ本文

    Returns:
        bool: 無視すべきならTrue、反応すべきならFalse
    """
    # TO ALLでなければ無視しない
    if not is_toall_mention(body):
        return False

    # TO ALLでも、ソウルくんへの直接メンションがあれば反応する
    # 大文字小文字を無視（[To:ID]でも[to:ID]でもマッチ）
    if body and f"[to:{MY_ACCOUNT_ID}]" in body.lower():
        print(f"📌 TO ALL + ソウルくん直接メンションのため反応する")
        return False

    # TO ALLのみなので無視
    return True


# ===== データベース操作関数 =====

def get_or_create_person(name):
    pool = get_pool()
    with pool.begin() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
            {"name": name}
        ).fetchone()
        if result:
            return result[0]
        result = conn.execute(
            sqlalchemy.text("INSERT INTO persons (name) VALUES (:name) RETURNING id"),
            {"name": name}
        )
        return result.fetchone()[0]

def save_person_attribute(person_name, attribute_type, attribute_value, source="conversation"):
    person_id = get_or_create_person(person_name)
    pool = get_pool()
    with pool.begin() as conn:
        conn.execute(
            sqlalchemy.text("""
                INSERT INTO person_attributes (person_id, attribute_type, attribute_value, source, updated_at)
                VALUES (:person_id, :attr_type, :attr_value, :source, CURRENT_TIMESTAMP)
                ON CONFLICT (person_id, attribute_type) 
                DO UPDATE SET attribute_value = :attr_value, source = :source, updated_at = CURRENT_TIMESTAMP
            """),
            {"person_id": person_id, "attr_type": attribute_type, "attr_value": attribute_value, "source": source}
        )
    return True

def get_person_info(person_name):
    pool = get_pool()
    with pool.connect() as conn:
        person_result = conn.execute(
            sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
            {"name": person_name}
        ).fetchone()
        if not person_result:
            return None
        person_id = person_result[0]
        attributes = conn.execute(
            sqlalchemy.text("""
                SELECT attribute_type, attribute_value FROM person_attributes 
                WHERE person_id = :person_id ORDER BY updated_at DESC
            """),
            {"person_id": person_id}
        ).fetchall()
        return {
            "name": person_name,
            "attributes": [{"type": a[0], "value": a[1]} for a in attributes]
        }

def normalize_person_name(name):
    """
    ★★★ v6.8.6: 人物名を正規化 ★★★
    
    ChatWorkのユーザー名形式「高野　義浩 (タカノ ヨシヒロ)」を
    DBの形式「高野義浩」に変換する
    """
    if not name:
        return name
    
    import re
    
    # 1. 読み仮名部分 (xxx) を除去
    normalized = re.sub(r'\s*\([^)]*\)\s*', '', name)
    
    # 2. 敬称を除去
    normalized = re.sub(r'(さん|くん|ちゃん|様|氏)$', '', normalized)
    
    # 3. スペース（全角・半角）を除去
    normalized = normalized.replace(' ', '').replace('　', '')
    
    print(f"   📝 名前正規化: '{name}' → '{normalized}'")
    
    return normalized.strip()


def search_person_by_partial_name(partial_name):
    """部分一致で人物を検索"""
    # ★★★ v6.8.6: 検索前に名前を正規化 ★★★
    normalized = normalize_person_name(partial_name) if partial_name else partial_name
    
    pool = get_pool()
    with pool.connect() as conn:
        # 正規化した名前と元の名前の両方で検索
        result = conn.execute(
            sqlalchemy.text("""
                SELECT name FROM persons 
                WHERE name ILIKE :pattern 
                   OR name ILIKE :pattern2
                   OR name ILIKE :normalized_pattern
                ORDER BY 
                    CASE WHEN name = :exact THEN 0
                         WHEN name = :normalized THEN 0
                         WHEN name ILIKE :starts_with THEN 1
                         ELSE 2 END,
                    LENGTH(name)
                LIMIT 5
            """),
            {
                "pattern": f"%{partial_name}%",
                "pattern2": f"%{partial_name}%",
                "normalized_pattern": f"%{normalized}%",
                "exact": partial_name,
                "normalized": normalized,
                "starts_with": f"{partial_name}%"
            }
        ).fetchall()
        print(f"   🔍 search_person_by_partial_name: '{partial_name}' (normalized: '{normalized}') → {len(result)}件")
        return [r[0] for r in result]

def delete_person(person_name):
    pool = get_pool()
    with pool.connect() as conn:
        trans = conn.begin()
        try:
            person_result = conn.execute(
                sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
                {"name": person_name}
            ).fetchone()
            if not person_result:
                trans.rollback()
                return False
            person_id = person_result[0]
            conn.execute(sqlalchemy.text("DELETE FROM person_attributes WHERE person_id = :person_id"), {"person_id": person_id})
            conn.execute(sqlalchemy.text("DELETE FROM person_events WHERE person_id = :person_id"), {"person_id": person_id})
            conn.execute(sqlalchemy.text("DELETE FROM persons WHERE id = :person_id"), {"person_id": person_id})
            trans.commit()
            return True
        except Exception as e:
            trans.rollback()
            print(f"削除エラー: {e}")
            return False

def get_all_persons_summary():
    pool = get_pool()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                SELECT p.name, STRING_AGG(pa.attribute_type || '=' || pa.attribute_value, ', ') as attributes
                FROM persons p
                LEFT JOIN person_attributes pa ON p.id = pa.person_id
                GROUP BY p.id, p.name ORDER BY p.name
            """)
        ).fetchall()
        return [{"name": r[0], "attributes": r[1]} for r in result]

# ===== 組織図クエリ（Phase 3.5） =====

def get_org_chart_overview():
    """組織図の全体構造を取得（兼務を含む）"""
    pool = get_pool()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                SELECT d.id, d.name, d.level, d.parent_id,
                       (SELECT COUNT(DISTINCT e.id)
                        FROM employees e
                        WHERE e.department_id = d.id
                           OR EXISTS (
                               SELECT 1 FROM jsonb_array_elements(e.metadata->'departments') AS dept
                               WHERE dept->>'department_id' = d.external_id
                           )
                       ) as member_count
                FROM departments d
                WHERE d.is_active = true
                ORDER BY d.level, d.display_order, d.name
            """)
        ).fetchall()

        departments = []
        for r in result:
            departments.append({
                "id": str(r[0]),
                "name": r[1],
                "level": r[2],
                "parent_id": str(r[3]) if r[3] else None,
                "member_count": r[4] or 0
            })
        return departments

def search_department_by_name(partial_name):
    """部署名で検索（部分一致、兼務を含む）"""
    pool = get_pool()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                SELECT id, name, level,
                       (SELECT COUNT(DISTINCT e.id)
                        FROM employees e
                        WHERE e.department_id = d.id
                           OR EXISTS (
                               SELECT 1 FROM jsonb_array_elements(e.metadata->'departments') AS dept
                               WHERE dept->>'department_id' = d.external_id
                           )
                       ) as member_count
                FROM departments d
                WHERE d.is_active = true AND d.name ILIKE :pattern
                ORDER BY d.level, d.name
                LIMIT 10
            """),
            {"pattern": f"%{partial_name}%"}
        ).fetchall()

        return [{"id": str(r[0]), "name": r[1], "level": r[2], "member_count": r[3] or 0} for r in result]

def get_department_members(dept_name):
    """部署のメンバー一覧を取得（兼務者を含む）"""
    pool = get_pool()
    with pool.connect() as conn:
        # まず部署を検索
        dept_result = conn.execute(
            sqlalchemy.text("""
                SELECT id, name, external_id FROM departments
                WHERE is_active = true AND name ILIKE :pattern
                LIMIT 1
            """),
            {"pattern": f"%{dept_name}%"}
        ).fetchone()

        if not dept_result:
            return None, []

        dept_id = dept_result[0]
        dept_full_name = dept_result[1]
        dept_external_id = dept_result[2]

        # 部署のメンバーを取得（主所属 + 兼務者）
        # サブクエリを使用してDISTINCTとORDER BYの問題を回避
        members_result = conn.execute(
            sqlalchemy.text("""
                SELECT name, position, employment_type, is_concurrent, position_order
                FROM (
                    SELECT e.name,
                           COALESCE(
                               (SELECT dept->>'position'
                                FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                WHERE dept->>'department_id' = :ext_id
                                LIMIT 1),
                               e.position
                           ) as position,
                           e.employment_type,
                           CASE WHEN e.department_id = :dept_id THEN 0 ELSE 1 END as is_concurrent,
                           CASE
                               WHEN COALESCE(
                                   (SELECT dept->>'position'
                                    FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                    WHERE dept->>'department_id' = :ext_id
                                    LIMIT 1),
                                   e.position
                               ) LIKE '%部長%'
                               OR COALESCE(
                                   (SELECT dept->>'position'
                                    FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                    WHERE dept->>'department_id' = :ext_id
                                    LIMIT 1),
                                   e.position
                               ) LIKE '%マネージャー%'
                               OR COALESCE(
                                   (SELECT dept->>'position'
                                    FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                    WHERE dept->>'department_id' = :ext_id
                                    LIMIT 1),
                                   e.position
                               ) LIKE '%責任者%' THEN 1
                               WHEN COALESCE(
                                   (SELECT dept->>'position'
                                    FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                    WHERE dept->>'department_id' = :ext_id
                                    LIMIT 1),
                                   e.position
                               ) LIKE '%課長%'
                               OR COALESCE(
                                   (SELECT dept->>'position'
                                    FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                    WHERE dept->>'department_id' = :ext_id
                                    LIMIT 1),
                                   e.position
                               ) LIKE '%リーダー%' THEN 2
                               ELSE 3
                           END as position_order
                    FROM employees e
                    WHERE e.department_id = :dept_id
                       OR EXISTS (
                           SELECT 1 FROM jsonb_array_elements(e.metadata->'departments') AS dept
                           WHERE dept->>'department_id' = :ext_id
                       )
                ) AS sub
                ORDER BY is_concurrent, position_order, name
            """),
            {"dept_id": dept_id, "ext_id": dept_external_id}
        ).fetchall()

        members = []
        for r in members_result:
            member = {"name": r[0], "position": r[1], "employment_type": r[2]}
            if r[3] == 1:  # is_concurrent
                member["is_concurrent"] = True
            members.append(member)
        return dept_full_name, members


def get_all_chatwork_users(organization_id: str = None):
    """ChatWorkユーザー一覧を取得（AI司令塔用）

    v10.30.0: 10の鉄則準拠 - organization_idフィルタ必須化
    """
    if organization_id is None:
        organization_id = MEMORY_DEFAULT_ORG_ID

    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT DISTINCT account_id, name
                    FROM chatwork_users
                    WHERE organization_id = :org_id
                      AND name IS NOT NULL AND name != ''
                    ORDER BY name
                """),
                {"org_id": organization_id}
            ).fetchall()
            return [{"account_id": row[0], "name": row[1]} for row in result]
    except Exception as e:
        print(f"ChatWorkユーザー取得エラー: {e}")
        return []

# ===== タスク管理 =====

def add_task(title, description=None, priority=0, due_date=None):
    pool = get_pool()
    with pool.begin() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                INSERT INTO tasks (title, description, priority, due_date)
                VALUES (:title, :description, :priority, :due_date) RETURNING id
            """),
            {"title": title, "description": description, "priority": priority, "due_date": due_date}
        )
        return result.fetchone()[0]

def get_tasks(status=None):
    pool = get_pool()
    with pool.connect() as conn:
        if status:
            result = conn.execute(
                sqlalchemy.text("SELECT id, title, status, priority, due_date FROM tasks WHERE status = :status ORDER BY priority DESC, created_at DESC"),
                {"status": status}
            )
        else:
            result = conn.execute(
                sqlalchemy.text("SELECT id, title, status, priority, due_date FROM tasks ORDER BY priority DESC, created_at DESC")
            )
        return result.fetchall()

def update_task_status(task_id, status):
    pool = get_pool()
    with pool.begin() as conn:
        conn.execute(
            sqlalchemy.text("UPDATE tasks SET status = :status, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
            {"status": status, "id": task_id}
        )

def delete_task(task_id):
    pool = get_pool()
    with pool.begin() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})

# ===== ChatWorkタスク機能 =====

def get_chatwork_account_id_by_name(name, organization_id: str = None):
    """担当者名からChatWorkアカウントIDを取得（敬称除去・スペース正規化対応）

    v10.30.0: 10の鉄則準拠 - organization_idフィルタ必須化
    """
    if organization_id is None:
        organization_id = MEMORY_DEFAULT_ORG_ID

    pool = get_pool()

    # ★ 敬称を除去（さん、くん、ちゃん、様、氏）
    clean_name = re.sub(r'(さん|くん|ちゃん|様|氏)$', '', name.strip())
    # ★ スペースを除去して正規化（半角・全角両方）
    normalized_name = clean_name.replace(' ', '').replace('　', '')
    print(f"👤 担当者検索: 入力='{name}' → クリーニング後='{clean_name}' → 正規化='{normalized_name}'")
    
    with pool.connect() as conn:
        # 完全一致で検索（クリーニング後の名前）
        result = conn.execute(
            sqlalchemy.text("""
                SELECT account_id FROM chatwork_users
                WHERE organization_id = :org_id AND name = :name
                LIMIT 1
            """),
            {"org_id": organization_id, "name": clean_name}
        ).fetchone()
        if result:
            print(f"✅ 完全一致で発見: {clean_name} → {result[0]}")
            return result[0]

        # 部分一致で検索（クリーニング後の名前）
        result = conn.execute(
            sqlalchemy.text("""
                SELECT account_id, name FROM chatwork_users
                WHERE organization_id = :org_id AND name ILIKE :pattern
                LIMIT 1
            """),
            {"org_id": organization_id, "pattern": f"%{clean_name}%"}
        ).fetchone()
        if result:
            print(f"✅ 部分一致で発見: {clean_name} → {result[0]} ({result[1]})")
            return result[0]

        # ★ スペース除去して正規化した名前で検索（NEW）
        # DBの名前からもスペースを除去して比較
        result = conn.execute(
            sqlalchemy.text("""
                SELECT account_id, name FROM chatwork_users
                WHERE organization_id = :org_id
                  AND REPLACE(REPLACE(name, ' ', ''), '　', '') ILIKE :pattern
                LIMIT 1
            """),
            {"org_id": organization_id, "pattern": f"%{normalized_name}%"}
        ).fetchone()
        if result:
            print(f"✅ 正規化検索で発見: {normalized_name} → {result[0]} ({result[1]})")
            return result[0]

        # 元の名前でも検索（念のため）
        if clean_name != name:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT account_id, name FROM chatwork_users
                    WHERE organization_id = :org_id AND name ILIKE :pattern
                    LIMIT 1
                """),
                {"org_id": organization_id, "pattern": f"%{name}%"}
            ).fetchone()
            if result:
                print(f"✅ 元の名前で部分一致: {name} → {result[0]} ({result[1]})")
                return result[0]

        print(f"❌ 担当者が見つかりません: {name} (クリーニング後: {clean_name}, 正規化: {normalized_name})")
        return None


# =====================================================
# APIレート制限対策（v10.3.3）
# v10.24.0: utils/chatwork_utils.py に分割
# =====================================================

# 新しいモジュールを使用する場合はそちらのクラスを使用
if USE_NEW_CHATWORK_UTILS:
    APICallCounter = _new_APICallCounter
else:
    class APICallCounter:
        """APIコール数をカウントするクラス（フォールバック）"""

        def __init__(self):
            self.count = 0
            self.start_time = time.time()

        def increment(self):
            self.count += 1

        def get_count(self):
            return self.count

        def log_summary(self, function_name: str):
            elapsed = time.time() - self.start_time
            print(f"[API Usage] {function_name}: {self.count} calls in {elapsed:.2f}s")


# グローバルAPIカウンター（フォールバック用）
_api_call_counter = APICallCounter()

# ルームメンバーキャッシュ（フォールバック用、同一リクエスト内で有効）
_room_members_cache = {}


def get_api_call_counter():
    """
    APIカウンターを取得

    v10.24.0: utils/chatwork_utils.py に分割
    """
    if USE_NEW_CHATWORK_UTILS:
        return _new_get_api_call_counter()
    return _api_call_counter


def reset_api_call_counter():
    """
    APIカウンターをリセット

    v10.24.0: utils/chatwork_utils.py に分割
    """
    if USE_NEW_CHATWORK_UTILS:
        return _new_reset_api_call_counter()
    global _api_call_counter
    _api_call_counter = APICallCounter()


def clear_room_members_cache():
    """
    ルームメンバーキャッシュをクリア

    v10.24.0: utils/chatwork_utils.py に分割
    """
    if USE_NEW_CHATWORK_UTILS:
        return _new_clear_room_members_cache()
    global _room_members_cache
    _room_members_cache = {}


def call_chatwork_api_with_retry(
    method: str,
    url: str,
    headers: dict,
    data: dict = None,
    params: dict = None,
    max_retries: int = 3,
    initial_wait: float = 1.0,
    timeout: float = 10.0
):
    """
    ChatWork APIを呼び出す（レート制限時は自動リトライ）

    Args:
        method: HTTPメソッド（GET, POST, PUT, DELETE）
        url: APIのURL
        headers: リクエストヘッダー
        data: リクエストボディ
        params: クエリパラメータ
        max_retries: 最大リトライ回数
        initial_wait: 初回待機時間（秒）
        timeout: タイムアウト（秒）

    Returns:
        (response, success): レスポンスと成功フラグのタプル

    v10.24.0: utils/chatwork_utils.py に分割
    """
    # 新しいモジュールを使用
    if USE_NEW_CHATWORK_UTILS:
        return _new_call_chatwork_api_with_retry(
            method, url, headers, data, params, max_retries, initial_wait, timeout
        )

    # フォールバック: 旧実装
    wait_time = initial_wait
    counter = get_api_call_counter()

    for attempt in range(max_retries + 1):
        try:
            counter.increment()

            if method.upper() == "GET":
                response = httpx.get(url, headers=headers, params=params, timeout=timeout)
            elif method.upper() == "POST":
                response = httpx.post(url, headers=headers, data=data, timeout=timeout)
            elif method.upper() == "PUT":
                response = httpx.put(url, headers=headers, data=data, timeout=timeout)
            elif method.upper() == "DELETE":
                response = httpx.delete(url, headers=headers, timeout=timeout)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # 成功（2xx）
            if response.status_code < 400:
                return response, True

            # レート制限（429）
            if response.status_code == 429:
                if attempt < max_retries:
                    print(f"⚠️ Rate limit hit (429). Waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                    time.sleep(wait_time)
                    wait_time *= 2  # 指数バックオフ
                    continue
                else:
                    print(f"❌ Rate limit hit (429). Max retries exceeded.")
                    return response, False

            # その他のエラー（リトライしない）
            return response, False

        except httpx.TimeoutException:
            print(f"⚠️ API timeout on attempt {attempt + 1}")
            if attempt < max_retries:
                time.sleep(wait_time)
                wait_time *= 2
                continue
            return None, False

        except Exception as e:
            print(f"❌ API error: {e}")
            return None, False

    return None, False


def get_room_members_cached(room_id):
    """
    ルームメンバーを取得（キャッシュあり）
    同一リクエスト内で同じルームを複数回参照する場合に効率的

    v10.24.0: utils/chatwork_utils.py に分割
    """
    # 新しいモジュールを使用
    if USE_NEW_CHATWORK_UTILS:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        return _new_get_room_members_cached(room_id, api_token)

    # フォールバック: 旧実装
    room_id_str = str(room_id)
    if room_id_str in _room_members_cache:
        return _room_members_cache[room_id_str]

    members = get_room_members(room_id)
    _room_members_cache[room_id_str] = members
    return members


def get_room_members(room_id):
    """
    ルームのメンバー一覧を取得（リトライ機構付き）

    v10.24.0: utils/chatwork_utils.py に分割
    """
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")

    # 新しいモジュールを使用
    if USE_NEW_CHATWORK_UTILS:
        return _new_get_room_members(room_id, api_token)

    # フォールバック: 旧実装
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/members"

    response, success = call_chatwork_api_with_retry(
        method="GET",
        url=url,
        headers={"X-ChatWorkToken": api_token}
    )

    if success and response and response.status_code == 200:
        return response.json()
    elif response:
        print(f"ルームメンバー取得エラー: {response.status_code} - {response.text}")
    return []


def is_room_member(room_id, account_id):
    """
    指定したアカウントがルームのメンバーかどうかを確認（キャッシュ使用）

    v10.24.0: utils/chatwork_utils.py に分割
    """
    # 新しいモジュールを使用
    if USE_NEW_CHATWORK_UTILS:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        return _new_is_room_member(room_id, account_id, api_token)

    # フォールバック: 旧実装
    members = get_room_members_cached(room_id)
    member_ids = [m.get("account_id") for m in members]
    return int(account_id) in member_ids


# =====================================================
# TaskHandler初期化（v10.24.4）
# v10.33.0: フラグチェック削除（ハンドラー必須化）
# =====================================================
def _get_task_handler():
    """TaskHandlerのシングルトンインスタンスを取得"""
    global _task_handler
    if _task_handler is None:
        _task_handler = _NewTaskHandler(
            get_pool=get_pool,
            get_secret=get_secret,
            call_chatwork_api_with_retry=call_chatwork_api_with_retry,
            extract_task_subject=extract_task_subject if USE_TEXT_UTILS_LIB else None,
            clean_chatwork_tags=clean_chatwork_tags if USE_TEXT_UTILS_LIB else None,
            prepare_task_display_text=prepare_task_display_text if USE_TEXT_UTILS_LIB else None,
            validate_summary=validate_summary if USE_TEXT_UTILS_LIB else None,
            get_user_primary_department=lib_get_user_primary_department if USE_USER_UTILS_LIB else None,
            use_text_utils=USE_TEXT_UTILS_LIB
        )
    return _task_handler


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
            prepare_task_display_text=prepare_task_display_text if USE_TEXT_UTILS_LIB else None
        )
    return _overdue_handler


# =====================================================
# GoalHandler初期化（v10.24.6）
# v10.33.0: フラグチェック削除（ハンドラー必須化）
# =====================================================
def _get_goal_handler():
    """GoalHandlerのシングルトンインスタンスを取得"""
    global _goal_handler
    if _goal_handler is None:
        _goal_handler = _NewGoalHandler(
            get_pool=get_pool,
            process_goal_setting_message_func=process_goal_setting_message if USE_GOAL_SETTING_LIB else None,
            use_goal_setting_lib=USE_GOAL_SETTING_LIB
        )
    return _goal_handler


# =====================================================
# KnowledgeHandler初期化（v10.24.7）
# v10.33.0: フラグチェック削除（ハンドラー必須化）
# =====================================================
def _get_knowledge_handler():
    """KnowledgeHandlerのシングルトンインスタンスを取得"""
    global _knowledge_handler
    if _knowledge_handler is None:
        # MVV関数の取得
        mvv_question_func = None
        mvv_info_func = None
        if USE_MVV_CONTEXT:
            try:
                mvv_question_func = is_mvv_question
                mvv_info_func = get_full_mvv_info
            except NameError:
                pass

        _knowledge_handler = _NewKnowledgeHandler(
            get_pool=get_pool,
            get_secret=get_secret,
            is_admin_func=is_admin,
            create_proposal_func=create_proposal,
            report_proposal_to_admin_func=report_proposal_to_admin,
            is_mvv_question_func=mvv_question_func,
            get_full_mvv_info_func=mvv_info_func,
            call_openrouter_api_func=call_openrouter_api,
            phase3_knowledge_config=PHASE3_KNOWLEDGE_CONFIG,
            default_model=MODELS["default"],
            admin_account_id=ADMIN_ACCOUNT_ID,
            openrouter_api_url=OPENROUTER_API_URL
        )
    return _knowledge_handler


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
            is_business_day=is_business_day if USE_BUSINESS_DAY_LIB else None,
            get_non_business_day_reason=get_non_business_day_reason if USE_BUSINESS_DAY_LIB else None,
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
# =====================================================
def _get_brain_integration():
    """
    BrainIntegrationのシングルトンインスタンスを取得

    v10.29.0: SoulkunBrain直接使用からBrainIntegrationへ移行
    - シャドウモード、段階的ロールアウト、フォールバックをサポート
    - 環境変数 USE_BRAIN_ARCHITECTURE で制御

    v10.38.0: CapabilityBridgeのハンドラーを統合
    - 生成ハンドラー（generate_document, generate_image, generate_video）
    """
    global _brain_integration
    if _brain_integration is None and USE_BRAIN_ARCHITECTURE and create_integration:
        # 基本ハンドラー
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
            "goal_registration": _brain_handle_goal_setting_start,  # v10.29.6: SYSTEM_CAPABILITIESと名前を一致
            "goal_progress_report": _brain_handle_goal_progress_report,
            "goal_status_check": _brain_handle_goal_status_check,
            "announcement_create": _brain_handle_announcement_create,
            "query_org_chart": _brain_handle_query_org_chart,
            "daily_reflection": _brain_handle_daily_reflection,
            "proposal_decision": _brain_handle_proposal_decision,
            "api_limitation": _brain_handle_api_limitation,
            "general_conversation": _brain_handle_general_conversation,
            # v10.39.1: セッション継続ハンドラー（脳のcore.pyから呼び出される）
            "continue_goal_setting": _brain_continue_goal_setting,
            "continue_announcement": _brain_continue_announcement,
            "continue_task_pending": _brain_continue_task_pending,
            # v10.39.2: 目標設定中断・再開ハンドラー（意図理解による中断対応）
            "interrupt_goal_setting": _brain_interrupt_goal_setting,
            "get_interrupted_goal_setting": _brain_get_interrupted_goal_setting,
            "resume_goal_setting": _brain_resume_goal_setting,
            # v10.40.1: goal_setting.pyがbrain_conversation_statesを使用するためのpool
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

                # historyを準備（会話履歴形式に変換）
                history = []
                for msg in (recent_conv or []):
                    if isinstance(msg, dict):
                        history.append(msg)
                    elif hasattr(msg, "to_dict"):
                        history.append(msg.to_dict())

                return get_ai_response(message, history, sender_name, context_dict)
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


# =====================================================
# v10.28.0: 脳アーキテクチャ - SoulkunBrain初期化（後方互換）
# =====================================================
def _get_brain():
    """
    SoulkunBrainのシングルトンインスタンスを取得（後方互換用）

    v10.29.0: BrainIntegrationから内部のbrainを取得するように変更
    """
    global _brain_instance
    # BrainIntegrationがある場合はそちらのbrainを使用
    integration = _get_brain_integration()
    if integration:
        return integration.get_brain()
    # フォールバック: 直接SoulkunBrainを初期化
    if _brain_instance is None and USE_BRAIN_ARCHITECTURE:
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
            "goal_registration": _brain_handle_goal_setting_start,  # v10.29.6: SYSTEM_CAPABILITIESと名前を一致
            "goal_progress_report": _brain_handle_goal_progress_report,
            "goal_status_check": _brain_handle_goal_status_check,
            "announcement_create": _brain_handle_announcement_create,
            "query_org_chart": _brain_handle_query_org_chart,
            "daily_reflection": _brain_handle_daily_reflection,
            "proposal_decision": _brain_handle_proposal_decision,
            "api_limitation": _brain_handle_api_limitation,
            "general_conversation": _brain_handle_general_conversation,
            # v10.39.1: セッション継続ハンドラー（脳のcore.pyから呼び出される）
            "continue_goal_setting": _brain_continue_goal_setting,
            "continue_announcement": _brain_continue_announcement,
            "continue_task_pending": _brain_continue_task_pending,
            # v10.39.2: 目標設定中断・再開ハンドラー（意図理解による中断対応）
            "interrupt_goal_setting": _brain_interrupt_goal_setting,
            "get_interrupted_goal_setting": _brain_get_interrupted_goal_setting,
            "resume_goal_setting": _brain_resume_goal_setting,
            # v10.40.1: goal_setting.pyがbrain_conversation_statesを使用するためのpool
            "_pool": get_pool(),
        }

        # v10.38.0: CapabilityBridgeのハンドラーを追加（フォールバック用）
        bridge = _get_capability_bridge()
        if bridge:
            try:
                capability_handlers = bridge.get_capability_handlers()
                handlers.update(capability_handlers)
            except Exception as e:
                print(f"⚠️ CapabilityBridge handlers failed (fallback): {e}")

        _brain_instance = SoulkunBrain(
            pool=get_pool(),
            org_id=ADMIN_CONFIG_DEFAULT_ORG_ID if USE_ADMIN_CONFIG else "5f98365f-e7c5-4f48-9918-7fe9aabae5df",
            handlers=handlers,
            capabilities=SYSTEM_CAPABILITIES,  # v10.29.7: 直接参照（in dir()は機能しない）
            get_ai_response_func=get_ai_response,
            firestore_db=db,
        )
        print("✅ SoulkunBrain instance initialized (fallback)")
    return _brain_instance


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
    if USE_GOAL_SETTING_LIB:
        try:
            pool = get_pool()
            session = has_active_goal_session(pool, room_id, account_id)
            if session:
                context["has_active_goal_session"] = True
                context["goal_session_id"] = session.get("session_id") if isinstance(session, dict) else None
        except Exception as e:
            print(f"⚠️ Goal session check failed: {e}")

    # アナウンス確認待ちチェック（v10.33.0: フラグチェック削除）
    try:
        handler = _get_announcement_handler()
        if handler:
            pending = handler._get_pending_announcement(room_id, account_id)
            if pending:
                context["has_pending_announcement"] = True
                context["announcement_id"] = pending.get("id") if isinstance(pending, dict) else None
    except Exception as e:
        print(f"⚠️ Announcement check failed: {e}")

    return context


# =====================================================
# v10.38.1: バイパスハンドラー（脳の中から呼び出される）
# 脳の7原則「全ての入力は脳を通る」を守りつつ、既存の安定した
# ハンドラーを活用するためのラッパー関数
# =====================================================

def _bypass_handle_goal_session(message, room_id, account_id, sender_name, bypass_context):
    """
    目標設定セッション用のバイパスハンドラー

    アクティブな目標設定セッションがある場合、または目標設定を
    開始したいキーワードが含まれている場合に呼び出される。

    Returns:
        str: 応答メッセージ、Noneの場合は通常処理へ
    """
    if not USE_GOAL_SETTING_LIB:
        return None

    try:
        pool = get_pool()
        has_session = has_active_goal_session(pool, room_id, account_id)

        # 目標設定開始キーワードの検出
        goal_start_keywords = [
            "目標設定したい", "目標を設定したい", "目標を立てたい", "目標を決めたい",
            "目標設定を始め", "目標登録したい", "目標を登録したい",
            "今月の目標を設定", "個人目標を設定", "目標設定して"
        ]
        is_question = message.endswith("？") or any(q in message for q in ["繋がってる", "どう思う", "ちゃんと", "について"])
        wants_goal_setting = any(kw in message for kw in goal_start_keywords) and not is_question

        print(f"🎯 [バイパス] 目標設定: has_session={has_session}, wants_goal_setting={wants_goal_setting}")

        if has_session or wants_goal_setting:
            result = process_goal_setting_message(pool, room_id, account_id, message)
            if result and result.get("success"):
                return result.get("message", "")
            else:
                error_msg = result.get("message") if result else None
                if not error_msg:
                    error_msg = "🤔 目標設定の処理中にエラーが発生したウル...\nもう一度メッセージを送ってほしいウル🐺"
                return error_msg

        return None  # セッションなし、開始キーワードなしの場合は通常処理へ

    except Exception as e:
        print(f"❌ [バイパス] 目標設定エラー: {e}")
        import traceback
        traceback.print_exc()
        # エラーでもセッションがある場合はエラーメッセージを返す
        if bypass_context.get("has_active_goal_session"):
            return "🤔 目標設定の処理中にエラーが発生したウル...\nもう一度メッセージを送ってほしいウル🐺"
        return None


def _bypass_handle_announcement(message, room_id, account_id, sender_name, bypass_context):
    """
    アナウンス確認待ち用のバイパスハンドラー

    pending announcementがある場合に呼び出される。

    Returns:
        str: 応答メッセージ、Noneの場合は通常処理へ
    """
    try:
        announcement_handler = _get_announcement_handler()
        if not announcement_handler:
            return None

        pending = announcement_handler._get_pending_announcement(room_id, account_id)
        if not pending:
            return None

        print(f"📢 [バイパス] pending announcement検出: {pending.get('id')}")

        response = announcement_handler.handle_announcement_request(
            params={"raw_message": message},
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )

        # Noneが返った場合はフォローアップではないので通常処理へ
        if response is None:
            print(f"📢 [バイパス] フォローアップではない判定 → 通常処理へ")
            return None

        return response

    except Exception as e:
        print(f"❌ [バイパス] announcement エラー: {e}")
        return None


def _build_bypass_handlers():
    """
    バイパスハンドラーのマッピングを構築

    v10.39.3: goal_sessionバイパスを削除
    - 脳の意図理解を通すため、バイパスを使わない
    - 脳のcore.py _continue_goal_setting() で意図を理解してから処理

    Returns:
        dict: バイパスタイプ -> ハンドラー関数のマッピング
    """
    return {
        # v10.39.3: goal_session バイパスを削除（脳が意図理解してからハンドラーを呼ぶ）
        # "goal_session": _bypass_handle_goal_session,
        "announcement_pending": _bypass_handle_announcement,
        # "task_pending" と "local_command" は既存の脳内処理で対応可能
    }


# =====================================================
# v10.28.0: 脳用ハンドラーラッパー関数
# =====================================================

async def _brain_handle_task_search(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_chatwork_task_search(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "タスクが見つからなかったウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"タスク検索でエラーが発生したウル🐺")


async def _brain_handle_task_create(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_chatwork_task_create(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "タスクを作成したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"タスク作成でエラーが発生したウル🐺")


async def _brain_handle_task_complete(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        handler_context = {}
        if context and hasattr(context, 'recent_tasks') and context.recent_tasks:
            handler_context["recent_tasks_context"] = context.recent_tasks
        result = handle_chatwork_task_complete(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=handler_context)
        return HandlerResult(success=True, message=result if result else "タスクを完了にしたウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"タスク完了でエラーが発生したウル🐺")


async def _brain_handle_query_knowledge(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_query_company_knowledge(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "ナレッジが見つからなかったウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"ナレッジ検索でエラーが発生したウル🐺")


async def _brain_handle_save_memory(params, room_id, account_id, sender_name, context):
    """
    記憶保存ハンドラー

    v10.40.9: メモリ分離対応
    - ボットペルソナ設定 → bot_persona_memoryに保存
    - 長期記憶パターン → user_long_term_memoryに保存
    - それ以外 → 従来の人物情報記憶（persons/person_attributes）
    """
    from lib.brain.models import HandlerResult
    try:
        # オリジナルメッセージを取得
        original_message = ""
        if context:
            original_message = getattr(context, 'original_message', '') or ''
            if not original_message and hasattr(context, 'to_dict'):
                ctx_dict = context.to_dict()
                original_message = ctx_dict.get('original_message', '')

        # v10.40.9: ボットペルソナ設定を先に検出
        if USE_BOT_PERSONA_MEMORY and original_message and is_bot_persona_setting(original_message):
            print(f"🐺 ボットペルソナ設定検出: {original_message[:50]}...")
            result = await _handle_save_bot_persona(
                original_message, room_id, account_id, sender_name
            )
            return HandlerResult(success=result.get("success", False), message=result.get("message", ""))

        # v10.40.8: 長期記憶パターンを検出
        if USE_LONG_TERM_MEMORY and original_message and is_long_term_memory_request(original_message):
            print(f"🔥 長期記憶パターン検出: {original_message[:50]}...")
            result = await _handle_save_long_term_memory(
                original_message, room_id, account_id, sender_name
            )
            return HandlerResult(success=result.get("success", False), message=result.get("message", ""))

        # 通常の人物情報記憶
        result = handle_save_memory(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "覚えたウル🐺")
    except Exception as e:
        print(f"❌ 記憶保存エラー: {e}")
        return HandlerResult(success=False, message=f"記憶保存でエラーが発生したウル🐺")


async def _handle_save_long_term_memory(message: str, room_id: str, account_id: str, sender_name: str):
    """
    長期記憶（人生軸・価値観）を保存

    v10.40.8: 新規追加
    """
    try:
        pool = get_pool()

        # ユーザー情報を取得
        with pool.connect() as conn:
            user_result = conn.execute(
                sqlalchemy.text("""
                    SELECT id, organization_id FROM users
                    WHERE chatwork_account_id = :account_id
                    LIMIT 1
                """),
                {"account_id": str(account_id)}
            ).fetchone()

            if not user_result:
                return {
                    "success": False,
                    "message": "ユーザー情報が見つからなかったウル...🐺"
                }

            user_id = int(user_result[0])  # v10.40.8: integerとして保持
            org_id = str(user_result[1]) if user_result[1] else None

            if not org_id:
                return {
                    "success": False,
                    "message": "組織情報が見つからなかったウル...🐺"
                }

        # 長期記憶を保存
        result = save_long_term_memory(
            pool=pool,
            org_id=org_id,
            user_id=user_id,
            user_name=sender_name,
            message=message
        )

        return result

    except Exception as e:
        print(f"❌ 長期記憶保存エラー: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"長期記憶の保存中にエラーが発生したウル...🐺\n（エラー: {str(e)}）"
        }


async def _handle_save_bot_persona(
    message: str,
    room_id: str,
    account_id: str,
    sender_name: str
) -> Dict[str, Any]:
    """
    v10.40.9: ボットペルソナ設定を保存

    ソウルくんのキャラ設定（好物、口調など）を保存。
    管理者のみ設定可能。
    """
    try:
        # 管理者チェック
        if not is_admin(account_id):
            return {
                "success": False,
                "message": "ソウルくんの設定は管理者のみ変更できるウル🐺\n菊地さんにお願いしてほしいウル！"
            }

        pool = get_pool()

        # 組織IDを取得
        with pool.connect() as conn:
            user_result = conn.execute(
                sqlalchemy.text("""
                    SELECT organization_id FROM users
                    WHERE chatwork_account_id = :account_id
                    LIMIT 1
                """),
                {"account_id": str(account_id)}
            ).fetchone()

            if not user_result:
                # 組織が見つからない場合はデフォルト組織を使用
                org_result = conn.execute(
                    sqlalchemy.text("""
                        SELECT id FROM organizations LIMIT 1
                    """)
                ).fetchone()
                if org_result:
                    org_id = str(org_result[0])
                else:
                    return {
                        "success": False,
                        "message": "組織情報が見つからなかったウル...🐺"
                    }
            else:
                org_id = str(user_result[0]) if user_result[0] else None

        if not org_id:
            return {
                "success": False,
                "message": "組織情報が見つからなかったウル...🐺"
            }

        # ボットペルソナを保存
        result = save_bot_persona(
            pool=pool,
            org_id=org_id,
            message=message,
            account_id=str(account_id),
            sender_name=sender_name
        )

        return result

    except Exception as e:
        print(f"❌ ボットペルソナ保存エラー: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"ボット設定の保存中にエラーが発生したウル...🐺"
        }


async def _handle_query_long_term_memory(
    account_id: str,
    sender_name: str,
    target_user_id: int = None
) -> Dict[str, Any]:
    """
    v10.40.9: 長期記憶（人生軸・価値観）を取得

    アクセス制御:
    - 本人の記憶: 全て取得可能
    - 他ユーザーの記憶: ORG_SHARED のみ取得可能
    - PRIVATEスコープの記憶は本人以外には絶対に返さない
    """
    try:
        pool = get_pool()

        # リクエスターのユーザー情報を取得
        with pool.connect() as conn:
            requester_result = conn.execute(
                sqlalchemy.text("""
                    SELECT user_id, organization_id FROM users
                    WHERE chatwork_account_id = :account_id
                    LIMIT 1
                """),
                {"account_id": str(account_id)}
            ).fetchone()

            if not requester_result:
                return {
                    "success": False,
                    "message": "ユーザー情報が見つからなかったウル...🐺"
                }

            requester_user_id = int(requester_result[0])
            org_id = str(requester_result[1]) if requester_result[1] else None

            if not org_id:
                return {
                    "success": False,
                    "message": "組織情報が見つからなかったウル...🐺"
                }

        # ターゲットユーザーを決定（指定がなければリクエスター自身）
        target_id = target_user_id if target_user_id else requester_user_id
        is_self_query = (target_id == requester_user_id)

        # 長期記憶を取得（アクセス制御付き）
        manager = LongTermMemoryManager(pool, org_id, target_id, sender_name)

        if is_self_query:
            # 本人の記憶は全て取得
            memories = manager.get_all()
            if not memories:
                return {
                    "success": True,
                    "message": f"🐺 {sender_name}さんの人生の軸はまだ登録されていないウル！\n\n「人生の軸として覚えて」と言ってくれたら覚えるウル！"
                }
            display = manager.format_for_display(show_scope=False)
            return {
                "success": True,
                "message": display
            }
        else:
            # 他ユーザーの記憶はORG_SHAREDのみ
            memories = manager.get_all_for_requester(requester_user_id)
            if not memories:
                return {
                    "success": True,
                    "message": "共有されている情報は見つからなかったウル🐺"
                }
            # 注意: 他ユーザーの記憶を表示する際は個人情報を匿名化
            display = f"🐺 共有されている情報ウル！\n\n"
            for m in memories:
                type_label = m.get("memory_type", "記憶")
                display += f"【{type_label}】\n{m['content']}\n\n"
            return {
                "success": True,
                "message": display
            }

    except Exception as e:
        print(f"❌ 長期記憶取得エラー: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"長期記憶の取得中にエラーが発生したウル...🐺"
        }


async def _brain_handle_query_memory(params, room_id, account_id, sender_name, context):
    """
    記憶検索ハンドラー

    v10.40.9: 長期記憶（人生軸）クエリを検出して分岐
    - 「軸を確認」「人生の軸」→ user_long_term_memoryから取得
    - それ以外 → 従来のpersons/person_attributesから取得
    """
    from lib.brain.models import HandlerResult
    import re
    try:
        # v10.40.9: 長期記憶クエリパターンの検出
        original_message = ""
        if context:
            original_message = getattr(context, 'original_message', '') or ''
            if not original_message and hasattr(context, 'to_dict'):
                ctx_dict = context.to_dict()
                original_message = ctx_dict.get('original_message', '')

        # 長期記憶クエリパターン
        long_term_memory_query_patterns = [
            r"軸を(確認|教えて|見せて)",
            r"(俺|私|自分)の軸",
            r"人生の軸",
            r"価値観を(確認|教えて)",
            r"(何を)?覚えてる.*軸",
        ]

        is_long_term_query = False
        if USE_LONG_TERM_MEMORY and original_message:
            for pattern in long_term_memory_query_patterns:
                if re.search(pattern, original_message, re.IGNORECASE):
                    is_long_term_query = True
                    break

        if is_long_term_query:
            print(f"🔥 長期記憶クエリ検出: {original_message[:50]}...")
            result = await _handle_query_long_term_memory(
                account_id=account_id,
                sender_name=sender_name
            )
            return HandlerResult(success=result.get("success", False), message=result.get("message", ""))

        # 通常の人物情報検索
        result = handle_query_memory(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "記憶が見つからなかったウル🐺")
    except Exception as e:
        print(f"❌ 記憶検索エラー: {e}")
        return HandlerResult(success=False, message=f"記憶検索でエラーが発生したウル🐺")


async def _brain_handle_delete_memory(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_delete_memory(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "忘れたウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"記憶削除でエラーが発生したウル🐺")


async def _brain_handle_learn_knowledge(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_learn_knowledge(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "覚えたウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"知識学習でエラーが発生したウル🐺")


async def _brain_handle_forget_knowledge(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_forget_knowledge(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "忘れたウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"知識削除でエラーが発生したウル🐺")


async def _brain_handle_list_knowledge(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_list_knowledge(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "知識一覧を取得したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"知識一覧でエラーが発生したウル🐺")


async def _brain_handle_goal_setting_start(params, room_id, account_id, sender_name, context):
    """目標設定開始ハンドラー（v10.29.8）"""
    from lib.brain.models import HandlerResult
    try:
        if USE_GOAL_SETTING_LIB:
            pool = get_pool()
            result = process_goal_setting_message(pool, room_id, account_id, "目標を設定したい")
            if result:
                message = result.get("message", "")
                if message:
                    return HandlerResult(success=result.get("success", False), message=message)
        return HandlerResult(success=True, message="目標設定を始めるウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message="目標設定でエラーが発生したウル🐺")


# =====================================================
# v10.39.1: セッション継続ハンドラー
# 脳のcore.pyの_continue_*メソッドから呼び出される
# シグネチャ: (message, room_id, account_id, sender_name, state_data) -> dict or str or None
# =====================================================

def _brain_continue_goal_setting(message, room_id, account_id, sender_name, state_data):
    """
    目標設定セッションを継続

    GoalSettingDialogueを使用してセッションを継続します。

    v10.41.0: 長期記憶要求検出時のリダイレクト対応
    """
    try:
        if USE_GOAL_SETTING_LIB:
            pool = get_pool()
            result = process_goal_setting_message(pool, room_id, account_id, message)
            if result:
                # v10.41.0: 長期記憶へのリダイレクトをチェック
                if result.get("redirect_to") == "save_long_term_memory":
                    print(f"🔥 長期記憶へリダイレクト: {message[:50]}...")
                    original_message = result.get("original_message", message)

                    # 長期記憶保存を実行
                    import asyncio
                    loop = asyncio.get_event_loop()
                    ltm_result = loop.run_until_complete(
                        _handle_save_long_term_memory(original_message, room_id, account_id, sender_name)
                    )

                    if ltm_result.get("success"):
                        # 保存成功：目標設定セッションは中断状態のまま
                        # ユーザーに保存完了を通知し、目標設定を続けるか確認
                        followup_message = (
                            f"\n\n💡 目標設定の途中だったウル！続ける場合は「続ける」、"
                            f"やめる場合は「やめる」と言ってウル🐺"
                        )
                        # v10.41.0: 社長の魂OSガードレールを適用
                        final_message = ensure_soul_os_compliant(
                            ltm_result.get("message", "") + followup_message,
                            context="goal_setting_ltm_redirect"
                        )
                        return {
                            "message": final_message,
                            "success": True,
                            "session_completed": False,
                            "new_state": None,
                            "state_changed": False,
                        }
                    else:
                        # 保存失敗：エラーメッセージを返す
                        return {
                            "message": ltm_result.get("message", "長期記憶の保存に失敗したウル..."),
                            "success": False,
                            "session_completed": False,
                        }

                response_message = result.get("message", "")
                session_completed = result.get("session_completed", False)
                return {
                    "message": response_message,
                    "success": result.get("success", True),
                    "session_completed": session_completed,
                    "new_state": "normal" if session_completed else None,
                    "state_changed": session_completed,
                }
        # フォールバック
        return {
            "message": "目標設定を続けるウル🐺 もう少し詳しく教えてほしいウル！",
            "success": True,
        }
    except Exception as e:
        print(f"❌ _brain_continue_goal_setting error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "message": "目標設定の処理中にエラーが発生したウル🐺",
            "success": False,
            "session_completed": True,
            "new_state": "normal",
        }


def _brain_continue_announcement(message, room_id, account_id, sender_name, state_data):
    """
    アナウンス確認セッションを継続

    AnnouncementHandlerを使用してセッションを継続します。
    """
    try:
        handler = _get_announcement_handler()
        if handler:
            # state_dataからpending_announcement_idを取得
            pending_id = state_data.get("pending_announcement_id") if state_data else None
            context = {
                "awaiting_announcement_response": True,
                "pending_announcement_id": pending_id,
            }
            # パラメータを構築
            params = {
                "raw_message": message,
            }
            result = handler.handle_announcement_request(
                params=params,
                room_id=room_id,
                account_id=account_id,
                sender_name=sender_name,
                context=context,
            )
            if result:
                # 結果を解析して完了状態を判定
                is_completed = any(kw in result for kw in ["送信完了", "キャンセル", "スケジュール完了"])
                return {
                    "message": result,
                    "success": True,
                    "session_completed": is_completed,
                    "new_state": "normal" if is_completed else None,
                }
        return {
            "message": "アナウンスの確認を続けるウル🐺",
            "success": True,
        }
    except Exception as e:
        print(f"❌ _brain_continue_announcement error: {e}")
        return {
            "message": "アナウンス処理中にエラーが発生したウル🐺",
            "success": False,
            "session_completed": True,
            "new_state": "normal",
        }


def _brain_continue_task_pending(message, room_id, account_id, sender_name, state_data):
    """
    タスク作成待ち状態を継続

    handle_pending_task_followupを使用して不足情報を補完します。
    """
    try:
        # handle_pending_task_followupを呼び出し
        result = handle_pending_task_followup(message, room_id, account_id, sender_name)

        if result:
            # タスク作成成功
            return {
                "message": result,
                "success": True,
                "task_created": True,
                "new_state": "normal",
            }
        else:
            # 補完できなかった場合
            return None
    except Exception as e:
        print(f"❌ _brain_continue_task_pending error: {e}")
        return {
            "message": "タスク作成中にエラーが発生したウル🐺",
            "success": False,
            "task_created": False,
            "new_state": "normal",
        }


# =====================================================
# v10.39.2: 目標設定中断・再開ハンドラー
# 脳が意図を汲み取り、別の話題に対応するための仕組み
# =====================================================

# グローバル変数: 中断されたセッションを一時保存
_interrupted_goal_sessions = {}


def _brain_interrupt_goal_setting(room_id, account_id, interrupted_session):
    """
    目標設定セッションを中断状態で保存

    脳が「別の意図」を検出した場合に呼ばれる。
    途中経過を記憶し、後で再開できるようにする。
    """
    try:
        key = f"{room_id}:{account_id}"
        _interrupted_goal_sessions[key] = interrupted_session
        print(f"📝 目標設定セッションを中断保存: {key}, step={interrupted_session.get('current_step')}")
        return True
    except Exception as e:
        print(f"❌ _brain_interrupt_goal_setting error: {e}")
        return False


def _brain_get_interrupted_goal_setting(room_id, account_id):
    """中断されたセッションを取得"""
    key = f"{room_id}:{account_id}"
    return _interrupted_goal_sessions.get(key)


def _brain_resume_goal_setting(message, room_id, account_id, sender_name, state_data):
    """
    中断されたセッションを再開

    「目標設定の続き」などのキーワードで呼ばれる。
    """
    try:
        key = f"{room_id}:{account_id}"
        interrupted = _interrupted_goal_sessions.get(key)

        if not interrupted:
            return {
                "message": "中断された目標設定は見つからなかったウル🐺\n新しく目標設定を始める？「目標設定したい」と言ってくれればスタートするウル！",
                "success": True,
                "session_completed": False,
            }

        # 中断されたセッションの情報を取得
        current_step = interrupted.get("current_step", "why")
        why_answer = interrupted.get("why_answer", "")
        what_answer = interrupted.get("what_answer", "")
        how_answer = interrupted.get("how_answer", "")

        # セッションを再開
        if USE_GOAL_SETTING_LIB:
            pool = get_pool()
            # 既存のセッションを再開するか、新しいセッションを開始
            result = process_goal_setting_message(pool, room_id, account_id, "目標設定を再開したい")
            if result:
                # 中断されたセッションをクリア
                del _interrupted_goal_sessions[key]

                # 進捗を表示
                progress_summary = "📝 前回の進捗:\n"
                if why_answer:
                    progress_summary += f"・WHY: {why_answer[:50]}...\n" if len(why_answer) > 50 else f"・WHY: {why_answer}\n"
                if what_answer:
                    progress_summary += f"・WHAT: {what_answer[:50]}...\n" if len(what_answer) > 50 else f"・WHAT: {what_answer}\n"
                if how_answer:
                    progress_summary += f"・HOW: {how_answer[:50]}...\n" if len(how_answer) > 50 else f"・HOW: {how_answer}\n"

                response = result.get("message", "")
                if progress_summary != "📝 前回の進捗:\n":
                    response = f"{progress_summary}\n{response}"

                return {
                    "message": response,
                    "success": True,
                    "session_completed": result.get("session_completed", False),
                }

        return {
            "message": "目標設定を再開するウル🐺",
            "success": True,
        }
    except Exception as e:
        print(f"❌ _brain_resume_goal_setting error: {e}")
        return {
            "message": "目標設定の再開中にエラーが発生したウル🐺",
            "success": False,
        }


async def _brain_handle_goal_progress_report(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_goal_progress_report(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "進捗を報告したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"進捗報告でエラーが発生したウル🐺")


async def _brain_handle_goal_status_check(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_goal_status_check(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "目標状況を確認したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"目標状況確認でエラーが発生したウル🐺")


async def _brain_handle_announcement_create(params, room_id, account_id, sender_name, context):
    """v10.33.0: USE_ANNOUNCEMENT_FEATUREフラグチェック削除"""
    from lib.brain.models import HandlerResult
    try:
        handler = _get_announcement_handler()
        if handler:
            result = handler.handle_announcement_request(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name)
            if result:
                return HandlerResult(success=True, message=result)
        return HandlerResult(success=True, message="アナウンス機能は現在準備中ウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"アナウンスでエラーが発生したウル🐺")


async def _brain_handle_query_org_chart(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_query_org_chart(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "組織情報を取得したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"組織図クエリでエラーが発生したウル🐺")


async def _brain_handle_daily_reflection(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_daily_reflection(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "振り返りを記録したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"振り返りでエラーが発生したウル🐺")


async def _brain_handle_proposal_decision(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_proposal_decision(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "提案を処理したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"提案処理でエラーが発生したウル🐺")


async def _brain_handle_api_limitation(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        result = handle_api_limitation(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "API制限の説明ウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"API制限説明でエラーが発生したウル🐺")


async def _brain_handle_general_conversation(params, room_id, account_id, sender_name, context):
    from lib.brain.models import HandlerResult
    try:
        history = get_conversation_history(room_id, account_id)
        room_context = get_room_context(room_id, limit=30)
        all_persons = get_all_persons_summary()
        context_parts = []
        if room_context:
            context_parts.append(f"【このルームの最近の会話】\n{room_context}")
        if all_persons:
            persons_str = "\n".join([f"・{p['name']}: {p['attributes']}" for p in all_persons[:5] if p['attributes']])
            if persons_str:
                context_parts.append(f"【覚えている人物】\n{persons_str}")
        context_str = "\n\n".join(context_parts) if context_parts else None
        ai_response = get_ai_response(params.get("message", ""), history, sender_name, context_str, "ja")
        return HandlerResult(success=True, message=ai_response)
    except Exception as e:
        return HandlerResult(success=False, message=f"ごめんウル...もう一度試してほしいウル🐺")


def create_chatwork_task(room_id, task_body, assigned_to_account_id, limit=None):
    """
    ChatWork APIでタスクを作成（リトライ機構付き）

    v10.24.4: handlers/task_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_task_handler()
    if handler:
        return handler.create_chatwork_task(room_id, task_body, assigned_to_account_id, limit)

    print("❌ TaskHandler not available - cannot create task")
    return None


def complete_chatwork_task(room_id, task_id):
    """
    ChatWork APIでタスクを完了にする（リトライ機構付き）

    v10.24.4: handlers/task_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_task_handler()
    if handler:
        return handler.complete_chatwork_task(room_id, task_id)

    print("❌ TaskHandler not available - cannot complete task")
    return None


def get_user_id_from_chatwork_account(conn, chatwork_account_id):
    """ChatWorkアカウントIDからユーザーIDを取得（Phase 3.5対応）"""
    try:
        result = conn.execute(
            sqlalchemy.text("""
                SELECT id FROM users
                WHERE chatwork_account_id = :chatwork_account_id
                  AND is_active = TRUE
                LIMIT 1
            """),
            {"chatwork_account_id": str(chatwork_account_id)}
        )
        row = result.fetchone()
        return row[0] if row else None
    except Exception as e:
        print(f"ユーザーID取得エラー: {e}")
        return None


def get_accessible_departments(conn, user_id, organization_id):
    """ユーザーがアクセス可能な部署IDリストを取得（Phase 3.5対応）"""
    try:
        # ユーザーの権限レベルを取得
        result = conn.execute(
            sqlalchemy.text("""
                SELECT COALESCE(MAX(r.level), 2) as max_level
                FROM user_departments ud
                JOIN roles r ON ud.role_id = r.id
                WHERE ud.user_id = :user_id AND ud.ended_at IS NULL
            """),
            {"user_id": user_id}
        )
        row = result.fetchone()
        role_level = row[0] if row and row[0] else 2

        # Level 5-6: 全組織アクセス（フィルタなし）
        if role_level >= 5:
            return None  # Noneは「フィルタなし」を意味

        # ユーザーの所属部署を取得
        result = conn.execute(
            sqlalchemy.text("""
                SELECT department_id FROM user_departments
                WHERE user_id = :user_id AND ended_at IS NULL
            """),
            {"user_id": user_id}
        )
        user_depts = [row[0] for row in result.fetchall()]

        if not user_depts:
            return []

        accessible_depts = set(user_depts)

        for dept_id in user_depts:
            if role_level >= 4:
                # 配下全部署
                result = conn.execute(
                    sqlalchemy.text("""
                        WITH dept_path AS (
                            SELECT path FROM departments WHERE id = :dept_id
                        )
                        SELECT d.id FROM departments d, dept_path dp
                        WHERE d.path <@ dp.path AND d.id != :dept_id AND d.is_active = TRUE
                    """),
                    {"dept_id": dept_id}
                )
                accessible_depts.update([row[0] for row in result.fetchall()])
            elif role_level >= 3:
                # 直下部署のみ
                result = conn.execute(
                    sqlalchemy.text("""
                        SELECT id FROM departments
                        WHERE parent_id = :dept_id AND is_active = TRUE
                    """),
                    {"dept_id": dept_id}
                )
                accessible_depts.update([row[0] for row in result.fetchall()])

        return list(accessible_depts)
    except Exception as e:
        print(f"アクセス可能部署取得エラー: {e}")
        return None  # エラー時はフィルタなし（後方互換性）


def search_tasks_from_db(room_id, assigned_to_account_id=None, assigned_by_account_id=None, status="open",
                          enable_dept_filter=False, organization_id=None, search_all_rooms=False):
    """DBからタスクを検索

    v10.24.4: handlers/task_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）

    Args:
        room_id: チャットルームID（search_all_rooms=Trueの場合は無視）
        assigned_to_account_id: 担当者のChatWorkアカウントID
        assigned_by_account_id: 依頼者のChatWorkアカウントID
        status: タスクステータス（"open", "done", "all"）
        enable_dept_filter: True=部署フィルタを有効化（Phase 3.5対応）
        organization_id: 組織ID（部署フィルタ有効時に必要）
        search_all_rooms: True=全ルームからタスクを検索（v10.22.0 BUG-001修正）
    """
    handler = _get_task_handler()
    if handler:
        return handler.search_tasks_from_db(
            room_id, assigned_to_account_id, assigned_by_account_id, status,
            enable_dept_filter, organization_id, search_all_rooms,
            get_user_id_from_chatwork_account, get_accessible_departments
        )

    print("❌ TaskHandler not available - cannot search tasks")
    return []


def update_task_status_in_db(task_id, status):
    """
    DBのタスクステータスを更新

    v10.24.4: handlers/task_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_task_handler()
    if handler:
        return handler.update_task_status_in_db(task_id, status)

    print("❌ TaskHandler not available - cannot update task status")
    return False


def get_user_primary_department(conn, chatwork_account_id):
    """担当者のメイン部署IDを取得（Phase 3.5対応）"""
    try:
        result = conn.execute(
            sqlalchemy.text("""
                SELECT ud.department_id
                FROM user_departments ud
                JOIN users u ON ud.user_id = u.id
                WHERE u.chatwork_account_id = :chatwork_account_id
                  AND ud.is_primary = TRUE
                  AND ud.ended_at IS NULL
                LIMIT 1
            """),
            {"chatwork_account_id": str(chatwork_account_id)}
        )
        row = result.fetchone()
        return row[0] if row else None
    except Exception as e:
        print(f"部署取得エラー: {e}")
        return None


def save_chatwork_task_to_db(task_id, room_id, assigned_by_account_id, assigned_to_account_id, body, limit_time):
    """
    ChatWorkタスクをデータベースに保存（明示的なパラメータで受け取る）

    ★★★ v10.18.1: summary生成機能追加 ★★★
    タスク作成時にsummaryを自動生成して保存

    v10.24.4: handlers/task_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_task_handler()
    if handler:
        return handler.save_chatwork_task_to_db(
            task_id, room_id, assigned_by_account_id, assigned_to_account_id, body, limit_time
        )

    print("❌ TaskHandler not available - cannot save task to DB")
    return False


# ===== 分析イベントログ =====

def log_analytics_event(event_type, actor_account_id, actor_name, room_id, event_data, success=True, error_message=None, event_subtype=None):
    """
    分析用イベントログを記録

    v10.24.4: handlers/task_handler.py に委譲
    v10.32.0: フォールバック削除（ハンドラー必須化）

    Args:
        event_type: イベントタイプ（'task_created', 'memory_saved', 'memory_queried', 'general_chat'等）
        actor_account_id: 実行者のChatWork account_id
        actor_name: 実行者の名前
        room_id: ChatWorkルームID
        event_data: 詳細データ（辞書形式）
        success: 成功したかどうか
        error_message: エラーメッセージ（失敗時）
        event_subtype: 詳細分類（オプション）

    Note:
        この関数はエラーが発生しても例外を投げない（処理を止めない）
        ログ記録は「あったら嬉しい」レベルの機能であり、本体処理を妨げない
    """
    handler = _get_task_handler()
    if handler:
        handler.log_analytics_event(
            event_type=event_type,
            actor_account_id=actor_account_id,
            actor_name=actor_name,
            room_id=room_id,
            event_data=event_data,
            success=success,
            error_message=error_message,
            event_subtype=event_subtype
        )
        return

    # Handler not available - skip logging (non-critical)
    print(f"⚠️ TaskHandler not available - skipping analytics log for {event_type}")


# ===== pending_task（タスク作成の途中状態）管理 =====

def get_pending_task(room_id, account_id):
    """pending_taskを取得（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            # 10分以上前のpending_taskは無効
            created_at = data.get("created_at")
            if created_at:
                expiry_time = datetime.now(timezone.utc) - timedelta(minutes=10)
                if created_at.replace(tzinfo=timezone.utc) < expiry_time:
                    # 期限切れなので削除
                    doc_ref.delete()
                    return None
            return data
    except Exception as e:
        print(f"pending_task取得エラー: {e}")
    return None

def save_pending_task(room_id, account_id, task_data):
    """pending_taskを保存（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        task_data["created_at"] = datetime.now(timezone.utc)
        doc_ref.set(task_data)
        print(f"✅ pending_task保存: room={room_id}, account={account_id}, data={task_data}")
        return True
    except Exception as e:
        print(f"pending_task保存エラー: {e}")
        return False

def delete_pending_task(room_id, account_id):
    """pending_taskを削除（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        doc_ref.delete()
        print(f"🗑️ pending_task削除: room={room_id}, account={account_id}")
        return True
    except Exception as e:
        print(f"pending_task削除エラー: {e}")
        return False


def parse_date_from_text(text):
    """
    自然言語の日付表現をYYYY-MM-DD形式に変換
    例: "明日", "明後日", "12/27", "来週金曜日"

    v10.24.0: utils/date_utils.py に分割
    """
    # 新しいモジュールを使用（USE_NEW_DATE_UTILS=trueの場合）
    if USE_NEW_DATE_UTILS:
        return _new_parse_date_from_text(text)

    # フォールバック: 旧実装
    now = datetime.now(JST)
    today = now.date()

    text = text.strip().lower()

    # 「明日」
    if "明日" in text or "あした" in text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # 「明後日」
    if "明後日" in text or "あさって" in text:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    # 「今日」
    if "今日" in text or "きょう" in text:
        return today.strftime("%Y-%m-%d")

    # 「来週」
    if "来週" in text:
        # 来週の月曜日を基準に
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_monday = today + timedelta(days=days_until_monday)

        # 曜日指定があるか確認
        weekdays = {
            "月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6,
            "月曜": 0, "火曜": 1, "水曜": 2, "木曜": 3, "金曜": 4, "土曜": 5, "日曜": 6,
        }
        for day_name, day_num in weekdays.items():
            if day_name in text:
                target = next_monday + timedelta(days=day_num)
                return target.strftime("%Y-%m-%d")

        # 曜日指定がなければ来週の月曜日
        return next_monday.strftime("%Y-%m-%d")

    # 「○日後」
    match = re.search(r'(\d+)日後', text)
    if match:
        days = int(match.group(1))
        return (today + timedelta(days=days)).strftime("%Y-%m-%d")

    # 「MM/DD」形式
    match = re.search(r'(\d{1,2})[/\-](\d{1,2})', text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = today.year
        # 過去の日付なら来年に
        target = datetime(year, month, day).date()
        if target < today:
            target = datetime(year + 1, month, day).date()
        return target.strftime("%Y-%m-%d")

    # 「MM月DD日」形式
    match = re.search(r'(\d{1,2})月(\d{1,2})日', text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = today.year
        target = datetime(year, month, day).date()
        if target < today:
            target = datetime(year + 1, month, day).date()
        return target.strftime("%Y-%m-%d")

    return None


# =====================================================
# v10.3.0: 期限ガードレール機能
# =====================================================
# タスク追加時に期限が「当日」または「明日」の場合、
# 依頼者にアラートを送信する。タスク作成自体はブロックしない。
# =====================================================

def check_deadline_proximity(limit_date_str: str) -> tuple:
    """
    期限が近すぎるかチェックする

    Args:
        limit_date_str: タスクの期限日（YYYY-MM-DD形式）

    Returns:
        (needs_alert: bool, days_until: int, limit_date: date or None)
        - needs_alert: アラートが必要か
        - days_until: 期限までの日数（0=今日, 1=明日, 負=過去）
        - limit_date: 期限日（date型）

    v10.24.0: utils/date_utils.py に分割
    """
    # 新しいモジュールを使用（USE_NEW_DATE_UTILS=trueの場合）
    if USE_NEW_DATE_UTILS:
        return _new_check_deadline_proximity(limit_date_str)

    # フォールバック: 旧実装
    if not limit_date_str:
        return False, -1, None

    try:
        # JSTで現在日付を取得
        now = datetime.now(JST)
        today = now.date()

        # 期限日をパース
        limit_date = datetime.strptime(limit_date_str, "%Y-%m-%d").date()

        # 期限までの日数を計算
        days_until = (limit_date - today).days

        # 過去の日付は別のバリデーションで処理（ここではアラート対象外）
        if days_until < 0:
            return False, days_until, limit_date

        # 当日(0) または 明日(1) ならアラート
        if days_until in DEADLINE_ALERT_DAYS:
            return True, days_until, limit_date

        return False, days_until, limit_date
    except Exception as e:
        print(f"⚠️ check_deadline_proximity エラー: {e}")
        return False, -1, None


# =====================================================
# v10.24.8: フォールバック用切り詰め関数
# =====================================================
def _fallback_truncate_text(text: str, max_length: int = 40) -> str:
    """
    フォールバック用の切り詰め処理（自然な位置で切る）

    prepare_task_display_text()が使えない場合の最終手段。
    句点、読点、助詞の後ろで切ることで、途中で途切れる感を軽減。

    Args:
        text: 切り詰める文字列
        max_length: 最大文字数

    Returns:
        切り詰めた文字列
    """
    if not text:
        return "（タスク内容なし）"

    if len(text) <= max_length:
        return text

    truncated = text[:max_length]

    # 句点、読点、助詞の後ろで切る
    for sep in ["。", "、", "を", "に", "で", "が", "は", "の"]:
        pos = truncated.rfind(sep)
        if pos > max_length // 2:
            return truncated[:pos + 1] + "..."

    return truncated + "..."


# =====================================================
# v10.13.4: タスク本文クリーニング関数
# =====================================================
def clean_task_body_for_summary(body: str) -> str:
    """
    タスク本文からChatWorkのタグや記号を完全に除去（要約用）

    ★★★ v10.13.4: chatwork-webhookにも追加 ★★★
    TODO: Phase 3.5でlib/に共通化予定
    """
    if not body:
        return ""

    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return ""

    try:
        # 1. 引用ブロックの処理
        non_quote_text = re.sub(r'\[qt\].*?\[/qt\]', '', body, flags=re.DOTALL)
        non_quote_text = non_quote_text.strip()

        if non_quote_text and len(non_quote_text) > 10:
            body = non_quote_text
        else:
            quote_matches = re.findall(
                r'\[qt\]\[qtmeta[^\]]*\](.*?)\[/qt\]',
                body,
                flags=re.DOTALL
            )
            if quote_matches:
                extracted_text = ' '.join(quote_matches)
                if extracted_text.strip():
                    body = extracted_text

        # 2. [qtmeta ...] タグを除去
        body = re.sub(r'\[qtmeta[^\]]*\]', '', body)

        # 3. [qt] [/qt] の単独タグを除去
        body = re.sub(r'\[/?qt\]', '', body)

        # 4. [To:xxx] タグを除去
        body = re.sub(r'\[To:\d+\]\s*[^\n\[]*(?:さん|くん|ちゃん|様|氏)?', '', body)
        body = re.sub(r'\[To:\d+\]', '', body)

        # 5. [piconname:xxx] タグを除去
        body = re.sub(r'\[piconname:\d+\]', '', body)

        # 6. [info]...[/info] タグを除去（内容は残す）
        body = re.sub(r'\[/?info\]', '', body)
        body = re.sub(r'\[/?title\]', '', body)

        # 7. [rp aid=xxx to=xxx-xxx] タグを除去
        body = re.sub(r'\[rp aid=\d+[^\]]*\]', '', body)
        body = re.sub(r'\[/rp\]', '', body)

        # 8. [dtext:xxx] タグを除去
        body = re.sub(r'\[dtext:[^\]]*\]', '', body)

        # 9. [preview ...] タグを除去
        body = re.sub(r'\[preview[^\]]*\]', '', body)
        body = re.sub(r'\[/preview\]', '', body)

        # 10. [code]...[/code] タグを除去（内容は残す）
        body = re.sub(r'\[/?code\]', '', body)

        # 11. [hr] タグを除去
        body = re.sub(r'\[hr\]', '', body)

        # 12. その他の [...] 形式のタグを除去
        body = re.sub(r'\[/?[a-z]+(?::[^\]]+)?\]', '', body, flags=re.IGNORECASE)

        # 13. 連続する改行を整理
        body = re.sub(r'\n{3,}', '\n\n', body)

        # 14. 連続するスペースを整理
        body = re.sub(r' {2,}', ' ', body)

        # 15. 前後の空白を除去
        body = body.strip()

        return body

    except Exception as e:
        print(f"⚠️ clean_task_body_for_summary エラー: {e}")
        return body


def generate_deadline_alert_message(
    task_name: str,
    limit_date,
    days_until: int,
    requester_account_id: str = None,
    requester_name: str = None
) -> str:
    """
    期限が近いタスクのアラートメッセージを生成する

    v10.3.1: カズさんの意図を反映したメッセージに修正
    - 依頼する側の配慮を促す文化づくり
    - 依頼された側が大変にならないように

    v10.3.2: メンション機能追加
    - グループチャットでアラートを送る時、依頼者にメンションをかける

    Args:
        task_name: タスク名
        limit_date: 期限日（date型）
        days_until: 期限までの日数（0=今日, 1=明日）
        requester_account_id: 依頼者のChatWorkアカウントID（メンション用）
        requester_name: 依頼者の名前

    Returns:
        アラートメッセージ文字列
    v10.13.4: 改善
    - タスク名からChatWorkタグを除去
    - 「あなたが依頼した」を明記
    """
    day_label = DEADLINE_ALERT_DAYS.get(days_until, f"{days_until}日後")
    formatted_date = limit_date.strftime("%m/%d")

    # タスク名からChatWorkタグを除去（v10.13.4）
    # ★★★ v10.24.8: prepare_task_display_text()で自然な位置で切る ★★★
    clean_task_name = clean_task_body_for_summary(task_name)
    if not clean_task_name:
        clean_task_name = "（タスク内容なし）"
    else:
        clean_task_name = prepare_task_display_text(clean_task_name, max_length=30)

    # メンション部分を生成（v10.13.4: 「あなたが」に統一）
    mention_line = ""
    if requester_account_id:
        if requester_name:
            mention_line = f"[To:{requester_account_id}] {requester_name}さん\n\n"
        else:
            mention_line = f"[To:{requester_account_id}]\n\n"

    message = f"""{mention_line}⚠️ あなたが依頼した期限が近いタスクだウル！

「{clean_task_name}」の期限が【{formatted_date}（{day_label}）】だウル。

期限が当日・明日だと、依頼された側も大変かもしれないウル。
もし余裕があるなら、期限を少し先に編集してあげてね。

※ 明後日以降ならこのアラートは出ないウル
※ このままでOKなら、何もしなくて大丈夫だウル！"""

    return message


def log_deadline_alert(task_id, room_id: str, account_id: str, limit_date, days_until: int) -> None:
    """
    期限アラートの送信をnotification_logsに記録する

    Args:
        task_id: タスクID
        room_id: ルームID
        account_id: 依頼者のアカウントID
        limit_date: 期限日（date型）
        days_until: 期限までの日数
    """
    try:
        pool = get_pool()
        with pool.begin() as conn:
            # まずテーブルが存在するか確認し、なければ作成
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS notification_logs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID DEFAULT '5f98365f-e7c5-4f48-9918-7fe9aabae5df',
                    notification_type VARCHAR(50) NOT NULL,
                    target_type VARCHAR(50) NOT NULL,
                    target_id TEXT,  -- BIGINTから変更: task_id（数値）とuser_id（UUID）両方対応
                    notification_date DATE NOT NULL,
                    sent_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    status VARCHAR(20) NOT NULL,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    channel VARCHAR(20),
                    channel_target VARCHAR(255),
                    metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    created_by VARCHAR(100),
                    UNIQUE(organization_id, target_type, target_id, notification_date, notification_type)
                )
            """))

            # アラートをログに記録
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO notification_logs (
                        organization_id,
                        notification_type,
                        target_type,
                        target_id,
                        notification_date,
                        sent_at,
                        status,
                        channel,
                        channel_target,
                        metadata
                    ) VALUES (
                        '5f98365f-e7c5-4f48-9918-7fe9aabae5df',
                        'deadline_alert',
                        'task',
                        :task_id,
                        :notification_date,
                        NOW(),
                        'sent',
                        'chatwork',
                        :room_id,
                        :metadata
                    )
                    ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
                    DO UPDATE SET
                        retry_count = notification_logs.retry_count + 1,
                        updated_at = NOW()
                """),
                {
                    "task_id": int(task_id) if task_id else 0,
                    "notification_date": datetime.now(JST).date(),
                    "room_id": str(room_id),
                    "metadata": json.dumps({
                        "room_id": str(room_id),
                        "account_id": str(account_id),
                        "limit_date": limit_date.isoformat() if limit_date else None,
                        "days_until": days_until,
                        "alert_type": "deadline_proximity"
                    }, ensure_ascii=False)
                }
            )
        print(f"📝 期限アラートをログに記録: task_id={task_id}, days_until={days_until}")
    except Exception as e:
        print(f"⚠️ 期限アラートのログ記録に失敗（タスク作成は成功）: {e}")
        # ログ記録失敗してもタスク作成は成功させる（ノンブロッキング）


def handle_chatwork_task_create(params, room_id, account_id, sender_name, context=None):
    """ChatWorkタスク作成を処理（必須項目確認機能付き）"""
    print(f"📝 handle_chatwork_task_create 開始")
    
    assigned_to_name = params.get("assigned_to", "")
    task_body = params.get("task_body", "")
    limit_date = params.get("limit_date")
    limit_time = params.get("limit_time")
    needs_confirmation = params.get("needs_confirmation", False)
    
    print(f"   assigned_to_name: '{assigned_to_name}'")
    print(f"   task_body: '{task_body}'")
    print(f"   limit_date: {limit_date}")
    print(f"   limit_time: {limit_time}")
    print(f"   needs_confirmation: {needs_confirmation}")
    
    
    # 「俺」「自分」「私」の場合は依頼者自身に変換
    if assigned_to_name in ["依頼者自身", "俺", "自分", "私", "僕"]:
        print(f"   → '{assigned_to_name}' を '{sender_name}' に変換")
        assigned_to_name = sender_name
    
    # 必須項目の確認
    missing_items = []
    
    if not task_body or task_body.strip() == "":
        missing_items.append("task_body")
    
    if not assigned_to_name or assigned_to_name.strip() == "":
        missing_items.append("assigned_to")
    
    if not limit_date:
        missing_items.append("limit_date")
    
    # 不足項目がある場合は確認メッセージを返し、pending_taskを保存
    if missing_items:
        # pending_taskを保存
        pending_data = {
            "assigned_to": assigned_to_name,
            "task_body": task_body,
            "limit_date": limit_date,
            "limit_time": limit_time,
            "missing_items": missing_items,
            "sender_name": sender_name
        }
        save_pending_task(room_id, account_id, pending_data)
        
        response = "了解ウル！タスクを作成する前に確認させてウル🐕\n\n"
        
        # 入力済み項目を表示
        if task_body:
            response += f"📝 タスク内容: {task_body}\n"
        else:
            response += "📝 タスク内容: ❓ 未指定\n"
        
        if assigned_to_name:
            response += f"👤 担当者: {assigned_to_name}さん\n"
        else:
            response += "👤 担当者: ❓ 未指定\n"
        
        if limit_date:
            response += f"📅 期限: {limit_date}"
            if limit_time:
                response += f" {limit_time}"
            response += "\n"
        else:
            response += "📅 期限: ❓ 未指定\n"
        
        response += "\n"
        
        # 不足項目を質問
        if "task_body" in missing_items:
            response += "何のタスクか教えてウル！\n"
        elif "assigned_to" in missing_items:
            response += "誰に依頼するか教えてウル！\n"
        elif "limit_date" in missing_items:
            response += "期限はいつにするウル？（例: 12/27、明日、来週金曜日）\n"
        
        return response
    
    # --- 以下、全項目が揃っている場合のタスク作成処理 ---
    
    # pending_taskがあれば削除
    delete_pending_task(room_id, account_id)
    
    assigned_to_account_id = get_chatwork_account_id_by_name(assigned_to_name)
    print(f"👤 担当者ID解決: {assigned_to_name} → {assigned_to_account_id}")
    
    if not assigned_to_account_id:
        error_msg = f"❌ 担当者解決失敗: '{assigned_to_name}' が見つかりません"
        print(error_msg)
        print(f"💡 ヒント: データベースに '{assigned_to_name}' が登録されているか確認してください")
        return f"🤔 {assigned_to_name}さんが見つからなかったウル...\nデータベースに登録されているか確認してほしいウル！"

    # ルームメンバーシップチェック
    if not is_room_member(room_id, assigned_to_account_id):
        print(f"❌ ルームメンバーシップエラー: {assigned_to_name}（ID: {assigned_to_account_id}）はルーム {room_id} のメンバーではありません")
        return f"🤔 {assigned_to_name}さんはこのルームのメンバーじゃないみたいウル...\n{assigned_to_name}さんがいるルームでタスクを作成してほしいウル！"

    limit_timestamp = None
    if limit_date:
        try:
            time_str = limit_time if limit_time else "23:59"
            dt_str = f"{limit_date} {time_str}"
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            jst = timezone(timedelta(hours=9))
            dt_jst = dt.replace(tzinfo=jst)
            limit_timestamp = int(dt_jst.timestamp())
            print(f"期限設定: {dt_str} → {limit_timestamp}")
        except Exception as e:
            print(f"期限の解析エラー: {e}")
    
    print(f"タスク作成開始: room_id={room_id}, assigned_to={assigned_to_account_id}, body={task_body}, limit={limit_timestamp}")
    
    task_data = create_chatwork_task(
        room_id=room_id,
        task_body=task_body,
        assigned_to_account_id=assigned_to_account_id,
        limit=limit_timestamp
    )
    
    if not task_data:
        return "❌ タスクの作成に失敗したウル...\nもう一度試してみてほしいウル！"
    
    # ChatWork APIのレスポンス形式: {"task_ids": [1234]}
    task_ids = task_data.get("task_ids", [])
    if not task_ids:
        print(f"⚠️ 予期しないAPIレスポンス形式: {task_data}")
        return "❌ タスクの作成に失敗したウル...\nもう一度試してみてほしいウル！"
    
    task_id = task_ids[0]
    print(f"✅ ChatWorkタスク作成成功: task_id={task_id}")
    
    # DBに保存（既に持っている情報を使う）
    save_success = save_chatwork_task_to_db(
        task_id=task_id,
        room_id=room_id,
        assigned_by_account_id=account_id,
        assigned_to_account_id=assigned_to_account_id,
        body=task_body,
        limit_time=limit_timestamp
    )
    
    if not save_success:
        print("警告: データベースへの保存に失敗しましたが、ChatWorkタスクは作成されました")
    
    # 分析ログ記録
    log_analytics_event(
        event_type="task_created",
        actor_account_id=account_id,
        actor_name=sender_name,
        room_id=room_id,
        event_data={
            "task_id": task_id,
            "assigned_to": assigned_to_name,
            "assigned_to_account_id": assigned_to_account_id,
            "task_body": task_body,
            "limit_timestamp": limit_timestamp
        }
    )
    
    # 成功メッセージ（既に持っている情報を使う）
    message = f"✅ {assigned_to_name}さんにタスクを作成したウル！🎉\n\n"
    message += f"📝 タスク内容: {task_body}\n"
    message += f"タスクID: {task_id}"

    if limit_timestamp:
        limit_dt = datetime.fromtimestamp(limit_timestamp, tz=timezone(timedelta(hours=9)))
        message += f"\n⏰ 期限: {limit_dt.strftime('%Y年%m月%d日 %H:%M')}"

    # =====================================================
    # v10.3.0: 期限ガードレール
    # =====================================================
    # タスク作成成功後、期限が近すぎる場合はアラートを追加
    # =====================================================
    needs_alert, days_until, parsed_limit_date = check_deadline_proximity(limit_date)

    if needs_alert:
        print(f"⚠️ 期限ガードレール発動: days_until={days_until}")
        alert_message = generate_deadline_alert_message(
            task_name=task_body,
            limit_date=parsed_limit_date,
            days_until=days_until,
            requester_account_id=str(account_id),
            requester_name=sender_name
        )
        message = message + "\n\n" + "─" * 20 + "\n\n" + alert_message

        # アラート送信をログに記録（ノンブロッキング）
        log_deadline_alert(
            task_id=task_id,
            room_id=room_id,
            account_id=account_id,
            limit_date=parsed_limit_date,
            days_until=days_until
        )

    return message


def handle_chatwork_task_complete(params, room_id, account_id, sender_name, context=None):
    """
    タスク完了ハンドラー
    
    contextに recent_tasks_context があれば、番号でタスクを特定できる
    """
    print(f"✅ handle_chatwork_task_complete 開始")
    print(f"   params: {params}")
    print(f"   context: {context}")
    
    task_identifier = params.get("task_identifier", "")
    
    # contextから最近のタスクリストを取得
    recent_tasks = []
    if context and "recent_tasks_context" in context:
        recent_tasks = context.get("recent_tasks_context", [])
    
    # タスクを特定
    target_task = None
    
    # 番号指定の場合（例: "1", "1番", "1のタスク"）
    import re
    number_match = re.search(r'(\d+)', task_identifier)
    if number_match and recent_tasks:
        task_index = int(number_match.group(1)) - 1  # 1-indexed → 0-indexed
        if 0 <= task_index < len(recent_tasks):
            target_task = recent_tasks[task_index]
            print(f"   番号指定でタスク特定: index={task_index}, task={target_task}")
    
    # タスク内容で検索（番号で見つからない場合）
    if not target_task and task_identifier:
        # DBからタスクを検索
        tasks = search_tasks_from_db(room_id, assigned_to_account_id=account_id, status="open")
        for task in tasks:
            if task_identifier.lower() in task["body"].lower():
                target_task = task
                print(f"   内容検索でタスク特定: {target_task}")
                break
    
    if not target_task:
        return f"🤔 どのタスクを完了にするか分からなかったウル...\n「1のタスクを完了」や「資料作成のタスクを完了」のように教えてウル！"
    
    task_id = target_task.get("task_id")
    task_body = target_task.get("body", "")
    
    # ChatWork APIでタスクを完了に
    result = complete_chatwork_task(room_id, task_id)
    
    if result:
        # DBのステータスも更新
        update_task_status_in_db(task_id, "done")
        
        # 分析ログ記録
        log_analytics_event(
            event_type="task_completed",
            actor_account_id=account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "task_id": task_id,
                "task_body": task_body
            }
        )
        
        # ★★★ v10.24.8: prepare_task_display_text()で自然な位置で切る ★★★
        task_display = prepare_task_display_text(clean_chatwork_tags(task_body), max_length=30)
        return f"✅ タスク「{task_display}」を完了にしたウル🎉\nお疲れ様ウル！他にも何か手伝えることがあったら教えてウル🐺✨"
    else:
        return f"❌ タスクの完了に失敗したウル...\nもう一度試してみてほしいウル！"


def handle_chatwork_task_search(params, room_id, account_id, sender_name, context=None):
    """
    タスク検索ハンドラー

    params:
        person_name: 検索する人物名（"sender"の場合は質問者自身）
        status: タスクの状態（open/done/all）
        assigned_by: タスクを依頼した人物名

    v10.22.0: BUG-001修正 - 自分のタスクを検索する場合は全ルームから検索
    """
    print(f"🔍 handle_chatwork_task_search 開始")
    print(f"   params: {params}")

    person_name = params.get("person_name", "")
    status = params.get("status", "open")
    assigned_by = params.get("assigned_by", "")

    # "sender" または "自分" の場合は質問者自身
    # v10.22.0: 自分のタスク検索時は全ルームから検索
    is_self_search = person_name.lower() in ["sender", "自分", "俺", "私", "僕", ""]
    if is_self_search:
        assigned_to_account_id = account_id
        display_name = "あなた"
    else:
        # 名前からaccount_idを取得
        assigned_to_account_id = get_chatwork_account_id_by_name(person_name)
        if not assigned_to_account_id:
            return f"🤔 {person_name}さんが見つからなかったウル...\n正確な名前を教えてほしいウル！"
        display_name = person_name

    # assigned_byの解決
    assigned_by_account_id = None
    if assigned_by:
        assigned_by_account_id = get_chatwork_account_id_by_name(assigned_by)

    # DBからタスクを検索
    # v10.22.0: 自分のタスク検索時は全ルームから検索（BUG-001修正）
    tasks = search_tasks_from_db(
        room_id,
        assigned_to_account_id=assigned_to_account_id,
        assigned_by_account_id=assigned_by_account_id,
        status=status,
        search_all_rooms=is_self_search  # 自分のタスク→全ルーム検索
    )

    if not tasks:
        status_text = "未完了の" if status == "open" else "完了済みの" if status == "done" else ""
        return f"📋 {display_name}の{status_text}タスクは見つからなかったウル！\nタスクがないか、まだ同期されていないかもウル🤔"

    # タスク一覧を作成
    status_text = "未完了" if status == "open" else "完了済み" if status == "done" else "全て"
    response = f"📋 **{display_name}の{status_text}タスク**ウル！\n\n"

    # v10.22.0: 全ルーム検索の場合はルーム別にグループ化
    if is_self_search:
        # ルーム別にグループ化
        tasks_by_room = {}
        for task in tasks:
            room_name = task.get("room_name") or "不明なルーム"
            if room_name not in tasks_by_room:
                tasks_by_room[room_name] = []
            tasks_by_room[room_name].append(task)

        # ルーム別に表示
        task_num = 1
        for room_name, room_tasks in tasks_by_room.items():
            response += f"📁 **{room_name}**\n"
            for task in room_tasks:
                body = task["body"]
                summary = task.get("summary")  # v10.25.0: AI生成の要約を優先
                limit_time = task.get("limit_time")

                # 期限の表示
                limit_str = ""
                if limit_time:
                    try:
                        limit_dt = datetime.fromtimestamp(limit_time, tz=timezone(timedelta(hours=9)))
                        limit_str = f"（期限: {limit_dt.strftime('%m/%d')}）"
                    except:
                        pass

                # v10.27.0: AI生成のsummaryを優先使用（有効な場合のみ）
                body_short = None
                if summary and USE_TEXT_UTILS_LIB:
                    if validate_summary(summary, body):
                        body_short = summary
                    else:
                        print(f"⚠️ summary検証失敗、bodyから生成: task_id={task.get('task_id')}")

                if not body_short:
                    clean_body = clean_chatwork_tags(body)
                    body_short = prepare_task_display_text(clean_body, max_length=40)
                response += f"  {task_num}. {body_short} {limit_str}\n"
                task_num += 1
            response += "\n"
    else:
        # 従来の表示（単一ルーム）
        for i, task in enumerate(tasks, 1):
            body = task["body"]
            summary = task.get("summary")  # v10.25.0: AI生成の要約を優先
            limit_time = task.get("limit_time")

            # 期限の表示
            limit_str = ""
            if limit_time:
                try:
                    limit_dt = datetime.fromtimestamp(limit_time, tz=timezone(timedelta(hours=9)))
                    limit_str = f"（期限: {limit_dt.strftime('%m/%d')}）"
                except:
                    pass

            # v10.27.0: AI生成のsummaryを優先使用（有効な場合のみ）
            body_short = None
            if summary and USE_TEXT_UTILS_LIB:
                if validate_summary(summary, body):
                    body_short = summary
                else:
                    print(f"⚠️ summary検証失敗、bodyから生成: task_id={task.get('task_id')}")

            if not body_short:
                clean_body = clean_chatwork_tags(body)
                body_short = prepare_task_display_text(clean_body, max_length=40)
            response += f"{i}. {body_short} {limit_str}\n"

    response += f"この{len(tasks)}つが{status_text}タスクだよウル！頑張ってねウル💪✨"
    
    # 分析ログ記録
    log_analytics_event(
        event_type="task_searched",
        actor_account_id=account_id,
        actor_name=sender_name,
        room_id=room_id,
        event_data={
            "searched_for": display_name,
            "status": status,
            "result_count": len(tasks)
        }
    )
    
    return response


def handle_pending_task_followup(message, room_id, account_id, sender_name):
    """
    pending_taskがある場合のフォローアップ処理
    
    Returns:
        応答メッセージ（処理した場合）またはNone（pending_taskがない場合）
    """
    pending = get_pending_task(room_id, account_id)
    if not pending:
        return None
    
    print(f"📋 pending_task発見: {pending}")
    
    missing_items = pending.get("missing_items", [])
    assigned_to = pending.get("assigned_to", "")
    task_body = pending.get("task_body", "")
    limit_date = pending.get("limit_date")
    limit_time = pending.get("limit_time")
    
    # 不足項目を補完
    updated = False
    
    # 期限が不足している場合
    if "limit_date" in missing_items:
        parsed_date = parse_date_from_text(message)
        if parsed_date:
            limit_date = parsed_date
            missing_items.remove("limit_date")
            updated = True
            print(f"   → 期限を補完: {parsed_date}")
    
    # タスク内容が不足している場合
    if "task_body" in missing_items and not updated:
        # メッセージ全体をタスク内容として使用
        task_body = message
        missing_items.remove("task_body")
        updated = True
        print(f"   → タスク内容を補完: {task_body}")
    
    # 担当者が不足している場合
    if "assigned_to" in missing_items and not updated:
        # メッセージから名前を抽出（簡易的）
        assigned_to = message.strip()
        missing_items.remove("assigned_to")
        updated = True
        print(f"   → 担当者を補完: {assigned_to}")
    
    if updated:
        # 補完後の情報でタスク作成を再試行
        params = {
            "assigned_to": assigned_to,
            "task_body": task_body,
            "limit_date": limit_date,
            "limit_time": limit_time,
            "needs_confirmation": False
        }
        return handle_chatwork_task_create(params, room_id, account_id, sender_name, None)
    
    # 何も補完できなかった場合
    return None


# =====================================================
# ===== ハンドラー関数（各機能の実行処理） =====
# =====================================================

def resolve_person_name(name):
    """部分的な名前から正式な名前を解決（ユーティリティ関数）"""
    # ★★★ v6.8.6: 名前を正規化してから検索 ★★★
    normalized_name = normalize_person_name(name)
    
    # まず正規化した名前で完全一致を試す
    info = get_person_info(normalized_name)
    if info:
        return normalized_name
    
    # 元の名前で完全一致を試す
    info = get_person_info(name)
    if info:
        return name
    
    # 正規化した名前で部分一致検索
    matches = search_person_by_partial_name(normalized_name)
    if matches:
        return matches[0]
    
    # 元の名前で部分一致検索
    matches = search_person_by_partial_name(name)
    if matches:
        return matches[0]
    
    return name


def parse_attribute_string(attr_str):
    """
    AI司令塔が返す文字列形式のattributeをパースする
    
    入力例: "黒沼 賢人: 部署=広報部, 役職=部長兼戦略設計責任者"
    出力例: [{"person": "黒沼 賢人", "type": "部署", "value": "広報部"}, ...]
    """
    results = []
    
    try:
        # "黒沼 賢人: 部署=広報部, 役職=部長兼戦略設計責任者"
        if ":" in attr_str:
            parts = attr_str.split(":", 1)
            person = parts[0].strip()
            attrs_part = parts[1].strip() if len(parts) > 1 else ""
            
            # "部署=広報部, 役職=部長兼戦略設計責任者"
            for attr_pair in attrs_part.split(","):
                attr_pair = attr_pair.strip()
                if "=" in attr_pair:
                    key_value = attr_pair.split("=", 1)
                    attr_type = key_value[0].strip()
                    attr_value = key_value[1].strip() if len(key_value) > 1 else ""
                    if attr_type and attr_value:
                        results.append({
                            "person": person,
                            "type": attr_type,
                            "value": attr_value
                        })
        else:
            # ":" がない場合（シンプルな形式）
            # 例: "黒沼さんは営業部の部長です" のような形式は想定外
            print(f"   ⚠️ パースできない形式: {attr_str}")
    except Exception as e:
        print(f"   ❌ パースエラー: {e}")
    
    return results


def handle_save_memory(params, room_id, account_id, sender_name, context=None):
    """
    人物情報を記憶するハンドラー（文字列形式と辞書形式の両方に対応）

    v10.25.0: 提案制を追加
    - 管理者（カズさん）からは即時保存
    - 他のスタッフからは提案として記録し、確認後に保存
    """
    print(f"📝 handle_save_memory 開始")
    print(f"   params: {json.dumps(params, ensure_ascii=False)}")

    attributes = params.get("attributes", [])
    print(f"   attributes: {attributes}")

    if not attributes:
        return "🤔 何を覚えればいいかわからなかったウル...もう少し詳しく教えてほしいウル！"

    # v10.25.0: 管理者判定
    is_admin_user = is_admin(account_id)

    saved = []
    proposed = []

    def process_attribute(person, attr_type, attr_value):
        """属性を処理（管理者なら即時保存、それ以外は提案）"""
        if not person or not attr_value:
            return False
        if person.lower() in [bn.lower() for bn in BOT_NAME_PATTERNS]:
            print(f"   → スキップ: ボット名パターンに一致")
            return False

        if is_admin_user:
            # 管理者は即時保存
            save_person_attribute(person, attr_type, attr_value, "command")
            saved.append(f"{person}さんの{attr_type}「{attr_value}」")
            print(f"   → 管理者: 即時保存成功: {person}さんの{attr_type}")
        else:
            # スタッフは提案として記録
            # valueにJSON形式で{type, value}を保存
            proposal_value = json.dumps({"type": attr_type, "value": attr_value}, ensure_ascii=False)
            proposal_id = create_proposal(
                proposed_by_account_id=account_id,
                proposed_by_name=sender_name,
                proposed_in_room_id=room_id,
                category="memory",  # 人物情報用のカテゴリ
                key=person,         # 人物名
                value=proposal_value
            )
            if proposal_id:
                # 管理者に通知（裏で）
                try:
                    # v10.25.0: category='memory'を渡して人物情報用メッセージに
                    report_proposal_to_admin(proposal_id, sender_name, person, proposal_value, category="memory")
                except Exception as e:
                    print(f"⚠️ 管理部への報告エラー: {e}")
                proposed.append(f"{person}さんの{attr_type}「{attr_value}」")
                print(f"   → スタッフ: 提案として記録: {person}さんの{attr_type}, ID={proposal_id}")
        return True

    for attr in attributes:
        print(f"   処理中のattr: {attr} (型: {type(attr).__name__})")

        # ★ 文字列形式の場合はパースする
        if isinstance(attr, str):
            print(f"   → 文字列形式を検出、パース開始")
            parsed_attrs = parse_attribute_string(attr)
            print(f"   → パース結果: {parsed_attrs}")

            for parsed in parsed_attrs:
                person = parsed.get("person", "")
                attr_type = parsed.get("type", "メモ")
                attr_value = parsed.get("value", "")
                print(f"   person='{person}', type='{attr_type}', value='{attr_value}'")
                process_attribute(person, attr_type, attr_value)
            continue

        # ★ 辞書形式の場合は従来通り処理
        if isinstance(attr, dict):
            person = attr.get("person", "")
            attr_type = attr.get("type", "メモ")
            attr_value = attr.get("value", "")
            print(f"   person='{person}', type='{attr_type}', value='{attr_value}'")
            process_attribute(person, attr_type, attr_value)
        else:
            print(f"   ⚠️ 未対応の型: {type(attr).__name__}")

    # 分析ログ記録
    if saved or proposed:
        log_analytics_event(
            event_type="memory_saved" if saved else "memory_proposed",
            actor_account_id=account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "saved_items": saved,
                "proposed_items": proposed,
                "original_params": params
            }
        )

    # レスポンス
    if saved:
        return f"✅ 覚えたウル！📝\n" + "\n".join([f"・{s}" for s in saved])
    elif proposed:
        # v10.25.0: スタッフ向けメッセージ（ソウルくんが確認）
        return f"教えてくれてありがとウル！🐺\n\nソウルくんが会社として問題ないか確認するウル！\n確認できたら覚えるウル！✨\n\n" + "\n".join([f"・{s}" for s in proposed])
    return "🤔 覚えられなかったウル..."


def handle_query_memory(params, room_id, account_id, sender_name, context=None):
    """人物情報を検索するハンドラー"""
    print(f"🔍 handle_query_memory 開始")
    print(f"   params: {params}")
    
    is_all = params.get("is_all_persons", False)
    persons = params.get("persons", [])
    matched = params.get("matched_persons", [])
    original_query = params.get("original_query", "")
    
    print(f"   is_all: {is_all}")
    print(f"   persons: {persons}")
    print(f"   matched: {matched}")
    print(f"   original_query: {original_query}")
    
    if is_all:
        all_persons = get_all_persons_summary()
        if all_persons:
            response = "📋 **覚えている人たち**ウル！🐕✨\n\n"
            for p in all_persons:
                attrs = p["attributes"] if p["attributes"] else "（まだ詳しいことは知らないウル）"
                response += f"・**{p['name']}さん**: {attrs}\n"
            # 分析ログ記録
            log_analytics_event(
                event_type="memory_queried",
                event_subtype="all_persons",
                actor_account_id=account_id,
                actor_name=sender_name,
                room_id=room_id,
                event_data={
                    "query_type": "all",
                    "result_count": len(all_persons)
                }
            )
            return response
        return "🤔 まだ誰のことも覚えていないウル..."
    
    target_persons = matched if matched else persons
    if not target_persons and original_query:
        matches = search_person_by_partial_name(original_query)
        if matches:
            target_persons = matches
    
    if target_persons:
        responses = []
        for person_name in target_persons:
            resolved_name = resolve_person_name(person_name)
            info = get_person_info(resolved_name)
            if info:
                response = f"📋 **{resolved_name}さん**について覚えていることウル！\n\n"
                if info["attributes"]:
                    for attr in info["attributes"]:
                        response += f"・{attr['type']}: {attr['value']}\n"
                else:
                    response += "（まだ詳しいことは知らないウル）"
                responses.append(response)
            else:
                # ★★★ v6.8.6: 正規化した名前でも検索 ★★★
                normalized_name = normalize_person_name(person_name)
                partial_matches = search_person_by_partial_name(normalized_name)
                if partial_matches:
                    for match in partial_matches[:1]:
                        match_info = get_person_info(match)
                        if match_info:
                            response = f"📋 **{match}さん**について覚えていることウル！\n"
                            response += f"（「{person_name}」で検索したウル）\n\n"
                            for attr in match_info["attributes"]:
                                response += f"・{attr['type']}: {attr['value']}\n"
                            responses.append(response)
                            break
                else:
                    responses.append(f"🤔 {person_name}さんについてはまだ何も覚えていないウル...")
        # 分析ログ記録
        log_analytics_event(
            event_type="memory_queried",
            event_subtype="specific_persons",
            actor_account_id=account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "query_type": "specific",
                "queried_persons": target_persons,
                "result_count": len(responses)
            }
        )
        return "\n\n".join(responses)
    
    return None


def handle_delete_memory(params, room_id, account_id, sender_name, context=None):
    """人物情報を削除するハンドラー"""
    persons = params.get("persons", [])
    matched = params.get("matched_persons", persons)
    
    if not persons and not matched:
        return "🤔 誰の記憶を削除すればいいかわからなかったウル..."
    
    target_persons = matched if matched else persons
    resolved_persons = [resolve_person_name(p) for p in target_persons]
    
    deleted = []
    not_found = []
    for person_name in resolved_persons:
        if delete_person(person_name):
            deleted.append(person_name)
        else:
            not_found.append(person_name)
    
    response_parts = []
    if deleted:
        names = "、".join([f"{n}さん" for n in deleted])
        response_parts.append(f"✅ {names}の記憶をすべて削除したウル！🗑️")
    if not_found:
        names = "、".join([f"{n}さん" for n in not_found])
        response_parts.append(f"🤔 {names}の記憶は見つからなかったウル...")
    
    return "\n".join(response_parts) if response_parts else "🤔 削除できなかったウル..."


# =====================================================
# ===== v6.9.0: 管理者学習機能ハンドラー =====
# =====================================================

def handle_learn_knowledge(params, room_id, account_id, sender_name, context=None):
    """
    知識を学習するハンドラー
    - 管理者（カズさん）からは即時反映
    - 他のスタッフからは提案として受け付け、管理部に報告
    v6.9.1: 通知失敗時のメッセージを事実ベースに改善

    v10.24.7: handlers/knowledge_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_knowledge_handler()
    if handler:
        return handler.handle_learn_knowledge(params, room_id, account_id, sender_name, context)

    print("❌ KnowledgeHandler not available - cannot learn knowledge")
    return "ごめんウル...今は知識を覚えられないウル🐺 もう一度試してほしいウル！"


def handle_forget_knowledge(params, room_id, account_id, sender_name, context=None):
    """
    知識を削除するハンドラー
    - 管理者のみ実行可能

    v10.24.7: handlers/knowledge_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_knowledge_handler()
    if handler:
        return handler.handle_forget_knowledge(params, room_id, account_id, sender_name, context)

    print("❌ KnowledgeHandler not available - cannot forget knowledge")
    return "ごめんウル...今は知識を消せないウル🐺 もう一度試してほしいウル！"


def handle_list_knowledge(params, room_id, account_id, sender_name, context=None):
    """
    学習した知識の一覧を表示するハンドラー

    v10.24.7: handlers/knowledge_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    v10.40.9: メモリ分離対応（ボットペルソナと業務知識を分離表示）
    """
    lines = ["**覚えていること**ウル！🐺✨\n"]
    total_count = 0

    # v10.40.9: ボットペルソナ設定を先に表示
    if USE_BOT_PERSONA_MEMORY:
        try:
            pool = get_pool()
            # 組織IDを取得
            with pool.connect() as conn:
                user_result = conn.execute(
                    sqlalchemy.text("""
                        SELECT organization_id FROM users
                        WHERE chatwork_account_id = :account_id
                        LIMIT 1
                    """),
                    {"account_id": str(account_id)}
                ).fetchone()

                if user_result and user_result[0]:
                    org_id = str(user_result[0])
                else:
                    # デフォルト組織を取得
                    org_result = conn.execute(
                        sqlalchemy.text("SELECT id FROM organizations LIMIT 1")
                    ).fetchone()
                    org_id = str(org_result[0]) if org_result else None

            if org_id:
                manager = BotPersonaMemoryManager(pool, org_id)
                persona_settings = manager.get_all()

                if persona_settings:
                    lines.append("\n**🐺 ソウルくんの設定**")
                    for s in persona_settings:
                        lines.append(f"・{s['key']}: {s['value']}")
                    total_count += len(persona_settings)
        except Exception as e:
            print(f"⚠️ ボットペルソナ取得エラー: {e}")

    # 業務知識（soulkun_knowledge）を表示
    handler = _get_knowledge_handler()
    if handler:
        knowledge_list = handler.get_all_knowledge()

        if knowledge_list:
            # カテゴリごとにグループ化（characterは除外 - bot_persona_memoryに移行済み）
            by_category = {}
            for k in knowledge_list:
                cat = k["category"]
                # v10.40.9: characterカテゴリは除外（bot_persona_memoryに移行）
                if cat == "character":
                    continue
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(f"・{k['key']}: {k['value']}")

            # 整形
            category_names = {
                "rules": "📋 業務ルール",
                "members": "👥 社員情報",
                "other": "📝 その他"
            }

            for cat, items in by_category.items():
                cat_name = category_names.get(cat, f"📁 {cat}")
                lines.append(f"\n**{cat_name}**")
                lines.extend(items)
                total_count += len(items)

    if total_count == 0:
        return "まだ何も覚えてないウル！🐺\n\n「設定：〇〇は△△」と教えてくれたら覚えるウル！"

    lines.append(f"\n\n合計 {total_count} 件覚えてるウル！")
    return "\n".join(lines)


def handle_proposal_decision(params, room_id, account_id, sender_name, context=None):
    """
    提案の承認/却下を処理するハンドラー（AI司令塔経由）
    - 管理者のみ有効
    - 管理部ルームでの発言のみ対応
    v6.9.1: ID指定方式を推奨（handle_proposal_by_idを使用）

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.handle_proposal_decision(params, room_id, account_id, sender_name, context)

    print("❌ ProposalHandler not available - cannot handle proposal decision")
    return "ごめんウル...今は提案を処理できないウル🐺 もう一度試してほしいウル！"


# =====================================================
# v6.9.1: ローカルコマンド用ハンドラー
# =====================================================
# AI司令塔を呼ばずに直接処理するコマンド用
# =====================================================

def handle_proposal_by_id(proposal_id: int, decision: str, account_id: str, sender_name: str, room_id: str):
    """
    ID指定で提案を承認/却下（v6.9.1追加）
    ローカルコマンド「承認 123」「却下 123」用

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.handle_proposal_by_id(proposal_id, decision, account_id, sender_name, room_id)

    print("❌ ProposalHandler not available - cannot handle proposal by ID")
    return "ごめんウル...今は提案を処理できないウル🐺 もう一度試してほしいウル！"


def handle_list_pending_proposals(room_id: str, account_id: str):
    """
    承認待ち提案の一覧を表示（v6.9.1追加）
    ローカルコマンド「承認待ち一覧」用
    """
    # 管理部ルームかチェック
    if str(room_id) != str(ADMIN_ROOM_ID):
        return "🤔 承認待ち一覧は管理部ルームで確認してウル！"
    
    proposals = get_pending_proposals()
    
    if not proposals:
        return "✨ 承認待ちの提案は今ないウル！スッキリ！🐺"
    
    lines = [f"📋 **承認待ちの提案一覧**（{len(proposals)}件）ウル！🐺\n"]
    
    for p in proposals:
        created = p["created_at"].strftime("%m/%d %H:%M") if p.get("created_at") else "不明"
        lines.append(f"・**ID={p['id']}** 「{p['key']}: {p['value']}」")
        lines.append(f"  └ 提案者: {p['proposed_by_name']}さん（{created}）")
    
    lines.append("\n---")
    lines.append("「承認 ID番号」または「却下 ID番号」で処理できるウル！")
    lines.append("例：「承認 1」「却下 2」")
    
    return "\n".join(lines)


def handle_local_learn_knowledge(key: str, value: str, account_id: str, sender_name: str, room_id: str):
    """
    ローカルコマンドによる知識学習（v6.9.1追加）
    「設定：キー=値」形式で呼ばれる

    v10.24.7: handlers/knowledge_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_knowledge_handler()
    if handler:
        return handler.handle_local_learn_knowledge(key, value, account_id, sender_name, room_id)

    print("❌ KnowledgeHandler not available - cannot learn knowledge locally")
    return "ごめんウル...今は知識を覚えられないウル🐺 もう一度試してほしいウル！"


# =====================================================
# v6.9.2: 未通知提案の一覧・再通知ハンドラー
# =====================================================

def handle_list_unnotified_proposals(room_id: str, account_id: str):
    """
    通知失敗した提案の一覧を表示（v6.9.2追加）
    管理者のみ閲覧可能
    """
    # 管理者判定
    if not is_admin(account_id):
        return "🙏 未通知提案の確認は菊地さんだけができるウル！"
    
    proposals = get_unnotified_proposals()
    
    if not proposals:
        return "✨ 通知失敗した提案はないウル！全部ちゃんと届いてるウル！🐺"
    
    lines = [f"⚠️ **通知失敗した提案一覧**（{len(proposals)}件）ウル！🐺\n"]
    
    for p in proposals:
        created = p["created_at"].strftime("%m/%d %H:%M") if p.get("created_at") else "不明"
        lines.append(f"・**ID={p['id']}** 「{p['key']}: {p['value']}」")
        lines.append(f"  └ 提案者: {p['proposed_by_name']}さん（{created}）")
    
    lines.append("\n---")
    lines.append("「再通知 ID番号」で再送できるウル！")
    lines.append("例：「再通知 1」「再送 2」")
    
    return "\n".join(lines)


def handle_retry_notification(proposal_id: int, room_id: str, account_id: str):
    """
    提案の通知を再送（v6.9.2追加）
    管理者のみ実行可能
    """
    # 管理者判定
    if not is_admin(account_id):
        return "🙏 再通知は菊地さんだけができるウル！"
    
    success, message = retry_proposal_notification(proposal_id)
    
    if success:
        return f"✅ 再通知したウル！🐺\n\n{message}\n管理部に届いたはずウル！"
    else:
        return f"😢 再通知に失敗したウル...\n\n{message}"


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
        if delete_knowledge(key=key):
            return f"忘れたウル！🐺\n\n🗑️ 「{key}」の設定を削除したウル！"
        else:
            return f"🤔 「{key}」という設定は見つからなかったウル..."
    
    elif action == "list_knowledge":
        return handle_list_knowledge({}, room_id, account_id, sender_name, None)
    
    return None  # マッチしなかった場合はAI司令塔に委ねる


def report_proposal_to_admin(proposal_id: int, proposer_name: str, key: str, value: str, category: str = None):
    """
    提案を管理部に報告
    v6.9.1: ID表示、admin_notifiedフラグ更新
    v10.25.0: category='memory'の場合は人物情報用メッセージ

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.report_proposal_to_admin(proposal_id, proposer_name, key, value, category)

    print("❌ ProposalHandler not available - cannot report proposal to admin")
    return False


# v10.33.0: notify_proposal_result は handlers/proposal_handler.py に移行済み（未使用のため削除）


def handle_query_org_chart(params, room_id, account_id, sender_name, context=None):
    """組織図クエリのハンドラー（Phase 3.5）"""
    query_type = params.get("query_type", "overview")
    department = params.get("department", "")

    if query_type == "overview":
        # 組織図の全体構造を表示
        departments = get_org_chart_overview()
        if not departments:
            return "🤔 組織図データがまだ登録されていないウル..."

        # 階層構造で表示
        response = "🏢 **組織図**ウル！\n\n"

        for dept in departments:
            level = dept["level"]
            indent = "　" * (level - 1)
            member_info = f"（{dept['member_count']}名）" if dept["member_count"] > 0 else ""
            response += f"{indent}📁 {dept['name']}{member_info}\n"

        response += f"\n合計: {len(departments)}部署"
        return response

    elif query_type == "members":
        # 部署のメンバー一覧
        if not department:
            return "🤔 どの部署のメンバーを知りたいウル？部署名を教えてほしいウル！"

        dept_name, members = get_department_members(department)
        if dept_name is None:
            return f"🤔 「{department}」という部署が見つからなかったウル..."

        if not members:
            return f"📁 **{dept_name}** には現在メンバーがいないウル"

        response = f"👥 **{dept_name}のメンバー**ウル！\n\n"
        for m in members:
            concurrent_mark = "【兼】" if m.get("is_concurrent") else ""
            position_str = f"（{m['position']}）" if m.get("position") else ""
            emp_type_str = f" [{m['employment_type']}]" if m.get("employment_type") else ""
            response += f"・{concurrent_mark}{m['name']}{position_str}{emp_type_str}\n"

        response += f"\n合計: {len(members)}名"
        return response

    elif query_type == "detail":
        # 部署の詳細情報
        if not department:
            return "🤔 どの部署の詳細を知りたいウル？部署名を教えてほしいウル！"

        depts = search_department_by_name(department)
        if not depts:
            return f"🤔 「{department}」という部署が見つからなかったウル..."

        dept = depts[0]
        dept_name, members = get_department_members(dept["name"])

        response = f"📁 **{dept['name']}** の詳細ウル！\n\n"
        response += f"・階層レベル: {dept['level']}\n"
        response += f"・所属人数: {dept['member_count']}名\n"

        if members:
            response += f"\n👥 **メンバー**:\n"
            for m in members[:10]:  # 最大10名まで表示
                concurrent_mark = "【兼】" if m.get("is_concurrent") else ""
                position_str = f"（{m['position']}）" if m.get("position") else ""
                response += f"　・{concurrent_mark}{m['name']}{position_str}\n"
            if len(members) > 10:
                response += f"　...他{len(members) - 10}名"

        return response

    return "🤔 組織図の検索方法がわからなかったウル..."


def handle_general_chat(params, room_id, account_id, sender_name, context=None):
    """一般会話のハンドラー（execute_actionからNoneを返して後続処理に委ねる）"""
    # 一般会話は別のフローで処理するのでNoneを返す
    return None


def handle_api_limitation(params, room_id, account_id, sender_name, context=None):
    """
    API制約により実装不可能な機能を要求された時のハンドラー
    
    ChatWork APIの制約により、タスクの編集・削除は実装できない。
    ユーザーに適切な説明を返す。
    """
    # contextからどの機能が呼ばれたか特定
    action = context.get("action", "") if context else ""
    
    # 機能カタログからメッセージを取得
    capability = SYSTEM_CAPABILITIES.get(action, {})
    limitation_message = capability.get("limitation_message", "この機能")
    
    # ソウルくんキャラクターで説明
    response = f"""ごめんウル！🐺

{limitation_message}は、ChatWorkの仕様でソウルくんからはできないウル…

【ソウルくんができること】
✅ タスクの作成（「〇〇さんに△△をお願いして」）
✅ タスクの完了（「〇〇のタスク完了にして」）
✅ タスクの検索（「自分のタスク教えて」）
✅ リマインド（期限前に自動でお知らせ）
✅ 遅延管理（期限超過タスクを管理部に報告）

【{limitation_message}が必要な場合】
ChatWorkアプリで直接操作してほしいウル！
タスクを開いて、編集や削除ができるウル🐺

もし「このタスクのリマインドだけ止めて」ならソウルくんでできるウル！"""
    
    return response


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
def handle_query_company_knowledge(params, room_id, account_id, sender_name, context=None):
    """
    会社知識の参照ハンドラー（Phase 3統合版）

    統合ナレッジ検索を使用して、就業規則・マニュアル等から回答を生成する。
    旧システム（soulkun_knowledge）とPhase 3（Pinecone）を自動的に切り替え。

    Args:
        params: {"query": "検索したい内容"}
        room_id: ChatWorkルームID
        account_id: ユーザーのアカウントID
        sender_name: 送信者名
        context: コンテキスト情報

    Returns:
        回答テキスト

    v10.24.7: handlers/knowledge_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_knowledge_handler()
    if handler:
        return handler.handle_query_company_knowledge(params, room_id, account_id, sender_name, context)

    print("❌ KnowledgeHandler not available - cannot query company knowledge")
    return "ごめんウル...今はナレッジ検索ができないウル🐺 もう一度試してほしいウル！"


def call_openrouter_api(system_prompt: str, user_message: str, model: str = None):
    """
    OpenRouter APIを呼び出してLLM応答を取得

    Args:
        system_prompt: システムプロンプト
        user_message: ユーザーメッセージ
        model: 使用するモデル

    Returns:
        LLMの応答テキスト（エラー時はNone）
    """
    try:
        api_key = get_secret("openrouter-api-key")
        if not api_key:
            print("❌ OpenRouter APIキーが見つかりません")
            return None

        model = model or MODELS["default"]

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://soulkun.soulsyncs.co.jp",
                    "X-Title": "Soul-kun ChatWork Bot"
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1000
                }
            )

            if response.status_code != 200:
                print(f"❌ OpenRouter API エラー: {response.status_code} - {response.text}")
                return None

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content.strip() if content else None

    except Exception as e:
        print(f"❌ OpenRouter API 呼び出しエラー: {e}")
        traceback.print_exc()
        return None


# =====  =====
def handle_daily_reflection(params, room_id, account_id, sender_name, context=None):
    """daily_reflection_logs"""
    print(f"handle_daily_reflection : room_id={room_id}, account_id={account_id}")
    
    try:
        reflection_text = params.get("reflection_text", "")
        if not reflection_text:
            return {"success": False, "message": "..."}
        
        from datetime import datetime
        from sqlalchemy import text
        
        conn = get_db_connection()
        if not conn:
            return {"success": False, "message": "..."}
        
        try:
            insert_query = text("""
                INSERT INTO daily_reflection_logs 
                (account_id, recorded_at, reflection_text, room_id, message_id, created_at)
                VALUES (:account_id, :recorded_at, :reflection_text, :room_id, :message_id, NOW())
            """)
            
            conn.execute(insert_query, {
                "account_id": str(account_id),
                "recorded_at": datetime.now().date(),
                "reflection_text": reflection_text,
                "room_id": str(room_id),
                "message_id": context.get("message_id", "") if context else ""
            })
            conn.commit()
            
            print(f": account_id={account_id}")
            return {"success": True, "message": "\n"}
            
        finally:
            conn.close()
            
    except Exception as e:
        print(f"handle_daily_reflection : {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "message": "..."}


# =====================================================
# ===== Phase 2.5: 目標達成支援ハンドラー =====
# =====================================================
# v10.24.6: handlers/goal_handler.py に分割

def handle_goal_registration(params, room_id, account_id, sender_name, context=None):
    """
    目標登録ハンドラー（Phase 2.5 v1.6）

    v10.19.0: WHY→WHAT→HOW の一問一答形式の目標設定対話を開始。
    具体的なgoal_titleがある場合は直接登録（後方互換性維持）。

    アチーブメント社・選択理論に基づく目標設定支援。

    v10.24.6: handlers/goal_handler.py に分割
    """
    # v10.32.0: ハンドラー必須化（フォールバック削除）
    handler = _get_goal_handler()
    if handler:
        return handler.handle_goal_registration(params, room_id, account_id, sender_name, context)

    print("❌ GoalHandler not available - cannot register goal")
    return {
        "success": False,
        "message": "ごめんウル...今は目標を登録できないウル🐺 もう一度試してほしいウル！"
    }


def handle_goal_progress_report(params, room_id, account_id, sender_name, context=None):
    """
    目標進捗報告ハンドラー（Phase 2.5）

    goal_progress テーブルに進捗を記録する。

    v10.24.6: handlers/goal_handler.py に分割
    """
    # v10.32.0: ハンドラー必須化（フォールバック削除）
    handler = _get_goal_handler()
    if handler:
        return handler.handle_goal_progress_report(params, room_id, account_id, sender_name, context)

    print("❌ GoalHandler not available - cannot report progress")
    return {
        "success": False,
        "message": "ごめんウル...今は進捗を記録できないウル🐺 もう一度試してほしいウル！"
    }


def handle_goal_status_check(params, room_id, account_id, sender_name, context=None):
    """
    目標確認ハンドラー（Phase 2.5）

    現在の目標と進捗状況を返す。

    v10.24.6: handlers/goal_handler.py に分割
    """
    # v10.32.0: ハンドラー必須化（フォールバック削除）
    handler = _get_goal_handler()
    if handler:
        return handler.handle_goal_status_check(params, room_id, account_id, sender_name, context)

    print("❌ GoalHandler not available - cannot check status")
    return {
        "success": False,
        "message": "ごめんウル...今は目標を確認できないウル🐺 もう一度試してほしいウル！"
    }


HANDLERS = {
    "handle_chatwork_task_create": handle_chatwork_task_create,
    "handle_chatwork_task_complete": handle_chatwork_task_complete,
    "handle_chatwork_task_search": handle_chatwork_task_search,
    "handle_daily_reflection": handle_daily_reflection,
    "handle_save_memory": handle_save_memory,
    "handle_query_memory": handle_query_memory,
    "handle_delete_memory": handle_delete_memory,
    "handle_general_chat": handle_general_chat,
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
    # v10.26.0: アナウンス機能
    "handle_announcement_request": lambda params, room_id, account_id, sender_name, context=None: (
        _get_announcement_handler().handle_announcement_request(
            params, room_id, account_id, sender_name, context
        ) if _get_announcement_handler() else "🚫 アナウンス機能は現在利用できませんウル"
    ),
}


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

    v10.24.3: handlers/memory_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_memory_handler()
    if handler:
        return handler.get_conversation_history(room_id, account_id)

    print("❌ MemoryHandler not available - cannot get conversation history")
    return []

def save_conversation_history(room_id, account_id, history):
    """
    会話履歴を保存

    v10.24.3: handlers/memory_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_memory_handler()
    if handler:
        return handler.save_conversation_history(room_id, account_id, history)

    print("❌ MemoryHandler not available - cannot save conversation history")


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

    B1: 会話サマリー - 会話が10件以上溜まったらサマリーを生成
    B2: ユーザー嗜好 - 会話パターンからユーザーの好みを学習
    B4: 会話検索 - 会話をインデックス化（検索可能に）

    v10.24.3: handlers/memory_handler.py に分割

    Args:
        room_id: ChatWorkルームID
        account_id: ユーザーのChatWorkアカウントID
        sender_name: 送信者名
        user_message: ユーザーのメッセージ
        ai_response: AIの応答
        history: 会話履歴

    Note:
        - エラーが発生しても会話処理には影響を与えない
        - 会話数が閾値未満の場合は何もしない（負荷軽減）
    """
    # v10.32.0: ハンドラー必須化（フォールバック削除）
    handler = _get_memory_handler()
    if handler:
        return handler.process_memory_after_conversation(
            room_id, account_id, sender_name, user_message, ai_response, history
        )

    print("❌ MemoryHandler not available - cannot process memory")


# ===== AI司令塔（AIの判断力を最大活用する設計） =====

def ai_commander(message, all_persons, all_tasks, chatwork_users=None, sender_name=None):
    """
    ユーザーのメッセージを解析し、適切なアクションを判断
    
    【設計思想】
    - 機能カタログ(SYSTEM_CAPABILITIES)からプロンプトを動的生成
    - AIにシステムの全情報を渡し、AIが自分で判断する
    - 新機能追加時はカタログに追加するだけでAIが認識
    """
    api_key = get_secret("openrouter-api-key")
    
    # ChatWorkユーザー一覧（なければ取得）
    if chatwork_users is None:
        chatwork_users = get_all_chatwork_users()
    
    # 各コンテキストを文字列化
    users_context = ""
    if chatwork_users:
        users_list = [f"- {u['name']}" for u in chatwork_users]
        users_context = "\n".join(users_list)
    
    persons_context = ""
    if all_persons:
        persons_list = [f"- {p['name']}: {p['attributes']}" for p in all_persons[:20]]
        persons_context = "\n".join(persons_list)
    
    tasks_context = ""
    if all_tasks:
        tasks_list = [f"- ID:{t[0]} {t[1]} [{t[2]}]" for t in all_tasks[:10]]
        tasks_context = "\n".join(tasks_list)
    
    # ★ v6.9.0: 学習済みの知識を取得
    knowledge_context = ""
    try:
        knowledge_context = get_knowledge_for_prompt()
    except Exception as e:
        print(f"⚠️ 知識取得エラー（続行）: {e}")
    
    # ★ 機能カタログからアクション一覧を動的生成
    capabilities_prompt = generate_capabilities_prompt(SYSTEM_CAPABILITIES, chatwork_users, sender_name)
    
    # 有効なアクション名の一覧
    enabled_actions = list(get_enabled_capabilities().keys())
    
    system_prompt = f"""あなたは「ソウルくん」のAI司令塔です。

【あなたの役割】
ユーザーのメッセージを理解し、以下のシステム情報と機能一覧を考慮して、
システムが正しく実行できるアクションとパラメータを出力すること。

★ 重要: あなたはAIとしての判断力を最大限に発揮してください。
ユーザーは様々な言い方をします（敬称あり/なし、フルネーム/名前だけ、ニックネームなど）。
あなたの仕事は、ユーザーの意図を汲み取り、システムが動く形式に変換することです。

=======================================================
【システム情報】
=======================================================

【1. ChatWorkユーザー一覧】（タスク担当者として指定可能な人）
{users_context if users_context else "（ユーザー情報なし）"}

【2. 記憶している人物情報】
{persons_context if persons_context else "（まだ誰も記憶していません）"}

【2.5. ソウルくんが学習した知識】
{knowledge_context if knowledge_context else "（まだ学習した知識はありません）"}

【3. 現在のタスク】
{tasks_context if tasks_context else "（タスクはありません）"}

【4. 今話しかけてきた人】
{sender_name if sender_name else "（不明）"}

【5. 今日の日付】
{datetime.now(JST).strftime("%Y-%m-%d")}（{datetime.now(JST).strftime("%A")}）

=======================================================
【最重要：担当者名の解決ルール】
=======================================================

ユーザーがタスクの担当者を指定する際、様々な言い方をします。
あなたは【ChatWorkユーザー一覧】から該当する人を見つけて、
【正確な名前をコピー】して出力してください。

例：
- 「崇樹」「崇樹くん」「崇樹さん」「上野」「上野さん」
  → 一覧から「上野 崇樹」を見つけて「上野 崇樹」と出力
  
- 「黒沼」「黒沼さん」「黒沼くん」「賢人」
  → 一覧から「黒沼 賢人」を見つけて「黒沼 賢人」と出力
  
- 「俺」「自分」「私」「僕」
  → 「依頼者自身」と出力（システムが送信者の名前に変換します）

★ assigned_to には【必ず】ChatWorkユーザー一覧の名前を正確にコピーして出力すること
★ リストにない名前を勝手に作成しないこと
★ 敬称は除去してリストの正式名で出力すること

=======================================================
【使用可能な機能一覧】
=======================================================
{capabilities_prompt}

=======================================================
【言語検出】
=======================================================
ユーザーのメッセージの言語を検出し、response_language に記録してください。
対応: ja(日本語), en(英語), zh(中国語), ko(韓国語), es(スペイン語), fr(フランス語), de(ドイツ語), other

=======================================================
【出力形式】
=======================================================
必ず以下のJSON形式で出力してください：

{{
  "action": "アクション名（{', '.join(enabled_actions)} のいずれか）",
  "confidence": 0.0-1.0,
  "reasoning": "この判断をした理由（日本語で簡潔に）",
  "response_language": "言語コード",
  "params": {{
    // アクションに応じたパラメータ
  }}
}}

=======================================================
【判断の優先順位】
=======================================================
★★★ 重要：「タスク」という言葉があれば、まずタスク系の機能を検討 ★★★

1. タスク完了のキーワード（完了/終わった/done/済み/クリア）があれば → chatwork_task_complete
2. タスク検索のキーワード（〇〇のタスク/タスク教えて/タスク一覧/抱えているタスク）があれば → chatwork_task_search
3. タスク作成のキーワード（追加/作成/依頼/お願い/振って）があれば → chatwork_task_create
4. 人物情報を教えてくれていれば（〇〇さんは△△です）→ save_memory
5. 人物について質問していれば（〇〇さんについて/〇〇さんのこと）→ query_memory
   ★ ただし「〇〇のタスク」の場合は2の chatwork_task_search を優先
6. 忘れてほしいと言われていれば → delete_memory
7. ★★★ 会社のルール・規則・制度に関する質問 → query_company_knowledge ★★★
   - 有給休暇、年休、休暇に関する質問
   - 就業規則、社内ルールに関する質問
   - 経費精算、各種手続きに関する質問
   - 会社の制度、福利厚生に関する質問
   - 「何日？」「どうやって？」「ルールは？」のような制度への質問
8. ★★★ 目標に関する発言 → goal系アクション ★★★
   - 「今日は〇〇した」「今日〇〇円売り上げた」「今日〇〇件達成」など進捗報告 → goal_progress_report
   - 「目標を設定したい」「目標を登録したい」「KPIを設定」など目標設定 → goal_registration
   - 「目標の進捗は？」「達成率を教えて」など目標確認 → goal_status_check
   ★★★ 特に数値＋売上/件数/達成などの組み合わせは goal_progress_report を優先 ★★★
9. それ以外 → general_chat

【具体例】
- 「崇樹のタスク教えて」→ chatwork_task_search（タスク検索）
- 「崇樹について教えて」→ query_memory（人物情報検索）
- 「1のタスク完了にして」→ chatwork_task_complete（タスク完了）
- 「崇樹にタスク追加して」→ chatwork_task_create（タスク作成）
- 「有給休暇は何日？」→ query_company_knowledge（会社知識検索）
- 「経費精算のルールは？」→ query_company_knowledge（会社知識検索）
- 「就業規則を教えて」→ query_company_knowledge（会社知識検索）
- 「今日は25万売り上げた」→ goal_progress_report（目標進捗報告）★★★
- 「今日10件成約した」→ goal_progress_report（目標進捗報告）★★★
- 「今日の売上は50万円」→ goal_progress_report（目標進捗報告）★★★
- 「目標を設定したい」→ goal_registration（目標登録）
- 「目標の進捗を教えて」→ goal_status_check（目標確認）"""

    try:
        response = httpx.post(
            OPENROUTER_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": MODELS["commander"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"以下のメッセージを解析してください：\n\n「{message}」"}
                ],
                "max_tokens": 800,
                "temperature": 0.1,
            },
            timeout=20.0
        )
        
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                result = json.loads(json_match.group())
                # AI司令塔の判断結果を詳細にログ出力
                print("=" * 50)
                print(f"🤖 AI司令塔の判断結果:")
                print(f"   アクション: {result.get('action')}")
                print(f"   信頼度: {result.get('confidence')}")
                print(f"   理由: {result.get('reasoning')}")
                print(f"   パラメータ: {json.dumps(result.get('params', {}), ensure_ascii=False)}")
                print("=" * 50)
                return result
    except Exception as e:
        print(f"AI司令塔エラー: {e}")
    
    return {"action": "general_chat", "confidence": 0.5, "reasoning": "解析失敗", "response_language": "ja", "params": {}}

def execute_action(command, sender_name, room_id=None, account_id=None, context=None):
    """
    AI司令塔の判断に基づいてアクションを動的に実行
    
    【設計思想】
    - SYSTEM_CAPABILITIESからアクション情報を取得
    - HANDLERSから対応するハンドラー関数を取得して実行
    - カタログにないアクションはフォールバック処理
    """
    action = command.get("action", "general_chat")
    params = command.get("params", {})
    reasoning = command.get("reasoning", "")
    
    print(f"⚙️ execute_action 開始:")
    print(f"   アクション: {action}")
    print(f"   送信者: {sender_name}")
    print(f"   パラメータ: {json.dumps(params, ensure_ascii=False)}")
    
    # =====================================================
    # カタログベースの動的実行
    # =====================================================
    
    # カタログから機能情報を取得
    capability = SYSTEM_CAPABILITIES.get(action)
    
    if capability:
        # 機能が無効化されていないかチェック
        if not capability.get("enabled", True):
            print(f"⚠️ 機能 '{action}' は現在無効です")
            return "🤔 その機能は現在利用できないウル..."
        
        # ハンドラー名を取得
        handler_name = capability.get("handler")
        
        # HANDLERSからハンドラー関数を取得
        handler = HANDLERS.get(handler_name)
        
        if handler:
            print(f"✅ ハンドラー '{handler_name}' を実行")
            try:
                # contextにactionを追加（API制約ハンドラー用）
                if context is None:
                    context = {}
                context["action"] = action
                result = handler(params, room_id, account_id, sender_name, context)
                # dictが返された場合はmessageキーを取り出す（goal系ハンドラー対応）
                if isinstance(result, dict):
                    return result.get("message", "🤔 応答の生成に失敗したウル...")
                return result
            except Exception as e:
                print(f"❌ ハンドラー実行エラー: {e}")
                return "🤔 処理中にエラーが発生したウル...もう一度試してほしいウル！"
        else:
            print(f"⚠️ ハンドラー '{handler_name}' が見つかりません")
    
    # =====================================================
    # フォールバック処理（レガシーアクション用）
    # =====================================================
    
    if action == "add_task":
        task_title = params.get("task_title", "")
        if task_title:
            task_id = add_task(task_title)
            return f"✅ タスクを追加したウル！📝\nID: {task_id}\nタイトル: {task_title}"
        return "🤔 何をタスクにすればいいかわからなかったウル..."
    
    elif action == "list_tasks":
        tasks = get_tasks()
        if tasks:
            response = "📋 **タスク一覧**ウル！\n\n"
            for task in tasks:
                status_emoji = "✅" if task[2] == "completed" else "📝"
                response += f"{status_emoji} ID:{task[0]} - {task[1]} [{task[2]}]\n"
            return response
        return "📋 タスクはまだないウル！"
    
    elif action == "complete_task":
        task_id = params.get("task_id")
        if task_id:
            try:
                update_task_status(int(task_id), "completed")
                return f"✅ タスク ID:{task_id} を完了にしたウル！🎉"
            except:
                pass
        return "🤔 どのタスクを完了にすればいいかわからなかったウル..."
    
    elif action == "delete_task":
        task_id = params.get("task_id")
        if task_id:
            try:
                delete_task(int(task_id))
                return f"🗑️ タスク ID:{task_id} を削除したウル！"
            except:
                pass
        return "🤔 どのタスクを削除すればいいかわからなかったウル..."
    
    return None

# ===== 多言語対応のAI応答生成（NEW） =====

def get_ai_response(message, history, sender_name, context=None, response_language="ja"):
    """通常会話用のAI応答生成（多言語対応 + 組織論的行動指針）"""
    api_key = get_secret("openrouter-api-key")

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
    
    # 指定された言語のプロンプトを使用（デフォルトは日本語）
    system_prompt = language_prompts.get(response_language, language_prompts["ja"])
    
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
        # バイパスハンドラーは _build_bypass_handlers() で定義
        # =====================================================

        # =====================================================
        # v10.29.0: 脳アーキテクチャ（BrainIntegration経由）
        # USE_BRAIN_ARCHITECTURE で制御:
        #   - false: 無効（従来フロー）
        #   - true/enabled: 有効（脳で処理、エラー時フォールバック）
        #   - shadow: シャドウモード（新旧並列実行、旧結果を返却）
        #   - gradual: 段階的ロールアウト（一部ユーザーのみ脳）
        # =====================================================
        if USE_BRAIN_ARCHITECTURE:
            try:
                integration = _get_brain_integration()
                if integration and integration.is_brain_enabled():
                    mode = integration.get_mode().value
                    print(f"🧠 脳アーキテクチャで処理開始: mode={mode}")

                    # バイパスコンテキストとハンドラーを構築
                    bypass_context = _build_bypass_context(room_id, sender_account_id)
                    bypass_handlers = _build_bypass_handlers()

                    # フォールバック関数（従来のai_commander + execute_action + get_ai_response）
                    async def fallback_ai_commander(msg, r_id, a_id, s_name):
                        """従来のAI司令塔フロー"""
                        try:
                            # コンテキスト準備（フォールバック用に簡易版）
                            # Note: get_all_persons_summary()は要約版を返す
                            fb_all_persons = get_all_persons_summary()
                            # BUG-017修正: account_id → assigned_to_account_id, limit引数削除
                            fb_all_tasks = search_tasks_from_db(room_id=r_id, assigned_to_account_id=a_id)
                            fb_chatwork_users = get_all_chatwork_users()
                            fb_conversation_history = get_conversation_history(r_id, a_id)
                            fb_context = {}

                            # AI司令塔
                            command = ai_commander(msg, fb_all_persons, fb_all_tasks, fb_chatwork_users, s_name)

                            # アクション実行
                            if command and hasattr(command, 'action') and command.action != "general_chat":
                                result = execute_action(command, s_name, r_id, a_id, fb_context)
                                return result
                            else:
                                # 通常会話
                                return get_ai_response(msg, fb_conversation_history, s_name, fb_context)
                        except Exception as fb_e:
                            print(f"⚠️ フォールバック処理でエラー: {fb_e}")
                            return "申し訳ないウル、処理中にエラーが発生したウル🐺"

                    # BrainIntegration経由で処理
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
                                fallback_func=fallback_ai_commander,
                                bypass_context=bypass_context,
                                bypass_handlers=bypass_handlers,
                            )
                        )
                    finally:
                        loop.close()

                    if result and result.success and result.message:
                        print(f"🧠 応答: brain={result.used_brain}, fallback={result.fallback_used}, time={result.processing_time_ms}ms")
                        show_guide = should_show_guide(room_id, sender_account_id)
                        send_chatwork_message(room_id, result.to_chatwork_message(), sender_account_id, show_guide)
                        update_conversation_timestamp(room_id, sender_account_id)
                        return jsonify({
                            "status": "ok",
                            "brain": result.used_brain,
                            "fallback": result.fallback_used,
                            "mode": mode,
                        })
            except Exception as e:
                print(f"⚠️ 脳アーキテクチャエラー（従来フローにフォールバック）: {e}")
                import traceback
                traceback.print_exc()

        # =====================================================
        # 従来のフロー
        # =====================================================

        # ★★★ pending_taskのフォローアップを最初にチェック ★★★
        pending_response = handle_pending_task_followup(clean_message, room_id, sender_account_id, sender_name)
        if pending_response:
            print(f"📋 pending_taskのフォローアップを処理")
            show_guide = should_show_guide(room_id, sender_account_id)
            send_chatwork_message(room_id, pending_response, sender_account_id, show_guide)
            update_conversation_timestamp(room_id, sender_account_id)
            return jsonify({"status": "ok"})

        # =====================================================
        # v10.38.1: 従来フロー用フォールバック（脳無効時のみ実行）
        # 脳アーキテクチャ有効時は、bypass_handlers で脳内から処理される
        # ここは USE_BRAIN_ARCHITECTURE=false の場合のみ実行される
        # =====================================================
        if USE_GOAL_SETTING_LIB:
            goal_session_handled = False
            try:
                pool = get_pool()
                has_session = has_active_goal_session(pool, room_id, sender_account_id)
                print(f"🎯 目標設定セッションチェック: room_id={room_id}, has_session={has_session}")

                if has_session:
                    goal_session_handled = True
                    print(f"🎯 アクティブなセッションを検出 - 対話フローにルーティング")
                    result = process_goal_setting_message(pool, room_id, sender_account_id, clean_message)

                    if result and result.get("success"):
                        response_message = result.get("message", "")
                        if response_message:
                            show_guide = should_show_guide(room_id, sender_account_id)
                            send_chatwork_message(room_id, response_message, sender_account_id, show_guide)
                            update_conversation_timestamp(room_id, sender_account_id)
                            return jsonify({"status": "ok"})
                        else:
                            # 成功だがメッセージが空の場合（通常はないが念のため）
                            print(f"⚠️ 目標設定処理成功だがメッセージが空")
                            return jsonify({"status": "ok"})
                    else:
                        # result が None または success=False の場合
                        # セッションがあるのでAI司令塔には渡さない
                        error_msg = result.get("message") if result else None
                        if not error_msg:
                            error_msg = "🤔 目標設定の処理中にエラーが発生したウル...\nもう一度メッセージを送ってほしいウル🐺"
                        print(f"⚠️ 目標設定処理失敗: {error_msg}")
                        send_chatwork_message(room_id, error_msg, sender_account_id, False)
                        return jsonify({"status": "ok"})

            except Exception as e:
                print(f"❌ 目標設定セッション処理で例外: {e}")
                import traceback
                traceback.print_exc()

                # セッションがあった場合はAI司令塔に渡さない（v10.19.4）
                if goal_session_handled:
                    send_chatwork_message(
                        room_id,
                        "🤔 目標設定の処理中にエラーが発生したウル...\nもう一度メッセージを送ってほしいウル🐺",
                        sender_account_id, False
                    )
                    return jsonify({"status": "ok"})

        # =====================================================
        # v6.9.1: ローカルコマンド判定（API制限対策）
        # =====================================================
        # 明確なコマンドはAI司令塔を呼ばずに直接処理
        local_action, local_groups = match_local_command(clean_message)
        if local_action:
            print(f"🏠 ローカルコマンド検出: {local_action}")
            local_response = execute_local_command(
                local_action, local_groups, 
                sender_account_id, sender_name, room_id
            )
            if local_response:
                show_guide = should_show_guide(room_id, sender_account_id)
                send_chatwork_message(room_id, local_response, sender_account_id, show_guide)
                update_conversation_timestamp(room_id, sender_account_id)
                return jsonify({"status": "ok"})
            # local_responseがNoneの場合はAI司令塔に委ねる
        
        # 現在のデータを取得
        all_persons = get_all_persons_summary()
        all_tasks = get_tasks()
        chatwork_users = get_all_chatwork_users()  # ★ ChatWorkユーザー一覧を取得

        # ★ Phase X: pending announcement があればそちらを優先処理
        # v10.33.0: USE_ANNOUNCEMENT_FEATUREフラグチェック削除
        try:
            announcement_handler = _get_announcement_handler()
            if announcement_handler:
                pending = announcement_handler._get_pending_announcement(room_id, sender_account_id)
                if pending:
                    print(f"📢 pending announcement検出: {pending['id']}")
                    response = announcement_handler.handle_announcement_request(
                        params={"raw_message": clean_message},
                        room_id=room_id,
                        account_id=sender_account_id,
                        sender_name=sender_name,
                    )
                    # v10.26.5: Noneが返った場合はフォローアップではないのでAI司令塔に委ねる
                    if response is None:
                        print(f"📢 フォローアップではない判定 → AI司令塔に委ねる")
                    elif response:
                        show_guide = should_show_guide(room_id, sender_account_id)
                        send_chatwork_message(room_id, response, sender_account_id, show_guide)
                        update_conversation_timestamp(room_id, sender_account_id)
                        return jsonify({"status": "ok"})
        except Exception as e:
            print(f"❌ pending announcement チェックエラー: {e}")

        # AI司令塔に判断を委ねる（AIの判断力を最大活用）
        command = ai_commander(clean_message, all_persons, all_tasks, chatwork_users, sender_name)
        
        # 検出された言語を取得（NEW）
        response_language = command.get("response_language", "ja")
        print(f"検出された言語: {response_language}")
        
        # アクションを実行
        action_response = execute_action(command, sender_name, room_id, sender_account_id)
        
        if action_response:
            # 案内を表示すべきか判定
            show_guide = should_show_guide(room_id, sender_account_id)
            send_chatwork_message(room_id, action_response, sender_account_id, show_guide)
            # タイムスタンプを更新
            update_conversation_timestamp(room_id, sender_account_id)
            return jsonify({"status": "ok"})
        
        # 通常会話として処理（言語を指定）
        history = get_conversation_history(room_id, sender_account_id)
        
        # 関連する人物情報をコンテキストに追加
        # ルームの最近の会話を取得
        room_context = get_room_context(room_id, limit=30)
        
        context_parts = []
        if room_context:
            context_parts.append(f"【このルームの最近の会話】\n{room_context}")
        if all_persons:
            persons_str = "\n".join([f"・{p['name']}: {p['attributes']}" for p in all_persons[:5] if p['attributes']])
            if persons_str:
                context_parts.append(f"【覚えている人物】\n{persons_str}")
        
        context = "\n\n".join(context_parts) if context_parts else None
        
        # 言語を指定してAI応答生成（NEW）
        ai_response = get_ai_response(clean_message, history, sender_name, context, response_language)
        
        # 分析ログ記録（一般会話）
        log_analytics_event(
            event_type="general_chat",
            actor_account_id=sender_account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "message_length": len(clean_message),
                "response_length": len(ai_response),
                "response_language": response_language
            }
        )
        
        # 会話履歴を保存
        history.append({"role": "user", "content": clean_message})
        history.append({"role": "assistant", "content": ai_response})
        save_conversation_history(room_id, sender_account_id, history)
        
        # ChatWorkへ返信
        # 案内を表示すべきか判定
        show_guide = should_show_guide(room_id, sender_account_id)
        send_chatwork_message(room_id, ai_response, sender_account_id, show_guide)
        # タイムスタンプを更新
        update_conversation_timestamp(room_id, sender_account_id)

        # v10.21.0: Memory Framework処理（会話記憶）
        # ChatWork送信後に実行（ユーザー体験を優先）
        process_memory_after_conversation(
            room_id=room_id,
            account_id=sender_account_id,
            sender_name=sender_name,
            user_message=clean_message,
            ai_response=ai_response,
            history=history
        )

        return jsonify({"status": "ok"})
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

def get_sender_name(room_id, account_id):
    try:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        response = httpx.get(
            f"https://api.chatwork.com/v2/rooms/{room_id}/members",
            headers={"X-ChatWorkToken": api_token}, timeout=10.0
        )
        if response.status_code == 200:
            for member in response.json():
                if str(member.get("account_id")) == str(account_id):
                    return member.get("name", "ゲスト")
    except:
        pass
    return "ゲスト"

def should_show_guide(room_id, account_id):
    """案内文を表示すべきかどうかを判定（PostgreSQL版）"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            # DMルームの場合は案内を表示しない
            dm_check = conn.execute(
                sqlalchemy.text("""
                    SELECT 1 FROM dm_room_cache
                    WHERE dm_room_id = :room_id
                    LIMIT 1
                """),
                {"room_id": room_id}
            ).fetchone()

            if dm_check:
                return False  # DMルームでは案内不要

            result = conn.execute(
                sqlalchemy.text("""
                    SELECT last_conversation_at
                    FROM conversation_timestamps
                    WHERE room_id = :room_id AND account_id = :account_id
                """),
                {"room_id": room_id, "account_id": account_id}
            ).fetchone()

            if not result:
                return True  # 会話履歴がない場合は表示

            last_conversation_at = result[0]
            if not last_conversation_at:
                return True

            # 最終会話から1時間以上経過しているか
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            if last_conversation_at.replace(tzinfo=timezone.utc) < one_hour_ago:
                return True

            return False
    except Exception as e:
        print(f"案内表示判定エラー: {e}")
        return True  # エラー時は表示

def update_conversation_timestamp(room_id, account_id):
    """会話のタイムスタンプを更新"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO conversation_timestamps (room_id, account_id, last_conversation_at, updated_at)
                    VALUES (:room_id, :account_id, :now, :now)
                    ON CONFLICT (room_id, account_id)
                    DO UPDATE SET last_conversation_at = :now, updated_at = :now
                """),
                {
                    "room_id": room_id,
                    "account_id": account_id,
                    "now": datetime.now(timezone.utc)
                }
            )
    except Exception as e:
        print(f"会話タイムスタンプ更新エラー: {e}")
        traceback.print_exc()

def send_chatwork_message(room_id, message, reply_to=None, show_guide=False, return_details=False):
    """メッセージを送信（リトライ機構付き）

    Args:
        room_id: 送信先ルームID
        message: 送信メッセージ
        reply_to: 返信先アカウントID（オプション）
        show_guide: 案内文を追加するか
        return_details: Trueの場合、message_idを含む詳細を返す（v10.26.1追加）

    Returns:
        return_details=False (デフォルト): bool - 成功/失敗
        return_details=True: dict - {"success": bool, "message_id": str or None}
    """
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")

    # 案内文を追加（条件を満たす場合のみ）
    if show_guide:
        message += "\n\n💬 グループチャットでは @ソウルくん をつけて話しかけてウル🐕"

    # 返信タグを一時的に無効化（テスト中）
    # if reply_to:
    #     message = f"[rp aid={reply_to}][/rp]\n{message}"

    response, success = call_chatwork_api_with_retry(
        method="POST",
        url=f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
        headers={"X-ChatWorkToken": api_token},
        data={"body": message}
    )

    # v10.26.1: return_details=True の場合、message_idを含む詳細を返す
    if return_details:
        result = {"success": False, "message_id": None}
        if success and response and response.status_code == 200:
            try:
                json_data = response.json()
                result = {
                    "success": True,
                    "message_id": json_data.get("message_id")
                }
            except Exception:
                result = {"success": True, "message_id": None}
        return result

    # デフォルト: 後方互換性のためboolを返す
    return success and response and response.status_code == 200

# ========================================
# ポーリング機能（返信ボタン検知用）
# ========================================

def get_all_rooms():
    """ソウルくんが参加している全ルームを取得（リトライ機構付き）"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")

    response, success = call_chatwork_api_with_retry(
        method="GET",
        url="https://api.chatwork.com/v2/rooms",
        headers={"X-ChatWorkToken": api_token}
    )

    if success and response and response.status_code == 200:
        return response.json()
    elif response:
        print(f"ルーム一覧取得エラー: {response.status_code}")
    return []

def get_room_messages(room_id, force=False):
    """ルームのメッセージを取得
    
    堅牢なエラーハンドリング版
    """
    # room_idの検証
    if room_id is None:
        print(f"   ⚠️ room_idがNone")
        return []
    
    try:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    except Exception as e:
        print(f"   ❌ APIトークン取得エラー: {e}")
        return []
    
    if not api_token:
        print(f"   ❌ APIトークンが空")
        return []
    
    try:
        params = {"force": 1} if force else {}
        
        print(f"   🌐 API呼び出し: GET /rooms/{room_id}/messages, force={force}")
        
        response = httpx.get(
            f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            params=params,
            timeout=10.0
        )
        
        print(f"   📬 APIレスポンス: status={response.status_code}")
        
        if response.status_code == 200:
            try:
                messages = response.json()
                
                # レスポンスの検証
                if messages is None:
                    print(f"   ⚠️ APIレスポンスがNone")
                    return []
                
                if not isinstance(messages, list):
                    print(f"   ⚠️ APIレスポンスが配列ではない: {type(messages)}")
                    return []
                
                return messages
            except Exception as e:
                print(f"   ❌ JSONパースエラー: {e}")
                return []
        
        elif response.status_code == 204:
            # 新しいメッセージなし（正常）
            return []
        
        elif response.status_code == 429:
            # レートリミット
            print(f"   ⚠️ レートリミット: room_id={room_id}")
            return []
        
        else:
            # その他のエラー
            try:
                error_body = response.text[:200] if response.text else "No body"
            except:
                error_body = "Could not read body"
            print(f"   ⚠️ メッセージ取得エラー: status={response.status_code}, body={error_body}")
            return []
    
    except httpx.TimeoutException:
        print(f"   ⚠️ タイムアウト: room_id={room_id}")
        return []
    
    except httpx.RequestError as e:
        print(f"   ❌ リクエストエラー: {e}")
        return []
    
    except Exception as e:
        print(f"   ❌ メッセージ取得で予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        return []


def is_processed(message_id):
    """処理済みかどうかを確認（PostgreSQL版）"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("SELECT 1 FROM processed_messages WHERE message_id = :message_id"),
                {"message_id": message_id}
            ).fetchone()
            return result is not None
    except Exception as e:
        print(f"処理済み確認エラー: {e}")
        return False


def save_room_message(room_id, message_id, account_id, account_name, body, send_time=None):
    """ルームのメッセージを保存"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO room_messages (room_id, message_id, account_id, account_name, body, send_time)
                    VALUES (:room_id, :message_id, :account_id, :account_name, :body, :send_time)
                    ON CONFLICT (message_id) DO NOTHING
                """),
                {
                    "room_id": room_id,
                    "message_id": message_id,
                    "account_id": account_id,
                    "account_name": account_name,
                    "body": body,
                    "send_time": send_time or datetime.now(timezone.utc)
                }
            )
    except Exception as e:
        print(f"メッセージ保存エラー: {e}")
        traceback.print_exc()

def get_room_context(room_id, limit=30):
    """ルーム全体の最近のメッセージを取得してAI用の文脈を構築"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT account_name, body, send_time
                    FROM room_messages
                    WHERE room_id = :room_id
                    ORDER BY send_time DESC
                    LIMIT :limit
                """),
                {"room_id": room_id, "limit": limit}
            ).fetchall()
        
        if not result:
            return None
        
        # 時系列順に並べ替えて文脈を構築
        messages = list(reversed(result))
        context_lines = []
        for msg in messages:
            name = msg[0] or "不明"
            body = msg[1] or ""
            if msg[2]:
                time_str = msg[2].strftime("%H:%M")
            else:
                time_str = ""
            context_lines.append(f"[{time_str}] {name}: {body}")
        
        return "\n".join(context_lines)
    except Exception as e:
        print(f"ルーム文脈取得エラー: {e}")
        return None

def ensure_room_messages_table():
    """room_messagesテーブルが存在しない場合は作成"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS room_messages (
                    id SERIAL PRIMARY KEY,
                    room_id BIGINT NOT NULL,
                    message_id VARCHAR(50) NOT NULL UNIQUE,
                    account_id BIGINT NOT NULL,
                    account_name VARCHAR(255),
                    body TEXT,
                    send_time TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_room_messages_room_id ON room_messages(room_id);
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_room_messages_send_time ON room_messages(room_id, send_time DESC);
            """))
            print("✅ room_messagesテーブルの確認/作成完了")
    except Exception as e:
        print(f"⚠️ room_messagesテーブル作成エラー: {e}")
        traceback.print_exc()

def ensure_processed_messages_table():
    """processed_messagesテーブルが存在しない場合は作成（二重処理防止の要）"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id VARCHAR(50) PRIMARY KEY,
                    room_id BIGINT NOT NULL,
                    processed_at TIMESTAMP WITH TIME ZONE NOT NULL
                );
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_processed_messages_room_id 
                ON processed_messages(room_id);
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_processed_messages_processed_at 
                ON processed_messages(processed_at);
            """))
            print("✅ processed_messagesテーブルの確認/作成完了")
    except Exception as e:
        print(f"⚠️ processed_messagesテーブル作成エラー: {e}")
        traceback.print_exc()

def mark_as_processed(message_id, room_id):
    """処理済みとしてマーク（PostgreSQL版）"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO processed_messages (message_id, room_id, processed_at)
                    VALUES (:message_id, :room_id, :processed_at)
                    ON CONFLICT (message_id) DO NOTHING
                """),
                {
                    "message_id": message_id,
                    "room_id": room_id,
                    "processed_at": datetime.now(timezone.utc)
                }
            )
    except Exception as e:
        print(f"処理済みマークエラー: {e}")
        traceback.print_exc()


# =====================================================
# ===== 遅延管理機能（P1-020〜P1-022, P1-030） =====
# =====================================================

def ensure_overdue_tables():
    """
    遅延管理用テーブルが存在しない場合は作成

    v10.24.5: handlers/overdue_handler.py に委譲
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_overdue_handler()
    if handler:
        handler.ensure_overdue_tables()
        return

    print("❌ OverdueHandler not available - cannot ensure tables")


# =====================================================
# ===== v6.9.0: 管理者学習機能 =====
# =====================================================
# 
# カズさんとのやりとりでソウルくんが学習する機能
# - 管理者（カズさん）からの即時学習
# - スタッフからの提案 → 管理者承認後に反映
# =====================================================

def ensure_knowledge_tables():
    """管理者学習機能用テーブルが存在しない場合は作成"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            # 知識テーブル
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS soulkun_knowledge (
                    id SERIAL PRIMARY KEY,
                    category TEXT NOT NULL DEFAULT 'other',
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_by TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(category, key)
                );
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_category 
                ON soulkun_knowledge(category);
            """))
            
            # 提案テーブル
            # v6.9.1: admin_notifiedフラグ追加（通知失敗検知用）
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS knowledge_proposals (
                    id SERIAL PRIMARY KEY,
                    proposed_by_account_id TEXT NOT NULL,
                    proposed_by_name TEXT,
                    proposed_in_room_id TEXT,
                    category TEXT NOT NULL DEFAULT 'other',
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    message_id TEXT,
                    admin_message_id TEXT,
                    admin_notified BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    reviewed_by TEXT,
                    reviewed_at TIMESTAMP WITH TIME ZONE
                );
            """))
            # v6.9.1: 既存テーブルにカラム追加（マイグレーション用）
            try:
                conn.execute(sqlalchemy.text("""
                    ALTER TABLE knowledge_proposals 
                    ADD COLUMN IF NOT EXISTS admin_notified BOOLEAN DEFAULT FALSE;
                """))
            except:
                pass  # カラム既存の場合は無視
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_proposals_status 
                ON knowledge_proposals(status);
            """))
            
            print("✅ 管理者学習機能テーブルの確認/作成完了")
    except Exception as e:
        print(f"⚠️ 管理者学習機能テーブル作成エラー: {e}")
        traceback.print_exc()


def is_admin(account_id):
    """
    管理者（カズさん）かどうかを判定

    v10.30.1: lib/admin_config.py を使用（DB取得、キャッシュ付き）
    フォールバック時は従来のハードコード比較を使用
    """
    if USE_ADMIN_CONFIG:
        return is_admin_account(str(account_id))
    return str(account_id) == str(ADMIN_ACCOUNT_ID)


def save_knowledge(category: str, key: str, value: str, created_by: str = None):
    """知識を保存（既存の場合は更新）"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            # UPSERT（存在すれば更新、なければ挿入）
            conn.execute(sqlalchemy.text("""
                INSERT INTO soulkun_knowledge (category, key, value, created_by, updated_at)
                VALUES (:category, :key, :value, :created_by, CURRENT_TIMESTAMP)
                ON CONFLICT (category, key) 
                DO UPDATE SET value = :value, updated_at = CURRENT_TIMESTAMP
            """), {
                "category": category,
                "key": key,
                "value": value,
                "created_by": created_by
            })
        print(f"✅ 知識を保存: [{category}] {key} = {value}")
        return True
    except Exception as e:
        print(f"❌ 知識保存エラー: {e}")
        traceback.print_exc()
        return False


def delete_knowledge(category: str = None, key: str = None):
    """知識を削除"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            if category and key:
                conn.execute(sqlalchemy.text("""
                    DELETE FROM soulkun_knowledge WHERE category = :category AND key = :key
                """), {"category": category, "key": key})
            elif key:
                # カテゴリ指定なしの場合はkeyのみで検索
                conn.execute(sqlalchemy.text("""
                    DELETE FROM soulkun_knowledge WHERE key = :key
                """), {"key": key})
        print(f"✅ 知識を削除: [{category}] {key}")
        return True
    except Exception as e:
        print(f"❌ 知識削除エラー: {e}")
        traceback.print_exc()
        return False


# v6.9.1: 知識の上限設定（トークン制限対策）
KNOWLEDGE_LIMIT = 50  # プロンプトに含める知識の最大件数
KNOWLEDGE_VALUE_MAX_LENGTH = 200  # 各知識の値の最大文字数


# =====================================================
# v10.33.0: Phase 3 ナレッジ検索関連の旧関数を削除
# search_phase3_knowledge, format_phase3_results,
# integrated_knowledge_search, search_legacy_knowledge は
# handlers/knowledge_handler.py に移行済み
# =====================================================

def get_all_knowledge(limit: int = None):
    """全ての知識を取得"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            # v6.9.1: LIMITを追加
            sql = """
                SELECT category, key, value, created_at 
                FROM soulkun_knowledge 
                ORDER BY category, updated_at DESC
            """
            if limit:
                sql += f" LIMIT {limit}"
            result = conn.execute(sqlalchemy.text(sql))
            rows = result.fetchall()
            return [{"category": r[0], "key": r[1], "value": r[2], "created_at": r[3]} for r in rows]
    except Exception as e:
        print(f"❌ 知識取得エラー: {e}")
        traceback.print_exc()
        return []


def get_knowledge_for_prompt():
    """プロンプト用に知識を整形して取得（上限付き）"""
    # v6.9.1: 上限を設定
    knowledge_list = get_all_knowledge(limit=KNOWLEDGE_LIMIT)
    if not knowledge_list:
        return ""
    
    # カテゴリごとにグループ化
    by_category = {}
    for k in knowledge_list:
        cat = k["category"]
        if cat not in by_category:
            by_category[cat] = []
        # v6.9.1: 値の長さを制限
        value = k['value']
        if len(value) > KNOWLEDGE_VALUE_MAX_LENGTH:
            value = value[:KNOWLEDGE_VALUE_MAX_LENGTH] + "..."
        by_category[cat].append(f"- {k['key']}: {value}")
    
    # 整形
    lines = ["【学習済みの知識】"]
    category_names = {
        "character": "キャラ設定",
        "rules": "業務ルール", 
        "members": "社員情報",
        "other": "その他"
    }
    for cat, items in by_category.items():
        cat_name = category_names.get(cat, cat)
        lines.append(f"\n▼ {cat_name}")
        lines.extend(items)
    
    return "\n".join(lines)


# =====================================================
# ProposalHandler初期化（v10.24.2）
# v10.33.0: フラグチェック削除（ハンドラー必須化）
# =====================================================
def _get_proposal_handler():
    """ProposalHandlerのシングルトンインスタンスを取得"""
    global _proposal_handler
    if _proposal_handler is None:
        _proposal_handler = _NewProposalHandler(
            get_pool=get_pool,
            get_secret=get_secret,
            admin_room_id=str(ADMIN_ROOM_ID),
            admin_account_id=ADMIN_ACCOUNT_ID,
            is_admin=is_admin,
            save_person_attribute=save_person_attribute  # v10.25.0: 人物情報提案対応
        )
    return _proposal_handler


def create_proposal(proposed_by_account_id: str, proposed_by_name: str,
                   proposed_in_room_id: str, category: str, key: str,
                   value: str, message_id: str = None):
    """
    知識の提案を作成

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.create_proposal(
            proposed_by_account_id, proposed_by_name, proposed_in_room_id,
            category, key, value, message_id
        )

    print("❌ ProposalHandler not available - cannot create proposal")
    return None


def get_pending_proposals():
    """
    承認待ちの提案を取得
    v6.9.1: 古い順（FIFO）に変更 - 待たせている人から処理

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.get_pending_proposals()

    print("❌ ProposalHandler not available - cannot get pending proposals")
    return []


def get_oldest_pending_proposal():
    """
    最も古い承認待ち提案を取得（v6.9.1: FIFO）

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.get_oldest_pending_proposal()

    print("❌ ProposalHandler not available - cannot get oldest pending proposal")
    return None


def get_proposal_by_id(proposal_id: int):
    """
    ID指定で提案を取得（v6.9.1追加）

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.get_proposal_by_id(proposal_id)

    print("❌ ProposalHandler not available - cannot get proposal by ID")
    return None


def get_latest_pending_proposal():
    """
    最新の承認待ち提案を取得（後方互換性のため残す）

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.get_latest_pending_proposal()

    print("❌ ProposalHandler not available - cannot get latest pending proposal")
    return None


# =====================================================
# v6.9.2: 未通知提案の取得・再通知機能
# =====================================================

def get_unnotified_proposals():
    """
    通知失敗した提案を取得（admin_notified=FALSE）
    v6.9.2追加

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.get_unnotified_proposals()

    print("❌ ProposalHandler not available - cannot get unnotified proposals")
    return []


def retry_proposal_notification(proposal_id: int):
    """
    提案の通知を再送（v6.9.2追加）

    v10.24.2: handlers/proposal_handler.py に分割
    v10.25.0: category対応
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.retry_proposal_notification(proposal_id)

    print("❌ ProposalHandler not available - cannot retry proposal notification")
    return False, "ハンドラーが利用できません"


def approve_proposal(proposal_id: int, reviewed_by: str):
    """
    提案を承認して知識または人物情報に反映

    v10.24.2: handlers/proposal_handler.py に分割
    v10.25.0: category='memory'の場合は人物情報として保存
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.approve_proposal(proposal_id, reviewed_by)

    print("❌ ProposalHandler not available - cannot approve proposal")
    return False


def reject_proposal(proposal_id: int, reviewed_by: str):
    """
    提案を却下

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_proposal_handler()
    if handler:
        return handler.reject_proposal(proposal_id, reviewed_by)

    print("❌ ProposalHandler not available - cannot reject proposal")
    return False


def get_all_contacts():
    """
    ★★★ v6.8.3: /contacts APIでコンタクト一覧を取得 ★★★
    ★★★ v6.8.4: fetched_okフラグ導入 & 429時もキャッシュセット ★★★
    
    ChatWork /contacts APIを使用して、全コンタクトのaccount_idとroom_id（DMルームID）を取得。
    これにより、N+1問題が完全に解消される。
    
    Returns:
        tuple: (contacts_map, fetched_ok)
            - contacts_map: {account_id: room_id} のマッピング
            - fetched_ok: True=API成功, False=API失敗（429含む）
        
    Note:
        - 429時も空dictをキャッシュ（同一実行内でリトライ連打を防止）
        - fetched_okで成功/失敗を判定（空dict=成功の可能性あり）
    """
    global _runtime_contacts_cache, _runtime_contacts_fetched_ok
    
    # 実行内キャッシュがあればそれを返す（成功/失敗問わず）
    if _runtime_contacts_cache is not None:
        status = "成功" if _runtime_contacts_fetched_ok else "失敗（キャッシュ済み）"
        print(f"✅ コンタクト一覧 メモリキャッシュ使用（{len(_runtime_contacts_cache)}件, {status}）")
        return _runtime_contacts_cache, _runtime_contacts_fetched_ok  # ★★★ v6.8.4: タプルで返す ★★★
    
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    try:
        print("🔍 /contacts APIでコンタクト一覧を取得中...")
        response = httpx.get(
            "https://api.chatwork.com/v2/contacts",
            headers={"X-ChatWorkToken": api_token},
            timeout=30.0
        )
        
        if response.status_code == 200:
            contacts = response.json()
            # {account_id: room_id} のマッピングを作成
            contacts_map = {}
            for contact in contacts:
                account_id = contact.get("account_id")
                room_id = contact.get("room_id")
                if account_id and room_id:
                    contacts_map[int(account_id)] = int(room_id)
            
            print(f"✅ コンタクト一覧取得成功: {len(contacts_map)}件")
            
            # ★★★ v6.8.4: 成功フラグをセット ★★★
            _runtime_contacts_cache = contacts_map
            _runtime_contacts_fetched_ok = True
            
            return contacts_map, True  # ★★★ v6.8.4: タプルで返す ★★★
        
        elif response.status_code == 429:
            print(f"⚠️ /contacts API レート制限に達しました")
            # ★★★ v6.8.4: 429でも空dictをキャッシュ（リトライ連打防止）★★★
            _runtime_contacts_cache = {}
            _runtime_contacts_fetched_ok = False
            return {}, False  # ★★★ v6.8.4: タプルで返す ★★★
        
        else:
            print(f"❌ /contacts API エラー: {response.status_code}")
            # ★★★ v6.8.4: エラーでも空dictをキャッシュ ★★★
            _runtime_contacts_cache = {}
            _runtime_contacts_fetched_ok = False
            return {}, False  # ★★★ v6.8.4: タプルで返す ★★★
    
    except Exception as e:
        print(f"❌ /contacts API 取得エラー: {e}")
        traceback.print_exc()
        # ★★★ v6.8.4: 例外でも空dictをキャッシュ ★★★
        _runtime_contacts_cache = {}
        _runtime_contacts_fetched_ok = False
        return {}, False  # ★★★ v6.8.4: タプルで返す ★★★


def get_direct_room(account_id):
    """
    指定アカウントとの個人チャット（ダイレクト）のroom_idを取得
    
    ★★★ v6.8.3: /contacts APIベースに完全刷新 ★★★
    - N+1問題が完全解消（API 1回で全コンタクト取得）
    - メモリキャッシュ→DBキャッシュ→/contacts APIの順で探索
    
    ★★★ v6.8.4: fetched_okフラグでネガティブキャッシュ判定 ★★★
    - 空dict判定の誤りを修正（コンタクト0件でも成功は成功）
    - 429/エラー時はネガティブキャッシュしない
    
    ★ 運用ルール: 新社員はソウルくんとコンタクト追加が必要
    """
    global _runtime_dm_cache
    
    if not account_id:
        return None
    
    account_id_int = int(account_id)
    
    # 1. まず実行内メモリキャッシュを確認（最速）
    if account_id_int in _runtime_dm_cache:
        cached_room = _runtime_dm_cache[account_id_int]
        if cached_room is not None:
            print(f"✅ DMルーム メモリキャッシュヒット: account_id={account_id}, room_id={cached_room}")
            return cached_room
        elif cached_room is None and _runtime_dm_cache.get(f"{account_id_int}_negative"):
            # ネガティブキャッシュ（API成功で本当に見つからなかった場合のみ）
            print(f"⚠️ DMルーム メモリキャッシュ: account_id={account_id} は見つからない（キャッシュ済み）")
            return None
    
    pool = get_pool()
    
    try:
        # 2. DBキャッシュを確認（API 0回で済む）
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("SELECT dm_room_id FROM dm_room_cache WHERE account_id = :account_id"),
                {"account_id": account_id_int}
            )
            cached = result.fetchone()
            if cached:
                room_id = cached[0]
                print(f"✅ DMルーム DBキャッシュヒット: account_id={account_id}, room_id={room_id}")
                # メモリキャッシュにも保存
                _runtime_dm_cache[account_id_int] = room_id
                return room_id
        
        # 3. /contacts APIで探索（API 1回で全コンタクト取得）
        print(f"🔍 DMルーム探索開始: account_id={account_id}")
        contacts_map, fetched_ok = get_all_contacts()  # ★★★ v6.8.5: タプルで受け取る ★★★
        
        if account_id_int in contacts_map:
            room_id = contacts_map[account_id_int]
            print(f"✅ DMルーム発見（/contacts API）: account_id={account_id}, room_id={room_id}")
            
            # メモリキャッシュに保存
            _runtime_dm_cache[account_id_int] = room_id
            
            # DBにキャッシュ保存
            try:
                with pool.begin() as conn:
                    conn.execute(
                        sqlalchemy.text("""
                            INSERT INTO dm_room_cache (account_id, dm_room_id)
                            VALUES (:account_id, :dm_room_id)
                            ON CONFLICT (account_id) DO UPDATE SET 
                                dm_room_id = :dm_room_id,
                                cached_at = CURRENT_TIMESTAMP
                        """),
                        {"account_id": account_id_int, "dm_room_id": room_id}
                    )
            except Exception as e:
                print(f"⚠️ DMキャッシュ保存エラー（続行）: {e}")
            
            return room_id
        
        # 4. 見つからなかった場合
        print(f"❌ DMルームが見つかりません: account_id={account_id}")
        print(f"   → この人とソウルくんがコンタクト追加されていない可能性があります")
        
        # ★★★ v6.8.5: ローカル変数fetched_okで判定 ★★★
        # API成功時のみネガティブキャッシュ（429/エラー時はキャッシュしない）
        if fetched_ok:
            _runtime_dm_cache[account_id_int] = None
            _runtime_dm_cache[f"{account_id_int}_negative"] = True
        
        return None
        
    except Exception as e:
        print(f"❌ DMルーム取得エラー: {e}")
        traceback.print_exc()
        return None


def notify_dm_not_available(person_name, account_id, tasks, action_type):
    """
    DMが送れない場合にバッファに追加（まとめ送信用）
    
    ★★★ v6.8.3: バッファ方式に変更（per-room制限回避）★★★
    実際の送信はflush_dm_unavailable_notifications()で行う
    
    Args:
        person_name: 対象者の名前
        account_id: 対象者のaccount_id
        tasks: 関連タスクのリスト
        action_type: "督促" or "エスカレーション" or "期限変更質問"
    """
    global _dm_unavailable_buffer
    
    _dm_unavailable_buffer.append({
        "person_name": person_name,
        "account_id": account_id,
        "tasks": tasks,
        "action_type": action_type
    })
    print(f"📝 DM不可通知をバッファに追加: {person_name}さん（{action_type}）")


def flush_dm_unavailable_notifications():
    """
    ★★★ v6.8.3: バッファに溜まったDM不可通知をまとめて1通で送信 ★★★
    
    これにより、per-room制限（10秒10回）を回避できる。
    process_overdue_tasks()の最後に呼び出す。
    """
    global _dm_unavailable_buffer
    
    if not _dm_unavailable_buffer:
        return
    
    print(f"📤 DM不可通知をまとめて送信（{len(_dm_unavailable_buffer)}件）")
    
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    # まとめメッセージを作成
    message_lines = ["[info][title]⚠️ DM送信できなかった通知一覧[/title]"]
    message_lines.append(f"以下の{len(_dm_unavailable_buffer)}名にDMを送信できませんでした：\n")
    
    for i, item in enumerate(_dm_unavailable_buffer[:20], 1):  # 最大20件まで
        person_name = item["person_name"]
        account_id = item["account_id"]
        action_type = item["action_type"]
        tasks = item.get("tasks", [])
        
        # タスク情報（1件のみ表示）
        task_hint = ""
        if tasks and len(tasks) > 0:
            body = tasks[0].get("body", "")
            body_short = (body[:15] + "...") if len(body) > 15 else body
            task_hint = f"「{body_short}」"
        
        message_lines.append(f"{i}. {person_name}（ID:{account_id}）- {action_type} {task_hint}")
    
    if len(_dm_unavailable_buffer) > 20:
        message_lines.append(f"\n...他{len(_dm_unavailable_buffer) - 20}名")
    
    message_lines.append("\n【対応】")
    message_lines.append("ChatWorkで上記の方々がソウルくんをコンタクト追加するか、")
    message_lines.append("管理者がソウルくんアカウントからコンタクト追加してください。[/info]")
    
    message = "\n".join(message_lines)
    
    try:
        response = httpx.post(
            f"https://api.chatwork.com/v2/rooms/{ADMIN_ROOM_ID}/messages",
            headers={"X-ChatWorkToken": api_token},
            data={"body": message},
            timeout=10.0
        )
        
        if response.status_code == 200:
            print(f"✅ 管理部へのDM不可通知まとめ送信成功（{len(_dm_unavailable_buffer)}件）")
        else:
            print(f"❌ 管理部へのDM不可通知まとめ送信失敗: {response.status_code}")
    except Exception as e:
        print(f"❌ 管理部通知エラー: {e}")
    
    # バッファをクリア
    _dm_unavailable_buffer = []


def get_overdue_days(limit_time):
    """
    期限超過日数を計算

    v10.24.0: utils/date_utils.py に分割
    """
    # 新しいモジュールを使用（USE_NEW_DATE_UTILS=trueの場合）
    if USE_NEW_DATE_UTILS:
        return _new_get_overdue_days(limit_time)

    # フォールバック: 旧実装
    if not limit_time:
        return 0

    now = datetime.now(JST)
    today = now.date()

    # v6.8.6: int/float両対応
    try:
        if isinstance(limit_time, (int, float)):
            limit_date = datetime.fromtimestamp(int(limit_time), tz=JST).date()
        elif hasattr(limit_time, 'date'):
            limit_date = limit_time.date()
        else:
            print(f"⚠️ get_overdue_days: 不明なlimit_time型: {type(limit_time)}")
            return 0
    except Exception as e:
        print(f"⚠️ get_overdue_days: 変換エラー: {limit_time}, error={e}")
        return 0

    delta = (today - limit_date).days
    return max(0, delta)


def process_overdue_tasks():
    """
    遅延タスクを処理：督促送信 + エスカレーション
    毎日8:30に実行（remind_tasksから呼び出し）

    v10.24.5: handlers/overdue_handler.py に委譲
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_overdue_handler()
    if handler:
        # キャッシュリセット（ハンドラー呼び出し前）
        global _runtime_dm_cache, _runtime_direct_rooms, _runtime_contacts_cache, _runtime_contacts_fetched_ok
        _runtime_dm_cache = {}
        _runtime_direct_rooms = None
        _runtime_contacts_cache = None
        _runtime_contacts_fetched_ok = None
        print("✅ メモリキャッシュをリセット")
        handler.process_overdue_tasks()
        return

    print("❌ OverdueHandler not available - cannot process overdue tasks")


# =====================================================
# ===== タスク期限変更検知（P1-030） =====
# =====================================================

def detect_and_report_limit_changes(cursor, task_id, old_limit, new_limit, task_info):
    """
    タスクの期限変更を検知して報告
    sync_chatwork_tasks内から呼び出される

    v10.24.5: handlers/overdue_handler.py に委譲
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    handler = _get_overdue_handler()
    if handler:
        handler.detect_and_report_limit_changes(task_id, old_limit, new_limit, task_info)
        return

    print("❌ OverdueHandler not available - cannot report limit changes")


@functions_framework.http
def check_reply_messages(request):
    """5分ごとに実行：返信ボタンとメンションのメッセージを検出
    
    堅牢なエラーハンドリング版 - あらゆるエッジケースに対応
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
        
        processed_count = 0
        
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
        skipped_my = 0
        processed_rooms = 0
        error_rooms = 0
        skipped_messages = 0
        
        for room in rooms:
            room_id = None  # エラーログ用に先に定義
            
            try:
                # ルームデータの検証
                if not isinstance(room, dict):
                    print(f"⚠️ 不正なルームデータ型: {type(room)}")
                    error_rooms += 1
                    continue
                
                room_id = room.get("room_id")
                room_type = room.get("type")
                room_name = room.get("name", "不明")
                
                # room_idの検証
                if room_id is None:
                    print(f"⚠️ room_idがNone: {room}")
                    error_rooms += 1
                    continue
                
                print(f"🔍 ルームチェック開始: room_id={room_id}, type={room_type}, name={room_name}")
                
                # マイチャットをスキップ
                if room_type == "my":
                    skipped_my += 1
                    print(f"⏭️ マイチャットをスキップ: {room_id}")
                    continue
                
                processed_rooms += 1
                
                # メッセージを取得
                print(f"📞 get_room_messages呼び出し: room_id={room_id}")
                
                try:
                    messages = get_room_messages(room_id, force=True)
                except Exception as e:
                    print(f"❌ メッセージ取得エラー: room_id={room_id}, error={e}")
                    error_rooms += 1
                    continue
                
                # messagesの検証
                if messages is None:
                    print(f"⚠️ messagesがNone: room_id={room_id}")
                    messages = []
                
                if not isinstance(messages, list):
                    print(f"⚠️ messagesが不正な型: {type(messages)}, room_id={room_id}")
                    messages = []
                
                print(f"📨 ルーム {room_id} ({room_name}): {len(messages)}件のメッセージを取得")
                
                # メッセージがない場合はスキップ
                if not messages:
                    continue
                
                for msg in messages:
                    try:
                        # msgの検証
                        if not isinstance(msg, dict):
                            print(f"⚠️ 不正なメッセージデータ型: {type(msg)}")
                            skipped_messages += 1
                            continue
                        
                        # 各フィールドを安全に取得
                        message_id = msg.get("message_id")
                        body = msg.get("body")  # Noneの可能性あり
                        account_data = msg.get("account")
                        send_time = msg.get("send_time")
                        
                        # message_idの検証
                        if message_id is None:
                            print(f"⚠️ message_idがNone")
                            skipped_messages += 1
                            continue
                        
                        # accountデータの検証
                        if account_data is None or not isinstance(account_data, dict):
                            print(f"⚠️ accountデータが不正: message_id={message_id}")
                            account_id = None
                            sender_name = "ゲスト"
                        else:
                            account_id = account_data.get("account_id")
                            sender_name = account_data.get("name", "ゲスト")
                        
                        # bodyの検証と安全な処理
                        if body is None:
                            body = ""
                            print(f"⚠️ bodyがNone: message_id={message_id}")
                        
                        if not isinstance(body, str):
                            print(f"⚠️ bodyが文字列ではない: type={type(body)}, message_id={message_id}")
                            body = str(body) if body else ""
                        
                        # デバッグログ（安全なスライス）
                        print(f"🔍 メッセージチェック: message_id={message_id}")
                        print(f"   body type: {type(body)}")
                        print(f"   body length: {len(body)}")
                        
                        # 安全なbody表示（スライスエラー防止）
                        if body:
                            body_preview = body[:100] if len(body) > 100 else body
                            # 改行を置換して見やすくする
                            body_preview = body_preview.replace('\n', '\\n')
                            print(f"   body preview: {body_preview}")
                        else:
                            print(f"   body: (empty)")
                        
                        # メンション/返信チェック（安全な呼び出し）
                        try:
                            is_mention_or_reply = is_mention_or_reply_to_soulkun(body) if body else False
                            print(f"   is_mention_or_reply: {is_mention_or_reply}")
                        except Exception as e:
                            print(f"   ❌ is_mention_or_reply_to_soulkun エラー: {e}")
                            is_mention_or_reply = False
                        
                        # 5分以内のメッセージのみ処理
                        if send_time is not None:
                            try:
                                if int(send_time) < five_minutes_ago:
                                    continue
                            except (ValueError, TypeError) as e:
                                print(f"⚠️ send_time変換エラー: {send_time}, error={e}")
                        
                        # 自分自身のメッセージを無視
                        if account_id is not None and str(account_id) == MY_ACCOUNT_ID:
                            continue

                        # v10.16.1: オールメンション（toall）の判定改善
                        if should_ignore_toall(body):
                            print(f"   ⏭️ オールメンション（toall）のみのため無視")
                            continue

                        # メンションまたは返信を検出
                        if not is_mention_or_reply:
                            continue

                        # 処理済みならスキップ
                        try:
                            if is_processed(message_id):
                                print(f"⏭️ すでに処理済み: message_id={message_id}")
                                continue
                        except Exception as e:
                            print(f"⚠️ 処理済みチェックエラー（続行）: {e}")
                        
                        print(f"✅ 検出成功！処理開始: room={room_id}, message_id={message_id}")
                        
                        # ★★★ 2重処理防止: 即座にマーク（他のプロセスが処理しないように） ★★★
                        mark_as_processed(message_id, room_id)
                        print(f"🔒 処理開始マーク: message_id={message_id}")
                        
                        # メッセージをDBに保存
                        try:
                            save_room_message(
                                room_id=room_id,
                                message_id=message_id,
                                account_id=account_id,
                                account_name=sender_name,
                                body=body,
                                send_time=datetime.fromtimestamp(send_time, tz=JST) if send_time else None
                            )
                        except Exception as e:
                            print(f"⚠️ メッセージ保存エラー（続行）: {e}")
                        
                        # メッセージをクリーニング
                        try:
                            clean_message = clean_chatwork_message(body) if body else ""
                        except Exception as e:
                            print(f"⚠️ メッセージクリーニングエラー: {e}")
                            clean_message = body
                        
                        if clean_message:
                            try:
                                # ★★★ pending_taskのフォローアップを最初にチェック ★★★
                                pending_response = handle_pending_task_followup(clean_message, room_id, account_id, sender_name)
                                if pending_response:
                                    print(f"📋 pending_taskのフォローアップを処理")
                                    send_chatwork_message(room_id, pending_response, None, False)
                                    processed_count += 1
                                    continue
                                
                                # =====================================================
                                # v6.9.1: ローカルコマンド判定（API制限対策）
                                # =====================================================
                                local_action, local_groups = match_local_command(clean_message)
                                if local_action:
                                    print(f"🏠 ローカルコマンド検出: {local_action}")
                                    local_response = execute_local_command(
                                        local_action, local_groups, 
                                        account_id, sender_name, room_id
                                    )
                                    if local_response:
                                        send_chatwork_message(room_id, local_response, None, False)
                                        processed_count += 1
                                        continue
                                
                                # 通常のWebhook処理と同じ処理を実行
                                all_persons = get_all_persons_summary()
                                all_tasks = get_tasks()
                                chatwork_users = get_all_chatwork_users()  # ★ ChatWorkユーザー一覧を取得
                                
                                # AI司令塔に判断を委ねる（AIの判断力を最大活用）
                                command = ai_commander(clean_message, all_persons, all_tasks, chatwork_users, sender_name)
                                response_language = command.get("response_language", "ja") if command else "ja"
                                
                                # アクションを実行
                                action_response = execute_action(command, sender_name, room_id, account_id)
                                
                                if action_response:
                                    send_chatwork_message(room_id, action_response, None, False)
                                else:
                                    # 通常会話として処理
                                    history = get_conversation_history(room_id, account_id)
                                    room_context = get_room_context(room_id, limit=30)
                                    
                                    context_parts = []
                                    if room_context:
                                        context_parts.append(f"【このルームの最近の会話】\n{room_context}")
                                    if all_persons:
                                        persons_str = "\n".join([f"・{p['name']}: {p['attributes']}" for p in all_persons[:5] if p.get('attributes')])
                                        if persons_str:
                                            context_parts.append(f"【覚えている人物】\n{persons_str}")
                                    
                                    context = "\n\n".join(context_parts) if context_parts else None
                                    
                                    ai_response = get_ai_response(clean_message, history, sender_name, context, response_language)
                                    
                                    if history is None:
                                        history = []
                                    history.append({"role": "user", "content": clean_message})
                                    history.append({"role": "assistant", "content": ai_response})
                                    save_conversation_history(room_id, account_id, history)
                                    
                                    send_chatwork_message(room_id, ai_response, None, False)
                                
                                processed_count += 1
                                
                            except Exception as e:
                                print(f"❌ メッセージ処理エラー: message_id={message_id}, error={e}")
                                import traceback
                                traceback.print_exc()
                    
                    except Exception as e:
                        print(f"❌ メッセージ処理中に予期しないエラー: {e}")
                        import traceback
                        traceback.print_exc()
                        skipped_messages += 1
                        continue
                
            except Exception as e:
                error_rooms += 1
                print(f"❌ ルーム {room_id} の処理中にエラー: {e}")
                import traceback
                traceback.print_exc()
                continue  # 次のルームへ
        
        # サマリーログ
        print("=" * 50)
        print(f"📊 処理サマリー:")
        print(f"   - 総ルーム数: {len(rooms)}")
        print(f"   - スキップ（マイチャット）: {skipped_my}")
        print(f"   - 処理したルーム: {processed_rooms}")
        print(f"   - エラーが発生したルーム: {error_rooms}")
        print(f"   - スキップしたメッセージ: {skipped_messages}")
        print(f"   - 処理したメッセージ: {processed_count}")
        print("=" * 50)
        print(f"✅ ポーリング完了: {processed_count}件処理")
        
        return jsonify({
            "status": "ok",
            "processed_count": processed_count,
            "rooms_checked": len(rooms),
            "skipped_my": skipped_my,
            "processed_rooms": processed_rooms,
            "error_rooms": error_rooms,
            "skipped_messages": skipped_messages
        })
        
    except Exception as e:
        print(f"❌ ポーリング全体でエラー: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================================================

def get_room_tasks(room_id, status='open'):
    """
    指定されたルームのタスク一覧を取得
    
    Args:
        room_id: ルームID
        status: タスクのステータス ('open' or 'done')
    
    Returns:
        タスクのリスト
    """
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks"
    # ★★★ v10.4.0: 全タスク同期対応 ★★★
    # assigned_by_account_id フィルタを削除し、全ユーザーが作成したタスクを取得
    params = {
        'status': status,
    }

    headers = {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}
    response = httpx.get(url, headers=headers, params=params, timeout=10.0)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to get tasks for room {room_id}: {response.status_code}")
        return []

def send_completion_notification(room_id, task, assigned_by_name):
    """
    タスク完了通知を送信（個別通知）

    ★★★ v10.15.0: 無効化 ★★★
    個別グループへの完了通知を廃止。
    代わりに remind-tasks の process_completed_tasks_summary() で
    管理部チャットに1日1回まとめて報告する方式に変更。

    Args:
        room_id: ルームID
        task: タスク情報の辞書
        assigned_by_name: 依頼者名
    """
    # v10.15.0: 個別通知を無効化（管理部への日次報告に集約）
    task_id = task.get('task_id', 'unknown')
    print(f"📝 [v10.15.0] 完了通知スキップ: task_id={task_id} (管理部への日次報告に集約)")
    return

    # --- 以下は無効化（v10.15.0以前のコード） ---
    # assigned_to_name = task.get('account', {}).get('name', '担当者')
    # task_body = task.get('body', 'タスク')
    #
    # message = f"[info][title]{assigned_to_name}さんがタスクを完了しましたウル！[/title]"
    # message += f"タスク: {task_body}\n"
    # message += f"依頼者: {assigned_by_name}さん\n"
    # message += f"お疲れ様でしたウル！[/info]"
    #
    # url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
    # data = {'body': message}
    #
    # headers = {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}
    # response = httpx.post(url, headers=headers, data=data, timeout=10.0)
    #
    # if response.status_code == 200:
    #     print(f"Completion notification sent for task {task['task_id']} in room {room_id}")
    # else:
    #     print(f"Failed to send completion notification: {response.status_code}")

def sync_room_members():
    """全ルームのメンバーをchatwork_usersテーブルに同期

    v10.30.0: 10の鉄則準拠 - organization_id追加
    """
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    organization_id = MEMORY_DEFAULT_ORG_ID

    try:
        # 全ルームを取得
        rooms = get_all_rooms()

        if not rooms:
            print("No rooms found")
            return

        pool = get_pool()
        synced_count = 0

        for room in rooms:
            room_id = room.get("room_id")
            room_type = room.get("type")

            # マイチャットはスキップ
            if room_type == "my":
                continue

            try:
                # ルームメンバーを取得
                response = httpx.get(
                    f"https://api.chatwork.com/v2/rooms/{room_id}/members",
                    headers={"X-ChatWorkToken": api_token},
                    timeout=10.0
                )

                if response.status_code != 200:
                    print(f"Failed to get members for room {room_id}: {response.status_code}")
                    continue

                members = response.json()

                with pool.begin() as conn:
                    for member in members:
                        account_id = member.get("account_id")
                        name = member.get("name", "")

                        if not account_id or not name:
                            continue

                        # UPSERT: 存在すれば更新、なければ挿入
                        # v10.30.0: organization_id追加（複合ユニーク制約対応）
                        conn.execute(
                            sqlalchemy.text("""
                                INSERT INTO chatwork_users (organization_id, account_id, name, room_id, updated_at)
                                VALUES (:org_id, :account_id, :name, :room_id, CURRENT_TIMESTAMP)
                                ON CONFLICT (organization_id, account_id)
                                DO UPDATE SET name = :name, room_id = :room_id, updated_at = CURRENT_TIMESTAMP
                            """),
                            {
                                "org_id": organization_id,
                                "account_id": account_id,
                                "name": name,
                                "room_id": room_id
                            }
                        )
                        synced_count += 1

            except Exception as e:
                print(f"Error syncing members for room {room_id}: {e}")
                traceback.print_exc()
                continue

        print(f"Synced {synced_count} members")

    except Exception as e:
        print(f"Error in sync_room_members: {e}")
        traceback.print_exc()

@functions_framework.http
def sync_chatwork_tasks(request):
    """
    Cloud Function: ChatWorkのタスクをDBと同期
    30分ごとに実行される
    
    ★★★ v6.8.5: conn/cursor安全化 & キャッシュリセット追加 ★★★
    """
    global _runtime_dm_cache, _runtime_direct_rooms, _runtime_contacts_cache, _runtime_contacts_fetched_ok, _dm_unavailable_buffer
    
    print("=== Starting task sync ===")
    
    # ★★★ v6.8.5: 実行開始時にメモリキャッシュをリセット（ウォームスタート対策）★★★
    _runtime_dm_cache = {}
    _runtime_direct_rooms = None
    _runtime_contacts_cache = None
    _runtime_contacts_fetched_ok = None
    _dm_unavailable_buffer = []
    print("✅ メモリキャッシュをリセット")
    
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
                    SELECT task_id, status, limit_time, assigned_by_name FROM chatwork_tasks WHERE task_id = %s
                """, (task_id,))
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
                        WHERE task_id = %s
                    """, (body, limit_datetime, room_name, assigned_to_name, task_id))
                else:
                    # 新規タスクの挿入
                    # ★★★ v10.18.1: summary生成（3段階フォールバック） ★★★
                    # ★★★ v10.24.8: フォールバックも自然な位置で切る ★★★
                    summary = None
                    if USE_TEXT_UTILS_LIB and body:
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
                         skip_tracking, last_synced_at, room_name, assigned_to_name, assigned_by_name, summary, department_id)
                        VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s)
                        ON CONFLICT (task_id) DO NOTHING
                    """, (task_id, room_id, assigned_to_id, assigned_by_id, body,
                          limit_datetime, skip_tracking, room_name, assigned_to_name, assigned_by_name, summary, department_id))

            # 完了タスクを取得
            done_tasks = get_room_tasks(room_id, 'done')
            
            for task in done_tasks:
                task_id = task['task_id']
                
                # DBに存在するか確認
                cursor.execute("""
                    SELECT task_id, status, completion_notified, assigned_by_name 
                    FROM chatwork_tasks 
                    WHERE task_id = %s
                """, (task_id,))
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
                            WHERE task_id = %s
                        """, (task_id,))
                        
                        # 完了通知を送信（まだ送信していない場合）
                        if not completion_notified:
                            send_completion_notification(room_id, task, assigned_by_name)
                            cursor.execute("""
                                UPDATE chatwork_tasks
                                SET completion_notified = TRUE
                                WHERE task_id = %s
                            """, (task_id,))
        
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
        """)
        
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
