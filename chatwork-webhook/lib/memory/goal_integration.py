"""
Phase 2.5 + B Memory統合: 目標設定への記憶機能統合

このモジュールは、B1(会話サマリー)とB2(ユーザー嗜好)の情報を
目標設定対話に統合し、パーソナライズされた対話を実現する。

Author: Claude Code
Created: 2026-01-24
"""

from typing import Dict, Any, Optional, List
from uuid import UUID
from datetime import datetime, timedelta
import logging

from sqlalchemy import text


logger = logging.getLogger(__name__)


class GoalSettingContextEnricher:
    """
    目標設定対話にMemory Frameworkのコンテキストを統合

    B1(会話サマリー)、B2(ユーザー嗜好)、目標履歴を組み合わせて、
    パーソナライズされた目標設定対話のためのコンテキストを提供する。

    使用例:
        enricher = GoalSettingContextEnricher(conn, org_id)
        context = await enricher.get_enriched_context(user_id)

        # contextをGoalSettingDialogueに渡す
        dialogue = GoalSettingDialogue(pool, room_id, account_id)
        dialogue.set_memory_context(context)
    """

    def __init__(self, conn, org_id: str, openrouter_api_key: Optional[str] = None):
        """
        初期化

        Args:
            conn: データベース接続
            org_id: 組織ID（テナント分離用）
            openrouter_api_key: OpenRouter APIキー（オプション）
        """
        self.conn = conn
        self.org_id = str(org_id) if org_id else None
        self.openrouter_api_key = openrouter_api_key

        # Memory Frameworkのサービスをlazy load
        self._summary_service = None
        self._preference_service = None

    def _get_summary_service(self):
        """ConversationSummaryサービスをlazy loadで取得"""
        if self._summary_service is None:
            try:
                # v10.31.4: 相対インポートに変更（googleapiclient警告修正）
                from .conversation_summary import ConversationSummary
                self._summary_service = ConversationSummary(
                    conn=self.conn,
                    org_id=UUID(self.org_id),
                    openrouter_api_key=self.openrouter_api_key
                )
            except ImportError:
                logger.warning("ConversationSummary not available")
        return self._summary_service

    def _get_preference_service(self):
        """UserPreferenceサービスをlazy loadで取得"""
        if self._preference_service is None:
            try:
                # v10.31.4: 相対インポートに変更（googleapiclient警告修正）
                from .user_preference import UserPreference
                self._preference_service = UserPreference(
                    conn=self.conn,
                    org_id=UUID(self.org_id),
                    openrouter_api_key=self.openrouter_api_key
                )
            except ImportError:
                logger.warning("UserPreference not available")
        return self._preference_service

    async def get_enriched_context(
        self,
        user_id: str,
        include_summaries: bool = True,
        include_preferences: bool = True,
        include_goal_patterns: bool = True
    ) -> Dict[str, Any]:
        """
        統合コンテキストを取得

        Args:
            user_id: ユーザーID
            include_summaries: 会話サマリーを含めるか
            include_preferences: ユーザー嗜好を含めるか
            include_goal_patterns: 目標パターンを含めるか

        Returns:
            統合コンテキスト辞書:
            {
                "conversation_summary": {
                    "recent_topics": ["売上目標", "チーム管理"],
                    "mentioned_tasks": ["プロジェクトA"],
                    "user_concerns": ["リソース不足"]
                },
                "user_preferences": {
                    "response_style": "detailed",
                    "communication_style": "formal",
                    "emotion_trend": {"trend_direction": "stable"}
                },
                "goal_patterns": {
                    "dominant_pattern": "ng_abstract",
                    "avg_retry_count": 1.5,
                    "completion_rate": 75.0
                },
                "recommendations": {
                    "suggested_feedback_style": "supportive",
                    "focus_areas": ["具体的な数値"],
                    "avoid_patterns": ["ng_abstract"]
                }
            }
        """
        if not self.org_id or not user_id:
            return self._empty_context()

        context = {
            "conversation_summary": {},
            "user_preferences": {},
            "goal_patterns": {},
            "recommendations": {}
        }

        try:
            # B1: 会話サマリーから最近のトピックを取得
            if include_summaries:
                context["conversation_summary"] = await self._get_conversation_context(user_id)

            # B2: ユーザー嗜好を取得
            if include_preferences:
                context["user_preferences"] = await self._get_preference_context(user_id)

            # 目標パターンを取得
            if include_goal_patterns:
                context["goal_patterns"] = self._get_goal_pattern_context(user_id)

            # 推奨事項を生成
            context["recommendations"] = self._generate_recommendations(context)

        except Exception as e:
            logger.error(f"Failed to get enriched context: {e}")
            return self._empty_context()

        return context

    async def _get_conversation_context(self, user_id: str) -> Dict[str, Any]:
        """B1会話サマリーからコンテキストを取得"""
        summary_service = self._get_summary_service()
        if not summary_service:
            return {}

        try:
            # 直近7日間のサマリーを取得
            summaries = await summary_service.retrieve(
                user_id=UUID(user_id),
                limit=3,
                from_date=datetime.utcnow() - timedelta(days=7)
            )

            if not summaries:
                return {}

            all_topics = []
            all_tasks = []
            all_persons = []

            for s in summaries:
                all_topics.extend(s.key_topics or [])
                all_tasks.extend(s.mentioned_tasks or [])
                all_persons.extend(s.mentioned_persons or [])

            return {
                "recent_topics": list(set(all_topics))[:5],
                "mentioned_tasks": list(set(all_tasks))[:5],
                "mentioned_persons": list(set(all_persons))[:5],
                "summary_count": len(summaries)
            }

        except Exception as e:
            logger.warning(f"Failed to get conversation context: {e}")
            return {}

    async def _get_preference_context(self, user_id: str) -> Dict[str, Any]:
        """B2ユーザー嗜好からコンテキストを取得"""
        pref_service = self._get_preference_service()
        if not pref_service:
            return {}

        try:
            # 信頼度0.6以上の嗜好を取得
            preferences = await pref_service.retrieve(
                user_id=UUID(user_id),
                min_confidence=0.6
            )

            if not preferences:
                return {}

            result = {}
            for pref in preferences:
                if pref.preference_type == "response_style":
                    result["response_style"] = pref.preference_value
                elif pref.preference_type == "communication":
                    result["communication_style"] = pref.preference_value
                elif pref.preference_type == "emotion_trend":
                    result["emotion_trend"] = pref.preference_value
                elif pref.preference_type == "feature_usage":
                    if pref.preference_key == "goal_setting":
                        result["goal_setting_usage"] = pref.preference_value

            return result

        except Exception as e:
            logger.warning(f"Failed to get preference context: {e}")
            return {}

    def _get_goal_pattern_context(self, user_id: str) -> Dict[str, Any]:
        """目標設定パターンからコンテキストを取得"""
        try:
            result = self.conn.execute(
                text("""
                    SELECT
                        dominant_pattern,
                        pattern_history,
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
                return {}

            return {
                "dominant_pattern": result[0],
                "pattern_history": result[1] or {},
                "avg_retry_count": float(result[2] or 0),
                "completion_rate": float(result[3] or 0),
                "why_tendency": result[4] or {},
                "what_tendency": result[5] or {},
                "how_tendency": result[6] or {},
                "avg_specificity_score": float(result[7] or 0),
                "preferred_feedback_style": result[8]
            }

        except Exception as e:
            logger.warning(f"Failed to get goal pattern context: {e}")
            return {}

    def _generate_recommendations(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """コンテキストから推奨事項を生成"""
        recommendations = {
            "suggested_feedback_style": "supportive",
            "focus_areas": [],
            "avoid_patterns": [],
            "personalization_hints": []
        }

        goal_patterns = context.get("goal_patterns", {})
        preferences = context.get("user_preferences", {})
        summaries = context.get("conversation_summary", {})

        # 目標パターンからの推奨
        if goal_patterns:
            dominant = goal_patterns.get("dominant_pattern")
            avg_retry = goal_patterns.get("avg_retry_count", 0)
            completion_rate = goal_patterns.get("completion_rate", 0)
            avg_score = goal_patterns.get("avg_specificity_score", 0)

            # リトライ回数が多い場合
            if avg_retry > 2:
                recommendations["suggested_feedback_style"] = "gentle"
                recommendations["focus_areas"].append("より具体的な例を提示")

            # 完了率が低い場合
            if completion_rate < 50 and completion_rate > 0:
                recommendations["focus_areas"].append("小さなステップから始める")

            # 具体性スコアが低い場合
            if avg_score < 0.5 and avg_score > 0:
                recommendations["focus_areas"].append("数値や期限の例を多く提示")

            # 最頻出パターンへの対策
            if dominant == "ng_abstract":
                recommendations["avoid_patterns"].append("抽象的な表現")
                recommendations["focus_areas"].append("具体的な数値目標の例を提示")
            elif dominant == "ng_other_blame":
                recommendations["focus_areas"].append("自分でコントロールできることに焦点")
            elif dominant == "ng_career":
                recommendations["personalization_hints"].append("転職志向あり - 社内での成長に焦点を当てる")

            # 好むフィードバックスタイルがあれば適用
            if goal_patterns.get("preferred_feedback_style"):
                recommendations["suggested_feedback_style"] = goal_patterns["preferred_feedback_style"]

        # 感情傾向からの推奨
        emotion_trend = preferences.get("emotion_trend", {})
        if emotion_trend:
            trend_direction = emotion_trend.get("trend_direction")
            if trend_direction == "declining":
                recommendations["suggested_feedback_style"] = "gentle"
                recommendations["personalization_hints"].append("感情傾向が下降中 - 励ましを強化")
            elif trend_direction == "improving":
                recommendations["personalization_hints"].append("感情傾向が上昇中 - ポジティブな雰囲気を維持")

        # 最近のトピックがあれば参照
        recent_topics = summaries.get("recent_topics", [])
        if recent_topics:
            recommendations["personalization_hints"].append(
                f"最近話題: {', '.join(recent_topics[:3])}"
            )

        return recommendations

    def _empty_context(self) -> Dict[str, Any]:
        """空のコンテキストを返す"""
        return {
            "conversation_summary": {},
            "user_preferences": {},
            "goal_patterns": {},
            "recommendations": {
                "suggested_feedback_style": "supportive",
                "focus_areas": [],
                "avoid_patterns": [],
                "personalization_hints": []
            }
        }

    def get_personalization_summary(self, context: Dict[str, Any]) -> str:
        """
        コンテキストからパーソナライゼーションサマリーを生成

        目標設定対話の開始時に、ソウルくんが参照する簡潔な情報。

        Args:
            context: get_enriched_context()の戻り値

        Returns:
            パーソナライゼーションサマリー文字列
        """
        lines = []

        goal_patterns = context.get("goal_patterns", {})
        recommendations = context.get("recommendations", {})

        # 過去のセッション情報
        if goal_patterns.get("completion_rate", 0) > 0:
            lines.append(f"過去の完了率: {goal_patterns['completion_rate']:.0f}%")

        # 苦手パターン
        if goal_patterns.get("dominant_pattern"):
            pattern_names = {
                "ng_abstract": "抽象的な表現が多い",
                "ng_other_blame": "他責的な表現が多い",
                "ng_career": "転職志向がある",
                "ng_no_goal": "目標を持ちにくい",
                "ok": "具体的な目標を設定できている"
            }
            pattern = goal_patterns["dominant_pattern"]
            if pattern in pattern_names:
                lines.append(f"傾向: {pattern_names[pattern]}")

        # 推奨フィードバックスタイル
        style = recommendations.get("suggested_feedback_style", "supportive")
        style_names = {
            "gentle": "優しいトーンで",
            "direct": "ストレートに",
            "supportive": "サポーティブに"
        }
        if style in style_names:
            lines.append(f"対応: {style_names[style]}")

        # フォーカスエリア
        focus_areas = recommendations.get("focus_areas", [])
        if focus_areas:
            lines.append(f"注力: {', '.join(focus_areas[:2])}")

        return "\n".join(lines) if lines else "初回の目標設定"
