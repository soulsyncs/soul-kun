"""
Phase 2M: コミュニケーションスタイル適応

ユーザーごとの好みのコミュニケーションスタイルを学習し、
メッセージのトーンや長さを適応させる。

PII保護: メッセージ本文は保存しない。スタイルメタデータのみ。
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from .constants import (
    FEATURE_FLAG_INTERPERSONAL_ENABLED,
    PROFILE_UPDATE_WEIGHT,
    TABLE_BRAIN_COMMUNICATION_PROFILES,
    InterpersonalStyleType,
    PreferredTiming,
)
from .models import CommunicationProfile, InterpersonalResult

logger = logging.getLogger(__name__)


class CommunicationStyleAdapter:
    """ユーザーの好みスタイルを学習し、コミュニケーションを適応させる

    主な機能:
    1. get_user_profile: ユーザーのスタイルプロファイル取得
    2. adapt_message_style: メッセージスタイルの推奨パラメータを返す
    3. update_profile_from_interaction: インタラクションからプロファイル更新
    4. evaluate_timing: 現在時刻がユーザーの好ましいタイミングか判定
    """

    def __init__(self, organization_id: str = ""):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

    async def get_user_profile(
        self,
        conn: Any,
        user_id: str,
    ) -> Optional[CommunicationProfile]:
        """ユーザーのコミュニケーションプロファイルを取得

        Args:
            conn: DB接続
            user_id: ユーザーID

        Returns:
            CommunicationProfile or None
        """
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT id, organization_id, user_id,
                           preferred_length, formality_level, preferred_timing,
                           response_preferences, interaction_count, confidence_score,
                           created_at, updated_at
                    FROM {TABLE_BRAIN_COMMUNICATION_PROFILES}
                    WHERE organization_id = :org_id AND user_id = :user_id
                    LIMIT 1
                """),
                {"org_id": self.organization_id, "user_id": user_id},
            )
            row = result.fetchone()
            if row is None:
                return None

            return CommunicationProfile(
                id=str(row[0]),
                organization_id=str(row[1]),
                user_id=str(row[2]),
                preferred_length=InterpersonalStyleType(row[3]) if row[3] else InterpersonalStyleType.BALANCED,
                formality_level=InterpersonalStyleType(row[4]) if row[4] else InterpersonalStyleType.ADAPTIVE,
                preferred_timing=PreferredTiming(row[5]) if row[5] else PreferredTiming.ANYTIME,
                response_preferences=row[6] if row[6] else {},
                interaction_count=row[7] or 0,
                confidence_score=float(row[8]) if row[8] else 0.5,
                created_at=row[9],
                updated_at=row[10],
            )
        except Exception as e:
            logger.warning("Failed to get communication profile for user %s: %s", user_id, e)
            return None

    def adapt_message_style(
        self,
        profile: Optional[CommunicationProfile],
    ) -> Dict[str, Any]:
        """プロファイルに基づいてメッセージスタイルの推奨パラメータを返す

        Args:
            profile: ユーザーのプロファイル（Noneの場合はデフォルト）

        Returns:
            スタイル推奨パラメータ dict
        """
        if profile is None:
            return {
                "length": "balanced",
                "formality": "adaptive",
                "timing_ok": True,
                "confidence": 0.0,
            }

        return {
            "length": profile.preferred_length.value,
            "formality": profile.formality_level.value,
            "timing_ok": self._is_good_timing(profile.preferred_timing),
            "confidence": profile.confidence_score,
            "interaction_count": profile.interaction_count,
        }

    async def update_profile_from_interaction(
        self,
        conn: Any,
        user_id: str,
        observed_length: Optional[str] = None,
        observed_formality: Optional[str] = None,
        observed_timing: Optional[str] = None,
    ) -> InterpersonalResult:
        """インタラクション観察からプロファイルを更新

        Args:
            conn: DB接続
            user_id: ユーザーID
            observed_length: 観察されたメッセージ長傾向
            observed_formality: 観察されたフォーマリティ
            observed_timing: 観察されたタイミング傾向

        Returns:
            InterpersonalResult
        """
        try:
            from sqlalchemy import text
            existing = await self.get_user_profile(conn, user_id)

            if existing is None:
                # 新規作成
                conn.execute(
                    text(f"""
                        INSERT INTO {TABLE_BRAIN_COMMUNICATION_PROFILES}
                        (organization_id, user_id, preferred_length, formality_level,
                         preferred_timing, interaction_count, confidence_score)
                        VALUES (:org_id, :user_id, :length, :formality,
                                :timing, 1, 0.3)
                    """),
                    {
                        "org_id": self.organization_id,
                        "user_id": user_id,
                        "length": observed_length or InterpersonalStyleType.BALANCED.value,
                        "formality": observed_formality or InterpersonalStyleType.ADAPTIVE.value,
                        "timing": observed_timing or PreferredTiming.ANYTIME.value,
                    },
                )
                return InterpersonalResult(success=True, message="Profile created")

            # 既存プロファイル更新（加重移動平均）
            updates = {}
            if observed_length:
                updates["preferred_length"] = observed_length
            if observed_formality:
                updates["formality_level"] = observed_formality
            if observed_timing:
                updates["preferred_timing"] = observed_timing

            new_count = existing.interaction_count + 1
            new_confidence = min(1.0, existing.confidence_score + PROFILE_UPDATE_WEIGHT * (1.0 - existing.confidence_score))

            set_clauses = ["interaction_count = :count", "confidence_score = :confidence", "updated_at = NOW()"]
            params: Dict[str, Any] = {
                "org_id": self.organization_id,
                "user_id": user_id,
                "count": new_count,
                "confidence": new_confidence,
            }

            # SECURITY: col keys are hardcoded internal values (preferred_length etc.), not user input
            for col, val in updates.items():
                set_clauses.append(f"{col} = :{col}")
                params[col] = val

            conn.execute(
                text(f"""
                    UPDATE {TABLE_BRAIN_COMMUNICATION_PROFILES}
                    SET {', '.join(set_clauses)}
                    WHERE organization_id = :org_id AND user_id = :user_id
                """),
                params,
            )
            return InterpersonalResult(success=True, message="Profile updated")

        except Exception as e:
            logger.error("Failed to update communication profile for user %s: %s", user_id, e)
            return InterpersonalResult(success=False, message=str(e))

    def _is_good_timing(self, preferred: PreferredTiming) -> bool:
        """現在時刻がユーザーの好ましいタイミングかを判定"""
        if preferred == PreferredTiming.ANYTIME:
            return True

        JST = timezone(timedelta(hours=9))
        hour = datetime.now(JST).hour
        if preferred == PreferredTiming.MORNING:
            return 9 <= hour < 12
        elif preferred == PreferredTiming.AFTERNOON:
            return 12 <= hour < 17
        elif preferred == PreferredTiming.EVENING:
            return hour >= 17
        return True


def create_style_adapter(organization_id: str = "") -> CommunicationStyleAdapter:
    """CommunicationStyleAdapterのファクトリ関数"""
    return CommunicationStyleAdapter(organization_id=organization_id)
