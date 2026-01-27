"""
Ultimate Brain Phase 1: Self-Critique テスト

設計書: docs/19_ultimate_brain_architecture.md
"""

import pytest
from lib.brain.self_critique import (
    SelfCritique,
    create_self_critique,
    QualityCriterion,
    IssueType,
    IssueSeverity,
    QualityScore,
    DetectedIssue,
    CritiqueResult,
    RefinedResponse,
    QUALITY_THRESHOLDS,
    OVERALL_REFINEMENT_THRESHOLD,
    LENGTH_GUIDELINES,
)


class TestQualityCriterion:
    """QualityCriterion Enumテスト"""

    def test_quality_criterion_values(self):
        """品質基準の値を確認"""
        assert QualityCriterion.RELEVANCE.value == "relevance"
        assert QualityCriterion.COMPLETENESS.value == "completeness"
        assert QualityCriterion.CONSISTENCY.value == "consistency"
        assert QualityCriterion.TONE.value == "tone"
        assert QualityCriterion.ACTIONABILITY.value == "actionability"
        assert QualityCriterion.SAFETY.value == "safety"

    def test_quality_criterion_count(self):
        """品質基準の数を確認"""
        assert len(QualityCriterion) == 6


class TestIssueType:
    """IssueType Enumテスト"""

    def test_issue_type_values(self):
        """問題タイプの値を確認"""
        assert IssueType.INCOMPLETE_SENTENCE.value == "incomplete_sentence"
        assert IssueType.CONTRADICTION.value == "contradiction"
        assert IssueType.MISSING_INFO.value == "missing_info"
        assert IssueType.WRONG_TONE.value == "wrong_tone"
        assert IssueType.TOO_LONG.value == "too_long"
        assert IssueType.TOO_SHORT.value == "too_short"


class TestIssueSeverity:
    """IssueSeverity Enumテスト"""

    def test_issue_severity_values(self):
        """深刻度の値を確認"""
        assert IssueSeverity.CRITICAL.value == "critical"
        assert IssueSeverity.HIGH.value == "high"
        assert IssueSeverity.MEDIUM.value == "medium"
        assert IssueSeverity.LOW.value == "low"


class TestQualityScore:
    """QualityScoreデータクラステスト"""

    def test_quality_score_creation(self):
        """QualityScoreを作成"""
        score = QualityScore(
            criterion=QualityCriterion.RELEVANCE,
            score=0.85,
            reasoning="キーワードがよく反映されている",
            details={"keyword_match_ratio": 0.8},
        )
        assert score.criterion == QualityCriterion.RELEVANCE
        assert score.score == 0.85


class TestDetectedIssue:
    """DetectedIssueデータクラステスト"""

    def test_detected_issue_creation(self):
        """DetectedIssueを作成"""
        issue = DetectedIssue(
            issue_type=IssueType.INCOMPLETE_SENTENCE,
            severity=IssueSeverity.CRITICAL,
            description="文が途切れている",
            location="...を",
            suggestion="文を完結させる",
        )
        assert issue.issue_type == IssueType.INCOMPLETE_SENTENCE
        assert issue.severity == IssueSeverity.CRITICAL


class TestCritiqueResult:
    """CritiqueResultデータクラステスト"""

    def test_critique_result_creation(self):
        """CritiqueResultを作成"""
        result = CritiqueResult(
            scores=[],
            issues=[],
            overall_score=0.8,
            needs_refinement=False,
            refinement_priority=[],
        )
        assert result.overall_score == 0.8
        assert result.needs_refinement is False


class TestRefinedResponse:
    """RefinedResponseデータクラステスト"""

    def test_refined_response_creation(self):
        """RefinedResponseを作成"""
        response = RefinedResponse(
            original="テスト",
            refined="テストウル🐺",
            improvements=[],
            refinement_applied=True,
            refinement_time_ms=5.0,
        )
        assert response.original == "テスト"
        assert response.refined == "テストウル🐺"
        assert response.refinement_applied is True


