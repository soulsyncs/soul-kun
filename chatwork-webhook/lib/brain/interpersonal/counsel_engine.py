"""
Phase 2M: 助言エンジン

適切なタイミングでのフィードバック・助言を提供する。
受容度（receptiveness）を判定し、タイミングを最適化する。

PII保護: メッセージ本文は保存しない。カテゴリタグのみ。
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import (
    MIN_FEEDBACK_INTERVAL_HOURS,
    RECEPTIVENESS_HIGH_THRESHOLD,
    RECEPTIVENESS_LOW_THRESHOLD,
    TABLE_BRAIN_FEEDBACK_OPPORTUNITIES,
    FeedbackType,
    ReceptivenessLevel,
)
from .models import FeedbackOpportunity, InterpersonalResult

logger = logging.getLogger(__name__)


class CounselEngine:
    """適切なタイミングでの助言・フィードバックを管理

    主な機能:
    1. assess_receptiveness: ユーザーの受容度を評価
    2. record_feedback_opportunity: フィードバック機会を記録
    3. get_recent_feedback: 直近のフィードバック履歴を取得
    4. should_provide_feedback: フィードバックすべきか判定
    """

    def __init__(self, organization_id: str = ""):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

    def assess_receptiveness(
        self,
        signals: Dict[str, Any],
    ) -> Dict[str, Any]:
        """シグナルからユーザーの受容度を評価

        Args:
            signals: 観察シグナル
                - is_busy: bool (忙しそうか)
                - recent_negative_event: bool (最近ネガティブなイベントがあったか)
                - time_of_day: str (morning/afternoon/evening)
                - recent_success: bool (最近成功体験があったか)
                - conversation_tone: str (positive/neutral/negative)

        Returns:
            {"score": float, "level": str, "reasoning": str}
        """
        score = 0.5  # ベースライン

        # ビジー状態は受容度を下げる
        if signals.get("is_busy", False):
            score -= 0.2

        # ネガティブイベント直後は受容度が低い
        if signals.get("recent_negative_event", False):
            score -= 0.25

        # 成功体験後は受容度が高い
        if signals.get("recent_success", False):
            score += 0.2

        # 会話トーン
        tone = signals.get("conversation_tone", "neutral")
        if tone == "positive":
            score += 0.15
        elif tone == "negative":
            score -= 0.15

        # 時間帯（午前中が最も受容しやすい傾向）
        time_of_day = signals.get("time_of_day", "")
        if time_of_day == "morning":
            score += 0.1
        elif time_of_day == "evening":
            score -= 0.05

        # スコアをクランプ
        score = max(0.0, min(1.0, score))

        # レベル判定
        if score >= RECEPTIVENESS_HIGH_THRESHOLD:
            level = ReceptivenessLevel.HIGH
        elif score >= RECEPTIVENESS_LOW_THRESHOLD:
            level = ReceptivenessLevel.MEDIUM
        else:
            level = ReceptivenessLevel.LOW

        reasoning_parts = []
        if signals.get("is_busy"):
            reasoning_parts.append("user appears busy")
        if signals.get("recent_success"):
            reasoning_parts.append("recent success detected")
        if signals.get("recent_negative_event"):
            reasoning_parts.append("recent negative event")

        return {
            "score": round(score, 2),
            "level": level.value,
            "reasoning": "; ".join(reasoning_parts) if reasoning_parts else "baseline assessment",
        }

    async def should_provide_feedback(
        self,
        conn: Any,
        user_id: str,
        feedback_type: FeedbackType,
        receptiveness_score: float,
    ) -> Dict[str, Any]:
        """フィードバックを今提供すべきか判定

        Args:
            conn: DB接続
            user_id: ユーザーID
            feedback_type: フィードバック種別
            receptiveness_score: 受容度スコア

        Returns:
            {"should_provide": bool, "reason": str}
        """
        # 受容度が低すぎる場合はスキップ
        if receptiveness_score < RECEPTIVENESS_LOW_THRESHOLD:
            return {
                "should_provide": False,
                "reason": f"Receptiveness too low ({receptiveness_score:.2f} < {RECEPTIVENESS_LOW_THRESHOLD})",
            }

        # 修正・指摘は受容度が高い時のみ
        if feedback_type in (FeedbackType.CORRECTION, FeedbackType.CONSTRUCTIVE):
            if receptiveness_score < RECEPTIVENESS_HIGH_THRESHOLD:
                return {
                    "should_provide": False,
                    "reason": f"Constructive feedback requires high receptiveness ({receptiveness_score:.2f} < {RECEPTIVENESS_HIGH_THRESHOLD})",
                }

        # 最近フィードバックしていないか確認
        recent = await self.get_recent_feedback(conn, user_id, hours=MIN_FEEDBACK_INTERVAL_HOURS)
        if recent:
            return {
                "should_provide": False,
                "reason": f"Recent feedback exists within {MIN_FEEDBACK_INTERVAL_HOURS}h interval",
            }

        return {"should_provide": True, "reason": "Conditions met"}

    async def record_feedback_opportunity(
        self,
        conn: Any,
        user_id: str,
        feedback_type: FeedbackType,
        context_category: str,
        receptiveness_score: float,
        delivered: bool = False,
    ) -> InterpersonalResult:
        """フィードバック機会を記録"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE_BRAIN_FEEDBACK_OPPORTUNITIES}
                    (organization_id, user_id, feedback_type, context_category,
                     receptiveness_score, delivered, delivered_at)
                    VALUES (:org_id, :user_id, :type, :category,
                            :score, :delivered, :delivered_at)
                """),
                {
                    "org_id": self.organization_id,
                    "user_id": user_id,
                    "type": feedback_type.value,
                    "category": context_category,
                    "score": receptiveness_score,
                    "delivered": delivered,
                    "delivered_at": datetime.now(timezone.utc) if delivered else None,
                },
            )
            return InterpersonalResult(success=True, message="Feedback opportunity recorded")
        except Exception as e:
            logger.error("Failed to record feedback opportunity for user %s: %s", user_id, e)
            return InterpersonalResult(success=False, message=type(e).__name__)

    async def get_recent_feedback(
        self,
        conn: Any,
        user_id: str,
        hours: int = MIN_FEEDBACK_INTERVAL_HOURS,
    ) -> List[FeedbackOpportunity]:
        """直近のフィードバック履歴を取得"""
        try:
            from sqlalchemy import text
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            result = conn.execute(
                text(f"""
                    SELECT id, organization_id, user_id, feedback_type,
                           context_category, receptiveness_score, delivered
                    FROM {TABLE_BRAIN_FEEDBACK_OPPORTUNITIES}
                    WHERE organization_id = :org_id
                      AND user_id = :user_id
                      AND delivered = true
                      AND created_at >= :cutoff
                    ORDER BY created_at DESC
                """),
                {
                    "org_id": self.organization_id,
                    "user_id": user_id,
                    "cutoff": cutoff,
                },
            )
            rows = result.fetchall()
            return [
                FeedbackOpportunity(
                    id=str(row[0]),
                    organization_id=str(row[1]),
                    user_id=str(row[2]),
                    feedback_type=FeedbackType(row[3]) if row[3] else FeedbackType.CONSTRUCTIVE,
                    context_category=row[4] or "",
                    receptiveness_score=float(row[5]) if row[5] else 0.5,
                    delivered=row[6],
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to get recent feedback for user %s: %s", user_id, e)
            return []


def create_counsel_engine(organization_id: str = "") -> CounselEngine:
    """CounselEngineのファクトリ関数"""
    return CounselEngine(organization_id=organization_id)
