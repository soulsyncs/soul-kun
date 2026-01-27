# lib/brain/learning.py
"""
ソウルくんの脳 - 学習層（Learning Layer）

判断ログの記録、記憶の更新、パターン分析を行う層です。

設計思想:
- 脳の判断を記録して後から分析可能にする
- ユーザーとのやり取りから学習する
- 低確信度の判断パターンを検出して改善につなげる

設計書: docs/13_brain_architecture.md セクション10
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum

from .models import (
    BrainContext,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
    ConversationMessage,
)
from .constants import (
    CONFIRMATION_THRESHOLD,
    SAVE_DECISION_LOGS,
)

# Phase 2E: 学習基盤統合
try:
    from .learning_foundation import (
        BrainLearning as Phase2ELearning,
        FeedbackDetectionResult,
        ConversationContext as LearningConversationContext,
        Learning,
        CONFIDENCE_THRESHOLD_AUTO_LEARN,
    )
    PHASE_2E_AVAILABLE = True
except ImportError:
    PHASE_2E_AVAILABLE = False

logger = logging.getLogger(__name__)


# =============================================================================
# 学習層の定数
# =============================================================================

# 判断ログの保持期間（日）
DECISION_LOG_RETENTION_DAYS: int = 90

# 低確信度の閾値
LOW_CONFIDENCE_THRESHOLD: float = 0.5

# パターン分析の最小サンプル数
MIN_PATTERN_SAMPLES: int = 10

# 会話サマリーを生成する閾値（会話数）
SUMMARY_THRESHOLD: int = 10

# ユーザー嗜好更新の最小間隔（分）
PREFERENCE_UPDATE_INTERVAL_MINUTES: int = 60


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class DecisionLogEntry:
    """
    判断ログのエントリ
    """
    # 入力情報（必須フィールド）
    room_id: str
    user_id: str
    user_message: str

    # 理解層の結果（必須フィールド）
    understanding_intent: str
    understanding_confidence: float

    # 判断層の結果（必須フィールド）
    selected_action: str

    # 理解層の結果（オプション）
    understanding_entities: Dict[str, Any] = field(default_factory=dict)
    understanding_time_ms: int = 0

    # 判断層の結果（オプション）
    action_params: Dict[str, Any] = field(default_factory=dict)
    decision_confidence: float = 0.0
    decision_reasoning: Optional[str] = None
    required_confirmation: bool = False
    confirmation_question: Optional[str] = None

    # 実行結果
    execution_success: bool = False
    execution_error: Optional[str] = None
    execution_time_ms: int = 0

    # 全体パフォーマンス
    total_time_ms: int = 0

    # メタデータ
    created_at: datetime = field(default_factory=datetime.now)
    classification: str = "internal"

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "room_id": self.room_id,
            "user_id": self.user_id,
            "user_message": self.user_message,
            "understanding_result": {
                "intent": self.understanding_intent,
                "confidence": self.understanding_confidence,
                "entities": self.understanding_entities,
            },
            "understanding_confidence": self.understanding_confidence,
            "selected_action": self.selected_action,
            "action_params": self.action_params,
            "decision_confidence": self.decision_confidence,
            "decision_reasoning": self.decision_reasoning,
            "required_confirmation": self.required_confirmation,
            "confirmation_question": self.confirmation_question,
            "execution_success": self.execution_success,
            "execution_error": self.execution_error,
            "understanding_time_ms": self.understanding_time_ms,
            "decision_time_ms": 0,  # 判断層の実行時間
            "execution_time_ms": self.execution_time_ms,
            "total_time_ms": self.total_time_ms,
            "created_at": self.created_at.isoformat(),
            "classification": self.classification,
        }


@dataclass
class LearningInsight:
    """
    学習から得られたインサイト
    """
    insight_type: str  # "low_confidence", "frequent_error", "pattern_detected"
    description: str
    action: str
    confidence: float
    sample_count: int
    recommendation: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class MemoryUpdate:
    """
    記憶更新の結果
    """
    conversation_saved: bool = False
    summary_generated: bool = False
    preference_updated: bool = False
    learning_saved: bool = False  # Phase 2E: フィードバックから学習を保存したか
    errors: List[str] = field(default_factory=list)


# =============================================================================
# BrainLearning クラス
# =============================================================================

class BrainLearning:
    """
    ソウルくんの脳 - 学習層

    判断ログの記録、記憶の更新、パターン分析を行います。

    主な責務:
    1. 判断ログ記録（brain_decision_logsテーブル）
    2. 記憶更新（会話履歴、会話サマリー）
    3. ユーザー嗜好の学習
    4. パターン分析（低確信度判断の検出）

    Attributes:
        pool: データベース接続プール
        org_id: 組織ID
        firestore_db: Firestoreクライアント（会話履歴用）
        enable_logging: ログ記録を有効にするか
        enable_learning: 学習機能を有効にするか
    """

    def __init__(
        self,
        pool=None,
        org_id: str = "",
        firestore_db=None,
        enable_logging: bool = True,
        enable_learning: bool = True,
    ):
        """
        学習層を初期化

        Args:
            pool: データベース接続プール
            org_id: 組織ID
            firestore_db: Firestoreクライアント
            enable_logging: ログ記録を有効にするか
            enable_learning: 学習機能を有効にするか
        """
        self.pool = pool
        self.org_id = org_id
        self.firestore_db = firestore_db
        self.enable_logging = enable_logging and SAVE_DECISION_LOGS
        self.enable_learning = enable_learning

        # キャッシュ
        self._preference_update_times: Dict[str, datetime] = {}
        self._decision_logs_buffer: List[DecisionLogEntry] = []

        # Phase 2E: 学習基盤
        self._phase2e_learning = None
        if PHASE_2E_AVAILABLE and org_id:
            try:
                self._phase2e_learning = Phase2ELearning(
                    organization_id=org_id,
                    ceo_account_ids=["1728974"],  # カズさん
                    manager_account_ids=[],
                )
                logger.info("Phase 2E Learning Foundation initialized")
            except Exception as e:
                logger.warning(f"Phase 2E initialization failed: {e}")

        logger.debug(
            f"BrainLearning initialized: "
            f"org_id={org_id}, "
            f"enable_logging={self.enable_logging}, "
            f"enable_learning={enable_learning}, "
            f"phase2e={'enabled' if self._phase2e_learning else 'disabled'}"
        )

    # =========================================================================
    # 判断ログ記録
    # =========================================================================

    async def log_decision(
        self,
        message: str,
        understanding: UnderstandingResult,
        decision: DecisionResult,
        result: HandlerResult,
        room_id: str,
        account_id: str,
        understanding_time_ms: int = 0,
        execution_time_ms: int = 0,
        total_time_ms: int = 0,
    ) -> bool:
        """
        判断ログを記録

        Args:
            message: ユーザーのメッセージ
            understanding: 理解層の結果
            decision: 判断層の結果
            result: 実行結果
            room_id: ルームID
            account_id: アカウントID
            understanding_time_ms: 理解にかかった時間
            execution_time_ms: 実行にかかった時間
            total_time_ms: 全体の処理時間

        Returns:
            記録に成功したか
        """
        if not self.enable_logging:
            return True

        try:
            log_entry = DecisionLogEntry(
                room_id=room_id,
                user_id=account_id,
                user_message=message,
                understanding_intent=understanding.intent,
                understanding_confidence=understanding.intent_confidence,
                understanding_entities=understanding.entities,
                understanding_time_ms=understanding_time_ms,
                selected_action=decision.action,
                action_params=decision.params,
                decision_confidence=decision.confidence,
                required_confirmation=decision.needs_confirmation,
                confirmation_question=decision.confirmation_question,
                execution_success=result.success,
                execution_error=result.error_details,
                execution_time_ms=execution_time_ms,
                total_time_ms=total_time_ms,
            )

            # バッファに追加
            self._decision_logs_buffer.append(log_entry)

            # DBに記録（バッファが一定数を超えたらフラッシュ）
            if len(self._decision_logs_buffer) >= 10:
                await self._flush_decision_logs()

            logger.debug(
                f"Decision logged: intent={understanding.intent}, "
                f"action={decision.action}, "
                f"confidence={decision.confidence:.2f}, "
                f"success={result.success}"
            )

            return True

        except Exception as e:
            logger.warning(f"Error logging decision: {e}")
            return False

    async def _flush_decision_logs(self) -> int:
        """
        バッファされた判断ログをDBにフラッシュ

        Returns:
            保存した件数
        """
        if not self._decision_logs_buffer:
            return 0

        if not self.pool:
            # DBがない場合はバッファをクリアして終了
            count = len(self._decision_logs_buffer)
            self._decision_logs_buffer.clear()
            return count

        try:
            logs_to_save = self._decision_logs_buffer.copy()
            self._decision_logs_buffer.clear()

            # TODO: DBへの一括挿入
            # 現在はログ出力のみ
            for log in logs_to_save:
                logger.info(
                    f"[DECISION_LOG] action={log.selected_action}, "
                    f"confidence={log.decision_confidence:.2f}, "
                    f"success={log.execution_success}"
                )

            return len(logs_to_save)

        except Exception as e:
            logger.error(f"Error flushing decision logs: {e}")
            return 0

    async def _save_decision_log_to_db(
        self,
        log_entry: DecisionLogEntry,
    ) -> bool:
        """
        判断ログをDBに保存

        Args:
            log_entry: ログエントリ

        Returns:
            保存に成功したか
        """
        if not self.pool:
            return False

        try:
            # TODO: 実際のDB保存ロジック
            # brain_decision_logsテーブルへのINSERT

            return True

        except Exception as e:
            logger.error(f"Error saving decision log to DB: {e}")
            return False

    # =========================================================================
    # 記憶更新
    # =========================================================================

    async def update_memory(
        self,
        message: str,
        result: HandlerResult,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> MemoryUpdate:
        """
        記憶を更新

        Args:
            message: ユーザーのメッセージ
            result: 実行結果
            context: コンテキスト
            room_id: ルームID
            account_id: アカウントID
            sender_name: 送信者名

        Returns:
            MemoryUpdate: 更新結果
        """
        update_result = MemoryUpdate()

        try:
            # 1. 会話履歴を保存
            if await self._save_conversation(
                message, result.message, room_id, account_id, sender_name
            ):
                update_result.conversation_saved = True

            # 2. 会話サマリーを更新（閾値を超えた場合）
            if len(context.recent_conversation) >= SUMMARY_THRESHOLD:
                if await self._update_conversation_summary(
                    context.recent_conversation, room_id, account_id
                ):
                    update_result.summary_generated = True

            # 3. ユーザー嗜好を更新（間隔をチェック）
            if self._should_update_preference(account_id):
                if await self._update_user_preference(
                    result, context, account_id
                ):
                    update_result.preference_updated = True
                    self._preference_update_times[account_id] = datetime.now()

            # 4. Phase 2E: フィードバックから学習
            if self._phase2e_learning and self.enable_learning:
                learning_saved = await self._process_feedback_learning(
                    message=message,
                    room_id=room_id,
                    account_id=account_id,
                    sender_name=sender_name,
                )
                if learning_saved:
                    update_result.learning_saved = True

        except Exception as e:
            logger.warning(f"Error updating memory: {e}")
            update_result.errors.append(str(e))

        return update_result

    async def _save_conversation(
        self,
        user_message: str,
        ai_response: str,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> bool:
        """
        会話履歴を保存

        Args:
            user_message: ユーザーのメッセージ
            ai_response: AIの応答
            room_id: ルームID
            account_id: アカウントID
            sender_name: 送信者名

        Returns:
            保存に成功したか
        """
        if not self.firestore_db:
            return False

        try:
            # Firestoreに会話履歴を保存
            # TODO: 実際のFirestore保存ロジック
            logger.debug(
                f"Conversation saved: room={room_id}, "
                f"user={sender_name}"
            )
            return True

        except Exception as e:
            logger.warning(f"Error saving conversation: {e}")
            return False

    async def _update_conversation_summary(
        self,
        recent_conversation: List[ConversationMessage],
        room_id: str,
        account_id: str,
    ) -> bool:
        """
        会話サマリーを更新

        Args:
            recent_conversation: 直近の会話
            room_id: ルームID
            account_id: アカウントID

        Returns:
            更新に成功したか
        """
        if not self.pool:
            return False

        try:
            # TODO: LLMを使用してサマリーを生成
            # conversation_summariesテーブルへの保存
            logger.debug(
                f"Conversation summary updated: room={room_id}, "
                f"messages={len(recent_conversation)}"
            )
            return True

        except Exception as e:
            logger.warning(f"Error updating conversation summary: {e}")
            return False

    async def _update_user_preference(
        self,
        result: HandlerResult,
        context: BrainContext,
        account_id: str,
    ) -> bool:
        """
        ユーザー嗜好を更新

        Args:
            result: 実行結果
            context: コンテキスト
            account_id: アカウントID

        Returns:
            更新に成功したか
        """
        if not self.pool:
            return False

        try:
            # TODO: ユーザー嗜好の分析と保存
            # user_preferencesテーブルへの保存
            logger.debug(f"User preference updated: user={account_id}")
            return True

        except Exception as e:
            logger.warning(f"Error updating user preference: {e}")
            return False

    def _should_update_preference(self, account_id: str) -> bool:
        """
        ユーザー嗜好を更新すべきかチェック

        Args:
            account_id: アカウントID

        Returns:
            更新すべきか
        """
        if not self.enable_learning:
            return False

        last_update = self._preference_update_times.get(account_id)
        if last_update is None:
            return True

        elapsed = datetime.now() - last_update
        return elapsed.total_seconds() >= PREFERENCE_UPDATE_INTERVAL_MINUTES * 60

    # =========================================================================
    # Phase 2E: フィードバック学習
    # =========================================================================

    async def _process_feedback_learning(
        self,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> bool:
        """
        Phase 2E: メッセージからフィードバックを検出し、学習を保存

        Args:
            message: ユーザーのメッセージ
            room_id: ルームID
            account_id: アカウントID
            sender_name: 送信者名

        Returns:
            学習を保存したか
        """
        if not self._phase2e_learning:
            return False

        try:
            # 1. フィードバックを検出
            detection_result = self._phase2e_learning.detect(message)

            if not detection_result:
                return False

            logger.info(
                f"[Phase2E] Feedback detected: "
                f"pattern={detection_result.pattern_name}, "
                f"confidence={detection_result.confidence:.2f}, "
                f"category={detection_result.category}"
            )

            # 2. 自動学習すべきか判定
            if not self._phase2e_learning.should_auto_learn(detection_result):
                logger.debug(
                    f"[Phase2E] Confidence too low for auto-learn: "
                    f"{detection_result.confidence:.2f}"
                )
                return False

            # 3. 学習オブジェクトを抽出
            learning = self._phase2e_learning.extract(
                detection_result=detection_result,
                message=message,
                taught_by_account_id=account_id,
                taught_by_name=sender_name,
                room_id=room_id,
            )

            # 4. DBに保存
            if not self.pool:
                logger.warning("[Phase2E] No DB pool, cannot save learning")
                return False

            with self.pool.connect() as conn:
                saved_learning = self._phase2e_learning.save(conn, learning)
                conn.commit()

            logger.info(
                f"[Phase2E] Learning saved: "
                f"id={saved_learning.id}, "
                f"category={saved_learning.category}, "
                f"trigger={saved_learning.trigger_value}"
            )

            return True

        except Exception as e:
            logger.warning(f"[Phase2E] Error processing feedback: {e}")
            return False

    # =========================================================================
    # パターン分析
    # =========================================================================

    async def analyze_patterns(
        self,
        days: int = 7,
    ) -> List[LearningInsight]:
        """
        判断パターンを分析

        Args:
            days: 分析対象の日数

        Returns:
            検出されたインサイトのリスト
        """
        insights: List[LearningInsight] = []

        if not self.pool:
            return insights

        try:
            # 1. 低確信度の判断を検出
            low_confidence_insights = await self._detect_low_confidence_patterns(days)
            insights.extend(low_confidence_insights)

            # 2. 頻繁なエラーを検出
            error_insights = await self._detect_frequent_errors(days)
            insights.extend(error_insights)

            # 3. アクション別の成功率を分析
            success_rate_insights = await self._analyze_action_success_rates(days)
            insights.extend(success_rate_insights)

            logger.info(f"Pattern analysis completed: {len(insights)} insights found")

        except Exception as e:
            logger.error(f"Error analyzing patterns: {e}")

        return insights

    async def _detect_low_confidence_patterns(
        self,
        days: int,
    ) -> List[LearningInsight]:
        """
        低確信度パターンを検出

        Args:
            days: 分析対象の日数

        Returns:
            インサイトのリスト
        """
        insights: List[LearningInsight] = []

        # TODO: DBから低確信度の判断を取得して分析
        # brain_decision_logsテーブルのdecision_confidence < LOW_CONFIDENCE_THRESHOLD

        return insights

    async def _detect_frequent_errors(
        self,
        days: int,
    ) -> List[LearningInsight]:
        """
        頻繁なエラーを検出

        Args:
            days: 分析対象の日数

        Returns:
            インサイトのリスト
        """
        insights: List[LearningInsight] = []

        # TODO: DBからエラーを取得して分析
        # brain_decision_logsテーブルのexecution_success = false

        return insights

    async def _analyze_action_success_rates(
        self,
        days: int,
    ) -> List[LearningInsight]:
        """
        アクション別の成功率を分析

        Args:
            days: 分析対象の日数

        Returns:
            インサイトのリスト
        """
        insights: List[LearningInsight] = []

        # TODO: DBからアクション別の成功率を計算
        # selected_actionでグループ化してexecution_successの割合を計算

        return insights

    # =========================================================================
    # フィードバック処理
    # =========================================================================

    async def record_feedback(
        self,
        decision_log_id: str,
        feedback_type: str,
        feedback_value: Any,
        room_id: str,
        account_id: str,
    ) -> bool:
        """
        ユーザーフィードバックを記録

        Args:
            decision_log_id: 判断ログのID
            feedback_type: フィードバックの種類（"correct", "incorrect", "helpful"等）
            feedback_value: フィードバックの値
            room_id: ルームID
            account_id: アカウントID

        Returns:
            記録に成功したか
        """
        if not self.pool:
            return False

        try:
            # TODO: フィードバックをDBに記録
            logger.info(
                f"Feedback recorded: type={feedback_type}, "
                f"value={feedback_value}, "
                f"decision_id={decision_log_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Error recording feedback: {e}")
            return False

    async def learn_from_feedback(
        self,
        feedback_type: str,
        original_understanding: UnderstandingResult,
        original_decision: DecisionResult,
        corrected_action: Optional[str] = None,
        corrected_params: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        フィードバックから学習

        Args:
            feedback_type: フィードバックの種類
            original_understanding: 元の理解結果
            original_decision: 元の判断結果
            corrected_action: 修正後のアクション
            corrected_params: 修正後のパラメータ

        Returns:
            学習に成功したか
        """
        if not self.enable_learning:
            return False

        try:
            # TODO: フィードバックに基づく学習ロジック
            # - 誤判断パターンの記録
            # - キーワードマッピングの更新
            # - ユーザー嗜好の更新

            logger.info(
                f"Learning from feedback: type={feedback_type}, "
                f"original_action={original_decision.action}, "
                f"corrected_action={corrected_action}"
            )
            return True

        except Exception as e:
            logger.error(f"Error learning from feedback: {e}")
            return False

    # =========================================================================
    # 統計情報
    # =========================================================================

    async def get_statistics(
        self,
        days: int = 7,
    ) -> Dict[str, Any]:
        """
        学習統計情報を取得

        Args:
            days: 統計対象の日数

        Returns:
            統計情報
        """
        stats = {
            "period_days": days,
            "total_decisions": 0,
            "success_rate": 0.0,
            "avg_confidence": 0.0,
            "low_confidence_count": 0,
            "confirmation_rate": 0.0,
            "action_distribution": {},
            "avg_response_time_ms": 0,
        }

        if not self.pool:
            return stats

        try:
            # TODO: DBから統計情報を取得
            pass

        except Exception as e:
            logger.error(f"Error getting statistics: {e}")

        return stats

    async def get_recent_decisions(
        self,
        limit: int = 10,
        action_filter: Optional[str] = None,
    ) -> List[DecisionLogEntry]:
        """
        直近の判断ログを取得

        Args:
            limit: 取得件数
            action_filter: アクションでフィルタ

        Returns:
            判断ログのリスト
        """
        decisions: List[DecisionLogEntry] = []

        # バッファから取得
        for log in reversed(self._decision_logs_buffer):
            if action_filter and log.selected_action != action_filter:
                continue
            decisions.append(log)
            if len(decisions) >= limit:
                break

        return decisions

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    async def cleanup_old_logs(
        self,
        days: int = DECISION_LOG_RETENTION_DAYS,
    ) -> int:
        """
        古いログを削除

        Args:
            days: 保持日数

        Returns:
            削除した件数
        """
        if not self.pool:
            return 0

        try:
            # TODO: 古いログの削除
            # DELETE FROM brain_decision_logs
            # WHERE created_at < NOW() - INTERVAL 'X days'

            logger.info(f"Cleaned up logs older than {days} days")
            return 0

        except Exception as e:
            logger.error(f"Error cleaning up old logs: {e}")
            return 0

    def get_buffer_size(self) -> int:
        """バッファサイズを取得"""
        return len(self._decision_logs_buffer)

    async def force_flush(self) -> int:
        """強制的にバッファをフラッシュ"""
        return await self._flush_decision_logs()


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_learning(
    pool=None,
    org_id: str = "",
    firestore_db=None,
    enable_logging: bool = True,
    enable_learning: bool = True,
) -> BrainLearning:
    """
    BrainLearningインスタンスを作成

    Args:
        pool: データベース接続プール
        org_id: 組織ID
        firestore_db: Firestoreクライアント
        enable_logging: ログ記録を有効にするか
        enable_learning: 学習機能を有効にするか

    Returns:
        BrainLearning
    """
    return BrainLearning(
        pool=pool,
        org_id=org_id,
        firestore_db=firestore_db,
        enable_logging=enable_logging,
        enable_learning=enable_learning,
    )
