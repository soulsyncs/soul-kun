# tests/test_video_generator.py
"""
Phase G5: 動画生成のテスト

Author: Claude Opus 4.5
Created: 2026-01-28
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from uuid import uuid4

# テスト対象のインポート
from lib.capabilities.generation import (
    # 定数
    VideoProvider,
    VideoResolution,
    VideoDuration,
    VideoAspectRatio,
    VideoStyle,
    GenerationType,
    GenerationStatus,
    DEFAULT_VIDEO_PROVIDER,
    DEFAULT_VIDEO_RESOLUTION,
    DEFAULT_VIDEO_DURATION,
    DEFAULT_VIDEO_ASPECT_RATIO,
    DEFAULT_VIDEO_STYLE,
    MAX_VIDEO_PROMPT_LENGTH,
    VIDEO_COST_JPY,
    VIDEO_ERROR_MESSAGES,
    RUNWAY_GEN3_MODEL,
    RUNWAY_GEN3_TURBO_MODEL,
    VIDEO_STYLE_PROMPT_MODIFIERS,
    SUPPORTED_RESOLUTIONS_BY_PROVIDER,
    SUPPORTED_DURATIONS_BY_PROVIDER,

    # モデル
    VideoRequest,
    VideoResult,
    VideoOptimizedPrompt,
    GenerationInput,
    GenerationOutput,

    # 例外
    VideoGenerationError,
    VideoPromptEmptyError,
    VideoPromptTooLongError,
    VideoInvalidResolutionError,
    VideoInvalidDurationError,
    RunwayAPIError,
    RunwayRateLimitError,
    RunwayTimeoutError,

    # ジェネレーター
    VideoGenerator,
    create_video_generator,

    # クライアント
    RunwayClient,
    create_runway_client,
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
def video_request(org_id, user_id):
    """テスト用動画リクエスト"""
    return VideoRequest(
        organization_id=org_id,
        prompt="A cat walking in a garden with flowers",
        user_id=user_id,
    )


@pytest.fixture
def video_generator(mock_pool, org_id):
    """テスト用動画ジェネレーター"""
    return VideoGenerator(
        pool=mock_pool,
        organization_id=org_id,
        api_key="test-api-key",
        runway_api_key="test-runway-key",
    )


# =============================================================================
# 定数テスト
# =============================================================================


class TestVideoConstants:
    """動画定数のテスト"""

    def test_video_providers(self):
        """プロバイダーの定義"""
        assert VideoProvider.RUNWAY_GEN3.value == "runway_gen3"
        assert VideoProvider.RUNWAY_GEN3_TURBO.value == "runway_gen3_turbo"
        assert VideoProvider.PIKA.value == "pika"

    def test_video_resolutions(self):
        """解像度の定義"""
        assert VideoResolution.HD_720P.value == "720p"
        assert VideoResolution.FULL_HD_1080P.value == "1080p"

    def test_video_durations(self):
        """動画長さの定義"""
        assert VideoDuration.SHORT_5S.value == "5"
        assert VideoDuration.STANDARD_10S.value == "10"

    def test_video_aspect_ratios(self):
        """アスペクト比の定義"""
        assert VideoAspectRatio.LANDSCAPE_16_9.value == "16:9"
        assert VideoAspectRatio.PORTRAIT_9_16.value == "9:16"
        assert VideoAspectRatio.SQUARE_1_1.value == "1:1"

    def test_video_styles(self):
        """スタイルの定義"""
        assert VideoStyle.REALISTIC.value == "realistic"
        assert VideoStyle.CINEMATIC.value == "cinematic"
        assert VideoStyle.ANIME.value == "anime"
        assert VideoStyle.CREATIVE.value == "creative"

    def test_defaults(self):
        """デフォルト値"""
        assert DEFAULT_VIDEO_PROVIDER == VideoProvider.RUNWAY_GEN3
        assert DEFAULT_VIDEO_RESOLUTION == VideoResolution.FULL_HD_1080P
        assert DEFAULT_VIDEO_DURATION == VideoDuration.STANDARD_10S
        assert DEFAULT_VIDEO_ASPECT_RATIO == VideoAspectRatio.LANDSCAPE_16_9
        assert DEFAULT_VIDEO_STYLE == VideoStyle.REALISTIC

    def test_max_prompt_length(self):
        """プロンプト最大長"""
        assert MAX_VIDEO_PROMPT_LENGTH == 2000

    def test_cost_mapping(self):
        """コストマッピング"""
        key = f"{VideoProvider.RUNWAY_GEN3.value}_{VideoDuration.STANDARD_10S.value}"
        assert key in VIDEO_COST_JPY
        assert VIDEO_COST_JPY[key] == 75.0

        key_5s = f"{VideoProvider.RUNWAY_GEN3.value}_{VideoDuration.SHORT_5S.value}"
        assert VIDEO_COST_JPY[key_5s] == 37.5

    def test_turbo_cost_mapping(self):
        """Turboコストマッピング"""
        key = f"{VideoProvider.RUNWAY_GEN3_TURBO.value}_{VideoDuration.STANDARD_10S.value}"
        assert VIDEO_COST_JPY[key] == 50.0

    def test_error_messages(self):
        """エラーメッセージ"""
        assert "EMPTY_PROMPT" in VIDEO_ERROR_MESSAGES
        assert "PROMPT_TOO_LONG" in VIDEO_ERROR_MESSAGES
        assert "CONTENT_POLICY_VIOLATION" in VIDEO_ERROR_MESSAGES
        assert "RUNWAY_API_ERROR" in VIDEO_ERROR_MESSAGES
        assert "RUNWAY_TIMEOUT" in VIDEO_ERROR_MESSAGES

    def test_model_names(self):
        """モデル名"""
        assert RUNWAY_GEN3_MODEL == "gen3a_turbo"
        assert RUNWAY_GEN3_TURBO_MODEL == "gen3a_turbo"

    def test_style_modifiers(self):
        """スタイル修飾子"""
        assert "photorealistic" in VIDEO_STYLE_PROMPT_MODIFIERS[VideoStyle.REALISTIC.value]
        assert "cinematic" in VIDEO_STYLE_PROMPT_MODIFIERS[VideoStyle.CINEMATIC.value]
        assert "anime" in VIDEO_STYLE_PROMPT_MODIFIERS[VideoStyle.ANIME.value]

    def test_supported_resolutions(self):
        """サポート解像度"""
        assert VideoResolution.HD_720P.value in SUPPORTED_RESOLUTIONS_BY_PROVIDER[VideoProvider.RUNWAY_GEN3.value]
        assert VideoResolution.FULL_HD_1080P.value in SUPPORTED_RESOLUTIONS_BY_PROVIDER[VideoProvider.RUNWAY_GEN3.value]

    def test_supported_durations(self):
        """サポート動画長さ"""
        assert VideoDuration.SHORT_5S.value in SUPPORTED_DURATIONS_BY_PROVIDER[VideoProvider.RUNWAY_GEN3.value]
        assert VideoDuration.STANDARD_10S.value in SUPPORTED_DURATIONS_BY_PROVIDER[VideoProvider.RUNWAY_GEN3.value]


# =============================================================================
# モデルテスト
# =============================================================================


class TestVideoModels:
    """動画モデルのテスト"""

    def test_video_request(self, video_request, org_id):
        """VideoRequest"""
        assert video_request.organization_id == org_id
        assert "cat" in video_request.prompt
        assert video_request.provider == DEFAULT_VIDEO_PROVIDER
        assert video_request.resolution == DEFAULT_VIDEO_RESOLUTION
        assert video_request.duration == DEFAULT_VIDEO_DURATION

    def test_video_request_to_dict(self, video_request):
        """VideoRequestの辞書変換"""
        d = video_request.to_dict()
        assert "prompt" in d
        assert d["provider"] == "runway_gen3"
        assert d["resolution"] == "1080p"
        assert d["duration"] == "10"
        assert d["aspect_ratio"] == "16:9"

    def test_video_request_custom(self, org_id):
        """カスタム設定のVideoRequest"""
        request = VideoRequest(
            organization_id=org_id,
            prompt="test",
            provider=VideoProvider.RUNWAY_GEN3_TURBO,
            resolution=VideoResolution.HD_720P,
            duration=VideoDuration.SHORT_5S,
            aspect_ratio=VideoAspectRatio.PORTRAIT_9_16,
            style=VideoStyle.CINEMATIC,
        )
        assert request.provider == VideoProvider.RUNWAY_GEN3_TURBO
        assert request.resolution == VideoResolution.HD_720P
        assert request.duration == VideoDuration.SHORT_5S
        assert request.aspect_ratio == VideoAspectRatio.PORTRAIT_9_16
        assert request.style == VideoStyle.CINEMATIC

    def test_video_optimized_prompt(self):
        """VideoOptimizedPrompt"""
        opt = VideoOptimizedPrompt(
            original_prompt="猫が庭を歩いている",
            optimized_prompt="A cat walking slowly in a garden",
            japanese_summary="庭を歩く猫の動画",
            warnings=["動きが少ない可能性"],
        )
        assert opt.original_prompt == "猫が庭を歩いている"
        assert opt.optimized_prompt == "A cat walking slowly in a garden"
        assert len(opt.warnings) == 1

    def test_video_result_generating(self):
        """生成中の結果"""
        result = VideoResult(status=GenerationStatus.GENERATING)
        msg = result.to_user_message()
        assert "生成中" in msg

    def test_video_result_completed(self):
        """完了した結果"""
        result = VideoResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            video_url="https://example.com/video.mp4",
            estimated_cost_jpy=75.0,
            resolution=VideoResolution.FULL_HD_1080P,
            duration=VideoDuration.STANDARD_10S,
        )
        msg = result.to_user_message()
        assert "完成" in msg
        assert "example.com" in msg
        assert "¥75" in msg

    def test_video_result_failed(self):
        """失敗した結果"""
        result = VideoResult(
            status=GenerationStatus.FAILED,
            success=False,
            error_message="テストエラー",
        )
        msg = result.to_user_message()
        assert "失敗" in msg
        assert "テストエラー" in msg

    def test_video_result_to_dict(self):
        """VideoResultの辞書変換"""
        result = VideoResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            video_url="https://example.com/video.mp4",
        )
        d = result.to_dict()
        assert d["status"] == "completed"
        assert d["success"] is True
        assert d["video_url"] == "https://example.com/video.mp4"

    def test_video_result_to_brain_context(self):
        """VideoResultの脳コンテキスト"""
        result = VideoResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            prompt_used="A test video",
            resolution=VideoResolution.FULL_HD_1080P,
            duration=VideoDuration.STANDARD_10S,
        )
        ctx = result.to_brain_context()
        assert "動画生成結果" in ctx
        assert "1080p" in ctx
        assert "10秒" in ctx

    def test_video_result_complete_method(self):
        """VideoResultのcompleteメソッド"""
        result = VideoResult()
        result.complete(success=True)
        assert result.success is True
        assert result.status == GenerationStatus.COMPLETED

    def test_video_result_complete_method_failure(self):
        """VideoResultのcompleteメソッド（失敗）"""
        result = VideoResult()
        result.complete(success=False, error_message="エラー")
        assert result.success is False
        assert result.status == GenerationStatus.FAILED
        assert result.error_message == "エラー"


# =============================================================================
# 例外テスト
# =============================================================================


class TestVideoExceptions:
    """動画例外のテスト"""

    def test_video_generation_error(self):
        """VideoGenerationError"""
        error = VideoGenerationError(
            message="Test error",
            error_code="TEST_ERROR",
        )
        assert str(error) == "Test error"
        assert error.error_code == "TEST_ERROR"
        assert error.generation_type == GenerationType.VIDEO

    def test_video_prompt_empty_error(self):
        """VideoPromptEmptyError"""
        error = VideoPromptEmptyError()
        assert "動画" in error.to_user_message()

    def test_video_prompt_too_long_error(self):
        """VideoPromptTooLongError"""
        error = VideoPromptTooLongError(actual_length=3000, max_length=2000)
        assert "3000" in error.to_user_message()
        assert "2000" in error.to_user_message()

    def test_video_invalid_resolution_error(self):
        """VideoInvalidResolutionError"""
        error = VideoInvalidResolutionError(
            resolution="4k",
            provider="runway_gen3",
            supported_resolutions=["720p", "1080p"],
        )
        assert "4k" in error.to_user_message()
        assert "runway_gen3" in error.to_user_message()

    def test_video_invalid_duration_error(self):
        """VideoInvalidDurationError"""
        error = VideoInvalidDurationError(
            duration="30",
            provider="runway_gen3",
            supported_durations=["5", "10"],
        )
        assert "30" in error.to_user_message()

    def test_runway_api_error(self):
        """RunwayAPIError"""
        error = RunwayAPIError(
            message="API Error",
            model="gen3a_turbo",
        )
        assert error.model == "gen3a_turbo"

    def test_runway_rate_limit_error(self):
        """RunwayRateLimitError"""
        error = RunwayRateLimitError(retry_after=60)
        assert "60秒" in error.to_user_message()

    def test_runway_timeout_error(self):
        """RunwayTimeoutError"""
        error = RunwayTimeoutError(timeout_seconds=300)
        assert "タイムアウト" in error.to_user_message()


# =============================================================================
# ジェネレーターテスト
# =============================================================================


class TestVideoGenerator:
    """VideoGeneratorのテスト"""

    def test_init(self, mock_pool, org_id):
        """初期化"""
        generator = VideoGenerator(
            pool=mock_pool,
            organization_id=org_id,
            api_key="test-key",
            runway_api_key="test-runway-key",
        )
        assert generator._organization_id == org_id
        assert generator._runway_client is not None

    def test_validate_request_empty_prompt(self, video_generator, org_id):
        """空のプロンプトでエラー"""
        request = VideoRequest(
            organization_id=org_id,
            prompt="",
        )
        with pytest.raises(VideoPromptEmptyError):
            video_generator._validate_request(request)

    def test_validate_request_whitespace_only_prompt(self, video_generator, org_id):
        """空白のみのプロンプトでエラー"""
        request = VideoRequest(
            organization_id=org_id,
            prompt="   ",
        )
        with pytest.raises(VideoPromptEmptyError):
            video_generator._validate_request(request)

    def test_validate_request_long_prompt(self, video_generator, org_id):
        """長すぎるプロンプトでエラー"""
        request = VideoRequest(
            organization_id=org_id,
            prompt="a" * 3000,
        )
        with pytest.raises(VideoPromptTooLongError):
            video_generator._validate_request(request)

    def test_validate_request_valid(self, video_generator, org_id):
        """正常なリクエストは検証通過"""
        request = VideoRequest(
            organization_id=org_id,
            prompt="A cat walking in a garden",
        )
        # エラーが発生しないことを確認
        video_generator._validate_request(request)

    def test_calculate_cost_gen3_10s(self, video_generator, org_id):
        """Gen-3 10秒のコスト計算"""
        request = VideoRequest(
            organization_id=org_id,
            prompt="test",
            provider=VideoProvider.RUNWAY_GEN3,
            duration=VideoDuration.STANDARD_10S,
        )
        cost = video_generator._calculate_cost(request)
        assert cost == 75.0

    def test_calculate_cost_gen3_5s(self, video_generator, org_id):
        """Gen-3 5秒のコスト計算"""
        request = VideoRequest(
            organization_id=org_id,
            prompt="test",
            provider=VideoProvider.RUNWAY_GEN3,
            duration=VideoDuration.SHORT_5S,
        )
        cost = video_generator._calculate_cost(request)
        assert cost == 37.5

    def test_calculate_cost_turbo(self, video_generator, org_id):
        """Turboコスト計算"""
        request = VideoRequest(
            organization_id=org_id,
            prompt="test",
            provider=VideoProvider.RUNWAY_GEN3_TURBO,
            duration=VideoDuration.STANDARD_10S,
        )
        cost = video_generator._calculate_cost(request)
        assert cost == 50.0

    def test_apply_style_modifier_realistic(self, video_generator):
        """リアルスタイル修飾子適用"""
        prompt = "a cat walking"
        modified = video_generator._apply_style_modifier(prompt, VideoStyle.REALISTIC)
        assert "photorealistic" in modified.lower()

    def test_apply_style_modifier_cinematic(self, video_generator):
        """シネマティックスタイル修飾子適用"""
        prompt = "a car driving"
        modified = video_generator._apply_style_modifier(prompt, VideoStyle.CINEMATIC)
        assert "cinematic" in modified.lower()

    def test_apply_style_modifier_anime(self, video_generator):
        """アニメスタイル修飾子適用"""
        prompt = "a character running"
        modified = video_generator._apply_style_modifier(prompt, VideoStyle.ANIME)
        assert "anime" in modified.lower()

    def test_select_model_gen3(self, video_generator):
        """Gen-3モデル選択"""
        model = video_generator._select_model(VideoProvider.RUNWAY_GEN3)
        assert model == RUNWAY_GEN3_MODEL

    def test_select_model_gen3_turbo(self, video_generator):
        """Gen-3 Turboモデル選択"""
        model = video_generator._select_model(VideoProvider.RUNWAY_GEN3_TURBO)
        assert model == RUNWAY_GEN3_TURBO_MODEL

    @pytest.mark.asyncio
    async def test_generate_success(self, video_generator, org_id, user_id):
        """正常な動画生成"""
        request = VideoRequest(
            organization_id=org_id,
            prompt="A beautiful sunset over the ocean",
            user_id=user_id,
        )

        input_data = GenerationInput(
            generation_type=GenerationType.VIDEO,
            organization_id=org_id,
            video_request=request,
        )

        # RunwayClientをモック
        with patch.object(
            video_generator._runway_client,
            "generate",
            new_callable=AsyncMock,
            return_value={
                "task_id": "test-task-id",
            },
        ):
            with patch.object(
                video_generator._runway_client,
                "wait_for_completion",
                new_callable=AsyncMock,
                return_value={
                    "status": "completed",
                    "output_url": "https://example.com/video.mp4",
                },
            ):
                # プロンプト最適化をスキップ
                with patch.object(
                    video_generator,
                    "_optimize_prompt",
                    new_callable=AsyncMock,
                    return_value=VideoOptimizedPrompt(
                        original_prompt="A beautiful sunset over the ocean",
                        optimized_prompt="A beautiful sunset over the ocean, cinematic",
                    ),
                ):
                    result = await video_generator.generate(input_data)

        assert result.success
        assert result.status == GenerationStatus.COMPLETED
        assert result.video_result is not None
        assert result.video_result.video_url == "https://example.com/video.mp4"

    @pytest.mark.asyncio
    async def test_generate_missing_request(self, video_generator, org_id):
        """video_requestがないとエラー"""
        input_data = GenerationInput(
            generation_type=GenerationType.VIDEO,
            organization_id=org_id,
        )

        with pytest.raises(VideoGenerationError) as exc_info:
            await video_generator.generate(input_data)

        assert "video_request is required" in str(exc_info.value)


# =============================================================================
# クライアントテスト
# =============================================================================


class TestRunwayClient:
    """RunwayClientのテスト"""

    def test_init(self):
        """初期化"""
        client = RunwayClient(api_key="test-key")
        assert client._api_key == "test-key"

    def test_init_without_key(self):
        """APIキーなしの初期化"""
        client = RunwayClient()
        assert client._api_key is None

    def test_create_runway_client(self):
        """ファクトリ関数"""
        client = create_runway_client(api_key="test-key")
        assert isinstance(client, RunwayClient)


# =============================================================================
# ファクトリ関数テスト
# =============================================================================


class TestVideoFactoryFunctions:
    """ファクトリ関数のテスト"""

    def test_create_video_generator(self, mock_pool, org_id):
        """VideoGenerator作成"""
        generator = create_video_generator(
            pool=mock_pool,
            organization_id=org_id,
        )
        assert isinstance(generator, VideoGenerator)
        assert generator._organization_id == org_id


# =============================================================================
# 統合モデルテスト
# =============================================================================


class TestVideoIntegrationModels:
    """統合モデルのテスト"""

    def test_generation_input_with_video(self, org_id, user_id):
        """動画リクエストを含むGenerationInput"""
        request = VideoRequest(
            organization_id=org_id,
            prompt="test video",
            user_id=user_id,
        )
        input_data = GenerationInput(
            generation_type=GenerationType.VIDEO,
            organization_id=org_id,
            video_request=request,
        )
        assert input_data.get_request() == request

    def test_generation_output_with_video(self):
        """動画結果を含むGenerationOutput"""
        result = VideoResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            video_url="https://example.com/video.mp4",
        )
        output = GenerationOutput(
            generation_type=GenerationType.VIDEO,
            success=True,
            status=GenerationStatus.COMPLETED,
            video_result=result,
        )
        assert output.get_result() == result
        assert "完成" in output.to_user_message()

    def test_generation_output_to_dict_with_video(self):
        """GenerationOutputの辞書変換（動画）"""
        result = VideoResult(
            status=GenerationStatus.COMPLETED,
            success=True,
        )
        output = GenerationOutput(
            generation_type=GenerationType.VIDEO,
            success=True,
            video_result=result,
        )
        d = output.to_dict()
        assert d["generation_type"] == "video"
        assert "video_result" in d


# =============================================================================
# パッケージインポートテスト
# =============================================================================


class TestVideoPackageImports:
    """パッケージインポートのテスト"""

    def test_import_video_types(self):
        """動画タイプのインポート"""
        from lib.capabilities.generation import (
            VideoProvider,
            VideoResolution,
            VideoDuration,
            VideoAspectRatio,
            VideoStyle,
        )
        assert VideoProvider.RUNWAY_GEN3.value == "runway_gen3"
        assert VideoResolution.FULL_HD_1080P.value == "1080p"
        assert VideoDuration.STANDARD_10S.value == "10"
        assert VideoAspectRatio.LANDSCAPE_16_9.value == "16:9"
        assert VideoStyle.REALISTIC.value == "realistic"

    def test_import_video_models(self):
        """動画モデルのインポート"""
        from lib.capabilities.generation import (
            VideoRequest,
            VideoResult,
            VideoOptimizedPrompt,
        )
        assert VideoRequest is not None
        assert VideoResult is not None
        assert VideoOptimizedPrompt is not None

    def test_import_video_exceptions(self):
        """動画例外のインポート"""
        from lib.capabilities.generation import (
            VideoGenerationError,
            VideoPromptEmptyError,
            VideoPromptTooLongError,
            VideoInvalidResolutionError,
            VideoInvalidDurationError,
            RunwayAPIError,
            RunwayRateLimitError,
            RunwayTimeoutError,
        )
        assert VideoGenerationError is not None
        assert VideoPromptEmptyError is not None
        assert RunwayAPIError is not None

    def test_import_video_generator(self):
        """動画ジェネレーターのインポート"""
        from lib.capabilities.generation import (
            VideoGenerator,
            create_video_generator,
            RunwayClient,
            create_runway_client,
        )
        assert VideoGenerator is not None
        assert create_video_generator is not None
        assert RunwayClient is not None
        assert create_runway_client is not None

    def test_import_video_constants(self):
        """動画定数のインポート"""
        from lib.capabilities.generation import (
            DEFAULT_VIDEO_PROVIDER,
            DEFAULT_VIDEO_RESOLUTION,
            DEFAULT_VIDEO_DURATION,
            DEFAULT_VIDEO_ASPECT_RATIO,
            DEFAULT_VIDEO_STYLE,
            MAX_VIDEO_PROMPT_LENGTH,
            VIDEO_COST_JPY,
            VIDEO_ERROR_MESSAGES,
            RUNWAY_GEN3_MODEL,
            VIDEO_STYLE_PROMPT_MODIFIERS,
        )
        assert DEFAULT_VIDEO_PROVIDER is not None
        assert MAX_VIDEO_PROMPT_LENGTH == 2000
        assert VIDEO_COST_JPY is not None
        assert VIDEO_ERROR_MESSAGES is not None
