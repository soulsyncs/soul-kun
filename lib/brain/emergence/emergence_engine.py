"""
Phase 2O: 創発エンジン

個別能力の組み合わせから、単独では不可能な高度なパターンを検出する。

PII保護: パターンタイプ・スコアのみ。個人データは含まない。
"""

import json
import logging
from typing import Any, Dict, List

from .constants import (
    EMERGENCE_CONFIDENCE_THRESHOLD,
    MAX_EMERGENT_BEHAVIORS_PER_ORG,
    TABLE_BRAIN_EMERGENT_BEHAVIORS,
    EmergentBehaviorType,
)
from .models import CapabilityEdge, EmergentBehavior, EmergenceResult

logger = logging.getLogger(__name__)


# 既知の創発パターンテンプレート
_KNOWN_EMERGENCE_PATTERNS: Dict[str, Dict[str, Any]] = {
    "learning_memory_judgment": {
        "phases": {"2E", "2G", "2J"},
        "description": "Learning from outcomes + episodic recall + judgment yields insight-driven decisions",
        "behavior_type": EmergentBehaviorType.NOVEL_COMBINATION.value,
    },
    "self_awareness_optimization": {
        "phases": {"2H", "2N"},
        "description": "Self-awareness + self-optimization enables targeted self-improvement",
        "behavior_type": EmergentBehaviorType.ADAPTIVE_RESPONSE.value,
    },
    "prediction_execution": {
        "phases": {"2F", "2L"},
        "description": "Outcome prediction + execution management enables proactive risk mitigation",
        "behavior_type": EmergentBehaviorType.CROSS_DOMAIN.value,
    },
    "interpersonal_proactive": {
        "phases": {"2M", "2K"},
        "description": "Interpersonal skills + proactive behavior enables context-aware engagement",
        "behavior_type": EmergentBehaviorType.ADAPTIVE_RESPONSE.value,
    },
    "deep_understanding_judgment": {
        "phases": {"2I", "2J"},
        "description": "Deep understanding + judgment enables nuanced organizational reasoning",
        "behavior_type": EmergentBehaviorType.NOVEL_COMBINATION.value,
    },
}