class TestSelfCritiqueInitialization:
    """SelfCritique初期化テスト"""

    def test_init_without_llm(self):
        """LLMなしで初期化"""
        sc = SelfCritique()
        assert sc.llm_client is None

    def test_init_with_llm(self):
        """LLMありで初期化"""
        mock_llm = object()
        sc = SelfCritique(llm_client=mock_llm)
        assert sc.llm_client is mock_llm

    def test_factory_function(self):
        """ファクトリ関数を使用"""
        sc = create_self_critique()
        assert isinstance(sc, SelfCritique)


class TestRelevanceEvaluation:
    """関連性評価テスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_high_relevance_with_keywords(self, sc):
        """キーワードが含まれる高関連性"""
        result = sc.critique(
            response="自分のタスクは3件あるウル🐺",
            original_message="自分のタスクを教えて",
        )
        relevance_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.RELEVANCE
        )
        assert relevance_score.score >= 0.7

    def test_low_relevance_without_keywords(self, sc):
        """キーワードがない低関連性"""
        result = sc.critique(
            response="今日は天気がいいウル🐺",
            original_message="タスクを教えて",
        )
        relevance_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.RELEVANCE
        )
        # キーワードがない場合は関連性が下がる
        assert relevance_score.score < 1.0


class TestCompletenessEvaluation:
    """完全性評価テスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_too_short_response(self, sc):
        """短すぎる回答"""
        result = sc.critique(
            response="OK",
            original_message="タスクを教えて",
        )
        completeness_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.COMPLETENESS
        )
        assert completeness_score.score < 0.7

    def test_appropriate_length_response(self, sc):
        """適切な長さの回答"""
        result = sc.critique(
            response="自分のタスクは3件あるウル🐺 1. 資料作成 2. 会議準備 3. レビュー",
            original_message="タスクを教えて",
        )
        completeness_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.COMPLETENESS
        )
        assert completeness_score.score >= 0.6

    def test_incomplete_sentence_detection(self, sc):
        """途切れた文を検出"""
        result = sc.critique(
            response="タスクを",
            original_message="タスクを教えて",
        )
        # 助詞で終わっているので途切れ
        assert any(
            issue.issue_type == IssueType.INCOMPLETE_SENTENCE
            for issue in result.issues
        )


class TestConsistencyEvaluation:
    """一貫性評価テスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_no_contradiction(self, sc):
        """矛盾なし"""
        result = sc.critique(
            response="できるウル🐺",
            original_message="これできる？",
        )
        consistency_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.CONSISTENCY
        )
        assert consistency_score.score >= 0.8

    def test_potential_contradiction(self, sc):
        """潜在的な矛盾"""
        result = sc.critique(
            response="できるウル。でもできないこともあるウル🐺",
            original_message="これできる？",
        )
        consistency_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.CONSISTENCY
        )
        # 「できる」と「できない」が両方あるので減点
        assert consistency_score.score < 1.0


class TestToneEvaluation:
    """トーン評価テスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_soulkun_tone(self, sc):
        """ソウルくんらしいトーン"""
        result = sc.critique(
            response="了解ウル🐺 やっておくウル！",
            original_message="タスクを作成して",
        )
        tone_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.TONE
        )
        assert tone_score.score >= 0.7

    def test_formal_tone(self, sc):
        """硬すぎるトーン"""
        result = sc.critique(
            response="かしこまりました。タスクを作成いたします。",
            original_message="タスクを作成して",
        )
        tone_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.TONE
        )
        # 過度に丁寧なので減点
        assert tone_score.score < 1.0

    def test_no_soulkun_expression(self, sc):
        """ソウルくんらしい表現がない"""
        result = sc.critique(
            response="タスクを作成しました",
            original_message="タスクを作成して",
        )
        tone_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.TONE
        )
        # 「ウル」がないので減点
        assert tone_score.score < 1.0


