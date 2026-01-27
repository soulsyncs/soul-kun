"""
Phase 2E: 学習基盤モジュール

設計書: docs/18_phase2e_learning_foundation.md v1.1.0

ソウルくんの学習機能を提供する。
- フィードバック検出
- 学習の保存・適用・管理
- 矛盾検出と解決
- 権限レベル管理
- 有効性追跡（Phase 2N準備）
"""

__version__ = "2.0.0"  # Phase 2E

# ============================================================================
# 定数
# ============================================================================

from .constants import (
    # Enum
    LearningCategory,
    LearningScope,
    AuthorityLevel,
    TriggerType,
    RelationshipType,
    DecisionImpact,
    ConflictResolutionStrategy,
    ConflictType,
    # 権限優先度
    AUTHORITY_PRIORITY,
    # 閾値
    CONFIDENCE_THRESHOLD_AUTO_LEARN,
    CONFIDENCE_THRESHOLD_CONFIRM,
    CONFIDENCE_THRESHOLD_MIN,
    DEFAULT_CONFIDENCE_DECAY_RATE,
    DEFAULT_LEARNED_CONTENT_VERSION,
    DEFAULT_CLASSIFICATION,
    # キーワード
    POSITIVE_CONFIRMATION_KEYWORDS,
    NEGATIVE_CONFIRMATION_KEYWORDS,
    LIST_LEARNING_KEYWORDS,
    DELETE_LEARNING_KEYWORDS,
    # メッセージテンプレート
    ERROR_MESSAGES,
    SUCCESS_MESSAGES,
    CONFIRMATION_MESSAGES,
    CEO_CONFLICT_MESSAGE_TEMPLATE,
    MENTION_TEMPLATES,
    # DB定数
    TABLE_BRAIN_LEARNINGS,
    TABLE_BRAIN_LEARNING_LOGS,
    MAX_LEARNINGS_PER_QUERY,
    MAX_LOGS_PER_QUERY,
    MAX_LEARNINGS_PER_CATEGORY_DISPLAY,
)

# ============================================================================
# データモデル
# ============================================================================

from .models import (
    Learning,
    LearningLog,
    FeedbackDetectionResult,
    ConversationContext,
    ConflictInfo,
    Resolution,
    AppliedLearning,
    EffectivenessResult,
    ImprovementSuggestion,
)

# ============================================================================
# パターン
# ============================================================================

from .patterns import (
    DetectionPattern,
    ALL_PATTERNS,
    PATTERNS_BY_NAME,
    PATTERNS_BY_CATEGORY,
    get_patterns_for_category,
)

# ============================================================================
# 検出
# ============================================================================

from .detector import (
    FeedbackDetector,
    create_detector,
)

# ============================================================================
# 抽出
# ============================================================================

from .extractor import (
    LearningExtractor,
    create_extractor,
)

# ============================================================================
# リポジトリ
# ============================================================================

from .repository import (
    LearningRepository,
    create_repository,
)

# ============================================================================
# 適用
# ============================================================================

from .applier import (
    LearningApplier,
    LearningApplierWithCeoCheck,
    create_applier,
    create_applier_with_ceo_check,
)

# ============================================================================
# 管理
# ============================================================================

from .manager import (
    LearningManager,
    create_manager,
)

# ============================================================================
# 矛盾検出
# ============================================================================

from .conflict_detector import (
    ConflictDetector,
    create_conflict_detector,
)

# ============================================================================
# 権限解決
# ============================================================================

from .authority_resolver import (
    AuthorityResolver,
    AuthorityResolverWithDb,
    create_authority_resolver,
    create_authority_resolver_with_db,
)

# ============================================================================
# 有効性追跡
# ============================================================================

from .effectiveness_tracker import (
    EffectivenessTracker,
    EffectivenessMetrics,
    LearningHealth,
    create_effectiveness_tracker,
)

# ============================================================================
# 統合クラス
# ============================================================================