class EmergenceEngine:
    """創発的パターンの検出・記録

    主な機能:
    1. detect_emergent_patterns: 強い相乗効果から創発パターンを検出
    2. record_behavior: 検出したパターンを記録
    3. get_emergent_behaviors: 記録済みパターンの取得
    4. assess_emergence_level: 組織の創発レベルを評価
    """

    def __init__(self, organization_id: str = ""):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

    def detect_emergent_patterns(
        self,
        edges: List[CapabilityEdge],
    ) -> List[EmergentBehavior]:
        """強い結合パターンから創発行動を検出"""
        detected: List[EmergentBehavior] = []

        # エッジから強い接続のフェーズペアを収集
        strong_connections: Dict[str, set] = {}
        for edge in edges:
            if edge.strength >= EMERGENCE_CONFIDENCE_THRESHOLD:
                if edge.source_phase not in strong_connections:
                    strong_connections[edge.source_phase] = set()
                strong_connections[edge.source_phase].add(edge.target_phase)

        # 既知パターンとの照合
        connected_phases = set()
        for src, targets in strong_connections.items():
            connected_phases.add(src)
            connected_phases.update(targets)

        for pattern_name, pattern_def in _KNOWN_EMERGENCE_PATTERNS.items():
            required_phases = pattern_def["phases"]
            if required_phases.issubset(connected_phases):
                # パターンに関与するエッジの平均強度を計算
                relevant_strengths = [
                    e.strength for e in edges
                    if e.source_phase in required_phases and e.target_phase in required_phases
                ]
                avg_confidence = (
                    sum(relevant_strengths) / len(relevant_strengths)
                    if relevant_strengths else 0.0
                )

                if avg_confidence >= EMERGENCE_CONFIDENCE_THRESHOLD:
                    detected.append(EmergentBehavior(
                        organization_id=self.organization_id,
                        behavior_type=pattern_def["behavior_type"],
                        description=pattern_def["description"],
                        involved_phases=sorted(required_phases),
                        confidence=round(avg_confidence, 4),
                        impact_score=round(avg_confidence * 0.8, 4),
                    ))

        return detected

    async def record_behavior(
        self,
        conn: Any,
        behavior: EmergentBehavior,
    ) -> EmergenceResult:
        """創発行動を記録"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE_BRAIN_EMERGENT_BEHAVIORS}
                    (organization_id, behavior_type, description,
                     involved_phases, confidence, impact_score, occurrence_count)
                    VALUES (:org_id, :btype, :desc,
                            :phases, :confidence, :impact, :count)
                """),
                {
                    "org_id": self.organization_id,
                    "btype": behavior.behavior_type,
                    "desc": behavior.description,
                    "phases": json.dumps(behavior.involved_phases),
                    "confidence": behavior.confidence,
                    "impact": behavior.impact_score,
                    "count": behavior.occurrence_count,
                },
            )
            logger.info(
                "Emergent behavior recorded: type=%s, phases=%s, confidence=%.4f",
                behavior.behavior_type, behavior.involved_phases, behavior.confidence,
            )
            return EmergenceResult(success=True, message="Behavior recorded")
        except Exception as e:
            logger.error("Failed to record emergent behavior: %s", e)
            return EmergenceResult(success=False, message=str(e))

    async def get_emergent_behaviors(
        self,
        conn: Any,
        limit: int = 20,
    ) -> List[EmergentBehavior]:
        """記録済み創発行動を取得"""
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT id, organization_id, behavior_type, description,
                           involved_phases, confidence, impact_score,
                           occurrence_count, created_at
                    FROM {TABLE_BRAIN_EMERGENT_BEHAVIORS}
                    WHERE organization_id = :org_id
                    ORDER BY confidence DESC, created_at DESC
                    LIMIT :limit
                """),
                {"org_id": self.organization_id, "limit": limit},
            )
            rows = result.fetchall()
            behaviors = []
            for row in rows:
                phases_raw = row[4]
                if isinstance(phases_raw, str):
                    phases = json.loads(phases_raw)
                elif isinstance(phases_raw, list):
                    phases = phases_raw
                else:
                    phases = []

                behaviors.append(EmergentBehavior(
                    id=str(row[0]),
                    organization_id=str(row[1]),
                    behavior_type=row[2],
                    description=row[3] or "",
                    involved_phases=phases,
                    confidence=float(row[5]) if row[5] else 0.0,
                    impact_score=float(row[6]) if row[6] else 0.0,
                    occurrence_count=int(row[7]) if row[7] else 0,
                    created_at=row[8],
                ))
            return behaviors
        except Exception as e:
            logger.warning("Failed to get emergent behaviors: %s", e)
            return []

    def assess_emergence_level(
        self,
        behaviors: List[EmergentBehavior],
    ) -> Dict[str, Any]:
        """組織の創発レベルを評価

        Returns:
            {"level": str, "score": float, "pattern_count": int, "top_patterns": [...]}
        """
        if not behaviors:
            return {
                "level": "none",
                "score": 0.0,
                "pattern_count": 0,
                "top_patterns": [],
            }

        avg_confidence = sum(b.confidence for b in behaviors) / len(behaviors)
        pattern_count = len(behaviors)

        # レベル判定
        if avg_confidence >= 0.8 and pattern_count >= 5:
            level = "advanced"
        elif avg_confidence >= 0.6 and pattern_count >= 3:
            level = "intermediate"
        elif pattern_count >= 1:
            level = "basic"
        else:
            level = "none"

        top_patterns = [
            {
                "type": b.behavior_type,
                "phases": b.involved_phases,
                "confidence": b.confidence,
            }
            for b in sorted(behaviors, key=lambda x: x.confidence, reverse=True)[:3]
        ]

        return {
            "level": level,
            "score": round(avg_confidence, 4),
            "pattern_count": pattern_count,
            "top_patterns": top_patterns,
        }


def create_emergence_engine(organization_id: str = "") -> EmergenceEngine:
    """EmergenceEngineのファクトリ関数"""
    return EmergenceEngine(organization_id=organization_id)
