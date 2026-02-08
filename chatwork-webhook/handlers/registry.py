# handlers/registry.py
"""
ハンドラーレジストリ（Handlers Registry）

このファイルは、ソウルくんの全機能（Capability）とハンドラー関数のマッピングを
一元管理する「機能カタログ」です。

【設計目標】
「新機能追加 = handlers/xxx_handler.py作成 + このファイルに1エントリ追加」

【7つの鉄則との整合性】
4. 機能拡張しても脳の構造は変わらない → このカタログに追加するだけでAIが認識

【このファイルの役割】
1. SYSTEM_CAPABILITIES: AIが認識する機能カタログ（意図理解用）
2. HANDLERS: ハンドラー関数のマッピング（実行用）
3. 両者の整合性を保証

【新機能追加手順】
1. handlers/xxx_handler.py を作成
2. このファイルの該当セクションに CAPABILITY_DEF を追加
3. このファイルの HANDLERS に関数を登録
4. main.py は変更不要

Author: Claude Opus 4.5
Created: 2026-01-29
"""

from typing import Dict, Callable, Any

# =============================================================================
# SYSTEM_CAPABILITIES: AIが認識する機能カタログ
# =============================================================================
#
# 【構造】
# - name: 機能名（日本語）
# - description: 機能の説明（AIがこれを読んで判断）
# - category: カテゴリ（task/memory/goal/generation/etc）
# - enabled: 有効/無効
# - trigger_examples: トリガー例（AIの学習用）
# - params_schema: パラメータスキーマ
# - handler: ハンドラー関数名（HANDLERSのキー）
# - requires_confirmation: 確認が必要か
# - required_data: 必要なデータ
# - brain_metadata: 脳アーキテクチャ用メタデータ（intent_keywords等）
#
# =============================================================================

