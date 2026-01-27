# tests/test_audio.py
"""
Phase M2: 音声入力能力 テスト

音声処理機能の包括的なテストを提供します。

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
import json

# テスト対象のインポート
from lib.capabilities.multimodal.constants import (
    InputType,
    ProcessingStatus,
    AudioType,
    TranscriptionStatus,
    SpeakerLabel,
    ContentConfidenceLevel,
    SUPPORTED_AUDIO_FORMATS,
    AUDIO_MIME_TYPES,
    MAX_AUDIO_SIZE_BYTES,
    MAX_AUDIO_DURATION_SECONDS,
    MAX_AUDIO_DURATION_MINUTES,
    WHISPER_API_TIMEOUT_SECONDS,
    DEFAULT_WHISPER_MODEL,
    DEFAULT_WHISPER_LANGUAGE,
    FEATURE_FLAG_AUDIO,
    MAX_SPEAKERS,
    AUDIO_TYPE_KEYWORDS,
)

from lib.capabilities.multimodal.exceptions import (
    AudioProcessingError,
    AudioDecodeError,
    AudioTooLongError,
    AudioTranscriptionError,
    NoSpeechDetectedError,
    SpeakerDetectionError,
    WhisperAPIError,
    WhisperAPITimeoutError,
    WhisperAPIRateLimitError,
)

from lib.capabilities.multimodal.models import (
    Speaker,
    TranscriptSegment,
    AudioMetadata,
    AudioAnalysisResult,
    MultimodalInput,
    MultimodalOutput,
    ProcessingMetadata,
    ExtractedEntity,
)

from lib.capabilities.multimodal.audio_processor import (
    AudioProcessor,
    WhisperAPIClient,
    create_audio_processor,
)


# =============================================================================
# テストフィクスチャ
# =============================================================================


@pytest.fixture
def mock_pool():
    """モックデータベースプール"""
    return Mock()


@pytest.fixture
def org_id():
    """テスト用組織ID"""
    return "test-org-123"


@pytest.fixture
def audio_processor(mock_pool, org_id):
    """AudioProcessorインスタンス"""
    return AudioProcessor(
        pool=mock_pool,
        organization_id=org_id,
        api_key="test-openrouter-key",
        openai_api_key="test-openai-key",
    )


@pytest.fixture
def sample_audio_data():
    """サンプル音声データ（MP3ヘッダー）"""
    # ID3タグ付きMP3ヘッダーのダミー
    return b'ID3' + b'\x00' * 100


@pytest.fixture
def sample_wav_data():
    """サンプルWAVデータ"""
    return b'RIFF' + b'\x00\x00\x00\x00' + b'WAVE' + b'\x00' * 100


@pytest.fixture
def sample_transcript_result():
    """サンプル文字起こし結果"""
    return {
        "text": "こんにちは。本日の会議を始めます。議題は新プロジェクトについてです。",
        "language": "ja",
        "segments": [
            {
                "id": 0,
                "text": "こんにちは。",
                "start": 0.0,
                "end": 1.5,
                "avg_logprob": -0.3,
            },
            {
                "id": 1,
                "text": "本日の会議を始めます。",
                "start": 1.5,
                "end": 4.0,
                "avg_logprob": -0.2,
            },
            {
                "id": 2,
                "text": "議題は新プロジェクトについてです。",
                "start": 4.5,
                "end": 7.0,
                "avg_logprob": -0.25,
            },
        ],
    }


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_supported_audio_formats(self):
        """サポートされる音声フォーマット"""
        assert "mp3" in SUPPORTED_AUDIO_FORMATS
        assert "wav" in SUPPORTED_AUDIO_FORMATS
        assert "m4a" in SUPPORTED_AUDIO_FORMATS
        assert "webm" in SUPPORTED_AUDIO_FORMATS
        assert "flac" in SUPPORTED_AUDIO_FORMATS
        assert "ogg" in SUPPORTED_AUDIO_FORMATS

    def test_audio_mime_types(self):
        """MIMEタイプマッピング"""
        assert AUDIO_MIME_TYPES["mp3"] == "audio/mpeg"
        assert AUDIO_MIME_TYPES["wav"] == "audio/wav"
        assert AUDIO_MIME_TYPES["m4a"] == "audio/mp4"

    def test_size_limits(self):
        """サイズ制限"""
        assert MAX_AUDIO_SIZE_BYTES == 25 * 1024 * 1024  # 25MB
        assert MAX_AUDIO_DURATION_SECONDS == 120 * 60  # 2時間
        assert MAX_AUDIO_DURATION_MINUTES == 120

    def test_whisper_settings(self):
        """Whisper API設定"""
        assert DEFAULT_WHISPER_MODEL == "whisper-1"
        assert DEFAULT_WHISPER_LANGUAGE == "ja"
        assert WHISPER_API_TIMEOUT_SECONDS == 300

    def test_audio_type_enum(self):
        """AudioType列挙型"""
        assert AudioType.MEETING.value == "meeting"
        assert AudioType.VOICE_MEMO.value == "voice_memo"
        assert AudioType.PHONE_CALL.value == "phone_call"
        assert AudioType.UNKNOWN.value == "unknown"

    def test_transcription_status_enum(self):
        """TranscriptionStatus列挙型"""
        assert TranscriptionStatus.PENDING.value == "pending"
        assert TranscriptionStatus.TRANSCRIBING.value == "transcribing"
        assert TranscriptionStatus.COMPLETED.value == "completed"
        assert TranscriptionStatus.FAILED.value == "failed"

    def test_speaker_label_from_index(self):
        """SpeakerLabel.from_index"""
        assert SpeakerLabel.from_index(1) == SpeakerLabel.SPEAKER_1
        assert SpeakerLabel.from_index(5) == SpeakerLabel.SPEAKER_5
        assert SpeakerLabel.from_index(0) == SpeakerLabel.UNKNOWN
        assert SpeakerLabel.from_index(9) == SpeakerLabel.UNKNOWN

    def test_audio_type_keywords(self):
        """音声タイプ検出キーワード"""
        assert "会議" in AUDIO_TYPE_KEYWORDS["meeting"]
        assert "メモ" in AUDIO_TYPE_KEYWORDS["voice_memo"]
        assert "電話" in AUDIO_TYPE_KEYWORDS["phone_call"]


# =============================================================================
# 例外テスト
# =============================================================================


class TestExceptions:
    """例外クラスのテスト"""

    def test_audio_processing_error(self):
        """AudioProcessingError"""
        error = AudioProcessingError("処理エラー")
        assert error.message == "処理エラー"
        assert error.error_code == "AUDIO_PROCESSING_ERROR"
        assert error.input_type == InputType.AUDIO

    def test_audio_decode_error(self):
        """AudioDecodeError"""
        error = AudioDecodeError()
        assert "読み込めなかった" in error.message
        assert error.error_code == "AUDIO_DECODE_ERROR"

    def test_audio_too_long_error(self):
        """AudioTooLongError"""
        error = AudioTooLongError(
            actual_duration_seconds=9000,  # 150分
            max_duration_seconds=7200,     # 120分
        )
        assert "150.0分" in error.message
        assert "120分" in error.message
        assert error.error_code == "AUDIO_TOO_LONG"
        assert error.actual_duration_seconds == 9000
        assert error.max_duration_seconds == 7200

    def test_audio_transcription_error(self):
        """AudioTranscriptionError"""
        error = AudioTranscriptionError(reason="APIエラー")
        assert "文字起こしに失敗" in error.message
        assert "APIエラー" in error.message

    def test_no_speech_detected_error(self):
        """NoSpeechDetectedError"""
        error = NoSpeechDetectedError()
        assert "音声が検出されなかった" in error.message
        assert error.error_code == "NO_SPEECH_DETECTED"

    def test_speaker_detection_error(self):
        """SpeakerDetectionError"""
        error = SpeakerDetectionError()
        assert "話者の識別に失敗" in error.message

    def test_whisper_api_error(self):
        """WhisperAPIError"""
        error = WhisperAPIError(
            message="API呼び出し失敗",
            model="whisper-1",
        )
        assert error.message == "API呼び出し失敗"
        assert error.model == "whisper-1"
        assert error.error_code == "WHISPER_API_ERROR"

    def test_whisper_api_timeout_error(self):
        """WhisperAPITimeoutError"""
        error = WhisperAPITimeoutError(timeout_seconds=300)
        assert "300秒" in error.message
        assert error.details["timeout_seconds"] == 300

    def test_whisper_api_rate_limit_error(self):
        """WhisperAPIRateLimitError"""
        error = WhisperAPIRateLimitError(retry_after=60)
        assert "レート制限" in error.message
        assert "60秒" in error.message

    def test_exception_to_user_message(self):
        """例外のユーザー向けメッセージ"""
        error = AudioProcessingError("エラー発生")
        user_msg = error.to_user_message()
        assert "ごめんウル" in user_msg

    def test_exception_to_dict(self):
        """例外の辞書変換"""
        error = AudioTooLongError(9000, 7200)
        d = error.to_dict()
        assert d["error"] == "AUDIO_TOO_LONG"
        assert "input_type" in d


# =============================================================================
# モデルテスト
# =============================================================================


class TestModels:
    """データモデルのテスト"""

    def test_speaker_model(self):
        """Speakerモデル"""
        speaker = Speaker(
            speaker_id="speaker_1",
            label=SpeakerLabel.SPEAKER_1,
            name="田中さん",
            speaking_time_seconds=120.5,
            segment_count=10,
            confidence=0.85,
        )

        assert speaker.speaker_id == "speaker_1"
        assert speaker.name == "田中さん"
        assert speaker.speaking_time_seconds == 120.5

        d = speaker.to_dict()
        assert d["speaker_id"] == "speaker_1"
        assert d["name"] == "田中さん"
        assert d["confidence"] == 0.85

    def test_transcript_segment_model(self):
        """TranscriptSegmentモデル"""
        speaker = Speaker(
            speaker_id="speaker_1",
            label=SpeakerLabel.SPEAKER_1,
        )

        segment = TranscriptSegment(
            segment_id=0,
            text="こんにちは",
            start_time=0.0,
            end_time=1.5,
            speaker=speaker,
            confidence=0.9,
            language="ja",
        )

        assert segment.duration == 1.5
        assert segment.format_timestamp() == "[00:00 - 00:01]"

        d = segment.to_dict()
        assert d["text"] == "こんにちは"
        assert d["duration"] == 1.5
        assert "speaker" in d

    def test_audio_metadata_model(self):
        """AudioMetadataモデル"""
        metadata = AudioMetadata(
            duration_seconds=3661,  # 1時間1分1秒
            format="mp3",
            file_size_bytes=5 * 1024 * 1024,
            sample_rate=44100,
            channels=2,
            bitrate=128,
        )

        assert metadata.duration_minutes == pytest.approx(61.0167, rel=0.01)
        assert "1時間1分" in metadata.duration_formatted
        assert metadata.channels == 2

        d = metadata.to_dict()
        assert d["format"] == "mp3"
        assert d["sample_rate"] == 44100

    def test_audio_analysis_result_model(self):
        """AudioAnalysisResultモデル"""
        result = AudioAnalysisResult(
            success=True,
            audio_type=AudioType.MEETING,
            full_transcript="会議の内容です",
            speaker_count=3,
            speakers_detected=True,
            detected_language="ja",
            summary="3人の会議",
            key_points=["ポイント1", "ポイント2"],
            action_items=["タスク1"],
            topics=["トピック1"],
            overall_confidence=0.85,
        )

        assert result.success
        assert result.audio_type == AudioType.MEETING
        assert result.speaker_count == 3

        d = result.to_dict()
        assert d["audio_type"] == "meeting"
        assert d["speaker_count"] == 3

    def test_audio_analysis_result_to_brain_context(self):
        """AudioAnalysisResult.to_brain_context"""
        result = AudioAnalysisResult(
            success=True,
            audio_type=AudioType.MEETING,
            audio_metadata=AudioMetadata(duration_seconds=600),
            full_transcript="会議の内容",
            summary="10分の会議",
            key_points=["ポイント1", "ポイント2"],
            action_items=["タスク1"],
            topics=["トピック1"],
            detected_language="ja",
            speaker_count=2,
        )

        context = result.to_brain_context()
        assert "音声解析結果" in context
        assert "日本語" in context
        assert "話者数: 2名" in context
        assert "ポイント1" in context

    def test_audio_analysis_result_transcript_with_speakers(self):
        """話者ラベル付き文字起こし"""
        speaker1 = Speaker(
            speaker_id="s1",
            label=SpeakerLabel.SPEAKER_1,
            name="田中",
        )
        speaker2 = Speaker(
            speaker_id="s2",
            label=SpeakerLabel.SPEAKER_2,
            name="佐藤",
        )

        segments = [
            TranscriptSegment(0, "おはようございます", 0.0, 2.0, speaker1),
            TranscriptSegment(1, "おはようございます", 2.0, 4.0, speaker2),
        ]

        result = AudioAnalysisResult(
            success=True,
            segments=segments,
            speakers=[speaker1, speaker2],
        )

        transcript = result.get_transcript_with_speakers()
        assert "田中:" in transcript
        assert "佐藤:" in transcript

    def test_multimodal_input_audio(self):
        """MultimodalInput音声サポート"""
        input_data = MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id="org-123",
            audio_data=b"audio data",
            detect_speakers=True,
            generate_summary=True,
            language="ja",
        )

        assert input_data.validate()
        assert input_data.input_type == InputType.AUDIO
        assert input_data.detect_speakers
        assert input_data.language == "ja"

    def test_multimodal_output_audio(self):
        """MultimodalOutput音声サポート"""
        audio_result = AudioAnalysisResult(success=True)
        output = MultimodalOutput(
            success=True,
            input_type=InputType.AUDIO,
            audio_result=audio_result,
            summary="テスト要約",
        )

        assert output.get_result() == audio_result
        assert output.input_type == InputType.AUDIO


# =============================================================================
# WhisperAPIClientテスト
# =============================================================================


class TestWhisperAPIClient:
    """WhisperAPIClientのテスト"""

    def test_init(self):
        """初期化テスト"""
        client = WhisperAPIClient(api_key="test-key")
        assert client._api_key == "test-key"
        assert client._model == DEFAULT_WHISPER_MODEL
        assert client._timeout_seconds == WHISPER_API_TIMEOUT_SECONDS

    def test_get_mime_type(self):
        """MIMEタイプ取得"""
        client = WhisperAPIClient()
        assert client._get_mime_type("audio.mp3") == "audio/mpeg"
        assert client._get_mime_type("audio.wav") == "audio/wav"
        assert client._get_mime_type("audio.m4a") == "audio/mp4"
        assert client._get_mime_type("audio.unknown") == "audio/mpeg"  # デフォルト

    @pytest.mark.asyncio
    async def test_transcribe_no_api_key(self):
        """API Key未設定エラー"""
        # 環境変数も未設定にしてからクライアント作成
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            client = WhisperAPIClient(api_key=None)
            client._api_key = None  # 明示的にNoneに設定
            with pytest.raises(WhisperAPIError) as exc_info:
                await client.transcribe(b"audio data")
            assert "API key not configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transcribe_success(self, sample_audio_data, sample_transcript_result):
        """正常な文字起こし"""
        client = WhisperAPIClient(api_key="test-key")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_transcript_result
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await client.transcribe(
                sample_audio_data,
                filename="test.mp3",
                language="ja",
            )

            assert result["text"] == sample_transcript_result["text"]
            assert result["language"] == "ja"

    @pytest.mark.asyncio
    async def test_transcribe_rate_limit(self, sample_audio_data):
        """レート制限エラー"""
        client = WhisperAPIClient(api_key="test-key")

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(WhisperAPIRateLimitError):
                await client.transcribe(sample_audio_data)

    @pytest.mark.asyncio
    async def test_transcribe_timeout(self, sample_audio_data):
        """タイムアウトエラー"""
        import httpx
        client = WhisperAPIClient(api_key="test-key")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(WhisperAPITimeoutError):
                await client.transcribe(sample_audio_data)


# =============================================================================
# AudioProcessorテスト
# =============================================================================


class TestAudioProcessor:
    """AudioProcessorのテスト"""

    def test_init(self, mock_pool, org_id):
        """初期化テスト"""
        processor = AudioProcessor(
            pool=mock_pool,
            organization_id=org_id,
            api_key="openrouter-key",
            openai_api_key="openai-key",
        )
        assert processor._organization_id == org_id
        assert processor._input_type == InputType.AUDIO

    def test_validate_success(self, audio_processor, sample_audio_data, org_id):
        """入力検証成功"""
        input_data = MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id=org_id,
            audio_data=sample_audio_data,
        )

        # 例外が発生しなければOK
        audio_processor.validate(input_data)

    def test_validate_wrong_input_type(self, audio_processor, org_id):
        """入力タイプエラー"""
        from lib.capabilities.multimodal.exceptions import ValidationError

        input_data = MultimodalInput(
            input_type=InputType.IMAGE,  # 間違ったタイプ
            organization_id=org_id,
            audio_data=b"data",
        )

        with pytest.raises(ValidationError):
            audio_processor.validate(input_data)

    def test_validate_no_data(self, audio_processor, org_id):
        """データなしエラー"""
        from lib.capabilities.multimodal.exceptions import ValidationError

        input_data = MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id=org_id,
            # audio_dataもfile_pathもなし
        )

        with pytest.raises(ValidationError):
            audio_processor.validate(input_data)

    def test_validate_file_too_large(self, audio_processor, org_id):
        """ファイルサイズ超過"""
        from lib.capabilities.multimodal.exceptions import FileTooLargeError

        large_data = b"x" * (MAX_AUDIO_SIZE_BYTES + 1)
        input_data = MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id=org_id,
            audio_data=large_data,
        )

        with pytest.raises(FileTooLargeError):
            audio_processor.validate(input_data)

    def test_validate_unsupported_format(self, audio_processor, org_id):
        """未サポートフォーマット"""
        from lib.capabilities.multimodal.exceptions import UnsupportedFormatError

        input_data = MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id=org_id,
            file_path="/path/to/file.xyz",  # 未サポート拡張子
        )

        with pytest.raises(UnsupportedFormatError):
            audio_processor.validate(input_data)

    def test_detect_audio_format_mp3(self, audio_processor):
        """MP3フォーマット検出"""
        mp3_data = b'ID3\x04\x00\x00\x00\x00\x00\x00' + b'\x00' * 100
        result = audio_processor._detect_audio_format(mp3_data)
        assert result == "mp3"

    def test_detect_audio_format_wav(self, audio_processor):
        """WAVフォーマット検出"""
        wav_data = b'RIFF\x00\x00\x00\x00WAVE' + b'\x00' * 100
        result = audio_processor._detect_audio_format(wav_data)
        assert result == "wav"

    def test_detect_audio_format_flac(self, audio_processor):
        """FLACフォーマット検出"""
        flac_data = b'fLaC\x00\x00\x00\x00' + b'\x00' * 100
        result = audio_processor._detect_audio_format(flac_data)
        assert result == "flac"

    def test_detect_audio_type_meeting(self, audio_processor):
        """会議タイプ検出"""
        transcript = "本日の会議を始めます。議題は..."
        result = audio_processor._detect_audio_type(transcript)
        assert result == AudioType.MEETING

    def test_detect_audio_type_voice_memo(self, audio_processor):
        """ボイスメモタイプ検出"""
        transcript = "メモを録音しておきます。"
        result = audio_processor._detect_audio_type(transcript)
        assert result == AudioType.VOICE_MEMO

    def test_detect_audio_type_unknown(self, audio_processor):
        """不明なタイプ"""
        transcript = "今日の天気は晴れです。"
        result = audio_processor._detect_audio_type(transcript)
        assert result == AudioType.UNKNOWN

    def test_parse_segments(self, audio_processor, sample_transcript_result):
        """セグメント解析"""
        segments = audio_processor._parse_segments(sample_transcript_result)

        assert len(segments) == 3
        assert segments[0].text == "こんにちは。"
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 1.5
        assert segments[1].text == "本日の会議を始めます。"

    def test_estimate_duration(self, audio_processor):
        """音声時間の推定"""
        # 1MBのMP3（128kbps想定）
        data_size = 1 * 1024 * 1024
        duration = audio_processor._estimate_duration(b"x" * data_size, "mp3")

        # 128kbps = 16KB/s なので、1MB ≈ 62.5秒
        assert 60 < duration < 70

    def test_get_filename_from_path(self, audio_processor, org_id):
        """ファイル名取得"""
        input_data = MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id=org_id,
            file_path="/path/to/meeting.mp3",
        )
        filename = audio_processor._get_filename(input_data)
        assert filename == "meeting.mp3"

    def test_get_filename_default(self, audio_processor, org_id):
        """デフォルトファイル名"""
        input_data = MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id=org_id,
            audio_data=b"data",
        )
        filename = audio_processor._get_filename(input_data)
        assert filename == "audio.mp3"

    def test_calculate_overall_confidence(self, audio_processor, sample_transcript_result):
        """確信度計算"""
        segments = audio_processor._parse_segments(sample_transcript_result)
        confidence = audio_processor._calculate_overall_confidence(
            sample_transcript_result, segments
        )

        assert 0.0 <= confidence <= 1.0

    @pytest.mark.asyncio
    async def test_process_success(
        self, audio_processor, sample_audio_data, sample_transcript_result, org_id
    ):
        """正常な処理フロー"""
        input_data = MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id=org_id,
            audio_data=sample_audio_data,
            detect_speakers=True,
            generate_summary=True,
        )

        # Whisper APIモック
        with patch.object(
            audio_processor._whisper_client,
            "transcribe",
            new_callable=AsyncMock,
            return_value=sample_transcript_result,
        ):
            # 要約生成モック
            with patch.object(
                audio_processor,
                "_generate_summary",
                new_callable=AsyncMock,
                return_value={
                    "summary": "会議の要約です",
                    "key_points": ["ポイント1"],
                    "action_items": ["タスク1"],
                    "topics": ["トピック1"],
                },
            ):
                # メタデータ抽出モック（mutagenなし想定）
                with patch.object(
                    audio_processor,
                    "_extract_audio_metadata",
                    new_callable=AsyncMock,
                    return_value=AudioMetadata(
                        duration_seconds=60,
                        format="mp3",
                        file_size_bytes=len(sample_audio_data),
                    ),
                ):
                    result = await audio_processor.process(input_data)

        assert result.success
        assert result.input_type == InputType.AUDIO
        assert result.audio_result is not None
        assert result.audio_result.full_transcript != ""
        assert result.summary == "会議の要約です"

    @pytest.mark.asyncio
    async def test_process_no_speech(self, audio_processor, sample_audio_data, org_id):
        """音声未検出エラー"""
        input_data = MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id=org_id,
            audio_data=sample_audio_data,
        )

        # 空の文字起こし結果
        empty_result = {"text": "", "language": "ja", "segments": []}

        with patch.object(
            audio_processor._whisper_client,
            "transcribe",
            new_callable=AsyncMock,
            return_value=empty_result,
        ):
            with patch.object(
                audio_processor,
                "_extract_audio_metadata",
                new_callable=AsyncMock,
                return_value=AudioMetadata(duration_seconds=60),
            ):
                with pytest.raises(NoSpeechDetectedError):
                    await audio_processor.process(input_data)

    @pytest.mark.asyncio
    async def test_process_audio_too_long(self, audio_processor, sample_audio_data, org_id):
        """音声時間超過エラー"""
        input_data = MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id=org_id,
            audio_data=sample_audio_data,
        )

        # 3時間の音声メタデータ
        long_metadata = AudioMetadata(
            duration_seconds=3 * 60 * 60,  # 3時間
            format="mp3",
        )

        with patch.object(
            audio_processor,
            "_extract_audio_metadata",
            new_callable=AsyncMock,
            return_value=long_metadata,
        ):
            with pytest.raises(AudioTooLongError):
                await audio_processor.process(input_data)


# =============================================================================
# ファクトリ関数テスト
# =============================================================================


class TestFactoryFunctions:
    """ファクトリ関数のテスト"""

    def test_create_audio_processor(self, mock_pool, org_id):
        """create_audio_processor"""
        processor = create_audio_processor(
            pool=mock_pool,
            organization_id=org_id,
            api_key="openrouter-key",
            openai_api_key="openai-key",
        )

        assert isinstance(processor, AudioProcessor)
        assert processor._organization_id == org_id


# =============================================================================
# パッケージインポートテスト
# =============================================================================


class TestPackageImports:
    """パッケージインポートのテスト"""

    def test_import_audio_types(self):
        """音声関連タイプのインポート"""
        from lib.capabilities.multimodal import (
            AudioType,
            TranscriptionStatus,
            SpeakerLabel,
        )

        assert AudioType.MEETING is not None
        assert TranscriptionStatus.COMPLETED is not None
        assert SpeakerLabel.SPEAKER_1 is not None

    def test_import_audio_constants(self):
        """音声関連定数のインポート"""
        from lib.capabilities.multimodal import (
            SUPPORTED_AUDIO_FORMATS,
            AUDIO_MIME_TYPES,
            MAX_AUDIO_SIZE_BYTES,
            MAX_AUDIO_DURATION_SECONDS,
            WHISPER_API_TIMEOUT_SECONDS,
            FEATURE_FLAG_AUDIO,
        )

        assert len(SUPPORTED_AUDIO_FORMATS) > 0
        assert MAX_AUDIO_SIZE_BYTES > 0

    def test_import_audio_exceptions(self):
        """音声関連例外のインポート"""
        from lib.capabilities.multimodal import (
            AudioProcessingError,
            AudioDecodeError,
            AudioTooLongError,
            AudioTranscriptionError,
            NoSpeechDetectedError,
            SpeakerDetectionError,
            WhisperAPIError,
            WhisperAPITimeoutError,
            WhisperAPIRateLimitError,
        )

        assert AudioProcessingError is not None
        assert WhisperAPIError is not None

    def test_import_audio_models(self):
        """音声関連モデルのインポート"""
        from lib.capabilities.multimodal import (
            Speaker,
            TranscriptSegment,
            AudioMetadata,
            AudioAnalysisResult,
        )

        assert Speaker is not None
        assert AudioAnalysisResult is not None

    def test_import_audio_processor(self):
        """AudioProcessorのインポート"""
        from lib.capabilities.multimodal import (
            AudioProcessor,
            WhisperAPIClient,
            create_audio_processor,
        )

        assert AudioProcessor is not None
        assert WhisperAPIClient is not None
        assert create_audio_processor is not None


# =============================================================================
# 統合テスト
# =============================================================================


class TestIntegration:
    """統合テスト"""

    def test_coordinator_audio_type_detection(self, mock_pool, org_id):
        """Coordinatorの音声タイプ検出"""
        from lib.capabilities.multimodal import (
            MultimodalCoordinator,
            AttachmentType,
        )

        coordinator = MultimodalCoordinator(mock_pool, org_id)

        # MP3
        result = coordinator.detect_attachment_type(filename="meeting.mp3")
        assert result == AttachmentType.AUDIO

        # WAV
        result = coordinator.detect_attachment_type(filename="recording.wav")
        assert result == AttachmentType.AUDIO

        # M4A
        result = coordinator.detect_attachment_type(filename="voice.m4a")
        assert result == AttachmentType.AUDIO

        # MIMEタイプで検出
        result = coordinator.detect_attachment_type(mime_type="audio/mpeg")
        assert result == AttachmentType.AUDIO

    def test_coordinator_supported_formats_includes_audio(self, mock_pool, org_id):
        """Coordinatorのサポートフォーマットに音声が含まれる"""
        from lib.capabilities.multimodal import MultimodalCoordinator

        coordinator = MultimodalCoordinator(mock_pool, org_id)
        formats = coordinator.get_supported_formats()

        assert "audio" in formats
        assert "mp3" in formats["audio"]
        assert "wav" in formats["audio"]

    def test_coordinator_size_limits_includes_audio(self, mock_pool, org_id):
        """Coordinatorのサイズ制限に音声が含まれる"""
        from lib.capabilities.multimodal import MultimodalCoordinator

        coordinator = MultimodalCoordinator(mock_pool, org_id)
        limits = coordinator.get_size_limits()

        assert "audio" in limits
        assert limits["audio"] == MAX_AUDIO_SIZE_BYTES

    def test_coordinator_audio_limits(self, mock_pool, org_id):
        """Coordinatorの音声制限情報"""
        from lib.capabilities.multimodal import MultimodalCoordinator

        coordinator = MultimodalCoordinator(mock_pool, org_id)
        limits = coordinator.get_audio_limits()

        assert limits["max_size_bytes"] == MAX_AUDIO_SIZE_BYTES
        assert limits["max_duration_minutes"] == MAX_AUDIO_DURATION_MINUTES
        assert "mp3" in limits["supported_formats"]
