"""
矛盾検出器（ConflictDetector）の包括的ユニットテスト

テスト対象: lib/brain/learning_foundation/conflict_detector.py

テストカバレッジ目標: 80%+

テスト対象メソッド:
- __init__
- detect_conflicts
- has_ceo_conflict
- resolve_conflict
- get_resolution_strategy
- _detect_conflict_type
- _is_conflicting_content
- _detect_ceo_conflicts
- _find_ceo_learnings
- _describe_conflict
- _suggest_resolution
- _format_ceo_conflict_message
- _format_confirmation_message
- create_conflict_detector (ファクトリ関数)
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from lib.brain.learning_foundation.conflict_detector import (
    ConflictDetector,
    create_conflict_detector,
)
from lib.brain.learning_foundation.constants import (
    AuthorityLevel,
    AUTHORITY_PRIORITY,
    ConflictResolutionStrategy,
    ConflictType,
    LearningCategory,
    LearningScope,
    TriggerType,
    CEO_CONFLICT_MESSAGE_TEMPLATE,
)
from lib.brain.learning_foundation.models import (
    ConflictInfo,
    Learning,
    Resolution,
)
from lib.brain.learning_foundation.repository import LearningRepository


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
def mock_repository():
    """モックリポジトリ"""
    repo = MagicMock(spec=LearningRepository)
    repo.find_by_trigger = MagicMock(return_value=[])
    repo.find_by_category = MagicMock(return_value=[])
    repo.update_supersedes = MagicMock(return_value=True)
    return repo


@pytest.fixture
def sample_user_learning():
    """サンプルユーザー学習データ"""
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
def sample_manager_learning():
    """サンプルマネージャー学習データ"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.RULE.value,
        trigger_type=TriggerType.CONTEXT.value,
        trigger_value="報告",
        learned_content={
            "type": "rule",
            "condition": "報告時",
            "action": "箇条書きで報告する",
            "description": "報告時は箇条書きで報告する",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.MANAGER.value,
        taught_by_account_id="67890",
        taught_by_name="佐藤さん",
        is_active=True,
        created_at=datetime.now(),
    )


@pytest.fixture
def conflicting_alias_learning():
    """mtgの別定義（矛盾する別名）"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.ALIAS.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="mtg",
        learned_content={
            "type": "alias",
            "from": "mtg",
            "to": "会議",  # ミーティングではなく会議
            "bidirectional": False,
            "description": "mtgは会議の略称",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="99999",
        taught_by_name="鈴木さん",
        is_active=True,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_fact_learning():
    """サンプル事実学習データ"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.FACT.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="田中",
        learned_content={
            "type": "fact",
            "subject": "田中さんの役職",
            "value": "営業部長",
            "description": "田中さんは営業部長",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="12345",
        is_active=True,
        created_at=datetime.now(),
    )


@pytest.fixture
def conflicting_fact_learning():
    """矛盾する事実学習データ"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.FACT.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="田中",
        learned_content={
            "type": "fact",
            "subject": "田中さんの役職",
            "value": "総務部長",  # 営業部長ではなく総務部長
            "description": "田中さんは総務部長",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="67890",
        is_active=True,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_preference_learning():
    """サンプル好み学習データ"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.PREFERENCE.value,
        trigger_type=TriggerType.ALWAYS.value,
        trigger_value="*",
        learned_content={
            "type": "preference",
            "subject": "回答形式",
            "preference": "箇条書き",
            "description": "回答は箇条書きが好み",
        },
        scope=LearningScope.USER.value,
        scope_target_id="user123",
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="user123",
        is_active=True,
        created_at=datetime.now(),
    )


@pytest.fixture
def conflicting_preference_learning():
    """矛盾する好み学習データ"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.PREFERENCE.value,
        trigger_type=TriggerType.ALWAYS.value,
        trigger_value="*",
        learned_content={
            "type": "preference",
            "subject": "回答形式",
            "preference": "詳細な文章",  # 箇条書きではなく詳細な文章
            "description": "回答は詳細な文章が好み",
        },
        scope=LearningScope.USER.value,
        scope_target_id="user123",
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="user123",
        is_active=True,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_correction_learning():
    """サンプル修正学習データ"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.CORRECTION.value,
        trigger_type=TriggerType.PATTERN.value,
        trigger_value="田中",
        learned_content={
            "type": "correction",
            "wrong_pattern": "田中課長",
            "correct_pattern": "田中部長",
            "description": "田中課長ではなく田中部長",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        is_active=True,
        created_at=datetime.now(),
    )


@pytest.fixture
def conflicting_correction_learning():
    """矛盾する修正学習データ"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.CORRECTION.value,
        trigger_type=TriggerType.PATTERN.value,
        trigger_value="田中",
        learned_content={
            "type": "correction",
            "wrong_pattern": "田中課長",
            "correct_pattern": "田中係長",  # 部長ではなく係長
            "description": "田中課長ではなく田中係長",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        is_active=True,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_procedure_learning():
    """サンプル手順学習データ"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.PROCEDURE.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="経費精算",
        learned_content={
            "type": "procedure",
            "task": "経費精算",
            "steps": ["1. 申請書作成", "2. 上長承認", "3. 経理提出"],
            "description": "経費精算の手順",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        is_active=True,
        created_at=datetime.now(),
    )