SYSTEM_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    # =========================================================================
    # タスク管理
    # =========================================================================
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
        "handler": "chatwork_task_create",
        "requires_confirmation": False,
        "required_data": ["chatwork_users", "sender_name"],
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
        "handler": "chatwork_task_complete",
        "requires_confirmation": False,
        "required_data": ["recent_tasks_context"],
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
        "handler": "chatwork_task_search",
        "requires_confirmation": False,
        "required_data": ["chatwork_users", "sender_name"],
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

    "chatwork_task_edit": {
        "name": "タスク編集（API制約により不可）",
        "description": "タスクの期限変更や内容変更を行う。「期限を変更して」「タスクを編集して」などの要望に対応。※ChatWork APIにタスク編集機能がないため、ソウルくんでは対応不可。",
        "category": "task",
        "enabled": True,
        "api_limitation": True,
        "trigger_examples": [
            "タスクの期限を変更して",
            "〇〇のタスクを編集して",
            "期限を明日に変えて",
            "タスクの内容を修正して",
        ],
        "params_schema": {},
        "handler": "api_limitation",
        "requires_confirmation": False,
        "required_data": [],
        "limitation_message": "タスクの編集（期限変更・内容変更）",
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["タスク編集", "期限変更", "タスク変更"],
                "secondary": ["編集", "変更", "修正"],
                "negative": ["作成", "追加", "完了", "削除"],
            },
            "intent_keywords": {
                "primary": ["タスク編集", "期限変更"],
                "secondary": ["タスク", "期限"],
                "modifiers": ["編集", "変更", "修正", "変えて"],
                "negative": [],
                "confidence_boost": 0.7,
            },
            "risk_level": "low",
            "priority": 3,
        },
    },

    "chatwork_task_delete": {
        "name": "タスク削除（API制約により不可）",
        "description": "タスクを削除する。「タスクを削除して」「タスクを消して」などの要望に対応。※ChatWork APIにタスク削除機能がないため、ソウルくんでは対応不可。",
        "category": "task",
        "enabled": True,
        "api_limitation": True,
        "trigger_examples": [
            "タスクを削除して",
            "このタスクを消して",
            "〇〇のタスクを取り消して",
            "間違えて作ったタスクを消して",
        ],
        "params_schema": {},
        "handler": "api_limitation",
        "requires_confirmation": False,
        "required_data": [],
        "limitation_message": "タスクの削除",
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["タスク削除", "タスク消去"],
                "secondary": ["削除", "消して", "取り消し"],
                "negative": ["作成", "追加", "完了", "編集"],
            },
            "intent_keywords": {
                "primary": ["タスク削除"],
                "secondary": ["タスク", "削除"],
                "modifiers": ["消して", "削除", "取り消し"],
                "negative": [],
                "confidence_boost": 0.7,
            },
            "risk_level": "medium",
            "priority": 3,
        },
    },

    # =========================================================================
    # 振り返り
    # =========================================================================
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
        "handler": "daily_reflection",
        "requires_confirmation": False,
        "required_data": [],
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

    # =========================================================================
    # 接続情報（v10.44.2）
    # =========================================================================
    "connection_query": {
        "name": "DM可能な相手一覧",
        "description": "ソウルくんがChatWorkで1on1（DM）できる相手の一覧を返す。代表のみ閲覧可能。",
        "category": "connection",
        "enabled": True,
        "trigger_examples": [
            "DMできる相手は誰？",
            "DMできる人教えて",
            "1on1で繋がってる人一覧教えて",
            "直接チャットできる相手は？",
            "個別で繋がってる人は？",
        ],
        "params_schema": {},
        "handler": "connection_query",  # CapabilityBridge経由
        "requires_confirmation": False,
        "required_data": [],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["DM", "1on1", "繋がってる", "直接チャット", "個別"],
                "secondary": ["話せる", "チャットできる", "コネクション"],
                "negative": ["タスク", "目標", "記憶"],
            },
            "intent_keywords": {
                "primary": ["DMできる相手", "DMできる人", "1on1で繋がってる", "直接チャットできる相手", "個別で繋がってる人"],
                "secondary": ["DM", "1on1", "個別", "繋がってる", "直接", "話せる", "チャットできる"],
                "modifiers": ["教えて", "一覧", "誰", "全員", "名前", "どんな人"],
                "negative": ["タスク", "目標", "記憶", "覚えて"],
                "confidence_boost": 1.5,
            },
            "risk_level": "low",
            "priority": 1,
        },
    },

    # =========================================================================
    # 記憶機能
    # =========================================================================
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
        "handler": "save_memory",
        "requires_confirmation": False,
        "required_data": [],
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
        "handler": "query_memory",
        "requires_confirmation": False,
        "required_data": ["all_persons"],
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
        "handler": "delete_memory",
        "requires_confirmation": False,
        "required_data": [],
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

    # =========================================================================
    # 学習機能（管理者）
    # =========================================================================
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
        "handler": "learn_knowledge",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "sender_name", "room_id"],
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
        "handler": "forget_knowledge",
        "requires_confirmation": False,
        "required_data": ["sender_account_id"],
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
        "handler": "list_knowledge",
        "requires_confirmation": False,
        "required_data": [],
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
        "handler": "proposal_decision",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "room_id"],
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

    # =========================================================================
    # 組織図クエリ（Phase 3.5）
    # =========================================================================
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
        "handler": "query_org_chart",
        "requires_confirmation": False,
        "required_data": [],
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

    # =========================================================================
    # ナレッジ検索（Phase 3）
    # =========================================================================
    "query_knowledge": {
        "name": "会社知識の参照",
        "description": "就業規則、マニュアル、社内ルールなど会社の知識ベースを参照して回答する。有給休暇、経費精算、各種手続きなどの質問に対応。",
        "category": "knowledge",
        "enabled": True,
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
        "handler": "query_knowledge",
        "requires_confirmation": False,
        "required_data": [],
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

    # =========================================================================
    # 目標達成支援（Phase 2.5）
    # =========================================================================
    "goal_registration": {
        "name": "目標登録",
        "description": "【新規】目標を新しく登録する。「新しく目標を作りたい」「目標を登録したい」「目標設定したい」などの【新規作成】意図が明確な場合のみ。既存目標の確認・整理は goal_review、相談は goal_consult へ。",
        "category": "goal",
        "enabled": True,
        "trigger_examples": [
            "新しく目標を作りたい",
            "目標を登録したい",
            "目標設定したい",
            "粗利300万円を目標に登録して",
            "新しい目標を設定して",
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
        "handler": "goal_registration",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "sender_name"],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["目標登録", "目標を登録", "新しく目標", "目標を新規", "目標作成", "目標設定したい", "目標を立てたい"],
                "secondary": ["登録したい", "作りたい", "新規", "設定したい"],
                "negative": ["一覧", "表示", "確認", "整理", "削除", "修正", "どっち", "優先", "相談", "迷う"],
            },
            "intent_keywords": {
                "primary": ["目標登録", "目標を登録", "新しく目標", "目標を新規", "目標作成", "目標設定したい", "目標を立てたい", "ゴールを決めたい"],
                "secondary": ["登録したい", "作りたい", "新規作成", "設定したい", "立てたい", "決めたい"],
                "modifiers": ["登録", "新規", "新しく", "作成", "設定", "立て"],
                "negative": ["一覧", "表示", "出して", "確認", "整理", "削除", "修正", "過去", "登録済み", "もともと", "多すぎ", "ぐちゃぐちゃ", "どっち優先", "理由", "数字で", "どう決める", "迷う", "方針", "進捗", "報告", "状況", "どうなった"],
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
        "handler": "goal_progress_report",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "sender_name"],
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
        "name": "目標進捗確認",
        "description": "現在の目標の【進捗状況・達成率】を確認する。「達成率は？」「今の進捗は？」など。一覧表示・整理は goal_review へ。",
        "category": "goal",
        "enabled": True,
        "trigger_examples": [
            "達成率は？",
            "今の進捗を教えて",
            "どれくらい達成した？",
        ],
        "params_schema": {},
        "handler": "goal_status_check",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "sender_name"],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["達成率", "進捗確認", "どれくらい達成"],
                "secondary": ["進捗", "状況"],
                "negative": ["一覧", "表示", "整理", "削除", "修正", "設定", "登録"],
            },
            "intent_keywords": {
                "primary": ["達成率", "進捗確認", "どれくらい達成", "目標の進捗"],
                "secondary": ["進捗", "状況"],
                "modifiers": ["確認", "教えて"],
                "negative": ["一覧", "表示", "整理", "削除", "修正", "設定", "登録", "新規"],
                "confidence_boost": 0.8,
            },
            "risk_level": "low",
            "priority": 4,
        },
    },

    "goal_review": {
        "name": "目標一覧・整理",
        "description": "既存の目標一覧を表示する、または整理・削除・修正する。「目標を見せて」「一覧」「整理したい」「多すぎ」「削除」「修正」などに対応。新規作成は goal_registration へ。",
        "category": "goal",
        "enabled": True,
        "trigger_examples": [
            "目標一覧を出して",
            "登録済みの目標を表示して",
            "過去に登録した目標を見せて",
            "目標を整理したい",
            "目標が多すぎる",
        ],
        "params_schema": {
            "action": {
                "type": "string",
                "description": "アクション: list（一覧表示）、organize（整理）、delete（削除）、edit（修正）",
                "required": False,
                "default": "list",
            }
        },
        "handler": "goal_review",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "sender_name"],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["目標一覧", "目標を見", "目標を表示", "目標を出", "目標整理", "登録済み"],
                "secondary": ["一覧", "表示", "整理", "削除", "修正", "過去", "もともと"],
                "negative": ["登録したい", "新規", "新しく", "作りたい"],
            },
            "intent_keywords": {
                "primary": ["目標一覧", "目標を見せて", "目標を表示", "目標を出して", "登録済みの目標", "過去の目標", "目標整理", "目標多すぎ"],
                "secondary": ["目標", "ゴール"],
                "modifiers": ["一覧", "表示", "整理", "削除", "修正", "過去", "登録済み", "最新", "多すぎ", "ぐちゃぐちゃ"],
                "negative": ["登録したい", "新規", "新しく", "作りたい", "設定したい", "立てたい", "決めたい", "タスク", "組織"],
                "confidence_boost": 0.90,
            },
            "risk_level": "low",
            "priority": 5,
        },
    },

    "goal_consult": {
        "name": "目標相談",
        "description": "目標の決め方や優先順位について相談する。「売上と利益どっち優先？」「目標をどう決めたらいい？」「迷っている」などに対応。",
        "category": "goal",
        "enabled": True,
        "trigger_examples": [
            "今月の目標、売上と利益どっち優先？",
            "目標をどう決めたらいい？",
            "目標設定で迷ってる",
            "目標の優先順位を相談したい",
        ],
        "params_schema": {
            "consultation_topic": {
                "type": "string",
                "description": "相談内容",
                "required": False,
            }
        },
        "handler": "goal_consult",
        "requires_confirmation": False,
        "required_data": ["sender_account_id", "sender_name"],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["どっち優先", "どう決め", "目標相談", "目標について相談", "目標の決め方"],
                "secondary": ["迷う", "迷って", "優先順位", "方針", "アドバイス"],
                "negative": ["登録したい", "一覧", "表示"],
            },
            "intent_keywords": {
                "primary": ["どっち優先", "どう決めたらいい", "目標相談", "目標の決め方", "優先順位"],
                "secondary": ["迷う", "迷って", "方針", "アドバイス", "理由", "数字で", "どっちがいい"],
                "modifiers": ["相談", "教えて", "アドバイス"],
                "negative": ["登録したい", "一覧", "表示", "整理"],
                "confidence_boost": 0.90,
            },
            "risk_level": "low",
            "priority": 5,
        },
    },

    # =========================================================================
    # 目標削除・整理（v10.56.0）
    # =========================================================================
    "goal_delete": {
        "name": "目標削除",
        "description": "登録済みの目標を削除する。「目標を消したい」「目標#3を削除して」「いらない目標を消して」などに対応。確認必須の危険操作。",
        "category": "goal",
        "enabled": True,
        "trigger_examples": [
            "目標を消したい",
            "目標#3を削除して",
            "いらない目標を消して",
            "この目標やめたい",
        ],
        "params_schema": {
            "target_numbers": {
                "type": "string",
                "description": "削除対象の目標番号（例: '2,3,6-15'）",
                "required": False,
                "note": "省略時は目標一覧を表示して選択を促す"
            }
        },
        "handler": "goal_delete",
        "requires_confirmation": True,
        "required_data": ["sender_account_id", "sender_name"],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["目標を消", "目標を削除", "目標やめ", "目標キャンセル"],
                "secondary": ["消したい", "削除", "やめたい", "キャンセル"],
                "negative": ["登録したい", "一覧", "整理"],
            },
            "intent_keywords": {
                "primary": ["目標を消したい", "目標を削除して", "目標やめたい", "目標をキャンセル"],
                "secondary": ["消す", "削除", "やめる"],
                "modifiers": ["目標"],
                "negative": ["登録", "新規", "整理", "レビュー"],
                "confidence_boost": 0.85,
            },
            "risk_level": "high",
            "priority": 5,
        },
    },

    "goal_cleanup": {
        "name": "目標整理",
        "description": "重複・期限切れ・放置中の目標をまとめて整理する。「目標が多すぎる」「重複を統合したい」「古い目標を消したい」などに対応。メニュー形式で選択。",
        "category": "goal",
        "enabled": True,
        "trigger_examples": [
            "目標を整理したい",
            "重複した目標をまとめて",
            "古い目標を消したい",
            "目標が多すぎる",
        ],
        "params_schema": {
            "cleanup_type": {
                "type": "string",
                "description": "整理タイプ: duplicates（重複統合）, expired（期限切れ整理）, pending（放置中整理）",
                "required": False,
                "note": "省略時はメニューを表示"
            }
        },
        "handler": "goal_cleanup",
        "requires_confirmation": True,
        "required_data": ["sender_account_id", "sender_name"],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["目標整理", "重複統合", "目標が多すぎ", "古い目標"],
                "secondary": ["整理", "統合", "まとめ", "クリーンアップ"],
                "negative": ["登録", "新規", "削除して"],
            },
            "intent_keywords": {
                "primary": ["目標整理", "目標をまとめ", "重複した目標", "古い目標を消"],
                "secondary": ["整理", "統合", "まとめ", "クリーンアップ"],
                "modifiers": ["目標"],
                "negative": ["登録", "新規", "削除して"],
                "confidence_boost": 0.85,
            },
            "risk_level": "medium",
            "priority": 5,
        },
    },

    # =========================================================================
    # アナウンス機能（v10.26.0）
    # =========================================================================
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
        "handler": "announcement_create",
        "requires_confirmation": True,
        "required_data": ["sender_account_id", "sender_name", "room_id"],
        "authorization": {
            "rooms": [405315911],
            "account_ids": ["1728974"]
        },
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

    # =========================================================================
    # 生成機能（v10.38.0 Brain-Capability統合）
    # =========================================================================
    "generate_document": {
        "name": "文書生成",
        "description": "Google Docsで文書（レポート、議事録、提案書、マニュアル等）を生成する。資料作成、ドキュメント作成、レポート作成などの要望に対応。",
        "category": "generation",
        "enabled": True,
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
            "output_format": {
                "type": "string",
                "description": "出力形式: google_docs（Googleドキュメント）, markdown（マークダウン）",
                "required": False,
                "default": "google_docs",
                "note": "省略時はgoogle_docs"
            },
        },
        "handler": "generate_document",  # CapabilityBridge経由
        "requires_confirmation": True,
        "required_data": [],
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
            "risk_level": "medium",
            "priority": 4,
        },
    },

    "generate_image": {
        "name": "画像生成",
        "description": "DALL-Eで画像を生成する。イラスト作成、図の作成、画像作成などの要望に対応。",
        "category": "generation",
        "enabled": True,
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
                "description": "スタイル: vivid（鮮やか）, natural（自然）, anime（アニメ風）, realistic（写実的）, illustration（イラスト）, minimalist（ミニマル）, corporate（ビジネス）",
                "required": False,
                "note": "省略時はvivid"
            },
            "size": {
                "type": "string",
                "description": "サイズ: 1024x1024（正方形）, 1792x1024（横長）, 1024x1792（縦長）",
                "required": False,
                "default": "1024x1024",
            },
        },
        "handler": "generate_image",  # CapabilityBridge経由
        "requires_confirmation": True,
        "required_data": [],
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
            "risk_level": "medium",
            "priority": 4,
        },
    },

    "generate_video": {
        "name": "動画生成",
        "description": "Runway Gen-3で動画を生成する。動画作成、ムービー作成などの要望に対応。コストが高いため慎重に使用。",
        "category": "generation",
        "enabled": False,  # コストが高いためデフォルト無効
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
        "handler": "generate_video",  # CapabilityBridge経由
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
            "risk_level": "high",
            "priority": 3,
        },
    },

    # =========================================================================
    # 一般会話（フォールバック）
    # =========================================================================
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
        "handler": "general_conversation",
        "requires_confirmation": False,
        "required_data": [],
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
            "priority": 10,  # 最低優先度（フォールバック）
        },
    },

    # =========================================================================
    # スケジュール管理（将来実装）
    # =========================================================================
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
        "handler": "schedule_management",
        "requires_confirmation": True,
        "required_data": ["google_calendar_api"],
        "brain_metadata": {
            "decision_keywords": {
                "primary": ["スケジュール管理", "予定管理", "カレンダー"],
                "secondary": ["予定", "会議", "ミーティング"],
                "negative": ["タスク", "メモ", "ナレッジ"],
            },
            "intent_keywords": {
                "primary": ["スケジュール", "予定", "カレンダー"],
                "secondary": ["会議", "ミーティング", "打ち合わせ"],
                "modifiers": ["入れて", "追加", "確認", "教えて"],
                "negative": [],
                "confidence_boost": 0.8,
            },
            "risk_level": "medium",
            "priority": 4,
        },
    },
}


