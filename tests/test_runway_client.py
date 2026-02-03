"""
lib/capabilities/generation/runway_client.py のテスト

Runway APIクライアントの網羅的なテスト。
カバレッジ80%以上を目指す。
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import httpx

from lib.capabilities.generation.runway_client import (
    RunwayClient,
    create_runway_client,
)
from lib.capabilities.generation.constants import (
    VideoDuration,
)
from lib.capabilities.generation.exceptions import (
    RunwayAPIError,
    RunwayRateLimitError,
    RunwayTimeoutError,
    RunwayQuotaExceededError,
    RunwayServerError,
    VideoContentPolicyViolationError,
)


# ================================================================
# フィクスチャ
# ================================================================

@pytest.fixture
def client():
    """RunwayClientインスタンス"""
    return RunwayClient(api_key="test_api_key")


@pytest.fixture
def client_no_key():
    """APIキーなしのクライアント"""
    with patch.dict('os.environ', {}, clear=True):
        return RunwayClient()


# ================================================================
# 初期化テスト
# ================================================================

class TestRunwayClientInit:
    """初期化のテスト"""

    def test_init_with_api_key(self):
        """APIキー指定で初期化"""
        client = RunwayClient(api_key="my_key")
        assert client._api_key == "my_key"

    def test_init_from_env(self):
        """環境変数からAPIキー取得"""
        with patch.dict('os.environ', {'RUNWAY_API_KEY': 'env_key'}):
            client = RunwayClient()
            assert client._api_key == "env_key"

    def test_init_custom_timeout(self):
        """カスタムタイムアウト"""
        client = RunwayClient(api_key="key", timeout_seconds=120)
        assert client._timeout_seconds == 120

    def test_init_custom_retries(self):
        """カスタムリトライ回数"""
        client = RunwayClient(api_key="key", max_retries=5)
        assert client._max_retries == 5


# ================================================================
# 生成テスト
# ================================================================

class TestGenerate:
    """generate メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_generate_no_api_key(self, client_no_key):
        """APIキーなしでエラー"""
        with pytest.raises(RunwayAPIError):
            await client_no_key.generate(prompt="Test")
        # APIキーなしでRunwayAPIErrorがraiseされることを確認

    @pytest.mark.asyncio
    async def test_generate_success(self, client):
        """生成成功"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "task_123"}

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await client.generate(
                prompt="A cat walking",
                duration=VideoDuration.STANDARD_10S,
            )

        assert result["task_id"] == "task_123"
        assert result["status"] == "PENDING"
        # リクエストペイロードの検証
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert "json" in call_kwargs
        payload = call_kwargs["json"]
        assert payload["promptText"] == "A cat walking"
        assert payload["duration"] == 10

    @pytest.mark.asyncio
    async def test_generate_with_source_image(self, client):
        """画像→動画生成"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "task_456"}

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await client.generate(
                prompt="A cat walking",
                source_image_url="https://example.com/cat.jpg",
            )

        assert result["task_id"] == "task_456"
        # リクエストペイロードの検証（画像URL含む）
        payload = mock_post.call_args[1]["json"]
        assert payload["promptText"] == "A cat walking"
        assert payload["promptImage"] == "https://example.com/cat.jpg"

    @pytest.mark.asyncio
    async def test_generate_with_seed(self, client):
        """シード値指定"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "task_789"}

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await client.generate(
                prompt="A cat walking",
                seed=12345,
            )

        assert result["task_id"] == "task_789"
        # リクエストペイロードの検証（シード値含む）
        payload = mock_post.call_args[1]["json"]
        assert payload["seed"] == 12345

    @pytest.mark.asyncio
    async def test_generate_rate_limit(self, client):
        """レート制限エラー"""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(RunwayRateLimitError):
                await client.generate(prompt="Test")

    @pytest.mark.asyncio
    async def test_generate_rate_limit_no_header(self, client):
        """レート制限（Retry-Afterなし）"""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(RunwayRateLimitError):
                await client.generate(prompt="Test")

    @pytest.mark.asyncio
    async def test_generate_invalid_api_key(self, client):
        """無効なAPIキー"""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(RunwayAPIError):
                await client.generate(prompt="Test")
            # 401エラーでRunwayAPIErrorがraiseされることを確認

    @pytest.mark.asyncio
    async def test_generate_quota_exceeded(self, client):
        """クォータ超過"""
        mock_response = MagicMock()
        mock_response.status_code = 402

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(RunwayQuotaExceededError):
                await client.generate(prompt="Test")

    @pytest.mark.asyncio
    async def test_generate_server_error(self, client):
        """サーバーエラー"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(RunwayServerError):
                await client.generate(prompt="Test")

    @pytest.mark.asyncio
    async def test_generate_content_policy_violation(self, client):
        """コンテンツポリシー違反"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.content = b'{"error": "Content policy violation"}'
        mock_response.json.return_value = {"error": "Content policy violation"}

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(VideoContentPolicyViolationError):
                await client.generate(prompt="Test")

    @pytest.mark.asyncio
    async def test_generate_inappropriate_content(self, client):
        """不適切なコンテンツ"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.content = b'{"error": "Inappropriate content"}'
        mock_response.json.return_value = {"error": "Inappropriate content"}

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(VideoContentPolicyViolationError):
                await client.generate(prompt="Test")

    @pytest.mark.asyncio
    async def test_generate_other_error(self, client):
        """その他のエラー"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.content = b'{"error": "Bad request"}'
        mock_response.json.return_value = {"error": "Bad request"}

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(RunwayAPIError):
                await client.generate(prompt="Test")

    @pytest.mark.asyncio
    async def test_generate_empty_error_response(self, client):
        """エラーレスポンスが空"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.content = b''
        mock_response.text = "Error"

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(RunwayAPIError):
                await client.generate(prompt="Test")

    @pytest.mark.asyncio
    async def test_generate_timeout(self, client):
        """タイムアウト"""
        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(RunwayTimeoutError):
                await client.generate(prompt="Test")

    @pytest.mark.asyncio
    async def test_generate_unexpected_error(self, client):
        """予期しないエラー"""
        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, side_effect=Exception("Unexpected")):
            with pytest.raises(RunwayAPIError):
                await client.generate(prompt="Test")


