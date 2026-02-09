# tests/test_zoom_api_client.py
"""
Zoom APIクライアントのユニットテスト

Author: Claude Opus 4.6
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from lib.meetings.zoom_api_client import (
    ZoomAPIClient,
    ZoomToken,
    TOKEN_TTL_SECONDS,
    create_zoom_client_from_secrets,
)


@pytest.fixture
def zoom_client():
    return ZoomAPIClient(
        account_id="test_account",
        client_id="test_client_id",
        client_secret="test_client_secret",
    )


class TestZoomAPIClientInit:
    def test_valid_credentials(self):
        client = ZoomAPIClient("acc", "cid", "csec")
        assert client._account_id == "acc"

    def test_empty_account_id_raises(self):
        with pytest.raises(ValueError, match="Zoom credentials"):
            ZoomAPIClient("", "cid", "csec")

    def test_empty_client_id_raises(self):
        with pytest.raises(ValueError, match="Zoom credentials"):
            ZoomAPIClient("acc", "", "csec")

    def test_empty_client_secret_raises(self):
        with pytest.raises(ValueError, match="Zoom credentials"):
            ZoomAPIClient("acc", "cid", "")


class TestGetToken:
    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_token_request_success(self, mock_post, zoom_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok123"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        token = zoom_client._get_token()

        assert token == "tok123"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["params"]["grant_type"] == "account_credentials"
        assert call_kwargs[1]["params"]["account_id"] == "test_account"

    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_token_caching(self, mock_post, zoom_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "cached_tok"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        token1 = zoom_client._get_token()
        token2 = zoom_client._get_token()

        assert token1 == token2 == "cached_tok"
        assert mock_post.call_count == 1  # Only one HTTP call

    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_token_refresh_on_expiry(self, mock_post, zoom_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "new_tok"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        # Set expired token
        zoom_client._token = ZoomToken(
            access_token="old_tok", expires_at=time.time() - 10
        )

        token = zoom_client._get_token()
        assert token == "new_tok"
        assert mock_post.call_count == 1

    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_token_request_failure(self, mock_post, zoom_client):
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock()
        )
        mock_post.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            zoom_client._get_token()


class TestListRecordings:
    @patch("lib.meetings.zoom_api_client.httpx.get")
    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_list_recordings_success(self, mock_post, mock_get, zoom_client):
        # Token
        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "tok"}
        token_resp.raise_for_status = MagicMock()
        mock_post.return_value = token_resp

        # Recordings
        rec_resp = MagicMock()
        rec_resp.json.return_value = {
            "meetings": [
                {"id": "m1", "topic": "Meeting 1"},
                {"id": "m2", "topic": "Meeting 2"},
            ]
        }
        rec_resp.raise_for_status = MagicMock()
        mock_get.return_value = rec_resp

        result = zoom_client.list_recordings(from_date="2026-02-01")
        assert len(result) == 2
        assert result[0]["topic"] == "Meeting 1"

    @patch("lib.meetings.zoom_api_client.httpx.get")
    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_list_recordings_empty(self, mock_post, mock_get, zoom_client):
        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "tok"}
        token_resp.raise_for_status = MagicMock()
        mock_post.return_value = token_resp

        rec_resp = MagicMock()
        rec_resp.json.return_value = {"meetings": []}
        rec_resp.raise_for_status = MagicMock()
        mock_get.return_value = rec_resp

        result = zoom_client.list_recordings()
        assert result == []


class TestDownloadTranscript:
    @patch("lib.meetings.zoom_api_client.httpx.get")
    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_download_transcript_success(self, mock_post, mock_get, zoom_client):
        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "tok"}
        token_resp.raise_for_status = MagicMock()
        mock_post.return_value = token_resp

        vtt_resp = MagicMock()
        vtt_resp.text = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nHello"
        vtt_resp.raise_for_status = MagicMock()
        mock_get.return_value = vtt_resp

        result = zoom_client.download_transcript("https://zoom.us/rec/download/abc")
        assert "WEBVTT" in result
        assert "Hello" in result

    @patch("lib.meetings.zoom_api_client.httpx.get")
    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_download_url_with_existing_query_params(self, mock_post, mock_get, zoom_client):
        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "tok"}
        token_resp.raise_for_status = MagicMock()
        mock_post.return_value = token_resp

        vtt_resp = MagicMock()
        vtt_resp.text = "WEBVTT"
        vtt_resp.raise_for_status = MagicMock()
        mock_get.return_value = vtt_resp

        zoom_client.download_transcript("https://zoom.us/rec?foo=bar")
        call_args = mock_get.call_args
        url = call_args[0][0]
        assert "&access_token=tok" in url


class TestFindTranscriptUrl:
    def test_find_transcript_url_exists(self, zoom_client):
        recording_data = {
            "recording_files": [
                {"file_type": "MP4", "download_url": "https://zoom.us/mp4"},
                {"file_type": "TRANSCRIPT", "download_url": "https://zoom.us/vtt"},
            ]
        }
        url = zoom_client.find_transcript_url(recording_data)
        assert url == "https://zoom.us/vtt"

    def test_find_transcript_url_no_transcript(self, zoom_client):
        recording_data = {
            "recording_files": [
                {"file_type": "MP4", "download_url": "https://zoom.us/mp4"},
            ]
        }
        url = zoom_client.find_transcript_url(recording_data)
        assert url is None

    def test_find_transcript_url_empty_files(self, zoom_client):
        assert zoom_client.find_transcript_url({"recording_files": []}) is None

    def test_find_transcript_url_no_key(self, zoom_client):
        assert zoom_client.find_transcript_url({}) is None


class TestApiGetError:
    """_api_get の HTTP エラーパス"""

    @patch("lib.meetings.zoom_api_client.httpx.get")
    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_api_get_http_error_propagates(self, mock_post, mock_get, zoom_client):
        import httpx

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "tok"}
        token_resp.raise_for_status = MagicMock()
        mock_post.return_value = token_resp

        error_resp = MagicMock()
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )
        mock_get.return_value = error_resp

        with pytest.raises(httpx.HTTPStatusError):
            zoom_client.get_meeting_recordings("meeting_123")

    @patch("lib.meetings.zoom_api_client.httpx.get")
    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_list_recordings_http_error(self, mock_post, mock_get, zoom_client):
        import httpx

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "tok"}
        token_resp.raise_for_status = MagicMock()
        mock_post.return_value = token_resp

        error_resp = MagicMock()
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        mock_get.return_value = error_resp

        with pytest.raises(httpx.HTTPStatusError):
            zoom_client.list_recordings()


class TestDownloadTranscriptError:
    """download_transcript のエラーパス"""

    @patch("lib.meetings.zoom_api_client.httpx.get")
    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_download_transcript_http_error(self, mock_post, mock_get, zoom_client):
        import httpx

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "tok"}
        token_resp.raise_for_status = MagicMock()
        mock_post.return_value = token_resp

        error_resp = MagicMock()
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock()
        )
        mock_get.return_value = error_resp

        with pytest.raises(httpx.HTTPStatusError):
            zoom_client.download_transcript("https://zoom.us/rec/download/abc")


class TestListRecordingsPageSize:
    """page_size の上限キャップ"""

    @patch("lib.meetings.zoom_api_client.httpx.get")
    @patch("lib.meetings.zoom_api_client.httpx.post")
    def test_page_size_capped_at_300(self, mock_post, mock_get, zoom_client):
        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "tok"}
        token_resp.raise_for_status = MagicMock()
        mock_post.return_value = token_resp

        rec_resp = MagicMock()
        rec_resp.json.return_value = {"meetings": []}
        rec_resp.raise_for_status = MagicMock()
        mock_get.return_value = rec_resp

        zoom_client.list_recordings(page_size=999)
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["page_size"] == 300


class TestCreateFromSecrets:
    def test_factory_uses_secrets(self):
        mock_secret = MagicMock(
            side_effect=lambda name: {
                "zoom-account-id": "acc_123",
                "zoom-client-id": "cid_456",
                "zoom-client-secret": "csec_789",
            }[name]
        )

        with patch(
            "lib.secrets.get_secret_cached",
            mock_secret,
        ):
            client = create_zoom_client_from_secrets()

        assert client._account_id == "acc_123"
        assert client._client_id == "cid_456"
        assert client._client_secret == "csec_789"
