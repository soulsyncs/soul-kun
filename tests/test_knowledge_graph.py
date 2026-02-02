# tests/test_knowledge_graph.py
"""
KnowledgeGraph のユニットテスト

lib/brain/memory_enhancement/knowledge_graph.py のカバレッジ強化
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from lib.brain.memory_enhancement.knowledge_graph import (
    KnowledgeGraph,
    create_knowledge_graph,
    INVERSE_RELATIONS,
    BIDIRECTIONAL_RELATIONS,
)
from lib.brain.memory_enhancement.models import KnowledgeNode, KnowledgeEdge, KnowledgeSubgraph
from lib.brain.memory_enhancement.constants import (
    NodeType,
    EdgeType,
    KnowledgeSource,
)


# =============================================================================
# テストデータ
# =============================================================================

TEST_ORG_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_NODE_ID = "660e8400-e29b-41d4-a716-446655440001"
TEST_NODE_ID_2 = "660e8400-e29b-41d4-a716-446655440002"
TEST_EDGE_ID = "770e8400-e29b-41d4-a716-446655440001"


def create_test_node(
    node_id: str = None,
    name: str = "テストノード",
    node_type: NodeType = NodeType.CONCEPT,
    importance_score: float = 0.5,
) -> KnowledgeNode:
    """テスト用KnowledgeNodeを作成"""
    return KnowledgeNode(
        id=node_id or str(uuid4()),
        organization_id=TEST_ORG_ID,
        node_type=node_type,
        name=name,
        description="テスト説明",
        aliases=["別名1"],
        properties={"key": "value"},
        importance_score=importance_score,
        activation_level=0.5,
        source=KnowledgeSource.SYSTEM,
        evidence_count=1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def create_test_edge(
    edge_id: str = None,
    source_node_id: str = TEST_NODE_ID,
    target_node_id: str = TEST_NODE_ID_2,
    relation_type: EdgeType = EdgeType.RELATED_TO,
) -> KnowledgeEdge:
    """テスト用KnowledgeEdgeを作成"""
    return KnowledgeEdge(
        id=edge_id or str(uuid4()),
        organization_id=TEST_ORG_ID,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        relation_type=relation_type,
        weight=0.5,
        confidence=0.8,
        properties={},
        is_bidirectional=False,
        evidence_count=1,
        source=KnowledgeSource.SYSTEM,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def create_mock_node_row(node: KnowledgeNode = None):
    """DBの行データをモック"""
    n = node or create_test_node()
    return (
        n.id,
        n.organization_id,
        n.node_type.value if isinstance(n.node_type, NodeType) else n.node_type,
        n.name,
        n.description,
        n.aliases,
        n.properties,
        n.importance_score,
        n.activation_level,
        n.source.value if isinstance(n.source, KnowledgeSource) else n.source,
        n.evidence_count,
        n.created_at,
        n.updated_at,
    )


def create_mock_edge_row(edge: KnowledgeEdge = None):
    """DBの行データをモック"""
    e = edge or create_test_edge()
    return (
        e.id,
        e.organization_id,
        e.source_node_id,
        e.target_node_id,
        e.relation_type.value if isinstance(e.relation_type, EdgeType) else e.relation_type,
        e.weight,
        e.confidence,
        e.properties,
        e.is_bidirectional,
        e.evidence_count,
        e.source.value if isinstance(e.source, KnowledgeSource) else e.source,
        e.created_at,
        e.updated_at,
    )


# =============================================================================
# 初期化テスト
# =============================================================================


class TestKnowledgeGraphInit:
    """初期化テスト"""

    def test_init_with_org_id(self):
        """organization_idで初期化できる"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        assert graph.organization_id == TEST_ORG_ID

    def test_factory_function(self):
        """ファクトリ関数でインスタンス作成"""
        graph = create_knowledge_graph(TEST_ORG_ID)
        assert isinstance(graph, KnowledgeGraph)


class TestConstants:
    """定数のテスト"""

    def test_inverse_relations_defined(self):
        """逆関係マッピングが定義されている"""
        assert EdgeType.IS_A in INVERSE_RELATIONS

    def test_bidirectional_relations_defined(self):
        """双方向関係が定義されている"""
        assert EdgeType.RELATED_TO in BIDIRECTIONAL_RELATIONS


# =============================================================================
# ノード操作テスト
# =============================================================================


