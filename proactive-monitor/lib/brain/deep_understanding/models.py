# lib/brain/deep_understanding/models.py
"""
Phase 2I: 理解力強化（Deep Understanding）- データモデル

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I

このファイルには、深い理解層で使用するデータモデルを定義します。

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any, Set
from uuid import UUID, uuid4

from .constants import (
    ImplicitIntentType,
    ReferenceResolutionStrategy,
    OrganizationContextType,
    VocabularyCategory,
    EmotionCategory,
    UrgencyLevel,
    NuanceType,
    ContextRecoverySource,
)


# =============================================================================
# 意図推測関連モデル
# =============================================================================

@dataclass
class ResolvedReference:
    """
    解決された参照

    指示代名詞や省略が何を指しているかの解決結果。
    """
    # 元の表現
    original_expression: str

    # 解決後の値
    resolved_value: str

    # 参照タイプ
    reference_type: ImplicitIntentType

    # 解決戦略
    resolution_strategy: ReferenceResolutionStrategy

    # 信頼度（0.0〜1.0）
    confidence: float

    # 解決に使用したソース情報
    source_info: Dict[str, Any] = field(default_factory=dict)

    # 他の候補（複数候補がある場合）
    alternative_candidates: List[str] = field(default_factory=list)

    # 解決の根拠
    reasoning: str = ""


@dataclass
class ImplicitIntent:
    """
    暗黙の意図

    ユーザーの発話に含まれる暗黙的な意図を表現。
    """
    # 意図タイプ
    intent_type: ImplicitIntentType

    # 推測された具体的な意図
    inferred_intent: str

    # 信頼度（0.0〜1.0）
    confidence: float

    # 解決された参照のリスト
    resolved_references: List[ResolvedReference] = field(default_factory=list)

    # 元のメッセージ
    original_message: str = ""

    # 推論の根拠
    reasoning: str = ""

    # 確認が必要か
    needs_confirmation: bool = False

    # 確認用の選択肢
    confirmation_options: List[str] = field(default_factory=list)


@dataclass
class IntentInferenceResult:
    """
    意図推測の結果

    暗黙の意図推測の全体結果。
    """
    # 推測された暗黙の意図リスト
    implicit_intents: List[ImplicitIntent] = field(default_factory=list)

    # 最も確信度の高い意図
    primary_intent: Optional[ImplicitIntent] = None

    # 全体の信頼度
    overall_confidence: float = 0.0

    # 確認が必要か
    needs_confirmation: bool = False

    # 確認が必要な理由
    confirmation_reason: str = ""

    # 処理時間（ミリ秒）
    processing_time_ms: int = 0

    # 使用した戦略
    strategies_used: List[ReferenceResolutionStrategy] = field(default_factory=list)


# =============================================================================
# 組織文脈関連モデル
# =============================================================================

@dataclass
class VocabularyEntry:
    """
    組織語彙エントリ

    組織固有の用語・表現の定義。
    """
    # 一意識別子
    id: UUID = field(default_factory=uuid4)

    # 組織ID
    organization_id: str = ""

    # 語彙（キーワード）
    term: str = ""

    # カテゴリ
    category: VocabularyCategory = VocabularyCategory.IDIOM

    # 意味・説明
    meaning: str = ""

    # エイリアス（別の呼び方）
    aliases: List[str] = field(default_factory=list)

    # 関連語彙
    related_terms: List[str] = field(default_factory=list)

    # 使用例
    usage_examples: List[str] = field(default_factory=list)

    # 出現回数（学習用）
    occurrence_count: int = 0

    # 最終使用日時
    last_used_at: Optional[datetime] = None

    # 作成日時
    created_at: datetime = field(default_factory=datetime.now)

    # 更新日時
    updated_at: datetime = field(default_factory=datetime.now)

    # アクティブフラグ
    is_active: bool = True

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrganizationContext:
    """
    組織文脈

    ある表現が組織内で持つ文脈的な意味。
    """
    # 文脈タイプ
    context_type: OrganizationContextType

    # 元の表現
    original_expression: str

    # 解決された意味
    resolved_meaning: str

    # 関連する語彙エントリ
    vocabulary_entry: Optional[VocabularyEntry] = None

    # 信頼度
    confidence: float = 0.0

    # 解決に使用したソース
    source: str = ""

    # 追加のコンテキスト情報
    additional_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrganizationContextResult:
    """
    組織文脈解決の結果
    """
    # 解決された文脈リスト
    contexts: List[OrganizationContext] = field(default_factory=list)

    # 使用した語彙エントリ
    vocabulary_entries_used: List[VocabularyEntry] = field(default_factory=list)

    # 全体の信頼度
    overall_confidence: float = 0.0

    # 処理時間（ミリ秒）
    processing_time_ms: int = 0


# =============================================================================
# 感情・ニュアンス関連モデル
# =============================================================================

@dataclass
class DetectedEmotion:
    """
    検出された感情
    """
    # 感情カテゴリ
    category: EmotionCategory

    # 強度（0.0〜1.0）
    intensity: float

    # 信頼度（0.0〜1.0）
    confidence: float

    # 検出に使用した手がかり
    indicators: List[str] = field(default_factory=list)

    # 推論の根拠
    reasoning: str = ""


@dataclass
class DetectedUrgency:
    """
    検出された緊急度
    """
    # 緊急度レベル
    level: UrgencyLevel

    # 信頼度（0.0〜1.0）
    confidence: float

    # 推定期限（時間単位）
    estimated_deadline_hours: Optional[float] = None

    # 検出に使用した手がかり
    indicators: List[str] = field(default_factory=list)

    # 推論の根拠
    reasoning: str = ""


@dataclass
class DetectedNuance:
    """
    検出されたニュアンス
    """
    # ニュアンスタイプ
    nuance_type: NuanceType

    # 信頼度（0.0〜1.0）
    confidence: float

    # 検出に使用した手がかり
    indicators: List[str] = field(default_factory=list)

    # 推論の根拠
    reasoning: str = ""


@dataclass
class EmotionReadingResult:
    """
    感情・ニュアンス読み取りの結果
    """
    # 検出された感情リスト
    emotions: List[DetectedEmotion] = field(default_factory=list)

    # 主要な感情
    primary_emotion: Optional[DetectedEmotion] = None

    # 検出された緊急度
    urgency: Optional[DetectedUrgency] = None

    # 検出されたニュアンスリスト
    nuances: List[DetectedNuance] = field(default_factory=list)

    # 元のメッセージ
    original_message: str = ""

    # 全体の信頼度
    overall_confidence: float = 0.0

    # 処理時間（ミリ秒）
    processing_time_ms: int = 0

    # サマリー（人間が読める形式）
    summary: str = ""


# =============================================================================
# 文脈復元関連モデル
# =============================================================================

@dataclass
class ContextFragment:
    """
    文脈の断片

    会話履歴や過去のインタラクションから抽出された文脈情報。
    """
    # ソースタイプ
    source: ContextRecoverySource

    # 内容
    content: str

    # 関連度スコア（0.0〜1.0）
    relevance_score: float

    # タイムスタンプ
    timestamp: Optional[datetime] = None

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 元のソースID（会話ID、タスクID等）
    source_id: Optional[str] = None


@dataclass
class RecoveredContext:
    """
    復元された文脈
    """
    # 文脈断片のリスト
    fragments: List[ContextFragment] = field(default_factory=list)

    # 統合された文脈サマリー
    summary: str = ""

    # 主要なトピック
    main_topics: List[str] = field(default_factory=list)

    # 関連する人物
    related_persons: List[str] = field(default_factory=list)

    # 関連するタスク
    related_tasks: List[str] = field(default_factory=list)

    # 全体の信頼度
    overall_confidence: float = 0.0

    # 処理時間（ミリ秒）
    processing_time_ms: int = 0


# =============================================================================
# 統合モデル
# =============================================================================

@dataclass
class DeepUnderstandingInput:
    """
    深い理解層への入力
    """
    # ユーザーのメッセージ
    message: str

    # 組織ID
    organization_id: str

    # ユーザーID（オプション）
    user_id: Optional[str] = None

    # ChatWorkアカウントID（オプション）
    chatwork_account_id: Optional[str] = None

    # ルームID（オプション）
    room_id: Optional[str] = None

    # 直近の会話履歴
    recent_conversation: List[Dict[str, Any]] = field(default_factory=list)

    # 直近のタスク
    recent_tasks: List[Dict[str, Any]] = field(default_factory=list)

    # 人物情報
    person_info: List[Dict[str, Any]] = field(default_factory=list)

    # アクティブな目標
    active_goals: List[Dict[str, Any]] = field(default_factory=list)

    # 追加のコンテキスト
    additional_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeepUnderstandingOutput:
    """
    深い理解層からの出力
    """
    # 元の入力
    input: DeepUnderstandingInput = field(default_factory=lambda: DeepUnderstandingInput(message="", organization_id=""))

    # 意図推測結果
    intent_inference: Optional[IntentInferenceResult] = None

    # 組織文脈結果
    organization_context: Optional[OrganizationContextResult] = None

    # 感情読み取り結果
    emotion_reading: Optional[EmotionReadingResult] = None

    # 復元された文脈
    recovered_context: Optional[RecoveredContext] = None

    # 強化されたメッセージ（解決済み参照を含む）
    enhanced_message: str = ""

    # 全体の信頼度
    overall_confidence: float = 0.0

    # 確認が必要か
    needs_confirmation: bool = False

    # 確認理由
    confirmation_reason: str = ""

    # 確認用選択肢
    confirmation_options: List[str] = field(default_factory=list)

    # 処理時間（ミリ秒）
    processing_time_ms: int = 0

    # エラー情報
    errors: List[str] = field(default_factory=list)

    # 警告情報
    warnings: List[str] = field(default_factory=list)


# =============================================================================
# DB永続化用モデル
# =============================================================================

@dataclass
class VocabularyEntryDB:
    """
    組織語彙のDB永続化用モデル

    テーブル: organization_vocabulary
    """
    id: UUID
    organization_id: str
    term: str
    category: str
    meaning: str
    aliases: List[str]
    related_terms: List[str]
    usage_examples: List[str]
    occurrence_count: int
    last_used_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    is_active: bool
    metadata: Dict[str, Any]

    @classmethod
    def from_domain(cls, entry: VocabularyEntry) -> "VocabularyEntryDB":
        """ドメインモデルからDBモデルへ変換"""
        return cls(
            id=entry.id,
            organization_id=entry.organization_id,
            term=entry.term,
            category=entry.category.value,
            meaning=entry.meaning,
            aliases=entry.aliases,
            related_terms=entry.related_terms,
            usage_examples=entry.usage_examples,
            occurrence_count=entry.occurrence_count,
            last_used_at=entry.last_used_at,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            is_active=entry.is_active,
            metadata=entry.metadata,
        )

    def to_domain(self) -> VocabularyEntry:
        """DBモデルからドメインモデルへ変換"""
        return VocabularyEntry(
            id=self.id,
            organization_id=self.organization_id,
            term=self.term,
            category=VocabularyCategory(self.category),
            meaning=self.meaning,
            aliases=self.aliases,
            related_terms=self.related_terms,
            usage_examples=self.usage_examples,
            occurrence_count=self.occurrence_count,
            last_used_at=self.last_used_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
            is_active=self.is_active,
            metadata=self.metadata,
        )


@dataclass
class DeepUnderstandingLogDB:
    """
    深い理解のログDB永続化用モデル

    テーブル: deep_understanding_logs
    """
    id: UUID
    organization_id: str
    user_id: Optional[str]
    original_message: str
    enhanced_message: str
    intent_inference_json: Dict[str, Any]
    organization_context_json: Dict[str, Any]
    emotion_reading_json: Dict[str, Any]
    recovered_context_json: Dict[str, Any]
    overall_confidence: float
    needs_confirmation: bool
    processing_time_ms: int
    created_at: datetime


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    # 意図推測
    "ResolvedReference",
    "ImplicitIntent",
    "IntentInferenceResult",

    # 組織文脈
    "VocabularyEntry",
    "OrganizationContext",
    "OrganizationContextResult",

    # 感情・ニュアンス
    "DetectedEmotion",
    "DetectedUrgency",
    "DetectedNuance",
    "EmotionReadingResult",

    # 文脈復元
    "ContextFragment",
    "RecoveredContext",

    # 統合
    "DeepUnderstandingInput",
    "DeepUnderstandingOutput",

    # DB永続化
    "VocabularyEntryDB",
    "DeepUnderstandingLogDB",
]
