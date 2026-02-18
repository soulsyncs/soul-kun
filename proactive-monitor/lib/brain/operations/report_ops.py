# lib/brain/operations/report_ops.py
"""
書き込み系操作ハンドラー — Step C-5: レポート生成・CSV出力・ファイル作成

【設計原則】
- 出力先はGCSバケット（OPERATIONS_GCS_BUCKET）のみ。ローカルファイルシステム書き込み禁止
- 全操作は社長の確認が必須（requires_confirmation: True）
- organization_idフィルタ必須（CLAUDE.md §3 鉄則#1）
- PII除去: ユーザー名・メールは出力に含めない
- ファイルサイズ上限: 1MB
- 出力はOperationResult形式で統一

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import asyncio
import csv
import io
import logging
import os
from datetime import datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo

from lib.brain.operations.registry import OperationResult

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")

# GCSバケット名（環境変数から取得）
OPERATIONS_GCS_BUCKET = os.getenv("OPERATIONS_GCS_BUCKET", "")

# ファイルサイズ上限（1MB）
MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024


# =====================================================
# GCSヘルパー
# =====================================================


def _upload_to_gcs(
    content: str,
    blob_path: str,
    content_type: str,
    organization_id: str,
) -> str:
    """
    GCSにファイルをアップロードする（同期関数）。

    asyncio.to_thread()で呼び出すこと。

    Returns:
        GCSパス（gs://bucket/path）
    """
    bucket_name = OPERATIONS_GCS_BUCKET
    if not bucket_name:
        raise ValueError("OPERATIONS_GCS_BUCKET環境変数が設定されていません")

    # ファイルサイズチェック
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"ファイルサイズが上限（1MB）を超えています: {len(content_bytes)} bytes"
        )

    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    full_path = f"{organization_id}/{blob_path}"
    blob = bucket.blob(full_path)
    blob.upload_from_string(content_bytes, content_type=content_type)

    gcs_path = f"gs://{bucket_name}/{full_path}"
    logger.info("File uploaded to GCS: %s (%d bytes)", gcs_path, len(content_bytes))
    return gcs_path


# =====================================================
# レポート生成ハンドラー
# =====================================================


async def handle_report_generate(
    params: Dict[str, Any],
    organization_id: str,
    account_id: str,
) -> OperationResult:
    """
    レポートを生成してGCSに保存する。

    params:
        title: レポートタイトル（必須）
        content: レポート本文（必須）
        format: 出力形式（"text" or "markdown"、デフォルト: "text"）
    """
    title = params.get("title", "")
    content = params.get("content", "")
    fmt = params.get("format", "text")

    if not title or not content:
        return OperationResult(
            success=False,
            message="レポートのタイトルと本文が必要です。",
        )

    try:
        now = datetime.now(JST)
        timestamp = now.strftime("%Y%m%d_%H%M%S")

        if fmt == "markdown":
            ext = "md"
            body = f"# {title}\n\n生成日時: {now.strftime('%Y-%m-%d %H:%M')}\n\n{content}"
            content_type = "text/markdown; charset=utf-8"
        else:
            ext = "txt"
            body = f"{title}\n{'=' * len(title)}\n\n生成日時: {now.strftime('%Y-%m-%d %H:%M')}\n\n{content}"
            content_type = "text/plain; charset=utf-8"

        blob_path = f"reports/{timestamp}_{_safe_filename(title)}.{ext}"

        gcs_path = await asyncio.to_thread(
            _upload_to_gcs, body, blob_path, content_type, organization_id
        )

        return OperationResult(
            success=True,
            message=f"レポート「{title}」を作成しました。\n保存先: {gcs_path}",
            data={
                "gcs_path": gcs_path,
                "title": title,
                "format": fmt,
                "size_bytes": len(body.encode("utf-8")),
            },
        )

    except ValueError as e:
        return OperationResult(success=False, message=str(e))
    except Exception as e:
        logger.error("report_generate error: %s", type(e).__name__, exc_info=True)
        return OperationResult(
            success=False,
            message="レポートの生成でエラーが発生しました。",
        )


# =====================================================
# CSV出力ハンドラー
# =====================================================


async def handle_csv_export(
    params: Dict[str, Any],
    organization_id: str,
    account_id: str,
) -> OperationResult:
    """
    データをCSVに出力してGCSに保存する。

    params:
        data_source: データソース名（"tasks" or "goals"）（必須）
        filters: フィルタ条件（任意）
    """
    data_source = params.get("data_source", "")

    if not data_source:
        return OperationResult(
            success=False,
            message="エクスポートするデータソースを指定してください。",
        )

    try:
        from lib.brain.operations.data_ops import (
            _resolve_data_source,
            _build_task_filter,
        )

        table = _resolve_data_source(data_source)
        if not table:
            return OperationResult(
                success=False,
                message=f"「{data_source}」は対応していません。tasks（タスク）またはgoals（目標）を指定してください。",
            )

        filters = params.get("filters", "")
        rows = await asyncio.to_thread(
            _fetch_csv_data, table, filters, organization_id
        )

        # CSV生成
        csv_content = _build_csv(table, rows)

        now = datetime.now(JST)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        blob_path = f"exports/{timestamp}_{data_source}.csv"

        gcs_path = await asyncio.to_thread(
            _upload_to_gcs, csv_content, blob_path, "text/csv; charset=utf-8", organization_id
        )

        return OperationResult(
            success=True,
            message=f"「{data_source}」のCSVを出力しました（{len(rows)}件）。\n保存先: {gcs_path}",
            data={
                "gcs_path": gcs_path,
                "data_source": data_source,
                "row_count": len(rows),
                "size_bytes": len(csv_content.encode("utf-8")),
            },
        )

    except ValueError as e:
        return OperationResult(success=False, message=str(e))
    except Exception as e:
        logger.error("csv_export error: %s", type(e).__name__, exc_info=True)
        return OperationResult(
            success=False,
            message="CSVの出力でエラーが発生しました。",
        )


def _fetch_csv_data(table: str, filters: str, organization_id: str) -> list:
    """DBからCSV用データを取得する（同期関数）"""
    from lib.brain.operations.data_ops import _build_task_filter
    from lib.db import get_db_pool
    from sqlalchemy import text

    pool = get_db_pool()
    with pool.connect() as conn:
        base_where = "organization_id = :org_id"
        base_params: Dict[str, Any] = {"org_id": organization_id}

        extra_where, extra_params = _build_task_filter(filters)
        all_params = {**base_params, **extra_params}
        where_clause = base_where
        if extra_where:
            where_clause += f" AND {extra_where}"

        if table == "chatwork_tasks":
            # PII除去: assigned_by等は含めない
            query = text(f"""
                SELECT task_id, summary, status, limit_time, room_name
                FROM chatwork_tasks
                WHERE {where_clause}
                ORDER BY created_at DESC NULLS LAST
                LIMIT 1000
            """)
        elif table == "staff_goals":
            query = text(f"""
                SELECT id, goal_month, sessions_target
                FROM staff_goals
                WHERE {where_clause}
                ORDER BY goal_month DESC
                LIMIT 1000
            """)
        else:
            return []

        return conn.execute(query, all_params).fetchall()


def _build_csv(table: str, rows: list) -> str:
    """行データからCSV文字列を生成する"""
    output = io.StringIO()
    writer = csv.writer(output)

    if table == "chatwork_tasks":
        writer.writerow(["タスクID", "概要", "ステータス", "期限", "ルーム"])
        for row in rows:
            status_ja = {"open": "未完了", "done": "完了"}.get(row[2], row[2] or "不明")
            deadline = ""
            if row[3]:
                try:
                    dt = datetime.utcfromtimestamp(int(row[3]))
                    deadline = dt.strftime("%Y-%m-%d")
                except (ValueError, TypeError, OSError):
                    pass
            writer.writerow([row[0], (row[1] or "")[:100], status_ja, deadline, row[4] or ""])
    elif table == "staff_goals":
        writer.writerow(["目標ID", "月", "目標セッション数"])
        for row in rows:
            writer.writerow([row[0], row[1] or "", row[2] or ""])

    return output.getvalue()


# =====================================================
# ファイル作成ハンドラー
# =====================================================


async def handle_file_create(
    params: Dict[str, Any],
    organization_id: str,
    account_id: str,
) -> OperationResult:
    """
    テキストファイルを作成してGCSに保存する。

    params:
        filename: ファイル名（必須）
        content: ファイル内容（必須）
    """
    filename = params.get("filename", "")
    content = params.get("content", "")

    if not filename or not content:
        return OperationResult(
            success=False,
            message="ファイル名と内容が必要です。",
        )

    # ファイル名の安全チェック
    safe_name = _safe_filename(filename)
    if not safe_name:
        return OperationResult(
            success=False,
            message="ファイル名が不正です。",
        )

    try:
        now = datetime.now(JST)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        blob_path = f"files/{timestamp}_{safe_name}"

        gcs_path = await asyncio.to_thread(
            _upload_to_gcs, content, blob_path, "text/plain; charset=utf-8", organization_id
        )

        return OperationResult(
            success=True,
            message=f"ファイル「{safe_name}」を作成しました。\n保存先: {gcs_path}",
            data={
                "gcs_path": gcs_path,
                "filename": safe_name,
                "size_bytes": len(content.encode("utf-8")),
            },
        )

    except ValueError as e:
        return OperationResult(success=False, message=str(e))
    except Exception as e:
        logger.error("file_create error: %s", type(e).__name__, exc_info=True)
        return OperationResult(
            success=False,
            message="ファイルの作成でエラーが発生しました。",
        )


# =====================================================
# ユーティリティ
# =====================================================


def _safe_filename(name: str) -> str:
    """ファイル名から危険な文字を除去する"""
    import re
    # パストラバーサル除去（.. を削除）
    safe = name.replace("..", "")
    # 英数字、日本語、ハイフン、アンダースコア、ドットのみ許可
    safe = re.sub(r'[^\w\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF.\-]', '_', safe)
    # 連続アンダースコアを1つにまとめる
    safe = re.sub(r'_+', '_', safe).strip('_')
    # 最大50文字
    return safe[:50] if safe else ""