class BrainLearning:
    """脳学習統合クラス

    学習機能の全コンポーネントを統合して提供する。

    使用例:
        brain_learning = BrainLearning(organization_id)

        # フィードバック検出
        result = brain_learning.detect(message, context)

        # 学習の保存
        if result and brain_learning.should_auto_learn(result):
            learning = brain_learning.extract(result, message, context, ...)
            brain_learning.save(conn, learning)

        # 学習の適用
        applicable = brain_learning.find_applicable(conn, message, context)
        context_additions = brain_learning.build_context_additions(applicable)
    """

    def __init__(
        self,
        organization_id: str,
        ceo_account_ids: list = None,
        manager_account_ids: list = None,
    ):
        """初期化

        Args:
            organization_id: 組織ID
            ceo_account_ids: CEOのアカウントIDリスト
            manager_account_ids: 管理者のアカウントIDリスト
        """
        self.organization_id = organization_id

        # リポジトリ（共有）
        self._repository = LearningRepository(organization_id)

        # コンポーネント初期化
        self._detector = FeedbackDetector()
        self._extractor = LearningExtractor(organization_id)
        self._applier = LearningApplierWithCeoCheck(
            organization_id, self._repository
        )
        self._manager = LearningManager(organization_id, self._repository)
        self._conflict_detector = ConflictDetector(
            organization_id, self._repository
        )
        self._authority_resolver = AuthorityResolver(
            organization_id,
            ceo_account_ids or [],
            manager_account_ids or [],
        )
        self._effectiveness_tracker = EffectivenessTracker(
            organization_id, self._repository
        )

    # ========================================================================
    # 検出
    # ========================================================================

    def detect(
        self,
        message: str,
        context: ConversationContext = None,
    ) -> FeedbackDetectionResult:
        """フィードバックを検出

        Args:
            message: メッセージ
            context: 会話コンテキスト

        Returns:
            検出結果（検出なしの場合はNone）
        """
        return self._detector.detect(message, context)

    def should_auto_learn(
        self,
        detection_result: FeedbackDetectionResult,
    ) -> bool:
        """自動学習すべきか判定

        Args:
            detection_result: 検出結果

        Returns:
            自動学習すべきかどうか
        """
        return self._detector.should_auto_learn(detection_result)

    def requires_confirmation(
        self,
        detection_result: FeedbackDetectionResult,
    ) -> bool:
        """確認が必要か判定

        Args:
            detection_result: 検出結果

        Returns:
            確認が必要かどうか
        """
        return self._detector.requires_confirmation(detection_result)

    # ========================================================================
    # 抽出・保存
    # ========================================================================

    def extract(
        self,
        detection_result: FeedbackDetectionResult,
        message: str,
        context: ConversationContext = None,
        taught_by_account_id: str = "",
        taught_by_name: str = None,
        taught_by_authority: str = None,
        room_id: str = None,
    ) -> Learning:
        """学習オブジェクトを抽出

        Args:
            detection_result: 検出結果
            message: メッセージ
            context: 会話コンテキスト
            taught_by_account_id: 教えた人のアカウントID
            taught_by_name: 教えた人の名前
            taught_by_authority: 教えた人の権限レベル
            room_id: ルームID

        Returns:
            学習オブジェクト
        """
        # 権限レベルを自動判定
        if taught_by_authority is None:
            taught_by_authority = self._authority_resolver.get_authority_level(
                None, taught_by_account_id
            )

        return self._extractor.extract(
            detection_result=detection_result,
            message=message,
            context=context,
            taught_by_account_id=taught_by_account_id,
            taught_by_name=taught_by_name,
            taught_by_authority=taught_by_authority,
            room_id=room_id,
        )

    def save(self, conn, learning: Learning) -> str:
        """学習を保存

        Args:
            conn: DB接続
            learning: 学習

        Returns:
            保存された学習のID
        """
        # 矛盾チェック
        conflicts = self._conflict_detector.detect_conflicts(conn, learning)
        ceo_conflicts = [
            c for c in conflicts
            if c.conflict_type == ConflictType.CEO_CONFLICT.value
        ]

        # CEO教えとの矛盾がある場合は拒否
        if ceo_conflicts:
            raise ValueError(
                CEO_CONFLICT_MESSAGE_TEMPLATE.format(
                    ceo_teaching=ceo_conflicts[0].existing_learning.learned_content.get(
                        "description", ""
                    )
                )
            )

        return self._repository.save(conn, learning)

    # ========================================================================
    # 適用
    # ========================================================================

    def find_applicable(
        self,
        conn,
        message: str,
        context: ConversationContext = None,
        user_id: str = None,
        room_id: str = None,
    ) -> list:
        """適用可能な学習を検索

        Args:
            conn: DB接続
            message: メッセージ
            context: 会話コンテキスト
            user_id: ユーザーID
            room_id: ルームID

        Returns:
            適用可能な学習のリスト
        """
        return self._applier.find_applicable(
            conn, message, context, user_id, room_id
        )

    def apply(
        self,
        conn,
        learning: Learning,
        message: str,
        context: ConversationContext = None,
        room_id: str = None,
        account_id: str = None,
    ) -> AppliedLearning:
        """学習を適用

        Args:
            conn: DB接続
            learning: 学習
            message: メッセージ
            context: 会話コンテキスト
            room_id: ルームID
            account_id: アカウントID

        Returns:
            適用結果
        """
        return self._applier.apply(
            conn, learning, message, context, room_id, account_id
        )

    def build_context_additions(
        self,
        applied_learnings: list,
    ) -> dict:
        """コンテキスト追加情報を構築

        Args:
            applied_learnings: 適用された学習のリスト

        Returns:
            コンテキスト追加情報
        """
        return self._applier.build_context_additions(applied_learnings)

    def build_prompt_instructions(
        self,
        context_additions: dict,
    ) -> str:
        """プロンプト指示文を構築

        Args:
            context_additions: コンテキスト追加情報

        Returns:
            プロンプト指示文
        """
        return self._applier.build_prompt_instructions(context_additions)

    # ========================================================================
    # 管理
    # ========================================================================

    def list_all(
        self,
        conn,
        user_id: str = None,
    ) -> dict:
        """全学習を一覧表示

        Args:
            conn: DB接続
            user_id: ユーザーID

        Returns:
            カテゴリ別の学習辞書
        """
        return self._manager.list_all(conn, user_id)

    def delete(
        self,
        conn,
        learning_id: str,
        requester_account_id: str,
        requester_authority: str = None,
    ) -> tuple:
        """学習を削除

        Args:
            conn: DB接続
            learning_id: 学習ID
            requester_account_id: 削除要求者のアカウントID
            requester_authority: 削除要求者の権限レベル

        Returns:
            (成功したか, メッセージ)
        """
        if requester_authority is None:
            requester_authority = self._authority_resolver.get_authority_level(
                None, requester_account_id
            )
        return self._manager.delete(
            conn, learning_id, requester_account_id, requester_authority
        )

    def format_list_response(
        self,
        learnings_by_category: dict,
    ) -> str:
        """一覧表示用レスポンスをフォーマット

        Args:
            learnings_by_category: カテゴリ別の学習辞書

        Returns:
            フォーマットされたレスポンス
        """
        return self._manager.format_list_response(learnings_by_category)

    # ========================================================================
    # コマンド判定
    # ========================================================================

    def is_list_command(self, message: str) -> bool:
        """一覧コマンドか判定"""
        return self._manager.is_list_command(message)

    def is_delete_command(self, message: str) -> bool:
        """削除コマンドか判定"""
        return self._manager.is_delete_command(message)

    # ========================================================================
    # フィードバック
    # ========================================================================

    def record_feedback(
        self,
        conn,
        learning_id: str,
        is_positive: bool,
    ) -> bool:
        """フィードバックを記録

        Args:
            conn: DB接続
            learning_id: 学習ID
            is_positive: ポジティブかどうか

        Returns:
            成功したかどうか
        """
        return self._applier.record_feedback(conn, learning_id, is_positive)

    # ========================================================================
    # 統計
    # ========================================================================

    def get_statistics(self, conn) -> dict:
        """統計情報を取得

        Args:
            conn: DB接続

        Returns:
            統計情報
        """
        return self._manager.get_statistics(conn)

    def get_effectiveness_report(self, conn) -> dict:
        """有効性レポートを取得

        Args:
            conn: DB接続

        Returns:
            有効性レポート
        """
        return self._effectiveness_tracker.generate_summary_report(conn)


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_brain_learning(
    organization_id: str,
    ceo_account_ids: list = None,
    manager_account_ids: list = None,
) -> BrainLearning:
    """脳学習統合クラスを作成

    Args:
        organization_id: 組織ID
        ceo_account_ids: CEOのアカウントIDリスト
        manager_account_ids: 管理者のアカウントIDリスト

    Returns:
        BrainLearning インスタンス
    """
    return BrainLearning(
        organization_id, ceo_account_ids, manager_account_ids
    )


