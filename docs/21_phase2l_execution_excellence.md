# 第21章：Phase 2L - 実行力強化（Execution Excellence）

## 21.1 概要

**完璧にやり遂げる能力の実現**

Phase 2Lは、ソウルくんが「指示されたタスクを確実に完遂する」能力を実装するフェーズです。
単純なアクション実行から、複雑なマルチステップワークフローの自動実行まで対応します。

### 位置づけ

```
Phase 2K: 能動性（Proactivity）✅ 完了
    │
    ▼
Phase 2L: 実行力強化（Execution Excellence）← 今ここ
    │
    ▼
Phase 2M: 対人力強化（Interpersonal Skills）
```

### 依存関係

| 依存Phase | 提供される能力 | Phase 2Lでの活用 |
|-----------|---------------|------------------|
| Phase 2K | プロアクティブ監視 | 進捗監視、リマインド |
| Phase 2J | 判断力強化 | タスク優先度判断、リスク評価 |
| Phase 2I | 理解力強化 | 曖昧な指示の解釈 |
| Phase 2E | 学習基盤 | 実行パターンの学習 |

---

## 21.2 実装する能力

### 能力一覧

| # | 能力名 | 説明 | 優先度 |
|---|--------|------|--------|
| 1 | タスク自動分解 | 複雑なリクエストをサブタスクに分解 | 高 |
| 2 | 実行計画立案 | サブタスクの依存関係と実行順序を決定 | 高 |
| 3 | 進捗自動追跡 | 各サブタスクの進捗を追跡 | 高 |
| 4 | 品質チェック | 実行結果の品質を検証 | 中 |
| 5 | 例外処理 | エラー発生時の自動リカバリー | 中 |
| 6 | エスカレーション | 自動解決不可の場合に人間に確認 | 中 |
| 7 | 代替案提示 | 失敗時の代替アプローチ提案 | 中 |
| 8 | 完了確認 | タスク完了の確認と報告 | 高 |

---

## 21.3 アーキテクチャ設計

### 21.3.1 全体構成

```
┌─────────────────────────────────────────────────────────────────┐
│                      SoulkunBrain.process_message()            │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ Understanding│→│  Decision   │→│  ExecutionExcellence    │ │
│  │    Layer    │  │    Layer    │  │       Layer             │ │
│  └─────────────┘  └─────────────┘  └───────────┬─────────────┘ │
│                                                  │               │
└──────────────────────────────────────────────────│───────────────┘
                                                   │
                                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ExecutionExcellence                           │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    TaskDecomposer                         │  │
│  │  「〇〇を手配して」→ サブタスク1, 2, 3...に分解           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    ExecutionPlanner                       │  │
│  │  依存関係を解析 → 実行順序を決定 → ExecutionPlanを生成    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    WorkflowExecutor                       │  │
│  │  ExecutionPlanに従ってサブタスクを順次/並列実行          │  │
│  │  ├─ ProgressTracker（進捗追跡）                          │  │
│  │  ├─ QualityChecker（品質チェック）                       │  │
│  │  ├─ ExceptionHandler（例外処理）                         │  │
│  │  └─ EscalationManager（エスカレーション）                │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    CompletionVerifier                     │  │
│  │  全サブタスク完了確認 → 最終品質チェック → 完了報告      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 21.3.2 データフロー

```
1. 入力受付
   ユーザー: 「会議室Aを明日14時で予約して、参加者にカレンダー招待送って」
        │
        ▼
2. タスク分解（TaskDecomposer）
   ├─ SubTask1: 会議室Aの空き確認（明日14時）
   ├─ SubTask2: 会議室Aの予約
   ├─ SubTask3: 参加者リストの取得
   └─ SubTask4: カレンダー招待送信
        │
        ▼
3. 実行計画立案（ExecutionPlanner）
   ExecutionPlan:
   ├─ Step1: SubTask1（空き確認）
   │      └─ 成功 → Step2へ
   │      └─ 失敗 → 代替案提示（別の時間を提案）
   ├─ Step2: SubTask2（予約）[依存: Step1]
   ├─ Step3: SubTask3（参加者取得）[並列実行可]
   └─ Step4: SubTask4（招待送信）[依存: Step2, Step3]
        │
        ▼
4. ワークフロー実行（WorkflowExecutor）
   ├─ Step1実行 → 成功
   ├─ Step2実行 → 成功
   ├─ Step3実行 → 成功
   └─ Step4実行 → 成功
        │
        ▼
5. 完了確認（CompletionVerifier）
   ├─ 全ステップ完了確認 → OK
   ├─ 品質チェック → OK
   └─ 完了報告生成
        │
        ▼
6. ユーザーへの報告
   「会議室Aを明日14時で予約したウル！
    参加者5名にカレンダー招待も送ったウル🐺」
