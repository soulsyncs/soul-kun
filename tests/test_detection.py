"""
Phase 2 進化版 A1: 検出基盤のユニットテスト

このモジュールは、lib/detection/ パッケージのユニットテストを提供します。

テスト対象:
- constants.py: 定数、Enum
- exceptions.py: カスタム例外
- base.py: BaseDetector抽象クラス、データクラス
- pattern_detector.py: PatternDetector検出器

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-23
"""

import hashlib
import pytest
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

# ================================================================
# テスト対象のインポート
# ================================================================

from lib.detection.constants import (
    DetectionParameters,
    QuestionCategory,
    CATEGORY_KEYWORDS,
    PatternStatus,
    InsightStatus,
    WeeklyReportStatus,
    InsightType,
    SourceType,
    NotificationType,
    Importance,
    Classification,
    ErrorCode,
    IdempotencyKeyPrefix,
    LogMessages,
)

from lib.detection.exceptions import (
    DetectionBaseException,
    DetectionError,
    PatternSaveError,
    InsightCreateError,
    NotificationError,
    DatabaseError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    wrap_database_error,
    wrap_detection_error,
)

from lib.detection.base import (
    InsightData,
    DetectionContext,
    DetectionResult,
    BaseDetector,
    validate_uuid,
    truncate_text,
)

from lib.detection.pattern_detector import (
    PatternData,
    PatternDetector,
)


# ================================================================
# constants.py のテスト
# ================================================================

class TestDetectionParameters:
    """DetectionParametersのテスト"""

    def test_pattern_threshold_default(self):
        """パターン閾値のデフォルト値"""
        assert DetectionParameters.PATTERN_THRESHOLD == 5

    def test_pattern_window_days_default(self):
        """パターン検出期間のデフォルト値"""
        assert DetectionParameters.PATTERN_WINDOW_DAYS == 30

    def test_max_sample_questions_default(self):
        """サンプル質問数のデフォルト値"""
        assert DetectionParameters.MAX_SAMPLE_QUESTIONS == 5

    def test_similarity_threshold_default(self):
        """類似度閾値のデフォルト値"""
        assert DetectionParameters.SIMILARITY_THRESHOLD == 0.85

    def test_weekly_report_day_default(self):
        """週次レポート送信曜日のデフォルト値（月曜=0）"""
        assert DetectionParameters.WEEKLY_REPORT_DAY == 0


class TestQuestionCategory:
    """QuestionCategoryのテスト"""

    def test_all_categories_exist(self):
        """全カテゴリが存在すること"""
        expected = [
            "business_process",
            "company_rule",
            "technical",
            "hr_related",
            "project",
            "other",
        ]
        actual = [c.value for c in QuestionCategory]
        assert sorted(actual) == sorted(expected)

    def test_from_string_valid(self):
        """有効な文字列からカテゴリを取得"""
        assert QuestionCategory.from_string("business_process") == QuestionCategory.BUSINESS_PROCESS
        assert QuestionCategory.from_string("TECHNICAL") == QuestionCategory.TECHNICAL

    def test_from_string_invalid(self):
        """無効な文字列はOTHERを返す"""
        assert QuestionCategory.from_string("unknown") == QuestionCategory.OTHER
        assert QuestionCategory.from_string("") == QuestionCategory.OTHER


class TestCategoryKeywords:
    """CATEGORY_KEYWORDSのテスト"""

    def test_business_process_keywords(self):
        """業務手続きカテゴリのキーワード"""
        keywords = CATEGORY_KEYWORDS[QuestionCategory.BUSINESS_PROCESS]
        assert "週報" in keywords
        assert "経費" in keywords
        assert "精算" in keywords

    def test_company_rule_keywords(self):
        """社内ルールカテゴリのキーワード"""
        keywords = CATEGORY_KEYWORDS[QuestionCategory.COMPANY_RULE]
        assert "有給" in keywords
        assert "休暇" in keywords
        assert "服装" in keywords

    def test_technical_keywords(self):
        """技術質問カテゴリのキーワード"""
        keywords = CATEGORY_KEYWORDS[QuestionCategory.TECHNICAL]
        assert "slack" in keywords
        assert "vpn" in keywords
        assert "パスワード" in keywords


