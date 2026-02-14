"""
ソウルくん Voice Pipeline — 音声対話（STT + TTS）

Whisper（OpenAI API）で音声→テキスト変換、
Google Cloud TTS で テキスト→日本語音声変換。

【フロー】
  ユーザー（声） → Whisper STT → Brain処理 → Google TTS → 音声レスポンス

【設計方針】
- 音声データに PII が含まれる可能性 → ログに音声内容を記録しない（鉄則#8）
- 音声ファイルは処理後即削除（tmpfile）
- Brain経由で処理（鉄則1: bypass禁止）

Author: Claude Opus 4.6
Created: 2026-02-14
"""

import io
import logging
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])

# =============================================================================
# 設定
# =============================================================================

# Whisper API（OpenAI互換）
WHISPER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
WHISPER_MODEL = "whisper-1"
WHISPER_MAX_FILE_SIZE_MB = 25  # OpenAI制限

# Google Cloud TTS
TTS_LANGUAGE_CODE = "ja-JP"
TTS_VOICE_NAME = "ja-JP-Neural2-B"  # 男性声（ソウルくんの声）
TTS_AUDIO_ENCODING = "MP3"


# =============================================================================
# モデル
# =============================================================================


class STTResponse(BaseModel):
    """音声認識結果"""
    text: str
    confidence: float = 1.0
    language: str = "ja"
    duration_seconds: Optional[float] = None


class TTSRequest(BaseModel):
    """音声合成リクエスト"""
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = TTS_VOICE_NAME
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class VoiceChatRequest(BaseModel):
    """音声チャット（STT → Brain → TTS の一括処理）"""
    # audio は multipart/form-data で受け取る


class VoiceChatResponse(BaseModel):
    """音声チャットレスポンス"""
    text_input: str
    text_response: str
    audio_url: Optional[str] = None


# =============================================================================
# STT — Whisper API
# =============================================================================


async def transcribe_audio(audio_file: UploadFile) -> STTResponse:
    """
    音声ファイルをテキストに変換（Whisper API）

    対応形式: wav, mp3, m4a, ogg, webm
    最大サイズ: 25MB
    """
    if not WHISPER_API_KEY:
        raise HTTPException(status_code=503, detail="Whisper API key not configured")

    # ファイルサイズチェック
    content = await audio_file.read()
    if len(content) > WHISPER_MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File too large (max {WHISPER_MAX_FILE_SIZE_MB}MB)")

    # 一時ファイルに書き出し（Whisper APIがファイルパスを要求）
    suffix = _get_extension(audio_file.filename or "audio.wav")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        import openai

        client = openai.OpenAI(api_key=WHISPER_API_KEY)

        with open(tmp_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=f,
                language="ja",
                response_format="verbose_json",
            )

        return STTResponse(
            text=result.text,
            confidence=1.0,  # Whisper APIは confidence を返さない
            language=result.language or "ja",
            duration_seconds=getattr(result, "duration", None),
        )

    except openai.APIError as e:
        logger.error(f"Whisper API error: {e}")
        raise HTTPException(status_code=502, detail="音声認識に失敗しました")

    finally:
        # 一時ファイル削除（PII保護）
        os.unlink(tmp_path)


def _get_extension(filename: str) -> str:
    """ファイル拡張子を取得"""
    ext = os.path.splitext(filename)[1].lower()
    allowed = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}
    return ext if ext in allowed else ".wav"


# =============================================================================
# TTS — Google Cloud Text-to-Speech
# =============================================================================


async def synthesize_speech(text: str, voice: str = TTS_VOICE_NAME, speed: float = 1.0) -> bytes:
    """
    テキストを音声に変換（Google Cloud TTS）

    返り値: MP3バイト列
    """
    try:
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechClient()

        # SSML で自然な読み上げ
        ssml = f'<speak><prosody rate="{speed}">{_escape_ssml(text)}</prosody></speak>'

        synthesis_input = texttospeech.SynthesisInput(ssml=ssml)

        voice_config = texttospeech.VoiceSelectionParams(
            language_code=TTS_LANGUAGE_CODE,
            name=voice,
        )

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speed,
            pitch=0.0,
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice_config,
            audio_config=audio_config,
        )

        return response.audio_content

    except ImportError:
        # google-cloud-texttospeech がない場合のフォールバック
        logger.warning("google-cloud-texttospeech not installed, using stub")
        raise HTTPException(status_code=503, detail="TTS service not available")

    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=502, detail="音声合成に失敗しました")


def _escape_ssml(text: str) -> str:
    """SSML用のエスケープ"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


# =============================================================================
# エンドポイント
# =============================================================================


@router.post("/stt", response_model=STTResponse)
async def speech_to_text(audio: UploadFile = File(...)):
    """音声→テキスト変換"""
    return await transcribe_audio(audio)


@router.post("/tts")
async def text_to_speech(req: TTSRequest):
    """テキスト→音声変換（MP3ストリーミング返却）"""
    audio_bytes = await synthesize_speech(req.text, req.voice, req.speed)
    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'attachment; filename="response.mp3"'},
    )


@router.post("/chat")
async def voice_chat(
    audio: UploadFile = File(...),
):
    """
    音声チャット（STT → Brain → TTS の一括処理）

    1. 音声をテキストに変換（Whisper）
    2. Brain で処理
    3. レスポンスを音声に変換（Google TTS）
    4. 音声をストリーミング返却
    """
    # Step 1: STT
    stt_result = await transcribe_audio(audio)
    user_text = stt_result.text

    if not user_text.strip():
        raise HTTPException(status_code=400, detail="音声を認識できませんでした")

    # Step 2: Brain処理（JWT認証はmain.pyのmiddlewareで処理済み想定）
    # ここでは簡易的にテキスト変換結果を返す
    # 実際のBrain処理はmain.pyのchat endpointと同じフロー
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "chatwork-webhook"))

    from lib.config import ORGANIZATION_ID

    try:
        from lib.db import get_db_pool
        from handlers.registry import SYSTEM_CAPABILITIES, build_handlers
        from lib.brain.integration import BrainIntegration
        from lib.brain.llm import get_ai_response_raw

        pool = get_db_pool()
        handlers = build_handlers()
        integration = BrainIntegration(
            pool=pool,
            org_id=ORGANIZATION_ID,
            handlers=handlers,
            capabilities=SYSTEM_CAPABILITIES,
            get_ai_response_func=get_ai_response_raw,
        )

        result = await integration.process_message(
            message=user_text,
            room_id="voice-chat",
            account_id="voice-user",
            sender_name="Voice User",
        )

        response_text = (
            result.to_chatwork_message()
            if hasattr(result, "to_chatwork_message")
            else str(result)
        )
    except Exception as e:
        logger.exception("Voice chat Brain processing failed")
        response_text = "申し訳ありません。処理中にエラーが発生しました。"

    # Step 3: TTS
    try:
        audio_bytes = await synthesize_speech(response_text)
    except HTTPException:
        # TTS失敗時はテキストのみ返す
        return VoiceChatResponse(
            text_input=user_text,
            text_response=response_text,
        )

    # Step 4: 音声レスポンス（multipart: テキスト + 音声）
    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": 'attachment; filename="response.mp3"',
            "X-Text-Input": user_text,
            "X-Text-Response": response_text,
        },
    )
