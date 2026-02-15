"""
Phase 2 進化版 A4: 感情変化検出

このモジュールは、従業員のメッセージから感情の変化を検出し、
メンタルヘルスリスクを早期に可視化します。

検出項目:
1. 急激な感情悪化（sudden_drop）
2. 継続的なネガティブ（sustained_negative）
3. 感情の不安定さ（high_volatility）
4. 回復（recovery）- ポジティブな変化

設計原則:
- プライバシー最優先: 全データはCONFIDENTIAL分類
- 管理者のみ通知: 本人には直接通知しない
- トレンドベース: 単発メッセージではなく変化を検出
- 支援的フレーミング: 「監視」ではなく「ウェルネスチェック」

設計書: docs/09_phase2_a4_emotion_detection.md

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-24
Version: 1.0
"""

import json
import os

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

import requests
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
    EmotionAlertType,
    EmotionRiskLevel,
    EmotionStatus,
    Importance,
    InsightType,
    SentimentLabel,
    SourceType,
)
from lib.detection.exceptions import (
    DatabaseError,
    DetectionError,
    wrap_database_error,
)


def _ensure_aware(dt: Any) -> Any:
    """naive datetime を UTC aware に変換。aware ならそのまま返す。

    room_messages.send_time は TIMESTAMP WITHOUT TIME ZONE であり、
    pg8000 から naive datetime として返される。
    アプリケーション内では全て UTC aware で統一する。
    """
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ================================================================
# 感情分析プロンプト
# ================================================================

SENTIMENT_ANALYSIS_PROMPT = """あなたは職場メッセージの感情分析専門家です。
以下のメッセージの感情トーンを分析し、JSON形式で返してください。

分析ポイント:
- 全体的な感情トーン（ポジティブ/ニュートラル/ネガティブ）
- 検出された感情（不満、不安、疲労、焦り、喜び等）
- 信頼度（分析の確実性）

注意:
- 業務上の普通のやり取りは「neutral」と判定
- 明確な感情表現がある場合のみ positive/negative と判定
- 個人名や具体的な内容は key_indicators に含めない

出力形式（JSONのみ、説明不要）:
{
  "sentiment_score": -1.0から1.0の数値,
  "sentiment_label": "very_negative" | "negative" | "neutral" | "positive" | "very_positive",
  "detected_emotions": ["感情1", "感情2"],
  "confidence": 0.0から1.0の数値
}

メッセージ:
"""


