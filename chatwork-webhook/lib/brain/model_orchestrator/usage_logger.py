"""
利用ログ記録

AI呼び出しの利用ログを非同期で記録

設計書: docs/20_next_generation_capabilities.md セクション10.2.2
10の鉄則:
- #1: 全クエリにorganization_idフィルタ
- #9: SQLインジェクション対策（パラメータ化クエリ）
"""

from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Dict, Any, List
from uuid import UUID
import hashlib
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .constants import Tier

logger = logging.getLogger(__name__)


# =============================================================================
# データモデル
# =============================================================================

@dataclass
class UsageLogEntry:
    """利用ログエントリ"""
    id: UUID
    organization_id: str
    model_id: str
    task_type: str
    tier: str
    input_tokens: int
    output_tokens: int
    cost_jpy: Decimal
    room_id: Optional[str]
    user_id: Optional[str]
    latency_ms: Optional[int]
    was_fallback: bool
    original_model_id: Optional[str]
    fallback_reason: Optional[str]
    fallback_attempt: int
    success: bool
    error_message: Optional[str]
    created_at: datetime


@dataclass
class UsageStats:
    """利用統計"""
    total_requests: int
    total_cost_jpy: Decimal
    total_input_tokens: int
    total_output_tokens: int
    success_rate: float
    average_latency_ms: float
    by_tier: Dict[str, int]
    by_model: Dict[str, int]
    by_task_type: Dict[str, int]


# =============================================================================
# 利用ログ記録
# =============================================================================

