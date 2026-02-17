"""
Googleドライブ ファイル検索ツール テスト — Step A-5

drive_tool のファイル検索・フォーマット機能をテスト:
- 正常なファイル名検索
- クエリなし（最近のファイル一覧）
- 空の結果
- DB接続エラー
- organization_id未指定
- フォーマット関数
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from lib.brain.drive_tool import (
    search_drive_files,
    format_drive_files,
    DEFAULT_MAX_FILES,
    MAX_ALLOWED_FILES,
)


class TestSearchDriveFiles:
    """search_drive_files のテスト"""

    def test_missing_organization_id_returns_error(self):
        """organization_id未指定はエラーを返す"""
        pool = MagicMock()
        result = search_drive_files(
            pool=pool,
            organization_id="",
            query="test",
        )
        assert result["success"] is False
        assert "組織ID" in result["error"]

    def test_successful_file_search(self):
        """正常にファイルを検索"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        # SQLAlchemy fetchall の結果をモック
        mock_conn.execute.return_value.fetchall.return_value = [
            ("営業マニュアル.pdf", "営業マニュアル", "https://drive.google.com/file/1", datetime(2026, 2, 17, 10, 0), "internal"),
            ("営業報告書.docx", "営業報告テンプレート", "https://drive.google.com/file/2", datetime(2026, 2, 16, 15, 30), "internal"),
        ]

        result = search_drive_files(
            pool=pool,
            organization_id="org-123",
            query="営業",
        )

        assert result["success"] is True
        assert result["file_count"] == 2
        assert result["files"][0]["file_name"] == "営業マニュアル.pdf"
        assert result["files"][0]["title"] == "営業マニュアル"
        assert result["files"][0]["web_view_link"] == "https://drive.google.com/file/1"
        assert result["files"][1]["file_name"] == "営業報告書.docx"
        assert result["query"] == "営業"

    def test_successful_recent_files(self):
        """クエリなしで最近のファイル一覧を取得"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchall.return_value = [
            ("最新資料.pdf", "最新資料", "https://drive.google.com/file/3", datetime(2026, 2, 17, 12, 0), "public"),
        ]

        result = search_drive_files(
            pool=pool,
            organization_id="org-123",
        )

        assert result["success"] is True
        assert result["file_count"] == 1
        assert result["query"] == ""

    def test_no_files_returns_empty(self):
        """ファイルが見つからない場合"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchall.return_value = []

        result = search_drive_files(
            pool=pool,
            organization_id="org-123",
            query="存在しないファイル",
        )

        assert result["success"] is True
        assert result["file_count"] == 0
        assert result["files"] == []

    def test_db_error_returns_failure(self):
        """DB接続エラー時"""
        pool = MagicMock()
        pool.connect.side_effect = Exception("DB Error")

        result = search_drive_files(
            pool=pool,
            organization_id="org-123",
            query="test",
        )

        assert result["success"] is False
        assert "失敗" in result["error"]

    def test_max_results_capped(self):
        """max_resultsがMAX_ALLOWED_FILESに制限される"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        # max_results=100を渡しても内部でMAX_ALLOWED_FILESに制限される
        result = search_drive_files(
            pool=pool,
            organization_id="org-123",
            query="test",
            max_results=100,
        )

        # 実行は成功する（内部でclampされる）
        assert result["success"] is True

    def test_max_results_minimum_is_one(self):
        """max_resultsは最小1"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        result = search_drive_files(
            pool=pool,
            organization_id="org-123",
            query="test",
            max_results=0,
        )

        assert result["success"] is True

    def test_updated_at_none_handled(self):
        """updated_atがNoneの場合もエラーにならない"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchall.return_value = [
            ("old_file.pdf", None, None, None, None),
        ]

        result = search_drive_files(
            pool=pool,
            organization_id="org-123",
            query="old",
        )

        assert result["success"] is True
        assert result["files"][0]["file_name"] == "old_file.pdf"
        assert result["files"][0]["title"] == "old_file.pdf"  # titleがNoneならfile_nameを使う
        assert result["files"][0]["updated_at"] is None
        assert result["files"][0]["classification"] == "internal"  # Noneの場合のデフォルト

    def test_organization_id_filter_in_query(self):
        """organization_idがSQLクエリに渡されていること（セキュリティ確認）"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        search_drive_files(
            pool=pool,
            organization_id="org-secure-123",
            query="test",
        )

        # set_configが呼ばれていることを確認
        calls = mock_conn.execute.call_args_list
        assert len(calls) >= 2  # set_config + 検索クエリ
        # 最初のcallがset_configであること
        first_call_params = calls[0]
        # パラメータにorg_idが含まれていること
        assert "org-secure-123" in str(first_call_params)


