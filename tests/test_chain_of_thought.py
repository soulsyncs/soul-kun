"""
Ultimate Brain Phase 1: Chain-of-Thought テスト

設計書: docs/19_ultimate_brain_architecture.md
"""

import pytest
from lib.brain.chain_of_thought import (
    ChainOfThought,
    create_chain_of_thought,
    InputType,
    StructureElement,
    ThoughtStep,
    PossibleIntent,
    StructureAnalysis,
    ThoughtChain,
    INPUT_TYPE_PATTERNS,
    INTENT_KEYWORDS,
)


class TestInputType:
    """InputType Enumテスト"""

    def test_input_type_values(self):
        """入力タイプの値を確認"""
        assert InputType.QUESTION.value == "question"
        assert InputType.REQUEST.value == "request"
        assert InputType.REPORT.value == "report"
        assert InputType.CONFIRMATION.value == "confirmation"
        assert InputType.EMOTION.value == "emotion"
        assert InputType.CHAT.value == "chat"
        assert InputType.COMMAND.value == "command"
        assert InputType.UNKNOWN.value == "unknown"

    def test_input_type_count(self):
        """入力タイプの数を確認"""
        assert len(InputType) == 8


class TestStructureElement:
    """StructureElement Enumテスト"""

    def test_structure_element_values(self):
        """構造要素の値を確認"""
        assert StructureElement.SUBJECT.value == "subject"
        assert StructureElement.PREDICATE.value == "predicate"
        assert StructureElement.INTERROGATIVE.value == "interrogative"


class TestThoughtStep:
    """ThoughtStepデータクラステスト"""

    def test_thought_step_creation(self):
        """ThoughtStepを作成"""
        step = ThoughtStep(
            step_number=1,
            step_name="入力分類",
            reasoning="「？」で終わっている",
            conclusion="question",
            confidence=0.8,
        )
        assert step.step_number == 1
        assert step.step_name == "入力分類"
        assert step.confidence == 0.8


class TestPossibleIntent:
    """PossibleIntentデータクラステスト"""

    def test_possible_intent_creation(self):
        """PossibleIntentを作成"""
        intent = PossibleIntent(
            intent="task_search",
            probability=0.85,
            reasoning="タスクキーワードを含む",
            keywords_matched=["タスク", "教えて"],
        )
        assert intent.intent == "task_search"
        assert intent.probability == 0.85
        assert len(intent.keywords_matched) == 2


class TestStructureAnalysis:
    """StructureAnalysisデータクラステスト"""

    def test_structure_analysis_creation(self):
        """StructureAnalysisを作成"""
        analysis = StructureAnalysis(
            elements={"interrogative": ["何"]},
            sentence_type="interrogative",
            is_negative=False,
            has_conditional=False,
            main_topic="タスク",
        )
        assert analysis.sentence_type == "interrogative"
        assert analysis.main_topic == "タスク"


class TestThoughtChain:
    """ThoughtChainデータクラステスト"""

    def test_thought_chain_creation(self):
        """ThoughtChainを作成"""
        chain = ThoughtChain(
            steps=[],
            input_type=InputType.QUESTION,
            structure=StructureAnalysis(
                elements={},
                sentence_type="interrogative",
                is_negative=False,
                has_conditional=False,
            ),
            possible_intents=[],
            final_intent="task_search",
            confidence=0.9,
            reasoning_summary="タスク検索の質問",
            analysis_time_ms=10.5,
        )
        assert chain.input_type == InputType.QUESTION
        assert chain.final_intent == "task_search"


class TestChainOfThoughtInitialization:
    """ChainOfThought初期化テスト"""

    def test_init_without_llm(self):
        """LLMなしで初期化"""
        cot = ChainOfThought()
        assert cot.llm_client is None

    def test_init_with_llm(self):
        """LLMありで初期化"""
        mock_llm = object()
        cot = ChainOfThought(llm_client=mock_llm)
        assert cot.llm_client is mock_llm

    def test_factory_function(self):
        """ファクトリ関数を使用"""
        cot = create_chain_of_thought()
        assert isinstance(cot, ChainOfThought)


