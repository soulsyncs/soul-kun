# tests/test_llm_brain_core.py
"""
LLM Brain - Core のテスト

Claude Opus 4.5を使用したFunction Calling方式の脳の機能をテストします。

設計書: docs/25_llm_native_brain_architecture.md セクション5.2

テスト対象:
- ToolCall, ConfidenceScores, LLMBrainResult データクラス
- LLMBrain 初期化
- LLMBrain.process() メソッド
- 確信度抽出
- System Prompt構築
- エラーハンドリング
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
import os
import json

from lib.brain.llm_brain import (
    ToolCall,
    ConfidenceScores,
    LLMBrainResult,
    LLMBrain,
    APIProvider,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_MODEL_OPENROUTER,
    DEFAULT_MODEL_ANTHROPIC,
    create_llm_brain,
    create_llm_brain_auto,
    _get_openrouter_api_key,
    _get_anthropic_api_key,
)
from lib.brain.context_builder import LLMContext


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def sample_context():
    """テスト用のLLMContext"""
    return LLMContext(
        user_id="user_001",
        user_name="テストユーザー",
        user_role="member",
        organization_id="org_test",
        room_id="room_123",
        current_datetime=datetime.now(),
    )


@pytest.fixture
def sample_tools():
    """テスト用のToolリスト（Anthropic形式）"""
    return [
        {
            "name": "chatwork_task_create",
            "description": "タスクを作成する",
            "input_schema": {
                "type": "object",
                "properties": {
                    "body": {"type": "string", "description": "タスク内容"},
                    "room_id": {"type": "string", "description": "ルームID"},
                },
                "required": ["body"],
            },
        },
        {
            "name": "chatwork_task_search",
            "description": "タスクを検索する",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "検索クエリ"},
                },
                "required": [],
            },
        },
    ]


@pytest.fixture
def mock_openrouter_response():
    """モックのOpenRouter APIレスポンス（OpenAI形式）"""
    return {
        "choices": [
            {
                "message": {
                    "content": """【思考過程】
- 意図理解: ユーザーはタスクを追加したいと考えられる
- 根拠: 「タスク追加して」というキーワードから判断
- Tool選択: chatwork_task_createを使用する
- 確信度: 90%

【応答】
タスクを追加するウル！""",
                    "tool_calls": [
                        {
                            "id": "tu_001",
                            "type": "function",
                            "function": {
                                "name": "chatwork_task_create",
                                "arguments": json.dumps({"body": "テストタスク", "room_id": "123"}),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
        },
    }


@pytest.fixture
def mock_anthropic_response():
    """モックのAnthropic APIレスポンス"""
    return {
        "content": [
            {
                "type": "text",
                "text": """【思考過程】
- 意図理解: ユーザーはタスクを追加したいと考えられる
- 根拠: 「タスク追加して」というキーワードから判断
- Tool選択: chatwork_task_createを使用する
- 確信度: 90%