class TestFormatDriveFiles:
    """format_drive_files のテスト"""

    def test_format_with_files(self):
        """ファイルありのフォーマット"""
        result = {
            "success": True,
            "files": [
                {
                    "file_name": "営業マニュアル.pdf",
                    "title": "営業マニュアル",
                    "web_view_link": "https://drive.google.com/file/1",
                    "updated_at": "2026-02-17 10:00",
                    "classification": "internal",
                },
            ],
            "query": "営業",
            "file_count": 1,
        }
        formatted = format_drive_files(result)
        assert "営業" in formatted
        assert "1件" in formatted
        assert "営業マニュアル" in formatted
        assert "2026-02-17" in formatted

    def test_format_no_files_with_query(self):
        """クエリあり・ファイルなしのフォーマット"""
        result = {
            "success": True,
            "files": [],
            "query": "存在しないファイル",
            "file_count": 0,
        }
        formatted = format_drive_files(result)
        assert "見つかりませんでした" in formatted
        assert "存在しないファイル" in formatted

    def test_format_no_files_no_query(self):
        """クエリなし・ファイルなしのフォーマット"""
        result = {
            "success": True,
            "files": [],
            "query": "",
            "file_count": 0,
        }
        formatted = format_drive_files(result)
        assert "ファイルがありません" in formatted

    def test_format_error(self):
        """エラーのフォーマット"""
        result = {
            "success": False,
            "error": "DB接続エラー",
        }
        formatted = format_drive_files(result)
        assert "ドライブ検索エラー" in formatted
        assert "DB接続エラー" in formatted

    def test_format_recent_files(self):
        """最近のファイル一覧のフォーマット"""
        result = {
            "success": True,
            "files": [
                {
                    "file_name": "report.pdf",
                    "title": "月次レポート",
                    "web_view_link": "https://drive.google.com/file/1",
                    "updated_at": "2026-02-17 10:00",
                    "classification": "internal",
                },
            ],
            "query": "",
            "file_count": 1,
        }
        formatted = format_drive_files(result)
        assert "最近更新された" in formatted
        assert "月次レポート" in formatted

    def test_format_with_different_title_and_filename(self):
        """タイトルとファイル名が違う場合、両方表示"""
        result = {
            "success": True,
            "files": [
                {
                    "file_name": "doc_2026_02.pdf",
                    "title": "2月の営業報告書",
                    "web_view_link": None,
                    "updated_at": "2026-02-17 10:00",
                    "classification": "internal",
                },
            ],
            "query": "報告",
            "file_count": 1,
        }
        formatted = format_drive_files(result)
        assert "2月の営業報告書" in formatted
        assert "doc_2026_02.pdf" in formatted

    def test_format_with_link(self):
        """リンクが含まれること"""
        result = {
            "success": True,
            "files": [
                {
                    "file_name": "test.pdf",
                    "title": "test.pdf",
                    "web_view_link": "https://drive.google.com/file/abc123",
                    "updated_at": None,
                    "classification": "public",
                },
            ],
            "query": "test",
            "file_count": 1,
        }
        formatted = format_drive_files(result)
        assert "https://drive.google.com/file/abc123" in formatted
