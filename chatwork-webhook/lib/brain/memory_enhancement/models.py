"""
Phase 2G: 記憶の強化（Memory Enhancement）- データモデル

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2G

エピソード記憶、知識グラフ、時系列記憶のデータモデル定義。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .constants import (
    BASE_IMPORTANCE,
    ComparisonType,
    ConsolidationAction,
    ConsolidationType,
    EdgeType,
    EntityRelationship,
    EntityType,
    EpisodeType,
    KnowledgeSource,
    NodeType,
    RecallTrigger,
    TemporalEventType,
    TrendType,
    EPISODE_DECAY_DEFAULT,
    EPISODE_IMPORTANCE_DEFAULT,
    EMOTIONAL_VALENCE_DEFAULT,
    KNOWLEDGE_CONFIDENCE_DEFAULT,
    EDGE_WEIGHT_DEFAULT,
)


# ============================================================================
# エピソード記憶モデル
# ============================================================================

@dataclass
class RelatedEntity:
    """関連エンティティ

    エピソードに関連する人物、タスク、目標などのエンティティ。
    """
    entity_type: EntityType
    entity_id: str
    entity_name: Optional[str] = None
    relationship: EntityRelationship = EntityRelationship.INVOLVED
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "entity_type": self.entity_type.value if isinstance(self.entity_type, EntityType) else self.entity_type,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "relationship": self.relationship.value if isinstance(self.relationship, EntityRelationship) else self.relationship,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RelatedEntity":
        """辞書から生成"""
        entity_type = data.get("entity_type", "person")
        if isinstance(entity_type, str):
            try:
                entity_type = EntityType(entity_type)
            except ValueError:
                entity_type = EntityType.PERSON

        relationship = data.get("relationship", "involved")
        if isinstance(relationship, str):
            try:
                relationship = EntityRelationship(relationship)
            except ValueError:
                relationship = EntityRelationship.INVOLVED

        return cls(
            entity_type=entity_type,
            entity_id=data.get("entity_id", ""),
            entity_name=data.get("entity_name"),
            relationship=relationship,
            metadata=data.get("metadata", {}),
        )


@dataclass
class Episode:
    """エピソード記憶

    人間の記憶におけるエピソード記憶（出来事の記憶）をモデル化。
    「いつ」「どこで」「誰と」「何が」起きたかを記録する。
    """
    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None
    user_id: Optional[str] = None           # NULLなら組織全体の記憶

    # エピソード内容
    episode_type: EpisodeType = EpisodeType.INTERACTION
    summary: str = ""                       # 要約（100字程度）
    details: Dict[str, Any] = field(default_factory=dict)

    # 感情・重要度
    emotional_valence: float = EMOTIONAL_VALENCE_DEFAULT  # -1.0〜1.0
    importance_score: float = EPISODE_IMPORTANCE_DEFAULT  # 0.0〜1.0

    # 検索用
    keywords: List[str] = field(default_factory=list)
    related_entities: List[RelatedEntity] = field(default_factory=list)
    embedding_id: Optional[str] = None      # ベクトル埋め込みID

    # 想起管理
    recall_count: int = 0
    last_recalled_at: Optional[datetime] = None
    decay_factor: float = EPISODE_DECAY_DEFAULT  # 忘却係数

    # メタデータ
    occurred_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    source: Optional[str] = None            # 記録元（conversation, system等）

    def __post_init__(self):
        """初期化後処理"""
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.occurred_at is None:
            self.occurred_at = self.created_at

    @property
    def effective_importance(self) -> float:
        """実効重要度（忘却係数を考慮）"""
        return self.importance_score * self.decay_factor

    @property
    def is_positive(self) -> bool:
        """ポジティブなエピソードか"""
        return self.emotional_valence > 0.2

    @property
    def is_negative(self) -> bool:
        """ネガティブなエピソードか"""
        return self.emotional_valence < -0.2

    @property
    def should_forget(self) -> bool:
        """忘却すべきか"""
        from .constants import FORGET_THRESHOLD, MIN_IMPORTANCE_FOR_RETENTION
        return (
            self.decay_factor < FORGET_THRESHOLD and
            self.importance_score < MIN_IMPORTANCE_FOR_RETENTION
        )

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "user_id": self.user_id,
            "episode_type": self.episode_type.value if isinstance(self.episode_type, EpisodeType) else self.episode_type,
            "summary": self.summary,
            "details": self.details,
            "emotional_valence": self.emotional_valence,
            "importance_score": self.importance_score,
            "keywords": self.keywords,
            "related_entities": [e.to_dict() for e in self.related_entities],
            "embedding_id": self.embedding_id,
            "recall_count": self.recall_count,
            "last_recalled_at": self.last_recalled_at.isoformat() if self.last_recalled_at else None,
            "decay_factor": self.decay_factor,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Episode":
        """辞書から生成"""
        episode_type = data.get("episode_type", "interaction")
        if isinstance(episode_type, str):
            try:
                episode_type = EpisodeType(episode_type)
            except ValueError:
                episode_type = EpisodeType.INTERACTION

        related_entities = [
            RelatedEntity.from_dict(e) if isinstance(e, dict) else e
            for e in data.get("related_entities", [])
        ]

        def parse_datetime(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            return datetime.fromisoformat(val.replace("Z", "+00:00"))

        return cls(
            id=data.get("id"),
            organization_id=data.get("organization_id"),
            user_id=data.get("user_id"),
            episode_type=episode_type,
            summary=data.get("summary", ""),
            details=data.get("details", {}),
            emotional_valence=data.get("emotional_valence", EMOTIONAL_VALENCE_DEFAULT),
            importance_score=data.get("importance_score", EPISODE_IMPORTANCE_DEFAULT),
            keywords=data.get("keywords", []),
            related_entities=related_entities,
            embedding_id=data.get("embedding_id"),
            recall_count=data.get("recall_count", 0),
            last_recalled_at=parse_datetime(data.get("last_recalled_at")),
            decay_factor=data.get("decay_factor", EPISODE_DECAY_DEFAULT),
            occurred_at=parse_datetime(data.get("occurred_at")),
            created_at=parse_datetime(data.get("created_at")),
            updated_at=parse_datetime(data.get("updated_at")),
            source=data.get("source"),
        )


@dataclass
class RecallResult:
    """想起結果

    記憶の想起結果を表す。
    """
    episode: Episode
    relevance_score: float                  # 関連度（0.0〜1.0）
    trigger: RecallTrigger                  # 想起のトリガー
    matched_keywords: List[str] = field(default_factory=list)
    matched_entities: List[str] = field(default_factory=list)
    reasoning: str = ""                     # 想起理由の説明

    @property
    def final_score(self) -> float:
        """最終スコア（関連度×実効重要度）"""
        return self.relevance_score * self.episode.effective_importance


# ============================================================================
# 知識グラフモデル
# ============================================================================

@dataclass
class KnowledgeNode:
    """知識ノード

    概念、エンティティ、アクションなどを表すノード。
    """
    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # ノード情報
    node_type: NodeType = NodeType.CONCEPT
    name: str = ""
    description: Optional[str] = None
    aliases: List[str] = field(default_factory=list)  # 別名

    # 属性
    properties: Dict[str, Any] = field(default_factory=dict)

    # 重要度・活性度
    importance_score: float = 0.5           # 0.0〜1.0
    activation_level: float = 0.5           # 最近どれだけ使われたか

    # メタデータ
    source: KnowledgeSource = KnowledgeSource.SYSTEM
    evidence_count: int = 1                 # このノードを裏付けるエビデンス数
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        """初期化後処理"""
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now()

    def matches_name(self, query: str) -> bool:
        """名前または別名にマッチするか"""
        query_lower = query.lower()
        if self.name.lower() == query_lower:
            return True
        return any(alias.lower() == query_lower for alias in self.aliases)

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "node_type": self.node_type.value if isinstance(self.node_type, NodeType) else self.node_type,
            "name": self.name,
            "description": self.description,
            "aliases": self.aliases,
            "properties": self.properties,
            "importance_score": self.importance_score,
            "activation_level": self.activation_level,
            "source": self.source.value if isinstance(self.source, KnowledgeSource) else self.source,
            "evidence_count": self.evidence_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeNode":
        """辞書から生成"""
        node_type = data.get("node_type", "concept")
        if isinstance(node_type, str):
            try:
                node_type = NodeType(node_type)
            except ValueError:
                node_type = NodeType.CONCEPT

        source = data.get("source", "system")
        if isinstance(source, str):
            try:
                source = KnowledgeSource(source)
            except ValueError:
                source = KnowledgeSource.SYSTEM

        def parse_datetime(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            return datetime.fromisoformat(val.replace("Z", "+00:00"))

        return cls(
            id=data.get("id"),
            organization_id=data.get("organization_id"),
            node_type=node_type,
            name=data.get("name", ""),
            description=data.get("description"),
            aliases=data.get("aliases", []),
            properties=data.get("properties", {}),
            importance_score=data.get("importance_score", 0.5),
            activation_level=data.get("activation_level", 0.5),
            source=source,
            evidence_count=data.get("evidence_count", 1),
            created_at=parse_datetime(data.get("created_at")),
            updated_at=parse_datetime(data.get("updated_at")),
        )


@dataclass
class KnowledgeEdge:
    """知識エッジ

    2つのノード間の関係を表すエッジ。
    """
    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # 関係
    source_node_id: str = ""
    target_node_id: str = ""
    relation_type: EdgeType = EdgeType.RELATED_TO

    # 属性
    weight: float = EDGE_WEIGHT_DEFAULT     # 関係の強さ
    confidence: float = KNOWLEDGE_CONFIDENCE_DEFAULT  # 確信度
    properties: Dict[str, Any] = field(default_factory=dict)

    # 双方向性
    is_bidirectional: bool = False

    # メタデータ
    evidence_count: int = 1
    source: KnowledgeSource = KnowledgeSource.SYSTEM
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        """初期化後処理"""
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now()

    @property
    def is_strong(self) -> bool:
        """強い関係か"""
        return self.weight >= 0.7 and self.confidence >= 0.7

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "relation_type": self.relation_type.value if isinstance(self.relation_type, EdgeType) else self.relation_type,
            "weight": self.weight,
            "confidence": self.confidence,
            "properties": self.properties,
            "is_bidirectional": self.is_bidirectional,
            "evidence_count": self.evidence_count,
            "source": self.source.value if isinstance(self.source, KnowledgeSource) else self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeEdge":
        """辞書から生成"""
        relation_type = data.get("relation_type", "related_to")
        if isinstance(relation_type, str):
            try:
                relation_type = EdgeType(relation_type)
            except ValueError:
                relation_type = EdgeType.RELATED_TO

        source = data.get("source", "system")
        if isinstance(source, str):
            try:
                source = KnowledgeSource(source)
            except ValueError:
                source = KnowledgeSource.SYSTEM

        def parse_datetime(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            return datetime.fromisoformat(val.replace("Z", "+00:00"))

        return cls(
            id=data.get("id"),
            organization_id=data.get("organization_id"),
            source_node_id=data.get("source_node_id", ""),
            target_node_id=data.get("target_node_id", ""),
            relation_type=relation_type,
            weight=data.get("weight", EDGE_WEIGHT_DEFAULT),
            confidence=data.get("confidence", KNOWLEDGE_CONFIDENCE_DEFAULT),
            properties=data.get("properties", {}),
            is_bidirectional=data.get("is_bidirectional", False),
            evidence_count=data.get("evidence_count", 1),
            source=source,
            created_at=parse_datetime(data.get("created_at")),
            updated_at=parse_datetime(data.get("updated_at")),
        )


@dataclass
class KnowledgeSubgraph:
    """知識サブグラフ

    中心ノードとその周辺ノード・エッジの集合。
    """
    center_node: KnowledgeNode
    nodes: List[KnowledgeNode] = field(default_factory=list)
    edges: List[KnowledgeEdge] = field(default_factory=list)
    depth: int = 1

    def get_node_by_id(self, node_id: str) -> Optional[KnowledgeNode]:
        """IDでノードを取得"""
        if self.center_node.id == node_id:
            return self.center_node
        return next((n for n in self.nodes if n.id == node_id), None)


# ============================================================================
# 時系列記憶モデル
# ============================================================================

@dataclass
class TemporalEvent:
    """時系列イベント

    時間軸上のイベントを記録し、比較可能にする。
    """
    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None
    user_id: Optional[str] = None

    # イベント情報
    event_type: TemporalEventType = TemporalEventType.MEETING
    event_name: str = ""

    # 時間情報
    occurred_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None

    # メトリクス・値
    numeric_value: Optional[float] = None   # 数値（売上、完了数等）
    string_value: Optional[str] = None      # 文字列（ステータス等）

    # 詳細
    details: Dict[str, Any] = field(default_factory=dict)

    # 関連
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[str] = None

    # メタデータ
    source: Optional[str] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        """初期化後処理"""
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.occurred_at is None:
            self.occurred_at = self.created_at

    @property
    def has_numeric_value(self) -> bool:
        """数値を持つか"""
        return self.numeric_value is not None

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "user_id": self.user_id,
            "event_type": self.event_type.value if isinstance(self.event_type, TemporalEventType) else self.event_type,
            "event_name": self.event_name,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "duration_minutes": self.duration_minutes,
            "numeric_value": self.numeric_value,
            "string_value": self.string_value,
            "details": self.details,
            "related_entity_type": self.related_entity_type,
            "related_entity_id": self.related_entity_id,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemporalEvent":
        """辞書から生成"""
        event_type = data.get("event_type", "meeting")
        if isinstance(event_type, str):
            try:
                event_type = TemporalEventType(event_type)
            except ValueError:
                event_type = TemporalEventType.MEETING

        def parse_datetime(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            return datetime.fromisoformat(val.replace("Z", "+00:00"))

        return cls(
            id=data.get("id"),
            organization_id=data.get("organization_id"),
            user_id=data.get("user_id"),
            event_type=event_type,
            event_name=data.get("event_name", ""),
            occurred_at=parse_datetime(data.get("occurred_at")),
            duration_minutes=data.get("duration_minutes"),
            numeric_value=data.get("numeric_value"),
            string_value=data.get("string_value"),
            details=data.get("details", {}),
            related_entity_type=data.get("related_entity_type"),
            related_entity_id=data.get("related_entity_id"),
            source=data.get("source"),
            created_at=parse_datetime(data.get("created_at")),
        )


@dataclass
class TemporalComparison:
    """時系列比較結果

    2つのイベントの比較結果を保持。
    """
    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # 比較対象
    event_type: str = ""
    current_event_id: Optional[str] = None
    previous_event_id: Optional[str] = None
    current_event: Optional[TemporalEvent] = None
    previous_event: Optional[TemporalEvent] = None

    # 比較結果
    comparison_type: ComparisonType = ComparisonType.FIRST
    delta_value: Optional[float] = None     # 差分
    delta_percentage: Optional[float] = None  # 変化率
    trend: TrendType = TrendType.UNKNOWN

    # 生成されたインサイト
    insight: Optional[str] = None
    confidence: float = 0.5

    # メタデータ
    compared_at: Optional[datetime] = None

    def __post_init__(self):
        """初期化後処理"""
        if self.id is None:
            self.id = str(uuid4())
        if self.compared_at is None:
            self.compared_at = datetime.now()

    @property
    def is_improvement(self) -> bool:
        """改善したか"""
        return self.comparison_type in (ComparisonType.INCREASE, ComparisonType.BETTER)

    @property
    def is_decline(self) -> bool:
        """悪化したか"""
        return self.comparison_type in (ComparisonType.DECREASE, ComparisonType.WORSE)

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "event_type": self.event_type,
            "current_event_id": self.current_event_id,
            "previous_event_id": self.previous_event_id,
            "comparison_type": self.comparison_type.value if isinstance(self.comparison_type, ComparisonType) else self.comparison_type,
            "delta_value": self.delta_value,
            "delta_percentage": self.delta_percentage,
            "trend": self.trend.value if isinstance(self.trend, TrendType) else self.trend,
            "insight": self.insight,
            "confidence": self.confidence,
            "compared_at": self.compared_at.isoformat() if self.compared_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemporalComparison":
        """辞書から生成"""
        comparison_type = data.get("comparison_type", "first")
        if isinstance(comparison_type, str):
            try:
                comparison_type = ComparisonType(comparison_type)
            except ValueError:
                comparison_type = ComparisonType.FIRST

        trend = data.get("trend", "unknown")
        if isinstance(trend, str):
            try:
                trend = TrendType(trend)
            except ValueError:
                trend = TrendType.UNKNOWN

        def parse_datetime(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            return datetime.fromisoformat(val.replace("Z", "+00:00"))

        return cls(
            id=data.get("id"),
            organization_id=data.get("organization_id"),
            event_type=data.get("event_type", ""),
            current_event_id=data.get("current_event_id"),
            previous_event_id=data.get("previous_event_id"),
            comparison_type=comparison_type,
            delta_value=data.get("delta_value"),
            delta_percentage=data.get("delta_percentage"),
            trend=trend,
            insight=data.get("insight"),
            confidence=data.get("confidence", 0.5),
            compared_at=parse_datetime(data.get("compared_at")),
        )


# ============================================================================
# 記憶統合モデル
# ============================================================================

@dataclass
class ConsolidationResult:
    """記憶統合結果

    記憶の統合処理の結果を記録。
    """
    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # 統合情報
    consolidation_type: ConsolidationType = ConsolidationType.DAILY

    # 処理結果
    episodes_processed: int = 0
    episodes_merged: int = 0
    episodes_forgotten: int = 0
    patterns_extracted: int = 0
    knowledge_nodes_created: int = 0
    knowledge_edges_created: int = 0

    # 詳細
    details: Dict[str, Any] = field(default_factory=dict)
    actions: List[Dict[str, Any]] = field(default_factory=list)

    # メタデータ
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def __post_init__(self):
        """初期化後処理"""
        if self.id is None:
            self.id = str(uuid4())
        if self.started_at is None:
            self.started_at = datetime.now()

    @property
    def duration_seconds(self) -> Optional[float]:
        """処理時間（秒）"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def is_completed(self) -> bool:
        """完了したか"""
        return self.completed_at is not None

    def add_action(
        self,
        action: ConsolidationAction,
        target_id: str,
        description: str,
    ):
        """アクションを追加"""
        self.actions.append({
            "action": action.value if isinstance(action, ConsolidationAction) else action,
            "target_id": target_id,
            "description": description,
            "timestamp": datetime.now().isoformat(),
        })

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "consolidation_type": self.consolidation_type.value if isinstance(self.consolidation_type, ConsolidationType) else self.consolidation_type,
            "episodes_processed": self.episodes_processed,
            "episodes_merged": self.episodes_merged,
            "episodes_forgotten": self.episodes_forgotten,
            "patterns_extracted": self.patterns_extracted,
            "knowledge_nodes_created": self.knowledge_nodes_created,
            "knowledge_edges_created": self.knowledge_edges_created,
            "details": self.details,
            "actions": self.actions,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ============================================================================
