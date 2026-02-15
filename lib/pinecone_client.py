"""
Pinecone ベクターDB 連携モジュール

ナレッジ検索のためのベクターデータベース操作を提供します。

使用例:
    from lib.pinecone_client import PineconeClient

    client = PineconeClient()

    # ベクターをupsert
    await client.upsert_vectors(
        organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
        vectors=[{"id": "chunk_001", "values": [...], "metadata": {...}}]
    )

    # 検索
    results = await client.search(
        organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
        query_vector=[...],
        filters={"classification": {"$in": ["public", "internal"]}}
    )

設計ドキュメント:
    docs/05_phase3_knowledge_detailed_design.md
"""

import os
import asyncio
from typing import Optional, Any
from dataclasses import dataclass, field
import logging

from pinecone import Pinecone, ServerlessSpec

from lib.config import get_settings
from lib.secrets import get_secret


logger = logging.getLogger(__name__)


# ================================================================
# データクラス定義
# ================================================================

@dataclass
class SearchResult:
    """検索結果"""
    id: str
    score: float
    metadata: dict = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        """チャンクID（pinecone_id）"""
        return self.id

    @property
    def document_id(self) -> Optional[str]:
        """ドキュメントID（メタデータから取得）"""
        return self.metadata.get('document_id')


@dataclass
class SearchResponse:
    """検索レスポンス"""
    results: list[SearchResult]
    total_count: int
    namespace: str

    @property
    def top_score(self) -> Optional[float]:
        """最高スコア"""
        if self.results:
            return self.results[0].score
        return None

    @property
    def average_score(self) -> Optional[float]:
        """平均スコア"""
        if self.results:
            return sum(r.score for r in self.results) / len(self.results)
        return None


# ================================================================
# Pinecone クライアント
# ================================================================

