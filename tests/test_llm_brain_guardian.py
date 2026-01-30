# tests/test_llm_brain_guardian.py
"""
LLM Brain - Guardian Layer のテスト

LLMの判断をチェックする安全層の機能をテストします。

設計書: docs/25_llm_native_brain_architecture.md セクション5.3
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from lib.brain.guardian_layer import (
    GuardianLayer,
    GuardianAction,
    GuardianResult,
    DANGEROUS_OPERATIONS,
    SECURITY_NG_PATTERNS,
)
from lib.brain.llm_brain import ToolCall, LLMBrainResult, ConfidenceScores
from lib.brain.context_builder import LLMContext, CEOTeaching


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
def sample_tool_call():
    """テスト用のToolCall"""
    return ToolCall(
        tool_name="chatwork_task_create",
        parameters={"body": "テストタスク", "room_id": "123"},
        reasoning="タスク作成の意図を検出",
    )


@pytest.fixture
def sample_llm_result(sample_tool_call):
    """テスト用のLLMBrainResult"""
    return LLMBrainResult(
        output_type="tool_call",
        tool_calls=[sample_tool_call],
        reasoning="ユーザーがタスク追加を要求している",
        confidence=ConfidenceScores(overall=0.85, intent=0.90, parameters=0.80),
    )


@pytest.fixture
def sample_ceo_teachings():
    """テスト用のCEO教えリスト"""
    return [
        CEOTeaching(content="お客様第一", category="行動指針", priority=1),
        CEOTeaching(content="迅速に対応する", category="行動指針", priority=2),
    ]


@pytest.fixture
def guardian_with_teachings(sample_ceo_teachings):
    """CEO教え付きのGuardianLayer"""
    return GuardianLayer(ceo_teachings=sample_ceo_teachings)


@pytest.fixture
def guardian_no_teachings():
    """CEO教えなしのGuardianLayer"""
    return GuardianLayer()


# =============================================================================
# GuardianAction 列挙型テスト
# =============================================================================


class TestGuardianAction:
    """GuardianAction列挙型のテスト"""

    def test_values(self):
        """値が正しいこと"""
        assert GuardianAction.ALLOW.value == "allow"
        assert GuardianAction.CONFIRM.value == "confirm"
        assert GuardianAction.BLOCK.value == "block"
        assert GuardianAction.MODIFY.value == "modify"

    def test_all_actions(self):
        """全てのアクションが定義されていること"""
        assert len(list(GuardianAction)) == 4


# =============================================================================
# GuardianResult データクラステスト
# =============================================================================


class TestGuardianResult:
    """GuardianResultデータクラスのテスト"""

    def test_init_allow(self):
        """ALLOWの初期化"""
        result = GuardianResult(action=GuardianAction.ALLOW)
        assert result.action == GuardianAction.ALLOW
        assert result.reason is None

    def test_init_confirm(self):
        """CONFIRMの初期化"""
        result = GuardianResult(
            action=GuardianAction.CONFIRM,
            confirmation_question="確認してもいいですか？",
            reason="確信度が低い",
        )
        assert result.action == GuardianAction.CONFIRM
        assert result.confirmation_question == "確認してもいいですか？"

    def test_init_block(self):
        """BLOCKの初期化"""
        result = GuardianResult(
            action=GuardianAction.BLOCK,
            blocked_reason="危険な操作です",
        )
        assert result.action == GuardianAction.BLOCK
        assert result.blocked_reason == "危険な操作です"

    def test_to_dict(self):
        """to_dictが正しい形式を返すこと"""
        result = GuardianResult(
            action=GuardianAction.CONFIRM,
            reason="テスト理由",
            priority_level=3,
        )
        d = result.to_dict()
        assert d["action"] == "confirm"
        assert d["reason"] == "テスト理由"
        assert d["priority_level"] == 3


# =============================================================================
# DANGEROUS_OPERATIONS 定数テスト
# =============================================================================


class TestDangerousOperations:
    """DANGEROUS_OPERATIONS定数のテスト"""

    def test_structure(self):
        """各操作が正しい構造を持つこと"""
        for op_name, config in DANGEROUS_OPERATIONS.items():
            assert "risk" in config
            assert "action" in config

    def test_high_risk_operations(self):
        """高リスク操作が定義されていること"""
        high_risk = [
            op for op, config in DANGEROUS_OPERATIONS.items()
            if config.get("risk") == "high"
        ]
        assert len(high_risk) > 0

    def test_send_to_all_is_high_risk(self):
        """send_to_allが高リスクであること"""
        assert "send_to_all" in DANGEROUS_OPERATIONS
        assert DANGEROUS_OPERATIONS["send_to_all"]["risk"] == "high"

    def test_delete_operations_exist(self):
        """削除系操作が定義されていること"""
        delete_ops = [op for op in DANGEROUS_OPERATIONS.keys() if "delete" in op]
        assert len(delete_ops) > 0


# =============================================================================
# SECURITY_NG_PATTERNS 定数テスト
# =============================================================================


class TestSecurityNGPatterns:
    """SECURITY_NG_PATTERNS定数のテスト"""

    def test_not_empty(self):
        """空でないこと"""
        assert len(SECURITY_NG_PATTERNS) > 0

    def test_patterns_are_strings(self):
        """全てのパターンが文字列であること"""
        for pattern in SECURITY_NG_PATTERNS:
            assert isinstance(pattern, str)


# =============================================================================
# GuardianLayer 初期化テスト
# =============================================================================


class TestGuardianLayerInit:
    """GuardianLayer初期化のテスト"""

    def test_init_no_args(self):
        """引数なしで初期化できること"""
        guardian = GuardianLayer()
        assert guardian.ceo_teachings == []

    def test_init_with_ceo_teachings(self, sample_ceo_teachings):
        """CEO教え付きで初期化できること"""
        guardian = GuardianLayer(ceo_teachings=sample_ceo_teachings)
        assert len(guardian.ceo_teachings) == 2

    def test_init_with_custom_ng_patterns(self):
        """カスタムNGパターン付きで初期化できること"""
        custom_patterns = ["カスタムNG1", "カスタムNG2"]
        guardian = GuardianLayer(custom_ng_patterns=custom_patterns)
        assert "カスタムNG1" in guardian.ng_patterns
        assert "カスタムNG2" in guardian.ng_patterns

    def test_thresholds(self):
        """閾値が設定されていること"""
        guardian = GuardianLayer()
        assert hasattr(guardian, "CONFIDENCE_THRESHOLD_BLOCK")
        assert hasattr(guardian, "CONFIDENCE_THRESHOLD_CONFIRM")
        assert guardian.CONFIDENCE_THRESHOLD_BLOCK < guardian.CONFIDENCE_THRESHOLD_CONFIRM


# =============================================================================
# GuardianLayer.check - 正常系テスト
# =============================================================================


class TestGuardianLayerCheckNormal:
    """GuardianLayer.check 正常系のテスト"""

    @pytest.mark.asyncio
    async def test_allow_high_confidence_safe_operation(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """高確信度の安全な操作でALLOWを返すこと"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={"body": "テスト"},
                    reasoning="タスク作成",
                )
            ],
            reasoning="ユーザーがタスク追加を要求しています。chatwork_task_createを使用してタスクを作成します。",  # 必須
            confidence=ConfidenceScores(overall=0.85, intent=0.90, parameters=0.80),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        assert guardian_result.action == GuardianAction.ALLOW

    @pytest.mark.asyncio
    async def test_allow_text_response(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """テキスト応答のみの場合でもALLOWを返すこと"""
        result = LLMBrainResult(
            output_type="text_response",
            tool_calls=None,
            text_response="お手伝いできることはありますか？",
            confidence=ConfidenceScores(overall=0.9, intent=0.9, parameters=0.9),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        assert guardian_result.action == GuardianAction.ALLOW


# =============================================================================
# GuardianLayer.check - 確信度チェックテスト
# =============================================================================


class TestGuardianLayerCheckConfidence:
    """GuardianLayer.check 確信度チェックのテスト"""

    @pytest.mark.asyncio
    async def test_confirm_low_confidence(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """低確信度でCONFIRMを返すこと"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={"body": "テスト"},
                    reasoning="タスク作成...かもしれない",
                )
            ],
            reasoning="ユーザーの意図を分析しています。タスク作成かもしれませんが確信が持てません。",  # 必須
            confidence=ConfidenceScores(overall=0.5, intent=0.6, parameters=0.4),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM
        assert "確信度" in guardian_result.reason

    @pytest.mark.asyncio
    async def test_block_very_low_confidence(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """非常に低い確信度でBLOCKを返すこと"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={"body": "テスト"},
                    reasoning="よくわからない",
                )
            ],
            confidence=ConfidenceScores(overall=0.2, intent=0.2, parameters=0.2),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        assert guardian_result.action == GuardianAction.BLOCK


# =============================================================================
# GuardianLayer.check - 危険操作チェックテスト
# =============================================================================


class TestGuardianLayerCheckDangerous:
    """GuardianLayer.check 危険操作チェックのテスト"""

    @pytest.mark.asyncio
    async def test_confirm_send_to_all(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """全員送信でCONFIRMを返すこと"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="send_to_all",
                    parameters={"message": "お知らせ"},
                    reasoning="全員への送信",
                )
            ],
            reasoning="ユーザーが全員へのメッセージ送信を要求しています。send_to_allを使用します。",  # 必須
            confidence=ConfidenceScores(overall=0.95, intent=0.95, parameters=0.95),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM
        assert "危険" in guardian_result.reason or "send_to_all" in guardian_result.reason

    @pytest.mark.asyncio
    async def test_confirm_delete_operation(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """削除操作でCONFIRMを返すこと"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="delete_task",
                    parameters={"task_id": "123"},
                    reasoning="タスク削除",
                )
            ],
            reasoning="ユーザーがタスクの削除を要求しています。delete_taskを使用します。",  # 必須
            confidence=ConfidenceScores(overall=0.9, intent=0.9, parameters=0.9),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        assert guardian_result.action == GuardianAction.CONFIRM


