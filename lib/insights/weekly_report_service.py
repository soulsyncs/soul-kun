"""
Phase 2 進化版: 週次レポート管理サービス

このモジュールは、soulkun_weekly_reports テーブルのCRUD操作と
週次レポートの生成・送信ロジックを提供します。

設計書: docs/06_phase2_a1_pattern_detection.md

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-23
Version: 1.0
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import json
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lib.detection.constants import (
    Classification,
    DetectionParameters,
    Importance,
    InsightStatus,
    InsightType,
    NotificationType,
    WeeklyReportStatus,
)
from lib.detection.exceptions import (
    DatabaseError,
    NotificationError,
    ValidationError,
    wrap_database_error,
)


# ================================================================
# データクラス
# ================================================================

@dataclass
class WeeklyReportRecord:
    """
    週次レポートレコード

    soulkun_weekly_reports テーブルの1レコードを表現

    Attributes:
        id: レポートID
        organization_id: 組織ID
        week_start: 週の開始日（月曜日）
        week_end: 週の終了日（日曜日）
        report_content: レポート本文（マークダウン）
        insights_summary: インサイトのサマリー（JSON）
        included_insight_ids: 含まれるインサイトのIDリスト
        sent_at: 送信日時
        sent_to: 送信先ユーザーIDリスト
        sent_via: 送信方法
        chatwork_room_id: ChatWork room_id
        chatwork_message_id: ChatWork message_id
        status: ステータス
        error_message: エラーメッセージ
        retry_count: リトライ回数
        classification: 機密区分
        created_by: 作成者ID
        updated_by: 更新者ID
        created_at: 作成日時
        updated_at: 更新日時
    """

    id: UUID
    organization_id: UUID
    week_start: date
    week_end: date
    report_content: str
    insights_summary: dict[str, Any]
    included_insight_ids: list[UUID]
    sent_at: Optional[datetime]
    sent_to: list[UUID]
    sent_via: Optional[str]
    chatwork_room_id: Optional[int]
    chatwork_message_id: Optional[str]
    status: str
    error_message: Optional[str]
    retry_count: int
    classification: str
    created_by: Optional[UUID]
    updated_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """
        辞書形式に変換

        Returns:
            週次レポートデータの辞書
        """
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "week_start": self.week_start.isoformat(),
            "week_end": self.week_end.isoformat(),
            "report_content": self.report_content,
            "insights_summary": self.insights_summary,
            "included_insight_ids": [str(uid) for uid in self.included_insight_ids],
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "sent_to": [str(uid) for uid in self.sent_to] if self.sent_to else [],
            "sent_via": self.sent_via,
            "chatwork_room_id": self.chatwork_room_id,
            "chatwork_message_id": self.chatwork_message_id,
            "status": self.status,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "classification": self.classification,
            "created_by": str(self.created_by) if self.created_by else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class ReportInsightItem:
    """
    週次レポートに含めるインサイト項目

    Attributes:
        id: インサイトID
        insight_type: インサイトタイプ
        importance: 重要度
        title: タイトル
        description: 説明
        recommended_action: 推奨アクション
        status: ステータス
        created_at: 作成日時
    """

    id: UUID
    insight_type: str
    importance: str
    title: str
    description: str
    recommended_action: Optional[str]
    status: str
    created_at: datetime


@dataclass
class GeneratedReport:
    """
    生成されたレポートデータ

    Attributes:
        content: レポート本文（マークダウン）
        summary: インサイトのサマリー
        insight_ids: 含まれるインサイトのIDリスト
    """

    content: str
    summary: dict[str, Any]
    insight_ids: list[UUID]


# ================================================================
# WeeklyReportService クラス
# ================================================================

class WeeklyReportService:
    """
    週次レポート管理サービス

    soulkun_weekly_reports テーブルへのCRUD操作と
    週次レポートの生成・送信ロジックを提供

    使用例:
        >>> service = WeeklyReportService(conn, org_id)
        >>>
        >>> # 今週のレポートを生成
        >>> report = await service.generate_weekly_report()
        >>>
        >>> # レポートを送信
        >>> await service.send_report(report.id, room_id=12345)

    Attributes:
        conn: データベース接続
        org_id: 組織ID
    """

    # レポートテンプレート
    REPORT_TEMPLATE = """# ソウルくん週次レポート

