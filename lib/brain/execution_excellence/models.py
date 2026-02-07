# lib/brain/execution_excellence/models.py
"""
Phase 2L: 実行力強化（Execution Excellence） - データモデル

複雑なタスクの分解、実行計画、進捗追跡、品質チェック、
エスカレーションのためのデータモデルを定義します。

設計書: docs/21_phase2l_execution_excellence.md
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# =============================================================================
# Enum定義
# =============================================================================


class SubTaskStatus(str, Enum):
    """サブタスクのステータス"""

    PENDING = "pending"           # 実行待ち
    IN_PROGRESS = "in_progress"   # 実行中
    COMPLETED = "completed"       # 完了
    FAILED = "failed"             # 失敗
    BLOCKED = "blocked"           # ブロック中（依存タスク待ち）
    SKIPPED = "skipped"           # スキップ（不要になった）
    ESCALATED = "escalated"       # エスカレーション済み


class ExecutionPriority(str, Enum):
    """実行優先度"""

    CRITICAL = "critical"   # 最優先（即座に実行）
    HIGH = "high"           # 高（できるだけ早く）
    NORMAL = "normal"       # 通常
    LOW = "low"             # 低（他のタスク完了後）


class RecoveryStrategy(str, Enum):
    """リカバリー戦略"""

    RETRY = "retry"                 # リトライ
    ALTERNATIVE = "alternative"     # 代替アプローチ
    SKIP = "skip"                   # スキップ（オプショナルタスク）
    ESCALATE = "escalate"           # 人間にエスカレーション
    ABORT = "abort"                 # 全体を中止


class QualityCheckResult(str, Enum):
    """品質チェック結果"""

    PASS = "pass"               # 合格
    WARNING = "warning"         # 警告あり（続行可）
    FAIL = "fail"               # 不合格（修正必要）
    SKIPPED = "skipped"         # チェックスキップ


class EscalationLevel(str, Enum):
    """エスカレーションレベル"""

    INFO = "info"               # 情報提供のみ
    CONFIRMATION = "confirmation"  # 確認が必要
    DECISION = "decision"       # 判断が必要
    URGENT = "urgent"           # 緊急対応が必要


# =============================================================================
# サブタスク
# =============================================================================


@dataclass
class SubTask:
    """
    分解されたサブタスク

    複雑なリクエストを分解した単位タスク。
    """

    id: str
    name: str                           # タスク名（例: 「会議室の空き確認」）
    description: str                    # 詳細説明
    action: str                         # 実行するアクション名（SYSTEM_CAPABILITIESのキー）
    params: Dict[str, Any] = field(default_factory=dict)  # アクションパラメータ

    # 依存関係
    depends_on: List[str] = field(default_factory=list)   # 依存するサブタスクID
    blocks: List[str] = field(default_factory=list)       # ブロックするサブタスクID

    # ステータス
    status: SubTaskStatus = SubTaskStatus.PENDING
    priority: ExecutionPriority = ExecutionPriority.NORMAL

    # 実行設定
    is_optional: bool = False           # オプショナルか（失敗しても続行）
    max_retries: int = 3                # 最大リトライ回数
    timeout_seconds: int = 60           # タイムアウト秒数
    recovery_strategy: RecoveryStrategy = RecoveryStrategy.RETRY

    # 実行結果
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0

    # タイムスタンプ
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def is_ready(self) -> bool:
        """実行可能な状態か"""
        return self.status == SubTaskStatus.PENDING

    @property
    def is_terminal(self) -> bool:
        """終了状態か"""
        return self.status in (
            SubTaskStatus.COMPLETED,
            SubTaskStatus.FAILED,
            SubTaskStatus.SKIPPED,
            SubTaskStatus.ESCALATED,
        )

    @property
    def execution_time_ms(self) -> Optional[int]:
        """実行時間（ミリ秒）"""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return int(delta.total_seconds() * 1000)
        return None

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "action": self.action,
            "params": self.params,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "priority": self.priority.value,
            "is_optional": self.is_optional,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count,
        }


# =============================================================================
# 実行計画
# =============================================================================


@dataclass
class ExecutionPlan:
    """
    実行計画

    サブタスク群の実行順序と依存関係を定義。
    """

    id: str
    name: str                           # 計画名（例: 「会議室予約ワークフロー」）
    description: str                    # 計画の説明
    original_request: str               # 元のユーザーリクエスト

    # サブタスク
    subtasks: List[SubTask] = field(default_factory=list)

    # 実行設定
    parallel_execution: bool = True     # 並列実行を許可するか
    continue_on_failure: bool = False   # 失敗時も続行するか

    # ステータス
    status: SubTaskStatus = SubTaskStatus.PENDING
    current_step: int = 0               # 現在のステップ

    # 品質チェック設定
    quality_checks_enabled: bool = True
    required_quality_level: float = 0.8  # 必要な品質スコア（0.0-1.0）

    # タイムスタンプ
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # メタデータ
    room_id: str = ""
    account_id: str = ""
    organization_id: str = ""

    @property
    def progress(self) -> float:
        """進捗率（0.0-1.0）"""
        if not self.subtasks:
            return 0.0
        completed = sum(1 for st in self.subtasks if st.is_terminal)
        return completed / len(self.subtasks)

    @property
    def completed_count(self) -> int:
        """完了したサブタスク数"""
        return sum(1 for st in self.subtasks if st.status == SubTaskStatus.COMPLETED)

    @property
    def failed_count(self) -> int:
        """失敗したサブタスク数"""
        return sum(1 for st in self.subtasks if st.status == SubTaskStatus.FAILED)

    @property
    def in_progress_count(self) -> int:
        """実行中のサブタスク数"""
        return sum(1 for st in self.subtasks if st.status == SubTaskStatus.IN_PROGRESS)

    @property
    def pending_count(self) -> int:
        """待機中のサブタスク数"""
        return sum(1 for st in self.subtasks if st.status == SubTaskStatus.PENDING)

    @property
    def total_execution_time_ms(self) -> int:
        """総実行時間（ミリ秒）"""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return int(delta.total_seconds() * 1000)
        elif self.started_at:
            delta = datetime.now() - self.started_at
            return int(delta.total_seconds() * 1000)
        return 0

    def get_ready_tasks(self) -> List[SubTask]:
        """実行可能なサブタスクを取得"""
        ready = []
        completed_ids = {
            st.id for st in self.subtasks
            if st.status in (SubTaskStatus.COMPLETED, SubTaskStatus.SKIPPED)
        }
        for st in self.subtasks:
            if st.is_ready and all(dep in completed_ids for dep in st.depends_on):
                ready.append(st)
        return ready

    def get_subtask(self, subtask_id: str) -> Optional[SubTask]:
        """IDでサブタスクを取得"""
        for st in self.subtasks:
            if st.id == subtask_id:
                return st
        return None

    def is_complete(self) -> bool:
        """計画が完了したか"""
        return all(st.is_terminal for st in self.subtasks)

    def has_failures(self) -> bool:
        """失敗があるか"""
        return self.failed_count > 0

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "original_request": self.original_request,
            "subtasks": [st.to_dict() for st in self.subtasks],
            "status": self.status.value,
            "progress": self.progress,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "room_id": self.room_id,
            "account_id": self.account_id,
            "organization_id": self.organization_id,
        }


# =============================================================================
# 進捗レポート
# =============================================================================


@dataclass
class ProgressReport:
    """
    進捗レポート

    実行中のワークフローの進捗状況。
    """

    plan_id: str
    plan_name: str

    # 進捗
    total_subtasks: int
    completed_subtasks: int
    failed_subtasks: int
    in_progress_subtasks: int
    pending_subtasks: int

    # 進捗率
    progress_percentage: float          # 0.0-100.0

    # 現在のステータス
    current_activity: str               # 現在実行中の内容
    estimated_remaining_time: Optional[int] = None  # 残り時間（秒）

    # 問題
    issues: List[str] = field(default_factory=list)

    # タイムスタンプ
    started_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_user_message(self) -> str:
        """ユーザー向けメッセージを生成"""
        progress_bar = self._generate_progress_bar()

        message = f"""📊 進捗状況ウル

