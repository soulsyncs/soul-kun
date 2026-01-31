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


# =============================================================================
# DB連携モニタリング（設計書15.2ダッシュボード対応）
# =============================================================================

@dataclass
class DailyDBMetrics:
    """
    日次DBメトリクス（設計書15.2のダッシュボード用）

    brain_daily_metrics テーブルから取得するメトリクス。
    リアルタイムの AggregatedMetrics とは異なり、DBに永続化されたデータを使用。
    """
    # 基本情報
    organization_id: str
    metric_date: datetime

    # 会話統計
    total_conversations: int = 0
    unique_users: int = 0

    # 応答時間
    avg_response_time_ms: int = 0
    p50_response_time_ms: int = 0
    p95_response_time_ms: int = 0
    p99_response_time_ms: int = 0
    max_response_time_ms: int = 0

    # 確信度
    avg_confidence: float = 0.0
    min_confidence: float = 0.0

    # 出力タイプ別
    tool_call_count: int = 0
    text_response_count: int = 0
    clarification_count: int = 0

    # Guardian判定
    allow_count: int = 0
    confirm_count: int = 0
    block_count: int = 0

    # 実行結果
    success_count: int = 0
    error_count: int = 0

    # コスト
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_yen: float = 0.0

    # 遅いリクエスト
    slow_request_count: int = 0

    @property
    def error_rate(self) -> float:
        """エラー率（%）"""
        if self.total_conversations == 0:
            return 0.0
        return (self.error_count / self.total_conversations) * 100

    @property
    def confirm_rate(self) -> float:
        """確認モード発生率（%）"""
        if self.total_conversations == 0:
            return 0.0
        return (self.confirm_count / self.total_conversations) * 100

    @property
    def block_rate(self) -> float:
        """ブロック発生率（%）"""
        if self.total_conversations == 0:
            return 0.0
        return (self.block_count / self.total_conversations) * 100

    def check_alerts(self) -> List[Dict[str, Any]]:
        """
        設計書15.1の閾値に基づくアラートをチェック

        Returns:
            アラートのリスト
        """
        alerts = []
        thresholds = DEFAULT_THRESHOLDS

        # LLM応答時間 > 10秒
        if self.avg_response_time_ms > thresholds.response_time_critical_ms:
            alerts.append({
                "level": "warning",
                "category": "response_time",
                "message": f"LLM応答時間が閾値を超えています: {self.avg_response_time_ms}ms",
                "value": self.avg_response_time_ms,
                "threshold": thresholds.response_time_critical_ms,
            })

        # エラー率 > 5%
        if self.error_rate > thresholds.error_rate_critical * 100:
            alerts.append({
                "level": "warning",
                "category": "error_rate",
                "message": f"エラー率が閾値を超えています: {self.error_rate:.1f}%",
                "value": self.error_rate,
                "threshold": thresholds.error_rate_critical * 100,
            })

        # 確認モード発生率 > 30%
        if self.confirm_rate > thresholds.guardian_confirm_rate_info * 100:
            alerts.append({
                "level": "info",
                "category": "confirm_rate",
                "message": f"確認モード発生率が高くなっています: {self.confirm_rate:.1f}%",
                "value": self.confirm_rate,
                "threshold": thresholds.guardian_confirm_rate_info * 100,
            })

        # ブロック発生率 > 10%
        if self.block_rate > thresholds.guardian_block_rate_warning * 100:
            alerts.append({
                "level": "warning",
                "category": "block_rate",
                "message": f"ブロック発生率が閾値を超えています: {self.block_rate:.1f}%",
                "value": self.block_rate,
                "threshold": thresholds.guardian_block_rate_warning * 100,
            })

        # 日次コスト > 5,000円
        if self.total_cost_yen > thresholds.daily_cost_warning:
            alerts.append({
                "level": "warning",
                "category": "daily_cost",
                "message": f"日次コストが閾値を超えています: ¥{self.total_cost_yen:,.0f}",
                "value": self.total_cost_yen,
                "threshold": thresholds.daily_cost_warning,
            })

        return alerts

    def to_dashboard_string(self) -> str:
        """
        設計書15.2形式のダッシュボード文字列を生成

        【ソウルくん脳モニター】
        今日の統計:
        - 総会話数: 150
        - 平均応答時間: 2.3秒
        - 確信度平均: 0.85
        - 確認モード: 12回 (8%)
        - ブロック: 2回 (1.3%)
        """
        avg_time_sec = self.avg_response_time_ms / 1000 if self.avg_response_time_ms else 0
        date_str = self.metric_date.strftime("%Y-%m-%d") if isinstance(self.metric_date, datetime) else str(self.metric_date)

        dashboard = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【ソウルくん脳モニター】 {date_str}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 今日の統計:
  - 総会話数: {self.total_conversations:,}
  - ユニークユーザー: {self.unique_users:,}
  - 平均応答時間: {avg_time_sec:.1f}秒
  - 確信度平均: {self.avg_confidence:.2f}

