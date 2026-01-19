"""
lib/embedding.py のテスト

エンベディング生成モジュールのユニットテスト
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from lib.embedding import (
    EmbeddingClient,
    EmbeddingResult,
    BatchEmbeddingResult,
    embed_text,
    embed_text_sync,
    get_embedding_client,
    EMBEDDING_MODELS,
    DEFAULT_MODEL,
)


class TestEmbeddingClient:
    """EmbeddingClient のテスト"""

    def test_init_with_api_key(self, mock_openai_embedding):
        """APIキー指定での初期化"""
        client = EmbeddingClient(api_key="test-key")
        assert client._api_key == "test-key"
        assert client.model == DEFAULT_MODEL

    def test_init_with_default_model(self, mock_openai_embedding):
        """デフォルトモデル（Gemini text-embedding-004）での初期化"""
        client = EmbeddingClient(api_key="test-key")
        assert client.model == DEFAULT_MODEL
        assert client.dimension == 768

    def test_init_invalid_model_raises_error(self, mock_openai_embedding):
        """無効なモデル指定でエラー"""
        with pytest.raises(ValueError, match="サポートされていないモデル"):
            EmbeddingClient(api_key="test-key", model="invalid-model")

    def test_dimension_property(self, mock_openai_embedding):
        """次元数プロパティのテスト"""
        client = EmbeddingClient(api_key="test-key")
        assert client.dimension == 768  # Gemini text-embedding-004

    def test_embed_text_sync(self, mock_openai_embedding):
        """同期版エンベディング生成"""
        client = EmbeddingClient(api_key="test-key")
        result = client.embed_text_sync("テスト文章")

        assert isinstance(result, EmbeddingResult)
        assert len(result.vector) == 768
        assert result.model == DEFAULT_MODEL
        # トークン数は estimate_tokens により計算される（文字数 * 0.5）
        assert result.token_count >= 0

    def test_embed_texts_sync(self, mock_openai_embedding):
        """同期版バッチエンベディング生成"""
        client = EmbeddingClient(api_key="test-key")
        result = client.embed_texts_sync(["テスト1", "テスト2"])

        assert isinstance(result, BatchEmbeddingResult)
        assert result.model == DEFAULT_MODEL
        assert result.total_tokens >= 0
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_embed_text_async(self, mock_openai_embedding):
        """非同期版エンベディング生成"""
        client = EmbeddingClient(api_key="test-key")
        result = await client.embed_text("テスト文章")

        assert isinstance(result, EmbeddingResult)
        assert len(result.vector) == 768

    @pytest.mark.asyncio
    async def test_embed_texts_async(self, mock_openai_embedding):
        """非同期版バッチエンベディング生成"""
        client = EmbeddingClient(api_key="test-key")
        result = await client.embed_texts(["テスト1", "テスト2"])

        assert isinstance(result, BatchEmbeddingResult)

    def test_estimate_tokens(self, mock_openai_embedding):
        """トークン数推定"""
        client = EmbeddingClient(api_key="test-key")
        # 日本語10文字 → 約5トークン
        estimate = client.estimate_tokens("あいうえおかきくけこ")
        assert estimate == 5

    def test_estimate_cost(self, mock_openai_embedding):
        """コスト推定（Gemini Embeddingは無料）"""
        client = EmbeddingClient(api_key="test-key")
        # Gemini Embedding は Free Tier のため、コストは0
        cost = client.estimate_cost(1000)
        assert cost == 0.0


class TestEmbeddingResult:
    """EmbeddingResult のテスト"""

    def test_vector_list_property(self):
        """vector_list プロパティのテスト"""
        result = EmbeddingResult(
            vector=[0.1, 0.2, 0.3],
            model="test-model",
            token_count=5,
            dimension=3
        )
        assert result.vector_list == [0.1, 0.2, 0.3]


class TestConvenienceFunctions:
    """便利関数のテスト"""

    def test_get_embedding_client_singleton(self, mock_openai_embedding):
        """シングルトンパターンのテスト"""
        # キャッシュをクリア
        import lib.embedding
        lib.embedding._default_client = None

        client1 = get_embedding_client()
        client2 = get_embedding_client()
        assert client1 is client2

    def test_embed_text_sync_function(self, mock_openai_embedding):
        """embed_text_sync 便利関数のテスト"""
        import lib.embedding
        lib.embedding._default_client = None

        vector = embed_text_sync("テスト")
        assert isinstance(vector, list)
        assert len(vector) == 768


class TestEmbeddingModels:
    """エンベディングモデル設定のテスト"""

    def test_default_model_exists(self):
        """デフォルトモデルが設定に存在"""
        assert DEFAULT_MODEL in EMBEDDING_MODELS

    def test_model_info_structure(self):
        """モデル情報の構造"""
        for model_name, info in EMBEDDING_MODELS.items():
            assert "dimension" in info
            assert "max_tokens" in info
            assert "cost_per_1k_tokens" in info
            assert isinstance(info["dimension"], int)
            assert isinstance(info["max_tokens"], int)
            assert isinstance(info["cost_per_1k_tokens"], float)