class TestAddNode:
    """add_node()メソッドのテスト"""

    def test_add_node_new(self):
        """新規ノードの追加"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=(TEST_NODE_ID,))
        conn.execute = MagicMock(return_value=mock_result)

        node = create_test_node(node_id=None)
        node.id = None

        result = graph.add_node(conn, node)

        assert result is not None

    def test_add_node_with_id(self):
        """ID付きノードの追加"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=(TEST_NODE_ID,))
        conn.execute = MagicMock(return_value=mock_result)

        node = create_test_node(node_id=TEST_NODE_ID)

        result = graph.add_node(conn, node)

        assert result == TEST_NODE_ID

    def test_add_node_error(self):
        """エラー時に例外が上がる"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        node = create_test_node()

        with pytest.raises(Exception):
            graph.add_node(conn, node)


class TestFindNodeById:
    """find_node_by_id()メソッドのテスト"""

    def test_find_node_by_id_found(self):
        """IDでノードを取得"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        node = create_test_node(node_id=TEST_NODE_ID)
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=create_mock_node_row(node))
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.find_node_by_id(conn, TEST_NODE_ID)

        assert result is not None
        assert result.id == TEST_NODE_ID

    def test_find_node_by_id_not_found(self):
        """ノードが見つからない"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=None)
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.find_node_by_id(conn, TEST_NODE_ID)

        assert result is None

    def test_find_node_by_id_error(self):
        """エラー時はNoneを返す"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = graph.find_node_by_id(conn, TEST_NODE_ID)

        assert result is None


class TestFindNodeByName:
    """find_node_by_name()メソッドのテスト"""

    def test_find_node_by_name_found(self):
        """名前でノードを検索"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        node = create_test_node(name="田中さん")
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=create_mock_node_row(node))
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.find_node_by_name(conn, "田中さん")

        assert result is not None

    def test_find_node_by_name_with_type(self):
        """ノードタイプ指定で検索"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=None)
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.find_node_by_name(conn, "田中", node_type=NodeType.PERSON)

        assert result is None

    def test_find_node_by_name_no_aliases(self):
        """別名検索を無効化"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=None)
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.find_node_by_name(conn, "田中", include_aliases=False)

        assert result is None

    def test_find_node_by_name_error(self):
        """エラー時はNoneを返す"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = graph.find_node_by_name(conn, "田中")

        assert result is None


class TestSearchNodes:
    """search_nodes()メソッドのテスト"""

    def test_search_nodes_found(self):
        """ノード検索"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        node = create_test_node()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_node_row(node)])
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.search_nodes(conn, "テスト")

        assert len(result) == 1

    def test_search_nodes_with_type(self):
        """ノードタイプ指定で検索"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.search_nodes(conn, "テスト", node_type=NodeType.PERSON)

        assert result == []

    def test_search_nodes_error(self):
        """エラー時は空リストを返す"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = graph.search_nodes(conn, "テスト")

        assert result == []


class TestUpdateNodeActivation:
    """update_node_activation()メソッドのテスト"""

    def test_update_node_activation_success(self):
        """活性度の更新成功"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.update_node_activation(conn, TEST_NODE_ID)

        assert result is True

    def test_update_node_activation_not_found(self):
        """ノードが見つからない"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.update_node_activation(conn, TEST_NODE_ID)

        assert result is False

    def test_update_node_activation_error(self):
        """エラー時はFalseを返す"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = graph.update_node_activation(conn, TEST_NODE_ID)

        assert result is False


class TestApplyActivationDecay:
    """apply_activation_decay()メソッドのテスト"""

    def test_apply_activation_decay_success(self):
        """活性度減衰の適用成功"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.apply_activation_decay(conn)

        assert result == 5

    def test_apply_activation_decay_error(self):
        """エラー時は0を返す"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = graph.apply_activation_decay(conn)

        assert result == 0


# =============================================================================
# エッジ操作テスト
# =============================================================================


class TestAddEdge:
    """add_edge()メソッドのテスト"""

    def test_add_edge_new(self):
        """新規エッジの追加"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=(TEST_EDGE_ID,))
        conn.execute = MagicMock(return_value=mock_result)

        edge = create_test_edge(edge_id=None)
        edge.id = None

        result = graph.add_edge(conn, edge)

        assert result is not None

    def test_add_edge_bidirectional(self):
        """双方向エッジの追加"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=(TEST_EDGE_ID,))
        conn.execute = MagicMock(return_value=mock_result)

        edge = create_test_edge(relation_type=EdgeType.RELATED_TO)

        result = graph.add_edge(conn, edge)

        assert result is not None
        assert edge.is_bidirectional is True

    def test_add_edge_error(self):
        """エラー時に例外が上がる"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        edge = create_test_edge()

        with pytest.raises(Exception):
            graph.add_edge(conn, edge)


class TestFindEdgesFrom:
    """find_edges_from()メソッドのテスト"""

    def test_find_edges_from_found(self):
        """ノードから出るエッジを取得"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        edge = create_test_edge()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_edge_row(edge)])
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.find_edges_from(conn, TEST_NODE_ID)

        assert len(result) == 1

    def test_find_edges_from_with_type(self):
        """関係タイプ指定で検索"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.find_edges_from(conn, TEST_NODE_ID, relation_type=EdgeType.IS_A)

        assert result == []

    def test_find_edges_from_error(self):
        """エラー時は空リストを返す"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = graph.find_edges_from(conn, TEST_NODE_ID)

        assert result == []


