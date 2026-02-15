"""
Phase 2 進化版 A2: 属人化検出

このモジュールは、特定の人にしか回答できない質問・業務を検出し、
BCP（事業継続）リスクを可視化します。

検出ロジック:
1. カテゴリ別の回答者を集計
2. 特定の人の回答比率を計算
3. 閾値を超えたら属人化リスクとして検出
4. リスクレベルを評価
5. soulkun_insightsに登録

設計書: docs/07_phase2_a2_personalization_detection.md

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-24
Version: 1.0
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

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
    PersonalizationRiskLevel,
    PersonalizationStatus,
    QuestionCategory,
    SourceType,
)
from lib.detection.exceptions import (
    DatabaseError,
    DetectionError,
    wrap_database_error,
)


class PersonalizationDetector(BaseDetector):
    """
    属人化検出器

    特定の人にしか回答できない状態を検出し、BCPリスクを可視化

    使用例:
        >>> detector = PersonalizationDetector(conn, org_id)
        >>> result = await detector.detect()
        >>> print(f"検出されたリスク: {result.detected_count}件")
    """

    def __init__(
        self,
        conn: Connection,
        org_id: UUID,
        personalization_threshold: float = DetectionParameters.PERSONALIZATION_THRESHOLD,
        min_responses: int = DetectionParameters.MIN_RESPONSES_FOR_PERSONALIZATION,
        analysis_window_days: int = DetectionParameters.PERSONALIZATION_WINDOW_DAYS,
        high_risk_days: int = DetectionParameters.HIGH_RISK_EXCLUSIVE_DAYS,
        critical_risk_days: int = DetectionParameters.CRITICAL_RISK_EXCLUSIVE_DAYS,
    ) -> None:
        """
        PersonalizationDetectorを初期化

        Args:
            conn: データベース接続
            org_id: 組織ID
            personalization_threshold: 属人化判定の偏り閾値（デフォルト: 0.8）
            min_responses: 検出に必要な最小回答数（デフォルト: 5）
            analysis_window_days: 分析対象期間（日数、デフォルト: 30）
            high_risk_days: 高リスク判定の連続日数（デフォルト: 14）
            critical_risk_days: 緊急リスク判定の連続日数（デフォルト: 30）
        """
        super().__init__(
            conn=conn,
            org_id=org_id,
            detector_type=SourceType.A2_PERSONALIZATION,
            insight_type=InsightType.PERSONALIZATION_RISK,
        )

        self._personalization_threshold = personalization_threshold
        self._min_responses = min_responses
        self._analysis_window_days = analysis_window_days
        self._high_risk_days = high_risk_days
        self._critical_risk_days = critical_risk_days

    async def detect(self, **kwargs: Any) -> DetectionResult:
        """
        属人化リスクを検出

        Returns:
            DetectionResult: 検出結果
        """
        start_time = datetime.now(timezone.utc)
        self.log_detection_start()

        try:
            # 1. カテゴリ別の回答統計を取得
            stats = await self._get_response_statistics()

            if not stats:
                self._logger.info("No response statistics found")
                result = DetectionResult(
                    success=True,
                    detected_count=0,
                    insight_created=False,
                    details={"message": "分析対象の回答がありません"},
                )
                self.log_detection_complete(result)
                return result

            # 2. 属人化リスクを評価
            risks = []
            for category, category_stats in stats.items():
                risk = self._evaluate_personalization(category, category_stats)
                if risk:
                    risks.append(risk)

            # 3. リスクをDBに保存
            saved_risks = []
            for risk in risks:
                saved_risk = await self._save_risk(risk)
                if saved_risk:
                    saved_risks.append(saved_risk)

            # 4. 閾値を超えたリスクはInsightに登録
            insights_created = 0
            last_insight_id = None

            for risk in saved_risks:
                if risk['risk_level'] in (
                    PersonalizationRiskLevel.CRITICAL.value,
                    PersonalizationRiskLevel.HIGH.value,
                    PersonalizationRiskLevel.MEDIUM.value,
                ):
                    # 既にインサイトがあるか確認
                    if not await self.insight_exists_for_source(risk['id']):
                        insight_data = self._create_insight_data(risk)
                        insight_id = await self.save_insight(insight_data)
                        insights_created += 1
                        last_insight_id = insight_id

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            result = DetectionResult(
                success=True,
                detected_count=len(saved_risks),
                insight_created=insights_created > 0,
                insight_id=last_insight_id,
                details={
                    "total_categories": len(stats),
                    "risks_detected": len(saved_risks),
                    "insights_created": insights_created,
                    "risk_levels": {
                        "critical": len([r for r in saved_risks if r['risk_level'] == 'critical']),
                        "high": len([r for r in saved_risks if r['risk_level'] == 'high']),
                        "medium": len([r for r in saved_risks if r['risk_level'] == 'medium']),
                        "low": len([r for r in saved_risks if r['risk_level'] == 'low']),
                    },
                },
            )

            self.log_detection_complete(result, duration_ms)
            return result

        except Exception as e:
            self.log_error("Personalization detection failed", e)
            return DetectionResult(
                success=False,
                error_message="パーソナライゼーション検出中に内部エラーが発生しました",
            )

    async def _get_response_statistics(self) -> dict[str, dict[str, Any]]:
        """
        カテゴリ別の回答統計を取得

        room_messagesから回答パターンを分析

        Returns:
            カテゴリ別の統計情報
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=self._analysis_window_days)

        # ソウルくんへの質問に対する回答を分析
        # 質問: ソウルくんへのメンションを含むメッセージ
        # 回答: 質問後30分以内の同じルームでの別ユーザーのメッセージ
        try:
            result = self._conn.execute(text("""
                WITH questions AS (
                    -- ソウルくんへの質問を抽出
                    SELECT
                        rm.message_id,
                        rm.room_id,
                        rm.account_id as questioner_id,
                        rm.send_time,
                        rm.body
                    FROM room_messages rm
                    WHERE rm.organization_id = CAST(:org_id AS uuid)
                      AND rm.send_time >= :cutoff_time
                      AND (
                          rm.body LIKE '%[To:10909425]%'
                          OR rm.body LIKE '%ソウルくん%'
                          OR rm.body LIKE '%そうるくん%'
                      )
                      AND rm.account_id != '10909425'
                ),
                responses AS (
                    -- 質問に対する回答を抽出（質問後30分以内）
                    SELECT
                        q.message_id as question_id,
                        rm.message_id as response_id,
                        rm.account_id as responder_id,
                        rm.send_time as response_time,
                        u.id as responder_user_id,
                        u.name as responder_name
                    FROM questions q
                    JOIN room_messages rm ON rm.room_id = q.room_id
                        AND rm.organization_id = CAST(:org_id AS uuid)
                        AND rm.send_time > q.send_time
                        AND rm.send_time <= q.send_time + INTERVAL '30 minutes'
                        AND rm.account_id != q.questioner_id
                        AND rm.account_id != '10909425'
                    LEFT JOIN users u ON u.chatwork_account_id = rm.account_id::text
                        AND u.organization_id = :org_id
                    WHERE LENGTH(rm.body) > 10  -- 短すぎる返信は除外
                )
                SELECT
                    responder_user_id,
                    responder_name,
                    COUNT(*) as response_count
                FROM responses
                WHERE responder_user_id IS NOT NULL
                GROUP BY responder_user_id, responder_name
                ORDER BY response_count DESC
            """), {
                "org_id": str(self._org_id),
                "cutoff_time": cutoff_time,
            })

            # 回答者ごとの統計を集計
            responder_stats = {}
            total_responses = 0

            for row in result:
                user_id = row[0]
                user_name = row[1]
                count = row[2]

                if user_id:
                    responder_stats[str(user_id)] = {
                        "user_id": user_id,
                        "user_name": user_name,
                        "response_count": count,
                    }
                    total_responses += count

            if total_responses == 0:
                return {}

            # 全体統計として返す（カテゴリ分類は将来実装）
            return {
                "general": {
                    "total_responses": total_responses,
                    "responders": {
                        uid: stats["response_count"]
                        for uid, stats in responder_stats.items()
                    },
                    "responder_names": {
                        uid: stats["user_name"]
                        for uid, stats in responder_stats.items()
                    },
                    "consecutive_days": self._analysis_window_days,  # 簡易実装
                }
            }

        except Exception as e:
            raise wrap_database_error(e, "get response statistics")

    def _evaluate_personalization(
        self,
        category: str,
        stats: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """
        属人化リスクを評価

        Args:
            category: カテゴリ名
            stats: カテゴリの統計情報

        Returns:
            リスク情報（閾値未満の場合はNone）
        """
        total = stats.get('total_responses', 0)
        if total < self._min_responses:
            return None

        responders = stats.get('responders', {})
        if not responders:
            return None

        # 最も多く回答している人を特定
        top_responder_id = max(responders.keys(), key=lambda k: responders[k])
        top_responder_count = responders[top_responder_id]
        ratio = top_responder_count / total

        # 60%未満は検出対象外
        if ratio < 0.6:
            return None

        # リスクレベルを判定
        is_exclusive = len(responders) == 1
        consecutive_days = stats.get('consecutive_days', 0)

        risk_level = self._determine_risk_level(
            ratio=ratio,
            exclusive=is_exclusive,
            consecutive_days=consecutive_days,
        )

        # 代替回答者リスト
        alternative_responders = [
            uid for uid in responders.keys()
            if uid != top_responder_id
        ]

        return {
            'expert_user_id': UUID(top_responder_id),
            'topic_category': category,
            'total_responses': total,
            'expert_responses': top_responder_count,
            'personalization_ratio': Decimal(str(round(ratio, 4))),
            'risk_level': risk_level,
            'alternative_responders': [UUID(uid) for uid in alternative_responders],
            'has_alternative': len(alternative_responders) > 0,
            'consecutive_days': consecutive_days,
            'responder_name': stats.get('responder_names', {}).get(top_responder_id, "不明"),
        }

    def _determine_risk_level(
        self,
        ratio: float,
        exclusive: bool,
        consecutive_days: int,
    ) -> str:
        """
        リスクレベルを判定

        Args:
            ratio: 属人化率
            exclusive: 独占状態か（1人だけが回答）
            consecutive_days: 連続検出日数

        Returns:
            リスクレベル文字列
        """
        if exclusive and consecutive_days >= self._critical_risk_days:
            return PersonalizationRiskLevel.CRITICAL.value
        elif ratio >= self._personalization_threshold and consecutive_days >= self._high_risk_days:
            return PersonalizationRiskLevel.HIGH.value
        elif ratio >= 0.6 and consecutive_days >= 7:
            return PersonalizationRiskLevel.MEDIUM.value
        else:
            return PersonalizationRiskLevel.LOW.value

    async def _save_risk(self, risk: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        リスクをDBに保存

        Args:
            risk: リスク情報

        Returns:
            保存されたリスク情報（IDを含む）
        """
        try:
            # UPSERT: 既存レコードがあれば更新、なければ挿入
            result = self._conn.execute(text("""
                INSERT INTO personalization_risks (
                    organization_id,
                    expert_user_id,
                    topic_category,
                    total_responses,
                    expert_responses,
                    personalization_ratio,
                    first_detected_at,
                    last_detected_at,
                    consecutive_days,
                    alternative_responders,
                    has_alternative,
                    risk_level,
                    status
                ) VALUES (
                    :org_id,
                    :expert_user_id,
                    :topic_category,
                    :total_responses,
                    :expert_responses,
                    :personalization_ratio,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    :consecutive_days,
                    :alternative_responders,
                    :has_alternative,
                    :risk_level,
                    :status
                )
                ON CONFLICT (organization_id, expert_user_id, topic_category)
                DO UPDATE SET
                    total_responses = EXCLUDED.total_responses,
                    expert_responses = EXCLUDED.expert_responses,
                    personalization_ratio = EXCLUDED.personalization_ratio,
                    last_detected_at = CURRENT_TIMESTAMP,
                    consecutive_days = personalization_risks.consecutive_days + 1,
                    alternative_responders = EXCLUDED.alternative_responders,
                    has_alternative = EXCLUDED.has_alternative,
                    risk_level = EXCLUDED.risk_level,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id, consecutive_days
            """), {
                "org_id": str(self._org_id),
                "expert_user_id": str(risk['expert_user_id']),
                "topic_category": risk['topic_category'],
                "total_responses": risk['total_responses'],
                "expert_responses": risk['expert_responses'],
                "personalization_ratio": float(risk['personalization_ratio']),
                "consecutive_days": risk['consecutive_days'],
                "alternative_responders": [str(uid) for uid in risk.get('alternative_responders', [])],
                "has_alternative": risk['has_alternative'],
                "risk_level": risk['risk_level'],
                "status": PersonalizationStatus.ACTIVE.value,
            })

            row = result.fetchone()
            if row:
                risk['id'] = row[0]
                risk['consecutive_days'] = row[1]
                return risk

            return None

        except Exception as e:
            self._logger.error(
                "Failed to save personalization risk",
                extra={"error_type": type(e).__name__}
            )
            return None

    def _create_insight_data(self, risk: dict[str, Any]) -> InsightData:
        """
        リスクからInsightDataを生成

        Args:
            risk: リスク情報

        Returns:
            InsightData: インサイトデータ
        """
        ratio_pct = int(float(risk['personalization_ratio']) * 100)
        responder_name = risk.get('responder_name', '特定の社員')

        # 重要度をリスクレベルから変換
        importance_map = {
            PersonalizationRiskLevel.CRITICAL.value: Importance.CRITICAL,
            PersonalizationRiskLevel.HIGH.value: Importance.HIGH,
            PersonalizationRiskLevel.MEDIUM.value: Importance.MEDIUM,
            PersonalizationRiskLevel.LOW.value: Importance.LOW,
        }
        importance = importance_map.get(risk['risk_level'], Importance.MEDIUM)

        # 代替者の有無でメッセージを変更
        if risk['has_alternative']:
            alt_message = "代替回答者がいますが、偏りが大きい状態です。"
        else:
            alt_message = "代替回答者がおらず、BCPリスクが高い状態です。"

        return InsightData(
            organization_id=self._org_id,
            insight_type=InsightType.PERSONALIZATION_RISK,
            source_type=SourceType.A2_PERSONALIZATION,
            source_id=risk.get('id'),
            importance=importance,
            title=f"「{risk['topic_category']}」の回答が{ratio_pct}%属人化しています",
            description=(
                f"過去{self._analysis_window_days}日間で「{risk['topic_category']}」に関する質問への回答の"
                f"{ratio_pct}%が{responder_name}さんに集中しています。"
                f"{alt_message}"
            ),
            recommended_action=(
                "1. この分野のナレッジを文書化\n"
                "2. 代替回答者の育成\n"
                "3. 定期的な知識共有セッションの実施"
            ),
            evidence={
                "expert_user_id": str(risk['expert_user_id']),
                "topic_category": risk['topic_category'],
                "personalization_ratio": ratio_pct,
                "total_responses": risk['total_responses'],
                "expert_responses": risk['expert_responses'],
                "has_alternative": risk['has_alternative'],
                "consecutive_days": risk['consecutive_days'],
            },
            classification=Classification.INTERNAL,
        )
