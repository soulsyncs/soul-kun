# tests/test_brain_models.py
"""
lib/brain/models.py のテスト

全データクラス、Enum、メソッド（to_dict, from_dict, プロパティ等）を網羅的にテスト。
ターゲット: 未カバー行を中心にカバレッジ向上を狙う。
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from lib.brain.models import (
    # Enums
    MemoryType,
    StateType,
    UrgencyLevel,
    ConfidenceLevel,
    TeachingCategory,
    ValidationStatus,
    ConflictType,
    AlertStatus,
    Severity,
    ProactiveMessageTone,
    # Dataclasses
    Confidence,
    ConversationMessage,
    SummaryData,
    PreferenceData,
    PersonInfo,
    TaskInfo,
    GoalInfo,
    GoalSessionInfo,
    KnowledgeChunk,
    InsightInfo,
    ConversationState,
    BrainContext,
    ResolvedEntity,
    UnderstandingResult,
    ActionCandidate,
    DecisionResult,
    HandlerResult,
    ConfirmationRequest,
    BrainResponse,
    CEOTeaching,
    ConflictInfo,
    GuardianAlert,
    TeachingValidationResult,
    TeachingUsageContext,
    CEOTeachingContext,
    ProactiveMessageResult,
)


# =============================================================================
# Enum テスト
# =============================================================================


class TestMemoryType:
    """MemoryType Enumのテスト"""

    def test_values(self):
        assert MemoryType.CURRENT_STATE == "current_state"
        assert MemoryType.RECENT_CONVERSATION == "recent_conversation"
        assert MemoryType.CONVERSATION_SUMMARY == "conversation_summary"
        assert MemoryType.CONVERSATION_SEARCH == "conversation_search"

    def test_is_str(self):
        assert isinstance(MemoryType.CURRENT_STATE, str)


class TestStateType:
    """StateType Enumのテスト"""

    def test_values(self):
        assert StateType.NORMAL == "normal"
        assert StateType.GOAL_SETTING == "goal_setting"
        assert StateType.LIST_CONTEXT == "list_context"

    def test_is_str(self):
        assert isinstance(StateType.NORMAL, str)


class TestUrgencyLevel:
    """UrgencyLevel Enumのテスト"""

    def test_values(self):
        assert UrgencyLevel.LOW == "low"
        assert UrgencyLevel.MEDIUM == "medium"
        assert UrgencyLevel.HIGH == "high"


class TestConfidenceLevel:
    """ConfidenceLevel Enumのテスト"""

    def test_values(self):
        assert ConfidenceLevel.VERY_LOW == "very_low"
        assert ConfidenceLevel.LOW == "low"
        assert ConfidenceLevel.MEDIUM == "medium"
        assert ConfidenceLevel.HIGH == "high"
        assert ConfidenceLevel.VERY_HIGH == "very_high"

    def test_from_score_very_low(self):
        assert ConfidenceLevel.from_score(0.0) == ConfidenceLevel.VERY_LOW
        assert ConfidenceLevel.from_score(0.29) == ConfidenceLevel.VERY_LOW

    def test_from_score_low(self):
        assert ConfidenceLevel.from_score(0.3) == ConfidenceLevel.LOW
        assert ConfidenceLevel.from_score(0.49) == ConfidenceLevel.LOW

    def test_from_score_medium(self):
        assert ConfidenceLevel.from_score(0.5) == ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.from_score(0.69) == ConfidenceLevel.MEDIUM

    def test_from_score_high(self):
        assert ConfidenceLevel.from_score(0.7) == ConfidenceLevel.HIGH
        assert ConfidenceLevel.from_score(0.89) == ConfidenceLevel.HIGH

    def test_from_score_very_high(self):
        assert ConfidenceLevel.from_score(0.9) == ConfidenceLevel.VERY_HIGH
        assert ConfidenceLevel.from_score(1.0) == ConfidenceLevel.VERY_HIGH


# =============================================================================
# Confidence テスト (lines 119-122, 127, 132, 137, 141, 163-174, 178, 182-183,
#                     187-188, 192-193, 197-198)
# =============================================================================


class TestConfidence:
    """Confidence dataclass のテスト"""

    def test_default_values(self):
        """デフォルト値のテスト"""
        c = Confidence()
        assert c.overall == 0.0
        assert c.reasoning is None
        assert c.intent_confidence is None
        assert c.entity_confidence is None

    def test_creation_with_values(self):
        c = Confidence(overall=0.85, reasoning="テスト理由")
        assert c.overall == 0.85
        assert c.reasoning == "テスト理由"

    # --- __post_init__ validation (lines 119-122) ---
    def test_validation_type_error(self):
        """overall が数値でない場合 TypeError"""
        with pytest.raises(TypeError, match="overall must be a number"):
            Confidence(overall="invalid")

    def test_validation_too_low(self):
        """overall が 0.0 未満の場合 ValueError"""
        with pytest.raises(ValueError, match="overall must be between 0.0 and 1.0"):
            Confidence(overall=-0.1)

    def test_validation_too_high(self):
        """overall が 1.0 超の場合 ValueError"""
        with pytest.raises(ValueError, match="overall must be between 0.0 and 1.0"):
            Confidence(overall=1.1)

    def test_validation_int_accepted(self):
        """int(0 or 1) は受け入れられる"""
        c = Confidence(overall=1)
        assert c.overall == 1

    def test_validation_boundary_zero(self):
        c = Confidence(overall=0.0)
        assert c.overall == 0.0

    def test_validation_boundary_one(self):
        c = Confidence(overall=1.0)
        assert c.overall == 1.0

    # --- level property (line 127) ---
    def test_level_property(self):
        assert Confidence(overall=0.85).level == ConfidenceLevel.HIGH
        assert Confidence(overall=0.1).level == ConfidenceLevel.VERY_LOW
        assert Confidence(overall=0.95).level == ConfidenceLevel.VERY_HIGH

    # --- is_high property (line 132) ---
    def test_is_high_true(self):
        assert Confidence(overall=0.7).is_high is True
        assert Confidence(overall=0.9).is_high is True

    def test_is_high_false(self):
        assert Confidence(overall=0.69).is_high is False

    # --- is_low property (line 137) ---
    def test_is_low_true(self):
        assert Confidence(overall=0.0).is_low is True
        assert Confidence(overall=0.49).is_low is True

    def test_is_low_false(self):
        assert Confidence(overall=0.5).is_low is False

    # --- to_dict (line 141) ---
    def test_to_dict(self):
        c = Confidence(
            overall=0.85,
            reasoning="test",
            intent_confidence=0.9,
            entity_confidence=0.8,
        )
        d = c.to_dict()
        assert d["overall"] == 0.85
        assert d["level"] == "high"
        assert d["reasoning"] == "test"
        assert d["intent_confidence"] == 0.9
        assert d["entity_confidence"] == 0.8

    def test_to_dict_defaults(self):
        d = Confidence().to_dict()
        assert d["overall"] == 0.0
        assert d["reasoning"] is None
        assert d["intent_confidence"] is None
        assert d["entity_confidence"] is None

    # --- from_value (lines 163-174) ---
    def test_from_value_confidence_passthrough(self):
        """Confidence インスタンスをそのまま返す"""
        c = Confidence(overall=0.5)
        result = Confidence.from_value(c)
        assert result is c

    def test_from_value_float(self):
        c = Confidence.from_value(0.75)
        assert c.overall == 0.75

    def test_from_value_int(self):
        c = Confidence.from_value(1)
        assert c.overall == 1.0

    def test_from_value_dict(self):
        d = {
            "overall": 0.8,
            "reasoning": "dict理由",
            "intent_confidence": 0.9,
            "entity_confidence": 0.7,
        }
        c = Confidence.from_value(d)
        assert c.overall == 0.8
        assert c.reasoning == "dict理由"
        assert c.intent_confidence == 0.9
        assert c.entity_confidence == 0.7

    def test_from_value_dict_defaults(self):
        c = Confidence.from_value({})
        assert c.overall == 0.0
        assert c.reasoning is None

    def test_from_value_unsupported_type(self):
        with pytest.raises(TypeError, match="Cannot create Confidence from"):
            Confidence.from_value("invalid")

    # --- __float__ (line 178) ---
    def test_float_conversion(self):
        c = Confidence(overall=0.85)
        assert float(c) == 0.85

    # --- comparison operators (lines 182-183, 187-188, 192-193, 197-198) ---
    def test_lt_float(self):
        c = Confidence(overall=0.5)
        assert (c < 0.6) is True
        assert (c < 0.4) is False

    def test_lt_confidence(self):
        c1 = Confidence(overall=0.3)
        c2 = Confidence(overall=0.7)
        assert (c1 < c2) is True
        assert (c2 < c1) is False

    def test_le_float(self):
        c = Confidence(overall=0.5)
        assert (c <= 0.5) is True
        assert (c <= 0.6) is True
        assert (c <= 0.4) is False

    def test_le_confidence(self):
        c1 = Confidence(overall=0.5)
        c2 = Confidence(overall=0.5)
        assert (c1 <= c2) is True

    def test_gt_float(self):
        c = Confidence(overall=0.7)
        assert (c > 0.5) is True
        assert (c > 0.8) is False

    def test_gt_confidence(self):
        c1 = Confidence(overall=0.8)
        c2 = Confidence(overall=0.3)
        assert (c1 > c2) is True

    def test_ge_float(self):
        c = Confidence(overall=0.7)
        assert (c >= 0.7) is True
        assert (c >= 0.6) is True
        assert (c >= 0.8) is False

    def test_ge_confidence(self):
        c1 = Confidence(overall=0.7)
        c2 = Confidence(overall=0.7)
        assert (c1 >= c2) is True


# =============================================================================
# ConversationMessage テスト (line 218)
# =============================================================================


class TestConversationMessage:
    """ConversationMessage dataclass のテスト"""

    def test_to_dict(self):
        ts = datetime(2026, 1, 1, 12, 0, 0)
        msg = ConversationMessage(
            role="user",
            content="テストメッセージ",
            timestamp=ts,
            message_id="msg-1",
            sender_name="テスト太郎",
        )
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "テストメッセージ"
        assert d["timestamp"] == ts.isoformat()
        assert d["message_id"] == "msg-1"
        assert d["sender_name"] == "テスト太郎"

    def test_to_dict_no_optional(self):
        ts = datetime(2026, 1, 1, 12, 0, 0)
        msg = ConversationMessage(role="assistant", content="応答", timestamp=ts)
        d = msg.to_dict()
        assert d["message_id"] is None
        assert d["sender_name"] is None


# =============================================================================
# SummaryData テスト (line 239)
# =============================================================================


class TestSummaryData:
    """SummaryData dataclass のテスト"""

    def test_to_dict(self):
        ts = datetime(2026, 1, 15, 9, 0, 0)
        sd = SummaryData(
            summary="テスト要約",
            key_topics=["話題A", "話題B"],
            mentioned_persons=["田中"],
            mentioned_tasks=["タスクX"],
            created_at=ts,
        )
        d = sd.to_dict()
        assert d["summary"] == "テスト要約"
        assert d["key_topics"] == ["話題A", "話題B"]
        assert d["mentioned_persons"] == ["田中"]
        assert d["mentioned_tasks"] == ["タスクX"]
        assert d["created_at"] == ts.isoformat()


# =============================================================================
# PreferenceData テスト (line 259)
# =============================================================================


class TestPreferenceData:
    """PreferenceData dataclass のテスト"""

    def test_defaults(self):
        pd = PreferenceData()
        assert pd.response_style is None
        assert pd.feature_usage == {}
        assert pd.preferred_times == []
        assert pd.custom_keywords == {}

    def test_to_dict(self):
        pd = PreferenceData(
            response_style="casual",
            feature_usage={"task": 5},
            preferred_times=["morning"],
            custom_keywords={"kw": "val"},
        )
        d = pd.to_dict()
        assert d["response_style"] == "casual"
        assert d["feature_usage"] == {"task": 5}
        assert d["preferred_times"] == ["morning"]
        assert d["custom_keywords"] == {"kw": "val"}


# =============================================================================
# PersonInfo テスト (lines 328, 335, 340)
# =============================================================================


class TestPersonInfo:
    """PersonInfo dataclass のテスト"""

    def test_defaults(self):
        p = PersonInfo()
        assert p.person_id == ""
        assert p.name == ""
        assert p.expertise == []
        assert p.responsibilities == []
        assert p.attributes == {}

    def test_to_dict(self):
        p = PersonInfo(
            person_id="p-1",
            name="菊地",
            department="開発部",
            role="エンジニア",
        )
        d = p.to_dict()
        assert d["person_id"] == "p-1"
        assert d["name"] == "菊地"
        assert d["department"] == "開発部"
        assert d["role"] == "エンジニア"

    def test_to_string_name_only(self):
        p = PersonInfo(name="田中")
        assert p.to_string() == "田中"

    def test_to_string_with_department(self):
        p = PersonInfo(name="田中", department="営業部")
        assert p.to_string() == "田中(営業部)"

    def test_to_string_with_role(self):
        p = PersonInfo(name="田中", role="部長")
        assert "田中" in p.to_string()
        assert "[部長]" in p.to_string()

    def test_to_string_with_position_fallback(self):
        """role が None で position がある場合"""
        p = PersonInfo(name="田中", position="課長")
        assert "[課長]" in p.to_string()

    def test_to_string_with_description(self):
        """description ありの場合 (line 328)"""
        p = PersonInfo(name="田中", description="営業リーダー")
        assert "田中" in p.to_string()
        assert ": 営業リーダー" in p.to_string()

    def test_to_string_full(self):
        p = PersonInfo(name="田中", department="営業部", role="部長", description="ベテラン")
        result = p.to_string()
        assert "田中" in result
        assert "(営業部)" in result
        assert "[部長]" in result
        assert ": ベテラン" in result

    # --- 後方互換プロパティ (lines 335, 340) ---
    def test_known_info_alias(self):
        """known_info は attributes のエイリアス (line 335)"""
        p = PersonInfo(attributes={"key": "value"})
        assert p.known_info == {"key": "value"}

    def test_chatwork_id_alias(self):
        """chatwork_id は chatwork_account_id のエイリアス (line 340)"""
        p = PersonInfo(chatwork_account_id="12345")
        assert p.chatwork_id == "12345"

    def test_chatwork_id_alias_none(self):
        p = PersonInfo()
        assert p.chatwork_id is None

    def test_id_alias(self):
        p = PersonInfo(person_id="p-123")
        assert p.id == "p-123"

    # --- to_safe_dict PII マスキング ---

    def test_to_safe_dict_masks_name(self):
        """to_safe_dict は name を [PERSON] にマスク"""
        p = PersonInfo(name="田中太郎", department="営業部")
        d = p.to_safe_dict()
        assert d["name"] == "[PERSON]"
        assert d["department"] == "営業部"

    def test_to_safe_dict_masks_email(self):
        """to_safe_dict は email を [EMAIL] にマスク"""
        p = PersonInfo(name="田中", email="tanaka@example.com")
        d = p.to_safe_dict()
        assert d["email"] == "[EMAIL]"

    def test_to_safe_dict_empty_name_stays_empty(self):
        """to_safe_dict は空の name を [PERSON] にしない"""
        p = PersonInfo(name="")
        d = p.to_safe_dict()
        assert d["name"] == ""

    def test_to_safe_dict_none_email_stays_none(self):
        """to_safe_dict は None の email を [EMAIL] にしない"""
        p = PersonInfo(name="田中", email=None)
        d = p.to_safe_dict()
        assert d["email"] is None

    def test_to_safe_dict_preserves_non_pii(self):
        """to_safe_dict は PII 以外のフィールドを変更しない"""
        p = PersonInfo(
            person_id="p-1",
            department="開発部",
            role="エンジニア",
            expertise=["Python", "AI"],
        )
        d = p.to_safe_dict()
        assert d["person_id"] == "p-1"
        assert d["department"] == "開発部"
        assert d["role"] == "エンジニア"
        assert d["expertise"] == ["Python", "AI"]

    def test_to_dict_still_returns_raw_pii(self):
        """to_dict は引き続き生の PII を返す（内部ロジック用）"""
        p = PersonInfo(name="田中太郎", email="tanaka@example.com")
        d = p.to_dict()
        assert d["name"] == "田中太郎"
        assert d["email"] == "tanaka@example.com"


# =============================================================================
# TaskInfo テスト (lines 437, 442-445)
# =============================================================================


class TestTaskInfo:
    """TaskInfo dataclass のテスト"""

    def test_defaults(self):
        t = TaskInfo()
        assert t.task_id == ""
        assert t.status == "open"
        assert t.priority == "normal"
        assert t.is_overdue is False

    def test_to_dict(self):
        due = datetime(2026, 2, 15)
        t = TaskInfo(
            task_id="t-1",
            title="テストタスク",
            body="タスクの詳細",
            due_date=due,
            is_overdue=True,
        )
        d = t.to_dict()
        assert d["task_id"] == "t-1"
        assert d["title"] == "テストタスク"
        assert d["due_date"] == due.isoformat()
        assert d["is_overdue"] is True

    def test_to_dict_none_dates(self):
        t = TaskInfo()
        d = t.to_dict()
        assert d["due_date"] is None
        assert d["created_at"] is None
        assert d["completed_at"] is None

    def test_to_string_with_title(self):
        t = TaskInfo(title="経費精算")
        assert "経費精算" in t.to_string()

    def test_to_string_with_summary_fallback(self):
        t = TaskInfo(summary="要約テスト")
        assert "要約テスト" in t.to_string()

    def test_to_string_with_body_fallback(self):
        t = TaskInfo(body="これはタスクの本文でありとても長い内容が含まれています")
        result = t.to_string()
        assert len(result) > 0

    def test_to_string_with_due_date(self):
        t = TaskInfo(title="タスク", due_date=datetime(2026, 3, 1))
        assert "期限: 2026-03-01" in t.to_string()

    def test_to_string_overdue(self):
        t = TaskInfo(title="タスク", is_overdue=True)
        assert "[期限切れ]" in t.to_string()

    def test_to_string_with_assignee(self):
        t = TaskInfo(title="タスク", assignee_name="山田")
        assert "担当: 山田" in t.to_string()

    # --- 後方互換プロパティ (line 437) ---
    def test_assigned_to_name_alias(self):
        """assigned_to_name は assignee_name のエイリアス (line 437)"""
        t = TaskInfo(assignee_name="田中")
        assert t.assigned_to_name == "田中"

    def test_limit_time_alias(self):
        due = datetime(2026, 2, 15)
        t = TaskInfo(due_date=due)
        assert t.limit_time == due

    def test_assigned_to_alias(self):
        t = TaskInfo(assignee_name="山田")
        assert t.assigned_to == "山田"

    # --- days_until_due (lines 442-445) ---
    def test_days_until_due_with_date(self):
        """期限がある場合の日数計算 (lines 442-444)"""
        future_date = datetime.now() + timedelta(days=10)
        t = TaskInfo(due_date=future_date)
        days = t.days_until_due
        assert days is not None
        assert days >= 9  # 端数の関係で9以上

    def test_days_until_due_none(self):
        """期限がない場合は None (line 445)"""
        t = TaskInfo()
        assert t.days_until_due is None

    def test_days_until_due_past(self):
        """期限が過去の場合は負の値"""
        past_date = datetime.now() - timedelta(days=5)
        t = TaskInfo(due_date=past_date)
        days = t.days_until_due
        assert days is not None
        assert days < 0


# =============================================================================
# GoalInfo テスト (lines 520, 525, 530-533, 538-540)
# =============================================================================


class TestGoalInfo:
    """GoalInfo dataclass のテスト"""

    def test_defaults(self):
        g = GoalInfo()
        assert g.goal_id == ""
        assert g.status == "active"
        assert g.progress == 0.0

    def test_to_dict(self):
        dl = datetime(2026, 6, 1)
        g = GoalInfo(
            goal_id="g-1",
            title="売上目標",
            progress=50.0,
            deadline=dl,
        )
        d = g.to_dict()
        assert d["goal_id"] == "g-1"
        assert d["title"] == "売上目標"
        assert d["progress"] == 50.0
        assert d["deadline"] == dl.isoformat()

    def test_to_dict_none_dates(self):
        g = GoalInfo()
        d = g.to_dict()
        assert d["deadline"] is None
        assert d["created_at"] is None
        assert d["updated_at"] is None
        assert d["completed_at"] is None

    def test_to_string(self):
        g = GoalInfo(title="売上倍増", progress=75.0)
        result = g.to_string()
        assert "売上倍増" in result
        assert "75%達成" in result

    def test_to_string_what_fallback(self):
        g = GoalInfo(what="顧客満足度向上", progress=30.0)
        result = g.to_string()
        assert "顧客満足度向上" in result

    # --- 後方互換プロパティ ---
    def test_due_date_alias(self):
        dl = datetime(2026, 6, 1)
        g = GoalInfo(deadline=dl)
        assert g.due_date == dl

    def test_id_alias(self):
        g = GoalInfo(goal_id="g-99")
        assert g.id == "g-99"

    # --- target_date (line 520) ---
    def test_target_date_alias(self):
        """target_date は deadline のエイリアス (line 520)"""
        dl = datetime(2026, 6, 1)
        g = GoalInfo(deadline=dl)
        assert g.target_date == dl

    def test_target_date_none(self):
        g = GoalInfo()
        assert g.target_date is None

    # --- progress_percentage (line 525) ---
    def test_progress_percentage(self):
        """progress_percentage は int(progress) (line 525)"""
        g = GoalInfo(progress=67.8)
        assert g.progress_percentage == 67
        assert isinstance(g.progress_percentage, int)

    # --- is_stale (lines 530-533) ---
    def test_is_stale_true(self):
        """7日以上更新がない active な目標は stale (lines 530-532)"""
        old_date = datetime.now() - timedelta(days=10)
        g = GoalInfo(status="active", updated_at=old_date)
        assert g.is_stale is True

    def test_is_stale_false_recent(self):
        """最近更新された目標は stale でない"""
        recent = datetime.now() - timedelta(days=3)
        g = GoalInfo(status="active", updated_at=recent)
        assert g.is_stale is False

    def test_is_stale_false_not_active(self):
        """active でない目標は stale でない"""
        old_date = datetime.now() - timedelta(days=10)
        g = GoalInfo(status="completed", updated_at=old_date)
        assert g.is_stale is False

    def test_is_stale_false_no_updated_at(self):
        """updated_at が None なら stale でない (line 533)"""
        g = GoalInfo(status="active")
        assert g.is_stale is False

    # --- days_since_update (lines 538-540) ---
    def test_days_since_update_with_date(self):
        """updated_at があれば日数を返す (lines 538-539)"""
        old_date = datetime.now() - timedelta(days=5)
        g = GoalInfo(updated_at=old_date)
        assert g.days_since_update >= 4

    def test_days_since_update_none(self):
        """updated_at が None なら 0 (line 540)"""
        g = GoalInfo()
        assert g.days_since_update == 0


# =============================================================================
# GoalSessionInfo テスト (line 555)
# =============================================================================


class TestGoalSessionInfo:
    """GoalSessionInfo dataclass のテスト"""

    def test_to_dict(self):
        """to_dict の基本テスト (line 555)"""
        gs = GoalSessionInfo(
            session_id="s-1",
            current_step="why",
            retry_count=2,
            data={"key": "val"},
        )
        d = gs.to_dict()
        assert d["session_id"] == "s-1"
        assert d["current_step"] == "why"
        assert d["retry_count"] == 2
        assert d["data"] == {"key": "val"}
        assert "created_at" in d


# =============================================================================
# KnowledgeChunk テスト (line 576)
# =============================================================================


class TestKnowledgeChunk:
    """KnowledgeChunk dataclass のテスト"""

    def test_to_dict(self):
        """to_dict の基本テスト (line 576)"""
        kc = KnowledgeChunk(
            chunk_id="c-1",
            content="テスト知識",
            source="FAQ",
            relevance_score=0.9,
            metadata={"page": 3},
        )
        d = kc.to_dict()
        assert d["chunk_id"] == "c-1"
        assert d["content"] == "テスト知識"
        assert d["source"] == "FAQ"
        assert d["relevance_score"] == 0.9
        assert d["metadata"] == {"page": 3}


# =============================================================================
# InsightInfo テスト (line 598)
# =============================================================================


class TestInsightInfo:
    """InsightInfo dataclass のテスト"""

    def test_to_dict(self):
        """to_dict の基本テスト (line 598)"""
        ts = datetime(2026, 1, 20, 15, 30, 0)
        ii = InsightInfo(
            insight_id="i-1",
            insight_type="stagnant_task",
            title="停滞タスク",
            description="5日間動きなし",
            severity="high",
            created_at=ts,
        )
        d = ii.to_dict()
        assert d["insight_id"] == "i-1"
        assert d["insight_type"] == "stagnant_task"
        assert d["title"] == "停滞タスク"
        assert d["description"] == "5日間動きなし"
        assert d["severity"] == "high"
        assert d["created_at"] == ts.isoformat()


# =============================================================================
# ConversationState テスト (line 655)
# =============================================================================


class TestConversationState:
    """ConversationState dataclass のテスト"""

    def test_defaults(self):
        cs = ConversationState()
        assert cs.state_type == StateType.NORMAL
        assert cs.is_active is False  # NORMAL は常に非アクティブ

    def test_is_active_normal(self):
        """NORMAL状態は非アクティブ"""
        cs = ConversationState(state_type=StateType.NORMAL)
        assert cs.is_active is False

    def test_is_active_goal_setting(self):
        """GOAL_SETTING で期限なしはアクティブ"""
        cs = ConversationState(state_type=StateType.GOAL_SETTING)
        assert cs.is_active is True

    def test_is_active_expired(self):
        """期限切れの状態は非アクティブ"""
        past = datetime(2020, 1, 1, tzinfo=timezone.utc)
        cs = ConversationState(state_type=StateType.GOAL_SETTING, expires_at=past)
        assert cs.is_active is False

    def test_is_active_not_expired(self):
        """期限内の状態はアクティブ"""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        cs = ConversationState(state_type=StateType.CONFIRMATION, expires_at=future)
        assert cs.is_active is True

    def test_is_expired_no_expiry(self):
        """expires_at が None なら期限切れでない"""
        cs = ConversationState()
        assert cs.is_expired is False

    def test_is_expired_true(self):
        past = datetime(2020, 1, 1, tzinfo=timezone.utc)
        cs = ConversationState(expires_at=past)
        assert cs.is_expired is True

    def test_is_expired_naive_datetime(self):
        """タイムゾーンなしの過去のdatetimeでも正しく判定"""
        past = datetime(2020, 1, 1)
        cs = ConversationState(expires_at=past)
        assert cs.is_expired is True

    def test_to_dict(self):
        """to_dict の基本テスト (line 655)"""
        cs = ConversationState(
            state_id="st-1",
            organization_id="org-1",
            room_id="room-1",
            user_id="user-1",
            state_type=StateType.GOAL_SETTING,
            state_step="why",
            state_data={"goal_id": "g-1"},
        )
        d = cs.to_dict()
        assert d["state_id"] == "st-1"
        assert d["state_type"] == "goal_setting"
        assert d["state_step"] == "why"
        assert d["is_active"] is True
        assert d["is_expired"] is False


# =============================================================================
# BrainContext テスト (lines 738-745, 749, 761, 770, 782-786, 798-800,
#                       807-810, 814, 818, 822-830, 834-836, 840-842, 847,
#                       851-852)
# =============================================================================


class TestBrainContext:
    """BrainContext dataclass のテスト"""

    def test_defaults(self):
        bc = BrainContext()
        assert bc.current_state is None
        assert bc.recent_conversation == []
        assert bc.person_info == []

    def test_has_active_session_true(self):
        cs = ConversationState(state_type=StateType.GOAL_SETTING)
        bc = BrainContext(current_state=cs)
        assert bc.has_active_session() is True

    def test_has_active_session_false_none(self):
        bc = BrainContext()
        assert bc.has_active_session() is False

    def test_has_active_session_false_normal(self):
        cs = ConversationState(state_type=StateType.NORMAL)
        bc = BrainContext(current_state=cs)
        assert bc.has_active_session() is False

    # --- get_recent_task_names (lines 738-745) ---
    def test_get_recent_task_names_with_taskinfo(self):
        """TaskInfo オブジェクトのリスト (lines 742-743)"""
        tasks = [
            TaskInfo(summary="タスクA"),
            TaskInfo(body="タスクBの本文は長い文章です"),
        ]
        bc = BrainContext(recent_tasks=tasks)
        names = bc.get_recent_task_names()
        assert "タスクA" in names
        assert len(names) == 2

    def test_get_recent_task_names_with_dicts(self):
        """辞書形式のタスク (lines 740-741)"""
        tasks = [
            {"summary": "辞書タスクA", "body": "body"},
            {"body": "辞書タスクBの本文"},
        ]
        bc = BrainContext(recent_tasks=tasks)
        names = bc.get_recent_task_names()
        assert "辞書タスクA" in names
        assert len(names) == 2

    def test_get_recent_task_names_max_5(self):
        """最大5件 (line 739)"""
        tasks = [TaskInfo(summary=f"タスク{i}") for i in range(10)]
        bc = BrainContext(recent_tasks=tasks)
        names = bc.get_recent_task_names()
        assert len(names) == 5

    def test_get_recent_task_names_empty(self):
        bc = BrainContext()
        assert bc.get_recent_task_names() == []

    def test_get_recent_task_names_dict_no_summary(self):
        """summary がない辞書で body の先頭50文字 (line 741)"""
        tasks = [{"body": "A" * 100}]
        bc = BrainContext(recent_tasks=tasks)
        names = bc.get_recent_task_names()
        assert len(names[0]) == 50

    def test_get_recent_task_names_taskinfo_no_summary(self):
        """TaskInfo で summary が None で body がある場合 (line 743)"""
        tasks = [TaskInfo(body="B" * 100)]
        bc = BrainContext(recent_tasks=tasks)
        names = bc.get_recent_task_names()
        assert len(names[0]) == 50

    # --- get_known_persons (line 749) ---
    def test_get_known_persons(self):
        """人物名リストの取得 (line 749)"""
        persons = [PersonInfo(name="田中"), PersonInfo(name="山田")]
        bc = BrainContext(person_info=persons)
        assert bc.get_known_persons() == ["田中", "山田"]

    def test_get_known_persons_empty(self):
        bc = BrainContext()
        assert bc.get_known_persons() == []

    # --- has_multimodal_content (line 761) ---
    def test_has_multimodal_content_none(self):
        bc = BrainContext()
        assert bc.has_multimodal_content() is False

    def test_has_multimodal_content_with_attr(self):
        """multimodal_context に has_multimodal_content 属性がある場合 (line 761)"""
        mock_ctx = MagicMock()
        mock_ctx.has_multimodal_content = True
        bc = BrainContext(multimodal_context=mock_ctx)
        assert bc.has_multimodal_content() is True

    def test_has_multimodal_content_without_attr(self):
        """属性がないオブジェクトの場合は False"""
        bc = BrainContext(multimodal_context="plain_string")
        # getattr fallback to False
        assert bc.has_multimodal_content() is False

    # --- has_generation_request (line 770) ---
    def test_has_generation_request_none(self):
        bc = BrainContext()
        assert bc.has_generation_request() is False

    def test_has_generation_request_present(self):
        """generation_request が設定されている場合 (line 770)"""
        bc = BrainContext(generation_request={"type": "image"})
        assert bc.has_generation_request() is True

    # --- get_multimodal_summary (lines 782-786) ---
    def test_get_multimodal_summary_no_content(self):
        bc = BrainContext()
        assert bc.get_multimodal_summary() == ""

    def test_get_multimodal_summary_with_context(self):
        """to_prompt_context() を持つコンテキスト (lines 783-785)"""
        mock_ctx = MagicMock()
        mock_ctx.has_multimodal_content = True
        mock_ctx.to_prompt_context.return_value = "画像の要約"
        bc = BrainContext(multimodal_context=mock_ctx)
        assert bc.get_multimodal_summary() == "画像の要約"

    def test_get_multimodal_summary_none_result(self):
        """to_prompt_context() が None を返す場合 (line 785)"""
        mock_ctx = MagicMock()
        mock_ctx.has_multimodal_content = True
        mock_ctx.to_prompt_context.return_value = None
        bc = BrainContext(multimodal_context=mock_ctx)
        assert bc.get_multimodal_summary() == ""

    def test_get_multimodal_summary_no_method(self):
        """to_prompt_context メソッドがない場合 (line 786)"""
        mock_ctx = MagicMock(spec=[])  # spec=[] means no attributes
        # has_multimodal_content を外から設定
        # spec=[] の場合 getattr で False が返る → has_multimodal_content() が False
        bc = BrainContext(multimodal_context=mock_ctx)
        assert bc.get_multimodal_summary() == ""

    def test_get_multimodal_summary_has_content_but_no_to_prompt(self):
        """has_multimodal_content=True だが to_prompt_context がないオブジェクト (line 786)"""
        # has_multimodal_content が True を返すが to_prompt_context を持たないオブジェクト
        class FakeCtx:
            has_multimodal_content = True
        bc = BrainContext(multimodal_context=FakeCtx())
        # has_multimodal_content() は getattr で True を取得
        # しかし hasattr(ctx, 'to_prompt_context') が False → line 786 の return "" に到達
        assert bc.get_multimodal_summary() == ""

    # --- to_prompt_context (lines 798-800, 807-810, 814, 818, 822-830,
    #                         834-836, 840-842, 847, 851-852) ---
    def test_to_prompt_context_minimal(self):
        bc = BrainContext(sender_name="テスト太郎")
        result = bc.to_prompt_context()
        assert "【送信者】テスト太郎" in result

    def test_to_prompt_context_with_active_state(self):
        """アクティブな状態がある場合 (lines 798-800)"""
        cs = ConversationState(
            state_type=StateType.GOAL_SETTING,
            state_step="why",
        )
        bc = BrainContext(current_state=cs, sender_name="太郎")
        result = bc.to_prompt_context()
        assert "【現在の状態】goal_setting" in result
        assert "ステップ: why" in result

    def test_to_prompt_context_with_conversation(self):
        """直近の会話がある場合 (lines 807-810)"""
        ts = datetime.now()
        msgs = [
            ConversationMessage(role="user", content="こんにちは", timestamp=ts),
            ConversationMessage(role="assistant", content="こんにちは！", timestamp=ts),
        ]
        bc = BrainContext(recent_conversation=msgs, sender_name="太郎")
        result = bc.to_prompt_context()
        assert "【直近の会話】" in result
        assert "ユーザー: こんにちは" in result
        assert "ソウルくん: こんにちは！" in result

    def test_to_prompt_context_with_summary(self):
        """会話要約がある場合 (line 814)"""
        sd = SummaryData(
            summary="テスト",
            key_topics=["話題A", "話題B"],
            mentioned_persons=[],
            mentioned_tasks=[],
            created_at=datetime.now(),
        )
        bc = BrainContext(conversation_summary=sd, sender_name="太郎")
        result = bc.to_prompt_context()
        assert "【過去の話題】話題A, 話題B" in result

    def test_to_prompt_context_with_preferences(self):
        """ユーザー嗜好がある場合 (line 818)"""
        pref = PreferenceData(response_style="formal")
        bc = BrainContext(user_preferences=pref, sender_name="太郎")
        result = bc.to_prompt_context()
        assert "【応答スタイル】formal" in result

    def test_to_prompt_context_with_preferences_no_style(self):
        """response_style が None の場合は表示しない"""
        pref = PreferenceData()
        bc = BrainContext(user_preferences=pref, sender_name="太郎")
        result = bc.to_prompt_context()
        assert "応答スタイル" not in result

    def test_to_prompt_context_with_tasks_taskinfo(self):
        """TaskInfo オブジェクトのタスク (lines 827-830)"""
        tasks = [
            TaskInfo(summary="タスクA", status="open"),
            TaskInfo(body="タスクBの本文", status="done"),
        ]
        bc = BrainContext(recent_tasks=tasks, sender_name="太郎")
        result = bc.to_prompt_context()
        assert "【関連タスク】" in result
        assert "タスクA (open)" in result

    def test_to_prompt_context_with_tasks_dict(self):
        """辞書形式のタスク (lines 824-826)"""
        tasks = [
            {"summary": "辞書タスク", "status": "open"},
            {"body": "辞書タスクB本文", "status": "done"},
        ]
        bc = BrainContext(recent_tasks=tasks, sender_name="太郎")
        result = bc.to_prompt_context()
        assert "【関連タスク】" in result
        assert "辞書タスク (open)" in result

    def test_to_prompt_context_with_goals(self):
        """目標がある場合 (lines 834-836)"""
        goals = [GoalInfo(what="売上2倍")]
        bc = BrainContext(active_goals=goals, sender_name="太郎")
        result = bc.to_prompt_context()
        assert "【進行中の目標】" in result
        assert "売上2倍" in result

    def test_to_prompt_context_with_ceo_teachings(self):
        """CEO教えがある場合 (lines 840-842)"""
        teaching = CEOTeaching(statement="お客様第一")
        ctx = CEOTeachingContext(relevant_teachings=[teaching])
        bc = BrainContext(ceo_teachings=ctx, sender_name="太郎")
        result = bc.to_prompt_context()
        assert "【会社の教え】" in result
        assert "お客様第一" in result

    def test_to_prompt_context_with_multimodal(self):
        """マルチモーダルコンテキストがある場合 (line 847)"""
        mock_ctx = MagicMock()
        mock_ctx.has_multimodal_content = True
        mock_ctx.to_prompt_context.return_value = "【画像分析】テスト画像"
        bc = BrainContext(multimodal_context=mock_ctx, sender_name="太郎")
        result = bc.to_prompt_context()
        assert "【画像分析】テスト画像" in result

    def test_to_prompt_context_with_persons(self):
        """記憶している人物がある場合 (lines 851-852)"""
        persons = [PersonInfo(name="田中"), PersonInfo(name="山田")]
        bc = BrainContext(person_info=persons, sender_name="太郎")
        result = bc.to_prompt_context()
        assert "【記憶している人物】田中, 山田" in result

    # --- to_dict (lines 865-867) ---
    def test_to_dict(self):
        """BrainContext.to_dict() の基本テスト (lines 865-867)"""
        ts = datetime.now()
        bc = BrainContext(
            sender_name="テスト太郎",
            sender_account_id="acc-1",
            organization_id="org-1",
            room_id="room-1",
            timestamp=ts,
        )
        d = bc.to_dict()
        assert d["sender_name"] == "テスト太郎"
        assert d["sender_account_id"] == "acc-1"
        assert d["organization_id"] == "org-1"
        assert d["room_id"] == "room-1"
        assert d["current_state"] is None
        assert d["conversation_summary"] is None
        assert d["user_preferences"] is None
        assert d["goal_session"] is None
        assert isinstance(d["recent_conversation"], list)
        assert isinstance(d["person_info"], list)
        assert isinstance(d["recent_tasks"], list)
        assert isinstance(d["active_goals"], list)
        assert isinstance(d["insights"], list)

    def test_to_dict_with_nested_objects(self):
        """ネストされたオブジェクトを含む BrainContext.to_dict()"""
        ts = datetime.now()
        bc = BrainContext(
            current_state=ConversationState(state_type=StateType.GOAL_SETTING),
            recent_conversation=[
                ConversationMessage(role="user", content="test", timestamp=ts),
            ],
            conversation_summary=SummaryData(
                summary="要約",
                key_topics=["A"],
                mentioned_persons=[],
                mentioned_tasks=[],
                created_at=ts,
            ),
            user_preferences=PreferenceData(response_style="formal"),
            person_info=[PersonInfo(name="田中")],
            recent_tasks=[TaskInfo(task_id="t-1")],
            active_goals=[GoalInfo(goal_id="g-1")],
            goal_session=GoalSessionInfo(session_id="s-1", current_step="why"),
            insights=[
                InsightInfo(
                    insight_id="i-1",
                    insight_type="test",
                    title="T",
                    description="D",
                    severity="low",
                    created_at=ts,
                )
            ],
            sender_name="太郎",
            organization_id="org-1",
            room_id="room-1",
            timestamp=ts,
        )
        d = bc.to_dict()
        assert d["current_state"] is not None
        assert len(d["recent_conversation"]) == 1
        assert d["conversation_summary"] is not None
        assert d["user_preferences"] is not None
        assert d["goal_session"] is not None
        assert len(d["insights"]) == 1


# =============================================================================
# ResolvedEntity テスト (line 902)
# =============================================================================


class TestResolvedEntity:
    """ResolvedEntity dataclass のテスト"""

    def test_to_dict(self):
        """to_dict の基本テスト (line 902)"""
        re = ResolvedEntity(
            original="菊地さん",
            resolved="菊地太郎",
            entity_type="person",
            source="memory",
            confidence=0.95,
        )
        d = re.to_dict()
        assert d["original"] == "菊地さん"
        assert d["resolved"] == "菊地太郎"
        assert d["entity_type"] == "person"
        assert d["source"] == "memory"
        assert d["confidence"] == 0.95


# =============================================================================
# UnderstandingResult テスト (lines 952, 956)
# =============================================================================


class TestUnderstandingResult:
    """UnderstandingResult dataclass のテスト"""

    def test_confidence_level_property(self):
        """confidence_level プロパティ (line 952)"""
        ur = UnderstandingResult(
            raw_message="テスト",
            intent="search_tasks",
            intent_confidence=0.85,
        )
        assert ur.confidence_level == ConfidenceLevel.HIGH

    def test_to_dict(self):
        """to_dict の基本テスト (line 956)"""
        re = ResolvedEntity(
            original="テスト",
            resolved="テスト解決",
            entity_type="task",
            source="db",
        )
        ur = UnderstandingResult(
            raw_message="タスクを検索",
            intent="search_tasks",
            intent_confidence=0.8,
            entities={"task": "経費精算"},
            resolved_ambiguities=[re],
            needs_confirmation=True,
            confirmation_reason="確認理由",
            confirmation_options=["A", "B"],
            reasoning="推論理由",
            processing_time_ms=150,
        )
        d = ur.to_dict()
        assert d["raw_message"] == "タスクを検索"
        assert d["intent"] == "search_tasks"
        assert d["intent_confidence"] == 0.8
        assert d["confidence_level"] == "high"
        assert d["needs_confirmation"] is True
        assert len(d["resolved_ambiguities"]) == 1
        assert d["processing_time_ms"] == 150


# =============================================================================
# ActionCandidate テスト (line 987)
# =============================================================================


class TestActionCandidate:
    """ActionCandidate dataclass のテスト"""

    def test_to_dict(self):
        """to_dict の基本テスト (line 987)"""
        ac = ActionCandidate(
            action="search_tasks",
            score=0.9,
            params={"query": "経費"},
            reasoning="キーワードマッチ",
        )
        d = ac.to_dict()
        assert d["action"] == "search_tasks"
        assert d["score"] == 0.9
        assert d["params"] == {"query": "経費"}
        assert d["reasoning"] == "キーワードマッチ"


# =============================================================================
# DecisionResult テスト (line 1026)
# =============================================================================


class TestDecisionResult:
    """DecisionResult dataclass のテスト"""

    def test_to_dict(self):
        """to_dict の基本テスト (line 1026)"""
        candidate = ActionCandidate(action="alt_action", score=0.5)
        dr = DecisionResult(
            action="search_tasks",
            params={"q": "test"},
            confidence=0.85,
            needs_confirmation=True,
            confirmation_question="これでいいですか？",
            confirmation_options=["はい", "いいえ"],
            other_candidates=[candidate],
            reasoning="テスト理由",
            processing_time_ms=200,
        )
        d = dr.to_dict()
        assert d["action"] == "search_tasks"
        assert d["confidence"] == 0.85
        assert d["needs_confirmation"] is True
        assert d["confirmation_question"] == "これでいいですか？"
        assert len(d["other_candidates"]) == 1
        assert d["processing_time_ms"] == 200


# =============================================================================
# HandlerResult テスト (line 1073)
# =============================================================================


class TestHandlerResult:
    """HandlerResult dataclass のテスト"""

    def test_to_dict(self):
        """to_dict の基本テスト (line 1073)"""
        hr = HandlerResult(
            success=True,
            message="タスクを作成しました",
            data={"task_id": "t-1"},
            next_action="notify",
            next_params={"target": "user-1"},
            update_state={"type": "task_pending"},
            suggestions=["他のタスクも？"],
            error_code=None,
            error_details=None,
        )
        d = hr.to_dict()
        assert d["success"] is True
        assert d["message"] == "タスクを作成しました"
        assert d["next_action"] == "notify"
        assert d["suggestions"] == ["他のタスクも？"]


# =============================================================================
# ConfirmationRequest テスト (line 1119)
# =============================================================================


class TestConfirmationRequest:
    """ConfirmationRequest dataclass のテスト"""

    def test_to_message(self):
        cr = ConfirmationRequest(
            question="どちらの意味ですか？",
            options=["選択肢A", "選択肢B"],
        )
        msg = cr.to_message()
        assert "どちらの意味ですか？" in msg
        assert "1. 選択肢A" in msg
        assert "2. 選択肢B" in msg

    def test_to_dict(self):
        """to_dict の基本テスト (line 1119)"""
        cr = ConfirmationRequest(
            question="確認質問",
            options=["A", "B"],
            default_option="A",
            timeout_seconds=600,
            on_confirm_action="create_task",
            on_confirm_params={"title": "タスク"},
        )
        d = cr.to_dict()
        assert d["question"] == "確認質問"
        assert d["options"] == ["A", "B"]
        assert d["default_option"] == "A"
        assert d["timeout_seconds"] == 600
        assert d["on_confirm_action"] == "create_task"
        assert d["on_confirm_params"] == {"title": "タスク"}


# =============================================================================
# BrainResponse テスト (line 1170)
# =============================================================================


class TestBrainResponse:
    """BrainResponse dataclass のテスト"""

    def test_to_dict(self):
        """to_dict の基本テスト (line 1170)"""
        br = BrainResponse(
            message="タスクを作成したウル！",
            action_taken="create_task",
            action_params={"title": "テスト"},
            success=True,
            suggestions=["他にもありますか？"],
            state_changed=True,
            new_state="task_pending",
            awaiting_confirmation=False,
            debug_info={"ms": 100},
            total_time_ms=150,
        )
        d = br.to_dict()
        assert d["message"] == "タスクを作成したウル！"
        assert d["action_taken"] == "create_task"
        assert d["success"] is True
        assert d["state_changed"] is True
        assert d["new_state"] == "task_pending"
        assert d["total_time_ms"] == 150


# =============================================================================
# CEOTeaching テスト (line 1365)
# =============================================================================


class TestCEOTeaching:
    """CEOTeaching dataclass のテスト"""

    def test_defaults(self):
        t = CEOTeaching()
        assert t.id is None
        assert t.statement == ""
        assert t.category == TeachingCategory.OTHER
        assert t.validation_status == ValidationStatus.PENDING
        assert t.priority == 5
        assert t.is_active is True
        assert t.usage_count == 0

    def test_is_relevant_to_keyword(self):
        t = CEOTeaching(keywords=["営業", "売上"])
        assert t.is_relevant_to("営業のコツ") is True
        assert t.is_relevant_to("プログラミング") is False

    def test_is_relevant_to_statement(self):
        t = CEOTeaching(statement="お客様第一で行動すること")
        assert t.is_relevant_to("お客様") is True
        assert t.is_relevant_to("全く関係ない") is False

    def test_is_relevant_to_reverse_match(self):
        """トピックがキーワードに含まれる場合"""
        t = CEOTeaching(keywords=["営業戦略"])
        assert t.is_relevant_to("営業") is True

    def test_to_prompt_context(self):
        t = CEOTeaching(
            category=TeachingCategory.MVV_MISSION,
            statement="ミッション第一",
            reasoning="会社の核",
            target="全員",
        )
        result = t.to_prompt_context()
        assert "【mvv_mission】ミッション第一" in result
        assert "理由: 会社の核" in result
        assert "対象: 全員" in result

    def test_to_prompt_context_no_optional(self):
        t = CEOTeaching(
            category=TeachingCategory.OTHER,
            statement="テスト教え",
        )
        result = t.to_prompt_context()
        assert "【other】テスト教え" in result
        assert "理由:" not in result

    def test_to_dict(self):
        """to_dict の基本テスト (line 1365)"""
        t = CEOTeaching(
            id="teach-1",
            organization_id="org-1",
            statement="教えのテスト",
            category=TeachingCategory.CULTURE,
            validation_status=ValidationStatus.VERIFIED,
        )
        d = t.to_dict()
        assert d["id"] == "teach-1"
        assert d["organization_id"] == "org-1"
        assert d["statement"] == "教えのテスト"
        assert d["category"] == "culture"
        assert d["validation_status"] == "verified"

    def test_to_dict_with_dates(self):
        ts = datetime(2026, 2, 1, 12, 0, 0)
        t = CEOTeaching(
            last_used_at=ts,
            extracted_at=ts,
            created_at=ts,
            updated_at=ts,
        )
        d = t.to_dict()
        assert d["last_used_at"] == ts.isoformat()
        assert d["extracted_at"] == ts.isoformat()
        assert d["created_at"] == ts.isoformat()

    def test_to_dict_none_dates(self):
        t = CEOTeaching(last_used_at=None)
        d = t.to_dict()
        assert d["last_used_at"] is None


# =============================================================================
# ConflictInfo テスト (line 1434)
# =============================================================================


class TestConflictInfo:
    """ConflictInfo dataclass のテスト"""

    def test_defaults(self):
        ci = ConflictInfo()
        assert ci.conflict_type == ConflictType.MVV
        assert ci.severity == Severity.MEDIUM

    def test_to_alert_summary_high(self):
        ci = ConflictInfo(
            severity=Severity.HIGH,
            conflict_type=ConflictType.MVV,
            description="ミッションと矛盾",
        )
        result = ci.to_alert_summary()
        assert "[mvv]" in result
        assert "ミッションと矛盾" in result

    def test_to_alert_summary_medium(self):
        ci = ConflictInfo(severity=Severity.MEDIUM, description="解釈の余地")
        result = ci.to_alert_summary()
        assert "解釈の余地" in result

    def test_to_alert_summary_low(self):
        ci = ConflictInfo(severity=Severity.LOW, description="軽微な不整合")
        result = ci.to_alert_summary()
        assert "軽微な不整合" in result

    def test_to_dict(self):
        """to_dict の基本テスト (line 1434)"""
        ci = ConflictInfo(
            id="conf-1",
            organization_id="org-1",
            teaching_id="teach-1",
            conflict_type=ConflictType.CHOICE_THEORY,
            severity=Severity.HIGH,
            description="矛盾の説明",
        )
        d = ci.to_dict()
        assert d["id"] == "conf-1"
        assert d["conflict_type"] == "choice_theory"
        assert d["severity"] == "high"
        assert d["description"] == "矛盾の説明"


# =============================================================================
# GuardianAlert テスト (lines 1492, 1498, 1542)
# =============================================================================


class TestGuardianAlert:
    """GuardianAlert dataclass のテスト"""

    def test_defaults(self):
        ga = GuardianAlert()
        assert ga.status == AlertStatus.PENDING
        assert ga.conflicts == []

    def test_is_resolved_pending(self):
        ga = GuardianAlert(status=AlertStatus.PENDING)
        assert ga.is_resolved is False

    def test_is_resolved_acknowledged(self):
        ga = GuardianAlert(status=AlertStatus.ACKNOWLEDGED)
        assert ga.is_resolved is True

    def test_is_resolved_overridden(self):
        ga = GuardianAlert(status=AlertStatus.OVERRIDDEN)
        assert ga.is_resolved is True

    # --- max_severity (lines 1492, 1498) ---
    def test_max_severity_no_conflicts(self):
        """矛盾がない場合は LOW (line 1492)"""
        ga = GuardianAlert()
        assert ga.max_severity == Severity.LOW

    def test_max_severity_high(self):
        conflicts = [
            ConflictInfo(severity=Severity.LOW),
            ConflictInfo(severity=Severity.HIGH),
        ]
        ga = GuardianAlert(conflicts=conflicts)
        assert ga.max_severity == Severity.HIGH

    def test_max_severity_medium(self):
        conflicts = [
            ConflictInfo(severity=Severity.LOW),
            ConflictInfo(severity=Severity.MEDIUM),
        ]
        ga = GuardianAlert(conflicts=conflicts)
        assert ga.max_severity == Severity.MEDIUM

    def test_max_severity_low_only(self):
        """LOW のみの場合 (line 1498)"""
        conflicts = [ConflictInfo(severity=Severity.LOW)]
        ga = GuardianAlert(conflicts=conflicts)
        assert ga.max_severity == Severity.LOW

    def test_generate_alert_message(self):
        teaching = CEOTeaching(statement="テスト教え")
        ga = GuardianAlert(
            conflict_summary="ミッションと矛盾しています",
            alternative_suggestion="こう言い換えてはどうでしょう",
        )
        msg = ga.generate_alert_message(teaching)
        assert "テスト教え" in msg
        assert "ミッションと矛盾しています" in msg
        assert "こんな言い方はどうウル？" in msg
        assert "こう言い換えてはどうでしょう" in msg

    def test_generate_alert_message_no_alternative(self):
        teaching = CEOTeaching(statement="短い教え")
        ga = GuardianAlert(conflict_summary="矛盾あり")
        msg = ga.generate_alert_message(teaching)
        assert "短い教え" in msg
        assert "こんな言い方はどうウル？" not in msg

    def test_to_dict(self):
        """to_dict の基本テスト (line 1542)"""
        ga = GuardianAlert(
            id="alert-1",
            organization_id="org-1",
            teaching_id="teach-1",
            status=AlertStatus.OVERRIDDEN,
            conflicts=[ConflictInfo(severity=Severity.HIGH)],
        )
        d = ga.to_dict()
        assert d["id"] == "alert-1"
        assert d["status"] == "overridden"
        assert d["is_resolved"] is True
        assert d["max_severity"] == "high"
        assert len(d["conflicts"]) == 1

    def test_to_dict_with_dates(self):
        ts = datetime(2026, 2, 1, 12, 0, 0)
        ga = GuardianAlert(
            resolved_at=ts,
            notified_at=ts,
            created_at=ts,
            updated_at=ts,
        )
        d = ga.to_dict()
        assert d["resolved_at"] == ts.isoformat()
        assert d["notified_at"] == ts.isoformat()


# =============================================================================
# TeachingValidationResult テスト (lines 1610-1616, 1620)
# =============================================================================


class TestTeachingValidationResult:
    """TeachingValidationResult dataclass のテスト"""

    def test_defaults(self):
        t = CEOTeaching()
        tvr = TeachingValidationResult(teaching=t)
        assert tvr.is_valid is True
        assert tvr.overall_score == 1.0

    def test_should_alert_invalid(self):
        t = CEOTeaching()
        tvr = TeachingValidationResult(teaching=t, is_valid=False)
        assert tvr.should_alert() is True

    def test_should_alert_high_severity(self):
        t = CEOTeaching()
        conflict = ConflictInfo(severity=Severity.HIGH)
        tvr = TeachingValidationResult(teaching=t, conflicts=[conflict])
        assert tvr.should_alert() is True

    def test_should_alert_low_score(self):
        t = CEOTeaching()
        tvr = TeachingValidationResult(teaching=t, overall_score=0.3)
        assert tvr.should_alert() is True

    def test_should_alert_false(self):
        t = CEOTeaching()
        tvr = TeachingValidationResult(teaching=t, is_valid=True, overall_score=0.8)
        assert tvr.should_alert() is False

    # --- get_alert_reason (lines 1610-1616) ---
    def test_get_alert_reason_no_conflicts(self):
        """矛盾がない場合のデフォルトメッセージ (line 1611)"""
        t = CEOTeaching()
        tvr = TeachingValidationResult(teaching=t)
        assert tvr.get_alert_reason() == "検証結果に問題がありました"

    def test_get_alert_reason_high_conflict(self):
        """高深刻度の矛盾がある場合 (lines 1613-1615)"""
        t = CEOTeaching()
        conflict_high = ConflictInfo(severity=Severity.HIGH, description="重大な矛盾")
        conflict_low = ConflictInfo(severity=Severity.LOW, description="軽微な矛盾")
        tvr = TeachingValidationResult(
            teaching=t, conflicts=[conflict_low, conflict_high]
        )
        assert tvr.get_alert_reason() == "重大な矛盾"

    def test_get_alert_reason_no_high_conflict(self):
        """高深刻度がない場合は最初の矛盾 (line 1616)"""
        t = CEOTeaching()
        conflict = ConflictInfo(severity=Severity.MEDIUM, description="中程度の矛盾")
        tvr = TeachingValidationResult(teaching=t, conflicts=[conflict])
        assert tvr.get_alert_reason() == "中程度の矛盾"

    # --- to_dict (line 1620) ---
    def test_to_dict(self):
        """to_dict の基本テスト (line 1620)"""
        t = CEOTeaching(statement="テスト教え")
        tvr = TeachingValidationResult(
            teaching=t,
            is_valid=False,
            validation_status=ValidationStatus.ALERT_PENDING,
            mvv_alignment_score=0.3,
            theory_alignment_score=0.4,
            overall_score=0.35,
            recommended_action="alert",
            alternative_suggestion="代替案",
            validation_time_ms=100,
        )
        d = tvr.to_dict()
        assert d["is_valid"] is False
        assert d["validation_status"] == "alert_pending"
        assert d["mvv_alignment_score"] == 0.3
        assert d["recommended_action"] == "alert"
        assert d["alternative_suggestion"] == "代替案"
        assert d["teaching"]["statement"] == "テスト教え"


# =============================================================================
# TeachingUsageContext テスト (line 1665)
# =============================================================================


class TestTeachingUsageContext:
    """TeachingUsageContext dataclass のテスト"""

    def test_to_dict(self):
        """to_dict の基本テスト (line 1665)"""
        tuc = TeachingUsageContext(
            teaching_id="teach-1",
            organization_id="org-1",
            room_id="room-1",
            account_id="acc-1",
            user_message="テストメッセージ",
            response_excerpt="応答の一部",
            relevance_score=0.9,
            selection_reasoning="キーワードマッチ",
            was_helpful=True,
            feedback="役に立った",
        )
        d = tuc.to_dict()
        assert d["teaching_id"] == "teach-1"
        assert d["organization_id"] == "org-1"
        assert d["relevance_score"] == 0.9
        assert d["was_helpful"] is True
        assert d["feedback"] == "役に立った"
        assert "used_at" in d


# =============================================================================
# CEOTeachingContext テスト (lines 1713, 1725)
# =============================================================================


class TestCEOTeachingContext:
    """CEOTeachingContext dataclass のテスト"""

    def test_defaults(self):
        ctx = CEOTeachingContext()
        assert ctx.relevant_teachings == []
        assert ctx.pending_alerts == []
        assert ctx.is_ceo_user is False

    def test_get_top_teachings(self):
        teachings = [
            CEOTeaching(statement=f"教え{i}") for i in range(5)
        ]
        ctx = CEOTeachingContext(relevant_teachings=teachings)
        top = ctx.get_top_teachings(3)
        assert len(top) == 3
        assert top[0].statement == "教え0"

    def test_has_pending_alerts_true(self):
        ctx = CEOTeachingContext(pending_alerts=[GuardianAlert()])
        assert ctx.has_pending_alerts() is True

    def test_has_pending_alerts_false(self):
        ctx = CEOTeachingContext()
        assert ctx.has_pending_alerts() is False

    # --- to_prompt_context (line 1713) ---
    def test_to_prompt_context_empty(self):
        """教えがない場合は空文字 (line 1713)"""
        ctx = CEOTeachingContext()
        assert ctx.to_prompt_context() == ""

    def test_to_prompt_context_with_teachings(self):
        teachings = [
            CEOTeaching(statement="教えA", reasoning="理由A"),
            CEOTeaching(statement="教えB"),
        ]
        ctx = CEOTeachingContext(relevant_teachings=teachings)
        result = ctx.to_prompt_context()
        assert "【会社の教え】" in result
        assert "教えA" in result
        assert "（理由A）" in result
        assert "教えB" in result

    def test_to_prompt_context_max_3(self):
        teachings = [CEOTeaching(statement=f"教え{i}") for i in range(5)]
        ctx = CEOTeachingContext(relevant_teachings=teachings)
        result = ctx.to_prompt_context()
        assert "教え0" in result
        assert "教え2" in result
        assert "教え3" not in result

    # --- to_dict (line 1725) ---
    def test_to_dict(self):
        """to_dict の基本テスト (line 1725)"""
        teaching = CEOTeaching(statement="教えテスト")
        alert = GuardianAlert(id="alert-1")
        ctx = CEOTeachingContext(
            relevant_teachings=[teaching],
            pending_alerts=[alert],
            is_ceo_user=True,
            ceo_user_id="ceo-1",
            total_teachings_count=10,
            active_teachings_count=8,
        )
        d = ctx.to_dict()
        assert len(d["relevant_teachings"]) == 1
        assert len(d["pending_alerts"]) == 1
        assert d["is_ceo_user"] is True
        assert d["ceo_user_id"] == "ceo-1"
        assert d["total_teachings_count"] == 10
        assert d["active_teachings_count"] == 8


# =============================================================================
# ProactiveMessageResult テスト
# =============================================================================


class TestProactiveMessageResult:
    """ProactiveMessageResult dataclass のテスト"""

    def test_defaults(self):
        pmr = ProactiveMessageResult(should_send=False)
        assert pmr.should_send is False
        assert pmr.message is None
        assert pmr.confidence == 0.0
        assert pmr.tone == ProactiveMessageTone.FRIENDLY

    def test_to_dict(self):
        pmr = ProactiveMessageResult(
            should_send=True,
            message="お疲れ様ウル！",
            reason="退勤時間",
            confidence=0.9,
            tone=ProactiveMessageTone.ENCOURAGING,
            context_used={"trigger": "time"},
            debug_info={"model": "gpt"},
        )
        d = pmr.to_dict()
        assert d["should_send"] is True
        assert d["message"] == "お疲れ様ウル！"
        assert d["tone"] == "encouraging"
        assert d["confidence"] == 0.9


# =============================================================================
# Phase 2D Enum テスト
# =============================================================================


class TestPhase2DEnums:
    """Phase 2D 関連 Enum のテスト"""

    def test_teaching_category_values(self):
        assert TeachingCategory.MVV_MISSION == "mvv_mission"
        assert TeachingCategory.OTHER == "other"
        assert TeachingCategory.COMMUNICATION == "communication"

    def test_validation_status_values(self):
        assert ValidationStatus.PENDING == "pending"
        assert ValidationStatus.VERIFIED == "verified"
        assert ValidationStatus.ALERT_PENDING == "alert_pending"
        assert ValidationStatus.OVERRIDDEN == "overridden"

    def test_conflict_type_values(self):
        assert ConflictType.MVV == "mvv"
        assert ConflictType.EXISTING == "existing"

    def test_alert_status_values(self):
        assert AlertStatus.PENDING == "pending"
        assert AlertStatus.ACKNOWLEDGED == "acknowledged"
        assert AlertStatus.OVERRIDDEN == "overridden"
        assert AlertStatus.RETRACTED == "retracted"

    def test_severity_values(self):
        assert Severity.HIGH == "high"
        assert Severity.MEDIUM == "medium"
        assert Severity.LOW == "low"

    def test_proactive_message_tone_values(self):
        assert ProactiveMessageTone.FRIENDLY == "friendly"
        assert ProactiveMessageTone.ENCOURAGING == "encouraging"
        assert ProactiveMessageTone.CONCERNED == "concerned"
        assert ProactiveMessageTone.CELEBRATORY == "celebratory"
        assert ProactiveMessageTone.REMINDER == "reminder"
        assert ProactiveMessageTone.SUPPORTIVE == "supportive"
