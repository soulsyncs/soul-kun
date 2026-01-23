"""
エンベディング生成モジュール（Gemini Embedding版）

テキストからエンベディングベクターを生成する機能を提供します。

★★★ v10.12.0: Gemini Embeddingに変更 ★★★
- OpenAI text-embedding-3-small → Gemini text-embedding-004
- 次元数: 1536 → 768
- コスト: $0.02/1M tokens → 無料（Free Tier）

使用例:
    from lib.embedding import EmbeddingClient

    client = EmbeddingClient()

    # 単一テキストのエンベディング（ドキュメント保存用）
    result = client.embed_text_sync("経費精算の手順を教えてください")
    print(f"次元数: {result.dimension}")  # 768

    # 複数テキストのエンベディング（バッチ処理）
    results = client.embed_texts_sync([
        "経費精算の手順",
        "出張申請の方法",
        "勤怠入力のルール"
    ])

    # クエリ用エンベディング（検索時に使用）
    query_result = client.embed_query_sync("有給申請の方法は？")

設計ドキュメント:
    docs/05_phase3_knowledge_detailed_design.md
"""

import os
import asyncio
import time
from typing import Optional
from dataclasses import dataclass
import logging

import google.generativeai as genai

from lib.config import get_settings
from lib.secrets import get_secret


logger = logging.getLogger(__name__)


# ================================================================
# 設定
# ================================================================

# 利用可能なモデル
EMBEDDING_MODELS = {
    "models/text-embedding-004": {
        "dimension": 768,
        "max_tokens": 2048,
        "cost_per_1k_tokens": 0.0,  # 無料（Free Tier）
    },
}

# デフォルトモデル
DEFAULT_MODEL = "models/text-embedding-004"


# ================================================================
# データクラス定義
# ================================================================

@dataclass
class EmbeddingResult:
    """エンベディング結果"""
    vector: list[float]
    model: str
    token_count: int
    dimension: int

    @property
    def vector_list(self) -> list[float]:
        """ベクターをリストとして取得（Pinecone用）"""
        return self.vector


@dataclass
class BatchEmbeddingResult:
    """バッチエンベディング結果"""
    results: list[EmbeddingResult]
    total_tokens: int
    model: str
    processing_time_ms: int


# ================================================================
# エンベディングクライアント
# ================================================================

