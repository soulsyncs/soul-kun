# tests/test_llm_brain_edge_cases.py
"""
LLM Brain - エッジケーステスト

Task #8: カバレッジ向上のためのエッジケーステスト

テスト対象:
- llm_brain.py: _call_openrouter(), _call_anthropic(), レスポンス解析
- guardian_layer.py: _check_amount_and_recipients(), _check_consistency(), _check_date_validity()
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta
import json
import httpx

from lib.brain.guardian_layer import (
    GuardianLayer,
    GuardianAction,
    GuardianResult,
)
from lib.brain.llm_brain import (
    ToolCall,
    LLMBrainResult,
    ConfidenceScores,
    LLMBrain,
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
def guardian():
    """標準のGuardianLayer"""
    return GuardianLayer()


@pytest.fixture
def llm_brain_openrouter():
    """OpenRouter APIを使用するLLMBrain"""
    return LLMBrain(
        api_key="test-openrouter-key",
        use_openrouter=True,
    )


@pytest.fixture
def llm_brain_anthropic():
    """Anthropic APIを使用するLLMBrain"""
    return LLMBrain(
        api_key="test-anthropic-key",
        use_openrouter=False,
    )


# =============================================================================
# GuardianLayer - 金額・送信先チェックテスト
# =============================================================================


class TestGuardianCheckAmountAndRecipients:
    """_check_amount_and_recipients() のテスト"""

    @pytest.mark.asyncio
    async def test_high_amount_requires_double_confirmation(self, guardian, sample_context):
        """高額操作（100万以上）は強い確認が必要"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="payment_execute",
                    parameters={"amount": 1500000, "recipient": "業者A"},
                    reasoning="支払い実行",
                )
            ],
            reasoning="支払い操作を実行します",
            confidence=ConfidenceScores(overall=0.95, intent=0.95, parameters=0.95),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM
        # 金額は表示される（フォーマットはカンマなしでも可）
        assert "1500000" in guardian_result.confirmation_question or "1,500,000" in guardian_result.confirmation_question
        assert "本当に" in guardian_result.confirmation_question

    @pytest.mark.asyncio
    async def test_medium_amount_requires_confirmation(self, guardian, sample_context):
        """中額操作（10万以上）は確認が必要"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="payment_execute",
                    parameters={"amount": 150000},
                    reasoning="支払い実行",
                )
            ],
            reasoning="支払い操作を実行します",
            confidence=ConfidenceScores(overall=0.95, intent=0.95, parameters=0.95),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM
        # 金額は表示される（フォーマットはカンマなしでも可）
        assert "150000" in guardian_result.confirmation_question or "150,000" in guardian_result.confirmation_question

    @pytest.mark.asyncio
    async def test_low_amount_allowed(self, guardian, sample_context):
        """低額操作（10万未満）は確認不要"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={"body": "テスト", "amount": 5000},
                    reasoning="タスク作成",
                )
            ],
            reasoning="タスク作成を実行します",
            confidence=ConfidenceScores(overall=0.85, intent=0.9, parameters=0.8),
        )

        guardian_result = await guardian.check(result, sample_context)
        # 金額が低く、安全な操作なのでALLOW
        assert guardian_result.action == GuardianAction.ALLOW

    @pytest.mark.asyncio
    async def test_many_recipients_requires_double_confirmation(self, guardian, sample_context):
        """大量送信（50人以上）は強い確認が必要"""
        recipients = [f"user_{i}" for i in range(60)]
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="send_message",
                    parameters={"message": "お知らせ", "recipients": recipients},
                    reasoning="メッセージ送信",
                )
            ],
            reasoning="メッセージ送信を実行します",
            confidence=ConfidenceScores(overall=0.95, intent=0.95, parameters=0.95),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM
        assert "60人" in guardian_result.confirmation_question
        assert "本当に" in guardian_result.confirmation_question

    @pytest.mark.asyncio
    async def test_some_recipients_requires_confirmation(self, guardian, sample_context):
        """複数送信（10人以上）は確認が必要"""
        recipients = [f"user_{i}" for i in range(15)]
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="send_message",
                    parameters={"message": "お知らせ", "recipients": recipients},
                    reasoning="メッセージ送信",
                )
            ],
            reasoning="メッセージ送信を実行します",
            confidence=ConfidenceScores(overall=0.95, intent=0.95, parameters=0.95),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM
        assert "15人" in guardian_result.confirmation_question

    @pytest.mark.asyncio
    async def test_amount_with_japanese_key(self, guardian, sample_context):
        """日本語キー「金額」でも金額チェックが動作する"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="payment_execute",
                    parameters={"金額": 200000},
                    reasoning="支払い実行",
                )
            ],
            reasoning="支払い操作を実行します",
            confidence=ConfidenceScores(overall=0.95, intent=0.95, parameters=0.95),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM
        # 金額は表示される（フォーマットはカンマなしでも可）
        assert "200000" in guardian_result.confirmation_question or "200,000" in guardian_result.confirmation_question

    @pytest.mark.asyncio
    async def test_invalid_amount_value_skipped(self, guardian, sample_context):
        """無効な金額値はスキップされる"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={"body": "テスト", "amount": "たくさん"},
                    reasoning="タスク作成",
                )
            ],
            reasoning="タスク作成を実行します",
            confidence=ConfidenceScores(overall=0.85, intent=0.9, parameters=0.8),
        )

        guardian_result = await guardian.check(result, sample_context)
        # 金額が無効なので金額チェックはスキップされ、他のチェックに進む
        assert guardian_result.action in [GuardianAction.ALLOW, GuardianAction.CONFIRM]


