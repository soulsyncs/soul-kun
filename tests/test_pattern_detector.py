"""
Phase 2 進化版 A1: PatternDetector 包括的ユニットテスト

このモジュールは、lib/detection/pattern_detector.py のカバレッジを80%以上に
引き上げるための包括的なユニットテストを提供します。

テスト対象:
- PatternData: データクラスとそのメソッド
- PatternDetector: 全パブリックメソッドとプロパティ
- 正規化機能: _normalize_question, _remove_greetings_simple, _normalize_width
- カテゴリ分類: _classify_category
- ハッシュ生成: _generate_hash
- パターン操作: _find_existing_pattern, _update_pattern, _create_pattern
- インサイト生成: _create_insight_data, _pattern_to_dict
- バッチ処理: detect_batch
- 分析・レポート: get_top_patterns, get_patterns_summary

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-02-04
"""

import hashlib
import pytest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from uuid import UUID, uuid4

# テスト対象のインポート
from lib.detection.constants import (
    DetectionParameters,
    QuestionCategory,
    CATEGORY_KEYWORDS,
    PatternStatus,
    InsightType,
    SourceType,
    Importance,
    Classification,
)
from lib.detection.base import (
    DetectionContext,
    DetectionResult,
    InsightData,
)
from lib.detection.pattern_detector import (
    PatternData,
    PatternDetector,
)
from lib.detection.exceptions import (
    ValidationError,
    PatternSaveError,
    DatabaseError,
)


# ================================================================
# テストフィクスチャ
# ================================================================

@pytest.fixture
def mock_conn():
    """SQLAlchemy接続のモック"""
    conn = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = None
    result.fetchall.return_value = []
    conn.execute.return_value = result
    return conn


@pytest.fixture
def org_id():
    """テスト用組織ID"""
    return uuid4()


@pytest.fixture
def user_id():
    """テスト用ユーザーID"""
    return uuid4()


@pytest.fixture
def department_id():
    """テスト用部署ID"""
    return uuid4()


@pytest.fixture
def detector(mock_conn, org_id):
    """PatternDetectorインスタンス"""
    return PatternDetector(mock_conn, org_id)


@pytest.fixture
def sample_pattern_data(org_id):
    """サンプルPatternData"""
    now = datetime.now(timezone.utc)
    return PatternData(
        id=uuid4(),
        organization_id=org_id,
        department_id=None,
        question_category=QuestionCategory.BUSINESS_PROCESS,
        question_hash="a" * 64,
        normalized_question="週報の出し方を教えてください",
        occurrence_count=5,
        occurrence_timestamps=[now - timedelta(days=i) for i in range(5)],
        first_asked_at=now - timedelta(days=10),
        last_asked_at=now,
        asked_by_user_ids=[uuid4() for _ in range(3)],
        sample_questions=["週報の出し方は？", "週報を出すには？"],
        status=PatternStatus.ACTIVE
    )


# ================================================================
# PatternData クラスのテスト
# ================================================================

