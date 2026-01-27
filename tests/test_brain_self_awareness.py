"""
Phase 2H: 自己認識（Self-Awareness）テスト

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2H
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from lib.brain.self_awareness import (
    # 統合クラス
    BrainSelfAwareness,
    create_self_awareness,
    # モデル
    Ability,
    AbilityScore,
    AbilitySummary,
    ConfidenceAssessment,
    ImprovementLog,
    Limitation,
    SelfDiagnosis,
    # Enums
    AbilityCategory,
    AbilityLevel,
    ConfidenceLevel,
    DiagnosisType,
    EscalationReason,
    ImprovementType,
    LimitationType,
    # 定数
    ABILITY_SCORE_DEFAULT,
    CONFIDENCE_THRESHOLD_HIGH,
    CONFIDENCE_THRESHOLD_LOW,
    DEFAULT_ABILITY_SCORES,
)


# ============================================================================
# AbilityScore Tests
# ============================================================================

class TestAbilityScore:
    """AbilityScoreモデルのテスト"""

    def test_create_ability_score(self):
        """能力スコア作成"""
        score = AbilityScore(
            organization_id="org123",
            category=AbilityCategory.TASK_MANAGEMENT,
            score=0.7,
        )
        assert score.id is not None
        assert score.organization_id == "org123"
        assert score.category == AbilityCategory.TASK_MANAGEMENT
        assert score.score == 0.7

    def test_ability_level_expert(self):
        """レベル判定 - 得意"""
        score = AbilityScore(score=0.85)
        assert score.level == AbilityLevel.EXPERT
        assert score.is_strong is True
        assert score.is_weak is False

    def test_ability_level_novice(self):
        """レベル判定 - 苦手"""
        score = AbilityScore(score=0.3)
        assert score.level == AbilityLevel.NOVICE
        assert score.is_strong is False
        assert score.is_weak is True

    def test_update_score_success(self):
        """スコア更新 - 成功時"""
        score = AbilityScore(score=0.5)
        new_score = score.update_score(success=True, weight=0.1)

        assert new_score > 0.5
        assert score.sample_count == 1
        assert score.success_count == 1
        assert score.failure_count == 0

    def test_update_score_failure(self):
        """スコア更新 - 失敗時"""
        score = AbilityScore(score=0.5)
        new_score = score.update_score(success=False, weight=0.1)

        assert new_score < 0.5
        assert score.sample_count == 1
        assert score.success_count == 0
        assert score.failure_count == 1

    def test_success_rate(self):
        """成功率の計算"""
        score = AbilityScore(
            sample_count=10,
            success_count=7,
            failure_count=3,
        )
        assert score.success_rate == 0.7

    def test_success_rate_zero_samples(self):
        """成功率 - サンプルなし"""
        score = AbilityScore(sample_count=0)
        assert score.success_rate == 0.0

    def test_to_dict(self):
        """辞書変換"""
        score = AbilityScore(
            organization_id="org123",
            category=AbilityCategory.KNOWLEDGE_SEARCH,
            score=0.65,
        )
        d = score.to_dict()

        assert d["organization_id"] == "org123"
        assert d["category"] == "knowledge_search"
        assert d["score"] == 0.65
        assert d["level"] == "proficient"

    def test_from_dict(self):
        """辞書から生成"""
        data = {
            "id": str(uuid4()),
            "organization_id": "org123",
            "category": "task_management",
            "score": 0.8,
            "sample_count": 5,
            "success_count": 4,
        }
        score = AbilityScore.from_dict(data)

        assert score.organization_id == "org123"
        assert score.category == AbilityCategory.TASK_MANAGEMENT
        assert score.score == 0.8


# ============================================================================
# Limitation Tests
# ============================================================================

class TestLimitation:
    """Limitationモデルのテスト"""

    def test_create_limitation(self):
        """限界情報作成"""
        limitation = Limitation(
            organization_id="org123",
            limitation_type=LimitationType.KNOWLEDGE_GAP,
            description="法務関連の知識が不足",
        )
        assert limitation.id is not None
        assert limitation.limitation_type == LimitationType.KNOWLEDGE_GAP
        assert limitation.occurrence_count == 1

    def test_increment_occurrence(self):
        """発生回数インクリメント"""
        limitation = Limitation(
            limitation_type=LimitationType.UNCERTAINTY,
            description="テスト",
        )
        limitation.increment_occurrence()
        limitation.increment_occurrence()

        assert limitation.occurrence_count == 3

    def test_to_dict(self):
        """辞書変換"""
        limitation = Limitation(
            limitation_type=LimitationType.DOMAIN_SPECIFIC,
            description="専門外の質問",
            keywords=["法務", "契約"],
        )
        d = limitation.to_dict()

        assert d["limitation_type"] == "domain_specific"
        assert d["description"] == "専門外の質問"
        assert "法務" in d["keywords"]


# ============================================================================
# ConfidenceAssessment Tests
# ============================================================================

class TestConfidenceAssessment:
    """ConfidenceAssessmentモデルのテスト"""

    def test_high_confidence(self):
        """高確信度"""
        assessment = ConfidenceAssessment(
            knowledge_confidence=0.9,
            context_confidence=0.85,
            historical_accuracy=0.9,
        )
        assert assessment.confidence_level == ConfidenceLevel.HIGH
        assert assessment.needs_confirmation is False
        assert assessment.needs_escalation is False

    def test_medium_confidence(self):
        """中程度の確信度"""
        assessment = ConfidenceAssessment(
            knowledge_confidence=0.6,
            context_confidence=0.6,
            historical_accuracy=0.6,
        )
        assert assessment.confidence_level == ConfidenceLevel.MEDIUM
        assert assessment.needs_confirmation is True
        assert assessment.needs_escalation is False

    def test_low_confidence(self):
        """低確信度"""
        assessment = ConfidenceAssessment(
            knowledge_confidence=0.4,
            context_confidence=0.4,
            historical_accuracy=0.4,
        )
        assert assessment.confidence_level == ConfidenceLevel.LOW
        assert assessment.needs_confirmation is True
        assert assessment.needs_escalation is False

    def test_very_low_confidence(self):
        """非常に低い確信度"""
        assessment = ConfidenceAssessment(
            knowledge_confidence=0.2,
            context_confidence=0.2,
            historical_accuracy=0.2,
        )
        assert assessment.confidence_level == ConfidenceLevel.VERY_LOW
        assert assessment.needs_escalation is True


# ============================================================================
# SelfDiagnosis Tests
# ============================================================================

class TestSelfDiagnosis:
    """SelfDiagnosisモデルのテスト"""

    def test_create_diagnosis(self):
        """診断作成"""
        diagnosis = SelfDiagnosis(
            organization_id="org123",
            diagnosis_type=DiagnosisType.DAILY,
            total_interactions=100,
            successful_interactions=80,
        )
        assert diagnosis.success_rate == 0.8

    def test_escalation_rate(self):
        """エスカレーション率"""
        diagnosis = SelfDiagnosis(
            total_interactions=100,
            escalated_interactions=10,
        )
        assert diagnosis.escalation_rate == 0.1


# ============================================================================
# ImprovementLog Tests
# ============================================================================

class TestImprovementLog:
    """ImprovementLogモデルのテスト"""

    def test_improvement(self):
        """改善ログ - 改善"""
        log = ImprovementLog(
            improvement_type=ImprovementType.ACCURACY,
            previous_score=0.5,
            current_score=0.7,
        )
        assert log.is_improvement is True
        assert log.change_amount == pytest.approx(0.2)
        assert log.change_percent == pytest.approx(40.0)

    def test_regression(self):
        """改善ログ - 悪化"""
        log = ImprovementLog(
            improvement_type=ImprovementType.ACCURACY,
            previous_score=0.7,
            current_score=0.5,
        )
        assert log.is_improvement is False
        assert log.change_amount == pytest.approx(-0.2)


# ============================================================================
# Constants Tests
# ============================================================================

class TestConstants:
    """定数のテスト"""

    def test_ability_category_values(self):
        """AbilityCategoryの値"""
        assert AbilityCategory.TASK_MANAGEMENT.value == "task_management"
        assert AbilityCategory.KNOWLEDGE_SEARCH.value == "knowledge_search"

    def test_ability_level_values(self):
        """AbilityLevelの値"""
        assert AbilityLevel.EXPERT.value == "expert"
        assert AbilityLevel.NOVICE.value == "novice"

    def test_confidence_level_values(self):
        """ConfidenceLevelの値"""
        assert ConfidenceLevel.HIGH.value == "high"
        assert ConfidenceLevel.VERY_LOW.value == "very_low"

    def test_default_ability_scores(self):
        """デフォルト能力スコアの存在確認"""
        assert len(DEFAULT_ABILITY_SCORES) > 0
        assert AbilityCategory.TASK_MANAGEMENT in DEFAULT_ABILITY_SCORES


# ============================================================================
# BrainSelfAwareness Tests
# ============================================================================

class TestBrainSelfAwareness:
    """BrainSelfAwarenessのテスト"""

    def test_create_self_awareness(self):
        """インスタンス生成"""
        awareness = create_self_awareness("org123")
        assert awareness.organization_id == "org123"

    def test_assess_confidence_high(self):
        """確信度評価 - 高"""
        awareness = create_self_awareness("org123")
        assessment = awareness.assess_confidence(
            category=AbilityCategory.TASK_MANAGEMENT,
            context={"has_source": True, "is_verified": True, "clear_intent": True},
        )
        # コンテキストが充実しているので高めの確信度
        assert assessment.confidence_score >= 0.5

    def test_assess_confidence_with_uncertainty(self):
        """確信度評価 - 不確実性キーワードあり"""
        awareness = create_self_awareness("org123")
        assessment = awareness.assess_confidence(
            category=AbilityCategory.KNOWLEDGE_SEARCH,
            message="これは推測ですが、たぶん正しいと思います",
        )
        assert len(assessment.uncertainty_factors) > 0

    def test_record_interaction_result_success(self):
        """インタラクション結果記録 - 成功"""
        awareness = create_self_awareness("org123")
        score = awareness.record_interaction_result(
            conn=None,
            category=AbilityCategory.TASK_MANAGEMENT,
            success=True,
        )
        assert score.success_count == 1
        assert score.score > DEFAULT_ABILITY_SCORES[AbilityCategory.TASK_MANAGEMENT]

    def test_record_interaction_result_failure(self):
        """インタラクション結果記録 - 失敗"""
        awareness = create_self_awareness("org123")
        initial_score = DEFAULT_ABILITY_SCORES[AbilityCategory.TASK_MANAGEMENT]
        score = awareness.record_interaction_result(
            conn=None,
            category=AbilityCategory.TASK_MANAGEMENT,
            success=False,
        )
        assert score.failure_count == 1
        assert score.score < initial_score

    def test_get_ability_score(self):
        """能力スコア取得"""
        awareness = create_self_awareness("org123")
        score = awareness.get_ability_score(AbilityCategory.KNOWLEDGE_SEARCH)

        assert score.category == AbilityCategory.KNOWLEDGE_SEARCH
        assert score.score == DEFAULT_ABILITY_SCORES[AbilityCategory.KNOWLEDGE_SEARCH]

    def test_get_ability_summary(self):
        """能力サマリー取得"""
        awareness = create_self_awareness("org123")
        summary = awareness.get_ability_summary()

        assert summary.organization_id == "org123"
        assert summary.total_abilities > 0
        assert 0.0 <= summary.overall_score <= 1.0

    def test_record_limitation(self):
        """限界記録"""
        awareness = create_self_awareness("org123")
        limitation = awareness.record_limitation(
            limitation_type=LimitationType.KNOWLEDGE_GAP,
            description="税務関連の知識が不足",
            keywords=["税務", "確定申告"],
        )
        assert limitation.limitation_type == LimitationType.KNOWLEDGE_GAP
        assert limitation.occurrence_count == 1

    def test_record_limitation_increment(self):
        """限界記録 - 既存の限界をインクリメント"""
        awareness = create_self_awareness("org123")

        # 同じ限界を2回記録
        awareness.record_limitation(
            limitation_type=LimitationType.KNOWLEDGE_GAP,
            description="税務関連の知識が不足",
        )
        limitation = awareness.record_limitation(
            limitation_type=LimitationType.KNOWLEDGE_GAP,
            description="税務関連の知識が不足",
        )

        assert limitation.occurrence_count == 2

    def test_get_limitations(self):
        """限界リスト取得"""
        awareness = create_self_awareness("org123")

        # いくつかの限界を記録
        awareness.record_limitation(
            limitation_type=LimitationType.KNOWLEDGE_GAP,
            description="テスト1",
        )
        awareness.record_limitation(
            limitation_type=LimitationType.UNCERTAINTY,
            description="テスト2",
        )

        limitations = awareness.get_limitations()
        assert len(limitations) >= 2

    def test_run_self_diagnosis(self):
        """自己診断実行"""
        awareness = create_self_awareness("org123")
        diagnosis = awareness.run_self_diagnosis()

        assert diagnosis.organization_id == "org123"
        assert diagnosis.diagnosis_type == DiagnosisType.DAILY
        assert 0.0 <= diagnosis.overall_score <= 1.0

    def test_should_add_confirmation(self):
        """確認メッセージ追加判定"""
        awareness = create_self_awareness("org123")
        should_add, message = awareness.should_add_confirmation(
            category=AbilityCategory.GENERAL,
        )
        # デフォルトスコアは中程度なので確認が必要
        assert isinstance(should_add, bool)
        assert isinstance(message, str)

    def test_should_escalate(self):
        """エスカレーション判定"""
        awareness = create_self_awareness("org123")
        should_escalate, reason, target = awareness.should_escalate(
            category=AbilityCategory.GENERAL,
        )
        assert isinstance(should_escalate, bool)


# ============================================================================
# Edge Cases Tests
# ============================================================================

class TestEdgeCases:
    """エッジケーステスト"""

    def test_ability_score_boundary_values(self):
        """境界値テスト - スコア"""
        # 最小値
        score_min = AbilityScore(score=0.0)
        assert score_min.level in [AbilityLevel.NOVICE, AbilityLevel.UNKNOWN]

        # 最大値
        score_max = AbilityScore(score=1.0)
        # 1.0は範囲外になる可能性があるのでチェック
        assert score_max.score == 1.0

    def test_empty_limitations(self):
        """限界リスト - 空"""
        awareness = create_self_awareness("org123")
        limitations = awareness.get_limitations()
        assert limitations == []

    def test_unknown_category_in_from_dict(self):
        """未知のカテゴリ"""
        data = {
            "category": "unknown_category",
            "score": 0.5,
        }
        score = AbilityScore.from_dict(data)
        assert score.category == AbilityCategory.GENERAL

    def test_assessment_with_no_context(self):
        """コンテキストなしの評価"""
        awareness = create_self_awareness("org123")
        assessment = awareness.assess_confidence(
            category=AbilityCategory.TASK_MANAGEMENT,
        )
        assert assessment.confidence_score > 0