# ============================================================================
# 利便性のためのエイリアス
# ============================================================================

# 検出
detect_feedback = FeedbackDetector().detect

# パターン取得
get_all_patterns = lambda: ALL_PATTERNS
get_pattern_by_name = lambda name: PATTERNS_BY_NAME.get(name)


# ============================================================================
# __all__ 定義
# ============================================================================

__all__ = [
    # バージョン
    "__version__",
    # Enum
    "LearningCategory",
    "LearningScope",
    "AuthorityLevel",
    "TriggerType",
    "RelationshipType",
    "DecisionImpact",
    "ConflictResolutionStrategy",
    "ConflictType",
    # 定数
    "AUTHORITY_PRIORITY",
    "CONFIDENCE_THRESHOLD_AUTO_LEARN",
    "CONFIDENCE_THRESHOLD_CONFIRM",
    "CONFIDENCE_THRESHOLD_MIN",
    "DEFAULT_CONFIDENCE_DECAY_RATE",
    "DEFAULT_LEARNED_CONTENT_VERSION",
    "DEFAULT_CLASSIFICATION",
    "POSITIVE_CONFIRMATION_KEYWORDS",
    "NEGATIVE_CONFIRMATION_KEYWORDS",
    "LIST_LEARNING_KEYWORDS",
    "DELETE_LEARNING_KEYWORDS",
    "ERROR_MESSAGES",
    "SUCCESS_MESSAGES",
    "CONFIRMATION_MESSAGES",
    "CEO_CONFLICT_MESSAGE_TEMPLATE",
    "MENTION_TEMPLATES",
    "TABLE_BRAIN_LEARNINGS",
    "TABLE_BRAIN_LEARNING_LOGS",
    "MAX_LEARNINGS_PER_QUERY",
    "MAX_LOGS_PER_QUERY",
    "MAX_LEARNINGS_PER_CATEGORY_DISPLAY",
    # データモデル
    "Learning",
    "LearningLog",
    "FeedbackDetectionResult",
    "ConversationContext",
    "ConflictInfo",
    "Resolution",
    "AppliedLearning",
    "EffectivenessResult",
    "ImprovementSuggestion",
    # パターン
    "DetectionPattern",
    "ALL_PATTERNS",
    "PATTERNS_BY_NAME",
    "PATTERNS_BY_CATEGORY",
    "get_patterns_for_category",
    # クラス
    "FeedbackDetector",
    "LearningExtractor",
    "LearningRepository",
    "LearningApplier",
    "LearningApplierWithCeoCheck",
    "LearningManager",
    "ConflictDetector",
    "AuthorityResolver",
    "AuthorityResolverWithDb",
    "EffectivenessTracker",
    "EffectivenessMetrics",
    "LearningHealth",
    "BrainLearning",
    # ファクトリ関数
    "create_detector",
    "create_extractor",
    "create_repository",
    "create_applier",
    "create_applier_with_ceo_check",
    "create_manager",
    "create_conflict_detector",
    "create_authority_resolver",
    "create_authority_resolver_with_db",
    "create_effectiveness_tracker",
    "create_brain_learning",
    # 利便性関数
    "detect_feedback",
    "get_all_patterns",
    "get_pattern_by_name",
]