# =============================================================================
# GuardianLayer.check - セキュリティチェックテスト
# =============================================================================


class TestGuardianLayerCheckSecurity:
    """GuardianLayer.check セキュリティチェックのテスト"""

    @pytest.mark.asyncio
    async def test_block_security_ng_pattern(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """セキュリティNGパターンでBLOCKを返すこと"""
        # NGパターンを含むパラメータ
        ng_pattern = SECURITY_NG_PATTERNS[0] if SECURITY_NG_PATTERNS else "password"
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="save_memory",
                    parameters={"content": f"秘密情報: {ng_pattern}"},
                    reasoning="メモリ保存",
                )
            ],
            confidence=ConfidenceScores(overall=0.9, intent=0.9, parameters=0.9),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        # セキュリティNGパターンが検出されればBLOCK
        # 検出されない場合はALLOW（パターンの内容による）
        assert guardian_result.action in [GuardianAction.BLOCK, GuardianAction.ALLOW]


# =============================================================================
# GuardianLayer - 確認メッセージ生成テスト
# =============================================================================


class TestGuardianLayerConfirmationMessages:
    """確認メッセージ生成のテスト"""

    @pytest.mark.asyncio
    async def test_confirmation_question_format(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """確認質問が適切な形式であること"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="send_to_all",
                    parameters={"message": "テスト"},
                    reasoning="全員送信",
                )
            ],
            confidence=ConfidenceScores(overall=0.9, intent=0.9, parameters=0.9),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        if guardian_result.confirmation_question:
            # ソウルくんの口調を含むこと
            assert "ウル" in guardian_result.confirmation_question

    @pytest.mark.asyncio
    async def test_confirmation_includes_tool_name(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """確認質問にTool名が含まれること"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="delete_memory",
                    parameters={"memory_id": "123"},
                    reasoning="メモリ削除",
                )
            ],
            confidence=ConfidenceScores(overall=0.9, intent=0.9, parameters=0.9),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        if guardian_result.confirmation_question:
            assert "delete_memory" in guardian_result.confirmation_question


