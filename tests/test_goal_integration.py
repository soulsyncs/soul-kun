"""
lib/memory/goal_integration.py のテスト

対象:
- B1/B2/目標パターン統合
- 推奨生成
- パーソナライズサマリー
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from lib.memory.goal_integration import GoalSettingContextEnricher


class DummySummaryService:
    def __init__(self, summaries):
        self._summaries = summaries

    async def retrieve(self, *args, **kwargs):
        return self._summaries


class DummyPreferenceService:
    def __init__(self, prefs):
        self._prefs = prefs

    async def retrieve(self, *args, **kwargs):
        return self._prefs


@pytest.mark.asyncio
async def test_get_enriched_context_returns_empty_when_missing_ids():
    enricher = GoalSettingContextEnricher(conn=MagicMock(), org_id=None)
    result = await enricher.get_enriched_context(user_id="")
    assert result["conversation_summary"] == {}
    assert result["user_preferences"] == {}
    assert result["goal_patterns"] == {}
    assert "suggested_feedback_style" in result["recommendations"]


@pytest.mark.asyncio
async def test_get_conversation_context_aggregates_topics_tasks_people():
    summaries = [
        SimpleNamespace(key_topics=["売上目標", "チーム管理"], mentioned_tasks=["A"], mentioned_persons=["山田"]),
        SimpleNamespace(key_topics=["売上目標", "採用"], mentioned_tasks=["B"], mentioned_persons=["佐藤"]),
    ]
    enricher = GoalSettingContextEnricher(conn=MagicMock(), org_id="11111111-1111-1111-1111-111111111111")
    enricher._summary_service = DummySummaryService(summaries)

    result = await enricher._get_conversation_context("22222222-2222-2222-2222-222222222222")

    assert set(result["recent_topics"]) == {"売上目標", "チーム管理", "採用"}
    assert set(result["mentioned_tasks"]) == {"A", "B"}
    assert set(result["mentioned_persons"]) == {"山田", "佐藤"}
    assert result["summary_count"] == 2


@pytest.mark.asyncio
async def test_get_preference_context_maps_types():
    prefs = [
        SimpleNamespace(preference_type="response_style", preference_value="detailed", preference_key=None),
        SimpleNamespace(preference_type="communication", preference_value="formal", preference_key=None),
        SimpleNamespace(preference_type="emotion_trend", preference_value={"trend_direction": "declining"}, preference_key=None),
        SimpleNamespace(preference_type="feature_usage", preference_value="frequent", preference_key="goal_setting"),
    ]
    enricher = GoalSettingContextEnricher(conn=MagicMock(), org_id="11111111-1111-1111-1111-111111111111")
    enricher._preference_service = DummyPreferenceService(prefs)

    result = await enricher._get_preference_context("22222222-2222-2222-2222-222222222222")

    assert result["response_style"] == "detailed"
    assert result["communication_style"] == "formal"
    assert result["emotion_trend"]["trend_direction"] == "declining"
    assert result["goal_setting_usage"] == "frequent"


def test_get_goal_pattern_context_parses_row():
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (
        "ng_abstract",  # dominant_pattern
        {"history": 1},  # pattern_history
        3,  # avg_retry_count
        45.5,  # completion_rate
        {"why": 1},  # why_pattern_tendency
        {"what": 2},  # what_pattern_tendency
        {"how": 3},  # how_pattern_tendency
        0.4,  # avg_specificity_score
        "direct",  # preferred_feedback_style
    )
    mock_conn.execute.return_value = mock_result

    enricher = GoalSettingContextEnricher(conn=mock_conn, org_id="11111111-1111-1111-1111-111111111111")
    result = enricher._get_goal_pattern_context("22222222-2222-2222-2222-222222222222")

    assert result["dominant_pattern"] == "ng_abstract"
    assert result["avg_retry_count"] == 3.0
    assert result["completion_rate"] == 45.5
    assert result["avg_specificity_score"] == 0.4
    assert result["preferred_feedback_style"] == "direct"


def test_generate_recommendations_with_patterns_and_emotion():
    enricher = GoalSettingContextEnricher(conn=MagicMock(), org_id="11111111-1111-1111-1111-111111111111")
    context = {
        "goal_patterns": {
            "dominant_pattern": "ng_abstract",
            "avg_retry_count": 3,
            "completion_rate": 40,
            "avg_specificity_score": 0.3,
            "preferred_feedback_style": "direct",
        },
        "user_preferences": {
            "emotion_trend": {"trend_direction": "declining"},
        },
        "conversation_summary": {
            "recent_topics": ["売上", "採用", "評価"],
        },
    }

    rec = enricher._generate_recommendations(context)

    assert rec["suggested_feedback_style"] == "gentle"
    assert "より具体的な例を提示" in rec["focus_areas"]
    assert "小さなステップから始める" in rec["focus_areas"]
    assert "具体的な数値目標の例を提示" in rec["focus_areas"]
    assert "抽象的な表現" in rec["avoid_patterns"]
    assert any("感情傾向" in hint for hint in rec["personalization_hints"])
    assert any("最近話題" in hint for hint in rec["personalization_hints"])


def test_get_personalization_summary_builds_lines():
    enricher = GoalSettingContextEnricher(conn=MagicMock(), org_id="11111111-1111-1111-1111-111111111111")
    context = {
        "goal_patterns": {
            "completion_rate": 80,
            "dominant_pattern": "ng_abstract",
        },
        "recommendations": {
            "suggested_feedback_style": "gentle",
            "focus_areas": ["数値", "期限"],
        },
    }

    summary = enricher.get_personalization_summary(context)
    assert "過去の完了率" in summary
    assert "抽象的な表現が多い" in summary
    assert "優しいトーンで" in summary
    assert "注力" in summary
