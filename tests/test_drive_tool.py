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
    get_accessible_classifications_for_account,
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

    def test_accessible_classifications_default_is_public_internal(self):
        """accessible_classifications=Noneの場合、['public', 'internal']がデフォルト"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        search_drive_files(
            pool=pool,
            organization_id="org-123",
            query="test",
            accessible_classifications=None,
        )

        # 2回目のexecuteがSELECTクエリ、paramsに cls0/cls1 が含まれること
        calls = mock_conn.execute.call_args_list
        search_call_params = str(calls[1])
        assert "cls0" in search_call_params
        assert "cls1" in search_call_params
        assert "public" in search_call_params
        assert "internal" in search_call_params

    def test_accessible_classifications_invalid_values_filtered(self):
        """ホワイトリスト外の分類値は除外される（SQLインジェクション対策）"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        # 無効な値を渡す
        search_drive_files(
            pool=pool,
            organization_id="org-123",
            query="test",
            accessible_classifications=["super_secret", "admin", "'; DROP TABLE documents;--"],
        )

        # 全て無効 → デフォルト ['public', 'internal'] にフォールバック
        calls = mock_conn.execute.call_args_list
        search_call_params = str(calls[1])
        assert "super_secret" not in search_call_params
        assert "DROP TABLE" not in search_call_params
        assert "public" in search_call_params
        assert "internal" in search_call_params

    def test_accessible_classifications_valid_values_accepted(self):
        """有効な分類値（restricted, confidential等）は受け入れられる"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        search_drive_files(
            pool=pool,
            organization_id="org-123",
            query="test",
            accessible_classifications=["public", "internal", "restricted", "confidential"],
        )

        # 4つ全て有効 → cls0〜cls3 が渡される
        calls = mock_conn.execute.call_args_list
        search_call_params = str(calls[1])
        assert "restricted" in search_call_params
        assert "confidential" in search_call_params

    def test_accessible_classifications_mixed_valid_invalid(self):
        """有効・無効が混在する場合、有効なものだけが残る"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        search_drive_files(
            pool=pool,
            organization_id="org-123",
            query="test",
            accessible_classifications=["public", "invalid_level", "restricted"],
        )

        # "public" と "restricted" は残り、"invalid_level" は除外
        calls = mock_conn.execute.call_args_list
        search_call_params = str(calls[1])
        assert "public" in search_call_params
        assert "restricted" in search_call_params
        assert "invalid_level" not in search_call_params


class TestGetAccessibleClassificationsForAccount:
    """get_accessible_classifications_for_account のテスト"""

    def _make_pool(self, role_level):
        """モックプールを生成する（role_level を返す）"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (role_level,)
        return pool

    def test_level1_2_returns_public_internal(self):
        """権限レベル1-2（一般社員）は public/internal のみ"""
        pool = self._make_pool(2)
        result = get_accessible_classifications_for_account(pool, "12345678", "org-123")
        assert result == ["public", "internal"]

    def test_level3_4_returns_restricted(self):
        """権限レベル3-4（リーダー/幹部）は restricted まで見える"""
        pool = self._make_pool(4)
        result = get_accessible_classifications_for_account(pool, "12345678", "org-123")
        assert result == ["public", "internal", "restricted"]

    def test_level5_6_returns_confidential(self):
        """権限レベル5-6（管理部/代表）は confidential まで見える"""
        pool = self._make_pool(6)
        result = get_accessible_classifications_for_account(pool, "12345678", "org-123")
        assert result == ["public", "internal", "restricted", "confidential"]

    def test_user_not_found_returns_default(self):
        """ユーザーが見つからない場合はデフォルト（最小権限）を返す"""
        pool = MagicMock()
        mock_conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None
        result = get_accessible_classifications_for_account(pool, "99999999", "org-123")
        assert result == ["public", "internal"]

    def test_empty_account_id_returns_default(self):
        """account_idが空の場合はデフォルトを返す（DB呼び出しなし）"""
        pool = MagicMock()
        result = get_accessible_classifications_for_account(pool, "", "org-123")
        assert result == ["public", "internal"]
        pool.connect.assert_not_called()

    def test_db_error_returns_default(self):
        """DB接続エラー時も最小権限でフォールバック"""
        pool = MagicMock()
        pool.connect.side_effect = Exception("DB Error")
        result = get_accessible_classifications_for_account(pool, "12345678", "org-123")
        assert result == ["public", "internal"]


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
