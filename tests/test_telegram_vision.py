# tests/test_telegram_vision.py
"""
Telegram画像認識AI（Vision AI）のテスト

テスト対象:
- download_telegram_file(): Telegram Bot APIからファイルをダウンロード
- is_image_media(): メディア情報が画像かどうかの判定
- BypassType.IMAGE_ANALYSIS: Brainのバイパス検出
"""

import pytest
from unittest.mock import patch, MagicMock


# =============================================================================
# download_telegram_file テスト
# =============================================================================


class TestDownloadTelegramFile:
    """Telegram Bot APIからのファイルダウンロード"""

    @patch("lib.channels.telegram_adapter.httpx.Client")
    def test_successful_download(self, mock_client_cls):
        from lib.channels.telegram_adapter import download_telegram_file

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        # getFile レスポンス
        get_file_resp = MagicMock()
        get_file_resp.json.return_value = {
            "ok": True,
            "result": {"file_path": "photos/file_123.jpg", "file_size": 1024},
        }
        get_file_resp.raise_for_status = MagicMock()

        # ダウンロードレスポンス
        dl_resp = MagicMock()
        dl_resp.content = b"\xff\xd8\xff\xe0fake_jpeg_data"
        dl_resp.raise_for_status = MagicMock()

        mock_client.get.side_effect = [get_file_resp, dl_resp]

        result = download_telegram_file("AgADtest123", bot_token="test_token")
        assert result == b"\xff\xd8\xff\xe0fake_jpeg_data"

    def test_missing_token_returns_none(self):
        from lib.channels.telegram_adapter import download_telegram_file

        result = download_telegram_file("file_id", bot_token="")
        assert result is None

    def test_missing_file_id_returns_none(self):
        from lib.channels.telegram_adapter import download_telegram_file

        result = download_telegram_file("", bot_token="test_token")
        assert result is None

    @patch("lib.channels.telegram_adapter.httpx.Client")
    def test_getfile_not_ok_returns_none(self, mock_client_cls):
        from lib.channels.telegram_adapter import download_telegram_file

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = MagicMock()
        resp.json.return_value = {"ok": False, "description": "Bad Request"}
        resp.raise_for_status = MagicMock()
        mock_client.get.return_value = resp

        result = download_telegram_file("file_id", bot_token="test_token")
        assert result is None

    @patch("lib.channels.telegram_adapter.httpx.Client")
    def test_file_too_large_returns_none(self, mock_client_cls):
        from lib.channels.telegram_adapter import download_telegram_file

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = MagicMock()
        resp.json.return_value = {
            "ok": True,
            "result": {
                "file_path": "photos/huge.jpg",
                "file_size": 30 * 1024 * 1024,  # 30MB > 20MB limit
            },
        }
        resp.raise_for_status = MagicMock()
        mock_client.get.return_value = resp

        result = download_telegram_file("file_id", bot_token="test_token")
        assert result is None

    @patch("lib.channels.telegram_adapter.httpx.Client")
    def test_empty_file_path_returns_none(self, mock_client_cls):
        from lib.channels.telegram_adapter import download_telegram_file

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = MagicMock()
        resp.json.return_value = {
            "ok": True,
            "result": {"file_path": "", "file_size": 0},
        }
        resp.raise_for_status = MagicMock()
        mock_client.get.return_value = resp

        result = download_telegram_file("file_id", bot_token="test_token")
        assert result is None

    @patch("lib.channels.telegram_adapter.httpx.Client")
    def test_http_error_returns_none(self, mock_client_cls):
        import httpx
        from lib.channels.telegram_adapter import download_telegram_file

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_response,
        )

        result = download_telegram_file("file_id", bot_token="test_token")
        assert result is None


# =============================================================================
# is_image_media テスト
# =============================================================================


class TestIsImageMedia:
    """メディア情報が画像かどうかの判定"""

    def test_photo_is_image(self):
        from lib.channels.telegram_adapter import is_image_media

        assert is_image_media({"media_type": "photo"}) is True

    def test_video_is_not_image(self):
        from lib.channels.telegram_adapter import is_image_media

        assert is_image_media({"media_type": "video"}) is False

    def test_voice_is_not_image(self):
        from lib.channels.telegram_adapter import is_image_media

        assert is_image_media({"media_type": "voice"}) is False

    def test_document_image_mime(self):
        from lib.channels.telegram_adapter import is_image_media

        assert is_image_media({"media_type": "document", "mime_type": "image/png"}) is True
        assert is_image_media({"media_type": "document", "mime_type": "image/jpeg"}) is True

    def test_document_pdf_not_image(self):
        from lib.channels.telegram_adapter import is_image_media

        assert is_image_media({"media_type": "document", "mime_type": "application/pdf"}) is False

    def test_empty_media_not_image(self):
        from lib.channels.telegram_adapter import is_image_media

        assert is_image_media({}) is False
        assert is_image_media(None) is False


# =============================================================================
# BypassType.IMAGE_ANALYSIS テスト
# =============================================================================


class TestBypassTypeImageAnalysis:
    """BrainのIMAGE_ANALYSISバイパス検出"""

    def test_image_analysis_enum_in_source(self):
        """integration.pyにIMAGE_ANALYSISが定義されていることを確認"""
        import pathlib
        source = pathlib.Path("lib/brain/integration.py").read_text()
        assert 'IMAGE_ANALYSIS = "image_analysis"' in source

    def test_bypass_detection_has_image_check(self):
        """_detect_bypassにhas_imageチェックがあることを確認"""
        import pathlib
        source = pathlib.Path("lib/brain/integration.py").read_text()
        assert 'context.get("has_image")' in source
        assert "BypassType.IMAGE_ANALYSIS" in source


# =============================================================================
# is_image_media 追加テスト（MIMEバリエーション）
# =============================================================================


class TestIsImageMediaMimeVariations:
    """is_image_mediaの各種MIMEタイプ対応"""

    def test_document_image_webp(self):
        from lib.channels.telegram_adapter import is_image_media

        assert is_image_media({"media_type": "document", "mime_type": "image/webp"}) is True

    def test_document_image_gif(self):
        from lib.channels.telegram_adapter import is_image_media

        assert is_image_media({"media_type": "document", "mime_type": "image/gif"}) is True

    def test_document_image_bmp(self):
        from lib.channels.telegram_adapter import is_image_media

        assert is_image_media({"media_type": "document", "mime_type": "image/bmp"}) is True

    def test_document_zip_not_image(self):
        from lib.channels.telegram_adapter import is_image_media

        assert is_image_media({"media_type": "document", "mime_type": "application/zip"}) is False
