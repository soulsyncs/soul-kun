"""
Phase 2F: 結果からの学習 - 暗黙フィードバック検出

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2F

暗黙のフィードバックを検出するクラス。
ユーザーの行動から間接的なフィードバックを読み取る。
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .constants import (
    ADOPTED_THRESHOLD_HOURS,
    DELAYED_THRESHOLD_HOURS,
    GOAL_RESPONSE_EXPECTED_DAYS,
    IGNORED_THRESHOLD_HOURS,
    NO_RESPONSE_THRESHOLD_DAYS,
    EventType,
    FeedbackSignal,
    OutcomeType,
)
from .models import DetectionContext, ImplicitFeedback, OutcomeEvent
from .repository import OutcomeRepository


logger = logging.getLogger(__name__)


class ImplicitFeedbackDetector:
    """暗黙フィードバック検出クラス

    検出ルール:
    1. 通知後N時間以内のアクション → 採用
    2. 通知後反応なし → 無視
    3. daily_noteなしが続く → リマインド効果低い
    4. タスク完了が提案後 → 提案が効果的

    使用例:
        detector = ImplicitFeedbackDetector(organization_id)

        # 暗黙フィードバック検出
        feedback = await detector.detect(conn, event)
        if feedback:
            print(f"Detected: {feedback.outcome_type}, confidence: {feedback.confidence}")
    """

    def __init__(self, organization_id: str):
        """初期化

        Args:
            organization_id: 組織ID
        """
        self.organization_id = organization_id

    def detect(
        self,
        conn: Connection,
        event: OutcomeEvent,
    ) -> Optional[ImplicitFeedback]:
        """暗黙フィードバックを検出

        Args:
            conn: DB接続
            event: イベント

        Returns:
            検出されたフィードバック（検出できない場合はNone）
        """
        if event.id is None:
            logger.warning("Event has no ID, skipping detection")
            return None

        if event.outcome_detected:
            logger.debug(f"Event already has outcome: {event.id}")
            return None

        # イベントタイプに応じた検出
        event_type = event.event_type

        if event_type == EventType.GOAL_REMINDER.value:
            return self._detect_from_goal_progress(conn, event)

        elif event_type == EventType.TASK_REMINDER.value:
            return self._detect_from_task_status(conn, event)

        elif event_type == EventType.DAILY_CHECK.value:
            return self._detect_from_daily_response(conn, event)

        elif event_type in [
            EventType.NOTIFICATION_SENT.value,
            EventType.PROACTIVE_MESSAGE.value,
            EventType.FOLLOW_UP.value,
        ]:
            return self._detect_from_time_elapsed(conn, event)

        else:
            return self._detect_from_time_elapsed(conn, event)

    def _detect_from_goal_progress(
        self,
        conn: Connection,
        event: OutcomeEvent,
    ) -> Optional[ImplicitFeedback]:
        """目標進捗から暗黙フィードバックを検出

        Args:
            conn: DB接続
            event: イベント（event.idは非None保証: detect()で検証済み）

        Returns:
            フィードバック
        """
        assert event.id is not None  # detect()で検証済み
        goal_id = event.related_resource_id
        if not goal_id:
            return self._detect_from_time_elapsed(conn, event)

        # 目標進捗を確認
        query = text("""
            SELECT
                gp.progress_date,
                gp.daily_note,
                gp.daily_choice,
                gp.created_at
            FROM goal_progress gp
            WHERE gp.goal_id = CAST(:goal_id AS uuid)
              AND gp.progress_date >= :event_date
            ORDER BY gp.progress_date ASC
            LIMIT 5
        """)

        event_date = event.event_timestamp.date() if event.event_timestamp else datetime.now().date()

        try:
            result = conn.execute(query, {
                "goal_id": goal_id,
                "event_date": event_date,
            })
            rows = result.fetchall()
        except Exception as e:
            logger.warning(f"Failed to query goal_progress: {e}")
            return self._detect_from_time_elapsed(conn, event)

        if not rows:
            # 進捗なし = 無視の可能性
            elapsed = datetime.now() - (event.event_timestamp or datetime.now())
            if elapsed.total_seconds() / 3600 > IGNORED_THRESHOLD_HOURS:
                return ImplicitFeedback(
                    event_id=event.id,
                    feedback_signal=FeedbackSignal.GOAL_STALLED.value,
                    outcome_type=OutcomeType.IGNORED.value,
                    confidence=0.7,
                    evidence={
                        "detection_method": "goal_progress",
                        "elapsed_hours": elapsed.total_seconds() / 3600,
                        "no_progress_recorded": True,
                    },
                    detected_at=datetime.now(),
                )
            return None

        # 進捗あり
        first_progress = rows[0]
        progress_date = first_progress[0]
        daily_note = first_progress[1]

        # daily_noteが記録されている = 採用
        if daily_note:
            return ImplicitFeedback(
                event_id=event.id,
                feedback_signal=FeedbackSignal.GOAL_PROGRESS_MADE.value,
                outcome_type=OutcomeType.ADOPTED.value,
                confidence=0.85,
                evidence={
                    "detection_method": "goal_progress",
                    "progress_date": str(progress_date),
                    "has_daily_note": True,
                },
                detected_at=datetime.now(),
            )

        # daily_noteなし = 遅延または部分採用
        return ImplicitFeedback(
            event_id=event.id,
            feedback_signal=FeedbackSignal.READ_BUT_NO_ACTION.value,
            outcome_type=OutcomeType.PARTIAL.value,
            confidence=0.6,
            evidence={
                "detection_method": "goal_progress",
                "progress_date": str(progress_date),
                "has_daily_note": False,
            },
            detected_at=datetime.now(),
        )

    def _detect_from_task_status(
        self,
        conn: Connection,
        event: OutcomeEvent,
    ) -> Optional[ImplicitFeedback]:
        """タスク状態から暗黙フィードバックを検出

        Args:
            conn: DB接続
            event: イベント（event.idは非None保証: detect()で検証済み）

        Returns:
            フィードバック
        """
        assert event.id is not None  # detect()で検証済み
        task_id = event.related_resource_id
        if not task_id:
            return self._detect_from_time_elapsed(conn, event)

        # タスク状態を確認
        query = text("""
            SELECT
                status,
                updated_at,
                limit_time
            FROM chatwork_tasks
            WHERE id = CAST(:task_id AS uuid)
        """)

        try:
            result = conn.execute(query, {"task_id": task_id})
            row = result.fetchone()
        except Exception as e:
            logger.warning(f"Failed to query chatwork_tasks: {e}")
            return self._detect_from_time_elapsed(conn, event)

        if not row:
            return self._detect_from_time_elapsed(conn, event)

        status = row[0]
        updated_at = row[1]

        # タスク完了 = 採用
        if status == "done":
            return ImplicitFeedback(
                event_id=event.id,
                feedback_signal=FeedbackSignal.TASK_COMPLETED.value,
                outcome_type=OutcomeType.ADOPTED.value,
                confidence=0.9,
                evidence={
                    "detection_method": "task_status",
                    "task_status": status,
                    "completed_at": str(updated_at) if updated_at else None,
                },
                detected_at=datetime.now(),
            )

        # タスク期限切れ = 無視の可能性
        limit_time = row[2]
        if limit_time and datetime.now() > limit_time:
            return ImplicitFeedback(
                event_id=event.id,
                feedback_signal=FeedbackSignal.TASK_OVERDUE.value,
                outcome_type=OutcomeType.IGNORED.value,
                confidence=0.7,
                evidence={
                    "detection_method": "task_status",
                    "task_status": status,
                    "limit_time": str(limit_time),
                    "is_overdue": True,
                },
                detected_at=datetime.now(),
            )

        # まだ判断できない
        return None

    def _detect_from_daily_response(
        self,
        conn: Connection,
        event: OutcomeEvent,
    ) -> Optional[ImplicitFeedback]:
        """日次チェックへの反応から暗黙フィードバックを検出

        Args:
            conn: DB接続
            event: イベント（event.idは非None保証: detect()で検証済み）

        Returns:
            フィードバック
        """
        assert event.id is not None  # detect()で検証済み
        # notification_logsから反応を確認
        query = text("""
            SELECT
                status,
                updated_at,
                metadata
            FROM notification_logs
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND target_id = :target_id
              AND notification_date = :notification_date
            ORDER BY updated_at DESC
            LIMIT 1
        """)

        event_date = event.event_timestamp.date() if event.event_timestamp else datetime.now().date()

        try:
            result = conn.execute(query, {
                "organization_id": self.organization_id,
                "target_id": event.target_account_id,
                "notification_date": event_date,
            })
            row = result.fetchone()
        except Exception as e:
            logger.warning(f"Failed to query notification_logs: {e}")
            return self._detect_from_time_elapsed(conn, event)

        if row and row[0] == "success":
            # 通知成功 = 時間経過で判断
            return self._detect_from_time_elapsed(conn, event)

        # 通知失敗
        return None

    def _detect_from_time_elapsed(
        self,
        conn: Connection,
        event: OutcomeEvent,
    ) -> Optional[ImplicitFeedback]:
        """経過時間から暗黙フィードバックを検出

        Args:
            conn: DB接続
            event: イベント（event.idは非None保証: detect()で検証済み）

        Returns:
            フィードバック
        """
        assert event.id is not None  # detect()で検証済み
        if not event.event_timestamp:
            return None

        elapsed = datetime.now() - event.event_timestamp
        elapsed_hours = elapsed.total_seconds() / 3600

        # ユーザーの反応を確認（chatwork_messagesなど）
        # 反応があれば早い段階でも判断可能
        has_response = self._check_user_response(conn, event)

        if has_response:
            # 反応あり = 採用（時間によって遅延かどうかを分類）
            if elapsed_hours <= ADOPTED_THRESHOLD_HOURS:
                outcome_type = OutcomeType.ADOPTED.value
                confidence = 0.85
            elif elapsed_hours <= DELAYED_THRESHOLD_HOURS:
                outcome_type = OutcomeType.DELAYED.value
                confidence = 0.75
            else:
                outcome_type = OutcomeType.DELAYED.value
                confidence = 0.6

            return ImplicitFeedback(
                event_id=event.id,
                feedback_signal=FeedbackSignal.REPLY_RECEIVED.value,
                outcome_type=outcome_type,
                confidence=confidence,
                evidence={
                    "detection_method": "time_based",
                    "elapsed_hours": elapsed_hours,
                    "has_response": True,
                },
                detected_at=datetime.now(),
            )

        # 反応なしの場合、無視判定の閾値を超えるまで待つ
        if elapsed_hours >= IGNORED_THRESHOLD_HOURS:
            return ImplicitFeedback(
                event_id=event.id,
                feedback_signal=FeedbackSignal.NO_RESPONSE.value,
                outcome_type=OutcomeType.IGNORED.value,
                confidence=0.7,
                evidence={
                    "detection_method": "time_based",
                    "elapsed_hours": elapsed_hours,
                    "threshold_hours": IGNORED_THRESHOLD_HOURS,
                    "has_response": False,
                },
                detected_at=datetime.now(),
            )

        # まだ判断できない（反応なし、かつ無視判定閾値未満）
        return None

    def _check_user_response(
        self,
        conn: Connection,
        event: OutcomeEvent,
    ) -> bool:
        """ユーザーの反応があったかチェック

        Args:
            conn: DB接続
            event: イベント

        Returns:
            反応があったかどうか
        """
        # ルームでのメッセージを確認
        if not event.target_room_id:
            return False

        query = text("""
            SELECT EXISTS(
                SELECT 1
                FROM chatwork_messages
                WHERE room_id = :room_id
                  AND account_id = :account_id
                  AND sent_at > :event_timestamp
                  AND sent_at <= :check_until
            )
        """)

        check_until = (event.event_timestamp or datetime.now()) + timedelta(hours=IGNORED_THRESHOLD_HOURS)

        try:
            result = conn.execute(query, {
                "room_id": event.target_room_id,
                "account_id": event.target_account_id,
                "event_timestamp": event.event_timestamp,
                "check_until": min(check_until, datetime.now()),
            })
            row = result.fetchone()
            return bool(row and row[0])
        except Exception as e:
            logger.debug(f"Failed to check user response: {e}")
            return False

    def detect_batch(
        self,
        conn: Connection,
        events: List[OutcomeEvent],
    ) -> List[ImplicitFeedback]:
        """バッチで暗黙フィードバックを検出

        Args:
            conn: DB接続
            events: イベントリスト

        Returns:
            検出されたフィードバックリスト
        """
        feedbacks = []
        for event in events:
            try:
                feedback = self.detect(conn, event)
                if feedback:
                    feedbacks.append(feedback)
            except Exception as e:
                logger.warning(f"Failed to detect feedback for event {event.id}: {e}")
        return feedbacks


def create_implicit_feedback_detector(
    organization_id: str,
) -> ImplicitFeedbackDetector:
    """ImplicitFeedbackDetectorのファクトリ関数

    Args:
        organization_id: 組織ID

    Returns:
        ImplicitFeedbackDetector
    """
    return ImplicitFeedbackDetector(organization_id)
