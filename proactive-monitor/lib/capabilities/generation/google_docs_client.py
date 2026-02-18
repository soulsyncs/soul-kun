# lib/capabilities/generation/google_docs_client.py
"""
Phase G1: 文書生成能力 - Google Docs APIクライアント

このモジュールは、Google Docs APIとのやり取りを担当します。

設計書: docs/20_next_generation_capabilities.md セクション6
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from typing import Optional, Dict, Any, List
import logging
import os
import re

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .constants import (
    GOOGLE_DOCS_API_VERSION,
    GOOGLE_DOCS_SCOPES,
    GOOGLE_DRIVE_API_VERSION,
    GOOGLE_DRIVE_SCOPES,
)
from .exceptions import (
    GoogleAuthError,
    GoogleDocsCreateError,
    GoogleDocsUpdateError,
    GoogleDriveUploadError,
)
from .models import SectionContent, SectionType


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# Google Docs APIクライアント
# =============================================================================


class GoogleDocsClient:
    """
    Google Docs APIクライアント

    Google Docsの作成・更新・共有を行う。
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
        self._docs_service = None
        self._drive_service = None
        self._credentials = None

    def _get_credentials(self):
        """認証情報を取得"""
        if self._credentials:
            return self._credentials

        try:
            scopes = list(GOOGLE_DOCS_SCOPES | GOOGLE_DRIVE_SCOPES)

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
                # Cloud Run/Functions: ADC（Application Default Credentials）
                from google.auth import default

                self._credentials = default(scopes=scopes)[0]

            return self._credentials

        except Exception as e:
            logger.error("Google auth failed: %s", type(e).__name__)
            raise GoogleAuthError(original_error=e)

    def _get_docs_service(self):
        """Docs APIサービスを取得"""
        if self._docs_service:
            return self._docs_service

        credentials = self._get_credentials()
        self._docs_service = build(
            "docs",
            GOOGLE_DOCS_API_VERSION,
            credentials=credentials,
        )
        return self._docs_service

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

    async def create_document(
        self,
        title: str,
        folder_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        新規文書を作成

        Args:
            title: 文書タイトル
            folder_id: 配置先フォルダID

        Returns:
            {"document_id": "...", "document_url": "..."}
        """
        try:
            docs_service = self._get_docs_service()

            # Docs APIで文書を作成
            document = docs_service.documents().create(
                body={"title": title}
            ).execute()

            document_id = document.get("documentId")
            document_url = f"https://docs.google.com/document/d/{document_id}/edit"

            logger.info(f"Created Google Doc: {document_id}")

            # フォルダに移動（指定がある場合）
            if folder_id:
                await self._move_to_folder(document_id, folder_id)

            return {
                "document_id": document_id,
                "document_url": document_url,
            }

        except HttpError as e:
            logger.error("Google Docs create failed: %s: %s", type(e).__name__, str(e)[:500])
            raise GoogleDocsCreateError(
                document_title=title,
                original_error=e,
            )
        except Exception as e:
            logger.error("Unexpected error creating document: %s: %s", type(e).__name__, str(e)[:500])
            raise GoogleDocsCreateError(
                document_title=title,
                original_error=e,
            )

    async def update_document(
        self,
        document_id: str,
        sections: List[SectionContent],
    ) -> bool:
        """
        文書を更新（セクションを追加）

        Args:
            document_id: 文書ID
            sections: 追加するセクションのリスト

        Returns:
            成功したかどうか
        """
        try:
            docs_service = self._get_docs_service()

            # リクエストを構築
            requests = []
            current_index = 1  # ドキュメントの開始位置

            for section in sections:
                # セクションタイトル
                if section.section_type in [
                    SectionType.HEADING1,
                    SectionType.HEADING2,
                    SectionType.HEADING3,
                    SectionType.TITLE,
                    SectionType.SUBTITLE,
                ]:
                    # 見出しを挿入
                    heading_style = self._get_heading_style(section.section_type)
                    title_text = f"{section.title}\n"

                    requests.append({
                        "insertText": {
                            "location": {"index": current_index},
                            "text": title_text,
                        }
                    })

                    # スタイルを適用
                    requests.append({
                        "updateParagraphStyle": {
                            "range": {
                                "startIndex": current_index,
                                "endIndex": current_index + len(title_text),
                            },
                            "paragraphStyle": {
                                "namedStyleType": heading_style,
                            },
                            "fields": "namedStyleType",
                        }
                    })

                    current_index += len(title_text)

                # セクションコンテンツ
                if section.content:
                    content_text = f"{section.content}\n\n"

                    requests.append({
                        "insertText": {
                            "location": {"index": current_index},
                            "text": content_text,
                        }
                    })

                    current_index += len(content_text)

            # バッチ更新を実行
            if requests:
                docs_service.documents().batchUpdate(
                    documentId=document_id,
                    body={"requests": requests},
                ).execute()

            logger.info(f"Updated Google Doc: {document_id}, sections={len(sections)}")
            return True

        except HttpError as e:
            logger.error("Google Docs update failed: %s", type(e).__name__)
            raise GoogleDocsUpdateError(
                document_id=document_id,
                original_error=e,
            )
        except Exception as e:
            logger.error("Unexpected error updating document: %s", type(e).__name__)
            raise GoogleDocsUpdateError(
                document_id=document_id,
                original_error=e,
            )

    async def write_markdown_content(
        self,
        document_id: str,
        markdown_content: str,
    ) -> bool:
        """
        Markdown形式のコンテンツを文書に書き込む

        Args:
            document_id: 文書ID
            markdown_content: Markdownコンテンツ

        Returns:
            成功したかどうか
        """
        try:
            docs_service = self._get_docs_service()

            # Markdownをパース
            requests = self._markdown_to_requests(markdown_content)

            # バッチ更新を実行
            if requests:
                docs_service.documents().batchUpdate(
                    documentId=document_id,
                    body={"requests": requests},
                ).execute()

            logger.info(f"Wrote markdown to Google Doc: {document_id}")
            return True

        except HttpError as e:
            logger.error("Google Docs write failed: %s", type(e).__name__)
            raise GoogleDocsUpdateError(
                document_id=document_id,
                original_error=e,
            )

    async def share_document(
        self,
        document_id: str,
        email_addresses: List[str],
        role: str = "reader",
    ) -> bool:
        """
        文書を共有

        Args:
            document_id: 文書ID
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
                    fileId=document_id,
                    body=permission,
                    sendNotificationEmail=False,
                ).execute()

            logger.info(f"Shared document {document_id} with {len(email_addresses)} users")
            return True

        except HttpError as e:
            logger.error("Google Drive share failed: %s", type(e).__name__)
            raise GoogleDriveUploadError(
                file_name=document_id,
                original_error=e,
            )

    async def _move_to_folder(
        self,
        document_id: str,
        folder_id: str,
    ) -> bool:
        """
        文書をフォルダに移動

        Args:
            document_id: 文書ID
            folder_id: フォルダID

        Returns:
            成功したかどうか
        """
        try:
            drive_service = self._get_drive_service()

            # 現在の親を取得
            file = drive_service.files().get(
                fileId=document_id,
                fields="parents",
            ).execute()
            previous_parents = ",".join(file.get("parents", []))

            # フォルダに移動
            drive_service.files().update(
                fileId=document_id,
                addParents=folder_id,
                removeParents=previous_parents,
                fields="id, parents",
            ).execute()

            logger.info(f"Moved document {document_id} to folder {folder_id}")
            return True

        except HttpError as e:
            logger.warning("Failed to move document to folder: %s", type(e).__name__)
            return False

    def _get_heading_style(self, section_type: SectionType) -> str:
        """セクションタイプに応じたGoogle Docsスタイル名を取得"""
        style_map = {
            SectionType.TITLE: "TITLE",
            SectionType.SUBTITLE: "SUBTITLE",
            SectionType.HEADING1: "HEADING_1",
            SectionType.HEADING2: "HEADING_2",
            SectionType.HEADING3: "HEADING_3",
        }
        return style_map.get(section_type, "NORMAL_TEXT")

    def _markdown_to_requests(self, markdown: str) -> List[Dict[str, Any]]:
        """
        MarkdownをGoogle Docs APIリクエストに変換

        Args:
            markdown: Markdownテキスト

        Returns:
            APIリクエストのリスト
        """
        requests = []
        current_index = 1
        lines = markdown.split("\n")

        for line in lines:
            if not line.strip():
                # 空行
                text = "\n"
                requests.append({
                    "insertText": {
                        "location": {"index": current_index},
                        "text": text,
                    }
                })
                current_index += len(text)
                continue

            # 見出しの検出
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2) + "\n"

                requests.append({
                    "insertText": {
                        "location": {"index": current_index},
                        "text": text,
                    }
                })

                # 見出しスタイル
                style_map = {
                    1: "HEADING_1",
                    2: "HEADING_2",
                    3: "HEADING_3",
                    4: "HEADING_4",
                    5: "HEADING_5",
                    6: "HEADING_6",
                }
                requests.append({
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": current_index,
                            "endIndex": current_index + len(text),
                        },
                        "paragraphStyle": {
                            "namedStyleType": style_map.get(level, "NORMAL_TEXT"),
                        },
                        "fields": "namedStyleType",
                    }
                })

                current_index += len(text)
                continue

            # 箇条書きの検出
            bullet_match = re.match(r'^[\-\*]\s+(.+)$', line)
            if bullet_match:
                text = bullet_match.group(1) + "\n"

                requests.append({
                    "insertText": {
                        "location": {"index": current_index},
                        "text": text,
                    }
                })

                requests.append({
                    "createParagraphBullets": {
                        "range": {
                            "startIndex": current_index,
                            "endIndex": current_index + len(text),
                        },
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                    }
                })

                current_index += len(text)
                continue

            # 番号付きリストの検出
            numbered_match = re.match(r'^\d+\.\s+(.+)$', line)
            if numbered_match:
                text = numbered_match.group(1) + "\n"

                requests.append({
                    "insertText": {
                        "location": {"index": current_index},
                        "text": text,
                    }
                })

                requests.append({
                    "createParagraphBullets": {
                        "range": {
                            "startIndex": current_index,
                            "endIndex": current_index + len(text),
                        },
                        "bulletPreset": "NUMBERED_DECIMAL_ALPHA_ROMAN",
                    }
                })

                current_index += len(text)
                continue

            # 通常のテキスト
            text = line + "\n"
            requests.append({
                "insertText": {
                    "location": {"index": current_index},
                    "text": text,
                }
            })
            current_index += len(text)

        return requests

    async def get_document_content(self, document_id: str) -> str:
        """
        文書の内容を取得

        Args:
            document_id: 文書ID

        Returns:
            文書のプレーンテキスト
        """
        try:
            docs_service = self._get_docs_service()

            document = docs_service.documents().get(
                documentId=document_id
            ).execute()

            # コンテンツを抽出
            content = []
            body = document.get("body", {}).get("content", [])

            for element in body:
                if "paragraph" in element:
                    paragraph = element["paragraph"]
                    for elem in paragraph.get("elements", []):
                        if "textRun" in elem:
                            content.append(elem["textRun"].get("content", ""))

            return "".join(content)

        except HttpError as e:
            logger.error("Failed to get document content: %s", type(e).__name__)
            raise GoogleDocsUpdateError(
                document_id=document_id,
                original_error=e,
            )


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_google_docs_client(
    credentials_path: Optional[str] = None,
    credentials_json: Optional[Dict[str, Any]] = None,
) -> GoogleDocsClient:
    """
    GoogleDocsClientを作成

    Args:
        credentials_path: サービスアカウントJSONファイルのパス
        credentials_json: サービスアカウントJSONの内容

    Returns:
        GoogleDocsClient
    """
    return GoogleDocsClient(
        credentials_path=credentials_path,
        credentials_json=credentials_json,
    )
