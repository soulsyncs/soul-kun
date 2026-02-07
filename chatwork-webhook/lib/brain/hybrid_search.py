# lib/brain/hybrid_search.py
"""
ハイブリッド検索（ベクトル + キーワード）

Pinecone（ベクトル検索）とPostgreSQL（キーワード検索）を並列実行し、
RRF（Reciprocal Rank Fusion）でスコアを統合する。

OpenClawの「Hybrid Search」アイデアをsoul-kunの設計思想で独自実装。

【設計原則】
- 脳（Brain）を経由: get_relevant_knowledge()の置き換え
- Truth順位準拠: DB（2位）からの検索結果
- 10の鉄則準拠: organization_idフィルタ必須、SQLパラメータ化

【検索フロー】
1. クエリを受け取る
2. 並列実行:
   Path A: クエリ → Embedding → Pinecone（ベクトル検索）
   Path B: クエリ → PostgreSQL ILIKE（キーワード検索）
3. RRFでスコア統合
4. 重複排除 + 上位N件を返す

Author: Claude Code
Created: 2026-02-07
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID

from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================

# RRF定数: k=60はオリジナル論文の推奨値
RRF_K: int = 60

# ベクトル検索の重み（0.0〜1.0）
VECTOR_WEIGHT: float = 0.7

# キーワード検索の重み（= 1.0 - VECTOR_WEIGHT）
KEYWORD_WEIGHT: float = 0.3

# 並列検索のタイムアウト（秒）
SEARCH_TIMEOUT_SECONDS: float = 5.0

# ベクトル検索の最小スコア（これ未満の結果は除外）
MIN_VECTOR_SCORE: float = 0.3

# デフォルトの検索件数
DEFAULT_TOP_K: int = 5

# クエリの最大文字数
MAX_QUERY_LENGTH: int = 500


# =============================================================================
# ユーティリティ
# =============================================================================


def escape_ilike(value: str) -> str:
    """ILIKEメタキャラクタをエスケープ（パターンインジェクション防止）"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# =============================================================================
# データクラス
# =============================================================================


@dataclass
class HybridSearchResult:
    """ハイブリッド検索の個別結果"""
    id: str
    content: str
    title: str
    category: Optional[str] = None
    source: str = "unknown"  # "vector", "keyword", "both"
    vector_score: float = 0.0
    keyword_score: float = 0.0
    hybrid_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "title": self.title,
            "category": self.category,
            "source": self.source,
            "vector_score": self.vector_score,
            "keyword_score": self.keyword_score,
            "hybrid_score": self.hybrid_score,
        }


@dataclass
class HybridSearchResponse:
    """ハイブリッド検索の統合結果"""
    results: List[HybridSearchResult] = field(default_factory=list)
    vector_count: int = 0
    keyword_count: int = 0
    total_count: int = 0
    search_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "vector_count": self.vector_count,
            "keyword_count": self.keyword_count,
            "total_count": self.total_count,
            "search_time_ms": self.search_time_ms,
        }


# =============================================================================
# RRFスコア計算
# =============================================================================


def compute_rrf_score(rank: int, k: int = RRF_K) -> float:
    """
    Reciprocal Rank Fusionスコアを計算

    RRF(d) = 1 / (k + rank)
    kはランキングの安定化パラメータ（論文推奨: 60）

    Args:
        rank: 検索結果の順位（1始まり）
        k: RRFパラメータ

    Returns:
        RRFスコア
    """
    return 1.0 / (k + rank)


