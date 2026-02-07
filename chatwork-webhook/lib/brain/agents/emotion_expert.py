# lib/brain/agents/emotion_expert.py
"""
ソウルくんの脳 - 感情ケア専門家エージェント

Ultimate Brain Phase 3: 感情ケアに特化したエキスパートエージェント

設計思想:
- 共感を最優先に、寄り添う姿勢を示す
- 適切なタイミングで専門家への相談を促す
- 選択理論・心理的安全性に基づいた対応

主要機能:
1. 共感的な応答
2. メンタルヘルスケア支援
3. 励まし・モチベーション支援
4. 感情変化の検知と対応

設計書: docs/19_ultimate_brain_architecture.md セクション5.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from lib.brain.agents.base import (
    BaseAgent,
    AgentType,
    AgentCapability,
    AgentMessage,
    AgentResponse,
    AgentContext,
    MessageType,
    ExpertiseLevel,
)


logger = logging.getLogger(__name__)


# =============================================================================
# Enum
# =============================================================================

class EmotionType(str, Enum):
    """感情タイプ"""
    JOY = "joy"                    # 喜び
    SADNESS = "sadness"            # 悲しみ
    ANGER = "anger"                # 怒り
    FEAR = "fear"                  # 恐れ
    SURPRISE = "surprise"          # 驚き
    DISGUST = "disgust"            # 嫌悪
    ANXIETY = "anxiety"            # 不安
    FRUSTRATION = "frustration"    # フラストレーション
    CONFUSION = "confusion"        # 混乱
    NEUTRAL = "neutral"            # 中立


class SupportType(str, Enum):
    """サポートタイプ"""
    EMPATHY = "empathy"            # 共感
    ENCOURAGEMENT = "encouragement"  # 励まし
    ADVICE = "advice"              # アドバイス
    DISTRACTION = "distraction"    # 気分転換
    REFERRAL = "referral"          # 専門家紹介


class UrgencyLevel(str, Enum):
    """緊急度レベル"""
    CRITICAL = "critical"          # 即時対応必要
    HIGH = "high"                  # 優先対応
    MEDIUM = "medium"              # 通常対応
    LOW = "low"                    # 経過観察


# =============================================================================
# 定数
# =============================================================================

# ネガティブ感情のキーワード
NEGATIVE_EMOTION_KEYWORDS = [
    "つらい", "辛い", "しんどい", "きつい",
    "悲しい", "泣きたい", "落ち込む", "凹む",
    "不安", "心配", "怖い", "恐い",
    "イライラ", "怒り", "ムカつく", "腹立つ",
    "疲れた", "もう無理", "限界", "逃げたい",
]

# ポジティブ感情のキーワード
POSITIVE_EMOTION_KEYWORDS = [
    "嬉しい", "楽しい", "幸せ", "ハッピー",
    "良かった", "やった", "できた", "成功",
    "感謝", "ありがとう", "助かった",
    "成長", "達成", "前進", "進歩",
]

# 励まし要求のキーワード
ENCOURAGEMENT_KEYWORDS = [
    "励まして", "元気", "頑張る", "やる気",
    "モチベーション", "自信", "勇気",
    "背中を押して", "応援",
]

# 相談・悩みのキーワード
CONSULTATION_KEYWORDS = [
    "悩み", "相談", "聞いて", "話したい",
    "どうしたら", "どうすれば", "困った",
]

# 緊急対応が必要なキーワード
URGENT_KEYWORDS = [
    "死にたい", "消えたい", "いなくなりたい",
    "限界", "もう無理", "耐えられない",
    "誰にも言えない", "一人で",
]

# 選択理論の5つの基本欲求
BASIC_NEEDS = [
    "生存", "愛・所属", "力", "自由", "楽しみ",
]


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class EmotionState:
    """
    感情状態
    """
    primary_emotion: EmotionType = EmotionType.NEUTRAL
    intensity: float = 0.5  # 0.0〜1.0
    secondary_emotions: List[EmotionType] = field(default_factory=list)
    detected_keywords: List[str] = field(default_factory=list)
    urgency: UrgencyLevel = UrgencyLevel.LOW
    timestamp: Optional[datetime] = None


@dataclass
class SupportResponse:
    """
    サポート応答
    """
    support_type: SupportType = SupportType.EMPATHY
    message: str = ""
    follow_up_suggestions: List[str] = field(default_factory=list)
    resources: List[str] = field(default_factory=list)
    need_escalation: bool = False
    escalation_reason: str = ""


@dataclass
class EmotionTrend:
    """
    感情トレンド
    """
    user_id: str = ""
    period_days: int = 7
    average_sentiment: float = 0.0  # -1.0〜1.0
    trend_direction: str = ""  # "improving", "stable", "declining"
    significant_events: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


# =============================================================================
# EmotionExpert クラス
# =============================================================================

class EmotionExpert(BaseAgent):
    """
    感情ケア専門家エージェント

    社員の感情に寄り添い、適切なサポートを提供する専門家。
    共感、励まし、必要に応じた専門家への紹介を行う。

    Attributes:
        pool: データベース接続プール
        organization_id: 組織ID
    """

    def __init__(
        self,
        pool: Optional[Any] = None,
        organization_id: str = "",
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
        """
        super().__init__(
            agent_type=AgentType.EMOTION_EXPERT,
            pool=pool,
            organization_id=organization_id,
        )

        logger.info(
            "EmotionExpert initialized",
            extra={"organization_id": organization_id}
        )

    # -------------------------------------------------------------------------
    # BaseAgent 実装
    # -------------------------------------------------------------------------

    def _initialize_capabilities(self) -> None:
        """エージェントの能力を初期化"""
        self._capabilities = [
            AgentCapability(
                capability_id="empathy_response",
                name="共感的応答",
                description="感情に寄り添う応答を生成する",
                keywords=NEGATIVE_EMOTION_KEYWORDS + CONSULTATION_KEYWORDS,
                actions=["empathize", "listen", "validate_feeling"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.2,
            ),
            AgentCapability(
                capability_id="encouragement",
                name="励まし",
                description="モチベーションを高める励ましを提供する",
                keywords=ENCOURAGEMENT_KEYWORDS + POSITIVE_EMOTION_KEYWORDS,
                actions=["encourage", "motivate", "celebrate"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="emotion_detection",
                name="感情検知",
                description="メッセージから感情状態を検知する",
                keywords=[],
                actions=["detect_emotion", "analyze_sentiment"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="crisis_support",
                name="危機対応",
                description="緊急時の対応と専門家紹介を行う",
                keywords=URGENT_KEYWORDS,
                actions=["crisis_response", "escalate", "refer_professional"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.25,  # 緊急時は最優先
            ),
            AgentCapability(
                capability_id="emotion_tracking",
                name="感情トラッキング",
                description="感情の変化をトラッキングする",
                keywords=["気分", "調子", "最近"],
                actions=["track_emotion", "get_trend", "check_wellbeing"],
                expertise_level=ExpertiseLevel.SECONDARY,
                confidence_boost=0.1,
            ),
        ]

    def _register_handlers(self) -> None:
        """ハンドラーを登録"""
        self._handlers = {
            # 共感
            "empathize": self._handle_empathize,
            "listen": self._handle_listen,
            "validate_feeling": self._handle_validate_feeling,
            # 励まし
            "encourage": self._handle_encourage,
            "motivate": self._handle_motivate,
            "celebrate": self._handle_celebrate,
            # 感情検知
            "detect_emotion": self._handle_detect_emotion,
            "analyze_sentiment": self._handle_analyze_sentiment,
            # 危機対応
            "crisis_response": self._handle_crisis_response,
            "escalate": self._handle_escalate,
            "refer_professional": self._handle_refer_professional,
            # トラッキング
            "track_emotion": self._handle_track_emotion,
            "get_trend": self._handle_get_trend,
            "check_wellbeing": self._handle_check_wellbeing,
        }

    async def process(
        self,
        context: AgentContext,
        message: AgentMessage,
    ) -> AgentResponse:
        """
        メッセージを処理

        Args:
            context: エージェントコンテキスト
            message: 処理するメッセージ

        Returns:
            AgentResponse: 処理結果
        """
        content = message.content
        action = content.get("action", "")

        # まず感情を検知
        original_message = content.get("message", context.original_message)
        emotion_state = self._detect_emotion_state(original_message)

        # 緊急対応が必要な場合は優先
        if emotion_state.urgency == UrgencyLevel.CRITICAL:
            return await self._handle_urgent_case(message, context, emotion_state)

        if action and action in self._handlers:
            handler = self._handlers[action]
            try:
                result = await handler(content, context, emotion_state)
                confidence = self.get_confidence(action, context)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=True,
                    result=result,
                    confidence=confidence,
                    metadata={"emotion_state": emotion_state.__dict__},
                )
            except Exception as e:
                logger.error(f"Handler error: {action}: {e}", exc_info=True)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=False,
                    error_message=str(e),
                )

        # アクションを推論
        inferred_action = self._infer_action(original_message, emotion_state)

        if inferred_action and inferred_action in self._handlers:
            content["action"] = inferred_action
            handler = self._handlers[inferred_action]
            try:
                result = await handler(content, context, emotion_state)
                confidence = self.get_confidence(inferred_action, context)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=True,
                    result=result,
                    confidence=confidence,
                    metadata={"emotion_state": emotion_state.__dict__},
                )
            except Exception as e:
                logger.error(f"Handler error: {inferred_action}: {e}", exc_info=True)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=False,
                    error_message=str(e),
                )

        return AgentResponse(
            request_id=message.id,
            agent_type=self._agent_type,
            success=False,
            error_message="感情ケア関連の操作を特定できませんでした",
            confidence=0.3,
        )

    def can_handle(
        self,
        action: str,
        context: AgentContext,
    ) -> bool:
        """
        指定されたアクションを処理できるか判定
        """
        if action in self._handlers:
            return True

        for capability in self._capabilities:
            if action in capability.actions:
                return True

        return False

    def get_confidence(
        self,
        action: str,
        context: AgentContext,
    ) -> float:
        """
        指定されたアクションに対する確信度を計算
        """
        base_confidence = 0.5

        capability = self.get_capability_for_action(action)
        if capability:
            base_confidence = 0.7
            base_confidence += capability.confidence_boost

            if capability.expertise_level == ExpertiseLevel.PRIMARY:
                base_confidence += 0.1
            elif capability.expertise_level == ExpertiseLevel.SECONDARY:
                base_confidence += 0.05

        return min(base_confidence, 1.0)

    # -------------------------------------------------------------------------
    # 感情検知
    # -------------------------------------------------------------------------

    def _detect_emotion_state(self, message: str) -> EmotionState:
        """
        メッセージから感情状態を検知

        Args:
            message: 分析するメッセージ

        Returns:
            EmotionState: 検知した感情状態
        """
        message_lower = message.lower()
        detected_keywords = []
        emotions: List[EmotionType] = []

        # 緊急キーワードチェック
        urgency = UrgencyLevel.LOW
        for keyword in URGENT_KEYWORDS:
            if keyword in message_lower:
                detected_keywords.append(keyword)
                urgency = UrgencyLevel.CRITICAL

        # ネガティブ感情チェック
        negative_count = 0
        for keyword in NEGATIVE_EMOTION_KEYWORDS:
            if keyword in message_lower:
                detected_keywords.append(keyword)
                negative_count += 1

        # ポジティブ感情チェック
        positive_count = 0
        for keyword in POSITIVE_EMOTION_KEYWORDS:
            if keyword in message_lower:
                detected_keywords.append(keyword)
                positive_count += 1

        # プライマリ感情を決定
        if urgency == UrgencyLevel.CRITICAL:
            primary = EmotionType.FEAR
            intensity = 1.0
        elif negative_count > positive_count:
            primary = self._classify_negative_emotion(detected_keywords)
            intensity = min(0.5 + negative_count * 0.1, 1.0)
            if negative_count >= 3:
                urgency = UrgencyLevel.HIGH
            elif negative_count >= 2:
                urgency = UrgencyLevel.MEDIUM
        elif positive_count > negative_count:
            primary = EmotionType.JOY
            intensity = min(0.5 + positive_count * 0.1, 1.0)
        else:
            primary = EmotionType.NEUTRAL
            intensity = 0.5

        return EmotionState(
            primary_emotion=primary,
            intensity=intensity,
            secondary_emotions=emotions,
            detected_keywords=detected_keywords,
            urgency=urgency,
            timestamp=datetime.now(),
        )

    def _classify_negative_emotion(self, keywords: List[str]) -> EmotionType:
        """
        キーワードからネガティブ感情を分類
        """
        sadness_keywords = ["悲しい", "泣きたい", "落ち込む", "凹む"]
        anger_keywords = ["イライラ", "怒り", "ムカつく", "腹立つ"]
        anxiety_keywords = ["不安", "心配", "怖い", "恐い"]
        frustration_keywords = ["つらい", "辛い", "しんどい", "きつい", "疲れた"]

        for kw in keywords:
            if kw in sadness_keywords:
                return EmotionType.SADNESS
            if kw in anger_keywords:
                return EmotionType.ANGER
            if kw in anxiety_keywords:
                return EmotionType.ANXIETY
            if kw in frustration_keywords:
                return EmotionType.FRUSTRATION

        return EmotionType.SADNESS  # デフォルト

    # -------------------------------------------------------------------------
    # アクション推論
    # -------------------------------------------------------------------------

    def _infer_action(
        self,
        message: str,
        emotion_state: EmotionState,
    ) -> Optional[str]:
        """
        メッセージと感情状態からアクションを推論
        """
        message_lower = message.lower()

        # 緊急時
        if emotion_state.urgency == UrgencyLevel.CRITICAL:
            return "crisis_response"

        # 励ましを求めている
        for keyword in ENCOURAGEMENT_KEYWORDS:
            if keyword in message_lower:
                return "encourage"

        # ポジティブな報告
        if emotion_state.primary_emotion == EmotionType.JOY:
            return "celebrate"

        # ネガティブな感情
        if emotion_state.primary_emotion in [
            EmotionType.SADNESS,
            EmotionType.ANGER,
            EmotionType.ANXIETY,
            EmotionType.FRUSTRATION,
        ]:
            return "empathize"

        # 相談・悩み
        for keyword in CONSULTATION_KEYWORDS:
            if keyword in message_lower:
                return "listen"

        return None

    # -------------------------------------------------------------------------
    # 緊急対応
    # -------------------------------------------------------------------------

    async def _handle_urgent_case(
        self,
        message: AgentMessage,
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> AgentResponse:
        """
        緊急ケースを処理

        Args:
            message: メッセージ
            context: コンテキスト
            emotion_state: 感情状態

        Returns:
            AgentResponse: 応答
        """
        logger.warning(
            "Urgent emotional case detected",
            extra={
                "user_id": context.user_id,
                "keywords": emotion_state.detected_keywords,
            }
        )

        result = {
            "action": "crisis_response",
            "urgency": "critical",
            "emotion_state": emotion_state.__dict__,
            "response": (
                "お話しいただいてありがとうございますウル。"
                "今とてもつらい状況なのですね。"
                "一人で抱え込まないでほしいウル。"
            ),
            "resources": [
                "いのちの電話: 0120-783-556",
                "よりそいホットライン: 0120-279-338",
            ],
            "requires_follow_up": True,
            "escalation_recommended": True,
        }

        return AgentResponse(
            request_id=message.id,
            agent_type=self._agent_type,
            success=True,
            result=result,
            confidence=1.0,
            metadata={"emotion_state": emotion_state.__dict__},
        )

    # -------------------------------------------------------------------------
    # ハンドラー
    # -------------------------------------------------------------------------

    async def _handle_empathize(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """共感ハンドラー"""
        message = content.get("message", "")

        return {
            "action": "empathize",
            "emotion_state": emotion_state.__dict__,
            "response": "つらい気持ちを話してくれてありがとうウル。",
            "support_type": SupportType.EMPATHY.value,
            "requires_external_handler": True,
        }

    async def _handle_listen(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """傾聴ハンドラー"""
        message = content.get("message", "")

        return {
            "action": "listen",
            "emotion_state": emotion_state.__dict__,
            "response": "話を聞かせてほしいウル。",
            "support_type": SupportType.EMPATHY.value,
            "requires_external_handler": True,
        }

    async def _handle_validate_feeling(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """感情の承認ハンドラー"""
        return {
            "action": "validate_feeling",
            "emotion_state": emotion_state.__dict__,
            "response": "そう感じるのは自然なことウル。",
            "support_type": SupportType.EMPATHY.value,
            "requires_external_handler": True,
        }

    async def _handle_encourage(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """励ましハンドラー"""
        return {
            "action": "encourage",
            "emotion_state": emotion_state.__dict__,
            "response": "あなたなら大丈夫ウル！",
            "support_type": SupportType.ENCOURAGEMENT.value,
            "requires_external_handler": True,
        }

    async def _handle_motivate(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """モチベーション支援ハンドラー"""
        return {
            "action": "motivate",
            "emotion_state": emotion_state.__dict__,
            "response": "一歩ずつ進んでいけばいいウル！",
            "support_type": SupportType.ENCOURAGEMENT.value,
            "requires_external_handler": True,
        }

    async def _handle_celebrate(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """お祝いハンドラー"""
        return {
            "action": "celebrate",
            "emotion_state": emotion_state.__dict__,
            "response": "素晴らしいウル！一緒に喜びたいウル！",
            "support_type": SupportType.ENCOURAGEMENT.value,
            "requires_external_handler": True,
        }

    async def _handle_detect_emotion(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """感情検知ハンドラー"""
        return {
            "action": "detect_emotion",
            "emotion_state": emotion_state.__dict__,
            "response": f"感情を検知しましたウル: {emotion_state.primary_emotion.value}",
            "requires_external_handler": False,
        }

    async def _handle_analyze_sentiment(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """感情分析ハンドラー"""
        return {
            "action": "analyze_sentiment",
            "emotion_state": emotion_state.__dict__,
            "response": "感情分析を行いましたウル。",
            "requires_external_handler": True,
        }

    async def _handle_crisis_response(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """危機対応ハンドラー"""
        return {
            "action": "crisis_response",
            "emotion_state": emotion_state.__dict__,
            "urgency": "critical",
            "response": "今とてもつらい状況なのですね。一人で抱え込まないでほしいウル。",
            "resources": [
                "いのちの電話: 0120-783-556",
                "よりそいホットライン: 0120-279-338",
            ],
            "escalation_recommended": True,
            "requires_external_handler": True,
        }

    async def _handle_escalate(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """エスカレーションハンドラー"""
        reason = content.get("reason", "")

        return {
            "action": "escalate",
            "emotion_state": emotion_state.__dict__,
            "reason": reason,
            "response": "適切な担当者に相談を繋ぎますウル。",
            "requires_external_handler": True,
        }

    async def _handle_refer_professional(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """専門家紹介ハンドラー"""
        return {
            "action": "refer_professional",
            "emotion_state": emotion_state.__dict__,
            "response": "専門家に相談することをお勧めしますウル。",
            "resources": [
                "産業医",
                "EAP（従業員支援プログラム）",
                "カウンセラー",
            ],
            "requires_external_handler": True,
        }

    async def _handle_track_emotion(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """感情トラッキングハンドラー"""
        return {
            "action": "track_emotion",
            "emotion_state": emotion_state.__dict__,
            "user_id": context.user_id,
            "response": "感情を記録しましたウル。",
            "requires_external_handler": True,
        }

    async def _handle_get_trend(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """感情トレンド取得ハンドラー"""
        period = content.get("period_days", 7)

        return {
            "action": "get_trend",
            "user_id": context.user_id,
            "period_days": period,
            "response": "最近の気分の変化を確認しますウル。",
            "requires_external_handler": True,
        }

    async def _handle_check_wellbeing(
        self,
        content: Dict[str, Any],
        context: AgentContext,
        emotion_state: EmotionState,
    ) -> Dict[str, Any]:
        """ウェルビーイングチェックハンドラー"""
        return {
            "action": "check_wellbeing",
            "user_id": context.user_id,
            "emotion_state": emotion_state.__dict__,
            "response": "調子はどうですかウル？",
            "requires_external_handler": True,
        }


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_emotion_expert(
    pool: Optional[Any] = None,
    organization_id: str = "",
) -> EmotionExpert:
    """
    感情ケア専門家エージェントを作成するファクトリ関数
    """
    return EmotionExpert(
        pool=pool,
        organization_id=organization_id,
    )
