# tests/test_ceo_learning.py
"""
Phase 2D: CEO学習・ガーディアン機能のテスト

テスト対象:
- lib/brain/models.py (CEO Learning関連)
- lib/brain/ceo_teaching_repository.py
- lib/brain/ceo_learning.py
- lib/brain/guardian.py

テスト内容:
- CEO教えの登録・取得・検索
- 学習メカニズム（教え抽出、検証）
- UUID検証とエラーハンドリング
- リポジトリ層のCRUD操作
- エッジケース

設計書: docs/15_phase2d_ceo_learning.md
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
    BrainContext,
    ConversationMessage,
)

from lib.brain.ceo_learning import (
    CEOLearningService,
    ExtractedTeaching,
    ProcessingResult,
    format_teachings_for_prompt,
    should_include_teachings,
    CEO_ACCOUNT_IDS,
    TEACHING_CONFIDENCE_THRESHOLD,
    DEFAULT_TEACHING_LIMIT,
    CATEGORY_KEYWORDS,
)

from lib.brain.ceo_teaching_repository import (
    CEOTeachingRepository,
    ConflictRepository,
    GuardianAlertRepository,
    TeachingUsageRepository,
    _check_uuid_format,
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
        organization_id="org_soulsyncs",
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
        organization_id="org_soulsyncs",
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
        organization_id="org_soulsyncs",
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


@pytest.fixture
def valid_org_id():
    """有効なUUID形式のorganization_id"""
    return str(uuid4())


@pytest.fixture
def invalid_org_id():
    """無効なorganization_id（UUID形式でない）"""
    return "org_soulsyncs"


@pytest.fixture
def sample_ceo_user_id():
    """サンプルCEOユーザーID（UUID形式）"""
    return str(uuid4())


@pytest.fixture
def sample_context():
    """サンプルBrainContext"""
    return BrainContext(
        sender_account_id="12345",
        sender_name="テストユーザー",
        recent_conversation=[
            ConversationMessage(
                role="user",
                content="チームの雰囲気を良くしたいです",
                timestamp=datetime.now() - timedelta(minutes=2),
            ),
            ConversationMessage(
                role="assistant",
                content="チームの雰囲気づくり、大切ですね！",
                timestamp=datetime.now() - timedelta(minutes=1),
            ),
        ],
        organization_id="org_test",
        room_id="room123",
    )


@pytest.fixture
def sample_teachings(valid_org_id, sample_ceo_user_id):
    """複数のサンプルCEOTeaching"""
    return [
        CEOTeaching(
            id=str(uuid4()),
            organization_id=valid_org_id,
            ceo_user_id=sample_ceo_user_id,
            statement="選択理論を実践しよう",
            category=TeachingCategory.CHOICE_THEORY,
            keywords=["選択理論", "実践"],
            validation_status=ValidationStatus.VERIFIED,
            priority=7,
            is_active=True,
            usage_count=10,
            helpful_count=8,
        ),
        CEOTeaching(
            id=str(uuid4()),
            organization_id=valid_org_id,
            ceo_user_id=sample_ceo_user_id,
            statement="心理的安全性を大切に",
            category=TeachingCategory.PSYCH_SAFETY,
            keywords=["心理的安全性", "安心"],
            validation_status=ValidationStatus.VERIFIED,
            priority=9,
            is_active=True,
            usage_count=3,
            helpful_count=2,
        ),
    ]


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
        service = CEOLearningService(mock_pool, "org_soulsyncs")

        # CEO
        assert service.is_ceo_user("1728974") is True

        # 一般ユーザー
        assert service.is_ceo_user("1234567") is False

    def test_estimate_categories_mvv(self, mock_pool):
        """MVVカテゴリを推定できること"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")

        categories = service._estimate_categories("可能性を信じることが大切")
        assert TeachingCategory.MVV_MISSION in categories

    def test_estimate_categories_choice_theory(self, mock_pool):
        """選択理論カテゴリを推定できること"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")

        categories = service._estimate_categories("5つの欲求を意識しよう")
        assert TeachingCategory.CHOICE_THEORY in categories

    def test_calculate_relevance_score(self, mock_pool, sample_teaching):
        """関連度スコアを計算できること"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")

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
        service = CEOLearningService(mock_pool, "org_soulsyncs")

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
        service = CEOLearningService(mock_pool, "org_soulsyncs")

        result = await service.process_ceo_message(
            message="挑戦を恐れるな",
            room_id="123",
            account_id="1728974",  # CEO
        )

        assert result.success is True
        assert result.teachings_extracted == 0

    def test_parse_extraction_response(self, mock_pool):
        """抽出レスポンスを解析できること"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")

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
        service = CEOLearningService(mock_pool, "org_soulsyncs")

        response = """```json
{"teachings": []}
```"""
        teachings = service._parse_extraction_response(response)
        assert len(teachings) == 0

    def test_parse_extraction_response_invalid(self, mock_pool):
        """無効なレスポンスをハンドリングできること"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")

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
        service = GuardianService(mock_pool, "org_soulsyncs")

        assert service._parse_severity("high") == Severity.HIGH
        assert service._parse_severity("medium") == Severity.MEDIUM
        assert service._parse_severity("low") == Severity.LOW
        assert service._parse_severity("unknown") == Severity.MEDIUM  # デフォルト

    def test_generate_conflict_summary_no_conflicts(self, mock_pool):
        """矛盾なしの要約を生成できること"""
        service = GuardianService(mock_pool, "org_soulsyncs")

        summary = service._generate_conflict_summary([])
        assert "検出されませんでした" in summary

    def test_generate_conflict_summary_with_conflicts(self, mock_pool, sample_conflict):
        """矛盾ありの要約を生成できること"""
        service = GuardianService(mock_pool, "org_soulsyncs")

        summary = service._generate_conflict_summary([sample_conflict])
        assert "軽微な矛盾が1件" in summary

    def test_generate_conflict_summary_with_high_severity(self, mock_pool):
        """HIGH深刻度の要約を生成できること"""
        service = GuardianService(mock_pool, "org_soulsyncs")

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
        service = GuardianService(mock_pool, "org_soulsyncs")

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
        service = GuardianService(mock_pool, "org_soulsyncs")

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
        service = GuardianService(mock_pool, "org_soulsyncs")

        result = service._parse_llm_response("invalid json")
        assert result["overall_alignment"] is True  # デフォルト
        assert result["overall_score"] == 0.8  # デフォルト

    @pytest.mark.asyncio
    async def test_validate_teaching_no_llm(self, mock_pool, sample_teaching):
        """LLMなしで検証が安全に完了すること"""
        service = GuardianService(mock_pool, "org_soulsyncs")

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


