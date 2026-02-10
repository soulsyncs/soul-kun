# lib/brain/execution_excellence/planner.py
"""
Phase 2L: 実行力強化（Execution Excellence） - 実行計画立案

サブタスクの依存関係を解析し、最適な実行順序を決定するコンポーネント。

設計書: docs/21_phase2l_execution_excellence.md
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from lib.brain.models import BrainContext
from lib.brain.execution_excellence.models import (
    SubTask,
    ExecutionPlan,
    ExecutionPriority,
    create_execution_plan,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================


# デフォルトの計画名生成キーワード
PLAN_NAME_KEYWORDS = {
    "chatwork_task": "タスク管理",
    "meeting_room": "会議室予約",
    "announcement": "アナウンス",
    "knowledge": "ナレッジ",
    "goal": "目標",
    "calendar": "カレンダー",
}


# =============================================================================
# 依存関係グラフ
# =============================================================================


class DependencyGraph:
    """
    依存関係グラフ

    サブタスク間の依存関係を管理し、トポロジカルソートを提供。
    """

    def __init__(self, subtasks: List[SubTask]):
        """
        グラフを初期化

        Args:
            subtasks: サブタスクリスト
        """
        self.subtasks = {st.id: st for st in subtasks}
        self.adjacency: Dict[str, List[str]] = defaultdict(list)  # id -> depends_on
        self.reverse_adjacency: Dict[str, List[str]] = defaultdict(list)  # id -> blocks

        self._build_graph()

    def _build_graph(self) -> None:
        """グラフを構築"""
        for subtask in self.subtasks.values():
            for dep_id in subtask.depends_on:
                if dep_id in self.subtasks:
                    self.adjacency[subtask.id].append(dep_id)
                    self.reverse_adjacency[dep_id].append(subtask.id)
                else:
                    logger.warning(
                        f"Unknown dependency: {subtask.id} depends on {dep_id}"
                    )

    def has_cycle(self) -> bool:
        """
        循環依存があるかチェック

        Returns:
            循環があればTrue
        """
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in self.adjacency.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for node in self.subtasks:
            if node not in visited:
                if dfs(node):
                    return True

        return False

    def topological_sort(self) -> List[SubTask]:
        """
        トポロジカルソート

        依存関係を考慮した実行順序でサブタスクを返す。

        Returns:
            ソート済みサブタスクリスト

        Raises:
            ValueError: 循環依存がある場合
        """
        if self.has_cycle():
            raise ValueError("循環依存が検出されました")

        # カーンのアルゴリズム
        in_degree: Dict[str, int] = defaultdict(int)

        for node in self.subtasks:
            in_degree[node] = len(self.adjacency.get(node, []))

        # 入次数0のノードをキューに追加
        queue = [
            node_id for node_id, degree in in_degree.items()
            if degree == 0
        ]

        result = []

        while queue:
            # 優先度の高いタスクを先に処理
            queue.sort(key=lambda nid: -self._get_priority_value(nid))
            node = queue.pop(0)
            result.append(self.subtasks[node])

            # 隣接ノードの入次数を減らす
            for neighbor in self.reverse_adjacency.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self.subtasks):
            # これは起こらないはず（has_cycleで検出済み）
            raise ValueError("トポロジカルソートに失敗しました")

        return result

    def _get_priority_value(self, subtask_id: str) -> int:
        """優先度の数値を取得"""
        subtask = self.subtasks.get(subtask_id)
        if not subtask:
            return 0

        priority_values = {
            ExecutionPriority.CRITICAL: 100,
            ExecutionPriority.HIGH: 75,
            ExecutionPriority.NORMAL: 50,
            ExecutionPriority.LOW: 25,
        }
        return priority_values.get(subtask.priority, 50)

    def identify_parallel_groups(self) -> List[List[SubTask]]:
        """
        並列実行可能なグループを特定

        同じ「レイヤー」に属するタスク（相互に依存がない）をグループ化。

        Returns:
            並列実行可能なグループのリスト
        """
        groups: List[List[SubTask]] = []
        remaining = set(self.subtasks.keys())
        completed: Set[str] = set()

        while remaining:
            # このイテレーションで実行可能なタスク
            ready = [
                st_id for st_id in remaining
                if all(dep in completed for dep in self.adjacency.get(st_id, []))
            ]

            if not ready:
                # デッドロック（循環依存はチェック済みなので起こらないはず）
                logger.error("Deadlock detected in parallel group identification")
                break

            group = [self.subtasks[st_id] for st_id in ready]
            groups.append(group)

            for st_id in ready:
                completed.add(st_id)
                remaining.remove(st_id)

        return groups

    def get_critical_path(self) -> List[SubTask]:
        """
        クリティカルパスを取得

        最も長い依存チェーンを特定。

        Returns:
            クリティカルパス上のサブタスク
        """
        # 各ノードからの最長パスを計算
        memo: Dict[str, int] = {}

        def longest_path_from(node: str) -> int:
            if node in memo:
                return memo[node]

            max_length = 1
            for neighbor in self.reverse_adjacency.get(node, []):
                max_length = max(max_length, 1 + longest_path_from(neighbor))

            memo[node] = max_length
            return max_length

        # 全ノードの最長パスを計算
        for node in self.subtasks:
            longest_path_from(node)

        # 最長パスの始点を見つける
        if not memo:
            return list(self.subtasks.values())

        max_length = max(memo.values())
        start_nodes = [n for n, length in memo.items() if length == max_length]

        # クリティカルパスを再構築
        critical_path = []
        current = start_nodes[0] if start_nodes else None

        while current:
            critical_path.append(self.subtasks[current])
            next_nodes = self.reverse_adjacency.get(current, [])
            if not next_nodes:
                break
            # 最長パスを持つ次のノードを選択
            current = max(next_nodes, key=lambda n: memo.get(n, 0))

        return critical_path


# =============================================================================
# ExecutionPlanner
# =============================================================================


class ExecutionPlanner:
    """
    実行計画立案

    サブタスクの依存関係を解析し、最適な実行順序を決定する。
    """

    def __init__(
        self,
        default_parallel_execution: bool = True,
        default_continue_on_failure: bool = False,
        default_quality_checks_enabled: bool = True,
    ):
        """
        実行計画立案を初期化

        Args:
            default_parallel_execution: デフォルトで並列実行を有効化
            default_continue_on_failure: デフォルトで失敗時も続行
            default_quality_checks_enabled: デフォルトで品質チェックを有効化
        """
        self.default_parallel_execution = default_parallel_execution
        self.default_continue_on_failure = default_continue_on_failure
        self.default_quality_checks_enabled = default_quality_checks_enabled

        logger.debug(
            f"ExecutionPlanner initialized: "
            f"parallel={default_parallel_execution}, "
            f"continue_on_failure={default_continue_on_failure}"
        )

    def create_plan(
        self,
        subtasks: List[SubTask],
        request: str,
        context: BrainContext,
        parallel_execution: Optional[bool] = None,
        continue_on_failure: Optional[bool] = None,
    ) -> ExecutionPlan:
        """
        実行計画を作成

        Args:
            subtasks: サブタスクリスト
            request: 元のリクエスト
            context: 脳コンテキスト
            parallel_execution: 並列実行を許可（Noneならデフォルト）
            continue_on_failure: 失敗時も続行（Noneならデフォルト）

        Returns:
            実行計画

        Raises:
            ValueError: 循環依存がある場合
        """
        logger.info(f"Creating execution plan for {len(subtasks)} subtasks")

        # 1. 依存関係グラフを構築
        graph = DependencyGraph(subtasks)

        # 2. 循環依存チェック
        if graph.has_cycle():
            logger.error("Circular dependency detected")
            raise ValueError("循環依存が検出されました。タスクの依存関係を確認してください。")

        # 3. トポロジカルソート
        sorted_tasks = graph.topological_sort()

        # 4. 並列実行可能グループを特定
        parallel_groups = graph.identify_parallel_groups()

        # 5. 計画名を生成
        plan_name = self._generate_plan_name(request, subtasks)

        # 6. 並列実行の判断
        use_parallel = parallel_execution if parallel_execution is not None else self.default_parallel_execution
        # 並列グループが1つだけなら並列の意味がない
        if len(parallel_groups) <= 1 or all(len(g) <= 1 for g in parallel_groups):
            use_parallel = False

        # 7. 実行計画を構築
        plan = ExecutionPlan(
            id=str(uuid.uuid4()),
            name=plan_name,
            description=f"「{request[:50]}...」の実行計画",
            original_request=request,
            subtasks=sorted_tasks,
            parallel_execution=use_parallel,
            continue_on_failure=continue_on_failure if continue_on_failure is not None else self.default_continue_on_failure,
            quality_checks_enabled=self.default_quality_checks_enabled,
            room_id=context.room_id,
            account_id=context.sender_account_id,
            organization_id=context.organization_id,
        )

        logger.info(
            f"Plan created: {plan_name}, "
            f"subtasks={len(sorted_tasks)}, "
            f"parallel_groups={len(parallel_groups)}, "
            f"parallel_execution={use_parallel}"
        )

        return plan

    def _generate_plan_name(
        self,
        request: str,
        subtasks: List[SubTask],
    ) -> str:
        """
        計画名を生成

        Args:
            request: 元のリクエスト
            subtasks: サブタスクリスト

        Returns:
            計画名
        """
        # アクション名からキーワードを探す
        for subtask in subtasks:
            for keyword, name in PLAN_NAME_KEYWORDS.items():
                if keyword in subtask.action:
                    return f"{name}ワークフロー"

        # リクエストからキーワードを探す
        request_lower = request.lower()
        for keyword, name in PLAN_NAME_KEYWORDS.items():
            if keyword.replace("_", "") in request_lower:
                return f"{name}ワークフロー"

        # デフォルト
        return "複合タスク実行"

    def estimate_execution_time(self, plan: ExecutionPlan) -> int:
        """
        実行時間を推定（秒）

        Args:
            plan: 実行計画

        Returns:
            推定実行時間（秒）
        """
        if not plan.subtasks:
            return 0

        if plan.parallel_execution:
            # 並列実行の場合、クリティカルパスの時間
            graph = DependencyGraph(plan.subtasks)
            critical_path = graph.get_critical_path()
            return sum(st.timeout_seconds for st in critical_path)
        else:
            # 順次実行の場合、全タスクの合計
            return sum(st.timeout_seconds for st in plan.subtasks)

    def validate_plan(self, plan: ExecutionPlan) -> Tuple[bool, List[str]]:
        """
        計画を検証

        Args:
            plan: 実行計画

        Returns:
            (有効か, エラーメッセージリスト)
        """
        errors = []

        # サブタスクがあるか
        if not plan.subtasks:
            errors.append("サブタスクがありません")

        # 依存関係の整合性
        subtask_ids = {st.id for st in plan.subtasks}
        for subtask in plan.subtasks:
            for dep_id in subtask.depends_on:
                if dep_id not in subtask_ids:
                    errors.append(
                        f"サブタスク「{subtask.name}」の依存先「{dep_id}」が見つかりません"
                    )

        # 循環依存
        try:
            graph = DependencyGraph(plan.subtasks)
            if graph.has_cycle():
                errors.append("循環依存が検出されました")
        except Exception as e:
            errors.append(f"依存関係の検証に失敗: {type(e).__name__}")

        return len(errors) == 0, errors


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_execution_planner(
    parallel_execution: bool = True,
    continue_on_failure: bool = False,
    quality_checks_enabled: bool = True,
) -> ExecutionPlanner:
    """
    ExecutionPlannerを作成

    Args:
        parallel_execution: 並列実行を有効化
        continue_on_failure: 失敗時も続行
        quality_checks_enabled: 品質チェックを有効化

    Returns:
        ExecutionPlanner
    """
    return ExecutionPlanner(
        default_parallel_execution=parallel_execution,
        default_continue_on_failure=continue_on_failure,
        default_quality_checks_enabled=quality_checks_enabled,
    )
