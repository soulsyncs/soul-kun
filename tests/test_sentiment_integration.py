# tests/test_sentiment_integration.py
"""
Task 7: センチメント分析統合テスト

EmotionReaderの検出結果がBrainの判断に統合されることを検証する。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from lib.brain.context_builder import ContextBuilder, LLMContext
from lib.brain.observability import ContextType, ObservabilityLog, BrainObservability
from lib.brain.deep_understanding.models import (
    DetectedEmotion,
    DetectedUrgency,
    DetectedNuance,
    EmotionReadingResult,
    DeepUnderstandingInput,
)
from lib.brain.deep_understanding.constants import (
    EmotionCategory,
    UrgencyLevel,
    NuanceType,
)


# =============================================================================
# LLMContext: emotion_context フィールド
# =============================================================================


class TestLLMContextEmotionField:
    """LLMContextに感情コンテキストフィールドが追加されたことを検証"""

    def test_emotion_context_default_empty(self):
        """デフォルトは空文字"""
        ctx = LLMContext()
        assert ctx.emotion_context == ""

    def test_emotion_context_set(self):
        """感情コンテキストを設定できる"""
        ctx = LLMContext(emotion_context="【ユーザーの感情・ニュアンス】\n- 主要感情: frustrated")
        assert "frustrated" in ctx.emotion_context

    def test_to_prompt_string_includes_emotion(self):
        """to_prompt_string()に感情コンテキストが含まれる"""
        ctx = LLMContext(
            emotion_context="【ユーザーの感情・ニュアンス】\n- 主要感情: anxious"
        )
        prompt = ctx.to_prompt_string()
        assert "感情・ニュアンス" in prompt
        assert "anxious" in prompt

    def test_to_prompt_string_excludes_empty_emotion(self):
        """空の場合はプロンプトに含まれない"""
        ctx = LLMContext(emotion_context="")
        prompt = ctx.to_prompt_string()
        assert "感情・ニュアンス" not in prompt


# =============================================================================
# ContextBuilder: _get_emotion_context
# =============================================================================


class TestGetEmotionContext:
    """ContextBuilder._get_emotion_context のテスト"""

    @pytest.mark.asyncio
    async def test_no_emotion_reader(self):
        """emotion_reader が None の場合は空文字"""
        builder = ContextBuilder(pool=None, emotion_reader=None)
        result = await builder._get_emotion_context("テスト", "org1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_with_primary_emotion(self):
        """主要感情が検出された場合"""
        mock_reader = MagicMock()
        primary = DetectedEmotion(
            category=EmotionCategory.FRUSTRATED,
            intensity=0.7,
            confidence=0.85,
            indicators=["困った"],
            reasoning="frustration detected",
        )
        mock_reader.read = AsyncMock(return_value=EmotionReadingResult(
            emotions=[primary],
            primary_emotion=primary,
            urgency=None,
            nuances=[],
            original_message="困ったなあ",
            overall_confidence=0.85,
            summary="ユーザーは困惑している",
        ))

        builder = ContextBuilder(pool=None, emotion_reader=mock_reader)
        result = await builder._get_emotion_context("困ったなあ", "org1")

        assert "感情・ニュアンス" in result
        assert "frustrated" in result
        assert "85%" in result

    @pytest.mark.asyncio
    async def test_with_urgency(self):
        """緊急度が検出された場合"""
        mock_reader = MagicMock()
        urgency = DetectedUrgency(
            level=UrgencyLevel.HIGH,
            confidence=0.9,
            indicators=["急いで"],
        )
        emotion = DetectedEmotion(
            category=EmotionCategory.ANXIOUS,
            intensity=0.6,
            confidence=0.8,
            indicators=["急いで"],
        )
        mock_reader.read = AsyncMock(return_value=EmotionReadingResult(
            emotions=[emotion],
            primary_emotion=emotion,
            urgency=urgency,
            nuances=[],
            original_message="急いでお願い",
            overall_confidence=0.8,
            summary="急ぎの依頼",
        ))

        builder = ContextBuilder(pool=None, emotion_reader=mock_reader)
        result = await builder._get_emotion_context("急いでお願い", "org1")

        assert "緊急度: high" in result

    @pytest.mark.asyncio
    async def test_with_nuances(self):
        """ニュアンスが検出された場合"""
        mock_reader = MagicMock()
        emotion = DetectedEmotion(
            category=EmotionCategory.NEUTRAL,
            intensity=0.3,
            confidence=0.7,
            indicators=[],
        )
        nuance = DetectedNuance(
            nuance_type=NuanceType.FORMAL,
            confidence=0.8,
            indicators=["お願いいたします"],
        )
        mock_reader.read = AsyncMock(return_value=EmotionReadingResult(
            emotions=[emotion],
            primary_emotion=emotion,
            urgency=None,
            nuances=[nuance],
            original_message="お願いいたします",
            overall_confidence=0.7,
            summary="丁寧な依頼",
        ))

        builder = ContextBuilder(pool=None, emotion_reader=mock_reader)
        result = await builder._get_emotion_context("お願いいたします", "org1")

        assert "ニュアンス" in result
        assert "formal" in result

    @pytest.mark.asyncio
    async def test_no_emotions_detected(self):
        """感情が検出されなかった場合は空文字"""
        mock_reader = MagicMock()
        mock_reader.read = AsyncMock(return_value=EmotionReadingResult(
            emotions=[],
            primary_emotion=None,
            urgency=None,
            nuances=[],
            original_message="test",
            overall_confidence=0.0,
        ))

        builder = ContextBuilder(pool=None, emotion_reader=mock_reader)
        result = await builder._get_emotion_context("test", "org1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_emotion_reader_exception(self):
        """EmotionReaderが例外を投げた場合は空文字"""
        mock_reader = MagicMock()
        mock_reader.read = AsyncMock(side_effect=RuntimeError("reader error"))

        builder = ContextBuilder(pool=None, emotion_reader=mock_reader)
        result = await builder._get_emotion_context("test", "org1")
        assert result == ""


# =============================================================================
# Observability: SENTIMENT ContextType
# =============================================================================


class TestSentimentObservability:
    """感情検出のObservabilityログテスト"""

    def test_sentiment_context_type_exists(self):
        """SENTIMENT ContextTypeが存在する"""
        assert ContextType.SENTIMENT == "sentiment"

    def test_sentiment_emoji(self):
        """SENTIMENTの絵文字マッピング"""
        log = ObservabilityLog(
            context_type=ContextType.SENTIMENT,
            path="emotion_reader",
            applied=True,
            account_id="user1",
        )
        assert log._get_emoji() == "😊"

    def test_log_sentiment_detected(self):
        """感情検出時のログ出力"""
        obs = BrainObservability(org_id="org1")
        obs.log_context = MagicMock()

        obs.log_sentiment(
            account_id="user1",
            detected=True,
            primary_emotion="frustrated",
            urgency_level="high",
            confidence=0.85,
        )

        obs.log_context.assert_called_once()
        call_kwargs = obs.log_context.call_args[1]
        assert call_kwargs["context_type"] == ContextType.SENTIMENT
        assert call_kwargs["applied"] is True
        assert call_kwargs["details"]["emotion"] == "frustrated"
        assert call_kwargs["details"]["urgency"] == "high"
        assert call_kwargs["details"]["confidence"] == 0.85

    def test_log_sentiment_not_detected(self):
        """感情が検出されなかった場合"""
        obs = BrainObservability(org_id="org1")
        obs.log_context = MagicMock()

        obs.log_sentiment(
            account_id="user1",
            detected=False,
            confidence=0.1,
        )

        call_kwargs = obs.log_context.call_args[1]
        assert call_kwargs["applied"] is False
        assert "emotion" not in call_kwargs["details"]
        assert "urgency" not in call_kwargs["details"]