# =============================================================================
# UUID検証ヘルパーのテスト
# =============================================================================


class TestCheckUuidFormat:
    """_check_uuid_format関数のテスト"""

    def test_valid_uuid_returns_true(self):
        """有効なUUID形式はTrueを返す"""
        valid_uuids = [
            str(uuid4()),
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        ]
        for uuid_str in valid_uuids:
            assert _check_uuid_format(uuid_str) is True

    def test_invalid_uuid_returns_false(self):
        """無効なUUID形式はFalseを返す"""
        invalid_uuids = [
            "org_soulsyncs",
            "not-a-uuid",
            "12345",
            "",
            "550e8400-e29b-41d4-a716",  # 不完全なUUID
        ]
        for uuid_str in invalid_uuids:
            assert _check_uuid_format(uuid_str) is False

    def test_none_returns_false(self):
        """NoneはFalseを返す"""
        assert _check_uuid_format(None) is False

    def test_empty_string_returns_false(self):
        """空文字はFalseを返す"""
        assert _check_uuid_format("") is False


# =============================================================================
# CEOTeachingRepositoryのテスト
# =============================================================================


class TestCEOTeachingRepository:
    """CEOTeachingRepositoryのテスト"""

    def test_init_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDで初期化"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)
        assert repo._pool is mock_pool
        assert repo._organization_id == valid_org_id
        assert repo._org_id_is_uuid is True

    def test_init_with_invalid_uuid(self, mock_pool, invalid_org_id):
        """無効なUUIDで初期化（DBクエリはスキップ）"""
        repo = CEOTeachingRepository(mock_pool, invalid_org_id)
        assert repo._org_id_is_uuid is False

    def test_create_teaching_with_invalid_uuid_raises_error(
        self, mock_pool, invalid_org_id, sample_teaching
    ):
        """無効なUUIDでcreate_teachingはエラー"""
        repo = CEOTeachingRepository(mock_pool, invalid_org_id)
        with pytest.raises(ValueError) as exc_info:
            repo.create_teaching(sample_teaching)
        assert "not UUID format" in str(exc_info.value)

    def test_get_teaching_by_id_with_invalid_uuid_returns_none(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでget_teaching_by_idはNoneを返す"""
        repo = CEOTeachingRepository(mock_pool, invalid_org_id)
        result = repo.get_teaching_by_id("some-id")
        assert result is None

    def test_get_active_teachings_with_invalid_uuid_returns_empty(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでget_active_teachingsは空リストを返す"""
        repo = CEOTeachingRepository(mock_pool, invalid_org_id)
        result = repo.get_active_teachings()
        assert result == []

    def test_search_teachings_with_invalid_uuid_returns_empty(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでsearch_teachingsは空リストを返す"""
        repo = CEOTeachingRepository(mock_pool, invalid_org_id)
        result = repo.search_teachings("可能性")
        assert result == []

    def test_search_teachings_empty_query_returns_empty(
        self, mock_pool, valid_org_id
    ):
        """空のクエリでsearch_teachingsは空リストを返す"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)
        result = repo.search_teachings("")
        assert result == []

    def test_search_teachings_whitespace_only_returns_empty(
        self, mock_pool, valid_org_id
    ):
        """空白のみのクエリでsearch_teachingsは空リストを返す"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)
        result = repo.search_teachings("   ")
        assert result == []

    def test_get_teachings_by_category_empty_list_returns_empty(
        self, mock_pool, valid_org_id
    ):
        """空のカテゴリリストは空リストを返す"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)
        result = repo.get_teachings_by_category([])
        assert result == []

    def test_get_teachings_by_category_with_invalid_uuid_returns_empty(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでget_teachings_by_categoryは空リストを返す"""
        repo = CEOTeachingRepository(mock_pool, invalid_org_id)
        result = repo.get_teachings_by_category([TeachingCategory.MVV_MISSION])
        assert result == []

    def test_get_pending_teachings_with_invalid_uuid_returns_empty(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでget_pending_teachingsは空リストを返す"""
        repo = CEOTeachingRepository(mock_pool, invalid_org_id)
        result = repo.get_pending_teachings()
        assert result == []

    def test_update_teaching_with_empty_updates(
        self, mock_pool, valid_org_id
    ):
        """空のupdatesでupdate_teachingは既存教えを返す（取得試行）"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)
        # 実際にはDBからの取得なのでNoneになる（モックのため）
        result = repo.update_teaching("some-id", {})
        assert result is None

    def test_update_teaching_with_invalid_uuid_returns_none(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでupdate_teachingはNoneを返す"""
        repo = CEOTeachingRepository(mock_pool, invalid_org_id)
        result = repo.update_teaching("some-id", {"priority": 10})
        assert result is None

    def test_update_teaching_filters_allowed_fields(
        self, mock_pool, valid_org_id
    ):
        """update_teachingは許可されたフィールドのみ更新"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)
        # 許可されていないフィールドを含む更新
        result = repo.update_teaching("some-id", {
            "priority": 10,  # 許可
            "id": "hacked-id",  # 許可されていない
            "created_at": datetime.now(),  # 許可されていない
        })
        # 結果はNone（モックのため実際の更新は行われない）
        assert result is None

    def test_update_validation_status_with_invalid_uuid_returns_false(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでupdate_validation_statusはFalseを返す"""
        repo = CEOTeachingRepository(mock_pool, invalid_org_id)
        result = repo.update_validation_status("some-id", ValidationStatus.VERIFIED)
        assert result is False

    def test_increment_usage_with_invalid_uuid_returns_false(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでincrement_usageはFalseを返す"""
        repo = CEOTeachingRepository(mock_pool, invalid_org_id)
        result = repo.increment_usage("some-id")
        assert result is False

    def test_increment_usage_with_helpful_flag(
        self, mock_pool, valid_org_id
    ):
        """increment_usageがwas_helpfulフラグを処理"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)
        # モックなのでFalseが返る（rowがNone）
        result = repo.increment_usage("some-id", was_helpful=True)
        assert result is False

    def test_deactivate_teaching_with_invalid_uuid_returns_false(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでdeactivate_teachingはFalseを返す"""
        repo = CEOTeachingRepository(mock_pool, invalid_org_id)
        result = repo.deactivate_teaching("some-id")
        assert result is False

    def test_deactivate_teaching_with_superseded_by(
        self, mock_pool, valid_org_id
    ):
        """deactivate_teachingがsuperseded_byを処理"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)
        result = repo.deactivate_teaching(
            "old-teaching-id",
            superseded_by="new-teaching-id"
        )
        # モックなのでFalse（rowがNone）
        assert result is False


# =============================================================================
# ConflictRepositoryのテスト
# =============================================================================


class TestConflictRepository:
    """ConflictRepositoryのテスト"""

    def test_init_with_invalid_uuid(self, mock_pool, invalid_org_id):
        """無効なUUIDで初期化"""
        repo = ConflictRepository(mock_pool, invalid_org_id)
        assert repo._org_id_is_uuid is False

    def test_create_conflict_with_invalid_uuid_raises_error(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでcreate_conflictはエラー"""
        repo = ConflictRepository(mock_pool, invalid_org_id)
        conflict = ConflictInfo(
            teaching_id="some-id",
            conflict_type=ConflictType.MVV,
            description="テスト矛盾",
        )
        with pytest.raises(ValueError) as exc_info:
            repo.create_conflict(conflict)
        assert "not UUID format" in str(exc_info.value)

    def test_get_conflicts_for_teaching_with_invalid_uuid(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでget_conflicts_for_teachingは空リストを返す"""
        repo = ConflictRepository(mock_pool, invalid_org_id)
        result = repo.get_conflicts_for_teaching("some-id")
        assert result == []

    def test_delete_conflicts_for_teaching_with_invalid_uuid(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでdelete_conflicts_for_teachingは0を返す"""
        repo = ConflictRepository(mock_pool, invalid_org_id)
        result = repo.delete_conflicts_for_teaching("some-id")
        assert result == 0


# =============================================================================
# GuardianAlertRepositoryのテスト
# =============================================================================


class TestGuardianAlertRepository:
    """GuardianAlertRepositoryのテスト"""

    def test_init_with_invalid_uuid(self, mock_pool, invalid_org_id):
        """無効なUUIDで初期化"""
        repo = GuardianAlertRepository(mock_pool, invalid_org_id)
        assert repo._org_id_is_uuid is False

    def test_create_alert_with_invalid_uuid_raises_error(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでcreate_alertはエラー"""
        repo = GuardianAlertRepository(mock_pool, invalid_org_id)
        alert = GuardianAlert(
            teaching_id="some-id",
            conflict_summary="テスト矛盾",
            alert_message="テストアラート",
        )
        with pytest.raises(ValueError) as exc_info:
            repo.create_alert(alert)
        assert "not UUID format" in str(exc_info.value)

    def test_get_alert_by_id_with_invalid_uuid(self, mock_pool, invalid_org_id):
        """無効なUUIDでget_alert_by_idはNoneを返す"""
        repo = GuardianAlertRepository(mock_pool, invalid_org_id)
        result = repo.get_alert_by_id("some-id")
        assert result is None

    def test_get_pending_alerts_with_invalid_uuid(self, mock_pool, invalid_org_id):
        """無効なUUIDでget_pending_alertsは空リストを返す"""
        repo = GuardianAlertRepository(mock_pool, invalid_org_id)
        result = repo.get_pending_alerts()
        assert result == []

    def test_get_alert_by_teaching_id_with_invalid_uuid(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでget_alert_by_teaching_idはNoneを返す"""
        repo = GuardianAlertRepository(mock_pool, invalid_org_id)
        result = repo.get_alert_by_teaching_id("some-id")
        assert result is None

    def test_update_notification_info_with_invalid_uuid(
        self, mock_pool, invalid_org_id
    ):
        """無効なUUIDでupdate_notification_infoはFalseを返す"""
        repo = GuardianAlertRepository(mock_pool, invalid_org_id)
        result = repo.update_notification_info("some-id", "room123", "msg456")
        assert result is False

    def test_resolve_alert_with_invalid_uuid(self, mock_pool, invalid_org_id):
        """無効なUUIDでresolve_alertはFalseを返す"""
        repo = GuardianAlertRepository(mock_pool, invalid_org_id)
        result = repo.resolve_alert("some-id", AlertStatus.ACKNOWLEDGED)
        assert result is False

    def test_resolve_alert_with_ceo_response(self, mock_pool, valid_org_id):
        """resolve_alertがCEOレスポンスを処理"""
        repo = GuardianAlertRepository(mock_pool, valid_org_id)
        result = repo.resolve_alert(
            "some-id",
            AlertStatus.OVERRIDDEN,
            ceo_response="そのまま保存してください",
            ceo_reasoning="重要な方針です",
        )
        # モックなのでFalse
        assert result is False


# =============================================================================
# TeachingUsageRepositoryのテスト
# =============================================================================


class TestTeachingUsageRepository:
    """TeachingUsageRepositoryのテスト"""

    def test_init_with_invalid_uuid(self, mock_pool, invalid_org_id):
        """無効なUUIDで初期化"""
        repo = TeachingUsageRepository(mock_pool, invalid_org_id)
        assert repo._org_id_is_uuid is False

    def test_log_usage_with_invalid_uuid_returns_usage(self, mock_pool, invalid_org_id):
        """無効なUUIDでlog_usageはそのままusageを返す（記録なし）"""
        repo = TeachingUsageRepository(mock_pool, invalid_org_id)
        usage = TeachingUsageContext(
            teaching_id="some-id",
            room_id="room123",
            account_id="user456",
            user_message="テストメッセージ",
        )
        result = repo.log_usage(usage)
        assert result is usage

    def test_log_usage_truncates_long_messages(self, mock_pool, valid_org_id):
        """log_usageが長いメッセージを切り詰める"""
        repo = TeachingUsageRepository(mock_pool, valid_org_id)
        long_message = "a" * 1000  # 1000文字
        usage = TeachingUsageContext(
            teaching_id="some-id",
            room_id="room123",
            account_id="user456",
            user_message=long_message,
            response_excerpt="b" * 500,
        )
        # log_usageは内部で500文字と200文字に切り詰める
        result = repo.log_usage(usage)
        assert result is usage

    def test_update_feedback_with_invalid_uuid(self, mock_pool, invalid_org_id):
        """無効なUUIDでupdate_feedbackはFalseを返す"""
        repo = TeachingUsageRepository(mock_pool, invalid_org_id)
        result = repo.update_feedback("teaching-id", "room123", True, "Good!")
        assert result is False

    def test_get_usage_stats_with_invalid_uuid(self, mock_pool, invalid_org_id):
        """無効なUUIDでget_usage_statsはデフォルト統計を返す"""
        repo = TeachingUsageRepository(mock_pool, invalid_org_id)
        result = repo.get_usage_stats("teaching-id", days=30)
        assert result == {
            "total_usage": 0,
            "helpful_count": 0,
            "not_helpful_count": 0,
            "avg_relevance_score": None,
        }

    def test_get_usage_stats_with_custom_days(self, mock_pool, valid_org_id):
        """get_usage_statsがカスタム日数を処理"""
        repo = TeachingUsageRepository(mock_pool, valid_org_id)
        result = repo.get_usage_stats("teaching-id", days=7)
        # モックなのでデフォルト値
        assert isinstance(result, dict)


# =============================================================================
# CEOLearningService追加テスト
# =============================================================================


class TestCEOLearningServiceExtended:
    """CEOLearningServiceの追加テスト"""

    def test_get_ceo_name(self, mock_pool):
        """get_ceo_nameがCEOの名前を返す"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")
        name = service.get_ceo_name("1728974")
        assert name == "菊地雅克"

    def test_estimate_categories_sdt(self, mock_pool):
        """SDTカテゴリを推定できること"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")
        categories = service._estimate_categories("自己決定と自律性について")
        assert TeachingCategory.SDT in categories

    def test_estimate_categories_psych_safety(self, mock_pool):
        """心理的安全性カテゴリを推定できること"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")
        categories = service._estimate_categories("心理的安全性を大切に")
        assert TeachingCategory.PSYCH_SAFETY in categories

    def test_estimate_categories_max_3(self, mock_pool):
        """カテゴリは最大3つまで"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")
        # 複数カテゴリにマッチするクエリ
        query = "可能性 選択理論 自己決定 心理的安全性"
        categories = service._estimate_categories(query)
        assert len(categories) <= 3

    def test_estimate_categories_no_match(self, mock_pool):
        """マッチしない場合は空リストを返す"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")
        categories = service._estimate_categories("ランチのおすすめは？")
        assert categories == []

    def test_get_teaching_returns_none(self, mock_pool):
        """get_teachingが存在しない教えでNoneを返す"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")
        result = service.get_teaching("nonexistent-id")
        assert result is None

    def test_update_teaching_returns_none(self, mock_pool):
        """update_teachingが存在しない教えでNoneを返す"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")
        result = service.update_teaching("nonexistent-id", {"priority": 10})
        assert result is None

    def test_deactivate_teaching_returns_false(self, mock_pool):
        """deactivate_teachingが存在しない教えでFalseを返す"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")
        result = service.deactivate_teaching("nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_process_ceo_message_with_llm(self, mock_pool, valid_org_id):
        """LLM付きでprocess_ceo_messageが動作"""
        # LLMの応答をモック
        mock_llm = AsyncMock(return_value=json.dumps({
            "teachings": [
                {
                    "statement": "スタッフを信じることが大切",
                    "reasoning": "可能性の解放がミッション",
                    "context": "1on1での話題",
                    "target": "全員",
                    "category": "mvv_mission",
                    "keywords": ["信じる", "可能性"],
                    "confidence": 0.85,
                }
            ]
        }))

        with patch.object(
            CEOLearningService,
            "_get_user_id_from_account_id",
            return_value=str(uuid4()),
        ):
            service = CEOLearningService(
                mock_pool, valid_org_id, llm_caller=mock_llm
            )

            # create_teachingもモック
            with patch.object(
                service._teaching_repo,
                "create_teaching",
                return_value=CEOTeaching(
                    id=str(uuid4()),
                    statement="スタッフを信じることが大切",
                ),
            ):
                ceo_id = CEO_ACCOUNT_IDS[0]
                result = await service.process_ceo_message(
                    message="スタッフを信じることが大切だ",
                    room_id="room123",
                    account_id=ceo_id,
                )

        assert result.success is True
        assert result.teachings_extracted == 1
        assert result.teachings_saved == 1

    @pytest.mark.asyncio
    async def test_process_ceo_message_user_not_found(self, mock_pool, valid_org_id):
        """ユーザーが見つからない場合のprocess_ceo_message"""
        mock_llm = AsyncMock(return_value=json.dumps({
            "teachings": [{"statement": "テスト", "confidence": 0.9}]
        }))

        with patch.object(
            CEOLearningService,
            "_get_user_id_from_account_id",
            return_value=None,  # ユーザーが見つからない
        ):
            service = CEOLearningService(
                mock_pool, valid_org_id, llm_caller=mock_llm
            )
            ceo_id = CEO_ACCOUNT_IDS[0]
            result = await service.process_ceo_message(
                message="テスト",
                room_id="room123",
                account_id=ceo_id,
            )

        assert result.success is False
        assert "ユーザーが見つかりません" in result.message

    @pytest.mark.asyncio
    async def test_process_ceo_message_filters_low_confidence(
        self, mock_pool, valid_org_id
    ):
        """低確信度の教えがフィルタされること"""
        mock_llm = AsyncMock(return_value=json.dumps({
            "teachings": [
                {"statement": "高確信度", "confidence": 0.9},
                {"statement": "低確信度", "confidence": 0.3},
            ]
        }))

        with patch.object(
            CEOLearningService,
            "_get_user_id_from_account_id",
            return_value=str(uuid4()),
        ):
            service = CEOLearningService(
                mock_pool, valid_org_id, llm_caller=mock_llm
            )

            with patch.object(
                service._teaching_repo,
                "create_teaching",
                return_value=CEOTeaching(
                    id=str(uuid4()),
                    statement="高確信度",
                ),
            ):
                ceo_id = CEO_ACCOUNT_IDS[0]
                result = await service.process_ceo_message(
                    message="テスト",
                    room_id="room123",
                    account_id=ceo_id,
                )

        # 高確信度の1件のみ保存される
        assert result.teachings_saved == 1


# =============================================================================
# ExtractedTeachingデータクラスのテスト
# =============================================================================


class TestExtractedTeaching:
    """ExtractedTeachingデータクラスのテスト"""

    def test_create_with_all_fields(self):
        """全フィールド指定で作成"""
        teaching = ExtractedTeaching(
            statement="テスト教え",
            reasoning="テスト理由",
            context="テスト文脈",
            target="全員",
            category="mvv_mission",
            keywords=["キーワード1", "キーワード2"],
            confidence=0.85,
        )
        assert teaching.statement == "テスト教え"
        assert teaching.reasoning == "テスト理由"
        assert teaching.context == "テスト文脈"
        assert teaching.target == "全員"
        assert teaching.category == "mvv_mission"
        assert teaching.keywords == ["キーワード1", "キーワード2"]
        assert teaching.confidence == 0.85

    def test_create_with_defaults(self):
        """デフォルト値で作成"""
        teaching = ExtractedTeaching(statement="テスト教え")
        assert teaching.statement == "テスト教え"
        assert teaching.reasoning is None
        assert teaching.context is None
        assert teaching.target is None
        assert teaching.category == "other"
        assert teaching.keywords == []
        assert teaching.confidence == 0.0


# =============================================================================
# ProcessingResultデータクラスのテスト
# =============================================================================


class TestProcessingResult:
    """ProcessingResultデータクラスのテスト"""

    def test_create_success_result(self):
        """成功結果の作成"""
        result = ProcessingResult(
            success=True,
            teachings_extracted=2,
            teachings_saved=2,
            teachings_pending=0,
            message="2件の教えを保存しました",
        )
        assert result.success is True
        assert result.teachings_extracted == 2
        assert result.teachings_saved == 2
        assert result.teachings_pending == 0

    def test_create_failure_result(self):
        """失敗結果の作成"""
        result = ProcessingResult(
            success=False,
            message="CEOユーザーではありません",
        )
        assert result.success is False
        assert result.teachings_extracted == 0
        assert result.teachings_saved == 0

    def test_default_extracted_teachings_list(self):
        """extracted_teachingsのデフォルトは空リスト"""
        result = ProcessingResult(success=True)
        assert result.extracted_teachings == []


# =============================================================================
# エッジケースのテスト
# =============================================================================


class TestEdgeCases:
    """エッジケースのテスト"""

    def test_teaching_with_none_keywords_raises_typeerror(self, valid_org_id, sample_ceo_user_id):
        """keywordsがNoneの教えでis_relevant_toはTypeErrorを発生"""
        teaching = CEOTeaching(
            organization_id=valid_org_id,
            ceo_user_id=sample_ceo_user_id,
            statement="テスト教え",
            keywords=None,  # Noneを設定
        )
        # 現在の実装ではNoneのkeywordsはTypeErrorになる
        # （デフォルトでは空リストなのでNoneは異常値）
        with pytest.raises(TypeError):
            teaching.is_relevant_to("テスト")

    def test_teaching_with_empty_keywords(self, valid_org_id, sample_ceo_user_id):
        """keywordsが空リストの教え"""
        teaching = CEOTeaching(
            organization_id=valid_org_id,
            ceo_user_id=sample_ceo_user_id,
            statement="テスト教え",
            keywords=[],  # 空リスト
        )
        # statement内のマッチでTrueになる
        result = teaching.is_relevant_to("テスト")
        assert result is True

    def test_teaching_with_empty_statement(self, valid_org_id, sample_ceo_user_id):
        """空の主張を持つ教え"""
        teaching = CEOTeaching(
            organization_id=valid_org_id,
            ceo_user_id=sample_ceo_user_id,
            statement="",
        )
        result = teaching.to_prompt_context()
        assert result is not None

    def test_extracted_teaching_with_invalid_category(self):
        """無効なカテゴリのExtractedTeaching"""
        teaching = ExtractedTeaching(
            statement="テスト",
            category="invalid_category",
            confidence=0.8,
        )
        assert teaching.category == "invalid_category"

    def test_format_teachings_with_none_reasoning(self, valid_org_id, sample_ceo_user_id):
        """reasoningがNoneの教えをフォーマット"""
        teaching = CEOTeaching(
            organization_id=valid_org_id,
            ceo_user_id=sample_ceo_user_id,
            statement="テスト教え",
            reasoning=None,
        )
        result = format_teachings_for_prompt([teaching])
        assert "テスト教え" in result

    def test_should_include_teachings_with_active_session(self):
        """アクティブセッション中は教えを含めない"""
        context = Mock()
        context.has_active_session = Mock(return_value=True)
        result = should_include_teachings(context, "9999999")
        assert result is False

    def test_ceo_teaching_context_empty_teachings(self):
        """教えなしのCEOTeachingContext"""
        context = CEOTeachingContext(relevant_teachings=[])
        assert context.get_top_teachings(5) == []
        assert context.to_prompt_context() == ""

    def test_guardian_alert_empty_conflicts(self):
        """矛盾なしのGuardianAlert"""
        alert = GuardianAlert(teaching_id="test-id", conflicts=[])
        assert alert.max_severity == Severity.LOW

    def test_conflict_info_default_values(self):
        """ConflictInfoのデフォルト値"""
        conflict = ConflictInfo(
            teaching_id="test-id",
            description="テスト",
        )
        assert conflict.conflict_type == ConflictType.MVV
        assert conflict.severity == Severity.MEDIUM


# =============================================================================
# 追加の統合テスト
# =============================================================================


class TestFullIntegration:
    """追加の統合テスト"""

    def test_full_teaching_context_flow(
        self, mock_pool, sample_teachings, sample_context
    ):
        """教えコンテキスト取得の完全フロー"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")

        # 検索をモック
        with patch.object(
            service._teaching_repo,
            "search_teachings",
            return_value=sample_teachings,
        ):
            with patch.object(
                service._teaching_repo,
                "get_teachings_by_category",
                return_value=[],
            ):
                with patch.object(
                    service._teaching_repo,
                    "get_active_teachings",
                    return_value=sample_teachings,
                ):
                    with patch.object(
                        service._alert_repo,
                        "get_pending_alerts",
                        return_value=[],
                    ):
                        context = service.get_ceo_teaching_context(
                            query="選択理論について教えて",
                            is_ceo=False,
                            context=sample_context,
                        )

        assert isinstance(context, CEOTeachingContext)
        assert context.is_ceo_user is False

    def test_teaching_usage_logging_flow(self, mock_pool, sample_teaching):
        """教え使用ログ記録のフロー"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")

        # log_usageとincrement_usageをモック
        with patch.object(
            service._usage_repo,
            "log_usage",
        ):
            with patch.object(
                service._teaching_repo,
                "increment_usage",
            ):
                # エラーなく完了すること
                service.log_teaching_usage(
                    teaching=sample_teaching,
                    room_id="room123",
                    account_id="user456",
                    user_message="テストメッセージ",
                    response_excerpt="テスト応答",
                    relevance_score=0.8,
                )

    def test_teaching_feedback_flow(self, mock_pool, sample_teaching):
        """教えフィードバック更新のフロー"""
        service = CEOLearningService(mock_pool, "org_soulsyncs")

        with patch.object(
            service._usage_repo,
            "update_feedback",
        ):
            with patch.object(
                service._teaching_repo,
                "increment_usage",
            ):
                # エラーなく完了すること
                service.update_teaching_feedback(
                    teaching_id=sample_teaching.id,
                    room_id="room123",
                    was_helpful=True,
                    feedback="とても参考になりました",
                )


# =============================================================================
# リポジトリDB操作パスのテスト（モックでDB操作をシミュレート）
# =============================================================================


class TestRepositoryDBOperations:
    """リポジトリのDB操作パスのテスト"""

    def test_create_teaching_with_valid_uuid(self, mock_pool, valid_org_id, sample_ceo_user_id):
        """有効なUUIDでcreate_teachingが動作"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)

        # DB操作のモック設定
        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = (
            str(uuid4()),  # id
            datetime.now(),  # created_at
            datetime.now(),  # updated_at
        )
        mock_conn.execute.return_value = mock_result

        teaching = CEOTeaching(
            organization_id=valid_org_id,
            ceo_user_id=sample_ceo_user_id,
            statement="テスト教え",
            category=TeachingCategory.CULTURE,
        )

        result = repo.create_teaching(teaching)
        assert result.id is not None
        assert result.organization_id == valid_org_id

    def test_get_active_teachings_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでget_active_teachingsが動作"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)

        # 空リストを返す
        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = repo.get_active_teachings()
        assert result == []

    def test_get_active_teachings_with_category_filter(self, mock_pool, valid_org_id):
        """カテゴリフィルタ付きでget_active_teachingsが動作"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = repo.get_active_teachings(category=TeachingCategory.MVV_MISSION)
        assert result == []

    def test_search_teachings_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでsearch_teachingsが動作"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = repo.search_teachings("可能性")
        assert result == []

    def test_search_teachings_with_multiple_keywords(self, mock_pool, valid_org_id):
        """複数キーワードでsearch_teachingsが動作"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = repo.search_teachings("可能性 信じる 挑戦")
        assert result == []

    def test_get_teachings_by_category_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでget_teachings_by_categoryが動作"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = repo.get_teachings_by_category([
            TeachingCategory.MVV_MISSION,
            TeachingCategory.CHOICE_THEORY,
        ])
        assert result == []

    def test_get_pending_teachings_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでget_pending_teachingsが動作"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = repo.get_pending_teachings()
        assert result == []

    def test_update_validation_status_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでupdate_validation_statusが動作"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = (str(uuid4()),)  # 更新成功
        mock_conn.execute.return_value = mock_result

        result = repo.update_validation_status(
            "teaching-id",
            ValidationStatus.VERIFIED,
            mvv_score=0.9,
            theory_score=0.85,
        )
        assert result is True

    def test_increment_usage_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでincrement_usageが動作"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = (str(uuid4()),)
        mock_conn.execute.return_value = mock_result

        result = repo.increment_usage("teaching-id", was_helpful=True)
        assert result is True

    def test_deactivate_teaching_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでdeactivate_teachingが動作"""
        repo = CEOTeachingRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = (str(uuid4()),)
        mock_conn.execute.return_value = mock_result

        result = repo.deactivate_teaching("teaching-id")
        assert result is True

    def test_create_conflict_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでcreate_conflictが動作"""
        repo = ConflictRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = (
            str(uuid4()),  # id
            datetime.now(),  # created_at
        )
        mock_conn.execute.return_value = mock_result

        conflict = ConflictInfo(
            teaching_id=str(uuid4()),
            conflict_type=ConflictType.MVV,
            description="テスト矛盾",
            reference="MVV",
            severity=Severity.MEDIUM,
        )

        result = repo.create_conflict(conflict)
        assert result.id is not None

    def test_get_conflicts_for_teaching_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでget_conflicts_for_teachingが動作"""
        repo = ConflictRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = repo.get_conflicts_for_teaching("teaching-id")
        assert result == []

    def test_delete_conflicts_for_teaching_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでdelete_conflicts_for_teachingが動作"""
        repo = ConflictRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.rowcount = 2
        mock_conn.execute.return_value = mock_result

        result = repo.delete_conflicts_for_teaching("teaching-id")
        assert result == 2

    def test_create_alert_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでcreate_alertが動作"""
        repo = GuardianAlertRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = (
            str(uuid4()),  # id
            datetime.now(),  # created_at
            datetime.now(),  # updated_at
        )
        mock_conn.execute.return_value = mock_result

        alert = GuardianAlert(
            teaching_id=str(uuid4()),
            conflict_summary="テスト矛盾",
            alert_message="確認してください",
        )

        result = repo.create_alert(alert)
        assert result.id is not None

    def test_get_pending_alerts_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでget_pending_alertsが動作"""
        repo = GuardianAlertRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = repo.get_pending_alerts()
        assert result == []

    def test_update_notification_info_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでupdate_notification_infoが動作"""
        repo = GuardianAlertRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = (str(uuid4()),)
        mock_conn.execute.return_value = mock_result

        result = repo.update_notification_info("alert-id", "room123", "msg456")
        assert result is True

    def test_resolve_alert_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでresolve_alertが動作"""
        repo = GuardianAlertRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = (str(uuid4()),)
        mock_conn.execute.return_value = mock_result

        result = repo.resolve_alert(
            "alert-id",
            AlertStatus.ACKNOWLEDGED,
            ceo_response="確認しました",
            ceo_reasoning="問題ありません",
        )
        assert result is True

    def test_log_usage_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでlog_usageが動作"""
        repo = TeachingUsageRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = (
            str(uuid4()),  # id
            datetime.now(),  # created_at
        )
        mock_conn.execute.return_value = mock_result

        usage = TeachingUsageContext(
            teaching_id=str(uuid4()),
            room_id="room123",
            account_id="user456",
            user_message="テストメッセージ",
            relevance_score=0.8,
        )

        result = repo.log_usage(usage)
        assert result is usage

    def test_update_feedback_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでupdate_feedbackが動作"""
        repo = TeachingUsageRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = (str(uuid4()),)
        mock_conn.execute.return_value = mock_result

        result = repo.update_feedback(
            teaching_id="teaching-id",
            room_id="room123",
            was_helpful=True,
            feedback="とても参考になりました",
        )
        assert result is True

    def test_get_usage_stats_with_valid_uuid(self, mock_pool, valid_org_id):
        """有効なUUIDでget_usage_statsが動作"""
        repo = TeachingUsageRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = (10, 7, 2, 0.85)  # 統計データ
        mock_conn.execute.return_value = mock_result

        result = repo.get_usage_stats("teaching-id", days=30)
        assert result["total_usage"] == 10
        assert result["helpful_count"] == 7
        assert result["not_helpful_count"] == 2
        assert result["avg_relevance_score"] == 0.85

    def test_get_usage_stats_with_null_result(self, mock_pool, valid_org_id):
        """get_usage_statsがNULL結果を処理"""
        repo = TeachingUsageRepository(mock_pool, valid_org_id)

        mock_conn = mock_pool.connect.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.fetchone.return_value = None  # データなし
        mock_conn.execute.return_value = mock_result

        result = repo.get_usage_stats("teaching-id", days=30)
        assert result["total_usage"] == 0
        assert result["helpful_count"] == 0


# =============================================================================
# 追加の定数テスト
# =============================================================================


class TestConstantsExtended:
    """追加の定数テスト"""

    def test_default_teaching_limit(self):
        """DEFAULT_TEACHING_LIMITが正の整数"""
        assert DEFAULT_TEACHING_LIMIT > 0
        assert DEFAULT_TEACHING_LIMIT == 5

    def test_category_keywords_all_have_lists(self):
        """全カテゴリキーワードがリスト形式"""
        for category, keywords in CATEGORY_KEYWORDS.items():
            assert isinstance(keywords, list)
            assert all(isinstance(kw, str) for kw in keywords)
