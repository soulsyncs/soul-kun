# lib/brain/episodic_memory.py
"""
Ultimate Brain Architecture - Phase 2: エピソード記憶

設計書: docs/19_ultimate_brain_architecture.md
セクション: 4.3 エピソード記憶

重要な出来事を長期記憶し、関連する場面で想起する。
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, NAMESPACE_DNS, uuid5

from sqlalchemy import text as sql_text

from .constants import JST

logger = logging.getLogger(__name__)


# ============================================================================
# Enum定義
# ============================================================================

class EpisodeType(Enum):
    """エピソードの種類"""
    ACHIEVEMENT = "achievement"     # 達成（目標達成、タスク完了）
    FAILURE = "failure"             # 失敗（ミス、期限超過）
    DECISION = "decision"           # 重要な判断
    INTERACTION = "interaction"     # 重要なやりとり
    LEARNING = "learning"           # 学習（CEO教え、フィードバック）
    EMOTION = "emotion"             # 感情的な出来事


class RecallTrigger(Enum):
    """想起のトリガー"""
    KEYWORD = "keyword"             # キーワードマッチ
    SEMANTIC = "semantic"           # 意味的類似
    ENTITY = "entity"               # エンティティマッチ
    TEMPORAL = "temporal"           # 時間的関連
    EMOTIONAL = "emotional"         # 感情的関連


# ============================================================================
# データクラス
# ============================================================================

@dataclass
class RelatedEntity:
    """関連エンティティ"""
    entity_type: str                # "person", "task", "goal", "room"
    entity_id: str
    entity_name: Optional[str] = None
    relationship: str = "involved"  # "involved", "caused", "affected"


@dataclass
class Episode:
    """エピソード"""
    id: Optional[str] = None
    organization_id: Optional[str] = None
    user_id: Optional[str] = None   # NULLなら組織全体の記憶

    # エピソード内容
    episode_type: EpisodeType = EpisodeType.INTERACTION
    summary: str = ""               # 要約
    details: Dict[str, Any] = field(default_factory=dict)

    # 感情・重要度
    emotional_valence: float = 0.0  # -1.0〜1.0（ネガティブ〜ポジティブ）
    importance_score: float = 0.5   # 0.0〜1.0

    # 検索用
    keywords: List[str] = field(default_factory=list)
    related_entities: List[RelatedEntity] = field(default_factory=list)
    embedding_id: Optional[str] = None

    # 想起管理
    recall_count: int = 0
    last_recalled_at: Optional[datetime] = None
    decay_factor: float = 1.0       # 忘却係数（時間経過で減少）

    # メタデータ
    occurred_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


@dataclass
class RecallResult:
    """想起結果"""
    episode: Episode
    relevance_score: float          # 関連度（0.0〜1.0）
    trigger: RecallTrigger          # 想起のトリガー
    matched_keywords: List[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class MemoryRecallLog:
    """想起ログ"""
    memory_id: str
    trigger_message: str
    relevance_score: float
    was_used: bool = False
    recalled_at: Optional[datetime] = None


# ============================================================================
# 定数
# ============================================================================

# エピソードタイプ別の基本重要度
BASE_IMPORTANCE: Dict[EpisodeType, float] = {
    EpisodeType.ACHIEVEMENT: 0.8,
    EpisodeType.FAILURE: 0.7,
    EpisodeType.DECISION: 0.6,
    EpisodeType.INTERACTION: 0.4,
    EpisodeType.LEARNING: 0.9,
    EpisodeType.EMOTION: 0.5,
}

# 忘却係数の減衰率（日数あたり）
DECAY_RATE_PER_DAY: float = 0.02

# 想起で重要度を回復する量
RECALL_IMPORTANCE_BOOST: float = 0.05

# 最大想起数
MAX_RECALL_COUNT: int = 5

# キーワード抽出パターン
KEYWORD_PATTERNS: List[Tuple[str, str]] = [
    (r"「([^」]+)」", "quoted"),           # 引用
    (r"【([^】]+)】", "bracketed"),        # 角括弧
    (r"#(\w+)", "hashtag"),               # ハッシュタグ
]

# 重要なキーワード（重要度を上げる）
IMPORTANT_KEYWORDS: Set[str] = {
    "目標", "達成", "完了", "成功", "失敗",
    "問題", "解決", "改善", "学習", "気づき",
    "決定", "決断", "重要", "緊急", "注意",
    "ありがとう", "すごい", "困った", "助けて",
}


# ============================================================================
# メインクラス
# ============================================================================

class EpisodicMemory:
    """
    エピソード記憶システム

    重要な出来事を長期記憶し、関連する場面で想起する。
    """

    def __init__(
        self,
        pool=None,
        organization_id: Optional[str] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
        """
        self.pool = pool
        self.organization_id = organization_id
        self._memory_cache: Dict[str, Episode] = {}
        self._bg_tasks: set = set()  # run_in_executor futureの参照保持（GC防止）
        self._cache_loaded: bool = False  # W-3: 起動時DBキャッシュウォームアップ済みフラグ

        logger.debug(f"EpisodicMemory initialized for org_id={organization_id}")

    # =========================================================================
    # エピソード保存
    # =========================================================================

    def create_episode(
        self,
        episode_type: EpisodeType,
        summary: str,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        emotional_valence: float = 0.0,
        related_entities: Optional[List[RelatedEntity]] = None,
        occurred_at: Optional[datetime] = None,
    ) -> Episode:
        """
        エピソードを作成

        Args:
            episode_type: エピソードの種類
            summary: 要約
            details: 詳細情報
            user_id: ユーザーID（NULLなら組織全体）
            emotional_valence: 感情価（-1.0〜1.0）
            related_entities: 関連エンティティ
            occurred_at: 発生日時

        Returns:
            Episode: 作成されたエピソード
        """
        now = datetime.now(JST)

        # キーワード抽出
        keywords = self._extract_keywords(summary)
        if details:
            for key, value in details.items():
                if isinstance(value, str):
                    keywords.extend(self._extract_keywords(value))
        keywords = list(set(keywords))  # 重複除去

        # 重要度計算
        importance = self._calculate_importance(
            episode_type=episode_type,
            keywords=keywords,
            emotional_valence=emotional_valence,
        )

        # エピソードID生成
        episode_id = self._generate_episode_id(summary, occurred_at or now)

        episode = Episode(
            id=episode_id,
            organization_id=self.organization_id,
            user_id=user_id,
            episode_type=episode_type,
            summary=summary,
            details=details or {},
            emotional_valence=emotional_valence,
            importance_score=importance,
            keywords=keywords,
            related_entities=related_entities or [],
            recall_count=0,
            decay_factor=1.0,
            occurred_at=occurred_at or now,
            created_at=now,
        )

        # キャッシュとDBに保存
        self.save_episode(episode)

        # v11.2.0: CLAUDE.md §9-3「名前・メール・本文をログに記録しない」準拠
        # keywordsには人名（田中さん等）が含まれうるため出力を禁止し件数のみ記録
        logger.info(
            f"Episode created: type={episode_type.value}, "
            f"importance={importance:.2f}, keyword_count={len(keywords)}"
        )

        return episode

    def save_episode(self, episode: Episode) -> bool:
        """
        エピソードをDBに保存（RLS対応・async/syncコンテキスト両対応）

        asyncコンテキストから呼ばれた場合はrun_in_executorでスレッドプールに委譲し、
        syncコンテキストからは直接DB書き込みを行う。
        いずれの場合もキャッシュには先に書き込む。

        Returns:
            bool: 成功したか（キャッシュ保存のみの場合もTrueを返す）
        """
        import asyncio

        # W-3: episode.id の None チェック（DBのNOT NULL制約違反を防ぐ）
        if episode.id is None:
            logger.error("save_episode: episode.id is None, cannot persist to DB")
            return False

        # S-2: organization_id の None チェック（RLSコンテキスト設定に必須）
        if not self.organization_id:
            logger.warning("save_episode: organization_id is None, cannot persist")
            self._memory_cache[episode.id] = episode
            return False

        # キャッシュには必ず保存（DB失敗時のフォールバック）
        self._memory_cache[episode.id] = episode

        if not self.pool:
            logger.warning("No database pool, episode cached only (not persisted)")
            return True

        # C-1: asyncコンテキスト検出（CLAUDE.md §3-2 #6 asyncブロッキング防止）
        try:
            loop = asyncio.get_running_loop()
            # asyncコンテキスト: run_in_executorでスレッドプールに委譲（fire-and-forget）
            future = loop.run_in_executor(None, self._persist_episode_sync, episode)
            self._bg_tasks.add(future)
            future.add_done_callback(self._bg_tasks.discard)
            return True
        except RuntimeError:
            # イベントループなし: syncコンテキスト、直接呼び出し可
            return self._persist_episode_sync(episode)

    def _persist_episode_sync(self, episode: Episode) -> bool:
        """
        エピソードをDBに同期書き込み（RLS対応）

        run_in_executor経由で呼ばれることを前提。
        直接呼び出す場合はイベントループ外（syncコンテキスト）のみ。
        """
        try:
            with self.pool.connect() as conn:
                # RLS対応 — state_manager._connect_with_org_context()と同じパターン
                # (CLAUDE.md §3-2 #9: pg8000はSET文でパラメータ使用不可のためset_config()を使用)
                try:
                    conn.rollback()  # アボート状態をクリア
                except Exception:
                    pass

                conn.execute(
                    sql_text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                    {"org_id": self.organization_id},
                )

                try:
                    conn.execute(
                        sql_text("""
                            INSERT INTO brain_episodes (
                                id, organization_id, user_id,
                                episode_type, summary, details,
                                emotional_valence, importance_score,
                                keywords, embedding_id,
                                recall_count, last_recalled_at, decay_factor,
                                occurred_at, created_at, updated_at
                            ) VALUES (
                                CAST(:id AS uuid),
                                CAST(:organization_id AS uuid),
                                :user_id,
                                :episode_type, :summary, CAST(:details AS jsonb),
                                :emotional_valence, :importance_score,
                                :keywords, :embedding_id,
                                :recall_count, :last_recalled_at, :decay_factor,
                                :occurred_at, :created_at, :updated_at
                            )
                            ON CONFLICT (id) DO UPDATE SET
                                summary = EXCLUDED.summary,
                                details = EXCLUDED.details,
                                emotional_valence = EXCLUDED.emotional_valence,
                                importance_score = EXCLUDED.importance_score,
                                keywords = EXCLUDED.keywords,
                                recall_count = EXCLUDED.recall_count,
                                last_recalled_at = EXCLUDED.last_recalled_at,
                                decay_factor = EXCLUDED.decay_factor,
                                updated_at = EXCLUDED.updated_at
                        """),
                        {
                            "id": episode.id,
                            "organization_id": self.organization_id,
                            "user_id": episode.user_id,
                            "episode_type": (
                                episode.episode_type.value
                                if isinstance(episode.episode_type, EpisodeType)
                                else episode.episode_type
                            ),
                            "summary": episode.summary,
                            "details": json.dumps(episode.details, ensure_ascii=False, default=str),
                            "emotional_valence": episode.emotional_valence,
                            "importance_score": episode.importance_score,
                            "keywords": episode.keywords,
                            "embedding_id": episode.embedding_id,
                            "recall_count": episode.recall_count,
                            "last_recalled_at": episode.last_recalled_at,
                            "decay_factor": episode.decay_factor,
                            "occurred_at": episode.occurred_at,
                            "created_at": episode.created_at,
                            "updated_at": datetime.now(JST),
                        },
                    )
                    conn.commit()
                    logger.debug("Episode persisted to DB: id=%s", episode.id)
                    return True

                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise

                finally:
                    # RLSコンテキストをクリア（org_id残留によるデータ漏洩防止）
                    try:
                        conn.execute(sql_text("SELECT set_config('app.current_organization_id', NULL, false)"))
                    except Exception as reset_err:
                        logger.warning("[RLS] RESET failed: %s", type(reset_err).__name__)
                        try:
                            conn.rollback()
                            conn.execute(sql_text("SELECT set_config('app.current_organization_id', NULL, false)"))
                        except Exception:
                            logger.error("[RLS] RESET retry failed, invalidating connection")
                            try:
                                conn.invalidate()
                            except Exception:
                                pass

        except Exception as e:
            logger.error("Failed to persist episode to DB: %s", type(e).__name__)
            return False

    # =========================================================================
    # エピソード想起
    # =========================================================================

    def recall(
        self,
        message: str,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        max_results: int = MAX_RECALL_COUNT,
    ) -> List[RecallResult]:
        """
        関連するエピソードを想起

        Args:
            message: トリガーとなるメッセージ
            user_id: ユーザーID（指定時はそのユーザーの記憶を優先）
            context: 追加コンテキスト
            max_results: 最大結果数

        Returns:
            List[RecallResult]: 想起されたエピソード
        """
        context = context or {}
        results: List[RecallResult] = []

        # W-3: 起動直後はキャッシュが空のためDBから最新エピソードを読み込む
        # 一度だけ実行（_cache_loaded フラグで制御）
        if not self._cache_loaded and self.pool and self.organization_id:
            self._load_recent_from_db()

        # キーワードマッチング
        keyword_matches = self._recall_by_keywords(message, user_id)
        results.extend(keyword_matches)

        # エンティティマッチング
        entities = context.get("related_entities", [])
        if entities:
            entity_matches = self._recall_by_entities(entities, user_id)
            results.extend(entity_matches)

        # 時間的関連（同じ時期の出来事）
        temporal_matches = self._recall_by_temporal(
            reference_time=context.get("reference_time"),
            user_id=user_id,
        )
        results.extend(temporal_matches)

        # スコアリング・ランキング
        scored_results = self._score_and_rank(results)

        # 上位N件を返す
        top_results = scored_results[:max_results]

        # 想起統計を更新
        self._update_recall_stats(top_results)

        logger.debug(
            f"Recalled {len(top_results)} episodes for message: {message[:50]}..."
        )

        return top_results

    def _recall_by_keywords(
        self,
        message: str,
        user_id: Optional[str] = None,
    ) -> List[RecallResult]:
        """キーワードベースで想起"""
        results = []
        message_keywords = set(self._extract_keywords(message))

        for episode_id, episode in self._memory_cache.items():
            # ユーザーフィルタ
            if user_id and episode.user_id and episode.user_id != user_id:
                continue

            # キーワードマッチ
            episode_keywords = set(episode.keywords)
            matched = message_keywords & episode_keywords

            if matched:
                relevance = len(matched) / max(len(episode_keywords), 1)
                results.append(RecallResult(
                    episode=episode,
                    relevance_score=relevance,
                    trigger=RecallTrigger.KEYWORD,
                    matched_keywords=list(matched),
                    reasoning=f"キーワード一致: {', '.join(matched)}",
                ))

        return results

    def _recall_by_entities(
        self,
        entities: List[Dict[str, str]],
        user_id: Optional[str] = None,
    ) -> List[RecallResult]:
        """エンティティベースで想起"""
        results = []
        entity_ids = {e.get("entity_id") for e in entities if e.get("entity_id")}

        for episode_id, episode in self._memory_cache.items():
            # ユーザーフィルタ
            if user_id and episode.user_id and episode.user_id != user_id:
                continue

            # エンティティマッチ
            episode_entity_ids = {
                e.entity_id for e in episode.related_entities
            }
            matched = entity_ids & episode_entity_ids

            if matched:
                relevance = len(matched) / max(len(episode_entity_ids), 1)
                results.append(RecallResult(
                    episode=episode,
                    relevance_score=relevance * 0.8,  # エンティティは少し重みを下げる
                    trigger=RecallTrigger.ENTITY,
                    reasoning=f"関連エンティティ: {len(matched)}件",
                ))

        return results

    def _recall_by_temporal(
        self,
        reference_time: Optional[datetime] = None,
        user_id: Optional[str] = None,
        days_range: int = 7,
    ) -> List[RecallResult]:
        """時間的関連で想起"""
        results: List[RecallResult] = []
        if not reference_time:
            return results

        time_min = reference_time - timedelta(days=days_range)
        time_max = reference_time + timedelta(days=days_range)

        for episode_id, episode in self._memory_cache.items():
            # ユーザーフィルタ
            if user_id and episode.user_id and episode.user_id != user_id:
                continue

            # 時間範囲チェック
            if episode.occurred_at and time_min <= episode.occurred_at <= time_max:
                # 時間的距離に基づく関連度
                time_diff = abs((episode.occurred_at - reference_time).days)
                relevance = 1.0 - (time_diff / days_range) * 0.5

                results.append(RecallResult(
                    episode=episode,
                    relevance_score=relevance * 0.6,  # 時間関連は重みを下げる
                    trigger=RecallTrigger.TEMPORAL,
                    reasoning=f"時間的関連: {time_diff}日差",
                ))

        return results

    def _score_and_rank(
        self,
        results: List[RecallResult],
    ) -> List[RecallResult]:
        """スコアリングとランキング"""
        # 重複除去（同じエピソードは最高スコアのものを残す）
        episode_best: Dict[str, RecallResult] = {}
        for result in results:
            episode_id = result.episode.id
            if episode_id is None:
                continue
            if episode_id not in episode_best or result.relevance_score > episode_best[episode_id].relevance_score:
                episode_best[episode_id] = result

        # 最終スコア計算
        scored = []
        for result in episode_best.values():
            episode = result.episode
            # 最終スコア = 関連度 × 重要度 × 忘却係数
            final_score = (
                result.relevance_score *
                episode.importance_score *
                episode.decay_factor
            )
            result.relevance_score = final_score
            scored.append(result)

        # スコア降順でソート
        scored.sort(key=lambda x: x.relevance_score, reverse=True)

        return scored

    def _update_recall_stats(self, results: List[RecallResult]):
        """想起統計を更新"""
        now = datetime.now(JST)
        for result in results:
            episode = result.episode
            episode.recall_count += 1
            episode.last_recalled_at = now
            # 想起で重要度を少し回復
            episode.importance_score = min(
                1.0,
                episode.importance_score + RECALL_IMPORTANCE_BOOST
            )

    # =========================================================================
    # 忘却処理
    # =========================================================================

    def apply_decay(self, days_since_creation: int = 1):
        """
        忘却係数を適用

        Args:
            days_since_creation: 作成からの日数
        """
        for episode_id, episode in self._memory_cache.items():
            # 重要度が高いほど忘却しにくい
            effective_decay = DECAY_RATE_PER_DAY * (1.0 - episode.importance_score * 0.5)
            episode.decay_factor = max(
                0.1,  # 最低でも10%は残る
                episode.decay_factor - effective_decay * days_since_creation
            )

    def cleanup_forgotten(self, threshold: float = 0.2):
        """
        忘却されたエピソードを削除

        Args:
            threshold: 削除閾値（これ以下は削除）
        """
        to_remove = [
            episode_id
            for episode_id, episode in self._memory_cache.items()
            if episode.decay_factor < threshold and episode.importance_score < 0.5
        ]

        for episode_id in to_remove:
            del self._memory_cache[episode_id]

        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} forgotten episodes")

    # =========================================================================
    # DBキャッシュウォームアップ（W-3: 起動直後のキャッシュ空問題対策）
    # =========================================================================

    def _load_recent_from_db(self, limit: int = 50) -> None:
        """
        DBから最新エピソードをキャッシュに読み込む（初回呼び出し時のみ）

        Cloud Runは再起動のたびにキャッシュがリセットされるため、
        recall()の初回呼び出し時にDBから最新N件を読み込んでキャッシュを温める。

        Args:
            limit: 読み込む最大件数
        """
        self._cache_loaded = True  # エラーが起きても二重実行しない

        if not self.pool or not self.organization_id:
            return

        try:
            with self.pool.connect() as conn:
                try:
                    conn.rollback()
                except Exception:
                    pass

                conn.execute(
                    sql_text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                    {"org_id": self.organization_id},
                )

                try:
                    rows = conn.execute(
                        sql_text("""
                            SELECT
                                id, organization_id, user_id,
                                episode_type, summary, details,
                                emotional_valence, importance_score,
                                keywords, embedding_id,
                                recall_count, last_recalled_at, decay_factor,
                                occurred_at, created_at
                            FROM brain_episodes
                            WHERE organization_id = CAST(:org_id AS uuid)
                            ORDER BY importance_score DESC, occurred_at DESC
                            LIMIT :limit
                        """),
                        {"org_id": self.organization_id, "limit": limit},
                    ).fetchall()

                    for row in rows:
                        ep_id = str(row[0]) if row[0] else None
                        if not ep_id or ep_id in self._memory_cache:
                            continue

                        # details はJSONB → Python dict
                        details_raw = row[5]
                        if isinstance(details_raw, str):
                            details = json.loads(details_raw)
                        elif isinstance(details_raw, dict):
                            details = details_raw
                        else:
                            details = {}

                        # keywords はARRAY → List[str]
                        keywords = list(row[8]) if row[8] else []

                        episode = Episode(
                            id=ep_id,
                            organization_id=str(row[1]) if row[1] else None,
                            user_id=row[2],
                            episode_type=EpisodeType(row[3]) if row[3] in [e.value for e in EpisodeType] else EpisodeType.INTERACTION,
                            summary=row[4] or "",
                            details=details,
                            emotional_valence=float(row[6]) if row[6] is not None else 0.0,
                            importance_score=float(row[7]) if row[7] is not None else 0.5,
                            keywords=keywords,
                            embedding_id=row[9],
                            recall_count=int(row[10]) if row[10] is not None else 0,
                            last_recalled_at=row[11],
                            decay_factor=float(row[12]) if row[12] is not None else 1.0,
                            occurred_at=row[13],
                            created_at=row[14],
                        )
                        self._memory_cache[ep_id] = episode

                    logger.debug("Loaded %d episodes from DB into cache", len(rows))

                finally:
                    try:
                        conn.execute(sql_text("SELECT set_config('app.current_organization_id', NULL, false)"))
                    except Exception:
                        try:
                            conn.invalidate()
                        except Exception:
                            pass

        except Exception as e:
            logger.warning("Failed to load episodes from DB: %s", type(e).__name__)

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def _extract_keywords(self, text: str) -> List[str]:
        """テキストからキーワードを抽出"""
        keywords = []

        # パターンマッチング
        for pattern, _ in KEYWORD_PATTERNS:
            matches = re.findall(pattern, text)
            keywords.extend(matches)

        # 重要キーワードの検出
        for keyword in IMPORTANT_KEYWORDS:
            if keyword in text:
                keywords.append(keyword)

        # 名詞的なパターン（簡易）
        # 実際にはMeCab等を使う
        noun_pattern = r"[ぁ-んァ-ン一-龥]+(?:さん|くん|様|氏)?"
        nouns = re.findall(noun_pattern, text)
        keywords.extend([n for n in nouns if len(n) >= 2])

        return list(set(keywords))

    def _calculate_importance(
        self,
        episode_type: EpisodeType,
        keywords: List[str],
        emotional_valence: float,
    ) -> float:
        """重要度を計算"""
        # 基本重要度
        base = BASE_IMPORTANCE.get(episode_type, 0.5)

        # 重要キーワードボーナス
        important_count = sum(1 for k in keywords if k in IMPORTANT_KEYWORDS)
        keyword_bonus = min(0.2, important_count * 0.05)

        # 感情的な出来事は重要
        emotion_bonus = abs(emotional_valence) * 0.1

        return min(1.0, base + keyword_bonus + emotion_bonus)

    def _generate_episode_id(self, summary: str, occurred_at: datetime) -> str:
        """エピソードIDを生成（UUID形式 — brain_episodes.id はuuid型）"""
        content = f"{summary}_{occurred_at.isoformat()}"
        return str(uuid5(NAMESPACE_DNS, content))

    # =========================================================================
    # 便利メソッド
    # =========================================================================

    def record_achievement(
        self,
        summary: str,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Episode:
        """達成を記録"""
        return self.create_episode(
            episode_type=EpisodeType.ACHIEVEMENT,
            summary=summary,
            user_id=user_id,
            details=details,
            emotional_valence=0.8,  # ポジティブ
        )

    def record_failure(
        self,
        summary: str,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Episode:
        """失敗を記録"""
        return self.create_episode(
            episode_type=EpisodeType.FAILURE,
            summary=summary,
            user_id=user_id,
            details=details,
            emotional_valence=-0.5,  # ネガティブ
        )

    def record_learning(
        self,
        summary: str,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Episode:
        """学習を記録"""
        return self.create_episode(
            episode_type=EpisodeType.LEARNING,
            summary=summary,
            user_id=user_id,
            details=details,
            emotional_valence=0.3,  # 少しポジティブ
        )

    def get_recent_episodes(
        self,
        user_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        limit: int = 10,
    ) -> List[Episode]:
        """最近のエピソードを取得"""
        episodes = []

        for episode in self._memory_cache.values():
            # フィルタ
            if user_id and episode.user_id != user_id:
                continue
            if episode_type and episode.episode_type != episode_type:
                continue
            episodes.append(episode)

        # 発生日時でソート
        episodes.sort(
            key=lambda x: x.occurred_at or datetime.min.replace(tzinfo=JST),
            reverse=True
        )

        return episodes[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """統計情報を取得"""
        total = len(self._memory_cache)
        by_type: Dict[str, int] = {}
        total_recalls = 0
        avg_importance = 0.0

        for episode in self._memory_cache.values():
            # タイプ別カウント
            type_name = episode.episode_type.value
            by_type[type_name] = by_type.get(type_name, 0) + 1

            # 想起回数
            total_recalls += episode.recall_count

            # 平均重要度
            avg_importance += episode.importance_score

        if total > 0:
            avg_importance /= total

        return {
            "total_episodes": total,
            "by_type": by_type,
            "total_recalls": total_recalls,
            "avg_importance": avg_importance,
        }


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_episodic_memory(
    pool=None,
    organization_id: Optional[str] = None,
) -> EpisodicMemory:
    """EpisodicMemoryのファクトリ関数"""
    return EpisodicMemory(
        pool=pool,
        organization_id=organization_id,
    )
