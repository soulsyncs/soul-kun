# lib/brain/dashboard.py
"""
Brain Observability ダッシュボードユーティリティ

設計書: docs/25_llm_native_brain_architecture.md セクション15.2

【機能】
- 日次メトリクスの取得
- アラートの取得
- ダッシュボード文字列生成
- コスト分析

Author: Claude Opus 4.5
Created: 2026-01-31
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


# 監視閾値（設計書15.1準拠）
DEFAULT_THRESHOLDS = {
    "response_time_warning_ms": 3000,     # 早期警告: 3秒
    "response_time_critical_ms": 10000,   # 警告: 10秒
    "error_rate_warning": 0.03,           # 早期警告: 3%
    "error_rate_critical": 0.05,          # 警告: 5%
    "confirm_rate_info": 0.30,            # 情報: 30%
    "block_rate_warning": 0.10,           # 警告: 10%
    "daily_cost_warning": 5000.0,         # 警告: 5,000円
    "daily_cost_critical": 10000.0,       # 警告: 10,000円
}


@dataclass
class DashboardMetrics:
    """ダッシュボード用メトリクス"""
    organization_id: str
    metric_date: date

    # 会話統計
    total_conversations: int = 0
    unique_users: int = 0

    # 応答時間
    avg_response_time_ms: Optional[int] = None
    p50_response_time_ms: Optional[int] = None
    p95_response_time_ms: Optional[int] = None
    p99_response_time_ms: Optional[int] = None
    max_response_time_ms: Optional[int] = None

    # 確信度
    avg_confidence: Optional[Decimal] = None
    min_confidence: Optional[Decimal] = None

    # アクション分布
    tool_call_count: int = 0
    text_response_count: int = 0
    clarification_count: int = 0

    # Guardian判定分布
    allow_count: int = 0
    confirm_count: int = 0
    block_count: int = 0

    # 実行結果
    success_count: int = 0
    error_count: int = 0

    # コスト
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_yen: Decimal = Decimal("0")

    # パフォーマンス
    slow_request_count: int = 0

    @property
    def error_rate(self) -> float:
        """エラー率を計算"""
        if self.total_conversations == 0:
            return 0.0
        return (self.error_count / self.total_conversations) * 100

    @property
    def confirm_rate(self) -> float:
        """確認モード率を計算"""
        if self.total_conversations == 0:
            return 0.0
        return (self.confirm_count / self.total_conversations) * 100

    @property
    def block_rate(self) -> float:
        """ブロック率を計算"""
        if self.total_conversations == 0:
            return 0.0
        return (self.block_count / self.total_conversations) * 100

    @property
    def avg_cost_per_conversation(self) -> Decimal:
        """会話あたりの平均コスト"""
        if self.total_conversations == 0:
            return Decimal("0")
        return self.total_cost_yen / self.total_conversations

    def check_alerts(self, thresholds: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        アラート条件をチェック

        Returns:
            アラートのリスト
        """
        if thresholds is None:
            thresholds = DEFAULT_THRESHOLDS

        alerts = []

        # 応答時間チェック
        if self.avg_response_time_ms:
            if self.avg_response_time_ms > thresholds["response_time_critical_ms"]:
                alerts.append({
                    "category": "response_time",
                    "level": "warning",
                    "message": f"平均応答時間が{self.avg_response_time_ms}msです（閾値: {thresholds['response_time_critical_ms']}ms）",
                    "value": self.avg_response_time_ms,
                    "threshold": thresholds["response_time_critical_ms"],
                })
            elif self.avg_response_time_ms > thresholds["response_time_warning_ms"]:
                alerts.append({
                    "category": "response_time",
                    "level": "info",
                    "message": f"平均応答時間が{self.avg_response_time_ms}msです（早期警告: {thresholds['response_time_warning_ms']}ms）",
                    "value": self.avg_response_time_ms,
                    "threshold": thresholds["response_time_warning_ms"],
                })

        # エラー率チェック
        error_rate_decimal = self.error_rate / 100
        if error_rate_decimal > thresholds["error_rate_critical"]:
            alerts.append({
                "category": "error_rate",
                "level": "warning",
                "message": f"エラー率が{self.error_rate:.1f}%です（閾値: {thresholds['error_rate_critical']*100}%）",
                "value": self.error_rate,
                "threshold": thresholds["error_rate_critical"] * 100,
            })
        elif error_rate_decimal > thresholds["error_rate_warning"]:
            alerts.append({
                "category": "error_rate",
                "level": "info",
                "message": f"エラー率が{self.error_rate:.1f}%です（早期警告: {thresholds['error_rate_warning']*100}%）",
                "value": self.error_rate,
                "threshold": thresholds["error_rate_warning"] * 100,
            })

        # 確認モード率チェック
        confirm_rate_decimal = self.confirm_rate / 100
        if confirm_rate_decimal > thresholds["confirm_rate_info"]:
            alerts.append({
                "category": "confirm_rate",
                "level": "info",
                "message": f"確認モード率が{self.confirm_rate:.1f}%です（閾値: {thresholds['confirm_rate_info']*100}%）",
                "value": self.confirm_rate,
                "threshold": thresholds["confirm_rate_info"] * 100,
            })

        # ブロック率チェック
        block_rate_decimal = self.block_rate / 100
        if block_rate_decimal > thresholds["block_rate_warning"]:
            alerts.append({
                "category": "block_rate",
                "level": "warning",
                "message": f"ブロック率が{self.block_rate:.1f}%です（閾値: {thresholds['block_rate_warning']*100}%）",
                "value": self.block_rate,
                "threshold": thresholds["block_rate_warning"] * 100,
            })

        # コストチェック
        if self.total_cost_yen > Decimal(str(thresholds["daily_cost_critical"])):
            alerts.append({
                "category": "daily_cost",
                "level": "critical",
                "message": f"日次コストが{self.total_cost_yen:,.0f}円です（閾値: {thresholds['daily_cost_critical']:,.0f}円）",
                "value": float(self.total_cost_yen),
                "threshold": thresholds["daily_cost_critical"],
            })
        elif self.total_cost_yen > Decimal(str(thresholds["daily_cost_warning"])):
            alerts.append({
                "category": "daily_cost",
                "level": "warning",
                "message": f"日次コストが{self.total_cost_yen:,.0f}円です（閾値: {thresholds['daily_cost_warning']:,.0f}円）",
                "value": float(self.total_cost_yen),
                "threshold": thresholds["daily_cost_warning"],
            })

        return alerts

    def to_dashboard_string(self) -> str:
        """
        ダッシュボード表示用の文字列を生成

        設計書15.2のフォーマットに準拠
        """
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "  ソウルくん脳モニター",
            f"  {self.metric_date} レポート",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "📊 今日の統計",
            f"  総会話数:     {self.total_conversations:,}",
            f"  ユニークユーザー: {self.unique_users:,}",
        ]

        if self.avg_response_time_ms:
            lines.append(f"  平均応答時間: {self.avg_response_time_ms / 1000:.1f}秒")

        if self.avg_confidence:
            lines.append(f"  確信度平均:   {self.avg_confidence}")

        lines.extend([
            "",
            "🛡️ Guardian判定",
            f"  許可(allow):  {self.allow_count:,} ({self.allow_count / max(self.total_conversations, 1) * 100:.1f}%)",
            f"  確認(confirm): {self.confirm_count:,} ({self.confirm_rate:.1f}%)",
            f"  拒否(block):  {self.block_count:,} ({self.block_rate:.1f}%)",
            "",
            "💰 コスト",
            f"  本日コスト:   ¥{self.total_cost_yen:,.0f}",
            f"  入力トークン: {self.total_input_tokens:,}",
            f"  出力トークン: {self.total_output_tokens:,}",
        ])

        if self.total_conversations > 0:
            lines.append(f"  会話あたり:   ¥{self.avg_cost_per_conversation:.2f}")

        # アラート
        alerts = self.check_alerts()
        if alerts:
            lines.extend([
                "",
                "⚠️ アラート",
            ])
            for alert in alerts:
                level_icon = {
                    "critical": "🔴",
                    "warning": "🟡",
                    "info": "🔵",
                }.get(alert["level"], "⚪")
                lines.append(f"  {level_icon} [{alert['level'].upper()}] {alert['message']}")

        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ])

        return "\n".join(lines)