```

---

## 21.4 データモデル

### 21.4.1 Enum定義

```python
# lib/brain/execution_excellence/models.py

from enum import Enum

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
```

### 21.4.2 データクラス定義

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any

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


@dataclass
class ExecutionResult:
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
```

---

## 21.5 コンポーネント詳細設計

### 21.5.1 TaskDecomposer（タスク分解器）

```python
# lib/brain/execution_excellence/decomposer.py

class TaskDecomposer:
    """
    タスク分解器

    複雑なユーザーリクエストをサブタスクに分解する。
    """

    def __init__(
        self,
        capabilities: Dict[str, Dict],
        llm_client: Optional[Any] = None,
    ):
        self.capabilities = capabilities
        self.llm_client = llm_client

        # 分解パターン（ルールベース）
        self.decomposition_patterns = self._load_patterns()

    async def decompose(
        self,
        request: str,
        context: BrainContext,
    ) -> List[SubTask]:
        """
        リクエストをサブタスクに分解

        Args:
            request: ユーザーリクエスト
            context: 脳コンテキスト

        Returns:
            サブタスクのリスト
        """
        # 1. ルールベース分解を試行
        subtasks = self._rule_based_decompose(request)

        if subtasks:
            return subtasks

        # 2. LLMベース分解（複雑なケース）
        if self.llm_client:
            subtasks = await self._llm_based_decompose(request, context)

        return subtasks or self._create_single_task(request)

    def _rule_based_decompose(self, request: str) -> Optional[List[SubTask]]:
        """ルールベースの分解"""
        for pattern in self.decomposition_patterns:
            if pattern.matches(request):
                return pattern.decompose(request)
        return None

    async def _llm_based_decompose(
        self,
        request: str,
        context: BrainContext,
    ) -> List[SubTask]:
        """LLMを使った分解"""
        prompt = self._build_decomposition_prompt(request, context)
        response = await self.llm_client.generate(prompt)
        return self._parse_decomposition_response(response)
```

**分解パターン例:**

```python
DECOMPOSITION_PATTERNS = [
    # 会議室予約パターン
    DecompositionPattern(
        name="meeting_room_reservation",
        triggers=["会議室", "予約", "ミーティングルーム"],
        conditions=["日時指定", "参加者指定"],
        subtasks=[
            SubTaskTemplate(
                name="空き確認",
                action="check_room_availability",
                depends_on=[],
            ),
            SubTaskTemplate(
                name="予約実行",
                action="reserve_meeting_room",
                depends_on=["空き確認"],
            ),
            SubTaskTemplate(
                name="招待送信",
                action="send_calendar_invite",
                depends_on=["予約実行"],
                is_optional=True,
            ),
        ],
    ),

    # タスク一括完了パターン
    DecompositionPattern(
        name="bulk_task_completion",
        triggers=["タスク", "完了", "一括", "まとめて"],
        conditions=["複数タスク指定"],
        subtasks=[
            SubTaskTemplate(
                name="タスク取得",
                action="chatwork_task_search",
                depends_on=[],
            ),
            SubTaskTemplate(
                name="一括完了",
                action="chatwork_task_complete_bulk",
                depends_on=["タスク取得"],
            ),
            SubTaskTemplate(
                name="完了報告",
                action="generate_completion_report",
                depends_on=["一括完了"],
            ),
        ],
    ),
]
```

### 21.5.2 ExecutionPlanner（実行計画立案）

```python
# lib/brain/execution_excellence/planner.py

class ExecutionPlanner:
    """
    実行計画立案

    サブタスクの依存関係を解析し、最適な実行順序を決定する。
    """

    def create_plan(
        self,
        subtasks: List[SubTask],
        request: str,
        context: BrainContext,
    ) -> ExecutionPlan:
        """
        実行計画を作成

        Args:
            subtasks: サブタスクリスト
            request: 元のリクエスト
            context: 脳コンテキスト

        Returns:
            実行計画
        """
        # 1. 依存関係グラフを構築
        dependency_graph = self._build_dependency_graph(subtasks)

        # 2. トポロジカルソート（循環依存チェック含む）
        sorted_tasks = self._topological_sort(dependency_graph)

        # 3. 並列実行可能グループを特定
        parallel_groups = self._identify_parallel_groups(sorted_tasks, dependency_graph)

        # 4. 実行計画を構築
        plan = ExecutionPlan(
            id=str(uuid.uuid4()),
            name=self._generate_plan_name(request),
            description=f"「{request}」の実行計画",
            original_request=request,
            subtasks=sorted_tasks,
            parallel_execution=len(parallel_groups) > 1,
            room_id=context.room_id,
            account_id=context.sender_account_id,
            organization_id=context.organization_id,
        )

        return plan

    def _build_dependency_graph(
        self,
        subtasks: List[SubTask],
    ) -> Dict[str, List[str]]:
        """依存関係グラフを構築"""
        graph = {st.id: st.depends_on for st in subtasks}
        return graph

    def _topological_sort(
        self,
        graph: Dict[str, List[str]],
    ) -> List[SubTask]:
        """トポロジカルソート"""
        # カーンのアルゴリズムを使用
        in_degree = {node: 0 for node in graph}
        for deps in graph.values():
            for dep in deps:
                in_degree[dep] = in_degree.get(dep, 0) + 1

        queue = [node for node, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor, deps in graph.items():
                if node in deps:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

        if len(result) != len(graph):
            raise ValueError("循環依存が検出されました")

        return result
```

