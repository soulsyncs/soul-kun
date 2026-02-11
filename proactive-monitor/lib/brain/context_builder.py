# lib/brain/context_builder.py
"""
LLM Brainに渡すコンテキストを構築する

設計書: docs/25_llm_native_brain_architecture.md セクション5.1（6.1）

【目的】
LLM Brainに渡す「文脈情報」を構築する。
全ての記憶・状態・設計思想をここで集約し、LLMが適切な判断を行えるようにする。

【収集する情報（優先順）】
1. 現在の状態（セッション状態、pending操作）
2. 会話履歴（直近10件）
3. ユーザー情報・嗜好
4. 記憶（人物情報、タスク、目標）
5. 価値観（CEO教え、会社のMVV）
6. ナレッジ（必要時に遅延取得）

【Truth順位（CLAUDE.md セクション3）】
1位: リアルタイムAPI
2位: DB（正規データ）
3位: 設計書・仕様書
4位: Memory（会話の文脈）
5位: 推測 → 禁止

Author: Claude Opus 4.5
Created: 2026-01-30
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

# SoT: lib/brain/models.py から統一版をimport
from lib.brain.models import PersonInfo, TaskInfo, GoalInfo

logger = logging.getLogger(__name__)

# 日本時間
JST = ZoneInfo("Asia/Tokyo")


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class Message:
    """会話メッセージ"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: Optional[datetime] = None
    sender: Optional[str] = None  # sender name for display

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "sender": self.sender,
        }


@dataclass
class UserPreferences:
    """ユーザー嗜好"""
    preferred_name: Optional[str] = None  # 呼ばれたい名前
    report_format: Optional[str] = None   # 報告形式の好み
    notification_time: Optional[str] = None  # 通知希望時間
    other_preferences: Dict[str, Any] = field(default_factory=dict)

    def to_string(self) -> str:
        parts = []
        if self.preferred_name:
            parts.append(f"呼び名: {self.preferred_name}")
        if self.report_format:
            parts.append(f"報告形式: {self.report_format}")
        if self.notification_time:
            parts.append(f"通知時間: {self.notification_time}")
        for key, value in self.other_preferences.items():
            parts.append(f"{key}: {value}")
        return ", ".join(parts) if parts else "なし"


# PersonInfo, TaskInfo, GoalInfo は lib/brain/models.py からimport済み
# 重複定義を避けるため、ここでは定義しない（SoT: models.py）


@dataclass
class CEOTeaching:
    """CEO教え"""
    content: str
    category: Optional[str] = None
    priority: int = 0
    created_at: Optional[datetime] = None

    def to_string(self) -> str:
        if self.category:
            return f"[{self.category}] {self.content}"
        return self.content


@dataclass
class KnowledgeChunk:
    """ナレッジの断片"""
    content: str
    source: str
    relevance_score: float = 0.0


@dataclass
class SessionState:
    """セッション状態（LLM Brain用の簡易版）"""
    mode: str = "normal"  # normal, confirmation_pending, multi_step_flow
    pending_action: Optional[Dict[str, Any]] = None
    last_intent: Optional[str] = None
    last_tool_called: Optional[str] = None

    def to_string(self) -> str:
        lines = [f"モード: {self.mode}"]
        if self.pending_action:
            lines.append(f"確認待ち: {self.pending_action.get('tool_name', '不明')}")
        if self.last_intent:
            lines.append(f"直前の意図: {self.last_intent}")
        return "\n".join(lines)