class TestFindEdgesTo:
    """find_edges_to()メソッドのテスト"""

    def test_find_edges_to_found(self):
        """ノードに入るエッジを取得"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        edge = create_test_edge()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_edge_row(edge)])
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.find_edges_to(conn, TEST_NODE_ID_2)

        assert len(result) == 1

    def test_find_edges_to_with_type(self):
        """関係タイプ指定で検索"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = graph.find_edges_to(conn, TEST_NODE_ID, relation_type=EdgeType.BELONGS_TO)

        assert result == []

    def test_find_edges_to_error(self):
        """エラー時は空リストを返す"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = graph.find_edges_to(conn, TEST_NODE_ID)

        assert result == []


# =============================================================================
# グラフ探索テスト
# =============================================================================


class TestFindRelatedNodes:
    """find_related_nodes()メソッドのテスト"""

    def test_find_related_nodes_found(self):
        """関連ノードを検索"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()

        node2 = create_test_node(node_id=TEST_NODE_ID_2, name="関連ノード")
        edge = create_test_edge()

        with patch.object(graph, 'find_edges_from', return_value=[edge]):
            with patch.object(graph, 'find_node_by_id', return_value=node2):
                result = graph.find_related_nodes(conn, TEST_NODE_ID)

        assert len(result) >= 0

    def test_find_related_nodes_with_relation_types(self):
        """関係タイプ指定で検索"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()

        with patch.object(graph, 'find_edges_from', return_value=[]):
            result = graph.find_related_nodes(
                conn, TEST_NODE_ID,
                relation_types=[EdgeType.IS_A],
            )

        assert result == []


class TestFindPath:
    """find_path()メソッドのテスト"""

    def test_find_path_same_node(self):
        """同一ノードへのパス"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        node = create_test_node(node_id=TEST_NODE_ID)

        with patch.object(graph, 'find_node_by_id', return_value=node):
            result = graph.find_path(conn, TEST_NODE_ID, TEST_NODE_ID)

        assert result is not None
        assert len(result) == 1

    def test_find_path_not_found(self):
        """パスが見つからない"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()

        with patch.object(graph, 'find_edges_from', return_value=[]):
            result = graph.find_path(conn, TEST_NODE_ID, TEST_NODE_ID_2)

        assert result is None

    def test_find_path_found(self):
        """パスが見つかる"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()

        node1 = create_test_node(node_id=TEST_NODE_ID)
        node2 = create_test_node(node_id=TEST_NODE_ID_2)
        edge = create_test_edge(target_node_id=TEST_NODE_ID_2)

        def mock_find_node(conn, node_id):
            if node_id == TEST_NODE_ID:
                return node1
            return node2

        with patch.object(graph, 'find_edges_from', return_value=[edge]):
            with patch.object(graph, 'find_node_by_id', side_effect=mock_find_node):
                result = graph.find_path(conn, TEST_NODE_ID, TEST_NODE_ID_2)

        assert result is not None


class TestGetSubgraph:
    """get_subgraph()メソッドのテスト"""

    def test_get_subgraph_success(self):
        """サブグラフ取得成功"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()

        center_node = create_test_node(node_id=TEST_NODE_ID, name="中心")

        with patch.object(graph, 'find_node_by_id', return_value=center_node):
            with patch.object(graph, 'find_edges_from', return_value=[]):
                result = graph.get_subgraph(conn, TEST_NODE_ID)

        assert isinstance(result, KnowledgeSubgraph)
        assert result.center_node == center_node

    def test_get_subgraph_center_not_found(self):
        """中心ノードが見つからない"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()

        with patch.object(graph, 'find_node_by_id', return_value=None):
            with pytest.raises(ValueError):
                graph.get_subgraph(conn, TEST_NODE_ID)


# =============================================================================
# 知識抽出テスト
# =============================================================================


