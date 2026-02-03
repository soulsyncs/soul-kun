# tests/test_dalle_client.py
"""
DALL-E APIクライアントのテスト

lib/capabilities/generation/dalle_client.py のカバレッジ80%以上を目指す。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from lib.capabilities.generation.dalle_client import (
    DALLEClient,
    create_dalle_client,
)
from lib.capabilities.generation.constants import (
    ImageSize,
    ImageQuality,
    ImageStyle,
    DEFAULT_IMAGE_MODEL,
    DALLE2_MODEL,
    DALLE_API_TIMEOUT_SECONDS,
)
from lib.capabilities.generation.exceptions import (
    DALLEAPIError,
    DALLERateLimitError,
    DALLETimeoutError,
    DALLEQuotaExceededError,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def dalle_client():
    """テスト用DALLEClientを作成"""
    return DALLEClient(api_key="test-api-key")


@pytest.fixture
def mock_response_success():
    """成功レスポンスのモック"""
    return {
        "data": [
            {
                "url": "https://example.com/image.png",
                "revised_prompt": "A beautiful sunset over the ocean",
            }
        ]
    }


@pytest.fixture
def mock_response_b64():
    """base64レスポンスのモック"""
    return {
        "data": [
            {
                "b64_json": "iVBORw0KGgo=",
                "revised_prompt": "A beautiful sunset",
            }
        ]
    }


# =============================================================================
# TestDALLEClientInit - 初期化テスト
# =============================================================================


class TestDALLEClientInit:
    """DALLEClient初期化のテスト"""

    def test_init_with_api_key(self):
        """API Keyを指定して初期化"""
        client = DALLEClient(api_key="sk-test-key")
        assert client._api_key == "sk-test-key"
        assert client._timeout_seconds == DALLE_API_TIMEOUT_SECONDS

    def test_init_from_env(self):
        """環境変数からAPI Keyを取得"""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env-key"}):
            client = DALLEClient()
            assert client._api_key == "sk-env-key"

    def test_init_custom_timeout(self):
        """カスタムタイムアウトを設定"""
        client = DALLEClient(api_key="sk-test", timeout_seconds=60)
        assert client._timeout_seconds == 60

    def test_init_custom_retries(self):
        """カスタムリトライ回数を設定"""
        client = DALLEClient(api_key="sk-test", max_retries=5)
        assert client._max_retries == 5


# =============================================================================
# TestGenerate - 画像生成テスト
# =============================================================================


class TestGenerate:
    """generate()メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_generate_no_api_key(self):
        """API Keyなしでエラー"""
        client = DALLEClient(api_key=None)
        with patch.dict("os.environ", {}, clear=True):
            client._api_key = None
            with pytest.raises(DALLEAPIError) as exc_info:
                await client.generate(prompt="test")
            assert "API_KEY_MISSING" in str(exc_info.value.error_code)

    @pytest.mark.asyncio
    async def test_generate_success(self, dalle_client, mock_response_success):
        """正常に画像を生成"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_response_success

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(return_value=mock_resp)
            result = await dalle_client.generate(prompt="A sunset")

        assert result["success"] is True
        assert result["url"] == "https://example.com/image.png"
        assert result["revised_prompt"] == "A beautiful sunset over the ocean"
        # リクエストペイロードの検証
        call_args = mock_instance.post.call_args
        assert call_args[1]["json"]["prompt"] == "A sunset"
        assert call_args[1]["json"]["model"] == DEFAULT_IMAGE_MODEL

    @pytest.mark.asyncio
    async def test_generate_with_dalle2(self, dalle_client, mock_response_success):
        """DALL-E 2モデルで生成"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_response_success

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(return_value=mock_resp)
            result = await dalle_client.generate(
                prompt="A sunset",
                model=DALLE2_MODEL,
                n=2,
            )

        assert result["success"] is True
        # DALL-E 2はn=2でも送信可能（内部でn=1にしないため）
        call_args = mock_instance.post.call_args
        assert call_args[1]["json"]["model"] == DALLE2_MODEL

    @pytest.mark.asyncio
    async def test_generate_with_custom_size(self, dalle_client, mock_response_success):
        """カスタムサイズで生成"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_response_success

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(return_value=mock_resp)
            await dalle_client.generate(
                prompt="A sunset",
                size=ImageSize.LANDSCAPE_1792,
            )

        call_args = mock_instance.post.call_args
        assert call_args[1]["json"]["size"] == "1792x1024"

    @pytest.mark.asyncio
    async def test_generate_with_hd_quality(self, dalle_client, mock_response_success):
        """HD品質で生成"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_response_success

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(return_value=mock_resp)
            await dalle_client.generate(
                prompt="A sunset",
                quality=ImageQuality.HD,
            )

        call_args = mock_instance.post.call_args
        assert call_args[1]["json"]["quality"] == "hd"

    @pytest.mark.asyncio
    async def test_generate_with_natural_style(self, dalle_client, mock_response_success):
        """Natural スタイルで生成"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_response_success

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(return_value=mock_resp)
            await dalle_client.generate(
                prompt="A sunset",
                style=ImageStyle.NATURAL,
            )

        call_args = mock_instance.post.call_args
        assert call_args[1]["json"]["style"] == "natural"

    @pytest.mark.asyncio
    async def test_generate_with_custom_style_falls_back_to_vivid(
        self, dalle_client, mock_response_success
    ):
        """カスタムスタイル（ANIME等）はvividにフォールバック"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_response_success

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(return_value=mock_resp)
            await dalle_client.generate(
                prompt="A sunset",
                style=ImageStyle.ANIME,
            )

        call_args = mock_instance.post.call_args
        assert call_args[1]["json"]["style"] == "vivid"

    @pytest.mark.asyncio
    async def test_generate_b64_response_format(self, dalle_client, mock_response_b64):
        """base64形式でレスポンスを取得"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_response_b64

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(return_value=mock_resp)
            result = await dalle_client.generate(
                prompt="A sunset",
                response_format="b64_json",
            )

        assert result["success"] is True
        assert result["b64_json"] == "iVBORw0KGgo="

    @pytest.mark.asyncio
    async def test_generate_rate_limit(self, dalle_client):
        """レート制限エラー"""
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {"Retry-After": "30"}
        mock_resp.json.return_value = {"error": {"message": "Rate limit exceeded"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            with pytest.raises(DALLERateLimitError) as exc_info:
                await dalle_client.generate(prompt="test")

        assert exc_info.value.retry_after == 30

    @pytest.mark.asyncio
    async def test_generate_rate_limit_no_header(self, dalle_client):
        """レート制限エラー（Retry-Afterヘッダなし）"""
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {}
        mock_resp.json.return_value = {"error": {"message": "Rate limit exceeded"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            with pytest.raises(DALLERateLimitError) as exc_info:
                await dalle_client.generate(prompt="test")

        assert exc_info.value.retry_after is None

    @pytest.mark.asyncio
    async def test_generate_quota_exceeded_402(self, dalle_client):
        """クォータ超過エラー（402）"""
        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.json.return_value = {"error": {"message": "Billing error"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            with pytest.raises(DALLEQuotaExceededError):
                await dalle_client.generate(prompt="test")

    @pytest.mark.asyncio
    async def test_generate_quota_exceeded_message(self, dalle_client):
        """クォータ超過エラー（メッセージに'quota'を含む）"""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": {"message": "You exceeded your current quota"}
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            with pytest.raises(DALLEQuotaExceededError):
                await dalle_client.generate(prompt="test")

    @pytest.mark.asyncio
    async def test_generate_content_policy_violation(self, dalle_client):
        """コンテンツポリシー違反（DALLEAPIErrorでラップされる）"""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": {
                "message": "Your request was rejected",
                "code": "content_policy_violation",
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            # ContentPolicyViolationErrorはDALLEAPIErrorでラップされる
            with pytest.raises(DALLEAPIError):
                await dalle_client.generate(prompt="inappropriate content")

    @pytest.mark.asyncio
    async def test_generate_safety_error(self, dalle_client):
        """安全性エラー（safety関連のメッセージで検出）"""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": {
                "message": "This request contains safety issues",
                "code": "invalid_request",
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            # safetyキーワードを含むエラーでDALLEAPIErrorがraiseされる
            with pytest.raises(DALLEAPIError):
                await dalle_client.generate(prompt="unsafe content")

    @pytest.mark.asyncio
    async def test_generate_server_error(self, dalle_client):
        """サーバーエラー"""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": {"message": "Internal server error"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            with pytest.raises(DALLEAPIError) as exc_info:
                await dalle_client.generate(prompt="test")

        assert "HTTP_500" in exc_info.value.error_code

    @pytest.mark.asyncio
    async def test_generate_error_parse_failure(self, dalle_client):
        """エラーレスポンスのパース失敗"""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.side_effect = Exception("Invalid JSON")
        mock_resp.text = "Bad request"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            with pytest.raises(DALLEAPIError):
                await dalle_client.generate(prompt="test")

    @pytest.mark.asyncio
    async def test_generate_timeout(self, dalle_client):
        """タイムアウトエラー"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )
            with pytest.raises(DALLETimeoutError):
                await dalle_client.generate(prompt="test")

    @pytest.mark.asyncio
    async def test_generate_unexpected_error(self, dalle_client):
        """予期しないエラー"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=RuntimeError("Unexpected error")
            )
            # 予期しないエラーがDALLEAPIErrorとしてラップされる
            with pytest.raises(DALLEAPIError):
                await dalle_client.generate(prompt="test")

    @pytest.mark.asyncio
    async def test_generate_empty_response(self, dalle_client):
        """空のレスポンス"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            result = await dalle_client.generate(prompt="test")

        assert result["success"] is False
        assert "error" in result  # エラーフィールドが存在することを確認

    @pytest.mark.asyncio
    async def test_generate_retry_exhausted_rate_limit(self, dalle_client):
        """レート制限でリトライ回数を使い切った場合"""
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        mock_resp_429.headers = {"Retry-After": "1"}
        mock_resp_429.json.return_value = {"error": {"message": "Rate limited"}}

        with patch("httpx.AsyncClient") as mock_client:
            # 常に429を返す（リトライ回数を使い切る）
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp_429
            )
            with patch("asyncio.sleep", new=AsyncMock()):
                with pytest.raises(DALLERateLimitError):
                    dalle_client._max_retries = 1
                    await dalle_client.generate(prompt="test")