class PineconeClient:
    """
    Pinecone ベクターDBクライアント

    使用例:
        client = PineconeClient()

        # インデックス情報
        stats = await client.describe_index_stats("5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        # ベクターをupsert
        await client.upsert_vectors(
            organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
            vectors=[
                {
                    "id": "org_soulsyncs_doc123_v1_chunk0",
                    "values": [0.1, 0.2, ...],  # 768次元（Gemini Embedding）
                    "metadata": {
                        "document_id": "doc123",
                        "classification": "internal",
                        "category": "B",
                        "title": "経費精算マニュアル"
                    }
                }
            ]
        )

        # 検索
        results = await client.search(
            organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
            query_vector=[0.1, 0.2, ...],
            top_k=5,
            filters={"classification": {"$in": ["public", "internal"]}}
        )
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        index_name: Optional[str] = None,
    ):
        """
        Args:
            api_key: Pinecone APIキー（未指定時は環境変数またはSecret Managerから取得）
            index_name: インデックス名（未指定時は設定から取得）
        """
        self.settings = get_settings()

        # APIキーの取得
        if api_key:
            self._api_key = api_key
        else:
            self._api_key = os.getenv('PINECONE_API_KEY')
            if not self._api_key:
                try:
                    self._api_key = get_secret('PINECONE_API_KEY')
                except Exception as e:
                    logger.warning(f"Failed to get PINECONE_API_KEY from Secret Manager: {e}")
                    raise ValueError(
                        "Pinecone APIキーが設定されていません。"
                        "環境変数 PINECONE_API_KEY または Secret Manager で設定してください。"
                    ) from e

        # インデックス名
        self.index_name = index_name or self.settings.PINECONE_INDEX_NAME

        # Pineconeクライアントの初期化
        self.pc = Pinecone(api_key=self._api_key)
        self._index = None

    @property
    def index(self):
        """インデックスを取得（遅延初期化）"""
        if self._index is None:
            self._index = self.pc.Index(self.index_name)
        return self._index

    # ================================================================
    # Namespace
    # ================================================================

    def get_namespace(self, organization_id: str) -> str:
        """
        組織IDからnamespaceを生成

        フォーマット: org_{organization_id}
        例: org_soulsyncs
        """
        return f"org_{organization_id}"

    # ================================================================
    # インデックス操作
    # ================================================================

    async def create_index_if_not_exists(
        self,
        dimension: int = 768,
        metric: str = "cosine",
    ) -> bool:
        """
        インデックスが存在しない場合に作成

        Args:
            dimension: ベクターの次元数（Gemini text-embedding-004: 768）
            metric: 距離メトリック（cosine, euclidean, dotproduct）

        Returns:
            作成された場合はTrue

        Note:
            v10.12.0: OpenAI (1536) → Gemini (768) に変更
        """
        loop = asyncio.get_event_loop()

        # 既存のインデックスを確認
        existing_indexes = await loop.run_in_executor(
            None,
            lambda: [idx.name for idx in self.pc.list_indexes()]
        )

        if self.index_name in existing_indexes:
            logger.info(f"インデックス '{self.index_name}' は既に存在します")
            return False

        # インデックスを作成
        await loop.run_in_executor(
            None,
            lambda: self.pc.create_index(
                name=self.index_name,
                dimension=dimension,
                metric=metric,
                spec=ServerlessSpec(
                    cloud="aws",
                    region="us-east-1"
                )
            )
        )

        logger.info(f"インデックス '{self.index_name}' を作成しました")
        return True

    async def describe_index_stats(
        self,
        organization_id: Optional[str] = None
    ) -> dict:
        """
        インデックスの統計情報を取得

        Args:
            organization_id: 指定時はそのnamespaceのみの統計

        Returns:
            統計情報の辞書
        """
        loop = asyncio.get_event_loop()

        if organization_id:
            namespace = self.get_namespace(organization_id)
            stats = await loop.run_in_executor(
                None,
                lambda: self.index.describe_index_stats(
                    filter=None
                )
            )
            # 特定のnamespaceの情報を抽出
            ns_stats = stats.namespaces.get(namespace, {})
            return {
                "namespace": namespace,
                "vector_count": ns_stats.get("vector_count", 0),
                "dimension": stats.dimension,
            }
        else:
            stats = await loop.run_in_executor(
                None,
                lambda: self.index.describe_index_stats()
            )
            return {
                "total_vector_count": stats.total_vector_count,
                "dimension": stats.dimension,
                "namespaces": {
                    ns: {"vector_count": data.vector_count}
                    for ns, data in stats.namespaces.items()
                }
            }

    # ================================================================
    # ベクター操作
    # ================================================================

    async def upsert_vectors(
        self,
        organization_id: str,
        vectors: list[dict],
        batch_size: int = 100,
    ) -> int:
        """
        ベクターをupsert

        Args:
            organization_id: 組織ID
            vectors: ベクターのリスト
                [
                    {
                        "id": "pinecone_id",
                        "values": [0.1, 0.2, ...],
                        "metadata": {"key": "value"}
                    }
                ]
            batch_size: バッチサイズ

        Returns:
            upsertされたベクター数
        """
        loop = asyncio.get_event_loop()
        namespace = self.get_namespace(organization_id)
        total_upserted = 0

        # バッチ処理
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]

            # Pinecone形式に変換
            pinecone_vectors = [
                (v["id"], v["values"], v.get("metadata", {}))
                for v in batch
            ]

            await loop.run_in_executor(
                None,
                lambda vecs=pinecone_vectors: self.index.upsert(
                    vectors=vecs,
                    namespace=namespace
                )
            )

            total_upserted += len(batch)
            logger.debug(f"Upserted {total_upserted}/{len(vectors)} vectors")

        return total_upserted

    async def delete_vectors(
        self,
        organization_id: str,
        vector_ids: list[str],
    ) -> int:
        """
        ベクターを削除

        Args:
            organization_id: 組織ID
            vector_ids: 削除するベクターIDのリスト

        Returns:
            削除されたベクター数
        """
        loop = asyncio.get_event_loop()
        namespace = self.get_namespace(organization_id)

        await loop.run_in_executor(
            None,
            lambda: self.index.delete(
                ids=vector_ids,
                namespace=namespace
            )
        )

        return len(vector_ids)

    async def delete_by_filter(
        self,
        organization_id: str,
        filter: dict,
    ) -> None:
        """
        フィルタに一致するベクターを削除

        Args:
            organization_id: 組織ID
            filter: メタデータフィルタ
                例: {"document_id": "doc123"}
        """
        loop = asyncio.get_event_loop()
        namespace = self.get_namespace(organization_id)

        await loop.run_in_executor(
            None,
            lambda: self.index.delete(
                filter=filter,
                namespace=namespace
            )
        )

    async def delete_document_vectors(
        self,
        organization_id: str,
        document_id: str,
        version: Optional[int] = None,
    ) -> None:
        """
        ドキュメントに関連するベクターを削除

        Args:
            organization_id: 組織ID
            document_id: ドキュメントID
            version: バージョン番号（指定時はそのバージョンのみ削除）
        """
        filter = {"document_id": document_id}
        if version is not None:
            filter["version"] = version

        await self.delete_by_filter(organization_id, filter)

    # ================================================================
    # 検索
    # ================================================================

    async def search(
        self,
        organization_id: str,
        query_vector: list[float],
        top_k: int = 5,
        filters: Optional[dict] = None,
        include_metadata: bool = True,
    ) -> SearchResponse:
        """
        ベクター検索を実行

        Args:
            organization_id: 組織ID
            query_vector: クエリベクター
            top_k: 返す結果の数
            filters: メタデータフィルタ
                例: {
                    "classification": {"$in": ["public", "internal"]},
                    "category": {"$in": ["A", "B"]}
                }
            include_metadata: メタデータを含めるか

        Returns:
            SearchResponse オブジェクト
        """
        loop = asyncio.get_event_loop()
        namespace = self.get_namespace(organization_id)

        response = await loop.run_in_executor(
            None,
            lambda: self.index.query(
                vector=query_vector,
                top_k=top_k,
                namespace=namespace,
                filter=filters,
                include_metadata=include_metadata,
            )
        )

        results = [
            SearchResult(
                id=match.id,
                score=match.score,
                metadata=dict(match.metadata) if match.metadata else {}
            )
            for match in response.matches
        ]

        return SearchResponse(
            results=results,
            total_count=len(results),
            namespace=namespace,
        )

    async def search_with_access_control(
        self,
        organization_id: str,
        query_vector: list[float],
        accessible_classifications: list[str],
        accessible_department_ids: Optional[list[str]] = None,
        top_k: int = 5,
        category_filter: Optional[list[str]] = None,
    ) -> SearchResponse:
        """
        アクセス制御を適用した検索

        Args:
            organization_id: 組織ID
            query_vector: クエリベクター
            accessible_classifications: アクセス可能な機密区分のリスト
            accessible_department_ids: アクセス可能な部署IDのリスト（confidential用）
            top_k: 返す結果の数
            category_filter: カテゴリフィルタ

        Returns:
            SearchResponse オブジェクト
        """
        # フィルタを構築
        # 部署アクセス制御の有無で分岐
        # accessible_department_ids が None → 部署フィルタなし（classification のみ）
        # accessible_department_ids が [] → confidential アクセス不可（non-confidential のみ）
        # accessible_department_ids が ["dept_1"] → non-confidential + confidential(部署一致)
        if accessible_department_ids is not None:
            non_confidential = [c for c in accessible_classifications if c != "confidential"]
            has_confidential = "confidential" in accessible_classifications

            access_or: list[dict[str, Any]] = []
            if non_confidential:
                access_or.append({"classification": {"$in": non_confidential}})
            if has_confidential and accessible_department_ids:
                access_or.append({
                    "$and": [
                        {"classification": "confidential"},
                        {"department_id": {"$in": accessible_department_ids}},
                    ]
                })

            if not access_or:
                # アクセス可能な分類なし → 空結果を返すフィルタ
                filters: dict[str, Any] = {"classification": {"$in": []}}
            elif len(access_or) == 1:
                filters = access_or[0]
            else:
                filters = {"$or": access_or}
        else:
            filters: dict[str, Any] = {
                "classification": {"$in": accessible_classifications}
            }

        # カテゴリフィルタ
        if category_filter:
            filters = {"$and": [filters, {"category": {"$in": category_filter}}]}

        return await self.search(
            organization_id=organization_id,
            query_vector=query_vector,
            top_k=top_k,
            filters=filters,
            include_metadata=True,
        )

    # ================================================================
    # ユーティリティ
    # ================================================================

    def generate_pinecone_id(
        self,
        organization_id: str,
        document_id: str,
        version: int,
        chunk_index: int,
    ) -> str:
        """
        Pinecone IDを生成

        フォーマット: {org_id}_{doc_id}_v{version}_chunk{index}
        例: org_soulsyncs_doc_manual001_v1_chunk0
        """
        return f"{organization_id}_{document_id}_v{version}_chunk{chunk_index}"

    def parse_pinecone_id(self, pinecone_id: str) -> dict:
        """
        Pinecone IDをパース

        フォーマット: {org_id}_{doc_id}_v{version}_chunk{index}
        例: org_soulsyncs_doc_manual001_v1_chunk0
            → organization_id: "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
            → document_id: "doc_manual001"
            → version: 1
            → chunk_index: 0

        Returns:
            {
                "organization_id": "5f98365f-e7c5-4f48-9918-7fe9aabae5df",
                "document_id": "doc_manual001",
                "version": 1,
                "chunk_index": 0
            }
        """
        # Step 1: _chunk{N} を分離
        parts = pinecone_id.rsplit("_chunk", 1)
        if len(parts) != 2:
            return {"raw": pinecone_id}

        try:
            chunk_index = int(parts[1])
        except ValueError:
            return {"raw": pinecone_id}

        remaining = parts[0]

        # Step 2: _v{N} を分離
        version_parts = remaining.rsplit("_v", 1)
        if len(version_parts) != 2:
            return {"raw": pinecone_id, "chunk_index": chunk_index}

        try:
            version = int(version_parts[1])
        except ValueError:
            return {"raw": pinecone_id, "chunk_index": chunk_index}

        # Step 3: organization_id と document_id を分離
        # document_idは "doc" で始まることを想定
        # 例: "org_soulsyncs_doc_manual001" → org_soulsyncs + doc_manual001
        org_doc_str = version_parts[0]

        # "_doc" を探して分割（document_idは "doc" で始まる規約）
        doc_prefix_index = org_doc_str.find("_doc")
        if doc_prefix_index > 0:
            organization_id = org_doc_str[:doc_prefix_index]
            document_id = org_doc_str[doc_prefix_index + 1:]  # "_doc" の "_" をスキップ
        else:
            # "_doc" が見つからない場合は最初の "_" で分割（フォールバック）
            fallback_parts = org_doc_str.split("_", 1)
            if len(fallback_parts) != 2:
                return {
                    "raw": pinecone_id,
                    "version": version,
                    "chunk_index": chunk_index
                }
            organization_id = fallback_parts[0]
            document_id = fallback_parts[1]

        return {
            "organization_id": organization_id,
            "document_id": document_id,
            "version": version,
            "chunk_index": chunk_index
        }


# ================================================================
# エクスポート
# ================================================================

__all__ = [
    'PineconeClient',
    'SearchResult',
    'SearchResponse',
]