# 統計モデル
# ============================================================================

@dataclass
class MemoryStatistics:
    """記憶統計

    記憶システム全体の統計情報。
    """
    # エピソード統計
    total_episodes: int = 0
    episodes_by_type: Dict[str, int] = field(default_factory=dict)
    avg_importance: float = 0.0
    avg_decay: float = 0.0
    total_recalls: int = 0

    # 知識グラフ統計
    total_nodes: int = 0
    nodes_by_type: Dict[str, int] = field(default_factory=dict)
    total_edges: int = 0
    edges_by_type: Dict[str, int] = field(default_factory=dict)

    # 時系列統計
    total_temporal_events: int = 0
    events_by_type: Dict[str, int] = field(default_factory=dict)
    total_comparisons: int = 0

    # 統合統計
    last_consolidation_at: Optional[datetime] = None
    total_consolidations: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "total_episodes": self.total_episodes,
            "episodes_by_type": self.episodes_by_type,
            "avg_importance": self.avg_importance,
            "avg_decay": self.avg_decay,
            "total_recalls": self.total_recalls,
            "total_nodes": self.total_nodes,
            "nodes_by_type": self.nodes_by_type,
            "total_edges": self.total_edges,
            "edges_by_type": self.edges_by_type,
            "total_temporal_events": self.total_temporal_events,
            "events_by_type": self.events_by_type,
            "total_comparisons": self.total_comparisons,
            "last_consolidation_at": self.last_consolidation_at.isoformat() if self.last_consolidation_at else None,
            "total_consolidations": self.total_consolidations,
        }