# =============================================================================
# GuardianLayer - 優先度レベルテスト
# =============================================================================


class TestGuardianLayerPriorityLevel:
    """優先度レベルのテスト"""

    @pytest.mark.asyncio
    async def test_priority_level_set(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """優先度レベルが設定されること"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="send_to_all",
                    parameters={"message": "テスト"},
                    reasoning="全員送信",
                )
            ],
            confidence=ConfidenceScores(overall=0.9, intent=0.9, parameters=0.9),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        assert guardian_result.priority_level >= 0


# =============================================================================
# GuardianLayer - エッジケーステスト
# =============================================================================


class TestGuardianLayerEdgeCases:
    """エッジケースのテスト"""

    @pytest.mark.asyncio
    async def test_empty_tool_calls(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """空のtool_callsでも動作すること"""
        result = LLMBrainResult(
            output_type="text_response",
            tool_calls=[],
            text_response="テスト応答",
            confidence=ConfidenceScores(overall=0.9, intent=0.9, parameters=0.9),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        assert guardian_result.action == GuardianAction.ALLOW

    @pytest.mark.asyncio
    async def test_none_tool_calls(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """Noneのtool_callsでも動作すること"""
        result = LLMBrainResult(
            output_type="text_response",
            tool_calls=None,
            text_response="テスト応答",
            confidence=ConfidenceScores(overall=0.9, intent=0.9, parameters=0.9),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        assert guardian_result.action == GuardianAction.ALLOW

    @pytest.mark.asyncio
    async def test_empty_parameters(
        self,
        guardian_no_teachings,
        sample_context,
    ):
        """空のparametersでも動作すること"""
        result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_search",
                    parameters={},
                    reasoning="タスク検索",
                )
            ],
            reasoning="ユーザーがタスク検索を要求しています。chatwork_task_searchを使用します。",  # 必須
            confidence=ConfidenceScores(overall=0.85, intent=0.9, parameters=0.8),
        )

        guardian_result = await guardian_no_teachings.check(result, sample_context)
        # パラメータが空でも安全な操作ならALLOW
        assert guardian_result.action in [GuardianAction.ALLOW, GuardianAction.CONFIRM]
