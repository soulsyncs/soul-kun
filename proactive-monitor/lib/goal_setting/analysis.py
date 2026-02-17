"""
目標設定対話フロー - パターン分析・履歴提供クラス

GoalSettingUserPatternAnalyzer: ユーザーの目標設定パターンを分析・蓄積
GoalHistoryProvider: 過去の目標・進捗データをコンテキストとして提供
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import text
import json
import logging
import re

logger = logging.getLogger(__name__)


class GoalSettingUserPatternAnalyzer:
    """
    ユーザーの目標設定パターンを分析・蓄積

    目標設定対話の結果を蓄積し、ユーザーの傾向を分析する。
    パーソナライズされたフィードバック生成に活用。

    使用例:
        analyzer = GoalSettingUserPatternAnalyzer(conn, org_id)
        analyzer.update_user_pattern(user_id, session_id, "why", "ng_abstract", False, 2)
        summary = analyzer.get_user_pattern_summary(user_id)
    """

    def __init__(self, conn, org_id: str):
        """
        初期化

        Args:
            conn: データベース接続
            org_id: 組織ID（テナント分離用）
        """
        self.conn = conn
        self.org_id = str(org_id) if org_id else None

    def update_user_pattern(
        self,
        user_id: str,
        session_id: str,
        step: str,
        pattern: str,
        was_accepted: bool,
        retry_count: int,
        specificity_score: float = 0.0
    ) -> None:
        """
        目標設定対話の結果をユーザーパターンに反映

        Args:
            user_id: ユーザーID
            session_id: セッションID
            step: ステップ（why/what/how）
            pattern: 検出されたパターン
            was_accepted: 回答が受け入れられたか
            retry_count: このステップでのリトライ回数
            specificity_score: 具体性スコア（0-1）
        """
        if not self.org_id or not user_id:
            return

        try:
            # 既存レコードを取得
            existing = self.conn.execute(
                text("""
                    SELECT id, pattern_history, total_sessions,
                           why_pattern_tendency, what_pattern_tendency, how_pattern_tendency,
                           avg_specificity_score
                    FROM goal_setting_user_patterns
                    WHERE organization_id = :org_id AND user_id = :user_id
                """),
                {"org_id": self.org_id, "user_id": str(user_id)}
            ).fetchone()

            if existing:
                # 既存レコードを更新
                self._update_existing_pattern(
                    existing, step, pattern, was_accepted, retry_count, specificity_score
                )
            else:
                # 新規レコードを作成
                self._create_new_pattern(
                    user_id, step, pattern, was_accepted, retry_count, specificity_score
                )

            self.conn.commit()

        except Exception as e:
            logger.error("パターン更新エラー（続行）: %s", e)

    def _update_existing_pattern(
        self,
        existing,
        step: str,
        pattern: str,
        was_accepted: bool,
        retry_count: int,
        specificity_score: float
    ) -> None:
        """既存レコードを更新"""
        record_id = existing[0]
        pattern_history = existing[1] or {}
        total_sessions = existing[2] or 0
        why_tendency = existing[3] or {}
        what_tendency = existing[4] or {}
        how_tendency = existing[5] or {}
        avg_score = float(existing[6] or 0)

        # パターン履歴を更新
        pattern_history[pattern] = pattern_history.get(pattern, 0) + 1

        # ステップ別傾向を更新
        step_tendencies = {
            "why": why_tendency,
            "what": what_tendency,
            "how": how_tendency
        }
        if step in step_tendencies:
            step_tendencies[step][pattern] = step_tendencies[step].get(pattern, 0) + 1

        # 最頻出パターンを計算
        dominant = max(pattern_history, key=pattern_history.get) if pattern_history else None

        # 平均具体性スコアを更新（移動平均）
        new_avg_score = (avg_score * 0.8) + (specificity_score * 0.2)

        self.conn.execute(
            text("""
                UPDATE goal_setting_user_patterns
                SET pattern_history = :pattern_history,
                    dominant_pattern = :dominant,
                    why_pattern_tendency = :why_tendency,
                    what_pattern_tendency = :what_tendency,
                    how_pattern_tendency = :how_tendency,
                    avg_specificity_score = :avg_score,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {
                "id": str(record_id),
                "pattern_history": json.dumps(pattern_history),
                "dominant": dominant,
                "why_tendency": json.dumps(step_tendencies["why"]),
                "what_tendency": json.dumps(step_tendencies["what"]),
                "how_tendency": json.dumps(step_tendencies["how"]),
                "avg_score": new_avg_score
            }
        )

    def _create_new_pattern(
        self,
        user_id: str,
        step: str,
        pattern: str,
        was_accepted: bool,
        retry_count: int,
        specificity_score: float
    ) -> None:
        """新規レコードを作成"""
        pattern_history = {pattern: 1}
        step_tendencies = {"why": {}, "what": {}, "how": {}}
        if step in step_tendencies:
            step_tendencies[step] = {pattern: 1}

        self.conn.execute(
            text("""
                INSERT INTO goal_setting_user_patterns (
                    organization_id, user_id, pattern_history, dominant_pattern,
                    why_pattern_tendency, what_pattern_tendency, how_pattern_tendency,
                    total_sessions, avg_specificity_score
                ) VALUES (
                    :org_id, :user_id, :pattern_history, :dominant,
                    :why_tendency, :what_tendency, :how_tendency,
                    1, :avg_score
                )
            """),
            {
                "org_id": self.org_id,
                "user_id": str(user_id),
                "pattern_history": json.dumps(pattern_history),
                "dominant": pattern,
                "why_tendency": json.dumps(step_tendencies["why"]),
                "what_tendency": json.dumps(step_tendencies["what"]),
                "how_tendency": json.dumps(step_tendencies["how"]),
                "avg_score": specificity_score
            }
        )

    def update_session_stats(
        self,
        user_id: str,
        completed: bool,
        total_retry_count: int
    ) -> None:
        """
        セッション統計を更新

        Args:
            user_id: ユーザーID
            completed: セッションが完了したか
            total_retry_count: セッション全体のリトライ回数
        """
        if not self.org_id or not user_id:
            return

        try:
            self.conn.execute(
                text("""
                    UPDATE goal_setting_user_patterns
                    SET total_sessions = total_sessions + 1,
                        completed_sessions = completed_sessions + :completed,
                        completion_rate = CASE
                            WHEN total_sessions + 1 > 0
                            THEN ((completed_sessions + :completed)::DECIMAL / (total_sessions + 1)) * 100
                            ELSE 0
                        END,
                        avg_retry_count = CASE
                            WHEN total_sessions + 1 > 0
                            THEN ((avg_retry_count * total_sessions) + :retry_count) / (total_sessions + 1)
                            ELSE :retry_count
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE organization_id = :org_id AND user_id = :user_id
                """),
                {
                    "org_id": self.org_id,
                    "user_id": str(user_id),
                    "completed": 1 if completed else 0,
                    "retry_count": total_retry_count
                }
            )
            self.conn.commit()
        except Exception as e:
            logger.error("セッション統計更新エラー（続行）: %s", e)

    def get_user_pattern_summary(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        ユーザーのパターン傾向サマリーを取得

        Args:
            user_id: ユーザーID

        Returns:
            パターンサマリー辞書、またはNone
        """
        if not self.org_id or not user_id:
            return None

        try:
            result = self.conn.execute(
                text("""
                    SELECT
                        dominant_pattern,
                        pattern_history,
                        total_sessions,
                        completed_sessions,
                        avg_retry_count,
                        completion_rate,
                        why_pattern_tendency,
                        what_pattern_tendency,
                        how_pattern_tendency,
                        avg_specificity_score,
                        preferred_feedback_style
                    FROM goal_setting_user_patterns
                    WHERE organization_id = :org_id AND user_id = :user_id
                """),
                {"org_id": self.org_id, "user_id": str(user_id)}
            ).fetchone()

            if not result:
                return None

            return {
                "dominant_pattern": result[0],
                "pattern_history": result[1] or {},
                "total_sessions": result[2] or 0,
                "completed_sessions": result[3] or 0,
                "avg_retry_count": float(result[4] or 0),
                "completion_rate": float(result[5] or 0),
                "why_pattern_tendency": result[6] or {},
                "what_pattern_tendency": result[7] or {},
                "how_pattern_tendency": result[8] or {},
                "avg_specificity_score": float(result[9] or 0),
                "preferred_feedback_style": result[10],
                "recommendations": self._generate_recommendations(result)
            }

        except Exception as e:
            logger.error("パターンサマリー取得エラー: %s", e)
            return None

    def _generate_recommendations(self, result) -> Dict[str, Any]:
        """パターン分析結果から推奨事項を生成"""
        dominant = result[0]
        avg_retry = float(result[4] or 0)
        completion_rate = float(result[5] or 0)
        avg_score = float(result[9] or 0)

        recommendations = {
            "suggested_feedback_style": "supportive",  # デフォルト
            "focus_areas": [],
            "avoid_patterns": []
        }

        # リトライ回数が多い場合は優しいフィードバック
        if avg_retry > 2:
            recommendations["suggested_feedback_style"] = "gentle"
            recommendations["focus_areas"].append("より具体的な例を提示")

        # 完了率が低い場合
        if completion_rate < 50:
            recommendations["focus_areas"].append("小さなステップから始める")

        # 具体性スコアが低い場合
        if avg_score < 0.5:
            recommendations["focus_areas"].append("数値や期限の例を多く提示")

        # 最頻出パターンに基づく推奨
        if dominant == "ng_abstract":
            recommendations["avoid_patterns"].append("抽象的な表現")
            recommendations["focus_areas"].append("具体的な数値目標の例を提示")
        elif dominant == "ng_other_blame":
            recommendations["focus_areas"].append("自分でコントロールできることに焦点")

        return recommendations


class GoalHistoryProvider:
    """
    過去の目標・進捗データをコンテキストとして提供

    ユーザーの過去の目標設定履歴を取得し、
    成功パターンや苦手エリアを分析する。

    使用例:
        provider = GoalHistoryProvider(conn, org_id)
        context = provider.get_past_goals_context(user_id)
    """

    def __init__(self, conn, org_id: str):
        """
        初期化

        Args:
            conn: データベース接続
            org_id: 組織ID（テナント分離用）
        """
        self.conn = conn
        self.org_id = str(org_id) if org_id else None

    def get_past_goals_context(
        self,
        user_id: str,
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        過去の目標履歴を取得

        Args:
            user_id: ユーザーID
            limit: 取得件数

        Returns:
            過去目標のコンテキスト辞書
        """
        if not self.org_id or not user_id:
            return {
                "past_goals": [],
                "success_patterns": [],
                "struggle_areas": [],
                "avg_achievement_rate": 0
            }

        try:
            # goalsテーブルから過去の目標を取得
            result = self.conn.execute(
                text("""
                    SELECT
                        g.id,
                        g.title,
                        g.description,
                        g.status,
                        g.target_value,
                        g.current_value,
                        g.deadline,
                        g.created_at
                    FROM goals g
                    WHERE g.organization_id = :org_id
                      AND g.user_id = :user_id
                    ORDER BY g.created_at DESC
                    LIMIT :limit
                """),
                {
                    "org_id": self.org_id,
                    "user_id": str(user_id),
                    "limit": limit
                }
            ).fetchall()

            past_goals = []
            total_achievement = 0
            completed_count = 0

            for row in result:
                goal = {
                    "id": str(row[0]),
                    "title": row[1],
                    "description": row[2],
                    "status": row[3],
                    "target_value": float(row[4]) if row[4] else None,
                    "current_value": float(row[5]) if row[5] else None,
                    "deadline": row[6].isoformat() if row[6] else None,
                    "created_at": row[7].isoformat() if row[7] else None
                }

                # 達成率を計算
                if goal["target_value"] and goal["current_value"]:
                    goal["achievement_rate"] = min(
                        (goal["current_value"] / goal["target_value"]) * 100,
                        100
                    )
                    total_achievement += goal["achievement_rate"]
                    completed_count += 1
                else:
                    goal["achievement_rate"] = 0

                # WHY/WHAT/HOWを抽出（descriptionから）
                self._extract_why_what_how(goal)

                past_goals.append(goal)

            # 成功パターンと苦手エリアを分析
            analysis = self._analyze_patterns(past_goals)

            return {
                "past_goals": past_goals,
                "success_patterns": analysis["success_patterns"],
                "struggle_areas": analysis["struggle_areas"],
                "avg_achievement_rate": (
                    total_achievement / completed_count if completed_count > 0 else 0
                )
            }

        except Exception as e:
            logger.error("過去目標取得エラー: %s", e)
            return {
                "past_goals": [],
                "success_patterns": [],
                "struggle_areas": [],
                "avg_achievement_rate": 0
            }

    def _extract_why_what_how(self, goal: Dict[str, Any]) -> None:
        """descriptionからWHY/WHAT/HOWを抽出"""
        description = goal.get("description", "") or ""

        # WHY: / WHAT: / HOW: パターンを検索
        why_match = re.search(r'WHY[:：]\s*(.+?)(?=WHAT[:：]|HOW[:：]|$)', description, re.DOTALL)
        what_match = re.search(r'WHAT[:：]\s*(.+?)(?=HOW[:：]|$)', description, re.DOTALL)
        how_match = re.search(r'HOW[:：]\s*(.+?)$', description, re.DOTALL)

        goal["why"] = why_match.group(1).strip() if why_match else ""
        goal["what"] = what_match.group(1).strip() if what_match else ""
        goal["how"] = how_match.group(1).strip() if how_match else ""

    def _analyze_patterns(self, past_goals: list) -> Dict[str, list]:
        """過去目標から成功パターンと苦手エリアを分析"""
        success_patterns = []
        struggle_areas = []

        high_achievement_goals = [g for g in past_goals if g.get("achievement_rate", 0) >= 80]
        low_achievement_goals = [g for g in past_goals if g.get("achievement_rate", 0) < 50]

        # 成功パターンを抽出
        for goal in high_achievement_goals:
            if goal.get("target_value"):
                success_patterns.append("数値目標")
            if goal.get("how") and ("毎日" in goal["how"] or "毎週" in goal["how"]):
                success_patterns.append("習慣化")
            if goal.get("deadline"):
                success_patterns.append("期限設定")

        # 苦手エリアを抽出
        for goal in low_achievement_goals:
            if not goal.get("target_value"):
                struggle_areas.append("数値目標の設定")
            if not goal.get("how"):
                struggle_areas.append("具体的な行動計画")

        return {
            "success_patterns": list(set(success_patterns)),
            "struggle_areas": list(set(struggle_areas))
        }

    def get_goal_trend_analysis(self, user_id: str) -> Dict[str, Any]:
        """
        目標達成傾向を分析

        Args:
            user_id: ユーザーID

        Returns:
            傾向分析結果
        """
        context = self.get_past_goals_context(user_id, limit=10)
        past_goals = context.get("past_goals", [])

        if not past_goals:
            return {
                "goal_type_preference": None,
                "period_preference": None,
                "progress_style": None,
                "weak_points": []
            }

        # 目標タイプの傾向
        numeric_count = sum(1 for g in past_goals if g.get("target_value"))
        goal_type_preference = "numeric" if numeric_count > len(past_goals) / 2 else "qualitative"

        # 期間の傾向を分析
        period_preference = self._analyze_period_preference(past_goals)

        # 進捗スタイルを分析
        progress_style = self._analyze_progress_style(past_goals)

        return {
            "goal_type_preference": goal_type_preference,
            "period_preference": period_preference,
            "progress_style": progress_style,
            "weak_points": context.get("struggle_areas", [])
        }

    def _analyze_period_preference(self, past_goals: List[Dict[str, Any]]) -> str:
        """過去目標の期間パターンからユーザーの好む目標期間を判定"""
        period_days_list: List[int] = []
        for g in past_goals:
            deadline_str = g.get("deadline")
            created_str = g.get("created_at")
            if not deadline_str or not created_str:
                continue
            try:
                deadline_dt = datetime.fromisoformat(deadline_str)
                created_dt = datetime.fromisoformat(created_str)
                days = (deadline_dt - created_dt).days
                if days > 0:
                    period_days_list.append(days)
            except (ValueError, TypeError):
                continue

        if not period_days_list:
            return "monthly"

        avg_days = sum(period_days_list) / len(period_days_list)
        if avg_days <= 10:
            return "weekly"
        elif avg_days <= 45:
            return "monthly"
        elif avg_days <= 120:
            return "quarterly"
        else:
            return "yearly"

    def _analyze_progress_style(self, past_goals: List[Dict[str, Any]]) -> str:
        """過去目標の達成パターンからユーザーの進捗スタイルを判定"""
        completed = [g for g in past_goals if g.get("status") == "completed"]
        abandoned = [g for g in past_goals if g.get("status") == "abandoned"]
        active = [g for g in past_goals if g.get("status") == "active"]

        if not past_goals:
            return "steady"

        total = len(past_goals)
        completion_rate = len(completed) / total if total > 0 else 0

        # 達成率のばらつきを確認
        rates = [g.get("achievement_rate", 0) for g in past_goals]
        avg_rate = sum(rates) / len(rates) if rates else 0

        if len(rates) >= 2:
            variance = sum((r - avg_rate) ** 2 for r in rates) / len(rates)
        else:
            variance = 0

        # 放棄率が高い → 三日坊主型
        if len(abandoned) > total * 0.4:
            return "sprint"

        # ばらつきが大きい → 波がある
        if variance > 1000:
            return "fluctuating"

        # 完了率が高く安定 → 着実型
        if completion_rate >= 0.6 and avg_rate >= 60:
            return "steady"

        # 進行中が多い（まだ結果が出ていない）→ slow_start
        if len(active) > total * 0.5:
            return "slow_start"

        return "steady"
