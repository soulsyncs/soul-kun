# lib/brain/monitoring.py
"""
LLM Brain モニタリングモジュール

Task #9: 本番ログ分析・エラー率確認

【目的】
- LLM Brainの本番稼働状況を監視
- エラー率、レスポンス時間、APIコストを追跡
- 異常検知と自動アラート

【メトリクス】
- error_rate: エラー率（目標: < 1%）
- avg_response_time_ms: 平均レスポンス時間（目標: < 3000ms）
- api_cost_per_request: 1リクエストあたりのAPIコスト
- confidence_distribution: 確信度の分布
- guardian_block_rate: Guardian Layerのブロック率

Author: Claude Opus 4.5
Created: 2026-01-31
"""

import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)


# =============================================================================
# 閾値定義
# =============================================================================

@dataclass
class MonitoringThresholds:
    """
    モニタリング閾値

    設計書: docs/25_llm_native_brain_architecture.md 第15章「監視・運用」
    """
    # エラー率（設計書: > 5% 警告）
    error_rate_warning: float = 0.01  # 1%（より早く検知）
    error_rate_critical: float = 0.05  # 5%（設計書準拠）

    # レスポンス時間（設計書: > 10秒 警告）
    response_time_warning_ms: int = 3000  # 3秒（より早く検知）
    response_time_critical_ms: int = 10000  # 10秒（設計書準拠）

    # APIエラー率
    api_error_rate_warning: float = 0.02  # 2%
    api_error_rate_critical: float = 0.10  # 10%

    # Guardian Layerブロック率（設計書: > 10% 警告）
    guardian_block_rate_warning: float = 0.10  # 10%（設計書準拠）
    guardian_block_rate_critical: float = 0.20  # 20%

    # 確認モード発生率（設計書: > 30% 情報）【v10.51.1追加】
    guardian_confirm_rate_info: float = 0.30  # 30%（設計書準拠）
    guardian_confirm_rate_warning: float = 0.50  # 50%

    # 確信度
    low_confidence_threshold: float = 0.5  # 50%未満は低確信度
    low_confidence_rate_warning: float = 0.20  # 20%が低確信度

    # コスト（円/リクエスト）
    cost_per_request_warning: float = 10.0  # 10円
    cost_per_request_critical: float = 20.0  # 20円

    # 日次コスト（設計書: > 5,000円 警告）【v10.51.1追加】
    daily_cost_warning: float = 5000.0  # 5,000円（設計書準拠）
    daily_cost_critical: float = 10000.0  # 10,000円


# デフォルト閾値
DEFAULT_THRESHOLDS = MonitoringThresholds()


# =============================================================================
# メトリクスデータ構造
# =============================================================================

@dataclass
class RequestMetrics:
    """1リクエストのメトリクス"""
    request_id: str
    timestamp: datetime
    response_time_ms: int
    success: bool
    output_type: str
    confidence: float
    tool_name: Optional[str] = None
    guardian_action: str = "allow"
    api_provider: str = "openrouter"
    input_tokens: int = 0
    output_tokens: int = 0
    error_type: Optional[str] = None


