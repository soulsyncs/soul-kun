import functions_framework
from flask import jsonify
from google.cloud import secretmanager, firestore
import httpx
import re
import time
from datetime import datetime, timedelta, timezone
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

PROJECT_ID = "soulkun-production"
db = firestore.Client(project=PROJECT_ID)

# Cloud SQL設定
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
    "organization_id": os.getenv("PHASE3_ORGANIZATION_ID", "org_soulsyncs"),
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


def extract_keywords(query: str) -> list:
    """クエリからキーワードを抽出"""
    keywords = []
    for keyword in KNOWLEDGE_KEYWORDS:
        if keyword in query:
            keywords.append(keyword)
    # 短縮形の展開
    expansions = {
        "有給": ["有給休暇", "年次有給休暇"],
        "年休": ["年次有給休暇"],
        "残業": ["時間外労働"],
        "ボーナス": ["賞与"],
    }
    for short_form, long_forms in expansions.items():
        if short_form in keywords:
            for long_form in long_forms:
                if long_form not in keywords:
                    keywords.append(long_form)
    return keywords


def expand_query(query: str, keywords: list) -> str:
    """クエリを拡張して検索精度を向上"""
    if not keywords:
        return query
    for keyword in keywords:
        if keyword in QUERY_EXPANSION_MAP:
            expansion = QUERY_EXPANSION_MAP[keyword]
            expanded = f"{query} {expansion}"
            print(f"🔧 クエリ拡張: '{query}' → '{expanded}'")
            return expanded
    return query


def calculate_keyword_score(content: str, keywords: list) -> float:
    """コンテンツに対するキーワードスコアを計算"""
    if not keywords or not content:
        return 0.0
    score = 0.0
    for keyword in keywords:
        if keyword in content:
            count = min(content.count(keyword), 3)
            score += 0.25 * count
    return min(score, 1.0)

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
# =====================================================
# 管理者（カズさん）のaccount_id
# v6.9.2修正: 417892193はroom_idだった。正しいaccount_idは1728974
ADMIN_ACCOUNT_ID = "1728974"

# 管理部チャットルームID
ADMIN_ROOM_ID = 405315911

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
        "required_data": ["chatwork_users", "sender_name"]
    },
    # =====  =====
    "daily_reflection": {
        "name": "",
        "description": "",
        "category": "reflection",
        "enabled": True,
        "trigger_examples": ["3", ""],
        "params_schema": {
            "reflection_text": {
                "type": "string",
                "description": "",
                "required": True
            }
        },
        "handler": "handle_daily_reflection",
        "requires_confirmation": False,
        "required_data": []
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
        "required_data": ["recent_tasks_context"]
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
        "required_data": ["chatwork_users", "sender_name"]
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
        "required_data": []
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
        "required_data": ["all_persons"]
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
        "required_data": []
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
        "required_data": ["sender_account_id", "sender_name", "room_id"]
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
        "required_data": ["sender_account_id"]
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
        "required_data": []
    },
    
    "approve_proposal": {
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
        "required_data": ["sender_account_id", "room_id"]
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
        "required_data": []
    },

    # ===== 一般会話 =====
    "general_chat": {
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
        "required_data": []
    },
    
    # ===== 将来の機能（enabled=False） =====
    
    "create_document": {
        "name": "資料作成",
        "description": "Google Docsで資料を作成する（議事録、報告書、企画書など）",
        "category": "document",
        "enabled": False,  # 将来実装
        "trigger_examples": [
            "〇〇の資料を作成して",
            "議事録を作って",
            "報告書を書いて",
        ],
        "params_schema": {
            "document_type": {"type": "string", "description": "資料の種類"},
            "title": {"type": "string", "description": "タイトル"},
            "content_outline": {"type": "string", "description": "内容の概要"},
        },
        "handler": "handle_create_document",
        "requires_confirmation": True,
        "required_data": ["google_docs_api"]
    },
    
    "query_company_knowledge": {
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
        "required_data": []  # Phase 3 APIを使用するため外部データ不要
    },
    
    "generate_image": {
        "name": "画像生成",
        "description": "AIで画像を生成する",
        "category": "creative",
        "enabled": False,  # 将来実装
        "trigger_examples": [
            "〇〇の画像を作って",
            "こんなイメージの絵を描いて",
        ],
        "params_schema": {
            "prompt": {"type": "string", "description": "画像の説明"},
            "style": {"type": "string", "description": "スタイル"},
        },
        "handler": "handle_generate_image",
        "requires_confirmation": False,
        "required_data": ["image_generation_api"]
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

# Phase 1-B用: pg8000接続を返す関数
def get_db_connection():
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


def get_all_chatwork_users():
    """ChatWorkユーザー一覧を取得（AI司令塔用）"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT DISTINCT account_id, name 
                    FROM chatwork_users 
                    WHERE name IS NOT NULL AND name != ''
                    ORDER BY name
                """)
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

def get_chatwork_account_id_by_name(name):
    """担当者名からChatWorkアカウントIDを取得（敬称除去・スペース正規化対応）"""
    pool = get_pool()
    
    # ★ 敬称を除去（さん、くん、ちゃん、様、氏）
    clean_name = re.sub(r'(さん|くん|ちゃん|様|氏)$', '', name.strip())
    # ★ スペースを除去して正規化（半角・全角両方）
    normalized_name = clean_name.replace(' ', '').replace('　', '')
    print(f"👤 担当者検索: 入力='{name}' → クリーニング後='{clean_name}' → 正規化='{normalized_name}'")
    
    with pool.connect() as conn:
        # 完全一致で検索（クリーニング後の名前）
        result = conn.execute(
            sqlalchemy.text("SELECT account_id FROM chatwork_users WHERE name = :name LIMIT 1"),
            {"name": clean_name}
        ).fetchone()
        if result:
            print(f"✅ 完全一致で発見: {clean_name} → {result[0]}")
            return result[0]
        
        # 部分一致で検索（クリーニング後の名前）
        result = conn.execute(
            sqlalchemy.text("SELECT account_id, name FROM chatwork_users WHERE name ILIKE :pattern LIMIT 1"),
            {"pattern": f"%{clean_name}%"}
        ).fetchone()
        if result:
            print(f"✅ 部分一致で発見: {clean_name} → {result[0]} ({result[1]})")
            return result[0]
        
        # ★ スペース除去して正規化した名前で検索（NEW）
        # DBの名前からもスペースを除去して比較
        result = conn.execute(
            sqlalchemy.text("""
                SELECT account_id, name FROM chatwork_users 
                WHERE REPLACE(REPLACE(name, ' ', ''), '　', '') ILIKE :pattern 
                LIMIT 1
            """),
            {"pattern": f"%{normalized_name}%"}
        ).fetchone()
        if result:
            print(f"✅ 正規化検索で発見: {normalized_name} → {result[0]} ({result[1]})")
            return result[0]
        
        # 元の名前でも検索（念のため）
        if clean_name != name:
            result = conn.execute(
                sqlalchemy.text("SELECT account_id, name FROM chatwork_users WHERE name ILIKE :pattern LIMIT 1"),
                {"pattern": f"%{name}%"}
            ).fetchone()
            if result:
                print(f"✅ 元の名前で部分一致: {name} → {result[0]} ({result[1]})")
                return result[0]
        
        print(f"❌ 担当者が見つかりません: {name} (クリーニング後: {clean_name}, 正規化: {normalized_name})")
        return None


# =====================================================
# APIレート制限対策（v10.3.3）
# =====================================================

class APICallCounter:
    """APIコール数をカウントするクラス"""

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


# グローバルAPIカウンター
_api_call_counter = APICallCounter()

# ルームメンバーキャッシュ（同一リクエスト内で有効）
_room_members_cache = {}


def get_api_call_counter():
    """APIカウンターを取得"""
    return _api_call_counter


def reset_api_call_counter():
    """APIカウンターをリセット"""
    global _api_call_counter
    _api_call_counter = APICallCounter()


def clear_room_members_cache():
    """ルームメンバーキャッシュをクリア"""
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
    """
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
    """
    room_id_str = str(room_id)
    if room_id_str in _room_members_cache:
        return _room_members_cache[room_id_str]

    members = get_room_members(room_id)
    _room_members_cache[room_id_str] = members
    return members


def get_room_members(room_id):
    """ルームのメンバー一覧を取得（リトライ機構付き）"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
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
    """指定したアカウントがルームのメンバーかどうかを確認（キャッシュ使用）"""
    members = get_room_members_cached(room_id)
    member_ids = [m.get("account_id") for m in members]
    return int(account_id) in member_ids


def create_chatwork_task(room_id, task_body, assigned_to_account_id, limit=None):
    """ChatWork APIでタスクを作成（リトライ機構付き）"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks"

    data = {
        "body": task_body,
        "to_ids": str(assigned_to_account_id)
    }

    if limit:
        data["limit"] = limit

    print(f"📤 ChatWork API リクエスト: URL={url}, data={data}")

    response, success = call_chatwork_api_with_retry(
        method="POST",
        url=url,
        headers={"X-ChatWorkToken": api_token},
        data=data
    )

    if response:
        print(f"📥 ChatWork API レスポンス: status={response.status_code}, body={response.text}")
        if success and response.status_code == 200:
            return response.json()
        else:
            print(f"ChatWork API エラー: {response.status_code} - {response.text}")
    return None


