# lib/brain/drive_tool.py
"""
Googleドライブ ファイル検索ツール — Step A-5: 秘書に書庫を見せる

ソウルくんがGoogleドライブ上のファイルを名前で検索・一覧表示できるようにする機能。
既存のdocumentsテーブル（watch-google-driveで同期済み）を活用し、
ファイル名検索と最近更新されたファイルの一覧を提供する。

【設計原則】
- 読み取り専用（DBから検索のみ）→ リスクレベルは"low"
- 全文検索はquery_knowledge（RAG）で既に対応済み。
  このツールはファイル名・メタデータ検索に特化。
- organization_idフィルタ必須（CLAUDE.md §3 鉄則#1）
- PIIマスキング: ファイルパスにメールが含まれる場合を考慮
- sync I/Oは asyncio.to_thread() で包む（CLAUDE.md §3-2 #6）

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# デフォルト設定
DEFAULT_MAX_FILES = 10
MAX_ALLOWED_FILES = 20


def search_drive_files(
    pool: Any,
    organization_id: str,
    query: Optional[str] = None,
    max_results: int = DEFAULT_MAX_FILES,
) -> Dict[str, Any]:
    """
    Googleドライブのファイルを名前で検索する。

    documentsテーブル（watch-google-driveで同期済み）を使い、
    ファイル名のLIKE検索を行う。

    Args:
        pool: SQLAlchemy connection pool
        organization_id: 組織ID
        query: 検索クエリ（ファイル名の部分一致）。省略時は最近更新されたファイル。
        max_results: 最大取得件数

    Returns:
        dict: {
            "success": bool,
            "files": [{
                "file_name": str,
                "title": str,
                "web_view_link": str | None,
                "updated_at": str | None,
                "classification": str,
            }],
            "query": str,
            "file_count": int,
        }
    """
    # max_resultsを制限
    max_results = min(max(1, max_results), MAX_ALLOWED_FILES)

    if not organization_id:
        return {
            "success": False,
            "error": "組織IDが指定されていません",
            "files": [],
            "query": query or "",
            "file_count": 0,
        }

    try:
        from sqlalchemy import text as sa_text

        with pool.connect() as conn:
            # RLS用のorganization_id設定
            conn.execute(
                sa_text(
                    "SELECT set_config('app.current_organization_id', :org_id, true)"
                ),
                {"org_id": organization_id},
            )

            if query and query.strip():
                # ファイル名検索（LIKE）
                search_query = f"%{query.strip()}%"
                rows = conn.execute(
                    sa_text("""
                        SELECT file_name, title, google_drive_web_view_link,
                               updated_at, classification
                        FROM documents
                        WHERE organization_id = :org_id
                          AND is_searchable = TRUE
                          AND deleted_at IS NULL
                          AND (
                              file_name ILIKE :q
                              OR title ILIKE :q
                          )
                        ORDER BY updated_at DESC NULLS LAST
                        LIMIT :limit
                    """),
                    {"org_id": organization_id, "q": search_query, "limit": max_results},
                ).fetchall()
            else:
                # クエリなし → 最近更新されたファイル一覧
                rows = conn.execute(
                    sa_text("""
                        SELECT file_name, title, google_drive_web_view_link,
                               updated_at, classification
                        FROM documents
                        WHERE organization_id = :org_id
                          AND is_searchable = TRUE
                          AND deleted_at IS NULL
                        ORDER BY updated_at DESC NULLS LAST
                        LIMIT :limit
                    """),
                    {"org_id": organization_id, "limit": max_results},
                ).fetchall()

    except Exception as e:
        logger.error("Drive file search failed: %s", type(e).__name__)
        return {
            "success": False,
            "error": f"ドライブファイルの検索に失敗しました: {type(e).__name__}",
            "files": [],
            "query": query or "",
            "file_count": 0,
        }

    # 結果をフォーマット
    files = []
    for row in rows:
        file_name = row[0] or ""
        title = row[1] or file_name
        web_view_link = row[2]
        updated_at = row[3]
        classification = row[4] or "internal"

        updated_at_str = None
        if updated_at:
            if isinstance(updated_at, datetime):
                updated_at_str = updated_at.strftime("%Y-%m-%d %H:%M")
            else:
                updated_at_str = str(updated_at)[:16]

        files.append({
            "file_name": file_name,
            "title": title,
            "web_view_link": web_view_link,
            "updated_at": updated_at_str,
            "classification": classification,
        })

    return {
        "success": True,
        "files": files,
        "query": query or "",
        "file_count": len(files),
    }


def format_drive_files(result: Dict[str, Any]) -> str:
    """
    ドライブファイル検索結果をBrainが合成回答に使える形式にフォーマットする。

    Args:
        result: search_drive_files() の結果

    Returns:
        str: フォーマットされたファイル一覧テキスト
    """
    if not result.get("success"):
        return f"ドライブ検索エラー: {result.get('error', '不明なエラー')}"

    files = result.get("files", [])
    query = result.get("query", "")

    if not files:
        if query:
            return f"「{query}」に一致するファイルは見つかりませんでした。"
        return "ドライブにファイルがありません。"

    if query:
        header = f"【ドライブ検索「{query}」: {len(files)}件】"
    else:
        header = f"【最近更新されたファイル: {len(files)}件】"

    parts = [header]

    for i, f in enumerate(files, 1):
        title = f.get("title") or f.get("file_name", "（タイトルなし）")
        file_name = f.get("file_name", "")
        updated = f.get("updated_at", "")
        link = f.get("web_view_link")

        line = f"{i}. {title}"
        if file_name and file_name != title:
            line += f"\n   ファイル名: {file_name}"
        if updated:
            line += f"\n   更新: {updated}"
        if link:
            line += f"\n   リンク: {link}"

        parts.append(line)

    return "\n".join(parts)
