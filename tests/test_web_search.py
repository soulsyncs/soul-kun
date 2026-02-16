"""
Web検索（WebSearchClient）テスト — Step A-1

WebSearchClientの検索機能をテストする:
- 正常な検索結果の返却
- 空クエリの処理
- APIキー未設定時のエラーハンドリング
- 結果フォーマット
- max_resultsの制限
"""

import pytest
from unittest.mock import patch, MagicMock

from lib.brain.web_search import (
    WebSearchClient,
    format_search_results,
    get_web_search_client,
    DEFAULT_MAX_RESULTS,
    MAX_ALLOWED_RESULTS,
)


class TestWebSearchClient:
    """WebSearchClientの基本テスト"""

    def test_empty_query_returns_error(self):
        """空クエリはエラーを返す"""
        client = WebSearchClient(api_key="test-key")
        result = client.search("")
        assert result["success"] is False
        assert "空" in result["error"]
        assert result["results"] == []

    def test_whitespace_query_returns_error(self):
        """空白のみのクエリはエラーを返す"""
        client = WebSearchClient(api_key="test-key")
        result = client.search("   ")
        assert result["success"] is False

    def test_no_api_key_returns_error(self):
        """APIキー未設定時はエラーを返す"""
        with patch.dict("os.environ", {}, clear=True):
            client = WebSearchClient(api_key="")
            result = client.search("test query")
            assert result["success"] is False
            assert "TAVILY_API_KEY" in result["error"]

    @patch("lib.brain.web_search.WebSearchClient._get_client")
    def test_successful_search(self, mock_get_client):
        """正常な検索結果を返す"""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "answer": "テストの答え",
            "results": [
                {
                    "title": "テスト結果1",
                    "url": "https://example.com/1",
                    "content": "テスト内容1",
                },
                {
                    "title": "テスト結果2",
                    "url": "https://example.com/2",
                    "content": "テスト内容2",
                },
            ],
        }
        mock_get_client.return_value = mock_client

        client = WebSearchClient(api_key="test-key")
        result = client.search("テストクエリ")

        assert result["success"] is True
        assert result["answer"] == "テストの答え"
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "テスト結果1"
        assert result["query"] == "テストクエリ"
        assert result["result_count"] == 2

    @patch("lib.brain.web_search.WebSearchClient._get_client")
    def test_search_with_max_results(self, mock_get_client):
        """max_resultsが正しく渡される"""
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        mock_get_client.return_value = mock_client

        client = WebSearchClient(api_key="test-key")
        client.search("test", max_results=3)

        mock_client.search.assert_called_once_with(
            query="test",
            max_results=3,
            search_depth="basic",
            include_answer=True,
        )

    def test_max_results_capped(self):
        """max_resultsがMAX_ALLOWED_RESULTSに制限される"""
        with patch("lib.brain.web_search.WebSearchClient._get_client") as mock:
            mock_client = MagicMock()
            mock_client.search.return_value = {"results": []}
            mock.return_value = mock_client

            client = WebSearchClient(api_key="test-key")
            client.search("test", max_results=100)

            called_max = mock_client.search.call_args[1]["max_results"]
            assert called_max == MAX_ALLOWED_RESULTS

    def test_max_results_minimum_is_one(self):
        """max_resultsは最小1"""
        with patch("lib.brain.web_search.WebSearchClient._get_client") as mock:
            mock_client = MagicMock()
            mock_client.search.return_value = {"results": []}
            mock.return_value = mock_client

            client = WebSearchClient(api_key="test-key")
            client.search("test", max_results=0)

            called_max = mock_client.search.call_args[1]["max_results"]
            assert called_max == 1

    @patch("lib.brain.web_search.WebSearchClient._get_client")
    def test_search_api_exception(self, mock_get_client):
        """API例外時はエラーを返す"""
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client

        client = WebSearchClient(api_key="test-key")
        result = client.search("test")

        assert result["success"] is False
        assert "エラー" in result["error"]

    def test_tavily_import_error(self):
        """tavilyパッケージ未インストール時"""
        client = WebSearchClient(api_key="test-key")
        client._client = None  # reset

        with patch.dict("sys.modules", {"tavily": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'tavily'")):
                result = client.search("test")
                assert result["success"] is False


class TestFormatSearchResults:
    """検索結果フォーマットのテスト"""

    def test_format_successful_results(self):
        """正常な検索結果のフォーマット"""
        search_result = {
            "success": True,
            "answer": "要約テキスト",
            "results": [
                {
                    "title": "タイトル1",
                    "url": "https://example.com",
                    "content": "内容テキスト",
                },
            ],
            "result_count": 1,
        }
        formatted = format_search_results(search_result)

        assert "【要約】" in formatted
        assert "要約テキスト" in formatted
        assert "【検索結果: 1件】" in formatted
        assert "タイトル1" in formatted
        assert "https://example.com" in formatted
        assert "内容テキスト" in formatted

    def test_format_error_result(self):
        """エラー結果のフォーマット"""
        search_result = {
            "success": False,
            "error": "APIキーが無効です",
            "results": [],
        }
        formatted = format_search_results(search_result)
        assert "検索エラー" in formatted
        assert "APIキーが無効です" in formatted

    def test_format_no_results(self):
        """結果なしのフォーマット"""
        search_result = {
            "success": True,
            "answer": None,
            "results": [],
            "result_count": 0,
        }
        formatted = format_search_results(search_result)
        assert "見つかりませんでした" in formatted

    def test_format_long_content_truncated(self):
        """長いコンテンツは切り詰められる"""
        long_content = "あ" * 500
        search_result = {
            "success": True,
            "answer": None,
            "results": [
                {
                    "title": "テスト",
                    "url": "https://example.com",
                    "content": long_content,
                },
            ],
            "result_count": 1,
        }
        formatted = format_search_results(search_result)
        assert "..." in formatted
        assert len(formatted) < len(long_content) + 200

    def test_format_without_answer(self):
        """AI要約なしのフォーマット"""
        search_result = {
            "success": True,
            "answer": None,
            "results": [
                {
                    "title": "タイトル",
                    "url": "https://example.com",
                    "content": "内容",
                },
            ],
            "result_count": 1,
        }
        formatted = format_search_results(search_result)
        assert "【要約】" not in formatted
        assert "タイトル" in formatted


class TestGetWebSearchClient:
    """シングルトンアクセスのテスト"""

    def test_returns_web_search_client(self):
        """get_web_search_client()はWebSearchClientを返す"""
        # グローバル変数をリセット
        import lib.brain.web_search as ws
        ws._web_search_client = None

        client = get_web_search_client()
        assert isinstance(client, WebSearchClient)

    def test_singleton_returns_same_instance(self):
        """同じインスタンスを返す"""
        import lib.brain.web_search as ws
        ws._web_search_client = None

        client1 = get_web_search_client()
        client2 = get_web_search_client()
        assert client1 is client2


class TestWebSearchResultStructure:
    """検索結果のデータ構造テスト"""

    @patch("lib.brain.web_search.WebSearchClient._get_client")
    def test_result_has_all_required_fields(self, mock_get_client):
        """結果に必要なフィールドが全てある"""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "answer": "answer",
            "results": [{"title": "t", "url": "u", "content": "c"}],
        }
        mock_get_client.return_value = mock_client

        client = WebSearchClient(api_key="test-key")
        result = client.search("test")

        assert "success" in result
        assert "answer" in result
        assert "results" in result
        assert "query" in result
        assert "result_count" in result

    def test_error_result_has_required_fields(self):
        """エラー結果にも必要なフィールドがある"""
        client = WebSearchClient(api_key="")
        with patch.dict("os.environ", {}, clear=True):
            result = client.search("test")

        assert "success" in result
        assert "error" in result
        assert "results" in result
        assert "query" in result
        assert "result_count" in result
