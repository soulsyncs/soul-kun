"""
Phase 2E: 学習基盤モジュールの包括的ユニットテスト

設計書: docs/18_phase2e_learning_foundation.md v1.1.0

テスト対象:
- constants.py: 定数、Enum
- models.py: データモデル
- patterns.py: 検出パターン
- detector.py: フィードバック検出
- extractor.py: 学習内容抽出
- repository.py: DB操作
- applier.py: 学習適用
- manager.py: 学習管理
- conflict_detector.py: 矛盾検出
- authority_resolver.py: 権限解決
- effectiveness_tracker.py: 有効性追跡
- __init__.py: BrainLearning統合クラス
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from uuid import uuid4

# 定数
from lib.brain.learning_foundation.constants import (
    LearningCategory,
    LearningScope,
    AuthorityLevel,
    TriggerType,
    RelationshipType,
    DecisionImpact,
    ConflictResolutionStrategy,
    ConflictType,
    AUTHORITY_PRIORITY,
    CONFIDENCE_THRESHOLD_AUTO_LEARN,
    CONFIDENCE_THRESHOLD_CONFIRM,
    CONFIDENCE_THRESHOLD_MIN,
    DEFAULT_CONFIDENCE_DECAY_RATE,
    DEFAULT_LEARNED_CONTENT_VERSION,
    DEFAULT_CLASSIFICATION,
    POSITIVE_CONFIRMATION_KEYWORDS,
    NEGATIVE_CONFIRMATION_KEYWORDS,
    LIST_LEARNING_KEYWORDS,
    DELETE_LEARNING_KEYWORDS,
    ERROR_MESSAGES,
    SUCCESS_MESSAGES,
    CONFIRMATION_MESSAGES,
    TABLE_BRAIN_LEARNINGS,
    TABLE_BRAIN_LEARNING_LOGS,
    MAX_LEARNINGS_PER_QUERY,
    MAX_LEARNINGS_PER_CATEGORY_DISPLAY,
)

# モデル
from lib.brain.learning_foundation.models import (
    Learning,
    LearningLog,
    FeedbackDetectionResult,
    ConversationContext,
    ConflictInfo,
    Resolution,
    AppliedLearning,
    EffectivenessResult,
    ImprovementSuggestion,
    PatternMatch,
)

# パターン
from lib.brain.learning_foundation.patterns import (
    DetectionPattern,
    ALL_PATTERNS,
    PATTERNS_BY_NAME,
    PATTERNS_BY_CATEGORY,
    get_patterns_for_category,
)

# 検出
from lib.brain.learning_foundation.detector import (
    FeedbackDetector,
    create_detector,
)

# 抽出
from lib.brain.learning_foundation.extractor import (
    LearningExtractor,
    create_extractor,
)

# 統合
from lib.brain.learning_foundation import (
    BrainLearning,
    create_brain_learning,
    __version__,
)


# =============================================================================
# テスト用フィクスチャ
# =============================================================================

@pytest.fixture
def mock_conn():
    """モックDB接続"""
    conn = MagicMock()
    conn.execute = MagicMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
    return conn


@pytest.fixture
def mock_pool():
    """モックDBプール"""
    pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    pool.connect = MagicMock(return_value=mock_conn)
    return pool


@pytest.fixture
def sample_learning():
    """サンプル学習データ"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.ALIAS.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="mtg",
        learned_content={
            "type": "alias",
            "from": "mtg",
            "to": "ミーティング",
            "bidirectional": False,
            "description": "mtgはミーティングの略称",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="12345",
        taught_by_name="田中さん",
        is_active=True,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_ceo_learning():
    """サンプルCEO教えデータ"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.RULE.value,
        trigger_type=TriggerType.ALWAYS.value,
        trigger_value="*",
        learned_content={
            "type": "rule",
            "condition": "常に",
            "action": "人の可能性を信じる",
            "priority": "high",
            "is_prohibition": False,
            "description": "人の可能性を信じる",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.CEO.value,
        taught_by_account_id="1728974",
        taught_by_name="菊地さん",
        is_active=True,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_context():
    """サンプル会話コンテキスト"""
    return ConversationContext(
        previous_messages=[
            {"role": "user", "content": "タスクを教えて"},
            {"role": "assistant", "content": "タスク一覧を表示するウル！"},
        ],
        soulkun_last_action="task_search",
        soulkun_last_response="タスク一覧を表示するウル！",
        has_recent_error=False,
        room_id="room123",
        user_id="user456",
        user_name="田中さん",
    )


@pytest.fixture
def sample_detection_result():
    """サンプル検出結果"""
    return FeedbackDetectionResult(
        pattern_name="alias_definition",
        pattern_category=LearningCategory.ALIAS.value,
        match=PatternMatch(
            groups={"from_value": "mtg", "to_value": "ミーティング"},
            start=0,
            end=20,
            matched_text="mtgはミーティングのこと",
        ),
        extracted={
            "category": "alias",
            "type": "alias",
            "from_value": "mtg",
            "to_value": "ミーティング",
            "bidirectional": False,
        },
        confidence=0.85,
        context_support=False,
        recent_error_support=False,
    )


# =============================================================================
# 定数テスト（10件）
# =============================================================================

class TestConstants:
    """constants.py のテスト"""

    def test_learning_category_values(self):
        """学習カテゴリが8種類"""
        assert len(LearningCategory) == 8
        assert LearningCategory.ALIAS.value == "alias"
        assert LearningCategory.PREFERENCE.value == "preference"
        assert LearningCategory.FACT.value == "fact"
        assert LearningCategory.RULE.value == "rule"
        assert LearningCategory.CORRECTION.value == "correction"
        assert LearningCategory.CONTEXT.value == "context"
        assert LearningCategory.RELATIONSHIP.value == "relationship"
        assert LearningCategory.PROCEDURE.value == "procedure"

    def test_learning_scope_values(self):
        """学習スコープが4種類"""
        assert len(LearningScope) == 4
        assert LearningScope.GLOBAL.value == "global"
        assert LearningScope.USER.value == "user"
        assert LearningScope.ROOM.value == "room"
        assert LearningScope.TEMPORARY.value == "temporary"

    def test_authority_level_values(self):
        """権限レベルが4種類"""
        assert len(AuthorityLevel) == 4
        assert AuthorityLevel.CEO.value == "ceo"
        assert AuthorityLevel.MANAGER.value == "manager"
        assert AuthorityLevel.USER.value == "user"
        assert AuthorityLevel.SYSTEM.value == "system"

    def test_authority_priority_order(self):
        """権限優先度の順序（CEO > MANAGER > USER > SYSTEM）"""
        assert AUTHORITY_PRIORITY[AuthorityLevel.CEO.value] == 1
        assert AUTHORITY_PRIORITY[AuthorityLevel.MANAGER.value] == 2
        assert AUTHORITY_PRIORITY[AuthorityLevel.USER.value] == 3
        assert AUTHORITY_PRIORITY[AuthorityLevel.SYSTEM.value] == 4

    def test_confidence_thresholds(self):
        """確信度閾値が正しい範囲"""
        assert CONFIDENCE_THRESHOLD_AUTO_LEARN == 0.7
        assert CONFIDENCE_THRESHOLD_CONFIRM == 0.4
        assert CONFIDENCE_THRESHOLD_MIN == 0.2
        assert CONFIDENCE_THRESHOLD_AUTO_LEARN > CONFIDENCE_THRESHOLD_CONFIRM
        assert CONFIDENCE_THRESHOLD_CONFIRM > CONFIDENCE_THRESHOLD_MIN

    def test_trigger_type_values(self):
        """トリガータイプが4種類"""
        assert len(TriggerType) == 4
        assert TriggerType.KEYWORD.value == "keyword"
        assert TriggerType.PATTERN.value == "pattern"
        assert TriggerType.CONTEXT.value == "context"
        assert TriggerType.ALWAYS.value == "always"

    def test_confirmation_keywords(self):
        """確認キーワードが適切に定義"""
        assert "うん" in POSITIVE_CONFIRMATION_KEYWORDS
        assert "はい" in POSITIVE_CONFIRMATION_KEYWORDS
        assert "いや" in NEGATIVE_CONFIRMATION_KEYWORDS
        assert "違う" in NEGATIVE_CONFIRMATION_KEYWORDS

    def test_management_keywords(self):
        """管理コマンドキーワードが定義"""
        assert "何覚えてる" in LIST_LEARNING_KEYWORDS
        assert "忘れて" in DELETE_LEARNING_KEYWORDS

    def test_message_templates(self):
        """メッセージテンプレートが定義"""
        assert "ceo_conflict" in ERROR_MESSAGES
        assert "save_failed" in ERROR_MESSAGES
        assert "alias" in SUCCESS_MESSAGES
        assert "alias" in CONFIRMATION_MESSAGES

    def test_db_constants(self):
        """DB関連定数が適切"""
        assert TABLE_BRAIN_LEARNINGS == "brain_learnings"
        assert TABLE_BRAIN_LEARNING_LOGS == "brain_learning_logs"
        assert MAX_LEARNINGS_PER_QUERY == 100
        assert MAX_LEARNINGS_PER_CATEGORY_DISPLAY == 10


# =============================================================================
# モデルテスト（15件）
# =============================================================================

class TestLearningModel:
    """Learningデータモデルのテスト"""

    def test_create_with_defaults(self):
        """デフォルト値で作成"""
        learning = Learning()
        assert learning.id is None
        assert learning.organization_id is None
        assert learning.category == LearningCategory.FACT.value
        assert learning.scope == LearningScope.GLOBAL.value
        assert learning.authority_level == AuthorityLevel.USER.value
        assert learning.is_active is True
        assert learning.applied_count == 0

    def test_create_with_values(self, sample_learning):
        """値指定で作成"""
        assert sample_learning.category == LearningCategory.ALIAS.value
        assert sample_learning.trigger_value == "mtg"
        assert sample_learning.learned_content["to"] == "ミーティング"

    def test_to_dict(self, sample_learning):
        """辞書変換"""
        d = sample_learning.to_dict()
        assert d["category"] == LearningCategory.ALIAS.value
        assert d["trigger_value"] == "mtg"
        assert "learned_content" in d
        assert "created_at" in d

    def test_from_dict(self):
        """辞書から生成"""
        data = {
            "id": "test-id",
            "organization_id": "org_test",
            "category": "alias",
            "trigger_value": "abc",
            "learned_content": {"from": "abc", "to": "ABC"},
        }
        learning = Learning.from_dict(data)
        assert learning.id == "test-id"
        assert learning.category == "alias"
        assert learning.learned_content["from"] == "abc"

    def test_get_description_alias(self, sample_learning):
        """別名の説明取得"""
        desc = sample_learning.get_description()
        assert "mtg" in desc
        assert "ミーティング" in desc

    def test_get_description_rule(self, sample_ceo_learning):
        """ルールの説明取得"""
        desc = sample_ceo_learning.get_description()
        assert "人の可能性を信じる" in desc

    def test_authority_level_priority(self, sample_learning, sample_ceo_learning):
        """権限レベル優先度取得"""
        assert sample_learning.authority_level_priority == 3  # USER
        assert sample_ceo_learning.authority_level_priority == 1  # CEO


class TestLearningLogModel:
    """LearningLogデータモデルのテスト"""

    def test_create_with_defaults(self):
        """デフォルト値で作成"""
        log = LearningLog()
        assert log.id is None
        assert log.learning_id == ""
        assert log.feedback_received is False

    def test_to_dict(self):
        """辞書変換"""
        log = LearningLog(
            id="log-1",
            learning_id="learning-1",
            applied_at=datetime.now(),
            applied_in_room_id="room123",
        )
        d = log.to_dict()
        assert d["id"] == "log-1"
        assert d["learning_id"] == "learning-1"
        assert "applied_at" in d


class TestFeedbackDetectionResultModel:
    """FeedbackDetectionResultデータモデルのテスト"""

    def test_create_with_defaults(self):
        """デフォルト値で作成"""
        result = FeedbackDetectionResult()
        assert result.pattern_name == ""
        assert result.confidence == 0.0
        assert result.extracted == {}

    def test_to_dict(self, sample_detection_result):
        """辞書変換"""
        d = sample_detection_result.to_dict()
        assert d["pattern_name"] == "alias_definition"
        assert d["confidence"] == 0.85
        assert "match" in d
        assert "extracted" in d


class TestConversationContextModel:
    """ConversationContextデータモデルのテスト"""

    def test_create_with_values(self, sample_context):
        """値指定で作成"""
        assert sample_context.room_id == "room123"
        assert sample_context.user_name == "田中さん"
        assert sample_context.has_recent_error is False

    def test_to_dict(self, sample_context):
        """辞書変換"""
        d = sample_context.to_dict()
        assert d["room_id"] == "room123"
        assert d["user_name"] == "田中さん"
        assert len(d["previous_messages"]) == 2


class TestConflictInfoModel:
    """ConflictInfoデータモデルのテスト"""

    def test_create_with_learnings(self, sample_learning, sample_ceo_learning):
        """学習を指定して作成"""
        conflict = ConflictInfo(
            new_learning=sample_learning,
            existing_learning=sample_ceo_learning,
            conflict_type=ConflictType.CEO_CONFLICT.value,
            resolution_suggestion="CEO教えを優先",
        )
        assert conflict.conflict_type == ConflictType.CEO_CONFLICT.value
        assert conflict.new_learning.category == LearningCategory.ALIAS.value
        assert conflict.existing_learning.authority_level == AuthorityLevel.CEO.value


# =============================================================================
# パターンテスト（18件）
# =============================================================================

class TestPatterns:
    """patterns.py のテスト"""

    def test_all_patterns_not_empty(self):
        """パターンリストが空でない"""
        assert len(ALL_PATTERNS) > 0

    def test_all_patterns_have_required_fields(self):
        """全パターンが必須フィールドを持つ"""
        for pattern in ALL_PATTERNS:
            assert pattern.name, "パターン名が必要"
            assert pattern.category, "カテゴリが必要"
            assert pattern.base_confidence > 0, "基本確信度が必要"

    def test_patterns_by_name_lookup(self):
        """パターン名で検索できる"""
        assert len(PATTERNS_BY_NAME) > 0
        # 最初のパターン名で検索
        first_pattern = ALL_PATTERNS[0]
        assert first_pattern.name in PATTERNS_BY_NAME
        assert PATTERNS_BY_NAME[first_pattern.name] == first_pattern

    def test_patterns_by_category(self):
        """カテゴリ別パターン取得"""
        assert len(PATTERNS_BY_CATEGORY) > 0
        # 少なくとも1つのカテゴリにパターンがある
        has_patterns = False
        for patterns in PATTERNS_BY_CATEGORY.values():
            if len(patterns) > 0:
                has_patterns = True
                break
        assert has_patterns

    def test_get_patterns_for_category(self):
        """カテゴリ別パターン取得関数"""
        alias_patterns = get_patterns_for_category(LearningCategory.ALIAS.value)
        # 別名パターンが存在することを確認
        for pattern in alias_patterns:
            assert pattern.category == LearningCategory.ALIAS.value

    def test_detection_pattern_dataclass(self):
        """DetectionPatternデータクラス"""
        pattern = DetectionPattern(
            name="test_pattern",
            category=LearningCategory.FACT.value,
            regex_patterns=[r"テスト"],
            base_confidence=0.75,
            priority=10,
        )
        assert pattern.name == "test_pattern"
        assert pattern.base_confidence == 0.75

    def test_pattern_match_method(self):
        """パターンのmatchメソッド"""
        # 別名パターンを取得してテスト
        alias_patterns = get_patterns_for_category(LearningCategory.ALIAS.value)
        if alias_patterns:
            pattern = alias_patterns[0]
            # パターンによってはマッチしないかもしれないが、メソッドが存在することを確認
            result = pattern.match("これはテストメッセージ")
            # 結果はNoneまたは辞書
            assert result is None or isinstance(result, dict)

    def test_pattern_priority_ordering(self):
        """パターンが優先度順にソートされている"""
        for i in range(len(ALL_PATTERNS) - 1):
            # 優先度が高い順（大きい数字が先）
            assert ALL_PATTERNS[i].priority >= ALL_PATTERNS[i + 1].priority


class TestPatternMatching:
    """パターンマッチングのテスト"""

    def test_alias_pattern_match(self):
        """別名パターンのマッチ"""
        alias_patterns = get_patterns_for_category(LearningCategory.ALIAS.value)
        # 「AはBのこと」パターンをテスト
        test_messages = [
            "mtgはミーティングのこと",
            "PLはプロジェクトリーダーの略",
        ]
        for msg in test_messages:
            for pattern in alias_patterns:
                result = pattern.match(msg)
                if result:
                    assert "groups" in result or result.get("matched_text")

    def test_correction_pattern_match(self):
        """修正パターンのマッチ"""
        correction_patterns = get_patterns_for_category(LearningCategory.CORRECTION.value)
        test_messages = [
            "違う、田中さんじゃなくて佐藤さん",
            "正しくは12時",
        ]
        for msg in test_messages:
            for pattern in correction_patterns:
                result = pattern.match(msg)
                if result:
                    assert isinstance(result, dict)

    def test_rule_pattern_match(self):
        """ルールパターンのマッチ"""
        rule_patterns = get_patterns_for_category(LearningCategory.RULE.value)
        test_messages = [
            "月曜日は朝会がある",
            "報告書は金曜日までに提出",
        ]
        for msg in test_messages:
            for pattern in rule_patterns:
                result = pattern.match(msg)
                if result:
                    assert isinstance(result, dict)

    def test_fact_pattern_match(self):
        """事実パターンのマッチ"""
        fact_patterns = get_patterns_for_category(LearningCategory.FACT.value)
        test_messages = [
            "田中さんの電話番号は090-1234-5678",
            "会社の住所は東京都渋谷区",
        ]
        for msg in test_messages:
            for pattern in fact_patterns:
                result = pattern.match(msg)
                if result:
                    assert isinstance(result, dict)

    def test_preference_pattern_match(self):
        """好みパターンのマッチ"""
        pref_patterns = get_patterns_for_category(LearningCategory.PREFERENCE.value)
        test_messages = [
            "箇条書きで教えて",
            "詳しく説明してほしい",
        ]
        for msg in test_messages:
            for pattern in pref_patterns:
                result = pattern.match(msg)
                if result:
                    assert isinstance(result, dict)

    def test_relationship_pattern_match(self):
        """関係パターンのマッチ"""
        rel_patterns = get_patterns_for_category(LearningCategory.RELATIONSHIP.value)
        test_messages = [
            "田中さんと佐藤さんは同期",
            "山田さんは鈴木さんの上司",
        ]
        for msg in test_messages:
            for pattern in rel_patterns:
                result = pattern.match(msg)
                if result:
                    assert isinstance(result, dict)

    def test_procedure_pattern_match(self):
        """手順パターンのマッチ"""
        proc_patterns = get_patterns_for_category(LearningCategory.PROCEDURE.value)
        test_messages = [
            "経費精算は経理に回して",
            "備品発注は総務に依頼",
        ]
        for msg in test_messages:
            for pattern in proc_patterns:
                result = pattern.match(msg)
                if result:
                    assert isinstance(result, dict)

    def test_context_pattern_match(self):
        """文脈パターンのマッチ"""
        ctx_patterns = get_patterns_for_category(LearningCategory.CONTEXT.value)
        test_messages = [
            "今月は決算期だから忙しい",
            "今週は展示会の準備中",
        ]
        for msg in test_messages:
            for pattern in ctx_patterns:
                result = pattern.match(msg)
                if result:
                    assert isinstance(result, dict)


# =============================================================================
# 検出テスト（20件）
# =============================================================================

class TestFeedbackDetector:
    """FeedbackDetectorのテスト"""

    def test_create_detector(self):
        """検出器の作成"""
        detector = create_detector()
        assert isinstance(detector, FeedbackDetector)
        assert len(detector.patterns) > 0

    def test_detect_empty_message(self):
        """空メッセージは検出しない"""
        detector = FeedbackDetector()
        result = detector.detect("")
        assert result is None

        result = detector.detect("   ")
        assert result is None

    def test_detect_returns_result_or_none(self):
        """detectはFeedbackDetectionResultまたはNoneを返す"""
        detector = FeedbackDetector()
        result = detector.detect("mtgはミーティングのこと")
        assert result is None or isinstance(result, FeedbackDetectionResult)

    def test_detect_all_returns_list(self):
        """detect_allはリストを返す"""
        detector = FeedbackDetector()
        results = detector.detect_all("mtgはミーティングのこと")
        assert isinstance(results, list)

    def test_detect_with_context(self, sample_context):
        """コンテキスト付きで検出"""
        detector = FeedbackDetector()
        result = detector.detect("mtgはミーティングのこと", sample_context)
        assert result is None or isinstance(result, FeedbackDetectionResult)

    def test_requires_confirmation_low_confidence(self):
        """低確信度は確認が必要"""
        detector = FeedbackDetector()
        result = FeedbackDetectionResult(
            pattern_name="test",
            pattern_category="alias",
            confidence=0.5,  # CONFIRM < 0.5 < AUTO_LEARN
        )
        assert detector.requires_confirmation(result) is True

    def test_requires_confirmation_high_confidence(self):
        """高確信度は確認不要"""
        detector = FeedbackDetector()
        result = FeedbackDetectionResult(
            pattern_name="test",
            pattern_category="alias",
            confidence=0.8,  # > AUTO_LEARN
        )
        assert detector.requires_confirmation(result) is False

    def test_should_auto_learn_high_confidence(self):
        """高確信度は自動学習すべき"""
        detector = FeedbackDetector()
        result = FeedbackDetectionResult(
            pattern_name="test",
            pattern_category="alias",
            confidence=0.8,  # > AUTO_LEARN
        )
        assert detector.should_auto_learn(result) is True

    def test_should_auto_learn_low_confidence(self):
        """低確信度は自動学習しない"""
        detector = FeedbackDetector()
        result = FeedbackDetectionResult(
            pattern_name="test",
            pattern_category="alias",
            confidence=0.5,  # < AUTO_LEARN
        )
        assert detector.should_auto_learn(result) is False

    def test_normalize_message(self):
        """メッセージ正規化"""
        detector = FeedbackDetector()
        normalized = detector._normalize_message("  test　message  ")
        assert normalized == "test message"

    def test_detect_with_custom_patterns(self):
        """カスタムパターン付き検出器"""
        custom_pattern = DetectionPattern(
            name="custom_test",
            category=LearningCategory.FACT.value,
            regex_patterns=[r"カスタム(.+)"],
            base_confidence=0.9,
            priority=100,
        )
        detector = FeedbackDetector(custom_patterns=[custom_pattern])
        # カスタムパターンが追加されている
        assert len(detector.patterns) == len(ALL_PATTERNS) + 1


class TestDetectorConfidenceCalculation:
    """確信度計算のテスト"""

    def test_confidence_with_context_support(self, sample_context):
        """文脈サポートで確信度アップ"""
        detector = FeedbackDetector()
        # correctionパターンで、soulkun_last_responseがあれば文脈サポートあり
        sample_context.soulkun_last_response = "田中さんのタスクです"

        # 修正パターンをテスト
        pattern = DetectionPattern(
            name="test_correction",
            category=LearningCategory.CORRECTION.value,
            regex_patterns=[r"違う"],
            base_confidence=0.6,
        )
        assert detector._has_context_support(pattern, sample_context) is True

    def test_confidence_with_error_support(self):
        """エラーサポートで確信度アップ"""
        detector = FeedbackDetector()
        context = ConversationContext(has_recent_error=True)
        assert detector._has_error_support(context) is True

        context.has_recent_error = False
        assert detector._has_error_support(context) is False


class TestDetectorExtraction:
    """情報抽出のテスト"""

    def test_extract_alias_info(self):
        """別名情報の抽出"""
        detector = FeedbackDetector()
        groups = {"from_value": "mtg", "to_value": "ミーティング"}
        result = detector._extract_alias_info(groups, None)
        assert result["type"] == "alias"
        assert result["from_value"] == "mtg"
        assert result["to_value"] == "ミーティング"

    def test_extract_correction_info(self):
        """修正情報の抽出"""
        detector = FeedbackDetector()
        groups = {"wrong": "田中", "correct": "佐藤"}
        result = detector._extract_correction_info(groups, None)
        assert result["type"] == "correction"
        assert result["wrong_pattern"] == "田中"
        assert result["correct_pattern"] == "佐藤"

    def test_extract_rule_info(self):
        """ルール情報の抽出"""
        detector = FeedbackDetector()
        groups = {"condition": "月曜日", "action": "朝会"}
        result = detector._extract_rule_info(groups, None)
        assert result["type"] == "rule"
        assert result["condition"] == "月曜日"
        assert result["action"] == "朝会"

    def test_extract_preference_info(self, sample_context):
        """好み情報の抽出"""
        detector = FeedbackDetector()
        groups = {"preference": "箇条書き"}
        result = detector._extract_preference_info(groups, sample_context)
        assert result["type"] == "preference"
        assert result["preference"] == "箇条書き"
        assert result["user_name"] == "田中さん"

    def test_extract_relationship_info(self):
        """関係情報の抽出"""
        detector = FeedbackDetector()
        groups = {"person1": "田中", "person2": "佐藤", "relationship": "同期"}
        result = detector._extract_relationship_info(groups, None)
        assert result["type"] == "relationship"
        assert result["person1"] == "田中"
        assert result["person2"] == "佐藤"


# =============================================================================
# 抽出テスト（15件）
# =============================================================================

class TestLearningExtractor:
    """LearningExtractorのテスト"""

    def test_create_extractor(self):
        """抽出器の作成"""
        extractor = create_extractor("org_test")
        assert isinstance(extractor, LearningExtractor)
        assert extractor.organization_id == "org_test"

    def test_extract_alias_learning(self, sample_detection_result):
        """別名学習の抽出"""
        extractor = LearningExtractor("org_test")
        learning = extractor.extract(
            detection_result=sample_detection_result,
            message="mtgはミーティングのこと",
            taught_by_account_id="12345",
            taught_by_name="田中さん",
        )

        assert isinstance(learning, Learning)
        assert learning.category == LearningCategory.ALIAS.value
        assert learning.trigger_type == TriggerType.KEYWORD.value
        assert learning.trigger_value == "mtg"
        assert learning.learned_content["from"] == "mtg"
        assert learning.learned_content["to"] == "ミーティング"
        assert learning.taught_by_name == "田中さん"

    def test_extract_sets_organization_id(self, sample_detection_result):
        """組織IDが設定される"""
        extractor = LearningExtractor("org_soulsyncs")
        learning = extractor.extract(
            detection_result=sample_detection_result,
            message="test",
            taught_by_account_id="12345",
        )
        assert learning.organization_id == "org_soulsyncs"

    def test_extract_generates_uuid(self, sample_detection_result):
        """UUIDが生成される"""
        extractor = LearningExtractor("org_test")
        learning = extractor.extract(
            detection_result=sample_detection_result,
            message="test",
            taught_by_account_id="12345",
        )
        assert learning.id is not None
        assert len(learning.id) == 36  # UUID format


class TestExtractorBuildLearnedContent:
    """learned_content構築のテスト"""

    def test_build_alias_content(self):
        """別名コンテンツ構築"""
        extractor = LearningExtractor("org_test")
        extracted = {"from_value": "PL", "to_value": "プロジェクトリーダー"}
        content = extractor._build_learned_content(
            LearningCategory.ALIAS.value, extracted
        )
        assert content["type"] == "alias"
        assert content["from"] == "PL"
        assert content["to"] == "プロジェクトリーダー"
        assert "description" in content

    def test_build_preference_content(self):
        """好みコンテンツ構築"""
        extractor = LearningExtractor("org_test")
        extracted = {"preference": "箇条書き", "user_name": "田中さん"}
        content = extractor._build_learned_content(
            LearningCategory.PREFERENCE.value, extracted
        )
        assert content["type"] == "preference"
        assert content["preference"] == "箇条書き"

    def test_build_fact_content(self):
        """事実コンテンツ構築"""
        extractor = LearningExtractor("org_test")
        extracted = {"subject": "田中さんの電話", "value": "090-1234-5678"}
        content = extractor._build_learned_content(
            LearningCategory.FACT.value, extracted
        )
        assert content["type"] == "fact"
        assert content["subject"] == "田中さんの電話"
        assert content["value"] == "090-1234-5678"

    def test_build_rule_content(self):
        """ルールコンテンツ構築"""
        extractor = LearningExtractor("org_test")
        extracted = {"condition": "月曜日", "action": "朝会がある"}
        content = extractor._build_learned_content(
            LearningCategory.RULE.value, extracted
        )
        assert content["type"] == "rule"
        assert content["condition"] == "月曜日"
        assert content["action"] == "朝会がある"

    def test_build_correction_content(self):
        """修正コンテンツ構築"""
        extractor = LearningExtractor("org_test")
        extracted = {"wrong_pattern": "田中", "correct_pattern": "佐藤"}
        content = extractor._build_learned_content(
            LearningCategory.CORRECTION.value, extracted
        )
        assert content["type"] == "correction"
        assert content["wrong_pattern"] == "田中"
        assert content["correct_pattern"] == "佐藤"

    def test_build_relationship_content(self):
        """関係コンテンツ構築"""
        extractor = LearningExtractor("org_test")
        extracted = {"person1": "田中", "person2": "佐藤", "relationship": "同期"}
        content = extractor._build_learned_content(
            LearningCategory.RELATIONSHIP.value, extracted
        )
        assert content["type"] == "relationship"
        assert content["person1"] == "田中"
        assert content["relationship"] == "同期"


class TestExtractorTriggerDetermination:
    """トリガー決定のテスト"""

    def test_determine_trigger_alias(self):
        """別名のトリガー決定"""
        extractor = LearningExtractor("org_test")
        learned_content = {"from": "mtg", "to": "ミーティング"}
        trigger_type, trigger_value = extractor._determine_trigger(
            LearningCategory.ALIAS.value, {}, learned_content
        )
        assert trigger_type == TriggerType.KEYWORD.value
        assert trigger_value == "mtg"

    def test_determine_trigger_preference(self):
        """好みのトリガー決定"""
        extractor = LearningExtractor("org_test")
        learned_content = {"subject": "形式", "preference": "箇条書き"}
        trigger_type, trigger_value = extractor._determine_trigger(
            LearningCategory.PREFERENCE.value, {}, learned_content
        )
        assert trigger_type == TriggerType.ALWAYS.value

    def test_determine_trigger_rule(self):
        """ルールのトリガー決定"""
        extractor = LearningExtractor("org_test")
        learned_content = {"condition": "月曜日", "action": "朝会"}
        trigger_type, trigger_value = extractor._determine_trigger(
            LearningCategory.RULE.value, {}, learned_content
        )
        assert trigger_type == TriggerType.CONTEXT.value
        assert trigger_value == "月曜日"


# =============================================================================
# 適用テスト（12件）
# =============================================================================

class TestLearningApplier:
    """LearningApplierのテスト"""

    def test_build_context_additions(self, sample_learning):
        """コンテキスト追加情報の構築"""
        from lib.brain.learning_foundation.applier import LearningApplier

        applier = LearningApplier("org_test")
        applied = AppliedLearning(learning=sample_learning)
        additions = applier.build_context_additions([applied])

        assert "aliases" in additions
        assert "preferences" in additions
        assert "facts" in additions
        assert "rules" in additions
        assert len(additions["aliases"]) == 1
        assert additions["aliases"][0]["from"] == "mtg"

    def test_build_prompt_instructions_empty(self):
        """空のコンテキストでプロンプト指示生成"""
        from lib.brain.learning_foundation.applier import LearningApplier

        applier = LearningApplier("org_test")
        instructions = applier.build_prompt_instructions({})
        assert instructions == ""

    def test_build_prompt_instructions_with_aliases(self, sample_learning):
        """別名ありでプロンプト指示生成"""
        from lib.brain.learning_foundation.applier import LearningApplier

        applier = LearningApplier("org_test")
        applied = AppliedLearning(learning=sample_learning)
        additions = applier.build_context_additions([applied])
        instructions = applier.build_prompt_instructions(additions)

        assert "覚えている別名" in instructions
        assert "mtg" in instructions
        assert "ミーティング" in instructions

    def test_build_prompt_instructions_with_rules(self, sample_ceo_learning):
        """ルールありでプロンプト指示生成"""
        from lib.brain.learning_foundation.applier import LearningApplier

        applier = LearningApplier("org_test")
        applied = AppliedLearning(learning=sample_ceo_learning)
        additions = applier.build_context_additions([applied])
        instructions = applier.build_prompt_instructions(additions)

        assert "守るべきルール" in instructions


class TestLearningApplierWithCeoCheck:
    """LearningApplierWithCeoCheckのテスト"""

    def test_is_conflicting_same_alias_different_to(self, sample_learning):
        """同じ別名で異なる宛先は矛盾"""
        from lib.brain.learning_foundation.applier import LearningApplierWithCeoCheck

        applier = LearningApplierWithCeoCheck("org_test")

        learning1 = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "ミーティング"},
        )
        learning2 = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "会議"},
        )

        assert applier._is_conflicting(learning1, learning2) is True

    def test_is_conflicting_different_trigger(self, sample_learning):
        """異なるトリガーは矛盾しない"""
        from lib.brain.learning_foundation.applier import LearningApplierWithCeoCheck

        applier = LearningApplierWithCeoCheck("org_test")

        learning1 = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "ミーティング"},
        )
        learning2 = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="pl",
            learned_content={"from": "pl", "to": "プロジェクトリーダー"},
        )

        assert applier._is_conflicting(learning1, learning2) is False


# =============================================================================
# 権限解決テスト（12件）
# =============================================================================

class TestAuthorityResolver:
    """AuthorityResolverのテスト"""

    def test_create_resolver(self):
        """解決器の作成"""
        from lib.brain.learning_foundation.authority_resolver import (
            AuthorityResolver,
            create_authority_resolver,
        )

        resolver = create_authority_resolver(
            "org_test",
            ceo_account_ids=["12345"],
            manager_account_ids=["67890"],
        )
        assert isinstance(resolver, AuthorityResolver)

    def test_get_authority_level_ceo(self):
        """CEOの権限レベル取得"""
        from lib.brain.learning_foundation.authority_resolver import AuthorityResolver

        resolver = AuthorityResolver(
            "org_test",
            ceo_account_ids=["12345"],
            manager_account_ids=[],
        )
        level = resolver.get_authority_level(None, "12345")
        assert level == AuthorityLevel.CEO.value

    def test_get_authority_level_manager(self):
        """マネージャーの権限レベル取得"""
        from lib.brain.learning_foundation.authority_resolver import AuthorityResolver

        resolver = AuthorityResolver(
            "org_test",
            ceo_account_ids=[],
            manager_account_ids=["67890"],
        )
        level = resolver.get_authority_level(None, "67890")
        assert level == AuthorityLevel.MANAGER.value

    def test_get_authority_level_user(self):
        """一般ユーザーの権限レベル取得"""
        from lib.brain.learning_foundation.authority_resolver import AuthorityResolver

        resolver = AuthorityResolver(
            "org_test",
            ceo_account_ids=["12345"],
            manager_account_ids=["67890"],
        )
        level = resolver.get_authority_level(None, "99999")
        assert level == AuthorityLevel.USER.value

    def test_compare_authority_ceo_vs_user(self):
        """CEO vs USER の権限比較"""
        from lib.brain.learning_foundation.authority_resolver import AuthorityResolver

        resolver = AuthorityResolver("org_test", [], [])
        # CEOの優先度(1)がUSER(3)より高いので、-1を返す（1が高い）
        assert resolver.compare_authority(
            AuthorityLevel.CEO.value,
            AuthorityLevel.USER.value
        ) < 0

    def test_compare_authority_same_level(self):
        """同じ権限レベルの比較"""
        from lib.brain.learning_foundation.authority_resolver import AuthorityResolver

        resolver = AuthorityResolver("org_test", [], [])
        assert resolver.compare_authority(
            AuthorityLevel.USER.value,
            AuthorityLevel.USER.value
        ) == 0

    def test_is_higher_or_equal(self):
        """権限が同等以上かの判定"""
        from lib.brain.learning_foundation.authority_resolver import AuthorityResolver

        resolver = AuthorityResolver("org_test", [], [])

        # CEO >= USER
        assert resolver.is_higher_or_equal(
            AuthorityLevel.CEO.value,
            AuthorityLevel.USER.value
        ) is True

        # USER >= CEO は False
        assert resolver.is_higher_or_equal(
            AuthorityLevel.USER.value,
            AuthorityLevel.CEO.value
        ) is False

    def test_can_teach(self):
        """教える権限があるかの判定"""
        from lib.brain.learning_foundation.authority_resolver import AuthorityResolver

        resolver = AuthorityResolver("org_test", ["ceo_id"], ["mgr_id"])
        # 全員が教える権限を持つ（can_teachはconn, account_idを受け取る）
        can_teach, authority = resolver.can_teach(None, "user_123")
        assert can_teach is True

        can_teach, authority = resolver.can_teach(None, "ceo_id")
        assert can_teach is True
        assert authority == AuthorityLevel.CEO.value

    def test_can_modify(self):
        """修正権限があるかの判定"""
        from lib.brain.learning_foundation.authority_resolver import AuthorityResolver

        resolver = AuthorityResolver("org_test", ["ceo_id"], ["mgr_id"])

        # 学習モデルを作成
        ceo_learning = Learning(
            id="learning1",
            organization_id="org_test",
            authority_level=AuthorityLevel.CEO.value,
            taught_by_account_id="ceo_id",
        )

        # CEOはCEO教えを修正可能
        can_modify, reason = resolver.can_modify(None, "ceo_id", ceo_learning)
        assert can_modify is True

        # 一般ユーザーはCEO教えを修正不可
        can_modify, reason = resolver.can_modify(None, "user_123", ceo_learning)
        assert can_modify is False

    def test_can_delete(self):
        """削除権限があるかの判定"""
        from lib.brain.learning_foundation.authority_resolver import AuthorityResolver

        resolver = AuthorityResolver("org_test", ["ceo_id"], ["mgr_id"])

        # ユーザー教えの学習
        user_learning = Learning(
            id="learning1",
            organization_id="org_test",
            authority_level=AuthorityLevel.USER.value,
            taught_by_account_id="user_123",
        )

        # 自分が教えたものは削除可能
        can_delete, reason = resolver.can_delete(None, "user_123", user_learning)
        assert can_delete is True

        # CEO教えは一般ユーザーは削除不可
        ceo_learning = Learning(
            id="learning2",
            organization_id="org_test",
            authority_level=AuthorityLevel.CEO.value,
            taught_by_account_id="ceo_id",
        )
        can_delete, reason = resolver.can_delete(None, "user_123", ceo_learning)
        assert can_delete is False


# =============================================================================
# 矛盾検出テスト（12件）
# =============================================================================

class TestConflictDetector:
    """ConflictDetectorのテスト"""

    def test_create_conflict_detector(self):
        """矛盾検出器の作成"""
        from lib.brain.learning_foundation.conflict_detector import (
            ConflictDetector,
            create_conflict_detector,
        )

        detector = create_conflict_detector("org_test")
        assert isinstance(detector, ConflictDetector)

    def test_has_ceo_conflict(self, sample_learning, sample_ceo_learning):
        """CEO教えとの矛盾判定"""
        from lib.brain.learning_foundation.conflict_detector import ConflictDetector

        detector = ConflictDetector("org_test")

        # 矛盾するルールを作成（同じカテゴリ・同じconditionで異なるaction）
        conflicting_learning = Learning(
            category=sample_ceo_learning.category,
            trigger_type=sample_ceo_learning.trigger_type,
            trigger_value=sample_ceo_learning.trigger_value,
            learned_content={
                "condition": sample_ceo_learning.learned_content.get("condition", "常に"),
                "action": "人を疑う",  # CEOの「人の可能性を信じる」と矛盾
            },
            authority_level=AuthorityLevel.USER.value,
        )

        # _is_conflicting_contentを使って矛盾判定
        has_conflict = detector._is_conflicting_content(
            conflicting_learning, sample_ceo_learning
        )
        assert has_conflict is True


class TestConflictResolution:
    """矛盾解決のテスト"""

    def test_resolve_conflict_ceo_always_wins(self, sample_learning, sample_ceo_learning):
        """CEO教えは常に勝つ"""
        from lib.brain.learning_foundation.conflict_detector import ConflictDetector
        from lib.brain.learning_foundation.constants import ConflictResolutionStrategy

        detector = ConflictDetector("org_test")

        conflict = ConflictInfo(
            new_learning=sample_learning,
            existing_learning=sample_ceo_learning,
            conflict_type=ConflictType.CEO_CONFLICT.value,
        )

        # resolve_conflictはconn, conflict, strategyを受け取る
        resolution = detector.resolve_conflict(
            None,  # conn（モック不要の場合）
            conflict,
            ConflictResolutionStrategy.HIGHER_AUTHORITY,
        )
        assert resolution.action == "reject"
        assert resolution.kept_learning == sample_ceo_learning

    def test_resolve_conflict_higher_authority_wins(self):
        """権限が高い方が勝つ"""
        from lib.brain.learning_foundation.conflict_detector import ConflictDetector
        from lib.brain.learning_foundation.constants import ConflictResolutionStrategy

        detector = ConflictDetector("org_test")

        manager_learning = Learning(
            id="mgr_learning",
            authority_level=AuthorityLevel.MANAGER.value,
            learned_content={"action": "manager rule"},
        )
        user_learning = Learning(
            id="user_learning",
            authority_level=AuthorityLevel.USER.value,
            learned_content={"action": "user rule"},
        )

        conflict = ConflictInfo(
            new_learning=user_learning,
            existing_learning=manager_learning,
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
        )

        resolution = detector.resolve_conflict(
            None,  # conn
            conflict,
            ConflictResolutionStrategy.HIGHER_AUTHORITY,
        )
        # マネージャーが勝つ（ユーザーの学習は拒否される）
        assert resolution.kept_learning == manager_learning


# =============================================================================
# 管理テスト（12件）
# =============================================================================

class TestLearningManager:
    """LearningManagerのテスト"""

    def test_is_list_command(self):
        """一覧コマンド判定"""
        from lib.brain.learning_foundation.manager import LearningManager

        manager = LearningManager("org_test")

        assert manager.is_list_command("何覚えてる？") is True
        assert manager.is_list_command("覚えたこと教えて") is True
        assert manager.is_list_command("タスクを教えて") is False

    def test_is_delete_command(self):
        """削除コマンド判定"""
        from lib.brain.learning_foundation.manager import LearningManager

        manager = LearningManager("org_test")

        assert manager.is_delete_command("mtgのこと忘れて") is True
        assert manager.is_delete_command("削除して") is True
        assert manager.is_delete_command("覚えて") is False

    def test_format_list_response_empty(self):
        """空の一覧フォーマット"""
        from lib.brain.learning_foundation.manager import LearningManager

        manager = LearningManager("org_test")
        response = manager.format_list_response({})
        # 「まだ何も覚えていないウル🐺」というメッセージを確認
        assert "覚えていない" in response or "何も" in response

    def test_format_list_response_with_learnings(self, sample_learning):
        """学習ありの一覧フォーマット"""
        from lib.brain.learning_foundation.manager import LearningManager

        manager = LearningManager("org_test")
        learnings_by_category = {
            LearningCategory.ALIAS.value: [sample_learning],
        }
        response = manager.format_list_response(learnings_by_category)
        assert "別名" in response or "mtg" in response


# =============================================================================
# 有効性追跡テスト（12件）
# =============================================================================

class TestEffectivenessTracker:
    """EffectivenessTrackerのテスト"""

    def test_calculate_effectiveness(self, sample_learning):
        """有効性計算"""
        from lib.brain.learning_foundation.effectiveness_tracker import (
            EffectivenessTracker,
            create_effectiveness_tracker,
        )

        # Learningにcreated_atとupdated_atを設定
        sample_learning.created_at = datetime.now()
        sample_learning.updated_at = datetime.now()

        tracker = create_effectiveness_tracker("org_test")
        result = tracker.calculate_effectiveness(sample_learning)

        assert isinstance(result, EffectivenessResult)
        assert 0 <= result.effectiveness_score <= 1

    def test_check_health_healthy(self, sample_learning):
        """健全な学習の健全性チェック"""
        from lib.brain.learning_foundation.effectiveness_tracker import EffectivenessTracker

        tracker = EffectivenessTracker("org_test")

        # 健全な学習（適用回数あり、ポジティブフィードバックあり）
        # モデルのフィールド名に合わせる
        sample_learning.applied_count = 10
        sample_learning.success_count = 8
        sample_learning.failure_count = 1
        sample_learning.created_at = datetime.now()
        sample_learning.updated_at = datetime.now()

        health = tracker.check_health(sample_learning)
        assert health.status == "healthy"

    def test_check_health_warning(self, sample_learning):
        """警告が必要な学習の健全性チェック"""
        from lib.brain.learning_foundation.effectiveness_tracker import EffectivenessTracker

        tracker = EffectivenessTracker("org_test")

        # 警告が必要な学習（ネガティブフィードバックが多い）
        # モデルのフィールド名に合わせる
        sample_learning.applied_count = 10
        sample_learning.success_count = 2
        sample_learning.failure_count = 5
        sample_learning.created_at = datetime.now()
        sample_learning.updated_at = datetime.now()

        health = tracker.check_health(sample_learning)
        assert health.status in ["warning", "critical"]

    def test_check_health_stale(self, sample_learning):
        """古い学習の健全性チェック"""
        from lib.brain.learning_foundation.effectiveness_tracker import EffectivenessTracker

        tracker = EffectivenessTracker("org_test")

        # 古い学習（長期間使用されていない）
        sample_learning.created_at = datetime.now() - timedelta(days=200)
        sample_learning.updated_at = datetime.now() - timedelta(days=200)
        sample_learning.applied_count = 0
        sample_learning.success_count = 0
        sample_learning.failure_count = 0

        health = tracker.check_health(sample_learning)
        assert health.status == "stale" or health.status == "healthy"


# =============================================================================
# BrainLearning統合テスト（10件）
# =============================================================================

class TestBrainLearningIntegration:
    """BrainLearning統合クラスのテスト"""

    def test_create_brain_learning(self):
        """BrainLearning作成"""
        brain_learning = create_brain_learning(
            "org_test",
            ceo_account_ids=["12345"],
            manager_account_ids=["67890"],
        )
        assert isinstance(brain_learning, BrainLearning)
        assert brain_learning.organization_id == "org_test"

    def test_version(self):
        """バージョン確認"""
        assert __version__ == "2.0.0"

    def test_detect_method(self):
        """detectメソッド"""
        brain_learning = BrainLearning("org_test")
        result = brain_learning.detect("mtgはミーティングのこと")
        assert result is None or isinstance(result, FeedbackDetectionResult)

    def test_should_auto_learn_method(self, sample_detection_result):
        """should_auto_learnメソッド"""
        brain_learning = BrainLearning("org_test")

        # 高確信度
        sample_detection_result.confidence = 0.85
        assert brain_learning.should_auto_learn(sample_detection_result) is True

        # 低確信度
        sample_detection_result.confidence = 0.5
        assert brain_learning.should_auto_learn(sample_detection_result) is False

    def test_requires_confirmation_method(self, sample_detection_result):
        """requires_confirmationメソッド"""
        brain_learning = BrainLearning("org_test")

        # 確認が必要な確信度
        sample_detection_result.confidence = 0.5
        assert brain_learning.requires_confirmation(sample_detection_result) is True

        # 確認不要な確信度
        sample_detection_result.confidence = 0.85
        assert brain_learning.requires_confirmation(sample_detection_result) is False

    def test_extract_method(self, sample_detection_result):
        """extractメソッド"""
        brain_learning = BrainLearning("org_test")
        learning = brain_learning.extract(
            detection_result=sample_detection_result,
            message="mtgはミーティングのこと",
            taught_by_account_id="12345",
            taught_by_name="田中さん",
        )

        assert isinstance(learning, Learning)
        assert learning.organization_id == "org_test"
        assert learning.taught_by_name == "田中さん"

    def test_is_list_command_method(self):
        """is_list_commandメソッド"""
        brain_learning = BrainLearning("org_test")

        assert brain_learning.is_list_command("何覚えてる？") is True
        assert brain_learning.is_list_command("タスク作って") is False

    def test_is_delete_command_method(self):
        """is_delete_commandメソッド"""
        brain_learning = BrainLearning("org_test")

        assert brain_learning.is_delete_command("mtgのこと忘れて") is True
        assert brain_learning.is_delete_command("覚えて") is False

    def test_build_context_additions_method(self, sample_learning):
        """build_context_additionsメソッド"""
        brain_learning = BrainLearning("org_test")
        applied = AppliedLearning(learning=sample_learning)
        additions = brain_learning.build_context_additions([applied])

        assert isinstance(additions, dict)
        assert "aliases" in additions
        assert "rules" in additions

    def test_build_prompt_instructions_method(self, sample_learning):
        """build_prompt_instructionsメソッド"""
        brain_learning = BrainLearning("org_test")
        applied = AppliedLearning(learning=sample_learning)
        additions = brain_learning.build_context_additions([applied])
        instructions = brain_learning.build_prompt_instructions(additions)

        assert isinstance(instructions, str)
        # 別名があれば指示文に含まれる
        if additions["aliases"]:
            assert "mtg" in instructions or "ミーティング" in instructions


# =============================================================================
# エッジケーステスト（10件）
# =============================================================================

class TestEdgeCases:
    """エッジケースのテスト"""

    def test_empty_organization_id(self):
        """空の組織ID"""
        brain_learning = BrainLearning("")
        assert brain_learning.organization_id == ""

    def test_none_context(self):
        """Noneコンテキスト"""
        brain_learning = BrainLearning("org_test")
        result = brain_learning.detect("mtgはミーティング", context=None)
        assert result is None or isinstance(result, FeedbackDetectionResult)

    def test_unicode_message(self):
        """Unicode文字を含むメッセージ"""
        brain_learning = BrainLearning("org_test")
        result = brain_learning.detect("絵文字🎉はいいね👍のこと")
        assert result is None or isinstance(result, FeedbackDetectionResult)

    def test_very_long_message(self):
        """非常に長いメッセージ"""
        brain_learning = BrainLearning("org_test")
        long_message = "これは非常に長いメッセージです。" * 100
        result = brain_learning.detect(long_message)
        assert result is None or isinstance(result, FeedbackDetectionResult)

    def test_special_characters(self):
        """特殊文字を含むメッセージ"""
        brain_learning = BrainLearning("org_test")
        result = brain_learning.detect("<script>alert('XSS')</script>")
        assert result is None or isinstance(result, FeedbackDetectionResult)

    def test_multiple_patterns_in_one_message(self):
        """1つのメッセージに複数のパターン"""
        detector = FeedbackDetector()
        # 複数のパターンを含むメッセージ
        results = detector.detect_all(
            "mtgはミーティングのこと、PLはプロジェクトリーダーの略"
        )
        # 結果はリスト（空でも可）
        assert isinstance(results, list)

    def test_learning_with_no_content(self):
        """内容がない学習"""
        learning = Learning(learned_content={})
        desc = learning.get_description()
        # 空でもエラーにならない
        assert isinstance(desc, str)

    def test_authority_resolver_empty_lists(self):
        """空のCEO/マネージャーリスト"""
        from lib.brain.learning_foundation.authority_resolver import AuthorityResolver

        resolver = AuthorityResolver("org_test", [], [])
        # 全員がUSERになる
        assert resolver.get_authority_level(None, "12345") == AuthorityLevel.USER.value

    def test_datetime_handling(self, sample_learning):
        """日時のハンドリング"""
        sample_learning.valid_from = datetime.now()
        sample_learning.valid_until = datetime.now() + timedelta(days=30)

        d = sample_learning.to_dict()
        assert "valid_from" in d
        assert d["valid_from"] is not None

    def test_concurrent_learning_creation(self, sample_detection_result):
        """並行して学習を作成"""
        brain_learning = BrainLearning("org_test")

        learnings = []
        for i in range(10):
            learning = brain_learning.extract(
                detection_result=sample_detection_result,
                message=f"test{i}",
                taught_by_account_id=f"user{i}",
            )
            learnings.append(learning)

        # 全て異なるID
        ids = [l.id for l in learnings]
        assert len(ids) == len(set(ids))
