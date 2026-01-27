# lib/capabilities/feedback/ceo_feedback_engine.py
"""
Phase F1: CEOフィードバックシステム - メイン統合エンジン

このモジュールは、CEOフィードバックシステムの全機能を統合し、
単一のエントリーポイントを提供します。

設計書: docs/20_next_generation_capabilities.md セクション8

アーキテクチャ:
    CEOFeedbackEngine
    ├─ FactCollector (ファクト収集)
    ├─ Analyzer (分析)
    ├─ FeedbackGenerator (フィードバック生成)
    └─ FeedbackDelivery (配信)

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .analyzer import Analyzer, create_analyzer
from .constants import (
    AnalysisParameters,
    DeliveryParameters,
    FEATURE_FLAG_NAME,
    FEATURE_FLAG_DAILY_DIGEST,
    FEATURE_FLAG_WEEKLY_REVIEW,
    FEATURE_FLAG_REALTIME_ALERT,
    FEATURE_FLAG_ON_DEMAND,
    FeedbackType,
)
from .delivery import (
    DeliveryConfig,
    FeedbackDelivery,
    create_feedback_delivery,
)
from .fact_collector import FactCollector, create_fact_collector
from .feedback_generator import FeedbackGenerator, create_feedback_generator
from .models import (
    Anomaly,
    AnalysisResult,
    CEOFeedback,
    DailyFacts,
    DeliveryResult,
)


# =============================================================================
# 例外クラス
# =============================================================================


class CEOFeedbackEngineError(Exception):
    """CEOフィードバックエンジンエラー"""

    def __init__(
        self,
        message: str,
        operation: str = "",
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.operation = operation
        self.details = details or {}
        self.original_exception = original_exception


class FeatureDisabledError(CEOFeedbackEngineError):
    """機能が無効化されているエラー"""
    pass


# =============================================================================
# CEOフィードバック設定
# =============================================================================


@dataclass
class CEOFeedbackSettings:
    """
    CEOフィードバック設定

    Attributes:
        recipient_user_id: 受信者ユーザーID（CEO）
        recipient_name: 受信者の名前
        chatwork_room_id: 配信先ChatWorkルームID
        enable_daily_digest: デイリーダイジェストを有効にするか
        enable_weekly_review: ウィークリーレビューを有効にするか
        enable_monthly_insight: マンスリーインサイトを有効にするか
        enable_realtime_alert: リアルタイムアラートを有効にするか
        enable_on_demand: オンデマンド分析を有効にするか
    """
    recipient_user_id: UUID
    recipient_name: str
    chatwork_room_id: Optional[int] = None
    enable_daily_digest: bool = True
    enable_weekly_review: bool = True
    enable_monthly_insight: bool = True
    enable_realtime_alert: bool = True
    enable_on_demand: bool = True


# =============================================================================
# CEOFeedbackEngine クラス
# =============================================================================


class CEOFeedbackEngine:
    """
    CEOフィードバックエンジン

    全機能を統合し、以下のフィードバックを提供:
    - デイリーダイジェスト（毎朝8:00）
    - ウィークリーレビュー（毎週月曜9:00）
    - マンスリーインサイト（毎月1日9:00）
    - リアルタイムアラート（随時）
    - オンデマンド分析（「最近どう？」）

    使用例:
        >>> engine = CEOFeedbackEngine(conn, org_id, settings)
        >>>
        >>> # デイリーダイジェストを生成・配信
        >>> result = await engine.generate_daily_digest()
        >>>
        >>> # リアルタイムアラートを送信
        >>> result = await engine.send_realtime_alert(anomaly)
        >>>
        >>> # オンデマンド分析
        >>> feedback = await engine.analyze_on_demand("最近チームの様子どう？")

    Attributes:
        conn: データベース接続
        org_id: 組織ID
        settings: フィードバック設定
    """

    def __init__(
        self,
        conn: Connection,
        organization_id: UUID,
        settings: CEOFeedbackSettings,
    ) -> None:
        """
        CEOFeedbackEngineを初期化

        Args:
            conn: データベース接続
            organization_id: 組織ID
            settings: フィードバック設定
        """
        self._conn = conn
        self._org_id = organization_id
        self._settings = settings

        # 各コンポーネントを初期化
        self._fact_collector = create_fact_collector(conn, organization_id)
        self._analyzer = create_analyzer()
        self._feedback_generator = create_feedback_generator(
            organization_id=organization_id,
            recipient_user_id=settings.recipient_user_id,
            recipient_name=settings.recipient_name,
        )
        self._delivery = create_feedback_delivery(
            conn=conn,
            organization_id=organization_id,
            chatwork_room_id=settings.chatwork_room_id,
            config=DeliveryConfig(
                chatwork_room_id=settings.chatwork_room_id,
                enable_daily_digest=settings.enable_daily_digest,
                enable_weekly_review=settings.enable_weekly_review,
                enable_monthly_insight=settings.enable_monthly_insight,
                enable_realtime_alert=settings.enable_realtime_alert,
            ),
        )

        # ロガーの初期化
        try:
            from lib.logging import get_logger
            self._logger = get_logger("feedback.engine")
        except ImportError:
            import logging
            self._logger = logging.getLogger("feedback.engine")

    # =========================================================================
    # プロパティ
    # =========================================================================

    @property
    def conn(self) -> Connection:
        """データベース接続を取得"""
        return self._conn

    @property
    def organization_id(self) -> UUID:
        """組織IDを取得"""
        return self._org_id

    @property
    def settings(self) -> CEOFeedbackSettings:
        """設定を取得"""
        return self._settings

    # =========================================================================
    # デイリーダイジェスト
    # =========================================================================

    async def generate_daily_digest(
        self,
        target_date: Optional[date] = None,
        deliver: bool = True,
    ) -> Tuple[CEOFeedback, Optional[DeliveryResult]]:
        """
        デイリーダイジェストを生成・配信

        毎朝8:00に配信する「今日注目すべきこと」を生成。

        Args:
            target_date: 対象日（デフォルト: 今日）
            deliver: 配信するか（デフォルト: True）

        Returns:
            Tuple[CEOFeedback, Optional[DeliveryResult]]:
                生成されたフィードバックと配信結果

        Raises:
            FeatureDisabledError: 機能が無効化されている場合
            CEOFeedbackEngineError: 生成に失敗した場合
        """
        # 機能チェック
        if not self._settings.enable_daily_digest:
            raise FeatureDisabledError(
                message="デイリーダイジェスト機能は無効化されています",
                operation="daily_digest",
            )

        self._logger.info(
            "Generating daily digest",
            extra={
                "organization_id": str(self._org_id),
                "target_date": (target_date or date.today()).isoformat(),
            }
        )

        try:
            # 1. ファクト収集
            facts = await self._fact_collector.collect_daily(target_date)

            # 2. 分析
            analysis = await self._analyzer.analyze(facts)

            # 3. フィードバック生成
            feedback = await self._feedback_generator.generate_daily_digest(
                facts=facts,
                analysis=analysis,
            )

            # 4. 配信（オプション）
            delivery_result = None
            if deliver:
                delivery_result = await self._delivery.deliver(feedback)

            self._logger.info(
                "Daily digest generated successfully",
                extra={
                    "organization_id": str(self._org_id),
                    "feedback_id": feedback.feedback_id,
                    "item_count": len(feedback.items),
                    "delivered": deliver and delivery_result is not None and delivery_result.success,
                }
            )

            return feedback, delivery_result

        except FeatureDisabledError:
            raise
        except Exception as e:
            self._logger.error(
                "Failed to generate daily digest",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            raise CEOFeedbackEngineError(
                message="デイリーダイジェストの生成に失敗しました",
                operation="daily_digest",
                original_exception=e,
            )

    # =========================================================================
    # ウィークリーレビュー
    # =========================================================================

    async def generate_weekly_review(
        self,
        week_start: Optional[date] = None,
        deliver: bool = True,
    ) -> Tuple[CEOFeedback, Optional[DeliveryResult]]:
        """
        ウィークリーレビューを生成・配信

        毎週月曜9:00に配信する「先週の振り返り + 今週の注目点」を生成。

        Args:
            week_start: 週の開始日（月曜日）、デフォルトは先週
            deliver: 配信するか（デフォルト: True）

        Returns:
            Tuple[CEOFeedback, Optional[DeliveryResult]]:
                生成されたフィードバックと配信結果
        """
        if not self._settings.enable_weekly_review:
            raise FeatureDisabledError(
                message="ウィークリーレビュー機能は無効化されています",
                operation="weekly_review",
            )

        # 週の開始日を計算
        if week_start is None:
            today = date.today()
            week_start = today - timedelta(days=today.weekday() + 7)  # 先週の月曜日

        week_end = week_start + timedelta(days=6)

        self._logger.info(
            "Generating weekly review",
            extra={
                "organization_id": str(self._org_id),
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
            }
        )

        try:
            # 1. 週のファクト収集
            weekly_facts = await self._fact_collector.collect_weekly(week_start)

            # 2. 週全体の分析（最新のファクトを使用）
            if weekly_facts:
                combined_analysis = await self._analyzer.analyze(
                    weekly_facts[-1],
                    historical_facts=weekly_facts[:-1] if len(weekly_facts) > 1 else None,
                )
            else:
                combined_analysis = AnalysisResult()

            # 3. フィードバック生成
            feedback = await self._feedback_generator.generate_weekly_review(
                weekly_facts=weekly_facts,
                weekly_analysis=combined_analysis,
                week_start=week_start,
                week_end=week_end,
            )

            # 4. 配信（オプション）
            delivery_result = None
            if deliver:
                delivery_result = await self._delivery.deliver(feedback)

            return feedback, delivery_result

        except FeatureDisabledError:
            raise
        except Exception as e:
            self._logger.error(
                "Failed to generate weekly review",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            raise CEOFeedbackEngineError(
                message="ウィークリーレビューの生成に失敗しました",
                operation="weekly_review",
                original_exception=e,
            )

    # =========================================================================
    # リアルタイムアラート
    # =========================================================================

    async def send_realtime_alert(
        self,
        anomaly: Anomaly,
        facts: Optional[DailyFacts] = None,
    ) -> Tuple[CEOFeedback, Optional[DeliveryResult]]:
        """
        リアルタイムアラートを送信

        重要な変化を即座に通知。

        Args:
            anomaly: 検出された異常
            facts: 関連するファクト（オプション）

        Returns:
            Tuple[CEOFeedback, Optional[DeliveryResult]]:
                生成されたフィードバックと配信結果
        """
        if not self._settings.enable_realtime_alert:
            raise FeatureDisabledError(
                message="リアルタイムアラート機能は無効化されています",
                operation="realtime_alert",
            )

        self._logger.info(
            "Sending realtime alert",
            extra={
                "organization_id": str(self._org_id),
                "anomaly_type": anomaly.anomaly_type,
                "severity": anomaly.severity.value,
            }
        )

        try:
            # 1. フィードバック生成
            feedback = await self._feedback_generator.generate_realtime_alert(
                anomaly=anomaly,
                facts=facts,
            )

            # 2. 即時配信
            delivery_result = await self._delivery.deliver(feedback)

            return feedback, delivery_result

        except FeatureDisabledError:
            raise
        except Exception as e:
            self._logger.error(
                "Failed to send realtime alert",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            raise CEOFeedbackEngineError(
                message="リアルタイムアラートの送信に失敗しました",
                operation="realtime_alert",
                original_exception=e,
            )

    # =========================================================================
    # オンデマンド分析
    # =========================================================================

    async def analyze_on_demand(
        self,
        query: str,
        deliver: bool = False,
    ) -> Tuple[CEOFeedback, Optional[DeliveryResult]]:
        """
        オンデマンド分析を実行

        「最近どう？」などの質問に対する深掘り分析を実行。

        Args:
            query: ユーザーの質問
            deliver: 配信するか（デフォルト: False）

        Returns:
            Tuple[CEOFeedback, Optional[DeliveryResult]]:
                生成されたフィードバックと配信結果
        """
        if not self._settings.enable_on_demand:
            raise FeatureDisabledError(
                message="オンデマンド分析機能は無効化されています",
                operation="on_demand",
            )

        self._logger.info(
            "Executing on-demand analysis",
            extra={
                "organization_id": str(self._org_id),
                "query": query[:50],
            }
        )

        try:
            # 1. ファクト収集
            facts = await self._fact_collector.collect_daily()

            # 2. 分析
            analysis = await self._analyzer.analyze(facts)

            # 3. フィードバック生成
            feedback = await self._feedback_generator.generate_on_demand_analysis(
                query=query,
                facts=facts,
                analysis=analysis,
            )

            # 4. 配信（オプション）
            delivery_result = None
            if deliver:
                delivery_result = await self._delivery.deliver(feedback)

            return feedback, delivery_result

        except FeatureDisabledError:
            raise
        except Exception as e:
            self._logger.error(
                "Failed to execute on-demand analysis",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            raise CEOFeedbackEngineError(
                message="オンデマンド分析の実行に失敗しました",
                operation="on_demand",
                original_exception=e,
            )

    # =========================================================================
    # スケジュール配信チェック
    # =========================================================================

    async def run_scheduled_tasks(
        self,
        now: Optional[datetime] = None,
    ) -> List[DeliveryResult]:
        """
        スケジュールされたタスクを実行

        現在時刻に基づいて、配信すべきフィードバックを生成・配信。

        Args:
            now: 現在時刻（テスト用）

        Returns:
            List[DeliveryResult]: 配信結果のリスト
        """
        now = now or datetime.now()
        results = []

        self._logger.info(
            "Running scheduled tasks",
            extra={
                "organization_id": str(self._org_id),
                "current_time": now.isoformat(),
            }
        )

        # デイリーダイジェスト
        if self._delivery.should_deliver_daily_digest(now):
            try:
                _, result = await self.generate_daily_digest(deliver=True)
                if result:
                    results.append(result)
            except Exception as e:
                self._logger.error(
                    "Failed to deliver daily digest",
                    extra={"error": str(e)}
                )

        # ウィークリーレビュー
        if self._delivery.should_deliver_weekly_review(now):
            try:
                _, result = await self.generate_weekly_review(deliver=True)
                if result:
                    results.append(result)
            except Exception as e:
                self._logger.error(
                    "Failed to deliver weekly review",
                    extra={"error": str(e)}
                )

        # マンスリーインサイト
        if self._delivery.should_deliver_monthly_insight(now):
            # TODO: マンスリーインサイトの実装
            pass

        return results

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    async def get_recent_feedbacks(
        self,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        最近のフィードバック配信履歴を取得

        Args:
            limit: 取得件数

        Returns:
            List[Dict[str, Any]]: フィードバック履歴
        """
        try:
            result = self._conn.execute(text("""
                SELECT
                    id,
                    feedback_id,
                    feedback_type,
                    channel,
                    channel_target,
                    delivered_at,
                    created_at
                FROM feedback_deliveries
                WHERE organization_id = :org_id
                ORDER BY delivered_at DESC
                LIMIT :limit
            """), {
                "org_id": str(self._org_id),
                "limit": limit,
            })

            feedbacks = []
            for row in result.fetchall():
                feedbacks.append({
                    "id": str(row[0]),
                    "feedback_id": row[1],
                    "feedback_type": row[2],
                    "channel": row[3],
                    "channel_target": row[4],
                    "delivered_at": row[5].isoformat() if row[5] else None,
                    "created_at": row[6].isoformat() if row[6] else None,
                })

            return feedbacks

        except Exception as e:
            self._logger.warning(
                "Failed to get recent feedbacks",
                extra={"error": str(e)}
            )
            return []

    async def check_health(self) -> Dict[str, Any]:
        """
        システムの健全性をチェック

        Returns:
            Dict[str, Any]: ヘルスチェック結果
        """
        health = {
            "status": "healthy",
            "components": {},
            "checked_at": datetime.now().isoformat(),
        }

        # DBコネクションチェック
        try:
            self._conn.execute(text("SELECT 1"))
            health["components"]["database"] = "ok"
        except Exception as e:
            health["components"]["database"] = f"error: {str(e)}"
            health["status"] = "unhealthy"

        # 設定チェック
        health["components"]["settings"] = {
            "daily_digest": "enabled" if self._settings.enable_daily_digest else "disabled",
            "weekly_review": "enabled" if self._settings.enable_weekly_review else "disabled",
            "realtime_alert": "enabled" if self._settings.enable_realtime_alert else "disabled",
            "on_demand": "enabled" if self._settings.enable_on_demand else "disabled",
        }

        return health


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_ceo_feedback_engine(
    conn: Connection,
    organization_id: UUID,
    recipient_user_id: UUID,
    recipient_name: str,
    chatwork_room_id: Optional[int] = None,
) -> CEOFeedbackEngine:
    """
    CEOFeedbackEngineを作成

    Args:
        conn: データベース接続
        organization_id: 組織ID
        recipient_user_id: 受信者ユーザーID（CEO）
        recipient_name: 受信者の名前
        chatwork_room_id: ChatWorkルームID（オプション）

    Returns:
        CEOFeedbackEngine: フィードバックエンジン
    """
    settings = CEOFeedbackSettings(
        recipient_user_id=recipient_user_id,
        recipient_name=recipient_name,
        chatwork_room_id=chatwork_room_id,
    )

    return CEOFeedbackEngine(
        conn=conn,
        organization_id=organization_id,
        settings=settings,
    )