class TestPatternData:
    """PatternData データクラスのテスト"""

    def test_basic_creation(self, org_id):
        """基本的なPatternData作成"""
        pattern_id = uuid4()
        now = datetime.now(timezone.utc)
        user_ids = [uuid4()]

        data = PatternData(
            id=pattern_id,
            organization_id=org_id,
            department_id=None,
            question_category=QuestionCategory.BUSINESS_PROCESS,
            question_hash="abc123" + "0" * 58,
            normalized_question="週報の出し方",
            occurrence_count=3,
            occurrence_timestamps=[now],
            first_asked_at=now,
            last_asked_at=now,
            asked_by_user_ids=user_ids,
            sample_questions=["週報の出し方は？"],
            status=PatternStatus.ACTIVE
        )

        assert data.id == pattern_id
        assert data.organization_id == org_id
        assert data.department_id is None
        assert data.question_category == QuestionCategory.BUSINESS_PROCESS
        assert data.occurrence_count == 3
        assert data.status == PatternStatus.ACTIVE

    def test_creation_with_department_id(self, org_id, department_id):
        """部署ID付きのPatternData作成"""
        now = datetime.now(timezone.utc)

        data = PatternData(
            id=uuid4(),
            organization_id=org_id,
            department_id=department_id,
            question_category=QuestionCategory.TECHNICAL,
            question_hash="def456" + "0" * 58,
            normalized_question="VPNの接続方法",
            occurrence_count=2,
            occurrence_timestamps=[now],
            first_asked_at=now,
            last_asked_at=now,
            asked_by_user_ids=[uuid4()],
            sample_questions=["VPNに繋がらない"],
            status=PatternStatus.ACTIVE
        )

        assert data.department_id == department_id

    def test_window_occurrence_count_property(self, org_id):
        """window_occurrence_countプロパティのテスト"""
        now = datetime.now(timezone.utc)
        timestamps = [now - timedelta(hours=i) for i in range(5)]

        data = PatternData(
            id=uuid4(),
            organization_id=org_id,
            department_id=None,
            question_category=QuestionCategory.BUSINESS_PROCESS,
            question_hash="a" * 64,
            normalized_question="テスト",
            occurrence_count=10,  # 全期間は10回
            occurrence_timestamps=timestamps,  # ウィンドウ内は5回
            first_asked_at=now - timedelta(days=30),
            last_asked_at=now,
            asked_by_user_ids=[uuid4()],
            sample_questions=["テスト"],
            status=PatternStatus.ACTIVE
        )

        assert data.window_occurrence_count == 5

    def test_window_occurrence_count_empty(self, org_id):
        """空のoccurrence_timestampsでのwindow_occurrence_count"""
        now = datetime.now(timezone.utc)

        data = PatternData(
            id=uuid4(),
            organization_id=org_id,
            department_id=None,
            question_category=QuestionCategory.OTHER,
            question_hash="b" * 64,
            normalized_question="テスト",
            occurrence_count=1,
            occurrence_timestamps=[],
            first_asked_at=now,
            last_asked_at=now,
            asked_by_user_ids=[uuid4()],
            sample_questions=["テスト"],
            status=PatternStatus.ACTIVE
        )

        assert data.window_occurrence_count == 0

    def test_get_window_occurrence_count_with_mixed_timestamps(self, org_id):
        """get_window_occurrence_count: 古いタイムスタンプと新しいタイムスタンプの混合"""
        now = datetime.now(timezone.utc)
        timestamps = [
            now - timedelta(days=50),  # ウィンドウ外
            now - timedelta(days=40),  # ウィンドウ外
            now - timedelta(days=25),  # 30日ウィンドウ内
            now - timedelta(days=10),  # 30日ウィンドウ内
            now,                        # 30日ウィンドウ内
        ]

        data = PatternData(
            id=uuid4(),
            organization_id=org_id,
            department_id=None,
            question_category=QuestionCategory.BUSINESS_PROCESS,
            question_hash="c" * 64,
            normalized_question="テスト",
            occurrence_count=5,
            occurrence_timestamps=timestamps,
            first_asked_at=timestamps[0],
            last_asked_at=now,
            asked_by_user_ids=[uuid4()],
            sample_questions=["テスト"],
            status=PatternStatus.ACTIVE
        )

        # 30日ウィンドウ
        assert data.get_window_occurrence_count(window_days=30) == 3
        # 60日ウィンドウ
        assert data.get_window_occurrence_count(window_days=60) == 5
        # 7日ウィンドウ
        assert data.get_window_occurrence_count(window_days=7) == 1

    def test_from_row_basic(self, org_id):
        """from_row: 基本的なDB行からの変換"""
        pattern_id = uuid4()
        user_id = uuid4()
        now = datetime.now(timezone.utc)

        row = (
            str(pattern_id),           # id
            str(org_id),               # organization_id
            None,                       # department_id
            "business_process",         # question_category
            "d" * 64,                   # question_hash
            "正規化された質問",           # normalized_question
            5,                          # occurrence_count
            [now],                      # occurrence_timestamps
            now,                        # first_asked_at
            now,                        # last_asked_at
            [str(user_id)],            # asked_by_user_ids
            ["サンプル質問"],            # sample_questions
            "active",                   # status
        )

        data = PatternData.from_row(row)

        assert data.id == pattern_id
        assert data.organization_id == org_id
        assert data.department_id is None
        assert data.question_category == QuestionCategory.BUSINESS_PROCESS
        assert data.occurrence_count == 5
        assert data.status == PatternStatus.ACTIVE
        assert len(data.asked_by_user_ids) == 1

    def test_from_row_with_department(self, org_id, department_id):
        """from_row: 部署ID付きのDB行からの変換"""
        pattern_id = uuid4()
        now = datetime.now(timezone.utc)

        row = (
            str(pattern_id),
            str(org_id),
            str(department_id),  # 部署ID
            "technical",
            "e" * 64,
            "VPNの接続方法",
            3,
            [now],
            now,
            now,
            [],
            [],
            "active",
        )

        data = PatternData.from_row(row)

        assert data.department_id == department_id

    def test_from_row_with_iso_string_timestamps(self, org_id):
        """from_row: ISO形式文字列のタイムスタンプを変換"""
        pattern_id = uuid4()
        now = datetime.now(timezone.utc)
        iso_string = "2026-02-04T10:30:00+00:00"

        row = (
            str(pattern_id),
            str(org_id),
            None,
            "other",
            "f" * 64,
            "テスト",
            1,
            [iso_string],  # ISO形式文字列
            now,
            now,
            [],
            [],
            "active",
        )

        data = PatternData.from_row(row)

        assert len(data.occurrence_timestamps) == 1
        assert isinstance(data.occurrence_timestamps[0], datetime)

    def test_from_row_with_z_suffix_timestamps(self, org_id):
        """from_row: Zサフィックス付きISO形式タイムスタンプを変換"""
        pattern_id = uuid4()
        now = datetime.now(timezone.utc)
        iso_string_z = "2026-02-04T10:30:00Z"

        row = (
            str(pattern_id),
            str(org_id),
            None,
            "other",
            "g" * 64,
            "テスト",
            1,
            [iso_string_z],
            now,
            now,
            [],
            [],
            "active",
        )

        data = PatternData.from_row(row)

        assert len(data.occurrence_timestamps) == 1

    def test_from_row_with_invalid_timestamp_string(self, org_id):
        """from_row: 無効なタイムスタンプ文字列は無視される"""
        pattern_id = uuid4()
        now = datetime.now(timezone.utc)

        row = (
            str(pattern_id),
            str(org_id),
            None,
            "other",
            "h" * 64,
            "テスト",
            1,
            ["invalid-timestamp", now],  # 無効な文字列と有効なdatetime
            now,
            now,
            [],
            [],
            "active",
        )

        data = PatternData.from_row(row)

        # 無効な文字列は無視されるので1つだけ
        assert len(data.occurrence_timestamps) == 1

    def test_from_row_with_empty_arrays(self, org_id):
        """from_row: 空の配列フィールドを処理"""
        pattern_id = uuid4()
        now = datetime.now(timezone.utc)

        row = (
            str(pattern_id),
            str(org_id),
            None,
            "other",
            "i" * 64,
            "テスト",
            1,
            None,  # occurrence_timestamps: None
            now,
            now,
            None,  # asked_by_user_ids: None
            None,  # sample_questions: None
            "active",
        )

        data = PatternData.from_row(row)

        assert data.occurrence_timestamps == []
        assert data.asked_by_user_ids == []
        assert data.sample_questions == []

    def test_from_row_unknown_category(self, org_id):
        """from_row: 不明なカテゴリはOTHERにフォールバック"""
        pattern_id = uuid4()
        now = datetime.now(timezone.utc)

        row = (
            str(pattern_id),
            str(org_id),
            None,
            "unknown_category",  # 不明なカテゴリ
            "j" * 64,
            "テスト",
            1,
            [],
            now,
            now,
            [],
            [],
            "active",
        )

        data = PatternData.from_row(row)

        assert data.question_category == QuestionCategory.OTHER


# ================================================================
# PatternDetector プロパティのテスト
# ================================================================

class TestPatternDetectorProperties:
    """PatternDetectorのプロパティテスト"""

    def test_pattern_threshold_default(self, mock_conn, org_id):
        """pattern_threshold: デフォルト値"""
        detector = PatternDetector(mock_conn, org_id)
        assert detector.pattern_threshold == DetectionParameters.PATTERN_THRESHOLD

    def test_pattern_threshold_custom(self, mock_conn, org_id):
        """pattern_threshold: カスタム値"""
        detector = PatternDetector(mock_conn, org_id, pattern_threshold=10)
        assert detector.pattern_threshold == 10

    def test_pattern_window_days_default(self, mock_conn, org_id):
        """pattern_window_days: デフォルト値"""
        detector = PatternDetector(mock_conn, org_id)
        assert detector.pattern_window_days == DetectionParameters.PATTERN_WINDOW_DAYS

    def test_pattern_window_days_custom(self, mock_conn, org_id):
        """pattern_window_days: カスタム値"""
        detector = PatternDetector(mock_conn, org_id, pattern_window_days=14)
        assert detector.pattern_window_days == 14

    def test_max_sample_questions_default(self, mock_conn, org_id):
        """max_sample_questions: デフォルト値"""
        detector = PatternDetector(mock_conn, org_id)
        assert detector.max_sample_questions == DetectionParameters.MAX_SAMPLE_QUESTIONS

    def test_max_sample_questions_custom(self, mock_conn, org_id):
        """max_sample_questions: カスタム値"""
        detector = PatternDetector(mock_conn, org_id, max_sample_questions=10)
        assert detector.max_sample_questions == 10

    def test_max_occurrence_timestamps_default(self, mock_conn, org_id):
        """max_occurrence_timestamps: デフォルト値"""
        detector = PatternDetector(mock_conn, org_id)
        assert detector.max_occurrence_timestamps == DetectionParameters.MAX_OCCURRENCE_TIMESTAMPS

    def test_max_occurrence_timestamps_custom(self, mock_conn, org_id):
        """max_occurrence_timestamps: カスタム値"""
        detector = PatternDetector(mock_conn, org_id, max_occurrence_timestamps=100)
        assert detector.max_occurrence_timestamps == 100


