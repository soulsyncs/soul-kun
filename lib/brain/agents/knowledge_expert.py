# lib/brain/agents/knowledge_expert.py
"""
ソウルくんの脳 - ナレッジ専門家エージェント

Ultimate Brain Phase 3: 知識管理に特化したエキスパートエージェント

設計思想:
- 組織の知識資産を効率的に管理
- 適切な情報を適切なタイミングで提供
- 学習と知識の蓄積を支援

主要機能:
1. 知識の検索と提供
2. 新しい知識の学習と保存
3. FAQ対応
4. ドキュメント検索

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

# 知識検索のキーワード
KNOWLEDGE_SEARCH_KEYWORDS = [
    "教えて", "知りたい", "調べて", "検索", "探して",
    "何", "どう", "どこ", "どれ", "いつ", "誰",
    "について", "とは", "方法", "やり方",
]

# 知識保存のキーワード
KNOWLEDGE_SAVE_KEYWORDS = [
    "覚えて", "記憶して", "保存して", "登録して",
    "メモして", "覚えといて", "忘れないで",
]

# 知識削除のキーワード
KNOWLEDGE_DELETE_KEYWORDS = [
    "忘れて", "削除して", "消して", "取り消して",
]

# FAQ関連のキーワード
FAQ_KEYWORDS = [
    "よくある質問", "FAQ", "質問", "聞きたい",
]

# ドキュメント関連のキーワード
DOCUMENT_KEYWORDS = [
    "ドキュメント", "資料", "マニュアル", "手順書",
    "ファイル", "書類", "規定", "規則",
]

# 検索結果の最大数
DEFAULT_SEARCH_LIMIT = 5


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class KnowledgeItem:
    """
    知識アイテム
    """
    id: str = ""
    organization_id: str = ""
    category: str = ""
    title: str = ""
    content: str = ""
    keywords: List[str] = field(default_factory=list)
    source: str = ""
    confidence: float = 1.0
    created_by: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class SearchResult:
    """
    検索結果
    """
    items: List[KnowledgeItem] = field(default_factory=list)
    total_count: int = 0
    query: str = ""
    search_type: str = ""  # "keyword", "semantic", "hybrid"
    execution_time_ms: float = 0.0


@dataclass
class FAQItem:
    """
    FAQアイテム
    """
    id: str = ""
    question: str = ""
    answer: str = ""
    category: str = ""
    frequency: int = 0
    last_asked_at: Optional[datetime] = None


# =============================================================================
# KnowledgeExpert クラス
# =============================================================================

class KnowledgeExpert(BaseAgent):
    """
    ナレッジ専門家エージェント

    知識管理のあらゆる側面に対応する専門家。
    知識の検索、保存、FAQ対応を行う。

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
            agent_type=AgentType.KNOWLEDGE_EXPERT,
            pool=pool,
            organization_id=organization_id,
        )

        logger.info(
            "KnowledgeExpert initialized",
            extra={"organization_id": organization_id}
        )

    # -------------------------------------------------------------------------
    # BaseAgent 実装
    # -------------------------------------------------------------------------

    def _initialize_capabilities(self) -> None:
        """エージェントの能力を初期化"""
        self._capabilities = [
            AgentCapability(
                capability_id="knowledge_search",
                name="知識検索",
                description="組織の知識を検索して提供する",
                keywords=KNOWLEDGE_SEARCH_KEYWORDS,
                actions=["query_knowledge", "search_knowledge"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="knowledge_save",
                name="知識保存",
                description="新しい知識を学習して保存する",
                keywords=KNOWLEDGE_SAVE_KEYWORDS,
                actions=["save_memory", "learn_knowledge"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="knowledge_delete",
                name="知識削除",
                description="保存された知識を削除する",
                keywords=KNOWLEDGE_DELETE_KEYWORDS,
                actions=["delete_memory", "forget_knowledge"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.1,
            ),
            AgentCapability(
                capability_id="knowledge_list",
                name="知識一覧",
                description="保存された知識を一覧表示する",
                keywords=["一覧", "リスト", "何を覚えてる", "記憶"],
                actions=["list_knowledge", "query_memory"],
                expertise_level=ExpertiseLevel.SECONDARY,
                confidence_boost=0.1,
            ),
            AgentCapability(
                capability_id="faq",
                name="FAQ対応",
                description="よくある質問に回答する",
                keywords=FAQ_KEYWORDS,
                actions=["answer_faq", "get_faq"],
                expertise_level=ExpertiseLevel.SECONDARY,
                confidence_boost=0.1,
            ),
            AgentCapability(
                capability_id="document_search",
                name="ドキュメント検索",
                description="社内ドキュメントを検索する",
                keywords=DOCUMENT_KEYWORDS,
                actions=["search_documents", "get_document"],
                expertise_level=ExpertiseLevel.SECONDARY,
                confidence_boost=0.1,
            ),
        ]

    def _register_handlers(self) -> None:
        """ハンドラーを登録"""
        self._handlers = {
            "query_knowledge": self._handle_query_knowledge,
            "search_knowledge": self._handle_query_knowledge,
            "save_memory": self._handle_save_memory,
            "learn_knowledge": self._handle_learn_knowledge,
            "delete_memory": self._handle_delete_memory,
            "forget_knowledge": self._handle_forget_knowledge,
            "list_knowledge": self._handle_list_knowledge,
            "query_memory": self._handle_query_memory,
            "answer_faq": self._handle_answer_faq,
            "search_documents": self._handle_search_documents,
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
            error_message="知識関連の操作を特定できませんでした",
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

        # 知識削除
        for keyword in KNOWLEDGE_DELETE_KEYWORDS:
            if keyword.lower() in message_lower:
                return "forget_knowledge"

        # 知識保存
        for keyword in KNOWLEDGE_SAVE_KEYWORDS:
            if keyword.lower() in message_lower:
                return "save_memory"

        # 知識検索（デフォルト）
        for keyword in KNOWLEDGE_SEARCH_KEYWORDS:
            if keyword.lower() in message_lower:
                return "query_knowledge"

        return None

    # -------------------------------------------------------------------------
    # ハンドラー
    # -------------------------------------------------------------------------

    async def _handle_query_knowledge(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """知識検索ハンドラー"""
        query = content.get("query", content.get("message", ""))
        limit = content.get("limit", DEFAULT_SEARCH_LIMIT)

        return {
            "action": "query_knowledge",
            "query": query,
            "limit": limit,
            "response": "知識を検索しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_save_memory(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """記憶保存ハンドラー"""
        message = content.get("message", "")
        subject = content.get("subject", "")
        person = content.get("person", "")

        return {
            "action": "save_memory",
            "content": message,
            "subject": subject,
            "person": person,
            "response": "覚えましたウル！",
            "requires_external_handler": True,
        }

    async def _handle_learn_knowledge(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """知識学習ハンドラー"""
        message = content.get("message", "")
        category = content.get("category", "general")

        return {
            "action": "learn_knowledge",
            "content": message,
            "category": category,
            "response": "新しい知識を学習しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_delete_memory(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """記憶削除ハンドラー"""
        message = content.get("message", "")
        memory_id = content.get("memory_id", "")
        # fix: save_memoryと同じperson/subjectキーで人物名を取り出し、
        # ハンドラー（memory_actions.py）が期待するpersonsリスト形式に変換
        person = content.get("person", "") or content.get("subject", "")
        persons_list = [person] if person else ([message] if message else [])

        return {
            "action": "delete_memory",
            "persons": persons_list,  # fix: ハンドラーが期待するキー（queryではなくpersons）
            "query": message,
            "memory_id": memory_id,
            "response": "記憶を削除しますウル。",
            "requires_external_handler": True,
        }

    async def _handle_forget_knowledge(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """知識削除ハンドラー"""
        message = content.get("message", "")
        knowledge_id = content.get("knowledge_id", "")

        return {
            "action": "forget_knowledge",
            "query": message,
            "knowledge_id": knowledge_id,
            "response": "知識を削除しますウル。",
            "requires_external_handler": True,
        }

    async def _handle_list_knowledge(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """知識一覧ハンドラー"""
        category = content.get("category", "")
        limit = content.get("limit", 10)

        return {
            "action": "list_knowledge",
            "category": category,
            "limit": limit,
            "response": "覚えている知識を表示しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_query_memory(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """記憶検索ハンドラー"""
        query = content.get("query", content.get("message", ""))
        person = content.get("person", "")

        return {
            "action": "query_memory",
            "query": query,
            "person": person,
            "response": "記憶を検索しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_answer_faq(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """FAQ回答ハンドラー"""
        question = content.get("question", content.get("message", ""))

        return {
            "action": "answer_faq",
            "question": question,
            "response": "よくある質問から探しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_search_documents(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """ドキュメント検索ハンドラー"""
        query = content.get("query", content.get("message", ""))
        doc_type = content.get("doc_type", "")

        return {
            "action": "search_documents",
            "query": query,
            "doc_type": doc_type,
            "response": "ドキュメントを検索しますウル！",
            "requires_external_handler": True,
        }


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_knowledge_expert(
    pool: Optional[Any] = None,
    organization_id: str = "",
) -> KnowledgeExpert:
    """
    ナレッジ専門家エージェントを作成するファクトリ関数
    """
    return KnowledgeExpert(
        pool=pool,
        organization_id=organization_id,
    )
