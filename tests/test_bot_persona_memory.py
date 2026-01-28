"""
ボットペルソナ記憶のテスト

テスト対象:
- パターン検出（is_bot_persona_setting）
- カテゴリ判定（detect_persona_category）
- キー・値抽出（extract_persona_key_value）

実行方法:
    pytest tests/test_bot_persona_memory.py -v
"""

import pytest
import sys
import os

# libディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.bot_persona_memory import (
    is_bot_persona_setting,
    detect_persona_category,
    extract_persona_key_value,
    PersonaCategory,
    BOT_PERSONA_PATTERNS,
    BOT_SETTING_KEYWORDS,
)


class TestBotPersonaPatternDetection:
    """ボットペルソナパターン検出のテスト"""

    @pytest.mark.parametrize("message,expected", [
        # ボット設定（True）
        ("好物は10円パン", True),
        ("ソウルくんの好物は10円パン", True),
        ("口調はウル", True),
        ("モチーフ動物は狼", True),
        ("キャラ設定として覚えて", True),
        ("語尾はウル", True),
        ("性格は明るい", True),

        # ボット設定ではない（False）
        ("田中さんの好物はラーメン", False),
        ("山田さんは営業部です", False),
        ("今日の予定を教えて", False),
        ("タスクを登録して", False),
        ("人生の軸として覚えて", False),  # これは長期記憶
    ])
    def test_pattern_detection(self, message, expected):
        """パターン検出の正確性"""
        result = is_bot_persona_setting(message)
        assert result == expected, f"Message: {message}"


class TestPersonaCategoryDetection:
    """ペルソナカテゴリ判定のテスト"""

    @pytest.mark.parametrize("message,expected_category", [
        # キャラ設定（デフォルト）
        ("モチーフ動物は狼", PersonaCategory.CHARACTER),
        ("名前はソウルくん", PersonaCategory.CHARACTER),

        # 性格
        ("性格は明るい", PersonaCategory.PERSONALITY),
        ("元気なキャラクター", PersonaCategory.PERSONALITY),

        # 好み
        ("好物は10円パン", PersonaCategory.PREFERENCE),
        ("趣味はゲーム", PersonaCategory.PREFERENCE),
    ])
    def test_category_detection(self, message, expected_category):
        """カテゴリ判定の正確性"""
        result = detect_persona_category(message)
        assert result == expected_category, f"Message: {message}"


class TestKeyValueExtraction:
    """キー・値抽出のテスト"""

    @pytest.mark.parametrize("message,expected_key,expected_value", [
        ("好物は10円パン", "好物", "10円パン"),
        ("口調はウル", "口調", "ウル"),
        ("モチーフは狼", "モチーフ", "狼"),
        ("性格は明るいです", "性格", "明るい"),
        ("ソウルくんの好物は10円パンだよ", "好物", "10円パン"),
    ])
    def test_key_value_extraction(self, message, expected_key, expected_value):
        """キー・値抽出の正確性"""
        result = extract_persona_key_value(message)
        assert result["key"] == expected_key, f"Key mismatch for: {message}"
        assert result["value"] == expected_value, f"Value mismatch for: {message}"


class TestBotPersonaVsUserMemory:
    """ボットペルソナとユーザー記憶の分離テスト"""

    def test_bot_persona_not_detected_as_user_memory(self):
        """ボット設定はユーザー長期記憶として検出されない"""
        from lib.long_term_memory import is_long_term_memory_request

        bot_settings = [
            "好物は10円パン",
            "モチーフは狼",
            "口調はウル",
        ]

        for msg in bot_settings:
            assert is_bot_persona_setting(msg) is True, f"Should be bot persona: {msg}"
            assert is_long_term_memory_request(msg) is False, f"Should NOT be user memory: {msg}"

    def test_user_memory_not_detected_as_bot_persona(self):
        """ユーザー長期記憶はボット設定として検出されない"""
        from lib.long_term_memory import is_long_term_memory_request

        user_memories = [
            "人生の軸として覚えて",
            "俺の人生のWHYは挑戦すること",  # Fixed: 「人生のWHY」パターンに合わせる
            "価値観として記憶して",
        ]

        for msg in user_memories:
            assert is_long_term_memory_request(msg) is True, f"Should be user memory: {msg}"
            assert is_bot_persona_setting(msg) is False, f"Should NOT be bot persona: {msg}"


class TestPersonMemoryVsBotPersona:
    """人物情報とボットペルソナの分離テスト"""

    def test_person_attribute_not_detected_as_bot_persona(self):
        """「〜さんの好物」は人物情報であり、ボット設定ではない"""
        person_attributes = [
            "田中さんの好物はラーメン",
            "山田様の趣味は読書",
            "鈴木くんの性格は穏やか",
        ]

        for msg in person_attributes:
            result = is_bot_persona_setting(msg)
            assert result is False, f"Should NOT be bot persona: {msg}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