@dataclass
class AggregatedMetrics:
    """集計メトリクス"""
    period_start: datetime
    period_end: datetime

    # カウント
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    api_errors: int = 0

    # レスポンス時間
    total_response_time_ms: int = 0
    max_response_time_ms: int = 0
    min_response_time_ms: int = 0

    # 確信度
    total_confidence: float = 0.0
    low_confidence_count: int = 0

    # Guardian Layer
    guardian_allow_count: int = 0
    guardian_confirm_count: int = 0
    guardian_block_count: int = 0

    # コスト
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # 出力タイプ別
    output_types: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # ツール使用頻度
    tools_used: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # エラー種別
    errors_by_type: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def error_rate(self) -> float:
        """エラー率"""
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests

    @property
    def avg_response_time_ms(self) -> float:
        """平均レスポンス時間"""
        if self.total_requests == 0:
            return 0.0
        return self.total_response_time_ms / self.total_requests

    @property
    def avg_confidence(self) -> float:
        """平均確信度"""
        if self.total_requests == 0:
            return 0.0
        return self.total_confidence / self.total_requests

    @property
    def guardian_block_rate(self) -> float:
        """Guardianブロック率"""
        total = self.guardian_allow_count + self.guardian_confirm_count + self.guardian_block_count
        if total == 0:
            return 0.0
        return self.guardian_block_count / total

    @property
    def guardian_confirm_rate(self) -> float:
        """Guardian確認モード率（設計書: > 30% 情報）"""
        total = self.guardian_allow_count + self.guardian_confirm_count + self.guardian_block_count
        if total == 0:
            return 0.0
        return self.guardian_confirm_count / total

    @property
    def low_confidence_rate(self) -> float:
        """低確信度率"""
        if self.total_requests == 0:
            return 0.0
        return self.low_confidence_count / self.total_requests

    @property
    def estimated_cost_yen(self) -> float:
        """推定コスト（円）"""
        # GPT-5.2 の料金: $1.75/M入力, $14/M出力
        # 1ドル = 154円で計算
        input_cost = (self.total_input_tokens / 1_000_000) * 1.75 * 154
        output_cost = (self.total_output_tokens / 1_000_000) * 14.0 * 154
        return input_cost + output_cost

    @property
    def cost_per_request(self) -> float:
        """1リクエストあたりのコスト"""
        if self.total_requests == 0:
            return 0.0
        return self.estimated_cost_yen / self.total_requests

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "period": {
                "start": self.period_start.isoformat(),
                "end": self.period_end.isoformat(),
            },
            "counts": {
                "total": self.total_requests,
                "successful": self.successful_requests,
                "failed": self.failed_requests,
                "api_errors": self.api_errors,
            },
            "rates": {
                "error_rate": round(self.error_rate, 4),
                "guardian_block_rate": round(self.guardian_block_rate, 4),
                "guardian_confirm_rate": round(self.guardian_confirm_rate, 4),
                "low_confidence_rate": round(self.low_confidence_rate, 4),
            },
            "response_time_ms": {
                "avg": round(self.avg_response_time_ms, 1),
                "max": self.max_response_time_ms,
                "min": self.min_response_time_ms,
            },
            "confidence": {
                "avg": round(self.avg_confidence, 3),
                "low_count": self.low_confidence_count,
            },
            "guardian": {
                "allow": self.guardian_allow_count,
                "confirm": self.guardian_confirm_count,
                "block": self.guardian_block_count,
            },
            "cost": {
                "total_yen": round(self.estimated_cost_yen, 2),
                "per_request_yen": round(self.cost_per_request, 2),
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens,
            },
            "output_types": dict(self.output_types),
            "top_tools": dict(sorted(
                self.tools_used.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]),
            "errors_by_type": dict(self.errors_by_type),
        }


# =============================================================================
# LLM Brain モニター
# =============================================================================