### 21.5.3 WorkflowExecutor（ワークフロー実行）

```python
# lib/brain/execution_excellence/executor.py

class WorkflowExecutor:
    """
    ワークフロー実行

    ExecutionPlanに従ってサブタスクを実行する。
    """

    def __init__(
        self,
        handlers: Dict[str, Callable],
        progress_tracker: ProgressTracker,
        quality_checker: QualityChecker,
        exception_handler: ExceptionHandler,
        escalation_manager: EscalationManager,
    ):
        self.handlers = handlers
        self.progress_tracker = progress_tracker
        self.quality_checker = quality_checker
        self.exception_handler = exception_handler
        self.escalation_manager = escalation_manager

    async def execute(
        self,
        plan: ExecutionPlan,
        context: BrainContext,
    ) -> ExecutionResult:
        """
        実行計画を実行

        Args:
            plan: 実行計画
            context: 脳コンテキスト

        Returns:
            実行結果
        """
        plan.status = SubTaskStatus.IN_PROGRESS
        plan.started_at = datetime.now()

        try:
            # 1. 実行可能なタスクを順次/並列実行
            while not self._is_plan_complete(plan):
                ready_tasks = plan.get_ready_tasks()

                if not ready_tasks:
                    # 実行可能なタスクがない = デッドロックまたは全て完了
                    if not self._is_plan_complete(plan):
                        raise ExecutionError("実行可能なタスクがありません（デッドロック?）")
                    break

                # 並列実行
                if plan.parallel_execution and len(ready_tasks) > 1:
                    results = await asyncio.gather(
                        *[self._execute_subtask(st, plan, context) for st in ready_tasks],
                        return_exceptions=True,
                    )
                else:
                    # 順次実行
                    for task in ready_tasks:
                        await self._execute_subtask(task, plan, context)

                # 進捗更新
                await self.progress_tracker.update(plan)

            # 2. 品質チェック
            if plan.quality_checks_enabled:
                quality_report = await self.quality_checker.check_plan(plan)
                if quality_report.overall_result == QualityCheckResult.FAIL:
                    # 品質不合格 → エスカレーション
                    escalation = await self.escalation_manager.create_quality_escalation(
                        plan, quality_report
                    )
                    return self._create_result(plan, escalation=escalation)

            # 3. 完了
            plan.status = SubTaskStatus.COMPLETED
            plan.completed_at = datetime.now()

            return self._create_result(plan)

        except Exception as e:
            # 例外処理
            recovery_result = await self.exception_handler.handle(e, plan, context)
            return self._create_result(plan, error=recovery_result)

    async def _execute_subtask(
        self,
        subtask: SubTask,
        plan: ExecutionPlan,
        context: BrainContext,
    ) -> bool:
        """サブタスクを実行"""
        subtask.status = SubTaskStatus.IN_PROGRESS
        subtask.started_at = datetime.now()

        try:
            # ハンドラーを取得
            handler = self.handlers.get(subtask.action)
            if not handler:
                raise HandlerNotFoundError(f"ハンドラーが見つかりません: {subtask.action}")

            # 実行（リトライあり）
            for attempt in range(subtask.max_retries):
                try:
                    result = await asyncio.wait_for(
                        handler(
                            params=subtask.params,
                            room_id=plan.room_id,
                            account_id=plan.account_id,
                            sender_name=context.sender_name,
                            context=context,
                        ),
                        timeout=subtask.timeout_seconds,
                    )

                    if result.success:
                        subtask.status = SubTaskStatus.COMPLETED
                        subtask.result = result.data
                        subtask.completed_at = datetime.now()
                        return True

                    subtask.retry_count += 1

                except asyncio.TimeoutError:
                    subtask.retry_count += 1
                    if attempt == subtask.max_retries - 1:
                        raise

            # リトライ上限到達
            subtask.status = SubTaskStatus.FAILED
            subtask.error = "最大リトライ回数を超えました"
            return False

        except Exception as e:
            subtask.status = SubTaskStatus.FAILED
            subtask.error = str(e)

            # リカバリー戦略に基づく処理
            return await self._apply_recovery_strategy(subtask, plan, context, e)

    async def _apply_recovery_strategy(
        self,
        subtask: SubTask,
        plan: ExecutionPlan,
        context: BrainContext,
        error: Exception,
    ) -> bool:
        """リカバリー戦略を適用"""
        strategy = subtask.recovery_strategy

        if strategy == RecoveryStrategy.SKIP and subtask.is_optional:
            subtask.status = SubTaskStatus.SKIPPED
            return True

        elif strategy == RecoveryStrategy.ESCALATE:
            escalation = await self.escalation_manager.create_task_escalation(
                subtask, plan, error
            )
            subtask.status = SubTaskStatus.ESCALATED
            return False

        elif strategy == RecoveryStrategy.ABORT:
            plan.status = SubTaskStatus.FAILED
            raise ExecutionError(f"タスク失敗により中止: {subtask.name}")

        # RETRY, ALTERNATIVEは_execute_subtask内で処理済み
        return False
```

