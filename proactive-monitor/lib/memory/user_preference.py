"""
Phase 2 B2: ユーザー嗜好学習

ユーザーごとの好み（回答スタイル、よく使う機能、コミュニケーション傾向）
を自動学習し、パーソナライズされた対応を行う。

Author: Claude Code
Created: 2026-01-24
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from uuid import UUID
from datetime import datetime
import logging
import json

from sqlalchemy import text

from .base import BaseMemory, MemoryResult
from .constants import (
    MemoryParameters,
    PreferenceType,
    LearnedFrom,
)
from .exceptions import (
    PreferenceSaveError,
    PreferenceNotFoundError,
    DatabaseError,
    ValidationError,
    wrap_memory_error,
)


logger = logging.getLogger(__name__)


# ================================================================
# データクラス
# ================================================================

@dataclass
class PreferenceData:
    """ユーザー嗜好のデータクラス"""

    id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    preference_type: str = ""
    preference_key: str = ""
    preference_value: Any = None
    learned_from: str = LearnedFrom.AUTO.value
    confidence: float = 0.5
    sample_count: int = 1
    classification: str = "internal"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "id": str(self.id) if self.id else None,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "preference_type": self.preference_type,
            "preference_key": self.preference_key,
            "preference_value": self.preference_value,
            "learned_from": self.learned_from,
            "confidence": self.confidence,
            "sample_count": self.sample_count,
            "classification": self.classification,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ================================================================
# ユーザー嗜好学習クラス
# ================================================================

class UserPreference(BaseMemory):
    """
    B2: ユーザー嗜好学習

    ユーザーの行動パターンから嗜好を自動学習し、
    パーソナライズされた対応を可能にする。
    """

    def __init__(
        self,
        conn,
        org_id: UUID,
        openrouter_api_key: Optional[str] = None,
        model: str = "google/gemini-3-flash-preview"
    ):
        """
        初期化

        Args:
            conn: データベース接続
            org_id: 組織ID
            openrouter_api_key: OpenRouter APIキー
            model: 使用するLLMモデル
        """
        super().__init__(
            conn=conn,
            org_id=org_id,
            memory_type="b2_preference",
            openrouter_api_key=openrouter_api_key,
            model=model
        )

    # ================================================================
    # 公開メソッド
    # ================================================================

    @wrap_memory_error
    async def save(
        self,
        user_id: UUID,
        preference_type: str,
        preference_key: str,
        preference_value: Any,
        learned_from: str = LearnedFrom.AUTO.value,
        confidence: float = MemoryParameters.PREFERENCE_INITIAL_CONFIDENCE,
        classification: str = "internal"
    ) -> MemoryResult:
        """
        嗜好を保存（UPSERT）

        Args:
            user_id: ユーザーID
            preference_type: 嗜好タイプ
            preference_key: 嗜好キー
            preference_value: 嗜好値
            learned_from: 学習元
            confidence: 信頼度
            classification: 機密区分

        Returns:
            MemoryResult: 保存結果
        """
        user_id = self.validate_uuid(user_id, "user_id")

        # 嗜好タイプの検証
        valid_types = [t.value for t in PreferenceType]
        if preference_type not in valid_types:
            raise ValidationError(
                message=f"Invalid preference_type: {preference_type}. Valid types: {valid_types}",
                field="preference_type"
            )

        # 信頼度の範囲チェック
        confidence = max(0.0, min(confidence, MemoryParameters.PREFERENCE_MAX_CONFIDENCE))

        # preference_valueをJSON形式に変換
        if not isinstance(preference_value, (dict, list, str, int, float, bool, type(None))):
            preference_value = str(preference_value)

        preference_value_json = json.dumps(preference_value, ensure_ascii=False)

        try:
            # UPSERT: 既存があれば更新、なければ挿入
            result = self.conn.execute(text("""
                INSERT INTO user_preferences (
                    organization_id, user_id, preference_type, preference_key,
                    preference_value, learned_from, confidence, sample_count,
                    classification
                ) VALUES (
                    :org_id, :user_id, :pref_type, :pref_key,
                    CAST(:pref_value AS jsonb), :learned_from, :confidence, 1,
                    :classification
                )
                ON CONFLICT (organization_id, user_id, preference_type, preference_key)
                DO UPDATE SET
                    preference_value = CAST(:pref_value AS jsonb),
                    learned_from = :learned_from,
                    confidence = LEAST(
                        user_preferences.confidence + :confidence_increment,
                        :max_confidence
                    ),
                    sample_count = user_preferences.sample_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id, confidence, sample_count
            """), {
                "org_id": str(self.org_id),
                "user_id": str(user_id),
                "pref_type": preference_type,
                "pref_key": preference_key,
                "pref_value": preference_value_json,
                "learned_from": learned_from,
                "confidence": confidence,
                "confidence_increment": MemoryParameters.PREFERENCE_CONFIDENCE_INCREMENT,
                "max_confidence": MemoryParameters.PREFERENCE_MAX_CONFIDENCE,
                "classification": classification,
            })

            row = result.fetchone()
            self.conn.commit()

            pref_id = row[0]
            new_confidence = row[1]
            sample_count = row[2]

            self._log_operation("save_preference", user_id, {
                "preference_id": str(pref_id),
                "preference_type": preference_type,
                "preference_key": preference_key,
                "confidence": new_confidence,
            })

            return MemoryResult(
                success=True,
                memory_id=pref_id,
                message="Preference saved successfully",
                data={
                    "confidence": new_confidence,
                    "sample_count": sample_count,
                }
            )

        except Exception as e:
            logger.error(f"Failed to save preference: {e}")
            raise PreferenceSaveError(
                message=f"Failed to save preference: {str(e)}",
                user_id=str(user_id),
                preference_type=preference_type
            )

    @wrap_memory_error
    async def retrieve(
        self,
        user_id: UUID,
        preference_type: Optional[str] = None,
        min_confidence: float = 0.0
    ) -> List[PreferenceData]:
        """
        嗜好を取得

        Args:
            user_id: ユーザーID
            preference_type: 嗜好タイプ（指定しない場合は全タイプ）
            min_confidence: 最小信頼度

        Returns:
            List[PreferenceData]: 嗜好のリスト
        """
        user_id = self.validate_uuid(user_id, "user_id")

        conditions = [
            "organization_id = :org_id",
            "user_id = :user_id",
            "confidence >= :min_confidence"
        ]
        params = {
            "org_id": str(self.org_id),
            "user_id": str(user_id),
            "min_confidence": min_confidence,
        }

        if preference_type:
            conditions.append("preference_type = :pref_type")
            params["pref_type"] = preference_type

        where_clause = " AND ".join(conditions)

        try:
            result = self.conn.execute(text(f"""
                SELECT
                    id, organization_id, user_id, preference_type, preference_key,
                    preference_value, learned_from, confidence, sample_count,
                    classification, created_at, updated_at
                FROM user_preferences
                WHERE {where_clause}
                ORDER BY confidence DESC, updated_at DESC
            """), params)

            preferences = []
            for row in result.fetchall():
                # JSONBからPythonオブジェクトに変換
                pref_value = row[5]
                if isinstance(pref_value, str):
                    try:
                        pref_value = json.loads(pref_value)
                    except json.JSONDecodeError:
                        pass

                preferences.append(PreferenceData(
                    id=row[0],
                    organization_id=row[1],
                    user_id=row[2],
                    preference_type=row[3],
                    preference_key=row[4],
                    preference_value=pref_value,
                    learned_from=row[6],
                    confidence=float(row[7]) if row[7] else 0.5,
                    sample_count=row[8],
                    classification=row[9],
                    created_at=row[10],
                    updated_at=row[11],
                ))

            return preferences

        except Exception as e:
            logger.error(f"Failed to retrieve preferences: {e}")
            raise DatabaseError(
                message=f"Failed to retrieve preferences: {str(e)}",
                original_error=e
            )

    @wrap_memory_error
    async def get_preference(
        self,
        user_id: UUID,
        preference_type: str,
        preference_key: str
    ) -> Optional[PreferenceData]:
        """
        特定の嗜好を取得

        Args:
            user_id: ユーザーID
            preference_type: 嗜好タイプ
            preference_key: 嗜好キー

        Returns:
            PreferenceData or None
        """
        user_id = self.validate_uuid(user_id, "user_id")

        try:
            result = self.conn.execute(text("""
                SELECT
                    id, organization_id, user_id, preference_type, preference_key,
                    preference_value, learned_from, confidence, sample_count,
                    classification, created_at, updated_at
                FROM user_preferences
                WHERE organization_id = :org_id
                  AND user_id = :user_id
                  AND preference_type = :pref_type
                  AND preference_key = :pref_key
            """), {
                "org_id": str(self.org_id),
                "user_id": str(user_id),
                "pref_type": preference_type,
                "pref_key": preference_key,
            })

            row = result.fetchone()
            if not row:
                return None

            pref_value = row[5]
            if isinstance(pref_value, str):
                try:
                    pref_value = json.loads(pref_value)
                except json.JSONDecodeError:
                    pass

            return PreferenceData(
                id=row[0],
                organization_id=row[1],
                user_id=row[2],
                preference_type=row[3],
                preference_key=row[4],
                preference_value=pref_value,
                learned_from=row[6],
                confidence=float(row[7]) if row[7] else 0.5,
                sample_count=row[8],
                classification=row[9],
                created_at=row[10],
                updated_at=row[11],
            )

        except Exception as e:
            logger.error(f"Failed to get preference: {e}")
            raise DatabaseError(
                message=f"Failed to get preference: {str(e)}",
                original_error=e
            )

    @wrap_memory_error
    async def learn_from_interaction(
        self,
        user_id: UUID,
        interaction_type: str,
        interaction_data: Dict[str, Any]
    ) -> List[MemoryResult]:
        """
        ユーザーのインタラクションから嗜好を学習

        Args:
            user_id: ユーザーID
            interaction_type: インタラクションタイプ（message, task_create, search, etc.）
            interaction_data: インタラクションデータ

        Returns:
            List[MemoryResult]: 学習結果のリスト
        """
        results = []

        # 機能使用を学習
        if interaction_type in ["task_create", "task_search", "knowledge_search", "memory", "goal_setting"]:
            result = await self.save(
                user_id=user_id,
                preference_type=PreferenceType.FEATURE_USAGE.value,
                preference_key=interaction_type,
                preference_value={"count": 1, "last_used": datetime.utcnow().isoformat()},
                learned_from=LearnedFrom.AUTO.value
            )
            results.append(result)

        # メッセージからスタイルを学習
        if interaction_type == "message" and "content" in interaction_data:
            content = interaction_data["content"]

            # 絵文字使用を学習
            emoji_count = sum(1 for c in content if ord(c) > 0x1F600)
            if emoji_count > 0:
                result = await self.save(
                    user_id=user_id,
                    preference_type=PreferenceType.RESPONSE_STYLE.value,
                    preference_key="emoji_usage",
                    preference_value={"uses_emoji": True, "sample_count": emoji_count},
                    learned_from=LearnedFrom.AUTO.value
                )
                results.append(result)

            # メッセージ長から詳しさを学習
            msg_length = len(content)
            length_preference = "detailed" if msg_length > 100 else "concise"
            result = await self.save(
                user_id=user_id,
                preference_type=PreferenceType.RESPONSE_STYLE.value,
                preference_key="length",
                preference_value={"preference": length_preference, "sample_length": msg_length},
                learned_from=LearnedFrom.AUTO.value
            )
            results.append(result)

        # タイムスタンプからアクティブ時間を学習
        if "timestamp" in interaction_data:
            timestamp = interaction_data["timestamp"]
            if isinstance(timestamp, datetime):
                hour = timestamp.hour
                result = await self.save(
                    user_id=user_id,
                    preference_type=PreferenceType.COMMUNICATION.value,
                    preference_key="active_hours",
                    preference_value={"hour": hour},
                    learned_from=LearnedFrom.AUTO.value
                )
                results.append(result)

        return results

    @wrap_memory_error
    async def update_from_emotion_detection(
        self,
        user_id: UUID,
        baseline_score: float,
        current_score: float,
        volatility: float
    ) -> MemoryResult:
        """
        A4感情検出からの連携で感情傾向を更新

        Args:
            user_id: ユーザーID
            baseline_score: ベースラインスコア
            current_score: 現在のスコア
            volatility: 変動の大きさ

        Returns:
            MemoryResult: 更新結果
        """
        trend_direction = "improving" if current_score > baseline_score else "declining"
        if abs(current_score - baseline_score) < 0.1:
            trend_direction = "stable"

        return await self.save(
            user_id=user_id,
            preference_type=PreferenceType.EMOTION_TREND.value,
            preference_key="current_state",
            preference_value={
                "baseline_score": baseline_score,
                "current_score": current_score,
                "volatility": volatility,
                "trend_direction": trend_direction,
                "updated_at": datetime.utcnow().isoformat(),
            },
            learned_from=LearnedFrom.A4_EMOTION.value,
            classification="confidential"  # 感情データはconfidential
        )

    @wrap_memory_error
    async def delete_preference(
        self,
        user_id: UUID,
        preference_type: Optional[str] = None,
        preference_key: Optional[str] = None
    ) -> int:
        """
        嗜好を削除

        Args:
            user_id: ユーザーID
            preference_type: 嗜好タイプ（指定しない場合は全タイプ）
            preference_key: 嗜好キー（指定しない場合は全キー）

        Returns:
            int: 削除件数
        """
        user_id = self.validate_uuid(user_id, "user_id")

        conditions = [
            "organization_id = :org_id",
            "user_id = :user_id"
        ]
        params = {
            "org_id": str(self.org_id),
            "user_id": str(user_id),
        }

        if preference_type:
            conditions.append("preference_type = :pref_type")
            params["pref_type"] = preference_type

        if preference_key:
            conditions.append("preference_key = :pref_key")
            params["pref_key"] = preference_key

        where_clause = " AND ".join(conditions)

        try:
            result = self.conn.execute(text(f"""
                DELETE FROM user_preferences
                WHERE {where_clause}
            """), params)

            deleted_count = result.rowcount
            self.conn.commit()

            self._log_operation("delete_preference", user_id, {
                "deleted_count": deleted_count,
                "preference_type": preference_type,
            })

            return deleted_count

        except Exception as e:
            logger.error(f"Failed to delete preference: {e}")
            raise DatabaseError(
                message=f"Failed to delete preference: {str(e)}",
                original_error=e
            )