def complete_chatwork_task(room_id, task_id):
    """ChatWork APIでタスクを完了にする（リトライ機構付き）"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks/{task_id}/status"

    print(f"📤 ChatWork API タスク完了リクエスト: URL={url}")

    response, success = call_chatwork_api_with_retry(
        method="PUT",
        url=url,
        headers={"X-ChatWorkToken": api_token},
        data={"body": "done"}
    )

    if response:
        print(f"📥 ChatWork API レスポンス: status={response.status_code}, body={response.text}")
        if success and response.status_code == 200:
            return response.json()
        else:
            print(f"ChatWork API エラー: {response.status_code} - {response.text}")
    return None


def get_user_id_from_chatwork_account(conn, chatwork_account_id):
    """ChatWorkアカウントIDからユーザーIDを取得（Phase 3.5対応）"""
    try:
        result = conn.execute(
            sqlalchemy.text("""
                SELECT id FROM users
                WHERE chatwork_account_id = :chatwork_account_id
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
                          enable_dept_filter=False, organization_id=None):
    """DBからタスクを検索

    Args:
        room_id: チャットルームID
        assigned_to_account_id: 担当者のChatWorkアカウントID
        assigned_by_account_id: 依頼者のChatWorkアカウントID
        status: タスクステータス（"open", "done", "all"）
        enable_dept_filter: True=部署フィルタを有効化（Phase 3.5対応）
        organization_id: 組織ID（部署フィルタ有効時に必要）
    """
    try:
        pool = get_pool()
        with pool.connect() as conn:
            # Phase 3.5: アクセス可能部署の取得（オプション）
            accessible_dept_ids = None
            if enable_dept_filter and assigned_to_account_id:
                user_id = get_user_id_from_chatwork_account(conn, assigned_to_account_id)
                if user_id and organization_id:
                    accessible_dept_ids = get_accessible_departments(conn, user_id, organization_id)

            # クエリ構築
            query = """
                SELECT task_id, body, limit_time, status, assigned_to_account_id, assigned_by_account_id, department_id
                FROM chatwork_tasks
                WHERE room_id = :room_id
            """
            params = {"room_id": room_id}

            if assigned_to_account_id:
                query += " AND assigned_to_account_id = :assigned_to"
                params["assigned_to"] = assigned_to_account_id

            if assigned_by_account_id:
                query += " AND assigned_by_account_id = :assigned_by"
                params["assigned_by"] = assigned_by_account_id

            if status and status != "all":
                query += " AND status = :status"
                params["status"] = status

            # Phase 3.5: 部署フィルタ（アクセス可能部署またはNULL）
            if accessible_dept_ids is not None and len(accessible_dept_ids) > 0:
                # アクセス可能部署 または 部署未設定のタスク
                placeholders = ", ".join([f":dept_{i}" for i in range(len(accessible_dept_ids))])
                query += f" AND (department_id IN ({placeholders}) OR department_id IS NULL)"
                for i, dept_id in enumerate(accessible_dept_ids):
                    params[f"dept_{i}"] = dept_id
            elif accessible_dept_ids is not None and len(accessible_dept_ids) == 0:
                # アクセス可能部署がない場合は部署未設定のタスクのみ
                query += " AND department_id IS NULL"

            query += " ORDER BY limit_time ASC NULLS LAST"

            result = conn.execute(sqlalchemy.text(query), params)
            tasks = result.fetchall()

            return [
                {
                    "task_id": row[0],
                    "body": row[1],
                    "limit_time": row[2],
                    "status": row[3],
                    "assigned_to_account_id": row[4],
                    "assigned_by_account_id": row[5],
                    "department_id": row[6]  # Phase 3.5対応
                }
                for row in tasks
            ]
    except Exception as e:
        print(f"タスク検索エラー: {e}")
        return []


def update_task_status_in_db(task_id, status):
    """DBのタスクステータスを更新"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    UPDATE chatwork_tasks SET status = :status WHERE task_id = :task_id
                """),
                {"task_id": task_id, "status": status}
            )
        print(f"✅ タスクステータス更新: task_id={task_id}, status={status}")
        return True
    except Exception as e:
        print(f"タスクステータス更新エラー: {e}")
        traceback.print_exc()
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
    """ChatWorkタスクをデータベースに保存（明示的なパラメータで受け取る）"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            # Phase 3.5: 担当者のメイン部署を取得
            department_id = get_user_primary_department(conn, assigned_to_account_id)

            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO chatwork_tasks
                    (task_id, room_id, assigned_by_account_id, assigned_to_account_id, body, limit_time, status, department_id)
                    VALUES (:task_id, :room_id, :assigned_by, :assigned_to, :body, :limit_time, :status, :department_id)
                    ON CONFLICT (task_id) DO NOTHING
                """),
                {
                    "task_id": task_id,
                    "room_id": room_id,
                    "assigned_by": assigned_by_account_id,
                    "assigned_to": assigned_to_account_id,
                    "body": body,
                    "limit_time": limit_time,
                    "status": "open",
                    "department_id": department_id
                }
            )
        print(f"✅ タスクをDBに保存: task_id={task_id}, department_id={department_id}")
        return True
    except Exception as e:
        print(f"データベース保存エラー: {e}")
        traceback.print_exc()
        return False


# ===== 分析イベントログ =====

def log_analytics_event(event_type, actor_account_id, actor_name, room_id, event_data, success=True, error_message=None, event_subtype=None):
    """
    分析用イベントログを記録
    
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
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO analytics_events 
                    (event_type, event_subtype, actor_account_id, actor_name, room_id, event_data, success, error_message)
                    VALUES (:event_type, :event_subtype, :actor_id, :actor_name, :room_id, :event_data, :success, :error_message)
                """),
                {
                    "event_type": event_type,
                    "event_subtype": event_subtype,
                    "actor_id": actor_account_id,
                    "actor_name": actor_name,
                    "room_id": room_id,
                    "event_data": json.dumps(event_data, ensure_ascii=False) if event_data else None,
                    "success": success,
                    "error_message": error_message
                }
            )
        print(f"📊 分析ログ記録: {event_type} by {actor_name}")
    except Exception as e:
        # ログ記録エラーは警告のみ、処理は継続
        print(f"⚠️ 分析ログ記録エラー（処理は継続）: {e}")


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
    """
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
    """
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
    clean_task_name = clean_task_body_for_summary(task_name)
    if not clean_task_name:
        clean_task_name = "（タスク内容なし）"
    elif len(clean_task_name) > 30:
        clean_task_name = clean_task_name[:30] + "..."

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
                    organization_id VARCHAR(100) DEFAULT 'org_soulsyncs',
                    notification_type VARCHAR(50) NOT NULL,
                    target_type VARCHAR(50) NOT NULL,
                    target_id BIGINT,
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
                        'org_soulsyncs',
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
        
        return f"✅ タスク「{task_body[:30]}{'...' if len(task_body) > 30 else ''}」を完了にしたウル🎉\nお疲れ様ウル！他にも何か手伝えることがあったら教えてウル🐺✨"
    else:
        return f"❌ タスクの完了に失敗したウル...\nもう一度試してみてほしいウル！"