{self.plan_name}
{progress_bar} {self.progress_percentage:.0f}%

{self.current_activity}"""

        if self.issues:
            message += f"\n\n⚠️ 注意: {', '.join(self.issues)}"

        return message

    def _generate_progress_bar(self) -> str:
        """プログレスバーを生成"""
        filled = int(self.progress_percentage / 10)
        empty = 10 - filled
        return "▓" * filled + "░" * empty


# =============================================================================
# 品質レポート
# =============================================================================


@dataclass
class QualityReport:
    """
    品質チェックレポート

    実行結果の品質検証結果。
    """

    plan_id: str
    subtask_id: Optional[str] = None    # 個別サブタスクの場合

    # チェック結果
    overall_result: QualityCheckResult = QualityCheckResult.PASS
    quality_score: float = 1.0          # 0.0-1.0

    # 詳細チェック
    checks: List[Dict[str, Any]] = field(default_factory=list)
    # [
    #   {"name": "データ整合性", "result": "pass", "score": 1.0},
    #   {"name": "期限チェック", "result": "warning", "score": 0.8, "message": "24時間以内"},
    # ]

    # 問題点
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # 推奨アクション
    recommended_actions: List[str] = field(default_factory=list)

    # タイムスタンプ
    checked_at: datetime = field(default_factory=datetime.now)


# =============================================================================
# エスカレーションリクエスト
# =============================================================================


@dataclass
class EscalationRequest:
    """
    エスカレーションリクエスト

    自動処理できない場合に人間に確認を求める。
    """

    id: str
    plan_id: str
    subtask_id: Optional[str] = None

    # エスカレーション内容
    level: EscalationLevel = EscalationLevel.CONFIRMATION
    title: str = ""                     # 件名
    description: str = ""               # 詳細説明
    context: str = ""                   # 背景・経緯

    # 選択肢（確認・判断の場合）
    options: List[Dict[str, str]] = field(default_factory=list)
    # [
    #   {"id": "proceed", "label": "続行する", "description": "..."},
    #   {"id": "abort", "label": "中止する", "description": "..."},
    # ]
    default_option: Optional[str] = None

    # 推奨
    recommendation: Optional[str] = None  # ソウルくんの推奨
    recommendation_reasoning: Optional[str] = None

    # ステータス
    status: str = "pending"             # pending, responded, expired
    response: Optional[str] = None
    response_reasoning: Optional[str] = None

    # タイムスタンプ
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None

    # 通知情報
    notification_sent: bool = False
    notification_room_id: Optional[str] = None
    notification_message_id: Optional[str] = None

    def __post_init__(self):
        """初期化後処理"""
        if self.expires_at is None:
            # デフォルト30分でタイムアウト
            self.expires_at = datetime.now() + timedelta(minutes=30)

    @property
    def is_expired(self) -> bool:
        """期限切れか"""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    @property
    def is_pending(self) -> bool:
        """応答待ちか"""
        return self.status == "pending" and not self.is_expired

    def to_user_message(self) -> str:
        """ユーザー向けエスカレーションメッセージを生成"""
        level_emoji = {
            EscalationLevel.INFO: "ℹ️",
            EscalationLevel.CONFIRMATION: "🤔",
            EscalationLevel.DECISION: "⚠️",
            EscalationLevel.URGENT: "🚨",
        }

        message = f"""{level_emoji.get(self.level, "❓")} {self.title}