@dataclass
class LLMContext:
    """
    LLM Brainに渡すコンテキスト

    設計書: docs/25_llm_native_brain_architecture.md セクション5.1.3
    """

    # === 現在の状態 ===
    session_state: Optional[SessionState] = None
    pending_action: Optional[Dict[str, Any]] = None

    # === ユーザー情報 ===
    user_id: str = ""
    user_name: str = ""
    user_role: str = ""
    user_preferences: Optional[UserPreferences] = None

    # === 会話履歴 ===
    recent_messages: List[Message] = field(default_factory=list)
    conversation_summary: Optional[str] = None

    # === 記憶 ===
    known_persons: List[PersonInfo] = field(default_factory=list)
    recent_tasks: List[TaskInfo] = field(default_factory=list)
    active_goals: List[GoalInfo] = field(default_factory=list)

    # === 価値観 ===
    ceo_teachings: List[CEOTeaching] = field(default_factory=list)
    company_values: str = ""

    # === ナレッジ（遅延取得可） ===
    relevant_knowledge: Optional[List[KnowledgeChunk]] = None

    # === Phase 2E: 学習済み知識 ===
    phase2e_learnings: str = ""

    # === Phase 2F: 行動パターン ===
    outcome_patterns: str = ""

    # === Task 7: 感情コンテキスト ===
    emotion_context: str = ""

    # === メタ情報 ===
    current_datetime: datetime = field(default_factory=lambda: datetime.now(JST))
    organization_id: str = ""
    room_id: str = ""

    def to_prompt_string(self) -> str:
        """
        LLMプロンプト用の文字列に変換

        Returns:
            LLMに渡す形式のコンテキスト文字列
        """
        sections = []

        # 現在の状態
        if self.session_state:
            sections.append(f"【現在のセッション】\n{self.session_state.to_string()}")
        if self.pending_action:
            tool_name = self.pending_action.get("tool_name", "不明")
            question = self.pending_action.get("confirmation_question", "")
            sections.append(f"【確認待ち操作】\nTool: {tool_name}\n確認質問: {question}")

        # ユーザー情報
        user_info_lines = [
            f"- 名前: {self.user_name}",
            f"- 役職: {self.user_role}" if self.user_role else None,
            f"- 嗜好: {self.user_preferences.to_string()}" if self.user_preferences else None,
        ]
        user_info = "\n".join([line for line in user_info_lines if line])
        sections.append(f"【ユーザー情報】\n{user_info}")

        # 会話履歴（直近3件 — v10.77.0: 5→3件に圧縮、コスト削減Phase 1-2）
        if self.recent_messages:
            history_lines = []
            for m in self.recent_messages[-3:]:
                sender = m.sender or ("ソウルくん" if m.role == "assistant" else "ユーザー")
                history_lines.append(f"- {sender}: {m.content[:80]}{'...' if len(m.content) > 80 else ''}")
            sections.append(f"【直近の会話】\n" + "\n".join(history_lines))

        # 記憶している人物（v10.77.0: 5→3人に圧縮）
        if self.known_persons:
            persons = "\n".join([f"- {p.to_string()}" for p in self.known_persons[:3]])
            sections.append(f"【記憶している人物】\n{persons}")

        # 関連タスク（v10.77.0: 5→3件に圧縮）
        if self.recent_tasks:
            tasks = "\n".join([f"- {t.to_string()}" for t in self.recent_tasks[:3]])
            sections.append(f"【関連タスク】\n{tasks}")

        # アクティブな目標
        if self.active_goals:
            goals = "\n".join([f"- {g.to_string()}" for g in self.active_goals[:3]])
            sections.append(f"【アクティブな目標】\n{goals}")

        # CEO教え
        if self.ceo_teachings:
            teachings = "\n".join([f"- {t.to_string()}" for t in self.ceo_teachings[:3]])
            sections.append(f"【CEO教え（最優先で従う）】\n{teachings}")

        # ナレッジ
        if self.relevant_knowledge:
            knowledge = "\n".join([f"- {k.content[:100]}..." for k in self.relevant_knowledge[:3]])
            sections.append(f"【関連ナレッジ】\n{knowledge}")

        # Phase 2E: 学習済み知識
        if self.phase2e_learnings:
            sections.append(self.phase2e_learnings)

        # Phase 2F: 行動パターン
        if self.outcome_patterns:
            sections.append(self.outcome_patterns)

        # Task 7: 感情コンテキスト
        if self.emotion_context:
            sections.append(self.emotion_context)

        # 現在日時
        sections.append(f"【現在日時】\n{self.current_datetime.strftime('%Y年%m月%d日 %H:%M')}")

        return "\n\n".join(sections)


# =============================================================================
# ContextBuilder クラス
# =============================================================================