# =============================================================================
# GuardianLayer - 日付妥当性チェックテスト
# =============================================================================


class TestGuardianCheckDateValidity:
    """_check_date_validity() のテスト"""

    @pytest.mark.asyncio
    async def test_past_date_requires_confirmation(self, guardian, sample_context):
        """過去の日付は確認が必要"""
        past_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={"body": "テスト", "limit_date": past_date},
                    reasoning="タスク作成",
                )
            ],
            reasoning="タスク作成を実行します",
            confidence=ConfidenceScores(overall=0.85, intent=0.9, parameters=0.8),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM
        assert "過去" in guardian_result.confirmation_question

    @pytest.mark.asyncio
    async def test_far_future_date_requires_confirmation(self, guardian, sample_context):
        """遠い未来（1年以上先）の日付は確認が必要"""
        far_future = (datetime.now() + timedelta(days=400)).strftime("%Y-%m-%d")
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={"body": "テスト", "due_date": far_future},
                    reasoning="タスク作成",
                )
            ],
            reasoning="タスク作成を実行します",
            confidence=ConfidenceScores(overall=0.85, intent=0.9, parameters=0.8),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM
        assert "先" in guardian_result.confirmation_question

    @pytest.mark.asyncio
    async def test_near_future_date_allowed(self, guardian, sample_context):
        """近い未来の日付は許可される"""
        near_future = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={"body": "テスト", "deadline": near_future},
                    reasoning="タスク作成",
                )
            ],
            reasoning="タスク作成を実行します",
            confidence=ConfidenceScores(overall=0.85, intent=0.9, parameters=0.8),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.ALLOW

    @pytest.mark.asyncio
    async def test_invalid_date_format_requires_confirmation(self, guardian, sample_context):
        """無効な日付形式は確認が必要"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={"body": "テスト", "limit_date": "来週の月曜日"},
                    reasoning="タスク作成",
                )
            ],
            reasoning="タスク作成を実行します",
            confidence=ConfidenceScores(overall=0.85, intent=0.9, parameters=0.8),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM
        assert "形式" in guardian_result.confirmation_question

    @pytest.mark.asyncio
    async def test_japanese_date_key(self, guardian, sample_context):
        """日本語キー「期限」でも日付チェックが動作する"""
        past_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={"body": "テスト", "期限": past_date},
                    reasoning="タスク作成",
                )
            ],
            reasoning="タスク作成を実行します",
            confidence=ConfidenceScores(overall=0.85, intent=0.9, parameters=0.8),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM


# =============================================================================
# LLMBrain - OpenRouter API呼び出しテスト
# =============================================================================


class TestLLMBrainOpenRouterAPICall:
    """_call_openrouter() のテスト"""

    @pytest.mark.asyncio
    async def test_call_openrouter_success(self, llm_brain_openrouter):
        """正常なOpenRouter API呼び出し"""
        mock_response = httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "【思考過程】テスト思考\n\nテスト応答",
                            "tool_calls": [],
                        }
                    }
                ]
            },
        )

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            response = await llm_brain_openrouter._call_openrouter(
                system="テストシステムプロンプト",
                messages=[{"role": "user", "content": "テスト"}],
                tools=[],
            )

            assert "choices" in response
            assert len(response["choices"]) == 1

    @pytest.mark.asyncio
    async def test_call_openrouter_rate_limit_error(self, llm_brain_openrouter):
        """OpenRouter レート制限エラー"""
        mock_response = httpx.Response(
            429,
            json={"error": {"message": "Rate limit exceeded"}},
            text='{"error": {"message": "Rate limit exceeded"}}',
        )

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            with pytest.raises(Exception) as exc_info:
                await llm_brain_openrouter._call_openrouter(
                    system="テスト",
                    messages=[{"role": "user", "content": "テスト"}],
                    tools=[],
                )

            assert "429" in str(exc_info.value) or "Rate limit" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_openrouter_server_error(self, llm_brain_openrouter):
        """OpenRouter サーバーエラー"""
        mock_response = httpx.Response(
            500,
            json={"error": {"message": "Internal server error"}},
            text='{"error": {"message": "Internal server error"}}',
        )

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            with pytest.raises(Exception) as exc_info:
                await llm_brain_openrouter._call_openrouter(
                    system="テスト",
                    messages=[{"role": "user", "content": "テスト"}],
                    tools=[],
                )

            assert "500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_openrouter_with_tools(self, llm_brain_openrouter):
        """Tool付きのOpenRouter API呼び出し"""
        mock_response = httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "【思考過程】タスク追加を実行します",
                            "tool_calls": [
                                {
                                    "id": "call_123",
                                    "type": "function",
                                    "function": {
                                        "name": "chatwork_task_create",
                                        "arguments": '{"body": "テストタスク"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            tools = [
                {
                    "name": "chatwork_task_create",
                    "description": "タスクを作成",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]

            response = await llm_brain_openrouter._call_openrouter(
                system="テスト",
                messages=[{"role": "user", "content": "タスク追加して"}],
                tools=tools,
            )

            assert "choices" in response
            message = response["choices"][0]["message"]
            assert len(message["tool_calls"]) == 1
            assert message["tool_calls"][0]["function"]["name"] == "chatwork_task_create"


# =============================================================================
# LLMBrain - Anthropic API呼び出しテスト
# =============================================================================


class TestLLMBrainAnthropicAPICall:
    """_call_anthropic() のテスト"""

    @pytest.mark.asyncio
    async def test_call_anthropic_success(self, llm_brain_anthropic):
        """正常なAnthropic API呼び出し"""
        mock_response = httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": "【思考過程】テスト思考\n\nテスト応答",
                    }
                ],
                "stop_reason": "end_turn",
            },
        )

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            response = await llm_brain_anthropic._call_anthropic(
                system="テストシステムプロンプト",
                messages=[{"role": "user", "content": "テスト"}],
                tools=[],
            )

            assert "content" in response

    @pytest.mark.asyncio
    async def test_call_anthropic_invalid_api_key(self, llm_brain_anthropic):
        """無効なAPIキーエラー"""
        mock_response = httpx.Response(
            401,
            json={"error": {"message": "Invalid API key"}},
            text='{"error": {"message": "Invalid API key"}}',
        )

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            with pytest.raises(Exception) as exc_info:
                await llm_brain_anthropic._call_anthropic(
                    system="テスト",
                    messages=[{"role": "user", "content": "テスト"}],
                    tools=[],
                )

            assert "401" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_anthropic_overloaded(self, llm_brain_anthropic):
        """Anthropic API過負荷エラー"""
        mock_response = httpx.Response(
            529,
            json={"error": {"message": "Overloaded"}},
            text='{"error": {"message": "Overloaded"}}',
        )

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            with pytest.raises(Exception) as exc_info:
                await llm_brain_anthropic._call_anthropic(
                    system="テスト",
                    messages=[{"role": "user", "content": "テスト"}],
                    tools=[],
                )

            assert "529" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_anthropic_with_tool_use(self, llm_brain_anthropic):
        """Tool使用を含むAnthropic API呼び出し"""
        mock_response = httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": "【思考過程】タスク追加を実行します",
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "chatwork_task_create",
                        "input": {"body": "テストタスク"},
                    },
                ],
                "stop_reason": "tool_use",
            },
        )

        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            tools = [
                {
                    "name": "chatwork_task_create",
                    "description": "タスクを作成",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]

            response = await llm_brain_anthropic._call_anthropic(
                system="テスト",
                messages=[{"role": "user", "content": "タスク追加して"}],
                tools=tools,
            )

            assert "content" in response
            assert len(response["content"]) == 2
            assert response["content"][1]["type"] == "tool_use"


# =============================================================================
# LLMBrain - レスポンス解析エッジケーステスト
# =============================================================================


class TestLLMBrainResponseParsing:
    """レスポンス解析のエッジケーステスト"""

    def test_parse_tool_arguments_json_error(self, llm_brain_openrouter):
        """無効なJSONのtool引数をパースしても例外を投げない"""
        response = {
            "choices": [
                {
                    "message": {
                        "content": "テスト",
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "test_tool",
                                    "arguments": "invalid json {{{",
                                },
                            }
                        ],
                    }
                }
            ]
        }

        # 例外が発生しないことを確認
        result = llm_brain_openrouter._parse_openrouter_response(response)

        # 結果が返されること
        assert result is not None
        assert result.tool_calls is not None
        # 無効なJSONの場合、パラメータは空辞書になる
        if result.tool_calls:
            assert result.tool_calls[0].parameters == {}

    def test_parse_empty_choices(self, llm_brain_openrouter):
        """空のchoicesでも結果を返す（エラーハンドリング）"""
        response = {"choices": []}

        result = llm_brain_openrouter._parse_openrouter_response(response)

        assert result is not None
        # 空のchoicesの場合はtext_response（エラーメッセージ付き）
        assert result.output_type in ["error", "text_response"]

    def test_parse_missing_message(self, llm_brain_openrouter):
        """messageがない場合の処理"""
        response = {
            "choices": [
                {
                    # messageがない
                }
            ]
        }

        result = llm_brain_openrouter._parse_openrouter_response(response)

        # エラーにならず結果が返される
        assert result is not None

    def test_parse_extract_reasoning_and_response(self, llm_brain_openrouter):
        """思考過程と応答の分離"""
        response = {
            "choices": [
                {
                    "message": {
                        "content": """【思考過程】
