"""
Decision Layer Enforcement テスト

v10.42.0 P1: NGパターン検出時の強制アクション（警告→強制）のテスト
"""

import pytest
from unittest.mock import MagicMock, patch
from lib.brain.decision import (
    BrainDecision,
    EnforcementAction,
    MVVCheckResult,
    create_decision,
)
from lib.brain.models import (
    UnderstandingResult,
    BrainContext,
)


class TestEnforcementAction:
    """EnforcementAction Enum のテスト"""

    def test_enum_values(self):
        """Enumの値が正しいこと"""
        assert EnforcementAction.NONE.value == "none"
        assert EnforcementAction.FORCE_LISTENING.value == "force_listening"
        assert EnforcementAction.BLOCK_AND_SUGGEST.value == "block_and_suggest"
        assert EnforcementAction.WARN_ONLY.value == "warn_only"

    def test_all_members_exist(self):
        """すべてのメンバーが存在すること"""
        members = list(EnforcementAction)
        assert len(members) == 4
        assert EnforcementAction.NONE in members
        assert EnforcementAction.FORCE_LISTENING in members
        assert EnforcementAction.BLOCK_AND_SUGGEST in members
        assert EnforcementAction.WARN_ONLY in members


class TestMVVCheckResult:
    """MVVCheckResult with enforcement_action のテスト"""

    def test_default_enforcement_action(self):
        """デフォルトではNONE"""
        result = MVVCheckResult()
        assert result.enforcement_action == EnforcementAction.NONE

    def test_enforcement_action_force_listening(self):
        """FORCE_LISTENINGを設定できること"""
        result = MVVCheckResult(
            is_aligned=False,
            ng_pattern_detected=True,
            ng_pattern_type="ng_mental_health",
            risk_level="CRITICAL",
            enforcement_action=EnforcementAction.FORCE_LISTENING,
        )
        assert result.enforcement_action == EnforcementAction.FORCE_LISTENING
        assert result.ng_pattern_detected is True
        assert result.risk_level == "CRITICAL"

    def test_enforcement_action_block_and_suggest(self):
        """BLOCK_AND_SUGGESTを設定できること"""
        result = MVVCheckResult(
            is_aligned=False,
            ng_pattern_detected=True,
            ng_pattern_type="ng_company_criticism",
            risk_level="MEDIUM",
            enforcement_action=EnforcementAction.BLOCK_AND_SUGGEST,
        )
        assert result.enforcement_action == EnforcementAction.BLOCK_AND_SUGGEST
        assert result.risk_level == "MEDIUM"


