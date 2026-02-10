"""
Phase 2M: 対立調停エンジン

対立の検知、共通点分析、調停戦略の提案を行う。

PII保護: 関係者はIDのみ。メッセージ本文・名前は保存しない。
コンテキストはカテゴリタグのみ。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .constants import (
    CONFLICT_MIN_EVIDENCE_COUNT,
    TABLE_BRAIN_CONFLICT_LOGS,
    ConflictSeverity,
    ConflictStatus,
)
from .models import ConflictLog, InterpersonalResult

logger = logging.getLogger(__name__)


class ConflictMediator:
    """対立の検知・分析・調停支援を提供

    主な機能:
    1. detect_conflict_signals: 対立シグナルの検知
    2. record_conflict: 対立ログの記録
    3. suggest_mediation_strategy: 調停戦略の提案
    4. update_conflict_status: ステータス更新
    5. get_active_conflicts: アクティブな対立一覧取得
    """

    def __init__(self, organization_id: str = ""):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

    def detect_conflict_signals(
        self,
        signals: Dict[str, Any],
    ) -> Dict[str, Any]:
        """シグナルから対立の兆候を検知

        Args:
            signals: 観察シグナル
                - disagreement_count: int (直近の意見不一致数)
                - negative_mentions: int (ネガティブ言及数)
                - avoidance_signals: int (回避行動のカウント)
                - escalation_requests: int (エスカレーション要求数)

        Returns:
            {"is_conflict": bool, "severity": str, "confidence": float, "evidence_count": int}
        """
        evidence_count = 0
        severity_score = 0.0

        disagreements = signals.get("disagreement_count", 0)
        if disagreements > 0:
            evidence_count += disagreements
            severity_score += min(0.3, disagreements * 0.1)

        negative = signals.get("negative_mentions", 0)
        if negative > 0:
            evidence_count += negative
            severity_score += min(0.3, negative * 0.15)

        avoidance = signals.get("avoidance_signals", 0)
        if avoidance > 0:
            evidence_count += avoidance
            severity_score += min(0.2, avoidance * 0.1)

        escalations = signals.get("escalation_requests", 0)
        if escalations > 0:
            evidence_count += escalations
            severity_score += min(0.3, escalations * 0.2)

        severity_score = min(1.0, severity_score)
        is_conflict = evidence_count >= CONFLICT_MIN_EVIDENCE_COUNT

        if severity_score >= 0.7:
            severity = ConflictSeverity.HIGH
        elif severity_score >= 0.4:
            severity = ConflictSeverity.MEDIUM
        else:
            severity = ConflictSeverity.LOW

        return {
            "is_conflict": is_conflict,
            "severity": severity.value,
            "confidence": round(severity_score, 2),
            "evidence_count": evidence_count,
        }

    def suggest_mediation_strategy(
        self,
        severity: ConflictSeverity,
        context_category: str = "",
    ) -> Dict[str, Any]:
        """対立の深刻度とコンテキストに基づいて調停戦略を提案

        Returns:
            {"strategy_type": str, "steps": list, "recommended_timing": str}
        """
        if severity == ConflictSeverity.HIGH:
            return {
                "strategy_type": "direct_mediation",
                "steps": [
                    "Notify CEO immediately",
                    "Arrange separate 1-on-1 conversations",
                    "Identify core needs of each party",
                    "Facilitate structured dialogue",
                    "Document agreed resolution",
                ],
                "recommended_timing": "immediate",
                "ceo_involvement": True,
            }
        elif severity == ConflictSeverity.MEDIUM:
            return {
                "strategy_type": "guided_resolution",
                "steps": [
                    "Monitor for 24-48 hours",
                    "Suggest common ground topics",
                    "Propose collaborative task to rebuild rapport",
                    "Escalate to CEO if not improving",
                ],
                "recommended_timing": "within_24h",
                "ceo_involvement": False,
            }
        else:
            return {
                "strategy_type": "passive_monitoring",
                "steps": [
                    "Continue monitoring signals",
                    "No direct intervention needed yet",
                    "Log for future reference",
                ],
                "recommended_timing": "ongoing",
                "ceo_involvement": False,
            }

    async def record_conflict(
        self,
        conn: Any,
        party_a_user_id: str,
        party_b_user_id: str,
        context_category: str,
        severity: ConflictSeverity,
        evidence_count: int = 0,
    ) -> InterpersonalResult:
        """対立ログを記録"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE_BRAIN_CONFLICT_LOGS}
                    (organization_id, party_a_user_id, party_b_user_id,
                     context_category, severity, status, evidence_count)
                    VALUES (:org_id, :party_a, :party_b,
                            :category, :severity, :status, :evidence)
                """),
                {
                    "org_id": self.organization_id,
                    "party_a": party_a_user_id,
                    "party_b": party_b_user_id,
                    "category": context_category,
                    "severity": severity.value,
                    "status": ConflictStatus.DETECTED.value,
                    "evidence": evidence_count,
                },
            )
            return InterpersonalResult(success=True, message="Conflict logged")
        except Exception as e:
            logger.error("Failed to record conflict: %s", e)
            return InterpersonalResult(success=False, message=type(e).__name__)

    async def update_conflict_status(
        self,
        conn: Any,
        conflict_id: str,
        new_status: ConflictStatus,
        mediation_strategy_type: Optional[str] = None,
    ) -> InterpersonalResult:
        """対立のステータスを更新"""
        try:
            from sqlalchemy import text
            params: Dict[str, Any] = {
                "org_id": self.organization_id,
                "conflict_id": conflict_id,
                "status": new_status.value,
            }

            set_clauses = ["status = :status"]
            if mediation_strategy_type:
                set_clauses.append("mediation_strategy_type = :strategy")
                params["strategy"] = mediation_strategy_type
            if new_status == ConflictStatus.RESOLVED:
                set_clauses.append("resolved_at = NOW()")

            conn.execute(
                text(f"""
                    UPDATE {TABLE_BRAIN_CONFLICT_LOGS}
                    SET {', '.join(set_clauses)}
                    WHERE organization_id = :org_id AND id = :conflict_id::uuid
                """),
                params,
            )
            return InterpersonalResult(success=True, message=f"Conflict status updated to {new_status.value}")
        except Exception as e:
            logger.error("Failed to update conflict %s: %s", conflict_id, e)
            return InterpersonalResult(success=False, message=type(e).__name__)

    async def get_active_conflicts(
        self,
        conn: Any,
    ) -> List[ConflictLog]:
        """アクティブな対立一覧を取得"""
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT id, organization_id, party_a_user_id, party_b_user_id,
                           context_category, severity, status,
                           mediation_strategy_type, evidence_count,
                           detected_at, resolved_at
                    FROM {TABLE_BRAIN_CONFLICT_LOGS}
                    WHERE organization_id = :org_id
                      AND status NOT IN ('resolved', 'escalated')
                    ORDER BY detected_at DESC
                """),
                {"org_id": self.organization_id},
            )
            rows = result.fetchall()
            return [
                ConflictLog(
                    id=str(row[0]),
                    organization_id=str(row[1]),
                    party_a_user_id=str(row[2]),
                    party_b_user_id=str(row[3]),
                    context_category=row[4] or "",
                    severity=ConflictSeverity(row[5]) if row[5] else ConflictSeverity.LOW,
                    status=ConflictStatus(row[6]) if row[6] else ConflictStatus.DETECTED,
                    mediation_strategy_type=row[7],
                    evidence_count=row[8] or 0,
                    detected_at=row[9],
                    resolved_at=row[10],
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to get active conflicts: %s", e)
            return []


def create_conflict_mediator(organization_id: str = "") -> ConflictMediator:
    """ConflictMediatorのファクトリ関数"""
    return ConflictMediator(organization_id=organization_id)