async def get_ceo_feedback_engine_for_organization(
    conn: Connection,
    organization_id: UUID,
) -> Optional[CEOFeedbackEngine]:
    """
    組織のCEOフィードバックエンジンを取得

    CEOの情報をDBから取得してエンジンを初期化する。

    Args:
        conn: データベース接続
        organization_id: 組織ID

    Returns:
        CEOFeedbackEngine: フィードバックエンジン（CEOが見つからない場合はNone）
    """
    try:
        # CEO（role='ceo'または最上位管理者）を取得
        result = conn.execute(text("""
            SELECT
                u.id,
                u.name,
                cu.chatwork_account_id
            FROM users u
            LEFT JOIN chatwork_users cu ON u.id = cu.user_id
            WHERE u.organization_id = :org_id
              AND u.is_active = TRUE
              AND (u.role = 'ceo' OR u.role = 'admin')
            ORDER BY
                CASE u.role
                    WHEN 'ceo' THEN 1
                    WHEN 'admin' THEN 2
                    ELSE 3
                END
            LIMIT 1
        """), {
            "org_id": str(organization_id),
        })

        row = result.fetchone()
        if not row:
            return None

        # DMルームIDを取得（あれば）
        chatwork_room_id = None
        if row[2]:  # chatwork_account_id がある場合
            try:
                # DMルームを取得
                dm_result = conn.execute(text("""
                    SELECT room_id FROM chatwork_dm_rooms
                    WHERE account_id = :account_id
                    LIMIT 1
                """), {
                    "account_id": row[2],
                })
                dm_row = dm_result.fetchone()
                if dm_row:
                    chatwork_room_id = dm_row[0]
            except Exception:
                pass

        return create_ceo_feedback_engine(
            conn=conn,
            organization_id=organization_id,
            recipient_user_id=UUID(str(row[0])),
            recipient_name=row[1] or "CEO",
            chatwork_room_id=chatwork_room_id,
        )

    except Exception as e:
        import logging
        logging.getLogger("feedback.engine").error(
            "Failed to get CEO feedback engine",
            extra={
                "organization_id": str(organization_id),
                "error": str(e),
            }
        )
        return None