# =============================================================================
# HANDLER_ALIASES: 旧ハンドラー名 → 新ハンドラー名のマッピング
# =============================================================================
#
# 移行期間中の互換性を保つためのエイリアス定義。
# main.pyの既存コードが旧名を使っている場合に対応。
#
# =============================================================================

HANDLER_ALIASES: Dict[str, str] = {
    # 旧名 → 新名
    "handle_chatwork_task_create": "chatwork_task_create",
    "handle_chatwork_task_complete": "chatwork_task_complete",
    "handle_chatwork_task_search": "chatwork_task_search",
    "handle_daily_reflection": "daily_reflection",
    "handle_connection_query": "connection_query",
    "handle_save_memory": "save_memory",
    "handle_query_memory": "query_memory",
    "handle_delete_memory": "delete_memory",
    "handle_learn_knowledge": "learn_knowledge",
    "handle_forget_knowledge": "forget_knowledge",
    "handle_list_knowledge": "list_knowledge",
    "handle_proposal_decision": "proposal_decision",
    "handle_query_org_chart": "query_org_chart",
    "handle_query_company_knowledge": "query_knowledge",
    "handle_goal_registration": "goal_registration",
    "handle_goal_progress_report": "goal_progress_report",
    "handle_goal_status_check": "goal_status_check",
    "handle_goal_review": "goal_review",
    "handle_goal_consult": "goal_consult",
    "handle_announcement_request": "announcement_create",
    "handle_general_chat": "general_conversation",
    "handle_api_limitation": "api_limitation",
}