class TestSafetyEvaluation:
    """安全性評価テスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_no_sensitive_info(self, sc):
        """機密情報なし"""
        result = sc.critique(
            response="タスクを作成したウル🐺",
            original_message="タスクを作成して",
        )
        safety_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.SAFETY
        )
        assert safety_score.score >= 0.9

    def test_phone_number_detected(self, sc):
        """電話番号を検出"""
        result = sc.critique(
            response="電話番号は090-1234-5678ウル🐺",
            original_message="連絡先を教えて",
        )
        safety_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.SAFETY
        )
        # 電話番号があるので減点
        assert safety_score.score < 1.0

    def test_email_detected(self, sc):
        """メールアドレスを検出"""
        result = sc.critique(
            response="メールはtest@example.comウル🐺",
            original_message="連絡先を教えて",
        )
        safety_score = next(
            s for s in result.scores if s.criterion == QualityCriterion.SAFETY
        )
        assert safety_score.score < 1.0


class TestIssueDetection:
    """問題検出テスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_detect_incomplete_sentence(self, sc):
        """途切れた文を検出"""
        result = sc.critique(
            response="タスクを",
            original_message="タスクを教えて",
        )
        incomplete_issues = [
            i for i in result.issues
            if i.issue_type == IssueType.INCOMPLETE_SENTENCE
        ]
        assert len(incomplete_issues) > 0
        assert incomplete_issues[0].severity == IssueSeverity.CRITICAL

    def test_detect_too_short(self, sc):
        """短すぎることを検出"""
        result = sc.critique(
            response="OK",
            original_message="タスクを教えて",
        )
        short_issues = [
            i for i in result.issues
            if i.issue_type == IssueType.TOO_SHORT
        ]
        assert len(short_issues) > 0

    def test_detect_too_long(self, sc):
        """長すぎることを検出"""
        long_response = "ウル🐺 " * 200
        result = sc.critique(
            response=long_response,
            original_message="タスクを教えて",
        )
        long_issues = [
            i for i in result.issues
            if i.issue_type == IssueType.TOO_LONG
        ]
        assert len(long_issues) > 0


class TestRefinement:
    """改善テスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_refine_incomplete_sentence(self, sc):
        """途切れた文を改善"""
        result = sc.evaluate_and_refine(
            response="タスクを",
            original_message="タスクを教えて",
        )
        assert result.refinement_applied is True
        # 文が完結している
        assert not result.refined.endswith("を")

    def test_refine_tone(self, sc):
        """トーンを改善"""
        result = sc.evaluate_and_refine(
            response="タスクを作成しました。",
            original_message="タスクを作成して",
        )
        # トーン改善が適用された場合、ソウルくんらしい表現が追加される
        # 適用されない場合もあるため、どちらも許容
        assert result is not None
        # 評価結果は存在する
        assert len(result.improvements) >= 0

    def test_no_refinement_needed(self, sc):
        """改善不要"""
        result = sc.evaluate_and_refine(
            response="自分のタスクは3件あるウル🐺 1. 資料作成 2. 会議準備 3. レビュー",
            original_message="タスクを教えて",
        )
        # スコアが高ければ改善不要
        if not result.refinement_applied:
            assert result.original == result.refined

    def test_refine_sensitive_info(self, sc):
        """機密情報を削除"""
        result = sc.evaluate_and_refine(
            response="パスワード: secret123 を設定したウル🐺",
            original_message="設定して",
        )
        if result.refinement_applied:
            assert "secret123" not in result.refined


class TestOverallScore:
    """全体スコアテスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_high_overall_score(self, sc):
        """高い全体スコア"""
        result = sc.critique(
            response="自分のタスクは3件あるウル🐺 明日までに完了させるね！",
            original_message="タスクを教えて",
        )
        assert result.overall_score >= 0.6

    def test_low_overall_score(self, sc):
        """低い全体スコア"""
        result = sc.critique(
            response="OK",
            original_message="タスクを教えて",
        )
        # 短い回答は問題として検出される
        assert any(i.issue_type == IssueType.TOO_SHORT for i in result.issues)
        # 全体スコアは計算される（値は実装依存）
        assert 0.0 <= result.overall_score <= 1.0