# ================================================================
# 正規化機能のテスト
# ================================================================

class TestPatternDetectorNormalization:
    """PatternDetectorの正規化機能テスト"""

    def test_normalize_empty_string(self, detector):
        """空文字列の正規化"""
        assert detector._normalize_question("") == ""

    def test_normalize_none_equivalent(self, detector):
        """空白のみの文字列の正規化"""
        assert detector._normalize_question("   ") == ""

    def test_normalize_basic_whitespace(self, detector):
        """基本的な空白の除去"""
        result = detector._normalize_question("  テスト質問です  ")
        assert result == "テスト質問です"

    def test_normalize_newlines(self, detector):
        """改行の正規化"""
        result = detector._normalize_question("テスト\n質問\nです")
        assert "\n" not in result
        assert "テスト 質問 です" == result or "テスト質問です" in result

    def test_normalize_multiple_spaces(self, detector):
        """連続スペースの正規化"""
        result = detector._normalize_question("テスト    質問    です")
        assert "    " not in result
        assert "テスト 質問 です" == result

    def test_normalize_greeting_otsukare(self, detector):
        """「お疲れ様です」の除去"""
        result = detector._normalize_question("お疲れ様です。週報の出し方を教えてください")
        assert "お疲れ様" not in result
        assert "週報" in result

    def test_normalize_greeting_otsukare_variation(self, detector):
        """「お疲れさまです」の除去（ひらがな）"""
        result = detector._normalize_question("お疲れさまです、週報の出し方を教えてください")
        assert "お疲れさま" not in result
        assert "週報" in result

    def test_normalize_greeting_osewa(self, detector):
        """「お世話になっております」の除去"""
        result = detector._normalize_question("お世話になっております。経費精算について教えてください")
        assert "お世話になっております" not in result
        assert "経費精算" in result

    def test_normalize_greeting_konnichiwa(self, detector):
        """「こんにちは」の除去"""
        result = detector._normalize_question("こんにちは。質問があります")
        assert "こんにちは" not in result

    def test_normalize_greeting_konbanwa(self, detector):
        """「こんばんは」の除去"""
        result = detector._normalize_question("こんばんは。教えてください")
        assert "こんばんは" not in result

    def test_normalize_greeting_ohayo(self, detector):
        """「おはようございます」の除去"""
        result = detector._normalize_question("おはようございます。タスクの確認お願いします")
        assert "おはようございます" not in result

    def test_normalize_fullwidth_numbers(self, detector):
        """全角数字の半角変換"""
        result = detector._normalize_question("第１章の２ページ目")
        assert "1" in result
        assert "2" in result
        assert "１" not in result
        assert "２" not in result

    def test_normalize_fullwidth_letters(self, detector):
        """全角英字の半角変換"""
        result = detector._normalize_question("ＶＰＮの設定")
        assert "VPN" in result
        assert "ＶＰＮ" not in result

    def test_normalize_fullwidth_lowercase(self, detector):
        """全角小文字英字の半角変換"""
        result = detector._normalize_question("ａｂｃのテスト")
        assert "abc" in result
        assert "ａｂｃ" not in result

    def test_normalize_mention_removal(self, detector):
        """メンションの除去"""
        result = detector._normalize_question("[To:12345678]質問があります")
        assert "[To:12345678]" not in result
        assert "質問" in result

    def test_normalize_multiple_mentions(self, detector):
        """複数メンションの除去"""
        result = detector._normalize_question("[To:12345678][To:87654321]質問です")
        assert "[To:" not in result
        assert "質問です" in result

    def test_normalize_mention_whitespace_cleanup(self, detector):
        """メンション除去後の空白正規化"""
        result = detector._normalize_question("[To:12345678]  質問です")
        assert "  " not in result


class TestRemoveGreetingsSimple:
    """_remove_greetings_simpleメソッドのテスト"""

    def test_removes_otsukare(self, detector):
        """「お疲れ様です」を除去"""
        result = detector._remove_greetings_simple("お疲れ様です。本文")
        assert "お疲れ様" not in result
        assert "本文" in result

    def test_removes_otsukare_with_comma(self, detector):
        """「お疲れ様です、」を除去"""
        result = detector._remove_greetings_simple("お疲れ様です、本文")
        assert "お疲れ様" not in result

    def test_removes_always_thanks(self, detector):
        """「いつもありがとうございます」を除去"""
        result = detector._remove_greetings_simple("いつもありがとうございます。質問です")
        assert "いつもありがとうございます" not in result
        assert "質問です" in result


class TestNormalizeWidth:
    """_normalize_widthメソッドのテスト"""

    def test_fullwidth_0_to_9(self, detector):
        """全角数字0-9の変換"""
        result = detector._normalize_width("０１２３４５６７８９")
        assert result == "0123456789"

    def test_fullwidth_a_to_z_upper(self, detector):
        """全角大文字A-Zの変換"""
        result = detector._normalize_width("ＡＢＣＤＥＦＧ")
        assert result == "ABCDEFG"

    def test_fullwidth_a_to_z_lower(self, detector):
        """全角小文字a-zの変換"""
        result = detector._normalize_width("ａｂｃｄｅｆｇ")
        assert result == "abcdefg"

    def test_mixed_characters(self, detector):
        """混在文字の変換"""
        result = detector._normalize_width("Ａ１ｂ２日本語")
        assert result == "A1b2日本語"

    def test_already_halfwidth(self, detector):
        """既に半角の文字はそのまま"""
        result = detector._normalize_width("ABC123")
        assert result == "ABC123"


# ================================================================
# カテゴリ分類のテスト
# ================================================================

