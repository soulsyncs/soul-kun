# tests/test_image_generator.py
"""
Phase G2: 画像生成のテスト

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from uuid import uuid4

# テスト対象のインポート
from lib.capabilities.generation import (
    # 定数
    ImageProvider,
    ImageSize,
    ImageQuality,
    ImageStyle,
    GenerationType,
    GenerationStatus,
    DEFAULT_IMAGE_PROVIDER,
    DEFAULT_IMAGE_SIZE,
    DEFAULT_IMAGE_QUALITY,
    DEFAULT_IMAGE_STYLE,
    MAX_PROMPT_LENGTH,
    IMAGE_COST_JPY,
    IMAGE_ERROR_MESSAGES,

    # モデル
    ImageRequest,
    ImageResult,
    OptimizedPrompt,
    GenerationInput,
    GenerationOutput,

    # 例外
    ImageGenerationError,
    ImagePromptEmptyError,
    ImagePromptTooLongError,
    ImageInvalidSizeError,
    ImageInvalidQualityError,
    ContentPolicyViolationError,
    DALLEAPIError,
    DALLERateLimitError,
    DALLETimeoutError,

    # ジェネレーター
    ImageGenerator,
    create_image_generator,

    # クライアント
    DALLEClient,
    create_dalle_client,
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
def image_request(org_id, user_id):
    """テスト用画像リクエスト"""
    return ImageRequest(
        organization_id=org_id,
        prompt="A futuristic office with AI assistants helping humans",
        user_id=user_id,
    )


@pytest.fixture
def image_generator(mock_pool, org_id):
    """テスト用画像ジェネレーター"""
    return ImageGenerator(
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

    def test_image_providers(self):
        """プロバイダーの定義"""
        assert ImageProvider.DALLE3.value == "dalle3"
        assert ImageProvider.DALLE2.value == "dalle2"
        assert ImageProvider.STABILITY.value == "stability"

    def test_image_sizes(self):
        """サイズの定義"""
        assert ImageSize.SQUARE_1024.value == "1024x1024"
        assert ImageSize.LANDSCAPE_1792.value == "1792x1024"
        assert ImageSize.PORTRAIT_1024.value == "1024x1792"

    def test_image_quality(self):
        """品質の定義"""
        assert ImageQuality.STANDARD.value == "standard"
        assert ImageQuality.HD.value == "hd"

    def test_image_style(self):
        """スタイルの定義"""
        assert ImageStyle.VIVID.value == "vivid"
        assert ImageStyle.NATURAL.value == "natural"
        assert ImageStyle.ANIME.value == "anime"
        assert ImageStyle.PHOTOREALISTIC.value == "photorealistic"

    def test_defaults(self):
        """デフォルト値"""
        assert DEFAULT_IMAGE_PROVIDER == ImageProvider.DALLE3
        assert DEFAULT_IMAGE_SIZE == ImageSize.SQUARE_1024
        assert DEFAULT_IMAGE_QUALITY == ImageQuality.STANDARD
        assert DEFAULT_IMAGE_STYLE == ImageStyle.VIVID

    def test_max_prompt_length(self):
        """プロンプト最大長"""
        assert MAX_PROMPT_LENGTH == 4000

    def test_cost_mapping(self):
        """コストマッピング"""
        key = f"{ImageProvider.DALLE3.value}_{ImageQuality.STANDARD.value}_{ImageSize.SQUARE_1024.value}"
        assert key in IMAGE_COST_JPY
        assert IMAGE_COST_JPY[key] == 6.0

    def test_error_messages(self):
        """エラーメッセージ"""
        assert "EMPTY_PROMPT" in IMAGE_ERROR_MESSAGES
        assert "PROMPT_TOO_LONG" in IMAGE_ERROR_MESSAGES
        assert "CONTENT_POLICY_VIOLATION" in IMAGE_ERROR_MESSAGES
        assert "DALLE_API_ERROR" in IMAGE_ERROR_MESSAGES


# =============================================================================
# モデルテスト
# =============================================================================


class TestModels:
    """モデルのテスト"""

    def test_image_request(self, image_request, org_id):
        """ImageRequest"""
        assert image_request.organization_id == org_id
        assert "futuristic" in image_request.prompt
        assert image_request.provider == DEFAULT_IMAGE_PROVIDER
        assert image_request.size == DEFAULT_IMAGE_SIZE
        assert image_request.quality == DEFAULT_IMAGE_QUALITY

    def test_image_request_to_dict(self, image_request):
        """ImageRequestの辞書変換"""
        d = image_request.to_dict()
        assert "prompt" in d
        assert d["provider"] == "dalle3"
        assert d["size"] == "1024x1024"

    def test_image_request_custom(self, org_id):
        """カスタム設定のImageRequest"""
        request = ImageRequest(
            organization_id=org_id,
            prompt="test",
            provider=ImageProvider.DALLE2,
            size=ImageSize.SQUARE_512,
            quality=ImageQuality.STANDARD,
            style=ImageStyle.NATURAL,
        )
        assert request.provider == ImageProvider.DALLE2
        assert request.size == ImageSize.SQUARE_512

    def test_optimized_prompt(self):
        """OptimizedPrompt"""
        opt = OptimizedPrompt(
            original_prompt="未来的なオフィス",
            optimized_prompt="A futuristic office",
            japanese_summary="未来的なオフィスの画像",
            warnings=["注意点"],
        )
        assert opt.original_prompt == "未来的なオフィス"
        assert opt.optimized_prompt == "A futuristic office"
        assert len(opt.warnings) == 1

    def test_image_result_generating(self):
        """生成中の結果"""
        result = ImageResult(status=GenerationStatus.GENERATING)
        msg = result.to_user_message()
        assert "生成中" in msg

    def test_image_result_completed(self):
        """完了した結果"""
        result = ImageResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            image_url="https://example.com/image.png",
            estimated_cost_jpy=6.0,
            size=ImageSize.SQUARE_1024,
        )
        msg = result.to_user_message()
        assert "完成" in msg
        assert "example.com" in msg
        assert "¥6" in msg

    def test_image_result_failed(self):
        """失敗した結果"""
        result = ImageResult(
            status=GenerationStatus.FAILED,
            success=False,
            error_message="テストエラー",
        )
        msg = result.to_user_message()
        assert "失敗" in msg
        assert "テストエラー" in msg

    def test_image_result_to_dict(self):
        """ImageResultの辞書変換"""
        result = ImageResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            image_url="https://example.com/image.png",
        )
        d = result.to_dict()
        assert d["status"] == "completed"
        assert d["success"] is True
        assert d["image_url"] == "https://example.com/image.png"

    def test_image_result_to_brain_context(self):
        """ImageResultの脳コンテキスト"""
        result = ImageResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            prompt_used="A test image",
            size=ImageSize.SQUARE_1024,
        )
        ctx = result.to_brain_context()
        assert "画像生成結果" in ctx
        assert "1024x1024" in ctx

    def test_image_result_complete_method(self):
        """ImageResultのcompleteメソッド"""
        result = ImageResult()
        result.complete(success=True)
        assert result.success is True
        assert result.status == GenerationStatus.COMPLETED

    def test_image_result_complete_method_failure(self):
        """ImageResultのcompleteメソッド（失敗）"""
        result = ImageResult()
        result.complete(success=False, error_message="エラー")
        assert result.success is False
        assert result.status == GenerationStatus.FAILED
        assert result.error_message == "エラー"


# =============================================================================
# 例外テスト
# =============================================================================


class TestExceptions:
    """例外のテスト"""

    def test_image_generation_error(self):
        """ImageGenerationError"""
        error = ImageGenerationError(
            message="Test error",
            error_code="TEST_ERROR",
        )
        assert str(error) == "Test error"
        assert error.error_code == "TEST_ERROR"
        assert error.generation_type == GenerationType.IMAGE

    def test_image_prompt_empty_error(self):
        """ImagePromptEmptyError"""
        error = ImagePromptEmptyError()
        assert "どんな画像" in error.to_user_message()

    def test_image_prompt_too_long_error(self):
        """ImagePromptTooLongError"""
        error = ImagePromptTooLongError(actual_length=5000, max_length=4000)
        assert "5000" in error.to_user_message()
        assert "4000" in error.to_user_message()

    def test_image_invalid_size_error(self):
        """ImageInvalidSizeError"""
        error = ImageInvalidSizeError(
            size="2048x2048",
            provider="dalle3",
            supported_sizes=["1024x1024"],
        )
        assert "2048x2048" in error.to_user_message()
        assert "dalle3" in error.to_user_message()

    def test_content_policy_violation_error(self):
        """ContentPolicyViolationError"""
        error = ContentPolicyViolationError()
        assert "生成できません" in error.to_user_message()

    def test_dalle_api_error(self):
        """DALLEAPIError"""
        error = DALLEAPIError(
            message="API Error",
            model="dall-e-3",
        )
        assert error.model == "dall-e-3"

    def test_dalle_rate_limit_error(self):
        """DALLERateLimitError"""
        error = DALLERateLimitError(retry_after=60)
        assert "60秒" in error.to_user_message()

    def test_dalle_timeout_error(self):
        """DALLETimeoutError"""
        error = DALLETimeoutError(timeout_seconds=120)
        assert "タイムアウト" in error.to_user_message()


# =============================================================================
# ジェネレーターテスト
# =============================================================================


class TestImageGenerator:
    """ImageGeneratorのテスト"""

    def test_init(self, mock_pool, org_id):
        """初期化"""
        generator = ImageGenerator(
            pool=mock_pool,
            organization_id=org_id,
            api_key="test-key",
            openai_api_key="test-openai-key",
        )
        assert generator._organization_id == org_id
        assert generator._dalle_client is not None

    def test_validate_request_empty_prompt(self, image_generator, org_id):
        """空のプロンプトでエラー"""
        request = ImageRequest(
            organization_id=org_id,
            prompt="",
        )
        with pytest.raises(ImagePromptEmptyError):
            image_generator._validate_request(request)

    def test_validate_request_long_prompt(self, image_generator, org_id):
        """長すぎるプロンプトでエラー"""
        request = ImageRequest(
            organization_id=org_id,
            prompt="a" * 5000,
        )
        with pytest.raises(ImagePromptTooLongError):
            image_generator._validate_request(request)

    def test_validate_request_invalid_size(self, image_generator, org_id):
        """無効なサイズでエラー"""
        request = ImageRequest(
            organization_id=org_id,
            prompt="test",
            provider=ImageProvider.DALLE2,
            size=ImageSize.LANDSCAPE_1792,  # DALL-E 2ではサポートされない
        )
        with pytest.raises(ImageInvalidSizeError):
            image_generator._validate_request(request)

    def test_calculate_cost(self, image_generator, org_id):
        """コスト計算"""
        request = ImageRequest(
            organization_id=org_id,
            prompt="test",
            provider=ImageProvider.DALLE3,
            quality=ImageQuality.STANDARD,
            size=ImageSize.SQUARE_1024,
        )
        cost = image_generator._calculate_cost(request)
        assert cost == 6.0

    def test_calculate_cost_hd(self, image_generator, org_id):
        """HDコスト計算"""
        request = ImageRequest(
            organization_id=org_id,
            prompt="test",
            provider=ImageProvider.DALLE3,
            quality=ImageQuality.HD,
            size=ImageSize.SQUARE_1024,
        )
        cost = image_generator._calculate_cost(request)
        assert cost == 12.0

    def test_apply_style_modifier(self, image_generator):
        """スタイル修飾子適用"""
        prompt = "a cat"
        modified = image_generator._apply_style_modifier(prompt, ImageStyle.ANIME)
        assert "anime" in modified.lower()

    def test_select_model_dalle3(self, image_generator):
        """DALL-E 3モデル選択"""
        model = image_generator._select_model(ImageProvider.DALLE3, ImageQuality.STANDARD)
        assert model == "dall-e-3"

    def test_select_model_dalle2(self, image_generator):
        """DALL-E 2モデル選択"""
        model = image_generator._select_model(ImageProvider.DALLE2, ImageQuality.STANDARD)
        assert model == "dall-e-2"

    @pytest.mark.asyncio
    async def test_generate_success(self, image_generator, org_id, user_id):
        """正常な画像生成"""
        request = ImageRequest(
            organization_id=org_id,
            prompt="A beautiful sunset",
            user_id=user_id,
        )

        input_data = GenerationInput(
            generation_type=GenerationType.IMAGE,
            organization_id=org_id,
            image_request=request,
        )

        # DALLEClientをモック
        with patch.object(
            image_generator._dalle_client,
            "generate",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "url": "https://example.com/image.png",
                "revised_prompt": "A beautiful sunset over the ocean",
            },
        ):
            # プロンプト最適化をスキップ
            with patch.object(
                image_generator,
                "_optimize_prompt",
                new_callable=AsyncMock,
                return_value=OptimizedPrompt(
                    original_prompt="A beautiful sunset",
                    optimized_prompt="A beautiful sunset over the ocean",
                ),
            ):
                result = await image_generator.generate(input_data)

        assert result.success
        assert result.status == GenerationStatus.COMPLETED
        assert result.image_result is not None
        assert result.image_result.image_url == "https://example.com/image.png"


# =============================================================================
# クライアントテスト
# =============================================================================


class TestDALLEClient:
    """DALLEClientのテスト"""

    def test_init(self):
        """初期化"""
        client = DALLEClient(api_key="test-key")
        assert client._api_key == "test-key"

    def test_create_dalle_client(self):
        """ファクトリ関数"""
        client = create_dalle_client(api_key="test-key")
        assert isinstance(client, DALLEClient)


# =============================================================================
# ファクトリ関数テスト
# =============================================================================


class TestFactoryFunctions:
    """ファクトリ関数のテスト"""

    def test_create_image_generator(self, mock_pool, org_id):
        """ImageGenerator作成"""
        generator = create_image_generator(
            pool=mock_pool,
            organization_id=org_id,
        )
        assert isinstance(generator, ImageGenerator)
        assert generator._organization_id == org_id


# =============================================================================
# 統合モデルテスト
# =============================================================================


class TestIntegrationModels:
    """統合モデルのテスト"""

    def test_generation_input_with_image(self, org_id, user_id):
        """画像リクエストを含むGenerationInput"""
        request = ImageRequest(
            organization_id=org_id,
            prompt="test",
            user_id=user_id,
        )
        input_data = GenerationInput(
            generation_type=GenerationType.IMAGE,
            organization_id=org_id,
            image_request=request,
        )
        assert input_data.get_request() == request

    def test_generation_output_with_image(self):
        """画像結果を含むGenerationOutput"""
        result = ImageResult(
            status=GenerationStatus.COMPLETED,
            success=True,
            image_url="https://example.com/image.png",
        )
        output = GenerationOutput(
            generation_type=GenerationType.IMAGE,
            success=True,
            status=GenerationStatus.COMPLETED,
            image_result=result,
        )
        assert output.get_result() == result
        assert "完成" in output.to_user_message()

    def test_generation_output_to_dict_with_image(self):
        """GenerationOutputの辞書変換（画像）"""
        result = ImageResult(
            status=GenerationStatus.COMPLETED,
            success=True,
        )
        output = GenerationOutput(
            generation_type=GenerationType.IMAGE,
            success=True,
            image_result=result,
        )
        d = output.to_dict()
        assert d["generation_type"] == "image"
        assert "image_result" in d


# =============================================================================
# パッケージインポートテスト
# =============================================================================


class TestPackageImports:
    """パッケージインポートのテスト"""

    def test_import_image_types(self):
        """画像タイプのインポート"""
        from lib.capabilities.generation import (
            ImageProvider,
            ImageSize,
            ImageQuality,
            ImageStyle,
        )
        assert ImageProvider.DALLE3.value == "dalle3"
        assert ImageSize.SQUARE_1024.value == "1024x1024"

    def test_import_image_models(self):
        """画像モデルのインポート"""
        from lib.capabilities.generation import (
            ImageRequest,
            ImageResult,
            OptimizedPrompt,
        )
        assert ImageRequest is not None
        assert ImageResult is not None

    def test_import_image_exceptions(self):
        """画像例外のインポート"""
        from lib.capabilities.generation import (
            ImageGenerationError,
            DALLEAPIError,
            ContentPolicyViolationError,
        )
        assert ImageGenerationError is not None
        assert DALLEAPIError is not None

    def test_import_image_generator(self):
        """画像ジェネレーターのインポート"""
        from lib.capabilities.generation import (
            ImageGenerator,
            create_image_generator,
            DALLEClient,
            create_dalle_client,
        )
        assert ImageGenerator is not None
        assert create_image_generator is not None
        assert DALLEClient is not None