def merge_results_rrf(
    vector_results: List[Dict[str, Any]],
    keyword_results: List[Dict[str, Any]],
    vector_weight: float = VECTOR_WEIGHT,
    keyword_weight: float = KEYWORD_WEIGHT,
    top_k: int = DEFAULT_TOP_K,
) -> List[HybridSearchResult]:
    """
    ベクトル検索とキーワード検索の結果をRRFで統合

    Args:
        vector_results: ベクトル検索結果 [{"id": ..., "content": ..., "title": ..., "score": ..., ...}]
        keyword_results: キーワード検索結果 [{"id": ..., "content": ..., "title": ..., ...}]
        vector_weight: ベクトル検索の重み
        keyword_weight: キーワード検索の重み
        top_k: 返す結果数

    Returns:
        統合・ソート済みのHybridSearchResultリスト
    """
    # ID → スコア情報のマッピング
    score_map: Dict[str, Dict[str, Any]] = {}

    # ベクトル検索結果のRRFスコア
    for rank, item in enumerate(vector_results, start=1):
        item_id = str(item.get("id", ""))
        rrf = compute_rrf_score(rank) * vector_weight
        score_map[item_id] = {
            "content": item.get("content", ""),
            "title": item.get("title", ""),
            "category": item.get("category"),
            "vector_rrf": rrf,
            "keyword_rrf": 0.0,
            "vector_score": item.get("score", 0.0),
            "source": "vector",
            "metadata": item.get("metadata", {}),
        }

    # キーワード検索結果のRRFスコア
    for rank, item in enumerate(keyword_results, start=1):
        item_id = str(item.get("id", ""))
        rrf = compute_rrf_score(rank) * keyword_weight

        if item_id in score_map:
            # 両方の検索で見つかった（ブースト）
            score_map[item_id]["keyword_rrf"] = rrf
            score_map[item_id]["source"] = "both"
        else:
            score_map[item_id] = {
                "content": item.get("content", ""),
                "title": item.get("title", ""),
                "category": item.get("category"),
                "vector_rrf": 0.0,
                "keyword_rrf": rrf,
                "vector_score": 0.0,
                "source": "keyword",
                "metadata": item.get("metadata", {}),
            }

    # ハイブリッドスコアを算出してソート
    merged = []
    for item_id, info in score_map.items():
        hybrid_score = info["vector_rrf"] + info["keyword_rrf"]
        merged.append(HybridSearchResult(
            id=item_id,
            content=info["content"],
            title=info["title"],
            category=info["category"],
            source=info["source"],
            vector_score=info["vector_score"],
            keyword_score=info["keyword_rrf"],
            hybrid_score=hybrid_score,
            metadata=info["metadata"],
        ))

    # ハイブリッドスコアで降順ソート
    merged.sort(key=lambda r: r.hybrid_score, reverse=True)

    return merged[:top_k]


# =============================================================================
# ハイブリッドサーチャー
# =============================================================================