class TestPatternDetectorClassification:
    """PatternDetectorのカテゴリ分類機能テスト"""

    @pytest.mark.asyncio
    async def test_classify_business_process_weekly_report(self, detector):
        """業務手続きカテゴリ: 週報"""
        result = await detector._classify_category("週報の出し方")
        assert result == QuestionCategory.BUSINESS_PROCESS

    @pytest.mark.asyncio
    async def test_classify_business_process_expense(self, detector):
        """業務手続きカテゴリ: 経費"""
        result = await detector._classify_category("経費精算の方法")
        assert result == QuestionCategory.BUSINESS_PROCESS

    @pytest.mark.asyncio
    async def test_classify_business_process_approval(self, detector):
        """業務手続きカテゴリ: 承認"""
        result = await detector._classify_category("承認フローについて")
        assert result == QuestionCategory.BUSINESS_PROCESS

    @pytest.mark.asyncio
    async def test_classify_company_rule_vacation(self, detector):
        """社内ルールカテゴリ: 有給"""
        # 「申請」はBUSINESS_PROCESSのキーワードなので、有給だけでテスト
        result = await detector._classify_category("有給について教えて")
        assert result == QuestionCategory.COMPANY_RULE

    @pytest.mark.asyncio
    async def test_classify_company_rule_dress(self, detector):
        """社内ルールカテゴリ: 服装"""
        result = await detector._classify_category("服装規定について")
        assert result == QuestionCategory.COMPANY_RULE

    @pytest.mark.asyncio
    async def test_classify_company_rule_overtime(self, detector):
        """社内ルールカテゴリ: 残業"""
        result = await detector._classify_category("残業時間の上限")
        assert result == QuestionCategory.COMPANY_RULE

    @pytest.mark.asyncio
    async def test_classify_technical_vpn(self, detector):
        """技術質問カテゴリ: VPN"""
        result = await detector._classify_category("VPNに接続できません")
        assert result == QuestionCategory.TECHNICAL

    @pytest.mark.asyncio
    async def test_classify_technical_slack(self, detector):
        """技術質問カテゴリ: Slack"""
        result = await detector._classify_category("Slackの使い方")
        assert result == QuestionCategory.TECHNICAL

    @pytest.mark.asyncio
    async def test_classify_technical_password(self, detector):
        """技術質問カテゴリ: パスワード"""
        result = await detector._classify_category("パスワードを忘れた")
        assert result == QuestionCategory.TECHNICAL

    @pytest.mark.asyncio
    async def test_classify_hr_related_evaluation(self, detector):
        """人事関連カテゴリ: 評価"""
        result = await detector._classify_category("評価面談はいつですか")
        assert result == QuestionCategory.HR_RELATED

    @pytest.mark.asyncio
    async def test_classify_hr_related_salary(self, detector):
        """人事関連カテゴリ: 給与"""
        result = await detector._classify_category("給与明細について")
        assert result == QuestionCategory.HR_RELATED

    @pytest.mark.asyncio
    async def test_classify_project_progress(self, detector):
        """プロジェクトカテゴリ: 進捗"""
        # 「報告」はBUSINESS_PROCESSのキーワードなので、進捗だけでテスト
        result = await detector._classify_category("プロジェクトの進捗を確認")
        assert result == QuestionCategory.PROJECT

    @pytest.mark.asyncio
    async def test_classify_project_deadline(self, detector):
        """プロジェクトカテゴリ: 納期"""
        result = await detector._classify_category("納期に間に合いますか")
        assert result == QuestionCategory.PROJECT

    @pytest.mark.asyncio
    async def test_classify_other_unrelated(self, detector):
        """その他カテゴリ: 分類不能"""
        result = await detector._classify_category("今日の天気は良いですね")
        assert result == QuestionCategory.OTHER

    @pytest.mark.asyncio
    async def test_classify_case_insensitive(self, detector):
        """大文字小文字を区別しない"""
        result = await detector._classify_category("SLACK の使い方")
        assert result == QuestionCategory.TECHNICAL


# ================================================================
# ハッシュ生成のテスト
# ================================================================

class TestPatternDetectorHash:
    """PatternDetectorのハッシュ生成機能テスト"""

    def test_hash_deterministic(self, detector):
        """同じ入力は同じハッシュ"""
        hash1 = detector._generate_hash("テスト質問")
        hash2 = detector._generate_hash("テスト質問")
        assert hash1 == hash2

    def test_hash_different_input(self, detector):
        """異なる入力は異なるハッシュ"""
        hash1 = detector._generate_hash("質問A")
        hash2 = detector._generate_hash("質問B")
        assert hash1 != hash2

    def test_hash_length_64(self, detector):
        """ハッシュ長は64文字"""
        result = detector._generate_hash("テスト")
        assert len(result) == 64

    def test_hash_is_hex(self, detector):
        """ハッシュは16進数文字列"""
        result = detector._generate_hash("テスト")
        int(result, 16)  # 例外が発生しなければOK

    def test_hash_case_insensitive_english(self, detector):
        """英字の大文字小文字は同一ハッシュ"""
        hash_lower = detector._generate_hash("test question")
        hash_upper = detector._generate_hash("TEST QUESTION")
        hash_mixed = detector._generate_hash("Test Question")
        assert hash_lower == hash_upper == hash_mixed

    def test_hash_empty_string(self, detector):
        """空文字列のハッシュ"""
        result = detector._generate_hash("")
        assert len(result) == 64

    def test_hash_unicode(self, detector):
        """Unicode文字列のハッシュ"""
        result = detector._generate_hash("日本語テスト")
        assert len(result) == 64

    def test_hash_with_special_chars(self, detector):
        """特殊文字を含む文字列のハッシュ"""
        result = detector._generate_hash("質問？！＠＃")
        assert len(result) == 64


# ================================================================
# detect メソッドのテスト
# ================================================================

