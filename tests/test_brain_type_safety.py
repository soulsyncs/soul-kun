# tests/test_brain_type_safety.py
"""
Brain型安全性テスト

本番と同じ処理フローをテストし、型不整合エラーを事前に検出する。

v10.54: 根本原因修正後の再発防止テスト
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from lib.brain.models import (
    BrainContext,
    PersonInfo,
    TaskInfo,
    GoalInfo,
    InsightInfo,
    ConversationMessage,
)


class TestBrainContextIntegrity:
    """BrainContextの型整合性テスト"""

    def test_person_info_is_object_not_dict(self):
        """person_infoにはPersonInfoオブジェクトが入ること"""
        ctx = BrainContext()
        ctx.person_info = [PersonInfo(name="田中")]

        # to_dict()がエラーなく動作すること
        result = ctx.to_dict()
        assert result["person_info"][0]["name"] == "田中"

    def test_person_info_dict_should_not_break_to_dict(self):
        """person_infoに辞書が入ってもto_dict()が動作すること（後方互換）"""
        ctx = BrainContext()
        ctx.person_info = [{"name": "田中", "department": "営業"}]

        # to_dict()がエラーなく動作すること
        result = ctx.to_dict()
        assert result["person_info"][0]["name"] == "田中"

    def test_recent_tasks_is_object_not_dict(self):
        """recent_tasksにはTaskInfoオブジェクトが入ること"""
        ctx = BrainContext()
        ctx.recent_tasks = [TaskInfo(task_id="1", body="テスト")]

        result = ctx.to_dict()
        assert result["recent_tasks"][0]["task_id"] == "1"

    def test_recent_tasks_dict_should_not_break_to_dict(self):
        """recent_tasksに辞書が入ってもto_dict()が動作すること（後方互換）"""
        ctx = BrainContext()
        ctx.recent_tasks = [{"task_id": "1", "body": "テスト"}]

        result = ctx.to_dict()
        assert result["recent_tasks"][0]["task_id"] == "1"

    def test_active_goals_is_object_not_dict(self):
        """active_goalsにはGoalInfoオブジェクトが入ること"""
        ctx = BrainContext()
        ctx.active_goals = [GoalInfo(goal_id="1", title="売上目標")]

        result = ctx.to_dict()
        assert result["active_goals"][0]["goal_id"] == "1"

    def test_active_goals_dict_should_not_break_to_dict(self):
        """active_goalsに辞書が入ってもto_dict()が動作すること（後方互換）"""
        ctx = BrainContext()
        ctx.active_goals = [{"goal_id": "1", "title": "売上目標"}]

        result = ctx.to_dict()
        assert result["active_goals"][0]["goal_id"] == "1"

    def test_mixed_types_should_not_break_to_dict(self):
        """オブジェクトと辞書が混在してもto_dict()が動作すること"""
        ctx = BrainContext()
        ctx.person_info = [
            PersonInfo(name="田中"),
            {"name": "山田"},  # 辞書も混在
        ]
        ctx.recent_tasks = [
            TaskInfo(task_id="1", body="タスク1"),
            {"task_id": "2", "body": "タスク2"},
        ]
        ctx.active_goals = [
            GoalInfo(goal_id="1", title="目標1"),
            {"goal_id": "2", "title": "目標2"},
        ]

        result = ctx.to_dict()
        assert len(result["person_info"]) == 2
        assert len(result["recent_tasks"]) == 2
        assert len(result["active_goals"]) == 2


class TestGoalReviewFlow:
    """goal_review処理フローのテスト"""

    def test_goal_info_to_dict_has_required_fields(self):
        """GoalInfo.to_dict()が必要なフィールドを含むこと"""
        goal = GoalInfo(
            goal_id="goal_001",
            title="売上目標",
            why="会社の成長のため",
            what="月間売上100万円",
            status="active",
            progress=50.0,
        )

        result = goal.to_dict()

        assert "goal_id" in result
        assert "title" in result
        assert "why" in result
        assert "what" in result
        assert "status" in result
        assert "progress" in result
        assert result["goal_id"] == "goal_001"
        assert result["progress"] == 50.0

    def test_goal_info_to_string_format(self):
        """GoalInfo.to_string()が正しい形式を返すこと"""
        goal = GoalInfo(title="売上目標", progress=75.5)

        result = goal.to_string()

        assert "売上目標" in result
        assert "76%" in result or "75%" in result  # 四捨五入


class TestTaskSearchFlow:
    """task_search処理フローのテスト"""

    def test_task_info_to_dict_has_required_fields(self):
        """TaskInfo.to_dict()が必要なフィールドを含むこと"""
        task = TaskInfo(
            task_id="task_001",
            title="資料作成",
            body="売上報告書の作成",
            status="open",
            due_date=datetime(2026, 2, 1),
            is_overdue=False,
        )

        result = task.to_dict()

        assert "task_id" in result
        assert "title" in result
        assert "body" in result
        assert "status" in result
        assert "due_date" in result
        assert "is_overdue" in result

    def test_task_info_to_string_format(self):
        """TaskInfo.to_string()が正しい形式を返すこと"""
        task = TaskInfo(
            title="資料作成",
            due_date=datetime(2026, 2, 1),
            is_overdue=True,
        )

        result = task.to_string()

        assert "資料作成" in result
        assert "期限切れ" in result


class TestPersonInfoFlow:
    """person_info処理フローのテスト"""

    def test_person_info_to_dict_has_required_fields(self):
        """PersonInfo.to_dict()が必要なフィールドを含むこと"""
        person = PersonInfo(
            person_id="person_001",
            name="田中太郎",
            department="営業部",
            role="部長",
        )

        result = person.to_dict()

        assert "person_id" in result
        assert "name" in result
        assert "department" in result
        assert "role" in result

    def test_person_info_to_string_format(self):
        """PersonInfo.to_string()が正しい形式を返すこと"""
        person = PersonInfo(
            name="田中太郎",
            department="営業部",
            role="部長",
        )

        result = person.to_string()

        assert "田中太郎" in result
        assert "営業部" in result


class TestBackwardCompatibility:
    """後方互換性のテスト"""

    def test_goal_info_id_alias(self):
        """GoalInfo.idがgoal_idのエイリアスとして機能すること"""
        goal = GoalInfo(goal_id="goal_001")
        assert goal.id == "goal_001"

    def test_goal_info_due_date_alias(self):
        """GoalInfo.due_dateがdeadlineのエイリアスとして機能すること"""
        deadline = datetime(2026, 3, 1)
        goal = GoalInfo(deadline=deadline)
        assert goal.due_date == deadline

    def test_task_info_limit_time_alias(self):
        """TaskInfo.limit_timeがdue_dateのエイリアスとして機能すること"""
        due = datetime(2026, 2, 1)
        task = TaskInfo(due_date=due)
        assert task.limit_time == due

    def test_task_info_assigned_to_alias(self):
        """TaskInfo.assigned_toがassignee_nameのエイリアスとして機能すること"""
        task = TaskInfo(assignee_name="田中")
        assert task.assigned_to == "田中"

    def test_person_info_id_alias(self):
        """PersonInfo.idがperson_idのエイリアスとして機能すること"""
        person = PersonInfo(person_id="person_001")
        assert person.id == "person_001"


class TestTypeSafetyIntegration:
    """type_safety.py のSoT統合テスト（v10.57）"""

    def test_safe_to_dict_handles_dataclass(self):
        """safe_to_dictがdataclassを正しく変換すること"""
        from lib.brain.type_safety import safe_to_dict

        person = PersonInfo(name="田中", department="営業")
        result = safe_to_dict(person)
        assert isinstance(result, dict)
        assert result["name"] == "田中"

    def test_safe_to_dict_handles_datetime(self):
        """safe_to_dictがdatetimeをISO文字列に変換すること"""
        from lib.brain.type_safety import safe_to_dict

        dt = datetime(2026, 2, 7, 10, 30)
        result = safe_to_dict(dt)
        assert result == "2026-02-07T10:30:00"

    def test_safe_to_dict_handles_enum(self):
        """safe_to_dictがEnumをvalueに変換すること"""
        from lib.brain.type_safety import safe_to_dict
        from lib.brain.models import MemoryType

        result = safe_to_dict(MemoryType.PERSON_INFO)
        assert result == "person_info"

    def test_safe_to_dict_handles_uuid(self):
        """safe_to_dictがUUIDを文字列に変換すること"""
        from lib.brain.type_safety import safe_to_dict
        from uuid import UUID

        u = UUID("12345678-1234-5678-1234-567812345678")
        result = safe_to_dict(u)
        assert result == "12345678-1234-5678-1234-567812345678"

    def test_safe_to_dict_handles_nested(self):
        """safe_to_dictがネストされた構造を再帰的に変換すること"""
        from lib.brain.type_safety import safe_to_dict

        data = {
            "person": PersonInfo(name="田中"),
            "time": datetime(2026, 1, 1),
            "items": [GoalInfo(goal_id="1", title="目標")],
        }
        result = safe_to_dict(data)
        assert result["person"]["name"] == "田中"
        assert result["time"] == "2026-01-01T00:00:00"
        assert result["items"][0]["goal_id"] == "1"

    def test_brain_context_to_dict_uses_type_safety(self):
        """BrainContext.to_dict()がtype_safety.safe_to_dictを使用すること"""
        ctx = BrainContext()
        ctx.person_info = [PersonInfo(name="田中")]
        ctx.recent_tasks = [TaskInfo(task_id="1", body="test")]
        ctx.active_goals = [GoalInfo(goal_id="g1", title="目標")]
        ctx.timestamp = datetime(2026, 2, 7)

        result = ctx.to_dict()

        # dataclassが正しく辞書化されること
        assert result["person_info"][0]["name"] == "田中"
        assert result["recent_tasks"][0]["task_id"] == "1"
        assert result["active_goals"][0]["goal_id"] == "g1"
        assert result["timestamp"] == "2026-02-07T00:00:00"

    def test_safe_json_encoder_uses_type_safety(self):
        """SafeJSONEncoderがtype_safety.safe_to_dictに委譲すること"""
        import json
        from lib.brain.state_manager import SafeJSONEncoder

        data = {
            "person": PersonInfo(name="テスト"),
            "time": datetime(2026, 1, 1),
        }
        result = json.loads(json.dumps(data, cls=SafeJSONEncoder, ensure_ascii=False))
        assert result["person"]["name"] == "テスト"
        assert result["time"] == "2026-01-01T00:00:00"


class TestIdNoneGuard:
    """id が None の場合の安全なガードのテスト（v10.57）"""

    def test_learning_manager_none_id_returns_error(self):
        """learning.id が None の場合、delete_by_descriptionがエラーを返すこと"""
        from lib.brain.learning_foundation.manager import LearningManager
        from lib.brain.learning_foundation.models import Learning
        from unittest.mock import MagicMock

        manager = LearningManager.__new__(LearningManager)
        manager.repository = MagicMock()

        # id=Noneの学習を返す
        learning = Learning(
            id=None,
            organization_id="org-1",
            category="rule",
            learned_content={"description": "テスト"},
            authority_level="normal",
        )
        manager.repository.find_all.return_value = ([learning], 1)
        manager.repository.search = MagicMock(return_value=[learning])

        success, message, result = manager.delete_by_description(
            MagicMock(), "テスト", "acc-1", "manager"
        )
        assert success is False
        assert "ID" in message

    def test_implicit_detector_skips_none_id_event(self):
        """event.id が None の場合、detect()がNoneを返すこと"""
        from lib.brain.outcome_learning.implicit_detector import ImplicitFeedbackDetector
        from lib.brain.outcome_learning.models import OutcomeEvent

        detector = ImplicitFeedbackDetector("org-1")
        event = OutcomeEvent(
            id=None,
            organization_id="org-1",
            event_type="goal_reminder",
        )

        result = detector.detect(MagicMock(), event)
        assert result is None

    def test_effectiveness_tracker_none_id_health_check_no_crash(self):
        """learning.id が None でも check_health() がクラッシュしないこと"""
        from lib.brain.learning_foundation.effectiveness_tracker import EffectivenessTracker
        from lib.brain.learning_foundation.models import Learning

        tracker = EffectivenessTracker.__new__(EffectivenessTracker)
        tracker.organization_id = "org-1"
        tracker.repository = MagicMock()
        tracker.confidence_decay_rate = 0.001

        learning = Learning(
            id=None,
            organization_id="org-1",
            category="rule",
            learned_content={"description": "テスト"},
            authority_level="normal",
        )

        # ValueError ではなく、critical ステータスを返すこと
        health = tracker.check_health(learning)
        assert health.status == "critical"
        assert health.learning_id == ""

    def test_effectiveness_tracker_none_id_calculate_no_crash(self):
        """learning.id が None でも calculate_effectiveness() がクラッシュしないこと"""
        from lib.brain.learning_foundation.effectiveness_tracker import EffectivenessTracker
        from lib.brain.learning_foundation.models import Learning

        tracker = EffectivenessTracker.__new__(EffectivenessTracker)
        tracker.organization_id = "org-1"
        tracker.repository = MagicMock()
        tracker.confidence_decay_rate = 0.001

        learning = Learning(
            id=None,
            organization_id="org-1",
            category="rule",
            learned_content={"description": "テスト"},
            authority_level="normal",
        )

        # ValueError ではなく、デフォルト結果を返すこと
        result = tracker.calculate_effectiveness(learning)
        assert result.learning_id == ""
        assert result.recommendation == "review"

    def test_effectiveness_tracker_batch_survives_none_id(self):
        """バッチ処理中に learning.id=None があっても全体がクラッシュしないこと"""
        from lib.brain.learning_foundation.effectiveness_tracker import EffectivenessTracker
        from lib.brain.learning_foundation.models import Learning

        tracker = EffectivenessTracker.__new__(EffectivenessTracker)
        tracker.organization_id = "org-1"
        tracker.repository = MagicMock()
        tracker.confidence_decay_rate = 0.001

        learnings = [
            Learning(id="valid-1", organization_id="org-1", category="rule",
                     learned_content={}, authority_level="normal"),
            Learning(id=None, organization_id="org-1", category="rule",
                     learned_content={}, authority_level="normal"),
            Learning(id="valid-2", organization_id="org-1", category="fact",
                     learned_content={}, authority_level="normal"),
        ]

        # バッチ全体がクラッシュしないこと
        results = tracker.calculate_effectiveness_batch(MagicMock(), learnings)
        assert len(results) == 3


class TestDirectionAndFilterPaths:
    """get_related_nodes direction / find_episodes_by_entity entity_type テスト"""

    def test_get_related_nodes_outgoing_direction(self):
        """outgoing方向で関連ノードを取得できること"""
        from lib.brain.memory_enhancement import BrainMemoryEnhancement
        from lib.brain.memory_enhancement.models import KnowledgeNode, KnowledgeEdge

        mem = BrainMemoryEnhancement.__new__(BrainMemoryEnhancement)
        mem._knowledge_graph = MagicMock()

        # outgoing edges from node-A
        edge = KnowledgeEdge(
            organization_id="org-1",
            source_node_id="node-A",
            target_node_id="node-B",
            relation_type="belongs_to",
        )
        mem._knowledge_graph.find_edges_from.return_value = [edge]
        target_node = KnowledgeNode(
            organization_id="org-1", name="Node B", node_type="person",
        )
        mem._knowledge_graph.find_node_by_id.return_value = target_node

        result = mem.get_related_nodes(MagicMock(), "node-A", direction="outgoing")
        assert len(result) == 1
        assert result[0].name == "Node B"
        mem._knowledge_graph.find_edges_from.assert_called_once()

    def test_get_related_nodes_incoming_direction(self):
        """incoming方向で関連ノードを取得できること"""
        from lib.brain.memory_enhancement import BrainMemoryEnhancement
        from lib.brain.memory_enhancement.models import KnowledgeNode, KnowledgeEdge

        mem = BrainMemoryEnhancement.__new__(BrainMemoryEnhancement)
        mem._knowledge_graph = MagicMock()

        # incoming edge to node-B
        edge = KnowledgeEdge(
            organization_id="org-1",
            source_node_id="node-A",
            target_node_id="node-B",
            relation_type="belongs_to",
        )
        mem._knowledge_graph.find_edges_to.return_value = [edge]
        source_node = KnowledgeNode(
            organization_id="org-1", name="Node A", node_type="person",
        )
        mem._knowledge_graph.find_node_by_id.return_value = source_node

        result = mem.get_related_nodes(MagicMock(), "node-B", direction="incoming")
        assert len(result) == 1
        assert result[0].name == "Node A"
        mem._knowledge_graph.find_edges_to.assert_called_once()

    def test_get_related_nodes_self_loop_skipped(self):
        """自己参照エッジがスキップされること"""
        from lib.brain.memory_enhancement import BrainMemoryEnhancement
        from lib.brain.memory_enhancement.models import KnowledgeEdge

        mem = BrainMemoryEnhancement.__new__(BrainMemoryEnhancement)
        mem._knowledge_graph = MagicMock()

        # self-loop edge
        edge = KnowledgeEdge(
            organization_id="org-1",
            source_node_id="node-A",
            target_node_id="node-A",
            relation_type="relates_to",
        )
        mem._knowledge_graph.find_edges_from.return_value = [edge]

        result = mem.get_related_nodes(MagicMock(), "node-A", direction="outgoing")
        assert len(result) == 0

    def test_get_related_nodes_edge_type_filter(self):
        """edge_typesフィルタが効くこと"""
        from lib.brain.memory_enhancement import BrainMemoryEnhancement
        from lib.brain.memory_enhancement.models import KnowledgeNode, KnowledgeEdge

        mem = BrainMemoryEnhancement.__new__(BrainMemoryEnhancement)
        mem._knowledge_graph = MagicMock()

        edge1 = KnowledgeEdge(
            organization_id="org-1",
            source_node_id="node-A", target_node_id="node-B",
            relation_type="belongs_to",
        )
        edge2 = KnowledgeEdge(
            organization_id="org-1",
            source_node_id="node-A", target_node_id="node-C",
            relation_type="manages",
        )
        mem._knowledge_graph.find_edges_from.return_value = [edge1, edge2]
        node_b = KnowledgeNode(organization_id="org-1", name="B", node_type="org")
        mem._knowledge_graph.find_node_by_id.return_value = node_b

        # manages のみフィルタ
        result = mem.get_related_nodes(
            MagicMock(), "node-A", edge_types=["manages"], direction="outgoing",
        )
        assert len(result) == 1

    def test_find_episodes_by_entity_passes_entity_type(self):
        """find_episodes_by_entity が entity_type を渡すこと"""
        from lib.brain.memory_enhancement import BrainMemoryEnhancement
        from lib.brain.memory_enhancement.constants import EntityType

        mem = BrainMemoryEnhancement.__new__(BrainMemoryEnhancement)
        mem._episode_repo = MagicMock()
        mem._episode_repo.find_by_entities.return_value = []

        mem.find_episodes_by_entity(
            MagicMock(), entity_type=EntityType.PERSON, entity_id="person-1",
        )

        call_kwargs = mem._episode_repo.find_by_entities.call_args
        assert call_kwargs.kwargs.get("entity_type") == EntityType.PERSON


class TestPatternExtractorNoneIdSkip:
    """pattern_extractor の None id スキップテスト"""

    def test_save_patterns_skips_none_id_existing(self):
        """既存パターンの id が None の場合、update をスキップすること"""
        from lib.brain.outcome_learning.pattern_extractor import PatternExtractor
        from lib.brain.outcome_learning.models import OutcomePattern
        from lib.brain.outcome_learning.repository import OutcomeRepository

        extractor = PatternExtractor.__new__(PatternExtractor)
        extractor.organization_id = "org-1"
        extractor.repository = MagicMock(spec=OutcomeRepository)

        # 既存パターン（id=None）
        existing = OutcomePattern(
            id=None,
            organization_id="org-1",
            pattern_type="timing",
            pattern_category="time_slot",
            scope="global",
        )
        extractor.repository.find_patterns.return_value = [existing]

        new_pattern = OutcomePattern(
            organization_id="org-1",
            pattern_type="timing",
            pattern_category="time_slot",
            scope="global",
            confidence_score=0.8,
            sample_count=10,
        )

        extractor.save_patterns(MagicMock(), [new_pattern])

        # update_pattern_stats は呼ばれないこと（id=None でスキップ）
        extractor.repository.update_pattern_stats.assert_not_called()
