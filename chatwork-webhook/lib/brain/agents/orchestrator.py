# lib/brain/agents/orchestrator.py
"""
ソウルくんの脳 - オーケストレーター（メインブレイン）

Ultimate Brain Phase 3: マルチエージェントシステムの司令塔

設計思想:
- 全てのリクエストを最初に受け取り、適切なエージェントに振り分ける
- エージェント間の協調を管理
- 最終的な応答を統合

主要機能:
1. リクエストのルーティング
2. エージェントの選択と委任
3. 応答の統合と品質管理
4. エージェント間の調停

設計書: docs/19_ultimate_brain_architecture.md セクション5.3
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from lib.brain.agents.base import (
    BaseAgent,
    AgentType,
    AgentStatus,
    AgentCapability,
    AgentMessage,
    AgentResponse,
    AgentContext,
    MessageType,
    MessagePriority,
    ExpertiseLevel,
    AGENT_TIMEOUT_SECONDS,
    MAX_CONCURRENT_AGENTS,
)


logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================

# エージェント選択の重み
EXPERTISE_WEIGHTS = {
    ExpertiseLevel.PRIMARY: 1.0,
    ExpertiseLevel.SECONDARY: 0.6,
    ExpertiseLevel.SUPPORTIVE: 0.3,
}

# 並列実行可能なエージェントの最大数
MAX_PARALLEL_AGENTS: int = 3

# 応答統合の確信度閾値
INTEGRATION_CONFIDENCE_THRESHOLD: float = 0.6

# エージェントルーティングのキーワードマッピング
AGENT_KEYWORDS: Dict[AgentType, List[str]] = {
    AgentType.TASK_EXPERT: [
        "タスク", "やること", "todo", "タスク作成", "タスク完了", "タスク検索",
        "優先順位", "リマインド", "期限", "締め切り", "締切", "遅延",
    ],
    AgentType.GOAL_EXPERT: [
        "目標", "ゴール", "目標設定", "目標達成", "進捗", "モチベーション",
        "やる気", "成長", "キャリア", "目指す", "達成",
    ],
    AgentType.KNOWLEDGE_EXPERT: [
        "知識", "ナレッジ", "覚えて", "教えて", "FAQ", "マニュアル",
        "ドキュメント", "検索", "調べて", "確認", "知りたい",
    ],
    AgentType.HR_EXPERT: [
        "規則", "ルール", "手続き", "申請", "休暇", "有給", "勤怠",
        "福利厚生", "研修", "人事", "相談", "制度",
    ],
    AgentType.EMOTION_EXPERT: [
        "疲れた", "つらい", "しんどい", "悩み", "不安", "心配",
        "嬉しい", "楽しい", "励まして", "相談", "聞いて",
    ],
    AgentType.ORGANIZATION_EXPERT: [
        "組織", "組織図", "部署", "チーム", "上司", "部下",
        "誰に", "担当", "責任者", "連絡先", "報告",
    ],
}

# アクションとエージェントのマッピング
ACTION_AGENT_MAPPING: Dict[str, AgentType] = {
    # タスク関連
    "task_create": AgentType.TASK_EXPERT,
    "task_search": AgentType.TASK_EXPERT,
    "task_complete": AgentType.TASK_EXPERT,
    "chatwork_task_create": AgentType.TASK_EXPERT,
    "chatwork_task_search": AgentType.TASK_EXPERT,
    "chatwork_task_complete": AgentType.TASK_EXPERT,

    # 目標関連
    "goal_setting_start": AgentType.GOAL_EXPERT,
    "goal_progress_report": AgentType.GOAL_EXPERT,
    "goal_status_check": AgentType.GOAL_EXPERT,

    # ナレッジ関連
    "query_knowledge": AgentType.KNOWLEDGE_EXPERT,
    "save_memory": AgentType.KNOWLEDGE_EXPERT,
    "query_memory": AgentType.KNOWLEDGE_EXPERT,
    "delete_memory": AgentType.KNOWLEDGE_EXPERT,
    "learn_knowledge": AgentType.KNOWLEDGE_EXPERT,
    "forget_knowledge": AgentType.KNOWLEDGE_EXPERT,
    "list_knowledge": AgentType.KNOWLEDGE_EXPERT,

    # 組織関連
    "query_org_chart": AgentType.ORGANIZATION_EXPERT,

    # 感情関連
    "daily_reflection": AgentType.EMOTION_EXPERT,

    # アナウンス
    "announcement_create": AgentType.TASK_EXPERT,

    # その他
    "general_conversation": AgentType.EMOTION_EXPERT,
}


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class AgentScore:
    """
    エージェントのスコアリング結果
    """
    agent_type: AgentType
    score: float = 0.0
    keyword_matches: List[str] = field(default_factory=list)
    action_match: bool = False
    capability_match: Optional[AgentCapability] = None


@dataclass
class RoutingDecision:
    """
    ルーティング決定
    """
    primary_agent: AgentType
    secondary_agents: List[AgentType] = field(default_factory=list)
    parallel_execution: bool = False
    confidence: float = 0.0
    reasoning: str = ""


@dataclass
class IntegratedResponse:
    """
    統合された応答
    """
    final_response: str = ""
    contributing_agents: List[AgentType] = field(default_factory=list)
    individual_responses: List[AgentResponse] = field(default_factory=list)
    overall_confidence: float = 0.0
    processing_time_ms: float = 0.0


# =============================================================================
# Orchestrator クラス
# =============================================================================

class Orchestrator(BaseAgent):
    """
    オーケストレーター（メインブレイン）

    マルチエージェントシステムの司令塔。
    全てのリクエストを受け取り、適切なエージェントに振り分ける。

    Attributes:
        agents: 管理するエージェントのマップ
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
            agent_type=AgentType.ORCHESTRATOR,
            pool=pool,
            organization_id=organization_id,
        )

        # 管理するエージェント
        self._agents: Dict[AgentType, BaseAgent] = {}

        # ルーティングキャッシュ
        self._routing_cache: Dict[str, RoutingDecision] = {}

        logger.info(
            "Orchestrator initialized",
            extra={"organization_id": organization_id}
        )

    # -------------------------------------------------------------------------
    # エージェント管理
    # -------------------------------------------------------------------------

    def register_agent(self, agent: BaseAgent) -> None:
        """
        エージェントを登録

        Args:
            agent: 登録するエージェント
        """
        self._agents[agent.agent_type] = agent
        agent.set_agent_registry(self._agents)

        logger.info(
            f"Agent registered: {agent.agent_type.value}",
            extra={"agent_type": agent.agent_type.value}
        )

    def register_agents(self, agents: List[BaseAgent]) -> None:
        """
        複数のエージェントを登録

        Args:
            agents: 登録するエージェントのリスト
        """
        for agent in agents:
            self.register_agent(agent)

        # 自分自身も登録
        self._agents[self._agent_type] = self
        self.set_agent_registry(self._agents)

    def get_agent(self, agent_type: AgentType) -> Optional[BaseAgent]:
        """
        エージェントを取得

        Args:
            agent_type: エージェントタイプ

        Returns:
            BaseAgent: エージェント（なければNone）
        """
        return self._agents.get(agent_type)

    def get_all_agents(self) -> List[BaseAgent]:
        """
        全エージェントを取得

        Returns:
            List[BaseAgent]: 全エージェントのリスト
        """
        return list(self._agents.values())

    # -------------------------------------------------------------------------
    # BaseAgent 実装
    # -------------------------------------------------------------------------

    def _initialize_capabilities(self) -> None:
        """エージェントの能力を初期化"""
        self._capabilities = [
            AgentCapability(
                capability_id="orchestration",
                name="オーケストレーション",
                description="リクエストのルーティングとエージェント間の調整",
                keywords=["調整", "振り分け", "管理"],
                actions=["route", "integrate", "coordinate"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.1,
            ),
            AgentCapability(
                capability_id="fallback",
                name="フォールバック対応",
                description="他のエージェントが対応できない場合の対応",
                keywords=["その他", "一般", "会話"],
                actions=["general_conversation", "fallback"],
                expertise_level=ExpertiseLevel.SECONDARY,
            ),
        ]

    def _register_handlers(self) -> None:
        """ハンドラーを登録"""
        self._handlers = {
            "route": self._handle_route,
            "integrate": self._handle_integrate,
            "coordinate": self._handle_coordinate,
            "general_conversation": self._handle_general_conversation,
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
        original_message = content.get("message", context.original_message)

        # アクションが明示されている場合はルーティング
        if action:
            return await self._route_by_action(context, action, content)

        # メッセージからルーティング決定
        routing = await self._decide_routing(original_message, context)

        if routing.parallel_execution:
            # 並列実行
            return await self._execute_parallel(context, routing, content)
        else:
            # 単一エージェントに委任
            return await self._execute_single(context, routing, content)

    def can_handle(
        self,
        action: str,
        context: AgentContext,
    ) -> bool:
        """
        指定されたアクションを処理できるか判定

        オーケストレーターは全てのアクションを受け付けて振り分ける

        Args:
            action: アクション名
            context: エージェントコンテキスト

        Returns:
            bool: 常にTrue
        """
        return True

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
            float: 確信度
        """
        # オーケストレーター自身のアクション
        if action in self._handlers:
            return 0.9

        # 他エージェントへ委任する場合
        if action in ACTION_AGENT_MAPPING:
            return 0.8

        # 不明なアクション
        return 0.5

    # -------------------------------------------------------------------------
    # ルーティング
    # -------------------------------------------------------------------------

    async def _decide_routing(
        self,
        message: str,
        context: AgentContext,
    ) -> RoutingDecision:
        """
        ルーティングを決定

        Args:
            message: ユーザーメッセージ
            context: エージェントコンテキスト

        Returns:
            RoutingDecision: ルーティング決定
        """
        # キャッシュチェック
        cache_key = f"{context.organization_id}:{message[:50]}"
        if cache_key in self._routing_cache:
            return self._routing_cache[cache_key]

        # エージェントをスコアリング
        scores = await self._score_agents(message, context)

        # スコアでソート
        sorted_scores = sorted(scores, key=lambda x: x.score, reverse=True)

        if not sorted_scores or sorted_scores[0].score < 0.1:
            # マッチするエージェントがない場合は感情専門家（一般会話）
            return RoutingDecision(
                primary_agent=AgentType.EMOTION_EXPERT,
                confidence=0.5,
                reasoning="マッチするエージェントがないため、一般会話として処理",
            )

        primary = sorted_scores[0]
        secondary: List[AgentType] = []

        # セカンダリエージェントの選択
        for score in sorted_scores[1:]:
            if score.score > 0.3 and len(secondary) < 2:
                secondary.append(score.agent_type)

        # 並列実行が必要か判断
        parallel = len(secondary) > 0 and sorted_scores[1].score > 0.5

        decision = RoutingDecision(
            primary_agent=primary.agent_type,
            secondary_agents=secondary,
            parallel_execution=parallel,
            confidence=primary.score,
            reasoning=f"キーワードマッチ: {primary.keyword_matches}",
        )

        # キャッシュに保存
        self._routing_cache[cache_key] = decision

        logger.debug(
            f"Routing decision: {decision.primary_agent.value}",
            extra={
                "confidence": decision.confidence,
                "secondary": [a.value for a in decision.secondary_agents],
            }
        )

        return decision

    async def _score_agents(
        self,
        message: str,
        context: AgentContext,
    ) -> List[AgentScore]:
        """
        各エージェントをスコアリング

        Args:
            message: ユーザーメッセージ
            context: エージェントコンテキスト

        Returns:
            List[AgentScore]: スコアのリスト
        """
        scores = []
        message_lower = message.lower()

        for agent_type, keywords in AGENT_KEYWORDS.items():
            if agent_type == AgentType.ORCHESTRATOR:
                continue

            score = AgentScore(agent_type=agent_type)

            # キーワードマッチング
            for keyword in keywords:
                if keyword.lower() in message_lower:
                    score.keyword_matches.append(keyword)
                    score.score += 0.15

            # エージェントが登録されている場合、能力もチェック
            agent = self._agents.get(agent_type)
            if agent:
                for capability in agent.capabilities:
                    for kw in capability.keywords:
                        if kw.lower() in message_lower and kw not in score.keyword_matches:
                            score.keyword_matches.append(kw)
                            score.score += 0.1 * EXPERTISE_WEIGHTS.get(
                                capability.expertise_level, 0.3
                            )

            # スコアを正規化（0.0〜1.0）
            score.score = min(score.score, 1.0)

            scores.append(score)

        return scores

    async def _route_by_action(
        self,
        context: AgentContext,
        action: str,
        content: Dict[str, Any],
    ) -> AgentResponse:
        """
        アクションに基づいてルーティング

        Args:
            context: エージェントコンテキスト
            action: アクション名
            content: リクエスト内容

        Returns:
            AgentResponse: 処理結果
        """
        # アクションに対応するエージェントを取得
        agent_type = ACTION_AGENT_MAPPING.get(action)

        if not agent_type:
            # マッピングがない場合はメッセージからルーティング
            message = content.get("message", "")
            routing = await self._decide_routing(message, context)
            agent_type = routing.primary_agent

        agent = self._agents.get(agent_type)
        if not agent:
            logger.warning(f"Agent not registered: {agent_type.value}")
            return AgentResponse(
                agent_type=self._agent_type,
                success=False,
                error_message=f"エージェント {agent_type.value} が登録されていません",
            )

        # エージェントに委任
        return await self.delegate_to(agent_type, context, content)

    # -------------------------------------------------------------------------
    # 実行
    # -------------------------------------------------------------------------

    async def _execute_single(
        self,
        context: AgentContext,
        routing: RoutingDecision,
        content: Dict[str, Any],
    ) -> AgentResponse:
        """
        単一エージェントで実行

        Args:
            context: エージェントコンテキスト
            routing: ルーティング決定
            content: リクエスト内容

        Returns:
            AgentResponse: 処理結果
        """
        agent = self._agents.get(routing.primary_agent)
        if not agent:
            return AgentResponse(
                agent_type=self._agent_type,
                success=False,
                error_message=f"エージェント {routing.primary_agent.value} が見つかりません",
            )

        return await self.delegate_to(routing.primary_agent, context, content)

    async def _execute_parallel(
        self,
        context: AgentContext,
        routing: RoutingDecision,
        content: Dict[str, Any],
    ) -> AgentResponse:
        """
        複数エージェントで並列実行

        Args:
            context: エージェントコンテキスト
            routing: ルーティング決定
            content: リクエスト内容

        Returns:
            AgentResponse: 統合された処理結果
        """
        agents_to_execute = [routing.primary_agent] + routing.secondary_agents[:MAX_PARALLEL_AGENTS - 1]

        # 並列実行
        tasks = []
        for agent_type in agents_to_execute:
            agent = self._agents.get(agent_type)
            if agent:
                # コンテキストをコピー（独立して実行）
                agent_context = AgentContext(
                    organization_id=context.organization_id,
                    user_id=context.user_id,
                    room_id=context.room_id,
                    session_id=context.session_id,
                    original_message=context.original_message,
                    brain_context=context.brain_context,
                    current_agent=agent_type,
                    depth=context.depth + 1,
                )
                message = AgentMessage(
                    from_agent=self._agent_type,
                    to_agent=agent_type,
                    content=content,
                )
                tasks.append(agent.handle_message(agent_context, message))

        # タイムアウト付きで待機
        try:
            responses = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=AGENT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Parallel execution timed out")
            responses = []

        # 応答を統合
        return self._integrate_responses(responses, routing)

    def _integrate_responses(
        self,
        responses: List[Any],
        routing: RoutingDecision,
    ) -> AgentResponse:
        """
        複数の応答を統合

        Args:
            responses: 各エージェントからの応答
            routing: ルーティング決定

        Returns:
            AgentResponse: 統合された応答
        """
        valid_responses = []
        for r in responses:
            if isinstance(r, AgentResponse) and r.success:
                valid_responses.append(r)
            elif isinstance(r, Exception):
                logger.error(f"Agent execution error: {r}")

        if not valid_responses:
            return AgentResponse(
                agent_type=self._agent_type,
                success=False,
                error_message="どのエージェントも応答できませんでした",
            )

        # プライマリエージェントの応答を優先
        primary_response = None
        for r in valid_responses:
            if r.agent_type == routing.primary_agent:
                primary_response = r
                break

        if primary_response:
            # プライマリの応答に補足情報を追加
            result = primary_response.result.copy()
            for r in valid_responses:
                if r.agent_type != routing.primary_agent:
                    supplementary = r.result.get("supplementary", [])
                    if supplementary:
                        result.setdefault("supplementary", []).extend(supplementary)

            return AgentResponse(
                agent_type=routing.primary_agent,
                success=True,
                result=result,
                confidence=primary_response.confidence,
            )

        # プライマリがなければ最初の有効な応答を使用
        return valid_responses[0]

    # -------------------------------------------------------------------------
    # ハンドラー
    # -------------------------------------------------------------------------

    async def _handle_route(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """ルーティングハンドラー"""
        message = content.get("message", "")
        routing = await self._decide_routing(message, context)
        return {
            "primary_agent": routing.primary_agent.value,
            "secondary_agents": [a.value for a in routing.secondary_agents],
            "confidence": routing.confidence,
        }

    async def _handle_integrate(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """統合ハンドラー"""
        responses = content.get("responses", [])
        # 統合ロジック
        return {"integrated": True, "count": len(responses)}

    async def _handle_coordinate(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """調整ハンドラー"""
        agents = content.get("agents", [])
        # 調整ロジック
        return {"coordinated": True, "agents": agents}

    async def _handle_general_conversation(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """一般会話ハンドラー（フォールバック）"""
        # 感情専門家に委任
        if AgentType.EMOTION_EXPERT in self._agents:
            response = await self.delegate_to(
                AgentType.EMOTION_EXPERT,
                context,
                content,
            )
            return response.result

        return {
            "response": "お話しいただきありがとうございますウル！",
            "handled_by": "orchestrator_fallback",
        }

    # -------------------------------------------------------------------------
    # ユーティリティ
    # -------------------------------------------------------------------------

    def clear_routing_cache(self) -> None:
        """ルーティングキャッシュをクリア"""
        self._routing_cache.clear()

    def get_agent_stats(self) -> Dict[AgentType, Dict[str, Any]]:
        """
        全エージェントの統計を取得

        Returns:
            Dict: エージェントタイプ→統計のマップ
        """
        stats = {}
        for agent_type, agent in self._agents.items():
            stats[agent_type] = {
                "total_requests": agent.stats.total_requests,
                "success_rate": agent.stats.success_rate,
                "avg_processing_time_ms": agent.stats.avg_processing_time_ms,
                "status": agent.status.value,
            }
        return stats


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_orchestrator(
    pool: Optional[Any] = None,
    organization_id: str = "",
) -> Orchestrator:
    """
    オーケストレーターを作成するファクトリ関数

    Args:
        pool: データベース接続プール
        organization_id: 組織ID

    Returns:
        Orchestrator: 作成されたオーケストレーター
    """
    return Orchestrator(
        pool=pool,
        organization_id=organization_id,
    )