class TestDecisionEnforcementOverride:
    """decide() での強制アクションオーバーライドのテスト"""

    @pytest.fixture
    def mock_capabilities(self):
        """テスト用の機能カタログ"""
        return {
            "general_conversation": {
                "name": "一般会話",
                "enabled": True,
                "brain_metadata": {
                    "decision_keywords": {
                        "primary": [],
                        "secondary": ["こんにちは"],
                        "negative": [],
                    }
                },
            },
            "chatwork_task_create": {
                "name": "タスク作成",
                "enabled": True,
                "brain_metadata": {
                    "decision_keywords": {
                        "primary": ["タスク作成", "タスク追加"],
                        "secondary": ["タスク"],
                        "negative": [],
                    }
                },
            },
        }

    @pytest.fixture
    def decision(self, mock_capabilities):
        """テスト用Decisionインスタンス"""
        return create_decision(
            capabilities=mock_capabilities,
            org_id="test-org",
        )

    @pytest.fixture
    def mock_understanding(self):
        """テスト用理解結果"""
        return UnderstandingResult(
            intent="general_conversation",
            intent_confidence=0.8,
            entities={},
            raw_message="テストメッセージ",
        )

    @pytest.fixture
    def mock_context(self):
        """テスト用コンテキスト"""
        context = MagicMock(spec=BrainContext)
        context.has_active_session.return_value = False
        return context

    @pytest.mark.asyncio
    async def test_critical_risk_forces_listening(
        self, decision, mock_understanding, mock_context
    ):
        """CRITICAL リスクは傾聴モードへ強制遷移"""
        mock_understanding.raw_message = "もう生きてる意味がない"

        # MVV checkがCRITICALを返すようにパッチ
        with patch.object(
            decision,
            "_check_mvv_alignment",
            return_value=MVVCheckResult(
                is_aligned=False,
                ng_pattern_detected=True,
                ng_pattern_type="ng_mental_health",
                ng_response_hint="つらい状況ですね",
                risk_level="CRITICAL",
                enforcement_action=EnforcementAction.FORCE_LISTENING,
            ),
        ):
            result = await decision.decide(mock_understanding, mock_context)

        assert result.action == "forced_listening"
        assert result.confidence == 1.0
        assert result.params["ng_pattern_type"] == "ng_mental_health"
        assert result.params["risk_level"] == "CRITICAL"
        assert "強制遷移" in result.reasoning

    @pytest.mark.asyncio
    async def test_high_risk_forces_listening(
        self, decision, mock_understanding, mock_context
    ):
        """HIGH リスクは傾聴モードへ強制遷移"""
        mock_understanding.raw_message = "転職を考えてる"

        with patch.object(
            decision,
            "_check_mvv_alignment",
            return_value=MVVCheckResult(
                is_aligned=False,
                ng_pattern_detected=True,
                ng_pattern_type="ng_retention_critical",
                ng_response_hint="状況を聞かせて",
                risk_level="HIGH",
                enforcement_action=EnforcementAction.FORCE_LISTENING,
            ),
        ):
            result = await decision.decide(mock_understanding, mock_context)

        assert result.action == "forced_listening"
        assert result.params["risk_level"] == "HIGH"

    @pytest.mark.asyncio
    async def test_medium_risk_blocks_and_suggests(
        self, decision, mock_understanding, mock_context
    ):
        """MEDIUM リスクは代替提案へ遷移"""
        mock_understanding.raw_message = "この会社はおかしい"

        with patch.object(
            decision,
            "_check_mvv_alignment",
            return_value=MVVCheckResult(
                is_aligned=False,
                ng_pattern_detected=True,
                ng_pattern_type="ng_company_criticism",
                ng_response_hint="もう少し詳しく聞かせて",
                risk_level="MEDIUM",
                enforcement_action=EnforcementAction.BLOCK_AND_SUGGEST,
            ),
        ):
            result = await decision.decide(mock_understanding, mock_context)

        assert result.action == "suggest_alternative"
        assert result.params["ng_pattern_type"] == "ng_company_criticism"
        assert result.params["risk_level"] == "MEDIUM"
        assert "代替提案" in result.reasoning

    @pytest.mark.asyncio
    async def test_low_risk_continues_normally(
        self, decision, mock_understanding, mock_context
    ):
        """LOW リスクは通常処理を継続"""
        mock_understanding.raw_message = "給料の話"

        with patch.object(
            decision,
            "_check_mvv_alignment",
            return_value=MVVCheckResult(
                is_aligned=False,
                ng_pattern_detected=True,
                ng_pattern_type="ng_hr_authority",
                risk_level="LOW",
                enforcement_action=EnforcementAction.WARN_ONLY,
            ),
        ):
            result = await decision.decide(mock_understanding, mock_context)

        # 強制遷移しない（通常のアクションを継続）
        assert result.action != "forced_listening"
        assert result.action != "suggest_alternative"

    @pytest.mark.asyncio
    async def test_no_ng_pattern_continues_normally(
        self, decision, mock_understanding, mock_context
    ):
        """NGパターンなしは通常処理"""
        mock_understanding.raw_message = "今日のタスク教えて"

        with patch.object(
            decision,
            "_check_mvv_alignment",
            return_value=MVVCheckResult(
                is_aligned=True,
                ng_pattern_detected=False,
                enforcement_action=EnforcementAction.NONE,
            ),
        ):
            result = await decision.decide(mock_understanding, mock_context)

        assert result.action not in ["forced_listening", "suggest_alternative"]