**期間**: {week_start} ～ {week_end}
**組織**: {organization_name}

---

## 📊 サマリー

- **総件数**: {total}件
- **重要度別**:
  - 🔴 Critical: {critical}件
  - 🟠 High: {high}件
  - 🟡 Medium: {medium}件
  - 🟢 Low: {low}件

---

## 📋 今週の気づき

{insights_section}

---

## 💡 推奨アクション

{actions_section}

---

_このレポートはソウルくんが自動生成しました。_
_ご不明な点があれば、お気軽にお声がけくださいウル！_
"""

    INSIGHT_ITEM_TEMPLATE = """### {index}. {title}

**重要度**: {importance_emoji} {importance}
**タイプ**: {insight_type}
**検出日**: {created_at}

{description}
"""

    ACTION_ITEM_TEMPLATE = """- **{title}**: {action}
"""

    def __init__(self, conn: Connection, org_id: UUID) -> None:
        """
        WeeklyReportServiceを初期化

        Args:
            conn: データベース接続（SQLAlchemy Connection）
            org_id: 組織ID（UUID）
        """
        self._conn = conn
        self._org_id = org_id

        # ロガーの初期化
        try:
            from lib.logging import get_logger
            self._logger = get_logger("insights.weekly_report")
        except ImportError:
            import logging
            self._logger = logging.getLogger("insights.weekly_report")

    # ================================================================
    # プロパティ
    # ================================================================

    @property
    def conn(self) -> Connection:
        """データベース接続を取得"""
        return self._conn

    @property
    def org_id(self) -> UUID:
        """組織IDを取得"""
        return self._org_id

    # ================================================================
    # 週次レポート生成
    # ================================================================

    async def generate_weekly_report(
        self,
        week_start: Optional[date] = None,
        organization_name: str = "組織",
    ) -> Optional[UUID]:
        """
        週次レポートを生成

        指定された週（デフォルトは先週）のインサイトをまとめて
        週次レポートを生成し、DBに保存

        Args:
            week_start: 週の開始日（月曜日）、Noneの場合は先週
            organization_name: 組織名（レポート表示用）

        Returns:
            UUID: 作成されたレポートのID（インサイトがない場合はNone）

        Raises:
            DatabaseError: データベースエラー
        """
        # 週の開始日・終了日を計算
        if week_start is None:
            # 先週の月曜日
            today = date.today()
            week_start = today - timedelta(days=today.weekday() + 7)

        week_end = week_start + timedelta(days=6)

        self._logger.info(
            "Generating weekly report",
            extra={
                "organization_id": str(self._org_id),
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
            }
        )

        # 既存のレポートがあるか確認
        existing = await self.get_report_by_week(week_start)
        if existing:
            self._logger.info(
                "Weekly report already exists",
                extra={
                    "organization_id": str(self._org_id),
                    "report_id": str(existing.id),
                }
            )
            return existing.id

        # 対象期間のインサイトを取得
        insights = await self._get_insights_for_report(week_start, week_end)

        if not insights:
            self._logger.info(
                "No insights for weekly report",
                extra={
                    "organization_id": str(self._org_id),
                    "week_start": week_start.isoformat(),
                }
            )
            return None

        # レポートを生成
        generated = self._generate_report_content(
            insights=insights,
            week_start=week_start,
            week_end=week_end,
            organization_name=organization_name,
        )

        # DBに保存
        report_id = await self._save_report(
            week_start=week_start,
            week_end=week_end,
            content=generated.content,
            summary=generated.summary,
            insight_ids=generated.insight_ids,
        )

        self._logger.info(
            "Weekly report generated",
            extra={
                "organization_id": str(self._org_id),
                "report_id": str(report_id),
                "insight_count": len(insights),
            }
        )

        return report_id

    async def _get_insights_for_report(
        self,
        week_start: date,
        week_end: date,
    ) -> list[ReportInsightItem]:
        """
        週次レポート用のインサイトを取得

        Args:
            week_start: 週の開始日
            week_end: 週の終了日

        Returns:
            list[ReportInsightItem]: インサイト項目のリスト
        """
        try:
            # 週の終了日は23:59:59まで含める
            end_datetime = datetime.combine(week_end, datetime.max.time())

            # 機密情報漏洩防止: confidential/restricted は週次レポートに含めない
            # （Codex HIGH指摘対応: 送信先が広い場合のリスク軽減）
            result = self._conn.execute(text("""
                SELECT
                    id,
                    insight_type,
                    importance,
                    title,
                    description,
                    recommended_action,
                    status,
                    created_at
                FROM soulkun_insights
                WHERE organization_id = :org_id
                  AND created_at >= :week_start
                  AND created_at <= :week_end
                  AND status IN ('new', 'acknowledged')
                  AND classification IN ('public', 'internal')
                ORDER BY
                    CASE importance
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END,
                    created_at DESC
            """), {
                "org_id": str(self._org_id),
                "week_start": week_start,
                "week_end": end_datetime,
            })

            return [
                ReportInsightItem(
                    id=UUID(str(row[0])),
                    insight_type=row[1],
                    importance=row[2],
                    title=row[3],
                    description=row[4],
                    recommended_action=row[5],
                    status=row[6],
                    created_at=row[7],
                )
                for row in result.fetchall()
            ]

        except Exception as e:
            raise wrap_database_error(e, "get insights for report")

    def _generate_report_content(
        self,
        insights: list[ReportInsightItem],
        week_start: date,
        week_end: date,
        organization_name: str,
    ) -> GeneratedReport:
        """
        レポート本文を生成

        Args:
            insights: インサイト項目のリスト
            week_start: 週の開始日
            week_end: 週の終了日
            organization_name: 組織名

        Returns:
            GeneratedReport: 生成されたレポート
        """
        # サマリーを計算
        summary = {
            "total": len(insights),
            "by_importance": {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
            },
            "by_type": {},
        }

        for insight in insights:
            # 重要度別カウント
            if insight.importance in summary["by_importance"]:
                summary["by_importance"][insight.importance] += 1

            # タイプ別カウント
            if insight.insight_type not in summary["by_type"]:
                summary["by_type"][insight.insight_type] = 0
            summary["by_type"][insight.insight_type] += 1

        # インサイトセクションを生成
        insights_section = ""
        for i, insight in enumerate(insights, 1):
            importance_emoji = self._get_importance_emoji(insight.importance)
            insights_section += self.INSIGHT_ITEM_TEMPLATE.format(
                index=i,
                title=insight.title,
                importance_emoji=importance_emoji,
                importance=insight.importance.upper(),
                insight_type=self._get_insight_type_label(insight.insight_type),
                created_at=insight.created_at.strftime("%Y-%m-%d %H:%M"),
                description=insight.description,
            )
            insights_section += "\n"

        # 推奨アクションセクションを生成
        actions_section = ""
        for insight in insights:
            if insight.recommended_action:
                actions_section += self.ACTION_ITEM_TEMPLATE.format(
                    title=insight.title,
                    action=insight.recommended_action,
                )

        if not actions_section:
            actions_section = "_今週の推奨アクションはありません。_"

        # レポート本文を生成
        content = self.REPORT_TEMPLATE.format(
            week_start=week_start.strftime("%Y/%m/%d"),
            week_end=week_end.strftime("%Y/%m/%d"),
            organization_name=organization_name,
            total=summary["total"],
            critical=summary["by_importance"]["critical"],
            high=summary["by_importance"]["high"],
            medium=summary["by_importance"]["medium"],
            low=summary["by_importance"]["low"],
            insights_section=insights_section if insights_section else "_今週の気づきはありません。_",
            actions_section=actions_section,
        )

        return GeneratedReport(
            content=content,
            summary=summary,
            insight_ids=[insight.id for insight in insights],
        )

    def _get_importance_emoji(self, importance: str) -> str:
        """
        重要度に対応する絵文字を取得

        Args:
            importance: 重要度

        Returns:
            str: 絵文字
        """
        emoji_map = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
        }
        return emoji_map.get(importance, "⚪")

    def _get_insight_type_label(self, insight_type: str) -> str:
        """
        インサイトタイプのラベルを取得

        Args:
            insight_type: インサイトタイプ

        Returns:
            str: ラベル
        """
        label_map = {
            "pattern_detected": "頻出パターン検出",
            "personalization_risk": "属人化リスク",
            "bottleneck": "ボトルネック",
            "emotion_change": "感情変化",
        }
        return label_map.get(insight_type, insight_type)

    async def _save_report(
        self,
        week_start: date,
        week_end: date,
        content: str,
        summary: dict[str, Any],
        insight_ids: list[UUID],
    ) -> UUID:
        """
        レポートをDBに保存

        Args:
            week_start: 週の開始日
            week_end: 週の終了日
            content: レポート本文
            summary: サマリー
            insight_ids: インサイトIDリスト

        Returns:
            UUID: 作成されたレポートのID
        """
        try:
            # ON CONFLICT DO NOTHINGで同週の重複を防止（Codex MEDIUM指摘対応）
            result = self._conn.execute(text("""
                INSERT INTO soulkun_weekly_reports (
                    organization_id,
                    week_start,
                    week_end,
                    report_content,
                    insights_summary,
                    included_insight_ids,
                    status,
                    classification,
                    created_at,
                    updated_at
                ) VALUES (
                    :organization_id,
                    :week_start,
                    :week_end,
                    :report_content,
                    :insights_summary,
                    :included_insight_ids,
                    :status,
                    :classification,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT ON CONSTRAINT uq_soulkun_weekly_reports_org_week
                DO NOTHING
                RETURNING id
            """), {
                "organization_id": str(self._org_id),
                "week_start": week_start,
                "week_end": week_end,
                "report_content": content,
                "insights_summary": json.dumps(summary),
                "included_insight_ids": [str(uid) for uid in insight_ids],
                "status": WeeklyReportStatus.DRAFT.value,
                "classification": Classification.INTERNAL.value,
            })

            row = result.fetchone()

            if row is not None:
                # 新規挿入成功
                return UUID(str(row[0]))

            # 重複検出 - 既存のレポートを取得
            existing = self._conn.execute(text("""
                SELECT id FROM soulkun_weekly_reports
                WHERE organization_id = :org_id
                  AND week_start = :week_start
            """), {
                "org_id": str(self._org_id),
                "week_start": week_start,
            })
            existing_row = existing.fetchone()
            if existing_row is None:
                raise DatabaseError(
                    message="Conflict occurred but existing report not found",
                    details={"week_start": week_start.isoformat()}
                )
            return UUID(str(existing_row[0]))

        except DatabaseError:
            raise
        except Exception as e:
            raise wrap_database_error(e, "save weekly report")

    # ================================================================
    # レポート取得
    # ================================================================

    async def get_report(self, report_id: UUID) -> Optional[WeeklyReportRecord]:
        """
        レポートを取得

        Args:
            report_id: レポートID

        Returns:
            WeeklyReportRecord: レポートレコード（存在しない場合はNone）

        Raises:
            DatabaseError: データベースエラー
        """
        try:
            result = self._conn.execute(text("""
                SELECT
                    id,
                    organization_id,
                    week_start,
                    week_end,
                    report_content,
                    insights_summary,
                    included_insight_ids,
                    sent_at,
                    sent_to,
                    sent_via,
                    chatwork_room_id,
                    chatwork_message_id,
                    status,
                    error_message,
                    retry_count,
                    classification,
                    created_by,
                    updated_by,
                    created_at,
                    updated_at
                FROM soulkun_weekly_reports
                WHERE organization_id = :org_id
                  AND id = :report_id
            """), {
                "org_id": str(self._org_id),
                "report_id": str(report_id),
            })

            row = result.fetchone()
            if row is None:
                return None

            return self._row_to_record(row)

        except Exception as e:
            raise wrap_database_error(e, "get weekly report")

    async def get_report_by_week(self, week_start: date) -> Optional[WeeklyReportRecord]:
        """
        指定週のレポートを取得

        Args:
            week_start: 週の開始日（月曜日）

        Returns:
            WeeklyReportRecord: レポートレコード（存在しない場合はNone）

        Raises:
            DatabaseError: データベースエラー
        """
        try:
            result = self._conn.execute(text("""
                SELECT
                    id,
                    organization_id,
                    week_start,
                    week_end,
                    report_content,
                    insights_summary,
                    included_insight_ids,
                    sent_at,
                    sent_to,
                    sent_via,
                    chatwork_room_id,
                    chatwork_message_id,
                    status,
                    error_message,
                    retry_count,
                    classification,
                    created_by,
                    updated_by,
                    created_at,
                    updated_at
                FROM soulkun_weekly_reports
                WHERE organization_id = :org_id
                  AND week_start = :week_start
            """), {
                "org_id": str(self._org_id),
                "week_start": week_start,
            })

            row = result.fetchone()
            if row is None:
                return None

            return self._row_to_record(row)

        except Exception as e:
            raise wrap_database_error(e, "get weekly report by week")

    async def get_reports(
        self,
        limit: int = 10,
        offset: int = 0,
        status: Optional[WeeklyReportStatus] = None,
    ) -> list[WeeklyReportRecord]:
        """
        レポート一覧を取得

        Args:
            limit: 取得件数（デフォルト: 10、最大: 100）
            offset: オフセット（デフォルト: 0）
            status: ステータスフィルタ（オプション）

        Returns:
            list[WeeklyReportRecord]: レポートレコードのリスト

        Raises:
            DatabaseError: データベースエラー
        """
        if limit > 100:
            limit = 100

        try:
            params: dict[str, Any] = {
                "org_id": str(self._org_id),
                "limit": limit,
                "offset": offset,
            }

            status_clause = ""
            if status:
                status_clause = "AND status = :status"
                params["status"] = status.value

            result = self._conn.execute(text(f"""
                SELECT
                    id,
                    organization_id,
                    week_start,
                    week_end,
                    report_content,
                    insights_summary,
                    included_insight_ids,
                    sent_at,
                    sent_to,
                    sent_via,
                    chatwork_room_id,
                    chatwork_message_id,
                    status,
                    error_message,
                    retry_count,
                    classification,
                    created_by,
                    updated_by,
                    created_at,
                    updated_at
                FROM soulkun_weekly_reports
                WHERE organization_id = :org_id
                  {status_clause}
                ORDER BY week_start DESC
                LIMIT :limit OFFSET :offset
            """), params)

            return [self._row_to_record(row) for row in result.fetchall()]

        except Exception as e:
            raise wrap_database_error(e, "get weekly reports")

    async def get_pending_reports(self) -> list[WeeklyReportRecord]:
        """
        送信待ちのレポートを取得

        draft または failed ステータスのレポートを取得

        Returns:
            list[WeeklyReportRecord]: レポートレコードのリスト

        Raises:
            DatabaseError: データベースエラー
        """
        try:
            result = self._conn.execute(text("""
                SELECT
                    id,
                    organization_id,
                    week_start,
                    week_end,
                    report_content,
                    insights_summary,
                    included_insight_ids,
                    sent_at,
                    sent_to,
                    sent_via,
                    chatwork_room_id,
                    chatwork_message_id,
                    status,
                    error_message,
                    retry_count,
                    classification,
                    created_by,
                    updated_by,
                    created_at,
                    updated_at
                FROM soulkun_weekly_reports
                WHERE organization_id = :org_id
                  AND status IN ('draft', 'failed')
                  AND retry_count < 3
                ORDER BY week_start DESC
            """), {
                "org_id": str(self._org_id),
            })

            return [self._row_to_record(row) for row in result.fetchall()]

        except Exception as e:
            raise wrap_database_error(e, "get pending reports")

    # ================================================================
    # レポート送信
    # ================================================================

    async def mark_as_sent(
        self,
        report_id: UUID,
        sent_to: list[UUID],
        sent_via: str,
        chatwork_room_id: Optional[int] = None,
        chatwork_message_id: Optional[str] = None,
    ) -> bool:
        """
        レポートを送信済みとしてマーク

        Args:
            report_id: レポートID
            sent_to: 送信先ユーザーIDリスト
            sent_via: 送信方法
            chatwork_room_id: ChatWork room_id（オプション）
            chatwork_message_id: ChatWork message_id（オプション）

        Returns:
            bool: 更新成功したかどうか

        Raises:
            DatabaseError: データベースエラー
        """
        self._logger.info(
            "Marking report as sent",
            extra={
                "organization_id": str(self._org_id),
                "report_id": str(report_id),
                "sent_via": sent_via,
            }
        )

        try:
            # レポートの週開始日を取得（冪等性キー用）
            week_result = self._conn.execute(text("""
                SELECT week_start FROM soulkun_weekly_reports
                WHERE organization_id = :org_id AND id = :report_id
            """), {
                "org_id": str(self._org_id),
                "report_id": str(report_id),
            })
            week_row = week_result.fetchone()
            week_start = week_row[0] if week_row else date.today()

            result = self._conn.execute(text("""
                UPDATE soulkun_weekly_reports
                SET
                    status = :status,
                    sent_at = CURRENT_TIMESTAMP,
                    sent_to = :sent_to,
                    sent_via = :sent_via,
                    chatwork_room_id = :chatwork_room_id,
                    chatwork_message_id = :chatwork_message_id,
                    error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = :org_id
                  AND id = :report_id
            """), {
                "org_id": str(self._org_id),
                "report_id": str(report_id),
                "status": WeeklyReportStatus.SENT.value,
                "sent_to": [str(uid) for uid in sent_to],
                "sent_via": sent_via,
                "chatwork_room_id": chatwork_room_id,
                "chatwork_message_id": chatwork_message_id,
            })

            updated = result.rowcount > 0

            # 冪等性確保: notification_logsに記録（Codex HIGH指摘対応）
            # 二重通知を防止するため、ON CONFLICT DO NOTHINGを使用
            if updated:
                # target_type='system'を使用（設計書の既存定義に合わせる: Codex MEDIUM指摘対応）
                # target_id には週開始日とレポートIDを組み合わせて冪等性を確保
                self._conn.execute(text("""
                    INSERT INTO notification_logs (
                        organization_id,
                        notification_type,
                        target_type,
                        target_id,
                        notification_date,
                        status,
                        channel,
                        channel_target
                    )
                    VALUES (
                        :org_id,
                        :notification_type,
                        'system',
                        :target_id,
                        :notification_date,
                        'success',
                        :channel,
                        :channel_target
                    )
                    ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
                    DO NOTHING
                """), {
                    "org_id": str(self._org_id),
                    "notification_type": NotificationType.WEEKLY_REPORT.value,
                    "target_id": f"weekly_report:{report_id}",
                    "notification_date": week_start,
                    "channel": sent_via,
                    "channel_target": str(chatwork_room_id) if chatwork_room_id else None,
                })

            return updated

        except Exception as e:
            raise wrap_database_error(e, "mark report as sent")

    async def mark_as_failed(
        self,
        report_id: UUID,
        error_message: str,
    ) -> bool:
        """
        レポートを送信失敗としてマーク

        Args:
            report_id: レポートID
            error_message: エラーメッセージ

        Returns:
            bool: 更新成功したかどうか

        Raises:
            DatabaseError: データベースエラー
        """
        self._logger.warning(
            "Marking report as failed",
            extra={
                "organization_id": str(self._org_id),
                "report_id": str(report_id),
                "error_message": error_message[:100],
            }
        )

        try:
            result = self._conn.execute(text("""
                UPDATE soulkun_weekly_reports
                SET
                    status = :status,
                    error_message = :error_message,
                    retry_count = retry_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = :org_id
                  AND id = :report_id
            """), {
                "org_id": str(self._org_id),
                "report_id": str(report_id),
                "status": WeeklyReportStatus.FAILED.value,
                "error_message": error_message[:500],  # エラーメッセージは500文字まで
            })

            return result.rowcount > 0

        except Exception as e:
            raise wrap_database_error(e, "mark report as failed")

    # ================================================================
    # ChatWork送信ヘルパー
    # ================================================================

    def format_for_chatwork(self, report: WeeklyReportRecord) -> str:
        """
        ChatWork用にレポートをフォーマット

        マークダウンをChatWork形式に変換

        Args:
            report: レポートレコード

        Returns:
            str: ChatWork形式のメッセージ
        """
        content = report.report_content

        # マークダウンの変換
        # # -> [title]
        # ## -> [subtitle]
        # ### -> [info]

        lines = content.split("\n")
        formatted_lines = []
        in_info_block = False

        for line in lines:
            if line.startswith("### "):
                # ### はインフォブロックの開始
                if in_info_block:
                    formatted_lines.append("[/info]")
                formatted_lines.append(f"[info][title]{line[4:]}[/title]")
                in_info_block = True
            elif line.startswith("## "):
                # ## はサブタイトル
                if in_info_block:
                    formatted_lines.append("[/info]")
                    in_info_block = False
                formatted_lines.append(f"\n[hr]\n{line[3:]}")
            elif line.startswith("# "):
                # # はタイトル
                if in_info_block:
                    formatted_lines.append("[/info]")
                    in_info_block = False
                formatted_lines.append(f"[title]{line[2:]}[/title]")
            elif line.startswith("---"):
                # 区切り線
                if in_info_block:
                    formatted_lines.append("[/info]")
                    in_info_block = False
                formatted_lines.append("[hr]")
            elif line.startswith("**") and line.endswith("**"):
                # 太字（行全体）
                formatted_lines.append(line.replace("**", ""))
            elif line.startswith("- "):
                # リスト項目
                formatted_lines.append(f"・{line[2:]}")
            elif line.startswith("_") and line.endswith("_"):
                # イタリック（補足説明）
                formatted_lines.append(line.replace("_", ""))
            else:
                formatted_lines.append(line)

        if in_info_block:
            formatted_lines.append("[/info]")

        return "\n".join(formatted_lines)

    # ================================================================
    # ユーティリティ
    # ================================================================

    def get_current_week_start(self) -> date:
        """
        今週の月曜日を取得

        Returns:
            date: 今週の月曜日
        """
        today = date.today()
        return today - timedelta(days=today.weekday())

    def get_last_week_start(self) -> date:
        """
        先週の月曜日を取得

        Returns:
            date: 先週の月曜日
        """
        return self.get_current_week_start() - timedelta(days=7)

    def is_report_day(self) -> bool:
        """
        今日がレポート送信日かどうか

        Returns:
            bool: レポート送信日の場合True
        """
        today = date.today()
        return today.weekday() == DetectionParameters.WEEKLY_REPORT_DAY

    # ================================================================
    # ヘルパーメソッド
    # ================================================================

    def _row_to_record(self, row: Any) -> WeeklyReportRecord:
        """
        データベース行をWeeklyReportRecordに変換

        Args:
            row: データベースの行データ

        Returns:
            WeeklyReportRecord: レポートレコード
        """
        return WeeklyReportRecord(
            id=UUID(str(row[0])),
            organization_id=UUID(str(row[1])),
            week_start=row[2],
            week_end=row[3],
            report_content=row[4],
            insights_summary=row[5] if row[5] else {},
            included_insight_ids=[UUID(str(uid)) for uid in (row[6] or [])],
            sent_at=row[7],
            sent_to=[UUID(str(uid)) for uid in (row[8] or [])],
            sent_via=row[9],
            chatwork_room_id=row[10],
            chatwork_message_id=row[11],
            status=row[12],
            error_message=row[13],
            retry_count=row[14],
            classification=row[15],
            created_by=UUID(str(row[16])) if row[16] else None,
            updated_by=UUID(str(row[17])) if row[17] else None,
            created_at=row[18],
            updated_at=row[19],
        )