class TestImportance:
    """Importanceのテスト"""

    def test_all_levels_exist(self):
        """全重要度レベルが存在すること"""
        expected = ["critical", "high", "medium", "low"]
        actual = [i.value for i in Importance]
        assert sorted(actual) == sorted(expected)

    def test_from_occurrence_count_critical(self):
        """発生回数20回以上はCRITICAL"""
        assert Importance.from_occurrence_count(20, 1) == Importance.CRITICAL
        assert Importance.from_occurrence_count(25, 1) == Importance.CRITICAL

    def test_from_occurrence_count_critical_by_users(self):
        """ユニークユーザー10人以上はCRITICAL"""
        assert Importance.from_occurrence_count(5, 10) == Importance.CRITICAL
        assert Importance.from_occurrence_count(5, 15) == Importance.CRITICAL

    def test_from_occurrence_count_high(self):
        """発生回数10回以上はHIGH"""
        assert Importance.from_occurrence_count(10, 1) == Importance.HIGH
        assert Importance.from_occurrence_count(15, 1) == Importance.HIGH

    def test_from_occurrence_count_high_by_users(self):
        """ユニークユーザー5人以上はHIGH"""
        assert Importance.from_occurrence_count(5, 5) == Importance.HIGH
        assert Importance.from_occurrence_count(5, 7) == Importance.HIGH

    def test_from_occurrence_count_medium(self):
        """発生回数5回以上はMEDIUM"""
        assert Importance.from_occurrence_count(5, 1) == Importance.MEDIUM
        assert Importance.from_occurrence_count(8, 1) == Importance.MEDIUM

    def test_from_occurrence_count_low(self):
        """発生回数5回未満はLOW"""
        assert Importance.from_occurrence_count(1, 1) == Importance.LOW
        assert Importance.from_occurrence_count(4, 1) == Importance.LOW


class TestPatternStatus:
    """PatternStatusのテスト"""

    def test_all_statuses_exist(self):
        """全ステータスが存在すること"""
        expected = ["active", "addressed", "dismissed"]
        actual = [s.value for s in PatternStatus]
        assert sorted(actual) == sorted(expected)


class TestInsightStatus:
    """InsightStatusのテスト"""

    def test_all_statuses_exist(self):
        """全ステータスが存在すること"""
        expected = ["new", "acknowledged", "addressed", "dismissed"]
        actual = [s.value for s in InsightStatus]
        assert sorted(actual) == sorted(expected)


class TestClassification:
    """Classificationのテスト"""

    def test_all_classifications_exist(self):
        """全機密区分が存在すること"""
        expected = ["public", "internal", "confidential", "restricted"]
        actual = [c.value for c in Classification]
        assert sorted(actual) == sorted(expected)


# ================================================================
# exceptions.py のテスト
# ================================================================

class TestDetectionBaseException:
    """DetectionBaseExceptionのテスト"""

    def test_basic_exception(self):
        """基本的な例外作成"""
        exc = DetectionBaseException(
            error_code=ErrorCode.DETECTION_ERROR,
            message="Test error"
        )
        assert exc.error_code == ErrorCode.DETECTION_ERROR
        assert exc.message == "Test error"
        assert exc.details == {}
        assert exc.original_exception is None

    def test_exception_with_details(self):
        """詳細情報付きの例外"""
        exc = DetectionBaseException(
            error_code=ErrorCode.DETECTION_ERROR,
            message="Test error",
            details={"key": "value"}
        )
        assert exc.details == {"key": "value"}

    def test_uuid_sanitization(self):
        """UUIDのサニタイズ"""
        test_uuid = "12345678-1234-1234-1234-123456789012"
        exc = DetectionBaseException(
            error_code=ErrorCode.DETECTION_ERROR,
            message=f"Error with {test_uuid}"
        )
        # UUIDの最初の8文字のみが表示される
        assert "12345678..." in str(exc)
        assert test_uuid not in str(exc)

    def test_email_sanitization(self):
        """メールアドレスのサニタイズ"""
        exc = DetectionBaseException(
            error_code=ErrorCode.DETECTION_ERROR,
            message="Error with user@example.com"
        )
        assert "[EMAIL]" in str(exc)
        assert "user@example.com" not in str(exc)

    def test_ip_sanitization(self):
        """IPアドレスのサニタイズ"""
        exc = DetectionBaseException(
            error_code=ErrorCode.DETECTION_ERROR,
            message="Error from 192.168.1.1"
        )
        assert "[IP]" in str(exc)
        assert "192.168.1.1" not in str(exc)

    def test_to_dict(self):
        """辞書変換"""
        exc = DetectionBaseException(
            error_code=ErrorCode.DETECTION_ERROR,
            message="Test error",
            details={"key": "value"}
        )
        result = exc.to_dict()
        assert result["error_code"] == "DETECTION_ERROR"
        assert "message" in result
        assert result["details"] == {"key": "value"}

    def test_sensitive_details_redacted(self):
        """機密情報の詳細がマスクされる"""
        exc = DetectionBaseException(
            error_code=ErrorCode.DETECTION_ERROR,
            message="Test error",
            details={"password": "secret123", "key": "value"}
        )
        result = exc.to_dict()
        assert result["details"]["password"] == "[REDACTED]"
        assert result["details"]["key"] == "value"


