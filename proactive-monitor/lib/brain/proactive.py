# lib/brain/proactive.py
"""
Phase 2: 能動的モニタリング（Proactive Monitoring）

ユーザーからのメッセージを待たず、必要な時に自分から声をかける能力。

設計書: docs/19_ultimate_brain_architecture.md セクション4.2

【トリガー条件】
1. 目標放置: 7日間更新なし → 「目標の進捗、どうですか？」
2. タスク山積み: 5件以上遅延 → 「タスクが溜まってるみたいですね」
3. 感情変化: ネガティブ継続3日 → 「最近調子どうですか？」
4. 質問放置: 24時間未回答 → 「昨日の質問、分かりましたか？」
5. 成功パターン: 目標達成 → 「おめでとう！次の目標は？」

【実行タイミング】
Cloud Schedulerから毎時実行（本番環境）
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any, Callable, Awaitable
from uuid import UUID
from lib.brain.constants import JST
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ============================================================
# Enum定義
# ============================================================

class TriggerType(Enum):
    """トリガータイプ"""
    GOAL_ABANDONED = "goal_abandoned"          # 目標放置
    TASK_OVERLOAD = "task_overload"            # タスク山積み
    EMOTION_DECLINE = "emotion_decline"        # 感情変化（ネガティブ継続）
    QUESTION_UNANSWERED = "question_unanswered"  # 質問放置
    GOAL_ACHIEVED = "goal_achieved"            # 目標達成
    TASK_COMPLETED_STREAK = "task_completed_streak"  # タスク連続完了
    LONG_ABSENCE = "long_absence"              # 長期不在


class ProactiveMessageType(Enum):
    """能動的メッセージのタイプ"""
    FOLLOW_UP = "follow_up"        # フォローアップ
    ENCOURAGEMENT = "encouragement"  # 励まし
    REMINDER = "reminder"          # リマインダー
    CELEBRATION = "celebration"    # お祝い
    CHECK_IN = "check_in"          # 様子確認


class ActionPriority(Enum):
    """アクション優先度"""
    CRITICAL = "critical"    # 即座に対応が必要
    HIGH = "high"            # 当日中に対応
    MEDIUM = "medium"        # 週内に対応
    LOW = "low"              # 余裕があれば対応


# ============================================================
# 定数
# ============================================================

# 組織IDマッピング（UUID → chatwork_tasks用VARCHAR）
# chatwork_tasksテーブルはVARCHAR型のorganization_idを使用
# TODO: Phase 4A で organizations テーブルから動的に取得
ORGANIZATION_UUID_TO_SLUG = {
    "5f98365f-e7c5-4f48-9918-7fe9aabae5df": "org_soulsyncs",  # Soul Syncs
}
DEFAULT_CHATWORK_TASKS_ORG_ID = "org_soulsyncs"

# トリガー閾値
GOAL_ABANDONED_DAYS = 7          # 目標放置とみなす日数
TASK_OVERLOAD_COUNT = 5          # タスク山積みとみなす件数
EMOTION_DECLINE_DAYS = 3         # ネガティブ継続日数
QUESTION_UNANSWERED_HOURS = 24   # 質問放置時間
LONG_ABSENCE_DAYS = 14           # 長期不在とみなす日数

# メッセージクールダウン（同じトリガーで再度メッセージを送るまでの時間）
MESSAGE_COOLDOWN_HOURS = {
    TriggerType.GOAL_ABANDONED: 72,       # 3日
    TriggerType.TASK_OVERLOAD: 48,        # 2日
    TriggerType.EMOTION_DECLINE: 24,      # 1日
    TriggerType.QUESTION_UNANSWERED: 12,  # 12時間
    TriggerType.GOAL_ACHIEVED: 168,       # 7日（1回祝ったら終わり）
    TriggerType.TASK_COMPLETED_STREAK: 24,  # 1日
    TriggerType.LONG_ABSENCE: 168,        # 7日
}

# 優先度マッピング
TRIGGER_PRIORITY = {
    TriggerType.EMOTION_DECLINE: ActionPriority.CRITICAL,
    TriggerType.TASK_OVERLOAD: ActionPriority.HIGH,
    TriggerType.GOAL_ABANDONED: ActionPriority.MEDIUM,
    TriggerType.QUESTION_UNANSWERED: ActionPriority.MEDIUM,
    TriggerType.GOAL_ACHIEVED: ActionPriority.MEDIUM,
    TriggerType.TASK_COMPLETED_STREAK: ActionPriority.LOW,
    TriggerType.LONG_ABSENCE: ActionPriority.MEDIUM,
}

# メッセージテンプレート
MESSAGE_TEMPLATES = {
    TriggerType.GOAL_ABANDONED: [
        "目標の進捗、どうですかウル？🐺 一緒に確認してみませんか？",
        "{goal_name}の目標、最近どうなってますかウル？ 何かお手伝いできることはありますか？",
        "目標を立ててから{days}日経ちましたウル。進み具合を教えてもらえますか？",
    ],
    TriggerType.TASK_OVERLOAD: [
        "タスクが{count}件溜まってるみたいですねウル🐺 優先順位を一緒に整理しましょうか？",
        "お仕事がたくさんあるみたいですねウル。何か手伝えることはありますか？",
        "期限が過ぎているタスクが{overdue_count}件ありますウル。どれから片付けますか？",
    ],
    TriggerType.EMOTION_DECLINE: [
        "最近調子どうですかウル？🐺 何か気になることがあれば聞きますよ",
        "少し元気がないように感じましたウル。大丈夫ですか？",
        "最近忙しそうですねウル。無理しすぎていませんか？",
    ],
    TriggerType.QUESTION_UNANSWERED: [
        "昨日の質問、分かりましたかウル？🐺",
        "「{question_summary}」の件、解決しましたかウル？",
        "先ほどの質問にまだお答えできていませんでしたウル。改めて調べましょうか？",
    ],
    TriggerType.GOAL_ACHIEVED: [
        "おめでとうございますウル！🎉🐺 {goal_name}を達成しましたね！次の目標は何にしますか？",
        "素晴らしいですウル！目標達成おめでとうございます！🎉 この調子で次も頑張りましょう！",
        "{goal_name}、やりましたねウル！✨ どんな感じでしたか？",
    ],
    TriggerType.TASK_COMPLETED_STREAK: [
        "タスクを{count}件連続で完了しましたねウル！🎉 すごい調子です！",
        "最近タスクの完了ペースが上がってますねウル！✨ この調子で頑張りましょう！",
    ],
    TriggerType.LONG_ABSENCE: [
        "お久しぶりですウル！🐺 最近どうしていましたか？",
        "{days}日ぶりですねウル！元気にしてましたか？",
    ],
}


# ============================================================
# データクラス
# ============================================================

@dataclass(frozen=True)
class Trigger:
    """検出されたトリガー"""
    trigger_type: TriggerType
    user_id: str
    organization_id: str
    priority: ActionPriority
    details: Dict[str, Any] = field(default_factory=dict)
    detected_at: datetime = field(default_factory=lambda: datetime.now(JST))

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "trigger_type": self.trigger_type.value,
            "user_id": self.user_id,
            "organization_id": self.organization_id,
            "priority": self.priority.value,
            "details": self.details,
            "detected_at": self.detected_at.isoformat(),
        }


@dataclass(frozen=True)
class ProactiveMessage:
    """能動的メッセージ"""
    trigger: Trigger
    message_type: ProactiveMessageType
    message: str
    room_id: Optional[str] = None
    account_id: Optional[str] = None  # ChatWork account ID
    scheduled_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "trigger": self.trigger.to_dict(),
            "message_type": self.message_type.value,
            "message": self.message,
            "room_id": self.room_id,
            "account_id": self.account_id,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
        }


@dataclass
class ProactiveAction:
    """実行されたアクション"""
    message: ProactiveMessage
    sent_at: datetime = field(default_factory=lambda: datetime.now(JST))
    success: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "message": self.message.to_dict(),
            "sent_at": self.sent_at.isoformat(),
            "success": self.success,
            "error_message": self.error_message,
        }


@dataclass
class UserContext:
    """ユーザーコンテキスト（チェック対象の情報）"""
    user_id: str
    organization_id: str
    chatwork_account_id: Optional[str] = None
    dm_room_id: Optional[str] = None  # ダイレクトメッセージ用ルームID
    last_activity_at: Optional[datetime] = None
    last_proactive_message_at: Optional[datetime] = None
    last_proactive_trigger: Optional[TriggerType] = None


@dataclass
class CheckResult:
    """チェック結果"""
    user_id: str
    triggers_found: List[Trigger] = field(default_factory=list)
    actions_taken: List[ProactiveAction] = field(default_factory=list)
    skipped_triggers: List[Dict[str, Any]] = field(default_factory=list)  # クールダウン中などでスキップされたトリガー
    checked_at: datetime = field(default_factory=lambda: datetime.now(JST))


# ============================================================
# メインクラス
# ============================================================

class ProactiveMonitor:
    """
    能動的モニタリングシステム

    ユーザーからのメッセージを待たず、必要な時に自分から声をかける。
    Cloud Schedulerから毎時実行される。

    使用例:
        monitor = ProactiveMonitor(pool=db_pool)

        # 全ユーザーをチェック
        results = await monitor.check_and_act()

        # 特定ユーザーのみチェック
        result = await monitor.check_user(user_id="xxx", organization_id="yyy")
    """

    def __init__(
        self,
        pool=None,
        send_message_func: Optional[Callable[..., Awaitable[bool]]] = None,
        dry_run: bool = False,
        brain=None,  # CLAUDE.md鉄則1b: 脳経由でメッセージ生成
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            send_message_func: メッセージ送信関数（ChatWork API）
            dry_run: Trueの場合、メッセージを送信せずログのみ
            brain: SoulkunBrain インスタンス（脳経由でメッセージ生成）
        """
        self._pool = pool
        self._send_message_func = send_message_func
        self._dry_run = dry_run
        self._brain = brain  # CLAUDE.md鉄則1b準拠

        # トリガーチェッカーの登録
        self._trigger_checkers: Dict[TriggerType, Callable] = {
            TriggerType.GOAL_ABANDONED: self._check_goal_abandoned,
            TriggerType.TASK_OVERLOAD: self._check_task_overload,
            TriggerType.EMOTION_DECLINE: self._check_emotion_decline,
            TriggerType.QUESTION_UNANSWERED: self._check_question_unanswered,
            TriggerType.GOAL_ACHIEVED: self._check_goal_achieved,
            TriggerType.TASK_COMPLETED_STREAK: self._check_task_completed_streak,
            TriggerType.LONG_ABSENCE: self._check_long_absence,
        }

    @asynccontextmanager
    async def _connect_with_org_context(self, organization_id: str):
        """
        organization_idコンテキスト付きでDB接続を取得（RLS対応）

        brain_*テーブルのRLSポリシーはapp.current_organization_idを
        参照するため、接続時に必ず設定する。

        注意:
        - 必ずSETを実行し、前の接続の値が残らないようにする（データ漏洩防止）
        - 終了時にRESETで値をクリア

        Args:
            organization_id: 組織ID（UUID文字列）
        """
        async with self._pool.connect() as conn:
            await conn.execute(
                text("SET app.current_organization_id = :org_id"),
                {"org_id": organization_id}
            )
            try:
                yield conn
            finally:
                await conn.execute(text("RESET app.current_organization_id"))

    # --------------------------------------------------------
    # ヘルパーメソッド（型変換）
    # --------------------------------------------------------

    def _get_chatwork_tasks_org_id(self, uuid_org_id: str) -> str:
        """
        chatwork_tasks テーブル用の organization_id を取得

        chatwork_tasks.organization_id は VARCHAR型で 'org_soulsyncs' 等の文字列。
        users.organization_id は UUID型。この変換を行う。

        Args:
            uuid_org_id: UUID形式のorganization_id

        Returns:
            str: chatwork_tasks用のorganization_id（'org_soulsyncs' 等）
        """
        return ORGANIZATION_UUID_TO_SLUG.get(uuid_org_id, DEFAULT_CHATWORK_TASKS_ORG_ID)

    def _get_chatwork_account_id_int(self, str_account_id: Optional[str]) -> Optional[int]:
        """
        chatwork_tasks テーブル用の account_id を整数に変換

        chatwork_tasks.assigned_to_account_id は BIGINT型。
        users.chatwork_account_id は VARCHAR型。この変換を行う。

        Args:
            str_account_id: 文字列形式のaccount_id

        Returns:
            int: 整数形式のaccount_id、または変換失敗時はNone
        """
        if not str_account_id:
            return None
        try:
            return int(str_account_id)
        except (ValueError, TypeError):
            logger.warning(f"[Proactive] Invalid chatwork_account_id: {str_account_id}")
            return None

    def _is_valid_uuid(self, value: str) -> bool:
        """
        文字列がUUID形式かどうかを判定

        Args:
            value: 検証する文字列

        Returns:
            bool: UUID形式ならTrue
        """
        if not value:
            return False
        # UUID形式: 8-4-4-4-12 (32文字 + 4ハイフン = 36文字)
        if len(value) < 32 or len(value) > 36:
            return False
        try:
            from uuid import UUID
            UUID(value)
            return True
        except (ValueError, AttributeError):
            return False

    # --------------------------------------------------------
    # メイン処理
    # --------------------------------------------------------

    async def check_and_act(
        self,
        organization_id: Optional[str] = None,
    ) -> List[CheckResult]:
        """
        全ユーザーをチェックし、必要に応じて声かけ

        Args:
            organization_id: 特定の組織のみチェック（省略時は全組織）

        Returns:
            各ユーザーのチェック結果リスト
        """
        results = []

        try:
            # アクティブユーザーを取得
            users = await self._get_active_users(organization_id)
            logger.info(f"[Proactive] Checking {len(users)} users")

            for user_ctx in users:
                try:
                    result = await self._check_single_user(user_ctx)
                    results.append(result)
                except Exception as e:
                    logger.error(f"[Proactive] Error checking user {user_ctx.user_id}: {e}")
                    results.append(CheckResult(
                        user_id=user_ctx.user_id,
                        triggers_found=[],
                        actions_taken=[ProactiveAction(
                            message=ProactiveMessage(
                                trigger=Trigger(
                                    trigger_type=TriggerType.GOAL_ABANDONED,
                                    user_id=user_ctx.user_id,
                                    organization_id=user_ctx.organization_id,
                                    priority=ActionPriority.LOW,
                                ),
                                message_type=ProactiveMessageType.CHECK_IN,
                                message="",
                            ),
                            success=False,
                            error_message=str(e),
                        )],
                    ))

            # 統計ログ
            total_triggers = sum(len(r.triggers_found) for r in results)
            total_actions = sum(len(r.actions_taken) for r in results)
            logger.info(f"[Proactive] Complete: {total_triggers} triggers found, {total_actions} actions taken")

        except Exception as e:
            logger.error(f"[Proactive] Critical error in check_and_act: {e}")

        return results

    async def check_user(
        self,
        user_id: str,
        organization_id: str,
    ) -> CheckResult:
        """
        特定ユーザーをチェック

        Args:
            user_id: ユーザーID
            organization_id: 組織ID

        Returns:
            チェック結果
        """
        user_ctx = await self._get_user_context(user_id, organization_id)
        if not user_ctx:
            return CheckResult(user_id=user_id, triggers_found=[])

        return await self._check_single_user(user_ctx)

    async def _check_single_user(self, user_ctx: UserContext) -> CheckResult:
        """単一ユーザーのチェックと対応"""
        result = CheckResult(user_id=user_ctx.user_id)

        # 全トリガーをチェック
        for trigger_type, checker in self._trigger_checkers.items():
            try:
                trigger = await checker(user_ctx)
                if trigger:
                    # クールダウンチェック
                    if await self._is_in_cooldown(user_ctx, trigger_type):
                        result.skipped_triggers.append({
                            "trigger_type": trigger_type.value,
                            "reason": "cooldown",
                        })
                        continue

                    result.triggers_found.append(trigger)

                    # アクション実行
                    if self._should_act(trigger, user_ctx):
                        action = await self._take_action(trigger, user_ctx)
                        result.actions_taken.append(action)

            except Exception as e:
                logger.warning(f"[Proactive] Error checking {trigger_type.value} for {user_ctx.user_id}: {e}")

        return result

    # --------------------------------------------------------
    # トリガーチェッカー
    # --------------------------------------------------------

    async def _check_goal_abandoned(self, user_ctx: UserContext) -> Optional[Trigger]:
        """目標放置チェック"""
        if not self._pool:
            return None

        # goals.organization_idはUUID型。有効なUUIDかチェック
        if not self._is_valid_uuid(user_ctx.organization_id):
            logger.debug(f"[Proactive] Skipping goal abandoned check - invalid UUID for user {user_ctx.user_id}: {user_ctx.organization_id}")
            return None

        try:
            from sqlalchemy import text

            query = text("""
                SELECT id, title, created_at, updated_at
                FROM goals
                WHERE organization_id = CAST(:org_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                  AND status = 'active'
                  AND updated_at < :threshold AT TIME ZONE 'Asia/Tokyo'
                ORDER BY updated_at ASC
                LIMIT 1
            """)

            threshold = datetime.now(JST) - timedelta(days=GOAL_ABANDONED_DAYS)

            async with self._pool.connect() as conn:
                result = await conn.execute(query, {
                    "org_id": user_ctx.organization_id,
                    "user_id": user_ctx.user_id,
                    "threshold": threshold,
                })
                row = result.fetchone()

            if row:
                days_since_update = (datetime.now(JST) - row.updated_at).days
                return Trigger(
                    trigger_type=TriggerType.GOAL_ABANDONED,
                    user_id=user_ctx.user_id,
                    organization_id=user_ctx.organization_id,
                    priority=TRIGGER_PRIORITY[TriggerType.GOAL_ABANDONED],
                    details={
                        "goal_id": str(row.id),
                        "goal_name": row.title[:50] if row.title else "",
                        "days_since_update": days_since_update,
                    },
                )

        except Exception as e:
            logger.warning(f"[Proactive] Goal abandoned check failed: {e}")

        return None

    async def _check_task_overload(self, user_ctx: UserContext) -> Optional[Trigger]:
        """タスク山積みチェック"""
        if not self._pool:
            return None

        # chatwork_account_idをintに変換（chatwork_tasks.assigned_to_account_idはBIGINT）
        account_id_int = self._get_chatwork_account_id_int(user_ctx.chatwork_account_id)
        if account_id_int is None:
            logger.debug(f"[Proactive] Skipping task overload check - no valid account_id for user {user_ctx.user_id}")
            return None

        try:
            from sqlalchemy import text

            # chatwork_tasks.organization_idはVARCHAR型（'org_soulsyncs'等）
            chatwork_org_id = self._get_chatwork_tasks_org_id(user_ctx.organization_id)

            query = text("""
                SELECT COUNT(*) as total_count,
                       COUNT(CASE WHEN limit_time IS NOT NULL AND limit_time < EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)::bigint THEN 1 END) as overdue_count
                FROM chatwork_tasks
                WHERE organization_id = :org_id
                  AND assigned_to_account_id = :account_id
                  AND status = 'open'
            """)

            async with self._pool.connect() as conn:
                result = await conn.execute(query, {
                    "org_id": chatwork_org_id,
                    "account_id": account_id_int,
                })
                row = result.fetchone()

            if row and row.total_count >= TASK_OVERLOAD_COUNT:
                return Trigger(
                    trigger_type=TriggerType.TASK_OVERLOAD,
                    user_id=user_ctx.user_id,
                    organization_id=user_ctx.organization_id,
                    priority=TRIGGER_PRIORITY[TriggerType.TASK_OVERLOAD],
                    details={
                        "count": row.total_count,
                        "overdue_count": row.overdue_count or 0,
                    },
                )

        except Exception as e:
            logger.warning(f"[Proactive] Task overload check failed: {e}")

        return None

    async def _check_emotion_decline(self, user_ctx: UserContext) -> Optional[Trigger]:
        """感情変化チェック（ネガティブ継続）"""
        if not self._pool:
            return None

        # emotion_scores.organization_idはUUID型。有効なUUIDかチェック
        if not self._is_valid_uuid(user_ctx.organization_id):
            logger.debug(f"[Proactive] Skipping emotion decline check - invalid UUID for user {user_ctx.user_id}: {user_ctx.organization_id}")
            return None

        try:
            from sqlalchemy import text

            # 直近N日間の感情スコアを取得
            query = text("""
                SELECT sentiment_score, message_time
                FROM emotion_scores
                WHERE organization_id = CAST(:org_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                  AND message_time >= :threshold AT TIME ZONE 'Asia/Tokyo'
                ORDER BY message_time DESC
            """)

            threshold = datetime.now(JST) - timedelta(days=EMOTION_DECLINE_DAYS)

            async with self._pool.connect() as conn:
                result = await conn.execute(query, {
                    "org_id": user_ctx.organization_id,
                    "user_id": user_ctx.user_id,
                    "threshold": threshold,
                })
                rows = result.fetchall()

            if len(rows) >= 3:  # 最低3件のデータが必要
                avg_score = sum(r.sentiment_score for r in rows) / len(rows)
                if avg_score < -0.3:  # ネガティブ傾向
                    return Trigger(
                        trigger_type=TriggerType.EMOTION_DECLINE,
                        user_id=user_ctx.user_id,
                        organization_id=user_ctx.organization_id,
                        priority=TRIGGER_PRIORITY[TriggerType.EMOTION_DECLINE],
                        details={
                            "avg_sentiment_score": round(avg_score, 2),
                            "sample_count": len(rows),
                        },
                    )

        except Exception as e:
            logger.warning(f"[Proactive] Emotion decline check failed: {e}")

        return None

    async def _check_question_unanswered(self, user_ctx: UserContext) -> Optional[Trigger]:
        """質問放置チェック"""
        # 現時点では未実装（会話ログからの質問検出が必要）
        return None

    async def _check_goal_achieved(self, user_ctx: UserContext) -> Optional[Trigger]:
        """目標達成チェック"""
        if not self._pool:
            return None

        # goals.organization_idはUUID型。有効なUUIDかチェック
        if not self._is_valid_uuid(user_ctx.organization_id):
            logger.debug(f"[Proactive] Skipping goal achieved check - invalid UUID for user {user_ctx.user_id}: {user_ctx.organization_id}")
            return None

        try:
            from sqlalchemy import text

            # 直近24時間以内に達成された目標
            query = text("""
                SELECT id, title, updated_at
                FROM goals
                WHERE organization_id = CAST(:org_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                  AND status = 'completed'
                  AND updated_at >= :threshold AT TIME ZONE 'Asia/Tokyo'
                ORDER BY updated_at DESC
                LIMIT 1
            """)

            threshold = datetime.now(JST) - timedelta(hours=24)

            async with self._pool.connect() as conn:
                result = await conn.execute(query, {
                    "org_id": user_ctx.organization_id,
                    "user_id": user_ctx.user_id,
                    "threshold": threshold,
                })
                row = result.fetchone()

            if row:
                return Trigger(
                    trigger_type=TriggerType.GOAL_ACHIEVED,
                    user_id=user_ctx.user_id,
                    organization_id=user_ctx.organization_id,
                    priority=TRIGGER_PRIORITY[TriggerType.GOAL_ACHIEVED],
                    details={
                        "goal_id": str(row.id),
                        "goal_name": row.title[:50] if row.title else "",
                    },
                )

        except Exception as e:
            logger.warning(f"[Proactive] Goal achieved check failed: {e}")

        return None

    async def _check_task_completed_streak(self, user_ctx: UserContext) -> Optional[Trigger]:
        """タスク連続完了チェック"""
        if not self._pool:
            return None

        # chatwork_account_idをintに変換（chatwork_tasks.assigned_to_account_idはBIGINT）
        account_id_int = self._get_chatwork_account_id_int(user_ctx.chatwork_account_id)
        if account_id_int is None:
            logger.debug(f"[Proactive] Skipping task completed streak check - no valid account_id for user {user_ctx.user_id}")
            return None

        try:
            from sqlalchemy import text

            # chatwork_tasks.organization_idはVARCHAR型（'org_soulsyncs'等）
            chatwork_org_id = self._get_chatwork_tasks_org_id(user_ctx.organization_id)

            # 直近24時間以内に完了したタスク数
            query = text("""
                SELECT COUNT(*) as count
                FROM chatwork_tasks
                WHERE organization_id = :org_id
                  AND assigned_to_account_id = :account_id
                  AND status = 'done'
                  AND updated_at >= :threshold AT TIME ZONE 'Asia/Tokyo'
            """)

            threshold = datetime.now(JST) - timedelta(hours=24)

            async with self._pool.connect() as conn:
                result = await conn.execute(query, {
                    "org_id": chatwork_org_id,
                    "account_id": account_id_int,
                    "threshold": threshold,
                })
                row = result.fetchone()

            if row and row.count >= 3:  # 3件以上完了で称賛
                return Trigger(
                    trigger_type=TriggerType.TASK_COMPLETED_STREAK,
                    user_id=user_ctx.user_id,
                    organization_id=user_ctx.organization_id,
                    priority=TRIGGER_PRIORITY[TriggerType.TASK_COMPLETED_STREAK],
                    details={
                        "count": row.count,
                    },
                )

        except Exception as e:
            logger.warning(f"[Proactive] Task completed streak check failed: {e}")

        return None

    async def _check_long_absence(self, user_ctx: UserContext) -> Optional[Trigger]:
        """長期不在チェック"""
        if not user_ctx.last_activity_at:
            return None

        days_since_activity = (datetime.now(JST) - user_ctx.last_activity_at).days

        if days_since_activity >= LONG_ABSENCE_DAYS:
            return Trigger(
                trigger_type=TriggerType.LONG_ABSENCE,
                user_id=user_ctx.user_id,
                organization_id=user_ctx.organization_id,
                priority=TRIGGER_PRIORITY[TriggerType.LONG_ABSENCE],
                details={
                    "days": days_since_activity,
                },
            )

        return None

    # --------------------------------------------------------
    # アクション実行
    # --------------------------------------------------------

    def _should_act(self, trigger: Trigger, user_ctx: UserContext) -> bool:
        """アクションを実行すべきかどうか判定"""
        # 優先度がLOWの場合は日中のみ
        if trigger.priority == ActionPriority.LOW:
            current_hour = datetime.now(JST).hour
            if current_hour < 9 or current_hour >= 18:
                return False

        # 送信先がない場合はスキップ
        if not user_ctx.dm_room_id and not user_ctx.chatwork_account_id:
            return False

        return True

    async def _is_in_cooldown(
        self,
        user_ctx: UserContext,
        trigger_type: TriggerType,
    ) -> bool:
        """クールダウン期間中かどうかチェック"""
        if not self._pool:
            return False

        try:
            from sqlalchemy import text

            cooldown_hours = MESSAGE_COOLDOWN_HOURS.get(trigger_type, 24)
            threshold = datetime.now(JST) - timedelta(hours=cooldown_hours)

            query = text("""
                SELECT id FROM brain_proactive_actions
                WHERE organization_id = :org_id
                  AND user_id = :user_id
                  AND trigger_type = :trigger_type
                  AND sent_at >= :threshold AT TIME ZONE 'Asia/Tokyo'
                LIMIT 1
            """)

            # brain_*テーブルアクセス: RLSコンテキスト設定
            async with self._connect_with_org_context(user_ctx.organization_id) as conn:
                result = await conn.execute(query, {
                    "org_id": user_ctx.organization_id,
                    "user_id": user_ctx.user_id,
                    "trigger_type": trigger_type.value,
                    "threshold": threshold,
                })
                return result.fetchone() is not None

        except Exception as e:
            # テーブルが存在しない場合などはクールダウンなしとして扱う
            logger.debug(f"[Proactive] Cooldown check failed (continuing): {e}")
            return False

    async def _take_action(
        self,
        trigger: Trigger,
        user_ctx: UserContext,
    ) -> ProactiveAction:
        """
        アクションを実行（CLAUDE.md鉄則1b準拠: 脳経由でメッセージ生成）

        【処理フロー】
        1. 脳が利用可能なら、脳にメッセージ生成を依頼
        2. 脳が「送らない」と判断したらスキップ
        3. 脳が生成したメッセージを送信
        4. 脳が利用不可の場合のみ、フォールバック（テンプレート）を使用
        """
        message = None
        brain_result = None

        # CLAUDE.md鉄則1b: 脳経由でメッセージ生成
        if self._brain:
            try:
                brain_result = await self._brain.generate_proactive_message(
                    trigger_type=trigger.trigger_type.value,
                    trigger_details=trigger.details,
                    user_id=user_ctx.user_id,
                    organization_id=user_ctx.organization_id,
                    room_id=user_ctx.dm_room_id,
                    account_id=user_ctx.chatwork_account_id,
                )

                # 脳が「送らない」と判断した場合
                if not brain_result.should_send:
                    logger.info(
                        f"[Proactive] Brain decided not to send: {brain_result.reason}"
                    )
                    return ProactiveAction(
                        message=ProactiveMessage(
                            trigger=trigger,
                            message_type=self._get_message_type(trigger.trigger_type),
                            message="",
                            room_id=user_ctx.dm_room_id,
                            account_id=user_ctx.chatwork_account_id,
                        ),
                        success=True,
                        error_message=f"Skipped by brain: {brain_result.reason}",
                    )

                # 脳が生成したメッセージを使用
                message = brain_result.message
                logger.info(f"[Proactive] Using brain-generated message")

            except Exception as e:
                logger.warning(f"[Proactive] Brain message generation failed: {e}")
                # フォールバック: テンプレートを使用
                message = None

        # フォールバック: 脳が利用不可または失敗した場合
        if not message:
            logger.warning(
                "[Proactive] Using fallback template (brain not available or failed). "
                "This is a CLAUDE.md violation - brain should generate messages."
            )
            message = self._generate_message(trigger)

        proactive_msg = ProactiveMessage(
            trigger=trigger,
            message_type=self._get_message_type(trigger.trigger_type),
            message=message,
            room_id=user_ctx.dm_room_id,
            account_id=user_ctx.chatwork_account_id,
        )

        # dry_runモードの場合はログのみ
        if self._dry_run:
            brain_info = "(brain-generated)" if brain_result and brain_result.should_send else "(fallback)"
            logger.info(f"[Proactive][DRY_RUN] Would send {brain_info}: {message}")
            return ProactiveAction(message=proactive_msg, success=True)

        # メッセージ送信
        success = True
        error_message = None

        if self._send_message_func and user_ctx.dm_room_id:
            try:
                result = await self._send_message_func(
                    room_id=user_ctx.dm_room_id,
                    message=message,
                )
                success = bool(result)
            except Exception as e:
                success = False
                error_message = str(e)
                logger.error(f"[Proactive] Failed to send message: {e}")

        # アクションをログに記録
        if success:
            await self._log_action(trigger, user_ctx)

        return ProactiveAction(
            message=proactive_msg,
            success=success,
            error_message=error_message,
        )

    def _generate_message(self, trigger: Trigger) -> str:
        """メッセージを生成"""
        import random

        templates = MESSAGE_TEMPLATES.get(trigger.trigger_type, [])
        if not templates:
            return "何かお手伝いできることはありますかウル？🐺"

        template = random.choice(templates)

        # プレースホルダを置換
        details = trigger.details
        try:
            return template.format(**details)
        except KeyError:
            # プレースホルダがない場合は最初のテンプレートをそのまま使用
            return templates[0].format(**{k: v for k, v in details.items() if f"{{{k}}}" in templates[0]})

    def _get_message_type(self, trigger_type: TriggerType) -> ProactiveMessageType:
        """トリガータイプからメッセージタイプを決定"""
        mapping = {
            TriggerType.GOAL_ABANDONED: ProactiveMessageType.FOLLOW_UP,
            TriggerType.TASK_OVERLOAD: ProactiveMessageType.REMINDER,
            TriggerType.EMOTION_DECLINE: ProactiveMessageType.CHECK_IN,
            TriggerType.QUESTION_UNANSWERED: ProactiveMessageType.FOLLOW_UP,
            TriggerType.GOAL_ACHIEVED: ProactiveMessageType.CELEBRATION,
            TriggerType.TASK_COMPLETED_STREAK: ProactiveMessageType.ENCOURAGEMENT,
            TriggerType.LONG_ABSENCE: ProactiveMessageType.CHECK_IN,
        }
        return mapping.get(trigger_type, ProactiveMessageType.CHECK_IN)

    async def _log_action(self, trigger: Trigger, user_ctx: UserContext):
        """アクションをDBに記録"""
        if not self._pool:
            return

        try:
            from sqlalchemy import text

            query = text("""
                INSERT INTO brain_proactive_actions
                (organization_id, user_id, trigger_type, trigger_details, sent_at)
                VALUES (:org_id, :user_id, :trigger_type, CAST(:details AS jsonb), :sent_at)
            """)

            # brain_*テーブルアクセス: RLSコンテキスト設定
            async with self._connect_with_org_context(user_ctx.organization_id) as conn:
                await conn.execute(query, {
                    "org_id": user_ctx.organization_id,
                    "user_id": user_ctx.user_id,
                    "trigger_type": trigger.trigger_type.value,
                    "details": str(trigger.details),  # JSON文字列に変換
                    "sent_at": datetime.now(JST),
                })
                await conn.commit()

        except Exception as e:
            logger.warning(f"[Proactive] Failed to log action: {e}")

    # --------------------------------------------------------
    # データ取得
    # --------------------------------------------------------

    async def _get_active_users(
        self,
        organization_id: Optional[str] = None,
    ) -> List[UserContext]:
        """アクティブユーザーのリストを取得"""
        if not self._pool:
            return []

        try:
            from sqlalchemy import text

            if organization_id:
                query = text("""
                    SELECT u.id, u.organization_id, u.chatwork_account_id,
                           cu.room_id AS dm_room_id, NULL AS last_active_at
                    FROM users u
                    LEFT JOIN chatwork_users cu ON u.chatwork_account_id = cu.account_id::varchar
                        AND u.organization_id = cu.organization_id::varchar
                    WHERE u.organization_id = :org_id
                      AND u.is_active = true
                """)
                params = {"org_id": organization_id}
            else:
                query = text("""
                    SELECT u.id, u.organization_id, u.chatwork_account_id,
                           cu.room_id AS dm_room_id, NULL AS last_active_at
                    FROM users u
                    LEFT JOIN chatwork_users cu ON u.chatwork_account_id = cu.account_id::varchar
                        AND u.organization_id = cu.organization_id::varchar
                    WHERE u.is_active = true
                """)
                params = {}

            async with self._pool.connect() as conn:
                result = await conn.execute(query, params)
                rows = result.fetchall()

            return [
                UserContext(
                    user_id=str(row.id),
                    organization_id=str(row.organization_id),
                    chatwork_account_id=row.chatwork_account_id,
                    dm_room_id=row.dm_room_id,
                    last_activity_at=row.last_active_at,
                )
                for row in rows
            ]

        except Exception as e:
            logger.error(f"[Proactive] Failed to get active users: {e}")
            return []

    async def _get_user_context(
        self,
        user_id: str,
        organization_id: str,
    ) -> Optional[UserContext]:
        """特定ユーザーのコンテキストを取得"""
        if not self._pool:
            return None

        try:
            from sqlalchemy import text

            query = text("""
                SELECT u.id, u.organization_id, u.chatwork_account_id,
                       cu.room_id AS dm_room_id, NULL AS last_active_at
                FROM users u
                LEFT JOIN chatwork_users cu ON u.chatwork_account_id = cu.account_id::varchar
                    AND u.organization_id = cu.organization_id::varchar
                WHERE u.id = :user_id
                  AND u.organization_id = :org_id
            """)

            async with self._pool.connect() as conn:
                result = await conn.execute(query, {
                    "user_id": user_id,
                    "org_id": organization_id,
                })
                row = result.fetchone()

            if row:
                return UserContext(
                    user_id=str(row.id),
                    organization_id=str(row.organization_id),
                    chatwork_account_id=row.chatwork_account_id,
                    dm_room_id=row.dm_room_id,
                    last_activity_at=row.last_active_at,
                )

        except Exception as e:
            logger.error(f"[Proactive] Failed to get user context: {e}")

        return None


# ============================================================
# ファクトリ関数
# ============================================================

def create_proactive_monitor(
    pool=None,
    send_message_func: Optional[Callable[..., Awaitable[bool]]] = None,
    dry_run: bool = False,
    brain=None,  # CLAUDE.md鉄則1b: 脳経由でメッセージ生成
) -> ProactiveMonitor:
    """
    ProactiveMonitorインスタンスを作成

    Args:
        pool: データベース接続プール
        send_message_func: メッセージ送信関数
        dry_run: Trueの場合、メッセージを送信せずログのみ
        brain: SoulkunBrain インスタンス（脳経由でメッセージ生成）

    Returns:
        ProactiveMonitorインスタンス

    Note:
        CLAUDE.md鉄則1b準拠: brainを渡さないとフォールバック（テンプレート）が
        使用され、警告ログが出力される。本番運用時は必ずbrainを渡すこと。
    """
    if not brain:
        logger.warning(
            "[Proactive] brain not provided. Will use fallback templates. "
            "This violates CLAUDE.md rule 1b. Consider providing a brain instance."
        )

    return ProactiveMonitor(
        pool=pool,
        send_message_func=send_message_func,
        dry_run=dry_run,
        brain=brain,
    )