class TestPatternDetectorDetect:
    """PatternDetector.detectメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_detect_empty_question_after_normalization(self, detector, user_id):
        """正規化後に空になる質問"""
        result = await detector.detect(
            question="   ",
            user_id=user_id
        )

        assert result.success is True
        assert result.detected_count == 0
        assert result.details.get("reason") == "empty_after_normalization"

    @pytest.mark.asyncio
    async def test_detect_invalid_user_id(self, detector):
        """無効なuser_idはエラー結果を返す"""
        # detect()はValidationErrorを内部でキャッチしてDetectionResultを返す
        result = await detector.detect(
            question="テスト質問",
            user_id="invalid-uuid"
        )
        assert result.success is False
        assert "内部エラー" in result.error_message

    @pytest.mark.asyncio
    async def test_detect_none_user_id(self, detector):
        """Noneのuser_idはエラー結果を返す"""
        result = await detector.detect(
            question="テスト質問",
            user_id=None
        )
        assert result.success is False
        assert "内部エラー" in result.error_message

    @pytest.mark.asyncio
    async def test_detect_invalid_department_id(self, detector, user_id):
        """無効なdepartment_idはエラー結果を返す"""
        result = await detector.detect(
            question="テスト質問",
            user_id=user_id,
            department_id="invalid-uuid"
        )
        assert result.success is False
        assert "内部エラー" in result.error_message

    @pytest.mark.asyncio
    async def test_detect_new_pattern(self, mock_conn, org_id, user_id):
        """新規パターンの検出"""
        # 既存パターンが見つからないようにモック
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        # 新規パターン作成時のIDを返す
        new_pattern_id = uuid4()
        insert_result = MagicMock()
        insert_result.fetchone.return_value = (str(new_pattern_id),)
        mock_conn.execute.side_effect = [mock_result, insert_result]

        detector = PatternDetector(mock_conn, org_id)
        result = await detector.detect(
            question="新しい質問です",
            user_id=user_id
        )

        assert result.success is True
        assert result.detected_count == 1
        assert result.details.get("is_new_pattern") is True

    @pytest.mark.asyncio
    async def test_detect_existing_pattern(self, mock_conn, org_id, user_id):
        """既存パターンの更新"""
        pattern_id = uuid4()
        now = datetime.now(timezone.utc)

        # 既存パターンを返すモック
        existing_row = (
            str(pattern_id),
            str(org_id),
            None,
            "business_process",
            "a" * 64,
            "週報の出し方",
            3,
            [now],
            now,
            now,
            [str(user_id)],
            ["週報の出し方は？"],
            "active",
        )

        find_result = MagicMock()
        find_result.fetchone.return_value = existing_row

        # 更新後のパターンを返すモック
        updated_row = (
            str(pattern_id),
            str(org_id),
            None,
            "business_process",
            "a" * 64,
            "週報の出し方",
            4,  # occurrence_count増加
            [now, now],
            now,
            now,
            [str(user_id)],
            ["週報の出し方は？", "週報の出し方教えて"],
            "active",
        )
        update_result = MagicMock()
        update_result.fetchone.return_value = updated_row

        # insight_exists_for_sourceのモック
        insight_check_result = MagicMock()
        insight_check_result.fetchone.return_value = None

        mock_conn.execute.side_effect = [find_result, update_result, insight_check_result]

        detector = PatternDetector(mock_conn, org_id)
        result = await detector.detect(
            question="週報の出し方教えて",
            user_id=user_id
        )

        assert result.success is True
        assert result.details.get("is_new_pattern") is False

    @pytest.mark.asyncio
    async def test_detect_dry_run_mode(self, mock_conn, org_id, user_id):
        """dry_runモードでDBを更新しない"""
        now = datetime.now(timezone.utc)
        pattern_id = uuid4()

        # 既存パターンを返すモック
        existing_row = (
            str(pattern_id),
            str(org_id),
            None,
            "business_process",
            "a" * 64,
            "テスト",
            3,
            [now],
            now,
            now,
            [str(user_id)],
            ["テスト"],
            "active",
        )
        find_result = MagicMock()
        find_result.fetchone.return_value = existing_row
        mock_conn.execute.return_value = find_result

        context = DetectionContext(
            organization_id=org_id,
            dry_run=True
        )

        detector = PatternDetector(mock_conn, org_id)
        result = await detector.detect(
            question="テスト質問",
            user_id=user_id,
            context=context
        )

        assert result.success is True
        # dry_runモードではUPDATEが呼ばれない（1回のSELECTのみ）
        assert mock_conn.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_detect_threshold_reached_creates_insight(self, mock_conn, org_id, user_id):
        """閾値到達時にインサイトを作成"""
        pattern_id = uuid4()
        now = datetime.now(timezone.utc)

        # 閾値に達したパターン（5回以上）
        existing_row = (
            str(pattern_id),
            str(org_id),
            None,
            "business_process",
            "a" * 64,
            "週報の出し方",
            5,
            [now - timedelta(days=i) for i in range(5)],  # 5個のタイムスタンプ
            now - timedelta(days=10),
            now,
            [str(uuid4()) for _ in range(3)],
            ["週報の出し方は？"],
            "active",
        )

        find_result = MagicMock()
        find_result.fetchone.return_value = existing_row

        update_result = MagicMock()
        update_result.fetchone.return_value = existing_row

        # インサイト存在チェック: 存在しない
        insight_check = MagicMock()
        insight_check.fetchone.return_value = None

        # インサイト作成結果
        insight_id = uuid4()
        insight_create = MagicMock()
        insight_create.fetchone.return_value = (str(insight_id),)

        mock_conn.execute.side_effect = [find_result, update_result, insight_check, insight_create]

        detector = PatternDetector(mock_conn, org_id)
        result = await detector.detect(
            question="週報の出し方教えて",
            user_id=user_id
        )

        assert result.success is True
        assert result.insight_created is True or result.insight_id is not None

    @pytest.mark.asyncio
    async def test_detect_exception_handling(self, mock_conn, org_id, user_id):
        """例外発生時のエラーハンドリング"""
        mock_conn.execute.side_effect = Exception("Database connection error")

        detector = PatternDetector(mock_conn, org_id)
        result = await detector.detect(
            question="テスト質問",
            user_id=user_id
        )

        assert result.success is False
        assert "内部エラー" in result.error_message

    @pytest.mark.asyncio
    async def test_detect_with_department_id(self, mock_conn, org_id, user_id, department_id):
        """部署ID付きの検出"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None

        new_pattern_id = uuid4()
        insert_result = MagicMock()
        insert_result.fetchone.return_value = (str(new_pattern_id),)

        mock_conn.execute.side_effect = [mock_result, insert_result]

        detector = PatternDetector(mock_conn, org_id)
        result = await detector.detect(
            question="部署特有の質問",
            user_id=user_id,
            department_id=department_id
        )

        assert result.success is True


# ================================================================
# detect_batch メソッドのテスト
# ================================================================

