"""
Phase 2M: 対人力強化（Interpersonal Skills）モジュール

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2M

コミュニケーションスタイル適応、動機付け・励まし、
適切なタイミングでの助言、対立の調停支援を提供する。

使用例:
    from lib.brain.interpersonal import BrainInterpersonal, create_interpersonal

    # 統合クラスを使用
    interpersonal = create_interpersonal(organization_id="org_xxx")

    # コミュニケーションスタイル適応
    profile = await interpersonal.get_communication_profile(conn, user_id)
    style = interpersonal.get_style_recommendation(profile)

    # 落ち込み検知
    result = interpersonal.detect_discouragement(signals=[...])

    # 助言タイミング判定
    should = await interpersonal.should_provide_feedback(conn, user_id, ...)
"""

import logging
from typing import Any, Dict, List, Optional

from .constants import (
    # Feature flags
    FEATURE_FLAG_CONFLICT_DETECTION_ENABLED,
    FEATURE_FLAG_COUNSEL_ENABLED,
    FEATURE_FLAG_INTERPERSONAL_ENABLED,
    FEATURE_FLAG_MOTIVATION_ENABLED,
    # Enums
    ConflictSeverity,
    ConflictStatus,
    DiscouragementSignal,
    FeedbackType,
    InterpersonalStyleType,
    MotivationType,
    PreferredTiming,
    ReceptivenessLevel,
    # Thresholds
    CONFLICT_MIN_EVIDENCE_COUNT,
    DISCOURAGEMENT_CONFIDENCE_THRESHOLD,
    MIN_FEEDBACK_INTERVAL_HOURS,
    MOTIVATION_MIN_SAMPLE_COUNT,
    PROFILE_UPDATE_WEIGHT,
    RECEPTIVENESS_HIGH_THRESHOLD,
    RECEPTIVENESS_LOW_THRESHOLD,
    # Tables
    TABLE_BRAIN_COMMUNICATION_PROFILES,
    TABLE_BRAIN_CONFLICT_LOGS,
    TABLE_BRAIN_FEEDBACK_OPPORTUNITIES,
    TABLE_BRAIN_MOTIVATION_PROFILES,
)
from .models import (
    CommunicationProfile,
    ConflictLog,
    FeedbackOpportunity,
    InterpersonalResult,
    MotivationProfile,
)
from .style_adapter import CommunicationStyleAdapter, create_style_adapter
from .motivation_engine import MotivationEngine, create_motivation_engine
from .counsel_engine import CounselEngine, create_counsel_engine
from .conflict_mediator import ConflictMediator, create_conflict_mediator

logger = logging.getLogger(__name__)


# =============================================================================
# 統合クラス
# =============================================================================

