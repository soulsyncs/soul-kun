# lib/pinecone_metadata_sync.py
"""
Pinecone メタデータ同期モジュール

DBの document_chunks テーブルと Pinecone のメタデータを一致させる。

【背景と目的】
document_chunks.classification / documents.department_id が変更された場合
（例: Google Drive でファイルが別フォルダに移動、機密区分の変更）、
Pinecone のメタデータが古いままになる「ゾンビ権限」問題を防ぐ。

【使用方法】
1. 定期同期（Cloud Scheduler 等）:
   await sync_all_pinecone_metadata(pool, org_id, pinecone_client)

2. 特定ドキュメントの即時同期（documents_routes.py や members_routes.py から呼び出し）:
   await sync_document_metadata_by_ids(pool, org_id, pinecone_client, document_ids=["doc-1"])

3. 検証（同期後50件サンプリング）:
   result = await verify_pinecone_metadata_sample(pool, org_id, pinecone_client, sample_size=50)

【設計原則】
- CLAUDE.md 鉄則 #1: organization_id フィルタ必須
- CLAUDE.md 鉄則 #9: SQL パラメータ化
- CLAUDE.md 鉄則 #11: 実測してから修正
- Gemini 警告準拠: 同期後50件サンプリング検証
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# 一度に処理するチャンク数（Pinecone rate limit対策）
BATCH_SIZE = 50

# 1バッチ間のスリープ時間（秒）
BATCH_SLEEP_SECONDS = 0.5


@dataclass
class SyncResult:
    """同期結果サマリー"""
    org_id: str
    total_chunks_checked: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    errors: list = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id,
            "total_chunks_checked": self.total_chunks_checked,
            "updated_count": self.updated_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "success": self.success,
        }


def _fetch_chunks_from_db(
    conn: Any,
    org_id: str,
    document_ids: Optional[list[str]] = None,
) -> list[dict]:
    """
    DB から document_chunks の現在のメタデータを取得する（同期版）

    Returns:
        [{"pinecone_id": str, "classification": str, "department_id": str}, ...]
    """
    # organization_id フィルタ必須（CLAUDE.md 鉄則#1）
    if document_ids:
        result = conn.execute(
            text("""
                SELECT
                    dc.pinecone_id,
                    d.classification,
                    COALESCE(d.department_id::text, '') AS department_id
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE dc.is_indexed = TRUE
                  AND dc.pinecone_id IS NOT NULL
                  AND d.organization_id = CAST(:org_id AS uuid)
                  AND d.id = ANY(CAST(:doc_ids AS uuid[]))
                ORDER BY dc.updated_at DESC
            """),
            {"org_id": org_id, "doc_ids": document_ids},
        )
    else:
        result = conn.execute(
            text("""
                SELECT
                    dc.pinecone_id,
                    d.classification,
                    COALESCE(d.department_id::text, '') AS department_id
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE dc.is_indexed = TRUE
                  AND dc.pinecone_id IS NOT NULL
                  AND d.organization_id = CAST(:org_id AS uuid)
                ORDER BY dc.updated_at DESC
            """),
            {"org_id": org_id},
        )

    return [
        {
            "pinecone_id": row[0],
            "classification": row[1] or "internal",
            "department_id": row[2],
        }
        for row in result.fetchall()
    ]


async def sync_document_metadata_by_ids(
    pool: Any,
    org_id: str,
    pinecone_client: Any,
    document_ids: list[str],
) -> SyncResult:
    """
    指定したドキュメントIDのPineconeメタデータを即時同期する

    documents_routes.py や外部トリガーから呼び出す用途。

    Args:
        pool: SQLAlchemy 接続プール
        org_id: 組織ID
        pinecone_client: PineconeClient インスタンス
        document_ids: 同期対象のドキュメントID（DB UUID）リスト

    Returns:
        SyncResult
    """
    result = SyncResult(org_id=org_id)

    if not document_ids:
        return result

    try:
        def _sync_db():
            with pool.connect() as conn:
                return _fetch_chunks_from_db(conn, org_id, document_ids=document_ids)

        chunks = await asyncio.to_thread(_sync_db)
        result.total_chunks_checked = len(chunks)

        if not chunks:
            return result

        # Pinecone メタデータ更新
        updates = [
            {
                "id": c["pinecone_id"],
                "metadata": {
                    "classification": c["classification"],
                    "department_id": c["department_id"],
                },
            }
            for c in chunks
        ]

        updated = await pinecone_client.update_metadata_batch(org_id, updates)
        result.updated_count = updated

        logger.info(
            "Pinecone metadata sync complete: %d/%d chunks updated (org=%s, docs=%d)",
            updated,
            len(chunks),
            org_id,
            len(document_ids),
        )

    except Exception as e:
        result.error_count += 1
        result.errors.append(str(e))
        logger.error("Pinecone metadata sync error (org=%s): %s", org_id, type(e).__name__)

    return result


async def sync_all_pinecone_metadata(
    pool: Any,
    org_id: str,
    pinecone_client: Any,
) -> SyncResult:
    """
    組織全体の Pinecone メタデータを一括同期する

    Cloud Scheduler による定期実行（夜間バッチ）を想定。
    BATCH_SIZE 件ずつ処理し、レート制限に配慮する。

    Args:
        pool: SQLAlchemy 接続プール
        org_id: 組織ID
        pinecone_client: PineconeClient インスタンス

    Returns:
        SyncResult
    """
    result = SyncResult(org_id=org_id)

    try:
        def _fetch_all():
            with pool.connect() as conn:
                return _fetch_chunks_from_db(conn, org_id)

        all_chunks = await asyncio.to_thread(_fetch_all)
        result.total_chunks_checked = len(all_chunks)

        if not all_chunks:
            logger.info("Pinecone metadata sync: no indexed chunks found (org=%s)", org_id)
            return result

        logger.info(
            "Pinecone metadata sync start: %d chunks (org=%s)",
            len(all_chunks),
            org_id,
        )

        # バッチ処理（CLAUDE.md 鉄則#5 相当: 大量データは分割処理）
        for i in range(0, len(all_chunks), BATCH_SIZE):
            batch = all_chunks[i:i + BATCH_SIZE]
            updates = [
                {
                    "id": c["pinecone_id"],
                    "metadata": {
                        "classification": c["classification"],
                        "department_id": c["department_id"],
                    },
                }
                for c in batch
            ]

            try:
                updated = await pinecone_client.update_metadata_batch(org_id, updates)
                result.updated_count += updated
            except Exception as e:
                result.error_count += len(batch)
                result.errors.append(f"Batch {i // BATCH_SIZE}: {type(e).__name__}: {e}")
                logger.error(
                    "Pinecone batch update error (batch=%d, org=%s): %s",
                    i // BATCH_SIZE,
                    org_id,
                    type(e).__name__,
                )

            # レート制限対策
            if i + BATCH_SIZE < len(all_chunks):
                await asyncio.sleep(BATCH_SLEEP_SECONDS)

        logger.info(
            "Pinecone metadata sync complete: %d/%d updated, %d errors (org=%s)",
            result.updated_count,
            result.total_chunks_checked,
            result.error_count,
            org_id,
        )

    except Exception as e:
        result.error_count += 1
        result.errors.append(str(e))
        logger.error("Pinecone full sync error (org=%s): %s", org_id, type(e).__name__)

    return result


async def verify_pinecone_metadata_sample(
    pool: Any,
    org_id: str,
    pinecone_client: Any,
    sample_size: int = 50,
) -> dict:
    """
    同期後の検証：DBとPineconeのメタデータをサンプリングして一致確認

    Gemini 警告（ゾンビ権限検証）準拠。
    同期後に本関数を呼び出すことで、実際に更新されたか確認できる。

    Args:
        pool: SQLAlchemy 接続プール
        org_id: 組織ID
        pinecone_client: PineconeClient インスタンス
        sample_size: チェックするチャンク数（デフォルト50件）

    Returns:
        {"checked": N, "matched": N, "mismatched": [{"id": ..., "db": ..., "pinecone": ...}]}
    """
    try:
        def _fetch_sample():
            with pool.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT
                            dc.pinecone_id,
                            d.classification,
                            COALESCE(d.department_id::text, '') AS department_id
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        WHERE dc.is_indexed = TRUE
                          AND dc.pinecone_id IS NOT NULL
                          AND d.organization_id = CAST(:org_id AS uuid)
                        ORDER BY RANDOM()
                        LIMIT :limit
                    """),
                    {"org_id": org_id, "limit": sample_size},
                )
                return [
                    {"pinecone_id": row[0], "classification": row[1] or "internal", "department_id": row[2]}
                    for row in result.fetchall()
                ]

        sample = await asyncio.to_thread(_fetch_sample)

        if not sample:
            return {"checked": 0, "matched": 0, "mismatched": []}

        # Pinecone から取得（fetch API）
        loop = asyncio.get_event_loop()
        namespace = pinecone_client.get_namespace(org_id)
        pinecone_ids = [c["pinecone_id"] for c in sample]

        fetch_response = await loop.run_in_executor(
            None,
            lambda: pinecone_client.index.fetch(ids=pinecone_ids, namespace=namespace)
        )
        pinecone_vectors = fetch_response.vectors if hasattr(fetch_response, "vectors") else {}

        mismatched = []
        matched = 0
        for chunk in sample:
            vid = chunk["pinecone_id"]
            if vid not in pinecone_vectors:
                mismatched.append({"id": vid, "reason": "not_found_in_pinecone"})
                continue
            pinecone_meta = pinecone_vectors[vid].metadata or {}
            if (
                pinecone_meta.get("classification") == chunk["classification"]
                and pinecone_meta.get("department_id", "") == chunk["department_id"]
            ):
                matched += 1
            else:
                mismatched.append({
                    "id": vid,
                    "db": {"classification": chunk["classification"], "department_id": chunk["department_id"]},
                    "pinecone": {
                        "classification": pinecone_meta.get("classification"),
                        "department_id": pinecone_meta.get("department_id"),
                    },
                })

        return {
            "checked": len(sample),
            "matched": matched,
            "mismatched": mismatched,
        }

    except Exception as e:
        logger.error("Pinecone metadata verification error (org=%s): %s", org_id, type(e).__name__)
        return {"checked": 0, "matched": 0, "mismatched": [], "error": str(e)}
