# lib/capabilities/apps/meeting_minutes/meeting_minutes_generator.py
"""
App1: 議事録自動生成 - メインジェネレーター

M2（音声入力）とG1（文書生成）を統合し、
音声ファイルから議事録を自動生成する。

フロー:
1. 音声ファイルを受け取る
2. AudioProcessor で文字起こし・話者分離
3. LLM で会議内容を分析
4. DocumentGenerator で Google Docs に出力

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from typing import Optional, Dict, Any, List, TYPE_CHECKING
from uuid import UUID
import logging
import json

from .constants import (
    MeetingType,
    MinutesStatus,
    MinutesSection,
    DEFAULT_MINUTES_SECTIONS,
    MEETING_TYPE_SECTIONS,
    MEETING_TYPE_KEYWORDS,
    MINUTES_ANALYSIS_PROMPT,
    MINUTES_GENERATION_PROMPT,
    MAX_ACTION_ITEMS,
    MAX_DECISIONS,
    ANALYSIS_TIMEOUT,
    GENERATION_TIMEOUT,
    ERROR_MESSAGES,
)
from .models import (
    MeetingMinutesRequest,
    MeetingMinutesResult,
    MeetingAnalysis,
    ActionItem,
    Decision,
    DiscussionTopic,
)

# M2: 音声入力
from lib.capabilities.multimodal import (
    AudioProcessor,
    MultimodalInput,
    InputType,
    AudioAnalysisResult,
    NoSpeechDetectedError,
    AudioTooLongError,
)

# G1: 文書生成
from lib.capabilities.generation import (
    DocumentGenerator,
    DocumentRequest,
    DocumentResult,
    DocumentType,
    DocumentOutline,
    SectionOutline,
    SectionType,
    GenerationStatus,
    QualityLevel,
    ToneStyle,
)

if TYPE_CHECKING:
    from asyncpg import Pool


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# 議事録ジェネレーター
# =============================================================================


class MeetingMinutesGenerator:
    """
    議事録自動生成ジェネレーター

    M2（AudioProcessor）とG1（DocumentGenerator）を統合し、
    音声ファイルから議事録を自動生成する。
    """

    def __init__(
        self,
        pool: "Pool",
        organization_id: UUID,
        api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        google_credentials_path: Optional[str] = None,
        google_credentials_json: Optional[Dict[str, Any]] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            api_key: LLM API Key（OpenRouter）
            openai_api_key: OpenAI API Key（Whisper用）
            google_credentials_path: Google認証情報パス
            google_credentials_json: Google認証情報（JSON）
        """
        self._pool = pool
        self._organization_id = organization_id

        # M2: 音声プロセッサー
        self._audio_processor = AudioProcessor(
            pool=pool,
            organization_id=organization_id,
            api_key=api_key,
            openai_api_key=openai_api_key,
        )

        # G1: 文書ジェネレーター
        self._document_generator = DocumentGenerator(
            pool=pool,
            organization_id=organization_id,
            api_key=api_key,
            google_credentials_path=google_credentials_path,
            google_credentials_json=google_credentials_json,
        )

    async def generate(
        self,
        request: MeetingMinutesRequest,
    ) -> MeetingMinutesResult:
        """
        議事録を生成

        Args:
            request: 議事録生成リクエスト

        Returns:
            議事録生成結果
        """
        result = MeetingMinutesResult(
            status=MinutesStatus.PROCESSING,
            request_id=request.request_id,
        )

        try:
            # 1. 音声の文字起こし
            result.status = MinutesStatus.TRANSCRIBING
            logger.info(f"Starting transcription: {request.request_id}")

            audio_result = await self._transcribe_audio(request)

            result.transcript = audio_result.full_transcript
            result.transcript_segments = len(audio_result.segments)
            result.speakers_detected = audio_result.speaker_count
            result.audio_duration_seconds = audio_result.audio_metadata.duration_seconds if audio_result.audio_metadata else 0

            # 2. 会議内容の分析
            result.status = MinutesStatus.ANALYZING
            logger.info(f"Analyzing meeting content: {request.request_id}")

            analysis = await self._analyze_meeting(
                transcript=audio_result.full_transcript,
                segments=audio_result.segments,
                speakers=audio_result.speakers,
                request=request,
            )

            result.analysis = analysis
            result.total_tokens_used += analysis.tokens_used

            # 確認が必要な場合は一旦返す
            if request.require_confirmation:
                result.status = MinutesStatus.PENDING
                return result

            # 3. 議事録の生成
            result.status = MinutesStatus.GENERATING
            logger.info(f"Generating minutes: {request.request_id}")

            minutes_result = await self._generate_minutes(
                analysis=analysis,
                request=request,
            )

            result.minutes_content = minutes_result.full_content
            result.minutes_word_count = minutes_result.total_word_count
            result.document_id = minutes_result.document_id
            result.document_url = minutes_result.document_url
            result.total_tokens_used += minutes_result.metadata.total_tokens_used

            # コスト計算
            result.estimated_cost_jpy = self._calculate_cost(result.total_tokens_used)

            # 完了
            result.complete(success=True)
            logger.info(f"Minutes generation completed: {request.request_id}")

            return result

        except NoSpeechDetectedError:
            result.status = MinutesStatus.FAILED
            result.error_message = ERROR_MESSAGES["NO_SPEECH"]
            result.error_code = "NO_SPEECH"
            result.complete(success=False)
            return result

        except AudioTooLongError as e:
            result.status = MinutesStatus.FAILED
            result.error_message = str(e)
            result.error_code = "AUDIO_TOO_LONG"
            result.complete(success=False)
            return result

        except Exception as e:
            logger.error(f"Minutes generation failed: {str(e)}")
            result.status = MinutesStatus.FAILED
            result.error_message = str(e)
            result.error_code = "GENERATION_FAILED"
            result.complete(success=False)
            return result

    async def generate_from_analysis(
        self,
        analysis: MeetingAnalysis,
        request: MeetingMinutesRequest,
    ) -> MeetingMinutesResult:
        """
        分析結果から議事録を生成（確認後の続行用）

        Args:
            analysis: 会議分析結果
            request: 議事録生成リクエスト

        Returns:
            議事録生成結果
        """
        result = MeetingMinutesResult(
            status=MinutesStatus.GENERATING,
            request_id=request.request_id,
            analysis=analysis,
        )

        try:
            minutes_result = await self._generate_minutes(
                analysis=analysis,
                request=request,
            )

            result.minutes_content = minutes_result.full_content
            result.minutes_word_count = minutes_result.total_word_count
            result.document_id = minutes_result.document_id
            result.document_url = minutes_result.document_url
            result.total_tokens_used = minutes_result.metadata.total_tokens_used
            result.estimated_cost_jpy = self._calculate_cost(result.total_tokens_used)

            result.complete(success=True)
            return result

        except Exception as e:
            logger.error(f"Minutes generation from analysis failed: {str(e)}")
            result.status = MinutesStatus.FAILED
            result.error_message = str(e)
            result.error_code = "GENERATION_FAILED"
            result.complete(success=False)
            return result

    # =========================================================================
    # 内部メソッド
    # =========================================================================

    async def _transcribe_audio(
        self,
        request: MeetingMinutesRequest,
    ) -> AudioAnalysisResult:
        """
        音声を文字起こし

        Args:
            request: 議事録リクエスト

        Returns:
            音声分析結果
        """
        # MultimodalInputを構築
        audio_input = MultimodalInput(
            input_type=InputType.AUDIO,
            organization_id=request.organization_id,
            audio_data=request.audio_data,
            file_path=request.audio_file_path,
            instruction=request.instruction,
            language=request.language,
            detect_speakers=request.detect_speakers,
            generate_summary=True,
        )

        # 音声処理を実行
        output = await self._audio_processor.process(audio_input)

        if not output.success or not output.audio_result:
            raise Exception(output.error_message or ERROR_MESSAGES["TRANSCRIPTION_FAILED"])

        return output.audio_result

    async def _analyze_meeting(
        self,
        transcript: str,
        segments: list,
        speakers: list,
        request: MeetingMinutesRequest,
    ) -> MeetingAnalysis:
        """
        会議内容を分析

        Args:
            transcript: 文字起こしテキスト
            segments: セグメントリスト
            speakers: 話者リスト
            request: 議事録リクエスト

        Returns:
            会議分析結果
        """
        # 話者情報を整形
        speakers_info = self._format_speakers_info(speakers, segments)

        # 会議タイプを決定
        meeting_type = request.meeting_type
        if meeting_type == MeetingType.UNKNOWN:
            meeting_type = self._detect_meeting_type(transcript, request.instruction)

        # プロンプトを構築
        prompt = MINUTES_ANALYSIS_PROMPT.format(
            meeting_type=meeting_type.value,
            transcript=transcript[:30000],  # 長すぎる場合はトリミング
            speakers=speakers_info,
            instruction=request.instruction or "議事録に必要な情報を抽出してください",
        )

        # LLMで分析
        result = await self._document_generator._call_llm_json(
            prompt=prompt,
            system_prompt="あなたは優秀な議事録作成アシスタントです。会議の内容を正確に分析してください。",
            temperature=0.3,
            quality_level=QualityLevel.STANDARD,
        )

        parsed = result.get("parsed", {})
        if not parsed:
            # パース失敗時は基本情報だけ返す
            return MeetingAnalysis(
                meeting_title=request.meeting_title or "会議",
                meeting_type=meeting_type,
                tokens_used=result.get("total_tokens", 0),
            )

        # 分析結果を構築
        analysis = MeetingAnalysis(
            meeting_title=parsed.get("meeting_title") or request.meeting_title or "会議",
            meeting_date=parsed.get("meeting_date"),
            duration_estimate=parsed.get("duration_estimate"),
            meeting_type=meeting_type,
            attendees=parsed.get("attendees", []) or request.attendees,
            main_topics=parsed.get("main_topics", []),
            next_meeting=parsed.get("next_meeting"),
            notes=parsed.get("notes", ""),
            tokens_used=result.get("total_tokens", 0),
        )

        # 議論トピック
        for disc in parsed.get("key_discussions", []):
            analysis.discussions.append(DiscussionTopic(
                topic=disc.get("topic", ""),
                summary=disc.get("summary", ""),
                speakers=disc.get("speakers", []),
            ))

        # 決定事項
        for decision in parsed.get("decisions", [])[:MAX_DECISIONS]:
            if isinstance(decision, str):
                analysis.decisions.append(Decision(content=decision))
            elif isinstance(decision, dict):
                analysis.decisions.append(Decision(
                    content=decision.get("content", str(decision)),
                    context=decision.get("context"),
                ))

        # アクションアイテム
        for item in parsed.get("action_items", [])[:MAX_ACTION_ITEMS]:
            if isinstance(item, str):
                analysis.action_items.append(ActionItem(task=item))
            elif isinstance(item, dict):
                analysis.action_items.append(ActionItem(
                    task=item.get("task", str(item)),
                    assignee=item.get("assignee"),
                    deadline=item.get("deadline"),
                ))

        return analysis

    async def _generate_minutes(
        self,
        analysis: MeetingAnalysis,
        request: MeetingMinutesRequest,
    ) -> DocumentResult:
        """
        議事録を生成してGoogle Docsに出力

        Args:
            analysis: 会議分析結果
            request: 議事録リクエスト

        Returns:
            文書生成結果
        """
        # セクション構成を決定
        sections = MEETING_TYPE_SECTIONS.get(
            analysis.meeting_type.value,
            DEFAULT_MINUTES_SECTIONS,
        )

        # アウトラインを構築
        section_outlines = [
            SectionOutline(
                section_id=i,
                title=title,
                section_type=SectionType.HEADING1,
                order=i,
            )
            for i, title in enumerate(sections)
        ]

        outline = DocumentOutline(
            title=analysis.meeting_title,
            document_type=DocumentType.MINUTES,
            sections=section_outlines,
        )

        # DocumentRequestを構築
        doc_request = DocumentRequest(
            title=analysis.meeting_title,
            organization_id=request.organization_id,
            document_type=DocumentType.MINUTES,
            purpose="会議議事録の作成",
            instruction=request.instruction,
            context=self._build_minutes_context(analysis),
            quality_level=QualityLevel.STANDARD,
            tone_style=ToneStyle.PROFESSIONAL,
            require_confirmation=False,
            custom_outline=outline,
            target_folder_id=request.target_folder_id,
            share_with=request.share_with,
            user_id=request.user_id,
        )

        # 文書生成を実行
        from lib.capabilities.generation import GenerationInput, GenerationType

        gen_input = GenerationInput(
            generation_type=GenerationType.DOCUMENT,
            organization_id=request.organization_id,
            document_request=doc_request,
        )

        output = await self._document_generator.generate(gen_input)

        if not output.success or not output.document_result:
            raise Exception(output.error_message or ERROR_MESSAGES["GENERATION_FAILED"])

        return output.document_result

    def _format_speakers_info(self, speakers: list, segments: list) -> str:
        """話者情報を整形"""
        if not speakers:
            return "話者情報なし"

        lines = []
        for speaker in speakers:
            name = speaker.name or speaker.label.value if hasattr(speaker, 'label') else f"話者{speaker.speaker_id}"
            speaking_time = getattr(speaker, 'speaking_time_seconds', 0)
            if speaking_time:
                lines.append(f"- {name}: 発言時間 {int(speaking_time)}秒")
            else:
                lines.append(f"- {name}")

        return "\n".join(lines)

    def _detect_meeting_type(self, transcript: str, instruction: str) -> MeetingType:
        """会議タイプを検出"""
        text = f"{transcript} {instruction}".lower()

        for meeting_type, keywords in MEETING_TYPE_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text:
                    return MeetingType(meeting_type)

        return MeetingType.REGULAR  # デフォルトは定例会議

    def _build_minutes_context(self, analysis: MeetingAnalysis) -> str:
        """議事録生成用のコンテキストを構築"""
        parts = []

        # 基本情報
        parts.append(f"【会議タイトル】{analysis.meeting_title}")
        if analysis.meeting_date:
            parts.append(f"【日時】{analysis.meeting_date}")
        if analysis.duration_estimate:
            parts.append(f"【所要時間】{analysis.duration_estimate}")

        # 参加者
        if analysis.attendees:
            parts.append(f"【参加者】{', '.join(analysis.attendees)}")

        # 議題
        if analysis.main_topics:
            parts.append("【議題】")
            for topic in analysis.main_topics:
                parts.append(f"- {topic}")

        # 議論内容
        if analysis.discussions:
            parts.append("【議論内容】")
            for disc in analysis.discussions:
                parts.append(f"■ {disc.topic}")
                parts.append(f"  {disc.summary}")

        # 決定事項
        if analysis.decisions:
            parts.append("【決定事項】")
            for decision in analysis.decisions:
                parts.append(f"- {decision.content}")

        # アクションアイテム
        if analysis.action_items:
            parts.append("【アクションアイテム】")
            for item in analysis.action_items:
                line = f"- {item.task}"
                if item.assignee:
                    line += f"（担当: {item.assignee}）"
                if item.deadline:
                    line += f"【期限: {item.deadline}】"
                parts.append(line)

        # 次回予定
        if analysis.next_meeting:
            parts.append(f"【次回予定】{analysis.next_meeting}")

        return "\n".join(parts)

    def _calculate_cost(self, total_tokens: int) -> float:
        """コストを計算"""
        # 概算: 1000トークン = ¥3（Sonnet）+ Whisper API
        llm_cost = (total_tokens / 1000) * 3.0
        whisper_cost = 1.0  # 音声1分あたり約¥1として固定
        return llm_cost + whisper_cost


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_meeting_minutes_generator(
    pool: "Pool",
    organization_id: UUID,
    api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    google_credentials_path: Optional[str] = None,
    google_credentials_json: Optional[Dict[str, Any]] = None,
) -> MeetingMinutesGenerator:
    """
    MeetingMinutesGeneratorを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        api_key: LLM API Key
        openai_api_key: OpenAI API Key（Whisper用）
        google_credentials_path: Google認証情報パス
        google_credentials_json: Google認証情報（JSON）

    Returns:
        MeetingMinutesGenerator
    """
    return MeetingMinutesGenerator(
        pool=pool,
        organization_id=organization_id,
        api_key=api_key,
        openai_api_key=openai_api_key,
        google_credentials_path=google_credentials_path,
        google_credentials_json=google_credentials_json,
    )