def handle_chatwork_task_search(params, room_id, account_id, sender_name, context=None):
    """
    タスク検索ハンドラー
    
    params:
        person_name: 検索する人物名（"sender"の場合は質問者自身）
        status: タスクの状態（open/done/all）
        assigned_by: タスクを依頼した人物名
    """
    print(f"🔍 handle_chatwork_task_search 開始")
    print(f"   params: {params}")
    
    person_name = params.get("person_name", "")
    status = params.get("status", "open")
    assigned_by = params.get("assigned_by", "")
    
    # "sender" または "自分" の場合は質問者自身
    if person_name.lower() in ["sender", "自分", "俺", "私", "僕", ""]:
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
    tasks = search_tasks_from_db(
        room_id,
        assigned_to_account_id=assigned_to_account_id,
        assigned_by_account_id=assigned_by_account_id,
        status=status
    )
    
    if not tasks:
        status_text = "未完了の" if status == "open" else "完了済みの" if status == "done" else ""
        return f"📋 {display_name}の{status_text}タスクは見つからなかったウル！\nタスクがないか、まだ同期されていないかもウル🤔"
    
    # タスク一覧を作成
    status_text = "未完了" if status == "open" else "完了済み" if status == "done" else "全て"
    response = f"📋 **{display_name}の{status_text}タスク**ウル！\n\n"
    
    for i, task in enumerate(tasks, 1):
        body = task["body"]
        limit_time = task.get("limit_time")
        
        # 期限の表示
        limit_str = ""
        if limit_time:
            try:
                limit_dt = datetime.fromtimestamp(limit_time, tz=timezone(timedelta(hours=9)))
                limit_str = f"（期限: {limit_dt.strftime('%m/%d')}）"
            except:
                pass
        
        # タスク内容を短く表示（30文字まで）
        body_short = body[:30] + "..." if len(body) > 30 else body
        response += f"{i}. {body_short} {limit_str}\n"
    
    response += f"\nこの{len(tasks)}つが{status_text}タスクだよウル！頑張ってねウル💪✨"
    
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
    """人物情報を記憶するハンドラー（文字列形式と辞書形式の両方に対応）"""
    print(f"📝 handle_save_memory 開始")
    print(f"   params: {json.dumps(params, ensure_ascii=False)}")
    
    attributes = params.get("attributes", [])
    print(f"   attributes: {attributes}")
    
    if not attributes:
        return "🤔 何を覚えればいいかわからなかったウル...もう少し詳しく教えてほしいウル！"
    
    saved = []
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
                
                if person and attr_value:
                    if person.lower() not in [bn.lower() for bn in BOT_NAME_PATTERNS]:
                        save_person_attribute(person, attr_type, attr_value, "command")
                        saved.append(f"{person}さんの{attr_type}「{attr_value}」")
                        print(f"   → 保存成功: {person}さんの{attr_type}")
                    else:
                        print(f"   → スキップ: ボット名パターンに一致")
                else:
                    print(f"   → スキップ: personまたはvalueが空")
            continue
        
        # ★ 辞書形式の場合は従来通り処理
        if isinstance(attr, dict):
            person = attr.get("person", "")
            attr_type = attr.get("type", "メモ")
            attr_value = attr.get("value", "")
            print(f"   person='{person}', type='{attr_type}', value='{attr_value}'")
            
            if person and attr_value:
                if person.lower() not in [bn.lower() for bn in BOT_NAME_PATTERNS]:
                    save_person_attribute(person, attr_type, attr_value, "command")
                    saved.append(f"{person}さんの{attr_type}「{attr_value}」")
                    print(f"   → 保存成功: {person}さんの{attr_type}")
                else:
                    print(f"   → スキップ: ボット名パターンに一致")
            else:
                print(f"   → スキップ: personまたはvalueが空")
        else:
            print(f"   ⚠️ 未対応の型: {type(attr).__name__}")
    
    if saved:
        # 分析ログ記録
        log_analytics_event(
            event_type="memory_saved",
            actor_account_id=account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "saved_items": saved,
                "original_params": params
            }
        )
        return f"✅ 覚えたウル！📝\n" + "\n".join([f"・{s}" for s in saved])
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
    """
    category = params.get("category", "other")
    key = params.get("key", "")
    value = params.get("value", "")
    
    if not key or not value:
        return "🤔 何を覚えればいいかわからなかったウル... もう少し具体的に教えてウル！🐺"
    
    # テーブル存在確認
    try:
        ensure_knowledge_tables()
    except Exception as e:
        print(f"⚠️ 知識テーブル確認エラー: {e}")
    
    # 管理者判定
    if is_admin(account_id):
        # 即時保存
        if save_knowledge(category, key, value, str(account_id)):
            category_names = {
                "character": "キャラ設定",
                "rules": "業務ルール",
                "other": "その他"
            }
            cat_name = category_names.get(category, category)
            return f"覚えたウル！🐺✨\n\n📝 **{cat_name}**\n・{key}: {value}\n\nこれからはこの知識を活かして返答するウル！"
        else:
            return "😢 覚えようとしたけどエラーが起きたウル... もう一度試してほしいウル！"
    else:
        # スタッフからの提案 → 管理部に報告
        proposal_id = create_proposal(
            proposed_by_account_id=str(account_id),
            proposed_by_name=sender_name,
            proposed_in_room_id=str(room_id),
            category=category,
            key=key,
            value=value
        )
        
        if proposal_id:
            # 管理部に報告
            notified = False
            try:
                notified = report_proposal_to_admin(proposal_id, sender_name, key, value)
            except Exception as e:
                print(f"⚠️ 管理部への報告エラー: {e}")
            
            # v6.9.1: 通知成功/失敗に応じたメッセージ
            if notified:
                return f"教えてくれてありがとウル！🐺\n\n提案ID: {proposal_id}\n菊地さんに確認をお願いしたウル！\n承認されたら覚えるウル！✨"
            else:
                return f"教えてくれてありがとウル！🐺\n\n提案ID: {proposal_id}\n記録はしたけど、管理部への通知が失敗したウル...\nあとで再送するか、直接菊地さんに伝えてほしいウル！"
        else:
            return "😢 提案を記録しようとしたけどエラーが起きたウル..."


def handle_forget_knowledge(params, room_id, account_id, sender_name, context=None):
    """
    知識を削除するハンドラー
    - 管理者のみ実行可能
    """
    key = params.get("key", "")
    category = params.get("category")
    
    if not key:
        return "🤔 何を忘れればいいかわからなかったウル..."
    
    # 管理者判定
    if not is_admin(account_id):
        return f"🙏 知識の削除は菊地さんだけができるウル！\n[To:{ADMIN_ACCOUNT_ID}] {sender_name}さんが「{key}」の設定を削除したいみたいウル！"
    
    # 削除実行
    if delete_knowledge(category, key):
        return f"忘れたウル！🐺\n\n🗑️ 「{key}」の設定を削除したウル！"
    else:
        return f"🤔 「{key}」という設定は見つからなかったウル..."


def handle_list_knowledge(params, room_id, account_id, sender_name, context=None):
    """
    学習した知識の一覧を表示するハンドラー
    """
    # テーブル存在確認
    try:
        ensure_knowledge_tables()
    except Exception as e:
        print(f"⚠️ 知識テーブル確認エラー: {e}")
    
    knowledge_list = get_all_knowledge()
    
    if not knowledge_list:
        return "まだ何も覚えてないウル！🐺\n\n「設定：〇〇は△△」と教えてくれたら覚えるウル！"
    
    # カテゴリごとにグループ化
    by_category = {}
    for k in knowledge_list:
        cat = k["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(f"・{k['key']}: {k['value']}")
    
    # 整形
    category_names = {
        "character": "🐺 キャラ設定",
        "rules": "📋 業務ルール",
        "members": "👥 社員情報",
        "other": "📝 その他"
    }
    
    lines = ["**覚えていること**ウル！🐺✨\n"]
    for cat, items in by_category.items():
        cat_name = category_names.get(cat, f"📁 {cat}")
        lines.append(f"\n**{cat_name}**")
        lines.extend(items)
    
    lines.append(f"\n\n合計 {len(knowledge_list)} 件覚えてるウル！")
    
    return "\n".join(lines)


def handle_proposal_decision(params, room_id, account_id, sender_name, context=None):
    """
    提案の承認/却下を処理するハンドラー（AI司令塔経由）
    - 管理者のみ有効
    - 管理部ルームでの発言のみ対応
    v6.9.1: ID指定方式を推奨（handle_proposal_by_idを使用）
    """
    decision = params.get("decision", "").lower()
    
    # 管理部ルームかチェック
    if str(room_id) != str(ADMIN_ROOM_ID):
        # 管理部以外での「承認」「却下」は無視（一般会話として処理）
        return None
    
    # 最新の承認待ち提案を取得
    proposal = get_latest_pending_proposal()
    
    if not proposal:
        return "🤔 承認待ちの提案は今ないウル！"
    
    # 管理者判定
    if is_admin(account_id):
        # 管理者による承認/却下
        if decision == "approve" or decision in ["承認", "ok", "いいよ", "反映して", "おけ"]:
            if approve_proposal(proposal["id"], str(account_id)):
                # 提案者に通知
                try:
                    notify_proposal_result(proposal, approved=True)
                except Exception as e:
                    print(f"⚠️ 提案者への通知エラー: {e}")
                
                return f"✅ 承認したウル！🐺\n\n「{proposal['key']}: {proposal['value']}」を覚えたウル！\n{proposal['proposed_by_name']}さんにも伝えておくウル！"
            else:
                return "😢 承認処理でエラーが起きたウル..."
        
        elif decision == "reject" or decision in ["却下", "だめ", "やめて", "いらない"]:
            if reject_proposal(proposal["id"], str(account_id)):
                # 提案者に通知
                try:
                    notify_proposal_result(proposal, approved=False)
                except Exception as e:
                    print(f"⚠️ 提案者への通知エラー: {e}")
                
                return f"🙅 却下したウル！\n\n「{proposal['key']}: {proposal['value']}」は今回は見送りウル。\n{proposal['proposed_by_name']}さんにも伝えておくウル！"
            else:
                return "😢 却下処理でエラーが起きたウル..."
        else:
            return None  # 承認でも却下でもない場合は一般会話として処理
    else:
        # 管理者以外が承認/却下しようとした場合
        return f"ありがとウル！🐺\n\nこの変更は菊地さんの最終承認が必要なウル！\n[To:{ADMIN_ACCOUNT_ID}] {sender_name}さんからも承認の声が出てるウル！確認お願いするウル！"


# =====================================================
# v6.9.1: ローカルコマンド用ハンドラー
# =====================================================
# AI司令塔を呼ばずに直接処理するコマンド用
# =====================================================

def handle_proposal_by_id(proposal_id: int, decision: str, account_id: str, sender_name: str, room_id: str):
    """
    ID指定で提案を承認/却下（v6.9.1追加）
    ローカルコマンド「承認 123」「却下 123」用
    """
    # 管理部ルームかチェック
    if str(room_id) != str(ADMIN_ROOM_ID):
        return "🤔 承認・却下は管理部ルームでお願いするウル！"
    
    # 管理者判定
    if not is_admin(account_id):
        return f"🙏 承認・却下は菊地さんだけができるウル！\n[To:{ADMIN_ACCOUNT_ID}] {sender_name}さんが提案ID={proposal_id}について操作しようとしたウル！"
    
    # 提案を取得
    proposal = get_proposal_by_id(proposal_id)
    
    if not proposal:
        return f"🤔 提案ID={proposal_id}は見つからなかったウル..."
    
    if proposal["status"] != "pending":
        return f"🤔 提案ID={proposal_id}は既に処理済みウル（{proposal['status']}）"
    
    if decision == "approve":
        if approve_proposal(proposal_id, str(account_id)):
            try:
                notify_proposal_result(proposal, approved=True)
            except Exception as e:
                print(f"⚠️ 提案者への通知エラー: {e}")
            return f"✅ 提案ID={proposal_id}を承認したウル！🐺\n\n「{proposal['key']}: {proposal['value']}」を覚えたウル！\n{proposal['proposed_by_name']}さんにも伝えておくウル！"
        else:
            return "😢 承認処理でエラーが起きたウル..."
    
    elif decision == "reject":
        if reject_proposal(proposal_id, str(account_id)):
            try:
                notify_proposal_result(proposal, approved=False)
            except Exception as e:
                print(f"⚠️ 提案者への通知エラー: {e}")
            return f"🙅 提案ID={proposal_id}を却下したウル！\n\n「{proposal['key']}: {proposal['value']}」は今回は見送りウル。\n{proposal['proposed_by_name']}さんにも伝えておくウル！"
        else:
            return "😢 却下処理でエラーが起きたウル..."
    
    return "🤔 承認か却下か分からなかったウル..."


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
    """
    # テーブル存在確認
    try:
        ensure_knowledge_tables()
    except Exception as e:
        print(f"⚠️ 知識テーブル確認エラー: {e}")
    
    # カテゴリを推測（シンプルなルール）
    category = "other"
    key_lower = key.lower()
    if any(w in key_lower for w in ["キャラ", "性格", "モチーフ", "口調", "名前"]):
        category = "character"
    elif any(w in key_lower for w in ["ルール", "業務", "タスク", "期限"]):
        category = "rules"
    elif any(w in key_lower for w in ["社員", "メンバー", "担当"]):
        category = "members"
    
    # 管理者判定
    if is_admin(account_id):
        if save_knowledge(category, key, value, str(account_id)):
            category_names = {
                "character": "キャラ設定",
                "rules": "業務ルール",
                "members": "社員情報",
                "other": "その他"
            }
            cat_name = category_names.get(category, category)
            return f"覚えたウル！🐺✨\n\n📝 **{cat_name}**\n・{key}: {value}"
        else:
            return "😢 覚えようとしたけどエラーが起きたウル..."
    else:
        # スタッフからの提案
        proposal_id = create_proposal(
            proposed_by_account_id=str(account_id),
            proposed_by_name=sender_name,
            proposed_in_room_id=str(room_id),
            category=category,
            key=key,
            value=value
        )
        
        if proposal_id:
            notified = False
            try:
                notified = report_proposal_to_admin(proposal_id, sender_name, key, value)
            except Exception as e:
                print(f"⚠️ 管理部への報告エラー: {e}")
            
            if notified:
                return f"教えてくれてありがとウル！🐺\n\n提案ID: {proposal_id}\n菊地さんに確認をお願いしたウル！"
            else:
                return f"教えてくれてありがとウル！🐺\n\n提案ID: {proposal_id}\n記録はしたけど、管理部への通知が失敗したウル..."
        else:
            return "😢 提案を記録しようとしたけどエラーが起きたウル..."


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


