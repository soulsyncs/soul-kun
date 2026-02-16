# lib/brain/web_search.py
"""
Web検索ハンドラー — Step A-1: 手足を与える

ソウルくんがインターネット検索を行えるようにする「スマホを渡す」機能。
Tavily Search APIを使い、最新のWeb情報を取得する。

【設計原則】
- 読み取り専用（外部への書き込みなし）→ リスクレベルは"low"
- fire-and-forget不要（同期的に結果を返す必要がある）
- PII保護: 検索クエリの監査ログにはマスキング適用（audit_bridge経由）
- CLAUDE.md §3-2 #16: APIキーは環境変数から取得（ハードコード禁止）

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import logging
import os
from typing import Any, Dict, List, Optional

from lib.brain.env_config import ENV_TAVILY_API_KEY

logger = logging.getLogger(__name__)

# デフォルト設定
DEFAULT_MAX_RESULTS = 5
MAX_ALLOWED_RESULTS = 10


class WebSearchClient:
    """
    Web検索クライアント

    Tavily Search APIを使ったWeb検索を提供する。
    APIキーがない場合はgracefulにエラーを返す。
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Tavily APIキー。Noneの場合は環境変数から取得
        """
        self.api_key = api_key or os.environ.get(ENV_TAVILY_API_KEY, "")
        self._client = None

    def _get_client(self):
        """Tavily クライアントを遅延初期化"""
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "TAVILY_API_KEY が設定されていません。"
                    "環境変数 TAVILY_API_KEY を設定してください。"
                )
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "tavily パッケージがインストールされていません。"
                    "pip install tavily-python を実行してください。"
                )
        return self._client

    def search(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        search_depth: str = "basic",
        include_answer: bool = True,
    ) -> Dict[str, Any]:
        """
        Web検索を実行する。

        Args:
            query: 検索クエリ
            max_results: 最大結果件数（1-10）
            search_depth: 検索の深さ（"basic" or "advanced"）
            include_answer: AI要約を含めるか

        Returns:
            dict: {
                "success": bool,
                "answer": str | None,  # AI要約
                "results": [{
                    "title": str,
                    "url": str,
                    "content": str,  # スニペット
                }],
                "query": str,
                "result_count": int,
            }
        """
        if not query or not query.strip():
            return {
                "success": False,
                "error": "検索クエリが空です",
                "results": [],
                "query": "",
                "result_count": 0,
            }

        # max_results を制限
        max_results = min(max(1, max_results), MAX_ALLOWED_RESULTS)

        try:
            client = self._get_client()
            response = client.search(
                query=query,
                max_results=max_results,
                search_depth=search_depth,
                include_answer=include_answer,
            )

            # 結果を整形
            results = []
            for item in response.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                })

            return {
                "success": True,
                "answer": response.get("answer"),
                "results": results,
                "query": query,
                "result_count": len(results),
            }

        except ValueError as e:
            logger.warning("WebSearchClient: API key error: %s", e)
            return {
                "success": False,
                "error": str(e),
                "results": [],
                "query": query,
                "result_count": 0,
            }
        except ImportError as e:
            logger.warning("WebSearchClient: import error: %s", e)
            return {
                "success": False,
                "error": str(e),
                "results": [],
                "query": query,
                "result_count": 0,
            }
        except Exception as e:
            logger.error("WebSearchClient: search failed: %s", e, exc_info=True)
            return {
                "success": False,
                "error": f"検索中にエラーが発生しました: {type(e).__name__}",
                "results": [],
                "query": query,
                "result_count": 0,
            }


def format_search_results(search_result: Dict[str, Any]) -> str:
    """
    検索結果をBrainが合成回答に使える形式にフォーマットする。

    Brain層が検索結果を基に最終回答を生成するため、
    結果はmarkdown風のテキストで返す。

    Args:
        search_result: WebSearchClient.search()の結果

    Returns:
        str: フォーマットされた検索結果テキスト
    """
    if not search_result.get("success"):
        return f"検索エラー: {search_result.get('error', '不明なエラー')}"

    parts = []

    # AI要約があれば先頭に表示
    answer = search_result.get("answer")
    if answer:
        parts.append(f"【要約】\n{answer}")
        parts.append("")

    # 各検索結果
    results = search_result.get("results", [])
    if results:
        parts.append(f"【検索結果: {len(results)}件】")
        for i, r in enumerate(results, 1):
            title = r.get("title", "タイトルなし")
            url = r.get("url", "")
            content = r.get("content", "")
            parts.append(f"{i}. {title}")
            if url:
                parts.append(f"   URL: {url}")
            if content:
                # 長すぎるスニペットは切り詰め
                snippet = content[:300] + "..." if len(content) > 300 else content
                parts.append(f"   {snippet}")
            parts.append("")
    else:
        parts.append("検索結果が見つかりませんでした。")

    return "\n".join(parts)


# シングルトンインスタンス
_web_search_client: Optional[WebSearchClient] = None


def get_web_search_client() -> WebSearchClient:
    """WebSearchClientのシングルトンを取得"""
    global _web_search_client
    if _web_search_client is None:
        _web_search_client = WebSearchClient()
    return _web_search_client
