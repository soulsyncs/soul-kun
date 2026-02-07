"""
Phase 2F: 結果からの学習 - パターン抽出

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2F

成功パターンを自動抽出するクラス。
蓄積された結果データから有意なパターンを発見し、学習として活用できる形式に変換する。
"""

import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.engine import Connection

from .constants import (
    DAY_OF_WEEK_NAMES,
    MIN_CONFIDENCE_SCORE,
    MIN_SAMPLE_COUNT,
    MIN_SUCCESS_RATE,
    PROMOTION_CONFIDENCE_THRESHOLD,
    PROMOTION_MIN_SAMPLE_COUNT,
    TIME_SLOTS,
    OutcomeType,
    PatternScope,
    PatternType,
)
from .models import OutcomePattern, OutcomeStatistics
from .repository import OutcomeRepository


logger = logging.getLogger(__name__)


class PatternExtractor:
    """成功パターン抽出クラス

    抽出するパターン:
    1. 時間帯パターン: 「この人には午前中の連絡が効果的」
    2. 曜日パターン: 「月曜日の連絡は効果的」
    3. タスク種別パターン: 「定例系タスクは遅延しやすい」(将来実装)
    4. コミュニケーションスタイルパターン: (将来実装)

    使用例:
        extractor = PatternExtractor(organization_id, repository)

        # パターン抽出
        patterns = extractor.extract_timing_patterns(conn, target_account_id="12345")

        # 全パターン抽出
        all_patterns = extractor.extract_all_patterns(conn)
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

    def extract_timing_patterns(
        self,
        conn: Connection,
        target_account_id: Optional[str] = None,
        days: int = 30,
    ) -> List[OutcomePattern]:
        """時間帯パターンを抽出

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID（Noneで全体）
            days: 分析期間（日数）

        Returns:
            パターンリスト
        """
        patterns: List[OutcomePattern] = []

        # 時間帯別統計を取得
        hourly_stats = self.repository.get_hourly_statistics(
            conn,
            target_account_id=target_account_id,
            days=days,
        )

        if not hourly_stats:
            return patterns

        # 時間帯グループごとに分析
        for slot_name, slot_range in TIME_SLOTS.items():
            slot_stats = self._aggregate_slot_stats(
                hourly_stats,
                slot_range["start"],
                slot_range["end"],
            )

            if slot_stats["total"] < MIN_SAMPLE_COUNT:
                continue

            success_rate = slot_stats["adopted"] / slot_stats["total"]
            confidence = self._calculate_confidence(
                sample_count=slot_stats["total"],
                success_rate=success_rate,
            )

            if success_rate >= MIN_SUCCESS_RATE and confidence >= MIN_CONFIDENCE_SCORE:
                pattern = OutcomePattern(
                    id=str(uuid4()),
                    organization_id=self.organization_id,
                    pattern_type=PatternType.TIMING.value,
                    pattern_category=slot_name,
                    scope=PatternScope.USER.value if target_account_id else PatternScope.GLOBAL.value,
                    scope_target_id=target_account_id,
                    pattern_content={
                        "type": "timing",
                        "condition": {
                            "hour_range": [slot_range["start"], slot_range["end"]],
                            "slot_name": slot_name,
                        },
                        "effect": "high_response_rate",
                        "description": f"{slot_name}（{slot_range['start']}時〜{slot_range['end']}時）の連絡が効果的",
                    },
                    sample_count=slot_stats["total"],
                    success_count=slot_stats["adopted"],
                    failure_count=slot_stats["ignored"],
                    success_rate=success_rate,
                    confidence_score=confidence,
                )
                patterns.append(pattern)

        return patterns

    def extract_day_of_week_patterns(
        self,
        conn: Connection,
        target_account_id: Optional[str] = None,
        days: int = 30,
    ) -> List[OutcomePattern]:
        """曜日パターンを抽出

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID（Noneで全体）
            days: 分析期間（日数）

        Returns:
            パターンリスト
        """
        patterns: List[OutcomePattern] = []

        # 曜日別統計を取得
        dow_stats = self.repository.get_day_of_week_statistics(
            conn,
            target_account_id=target_account_id,
            days=days,
        )

        if not dow_stats:
            return patterns

        # 曜日ごとに分析
        for dow, stats in dow_stats.items():
            if stats["total"] < MIN_SAMPLE_COUNT:
                continue

            success_rate = stats["adopted"] / stats["total"]
            confidence = self._calculate_confidence(
                sample_count=stats["total"],
                success_rate=success_rate,
            )

            day_name = DAY_OF_WEEK_NAMES.get(dow, str(dow))

            if success_rate >= MIN_SUCCESS_RATE and confidence >= MIN_CONFIDENCE_SCORE:
                pattern = OutcomePattern(
                    id=str(uuid4()),
                    organization_id=self.organization_id,
                    pattern_type=PatternType.DAY_OF_WEEK.value,
                    pattern_category=day_name,
                    scope=PatternScope.USER.value if target_account_id else PatternScope.GLOBAL.value,
                    scope_target_id=target_account_id,
                    pattern_content={
                        "type": "day_of_week",
                        "condition": {
                            "day_of_week": dow,
                            "day_name": day_name,
                        },
                        "effect": "high_response_rate",
                        "description": f"{day_name}の連絡が効果的",
                    },
                    sample_count=stats["total"],
                    success_count=stats["adopted"],
                    failure_count=stats["ignored"],
                    success_rate=success_rate,
                    confidence_score=confidence,
                )
                patterns.append(pattern)

        return patterns

    def extract_user_response_patterns(
        self,
        conn: Connection,
        days: int = 30,
    ) -> List[OutcomePattern]:
        """ユーザー別の反応パターンを抽出

        全ユーザーに対して、それぞれのパターンを抽出する。

        Args:
            conn: DB接続
            days: 分析期間（日数）

        Returns:
            パターンリスト
        """
        patterns = []

        # アクティブユーザーを取得
        users = self._get_active_users(conn, days)

        for user_id in users:
            # 時間帯パターン
            timing_patterns = self.extract_timing_patterns(
                conn,
                target_account_id=user_id,
                days=days,
            )
            patterns.extend(timing_patterns)

            # 曜日パターン
            dow_patterns = self.extract_day_of_week_patterns(
                conn,
                target_account_id=user_id,
                days=days,
            )
            patterns.extend(dow_patterns)

        return patterns

    def extract_all_patterns(
        self,
        conn: Connection,
        days: int = 30,
    ) -> List[OutcomePattern]:
        """全パターンを抽出

        Args:
            conn: DB接続
            days: 分析期間（日数）

        Returns:
            パターンリスト
        """
        patterns = []

        # グローバルパターン
        patterns.extend(self.extract_timing_patterns(conn, days=days))
        patterns.extend(self.extract_day_of_week_patterns(conn, days=days))

        # ユーザー別パターン
        patterns.extend(self.extract_user_response_patterns(conn, days=days))

        logger.info(f"Extracted {len(patterns)} patterns")
        return patterns

    def save_patterns(
        self,
        conn: Connection,
        patterns: List[OutcomePattern],
    ) -> List[str]:
        """パターンを保存

        既存パターンとの重複をチェックし、新規パターンのみ保存する。

        Args:
            conn: DB接続
            patterns: パターンリスト

        Returns:
            保存されたパターンIDリスト
        """
        saved_ids = []

        for pattern in patterns:
            # 既存パターンをチェック
            existing = self.repository.find_patterns(
                conn,
                pattern_type=pattern.pattern_type,
                scope=pattern.scope,
                scope_target_id=pattern.scope_target_id,
            )

            # 同じ条件のパターンがあれば更新
            matching = [
                p for p in existing
                if self._is_same_pattern(p, pattern)
            ]

            if matching:
                # 統計を更新
                existing_pattern = matching[0]
                self.repository.update_pattern_stats(
                    conn,
                    pattern_id=existing_pattern.id or "",
                    sample_count=pattern.sample_count,
                    success_count=pattern.success_count,
                    failure_count=pattern.failure_count,
                    success_rate=pattern.success_rate or 0.0,
                    confidence_score=pattern.confidence_score or 0.0,
                )
                saved_ids.append(existing_pattern.id or "")
            else:
                # 新規保存
                pattern_id = self.repository.save_pattern(conn, pattern)
                saved_ids.append(pattern_id)

        logger.info(f"Saved/updated {len(saved_ids)} patterns")
        return saved_ids

    def find_promotable_patterns(
        self,
        conn: Connection,
    ) -> List[OutcomePattern]:
        """学習に昇格可能なパターンを検索

        Args:
            conn: DB接続

        Returns:
            パターンリスト
        """
        return self.repository.find_promotable_patterns(
            conn,
            min_confidence=PROMOTION_CONFIDENCE_THRESHOLD,
            min_sample_count=PROMOTION_MIN_SAMPLE_COUNT,
        )

    def _aggregate_slot_stats(
        self,
        hourly_stats: Dict[int, Dict[str, int]],
        start_hour: int,
        end_hour: int,
    ) -> Dict[str, int]:
        """時間帯の統計を集計

        Args:
            hourly_stats: 時間帯別統計
            start_hour: 開始時刻
            end_hour: 終了時刻

        Returns:
            集計結果
        """
        total = 0
        adopted = 0
        ignored = 0

        for hour in range(start_hour, end_hour):
            if hour in hourly_stats:
                stats = hourly_stats[hour]
                total += stats.get("total", 0)
                adopted += stats.get("adopted", 0)
                ignored += stats.get("ignored", 0)

        return {
            "total": total,
            "adopted": adopted,
            "ignored": ignored,
        }

    def _calculate_confidence(
        self,
        sample_count: int,
        success_rate: float,
    ) -> float:
        """確信度を計算

        サンプル数と成功率から確信度を計算する。
        Wilson score intervalの簡易版。

        Args:
            sample_count: サンプル数
            success_rate: 成功率

        Returns:
            確信度（0.0〜1.0）
        """
        if sample_count == 0:
            return 0.0

        # サンプル数によるペナルティ
        # sample_count=10で0.5、sample_count=50で0.9に近づく
        sample_factor = 1 - math.exp(-sample_count / 20)

        # 成功率の寄与
        rate_factor = success_rate

        # 確信度 = サンプル数による信頼度 × 成功率
        confidence = sample_factor * rate_factor

        return min(1.0, max(0.0, confidence))

    def _is_same_pattern(
        self,
        pattern1: OutcomePattern,
        pattern2: OutcomePattern,
    ) -> bool:
        """同じパターンかどうかを判定

        Args:
            pattern1: パターン1
            pattern2: パターン2

        Returns:
            同じパターンかどうか
        """
        if pattern1.pattern_type != pattern2.pattern_type:
            return False

        if pattern1.pattern_category != pattern2.pattern_category:
            return False

        content1 = pattern1.pattern_content.get("condition", {})
        content2 = pattern2.pattern_content.get("condition", {})

        return bool(content1 == content2)

    def _get_active_users(
        self,
        conn: Connection,
        days: int,
    ) -> List[str]:
        """アクティブユーザーを取得

        Args:
            conn: DB接続
            days: 期間（日数）

        Returns:
            ユーザーIDリスト
        """
        from datetime import timedelta
        from sqlalchemy import text

        threshold = datetime.now() - timedelta(days=days)

        query = text(f"""
            SELECT DISTINCT target_account_id
            FROM brain_outcome_events
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND event_timestamp >= :threshold
              AND outcome_detected = true
            LIMIT 100
        """)

        try:
            result = conn.execute(query, {
                "organization_id": self.organization_id,
                "threshold": threshold,
            })
            return [row[0] for row in result]
        except Exception as e:
            logger.warning(f"Failed to get active users: {e}")
            return []


def create_pattern_extractor(
    organization_id: str,
    repository: Optional[OutcomeRepository] = None,
) -> PatternExtractor:
    """PatternExtractorのファクトリ関数

    Args:
        organization_id: 組織ID
        repository: リポジトリ（Noneの場合は新規作成）

    Returns:
        PatternExtractor
    """
    if repository is None:
        repository = OutcomeRepository(organization_id)
    return PatternExtractor(organization_id, repository)
