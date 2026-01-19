"""
ナレッジ検索サービス

Phase 3: ナレッジ検索機能

設計ドキュメント:
    docs/05_phase3_knowledge_detailed_design.md

主な機能:
    - Pineconeベクトル検索
    - アクセス制御（機密区分、部署）
    - 検索ログ記録
    - フィードバック管理
"""

import uuid
import time
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from lib.config import get_settings
from lib.logging import get_logger
from lib.embedding import EmbeddingClient
from lib.pinecone_client import PineconeClient, SearchResult
from api.app.schemas.knowledge import (
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    ChunkResult,
    DocumentMetadata,
    KnowledgeFeedbackRequest,
    KnowledgeFeedbackResponse,
)


logger = get_logger(__name__)
settings = get_settings()


# ================================================================
# データクラス
# ================================================================

@dataclass
class UserContext:
    """ユーザーコンテキスト"""
    user_id: str
    organization_id: str
    department_id: Optional[str] = None
    accessible_classifications: list[str] = None
    accessible_department_ids: list[str] = None

    def __post_init__(self):
        if self.accessible_classifications is None:
            # デフォルト: public と internal にアクセス可能
            self.accessible_classifications = ["public", "internal"]
        if self.accessible_department_ids is None:
            self.accessible_department_ids = []


# ================================================================
# ナレッジ検索サービス
# ================================================================