class ContextBuilder:
    """
    LLM Brainに渡すコンテキストを構築する

    設計書: docs/25_llm_native_brain_architecture.md セクション5.1

    【使用例】
    builder = ContextBuilder(pool, memory_access, state_manager, ceo_repo)
    context = await builder.build(user_id, room_id, organization_id, message)
    """

    def __init__(
        self,
        pool,
        memory_access=None,
        state_manager=None,
        ceo_teaching_repository=None,
        phase2e_learning=None,
        outcome_learning=None,
        emotion_reader=None,
    ):
        """
        Args:
            pool: データベース接続プール
            memory_access: BrainMemoryAccessインスタンス（Noneの場合は内部で生成）
            state_manager: BrainStateManagerインスタンス
            ceo_teaching_repository: CEOTeachingRepositoryインスタンス
            phase2e_learning: Phase2ELearningインスタンス（学習基盤）
            outcome_learning: Phase 2F OutcomeLearningインスタンス
            emotion_reader: EmotionReaderインスタンス（Task 7: 感情分析）
        """
        self.pool = pool
        self.memory_access = memory_access
        self.state_manager = state_manager
        self.ceo_teaching_repository = ceo_teaching_repository
        self.phase2e_learning = phase2e_learning
        self.outcome_learning = outcome_learning
        self.emotion_reader = emotion_reader

    async def build(
        self,
        user_id: str,
        room_id: str,
        organization_id: str,
        message: str,
        sender_name: Optional[str] = None,
        phase2e_learnings_prefetched: Optional[str] = None,
    ) -> LLMContext:
        """
        コンテキストを構築する

        v10.78.0: 根本原因修正 — 全DBクエリを1コネクションに統合
        Before: 9つの pool.connect() → pool枯渇 → pool.connect()ハング → 全タイムアウト
        After: 1つの pool.connect() → 8クエリ直列実行 → pool枯渇なし
        証拠: state_manager（単発pool.connect()）は0.056sで完了。複数スレッドからの
        同時pool.connect()がdb-f1-microでハングする。

        Truth順位（CLAUDE.md セクション3）に従ってデータを取得。
        1位: リアルタイムAPI
        2位: DB（正規データ）
        3位: 設計書・仕様書
        4位: Memory（会話の文脈）
        5位: 推測 → 禁止
        """
        import time as _time
        _build_t0 = _time.monotonic()
        logger.debug("Building LLM context")
        print(f"[DIAG] context_builder.build() START (single-conn mode)")

        async def _safe(coro, name: str, default=None, timeout: float = 15.0):
            """タスクをタイムアウト付きで安全に実行"""
            try:
                return await asyncio.wait_for(coro, timeout=timeout)
            except asyncio.TimeoutError:
                print(f"[DIAG] {name} timed out after {timeout}s")
                logger.warning(f"{name} timed out after {timeout}s")
                return default
            except Exception as e:
                print(f"[DIAG] {name} failed: {type(e).__name__}")
                logger.warning(f"{name} failed: {type(e).__name__}")
                return default

        # 5タスクを並行実行:
        # - 3つの非DBタスク（Firestore/LLM API）
        # - 1つのDB統合タスク（8クエリを1コネクションで直列実行）
        # - 1つのCEO教え（独自リポジトリ経由、別コネクション）
        results = await asyncio.gather(
            _safe(self._get_session_state(user_id, room_id), "session_state"),
            _safe(self._get_recent_messages(user_id, room_id, organization_id), "messages", default=[]),
            _safe(self._get_emotion_context(message, organization_id, user_id), "emotion", default=""),
            _safe(self._fetch_all_db_data(
                user_id, room_id, organization_id, message,
                sender_name, phase2e_learnings_prefetched,
            ), "db_data", default={}, timeout=20.0),  # v10.79: 15→20 (DB_POOL_TIMEOUT=15の結果をキャッチするため、3AI合議)
            _safe(self._get_ceo_teachings(organization_id, message), "ceo_teachings", default=[], timeout=5.0),
            return_exceptions=True,
        )

        _build_elapsed = _time.monotonic() - _build_t0
        print(f"[DIAG] context_builder.build() ALL tasks done in {_build_elapsed:.3f}s")

        # 結果を展開（例外はデフォルト値に置換）
        def _unpack(val, default=None):
            return default if isinstance(val, Exception) or val is None else val

        session_state = _unpack(results[0])
        recent_messages = _unpack(results[1], [])
        emotion_context = _unpack(results[2], "")
        db_data = _unpack(results[3], {})
        ceo_teachings = _unpack(results[4], [])

        # DB統合結果を展開
        conversation_summary = db_data.get("summary")
        user_preferences = db_data.get("preferences")
        known_persons = db_data.get("persons", [])
        recent_tasks = db_data.get("tasks", [])
        active_goals = db_data.get("goals", [])
        user_info = db_data.get("user_info") or {"name": sender_name or "ユーザー", "role": ""}
        phase2e_learnings = db_data.get("phase2e", "")
        outcome_patterns = db_data.get("outcome_patterns", "")

        return LLMContext(
            session_state=session_state,
            pending_action=session_state.pending_action if session_state else None,
            user_id=user_id,
            user_name=user_info.get("name", sender_name or "ユーザー"),
            user_role=user_info.get("role", ""),
            user_preferences=user_preferences,
            recent_messages=recent_messages,
            conversation_summary=conversation_summary,
            known_persons=known_persons,
            recent_tasks=recent_tasks,
            active_goals=active_goals,
            ceo_teachings=ceo_teachings,
            company_values=self._get_company_values(),
            relevant_knowledge=None,  # 必要時に遅延取得
            phase2e_learnings=phase2e_learnings,
            outcome_patterns=outcome_patterns,
            emotion_context=emotion_context,
            current_datetime=datetime.now(JST),
            organization_id=organization_id,
            room_id=room_id,
        )

    def _handle_results(self, results: List[Any]) -> tuple:
        """結果を処理し、エラーをログする"""
        field_names = [
            "session_state",
            "recent_messages",
            "conversation_summary",
            "user_preferences",
            "known_persons",
            "recent_tasks",
            "active_goals",
            "ceo_teachings",
            "user_info",
            "phase2e_learnings",
            "outcome_patterns",
            "emotion_context",
        ]
        defaults: List[Any] = [
            None,  # session_state
            [],    # recent_messages
            None,  # conversation_summary
            None,  # user_preferences
            [],    # known_persons
            [],    # recent_tasks
            [],    # active_goals
            [],    # ceo_teachings
            {},    # user_info
            "",    # phase2e_learnings
            "",    # outcome_patterns
            "",    # emotion_context
        ]

        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("Error fetching %s: %s", field_names[i], type(result).__name__)
                processed.append(defaults[i])
            elif result is None and defaults[i] is not None:
                # タイムアウト時に_db_limitedがNoneを返す場合、
                # デフォルト値がNone以外のフィールド（[], {}, ""等）は
                # Noneのままだと後続でAttributeError/TypeErrorになる
                logger.debug("Field %s is None, using default", field_names[i])
                processed.append(defaults[i])
            else:
                processed.append(result)

        return tuple(processed)

    async def _fetch_all_db_data(
        self,
        user_id: str,
        room_id: str,
        organization_id: str,
        message: str,
        sender_name: Optional[str] = None,
        phase2e_learnings_prefetched: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        根本原因修正: 全DBクエリを1コネクション・1スレッドで実行

        v10.78.0: pool.connect()ハングの根本原因修正
        Before: 9つのasyncio.to_thread()が各自pool.connect()
          → db-f1-microでpool枯渇 → pool.connect()がpool_timeout(30s)まで待機
        After: 1つのasyncio.to_thread()で1つのpool.connect()
          → 8クエリを直列実行 → pool枯渇なし

        証拠:
        - state_manager（単発pool.connect()）は0.056sで完了
        - memory_access（9並列pool.connect()）は全て15秒タイムアウト
        - 3者合議（Claude+Codex+Gemini）でpool枯渇が原因と一致

        Returns:
            Dict with keys: summary, preferences, persons, tasks, goals,
            user_info, phase2e, outcome_patterns
        """
        from sqlalchemy import text as sa_text
        import time as _time

        org_is_uuid = False
        try:
            import uuid
            uuid.UUID(organization_id)
            org_is_uuid = True
        except (ValueError, AttributeError):
            pass

        pool = self.pool
        memory = self.memory_access
        phase2e_learning = self.phase2e_learning
        outcome_learning = self.outcome_learning
        org_id = organization_id
        prefetched = phase2e_learnings_prefetched

        t_before_thread = None  # asyncio.to_thread待ち計測用

        def _sync_all_queries():
            """1コネクションで全DBクエリを直列実行（スレッド内で実行）"""
            t0 = _time.monotonic()
            # [DIAG] スレッドキュー待ち時間（Codex指摘: to_threadのキュー詰まり検出）
            if t_before_thread is not None:
                print(f"[DIAG] thread queue wait: {t0 - t_before_thread:.3f}s")
            data: Dict[str, Any] = {
                "summary": None,
                "preferences": None,
                "persons": [],
                "tasks": [],
                "goals": [],
                "user_info": {"name": sender_name or "ユーザー", "role": ""},
                "phase2e": prefetched or "",
                "outcome_patterns": "",
            }

            try:
                # [DIAG] pool状態可視化（Codex+Gemini共通指摘: pool枯渇の検出）
                try:
                    _pool = pool.pool
                    _ps = _pool.status() if hasattr(_pool, 'status') else 'N/A'
                    _co = _pool.checkedout() if hasattr(_pool, 'checkedout') else 'N/A'
                    _sz = _pool.size() if hasattr(_pool, 'size') else 'N/A'
                    _ov = _pool.overflow() if hasattr(_pool, 'overflow') else 'N/A'
                    print(f"[DIAG] pool before connect: status={_ps}, checkedout={_co}, size={_sz}, overflow={_ov}")
                except Exception:
                    print("[DIAG] pool status unavailable")

                with pool.connect() as conn:
                    # state_managerと同じパターン: rollback()で接続状態をクリーン化
                    conn.rollback()
                    # DB側タイムアウト: 個別クエリが5秒以上かかったらキャンセル
                    conn.execute(sa_text(
                        "SELECT set_config('statement_timeout', '5000', true)"
                    ))
                    t_conn = _time.monotonic()
                    print(f"[DIAG] _fetch_all_db_data: conn ready in {t_conn - t0:.3f}s")
                    t_q = _time.monotonic()  # クエリ個別タイミング

                    # --- 1. 会話要約 (conversation_summaries) ---
                    if org_is_uuid and memory:
                        try:
                            row = conn.execute(sa_text("""
                                SELECT cs.id, cs.summary_text, cs.key_topics,
                                       cs.mentioned_persons, cs.mentioned_tasks,
                                       cs.message_count, cs.created_at
                                FROM conversation_summaries cs
                                JOIN users u ON cs.user_id = u.id
                                WHERE u.chatwork_account_id = :user_id
                                  AND cs.organization_id = CAST(:org_id AS uuid)
                                ORDER BY cs.created_at DESC LIMIT 1
                            """), {"user_id": user_id, "org_id": org_id}).fetchone()
                            if row and row[1]:
                                data["summary"] = str(row[1])
                        except Exception as e:
                            print(f"[DIAG] summary query failed: {type(e).__name__}")
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                    print(f"[DIAG] query_1_summary: {_time.monotonic() - t_q:.3f}s"); t_q = _time.monotonic()

                    # --- 2. ユーザー嗜好 (user_preferences) ---
                    if org_is_uuid and memory:
                        try:
                            rows = conn.execute(sa_text("""
                                SELECT up.preference_type, up.preference_key,
                                       up.preference_value, up.confidence
                                FROM user_preferences up
                                JOIN users u ON up.user_id = u.id
                                WHERE u.chatwork_account_id = :user_id
                                  AND up.organization_id = CAST(:org_id AS uuid)
                                ORDER BY up.confidence DESC LIMIT 20
                            """), {"user_id": user_id, "org_id": org_id}).fetchall()
                            if rows:
                                prefs = UserPreferences()
                                for r in rows:
                                    key = r[1] or ""
                                    value = r[2]
                                    if key == "preferred_name":
                                        prefs.preferred_name = value
                                    elif key == "report_format":
                                        prefs.report_format = value
                                    elif key == "notification_time":
                                        prefs.notification_time = value
                                    else:
                                        prefs.other_preferences[key] = value
                                data["preferences"] = prefs
                        except Exception as e:
                            print(f"[DIAG] preferences query failed: {type(e).__name__}")
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                    print(f"[DIAG] query_2_prefs: {_time.monotonic() - t_q:.3f}s"); t_q = _time.monotonic()

                    # --- 3. 人物情報 (persons + person_attributes) ---
                    if memory:
                        try:
                            from collections import OrderedDict
                            rows = conn.execute(sa_text("""
                                SELECT p.id, p.name,
                                       pa.attribute_type, pa.attribute_value
                                FROM persons p
                                LEFT JOIN person_attributes pa
                                  ON pa.person_id = p.id
                                  AND pa.organization_id = p.organization_id
                                WHERE p.organization_id = :org_id
                                ORDER BY p.name, pa.updated_at DESC
                            """), {"org_id": org_id}).fetchall()
                            person_map: OrderedDict = OrderedDict()
                            for row in rows:
                                pid = row[0]
                                if pid not in person_map:
                                    if len(person_map) >= 50:
                                        break
                                    person_map[pid] = {"name": row[1], "attrs": {}}
                                if row[2]:
                                    person_map[pid]["attrs"][row[2]] = row[3]
                            data["persons"] = [
                                PersonInfo(
                                    person_id=str(pid) if pid else "",
                                    name=info["name"],
                                    attributes=info["attrs"],
                                )
                                for pid, info in person_map.items()
                            ]
                        except Exception as e:
                            print(f"[DIAG] persons query failed: {type(e).__name__}")
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                    print(f"[DIAG] query_3_persons: {_time.monotonic() - t_q:.3f}s"); t_q = _time.monotonic()

                    # --- 4. タスク情報 (chatwork_tasks) ---
                    if memory:
                        try:
                            import time as time_mod
                            now_ts = int(time_mod.time())
                            rows = conn.execute(sa_text("""
                                SELECT task_id, body, summary, status, limit_time,
                                       room_id, room_name, assigned_to_name, assigned_by_name
                                FROM chatwork_tasks
                                WHERE assigned_to_account_id = :user_id
                                  AND status = 'open'
                                  AND organization_id = :org_id
                                ORDER BY
                                    CASE WHEN limit_time IS NOT NULL
                                              AND to_timestamp(limit_time) < NOW()
                                         THEN 0 ELSE 1 END,
                                    limit_time ASC NULLS LAST
                                LIMIT :lim
                            """), {"user_id": user_id, "org_id": org_id, "lim": 10}).fetchall()

                            def _parse_lt(lt):
                                if lt is None:
                                    return None
                                if isinstance(lt, datetime):
                                    return lt
                                if isinstance(lt, (int, float)):
                                    return datetime.fromtimestamp(lt)
                                return None

                            def _is_overdue(lt):
                                if lt is None:
                                    return False
                                if isinstance(lt, datetime):
                                    return lt < datetime.now()
                                if isinstance(lt, (int, float)):
                                    return lt < now_ts
                                return False

                            data["tasks"] = [
                                TaskInfo(
                                    task_id=str(r[0]) if r[0] else "",
                                    body=r[1] or "",
                                    summary=r[2],
                                    status=r[3] or "open",
                                    due_date=_parse_lt(r[4]),
                                    room_id=str(r[5]) if r[5] else None,
                                    room_name=r[6],
                                    assignee_name=r[7],
                                    assigned_by_name=r[8],
                                    is_overdue=_is_overdue(r[4]),
                                )
                                for r in rows
                            ]
                        except Exception as e:
                            print(f"[DIAG] tasks query failed: {type(e).__name__}")
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                    print(f"[DIAG] query_4_tasks: {_time.monotonic() - t_q:.3f}s"); t_q = _time.monotonic()

                    # --- 5. 目標情報 (goals) ---
                    if org_is_uuid and memory:
                        try:
                            rows = conn.execute(sa_text("""
                                SELECT g.id, g.title, g.description,
                                       g.target_value, g.current_value,
                                       g.status, g.deadline
                                FROM goals g
                                JOIN users u ON g.user_id = u.id
                                WHERE u.chatwork_account_id = :user_id
                                  AND g.organization_id = CAST(:org_id AS uuid)
                                  AND g.status = 'active'
                                ORDER BY g.created_at DESC LIMIT 5
                            """), {"user_id": user_id, "org_id": org_id}).fetchall()
                            data["goals"] = [
                                GoalInfo(
                                    goal_id=str(r[0]) if r[0] else "",
                                    title=r[1] or "",
                                    why=None,
                                    what=r[2],
                                    how=None,
                                    status=r[5] or "active",
                                    progress=(
                                        float(r[4] / r[3] * 100)
                                        if r[3] and r[4] else 0.0
                                    ),
                                    deadline=r[6],
                                )
                                for r in rows
                            ]
                        except Exception as e:
                            print(f"[DIAG] goals query failed: {type(e).__name__}")
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                    print(f"[DIAG] query_5_goals: {_time.monotonic() - t_q:.3f}s"); t_q = _time.monotonic()

                    # --- 6. ユーザー基本情報 (users) ---
                    try:
                        row = conn.execute(sa_text("""
                            SELECT u.name, r.name AS role_name
                            FROM users u
                            LEFT JOIN user_departments ud ON ud.user_id = u.id
                            LEFT JOIN roles r ON ud.role_id = r.id
                            WHERE u.chatwork_account_id = :account_id
                            AND u.organization_id = :org_id
                            LIMIT 1
                        """), {"account_id": user_id, "org_id": org_id}).fetchone()
                        if row:
                            data["user_info"] = {
                                "name": row[0] or sender_name or "ユーザー",
                                "role": row[1] or "",
                            }
                    except Exception as e:
                        print(f"[DIAG] user_info query failed: {type(e).__name__}")
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                    print(f"[DIAG] query_6_userinfo: {_time.monotonic() - t_q:.3f}s"); t_q = _time.monotonic()

                    # --- 7. Phase 2E 学習済み知識 ---
                    if prefetched is None and phase2e_learning:
                        try:
                            applicable = phase2e_learning.find_applicable(
                                conn, message, None, user_id, room_id
                            )
                            if applicable:
                                ctx_adds = phase2e_learning.build_context_additions(
                                    applicable
                                )
                                data["phase2e"] = (
                                    phase2e_learning.build_prompt_instructions(ctx_adds)
                                )
                        except Exception as e:
                            print(f"[DIAG] phase2e query failed: {type(e).__name__}")
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                    print(f"[DIAG] query_7_phase2e: {_time.monotonic() - t_q:.3f}s"); t_q = _time.monotonic()

                    # --- 8. Phase 2F 行動パターン ---
                    if outcome_learning:
                        try:
                            patterns = outcome_learning.find_applicable_patterns(
                                conn=conn, target_account_id=user_id,
                            )
                            if patterns:
                                lines = []
                                for p in patterns[:3]:
                                    content = p.pattern_content or {}
                                    desc = content.get("description", p.pattern_type)
                                    score = p.confidence_score or 0.0
                                    lines.append(f"- {desc} (信頼度: {score:.0%})")
                                data["outcome_patterns"] = (
                                    "【行動パターン（Phase 2F）】\n"
                                    + "\n".join(lines)
                                )
                        except Exception as e:
                            print(f"[DIAG] outcome query failed: {type(e).__name__}")
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                    print(f"[DIAG] query_8_outcome: {_time.monotonic() - t_q:.3f}s")

                    t_done = _time.monotonic()
                    print(
                        f"[DIAG] _fetch_all_db_data: all 8 queries done "
                        f"in {t_done - t0:.3f}s"
                    )

            except Exception as e:
                print(f"[DIAG] _fetch_all_db_data: conn failed: {type(e).__name__}")
                logger.warning(
                    "DB connection failed in _fetch_all_db_data: %s",
                    type(e).__name__,
                )

            return data

        t_before_thread = _time.monotonic()
        return await asyncio.to_thread(_sync_all_queries)

    async def _get_session_state(
        self,
        user_id: str,
        room_id: str,
    ) -> Optional[SessionState]:
        """セッション状態を取得"""
        if not self.state_manager:
            logger.debug("[状態取得] state_manager is None, skipping")
            return None

        try:
            # v10.56.6: 診断ログ追加（debugレベル、PII非露出）
            logger.debug("[状態取得開始]")
            state = await self.state_manager.get_current_state(room_id, user_id)
            if not state:
                logger.debug("[状態取得] 状態なし")
                return None

            # v10.56.6: 取得成功ログ
            state_type = state.state_type.value if hasattr(state, 'state_type') else "normal"
            state_step = state.state_step if hasattr(state, 'state_step') else None
            logger.debug(f"[状態取得成功] type={state_type}, step={state_step}")

            return SessionState(
                mode=state_type,
                pending_action=state.state_data if hasattr(state, 'state_data') else None,
                last_intent=state_step,
            )
        except Exception as e:
            logger.warning(f"[状態取得エラー] error={type(e).__name__}")
            return None

    async def _get_recent_messages(
        self,
        user_id: str,
        room_id: str,
        organization_id: str,
    ) -> List[Message]:
        """直近の会話履歴を取得"""
        if not self.memory_access:
            return []

        try:
            messages = await self.memory_access.get_recent_conversation(room_id, user_id)
            return [
                Message(
                    role=msg.role,
                    content=msg.content,
                    timestamp=msg.timestamp,
                    sender=None,
                )
                for msg in messages
            ]
        except Exception as e:
            logger.warning(f"Error getting recent messages: {type(e).__name__}")
            return []

    async def _get_conversation_summary(
        self,
        user_id: str,
        organization_id: str,
    ) -> Optional[str]:
        """会話の要約を取得"""
        if not self.memory_access:
            return None

        try:
            summary = await self.memory_access.get_conversation_summary(user_id)
            if summary and hasattr(summary, 'summary_text'):
                text = summary.summary_text
                return str(text) if text is not None else None
            return None
        except Exception as e:
            logger.warning(f"Error getting conversation summary: {type(e).__name__}")
            return None

    async def _get_user_preferences(
        self,
        user_id: str,
        organization_id: str,
    ) -> Optional[UserPreferences]:
        """ユーザー嗜好を取得"""
        if not self.memory_access:
            return None

        try:
            prefs = await self.memory_access.get_user_preferences(user_id)
            if not prefs:
                return None

            # 嗜好をUserPreferencesに変換
            result = UserPreferences()
            for pref in prefs:
                if hasattr(pref, 'preference_key') and hasattr(pref, 'preference_value'):
                    key = pref.preference_key
                    value = pref.preference_value
                    if key == "preferred_name":
                        result.preferred_name = value
                    elif key == "report_format":
                        result.report_format = value
                    elif key == "notification_time":
                        result.notification_time = value
                    else:
                        result.other_preferences[key] = value
            return result
        except Exception as e:
            logger.warning(f"Error getting user preferences: {type(e).__name__}")
            return None

    async def _get_known_persons(
        self,
        organization_id: str,
    ) -> List[PersonInfo]:
        """記憶している人物情報を取得"""
        if not self.memory_access:
            return []

        try:
            persons = await self.memory_access.get_person_info()
            return [
                PersonInfo(
                    person_id=p.person_id if hasattr(p, 'person_id') else "",  # 修正: person_id追加
                    name=p.name,
                    description=str(p.attributes) if p.attributes else "",
                    attributes=p.attributes if p.attributes else {},
                )
                for p in persons[:10]  # 最大10人
            ]
        except Exception as e:
            logger.warning(f"Error getting known persons: {type(e).__name__}")
            return []

    async def _get_recent_tasks(
        self,
        user_id: str,
        room_id: str,
        organization_id: str,
    ) -> List[TaskInfo]:
        """関連タスクを取得"""
        if not self.memory_access:
            return []

        try:
            tasks = await self.memory_access.get_recent_tasks(user_id)
            return [
                TaskInfo(
                    task_id=str(t.task_id),
                    title=t.summary or t.body[:50],
                    due_date=t.due_date,  # 修正: limit_time → due_date（統一版フィールド名）
                    status=t.status,
                    assignee_name=t.assignee_name,  # 修正: assigned_to → assignee_name
                    assigned_by_name=t.assigned_by_name,  # 修正: assigned_by → assigned_by_name
                    is_overdue=t.is_overdue,
                )
                for t in tasks[:10]  # 最大10件
            ]
        except Exception as e:
            logger.warning(f"Error getting recent tasks: {type(e).__name__}")
            return []

    async def _get_active_goals(
        self,
        user_id: str,
        organization_id: str,
    ) -> List[GoalInfo]:
        """アクティブな目標を取得"""
        if not self.memory_access:
            return []

        try:
            goals = await self.memory_access.get_active_goals(user_id)
            result = []
            for g in goals[:5]:  # 最大5件
                # memory_access.GoalInfoオブジェクトから属性を直接取得
                goal_info = GoalInfo(
                    goal_id=str(g.goal_id) if g.goal_id else "",  # 修正: g.id → g.goal_id（統一版フィールド名）
                    title=g.title or "",
                    progress=float(g.progress) if g.progress else 0.0,
                    status=g.status or "active",
                )
                result.append(goal_info)
            return result
        except Exception as e:
            logger.warning(f"Error getting active goals: {type(e).__name__}")
            return []

    async def _get_ceo_teachings(
        self,
        organization_id: str,
        message: str,
    ) -> List[CEOTeaching]:
        """CEO教えを取得"""
        if not self.ceo_teaching_repository:
            return []

        try:
            # 関連するCEO教えを検索
            teachings = await self.ceo_teaching_repository.search_relevant(
                query=message,
                organization_id=organization_id,
                limit=5,
            )
            return [
                CEOTeaching(
                    content=t.content if hasattr(t, 'content') else str(t),
                    category=t.category if hasattr(t, 'category') else None,
                    priority=t.priority if hasattr(t, 'priority') else 0,
                )
                for t in teachings
            ]
        except Exception as e:
            logger.warning(f"Error getting CEO teachings: {type(e).__name__}")
            return []

    @staticmethod
    async def _return_prefetched(value: str) -> str:
        """プリフェッチ済みの値を返す（asyncio.gather互換用）"""
        return value

    async def _get_phase2e_learnings(
        self,
        message: str,
        user_id: str,
        room_id: str,
    ) -> str:
        """Phase 2E: 適用可能な学習済み知識をプロンプト文として取得

        Note: asyncio.to_thread()で同期DB呼び出しをオフロードし、
        asyncio.gather()内でイベントループをブロックしない。
        """
        if not self.phase2e_learning:
            return ""

        try:
            def _sync_fetch():
                with self.pool.connect() as conn:
                    applicable = self.phase2e_learning.find_applicable(
                        conn, message, None, user_id, room_id
                    )
                    if not applicable:
                        return ""
                    context_additions = self.phase2e_learning.build_context_additions(
                        applicable
                    )
                    return self.phase2e_learning.build_prompt_instructions(
                        context_additions
                    )
            return await asyncio.to_thread(_sync_fetch)
        except Exception as e:
            logger.warning(f"Error getting Phase 2E learnings: {type(e).__name__}")
            return ""

    async def _get_outcome_patterns(
        self,
        user_id: str,
    ) -> str:
        """Phase 2F: ユーザーの行動パターンを取得

        Note: asyncio.to_thread()で同期DB呼び出しをオフロードし、
        asyncio.gather()内でイベントループをブロックしない。
        """
        if not self.outcome_learning:
            return ""

        try:
            def _sync_fetch():
                with self.pool.connect() as conn:
                    patterns = self.outcome_learning.find_applicable_patterns(
                        conn=conn, target_account_id=user_id,
                    )
                    if not patterns:
                        return ""
                    lines = []
                    for p in patterns[:3]:
                        content = p.pattern_content or {}
                        desc = content.get("description", p.pattern_type)
                        score = p.confidence_score or 0.0
                        lines.append(f"- {desc} (信頼度: {score:.0%})")
                    return "【行動パターン（Phase 2F）】\n" + "\n".join(lines)
            return await asyncio.to_thread(_sync_fetch)
        except Exception as e:
            logger.warning("Phase 2F pattern fetch failed: %s", type(e).__name__)
            return ""

    async def _get_emotion_context(
        self,
        message: str,
        organization_id: str,
        user_id: Optional[str] = None,
    ) -> str:
        """Task 7: ユーザーの感情・ニュアンスを読み取る"""
        if not self.emotion_reader:
            return ""

        try:
            from lib.brain.deep_understanding.models import DeepUnderstandingInput

            input_ctx = DeepUnderstandingInput(
                message=message,
                organization_id=organization_id,
                user_id=user_id,
            )
            result = await self.emotion_reader.read(
                message=message,
                input_context=input_ctx,
            )

            if not result.emotions and not result.urgency:
                return ""

            lines = []
            if result.primary_emotion:
                em = result.primary_emotion
                lines.append(
                    f"- 主要感情: {em.category.value}"
                    f"（強度: {em.intensity:.0%}, 信頼度: {em.confidence:.0%}）"
                )
            if result.urgency:
                lines.append(f"- 緊急度: {result.urgency.level.value}")
            if result.nuances:
                nuance_strs = [n.nuance_type.value for n in result.nuances[:3]]
                lines.append(f"- ニュアンス: {', '.join(nuance_strs)}")
            if result.summary:
                lines.append(f"- サマリー: {result.summary}")

            return "【ユーザーの感情・ニュアンス】\n" + "\n".join(lines)
        except Exception as e:
            logger.warning("Emotion reading failed: %s", type(e).__name__)
            return ""

    async def _get_user_info(
        self,
        user_id: str,
        organization_id: str,
        sender_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """ユーザー基本情報をDBから取得"""
        if self.pool:
            try:
                from sqlalchemy import text

                def _query():
                    with self.pool.connect() as conn:
                        result = conn.execute(text("""
                            SELECT u.name, r.name AS role_name
                            FROM users u
                            LEFT JOIN user_departments ud ON ud.user_id = u.id
                            LEFT JOIN roles r ON ud.role_id = r.id
                            WHERE u.chatwork_account_id = :account_id
                            AND u.organization_id = :org_id
                            LIMIT 1
                        """), {"account_id": user_id, "org_id": organization_id})
                        return result.fetchone()

                row = await asyncio.to_thread(_query)
                if row:
                    return {
                        "name": row[0] or sender_name or "ユーザー",
                        "role": row[1] or "",
                    }
            except Exception as e:
                logger.warning("Failed to get user info from DB: %s", type(e).__name__)
        return {
            "name": sender_name or "ユーザー",
            "role": "",
        }

    def _get_company_values(self) -> str:
        """会社の価値観（MVV）を取得"""
        # 設計書 docs/01_philosophy_and_principles.md より
        return """
ミッション: 可能性の解放
ビジョン: 前を向く全ての人の可能性を解放し続けることで、企業も人も心で繋がる未来
バリュー: 感謝で自分を満たし、満たした自分で相手を満たし、相手も自分で自分を満たせるように伴走する
""".strip()

    async def enrich_with_knowledge(
        self,
        context: LLMContext,
        query: str,
    ) -> LLMContext:
        """
        必要に応じてナレッジを追加取得

        Args:
            context: 既存のコンテキスト
            query: 検索クエリ

        Returns:
            ナレッジを追加したコンテキスト
        """
        if not self.memory_access:
            return context

        try:
            knowledge = await self.memory_access.get_relevant_knowledge(query)
            context.relevant_knowledge = [
                KnowledgeChunk(
                    content=k.get("content", ""),
                    source=k.get("source", ""),
                    relevance_score=k.get("score", 0.0),
                )
                for k in knowledge[:5]
            ]
        except Exception as e:
            logger.warning(f"Error enriching with knowledge: {type(e).__name__}")

        return context