### 21.5.4 ProgressTracker（進捗追跡）

```python
# lib/brain/execution_excellence/progress.py

class ProgressTracker:
    """
    進捗追跡

    実行中のワークフローの進捗を追跡し、ユーザーに報告する。
    """

    def __init__(
        self,
        notification_threshold: float = 0.25,  # 25%ごとに通知
        stale_threshold_seconds: int = 60,      # 60秒動きがなければ通知
    ):
        self.notification_threshold = notification_threshold
        self.stale_threshold_seconds = stale_threshold_seconds
        self._last_notified_progress: Dict[str, float] = {}
        self._last_activity_time: Dict[str, datetime] = {}

    async def update(self, plan: ExecutionPlan) -> Optional[ProgressReport]:
        """
        進捗を更新

        必要に応じてユーザーに進捗を通知する。
        """
        report = self._create_report(plan)

        # 通知が必要か判定
        should_notify = self._should_notify(plan.id, report)

        if should_notify:
            self._last_notified_progress[plan.id] = report.progress_percentage
            self._last_activity_time[plan.id] = datetime.now()
            return report

        return None

    def _create_report(self, plan: ExecutionPlan) -> ProgressReport:
        """進捗レポートを作成"""
        in_progress = sum(
            1 for st in plan.subtasks if st.status == SubTaskStatus.IN_PROGRESS
        )
        pending = sum(
            1 for st in plan.subtasks if st.status == SubTaskStatus.PENDING
        )

        current_activity = "処理中..."
        in_progress_tasks = [
            st for st in plan.subtasks if st.status == SubTaskStatus.IN_PROGRESS
        ]
        if in_progress_tasks:
            current_activity = f"「{in_progress_tasks[0].name}」を実行中"

        issues = []
        failed_tasks = [
            st for st in plan.subtasks if st.status == SubTaskStatus.FAILED
        ]
        if failed_tasks:
            issues.append(f"{len(failed_tasks)}個のタスクが失敗")

        return ProgressReport(
            plan_id=plan.id,
            plan_name=plan.name,
            total_subtasks=len(plan.subtasks),
            completed_subtasks=plan.completed_count,
            failed_subtasks=plan.failed_count,
            in_progress_subtasks=in_progress,
            pending_subtasks=pending,
            progress_percentage=plan.progress * 100,
            current_activity=current_activity,
            issues=issues,
        )

    def _should_notify(self, plan_id: str, report: ProgressReport) -> bool:
        """通知すべきか判定"""
        last_progress = self._last_notified_progress.get(plan_id, 0)
        progress_diff = report.progress_percentage - last_progress

        # 進捗が閾値を超えた
        if progress_diff >= self.notification_threshold * 100:
            return True

        # 長時間動きがない
        last_activity = self._last_activity_time.get(plan_id)
        if last_activity:
            elapsed = (datetime.now() - last_activity).total_seconds()
            if elapsed >= self.stale_threshold_seconds:
                return True

        # 完了または失敗
        if report.progress_percentage >= 100 or report.failed_subtasks > 0:
            return True

        return False
```

### 21.5.5 QualityChecker（品質チェッカー）