class TestSpecificExceptions:
    """各種例外クラスのテスト"""

    def test_detection_error(self):
        """DetectionError"""
        exc = DetectionError(message="Detection failed")
        assert exc.error_code == ErrorCode.DETECTION_ERROR

    def test_pattern_save_error(self):
        """PatternSaveError"""
        exc = PatternSaveError(message="Save failed")
        assert exc.error_code == ErrorCode.PATTERN_SAVE_ERROR

    def test_insight_create_error(self):
        """InsightCreateError"""
        exc = InsightCreateError(message="Create failed")
        assert exc.error_code == ErrorCode.INSIGHT_CREATE_ERROR

    def test_notification_error(self):
        """NotificationError"""
        exc = NotificationError(message="Notification failed")
        assert exc.error_code == ErrorCode.NOTIFICATION_ERROR

    def test_database_error(self):
        """DatabaseError"""
        exc = DatabaseError(message="DB error")
        assert exc.error_code == ErrorCode.DATABASE_ERROR

    def test_validation_error(self):
        """ValidationError"""
        exc = ValidationError(message="Validation failed")
        assert exc.error_code == ErrorCode.VALIDATION_ERROR

    def test_authentication_error(self):
        """AuthenticationError"""
        exc = AuthenticationError(message="Auth failed")
        assert exc.error_code == ErrorCode.AUTHENTICATION_ERROR

    def test_authorization_error(self):
        """AuthorizationError"""
        exc = AuthorizationError(message="Access denied")
        assert exc.error_code == ErrorCode.AUTHORIZATION_ERROR


class TestExceptionWrappers:
    """例外ラッパー関数のテスト"""

    def test_wrap_database_error(self):
        """wrap_database_error"""
        original = ValueError("Original error")
        wrapped = wrap_database_error(original, "test operation")
        assert isinstance(wrapped, DatabaseError)
        assert "test operation" in wrapped.message
        assert wrapped.original_exception == original

    def test_wrap_detection_error(self):
        """wrap_detection_error"""
        original = ValueError("Original error")
        wrapped = wrap_detection_error(original, "a1_pattern")
        assert isinstance(wrapped, DetectionError)
        assert "a1_pattern" in wrapped.message
        assert wrapped.original_exception == original


# ================================================================
# base.py のテスト
# ================================================================

class TestInsightData:
    """InsightDataのテスト"""

    def test_basic_creation(self):
        """基本的な作成"""
        org_id = uuid4()
        data = InsightData(
            organization_id=org_id,
            insight_type=InsightType.PATTERN_DETECTED,
            source_type=SourceType.A1_PATTERN,
            importance=Importance.HIGH,
            title="Test Insight",
            description="Test description"
        )
        assert data.organization_id == org_id
        assert data.insight_type == InsightType.PATTERN_DETECTED
        assert data.classification == Classification.INTERNAL  # デフォルト値

    def test_to_dict(self):
        """辞書変換"""
        org_id = uuid4()
        data = InsightData(
            organization_id=org_id,
            insight_type=InsightType.PATTERN_DETECTED,
            source_type=SourceType.A1_PATTERN,
            importance=Importance.HIGH,
            title="Test Insight",
            description="Test description"
        )
        result = data.to_dict()
        assert result["organization_id"] == str(org_id)
        assert result["insight_type"] == "pattern_detected"
        assert result["importance"] == "high"