class BrainInterpersonal:
    """Phase 2M: 対人力強化の統合クラス

    4つのコンポーネントを統合して提供する:
    1. CommunicationStyleAdapter（話し方適応）
    2. MotivationEngine（動機付け・励まし）
    3. CounselEngine（助言タイミング）
    4. ConflictMediator（対立調停）
    """

    def __init__(
        self,
        organization_id: str = "",
        enable_counsel: bool = True,
        enable_motivation: bool = True,
        enable_conflict_detection: bool = True,
    ):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

        # コンポーネント初期化
        self.style_adapter = CommunicationStyleAdapter(organization_id=organization_id)
        self.motivation_engine = MotivationEngine(organization_id=organization_id) if enable_motivation else None
        self.counsel_engine = CounselEngine(organization_id=organization_id) if enable_counsel else None
        self.conflict_mediator = ConflictMediator(organization_id=organization_id) if enable_conflict_detection else None

        logger.info(
            "BrainInterpersonal initialized: org=%s, counsel=%s, motivation=%s, conflict=%s",
            organization_id,
            enable_counsel,
            enable_motivation,
            enable_conflict_detection,
        )

    # =========================================================================
    # コミュニケーションスタイル
    # =========================================================================

    async def get_communication_profile(
        self,
        conn: Any,
        user_id: str,
    ) -> Optional[CommunicationProfile]:
        """ユーザーのコミュニケーションプロファイルを取得"""
        return await self.style_adapter.get_user_profile(conn, user_id)

    def get_style_recommendation(
        self,
        profile: Optional[CommunicationProfile],
    ) -> Dict[str, Any]:
        """プロファイルに基づくスタイル推奨を取得"""
        return self.style_adapter.adapt_message_style(profile)

    async def update_communication_profile(
        self,
        conn: Any,
        user_id: str,
        observed_length: Optional[str] = None,
        observed_formality: Optional[str] = None,
        observed_timing: Optional[str] = None,
    ) -> InterpersonalResult:
        """コミュニケーションプロファイルを更新"""
        return await self.style_adapter.update_profile_from_interaction(
            conn, user_id, observed_length, observed_formality, observed_timing,
        )

    # =========================================================================
    # 動機付け・励まし
    # =========================================================================

    async def get_motivation_profile(
        self,
        conn: Any,
        user_id: str,
    ) -> Optional[MotivationProfile]:
        """ユーザーのモチベーションプロファイルを取得"""
        if self.motivation_engine is None:
            return None
        return await self.motivation_engine.get_motivation_profile(conn, user_id)

    def detect_discouragement(
        self,
        signals: List[DiscouragementSignal],
        profile: Optional[MotivationProfile] = None,
    ) -> Dict[str, Any]:
        """落ち込みシグナルを検知"""
        if self.motivation_engine is None:
            return {"is_discouraged": False, "confidence": 0.0, "signals": []}
        return self.motivation_engine.detect_discouragement(signals, profile)

    def suggest_encouragement(
        self,
        profile: Optional[MotivationProfile],
    ) -> Dict[str, str]:
        """最適な励ましタイプを提案"""
        if self.motivation_engine is None:
            return {"approach": "general", "focus": "progress", "reasoning": "Motivation engine disabled"}
        return self.motivation_engine.suggest_encouragement_type(profile)

    # =========================================================================
    # 助言
    # =========================================================================

    def assess_receptiveness(
        self,
        signals: Dict[str, Any],
    ) -> Dict[str, Any]:
        """ユーザーの受容度を評価"""
        if self.counsel_engine is None:
            return {"score": 0.5, "level": "medium", "reasoning": "Counsel engine disabled"}
        return self.counsel_engine.assess_receptiveness(signals)

    async def should_provide_feedback(
        self,
        conn: Any,
        user_id: str,
        feedback_type: FeedbackType,
        receptiveness_score: float,
    ) -> Dict[str, Any]:
        """フィードバックすべきか判定"""
        if self.counsel_engine is None:
            return {"should_provide": False, "reason": "Counsel engine disabled"}
        return await self.counsel_engine.should_provide_feedback(
            conn, user_id, feedback_type, receptiveness_score,
        )

    async def record_feedback(
        self,
        conn: Any,
        user_id: str,
        feedback_type: FeedbackType,
        context_category: str,
        receptiveness_score: float,
        delivered: bool = False,
    ) -> InterpersonalResult:
        """フィードバック機会を記録"""
        if self.counsel_engine is None:
            return InterpersonalResult(success=False, message="Counsel engine disabled")
        return await self.counsel_engine.record_feedback_opportunity(
            conn, user_id, feedback_type, context_category, receptiveness_score, delivered,
        )

    # =========================================================================
    # 対立調停
    # =========================================================================

    def detect_conflict(
        self,
        signals: Dict[str, Any],
    ) -> Dict[str, Any]:
        """対立シグナルを検知"""
        if self.conflict_mediator is None:
            return {"is_conflict": False, "severity": "low", "confidence": 0.0, "evidence_count": 0}
        return self.conflict_mediator.detect_conflict_signals(signals)

    def suggest_mediation(
        self,
        severity: ConflictSeverity,
        context_category: str = "",
    ) -> Dict[str, Any]:
        """調停戦略を提案"""
        if self.conflict_mediator is None:
            return {"strategy_type": "none", "steps": [], "recommended_timing": "n/a"}
        return self.conflict_mediator.suggest_mediation_strategy(severity, context_category)

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
        if self.conflict_mediator is None:
            return InterpersonalResult(success=False, message="Conflict mediator disabled")
        return await self.conflict_mediator.record_conflict(
            conn, party_a_user_id, party_b_user_id, context_category, severity, evidence_count,
        )

    async def get_active_conflicts(
        self,
        conn: Any,
    ) -> List[ConflictLog]:
        """アクティブな対立一覧を取得"""
        if self.conflict_mediator is None:
            return []
        return await self.conflict_mediator.get_active_conflicts(conn)


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_interpersonal(
    organization_id: str = "",
    feature_flags: Optional[Dict[str, bool]] = None,
) -> BrainInterpersonal:
    """BrainInterpersonalのファクトリ関数"""
    flags = feature_flags or {}
    return BrainInterpersonal(
        organization_id=organization_id,
        enable_counsel=flags.get(FEATURE_FLAG_COUNSEL_ENABLED, True),
        enable_motivation=flags.get(FEATURE_FLAG_MOTIVATION_ENABLED, True),
        enable_conflict_detection=flags.get(FEATURE_FLAG_CONFLICT_DETECTION_ENABLED, True),
    )


def is_interpersonal_enabled(feature_flags: Optional[Dict[str, bool]] = None) -> bool:
    """Phase 2Mが有効かチェック"""
    if feature_flags is None:
        return False
    return feature_flags.get(FEATURE_FLAG_INTERPERSONAL_ENABLED, False)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Main class
    "BrainInterpersonal",
    "create_interpersonal",
    "is_interpersonal_enabled",
    # Components
    "CommunicationStyleAdapter",
    "create_style_adapter",
    "MotivationEngine",
    "create_motivation_engine",
    "CounselEngine",
    "create_counsel_engine",
    "ConflictMediator",
    "create_conflict_mediator",
    # Enums
    "InterpersonalStyleType",
    "PreferredTiming",
    "MotivationType",
    "DiscouragementSignal",
    "FeedbackType",
    "ReceptivenessLevel",
    "ConflictSeverity",
    "ConflictStatus",
    # Models
    "CommunicationProfile",
    "MotivationProfile",
    "FeedbackOpportunity",
    "ConflictLog",
    "InterpersonalResult",
    # Constants
    "RECEPTIVENESS_HIGH_THRESHOLD",
    "RECEPTIVENESS_LOW_THRESHOLD",
    "DISCOURAGEMENT_CONFIDENCE_THRESHOLD",
    "MIN_FEEDBACK_INTERVAL_HOURS",
    "CONFLICT_MIN_EVIDENCE_COUNT",
    "MOTIVATION_MIN_SAMPLE_COUNT",
    "PROFILE_UPDATE_WEIGHT",
    # Tables
    "TABLE_BRAIN_COMMUNICATION_PROFILES",
    "TABLE_BRAIN_MOTIVATION_PROFILES",
    "TABLE_BRAIN_FEEDBACK_OPPORTUNITIES",
    "TABLE_BRAIN_CONFLICT_LOGS",
    # Feature flags
    "FEATURE_FLAG_INTERPERSONAL_ENABLED",
    "FEATURE_FLAG_COUNSEL_ENABLED",
    "FEATURE_FLAG_MOTIVATION_ENABLED",
    "FEATURE_FLAG_CONFLICT_DETECTION_ENABLED",
]

__version__ = "1.0.0"
