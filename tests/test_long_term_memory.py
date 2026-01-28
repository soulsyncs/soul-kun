"""
ユーザー長期記憶（プロフィール）のテスト

テスト対象:
- パターン検出（is_long_term_memory_request）
- 記憶タイプ判定（detect_memory_type）
- 内容抽出（extract_memory_content）

実行方法:
    pytest tests/test_long_term_memory.py -v
"""

import pytest
import sys
import os

# libディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.long_term_memory import (
    is_long_term_memory_request,
    detect_memory_type,
    extract_memory_content,
    MemoryType,
    LONG_TERM_MEMORY_PATTERNS,
)


class TestLongTermMemoryPatternDetection:
    """長期記憶パターン検出のテスト"""

    @pytest.mark.parametrize("message,expected", [
        # 人生の軸・WHY
        ("人生の軸として覚えて", True),
        ("これは俺の人生のWHYだ", True),
        ("生き方としてのWHYを登録", True),
        ("俺の軸として覚えておいて", True),
        ("自分の軸として記憶して", True),

        # 価値観・判断基準
        ("判断基準として覚えて", True),
        ("価値観として記憶", True),
        ("大切にしていることを覚えて", True),

        # 覚えておいてほしい表現
        ("これは目標じゃなくて軸", True),
        ("今後の判断の基準にしたい", True),

        # 通常の記憶（長期記憶ではない）
        ("田中さんは営業部です", False),
        ("これを覚えて", False),
        ("明日の予定を教えて", False),
        ("タスクを登録して", False),
    ])
    def test_pattern_detection(self, message, expected):
        """パターン検出の正確性"""
        result = is_long_term_memory_request(message)
        assert result == expected, f"Message: {message}"


class TestMemoryTypeDetection:
    """記憶タイプ判定のテスト"""

    @pytest.mark.parametrize("message,expected_type", [
        # 人生のWHY（デフォルト）
        ("人生の軸として覚えて", MemoryType.LIFE_WHY),
        ("俺のWHYを覚えて", MemoryType.LIFE_WHY),

        # 価値観
        ("判断基準として覚えて", MemoryType.VALUES),
        ("価値観を記憶して", MemoryType.VALUES),
        ("大切にしていることを覚えて", MemoryType.VALUES),

        # 行動原則
        ("信条として覚えて", MemoryType.PRINCIPLES),
        ("ポリシーを記憶して", MemoryType.PRINCIPLES),

        # 長期目標
        ("10年後の目標を覚えて", MemoryType.LONG_TERM_GOAL),
    ])
    def test_memory_type_detection(self, message, expected_type):
        """記憶タイプの判定"""
        result = detect_memory_type(message)
        assert result == expected_type


class TestContentExtraction:
    """記憶内容抽出のテスト"""

    @pytest.mark.parametrize("message,expected_contains", [
        # 指示部分が除去される
        (
            "人生の軸として覚えて。人の可能性を信じ切る側の人間で在り続ける",
            "人の可能性を信じ切る側の人間で在り続ける"
        ),
        (
            "俺の軸は挑戦し続けること",
            "挑戦し続けること"
        ),
        (
            "これは目標じゃなくて、人の成長を支援したいという想い",
            "人の成長を支援したいという想い"
        ),
    ])
    def test_content_extraction(self, message, expected_contains):
        """内容抽出の正確性"""
        result = extract_memory_content(message)
        assert expected_contains in result, f"Expected '{expected_contains}' in '{result}'"


class TestRealWorldScenario:
    """実際のユースケースのテスト"""

    def test_kazu_life_why(self):
        """カズさんの人生のWHY保存シナリオ"""
        message = """俺の軸として覚えて。
人の可能性を信じ切る側の人間で在り続けるために、自分が一番挑戦すること。
言い訳して可能性を疑う側に回る自分になるのが一番嫌。"""

        # パターン検出
        assert is_long_term_memory_request(message) is True

        # タイプ判定
        memory_type = detect_memory_type(message)
        assert memory_type == MemoryType.LIFE_WHY

        # 内容抽出
        content = extract_memory_content(message)
        assert "人の可能性を信じ切る" in content
        assert "自分が一番挑戦" in content

    def test_not_goal_but_axis(self):
        """「目標じゃなくて軸」の判定"""
        message = "これは目標じゃなくて人生の軸。成長し続けることが大切"

        assert is_long_term_memory_request(message) is True
        assert detect_memory_type(message) == MemoryType.LIFE_WHY

    def test_regular_memory_not_detected(self):
        """通常の記憶は長期記憶として検出されない"""
        messages = [
            "山田さんは経理部の部長です。覚えて",
            "田中くんの誕生日は3月5日。メモして",
            "今週の目標を設定したい",
            "タスクを追加して",
        ]

        for msg in messages:
            assert is_long_term_memory_request(msg) is False, f"Should not detect: {msg}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