【応答】
タスクを追加するウル！""",
            },
            {
                "type": "tool_use",
                "id": "tu_001",
                "name": "chatwork_task_create",
                "input": {"body": "テストタスク", "room_id": "123"},
            },
        ],
        "stop_reason": "tool_use",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
        },
    }


# =============================================================================
# ToolCall データクラステスト
# =============================================================================


class TestToolCall:
    """ToolCallデータクラスのテスト"""

    def test_init(self):
        """初期化できること"""
        tc = ToolCall(
            tool_name="chatwork_task_create",
            parameters={"body": "テスト"},
            reasoning="タスク作成",
            tool_use_id="tu_001",
        )
        assert tc.tool_name == "chatwork_task_create"
        assert tc.parameters == {"body": "テスト"}
        assert tc.reasoning == "タスク作成"
        assert tc.tool_use_id == "tu_001"

    def test_init_defaults(self):
        """デフォルト値で初期化できること"""
        tc = ToolCall(
            tool_name="test",
            parameters={},
        )
        assert tc.reasoning == ""
        assert tc.tool_use_id == ""

    def test_to_dict(self):
        """to_dictが正しい形式を返すこと"""
        tc = ToolCall(
            tool_name="chatwork_task_create",
            parameters={"body": "テスト"},
            reasoning="タスク作成",
            tool_use_id="tu_001",
        )
        d = tc.to_dict()
        assert d["tool_name"] == "chatwork_task_create"
        assert d["parameters"] == {"body": "テスト"}
        assert d["reasoning"] == "タスク作成"
        assert d["tool_use_id"] == "tu_001"


# =============================================================================
# ConfidenceScores データクラステスト
# =============================================================================


class TestConfidenceScores:
    """ConfidenceScoresデータクラスのテスト"""

    def test_init(self):
        """初期化できること"""
        cs = ConfidenceScores(
            overall=0.85,
            intent=0.90,
            parameters=0.80,
        )
        assert cs.overall == 0.85
        assert cs.intent == 0.90
        assert cs.parameters == 0.80

    def test_init_defaults(self):
        """デフォルト値で初期化できること"""
        cs = ConfidenceScores()
        assert cs.overall == 0.8
        assert cs.intent == 0.8
        assert cs.parameters == 0.8

    def test_to_dict(self):
        """to_dictが正しい形式を返すこと"""
        cs = ConfidenceScores(overall=0.85, intent=0.90, parameters=0.80)
        d = cs.to_dict()
        assert d["overall"] == 0.85
        assert d["intent"] == 0.90
        assert d["parameters"] == 0.80


# =============================================================================
# LLMBrainResult データクラステスト
# =============================================================================


class TestLLMBrainResult:
    """LLMBrainResultデータクラスのテスト"""

    def test_init_text_response(self):
        """テキスト応答で初期化できること"""
        result = LLMBrainResult(
            output_type="text_response",
            text_response="こんにちは",
            reasoning="挨拶に応答",
            confidence=ConfidenceScores(overall=0.9),
        )
        assert result.output_type == "text_response"
        assert result.text_response == "こんにちは"
        assert result.tool_calls is None

    def test_init_tool_call(self):
        """Tool呼び出しで初期化できること"""
        tc = ToolCall(tool_name="test", parameters={})
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[tc],
            reasoning="ツール使用",
            confidence=ConfidenceScores(overall=0.85),
        )
        assert result.output_type == "tool_call"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "test"

    def test_to_dict(self):
        """to_dictが正しい形式を返すこと"""
        tc = ToolCall(tool_name="test", parameters={"a": 1})
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[tc],
            reasoning="テスト",
            confidence=ConfidenceScores(overall=0.8),
            api_provider="openrouter",
        )
        d = result.to_dict()
        assert d["output_type"] == "tool_call"
        assert d["reasoning"] == "テスト"
        assert d["api_provider"] == "openrouter"
        assert "confidence" in d


# =============================================================================
# DEFAULT_SYSTEM_PROMPT テスト
# =============================================================================


class TestDefaultSystemPrompt:
    """DEFAULT_SYSTEM_PROMPTのテスト"""

    def test_not_empty(self):
        """空でないこと"""
        assert len(DEFAULT_SYSTEM_PROMPT) > 0

    def test_contains_soulkun_identity(self):
        """ソウルくんのアイデンティティが含まれること"""
        assert "ソウルくん" in DEFAULT_SYSTEM_PROMPT

    def test_contains_mission(self):
        """ミッションが含まれること"""
        assert "ミッション" in DEFAULT_SYSTEM_PROMPT or "テクノロジー" in DEFAULT_SYSTEM_PROMPT

    def test_contains_role(self):
        """役割が含まれること"""
        assert "役割" in DEFAULT_SYSTEM_PROMPT

    def test_contains_speaking_rules(self):
        """話し方のルールが含まれること"""
        assert "ウル" in DEFAULT_SYSTEM_PROMPT


# =============================================================================
# APIキー取得関数テスト
# =============================================================================


class TestApiKeyFunctions:
    """APIキー取得関数のテスト"""

    def test_get_openrouter_api_key_from_env(self):
        """環境変数からOpenRouter APIキーを取得できること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            key = _get_openrouter_api_key()
            assert key == "sk-or-test-key"
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    def test_get_openrouter_api_key_returns_none_when_not_set(self):
        """APIキーが設定されていない場合Noneを返すこと"""
        # 環境変数をクリア
        original = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            # Secret Managerもモック（失敗させる）
            # get_secret_cached は lib.secrets からインポートされるため、そちらをパッチ
            with patch("lib.secrets.get_secret_cached", side_effect=Exception("Not available")):
                key = _get_openrouter_api_key()
                # 環境変数もSecret Managerもない場合はNone
                assert key is None
        finally:
            if original:
                os.environ["OPENROUTER_API_KEY"] = original

    def test_get_anthropic_api_key_from_env(self):
        """環境変数からAnthropic APIキーを取得できること"""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
        try:
            key = _get_anthropic_api_key()
            assert key == "sk-ant-test-key"
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_get_anthropic_api_key_returns_none_when_not_set(self):
        """APIキーが設定されていない場合Noneを返すこと"""
        original = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            key = _get_anthropic_api_key()
            assert key is None
        finally:
            if original:
                os.environ["ANTHROPIC_API_KEY"] = original


