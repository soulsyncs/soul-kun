#!/usr/bin/env python3
"""
Pinecone インデックス再構築スクリプト（v10.13.2）

品質フィルタリングを適用してPineconeインデックスを再構築します。

使用方法:
    # 環境変数を設定
    export PINECONE_API_KEY=your_key
    export GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json

    # 実行
    python scripts/rebuild_pinecone_index.py --org-id soulsyncs --dry-run
    python scripts/rebuild_pinecone_index.py --org-id soulsyncs

オプション:
    --org-id: 組織ID（必須）
    --dry-run: 実際にはupsertせず、処理内容を表示
    --force: 確認なしで実行
"""

import os
import sys
import argparse
import asyncio
import logging
from datetime import datetime

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'watch-google-drive'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'api'))

from lib.pinecone_client import PineconeClient
from lib.db import get_db_pool
from lib.embedding import EmbeddingClient
from lib.document_processor import (
    DocumentProcessor,
    is_table_of_contents,
    calculate_chunk_quality_score,
    should_exclude_chunk,
)
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_all_chunks_from_db(pool, organization_id: str) -> list[dict]:
    """DBから全チャンクを取得"""
    with pool.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    dc.id,
                    dc.document_id,
                    dc.chunk_index,
                    dc.pinecone_id,
                    dc.content,
                    dc.content_hash,
                    dc.char_count,
                    dc.page_number,
                    dc.section_title,
                    d.title as document_title,
                    d.category,
                    d.classification,
                    d.department_id,
                    dv.version_number
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                JOIN document_versions dv ON dc.document_version_id = dv.id
                WHERE dc.organization_id = :org_id
                  AND d.status = 'completed'
                  AND dv.version_number = d.current_version
                ORDER BY dc.document_id, dc.chunk_index
            """),
            {"org_id": organization_id}
        )
        return [dict(row._mapping) for row in result]


def analyze_chunks(chunks: list[dict]) -> dict:
    """チャンクの品質分析"""
    analysis = {
        "total_chunks": len(chunks),
        "high_quality": 0,
        "low_quality": 0,
        "table_of_contents": 0,
        "excluded": 0,
        "quality_scores": [],
        "exclusion_reasons": {},
    }

    for chunk in chunks:
        content = chunk.get("content", "")

        # 品質スコア計算
        quality_score = calculate_chunk_quality_score(content)
        analysis["quality_scores"].append(quality_score)

        # 除外判定
        excluded, reason = should_exclude_chunk(content)

        if excluded:
            analysis["excluded"] += 1
            analysis["exclusion_reasons"][reason] = analysis["exclusion_reasons"].get(reason, 0) + 1
            if reason == "table_of_contents":
                analysis["table_of_contents"] += 1
        elif quality_score >= 0.5:
            analysis["high_quality"] += 1
        else:
            analysis["low_quality"] += 1

    # 品質スコアの統計
    if analysis["quality_scores"]:
        analysis["avg_quality_score"] = sum(analysis["quality_scores"]) / len(analysis["quality_scores"])
        analysis["min_quality_score"] = min(analysis["quality_scores"])
        analysis["max_quality_score"] = max(analysis["quality_scores"])

    return analysis


async def rebuild_index(
    organization_id: str,
    dry_run: bool = True,
    min_quality_score: float = 0.4
):
    """Pineconeインデックスを再構築"""
    logger.info(f"=== Pinecone インデックス再構築 ===")
    logger.info(f"組織ID: {organization_id}")
    logger.info(f"ドライラン: {dry_run}")
    logger.info(f"最小品質スコア: {min_quality_score}")

    # クライアント初期化
    pool = get_db_pool()
    pinecone_client = PineconeClient()
    embedding_client = EmbeddingClient()

    # DBからチャンクを取得
    logger.info("DBからチャンクを取得中...")
    chunks = get_all_chunks_from_db(pool, organization_id)
    logger.info(f"取得チャンク数: {len(chunks)}")

    if not chunks:
        logger.warning("チャンクがありません")
        return

    # 品質分析
    logger.info("品質分析中...")
    analysis = analyze_chunks(chunks)

    logger.info(f"\n=== 品質分析結果 ===")
    logger.info(f"全チャンク数: {analysis['total_chunks']}")
    logger.info(f"高品質チャンク: {analysis['high_quality']}")
    logger.info(f"低品質チャンク: {analysis['low_quality']}")
    logger.info(f"除外対象: {analysis['excluded']}")
    logger.info(f"  - 目次: {analysis['table_of_contents']}")
    logger.info(f"除外理由内訳: {analysis['exclusion_reasons']}")
    logger.info(f"平均品質スコア: {analysis.get('avg_quality_score', 0):.3f}")
    logger.info(f"品質スコア範囲: {analysis.get('min_quality_score', 0):.3f} - {analysis.get('max_quality_score', 0):.3f}")

    if dry_run:
        logger.info("\n=== ドライラン: 除外されるチャンクのサンプル ===")
        excluded_samples = []
        for chunk in chunks:
            content = chunk.get("content", "")
            excluded, reason = should_exclude_chunk(content)
            quality_score = calculate_chunk_quality_score(content)

            if excluded or quality_score < min_quality_score:
                excluded_samples.append({
                    "pinecone_id": chunk.get("pinecone_id"),
                    "document_title": chunk.get("document_title"),
                    "chunk_index": chunk.get("chunk_index"),
                    "reason": reason if excluded else f"low_quality_{quality_score:.2f}",
                    "quality_score": quality_score,
                    "content_preview": content[:100].replace("\n", " ")
                })

        for i, sample in enumerate(excluded_samples[:10]):
            logger.info(f"\n[除外チャンク {i+1}]")
            logger.info(f"  ID: {sample['pinecone_id']}")
            logger.info(f"  ドキュメント: {sample['document_title']}")
            logger.info(f"  チャンク番号: {sample['chunk_index']}")
            logger.info(f"  除外理由: {sample['reason']}")
            logger.info(f"  品質スコア: {sample['quality_score']:.3f}")
            logger.info(f"  内容: {sample['content_preview']}...")

        logger.info(f"\n=== ドライラン完了 ===")
        logger.info(f"実際に実行するには --dry-run を外してください")
        return analysis

    # 実際の再構築処理
    logger.info("\n=== インデックス再構築開始 ===")

    # 1. 既存のベクターを削除
    logger.info("既存ベクターを削除中...")
    namespace = pinecone_client.get_namespace(organization_id)

    try:
        # namespaceの全ベクターを削除
        stats = await pinecone_client.describe_index_stats(organization_id)
        vector_count = stats.get("vector_count", 0)
        logger.info(f"削除対象ベクター数: {vector_count}")

        if vector_count > 0:
            # 全ドキュメントIDを取得して削除
            document_ids = set(chunk.get("document_id") for chunk in chunks)
            for doc_id in document_ids:
                await pinecone_client.delete_by_filter(
                    organization_id,
                    {"document_id": doc_id}
                )
            logger.info("既存ベクター削除完了")
    except Exception as e:
        logger.warning(f"既存ベクター削除エラー（続行）: {e}")

    # 2. 高品質チャンクのみをupsert
    logger.info("高品質チャンクをupsert中...")

    high_quality_chunks = []
    for chunk in chunks:
        content = chunk.get("content", "")
        excluded, reason = should_exclude_chunk(content)
        quality_score = calculate_chunk_quality_score(content)

        if not excluded and quality_score >= min_quality_score:
            chunk["quality_score"] = quality_score
            high_quality_chunks.append(chunk)

    logger.info(f"upsert対象チャンク数: {len(high_quality_chunks)}")

    # エンベディング生成とupsert（バッチ処理）
    batch_size = 50
    total_upserted = 0

    for i in range(0, len(high_quality_chunks), batch_size):
        batch = high_quality_chunks[i:i + batch_size]

        # エンベディング生成
        texts = [c.get("content", "") for c in batch]
        batch_result = embedding_client.embed_texts_sync(texts)

        # ベクター準備
        vectors = []
        for chunk, emb_result in zip(batch, batch_result.results):
            vectors.append({
                "id": chunk.get("pinecone_id"),
                "values": emb_result.vector,
                "metadata": {
                    "document_id": chunk.get("document_id"),
                    "version": chunk.get("version_number"),
                    "chunk_index": chunk.get("chunk_index"),
                    "title": chunk.get("document_title"),
                    "category": chunk.get("category"),
                    "classification": chunk.get("classification"),
                    "department_id": chunk.get("department_id") or "",
                    "page_number": chunk.get("page_number") or 0,
                    "section_title": chunk.get("section_title") or "",
                    "quality_score": chunk.get("quality_score", 0.5),
                }
            })

        # upsert
        await pinecone_client.upsert_vectors(organization_id, vectors)
        total_upserted += len(vectors)
        logger.info(f"upsert進捗: {total_upserted}/{len(high_quality_chunks)}")

    logger.info(f"\n=== インデックス再構築完了 ===")
    logger.info(f"upsertチャンク数: {total_upserted}")
    logger.info(f"除外チャンク数: {len(chunks) - total_upserted}")

    return {
        "total_chunks": len(chunks),
        "upserted_chunks": total_upserted,
        "excluded_chunks": len(chunks) - total_upserted,
    }


def main():
    parser = argparse.ArgumentParser(description="Pinecone インデックス再構築")
    parser.add_argument("--org-id", required=True, help="組織ID")
    parser.add_argument("--dry-run", action="store_true", help="実際にはupsertせず分析のみ")
    parser.add_argument("--force", action="store_true", help="確認なしで実行")
    parser.add_argument("--min-quality", type=float, default=0.4, help="最小品質スコア")

    args = parser.parse_args()

    if not args.dry_run and not args.force:
        print(f"\n警告: 組織 '{args.org_id}' のPineconeインデックスを再構築します。")
        print("既存のベクターは全て削除されます。")
        confirm = input("続行しますか？ (yes/no): ")
        if confirm.lower() != "yes":
            print("キャンセルしました")
            return

    result = asyncio.run(rebuild_index(
        organization_id=args.org_id,
        dry_run=args.dry_run,
        min_quality_score=args.min_quality
    ))

    print(f"\n完了: {result}")


if __name__ == "__main__":
    main()