class KnowledgeSearchService:
    """
    ナレッジ検索サービス

    使用例:
        service = KnowledgeSearchService(db_conn)
        response = await service.search(
            user_context=user_ctx,
            request=search_request
        )
    """

    def __init__(
        self,
        db_conn: AsyncConnection,
        embedding_client: Optional[EmbeddingClient] = None,
        pinecone_client: Optional[PineconeClient] = None,
    ):
        """
        Args:
            db_conn: 非同期DBコネクション
            embedding_client: エンベディングクライアント（省略時は自動生成）
            pinecone_client: Pineconeクライアント（省略時は自動生成）
        """
        self.db_conn = db_conn
        self.embedding_client = embedding_client or EmbeddingClient()
        self.pinecone_client = pinecone_client or PineconeClient()

    async def search(
        self,
        user_context: UserContext,
        request: KnowledgeSearchRequest,
    ) -> KnowledgeSearchResponse:
        """
        ナレッジ検索を実行

        処理フロー:
        1. クエリのエンベディング生成
        2. Pineconeベクトル検索
        3. アクセス制御フィルタ
        4. チャンク情報をDBから取得
        5. 検索ログ記録
        6. レスポンス生成

        Args:
            user_context: ユーザーコンテキスト
            request: 検索リクエスト

        Returns:
            KnowledgeSearchResponse
        """
        start_time = time.time()
        embedding_time_ms = 0
        search_time_ms = 0

        organization_id = user_context.organization_id

        # 1. クエリのエンベディング生成
        embed_start = time.time()
        query_embedding = await self.embedding_client.embed_text(request.query)
        embedding_time_ms = int((time.time() - embed_start) * 1000)

        # 2. Pineconeベクトル検索
        search_start = time.time()

        # メタデータフィルタを構築
        metadata_filter = self._build_metadata_filter(
            user_context=user_context,
            categories=request.categories,
        )

        # top_k を少し多めに取得（アクセス制御でフィルタされる可能性があるため）
        top_k = (request.top_k or settings.KNOWLEDGE_SEARCH_TOP_K) * 2

        search_results = await self.pinecone_client.search(
            organization_id=organization_id,
            query_vector=query_embedding.vector,
            top_k=top_k,
            filters=metadata_filter,
        )
        search_time_ms = int((time.time() - search_start) * 1000)

        # 3. アクセス制御フィルタ（DBから詳細情報を取得しながら）
        filtered_results, filtered_count = await self._filter_by_access_control(
            organization_id=organization_id,
            search_results=search_results.results,
            user_context=user_context,
            max_results=request.top_k or settings.KNOWLEDGE_SEARCH_TOP_K,
        )

        # 4. チャンク情報をDBから取得
        chunk_results = await self._enrich_with_db_data(
            organization_id=organization_id,
            search_results=filtered_results,
            include_content=request.include_content or True,
        )

        # 5. 統計計算
        scores = [r.score for r in filtered_results]
        top_score = max(scores) if scores else None
        average_score = sum(scores) / len(scores) if scores else None

        # 6. 回答拒否判定（MVP要件#8）
        answer_refused = False
        refused_reason = None

        if not chunk_results:
            answer_refused = True
            refused_reason = "no_results"
        elif top_score and top_score < settings.KNOWLEDGE_SEARCH_SCORE_THRESHOLD:
            if settings.KNOWLEDGE_REFUSE_ON_LOW_SCORE:
                answer_refused = True
                refused_reason = "low_confidence"

        # 7. 検索ログ記録
        search_log_id = await self._log_search(
            user_context=user_context,
            request=request,
            chunk_results=chunk_results,
            filtered_results=filtered_results,
            filtered_count=filtered_count,
            top_score=top_score,
            average_score=average_score,
            answer_refused=answer_refused,
            refused_reason=refused_reason,
            embedding_time_ms=embedding_time_ms,
            search_time_ms=search_time_ms,
        )

        total_time_ms = int((time.time() - start_time) * 1000)

        return KnowledgeSearchResponse(
            query=request.query,
            results=chunk_results,
            total_results=len(chunk_results),
            search_log_id=search_log_id,
            top_score=top_score,
            average_score=average_score,
            answer=None,  # 回答生成は Phase 3.5 以降
            answer_refused=answer_refused,
            refused_reason=refused_reason,
            search_time_ms=search_time_ms,
            total_time_ms=total_time_ms,
        )

    def _build_metadata_filter(
        self,
        user_context: UserContext,
        categories: Optional[list[str]] = None,
    ) -> dict:
        """
        Pineconeメタデータフィルタを構築

        Args:
            user_context: ユーザーコンテキスト
            categories: カテゴリフィルタ

        Returns:
            Pineconeフィルタ辞書
        """
        filter_conditions = []

        # 機密区分フィルタ
        if user_context.accessible_classifications:
            filter_conditions.append({
                "classification": {"$in": user_context.accessible_classifications}
            })

        # カテゴリフィルタ
        if categories:
            filter_conditions.append({
                "category": {"$in": categories}
            })

        # 部署フィルタ（Phase 3.5: ENABLE_DEPARTMENT_ACCESS_CONTROL が TRUE の場合）
        if settings.ENABLE_DEPARTMENT_ACCESS_CONTROL:
            if user_context.accessible_department_ids:
                filter_conditions.append({
                    "$or": [
                        {"department_id": ""},  # 部署指定なし
                        {"department_id": {"$in": user_context.accessible_department_ids}}
                    ]
                })

        if len(filter_conditions) == 1:
            return filter_conditions[0]
        elif len(filter_conditions) > 1:
            return {"$and": filter_conditions}
        else:
            return {}

    async def _filter_by_access_control(
        self,
        organization_id: str,
        search_results: list[SearchResult],
        user_context: UserContext,
        max_results: int,
    ) -> tuple[list[SearchResult], int]:
        """
        アクセス制御でフィルタ

        Pineconeのメタデータフィルタだけでは不十分な場合の追加フィルタ。
        DBからドキュメント情報を取得して、詳細なアクセス制御を行う。

        Args:
            organization_id: 組織ID
            search_results: Pinecone検索結果
            user_context: ユーザーコンテキスト
            max_results: 最大結果数

        Returns:
            (フィルタ済み結果, フィルタされた件数)
        """
        filtered = []
        filtered_count = 0

        for result in search_results:
            if len(filtered) >= max_results:
                break

            # メタデータから情報取得
            classification = result.metadata.get("classification", "internal")
            department_id = result.metadata.get("department_id", "")

            # 機密区分チェック
            if classification not in user_context.accessible_classifications:
                filtered_count += 1
                continue

            # 部署チェック（Phase 3.5）
            if settings.ENABLE_DEPARTMENT_ACCESS_CONTROL:
                if classification == "confidential" and department_id:
                    if department_id not in user_context.accessible_department_ids:
                        filtered_count += 1
                        continue

            filtered.append(result)

        return filtered, filtered_count

    async def _enrich_with_db_data(
        self,
        organization_id: str,
        search_results: list[SearchResult],
        include_content: bool,
    ) -> list[ChunkResult]:
        """
        DBからチャンク・ドキュメント情報を取得して結果を補完

        Args:
            organization_id: 組織ID
            search_results: フィルタ済みPinecone検索結果
            include_content: チャンク内容を含めるか

        Returns:
            ChunkResult リスト
        """
        if not search_results:
            return []

        # Pinecone IDのリストを取得
        pinecone_ids = [r.id for r in search_results]

        # PostgreSQL 配列リテラル形式に変換
        ids_str = "'{" + ",".join(f'"{id}"' for id in pinecone_ids) + "}'"

        # DBからチャンク情報を取得
        query = f"""
            SELECT
                dc.id as chunk_id,
                dc.pinecone_id,
                dc.content,
                dc.page_number,
                dc.section_title,
                d.id as document_id,
                d.title,
                d.file_name,
                d.category,
                d.classification,
                d.department_id,
                d.google_drive_web_view_link
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.organization_id = :org_id
              AND dc.pinecone_id = ANY(CAST(:pinecone_ids AS TEXT[]))
              AND dc.is_active = TRUE
              AND d.is_active = TRUE
              AND d.is_searchable = TRUE
              AND d.deleted_at IS NULL
        """

        result = await self.db_conn.execute(
            text(query),
            {
                "org_id": organization_id,
                "pinecone_ids": "{" + ",".join(pinecone_ids) + "}"
            }
        )
        rows = result.fetchall()

        # Pinecone ID をキーにしたマップを作成
        chunk_map = {row[1]: row for row in rows}

        # 検索結果の順序を維持しながら ChunkResult を作成
        chunk_results = []
        for search_result in search_results:
            row = chunk_map.get(search_result.id)
            if row:
                chunk_results.append(ChunkResult(
                    chunk_id=str(row[0]),
                    pinecone_id=row[1],
                    score=search_result.score,
                    content=row[2] if include_content else None,
                    page_number=row[3],
                    section_title=row[4],
                    document=DocumentMetadata(
                        document_id=str(row[5]),
                        title=row[6],
                        file_name=row[7],
                        category=row[8],
                        classification=row[9],
                        department_id=str(row[10]) if row[10] else None,
                        google_drive_web_view_link=row[11],
                    )
                ))

        return chunk_results

    async def _resolve_organization_uuid(self, organization_id: str) -> Optional[str]:
        """
        organization_id (テキスト識別子) から UUID を解決

        Args:
            organization_id: テキスト識別子 (例: org_soulsyncs) または UUID

        Returns:
            UUID文字列、見つからない場合はNone
        """
        # UUIDかテキスト識別子かを判定
        try:
            uuid.UUID(organization_id)
            return organization_id  # 既にUUID形式
        except ValueError:
            pass

        # テキスト識別子からUUIDを取得
        result = await self.db_conn.execute(
            text("SELECT id FROM organizations WHERE organization_id = :org_id"),
            {"org_id": organization_id}
        )
        row = result.fetchone()
        return str(row[0]) if row else None

    async def _resolve_user_uuid(
        self, user_id: str, organization_uuid: str
    ) -> Optional[str]:
        """
        user_id (external_id等) から UUID を解決

        Args:
            user_id: external_id または UUID
            organization_uuid: 組織のUUID

        Returns:
            UUID文字列、見つからない場合はNone
        """
        # UUIDかテキスト識別子かを判定
        try:
            uuid.UUID(user_id)
            return user_id  # 既にUUID形式
        except ValueError:
            pass

        # external_idからUUIDを取得
        result = await self.db_conn.execute(
            text("""
                SELECT id FROM users
                WHERE external_id = :user_id
                  AND organization_id = :org_id
            """),
            {"user_id": user_id, "org_id": organization_uuid}
        )
        row = result.fetchone()
        return str(row[0]) if row else None

    async def _log_search(
        self,
        user_context: UserContext,
        request: KnowledgeSearchRequest,
        chunk_results: list[ChunkResult],
        filtered_results: list[SearchResult],
        filtered_count: int,
        top_score: Optional[float],
        average_score: Optional[float],
        answer_refused: bool,
        refused_reason: Optional[str],
        embedding_time_ms: int,
        search_time_ms: int,
    ) -> str:
        """検索ログを記録"""
        log_id = str(uuid.uuid4())

        # organization_id と user_id をUUIDに解決
        org_uuid = await self._resolve_organization_uuid(user_context.organization_id)
        if not org_uuid:
            logger.warning(
                f"Organization not found: {user_context.organization_id}",
                tenant_id=user_context.organization_id
            )
            return log_id  # ログ記録をスキップ

        user_uuid = await self._resolve_user_uuid(user_context.user_id, org_uuid)
        if not user_uuid:
            logger.warning(
                f"User not found: {user_context.user_id}",
                tenant_id=user_context.organization_id
            )
            return log_id  # ログ記録をスキップ

        # チャンクIDと スコアの配列を作成
        chunk_ids = [str(r.chunk_id) for r in chunk_results]
        scores = [r.score for r in filtered_results]

        # PostgreSQL 配列リテラル形式に変換
        chunk_ids_pg = "{" + ",".join(chunk_ids) + "}" if chunk_ids else "{}"
        scores_pg = "{" + ",".join(str(s) for s in scores) + "}" if scores else "{}"

        query = """
            INSERT INTO knowledge_search_logs (
                id, organization_id, user_id, user_department_id,
                query, query_embedding_model,
                filters,
                result_count, result_chunk_ids, result_scores,
                top_score, average_score,
                answer_refused, refused_reason,
                accessible_classifications, filtered_by_access_control,
                embedding_time_ms, search_time_ms,
                source, source_room_id
            ) VALUES (
                CAST(:id AS UUID), CAST(:org_id AS UUID), CAST(:user_id AS UUID), :dept_id,
                :query, :embed_model,
                CAST(:filters AS jsonb),
                :result_count, CAST(:chunk_ids AS UUID[]), CAST(:scores AS FLOAT[]),
                :top_score, :avg_score,
                :refused, :refused_reason,
                CAST(:classifications AS TEXT[]), :filtered_count,
                :embed_time, :search_time,
                :source, :source_room_id
            )
        """

        import json
        filters_json = json.dumps({
            "categories": request.categories
        }) if request.categories else "{}"

        classifications_pg = "{" + ",".join(user_context.accessible_classifications) + "}"

        await self.db_conn.execute(
            text(query),
            {
                "id": log_id,
                "org_id": org_uuid,
                "user_id": user_uuid,
                "dept_id": None,  # TODO: resolve department_id to UUID
                "query": request.query,
                "embed_model": self.embedding_client.model,
                "filters": filters_json,
                "result_count": len(chunk_results),
                "chunk_ids": chunk_ids_pg,
                "scores": scores_pg,
                "top_score": top_score,
                "avg_score": average_score,
                "refused": answer_refused,
                "refused_reason": refused_reason,
                "classifications": classifications_pg,
                "filtered_count": filtered_count,
                "embed_time": embedding_time_ms,
                "search_time": search_time_ms,
                "source": request.source or "api",
                "source_room_id": request.source_room_id,
            }
        )

        # チャンクの検索ヒット数を更新
        if chunk_ids:
            chunk_ids_for_update = "{" + ",".join(chunk_ids) + "}"
            await self.db_conn.execute(
                text("""
                    UPDATE document_chunks
                    SET search_hit_count = search_hit_count + 1,
                        last_hit_at = NOW()
                    WHERE id = ANY(CAST(:chunk_ids AS UUID[]))
                """),
                {"chunk_ids": chunk_ids_for_update}
            )

        return log_id

    async def submit_feedback(
        self,
        user_context: UserContext,
        request: KnowledgeFeedbackRequest,
    ) -> KnowledgeFeedbackResponse:
        """
        フィードバックを登録

        Args:
            user_context: ユーザーコンテキスト
            request: フィードバックリクエスト

        Returns:
            KnowledgeFeedbackResponse
        """
        feedback_id = str(uuid.uuid4())

        # target_chunk_ids の PostgreSQL 配列リテラル変換
        target_chunk_ids_pg = None
        if request.target_chunk_ids:
            target_chunk_ids_pg = "{" + ",".join(request.target_chunk_ids) + "}"

        query = """
            INSERT INTO knowledge_feedback (
                id, organization_id, search_log_id, user_id,
                feedback_type, rating, comment,
                target_chunk_ids,
                suggested_answer, suggested_source
            ) VALUES (
                :id, :org_id, :search_log_id, :user_id,
                :feedback_type, :rating, :comment,
                CAST(:target_chunk_ids AS UUID[]),
                :suggested_answer, :suggested_source
            )
        """

        await self.db_conn.execute(
            text(query),
            {
                "id": feedback_id,
                "org_id": user_context.organization_id,
                "search_log_id": request.search_log_id,
                "user_id": user_context.user_id,
                "feedback_type": request.feedback_type,
                "rating": request.rating,
                "comment": request.comment,
                "target_chunk_ids": target_chunk_ids_pg,
                "suggested_answer": request.suggested_answer,
                "suggested_source": request.suggested_source,
            }
        )

        # 検索ログの has_feedback フラグを更新
        await self.db_conn.execute(
            text("""
                UPDATE knowledge_search_logs
                SET has_feedback = TRUE,
                    feedback_type = :feedback_type
                WHERE id = :search_log_id
            """),
            {
                "search_log_id": request.search_log_id,
                "feedback_type": request.feedback_type,
            }
        )

        # ドキュメントのフィードバック統計を更新
        if request.target_chunk_ids:
            if request.feedback_type == "helpful":
                await self.db_conn.execute(
                    text("""
                        UPDATE documents d
                        SET feedback_positive_count = feedback_positive_count + 1
                        FROM document_chunks dc
                        WHERE dc.document_id = d.id
                          AND dc.id = ANY(CAST(:chunk_ids AS UUID[]))
                    """),
                    {"chunk_ids": target_chunk_ids_pg}
                )
            elif request.feedback_type in ("not_helpful", "wrong", "incomplete", "outdated"):
                await self.db_conn.execute(
                    text("""
                        UPDATE documents d
                        SET feedback_negative_count = feedback_negative_count + 1
                        FROM document_chunks dc
                        WHERE dc.document_id = d.id
                          AND dc.id = ANY(CAST(:chunk_ids AS UUID[]))
                    """),
                    {"chunk_ids": target_chunk_ids_pg}
                )

        return KnowledgeFeedbackResponse(
            feedback_id=feedback_id,
            status="received",
            message="フィードバックを受け付けました",
        )
