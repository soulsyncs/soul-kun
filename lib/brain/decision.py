# lib/brain/decision.py
"""
ソウルくんの脳 - 判断層（Decision Layer）

このファイルには、理解した意図に基づいてどの機能を実行するかを決定する判断層を定義します。
SYSTEM_CAPABILITIESカタログから機能を動的に選択し、MVVに沿った判断を行います。

設計書: docs/13_brain_architecture.md

【判断の5ステップ】
1. 状態チェック: マルチステップセッション中か、pending操作があるか
2. 機能候補の抽出: SYSTEM_CAPABILITIESから候補を抽出しスコアリング
3. 確認要否の判断: 確信度・危険度に基づき確認モードを発動
4. MVV整合性チェック: NGパターン検出、トーン適切性
5. 実行コマンドの生成: アクション名・パラメータ・確信度・理由
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Callable

from lib.brain.models import (
    BrainContext,
    UnderstandingResult,
    DecisionResult,
    ActionCandidate,
    ConfirmationRequest,
    StateType,
    ConfidenceLevel,
)
from lib.brain.constants import (
    CONFIRMATION_THRESHOLD,
    AUTO_EXECUTE_THRESHOLD,
    DANGEROUS_ACTIONS,
    CAPABILITY_SCORING_WEIGHTS,
    CONJUNCTION_PATTERNS,
    CANCEL_KEYWORDS,
    SPLIT_PATTERNS,
    CAPABILITY_MIN_SCORE_THRESHOLD,
    RISK_LEVELS,
    CONFIRMATION_REQUIRED_RISK_LEVELS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 判断層プロンプト（LLM使用時）
# =============================================================================

DECISION_PROMPT = """あなたはソウルくんの脳の「判断層」です。
理解層から受け取った意図に基づいて、最適な機能を選択してください。

## 使用可能な機能カタログ:
{capabilities_json}

## ユーザーの意図:
- 意図: {intent}
- 確信度: {confidence}
- エンティティ: {entities}
- 元のメッセージ: {raw_message}

## コンテキスト:
{context}

## タスク:
1. 上記の意図に最も適合する機能を選択してください
2. 複数の機能が必要な場合はリストで返してください
3. 確認が必要な場合はその理由を説明してください