class TestDetectionContext:
    """DetectionContextのテスト"""

    def test_basic_creation(self):
        """基本的な作成"""
        org_id = uuid4()
        ctx = DetectionContext(organization_id=org_id)
        assert ctx.organization_id == org_id
        assert ctx.user_id is None
        assert ctx.dry_run is False
        assert ctx.debug is False

    def test_full_creation(self):
        """全パラメータ指定での作成"""
        org_id = uuid4()
        user_id = uuid4()
        dept_id = uuid4()
        ctx = DetectionContext(
            organization_id=org_id,
            user_id=user_id,
            department_id=dept_id,
            dry_run=True,
            debug=True
        )
        assert ctx.user_id == user_id
        assert ctx.department_id == dept_id
        assert ctx.dry_run is True
        assert ctx.debug is True


class TestDetectionResult:
    """DetectionResultのテスト"""

    def test_success_result(self):
        """成功結果"""
        result = DetectionResult(
            success=True,
            detected_count=5,
            insight_created=True,
            insight_id=uuid4()
        )
        assert result.success is True
        assert result.detected_count == 5
        assert result.insight_created is True
        assert result.error_message is None

    def test_failure_result(self):
        """失敗結果"""
        result = DetectionResult(
            success=False,
            error_message="Test error"
        )
        assert result.success is False
        assert result.detected_count == 0
        assert result.insight_created is False
        assert result.error_message == "Test error"


class TestValidateUuid:
    """validate_uuidのテスト"""

    def test_valid_uuid_object(self):
        """UUID型オブジェクト"""
        test_uuid = uuid4()
        result = validate_uuid(test_uuid, "test_field")
        assert result == test_uuid

    def test_valid_uuid_string(self):
        """UUID文字列"""
        test_uuid = str(uuid4())
        result = validate_uuid(test_uuid, "test_field")
        assert str(result) == test_uuid

    def test_none_value(self):
        """None値"""
        with pytest.raises(ValidationError) as exc_info:
            validate_uuid(None, "test_field")
        assert "required" in str(exc_info.value)

    def test_invalid_string(self):
        """無効な文字列"""
        with pytest.raises(ValidationError) as exc_info:
            validate_uuid("invalid", "test_field")
        assert "Invalid" in str(exc_info.value)


class TestTruncateText:
    """truncate_textのテスト"""

    def test_short_text(self):
        """短いテキスト（切り詰め不要）"""
        result = truncate_text("Hello", 10)
        assert result == "Hello"

    def test_exact_length(self):
        """ちょうど最大長"""
        result = truncate_text("HelloWorld", 10)
        assert result == "HelloWorld"

    def test_long_text(self):
        """長いテキスト（切り詰め必要）"""
        result = truncate_text("Hello World Test", 10)
        assert result == "Hello W..."
        assert len(result) == 10

    def test_custom_suffix(self):
        """カスタムサフィックス"""
        result = truncate_text("Hello World Test", 10, suffix="…")
        assert result == "Hello Wor…"


# ================================================================
# pattern_detector.py のテスト
# ================================================================

