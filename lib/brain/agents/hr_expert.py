# lib/brain/agents/hr_expert.py
"""
ソウルくんの脳 - HR専門家エージェント

Ultimate Brain Phase 3: 人事・労務に特化したエキスパートエージェント

設計思想:
- 社内規則や手続きを正確に伝える
- 困っている社員を適切な窓口につなぐ
- プライバシーに配慮しつつサポート

主要機能:
1. 社内規則の説明
2. 各種手続きの案内
3. 相談窓口への誘導
4. 福利厚生の案内

設計書: docs/19_ultimate_brain_architecture.md セクション5.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
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

# 規則関連のキーワード
RULE_KEYWORDS = [
    "規則", "ルール", "規定", "決まり", "禁止",
    "してはいけない", "ダメ", "やっていいの", "許可",
    "社則", "就業規則", "服務規程",
]

# 手続き関連のキーワード
PROCEDURE_KEYWORDS = [
    "手続き", "申請", "届出", "届け出", "フォーム",
    "書類", "提出", "いつまで", "期限", "締め切り",
    "どこに", "どうやって", "方法", "やり方",
]

# 休暇関連のキーワード
LEAVE_KEYWORDS = [
    "休み", "休暇", "有給", "有休", "年休",
    "欠勤", "遅刻", "早退", "時短",
    "産休", "育休", "介護休暇", "看護休暇",
    "忌引", "慶弔", "振替", "代休",
]

# 給与・福利厚生のキーワード
BENEFIT_KEYWORDS = [
    "給与", "給料", "賞与", "ボーナス", "昇給",
    "手当", "交通費", "経費", "精算",
    "福利厚生", "保険", "年金", "健康診断",
    "研修", "資格", "補助", "支援",
]

# 相談関連のキーワード
CONSULTATION_KEYWORDS = [
    "相談", "困って", "悩んで", "どうしたら",
    "誰に聞けば", "窓口", "担当", "連絡先",
    "ハラスメント", "パワハラ", "セクハラ",
    "メンタル", "体調", "病気",
]

# 入退社関連のキーワード
EMPLOYMENT_KEYWORDS = [
    "入社", "退社", "退職", "異動", "転勤",
    "配属", "出向", "復職", "休職",
]


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class RuleInfo:
    """
    規則情報
    """
    rule_id: str = ""
    category: str = ""
    title: str = ""
    summary: str = ""
    full_text: str = ""
    effective_date: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    source_document: str = ""


@dataclass
class ProcedureInfo:
    """
    手続き情報
    """
    procedure_id: str = ""
    name: str = ""
    description: str = ""
    steps: List[str] = field(default_factory=list)
    required_documents: List[str] = field(default_factory=list)
    deadline_info: str = ""
    contact_person: str = ""
    form_url: str = ""


@dataclass
class BenefitInfo:
    """
    福利厚生情報
    """
    benefit_id: str = ""
    name: str = ""
    description: str = ""
    eligibility: str = ""
    how_to_apply: str = ""
    contact: str = ""


@dataclass
class ConsultationGuide:
    """
    相談窓口案内
    """
    topic: str = ""
    recommended_contacts: List[str] = field(default_factory=list)
    external_resources: List[str] = field(default_factory=list)
    notes: str = ""


# =============================================================================
# HRExpert クラス
# =============================================================================

class HRExpert(BaseAgent):
    """
    HR専門家エージェント

    人事・労務関連のあらゆる質問に対応する専門家。
    規則説明、手続き案内、相談窓口への誘導を行う。

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
            agent_type=AgentType.HR_EXPERT,
            pool=pool,
            organization_id=organization_id,
        )

        logger.info(
            "HRExpert initialized",
            extra={"organization_id": organization_id}
        )

    # -------------------------------------------------------------------------
    # BaseAgent 実装
    # -------------------------------------------------------------------------

    def _initialize_capabilities(self) -> None:
        """エージェントの能力を初期化"""
        self._capabilities = [
            AgentCapability(
                capability_id="rule_explanation",
                name="規則説明",
                description="社内規則やルールを説明する",
                keywords=RULE_KEYWORDS,
                actions=["explain_rule", "search_rules"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="procedure_guide",
                name="手続き案内",
                description="各種手続きの方法を案内する",
                keywords=PROCEDURE_KEYWORDS,
                actions=["guide_procedure", "get_form"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="leave_management",
                name="休暇管理",
                description="休暇に関する情報を提供する",
                keywords=LEAVE_KEYWORDS,
                actions=["check_leave", "apply_leave", "leave_info"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="benefit_info",
                name="福利厚生案内",
                description="福利厚生の情報を提供する",
                keywords=BENEFIT_KEYWORDS,
                actions=["benefit_info", "search_benefits"],
                expertise_level=ExpertiseLevel.SECONDARY,
                confidence_boost=0.1,
            ),
            AgentCapability(
                capability_id="consultation_guide",
                name="相談窓口案内",
                description="適切な相談窓口を案内する",
                keywords=CONSULTATION_KEYWORDS,
                actions=["guide_consultation", "find_contact"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.2,  # 相談は重要度高
            ),
            AgentCapability(
                capability_id="employment_support",
                name="入退社サポート",
                description="入退社に関する手続きをサポートする",
                keywords=EMPLOYMENT_KEYWORDS,
                actions=["onboarding_guide", "offboarding_guide", "transfer_guide"],
                expertise_level=ExpertiseLevel.SECONDARY,
                confidence_boost=0.1,
            ),
        ]

    def _register_handlers(self) -> None:
        """ハンドラーを登録"""
        self._handlers = {
            # 規則関連
            "explain_rule": self._handle_explain_rule,
            "search_rules": self._handle_search_rules,
            # 手続き関連
            "guide_procedure": self._handle_guide_procedure,
            "get_form": self._handle_get_form,
            # 休暇関連
            "check_leave": self._handle_check_leave,
            "apply_leave": self._handle_apply_leave,
            "leave_info": self._handle_leave_info,
            # 福利厚生
            "benefit_info": self._handle_benefit_info,
            "search_benefits": self._handle_search_benefits,
            # 相談窓口
            "guide_consultation": self._handle_guide_consultation,
            "find_contact": self._handle_find_contact,
            # 入退社
            "onboarding_guide": self._handle_onboarding_guide,
            "offboarding_guide": self._handle_offboarding_guide,
            "transfer_guide": self._handle_transfer_guide,
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
                logger.error(f"Handler error: {action}: {type(e).__name__}", exc_info=True)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=False,
                    error_message=type(e).__name__,
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
                logger.error(f"Handler error: {inferred_action}: {type(e).__name__}", exc_info=True)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=False,
                    error_message=type(e).__name__,
                )

        return AgentResponse(
            request_id=message.id,
            agent_type=self._agent_type,
            success=False,
            error_message="HR関連の操作を特定できませんでした",
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
    # アクション推論
    # -------------------------------------------------------------------------

    def _infer_action(self, message: str) -> Optional[str]:
        """
        メッセージからアクションを推論
        """
        message_lower = message.lower()

        # 相談関連（優先度高）
        for keyword in CONSULTATION_KEYWORDS:
            if keyword.lower() in message_lower:
                return "guide_consultation"

        # 休暇関連
        for keyword in LEAVE_KEYWORDS:
            if keyword.lower() in message_lower:
                return "leave_info"

        # 手続き関連
        for keyword in PROCEDURE_KEYWORDS:
            if keyword.lower() in message_lower:
                return "guide_procedure"

        # 規則関連
        for keyword in RULE_KEYWORDS:
            if keyword.lower() in message_lower:
                return "explain_rule"

        # 福利厚生
        for keyword in BENEFIT_KEYWORDS:
            if keyword.lower() in message_lower:
                return "benefit_info"

        # 入退社
        for keyword in EMPLOYMENT_KEYWORDS:
            if keyword.lower() in message_lower:
                if "入社" in message_lower:
                    return "onboarding_guide"
                elif "退社" in message_lower or "退職" in message_lower:
                    return "offboarding_guide"
                else:
                    return "transfer_guide"

        return None

    # -------------------------------------------------------------------------
    # ハンドラー
    # -------------------------------------------------------------------------

    async def _handle_explain_rule(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """規則説明ハンドラー"""
        query = content.get("query", content.get("message", ""))

        return {
            "action": "explain_rule",
            "query": query,
            "response": "社内規則を調べますウル！",
            "requires_external_handler": True,
        }

    async def _handle_search_rules(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """規則検索ハンドラー"""
        query = content.get("query", content.get("message", ""))

        return {
            "action": "search_rules",
            "query": query,
            "response": "関連する規則を探しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_guide_procedure(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """手続き案内ハンドラー"""
        procedure_type = content.get("procedure_type", "")
        message = content.get("message", "")

        return {
            "action": "guide_procedure",
            "procedure_type": procedure_type,
            "query": message,
            "response": "手続きの方法をご案内しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_get_form(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """フォーム取得ハンドラー"""
        form_type = content.get("form_type", "")

        return {
            "action": "get_form",
            "form_type": form_type,
            "response": "必要なフォームをお探ししますウル！",
            "requires_external_handler": True,
        }

    async def _handle_check_leave(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """休暇残日数確認ハンドラー"""
        user_id = content.get("user_id", context.user_id)

        return {
            "action": "check_leave",
            "user_id": user_id,
            "response": "休暇の残り日数を確認しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_apply_leave(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """休暇申請ハンドラー"""
        leave_type = content.get("leave_type", "")
        start_date = content.get("start_date", "")
        end_date = content.get("end_date", "")

        return {
            "action": "apply_leave",
            "leave_type": leave_type,
            "start_date": start_date,
            "end_date": end_date,
            "response": "休暇申請の手続きをご案内しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_leave_info(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """休暇情報ハンドラー"""
        leave_type = content.get("leave_type", "")
        message = content.get("message", "")

        return {
            "action": "leave_info",
            "leave_type": leave_type,
            "query": message,
            "response": "休暇制度についてご説明しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_benefit_info(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """福利厚生情報ハンドラー"""
        benefit_type = content.get("benefit_type", "")
        message = content.get("message", "")

        return {
            "action": "benefit_info",
            "benefit_type": benefit_type,
            "query": message,
            "response": "福利厚生についてご説明しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_search_benefits(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """福利厚生検索ハンドラー"""
        query = content.get("query", content.get("message", ""))

        return {
            "action": "search_benefits",
            "query": query,
            "response": "利用できる福利厚生を探しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_guide_consultation(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """相談窓口案内ハンドラー"""
        topic = content.get("topic", content.get("message", ""))

        # センシティブな相談は慎重に対応
        is_sensitive = self._is_sensitive_consultation(topic)

        return {
            "action": "guide_consultation",
            "topic": topic,
            "is_sensitive": is_sensitive,
            "response": "適切な相談窓口をご案内しますウル。" if is_sensitive else "相談窓口をご案内しますウル！",
            "requires_external_handler": True,
            "note": "プライバシーに配慮した対応が必要" if is_sensitive else "",
        }

    async def _handle_find_contact(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """連絡先検索ハンドラー"""
        department = content.get("department", "")
        role = content.get("role", "")

        return {
            "action": "find_contact",
            "department": department,
            "role": role,
            "response": "担当者の連絡先をお探ししますウル！",
            "requires_external_handler": True,
        }

    async def _handle_onboarding_guide(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """入社手続き案内ハンドラー"""
        join_date = content.get("join_date", "")

        return {
            "action": "onboarding_guide",
            "join_date": join_date,
            "response": "入社手続きをご案内しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_offboarding_guide(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """退社手続き案内ハンドラー"""
        leave_date = content.get("leave_date", "")

        return {
            "action": "offboarding_guide",
            "leave_date": leave_date,
            "response": "退社手続きをご案内しますウル。",
            "requires_external_handler": True,
        }

    async def _handle_transfer_guide(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """異動手続き案内ハンドラー"""
        transfer_type = content.get("transfer_type", "")

        return {
            "action": "transfer_guide",
            "transfer_type": transfer_type,
            "response": "異動に関する手続きをご案内しますウル！",
            "requires_external_handler": True,
        }

    # -------------------------------------------------------------------------
    # ユーティリティ
    # -------------------------------------------------------------------------

    def _is_sensitive_consultation(self, topic: str) -> bool:
        """
        センシティブな相談かどうかを判定

        Args:
            topic: 相談トピック

        Returns:
            bool: センシティブな場合True
        """
        sensitive_keywords = [
            "ハラスメント", "パワハラ", "セクハラ", "いじめ",
            "メンタル", "うつ", "病気", "体調不良",
            "退職", "辞めたい", "転職",
            "給与", "待遇", "不満",
        ]

        topic_lower = topic.lower()
        return any(kw in topic_lower for kw in sensitive_keywords)


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_hr_expert(
    pool: Optional[Any] = None,
    organization_id: str = "",
) -> HRExpert:
    """
    HR専門家エージェントを作成するファクトリ関数
    """
    return HRExpert(
        pool=pool,
        organization_id=organization_id,
    )