class TestPatternDetectorBatch:
    """PatternDetector.detect_batchメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_detect_batch_empty_list(self, detector):
        """空のリストでのバッチ処理"""
        results = await detector.detect_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_detect_batch_single_item(self, mock_conn, org_id):
        """単一アイテムのバッチ処理"""
        user_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        insert_result = MagicMock()
        insert_result.fetchone.return_value = (str(uuid4()),)
        mock_conn.execute.side_effect = [mock_result, insert_result]

        detector = PatternDetector(mock_conn, org_id)

        questions = [
            {"question": "テスト質問", "user_id": user_id}
        ]

        results = await detector.detect_batch(questions)

        assert len(results) == 1
        assert results[0].success is True

    @pytest.mark.asyncio
    async def test_detect_batch_multiple_items(self, mock_conn, org_id):
        """複数アイテムのバッチ処理"""
        user_id = uuid4()

        # 各質問に対してmock結果を設定
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        insert_result = MagicMock()
        insert_result.fetchone.return_value = (str(uuid4()),)

        # 3つの質問に対して、各質問でfind + insert の2回ずつ
        mock_conn.execute.side_effect = [
            mock_result, insert_result,  # 質問1
            mock_result, insert_result,  # 質問2
            mock_result, insert_result,  # 質問3
        ]

        detector = PatternDetector(mock_conn, org_id)

        questions = [
            {"question": "質問1", "user_id": user_id},
            {"question": "質問2", "user_id": user_id},
            {"question": "質問3", "user_id": user_id},
        ]

        results = await detector.detect_batch(questions)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_detect_batch_with_errors(self, mock_conn, org_id):
        """エラーを含むバッチ処理"""
        user_id = uuid4()

        # 最初の質問は成功、2番目はエラー
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        insert_result = MagicMock()
        insert_result.fetchone.return_value = (str(uuid4()),)

        mock_conn.execute.side_effect = [
            mock_result, insert_result,  # 質問1: 成功
            Exception("DB Error"),        # 質問2: エラー
            mock_result, insert_result,  # 質問3: 成功
        ]

        detector = PatternDetector(mock_conn, org_id)

        questions = [
            {"question": "質問1", "user_id": user_id},
            {"question": "質問2", "user_id": user_id},
            {"question": "質問3", "user_id": user_id},
        ]

        results = await detector.detect_batch(questions)

        assert len(results) == 3
        assert results[1].success is False


# ================================================================
# get_top_patterns メソッドのテスト
# ================================================================

class TestGetTopPatterns:
    """PatternDetector.get_top_patternsメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_top_patterns_empty(self, mock_conn, org_id):
        """パターンが存在しない場合"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        patterns = await detector.get_top_patterns()

        assert patterns == []

    @pytest.mark.asyncio
    async def test_get_top_patterns_with_results(self, mock_conn, org_id):
        """パターンが存在する場合"""
        now = datetime.now(timezone.utc)
        user_id = uuid4()

        rows = [
            (
                str(uuid4()),
                str(org_id),
                None,
                "business_process",
                "a" * 64,
                "週報の出し方",
                10,
                [now],
                now,
                now,
                [str(user_id)],
                ["週報"],
                "active",
            ),
            (
                str(uuid4()),
                str(org_id),
                None,
                "technical",
                "b" * 64,
                "VPNの接続",
                8,
                [now],
                now,
                now,
                [str(user_id)],
                ["VPN"],
                "active",
            ),
        ]

        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        patterns = await detector.get_top_patterns()

        assert len(patterns) == 2
        assert patterns[0].occurrence_count == 10

    @pytest.mark.asyncio
    async def test_get_top_patterns_with_limit(self, mock_conn, org_id):
        """limit指定"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        await detector.get_top_patterns(limit=5)

        # SQLパラメータにlimitが含まれていることを確認
        # execute(text(...), params) の形式
        call_args = mock_conn.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params["limit"] == 5

    @pytest.mark.asyncio
    async def test_get_top_patterns_limit_capped(self, mock_conn, org_id):
        """limitが1000で上限"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        await detector.get_top_patterns(limit=5000)  # 大きすぎる値

        # limitが1000に制限される
        call_args = mock_conn.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params["limit"] == 1000

    @pytest.mark.asyncio
    async def test_get_top_patterns_with_min_occurrence(self, mock_conn, org_id):
        """min_occurrence指定"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        await detector.get_top_patterns(min_occurrence=3)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params["min_occurrence"] == 3

    @pytest.mark.asyncio
    async def test_get_top_patterns_with_category_filter(self, mock_conn, org_id):
        """カテゴリフィルタ指定"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        await detector.get_top_patterns(category=QuestionCategory.TECHNICAL)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params["category"] == "technical"

    @pytest.mark.asyncio
    async def test_get_top_patterns_db_error(self, mock_conn, org_id):
        """DBエラー時"""
        mock_conn.execute.side_effect = Exception("DB Error")

        detector = PatternDetector(mock_conn, org_id)

        with pytest.raises(DatabaseError):
            await detector.get_top_patterns()


# ================================================================
# get_patterns_summary メソッドのテスト
# ================================================================

class TestGetPatternsSummary:
    """PatternDetector.get_patterns_summaryメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_patterns_summary_empty(self, mock_conn, org_id):
        """パターンが存在しない場合"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        summary = await detector.get_patterns_summary()

        assert summary["total_patterns"] == 0
        assert summary["total_occurrences"] == 0
        assert summary["by_category"] == {}

    @pytest.mark.asyncio
    async def test_get_patterns_summary_with_data(self, mock_conn, org_id):
        """サマリーデータが存在する場合"""
        rows = [
            ("business_process", 5, 50, 2.5),
            ("technical", 3, 30, 2.0),
        ]

        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        summary = await detector.get_patterns_summary()

        assert summary["total_patterns"] == 8
        assert summary["total_occurrences"] == 80
        assert "business_process" in summary["by_category"]
        assert "technical" in summary["by_category"]
        assert summary["by_category"]["business_process"]["pattern_count"] == 5

    @pytest.mark.asyncio
    async def test_get_patterns_summary_with_null_avg(self, mock_conn, org_id):
        """avg_unique_usersがNullの場合"""
        rows = [
            ("other", 1, 1, None),  # avg_unique_usersがNull
        ]

        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        summary = await detector.get_patterns_summary()

        assert summary["by_category"]["other"]["avg_unique_users"] == 0

    @pytest.mark.asyncio
    async def test_get_patterns_summary_db_error(self, mock_conn, org_id):
        """DBエラー時"""
        mock_conn.execute.side_effect = Exception("DB Error")

        detector = PatternDetector(mock_conn, org_id)

        with pytest.raises(DatabaseError):
            await detector.get_patterns_summary()


# ================================================================
# _create_insight_data メソッドのテスト
# ================================================================

class TestCreateInsightData:
    """PatternDetector._create_insight_dataメソッドのテスト"""

    def test_create_insight_data_basic(self, detector, sample_pattern_data):
        """基本的なインサイトデータ作成"""
        pattern_dict = detector._pattern_to_dict(sample_pattern_data)
        insight_data = detector._create_insight_data(pattern_dict)

        assert isinstance(insight_data, InsightData)
        assert insight_data.insight_type == InsightType.PATTERN_DETECTED
        assert insight_data.source_type == SourceType.A1_PATTERN
        assert "頻出" in insight_data.title

    def test_create_insight_data_importance_critical(self, detector, org_id):
        """CRITICAL重要度のインサイト"""
        now = datetime.now(timezone.utc)

        # 20回以上でCRITICAL
        pattern_dict = {
            "id": uuid4(),
            "organization_id": org_id,
            "department_id": None,
            "question_category": "business_process",
            "question_hash": "a" * 64,
            "normalized_question": "週報の出し方",
            "occurrence_count": 25,
            "window_occurrence_count": 25,
            "occurrence_timestamps": [now],
            "first_asked_at": now,
            "last_asked_at": now,
            "asked_by_user_ids": [uuid4() for _ in range(5)],
            "sample_questions": ["週報"],
            "status": "active",
        }

        insight_data = detector._create_insight_data(pattern_dict)

        assert insight_data.importance == Importance.CRITICAL

    def test_create_insight_data_importance_high(self, detector, org_id):
        """HIGH重要度のインサイト"""
        now = datetime.now(timezone.utc)

        # 10回以上でHIGH
        pattern_dict = {
            "id": uuid4(),
            "organization_id": org_id,
            "department_id": None,
            "question_category": "business_process",
            "question_hash": "a" * 64,
            "normalized_question": "週報の出し方",
            "occurrence_count": 15,
            "window_occurrence_count": 15,
            "occurrence_timestamps": [now],
            "first_asked_at": now,
            "last_asked_at": now,
            "asked_by_user_ids": [uuid4() for _ in range(3)],
            "sample_questions": ["週報"],
            "status": "active",
        }

        insight_data = detector._create_insight_data(pattern_dict)

        assert insight_data.importance == Importance.HIGH

    def test_create_insight_data_importance_medium(self, detector, org_id):
        """MEDIUM重要度のインサイト"""
        now = datetime.now(timezone.utc)

        # 5回以上でMEDIUM
        pattern_dict = {
            "id": uuid4(),
            "organization_id": org_id,
            "department_id": None,
            "question_category": "business_process",
            "question_hash": "a" * 64,
            "normalized_question": "週報の出し方",
            "occurrence_count": 7,
            "window_occurrence_count": 7,
            "occurrence_timestamps": [now],
            "first_asked_at": now,
            "last_asked_at": now,
            "asked_by_user_ids": [uuid4() for _ in range(2)],
            "sample_questions": ["週報"],
            "status": "active",
        }

        insight_data = detector._create_insight_data(pattern_dict)

        assert insight_data.importance == Importance.MEDIUM

    def test_create_insight_data_with_long_question(self, detector, org_id):
        """長い質問文のタイトル切り詰め"""
        now = datetime.now(timezone.utc)
        long_question = "あ" * 100  # 100文字

        pattern_dict = {
            "id": uuid4(),
            "organization_id": org_id,
            "department_id": None,
            "question_category": "other",
            "question_hash": "a" * 64,
            "normalized_question": long_question,
            "occurrence_count": 5,
            "window_occurrence_count": 5,
            "occurrence_timestamps": [now],
            "first_asked_at": now,
            "last_asked_at": now,
            "asked_by_user_ids": [uuid4()],
            "sample_questions": [long_question],
            "status": "active",
        }

        insight_data = detector._create_insight_data(pattern_dict)

        # タイトルは30文字+...で切り詰められる
        assert len(insight_data.title) < 100

    def test_create_insight_data_includes_samples(self, detector, org_id):
        """サンプル質問が説明に含まれる"""
        now = datetime.now(timezone.utc)
        samples = ["質問1", "質問2", "質問3"]

        pattern_dict = {
            "id": uuid4(),
            "organization_id": org_id,
            "department_id": None,
            "question_category": "business_process",
            "question_hash": "a" * 64,
            "normalized_question": "テスト",
            "occurrence_count": 5,
            "window_occurrence_count": 5,
            "occurrence_timestamps": [now],
            "first_asked_at": now,
            "last_asked_at": now,
            "asked_by_user_ids": [uuid4()],
            "sample_questions": samples,
            "status": "active",
        }

        insight_data = detector._create_insight_data(pattern_dict)

        assert "質問1" in insight_data.description
        assert "質問2" in insight_data.description
        assert "質問3" in insight_data.description


# ================================================================
# _pattern_to_dict メソッドのテスト
# ================================================================

class TestPatternToDict:
    """PatternDetector._pattern_to_dictメソッドのテスト"""

    def test_pattern_to_dict_basic(self, detector, sample_pattern_data):
        """基本的な辞書変換"""
        result = detector._pattern_to_dict(sample_pattern_data)

        assert result["id"] == sample_pattern_data.id
        assert result["organization_id"] == sample_pattern_data.organization_id
        assert result["question_category"] == sample_pattern_data.question_category.value
        assert result["occurrence_count"] == sample_pattern_data.occurrence_count
        assert result["window_occurrence_count"] == sample_pattern_data.window_occurrence_count
        assert result["status"] == sample_pattern_data.status.value

    def test_pattern_to_dict_with_department(self, detector, org_id, department_id):
        """部署ID付きの辞書変換"""
        now = datetime.now(timezone.utc)

        pattern = PatternData(
            id=uuid4(),
            organization_id=org_id,
            department_id=department_id,
            question_category=QuestionCategory.TECHNICAL,
            question_hash="a" * 64,
            normalized_question="テスト",
            occurrence_count=1,
            occurrence_timestamps=[now],
            first_asked_at=now,
            last_asked_at=now,
            asked_by_user_ids=[uuid4()],
            sample_questions=["テスト"],
            status=PatternStatus.ACTIVE
        )

        result = detector._pattern_to_dict(pattern)

        assert result["department_id"] == department_id

    def test_pattern_to_dict_none_department(self, detector, sample_pattern_data):
        """部署IDがNoneの場合"""
        result = detector._pattern_to_dict(sample_pattern_data)

        assert result["department_id"] is None


# ================================================================
# _find_existing_pattern メソッドのテスト
# ================================================================

class TestFindExistingPattern:
    """PatternDetector._find_existing_patternメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_find_existing_pattern_not_found(self, mock_conn, org_id):
        """パターンが見つからない場合"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        result = await detector._find_existing_pattern("a" * 64)

        assert result is None

    @pytest.mark.asyncio
    async def test_find_existing_pattern_found(self, mock_conn, org_id):
        """パターンが見つかる場合"""
        now = datetime.now(timezone.utc)
        pattern_id = uuid4()

        row = (
            str(pattern_id),
            str(org_id),
            None,
            "business_process",
            "a" * 64,
            "テスト",
            5,
            [now],
            now,
            now,
            [],
            [],
            "active",
        )

        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        result = await detector._find_existing_pattern("a" * 64)

        assert result is not None
        assert result.id == pattern_id

    @pytest.mark.asyncio
    async def test_find_existing_pattern_with_department(self, mock_conn, org_id, department_id):
        """部署IDを指定して検索"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        await detector._find_existing_pattern("a" * 64, department_id=department_id)

        # 部署IDがクエリパラメータに含まれている
        call_args = mock_conn.execute.call_args
        assert str(department_id) in str(call_args)

    @pytest.mark.asyncio
    async def test_find_existing_pattern_db_error(self, mock_conn, org_id):
        """DBエラー時"""
        mock_conn.execute.side_effect = Exception("DB Error")

        detector = PatternDetector(mock_conn, org_id)

        with pytest.raises(DatabaseError):
            await detector._find_existing_pattern("a" * 64)


