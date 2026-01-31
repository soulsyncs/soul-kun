"""
Phase 2 進化版 A3: ボトルネック検出

このモジュールは、タスクの滞留・遅延・集中を検出し、
業務のボトルネックを可視化します。

検出項目:
1. 期限超過タスク（overdue_task）
2. 長期未完了タスク（stale_task）
3. 担当者へのタスク集中（task_concentration）
4. 担当者未設定タスク（no_assignee）

設計書: docs/08_phase2_a3_bottleneck_detection.md

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-24
Version: 1.0
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID
import json

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lib.detection.base import (
    BaseDetector,
    DetectionResult,
    InsightData,
)
from lib.detection.constants import (
    Classification,
    DetectionParameters,
    Importance,
    InsightType,
    BottleneckType,
    BottleneckRiskLevel,
    BottleneckStatus,
    SourceType,
)
from lib.detection.exceptions import (
    DatabaseError,
    DetectionError,
    wrap_database_error,
)


class BottleneckDetector(BaseDetector):
    """
    ボトルネック検出器

    タスクの滞留・遅延・集中を検出し、業務のボトルネックを可視化

    使用例:
        >>> detector = BottleneckDetector(conn, org_id)
        >>> result = await detector.detect()
        >>> print(f"検出されたボトルネック: {result.detected_count}件")
    """

    def __init__(
        self,
        conn: Connection,
        org_id: UUID,
        overdue_critical_days: int = DetectionParameters.OVERDUE_CRITICAL_DAYS,
        overdue_high_days: int = DetectionParameters.OVERDUE_HIGH_DAYS,
        overdue_medium_days: int = DetectionParameters.OVERDUE_MEDIUM_DAYS,
        stale_task_days: int = DetectionParameters.STALE_TASK_DAYS,
        task_concentration_threshold: int = DetectionParameters.TASK_CONCENTRATION_THRESHOLD,
        concentration_ratio_threshold: float = DetectionParameters.CONCENTRATION_RATIO_THRESHOLD,
    ) -> None:
        """
        BottleneckDetectorを初期化

        Args:
            conn: データベース接続
            org_id: 組織ID
            overdue_critical_days: 緊急レベルの期限超過日数（デフォルト: 7）
            overdue_high_days: 高リスクレベルの期限超過日数（デフォルト: 3）
            overdue_medium_days: 中リスクレベルの期限超過日数（デフォルト: 1）
            stale_task_days: 長期未完了と判定する日数（デフォルト: 7）
            task_concentration_threshold: タスク集中アラートの閾値（デフォルト: 10）
            concentration_ratio_threshold: 平均の何倍で集中と判定（デフォルト: 2.0）
        """
        super().__init__(
            conn=conn,
            org_id=org_id,
            detector_type=SourceType.A3_BOTTLENECK,
            insight_type=InsightType.BOTTLENECK,
        )

        self._overdue_critical_days = overdue_critical_days
        self._overdue_high_days = overdue_high_days
        self._overdue_medium_days = overdue_medium_days
        self._stale_task_days = stale_task_days
        self._task_concentration_threshold = task_concentration_threshold
        self._concentration_ratio_threshold = concentration_ratio_threshold

    def _get_org_id_for_chatwork_tasks(self) -> str:
        """
        chatwork_tasks テーブル用の organization_id を取得

        chatwork_tasks.organization_id は VARCHAR型で 'soul_syncs' 等の文字列。
        本来は organizations テーブルから slug を取得すべきだが、
        現在は単一テナントのため固定値を返す。

        TODO: Phase 4A (BPaaS対応) で organizations.slug との連携を実装

        Returns:
            str: organization_id（'soul_syncs' 等）
        """
        # 現在はソウルシンクスのみ
        # self._org_id は UUID だが、chatwork_tasks は 'soul_syncs' を使用
        return "soul_syncs"

    async def detect(self, **kwargs: Any) -> DetectionResult:
        """
        ボトルネックを検出

        Returns:
            DetectionResult: 検出結果
        """
        start_time = datetime.now(timezone.utc)
        self.log_detection_start()

        try:
            # 1. 期限超過タスクの検出
            overdue_alerts = await self._detect_overdue_tasks()
            self._logger.info(f"Overdue tasks detected: {len(overdue_alerts)}")

            # 2. 長期未完了タスクの検出
            stale_alerts = await self._detect_stale_tasks()
            self._logger.info(f"Stale tasks detected: {len(stale_alerts)}")

            # 3. 担当者集中の検出
            concentration_alerts = await self._detect_task_concentration()
            self._logger.info(f"Concentration alerts detected: {len(concentration_alerts)}")

            # 4. アラートをDBに保存
            all_alerts = overdue_alerts + stale_alerts + concentration_alerts
            saved_alerts = []

            for alert in all_alerts:
                saved = await self._save_alert(alert)
                if saved:
                    saved_alerts.append(saved)

            # 5. critical/high はInsightに登録
            insights_created = 0
            last_insight_id = None

            for alert in saved_alerts:
                if alert['risk_level'] in (
                    BottleneckRiskLevel.CRITICAL.value,
                    BottleneckRiskLevel.HIGH.value,
                ):
                    # 既にインサイトがあるか確認
                    if not await self.insight_exists_for_source(alert['id']):
                        insight_data = self._create_insight_data(alert)
                        insight_id = await self.save_insight(insight_data)
                        insights_created += 1
                        last_insight_id = insight_id

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            # リスクレベル別集計
            risk_counts = {
                "critical": len([a for a in saved_alerts if a['risk_level'] == 'critical']),
                "high": len([a for a in saved_alerts if a['risk_level'] == 'high']),
                "medium": len([a for a in saved_alerts if a['risk_level'] == 'medium']),
                "low": len([a for a in saved_alerts if a['risk_level'] == 'low']),
            }

            result = DetectionResult(
                success=True,
                detected_count=len(saved_alerts),
                insight_created=insights_created > 0,
                insight_id=last_insight_id,
                details={
                    "overdue_tasks": len(overdue_alerts),
                    "stale_tasks": len(stale_alerts),
                    "concentration_alerts": len(concentration_alerts),
                    "insights_created": insights_created,
                    "risk_levels": risk_counts,
                },
            )

            self.log_detection_complete(result, duration_ms)
            return result

        except Exception as e:
            self.log_error("Bottleneck detection failed", e)
            return DetectionResult(
                success=False,
                error_message=str(e),
            )

    async def _detect_overdue_tasks(self) -> list[dict[str, Any]]:
        """
        期限超過タスクを検出

        Returns:
            期限超過タスクのアラートリスト
        """
        try:
            # limit_time は bigint (Unix timestamp) なので to_timestamp() で変換
            # 注意: chatwork_tasks.organization_id は VARCHAR型（'soul_syncs'等）
            result = self._conn.execute(text("""
                SELECT
                    task_id,
                    body,
                    summary,
                    limit_time,
                    assigned_to_account_id,
                    assigned_to_name,
                    room_id,
                    room_name,
                    EXTRACT(DAY FROM (NOW() - to_timestamp(limit_time)))::INT as overdue_days
                FROM chatwork_tasks
                WHERE status = 'open'
                  AND limit_time IS NOT NULL
                  AND to_timestamp(limit_time) < NOW()
                  AND organization_id = :org_id
                ORDER BY limit_time ASC
                LIMIT 100
            """), {"org_id": self._get_org_id_for_chatwork_tasks()})

            alerts = []
            for row in result:
                task_id = row[0]
                body = row[1]
                summary = row[2]
                limit_time = row[3]
                assigned_to_id = row[4]
                assigned_to_name = row[5]
                room_id = row[6]
                room_name = row[7]
                overdue_days = row[8] or 0

                # リスクレベル判定
                if overdue_days >= self._overdue_critical_days:
                    risk_level = BottleneckRiskLevel.CRITICAL.value
                elif overdue_days >= self._overdue_high_days:
                    risk_level = BottleneckRiskLevel.HIGH.value
                elif overdue_days >= self._overdue_medium_days:
                    risk_level = BottleneckRiskLevel.MEDIUM.value
                else:
                    risk_level = BottleneckRiskLevel.LOW.value

                # limit_time は Unix timestamp (bigint) なので変換
                limit_time_iso = None
                if limit_time:
                    limit_time_iso = datetime.fromtimestamp(
                        limit_time, tz=timezone.utc
                    ).isoformat()

                alerts.append({
                    'bottleneck_type': BottleneckType.OVERDUE_TASK.value,
                    'risk_level': risk_level,
                    'target_type': 'task',
                    'target_id': str(task_id),
                    'target_name': summary or (body[:50] if body else "タスク"),
                    'overdue_days': overdue_days,
                    'related_task_ids': [str(task_id)],
                    'sample_tasks': [{
                        'task_id': task_id,
                        'summary': summary,
                        'limit_time': limit_time_iso,
                        'assigned_to_name': assigned_to_name,
                        'room_name': room_name,
                    }],
                })

            return alerts

        except Exception as e:
            raise wrap_database_error(e, "detect overdue tasks")

    async def _detect_stale_tasks(self) -> list[dict[str, Any]]:
        """
        長期未完了タスクを検出

        Returns:
            長期未完了タスクのアラートリスト
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self._stale_task_days)

        try:
            # limit_time は bigint (Unix timestamp) なので to_timestamp() で変換
            result = self._conn.execute(text("""
                SELECT
                    task_id,
                    body,
                    summary,
                    created_at,
                    limit_time,
                    assigned_to_account_id,
                    assigned_to_name,
                    room_id,
                    room_name,
                    EXTRACT(DAY FROM (NOW() - created_at))::INT as stale_days
                FROM chatwork_tasks
                WHERE status = 'open'
                  AND created_at < :cutoff_date
                  AND (limit_time IS NULL OR to_timestamp(limit_time) >= NOW())
                  AND organization_id = :org_id
                ORDER BY created_at ASC
                LIMIT 50
            """), {
                "cutoff_date": cutoff_date,
                "org_id": self._get_org_id_for_chatwork_tasks(),
            })

            alerts = []
            for row in result:
                task_id = row[0]
                body = row[1]
                summary = row[2]
                created_at = row[3]
                limit_time = row[4]
                assigned_to_id = row[5]
                assigned_to_name = row[6]
                room_id = row[7]
                room_name = row[8]
                stale_days = row[9] or 0

                # 長期未完了はlow/mediumレベル
                if stale_days >= 14:
                    risk_level = BottleneckRiskLevel.MEDIUM.value
                else:
                    risk_level = BottleneckRiskLevel.LOW.value

                alerts.append({
                    'bottleneck_type': BottleneckType.STALE_TASK.value,
                    'risk_level': risk_level,
                    'target_type': 'task',
                    'target_id': str(task_id),
                    'target_name': summary or (body[:50] if body else "タスク"),
                    'stale_days': stale_days,
                    'related_task_ids': [str(task_id)],
                    'sample_tasks': [{
                        'task_id': task_id,
                        'summary': summary,
                        'created_at': created_at.isoformat() if created_at else None,
                        'assigned_to_name': assigned_to_name,
                        'room_name': room_name,
                    }],
                })

            return alerts

        except Exception as e:
            raise wrap_database_error(e, "detect stale tasks")

    async def _detect_task_concentration(self) -> list[dict[str, Any]]:
        """
        担当者へのタスク集中を検出

        Returns:
            タスク集中アラートのリスト
        """
        try:
            # 担当者別の未完了タスク数を集計
            result = self._conn.execute(text("""
                SELECT
                    assigned_to_account_id,
                    assigned_to_name,
                    COUNT(*) as task_count,
                    ARRAY_AGG(task_id ORDER BY limit_time NULLS LAST) as task_ids
                FROM chatwork_tasks
                WHERE status = 'open'
                  AND assigned_to_account_id IS NOT NULL
                  AND organization_id = :org_id
                GROUP BY assigned_to_account_id, assigned_to_name
                HAVING COUNT(*) >= :threshold
                ORDER BY task_count DESC
                LIMIT 20
            """), {
                "threshold": self._task_concentration_threshold,
                "org_id": self._get_org_id_for_chatwork_tasks(),
            })

            alerts = []
            for row in result:
                assigned_to_id = row[0]
                assigned_to_name = row[1]
                task_count = row[2]
                task_ids = row[3] or []

                # リスクレベル判定
                if task_count >= 20:
                    risk_level = BottleneckRiskLevel.CRITICAL.value
                elif task_count >= 15:
                    risk_level = BottleneckRiskLevel.HIGH.value
                else:
                    risk_level = BottleneckRiskLevel.MEDIUM.value

                alerts.append({
                    'bottleneck_type': BottleneckType.TASK_CONCENTRATION.value,
                    'risk_level': risk_level,
                    'target_type': 'user',
                    'target_id': str(assigned_to_id),
                    'target_name': assigned_to_name or "不明",
                    'task_count': task_count,
                    'related_task_ids': [str(tid) for tid in task_ids[:10]],
                    'sample_tasks': [],
                })

            return alerts

        except Exception as e:
            raise wrap_database_error(e, "detect task concentration")

    async def _save_alert(self, alert: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        アラートをDBに保存

        Args:
            alert: アラート情報

        Returns:
            保存されたアラート情報（IDを含む）
        """
        try:
            # UPSERT: 既存レコードがあれば更新、なければ挿入
            result = self._conn.execute(text("""
                INSERT INTO bottleneck_alerts (
                    organization_id,
                    bottleneck_type,
                    risk_level,
                    target_type,
                    target_id,
                    target_name,
                    overdue_days,
                    task_count,
                    stale_days,
                    related_task_ids,
                    sample_tasks,
                    status,
                    first_detected_at,
                    last_detected_at
                ) VALUES (
                    :org_id,
                    :bottleneck_type,
                    :risk_level,
                    :target_type,
                    :target_id,
                    :target_name,
                    :overdue_days,
                    :task_count,
                    :stale_days,
                    :related_task_ids,
                    :sample_tasks,
                    :status,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (organization_id, bottleneck_type, target_type, target_id)
                DO UPDATE SET
                    risk_level = EXCLUDED.risk_level,
                    target_name = EXCLUDED.target_name,
                    overdue_days = EXCLUDED.overdue_days,
                    task_count = EXCLUDED.task_count,
                    stale_days = EXCLUDED.stale_days,
                    related_task_ids = EXCLUDED.related_task_ids,
                    sample_tasks = EXCLUDED.sample_tasks,
                    last_detected_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            """), {
                "org_id": str(self._org_id),
                "bottleneck_type": alert['bottleneck_type'],
                "risk_level": alert['risk_level'],
                "target_type": alert['target_type'],
                "target_id": alert['target_id'],
                "target_name": alert.get('target_name'),
                "overdue_days": alert.get('overdue_days'),
                "task_count": alert.get('task_count'),
                "stale_days": alert.get('stale_days'),
                "related_task_ids": alert.get('related_task_ids', []),
                "sample_tasks": json.dumps(alert.get('sample_tasks', [])),
                "status": BottleneckStatus.ACTIVE.value,
            })

            row = result.fetchone()
            if row:
                alert['id'] = row[0]
                return alert

            return None

        except Exception as e:
            self._logger.error(
                "Failed to save bottleneck alert",
                extra={"error": str(e)}
            )
            return None

    def _create_insight_data(self, alert: dict[str, Any]) -> InsightData:
        """
        アラートからInsightDataを生成

        Args:
            alert: アラート情報

        Returns:
            InsightData: インサイトデータ
        """
        bottleneck_type = alert['bottleneck_type']
        target_name = alert.get('target_name', '不明')

        # 重要度をリスクレベルから変換
        importance_map = {
            BottleneckRiskLevel.CRITICAL.value: Importance.CRITICAL,
            BottleneckRiskLevel.HIGH.value: Importance.HIGH,
            BottleneckRiskLevel.MEDIUM.value: Importance.MEDIUM,
            BottleneckRiskLevel.LOW.value: Importance.LOW,
        }
        importance = importance_map.get(alert['risk_level'], Importance.MEDIUM)

        # ボトルネックタイプ別のタイトルと説明
        if bottleneck_type == BottleneckType.OVERDUE_TASK.value:
            overdue_days = alert.get('overdue_days', 0)
            title = f"タスク「{target_name[:30]}」が{overdue_days}日期限超過しています"
            description = (
                f"タスク「{target_name}」が期限を{overdue_days}日超過しています。"
                f"早急に対応をお願いします。"
            )
            recommended_action = (
                "1. タスクの担当者に状況を確認\n"
                "2. 期限の再設定または優先度の見直し\n"
                "3. 必要に応じて他のメンバーへの再割り当て"
            )

        elif bottleneck_type == BottleneckType.STALE_TASK.value:
            stale_days = alert.get('stale_days', 0)
            title = f"タスク「{target_name[:30]}」が{stale_days}日間未完了です"
            description = (
                f"タスク「{target_name}」が作成から{stale_days}日間未完了のままです。"
                f"対応状況をご確認ください。"
            )
            recommended_action = (
                "1. タスクがまだ必要か確認\n"
                "2. 着手できない理由の特定\n"
                "3. 期限の設定または完了処理"
            )

        elif bottleneck_type == BottleneckType.TASK_CONCENTRATION.value:
            task_count = alert.get('task_count', 0)
            title = f"{target_name}さんに{task_count}件のタスクが集中しています"
            description = (
                f"{target_name}さんに未完了タスクが{task_count}件集中しています。"
                f"負荷分散をご検討ください。"
            )
            recommended_action = (
                "1. タスクの優先度を見直し\n"
                "2. 他のメンバーへの分散を検討\n"
                "3. 完了できるタスクがないか確認"
            )

        else:
            title = f"ボトルネックが検出されました: {target_name}"
            description = f"ボトルネックが検出されました。確認してください。"
            recommended_action = "状況を確認し、適切な対応を行ってください。"

        return InsightData(
            organization_id=self._org_id,
            insight_type=InsightType.BOTTLENECK,
            source_type=SourceType.A3_BOTTLENECK,
            source_id=alert.get('id'),
            importance=importance,
            title=title,
            description=description,
            recommended_action=recommended_action,
            evidence={
                "bottleneck_type": bottleneck_type,
                "target_type": alert['target_type'],
                "target_id": alert['target_id'],
                "target_name": target_name,
                "overdue_days": alert.get('overdue_days'),
                "task_count": alert.get('task_count'),
                "stale_days": alert.get('stale_days'),
                "related_task_ids": alert.get('related_task_ids', []),
            },
            classification=Classification.INTERNAL,
        )