class EmbeddingClient:
    """
    Gemini Embedding APIクライアント

    ★★★ v10.12.0: Gemini Embeddingに変更 ★★★

    使用例:
        client = EmbeddingClient()

        # ドキュメント保存用（task_type="retrieval_document"）
        result = client.embed_text_sync("検索対象のテキスト")
        print(f"次元数: {result.dimension}")  # 768
        print(f"ベクター: {result.vector[:5]}...")  # 最初の5要素

        # クエリ用（task_type="retrieval_query"）
        query_result = client.embed_query_sync("検索クエリ")

        # バッチ処理
        results = client.embed_texts_sync(["テキスト1", "テキスト2"])
        for r in results.results:
            print(f"次元数: {r.dimension}")

        # 非同期版（FastAPI用）
        result = await client.embed_text("検索対象のテキスト")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
    ):
        """
        Args:
            api_key: Gemini APIキー（未指定時は環境変数またはSecret Managerから取得）
            model: 使用するエンベディングモデル
        """
        self.settings = get_settings()

        # APIキーの取得
        if api_key:
            self._api_key = api_key
        else:
            # 環境変数から取得（GOOGLE_AI_API_KEY または GEMINI_API_KEY）
            self._api_key = os.getenv('GOOGLE_AI_API_KEY') or os.getenv('GEMINI_API_KEY')
            if not self._api_key:
                try:
                    self._api_key = get_secret('GOOGLE_AI_API_KEY')
                except Exception:
                    raise ValueError(
                        "Gemini APIキーが設定されていません。"
                        "環境変数 GOOGLE_AI_API_KEY または Secret Manager で設定してください。"
                    )

        # Gemini APIの設定
        genai.configure(api_key=self._api_key)

        self.model = model

        # モデル情報
        if model not in EMBEDDING_MODELS:
            raise ValueError(f"サポートされていないモデル: {model}")
        self.model_info = EMBEDDING_MODELS[model]

    @property
    def dimension(self) -> int:
        """エンベディングの次元数"""
        return self.model_info["dimension"]

    # ================================================================
    # 非同期メソッド（FastAPI用）
    # ================================================================

    async def embed_text(
        self,
        text: str,
        task_type: str = "retrieval_document"
    ) -> EmbeddingResult:
        """
        テキストのエンベディングを生成（非同期）

        Args:
            text: エンベディングを生成するテキスト
            task_type: タスクタイプ
                - "retrieval_document": ドキュメント保存用
                - "retrieval_query": 検索クエリ用

        Returns:
            EmbeddingResult オブジェクト
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.embed_text_sync(text, task_type)
        )

    async def embed_query(self, query: str) -> EmbeddingResult:
        """
        検索クエリのエンベディングを生成（非同期）

        Args:
            query: 検索クエリ

        Returns:
            EmbeddingResult オブジェクト
        """
        return await self.embed_text(query, task_type="retrieval_query")

    async def embed_texts(
        self,
        texts: list[str],
        task_type: str = "retrieval_document",
        batch_size: int = 100,
    ) -> BatchEmbeddingResult:
        """
        複数テキストのエンベディングを生成（非同期、バッチ処理）

        Args:
            texts: エンベディングを生成するテキストのリスト
            task_type: タスクタイプ
            batch_size: バッチサイズ

        Returns:
            BatchEmbeddingResult オブジェクト
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.embed_texts_sync(texts, task_type, batch_size)
        )

    # ================================================================
    # 同期メソッド（Cloud Functions用）
    # ================================================================

    def embed_text_sync(
        self,
        text: str,
        task_type: str = "retrieval_document"
    ) -> EmbeddingResult:
        """
        テキストのエンベディングを生成（同期）

        Args:
            text: エンベディングを生成するテキスト
            task_type: タスクタイプ
                - "retrieval_document": ドキュメント保存用
                - "retrieval_query": 検索クエリ用

        Returns:
            EmbeddingResult オブジェクト
        """
        result = genai.embed_content(
            model=self.model,
            content=text,
            task_type=task_type
        )

        embedding = result['embedding']

        return EmbeddingResult(
            vector=embedding,
            model=self.model,
            token_count=self.estimate_tokens(text),
            dimension=len(embedding),
        )

    def embed_query_sync(self, query: str) -> EmbeddingResult:
        """
        検索クエリのエンベディングを生成（同期）

        Args:
            query: 検索クエリ

        Returns:
            EmbeddingResult オブジェクト
        """
        return self.embed_text_sync(query, task_type="retrieval_query")

    def embed_texts_sync(
        self,
        texts: list[str],
        task_type: str = "retrieval_document",
        batch_size: int = 100,
    ) -> BatchEmbeddingResult:
        """
        複数テキストのエンベディングを生成（同期、バッチ処理）

        Args:
            texts: エンベディングを生成するテキストのリスト
            task_type: タスクタイプ
            batch_size: バッチサイズ

        Returns:
            BatchEmbeddingResult オブジェクト
        """
        start_time = time.time()
        all_results: list[EmbeddingResult] = []
        total_tokens = 0

        # バッチ処理
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            # Gemini embed_contentは単一テキストのみ対応
            # 複数テキストは順次処理
            for text in batch:
                result = genai.embed_content(
                    model=self.model,
                    content=text,
                    task_type=task_type
                )

                embedding = result['embedding']
                token_count = self.estimate_tokens(text)

                all_results.append(EmbeddingResult(
                    vector=embedding,
                    model=self.model,
                    token_count=token_count,
                    dimension=len(embedding),
                ))

                total_tokens += token_count

        processing_time_ms = int((time.time() - start_time) * 1000)

        return BatchEmbeddingResult(
            results=all_results,
            total_tokens=total_tokens,
            model=self.model,
            processing_time_ms=processing_time_ms,
        )

    # ================================================================
    # ユーティリティ
    # ================================================================

    def estimate_tokens(self, text: str) -> int:
        """
        テキストのトークン数を推定

        注: 正確ではなく、概算値を返します。
        """
        # 日本語は約0.5トークン/文字、英語は約0.25トークン/ワード
        # 簡易推定: 文字数 * 0.5
        return int(len(text) * 0.5)

    def estimate_cost(self, token_count: int) -> float:
        """
        API呼び出しのコストを推定（USD）

        Args:
            token_count: トークン数

        Returns:
            推定コスト（USD）

        Note:
            Gemini Embedding は Free Tier のため、コストは0
        """
        cost_per_1k = self.model_info["cost_per_1k_tokens"]
        return (token_count / 1000) * cost_per_1k


# ================================================================
# 便利な関数
# ================================================================

_default_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> EmbeddingClient:
    """デフォルトのエンベディングクライアントを取得（シングルトン）"""
    global _default_client
    if _default_client is None:
        _default_client = EmbeddingClient()
    return _default_client


async def embed_text(text: str) -> list[float]:
    """
    テキストのエンベディングを生成（便利関数）

    Args:
        text: エンベディングを生成するテキスト

    Returns:
        エンベディングベクター
    """
    client = get_embedding_client()
    result = await client.embed_text(text)
    return result.vector


def embed_text_sync(text: str) -> list[float]:
    """
    テキストのエンベディングを生成（同期版、便利関数）

    Args:
        text: エンベディングを生成するテキスト

    Returns:
        エンベディングベクター
    """
    client = get_embedding_client()
    result = client.embed_text_sync(text)
    return result.vector


async def embed_query(query: str) -> list[float]:
    """
    検索クエリのエンベディングを生成（便利関数）

    Args:
        query: 検索クエリ

    Returns:
        エンベディングベクター
    """
    client = get_embedding_client()
    result = await client.embed_query(query)
    return result.vector


def embed_query_sync(query: str) -> list[float]:
    """
    検索クエリのエンベディングを生成（同期版、便利関数）

    Args:
        query: 検索クエリ

    Returns:
        エンベディングベクター
    """
    client = get_embedding_client()
    result = client.embed_query_sync(query)
    return result.vector


# ================================================================
# エクスポート
# ================================================================

__all__ = [
    # クライアント
    'EmbeddingClient',
    'get_embedding_client',
    # データクラス
    'EmbeddingResult',
    'BatchEmbeddingResult',
    # 便利関数
    'embed_text',
    'embed_text_sync',
    'embed_query',
    'embed_query_sync',
    # 設定
    'EMBEDDING_MODELS',
    'DEFAULT_MODEL',
]