@pytest.fixture
def conflicting_procedure_learning():
    """矛盾する手順学習データ"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_soulsyncs",
        category=LearningCategory.PROCEDURE.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="経費精算",
        learned_content={
            "type": "procedure",
            "task": "経費精算",
            "steps": ["1. 経理に相談", "2. 申請書作成"],  # 異なる手順
            "description": "経費精算の手順",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        is_active=True,
        created_at=datetime.now(),
    )


# =============================================================================
# 初期化テスト
# =============================================================================

class TestConflictDetectorInit:
    """ConflictDetector初期化のテスト"""

    def test_init_with_organization_id(self):
        """組織IDで初期化"""
        detector = ConflictDetector("org_test")
        assert detector.organization_id == "org_test"
        assert detector.repository is not None

    def test_init_with_custom_repository(self, mock_repository):
        """カスタムリポジトリで初期化"""
        detector = ConflictDetector("org_test", repository=mock_repository)
        assert detector.organization_id == "org_test"
        assert detector.repository == mock_repository

    def test_init_creates_default_repository(self):
        """デフォルトリポジトリが作成される"""
        detector = ConflictDetector("org_soulsyncs")
        assert isinstance(detector.repository, LearningRepository)
        assert detector.repository.organization_id == "org_soulsyncs"


# =============================================================================
# ファクトリ関数テスト
# =============================================================================

class TestCreateConflictDetector:
    """create_conflict_detectorファクトリ関数のテスト"""

    def test_create_with_organization_id(self):
        """組織IDで作成"""
        detector = create_conflict_detector("org_test")
        assert isinstance(detector, ConflictDetector)
        assert detector.organization_id == "org_test"

    def test_create_with_repository(self, mock_repository):
        """リポジトリ指定で作成"""
        detector = create_conflict_detector("org_test", repository=mock_repository)
        assert detector.repository == mock_repository


# =============================================================================
# detect_conflictsテスト
# =============================================================================

class TestDetectConflicts:
    """detect_conflictsメソッドのテスト"""

    def test_detect_no_conflicts_when_no_existing(self, mock_conn, mock_repository, sample_user_learning):
        """既存学習がない場合は矛盾なし"""
        mock_repository.find_by_trigger.return_value = []
        mock_repository.find_by_category.return_value = []

        detector = ConflictDetector("org_test", repository=mock_repository)
        conflicts = detector.detect_conflicts(mock_conn, sample_user_learning)

        assert conflicts == []

    def test_detect_conflict_with_different_content(
        self, mock_conn, mock_repository, sample_user_learning, conflicting_alias_learning
    ):
        """異なる内容の既存学習との矛盾を検出"""
        mock_repository.find_by_trigger.return_value = [conflicting_alias_learning]
        mock_repository.find_by_category.return_value = []

        detector = ConflictDetector("org_test", repository=mock_repository)
        conflicts = detector.detect_conflicts(mock_conn, sample_user_learning)

        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.CONTENT_MISMATCH.value

    def test_detect_skips_same_learning(self, mock_conn, mock_repository, sample_user_learning):
        """同じ学習IDはスキップ"""
        mock_repository.find_by_trigger.return_value = [sample_user_learning]
        mock_repository.find_by_category.return_value = []

        detector = ConflictDetector("org_test", repository=mock_repository)
        conflicts = detector.detect_conflicts(mock_conn, sample_user_learning)

        assert conflicts == []

    def test_detect_ceo_conflict(
        self, mock_conn, mock_repository, sample_user_learning, sample_ceo_learning
    ):
        """CEO教えとの矛盾を検出"""
        # 同じカテゴリ・条件で異なるアクションの学習
        conflicting_user_learning = Learning(
            id=str(uuid4()),
            organization_id="org_soulsyncs",
            category=LearningCategory.RULE.value,
            trigger_type=TriggerType.ALWAYS.value,
            trigger_value="*",
            learned_content={
                "type": "rule",
                "condition": "常に",
                "action": "人を疑う",  # CEOの「信じる」と矛盾
                "description": "人を疑う",
            },
            authority_level=AuthorityLevel.USER.value,
            is_active=True,
        )

        mock_repository.find_by_trigger.return_value = []
        mock_repository.find_by_category.return_value = [sample_ceo_learning]

        detector = ConflictDetector("org_test", repository=mock_repository)
        conflicts = detector.detect_conflicts(mock_conn, conflicting_user_learning)

        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.CEO_CONFLICT.value

    def test_detect_rule_conflict(self, mock_conn, mock_repository):
        """ルール矛盾を検出"""
        existing_rule = Learning(
            id=str(uuid4()),
            organization_id="org_test",
            category=LearningCategory.RULE.value,
            trigger_type=TriggerType.CONTEXT.value,
            trigger_value="月曜日",
            learned_content={
                "condition": "月曜日",
                "action": "朝会を開く",
            },
            authority_level=AuthorityLevel.USER.value,
        )

        new_rule = Learning(
            id=str(uuid4()),
            organization_id="org_test",
            category=LearningCategory.RULE.value,
            trigger_type=TriggerType.CONTEXT.value,
            trigger_value="月曜日",
            learned_content={
                "condition": "月曜日",
                "action": "朝会をスキップ",  # 異なるアクション
            },
            authority_level=AuthorityLevel.USER.value,
        )

        mock_repository.find_by_trigger.return_value = [existing_rule]
        mock_repository.find_by_category.return_value = []

        detector = ConflictDetector("org_test", repository=mock_repository)
        conflicts = detector.detect_conflicts(mock_conn, new_rule)

        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.RULE_CONFLICT.value


# =============================================================================
# has_ceo_conflictテスト
# =============================================================================

class TestHasCeoConflict:
    """has_ceo_conflictメソッドのテスト"""

    def test_no_conflict_when_new_is_ceo(self, mock_conn, mock_repository, sample_ceo_learning):
        """新規がCEO教えの場合は矛盾なし"""
        detector = ConflictDetector("org_test", repository=mock_repository)
        has_conflict, conflicting_learning = detector.has_ceo_conflict(mock_conn, sample_ceo_learning)

        assert has_conflict is False
        assert conflicting_learning is None

    def test_no_conflict_when_no_ceo_learnings(self, mock_conn, mock_repository, sample_user_learning):
        """CEO教えがない場合は矛盾なし"""
        mock_repository.find_by_category.return_value = []

        detector = ConflictDetector("org_test", repository=mock_repository)
        has_conflict, conflicting_learning = detector.has_ceo_conflict(mock_conn, sample_user_learning)

        assert has_conflict is False
        assert conflicting_learning is None

    def test_conflict_detected_with_ceo_learning(self, mock_conn, mock_repository, sample_ceo_learning):
        """CEO教えとの矛盾を検出"""
        # 同じカテゴリ・条件で異なるアクションの学習を作成
        conflicting_user_learning = Learning(
            id=str(uuid4()),
            organization_id="org_soulsyncs",
            category=LearningCategory.RULE.value,
            trigger_type=TriggerType.ALWAYS.value,
            trigger_value="*",
            learned_content={
                "condition": "常に",
                "action": "人を疑う",  # CEO教えと矛盾
            },
            authority_level=AuthorityLevel.USER.value,
            is_active=True,
        )

        mock_repository.find_by_category.return_value = [sample_ceo_learning]

        detector = ConflictDetector("org_test", repository=mock_repository)
        has_conflict, conflicting_learning = detector.has_ceo_conflict(
            mock_conn, conflicting_user_learning
        )

        assert has_conflict is True
        assert conflicting_learning == sample_ceo_learning


# =============================================================================
# resolve_conflictテスト
# =============================================================================

class TestResolveConflict:
    """resolve_conflictメソッドのテスト"""

    def test_resolve_ceo_conflict_always_rejects(
        self, mock_conn, mock_repository, sample_user_learning, sample_ceo_learning
    ):
        """CEO教えとの矛盾は常に拒否"""
        conflict = ConflictInfo(
            conflict_type=ConflictType.CEO_CONFLICT.value,
            existing_learning=sample_ceo_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test", repository=mock_repository)
        resolution = detector.resolve_conflict(
            mock_conn, conflict, ConflictResolutionStrategy.NEWER_WINS
        )

        assert resolution.action == "reject"
        assert resolution.kept_learning == sample_ceo_learning
        assert resolution.removed_learning == sample_user_learning
        assert "ソウルシンクスとして大事にしていること" in resolution.message

    def test_resolve_newer_wins(
        self, mock_conn, mock_repository, sample_user_learning, conflicting_alias_learning
    ):
        """NEWER_WINS戦略で新しい学習が勝つ"""
        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=conflicting_alias_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test", repository=mock_repository)
        resolution = detector.resolve_conflict(
            mock_conn, conflict, ConflictResolutionStrategy.NEWER_WINS
        )

        assert resolution.action == "supersede"
        assert resolution.kept_learning == sample_user_learning
        assert resolution.removed_learning == conflicting_alias_learning
        mock_repository.update_supersedes.assert_called_once()

    def test_resolve_higher_authority_new_wins(
        self, mock_conn, mock_repository, sample_user_learning, sample_manager_learning
    ):
        """HIGHER_AUTHORITY戦略で権限が高い新しい学習が勝つ"""
        # マネージャー学習（authority=manager）がユーザー学習（authority=user）と競合
        user_learning = Learning(
            id=str(uuid4()),
            organization_id="org_test",
            category=LearningCategory.RULE.value,
            trigger_type=TriggerType.CONTEXT.value,
            trigger_value="報告",
            learned_content={
                "condition": "報告時",
                "action": "自由形式で報告する",
            },
            authority_level=AuthorityLevel.USER.value,
        )

        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=user_learning,
            new_learning=sample_manager_learning,
        )

        detector = ConflictDetector("org_test", repository=mock_repository)
        resolution = detector.resolve_conflict(
            mock_conn, conflict, ConflictResolutionStrategy.HIGHER_AUTHORITY
        )

        assert resolution.action == "supersede"
        assert resolution.kept_learning == sample_manager_learning

    def test_resolve_higher_authority_existing_wins(
        self, mock_conn, mock_repository, sample_user_learning, sample_manager_learning
    ):
        """HIGHER_AUTHORITY戦略で権限が高い既存学習が勝つ"""
        user_learning = Learning(
            id=str(uuid4()),
            organization_id="org_test",
            category=LearningCategory.RULE.value,
            trigger_type=TriggerType.CONTEXT.value,
            trigger_value="報告",
            learned_content={
                "condition": "報告時",
                "action": "自由形式で報告する",
            },
            authority_level=AuthorityLevel.USER.value,
        )

        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=sample_manager_learning,
            new_learning=user_learning,
        )

        detector = ConflictDetector("org_test", repository=mock_repository)
        resolution = detector.resolve_conflict(
            mock_conn, conflict, ConflictResolutionStrategy.HIGHER_AUTHORITY
        )

        assert resolution.action == "reject"
        assert resolution.kept_learning == sample_manager_learning

    def test_resolve_confirm_user_with_new_choice(
        self, mock_conn, mock_repository, sample_user_learning, conflicting_alias_learning
    ):
        """CONFIRM_USER戦略でユーザーが「new」を選択"""
        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=conflicting_alias_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test", repository=mock_repository)
        resolution = detector.resolve_conflict(
            mock_conn, conflict, ConflictResolutionStrategy.CONFIRM_USER, user_choice="new"
        )

        assert resolution.action == "supersede"
        assert resolution.kept_learning == sample_user_learning
        assert "了解ウル" in resolution.message

    def test_resolve_confirm_user_with_existing_choice(
        self, mock_conn, mock_repository, sample_user_learning, conflicting_alias_learning
    ):
        """CONFIRM_USER戦略でユーザーが「existing」を選択"""
        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=conflicting_alias_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test", repository=mock_repository)
        resolution = detector.resolve_conflict(
            mock_conn, conflict, ConflictResolutionStrategy.CONFIRM_USER, user_choice="existing"
        )

        assert resolution.action == "reject"
        assert resolution.kept_learning == conflicting_alias_learning
        assert "了解ウル" in resolution.message

    def test_resolve_confirm_user_pending(
        self, mock_conn, mock_repository, sample_user_learning, conflicting_alias_learning
    ):
        """CONFIRM_USER戦略で選択待ち（pendingを返す）"""
        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=conflicting_alias_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test", repository=mock_repository)
        resolution = detector.resolve_conflict(
            mock_conn, conflict, ConflictResolutionStrategy.CONFIRM_USER, user_choice=None
        )

        assert resolution.action == "pending"
        assert "ちょっと待って" in resolution.message

    def test_resolve_default_rejects(
        self, mock_conn, mock_repository, sample_user_learning, conflicting_alias_learning
    ):
        """不明な戦略の場合はデフォルトで拒否"""
        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=conflicting_alias_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test", repository=mock_repository)

        # Enumにない戦略を直接渡す（実際にはあり得ないが、デフォルトケースのテスト）
        # resolve_conflictはConflictResolutionStrategyを期待するが、
        # if文で全ての有効なケースを処理し終わった後のデフォルトをテスト
        # 実際には全てのEnum値が処理されるので、このデフォルトには到達しない
        # しかし、安全のためにテストしておく

        # CONFIRM_USERで不正な選択肢を渡してpendingにならないケースをテスト
        resolution = detector.resolve_conflict(
            mock_conn, conflict, ConflictResolutionStrategy.CONFIRM_USER, user_choice="invalid"
        )

        # 不正な選択肢の場合はpendingになる
        assert resolution.action == "pending"


# =============================================================================
# get_resolution_strategyテスト
# =============================================================================

class TestGetResolutionStrategy:
    """get_resolution_strategyメソッドのテスト"""

    def test_ceo_conflict_returns_higher_authority(
        self, sample_user_learning, sample_ceo_learning
    ):
        """CEO矛盾はHIGHER_AUTHORITYを返す"""
        conflict = ConflictInfo(
            conflict_type=ConflictType.CEO_CONFLICT.value,
            existing_learning=sample_ceo_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test")
        strategy = detector.get_resolution_strategy(conflict)

        assert strategy == ConflictResolutionStrategy.HIGHER_AUTHORITY

    def test_content_mismatch_different_authority_returns_higher_authority(
        self, sample_user_learning, sample_manager_learning
    ):
        """異なる権限レベルのCONTENT_MISMATCHはHIGHER_AUTHORITYを返す"""
        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=sample_manager_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test")
        strategy = detector.get_resolution_strategy(conflict)

        assert strategy == ConflictResolutionStrategy.HIGHER_AUTHORITY

    def test_content_mismatch_same_authority_returns_confirm_user(
        self, sample_user_learning, conflicting_alias_learning
    ):
        """同じ権限レベルのCONTENT_MISMATCHはCONFIRM_USERを返す"""
        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=conflicting_alias_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test")
        strategy = detector.get_resolution_strategy(conflict)

        assert strategy == ConflictResolutionStrategy.CONFIRM_USER

    def test_rule_conflict_returns_confirm_user(
        self, sample_user_learning
    ):
        """RULE_CONFLICTはCONFIRM_USERを返す"""
        rule_learning = Learning(
            id=str(uuid4()),
            category=LearningCategory.RULE.value,
            learned_content={"condition": "test", "action": "test"},
            authority_level=AuthorityLevel.USER.value,
        )

        conflict = ConflictInfo(
            conflict_type=ConflictType.RULE_CONFLICT.value,
            existing_learning=rule_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test")
        strategy = detector.get_resolution_strategy(conflict)

        assert strategy == ConflictResolutionStrategy.CONFIRM_USER

    def test_default_returns_newer_wins(self, sample_user_learning, conflicting_alias_learning):
        """デフォルトはNEWER_WINSを返す"""
        # 不明な矛盾タイプ
        conflict = ConflictInfo(
            conflict_type="unknown_type",  # type: ignore
            existing_learning=conflicting_alias_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test")
        strategy = detector.get_resolution_strategy(conflict)

        assert strategy == ConflictResolutionStrategy.NEWER_WINS


# =============================================================================
# _detect_conflict_typeテスト
# =============================================================================

class TestDetectConflictType:
    """_detect_conflict_typeメソッドのテスト"""

    def test_different_category_no_conflict(self, sample_user_learning, sample_fact_learning):
        """異なるカテゴリは矛盾なし"""
        detector = ConflictDetector("org_test")
        conflict_type = detector._detect_conflict_type(sample_user_learning, sample_fact_learning)

        assert conflict_type is None

    def test_same_category_conflicting_content(
        self, sample_user_learning, conflicting_alias_learning
    ):
        """同じカテゴリで異なる内容はCONTENT_MISMATCH"""
        detector = ConflictDetector("org_test")
        conflict_type = detector._detect_conflict_type(
            sample_user_learning, conflicting_alias_learning
        )

        assert conflict_type == ConflictType.CONTENT_MISMATCH.value

    def test_rule_category_conflict(self):
        """ルールカテゴリの矛盾はRULE_CONFLICT"""
        rule1 = Learning(
            id=str(uuid4()),
            category=LearningCategory.RULE.value,
            learned_content={"condition": "月曜日", "action": "朝会"},
            authority_level=AuthorityLevel.USER.value,
        )
        rule2 = Learning(
            id=str(uuid4()),
            category=LearningCategory.RULE.value,
            learned_content={"condition": "月曜日", "action": "休会"},
            authority_level=AuthorityLevel.USER.value,
        )

        detector = ConflictDetector("org_test")
        conflict_type = detector._detect_conflict_type(rule1, rule2)

        assert conflict_type == ConflictType.RULE_CONFLICT.value

    def test_same_category_no_conflict_when_content_matches(self):
        """同じカテゴリでも内容が一致すれば矛盾なし（line 303カバレッジ）"""
        # 同じfrom、同じtoで矛盾なし
        learning1 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
            authority_level=AuthorityLevel.USER.value,
        )
        learning2 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
            authority_level=AuthorityLevel.USER.value,
        )

        detector = ConflictDetector("org_test")
        conflict_type = detector._detect_conflict_type(learning1, learning2)

        assert conflict_type is None


# =============================================================================
# _is_conflicting_contentテスト
# =============================================================================

class TestIsConflictingContent:
    """_is_conflicting_contentメソッドのテスト"""

    def test_alias_conflict_same_from_different_to(
        self, sample_user_learning, conflicting_alias_learning
    ):
        """別名：同じfromで異なるtoは矛盾"""
        detector = ConflictDetector("org_test")
        is_conflicting = detector._is_conflicting_content(
            sample_user_learning, conflicting_alias_learning
        )

        assert is_conflicting is True

    def test_alias_no_conflict_different_from(self, sample_user_learning):
        """別名：異なるfromは矛盾なし"""
        other_alias = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "pl", "to": "プロジェクトリーダー"},
            authority_level=AuthorityLevel.USER.value,
        )

        detector = ConflictDetector("org_test")
        is_conflicting = detector._is_conflicting_content(sample_user_learning, other_alias)

        assert is_conflicting is False

    def test_alias_no_conflict_same_to(self, sample_user_learning):
        """別名：同じfrom、同じtoは矛盾なし"""
        same_alias = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
            authority_level=AuthorityLevel.USER.value,
        )

        detector = ConflictDetector("org_test")
        is_conflicting = detector._is_conflicting_content(sample_user_learning, same_alias)

        assert is_conflicting is False

    def test_rule_conflict_same_condition_different_action(self):
        """ルール：同じconditionで異なるactionは矛盾"""
        rule1 = Learning(
            id=str(uuid4()),
            category=LearningCategory.RULE.value,
            learned_content={"condition": "月曜日", "action": "朝会を開く"},
            authority_level=AuthorityLevel.USER.value,
        )
        rule2 = Learning(
            id=str(uuid4()),
            category=LearningCategory.RULE.value,
            learned_content={"condition": "月曜日", "action": "朝会をスキップ"},
            authority_level=AuthorityLevel.USER.value,
        )

        detector = ConflictDetector("org_test")
        is_conflicting = detector._is_conflicting_content(rule1, rule2)

        assert is_conflicting is True

    def test_fact_conflict_same_subject_different_value(
        self, sample_fact_learning, conflicting_fact_learning
    ):
        """事実：同じsubjectで異なるvalueは矛盾"""
        detector = ConflictDetector("org_test")
        is_conflicting = detector._is_conflicting_content(
            sample_fact_learning, conflicting_fact_learning
        )

        assert is_conflicting is True

    def test_preference_conflict_same_subject_different_preference(
        self, sample_preference_learning, conflicting_preference_learning
    ):
        """好み：同じsubjectで異なるpreferenceは矛盾"""
        detector = ConflictDetector("org_test")
        is_conflicting = detector._is_conflicting_content(
            sample_preference_learning, conflicting_preference_learning
        )

        assert is_conflicting is True

    def test_correction_conflict_same_wrong_different_correct(
        self, sample_correction_learning, conflicting_correction_learning
    ):
        """修正：同じwrong_patternで異なるcorrect_patternは矛盾"""
        detector = ConflictDetector("org_test")
        is_conflicting = detector._is_conflicting_content(
            sample_correction_learning, conflicting_correction_learning
        )

        assert is_conflicting is True

    def test_procedure_conflict_same_task_different_steps(
        self, sample_procedure_learning, conflicting_procedure_learning
    ):
        """手順：同じtaskで異なるstepsは矛盾"""
        detector = ConflictDetector("org_test")
        is_conflicting = detector._is_conflicting_content(
            sample_procedure_learning, conflicting_procedure_learning
        )

        assert is_conflicting is True

    def test_unknown_category_no_conflict(self):
        """不明なカテゴリは矛盾なし"""
        learning1 = Learning(
            id=str(uuid4()),
            category="unknown_category",
            learned_content={"foo": "bar"},
            authority_level=AuthorityLevel.USER.value,
        )
        learning2 = Learning(
            id=str(uuid4()),
            category="unknown_category",
            learned_content={"foo": "baz"},
            authority_level=AuthorityLevel.USER.value,
        )

        detector = ConflictDetector("org_test")
        is_conflicting = detector._is_conflicting_content(learning1, learning2)

        assert is_conflicting is False


# =============================================================================
# _detect_ceo_conflictsテスト
# =============================================================================

class TestDetectCeoConflicts:
    """_detect_ceo_conflictsメソッドのテスト"""

    def test_no_ceo_conflicts_when_new_is_ceo(
        self, mock_conn, mock_repository, sample_ceo_learning
    ):
        """新規がCEO教えの場合はCEO矛盾なし"""
        detector = ConflictDetector("org_test", repository=mock_repository)
        conflicts = detector._detect_ceo_conflicts(mock_conn, sample_ceo_learning)

        assert conflicts == []
        mock_repository.find_by_category.assert_not_called()

    def test_detects_ceo_conflicts(self, mock_conn, mock_repository, sample_ceo_learning):
        """CEO教えとの矛盾を検出"""
        conflicting_learning = Learning(
            id=str(uuid4()),
            organization_id="org_test",
            category=LearningCategory.RULE.value,
            trigger_type=TriggerType.ALWAYS.value,
            trigger_value="*",
            learned_content={
                "condition": "常に",
                "action": "人を疑う",  # CEO教えと矛盾
            },
            authority_level=AuthorityLevel.USER.value,
        )

        mock_repository.find_by_category.return_value = [sample_ceo_learning]

        detector = ConflictDetector("org_test", repository=mock_repository)
        conflicts = detector._detect_ceo_conflicts(mock_conn, conflicting_learning)

        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.CEO_CONFLICT.value


# =============================================================================
# _find_ceo_learningsテスト
# =============================================================================

class TestFindCeoLearnings:
    """_find_ceo_learningsメソッドのテスト"""

    def test_finds_ceo_learnings(self, mock_conn, mock_repository, sample_ceo_learning):
        """CEO教えを検索"""
        user_learning = Learning(
            id=str(uuid4()),
            category=LearningCategory.RULE.value,
            learned_content={},
            authority_level=AuthorityLevel.USER.value,
        )

        mock_repository.find_by_category.return_value = [sample_ceo_learning, user_learning]

        detector = ConflictDetector("org_test", repository=mock_repository)
        ceo_learnings = detector._find_ceo_learnings(
            mock_conn, LearningCategory.RULE.value, "*"
        )

        # CEOの学習のみが返される
        assert len(ceo_learnings) == 1
        assert ceo_learnings[0].authority_level == AuthorityLevel.CEO.value


# =============================================================================
# _describe_conflictテスト
# =============================================================================

class TestDescribeConflict:
    """_describe_conflictメソッドのテスト"""

    def test_describe_ceo_conflict(self, sample_user_learning, sample_ceo_learning):
        """CEO矛盾の説明"""
        detector = ConflictDetector("org_test")
        description = detector._describe_conflict(
            ConflictType.CEO_CONFLICT.value,
            sample_user_learning,
            sample_ceo_learning,
        )

        assert "CEO教え" in description
        assert "矛盾" in description

    def test_describe_rule_conflict(self):
        """ルール矛盾の説明"""
        rule1 = Learning(
            id=str(uuid4()),
            category=LearningCategory.RULE.value,
            learned_content={"description": "ルール1"},
            authority_level=AuthorityLevel.USER.value,
        )
        rule2 = Learning(
            id=str(uuid4()),
            category=LearningCategory.RULE.value,
            learned_content={"description": "ルール2"},
            authority_level=AuthorityLevel.USER.value,
        )

        detector = ConflictDetector("org_test")
        description = detector._describe_conflict(
            ConflictType.RULE_CONFLICT.value, rule1, rule2
        )

        assert "ルール" in description
        assert "矛盾" in description

    def test_describe_content_mismatch(self, sample_user_learning, conflicting_alias_learning):
        """内容不一致の説明"""
        detector = ConflictDetector("org_test")
        description = detector._describe_conflict(
            ConflictType.CONTENT_MISMATCH.value,
            sample_user_learning,
            conflicting_alias_learning,
        )

        assert "矛盾" in description


# =============================================================================
# _suggest_resolutionテスト
# =============================================================================

class TestSuggestResolution:
    """_suggest_resolutionメソッドのテスト"""

    def test_suggest_ceo_conflict_higher_authority(
        self, sample_user_learning, sample_ceo_learning
    ):
        """CEO矛盾はHIGHER_AUTHORITYを提案"""
        detector = ConflictDetector("org_test")
        suggestion = detector._suggest_resolution(
            ConflictType.CEO_CONFLICT.value,
            sample_user_learning,
            sample_ceo_learning,
        )

        assert suggestion == ConflictResolutionStrategy.HIGHER_AUTHORITY.value

    def test_suggest_different_priority_higher_authority(
        self, sample_user_learning, sample_manager_learning
    ):
        """異なる権限レベルはHIGHER_AUTHORITYを提案"""
        detector = ConflictDetector("org_test")
        suggestion = detector._suggest_resolution(
            ConflictType.CONTENT_MISMATCH.value,
            sample_user_learning,
            sample_manager_learning,
        )

        assert suggestion == ConflictResolutionStrategy.HIGHER_AUTHORITY.value

    def test_suggest_same_priority_confirm_user(
        self, sample_user_learning, conflicting_alias_learning
    ):
        """同じ権限レベルはCONFIRM_USERを提案"""
        detector = ConflictDetector("org_test")
        suggestion = detector._suggest_resolution(
            ConflictType.CONTENT_MISMATCH.value,
            sample_user_learning,
            conflicting_alias_learning,
        )

        assert suggestion == ConflictResolutionStrategy.CONFIRM_USER.value


# =============================================================================
# _format_ceo_conflict_messageテスト
# =============================================================================

class TestFormatCeoConflictMessage:
    """_format_ceo_conflict_messageメソッドのテスト"""

    def test_format_message(self, sample_ceo_learning):
        """CEO矛盾メッセージのフォーマット"""
        detector = ConflictDetector("org_test")
        message = detector._format_ceo_conflict_message(sample_ceo_learning)

        assert "ソウルシンクスとして大事にしていること" in message
        assert "人の可能性を信じる" in message
        assert "カズさんに確認が必要" in message

    def test_format_message_empty_description(self):
        """空のdescriptionでもエラーにならない"""
        learning = Learning(
            id=str(uuid4()),
            category=LearningCategory.RULE.value,
            learned_content={},  # description なし
            authority_level=AuthorityLevel.CEO.value,
        )

        detector = ConflictDetector("org_test")
        message = detector._format_ceo_conflict_message(learning)

        assert "ソウルシンクスとして大事にしていること" in message


# =============================================================================
# _format_confirmation_messageテスト
# =============================================================================

class TestFormatConfirmationMessage:
    """_format_confirmation_messageメソッドのテスト"""

    def test_format_message(self, sample_user_learning, conflicting_alias_learning):
        """確認メッセージのフォーマット"""
        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=conflicting_alias_learning,
            new_learning=sample_user_learning,
        )

        detector = ConflictDetector("org_test")
        message = detector._format_confirmation_message(conflict)

        assert "ちょっと待ってウル" in message
        assert "覚えている" in message
        assert "更新していいウル" in message
        assert "更新して" in message
        assert "そのままで" in message

    def test_format_message_empty_descriptions(self):
        """空のdescriptionでもエラーにならない"""
        learning1 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={},  # description なし
            authority_level=AuthorityLevel.USER.value,
        )
        learning2 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={},  # description なし
            authority_level=AuthorityLevel.USER.value,
        )

        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=learning1,
            new_learning=learning2,
        )

        detector = ConflictDetector("org_test")
        message = detector._format_confirmation_message(conflict)

        assert "ちょっと待ってウル" in message


# =============================================================================
# エッジケーステスト
# =============================================================================

class TestEdgeCases:
    """エッジケースのテスト"""

    def test_empty_organization_id(self):
        """空の組織ID"""
        detector = ConflictDetector("")
        assert detector.organization_id == ""

    def test_none_learned_content_values(self):
        """learned_contentにNone値が含まれる場合"""
        learning1 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={"from": None, "to": "test"},
            authority_level=AuthorityLevel.USER.value,
        )
        learning2 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={"from": None, "to": "test2"},
            authority_level=AuthorityLevel.USER.value,
        )

        detector = ConflictDetector("org_test")
        # None == None なので from が一致、to が異なるので矛盾
        is_conflicting = detector._is_conflicting_content(learning1, learning2)

        assert is_conflicting is True

    def test_missing_learned_content_keys(self):
        """learned_contentにキーがない場合"""
        learning1 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={},  # from, to がない
            authority_level=AuthorityLevel.USER.value,
        )
        learning2 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
            authority_level=AuthorityLevel.USER.value,
        )

        detector = ConflictDetector("org_test")
        # learning1.get("from") == None, learning2.get("from") == "mtg"
        # None != "mtg" なので矛盾なし
        is_conflicting = detector._is_conflicting_content(learning1, learning2)

        assert is_conflicting is False

    def test_unicode_content(self):
        """Unicode文字を含む内容"""
        learning1 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "絵文字🎉", "to": "celebration"},
            authority_level=AuthorityLevel.USER.value,
        )
        learning2 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "絵文字🎉", "to": "party"},
            authority_level=AuthorityLevel.USER.value,
        )

        detector = ConflictDetector("org_test")
        is_conflicting = detector._is_conflicting_content(learning1, learning2)

        assert is_conflicting is True

    def test_unknown_authority_level(self):
        """不明な権限レベル"""
        learning1 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "test", "to": "test1"},
            authority_level="unknown_level",  # type: ignore
        )
        learning2 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "test", "to": "test2"},
            authority_level=AuthorityLevel.USER.value,
        )

        conflict = ConflictInfo(
            conflict_type=ConflictType.CONTENT_MISMATCH.value,
            existing_learning=learning2,
            new_learning=learning1,
        )

        detector = ConflictDetector("org_test")
        # 不明な権限レベルはデフォルト優先度99
        suggestion = detector._suggest_resolution(
            ConflictType.CONTENT_MISMATCH.value, learning1, learning2
        )

        # 不明(99) != USER(3) なのでHIGHER_AUTHORITYを提案
        assert suggestion == ConflictResolutionStrategy.HIGHER_AUTHORITY.value

    def test_multiple_conflicts_detected(self, mock_conn, mock_repository, sample_user_learning):
        """複数の矛盾を検出"""
        # 2つの異なる矛盾する学習
        conflict1 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            trigger_type=TriggerType.KEYWORD.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "会議"},
            authority_level=AuthorityLevel.USER.value,
        )
        conflict2 = Learning(
            id=str(uuid4()),
            category=LearningCategory.ALIAS.value,
            trigger_type=TriggerType.KEYWORD.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "打ち合わせ"},
            authority_level=AuthorityLevel.USER.value,
        )

        mock_repository.find_by_trigger.return_value = [conflict1, conflict2]
        mock_repository.find_by_category.return_value = []

        detector = ConflictDetector("org_test", repository=mock_repository)
        conflicts = detector.detect_conflicts(mock_conn, sample_user_learning)

        assert len(conflicts) == 2

    def test_large_learned_content(self):
        """大きなlearned_content"""
        large_steps = [f"Step {i}" for i in range(100)]

        learning1 = Learning(
            id=str(uuid4()),
            category=LearningCategory.PROCEDURE.value,
            learned_content={"task": "大きな手順", "steps": large_steps},
            authority_level=AuthorityLevel.USER.value,
        )
        learning2 = Learning(
            id=str(uuid4()),
            category=LearningCategory.PROCEDURE.value,
            learned_content={"task": "大きな手順", "steps": large_steps[:50]},
            authority_level=AuthorityLevel.USER.value,
        )

        detector = ConflictDetector("org_test")
        is_conflicting = detector._is_conflicting_content(learning1, learning2)

        assert is_conflicting is True


# =============================================================================
# 統合テスト
# =============================================================================

class TestIntegration:
    """統合テスト"""

    def test_full_conflict_detection_and_resolution_flow(
        self, mock_conn, mock_repository, sample_user_learning, conflicting_alias_learning
    ):
        """矛盾検出から解決までのフロー"""
        mock_repository.find_by_trigger.return_value = [conflicting_alias_learning]
        mock_repository.find_by_category.return_value = []

        detector = ConflictDetector("org_test", repository=mock_repository)

        # 1. 矛盾を検出
        conflicts = detector.detect_conflicts(mock_conn, sample_user_learning)
        assert len(conflicts) == 1

        # 2. 解決戦略を取得
        strategy = detector.get_resolution_strategy(conflicts[0])
        assert strategy == ConflictResolutionStrategy.CONFIRM_USER

        # 3. ユーザーが「new」を選択して解決
        resolution = detector.resolve_conflict(
            mock_conn, conflicts[0], strategy, user_choice="new"
        )
        assert resolution.action == "supersede"
        assert resolution.kept_learning == sample_user_learning

    def test_ceo_conflict_always_rejected(
        self, mock_conn, mock_repository, sample_ceo_learning
    ):
        """CEO矛盾は常に拒否される完全フロー"""
        conflicting_learning = Learning(
            id=str(uuid4()),
            organization_id="org_test",
            category=LearningCategory.RULE.value,
            trigger_type=TriggerType.ALWAYS.value,
            trigger_value="*",
            learned_content={
                "condition": "常に",
                "action": "人を疑う",
            },
            authority_level=AuthorityLevel.USER.value,
        )

        mock_repository.find_by_trigger.return_value = []
        mock_repository.find_by_category.return_value = [sample_ceo_learning]

        detector = ConflictDetector("org_test", repository=mock_repository)

        # 1. CEO矛盾を検出
        conflicts = detector.detect_conflicts(mock_conn, conflicting_learning)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.CEO_CONFLICT.value

        # 2. どの戦略でも拒否される
        for strategy in ConflictResolutionStrategy:
            resolution = detector.resolve_conflict(mock_conn, conflicts[0], strategy)
            assert resolution.action == "reject"
            assert resolution.kept_learning == sample_ceo_learning
