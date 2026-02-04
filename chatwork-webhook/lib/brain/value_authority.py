# lib/brain/value_authority.py
"""
価値観権威層（Value Authority Layer）

v10.42.0 P3: アクション実行直前の最終価値観チェック

【役割】
Decision Layer で決定されたアクションが、ユーザーの人生軸・価値観・長期目標に
照らして「実行して良いか」を最終判定する"門番"レイヤー。

【設計思想】
- 「できるから実行するAI」ではなく「価値観に反しないから実行するAI」
- Decision Layer の再スコアリングではなく、最終承認/拒否の判定
- 厳しすぎない判定（精度より構造完成を優先）

【判定フロー】
Decision → ValueAuthority判定 → OKならExecution / NGなら代替提案 or モード遷移

設計書: docs/13_brain_architecture.md
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# 判定結果の型定義
# =============================================================================


class ValueDecision(Enum):
    """
    価値観権威層の判定結果

    APPROVE: 実行OK
    BLOCK_AND_SUGGEST: 実行ブロック + 代替案提示
    FORCE_MODE_SWITCH: モード強制遷移（傾聴など）
    """
    APPROVE = "approve"
    BLOCK_AND_SUGGEST = "block_and_suggest"
    FORCE_MODE_SWITCH = "force_mode_switch"


@dataclass
class ValueAuthorityResult:
    """
    価値観権威層の判定結果

    Attributes:
        decision: 判定結果（APPROVE/BLOCK_AND_SUGGEST/FORCE_MODE_SWITCH）
        reason: ブロック理由（APPROVEの場合はNone）
        suggested_alternative: 代替アクション名（任意）
        alternative_message: 代替応答メッセージ（任意）
        forced_mode: 強制遷移先モード名（任意）
        violation_type: 違反タイプ（life_axis/long_term_goal/ng_pattern等）
        original_action: 元のアクション名
    """
    decision: ValueDecision
    original_action: str
    reason: Optional[str] = None
    suggested_alternative: Optional[str] = None
    alternative_message: Optional[str] = None
    forced_mode: Optional[str] = None
    violation_type: Optional[str] = None

    @property
    def is_approved(self) -> bool:
        """実行が承認されたか"""
        return self.decision == ValueDecision.APPROVE

    @property
    def should_block(self) -> bool:
        """実行をブロックすべきか"""
        return self.decision in (
            ValueDecision.BLOCK_AND_SUGGEST,
            ValueDecision.FORCE_MODE_SWITCH,
        )

    @property
    def should_force_mode_switch(self) -> bool:
        """モード強制遷移すべきか"""
        return self.decision == ValueDecision.FORCE_MODE_SWITCH


# =============================================================================
# 価値観違反パターン定義
# =============================================================================


# 人生軸と矛盾する行動パターン
LIFE_AXIS_VIOLATION_PATTERNS: Dict[str, Dict[str, Any]] = {
    "family_priority": {
        "axis_keywords": ["家族", "ファミリー", "子供", "育児", "家庭"],
        "violation_patterns": [
            r"深夜.*(作業|仕事|タスク)",
            r"徹夜",
            r"休日.*(出勤|仕事)",
            r"週末.*返上",
        ],
        "alternative_message": (
            "🐺 ちょっと待ってウル！{user_name}さんは家族を大切にしてるウルよね。"
            "この計画だと家族との時間が削られそうウル。"
            "別の方法を一緒に考えようウル🐺"
        ),
    },
    "health_priority": {
        "axis_keywords": ["健康", "体調", "ウェルネス", "睡眠", "運動"],
        "violation_patterns": [
            r"徹夜",
            r"深夜.*作業",
            r"睡眠.*削",
            r"休憩.*なし",
            r"ぶっ通し",
        ],
        "alternative_message": (
            "🐺 待ってウル！{user_name}さんは健康を大事にしてるウルよね。"
            "無理は良くないウル。持続可能なペースを考えようウル🐺"
        ),
    },
    "work_life_balance": {
        "axis_keywords": ["ワークライフバランス", "プライベート", "趣味", "自分の時間"],
        "violation_patterns": [
            r"残業.*前提",
            r"休み.*返上",
            r"プライベート.*犠牲",
        ],
        "alternative_message": (
            "🐺 {user_name}さんはバランスを大切にしてるウルよね。"
            "この計画、ちょっとバランス崩れそうウル。調整しようウル🐺"
        ),
    },
}

# 長期目標と逆方向の行動パターン
GOAL_CONTRADICTION_PATTERNS: Dict[str, Dict[str, Any]] = {
    "independence_goal": {
        "goal_keywords": ["独立", "起業", "フリーランス", "自分の会社"],
        "contradiction_patterns": [
            r"安定.*重視",
            r"リスク.*避け",
            r"現状維持",
            r"挑戦.*やめ",
        ],
        "alternative_message": (
            "🐺 {user_name}さんは独立を目指してるウルよね。"
            "この選択は少し後退かもウル。本当にこれでいいウル？🐺"
        ),
    },
    "growth_goal": {
        "goal_keywords": ["成長", "スキルアップ", "レベルアップ", "自己成長"],
        "contradiction_patterns": [
            r"楽.*したい",
            r"現状.*維持",
            r"挑戦.*しない",
            r"学び.*やめ",
        ],
        "alternative_message": (
            "🐺 {user_name}さんは成長を大切にしてるウルよね。"
            "この方向でいいウル？成長の機会を逃さないでほしいウル🐺"
        ),
    },
    "leadership_goal": {
        "goal_keywords": ["リーダー", "マネージャー", "経営者", "チームを率いる"],
        "contradiction_patterns": [
            r"一人.*で",
            r"任せ.*ない",
            r"抱え込",
            r"委譲.*しない",
        ],
        "alternative_message": (
            "🐺 {user_name}さんはリーダーを目指してるウルよね。"
            "全部自分でやるのはリーダーの道と違うかもウル。"
            "任せることも大事ウル🐺"
        ),
    },
}


# =============================================================================
# Value Authority クラス
# =============================================================================


class ValueAuthority:
    """
    価値観権威層

    ユーザーの人生軸・価値観・長期目標に照らして
    「このアクションは実行してよいか」を最終判定するレイヤー。

    使用例:
        authority = ValueAuthority(
            user_life_axis=user_life_axis_data,
            user_name="菊地",
        )
        result = authority.evaluate_action(
            action="chatwork_task_create",
            action_params={"task_body": "徹夜で資料作成"},
            user_message="徹夜で資料作成のタスク追加して",
            ng_pattern_result=None,
        )
        if result.should_block:
            return result.alternative_message
    """

    def __init__(
        self,
        user_life_axis: Optional[List[Dict[str, Any]]] = None,
        user_name: str = "",
        organization_id: str = "",
    ):
        """
        Args:
            user_life_axis: ユーザーの人生軸データ（UserLongTermMemory.get_all()の結果）
            user_name: ユーザー名（メッセージ生成用）
            organization_id: 組織ID
        """
        self.user_life_axis = user_life_axis or []
        self.user_name = user_name or "あなた"
        self.organization_id = organization_id

        # 人生軸データを解析してキャッシュ
        self._parsed_axis = self._parse_life_axis()

        logger.debug(
            f"ValueAuthority initialized: "
            f"life_axis_count={len(self.user_life_axis)}, "
            f"user_name={user_name}"
        )

    def _parse_life_axis(self) -> Dict[str, List[str]]:
        """
        人生軸データを解析して検索しやすい形式に変換

        Returns:
            {
                "life_why": ["人生WHYの内容"],
                "values": ["価値観1", "価値観2"],
                "long_term_goals": ["目標1", "目標2"],
                "principles": ["原則1"],
            }
        """
        parsed: Dict[str, List[str]] = {
            "life_why": [],
            "values": [],
            "long_term_goals": [],
            "principles": [],
            "identity": [],
        }

        for memory in self.user_life_axis:
            memory_type = memory.get("memory_type", "")
            content = memory.get("content", "")

            if memory_type == "life_why":
                parsed["life_why"].append(content)
            elif memory_type == "values":
                parsed["values"].append(content)
            elif memory_type == "long_term_goal":
                parsed["long_term_goals"].append(content)
            elif memory_type == "principles":
                parsed["principles"].append(content)
            elif memory_type == "identity":
                parsed["identity"].append(content)

        return parsed

    def evaluate_action(
        self,
        action: str,
        action_params: Optional[Dict[str, Any]] = None,
        user_message: str = "",
        ng_pattern_result: Optional[Dict[str, Any]] = None,
    ) -> ValueAuthorityResult:
        """
        アクションが価値観に反していないかを評価

        Args:
            action: 実行予定のアクション名
            action_params: アクションパラメータ
            user_message: 元のユーザーメッセージ
            ng_pattern_result: P1のNGパターン検出結果（あれば）

        Returns:
            ValueAuthorityResult: 判定結果
        """
        action_params = action_params or {}

        logger.debug(
            f"🔍 [ValueAuthority] Evaluating action: {action}"
        )

        # ① NGパターンがCRITICALの場合 → FORCE_MODE_SWITCH
        if ng_pattern_result:
            ng_result = self._check_ng_pattern_critical(ng_pattern_result)
            if ng_result:
                return ng_result

        # 人生軸データがない場合は常にAPPROVE
        if not self.user_life_axis:
            logger.debug(
                "[ValueAuthority] No life axis data, auto-approving"
            )
            return ValueAuthorityResult(
                decision=ValueDecision.APPROVE,
                original_action=action,
            )

        # ② 人生軸との矛盾チェック
        life_axis_violation = self._check_life_axis_violation(
            action, action_params, user_message
        )
        if life_axis_violation:
            return life_axis_violation

        # ③ 長期目標との矛盾チェック
        goal_contradiction = self._check_goal_contradiction(
            action, action_params, user_message
        )
        if goal_contradiction:
            return goal_contradiction

        # ④ それ以外 → APPROVE
        logger.debug(
            f"✅ [ValueAuthority] Action approved: {action}"
        )
        return ValueAuthorityResult(
            decision=ValueDecision.APPROVE,
            original_action=action,
        )

    def _check_ng_pattern_critical(
        self,
        ng_pattern_result: Dict[str, Any],
    ) -> Optional[ValueAuthorityResult]:
        """
        NGパターンがCRITICALの場合のチェック

        Args:
            ng_pattern_result: NGパターン検出結果

        Returns:
            CRITICAL時はFORCE_MODE_SWITCH結果、それ以外はNone
        """
        risk_level = ng_pattern_result.get("risk_level", "")
        pattern_type = ng_pattern_result.get("pattern_type", "")

        # CRITICALの場合は傾聴モードへ強制遷移
        if risk_level == "CRITICAL":
            logger.warning(
                f"🚨 [ValueAuthority] CRITICAL NG pattern detected: {pattern_type}"
            )
            return ValueAuthorityResult(
                decision=ValueDecision.FORCE_MODE_SWITCH,
                original_action=ng_pattern_result.get("original_action", ""),
                reason=f"CRITICAL: {pattern_type}",
                forced_mode="listening",
                violation_type="ng_pattern_critical",
                alternative_message=(
                    "つらい状況なんだウルね。話してくれてありがとうウル。"
                    "専門家に相談することも考えてほしいウル。"
                    "今は何でも話していいウル🐺"
                ),
            )

        # HIGHの場合も傾聴モードへ
        if risk_level == "HIGH":
            logger.warning(
                f"⚠️ [ValueAuthority] HIGH NG pattern detected: {pattern_type}"
            )
            return ValueAuthorityResult(
                decision=ValueDecision.FORCE_MODE_SWITCH,
                original_action=ng_pattern_result.get("original_action", ""),
                reason=f"HIGH: {pattern_type}",
                forced_mode="listening",
                violation_type="ng_pattern_high",
                alternative_message=(
                    "そう感じてるウルね。まず話を聞かせてウル🐺"
                ),
            )

        return None

    def _check_life_axis_violation(
        self,
        action: str,
        action_params: Dict[str, Any],
        user_message: str,
    ) -> Optional[ValueAuthorityResult]:
        """
        人生軸との矛盾をチェック

        例: 「家族優先」が人生軸なのに深夜まで作業提案

        Returns:
            矛盾がある場合はBLOCK_AND_SUGGEST結果、なければNone
        """
        # 全ての人生軸テキストを結合
        all_axis_text = " ".join(
            self._parsed_axis.get("life_why", []) +
            self._parsed_axis.get("values", []) +
            self._parsed_axis.get("principles", []) +
            self._parsed_axis.get("identity", [])
        ).lower()

        if not all_axis_text:
            return None

        # 検査対象テキスト
        check_text = f"{user_message} {action_params.get('task_body', '')}".lower()

        # 各違反パターンをチェック
        for violation_key, violation_def in LIFE_AXIS_VIOLATION_PATTERNS.items():
            axis_keywords = violation_def.get("axis_keywords", [])
            violation_patterns = violation_def.get("violation_patterns", [])

            # このユーザーがこの人生軸を持っているか
            has_this_axis = any(
                kw.lower() in all_axis_text for kw in axis_keywords
            )

            if not has_this_axis:
                continue

            # 違反パターンに該当するか
            for pattern in violation_patterns:
                if re.search(pattern, check_text):
                    logger.info(
                        f"💡 [ValueAuthority] Life axis violation detected: "
                        f"axis={violation_key}, pattern={pattern}"
                    )

                    alternative_msg = violation_def.get(
                        "alternative_message", ""
                    ).format(user_name=self.user_name)

                    return ValueAuthorityResult(
                        decision=ValueDecision.BLOCK_AND_SUGGEST,
                        original_action=action,
                        reason=f"人生軸「{violation_key}」との矛盾を検出",
                        violation_type=f"life_axis_{violation_key}",
                        alternative_message=alternative_msg,
                        suggested_alternative="general_conversation",
                    )

        return None

    def _check_goal_contradiction(
        self,
        action: str,
        action_params: Dict[str, Any],
        user_message: str,
    ) -> Optional[ValueAuthorityResult]:
        """
        長期目標との矛盾をチェック

        例: 独立目標なのに安定志向への後退提案

        Returns:
            矛盾がある場合はBLOCK_AND_SUGGEST結果、なければNone
        """
        # 長期目標テキスト
        goals_text = " ".join(
            self._parsed_axis.get("long_term_goals", [])
        ).lower()

        if not goals_text:
            return None

        # 検査対象テキスト
        check_text = f"{user_message} {action_params.get('task_body', '')}".lower()

        # 各矛盾パターンをチェック
        for contradiction_key, contradiction_def in GOAL_CONTRADICTION_PATTERNS.items():
            goal_keywords = contradiction_def.get("goal_keywords", [])
            contradiction_patterns = contradiction_def.get("contradiction_patterns", [])

            # このユーザーがこの目標を持っているか
            has_this_goal = any(
                kw.lower() in goals_text for kw in goal_keywords
            )

            if not has_this_goal:
                continue

            # 矛盾パターンに該当するか
            for pattern in contradiction_patterns:
                if re.search(pattern, check_text):
                    logger.info(
                        f"💡 [ValueAuthority] Goal contradiction detected: "
                        f"goal={contradiction_key}, pattern={pattern}"
                    )

                    alternative_msg = contradiction_def.get(
                        "alternative_message", ""
                    ).format(user_name=self.user_name)

                    return ValueAuthorityResult(
                        decision=ValueDecision.BLOCK_AND_SUGGEST,
                        original_action=action,
                        reason=f"長期目標「{contradiction_key}」との矛盾を検出",
                        violation_type=f"goal_{contradiction_key}",
                        alternative_message=alternative_msg,
                        suggested_alternative="general_conversation",
                    )

        return None


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_value_authority(
    user_life_axis: Optional[List[Dict[str, Any]]] = None,
    user_name: str = "",
    organization_id: str = "",
) -> ValueAuthority:
    """
    ValueAuthorityのインスタンスを作成

    Args:
        user_life_axis: ユーザーの人生軸データ
        user_name: ユーザー名
        organization_id: 組織ID

    Returns:
        ValueAuthority インスタンス
    """
    return ValueAuthority(
        user_life_axis=user_life_axis,
        user_name=user_name,
        organization_id=organization_id,
    )