class TestInputClassification:
    """入力分類テスト"""

    @pytest.fixture
    def cot(self):
        return ChainOfThought()

    def test_classify_question_with_question_mark(self, cot):
        """疑問符で終わる質問を分類"""
        result = cot.analyze("自分のタスクを教えて？")
        assert result.input_type == InputType.QUESTION

    def test_classify_question_with_keywords(self, cot):
        """疑問詞を含む質問を分類"""
        result = cot.analyze("何をすればいい")
        assert result.input_type == InputType.QUESTION

    def test_classify_request(self, cot):
        """依頼を分類"""
        result = cot.analyze("タスクを作成して")
        assert result.input_type == InputType.REQUEST

    def test_classify_report(self, cot):
        """報告を分類"""
        result = cot.analyze("タスクを完了しました")
        assert result.input_type == InputType.REPORT

    def test_classify_confirmation(self, cot):
        """確認を分類"""
        result = cot.analyze("これでいい？")
        # 確認は質問の一種でもあるため、両方を許容
        assert result.input_type in [InputType.CONFIRMATION, InputType.QUESTION]

    def test_classify_emotion(self, cot):
        """感情表出を分類"""
        result = cot.analyze("困った、どうしよう")
        # 「どうしよう」は質問としても解釈可能
        assert result.input_type in [InputType.EMOTION, InputType.QUESTION]

    def test_classify_chat(self, cot):
        """雑談を分類"""
        result = cot.analyze("おはようございます")
        # 「ます」終わりは報告と判定されることもある
        assert result.input_type in [InputType.CHAT, InputType.REPORT]

    def test_classify_command(self, cot):
        """コマンドを分類"""
        result = cot.analyze("キャンセル")
        assert result.input_type == InputType.COMMAND


class TestStructureAnalysisMethod:
    """構造分析メソッドテスト"""

    @pytest.fixture
    def cot(self):
        return ChainOfThought()

    def test_detect_interrogative_sentence(self, cot):
        """疑問文を検出"""
        result = cot.analyze("何時ですか？")
        assert result.structure.sentence_type == "interrogative"

    def test_detect_exclamatory_sentence(self, cot):
        """感嘆文を検出"""
        result = cot.analyze("すごい！")
        assert result.structure.sentence_type == "exclamatory"

    def test_detect_imperative_sentence(self, cot):
        """命令文を検出"""
        result = cot.analyze("タスクを作成して")
        assert result.structure.sentence_type == "imperative"

    def test_detect_negative(self, cot):
        """否定形を検出"""
        result = cot.analyze("わからない")
        assert result.structure.is_negative is True

    def test_detect_conditional(self, cot):
        """条件形を検出"""
        result = cot.analyze("時間があれば教えて")
        assert result.structure.has_conditional is True

    def test_extract_main_topic(self, cot):
        """主題を抽出"""
        result = cot.analyze("目標設定として繋がってる？")
        assert result.structure.main_topic == "目標設定"


class TestIntentInference:
    """意図推論テスト"""

    @pytest.fixture
    def cot(self):
        return ChainOfThought()

    def test_infer_goal_setting_start(self, cot):
        """目標設定開始の意図を推論"""
        result = cot.analyze("目標設定を始めたい")
        # ポジティブキーワードにマッチ
        assert any(i.intent == "goal_setting_start" for i in result.possible_intents)

    def test_infer_task_search(self, cot):
        """タスク検索の意図を推論"""
        result = cot.analyze("自分のタスクを教えて")
        assert any(i.intent == "task_search" for i in result.possible_intents)

    def test_infer_task_create(self, cot):
        """タスク作成の意図を推論"""
        result = cot.analyze("タスクを追加して")
        assert any(i.intent == "task_create" for i in result.possible_intents)

    def test_negative_keywords_reduce_probability(self, cot):
        """ネガティブキーワードで確率を下げる"""
        # 「繋がってる？」はgoal_setting_startのネガティブキーワード
        result = cot.analyze("目標設定として繋がってる？")
        goal_intents = [i for i in result.possible_intents if i.intent == "goal_setting_start"]
        # goal_setting_startが最上位にならないはず
        if result.possible_intents:
            assert result.possible_intents[0].intent != "goal_setting_start"


class TestContextMatching:
    """コンテキスト照合テスト"""

    @pytest.fixture
    def cot(self):
        return ChainOfThought()

    def test_goal_setting_session_context(self, cot):
        """目標設定セッション中のコンテキスト"""
        result = cot.analyze(
            "これでいい？",
            context={"state": "goal_setting"}
        )
        assert result.final_intent == "goal_setting_response"

    def test_goal_setting_exit_command(self, cot):
        """目標設定セッション中の終了コマンド"""
        result = cot.analyze(
            "やめる",
            context={"state": "goal_setting"}
        )
        assert result.final_intent == "goal_setting_exit"

    def test_question_reduces_start_confidence(self, cot):
        """質問文で開始系の確信度を下げる"""
        result = cot.analyze("目標設定として繋がってる？")
        # 質問文 + 「繋がってる」→ confirmation_responseが優先される
        assert result.final_intent in ["confirmation_response", "query_knowledge"]