# ================================================================
# タスクステータス取得テスト
# ================================================================

class TestGetTaskStatus:
    """get_task_status メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_status_no_api_key(self, client_no_key):
        """APIキーなしでエラー"""
        with pytest.raises(RunwayAPIError):
            await client_no_key.get_task_status("task_123")

    @pytest.mark.asyncio
    async def test_get_status_success_pending(self, client):
        """ステータス取得（PENDING）"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "PENDING",
            "progress": 0,
        }

        with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=mock_response):
            result = await client.get_task_status("task_123")

        assert result["status"] == "PENDING"
        assert result["progress"] == 0

    @pytest.mark.asyncio
    async def test_get_status_success_running(self, client):
        """ステータス取得（RUNNING）"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "RUNNING",
            "progress": 50,
        }

        with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=mock_response):
            result = await client.get_task_status("task_123")

        assert result["status"] == "RUNNING"
        assert result["progress"] == 50

    @pytest.mark.asyncio
    async def test_get_status_success_completed(self, client):
        """ステータス取得（SUCCEEDED）"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "SUCCEEDED",
            "progress": 100,
            "output": ["https://example.com/video.mp4"],
            "createdAt": "2026-01-28T10:00:00Z",
        }

        with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=mock_response):
            result = await client.get_task_status("task_123")

        assert result["status"] == "SUCCEEDED"
        assert result["output_url"] == "https://example.com/video.mp4"

    @pytest.mark.asyncio
    async def test_get_status_success_failed(self, client):
        """ステータス取得（FAILED）"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "FAILED",
            "progress": 0,
            "failure": "Processing error",
            "failureCode": "PROCESSING_ERROR",
        }

        with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=mock_response):
            result = await client.get_task_status("task_123")

        assert result["status"] == "FAILED"
        assert result["error"] == "Processing error"
        assert result["failure_code"] == "PROCESSING_ERROR"

    @pytest.mark.asyncio
    async def test_get_status_rate_limit(self, client):
        """レート制限"""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "30"}

        with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(RunwayRateLimitError):
                await client.get_task_status("task_123")

    @pytest.mark.asyncio
    async def test_get_status_api_error(self, client):
        """APIエラー"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Task not found"

        with patch('httpx.AsyncClient.get', new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(RunwayAPIError):
                await client.get_task_status("task_123")

    @pytest.mark.asyncio
    async def test_get_status_timeout(self, client):
        """タイムアウト"""
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock, side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(RunwayTimeoutError):
                await client.get_task_status("task_123")

    @pytest.mark.asyncio
    async def test_get_status_unexpected_error(self, client):
        """予期しないエラー"""
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock, side_effect=Exception("Unexpected")):
            with pytest.raises(RunwayAPIError):
                await client.get_task_status("task_123")


