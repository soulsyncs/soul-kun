# lib/capabilities/generation/google_sheets_client.py
"""
Phase G4: スプレッドシート生成能力 - Google Sheets APIクライアント

このモジュールは、Google Sheets APIとのやり取りを担当します。
読み込み・作成・更新・共有をサポート。

設計書: docs/20_next_generation_capabilities.md
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from typing import Optional, Dict, Any, List, Union
import logging
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .constants import (
    GOOGLE_DRIVE_API_VERSION,
    GOOGLE_DRIVE_SCOPES,
)
from .exceptions import (
    GoogleAuthError,
    GoogleAPIError,
)


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================

GOOGLE_SHEETS_API_VERSION = "v4"
GOOGLE_SHEETS_SCOPES = frozenset([
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
])


# =============================================================================
# 例外
# =============================================================================


class GoogleSheetsError(GoogleAPIError):
    """Google Sheets API エラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "SHEETS_ERROR",
        spreadsheet_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            api_name="Google Sheets",
            details={"spreadsheet_id": spreadsheet_id, **(details or {})},
            original_error=original_error,
        )
        self.spreadsheet_id = spreadsheet_id


class GoogleSheetsCreateError(GoogleSheetsError):
    """スプレッドシート作成エラー"""

    def __init__(
        self,
        title: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Failed to create spreadsheet: {title}",
            error_code="SHEETS_CREATE_FAILED",
            details={"title": title},
            original_error=original_error,
        )
        self.title = title

    def to_user_message(self) -> str:
        return "スプレッドシートの作成に失敗しました。"


class GoogleSheetsReadError(GoogleSheetsError):
    """スプレッドシート読み込みエラー"""

    def __init__(
        self,
        spreadsheet_id: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Failed to read spreadsheet: {spreadsheet_id}",
            error_code="SHEETS_READ_FAILED",
            spreadsheet_id=spreadsheet_id,
            original_error=original_error,
        )

    def to_user_message(self) -> str:
        return "スプレッドシートの読み込みに失敗しました。"


class GoogleSheetsUpdateError(GoogleSheetsError):
    """スプレッドシート更新エラー"""

    def __init__(
        self,
        spreadsheet_id: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Failed to update spreadsheet: {spreadsheet_id}",
            error_code="SHEETS_UPDATE_FAILED",
            spreadsheet_id=spreadsheet_id,
            original_error=original_error,
        )

    def to_user_message(self) -> str:
        return "スプレッドシートの更新に失敗しました。"


# =============================================================================
# Google Sheets APIクライアント
# =============================================================================


