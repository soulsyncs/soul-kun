"""
Phase 2M: 動機付け・励ましエンジン

ユーザーの落ち込みを検知し、個別化された励ましを生成する。

PII保護: ユーザー名・メッセージ本文は保存しない。
モチベーションタイプとシグナルカテゴリのみ。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .constants import (
    DISCOURAGEMENT_CONFIDENCE_THRESHOLD,
    MOTIVATION_MIN_SAMPLE_COUNT,
    PROFILE_UPDATE_WEIGHT,
    TABLE_BRAIN_MOTIVATION_PROFILES,
    DiscouragementSignal,
    MotivationType,
)
from .models import InterpersonalResult, MotivationProfile

logger = logging.getLogger(__name__)


class MotivationEngine:
    """ユーザーのモチベーションタイプを学習し、個別化された励ましを提供

    主な機能:
    1. get_motivation_profile: モチベーションプロファイル取得
    2. detect_discouragement: 落ち込みシグナルの検知
    3. suggest_encouragement_type: 励ましタイプの提案
    4. update_profile: プロファイル更新
    """

    def __init__(self, organization_id: str = ""):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

    async def get_motivation_profile(
        self,
        conn: Any,
        user_id: str,
    ) -> Optional[MotivationProfile]:
        """ユーザーのモチベーションプロファイルを取得"""
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT id, organization_id, user_id,
                           primary_type, secondary_type,
                           key_values, discouragement_triggers,
                           sample_count, confidence_score,
                           created_at, updated_at
                    FROM {TABLE_BRAIN_MOTIVATION_PROFILES}
                    WHERE organization_id = :org_id AND user_id = :user_id
                    LIMIT 1
                """),
                {"org_id": self.organization_id, "user_id": user_id},
            )
            row = result.fetchone()
            if row is None:
                return None

            return MotivationProfile(
                id=str(row[0]),
                organization_id=str(row[1]),
                user_id=str(row[2]),
                primary_type=MotivationType(row[3]) if row[3] else MotivationType.ACHIEVEMENT,
                secondary_type=MotivationType(row[4]) if row[4] else None,
                key_values=row[5] if row[5] else [],
                discouragement_triggers=row[6] if row[6] else [],
                sample_count=row[7] or 0,
                confidence_score=float(row[8]) if row[8] else 0.5,
                created_at=row[9],
                updated_at=row[10],
            )
        except Exception as e:
            logger.warning("Failed to get motivation profile for user %s: %s", user_id, e)
            return None

    def detect_discouragement(
        self,
        signals: List[DiscouragementSignal],
        profile: Optional[MotivationProfile] = None,
    ) -> Dict[str, Any]:
        """落ち込みシグナルから落ち込み度を判定

        Args:
            signals: 観察された落ち込みシグナルのリスト
            profile: ユーザーのモチベーションプロファイル（あれば）

        Returns:
            {"is_discouraged": bool, "confidence": float, "signals": list}
        """
        if not signals:
            return {"is_discouraged": False, "confidence": 0.0, "signals": []}

        # シグナル数に基づく基本スコア
        base_score = min(1.0, len(signals) * 0.25)

        # プロファイルのトリガーに一致するシグナルがあればブースト
        boost = 0.0
        if profile and profile.discouragement_triggers:
            matching = [s for s in signals if s.value in profile.discouragement_triggers]
            if matching:
                boost = min(0.3, len(matching) * 0.15)

        confidence = min(1.0, base_score + boost)
        is_discouraged = confidence >= DISCOURAGEMENT_CONFIDENCE_THRESHOLD

        return {
            "is_discouraged": is_discouraged,
            "confidence": round(confidence, 2),
            "signals": [s.value for s in signals],
        }

    def suggest_encouragement_type(
        self,
        profile: Optional[MotivationProfile],
    ) -> Dict[str, str]:
        """プロファイルに基づいて最適な励ましタイプを提案

        Returns:
            {"approach": str, "focus": str, "reasoning": str}
        """
        if profile is None or profile.sample_count < MOTIVATION_MIN_SAMPLE_COUNT:
            return {
                "approach": "general",
                "focus": "progress",
                "reasoning": "Insufficient profile data, using general approach",
            }

        approach_map = {
            MotivationType.ACHIEVEMENT: {
                "approach": "milestone",
                "focus": "progress_and_goals",
                "reasoning": "Achievement-oriented: emphasize progress toward goals",
            },
            MotivationType.AFFILIATION: {
                "approach": "team_impact",
                "focus": "team_contribution",
                "reasoning": "Affiliation-oriented: emphasize team impact and belonging",
            },
            MotivationType.AUTONOMY: {
                "approach": "empowerment",
                "focus": "choices_and_control",
                "reasoning": "Autonomy-oriented: emphasize freedom and options",
            },
            MotivationType.GROWTH: {
                "approach": "learning",
                "focus": "skill_development",
                "reasoning": "Growth-oriented: emphasize learning opportunity",
            },
            MotivationType.IMPACT: {
                "approach": "purpose",
                "focus": "meaningful_contribution",
                "reasoning": "Impact-oriented: emphasize meaningful outcomes",
            },
            MotivationType.STABILITY: {
                "approach": "reassurance",
                "focus": "consistency_and_security",
                "reasoning": "Stability-oriented: emphasize reliability and plan",
            },
        }

        return approach_map.get(
            profile.primary_type,
            {"approach": "general", "focus": "progress", "reasoning": "Default approach"},
        )

    async def update_profile(
        self,
        conn: Any,
        user_id: str,
        observed_type: Optional[MotivationType] = None,
        observed_values: Optional[List[str]] = None,
        observed_triggers: Optional[List[str]] = None,
    ) -> InterpersonalResult:
        """モチベーションプロファイルを更新"""
        try:
            from sqlalchemy import text
            existing = await self.get_motivation_profile(conn, user_id)

            if existing is None:
                conn.execute(
                    text(f"""
                        INSERT INTO {TABLE_BRAIN_MOTIVATION_PROFILES}
                        (organization_id, user_id, primary_type,
                         key_values, discouragement_triggers,
                         sample_count, confidence_score)
                        VALUES (:org_id, :user_id, :primary_type,
                                :key_values, :triggers,
                                1, 0.3)
                    """),
                    {
                        "org_id": self.organization_id,
                        "user_id": user_id,
                        "primary_type": (observed_type or MotivationType.ACHIEVEMENT).value,
                        "key_values": observed_values or [],
                        "triggers": observed_triggers or [],
                    },
                )
                return InterpersonalResult(success=True, message="Motivation profile created")

            new_count = existing.sample_count + 1
            new_confidence = min(1.0, existing.confidence_score + PROFILE_UPDATE_WEIGHT * (1.0 - existing.confidence_score))

            params: Dict[str, Any] = {
                "org_id": self.organization_id,
                "user_id": user_id,
                "count": new_count,
                "confidence": new_confidence,
            }

            set_clauses = ["sample_count = :count", "confidence_score = :confidence", "updated_at = NOW()"]

            if observed_type:
                set_clauses.append("primary_type = :primary_type")
                params["primary_type"] = observed_type.value

            # Merge observed_values and observed_triggers with existing arrays
            if observed_values:
                merged_values = list(set((existing.key_values or []) + observed_values))
                set_clauses.append("key_values = :key_values")
                params["key_values"] = json.dumps(merged_values)

            if observed_triggers:
                merged_triggers = list(set((existing.discouragement_triggers or []) + observed_triggers))
                set_clauses.append("discouragement_triggers = :triggers")
                params["triggers"] = json.dumps(merged_triggers)

            conn.execute(
                text(f"""
                    UPDATE {TABLE_BRAIN_MOTIVATION_PROFILES}
                    SET {', '.join(set_clauses)}
                    WHERE organization_id = :org_id AND user_id = :user_id
                """),
                params,
            )
            return InterpersonalResult(success=True, message="Motivation profile updated")

        except Exception as e:
            logger.error("Failed to update motivation profile for user %s: %s", user_id, e)
            return InterpersonalResult(success=False, message=str(e))


def create_motivation_engine(organization_id: str = "") -> MotivationEngine:
    """MotivationEngineのファクトリ関数"""
    return MotivationEngine(organization_id=organization_id)
