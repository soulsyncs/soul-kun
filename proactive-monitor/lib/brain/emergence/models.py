"""
Phase 2O: 創発（Emergence）データモデル

PII保護: 組織メタデータ・能力スコアのみ。個人データは含まない。
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class CapabilityEdge:
    """能力間の関係エッジ

    PII: 含まない（能力タイプ・強度のみ）
    """
    id: str = ""
    organization_id: str = ""
    source_phase: str = ""     # e.g. "2E"
    target_phase: str = ""     # e.g. "2G"
    integration_type: str = "synergy"
    strength: float = 0.5
    status: str = "active"
    evidence_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "source_phase": self.source_phase,
            "target_phase": self.target_phase,
            "integration_type": self.integration_type,
            "strength": self.strength,
            "status": self.status,
            "evidence_count": self.evidence_count,
        }


@dataclass
class EmergentBehavior:
    """創発的に検出された行動パターン

    PII: 含まない（パターンタイプ・スコアのみ）
    """
    id: str = ""
    organization_id: str = ""
    behavior_type: str = "novel_combination"
    description: str = ""        # パターンの説明（PII含まない、機能的記述のみ）
    involved_phases: List[str] = field(default_factory=list)  # e.g. ["2E", "2G", "2J"]
    confidence: float = 0.0
    impact_score: float = 0.0
    occurrence_count: int = 1
    created_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "behavior_type": self.behavior_type,
            "description": self.description,
            "involved_phases": self.involved_phases,
            "confidence": self.confidence,
            "impact_score": self.impact_score,
            "occurrence_count": self.occurrence_count,
        }


@dataclass
class StrategicInsight:
    """戦略的インサイト

    PII: 含まない（カテゴリ・スコアのみ）
    """
    id: str = ""
    organization_id: str = ""
    insight_type: str = "opportunity"
    title: str = ""
    description: str = ""
    relevance_score: float = 0.0
    source_phases: List[str] = field(default_factory=list)
    actionable: bool = False
    created_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "insight_type": self.insight_type,
            "title": self.title,
            "description": self.description,
            "relevance_score": self.relevance_score,
            "source_phases": self.source_phases,
            "actionable": self.actionable,
        }


@dataclass
class OrgSnapshot:
    """組織状態のスナップショット

    PII: 含まない（集計メトリクスのみ）
    """
    id: str = ""
    organization_id: str = ""
    capability_scores: Dict[str, float] = field(default_factory=dict)  # phase -> score
    overall_score: float = 0.0
    active_edges: int = 0
    emergent_count: int = 0
    insight_count: int = 0
    status: str = "active"
    created_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "capability_scores": self.capability_scores,
            "overall_score": self.overall_score,
            "active_edges": self.active_edges,
            "emergent_count": self.emergent_count,
            "insight_count": self.insight_count,
            "status": self.status,
        }


@dataclass
class EmergenceResult:
    """操作結果"""
    success: bool = False
    message: str = ""
    data: Optional[Dict[str, Any]] = None
