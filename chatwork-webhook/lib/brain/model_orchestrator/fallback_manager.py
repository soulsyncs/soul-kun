"""
フォールバック管理

フォールバックチェーン、リトライロジックを担当

設計書: docs/20_next_generation_capabilities.md セクション4.5
"""

from dataclasses import dataclass, field
from typing import Optional, List, Callable, Any, Awaitable
from datetime import datetime
from decimal import Decimal
import asyncio
import logging

from .constants import (
    Tier,
    MAX_RETRIES,
    RETRY_DELAY_BASE_SECONDS,
    RETRY_DELAY_MAX_SECONDS,
    RETRIABLE_HTTP_CODES,
    NON_RETRIABLE_HTTP_CODES,
    API_TIMEOUT_SECONDS,
    PREMIUM_API_TIMEOUT_SECONDS,
)
from .registry import ModelRegistry, ModelInfo

logger = logging.getLogger(__name__)


# =============================================================================
# データモデル
# =============================================================================

@dataclass
class FallbackAttempt:
    """フォールバック試行の記録"""
    model_id: str
    attempt_number: int
    success: bool
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class FallbackResult:
    """フォールバック実行結果"""
    success: bool
    response: Optional[str] = None
    model_used: Optional[ModelInfo] = None
    was_fallback: bool = False
    original_model_id: Optional[str] = None
    fallback_attempts: List[FallbackAttempt] = field(default_factory=list)
    total_latency_ms: int = 0
    error_message: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0


class APIError(Exception):
    """API呼び出しエラー"""
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        is_retriable: bool = False
    ):
        super().__init__(message)
        self.status_code = status_code
        self.is_retriable = is_retriable


# =============================================================================
# フォールバックマネージャー
# =============================================================================

