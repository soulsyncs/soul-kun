# tests/test_ceo_learning.py
"""
Phase 2D: CEO学習・ガーディアン機能のテスト

テスト対象:
- lib/brain/models.py (CEO Learning関連)
- lib/brain/ceo_teaching_repository.py
- lib/brain/ceo_learning.py
- lib/brain/guardian.py
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from uuid import uuid4
import json

# テスト対象のインポート
from lib.brain.models import (
    TeachingCategory,
    ValidationStatus,
    ConflictType,
    AlertStatus,
    Severity,
    CEOTeaching,
    ConflictInfo,
    GuardianAlert,
    TeachingValidationResult,
    TeachingUsageContext,
    CEOTeachingContext,
)

from lib.brain.ceo_learning import (
    CEOLearningService,
    ExtractedTeaching,
    ProcessingResult,
    format_teachings_for_prompt,
    should_include_teachings,
    CEO_ACCOUNT_IDS,
    TEACHING_CONFIDENCE_THRESHOLD,
    CATEGORY_KEYWORDS,
)

from lib.brain.guardian import (
    GuardianService,
    MVV_VALIDATION_CRITERIA,
    CHOICE_THEORY_CRITERIA,
    SDT_CRITERIA,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_teaching():
    """サンプル教え"""
    return CEOTeaching(
        id=str(uuid4()),
        organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
        ceo_user_id="1728974",
        statement="失敗を恐れずに挑戦することが大切",
        reasoning="失敗から学ぶことで成長できる",
        context="新しいプロジェクトの開始時",
        target="全員",
        category=TeachingCategory.CULTURE,
        keywords=["失敗", "挑戦", "成長"],
        validation_status=ValidationStatus.VERIFIED,
        priority=7,
        is_active=True,
        usage_count=5,
        helpful_count=3,
    )


@pytest.fixture
def sample_conflict():
    """サンプル矛盾情報"""
    return ConflictInfo(
        id=str(uuid4()),
        organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
        teaching_id=str(uuid4()),
        conflict_type=ConflictType.SDT,
        conflict_subtype="autonomy",
        description="強制的な表現が自律性を損なう可能性があります",
        reference="SDT: 自律性（自分で決める感覚）",
        severity=Severity.MEDIUM,
    )


@pytest.fixture
def sample_alert(sample_teaching, sample_conflict):
    """サンプルアラート"""
    return GuardianAlert(
        id=str(uuid4()),
        organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
        teaching_id=sample_teaching.id,
        conflict_summary="軽微な矛盾が1件検出されました",
        alert_message="🐺 確認させてほしいウル",
        alternative_suggestion="別の表現を検討してください",
        conflicts=[sample_conflict],
        status=AlertStatus.PENDING,
    )


@pytest.fixture
def mock_pool():
    """モックDBプール"""
    pool = Mock()
    conn = Mock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=None)

    # Mock execute result - DBクエリ結果をシミュレート
    mock_result = Mock()
    mock_result.fetchall.return_value = []  # 空リストを返す
    mock_result.fetchone.return_value = None  # Noneを返す
    mock_result.rowcount = 0
    conn.execute.return_value = mock_result
    conn.commit = Mock()

    pool.connect.return_value = conn
    return pool


# =============================================================================
# TeachingCategory Tests
# =============================================================================


class TestTeachingCategory:
    """TeachingCategoryのテスト"""

    def test_all_categories_exist(self):
        """全カテゴリが存在すること"""
        expected_categories = [
            "mvv_mission", "mvv_vision", "mvv_values",
            "choice_theory", "sdt", "servant", "psych_safety",
            "biz_sales", "biz_hr", "biz_accounting", "biz_general",
            "culture", "communication", "staff_guidance",
            "other",
        ]
        actual_values = [c.value for c in TeachingCategory]
        for expected in expected_categories:
            assert expected in actual_values

    def test_category_from_value(self):
        """値からカテゴリを取得できること"""
        assert TeachingCategory("mvv_mission") == TeachingCategory.MVV_MISSION
        assert TeachingCategory("choice_theory") == TeachingCategory.CHOICE_THEORY


class TestValidationStatus:
    """ValidationStatusのテスト"""

    def test_all_statuses_exist(self):
        """全ステータスが存在すること"""
        expected = ["pending", "verified", "alert_pending", "overridden"]
        actual = [s.value for s in ValidationStatus]
        assert sorted(expected) == sorted(actual)


class TestConflictType:
    """ConflictTypeのテスト"""

    def test_all_conflict_types_exist(self):
        """全矛盾タイプが存在すること"""
        expected = ["mvv", "choice_theory", "sdt", "guidelines", "existing"]
        actual = [c.value for c in ConflictType]
        assert sorted(expected) == sorted(actual)


class TestAlertStatus:
    """AlertStatusのテスト"""

    def test_all_alert_statuses_exist(self):
        """全アラートステータスが存在すること"""
        expected = ["pending", "acknowledged", "overridden", "retracted"]
        actual = [s.value for s in AlertStatus]
        assert sorted(expected) == sorted(actual)


class TestSeverity:
    """Severityのテスト"""

    def test_all_severities_exist(self):
        """全深刻度が存在すること"""
        expected = ["high", "medium", "low"]
        actual = [s.value for s in Severity]
        assert sorted(expected) == sorted(actual)


# =============================================================================
# CEOTeaching Tests
# =============================================================================


class TestCEOTeaching:
    """CEOTeachingのテスト"""

    def test_create_teaching(self, sample_teaching):
        """教えを作成できること"""
        assert sample_teaching.statement == "失敗を恐れずに挑戦することが大切"
        assert sample_teaching.category == TeachingCategory.CULTURE
        assert sample_teaching.is_active is True

    def test_is_relevant_to_keyword_match(self, sample_teaching):
        """キーワードマッチで関連度を判定できること"""
        assert sample_teaching.is_relevant_to("失敗") is True
        assert sample_teaching.is_relevant_to("挑戦") is True
        assert sample_teaching.is_relevant_to("無関係") is False

    def test_is_relevant_to_statement_match(self, sample_teaching):
        """主張内容で関連度を判定できること"""
        assert sample_teaching.is_relevant_to("大切") is True

    def test_to_prompt_context(self, sample_teaching):
        """プロンプト用コンテキストを生成できること"""
        context = sample_teaching.to_prompt_context()
        assert "culture" in context
        assert "失敗を恐れずに挑戦" in context
        assert "理由" in context


# =============================================================================
# ConflictInfo Tests
# =============================================================================


class TestConflictInfo:
    """ConflictInfoのテスト"""

    def test_create_conflict(self, sample_conflict):
        """矛盾情報を作成できること"""
        assert sample_conflict.conflict_type == ConflictType.SDT
        assert sample_conflict.severity == Severity.MEDIUM

    def test_to_alert_summary(self, sample_conflict):
        """アラート用要約を生成できること"""
        summary = sample_conflict.to_alert_summary()
        assert "🟡" in summary  # MEDIUM severity
        assert "sdt" in summary
        assert "自律性" in summary


# =============================================================================
# GuardianAlert Tests
# =============================================================================


class TestGuardianAlert:
    """GuardianAlertのテスト"""

    def test_create_alert(self, sample_alert):
        """アラートを作成できること"""
        assert sample_alert.status == AlertStatus.PENDING
        assert len(sample_alert.conflicts) == 1

    def test_is_resolved(self, sample_alert):
        """解決済み判定が正しいこと"""
        assert sample_alert.is_resolved is False

        sample_alert.status = AlertStatus.ACKNOWLEDGED
        assert sample_alert.is_resolved is True

    def test_max_severity(self, sample_alert):
        """最大深刻度を取得できること"""
        assert sample_alert.max_severity == Severity.MEDIUM

        # HIGH深刻度を追加
        high_conflict = ConflictInfo(
            conflict_type=ConflictType.MVV,
            description="重大な矛盾",
            reference="MVV",
            severity=Severity.HIGH,
        )
        sample_alert.conflicts.append(high_conflict)
        assert sample_alert.max_severity == Severity.HIGH

    def test_generate_alert_message(self, sample_alert, sample_teaching):
        """アラートメッセージを生成できること"""
        message = sample_alert.generate_alert_message(sample_teaching)
        assert "🐺" in message
        assert "1️⃣" in message
        assert "2️⃣" in message
        assert "3️⃣" in message


# =============================================================================
# TeachingValidationResult Tests
# =============================================================================


class TestTeachingValidationResult:
    """TeachingValidationResultのテスト"""

    def test_should_alert_with_invalid(self, sample_teaching, sample_conflict):
        """無効な結果でアラートすべきと判定されること"""
        result = TeachingValidationResult(
            teaching=sample_teaching,
            is_valid=False,
            conflicts=[sample_conflict],
        )
        assert result.should_alert() is True

    def test_should_alert_with_high_severity(self, sample_teaching):
        """HIGH深刻度でアラートすべきと判定されること"""
        high_conflict = ConflictInfo(
            conflict_type=ConflictType.MVV,
            description="重大な矛盾",
            reference="MVV",
            severity=Severity.HIGH,
        )
        result = TeachingValidationResult(
            teaching=sample_teaching,
            is_valid=True,
            conflicts=[high_conflict],
        )
        assert result.should_alert() is True

    def test_should_alert_with_low_score(self, sample_teaching):
        """低スコアでアラートすべきと判定されること"""
        result = TeachingValidationResult(
            teaching=sample_teaching,
            is_valid=True,
            overall_score=0.3,
        )
        assert result.should_alert() is True

    def test_should_not_alert_when_valid(self, sample_teaching):
        """有効な結果でアラート不要と判定されること"""
        result = TeachingValidationResult(
            teaching=sample_teaching,
            is_valid=True,
            overall_score=0.9,
        )
        assert result.should_alert() is False


# =============================================================================
# CEOTeachingContext Tests
# =============================================================================


class TestCEOTeachingContext:
    """CEOTeachingContextのテスト"""

    def test_get_top_teachings(self, sample_teaching):
        """上位教えを取得できること"""
        context = CEOTeachingContext(
            relevant_teachings=[sample_teaching],
        )
        top = context.get_top_teachings(1)
        assert len(top) == 1
        assert top[0] == sample_teaching

    def test_has_pending_alerts(self, sample_alert):
        """未解決アラートの有無を判定できること"""
        context = CEOTeachingContext()
        assert context.has_pending_alerts() is False

        context.pending_alerts = [sample_alert]
        assert context.has_pending_alerts() is True

    def test_to_prompt_context(self, sample_teaching):
        """プロンプト用コンテキストを生成できること"""
        context = CEOTeachingContext(
            relevant_teachings=[sample_teaching],
        )
        prompt = context.to_prompt_context()
        assert "会社の教え" in prompt
        assert sample_teaching.statement in prompt


# =============================================================================
# CEOLearningService Tests
# =============================================================================


class TestCEOLearningService:
    """CEOLearningServiceのテスト"""

    def test_is_ceo_user(self, mock_pool):
        """CEOユーザー判定が正しいこと"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        # CEO
        assert service.is_ceo_user("1728974") is True

        # 一般ユーザー
        assert service.is_ceo_user("1234567") is False

    def test_is_ceo_user_with_ceo_user_id_match(self, mock_pool):
        """ceo_user_id指定時、DB照合で一致すればTrue"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")
        service._get_user_id_from_account_id = MagicMock(return_value="uuid-ceo-123")
        assert service.is_ceo_user("1728974", ceo_user_id="uuid-ceo-123") is True

    def test_is_ceo_user_with_ceo_user_id_mismatch(self, mock_pool):
        """ceo_user_id指定時、DB照合で不一致ならFalse"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")
        service._get_user_id_from_account_id = MagicMock(return_value="uuid-other-456")
        assert service.is_ceo_user("1728974", ceo_user_id="uuid-ceo-123") is False

    def test_is_ceo_user_with_ceo_user_id_db_miss_fallback(self, mock_pool):
        """ceo_user_id指定時、DB照合失敗ならCEO_ACCOUNT_IDSにフォールバック"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")
        service._get_user_id_from_account_id = MagicMock(return_value=None)
        # CEO_ACCOUNT_IDSにある → True
        assert service.is_ceo_user("1728974", ceo_user_id="uuid-ceo-123") is True
        # CEO_ACCOUNT_IDSにない → False
        assert service.is_ceo_user("9999999", ceo_user_id="uuid-ceo-123") is False

    def test_estimate_categories_mvv(self, mock_pool):
        """MVVカテゴリを推定できること"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        categories = service._estimate_categories("可能性を信じることが大切")
        assert TeachingCategory.MVV_MISSION in categories

    def test_estimate_categories_choice_theory(self, mock_pool):
        """選択理論カテゴリを推定できること"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        categories = service._estimate_categories("5つの欲求を意識しよう")
        assert TeachingCategory.CHOICE_THEORY in categories

    def test_calculate_relevance_score(self, mock_pool, sample_teaching):
        """関連度スコアを計算できること"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        score = service._calculate_relevance_score(
            sample_teaching,
            "失敗を恐れない",
            None,
        )
        assert 0.0 <= score <= 1.0
        assert score > 0.1  # キーワードマッチがあるので0以上

    @pytest.mark.asyncio
    async def test_process_ceo_message_non_ceo(self, mock_pool):
        """非CEOのメッセージは処理されないこと"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        result = await service.process_ceo_message(
            message="テストメッセージ",
            room_id="123",
            account_id="9999999",  # 非CEO
        )

        assert result.success is False
        assert "CEOユーザーではありません" in result.message

    @pytest.mark.asyncio
    async def test_process_ceo_message_no_llm(self, mock_pool):
        """LLMなしでは教え抽出されないこと"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        result = await service.process_ceo_message(
            message="挑戦を恐れるな",
            room_id="123",
            account_id="1728974",  # CEO
        )

        assert result.success is True
        assert result.teachings_extracted == 0

    def test_parse_extraction_response(self, mock_pool):
        """抽出レスポンスを解析できること"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        response = """
