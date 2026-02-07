"""
Phase 2F: 結果からの学習モジュール

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2F

暗黙のフィードバックから学ぶ仕組みを提供する。
Phase 2E（明示的フィードバック）に加え、ユーザーの行動から間接的に学習する。

使用例:
    from lib.brain.outcome_learning import BrainOutcomeLearning, create_outcome_learning

    # 統合クラスを使用
    outcome_learning = create_outcome_learning(organization_id)

    # イベント記録
    event_id = outcome_learning.record_action(
        conn=conn,
        action="send_reminder",
        target_account_id="12345",
        target_room_id="67890",
        action_params={"message": "..."},
    )

    # 結果検出（バッチ処理）
    processed = outcome_learning.process_pending_outcomes(conn)

    # パターン抽出
    patterns = outcome_learning.extract_patterns(conn)

    # インサイト生成
    insights = outcome_learning.generate_insights(conn)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.engine import Connection

from .analyzer import OutcomeAnalyzer, create_outcome_analyzer
from .constants import (
    # Enums
    EventType,
    FeedbackSignal,
    OutcomeType,
    PatternScope,
    PatternType,
    # Thresholds
    ADOPTED_THRESHOLD_HOURS,
    DELAYED_THRESHOLD_HOURS,
    IGNORED_THRESHOLD_HOURS,
    MIN_CONFIDENCE_SCORE,
    MIN_SAMPLE_COUNT,
    MIN_SUCCESS_RATE,
    OUTCOME_CHECK_MAX_AGE_HOURS,
    PROMOTION_CONFIDENCE_THRESHOLD,
    PROMOTION_MIN_SAMPLE_COUNT,
    # Actions
    TRACKABLE_ACTIONS,
    # Tables
    TABLE_BRAIN_OUTCOME_EVENTS,
    TABLE_BRAIN_OUTCOME_PATTERNS,
)
from .implicit_detector import (
    ImplicitFeedbackDetector,
    create_implicit_feedback_detector,
)
from .models import (
    DetectionContext,
    ImplicitFeedback,
    OutcomeEvent,
    OutcomeInsight,
    OutcomePattern,
    OutcomeStatistics,
)
from .pattern_extractor import PatternExtractor, create_pattern_extractor
from .repository import OutcomeRepository
from .tracker import OutcomeTracker, create_outcome_tracker


logger = logging.getLogger(__name__)


class BrainOutcomeLearning:
    """結果からの学習統合クラス

    Phase 2Fの全機能を統合して提供する。

    主な機能:
    1. アクションの記録（record_action）
    2. 結果の検出（process_pending_outcomes）
    3. パターンの抽出（extract_patterns）
    4. インサイトの生成（generate_insights）
    5. 学習への昇格（promote_patterns）
    """

    def __init__(
        self,
        organization_id: str,
    ):
        """初期化

        Args:
            organization_id: 組織ID
        """
        self.organization_id = organization_id

        # 共有リポジトリ
        self._repository = OutcomeRepository(organization_id)

        # 各コンポーネント
        self._tracker = OutcomeTracker(organization_id, self._repository)
        self._detector = ImplicitFeedbackDetector(organization_id)
        self._extractor = PatternExtractor(organization_id, self._repository)
        self._analyzer = OutcomeAnalyzer(organization_id, self._repository)

        logger.info(f"BrainOutcomeLearning initialized for org: {organization_id}")

    # ========================================================================
    # イベント記録
    # ========================================================================

    def is_trackable_action(self, action: str) -> bool:
        """追跡対象のアクションかどうか

        Args:
            action: アクション名

        Returns:
            追跡対象かどうか
        """
        return self._tracker.is_trackable_action(action)

    def record_action(
        self,
        conn: Connection,
        action: str,
        target_account_id: str,
        target_room_id: Optional[str] = None,
        action_params: Optional[Dict[str, Any]] = None,
        related_resource_type: Optional[str] = None,
        related_resource_id: Optional[str] = None,
        context_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """アクションを記録

        Args:
            conn: DB接続
            action: アクション名
            target_account_id: 対象ユーザーID
            target_room_id: 対象ルームID
            action_params: アクションパラメータ
            related_resource_type: 関連リソースタイプ
            related_resource_id: 関連リソースID
            context_snapshot: コンテキストスナップショット

        Returns:
            イベントID（追跡対象外の場合はNone）
        """
        return self._tracker.record_action(
            conn=conn,
            action=action,
            target_account_id=target_account_id,
            target_room_id=target_room_id,
            action_params=action_params,
            related_resource_type=related_resource_type,
            related_resource_id=related_resource_id,
            context_snapshot=context_snapshot,
        )

    # ========================================================================
    # 結果検出
    # ========================================================================

    def process_pending_outcomes(
        self,
        conn: Connection,
        max_age_hours: int = OUTCOME_CHECK_MAX_AGE_HOURS,
        limit: int = 100,
    ) -> int:
        """未処理イベントの結果を検出して更新

        Args:
            conn: DB接続
            max_age_hours: 最大経過時間（時間）
            limit: 最大処理件数

        Returns:
            処理件数
        """
        # 未処理イベントを取得
        pending_events = self._repository.find_pending_events(
            conn,
            max_age_hours=max_age_hours,
            limit=limit,
        )

        if not pending_events:
            logger.debug("No pending events to process")
            return 0

        processed = 0
        for event in pending_events:
            try:
                # 暗黙フィードバックを検出
                feedback = self._detector.detect(conn, event)

                if feedback and event.id is not None:
                    # 結果を更新
                    success = self._tracker.update_outcome(
                        conn=conn,
                        event_id=event.id,
                        outcome_type=feedback.outcome_type,
                        outcome_details={
                            "feedback_signal": feedback.feedback_signal,
                            "confidence": feedback.confidence,
                            "evidence": feedback.evidence,
                            "detected_at": feedback.detected_at.isoformat() if feedback.detected_at else None,
                        },
                    )
                    if success:
                        processed += 1
            except Exception as e:
                logger.warning(f"Failed to process event {event.id}: {e}")

        logger.info(f"Processed {processed} outcomes")
        return processed

    def get_pending_events(
        self,
        conn: Connection,
        max_age_hours: int = OUTCOME_CHECK_MAX_AGE_HOURS,
        limit: int = 100,
    ) -> List[OutcomeEvent]:
        """未処理イベントを取得

        Args:
            conn: DB接続
            max_age_hours: 最大経過時間（時間）
            limit: 最大取得件数

        Returns:
            イベントリスト
        """
        return self._repository.find_pending_events(
            conn,
            max_age_hours=max_age_hours,
            limit=limit,
        )

    # ========================================================================
    # パターン抽出
    # ========================================================================

    def extract_patterns(
        self,
        conn: Connection,
        days: int = 30,
        save: bool = True,
    ) -> List[OutcomePattern]:
        """パターンを抽出

        Args:
            conn: DB接続
            days: 分析期間（日数）
            save: 保存するかどうか

        Returns:
            パターンリスト
        """
        patterns = self._extractor.extract_all_patterns(conn, days=days)

        if save and patterns:
            self._extractor.save_patterns(conn, patterns)

        return patterns

    def extract_timing_patterns(
        self,
        conn: Connection,
        target_account_id: Optional[str] = None,
        days: int = 30,
    ) -> List[OutcomePattern]:
        """時間帯パターンを抽出

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID
            days: 分析期間（日数）

        Returns:
            パターンリスト
        """
        return self._extractor.extract_timing_patterns(
            conn,
            target_account_id=target_account_id,
            days=days,
        )

    def find_applicable_patterns(
        self,
        conn: Connection,
        target_account_id: str,
        pattern_type: Optional[str] = None,
    ) -> List[OutcomePattern]:
        """適用可能なパターンを検索

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID
            pattern_type: パターンタイプ

        Returns:
            パターンリスト
        """
        return self._repository.find_applicable_patterns(
            conn,
            target_account_id=target_account_id,
            pattern_type=pattern_type,
        )

    # ========================================================================
    # 学習への昇格
    # ========================================================================

    def find_promotable_patterns(
        self,
        conn: Connection,
    ) -> List[OutcomePattern]:
        """昇格可能なパターンを検索

        Args:
            conn: DB接続

        Returns:
            パターンリスト
        """
        return self._extractor.find_promotable_patterns(conn)

    def promote_pattern_to_learning(
        self,
        conn: Connection,
        pattern_id: str,
    ) -> Optional[str]:
        """パターンを学習に昇格

        Args:
            conn: DB接続
            pattern_id: パターンID

        Returns:
            学習ID（失敗時はNone）
        """
        # パターンを取得
        patterns = self._repository.find_patterns(conn, active_only=True)
        pattern = next((p for p in patterns if p.id == pattern_id), None)

        if not pattern:
            logger.warning(f"Pattern not found: {pattern_id}")
            return None

        if not pattern.is_promotable:
            logger.warning(f"Pattern not promotable: {pattern_id}")
            return None

        # 学習オブジェクトを作成
        from ..learning_foundation import Learning, LearningCategory, TriggerType

        learning = Learning(
            organization_id=self.organization_id,
            category=LearningCategory.FACT.value,
            trigger_type=TriggerType.CONTEXT.value,
            trigger_value=f"implicit_{pattern.pattern_type}",
            learned_content={
                "type": "implicit_pattern",
                "pattern_type": pattern.pattern_type,
                "pattern_content": pattern.pattern_content,
                "source": "outcome_learning",
            },
            scope=pattern.scope,
            scope_target_id=pattern.scope_target_id,
            authority_level="system",
            detection_pattern=f"outcome_pattern_{pattern.pattern_type}",
            detection_confidence=pattern.confidence_score,
            source_message=f"Automatically extracted from {pattern.sample_count} samples",
        )

        # 学習を保存
        try:
            from ..learning_foundation import LearningRepository

            learning_repo = LearningRepository(self.organization_id)
            learning_id = learning_repo.save(conn, learning)

            # パターンを昇格済みとしてマーク
            self._repository.mark_pattern_promoted(conn, pattern_id, learning_id)

            logger.info(f"Pattern promoted to learning: {pattern_id} -> {learning_id}")
            return learning_id
        except Exception as e:
            logger.error(f"Failed to promote pattern: {e}")
            return None

    # ========================================================================
    # 分析・インサイト
    # ========================================================================

    def generate_insights(
        self,
        conn: Connection,
        days: int = 30,
    ) -> List[OutcomeInsight]:
        """インサイトを生成

        Args:
            conn: DB接続
            days: 分析期間（日数）

        Returns:
            インサイトリスト
        """
        return self._analyzer.generate_insights(conn, days=days)

    def analyze_user_responsiveness(
        self,
        conn: Connection,
        account_id: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """ユーザーの反応傾向を分析

        Args:
            conn: DB接続
            account_id: ユーザーID
            days: 分析期間（日数）

        Returns:
            分析結果
        """
        return self._analyzer.analyze_user_responsiveness(
            conn,
            account_id=account_id,
            days=days,
        )

    def get_statistics(
        self,
        conn: Connection,
        target_account_id: Optional[str] = None,
        days: int = 30,
    ) -> OutcomeStatistics:
        """統計を取得

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID
            days: 分析期間（日数）

        Returns:
            統計
        """
        return self._repository.get_statistics(
            conn,
            target_account_id=target_account_id,
            days=days,
        )


def create_outcome_learning(
    organization_id: str,
) -> BrainOutcomeLearning:
    """BrainOutcomeLearningのファクトリ関数

    Args:
        organization_id: 組織ID

    Returns:
        BrainOutcomeLearning
    """
    return BrainOutcomeLearning(organization_id)


# ============================================================================
# エクスポート
# ============================================================================

__all__ = [
    # 統合クラス
    "BrainOutcomeLearning",
    "create_outcome_learning",
    # コンポーネント
    "OutcomeTracker",
    "create_outcome_tracker",
    "ImplicitFeedbackDetector",
    "create_implicit_feedback_detector",
    "PatternExtractor",
    "create_pattern_extractor",
    "OutcomeAnalyzer",
    "create_outcome_analyzer",
    "OutcomeRepository",
    # Enums
    "EventType",
    "FeedbackSignal",
    "OutcomeType",
    "PatternScope",
    "PatternType",
    # Models
    "OutcomeEvent",
    "ImplicitFeedback",
    "OutcomePattern",
    "OutcomeInsight",
    "OutcomeStatistics",
    "DetectionContext",
    # Constants
    "ADOPTED_THRESHOLD_HOURS",
    "DELAYED_THRESHOLD_HOURS",
    "IGNORED_THRESHOLD_HOURS",
    "MIN_CONFIDENCE_SCORE",
    "MIN_SAMPLE_COUNT",
    "MIN_SUCCESS_RATE",
    "OUTCOME_CHECK_MAX_AGE_HOURS",
    "PROMOTION_CONFIDENCE_THRESHOLD",
    "PROMOTION_MIN_SAMPLE_COUNT",
    "TRACKABLE_ACTIONS",
    "TABLE_BRAIN_OUTCOME_EVENTS",
    "TABLE_BRAIN_OUTCOME_PATTERNS",
]
