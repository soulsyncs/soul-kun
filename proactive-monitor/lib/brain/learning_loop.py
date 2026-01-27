# lib/brain/learning_loop.py
"""
ソウルくんの脳 - 真の学習ループ（Learning Loop）

Ultimate Brain Phase 3: フィードバックから実際に判断を改善する学習システム

設計思想:
- フィードバックを受け取って何が問題だったか分析
- 具体的な改善策を生成（閾値調整、パターン追加、キーワード更新）
- 改善を実際に適用して次回以降の判断を向上
- 学習履歴を記録して効果を測定

学習サイクル:
    判断 → 実行 → フィードバック → 分析 → 改善 → 次の判断

設計書: docs/19_ultimate_brain_architecture.md セクション5.1
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from uuid import uuid4

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================

# 学習履歴の保持期間（日）
LEARNING_HISTORY_RETENTION_DAYS: int = 180

# 改善適用の最小サンプル数
MIN_SAMPLES_FOR_IMPROVEMENT: int = 3

# 閾値調整の最小/最大値
THRESHOLD_MIN: float = 0.3
THRESHOLD_MAX: float = 0.95

# 閾値調整の単位
THRESHOLD_ADJUSTMENT_STEP: float = 0.05

# パターン追加時の最小確信度
PATTERN_MIN_CONFIDENCE: float = 0.6

# キーワード重みの初期値
DEFAULT_KEYWORD_WEIGHT: float = 1.0

# 学習ログバッファサイズ
LEARNING_LOG_BUFFER_SIZE: int = 20

# 分析時に参照する過去の判断数
ANALYSIS_DECISION_LOOKBACK: int = 50

# 効果測定の期間（日）
EFFECTIVENESS_MEASUREMENT_DAYS: int = 14


# =============================================================================
# 列挙型
# =============================================================================

class FeedbackType(str, Enum):
    """フィードバックの種類"""

    POSITIVE = "positive"           # 正しい判断だった
    NEGATIVE = "negative"           # 誤った判断だった
    CORRECTION = "correction"       # 修正された（正解を教えてもらった）
    CLARIFICATION = "clarification" # 曖昧さの解消
    PREFERENCE = "preference"       # ユーザーの好み
    SUGGESTION = "suggestion"       # 改善提案


class FailureCause(str, Enum):
    """失敗の原因カテゴリ"""

    INTENT_MISUNDERSTANDING = "intent_misunderstanding"   # 意図の誤解
    CONTEXT_MISSING = "context_missing"                   # コンテキスト不足
    THRESHOLD_WRONG = "threshold_wrong"                   # 閾値の問題
    PATTERN_UNKNOWN = "pattern_unknown"                   # パターン未学習
    KEYWORD_MISSING = "keyword_missing"                   # キーワード不足
    ENTITY_UNRESOLVED = "entity_unresolved"               # エンティティ解決失敗
    PARAMETER_WRONG = "parameter_wrong"                   # パラメータ誤り
    ACTION_WRONG = "action_wrong"                         # アクション選択誤り
    TIMING_WRONG = "timing_wrong"                         # タイミングの問題
    MULTIPLE_FACTORS = "multiple_factors"                 # 複合要因
    UNKNOWN = "unknown"                                   # 原因不明


class ImprovementType(str, Enum):
    """改善の種類"""

    THRESHOLD_ADJUSTMENT = "threshold_adjustment"   # 確信度閾値の調整
    PATTERN_ADDITION = "pattern_addition"           # パターンの追加
    KEYWORD_UPDATE = "keyword_update"               # キーワードマッピングの更新
    WEIGHT_ADJUSTMENT = "weight_adjustment"         # 重み付けの調整
    RULE_ADDITION = "rule_addition"                 # ルールの追加
    EXCEPTION_ADDITION = "exception_addition"       # 例外ケースの追加
    CONFIRMATION_RULE = "confirmation_rule"         # 確認ルールの追加


class LearningStatus(str, Enum):
    """学習の状態"""

    PENDING = "pending"             # 適用待ち
    APPLIED = "applied"             # 適用済み
    EFFECTIVE = "effective"         # 効果確認済み
    INEFFECTIVE = "ineffective"     # 効果なし
    REVERTED = "reverted"           # 取り消し


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class Feedback:
    """
    ユーザーからのフィードバック
    """
    # 識別情報
    id: str = field(default_factory=lambda: str(uuid4()))
    decision_id: str = ""

    # フィードバック内容
    feedback_type: FeedbackType = FeedbackType.NEGATIVE
    message: str = ""                          # フィードバックのメッセージ

    # 修正情報（correction の場合）
    correct_action: Optional[str] = None       # 正しかったアクション
    correct_params: Optional[Dict[str, Any]] = None
    correct_intent: Optional[str] = None       # 正しかった意図

    # コンテキスト
    room_id: str = ""
    user_id: str = ""
    original_message: str = ""                 # 元のユーザーメッセージ

    # メタデータ
    confidence: float = 1.0                    # フィードバックの確信度
    source: str = "user"                       # user, system, auto
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class DecisionSnapshot:
    """
    判断時点のスナップショット（分析用）
    """
    # 識別情報
    decision_id: str = ""

    # 入力
    user_message: str = ""
    room_id: str = ""
    user_id: str = ""

    # 理解層の結果
    detected_intent: str = ""
    intent_confidence: float = 0.0
    detected_entities: Dict[str, Any] = field(default_factory=dict)

    # 判断層の結果
    selected_action: str = ""
    action_confidence: float = 0.0
    action_params: Dict[str, Any] = field(default_factory=dict)
    alternative_actions: List[str] = field(default_factory=list)

    # 実行結果
    execution_success: bool = False
    response_message: str = ""

    # コンテキスト
    context_summary: str = ""                  # コンテキストの要約
    state_type: str = "normal"

    # タイミング
    created_at: datetime = field(default_factory=datetime.now)
    processing_time_ms: int = 0


@dataclass
class FailureAnalysis:
    """
    失敗の分析結果
    """
    # 主要な原因
    primary_cause: FailureCause = FailureCause.UNKNOWN
    cause_confidence: float = 0.0
    cause_explanation: str = ""

    # 副次的な原因
    secondary_causes: List[FailureCause] = field(default_factory=list)

    # 具体的な問題点
    issues: List[str] = field(default_factory=list)

    # 関連する過去の失敗
    similar_failures: List[str] = field(default_factory=list)  # decision_ids

    # 分析の詳細
    intent_analysis: Optional[str] = None      # 意図理解の分析
    action_analysis: Optional[str] = None      # アクション選択の分析
    context_analysis: Optional[str] = None     # コンテキストの分析

    # 統計情報
    failure_rate_for_pattern: float = 0.0      # このパターンの失敗率
    total_similar_cases: int = 0

    # メタデータ
    analysis_time_ms: int = 0
    analyzed_at: datetime = field(default_factory=datetime.now)


@dataclass
class Improvement:
    """
    生成された改善策
    """
    # 識別情報
    id: str = field(default_factory=lambda: str(uuid4()))

    # 改善内容
    improvement_type: ImprovementType = ImprovementType.PATTERN_ADDITION
    description: str = ""

    # 適用対象
    target_action: Optional[str] = None        # 対象のアクション
    target_intent: Optional[str] = None        # 対象の意図
    target_pattern: Optional[str] = None       # 対象のパターン

    # 改善の詳細（タイプ別）
    # THRESHOLD_ADJUSTMENT
    old_threshold: Optional[float] = None
    new_threshold: Optional[float] = None

    # PATTERN_ADDITION
    pattern_regex: Optional[str] = None
    pattern_examples: List[str] = field(default_factory=list)

    # KEYWORD_UPDATE
    keywords_to_add: List[str] = field(default_factory=list)
    keywords_to_remove: List[str] = field(default_factory=list)
    keyword_weights: Dict[str, float] = field(default_factory=dict)

    # WEIGHT_ADJUSTMENT
    weight_changes: Dict[str, float] = field(default_factory=dict)

    # RULE_ADDITION / EXCEPTION_ADDITION
    rule_condition: Optional[str] = None
    rule_action: Optional[str] = None

    # 優先度と状態
    priority: int = 5                          # 1-10（高いほど優先）
    status: LearningStatus = LearningStatus.PENDING

    # 効果測定
    expected_improvement: float = 0.0          # 期待される改善率
    actual_improvement: Optional[float] = None # 実際の改善率

    # ソース情報
    source_feedback_id: str = ""
    source_analysis_id: str = ""

    # メタデータ
    created_at: datetime = field(default_factory=datetime.now)
    applied_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "improvement_type": self.improvement_type.value,
            "description": self.description,
            "target_action": self.target_action,
            "target_intent": self.target_intent,
            "target_pattern": self.target_pattern,
            "old_threshold": self.old_threshold,
            "new_threshold": self.new_threshold,
            "pattern_regex": self.pattern_regex,
            "pattern_examples": self.pattern_examples,
            "keywords_to_add": self.keywords_to_add,
            "keywords_to_remove": self.keywords_to_remove,
            "keyword_weights": self.keyword_weights,
            "priority": self.priority,
            "status": self.status.value,
            "expected_improvement": self.expected_improvement,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class LearningEntry:
    """
    学習ログエントリ
    """
    # 識別情報
    id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: str = ""

    # 関連ID
    decision_id: str = ""
    feedback_id: str = ""

    # 分析結果
    failure_cause: FailureCause = FailureCause.UNKNOWN
    cause_explanation: str = ""

    # 適用された改善
    improvements: List[Improvement] = field(default_factory=list)

    # 効果測定
    baseline_success_rate: float = 0.0         # 改善前の成功率
    post_improvement_success_rate: Optional[float] = None  # 改善後の成功率
    improvement_verified: bool = False

    # メタデータ
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class LearningStatistics:
    """
    学習の統計情報
    """
    # 期間
    period_days: int = 7

    # フィードバック統計
    total_feedbacks: int = 0
    positive_feedbacks: int = 0
    negative_feedbacks: int = 0
    correction_feedbacks: int = 0

    # 学習統計
    total_learnings: int = 0
    applied_improvements: int = 0
    effective_improvements: int = 0
    reverted_improvements: int = 0

    # 原因分布
    cause_distribution: Dict[str, int] = field(default_factory=dict)

    # 改善タイプ分布
    improvement_type_distribution: Dict[str, int] = field(default_factory=dict)

    # 効果
    average_improvement_rate: float = 0.0      # 平均改善率
    success_rate_before: float = 0.0
    success_rate_after: float = 0.0

    # 計算日時
    calculated_at: datetime = field(default_factory=datetime.now)


# =============================================================================
# LearningLoop クラス
# =============================================================================

class LearningLoop:
    """
    真の学習ループ

    フィードバックから学習し、判断を改善するシステム。

    学習サイクル:
    1. フィードバック受信
    2. 元の判断を取得
    3. 何が問題だったか分析
    4. 改善策を生成
    5. 改善を適用
    6. 学習ログを記録
    7. 効果を測定

    Attributes:
        pool: データベース接続プール
        organization_id: 組織ID
        enable_auto_apply: 改善を自動適用するか
        enable_effectiveness_tracking: 効果測定を有効にするか
    """

    def __init__(
        self,
        pool=None,
        organization_id: str = "",
        enable_auto_apply: bool = True,
        enable_effectiveness_tracking: bool = True,
    ):
        """
        LearningLoop を初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            enable_auto_apply: 改善を自動適用するか
            enable_effectiveness_tracking: 効果測定を有効にするか
        """
        self.pool = pool
        self.organization_id = organization_id
        self.enable_auto_apply = enable_auto_apply
        self.enable_effectiveness_tracking = enable_effectiveness_tracking

        # キャッシュ
        self._decision_cache: Dict[str, DecisionSnapshot] = {}
        self._improvement_cache: Dict[str, Improvement] = {}
        self._learning_buffer: List[LearningEntry] = []

        # 適用済み改善（メモリ内）
        self._applied_thresholds: Dict[str, float] = {}
        self._applied_patterns: Dict[str, List[str]] = {}  # action -> patterns
        self._applied_keywords: Dict[str, Dict[str, float]] = {}  # action -> {keyword: weight}

        logger.debug(
            f"LearningLoop initialized: "
            f"org_id={organization_id}, "
            f"auto_apply={enable_auto_apply}, "
            f"effectiveness_tracking={enable_effectiveness_tracking}"
        )

    # =========================================================================
    # メイン学習フロー
    # =========================================================================

    async def learn_from_feedback(
        self,
        decision_id: str,
        feedback: Feedback,
    ) -> List[Improvement]:
        """
        フィードバックから学習

        Args:
            decision_id: 判断のID
            feedback: フィードバック

        Returns:
            適用された改善策のリスト
        """
        try:
            logger.info(
                f"[LearningLoop] Learning from feedback: "
                f"decision_id={decision_id}, "
                f"type={feedback.feedback_type.value}"
            )

            # 1. 元の判断を取得
            decision = await self._get_decision(decision_id)
            if not decision:
                logger.warning(f"[LearningLoop] Decision not found: {decision_id}")
                return []

            # 2. ポジティブフィードバックの場合は強化学習
            if feedback.feedback_type == FeedbackType.POSITIVE:
                await self._reinforce_successful_pattern(decision, feedback)
                return []

            # 3. 失敗の分析
            analysis = await self._analyze_failure(decision, feedback)

            # 4. 改善策の生成
            improvements = await self._generate_improvements(analysis, decision, feedback)

            if not improvements:
                logger.info("[LearningLoop] No improvements generated")
                return []

            # 5. 改善を適用
            if self.enable_auto_apply:
                for improvement in improvements:
                    await self._apply_improvement(improvement)

            # 6. 学習ログを記録
            await self._log_learning(
                decision_id=decision_id,
                feedback=feedback,
                analysis=analysis,
                improvements=improvements,
            )

            logger.info(
                f"[LearningLoop] Learning completed: "
                f"{len(improvements)} improvements generated"
            )

            return improvements

        except Exception as e:
            logger.error(f"[LearningLoop] Error learning from feedback: {e}")
            return []

    async def record_decision(
        self,
        decision_id: str,
        snapshot: DecisionSnapshot,
    ) -> bool:
        """
        判断をキャッシュに記録

        Args:
            decision_id: 判断ID
            snapshot: 判断のスナップショット

        Returns:
            記録に成功したか
        """
        try:
            self._decision_cache[decision_id] = snapshot

            # キャッシュサイズを制限
            if len(self._decision_cache) > 1000:
                # 古いエントリを削除
                oldest_keys = sorted(
                    self._decision_cache.keys(),
                    key=lambda k: self._decision_cache[k].created_at
                )[:500]
                for key in oldest_keys:
                    del self._decision_cache[key]

            return True

        except Exception as e:
            logger.error(f"[LearningLoop] Error recording decision: {e}")
            return False

    # =========================================================================
    # 判断取得
    # =========================================================================

    async def _get_decision(self, decision_id: str) -> Optional[DecisionSnapshot]:
        """
        判断を取得

        Args:
            decision_id: 判断ID

        Returns:
            判断のスナップショット（見つからない場合はNone）
        """
        # キャッシュから検索
        if decision_id in self._decision_cache:
            return self._decision_cache[decision_id]

        # DBから検索
        if self.pool:
            try:
                # TODO: DBからの取得実装
                pass
            except Exception as e:
                logger.warning(f"[LearningLoop] Error fetching decision from DB: {e}")

        return None

    # =========================================================================
    # 失敗分析
    # =========================================================================

    async def _analyze_failure(
        self,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> FailureAnalysis:
        """
        失敗を分析

        Args:
            decision: 判断のスナップショット
            feedback: フィードバック

        Returns:
            失敗の分析結果
        """
        import time
        start_time = time.time()

        analysis = FailureAnalysis()
        issues: List[str] = []

        # 1. 意図理解の分析
        intent_cause = self._analyze_intent_understanding(decision, feedback)
        if intent_cause:
            if not analysis.primary_cause or analysis.primary_cause == FailureCause.UNKNOWN:
                analysis.primary_cause = intent_cause
                analysis.cause_confidence = 0.8
            else:
                analysis.secondary_causes.append(intent_cause)

            analysis.intent_analysis = (
                f"検出された意図: {decision.detected_intent} "
                f"(確信度: {decision.intent_confidence:.2f})"
            )
            if feedback.correct_intent:
                analysis.intent_analysis += f", 正しい意図: {feedback.correct_intent}"
                issues.append(f"意図を誤解: {decision.detected_intent} → {feedback.correct_intent}")

        # 2. アクション選択の分析
        action_cause = self._analyze_action_selection(decision, feedback)
        if action_cause:
            if not analysis.primary_cause or analysis.primary_cause == FailureCause.UNKNOWN:
                analysis.primary_cause = action_cause
                analysis.cause_confidence = 0.7
            else:
                analysis.secondary_causes.append(action_cause)

            analysis.action_analysis = (
                f"選択されたアクション: {decision.selected_action} "
                f"(確信度: {decision.action_confidence:.2f})"
            )
            if feedback.correct_action:
                analysis.action_analysis += f", 正しいアクション: {feedback.correct_action}"
                issues.append(f"アクション誤り: {decision.selected_action} → {feedback.correct_action}")

        # 3. コンテキストの分析
        context_cause = self._analyze_context(decision, feedback)
        if context_cause:
            if not analysis.primary_cause or analysis.primary_cause == FailureCause.UNKNOWN:
                analysis.primary_cause = context_cause
                analysis.cause_confidence = 0.6
            else:
                analysis.secondary_causes.append(context_cause)

            analysis.context_analysis = f"コンテキスト: {decision.context_summary[:100]}"
            issues.append("コンテキストが不足または誤り")

        # 4. パターン分析（類似の失敗を検索）
        similar_failures = await self._find_similar_failures(decision)
        if similar_failures:
            analysis.similar_failures = similar_failures
            analysis.total_similar_cases = len(similar_failures)

        # 5. 原因不明の場合
        if analysis.primary_cause == FailureCause.UNKNOWN:
            analysis.cause_explanation = "具体的な原因を特定できませんでした"
        else:
            analysis.cause_explanation = self._generate_cause_explanation(
                analysis.primary_cause, decision, feedback
            )

        analysis.issues = issues
        analysis.analysis_time_ms = int((time.time() - start_time) * 1000)

        logger.debug(
            f"[LearningLoop] Failure analysis: "
            f"cause={analysis.primary_cause.value}, "
            f"confidence={analysis.cause_confidence:.2f}, "
            f"issues={len(issues)}"
        )

        return analysis

    def _analyze_intent_understanding(
        self,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> Optional[FailureCause]:
        """意図理解を分析"""
        # 正しい意図が指定されている場合
        if feedback.correct_intent and feedback.correct_intent != decision.detected_intent:
            return FailureCause.INTENT_MISUNDERSTANDING

        # 確信度が低い場合
        if decision.intent_confidence < 0.5:
            return FailureCause.INTENT_MISUNDERSTANDING

        return None

    def _analyze_action_selection(
        self,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> Optional[FailureCause]:
        """アクション選択を分析"""
        # 正しいアクションが指定されている場合
        if feedback.correct_action and feedback.correct_action != decision.selected_action:
            # 正しいアクションが代替候補にあった場合
            if feedback.correct_action in decision.alternative_actions:
                return FailureCause.THRESHOLD_WRONG  # 閾値の問題
            else:
                return FailureCause.PATTERN_UNKNOWN  # パターン未学習

        # 確信度が低い場合
        if decision.action_confidence < 0.5:
            return FailureCause.ACTION_WRONG

        return None

    def _analyze_context(
        self,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> Optional[FailureCause]:
        """コンテキストを分析"""
        # コンテキストが空の場合
        if not decision.context_summary:
            return FailureCause.CONTEXT_MISSING

        # フィードバックメッセージにコンテキスト関連のキーワードがある場合
        context_keywords = ["前の", "さっき", "続き", "それ", "あれ", "コンテキスト", "文脈"]
        feedback_lower = feedback.message.lower()

        for keyword in context_keywords:
            if keyword in feedback_lower:
                return FailureCause.CONTEXT_MISSING

        return None

    async def _find_similar_failures(
        self,
        decision: DecisionSnapshot,
    ) -> List[str]:
        """類似の失敗を検索"""
        similar_ids: List[str] = []

        # キャッシュから検索
        for decision_id, cached_decision in self._decision_cache.items():
            if decision_id == decision.decision_id:
                continue

            # 類似度チェック
            if self._is_similar_decision(decision, cached_decision):
                similar_ids.append(decision_id)

        return similar_ids[:10]  # 最大10件

    def _is_similar_decision(
        self,
        decision1: DecisionSnapshot,
        decision2: DecisionSnapshot,
    ) -> bool:
        """2つの判断が類似しているか"""
        # 同じアクションかつ同じ意図
        if (decision1.selected_action == decision2.selected_action and
            decision1.detected_intent == decision2.detected_intent):
            return True

        # メッセージの類似度（簡易版）
        words1 = set(decision1.user_message.split())
        words2 = set(decision2.user_message.split())

        if len(words1) == 0 or len(words2) == 0:
            return False

        overlap = len(words1 & words2)
        similarity = overlap / max(len(words1), len(words2))

        return similarity > 0.5

    def _generate_cause_explanation(
        self,
        cause: FailureCause,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> str:
        """原因の説明を生成"""
        explanations = {
            FailureCause.INTENT_MISUNDERSTANDING: (
                f"ユーザーの意図を誤解しました。"
                f"「{decision.user_message[:50]}」を「{decision.detected_intent}」と判断しましたが、"
                f"正しくは「{feedback.correct_intent or '別の意図'}」でした。"
            ),
            FailureCause.CONTEXT_MISSING: (
                f"会話のコンテキストが不足していました。"
                f"直前の会話や状態を考慮できませんでした。"
            ),
            FailureCause.THRESHOLD_WRONG: (
                f"確信度の閾値が不適切でした。"
                f"確信度{decision.action_confidence:.2f}で「{decision.selected_action}」を選択しましたが、"
                f"「{feedback.correct_action}」が正しかったです。"
            ),
            FailureCause.PATTERN_UNKNOWN: (
                f"このパターンは学習されていませんでした。"
                f"「{decision.user_message[:50]}」のような表現を認識できませんでした。"
            ),
            FailureCause.KEYWORD_MISSING: (
                f"キーワードが不足していました。"
                f"「{decision.user_message[:50]}」に含まれるキーワードを認識できませんでした。"
            ),
            FailureCause.ENTITY_UNRESOLVED: (
                f"エンティティ（人名、タスク名等）を解決できませんでした。"
            ),
            FailureCause.PARAMETER_WRONG: (
                f"パラメータが誤っていました。"
                f"アクション「{decision.selected_action}」のパラメータが不正確でした。"
            ),
            FailureCause.ACTION_WRONG: (
                f"アクション選択が誤っていました。"
                f"「{decision.selected_action}」ではなく「{feedback.correct_action or '別のアクション'}」でした。"
            ),
            FailureCause.TIMING_WRONG: (
                f"タイミングが不適切でした。"
            ),
            FailureCause.MULTIPLE_FACTORS: (
                f"複数の要因が絡み合っていました。"
            ),
            FailureCause.UNKNOWN: (
                f"原因を特定できませんでした。"
            ),
        }

        return explanations.get(cause, "原因不明")

    # =========================================================================
    # 改善生成
    # =========================================================================

    async def _generate_improvements(
        self,
        analysis: FailureAnalysis,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> List[Improvement]:
        """
        改善策を生成

        Args:
            analysis: 失敗の分析結果
            decision: 判断のスナップショット
            feedback: フィードバック

        Returns:
            改善策のリスト
        """
        improvements: List[Improvement] = []

        # 原因に基づいて改善策を生成
        if analysis.primary_cause == FailureCause.INTENT_MISUNDERSTANDING:
            improvement = self._generate_intent_improvement(analysis, decision, feedback)
            if improvement:
                improvements.append(improvement)

        elif analysis.primary_cause == FailureCause.THRESHOLD_WRONG:
            improvement = self._generate_threshold_improvement(analysis, decision, feedback)
            if improvement:
                improvements.append(improvement)

        elif analysis.primary_cause == FailureCause.PATTERN_UNKNOWN:
            improvement = self._generate_pattern_improvement(analysis, decision, feedback)
            if improvement:
                improvements.append(improvement)

        elif analysis.primary_cause == FailureCause.KEYWORD_MISSING:
            improvement = self._generate_keyword_improvement(analysis, decision, feedback)
            if improvement:
                improvements.append(improvement)

        elif analysis.primary_cause == FailureCause.CONTEXT_MISSING:
            improvement = self._generate_context_improvement(analysis, decision, feedback)
            if improvement:
                improvements.append(improvement)

        elif analysis.primary_cause == FailureCause.ACTION_WRONG:
            # アクション誤りは複数の改善が必要な場合がある
            pattern_improvement = self._generate_pattern_improvement(analysis, decision, feedback)
            if pattern_improvement:
                improvements.append(pattern_improvement)

            keyword_improvement = self._generate_keyword_improvement(analysis, decision, feedback)
            if keyword_improvement:
                improvements.append(keyword_improvement)

        # 副次的な原因に対する改善も生成
        for cause in analysis.secondary_causes[:2]:  # 最大2つ
            if cause == FailureCause.KEYWORD_MISSING:
                improvement = self._generate_keyword_improvement(analysis, decision, feedback)
                if improvement:
                    improvements.append(improvement)

        # 期待改善率を計算
        for improvement in improvements:
            improvement.expected_improvement = self._estimate_improvement_rate(improvement, analysis)
            improvement.source_feedback_id = feedback.id

        logger.debug(
            f"[LearningLoop] Generated {len(improvements)} improvements"
        )

        return improvements

    def _generate_intent_improvement(
        self,
        analysis: FailureAnalysis,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> Optional[Improvement]:
        """意図理解の改善を生成"""
        if not feedback.correct_intent:
            return None

        # パターン追加で対応
        return Improvement(
            improvement_type=ImprovementType.PATTERN_ADDITION,
            description=f"「{decision.user_message[:30]}」を「{feedback.correct_intent}」と認識するパターンを追加",
            target_intent=feedback.correct_intent,
            pattern_examples=[decision.user_message],
            priority=7,
        )

    def _generate_threshold_improvement(
        self,
        analysis: FailureAnalysis,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> Optional[Improvement]:
        """閾値調整の改善を生成"""
        # 正しいアクションが代替候補にある場合、閾値を下げる
        if feedback.correct_action and feedback.correct_action in decision.alternative_actions:
            current_threshold = self._applied_thresholds.get(
                decision.selected_action,
                decision.action_confidence
            )

            # 閾値を下げる（正しいアクションが選ばれやすくなる）
            new_threshold = max(
                THRESHOLD_MIN,
                current_threshold - THRESHOLD_ADJUSTMENT_STEP
            )

            if new_threshold != current_threshold:
                return Improvement(
                    improvement_type=ImprovementType.THRESHOLD_ADJUSTMENT,
                    description=f"「{decision.selected_action}」の閾値を{current_threshold:.2f}から{new_threshold:.2f}に調整",
                    target_action=decision.selected_action,
                    old_threshold=current_threshold,
                    new_threshold=new_threshold,
                    priority=6,
                )

        return None

    def _generate_pattern_improvement(
        self,
        analysis: FailureAnalysis,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> Optional[Improvement]:
        """パターン追加の改善を生成"""
        target_action = feedback.correct_action or decision.selected_action

        # メッセージからパターンを抽出
        pattern = self._extract_pattern_from_message(decision.user_message)

        if pattern:
            return Improvement(
                improvement_type=ImprovementType.PATTERN_ADDITION,
                description=f"「{target_action}」のパターンを追加",
                target_action=target_action,
                pattern_regex=pattern,
                pattern_examples=[decision.user_message],
                priority=8,
            )

        return None

    def _generate_keyword_improvement(
        self,
        analysis: FailureAnalysis,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> Optional[Improvement]:
        """キーワード更新の改善を生成"""
        target_action = feedback.correct_action or decision.selected_action

        # メッセージからキーワードを抽出
        keywords = self._extract_keywords_from_message(decision.user_message)

        if keywords:
            return Improvement(
                improvement_type=ImprovementType.KEYWORD_UPDATE,
                description=f"「{target_action}」のキーワードを追加: {', '.join(keywords[:3])}",
                target_action=target_action,
                keywords_to_add=keywords,
                keyword_weights={kw: DEFAULT_KEYWORD_WEIGHT for kw in keywords},
                priority=5,
            )

        return None

    def _generate_context_improvement(
        self,
        analysis: FailureAnalysis,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> Optional[Improvement]:
        """コンテキスト改善を生成"""
        # 確認ルールの追加
        return Improvement(
            improvement_type=ImprovementType.CONFIRMATION_RULE,
            description="コンテキストが不明な場合に確認を求めるルールを追加",
            rule_condition=f"intent == '{decision.detected_intent}' AND context_missing",
            rule_action="ask_for_clarification",
            priority=4,
        )

    def _extract_pattern_from_message(self, message: str) -> Optional[str]:
        """メッセージからパターンを抽出"""
        # 単純なパターン抽出（本格的な実装ではLLMを使用）
        # 変数部分を.*で置換

        # 数字を置換
        pattern = re.sub(r'\d+', r'\\d+', message)

        # 特殊文字をエスケープ
        special_chars = ['(', ')', '[', ']', '{', '}', '.', '*', '+', '?', '^', '$', '|', '\\']
        for char in special_chars:
            if char not in ['\\d', '+']:
                pattern = pattern.replace(char, f'\\{char}')

        # 空白を柔軟に
        pattern = re.sub(r'\s+', r'\\s*', pattern)

        if len(pattern) < 5:
            return None

        return pattern

    def _extract_keywords_from_message(self, message: str) -> List[str]:
        """メッセージからキーワードを抽出"""
        # ストップワード
        stop_words = {
            "の", "を", "に", "は", "が", "で", "と", "から", "まで", "へ",
            "です", "ます", "した", "して", "する", "これ", "それ", "あれ",
            "この", "その", "あの", "私", "僕", "俺", "あなた", "ウル",
        }

        # 単語分割（簡易版）
        words = re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]+', message)

        # フィルタリング
        keywords = []
        for word in words:
            if len(word) >= 2 and word not in stop_words:
                keywords.append(word)

        return keywords[:5]  # 最大5個

    def _estimate_improvement_rate(
        self,
        improvement: Improvement,
        analysis: FailureAnalysis,
    ) -> float:
        """改善の期待効果を推定"""
        base_rate = 0.0

        # タイプ別の基本効果
        type_effects = {
            ImprovementType.THRESHOLD_ADJUSTMENT: 0.15,
            ImprovementType.PATTERN_ADDITION: 0.25,
            ImprovementType.KEYWORD_UPDATE: 0.10,
            ImprovementType.WEIGHT_ADJUSTMENT: 0.10,
            ImprovementType.RULE_ADDITION: 0.20,
            ImprovementType.EXCEPTION_ADDITION: 0.15,
            ImprovementType.CONFIRMATION_RULE: 0.05,
        }

        base_rate = type_effects.get(improvement.improvement_type, 0.10)

        # 類似ケースが多い場合は効果増
        if analysis.total_similar_cases > 5:
            base_rate *= 1.5

        # 原因の確信度が高い場合は効果増
        base_rate *= (1 + analysis.cause_confidence * 0.5)

        return min(1.0, base_rate)

    # =========================================================================
    # 改善適用
    # =========================================================================

    async def _apply_improvement(self, improvement: Improvement) -> bool:
        """
        改善を適用

        Args:
            improvement: 改善策

        Returns:
            適用に成功したか
        """
        try:
            if improvement.improvement_type == ImprovementType.THRESHOLD_ADJUSTMENT:
                return await self._apply_threshold_adjustment(improvement)

            elif improvement.improvement_type == ImprovementType.PATTERN_ADDITION:
                return await self._apply_pattern_addition(improvement)

            elif improvement.improvement_type == ImprovementType.KEYWORD_UPDATE:
                return await self._apply_keyword_update(improvement)

            elif improvement.improvement_type == ImprovementType.WEIGHT_ADJUSTMENT:
                return await self._apply_weight_adjustment(improvement)

            elif improvement.improvement_type == ImprovementType.RULE_ADDITION:
                return await self._apply_rule_addition(improvement)

            elif improvement.improvement_type == ImprovementType.EXCEPTION_ADDITION:
                return await self._apply_exception_addition(improvement)

            elif improvement.improvement_type == ImprovementType.CONFIRMATION_RULE:
                return await self._apply_confirmation_rule(improvement)

            else:
                logger.warning(
                    f"[LearningLoop] Unknown improvement type: {improvement.improvement_type}"
                )
                return False

        except Exception as e:
            logger.error(f"[LearningLoop] Error applying improvement: {e}")
            return False

    async def _apply_threshold_adjustment(self, improvement: Improvement) -> bool:
        """閾値調整を適用"""
        if improvement.target_action and improvement.new_threshold is not None:
            self._applied_thresholds[improvement.target_action] = improvement.new_threshold
            improvement.status = LearningStatus.APPLIED
            improvement.applied_at = datetime.now()

            logger.info(
                f"[LearningLoop] Threshold adjusted: "
                f"{improvement.target_action} = {improvement.new_threshold:.2f}"
            )

            return True

        return False

    async def _apply_pattern_addition(self, improvement: Improvement) -> bool:
        """パターン追加を適用"""
        target = improvement.target_action or improvement.target_intent

        if target and improvement.pattern_regex:
            if target not in self._applied_patterns:
                self._applied_patterns[target] = []

            self._applied_patterns[target].append(improvement.pattern_regex)
            improvement.status = LearningStatus.APPLIED
            improvement.applied_at = datetime.now()

            logger.info(
                f"[LearningLoop] Pattern added: "
                f"{target} += {improvement.pattern_regex[:30]}..."
            )

            return True

        return False

    async def _apply_keyword_update(self, improvement: Improvement) -> bool:
        """キーワード更新を適用"""
        if improvement.target_action and improvement.keywords_to_add:
            if improvement.target_action not in self._applied_keywords:
                self._applied_keywords[improvement.target_action] = {}

            for keyword in improvement.keywords_to_add:
                weight = improvement.keyword_weights.get(keyword, DEFAULT_KEYWORD_WEIGHT)
                self._applied_keywords[improvement.target_action][keyword] = weight

            for keyword in improvement.keywords_to_remove:
                self._applied_keywords[improvement.target_action].pop(keyword, None)

            improvement.status = LearningStatus.APPLIED
            improvement.applied_at = datetime.now()

            logger.info(
                f"[LearningLoop] Keywords updated: "
                f"{improvement.target_action} += {improvement.keywords_to_add}"
            )

            return True

        return False

    async def _apply_weight_adjustment(self, improvement: Improvement) -> bool:
        """重み調整を適用"""
        # TODO: 実装
        improvement.status = LearningStatus.APPLIED
        improvement.applied_at = datetime.now()
        return True

    async def _apply_rule_addition(self, improvement: Improvement) -> bool:
        """ルール追加を適用"""
        # TODO: 実装
        improvement.status = LearningStatus.APPLIED
        improvement.applied_at = datetime.now()
        return True

    async def _apply_exception_addition(self, improvement: Improvement) -> bool:
        """例外追加を適用"""
        # TODO: 実装
        improvement.status = LearningStatus.APPLIED
        improvement.applied_at = datetime.now()
        return True

    async def _apply_confirmation_rule(self, improvement: Improvement) -> bool:
        """確認ルール追加を適用"""
        # TODO: 実装
        improvement.status = LearningStatus.APPLIED
        improvement.applied_at = datetime.now()
        return True

    # =========================================================================
    # 成功パターンの強化
    # =========================================================================

    async def _reinforce_successful_pattern(
        self,
        decision: DecisionSnapshot,
        feedback: Feedback,
    ) -> bool:
        """
        成功パターンを強化

        Args:
            decision: 判断のスナップショット
            feedback: フィードバック

        Returns:
            強化に成功したか
        """
        try:
            # キーワードの重みを増加
            if decision.selected_action in self._applied_keywords:
                keywords = self._extract_keywords_from_message(decision.user_message)
                for keyword in keywords:
                    if keyword in self._applied_keywords[decision.selected_action]:
                        current = self._applied_keywords[decision.selected_action][keyword]
                        self._applied_keywords[decision.selected_action][keyword] = min(
                            current * 1.1, 2.0
                        )

            logger.debug(
                f"[LearningLoop] Reinforced pattern: "
                f"action={decision.selected_action}"
            )

            return True

        except Exception as e:
            logger.warning(f"[LearningLoop] Error reinforcing pattern: {e}")
            return False

    # =========================================================================
    # 学習ログ
    # =========================================================================

    async def _log_learning(
        self,
        decision_id: str,
        feedback: Feedback,
        analysis: FailureAnalysis,
        improvements: List[Improvement],
    ) -> bool:
        """
        学習ログを記録

        Args:
            decision_id: 判断ID
            feedback: フィードバック
            analysis: 分析結果
            improvements: 改善策

        Returns:
            記録に成功したか
        """
        try:
            entry = LearningEntry(
                organization_id=self.organization_id,
                decision_id=decision_id,
                feedback_id=feedback.id,
                failure_cause=analysis.primary_cause,
                cause_explanation=analysis.cause_explanation,
                improvements=improvements,
            )

            self._learning_buffer.append(entry)

            # バッファサイズを超えたらフラッシュ
            if len(self._learning_buffer) >= LEARNING_LOG_BUFFER_SIZE:
                await self._flush_learning_buffer()

            logger.info(
                f"[LearningLoop] Learning logged: "
                f"cause={analysis.primary_cause.value}, "
                f"improvements={len(improvements)}"
            )

            return True

        except Exception as e:
            logger.error(f"[LearningLoop] Error logging learning: {e}")
            return False

    async def _flush_learning_buffer(self) -> int:
        """学習バッファをフラッシュ"""
        if not self._learning_buffer:
            return 0

        count = len(self._learning_buffer)

        # TODO: DBへの保存実装

        self._learning_buffer.clear()

        logger.debug(f"[LearningLoop] Flushed {count} learning entries")

        return count

    # =========================================================================
    # 統計情報
    # =========================================================================

    async def get_statistics(self, days: int = 7) -> LearningStatistics:
        """
        学習統計情報を取得

        Args:
            days: 統計対象の日数

        Returns:
            統計情報
        """
        stats = LearningStatistics(period_days=days)

        try:
            # バッファから統計を計算
            for entry in self._learning_buffer:
                stats.total_learnings += 1

                # 原因分布
                cause = entry.failure_cause.value
                stats.cause_distribution[cause] = stats.cause_distribution.get(cause, 0) + 1

                # 改善タイプ分布
                for improvement in entry.improvements:
                    imp_type = improvement.improvement_type.value
                    stats.improvement_type_distribution[imp_type] = (
                        stats.improvement_type_distribution.get(imp_type, 0) + 1
                    )

                    if improvement.status == LearningStatus.APPLIED:
                        stats.applied_improvements += 1
                    elif improvement.status == LearningStatus.EFFECTIVE:
                        stats.effective_improvements += 1
                    elif improvement.status == LearningStatus.REVERTED:
                        stats.reverted_improvements += 1

        except Exception as e:
            logger.error(f"[LearningLoop] Error getting statistics: {e}")

        return stats

    def get_applied_patterns(self, action: str) -> List[str]:
        """適用済みパターンを取得"""
        return self._applied_patterns.get(action, [])

    def get_applied_keywords(self, action: str) -> Dict[str, float]:
        """適用済みキーワードを取得"""
        return self._applied_keywords.get(action, {})

    def get_adjusted_threshold(self, action: str, default: float = 0.7) -> float:
        """調整済み閾値を取得"""
        return self._applied_thresholds.get(action, default)

    # =========================================================================
    # 効果測定
    # =========================================================================

    async def measure_effectiveness(
        self,
        improvement_id: str,
    ) -> Optional[float]:
        """
        改善の効果を測定

        Args:
            improvement_id: 改善ID

        Returns:
            改善率（-1.0〜1.0、正が改善）
        """
        if not self.enable_effectiveness_tracking:
            return None

        improvement = self._improvement_cache.get(improvement_id)
        if not improvement:
            return None

        # TODO: 実際の効果測定実装
        # - 適用前のN日間の成功率
        # - 適用後のN日間の成功率
        # - 差分を計算

        return None

    async def revert_improvement(
        self,
        improvement_id: str,
    ) -> bool:
        """
        改善を取り消す

        Args:
            improvement_id: 改善ID

        Returns:
            取り消しに成功したか
        """
        improvement = self._improvement_cache.get(improvement_id)
        if not improvement:
            return False

        try:
            if improvement.improvement_type == ImprovementType.THRESHOLD_ADJUSTMENT:
                if improvement.target_action and improvement.old_threshold is not None:
                    self._applied_thresholds[improvement.target_action] = improvement.old_threshold

            elif improvement.improvement_type == ImprovementType.PATTERN_ADDITION:
                target = improvement.target_action or improvement.target_intent
                if target and improvement.pattern_regex:
                    patterns = self._applied_patterns.get(target, [])
                    if improvement.pattern_regex in patterns:
                        patterns.remove(improvement.pattern_regex)

            elif improvement.improvement_type == ImprovementType.KEYWORD_UPDATE:
                if improvement.target_action:
                    for keyword in improvement.keywords_to_add:
                        self._applied_keywords.get(improvement.target_action, {}).pop(keyword, None)

            improvement.status = LearningStatus.REVERTED

            logger.info(f"[LearningLoop] Improvement reverted: {improvement_id}")

            return True

        except Exception as e:
            logger.error(f"[LearningLoop] Error reverting improvement: {e}")
            return False


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_learning_loop(
    pool=None,
    organization_id: str = "",
    enable_auto_apply: bool = True,
    enable_effectiveness_tracking: bool = True,
) -> LearningLoop:
    """
    LearningLoop インスタンスを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        enable_auto_apply: 改善を自動適用するか
        enable_effectiveness_tracking: 効果測定を有効にするか

    Returns:
        LearningLoop
    """
    return LearningLoop(
        pool=pool,
        organization_id=organization_id,
        enable_auto_apply=enable_auto_apply,
        enable_effectiveness_tracking=enable_effectiveness_tracking,
    )
