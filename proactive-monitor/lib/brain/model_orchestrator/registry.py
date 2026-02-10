"""
モデルレジストリ

AI モデルの情報をDBから取得・管理するリポジトリ層

設計書: docs/20_next_generation_capabilities.md セクション4
10の鉄則:
- #1: 全クエリにorganization_idフィルタ（このテーブルはマスタなので不要）
- #9: SQLインジェクション対策（パラメータ化クエリ）
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any, cast
from uuid import UUID
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .constants import Tier, DEFAULT_USD_TO_JPY_RATE

logger = logging.getLogger(__name__)


# =============================================================================
# データモデル
# =============================================================================

@dataclass
class ModelInfo:
    """AIモデル情報"""
    id: UUID
    model_id: str              # e.g., "anthropic/claude-opus-4-5-20251101"
    provider: str              # e.g., "anthropic"
    display_name: str          # e.g., "Claude Opus 4.5"
    tier: Tier
    capabilities: List[str]    # e.g., ["text", "vision", "code"]
    input_cost_per_1m_usd: Decimal
    output_cost_per_1m_usd: Decimal
    max_context_tokens: int
    max_output_tokens: int
    fallback_priority: int
    is_active: bool
    is_default_for_tier: bool
    created_at: datetime
    updated_at: datetime

    def calculate_cost_jpy(
        self,
        input_tokens: int,
        output_tokens: int,
        usd_to_jpy_rate: Decimal = DEFAULT_USD_TO_JPY_RATE
    ) -> Decimal:
        """
        コストを円換算で計算

        Args:
            input_tokens: 入力トークン数
            output_tokens: 出力トークン数
            usd_to_jpy_rate: USD→JPY換算レート

        Returns:
            コスト（円）
        """
        input_cost_usd = (Decimal(input_tokens) / Decimal(1_000_000)) * self.input_cost_per_1m_usd
        output_cost_usd = (Decimal(output_tokens) / Decimal(1_000_000)) * self.output_cost_per_1m_usd
        total_usd = input_cost_usd + output_cost_usd
        return total_usd * usd_to_jpy_rate


# =============================================================================
# モデルレジストリ
# =============================================================================

class ModelRegistry:
    """
    AIモデルレジストリ

    ai_model_registry テーブルへの読み取り操作を提供します。
    メモリキャッシュ付き（5分TTL）。
    """

    # キャッシュTTL（秒）
    CACHE_TTL_SECONDS = 300  # 5分

    def __init__(self, pool: Engine):
        """
        初期化

        Args:
            pool: SQLAlchemyのエンジン（DB接続プール）
        """
        self._pool = pool
        self._cache: Dict[str, Any] = {}
        self._cache_timestamp: Optional[datetime] = None

    # -------------------------------------------------------------------------
    # キャッシュ管理
    # -------------------------------------------------------------------------

    def _is_cache_valid(self) -> bool:
        """キャッシュが有効か確認"""
        if self._cache_timestamp is None:
            return False
        elapsed = (datetime.now() - self._cache_timestamp).total_seconds()
        return elapsed < self.CACHE_TTL_SECONDS

    def _invalidate_cache(self) -> None:
        """キャッシュを無効化"""
        self._cache = {}
        self._cache_timestamp = None

    def refresh_cache(self) -> None:
        """キャッシュを強制リフレッシュ"""
        self._invalidate_cache()
        self.get_all_models()

    # -------------------------------------------------------------------------
    # Read Operations
    # -------------------------------------------------------------------------

    def get_all_models(self) -> List[ModelInfo]:
        """
        全アクティブモデルを取得

        Returns:
            モデル情報のリスト
        """
        cache_key = "all_models"

        if self._is_cache_valid() and cache_key in self._cache:
            return cast(List[ModelInfo], self._cache[cache_key])

        query = text("""
            SELECT
                id,
                model_id,
                provider,
                display_name,
                tier,
                capabilities,
                input_cost_per_1m_usd,
                output_cost_per_1m_usd,
                max_context_tokens,
                max_output_tokens,
                fallback_priority,
                is_active,
                is_default_for_tier,
                created_at,
                updated_at
            FROM ai_model_registry
            WHERE is_active = TRUE
            ORDER BY tier, fallback_priority
        """)

        try:
            with self._pool.connect() as conn:
                result = conn.execute(query)
                rows = result.fetchall()

                models = [self._row_to_model_info(row) for row in rows]

                # キャッシュに保存
                self._cache[cache_key] = models
                self._cache_timestamp = datetime.now()

                return models

        except Exception as e:
            logger.error(f"Failed to get all models: {type(e).__name__}")
            raise

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        """
        モデルIDでモデル情報を取得

        Args:
            model_id: モデルID（e.g., "anthropic/claude-opus-4-5-20251101"）

        Returns:
            モデル情報（見つからない場合はNone）
        """
        cache_key = f"model:{model_id}"

        if self._is_cache_valid() and cache_key in self._cache:
            return cast(Optional[ModelInfo], self._cache[cache_key])

        query = text("""
            SELECT
                id,
                model_id,
                provider,
                display_name,
                tier,
                capabilities,
                input_cost_per_1m_usd,
                output_cost_per_1m_usd,
                max_context_tokens,
                max_output_tokens,
                fallback_priority,
                is_active,
                is_default_for_tier,
                created_at,
                updated_at
            FROM ai_model_registry
            WHERE model_id = :model_id
              AND is_active = TRUE
        """)

        try:
            with self._pool.connect() as conn:
                result = conn.execute(query, {"model_id": model_id})
                row = result.fetchone()

                if row is None:
                    return None

                model = self._row_to_model_info(row)

                # キャッシュに保存
                self._cache[cache_key] = model

                return model

        except Exception as e:
            logger.error(f"Failed to get model {model_id}: {type(e).__name__}")
            raise

    def get_models_by_tier(self, tier: Tier) -> List[ModelInfo]:
        """
        ティアでモデルを取得（フォールバック優先順）

        Args:
            tier: ティア

        Returns:
            モデル情報のリスト（fallback_priority順）
        """
        cache_key = f"tier:{tier.value}"

        if self._is_cache_valid() and cache_key in self._cache:
            return cast(List[ModelInfo], self._cache[cache_key])

        query = text("""
            SELECT
                id,
                model_id,
                provider,
                display_name,
                tier,
                capabilities,
                input_cost_per_1m_usd,
                output_cost_per_1m_usd,
                max_context_tokens,
                max_output_tokens,
                fallback_priority,
                is_active,
                is_default_for_tier,
                created_at,
                updated_at
            FROM ai_model_registry
            WHERE tier = :tier
              AND is_active = TRUE
            ORDER BY fallback_priority
        """)

        try:
            with self._pool.connect() as conn:
                result = conn.execute(query, {"tier": tier.value})
                rows = result.fetchall()

                models = [self._row_to_model_info(row) for row in rows]

                # キャッシュに保存
                self._cache[cache_key] = models

                return models

        except Exception as e:
            logger.error(f"Failed to get models by tier {tier}: {type(e).__name__}")
            raise

    def get_default_model_for_tier(self, tier: Tier) -> Optional[ModelInfo]:
        """
        ティアのデフォルトモデルを取得

        Args:
            tier: ティア

        Returns:
            デフォルトモデル（見つからない場合はNone）
        """
        cache_key = f"default:{tier.value}"

        if self._is_cache_valid() and cache_key in self._cache:
            return cast(Optional[ModelInfo], self._cache[cache_key])

        query = text("""
            SELECT
                id,
                model_id,
                provider,
                display_name,
                tier,
                capabilities,
                input_cost_per_1m_usd,
                output_cost_per_1m_usd,
                max_context_tokens,
                max_output_tokens,
                fallback_priority,
                is_active,
                is_default_for_tier,
                created_at,
                updated_at
            FROM ai_model_registry
            WHERE tier = :tier
              AND is_active = TRUE
              AND is_default_for_tier = TRUE
            LIMIT 1
        """)

        try:
            with self._pool.connect() as conn:
                result = conn.execute(query, {"tier": tier.value})
                row = result.fetchone()

                if row is None:
                    # デフォルトがない場合は最初のモデルを返す
                    models = self.get_models_by_tier(tier)
                    return models[0] if models else None

                model = self._row_to_model_info(row)

                # キャッシュに保存
                self._cache[cache_key] = model

                return model

        except Exception as e:
            logger.error(f"Failed to get default model for tier {tier}: {type(e).__name__}")
            raise

    def get_fallback_chain(self, tier: Tier) -> List[ModelInfo]:
        """
        フォールバックチェーンを取得

        指定ティアのモデル + 下位ティアのモデルを
        fallback_priority順に返します。

        Args:
            tier: 起点ティア

        Returns:
            フォールバックチェーン（モデルのリスト）
        """
        chain = []

        # 指定ティアのモデル
        chain.extend(self.get_models_by_tier(tier))

        # 下位ティアのモデルを追加
        if tier == Tier.PREMIUM:
            chain.extend(self.get_models_by_tier(Tier.STANDARD))
            chain.extend(self.get_models_by_tier(Tier.ECONOMY))
        elif tier == Tier.STANDARD:
            chain.extend(self.get_models_by_tier(Tier.ECONOMY))

        return chain

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _row_to_model_info(self, row) -> ModelInfo:
        """DBの行をModelInfoに変換"""
        # capabilitiesがJSON文字列の場合はパース
        capabilities = row[5]
        if isinstance(capabilities, str):
            import json
            capabilities = json.loads(capabilities)

        return ModelInfo(
            id=row[0],
            model_id=row[1],
            provider=row[2],
            display_name=row[3],
            tier=Tier(row[4]),
            capabilities=capabilities,
            input_cost_per_1m_usd=Decimal(str(row[6])),
            output_cost_per_1m_usd=Decimal(str(row[7])),
            max_context_tokens=row[8] or 128000,
            max_output_tokens=row[9] or 4096,
            fallback_priority=row[10] or 100,
            is_active=row[11],
            is_default_for_tier=row[12],
            created_at=row[13],
            updated_at=row[14],
        )

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    def get_model_stats(self) -> Dict[str, Any]:
        """
        モデル統計を取得

        Returns:
            統計情報
        """
        models = self.get_all_models()

        by_tier: Dict[str, int] = {}
        by_provider: Dict[str, int] = {}

        for model in models:
            # ティア別カウント
            tier_key = model.tier.value
            if tier_key not in by_tier:
                by_tier[tier_key] = 0
            by_tier[tier_key] += 1

            # プロバイダー別カウント
            if model.provider not in by_provider:
                by_provider[model.provider] = 0
            by_provider[model.provider] += 1

        return {
            "total_models": len(models),
            "by_tier": by_tier,
            "by_provider": by_provider,
        }