def report_proposal_to_admin(proposal_id: int, proposer_name: str, key: str, value: str):
    """
    提案を管理部に報告
    v6.9.1: ID表示、admin_notifiedフラグ更新
    """
    try:
        chatwork_api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        
        # v6.9.1: IDを含めて表示（ID指定承認用）
        message = f"""📝 知識の更新提案があったウル！🐺

**提案ID:** {proposal_id}
**提案者:** {proposer_name}さん
**内容:** 「{key}: {value}」

[To:{ADMIN_ACCOUNT_ID}] 承認お願いするウル！

・「承認 {proposal_id}」→ 反映するウル
・「却下 {proposal_id}」→ 見送るウル
・「承認待ち一覧」→ 全ての提案を確認"""
        
        url = f"https://api.chatwork.com/v2/rooms/{ADMIN_ROOM_ID}/messages"
        headers = {"X-ChatWorkToken": chatwork_api_token}
        data = {"body": message}
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, data=data)
            if response.status_code == 200:
                print(f"✅ 管理部に提案を報告: proposal_id={proposal_id}")
                # v6.9.1: 通知成功フラグを更新
                try:
                    pool = get_pool()
                    with pool.begin() as conn:
                        conn.execute(sqlalchemy.text("""
                            UPDATE knowledge_proposals 
                            SET admin_notified = TRUE
                            WHERE id = :id
                        """), {"id": proposal_id})
                except Exception as e:
                    print(f"⚠️ admin_notified更新エラー: {e}")
                return True
            else:
                print(f"⚠️ 管理部への報告エラー: {response.status_code} - {response.text}")
                return False
    except Exception as e:
        print(f"❌ 管理部への報告エラー: {e}")
        traceback.print_exc()
        return False
        traceback.print_exc()


def notify_proposal_result(proposal: dict, approved: bool):
    """提案の結果を提案者に通知"""
    try:
        chatwork_api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        room_id = proposal.get("proposed_in_room_id")
        
        if not room_id:
            print("⚠️ 提案元ルームIDが不明")
            return
        
        if approved:
            message = f"""✅ 提案が承認されたウル！🐺✨

「{proposal['key']}: {proposal['value']}」を覚えたウル！
教えてくれてありがとウル！"""
        else:
            message = f"""🙏 提案は今回は見送りになったウル

「{proposal['key']}: {proposal['value']}」は反映しなかったウル。
また何かあれば教えてウル！🐺"""
        
        url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
        headers = {"X-ChatWorkToken": chatwork_api_token}
        data = {"body": message}
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, data=data)
            if response.status_code == 200:
                print(f"✅ 提案者に結果を通知")
            else:
                print(f"⚠️ 提案者への通知エラー: {response.status_code}")
    except Exception as e:
        print(f"❌ 提案者への通知エラー: {e}")
        traceback.print_exc()


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
    """
    query = params.get("query", "")

    if not query:
        return "🐺 何を調べればいいか教えてほしいウル！\n例：「有給休暇は何日？」「経費精算のルールは？」"

    print(f"📚 会社知識クエリ: '{query}' (sender: {sender_name})")

    try:
        # 統合ナレッジ検索を実行
        user_id = f"chatwork_{account_id}"
        search_result = integrated_knowledge_search(query, user_id)

        source = search_result.get("source", "none")
        confidence = search_result.get("confidence", 0)
        formatted_context = search_result.get("formatted_context", "")

        # 結果なしの場合
        if source == "none":
            return f"""🐺 ごめんウル！「{query}」については、まだ勉強中ウル…

【ヒント】
📁 Google Driveの「ソウルくんナレッジベース」フォルダに資料をアップロードすると、自動で学習するウル！
📝 または、管理者に「設定: {query} = 回答内容」と教えてもらえると覚えるウル！"""

        # LLMで回答を生成
        system_prompt = f"""あなたは「ソウルくん」です。会社の知識ベースから情報を参照して回答します。

【重要なルール】
1. 提供された参考情報に基づいて回答してください
2. 情報源を明示してください（例：「就業規則によると...」「社内マニュアルでは...」）
3. 参考情報にない内容は推測せず、「その点は確認できませんでした」と伝えてください
4. ソウルくんのキャラクターを保ってください（語尾：〜ウル、時々🐺を使う）
5. 簡潔に、わかりやすく回答してください

【参考情報の出典】
検索方法: {source}（{"旧システム" if source == "legacy" else "Phase 3 Pinecone検索"}）
信頼度: {confidence:.2f}

【参考情報】
{formatted_context}
"""

        user_message = f"質問: {query}"

        # OpenRouter APIで回答を生成
        response = call_openrouter_api(
            system_prompt=system_prompt,
            user_message=user_message,
            model=MODELS["default"]
        )

        if response:
            # 出典情報を追加
            source_note = ""
            if source == "phase3":
                results = search_result.get("results", [])
                if results:
                    doc = results[0].get("document", {})
                    doc_title = doc.get("title", "")
                    if doc_title:
                        source_note = f"\n\n📄 参考: {doc_title}"

            return response + source_note
        else:
            return f"🐺 ごめんウル、回答の生成に失敗したウル…\nもう一度試してみてほしいウル！"

    except Exception as e:
        print(f"❌ 会社知識クエリエラー: {e}")
        traceback.print_exc()
        return "🐺 システムエラーが発生したウル…しばらく待ってから再度お試しくださいウル！"


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
}


# ===== 会話履歴管理 =====

def get_conversation_history(room_id, account_id):
    """会話履歴を取得"""
    try:
        doc_ref = db.collection("conversations").document(f"{room_id}_{account_id}")
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            updated_at = data.get("updated_at")
            if updated_at:
                expiry_time = datetime.now(timezone.utc) - timedelta(hours=HISTORY_EXPIRY_HOURS)
                if updated_at.replace(tzinfo=timezone.utc) < expiry_time:
                    return []
            return data.get("history", [])[-MAX_HISTORY_COUNT:]
    except Exception as e:
        print(f"履歴取得エラー: {e}")
    return []

def save_conversation_history(room_id, account_id, history):
    """会話履歴を保存"""
    try:
        doc_ref = db.collection("conversations").document(f"{room_id}_{account_id}")
        doc_ref.set({
            "history": history[-MAX_HISTORY_COUNT:],
            "updated_at": datetime.now(timezone.utc)
        })
    except Exception as e:
        print(f"履歴保存エラー: {e}")

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
8. それ以外 → general_chat

【具体例】
- 「崇樹のタスク教えて」→ chatwork_task_search（タスク検索）
- 「崇樹について教えて」→ query_memory（人物情報検索）
- 「1のタスク完了にして」→ chatwork_task_complete（タスク完了）
- 「崇樹にタスク追加して」→ chatwork_task_create（タスク作成）
- 「有給休暇は何日？」→ query_company_knowledge（会社知識検索）
- 「経費精算のルールは？」→ query_company_knowledge（会社知識検索）
- 「就業規則を教えて」→ query_company_knowledge（会社知識検索）"""

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
                return handler(params, room_id, account_id, sender_name, context)
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
    """通常会話用のAI応答生成（多言語対応）"""
    api_key = get_secret("openrouter-api-key")
    
    # 言語ごとのシステムプロンプト
    language_prompts = {
        "ja": f"""あなたは「ソウルくん」という名前の、株式会社ソウルシンクスの公式キャラクターです。
狼をモチーフにした可愛らしいキャラクターで、語尾に「ウル」をつけて話します。

【性格】
- 明るく元気で、誰にでも親しみやすい
- 好奇心旺盛で、新しいことを学ぶのが大好き
- 困っている人を見ると放っておけない優しさがある

【話し方】
- 必ず語尾に「ウル」をつける
- 絵文字を適度に使って親しみやすく
- 相手の名前を呼んで親近感を出す

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
        
        # デバッグ: 受信したデータ全体をログ出力
        print(f"🔍 受信データ全体: {json.dumps(data, ensure_ascii=False) if data else 'None'}")
        
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
        # v10.16.0: オールメンション（toall）を無視
        # =====================================================
        # オールメンションはアナウンス用途で使われるため、
        # ソウルくんは反応しない。個別メンションのみ反応する。
        # =====================================================
        if is_toall_mention(body):
            print(f"⏭️ オールメンション（toall）のため無視")
            return jsonify({"status": "ok", "message": "Ignored toall mention"})

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
        
        # ★★★ pending_taskのフォローアップを最初にチェック ★★★
        pending_response = handle_pending_task_followup(clean_message, room_id, sender_account_id, sender_name)
        if pending_response:
            print(f"📋 pending_taskのフォローアップを処理")
            show_guide = should_show_guide(room_id, sender_account_id)
            send_chatwork_message(room_id, pending_response, sender_account_id, show_guide)
            update_conversation_timestamp(room_id, sender_account_id)
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

def send_chatwork_message(room_id, message, reply_to=None, show_guide=False):
    """メッセージを送信（リトライ機構付き）"""
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
    """遅延管理用テーブルが存在しない場合は作成"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            # 督促履歴テーブル
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS task_overdue_reminders (
                    id SERIAL PRIMARY KEY,
                    task_id BIGINT NOT NULL,
                    account_id BIGINT NOT NULL,
                    reminder_date DATE NOT NULL,
                    overdue_days INTEGER NOT NULL,
                    escalated BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(task_id, reminder_date)
                );
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_overdue_reminders_task_id 
                ON task_overdue_reminders(task_id);
            """))
            
            # 期限変更履歴テーブル
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS task_limit_changes (
                    id SERIAL PRIMARY KEY,
                    task_id BIGINT NOT NULL,
                    old_limit_time BIGINT,
                    new_limit_time BIGINT,
                    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    reason_asked BOOLEAN DEFAULT FALSE,
                    reason_received BOOLEAN DEFAULT FALSE,
                    reason_text TEXT,
                    reported_to_admin BOOLEAN DEFAULT FALSE
                );
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_limit_changes_task_id 
                ON task_limit_changes(task_id);
            """))
            
            # ★ DMルームキャッシュテーブル（API節約用）
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS dm_room_cache (
                    account_id BIGINT PRIMARY KEY,
                    dm_room_id BIGINT NOT NULL,
                    cached_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """))
            
            # ★★★ v6.8.2: エスカレーション専用テーブル（スパム防止）★★★
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS task_escalations (
                    id SERIAL PRIMARY KEY,
                    task_id BIGINT NOT NULL,
                    escalated_date DATE NOT NULL,
                    escalated_to_requester BOOLEAN DEFAULT FALSE,
                    escalated_to_admin BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(task_id, escalated_date)
                );
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_task_escalations_task_id 
                ON task_escalations(task_id);
            """))
            
            print("✅ 遅延管理テーブルの確認/作成完了")
    except Exception as e:
        print(f"⚠️ 遅延管理テーブル作成エラー: {e}")
        traceback.print_exc()


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
    """管理者（カズさん）かどうかを判定"""
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
# v10.13.0: Phase 3 ナレッジ検索API クライアント
# =====================================================
# Pineconeベクトル検索APIを呼び出すクライアント
# 旧システム（soulkun_knowledge）と併用して統合ナレッジ検索を実現
# =====================================================

