# lib/capabilities/apps/meeting_minutes/constants.py
"""
App1: 議事録自動生成 - 定数定義

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from enum import Enum
from typing import Dict, List, FrozenSet


# =============================================================================
# 列挙型
# =============================================================================


class MeetingType(str, Enum):
    """会議タイプ"""
    REGULAR = "regular"           # 定例会議
    PROJECT = "project"           # プロジェクト会議
    BRAINSTORM = "brainstorm"     # ブレスト
    DECISION = "decision"         # 意思決定会議
    REVIEW = "review"             # レビュー会議
    ONE_ON_ONE = "one_on_one"     # 1on1
    INTERVIEW = "interview"       # 面談・インタビュー
    TRAINING = "training"         # 研修・勉強会
    CLIENT = "client"             # クライアント会議
    UNKNOWN = "unknown"           # 不明


class MinutesStatus(str, Enum):
    """議事録ステータス"""
    PROCESSING = "processing"     # 処理中
    TRANSCRIBING = "transcribing" # 文字起こし中
    ANALYZING = "analyzing"       # 分析中
    GENERATING = "generating"     # 生成中
    PENDING = "pending"           # 確認待ち
    COMPLETED = "completed"       # 完了
    FAILED = "failed"             # 失敗


class MinutesSection(str, Enum):
    """議事録セクション"""
    OVERVIEW = "overview"         # 会議概要
    ATTENDEES = "attendees"       # 出席者
    AGENDA = "agenda"             # 議題
    DISCUSSION = "discussion"     # 議論内容
    DECISIONS = "decisions"       # 決定事項
    ACTION_ITEMS = "action_items" # アクションアイテム
    NEXT_MEETING = "next_meeting" # 次回予定
    APPENDIX = "appendix"         # 補足・参考資料


# =============================================================================
# デフォルト設定
# =============================================================================


# 議事録のデフォルトセクション構成
DEFAULT_MINUTES_SECTIONS: List[str] = [
    "会議概要",
    "出席者",
    "議題",
    "議論内容",
    "決定事項",
    "アクションアイテム",
    "次回予定",
]

# 会議タイプ別のセクション構成
MEETING_TYPE_SECTIONS: Dict[str, List[str]] = {
    MeetingType.REGULAR.value: [
        "会議概要",
        "出席者",
        "前回からの進捗",
        "議論内容",
        "決定事項",
        "アクションアイテム",
        "次回予定",
    ],
    MeetingType.PROJECT.value: [
        "会議概要",
        "出席者",
        "プロジェクト状況",
        "課題・リスク",
        "議論内容",
        "決定事項",
        "アクションアイテム",
        "次回マイルストーン",
    ],
    MeetingType.BRAINSTORM.value: [
        "会議概要",
        "出席者",
        "テーマ",
        "アイデア一覧",
        "有望なアイデア",
        "次のステップ",
    ],
    MeetingType.DECISION.value: [
        "会議概要",
        "出席者",
        "背景・経緯",
        "検討事項",
        "議論のポイント",
        "決定事項",
        "実行計画",
    ],
    MeetingType.ONE_ON_ONE.value: [
        "面談概要",
        "参加者",
        "話し合った内容",
        "フィードバック",
        "今後のアクション",
    ],
    MeetingType.CLIENT.value: [
        "会議概要",
        "出席者（自社）",
        "出席者（クライアント）",
        "議題",
        "議論内容",
        "合意事項",
        "宿題事項",
        "次回予定",
    ],
}


# =============================================================================
# 会議タイプ検出キーワード
# =============================================================================


MEETING_TYPE_KEYWORDS: Dict[str, List[str]] = {
    MeetingType.REGULAR.value: [
        "定例", "週次", "月次", "朝会", "夕会",
    ],
    MeetingType.PROJECT.value: [
        "プロジェクト", "PJ", "開発", "進捗", "マイルストーン",
    ],
    MeetingType.BRAINSTORM.value: [
        "ブレスト", "ブレインストーミング", "アイデア出し", "企画会議",
    ],
    MeetingType.DECISION.value: [
        "意思決定", "承認", "判断", "決裁",
    ],
    MeetingType.REVIEW.value: [
        "レビュー", "振り返り", "KPT", "反省会",
    ],
    MeetingType.ONE_ON_ONE.value: [
        "1on1", "面談", "個別", "キャリア",
    ],
    MeetingType.INTERVIEW.value: [
        "インタビュー", "ヒアリング", "取材",
    ],
    MeetingType.TRAINING.value: [
        "研修", "勉強会", "セミナー", "ワークショップ",
    ],
    MeetingType.CLIENT.value: [
        "クライアント", "お客様", "顧客", "商談", "提案",
    ],
}


# =============================================================================
# プロンプトテンプレート
# =============================================================================


MINUTES_ANALYSIS_PROMPT: str = """
あなたは優秀な議事録作成アシスタントです。
以下の会議の文字起こしを分析し、議事録に必要な情報を抽出してください。

