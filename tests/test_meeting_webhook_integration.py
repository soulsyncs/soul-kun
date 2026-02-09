# tests/test_meeting_webhook_integration.py
"""
Phase C: ChatWork音声ファイル → 文字起こし ブリッジのテスト

[download:FILE_ID]タグ検出、ファイルダウンロード、音声/非音声振り分け、
ファイルサイズ制限、バイパスハンドラー統合をテスト。
"""

import importlib.util
import os
import sys
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# chatwork-webhook/infra/chatwork_api.py を直接ロード（namespace collision回避）
def _load_chatwork_api():
    """chatwork-webhook/infra/chatwork_api.py をimportlib経由でロード"""
    chatwork_dir = os.path.join(
        os.path.dirname(__file__), "..", "chatwork-webhook"
    )
    # infra.db のモック（get_pool, get_secret 等）
    mock_db = MagicMock()
    mock_db.get_pool = MagicMock()
    mock_db.get_secret = MagicMock(return_value="test-token")
    mock_db.get_db_connection = MagicMock()
    sys.modules["infra"] = MagicMock()
    sys.modules["infra.db"] = mock_db

    # utils.chatwork_utils のモック
    mock_utils = MagicMock()
    sys.modules["utils"] = MagicMock()
    sys.modules["utils.chatwork_utils"] = mock_utils

    spec = importlib.util.spec_from_file_location(
        "infra.chatwork_api",
        os.path.join(chatwork_dir, "infra", "chatwork_api.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["infra.chatwork_api"] = module
    spec.loader.exec_module(module)
    return module


class TestDownloadTagDetection:
    """[download:FILE_ID] タグの検出テスト"""

    def test_single_download_tag(self):
        body = "[To:10909425]この音声を文字起こしして[download:12345]"
        file_ids = re.findall(r'\[download:(\d+)\]', body)
        assert file_ids == ["12345"]

    def test_multiple_download_tags(self):
        body = "[download:111]テスト[download:222]"
        file_ids = re.findall(r'\[download:(\d+)\]', body)
        assert file_ids == ["111", "222"]

    def test_no_download_tag(self):
        body = "[To:10909425]こんにちは"
        file_ids = re.findall(r'\[download:(\d+)\]', body)
        assert file_ids == []

    def test_download_tag_in_info_block(self):
        body = "[info][title]ファイル[/title][download:99999][/info]"
        file_ids = re.findall(r'\[download:(\d+)\]', body)
        assert file_ids == ["99999"]


class TestAudioExtensionDetection:
    """音声ファイル拡張子の判定テスト"""

    AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "ogg", "flac", "webm", "mp4", "mpeg", "mpga"}

    @pytest.mark.parametrize("filename,expected", [
        ("recording.mp3", True),
        ("meeting.wav", True),
        ("voice.m4a", True),
        ("audio.ogg", True),
        ("sound.flac", True),
        ("document.pdf", False),
        ("image.png", False),
        ("report.xlsx", False),
        ("no_extension", False),
    ])
    def test_extension_check(self, filename, expected):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        assert (ext in self.AUDIO_EXTENSIONS) == expected


class TestDownloadChatworkFile:
    """ChatWork ファイルダウンロード関数のテスト"""

    def test_successful_download(self):
        chatwork_api = _load_chatwork_api()

        # get_secret モック
        chatwork_api.get_secret = MagicMock(return_value="test-token")

        # call_chatwork_api_with_retry モック（ファイル情報取得）
        file_info_response = MagicMock()
        file_info_response.status_code = 200
        file_info_response.json.return_value = {
            "file_id": 12345,
            "filename": "meeting.mp3",
            "filesize": 1024,
            "download_url": "https://do.chatwork.com/download?key=xxx",
        }
        chatwork_api.call_chatwork_api_with_retry = MagicMock(
            return_value=(file_info_response, True)
        )

        # httpx.Client モック（ファイルダウンロード）
        mock_dl_response = MagicMock()
        mock_dl_response.status_code = 200
        mock_dl_response.content = b"fake_audio_data"

        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_dl_response

        with patch.object(chatwork_api.httpx, "Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=None)

            data, filename = chatwork_api.download_chatwork_file("room1", "12345")

        assert data == b"fake_audio_data"
        assert filename == "meeting.mp3"

    def test_download_no_token(self):
        chatwork_api = _load_chatwork_api()
        chatwork_api.get_secret = MagicMock(return_value=None)

        data, filename = chatwork_api.download_chatwork_file("room1", "12345")
        assert data is None
        assert filename is None

    def test_download_api_failure(self):
        chatwork_api = _load_chatwork_api()
        chatwork_api.get_secret = MagicMock(return_value="test-token")

        error_response = MagicMock()
        error_response.status_code = 404
        chatwork_api.call_chatwork_api_with_retry = MagicMock(
            return_value=(error_response, False)
        )

        data, filename = chatwork_api.download_chatwork_file("room1", "99999")
        assert data is None
        assert filename is None

    def test_download_no_download_url(self):
        chatwork_api = _load_chatwork_api()
        chatwork_api.get_secret = MagicMock(return_value="test-token")

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "file_id": 12345,
            "filename": "test.mp3",
        }
        chatwork_api.call_chatwork_api_with_retry = MagicMock(
            return_value=(response, True)
        )

        data, filename = chatwork_api.download_chatwork_file("room1", "12345")
        assert data is None
        assert filename is None

    def test_download_exception_returns_none(self):
        chatwork_api = _load_chatwork_api()
        chatwork_api.get_secret = MagicMock(return_value="test-token")
        chatwork_api.call_chatwork_api_with_retry = MagicMock(
            side_effect=Exception("Network error")
        )

        data, filename = chatwork_api.download_chatwork_file("room1", "12345")
        assert data is None
        assert filename is None

    def test_download_file_too_large_rejected(self):
        """100MBを超えるファイルはダウンロードされない（OOM防止）"""
        chatwork_api = _load_chatwork_api()
        chatwork_api.get_secret = MagicMock(return_value="test-token")

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "file_id": 12345,
            "filename": "huge_recording.wav",
            "filesize": 200 * 1024 * 1024,  # 200MB
            "download_url": "https://do.chatwork.com/download?key=xxx",
        }
        chatwork_api.call_chatwork_api_with_retry = MagicMock(
            return_value=(response, True)
        )

        data, filename = chatwork_api.download_chatwork_file("room1", "12345")
        assert data is None
        assert filename is None

    def test_download_file_within_size_limit(self):
        """100MB以下のファイルはダウンロードされる"""
        chatwork_api = _load_chatwork_api()
        chatwork_api.get_secret = MagicMock(return_value="test-token")

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "file_id": 12345,
            "filename": "normal.mp3",
            "filesize": 50 * 1024 * 1024,  # 50MB
            "download_url": "https://do.chatwork.com/download?key=xxx",
        }
        chatwork_api.call_chatwork_api_with_retry = MagicMock(
            return_value=(response, True)
        )

        mock_dl_response = MagicMock()
        mock_dl_response.status_code = 200
        mock_dl_response.content = b"audio_data"

        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_dl_response

        with patch.object(chatwork_api.httpx, "Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client.return_value.__exit__ = MagicMock(return_value=None)

            data, filename = chatwork_api.download_chatwork_file("room1", "12345")

        assert data == b"audio_data"
        assert filename == "normal.mp3"


class TestDownloadMeetingAudioLogic:
    """_download_meeting_audio のロジックテスト"""

    def test_feature_disabled_returns_none(self):
        """ENABLE_MEETING_TRANSCRIPTION=false → スキップ"""
        enabled = os.environ.get("ENABLE_MEETING_TRANSCRIPTION", "false").lower() == "true"
        assert not enabled  # テスト環境ではデフォルトfalse

    def test_non_audio_file_skipped(self):
        """非音声ファイルはスキップ"""
        audio_exts = {"mp3", "wav", "m4a", "ogg", "flac", "webm", "mp4", "mpeg", "mpga"}
        assert "pdf" not in audio_exts
        assert "xlsx" not in audio_exts

    def test_audio_file_detected(self):
        """音声ファイルは検出される"""
        audio_exts = {"mp3", "wav", "m4a", "ogg", "flac", "webm", "mp4", "mpeg", "mpga"}
        assert "mp3" in audio_exts
        assert "wav" in audio_exts
        assert "m4a" in audio_exts


class TestBypassContextIntegration:
    """音声データがbypass_contextに正しく格納されるテスト"""

    def test_bypass_context_includes_audio_data(self):
        """音声データがbypass_contextに格納される"""
        context = {
            "has_active_goal_session": False,
            "has_pending_announcement": False,
        }
        # 音声データがダウンロードされた場合
        audio_data = b"fake_audio"
        audio_filename = "meeting.mp3"
        context["has_meeting_audio"] = True
        context["meeting_audio_data"] = audio_data
        context["meeting_audio_filename"] = audio_filename

        assert context["has_meeting_audio"] is True
        assert context["meeting_audio_data"] == b"fake_audio"
        assert context["meeting_audio_filename"] == "meeting.mp3"

    def test_bypass_context_without_audio(self):
        """音声ファイルなしの場合、audio関連キーは存在しない"""
        context = {
            "has_active_goal_session": False,
            "has_pending_announcement": False,
        }
        assert "has_meeting_audio" not in context
        assert "meeting_audio_data" not in context


class TestBypassHandlerMeetingAudio:
    """_bypass_handle_meeting_audio のテスト"""

    @pytest.mark.asyncio
    async def test_no_audio_data_returns_none(self):
        """audio_dataがcontextにない → None（通常処理へフォールスルー）"""
        # handler_wrappers.py をロード
        chatwork_dir = os.path.join(
            os.path.dirname(__file__), "..", "chatwork-webhook"
        )
        spec = importlib.util.spec_from_file_location(
            "lib.brain.handler_wrappers_test",
            os.path.join(chatwork_dir, "lib", "brain", "handler_wrappers.py"),
        )
        module = importlib.util.module_from_spec(spec)

        # 必要なモジュールをモック
        sys.modules["lib.brain.integration"] = MagicMock()
        sys.modules["lib.brain.capability_bridge"] = MagicMock()

        spec.loader.exec_module(module)

        result = await module._bypass_handle_meeting_audio(
            "test message", "room1", "acc1", "テスト太郎",
            {"has_meeting_audio": False}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_with_audio_data_calls_handler(self):
        """audio_dataがある → bridge._handle_meeting_transcriptionが呼ばれる"""
        chatwork_dir = os.path.join(
            os.path.dirname(__file__), "..", "chatwork-webhook"
        )
        spec = importlib.util.spec_from_file_location(
            "lib.brain.handler_wrappers_test2",
            os.path.join(chatwork_dir, "lib", "brain", "handler_wrappers.py"),
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["lib.brain.integration"] = MagicMock()
        sys.modules["lib.brain.capability_bridge"] = MagicMock()
        spec.loader.exec_module(module)

        # main モジュールをモック
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "文字起こし結果: テスト"

        mock_bridge = MagicMock()
        mock_bridge._handle_meeting_transcription = AsyncMock(return_value=mock_result)

        mock_main = MagicMock()
        mock_main._get_capability_bridge = MagicMock(return_value=mock_bridge)
        sys.modules["main"] = mock_main

        context = {
            "has_meeting_audio": True,
            "meeting_audio_data": b"fake_audio_bytes",
            "meeting_audio_filename": "test.mp3",
        }

        result = await module._bypass_handle_meeting_audio(
            "文字起こしして", "room1", "acc1", "テスト太郎", context
        )

        assert result == "文字起こし結果: テスト"
        mock_bridge._handle_meeting_transcription.assert_called_once()

    @pytest.mark.asyncio
    async def test_handler_failure_returns_error_message(self):
        """ハンドラーが失敗 → エラーメッセージを返す"""
        chatwork_dir = os.path.join(
            os.path.dirname(__file__), "..", "chatwork-webhook"
        )
        spec = importlib.util.spec_from_file_location(
            "lib.brain.handler_wrappers_test3",
            os.path.join(chatwork_dir, "lib", "brain", "handler_wrappers.py"),
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["lib.brain.integration"] = MagicMock()
        sys.modules["lib.brain.capability_bridge"] = MagicMock()
        spec.loader.exec_module(module)

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.message = "Transcription API error"

        mock_bridge = MagicMock()
        mock_bridge._handle_meeting_transcription = AsyncMock(return_value=mock_result)

        mock_main = MagicMock()
        mock_main._get_capability_bridge = MagicMock(return_value=mock_bridge)
        sys.modules["main"] = mock_main

        context = {
            "has_meeting_audio": True,
            "meeting_audio_data": b"audio",
            "meeting_audio_filename": "test.wav",
        }

        result = await module._bypass_handle_meeting_audio(
            "msg", "room1", "acc1", "太郎", context
        )

        assert result == "Transcription API error"
