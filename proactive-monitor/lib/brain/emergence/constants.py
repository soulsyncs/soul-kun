"""
Phase 2O: 創発（Emergence）定数定義

設計: 全Phase 2E-2Nの能力を統合し、創発的問題解決を実現する。
"""

from enum import Enum


# =============================================================================
# テーブル名
# =============================================================================

TABLE_BRAIN_CAPABILITY_GRAPH = "brain_capability_graph"
TABLE_BRAIN_EMERGENT_BEHAVIORS = "brain_emergent_behaviors"
TABLE_BRAIN_STRATEGIC_INSIGHTS = "brain_strategic_insights"
TABLE_BRAIN_ORG_SNAPSHOTS = "brain_org_snapshots"


# =============================================================================
# Feature Flags
# =============================================================================

FEATURE_FLAG_EMERGENCE_ENABLED = "ENABLE_EMERGENCE"
FEATURE_FLAG_STRATEGIC_ADVISOR_ENABLED = "ENABLE_STRATEGIC_ADVISOR"


# =============================================================================
# Phase IDs（統合対象の全能力フェーズ）
# =============================================================================

class PhaseID(str, Enum):
    """Brain Phase識別子"""
    PHASE_2E = "2E"  # 結果からの学習
    PHASE_2F = "2F"  # 結果予測
    PHASE_2G = "2G"  # エピソード記憶
    PHASE_2H = "2H"  # 自己認識
    PHASE_2I = "2I"  # 深い理解
    PHASE_2J = "2J"  # 判断力
    PHASE_2K = "2K"  # 能動行動
    PHASE_2L = "2L"  # 実行管理
    PHASE_2M = "2M"  # 対人力
    PHASE_2N = "2N"  # 自己最適化


# =============================================================================
# Enums
# =============================================================================

class IntegrationType(str, Enum):
    """能力間の統合タイプ"""
    SYNERGY = "synergy"           # 相乗効果（1+1>2）
    DEPENDENCY = "dependency"     # 依存関係（AがBに必要）
    AMPLIFICATION = "amplification"  # 増幅（Aの効果をBが強化）
    COMPLEMENT = "complement"     # 補完（AとBが互いに補う）


class InsightType(str, Enum):
    """戦略的インサイトのタイプ"""
    OPPORTUNITY = "opportunity"   # 改善機会
    RISK = "risk"                 # リスク検知
    TREND = "trend"               # トレンド変化
    RECOMMENDATION = "recommendation"  # 戦略提案
    PREDICTION = "prediction"     # 将来予測


class EmergentBehaviorType(str, Enum):
    """創発行動のタイプ"""
    NOVEL_COMBINATION = "novel_combination"     # 新しい能力組み合わせ
    UNEXPECTED_PATTERN = "unexpected_pattern"   # 予想外のパターン
    ADAPTIVE_RESPONSE = "adaptive_response"     # 適応的応答
    CROSS_DOMAIN = "cross_domain"               # 領域横断的発見


class SnapshotStatus(str, Enum):
    """組織スナップショットのステータス"""
    ACTIVE = "active"
    ARCHIVED = "archived"


class EdgeStatus(str, Enum):
    """能力グラフのエッジステータス"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    HYPOTHESIZED = "hypothesized"


# =============================================================================
# 閾値・設定
# =============================================================================

# 能力グラフ
EDGE_STRENGTH_MIN = 0.0
EDGE_STRENGTH_MAX = 1.0
EDGE_STRENGTH_DEFAULT = 0.5
STRONG_EDGE_THRESHOLD = 0.7   # 強い結合と見なす閾値
WEAK_EDGE_THRESHOLD = 0.3     # 弱い結合と見なす閾値

# 創発行動
EMERGENCE_CONFIDENCE_THRESHOLD = 0.6  # 創発と認定する信頼度
MAX_EMERGENT_BEHAVIORS_PER_ORG = 100  # 組織ごとの最大保存数

# 戦略的インサイト
INSIGHT_RELEVANCE_THRESHOLD = 0.5     # 関連性が高いとする閾値
MAX_INSIGHTS_PER_ANALYSIS = 10        # 1回の分析で生成する最大数
PREDICTION_HORIZON_DAYS = 180         # 予測の最大期間（日）

# スナップショット
SNAPSHOT_RETENTION_DAYS = 365  # スナップショット保持期間