# ================================================================
# 完了待機テスト
# ================================================================

class TestWaitForCompletion:
    """wait_for_completion メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_wait_success(self, client):
        """完了待機成功"""
        client.get_task_status = AsyncMock(return_value={
            "task_id": "task_123",
            "status": "SUCCEEDED",
            "progress": 100,
            "output_url": "https://example.com/video.mp4",
        })

        result = await client.wait_for_completion("task_123")

        assert result["status"] == "SUCCEEDED"
        assert result["output_url"] == "https://example.com/video.mp4"

    @pytest.mark.asyncio
    async def test_wait_with_progress_callback(self, client):
        """進捗コールバック付き"""
        call_count = [0]
        progress_values = []

        def callback(progress, status):
            call_count[0] += 1
            progress_values.append(progress)

        client.get_task_status = AsyncMock(side_effect=[
            {"task_id": "task_123", "status": "RUNNING", "progress": 50},
            {"task_id": "task_123", "status": "SUCCEEDED", "progress": 100},
        ])

        with patch('asyncio.sleep', new_callable=AsyncMock):
            result = await client.wait_for_completion(
                "task_123",
                progress_callback=callback,
            )

        assert result["status"] == "SUCCEEDED"
        assert call_count[0] == 2
        assert progress_values == [50, 100]

    @pytest.mark.asyncio
    async def test_wait_failed(self, client):
        """タスク失敗"""
        client.get_task_status = AsyncMock(return_value={
            "task_id": "task_123",
            "status": "FAILED",
            "progress": 0,
            "error": "Processing failed",
            "failure_code": "PROCESSING_ERROR",
        })

        with pytest.raises(RunwayAPIError):
            await client.wait_for_completion("task_123")

    @pytest.mark.asyncio
    async def test_wait_content_moderation_failure(self, client):
        """コンテンツモデレーション失敗"""
        client.get_task_status = AsyncMock(return_value={
            "task_id": "task_123",
            "status": "FAILED",
            "progress": 0,
            "error": "Content policy violation",
            "failure_code": "CONTENT_MODERATION",
        })

        with pytest.raises(VideoContentPolicyViolationError):
            await client.wait_for_completion("task_123")

    @pytest.mark.asyncio
    async def test_wait_timeout(self, client):
        """ポーリングタイムアウト"""
        client.get_task_status = AsyncMock(return_value={
            "task_id": "task_123",
            "status": "RUNNING",
            "progress": 50,
        })

        with patch('asyncio.sleep', new_callable=AsyncMock):
            with pytest.raises(RunwayTimeoutError):
                await client.wait_for_completion(
                    "task_123",
                    poll_interval=1,
                    max_attempts=2,
                )


# ================================================================
# タスクキャンセルテスト
# ================================================================

class TestCancelTask:
    """cancel_task メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_cancel_no_api_key(self, client_no_key):
        """APIキーなしでエラー"""
        with pytest.raises(RunwayAPIError):
            await client_no_key.cancel_task("task_123")

    @pytest.mark.asyncio
    async def test_cancel_success_200(self, client):
        """キャンセル成功（200）"""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch('httpx.AsyncClient.delete', new_callable=AsyncMock, return_value=mock_response):
            result = await client.cancel_task("task_123")

        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_success_204(self, client):
        """キャンセル成功（204）"""
        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch('httpx.AsyncClient.delete', new_callable=AsyncMock, return_value=mock_response):
            result = await client.cancel_task("task_123")

        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_failure(self, client):
        """キャンセル失敗"""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch('httpx.AsyncClient.delete', new_callable=AsyncMock, return_value=mock_response):
            result = await client.cancel_task("task_123")

        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_exception(self, client):
        """キャンセル中に例外"""
        with patch('httpx.AsyncClient.delete', new_callable=AsyncMock, side_effect=Exception("Error")):
            result = await client.cancel_task("task_123")

        assert result is False


# ================================================================
# ファクトリ関数テスト
# ================================================================

class TestCreateRunwayClient:
    """create_runway_client のテスト"""

    def test_create_with_key(self):
        """APIキー指定で作成"""
        client = create_runway_client(api_key="my_key")
        assert isinstance(client, RunwayClient)
        assert client._api_key == "my_key"

    def test_create_with_timeout(self):
        """タイムアウト指定で作成"""
        client = create_runway_client(api_key="key", timeout_seconds=120)
        assert client._timeout_seconds == 120