# =============================================================================
# TestFormatResponse - レスポンス整形テスト
# =============================================================================


class TestFormatResponse:
    """_format_response()メソッドのテスト"""

    def test_format_response_with_url(self, dalle_client):
        """URLレスポンスの整形"""
        result = {
            "data": [
                {
                    "url": "https://example.com/image.png",
                    "revised_prompt": "A sunset",
                }
            ]
        }
        formatted = dalle_client._format_response(result, DEFAULT_IMAGE_MODEL)

        assert formatted["success"] is True
        assert formatted["url"] == "https://example.com/image.png"
        assert formatted["revised_prompt"] == "A sunset"
        assert formatted["model"] == DEFAULT_IMAGE_MODEL

    def test_format_response_with_b64(self, dalle_client):
        """base64レスポンスの整形"""
        result = {
            "data": [
                {
                    "b64_json": "base64data",
                    "revised_prompt": "A sunset",
                }
            ]
        }
        formatted = dalle_client._format_response(result, DEFAULT_IMAGE_MODEL)

        assert formatted["success"] is True
        assert formatted["b64_json"] == "base64data"

    def test_format_response_empty_data(self, dalle_client):
        """空データの整形"""
        result = {"data": []}
        formatted = dalle_client._format_response(result, DEFAULT_IMAGE_MODEL)

        assert formatted["success"] is False
        assert "error" in formatted  # エラーフィールドが存在することを確認

    def test_format_response_no_data_key(self, dalle_client):
        """dataキーなしの整形"""
        result = {}
        formatted = dalle_client._format_response(result, DEFAULT_IMAGE_MODEL)

        assert formatted["success"] is False