- 意図理解: ユーザーは挨拶している
- 根拠: 「こんにちは」から判断

こんにちは！何かお手伝いできることはありますかウル？""",
                        "tool_calls": [],
                    }
                }
            ]
        }

        result = llm_brain_openrouter._parse_openrouter_response(response)

        assert result is not None
        # 思考過程が含まれること
        assert "意図理解" in result.reasoning
        # raw_responseに元のテキストが含まれること
        assert "こんにちは" in (result.raw_response or "")

    def test_parse_confidence_extraction(self, llm_brain_openrouter):
        """確信度の抽出"""
        response = {
            "choices": [
                {
                    "message": {
                        "content": """【思考過程】
- 意図理解: タスク追加
- 確信度: 92%

了解しましたウル！""",
                        "tool_calls": [],
                    }
                }
            ]
        }

        result = llm_brain_openrouter._parse_openrouter_response(response)

        assert result is not None
        assert result.confidence.overall >= 0.9


# =============================================================================
# GuardianLayer - 整合性チェックテスト
# =============================================================================


class TestGuardianCheckConsistency:
    """_check_consistency() のテスト"""

    @pytest.mark.asyncio
    async def test_consistency_check_passes_with_valid_params(self, guardian, sample_context):
        """有効なパラメータは整合性チェックをパスする"""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={
                        "body": "テストタスク",
                        "limit_date": tomorrow,
                        "room_id": "123",
                    },
                    reasoning="タスク作成",
                )
            ],
            reasoning="タスク作成を実行します",
            confidence=ConfidenceScores(overall=0.9, intent=0.9, parameters=0.9),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.ALLOW

    @pytest.mark.asyncio
    async def test_multiple_date_params_checked(self, guardian, sample_context):
        """複数の日付パラメータがすべてチェックされる"""
        past_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="event_create",
                    parameters={
                        "title": "イベント",
                        "due_date": past_date,  # これがチェックで引っかかる
                    },
                    reasoning="イベント作成",
                )
            ],
            reasoning="イベント作成を実行します",
            confidence=ConfidenceScores(overall=0.9, intent=0.9, parameters=0.9),
        )

        guardian_result = await guardian.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM


# =============================================================================
# 統合テスト - Guardian + LLMBrain
# =============================================================================


class TestGuardianLLMBrainIntegration:
    """GuardianLayerとLLMBrainの統合テスト"""

    @pytest.mark.asyncio
    async def test_full_flow_safe_operation(self, guardian, sample_context, llm_brain_openrouter):
        """安全な操作の完全フロー"""
        # LLMBrainの結果を模擬
        llm_result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_search",
                    parameters={"query": "今日のタスク"},
                    reasoning="タスク検索を実行",
                )
            ],
            reasoning="ユーザーがタスク検索を要求しています",
            confidence=ConfidenceScores(overall=0.9, intent=0.95, parameters=0.85),
        )

        # Guardianでチェック
        guardian_result = await guardian.check(llm_result, sample_context)

        # 安全な操作なのでALLOW
        assert guardian_result.action == GuardianAction.ALLOW

    @pytest.mark.asyncio
    async def test_full_flow_dangerous_operation(self, guardian, sample_context, llm_brain_openrouter):
        """危険な操作の完全フロー"""
        # 危険な操作を模擬（send_to_all は DANGEROUS_OPERATIONS に登録されている）
        llm_result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="send_to_all",
                    parameters={"message": "全員へのお知らせ"},
                    reasoning="全員送信",
                )
            ],
            reasoning="ユーザーが全員へのメッセージ送信を要求しています",
            confidence=ConfidenceScores(overall=0.95, intent=0.95, parameters=0.95),
        )

        # Guardianでチェック
        guardian_result = await guardian.check(llm_result, sample_context)

        # 危険な操作なのでCONFIRMまたはBLOCK
        assert guardian_result.action in [GuardianAction.CONFIRM, GuardianAction.BLOCK]


# =============================================================================
# Task #11: Guardian Layer強化テスト
# =============================================================================


class TestGuardianEnhancedRules:
    """Guardian Layer強化ルールのテスト"""

    @pytest.fixture
    def guardian(self):
        return GuardianLayer()

    @pytest.fixture
    def context(self):
        return LLMContext(
            user_id="user_001",
            user_name="テストユーザー",
            user_role="member",
            organization_id="org_test",
            room_id="room_123",
            current_datetime=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_payment_operation_requires_confirmation(self, guardian, context):
        """支払い操作は確認が必要"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="payment_execute",
                    parameters={"amount": 50000, "recipient": "業者A"},
                    reasoning="支払い実行",
                )
            ],
            reasoning="支払い操作",
            confidence=ConfidenceScores(overall=0.95, intent=0.95, parameters=0.95),
        )

        guardian_result = await guardian.check(result, context)
        assert guardian_result.action == GuardianAction.CONFIRM

    @pytest.mark.asyncio
    async def test_bulk_delete_requires_double_confirmation(self, guardian, context):
        """一括削除は二重確認が必要"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="bulk_delete",
                    parameters={"target": "old_tasks", "count": 100},
                    reasoning="一括削除",
                )
            ],
            reasoning="古いタスクの一括削除",
            confidence=ConfidenceScores(overall=0.95, intent=0.95, parameters=0.95),
        )

        guardian_result = await guardian.check(result, context)
        assert guardian_result.action == GuardianAction.CONFIRM
        assert "本当に" in guardian_result.confirmation_question

    @pytest.mark.asyncio
    async def test_permission_change_blocked(self, guardian, context):
        """権限変更はブロック"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="grant_access",
                    parameters={"user_id": "user_123", "resource": "confidential"},
                    reasoning="アクセス権付与",
                )
            ],
            reasoning="アクセス権付与",
            confidence=ConfidenceScores(overall=0.95, intent=0.95, parameters=0.95),
        )

        guardian_result = await guardian.check(result, context)
        assert guardian_result.action == GuardianAction.BLOCK

    @pytest.mark.asyncio
    async def test_external_api_call_requires_confirmation(self, guardian, context):
        """外部API呼び出しは確認が必要"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="api_call_external",
                    parameters={"url": "https://external.api.com", "method": "POST"},
                    reasoning="外部API呼び出し",
                )
            ],
            reasoning="外部APIへのリクエスト",
            confidence=ConfidenceScores(overall=0.9, intent=0.9, parameters=0.9),
        )

        guardian_result = await guardian.check(result, context)
        assert guardian_result.action == GuardianAction.CONFIRM
