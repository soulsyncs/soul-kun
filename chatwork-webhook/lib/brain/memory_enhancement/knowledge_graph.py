"""
Phase 2G: 記憶の強化（Memory Enhancement）- 知識グラフ

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2G

概念間の関係性を管理する知識グラフ。
「カズさん → CEO → ソウルシンクス」のような関係を追跡し、
文脈理解や推論に活用する。
"""

import json
import logging
import re
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .constants import (
    EDGE_EVIDENCE_THRESHOLD,
    EDGE_WEIGHT_DEFAULT,
    KNOWLEDGE_CONFIDENCE_DEFAULT,
    NODE_ACTIVATION_DECAY,
    TABLE_BRAIN_KNOWLEDGE_EDGES,
    TABLE_BRAIN_KNOWLEDGE_NODES,
    EdgeType,
    KnowledgeSource,
    NodeType,
)
from .models import KnowledgeEdge, KnowledgeNode, KnowledgeSubgraph


logger = logging.getLogger(__name__)


# ============================================================================
# 関係タイプの逆関係マッピング
# ============================================================================

INVERSE_RELATIONS: Dict[EdgeType, EdgeType] = {
    EdgeType.IS_A: EdgeType.HAS_A,
    EdgeType.PART_OF: EdgeType.HAS_A,
    EdgeType.BELONGS_TO: EdgeType.HAS_A,
    EdgeType.CAUSES: EdgeType.REQUIRES,
    EdgeType.BEFORE: EdgeType.AFTER,
    EdgeType.REPORTS_TO: EdgeType.SUPERVISES,
}


# ============================================================================
# 双方向関係タイプ
# ============================================================================

BIDIRECTIONAL_RELATIONS: Set[EdgeType] = {
    EdgeType.RELATED_TO,
    EdgeType.SIMILAR_TO,
    EdgeType.PEERS_WITH,
    EdgeType.WORKS_WITH,
    EdgeType.KNOWS,
}