class BrainDashboard:
    """
    Brain Observability ダッシュボードクラス

    DB接続を使用してメトリクスを取得し、ダッシュボードを生成
    """

    def __init__(self, pool: Optional[Any] = None):
        """
        Args:
            pool: asyncpg connection pool (asyncpg.Pool or compatible)
        """
        self.pool = pool

    async def get_daily_metrics(
        self,
        organization_id: str,
        target_date: Optional[date] = None
    ) -> DashboardMetrics:
        """
        指定日の日次メトリクスを取得

        Args:
            organization_id: 組織ID
            target_date: 対象日（省略時は今日）

        Returns:
            DashboardMetrics
        """
        if target_date is None:
            target_date = date.today()

        if self.pool is None:
            # プールがない場合は空のメトリクスを返す
            return DashboardMetrics(
                organization_id=organization_id,
                metric_date=target_date,
            )

        try:
            async with self.pool.acquire() as conn:
                # まず集計済みテーブルから取得を試みる
                row = await conn.fetchrow("""
                SELECT
                    total_conversations,
                    unique_users,
                    avg_response_time_ms,
                    p50_response_time_ms,
                    p95_response_time_ms,
                    p99_response_time_ms,
                    max_response_time_ms,
                    avg_confidence,
                    min_confidence,
                    tool_call_count,
                    text_response_count,
                    clarification_count,
                    allow_count,
                    confirm_count,
                    block_count,
                    success_count,
                    error_count,
                    total_input_tokens,
                    total_output_tokens,
                    total_cost_yen,
                    slow_request_count
                FROM brain_daily_metrics
                WHERE organization_id = $1 AND metric_date = $2
                """, organization_id, target_date)

                if row:
                    return DashboardMetrics(
                        organization_id=organization_id,
                        metric_date=target_date,
                        total_conversations=row['total_conversations'] or 0,
                        unique_users=row['unique_users'] or 0,
                        avg_response_time_ms=row['avg_response_time_ms'],
                        p50_response_time_ms=row['p50_response_time_ms'],
                        p95_response_time_ms=row['p95_response_time_ms'],
                        p99_response_time_ms=row['p99_response_time_ms'],
                        max_response_time_ms=row['max_response_time_ms'],
                        avg_confidence=row['avg_confidence'],
                        min_confidence=row['min_confidence'],
                        tool_call_count=row['tool_call_count'] or 0,
                        text_response_count=row['text_response_count'] or 0,
                        clarification_count=row['clarification_count'] or 0,
                        allow_count=row['allow_count'] or 0,
                        confirm_count=row['confirm_count'] or 0,
                        block_count=row['block_count'] or 0,
                        success_count=row['success_count'] or 0,
                        error_count=row['error_count'] or 0,
                        total_input_tokens=row['total_input_tokens'] or 0,
                        total_output_tokens=row['total_output_tokens'] or 0,
                        total_cost_yen=row['total_cost_yen'] or Decimal("0"),
                        slow_request_count=row['slow_request_count'] or 0,
                    )

                # 集計テーブルにない場合はリアルタイム集計
                row = await conn.fetchrow("""
                    SELECT
                    COUNT(*) AS total_conversations,
                    COUNT(DISTINCT user_id) AS unique_users,
                    AVG(total_response_time_ms)::INTEGER AS avg_response_time_ms,
                    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_response_time_ms)::INTEGER AS p50_response_time_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_response_time_ms)::INTEGER AS p95_response_time_ms,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY total_response_time_ms)::INTEGER AS p99_response_time_ms,
                    MAX(total_response_time_ms) AS max_response_time_ms,
                    AVG(confidence_overall)::DECIMAL(3,2) AS avg_confidence,
                    MIN(confidence_overall)::DECIMAL(3,2) AS min_confidence,
                    COUNT(*) FILTER (WHERE output_type = 'tool_call') AS tool_call_count,
                    COUNT(*) FILTER (WHERE output_type = 'text_response') AS text_response_count,
                    COUNT(*) FILTER (WHERE output_type = 'clarification_needed') AS clarification_count,
                    COUNT(*) FILTER (WHERE guardian_action = 'allow') AS allow_count,
                    COUNT(*) FILTER (WHERE guardian_action = 'confirm') AS confirm_count,
                    COUNT(*) FILTER (WHERE guardian_action = 'block') AS block_count,
                    COUNT(*) FILTER (WHERE execution_success = TRUE) AS success_count,
                    COUNT(*) FILTER (WHERE execution_success = FALSE) AS error_count,
                    COALESCE(SUM(input_tokens), 0)::BIGINT AS total_input_tokens,
                    COALESCE(SUM(output_tokens), 0)::BIGINT AS total_output_tokens,
                    COALESCE(SUM(estimated_cost_yen), 0)::DECIMAL(12,2) AS total_cost_yen,
                    COUNT(*) FILTER (WHERE total_response_time_ms > 10000) AS slow_request_count
                    FROM brain_observability_logs
                    WHERE organization_id = $1
                      AND DATE(created_at) = $2
                      AND environment = 'production'
                """, organization_id, target_date)

                return DashboardMetrics(
                    organization_id=organization_id,
                    metric_date=target_date,
                    total_conversations=row['total_conversations'] or 0,
                    unique_users=row['unique_users'] or 0,
                    avg_response_time_ms=row['avg_response_time_ms'],
                    p50_response_time_ms=row['p50_response_time_ms'],
                    p95_response_time_ms=row['p95_response_time_ms'],
                    p99_response_time_ms=row['p99_response_time_ms'],
                    max_response_time_ms=row['max_response_time_ms'],
                    avg_confidence=row['avg_confidence'],
                    min_confidence=row['min_confidence'],
                    tool_call_count=row['tool_call_count'] or 0,
                    text_response_count=row['text_response_count'] or 0,
                    clarification_count=row['clarification_count'] or 0,
                    allow_count=row['allow_count'] or 0,
                    confirm_count=row['confirm_count'] or 0,
                    block_count=row['block_count'] or 0,
                    success_count=row['success_count'] or 0,
                    error_count=row['error_count'] or 0,
                    total_input_tokens=row['total_input_tokens'] or 0,
                    total_output_tokens=row['total_output_tokens'] or 0,
                    total_cost_yen=row['total_cost_yen'] or Decimal("0"),
                    slow_request_count=row['slow_request_count'] or 0,
                )
        except Exception as e:
            logger.error(f"Failed to get daily metrics for {organization_id}: {type(e).__name__}")
            return DashboardMetrics(
                organization_id=organization_id,
                metric_date=target_date,
            )

    async def get_weekly_summary(
        self,
        organization_id: str,
        end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        週次サマリーを取得

        Args:
            organization_id: 組織ID
            end_date: 終了日（省略時は今日）

        Returns:
            週次サマリーの辞書
        """
        if end_date is None:
            end_date = date.today()

        start_date = end_date - timedelta(days=6)

        if self.pool is None:
            return {
                "organization_id": organization_id,
                "start_date": str(start_date),
                "end_date": str(end_date),
                "error": "No database pool available",
            }

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT
                        SUM(total_conversations) AS total_conversations,
                        SUM(unique_users) AS total_users,
                        AVG(avg_response_time_ms)::INTEGER AS avg_response_time_ms,
                        SUM(error_count)::DECIMAL / NULLIF(SUM(total_conversations), 0) * 100 AS avg_error_rate,
                        SUM(confirm_count)::DECIMAL / NULLIF(SUM(total_conversations), 0) * 100 AS avg_confirm_rate,
                        SUM(block_count)::DECIMAL / NULLIF(SUM(total_conversations), 0) * 100 AS avg_block_rate,
                        SUM(total_cost_yen) AS total_cost_yen,
                        COUNT(*) AS days_with_data
                    FROM brain_daily_metrics
                    WHERE organization_id = $1
                      AND metric_date BETWEEN $2 AND $3
                """, organization_id, start_date, end_date)

                return {
                    "organization_id": organization_id,
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                    "total_conversations": row['total_conversations'] or 0,
                    "total_users": row['total_users'] or 0,
                    "avg_response_time_ms": row['avg_response_time_ms'],
                    "avg_error_rate": float(row['avg_error_rate']) if row['avg_error_rate'] else 0,
                    "avg_confirm_rate": float(row['avg_confirm_rate']) if row['avg_confirm_rate'] else 0,
                    "avg_block_rate": float(row['avg_block_rate']) if row['avg_block_rate'] else 0,
                    "total_cost_yen": float(row['total_cost_yen']) if row['total_cost_yen'] else 0,
                    "days_with_data": row['days_with_data'] or 0,
                }
        except Exception as e:
            logger.error(f"Failed to get weekly summary for {organization_id}: {type(e).__name__}")
            return {
                "organization_id": organization_id,
                "start_date": str(start_date),
                "end_date": str(end_date),
                "error": type(e).__name__,
            }

    async def get_monthly_cost(
        self,
        organization_id: str,
        year: int,
        month: int
    ) -> Dict[str, Any]:
        """
        月次コストを取得

        Args:
            organization_id: 組織ID
            year: 年
            month: 月

        Returns:
            月次コストの辞書
        """
        if self.pool is None:
            return {
                "organization_id": organization_id,
                "year": year,
                "month": month,
                "error": "No database pool available",
            }

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT
                        SUM(total_conversations) AS total_conversations,
                        SUM(total_input_tokens) AS total_input_tokens,
                        SUM(total_output_tokens) AS total_output_tokens,
                        SUM(total_cost_yen) AS total_cost_yen
                    FROM brain_daily_metrics
                    WHERE organization_id = $1
                      AND EXTRACT(YEAR FROM metric_date) = $2
                      AND EXTRACT(MONTH FROM metric_date) = $3
                """, organization_id, year, month)

                total_conversations = row['total_conversations'] or 0
                total_cost = row['total_cost_yen'] or Decimal("0")

                return {
                    "organization_id": organization_id,
                    "year": year,
                    "month": month,
                    "total_conversations": total_conversations,
                    "total_input_tokens": row['total_input_tokens'] or 0,
                    "total_output_tokens": row['total_output_tokens'] or 0,
                    "total_cost_yen": float(total_cost),
                    "avg_cost_per_conversation": float(total_cost / total_conversations) if total_conversations > 0 else 0,
                }
        except Exception as e:
            logger.error(f"Failed to get monthly cost for {organization_id}: {type(e).__name__}")
            return {
                "organization_id": organization_id,
                "year": year,
                "month": month,
                "error": type(e).__name__,
            }


def create_dashboard(pool: Optional[Any] = None) -> BrainDashboard:
    """
    ダッシュボードインスタンスを作成

    Args:
        pool: asyncpg connection pool

    Returns:
        BrainDashboard
    """
    return BrainDashboard(pool=pool)