【会議タイプ】
{meeting_type}

【文字起こし】
{transcript}

【話者情報】
{speakers}

【指示】
{instruction}

【出力形式】
以下のJSON形式で出力してください：
{{
    "meeting_title": "会議タイトル",
    "meeting_date": "推定日時（わかる場合）",
    "duration_estimate": "推定所要時間",
    "attendees": ["参加者1", "参加者2"],
    "main_topics": ["議題1", "議題2"],
    "key_discussions": [
        {{
            "topic": "トピック",
            "summary": "議論の要約",
            "speakers": ["発言者"]
        }}
    ],
    "decisions": ["決定事項1", "決定事項2"],
    "action_items": [
        {{
            "task": "タスク内容",
            "assignee": "担当者（わかる場合）",
            "deadline": "期限（わかる場合）"
        }}
    ],
    "next_meeting": "次回予定（言及がある場合）",
    "notes": "その他の重要な情報"
}}
"""


MINUTES_GENERATION_PROMPT: str = """
あなたは優秀な議事録作成アシスタントです。
以下の情報を元に、読みやすい議事録を作成してください。

【会議タイプ】
{meeting_type}

【分析結果】
{analysis}

【セクション構成】
{sections}

【トーン】
{tone}

【出力形式】
Markdown形式で議事録を作成してください。
各セクションは「## 」で始めてください。
箇条書きを活用し、読みやすくしてください。
"""


# =============================================================================
# サイズ制限
# =============================================================================


# 最大参加者数
MAX_ATTENDEES: int = 50

# 最大アクションアイテム数
MAX_ACTION_ITEMS: int = 30

# 最大決定事項数
MAX_DECISIONS: int = 20

# 議事録の最大文字数
MAX_MINUTES_LENGTH: int = 50000


# =============================================================================
# タイムアウト
# =============================================================================


# 文字起こしタイムアウト（秒）
TRANSCRIPTION_TIMEOUT: int = 600  # 10分

# 分析タイムアウト（秒）
ANALYSIS_TIMEOUT: int = 120  # 2分

# 生成タイムアウト（秒）
GENERATION_TIMEOUT: int = 300  # 5分


# =============================================================================
# Feature Flag
# =============================================================================


FEATURE_FLAG_MEETING_MINUTES: str = "USE_MEETING_MINUTES_APP"


# =============================================================================
# エラーメッセージ
# =============================================================================


ERROR_MESSAGES: Dict[str, str] = {
    "NO_AUDIO": "音声ファイルが指定されていません。",
    "TRANSCRIPTION_FAILED": "音声の文字起こしに失敗しました。",
    "ANALYSIS_FAILED": "会議内容の分析に失敗しました。",
    "GENERATION_FAILED": "議事録の生成に失敗しました。",
    "NO_SPEECH": "音声が検出されませんでした。",
    "AUDIO_TOO_LONG": "音声が長すぎます。{max}分以内にしてください。",
    "FEATURE_DISABLED": "議事録自動生成機能は現在無効です。",
}
