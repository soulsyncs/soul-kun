# tests/test_google_slides_client.py
"""
Phase G4: Google Slides クライアントのテスト

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from uuid import uuid4

# テスト対象のインポート
from lib.capabilities.generation import (
    GoogleSlidesClient,
    GoogleSlidesError,
    GoogleSlidesCreateError,
    GoogleSlidesReadError,
    GoogleSlidesUpdateError,
    create_google_slides_client,
    LAYOUT_BLANK,
    LAYOUT_TITLE,
    LAYOUT_TITLE_AND_BODY,
    LAYOUT_SECTION_HEADER,
    LAYOUT_TITLE_ONLY,
    LAYOUT_ONE_COLUMN_TEXT,
    LAYOUT_TITLE_AND_TWO_COLUMNS,
    LAYOUT_BIG_NUMBER,
)
from lib.capabilities.generation.google_slides_client import (
    GOOGLE_SLIDES_API_VERSION,
    GOOGLE_SLIDES_SCOPES,
    LAYOUT_TITLE_ONLY,
    LAYOUT_BIG_NUMBER,
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
def slides_client(mock_credentials):
    """テスト用クライアント"""
    return GoogleSlidesClient(credentials_json=mock_credentials)


@pytest.fixture
def presentation_id():
    """テスト用プレゼンテーションID"""
    return "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_api_version(self):
        """APIバージョン"""
        assert GOOGLE_SLIDES_API_VERSION == "v1"

    def test_scopes(self):
        """スコープ"""
        assert "https://www.googleapis.com/auth/presentations" in GOOGLE_SLIDES_SCOPES
        assert "https://www.googleapis.com/auth/drive.file" in GOOGLE_SLIDES_SCOPES

    def test_layout_constants(self):
        """レイアウト定数"""
        assert LAYOUT_TITLE == "TITLE"
        assert LAYOUT_TITLE_AND_BODY == "TITLE_AND_BODY"
        assert LAYOUT_BLANK == "BLANK"
        assert LAYOUT_SECTION_HEADER == "SECTION_HEADER"
        assert LAYOUT_TITLE_ONLY == "TITLE_ONLY"
        assert LAYOUT_BIG_NUMBER == "BIG_NUMBER"


# =============================================================================
# 例外テスト
# =============================================================================


class TestExceptions:
    """例外のテスト"""

    def test_google_slides_error(self):
        """GoogleSlidesError"""
        error = GoogleSlidesError(
            message="Test error",
            error_code="TEST_ERROR",
            presentation_id="test-id",
        )
        assert str(error) == "Test error"
        assert error.error_code == "TEST_ERROR"
        assert error.presentation_id == "test-id"

    def test_google_slides_create_error(self):
        """GoogleSlidesCreateError"""
        error = GoogleSlidesCreateError(title="Test Presentation")
        assert "Test Presentation" in str(error)
        assert error.error_code == "SLIDES_CREATE_FAILED"
        assert "作成に失敗" in error.to_user_message()

    def test_google_slides_read_error(self):
        """GoogleSlidesReadError"""
        error = GoogleSlidesReadError(presentation_id="test-id")
        assert "test-id" in str(error)
        assert error.error_code == "SLIDES_READ_FAILED"
        assert "読み込みに失敗" in error.to_user_message()

    def test_google_slides_update_error(self):
        """GoogleSlidesUpdateError"""
        error = GoogleSlidesUpdateError(presentation_id="test-id")
        assert "test-id" in str(error)
        assert error.error_code == "SLIDES_UPDATE_FAILED"
        assert "更新に失敗" in error.to_user_message()


# =============================================================================
# クライアント初期化テスト
# =============================================================================


class TestClientInitialization:
    """クライアント初期化のテスト"""

    def test_init_with_credentials_json(self, mock_credentials):
        """JSON認証情報での初期化"""
        client = GoogleSlidesClient(credentials_json=mock_credentials)
        assert client._credentials_json == mock_credentials
        assert client._slides_service is None

    def test_init_with_credentials_path(self):
        """ファイルパスでの初期化"""
        client = GoogleSlidesClient(credentials_path="/path/to/credentials.json")
        assert client._credentials_path == "/path/to/credentials.json"

    def test_create_google_slides_client_factory(self, mock_credentials):
        """ファクトリ関数"""
        client = create_google_slides_client(credentials_json=mock_credentials)
        assert isinstance(client, GoogleSlidesClient)


# =============================================================================
# 読み込みテスト
# =============================================================================


class TestReadOperations:
    """読み込み操作のテスト"""

    @pytest.mark.asyncio
    async def test_get_presentation_info(self, slides_client, presentation_id):
        """プレゼンテーション情報取得"""
        mock_response = {
            "title": "Test Presentation",
            "slides": [
                {"objectId": "slide1", "slideProperties": {"layoutObjectId": "layout1"}},
                {"objectId": "slide2", "slideProperties": {"layoutObjectId": "layout2"}},
            ],
            "pageSize": {"width": {"magnitude": 9144000}, "height": {"magnitude": 5143500}},
        }

        with patch.object(slides_client, "_get_slides_service") as mock_service:
            mock_slides = Mock()
            mock_service.return_value = mock_slides
            mock_slides.presentations.return_value.get.return_value.execute.return_value = mock_response

            result = await slides_client.get_presentation_info(presentation_id)

            assert result["title"] == "Test Presentation"
            assert result["slide_count"] == 2
            assert len(result["slides"]) == 2
            assert result["slides"][0]["slide_id"] == "slide1"

    @pytest.mark.asyncio
    async def test_get_presentation_content(self, slides_client, presentation_id):
        """プレゼンテーション内容取得"""
        mock_response = {
            "slides": [
                {
                    "objectId": "slide1",
                    "pageElements": [
                        {
                            "objectId": "title1",
                            "shape": {
                                "placeholder": {"type": "TITLE"},
                                "text": {
                                    "textElements": [
                                        {"textRun": {"content": "スライドタイトル"}}
                                    ]
                                },
                            },
                        },
                        {
                            "objectId": "body1",
                            "shape": {
                                "placeholder": {"type": "BODY"},
                                "text": {
                                    "textElements": [
                                        {"textRun": {"content": "本文内容"}}
                                    ]
                                },
                            },
                        },
                    ],
                    "slideProperties": {},
                },
            ],
        }

        with patch.object(slides_client, "_get_slides_service") as mock_service:
            mock_slides = Mock()
            mock_service.return_value = mock_slides
            mock_slides.presentations.return_value.get.return_value.execute.return_value = mock_response

            result = await slides_client.get_presentation_content(presentation_id)

            assert len(result) == 1
            assert result[0]["title"] == "スライドタイトル"
            assert result[0]["body"] == "本文内容"
            assert result[0]["slide_id"] == "slide1"


# =============================================================================
# 作成テスト
# =============================================================================


class TestCreateOperations:
    """作成操作のテスト"""

    @pytest.mark.asyncio
    async def test_create_presentation(self, slides_client):
        """プレゼンテーション作成"""
        mock_response = {
            "presentationId": "new-presentation-id",
        }

        with patch.object(slides_client, "_get_slides_service") as mock_service:
            mock_slides = Mock()
            mock_service.return_value = mock_slides
            mock_slides.presentations.return_value.create.return_value.execute.return_value = mock_response

            result = await slides_client.create_presentation("新規プレゼンテーション")

            assert result["presentation_id"] == "new-presentation-id"
            assert "presentation_url" in result
            assert "new-presentation-id" in result["presentation_url"]


# =============================================================================
# スライド追加テスト
# =============================================================================


class TestSlideOperations:
    """スライド操作のテスト"""

    @pytest.mark.asyncio
    async def test_add_slide(self, slides_client, presentation_id):
        """スライド追加"""
        mock_presentation = {
            "layouts": [
                {
                    "objectId": "layout1",
                    "layoutProperties": {"name": "TITLE_AND_BODY"},
                }
            ],
            "slides": [],
        }

        with patch.object(slides_client, "_get_slides_service") as mock_service:
            mock_slides = Mock()
            mock_service.return_value = mock_slides
            mock_slides.presentations.return_value.get.return_value.execute.return_value = mock_presentation
            mock_slides.presentations.return_value.batchUpdate.return_value.execute.return_value = {}

            with patch.object(slides_client, "_add_text_to_slide") as mock_add_text:
                result = await slides_client.add_slide(
                    presentation_id,
                    title="テストタイトル",
                    body="テスト本文",
                )

                assert result.startswith("slide_")
                mock_add_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_title_slide(self, slides_client, presentation_id):
        """タイトルスライド追加"""
        with patch.object(slides_client, "add_slide") as mock_add:
            mock_add.return_value = "slide_123"

            result = await slides_client.add_title_slide(
                presentation_id,
                title="プレゼンテーションタイトル",
                subtitle="サブタイトル",
            )

            assert result == "slide_123"
            mock_add.assert_called_once_with(
                presentation_id=presentation_id,
                title="プレゼンテーションタイトル",
                body="サブタイトル",
                layout=LAYOUT_TITLE,
                insertion_index=0,
            )

    @pytest.mark.asyncio
    async def test_add_section_slide(self, slides_client, presentation_id):
        """セクションスライド追加"""
        with patch.object(slides_client, "add_slide") as mock_add:
            mock_add.return_value = "slide_456"

            result = await slides_client.add_section_slide(
                presentation_id,
                section_title="第1章",
            )

            assert result == "slide_456"
            mock_add.assert_called_once_with(
                presentation_id=presentation_id,
                title="第1章",
                layout=LAYOUT_SECTION_HEADER,
            )

    @pytest.mark.asyncio
    async def test_delete_slide(self, slides_client, presentation_id):
        """スライド削除"""
        with patch.object(slides_client, "_get_slides_service") as mock_service:
            mock_slides = Mock()
            mock_service.return_value = mock_slides
            mock_slides.presentations.return_value.batchUpdate.return_value.execute.return_value = {}

            result = await slides_client.delete_slide(presentation_id, "slide_123")

            assert result is True

    @pytest.mark.asyncio
    async def test_reorder_slides(self, slides_client, presentation_id):
        """スライド並び替え"""
        with patch.object(slides_client, "_get_slides_service") as mock_service:
            mock_slides = Mock()
            mock_service.return_value = mock_slides
            mock_slides.presentations.return_value.batchUpdate.return_value.execute.return_value = {}

            result = await slides_client.reorder_slides(
                presentation_id,
                ["slide_3", "slide_2"],
                insertion_index=0,
            )

            assert result is True


# =============================================================================
# 共有テスト
# =============================================================================


class TestShareOperations:
    """共有操作のテスト"""

    @pytest.mark.asyncio
    async def test_share_presentation(self, slides_client, presentation_id):
        """プレゼンテーション共有"""
        with patch.object(slides_client, "_get_drive_service") as mock_service:
            mock_drive = Mock()
            mock_service.return_value = mock_drive
            mock_drive.permissions.return_value.create.return_value.execute.return_value = {}

            result = await slides_client.share_presentation(
                presentation_id,
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

    def test_to_markdown(self, slides_client):
        """Markdown変換"""
        slides = [
            {
                "index": 0,
                "title": "タイトル",
                "body": "本文内容",
                "speaker_notes": "ノート",
            },
            {
                "index": 1,
                "title": "第2スライド",
                "body": "",
                "speaker_notes": "",
            },
        ]

        result = slides_client.to_markdown(slides)

        assert "## スライド 1: タイトル" in result
        assert "本文内容" in result
        assert "📝 スピーカーノート: ノート" in result
        assert "## スライド 2: 第2スライド" in result
        assert "---" in result

    def test_to_markdown_empty(self, slides_client):
        """空スライドのMarkdown変換"""
        result = slides_client.to_markdown([])
        assert result == ""

    def test_to_markdown_no_title(self, slides_client):
        """タイトルなしスライドのMarkdown変換"""
        slides = [
            {
                "index": 0,
                "title": "",
                "body": "本文のみ",
                "speaker_notes": "",
            }
        ]

        result = slides_client.to_markdown(slides)

        assert "## スライド 1" in result
        assert "本文のみ" in result

    def test_extract_text_from_shape(self, slides_client):
        """シェイプからテキスト抽出"""
        shape = {
            "text": {
                "textElements": [
                    {"textRun": {"content": "Hello "}},
                    {"textRun": {"content": "World"}},
                ]
            }
        }

        result = slides_client._extract_text_from_shape(shape)

        assert result == "Hello World"

    def test_extract_text_from_shape_empty(self, slides_client):
        """空シェイプからテキスト抽出"""
        shape = {}
        result = slides_client._extract_text_from_shape(shape)
        assert result == ""

    def test_extract_element_content_title(self, slides_client):
        """タイトル要素の抽出"""
        element = {
            "objectId": "title1",
            "shape": {
                "placeholder": {"type": "TITLE"},
                "text": {
                    "textElements": [
                        {"textRun": {"content": "タイトル"}}
                    ]
                },
            },
        }

        result = slides_client._extract_element_content(element)

        assert result["type"] == "title"
        assert result["text"] == "タイトル"
        assert result["object_id"] == "title1"

    def test_extract_element_content_body(self, slides_client):
        """本文要素の抽出"""
        element = {
            "objectId": "body1",
            "shape": {
                "placeholder": {"type": "BODY"},
                "text": {
                    "textElements": [
                        {"textRun": {"content": "本文"}}
                    ]
                },
            },
        }

        result = slides_client._extract_element_content(element)

        assert result["type"] == "body"
        assert result["text"] == "本文"

    def test_extract_element_content_no_shape(self, slides_client):
        """シェイプなし要素"""
        element = {"objectId": "image1"}
        result = slides_client._extract_element_content(element)
        assert result is None


# =============================================================================
# パッケージインポートテスト
# =============================================================================


class TestPackageImports:
    """パッケージインポートのテスト"""

    def test_import_client(self):
        """クライアントのインポート"""
        from lib.capabilities.generation import (
            GoogleSlidesClient,
            create_google_slides_client,
        )
        assert GoogleSlidesClient is not None
        assert create_google_slides_client is not None

    def test_import_exceptions(self):
        """例外のインポート"""
        from lib.capabilities.generation import (
            GoogleSlidesError,
            GoogleSlidesCreateError,
            GoogleSlidesReadError,
            GoogleSlidesUpdateError,
        )
        assert GoogleSlidesError is not None
        assert GoogleSlidesCreateError is not None
        assert GoogleSlidesReadError is not None
        assert GoogleSlidesUpdateError is not None

    def test_import_layout_constants(self):
        """レイアウト定数のインポート"""
        from lib.capabilities.generation import (
            LAYOUT_BLANK,
            LAYOUT_TITLE,
            LAYOUT_TITLE_AND_BODY,
            LAYOUT_SECTION_HEADER,
            LAYOUT_TITLE_ONLY,
            LAYOUT_ONE_COLUMN_TEXT,
        )
        assert LAYOUT_BLANK == "BLANK"
        assert LAYOUT_TITLE == "TITLE"
        assert LAYOUT_TITLE_AND_BODY == "TITLE_AND_BODY"
        assert LAYOUT_SECTION_HEADER == "SECTION_HEADER"
        assert LAYOUT_TITLE_ONLY == "TITLE_ONLY"
        assert LAYOUT_ONE_COLUMN_TEXT == "ONE_COLUMN_TEXT"