## 出力形式（JSON）:
{{
    "selected_action": "機能キー",
    "params": {{}},
    "confidence": 0.0-1.0,
    "reasoning": "選択理由",
    "needs_confirmation": true/false,
    "confirmation_question": "確認が必要な場合の質問",
    "other_candidates": [
        {{"action": "候補", "score": 0.0}}
    ]
}}"""


# =============================================================================
# 機能選択キーワード（スコアリング用）
# =============================================================================

# 各機能に対するキーワードマッピング
# intent_keywords は SYSTEM_CAPABILITIES に追加予定の拡張フィールド
# 現状は trigger_examples + description から抽出
CAPABILITY_KEYWORDS: Dict[str, Dict[str, List[str]]] = {
    "chatwork_task_create": {
        "primary": ["タスク作成", "タスク追加", "タスク作って", "依頼して", "お願いして"],
        "secondary": ["タスク", "仕事", "やること", "依頼", "お願い"],
        "negative": ["検索", "一覧", "教えて", "完了"],
    },
    "chatwork_task_search": {
        "primary": ["タスク検索", "タスク教えて", "タスク一覧", "タスク確認"],
        "secondary": ["タスク", "何がある", "抱えてる"],
        "negative": ["作成", "追加", "作って", "完了"],
    },
    "chatwork_task_complete": {
        "primary": ["タスク完了", "完了にして", "終わった", "できた"],
        "secondary": ["完了", "終わり", "done"],
        "negative": ["作成", "追加", "検索"],
    },
    "goal_registration": {  # v10.29.6: SYSTEM_CAPABILITIESと名前を統一
        "primary": ["目標設定", "目標を立てたい", "目標を決めたい", "目標設定したい"],
        "secondary": ["目標", "ゴール"],
        "negative": ["進捗", "報告", "確認"],
    },
    "goal_progress_report": {
        "primary": ["目標進捗", "目標報告", "進捗報告"],
        "secondary": ["進捗", "どのくらい"],
        "negative": ["設定", "立てたい"],
    },
    "save_memory": {
        "primary": ["覚えて", "記憶して", "メモして"],
        "secondary": ["は〜です", "さんは", "の人"],
        "negative": ["忘れて", "削除", "教えて"],
    },
    "query_memory": {
        "primary": ["覚えてる", "知ってる", "について教えて"],
        "secondary": ["誰", "情報"],
        "negative": ["覚えて", "記憶して", "忘れて"],
    },
    "delete_memory": {
        "primary": ["忘れて", "削除して", "消して"],
        "secondary": ["記憶", "情報"],
        "negative": ["覚えて", "教えて"],
    },
    "learn_knowledge": {
        "primary": ["ナレッジ追加", "知識を覚えて", "教えておくね"],
        "secondary": ["ナレッジ", "知識", "情報"],
        "negative": ["検索", "教えて", "忘れて"],
    },
    "query_knowledge": {
        "primary": ["ナレッジ検索", "知識を教えて", "会社について"],
        "secondary": ["どうやって", "方法", "やり方"],
        "negative": ["追加", "覚えて", "忘れて"],
    },
    "forget_knowledge": {
        "primary": ["ナレッジ削除", "知識を忘れて"],
        "secondary": ["削除", "忘れて"],
        "negative": ["追加", "検索", "教えて"],
    },
    "query_org_chart": {
        "primary": ["組織図", "部署", "誰がいる"],
        "secondary": ["組織", "構造", "チーム"],
        "negative": [],
    },
    # v10.29.9: send_announcement → announcement_create（SYSTEM_CAPABILITIESと統一）
    "announcement_create": {
        "primary": ["アナウンス", "お知らせ", "連絡して", "伝えて"],
        "secondary": ["全員に", "チャットに"],
        "negative": [],
    },
    # v10.29.9: 追加（SYSTEM_CAPABILITIESと統一）
    "proposal_decision": {
        "primary": ["承認", "却下", "反映して"],
        "secondary": ["OK", "いいよ", "ダメ", "やめて"],
        "negative": [],
    },
    # v10.29.9: 追加（SYSTEM_CAPABILITIESと統一）
    "general_conversation": {
        "primary": [],
        "secondary": ["こんにちは", "ありがとう", "どう思う"],
        "negative": [],
    },
}

# NOTE: RISK_LEVELS と SPLIT_PATTERNS は lib/brain/constants.py からインポート


# =============================================================================
# MVV整合性チェック用（lib/mvv_context.pyを使用）
# =============================================================================

# MVV関連のインポートは遅延で行う（循環参照防止）
_mvv_context_loaded = False
_detect_ng_pattern = None


def _load_mvv_context():
    """MVVコンテキストモジュールを遅延ロード"""
    global _mvv_context_loaded, _detect_ng_pattern
    if not _mvv_context_loaded:
        try:
            from lib.mvv_context import detect_ng_pattern
            _detect_ng_pattern = detect_ng_pattern
            _mvv_context_loaded = True
            logger.debug("MVV context module loaded successfully")
        except ImportError as e:
            logger.warning(f"Could not load mvv_context: {e}")
            _mvv_context_loaded = True  # 再試行防止


# =============================================================================
# 判断層クラス
# =============================================================================


@dataclass
class MVVCheckResult:
    """MVV整合性チェック結果"""
    is_aligned: bool = True
    ng_pattern_detected: bool = False
    ng_pattern_type: Optional[str] = None
    ng_response_hint: Optional[str] = None
    risk_level: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


class BrainDecision:
    """
    判断層クラス

    理解層から受け取った意図に基づいて、どの機能を実行するかを決定する。

    使用例:
        decision = BrainDecision(
            capabilities=SYSTEM_CAPABILITIES,
            get_ai_response_func=get_ai_response,
            org_id="org_soulsyncs",
        )
        result = await decision.decide(understanding, context)
    """

    def __init__(
        self,
        capabilities: Optional[Dict[str, Dict]] = None,
        get_ai_response_func: Optional[Callable] = None,
        org_id: str = "",
        use_llm: bool = False,
    ):
        """
        Args:
            capabilities: SYSTEM_CAPABILITIES（機能カタログ）
            get_ai_response_func: AI応答生成関数（LLM使用時）
            org_id: 組織ID
            use_llm: LLMを使用して判断するか（Falseの場合はルールベース）
        """
        self.capabilities = capabilities or {}
        self.get_ai_response = get_ai_response_func
        self.org_id = org_id
        self.use_llm = use_llm

        # 有効な機能のみをフィルタ
        self.enabled_capabilities = {
            key: cap for key, cap in self.capabilities.items()
            if cap.get("enabled", True)
        }

        logger.info(
            f"BrainDecision initialized: "
            f"capabilities={len(self.enabled_capabilities)}, "
            f"use_llm={use_llm}"
        )

    # =========================================================================
    # メイン判断メソッド
    # =========================================================================

    async def decide(
        self,
        understanding: UnderstandingResult,
        context: BrainContext,
    ) -> DecisionResult:
        """
        理解した意図に基づいてアクションを決定

        Args:
            understanding: 理解層の出力
            context: 脳のコンテキスト

        Returns:
            DecisionResult: 判断結果
        """
        start_time = time.time()

        try:
            # ステップ1: 状態チェック
            if context.has_active_session():
                return self._handle_active_session(understanding, context, start_time)

            # ステップ2: 複数アクション検出
            multiple_actions = self._detect_multiple_actions(understanding.raw_message)
            if len(multiple_actions) > 1:
                # 最初のアクションを処理、残りはキューに入れる
                logger.info(f"Multiple actions detected: {len(multiple_actions)}")
                # TODO: 複数アクションのキュー管理（Phase F以降）

            # ステップ3: 機能候補の抽出とスコアリング
            candidates = self._score_capabilities(understanding)

            if not candidates:
                # 候補がない場合は汎用応答
                # v10.29.7: general_response → general_conversation（ハンドラー名と統一）
                return DecisionResult(
                    action="general_conversation",
                    params={"message": understanding.raw_message},
                    confidence=0.3,
                    reasoning="No matching capability found",
                    processing_time_ms=self._elapsed_ms(start_time),
                )

            # ステップ4: 最適な候補を選択
            best_candidate = candidates[0]
            other_candidates = candidates[1:5]  # 上位5件まで

            # ステップ5: 確認要否の判断
            needs_confirmation, confirmation_question, confirmation_options = (
                self._determine_confirmation(
                    best_candidate,
                    understanding,
                    context,
                )
            )

            # ステップ6: MVV整合性チェック
            mvv_result = self._check_mvv_alignment(
                understanding.raw_message,
                best_candidate.action,
            )

            # MVVでNGが検出された場合
            if mvv_result.ng_pattern_detected:
                logger.warning(
                    f"NG pattern detected: {mvv_result.ng_pattern_type}"
                )
                # NGパターンの場合でも処理は続行するが、警告を付与
                # 実際の対応はレスポンス生成層で行う

            # パラメータをマージ（理解層のエンティティ + 候補のパラメータ）
            merged_params = {**understanding.entities, **best_candidate.params}

            return DecisionResult(
                action=best_candidate.action,
                params=merged_params,
                confidence=best_candidate.score,
                needs_confirmation=needs_confirmation,
                confirmation_question=confirmation_question,
                confirmation_options=confirmation_options,
                other_candidates=other_candidates,
                reasoning=self._build_reasoning(
                    best_candidate,
                    understanding,
                    mvv_result,
                ),
                processing_time_ms=self._elapsed_ms(start_time),
            )

        except Exception as e:
            logger.error(f"Decision error: {e}", exc_info=True)
            return DecisionResult(
                action="error",
                params={"error": str(e)},
                confidence=0.0,
                reasoning=f"Error during decision: {e}",
                processing_time_ms=self._elapsed_ms(start_time),
            )

    # =========================================================================
    # ステップ1: 状態チェック
    # =========================================================================

    def _handle_active_session(
        self,
        understanding: UnderstandingResult,
        context: BrainContext,
        start_time: float,
    ) -> DecisionResult:
        """アクティブなセッション中の判断処理"""
        state = context.current_state
        state_type = state.state_type if state else StateType.NORMAL

        # キャンセル要求のチェック
        if self._is_cancel_request(understanding.raw_message):
            return DecisionResult(
                action="cancel_session",
                params={"state_type": state_type.value if state_type else "unknown"},
                confidence=1.0,
                reasoning="Cancel request detected during active session",
                processing_time_ms=self._elapsed_ms(start_time),
            )

        # 状態タイプに応じた処理
        if state_type == StateType.GOAL_SETTING:
            return DecisionResult(
                action="continue_goal_setting",
                params={
                    "step": state.state_step if state else "unknown",
                    "response": understanding.raw_message,
                },
                confidence=1.0,
                reasoning="Continuing goal setting session",
                processing_time_ms=self._elapsed_ms(start_time),
            )

        elif state_type == StateType.ANNOUNCEMENT:
            return DecisionResult(
                action="continue_announcement",
                params={
                    "response": understanding.raw_message,
                },
                confidence=1.0,
                reasoning="Continuing announcement confirmation",
                processing_time_ms=self._elapsed_ms(start_time),
            )

        elif state_type == StateType.CONFIRMATION:
            return DecisionResult(
                action="handle_confirmation_response",
                params={
                    "response": understanding.raw_message,
                    "pending_action": state.state_data.get("pending_action") if state else None,
                },
                confidence=1.0,
                reasoning="Handling confirmation response",
                processing_time_ms=self._elapsed_ms(start_time),
            )

        # デフォルト: 通常処理に戻す
        return DecisionResult(
            action="continue_session",
            params={
                "state_type": state_type.value if state_type else "unknown",
                "response": understanding.raw_message,
            },
            confidence=0.8,
            reasoning="Continuing active session",
            processing_time_ms=self._elapsed_ms(start_time),
        )

    # =========================================================================
    # ステップ2: 複数アクション検出
    # =========================================================================

    def _detect_multiple_actions(self, message: str) -> List[str]:
        """
        メッセージから複数のアクションを検出

        例: 「崇樹にタスク追加して、あと自分のタスク教えて」
        → ["崇樹にタスク追加して", "自分のタスク教えて"]
        """
        segments = [message]

        for pattern in SPLIT_PATTERNS:
            new_segments = []
            for segment in segments:
                parts = re.split(pattern, segment)
                parts = [p.strip() for p in parts if p.strip()]
                new_segments.extend(parts)
            segments = new_segments

        # 空のセグメントを除去
        segments = [s for s in segments if len(s) > 2]

        return segments if segments else [message]

    # =========================================================================
    # ステップ3: 機能候補の抽出とスコアリング
    # =========================================================================

    def _score_capabilities(
        self,
        understanding: UnderstandingResult,
    ) -> List[ActionCandidate]:
        """
        全ての機能に対してスコアリングを行い、候補リストを返す

        スコア = キーワードマッチ(40%) + 意図マッチ(30%) + 文脈マッチ(30%)
        """
        candidates = []

        for cap_key, capability in self.enabled_capabilities.items():
            score = self._score_capability(
                cap_key,
                capability,
                understanding,
            )

            if score > CAPABILITY_MIN_SCORE_THRESHOLD:  # 最低スコア閾値
                candidates.append(ActionCandidate(
                    action=cap_key,
                    score=score,
                    params=self._extract_params_for_capability(
                        cap_key,
                        capability,
                        understanding,
                    ),
                    reasoning=f"Score: {score:.2f}",
                ))

        # スコア順にソート
        candidates.sort(key=lambda c: c.score, reverse=True)

        return candidates

    def _score_capability(
        self,
        cap_key: str,
        capability: Dict[str, Any],
        understanding: UnderstandingResult,
    ) -> float:
        """
        単一の機能に対するスコアを計算

        スコア = キーワードマッチ(40%) + 意図マッチ(30%) + 文脈マッチ(30%)
        """
        weights = CAPABILITY_SCORING_WEIGHTS
        message = understanding.raw_message.lower()
        intent = understanding.intent

        # 1. キーワードマッチ（40%）
        keyword_score = self._calculate_keyword_score(cap_key, message)

        # 2. 意図マッチ（30%）
        intent_score = self._calculate_intent_score(cap_key, intent, capability)

        # 3. 文脈マッチ（30%）
        context_score = self._calculate_context_score(cap_key, understanding)

        # 重み付け合計
        total_score = (
            keyword_score * weights.get("keyword_match", 0.4) +
            intent_score * weights.get("intent_match", 0.3) +
            context_score * weights.get("context_match", 0.3)
        )

        return min(1.0, total_score)

    def _calculate_keyword_score(
        self,
        cap_key: str,
        message: str,
    ) -> float:
        """キーワードマッチスコアを計算"""
        keywords = CAPABILITY_KEYWORDS.get(cap_key, {})
        if not keywords:
            # キーワード定義がない場合はcapabilityのdescriptionから
            return 0.0

        primary = keywords.get("primary", [])
        secondary = keywords.get("secondary", [])
        negative = keywords.get("negative", [])

        # ネガティブキーワードがあればスコアを下げる
        for neg in negative:
            if neg in message:
                return 0.0

        # プライマリキーワードのマッチ
        primary_matches = sum(1 for kw in primary if kw in message)
        if primary_matches > 0:
            return min(1.0, primary_matches * 0.5)

        # セカンダリキーワードのマッチ
        secondary_matches = sum(1 for kw in secondary if kw in message)
        if secondary_matches > 0:
            return min(0.7, secondary_matches * 0.3)

        return 0.0

    def _calculate_intent_score(
        self,
        cap_key: str,
        intent: str,
        capability: Dict[str, Any],
    ) -> float:
        """意図マッチスコアを計算"""
        # 完全一致
        if intent == cap_key:
            return 1.0

        # カテゴリマッチ
        cap_category = capability.get("category", "")
        if cap_category and cap_category in intent:
            return 0.6

        # trigger_examplesとの部分一致
        trigger_examples = capability.get("trigger_examples", [])
        for example in trigger_examples:
            if intent in example or example in intent:
                return 0.5

        return 0.0

    def _calculate_context_score(
        self,
        cap_key: str,
        understanding: UnderstandingResult,
    ) -> float:
        """文脈マッチスコアを計算"""
        entities = understanding.entities

        # エンティティの存在によるスコア加算
        score = 0.0

        # タスク関連
        if cap_key.startswith("chatwork_task_"):
            if "task" in entities or "person" in entities:
                score += 0.5

        # 目標関連
        if cap_key.startswith("goal_"):
            if "goal" in entities or "why" in entities:
                score += 0.5

        # 記憶関連
        if cap_key in ["save_memory", "query_memory", "delete_memory"]:
            if "person" in entities:
                score += 0.5

        # 知識関連
        if cap_key in ["learn_knowledge", "query_knowledge", "forget_knowledge"]:
            if "knowledge" in entities or "topic" in entities:
                score += 0.5

        return min(1.0, score)

    def _extract_params_for_capability(
        self,
        cap_key: str,
        capability: Dict[str, Any],
        understanding: UnderstandingResult,
    ) -> Dict[str, Any]:
        """機能に必要なパラメータを抽出"""
        params = {}
        schema = capability.get("params_schema", {})

        for param_name, param_def in schema.items():
            # 理解層のエンティティから対応する値を探す
            if param_name in understanding.entities:
                params[param_name] = understanding.entities[param_name]

            # エイリアスからの変換
            elif param_name == "assigned_to" and "person" in understanding.entities:
                params[param_name] = understanding.entities["person"]
            elif param_name == "task_body" and "task" in understanding.entities:
                params[param_name] = understanding.entities["task"]
            elif param_name == "person_name" and "person" in understanding.entities:
                params[param_name] = understanding.entities["person"]

        return params

    # =========================================================================
    # ステップ4: 確認要否の判断
    # =========================================================================

    def _determine_confirmation(
        self,
        candidate: ActionCandidate,
        understanding: UnderstandingResult,
        context: BrainContext,
    ) -> Tuple[bool, Optional[str], List[str]]:
        """
        確認が必要かどうかを判断

        Returns:
            (needs_confirmation, confirmation_question, confirmation_options)
        """
        action = candidate.action
        confidence = candidate.score

        # 理由と選択肢
        question = None
        options = ["はい", "いいえ"]

        # 確信度が低い場合
        if confidence < CONFIRMATION_THRESHOLD:
            question = f"「{understanding.raw_message}」は「{self._get_capability_name(action)}」でいいウル？"
            return (True, question, options)

        # 危険な操作の場合
        if action in DANGEROUS_ACTIONS:
            question = f"本当に「{self._get_capability_name(action)}」を実行していいウル？"
            return (True, question, options)

        # リスクレベルが高い場合
        risk_level = RISK_LEVELS.get(action, "low")
        if risk_level in CONFIRMATION_REQUIRED_RISK_LEVELS:
            question = f"「{self._get_capability_name(action)}」は取り消せないウル。本当に実行していいウル？"
            return (True, question, options)

        # 複数候補がある場合で差が小さい場合
        # TODO: other_candidatesとの比較

        # 確認不要
        return (False, None, [])

    def _get_capability_name(self, action: str) -> str:
        """機能の表示名を取得"""
        capability = self.capabilities.get(action, {})
        return capability.get("name", action)

    # =========================================================================
    # ステップ5: MVV整合性チェック
    # =========================================================================

    def _check_mvv_alignment(
        self,
        message: str,
        action: str,
    ) -> MVVCheckResult:
        """
        MVV（ミッション・ビジョン・バリュー）との整合性をチェック

        NGパターンの検出、トーンの適切性等を確認。
        """
        result = MVVCheckResult()

        # MVVコンテキストモジュールをロード
        _load_mvv_context()

        if _detect_ng_pattern is None:
            # モジュールがロードできない場合はスキップ
            return result

        try:
            ng_result = _detect_ng_pattern(message)

            if ng_result.detected:
                result.is_aligned = False
                result.ng_pattern_detected = True
                result.ng_pattern_type = ng_result.pattern_type
                result.ng_response_hint = ng_result.response_hint
                result.risk_level = (
                    ng_result.risk_level.value
                    if ng_result.risk_level else None
                )

                # 警告メッセージを追加
                result.warnings.append(
                    f"NGパターン検出: {ng_result.pattern_type}"
                )

        except Exception as e:
            logger.warning(f"Error checking MVV alignment: {e}")

        return result

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def _is_cancel_request(self, message: str) -> bool:
        """キャンセルリクエストかどうかを判定"""
        normalized = message.strip().lower()
        return any(kw in normalized for kw in CANCEL_KEYWORDS)

    def _build_reasoning(
        self,
        candidate: ActionCandidate,
        understanding: UnderstandingResult,
        mvv_result: MVVCheckResult,
    ) -> str:
        """判断理由を構築"""
        parts = [
            f"Selected '{candidate.action}' with score {candidate.score:.2f}.",
            f"Intent: {understanding.intent} (confidence: {understanding.intent_confidence:.2f})",
        ]

        if mvv_result.ng_pattern_detected:
            parts.append(f"Warning: NG pattern '{mvv_result.ng_pattern_type}' detected")

        return " ".join(parts)

    def _elapsed_ms(self, start_time: float) -> int:
        """経過時間をミリ秒で取得"""
        return int((time.time() - start_time) * 1000)

    # =========================================================================
    # LLM使用時の判断（オプション）
    # =========================================================================

    async def _decide_with_llm(
        self,
        understanding: UnderstandingResult,
        context: BrainContext,
    ) -> Optional[DecisionResult]:
        """
        LLMを使用して判断を行う（オプション機能）

        ルールベースで判断が難しい場合のフォールバックとして使用。
        """
        if not self.get_ai_response:
            return None

        try:
            # 機能カタログをJSON化
            capabilities_json = json.dumps(
                {k: {
                    "name": v.get("name", k),
                    "description": v.get("description", ""),
                    "category": v.get("category", ""),
                } for k, v in self.enabled_capabilities.items()},
                ensure_ascii=False,
                indent=2,
            )

            prompt = DECISION_PROMPT.format(
                capabilities_json=capabilities_json,
                intent=understanding.intent,
                confidence=understanding.intent_confidence,
                entities=json.dumps(understanding.entities, ensure_ascii=False),
                raw_message=understanding.raw_message,
                context=context.to_prompt_context(),
            )

            # LLM呼び出し
            response = self.get_ai_response([], prompt)

            # レスポンスをパース
            # TODO: JSONパースとエラーハンドリング

            return None  # 現状は未実装

        except Exception as e:
            logger.error(f"LLM decision error: {e}")
            return None


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_decision(
    capabilities: Optional[Dict[str, Dict]] = None,
    get_ai_response_func: Optional[Callable] = None,
    org_id: str = "",
    use_llm: bool = False,
) -> BrainDecision:
    """
    BrainDecisionのインスタンスを作成

    使用例:
        decision = create_decision(
            capabilities=SYSTEM_CAPABILITIES,
            org_id="org_soulsyncs",
        )
    """
    return BrainDecision(
        capabilities=capabilities,
        get_ai_response_func=get_ai_response_func,
        org_id=org_id,
        use_llm=use_llm,
    )
