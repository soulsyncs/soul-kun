# lib/brain/constants.py
"""
ソウルくんの脳 - 定数定義

このファイルには、脳アーキテクチャで使用する全ての定数を定義します。
定数の変更は慎重に行い、影響範囲を確認してください。

設計書: docs/13_brain_architecture.md
"""

from datetime import timezone, timedelta
from typing import List, Dict, Set

# =============================================================================
# タイムゾーン
# =============================================================================

# 日本標準時 (JST = UTC+9)
JST = timezone(timedelta(hours=9))

# =============================================================================
# 確信度と確認モード
# =============================================================================

# 確認モードの発動閾値
# この値未満の確信度の場合、ユーザーに確認を求める
CONFIRMATION_THRESHOLD: float = 0.7

# 自動実行の閾値
# この値以上の確信度の場合、確認なしで実行する
AUTO_EXECUTE_THRESHOLD: float = 0.9

# 危険な操作では常に確認する
DANGEROUS_ACTIONS: Set[str] = {
    "delete",
    "remove",
    "send_all",  # 全員への送信
    "cancel",
    "complete_all",
}

# =============================================================================
# v10.40.0: 対話フロー必須アクション
# =============================================================================

# 対話フロー（WHY→WHAT→HOW）を経由しないと実行できないアクション
# LLMの直接判定では実行不可、必ず対話完了後のみ実行可能
DIALOGUE_REQUIRED_ACTIONS: Set[str] = {
    "goal_registration",      # 目標登録は対話フロー必須
    "goal_setting",           # 目標設定も同様
    "handle_goal_registration",  # ハンドラー名でも制御
}

# フォールバック実行を禁止するアクション
# エラー時に「とりあえず実行」してはいけない
NO_FALLBACK_ACTIONS: Set[str] = {
    "goal_registration",
    "goal_setting",
    "handle_goal_registration",
    "task_execution",
    "memory_write",
    "announcement_send",
}

# =============================================================================
# セッションとタイムアウト
# =============================================================================

# セッションのデフォルトタイムアウト（分）
SESSION_TIMEOUT_MINUTES: int = 30

# 目標設定セッションのタイムアウト（分）
GOAL_SETTING_TIMEOUT_MINUTES: int = 1440  # 24時間

# アナウンス確認のタイムアウト（分）
ANNOUNCEMENT_TIMEOUT_MINUTES: int = 60  # 1時間

# 確認モードのタイムアウト（分）
CONFIRMATION_TIMEOUT_MINUTES: int = 5

# 最大リトライ回数
MAX_RETRY_COUNT: int = 3

# =============================================================================
# キャンセル検出
# =============================================================================

# キャンセルと判断するキーワード
# これらのキーワードが含まれる場合、現在のセッションをキャンセルする
CANCEL_KEYWORDS: List[str] = [
    # 直接的なキャンセル
    "やめる",
    "やめて",
    "やめた",
    "やめます",
    "キャンセル",
    "cancel",
    "中止",
    "止めて",
    "とめて",
    # 間接的なキャンセル
    "やっぱり",
    "やっぱいい",
    "やっぱりいい",
    "もういい",
    "もういいや",
    "いらない",
    "いらん",
    # 終了系
    "終わり",
    "終了",
    "おわり",
    "おしまい",
    # 否定系
    "やらない",
    "しない",
    "やめとく",
    "やめておく",
]

# =============================================================================
# 記憶の優先度
# =============================================================================

# 記憶を取得する際の優先度（数字が小さいほど優先）
MEMORY_PRIORITY: Dict[str, int] = {
    "current_state": 1,       # 現在の状態（最優先）
    "recent_conversation": 2,  # 直近の会話
    "conversation_summary": 3, # 会話要約
    "user_preferences": 4,     # ユーザー嗜好
    "person_info": 5,         # 人物情報
    "recent_tasks": 6,        # タスク情報
    "active_goals": 7,        # 目標情報
    "relevant_knowledge": 8,  # 会社知識
    "insights": 9,            # インサイト
    "conversation_search": 10, # 会話検索
}

# 直近の会話を取得する件数
RECENT_CONVERSATION_LIMIT: int = 10

# 関連タスクを取得する件数
RECENT_TASKS_LIMIT: int = 20

# インサイトを取得する件数
INSIGHTS_LIMIT: int = 5

# =============================================================================
# 理解層の設定
# =============================================================================

# 代名詞のリスト（解決が必要なもの）
PRONOUNS: Set[str] = {
    "あれ",
    "これ",
    "それ",
    "あの",
    "この",
    "その",
    "あの人",
    "この人",
    "その人",
    "彼",
    "彼女",
    "あいつ",
    "やつ",
}

# 時間表現の解決パターン
TIME_EXPRESSIONS: Dict[str, str] = {
    "今日": "today",
    "明日": "tomorrow",
    "明後日": "day_after_tomorrow",
    "昨日": "yesterday",
    "一昨日": "day_before_yesterday",
    "来週": "next_week",
    "先週": "last_week",
    "今週": "this_week",
    "来月": "next_month",
    "先月": "last_month",
    "今月": "this_month",
    "月末": "end_of_month",
    "週末": "weekend",
    "さっき": "just_now",
    "この前": "recently",
    "最近": "recently",
}