class LLMBrainMonitor:
    """
    LLM Brainのモニタリング

    使用例:
        monitor = LLMBrainMonitor()

        # リクエスト開始
        request_id = monitor.start_request()

        # 処理実行...

        # リクエスト完了
        monitor.complete_request(
            request_id=request_id,
            success=True,
            output_type="tool_call",
            confidence=0.85,
            tool_name="chatwork_task_create",
            guardian_action="allow",
        )

        # メトリクス取得
        metrics = monitor.get_current_metrics()
        print(f"エラー率: {metrics.error_rate:.2%}")
    """

    def __init__(
        self,
        thresholds: MonitoringThresholds = DEFAULT_THRESHOLDS,
        aggregation_window_minutes: int = 5,
    ):
        """
        モニターを初期化

        Args:
            thresholds: モニタリング閾値
            aggregation_window_minutes: 集計ウィンドウ（分）
        """
        self.thresholds = thresholds
        self.aggregation_window = timedelta(minutes=aggregation_window_minutes)

        # メトリクス保存
        self._requests: Dict[str, Dict[str, Any]] = {}
        self._completed_metrics: List[RequestMetrics] = []
        self._lock = Lock()

        # 集計キャッシュ
        self._aggregated_cache: Optional[AggregatedMetrics] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = timedelta(seconds=30)

        logger.info(
            f"LLMBrainMonitor initialized: "
            f"window={aggregation_window_minutes}min"
        )

    def start_request(self, request_id: Optional[str] = None) -> str:
        """
        リクエスト開始を記録

        Args:
            request_id: リクエストID（指定しない場合は自動生成）

        Returns:
            リクエストID
        """
        import uuid
        request_id = request_id or str(uuid.uuid4())[:8]

        with self._lock:
            self._requests[request_id] = {
                "start_time": time.time(),
                "timestamp": datetime.utcnow(),
            }

        return request_id

    def complete_request(
        self,
        request_id: str,
        success: bool,
        output_type: str = "text_response",
        confidence: float = 0.0,
        tool_name: Optional[str] = None,
        guardian_action: str = "allow",
        api_provider: str = "openrouter",
        input_tokens: int = 0,
        output_tokens: int = 0,
        error_type: Optional[str] = None,
    ) -> None:
        """
        リクエスト完了を記録

        Args:
            request_id: リクエストID
            success: 成功したか
            output_type: 出力タイプ
            confidence: 確信度
            tool_name: 使用したツール名
            guardian_action: Guardian Layerのアクション
            api_provider: 使用したAPIプロバイダー
            input_tokens: 入力トークン数
            output_tokens: 出力トークン数
            error_type: エラータイプ（失敗時）
        """
        with self._lock:
            request_data = self._requests.pop(request_id, None)

            if request_data is None:
                # 開始が記録されていない場合
                response_time_ms = 0
                timestamp = datetime.utcnow()
            else:
                response_time_ms = int((time.time() - request_data["start_time"]) * 1000)
                timestamp = request_data["timestamp"]

            metrics = RequestMetrics(
                request_id=request_id,
                timestamp=timestamp,
                response_time_ms=response_time_ms,
                success=success,
                output_type=output_type,
                confidence=confidence,
                tool_name=tool_name,
                guardian_action=guardian_action,
                api_provider=api_provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                error_type=error_type,
            )

            self._completed_metrics.append(metrics)

            # 古いメトリクスを削除（1時間以上前）
            cutoff = datetime.utcnow() - timedelta(hours=1)
            self._completed_metrics = [
                m for m in self._completed_metrics
                if m.timestamp > cutoff
            ]

        # 警告チェック
        self._check_alerts(metrics)

    def get_current_metrics(
        self,
        window_minutes: Optional[int] = None,
    ) -> AggregatedMetrics:
        """
        現在のメトリクスを取得

        Args:
            window_minutes: 集計ウィンドウ（分）

        Returns:
            集計メトリクス
        """
        # キャッシュチェック
        if (
            self._aggregated_cache is not None
            and self._cache_time is not None
            and datetime.utcnow() - self._cache_time < self._cache_ttl
        ):
            return self._aggregated_cache

        window = timedelta(minutes=window_minutes) if window_minutes else self.aggregation_window
        now = datetime.utcnow()
        cutoff = now - window

        with self._lock:
            recent_metrics = [
                m for m in self._completed_metrics
                if m.timestamp > cutoff
            ]

        # 集計
        aggregated = AggregatedMetrics(
            period_start=cutoff,
            period_end=now,
        )

        for m in recent_metrics:
            aggregated.total_requests += 1

            if m.success:
                aggregated.successful_requests += 1
            else:
                aggregated.failed_requests += 1
                if m.error_type == "api_error":
                    aggregated.api_errors += 1
                if m.error_type:
                    aggregated.errors_by_type[m.error_type] += 1

            aggregated.total_response_time_ms += m.response_time_ms
            aggregated.max_response_time_ms = max(
                aggregated.max_response_time_ms,
                m.response_time_ms
            )
            if aggregated.min_response_time_ms == 0 or m.response_time_ms < aggregated.min_response_time_ms:
                aggregated.min_response_time_ms = m.response_time_ms

            aggregated.total_confidence += m.confidence
            if m.confidence < self.thresholds.low_confidence_threshold:
                aggregated.low_confidence_count += 1

            if m.guardian_action == "allow":
                aggregated.guardian_allow_count += 1
            elif m.guardian_action == "confirm":
                aggregated.guardian_confirm_count += 1
            elif m.guardian_action == "block":
                aggregated.guardian_block_count += 1

            aggregated.total_input_tokens += m.input_tokens
            aggregated.total_output_tokens += m.output_tokens

            aggregated.output_types[m.output_type] += 1

            if m.tool_name:
                aggregated.tools_used[m.tool_name] += 1

        # キャッシュ更新
        self._aggregated_cache = aggregated
        self._cache_time = now

        return aggregated

    def _check_alerts(self, metrics: RequestMetrics) -> None:
        """
        アラートチェック

        Args:
            metrics: 完了したリクエストのメトリクス
        """
        # レスポンス時間アラート
        if metrics.response_time_ms > self.thresholds.response_time_critical_ms:
            logger.warning(
                f"CRITICAL: Response time exceeded threshold: "
                f"{metrics.response_time_ms}ms > {self.thresholds.response_time_critical_ms}ms"
            )
        elif metrics.response_time_ms > self.thresholds.response_time_warning_ms:
            logger.info(
                f"WARNING: Response time high: "
                f"{metrics.response_time_ms}ms > {self.thresholds.response_time_warning_ms}ms"
            )

        # エラーアラート
        if not metrics.success and metrics.error_type == "api_error":
            logger.warning(f"API Error detected: {metrics.error_type}")

    def get_health_status(self) -> Dict[str, Any]:
        """
        ヘルスステータスを取得

        Returns:
            ヘルスステータス辞書
        """
        metrics = self.get_current_metrics()

        status = "healthy"
        issues = []

        # エラー率チェック
        if metrics.error_rate >= self.thresholds.error_rate_critical:
            status = "critical"
            issues.append(f"Error rate critical: {metrics.error_rate:.2%}")
        elif metrics.error_rate >= self.thresholds.error_rate_warning:
            status = "warning"
            issues.append(f"Error rate high: {metrics.error_rate:.2%}")

        # レスポンス時間チェック
        if metrics.avg_response_time_ms >= self.thresholds.response_time_critical_ms:
            status = "critical"
            issues.append(f"Response time critical: {metrics.avg_response_time_ms:.0f}ms")
        elif metrics.avg_response_time_ms >= self.thresholds.response_time_warning_ms:
            if status != "critical":
                status = "warning"
            issues.append(f"Response time high: {metrics.avg_response_time_ms:.0f}ms")

        # Guardian ブロック率チェック
        if metrics.guardian_block_rate >= self.thresholds.guardian_block_rate_critical:
            if status != "critical":
                status = "warning"
            issues.append(f"Guardian block rate high: {metrics.guardian_block_rate:.2%}")

        # Guardian 確認モード率チェック（設計書: > 30% 情報）
        if metrics.guardian_confirm_rate >= self.thresholds.guardian_confirm_rate_warning:
            if status not in ["critical", "warning"]:
                status = "warning"
            issues.append(f"Guardian confirm rate very high: {metrics.guardian_confirm_rate:.2%}")
        elif metrics.guardian_confirm_rate >= self.thresholds.guardian_confirm_rate_info:
            issues.append(f"Guardian confirm rate high (info): {metrics.guardian_confirm_rate:.2%}")

        return {
            "status": status,
            "issues": issues,
            "metrics": metrics.to_dict(),
            "checked_at": datetime.utcnow().isoformat(),
        }