```json
{
  "teachings": [
    {
      "statement": "テスト教え",
      "reasoning": "テスト理由",
      "context": "テスト文脈",
      "target": "全員",
      "category": "culture",
      "keywords": ["テスト"],
      "confidence": 0.85
    }
  ]
}
```
"""
        teachings = service._parse_extraction_response(response)
        assert len(teachings) == 1
        assert teachings[0].statement == "テスト教え"
        assert teachings[0].confidence == 0.85

    def test_parse_extraction_response_empty(self, mock_pool):
        """空レスポンスを解析できること"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        response = """```json
{"teachings": []}
```"""
        teachings = service._parse_extraction_response(response)
        assert len(teachings) == 0

    def test_parse_extraction_response_invalid(self, mock_pool):
        """無効なレスポンスをハンドリングできること"""
        service = CEOLearningService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        teachings = service._parse_extraction_response("invalid json")
        assert len(teachings) == 0


# =============================================================================
# format_teachings_for_prompt Tests
# =============================================================================


class TestFormatTeachingsForPrompt:
    """format_teachings_for_promptのテスト"""

    def test_empty_teachings(self):
        """空リストで空文字列を返すこと"""
        result = format_teachings_for_prompt([])
        assert result == ""

    def test_single_teaching(self, sample_teaching):
        """単一の教えをフォーマットできること"""
        result = format_teachings_for_prompt([sample_teaching])
        assert "ソウルシンクスとして大事にしていること" in result
        assert sample_teaching.statement in result

    def test_respects_max_teachings(self, sample_teaching):
        """最大件数を尊重すること"""
        teachings = [sample_teaching] * 5
        result = format_teachings_for_prompt(teachings, max_teachings=2)
        # 2件のみ含まれる
        count = result.count(sample_teaching.statement)
        assert count == 2

    def test_includes_ceo_name_warning(self, sample_teaching):
        """CEO名前非表示の注意が含まれること"""
        result = format_teachings_for_prompt([sample_teaching])
        assert "菊地さんが言っていた" in result
        assert "絶対に言わない" in result


class TestShouldIncludeTeachings:
    """should_include_teachingsのテスト"""

    def test_excludes_ceo(self):
        """CEOには教えを含めないこと"""
        result = should_include_teachings(None, "1728974")
        assert result is False

    def test_includes_staff(self):
        """一般スタッフには教えを含めること"""
        result = should_include_teachings(None, "1234567")
        assert result is True


# =============================================================================
# GuardianService Tests
# =============================================================================


class TestGuardianService:
    """GuardianServiceのテスト"""

    def test_parse_severity(self, mock_pool):
        """深刻度を解析できること"""
        service = GuardianService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        assert service._parse_severity("high") == Severity.HIGH
        assert service._parse_severity("medium") == Severity.MEDIUM
        assert service._parse_severity("low") == Severity.LOW
        assert service._parse_severity("unknown") == Severity.MEDIUM  # デフォルト

    def test_generate_conflict_summary_no_conflicts(self, mock_pool):
        """矛盾なしの要約を生成できること"""
        service = GuardianService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        summary = service._generate_conflict_summary([])
        assert "検出されませんでした" in summary

    def test_generate_conflict_summary_with_conflicts(self, mock_pool, sample_conflict):
        """矛盾ありの要約を生成できること"""
        service = GuardianService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        summary = service._generate_conflict_summary([sample_conflict])
        assert "軽微な矛盾が1件" in summary

    def test_generate_conflict_summary_with_high_severity(self, mock_pool):
        """HIGH深刻度の要約を生成できること"""
        service = GuardianService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        high_conflict = ConflictInfo(
            conflict_type=ConflictType.MVV,
            description="重大な矛盾",
            reference="MVV",
            severity=Severity.HIGH,
        )
        summary = service._generate_conflict_summary([high_conflict])
        assert "重要な矛盾が1件" in summary

    def test_generate_alert_message(self, mock_pool, sample_teaching, sample_conflict):
        """アラートメッセージを生成できること"""
        service = GuardianService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        message = service._generate_alert_message(
            sample_teaching,
            [sample_conflict],
            "代替案テスト",
        )
        assert "🐺" in message
        assert "確認させてほしいウル" in message
        assert "代替案テスト" in message
        assert "1️⃣" in message

    def test_parse_llm_response_valid(self, mock_pool):
        """有効なLLMレスポンスを解析できること"""
        service = GuardianService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        response = """
