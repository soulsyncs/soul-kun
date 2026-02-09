"""
Phase 2M: 対人力強化（Interpersonal Skills）のテスト

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2M
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call
from datetime import datetime, timedelta, timezone

from lib.brain.interpersonal import (
    # Main class
    BrainInterpersonal,
    create_interpersonal,
    is_interpersonal_enabled,
    # Components
    CommunicationStyleAdapter,
    MotivationEngine,
    CounselEngine,
    ConflictMediator,
    # Models
    CommunicationProfile,
    MotivationProfile,
    FeedbackOpportunity,
    ConflictLog,
    InterpersonalResult,
    # Enums
    InterpersonalStyleType,
    PreferredTiming,
    MotivationType,
    DiscouragementSignal,
    FeedbackType,
    ReceptivenessLevel,
    ConflictSeverity,
    ConflictStatus,
    # Constants
    RECEPTIVENESS_HIGH_THRESHOLD,
    RECEPTIVENESS_LOW_THRESHOLD,
    DISCOURAGEMENT_CONFIDENCE_THRESHOLD,
    MIN_FEEDBACK_INTERVAL_HOURS,
    CONFLICT_MIN_EVIDENCE_COUNT,
    FEATURE_FLAG_INTERPERSONAL_ENABLED,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_conn():
    """Mock DB connection"""
    conn = MagicMock()
    conn.execute = MagicMock()
    return conn


@pytest.fixture
def interpersonal():
    """BrainInterpersonal instance"""
    return BrainInterpersonal(organization_id="org_test_123")


@pytest.fixture
def style_adapter():
    """CommunicationStyleAdapter instance"""
    return CommunicationStyleAdapter(organization_id="org_test_123")


@pytest.fixture
def motivation_engine():
    """MotivationEngine instance"""
    return MotivationEngine(organization_id="org_test_123")


@pytest.fixture
def counsel_engine():
    """CounselEngine instance"""
    return CounselEngine(organization_id="org_test_123")


@pytest.fixture
def conflict_mediator():
    """ConflictMediator instance"""
    return ConflictMediator(organization_id="org_test_123")


@pytest.fixture
def sample_profile():
    """Sample communication profile"""
    return CommunicationProfile(
        organization_id="org_test_123",
        user_id="user_001",
        preferred_length=InterpersonalStyleType.BRIEF,
        formality_level=InterpersonalStyleType.CASUAL,
        preferred_timing=PreferredTiming.MORNING,
        interaction_count=10,
        confidence_score=0.8,
    )


@pytest.fixture
def sample_motivation_profile():
    """Sample motivation profile"""
    return MotivationProfile(
        organization_id="org_test_123",
        user_id="user_001",
        primary_type=MotivationType.ACHIEVEMENT,
        secondary_type=MotivationType.GROWTH,
        key_values=["progress", "milestones"],
        discouragement_triggers=["missed_deadline", "negative_language"],
        sample_count=20,
        confidence_score=0.75,
    )


# =============================================================================
# Test: BrainInterpersonal (統合クラス)
# =============================================================================

class TestBrainInterpersonal:
    """統合クラスのテスト"""

    def test_initialization(self, interpersonal):
        """正常に初期化できること"""
        assert interpersonal.organization_id == "org_test_123"
        assert interpersonal.style_adapter is not None
        assert interpersonal.motivation_engine is not None
        assert interpersonal.counsel_engine is not None
        assert interpersonal.conflict_mediator is not None

    def test_initialization_requires_org_id(self):
        """organization_idなしで初期化するとエラー"""
        with pytest.raises(ValueError, match="organization_id is required"):
            BrainInterpersonal(organization_id="")

    def test_initialization_with_disabled_components(self):
        """コンポーネントを無効化して初期化"""
        inst = BrainInterpersonal(
            organization_id="org_test",
            enable_counsel=False,
            enable_motivation=False,
            enable_conflict_detection=False,
        )
        assert inst.style_adapter is not None  # 常に有効
        assert inst.motivation_engine is None
        assert inst.counsel_engine is None
        assert inst.conflict_mediator is None

    def test_disabled_motivation_returns_safe_defaults(self):
        """無効化されたmotivation_engineは安全なデフォルトを返す"""
        inst = BrainInterpersonal(
            organization_id="org_test",
            enable_motivation=False,
        )
        result = inst.detect_discouragement([DiscouragementSignal.DELAYED_RESPONSE])
        assert result["is_discouraged"] is False
        assert result["confidence"] == 0.0

    def test_disabled_counsel_returns_safe_defaults(self):
        """無効化されたcounsel_engineは安全なデフォルトを返す"""
        inst = BrainInterpersonal(
            organization_id="org_test",
            enable_counsel=False,
        )
        result = inst.assess_receptiveness({"is_busy": True})
        assert result["score"] == 0.5
        assert result["level"] == "medium"

    def test_disabled_conflict_returns_safe_defaults(self):
        """無効化されたconflict_mediatorは安全なデフォルトを返す"""
        inst = BrainInterpersonal(
            organization_id="org_test",
            enable_conflict_detection=False,
        )
        result = inst.detect_conflict({"disagreement_count": 5})
        assert result["is_conflict"] is False


# =============================================================================
# Test: Factory & Feature Flag
# =============================================================================

class TestFactoryAndFlags:
    """ファクトリ関数とFeature flagのテスト"""

    def test_create_interpersonal(self):
        """create_interpersonalでインスタンス作成"""
        inst = create_interpersonal(organization_id="org_test")
        assert isinstance(inst, BrainInterpersonal)

    def test_create_with_feature_flags(self):
        """Feature flagでコンポーネント制御"""
        inst = create_interpersonal(
            organization_id="org_test",
            feature_flags={"ENABLE_COUNSEL": False},
        )
        assert inst.counsel_engine is None

    def test_is_interpersonal_enabled_true(self):
        """Feature flagがTrueの場合"""
        assert is_interpersonal_enabled({FEATURE_FLAG_INTERPERSONAL_ENABLED: True}) is True

    def test_is_interpersonal_enabled_false(self):
        """Feature flagがFalseの場合"""
        assert is_interpersonal_enabled({FEATURE_FLAG_INTERPERSONAL_ENABLED: False}) is False

    def test_is_interpersonal_enabled_none(self):
        """Feature flagsがNoneの場合"""
        assert is_interpersonal_enabled(None) is False


# =============================================================================
# Test: CommunicationStyleAdapter
# =============================================================================

class TestCommunicationStyleAdapter:
    """コミュニケーションスタイル適応のテスト"""

    def test_initialization(self, style_adapter):
        assert style_adapter.organization_id == "org_test_123"

    def test_initialization_requires_org_id(self):
        with pytest.raises(ValueError):
            CommunicationStyleAdapter(organization_id="")

    def test_adapt_message_style_with_profile(self, style_adapter, sample_profile):
        """プロファイルありでスタイル推奨"""
        result = style_adapter.adapt_message_style(sample_profile)
        assert result["length"] == "brief"
        assert result["formality"] == "casual"
        assert result["confidence"] == 0.8

    def test_adapt_message_style_without_profile(self, style_adapter):
        """プロファイルなしでデフォルト"""
        result = style_adapter.adapt_message_style(None)
        assert result["length"] == "balanced"
        assert result["formality"] == "adaptive"
        assert result["confidence"] == 0.0

    def test_is_good_timing_anytime(self, style_adapter):
        """ANYTIMEは常にTrue"""
        assert style_adapter._is_good_timing(PreferredTiming.ANYTIME) is True


# =============================================================================
# Test: MotivationEngine
# =============================================================================

class TestMotivationEngine:
    """動機付けエンジンのテスト"""

    def test_initialization(self, motivation_engine):
        assert motivation_engine.organization_id == "org_test_123"

    def test_detect_discouragement_no_signals(self, motivation_engine):
        """シグナルなし = 落ち込みなし"""
        result = motivation_engine.detect_discouragement([])
        assert result["is_discouraged"] is False
        assert result["confidence"] == 0.0

    def test_detect_discouragement_single_signal(self, motivation_engine):
        """シグナル1つ = 閾値未満"""
        result = motivation_engine.detect_discouragement([DiscouragementSignal.DELAYED_RESPONSE])
        assert result["is_discouraged"] is False
        assert result["confidence"] == 0.25

    def test_detect_discouragement_multiple_signals(self, motivation_engine):
        """シグナル複数 = 閾値超え"""
        signals = [
            DiscouragementSignal.DELAYED_RESPONSE,
            DiscouragementSignal.SHORT_RESPONSE,
            DiscouragementSignal.NEGATIVE_LANGUAGE,
        ]
        result = motivation_engine.detect_discouragement(signals)
        assert result["is_discouraged"] is True
        assert result["confidence"] >= DISCOURAGEMENT_CONFIDENCE_THRESHOLD

    def test_detect_discouragement_with_profile_boost(self, motivation_engine, sample_motivation_profile):
        """プロファイルのトリガーに一致するとブースト"""
        signals = [
            DiscouragementSignal.MISSED_DEADLINE,  # トリガーに一致
            DiscouragementSignal.NEGATIVE_LANGUAGE,  # トリガーに一致
        ]
        result = motivation_engine.detect_discouragement(signals, sample_motivation_profile)
        # ブーストがかかるので、2シグナルでも閾値超えする
        assert result["confidence"] > 0.5

    def test_suggest_encouragement_achievement(self, motivation_engine, sample_motivation_profile):
        """達成志向の人への励まし提案"""
        result = motivation_engine.suggest_encouragement_type(sample_motivation_profile)
        assert result["approach"] == "milestone"
        assert result["focus"] == "progress_and_goals"

    def test_suggest_encouragement_insufficient_data(self, motivation_engine):
        """データ不足の場合はgeneral"""
        profile = MotivationProfile(sample_count=2)
        result = motivation_engine.suggest_encouragement_type(profile)
        assert result["approach"] == "general"

    def test_suggest_encouragement_no_profile(self, motivation_engine):
        """プロファイルなしの場合はgeneral"""
        result = motivation_engine.suggest_encouragement_type(None)
        assert result["approach"] == "general"

    def test_suggest_encouragement_all_types(self, motivation_engine):
        """全モチベーションタイプで適切な提案"""
        for mtype in MotivationType:
            profile = MotivationProfile(primary_type=mtype, sample_count=10)
            result = motivation_engine.suggest_encouragement_type(profile)
            assert "approach" in result
            assert "focus" in result


# =============================================================================
# Test: CounselEngine
# =============================================================================

class TestCounselEngine:
    """助言エンジンのテスト"""

    def test_initialization(self, counsel_engine):
        assert counsel_engine.organization_id == "org_test_123"

    def test_assess_receptiveness_neutral(self, counsel_engine):
        """ニュートラル状態"""
        result = counsel_engine.assess_receptiveness({})
        assert result["score"] == 0.5
        assert result["level"] == "medium"

    def test_assess_receptiveness_busy(self, counsel_engine):
        """忙しい状態 = 受容度低下"""
        result = counsel_engine.assess_receptiveness({"is_busy": True})
        assert result["score"] < 0.5

    def test_assess_receptiveness_after_success(self, counsel_engine):
        """成功直後 = 受容度上昇"""
        result = counsel_engine.assess_receptiveness({"recent_success": True})
        assert result["score"] > 0.5

    def test_assess_receptiveness_negative_event(self, counsel_engine):
        """ネガティブイベント直後 = 受容度低下"""
        result = counsel_engine.assess_receptiveness({"recent_negative_event": True})
        assert result["score"] < 0.5
        assert result["level"] == "low"

    def test_assess_receptiveness_high_conditions(self, counsel_engine):
        """好条件が揃った場合 = HIGH"""
        result = counsel_engine.assess_receptiveness({
            "recent_success": True,
            "conversation_tone": "positive",
            "time_of_day": "morning",
        })
        assert result["level"] == "high"

    def test_assess_receptiveness_clamped(self, counsel_engine):
        """スコアは0.0-1.0にクランプされる"""
        result = counsel_engine.assess_receptiveness({
            "is_busy": True,
            "recent_negative_event": True,
            "conversation_tone": "negative",
        })
        assert result["score"] >= 0.0
        assert result["score"] <= 1.0


# =============================================================================
# Test: ConflictMediator
# =============================================================================

class TestConflictMediator:
    """対立調停のテスト"""

    def test_initialization(self, conflict_mediator):
        assert conflict_mediator.organization_id == "org_test_123"

    def test_detect_no_conflict(self, conflict_mediator):
        """シグナルなし = 対立なし"""
        result = conflict_mediator.detect_conflict_signals({})
        assert result["is_conflict"] is False
        assert result["evidence_count"] == 0

    def test_detect_conflict_below_threshold(self, conflict_mediator):
        """エビデンス不足 = 対立未確定"""
        result = conflict_mediator.detect_conflict_signals({"disagreement_count": 1})
        assert result["is_conflict"] is False
        assert result["evidence_count"] == 1

    def test_detect_conflict_above_threshold(self, conflict_mediator):
        """エビデンス十分 = 対立検出"""
        result = conflict_mediator.detect_conflict_signals({
            "disagreement_count": 2,
            "negative_mentions": 2,
        })
        assert result["is_conflict"] is True
        assert result["evidence_count"] >= CONFLICT_MIN_EVIDENCE_COUNT

    def test_detect_conflict_high_severity(self, conflict_mediator):
        """深刻な対立の検出"""
        result = conflict_mediator.detect_conflict_signals({
            "disagreement_count": 3,
            "negative_mentions": 3,
            "escalation_requests": 2,
        })
        assert result["severity"] == "high"

    def test_suggest_mediation_high(self, conflict_mediator):
        """深刻な対立への調停戦略"""
        result = conflict_mediator.suggest_mediation_strategy(ConflictSeverity.HIGH)
        assert result["strategy_type"] == "direct_mediation"
        assert result["ceo_involvement"] is True
        assert result["recommended_timing"] == "immediate"

    def test_suggest_mediation_medium(self, conflict_mediator):
        """中程度の対立への調停戦略"""
        result = conflict_mediator.suggest_mediation_strategy(ConflictSeverity.MEDIUM)
        assert result["strategy_type"] == "guided_resolution"
        assert result["ceo_involvement"] is False

    def test_suggest_mediation_low(self, conflict_mediator):
        """軽微な対立への調停戦略"""
        result = conflict_mediator.suggest_mediation_strategy(ConflictSeverity.LOW)
        assert result["strategy_type"] == "passive_monitoring"


# =============================================================================
# Test: Models
# =============================================================================

class TestModels:
    """データモデルのテスト"""

    def test_communication_profile_defaults(self):
        """CommunicationProfileのデフォルト値"""
        profile = CommunicationProfile()
        assert profile.id is not None
        assert profile.preferred_length == InterpersonalStyleType.BALANCED
        assert profile.formality_level == InterpersonalStyleType.ADAPTIVE
        assert profile.preferred_timing == PreferredTiming.ANYTIME
        assert profile.interaction_count == 0

    def test_communication_profile_to_dict(self):
        """to_dictが正しく変換する"""
        profile = CommunicationProfile(organization_id="org1", user_id="user1")
        d = profile.to_dict()
        assert d["organization_id"] == "org1"
        assert d["user_id"] == "user1"
        assert d["preferred_length"] == "balanced"

    def test_motivation_profile_defaults(self):
        """MotivationProfileのデフォルト値"""
        profile = MotivationProfile()
        assert profile.primary_type == MotivationType.ACHIEVEMENT
        assert profile.secondary_type is None
        assert profile.key_values == []

    def test_motivation_profile_to_dict(self):
        """to_dictが正しく変換する"""
        profile = MotivationProfile(
            organization_id="org1",
            primary_type=MotivationType.GROWTH,
        )
        d = profile.to_dict()
        assert d["primary_type"] == "growth"

    def test_feedback_opportunity_defaults(self):
        """FeedbackOpportunityのデフォルト値"""
        opp = FeedbackOpportunity()
        assert opp.feedback_type == FeedbackType.CONSTRUCTIVE
        assert opp.delivered is False

    def test_conflict_log_defaults(self):
        """ConflictLogのデフォルト値"""
        log = ConflictLog()
        assert log.severity == ConflictSeverity.LOW
        assert log.status == ConflictStatus.DETECTED
        assert log.evidence_count == 0

    def test_interpersonal_result(self):
        """InterpersonalResultの動作"""
        result = InterpersonalResult(success=True, message="OK")
        assert result.success is True
        assert result.message == "OK"

    def test_all_enum_values_accessible(self):
        """全Enumの値にアクセスできること"""
        assert len(InterpersonalStyleType) == 6
        assert len(PreferredTiming) == 4
        assert len(MotivationType) == 6
        assert len(DiscouragementSignal) == 6
        assert len(FeedbackType) == 4
        assert len(ReceptivenessLevel) == 3
        assert len(ConflictSeverity) == 3
        assert len(ConflictStatus) == 5


# =============================================================================
# Test: Async DB操作（CRITICAL — SQL paths coverage）
# =============================================================================

class TestStyleAdapterDB:
    """CommunicationStyleAdapter のDB操作テスト"""

    @pytest.mark.asyncio
    async def test_get_user_profile_found(self, style_adapter, mock_conn):
        """プロファイルが見つかった場合"""
        mock_conn.execute.return_value.fetchone.return_value = (
            "uuid-1", "org_test_123", "user_001",
            "brief", "casual", "morning",
            {}, 10, 0.8,
            datetime(2026, 1, 1), datetime(2026, 1, 2),
        )
        profile = await style_adapter.get_user_profile(mock_conn, "user_001")
        assert profile is not None
        assert profile.user_id == "user_001"
        assert profile.preferred_length == InterpersonalStyleType.BRIEF
        assert profile.confidence_score == 0.8
        # org_id filterが使われていることを確認
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org_test_123"
        assert params["user_id"] == "user_001"

    @pytest.mark.asyncio
    async def test_get_user_profile_not_found(self, style_adapter, mock_conn):
        """プロファイルが見つからない場合"""
        mock_conn.execute.return_value.fetchone.return_value = None
        profile = await style_adapter.get_user_profile(mock_conn, "user_unknown")
        assert profile is None

    @pytest.mark.asyncio
    async def test_get_user_profile_db_error(self, style_adapter, mock_conn):
        """DB例外時はNone返却 + ログ"""
        mock_conn.execute.side_effect = Exception("DB connection lost")
        profile = await style_adapter.get_user_profile(mock_conn, "user_001")
        assert profile is None

    @pytest.mark.asyncio
    async def test_update_profile_create_new(self, style_adapter, mock_conn):
        """新規プロファイル作成"""
        # get_user_profileがNoneを返す → 新規INSERT
        mock_conn.execute.return_value.fetchone.return_value = None
        result = await style_adapter.update_profile_from_interaction(
            mock_conn, "user_new", observed_length="brief",
        )
        assert result.success is True
        assert result.message == "Profile created"
        # INSERT呼び出しの確認（2回: SELECT + INSERT）
        assert mock_conn.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_update_profile_update_existing(self, style_adapter, mock_conn):
        """既存プロファイル更新"""
        # 1回目のcall (get_user_profile): 既存データを返す
        existing_row = (
            "uuid-1", "org_test_123", "user_001",
            "balanced", "adaptive", "anytime",
            {}, 5, 0.5,
            datetime(2026, 1, 1), datetime(2026, 1, 1),
        )
        mock_conn.execute.return_value.fetchone.return_value = existing_row
        result = await style_adapter.update_profile_from_interaction(
            mock_conn, "user_001", observed_length="brief",
        )
        assert result.success is True
        assert result.message == "Profile updated"

    @pytest.mark.asyncio
    async def test_update_profile_db_error(self, style_adapter, mock_conn):
        """DB例外時はfailure返却"""
        mock_conn.execute.side_effect = Exception("write error")
        result = await style_adapter.update_profile_from_interaction(
            mock_conn, "user_001",
        )
        assert result.success is False


class TestMotivationEngineDB:
    """MotivationEngine のDB操作テスト"""

    @pytest.mark.asyncio
    async def test_get_motivation_profile_found(self, motivation_engine, mock_conn):
        """モチベーションプロファイルが見つかった場合"""
        mock_conn.execute.return_value.fetchone.return_value = (
            "uuid-m1", "org_test_123", "user_001",
            "achievement", "growth",
            ["progress"], ["missed_deadline"],
            20, 0.75,
            datetime(2026, 1, 1), datetime(2026, 1, 2),
        )
        profile = await motivation_engine.get_motivation_profile(mock_conn, "user_001")
        assert profile is not None
        assert profile.primary_type == MotivationType.ACHIEVEMENT
        assert profile.sample_count == 20

    @pytest.mark.asyncio
    async def test_get_motivation_profile_not_found(self, motivation_engine, mock_conn):
        """プロファイルが見つからない場合"""
        mock_conn.execute.return_value.fetchone.return_value = None
        profile = await motivation_engine.get_motivation_profile(mock_conn, "user_xxx")
        assert profile is None

    @pytest.mark.asyncio
    async def test_get_motivation_profile_db_error(self, motivation_engine, mock_conn):
        """DB例外時はNone"""
        mock_conn.execute.side_effect = Exception("timeout")
        profile = await motivation_engine.get_motivation_profile(mock_conn, "user_001")
        assert profile is None

    @pytest.mark.asyncio
    async def test_update_profile_create_new(self, motivation_engine, mock_conn):
        """新規モチベーションプロファイル作成"""
        mock_conn.execute.return_value.fetchone.return_value = None
        result = await motivation_engine.update_profile(
            mock_conn, "user_new",
            observed_type=MotivationType.GROWTH,
            observed_values=["learning"],
            observed_triggers=["criticism"],
        )
        assert result.success is True
        assert "created" in result.message

    @pytest.mark.asyncio
    async def test_update_profile_merge_arrays(self, motivation_engine, mock_conn):
        """既存プロファイル更新時にarray がマージされること"""
        existing_row = (
            "uuid-m1", "org_test_123", "user_001",
            "achievement", None,
            ["progress"], ["missed_deadline"],
            5, 0.5,
            datetime(2026, 1, 1), datetime(2026, 1, 1),
        )
        mock_conn.execute.return_value.fetchone.return_value = existing_row
        result = await motivation_engine.update_profile(
            mock_conn, "user_001",
            observed_values=["teamwork"],
            observed_triggers=["criticism"],
        )
        assert result.success is True
        # UPDATE呼び出しのパラメータを確認
        update_call = mock_conn.execute.call_args_list[-1]
        params = update_call[0][1]
        # key_valuesがマージされている
        merged_values = json.loads(params["key_values"])
        assert "progress" in merged_values
        assert "teamwork" in merged_values
        # triggersがマージされている
        merged_triggers = json.loads(params["triggers"])
        assert "missed_deadline" in merged_triggers
        assert "criticism" in merged_triggers

    @pytest.mark.asyncio
    async def test_update_profile_db_error(self, motivation_engine, mock_conn):
        """DB例外時はfailure"""
        mock_conn.execute.side_effect = Exception("write error")
        result = await motivation_engine.update_profile(mock_conn, "user_001")
        assert result.success is False


class TestCounselEngineDB:
    """CounselEngine のDB操作テスト"""

    @pytest.mark.asyncio
    async def test_should_provide_feedback_low_receptiveness(self, counsel_engine, mock_conn):
        """受容度が低い場合はフィードバックしない"""
        result = await counsel_engine.should_provide_feedback(
            mock_conn, "user_001", FeedbackType.CONSTRUCTIVE, 0.1,
        )
        assert result["should_provide"] is False
        assert "too low" in result["reason"]

    @pytest.mark.asyncio
    async def test_should_provide_feedback_constructive_needs_high(self, counsel_engine, mock_conn):
        """CONSTRUCTIVE feedbackは高い受容度が必要"""
        # 受容度は中程度(0.5)だが CONSTRUCTIVE は HIGH が必要
        mock_conn.execute.return_value.fetchall.return_value = []
        result = await counsel_engine.should_provide_feedback(
            mock_conn, "user_001", FeedbackType.CONSTRUCTIVE, 0.5,
        )
        assert result["should_provide"] is False

    @pytest.mark.asyncio
    async def test_should_provide_feedback_recent_exists(self, counsel_engine, mock_conn):
        """直近にフィードバック済みならスキップ"""
        # 受容度は十分高い
        mock_conn.execute.return_value.fetchall.return_value = [
            ("uuid-f1", "org_test_123", "user_001", "praise", "goal_progress", 0.8, True),
        ]
        result = await counsel_engine.should_provide_feedback(
            mock_conn, "user_001", FeedbackType.PRAISE, 0.8,
        )
        assert result["should_provide"] is False
        assert "Recent feedback" in result["reason"]

    @pytest.mark.asyncio
    async def test_should_provide_feedback_conditions_met(self, counsel_engine, mock_conn):
        """全条件が揃った場合はフィードバックOK"""
        mock_conn.execute.return_value.fetchall.return_value = []
        result = await counsel_engine.should_provide_feedback(
            mock_conn, "user_001", FeedbackType.PRAISE, 0.8,
        )
        assert result["should_provide"] is True

    @pytest.mark.asyncio
    async def test_record_feedback_opportunity_success(self, counsel_engine, mock_conn):
        """フィードバック機会の記録成功"""
        result = await counsel_engine.record_feedback_opportunity(
            mock_conn, "user_001", FeedbackType.PRAISE,
            "goal_progress", 0.8, delivered=True,
        )
        assert result.success is True
        # org_id filterの確認
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org_test_123"

    @pytest.mark.asyncio
    async def test_record_feedback_opportunity_db_error(self, counsel_engine, mock_conn):
        """DB例外時はfailure"""
        mock_conn.execute.side_effect = Exception("insert error")
        result = await counsel_engine.record_feedback_opportunity(
            mock_conn, "user_001", FeedbackType.PRAISE, "cat", 0.5,
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_recent_feedback_found(self, counsel_engine, mock_conn):
        """直近のフィードバック履歴取得"""
        mock_conn.execute.return_value.fetchall.return_value = [
            ("uuid-f1", "org_test_123", "user_001", "praise", "goal", 0.8, True),
        ]
        results = await counsel_engine.get_recent_feedback(mock_conn, "user_001")
        assert len(results) == 1
        assert results[0].feedback_type == FeedbackType.PRAISE

    @pytest.mark.asyncio
    async def test_get_recent_feedback_empty(self, counsel_engine, mock_conn):
        """フィードバック履歴なし"""
        mock_conn.execute.return_value.fetchall.return_value = []
        results = await counsel_engine.get_recent_feedback(mock_conn, "user_001")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_recent_feedback_db_error(self, counsel_engine, mock_conn):
        """DB例外時は空リスト"""
        mock_conn.execute.side_effect = Exception("read error")
        results = await counsel_engine.get_recent_feedback(mock_conn, "user_001")
        assert results == []


class TestConflictMediatorDB:
    """ConflictMediator のDB操作テスト"""

    @pytest.mark.asyncio
    async def test_record_conflict_success(self, conflict_mediator, mock_conn):
        """対立ログの記録成功"""
        result = await conflict_mediator.record_conflict(
            mock_conn, "user_a", "user_b",
            "project_disagreement", ConflictSeverity.MEDIUM, evidence_count=4,
        )
        assert result.success is True
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org_test_123"
        assert params["party_a"] == "user_a"
        assert params["severity"] == "medium"

    @pytest.mark.asyncio
    async def test_record_conflict_db_error(self, conflict_mediator, mock_conn):
        """DB例外時はfailure"""
        mock_conn.execute.side_effect = Exception("insert error")
        result = await conflict_mediator.record_conflict(
            mock_conn, "user_a", "user_b", "cat", ConflictSeverity.LOW,
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_update_conflict_status_success(self, conflict_mediator, mock_conn):
        """ステータス更新成功"""
        result = await conflict_mediator.update_conflict_status(
            mock_conn, "conflict-uuid-1", ConflictStatus.MEDIATING,
            mediation_strategy_type="guided_resolution",
        )
        assert result.success is True
        assert "mediating" in result.message

    @pytest.mark.asyncio
    async def test_update_conflict_status_resolved(self, conflict_mediator, mock_conn):
        """解決済みへの更新でresolved_atが設定される"""
        result = await conflict_mediator.update_conflict_status(
            mock_conn, "conflict-uuid-1", ConflictStatus.RESOLVED,
        )
        assert result.success is True
        # SQLにresolved_at = NOW()が含まれることを確認
        call_args = mock_conn.execute.call_args
        sql_str = str(call_args[0][0])
        assert "resolved_at" in sql_str

    @pytest.mark.asyncio
    async def test_update_conflict_status_db_error(self, conflict_mediator, mock_conn):
        """DB例外時はfailure"""
        mock_conn.execute.side_effect = Exception("update error")
        result = await conflict_mediator.update_conflict_status(
            mock_conn, "uuid-1", ConflictStatus.MEDIATING,
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_active_conflicts_found(self, conflict_mediator, mock_conn):
        """アクティブな対立の取得"""
        mock_conn.execute.return_value.fetchall.return_value = [
            ("uuid-c1", "org_test_123", "user_a", "user_b",
             "schedule", "medium", "monitoring",
             None, 3, datetime(2026, 1, 1), None),
        ]
        conflicts = await conflict_mediator.get_active_conflicts(mock_conn)
        assert len(conflicts) == 1
        assert conflicts[0].severity == ConflictSeverity.MEDIUM
        assert conflicts[0].party_a_user_id == "user_a"

    @pytest.mark.asyncio
    async def test_get_active_conflicts_empty(self, conflict_mediator, mock_conn):
        """アクティブな対立なし"""
        mock_conn.execute.return_value.fetchall.return_value = []
        conflicts = await conflict_mediator.get_active_conflicts(mock_conn)
        assert conflicts == []

    @pytest.mark.asyncio
    async def test_get_active_conflicts_db_error(self, conflict_mediator, mock_conn):
        """DB例外時は空リスト"""
        mock_conn.execute.side_effect = Exception("read error")
        conflicts = await conflict_mediator.get_active_conflicts(mock_conn)
        assert conflicts == []


# =============================================================================
# Test: BrainInterpersonal 統合クラスのDB操作委譲
# =============================================================================

class TestBrainInterpersonalDB:
    """統合クラスのDB操作委譲テスト"""

    @pytest.mark.asyncio
    async def test_get_communication_profile_delegates(self, interpersonal, mock_conn):
        """get_communication_profileがstyle_adapterに委譲"""
        mock_conn.execute.return_value.fetchone.return_value = None
        result = await interpersonal.get_communication_profile(mock_conn, "user_001")
        assert result is None  # not found

    @pytest.mark.asyncio
    async def test_get_motivation_profile_delegates(self, interpersonal, mock_conn):
        """get_motivation_profileがmotivation_engineに委譲"""
        mock_conn.execute.return_value.fetchone.return_value = None
        result = await interpersonal.get_motivation_profile(mock_conn, "user_001")
        assert result is None

    @pytest.mark.asyncio
    async def test_record_feedback_delegates(self, interpersonal, mock_conn):
        """record_feedbackがcounsel_engineに委譲"""
        result = await interpersonal.record_feedback(
            mock_conn, "user_001", FeedbackType.PRAISE, "goal", 0.8,
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_record_conflict_delegates(self, interpersonal, mock_conn):
        """record_conflictがconflict_mediatorに委譲"""
        result = await interpersonal.record_conflict(
            mock_conn, "user_a", "user_b", "schedule", ConflictSeverity.LOW,
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_get_active_conflicts_delegates(self, interpersonal, mock_conn):
        """get_active_conflictsがconflict_mediatorに委譲"""
        mock_conn.execute.return_value.fetchall.return_value = []
        result = await interpersonal.get_active_conflicts(mock_conn)
        assert result == []