class EmotionDetector(BaseDetector):
    """
    感情変化検出器

    従業員のメッセージから感情の変化を検出し、メンタルヘルスリスクを可視化

    プライバシー注意:
    - 全てのデータはCONFIDENTIAL分類
    - メッセージ本文はDBに保存しない
    - 管理者のみに通知

    使用例:
        >>> detector = EmotionDetector(conn, org_id)
        >>> result = await detector.detect()
        >>> print(f"検出された感情変化: {result.detected_count}件")
    """

    def __init__(
        self,
        conn: Connection,
        org_id: UUID,
        analysis_window_days: int = DetectionParameters.EMOTION_ANALYSIS_WINDOW_DAYS,
        baseline_window_days: int = DetectionParameters.EMOTION_BASELINE_WINDOW_DAYS,
        min_messages: int = DetectionParameters.MIN_MESSAGES_FOR_EMOTION,
        sentiment_drop_critical: float = DetectionParameters.SENTIMENT_DROP_CRITICAL,
        sentiment_drop_high: float = DetectionParameters.SENTIMENT_DROP_HIGH,
        sustained_negative_critical_days: int = DetectionParameters.SUSTAINED_NEGATIVE_CRITICAL_DAYS,
        sustained_negative_high_days: int = DetectionParameters.SUSTAINED_NEGATIVE_HIGH_DAYS,
        negative_score_threshold: float = DetectionParameters.NEGATIVE_SCORE_THRESHOLD,
        very_negative_score_threshold: float = DetectionParameters.VERY_NEGATIVE_SCORE_THRESHOLD,
    ) -> None:
        """
        EmotionDetectorを初期化

        Args:
            conn: データベース接続
            org_id: 組織ID
            analysis_window_days: 分析対象期間（デフォルト: 14日）
            baseline_window_days: ベースライン計算期間（デフォルト: 30日）
            min_messages: 分析に必要な最小メッセージ数（デフォルト: 5）
            sentiment_drop_critical: Critical判定の悪化閾値（デフォルト: 0.4）
            sentiment_drop_high: High判定の悪化閾値（デフォルト: 0.3）
            sustained_negative_critical_days: Critical判定の継続日数（デフォルト: 7）
            sustained_negative_high_days: High判定の継続日数（デフォルト: 5）
            negative_score_threshold: ネガティブ判定の閾値（デフォルト: -0.2）
            very_negative_score_threshold: 非常にネガティブ判定の閾値（デフォルト: -0.5）
        """
        super().__init__(
            conn=conn,
            org_id=org_id,
            detector_type=SourceType.A4_EMOTION,
            insight_type=InsightType.EMOTION_CHANGE,
        )

        self._analysis_window_days = analysis_window_days
        self._baseline_window_days = baseline_window_days
        self._min_messages = min_messages
        self._sentiment_drop_critical = sentiment_drop_critical
        self._sentiment_drop_high = sentiment_drop_high
        self._sustained_negative_critical_days = sustained_negative_critical_days
        self._sustained_negative_high_days = sustained_negative_high_days
        self._negative_score_threshold = negative_score_threshold
        self._very_negative_score_threshold = very_negative_score_threshold

        # OpenRouter API設定
        self._openrouter_api_url = "https://openrouter.ai/api/v1/chat/completions"
        self._default_model = "google/gemini-3-flash-preview"

    async def detect(self, **kwargs: Any) -> DetectionResult:
        """
        感情変化を検出

        Returns:
            DetectionResult: 検出結果
        """
        start_time = datetime.now(timezone.utc)
        self.log_detection_start()

        try:
            # 1. 分析対象のユーザーを取得
            users = await self._get_active_users()
            self._logger.info(f"Active users for emotion analysis: {len(users)}")

            if not users:
                result = DetectionResult(
                    success=True,
                    detected_count=0,
                    insight_created=False,
                    details={"message": "分析対象のユーザーがいません"},
                )
                self.log_detection_complete(result)
                return result

            # 2. ユーザーごとに感情分析
            all_alerts = []
            users_analyzed = 0
            users_skipped = 0

            for user in users:
                try:
                    # SAVEPOINT: 1ユーザーの失敗が他ユーザーのトランザクションを壊さないよう隔離
                    self._conn.execute(text("SAVEPOINT user_analysis"))
                    alerts = await self._analyze_user_emotion(user)
                    if alerts:
                        all_alerts.extend(alerts)
                        users_analyzed += 1
                    else:
                        users_skipped += 1
                    self._conn.execute(text("RELEASE SAVEPOINT user_analysis"))
                except Exception as e:
                    self._logger.warning(
                        f"Failed to analyze user {user['account_id']}: {type(e).__name__}"
                    )
                    try:
                        self._conn.execute(text("ROLLBACK TO SAVEPOINT user_analysis"))
                    except Exception as rollback_err:
                        self._logger.error(f"ROLLBACK TO SAVEPOINT failed: {type(rollback_err).__name__}")
                    users_skipped += 1
                    continue

            # 3. アラートをDBに保存
            saved_alerts = []
            for alert in all_alerts:
                saved = await self._save_alert(alert)
                if saved:
                    saved_alerts.append(saved)

            # 4. critical/high はInsightに登録
            insights_created = 0
            last_insight_id = None

            for alert in saved_alerts:
                if alert['risk_level'] in (
                    EmotionRiskLevel.CRITICAL.value,
                    EmotionRiskLevel.HIGH.value,
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
                    "users_analyzed": users_analyzed,
                    "users_skipped": users_skipped,
                    "alerts_created": len(saved_alerts),
                    "insights_created": insights_created,
                    "risk_levels": risk_counts,
                },
            )

            self.log_detection_complete(result, duration_ms)
            return result

        except Exception as e:
            self.log_error("感情検出中にエラーが発生しました", e)
            return DetectionResult(
                success=False,
                error_message="感情検出中に内部エラーが発生しました",
            )

    async def _get_active_users(self) -> list[dict[str, Any]]:
        """
        分析対象のアクティブユーザーを取得

        Returns:
            ユーザーリスト（account_id, account_name）
        """
        try:
            # 分析期間内にメッセージを送信したユーザーを取得
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=self._analysis_window_days)

            result = self._conn.execute(text("""
                SELECT DISTINCT
                    account_id,
                    account_name,
                    COUNT(*) as message_count
                FROM room_messages
                WHERE organization_id = CAST(:org_id AS uuid)
                  AND send_time >= :cutoff_date
                  AND account_id IS NOT NULL
                GROUP BY account_id, account_name
                HAVING COUNT(*) >= :min_messages
                ORDER BY message_count DESC
            """), {
                "org_id": str(self._org_id),
                "cutoff_date": cutoff_date,
                "min_messages": self._min_messages,
            })

            users = []
            for row in result:
                users.append({
                    'account_id': row[0],
                    'account_name': row[1] or "不明",
                    'message_count': row[2],
                })

            return users

        except Exception as e:
            raise wrap_database_error(e, "get active users")

    async def _analyze_user_emotion(
        self,
        user: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        ユーザーの感情を分析

        Args:
            user: ユーザー情報（account_id, account_name）

        Returns:
            検出されたアラートのリスト
        """
        account_id = user['account_id']
        account_name = user['account_name']

        # 1. 直近のメッセージを取得
        messages = await self._get_user_messages(account_id)
        if len(messages) < self._min_messages:
            self._logger.debug(f"Skipping user {account_id}: insufficient messages")
            return []

        # 2. 各メッセージの感情スコアを計算（または既存スコアを取得）
        scores = []
        for msg in messages:
            score = await self._get_or_calculate_sentiment(msg)
            if score:
                scores.append(score)

        if not scores:
            return []

        # 3. ベースラインスコアを計算
        baseline_score = await self._calculate_baseline_score(account_id)

        # 4. 現在のスコアを計算（直近7日間の平均）
        cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
        recent_scores = [s for s in scores if _ensure_aware(s['message_time']) >= cutoff_7d]
        if not recent_scores:
            return []

        current_score = sum(s['sentiment_score'] for s in recent_scores) / len(recent_scores)

        # 5. 連続ネガティブ日数を計算
        consecutive_negative_days = self._calculate_consecutive_negative_days(scores)

        # 6. 感情変化を検出
        alerts = []

        # 急激な悪化を検出
        score_drop = baseline_score - current_score
        if score_drop >= self._sentiment_drop_high:
            risk_level = self._determine_risk_level(
                baseline_score=baseline_score,
                current_score=current_score,
                consecutive_negative_days=consecutive_negative_days,
            )
            alerts.append({
                'alert_type': EmotionAlertType.SUDDEN_DROP.value,
                'risk_level': risk_level.value,
                'account_id': account_id,
                'user_name': account_name,
                'baseline_score': float(baseline_score),
                'current_score': float(current_score),
                'score_change': float(score_drop),
                'consecutive_negative_days': consecutive_negative_days,
                'message_count': len(scores),
                'negative_message_count': len([s for s in scores if s['sentiment_score'] < self._negative_score_threshold]),
            })

        # 継続的なネガティブを検出
        elif consecutive_negative_days >= 3:
            risk_level = self._determine_risk_level(
                baseline_score=baseline_score,
                current_score=current_score,
                consecutive_negative_days=consecutive_negative_days,
            )
            alerts.append({
                'alert_type': EmotionAlertType.SUSTAINED_NEGATIVE.value,
                'risk_level': risk_level.value,
                'account_id': account_id,
                'user_name': account_name,
                'baseline_score': float(baseline_score),
                'current_score': float(current_score),
                'score_change': float(score_drop),
                'consecutive_negative_days': consecutive_negative_days,
                'message_count': len(scores),
                'negative_message_count': len([s for s in scores if s['sentiment_score'] < self._negative_score_threshold]),
            })

        return alerts

    async def _get_user_messages(
        self,
        account_id: Any
    ) -> list[dict[str, Any]]:
        """
        ユーザーのメッセージを取得

        Args:
            account_id: ChatworkアカウントID

        Returns:
            メッセージリスト
        """
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=self._analysis_window_days)

            result = self._conn.execute(text("""
                SELECT
                    message_id,
                    room_id,
                    body,
                    send_time
                FROM room_messages
                WHERE organization_id = CAST(:org_id AS uuid)
                  AND account_id = :account_id
                  AND send_time >= :cutoff_date
                  AND body IS NOT NULL
                  AND LENGTH(body) > 10
                ORDER BY send_time DESC
                LIMIT 50
            """), {
                "org_id": str(self._org_id),
                "account_id": account_id,
                "cutoff_date": cutoff_date,
            })

            messages = []
            for row in result:
                # room_messages.send_time は TIMESTAMP WITHOUT TIME ZONE
                # pg8000 から naive datetime が返るので UTC aware に変換
                messages.append({
                    'message_id': row[0],
                    'room_id': row[1],
                    'body': row[2],
                    'send_time': _ensure_aware(row[3]),
                })

            return messages

        except Exception as e:
            raise wrap_database_error(e, "get user messages")

    async def _get_or_calculate_sentiment(
        self,
        message: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """
        メッセージの感情スコアを取得（なければ計算）

        Args:
            message: メッセージ情報

        Returns:
            感情スコア情報
        """
        message_id = message['message_id']

        # 1. 既存のスコアを確認
        try:
            result = self._conn.execute(text("""
                SELECT
                    sentiment_score,
                    sentiment_label,
                    confidence,
                    detected_emotions,
                    analyzed_at
                FROM emotion_scores
                WHERE organization_id = :org_id
                  AND message_id = :message_id
            """), {
                "org_id": str(self._org_id),
                "message_id": message_id,
            })

            row = result.fetchone()
            if row:
                return {
                    'message_id': message_id,
                    'sentiment_score': float(row[0]),
                    'sentiment_label': row[1],
                    'confidence': float(row[2]) if row[2] else None,
                    'detected_emotions': row[3] or [],
                    'message_time': _ensure_aware(message['send_time']),
                }
        except Exception as e:
            self._logger.warning(
                f"Failed to query existing emotion score for message {message_id}: {type(e).__name__}"
            )

        # 2. 新しく計算
        try:
            sentiment = await self._analyze_sentiment(message['body'])
            if not sentiment:
                return None

            # 3. DBに保存
            await self._save_emotion_score(message, sentiment)

            return {
                'message_id': message_id,
                'sentiment_score': sentiment['sentiment_score'],
                'sentiment_label': sentiment['sentiment_label'],
                'confidence': sentiment.get('confidence'),
                'detected_emotions': sentiment.get('detected_emotions', []),
                'message_time': _ensure_aware(message['send_time']),
            }

        except Exception as e:
            self._logger.warning(f"Failed to analyze sentiment for message {message_id}: {type(e).__name__}")
            return None

    async def _analyze_sentiment(self, text_body: str) -> Optional[dict[str, Any]]:
        """
        テキストの感情を分析（LLM使用）

        Args:
            text_body: 分析対象のテキスト

        Returns:
            感情分析結果
        """
        try:
            # テキストを適切な長さに制限
            truncated_text = text_body[:500] if len(text_body) > 500 else text_body

            # OpenRouter APIを呼び出し
            response = self._call_openrouter_api(
                system_prompt=SENTIMENT_ANALYSIS_PROMPT,
                user_message=truncated_text,
            )

            if not response:
                return None

            # JSONをパース
            try:
                # レスポンスからJSONを抽出
                response_text = response.strip()
                if response_text.startswith("```json"):
                    response_text = response_text[7:]
                if response_text.startswith("```"):
                    response_text = response_text[3:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]

                result = json.loads(response_text.strip())

                # 必須フィールドの検証
                if 'sentiment_score' not in result or 'sentiment_label' not in result:
                    return None

                # スコアの範囲を制限
                score = max(-1.0, min(1.0, float(result['sentiment_score'])))

                return {
                    'sentiment_score': score,
                    'sentiment_label': result.get('sentiment_label', SentimentLabel.from_score(score).value),
                    'confidence': float(result.get('confidence', 0.5)),
                    'detected_emotions': result.get('detected_emotions', []),
                }

            except json.JSONDecodeError:
                self._logger.warning("Failed to parse sentiment response as JSON")
                return None

        except Exception as e:
            self._logger.warning(f"Sentiment analysis failed: {type(e).__name__}")
            return None

    def _call_openrouter_api(
        self,
        system_prompt: str,
        user_message: str,
        model: str = None,
    ) -> Optional[str]:
        """
        OpenRouter API経由でLLMを呼び出し

        Args:
            system_prompt: システムプロンプト
            user_message: ユーザーメッセージ
            model: 使用するモデル

        Returns:
            LLMのレスポンステキスト
        """
        try:
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                self._logger.error("OPENROUTER_API_KEY not set")
                return None

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": model or self._default_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.1,
                "max_tokens": 200,
            }

            response = requests.post(
                self._openrouter_api_url,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code != 200:
                self._logger.warning(f"OpenRouter API error: {response.status_code}")
                return None

            data = response.json()
            return data.get('choices', [{}])[0].get('message', {}).get('content')

        except Exception as e:
            self._logger.warning(f"OpenRouter API call failed: {type(e).__name__}")
            return None

    async def _save_emotion_score(
        self,
        message: dict[str, Any],
        sentiment: dict[str, Any]
    ) -> None:
        """
        感情スコアをDBに保存

        Args:
            message: メッセージ情報
            sentiment: 感情分析結果
        """
        try:
            self._conn.execute(text("SAVEPOINT save_emotion_score"))
            self._conn.execute(text("""
                INSERT INTO emotion_scores (
                    organization_id,
                    message_id,
                    room_id,
                    user_id,
                    sentiment_score,
                    sentiment_label,
                    confidence,
                    detected_emotions,
                    analysis_model,
                    message_time,
                    classification
                ) VALUES (
                    :org_id,
                    :message_id,
                    :room_id,
                    :user_id,
                    :sentiment_score,
                    :sentiment_label,
                    :confidence,
                    :detected_emotions,
                    :analysis_model,
                    :message_time,
                    'confidential'
                )
                ON CONFLICT (organization_id, message_id) DO NOTHING
            """), {
                "org_id": str(self._org_id),
                "message_id": message['message_id'],
                "room_id": message['room_id'],
                "user_id": str(self._org_id),  # NOTE: user_id列はUUID型。account_id(BIGINT)は格納不可。スキーマ変更後に修正（Tier 2で対応）
                "sentiment_score": sentiment['sentiment_score'],
                "sentiment_label": sentiment['sentiment_label'],
                "confidence": sentiment.get('confidence'),
                "detected_emotions": sentiment.get('detected_emotions', []),
                "analysis_model": self._default_model,
                "message_time": _ensure_aware(message['send_time']),
            })
            self._conn.execute(text("RELEASE SAVEPOINT save_emotion_score"))

        except Exception as e:
            self._logger.warning(f"Failed to save emotion score: {type(e).__name__}")
            try:
                self._conn.execute(text("ROLLBACK TO SAVEPOINT save_emotion_score"))
            except Exception as rollback_err:
                self._logger.error(f"ROLLBACK TO SAVEPOINT failed: {type(rollback_err).__name__}")

    async def _calculate_baseline_score(self, account_id: Any) -> float:
        """
        ベースラインスコアを計算（過去N日間の平均）

        Args:
            account_id: ChatworkアカウントID

        Returns:
            ベースラインスコア
        """
        try:
            # 直近7日間を除いた、過去30日間の平均を計算
            baseline_start = datetime.now(timezone.utc) - timedelta(days=self._baseline_window_days)
            baseline_end = datetime.now(timezone.utc) - timedelta(days=7)

            result = self._conn.execute(text("""
                SELECT AVG(es.sentiment_score)
                FROM emotion_scores es
                INNER JOIN room_messages rm ON es.message_id = rm.message_id
                WHERE rm.account_id = :account_id
                  AND es.organization_id = :org_id
                  AND es.message_time >= :start_date
                  AND es.message_time < :end_date
            """), {
                "account_id": account_id,
                "org_id": str(self._org_id),
                "start_date": baseline_start,
                "end_date": baseline_end,
            })

            row = result.fetchone()
            if row and row[0] is not None:
                return float(row[0])

            # ベースラインがない場合はニュートラル
            return 0.0

        except Exception as e:
            self._logger.warning(f"Failed to calculate baseline: {type(e).__name__}")
            return 0.0

    def _calculate_consecutive_negative_days(
        self,
        scores: list[dict[str, Any]]
    ) -> int:
        """
        連続ネガティブ日数を計算

        Args:
            scores: 感情スコアリスト

        Returns:
            連続ネガティブ日数
        """
        if not scores:
            return 0

        # 日付ごとにグループ化
        daily_scores = {}
        for score in scores:
            msg_time = _ensure_aware(score['message_time'])
            if isinstance(msg_time, datetime):
                date_key = msg_time.date()
            else:
                continue

            if date_key not in daily_scores:
                daily_scores[date_key] = []
            daily_scores[date_key].append(score['sentiment_score'])

        # 日付順にソート
        sorted_dates = sorted(daily_scores.keys(), reverse=True)

        consecutive_days = 0
        for date in sorted_dates:
            avg_score = sum(daily_scores[date]) / len(daily_scores[date])
            if avg_score < self._negative_score_threshold:
                consecutive_days += 1
            else:
                break

        return consecutive_days

    def _determine_risk_level(
        self,
        baseline_score: float,
        current_score: float,
        consecutive_negative_days: int,
    ) -> EmotionRiskLevel:
        """
        リスクレベルを判定

        Args:
            baseline_score: ベースラインスコア
            current_score: 現在のスコア
            consecutive_negative_days: 連続ネガティブ日数

        Returns:
            EmotionRiskLevel: リスクレベル
        """
        score_drop = baseline_score - current_score

        # Critical条件
        if score_drop >= self._sentiment_drop_critical and consecutive_negative_days >= 3:
            return EmotionRiskLevel.CRITICAL
        if current_score <= self._very_negative_score_threshold and consecutive_negative_days >= self._sustained_negative_critical_days:
            return EmotionRiskLevel.CRITICAL

        # High条件
        if score_drop >= self._sentiment_drop_high and consecutive_negative_days >= 2:
            return EmotionRiskLevel.HIGH
        if current_score <= self._negative_score_threshold - 0.1 and consecutive_negative_days >= self._sustained_negative_high_days:
            return EmotionRiskLevel.HIGH

        # Medium条件
        if score_drop >= 0.2:
            return EmotionRiskLevel.MEDIUM
        if current_score <= self._negative_score_threshold and consecutive_negative_days >= 3:
            return EmotionRiskLevel.MEDIUM

        return EmotionRiskLevel.LOW

    async def _save_alert(
        self,
        alert: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """
        アラートをDBに保存

        Args:
            alert: アラート情報

        Returns:
            保存されたアラート情報（IDを含む）
        """
        try:
            self._conn.execute(text("SAVEPOINT save_alert"))
            today = datetime.now(timezone.utc).date()
            analysis_start = today - timedelta(days=self._analysis_window_days)

            # UPSERT: 既存レコードがあれば更新、なければ挿入
            result = self._conn.execute(text("""
                INSERT INTO emotion_alerts (
                    organization_id,
                    user_id,
                    user_name,
                    alert_type,
                    risk_level,
                    baseline_score,
                    current_score,
                    score_change,
                    consecutive_negative_days,
                    analysis_start_date,
                    analysis_end_date,
                    message_count,
                    negative_message_count,
                    evidence,
                    status,
                    first_detected_at,
                    last_detected_at,
                    classification
                ) VALUES (
                    :org_id,
                    :user_id,
                    :user_name,
                    :alert_type,
                    :risk_level,
                    :baseline_score,
                    :current_score,
                    :score_change,
                    :consecutive_negative_days,
                    :analysis_start_date,
                    :analysis_end_date,
                    :message_count,
                    :negative_message_count,
                    :evidence,
                    :status,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    'confidential'
                )
                ON CONFLICT (organization_id, user_id, alert_type, analysis_start_date)
                DO UPDATE SET
                    risk_level = EXCLUDED.risk_level,
                    baseline_score = EXCLUDED.baseline_score,
                    current_score = EXCLUDED.current_score,
                    score_change = EXCLUDED.score_change,
                    consecutive_negative_days = EXCLUDED.consecutive_negative_days,
                    message_count = EXCLUDED.message_count,
                    negative_message_count = EXCLUDED.negative_message_count,
                    evidence = EXCLUDED.evidence,
                    last_detected_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            """), {
                "org_id": str(self._org_id),
                "user_id": str(self._org_id),  # NOTE: user_id列はUUID型。account_id(BIGINT)は格納不可。スキーマ変更後に修正（Tier 2で対応）
                "user_name": alert.get('user_name'),
                "alert_type": alert['alert_type'],
                "risk_level": alert['risk_level'],
                "baseline_score": alert.get('baseline_score'),
                "current_score": alert.get('current_score'),
                "score_change": alert.get('score_change'),
                "consecutive_negative_days": alert.get('consecutive_negative_days', 0),
                "analysis_start_date": analysis_start,
                "analysis_end_date": today,
                "message_count": alert.get('message_count', 0),
                "negative_message_count": alert.get('negative_message_count', 0),
                "evidence": json.dumps({
                    "account_id": str(alert.get('account_id')),
                    # メッセージ本文は含めない（プライバシー保護）
                }),
                "status": EmotionStatus.ACTIVE.value,
            })

            row = result.fetchone()
            self._conn.execute(text("RELEASE SAVEPOINT save_alert"))
            if row:
                alert['id'] = row[0]
                return alert

            return None

        except Exception as e:
            self._logger.error(
                "Failed to save emotion alert",
                extra={"error_type": type(e).__name__}
            )
            try:
                self._conn.execute(text("ROLLBACK TO SAVEPOINT save_alert"))
            except Exception as rollback_err:
                self._logger.error(f"ROLLBACK TO SAVEPOINT failed: {type(rollback_err).__name__}")
            return None

    def _create_insight_data(self, alert: dict[str, Any]) -> InsightData:
        """
        アラートからInsightDataを生成

        Args:
            alert: アラート情報

        Returns:
            InsightData: インサイトデータ
        """
        alert_type = alert['alert_type']
        user_name = alert.get('user_name', '不明')

        # 重要度をリスクレベルから変換
        importance_map = {
            EmotionRiskLevel.CRITICAL.value: Importance.CRITICAL,
            EmotionRiskLevel.HIGH.value: Importance.HIGH,
            EmotionRiskLevel.MEDIUM.value: Importance.MEDIUM,
            EmotionRiskLevel.LOW.value: Importance.LOW,
        }
        importance = importance_map.get(alert['risk_level'], Importance.MEDIUM)

        # アラートタイプ別のタイトルと説明
        if alert_type == EmotionAlertType.SUDDEN_DROP.value:
            score_change = alert.get('score_change', 0)
            title = f"{user_name}さんの感情に急激な変化が見られます"
            description = (
                f"{user_name}さんのメッセージから、感情スコアが{score_change:.2f}ポイント低下しています。"
                f"ストレスや悩みを抱えている可能性があります。"
            )
            recommended_action = (
                "1. 本人との面談を検討（プライバシーに配慮）\n"
                "2. 業務負荷の確認\n"
                "3. 必要に応じてメンタルヘルスサポートの案内"
            )

        elif alert_type == EmotionAlertType.SUSTAINED_NEGATIVE.value:
            consecutive_days = alert.get('consecutive_negative_days', 0)
            title = f"{user_name}さんの感情が{consecutive_days}日間低迷しています"
            description = (
                f"{user_name}さんのメッセージから、{consecutive_days}日間連続でネガティブな傾向が続いています。"
                f"継続的なサポートが必要かもしれません。"
            )
            recommended_action = (
                "1. 業務環境や人間関係の確認\n"
                "2. 1on1ミーティングの実施\n"
                "3. EAP（従業員支援プログラム）の案内"
            )

        elif alert_type == EmotionAlertType.HIGH_VOLATILITY.value:
            title = f"{user_name}さんの感情に不安定さが見られます"
            description = (
                f"{user_name}さんのメッセージから、感情の大きな波が検出されました。"
                f"何らかの変化やストレス要因がある可能性があります。"
            )
            recommended_action = (
                "1. 状況の把握（プライバシーに配慮）\n"
                "2. 必要に応じたサポートの提供"
            )

        else:  # RECOVERY
            title = f"{user_name}さんの感情が回復傾向にあります"
            description = (
                f"{user_name}さんのメッセージから、ポジティブな変化が見られます。"
                f"良い兆候です。"
            )
            recommended_action = "現状維持。良い傾向を継続できるようサポート"

        return InsightData(
            organization_id=self._org_id,
            insight_type=InsightType.EMOTION_CHANGE,
            source_type=SourceType.A4_EMOTION,
            importance=importance,
            title=title,
            description=description,
            source_id=alert['id'],
            recommended_action=recommended_action,
            evidence={
                "alert_type": alert_type,
                "risk_level": alert['risk_level'],
                "consecutive_negative_days": alert.get('consecutive_negative_days'),
                "score_change": alert.get('score_change'),
                # メッセージ本文は含めない
            },
            classification=Classification.CONFIDENTIAL,  # 必ずCONFIDENTIAL
        )
