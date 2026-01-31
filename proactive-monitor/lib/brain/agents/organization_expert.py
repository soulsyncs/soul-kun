# lib/brain/agents/organization_expert.py
"""
ソウルくんの脳 - 組織専門家エージェント

Ultimate Brain Phase 3: 組織構造・人間関係に特化したエキスパートエージェント

設計思想:
- 組織図を深く理解し、適切な人を繋ぐ
- 人間関係の力学を把握してサポート
- 組織の暗黙知を活用

主要機能:
1. 組織図クエリ
2. 適切な相談相手の推薦
3. 人間関係の把握
4. コミュニケーションルートの提案

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
# SoT: lib/brain/models.py から統一版をimport
from lib.brain.models import PersonInfo


logger = logging.getLogger(__name__)


# =============================================================================
# Enum
# =============================================================================

class RelationshipType(str, Enum):
    """関係タイプ"""
    SUPERIOR = "superior"          # 上司
    SUBORDINATE = "subordinate"    # 部下
    COLLEAGUE = "colleague"        # 同僚
    MENTOR = "mentor"              # メンター
    MENTEE = "mentee"              # メンティー
    COLLABORATOR = "collaborator"  # 協力者
    STAKEHOLDER = "stakeholder"    # ステークホルダー


class CommunicationChannel(str, Enum):
    """コミュニケーションチャネル"""
    DIRECT = "direct"              # 直接
    CHAT = "chat"                  # チャット
    EMAIL = "email"                # メール
    MEETING = "meeting"            # ミーティング
    VIA_MANAGER = "via_manager"    # 上司経由


class QueryType(str, Enum):
    """クエリタイプ"""
    WHO_IS = "who_is"              # 誰が〜
    WHO_KNOWS = "who_knows"        # 誰が知っているか
    WHO_TO_ASK = "who_to_ask"      # 誰に聞くべきか
    REPORT_TO = "report_to"        # 誰の部下か
    MANAGES = "manages"            # 誰を管理しているか
    BELONGS_TO = "belongs_to"      # 何部署か


# =============================================================================
# 定数
# =============================================================================

# 組織図クエリのキーワード
ORG_CHART_KEYWORDS = [
    "組織図", "組織", "部署", "チーム", "課",
    "誰", "どこ", "所属", "配属",
]

# 人物クエリのキーワード
PERSON_KEYWORDS = [
    "担当", "責任者", "リーダー", "マネージャー",
    "部長", "課長", "係長", "主任",
    "誰が", "誰の", "誰に",
]

# 関係クエリのキーワード
RELATIONSHIP_KEYWORDS = [
    "上司", "部下", "同僚", "メンター",
    "報告", "レポートライン", "指示系統",
]

# 相談相手推薦のキーワード
RECOMMENDATION_KEYWORDS = [
    "誰に聞けば", "誰に相談", "誰がわかる",
    "詳しい人", "担当者", "専門家",
]

# コミュニケーションのキーワード
COMMUNICATION_KEYWORDS = [
    "連絡", "相談", "報告", "確認",
    "どうやって", "どこに", "ルート",
]

# 専門分野のキーワード
EXPERTISE_KEYWORDS = [
    "専門", "得意", "詳しい", "経験",
    "スキル", "資格", "実績",
]


# =============================================================================
# データクラス
# =============================================================================

# PersonInfo は lib/brain/models.py からimport済み
# 重複定義を避けるため、ここでは定義しない（SoT: models.py）


@dataclass
class DepartmentInfo:
    """
    部署情報
    """
    department_id: str = ""
    name: str = ""
    parent_department: str = ""
    manager: Optional[PersonInfo] = None
    members: List[PersonInfo] = field(default_factory=list)
    responsibilities: List[str] = field(default_factory=list)


@dataclass
class RelationshipInfo:
    """
    関係情報
    """
    from_person: str = ""
    to_person: str = ""
    relationship_type: RelationshipType = RelationshipType.COLLEAGUE
    strength: float = 0.5  # 0.0〜1.0
    context: str = ""


@dataclass
class RecommendationResult:
    """
    推薦結果
    """
    recommended_person: Optional[PersonInfo] = None
    reason: str = ""
    alternative_persons: List[PersonInfo] = field(default_factory=list)
    communication_channel: CommunicationChannel = CommunicationChannel.DIRECT
    notes: str = ""


@dataclass
class CommunicationRoute:
    """
    コミュニケーションルート
    """
    start_person: str = ""
    end_person: str = ""
    route: List[str] = field(default_factory=list)
    recommended_channel: CommunicationChannel = CommunicationChannel.DIRECT
    formality_level: str = ""  # "formal", "semi-formal", "casual"
    notes: str = ""


# =============================================================================
# OrganizationExpert クラス
# =============================================================================

class OrganizationExpert(BaseAgent):
    """
    組織専門家エージェント

    組織構造と人間関係を深く理解し、適切な人を繋ぐ専門家。
    組織図クエリ、相談相手推薦、コミュニケーションルート提案を行う。

    Attributes:
        pool: データベース接続プール
        organization_id: 組織ID
        org_graph: OrganizationGraphインスタンス（Phase 3で追加）
    """

    def __init__(
        self,
        pool: Optional[Any] = None,
        organization_id: str = "",
        org_graph: Optional[Any] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            org_graph: OrganizationGraphインスタンス
        """
        super().__init__(
            agent_type=AgentType.ORGANIZATION_EXPERT,
            pool=pool,
            organization_id=organization_id,
        )

        self._org_graph = org_graph

        logger.info(
            "OrganizationExpert initialized",
            extra={
                "organization_id": organization_id,
                "has_org_graph": org_graph is not None,
            }
        )

    # -------------------------------------------------------------------------
    # BaseAgent 実装
    # -------------------------------------------------------------------------

    def _initialize_capabilities(self) -> None:
        """エージェントの能力を初期化"""
        self._capabilities = [
            AgentCapability(
                capability_id="org_chart_query",
                name="組織図クエリ",
                description="組織図に関する質問に答える",
                keywords=ORG_CHART_KEYWORDS,
                actions=["query_org_chart", "get_department", "get_team_members"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="person_query",
                name="人物クエリ",
                description="人物に関する情報を提供する",
                keywords=PERSON_KEYWORDS,
                actions=["get_person_info", "find_person", "get_role"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="relationship_query",
                name="関係クエリ",
                description="人間関係を把握して回答する",
                keywords=RELATIONSHIP_KEYWORDS,
                actions=["get_relationship", "get_report_line", "get_team_structure"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="person_recommendation",
                name="相談相手推薦",
                description="適切な相談相手を推薦する",
                keywords=RECOMMENDATION_KEYWORDS,
                actions=["recommend_person", "find_expert", "suggest_contact"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.2,
            ),
            AgentCapability(
                capability_id="communication_route",
                name="コミュニケーションルート",
                description="適切なコミュニケーション方法を提案する",
                keywords=COMMUNICATION_KEYWORDS,
                actions=["suggest_route", "get_contact_method", "plan_communication"],
                expertise_level=ExpertiseLevel.SECONDARY,
                confidence_boost=0.1,
            ),
            AgentCapability(
                capability_id="expertise_search",
                name="専門分野検索",
                description="特定の専門分野を持つ人を検索する",
                keywords=EXPERTISE_KEYWORDS,
                actions=["search_by_expertise", "find_specialist", "get_skill_holders"],
                expertise_level=ExpertiseLevel.SECONDARY,
                confidence_boost=0.1,
            ),
        ]

    def _register_handlers(self) -> None:
        """ハンドラーを登録"""
        self._handlers = {
            # 組織図
            "query_org_chart": self._handle_query_org_chart,
            "get_department": self._handle_get_department,
            "get_team_members": self._handle_get_team_members,
            # 人物
            "get_person_info": self._handle_get_person_info,
            "find_person": self._handle_find_person,
            "get_role": self._handle_get_role,
            # 関係
            "get_relationship": self._handle_get_relationship,
            "get_report_line": self._handle_get_report_line,
            "get_team_structure": self._handle_get_team_structure,
            # 推薦
            "recommend_person": self._handle_recommend_person,
            "find_expert": self._handle_find_expert,
            "suggest_contact": self._handle_suggest_contact,
            # コミュニケーション
            "suggest_route": self._handle_suggest_route,
            "get_contact_method": self._handle_get_contact_method,
            "plan_communication": self._handle_plan_communication,
            # 専門分野
            "search_by_expertise": self._handle_search_by_expertise,
            "find_specialist": self._handle_find_specialist,
            "get_skill_holders": self._handle_get_skill_holders,
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
        inferred_action = self._infer_action(original_message)

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

        return AgentResponse(
            request_id=message.id,
            agent_type=self._agent_type,
            success=False,
            error_message="組織関連の操作を特定できませんでした",
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

        # org_graphがある場合は信頼度アップ
        if self._org_graph is not None:
            base_confidence += 0.05

        return min(base_confidence, 1.0)

    # -------------------------------------------------------------------------
    # アクション推論
    # -------------------------------------------------------------------------

    def _infer_action(self, message: str) -> Optional[str]:
        """
        メッセージからアクションを推論
        """
        message_lower = message.lower()

        # 相談相手推薦（優先度高）
        for keyword in RECOMMENDATION_KEYWORDS:
            if keyword in message_lower:
                return "recommend_person"

        # 専門家検索
        for keyword in EXPERTISE_KEYWORDS:
            if keyword in message_lower:
                return "find_expert"

        # 人物クエリ
        for keyword in PERSON_KEYWORDS:
            if keyword in message_lower:
                return "get_person_info"

        # 関係クエリ
        for keyword in RELATIONSHIP_KEYWORDS:
            if keyword in message_lower:
                return "get_relationship"

        # 組織図クエリ
        for keyword in ORG_CHART_KEYWORDS:
            if keyword in message_lower:
                return "query_org_chart"

        # コミュニケーション
        for keyword in COMMUNICATION_KEYWORDS:
            if keyword in message_lower:
                return "suggest_route"

        return None

    # -------------------------------------------------------------------------
    # ハンドラー
    # -------------------------------------------------------------------------

    async def _handle_query_org_chart(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """組織図クエリハンドラー"""
        query = content.get("query", content.get("message", ""))

        return {
            "action": "query_org_chart",
            "query": query,
            "response": "組織図を確認しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_get_department(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """部署情報取得ハンドラー"""
        department_name = content.get("department_name", "")

        return {
            "action": "get_department",
            "department_name": department_name,
            "response": f"{department_name}の情報を取得しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_get_team_members(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """チームメンバー取得ハンドラー"""
        team_name = content.get("team_name", "")

        return {
            "action": "get_team_members",
            "team_name": team_name,
            "response": "チームメンバーを確認しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_get_person_info(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """人物情報取得ハンドラー"""
        person_name = content.get("person_name", "")

        return {
            "action": "get_person_info",
            "person_name": person_name,
            "response": f"{person_name}さんの情報を取得しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_find_person(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """人物検索ハンドラー"""
        query = content.get("query", content.get("message", ""))

        return {
            "action": "find_person",
            "query": query,
            "response": "該当する方を探しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_get_role(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """役割取得ハンドラー"""
        person_name = content.get("person_name", "")

        return {
            "action": "get_role",
            "person_name": person_name,
            "response": "役割を確認しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_get_relationship(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """関係取得ハンドラー"""
        person1 = content.get("person1", "")
        person2 = content.get("person2", "")

        return {
            "action": "get_relationship",
            "person1": person1,
            "person2": person2,
            "response": "関係を確認しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_get_report_line(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """レポートライン取得ハンドラー"""
        person_name = content.get("person_name", "")

        return {
            "action": "get_report_line",
            "person_name": person_name,
            "response": "レポートラインを確認しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_get_team_structure(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """チーム構造取得ハンドラー"""
        team_name = content.get("team_name", "")

        return {
            "action": "get_team_structure",
            "team_name": team_name,
            "response": "チームの構造を確認しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_recommend_person(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """相談相手推薦ハンドラー"""
        topic = content.get("topic", content.get("message", ""))

        return {
            "action": "recommend_person",
            "topic": topic,
            "response": "相談できる方をお探ししますウル！",
            "requires_external_handler": True,
        }

    async def _handle_find_expert(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """専門家検索ハンドラー"""
        expertise_area = content.get("expertise_area", content.get("message", ""))

        return {
            "action": "find_expert",
            "expertise_area": expertise_area,
            "response": "専門家をお探ししますウル！",
            "requires_external_handler": True,
        }

    async def _handle_suggest_contact(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """連絡先提案ハンドラー"""
        purpose = content.get("purpose", "")

        return {
            "action": "suggest_contact",
            "purpose": purpose,
            "response": "連絡先をご案内しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_suggest_route(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """コミュニケーションルート提案ハンドラー"""
        target_person = content.get("target_person", "")
        purpose = content.get("purpose", "")

        return {
            "action": "suggest_route",
            "target_person": target_person,
            "purpose": purpose,
            "response": "適切な連絡方法をご提案しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_get_contact_method(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """連絡方法取得ハンドラー"""
        person_name = content.get("person_name", "")

        return {
            "action": "get_contact_method",
            "person_name": person_name,
            "response": "連絡方法を確認しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_plan_communication(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """コミュニケーション計画ハンドラー"""
        objective = content.get("objective", "")
        stakeholders = content.get("stakeholders", [])

        return {
            "action": "plan_communication",
            "objective": objective,
            "stakeholders": stakeholders,
            "response": "コミュニケーション計画を作成しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_search_by_expertise(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """専門分野検索ハンドラー"""
        expertise = content.get("expertise", content.get("message", ""))

        return {
            "action": "search_by_expertise",
            "expertise": expertise,
            "response": "該当する専門分野の方を探しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_find_specialist(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """スペシャリスト検索ハンドラー"""
        area = content.get("area", content.get("message", ""))

        return {
            "action": "find_specialist",
            "area": area,
            "response": "スペシャリストをお探ししますウル！",
            "requires_external_handler": True,
        }

    async def _handle_get_skill_holders(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """スキル保持者取得ハンドラー"""
        skill = content.get("skill", "")

        return {
            "action": "get_skill_holders",
            "skill": skill,
            "response": f"{skill}のスキルを持つ方を探しますウル！",
            "requires_external_handler": True,
        }


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_organization_expert(
    pool: Optional[Any] = None,
    organization_id: str = "",
    org_graph: Optional[Any] = None,
) -> OrganizationExpert:
    """
    組織専門家エージェントを作成するファクトリ関数
    """
    return OrganizationExpert(
        pool=pool,
        organization_id=organization_id,
        org_graph=org_graph,
    )
