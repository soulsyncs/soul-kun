# tests/performance/test_brain_performance.py
"""
Brain処理パフォーマンスベンチマーク

設計書: docs/09_implementation_standards.md セクション11.6

【目的】
- コンテキスト構築のレイテンシ測定
- 並列メッセージ処理のスループット測定
- Phase 2E学習検索のパフォーマンス検証

実行: pytest tests/performance/ -v -m performance
"""

import asyncio
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from lib.brain.context_builder import ContextBuilder, LLMContext
from lib.brain.models import BrainContext


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
def fast_context_builder(mock_pool):
    """高速モックのContextBuilder"""
    builder = ContextBuilder(pool=mock_pool)

    # 全ての内部メソッドを即座に返すようモック化
    builder._get_session_state = AsyncMock(return_value=None)
    builder._get_recent_messages = AsyncMock(return_value=[])
    builder._get_conversation_summary = AsyncMock(return_value=None)
    builder._get_user_preferences = AsyncMock(return_value=None)
    builder._get_known_persons = AsyncMock(return_value=[])
    builder._get_recent_tasks = AsyncMock(return_value=[])
    builder._get_active_goals = AsyncMock(return_value=[])
    builder._get_ceo_teachings = AsyncMock(return_value=[])
    builder._get_user_info = AsyncMock(return_value={"name": "テスト", "role": ""})
    builder._get_phase2e_learnings = AsyncMock(return_value="")

    return builder


# =============================================================================
# パフォーマンステスト
# =============================================================================


@pytest.mark.performance
class TestContextBuildPerformance:
    """コンテキスト構築のパフォーマンス"""

    @pytest.mark.asyncio
    async def test_context_build_latency(self, fast_context_builder):
        """コンテキスト構築が200ms以下で完了すること"""
        iterations = 100
        start = time.perf_counter()

        for _ in range(iterations):
            await fast_context_builder.build(
                user_id="user_001",
                room_id="room_123",
                organization_id="org_test",
                message="テストメッセージ",
            )

        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000

        assert avg_ms < 200, f"Average context build: {avg_ms:.1f}ms (limit: 200ms)"

    @pytest.mark.asyncio
    async def test_to_prompt_string_latency(self):
        """to_prompt_string変換が10ms以下で完了すること"""
        ctx = LLMContext(
            user_id="user_001",
            user_name="テストユーザー",
            user_role="member",
            organization_id="org_test",
            room_id="room_123",
            current_datetime=datetime.now(),
            phase2e_learnings="【覚えている別名】\n- 「麻美」は「渡部麻美」のこと\n" * 10,
        )

        iterations = 1000
        start = time.perf_counter()

        for _ in range(iterations):
            ctx.to_prompt_string()

        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000

        assert avg_ms < 10, f"Average to_prompt_string: {avg_ms:.2f}ms (limit: 10ms)"


@pytest.mark.performance
class TestConcurrentProcessingPerformance:
    """並列メッセージ処理のパフォーマンス"""

    @pytest.mark.asyncio
    async def test_concurrent_context_builds(self, fast_context_builder):
        """50件の並列コンテキスト構築が1秒以下で完了すること"""
        concurrency = 50

        start = time.perf_counter()
        tasks = [
            fast_context_builder.build(
                user_id=f"user_{i:03d}",
                room_id=f"room_{i:03d}",
                organization_id="org_test",
                message=f"テストメッセージ{i}",
            )
            for i in range(concurrency)
        ]
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

        assert len(results) == concurrency
        assert all(isinstance(r, LLMContext) for r in results)
        assert elapsed < 1.0, f"50 concurrent builds took {elapsed:.2f}s (limit: 1s)"

    @pytest.mark.asyncio
    async def test_concurrent_different_orgs(self, mock_pool):
        """異なるorg_idでの並列処理が互いに干渉しないこと"""
        org_ids = [f"org_{i:03d}" for i in range(10)]
        results = {}

        async def build_for_org(org_id):
            builder = ContextBuilder(pool=mock_pool)
            builder._get_session_state = AsyncMock(return_value=None)
            builder._get_recent_messages = AsyncMock(return_value=[])
            builder._get_conversation_summary = AsyncMock(return_value=None)
            builder._get_user_preferences = AsyncMock(return_value=None)
            builder._get_known_persons = AsyncMock(return_value=[])
            builder._get_recent_tasks = AsyncMock(return_value=[])
            builder._get_active_goals = AsyncMock(return_value=[])
            builder._get_ceo_teachings = AsyncMock(return_value=[])
            builder._get_user_info = AsyncMock(return_value={"name": "テスト", "role": ""})
            builder._get_phase2e_learnings = AsyncMock(return_value="")

            ctx = await builder.build(
                user_id="user_001",
                room_id="room_001",
                organization_id=org_id,
                message="テスト",
            )
            return org_id, ctx

        tasks = [build_for_org(oid) for oid in org_ids]
        pairs = await asyncio.gather(*tasks)

        for org_id, ctx in pairs:
            results[org_id] = ctx

        # 各orgのコンテキストが正しいorg_idを持つこと
        for org_id in org_ids:
            assert results[org_id].organization_id == org_id


@pytest.mark.performance
class TestPhase2EPerformance:
    """Phase 2E学習機能のパフォーマンス"""

    @pytest.mark.asyncio
    async def test_learning_lookup_latency(self, mock_pool):
        """Phase 2E学習検索が100ms以下で完了すること（モック）"""
        mock_learning = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_learning.find_applicable.return_value = [MagicMock()]
        mock_learning.build_context_additions.return_value = {"aliases": []}
        mock_learning.build_prompt_instructions.return_value = "test"

        builder = ContextBuilder(
            pool=mock_pool,
            phase2e_learning=mock_learning,
        )

        iterations = 100
        start = time.perf_counter()

        for _ in range(iterations):
            await builder._get_phase2e_learnings("テスト", "user_001", "room_123")

        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000

        assert avg_ms < 100, f"Average learning lookup: {avg_ms:.2f}ms (limit: 100ms)"

    def test_prompt_instructions_with_many_learnings(self):
        """大量の学習がある場合のプロンプト構築パフォーマンス"""
        try:
            from lib.brain.learning_foundation import BrainLearning as Phase2ELearning
            from lib.brain.learning_foundation.models import AppliedLearning, Learning
        except ImportError:
            pytest.skip("Phase 2E module not available")

        phase2e = Phase2ELearning(organization_id="org_test")

        # 100件の学習をシミュレート
        applied_learnings = []
        for i in range(100):
            mock_learning = MagicMock(spec=Learning)
            mock_learning.category = "fact"
            mock_learning.learned_content = {
                "subject": f"事実{i}",
                "value": f"値{i}",
                "description": f"テスト事実{i}: これはテストデータです",
                "source": "テスト",
            }
            mock_learning.taught_by_name = "テスト"
            mock_applied = MagicMock(spec=AppliedLearning)
            mock_applied.learning = mock_learning
            applied_learnings.append(mock_applied)

        iterations = 100
        start = time.perf_counter()

        for _ in range(iterations):
            additions = phase2e.build_context_additions(applied_learnings)
            phase2e.build_prompt_instructions(additions)

        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000

        assert avg_ms < 50, f"100 learnings prompt build: {avg_ms:.2f}ms (limit: 50ms)"
