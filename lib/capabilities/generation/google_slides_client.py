# lib/capabilities/generation/google_slides_client.py
"""
Phase G4: プレゼンテーション生成能力 - Google Slides APIクライアント

このモジュールは、Google Slides APIとのやり取りを担当します。
読み込み・作成・更新・共有をサポート。

設計書: docs/20_next_generation_capabilities.md
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from typing import Optional, Dict, Any, List
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

GOOGLE_SLIDES_API_VERSION = "v1"
GOOGLE_SLIDES_SCOPES = frozenset([
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive.file",
])

# スライドレイアウト
LAYOUT_TITLE = "TITLE"
LAYOUT_TITLE_AND_BODY = "TITLE_AND_BODY"
LAYOUT_TITLE_AND_TWO_COLUMNS = "TITLE_AND_TWO_COLUMNS"
LAYOUT_TITLE_ONLY = "TITLE_ONLY"
LAYOUT_BLANK = "BLANK"
LAYOUT_SECTION_HEADER = "SECTION_HEADER"
LAYOUT_ONE_COLUMN_TEXT = "ONE_COLUMN_TEXT"
LAYOUT_BIG_NUMBER = "BIG_NUMBER"


# =============================================================================
# 例外
# =============================================================================


class GoogleSlidesError(GoogleAPIError):
    """Google Slides API エラーの基底クラス"""

    def __init__(
        self,
        message: str,
        error_code: str = "SLIDES_ERROR",
        presentation_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            api_name="Google Slides",
            details={"presentation_id": presentation_id, **(details or {})},
            original_error=original_error,
        )
        self.presentation_id = presentation_id


class GoogleSlidesCreateError(GoogleSlidesError):
    """プレゼンテーション作成エラー"""

    def __init__(
        self,
        title: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Failed to create presentation: {title}",
            error_code="SLIDES_CREATE_FAILED",
            details={"title": title},
            original_error=original_error,
        )
        self.title = title

    def to_user_message(self) -> str:
        return "プレゼンテーションの作成に失敗しました。"


class GoogleSlidesReadError(GoogleSlidesError):
    """プレゼンテーション読み込みエラー"""

    def __init__(
        self,
        presentation_id: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Failed to read presentation: {presentation_id}",
            error_code="SLIDES_READ_FAILED",
            presentation_id=presentation_id,
            original_error=original_error,
        )

    def to_user_message(self) -> str:
        return "プレゼンテーションの読み込みに失敗しました。"


class GoogleSlidesUpdateError(GoogleSlidesError):
    """プレゼンテーション更新エラー"""

    def __init__(
        self,
        presentation_id: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Failed to update presentation: {presentation_id}",
            error_code="SLIDES_UPDATE_FAILED",
            presentation_id=presentation_id,
            original_error=original_error,
        )

    def to_user_message(self) -> str:
        return "プレゼンテーションの更新に失敗しました。"


# =============================================================================
# Google Slides APIクライアント
# =============================================================================


class GoogleSlidesClient:
    """
    Google Slides APIクライアント

    プレゼンテーションの読み込み・作成・更新・共有を行う。

    使用例:
        client = GoogleSlidesClient()

        # 読み込み
        slides = await client.get_presentation_content(presentation_id)

        # 作成
        result = await client.create_presentation("週次報告会")

        # スライド追加
        await client.add_slide(presentation_id, "タイトル", "本文")
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
        self._slides_service = None
        self._drive_service = None
        self._credentials = None

    def _get_credentials(self):
        """認証情報を取得"""
        if self._credentials:
            return self._credentials

        try:
            scopes = list(GOOGLE_SLIDES_SCOPES | GOOGLE_DRIVE_SCOPES)

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

    def _get_slides_service(self):
        """Slides APIサービスを取得"""
        if self._slides_service:
            return self._slides_service

        credentials = self._get_credentials()
        self._slides_service = build(
            "slides",
            GOOGLE_SLIDES_API_VERSION,
            credentials=credentials,
        )
        return self._slides_service

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

    async def get_presentation_info(
        self,
        presentation_id: str,
    ) -> Dict[str, Any]:
        """
        プレゼンテーションのメタデータを取得

        Args:
            presentation_id: プレゼンテーションID

        Returns:
            タイトル、スライド数などのメタデータ
        """
        try:
            slides_service = self._get_slides_service()

            presentation = slides_service.presentations().get(
                presentationId=presentation_id
            ).execute()

            slides = []
            for i, slide in enumerate(presentation.get("slides", [])):
                slide_info = {
                    "slide_id": slide.get("objectId"),
                    "index": i,
                    "layout": slide.get("slideProperties", {}).get(
                        "layoutObjectId"
                    ),
                }
                slides.append(slide_info)

            return {
                "presentation_id": presentation_id,
                "title": presentation.get("title"),
                "url": f"https://docs.google.com/presentation/d/{presentation_id}/edit",
                "slide_count": len(slides),
                "slides": slides,
                "page_size": presentation.get("pageSize"),
            }

        except HttpError as e:
            logger.error(f"Failed to get presentation info: {str(e)}")
            raise GoogleSlidesReadError(
                presentation_id=presentation_id,
                original_error=e,
            )

    async def get_presentation_content(
        self,
        presentation_id: str,
    ) -> List[Dict[str, Any]]:
        """
        プレゼンテーションの全スライド内容を取得

        Args:
            presentation_id: プレゼンテーションID

        Returns:
            各スライドのタイトルと本文のリスト
        """
        try:
            slides_service = self._get_slides_service()

            presentation = slides_service.presentations().get(
                presentationId=presentation_id
            ).execute()

            result = []
            for i, slide in enumerate(presentation.get("slides", [])):
                slide_content = {
                    "index": i,
                    "slide_id": slide.get("objectId"),
                    "title": "",
                    "body": "",
                    "speaker_notes": "",
                    "elements": [],
                }

                # ページ要素を解析
                for element in slide.get("pageElements", []):
                    element_info = self._extract_element_content(element)
                    if element_info:
                        slide_content["elements"].append(element_info)

                        # タイトルと本文を特定
                        if element_info.get("type") == "title":
                            slide_content["title"] = element_info.get("text", "")
                        elif element_info.get("type") == "body":
                            if slide_content["body"]:
                                slide_content["body"] += "\n"
                            slide_content["body"] += element_info.get("text", "")

                # スピーカーノートを取得
                notes_page = slide.get("slideProperties", {}).get("notesPage")
                if notes_page:
                    for element in notes_page.get("pageElements", []):
                        if element.get("shape", {}).get("shapeType") == "TEXT_BOX":
                            text = self._extract_text_from_shape(element.get("shape", {}))
                            if text and text.strip():
                                slide_content["speaker_notes"] = text.strip()

                result.append(slide_content)

            logger.info(f"Read {len(result)} slides from presentation {presentation_id}")
            return result

        except HttpError as e:
            logger.error(f"Failed to read presentation content: {str(e)}")
            raise GoogleSlidesReadError(
                presentation_id=presentation_id,
                original_error=e,
            )

    def _extract_element_content(self, element: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """ページ要素からコンテンツを抽出"""
        if "shape" not in element:
            return None

        shape = element.get("shape", {})
        placeholder = shape.get("placeholder", {})
        placeholder_type = placeholder.get("type", "")

        text = self._extract_text_from_shape(shape)

        if not text:
            return None

        element_type = "other"
        if placeholder_type in ["TITLE", "CENTERED_TITLE"]:
            element_type = "title"
        elif placeholder_type in ["BODY", "SUBTITLE"]:
            element_type = "body"

        return {
            "type": element_type,
            "placeholder_type": placeholder_type,
            "text": text,
            "object_id": element.get("objectId"),
        }

    def _extract_text_from_shape(self, shape: Dict[str, Any]) -> str:
        """シェイプからテキストを抽出"""
        text_content = shape.get("text", {}).get("textElements", [])
        texts = []

        for elem in text_content:
            if "textRun" in elem:
                content = elem["textRun"].get("content", "")
                texts.append(content)

        return "".join(texts).strip()

    # =========================================================================
    # 作成
    # =========================================================================

    async def create_presentation(
        self,
        title: str,
        folder_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        新規プレゼンテーションを作成

        Args:
            title: プレゼンテーションのタイトル
            folder_id: 配置先フォルダID

        Returns:
            {"presentation_id": "...", "presentation_url": "..."}
        """
        try:
            slides_service = self._get_slides_service()

            body = {"title": title}

            presentation = slides_service.presentations().create(
                body=body
            ).execute()

            presentation_id = presentation.get("presentationId")
            presentation_url = f"https://docs.google.com/presentation/d/{presentation_id}/edit"

            logger.info(f"Created presentation: {presentation_id}")

            # フォルダに移動（指定がある場合）
            if folder_id:
                await self._move_to_folder(presentation_id, folder_id)

            return {
                "presentation_id": presentation_id,
                "presentation_url": presentation_url,
            }

        except HttpError as e:
            logger.error(f"Failed to create presentation: {str(e)}")
            raise GoogleSlidesCreateError(
                title=title,
                original_error=e,
            )

    # =========================================================================
    # スライド追加
    # =========================================================================

    async def add_slide(
        self,
        presentation_id: str,
        title: str = "",
        body: str = "",
        layout: str = LAYOUT_TITLE_AND_BODY,
        insertion_index: Optional[int] = None,
    ) -> str:
        """
        スライドを追加

        Args:
            presentation_id: プレゼンテーションID
            title: スライドタイトル
            body: スライド本文
            layout: レイアウト
            insertion_index: 挿入位置（省略時は末尾）

        Returns:
            新しいスライドのID
        """
        try:
            slides_service = self._get_slides_service()

            # まずプレゼンテーション情報を取得してレイアウトを探す
            presentation = slides_service.presentations().get(
                presentationId=presentation_id
            ).execute()

            # レイアウトIDを取得
            layout_id = None
            for layout_obj in presentation.get("layouts", []):
                layout_props = layout_obj.get("layoutProperties", {})
                if layout_props.get("name") == layout or layout_props.get("displayName") == layout:
                    layout_id = layout_obj.get("objectId")
                    break

            # スライド作成リクエスト
            requests = []

            # 新しいスライドID
            import uuid
            slide_id = f"slide_{uuid.uuid4().hex[:8]}"

            create_slide_request: Dict[str, Any] = {
                "createSlide": {
                    "objectId": slide_id,
                    "slideLayoutReference": {},
                }
            }

            if layout_id:
                create_slide_request["createSlide"]["slideLayoutReference"]["layoutId"] = layout_id
            else:
                create_slide_request["createSlide"]["slideLayoutReference"]["predefinedLayout"] = layout

            if insertion_index is not None:
                create_slide_request["createSlide"]["insertionIndex"] = insertion_index

            requests.append(create_slide_request)

            # バッチ更新
            slides_service.presentations().batchUpdate(
                presentationId=presentation_id,
                body={"requests": requests},
            ).execute()

            # テキストを追加（別リクエスト）
            if title or body:
                await self._add_text_to_slide(
                    presentation_id, slide_id, title, body
                )

            logger.info(f"Added slide to presentation {presentation_id}")
            return slide_id

        except HttpError as e:
            logger.error(f"Failed to add slide: {str(e)}")
            raise GoogleSlidesUpdateError(
                presentation_id=presentation_id,
                original_error=e,
            )

    async def _add_text_to_slide(
        self,
        presentation_id: str,
        slide_id: str,
        title: str,
        body: str,
    ) -> None:
        """スライドにテキストを追加"""
        try:
            slides_service = self._get_slides_service()

            # スライドの要素を取得
            presentation = slides_service.presentations().get(
                presentationId=presentation_id
            ).execute()

            # 該当スライドを探す
            target_slide = None
            for slide in presentation.get("slides", []):
                if slide.get("objectId") == slide_id:
                    target_slide = slide
                    break

            if not target_slide:
                return

            requests = []

            # プレースホルダーにテキストを挿入
            for element in target_slide.get("pageElements", []):
                shape = element.get("shape", {})
                placeholder = shape.get("placeholder", {})
                placeholder_type = placeholder.get("type", "")
                object_id = element.get("objectId")

                if placeholder_type in ["TITLE", "CENTERED_TITLE"] and title:
                    requests.append({
                        "insertText": {
                            "objectId": object_id,
                            "text": title,
                        }
                    })
                elif placeholder_type in ["BODY", "SUBTITLE"] and body:
                    requests.append({
                        "insertText": {
                            "objectId": object_id,
                            "text": body,
                        }
                    })

            if requests:
                slides_service.presentations().batchUpdate(
                    presentationId=presentation_id,
                    body={"requests": requests},
                ).execute()

        except HttpError as e:
            logger.warning(f"Failed to add text to slide: {str(e)}")

    async def add_title_slide(
        self,
        presentation_id: str,
        title: str,
        subtitle: str = "",
    ) -> str:
        """タイトルスライドを追加"""
        return await self.add_slide(
            presentation_id=presentation_id,
            title=title,
            body=subtitle,
            layout=LAYOUT_TITLE,
            insertion_index=0,
        )

    async def add_section_slide(
        self,
        presentation_id: str,
        section_title: str,
    ) -> str:
        """セクション区切りスライドを追加"""
        return await self.add_slide(
            presentation_id=presentation_id,
            title=section_title,
            layout=LAYOUT_SECTION_HEADER,
        )

    # =========================================================================
    # スライド操作
    # =========================================================================

    async def delete_slide(
        self,
        presentation_id: str,
        slide_id: str,
    ) -> bool:
        """
        スライドを削除

        Args:
            presentation_id: プレゼンテーションID
            slide_id: スライドID

        Returns:
            成功したかどうか
        """
        try:
            slides_service = self._get_slides_service()

            requests = [{
                "deleteObject": {
                    "objectId": slide_id,
                }
            }]

            slides_service.presentations().batchUpdate(
                presentationId=presentation_id,
                body={"requests": requests},
            ).execute()

            logger.info(f"Deleted slide {slide_id} from {presentation_id}")
            return True

        except HttpError as e:
            logger.error(f"Failed to delete slide: {str(e)}")
            raise GoogleSlidesUpdateError(
                presentation_id=presentation_id,
                original_error=e,
            )

    async def reorder_slides(
        self,
        presentation_id: str,
        slide_ids: List[str],
        insertion_index: int,
    ) -> bool:
        """
        スライドの順序を変更

        Args:
            presentation_id: プレゼンテーションID
            slide_ids: 移動するスライドIDのリスト
            insertion_index: 移動先インデックス

        Returns:
            成功したかどうか
        """
        try:
            slides_service = self._get_slides_service()

            requests = [{
                "updateSlidesPosition": {
                    "slideObjectIds": slide_ids,
                    "insertionIndex": insertion_index,
                }
            }]

            slides_service.presentations().batchUpdate(
                presentationId=presentation_id,
                body={"requests": requests},
            ).execute()

            logger.info(f"Reordered slides in {presentation_id}")
            return True

        except HttpError as e:
            logger.error(f"Failed to reorder slides: {str(e)}")
            raise GoogleSlidesUpdateError(
                presentation_id=presentation_id,
                original_error=e,
            )

    # =========================================================================
    # 共有
    # =========================================================================

    async def share_presentation(
        self,
        presentation_id: str,
        email_addresses: List[str],
        role: str = "reader",
    ) -> bool:
        """
        プレゼンテーションを共有

        Args:
            presentation_id: プレゼンテーションID
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
                    fileId=presentation_id,
                    body=permission,
                    sendNotificationEmail=False,
                ).execute()

            logger.info(
                f"Shared presentation {presentation_id} with {len(email_addresses)} users"
            )
            return True

        except HttpError as e:
            logger.error(f"Failed to share presentation: {str(e)}")
            raise GoogleSlidesUpdateError(
                presentation_id=presentation_id,
                original_error=e,
            )

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    async def _move_to_folder(
        self,
        presentation_id: str,
        folder_id: str,
    ) -> bool:
        """フォルダに移動"""
        try:
            drive_service = self._get_drive_service()

            file = drive_service.files().get(
                fileId=presentation_id,
                fields="parents",
            ).execute()
            previous_parents = ",".join(file.get("parents", []))

            drive_service.files().update(
                fileId=presentation_id,
                addParents=folder_id,
                removeParents=previous_parents,
                fields="id, parents",
            ).execute()

            logger.info(f"Moved presentation {presentation_id} to folder {folder_id}")
            return True

        except HttpError as e:
            logger.warning(f"Failed to move presentation to folder: {str(e)}")
            return False

    def to_markdown(self, slides: List[Dict[str, Any]]) -> str:
        """
        スライド内容をMarkdownに変換

        Args:
            slides: get_presentation_contentの結果

        Returns:
            Markdown文字列
        """
        lines = []

        for slide in slides:
            # スライド番号とタイトル
            slide_num = slide.get("index", 0) + 1
            title = slide.get("title", "")

            if title:
                lines.append(f"## スライド {slide_num}: {title}")
            else:
                lines.append(f"## スライド {slide_num}")
            lines.append("")

            # 本文
            body = slide.get("body", "")
            if body:
                lines.append(body)
                lines.append("")

            # スピーカーノート
            notes = slide.get("speaker_notes", "")
            if notes:
                lines.append(f"> 📝 スピーカーノート: {notes}")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_google_slides_client(
    credentials_path: Optional[str] = None,
    credentials_json: Optional[Dict[str, Any]] = None,
) -> GoogleSlidesClient:
    """
    GoogleSlidesClientを作成

    Args:
        credentials_path: サービスアカウントJSONファイルのパス
        credentials_json: サービスアカウントJSONの内容

    Returns:
        GoogleSlidesClient
    """
    return GoogleSlidesClient(
        credentials_path=credentials_path,
        credentials_json=credentials_json,
    )