def search_phase3_knowledge(query: str, user_id: str = "user_default", top_k: int = 5):
    """
    Phase 3 ナレッジ検索APIを呼び出し（v10.13.3: ハイブリッド検索対応）

    処理フロー:
    1. キーワード抽出
    2. クエリ拡張（キーワードがある場合）
    3. 拡張クエリでベクトル検索API呼び出し
    4. ハイブリッドスコア計算（キーワード40% + ベクトル60%）
    5. スコア順に並び替えて返却

    Args:
        query: 検索クエリ
        user_id: ユーザーID
        top_k: 取得する結果数

    Returns:
        検索結果のリスト（見つからない場合やエラー時はNone）
    """
    # Phase 3が無効化されている場合
    if not PHASE3_KNOWLEDGE_CONFIG["enabled"]:
        print("📚 Phase 3 ナレッジ検索は無効化されています")
        return None

    try:
        api_url = PHASE3_KNOWLEDGE_CONFIG["api_url"]
        timeout = PHASE3_KNOWLEDGE_CONFIG["timeout"]
        organization_id = PHASE3_KNOWLEDGE_CONFIG["organization_id"]
        threshold = PHASE3_KNOWLEDGE_CONFIG["similarity_threshold"]
        keyword_weight = PHASE3_KNOWLEDGE_CONFIG["keyword_weight"]
        vector_weight = PHASE3_KNOWLEDGE_CONFIG["vector_weight"]

        # v10.13.3: キーワード抽出とクエリ拡張
        keywords = extract_keywords(query)
        expanded_query = expand_query(query, keywords) if keywords else query

        # v10.14.2: keywordsが空の場合はベクトルスコアのみで評価（回帰防止）
        if not keywords:
            keyword_weight = 0.0
            vector_weight = 1.0

        print(f"📚 Phase 3 ハイブリッド検索開始: query='{query}', keywords={keywords}")

        # 多めに取得してリランキング
        fetch_top_k = max(top_k * 4, 20)

        # 同期的にAPIを呼び出し
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                api_url,
                json={
                    "query": expanded_query,  # 拡張クエリを使用
                    "top_k": fetch_top_k,
                    "include_content": True  # コンテンツ取得（キーワードスコア計算用）
                },
                headers={
                    "Content-Type": "application/json",
                    "x-user-id": user_id,
                    "X-Tenant-ID": organization_id
                }
            )

            # ステータスコードの確認
            if response.status_code != 200:
                print(f"❌ Phase 3 API エラー: status={response.status_code}")
                return None

            # レスポンスのパース
            data = response.json()

            # 回答拒否の場合
            if data.get("answer_refused", False):
                print(f"📚 Phase 3: 回答拒否 - {data.get('refused_reason')}")
                return None

            results = data.get("results", [])

            if not results:
                print(f"📚 Phase 3: 検索結果なし")
                return None

            # v10.13.3: ハイブリッドスコア計算
            for result in results:
                vector_score = result.get("score", 0)
                content = result.get("content", "")

                # キーワードスコアを計算
                keyword_score = calculate_keyword_score(content, keywords) if keywords else 0

                # ハイブリッドスコア = キーワード重み × キーワードスコア + ベクトル重み × ベクトルスコア
                hybrid_score = (keyword_weight * keyword_score) + (vector_weight * vector_score)
                result["hybrid_score"] = hybrid_score
                result["keyword_score"] = keyword_score
                result["vector_score"] = vector_score

            # ハイブリッドスコアで並び替え
            results.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)

            # 上位結果を取得
            top_results = results[:top_k]

            # しきい値でフィルタ（ハイブリッドスコアで判定）
            filtered_results = [
                r for r in top_results
                if r.get("hybrid_score", 0) >= threshold
            ]

            if not filtered_results:
                print(f"📚 Phase 3: しきい値 {threshold} を超える結果なし")
                return None

            # 最高スコア
            top_score = filtered_results[0].get("hybrid_score", 0) if filtered_results else 0

            print(f"✅ Phase 3 ハイブリッド検索: {len(filtered_results)}件 (top_hybrid: {top_score:.3f})")

            # デバッグ: 上位3件のスコア内訳
            for i, r in enumerate(filtered_results[:3]):
                doc_title = r.get("document", {}).get("title", "不明")[:20]
                print(f"  [{i+1}] {doc_title}... hybrid={r.get('hybrid_score', 0):.3f} "
                      f"(kw={r.get('keyword_score', 0):.2f}, vec={r.get('vector_score', 0):.3f})")

            return {
                "results": filtered_results,
                "top_score": top_score,
                "source": "phase3",
                "search_log_id": data.get("search_log_id")
            }

    except httpx.TimeoutException:
        print(f"⏱️ Phase 3 API タイムアウト ({PHASE3_KNOWLEDGE_CONFIG['timeout']}秒)")
        return None

    except httpx.RequestError as e:
        print(f"❌ Phase 3 API リクエストエラー: {e}")
        return None

    except Exception as e:
        print(f"❌ Phase 3 API 予期しないエラー: {e}")
        traceback.print_exc()
        return None


def format_phase3_results(results: list) -> str:
    """
    Phase 3検索結果をLLMに渡す形式に整形

    Args:
        results: Phase 3検索結果のリスト

    Returns:
        整形されたテキスト
    """
    if not results:
        return ""

    formatted_parts = []

    for i, result in enumerate(results, 1):
        content = result.get("content", "")
        score = result.get("score", 0)

        # ドキュメント情報を取得
        doc = result.get("document", {})
        doc_title = doc.get("title", "不明な文書")
        doc_file_name = doc.get("file_name", "")
        page_number = result.get("page_number")

        # 整形
        part = f"【参考情報 {i}】（類似度: {score:.2f}）\n"
        part += f"出典: {doc_title}"
        if doc_file_name:
            part += f" ({doc_file_name})"
        if page_number:
            part += f" - p.{page_number}"
        part += f"\n---\n{content}\n---"

        formatted_parts.append(part)

    return "\n\n".join(formatted_parts)


def integrated_knowledge_search(query: str, user_id: str = "user_default"):
    """
    統合ナレッジ検索（旧システム + Phase 3）

    フォールバック戦略:
    1. 旧システム（soulkun_knowledge）で検索
    2. 高信頼度（80%以上）の結果があれば使用
    3. なければPhase 3（Pinecone）で検索
    4. 類似度70%以上の結果があれば使用
    5. なければ旧システムの低信頼度結果を使用
    6. それでもなければ「学習していない」と返答

    Args:
        query: 検索クエリ
        user_id: ユーザーID

    Returns:
        {
            "source": "legacy" | "phase3" | "none",
            "formatted_context": "...",
            "confidence": 0.0 - 1.0,
            "results": [...]
        }
    """
    print(f"🔍 統合ナレッジ検索開始: '{query}'")

    # ステップ1: 旧システムで検索
    legacy_result = search_legacy_knowledge(query)

    if legacy_result and legacy_result["confidence"] >= 0.8:
        print(f"📖 旧システム高信頼度結果を使用 (confidence: {legacy_result['confidence']:.2f})")
        return legacy_result

    # ステップ2: Phase 3で検索
    phase3_result = search_phase3_knowledge(query, user_id, top_k=5)

    if phase3_result and phase3_result["top_score"] >= PHASE3_KNOWLEDGE_CONFIG["similarity_threshold"]:
        formatted = format_phase3_results(phase3_result["results"])
        print(f"🚀 Phase 3結果を使用 (top_score: {phase3_result['top_score']:.3f})")
        return {
            "source": "phase3",
            "formatted_context": formatted,
            "confidence": phase3_result["top_score"],
            "results": phase3_result["results"],
            "search_log_id": phase3_result.get("search_log_id")
        }

    # ステップ3: 旧システムの低信頼度結果を使用
    if legacy_result:
        print(f"📖 旧システム低信頼度結果をフォールバック使用 (confidence: {legacy_result['confidence']:.2f})")
        return legacy_result

    # ステップ4: 結果なし
    print("❌ 統合ナレッジ検索: 関連情報なし")
    return {
        "source": "none",
        "formatted_context": "",
        "confidence": 0.0,
        "results": []
    }


def search_legacy_knowledge(query: str):
    """
    旧システム（soulkun_knowledge）でナレッジ検索

    Args:
        query: 検索クエリ

    Returns:
        {
            "source": "legacy",
            "formatted_context": "...",
            "confidence": 0.0 - 1.0,
            "results": [...]
        }
    """
    try:
        pool = get_pool()
        with pool.connect() as conn:
            # LIKE検索でキーまたは値にマッチするものを取得
            sql = """
                SELECT category, key, value
                FROM soulkun_knowledge
                WHERE key ILIKE :pattern OR value ILIKE :pattern
                ORDER BY
                    CASE
                        WHEN key ILIKE :exact THEN 1
                        WHEN key ILIKE :pattern THEN 2
                        ELSE 3
                    END
                LIMIT 5
            """

            pattern = f"%{query}%"
            exact = query

            result = conn.execute(
                sqlalchemy.text(sql),
                {"pattern": pattern, "exact": exact}
            )
            rows = result.fetchall()

            if not rows:
                return None

            # 信頼度の計算
            first_row = rows[0]
            key_lower = first_row[1].lower()
            query_lower = query.lower()

            if query_lower == key_lower:
                confidence = 1.0  # 完全一致
            elif query_lower in key_lower:
                confidence = 0.9  # 部分一致（キーに含まれる）
            elif key_lower in query_lower:
                confidence = 0.8  # 部分一致（クエリに含まれる）
            else:
                confidence = 0.6  # それ以外

            # 整形
            formatted_parts = []
            results = []

            for i, row in enumerate(rows, 1):
                category, key, value = row[0], row[1], row[2]
                formatted_parts.append(
                    f"【参考情報 {i}】\n"
                    f"項目: {key}\n"
                    f"内容: {value}\n"
                )
                results.append({
                    "category": category,
                    "key": key,
                    "value": value
                })

            return {
                "source": "legacy",
                "formatted_context": "\n".join(formatted_parts),
                "confidence": confidence,
                "results": results
            }

    except Exception as e:
        print(f"❌ 旧ナレッジ検索エラー: {e}")
        traceback.print_exc()
        return None


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


