"""
Ultimate Brain Architecture - Phase 1: 思考連鎖 (Chain-of-Thought)

設計書: docs/19_ultimate_brain_architecture.md
セクション: 3.1 思考連鎖

複雑な入力を段階的に分析し、正確な判断を行う。
「目標設定として繋がってる？」のような曖昧な入力も正しく解釈できる。
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .constants import JST


# ============================================================================
# Enum定義
# ============================================================================

class InputType(Enum):
    """入力の種類"""
    QUESTION = "question"           # 質問（？で終わる、情報を求める）
    REQUEST = "request"             # 依頼（〜して、〜したい）
    REPORT = "report"               # 報告（〜した、〜です）
    CONFIRMATION = "confirmation"   # 確認（〜でいい？、〜であってる？）
    EMOTION = "emotion"             # 感情表出（嬉しい、困った、など）
    CHAT = "chat"                   # 雑談（挨拶、世間話）
    COMMAND = "command"             # コマンド（承認、却下、など）
    UNKNOWN = "unknown"             # 不明


class StructureElement(Enum):
    """文構造要素"""
    SUBJECT = "subject"             # 主語
    PREDICATE = "predicate"         # 述語
    OBJECT = "object"               # 目的語
    MODIFIER = "modifier"           # 修飾語
    INTERROGATIVE = "interrogative" # 疑問詞
    PARTICLE = "particle"           # 助詞


# ============================================================================
# データクラス
# ============================================================================

@dataclass
class ThoughtStep:
    """思考の1ステップ"""
    step_number: int
    step_name: str
    reasoning: str
    conclusion: Any
    confidence: float = 1.0


@dataclass
class PossibleIntent:
    """推論された意図の候補"""
    intent: str
    probability: float
    reasoning: str
    keywords_matched: List[str] = field(default_factory=list)


@dataclass
class StructureAnalysis:
    """文構造分析結果"""
    elements: Dict[str, List[str]]
    sentence_type: str  # declarative, interrogative, imperative, exclamatory
    is_negative: bool
    has_conditional: bool
    main_topic: Optional[str] = None


@dataclass
class ThoughtChain:
    """思考連鎖の結果"""
    steps: List[ThoughtStep]
    input_type: InputType
    structure: StructureAnalysis
    possible_intents: List[PossibleIntent]
    final_intent: str
    confidence: float
    reasoning_summary: str
    analysis_time_ms: float


# ============================================================================
# 定数
# ============================================================================

# 入力タイプ判定キーワード
INPUT_TYPE_PATTERNS = {
    InputType.QUESTION: {
        "endings": ["？", "?", "かな", "だろう", "でしょうか", "ますか", "ですか"],
        "keywords": ["何", "どう", "いつ", "どこ", "誰", "なぜ", "どれ", "どの", "いくつ", "いくら"],
        "patterns": [r"教えて", r"知りたい", r"分から", r"わから"],
    },
    InputType.REQUEST: {
        "endings": ["して", "したい", "してほしい", "お願い", "ください", "頼む", "頼みたい"],
        "keywords": ["作成", "登録", "追加", "削除", "変更", "更新", "開始", "始め"],
        "patterns": [r"〜を.*して", r"〜に.*して"],
    },
    InputType.REPORT: {
        "endings": ["した", "しました", "です", "ます", "だった", "でした", "終わった", "完了"],
        "keywords": ["報告", "連絡", "結果"],
        "patterns": [],
    },
    InputType.CONFIRMATION: {
        "endings": ["でいい", "であってる", "で合ってる", "でOK", "でおk", "よね", "だよね"],
        "keywords": ["確認", "チェック"],
        "patterns": [r".*繋がってる[？?]?$", r".*合ってる[？?]?$", r".*いい[？?]?$"],
    },
    InputType.EMOTION: {
        "endings": [],
        "keywords": ["嬉しい", "悲しい", "困った", "辛い", "しんどい", "疲れた", "やる気", "楽しい", "不安"],
        "patterns": [],
    },
    InputType.CHAT: {
        "endings": [],
        "keywords": ["おはよう", "こんにちは", "こんばんは", "お疲れ", "ありがとう", "よろしく"],
        "patterns": [],
    },
    InputType.COMMAND: {
        "endings": [],
        "keywords": [],
        "patterns": [r"^承認\s*\d*$", r"^却下\s*\d*$", r"^キャンセル$", r"^やめる$", r"^終了$"],
    },
}

# 意図推論のためのキーワード（既存のCAPABILITY_KEYWORDSを拡張）
INTENT_KEYWORDS = {
    "goal_setting_start": {
        "positive": ["目標設定したい", "目標を設定", "目標を立て", "目標を決め", "目標設定を始め", "目標登録"],
        "negative": ["繋がってる", "どう思う", "ちゃんと", "について", "確認"],
        "weight": 0.4,
    },
    "goal_progress_report": {
        "positive": ["目標の進捗", "進捗報告", "目標達成", "〇〇%達成"],
        "negative": [],
        "weight": 0.3,
    },
    "task_create": {
        "positive": ["タスク作成", "タスクを追加", "タスク登録", "やることを", "TODO"],
        "negative": ["確認", "どう"],
        "weight": 0.4,
    },
    "task_search": {
        "positive": ["タスク検索", "タスクを探", "自分のタスク", "タスク教えて", "何やればいい"],
        "negative": [],
        "weight": 0.3,
    },
    "task_complete": {
        "positive": ["タスク完了", "終わった", "完了にして", "できた", "済んだ"],
        "negative": [],
        "weight": 0.4,
    },
    "query_knowledge": {
        "positive": ["教えて", "知りたい", "何？", "どういう", "とは"],
        "negative": ["タスク", "目標"],
        "weight": 0.2,
    },
    "save_memory": {
        "positive": ["覚えて", "記憶して", "メモして", "〇〇は〇〇"],
        "negative": [],
        "weight": 0.3,
    },
    "general_conversation": {
        "positive": ["おはよう", "こんにちは", "ありがとう", "お疲れ", "元気？"],
        "negative": [],
        "weight": 0.1,
    },
}


# ============================================================================
# ChainOfThoughtクラス
# ============================================================================

class ChainOfThought:
    """
    思考連鎖エンジン

    複雑な入力を段階的に分析し、正確な判断を導く。
    LLMに頼る前に、ルールベースで可能な限り正確に分析する。
    """

    def __init__(self, llm_client=None):
        """
        初期化

        Args:
            llm_client: LLMクライアント（オプション、複雑な分析用）
        """
        self.llm_client = llm_client

    def analyze(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ThoughtChain:
        """
        入力を段階的に分析

        Args:
            message: ユーザーメッセージ
            context: コンテキスト情報（会話履歴、ユーザー状態など）

        Returns:
            ThoughtChain: 思考連鎖の結果
        """
        start_time = datetime.now(JST)
        steps = []
        context = context or {}

        # Step 1: 入力の分類
        input_type, step1 = self._classify_input(message)
        steps.append(step1)

        # Step 2: 構造分析
        structure, step2 = self._analyze_structure(message)
        steps.append(step2)

        # Step 3: 意図推論
        possible_intents, step3 = self._infer_intents(message, input_type, structure)
        steps.append(step3)

        # Step 4: コンテキスト照合
        final_intent, confidence, step4 = self._match_with_context(
            possible_intents, context, input_type, message
        )
        steps.append(step4)

        # Step 5: 結論導出
        reasoning_summary, step5 = self._derive_conclusion(
            input_type, structure, final_intent, confidence
        )
        steps.append(step5)

        # 分析時間を計算
        end_time = datetime.now(JST)
        analysis_time_ms = (end_time - start_time).total_seconds() * 1000

        return ThoughtChain(
            steps=steps,
            input_type=input_type,
            structure=structure,
            possible_intents=possible_intents,
            final_intent=final_intent,
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            analysis_time_ms=analysis_time_ms,
        )

    def _classify_input(self, message: str) -> Tuple[InputType, ThoughtStep]:
        """
        Step 1: 入力を分類

        Args:
            message: ユーザーメッセージ

        Returns:
            (InputType, ThoughtStep)
        """
        scores = {}
        reasoning_parts = []

        clean_message = message.strip()

        for input_type, patterns_raw in INPUT_TYPE_PATTERNS.items():
            patterns: Dict[str, List[str]] = patterns_raw  # type: ignore[assignment]
            score = 0.0

            # 末尾チェック
            for ending in patterns.get("endings", []):
                if clean_message.endswith(ending):
                    score += 0.4
                    reasoning_parts.append(f"「{ending}」で終わっている → {input_type.value}")

            # キーワードチェック
            for keyword in patterns.get("keywords", []):
                if keyword in clean_message:
                    score += 0.3
                    reasoning_parts.append(f"「{keyword}」を含む → {input_type.value}")

            # パターンチェック
            for pattern in patterns.get("patterns", []):
                if re.search(pattern, clean_message):
                    score += 0.3
                    reasoning_parts.append(f"パターン「{pattern}」にマッチ → {input_type.value}")

            scores[input_type] = score

        # 最高スコアの入力タイプを選択
        if scores:
            best_type = max(scores, key=lambda x: scores.get(x, 0.0))
            best_score = scores[best_type]

            # スコアが低すぎる場合はUNKNOWN
            if best_score < 0.2:
                best_type = InputType.UNKNOWN
        else:
            best_type = InputType.UNKNOWN

        reasoning = "\n".join(reasoning_parts) if reasoning_parts else "特定のパターンにマッチしなかった"

        step = ThoughtStep(
            step_number=1,
            step_name="入力分類",
            reasoning=reasoning,
            conclusion=best_type.value,
            confidence=scores.get(best_type, 0.0),
        )

        return best_type, step

    def _analyze_structure(self, message: str) -> Tuple[StructureAnalysis, ThoughtStep]:
        """
        Step 2: 文構造を分析

        Args:
            message: ユーザーメッセージ

        Returns:
            (StructureAnalysis, ThoughtStep)
        """
        elements: Dict[str, List[str]] = {
            "subject": [],
            "predicate": [],
            "object": [],
            "modifier": [],
            "interrogative": [],
            "particle": [],
        }

        reasoning_parts = []

        # 疑問詞を検出
        interrogatives = ["何", "どう", "いつ", "どこ", "誰", "なぜ", "どれ", "どの", "いくつ", "いくら"]
        for interr in interrogatives:
            if interr in message:
                elements["interrogative"].append(interr)
                reasoning_parts.append(f"疑問詞「{interr}」を検出")

        # 文タイプを判定
        if message.rstrip().endswith(("？", "?")):
            sentence_type = "interrogative"
            reasoning_parts.append("疑問文（？で終わる）")
        elif message.rstrip().endswith(("！", "!")):
            sentence_type = "exclamatory"
            reasoning_parts.append("感嘆文（！で終わる）")
        elif any(message.rstrip().endswith(e) for e in ["して", "ください", "頼む"]):
            sentence_type = "imperative"
            reasoning_parts.append("命令文（〜してで終わる）")
        else:
            sentence_type = "declarative"
            reasoning_parts.append("平叙文")

        # 否定形を検出
        negatives = ["ない", "なく", "ません", "じゃない", "ではない"]
        is_negative = any(neg in message for neg in negatives)
        if is_negative:
            reasoning_parts.append("否定形を含む")

        # 条件形を検出
        conditionals = ["たら", "れば", "なら", "と", "場合"]
        has_conditional = any(cond in message for cond in conditionals)
        if has_conditional:
            reasoning_parts.append("条件形を含む")

        # 主題を抽出（「〇〇として」「〇〇は」「〇〇が」など）
        topic_patterns = [
            r"(.+?)として",
            r"(.+?)は",
            r"(.+?)が",
            r"(.+?)について",
        ]
        main_topic = None
        for pattern in topic_patterns:
            match = re.search(pattern, message)
            if match:
                main_topic = match.group(1)
                reasoning_parts.append(f"主題: 「{main_topic}」")
                break

        structure = StructureAnalysis(
            elements=elements,
            sentence_type=sentence_type,
            is_negative=is_negative,
            has_conditional=has_conditional,
            main_topic=main_topic,
        )

        step = ThoughtStep(
            step_number=2,
            step_name="構造分析",
            reasoning="\n".join(reasoning_parts) if reasoning_parts else "基本的な文構造",
            conclusion={
                "sentence_type": sentence_type,
                "is_negative": is_negative,
                "has_conditional": has_conditional,
                "main_topic": main_topic,
            },
            confidence=0.8,
        )

        return structure, step

    def _infer_intents(
        self,
        message: str,
        input_type: InputType,
        structure: StructureAnalysis
    ) -> Tuple[List[PossibleIntent], ThoughtStep]:
        """
        Step 3: 意図を推論

        Args:
            message: ユーザーメッセージ
            input_type: 入力タイプ
            structure: 構造分析結果

        Returns:
            (List[PossibleIntent], ThoughtStep)
        """
        intents = []
        reasoning_parts = []

        clean_message = message.lower().strip()

        for intent_name, config_raw in INTENT_KEYWORDS.items():
            config: Dict[str, Any] = config_raw
            score = 0.0
            matched_keywords: List[str] = []
            negative_matched = False

            # ポジティブキーワードのマッチング
            positive_keywords: List[str] = config["positive"]
            weight: float = config["weight"]
            for keyword in positive_keywords:
                if keyword.lower() in clean_message:
                    score += weight
                    matched_keywords.append(keyword)

            # ネガティブキーワードのマッチング（減点）
            negative_keywords: List[str] = config["negative"]
            for keyword in negative_keywords:
                if keyword.lower() in clean_message:
                    score -= weight * 1.5  # 強めの減点
                    negative_matched = True
                    reasoning_parts.append(
                        f"「{keyword}」検出 → {intent_name}の可能性を下げる"
                    )

            # 入力タイプによる調整
            if intent_name.endswith("_start") and input_type == InputType.QUESTION:
                # 質問文で「開始」系の意図は確率を下げる
                score -= 0.2
                reasoning_parts.append(f"質問文なので{intent_name}の可能性を下げる")

            if score > 0:
                intents.append(PossibleIntent(
                    intent=intent_name,
                    probability=min(score, 1.0),
                    reasoning=f"キーワード: {', '.join(matched_keywords)}" if matched_keywords else "低確率",
                    keywords_matched=matched_keywords,
                ))

        # スコアで降順ソート
        intents.sort(key=lambda x: x.probability, reverse=True)

        # 質問文の場合、一般会話/ナレッジ検索の可能性を考慮
        if input_type == InputType.QUESTION and not intents:
            intents.append(PossibleIntent(
                intent="query_knowledge",
                probability=0.5,
                reasoning="質問文だが特定の意図が検出されなかった",
                keywords_matched=[],
            ))

        if input_type == InputType.CONFIRMATION:
            # 確認の場合は「確認応答」が最も可能性が高い
            intents.insert(0, PossibleIntent(
                intent="confirmation_response",
                probability=0.7,
                reasoning="確認を求める文だった",
                keywords_matched=[],
            ))

        step = ThoughtStep(
            step_number=3,
            step_name="意図推論",
            reasoning="\n".join(reasoning_parts) if reasoning_parts else "キーワードマッチングによる推論",
            conclusion=[{
                "intent": i.intent,
                "probability": i.probability,
                "keywords": i.keywords_matched,
            } for i in intents[:5]],  # 上位5件
            confidence=intents[0].probability if intents else 0.0,
        )

        return intents, step

    def _match_with_context(
        self,
        possible_intents: List[PossibleIntent],
        context: Dict[str, Any],
        input_type: InputType,
        message: str
    ) -> Tuple[str, float, ThoughtStep]:
        """
        Step 4: コンテキストと照合

        Args:
            possible_intents: 意図候補リスト
            context: コンテキスト情報
            input_type: 入力タイプ
            message: 元のメッセージ

        Returns:
            (final_intent, confidence, ThoughtStep)
        """
        reasoning_parts = []

        # コンテキストから状態を取得
        current_state = context.get("state", "normal")
        last_action = context.get("last_action")
        conversation_topic = context.get("topic")

        # 状態による調整
        if current_state == "goal_setting":
            # 目標設定セッション中
            if input_type == InputType.COMMAND:
                # 終了コマンド
                final_intent = "goal_setting_exit"
                confidence = 0.9
                reasoning_parts.append("目標設定セッション中のコマンド → 終了")
            else:
                final_intent = "goal_setting_response"
                confidence = 0.85
                reasoning_parts.append("目標設定セッション中 → セッション継続")

            step = ThoughtStep(
                step_number=4,
                step_name="コンテキスト照合",
                reasoning="\n".join(reasoning_parts),
                conclusion={"intent": final_intent, "state_adjusted": True},
                confidence=confidence,
            )
            return final_intent, confidence, step

        # 通常状態での照合
        if possible_intents:
            top_intent = possible_intents[0]

            # 確認文の特別処理
            if input_type in [InputType.QUESTION, InputType.CONFIRMATION]:
                # 質問/確認文で「〜開始」系の意図がトップの場合は慎重に
                if top_intent.intent.endswith("_start"):
                    # 2位があれば比較
                    if len(possible_intents) > 1:
                        second_intent = possible_intents[1]
                        # 差が小さければ質問として処理
                        if top_intent.probability - second_intent.probability < 0.3:
                            reasoning_parts.append(
                                f"質問文で{top_intent.intent}と{second_intent.intent}が競合 → 質問として処理"
                            )
                            final_intent = "query_knowledge"
                            confidence = 0.6
                        else:
                            final_intent = top_intent.intent
                            confidence = top_intent.probability * 0.8  # 少し下げる
                            reasoning_parts.append(
                                f"質問文だが{top_intent.intent}の確率が高い"
                            )
                    else:
                        # 「繋がってる？」のような確認は質問として処理
                        if "繋がってる" in message or "合ってる" in message:
                            final_intent = "confirmation_response"
                            confidence = 0.8
                            reasoning_parts.append("確認を求めている → 確認応答")
                        else:
                            final_intent = top_intent.intent
                            confidence = top_intent.probability * 0.7
                else:
                    final_intent = top_intent.intent
                    confidence = top_intent.probability
            else:
                final_intent = top_intent.intent
                confidence = top_intent.probability
                reasoning_parts.append(f"最も確率の高い意図: {final_intent}")
        else:
            final_intent = "general_conversation"
            confidence = 0.5
            reasoning_parts.append("特定の意図が検出されなかった → 一般会話")

        step = ThoughtStep(
            step_number=4,
            step_name="コンテキスト照合",
            reasoning="\n".join(reasoning_parts) if reasoning_parts else "コンテキストによる調整なし",
            conclusion={
                "intent": final_intent,
                "current_state": current_state,
                "adjusted": len(reasoning_parts) > 0,
            },
            confidence=confidence,
        )

        return final_intent, confidence, step

    def _derive_conclusion(
        self,
        input_type: InputType,
        structure: StructureAnalysis,
        final_intent: str,
        confidence: float
    ) -> Tuple[str, ThoughtStep]:
        """
        Step 5: 結論を導出

        Args:
            input_type: 入力タイプ
            structure: 構造分析
            final_intent: 最終意図
            confidence: 確信度

        Returns:
            (reasoning_summary, ThoughtStep)
        """
        summary_parts = []

        # 入力タイプに基づく要約
        type_descriptions = {
            InputType.QUESTION: "質問",
            InputType.REQUEST: "依頼",
            InputType.REPORT: "報告",
            InputType.CONFIRMATION: "確認",
            InputType.EMOTION: "感情表出",
            InputType.CHAT: "雑談",
            InputType.COMMAND: "コマンド",
            InputType.UNKNOWN: "不明",
        }
        summary_parts.append(f"入力タイプ: {type_descriptions.get(input_type, '不明')}")

        # 構造に基づく要約
        if structure.sentence_type == "interrogative":
            summary_parts.append("文タイプ: 疑問文（情報を求めている）")
        elif structure.sentence_type == "imperative":
            summary_parts.append("文タイプ: 命令文（アクションを求めている）")

        if structure.main_topic:
            summary_parts.append(f"主題: {structure.main_topic}")

        # 意図に基づく要約
        intent_descriptions = {
            "goal_setting_start": "目標設定を開始する",
            "goal_setting_response": "目標設定セッションを継続する",
            "goal_setting_exit": "目標設定セッションを終了する",
            "task_create": "タスクを作成する",
            "task_search": "タスクを検索する",
            "task_complete": "タスクを完了する",
            "query_knowledge": "情報を提供する",
            "save_memory": "情報を記憶する",
            "general_conversation": "会話を続ける",
            "confirmation_response": "確認に応答する",
        }
        summary_parts.append(f"判断されたアクション: {intent_descriptions.get(final_intent, final_intent)}")

        # 確信度
        if confidence >= 0.8:
            confidence_desc = "高確信度"
        elif confidence >= 0.6:
            confidence_desc = "中確信度"
        else:
            confidence_desc = "低確信度（確認が必要かも）"
        summary_parts.append(f"確信度: {confidence:.0%} ({confidence_desc})")

        reasoning_summary = "\n".join(summary_parts)

        step = ThoughtStep(
            step_number=5,
            step_name="結論導出",
            reasoning=reasoning_summary,
            conclusion={
                "final_intent": final_intent,
                "confidence": confidence,
                "needs_confirmation": confidence < 0.7,
            },
            confidence=confidence,
        )

        return reasoning_summary, step


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_chain_of_thought(llm_client=None) -> ChainOfThought:
    """
    ChainOfThoughtインスタンスを作成

    Args:
        llm_client: LLMクライアント（オプション）

    Returns:
        ChainOfThought インスタンス
    """
    return ChainOfThought(llm_client=llm_client)
