# lib/brain/episodic_memory.py
"""
Ultimate Brain Architecture - Phase 2: エピソード記憶

設計書: docs/19_ultimate_brain_architecture.md
セクション: 4.3 エピソード記憶

重要な出来事を長期記憶し、関連する場面で想起する。
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

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

        # キャッシュに保存
        self._memory_cache[episode_id] = episode

        # v11.2.0: CLAUDE.md §9-3「名前・メール・本文をログに記録しない」準拠
        # keywordsには人名（田中さん等）が含まれうるため出力を禁止し件数のみ記録
        logger.info(
            f"Episode created: type={episode_type.value}, "
            f"importance={importance:.2f}, keyword_count={len(keywords)}"
        )

        return episode

    def save_episode(self, episode: Episode) -> bool:
        """
        エピソードをDBに保存

        Args:
            episode: 保存するエピソード

        Returns:
            bool: 成功したか
        """
        if not self.pool:
            logger.warning("No database pool, episode not persisted")
            return False

        try:
            # DB保存は実装時に追加
            # 現時点ではキャッシュのみ
            if episode.id is not None:
                self._memory_cache[episode.id] = episode
            return True
        except Exception as e:
            logger.error(f"Failed to save episode: {type(e).__name__}")
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
        """エピソードIDを生成"""
        content = f"{summary}_{occurred_at.isoformat()}"
        return hashlib.md5(content.encode()).hexdigest()[:16]

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