# =============================================================================
# グローバルインスタンス
# =============================================================================

_monitor: Optional[LLMBrainMonitor] = None


def get_monitor() -> LLMBrainMonitor:
    """
    モニターインスタンスを取得（シングルトン）

    Returns:
        LLMBrainMonitor
    """
    global _monitor
    if _monitor is None:
        _monitor = LLMBrainMonitor()
    return _monitor


def start_request(request_id: Optional[str] = None) -> str:
    """リクエスト開始を記録（便利関数）"""
    return get_monitor().start_request(request_id)


def complete_request(**kwargs) -> None:
    """リクエスト完了を記録（便利関数）"""
    get_monitor().complete_request(**kwargs)


def get_health_status() -> Dict[str, Any]:
    """ヘルスステータスを取得（便利関数）"""
    return get_monitor().get_health_status()


# =============================================================================
# レスポンス時間最適化ユーティリティ
# =============================================================================

class ResponseTimeOptimizer:
    """
    レスポンス時間最適化

    Task #10: レスポンス時間最適化

    【最適化項目】
    - コンテキストキャッシュ（同一ユーザー・短時間内の連続リクエスト）
    - タイムアウト設定（各フェーズごと）
    - 早期終了条件（明確な意図の場合）

    【目標】
    - 平均レスポンス時間: 3秒以下
    - 95パーセンタイル: 5秒以下
    - タイムアウト: 30秒
    """

    # キャッシュTTL（秒）
    CONTEXT_CACHE_TTL_SECONDS = 30

    # フェーズ別タイムアウト（秒）
    PHASE_TIMEOUTS = {
        "context_building": 5.0,
        "llm_processing": 20.0,
        "guardian_check": 2.0,
        "tool_execution": 10.0,
    }

    # 早期終了の確信度閾値
    EARLY_EXIT_CONFIDENCE = 0.95

    def __init__(self):
        self._context_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._lock = Lock()

    def get_cached_context(
        self,
        user_id: str,
        room_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        キャッシュされたコンテキストを取得

        Args:
            user_id: ユーザーID
            room_id: ルームID

        Returns:
            キャッシュされたコンテキスト（なければNone）
        """
        cache_key = f"{user_id}:{room_id}"

        with self._lock:
            if cache_key not in self._context_cache:
                return None

            timestamp = self._cache_timestamps.get(cache_key, 0)
            if time.time() - timestamp > self.CONTEXT_CACHE_TTL_SECONDS:
                # TTL超過
                del self._context_cache[cache_key]
                del self._cache_timestamps[cache_key]
                return None

            return self._context_cache[cache_key]

    def set_cached_context(
        self,
        user_id: str,
        room_id: str,
        context: Dict[str, Any],
    ) -> None:
        """
        コンテキストをキャッシュ

        Args:
            user_id: ユーザーID
            room_id: ルームID
            context: キャッシュするコンテキスト
        """
        cache_key = f"{user_id}:{room_id}"

        with self._lock:
            self._context_cache[cache_key] = context
            self._cache_timestamps[cache_key] = time.time()

            # キャッシュサイズ制限（最大100エントリ）
            if len(self._context_cache) > 100:
                # 最古のエントリを削除
                oldest_key = min(
                    self._cache_timestamps.keys(),
                    key=lambda k: self._cache_timestamps[k]
                )
                del self._context_cache[oldest_key]
                del self._cache_timestamps[oldest_key]

    def get_phase_timeout(self, phase: str) -> float:
        """
        フェーズ別タイムアウトを取得

        Args:
            phase: フェーズ名

        Returns:
            タイムアウト秒数
        """
        return self.PHASE_TIMEOUTS.get(phase, 10.0)

    def should_early_exit(self, confidence: float) -> bool:
        """
        早期終了すべきか判定

        Args:
            confidence: 確信度

        Returns:
            早期終了すべきならTrue
        """
        return confidence >= self.EARLY_EXIT_CONFIDENCE

    def invalidate_cache(self, user_id: str, room_id: str) -> None:
        """
        キャッシュを無効化

        Args:
            user_id: ユーザーID
            room_id: ルームID
        """
        cache_key = f"{user_id}:{room_id}"

        with self._lock:
            if cache_key in self._context_cache:
                del self._context_cache[cache_key]
            if cache_key in self._cache_timestamps:
                del self._cache_timestamps[cache_key]


# グローバル最適化インスタンス
_optimizer: Optional[ResponseTimeOptimizer] = None


def get_optimizer() -> ResponseTimeOptimizer:
    """最適化インスタンスを取得"""
    global _optimizer
    if _optimizer is None:
        _optimizer = ResponseTimeOptimizer()
    return _optimizer