# =============================================================================
# ユーティリティ関数
# =============================================================================

def get_enabled_capabilities() -> Dict[str, Dict[str, Any]]:
    """有効な機能の一覧を取得"""
    return {
        cap_id: cap for cap_id, cap in SYSTEM_CAPABILITIES.items()
        if cap.get("enabled", True)
    }


def get_capability_info(action_name: str) -> Dict[str, Any]:
    """
    指定されたアクションの機能情報を取得

    Args:
        action_name: アクション名（エイリアスも可）

    Returns:
        機能情報の辞書、見つからない場合はNone
    """
    # エイリアスを解決
    resolved_name = HANDLER_ALIASES.get(action_name, action_name)
    return SYSTEM_CAPABILITIES.get(resolved_name)


def get_handler_name(capability_id: str) -> str:
    """
    Capability IDからハンドラー名を取得

    Args:
        capability_id: Capability ID

    Returns:
        ハンドラー名
    """
    cap = SYSTEM_CAPABILITIES.get(capability_id)
    if cap:
        return cap.get("handler", capability_id)
    return capability_id


def resolve_handler_alias(handler_name: str) -> str:
    """
    旧ハンドラー名を新ハンドラー名に解決

    Args:
        handler_name: ハンドラー名（旧名または新名）

    Returns:
        解決されたハンドラー名
    """
    return HANDLER_ALIASES.get(handler_name, handler_name)


def generate_capabilities_prompt(
    capabilities: Dict[str, Dict[str, Any]] = None,
    chatwork_users: list = None,
    sender_name: str = None
) -> str:
    """
    機能カタログからAI司令塔用のプロンプトを自動生成する

    【設計思想】
    - カタログを追加するだけでAIが新機能を認識
    - enabled=Trueの機能のみプロンプトに含める
    - 各機能の使い方をAIに理解させる

    Args:
        capabilities: 機能カタログ（省略時はSYSTEM_CAPABILITIES）
        chatwork_users: ChatWorkユーザー一覧
        sender_name: 送信者名

    Returns:
        プロンプト文字列
    """
    if capabilities is None:
        capabilities = SYSTEM_CAPABILITIES

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


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    "SYSTEM_CAPABILITIES",
    "HANDLER_ALIASES",
    "get_enabled_capabilities",
    "get_capability_info",
    "get_handler_name",
    "resolve_handler_alias",
    "generate_capabilities_prompt",
]