```python
# lib/brain/execution_excellence/quality.py

class QualityChecker:
    """
    品質チェッカー

    実行結果の品質を検証する。
    """

    def __init__(self, checks: Optional[List[QualityCheck]] = None):
        self.checks = checks or self._default_checks()

    async def check_plan(self, plan: ExecutionPlan) -> QualityReport:
        """
        実行計画全体の品質をチェック
        """
        check_results = []
        issues = []
        warnings = []

        for check in self.checks:
            result = await check.execute(plan)
            check_results.append({
                "name": check.name,
                "result": result.status.value,
                "score": result.score,
                "message": result.message,
            })

            if result.status == QualityCheckResult.FAIL:
                issues.append(f"{check.name}: {result.message}")
            elif result.status == QualityCheckResult.WARNING:
                warnings.append(f"{check.name}: {result.message}")

        # 総合スコア計算
        total_score = sum(r["score"] for r in check_results) / len(check_results)

        # 総合結果判定
        if any(r["result"] == "fail" for r in check_results):
            overall_result = QualityCheckResult.FAIL
        elif any(r["result"] == "warning" for r in check_results):
            overall_result = QualityCheckResult.WARNING
        else:
            overall_result = QualityCheckResult.PASS

        return QualityReport(
            plan_id=plan.id,
            overall_result=overall_result,
            quality_score=total_score,
            checks=check_results,
            issues=issues,
            warnings=warnings,
        )

    def _default_checks(self) -> List[QualityCheck]:
        """デフォルトの品質チェック"""
        return [
            CompletionRateCheck(),      # 完了率チェック
            ErrorRateCheck(),           # エラー率チェック
            ExecutionTimeCheck(),       # 実行時間チェック
            DataIntegrityCheck(),       # データ整合性チェック
        ]
```

### 21.5.6 ExceptionHandler（例外処理）

```python
# lib/brain/execution_excellence/exception_handler.py

class ExceptionHandler:
    """
    例外処理

    実行中のエラーを処理し、適切なリカバリーを行う。
    """

    async def handle(
        self,
        error: Exception,
        plan: ExecutionPlan,
        context: BrainContext,
    ) -> RecoveryResult:
        """
        エラーを処理

        Args:
            error: 発生したエラー
            plan: 実行計画
            context: 脳コンテキスト

        Returns:
            リカバリー結果
        """
        error_type = type(error).__name__

        # エラータイプに応じた処理
        if error_type in TRANSIENT_ERRORS:
            # 一時的エラー → リトライ
            return await self._retry_recovery(error, plan)

        elif error_type in PERMISSION_ERRORS:
            # 権限エラー → エスカレーション
            return await self._escalate_permission_error(error, plan, context)

        elif error_type in DATA_ERRORS:
            # データエラー → 代替案提示
            return await self._suggest_alternative(error, plan, context)

        else:
            # 未知のエラー → ログ記録してエスカレーション
            logger.error(f"Unknown error in execution: {error}", exc_info=True)
            return await self._escalate_unknown_error(error, plan, context)

    async def _retry_recovery(
        self,
        error: Exception,
        plan: ExecutionPlan,
    ) -> RecoveryResult:
        """リトライによるリカバリー"""
        # 指数バックオフでリトライ
        delay = 2 ** plan.current_step  # 1, 2, 4, 8...秒
        await asyncio.sleep(min(delay, 30))  # 最大30秒

        return RecoveryResult(
            strategy=RecoveryStrategy.RETRY,
            success=True,
            message="リトライします",
        )

    async def _suggest_alternative(
        self,
        error: Exception,
        plan: ExecutionPlan,
        context: BrainContext,
    ) -> RecoveryResult:
        """代替案を提案"""
        alternatives = self._find_alternatives(plan, error)

        if alternatives:
            return RecoveryResult(
                strategy=RecoveryStrategy.ALTERNATIVE,
                success=True,
                message=f"代替案があるウル: {alternatives[0]}",
                alternatives=alternatives,
            )

        return RecoveryResult(
            strategy=RecoveryStrategy.ESCALATE,
            success=False,
            message="代替案が見つからないウル...",
        )
```

### 21.5.7 EscalationManager（エスカレーション管理）