# 緊急度を示すキーワード
URGENCY_KEYWORDS: Dict[str, str] = {
    # 高緊急度
    "すぐ": "high",
    "急ぎ": "high",
    "至急": "high",
    "緊急": "high",
    "今すぐ": "high",
    "大至急": "high",
    "できるだけ早く": "high",
    "ASAP": "high",
    # 中緊急度
    "なるべく": "medium",
    "できれば": "medium",
    "早めに": "medium",
    # 低緊急度
    "いつでも": "low",
    "暇な時": "low",
    "時間ある時": "low",
    "余裕ある時": "low",
}

# =============================================================================
# 判断層の設定
# =============================================================================

# 機能選択時の重み付け
# v10.42.0 P2: life_axis_alignment追加（従来の重みを調整）
CAPABILITY_SCORING_WEIGHTS: Dict[str, float] = {
    "keyword_match": 0.35,      # キーワードマッチ（0.4→0.35）
    "intent_match": 0.25,       # 意図マッチ（0.3→0.25）
    "context_match": 0.25,      # 文脈マッチ（0.3→0.25）
    "life_axis_alignment": 0.15,  # 人生軸との整合性（v10.42.0 P2）
}

# 複数アクション検出用の接続詞
CONJUNCTION_PATTERNS: List[str] = [
    "あと",
    "それと",
    "それから",
    "ついでに",
    "と",
    "、",
    "。",
    "で、",
    "んで",
    "して",
    "したら",
]

# 複数アクション分割用の正規表現パターン
SPLIT_PATTERNS: List[str] = [
    r"。\s*(?:あと|それと|それから|ついでに)",  # 句点 + 接続詞
    r"、\s*(?:あと|それと|それから|ついでに)",  # 読点 + 接続詞
    r"(?:あと|それと|それから|ついでに)\s*(?:、|。)?",  # 接続詞単体
    r"(?:して|したら|できたら)\s*(?:、|。)?",  # 依頼の連結
]

# 機能候補の最低スコア閾値
CAPABILITY_MIN_SCORE_THRESHOLD: float = 0.1

# リスクレベル定義
# v10.48.10: general_conversation追加（確認不要にするため）
RISK_LEVELS: Dict[str, str] = {
    # 低リスク（確認不要）
    "general_conversation": "low",  # 一般会話は確認不要
    "chatwork_task_create": "low",
    "chatwork_task_complete": "low",
    "chatwork_task_search": "low",
    "goal_registration": "low",  # v10.29.6: SYSTEM_CAPABILITIESと名前を統一
    "goal_progress_report": "low",
    "goal_status_check": "low",
    "goal_review": "low",
    "goal_consult": "low",
    "save_memory": "low",
    "query_memory": "low",
    "learn_knowledge": "low",
    "query_knowledge": "low",
    "query_org_chart": "low",
    "daily_reflection": "low",
    # 中リスク
    "delete_memory": "medium",
    "forget_knowledge": "medium",
    "send_announcement": "medium",
    "announcement_create": "medium",
    # 高リスク（要確認）
    "delete": "high",
    "remove": "high",
    "send_all": "high",
}

# 確認が必要なリスクレベル
CONFIRMATION_REQUIRED_RISK_LEVELS: Set[str] = {"high"}

# =============================================================================
# 状態タイプ
# =============================================================================

# 有効な状態タイプ
VALID_STATE_TYPES: Set[str] = {
    "normal",           # 通常状態（状態なし）
    "goal_setting",     # 目標設定対話中
    "announcement",     # アナウンス確認中
    "confirmation",     # 確認待ち
    "task_pending",     # タスク作成待ち
    "multi_action",     # 複数アクション実行中
}

# 状態ごとのデフォルトタイムアウト（分）
STATE_TIMEOUTS: Dict[str, int] = {
    "normal": 0,  # タイムアウトなし
    "goal_setting": GOAL_SETTING_TIMEOUT_MINUTES,
    "announcement": ANNOUNCEMENT_TIMEOUT_MINUTES,
    "confirmation": CONFIRMATION_TIMEOUT_MINUTES,
    "task_pending": SESSION_TIMEOUT_MINUTES,
    "multi_action": SESSION_TIMEOUT_MINUTES,
}

# =============================================================================
# レスポンス生成
# =============================================================================

# ソウルくんの口調テンプレート
SOULKUN_SUFFIXES: List[str] = [
    "ウル",
    "ウル！",
    "ウル🐺",
    "ウル✨",
]

# 確認メッセージのテンプレート
CONFIRMATION_TEMPLATE: str = """🤔 確認させてほしいウル！

{question}

{options}

番号で教えてほしいウル🐺"""

# キャンセル完了メッセージ
CANCEL_MESSAGE: str = "了解ウル！キャンセルしたウル🐺"

# エラーメッセージ（汎用）
ERROR_MESSAGE: str = "ごめんウル...ちょっとエラーが起きたみたいウル🐺 もう一回試してみてほしいウル"

# =============================================================================
# パフォーマンス設定
# =============================================================================

# 理解層のタイムアウト（秒）
UNDERSTANDING_TIMEOUT_SECONDS: int = 30

# 判断層のタイムアウト（秒）
DECISION_TIMEOUT_SECONDS: int = 10

# 実行層のタイムアウト（秒）
EXECUTION_TIMEOUT_SECONDS: int = 60

# 記憶取得の並列実行数
MEMORY_FETCH_CONCURRENCY: int = 5

# =============================================================================
# デバッグ設定
# =============================================================================

# デバッグモード（詳細ログ出力）
DEBUG_MODE: bool = False

# 判断ログを保存するか
SAVE_DECISION_LOGS: bool = True

# 記憶アクセスログを保存するか
SAVE_MEMORY_ACCESS_LOGS: bool = False
