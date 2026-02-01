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