```python
# lib/brain/execution_excellence/escalation.py

class EscalationManager:
    """
    エスカレーション管理

    自動処理できない問題を人間にエスカレーションする。
    """

    def __init__(
        self,
        chatwork_client: Any,
        default_timeout_minutes: int = 30,
    ):
        self.chatwork_client = chatwork_client
        self.default_timeout_minutes = default_timeout_minutes
        self._pending_escalations: Dict[str, EscalationRequest] = {}

    async def create_task_escalation(
        self,
        subtask: SubTask,
        plan: ExecutionPlan,
        error: Exception,
    ) -> EscalationRequest:
        """タスク失敗のエスカレーションを作成"""
        escalation = EscalationRequest(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            subtask_id=subtask.id,
            level=EscalationLevel.DECISION,
            title=f"「{subtask.name}」の実行に失敗しました",
            description=f"エラー内容: {str(error)}",
            context=f"「{plan.original_request}」の一部として実行中でした",
            options=[
                {"id": "retry", "label": "リトライ", "description": "もう一度試します"},
                {"id": "skip", "label": "スキップ", "description": "このタスクを飛ばして続行"},
                {"id": "abort", "label": "中止", "description": "全体の処理を中止"},
            ],
            recommendation="retry",
            recommendation_reasoning="一時的なエラーの可能性があります",
        )

        # 通知送信
        await self._send_notification(escalation, plan.room_id)

        self._pending_escalations[escalation.id] = escalation

        return escalation

    async def create_quality_escalation(
        self,
        plan: ExecutionPlan,
        quality_report: QualityReport,
    ) -> EscalationRequest:
        """品質問題のエスカレーションを作成"""
        escalation = EscalationRequest(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            level=EscalationLevel.CONFIRMATION,
            title="品質チェックで問題が見つかりました",
            description=f"問題点: {', '.join(quality_report.issues)}",
            context=f"「{plan.original_request}」の実行結果です",
            options=[
                {"id": "accept", "label": "そのまま完了", "description": "問題を許容して完了"},
                {"id": "retry", "label": "やり直し", "description": "最初からやり直し"},
                {"id": "manual", "label": "手動対応", "description": "自分で対応する"},
            ],
            recommendation="accept" if quality_report.quality_score > 0.7 else "manual",
        )

        await self._send_notification(escalation, plan.room_id)

        self._pending_escalations[escalation.id] = escalation

        return escalation

    async def process_response(
        self,
        escalation_id: str,
        response: str,
        reasoning: Optional[str] = None,
    ) -> bool:
        """エスカレーションへの応答を処理"""
        escalation = self._pending_escalations.get(escalation_id)
        if not escalation:
            return False

        escalation.status = "responded"
        escalation.response = response
        escalation.response_reasoning = reasoning
        escalation.responded_at = datetime.now()

        return True

    async def _send_notification(
        self,
        escalation: EscalationRequest,
        room_id: str,
    ) -> None:
        """通知を送信"""
        message = escalation.to_user_message()

        result = await self.chatwork_client.send_message(
            room_id=room_id,
            body=message,
        )

        escalation.notification_sent = True
        escalation.notification_room_id = room_id
        escalation.notification_message_id = result.get("message_id")
```

---

## 21.6 統合設計

### 21.6.1 ExecutionExcellence統合クラス

```python
# lib/brain/execution_excellence/__init__.py

class ExecutionExcellence:
    """
    実行力強化の統合クラス

    TaskDecomposer、ExecutionPlanner、WorkflowExecutor、
    およびサポートコンポーネントを統合する。
    """

    def __init__(
        self,
        pool,
        org_id: str,
        handlers: Dict[str, Callable],
        capabilities: Dict[str, Dict],
        chatwork_client: Optional[Any] = None,
        llm_client: Optional[Any] = None,
    ):
        self.pool = pool
        self.org_id = org_id

        # コンポーネント初期化
        self.decomposer = TaskDecomposer(capabilities, llm_client)
        self.planner = ExecutionPlanner()
        self.progress_tracker = ProgressTracker()
        self.quality_checker = QualityChecker()
        self.exception_handler = ExceptionHandler()
        self.escalation_manager = EscalationManager(chatwork_client)

        self.executor = WorkflowExecutor(
            handlers=handlers,
            progress_tracker=self.progress_tracker,
            quality_checker=self.quality_checker,
            exception_handler=self.exception_handler,
            escalation_manager=self.escalation_manager,
        )

    async def execute_request(
        self,
        request: str,
        context: BrainContext,
    ) -> ExecutionResult:
        """
        リクエストを実行

        Args:
            request: ユーザーリクエスト
            context: 脳コンテキスト

        Returns:
            実行結果
        """
        # 1. タスク分解
        subtasks = await self.decomposer.decompose(request, context)

        if len(subtasks) == 1:
            # 単一タスクの場合は従来の実行層を使用
            return await self._execute_single_task(subtasks[0], context)

        # 2. 実行計画立案
        plan = self.planner.create_plan(subtasks, request, context)

        # 3. ワークフロー実行
        result = await self.executor.execute(plan, context)

        # 4. 実行結果を記録（学習用）
        await self._log_execution(plan, result)

        return result

    def should_use_workflow(self, request: str, context: BrainContext) -> bool:
        """
        ワークフロー実行を使うべきか判定

        複雑なリクエストの場合はTrue
        """
        # 複数のアクションを示唆するキーワード
        multi_action_keywords = [
            "して、", "した後", "してから",
            "と、", "それから", "その後",
            "一括", "まとめて", "全部",
        ]

        for keyword in multi_action_keywords:
            if keyword in request:
                return True

        return False
```

### 21.6.2 脳への統合