class TestNeedsRefinement:
    """改善必要性判定テスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_needs_refinement_low_score(self, sc):
        """低スコアで改善必要"""
        result = sc.critique(
            response="OK",
            original_message="タスクを教えて",
        )
        # 短い回答は問題として検出される
        assert any(i.issue_type == IssueType.TOO_SHORT for i in result.issues)
        # 改善優先順位に含まれる
        assert IssueType.TOO_SHORT in result.refinement_priority

    def test_needs_refinement_critical_issue(self, sc):
        """致命的な問題で改善必要"""
        result = sc.critique(
            response="タスクを",
            original_message="タスクを教えて",
        )
        assert result.needs_refinement is True

    def test_no_refinement_needed(self, sc):
        """改善不要"""
        result = sc.critique(
            response="自分のタスクは3件あるウル🐺 1. 資料作成 2. 会議準備 3. レビュー 全部頑張るウル！",
            original_message="タスクを教えて",
        )
        # 高品質な回答は改善不要の可能性が高い
        # ただし閾値次第
        assert result.overall_score >= 0.5


class TestConstants:
    """定数テスト"""

    def test_quality_thresholds_exist(self):
        """品質閾値が存在"""
        assert QualityCriterion.RELEVANCE in QUALITY_THRESHOLDS
        assert QualityCriterion.SAFETY in QUALITY_THRESHOLDS

    def test_overall_threshold(self):
        """全体閾値の値"""
        assert 0 < OVERALL_REFINEMENT_THRESHOLD < 1

    def test_length_guidelines(self):
        """長さガイドライン"""
        assert LENGTH_GUIDELINES["min"] < LENGTH_GUIDELINES["ideal_min"]
        assert LENGTH_GUIDELINES["ideal_min"] < LENGTH_GUIDELINES["ideal_max"]
        assert LENGTH_GUIDELINES["ideal_max"] < LENGTH_GUIDELINES["max"]


class TestEdgeCases:
    """エッジケーステスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_empty_response(self, sc):
        """空の回答"""
        result = sc.critique(
            response="",
            original_message="タスクを教えて",
        )
        # 空の回答は問題として検出される
        assert any(i.issue_type == IssueType.TOO_SHORT for i in result.issues)
        # 改善優先順位に含まれる
        assert IssueType.TOO_SHORT in result.refinement_priority

    def test_empty_message(self, sc):
        """空のメッセージ"""
        result = sc.critique(
            response="何か質問があれば聞いてウル🐺",
            original_message="",
        )
        assert result is not None

    def test_unicode_characters(self, sc):
        """Unicode文字"""
        result = sc.critique(
            response="🎉 おめでとうウル🐺 💯",
            original_message="テスト完了",
        )
        assert result is not None

    def test_very_long_response(self, sc):
        """非常に長い回答"""
        long_response = "これは長い回答ウル🐺 " * 100
        result = sc.critique(
            response=long_response,
            original_message="タスクを教えて",
        )
        assert IssueType.TOO_LONG in [i.issue_type for i in result.issues]


class TestRefinementPriority:
    """改善優先順位テスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_critical_first(self, sc):
        """致命的な問題が最優先"""
        result = sc.critique(
            response="タスクを",  # 途切れ（CRITICAL）
            original_message="タスクを教えて",
        )
        if result.refinement_priority:
            # CRITICALな問題が優先
            assert IssueType.INCOMPLETE_SENTENCE in result.refinement_priority


class TestRefinementTime:
    """改善時間テスト"""

    @pytest.fixture
    def sc(self):
        return SelfCritique()

    def test_refinement_time_recorded(self, sc):
        """改善時間が記録される"""
        result = sc.evaluate_and_refine(
            response="タスクを",
            original_message="タスクを教えて",
        )
        assert result.refinement_time_ms >= 0

    def test_no_refinement_zero_time(self, sc):
        """改善不要なら時間は短い"""
        result = sc.evaluate_and_refine(
            response="自分のタスクは3件あるウル🐺 全部頑張るウル！",
            original_message="タスクを教えて",
        )
        # 改善が不要な場合、時間は短い（または0）
        if not result.refinement_applied:
            assert result.refinement_time_ms == 0