class UsageLogger:
    """
    利用ログ記録

    - ai_usage_logsテーブルへの非同期記録
    - 利用統計の取得
    - 重複検出
    """

    def __init__(self, pool: Engine, organization_id: str):
        """
        初期化

        Args:
            pool: SQLAlchemyのエンジン（DB接続プール）
            organization_id: 組織ID
        """
        self._pool = pool
        self._organization_id = organization_id

    # -------------------------------------------------------------------------
    # ログ記録
    # -------------------------------------------------------------------------

    def log_usage(
        self,
        model_id: str,
        task_type: str,
        tier: Tier,
        input_tokens: int,
        output_tokens: int,
        cost_jpy: Decimal,
        latency_ms: int,
        success: bool,
        room_id: Optional[str] = None,
        user_id: Optional[str] = None,
        was_fallback: bool = False,
        original_model_id: Optional[str] = None,
        fallback_reason: Optional[str] = None,
        fallback_attempt: int = 0,
        error_message: Optional[str] = None,
        request_content: Optional[str] = None,
    ) -> Optional[UUID]:
        """
        利用ログを記録

        Args:
            model_id: 使用したモデルID
            task_type: タスクタイプ
            tier: ティア
            input_tokens: 入力トークン数
            output_tokens: 出力トークン数
            cost_jpy: コスト（円）
            latency_ms: レイテンシ（ミリ秒）
            success: 成功したか
            room_id: ルームID（オプション）
            user_id: ユーザーID（オプション）
            was_fallback: フォールバックだったか
            original_model_id: 元のモデルID（フォールバック時）
            fallback_reason: フォールバック理由
            fallback_attempt: フォールバック試行回数
            error_message: エラーメッセージ
            request_content: リクエスト内容（ハッシュ生成用）

        Returns:
            作成されたログのUUID（失敗時はNone）
        """
        # リクエストハッシュを生成（重複検出用）
        request_hash = None
        if request_content:
            request_hash = hashlib.sha256(
                request_content.encode("utf-8")
            ).hexdigest()[:64]

        query = text("""
            INSERT INTO ai_usage_logs (
                organization_id,
                model_id,
                task_type,
                tier,
                input_tokens,
                output_tokens,
                cost_jpy,
                room_id,
                user_id,
                request_hash,
                latency_ms,
                was_fallback,
                original_model_id,
                fallback_reason,
                fallback_attempt,
                success,
                error_message
            ) VALUES (
                CAST(:org_id AS uuid),
                :model_id,
                :task_type,
                :tier,
                :input_tokens,
                :output_tokens,
                :cost_jpy,
                :room_id,
                :user_id,
                :request_hash,
                :latency_ms,
                :was_fallback,
                :original_model_id,
                :fallback_reason,
                :fallback_attempt,
                :success,
                :error_message
            )
            RETURNING id
        """)

        try:
            with self._pool.connect() as conn:
                result = conn.execute(query, {
                    "org_id": self._organization_id,
                    "model_id": model_id,
                    "task_type": task_type,
                    "tier": tier.value,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_jpy": float(cost_jpy),
                    "room_id": room_id,
                    "user_id": user_id,
                    "request_hash": request_hash,
                    "latency_ms": latency_ms,
                    "was_fallback": was_fallback,
                    "original_model_id": original_model_id,
                    "fallback_reason": fallback_reason,
                    "fallback_attempt": fallback_attempt,
                    "success": success,
                    "error_message": error_message,
                })
                conn.commit()

                row = result.fetchone()
                log_id: Optional[UUID] = None
                if row:
                    try:
                        log_id = UUID(str(row[0]))
                    except (ValueError, TypeError):
                        # Handle cases where row[0] is not a valid UUID string
                        log_id = row[0] if isinstance(row[0], UUID) else None

                logger.debug(
                    f"Logged usage: model={model_id}, tier={tier.value}, "
                    f"cost=¥{cost_jpy:.2f}, success={success}"
                )

                return log_id

        except Exception as e:
            logger.error(f"Failed to log usage: {e}")
            return None

    # -------------------------------------------------------------------------
    # 統計取得
    # -------------------------------------------------------------------------

    def get_daily_stats(self, target_date: Optional[date] = None) -> UsageStats:
        """
        日次統計を取得

        Args:
            target_date: 対象日（デフォルトは今日）

        Returns:
            利用統計
        """
        if target_date is None:
            target_date = date.today()

        query = text("""
            SELECT
                COUNT(*) as total_requests,
                COALESCE(SUM(cost_jpy), 0) as total_cost_jpy,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                COALESCE(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END), 0) as success_rate,
                COALESCE(AVG(latency_ms), 0) as avg_latency_ms
            FROM ai_usage_logs
            WHERE organization_id = CAST(:org_id AS uuid)
              AND DATE(created_at) = :target_date
        """)

        tier_query = text("""
            SELECT tier, COUNT(*) as count
            FROM ai_usage_logs
            WHERE organization_id = CAST(:org_id AS uuid)
              AND DATE(created_at) = :target_date
            GROUP BY tier
        """)

        model_query = text("""
            SELECT model_id, COUNT(*) as count
            FROM ai_usage_logs
            WHERE organization_id = CAST(:org_id AS uuid)
              AND DATE(created_at) = :target_date
            GROUP BY model_id
            ORDER BY count DESC
            LIMIT 10
        """)

        task_query = text("""
            SELECT task_type, COUNT(*) as count
            FROM ai_usage_logs
            WHERE organization_id = CAST(:org_id AS uuid)
              AND DATE(created_at) = :target_date
            GROUP BY task_type
            ORDER BY count DESC
            LIMIT 10
        """)

        try:
            with self._pool.connect() as conn:
                # 基本統計
                result = conn.execute(query, {
                    "org_id": self._organization_id,
                    "target_date": target_date.isoformat(),
                })
                stats_row = result.fetchone()

                # ティア別
                tier_result = conn.execute(tier_query, {
                    "org_id": self._organization_id,
                    "target_date": target_date.isoformat(),
                })
                by_tier = {r[0]: r[1] for r in tier_result.fetchall()}

                # モデル別
                model_result = conn.execute(model_query, {
                    "org_id": self._organization_id,
                    "target_date": target_date.isoformat(),
                })
                by_model = {r[0]: r[1] for r in model_result.fetchall()}

                # タスクタイプ別
                task_result = conn.execute(task_query, {
                    "org_id": self._organization_id,
                    "target_date": target_date.isoformat(),
                })
                by_task_type = {r[0]: r[1] for r in task_result.fetchall()}

                if stats_row is None:
                    raise ValueError("No stats row returned")

                return UsageStats(
                    total_requests=stats_row[0] or 0,
                    total_cost_jpy=Decimal(str(stats_row[1] or 0)),
                    total_input_tokens=stats_row[2] or 0,
                    total_output_tokens=stats_row[3] or 0,
                    success_rate=float(stats_row[4] or 0),
                    average_latency_ms=float(stats_row[5] or 0),
                    by_tier=by_tier,
                    by_model=by_model,
                    by_task_type=by_task_type,
                )

        except Exception as e:
            logger.error(f"Failed to get daily stats: {e}")
            return UsageStats(
                total_requests=0,
                total_cost_jpy=Decimal("0"),
                total_input_tokens=0,
                total_output_tokens=0,
                success_rate=0.0,
                average_latency_ms=0.0,
                by_tier={},
                by_model={},
                by_task_type={},
            )

    def get_recent_logs(
        self,
        limit: int = 100,
        success_only: bool = False
    ) -> List[UsageLogEntry]:
        """
        最近のログを取得

        Args:
            limit: 取得件数
            success_only: 成功のみ取得するか

        Returns:
            ログエントリのリスト
        """
        success_filter = "AND success = TRUE" if success_only else ""

        query = text(f"""
            SELECT
                id,
                organization_id,
                model_id,
                task_type,
                tier,
                input_tokens,
                output_tokens,
                cost_jpy,
                room_id,
                user_id,
                latency_ms,
                was_fallback,
                original_model_id,
                fallback_reason,
                fallback_attempt,
                success,
                error_message,
                created_at
            FROM ai_usage_logs
            WHERE organization_id = CAST(:org_id AS uuid)
              {success_filter}
            ORDER BY created_at DESC
            LIMIT :limit
        """)

        try:
            with self._pool.connect() as conn:
                result = conn.execute(query, {
                    "org_id": self._organization_id,
                    "limit": limit,
                })
                rows = result.fetchall()

                return [
                    UsageLogEntry(
                        id=row[0],
                        organization_id=str(row[1]),
                        model_id=row[2],
                        task_type=row[3],
                        tier=row[4],
                        input_tokens=row[5],
                        output_tokens=row[6],
                        cost_jpy=Decimal(str(row[7])),
                        room_id=row[8],
                        user_id=row[9],
                        latency_ms=row[10],
                        was_fallback=row[11],
                        original_model_id=row[12],
                        fallback_reason=row[13],
                        fallback_attempt=row[14] or 0,
                        success=row[15],
                        error_message=row[16],
                        created_at=row[17],
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"Failed to get recent logs: {e}")
            return []

    # -------------------------------------------------------------------------
    # エラー分析
    # -------------------------------------------------------------------------

    def get_error_summary(self, days: int = 7) -> Dict[str, Any]:
        """
        エラーサマリーを取得

        Args:
            days: 集計対象日数

        Returns:
            エラーサマリー
        """
        query = text("""
            SELECT
                model_id,
                COUNT(*) as error_count,
                COUNT(DISTINCT error_message) as unique_errors
            FROM ai_usage_logs
            WHERE organization_id = CAST(:org_id AS uuid)
              AND success = FALSE
              AND created_at >= NOW() - INTERVAL :days DAY
            GROUP BY model_id
            ORDER BY error_count DESC
        """)

        error_messages_query = text("""
            SELECT
                error_message,
                COUNT(*) as count
            FROM ai_usage_logs
            WHERE organization_id = CAST(:org_id AS uuid)
              AND success = FALSE
              AND created_at >= NOW() - INTERVAL :days DAY
              AND error_message IS NOT NULL
            GROUP BY error_message
            ORDER BY count DESC
            LIMIT 10
        """)

        try:
            with self._pool.connect() as conn:
                # モデル別エラー
                result = conn.execute(query, {
                    "org_id": self._organization_id,
                    "days": days,
                })
                by_model = [
                    {
                        "model_id": row[0],
                        "error_count": row[1],
                        "unique_errors": row[2],
                    }
                    for row in result.fetchall()
                ]

                # エラーメッセージ別
                errors_result = conn.execute(error_messages_query, {
                    "org_id": self._organization_id,
                    "days": days,
                })
                top_errors = [
                    {
                        "message": row[0],
                        "count": row[1],
                    }
                    for row in errors_result.fetchall()
                ]

                return {
                    "by_model": by_model,
                    "top_errors": top_errors,
                    "period_days": days,
                }

        except Exception as e:
            logger.error(f"Failed to get error summary: {e}")
            return {
                "by_model": [],
                "top_errors": [],
                "period_days": days,
            }

    # -------------------------------------------------------------------------
    # フォールバック分析
    # -------------------------------------------------------------------------

    def get_fallback_summary(self, days: int = 7) -> Dict[str, Any]:
        """
        フォールバックサマリーを取得

        Args:
            days: 集計対象日数

        Returns:
            フォールバックサマリー
        """
        query = text("""
            SELECT
                original_model_id,
                model_id as fallback_model_id,
                COUNT(*) as count,
                AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) as success_rate
            FROM ai_usage_logs
            WHERE organization_id = CAST(:org_id AS uuid)
              AND was_fallback = TRUE
              AND created_at >= NOW() - INTERVAL :days DAY
            GROUP BY original_model_id, model_id
            ORDER BY count DESC
        """)

        try:
            with self._pool.connect() as conn:
                result = conn.execute(query, {
                    "org_id": self._organization_id,
                    "days": days,
                })

                fallback_patterns = [
                    {
                        "original_model": row[0],
                        "fallback_model": row[1],
                        "count": row[2],
                        "success_rate": float(row[3] or 0),
                    }
                    for row in result.fetchall()
                ]

                return {
                    "fallback_patterns": fallback_patterns,
                    "period_days": days,
                }

        except Exception as e:
            logger.error(f"Failed to get fallback summary: {e}")
            return {
                "fallback_patterns": [],
                "period_days": days,
            }
