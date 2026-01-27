"""
Model Orchestrator メインクラス

全AI呼び出しを統括する統一インターフェース

設計書: docs/20_next_generation_capabilities.md セクション4
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Callable, Awaitable, Any, Dict
import logging
import os

from sqlalchemy.engine import Engine
import httpx

from .constants import (
    Tier,
    FEATURE_FLAG_NAME,
    API_TIMEOUT_SECONDS,
)
from .registry import ModelRegistry, ModelInfo
from .model_selector import ModelSelector, ModelSelection
from .cost_manager import CostManager, CostCheckResult, CostAction, CostEstimate
from .fallback_manager import FallbackManager, FallbackResult
from .usage_logger import UsageLogger

logger = logging.getLogger(__name__)


# =============================================================================
# データモデル
# =============================================================================

@dataclass
class OrchestratorResult:
    """Orchestrator実行結果"""
    success: bool
    content: Optional[str] = None

    # モデル情報
    model_used: Optional[ModelInfo] = None
    tier_used: Optional[Tier] = None
    selection_reason: Optional[str] = None

    # トークン・コスト
    input_tokens: int = 0
    output_tokens: int = 0
    cost_jpy: Decimal = Decimal("0")

    # パフォーマンス
    latency_ms: int = 0

    # フォールバック情報
    was_fallback: bool = False
    original_model_id: Optional[str] = None
    fallback_attempts: int = 0

    # コストチェック結果
    cost_action: Optional[CostAction] = None
    cost_message: Optional[str] = None

    # エラー
    error_message: Optional[str] = None


@dataclass
class OrchestratorConfig:
    """Orchestrator設定"""
    enable_cost_management: bool = True
    enable_fallback: bool = True
    enable_logging: bool = True
    dry_run: bool = False  # True: 実際のAPI呼び出しをスキップ


# =============================================================================
# Model Orchestrator
# =============================================================================

class ModelOrchestrator:
    """
    Model Orchestrator

    全AI呼び出しを統括する統一インターフェース。

    機能:
    1. タスクタイプに応じたモデル選択
    2. コスト管理（閾値監視、相談判定）
    3. フォールバック制御
    4. 利用ログ記録

    使用例:
        orchestrator = ModelOrchestrator(pool, org_id, api_key)
        result = await orchestrator.call(
            prompt="質問に回答して",
            task_type="conversation",
        )
        print(result.content)
    """

    def __init__(
        self,
        pool: Engine,
        organization_id: str,
        api_key: Optional[str] = None,
        config: Optional[OrchestratorConfig] = None,
    ):
        """
        初期化

        Args:
            pool: SQLAlchemyのエンジン（DB接続プール）
            organization_id: 組織ID
            api_key: OpenRouter API Key（省略時は環境変数から取得）
            config: Orchestrator設定
        """
        self._pool = pool
        self._organization_id = organization_id
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self._config = config or OrchestratorConfig()

        # サブコンポーネント
        self._registry = ModelRegistry(pool)
        self._selector = ModelSelector(self._registry)
        self._cost_manager = CostManager(pool, organization_id)
        self._fallback_manager = FallbackManager(self._registry)
        self._usage_logger = UsageLogger(pool, organization_id)

        # 初期化
        if self._config.enable_cost_management:
            self._cost_manager.ensure_settings_exist()

    # -------------------------------------------------------------------------
    # メインAPI
    # -------------------------------------------------------------------------

    async def call(
        self,
        prompt: str,
        task_type: str = "general",
        tier_override: Optional[Tier] = None,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        room_id: Optional[str] = None,
        user_id: Optional[str] = None,
        expected_output_tokens: Optional[int] = None,
    ) -> OrchestratorResult:
        """
        AIモデルを呼び出す

        処理フロー:
        1. モデル選択（タスクタイプ → ティア → モデル）
        2. コストチェック（閾値判定、相談判定）
        3. フォールバック付き実行
        4. コスト計算・記録
        5. 利用ログ記録
        6. 月次サマリー更新

        Args:
            prompt: プロンプト文字列
            task_type: タスクタイプ（e.g., "conversation", "ceo_learning"）
            tier_override: ティア直接指定（指定時は調整スキップ）
            max_tokens: 最大出力トークン数
            temperature: 温度パラメータ
            room_id: ルームID（ログ用）
            user_id: ユーザーID（ログ用）
            expected_output_tokens: 期待される出力トークン数（コスト推定用）

        Returns:
            OrchestratorResult: 実行結果
        """
        start_time = datetime.now()

        try:
            # Step 1: モデル選択
            selection = self._selector.select(
                task_type=task_type,
                message=prompt,
                tier_override=tier_override,
            )
            logger.debug(
                f"Model selected: {selection.model.display_name} "
                f"(tier={selection.tier.value}, reason={selection.reason})"
            )

            # Step 2: コストチェック
            cost_estimate = None
            cost_check = None

            if self._config.enable_cost_management:
                cost_estimate = self._cost_manager.estimate_cost(
                    model=selection.model,
                    prompt=prompt,
                    expected_output_tokens=expected_output_tokens,
                )
                cost_check = self._cost_manager.check_cost(
                    estimated_cost_jpy=cost_estimate.cost_jpy,
                    model=selection.model,
                )

                # コストアクションに応じた処理
                if cost_check.action == CostAction.BLOCK:
                    return OrchestratorResult(
                        success=False,
                        error_message=cost_check.message,
                        cost_action=cost_check.action,
                        cost_message=cost_check.message,
                        tier_used=selection.tier,
                        selection_reason=selection.reason,
                    )

            # Step 3: フォールバック付き実行
            if self._config.dry_run:
                # Dry run: 実際のAPI呼び出しをスキップ
                result = FallbackResult(
                    success=True,
                    response="[DRY RUN] This is a simulated response.",
                    model_used=selection.model,
                    was_fallback=False,
                    input_tokens=cost_estimate.input_tokens if cost_estimate else 100,
                    output_tokens=cost_estimate.output_tokens if cost_estimate else 50,
                )
            else:
                # 実際のAPI呼び出し
                async def call_api(model: ModelInfo) -> tuple[str, int, int]:
                    return await self._call_openrouter(
                        model=model,
                        prompt=prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )

                if self._config.enable_fallback:
                    result = await self._fallback_manager.execute_with_fallback(
                        primary_model=selection.model,
                        call_func=call_api,
                    )
                else:
                    # フォールバック無効時は直接呼び出し
                    try:
                        response, input_tokens, output_tokens = await call_api(selection.model)
                        result = FallbackResult(
                            success=True,
                            response=response,
                            model_used=selection.model,
                            was_fallback=False,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                        )
                    except Exception as e:
                        result = FallbackResult(
                            success=False,
                            error_message=str(e),
                            model_used=selection.model,
                        )

            # 実行時間
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Step 4: 実績コスト計算
            actual_cost_jpy = Decimal("0")
            if result.success and result.model_used:
                actual_cost_jpy = self._cost_manager.calculate_actual_cost(
                    model=result.model_used,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )

            # Step 5: 利用ログ記録
            if self._config.enable_logging:
                self._usage_logger.log_usage(
                    model_id=result.model_used.model_id if result.model_used else selection.model.model_id,
                    task_type=task_type,
                    tier=result.model_used.tier if result.model_used else selection.tier,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_jpy=actual_cost_jpy,
                    latency_ms=latency_ms,
                    success=result.success,
                    room_id=room_id,
                    user_id=user_id,
                    was_fallback=result.was_fallback,
                    original_model_id=result.original_model_id,
                    fallback_reason=result.error_message if result.was_fallback else None,
                    fallback_attempt=len(result.fallback_attempts),
                    error_message=result.error_message if not result.success else None,
                    request_content=prompt[:500],  # ハッシュ用に先頭500文字
                )

            # Step 6: 月次サマリー更新
            if self._config.enable_cost_management and result.success:
                tier_used = result.model_used.tier if result.model_used else selection.tier
                self._cost_manager.update_monthly_summary(
                    cost_jpy=actual_cost_jpy,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    tier=tier_used,
                    was_fallback=result.was_fallback,
                    success=result.success,
                )

            # 結果を返す
            return OrchestratorResult(
                success=result.success,
                content=result.response,
                model_used=result.model_used,
                tier_used=result.model_used.tier if result.model_used else selection.tier,
                selection_reason=selection.reason,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_jpy=actual_cost_jpy,
                latency_ms=latency_ms,
                was_fallback=result.was_fallback,
                original_model_id=result.original_model_id,
                fallback_attempts=len(result.fallback_attempts),
                cost_action=cost_check.action if cost_check else None,
                cost_message=cost_check.message if cost_check else None,
                error_message=result.error_message,
            )

        except Exception as e:
            logger.error(f"Orchestrator call failed: {e}")
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            return OrchestratorResult(
                success=False,
                error_message=str(e),
                latency_ms=latency_ms,
            )

    # -------------------------------------------------------------------------
    # OpenRouter API呼び出し
    # -------------------------------------------------------------------------

    async def _call_openrouter(
        self,
        model: ModelInfo,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.7,
    ) -> tuple[str, int, int]:
        """
        OpenRouter APIを呼び出す

        Args:
            model: モデル情報
            prompt: プロンプト
            max_tokens: 最大出力トークン数
            temperature: 温度

        Returns:
            (response_text, input_tokens, output_tokens)
        """
        if not self._api_key:
            raise RuntimeError("OpenRouter API key not configured")

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()

            data = response.json()

            # レスポンス解析
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

            return content, input_tokens, output_tokens

    # -------------------------------------------------------------------------
    # ユーティリティ
    # -------------------------------------------------------------------------

    def get_available_models(self) -> Dict[str, Any]:
        """
        利用可能なモデル一覧を取得

        Returns:
            モデル情報
        """
        return self._registry.get_model_stats()

    def explain_selection(self, task_type: str, message: Optional[str] = None) -> str:
        """
        モデル選択の説明を取得（デバッグ用）

        Args:
            task_type: タスクタイプ
            message: ユーザーメッセージ

        Returns:
            説明文
        """
        return self._selector.explain_selection(task_type, message)

    @staticmethod
    def is_enabled() -> bool:
        """
        Model Orchestratorが有効か確認

        Returns:
            有効ならTrue
        """
        return os.environ.get(FEATURE_FLAG_NAME, "false").lower() == "true"


# =============================================================================
# ファクトリー関数
# =============================================================================

def create_orchestrator(
    pool: Engine,
    organization_id: str,
    api_key: Optional[str] = None,
    enable_cost_management: bool = True,
    enable_fallback: bool = True,
    enable_logging: bool = True,
    dry_run: bool = False,
) -> ModelOrchestrator:
    """
    Model Orchestratorを作成するファクトリー関数

    Args:
        pool: SQLAlchemyのエンジン
        organization_id: 組織ID
        api_key: OpenRouter API Key
        enable_cost_management: コスト管理を有効化
        enable_fallback: フォールバックを有効化
        enable_logging: ログ記録を有効化
        dry_run: Dry runモード

    Returns:
        ModelOrchestrator
    """
    config = OrchestratorConfig(
        enable_cost_management=enable_cost_management,
        enable_fallback=enable_fallback,
        enable_logging=enable_logging,
        dry_run=dry_run,
    )

    return ModelOrchestrator(
        pool=pool,
        organization_id=organization_id,
        api_key=api_key,
        config=config,
    )