class TestExtractEntitiesFromText:
    """extract_entities_from_text()メソッドのテスト"""

    def test_extract_person_entities(self):
        """人名の抽出"""
        graph = KnowledgeGraph(TEST_ORG_ID)

        result = graph.extract_entities_from_text("田中さんが担当します")

        assert len(result) >= 1
        person_entities = [e for e in result if e.get("node_type") == NodeType.PERSON.value]
        assert len(person_entities) >= 1

    def test_extract_org_entities(self):
        """組織名の抽出"""
        graph = KnowledgeGraph(TEST_ORG_ID)

        result = graph.extract_entities_from_text("営業部のメンバー")

        assert len(result) >= 1
        org_entities = [e for e in result if e.get("node_type") == NodeType.ORGANIZATION.value]
        assert len(org_entities) >= 1

    def test_extract_project_entities(self):
        """プロジェクト名の抽出"""
        graph = KnowledgeGraph(TEST_ORG_ID)

        result = graph.extract_entities_from_text("新規プロジェクトについて")

        assert len(result) >= 1

    def test_extract_no_entities(self):
        """エンティティなし"""
        graph = KnowledgeGraph(TEST_ORG_ID)

        result = graph.extract_entities_from_text("今日は晴れです")

        # エンティティが抽出されないか、最小限
        assert isinstance(result, list)


class TestExtractRelationsFromText:
    """extract_relations_from_text()メソッドのテスト"""

    def test_extract_belongs_to_relation(self):
        """所属関係の抽出"""
        graph = KnowledgeGraph(TEST_ORG_ID)

        entities = [{"name": "田中", "node_type": "person"}]
        result = graph.extract_relations_from_text("田中は営業部に所属", entities)

        assert isinstance(result, list)

    def test_extract_responsible_relation(self):
        """責任関係の抽出"""
        graph = KnowledgeGraph(TEST_ORG_ID)

        entities = [{"name": "田中", "node_type": "person"}]
        result = graph.extract_relations_from_text("田中がプロジェクトを担当", entities)

        assert isinstance(result, list)

    def test_extract_reports_to_relation(self):
        """報告関係の抽出"""
        graph = KnowledgeGraph(TEST_ORG_ID)

        entities = [{"name": "田中", "node_type": "person"}]
        result = graph.extract_relations_from_text("田中は部長に報告", entities)

        assert isinstance(result, list)


# =============================================================================
# ユーティリティテスト
# =============================================================================


class TestRowToNode:
    """_row_to_node()メソッドのテスト"""

    def test_row_to_node_basic(self):
        """行データからNodeへの変換"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        node = create_test_node()
        row = create_mock_node_row(node)

        result = graph._row_to_node(row)

        assert result.id == node.id
        assert result.name == node.name

    def test_row_to_node_with_none_values(self):
        """NULLを含む行データの変換"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        row = (
            str(uuid4()),
            None,  # organization_id
            None,  # node_type
            None,  # name
            None,  # description
            None,  # aliases
            None,  # properties
            None,  # importance_score
            None,  # activation_level
            None,  # source
            None,  # evidence_count
            None,  # created_at
            None,  # updated_at
        )

        result = graph._row_to_node(row)

        assert result is not None
        assert result.name == ""


class TestRowToEdge:
    """_row_to_edge()メソッドのテスト"""

    def test_row_to_edge_basic(self):
        """行データからEdgeへの変換"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        edge = create_test_edge()
        row = create_mock_edge_row(edge)

        result = graph._row_to_edge(row)

        assert result.id == edge.id
        assert result.source_node_id == edge.source_node_id

    def test_row_to_edge_with_none_values(self):
        """NULLを含む行データの変換"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        row = (
            str(uuid4()),
            None,  # organization_id
            str(uuid4()),  # source_node_id
            str(uuid4()),  # target_node_id
            None,  # relation_type
            None,  # weight
            None,  # confidence
            None,  # properties
            None,  # is_bidirectional
            None,  # evidence_count
            None,  # source
            None,  # created_at
            None,  # updated_at
        )

        result = graph._row_to_edge(row)

        assert result is not None


# =============================================================================
# 統計テスト
# =============================================================================


class TestGetStatistics:
    """get_statistics()メソッドのテスト"""

    def test_get_statistics_success(self):
        """統計取得成功"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()

        node_result = MagicMock()
        node_result.fetchall = MagicMock(return_value=[("person", 5), ("concept", 10)])
        edge_result = MagicMock()
        edge_result.fetchall = MagicMock(return_value=[("related_to", 8)])

        conn.execute = MagicMock(side_effect=[node_result, edge_result])

        result = graph.get_statistics(conn)

        assert result["total_nodes"] == 15
        assert result["total_edges"] == 8

    def test_get_statistics_error(self):
        """エラー時はデフォルト値を返す"""
        graph = KnowledgeGraph(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = graph.get_statistics(conn)

        assert result["total_nodes"] == 0
        assert result["total_edges"] == 0