class TestPatternData:
    """PatternDataのテスト"""

    def test_basic_creation(self):
        """基本的な作成"""
        pattern_id = uuid4()
        org_id = uuid4()
        now = datetime.now()
        data = PatternData(
            id=pattern_id,
            organization_id=org_id,
            department_id=None,
            question_category=QuestionCategory.BUSINESS_PROCESS,
            question_hash="abc123",
            normalized_question="週報の出し方を教えてください",
            occurrence_count=5,
            occurrence_timestamps=[now],
            first_asked_at=now,
            last_asked_at=now,
            asked_by_user_ids=[uuid4()],
            sample_questions=["週報の出し方は？"],
            status=PatternStatus.ACTIVE
        )
        assert data.id == pattern_id
        assert data.occurrence_count == 5
        assert data.question_category == QuestionCategory.BUSINESS_PROCESS

    def test_with_department(self):
        """部署ID付きでの作成"""
        pattern_id = uuid4()
        org_id = uuid4()
        dept_id = uuid4()
        now = datetime.now()
        data = PatternData(
            id=pattern_id,
            organization_id=org_id,
            department_id=dept_id,
            question_category=QuestionCategory.TECHNICAL,
            question_hash="abc123",
            normalized_question="VPNの接続方法",
            occurrence_count=3,
            occurrence_timestamps=[now],
            first_asked_at=now,
            last_asked_at=now,
            asked_by_user_ids=[uuid4()],
            sample_questions=["VPNに繋がらない"],
            status=PatternStatus.ACTIVE
        )
        assert data.department_id == dept_id
        assert data.question_category == QuestionCategory.TECHNICAL

    def test_window_occurrence_count(self):
        """ウィンドウ期間内の発生回数（window_occurrence_count）"""
        pattern_id = uuid4()
        org_id = uuid4()
        now = datetime.now()
        timestamps = [now, now, now, now, now]  # 5回
        data = PatternData(
            id=pattern_id,
            organization_id=org_id,
            department_id=None,
            question_category=QuestionCategory.BUSINESS_PROCESS,
            question_hash="abc123",
            normalized_question="テスト",
            occurrence_count=10,  # 全期間は10回
            occurrence_timestamps=timestamps,  # ウィンドウ内は5回
            first_asked_at=now,
            last_asked_at=now,
            asked_by_user_ids=[uuid4()],
            sample_questions=["テスト"],
            status=PatternStatus.ACTIVE
        )
        assert data.window_occurrence_count == 5
        assert data.occurrence_count == 10

    def test_get_window_occurrence_count_with_old_timestamps(self):
        """古いタイムスタンプを含むウィンドウ発生回数のテスト"""
        from datetime import timedelta, timezone

        pattern_id = uuid4()
        org_id = uuid4()
        now = datetime.now(timezone.utc)
        old_timestamp = now - timedelta(days=40)  # 40日前（ウィンドウ外）
        recent_timestamp = now - timedelta(days=10)  # 10日前（ウィンドウ内）

        timestamps = [old_timestamp, recent_timestamp, now]
        data = PatternData(
            id=pattern_id,
            organization_id=org_id,
            department_id=None,
            question_category=QuestionCategory.BUSINESS_PROCESS,
            question_hash="abc123",
            normalized_question="テスト",
            occurrence_count=3,
            occurrence_timestamps=timestamps,
            first_asked_at=old_timestamp,
            last_asked_at=now,
            asked_by_user_ids=[uuid4()],
            sample_questions=["テスト"],
            status=PatternStatus.ACTIVE
        )
        # 30日間のウィンドウでは2件（recent_timestamp と now）
        assert data.get_window_occurrence_count(window_days=30) == 2
        # 50日間のウィンドウでは3件（全て）
        assert data.get_window_occurrence_count(window_days=50) == 3

    def test_empty_occurrence_timestamps(self):
        """空のタイムスタンプ配列"""
        pattern_id = uuid4()
        org_id = uuid4()
        now = datetime.now()
        data = PatternData(
            id=pattern_id,
            organization_id=org_id,
            department_id=None,
            question_category=QuestionCategory.BUSINESS_PROCESS,
            question_hash="abc123",
            normalized_question="テスト",
            occurrence_count=1,
            occurrence_timestamps=[],  # 空
            first_asked_at=now,
            last_asked_at=now,
            asked_by_user_ids=[uuid4()],
            sample_questions=["テスト"],
            status=PatternStatus.ACTIVE
        )
        assert data.window_occurrence_count == 0


class TestPatternDetectorNormalization:
    """PatternDetectorの正規化機能のテスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックデータベース接続"""
        return MagicMock()

    @pytest.fixture
    def detector(self, mock_conn):
        """PatternDetectorインスタンス"""
        org_id = uuid4()
        return PatternDetector(mock_conn, org_id)

    def test_normalize_basic(self, detector):
        """基本的な正規化"""
        result = detector._normalize_question("  週報の出し方を教えてください  ")
        assert result == "週報の出し方を教えてください"

    def test_normalize_with_greetings(self, detector):
        """挨拶の除去"""
        result = detector._normalize_question("お疲れ様です。週報の出し方を教えてください")
        # 挨拶が除去されていること
        assert "お疲れ" not in result
        assert "週報" in result

    def test_normalize_newlines(self, detector):
        """改行の正規化"""
        result = detector._normalize_question("週報の\n出し方を\n教えてください")
        # 改行がスペースに変換されているか、連結されている
        assert "\n" not in result