class HybridSearcher:
    """
    ベクトル検索 + キーワード検索のハイブリッドサーチャー

    Pinecone（ベクトル）とPostgreSQL（キーワード）を並列実行し、
    RRFでスコアを統合する。
    """

    def __init__(
        self,
        pool,
        org_id: str,
        pinecone_client=None,
        embedding_client=None,
    ):
        """
        Args:
            pool: SQLAlchemyデータベース接続プール
            org_id: 組織ID
            pinecone_client: PineconeClient インスタンス（オプション）
            embedding_client: EmbeddingClient インスタンス（オプション）
        """
        self.pool = pool
        self.org_id = org_id
        self.pinecone_client = pinecone_client
        self.embedding_client = embedding_client

    async def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
    ) -> HybridSearchResponse:
        """
        ハイブリッド検索を実行

        Args:
            query: 検索クエリ
            top_k: 返す結果数

        Returns:
            HybridSearchResponse
        """
        import time
        start = time.monotonic()

        if not query or not query.strip():
            return HybridSearchResponse()

        # クエリ長制限（HIGH-2対応: 過長クエリによるAPI/DBコスト防止）
        query = query.strip()[:MAX_QUERY_LENGTH]

        # ベクトル検索とキーワード検索を並列実行
        vector_task = self._vector_search(query, top_k=top_k * 2)
        keyword_task = self._keyword_search(query, limit=top_k * 2)

        try:
            vector_results, keyword_results = await asyncio.wait_for(
                asyncio.gather(vector_task, keyword_task, return_exceptions=True),
                timeout=SEARCH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Hybrid search timed out after %.1fs", SEARCH_TIMEOUT_SECONDS)
            # タイムアウト時はキーワード検索のみにフォールバック（こちらもタイムアウト保護）
            try:
                keyword_results = await asyncio.wait_for(
                    self._keyword_search(query, limit=top_k),
                    timeout=SEARCH_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                keyword_results = []
            vector_results = []

        # 例外が返された場合は空リストにフォールバック
        if isinstance(vector_results, Exception):
            logger.warning("Vector search failed: %s", vector_results)
            vector_results = []
        if isinstance(keyword_results, Exception):
            logger.warning("Keyword search failed: %s", keyword_results)
            keyword_results = []

        # RRFで統合
        merged = merge_results_rrf(
            vector_results=vector_results,
            keyword_results=keyword_results,
            top_k=top_k,
        )

        elapsed_ms = (time.monotonic() - start) * 1000

        return HybridSearchResponse(
            results=merged,
            vector_count=len(vector_results),
            keyword_count=len(keyword_results),
            total_count=len(merged),
            search_time_ms=round(elapsed_ms, 1),
        )

    async def _vector_search(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Pineconeベクトル検索

        クエリをEmbeddingに変換し、Pineconeで類似度検索する。
        pinecone_client または embedding_client がない場合は空リストを返す。
        """
        if not self.pinecone_client or not self.embedding_client:
            return []

        try:
            # クエリをベクトル化
            embedding_result = await self.embedding_client.embed_query(query)
            query_vector = embedding_result.vector

            # Pinecone検索
            response = await self.pinecone_client.search(
                organization_id=self.org_id,
                query_vector=query_vector,
                top_k=top_k,
            )

            # 最小スコアフィルタ
            results = []
            for r in response.results:
                if r.score < MIN_VECTOR_SCORE:
                    continue
                results.append({
                    "id": r.id,
                    "content": r.metadata.get("content", ""),
                    "title": r.metadata.get("title", ""),
                    "category": r.metadata.get("category"),
                    "score": r.score,
                    "metadata": r.metadata,
                })

            return results

        except Exception as e:
            logger.warning("Vector search error: %s", e)
            return []

    async def _keyword_search(
        self,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        PostgreSQLキーワード検索

        soulkun_knowledgeテーブルとdocument_chunksテーブルの両方を検索する。
        結果はマッチ度に基づいてソートされる。
        同期DB接続をasyncio.to_threadで非ブロッキング化（HIGH-1対応）。
        """
        return await asyncio.to_thread(self._keyword_search_sync, query, limit)

    def _keyword_search_sync(
        self,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """キーワード検索の同期実装（asyncio.to_threadから呼ばれる）"""
        results = []
        # ILIKEメタキャラクタをエスケープ（CRITICAL-2: パターンインジェクション防止）
        escaped_query = escape_ilike(query)

        try:
            with self.pool.connect() as conn:
                # soulkun_knowledge（会社知識）からの検索
                # 注意: このテーブルにはorganization_idがない（Phase 4前の設計）
                # 暫定対応: Phase 4のマイグレーションでorg_idカラム追加予定
                knowledge_results = conn.execute(
                    sql_text("""
                        SELECT
                            id::text,
                            key AS title,
                            value AS content,
                            category
                        FROM soulkun_knowledge
                        WHERE key ILIKE '%' || CAST(:query AS TEXT) || '%' ESCAPE '\\'
                           OR value ILIKE '%' || CAST(:query AS TEXT) || '%' ESCAPE '\\'
                        ORDER BY
                            CASE
                                WHEN key ILIKE CAST(:query AS TEXT) ESCAPE '\\' THEN 1
                                WHEN key ILIKE CAST(:query AS TEXT) || '%' ESCAPE '\\' THEN 2
                                WHEN key ILIKE '%' || CAST(:query AS TEXT) ESCAPE '\\' THEN 3
                                ELSE 4
                            END,
                            id DESC
                        LIMIT :limit
                    """),
                    {"query": escaped_query, "limit": limit},
                )

                for row in knowledge_results.fetchall():
                    results.append({
                        "id": f"knowledge_{row[0]}",
                        "title": row[1] or "",
                        "content": row[2] or "",
                        "category": row[3],
                        "source_table": "soulkun_knowledge",
                    })

                # document_chunks（ドキュメントチャンク）からの検索
                chunks_results = conn.execute(
                    sql_text("""
                        SELECT
                            dc.id::text,
                            COALESCE(dc.section_title, d.title, '') AS title,
                            dc.content,
                            d.category,
                            dc.pinecone_id
                        FROM document_chunks dc
                        JOIN documents d ON d.id = dc.document_id
                        WHERE d.organization_id = (
                            SELECT id FROM organizations WHERE slug = :org_id LIMIT 1
                        )
                        AND d.is_active = true
                        AND d.is_searchable = true
                        AND dc.content ILIKE '%' || CAST(:query AS TEXT) || '%' ESCAPE '\\'
                        ORDER BY dc.search_hit_count DESC, dc.id DESC
                        LIMIT :limit
                    """),
                    {"query": escaped_query, "org_id": self.org_id, "limit": limit},
                )

                for row in chunks_results.fetchall():
                    # HIGH-3対応: pinecone_idがあればそれをIDに使い、
                    # ベクトル検索結果との重複排除を可能にする
                    chunk_id = row[4] if row[4] else f"chunk_{row[0]}"
                    results.append({
                        "id": chunk_id,
                        "title": row[1] or "",
                        "content": row[2] or "",
                        "category": row[3],
                        "source_table": "document_chunks",
                    })

        except Exception as e:
            logger.warning("Keyword search error: %s", e)

        return results