🛡️ Guardian判定:
  - 許可 (allow): {self.allow_count:,}回
  - 確認 (confirm): {self.confirm_count:,}回 ({self.confirm_rate:.1f}%)
  - ブロック (block): {self.block_count:,}回 ({self.block_rate:.1f}%)

✅ 実行結果:
  - 成功: {self.success_count:,}回
  - エラー: {self.error_count:,}回 ({self.error_rate:.1f}%)
  - 遅延リクエスト (>10秒): {self.slow_request_count:,}回

💰 コスト:
  - 本日: ¥{self.total_cost_yen:,.0f}
  - 入力トークン: {self.total_input_tokens:,}
  - 出力トークン: {self.total_output_tokens:,}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        # アラートがあれば追加
        alerts = self.check_alerts()
        if alerts:
            dashboard += "\n🚨 アラート:\n"
            for alert in alerts:
                emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(alert["level"], "❓")
                dashboard += f"  {emoji} [{alert['level'].upper()}] {alert['message']}\n"
            dashboard += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

        return dashboard


class DBBrainMonitor:
    """
    DB連携 Brain モニター

    brain_observability_logs テーブルからメトリクスを取得して
    設計書15.2形式のダッシュボードを表示する。

    Usage:
        monitor = DBBrainMonitor(pool=db_pool)

        # 今日のメトリクスを取得
        metrics = await monitor.get_daily_metrics(org_id, date.today())
        print(metrics.to_dashboard_string())

        # アラートをチェック
        alerts = metrics.check_alerts()
    """

    def __init__(self, pool=None):
        """
        初期化

        Args:
            pool: データベース接続プール（asyncpg）
        """
        self.pool = pool

    async def get_daily_metrics(
        self,
        organization_id: str,
        target_date: datetime,
    ) -> DailyDBMetrics:
        """
        日次メトリクスを取得

        Args:
            organization_id: 組織ID
            target_date: 対象日

        Returns:
            DailyDBMetrics
        """
        if not self.pool:
            logger.warning("No pool available, returning empty metrics")
            return DailyDBMetrics(
                organization_id=organization_id,
                metric_date=target_date,
            )

        try:
            async with self.pool.acquire() as conn:
                # まず集計テーブルを確認
                row = await conn.fetchrow(
                    """
                    SELECT * FROM brain_daily_metrics
                    WHERE organization_id = $1 AND metric_date = $2
                    """,
                    organization_id,
                    target_date.date() if isinstance(target_date, datetime) else target_date,
                )

                if row:
                    return self._row_to_metrics(row, organization_id, target_date)

                # なければリアルタイム集計
                return await self._aggregate_realtime(conn, organization_id, target_date)

        except Exception as e:
            logger.error(f"Failed to get daily metrics: {e}")
            return DailyDBMetrics(
                organization_id=organization_id,
                metric_date=target_date,
            )

    async def _aggregate_realtime(
        self,
        conn,
        organization_id: str,
        target_date: datetime,
    ) -> DailyDBMetrics:
        """リアルタイム集計"""
        date_value = target_date.date() if isinstance(target_date, datetime) else target_date

        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as total_conversations,
                COUNT(DISTINCT user_id) as unique_users,
                COALESCE(AVG(total_response_time_ms)::INTEGER, 0) as avg_response_time_ms,
                COALESCE(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_response_time_ms)::INTEGER, 0) as p50_response_time_ms,
                COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_response_time_ms)::INTEGER, 0) as p95_response_time_ms,
                COALESCE(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY total_response_time_ms)::INTEGER, 0) as p99_response_time_ms,
                COALESCE(MAX(total_response_time_ms), 0) as max_response_time_ms,
                COALESCE(AVG(confidence_overall), 0) as avg_confidence,
                COALESCE(MIN(confidence_overall), 0) as min_confidence,
                COUNT(*) FILTER (WHERE output_type = 'tool_call') as tool_call_count,
                COUNT(*) FILTER (WHERE output_type = 'text_response') as text_response_count,
                COUNT(*) FILTER (WHERE output_type = 'clarification_needed') as clarification_count,
                COUNT(*) FILTER (WHERE guardian_action = 'allow') as allow_count,
                COUNT(*) FILTER (WHERE guardian_action = 'confirm') as confirm_count,
                COUNT(*) FILTER (WHERE guardian_action = 'block') as block_count,
                COUNT(*) FILTER (WHERE execution_success = TRUE) as success_count,
                COUNT(*) FILTER (WHERE execution_success = FALSE) as error_count,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                COALESCE(SUM(estimated_cost_yen), 0) as total_cost_yen,
                COUNT(*) FILTER (WHERE total_response_time_ms > 10000) as slow_request_count
            FROM brain_observability_logs
            WHERE organization_id = $1
              AND DATE(created_at) = $2
              AND environment = 'production'
            """,
            organization_id,
            date_value,
        )

        if not row:
            return DailyDBMetrics(
                organization_id=organization_id,
                metric_date=target_date,
            )

        return DailyDBMetrics(
            organization_id=organization_id,
            metric_date=target_date,
            total_conversations=row["total_conversations"] or 0,
            unique_users=row["unique_users"] or 0,
            avg_response_time_ms=row["avg_response_time_ms"] or 0,
            p50_response_time_ms=row["p50_response_time_ms"] or 0,
            p95_response_time_ms=row["p95_response_time_ms"] or 0,
            p99_response_time_ms=row["p99_response_time_ms"] or 0,
            max_response_time_ms=row["max_response_time_ms"] or 0,
            avg_confidence=float(row["avg_confidence"]) if row["avg_confidence"] else 0.0,
            min_confidence=float(row["min_confidence"]) if row["min_confidence"] else 0.0,
            tool_call_count=row["tool_call_count"] or 0,
            text_response_count=row["text_response_count"] or 0,
            clarification_count=row["clarification_count"] or 0,
            allow_count=row["allow_count"] or 0,
            confirm_count=row["confirm_count"] or 0,
            block_count=row["block_count"] or 0,
            success_count=row["success_count"] or 0,
            error_count=row["error_count"] or 0,
            total_input_tokens=row["total_input_tokens"] or 0,
            total_output_tokens=row["total_output_tokens"] or 0,
            total_cost_yen=float(row["total_cost_yen"] or 0),
            slow_request_count=row["slow_request_count"] or 0,
        )

    def _row_to_metrics(
        self,
        row,
        organization_id: str,
        target_date: datetime,
    ) -> DailyDBMetrics:
        """DBの行をDailyDBMetricsに変換"""
        return DailyDBMetrics(
            organization_id=organization_id,
            metric_date=target_date,
            total_conversations=row["total_conversations"] or 0,
            unique_users=row["unique_users"] or 0,
            avg_response_time_ms=row["avg_response_time_ms"] or 0,
            p50_response_time_ms=row["p50_response_time_ms"] or 0,
            p95_response_time_ms=row["p95_response_time_ms"] or 0,
            p99_response_time_ms=row["p99_response_time_ms"] or 0,
            max_response_time_ms=row["max_response_time_ms"] or 0,
            avg_confidence=float(row["avg_confidence"]) if row["avg_confidence"] else 0.0,
            min_confidence=float(row["min_confidence"]) if row["min_confidence"] else 0.0,
            tool_call_count=row["tool_call_count"] or 0,
            text_response_count=row["text_response_count"] or 0,
            clarification_count=row["clarification_count"] or 0,
            allow_count=row["allow_count"] or 0,
            confirm_count=row["confirm_count"] or 0,
            block_count=row["block_count"] or 0,
            success_count=row["success_count"] or 0,
            error_count=row["error_count"] or 0,
            total_input_tokens=row["total_input_tokens"] or 0,
            total_output_tokens=row["total_output_tokens"] or 0,
            total_cost_yen=float(row["total_cost_yen"] or 0),
            slow_request_count=row["slow_request_count"] or 0,
        )

    async def get_monthly_cost(
        self,
        organization_id: str,
        year: int,
        month: int,
    ) -> Dict[str, Any]:
        """
        月次コストを取得

        Args:
            organization_id: 組織ID
            year: 年
            month: 月

        Returns:
            月次コスト情報
        """
        if not self.pool:
            return {"error": "No pool available"}

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total_conversations,
                        COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                        COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                        COALESCE(SUM(estimated_cost_yen), 0) as total_cost_yen,
                        COALESCE(AVG(estimated_cost_yen), 0) as avg_cost_per_conversation
                    FROM brain_observability_logs
                    WHERE organization_id = $1
                      AND EXTRACT(YEAR FROM created_at) = $2
                      AND EXTRACT(MONTH FROM created_at) = $3
                      AND environment = 'production'
                    """,
                    organization_id,
                    year,
                    month,
                )

                return {
                    "year": year,
                    "month": month,
                    "total_conversations": row["total_conversations"] or 0,
                    "total_input_tokens": row["total_input_tokens"] or 0,
                    "total_output_tokens": row["total_output_tokens"] or 0,
                    "total_cost_yen": float(row["total_cost_yen"] or 0),
                    "avg_cost_per_conversation": float(row["avg_cost_per_conversation"] or 0),
                }

        except Exception as e:
            logger.error(f"Failed to get monthly cost: {e}")
            return {"error": str(e)}

    async def trigger_daily_aggregation(
        self,
        organization_id: str,
        target_date: datetime,
    ) -> bool:
        """
        日次集計をトリガー

        Args:
            organization_id: 組織ID
            target_date: 対象日

        Returns:
            成功したか
        """
        if not self.pool:
            return False

        try:
            date_value = target_date.date() if isinstance(target_date, datetime) else target_date

            async with self.pool.acquire() as conn:
                await conn.execute(
                    "SELECT aggregate_brain_daily_metrics($1, $2)",
                    organization_id,
                    date_value,
                )
                logger.info(f"Daily aggregation completed: {organization_id} {date_value}")
                return True

        except Exception as e:
            logger.error(f"Failed to trigger daily aggregation: {e}")
            return False


# DBモニターのファクトリ関数
def create_db_monitor(pool=None) -> DBBrainMonitor:
    """
    DBBrainMonitorインスタンスを作成

    Args:
        pool: データベース接続プール

    Returns:
        DBBrainMonitor
    """
    return DBBrainMonitor(pool=pool)


# =============================================================================
# CLI ユーティリティ
# =============================================================================

async def print_dashboard(pool, organization_id: str, target_date: Optional[datetime] = None):
    """
    ダッシュボードを表示（CLI用）

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        target_date: 対象日（デフォルト: 今日）
    """
    if target_date is None:
        target_date = datetime.utcnow()

    monitor = DBBrainMonitor(pool=pool)
    metrics = await monitor.get_daily_metrics(organization_id, target_date)
    print(metrics.to_dashboard_string())