class TestPatternDetectorClassification:
    """PatternDetectorのカテゴリ分類機能のテスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックデータベース接続"""
        return MagicMock()

    @pytest.fixture
    def detector(self, mock_conn):
        """PatternDetectorインスタンス"""
        org_id = uuid4()
        return PatternDetector(mock_conn, org_id)

    @pytest.mark.asyncio
    async def test_classify_business_process(self, detector):
        """業務手続きカテゴリの分類"""
        result = await detector._classify_category("週報の出し方を教えてください")
        assert result == QuestionCategory.BUSINESS_PROCESS

    @pytest.mark.asyncio
    async def test_classify_company_rule(self, detector):
        """社内ルールカテゴリの分類"""
        # "有給" と "休暇" はCOMPANY_RULEのキーワード
        result = await detector._classify_category("有給休暇は何日ありますか？")
        assert result == QuestionCategory.COMPANY_RULE

    @pytest.mark.asyncio
    async def test_classify_technical(self, detector):
        """技術質問カテゴリの分類"""
        result = await detector._classify_category("VPNに接続できません")
        assert result == QuestionCategory.TECHNICAL

    @pytest.mark.asyncio
    async def test_classify_hr_related(self, detector):
        """人事関連カテゴリの分類"""
        result = await detector._classify_category("評価面談はいつですか？")
        assert result == QuestionCategory.HR_RELATED

    @pytest.mark.asyncio
    async def test_classify_project(self, detector):
        """プロジェクトカテゴリの分類"""
        result = await detector._classify_category("プロジェクトの進捗を教えてください")
        assert result == QuestionCategory.PROJECT

    @pytest.mark.asyncio
    async def test_classify_other(self, detector):
        """その他カテゴリの分類"""
        result = await detector._classify_category("今日の天気は？")
        assert result == QuestionCategory.OTHER


class TestPatternDetectorHash:
    """PatternDetectorのハッシュ生成機能のテスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックデータベース接続"""
        return MagicMock()

    @pytest.fixture
    def detector(self, mock_conn):
        """PatternDetectorインスタンス"""
        org_id = uuid4()
        return PatternDetector(mock_conn, org_id)

    def test_hash_deterministic(self, detector):
        """ハッシュは決定論的"""
        hash1 = detector._generate_hash("週報の出し方")
        hash2 = detector._generate_hash("週報の出し方")
        assert hash1 == hash2

    def test_hash_different_for_different_text(self, detector):
        """異なるテキストは異なるハッシュ"""
        hash1 = detector._generate_hash("週報の出し方")
        hash2 = detector._generate_hash("経費精算の方法")
        assert hash1 != hash2

    def test_hash_same_text_same_hash(self, detector):
        """同じテキストは同じハッシュ"""
        hash1 = detector._generate_hash("テスト質問です")
        hash2 = detector._generate_hash("テスト質問です")
        assert hash1 == hash2

    def test_hash_length(self, detector):
        """ハッシュは64文字"""
        result = detector._generate_hash("テスト")
        assert len(result) == 64

    def test_hash_is_hex(self, detector):
        """ハッシュは16進数文字列"""
        result = detector._generate_hash("テスト")
        # 16進数文字列として有効かチェック
        try:
            int(result, 16)
            is_hex = True
        except ValueError:
            is_hex = False
        assert is_hex


# ================================================================
# __init__.py のテスト（インポートテスト）
# ================================================================

class TestDetectionImports:
    """lib/detection/ からのインポートテスト"""

    def test_import_all(self):
        """__all__で定義されたものがインポートできること"""
        from lib.detection import (
            __version__,
            __author__,
            DetectionParameters,
            QuestionCategory,
            PatternDetector,
            BaseDetector,
            DetectionResult,
            InsightData,
        )
        assert __version__ is not None
        assert __author__ is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