```python
# lib/brain/core.py への追加

class SoulkunBrain:
    def __init__(self, ...):
        # ... 既存の初期化 ...

        # Phase 2L: ExecutionExcellence
        self.execution_excellence = self._init_execution_excellence()

    def _init_execution_excellence(self) -> Optional[ExecutionExcellence]:
        """ExecutionExcellenceを初期化"""
        if not is_feature_enabled("ENABLE_EXECUTION_EXCELLENCE"):
            return None

        return ExecutionExcellence(
            pool=self.pool,
            org_id=self.org_id,
            handlers=self.handlers,
            capabilities=self.capabilities,
            chatwork_client=self.chatwork_client,
            llm_client=self.llm_client,
        )

    async def _execute(
        self,
        decision: DecisionResult,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> HandlerResult:
        """
        実行層 - 判断結果を実行
        """
        # Phase 2L: 複雑なリクエストはExecutionExcellenceを使用
        if self.execution_excellence:
            original_message = context.recent_conversation[-1].content if context.recent_conversation else ""

            if self.execution_excellence.should_use_workflow(original_message, context):
                result = await self.execution_excellence.execute_request(
                    request=original_message,
                    context=context,
                )
                return HandlerResult(
                    success=result.success,
                    message=result.message,
                    suggestions=result.suggestions,
                )

        # 従来の実行フロー
        return await self.execution_layer.execute(
            decision=decision,
            context=context,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )
```

---

## 21.7 DB設計

### 21.7.1 新規テーブル

```sql
-- 実行計画テーブル
CREATE TABLE execution_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    room_id VARCHAR(50) NOT NULL,
    account_id VARCHAR(50) NOT NULL,

    name VARCHAR(200) NOT NULL,
    description TEXT,
    original_request TEXT NOT NULL,

    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    progress DECIMAL(5, 2) DEFAULT 0.00,

    parallel_execution BOOLEAN DEFAULT TRUE,
    continue_on_failure BOOLEAN DEFAULT FALSE,
    quality_checks_enabled BOOLEAN DEFAULT TRUE,
    required_quality_level DECIMAL(3, 2) DEFAULT 0.80,

    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT fk_organization
        FOREIGN KEY (organization_id)
        REFERENCES organizations(id) ON DELETE CASCADE
);

-- サブタスクテーブル
CREATE TABLE execution_subtasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES execution_plans(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,

    name VARCHAR(200) NOT NULL,
    description TEXT,
    action VARCHAR(100) NOT NULL,
    params JSONB DEFAULT '{}',

    depends_on TEXT[] DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    priority VARCHAR(20) DEFAULT 'normal',

    is_optional BOOLEAN DEFAULT FALSE,
    max_retries INTEGER DEFAULT 3,
    timeout_seconds INTEGER DEFAULT 60,
    recovery_strategy VARCHAR(20) DEFAULT 'retry',

    result JSONB,
    error TEXT,
    retry_count INTEGER DEFAULT 0,

    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT fk_plan
        FOREIGN KEY (plan_id)
        REFERENCES execution_plans(id) ON DELETE CASCADE
);

-- エスカレーションテーブル
CREATE TABLE execution_escalations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES execution_plans(id),
    subtask_id UUID REFERENCES execution_subtasks(id),
    organization_id UUID NOT NULL,

    level VARCHAR(20) NOT NULL DEFAULT 'confirmation',
    title VARCHAR(300) NOT NULL,
    description TEXT,
    context TEXT,

    options JSONB DEFAULT '[]',
    default_option VARCHAR(50),
    recommendation VARCHAR(50),
    recommendation_reasoning TEXT,

    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    response VARCHAR(50),
    response_reasoning TEXT,

    expires_at TIMESTAMP WITH TIME ZONE,
    responded_at TIMESTAMP WITH TIME ZONE,

    notification_sent BOOLEAN DEFAULT FALSE,
    notification_room_id VARCHAR(50),
    notification_message_id VARCHAR(50),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT fk_plan
        FOREIGN KEY (plan_id)
        REFERENCES execution_plans(id) ON DELETE CASCADE
);

-- インデックス
CREATE INDEX idx_execution_plans_org_status ON execution_plans(organization_id, status);
CREATE INDEX idx_execution_plans_room ON execution_plans(room_id, created_at DESC);
CREATE INDEX idx_execution_subtasks_plan ON execution_subtasks(plan_id);
CREATE INDEX idx_execution_subtasks_status ON execution_subtasks(status);
CREATE INDEX idx_execution_escalations_plan ON execution_escalations(plan_id);
CREATE INDEX idx_execution_escalations_status ON execution_escalations(status);
```

---

## 21.8 Feature Flags

