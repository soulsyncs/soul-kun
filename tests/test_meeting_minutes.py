# tests/test_meeting_minutes.py
"""
App1: 議事録自動生成のテスト

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from uuid import uuid4, UUID
from datetime import datetime

# テスト対象のインポート
from lib.capabilities.apps.meeting_minutes.constants import (
    MeetingType,
    MinutesStatus,
    MinutesSection,
    DEFAULT_MINUTES_SECTIONS,
    MEETING_TYPE_SECTIONS,
    MEETING_TYPE_KEYWORDS,
    MAX_ACTION_ITEMS,
    MAX_DECISIONS,
    FEATURE_FLAG_MEETING_MINUTES,
    ERROR_MESSAGES,
)
from lib.capabilities.apps.meeting_minutes.models import (
    MeetingMinutesRequest,
    MeetingMinutesResult,
    MeetingAnalysis,
    ActionItem,
    Decision,
    DiscussionTopic,
)
from lib.capabilities.apps.meeting_minutes.meeting_minutes_generator import (
    MeetingMinutesGenerator,
    create_meeting_minutes_generator,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def org_id():
    """テスト用組織ID"""
    return uuid4()


@pytest.fixture
def user_id():
    """テスト用ユーザーID"""
    return uuid4()


@pytest.fixture
def mock_pool():
    """モックDBプール"""
    pool = Mock()
    pool.acquire = AsyncMock()
    return pool


@pytest.fixture
def sample_audio_data():
    """テスト用音声データ"""
    return b"RIFF" + b"\x00" * 100  # 最小限のWAVヘッダー


@pytest.fixture
def meeting_request(org_id, user_id, sample_audio_data):
    """テスト用議事録リクエスト"""
    return MeetingMinutesRequest(
        organization_id=org_id,
        audio_data=sample_audio_data,
        meeting_title="週次定例会議",
        meeting_type=MeetingType.REGULAR,
        user_id=user_id,
    )


@pytest.fixture
def sample_analysis():
    """テスト用会議分析結果"""
    return MeetingAnalysis(
        meeting_title="週次定例会議",
        meeting_date="2026-01-27 10:00",
        duration_estimate="60分",
        meeting_type=MeetingType.REGULAR,
        attendees=["田中", "山田", "佐藤"],
        main_topics=["進捗確認", "課題共有", "次週の予定"],
        discussions=[
            DiscussionTopic(
                topic="進捗確認",
                summary="各チームの進捗を確認した",
                speakers=["田中", "山田"],
            ),
        ],
        decisions=[
            Decision(content="次週までにドキュメントを完成させる"),
        ],
        action_items=[
            ActionItem(task="ドキュメント作成", assignee="山田", deadline="1/31"),
        ],
        next_meeting="2026-02-03 10:00",
    )


@pytest.fixture
def meeting_generator(mock_pool, org_id):
    """テスト用議事録ジェネレーター"""
    return MeetingMinutesGenerator(
        pool=mock_pool,
        organization_id=org_id,
        api_key="test-api-key",
        openai_api_key="test-openai-key",
    )


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_meeting_types(self):
        """会議タイプの定義"""
        assert MeetingType.REGULAR.value == "regular"
        assert MeetingType.PROJECT.value == "project"
        assert MeetingType.BRAINSTORM.value == "brainstorm"
        assert MeetingType.ONE_ON_ONE.value == "one_on_one"
        assert MeetingType.CLIENT.value == "client"

    def test_minutes_status(self):
        """議事録ステータスの定義"""
        assert MinutesStatus.PROCESSING.value == "processing"
        assert MinutesStatus.TRANSCRIBING.value == "transcribing"
        assert MinutesStatus.ANALYZING.value == "analyzing"
        assert MinutesStatus.GENERATING.value == "generating"
        assert MinutesStatus.COMPLETED.value == "completed"
        assert MinutesStatus.FAILED.value == "failed"

    def test_minutes_section(self):
        """議事録セクションの定義"""
        assert MinutesSection.OVERVIEW.value == "overview"
        assert MinutesSection.ATTENDEES.value == "attendees"
        assert MinutesSection.DECISIONS.value == "decisions"
        assert MinutesSection.ACTION_ITEMS.value == "action_items"

    def test_default_sections(self):
        """デフォルトセクション"""
        assert "会議概要" in DEFAULT_MINUTES_SECTIONS
        assert "決定事項" in DEFAULT_MINUTES_SECTIONS
        assert "アクションアイテム" in DEFAULT_MINUTES_SECTIONS

    def test_meeting_type_sections(self):
        """会議タイプ別セクション"""
        assert "regular" in MEETING_TYPE_SECTIONS
        assert "project" in MEETING_TYPE_SECTIONS
        assert "brainstorm" in MEETING_TYPE_SECTIONS

    def test_meeting_type_keywords(self):
        """会議タイプキーワード"""
        assert "定例" in MEETING_TYPE_KEYWORDS["regular"]
        assert "プロジェクト" in MEETING_TYPE_KEYWORDS["project"]
        assert "ブレスト" in MEETING_TYPE_KEYWORDS["brainstorm"]

    def test_feature_flag(self):
        """Feature Flag"""
        assert FEATURE_FLAG_MEETING_MINUTES == "USE_MEETING_MINUTES_APP"

    def test_error_messages(self):
        """エラーメッセージ"""
        assert "NO_AUDIO" in ERROR_MESSAGES
        assert "TRANSCRIPTION_FAILED" in ERROR_MESSAGES
        assert "NO_SPEECH" in ERROR_MESSAGES


# =============================================================================
# モデルテスト
# =============================================================================


class TestModels:
    """モデルのテスト"""

    def test_action_item(self):
        """アクションアイテム"""
        item = ActionItem(
            task="ドキュメント作成",
            assignee="山田",
            deadline="1/31",
        )
        assert item.task == "ドキュメント作成"
        assert item.assignee == "山田"
        assert item.deadline == "1/31"

    def test_action_item_to_markdown(self):
        """アクションアイテムのMarkdown変換"""
        item = ActionItem(
            task="ドキュメント作成",
            assignee="山田",
            deadline="1/31",
        )
        md = item.to_markdown()
        assert "ドキュメント作成" in md
        assert "山田" in md
        assert "1/31" in md

    def test_decision(self):
        """決定事項"""
        decision = Decision(
            content="次週までに完成させる",
            context="スケジュールの都合",
        )
        assert decision.content == "次週までに完成させる"

    def test_decision_to_markdown(self):
        """決定事項のMarkdown変換"""
        decision = Decision(content="次週までに完成させる")
        md = decision.to_markdown()
        assert "✅" in md
        assert "次週まで" in md

    def test_discussion_topic(self):
        """議論トピック"""
        topic = DiscussionTopic(
            topic="進捗確認",
            summary="各チームの進捗を確認した",
            speakers=["田中", "山田"],
        )
        assert topic.topic == "進捗確認"
        assert len(topic.speakers) == 2

    def test_meeting_analysis(self, sample_analysis):
        """会議分析結果"""
        assert sample_analysis.meeting_title == "週次定例会議"
        assert len(sample_analysis.attendees) == 3
        assert len(sample_analysis.decisions) == 1
        assert len(sample_analysis.action_items) == 1

    def test_meeting_analysis_to_dict(self, sample_analysis):
        """会議分析結果の辞書変換"""
        d = sample_analysis.to_dict()
        assert d["meeting_title"] == "週次定例会議"
        assert d["meeting_type"] == "regular"
        assert len(d["attendees"]) == 3

    def test_meeting_request(self, meeting_request, org_id):
        """議事録リクエスト"""
        assert meeting_request.organization_id == org_id
        assert meeting_request.meeting_title == "週次定例会議"
        assert meeting_request.meeting_type == MeetingType.REGULAR

    def test_meeting_request_to_dict(self, meeting_request):
        """リクエストの辞書変換"""
        d = meeting_request.to_dict()
        assert d["meeting_title"] == "週次定例会議"
        assert d["meeting_type"] == "regular"
        assert d["has_audio_data"] is True

    def test_meeting_result_processing(self):
        """処理中の結果"""
        result = MeetingMinutesResult(
            status=MinutesStatus.PROCESSING,
        )
        msg = result.to_user_message()
        assert "作成中" in msg

    def test_meeting_result_transcribing(self):
        """文字起こし中の結果"""
        result = MeetingMinutesResult(
            status=MinutesStatus.TRANSCRIBING,
        )
        msg = result.to_user_message()
        assert "文字起こし" in msg

    def test_meeting_result_pending(self, sample_analysis):
        """確認待ちの結果"""
        result = MeetingMinutesResult(
            status=MinutesStatus.PENDING,
            analysis=sample_analysis,
        )
        msg = result.to_user_message()
        assert "分析" in msg
        assert "参加者" in msg
        assert "3名" in msg

    def test_meeting_result_completed(self, sample_analysis):
        """完了した結果"""
        result = MeetingMinutesResult(
            status=MinutesStatus.COMPLETED,
            success=True,
            analysis=sample_analysis,
            document_url="https://docs.google.com/document/d/test",
            audio_duration_seconds=3600,
            speakers_detected=3,
            minutes_word_count=2000,
            estimated_cost_jpy=50,
        )
        msg = result.to_user_message()
        assert "完成" in msg
        assert "docs.google.com" in msg
        assert "1時間" in msg
        assert "3名" in msg

    def test_meeting_result_failed(self):
        """失敗した結果"""
        result = MeetingMinutesResult(
            status=MinutesStatus.FAILED,
            success=False,
            error_message="音声が検出されませんでした",
        )
        msg = result.to_user_message()
        assert "失敗" in msg
        assert "音声が検出" in msg

    def test_meeting_result_to_brain_context(self, sample_analysis):
        """脳コンテキスト用文字列"""
        result = MeetingMinutesResult(
            status=MinutesStatus.COMPLETED,
            analysis=sample_analysis,
            document_url="https://docs.google.com/document/d/test",
        )
        ctx = result.to_brain_context()
        assert "週次定例" in ctx
        assert "田中" in ctx

    def test_meeting_result_complete(self):
        """結果の完了処理"""
        result = MeetingMinutesResult()
        result.complete(success=True)
        assert result.status == MinutesStatus.COMPLETED
        assert result.completed_at is not None
        assert result.processing_time_ms is not None


# =============================================================================
# ジェネレーターテスト
# =============================================================================


class TestMeetingMinutesGenerator:
    """MeetingMinutesGeneratorのテスト"""

    def test_init(self, mock_pool, org_id):
        """初期化"""
        generator = MeetingMinutesGenerator(
            pool=mock_pool,
            organization_id=org_id,
            api_key="test-key",
            openai_api_key="test-openai-key",
        )
        assert generator._organization_id == org_id
        assert generator._audio_processor is not None
        assert generator._document_generator is not None

    def test_detect_meeting_type_regular(self, meeting_generator):
        """定例会議タイプの検出"""
        meeting_type = meeting_generator._detect_meeting_type(
            "本日の定例ミーティングを始めます",
            "",
        )
        assert meeting_type == MeetingType.REGULAR

    def test_detect_meeting_type_project(self, meeting_generator):
        """プロジェクト会議タイプの検出"""
        meeting_type = meeting_generator._detect_meeting_type(
            "プロジェクトAの進捗について確認します",
            "",
        )
        assert meeting_type == MeetingType.PROJECT

    def test_detect_meeting_type_brainstorm(self, meeting_generator):
        """ブレスト会議タイプの検出"""
        meeting_type = meeting_generator._detect_meeting_type(
            "今日はブレストを行います",
            "",
        )
        assert meeting_type == MeetingType.BRAINSTORM

    def test_detect_meeting_type_one_on_one(self, meeting_generator):
        """1on1タイプの検出"""
        meeting_type = meeting_generator._detect_meeting_type(
            "1on1面談を始めます",
            "",
        )
        assert meeting_type == MeetingType.ONE_ON_ONE

    def test_detect_meeting_type_from_instruction(self, meeting_generator):
        """指示からの会議タイプ検出"""
        meeting_type = meeting_generator._detect_meeting_type(
            "会議の内容です",
            "クライアントとの商談議事録を作成してください",
        )
        assert meeting_type == MeetingType.CLIENT

    def test_build_minutes_context(self, meeting_generator, sample_analysis):
        """議事録コンテキストの構築"""
        context = meeting_generator._build_minutes_context(sample_analysis)
        assert "週次定例会議" in context
        assert "田中" in context
        assert "進捗確認" in context
        assert "ドキュメント作成" in context

    def test_format_speakers_info_empty(self, meeting_generator):
        """話者情報なしの整形"""
        info = meeting_generator._format_speakers_info([], [])
        assert "話者情報なし" in info

    def test_calculate_cost(self, meeting_generator):
        """コスト計算"""
        cost = meeting_generator._calculate_cost(1000)
        assert cost > 0

    @pytest.mark.asyncio
    async def test_generate_success(self, meeting_generator, meeting_request):
        """正常な議事録生成"""
        # AudioProcessorモック
        mock_audio_result = Mock()
        mock_audio_result.full_transcript = "本日の定例会議を始めます。田中です。山田です。進捗を確認しましょう。"
        mock_audio_result.segments = []
        mock_audio_result.speakers = []
        mock_audio_result.speaker_count = 2
        mock_audio_result.audio_metadata = Mock(duration_seconds=3600)

        mock_audio_output = Mock()
        mock_audio_output.success = True
        mock_audio_output.audio_result = mock_audio_result

        # DocumentGeneratorモック
        mock_doc_result = Mock()
        mock_doc_result.full_content = "# 議事録\n\n内容"
        mock_doc_result.total_word_count = 500
        mock_doc_result.document_id = "doc123"
        mock_doc_result.document_url = "https://docs.google.com/document/d/doc123"
        mock_doc_result.metadata = Mock(total_tokens_used=1000)

        mock_doc_output = Mock()
        mock_doc_output.success = True
        mock_doc_output.document_result = mock_doc_result

        with patch.object(
            meeting_generator._audio_processor,
            "process",
            new_callable=AsyncMock,
            return_value=mock_audio_output,
        ):
            with patch.object(
                meeting_generator._document_generator,
                "_call_llm_json",
                new_callable=AsyncMock,
                return_value={
                    "parsed": {
                        "meeting_title": "定例会議",
                        "attendees": ["田中", "山田"],
                        "decisions": ["次週確認"],
                        "action_items": [{"task": "確認", "assignee": "田中"}],
                    },
                    "total_tokens": 500,
                },
            ):
                with patch.object(
                    meeting_generator._document_generator,
                    "generate",
                    new_callable=AsyncMock,
                    return_value=mock_doc_output,
                ):
                    result = await meeting_generator.generate(meeting_request)

        assert result.success
        assert result.status == MinutesStatus.COMPLETED
        assert result.document_url == "https://docs.google.com/document/d/doc123"

    @pytest.mark.asyncio
    async def test_generate_with_confirmation(self, meeting_generator, meeting_request):
        """確認付き議事録生成"""
        meeting_request.require_confirmation = True

        # AudioProcessorモック
        mock_audio_result = Mock()
        mock_audio_result.full_transcript = "会議内容"
        mock_audio_result.segments = []
        mock_audio_result.speakers = []
        mock_audio_result.speaker_count = 2
        mock_audio_result.audio_metadata = Mock(duration_seconds=600)

        mock_audio_output = Mock()
        mock_audio_output.success = True
        mock_audio_output.audio_result = mock_audio_result

        with patch.object(
            meeting_generator._audio_processor,
            "process",
            new_callable=AsyncMock,
            return_value=mock_audio_output,
        ):
            with patch.object(
                meeting_generator._document_generator,
                "_call_llm_json",
                new_callable=AsyncMock,
                return_value={
                    "parsed": {
                        "meeting_title": "会議",
                        "attendees": ["田中"],
                        "decisions": [],
                        "action_items": [],
                    },
                    "total_tokens": 100,
                },
            ):
                result = await meeting_generator.generate(meeting_request)

        assert result.status == MinutesStatus.PENDING
        assert result.analysis is not None

    @pytest.mark.asyncio
    async def test_generate_from_analysis(
        self, meeting_generator, sample_analysis, meeting_request
    ):
        """分析結果からの議事録生成"""
        # DocumentGeneratorモック
        mock_doc_result = Mock()
        mock_doc_result.full_content = "# 議事録"
        mock_doc_result.total_word_count = 500
        mock_doc_result.document_id = "doc456"
        mock_doc_result.document_url = "https://docs.google.com/document/d/doc456"
        mock_doc_result.metadata = Mock(total_tokens_used=500)

        mock_doc_output = Mock()
        mock_doc_output.success = True
        mock_doc_output.document_result = mock_doc_result

        with patch.object(
            meeting_generator._document_generator,
            "generate",
            new_callable=AsyncMock,
            return_value=mock_doc_output,
        ):
            result = await meeting_generator.generate_from_analysis(
                analysis=sample_analysis,
                request=meeting_request,
            )

        assert result.success
        assert result.status == MinutesStatus.COMPLETED


# =============================================================================
# ファクトリ関数テスト
# =============================================================================


class TestFactoryFunctions:
    """ファクトリ関数のテスト"""

    def test_create_meeting_minutes_generator(self, mock_pool, org_id):
        """MeetingMinutesGenerator作成"""
        generator = create_meeting_minutes_generator(
            pool=mock_pool,
            organization_id=org_id,
        )
        assert isinstance(generator, MeetingMinutesGenerator)
        assert generator._organization_id == org_id


# =============================================================================
# パッケージインポートテスト
# =============================================================================


class TestPackageImports:
    """パッケージインポートのテスト"""

    def test_import_meeting_types(self):
        """会議タイプのインポート"""
        from lib.capabilities.apps.meeting_minutes import (
            MeetingType,
            MinutesStatus,
            MinutesSection,
        )
        assert MeetingType.REGULAR.value == "regular"
        assert MinutesStatus.COMPLETED.value == "completed"

    def test_import_constants(self):
        """定数のインポート"""
        from lib.capabilities.apps.meeting_minutes import (
            DEFAULT_MINUTES_SECTIONS,
            FEATURE_FLAG_MEETING_MINUTES,
        )
        assert len(DEFAULT_MINUTES_SECTIONS) > 0
        assert FEATURE_FLAG_MEETING_MINUTES == "USE_MEETING_MINUTES_APP"

    def test_import_models(self):
        """モデルのインポート"""
        from lib.capabilities.apps.meeting_minutes import (
            MeetingMinutesRequest,
            MeetingMinutesResult,
            MeetingAnalysis,
            ActionItem,
            Decision,
        )
        assert MeetingMinutesRequest is not None
        assert MeetingMinutesResult is not None

    def test_import_generator(self):
        """ジェネレーターのインポート"""
        from lib.capabilities.apps.meeting_minutes import (
            MeetingMinutesGenerator,
            create_meeting_minutes_generator,
        )
        assert MeetingMinutesGenerator is not None
        assert create_meeting_minutes_generator is not None


# =============================================================================
# 統合テスト
# =============================================================================


class TestIntegration:
    """統合テスト"""

    @pytest.mark.asyncio
    async def test_full_workflow(self, mock_pool, org_id, user_id, sample_audio_data):
        """全体ワークフロー"""
        # リクエスト作成
        request = MeetingMinutesRequest(
            organization_id=org_id,
            audio_data=sample_audio_data,
            meeting_title="テスト会議",
            meeting_type=MeetingType.REGULAR,
            user_id=user_id,
            require_confirmation=True,
        )

        # ジェネレーター作成
        generator = create_meeting_minutes_generator(
            pool=mock_pool,
            organization_id=org_id,
            api_key="test-key",
            openai_api_key="test-openai-key",
        )

        # モック
        mock_audio_result = Mock()
        mock_audio_result.full_transcript = "テスト会議の内容です。"
        mock_audio_result.segments = []
        mock_audio_result.speakers = []
        mock_audio_result.speaker_count = 1
        mock_audio_result.audio_metadata = Mock(duration_seconds=300)

        mock_audio_output = Mock()
        mock_audio_output.success = True
        mock_audio_output.audio_result = mock_audio_result

        with patch.object(
            generator._audio_processor,
            "process",
            new_callable=AsyncMock,
            return_value=mock_audio_output,
        ):
            with patch.object(
                generator._document_generator,
                "_call_llm_json",
                new_callable=AsyncMock,
                return_value={
                    "parsed": {
                        "meeting_title": "テスト会議",
                        "attendees": ["参加者A"],
                        "main_topics": ["テスト"],
                        "decisions": [],
                        "action_items": [],
                    },
                    "total_tokens": 100,
                },
            ):
                result = await generator.generate(request)

        # 確認待ち状態
        assert result.status == MinutesStatus.PENDING
        assert result.analysis is not None
        assert result.analysis.meeting_title == "テスト会議"

        # ユーザー表示
        msg = result.to_user_message()
        assert "分析" in msg
        assert "テスト会議" in msg
