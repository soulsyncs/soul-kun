"""
Phase 2M: 対人力強化（Interpersonal Skills）- 定数定義

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2M

コミュニケーションスタイル適応、動機付け、助言、対立調停に関する定数とEnum定義。
"""

from enum import Enum


# ============================================================================
# テーブル名
# ============================================================================

TABLE_BRAIN_COMMUNICATION_PROFILES = "brain_communication_profiles"
TABLE_BRAIN_MOTIVATION_PROFILES = "brain_motivation_profiles"
TABLE_BRAIN_FEEDBACK_OPPORTUNITIES = "brain_feedback_opportunities"
TABLE_BRAIN_CONFLICT_LOGS = "brain_conflict_logs"


# ============================================================================
# コミュニケーションスタイル Enum
# ============================================================================

class InterpersonalStyleType(str, Enum):
    """対人コミュニケーションスタイルの種別

    Note: lib/brain/org_graph.py の CommunicationStyle とは異なる。
    こちらはPhase 2M固有の詳細なスタイル分類。
    """
    BRIEF = "brief"              # 簡潔（要点だけ）
    DETAILED = "detailed"        # 詳細（背景含む）
    BALANCED = "balanced"        # バランス型

    FORMAL = "formal"            # 敬語・丁寧
    CASUAL = "casual"            # フランク
    ADAPTIVE = "adaptive"        # 相手に合わせる


class PreferredTiming(str, Enum):
    """好ましいコミュニケーションタイミング"""
    MORNING = "morning"          # 朝 (9:00-12:00)
    AFTERNOON = "afternoon"      # 午後 (12:00-17:00)
    EVENING = "evening"          # 夕方以降 (17:00-)
    ANYTIME = "anytime"          # いつでもOK


# ============================================================================
# モチベーション Enum
# ============================================================================

class MotivationType(str, Enum):
    """モチベーションの源泉タイプ"""
    ACHIEVEMENT = "achievement"    # 達成志向（成果・目標達成で動く）
    AFFILIATION = "affiliation"    # 親和志向（チーム・仲間で動く）
    AUTONOMY = "autonomy"          # 自律志向（裁量・自由で動く）
    GROWTH = "growth"              # 成長志向（学び・スキルアップで動く）
    IMPACT = "impact"              # 影響志向（社会貢献・インパクトで動く）
    STABILITY = "stability"        # 安定志向（安心・安定で動く）


class DiscouragementSignal(str, Enum):
    """落ち込みを示すシグナルの種別"""
    DELAYED_RESPONSE = "delayed_response"        # 返信遅延
    SHORT_RESPONSE = "short_response"            # 返信が短い
    TASK_AVOIDANCE = "task_avoidance"            # タスク回避
    NEGATIVE_LANGUAGE = "negative_language"       # ネガティブな言葉遣い
    REDUCED_ACTIVITY = "reduced_activity"         # 活動量低下
    MISSED_DEADLINE = "missed_deadline"           # 期限超過


# ============================================================================
# フィードバック Enum
# ============================================================================

class FeedbackType(str, Enum):
    """フィードバック（助言）の種別"""
    PRAISE = "praise"              # 称賛
    CONSTRUCTIVE = "constructive"  # 建設的フィードバック
    CORRECTION = "correction"      # 修正・指摘
    COUNSEL = "counsel"            # 助言・相談


class ReceptivenessLevel(str, Enum):
    """フィードバック受容度レベル"""
    HIGH = "high"        # 受容しやすい状態 (0.7-1.0)
    MEDIUM = "medium"    # 普通 (0.4-0.7)
    LOW = "low"          # 受容しにくい状態 (0.0-0.4)


# ============================================================================
# 対立 Enum
# ============================================================================

class ConflictSeverity(str, Enum):
    """対立の深刻度"""
    LOW = "low"          # 軽微（意見の違い程度）
    MEDIUM = "medium"    # 中程度（感情的な対立あり）
    HIGH = "high"        # 深刻（業務に支障）


class ConflictStatus(str, Enum):
    """対立の対応ステータス"""
    DETECTED = "detected"        # 検出済み
    MONITORING = "monitoring"    # 監視中
    MEDIATING = "mediating"      # 調停中
    RESOLVED = "resolved"        # 解決済み
    ESCALATED = "escalated"      # エスカレーション済み


# ============================================================================
# 閾値・デフォルト値
# ============================================================================

# 受容度スコア閾値
RECEPTIVENESS_HIGH_THRESHOLD = 0.7
RECEPTIVENESS_LOW_THRESHOLD = 0.4

# 落ち込み検知の信頼度閾値
DISCOURAGEMENT_CONFIDENCE_THRESHOLD = 0.6

# フィードバックの最小間隔（時間）
MIN_FEEDBACK_INTERVAL_HOURS = 4

# 対立検知の最小エビデンス数
CONFLICT_MIN_EVIDENCE_COUNT = 3

# 動機付けプロファイルの最小サンプル数
MOTIVATION_MIN_SAMPLE_COUNT = 5

# コミュニケーションプロファイルのデフォルト更新重み
PROFILE_UPDATE_WEIGHT = 0.2

# ============================================================================
# Feature Flags
# ============================================================================

FEATURE_FLAG_INTERPERSONAL_ENABLED = "ENABLE_INTERPERSONAL"
FEATURE_FLAG_COUNSEL_ENABLED = "ENABLE_COUNSEL"
FEATURE_FLAG_MOTIVATION_ENABLED = "ENABLE_MOTIVATION"
FEATURE_FLAG_CONFLICT_DETECTION_ENABLED = "ENABLE_CONFLICT_DETECTION"
