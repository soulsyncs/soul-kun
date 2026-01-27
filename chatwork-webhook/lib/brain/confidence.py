# lib/brain/confidence.py
"""
Ultimate Brain Architecture - Phase 2: 確信度キャリブレーション

設計書: docs/19_ultimate_brain_architecture.md
セクション: 4.1 確信度キャリブレーション

判断の確実性を数値化し、低確信度時は確認を求める。
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .constants import JST
from .chain_of_thought import ThoughtChain, InputType

logger = logging.getLogger(__name__)


# ============================================================================
# Enum定義
# ============================================================================

class RiskLevel(Enum):
    """アクションのリスクレベル"""
    HIGH = "high"           # タスク完了、知識削除など
    NORMAL = "normal"       # 通常のアクション
    LOW = "low"             # 情報提供、雑談


class ConfidenceAction(Enum):
    """確信度に基づくアクション"""
    EXECUTE = "execute"             # そのまま実行
    CONFIRM = "confirm"             # 確認を求める
    CLARIFY = "clarify"             # 明確化を求める
    DECLINE = "decline"             # 実行を拒否


# ============================================================================
# データクラス
# ============================================================================

@dataclass
class ConfidenceAdjustment:
    """確信度調整"""
    factor: str                     # 調整要因
    delta: float                    # 調整値（-1.0〜1.0）
    reasoning: str                  # 理由


@dataclass
class CalibratedDecision:
    """キャリブレーション済み判断"""
    action: ConfidenceAction        # 取るべきアクション
    original_action: str            # 元々のアクション名
    confidence: float               # 最終確信度（0.0〜1.0）
    base_confidence: float          # 基本確信度
    adjustments: List[ConfidenceAdjustment] = field(default_factory=list)
    confirmation_message: Optional[str] = None  # 確認時のメッセージ
    alternatives: List[str] = field(default_factory=list)  # 代替アクション候補
    reasoning: str = ""             # 判断理由


# ============================================================================
# 定数
# ============================================================================

# リスクレベル別の確信度閾値
CONFIDENCE_THRESHOLDS: Dict[RiskLevel, float] = {
    RiskLevel.HIGH: 0.85,      # タスク完了、知識削除など
    RiskLevel.NORMAL: 0.70,    # 通常のアクション
    RiskLevel.LOW: 0.50,       # 情報提供、雑談
}

# アクション別リスクレベル
ACTION_RISK_LEVELS: Dict[str, RiskLevel] = {
    # 高リスク（取り消しが困難/影響大）
    "task_complete": RiskLevel.HIGH,
    "chatwork_task_complete": RiskLevel.HIGH,
    "forget_knowledge": RiskLevel.HIGH,
    "delete_memory": RiskLevel.HIGH,
    "announcement_create": RiskLevel.HIGH,
    "send_announcement": RiskLevel.HIGH,

    # 通常リスク
    "task_create": RiskLevel.NORMAL,
    "chatwork_task_create": RiskLevel.NORMAL,
    "task_search": RiskLevel.NORMAL,
    "chatwork_task_search": RiskLevel.NORMAL,
    "goal_setting_start": RiskLevel.NORMAL,
    "goal_registration": RiskLevel.NORMAL,
    "goal_progress_report": RiskLevel.NORMAL,
    "goal_status_check": RiskLevel.NORMAL,
    "learn_knowledge": RiskLevel.NORMAL,
    "save_memory": RiskLevel.NORMAL,

    # 低リスク（読み取り専用/会話）
    "query_knowledge": RiskLevel.LOW,
    "query_memory": RiskLevel.LOW,
    "query_org_chart": RiskLevel.LOW,
    "general_conversation": RiskLevel.LOW,
    "daily_reflection": RiskLevel.LOW,
}

# 曖昧な表現パターン（確信度を下げる）
AMBIGUOUS_PATTERNS: List[Tuple[str, float]] = [
    (r"(?:あれ|これ|それ|あの|この|その)(?:を|に|で|は)", -0.15),  # 指示代名詞
    (r"(?:なんか|ちょっと|たぶん|多分|maybe)", -0.10),  # 曖昧表現
    (r"(?:とか|など|みたいな)", -0.05),  # 列挙の曖昧化
    (r"(?:かな[？?]?|かも)", -0.10),  # 推量
    (r"\.{3,}|…", -0.05),  # 省略
]

# 明確な表現パターン（確信度を上げる）
CLEAR_PATTERNS: List[Tuple[str, float]] = [
    (r"(?:必ず|絶対に|確実に)", 0.10),  # 強調
    (r"(?:してください|してほしい|お願い)", 0.10),  # 明確な依頼
    (r"(?:今すぐ|すぐに|至急)", 0.05),  # 緊急性
    (r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", 0.10),  # 具体的な日付
    (r"「[^」]+」", 0.05),  # 引用（具体的な内容）
]

# 確認メッセージテンプレート
CONFIRMATION_TEMPLATES: Dict[str, str] = {
    "low_confidence": "🤔 確認させてほしいウル！\n\n{options}\n\nどちらでしょうか？🐺",
    "multiple_intents": "🐺 いくつか候補があるウル！\n\n{options}\n\n番号で教えてほしいウル",
    "high_risk": "⚠️ 念のため確認するウル！\n\n{action_description}\n\nこれでいいウル？（はい/いいえ）🐺",
    "ambiguous": "😅 ちょっと分からなかったウル\n\n{clarification_question}\n\nもう少し教えてほしいウル🐺",
}


# ============================================================================
# メインクラス
# ============================================================================

class ConfidenceCalibrator:
    """
    確信度キャリブレーター

    判断の確実性を数値化し、低確信度時は確認を求める。
    """

    def __init__(
        self,
        custom_thresholds: Optional[Dict[RiskLevel, float]] = None,
        custom_risk_levels: Optional[Dict[str, RiskLevel]] = None,
    ):
        """
        初期化

        Args:
            custom_thresholds: カスタム閾値
            custom_risk_levels: カスタムリスクレベル
        """
        self.thresholds = custom_thresholds or CONFIDENCE_THRESHOLDS.copy()
        self.risk_levels = custom_risk_levels or ACTION_RISK_LEVELS.copy()

        logger.debug("ConfidenceCalibrator initialized")

    def calibrate(
        self,
        thought_chain: ThoughtChain,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CalibratedDecision:
        """
        確信度をキャリブレーションし、アクションを決定

        Args:
            thought_chain: 思考連鎖の結果
            action: 判断されたアクション名
            context: 追加コンテキスト

        Returns:
            CalibratedDecision: キャリブレーション済みの判断
        """
        context = context or {}

        # 基本確信度（思考連鎖から）
        base_confidence = thought_chain.confidence

        # 調整要因を計算
        adjustments = self._calculate_adjustments(
            thought_chain=thought_chain,
            action=action,
            context=context,
        )

        # 最終確信度を計算
        total_delta = sum(adj.delta for adj in adjustments)
        final_confidence = max(0.0, min(1.0, base_confidence + total_delta))

        # リスクレベルを取得
        risk_level = self._get_risk_level(action)
        threshold = self.thresholds.get(risk_level, 0.70)

        # アクションを決定
        if final_confidence >= threshold:
            decision_action = ConfidenceAction.EXECUTE
            confirmation_message = None
        elif final_confidence >= threshold - 0.2:
            decision_action = ConfidenceAction.CONFIRM
            confirmation_message = self._generate_confirmation(
                action=action,
                thought_chain=thought_chain,
                confidence=final_confidence,
            )
        elif final_confidence >= 0.3:
            decision_action = ConfidenceAction.CLARIFY
            confirmation_message = self._generate_clarification(
                thought_chain=thought_chain,
            )
        else:
            decision_action = ConfidenceAction.DECLINE
            confirmation_message = "すみません、よく分からなかったウル🐺 もう少し詳しく教えてほしいウル"

        # 代替アクション候補
        alternatives = self._get_alternatives(thought_chain)

        # 判断理由
        reasoning = self._build_reasoning(
            base_confidence=base_confidence,
            final_confidence=final_confidence,
            threshold=threshold,
            adjustments=adjustments,
            decision_action=decision_action,
        )

        return CalibratedDecision(
            action=decision_action,
            original_action=action,
            confidence=final_confidence,
            base_confidence=base_confidence,
            adjustments=adjustments,
            confirmation_message=confirmation_message,
            alternatives=alternatives,
            reasoning=reasoning,
        )

    def _calculate_adjustments(
        self,
        thought_chain: ThoughtChain,
        action: str,
        context: Dict[str, Any],
    ) -> List[ConfidenceAdjustment]:
        """調整要因を計算"""
        adjustments = []

        # 入力文から各パターンをチェック
        original_message = context.get("original_message", "")

        # 曖昧なパターンで減点
        for pattern, delta in AMBIGUOUS_PATTERNS:
            if re.search(pattern, original_message):
                adjustments.append(ConfidenceAdjustment(
                    factor="ambiguous_expression",
                    delta=delta,
                    reasoning=f"曖昧な表現を検出: {pattern}",
                ))

        # 明確なパターンで加点
        for pattern, delta in CLEAR_PATTERNS:
            if re.search(pattern, original_message):
                adjustments.append(ConfidenceAdjustment(
                    factor="clear_expression",
                    delta=delta,
                    reasoning=f"明確な表現を検出: {pattern}",
                ))

        # コンテキストの豊富さで調整
        if context.get("recent_conversation"):
            adjustments.append(ConfidenceAdjustment(
                factor="rich_context",
                delta=0.10,
                reasoning="直近の会話コンテキストあり",
            ))

        # 同じパターンでの過去の成功
        if context.get("past_success_pattern"):
            adjustments.append(ConfidenceAdjustment(
                factor="past_success",
                delta=0.15,
                reasoning="過去に同じパターンで成功",
            ))

        # 複数の意図候補がある場合は減点
        if len(thought_chain.possible_intents) > 1:
            # 1位と2位の確率差が小さいほど減点
            if len(thought_chain.possible_intents) >= 2:
                prob_diff = (
                    thought_chain.possible_intents[0].probability -
                    thought_chain.possible_intents[1].probability
                )
                if prob_diff < 0.2:
                    adjustments.append(ConfidenceAdjustment(
                        factor="multiple_intents",
                        delta=-0.15,
                        reasoning=f"複数の意図候補が接近: 差={prob_diff:.2f}",
                    ))

        # 入力タイプと推論アクションの不一致
        input_type = thought_chain.input_type
        if input_type == InputType.QUESTION and action in ["task_create", "chatwork_task_create"]:
            adjustments.append(ConfidenceAdjustment(
                factor="type_action_mismatch",
                delta=-0.20,
                reasoning="質問に対してタスク作成は不自然",
            ))

        return adjustments

    def _get_risk_level(self, action: str) -> RiskLevel:
        """アクションのリスクレベルを取得"""
        return self.risk_levels.get(action, RiskLevel.NORMAL)

    def _generate_confirmation(
        self,
        action: str,
        thought_chain: ThoughtChain,
        confidence: float,
    ) -> str:
        """確認メッセージを生成"""
        # 複数の意図候補がある場合
        if len(thought_chain.possible_intents) > 1:
            options = []
            for i, intent in enumerate(thought_chain.possible_intents[:3], 1):
                options.append(f"{i}. {self._intent_to_japanese(intent.intent)}")
            return CONFIRMATION_TEMPLATES["multiple_intents"].format(
                options="\n".join(options)
            )

        # 高リスクアクションの場合
        risk_level = self._get_risk_level(action)
        if risk_level == RiskLevel.HIGH:
            return CONFIRMATION_TEMPLATES["high_risk"].format(
                action_description=self._action_to_description(action)
            )

        # 低確信度の場合
        main_intent = thought_chain.final_intent
        alternative = self._get_likely_alternative(thought_chain)
        options = [
            f"1. {self._intent_to_japanese(main_intent)}",
            f"2. {self._intent_to_japanese(alternative)}",
        ]
        return CONFIRMATION_TEMPLATES["low_confidence"].format(
            options="\n".join(options)
        )

    def _generate_clarification(self, thought_chain: ThoughtChain) -> str:
        """明確化を求めるメッセージを生成"""
        # 入力タイプに基づいて質問を生成
        input_type = thought_chain.input_type

        if input_type == InputType.QUESTION:
            return CONFIRMATION_TEMPLATES["ambiguous"].format(
                clarification_question="何について知りたいですか？"
            )
        elif input_type == InputType.REQUEST:
            return CONFIRMATION_TEMPLATES["ambiguous"].format(
                clarification_question="何をしてほしいですか？"
            )
        else:
            return CONFIRMATION_TEMPLATES["ambiguous"].format(
                clarification_question="もう少し詳しく教えてもらえますか？"
            )

    def _get_alternatives(self, thought_chain: ThoughtChain) -> List[str]:
        """代替アクション候補を取得"""
        alternatives = []
        for intent in thought_chain.possible_intents[1:4]:
            alternatives.append(intent.intent)
        return alternatives

    def _get_likely_alternative(self, thought_chain: ThoughtChain) -> str:
        """最も可能性の高い代替意図を取得"""
        if len(thought_chain.possible_intents) > 1:
            return thought_chain.possible_intents[1].intent
        return "general_conversation"

    def _build_reasoning(
        self,
        base_confidence: float,
        final_confidence: float,
        threshold: float,
        adjustments: List[ConfidenceAdjustment],
        decision_action: ConfidenceAction,
    ) -> str:
        """判断理由を構築"""
        lines = [
            f"基本確信度: {base_confidence:.2f}",
        ]

        if adjustments:
            lines.append("調整:")
            for adj in adjustments:
                sign = "+" if adj.delta > 0 else ""
                lines.append(f"  {sign}{adj.delta:.2f}: {adj.reasoning}")

        lines.extend([
            f"最終確信度: {final_confidence:.2f}",
            f"閾値: {threshold:.2f}",
            f"判断: {decision_action.value}",
        ])

        return "\n".join(lines)

    def _intent_to_japanese(self, intent: str) -> str:
        """意図を日本語に変換"""
        mapping = {
            "task_search": "タスクを検索する",
            "chatwork_task_search": "タスクを検索する",
            "task_create": "タスクを作成する",
            "chatwork_task_create": "タスクを作成する",
            "task_complete": "タスクを完了にする",
            "chatwork_task_complete": "タスクを完了にする",
            "goal_setting_start": "目標設定を始める",
            "goal_registration": "目標を登録する",
            "goal_progress_report": "目標の進捗を報告する",
            "goal_status_check": "目標の状態を確認する",
            "query_knowledge": "会社の知識を検索する",
            "learn_knowledge": "知識を覚える",
            "forget_knowledge": "知識を忘れる",
            "save_memory": "情報を覚える",
            "query_memory": "覚えていることを検索する",
            "delete_memory": "覚えていることを忘れる",
            "query_org_chart": "組織図を確認する",
            "announcement_create": "アナウンスを作成する",
            "general_conversation": "会話を続ける",
            "daily_reflection": "今日の振り返りをする",
            "confirmation_response": "確認に答える",
        }
        return mapping.get(intent, intent)

    def _action_to_description(self, action: str) -> str:
        """アクションを説明文に変換"""
        mapping = {
            "task_complete": "タスクを完了にします",
            "chatwork_task_complete": "タスクを完了にします",
            "forget_knowledge": "この知識を削除します",
            "delete_memory": "この情報を削除します",
            "announcement_create": "アナウンスを送信します",
            "send_announcement": "アナウンスを送信します",
        }
        return mapping.get(action, f"{action}を実行します")


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_confidence_calibrator(
    custom_thresholds: Optional[Dict[RiskLevel, float]] = None,
    custom_risk_levels: Optional[Dict[str, RiskLevel]] = None,
) -> ConfidenceCalibrator:
    """ConfidenceCalibratorのファクトリ関数"""
    return ConfidenceCalibrator(
        custom_thresholds=custom_thresholds,
        custom_risk_levels=custom_risk_levels,
    )