# =============================================================================
# LLMBrain 初期化テスト
# =============================================================================


class TestLLMBrainInit:
    """LLMBrain初期化のテスト"""

    def test_init_without_api_key_raises_error(self):
        """APIキーなしで初期化するとエラーになること"""
        # 環境変数をクリア
        original_openrouter = os.environ.pop("OPENROUTER_API_KEY", None)
        original_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            # get_secret_cached は lib.secrets からインポートされるため、そちらをパッチ
            with patch("lib.secrets.get_secret_cached", side_effect=Exception("Not available")):
                with pytest.raises(ValueError, match="OpenRouter API key is required"):
                    LLMBrain(use_openrouter=True)
        finally:
            if original_openrouter:
                os.environ["OPENROUTER_API_KEY"] = original_openrouter
            if original_anthropic:
                os.environ["ANTHROPIC_API_KEY"] = original_anthropic

    def test_init_with_openrouter_api_key(self):
        """OpenRouter APIキー付きで初期化できること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            brain = LLMBrain(use_openrouter=True)
            assert brain is not None
            assert brain.model == DEFAULT_MODEL_OPENROUTER
            assert brain.api_provider == APIProvider.OPENROUTER
            assert brain.use_openrouter is True
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    def test_init_with_anthropic_api_key(self):
        """Anthropic APIキー付きで初期化できること（フォールバック）"""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
        try:
            brain = LLMBrain(use_openrouter=False)
            assert brain is not None
            assert brain.model == DEFAULT_MODEL_ANTHROPIC
            assert brain.api_provider == APIProvider.ANTHROPIC
            assert brain.use_openrouter is False
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_init_with_custom_model(self):
        """カスタムモデルで初期化できること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        os.environ["LLM_BRAIN_MODEL"] = "anthropic/claude-3-opus-20240229"
        try:
            brain = LLMBrain(use_openrouter=True)
            assert brain.model == "anthropic/claude-3-opus-20240229"
        finally:
            del os.environ["OPENROUTER_API_KEY"]
            del os.environ["LLM_BRAIN_MODEL"]

    def test_init_with_explicit_model(self):
        """引数で明示的にモデルを指定できること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            brain = LLMBrain(model="custom/model", use_openrouter=True)
            assert brain.model == "custom/model"
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    def test_thresholds(self):
        """閾値が設定されていること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            brain = LLMBrain(use_openrouter=True)
            assert brain.CONFIDENCE_THRESHOLD_AUTO_EXECUTE == 0.7
            assert brain.CONFIDENCE_THRESHOLD_CONFIRM == 0.5
            assert brain.CONFIDENCE_THRESHOLD_CLARIFY == 0.3
        finally:
            del os.environ["OPENROUTER_API_KEY"]


# =============================================================================
# LLMBrain.process テスト（モック使用）
# =============================================================================