class TestCheckMvvAlignmentEnforcement:
    """_check_mvv_alignment の enforcement_action 設定テスト"""

    @pytest.fixture
    def decision(self):
        """テスト用Decisionインスタンス"""
        return create_decision(
            capabilities={},
            org_id="test-org",
        )

    def test_critical_sets_force_listening(self, decision):
        """CRITICALリスクはFORCE_LISTENINGを設定"""
        # ng_mental_health パターンをテスト
        with patch(
            "lib.brain.decision._detect_ng_pattern"
        ) as mock_detect:
            mock_result = MagicMock()
            mock_result.detected = True
            mock_result.pattern_type = "ng_mental_health"
            mock_result.response_hint = "つらい状況ですね"
            mock_result.risk_level = MagicMock(value="CRITICAL")
            mock_detect.return_value = mock_result

            # _load_mvv_context をモック
            with patch("lib.brain.decision._mvv_context_loaded", True):
                with patch(
                    "lib.brain.decision._detect_ng_pattern",
                    mock_detect,
                ):
                    result = decision._check_mvv_alignment(
                        "死にたい", "general_conversation"
                    )

            assert result.enforcement_action == EnforcementAction.FORCE_LISTENING

    def test_high_sets_force_listening(self, decision):
        """HIGHリスクはFORCE_LISTENINGを設定"""
        with patch(
            "lib.brain.decision._detect_ng_pattern"
        ) as mock_detect:
            mock_result = MagicMock()
            mock_result.detected = True
            mock_result.pattern_type = "ng_retention_critical"
            mock_result.response_hint = "状況を聞かせて"
            mock_result.risk_level = MagicMock(value="HIGH")
            mock_detect.return_value = mock_result

            with patch("lib.brain.decision._mvv_context_loaded", True):
                with patch(
                    "lib.brain.decision._detect_ng_pattern",
                    mock_detect,
                ):
                    result = decision._check_mvv_alignment(
                        "辞めたい", "general_conversation"
                    )

            assert result.enforcement_action == EnforcementAction.FORCE_LISTENING

    def test_medium_sets_block_and_suggest(self, decision):
        """MEDIUMリスクはBLOCK_AND_SUGGESTを設定"""
        with patch(
            "lib.brain.decision._detect_ng_pattern"
        ) as mock_detect:
            mock_result = MagicMock()
            mock_result.detected = True
            mock_result.pattern_type = "ng_company_criticism"
            mock_result.response_hint = "詳しく聞かせて"
            mock_result.risk_level = MagicMock(value="MEDIUM")
            mock_detect.return_value = mock_result

            with patch("lib.brain.decision._mvv_context_loaded", True):
                with patch(
                    "lib.brain.decision._detect_ng_pattern",
                    mock_detect,
                ):
                    result = decision._check_mvv_alignment(
                        "会社がおかしい", "general_conversation"
                    )

            assert result.enforcement_action == EnforcementAction.BLOCK_AND_SUGGEST

    def test_low_sets_warn_only(self, decision):
        """LOWリスクはWARN_ONLYを設定"""
        with patch(
            "lib.brain.decision._detect_ng_pattern"
        ) as mock_detect:
            mock_result = MagicMock()
            mock_result.detected = True
            mock_result.pattern_type = "ng_hr_authority"
            mock_result.response_hint = "人事に確認を"
            mock_result.risk_level = MagicMock(value="LOW")
            mock_detect.return_value = mock_result

            with patch("lib.brain.decision._mvv_context_loaded", True):
                with patch(
                    "lib.brain.decision._detect_ng_pattern",
                    mock_detect,
                ):
                    result = decision._check_mvv_alignment(
                        "給料上げて", "general_conversation"
                    )

            assert result.enforcement_action == EnforcementAction.WARN_ONLY