```json
{
  "overall_alignment": true,
  "overall_score": 0.9
}
```
"""
        result = service._parse_llm_response(response)
        assert result["overall_alignment"] is True
        assert result["overall_score"] == 0.9

    def test_parse_llm_response_invalid(self, mock_pool):
        """無効なLLMレスポンスをハンドリングできること"""
        service = GuardianService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        result = service._parse_llm_response("invalid json")
        assert result["overall_alignment"] is True  # デフォルト
        assert result["overall_score"] == 0.8  # デフォルト

    @pytest.mark.asyncio
    async def test_validate_teaching_no_llm(self, mock_pool, sample_teaching):
        """LLMなしで検証が安全に完了すること"""
        service = GuardianService(mock_pool, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        result = await service.validate_teaching(sample_teaching)
        assert result.is_valid is True
        assert result.overall_score >= 0.5


# =============================================================================
# Validation Criteria Tests
# =============================================================================


class TestValidationCriteria:
    """検証基準のテスト"""

    def test_mvv_criteria_structure(self):
        """MVV基準の構造が正しいこと"""
        assert "mission" in MVV_VALIDATION_CRITERIA
        assert "vision" in MVV_VALIDATION_CRITERIA
        assert "values" in MVV_VALIDATION_CRITERIA

        mission = MVV_VALIDATION_CRITERIA["mission"]
        assert "statement" in mission
        assert "core_concepts" in mission
        assert "anti_patterns" in mission

    def test_choice_theory_criteria_structure(self):
        """選択理論基準の構造が正しいこと"""
        assert "five_basic_needs" in CHOICE_THEORY_CRITERIA
        assert "lead_management" in CHOICE_THEORY_CRITERIA
        assert "core_principle" in CHOICE_THEORY_CRITERIA

        needs = CHOICE_THEORY_CRITERIA["five_basic_needs"]
        assert "survival" in needs
        assert "love" in needs
        assert "power" in needs
        assert "freedom" in needs
        assert "fun" in needs

    def test_sdt_criteria_structure(self):
        """SDT基準の構造が正しいこと"""
        assert "autonomy" in SDT_CRITERIA
        assert "competence" in SDT_CRITERIA
        assert "relatedness" in SDT_CRITERIA

        for key in SDT_CRITERIA:
            criteria = SDT_CRITERIA[key]
            assert "description" in criteria
            assert "valid_approaches" in criteria
            assert "violations" in criteria


# =============================================================================
# Category Keywords Tests
# =============================================================================


class TestCategoryKeywords:
    """カテゴリキーワードのテスト"""

    def test_all_categories_have_keywords(self):
        """全カテゴリにキーワードがあること"""
        for category in TeachingCategory:
            if category != TeachingCategory.OTHER:
                assert category in CATEGORY_KEYWORDS
                assert len(CATEGORY_KEYWORDS[category]) > 0

    def test_mvv_keywords(self):
        """MVVキーワードが適切であること"""
        mvv_keywords = CATEGORY_KEYWORDS[TeachingCategory.MVV_MISSION]
        assert "可能性" in mvv_keywords
        assert "解放" in mvv_keywords

    def test_choice_theory_keywords(self):
        """選択理論キーワードが適切であること"""
        ct_keywords = CATEGORY_KEYWORDS[TeachingCategory.CHOICE_THEORY]
        assert "選択理論" in ct_keywords
        assert "5つの欲求" in ct_keywords


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_ceo_account_ids(self):
        """CEOアカウントIDが設定されていること"""
        assert len(CEO_ACCOUNT_IDS) > 0
        assert "1728974" in CEO_ACCOUNT_IDS

    def test_teaching_confidence_threshold(self):
        """教え確信度閾値が適切であること"""
        assert 0 < TEACHING_CONFIDENCE_THRESHOLD < 1
        assert TEACHING_CONFIDENCE_THRESHOLD == 0.7


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """統合テスト"""

    def test_teaching_flow(self, sample_teaching, sample_conflict):
        """教えのフローが正しく動作すること"""
        # 1. 教えを作成
        assert sample_teaching.validation_status == ValidationStatus.VERIFIED

        # 2. 矛盾を検出
        sample_teaching.validation_status = ValidationStatus.ALERT_PENDING

        # 3. アラートを生成
        alert = GuardianAlert(
            teaching_id=sample_teaching.id,
            conflict_summary="矛盾が検出されました",
            alert_message="確認が必要です",
            conflicts=[sample_conflict],
        )
        assert alert.is_resolved is False

        # 4. アラートを解決
        alert.status = AlertStatus.OVERRIDDEN
        assert alert.is_resolved is True

        # 5. 教えを有効化
        sample_teaching.validation_status = ValidationStatus.OVERRIDDEN
        assert sample_teaching.is_active is True

    def test_context_generation(self, sample_teaching, sample_alert):
        """コンテキスト生成が正しく動作すること"""
        context = CEOTeachingContext(
            relevant_teachings=[sample_teaching],
            pending_alerts=[sample_alert],
            is_ceo_user=True,
        )

        # 教えを取得
        top_teachings = context.get_top_teachings(1)
        assert len(top_teachings) == 1

        # アラートを確認
        assert context.has_pending_alerts() is True

        # プロンプト生成
        prompt = context.to_prompt_context()
        assert len(prompt) > 0
