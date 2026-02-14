"""
ソウルくん Voice Pipeline — 音声対話（STT + TTS）

Whisper（OpenAI API）で音声→テキスト変換、
Google Cloud TTS で テキスト→日本語音声変換。

【設計方針】
- 全エンドポイントにJWT認証必須（鉄則#4）
- organization_id はJWTから取得（鉄則#1: ハードコード禁止）
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
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])

# =============================================================================
# 設定
# =============================================================================

WHISPER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
WHISPER_MODEL = "whisper-1"
WHISPER_MAX_FILE_SIZE_MB = 25

TTS_LANGUAGE_CODE = "ja-JP"
TTS_VOICE_NAME = "ja-JP-Neural2-B"


# =============================================================================
# モデル
# =============================================================================


class STTResponse(BaseModel):
    text: str
    confidence: float = 1.0
    language: str = "ja"
    duration_seconds: Optional[float] = None


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = TTS_VOICE_NAME
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class VoiceChatResponse(BaseModel):
    text_input: str
    text_response: str


# =============================================================================
# 認証依存 — main.py からインポート
# =============================================================================


def _get_current_user():
    """遅延インポートで循環依存を回避"""
    from main import get_current_user
    return get_current_user


# =============================================================================
# STT — Whisper API
# =============================================================================


async def transcribe_audio(audio_file: UploadFile) -> STTResponse:
    """
    音声ファイルをテキストに変換（Whisper API）

    対応形式: wav, mp3, m4a, ogg, webm, flac
    最大サイズ: 25MB
    """
    if not WHISPER_API_KEY:
        raise HTTPException(status_code=503, detail="Whisper API key not configured")

    content = await audio_file.read()
    if len(content) > WHISPER_MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {WHISPER_MAX_FILE_SIZE_MB}MB)",
        )

    # content-type検証
    allowed_types = {
        "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3",
        "audio/mp4", "audio/m4a", "audio/ogg", "audio/webm", "audio/flac",
    }
    if audio_file.content_type and audio_file.content_type not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio format: {audio_file.content_type}",
        )

    suffix = _get_extension(audio_file.filename or "audio.wav")

    # 専用一時ディレクトリで安全にファイル作成
    tmp_dir = tempfile.mkdtemp(prefix="soulkun_voice_")
    tmp_path = os.path.join(tmp_dir, f"audio{suffix}")

    try:
        with open(tmp_path, "wb") as f:
            f.write(content)

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
            confidence=1.0,
            language=result.language or "ja",
            duration_seconds=getattr(result, "duration", None),
        )

    except openai.APIError as e:
        # PII保護: APIエラー詳細はログに出さない（鉄則#8）
        logger.error(f"Whisper API error: status={getattr(e, 'status_code', 'unknown')}")
        raise HTTPException(status_code=502, detail="音声認識に失敗しました")

    finally:
        # 一時ファイル + ディレクトリ削除（PII保護）
        try:
            os.unlink(tmp_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass


def _get_extension(filename: str) -> str:
    """ファイル拡張子を取得"""
    ext = os.path.splitext(filename)[1].lower()
    allowed = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}
    return ext if ext in allowed else ".wav"


# =============================================================================
# TTS — Google Cloud Text-to-Speech
# =============================================================================


async def synthesize_speech(
    text: str,
    voice: str = TTS_VOICE_NAME,
    speed: float = 1.0,
) -> bytes:
    """テキストを音声に変換（Google Cloud TTS）。返り値: MP3バイト列"""
    try:
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechClient()

        synthesis_input = texttospeech.SynthesisInput(
            text=_escape_ssml(text),
        )

        voice_config = texttospeech.VoiceSelectionParams(
            language_code=TTS_LANGUAGE_CODE,
            name=voice,
        )

        # speed は AudioConfig のみで設定（SSMLとの二重適用を防ぐ）
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speed,
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice_config,
            audio_config=audio_config,
        )

        return response.audio_content

    except ImportError:
        logger.warning("google-cloud-texttospeech not installed")
        raise HTTPException(status_code=503, detail="TTS service not available")

    except Exception:
        logger.exception("TTS synthesis failed")
        raise HTTPException(status_code=502, detail="音声合成に失敗しました")


def _escape_ssml(text: str) -> str:
    """SSML特殊文字のエスケープ"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


# =============================================================================
# エンドポイント（全てJWT認証必須）
# =============================================================================


@router.post("/stt", response_model=STTResponse)
async def speech_to_text(
    audio: UploadFile = File(...),
    user: Dict = Depends(_get_current_user()),
):
    """音声→テキスト変換（認証必須）"""
    return await transcribe_audio(audio)


@router.post("/tts")
async def text_to_speech(
    req: TTSRequest,
    user: Dict = Depends(_get_current_user()),
):
    """テキスト→音声変換（MP3ストリーミング返却、認証必須）"""
    audio_bytes = await synthesize_speech(req.text, req.voice, req.speed)
    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'attachment; filename="response.mp3"'},
    )


@router.post("/chat", response_model=VoiceChatResponse)
async def voice_chat(
    audio: UploadFile = File(...),
    user: Dict = Depends(_get_current_user()),
):
    """
    音声チャット（STT → Brain → TTS の一括処理、認証必須）

    レスポンス: JSON（テキスト入力 + テキスト応答）
    音声が必要な場合はクライアントが /tts を別途呼ぶ。
    PII保護のためHTTPヘッダーにはテキストを含めない。
    """
    # Step 1: STT
    stt_result = await transcribe_audio(audio)
    user_text = stt_result.text

    if not user_text.strip():
        raise HTTPException(status_code=400, detail="音声を認識できませんでした")

    # Step 2: Brain処理（JWT の org_id / user_id を使用）
    try:
        from main import _get_pool, _get_handlers, _get_capabilities
        from lib.brain.integration import BrainIntegration
        from lib.brain.llm import get_ai_response_raw

        pool = _get_pool()
        handlers = _get_handlers()
        capabilities = _get_capabilities()

        integration = BrainIntegration(
            pool=pool,
            org_id=user["org_id"],
            handlers=handlers,
            capabilities=capabilities,
            get_ai_response_func=get_ai_response_raw,
        )

        result = await integration.process_message(
            message=user_text,
            room_id=f"voice-{user['sub']}",
            account_id=user["sub"],
            sender_name=user.get("display_name", "Voice User"),
        )

        response_text = (
            result.to_chatwork_message()
            if hasattr(result, "to_chatwork_message")
            else str(result)
        )
    except Exception:
        logger.exception("Voice chat Brain processing failed")
        response_text = "申し訳ありません。処理中にエラーが発生しました。"

    # JSON レスポンス（PII保護: HTTPヘッダーにテキストを入れない）
    return VoiceChatResponse(
        text_input=user_text,
        text_response=response_text,
    )