# ================================================================
# _update_pattern メソッドのテスト
# ================================================================

class TestUpdatePattern:
    """PatternDetector._update_patternメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_update_pattern_success(self, mock_conn, org_id, user_id):
        """パターン更新成功"""
        pattern_id = uuid4()
        now = datetime.now(timezone.utc)

        updated_row = (
            str(pattern_id),
            str(org_id),
            None,
            "business_process",
            "a" * 64,
            "テスト",
            6,  # 増加
            [now, now],
            now,
            now,
            [str(user_id)],
            ["テスト"],
            "active",
        )

        mock_result = MagicMock()
        mock_result.fetchone.return_value = updated_row
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        result = await detector._update_pattern(
            pattern_id=pattern_id,
            user_id=user_id,
            sample_question="新しい質問"
        )

        assert result.id == pattern_id
        assert result.occurrence_count == 6

    @pytest.mark.asyncio
    async def test_update_pattern_not_found(self, mock_conn, org_id, user_id):
        """パターンが見つからない場合"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)

        with pytest.raises(PatternSaveError):
            await detector._update_pattern(
                pattern_id=uuid4(),
                user_id=user_id,
                sample_question="テスト"
            )

    @pytest.mark.asyncio
    async def test_update_pattern_reactivate(self, mock_conn, org_id, user_id):
        """パターンの再活性化"""
        pattern_id = uuid4()
        now = datetime.now(timezone.utc)

        # 再活性化後のレコード
        reactivated_row = (
            str(pattern_id),
            str(org_id),
            None,
            "business_process",
            "a" * 64,
            "テスト",
            6,
            [now],
            now,
            now,
            [str(user_id)],
            ["テスト"],
            "active",  # activeに戻る
        )

        mock_result = MagicMock()
        mock_result.fetchone.return_value = reactivated_row
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        result = await detector._update_pattern(
            pattern_id=pattern_id,
            user_id=user_id,
            sample_question="再活性化",
            reactivate=True
        )

        assert result.status == PatternStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_update_pattern_db_error(self, mock_conn, org_id, user_id):
        """DBエラー時"""
        mock_conn.execute.side_effect = Exception("DB Error")

        detector = PatternDetector(mock_conn, org_id)

        with pytest.raises(DatabaseError):
            await detector._update_pattern(
                pattern_id=uuid4(),
                user_id=user_id,
                sample_question="テスト"
            )


