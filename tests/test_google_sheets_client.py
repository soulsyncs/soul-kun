# tests/test_google_sheets_client.py
"""
Phase G4: Google Sheets クライアントのテスト

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from uuid import uuid4

# テスト対象のインポート
from lib.capabilities.generation import (
    GoogleSheetsClient,
    GoogleSheetsError,
    GoogleSheetsCreateError,
    GoogleSheetsReadError,
    GoogleSheetsUpdateError,
    create_google_sheets_client,
)
from lib.capabilities.generation.google_sheets_client import (
    GOOGLE_SHEETS_API_VERSION,
    GOOGLE_SHEETS_SCOPES,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_credentials():
    """モック認証情報"""
    return {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test-key-id",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----\n",
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


@pytest.fixture
def sheets_client(mock_credentials):
    """テスト用クライアント"""
    return GoogleSheetsClient(credentials_json=mock_credentials)


@pytest.fixture
def spreadsheet_id():
    """テスト用スプレッドシートID"""
    return "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_api_version(self):
        """APIバージョン"""
        assert GOOGLE_SHEETS_API_VERSION == "v4"

    def test_scopes(self):
        """スコープ"""
        assert "https://www.googleapis.com/auth/spreadsheets" in GOOGLE_SHEETS_SCOPES
        assert "https://www.googleapis.com/auth/drive.file" in GOOGLE_SHEETS_SCOPES


# =============================================================================
# 例外テスト
# =============================================================================


class TestExceptions:
    """例外のテスト"""

    def test_google_sheets_error(self):
        """GoogleSheetsError"""
        error = GoogleSheetsError(
            message="Test error",
            error_code="TEST_ERROR",
            spreadsheet_id="test-id",
        )
        assert str(error) == "Test error"
        assert error.error_code == "TEST_ERROR"
        assert error.spreadsheet_id == "test-id"

    def test_google_sheets_create_error(self):
        """GoogleSheetsCreateError"""
        error = GoogleSheetsCreateError(title="Test Sheet")
        assert "Test Sheet" in str(error)
        assert error.error_code == "SHEETS_CREATE_FAILED"
        assert "作成に失敗" in error.to_user_message()

    def test_google_sheets_read_error(self):
        """GoogleSheetsReadError"""
        error = GoogleSheetsReadError(spreadsheet_id="test-id")
        assert "test-id" in str(error)
        assert error.error_code == "SHEETS_READ_FAILED"
        assert "読み込みに失敗" in error.to_user_message()

    def test_google_sheets_update_error(self):
        """GoogleSheetsUpdateError"""
        error = GoogleSheetsUpdateError(spreadsheet_id="test-id")
        assert "test-id" in str(error)
        assert error.error_code == "SHEETS_UPDATE_FAILED"
        assert "更新に失敗" in error.to_user_message()


# =============================================================================
# クライアント初期化テスト
# =============================================================================


class TestClientInitialization:
    """クライアント初期化のテスト"""

    def test_init_with_credentials_json(self, mock_credentials):
        """JSON認証情報での初期化"""
        client = GoogleSheetsClient(credentials_json=mock_credentials)
        assert client._credentials_json == mock_credentials
        assert client._sheets_service is None

    def test_init_with_credentials_path(self):
        """ファイルパスでの初期化"""
        client = GoogleSheetsClient(credentials_path="/path/to/credentials.json")
        assert client._credentials_path == "/path/to/credentials.json"

    def test_create_google_sheets_client_factory(self, mock_credentials):
        """ファクトリ関数"""
        client = create_google_sheets_client(credentials_json=mock_credentials)
        assert isinstance(client, GoogleSheetsClient)


# =============================================================================
# 読み込みテスト
# =============================================================================


class TestReadOperations:
    """読み込み操作のテスト"""

    @pytest.mark.asyncio
    async def test_read_sheet(self, sheets_client, spreadsheet_id):
        """シート読み込み"""
        mock_values = [
            ["Name", "Age", "City"],
            ["Alice", "30", "Tokyo"],
            ["Bob", "25", "Osaka"],
        ]

        with patch.object(sheets_client, "_get_sheets_service") as mock_service:
            mock_sheets = Mock()
            mock_service.return_value = mock_sheets
            mock_sheets.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
                "values": mock_values
            }

            result = await sheets_client.read_sheet(spreadsheet_id, "Sheet1!A1:C3")

            assert result == mock_values
            assert len(result) == 3
            assert result[0][0] == "Name"

    @pytest.mark.asyncio
    async def test_read_sheet_empty(self, sheets_client, spreadsheet_id):
        """空のシート読み込み"""
        with patch.object(sheets_client, "_get_sheets_service") as mock_service:
            mock_sheets = Mock()
            mock_service.return_value = mock_sheets
            mock_sheets.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {}

            result = await sheets_client.read_sheet(spreadsheet_id)

            assert result == []

    @pytest.mark.asyncio
    async def test_get_spreadsheet_info(self, sheets_client, spreadsheet_id):
        """スプレッドシート情報取得"""
        mock_response = {
            "properties": {"title": "Test Spreadsheet"},
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/xxx",
            "sheets": [
                {
                    "properties": {
                        "sheetId": 0,
                        "title": "Sheet1",
                        "index": 0,
                        "gridProperties": {"rowCount": 1000, "columnCount": 26},
                    }
                },
                {
                    "properties": {
                        "sheetId": 1,
                        "title": "Sheet2",
                        "index": 1,
                        "gridProperties": {"rowCount": 500, "columnCount": 10},
                    }
                },
            ],
        }

        with patch.object(sheets_client, "_get_sheets_service") as mock_service:
            mock_sheets = Mock()
            mock_service.return_value = mock_sheets
            mock_sheets.spreadsheets.return_value.get.return_value.execute.return_value = mock_response

            result = await sheets_client.get_spreadsheet_info(spreadsheet_id)

            assert result["title"] == "Test Spreadsheet"
            assert len(result["sheets"]) == 2
            assert result["sheets"][0]["title"] == "Sheet1"
            assert result["sheets"][1]["row_count"] == 500

    @pytest.mark.asyncio
    async def test_read_all_sheets(self, sheets_client, spreadsheet_id):
        """全シート読み込み"""
        with patch.object(sheets_client, "get_spreadsheet_info") as mock_info:
            mock_info.return_value = {
                "sheets": [
                    {"title": "Sheet1"},
                    {"title": "Sheet2"},
                ]
            }

            with patch.object(sheets_client, "read_sheet") as mock_read:
                mock_read.side_effect = [
                    [["A", "B"], [1, 2]],
                    [["X", "Y"], [3, 4]],
                ]

                result = await sheets_client.read_all_sheets(spreadsheet_id)

                assert "Sheet1" in result
                assert "Sheet2" in result
                assert result["Sheet1"] == [["A", "B"], [1, 2]]


# =============================================================================
# 作成テスト
# =============================================================================


class TestCreateOperations:
    """作成操作のテスト"""

    @pytest.mark.asyncio
    async def test_create_spreadsheet(self, sheets_client):
        """スプレッドシート作成"""
        mock_response = {
            "spreadsheetId": "new-spreadsheet-id",
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/new-spreadsheet-id",
        }

        with patch.object(sheets_client, "_get_sheets_service") as mock_service:
            mock_sheets = Mock()
            mock_service.return_value = mock_sheets
            mock_sheets.spreadsheets.return_value.create.return_value.execute.return_value = mock_response

            result = await sheets_client.create_spreadsheet("新規スプレッドシート")

            assert result["spreadsheet_id"] == "new-spreadsheet-id"
            assert "spreadsheet_url" in result

    @pytest.mark.asyncio
    async def test_create_spreadsheet_with_sheets(self, sheets_client):
        """複数シートで作成"""
        mock_response = {
            "spreadsheetId": "new-id",
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/new-id",
        }

        with patch.object(sheets_client, "_get_sheets_service") as mock_service:
            mock_sheets = Mock()
            mock_service.return_value = mock_sheets
            mock_sheets.spreadsheets.return_value.create.return_value.execute.return_value = mock_response

            result = await sheets_client.create_spreadsheet(
                "Test",
                sheet_names=["売上", "経費", "サマリー"],
            )

            assert result["spreadsheet_id"] == "new-id"
            # createが呼ばれた際のbodyを検証
            call_args = mock_sheets.spreadsheets.return_value.create.call_args
            body = call_args.kwargs.get("body", call_args[1].get("body") if len(call_args) > 1 else {})
            assert body.get("properties", {}).get("title") == "Test"


# =============================================================================
# 書き込みテスト
# =============================================================================


class TestWriteOperations:
    """書き込み操作のテスト"""

    @pytest.mark.asyncio
    async def test_write_sheet(self, sheets_client, spreadsheet_id):
        """データ書き込み"""
        mock_response = {
            "updatedRange": "Sheet1!A1:C3",
            "updatedRows": 3,
            "updatedColumns": 3,
            "updatedCells": 9,
        }

        with patch.object(sheets_client, "_get_sheets_service") as mock_service:
            mock_sheets = Mock()
            mock_service.return_value = mock_sheets
            mock_sheets.spreadsheets.return_value.values.return_value.update.return_value.execute.return_value = mock_response

            values = [["A", "B", "C"], [1, 2, 3], [4, 5, 6]]
            result = await sheets_client.write_sheet(spreadsheet_id, "Sheet1!A1", values)

            assert result["updated_cells"] == 9
            assert result["updated_rows"] == 3

    @pytest.mark.asyncio
    async def test_append_sheet(self, sheets_client, spreadsheet_id):
        """データ追記"""
        mock_response = {
            "updates": {
                "updatedRange": "Sheet1!A4:C4",
                "updatedRows": 1,
                "updatedColumns": 3,
                "updatedCells": 3,
            }
        }

        with patch.object(sheets_client, "_get_sheets_service") as mock_service:
            mock_sheets = Mock()
            mock_service.return_value = mock_sheets
            mock_sheets.spreadsheets.return_value.values.return_value.append.return_value.execute.return_value = mock_response

            values = [[7, 8, 9]]
            result = await sheets_client.append_sheet(spreadsheet_id, "Sheet1!A1", values)

            assert result["updated_cells"] == 3
            assert result["updated_rows"] == 1

    @pytest.mark.asyncio
    async def test_clear_sheet(self, sheets_client, spreadsheet_id):
        """範囲クリア"""
        with patch.object(sheets_client, "_get_sheets_service") as mock_service:
            mock_sheets = Mock()
            mock_service.return_value = mock_sheets
            mock_sheets.spreadsheets.return_value.values.return_value.clear.return_value.execute.return_value = {}

            result = await sheets_client.clear_sheet(spreadsheet_id, "Sheet1!A1:C10")

            assert result is True


# =============================================================================
# シート操作テスト
# =============================================================================


class TestSheetOperations:
    """シート操作のテスト"""

    @pytest.mark.asyncio
    async def test_add_sheet(self, sheets_client, spreadsheet_id):
        """シート追加"""
        mock_response = {
            "replies": [
                {
                    "addSheet": {
                        "properties": {
                            "sheetId": 12345,
                            "title": "新しいシート",
                        }
                    }
                }
            ]
        }

        with patch.object(sheets_client, "_get_sheets_service") as mock_service:
            mock_sheets = Mock()
            mock_service.return_value = mock_sheets
            mock_sheets.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = mock_response

            result = await sheets_client.add_sheet(spreadsheet_id, "新しいシート")

            assert result == 12345

    @pytest.mark.asyncio
    async def test_delete_sheet(self, sheets_client, spreadsheet_id):
        """シート削除"""
        with patch.object(sheets_client, "_get_sheets_service") as mock_service:
            mock_sheets = Mock()
            mock_service.return_value = mock_sheets
            mock_sheets.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}

            result = await sheets_client.delete_sheet(spreadsheet_id, 12345)

            assert result is True


# =============================================================================
# 共有テスト
# =============================================================================


class TestShareOperations:
    """共有操作のテスト"""

    @pytest.mark.asyncio
    async def test_share_spreadsheet(self, sheets_client, spreadsheet_id):
        """スプレッドシート共有"""
        with patch.object(sheets_client, "_get_drive_service") as mock_service:
            mock_drive = Mock()
            mock_service.return_value = mock_drive
            mock_drive.permissions.return_value.create.return_value.execute.return_value = {}

            result = await sheets_client.share_spreadsheet(
                spreadsheet_id,
                ["user1@example.com", "user2@example.com"],
                role="writer",
            )

            assert result is True
            assert mock_drive.permissions.return_value.create.call_count == 2


# =============================================================================
# ユーティリティテスト
# =============================================================================


class TestUtilities:
    """ユーティリティのテスト"""

    def test_to_markdown_table(self, sheets_client):
        """Markdownテーブル変換"""
        data = [
            ["名前", "年齢", "都市"],
            ["太郎", "30", "東京"],
            ["花子", "25", "大阪"],
        ]

        result = sheets_client.to_markdown_table(data)

        assert "| 名前 | 年齢 | 都市 |" in result
        assert "| --- | --- | --- |" in result
        assert "| 太郎 | 30 | 東京 |" in result
        assert "| 花子 | 25 | 大阪 |" in result

    def test_to_markdown_table_empty(self, sheets_client):
        """空データのMarkdown変換"""
        result = sheets_client.to_markdown_table([])
        assert result == ""

    def test_to_markdown_table_uneven_rows(self, sheets_client):
        """不揃いな行数のMarkdown変換"""
        data = [
            ["A", "B", "C"],
            ["1", "2"],  # 列が足りない
            ["X", "Y", "Z", "W"],  # 列が多い
        ]

        result = sheets_client.to_markdown_table(data)

        # ヘッダーの列数に合わせる
        lines = result.split("\n")
        assert len(lines[2].split("|")) == len(lines[0].split("|"))


# =============================================================================
# パッケージインポートテスト
# =============================================================================


class TestPackageImports:
    """パッケージインポートのテスト"""

    def test_import_client(self):
        """クライアントのインポート"""
        from lib.capabilities.generation import (
            GoogleSheetsClient,
            create_google_sheets_client,
        )
        assert GoogleSheetsClient is not None
        assert create_google_sheets_client is not None

    def test_import_exceptions(self):
        """例外のインポート"""
        from lib.capabilities.generation import (
            GoogleSheetsError,
            GoogleSheetsCreateError,
            GoogleSheetsReadError,
            GoogleSheetsUpdateError,
        )
        assert GoogleSheetsError is not None
        assert GoogleSheetsCreateError is not None
        assert GoogleSheetsReadError is not None
        assert GoogleSheetsUpdateError is not None