{self.description}"""

        if self.context:
            message += f"\n\n📋 経緯:\n{self.context}"

        if self.recommendation:
            message += f"\n\n💡 ソウルくんの推奨: {self.recommendation}"
            if self.recommendation_reasoning:
                message += f"\n  理由: {self.recommendation_reasoning}"

        if self.options:
            message += "\n\n選択肢:"
            for i, opt in enumerate(self.options, 1):
                message += f"\n{i}. {opt['label']}"
                if opt.get('description'):
                    message += f"\n   {opt['description']}"

        message += "\n\n番号で教えてほしいウル🐺"

        return message


# =============================================================================
# リカバリー結果
# =============================================================================


@dataclass
class RecoveryResult:
    """
    リカバリー結果

    エラーからのリカバリー試行の結果。
    """

    strategy: RecoveryStrategy
    success: bool
    message: str
    alternatives: List[str] = field(default_factory=list)
    escalation: Optional[EscalationRequest] = None


# =============================================================================
# 実行結果
# =============================================================================


@dataclass
class ExecutionExcellenceResult:
    """
    実行結果

    ワークフロー全体の実行結果。
    """

    plan_id: str
    plan_name: str
    original_request: str

    # 結果
    success: bool
    message: str                        # ユーザー向けメッセージ

    # 詳細
    completed_subtasks: List[str] = field(default_factory=list)  # 完了したサブタスク名
    failed_subtasks: List[str] = field(default_factory=list)     # 失敗したサブタスク名
    skipped_subtasks: List[str] = field(default_factory=list)    # スキップしたサブタスク名

    # 品質
    quality_score: float = 1.0
    quality_report: Optional[QualityReport] = None

    # エスカレーション
    escalations: List[EscalationRequest] = field(default_factory=list)

    # 実行統計
    total_execution_time_ms: int = 0
    retry_count: int = 0

    # 次のアクション提案
    suggestions: List[str] = field(default_factory=list)

    # タイムスタンプ
    started_at: Optional[datetime] = None
    completed_at: datetime = field(default_factory=datetime.now)


# =============================================================================
# サブタスクテンプレート
# =============================================================================


@dataclass
class SubTaskTemplate:
    """
    サブタスクテンプレート

    分解パターンで使用するサブタスクの雛形。
    """

    name: str
    action: str
    description: str = ""
    depends_on: List[str] = field(default_factory=list)  # テンプレート名で依存を指定
    is_optional: bool = False
    recovery_strategy: RecoveryStrategy = RecoveryStrategy.RETRY
    param_mappings: Dict[str, str] = field(default_factory=dict)  # リクエストからの値マッピング

    def create_subtask(
        self,
        params: Dict[str, Any],
        resolved_depends: List[str],
    ) -> SubTask:
        """
        テンプレートからサブタスクを生成

        Args:
            params: アクションパラメータ
            resolved_depends: 解決済み依存タスクID

        Returns:
            生成されたサブタスク
        """
        return SubTask(
            id=str(uuid.uuid4()),
            name=self.name,
            description=self.description or f"{self.name}を実行",
            action=self.action,
            params=params,
            depends_on=resolved_depends,
            is_optional=self.is_optional,
            recovery_strategy=self.recovery_strategy,
        )


# =============================================================================
# 分解パターン
# =============================================================================


@dataclass
class DecompositionPattern:
    """
    分解パターン

    特定のリクエストパターンをサブタスクに分解するルール。
    """

    name: str                           # パターン名
    triggers: List[str]                 # トリガーキーワード
    conditions: List[str] = field(default_factory=list)  # 追加条件
    subtask_templates: List[SubTaskTemplate] = field(default_factory=list)
    priority: int = 0                   # マッチ優先度（高いほど優先）

    def matches(self, request: str) -> bool:
        """
        リクエストがパターンにマッチするか判定

        Args:
            request: ユーザーリクエスト

        Returns:
            マッチすればTrue
        """
        request_lower = request.lower()

        # 全てのトリガーキーワードが含まれているか
        trigger_count = sum(1 for t in self.triggers if t.lower() in request_lower)

        # 最低2つのトリガーが必要（複雑なリクエストの証拠）
        return trigger_count >= 2

    def decompose(
        self,
        request: str,
        extracted_params: Optional[Dict[str, Any]] = None,
    ) -> List[SubTask]:
        """
        リクエストをサブタスクに分解

        Args:
            request: ユーザーリクエスト
            extracted_params: 抽出済みパラメータ

        Returns:
            サブタスクのリスト
        """
        params = extracted_params or {}
        subtasks = []
        name_to_id: Dict[str, str] = {}

        for template in self.subtask_templates:
            # パラメータをマッピング
            task_params = {}
            for param_key, request_key in template.param_mappings.items():
                if request_key in params:
                    task_params[param_key] = params[request_key]

            # 依存関係を解決
            resolved_depends = [
                name_to_id[dep_name]
                for dep_name in template.depends_on
                if dep_name in name_to_id
            ]

            # サブタスク生成
            subtask = template.create_subtask(task_params, resolved_depends)
            subtasks.append(subtask)
            name_to_id[template.name] = subtask.id

        return subtasks


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_subtask(
    name: str,
    action: str,
    params: Optional[Dict[str, Any]] = None,
    depends_on: Optional[List[str]] = None,
    is_optional: bool = False,
) -> SubTask:
    """
    サブタスクを作成

    Args:
        name: タスク名
        action: アクション名
        params: パラメータ
        depends_on: 依存タスクID
        is_optional: オプショナルか

    Returns:
        SubTask
    """
    return SubTask(
        id=str(uuid.uuid4()),
        name=name,
        description=f"{name}を実行",
        action=action,
        params=params or {},
        depends_on=depends_on or [],
        is_optional=is_optional,
    )


def create_execution_plan(
    name: str,
    original_request: str,
    subtasks: List[SubTask],
    room_id: str = "",
    account_id: str = "",
    organization_id: str = "",
) -> ExecutionPlan:
    """
    実行計画を作成

    Args:
        name: 計画名
        original_request: 元のリクエスト
        subtasks: サブタスクリスト
        room_id: ルームID
        account_id: アカウントID
        organization_id: 組織ID

    Returns:
        ExecutionPlan
    """
    return ExecutionPlan(
        id=str(uuid.uuid4()),
        name=name,
        description=f"「{original_request}」の実行計画",
        original_request=original_request,
        subtasks=subtasks,
        room_id=room_id,
        account_id=account_id,
        organization_id=organization_id,
    )
