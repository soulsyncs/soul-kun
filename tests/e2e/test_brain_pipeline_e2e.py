# tests/e2e/test_brain_pipeline_e2e.py
"""
Brain処理パイプラインのE2Eテスト

SoulkunBrainのprocess_message()を通じた
全フロー（コンテキスト取得→理解→判断→実行→記憶更新）をテストする。
APIキー不要（全外部依存をモック化）。

設計書: docs/25_llm_native_brain_architecture.md
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from datetime import datetime

from lib.brain.models import (
    BrainContext,
    BrainResponse,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
    ConversationState,
    StateType,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_pool():
    """モックDBプール"""
    pool = MagicMock()
    conn = MagicMock()
    pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connect.return_value.__exit__ = MagicMock(return_value=False)
    return pool


@pytest.fixture
def mock_brain_deps():
    """SoulkunBrain依存のモック群"""
    return {
        "understanding": AsyncMock(),
        "decision": AsyncMock(),
        "execution": AsyncMock(),
        "learning": MagicMock(),
        "memory_manager": MagicMock(),
        "memory_access": AsyncMock(),
        "state_manager": MagicMock(),
    }


# =============================================================================
# E2Eテスト: Brain処理パイプライン
# =============================================================================


@pytest.mark.e2e
class TestBrainPipelineE2E:
    """Brain処理パイプラインの統合テスト（モックベース）"""

    @pytest.mark.asyncio
    async def test_full_pipeline_greeting(self, mock_pool):
        """挨拶メッセージ: _get_context→_understand→_decide→_executeフロー"""
        with patch("lib.brain.core.SoulkunBrain.__init__", return_value=None):
            from lib.brain.core import SoulkunBrain

            brain = SoulkunBrain.__new__(SoulkunBrain)
            brain.pool = mock_pool
            brain.org_id = "org_test"
            brain._initialized = True
            brain._background_tasks = set()

            # _get_contextをモック（コンテキスト取得成功）
            mock_context = BrainContext(
                organization_id="org_test",
                room_id="room_123",
                sender_name="テストユーザー",
                sender_account_id="user_001",
            )
            brain._get_context = AsyncMock(return_value=mock_context)

            # _understand→_decide→_executeの各層
            understanding = UnderstandingResult(
                raw_message="おはようございます",
                intent="greeting",
                intent_confidence=0.95,
            )
            brain._understand = AsyncMock(return_value=understanding)

            decision = DecisionResult(
                action="general_conversation",
                params={"response_type": "greeting"},
                confidence=0.95,
                reasoning="挨拶",
            )
            brain._decide = AsyncMock(return_value=decision)

            handler_result = HandlerResult(
                success=True,
                message="おはようございますウル！",
            )
            brain._execute = AsyncMock(return_value=handler_result)

            # 外部依存
            brain.memory_manager = MagicMock()
            brain.memory_manager.is_ceo_user = MagicMock(return_value=False)
            brain.memory_manager.get_ceo_teachings_context = AsyncMock(return_value=None)
            brain.memory_manager.update_memory_safely = AsyncMock()
            brain.memory_manager.log_decision_safely = AsyncMock()
            brain.state_manager = MagicMock()
            brain.state_manager.get_current_state = AsyncMock(return_value=None)
            brain.llm_brain = None
            brain.use_chain_of_thought = False
            brain.use_self_critique = False
            brain.mask_pii = MagicMock(return_value=("", []))
            brain.observability = MagicMock()
            brain._elapsed_ms = MagicMock(return_value=10)

            with patch("lib.brain.core.message_processing.is_llm_brain_enabled", return_value=False), \
                 patch("lib.brain.core.message_processing.SAVE_DECISION_LOGS", False):
                response = await brain.process_message(
                    message="おはようございます",
                    room_id="room_123",
                    account_id="user_001",
                    sender_name="テストユーザー",
                )

            assert isinstance(response, BrainResponse)
            assert response.success is True
            brain._understand.assert_called_once()
            brain._decide.assert_called_once()
            brain._execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_with_phase2e_learnings(self, mock_pool):
        """Phase 2E学習がコンテキストに含まれること"""
        with patch("lib.brain.core.SoulkunBrain.__init__", return_value=None):
            from lib.brain.core import SoulkunBrain

            brain = SoulkunBrain.__new__(SoulkunBrain)
            brain.pool = mock_pool
            brain.org_id = "org_test"
            brain._initialized = True
            brain._background_tasks = set()

            # Phase 2E学習付きコンテキスト
            mock_context = BrainContext(
                organization_id="org_test",
                room_id="room_123",
                sender_name="テストユーザー",
                sender_account_id="user_001",
                phase2e_learnings="【覚えている別名】\n- 「麻美」は「渡部麻美」のこと",
            )
            brain._get_context = AsyncMock(return_value=mock_context)

            brain._understand = AsyncMock(return_value=UnderstandingResult(
                raw_message="麻美さんに連絡して",
                intent="general_conversation", intent_confidence=0.9,
            ))
            brain._decide = AsyncMock(return_value=DecisionResult(
                action="general_conversation", params={},
                confidence=0.9, reasoning="応答",
            ))
            brain._execute = AsyncMock(return_value=HandlerResult(
                success=True, message="応答",
            ))

            brain.memory_manager = MagicMock()
            brain.memory_manager.is_ceo_user = MagicMock(return_value=False)
            brain.memory_manager.get_ceo_teachings_context = AsyncMock(return_value=None)
            brain.memory_manager.update_memory_safely = AsyncMock()
            brain.memory_manager.log_decision_safely = AsyncMock()
            brain.state_manager = MagicMock()
            brain.state_manager.get_current_state = AsyncMock(return_value=None)
            brain.llm_brain = None
            brain.use_chain_of_thought = False
            brain.use_self_critique = False
            brain.mask_pii = MagicMock(return_value=("", []))
            brain.observability = MagicMock()
            brain._elapsed_ms = MagicMock(return_value=10)

            with patch("lib.brain.core.message_processing.is_llm_brain_enabled", return_value=False), \
                 patch("lib.brain.core.message_processing.SAVE_DECISION_LOGS", False):
                response = await brain.process_message(
                    message="麻美さんに連絡して",
                    room_id="room_123",
                    account_id="user_001",
                    sender_name="テストユーザー",
                )

            assert response.success is True
            brain._get_context.assert_called_once()
            ctx_used = brain._get_context.return_value
            assert ctx_used.phase2e_learnings == "【覚えている別名】\n- 「麻美」は「渡部麻美」のこと"


@pytest.mark.e2e
class TestOrganizationIsolationE2E:
    """組織間のデータ分離テスト"""

    @pytest.mark.asyncio
    async def test_context_uses_correct_org_id(self):
        """_get_contextが正しいorganization_idを使用すること"""
        with patch("lib.brain.core.SoulkunBrain.__init__", return_value=None):
            from lib.brain.core import SoulkunBrain

            brain = SoulkunBrain.__new__(SoulkunBrain)
            brain.org_id = "org_alpha"
            brain.pool = MagicMock()

            brain.memory_access = MagicMock()
            brain.memory_access.get_all_context = AsyncMock(return_value={})
            brain.learning = MagicMock()
            brain.learning._phase2e_learning = None

            context = await brain._get_context(
                room_id="room_1",
                user_id="user_1",
                sender_name="テスト",
                message="テスト",
            )

            assert context.organization_id == "org_alpha"

    @pytest.mark.asyncio
    async def test_different_orgs_get_different_contexts(self):
        """異なるorg_idで異なるコンテキストが生成されること"""
        with patch("lib.brain.core.SoulkunBrain.__init__", return_value=None):
            from lib.brain.core import SoulkunBrain

            contexts = {}
            for org_id in ["org_alpha", "org_beta"]:
                brain = SoulkunBrain.__new__(SoulkunBrain)
                brain.org_id = org_id
                brain.pool = MagicMock()
                brain.memory_access = MagicMock()
                brain.memory_access.get_all_context = AsyncMock(return_value={})
                brain.learning = MagicMock()
                brain.learning._phase2e_learning = None

                contexts[org_id] = await brain._get_context(
                    room_id="room_1",
                    user_id="user_1",
                    sender_name="テスト",
                )

            assert contexts["org_alpha"].organization_id == "org_alpha"
            assert contexts["org_beta"].organization_id == "org_beta"
            assert contexts["org_alpha"].organization_id != contexts["org_beta"].organization_id


@pytest.mark.e2e
class TestPhase2ELearningLoopE2E:
    """Phase 2E: フィードバック検出→学習保存→適用のフルループテスト"""

    @pytest.mark.asyncio
    async def test_feedback_detection_to_storage(self):
        """フィードバック検出→学習保存の統合フロー"""
        try:
            from lib.brain.learning_foundation import (
                BrainLearning as Phase2ELearning,
                FeedbackDetectionResult,
                LearningCategory,
            )
        except ImportError:
            pytest.skip("Phase 2E module not available")

        phase2e = Phase2ELearning(
            organization_id="org_test",
            ceo_account_ids=["ceo_001"],
        )

        # CEOが「麻美は渡部麻美のこと」と教える
        result = phase2e.detect("麻美は渡部麻美のことだよ")
        assert result is not None
        assert result.pattern_category == LearningCategory.ALIAS.value

        # 自動学習の判定
        should_learn = phase2e.should_auto_learn(result)
        assert should_learn is True

        # 学習オブジェクト抽出
        learning = phase2e.extract(
            detection_result=result,
            message="麻美は渡部麻美のことだよ",
            taught_by_account_id="ceo_001",
            taught_by_name="カズ",
            room_id="room_123",
        )
        assert learning.category == LearningCategory.ALIAS.value
        assert "麻美" in str(learning.learned_content)
        assert "渡部麻美" in str(learning.learned_content)

    @pytest.mark.asyncio
    async def test_learning_application_builds_prompt(self):
        """保存した学習がプロンプト文に変換されること"""
        try:
            from lib.brain.learning_foundation import (
                BrainLearning as Phase2ELearning,
            )
            from lib.brain.learning_foundation.models import AppliedLearning, Learning
        except ImportError:
            pytest.skip("Phase 2E module not available")

        phase2e = Phase2ELearning(
            organization_id="org_test",
        )

        # モック学習オブジェクト
        mock_learning = MagicMock(spec=Learning)
        mock_learning.category = "alias"
        mock_learning.learned_content = {"from": "麻美", "to": "渡部麻美", "description": "麻美は渡部麻美"}
        mock_learning.taught_by_name = "カズ"

        mock_applied = MagicMock(spec=AppliedLearning)
        mock_applied.learning = mock_learning

        additions = phase2e.build_context_additions([mock_applied])
        assert len(additions["aliases"]) == 1

        prompt = phase2e.build_prompt_instructions(additions)
        assert "覚えている別名" in prompt
        assert "麻美" in prompt
        assert "渡部麻美" in prompt
