# lib/brain/execution_excellence/decomposer.py
"""
Phase 2L: 実行力強化（Execution Excellence） - タスク分解器

複雑なユーザーリクエストをサブタスクに分解するコンポーネント。

設計書: docs/21_phase2l_execution_excellence.md
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Callable, Dict, List, Optional

from lib.brain.models import BrainContext
from lib.brain.execution_excellence.models import (
    SubTask,
    SubTaskTemplate,
    DecompositionPattern,
    RecoveryStrategy,
    create_subtask,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 分解パターン定義
# =============================================================================


# タスク関連パターン
TASK_PATTERNS = [
    DecompositionPattern(
        name="task_create_and_assign",
        triggers=["タスク", "作成", "作って", "割り当て", "アサイン", "担当"],
        subtask_templates=[
            SubTaskTemplate(
                name="タスク作成",
                action="chatwork_task_create",
                description="新しいタスクを作成",
                param_mappings={"body": "task_body", "limit_time": "deadline"},
            ),
            SubTaskTemplate(
                name="担当者設定",
                action="chatwork_task_assign",
                description="タスクに担当者を設定",
                depends_on=["タスク作成"],
                param_mappings={"assignee_name": "assignee"},
                is_optional=True,
            ),
        ],
        priority=10,
    ),
    DecompositionPattern(
        name="bulk_task_completion",
        triggers=["タスク", "完了", "一括", "まとめて", "全部"],
        subtask_templates=[
            SubTaskTemplate(
                name="タスク検索",
                action="chatwork_task_search",
                description="対象タスクを検索",
            ),
            SubTaskTemplate(
                name="一括完了",
                action="chatwork_task_complete_bulk",
                description="タスクを一括完了",
                depends_on=["タスク検索"],
            ),
            SubTaskTemplate(
                name="完了報告",
                action="generate_completion_summary",
                description="完了報告を生成",
                depends_on=["一括完了"],
                is_optional=True,
            ),
        ],
        priority=8,
    ),
]

# 会議室予約パターン
MEETING_PATTERNS = [
    DecompositionPattern(
        name="meeting_room_reservation",
        triggers=["会議室", "予約", "ミーティングルーム", "招待", "カレンダー"],
        subtask_templates=[
            SubTaskTemplate(
                name="空き確認",
                action="check_room_availability",
                description="会議室の空き状況を確認",
                param_mappings={"room_name": "room", "datetime": "datetime"},
            ),
            SubTaskTemplate(
                name="予約実行",
                action="reserve_meeting_room",
                description="会議室を予約",
                depends_on=["空き確認"],
                param_mappings={"room_name": "room", "datetime": "datetime"},
            ),
            SubTaskTemplate(
                name="招待送信",
                action="send_calendar_invite",
                description="参加者にカレンダー招待を送信",
                depends_on=["予約実行"],
                param_mappings={"attendees": "participants"},
                is_optional=True,
            ),
        ],
        priority=10,
    ),
]

# アナウンスパターン
ANNOUNCEMENT_PATTERNS = [
    DecompositionPattern(
        name="multi_room_announcement",
        triggers=["アナウンス", "お知らせ", "周知", "複数", "ルーム", "全員"],
        subtask_templates=[
            SubTaskTemplate(
                name="対象ルーム特定",
                action="identify_target_rooms",
                description="アナウンス対象のルームを特定",
            ),
            SubTaskTemplate(
                name="アナウンス送信",
                action="announcement_create",
                description="アナウンスを送信",
                depends_on=["対象ルーム特定"],
                param_mappings={"message": "announcement_text"},
            ),
            SubTaskTemplate(
                name="送信確認",
                action="verify_announcement_delivery",
                description="送信結果を確認",
                depends_on=["アナウンス送信"],
                is_optional=True,
            ),
        ],
        priority=8,
    ),
]

# ナレッジ関連パターン
KNOWLEDGE_PATTERNS = [
    DecompositionPattern(
        name="knowledge_search_and_summarize",
        triggers=["調べて", "まとめて", "要約", "レポート", "報告"],
        subtask_templates=[
            SubTaskTemplate(
                name="ナレッジ検索",
                action="query_knowledge",
                description="関連するナレッジを検索",
                param_mappings={"query": "search_query"},
            ),
            SubTaskTemplate(
                name="要約生成",
                action="generate_summary",
                description="検索結果を要約",
                depends_on=["ナレッジ検索"],
            ),
        ],
        priority=6,
    ),
]

# 全パターン
ALL_DECOMPOSITION_PATTERNS = (
    TASK_PATTERNS +
    MEETING_PATTERNS +
    ANNOUNCEMENT_PATTERNS +
    KNOWLEDGE_PATTERNS
)


# =============================================================================
# 複合アクション検出
# =============================================================================


# 複合を示すキーワード
CONJUNCTION_KEYWORDS = [
    "して、", "した後", "してから",
    "って、", "って,", "て、",  # 「作って、」「教えて、」
    "と、", "それから", "その後",
    "一括", "まとめて", "全部",
    "ついでに", "あと", "さらに",
    "に割り当て", "を割り当て",  # 複合アクションを示す
]

# 否定・制限キーワード（これらがあると単純リクエストになる可能性）
NEGATION_KEYWORDS = [
    "だけ", "のみ", "それだけ",
    "簡単に", "とりあえず",
]


def detect_multi_action_request(request: str) -> bool:
    """
    複合アクションリクエストかを検出

    Args:
        request: ユーザーリクエスト

    Returns:
        複合アクションならTrue
    """
    request_lower = request.lower()

    # 否定キーワードがあれば単純リクエストの可能性
    for neg_kw in NEGATION_KEYWORDS:
        if neg_kw in request_lower:
            return False

    # 複合キーワードをチェック
    for conj_kw in CONJUNCTION_KEYWORDS:
        if conj_kw in request_lower:
            return True

    # 句点・読点で区切られた複数の動詞があるか
    verb_count = _count_action_verbs(request)
    if verb_count >= 2:
        return True

    return False


def _count_action_verbs(request: str) -> int:
    """
    アクション動詞の数をカウント

    Args:
        request: リクエスト

    Returns:
        動詞の数
    """
    action_verbs = [
        "して", "作って", "送って", "教えて", "確認して",
        "予約して", "完了して", "削除して", "更新して",
        "調べて", "まとめて", "報告して", "通知して",
    ]
    count = 0
    for verb in action_verbs:
        if verb in request:
            count += 1
    return count


# =============================================================================
# パラメータ抽出
# =============================================================================


class ParameterExtractor:
    """
    リクエストからパラメータを抽出

    日時、人名、タスク内容などを抽出する。
    """

    def extract(self, request: str, context: BrainContext) -> Dict[str, Any]:
        """
        パラメータを抽出

        Args:
            request: ユーザーリクエスト
            context: 脳コンテキスト

        Returns:
            抽出されたパラメータ
        """
        params = {}

        # 日時抽出
        datetime_value = self._extract_datetime(request)
        if datetime_value:
            params["datetime"] = datetime_value

        # 人名抽出
        person_names = self._extract_person_names(request, context)
        if person_names:
            params["assignee"] = person_names[0]
            params["participants"] = person_names

        # タスク内容抽出
        task_body = self._extract_task_body(request)
        if task_body:
            params["task_body"] = task_body

        # 検索クエリ抽出
        search_query = self._extract_search_query(request)
        if search_query:
            params["search_query"] = search_query

        return params

    def _extract_datetime(self, request: str) -> Optional[str]:
        """日時を抽出"""
        # 相対日時
        if "明日" in request:
            return "tomorrow"
        if "今日" in request:
            return "today"
        if "来週" in request:
            return "next_week"

        # 時刻パターン
        time_pattern = r"(\d{1,2})[:時](\d{0,2})"
        match = re.search(time_pattern, request)
        if match:
            hour = match.group(1)
            minute = match.group(2) or "00"
            return f"{hour}:{minute}"

        return None

    def _extract_person_names(
        self,
        request: str,
        context: BrainContext,
    ) -> List[str]:
        """人名を抽出"""
        names = []

        # コンテキストから既知の人物名とマッチ
        for person in context.person_info:
            if person.name in request:
                names.append(person.name)

        # 「〇〇さん」パターン
        san_pattern = r"([ぁ-んァ-ヶ一-龠a-zA-Z]+)さん"
        matches = re.findall(san_pattern, request)
        for match in matches:
            if match not in names:
                names.append(match)

        return names

    def _extract_task_body(self, request: str) -> Optional[str]:
        """タスク内容を抽出"""
        # 「〇〇を作って」「〇〇のタスク」パターン
        patterns = [
            r"「([^」]+)」(?:を|の|という)",
            r"タスク[「『]([^」』]+)[」』]",
            r"([^、。]+)(?:を作って|を作成)",
        ]

        for pattern in patterns:
            match = re.search(pattern, request)
            if match:
                return match.group(1).strip()

        return None

    def _extract_search_query(self, request: str) -> Optional[str]:
        """検索クエリを抽出"""
        # 「〇〇について」「〇〇を調べて」パターン
        patterns = [
            r"「([^」]+)」(?:について|を調べて|を検索)",
            r"([^、。]+)(?:について調べて|を教えて)",
        ]

        for pattern in patterns:
            match = re.search(pattern, request)
            if match:
                return match.group(1).strip()

        return None


# =============================================================================
# TaskDecomposer
# =============================================================================


class TaskDecomposer:
    """
    タスク分解器

    複雑なユーザーリクエストをサブタスクに分解する。

    分解ロジック:
    1. ルールベース: 定義済みパターンとのマッチング
    2. LLMベース: 複雑なケースでLLMを使用（オプション）
    """

    def __init__(
        self,
        capabilities: Dict[str, Dict],
        patterns: Optional[List[DecompositionPattern]] = None,
        llm_client: Optional[Any] = None,
        enable_llm_decomposition: bool = False,
    ):
        """
        タスク分解器を初期化

        Args:
            capabilities: 利用可能なアクション定義（SYSTEM_CAPABILITIES）
            patterns: 分解パターン（デフォルトは組み込みパターン）
            llm_client: LLMクライアント（オプション）
            enable_llm_decomposition: LLMベース分解を有効化
        """
        self.capabilities = capabilities
        self.patterns = patterns or ALL_DECOMPOSITION_PATTERNS
        self.llm_client = llm_client
        self.enable_llm_decomposition = enable_llm_decomposition

        self.param_extractor = ParameterExtractor()

        # パターンを優先度でソート
        self.patterns = sorted(self.patterns, key=lambda p: -p.priority)

        logger.debug(
            f"TaskDecomposer initialized: "
            f"patterns={len(self.patterns)}, "
            f"llm_enabled={enable_llm_decomposition}"
        )

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
            サブタスクのリスト（分解不要なら1件）
        """
        logger.info(f"Decomposing request: {request[:50]}...")

        # 1. 複合リクエストかチェック
        if not detect_multi_action_request(request):
            logger.debug("Single action request detected")
            return [self._create_single_task(request, context)]

        # 2. パラメータ抽出
        extracted_params = self.param_extractor.extract(request, context)
        logger.debug(f"Extracted params: {list(extracted_params.keys())}")

        # 3. ルールベース分解を試行
        subtasks = self._rule_based_decompose(request, extracted_params)

        if subtasks:
            logger.info(f"Rule-based decomposition: {len(subtasks)} subtasks")
            return subtasks

        # 4. LLMベース分解（有効な場合）
        if self.enable_llm_decomposition and self.llm_client:
            subtasks = await self._llm_based_decompose(request, context, extracted_params)
            if subtasks:
                logger.info(f"LLM-based decomposition: {len(subtasks)} subtasks")
                return subtasks

        # 5. 分解できない場合は単一タスクとして返す
        logger.debug("Could not decompose, returning single task")
        return [self._create_single_task(request, context)]

    def _rule_based_decompose(
        self,
        request: str,
        extracted_params: Dict[str, Any],
    ) -> Optional[List[SubTask]]:
        """
        ルールベースの分解

        Args:
            request: ユーザーリクエスト
            extracted_params: 抽出済みパラメータ

        Returns:
            サブタスクリスト、マッチしなければNone
        """
        for pattern in self.patterns:
            if pattern.matches(request):
                logger.debug(f"Matched pattern: {pattern.name}")
                return pattern.decompose(request, extracted_params)

        return None

    async def _llm_based_decompose(
        self,
        request: str,
        context: BrainContext,
        extracted_params: Dict[str, Any],
    ) -> Optional[List[SubTask]]:
        """
        LLMベースの分解

        Args:
            request: ユーザーリクエスト
            context: 脳コンテキスト
            extracted_params: 抽出済みパラメータ

        Returns:
            サブタスクリスト、失敗時はNone
        """
        try:
            # 利用可能なアクション一覧を作成
            available_actions = [
                f"- {name}: {cap.get('description', '')}"
                for name, cap in self.capabilities.items()
                if cap.get('brain_metadata', {}).get('is_primary', True)
            ]

            prompt = f"""以下のユーザーリクエストを、実行可能なサブタスクに分解してください。

リクエスト: {request}

利用可能なアクション:
{chr(10).join(available_actions[:20])}

抽出済みパラメータ:
{extracted_params}

JSON形式で回答してください:
{{
  "subtasks": [
    {{"name": "タスク名", "action": "アクション名", "params": {{}}, "depends_on": []}}
  ]
}}
"""

            response = await self.llm_client.generate(prompt)
            return self._parse_llm_response(response)

        except Exception as e:
            logger.warning(f"LLM decomposition failed: {e}")
            return None

    def _parse_llm_response(self, response: str) -> Optional[List[SubTask]]:
        """LLMレスポンスをパース"""
        import json

        try:
            # JSON部分を抽出
            json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if not json_match:
                return None

            data = json.loads(json_match.group())
            subtasks = []

            for st_data in data.get("subtasks", []):
                subtask = create_subtask(
                    name=st_data.get("name", "タスク"),
                    action=st_data.get("action", "general_response"),
                    params=st_data.get("params", {}),
                    depends_on=st_data.get("depends_on", []),
                )
                subtasks.append(subtask)

            return subtasks if subtasks else None

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return None

    def _create_single_task(
        self,
        request: str,
        context: BrainContext,
    ) -> SubTask:
        """
        単一タスクを作成

        分解不要な場合に使用。
        """
        return SubTask(
            id=str(uuid.uuid4()),
            name="リクエスト処理",
            description=f"「{request[:50]}...」を処理",
            action="general_response",
            params={"original_request": request},
        )

    def should_decompose(self, request: str) -> bool:
        """
        分解すべきリクエストか判定

        Args:
            request: ユーザーリクエスト

        Returns:
            分解すべきならTrue
        """
        return detect_multi_action_request(request)

    def add_pattern(self, pattern: DecompositionPattern) -> None:
        """
        分解パターンを追加

        Args:
            pattern: 追加するパターン
        """
        self.patterns.append(pattern)
        self.patterns = sorted(self.patterns, key=lambda p: -p.priority)
        logger.debug(f"Pattern added: {pattern.name}")


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_task_decomposer(
    capabilities: Dict[str, Dict],
    llm_client: Optional[Any] = None,
    enable_llm_decomposition: bool = False,
) -> TaskDecomposer:
    """
    TaskDecomposerを作成

    Args:
        capabilities: 利用可能なアクション定義
        llm_client: LLMクライアント
        enable_llm_decomposition: LLMベース分解を有効化

    Returns:
        TaskDecomposer
    """
    return TaskDecomposer(
        capabilities=capabilities,
        llm_client=llm_client,
        enable_llm_decomposition=enable_llm_decomposition,
    )
