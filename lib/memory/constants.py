"""
Phase 2 B: 記憶基盤 定数定義

このモジュールは、記憶機能で使用する定数、Enum、パラメータを定義します。

Author: Claude Code
Created: 2026-01-24
"""

from enum import Enum
from typing import Final


# ================================================================
# 記憶パラメータ
# ================================================================

class MemoryParameters:
    """記憶機能のデフォルトパラメータ"""

    # B1: 会話サマリー記憶
    SUMMARY_TRIGGER_COUNT: Final[int] = 10          # サマリー生成トリガーメッセージ数
    SUMMARY_MAX_LENGTH: Final[int] = 500            # サマリーの最大文字数
    SUMMARY_RETENTION_DAYS: Final[int] = 90         # サマリー保持期間（日）
    SUMMARY_MAX_TOPICS: Final[int] = 5              # 最大トピック数
    SUMMARY_MAX_PERSONS: Final[int] = 10            # 最大人物数
    SUMMARY_MAX_TASKS: Final[int] = 10              # 最大タスク数

    # B2: ユーザー嗜好学習
    PREFERENCE_INITIAL_CONFIDENCE: Final[float] = 0.5   # 初期信頼度
    PREFERENCE_MAX_CONFIDENCE: Final[float] = 0.95      # 最大信頼度
    PREFERENCE_CONFIDENCE_INCREMENT: Final[float] = 0.1 # 信頼度増加量
    PREFERENCE_MIN_SAMPLES: Final[int] = 3              # 学習に必要な最小サンプル数

    # B3: 組織知識自動蓄積
    KNOWLEDGE_AUTO_GENERATE_THRESHOLD: Final[int] = 5   # 自動生成閾値（occurrence_count）
    KNOWLEDGE_ANSWER_MAX_LENGTH: Final[int] = 1000      # 回答の最大文字数
    KNOWLEDGE_MAX_KEYWORDS: Final[int] = 10             # 最大キーワード数

    # B4: 会話検索
    SEARCH_DEFAULT_LIMIT: Final[int] = 10               # デフォルト検索件数
    SEARCH_MAX_LIMIT: Final[int] = 100                  # 最大検索件数
    SEARCH_CONTEXT_WINDOW: Final[int] = 5               # 前後の会話数
    SEARCH_INDEX_RETENTION_DAYS: Final[int] = 365       # インデックス保持期間（日）


# ================================================================
# Enum定義
# ================================================================

class PreferenceType(str, Enum):
    """嗜好タイプ"""
    RESPONSE_STYLE = "response_style"       # 回答スタイル
    FEATURE_USAGE = "feature_usage"         # よく使う機能
    COMMUNICATION = "communication"         # コミュニケーション傾向
    SCHEDULE = "schedule"                   # スケジュール傾向
    EMOTION_TREND = "emotion_trend"         # 感情傾向（A4連携）


class KnowledgeStatus(str, Enum):
    """組織知識ステータス"""
    DRAFT = "draft"             # 下書き
    APPROVED = "approved"       # 承認済み
    REJECTED = "rejected"       # 却下
    ARCHIVED = "archived"       # アーカイブ


class MessageType(str, Enum):
    """メッセージタイプ"""
    USER = "user"               # ユーザー発言
    ASSISTANT = "assistant"     # ソウルくん発言


class LearnedFrom(str, Enum):
    """学習元"""
    AUTO = "auto"               # 自動学習
    EXPLICIT = "explicit"       # 明示的に設定
    A4_EMOTION = "a4_emotion"   # A4感情検出連携


class GeneratedBy(str, Enum):
    """生成方法"""
    LLM = "llm"                 # LLM生成
    MANUAL = "manual"           # 手動作成


# ================================================================
# 嗜好キー定義
# ================================================================

class ResponseStyleKeys:
    """回答スタイルの嗜好キー"""
    LENGTH = "length"           # 簡潔 / 詳細
    FORMALITY = "formality"     # カジュアル / フォーマル
    EMOJI_USAGE = "emoji_usage" # 絵文字使用頻度
    EXPLANATION = "explanation" # 説明の詳しさ


class FeatureUsageKeys:
    """機能使用の嗜好キー"""
    TASK_CREATE = "task_create"         # タスク作成
    TASK_SEARCH = "task_search"         # タスク検索
    KNOWLEDGE_SEARCH = "knowledge_search"  # ナレッジ検索
    MEMORY = "memory"                   # 記憶機能
    GOAL_SETTING = "goal_setting"       # 目標設定


class CommunicationKeys:
    """コミュニケーションの嗜好キー"""
    ACTIVE_HOURS = "active_hours"       # アクティブな時間帯
    RESPONSE_SPEED = "response_speed"   # 返信速度の期待
    GREETING_STYLE = "greeting_style"   # 挨拶スタイル


class ScheduleKeys:
    """スケジュールの嗜好キー"""
    BUSY_DAYS = "busy_days"             # 忙しい曜日
    MEETING_HOURS = "meeting_hours"     # 会議が多い時間帯
    DEADLINE_BUFFER = "deadline_buffer" # 期限のバッファ


class EmotionTrendKeys:
    """感情傾向の嗜好キー（A4連携）"""
    BASELINE_SCORE = "baseline_score"       # ベースラインスコア
    VOLATILITY = "volatility"               # 変動の大きさ
    TREND_DIRECTION = "trend_direction"     # トレンド方向


# ================================================================
# プロンプトテンプレート
# ================================================================

CONVERSATION_SUMMARY_PROMPT = """
以下の会話履歴を要約してください。

【要約のポイント】
1. 主要なトピック（何について話したか）
2. 重要な決定事項や合意
3. 言及された人物名
4. 言及されたタスク
5. ユーザーの関心事や課題

【出力形式】JSON形式で出力してください。
{
  "summary": "200-500文字の要約",
  "key_topics": ["トピック1", "トピック2"],
  "mentioned_persons": ["人物1", "人物2"],
  "mentioned_tasks": ["タスク1"],
  "user_concerns": ["課題1"]
}

【会話履歴】
{conversation_history}

【注意】
- JSON形式のみ出力してください
- 説明文は不要です
"""

AUTO_KNOWLEDGE_GENERATION_PROMPT = """
以下の頻出質問に対する、組織内で使用できる回答を生成してください。

【頻出質問】
{question}

【質問の背景】
- この質問は過去{occurrence_count}回、{unique_users}人から寄せられました
- カテゴリ: {category}
- サンプル質問:
{sample_questions}

【回答の要件】
1. 簡潔かつ具体的に回答してください（500文字以内）
2. 社内用語があれば説明を付けてください
3. 関連するリンクや参照先があれば含めてください
4. 不明な点は「詳細は〇〇に確認してください」と案内してください

【出力形式】JSON形式で出力してください。
{
  "answer": "回答本文",
  "keywords": ["キーワード1", "キーワード2"],
  "related_topics": ["関連トピック1"]
}

【注意】
- JSON形式のみ出力してください
"""

KEYWORD_EXTRACTION_PROMPT = """
以下のメッセージから重要なキーワードを抽出してください。

【メッセージ】
{message}

【抽出対象】
- 人名
- 組織名・部署名
- プロジェクト名
- タスク・作業内容
- 期日・日時
- 専門用語

【出力形式】JSON形式で出力してください。
{
  "keywords": ["キーワード1", "キーワード2"],
  "entities": {
    "persons": ["人名1"],
    "organizations": ["組織名1"],
    "dates": ["日時1"],
    "tasks": ["タスク1"]
  }
}

【注意】
- JSON形式のみ出力してください
- キーワードは最大10個まで
"""