```python
# lib/feature_flags.py に追加

EXECUTION_EXCELLENCE_FLAGS = {
    # メイン機能フラグ
    "ENABLE_EXECUTION_EXCELLENCE": {
        "default": False,
        "description": "Phase 2L: 実行力強化を有効化",
    },

    # サブ機能フラグ
    "ENABLE_TASK_DECOMPOSITION": {
        "default": True,
        "description": "タスク自動分解を有効化",
        "depends_on": "ENABLE_EXECUTION_EXCELLENCE",
    },
    "ENABLE_PARALLEL_EXECUTION": {
        "default": True,
        "description": "並列実行を有効化",
        "depends_on": "ENABLE_EXECUTION_EXCELLENCE",
    },
    "ENABLE_QUALITY_CHECKS": {
        "default": True,
        "description": "品質チェックを有効化",
        "depends_on": "ENABLE_EXECUTION_EXCELLENCE",
    },
    "ENABLE_AUTO_ESCALATION": {
        "default": True,
        "description": "自動エスカレーションを有効化",
        "depends_on": "ENABLE_EXECUTION_EXCELLENCE",
    },

    # LLM使用フラグ
    "ENABLE_LLM_DECOMPOSITION": {
        "default": False,
        "description": "LLMベースのタスク分解を有効化（コスト注意）",
        "depends_on": "ENABLE_TASK_DECOMPOSITION",
    },
}
```

---

## 21.9 テスト計画

### 21.9.1 ユニットテスト

```python
# tests/test_execution_excellence.py

class TestTaskDecomposer:
    """TaskDecomposerのテスト"""

    @pytest.mark.asyncio
    async def test_simple_request_not_decomposed(self):
        """単純なリクエストは分解されない"""
        decomposer = TaskDecomposer(CAPABILITIES)
        subtasks = await decomposer.decompose(
            "自分のタスク教えて",
            mock_context(),
        )
        assert len(subtasks) == 1

    @pytest.mark.asyncio
    async def test_complex_request_decomposed(self):
        """複雑なリクエストは分解される"""
        decomposer = TaskDecomposer(CAPABILITIES)
        subtasks = await decomposer.decompose(
            "会議室Aを明日14時で予約して、参加者に招待送って",
            mock_context(),
        )
        assert len(subtasks) >= 2


class TestWorkflowExecutor:
    """WorkflowExecutorのテスト"""

    @pytest.mark.asyncio
    async def test_sequential_execution(self):
        """依存タスクが順次実行される"""
        ...

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        """独立タスクが並列実行される"""
        ...

    @pytest.mark.asyncio
    async def test_failure_recovery(self):
        """失敗時にリカバリーされる"""
        ...

    @pytest.mark.asyncio
    async def test_escalation_on_unrecoverable_error(self):
        """回復不能エラーでエスカレーションされる"""
        ...
```

### 21.9.2 統合テスト

```python
class TestExecutionExcellenceIntegration:
    """統合テスト"""

    @pytest.mark.asyncio
    async def test_end_to_end_workflow(self):
        """E2Eワークフロー実行"""
        brain = SoulkunBrain(...)
        response = await brain.process_message(
            message="タスク「報告書作成」を作って、田中さんに割り当てて",
            room_id="123",
            account_id="456",
            sender_name="菊地",
        )
        assert response.success
        # 両方のアクションが実行されたことを確認
        ...
```

---

## 21.10 実装順序

| 順序 | タスク | 優先度 | 想定工数 |
|------|--------|--------|----------|
| 1 | データモデル定義 | 高 | 小 |
| 2 | DBマイグレーション | 高 | 小 |
| 3 | TaskDecomposer実装 | 高 | 中 |
| 4 | ExecutionPlanner実装 | 高 | 中 |
| 5 | ProgressTracker実装 | 中 | 小 |
| 6 | QualityChecker実装 | 中 | 小 |
| 7 | ExceptionHandler実装 | 中 | 中 |
| 8 | EscalationManager実装 | 中 | 中 |
| 9 | WorkflowExecutor実装 | 高 | 大 |
| 10 | ExecutionExcellence統合 | 高 | 中 |
| 11 | 脳への統合 | 高 | 中 |
| 12 | テスト追加 | 高 | 中 |
| 13 | 本番デプロイ | 高 | 小 |

---

## 21.11 リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| 無限ループ | サービス停止 | 最大実行回数制限、タイムアウト設定 |
| リソース枯渇 | パフォーマンス低下 | 並列実行数制限、キュー管理 |
| エスカレーション過多 | ユーザー疲れ | 閾値調整、自動解決率向上 |
| 品質チェック誤検知 | 無駄な中断 | 閾値チューニング、学習による改善 |
| 複雑なリクエスト誤分解 | 意図と異なる実行 | 確認フロー追加、LLM精度向上 |

---

## 21.12 成功指標

| 指標 | 現状 | Phase 2L完了後目標 |
|------|------|-------------------|
| 複雑なリクエスト完遂率 | N/A | 80%以上 |
| エスカレーション応答時間 | N/A | 平均5分以内 |
| 自動リカバリー成功率 | N/A | 70%以上 |
| ユーザー満足度（複雑タスク） | N/A | 4.0/5.0以上 |

---

**[📁 目次に戻る](00_README.md)**
