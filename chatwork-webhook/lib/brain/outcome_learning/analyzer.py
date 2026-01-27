"""
Phase 2F: 結果からの学習 - 結果分析

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2F

結果データを分析し、インサイトを生成するクラス。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.engine import Connection

from .constants import (
    DAY_OF_WEEK_NAMES,
    MIN_SAMPLE_COUNT,
    MIN_SUCCESS_RATE,
    OutcomeType,
)
from .models import OutcomeInsight, OutcomeStatistics
from .repository import OutcomeRepository


logger = logging.getLogger(__name__)


class OutcomeAnalyzer:
    """結果分析クラス

    分析内容:
    1. ユーザー別の反応傾向
    2. 時間帯別の効果測定
    3. メッセージタイプ別の成功率
    4. 長期的なトレンド分析

    使用例:
        analyzer = OutcomeAnalyzer(organization_id, repository)

        # ユーザーの反応傾向を分析
        responsiveness = analyzer.analyze_user_responsiveness(conn, "12345")

        # インサイトを生成
        insights = analyzer.generate_insights(conn)
    """

    def __init__(
        self,
        organization_id: str,
        repository: OutcomeRepository,
    ):
        """初期化

        Args:
            organization_id: 組織ID
            repository: リポジトリ
        """
        self.organization_id = organization_id
        self.repository = repository

    def analyze_user_responsiveness(
        self,
        conn: Connection,
        account_id: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """ユーザーの反応傾向を分析

        Args:
            conn: DB接続
            account_id: ユーザーID
            days: 分析期間（日数）

        Returns:
            分析結果
        """
        # 基本統計を取得
        stats = self.repository.get_statistics(
            conn,
            target_account_id=account_id,
            days=days,
        )

        # 時間帯別統計を取得
        hourly_stats = self.repository.get_hourly_statistics(
            conn,
            target_account_id=account_id,
            days=days,
        )

        # 曜日別統計を取得
        dow_stats = self.repository.get_day_of_week_statistics(
            conn,
            target_account_id=account_id,
            days=days,
        )

        # 最も効果的な時間帯を特定
        best_hour = self._find_best_hour(hourly_stats)

        # 最も効果的な曜日を特定
        best_day = self._find_best_day(dow_stats)

        return {
            "account_id": account_id,
            "period_days": days,
            "total_events": stats.total_events,
            "adoption_rate": stats.adoption_rate,
            "ignore_rate": stats.ignore_rate,
            "best_hour": best_hour,
            "best_day": best_day,
            "hourly_stats": hourly_stats,
            "day_of_week_stats": {
                DAY_OF_WEEK_NAMES.get(k, str(k)): v
                for k, v in dow_stats.items()
            },
            "responsiveness_score": self._calculate_responsiveness_score(stats),
        }

    def analyze_timing_effectiveness(
        self,
        conn: Connection,
        account_id: Optional[str] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """時間帯別の効果を分析

        Args:
            conn: DB接続
            account_id: ユーザーID（Noneで全体）
            days: 分析期間（日数）

        Returns:
            分析結果
        """
        hourly_stats = self.repository.get_hourly_statistics(
            conn,
            target_account_id=account_id,
            days=days,
        )

        # 時間帯ごとの成功率を計算
        timing_analysis = {}
        for hour, stats in hourly_stats.items():
            total = stats.get("total", 0)
            adopted = stats.get("adopted", 0)

            timing_analysis[hour] = {
                "total": total,
                "adopted": adopted,
                "ignored": stats.get("ignored", 0),
                "success_rate": adopted / total if total > 0 else 0.0,
            }

        # 最も効果的な時間帯を特定
        best_hours = sorted(
            timing_analysis.items(),
            key=lambda x: x[1]["success_rate"],
            reverse=True,
        )[:3]

        return {
            "account_id": account_id,
            "period_days": days,
            "hourly_analysis": timing_analysis,
            "best_hours": [
                {"hour": h, "success_rate": d["success_rate"], "sample_count": d["total"]}
                for h, d in best_hours
                if d["total"] >= MIN_SAMPLE_COUNT
            ],
            "recommendation": self._generate_timing_recommendation(best_hours),
        }

    def generate_insights(
        self,
        conn: Connection,
        days: int = 30,
    ) -> List[OutcomeInsight]:
        """インサイトを生成

        Args:
            conn: DB接続
            days: 分析期間（日数）

        Returns:
            インサイトリスト
        """
        insights = []

        # 全体統計
        overall_stats = self.repository.get_statistics(conn, days=days)

        # 全体の採用率が低い場合のインサイト
        if overall_stats.total_events >= MIN_SAMPLE_COUNT:
            if overall_stats.adoption_rate < 0.5:
                insights.append(OutcomeInsight(
                    insight_type="low_adoption_rate",
                    title="採用率が低い",
                    description=f"過去{days}日間の提案採用率が{overall_stats.adoption_rate:.1%}と低めです",
                    evidence={
                        "total_events": overall_stats.total_events,
                        "adoption_rate": overall_stats.adoption_rate,
                    },
                    recommendation="時間帯やメッセージの言い回しを見直すことをお勧めします",
                    confidence=0.8,
                    generated_at=datetime.now(),
                ))

        # 時間帯別の分析
        timing_analysis = self.analyze_timing_effectiveness(conn, days=days)
        best_hours = timing_analysis.get("best_hours", [])

        if best_hours:
            best = best_hours[0]
            if best["success_rate"] >= MIN_SUCCESS_RATE:
                insights.append(OutcomeInsight(
                    insight_type="best_timing",
                    title="最も効果的な時間帯",
                    description=f"{best['hour']}時台の連絡が最も効果的です（成功率: {best['success_rate']:.1%}）",
                    evidence={
                        "hour": best["hour"],
                        "success_rate": best["success_rate"],
                        "sample_count": best["sample_count"],
                    },
                    recommendation=f"重要な連絡は{best['hour']}時台に送ることをお勧めします",
                    confidence=0.7,
                    generated_at=datetime.now(),
                ))

        # 曜日別の分析
        dow_stats = self.repository.get_day_of_week_statistics(conn, days=days)
        best_day = self._find_best_day(dow_stats)

        if best_day and best_day["success_rate"] >= MIN_SUCCESS_RATE:
            insights.append(OutcomeInsight(
                insight_type="best_day_of_week",
                title="最も効果的な曜日",
                description=f"{best_day['day_name']}の連絡が最も効果的です（成功率: {best_day['success_rate']:.1%}）",
                evidence={
                    "day_of_week": best_day["day_of_week"],
                    "day_name": best_day["day_name"],
                    "success_rate": best_day["success_rate"],
                    "sample_count": best_day["sample_count"],
                },
                recommendation=f"重要な連絡は{best_day['day_name']}に送ることをお勧めします",
                confidence=0.65,
                generated_at=datetime.now(),
            ))

        logger.info(f"Generated {len(insights)} insights")
        return insights

    def _find_best_hour(
        self,
        hourly_stats: Dict[int, Dict[str, int]],
    ) -> Optional[Dict[str, Any]]:
        """最も効果的な時間帯を特定

        Args:
            hourly_stats: 時間帯別統計

        Returns:
            最も効果的な時間帯の情報
        """
        best_hour = None
        best_rate = 0.0

        for hour, stats in hourly_stats.items():
            total = stats.get("total", 0)
            if total < MIN_SAMPLE_COUNT:
                continue

            adopted = stats.get("adopted", 0)
            rate = adopted / total

            if rate > best_rate:
                best_rate = rate
                best_hour = {
                    "hour": hour,
                    "success_rate": rate,
                    "sample_count": total,
                }

        return best_hour

    def _find_best_day(
        self,
        dow_stats: Dict[int, Dict[str, int]],
    ) -> Optional[Dict[str, Any]]:
        """最も効果的な曜日を特定

        Args:
            dow_stats: 曜日別統計

        Returns:
            最も効果的な曜日の情報
        """
        best_day = None
        best_rate = 0.0

        for dow, stats in dow_stats.items():
            total = stats.get("total", 0)
            if total < MIN_SAMPLE_COUNT:
                continue

            adopted = stats.get("adopted", 0)
            rate = adopted / total

            if rate > best_rate:
                best_rate = rate
                best_day = {
                    "day_of_week": dow,
                    "day_name": DAY_OF_WEEK_NAMES.get(dow, str(dow)),
                    "success_rate": rate,
                    "sample_count": total,
                }

        return best_day

    def _calculate_responsiveness_score(
        self,
        stats: OutcomeStatistics,
    ) -> float:
        """反応性スコアを計算

        Args:
            stats: 統計

        Returns:
            反応性スコア（0.0〜1.0）
        """
        if stats.total_events == 0:
            return 0.5  # デフォルト

        # 採用率と遅延率を考慮
        adopted_weight = 1.0
        delayed_weight = 0.5
        ignored_weight = 0.0

        weighted_sum = (
            stats.adopted_count * adopted_weight +
            stats.delayed_count * delayed_weight +
            stats.ignored_count * ignored_weight
        )

        max_possible = stats.total_events * adopted_weight

        return weighted_sum / max_possible if max_possible > 0 else 0.5

    def _generate_timing_recommendation(
        self,
        best_hours: List[tuple],
    ) -> Optional[str]:
        """時間帯の推奨を生成

        Args:
            best_hours: 最も効果的な時間帯リスト

        Returns:
            推奨メッセージ
        """
        if not best_hours:
            return None

        best = best_hours[0]
        hour = best[0]
        data = best[1]

        if data["total"] < MIN_SAMPLE_COUNT:
            return None

        if data["success_rate"] >= 0.7:
            return f"{hour}時台の連絡が非常に効果的です。この時間帯を優先することをお勧めします。"
        elif data["success_rate"] >= 0.5:
            return f"{hour}時台の連絡が比較的効果的です。"
        else:
            return None


def create_outcome_analyzer(
    organization_id: str,
    repository: Optional[OutcomeRepository] = None,
) -> OutcomeAnalyzer:
    """OutcomeAnalyzerのファクトリ関数

    Args:
        organization_id: 組織ID
        repository: リポジトリ（Noneの場合は新規作成）

    Returns:
        OutcomeAnalyzer
    """
    if repository is None:
        repository = OutcomeRepository(organization_id)
    return OutcomeAnalyzer(organization_id, repository)