class FallbackManager:
    """
    フォールバック管理

    - フォールバックチェーン構築
    - リトライロジック（指数バックオフ）
    - エラー判定（リトライ可能/不可）
    """

    def __init__(self, registry: ModelRegistry):
        """
        初期化

        Args:
            registry: モデルレジストリ
        """
        self._registry = registry

    # -------------------------------------------------------------------------
    # フォールバックチェーン
    # -------------------------------------------------------------------------

    def get_fallback_chain(self, primary_model: ModelInfo) -> List[ModelInfo]:
        """
        フォールバックチェーンを取得

        指定モデルのティアから始まり、同じティアの他モデル、
        次に下位ティアのモデルを順に含むチェーンを構築。

        Args:
            primary_model: メインモデル

        Returns:
            フォールバックチェーン（メインモデルは含まない）
        """
        chain = []

        # 同じティアの他モデル
        same_tier_models = self._registry.get_models_by_tier(primary_model.tier)
        for model in same_tier_models:
            if model.model_id != primary_model.model_id:
                chain.append(model)

        # 下位ティアのモデル
        if primary_model.tier == Tier.PREMIUM:
            chain.extend(self._registry.get_models_by_tier(Tier.STANDARD))
            chain.extend(self._registry.get_models_by_tier(Tier.ECONOMY))
        elif primary_model.tier == Tier.STANDARD:
            chain.extend(self._registry.get_models_by_tier(Tier.ECONOMY))

        return chain

    # -------------------------------------------------------------------------
    # エラー判定
    # -------------------------------------------------------------------------

    def is_retriable(self, error: Exception) -> bool:
        """
        エラーがリトライ可能か判定

        Args:
            error: 発生したエラー

        Returns:
            リトライ可能ならTrue
        """
        if isinstance(error, APIError):
            if error.is_retriable:
                return True
            if error.status_code in RETRIABLE_HTTP_CODES:
                return True
            if error.status_code in NON_RETRIABLE_HTTP_CODES:
                return False

        # タイムアウトはリトライ可能
        if isinstance(error, asyncio.TimeoutError):
            return True

        # 接続エラーはリトライ可能
        error_str = str(error).lower()
        if any(keyword in error_str for keyword in ["timeout", "connection", "network"]):
            return True

        return False

    def should_fallback(self, error: Exception) -> bool:
        """
        フォールバックすべきか判定

        リトライ不可能なエラーの場合はフォールバックへ。
        リトライ可能なエラーでリトライ回数を超えた場合もフォールバック。

        Args:
            error: 発生したエラー

        Returns:
            フォールバックすべきならTrue
        """
        # リトライ不可能なエラーはフォールバック
        if not self.is_retriable(error):
            return True

        return False

    # -------------------------------------------------------------------------
    # リトライ計算
    # -------------------------------------------------------------------------

    def calculate_retry_delay(self, attempt: int) -> float:
        """
        リトライ遅延を計算（指数バックオフ）

        Args:
            attempt: 試行回数（0から開始）

        Returns:
            遅延秒数
        """
        delay = RETRY_DELAY_BASE_SECONDS * (2 ** attempt)
        return min(delay, RETRY_DELAY_MAX_SECONDS)

    def get_timeout_for_model(self, model: ModelInfo) -> float:
        """
        モデルに応じたタイムアウトを取得

        Args:
            model: モデル情報

        Returns:
            タイムアウト秒数
        """
        if model.tier == Tier.PREMIUM:
            return PREMIUM_API_TIMEOUT_SECONDS
        return API_TIMEOUT_SECONDS

    # -------------------------------------------------------------------------
    # フォールバック実行
    # -------------------------------------------------------------------------

    async def execute_with_fallback(
        self,
        primary_model: ModelInfo,
        call_func: Callable[[ModelInfo], Awaitable[tuple[str, int, int]]],
        max_retries: int = MAX_RETRIES,
    ) -> FallbackResult:
        """
        フォールバック付きでAPI呼び出しを実行

        処理フロー:
        1. メインモデルで試行
        2. エラー発生時、リトライ可能ならリトライ（最大max_retries回）
        3. リトライ上限超過 or リトライ不可能エラー → フォールバックチェーンへ
        4. 全モデル失敗 → エラー返却

        Args:
            primary_model: メインモデル
            call_func: API呼び出し関数
                       (model) -> (response_text, input_tokens, output_tokens)
            max_retries: 最大リトライ回数

        Returns:
            FallbackResult
        """
        attempts: List[FallbackAttempt] = []
        total_latency_ms = 0
        original_model_id = primary_model.model_id

        # Step 1: メインモデルで試行
        logger.debug(f"Trying primary model: {primary_model.model_id}")
        success, result = await self._try_model_with_retry(
            primary_model,
            call_func,
            max_retries,
            attempts,
        )

        if success:
            response_text, input_tokens, output_tokens, latency_ms = result
            return FallbackResult(
                success=True,
                response=response_text,
                model_used=primary_model,
                was_fallback=False,
                fallback_attempts=attempts,
                total_latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        # Step 2: フォールバックチェーンへ
        fallback_chain = self.get_fallback_chain(primary_model)
        logger.info(
            f"Primary model {primary_model.model_id} failed, "
            f"trying {len(fallback_chain)} fallback models"
        )

        for fallback_model in fallback_chain:
            logger.debug(f"Trying fallback model: {fallback_model.model_id}")
            success, result = await self._try_model_with_retry(
                fallback_model,
                call_func,
                max_retries=1,  # フォールバックは1回のみ
                attempts=attempts,
            )

            if success:
                response_text, input_tokens, output_tokens, latency_ms = result
                total_latency_ms = sum(
                    a.latency_ms or 0 for a in attempts
                )
                return FallbackResult(
                    success=True,
                    response=response_text,
                    model_used=fallback_model,
                    was_fallback=True,
                    original_model_id=original_model_id,
                    fallback_attempts=attempts,
                    total_latency_ms=total_latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

        # Step 3: 全モデル失敗
        total_latency_ms = sum(a.latency_ms or 0 for a in attempts)
        last_error = attempts[-1].error_message if attempts else "Unknown error"

        logger.error(
            f"All models failed. Attempts: {len(attempts)}, "
            f"Last error: {last_error}"
        )

        return FallbackResult(
            success=False,
            was_fallback=True,
            original_model_id=original_model_id,
            fallback_attempts=attempts,
            total_latency_ms=total_latency_ms,
            error_message=f"All models failed. Last error: {last_error}",
        )

    async def _try_model_with_retry(
        self,
        model: ModelInfo,
        call_func: Callable[[ModelInfo], Awaitable[tuple[str, int, int]]],
        max_retries: int,
        attempts: List[FallbackAttempt],
    ) -> tuple[bool, Optional[tuple[str, int, int, int]]]:
        """
        リトライ付きでモデルを試行

        Args:
            model: モデル
            call_func: API呼び出し関数
            max_retries: 最大リトライ回数
            attempts: 試行記録リスト（追記される）

        Returns:
            (success, (response_text, input_tokens, output_tokens, latency_ms))
        """
        for attempt_num in range(max_retries):
            start_time = datetime.now()

            try:
                # タイムアウト付きで呼び出し
                timeout = self.get_timeout_for_model(model)
                response_text, input_tokens, output_tokens = await asyncio.wait_for(
                    call_func(model),
                    timeout=timeout,
                )

                latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                attempts.append(FallbackAttempt(
                    model_id=model.model_id,
                    attempt_number=attempt_num + 1,
                    success=True,
                    latency_ms=latency_ms,
                ))

                return True, (response_text, input_tokens, output_tokens, latency_ms)

            except Exception as e:
                latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                error_message = str(e)

                attempts.append(FallbackAttempt(
                    model_id=model.model_id,
                    attempt_number=attempt_num + 1,
                    success=False,
                    error_message=error_message,
                    latency_ms=latency_ms,
                ))

                logger.warning(
                    f"Model {model.model_id} attempt {attempt_num + 1} failed: {error_message}"
                )

                # リトライ判定
                if not self.is_retriable(e):
                    logger.debug(f"Error is not retriable, moving to fallback")
                    break

                if attempt_num < max_retries - 1:
                    delay = self.calculate_retry_delay(attempt_num)
                    logger.debug(f"Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)

        return False, None

    # -------------------------------------------------------------------------
    # ユーティリティ
    # -------------------------------------------------------------------------

    def format_attempts_summary(self, attempts: List[FallbackAttempt]) -> str:
        """
        試行記録のサマリーを生成

        Args:
            attempts: 試行記録リスト

        Returns:
            サマリー文字列
        """
        lines = [f"Total attempts: {len(attempts)}"]

        for i, attempt in enumerate(attempts, 1):
            status = "OK" if attempt.success else "FAIL"
            latency = f"{attempt.latency_ms}ms" if attempt.latency_ms else "N/A"
            error = f" - {attempt.error_message}" if attempt.error_message else ""
            lines.append(
                f"  {i}. {attempt.model_id} [{status}] {latency}{error}"
            )

        return "\n".join(lines)
