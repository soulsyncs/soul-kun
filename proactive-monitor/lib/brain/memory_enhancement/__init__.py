"""
Phase 2G: 記憶の強化（Memory Enhancement）モジュール

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2G

エピソード記憶と知識グラフの構築・管理を提供する。
「あの時のあの件」の想起、概念間の関係性理解を実現する。

使用例:
    from lib.brain.memory_enhancement import BrainMemoryEnhancement, create_memory_enhancement

    # 統合クラスを使用
    memory = create_memory_enhancement(organization_id)

    # エピソード記録
    episode_id = memory.record_episode(
        conn=conn,
        episode_type=EpisodeType.ACHIEVEMENT,
        summary="目標達成",
        content="山田さんが営業目標を達成した",
        user_id="user123",
    )

    # エピソード想起
    results = memory.recall_episodes(
        conn=conn,
        message="山田さんの成果",
        user_id="user123",
    )

    # 知識グラフノード追加
    node_id = memory.add_knowledge_node(
        conn=conn,
        name="カズさん",
        node_type=NodeType.PERSON,
    )

    # 関係追加
    edge_id = memory.add_knowledge_edge(
        conn=conn,
        source_node_id=kaz_node_id,
        target_node_id=org_node_id,
        edge_type=EdgeType.BELONGS_TO,
    )
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.engine import Connection

from .constants import (
    # Enums
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
    # Thresholds
    BASE_IMPORTANCE,
    DECAY_RATE_PER_DAY,
    EDGE_WEIGHT_DEFAULT,
    EMOTIONAL_VALENCE_DEFAULT,
    EPISODE_DECAY_DEFAULT,
    EPISODE_IMPORTANCE_DEFAULT,
    FORGET_THRESHOLD,
    IMPORTANT_KEYWORDS,
    KNOWLEDGE_CONFIDENCE_DEFAULT,
    MAX_RECALL_COUNT,
    MIN_IMPORTANCE_FOR_RETENTION,
    NODE_ACTIVATION_DECAY,
    EDGE_EVIDENCE_THRESHOLD,
    RECALL_IMPORTANCE_BOOST,
    RECALL_RELEVANCE_THRESHOLD,
    # Tables
    TABLE_BRAIN_EPISODES,
    TABLE_BRAIN_EPISODE_ENTITIES,
    TABLE_BRAIN_KNOWLEDGE_EDGES,
    TABLE_BRAIN_KNOWLEDGE_NODES,
    TABLE_BRAIN_MEMORY_CONSOLIDATIONS,
    TABLE_BRAIN_TEMPORAL_COMPARISONS,
    TABLE_BRAIN_TEMPORAL_EVENTS,
)
from .episode_repository import EpisodeRepository
from .knowledge_graph import KnowledgeGraph
from .models import (
    Episode,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeSubgraph,
    ConsolidationResult,
    RecallResult,
    RelatedEntity,
    TemporalComparison,
    TemporalEvent,
)


logger = logging.getLogger(__name__)


class BrainMemoryEnhancement:
    """記憶の強化統合クラス

    Phase 2Gの全機能を統合して提供する。

    主な機能:
    1. エピソード記憶（record_episode, recall_episodes）
    2. 知識グラフ（add_knowledge_node, add_knowledge_edge, query_subgraph）
    3. 時系列比較（record_temporal_event, compare_temporal_events）
    4. 記憶の統合（consolidate_memories）
    """

    def __init__(
        self,
        organization_id: str,
    ):
        """初期化

        Args:
            organization_id: 組織ID
        """
        self.organization_id = organization_id

        # 各コンポーネント
        self._episode_repo = EpisodeRepository(organization_id)
        self._knowledge_graph = KnowledgeGraph(organization_id)

        logger.info(f"BrainMemoryEnhancement initialized for org: {organization_id}")

    # ========================================================================
    # エピソード記憶
    # ========================================================================

    def record_episode(
        self,
        conn: Connection,
        episode_type: EpisodeType,
        summary: str,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        entities: Optional[List[RelatedEntity]] = None,
        importance: float = EPISODE_IMPORTANCE_DEFAULT,
        emotional_valence: float = EMOTIONAL_VALENCE_DEFAULT,
    ) -> str:
        """エピソードを記録

        Args:
            conn: DB接続
            episode_type: エピソードタイプ
            summary: 要約（1行）
            details: 詳細内容（JSONB）
            user_id: ユーザーID（None=組織全体の記憶）
            room_id: ルームID
            keywords: キーワードリスト
            entities: 関連エンティティリスト
            importance: 重要度（0.0-1.0）
            emotional_valence: 感情値（-1.0=ネガティブ, 0=中立, 1.0=ポジティブ）

        Returns:
            エピソードID
        """
        episode = Episode(
            organization_id=self.organization_id,
            user_id=user_id,
            episode_type=episode_type,
            summary=summary,
            details=details or {},
            keywords=keywords or [],
            related_entities=entities or [],
            importance_score=importance,
            emotional_valence=emotional_valence,
        )
        return self._episode_repo.save(conn, episode)

    def recall_episodes(
        self,
        conn: Connection,
        message: str,
        user_id: Optional[str] = None,
        limit: int = MAX_RECALL_COUNT,
        min_relevance: float = RECALL_RELEVANCE_THRESHOLD,
    ) -> List[RecallResult]:
        """メッセージに関連するエピソードを想起

        Args:
            conn: DB接続
            message: トリガーとなるメッセージ
            user_id: ユーザーID（None=組織全体の記憶）
            limit: 最大件数
            min_relevance: 最小関連度

        Returns:
            想起結果リスト
        """
        return self._episode_repo.recall(
            conn=conn,
            message=message,
            user_id=user_id,
            limit=limit,
            min_relevance=min_relevance,
        )

    def find_episodes_by_keywords(
        self,
        conn: Connection,
        keywords: List[str],
        user_id: Optional[str] = None,
        limit: int = MAX_RECALL_COUNT,
    ) -> List[Episode]:
        """キーワードでエピソードを検索

        Args:
            conn: DB接続
            keywords: 検索キーワード
            user_id: ユーザーID（None=組織全体）
            limit: 最大件数

        Returns:
            エピソードリスト
        """
        return self._episode_repo.find_by_keywords(
            conn=conn,
            keywords=keywords,
            user_id=user_id,
            limit=limit,
        )

    def find_episodes_by_entity(
        self,
        conn: Connection,
        entity_type: EntityType,
        entity_id: str,
        user_id: Optional[str] = None,
        limit: int = MAX_RECALL_COUNT,
    ) -> List[Episode]:
        """エンティティでエピソードを検索

        Args:
            conn: DB接続
            entity_type: エンティティタイプ
            entity_id: エンティティID
            user_id: ユーザーID（None=組織全体）
            limit: 最大件数

        Returns:
            エピソードリスト
        """
        return self._episode_repo.find_by_entity(
            conn=conn,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            limit=limit,
        )

    def get_episode(
        self,
        conn: Connection,
        episode_id: str,
    ) -> Optional[Episode]:
        """エピソードを取得

        Args:
            conn: DB接続
            episode_id: エピソードID

        Returns:
            エピソード（見つからない場合はNone）
        """
        return self._episode_repo.get(conn, episode_id)

    def update_episode_importance(
        self,
        conn: Connection,
        episode_id: str,
        importance_delta: float = RECALL_IMPORTANCE_BOOST,
    ) -> bool:
        """エピソードの重要度を更新（想起時）

        Args:
            conn: DB接続
            episode_id: エピソードID
            importance_delta: 重要度の増分

        Returns:
            更新成功したかどうか
        """
        return self._episode_repo.boost_importance(
            conn=conn,
            episode_id=episode_id,
            delta=importance_delta,
        )

    def decay_episodes(
        self,
        conn: Connection,
        decay_rate: float = DECAY_RATE_PER_DAY,
    ) -> int:
        """エピソードの重要度を減衰（バッチ処理用）

        Args:
            conn: DB接続
            decay_rate: 減衰率

        Returns:
            処理件数
        """
        return self._episode_repo.apply_decay(conn, decay_rate)

    def forget_episodes(
        self,
        conn: Connection,
        threshold: float = FORGET_THRESHOLD,
    ) -> int:
        """閾値以下のエピソードを削除（忘却）

        Args:
            conn: DB接続
            threshold: 忘却閾値

        Returns:
            削除件数
        """
        return self._episode_repo.forget_below_threshold(conn, threshold)

    # ========================================================================
    # 知識グラフ
    # ========================================================================

    def add_knowledge_node(
        self,
        conn: Connection,
        name: str,
        node_type: NodeType,
        description: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        aliases: Optional[List[str]] = None,
        source: KnowledgeSource = KnowledgeSource.LEARNED,
    ) -> str:
        """知識ノードを追加

        Args:
            conn: DB接続
            name: ノード名
            node_type: ノードタイプ
            description: 説明
            properties: プロパティ
            aliases: 別名リスト
            source: 知識のソース

        Returns:
            ノードID
        """
        node = KnowledgeNode(
            organization_id=self.organization_id,
            name=name,
            node_type=node_type,
            description=description,
            properties=properties or {},
            aliases=aliases or [],
            source=source,
        )
        return self._knowledge_graph.add_node(conn, node)

    def add_knowledge_edge(
        self,
        conn: Connection,
        source_node_id: str,
        target_node_id: str,
        relation_type: EdgeType,
        properties: Optional[Dict[str, Any]] = None,
        weight: float = EDGE_WEIGHT_DEFAULT,
        source: KnowledgeSource = KnowledgeSource.LEARNED,
    ) -> str:
        """知識エッジを追加

        Args:
            conn: DB接続
            source_node_id: ソースノードID
            target_node_id: ターゲットノードID
            relation_type: 関係タイプ
            properties: プロパティ
            weight: 重み
            source: 知識のソース

        Returns:
            エッジID
        """
        edge = KnowledgeEdge(
            organization_id=self.organization_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relation_type=relation_type,
            properties=properties or {},
            weight=weight,
            source=source,
        )
        return self._knowledge_graph.add_edge(conn, edge)

    def get_knowledge_node(
        self,
        conn: Connection,
        node_id: str,
    ) -> Optional[KnowledgeNode]:
        """知識ノードを取得

        Args:
            conn: DB接続
            node_id: ノードID

        Returns:
            ノード（見つからない場合はNone）
        """
        return self._knowledge_graph.get_node(conn, node_id)

    def find_knowledge_nodes_by_name(
        self,
        conn: Connection,
        name: str,
        fuzzy: bool = True,
    ) -> List[KnowledgeNode]:
        """名前で知識ノードを検索

        Args:
            conn: DB接続
            name: 検索名
            fuzzy: あいまい検索するか

        Returns:
            ノードリスト
        """
        return self._knowledge_graph.find_nodes_by_name(conn, name, fuzzy)

    def query_subgraph(
        self,
        conn: Connection,
        center_node_id: str,
        max_depth: int = 2,
        edge_types: Optional[List[EdgeType]] = None,
    ) -> KnowledgeSubgraph:
        """サブグラフを取得

        Args:
            conn: DB接続
            center_node_id: 中心ノードID
            max_depth: 最大深度
            edge_types: 取得するエッジタイプ（None=全て）

        Returns:
            サブグラフ
        """
        return self._knowledge_graph.get_subgraph(
            conn=conn,
            center_node_id=center_node_id,
            max_depth=max_depth,
            edge_types=edge_types,
        )

    def find_path(
        self,
        conn: Connection,
        source_node_id: str,
        target_node_id: str,
        max_depth: int = 5,
    ) -> Optional[List[KnowledgeEdge]]:
        """2つのノード間のパスを探索

        Args:
            conn: DB接続
            source_node_id: ソースノードID
            target_node_id: ターゲットノードID
            max_depth: 最大深度

        Returns:
            パス（エッジリスト）。見つからない場合はNone
        """
        return self._knowledge_graph.find_path(
            conn=conn,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            max_depth=max_depth,
        )

    def get_related_nodes(
        self,
        conn: Connection,
        node_id: str,
        edge_types: Optional[List[EdgeType]] = None,
        direction: str = "both",
    ) -> List[KnowledgeNode]:
        """関連ノードを取得

        Args:
            conn: DB接続
            node_id: ノードID
            edge_types: エッジタイプフィルタ
            direction: 方向（"outgoing", "incoming", "both"）

        Returns:
            関連ノードリスト
        """
        return self._knowledge_graph.get_related_nodes(
            conn=conn,
            node_id=node_id,
            edge_types=edge_types,
            direction=direction,
        )

    # ========================================================================
    # 便利メソッド
    # ========================================================================

    def record_achievement(
        self,
        conn: Connection,
        user_id: str,
        summary: str,
        details: Optional[Dict[str, Any]] = None,
        keywords: Optional[List[str]] = None,
        room_id: Optional[str] = None,
    ) -> str:
        """達成エピソードを記録（ショートカット）

        Args:
            conn: DB接続
            user_id: ユーザーID
            summary: 要約
            details: 詳細
            keywords: キーワード
            room_id: ルームID

        Returns:
            エピソードID
        """
        return self.record_episode(
            conn=conn,
            episode_type=EpisodeType.ACHIEVEMENT,
            summary=summary,
            details=details,
            user_id=user_id,
            room_id=room_id,
            keywords=keywords,
            importance=0.8,
            emotional_valence=0.7,
        )

    def record_failure(
        self,
        conn: Connection,
        user_id: str,
        summary: str,
        details: Optional[Dict[str, Any]] = None,
        keywords: Optional[List[str]] = None,
        room_id: Optional[str] = None,
    ) -> str:
        """失敗エピソードを記録（ショートカット）

        Args:
            conn: DB接続
            user_id: ユーザーID
            summary: 要約
            details: 詳細
            keywords: キーワード
            room_id: ルームID

        Returns:
            エピソードID
        """
        return self.record_episode(
            conn=conn,
            episode_type=EpisodeType.FAILURE,
            summary=summary,
            details=details,
            user_id=user_id,
            room_id=room_id,
            keywords=keywords,
            importance=0.7,
            emotional_valence=-0.5,
        )

    def record_decision(
        self,
        conn: Connection,
        user_id: str,
        summary: str,
        details: Optional[Dict[str, Any]] = None,
        keywords: Optional[List[str]] = None,
        room_id: Optional[str] = None,
    ) -> str:
        """判断・決定エピソードを記録（ショートカット）

        Args:
            conn: DB接続
            user_id: ユーザーID
            summary: 要約
            details: 詳細
            keywords: キーワード
            room_id: ルームID

        Returns:
            エピソードID
        """
        return self.record_episode(
            conn=conn,
            episode_type=EpisodeType.DECISION,
            summary=summary,
            details=details,
            user_id=user_id,
            room_id=room_id,
            keywords=keywords,
            importance=0.85,
            emotional_valence=0.0,
        )

    def record_learning(
        self,
        conn: Connection,
        summary: str,
        details: Optional[Dict[str, Any]] = None,
        keywords: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
    ) -> str:
        """学習エピソードを記録（ショートカット）

        Args:
            conn: DB接続
            summary: 要約
            details: 詳細
            keywords: キーワード
            user_id: ユーザーID（None=組織全体の学習）
            room_id: ルームID

        Returns:
            エピソードID
        """
        return self.record_episode(
            conn=conn,
            episode_type=EpisodeType.LEARNING,
            summary=summary,
            details=details,
            user_id=user_id,
            room_id=room_id,
            keywords=keywords,
            importance=0.75,
            emotional_valence=0.3,
        )

    # ========================================================================
    # 統計・分析
    # ========================================================================

    def get_episode_count(
        self,
        conn: Connection,
        user_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
    ) -> int:
        """エピソード数を取得

        Args:
            conn: DB接続
            user_id: ユーザーID（None=組織全体）
            episode_type: エピソードタイプフィルタ

        Returns:
            エピソード数
        """
        return self._episode_repo.count(
            conn=conn,
            user_id=user_id,
            episode_type=episode_type,
        )

    def get_knowledge_stats(
        self,
        conn: Connection,
    ) -> Dict[str, Any]:
        """知識グラフの統計を取得

        Args:
            conn: DB接続

        Returns:
            統計情報
        """
        return self._knowledge_graph.get_stats(conn)


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_memory_enhancement(organization_id: str) -> BrainMemoryEnhancement:
    """BrainMemoryEnhancementを生成

    Args:
        organization_id: 組織ID

    Returns:
        BrainMemoryEnhancementインスタンス
    """
    return BrainMemoryEnhancement(organization_id)


# ============================================================================
# エクスポート
# ============================================================================

__all__ = [
    # 統合クラス
    "BrainMemoryEnhancement",
    "create_memory_enhancement",
    # リポジトリ
    "EpisodeRepository",
    "KnowledgeGraph",
    # モデル
    "Episode",
    "RecallResult",
    "RelatedEntity",
    "KnowledgeNode",
    "KnowledgeEdge",
    "KnowledgeSubgraph",
    "TemporalEvent",
    "TemporalComparison",
    "ConsolidationResult",
    # Enums
    "EpisodeType",
    "RecallTrigger",
    "EntityType",
    "EntityRelationship",
    "NodeType",
    "EdgeType",
    "KnowledgeSource",
    "TemporalEventType",
    "TrendType",
    "ComparisonType",
    "ConsolidationType",
    "ConsolidationAction",
    # 定数
    "BASE_IMPORTANCE",
    "DECAY_RATE_PER_DAY",
    "FORGET_THRESHOLD",
    "MAX_RECALL_COUNT",
    "RECALL_RELEVANCE_THRESHOLD",
    "KNOWLEDGE_CONFIDENCE_DEFAULT",
    # テーブル
    "TABLE_BRAIN_EPISODES",
    "TABLE_BRAIN_EPISODE_ENTITIES",
    "TABLE_BRAIN_KNOWLEDGE_NODES",
    "TABLE_BRAIN_KNOWLEDGE_EDGES",
    "TABLE_BRAIN_TEMPORAL_EVENTS",
    "TABLE_BRAIN_TEMPORAL_COMPARISONS",
    "TABLE_BRAIN_MEMORY_CONSOLIDATIONS",
]