class GoogleSheetsClient:
    """
    Google Sheets APIクライアント

    スプレッドシートの読み込み・作成・更新・共有を行う。

    使用例:
        client = GoogleSheetsClient()

        # 読み込み
        data = await client.read_sheet(spreadsheet_id, "Sheet1!A1:D10")

        # 作成
        result = await client.create_spreadsheet("売上レポート")

        # 書き込み
        await client.write_sheet(spreadsheet_id, "Sheet1!A1", [["A", "B"], [1, 2]])
    """

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        credentials_json: Optional[Dict[str, Any]] = None,
    ):
        """
        初期化

        Args:
            credentials_path: サービスアカウントJSONファイルのパス
            credentials_json: サービスアカウントJSONの内容（辞書形式）
        """
        self._credentials_path = credentials_path or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        self._credentials_json = credentials_json
        self._sheets_service = None
        self._drive_service = None
        self._credentials = None

    def _get_credentials(self):
        """認証情報を取得"""
        if self._credentials:
            return self._credentials

        try:
            scopes = list(GOOGLE_SHEETS_SCOPES | GOOGLE_DRIVE_SCOPES)

            if self._credentials_json:
                self._credentials = service_account.Credentials.from_service_account_info(
                    self._credentials_json,
                    scopes=scopes,
                )
            elif self._credentials_path:
                self._credentials = service_account.Credentials.from_service_account_file(
                    self._credentials_path,
                    scopes=scopes,
                )
            else:
                raise GoogleAuthError(
                    details={"reason": "No credentials provided"}
                )

            return self._credentials

        except Exception as e:
            logger.error(f"Google auth failed: {str(e)}")
            raise GoogleAuthError(original_error=e)

    def _get_sheets_service(self):
        """Sheets APIサービスを取得"""
        if self._sheets_service:
            return self._sheets_service

        credentials = self._get_credentials()
        self._sheets_service = build(
            "sheets",
            GOOGLE_SHEETS_API_VERSION,
            credentials=credentials,
        )
        return self._sheets_service

    def _get_drive_service(self):
        """Drive APIサービスを取得"""
        if self._drive_service:
            return self._drive_service

        credentials = self._get_credentials()
        self._drive_service = build(
            "drive",
            GOOGLE_DRIVE_API_VERSION,
            credentials=credentials,
        )
        return self._drive_service

    # =========================================================================
    # 読み込み
    # =========================================================================

    async def read_sheet(
        self,
        spreadsheet_id: str,
        range_notation: str = "Sheet1",
        value_render_option: str = "FORMATTED_VALUE",
    ) -> List[List[Any]]:
        """
        スプレッドシートのデータを読み込む

        Args:
            spreadsheet_id: スプレッドシートID
            range_notation: 範囲指定（例: "Sheet1!A1:D10", "Sheet1"）
            value_render_option: 値のフォーマット
                - FORMATTED_VALUE: 表示されている値
                - UNFORMATTED_VALUE: 生の値
                - FORMULA: 数式

        Returns:
            2次元配列のデータ
        """
        try:
            sheets_service = self._get_sheets_service()

            result = sheets_service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueRenderOption=value_render_option,
            ).execute()

            values = result.get("values", [])
            logger.info(
                f"Read {len(values)} rows from spreadsheet {spreadsheet_id}"
            )
            return values

        except HttpError as e:
            logger.error(f"Failed to read spreadsheet: {str(e)}")
            raise GoogleSheetsReadError(
                spreadsheet_id=spreadsheet_id,
                original_error=e,
            )

    async def get_spreadsheet_info(
        self,
        spreadsheet_id: str,
    ) -> Dict[str, Any]:
        """
        スプレッドシートのメタデータを取得

        Args:
            spreadsheet_id: スプレッドシートID

        Returns:
            タイトル、シート一覧などのメタデータ
        """
        try:
            sheets_service = self._get_sheets_service()

            result = sheets_service.spreadsheets().get(
                spreadsheetId=spreadsheet_id,
            ).execute()

            sheets = []
            for sheet in result.get("sheets", []):
                props = sheet.get("properties", {})
                sheets.append({
                    "sheet_id": props.get("sheetId"),
                    "title": props.get("title"),
                    "index": props.get("index"),
                    "row_count": props.get("gridProperties", {}).get("rowCount"),
                    "column_count": props.get("gridProperties", {}).get("columnCount"),
                })

            return {
                "spreadsheet_id": spreadsheet_id,
                "title": result.get("properties", {}).get("title"),
                "url": result.get("spreadsheetUrl"),
                "sheets": sheets,
            }

        except HttpError as e:
            logger.error(f"Failed to get spreadsheet info: {str(e)}")
            raise GoogleSheetsReadError(
                spreadsheet_id=spreadsheet_id,
                original_error=e,
            )

    async def read_all_sheets(
        self,
        spreadsheet_id: str,
    ) -> Dict[str, List[List[Any]]]:
        """
        全シートのデータを読み込む

        Args:
            spreadsheet_id: スプレッドシートID

        Returns:
            {シート名: データ}の辞書
        """
        info = await self.get_spreadsheet_info(spreadsheet_id)
        result = {}

        for sheet in info.get("sheets", []):
            sheet_name = sheet.get("title")
            if sheet_name:
                data = await self.read_sheet(spreadsheet_id, sheet_name)
                result[sheet_name] = data

        return result

    # =========================================================================
    # 作成
    # =========================================================================

    async def create_spreadsheet(
        self,
        title: str,
        sheet_names: Optional[List[str]] = None,
        folder_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        新規スプレッドシートを作成

        Args:
            title: スプレッドシートのタイトル
            sheet_names: シート名のリスト（省略時は"Sheet1"のみ）
            folder_id: 配置先フォルダID

        Returns:
            {"spreadsheet_id": "...", "spreadsheet_url": "..."}
        """
        try:
            sheets_service = self._get_sheets_service()

            # シート設定
            sheets = []
            if sheet_names:
                for i, name in enumerate(sheet_names):
                    sheets.append({
                        "properties": {
                            "title": name,
                            "index": i,
                        }
                    })

            body = {
                "properties": {"title": title},
            }
            if sheets:
                body["sheets"] = sheets

            # 作成
            spreadsheet = sheets_service.spreadsheets().create(
                body=body
            ).execute()

            spreadsheet_id = spreadsheet.get("spreadsheetId")
            spreadsheet_url = spreadsheet.get("spreadsheetUrl")

            logger.info(f"Created spreadsheet: {spreadsheet_id}")

            # フォルダに移動（指定がある場合）
            if folder_id:
                await self._move_to_folder(spreadsheet_id, folder_id)

            return {
                "spreadsheet_id": spreadsheet_id,
                "spreadsheet_url": spreadsheet_url,
            }

        except HttpError as e:
            logger.error(f"Failed to create spreadsheet: {str(e)}")
            raise GoogleSheetsCreateError(
                title=title,
                original_error=e,
            )

    # =========================================================================
    # 書き込み
    # =========================================================================

    async def write_sheet(
        self,
        spreadsheet_id: str,
        range_notation: str,
        values: List[List[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> Dict[str, Any]:
        """
        スプレッドシートにデータを書き込む

        Args:
            spreadsheet_id: スプレッドシートID
            range_notation: 範囲指定（例: "Sheet1!A1"）
            values: 2次元配列のデータ
            value_input_option: 入力オプション
                - USER_ENTERED: ユーザー入力として解釈（数式も認識）
                - RAW: そのまま文字列として

        Returns:
            更新結果
        """
        try:
            sheets_service = self._get_sheets_service()

            body = {"values": values}

            result = sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueInputOption=value_input_option,
                body=body,
            ).execute()

            logger.info(
                f"Updated {result.get('updatedCells', 0)} cells in {spreadsheet_id}"
            )

            return {
                "updated_range": result.get("updatedRange"),
                "updated_rows": result.get("updatedRows"),
                "updated_columns": result.get("updatedColumns"),
                "updated_cells": result.get("updatedCells"),
            }

        except HttpError as e:
            logger.error(f"Failed to write spreadsheet: {str(e)}")
            raise GoogleSheetsUpdateError(
                spreadsheet_id=spreadsheet_id,
                original_error=e,
            )

    async def append_sheet(
        self,
        spreadsheet_id: str,
        range_notation: str,
        values: List[List[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> Dict[str, Any]:
        """
        スプレッドシートにデータを追記

        Args:
            spreadsheet_id: スプレッドシートID
            range_notation: 範囲指定（例: "Sheet1!A1"）
            values: 追加するデータ
            value_input_option: 入力オプション

        Returns:
            更新結果
        """
        try:
            sheets_service = self._get_sheets_service()

            body = {"values": values}

            result = sheets_service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueInputOption=value_input_option,
                insertDataOption="INSERT_ROWS",
                body=body,
            ).execute()

            updates = result.get("updates", {})
            logger.info(
                f"Appended {updates.get('updatedRows', 0)} rows to {spreadsheet_id}"
            )

            return {
                "updated_range": updates.get("updatedRange"),
                "updated_rows": updates.get("updatedRows"),
                "updated_columns": updates.get("updatedColumns"),
                "updated_cells": updates.get("updatedCells"),
            }

        except HttpError as e:
            logger.error(f"Failed to append to spreadsheet: {str(e)}")
            raise GoogleSheetsUpdateError(
                spreadsheet_id=spreadsheet_id,
                original_error=e,
            )

    async def clear_sheet(
        self,
        spreadsheet_id: str,
        range_notation: str,
    ) -> bool:
        """
        指定範囲をクリア

        Args:
            spreadsheet_id: スプレッドシートID
            range_notation: 範囲指定

        Returns:
            成功したかどうか
        """
        try:
            sheets_service = self._get_sheets_service()

            sheets_service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
            ).execute()

            logger.info(f"Cleared {range_notation} in {spreadsheet_id}")
            return True

        except HttpError as e:
            logger.error(f"Failed to clear spreadsheet: {str(e)}")
            raise GoogleSheetsUpdateError(
                spreadsheet_id=spreadsheet_id,
                original_error=e,
            )

    # =========================================================================
    # シート操作
    # =========================================================================

    async def add_sheet(
        self,
        spreadsheet_id: str,
        sheet_name: str,
    ) -> int:
        """
        新しいシートを追加

        Args:
            spreadsheet_id: スプレッドシートID
            sheet_name: シート名

        Returns:
            新しいシートのID
        """
        try:
            sheets_service = self._get_sheets_service()

            request = {
                "addSheet": {
                    "properties": {
                        "title": sheet_name,
                    }
                }
            }

            result = sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [request]},
            ).execute()

            sheet_id = result.get("replies", [{}])[0].get(
                "addSheet", {}
            ).get("properties", {}).get("sheetId")

            logger.info(f"Added sheet '{sheet_name}' to {spreadsheet_id}")
            return sheet_id

        except HttpError as e:
            logger.error(f"Failed to add sheet: {str(e)}")
            raise GoogleSheetsUpdateError(
                spreadsheet_id=spreadsheet_id,
                original_error=e,
            )

    async def delete_sheet(
        self,
        spreadsheet_id: str,
        sheet_id: int,
    ) -> bool:
        """
        シートを削除

        Args:
            spreadsheet_id: スプレッドシートID
            sheet_id: シートID

        Returns:
            成功したかどうか
        """
        try:
            sheets_service = self._get_sheets_service()

            request = {
                "deleteSheet": {
                    "sheetId": sheet_id,
                }
            }

            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [request]},
            ).execute()

            logger.info(f"Deleted sheet {sheet_id} from {spreadsheet_id}")
            return True

        except HttpError as e:
            logger.error(f"Failed to delete sheet: {str(e)}")
            raise GoogleSheetsUpdateError(
                spreadsheet_id=spreadsheet_id,
                original_error=e,
            )

    # =========================================================================
    # 共有
    # =========================================================================

    async def share_spreadsheet(
        self,
        spreadsheet_id: str,
        email_addresses: List[str],
        role: str = "reader",
    ) -> bool:
        """
        スプレッドシートを共有

        Args:
            spreadsheet_id: スプレッドシートID
            email_addresses: 共有先メールアドレスのリスト
            role: 権限（"reader", "writer", "commenter"）

        Returns:
            成功したかどうか
        """
        try:
            drive_service = self._get_drive_service()

            for email in email_addresses:
                permission = {
                    "type": "user",
                    "role": role,
                    "emailAddress": email,
                }
                drive_service.permissions().create(
                    fileId=spreadsheet_id,
                    body=permission,
                    sendNotificationEmail=False,
                ).execute()

            logger.info(
                f"Shared spreadsheet {spreadsheet_id} with {len(email_addresses)} users"
            )
            return True

        except HttpError as e:
            logger.error(f"Failed to share spreadsheet: {str(e)}")
            raise GoogleSheetsUpdateError(
                spreadsheet_id=spreadsheet_id,
                original_error=e,
            )

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    async def _move_to_folder(
        self,
        spreadsheet_id: str,
        folder_id: str,
    ) -> bool:
        """フォルダに移動"""
        try:
            drive_service = self._get_drive_service()

            file = drive_service.files().get(
                fileId=spreadsheet_id,
                fields="parents",
            ).execute()
            previous_parents = ",".join(file.get("parents", []))

            drive_service.files().update(
                fileId=spreadsheet_id,
                addParents=folder_id,
                removeParents=previous_parents,
                fields="id, parents",
            ).execute()

            logger.info(f"Moved spreadsheet {spreadsheet_id} to folder {folder_id}")
            return True

        except HttpError as e:
            logger.warning(f"Failed to move spreadsheet to folder: {str(e)}")
            return False

    def to_markdown_table(self, data: List[List[Any]]) -> str:
        """
        データをMarkdownテーブルに変換

        Args:
            data: 2次元配列（最初の行がヘッダー）

        Returns:
            Markdownテーブル文字列
        """
        if not data:
            return ""

        lines = []

        # ヘッダー
        header = data[0]
        lines.append("| " + " | ".join(str(cell) for cell in header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")

        # データ行
        for row in data[1:]:
            # 行の長さをヘッダーに合わせる
            padded_row = list(row) + [""] * (len(header) - len(row))
            lines.append("| " + " | ".join(str(cell) for cell in padded_row[:len(header)]) + " |")

        return "\n".join(lines)


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_google_sheets_client(
    credentials_path: Optional[str] = None,
    credentials_json: Optional[Dict[str, Any]] = None,
) -> GoogleSheetsClient:
    """
    GoogleSheetsClientを作成

    Args:
        credentials_path: サービスアカウントJSONファイルのパス
        credentials_json: サービスアカウントJSONの内容

    Returns:
        GoogleSheetsClient
    """
    return GoogleSheetsClient(
        credentials_path=credentials_path,
        credentials_json=credentials_json,
    )
