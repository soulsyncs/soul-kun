# lib/brain/agents/goal_expert.py
"""
ソウルくんの脳 - 目標専門家エージェント

Ultimate Brain Phase 3: 目標達成支援に特化したエキスパートエージェント

設計思想:
- WHY/WHAT/HOWの対話フレームワーク
- 選択理論とAchievement社メソッドに基づく
- モチベーション管理と進捗追跡

主要機能:
1. 目標設定の対話支援
2. 進捗管理と可視化
3. モチベーション維持
4. 成功パターンの分析

設計書: docs/19_ultimate_brain_architecture.md セクション5.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
# 定数
# =============================================================================

# 目標設定のステップ
GOAL_STEP_INTRO = "intro"
GOAL_STEP_WHY = "why"
GOAL_STEP_WHAT = "what"
GOAL_STEP_HOW = "how"
GOAL_STEP_COMPLETE = "complete"

# 目標の状態
GOAL_STATUS_ACTIVE = "active"
GOAL_STATUS_COMPLETED = "completed"
GOAL_STATUS_ABANDONED = "abandoned"
GOAL_STATUS_ON_HOLD = "on_hold"

# 目標設定開始のキーワード
GOAL_START_KEYWORDS = [
    "目標設定", "目標を設定", "目標を立てたい", "目標を決めたい",
    "ゴール設定", "今月の目標", "目標登録", "個人目標",
]

# 進捗報告のキーワード
GOAL_PROGRESS_KEYWORDS = [
    "進捗", "進み具合", "どこまで", "途中経過",
    "進んでる", "進捗報告", "経過報告",
]

# 状態確認のキーワード
GOAL_STATUS_KEYWORDS = [
    "目標の状態", "目標どうなってる", "目標確認",
    "ゴールの状態", "達成度", "進捗率",
]

# モチベーションキーワード
MOTIVATION_KEYWORDS = [
    "やる気", "モチベーション", "モチベ", "意欲",
    "頑張れない", "やる気出ない", "諦めそう",
]

# 放置警告の日数
GOAL_STALE_DAYS = 7
GOAL_ABANDONED_DAYS = 14


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class GoalInfo:
    """
    目標情報
    """
    goal_id: str = ""
    user_id: str = ""
    organization_id: str = ""

    # 目標内容
    title: str = ""
    why: str = ""              # なぜ（目的・動機）
    what: str = ""             # 何を（具体的な目標）
    how: str = ""              # どうやって（行動計画）

    # 状態
    status: str = GOAL_STATUS_ACTIVE
    progress_percentage: int = 0

    # 期限
    target_date: Optional[datetime] = None

    # タイムスタンプ
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def is_stale(self) -> bool:
        """放置されているか"""
        if self.updated_at and self.status == GOAL_STATUS_ACTIVE:
            days_since_update = (datetime.now() - self.updated_at).days
            return days_since_update >= GOAL_STALE_DAYS
        return False

    @property
    def days_since_update(self) -> int:
        """最終更新からの日数"""
        if self.updated_at:
            return (datetime.now() - self.updated_at).days
        return 0


@dataclass
class GoalSession:
    """
    目標設定セッション
    """
    session_id: str = ""
    user_id: str = ""
    room_id: str = ""

    # 進行状態
    current_step: str = GOAL_STEP_INTRO
    retry_count: int = 0

    # 収集した情報
    collected_why: str = ""
    collected_what: str = ""
    collected_how: str = ""

    # タイムスタンプ
    started_at: datetime = field(default_factory=datetime.now)
    last_activity_at: datetime = field(default_factory=datetime.now)


@dataclass
class MotivationAnalysis:
    """
    モチベーション分析
    """
    user_id: str = ""
    motivation_level: str = "normal"  # "high", "normal", "low", "critical"
    factors: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


# =============================================================================
# GoalExpert クラス
# =============================================================================

class GoalExpert(BaseAgent):
    """
    目標専門家エージェント

    目標達成支援のあらゆる側面に対応する専門家。
    WHY/WHAT/HOWの対話フレームワークで目標設定を支援。

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
            agent_type=AgentType.GOAL_EXPERT,
            pool=pool,
            organization_id=organization_id,
        )

        # アクティブセッション（メモリキャッシュ）
        self._active_sessions: Dict[str, GoalSession] = {}

        logger.info(
            "GoalExpert initialized",
            extra={"organization_id": organization_id}
        )

    # -------------------------------------------------------------------------
    # BaseAgent 実装
    # -------------------------------------------------------------------------

    def _initialize_capabilities(self) -> None:
        """エージェントの能力を初期化"""
        self._capabilities = [
            AgentCapability(
                capability_id="goal_setting",
                name="目標設定",
                description="WHY/WHAT/HOWフレームワークで目標設定を支援",
                keywords=GOAL_START_KEYWORDS,
                actions=["goal_setting_start", "goal_setting_continue"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.2,
            ),
            AgentCapability(
                capability_id="goal_progress",
                name="進捗管理",
                description="目標の進捗を記録・確認する",
                keywords=GOAL_PROGRESS_KEYWORDS,
                actions=["goal_progress_report", "goal_progress_update"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="goal_status",
                name="状態確認",
                description="目標の状態を確認・表示する",
                keywords=GOAL_STATUS_KEYWORDS,
                actions=["goal_status_check", "goal_list"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.1,
            ),
            AgentCapability(
                capability_id="motivation",
                name="モチベーション",
                description="モチベーション維持と回復を支援",
                keywords=MOTIVATION_KEYWORDS,
                actions=["motivation_boost", "motivation_analyze"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="achievement",
                name="達成支援",
                description="目標達成に向けたアドバイス",
                keywords=["達成", "成功", "コツ", "アドバイス", "ヒント"],
                actions=["achievement_advice", "success_pattern"],
                expertise_level=ExpertiseLevel.SECONDARY,
                confidence_boost=0.1,
            ),
        ]

    def _register_handlers(self) -> None:
        """ハンドラーを登録"""
        self._handlers = {
            "goal_setting_start": self._handle_goal_setting_start,
            "goal_setting_continue": self._handle_goal_setting_continue,
            "goal_progress_report": self._handle_goal_progress_report,
            "goal_progress_update": self._handle_goal_progress_update,
            "goal_status_check": self._handle_goal_status_check,
            "goal_list": self._handle_goal_list,
            "motivation_boost": self._handle_motivation_boost,
            "motivation_analyze": self._handle_motivation_analyze,
            "achievement_advice": self._handle_achievement_advice,
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

        # アクションが明示されている場合
        if action and action in self._handlers:
            handler = self._handlers[action]
            try:
                result = await handler(content, context)
                confidence = self.get_confidence(action, context)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=True,
                    result=result,
                    confidence=confidence,
                )
            except Exception as e:
                logger.error(f"Handler error: {action}: {e}", exc_info=True)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=False,
                    error_message=str(e),
                )

        # メッセージからアクションを推論
        original_message = content.get("message", context.original_message)
        inferred_action = self._infer_action(original_message, context)

        if inferred_action and inferred_action in self._handlers:
            content["action"] = inferred_action
            handler = self._handlers[inferred_action]
            try:
                result = await handler(content, context)
                confidence = self.get_confidence(inferred_action, context)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=True,
                    result=result,
                    confidence=confidence,
                )
            except Exception as e:
                logger.error(f"Handler error: {inferred_action}: {e}", exc_info=True)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=False,
                    error_message=str(e),
                )

        # アクションが特定できない場合
        return AgentResponse(
            request_id=message.id,
            agent_type=self._agent_type,
            success=False,
            error_message="目標関連の操作を特定できませんでした",
            confidence=0.3,
        )

    def can_handle(
        self,
        action: str,
        context: AgentContext,
    ) -> bool:
        """
        指定されたアクションを処理できるか判定

        Args:
            action: アクション名
            context: エージェントコンテキスト

        Returns:
            bool: 処理可能ならTrue
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

        Args:
            action: アクション名
            context: エージェントコンテキスト

        Returns:
            float: 確信度（0.0〜1.0）
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

        # アクティブセッションがある場合はブースト
        session_key = f"{context.user_id}:{context.room_id}"
        if session_key in self._active_sessions:
            base_confidence += 0.1

        return min(base_confidence, 1.0)

    # -------------------------------------------------------------------------
    # アクション推論
    # -------------------------------------------------------------------------

    def _infer_action(self, message: str, context: AgentContext) -> Optional[str]:
        """
        メッセージからアクションを推論

        Args:
            message: ユーザーメッセージ
            context: エージェントコンテキスト

        Returns:
            str: 推論されたアクション（なければNone）
        """
        message_lower = message.lower()

        # アクティブセッションがある場合は継続
        session_key = f"{context.user_id}:{context.room_id}"
        if session_key in self._active_sessions:
            return "goal_setting_continue"

        # 目標設定開始
        for keyword in GOAL_START_KEYWORDS:
            if keyword.lower() in message_lower:
                return "goal_setting_start"

        # 進捗報告
        for keyword in GOAL_PROGRESS_KEYWORDS:
            if keyword.lower() in message_lower:
                return "goal_progress_report"

        # 状態確認
        for keyword in GOAL_STATUS_KEYWORDS:
            if keyword.lower() in message_lower:
                return "goal_status_check"

        # モチベーション
        for keyword in MOTIVATION_KEYWORDS:
            if keyword.lower() in message_lower:
                return "motivation_boost"

        return None

    # -------------------------------------------------------------------------
    # ハンドラー
    # -------------------------------------------------------------------------

    async def _handle_goal_setting_start(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """目標設定開始ハンドラー"""
        user_id = content.get("user_id", context.user_id)
        room_id = content.get("room_id", context.room_id)

        # 新しいセッションを作成
        session = GoalSession(
            session_id=f"{user_id}:{room_id}:{datetime.now().timestamp()}",
            user_id=user_id,
            room_id=room_id,
            current_step=GOAL_STEP_WHY,
        )

        session_key = f"{user_id}:{room_id}"
        self._active_sessions[session_key] = session

        return {
            "action": "goal_setting_start",
            "session_id": session.session_id,
            "current_step": GOAL_STEP_WHY,
            "response": self._get_step_prompt(GOAL_STEP_WHY),
            "requires_external_handler": True,
        }

    async def _handle_goal_setting_continue(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """目標設定継続ハンドラー"""
        user_id = content.get("user_id", context.user_id)
        room_id = content.get("room_id", context.room_id)
        message = content.get("message", "")

        session_key = f"{user_id}:{room_id}"
        session = self._active_sessions.get(session_key)

        if not session:
            return {
                "action": "goal_setting_continue",
                "error": "active_session_not_found",
                "response": "目標設定のセッションが見つかりませんでした。新しく始めますか？",
            }

        # 現在のステップに応じて処理
        current_step = session.current_step
        validation = self._validate_step_input(current_step, message)

        if not validation["valid"]:
            session.retry_count += 1
            return {
                "action": "goal_setting_continue",
                "current_step": current_step,
                "retry_count": session.retry_count,
                "response": validation["feedback"],
            }

        # 入力を保存
        if current_step == GOAL_STEP_WHY:
            session.collected_why = message
            session.current_step = GOAL_STEP_WHAT
        elif current_step == GOAL_STEP_WHAT:
            session.collected_what = message
            session.current_step = GOAL_STEP_HOW
        elif current_step == GOAL_STEP_HOW:
            session.collected_how = message
            session.current_step = GOAL_STEP_COMPLETE

        session.retry_count = 0
        session.last_activity_at = datetime.now()

        # 完了チェック
        if session.current_step == GOAL_STEP_COMPLETE:
            del self._active_sessions[session_key]
            return {
                "action": "goal_setting_continue",
                "current_step": GOAL_STEP_COMPLETE,
                "goal_data": {
                    "why": session.collected_why,
                    "what": session.collected_what,
                    "how": session.collected_how,
                },
                "response": "素晴らしい目標ですね！登録しますウル！",
                "requires_external_handler": True,
            }

        return {
            "action": "goal_setting_continue",
            "current_step": session.current_step,
            "response": self._get_step_prompt(session.current_step),
        }

    async def _handle_goal_progress_report(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """進捗報告ハンドラー"""
        user_id = content.get("user_id", context.user_id)
        goal_id = content.get("goal_id", "")
        progress = content.get("progress", "")

        return {
            "action": "goal_progress_report",
            "user_id": user_id,
            "goal_id": goal_id,
            "progress": progress,
            "response": "進捗を記録しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_goal_progress_update(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """進捗更新ハンドラー"""
        goal_id = content.get("goal_id", "")
        percentage = content.get("percentage", 0)

        return {
            "action": "goal_progress_update",
            "goal_id": goal_id,
            "percentage": percentage,
            "response": f"進捗を{percentage}%に更新しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_goal_status_check(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """状態確認ハンドラー"""
        user_id = content.get("user_id", context.user_id)

        return {
            "action": "goal_status_check",
            "user_id": user_id,
            "response": "目標の状態を確認しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_goal_list(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """目標一覧ハンドラー"""
        user_id = content.get("user_id", context.user_id)
        status = content.get("status", GOAL_STATUS_ACTIVE)

        return {
            "action": "goal_list",
            "user_id": user_id,
            "status": status,
            "response": "目標一覧を表示しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_motivation_boost(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """モチベーション向上ハンドラー"""
        message = content.get("message", "")

        # モチベーションに合わせた応答を生成
        response = self._generate_motivation_response(message)

        return {
            "action": "motivation_boost",
            "response": response,
            "tips": [
                "小さな成功を積み重ねましょう",
                "なぜその目標を立てたか思い出してみましょう",
                "目標を小さく分解してみましょう",
            ],
        }

    async def _handle_motivation_analyze(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """モチベーション分析ハンドラー"""
        user_id = content.get("user_id", context.user_id)

        # 分析（実際にはDBからデータを取得して分析）
        analysis = MotivationAnalysis(
            user_id=user_id,
            motivation_level="normal",
            factors=["定期的な進捗更新", "目標の明確さ"],
            recommendations=["週1回は進捗を振り返りましょう"],
        )

        return {
            "action": "motivation_analyze",
            "analysis": {
                "motivation_level": analysis.motivation_level,
                "factors": analysis.factors,
                "recommendations": analysis.recommendations,
            },
            "response": f"モチベーションレベル: {analysis.motivation_level}",
        }

    async def _handle_achievement_advice(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """達成アドバイスハンドラー"""
        goal_id = content.get("goal_id", "")

        advices = [
            "目標を毎日見えるところに書いておきましょう",
            "週に1回は進捗を振り返りましょう",
            "小さな成功も祝いましょう",
            "困ったら周りに相談しましょう",
        ]

        return {
            "action": "achievement_advice",
            "goal_id": goal_id,
            "advices": advices,
            "response": "目標達成のコツをお伝えしますウル！\n" + "\n".join([f"・{a}" for a in advices]),
        }

    # -------------------------------------------------------------------------
    # ユーティリティ
    # -------------------------------------------------------------------------

    def _get_step_prompt(self, step: str) -> str:
        """
        ステップに応じたプロンプトを取得

        Args:
            step: 現在のステップ

        Returns:
            str: プロンプト
        """
        prompts = {
            GOAL_STEP_WHY: (
                "目標設定を始めますウル！\n\n"
                "まずは「なぜ」その目標を達成したいのか教えてください。\n"
                "どんな思いがありますか？"
            ),
            GOAL_STEP_WHAT: (
                "素敵な思いですね！\n\n"
                "次は「何を」達成したいのか、具体的に教えてください。\n"
                "できるだけ具体的に、測定可能な形で書いてみましょう。"
            ),
            GOAL_STEP_HOW: (
                "良い目標ですね！\n\n"
                "最後に「どうやって」達成するのか、\n"
                "具体的な行動計画を教えてください。"
            ),
            GOAL_STEP_COMPLETE: (
                "目標設定が完了しましたウル！\n"
                "一緒に頑張りましょう！"
            ),
        }
        return prompts.get(step, "目標設定を続けましょう")

    def _validate_step_input(self, step: str, message: str) -> Dict[str, Any]:
        """
        ステップの入力を検証

        Args:
            step: 現在のステップ
            message: ユーザーの入力

        Returns:
            Dict: 検証結果
        """
        # 短すぎる入力
        if len(message.strip()) < 10:
            return {
                "valid": False,
                "feedback": "もう少し詳しく教えてもらえますか？",
            }

        # ステップ固有の検証
        if step == GOAL_STEP_WHY:
            # WHYは理由や動機を含んでいるか
            reason_keywords = ["ため", "から", "ので", "たい", "ほしい", "なりたい"]
            if not any(kw in message for kw in reason_keywords):
                return {
                    "valid": False,
                    "feedback": "「〜したいから」「〜のため」のように、理由を教えてもらえますか？",
                }

        elif step == GOAL_STEP_WHAT:
            # WHATは具体的な目標か
            if len(message) < 20:
                return {
                    "valid": False,
                    "feedback": "もう少し具体的に書いてみましょう！",
                }

        elif step == GOAL_STEP_HOW:
            # HOWは行動計画か
            action_keywords = ["する", "やる", "行う", "実行", "取り組む", "始める"]
            if not any(kw in message for kw in action_keywords):
                return {
                    "valid": False,
                    "feedback": "具体的な行動を書いてみましょう！「〜する」「〜を行う」など。",
                }

        return {"valid": True, "feedback": ""}

    def _generate_motivation_response(self, message: str) -> str:
        """
        モチベーションに合わせた応答を生成

        Args:
            message: ユーザーのメッセージ

        Returns:
            str: 応答
        """
        # ネガティブなキーワードを検出
        negative_keywords = ["つらい", "しんどい", "無理", "できない", "諦め"]
        is_negative = any(kw in message for kw in negative_keywords)

        if is_negative:
            return (
                "今は大変な時期かもしれませんね。\n"
                "でも、ここまで頑張ってきた自分を褒めてあげてください。\n"
                "小さな一歩でも前に進んでいますウル！"
            )

        return (
            "目標に向かって頑張っているんですね！\n"
            "その調子で進んでいきましょうウル！"
        )


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_goal_expert(
    pool: Optional[Any] = None,
    organization_id: str = "",
) -> GoalExpert:
    """
    目標専門家エージェントを作成するファクトリ関数

    Args:
        pool: データベース接続プール
        organization_id: 組織ID

    Returns:
        GoalExpert: 作成された目標専門家エージェント
    """
    return GoalExpert(
        pool=pool,
        organization_id=organization_id,
    )