# =============================================================================
# TestCreateDALLEClient - ファクトリ関数テスト
# =============================================================================


class TestCreateDALLEClient:
    """create_dalle_client()のテスト"""

    def test_create_with_key(self):
        """API Keyを指定して作成"""
        client = create_dalle_client(api_key="sk-test")
        assert isinstance(client, DALLEClient)
        assert client._api_key == "sk-test"

    def test_create_with_timeout(self):
        """カスタムタイムアウトで作成"""
        client = create_dalle_client(api_key="sk-test", timeout_seconds=30)
        assert client._timeout_seconds == 30

    def test_create_without_key(self):
        """API Keyなしで作成（環境変数から取得）"""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env"}):
            client = create_dalle_client()
            assert client._api_key == "sk-env"


# =============================================================================
# TestHandleErrorResponse - エラーハンドリングテスト
# =============================================================================


class TestHandleErrorResponse:
    """_handle_error_response()メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_handle_401_error(self, dalle_client):
        """401エラー（認証失敗）"""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": {"message": "Invalid API key"}}

        with pytest.raises(DALLEAPIError) as exc_info:
            await dalle_client._handle_error_response(mock_resp, DEFAULT_IMAGE_MODEL)

        assert "HTTP_401" in exc_info.value.error_code

    @pytest.mark.asyncio
    async def test_handle_error_empty_code(self, dalle_client):
        """エラーコードなしの場合"""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": {"message": "Bad request"}}

        with pytest.raises(DALLEAPIError):
            await dalle_client._handle_error_response(mock_resp, DEFAULT_IMAGE_MODEL)