class KnowledgeGraph:
    """知識グラフ管理クラス

    概念（ノード）と関係（エッジ）を管理し、
    知識ベースの構築と検索を提供する。

    使用例:
        graph = KnowledgeGraph(organization_id)

        # ノード追加
        node_id = graph.add_node(conn, node)

        # エッジ追加
        edge_id = graph.add_edge(conn, edge)

        # 関連ノード検索
        related = graph.find_related_nodes(conn, node_id)

        # パス検索
        path = graph.find_path(conn, from_id, to_id)
    """

    def __init__(self, organization_id: str):
        """初期化

        Args:
            organization_id: 組織ID
        """
        self.organization_id = organization_id

    # =========================================================================
    # ノード操作
    # =========================================================================

    def add_node(
        self,
        conn: Connection,
        node: KnowledgeNode,
    ) -> str:
        """ノードを追加

        Args:
            conn: DB接続
            node: 追加するノード

        Returns:
            ノードID
        """
        if node.id is None:
            node.id = str(uuid4())

        now = datetime.now()

        query = text(f"""
            INSERT INTO {TABLE_BRAIN_KNOWLEDGE_NODES} (
                id, organization_id,
                node_type, name, description, aliases,
                properties, importance_score, activation_level,
                source, evidence_count, created_at, updated_at
            ) VALUES (
                CAST(:id AS uuid),
                CAST(:organization_id AS uuid),
                :node_type, :name, :description, :aliases,
                CAST(:properties AS jsonb), :importance_score, :activation_level,
                :source, :evidence_count, :created_at, :updated_at
            )
            ON CONFLICT (organization_id, node_type, name) DO UPDATE SET
                description = COALESCE(EXCLUDED.description, {TABLE_BRAIN_KNOWLEDGE_NODES}.description),
                aliases = array_cat({TABLE_BRAIN_KNOWLEDGE_NODES}.aliases, EXCLUDED.aliases),
                properties = {TABLE_BRAIN_KNOWLEDGE_NODES}.properties || EXCLUDED.properties,
                activation_level = GREATEST({TABLE_BRAIN_KNOWLEDGE_NODES}.activation_level, EXCLUDED.activation_level),
                evidence_count = {TABLE_BRAIN_KNOWLEDGE_NODES}.evidence_count + 1,
                updated_at = EXCLUDED.updated_at
            RETURNING id
        """)

        try:
            result = conn.execute(query, {
                "id": node.id,
                "organization_id": self.organization_id,
                "node_type": node.node_type.value if isinstance(node.node_type, NodeType) else node.node_type,
                "name": node.name,
                "description": node.description,
                "aliases": node.aliases,
                "properties": json.dumps(node.properties, ensure_ascii=False, default=str),
                "importance_score": node.importance_score,
                "activation_level": node.activation_level,
                "source": node.source.value if isinstance(node.source, KnowledgeSource) else node.source,
                "evidence_count": node.evidence_count,
                "created_at": node.created_at or now,
                "updated_at": now,
            })
            row = result.fetchone()
            node_id = str(row[0]) if row else node.id

            logger.info(f"Knowledge node added/updated: {node.name} ({node_id})")
            return node_id

        except Exception as e:
            logger.error(f"Failed to add knowledge node: {e}")
            raise

    def find_node_by_id(
        self,
        conn: Connection,
        node_id: str,
    ) -> Optional[KnowledgeNode]:
        """IDでノードを取得

        Args:
            conn: DB接続
            node_id: ノードID

        Returns:
            ノード（見つからない場合はNone）
        """
        query = text(f"""
            SELECT
                id, organization_id,
                node_type, name, description, aliases,
                properties, importance_score, activation_level,
                source, evidence_count, created_at, updated_at
            FROM {TABLE_BRAIN_KNOWLEDGE_NODES}
            WHERE id = CAST(:node_id AS uuid)
              AND organization_id = CAST(:organization_id AS uuid)
        """)

        try:
            result = conn.execute(query, {
                "node_id": node_id,
                "organization_id": self.organization_id,
            })
            row = result.fetchone()
            if row:
                return self._row_to_node(row)
            return None
        except Exception as e:
            logger.error(f"Failed to find node by id: {e}")
            return None

    def find_node_by_name(
        self,
        conn: Connection,
        name: str,
        node_type: Optional[NodeType] = None,
        include_aliases: bool = True,
    ) -> Optional[KnowledgeNode]:
        """名前でノードを検索

        Args:
            conn: DB接続
            name: 検索名
            node_type: ノードタイプ（指定時はフィルタ）
            include_aliases: 別名も検索するか

        Returns:
            ノード（見つからない場合はNone）
        """
        type_clause = ""
        if node_type:
            type_clause = "AND node_type = :node_type"

        alias_clause = ""
        if include_aliases:
            alias_clause = "OR :name = ANY(aliases)"

        query = text(f"""
            SELECT
                id, organization_id,
                node_type, name, description, aliases,
                properties, importance_score, activation_level,
                source, evidence_count, created_at, updated_at
            FROM {TABLE_BRAIN_KNOWLEDGE_NODES}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND (LOWER(name) = LOWER(:name) {alias_clause})
              {type_clause}
            ORDER BY importance_score DESC
            LIMIT 1
        """)

        try:
            params = {
                "organization_id": self.organization_id,
                "name": name,
            }
            if node_type:
                params["node_type"] = node_type.value if isinstance(node_type, NodeType) else node_type

            result = conn.execute(query, params)
            row = result.fetchone()
            if row:
                return self._row_to_node(row)
            return None
        except Exception as e:
            logger.error(f"Failed to find node by name: {e}")
            return None

    def search_nodes(
        self,
        conn: Connection,
        query_text: str,
        node_type: Optional[NodeType] = None,
        limit: int = 20,
    ) -> List[KnowledgeNode]:
        """ノードを検索

        Args:
            conn: DB接続
            query_text: 検索テキスト
            node_type: ノードタイプ
            limit: 最大件数

        Returns:
            ノードリスト
        """
        type_clause = ""
        if node_type:
            type_clause = "AND node_type = :node_type"

        query = text(f"""
            SELECT
                id, organization_id,
                node_type, name, description, aliases,
                properties, importance_score, activation_level,
                source, evidence_count, created_at, updated_at
            FROM {TABLE_BRAIN_KNOWLEDGE_NODES}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND (
                name ILIKE :pattern
                OR description ILIKE :pattern
                OR :query_text = ANY(aliases)
              )
              {type_clause}
            ORDER BY importance_score DESC, activation_level DESC
            LIMIT :limit
        """)

        try:
            params = {
                "organization_id": self.organization_id,
                "query_text": query_text,
                "pattern": f"%{query_text}%",
                "limit": limit,
            }
            if node_type:
                params["node_type"] = node_type.value if isinstance(node_type, NodeType) else node_type

            result = conn.execute(query, params)
            return [self._row_to_node(row) for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Failed to search nodes: {e}")
            return []

    def update_node_activation(
        self,
        conn: Connection,
        node_id: str,
        boost: float = 0.1,
    ) -> bool:
        """ノードの活性度を更新

        Args:
            conn: DB接続
            node_id: ノードID
            boost: 活性度の増加量

        Returns:
            成功したか
        """
        query = text(f"""
            UPDATE {TABLE_BRAIN_KNOWLEDGE_NODES}
            SET activation_level = LEAST(1.0, activation_level + :boost),
                updated_at = :now
            WHERE id = CAST(:node_id AS uuid)
              AND organization_id = CAST(:organization_id AS uuid)
        """)

        try:
            result = conn.execute(query, {
                "node_id": node_id,
                "organization_id": self.organization_id,
                "boost": boost,
                "now": datetime.now(),
            })
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to update node activation: {e}")
            return False

    def apply_activation_decay(
        self,
        conn: Connection,
    ) -> int:
        """活性度の減衰を適用

        Args:
            conn: DB接続

        Returns:
            更新件数
        """
        query = text(f"""
            UPDATE {TABLE_BRAIN_KNOWLEDGE_NODES}
            SET activation_level = GREATEST(0.1, activation_level - :decay),
                updated_at = :now
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND activation_level > 0.1
        """)

        try:
            result = conn.execute(query, {
                "organization_id": self.organization_id,
                "decay": NODE_ACTIVATION_DECAY,
                "now": datetime.now(),
            })
            return result.rowcount
        except Exception as e:
            logger.error(f"Failed to apply activation decay: {e}")
            return 0

    # =========================================================================
    # エッジ操作
    # =========================================================================

    def add_edge(
        self,
        conn: Connection,
        edge: KnowledgeEdge,
    ) -> str:
        """エッジを追加

        Args:
            conn: DB接続
            edge: 追加するエッジ

        Returns:
            エッジID
        """
        if edge.id is None:
            edge.id = str(uuid4())

        now = datetime.now()

        # 双方向性の自動判定
        if edge.relation_type in BIDIRECTIONAL_RELATIONS:
            edge.is_bidirectional = True

        query = text(f"""
            INSERT INTO {TABLE_BRAIN_KNOWLEDGE_EDGES} (
                id, organization_id,
                source_node_id, target_node_id, relation_type,
                weight, confidence, properties, is_bidirectional,
                evidence_count, source, created_at, updated_at
            ) VALUES (
                CAST(:id AS uuid),
                CAST(:organization_id AS uuid),
                CAST(:source_node_id AS uuid),
                CAST(:target_node_id AS uuid),
                :relation_type,
                :weight, :confidence, CAST(:properties AS jsonb), :is_bidirectional,
                :evidence_count, :source, :created_at, :updated_at
            )
            ON CONFLICT (organization_id, source_node_id, target_node_id, relation_type) DO UPDATE SET
                weight = ({TABLE_BRAIN_KNOWLEDGE_EDGES}.weight + EXCLUDED.weight) / 2,
                confidence = GREATEST({TABLE_BRAIN_KNOWLEDGE_EDGES}.confidence, EXCLUDED.confidence),
                properties = {TABLE_BRAIN_KNOWLEDGE_EDGES}.properties || EXCLUDED.properties,
                evidence_count = {TABLE_BRAIN_KNOWLEDGE_EDGES}.evidence_count + 1,
                updated_at = EXCLUDED.updated_at
            RETURNING id
        """)

        try:
            result = conn.execute(query, {
                "id": edge.id,
                "organization_id": self.organization_id,
                "source_node_id": edge.source_node_id,
                "target_node_id": edge.target_node_id,
                "relation_type": edge.relation_type.value if isinstance(edge.relation_type, EdgeType) else edge.relation_type,
                "weight": edge.weight,
                "confidence": edge.confidence,
                "properties": json.dumps(edge.properties, ensure_ascii=False, default=str),
                "is_bidirectional": edge.is_bidirectional,
                "evidence_count": edge.evidence_count,
                "source": edge.source.value if isinstance(edge.source, KnowledgeSource) else edge.source,
                "created_at": edge.created_at or now,
                "updated_at": now,
            })
            row = result.fetchone()
            edge_id = str(row[0]) if row else edge.id

            logger.debug(f"Knowledge edge added/updated: {edge.source_node_id} --{edge.relation_type}--> {edge.target_node_id}")
            return edge_id

        except Exception as e:
            logger.error(f"Failed to add knowledge edge: {e}")
            raise

    def find_edges_from(
        self,
        conn: Connection,
        node_id: str,
        relation_type: Optional[EdgeType] = None,
    ) -> List[KnowledgeEdge]:
        """ノードから出るエッジを取得

        Args:
            conn: DB接続
            node_id: ノードID
            relation_type: 関係タイプ（指定時はフィルタ）

        Returns:
            エッジリスト
        """
        type_clause = ""
        if relation_type:
            type_clause = "AND relation_type = :relation_type"

        query = text(f"""
            SELECT
                id, organization_id,
                source_node_id, target_node_id, relation_type,
                weight, confidence, properties, is_bidirectional,
                evidence_count, source, created_at, updated_at
            FROM {TABLE_BRAIN_KNOWLEDGE_EDGES}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND (source_node_id = CAST(:node_id AS uuid)
                   OR (is_bidirectional AND target_node_id = CAST(:node_id AS uuid)))
              {type_clause}
            ORDER BY weight DESC, confidence DESC
        """)

        try:
            params = {
                "organization_id": self.organization_id,
                "node_id": node_id,
            }
            if relation_type:
                params["relation_type"] = relation_type.value if isinstance(relation_type, EdgeType) else relation_type

            result = conn.execute(query, params)
            return [self._row_to_edge(row) for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Failed to find edges from node: {e}")
            return []

    def find_edges_to(
        self,
        conn: Connection,
        node_id: str,
        relation_type: Optional[EdgeType] = None,
    ) -> List[KnowledgeEdge]:
        """ノードに入るエッジを取得

        Args:
            conn: DB接続
            node_id: ノードID
            relation_type: 関係タイプ

        Returns:
            エッジリスト
        """
        type_clause = ""
        if relation_type:
            type_clause = "AND relation_type = :relation_type"

        query = text(f"""
            SELECT
                id, organization_id,
                source_node_id, target_node_id, relation_type,
                weight, confidence, properties, is_bidirectional,
                evidence_count, source, created_at, updated_at
            FROM {TABLE_BRAIN_KNOWLEDGE_EDGES}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND (target_node_id = CAST(:node_id AS uuid)
                   OR (is_bidirectional AND source_node_id = CAST(:node_id AS uuid)))
              {type_clause}
            ORDER BY weight DESC, confidence DESC
        """)

        try:
            params = {
                "organization_id": self.organization_id,
                "node_id": node_id,
            }
            if relation_type:
                params["relation_type"] = relation_type.value if isinstance(relation_type, EdgeType) else relation_type

            result = conn.execute(query, params)
            return [self._row_to_edge(row) for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Failed to find edges to node: {e}")
            return []

    # =========================================================================
    # グラフ探索
    # =========================================================================

    def find_related_nodes(
        self,
        conn: Connection,
        node_id: str,
        relation_types: Optional[List[EdgeType]] = None,
        depth: int = 1,
        limit: int = 20,
    ) -> List[Tuple[KnowledgeNode, KnowledgeEdge]]:
        """関連ノードを検索

        Args:
            conn: DB接続
            node_id: 中心ノードID
            relation_types: 関係タイプ（指定時はフィルタ）
            depth: 探索深度
            limit: 最大件数

        Returns:
            (ノード, エッジ)のリスト
        """
        results: List[Tuple[KnowledgeNode, KnowledgeEdge]] = []
        visited = {node_id}

        # BFS
        queue = deque([(node_id, 0)])
        while queue and len(results) < limit:
            current_id, current_depth = queue.popleft()
            if current_depth >= depth:
                continue

            # 出るエッジを取得
            edges = self.find_edges_from(conn, current_id)
            for edge in edges:
                target_id = edge.target_node_id
                if target_id == current_id:
                    target_id = edge.source_node_id  # 双方向の場合

                if target_id in visited:
                    continue

                if relation_types and edge.relation_type not in relation_types:
                    continue

                visited.add(target_id)
                target_node = self.find_node_by_id(conn, target_id)
                if target_node:
                    results.append((target_node, edge))
                    queue.append((target_id, current_depth + 1))

        return results

    def find_path(
        self,
        conn: Connection,
        from_node_id: str,
        to_node_id: str,
        max_depth: int = 5,
    ) -> Optional[List[Tuple[KnowledgeNode, Optional[KnowledgeEdge]]]]:
        """2ノード間のパスを検索

        Args:
            conn: DB接続
            from_node_id: 開始ノードID
            to_node_id: 終了ノードID
            max_depth: 最大探索深度

        Returns:
            パス（ノード, エッジ）のリスト、見つからない場合はNone
        """
        if from_node_id == to_node_id:
            node = self.find_node_by_id(conn, from_node_id)
            return [(node, None)] if node else None

        # BFS
        visited = {from_node_id}
        initial_path: List[Tuple[str, Optional[KnowledgeEdge]]] = [(from_node_id, None)]
        queue: deque[Tuple[str, List[Tuple[str, Optional[KnowledgeEdge]]]]] = deque([(from_node_id, initial_path)])

        while queue:
            current_id, path = queue.popleft()
            if len(path) > max_depth:
                continue

            edges = self.find_edges_from(conn, current_id)
            for edge in edges:
                target_id = edge.target_node_id
                if target_id == current_id:
                    target_id = edge.source_node_id

                if target_id == to_node_id:
                    # パス発見
                    result_path: List[Tuple[KnowledgeNode, Optional[KnowledgeEdge]]] = []
                    for node_id, edge_in_path in path:
                        node = self.find_node_by_id(conn, node_id)
                        if node:
                            result_path.append((node, edge_in_path))
                    target_node = self.find_node_by_id(conn, target_id)
                    if target_node:
                        result_path.append((target_node, edge))
                    return result_path

                if target_id not in visited:
                    visited.add(target_id)
                    new_path = path + [(target_id, edge)]
                    queue.append((target_id, new_path))

        return None

    def get_subgraph(
        self,
        conn: Connection,
        center_node_id: str,
        depth: int = 2,
        max_nodes: int = 50,
    ) -> KnowledgeSubgraph:
        """部分グラフを取得

        Args:
            conn: DB接続
            center_node_id: 中心ノードID
            depth: 探索深度
            max_nodes: 最大ノード数

        Returns:
            サブグラフ
        """
        center_node = self.find_node_by_id(conn, center_node_id)
        if not center_node:
            raise ValueError(f"Center node not found: {center_node_id}")

        nodes: List[KnowledgeNode] = []
        edges: List[KnowledgeEdge] = []
        visited_nodes = {center_node_id}
        visited_edges = set()

        # BFS
        queue = deque([(center_node_id, 0)])
        while queue and len(nodes) < max_nodes:
            current_id, current_depth = queue.popleft()
            if current_depth >= depth:
                continue

            node_edges = self.find_edges_from(conn, current_id)
            for edge in node_edges:
                if edge.id in visited_edges:
                    continue
                visited_edges.add(edge.id)
                edges.append(edge)

                target_id = edge.target_node_id
                if target_id == current_id:
                    target_id = edge.source_node_id

                if target_id not in visited_nodes:
                    visited_nodes.add(target_id)
                    target_node = self.find_node_by_id(conn, target_id)
                    if target_node:
                        nodes.append(target_node)
                        queue.append((target_id, current_depth + 1))

        return KnowledgeSubgraph(
            center_node=center_node,
            nodes=nodes,
            edges=edges,
            depth=depth,
        )

    # =========================================================================
    # 知識抽出
    # =========================================================================

    def extract_entities_from_text(
        self,
        text: str,
    ) -> List[Dict[str, Any]]:
        """テキストからエンティティを抽出

        Args:
            text: テキスト

        Returns:
            エンティティリスト
        """
        entities = []

        # 人名パターン（「〜さん」「〜くん」など）
        person_pattern = r"([ぁ-んァ-ン一-龥]+)(さん|くん|様|氏)"
        for match in re.finditer(person_pattern, text):
            entities.append({
                "name": match.group(0),
                "base_name": match.group(1),
                "node_type": NodeType.PERSON.value,
            })

        # 組織・部署パターン
        org_pattern = r"([ぁ-んァ-ン一-龥]+)(部|課|チーム|グループ)"
        for match in re.finditer(org_pattern, text):
            entities.append({
                "name": match.group(0),
                "node_type": NodeType.ORGANIZATION.value,
            })

        # プロジェクトパターン
        project_pattern = r"([ぁ-んァ-ン一-龥a-zA-Z0-9]+)(プロジェクト|PJ|案件)"
        for match in re.finditer(project_pattern, text):
            entities.append({
                "name": match.group(0),
                "node_type": NodeType.PROJECT.value,
            })

        return entities

    def extract_relations_from_text(
        self,
        text: str,
        entities: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """テキストから関係を抽出

        Args:
            text: テキスト
            entities: 抽出されたエンティティ

        Returns:
            関係リスト
        """
        relations = []

        # 所属関係パターン
        belongs_patterns = [
            (r"(.+)は(.+)に所属", EdgeType.BELONGS_TO),
            (r"(.+)は(.+)のメンバー", EdgeType.BELONGS_TO),
            (r"(.+)は(.+)の", EdgeType.BELONGS_TO),
        ]

        # 責任関係パターン
        responsible_patterns = [
            (r"(.+)が(.+)を担当", EdgeType.RESPONSIBLE_FOR),
            (r"(.+)は(.+)の責任者", EdgeType.RESPONSIBLE_FOR),
        ]

        # 報告関係パターン
        reports_patterns = [
            (r"(.+)は(.+)に報告", EdgeType.REPORTS_TO),
            (r"(.+)の上司は(.+)", EdgeType.REPORTS_TO),
        ]

        all_patterns = belongs_patterns + responsible_patterns + reports_patterns
        for pattern, relation_type in all_patterns:
            for match in re.finditer(pattern, text):
                relations.append({
                    "source": match.group(1).strip(),
                    "target": match.group(2).strip(),
                    "relation_type": relation_type.value,
                })

        return relations

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def _row_to_node(self, row) -> KnowledgeNode:
        """DBの行をKnowledgeNodeに変換"""
        return KnowledgeNode(
            id=str(row[0]),
            organization_id=str(row[1]) if row[1] else None,
            node_type=NodeType(row[2]) if row[2] else NodeType.CONCEPT,
            name=row[3] or "",
            description=row[4],
            aliases=list(row[5]) if row[5] else [],
            properties=row[6] if isinstance(row[6], dict) else {},
            importance_score=float(row[7]) if row[7] else 0.5,
            activation_level=float(row[8]) if row[8] else 0.5,
            source=KnowledgeSource(row[9]) if row[9] else KnowledgeSource.SYSTEM,
            evidence_count=row[10] or 1,
            created_at=row[11],
            updated_at=row[12],
        )

    def _row_to_edge(self, row) -> KnowledgeEdge:
        """DBの行をKnowledgeEdgeに変換"""
        return KnowledgeEdge(
            id=str(row[0]),
            organization_id=str(row[1]) if row[1] else None,
            source_node_id=str(row[2]),
            target_node_id=str(row[3]),
            relation_type=EdgeType(row[4]) if row[4] else EdgeType.RELATED_TO,
            weight=float(row[5]) if row[5] else EDGE_WEIGHT_DEFAULT,
            confidence=float(row[6]) if row[6] else KNOWLEDGE_CONFIDENCE_DEFAULT,
            properties=row[7] if isinstance(row[7], dict) else {},
            is_bidirectional=row[8] or False,
            evidence_count=row[9] or 1,
            source=KnowledgeSource(row[10]) if row[10] else KnowledgeSource.SYSTEM,
            created_at=row[11],
            updated_at=row[12],
        )

    # =========================================================================
    # 統計
    # =========================================================================

    def get_statistics(
        self,
        conn: Connection,
    ) -> Dict[str, Any]:
        """統計を取得

        Args:
            conn: DB接続

        Returns:
            統計情報
        """
        # ノード統計
        node_query = text(f"""
            SELECT node_type, COUNT(*) AS count
            FROM {TABLE_BRAIN_KNOWLEDGE_NODES}
            WHERE organization_id = CAST(:organization_id AS uuid)
            GROUP BY node_type
        """)

        # エッジ統計
        edge_query = text(f"""
            SELECT relation_type, COUNT(*) AS count
            FROM {TABLE_BRAIN_KNOWLEDGE_EDGES}
            WHERE organization_id = CAST(:organization_id AS uuid)
            GROUP BY relation_type
        """)

        try:
            node_result = conn.execute(node_query, {"organization_id": self.organization_id})
            nodes_by_type = {row[0]: row[1] for row in node_result.fetchall()}

            edge_result = conn.execute(edge_query, {"organization_id": self.organization_id})
            edges_by_type = {row[0]: row[1] for row in edge_result.fetchall()}

            return {
                "total_nodes": sum(nodes_by_type.values()),
                "nodes_by_type": nodes_by_type,
                "total_edges": sum(edges_by_type.values()),
                "edges_by_type": edges_by_type,
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {
                "total_nodes": 0,
                "nodes_by_type": {},
                "total_edges": 0,
                "edges_by_type": {},
            }


def create_knowledge_graph(organization_id: str) -> KnowledgeGraph:
    """KnowledgeGraphのファクトリ関数

    Args:
        organization_id: 組織ID

    Returns:
        KnowledgeGraph
    """
    return KnowledgeGraph(organization_id)