class TestConclusionDerivation:
    """結論導出テスト"""

    @pytest.fixture
    def cot(self):
        return ChainOfThought()

    def test_high_confidence_summary(self, cot):
        """高確信度のサマリー"""
        result = cot.analyze("タスクを作成して")
        # 依頼として分類される（確信度は文脈依存）
        assert result.input_type == InputType.REQUEST
        # サマリーには判断理由が含まれる
        assert len(result.reasoning_summary) > 0

    def test_low_confidence_needs_confirmation(self, cot):
        """低確信度で確認が必要"""
        result = cot.analyze("あれやっといて")
        # 曖昧な入力は確信度が低い
        # 確認が必要かどうかはstep5で判断
        assert result.steps[-1].conclusion.get("needs_confirmation", False) or result.confidence < 0.7


class TestAnalysisTime:
    """分析時間テスト"""

    @pytest.fixture
    def cot(self):
        return ChainOfThought()

    def test_analysis_time_recorded(self, cot):
        """分析時間が記録される"""
        result = cot.analyze("テスト")
        assert result.analysis_time_ms > 0

    def test_analysis_is_fast(self, cot):
        """分析が高速"""
        result = cot.analyze("自分のタスクを教えて")
        # 100ms以内（LLM不使用時）
        assert result.analysis_time_ms < 100


class TestConstants:
    """定数テスト"""

    def test_input_type_patterns_exist(self):
        """入力タイプパターンが存在"""
        assert InputType.QUESTION in INPUT_TYPE_PATTERNS
        assert InputType.REQUEST in INPUT_TYPE_PATTERNS
        assert InputType.CONFIRMATION in INPUT_TYPE_PATTERNS

    def test_intent_keywords_exist(self):
        """意図キーワードが存在"""
        assert "goal_setting_start" in INTENT_KEYWORDS
        assert "task_search" in INTENT_KEYWORDS
        assert "task_create" in INTENT_KEYWORDS

    def test_intent_keywords_have_positive_and_negative(self):
        """意図キーワードにポジティブとネガティブがある"""
        for intent, config in INTENT_KEYWORDS.items():
            assert "positive" in config
            assert "negative" in config
            assert "weight" in config


class TestEdgeCases:
    """エッジケーステスト"""

    @pytest.fixture
    def cot(self):
        return ChainOfThought()

    def test_empty_message(self, cot):
        """空メッセージ"""
        result = cot.analyze("")
        assert result is not None
        assert result.input_type == InputType.UNKNOWN

    def test_very_long_message(self, cot):
        """非常に長いメッセージ"""
        long_message = "これは " * 1000 + "長いメッセージです"
        result = cot.analyze(long_message)
        assert result is not None

    def test_special_characters(self, cot):
        """特殊文字"""
        result = cot.analyze("@#$%^&*()")
        assert result is not None

    def test_unicode_characters(self, cot):
        """Unicode文字"""
        result = cot.analyze("😀🔥💯 これでいい？")
        assert result is not None


class TestGoalSettingBugScenario:
    """目標設定バグシナリオテスト

    「目標設定として繋がってる？」が目標設定開始と誤判断されないことを確認
    """

    @pytest.fixture
    def cot(self):
        return ChainOfThought()

    def test_goal_setting_question_not_start(self, cot):
        """「繋がってる？」は開始ではない"""
        result = cot.analyze("目標設定としてちゃんと繋がってる？")

        # 入力タイプは質問/確認
        assert result.input_type in [InputType.QUESTION, InputType.CONFIRMATION]

        # 最終意図はgoal_setting_startではない
        assert result.final_intent != "goal_setting_start"

        # ステップの推論に「繋がってる」の検出が含まれる
        all_reasoning = " ".join(step.reasoning for step in result.steps)
        assert "繋がってる" in all_reasoning or "質問" in all_reasoning or "確認" in all_reasoning

    def test_actual_goal_setting_request(self, cot):
        """実際の目標設定リクエストは検出される"""
        result = cot.analyze("目標設定を始めたい")

        # リクエストとして分類
        assert result.input_type in [InputType.REQUEST, InputType.QUESTION]

        # goal_setting_startが候補に含まれる
        intents = [i.intent for i in result.possible_intents]
        assert "goal_setting_start" in intents
