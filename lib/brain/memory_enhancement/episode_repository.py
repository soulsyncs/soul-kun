"""
Phase 2G: 記憶の強化（Memory Enhancement）- エピソードリポジトリ

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2G

エピソード記憶のDB永続化を担当するリポジトリクラス。
既存のepisodic_memory.pyのメモリキャッシュ版を拡張し、
PostgreSQLでの永続化を実現する。
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .constants import (
    BASE_IMPORTANCE,
    DECAY_RATE_PER_DAY,
    FORGET_THRESHOLD,
    IMPORTANT_KEYWORDS,
    KEYWORD_PATTERNS,
    MAX_RECALL_COUNT,
    MIN_IMPORTANCE_FOR_RETENTION,
    RECALL_IMPORTANCE_BOOST,
    RECALL_RELEVANCE_THRESHOLD,
    TABLE_BRAIN_EPISODES,
    TABLE_BRAIN_EPISODE_ENTITIES,
    EpisodeType,
    RecallTrigger,
)
from .models import Episode, RecallResult, RelatedEntity


logger = logging.getLogger(__name__)


class EpisodeRepository:
    """エピソードリポジトリ

    エピソード記憶のCRUD操作とDB永続化を担当。

    使用例:
        repo = EpisodeRepository(organization_id)

        # エピソード保存
        episode_id = repo.save(conn, episode)

        # キーワード検索
        episodes = repo.find_by_keywords(conn, ["目標", "達成"])

        # 想起
        results = repo.recall(conn, message, user_id)
    """

    def __init__(self, organization_id: str):
        """初期化

        Args:
            organization_id: 組織ID
        """
        self.organization_id = organization_id

    # =========================================================================
    # 保存・更新
    # =========================================================================

    def save(self, conn: Connection, episode: Episode) -> str:
        """エピソードを保存

        Args:
            conn: DB接続
            episode: 保存するエピソード

        Returns:
            エピソードID
        """
        if episode.id is None:
            episode.id = str(uuid4())

        now = datetime.now()

        # エピソード本体を保存
        query = text(f"""
            INSERT INTO {TABLE_BRAIN_EPISODES} (
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
        """)

        try:
            conn.execute(query, {
                "id": episode.id,
                "organization_id": self.organization_id,
                "user_id": episode.user_id,
                "episode_type": episode.episode_type.value if isinstance(episode.episode_type, EpisodeType) else episode.episode_type,
                "summary": episode.summary,
                "details": json.dumps(episode.details, ensure_ascii=False, default=str),
                "emotional_valence": episode.emotional_valence,
                "importance_score": episode.importance_score,
                "keywords": episode.keywords,
                "embedding_id": episode.embedding_id,
                "recall_count": episode.recall_count,
                "last_recalled_at": episode.last_recalled_at,
                "decay_factor": episode.decay_factor,
                "occurred_at": episode.occurred_at or now,
                "created_at": episode.created_at or now,
                "updated_at": now,
            })

            # 関連エンティティを保存
            if episode.related_entities:
                self._save_entities(conn, episode.id, episode.related_entities)

            logger.info(f"Episode saved: {episode.id}")
            return episode.id

        except Exception as e:
            logger.error(f"Failed to save episode: {e}")
            raise

    def _save_entities(
        self,
        conn: Connection,
        episode_id: str,
        entities: List[RelatedEntity],
    ):
        """関連エンティティを保存"""
        # 既存を削除
        delete_query = text(f"""
            DELETE FROM {TABLE_BRAIN_EPISODE_ENTITIES}
            WHERE episode_id = CAST(:episode_id AS uuid)
        """)
        conn.execute(delete_query, {"episode_id": episode_id})

        # 新規を挿入
        if not entities:
            return

        insert_query = text(f"""
            INSERT INTO {TABLE_BRAIN_EPISODE_ENTITIES} (
                id, episode_id, entity_type, entity_id,
                entity_name, relationship, created_at
            ) VALUES (
                CAST(:id AS uuid),
                CAST(:episode_id AS uuid),
                :entity_type, :entity_id,
                :entity_name, :relationship, :created_at
            )
        """)

        now = datetime.now()
        for entity in entities:
            conn.execute(insert_query, {
                "id": str(uuid4()),
                "episode_id": episode_id,
                "entity_type": entity.entity_type.value if hasattr(entity.entity_type, 'value') else entity.entity_type,
                "entity_id": entity.entity_id,
                "entity_name": entity.entity_name,
                "relationship": entity.relationship.value if hasattr(entity.relationship, 'value') else entity.relationship,
                "created_at": now,
            })

    def update_recall_stats(
        self,
        conn: Connection,
        episode_id: str,
        boost_importance: bool = True,
    ) -> bool:
        """想起統計を更新

        Args:
            conn: DB接続
            episode_id: エピソードID
            boost_importance: 重要度を上げるか

        Returns:
            成功したか
        """
        importance_clause = ""
        if boost_importance:
            importance_clause = f", importance_score = LEAST(1.0, importance_score + {RECALL_IMPORTANCE_BOOST})"

        query = text(f"""
            UPDATE {TABLE_BRAIN_EPISODES}
            SET recall_count = recall_count + 1,
                last_recalled_at = :now,
                updated_at = :now
                {importance_clause}
            WHERE id = CAST(:episode_id AS uuid)
              AND organization_id = CAST(:organization_id AS uuid)
        """)

        try:
            result = conn.execute(query, {
                "episode_id": episode_id,
                "organization_id": self.organization_id,
                "now": datetime.now(),
            })
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to update recall stats: {e}")
            return False

    def apply_decay(
        self,
        conn: Connection,
        days: int = 1,
    ) -> int:
        """忘却係数を適用

        Args:
            conn: DB接続
            days: 経過日数

        Returns:
            更新件数
        """
        # 重要度が高いほど忘却しにくい
        # effective_decay = DECAY_RATE_PER_DAY * (1.0 - importance_score * 0.5)
        query = text(f"""
            UPDATE {TABLE_BRAIN_EPISODES}
            SET decay_factor = GREATEST(
                    0.1,
                    decay_factor - ({DECAY_RATE_PER_DAY} * (1.0 - importance_score * 0.5) * :days)
                ),
                updated_at = :now
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND decay_factor > 0.1
        """)

        try:
            result = conn.execute(query, {
                "organization_id": self.organization_id,
                "days": days,
                "now": datetime.now(),
            })
            count = result.rowcount
            if count > 0:
                logger.info(f"Applied decay to {count} episodes")
            return count
        except Exception as e:
            logger.error(f"Failed to apply decay: {e}")
            return 0

    def delete_forgotten(self, conn: Connection) -> int:
        """忘却されたエピソードを削除

        Args:
            conn: DB接続

        Returns:
            削除件数
        """
        query = text(f"""
            DELETE FROM {TABLE_BRAIN_EPISODES}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND decay_factor < :forget_threshold
              AND importance_score < :min_importance
        """)

        try:
            result = conn.execute(query, {
                "organization_id": self.organization_id,
                "forget_threshold": FORGET_THRESHOLD,
                "min_importance": MIN_IMPORTANCE_FOR_RETENTION,
            })
            count = result.rowcount
            if count > 0:
                logger.info(f"Deleted {count} forgotten episodes")
            return count
        except Exception as e:
            logger.error(f"Failed to delete forgotten episodes: {e}")
            return 0

    # =========================================================================
    # 検索
    # =========================================================================

    def find_by_id(
        self,
        conn: Connection,
        episode_id: str,
    ) -> Optional[Episode]:
        """IDでエピソードを取得

        Args:
            conn: DB接続
            episode_id: エピソードID

        Returns:
            エピソード（見つからない場合はNone）
        """
        query = text(f"""
            SELECT
                id, organization_id, user_id,
                episode_type, summary, details,
                emotional_valence, importance_score,
                keywords, embedding_id,
                recall_count, last_recalled_at, decay_factor,
                occurred_at, created_at, updated_at
            FROM {TABLE_BRAIN_EPISODES}
            WHERE id = CAST(:episode_id AS uuid)
              AND organization_id = CAST(:organization_id AS uuid)
        """)

        try:
            result = conn.execute(query, {
                "episode_id": episode_id,
                "organization_id": self.organization_id,
            })
            row = result.fetchone()
            if row:
                episode = self._row_to_episode(row)
                episode.related_entities = self._load_entities(conn, episode_id)
                return episode
            return None
        except Exception as e:
            logger.error(f"Failed to find episode by id: {e}")
            return None

    def find_by_keywords(
        self,
        conn: Connection,
        keywords: List[str],
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Episode]:
        """キーワードでエピソードを検索

        Args:
            conn: DB接続
            keywords: 検索キーワード
            user_id: ユーザーID（指定時はそのユーザーの記憶を優先）
            limit: 最大件数

        Returns:
            エピソードリスト
        """
        if not keywords:
            return []

        user_clause = ""
        if user_id:
            user_clause = "AND (user_id = :user_id OR user_id IS NULL)"

        query = text(f"""
            SELECT
                id, organization_id, user_id,
                episode_type, summary, details,
                emotional_valence, importance_score,
                keywords, embedding_id,
                recall_count, last_recalled_at, decay_factor,
                occurred_at, created_at, updated_at
            FROM {TABLE_BRAIN_EPISODES}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND keywords && :keywords
              {user_clause}
            ORDER BY importance_score * decay_factor DESC
            LIMIT :limit
        """)

        try:
            params = {
                "organization_id": self.organization_id,
                "keywords": keywords,
                "limit": limit,
            }
            if user_id:
                params["user_id"] = user_id

            result = conn.execute(query, params)
            return [self._row_to_episode(row) for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Failed to find episodes by keywords: {e}")
            return []

    def find_by_entities(
        self,
        conn: Connection,
        entity_ids: List[str],
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Episode]:
        """関連エンティティでエピソードを検索

        Args:
            conn: DB接続
            entity_ids: エンティティIDリスト
            user_id: ユーザーID
            limit: 最大件数

        Returns:
            エピソードリスト
        """
        if not entity_ids:
            return []

        user_clause = ""
        if user_id:
            user_clause = "AND (e.user_id = :user_id OR e.user_id IS NULL)"

        query = text(f"""
            SELECT DISTINCT
                e.id, e.organization_id, e.user_id,
                e.episode_type, e.summary, e.details,
                e.emotional_valence, e.importance_score,
                e.keywords, e.embedding_id,
                e.recall_count, e.last_recalled_at, e.decay_factor,
                e.occurred_at, e.created_at, e.updated_at
            FROM {TABLE_BRAIN_EPISODES} e
            JOIN {TABLE_BRAIN_EPISODE_ENTITIES} ee ON e.id = ee.episode_id
            WHERE e.organization_id = CAST(:organization_id AS uuid)
              AND ee.entity_id = ANY(:entity_ids)
              {user_clause}
            ORDER BY e.importance_score * e.decay_factor DESC
            LIMIT :limit
        """)

        try:
            params = {
                "organization_id": self.organization_id,
                "entity_ids": entity_ids,
                "limit": limit,
            }
            if user_id:
                params["user_id"] = user_id

            result = conn.execute(query, params)
            return [self._row_to_episode(row) for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Failed to find episodes by entities: {e}")
            return []

    def find_by_time_range(
        self,
        conn: Connection,
        start: datetime,
        end: datetime,
        user_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        limit: int = 100,
    ) -> List[Episode]:
        """時間範囲でエピソードを検索

        Args:
            conn: DB接続
            start: 開始日時
            end: 終了日時
            user_id: ユーザーID
            episode_type: エピソードタイプ
            limit: 最大件数

        Returns:
            エピソードリスト
        """
        user_clause = ""
        if user_id:
            user_clause = "AND (user_id = :user_id OR user_id IS NULL)"

        type_clause = ""
        if episode_type:
            type_clause = "AND episode_type = :episode_type"

        query = text(f"""
            SELECT
                id, organization_id, user_id,
                episode_type, summary, details,
                emotional_valence, importance_score,
                keywords, embedding_id,
                recall_count, last_recalled_at, decay_factor,
                occurred_at, created_at, updated_at
            FROM {TABLE_BRAIN_EPISODES}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND occurred_at BETWEEN :start AND :end
              {user_clause}
              {type_clause}
            ORDER BY occurred_at DESC
            LIMIT :limit
        """)

        try:
            params = {
                "organization_id": self.organization_id,
                "start": start,
                "end": end,
                "limit": limit,
            }
            if user_id:
                params["user_id"] = user_id
            if episode_type:
                params["episode_type"] = episode_type.value if isinstance(episode_type, EpisodeType) else episode_type

            result = conn.execute(query, params)
            return [self._row_to_episode(row) for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Failed to find episodes by time range: {e}")
            return []

    def find_similar(
        self,
        conn: Connection,
        episode: Episode,
        threshold: float = 0.5,
        limit: int = 10,
    ) -> List[Tuple[Episode, float]]:
        """類似エピソードを検索

        キーワードの重複度で類似度を計算。

        Args:
            conn: DB接続
            episode: 基準エピソード
            threshold: 類似度閾値
            limit: 最大件数

        Returns:
            (エピソード, 類似度)のリスト
        """
        if not episode.keywords:
            return []

        query = text(f"""
            SELECT
                id, organization_id, user_id,
                episode_type, summary, details,
                emotional_valence, importance_score,
                keywords, embedding_id,
                recall_count, last_recalled_at, decay_factor,
                occurred_at, created_at, updated_at,
                (
                    SELECT COUNT(*)::float
                    FROM unnest(keywords) k
                    WHERE k = ANY(:keywords)
                ) / GREATEST(array_length(keywords, 1), 1)::float AS similarity
            FROM {TABLE_BRAIN_EPISODES}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND id != CAST(:episode_id AS uuid)
              AND keywords && :keywords
            ORDER BY similarity DESC
            LIMIT :limit
        """)

        try:
            result = conn.execute(query, {
                "organization_id": self.organization_id,
                "episode_id": episode.id,
                "keywords": episode.keywords,
                "limit": limit,
            })

            results = []
            for row in result.fetchall():
                ep = self._row_to_episode(row[:-1])  # 最後の列はsimilarity
                similarity = row[-1]
                if similarity >= threshold:
                    results.append((ep, similarity))
            return results
        except Exception as e:
            logger.error(f"Failed to find similar episodes: {e}")
            return []

    def find_recent(
        self,
        conn: Connection,
        user_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        limit: int = 20,
    ) -> List[Episode]:
        """最近のエピソードを取得

        Args:
            conn: DB接続
            user_id: ユーザーID
            episode_type: エピソードタイプ
            limit: 最大件数

        Returns:
            エピソードリスト
        """
        user_clause = ""
        if user_id:
            user_clause = "AND (user_id = :user_id OR user_id IS NULL)"

        type_clause = ""
        if episode_type:
            type_clause = "AND episode_type = :episode_type"

        query = text(f"""
            SELECT
                id, organization_id, user_id,
                episode_type, summary, details,
                emotional_valence, importance_score,
                keywords, embedding_id,
                recall_count, last_recalled_at, decay_factor,
                occurred_at, created_at, updated_at
            FROM {TABLE_BRAIN_EPISODES}
            WHERE organization_id = CAST(:organization_id AS uuid)
              {user_clause}
              {type_clause}
            ORDER BY occurred_at DESC
            LIMIT :limit
        """)

        try:
            params = {
                "organization_id": self.organization_id,
                "limit": limit,
            }
            if user_id:
                params["user_id"] = user_id
            if episode_type:
                params["episode_type"] = episode_type.value if isinstance(episode_type, EpisodeType) else episode_type

            result = conn.execute(query, params)
            return [self._row_to_episode(row) for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Failed to find recent episodes: {e}")
            return []

    # =========================================================================
    # 想起
    # =========================================================================

    def recall(
        self,
        conn: Connection,
        message: str,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        max_results: int = MAX_RECALL_COUNT,
    ) -> List[RecallResult]:
        """関連するエピソードを想起

        Args:
            conn: DB接続
            message: トリガーとなるメッセージ
            user_id: ユーザーID
            context: 追加コンテキスト
            max_results: 最大結果数

        Returns:
            想起結果リスト
        """
        context = context or {}
        results: List[RecallResult] = []

        # キーワード抽出
        keywords = self._extract_keywords(message)

        # キーワードマッチング
        if keywords:
            keyword_matches = self._recall_by_keywords(conn, keywords, user_id)
            results.extend(keyword_matches)

        # エンティティマッチング
        entity_ids = context.get("entity_ids", [])
        if entity_ids:
            entity_matches = self._recall_by_entities(conn, entity_ids, user_id)
            results.extend(entity_matches)

        # 時間的関連
        reference_time = context.get("reference_time")
        if reference_time:
            temporal_matches = self._recall_by_temporal(conn, reference_time, user_id)
            results.extend(temporal_matches)

        # スコアリング・ランキング・重複除去
        ranked = self._rank_results(results)

        # 上位N件
        top_results = ranked[:max_results]

        # 想起統計を更新
        for result in top_results:
            if result.episode.id is not None:
                self.update_recall_stats(conn, result.episode.id)

        logger.debug(f"Recalled {len(top_results)} episodes for: {message[:50]}...")
        return top_results

    def _recall_by_keywords(
        self,
        conn: Connection,
        keywords: List[str],
        user_id: Optional[str] = None,
    ) -> List[RecallResult]:
        """キーワードベースで想起"""
        episodes = self.find_by_keywords(conn, keywords, user_id, limit=20)
        results = []

        keyword_set = set(keywords)
        for episode in episodes:
            episode_keywords = set(episode.keywords)
            matched = keyword_set & episode_keywords
            if matched:
                relevance = len(matched) / max(len(episode_keywords), 1)
                results.append(RecallResult(
                    episode=episode,
                    relevance_score=relevance,
                    trigger=RecallTrigger.KEYWORD,
                    matched_keywords=list(matched),
                    reasoning=f"キーワード一致: {', '.join(list(matched)[:3])}",
                ))

        return results

    def _recall_by_entities(
        self,
        conn: Connection,
        entity_ids: List[str],
        user_id: Optional[str] = None,
    ) -> List[RecallResult]:
        """エンティティベースで想起"""
        episodes = self.find_by_entities(conn, entity_ids, user_id, limit=20)
        results = []

        for episode in episodes:
            episode_entity_ids = [e.entity_id for e in episode.related_entities]
            matched = set(entity_ids) & set(episode_entity_ids)
            if matched:
                relevance = len(matched) / max(len(episode_entity_ids), 1) * 0.8
                results.append(RecallResult(
                    episode=episode,
                    relevance_score=relevance,
                    trigger=RecallTrigger.ENTITY,
                    matched_entities=list(matched),
                    reasoning=f"関連エンティティ: {len(matched)}件",
                ))

        return results

    def _recall_by_temporal(
        self,
        conn: Connection,
        reference_time: datetime,
        user_id: Optional[str] = None,
        days_range: int = 7,
    ) -> List[RecallResult]:
        """時間的関連で想起"""
        start = reference_time - timedelta(days=days_range)
        end = reference_time + timedelta(days=days_range)

        episodes = self.find_by_time_range(conn, start, end, user_id, limit=20)
        results = []

        for episode in episodes:
            if episode.occurred_at:
                time_diff = abs((episode.occurred_at - reference_time).days)
                relevance = (1.0 - time_diff / days_range) * 0.6
                if relevance > 0:
                    results.append(RecallResult(
                        episode=episode,
                        relevance_score=relevance,
                        trigger=RecallTrigger.TEMPORAL,
                        reasoning=f"時間的関連: {time_diff}日差",
                    ))

        return results

    def _rank_results(
        self,
        results: List[RecallResult],
    ) -> List[RecallResult]:
        """結果をランキング"""
        # 重複除去（同じエピソードは最高スコアのものを残す）
        best_by_episode: Dict[str, RecallResult] = {}
        for result in results:
            episode_id = result.episode.id
            if episode_id is None:
                continue
            if episode_id not in best_by_episode:
                best_by_episode[episode_id] = result
            elif result.relevance_score > best_by_episode[episode_id].relevance_score:
                best_by_episode[episode_id] = result

        # 最終スコア計算
        ranked = []
        for result in best_by_episode.values():
            # final_scoreを使用（relevance × effective_importance）
            if result.final_score >= RECALL_RELEVANCE_THRESHOLD:
                ranked.append(result)

        # スコア降順でソート
        ranked.sort(key=lambda x: x.final_score, reverse=True)
        return ranked

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
        noun_pattern = r"[ぁ-んァ-ン一-龥]+(?:さん|くん|様|氏)?"
        nouns = re.findall(noun_pattern, text)
        keywords.extend([n for n in nouns if len(n) >= 2])

        return list(set(keywords))

    def _row_to_episode(self, row) -> Episode:
        """DBの行をEpisodeに変換"""
        return Episode(
            id=str(row[0]),
            organization_id=str(row[1]) if row[1] else None,
            user_id=row[2],
            episode_type=EpisodeType(row[3]) if row[3] else EpisodeType.INTERACTION,
            summary=row[4] or "",
            details=row[5] if isinstance(row[5], dict) else {},
            emotional_valence=float(row[6]) if row[6] else 0.0,
            importance_score=float(row[7]) if row[7] else 0.5,
            keywords=list(row[8]) if row[8] else [],
            embedding_id=row[9],
            recall_count=row[10] or 0,
            last_recalled_at=row[11],
            decay_factor=float(row[12]) if row[12] else 1.0,
            occurred_at=row[13],
            created_at=row[14],
            updated_at=row[15],
        )

    def _load_entities(
        self,
        conn: Connection,
        episode_id: str,
    ) -> List[RelatedEntity]:
        """関連エンティティを読み込み"""
        query = text(f"""
            SELECT entity_type, entity_id, entity_name, relationship
            FROM {TABLE_BRAIN_EPISODE_ENTITIES}
            WHERE episode_id = CAST(:episode_id AS uuid)
        """)

        try:
            result = conn.execute(query, {"episode_id": episode_id})
            entities = []
            for row in result.fetchall():
                entities.append(RelatedEntity(
                    entity_type=row[0],
                    entity_id=row[1],
                    entity_name=row[2],
                    relationship=row[3],
                ))
            return entities
        except Exception as e:
            logger.warning(f"Failed to load entities: {e}")
            return []

    # =========================================================================
    # 統計
    # =========================================================================

    def get_statistics(
        self,
        conn: Connection,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """統計を取得

        Args:
            conn: DB接続
            user_id: ユーザーID

        Returns:
            統計情報
        """
        user_clause = ""
        if user_id:
            user_clause = "AND (user_id = :user_id OR user_id IS NULL)"

        query = text(f"""
            SELECT
                COUNT(*) AS total,
                AVG(importance_score) AS avg_importance,
                AVG(decay_factor) AS avg_decay,
                SUM(recall_count) AS total_recalls,
                episode_type,
                COUNT(*) AS type_count
            FROM {TABLE_BRAIN_EPISODES}
            WHERE organization_id = CAST(:organization_id AS uuid)
              {user_clause}
            GROUP BY episode_type
        """)

        try:
            params = {"organization_id": self.organization_id}
            if user_id:
                params["user_id"] = user_id

            result = conn.execute(query, params)
            rows = result.fetchall()

            total = 0
            avg_importance = 0.0
            avg_decay = 0.0
            total_recalls = 0
            by_type = {}

            for row in rows:
                total += row[5]
                if row[1]:
                    avg_importance = float(row[1])
                if row[2]:
                    avg_decay = float(row[2])
                if row[3]:
                    total_recalls = int(row[3])
                by_type[row[4]] = row[5]

            return {
                "total_episodes": total,
                "by_type": by_type,
                "avg_importance": avg_importance,
                "avg_decay": avg_decay,
                "total_recalls": total_recalls,
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {
                "total_episodes": 0,
                "by_type": {},
                "avg_importance": 0.0,
                "avg_decay": 0.0,
                "total_recalls": 0,
            }


def create_episode_repository(organization_id: str) -> EpisodeRepository:
    """EpisodeRepositoryのファクトリ関数

    Args:
        organization_id: 組織ID

    Returns:
        EpisodeRepository
    """
    return EpisodeRepository(organization_id)