class TestLLMBrainProcess:
    """LLMBrain.processメソッドのテスト（モック使用）"""

    @pytest.mark.asyncio
    async def test_process_returns_llm_brain_result(
        self,
        sample_context,
        sample_tools,
        mock_openrouter_response,
    ):
        """processがLLMBrainResultを返すこと"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            with patch.object(LLMBrain, "_call_openrouter", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = mock_openrouter_response
                brain = LLMBrain(use_openrouter=True)

                result = await brain.process(
                    context=sample_context,
                    message="タスク追加して",
                    tools=sample_tools,
                )

                assert isinstance(result, LLMBrainResult)
                assert result.api_provider == "openrouter"
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    @pytest.mark.asyncio
    async def test_process_extracts_tool_calls(
        self,
        sample_context,
        sample_tools,
        mock_openrouter_response,
    ):
        """processがTool呼び出しを正しく抽出すること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            with patch.object(LLMBrain, "_call_openrouter", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = mock_openrouter_response
                brain = LLMBrain(use_openrouter=True)

                result = await brain.process(
                    context=sample_context,
                    message="タスク追加して",
                    tools=sample_tools,
                )

                assert result.tool_calls is not None
                assert len(result.tool_calls) == 1
                assert result.tool_calls[0].tool_name == "chatwork_task_create"
                assert result.tool_calls[0].parameters == {"body": "テストタスク", "room_id": "123"}
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    @pytest.mark.asyncio
    async def test_process_extracts_reasoning(
        self,
        sample_context,
        sample_tools,
        mock_openrouter_response,
    ):
        """processがreasoningを抽出すること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            with patch.object(LLMBrain, "_call_openrouter", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = mock_openrouter_response
                brain = LLMBrain(use_openrouter=True)

                result = await brain.process(
                    context=sample_context,
                    message="タスク追加して",
                    tools=sample_tools,
                )

                assert result.reasoning is not None
                assert len(result.reasoning) > 0
                assert "タスク" in result.reasoning
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    @pytest.mark.asyncio
    async def test_process_extracts_confidence(
        self,
        sample_context,
        sample_tools,
        mock_openrouter_response,
    ):
        """processが確信度を抽出すること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            with patch.object(LLMBrain, "_call_openrouter", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = mock_openrouter_response
                brain = LLMBrain(use_openrouter=True)

                result = await brain.process(
                    context=sample_context,
                    message="タスク追加して",
                    tools=sample_tools,
                )

                # 「確信度: 90%」が含まれているので0.9
                assert result.confidence.overall == 0.9
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    @pytest.mark.asyncio
    async def test_process_text_only_response(
        self,
        sample_context,
        sample_tools,
    ):
        """テキストのみの応答を処理できること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            mock_response = {
                "choices": [
                    {
                        "message": {
                            "content": "こんにちは！お手伝いできることはありますか？ウル🐺",
                        },
                    }
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            }

            with patch.object(LLMBrain, "_call_openrouter", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = mock_response
                brain = LLMBrain(use_openrouter=True)

                result = await brain.process(
                    context=sample_context,
                    message="こんにちは",
                    tools=sample_tools,
                )

                assert result.output_type == "text_response"
                assert result.text_response is not None
                assert result.tool_calls is None or len(result.tool_calls) == 0
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    @pytest.mark.asyncio
    async def test_process_api_error_handling(
        self,
        sample_context,
        sample_tools,
    ):
        """APIエラー時にエラー結果を返すこと"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            with patch.object(LLMBrain, "_call_openrouter", new_callable=AsyncMock) as mock_call:
                mock_call.side_effect = Exception("API Error: 500")
                brain = LLMBrain(use_openrouter=True)

                result = await brain.process(
                    context=sample_context,
                    message="タスク追加して",
                    tools=sample_tools,
                )

                assert result.confidence.overall == 0.0
                assert "エラー" in result.text_response
                assert "Exception" in result.text_response
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    @pytest.mark.asyncio
    async def test_process_with_anthropic_api(
        self,
        sample_context,
        sample_tools,
        mock_anthropic_response,
    ):
        """Anthropic APIでも処理できること"""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
        try:
            with patch.object(LLMBrain, "_call_anthropic", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = mock_anthropic_response
                brain = LLMBrain(use_openrouter=False)

                result = await brain.process(
                    context=sample_context,
                    message="タスク追加して",
                    tools=sample_tools,
                )

                assert isinstance(result, LLMBrainResult)
                assert result.api_provider == "anthropic"
                assert result.tool_calls is not None
        finally:
            del os.environ["ANTHROPIC_API_KEY"]


# =============================================================================
# LLMBrain._extract_confidence テスト
# =============================================================================


class TestLLMBrainExtractConfidence:
    """LLMBrain._extract_confidenceメソッドのテスト"""

    @pytest.fixture
    def brain(self):
        """テスト用のLLMBrain"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        brain = LLMBrain(use_openrouter=True)
        del os.environ["OPENROUTER_API_KEY"]
        return brain

    def test_extract_explicit_confidence(self, brain):
        """明示的な確信度を抽出できること"""
        reasoning = "この操作について確信度90%で進めます。"
        full_text = ""
        result = brain._extract_confidence(reasoning, full_text)
        assert result.overall == 0.9

    def test_extract_explicit_confidence_with_colon(self, brain):
        """コロン付きの確信度表記を抽出できること"""
        reasoning = "- 確信度: 85%"
        full_text = ""
        result = brain._extract_confidence(reasoning, full_text)
        assert result.overall == 0.85

    def test_extract_high_confidence_keyword(self, brain):
        """高確信度キーワードを検出できること"""
        reasoning = "この操作は確実に正しいです。"
        full_text = ""
        result = brain._extract_confidence(reasoning, full_text)
        assert result.overall >= 0.8

    def test_extract_medium_confidence_keyword(self, brain):
        """中確信度キーワードを検出できること"""
        reasoning = "おそらくタスク追加だと思います。"
        full_text = ""
        result = brain._extract_confidence(reasoning, full_text)
        assert result.overall == 0.7

    def test_extract_low_confidence_keyword(self, brain):
        """低確信度キーワードを検出できること"""
        reasoning = "よくわかりませんが、タスク関連かもしれません。"
        full_text = ""
        result = brain._extract_confidence(reasoning, full_text)
        assert result.overall <= 0.6

    def test_extract_default_confidence(self, brain):
        """キーワードがない場合はデフォルト値を返すこと"""
        reasoning = "処理を進めます。"
        full_text = ""
        result = brain._extract_confidence(reasoning, full_text)
        assert result.overall == 0.8  # デフォルト


# =============================================================================
# LLMBrain._build_system_prompt テスト
# =============================================================================


class TestLLMBrainBuildSystemPrompt:
    """LLMBrain._build_system_promptメソッドのテスト"""

    @pytest.fixture
    def brain(self):
        """テスト用のLLMBrain"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        brain = LLMBrain(use_openrouter=True)
        del os.environ["OPENROUTER_API_KEY"]
        return brain

    def test_includes_default_prompt(self, brain, sample_context):
        """デフォルトのシステムプロンプトが含まれること"""
        prompt = brain._build_system_prompt(DEFAULT_SYSTEM_PROMPT, sample_context)
        assert "ソウルくん" in prompt

    def test_includes_context(self, brain, sample_context):
        """コンテキストが含まれること"""
        sample_context.user_name = "テスト太郎"
        prompt = brain._build_system_prompt(DEFAULT_SYSTEM_PROMPT, sample_context)
        assert "テスト太郎" in prompt

    def test_includes_instructions(self, brain, sample_context):
        """重要な指示が含まれること"""
        prompt = brain._build_system_prompt(DEFAULT_SYSTEM_PROMPT, sample_context)
        assert "思考過程" in prompt
        assert "確信度" in prompt


# =============================================================================
# LLMBrain._convert_tools_to_openai_format テスト
# =============================================================================


class TestLLMBrainConvertTools:
    """LLMBrain._convert_tools_to_openai_formatメソッドのテスト"""

    @pytest.fixture
    def brain(self):
        """テスト用のLLMBrain"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        brain = LLMBrain(use_openrouter=True)
        del os.environ["OPENROUTER_API_KEY"]
        return brain

    def test_converts_single_tool(self, brain, sample_tools):
        """単一のToolを変換できること"""
        openai_tools = brain._convert_tools_to_openai_format([sample_tools[0]])
        assert len(openai_tools) == 1
        assert openai_tools[0]["type"] == "function"
        assert openai_tools[0]["function"]["name"] == "chatwork_task_create"

    def test_converts_multiple_tools(self, brain, sample_tools):
        """複数のToolを変換できること"""
        openai_tools = brain._convert_tools_to_openai_format(sample_tools)
        assert len(openai_tools) == 2

    def test_preserves_parameters(self, brain, sample_tools):
        """パラメータが保持されること"""
        openai_tools = brain._convert_tools_to_openai_format([sample_tools[0]])
        parameters = openai_tools[0]["function"]["parameters"]
        assert "properties" in parameters
        assert "body" in parameters["properties"]


# =============================================================================
# LLMBrain - エラーハンドリングテスト
# =============================================================================


class TestLLMBrainErrorHandling:
    """LLMBrainのエラーハンドリングテスト"""

    @pytest.mark.asyncio
    async def test_handle_rate_limit_error(self, sample_context, sample_tools):
        """レート制限エラーを適切に処理すること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            with patch.object(LLMBrain, "_call_openrouter", new_callable=AsyncMock) as mock_call:
                mock_call.side_effect = Exception("rate_limit_error: 429 Too Many Requests")
                brain = LLMBrain(use_openrouter=True)

                result = await brain.process(
                    context=sample_context,
                    message="テスト",
                    tools=sample_tools,
                )

                assert result.confidence.overall == 0.0
                assert result.text_response is not None
                assert "エラー" in result.text_response
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    @pytest.mark.asyncio
    async def test_handle_invalid_response(self, sample_context, sample_tools):
        """無効なレスポンスを適切に処理すること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            mock_response = {
                "choices": [
                    {
                        "message": {
                            "content": "",  # 空のコンテンツ
                        },
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }

            with patch.object(LLMBrain, "_call_openrouter", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = mock_response
                brain = LLMBrain(use_openrouter=True)

                result = await brain.process(
                    context=sample_context,
                    message="テスト",
                    tools=sample_tools,
                )

                # エラーにならず、何らかの結果が返ること
                assert isinstance(result, LLMBrainResult)
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    @pytest.mark.asyncio
    async def test_handle_empty_choices(self, sample_context, sample_tools):
        """空のchoicesを適切に処理すること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            mock_response = {
                "choices": [],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }

            with patch.object(LLMBrain, "_call_openrouter", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = mock_response
                brain = LLMBrain(use_openrouter=True)

                result = await brain.process(
                    context=sample_context,
                    message="テスト",
                    tools=sample_tools,
                )

                # エラー結果が返ること
                assert result.confidence.overall == 0.0
                assert "エラー" in result.text_response
        finally:
            del os.environ["OPENROUTER_API_KEY"]


# =============================================================================
# ファクトリ関数テスト
# =============================================================================


class TestFactoryFunctions:
    """ファクトリ関数のテスト"""

    def test_create_llm_brain_openrouter(self):
        """create_llm_brainがOpenRouter用のLLMBrainを作成すること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        try:
            brain = create_llm_brain(use_openrouter=True)
            assert brain.api_provider == APIProvider.OPENROUTER
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    def test_create_llm_brain_anthropic(self):
        """create_llm_brainがAnthropic用のLLMBrainを作成すること"""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
        try:
            brain = create_llm_brain(use_openrouter=False)
            assert brain.api_provider == APIProvider.ANTHROPIC
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_create_llm_brain_auto_prefers_openrouter(self):
        """create_llm_brain_autoがOpenRouterを優先すること"""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
        try:
            brain = create_llm_brain_auto()
            assert brain.api_provider == APIProvider.OPENROUTER
        finally:
            del os.environ["OPENROUTER_API_KEY"]
            del os.environ["ANTHROPIC_API_KEY"]

    def test_create_llm_brain_auto_falls_back_to_anthropic(self):
        """create_llm_brain_autoがAnthropicにフォールバックすること"""
        original_openrouter = os.environ.pop("OPENROUTER_API_KEY", None)
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
        try:
            # get_secret_cached は lib.secrets からインポートされるため、そちらをパッチ
            with patch("lib.secrets.get_secret_cached", side_effect=Exception("Not available")):
                brain = create_llm_brain_auto()
                assert brain.api_provider == APIProvider.ANTHROPIC
        finally:
            if original_openrouter:
                os.environ["OPENROUTER_API_KEY"] = original_openrouter
            del os.environ["ANTHROPIC_API_KEY"]

    def test_create_llm_brain_auto_raises_when_no_key(self):
        """create_llm_brain_autoがキーなしでエラーを投げること"""
        original_openrouter = os.environ.pop("OPENROUTER_API_KEY", None)
        original_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            # get_secret_cached は lib.secrets からインポートされるため、そちらをパッチ
            with patch("lib.secrets.get_secret_cached", side_effect=Exception("Not available")):
                with pytest.raises(ValueError, match="No API key available"):
                    create_llm_brain_auto()
        finally:
            if original_openrouter:
                os.environ["OPENROUTER_API_KEY"] = original_openrouter
            if original_anthropic:
                os.environ["ANTHROPIC_API_KEY"] = original_anthropic