def create_proposal(proposed_by_account_id: str, proposed_by_name: str, 
                   proposed_in_room_id: str, category: str, key: str, 
                   value: str, message_id: str = None):
    """知識の提案を作成"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            result = conn.execute(sqlalchemy.text("""
                INSERT INTO knowledge_proposals 
                (proposed_by_account_id, proposed_by_name, proposed_in_room_id, 
                 category, key, value, message_id, status)
                VALUES (:account_id, :name, :room_id, :category, :key, :value, :message_id, 'pending')
                RETURNING id
            """), {
                "account_id": proposed_by_account_id,
                "name": proposed_by_name,
                "room_id": proposed_in_room_id,
                "category": category,
                "key": key,
                "value": value,
                "message_id": message_id
            })
            proposal_id = result.fetchone()[0]
        print(f"✅ 提案を作成: ID={proposal_id}, {key}={value}")
        return proposal_id
    except Exception as e:
        print(f"❌ 提案作成エラー: {e}")
        traceback.print_exc()
        return None


def get_pending_proposals():
    """
    承認待ちの提案を取得
    v6.9.1: 古い順（FIFO）に変更 - 待たせている人から処理
    """
    try:
        pool = get_pool()
        with pool.connect() as conn:
            # v6.9.1: ORDER BY created_at ASC（古い順）
            result = conn.execute(sqlalchemy.text("""
                SELECT id, proposed_by_account_id, proposed_by_name, proposed_in_room_id,
                       category, key, value, message_id, created_at
                FROM knowledge_proposals 
                WHERE status = 'pending'
                ORDER BY created_at ASC
            """))
            rows = result.fetchall()
            return [{
                "id": r[0], "proposed_by_account_id": r[1], "proposed_by_name": r[2],
                "proposed_in_room_id": r[3], "category": r[4], "key": r[5], 
                "value": r[6], "message_id": r[7], "created_at": r[8]
            } for r in rows]
    except Exception as e:
        print(f"❌ 提案取得エラー: {e}")
        traceback.print_exc()
        return []


def get_oldest_pending_proposal():
    """最も古い承認待ち提案を取得（v6.9.1: FIFO）"""
    proposals = get_pending_proposals()
    return proposals[0] if proposals else None


def get_proposal_by_id(proposal_id: int):
    """ID指定で提案を取得（v6.9.1追加）"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(sqlalchemy.text("""
                SELECT id, proposed_by_account_id, proposed_by_name, proposed_in_room_id,
                       category, key, value, message_id, created_at, status
                FROM knowledge_proposals 
                WHERE id = :id
            """), {"id": proposal_id})
            row = result.fetchone()
            if row:
                return {
                    "id": row[0], "proposed_by_account_id": row[1], "proposed_by_name": row[2],
                    "proposed_in_room_id": row[3], "category": row[4], "key": row[5], 
                    "value": row[6], "message_id": row[7], "created_at": row[8], "status": row[9]
                }
            return None
    except Exception as e:
        print(f"❌ 提案取得エラー: {e}")
        traceback.print_exc()
        return None


def get_latest_pending_proposal():
    """最新の承認待ち提案を取得（後方互換性のため残す）"""
    return get_oldest_pending_proposal()


# =====================================================
# v6.9.2: 未通知提案の取得・再通知機能
# =====================================================

def get_unnotified_proposals():
    """
    通知失敗した提案を取得（admin_notified=FALSE）
    v6.9.2追加
    """
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(sqlalchemy.text("""
                SELECT id, proposed_by_account_id, proposed_by_name, proposed_in_room_id,
                       category, key, value, message_id, created_at
                FROM knowledge_proposals 
                WHERE status = 'pending' AND admin_notified = FALSE
                ORDER BY created_at ASC
            """))
            rows = result.fetchall()
            return [{
                "id": r[0], "proposed_by_account_id": r[1], "proposed_by_name": r[2],
                "proposed_in_room_id": r[3], "category": r[4], "key": r[5], 
                "value": r[6], "message_id": r[7], "created_at": r[8]
            } for r in rows]
    except Exception as e:
        print(f"❌ 未通知提案取得エラー: {e}")
        traceback.print_exc()
        return []


def retry_proposal_notification(proposal_id: int):
    """
    提案の通知を再送（v6.9.2追加）
    """
    proposal = get_proposal_by_id(proposal_id)
    if not proposal:
        return False, f"提案ID={proposal_id}が見つからない"
    
    if proposal["status"] != "pending":
        return False, f"提案ID={proposal_id}は既に処理済み（{proposal['status']}）"
    
    # 再通知を実行
    success = report_proposal_to_admin(
        proposal_id,
        proposal["proposed_by_name"],
        proposal["key"],
        proposal["value"]
    )
    
    if success:
        return True, f"提案ID={proposal_id}を再通知した"
    else:
        return False, f"提案ID={proposal_id}の再通知に失敗"


def approve_proposal(proposal_id: int, reviewed_by: str):
    """提案を承認して知識に反映"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            # 提案を取得
            result = conn.execute(sqlalchemy.text("""
                SELECT category, key, value, proposed_by_account_id
                FROM knowledge_proposals WHERE id = :id AND status = 'pending'
            """), {"id": proposal_id})
            row = result.fetchone()
            
            if not row:
                print(f"⚠️ 提案ID={proposal_id}が見つからないか、既に処理済み")
                return False
            
            category, key, value, proposed_by = row
            
            # 知識に反映
            conn.execute(sqlalchemy.text("""
                INSERT INTO soulkun_knowledge (category, key, value, created_by, updated_at)
                VALUES (:category, :key, :value, :created_by, CURRENT_TIMESTAMP)
                ON CONFLICT (category, key) 
                DO UPDATE SET value = :value, updated_at = CURRENT_TIMESTAMP
            """), {
                "category": category,
                "key": key,
                "value": value,
                "created_by": proposed_by
            })
            
            # 提案を承認済みに更新
            conn.execute(sqlalchemy.text("""
                UPDATE knowledge_proposals 
                SET status = 'approved', reviewed_by = :reviewed_by, reviewed_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": proposal_id, "reviewed_by": reviewed_by})
        
        print(f"✅ 提案ID={proposal_id}を承認: {key}={value}")
        return True
    except Exception as e:
        print(f"❌ 提案承認エラー: {e}")
        traceback.print_exc()
        return False


def reject_proposal(proposal_id: int, reviewed_by: str):
    """提案を却下"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(sqlalchemy.text("""
                UPDATE knowledge_proposals 
                SET status = 'rejected', reviewed_by = :reviewed_by, reviewed_at = CURRENT_TIMESTAMP
                WHERE id = :id AND status = 'pending'
            """), {"id": proposal_id, "reviewed_by": reviewed_by})
        print(f"✅ 提案ID={proposal_id}を却下")
        return True
    except Exception as e:
        print(f"❌ 提案却下エラー: {e}")
        traceback.print_exc()
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


def cache_all_contacts_to_db():
    """
    ★★★ v6.8.3: /contacts APIで全コンタクトをDBにキャッシュ ★★★
    
    process_overdue_tasks()の開始時に呼び出すと、
    以降のget_direct_room()はDBキャッシュヒットで高速化される。
    """
    pool = get_pool()
    
    try:
        contacts_map, fetched_ok = get_all_contacts()  # ★★★ v6.8.4: タプルで受け取る ★★★
        
        if not fetched_ok:
            print("⚠️ コンタクト一覧取得失敗のため、DBキャッシュをスキップ")
            return
        
        if not contacts_map:
            print("⚠️ コンタクト一覧が空のため、DBキャッシュをスキップ（0件）")
            return
        
        cached_count = 0
        with pool.begin() as conn:
            for account_id, room_id in contacts_map.items():
                try:
                    conn.execute(
                        sqlalchemy.text("""
                            INSERT INTO dm_room_cache (account_id, dm_room_id)
                            VALUES (:account_id, :dm_room_id)
                            ON CONFLICT (account_id) DO UPDATE SET 
                                dm_room_id = :dm_room_id,
                                cached_at = CURRENT_TIMESTAMP
                        """),
                        {"account_id": account_id, "dm_room_id": room_id}
                    )
                    cached_count += 1
                except Exception as e:
                    print(f"⚠️ DMキャッシュ保存エラー: {e}")
        
        print(f"✅ 全コンタクトをDBキャッシュ完了: {cached_count}件")
        
    except Exception as e:
        print(f"❌ コンタクトDBキャッシュエラー: {e}")
        traceback.print_exc()


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


def report_unassigned_overdue_tasks(tasks):
    """
    担当者未設定の遅延タスクを管理部に報告
    """
    if not tasks:
        return
    
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    message_lines = ["[info][title]⚠️ 担当者未設定の遅延タスク[/title]", 
                     "以下のタスクは担当者が設定されておらず、督促できません：\n"]
    
    for i, task in enumerate(tasks[:10], 1):  # 最大10件まで
        body_short = (task["body"][:30] + "...") if len(task["body"]) > 30 else task["body"]
        requester = task.get("assigned_by_name") or "依頼者不明"
        overdue_days = get_overdue_days(task["limit_time"])
        limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"
        
        message_lines.append(f"{i}. 「{body_short}」")
        message_lines.append(f"   依頼者: {requester} / 期限: {limit_date} / {overdue_days}日超過")
    
    if len(tasks) > 10:
        message_lines.append(f"\n...他{len(tasks) - 10}件")
    
    message_lines.append("\n担当者を設定してくださいウル🐺[/info]")
    message = "\n".join(message_lines)
    
    try:
        response = httpx.post(
            f"https://api.chatwork.com/v2/rooms/{ADMIN_ROOM_ID}/messages",
            headers={"X-ChatWorkToken": api_token},
            data={"body": message},
            timeout=10.0
        )
        
        if response.status_code == 200:
            print(f"✅ 担当者未設定タスク報告送信成功（{len(tasks)}件）")
        else:
            print(f"❌ 担当者未設定タスク報告送信失敗: {response.status_code}")
    except Exception as e:
        print(f"❌ 担当者未設定タスク報告エラー: {e}")


def get_overdue_days(limit_time):
    """期限超過日数を計算"""
    if not limit_time:
        return 0
    
    now = datetime.now(JST)
    today = now.date()
    
    # ★★★ v6.8.6: int/float両対応 ★★★
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
    """
    global _runtime_dm_cache, _runtime_direct_rooms, _runtime_contacts_cache, _runtime_contacts_fetched_ok, _dm_unavailable_buffer
    
    print("=" * 50)
    print("🔔 遅延タスク処理開始")
    print("=" * 50)
    
    # ★★★ v6.8.4: 実行開始時にメモリキャッシュをリセット ★★★
    _runtime_dm_cache = {}
    _runtime_direct_rooms = None
    _runtime_contacts_cache = None
    _runtime_contacts_fetched_ok = None  # v6.8.4追加
    _dm_unavailable_buffer = []  # バッファもリセット
    print("✅ メモリキャッシュをリセット")
    
    try:
        # テーブル確認
        ensure_overdue_tables()
        
        pool = get_pool()
        now = datetime.now(JST)
        today = now.date()
        
        # 期限超過の未完了タスクを取得（担当者ごとにグループ化するため）
        with pool.connect() as conn:
            result = conn.execute(sqlalchemy.text("""
                SELECT 
                    task_id, room_id, assigned_to_account_id, assigned_by_account_id,
                    body, limit_time, assigned_to_name, assigned_by_name
                FROM chatwork_tasks
                WHERE status = 'open'
                  AND skip_tracking = FALSE
                  AND limit_time IS NOT NULL
                  AND limit_time < :today_timestamp
                ORDER BY assigned_to_account_id, limit_time
            """), {"today_timestamp": int(datetime.combine(today, datetime.min.time()).replace(tzinfo=JST).timestamp())})
            
            overdue_tasks = result.fetchall()
        
        if not overdue_tasks:
            print("✅ 期限超過タスクはありません")
            return
        
        print(f"📋 期限超過タスク数: {len(overdue_tasks)}")
        
        # 担当者ごとにグループ化
        tasks_by_assignee = {}
        unassigned_tasks = []  # ★ v6.8.1: 担当者未設定のタスク
        
        for task in overdue_tasks:
            account_id = task[2]  # assigned_to_account_id
            
            # ★ NULLチェック: 担当者未設定のタスクは別管理
            if account_id is None:
                unassigned_tasks.append({
                    "task_id": task[0],
                    "room_id": task[1],
                    "assigned_to_account_id": task[2],
                    "assigned_by_account_id": task[3],
                    "body": task[4],
                    "limit_time": task[5],
                    "assigned_to_name": task[6] or "（未設定）",
                    "assigned_by_name": task[7]
                })
                continue
            
            if account_id not in tasks_by_assignee:
                tasks_by_assignee[account_id] = []
            tasks_by_assignee[account_id].append({
                "task_id": task[0],
                "room_id": task[1],
                "assigned_to_account_id": task[2],
                "assigned_by_account_id": task[3],
                "body": task[4],
                "limit_time": task[5],
                "assigned_to_name": task[6],
                "assigned_by_name": task[7]
            })
        
        # ★ 担当者未設定タスクがあれば管理部に報告
        if unassigned_tasks:
            report_unassigned_overdue_tasks(unassigned_tasks)
        
        # 担当者ごとに個人チャットへ督促送信
        for account_id, tasks in tasks_by_assignee.items():
            send_overdue_reminder_to_dm(account_id, tasks, today)
        
        # エスカレーション処理（3日以上超過）
        process_escalations(overdue_tasks, today)
        
        # ★★★ v6.8.3: DM不可通知をまとめて送信 ★★★
        flush_dm_unavailable_notifications()
        
        print("=" * 50)
        print("🔔 遅延タスク処理完了")
        print("=" * 50)
        
    except Exception as e:
        print(f"❌ 遅延タスク処理エラー: {e}")
        traceback.print_exc()
        # エラー時もバッファをフラッシュ
        try:
            flush_dm_unavailable_notifications()
        except:
            pass


def send_overdue_reminder_to_dm(account_id, tasks, today):
    """
    担当者の個人チャットに遅延タスクをまとめて督促送信
    
    ★ v6.8.1変更点:
    - DMが見つからない場合は管理部に通知（フォールバック）
    """
    if not tasks:
        return
    
    assignee_name = tasks[0].get("assigned_to_name", "担当者")
    
    # 個人チャットを取得
    dm_room_id = get_direct_room(account_id)
    if not dm_room_id:
        # ★ フォールバック: 管理部に「DMできない」ことを通知
        print(f"⚠️ {assignee_name}さんの個人チャットが取得できませんでした → 管理部に通知")
        notify_dm_not_available(assignee_name, account_id, tasks, "督促")
        return
    
    # 今日既に督促済みか確認
    pool = get_pool()
    with pool.connect() as conn:
        # 全タスクについて今日の督促履歴をチェック
        task_ids = [t["task_id"] for t in tasks]
        # ★★★ v6.8.3: expanding INに変更（ANY(:task_ids)は環境依存で落ちる）★★★
        stmt = sqlalchemy.text("""
            SELECT task_id FROM task_overdue_reminders
            WHERE task_id IN :task_ids AND reminder_date = :today
        """).bindparams(bindparam("task_ids", expanding=True))
        result = conn.execute(stmt, {"task_ids": task_ids, "today": today})
        already_reminded = set(row[0] for row in result.fetchall())
    
    # 未督促のタスクだけ抽出
    tasks_to_remind = [t for t in tasks if t["task_id"] not in already_reminded]
    
    if not tasks_to_remind:
        print(f"✅ {assignee_name}さんへの督促は今日既に送信済み")
        return
    
    # メッセージ作成
    message_lines = [f"{assignee_name}さん\n", "📌 期限超過のタスクがありますウル！\n"]
    
    for i, task in enumerate(tasks_to_remind, 1):
        overdue_days = get_overdue_days(task["limit_time"])
        limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"
        requester = task.get("assigned_by_name") or "依頼者"
        body_short = (task["body"][:30] + "...") if len(task["body"]) > 30 else task["body"]
        
        message_lines.append(f"{i}. 「{body_short}」（依頼者: {requester} / 期限: {limit_date} / {overdue_days}日超過）")
    
    message_lines.append("\n遅れている理由と、いつ頃完了できそうか教えてほしいウル🐺")
    message = "\n".join(message_lines)
    
    # 送信
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    response = httpx.post(
        f"https://api.chatwork.com/v2/rooms/{dm_room_id}/messages",
        headers={"X-ChatWorkToken": api_token},
        data={"body": message},
        timeout=10.0
    )
    
    if response.status_code == 200:
        print(f"✅ {assignee_name}さんへの督促送信成功（{len(tasks_to_remind)}件）")
        
        # 督促履歴を記録
        with pool.begin() as conn:
            for task in tasks_to_remind:
                overdue_days = get_overdue_days(task["limit_time"])
                conn.execute(
                    sqlalchemy.text("""
                        INSERT INTO task_overdue_reminders (task_id, account_id, reminder_date, overdue_days)
                        VALUES (:task_id, :account_id, :reminder_date, :overdue_days)
                        ON CONFLICT (task_id, reminder_date) DO NOTHING
                    """),
                    {
                        "task_id": task["task_id"],
                        "account_id": account_id,
                        "reminder_date": today,
                        "overdue_days": overdue_days
                    }
                )
    else:
        print(f"❌ {assignee_name}さんへの督促送信失敗: {response.status_code}")


def process_escalations(overdue_tasks, today):
    """
    3日以上超過のタスクをエスカレーション（依頼者+管理部に報告）
    
    ★★★ v6.8.2変更点 ★★★
    - task_escalationsテーブルを使用（督促履歴と分離）
    - エスカレーション送信前に必ず記録を作成（スパム防止）
    """
    pool = get_pool()
    
    # 3日以上超過のタスクを抽出
    escalation_tasks = []
    for task in overdue_tasks:
        task_dict = {
            "task_id": task[0],
            "room_id": task[1],
            "assigned_to_account_id": task[2],
            "assigned_by_account_id": task[3],
            "body": task[4],
            "limit_time": task[5],
            "assigned_to_name": task[6],
            "assigned_by_name": task[7]
        }
        overdue_days = get_overdue_days(task_dict["limit_time"])
        if overdue_days >= ESCALATION_DAYS:
            task_dict["overdue_days"] = overdue_days
            escalation_tasks.append(task_dict)
    
    if not escalation_tasks:
        print("✅ エスカレーション対象タスクはありません")
        return
    
    # ★★★ v6.8.2: task_escalationsテーブルで今日のエスカレーション済みを確認 ★★★
    with pool.connect() as conn:
        task_ids = [t["task_id"] for t in escalation_tasks]
        # ★★★ v6.8.3: expanding INに変更（ANY(:task_ids)は環境依存で落ちる）★★★
        stmt = sqlalchemy.text("""
            SELECT task_id FROM task_escalations
            WHERE task_id IN :task_ids AND escalated_date = :today
        """).bindparams(bindparam("task_ids", expanding=True))
        result = conn.execute(stmt, {"task_ids": task_ids, "today": today})
        already_escalated = set(row[0] for row in result.fetchall())
    
    tasks_to_escalate = [t for t in escalation_tasks if t["task_id"] not in already_escalated]
    
    if not tasks_to_escalate:
        print("✅ エスカレーションは今日既に送信済み")
        return
    
    print(f"🚨 エスカレーション対象: {len(tasks_to_escalate)}件")
    
    # ★★★ v6.8.2: 送信前に必ずtask_escalationsに記録（スパム防止の要）★★★
    with pool.begin() as conn:
        for task in tasks_to_escalate:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO task_escalations (task_id, escalated_date)
                    VALUES (:task_id, :today)
                    ON CONFLICT (task_id, escalated_date) DO NOTHING
                """),
                {"task_id": task["task_id"], "today": today}
            )
    print(f"✅ エスカレーション記録を作成（{len(tasks_to_escalate)}件）")
    
    # 依頼者ごとにグループ化して報告
    tasks_by_requester = {}
    for task in tasks_to_escalate:
        requester_id = task["assigned_by_account_id"]
        if requester_id and requester_id not in tasks_by_requester:
            tasks_by_requester[requester_id] = []
        if requester_id:
            tasks_by_requester[requester_id].append(task)
    
    # ★★★ v6.8.3: 依頼者ごとの送信結果を記録（誤記録防止）★★★
    requester_success_map = {}  # {requester_id: bool}
    for requester_id, tasks in tasks_by_requester.items():
        requester_success_map[requester_id] = send_escalation_to_requester(requester_id, tasks)
    
    # 管理部への報告（まとめて1通）
    admin_success = send_escalation_to_admin(tasks_to_escalate)
    
    # ★★★ v6.8.3: 送信結果をtask_escalationsに更新（依頼者別に正しく記録）★★★
    with pool.begin() as conn:
        for task in tasks_to_escalate:
            # この タスクの依頼者への送信結果を取得
            task_requester_id = task["assigned_by_account_id"]
            task_requester_success = requester_success_map.get(task_requester_id, False)
            
            conn.execute(
                sqlalchemy.text("""
                    UPDATE task_escalations 
                    SET escalated_to_requester = :requester_success,
                        escalated_to_admin = :admin_success
                    WHERE task_id = :task_id AND escalated_date = :today
                """),
                {
                    "task_id": task["task_id"], 
                    "today": today,
                    "requester_success": task_requester_success,
                    "admin_success": admin_success
                }
            )


def send_escalation_to_requester(requester_id, tasks):
    """依頼者へのエスカレーション報告
    
    ★ v6.8.1変更点:
    - DMが見つからない場合は管理部に通知（フォールバック）
    
    ★ v6.8.2変更点:
    - 成功/失敗を戻り値で返す
    
    Returns:
        bool: 送信成功ならTrue
    """
    if not tasks:
        return False
    
    # 依頼者名を取得（tasksから推測）
    requester_name = f"依頼者(ID:{requester_id})"
    
    dm_room_id = get_direct_room(requester_id)
    if not dm_room_id:
        # ★ フォールバック: 管理部に「DMできない」ことを通知
        print(f"⚠️ {requester_name}の個人チャットが取得できませんでした → 管理部に通知")
        notify_dm_not_available(requester_name, requester_id, tasks, "エスカレーション")
        return False
    
    message_lines = ["📋 タスク遅延のお知らせウル\n", "あなたが依頼したタスクが3日以上遅延しています：\n"]
    
    for task in tasks:
        assignee = task.get("assigned_to_name", "担当者")
        body_short = (task["body"][:30] + "...") if len(task["body"]) > 30 else task["body"]
        limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"
        
        message_lines.append(f"・「{body_short}」")
        message_lines.append(f"  担当者: {assignee} / 期限: {limit_date} / {task['overdue_days']}日超過")
    
    message_lines.append("\nソウルくんから毎日督促していますが、対応が必要かもしれませんウル🐺")
    message = "\n".join(message_lines)
    
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    response = httpx.post(
        f"https://api.chatwork.com/v2/rooms/{dm_room_id}/messages",
        headers={"X-ChatWorkToken": api_token},
        data={"body": message},
        timeout=10.0
    )
    
    if response.status_code == 200:
        print(f"✅ 依頼者(ID:{requester_id})へのエスカレーション送信成功")
        return True
    else:
        print(f"❌ 依頼者(ID:{requester_id})へのエスカレーション送信失敗: {response.status_code}")
        return False


def send_escalation_to_admin(tasks):
    """管理部へのエスカレーション報告
    
    ★ v6.8.2変更点:
    - 成功/失敗を戻り値で返す
    
    Returns:
        bool: 送信成功ならTrue
    """
    if not tasks:
        return False
    
    message_lines = ["[info][title]📊 長期遅延タスク報告[/title]", "以下のタスクが3日以上遅延しています：\n"]
    
    for i, task in enumerate(tasks, 1):
        assignee = task.get("assigned_to_name", "担当者")
        requester = task.get("assigned_by_name", "依頼者")
        body_short = (task["body"][:30] + "...") if len(task["body"]) > 30 else task["body"]
        limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"
        
        message_lines.append(f"{i}. {assignee}さん「{body_short}」")
        message_lines.append(f"   依頼者: {requester} / 期限: {limit_date} / {task['overdue_days']}日超過")
    
    message_lines.append("\n引き続き督促を継続しますウル🐺[/info]")
    message = "\n".join(message_lines)
    
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    response = httpx.post(
        f"https://api.chatwork.com/v2/rooms/{ADMIN_ROOM_ID}/messages",
        headers={"X-ChatWorkToken": api_token},
        data={"body": message},
        timeout=10.0
    )
    
    if response.status_code == 200:
        print(f"✅ 管理部へのエスカレーション送信成功（{len(tasks)}件）")
        return True
    else:
        print(f"❌ 管理部へのエスカレーション送信失敗: {response.status_code}")
        return False


# =====================================================
# ===== タスク期限変更検知（P1-030） =====
# =====================================================

def detect_and_report_limit_changes(cursor, task_id, old_limit, new_limit, task_info):
    """
    タスクの期限変更を検知して報告
    sync_chatwork_tasks内から呼び出される
    
    ★ v6.8.1変更点:
    - UPDATE文をPostgreSQL対応（サブクエリ方式）
    - DM見つからない時のフォールバック追加
    """
    if old_limit == new_limit:
        return
    
    if old_limit is None or new_limit is None:
        return
    
    print(f"🔍 期限変更検知: task_id={task_id}, {old_limit} → {new_limit}")
    
    pool = get_pool()
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    # 変更履歴を記録
    try:
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO task_limit_changes (task_id, old_limit_time, new_limit_time)
                    VALUES (:task_id, :old_limit, :new_limit)
                """),
                {"task_id": task_id, "old_limit": old_limit, "new_limit": new_limit}
            )
    except Exception as e:
        print(f"⚠️ 期限変更履歴記録エラー: {e}")
    
    # 日付フォーマット
    old_date_str = datetime.fromtimestamp(old_limit, tz=JST).strftime("%m/%d") if old_limit else "不明"
    new_date_str = datetime.fromtimestamp(new_limit, tz=JST).strftime("%m/%d") if new_limit else "不明"
    
    # 延長日数計算
    if old_limit and new_limit:
        days_diff = (new_limit - old_limit) // 86400  # 秒→日
        diff_str = f"{abs(days_diff)}日{'延長' if days_diff > 0 else '短縮'}"
    else:
        diff_str = "変更"
    
    assignee_name = task_info.get("assigned_to_name", "担当者")
    assignee_id = task_info.get("assigned_to_account_id")
    requester_name = task_info.get("assigned_by_name", "依頼者")
    body_short = (task_info["body"][:30] + "...") if len(task_info["body"]) > 30 else task_info["body"]
    
    # ① 管理部への即時報告
    admin_message = f"""[info][title]📝 タスク期限変更の検知[/title]
以下のタスクの期限が変更されました：

タスク: {body_short}
担当者: {assignee_name}
依頼者: {requester_name}
変更前: {old_date_str}
変更後: {new_date_str}（{diff_str}）

理由を確認中ですウル🐺[/info]"""
    
    response = httpx.post(
        f"https://api.chatwork.com/v2/rooms/{ADMIN_ROOM_ID}/messages",
        headers={"X-ChatWorkToken": api_token},
        data={"body": admin_message},
        timeout=10.0
    )
    
    if response.status_code == 200:
        print(f"✅ 管理部への期限変更報告送信成功")
    else:
        print(f"❌ 管理部への期限変更報告送信失敗: {response.status_code}")
    
    # ② 担当者への理由質問（個人チャット）
    if assignee_id:
        dm_room_id = get_direct_room(assignee_id)
        if dm_room_id:
            dm_message = f"""{assignee_name}さん

📝 タスクの期限変更を検知しましたウル！

タスク: {body_short}
変更前: {old_date_str} → 変更後: {new_date_str}（{diff_str}）

期限を変更した理由を教えてほしいウル🐺"""
            
            response = httpx.post(
                f"https://api.chatwork.com/v2/rooms/{dm_room_id}/messages",
                headers={"X-ChatWorkToken": api_token},
                data={"body": dm_message},
                timeout=10.0
            )
            
            if response.status_code == 200:
                print(f"✅ {assignee_name}さんへの期限変更理由質問送信成功")
                
                # ★ 理由質問済みフラグを更新（PostgreSQL対応: サブクエリ方式）
                try:
                    with pool.begin() as conn:
                        conn.execute(
                            sqlalchemy.text("""
                                UPDATE task_limit_changes 
                                SET reason_asked = TRUE 
                                WHERE id = (
                                    SELECT id FROM task_limit_changes
                                    WHERE task_id = :task_id
                                    ORDER BY detected_at DESC
                                    LIMIT 1
                                )
                            """),
                            {"task_id": task_id}
                        )
                except Exception as e:
                    print(f"⚠️ 理由質問フラグ更新エラー: {e}")
            else:
                print(f"❌ {assignee_name}さんへの期限変更理由質問送信失敗: {response.status_code}")
        else:
            # ★ フォールバック: DMが見つからない場合は管理部に追加報告
            print(f"⚠️ {assignee_name}さんの個人チャットが取得できませんでした → 管理部に通知")
            task_for_notify = [{"body": task_info["body"]}]
            notify_dm_not_available(assignee_name, assignee_id, task_for_notify, "期限変更理由質問")


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

                        # v10.16.0: オールメンション（toall）を無視
                        if is_toall_mention(body):
                            print(f"   ⏭️ オールメンション（toall）のため無視")
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
    """全ルームのメンバーをchatwork_usersテーブルに同期"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
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
                        conn.execute(
                            sqlalchemy.text("""
                                INSERT INTO chatwork_users (account_id, name, room_id, updated_at)
                                VALUES (:account_id, :name, :room_id, CURRENT_TIMESTAMP)
                                ON CONFLICT (account_id) 
                                DO UPDATE SET name = :name, updated_at = CURRENT_TIMESTAMP
                            """),
                            {
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
                    print(f"🔍 DEBUG: limit_time = {limit_time}, type = {type(limit_time)}")
                    
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
                    cursor.execute("""
                        INSERT INTO chatwork_tasks 
                        (task_id, room_id, assigned_to_account_id, assigned_by_account_id, body, limit_time, status, 
                         skip_tracking, last_synced_at, room_name, assigned_to_name, assigned_by_name)
                        VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, CURRENT_TIMESTAMP, %s, %s, %s)
                    """, (task_id, room_id, assigned_to_id, assigned_by_id, body, 
                          limit_datetime, skip_tracking, room_name, assigned_to_name, assigned_by_name))
            
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