# ================================================================
# _create_pattern メソッドのテスト
# ================================================================

class TestCreatePattern:
    """PatternDetector._create_patternメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_create_pattern_success(self, mock_conn, org_id, user_id):
        """パターン作成成功"""
        new_pattern_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (str(new_pattern_id),)
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        result = await detector._create_pattern(
            category=QuestionCategory.BUSINESS_PROCESS,
            question_hash="a" * 64,
            normalized_question="週報の出し方",
            user_id=user_id,
            department_id=None,
            sample_question="週報の出し方を教えて"
        )

        assert result == new_pattern_id

    @pytest.mark.asyncio
    async def test_create_pattern_with_department(self, mock_conn, org_id, user_id, department_id):
        """部署ID付きパターン作成"""
        new_pattern_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (str(new_pattern_id),)
        mock_conn.execute.return_value = mock_result

        detector = PatternDetector(mock_conn, org_id)
        result = await detector._create_pattern(
            category=QuestionCategory.TECHNICAL,
            question_hash="b" * 64,
            normalized_question="VPN",
            user_id=user_id,
            department_id=department_id,
            sample_question="VPNの設定"
        )

        assert result == new_pattern_id

    @pytest.mark.asyncio
    async def test_create_pattern_conflict_fallback(self, mock_conn, org_id, user_id):
        """競合時の既存パターン更新"""
        now = datetime.now(timezone.utc)
        existing_pattern_id = uuid4()

        # INSERT時にNone（競合）
        insert_result = MagicMock()
        insert_result.fetchone.return_value = None

        # 既存パターン検索結果
        existing_row = (
            str(existing_pattern_id),
            str(org_id),
            None,
            "business_process",
            "a" * 64,
            "テスト",
            3,
            [now],
            now,
            now,
            [],
            [],
            "active",
        )
        find_result = MagicMock()
        find_result.fetchone.return_value = existing_row

        # 更新結果
        updated_row = (
            str(existing_pattern_id),
            str(org_id),
            None,
            "business_process",
            "a" * 64,
            "テスト",
            4,
            [now, now],
            now,
            now,
            [str(user_id)],
            ["テスト"],
            "active",
        )
        update_result = MagicMock()
        update_result.fetchone.return_value = updated_row

        mock_conn.execute.side_effect = [insert_result, find_result, update_result]

        detector = PatternDetector(mock_conn, org_id)
        result = await detector._create_pattern(
            category=QuestionCategory.BUSINESS_PROCESS,
            question_hash="a" * 64,
            normalized_question="テスト",
            user_id=user_id,
            department_id=None,
            sample_question="テスト質問"
        )

        assert result == existing_pattern_id

    @pytest.mark.asyncio
    async def test_create_pattern_conflict_not_found(self, mock_conn, org_id, user_id):
        """競合したが既存パターンが見つからない（異常系）"""
        # INSERT時にNone（競合）
        insert_result = MagicMock()
        insert_result.fetchone.return_value = None

        # 既存パターン検索もNone
        find_result = MagicMock()
        find_result.fetchone.return_value = None

        mock_conn.execute.side_effect = [insert_result, find_result]

        detector = PatternDetector(mock_conn, org_id)

        with pytest.raises(PatternSaveError):
            await detector._create_pattern(
                category=QuestionCategory.BUSINESS_PROCESS,
                question_hash="a" * 64,
                normalized_question="テスト",
                user_id=user_id,
                department_id=None,
                sample_question="テスト質問"
            )

    @pytest.mark.asyncio
    async def test_create_pattern_db_error(self, mock_conn, org_id, user_id):
        """DBエラー時"""
        mock_conn.execute.side_effect = Exception("DB Error")

        detector = PatternDetector(mock_conn, org_id)

        with pytest.raises(DatabaseError):
            await detector._create_pattern(
                category=QuestionCategory.OTHER,
                question_hash="a" * 64,
                normalized_question="テスト",
                user_id=user_id,
                department_id=None,
                sample_question="テスト質問"
            )


# ================================================================
# 閾値=1のテスト
# ================================================================

class TestThresholdOne:
    """閾値=1の特殊ケーステスト"""

    @pytest.mark.asyncio
    async def test_threshold_one_immediate_insight(self, mock_conn, org_id, user_id):
        """閾値=1で新規パターン作成時に即座にインサイト生成"""
        new_pattern_id = uuid4()
        now = datetime.now(timezone.utc)

        # パターン作成結果
        insert_result = MagicMock()
        insert_result.fetchone.return_value = (str(new_pattern_id),)

        # 作成したパターンの検索結果
        created_row = (
            str(new_pattern_id),
            str(org_id),
            None,
            "business_process",
            "a" * 64,
            "テスト",
            1,
            [now],
            now,
            now,
            [str(user_id)],
            ["テスト"],
            "active",
        )
        find_result = MagicMock()
        find_result.fetchone.return_value = created_row

        # インサイト存在チェック
        insight_check = MagicMock()
        insight_check.fetchone.return_value = None

        # インサイト作成結果
        insight_id = uuid4()
        insight_create = MagicMock()
        insight_create.fetchone.return_value = (str(insight_id),)

        mock_conn.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=None)),  # 既存パターン検索
            insert_result,  # パターン作成
            find_result,    # 作成したパターン検索
            insight_check,  # インサイト存在チェック
            insight_create, # インサイト作成
        ]

        detector = PatternDetector(mock_conn, org_id, pattern_threshold=1)
        result = await detector.detect(
            question="テスト質問",
            user_id=user_id
        )

        assert result.success is True
        assert result.insight_created is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
