# lib/capabilities/multimodal/audio_processor.py
"""
Phase M2: 音声入力能力 - 音声プロセッサー

このモジュールは、音声ファイルを処理して文字起こし・分析を行うプロセッサーを提供します。

設計書: docs/20_next_generation_capabilities.md セクション5.6
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from uuid import uuid4
import logging
import os
import io
import json
import re
import httpx

from .constants import (
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
    AUDIO_CHUNK_DURATION_SECONDS,
    WHISPER_API_TIMEOUT_SECONDS,
    AUDIO_PROCESSING_TIMEOUT_SECONDS,
    DEFAULT_WHISPER_MODEL,
    DEFAULT_WHISPER_LANGUAGE,
    DEFAULT_WHISPER_RESPONSE_FORMAT,
    MAX_SPEAKERS,
    MAX_AUDIO_SUMMARY_LENGTH,
    MAX_TRANSCRIPT_LENGTH,
    AUDIO_TYPE_KEYWORDS,
)
from .exceptions import (
    ValidationError,
    UnsupportedFormatError,
    FileTooLargeError,
    AudioProcessingError,
    AudioDecodeError,
    AudioTooLongError,
    AudioTranscriptionError,
    NoSpeechDetectedError,
    SpeakerDetectionError,
    WhisperAPIError,
    WhisperAPITimeoutError,
    WhisperAPIRateLimitError,
    wrap_multimodal_error,
)
from .models import (
    ProcessingMetadata,
    ExtractedEntity,
    MultimodalInput,
    MultimodalOutput,
    Speaker,
    TranscriptSegment,
    AudioMetadata,
    AudioAnalysisResult,
)
from .base import BaseMultimodalProcessor


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# Whisper APIクライアント
# =============================================================================


class WhisperAPIClient:
    """
    Whisper APIクライアント

    OpenAI Whisper APIを使用して音声を文字起こしする。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_WHISPER_MODEL,
        timeout_seconds: int = WHISPER_API_TIMEOUT_SECONDS,
    ):
        """
        初期化

        Args:
            api_key: OpenAI API Key（省略時は環境変数から取得）
            model: Whisperモデル
            timeout_seconds: タイムアウト秒数
        """
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._api_url = "https://api.openai.com/v1/audio/transcriptions"

    async def transcribe(
        self,
        audio_data: bytes,
        filename: str = "audio.mp3",
        language: Optional[str] = None,
        response_format: str = DEFAULT_WHISPER_RESPONSE_FORMAT,
        prompt: Optional[str] = None,
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """
        音声を文字起こしする

        Args:
            audio_data: 音声のバイナリデータ
            filename: ファイル名（拡張子でフォーマット判定）
            language: 言語コード（Noneで自動検出）
            response_format: レスポンス形式
            prompt: 文字起こしのヒント（専門用語等）
            temperature: 温度パラメータ（0.0-1.0）

        Returns:
            文字起こし結果（text, segments, language等）

        Raises:
            WhisperAPIError: API呼び出しに失敗した場合
        """
        if not self._api_key:
            raise WhisperAPIError("OpenAI API key not configured")

        # フォームデータ構築
        files = {
            "file": (filename, audio_data, self._get_mime_type(filename)),
        }

        data = {
            "model": self._model,
            "response_format": response_format,
            "temperature": str(temperature),
        }

        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt

        headers = {
            "Authorization": f"Bearer {self._api_key}",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    self._api_url,
                    headers=headers,
                    files=files,
                    data=data,
                )

                # レート制限チェック
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    raise WhisperAPIRateLimitError(
                        model=self._model,
                        retry_after=int(retry_after) if retry_after else None,
                    )

                response.raise_for_status()

                # レスポンス解析
                if response_format in ("json", "verbose_json"):
                    result: Dict[str, Any] = response.json()
                else:
                    result = {"text": response.text}

                return result

        except httpx.TimeoutException:
            raise WhisperAPITimeoutError(
                model=self._model,
                timeout_seconds=self._timeout_seconds,
            )
        except httpx.HTTPError as e:
            raise WhisperAPIError(
                message=f"Whisper API HTTP error: {str(e)}",
                model=self._model,
                original_error=e,
            )
        except WhisperAPIError:
            raise
        except Exception as e:
            raise WhisperAPIError(
                message=f"Whisper API error: {str(e)}",
                model=self._model,
                original_error=e,
            )

    def _get_mime_type(self, filename: str) -> str:
        """ファイル名からMIMEタイプを取得"""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp3"
        return AUDIO_MIME_TYPES.get(ext, "audio/mpeg")


# =============================================================================
# 音声プロセッサー
# =============================================================================


class AudioProcessor(BaseMultimodalProcessor):
    """
    音声プロセッサー

    音声ファイルを処理して文字起こし・要約・分析を行う。

    使用例:
        processor = AudioProcessor(pool, org_id)
        result = await processor.process(MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id=org_id,
            audio_data=audio_bytes,
            detect_speakers=True,
            generate_summary=True,
        ))
    """

    def __init__(
        self,
        pool,
        organization_id: str,
        api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            api_key: OpenRouter API Key（要約生成用）
            openai_api_key: OpenAI API Key（Whisper用）
        """
        super().__init__(
            pool=pool,
            organization_id=organization_id,
            api_key=api_key,
            input_type=InputType.AUDIO,
        )
        self._openai_api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        self._whisper_client = WhisperAPIClient(api_key=self._openai_api_key)

    # =========================================================================
    # メイン処理
    # =========================================================================

    @wrap_multimodal_error
    async def process(self, input_data: MultimodalInput) -> MultimodalOutput:
        """
        音声を処理

        Args:
            input_data: 入力データ

        Returns:
            MultimodalOutput: 処理結果
        """
        # 入力検証
        self.validate(input_data)

        # メタデータ初期化
        metadata = self._create_processing_metadata()
        self._log_processing_start("audio")

        try:
            # 音声データ取得
            audio_data = await self._get_audio_data(input_data)

            # 音声メタデータ抽出
            audio_metadata = await self._extract_audio_metadata(
                audio_data, input_data.file_path
            )

            # 時間制限チェック
            if audio_metadata.duration_seconds > MAX_AUDIO_DURATION_SECONDS:
                raise AudioTooLongError(
                    actual_duration_seconds=audio_metadata.duration_seconds,
                    max_duration_seconds=MAX_AUDIO_DURATION_SECONDS,
                )

            # 文字起こし
            transcript_result = await self._transcribe_audio(
                audio_data=audio_data,
                filename=self._get_filename(input_data),
                language=input_data.language,
            )

            # セグメント解析
            segments = self._parse_segments(transcript_result)
            full_transcript = transcript_result.get("text", "")

            # 音声が検出されなかった場合
            if not full_transcript.strip():
                raise NoSpeechDetectedError()

            # 検出言語
            detected_language = transcript_result.get("language", input_data.language)

            # 話者分離（オプション）
            speakers = []
            if input_data.detect_speakers and segments:
                speakers = await self._detect_speakers(segments)
                # セグメントに話者を紐付け
                segments = self._assign_speakers_to_segments(segments, speakers)

            # 要約生成（オプション）
            summary = ""
            key_points = []
            action_items = []
            topics = []

            if input_data.generate_summary and full_transcript:
                summary_result = await self._generate_summary(
                    transcript=full_transcript,
                    segments=segments,
                    instruction=input_data.instruction,
                )
                summary = summary_result.get("summary", "")
                key_points = summary_result.get("key_points", [])
                action_items = summary_result.get("action_items", [])
                topics = summary_result.get("topics", [])

            # 音声タイプ判定
            audio_type = self._detect_audio_type(
                transcript=full_transcript,
                instruction=input_data.instruction,
            )

            # エンティティ抽出
            entities = self._extract_entities_from_text(full_transcript)

            # 確信度計算
            overall_confidence = self._calculate_overall_confidence(
                transcript_result, segments
            )

            # 結果構築
            result = AudioAnalysisResult(
                success=True,
                audio_type=audio_type,
                audio_metadata=audio_metadata,
                full_transcript=full_transcript[:MAX_TRANSCRIPT_LENGTH],
                segments=segments,
                transcription_status=TranscriptionStatus.COMPLETED,
                speakers=speakers,
                speaker_count=len(speakers),
                speakers_detected=len(speakers) > 0,
                detected_language=detected_language,
                language_confidence=transcript_result.get("language_confidence", 0.9),
                summary=summary[:MAX_AUDIO_SUMMARY_LENGTH],
                key_points=key_points[:10],
                action_items=action_items[:10],
                topics=topics[:10],
                entities=entities[:50],
                overall_confidence=overall_confidence,
                confidence_level=self._calculate_confidence_level(overall_confidence),
                metadata=metadata,
            )

            # メタデータ完了
            metadata = self._complete_processing_metadata(metadata, success=True)
            result.metadata = metadata

            self._log_processing_complete(
                success=True,
                processing_time_ms=metadata.processing_time_ms,
                details={
                    "duration_seconds": audio_metadata.duration_seconds,
                    "transcript_length": len(full_transcript),
                    "segment_count": len(segments),
                    "speaker_count": len(speakers),
                },
            )

            return MultimodalOutput(
                success=True,
                input_type=InputType.AUDIO,
                audio_result=result,
                summary=summary,
                extracted_text=full_transcript,
                entities=entities,
                metadata=metadata,
            )

        except AudioProcessingError:
            raise
        except Exception as e:
            metadata = self._complete_processing_metadata(
                metadata,
                success=False,
                error_message=str(e),
                error_code="AUDIO_PROCESSING_ERROR",
            )
            self._log_processing_complete(
                success=False,
                processing_time_ms=metadata.processing_time_ms,
                details={"error": str(e)},
            )
            raise AudioProcessingError(
                message=f"音声処理中にエラーが発生したウル: {str(e)}"
            )

    def validate(self, input_data: MultimodalInput) -> None:
        """
        入力を検証

        Args:
            input_data: 入力データ

        Raises:
            ValidationError: 検証に失敗した場合
        """
        self._validate_organization_id()

        if input_data.input_type != InputType.AUDIO:
            raise ValidationError(
                message=f"Invalid input type: {input_data.input_type}",
                field="input_type",
                input_type=InputType.AUDIO,
            )

        # データ存在チェック
        if not input_data.audio_data and not input_data.file_path:
            raise ValidationError(
                message="audio_data or file_path is required",
                field="audio_data",
                input_type=InputType.AUDIO,
            )

        # ファイル拡張子チェック
        if input_data.file_path:
            ext = input_data.file_path.rsplit(".", 1)[-1].lower()
            if ext not in SUPPORTED_AUDIO_FORMATS:
                raise UnsupportedFormatError(
                    format_name=ext,
                    supported_formats=list(SUPPORTED_AUDIO_FORMATS),
                    input_type=InputType.AUDIO,
                )

        # ファイルサイズチェック
        if input_data.audio_data:
            size = len(input_data.audio_data)
            if size > MAX_AUDIO_SIZE_BYTES:
                raise FileTooLargeError(
                    actual_size_bytes=size,
                    max_size_bytes=MAX_AUDIO_SIZE_BYTES,
                    input_type=InputType.AUDIO,
                )

    # =========================================================================
    # 内部メソッド
    # =========================================================================

    async def _get_audio_data(self, input_data: MultimodalInput) -> bytes:
        """音声データを取得"""
        if input_data.audio_data:
            return input_data.audio_data

        if input_data.file_path:
            with open(input_data.file_path, "rb") as f:
                return f.read()

        raise ValidationError(
            message="No audio data provided",
            field="audio_data",
            input_type=InputType.AUDIO,
        )

    async def _extract_audio_metadata(
        self,
        audio_data: bytes,
        file_path: Optional[str] = None,
    ) -> AudioMetadata:
        """
        音声メタデータを抽出

        mutagen等のライブラリがない場合は基本情報のみ返す。
        """
        metadata = AudioMetadata(
            file_size_bytes=len(audio_data),
        )

        # ファイル拡張子からフォーマット推定
        if file_path:
            ext = file_path.rsplit(".", 1)[-1].lower()
            metadata.format = ext

        # マジックナンバーからフォーマット検出
        detected_format = self._detect_audio_format(audio_data)
        if detected_format:
            metadata.format = detected_format

        # mutagenが利用可能な場合は詳細メタデータ取得
        try:
            import mutagen
            from mutagen.mp3 import MP3
            from mutagen.wave import WAVE
            from mutagen.mp4 import MP4
            from mutagen.flac import FLAC
            from mutagen.ogg import OggFileType

            # BytesIOでラップ
            audio_file = io.BytesIO(audio_data)

            # フォーマットに応じて処理
            audio = None
            if metadata.format in ("mp3", "mpeg", "mpga"):
                audio = MP3(audio_file)
            elif metadata.format == "wav":
                audio = WAVE(audio_file)
            elif metadata.format in ("m4a", "mp4"):
                audio = MP4(audio_file)
            elif metadata.format == "flac":
                audio = FLAC(audio_file)
            elif metadata.format == "ogg":
                audio = mutagen.File(audio_file)

            if audio:
                if hasattr(audio, "info"):
                    info = audio.info
                    metadata.duration_seconds = getattr(info, "length", 0.0)
                    metadata.sample_rate = getattr(info, "sample_rate", None)
                    metadata.channels = getattr(info, "channels", 1)
                    metadata.bitrate = getattr(info, "bitrate", None)

        except ImportError:
            logger.warning("mutagen not available, using estimated duration")
            # mutagenがない場合は推定値を使用
            metadata.duration_seconds = self._estimate_duration(
                audio_data, metadata.format
            )
        except Exception as e:
            logger.warning(f"Failed to extract audio metadata: {e}")
            metadata.duration_seconds = self._estimate_duration(
                audio_data, metadata.format
            )

        return metadata

    def _detect_audio_format(self, data: bytes) -> Optional[str]:
        """マジックナンバーから音声フォーマットを検出"""
        if len(data) < 12:
            return None

        # ID3タグ（MP3）
        if data[:3] == b'ID3':
            return "mp3"
        # MP3フレームヘッダ
        if data[:2] == b'\xff\xfb' or data[:2] == b'\xff\xfa':
            return "mp3"
        # RIFF WAV
        if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
            return "wav"
        # FLAC
        if data[:4] == b'fLaC':
            return "flac"
        # OGG
        if data[:4] == b'OggS':
            return "ogg"
        # MP4/M4A
        if data[4:8] == b'ftyp':
            return "m4a"

        return None

    def _estimate_duration(self, audio_data: bytes, format: str) -> float:
        """
        音声の長さを推定

        正確な値を得るにはmutagenが必要。
        """
        size_bytes = len(audio_data)

        # フォーマット別の平均ビットレート（kbps）で推定
        bitrate_estimates = {
            "mp3": 128,
            "m4a": 128,
            "wav": 1411,  # CD品質
            "flac": 800,
            "ogg": 128,
        }

        bitrate_kbps = bitrate_estimates.get(format, 128)
        bitrate_bytes_per_sec = bitrate_kbps * 1000 / 8

        return size_bytes / bitrate_bytes_per_sec

    def _get_filename(self, input_data: MultimodalInput) -> str:
        """ファイル名を取得"""
        if input_data.file_path:
            return os.path.basename(input_data.file_path)
        return "audio.mp3"

    async def _transcribe_audio(
        self,
        audio_data: bytes,
        filename: str,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Whisper APIで文字起こし"""
        return await self._whisper_client.transcribe(
            audio_data=audio_data,
            filename=filename,
            language=language or DEFAULT_WHISPER_LANGUAGE,
            response_format="verbose_json",
        )

    def _parse_segments(
        self,
        transcript_result: Dict[str, Any],
    ) -> List[TranscriptSegment]:
        """文字起こし結果からセグメントを解析"""
        segments = []

        raw_segments = transcript_result.get("segments", [])
        for i, seg in enumerate(raw_segments):
            segment = TranscriptSegment(
                segment_id=i,
                text=seg.get("text", "").strip(),
                start_time=seg.get("start", 0.0),
                end_time=seg.get("end", 0.0),
                confidence=seg.get("avg_logprob", 0.0),
                language=transcript_result.get("language"),
            )

            # 確信度を0-1に正規化（log probは負の値）
            if segment.confidence < 0:
                segment.confidence = min(1.0, max(0.0, 1.0 + segment.confidence / 10))

            segments.append(segment)

        return segments

    async def _detect_speakers(
        self,
        segments: List[TranscriptSegment],
    ) -> List[Speaker]:
        """
        話者を検出

        現在は簡易的な実装。将来的にはpyannote-audio等を使用。
        """
        # 簡易実装: セグメント間の沈黙で話者を推定
        speakers: List[Speaker] = []
        current_speaker_id = 1
        speakers_map: Dict[int, Speaker] = {}

        prev_end = 0.0
        for segment in segments:
            # 1秒以上の沈黙があれば話者交代の可能性
            gap = segment.start_time - prev_end
            if gap > 1.0 and current_speaker_id < MAX_SPEAKERS:
                current_speaker_id += 1

            if current_speaker_id not in speakers_map:
                speakers_map[current_speaker_id] = Speaker(
                    speaker_id=f"speaker_{current_speaker_id}",
                    label=SpeakerLabel.from_index(current_speaker_id),
                    speaking_time_seconds=0.0,
                    segment_count=0,
                    confidence=0.6,  # 簡易実装のため低めの確信度
                )

            speaker = speakers_map[current_speaker_id]
            speaker.speaking_time_seconds += segment.duration
            speaker.segment_count += 1
            segment.speaker = speaker

            prev_end = segment.end_time

        return list(speakers_map.values())

    def _assign_speakers_to_segments(
        self,
        segments: List[TranscriptSegment],
        speakers: List[Speaker],
    ) -> List[TranscriptSegment]:
        """話者をセグメントに割り当て（すでに割り当て済みの場合はスキップ）"""
        # _detect_speakersで既に割り当て済みなのでそのまま返す
        return segments

    async def _generate_summary(
        self,
        transcript: str,
        segments: List[TranscriptSegment],
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """要約を生成"""
        # 文字起こしが短い場合はそのまま返す
        if len(transcript) < 200:
            return {
                "summary": transcript,
                "key_points": [],
                "action_items": [],
                "topics": [],
            }

        prompt = self._get_audio_summary_prompt(
            transcript=transcript,
            segment_count=len(segments),
            instruction=instruction,
        )

        try:
            # Vision APIクライアントを流用（テキスト処理）
            # 実際にはLLM APIを直接呼び出すべきだが、既存インフラを活用
            result = await self._call_llm_for_summary(prompt)
            return result
        except Exception as e:
            logger.warning(f"Failed to generate summary: {e}")
            return {
                "summary": self._truncate_text(transcript, 500),
                "key_points": [],
                "action_items": [],
                "topics": [],
            }

    async def _call_llm_for_summary(self, prompt: str) -> Dict[str, Any]:
        """LLMを呼び出して要約を生成"""
        if not self._api_key:
            return {
                "summary": "",
                "key_points": [],
                "action_items": [],
                "topics": [],
            }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://soulkun.soulsyncs.co.jp",
            "X-Title": "Soulkun Audio Processor",
        }

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.3,
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]

                # JSONを解析
                return self._parse_summary_response(content)

        except Exception as e:
            logger.warning(f"LLM call failed: {e}")
            return {
                "summary": "",
                "key_points": [],
                "action_items": [],
                "topics": [],
            }

    def _parse_summary_response(self, content: str) -> Dict[str, Any]:
        """LLMレスポンスから要約情報を解析"""
        result = {
            "summary": "",
            "key_points": [],
            "action_items": [],
            "topics": [],
        }

        # JSON部分を抽出
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                result["summary"] = parsed.get("summary", "")
                result["key_points"] = parsed.get("key_points", [])
                result["action_items"] = parsed.get("action_items", [])
                result["topics"] = parsed.get("topics", [])
                return result
            except json.JSONDecodeError:
                pass

        # JSONが見つからない場合はテキストから抽出
        result["summary"] = self._truncate_text(content, MAX_AUDIO_SUMMARY_LENGTH)
        return result

    def _detect_audio_type(
        self,
        transcript: str,
        instruction: Optional[str] = None,
    ) -> AudioType:
        """音声タイプを検出"""
        text_to_check = (transcript + " " + (instruction or "")).lower()

        for audio_type, keywords in AUDIO_TYPE_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text_to_check:
                    return AudioType(audio_type)

        return AudioType.UNKNOWN

    def _calculate_overall_confidence(
        self,
        transcript_result: Dict[str, Any],
        segments: List[TranscriptSegment],
    ) -> float:
        """全体の確信度を計算"""
        if not segments:
            return 0.5

        # セグメントの確信度の平均
        segment_confidences = [s.confidence for s in segments if s.confidence > 0]
        if not segment_confidences:
            return 0.7  # デフォルト値

        avg_confidence = sum(segment_confidences) / len(segment_confidences)

        # 言語検出の確信度も考慮（検出されていれば高め）
        if transcript_result.get("language"):
            avg_confidence = (avg_confidence + 0.9) / 2

        return min(1.0, max(0.0, avg_confidence))

    def _get_audio_summary_prompt(
        self,
        transcript: str,
        segment_count: int,
        instruction: Optional[str] = None,
    ) -> str:
        """音声要約用プロンプトを取得"""
        # 長すぎる場合は切り詰め
        transcript_preview = transcript[:15000]
        if len(transcript) > 15000:
            transcript_preview += "\n...(以下省略)"

        prompt = f"""以下の音声の文字起こしを分析して、要約・重要ポイント・アクションアイテムを抽出してください。

【文字起こし】（{segment_count}セグメント）
{transcript_preview}

【分析項目】
1. 要約（3-5文で内容を要約）
2. 重要ポイント（3-5個の箇条書き）
3. アクションアイテム（決定事項・タスク）
4. トピック（議題・テーマ）

回答はJSON形式で以下の構造で返してください：
```json
{{
    "summary": "要約テキスト",
    "key_points": ["ポイント1", "ポイント2", ...],
    "action_items": ["アクション1", "アクション2", ...],
    "topics": ["トピック1", "トピック2", ...]
}}
```"""

        if instruction:
            prompt += f"\n\n【追加の指示】\n{instruction}"

        return prompt


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_audio_processor(
    pool,
    organization_id: str,
    api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> AudioProcessor:
    """
    AudioProcessorを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        api_key: OpenRouter API Key（要約生成用）
        openai_api_key: OpenAI API Key（Whisper用）

    Returns:
        AudioProcessor: 音声プロセッサー
    """
    return AudioProcessor(
        pool=pool,
        organization_id=organization_id,
        api_key=api_key,
        openai_api_key=openai_api_key,
    )
