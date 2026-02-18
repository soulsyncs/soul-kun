# lib/brain/agents/base.py
"""
ソウルくんの脳 - エージェント基底クラス

Ultimate Brain Phase 3: マルチエージェントシステムの基底クラス

設計思想:
- 全てのエージェントが共通のインターフェースを持つ
- エージェント間のコミュニケーションプロトコルを統一
- 専門性と協調性の両立

主要機能:
1. メッセージ処理の共通インターフェース
2. エージェント間通信プロトコル
3. コンテキスト管理
4. ログ・監査機能

設計書: docs/19_ultimate_brain_architecture.md セクション5.3
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from lib.brain.models import BrainContext


logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================

# エージェントのタイムアウト（秒）
AGENT_TIMEOUT_SECONDS: float = 30.0

# エージェント間通信のタイムアウト（秒）
INTER_AGENT_TIMEOUT_SECONDS: float = 10.0

# 最大再試行回数
MAX_RETRY_COUNT: int = 3

# デフォルトの確信度閾値
DEFAULT_CONFIDENCE_THRESHOLD: float = 0.7

# エージェントの最大同時実行数
MAX_CONCURRENT_AGENTS: int = 3

# メッセージキューの最大サイズ
MESSAGE_QUEUE_SIZE: int = 100

# エージェントのキャッシュTTL（秒）
AGENT_CACHE_TTL: int = 300


# =============================================================================
# 列挙型
# =============================================================================

class AgentType(str, Enum):
    """エージェントの種類"""

    ORCHESTRATOR = "orchestrator"        # オーケストレーター（メインブレイン）
    TASK_EXPERT = "task_expert"          # タスク専門家
    GOAL_EXPERT = "goal_expert"          # 目標専門家
    KNOWLEDGE_EXPERT = "knowledge_expert"  # ナレッジ専門家
    HR_EXPERT = "hr_expert"              # HR専門家
    EMOTION_EXPERT = "emotion_expert"    # 感情専門家
    ORGANIZATION_EXPERT = "organization_expert"  # 組織専門家


class AgentStatus(str, Enum):
    """エージェントのステータス"""

    IDLE = "idle"                        # 待機中
    PROCESSING = "processing"            # 処理中
    WAITING = "waiting"                  # 他エージェントの応答待ち
    ERROR = "error"                      # エラー状態
    SUSPENDED = "suspended"              # 一時停止


class MessageType(str, Enum):
    """エージェント間メッセージの種類"""

    REQUEST = "request"                  # 依頼
    RESPONSE = "response"                # 応答
    DELEGATE = "delegate"                # 委任
    NOTIFY = "notify"                    # 通知
    QUERY = "query"                      # 問い合わせ
    FEEDBACK = "feedback"                # フィードバック


class MessagePriority(str, Enum):
    """メッセージの優先度"""

    URGENT = "urgent"                    # 緊急（即時処理）
    HIGH = "high"                        # 高優先度
    NORMAL = "normal"                    # 通常
    LOW = "low"                          # 低優先度


class ExpertiseLevel(str, Enum):
    """専門性レベル"""

    PRIMARY = "primary"                  # 主担当（最も得意）
    SECONDARY = "secondary"              # 副担当（対応可能）
    SUPPORTIVE = "supportive"            # サポート（補助的に対応）


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class AgentCapability:
    """
    エージェントの能力定義
    """
    # 識別情報
    capability_id: str = ""              # 能力ID
    name: str = ""                       # 能力名

    # 能力の詳細
    description: str = ""                # 説明
    keywords: List[str] = field(default_factory=list)  # 関連キーワード
    actions: List[str] = field(default_factory=list)   # 実行可能なアクション

    # 評価
    expertise_level: ExpertiseLevel = ExpertiseLevel.SUPPORTIVE
    confidence_boost: float = 0.0        # この能力での確信度ブースト

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "keywords": self.keywords,
            "actions": self.actions,
            "expertise_level": self.expertise_level.value,
            "confidence_boost": self.confidence_boost,
        }


@dataclass
class AgentMessage:
    """
    エージェント間のメッセージ
    """
    # 識別情報
    id: str = field(default_factory=lambda: str(uuid4()))
    correlation_id: Optional[str] = None  # 関連メッセージのID（応答時）

    # 送受信者
    from_agent: AgentType = AgentType.ORCHESTRATOR
    to_agent: AgentType = AgentType.ORCHESTRATOR

    # メッセージ内容
    message_type: MessageType = MessageType.REQUEST
    priority: MessagePriority = MessagePriority.NORMAL
    content: Dict[str, Any] = field(default_factory=dict)

    # メタデータ
    requires_response: bool = True
    timeout_seconds: float = INTER_AGENT_TIMEOUT_SECONDS

    # タイムスタンプ
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "correlation_id": self.correlation_id,
            "from_agent": self.from_agent.value,
            "to_agent": self.to_agent.value,
            "message_type": self.message_type.value,
            "priority": self.priority.value,
            "content": self.content,
            "requires_response": self.requires_response,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class AgentResponse:
    """
    エージェントの応答
    """
    # 識別情報
    id: str = field(default_factory=lambda: str(uuid4()))
    request_id: str = ""                 # 元のリクエストID

    # 応答者
    agent_type: AgentType = AgentType.ORCHESTRATOR

    # 応答内容
    success: bool = True
    result: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None

    # 評価
    confidence: float = 0.0
    processing_time_ms: float = 0.0

    # 次のアクション
    suggested_actions: List[str] = field(default_factory=list)
    delegate_to: Optional[AgentType] = None

    # メタデータ（追加情報）
    metadata: Dict[str, Any] = field(default_factory=dict)

    # タイムスタンプ
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "agent_type": self.agent_type.value,
            "success": self.success,
            "result": self.result,
            "error_message": self.error_message,
            "confidence": self.confidence,
            "processing_time_ms": self.processing_time_ms,
            "suggested_actions": self.suggested_actions,
            "delegate_to": self.delegate_to.value if self.delegate_to else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class AgentContext:
    """
    エージェントの実行コンテキスト
    """
    # 識別情報
    organization_id: str = ""
    user_id: str = ""
    room_id: str = ""
    session_id: str = ""

    # 入力
    original_message: str = ""
    brain_context: Optional[Any] = None   # BrainContext

    # エージェント状態
    current_agent: AgentType = AgentType.ORCHESTRATOR
    visited_agents: List[AgentType] = field(default_factory=list)
    depth: int = 0                        # 委任の深さ

    # メッセージ履歴
    message_history: List[AgentMessage] = field(default_factory=list)
    response_history: List[AgentResponse] = field(default_factory=list)

    # 共有データ
    shared_data: Dict[str, Any] = field(default_factory=dict)

    # タイムスタンプ
    started_at: datetime = field(default_factory=datetime.now)


@dataclass
class AgentStats:
    """
    エージェントの統計情報
    """
    agent_type: AgentType = AgentType.ORCHESTRATOR

    # 処理統計
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    delegated_requests: int = 0

    # パフォーマンス
    avg_processing_time_ms: float = 0.0
    avg_confidence: float = 0.0

    # 最終更新
    last_request_at: Optional[datetime] = None

    @property
    def success_rate(self) -> float:
        """成功率を計算"""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests


# =============================================================================
# BaseAgent 抽象基底クラス
# =============================================================================

class BaseAgent(ABC):
    """
    エージェントの抽象基底クラス

    全てのエージェントが継承する基底クラス。
    共通のインターフェースと基本機能を提供。

    Attributes:
        agent_type: エージェントの種類
        pool: データベース接続プール
        organization_id: 組織ID
    """

    def __init__(
        self,
        agent_type: AgentType,
        pool: Optional[Any] = None,
        organization_id: str = "",
    ):
        """
        初期化

        Args:
            agent_type: エージェントの種類
            pool: データベース接続プール
            organization_id: 組織ID
        """
        self._agent_type = agent_type
        self._pool = pool
        self._organization_id = organization_id

        # 状態
        self._status = AgentStatus.IDLE
        self._capabilities: List[AgentCapability] = []
        self._handlers: Dict[str, Callable] = {}

        # 統計
        self._stats = AgentStats(agent_type=agent_type)

        # 他エージェントへの参照（オーケストレーターが設定）
        self._agent_registry: Dict[AgentType, "BaseAgent"] = {}

        # v11.2.0: P6修正 — _fire_and_forget 用タスク参照保持
        self._background_tasks: set = set()

        # 初期化
        self._initialize_capabilities()
        self._register_handlers()

        logger.info(
            f"Agent initialized: {agent_type.value}",
            extra={
                "agent_type": agent_type.value,
                "organization_id": organization_id,
            }
        )

    def _fire_and_forget(self, coro) -> None:
        """create_taskの安全ラッパー: 参照保持+エラーログ（CLAUDE.md §3-2 #19）"""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        task.add_done_callback(self._log_background_error)

    @staticmethod
    def _log_background_error(task) -> None:
        """バックグラウンドタスクのエラーをログ出力"""
        if not task.cancelled() and task.exception() is not None:
            exc = task.exception()
            logger.error(
                "Background task error in BaseAgent: %s",
                type(exc).__name__,
            )

    @property
    def agent_type(self) -> AgentType:
        """エージェントの種類"""
        return self._agent_type

    @property
    def status(self) -> AgentStatus:
        """現在のステータス"""
        return self._status

    @property
    def capabilities(self) -> List[AgentCapability]:
        """エージェントの能力リスト"""
        return self._capabilities

    @property
    def stats(self) -> AgentStats:
        """統計情報"""
        return self._stats

    # -------------------------------------------------------------------------
    # 抽象メソッド（サブクラスで実装必須）
    # -------------------------------------------------------------------------

    @abstractmethod
    def _initialize_capabilities(self) -> None:
        """
        エージェントの能力を初期化

        サブクラスで実装必須。
        self._capabilities にエージェントの能力を登録する。
        """
        pass

    @abstractmethod
    def _register_handlers(self) -> None:
        """
        ハンドラーを登録

        サブクラスで実装必須。
        self._handlers にアクション→ハンドラー関数のマッピングを登録する。
        """
        pass

    @abstractmethod
    async def process(
        self,
        context: AgentContext,
        message: AgentMessage,
    ) -> AgentResponse:
        """
        メッセージを処理

        サブクラスで実装必須。
        エージェント固有の処理ロジックを実装する。

        Args:
            context: エージェントコンテキスト
            message: 処理するメッセージ

        Returns:
            AgentResponse: 処理結果
        """
        pass

    @abstractmethod
    def can_handle(
        self,
        action: str,
        context: AgentContext,
    ) -> bool:
        """
        指定されたアクションを処理できるか判定

        サブクラスで実装必須。

        Args:
            action: アクション名
            context: エージェントコンテキスト

        Returns:
            bool: 処理可能ならTrue
        """
        pass

    @abstractmethod
    def get_confidence(
        self,
        action: str,
        context: AgentContext,
    ) -> float:
        """
        指定されたアクションに対する確信度を計算

        サブクラスで実装必須。

        Args:
            action: アクション名
            context: エージェントコンテキスト

        Returns:
            float: 確信度（0.0〜1.0）
        """
        pass

    # -------------------------------------------------------------------------
    # 共通メソッド
    # -------------------------------------------------------------------------

    def set_agent_registry(self, registry: Dict[AgentType, "BaseAgent"]) -> None:
        """
        エージェントレジストリを設定

        オーケストレーターから呼び出される。

        Args:
            registry: エージェントタイプ→エージェントインスタンスのマッピング
        """
        self._agent_registry = registry

    async def handle_message(
        self,
        context: AgentContext,
        message: AgentMessage,
    ) -> AgentResponse:
        """
        メッセージを処理（共通ラッパー）

        統計更新、エラーハンドリング、ログを共通化。

        Args:
            context: エージェントコンテキスト
            message: 処理するメッセージ

        Returns:
            AgentResponse: 処理結果
        """
        start_time = datetime.now()
        self._status = AgentStatus.PROCESSING
        self._stats.total_requests += 1
        self._stats.last_request_at = start_time

        try:
            # 深度チェック（無限ループ防止）
            if context.depth > MAX_CONCURRENT_AGENTS:
                logger.warning(
                    f"Max delegation depth reached: {context.depth}",
                    extra={"agent_type": self._agent_type.value}
                )
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=False,
                    error_message="最大委任深度に達しました",
                )

            # 処理実行
            response = await self.process(context, message)

            # 統計更新
            if response.success:
                self._stats.successful_requests += 1
            else:
                self._stats.failed_requests += 1

            if response.delegate_to:
                self._stats.delegated_requests += 1

            # 処理時間計算
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            response.processing_time_ms = processing_time

            # 平均処理時間更新
            self._update_avg_processing_time(processing_time)

            return response

        except Exception as e:
            logger.error(
                f"Error processing message in {self._agent_type.value}: {type(e).__name__}",
                exc_info=True
            )
            self._stats.failed_requests += 1

            return AgentResponse(
                request_id=message.id,
                agent_type=self._agent_type,
                success=False,
                error_message=type(e).__name__,
            )

        finally:
            self._status = AgentStatus.IDLE

    async def delegate_to(
        self,
        target_agent: AgentType,
        context: AgentContext,
        content: Dict[str, Any],
    ) -> AgentResponse:
        """
        他のエージェントに委任

        Args:
            target_agent: 委任先エージェント
            context: エージェントコンテキスト
            content: 委任内容

        Returns:
            AgentResponse: 委任先からの応答
        """
        if target_agent not in self._agent_registry:
            logger.warning(f"Agent not found in registry: {target_agent.value}")
            return AgentResponse(
                agent_type=self._agent_type,
                success=False,
                error_message=f"エージェント {target_agent.value} が見つかりません",
            )

        # コンテキスト更新
        context.visited_agents.append(self._agent_type)
        context.depth += 1
        context.current_agent = target_agent

        # メッセージ作成
        message = AgentMessage(
            from_agent=self._agent_type,
            to_agent=target_agent,
            message_type=MessageType.DELEGATE,
            content=content,
        )

        # 委任先で処理
        target = self._agent_registry[target_agent]
        return await target.handle_message(context, message)

    async def query_agent(
        self,
        target_agent: AgentType,
        query: Dict[str, Any],
        timeout: float = INTER_AGENT_TIMEOUT_SECONDS,
    ) -> Optional[AgentResponse]:
        """
        他のエージェントに問い合わせ

        Args:
            target_agent: 問い合わせ先エージェント
            query: 問い合わせ内容
            timeout: タイムアウト（秒）

        Returns:
            AgentResponse: 応答（タイムアウト時はNone）
        """
        if target_agent not in self._agent_registry:
            logger.warning(f"Agent not found for query: {target_agent.value}")
            return None

        message = AgentMessage(
            from_agent=self._agent_type,
            to_agent=target_agent,
            message_type=MessageType.QUERY,
            content=query,
            timeout_seconds=timeout,
        )

        context = AgentContext(
            organization_id=self._organization_id,
            current_agent=target_agent,
        )

        try:
            target = self._agent_registry[target_agent]
            return await asyncio.wait_for(
                target.handle_message(context, message),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"Query to {target_agent.value} timed out",
                extra={"timeout": timeout}
            )
            return None

    def notify_agent(
        self,
        target_agent: AgentType,
        notification: Dict[str, Any],
    ) -> None:
        """
        他のエージェントに通知（非同期、応答不要）

        Args:
            target_agent: 通知先エージェント
            notification: 通知内容
        """
        if target_agent not in self._agent_registry:
            logger.warning(f"Agent not found for notification: {target_agent.value}")
            return

        message = AgentMessage(
            from_agent=self._agent_type,
            to_agent=target_agent,
            message_type=MessageType.NOTIFY,
            content=notification,
            requires_response=False,
        )

        # 非同期で通知（Fire-and-forget）
        # v11.2.0: P6修正 — asyncio.create_task → _fire_and_forget（参照保持）
        self._fire_and_forget(self._send_notification(target_agent, message))

    async def _send_notification(
        self,
        target_agent: AgentType,
        message: AgentMessage,
    ) -> None:
        """通知を送信（内部メソッド）"""
        try:
            context = AgentContext(
                organization_id=self._organization_id,
                current_agent=target_agent,
            )
            target = self._agent_registry[target_agent]
            await target.handle_message(context, message)
        except Exception as e:
            logger.error(f"Failed to send notification to {target_agent.value}: {type(e).__name__}")

    def get_capability_for_action(self, action: str) -> Optional[AgentCapability]:
        """
        アクションに対応する能力を取得

        Args:
            action: アクション名

        Returns:
            AgentCapability: 対応する能力（なければNone）
        """
        for capability in self._capabilities:
            if action in capability.actions:
                return capability
        return None

    def get_keywords(self) -> Set[str]:
        """
        エージェントの全キーワードを取得

        Returns:
            Set[str]: キーワードのセット
        """
        keywords = set()
        for capability in self._capabilities:
            keywords.update(capability.keywords)
        return keywords

    def _update_avg_processing_time(self, new_time_ms: float) -> None:
        """平均処理時間を更新（移動平均）"""
        if self._stats.total_requests == 1:
            self._stats.avg_processing_time_ms = new_time_ms
        else:
            # 指数移動平均
            alpha = 0.2
            self._stats.avg_processing_time_ms = (
                alpha * new_time_ms +
                (1 - alpha) * self._stats.avg_processing_time_ms
            )

    def _update_avg_confidence(self, new_confidence: float) -> None:
        """平均確信度を更新（移動平均）"""
        if self._stats.total_requests == 1:
            self._stats.avg_confidence = new_confidence
        else:
            alpha = 0.2
            self._stats.avg_confidence = (
                alpha * new_confidence +
                (1 - alpha) * self._stats.avg_confidence
            )


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_agent_message(
    from_agent: AgentType,
    to_agent: AgentType,
    message_type: MessageType = MessageType.REQUEST,
    priority: MessagePriority = MessagePriority.NORMAL,
    content: Optional[Dict[str, Any]] = None,
    requires_response: bool = True,
) -> AgentMessage:
    """
    エージェントメッセージを作成するファクトリ関数

    Args:
        from_agent: 送信元エージェント
        to_agent: 送信先エージェント
        message_type: メッセージタイプ
        priority: 優先度
        content: メッセージ内容
        requires_response: 応答が必要か

    Returns:
        AgentMessage: 作成されたメッセージ
    """
    return AgentMessage(
        from_agent=from_agent,
        to_agent=to_agent,
        message_type=message_type,
        priority=priority,
        content=content or {},
        requires_response=requires_response,
    )


def create_agent_context(
    organization_id: str,
    user_id: str = "",
    room_id: str = "",
    original_message: str = "",
    brain_context: Optional[Any] = None,
) -> AgentContext:
    """
    エージェントコンテキストを作成するファクトリ関数

    Args:
        organization_id: 組織ID
        user_id: ユーザーID
        room_id: ルームID
        original_message: 元のメッセージ
        brain_context: BrainContext

    Returns:
        AgentContext: 作成されたコンテキスト
    """
    return AgentContext(
        organization_id=organization_id,
        user_id=user_id,
        room_id=room_id,
        session_id=str(uuid4()),
        original_message=original_message,
        brain_context=brain_context,
    )
