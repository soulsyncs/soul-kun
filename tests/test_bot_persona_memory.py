"""
ボットペルソナ記憶のテスト

テスト対象:
- パターン検出（is_bot_persona_setting）
- カテゴリ判定（detect_persona_category）
- キー・値抽出（extract_persona_key_value）
- v10.40.10: 個人情報ガード（is_personal_information）

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
    # v10.40.10: 個人情報ガード
    is_personal_information,
    PERSONAL_STATEMENT_PATTERNS,
    FAMILY_PATTERNS,
    PERSONAL_THOUGHT_PATTERNS,
    PERSONAL_EXPERIENCE_PATTERNS,
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


# =====================================================
# v10.40.10: 個人情報ガードのテスト
# =====================================================

class TestPersonalInformationGuard:
    """個人情報ガードのテスト"""

    @pytest.mark.parametrize("message,value,is_personal,reason_contains", [
        # 個人発言パターン（ブロック）
        ("社長は常に挑戦しろと言っていた", "", True, "個人の発言"),
        ("部長が言うには明日から出張だ", "", True, "個人の発言"),
        ("田中さんは努力家です", "", True, "個人の発言"),
        ("山田さんの意見として覚えて", "", True, "個人の発言"),
        ("彼は成功すると言っていた", "", True, "個人の発言"),
        ("あの人の発言を覚えて", "", True, "個人の発言"),

        # 家族情報パターン（ブロック）
        ("父は厳しい人だった", "", True, "家族"),
        ("母の教えを覚えて", "", True, "家族"),
        ("妻は優しい", "", True, "家族"),
        ("子供の名前は太郎", "", True, "家族"),
        ("家族は大切だ", "", True, "家族"),
        ("お父さんの言葉を覚えて", "", True, "家族"),

        # 個人の人生軸・思想パターン（ブロック）
        ("私の人生軸は挑戦", "", True, "人生軸"),
        ("俺の価値観は誠実さ", "", True, "人生軸"),
        ("自分の信念として覚えて", "", True, "人生軸"),
        ("田中さんの人生軸を覚えて", "", True, "人生軸"),
        ("ライフビジョンとして保存して", "", True, "人生軸"),

        # 個人の過去体験パターン（ブロック）
        ("昔は大変だった", "", True, "過去体験"),
        ("学生時代に経験したこと", "", True, "過去体験"),
        ("以前、困難を乗り越えた", "", True, "過去体験"),
        ("思い出として覚えて", "", True, "過去体験"),
        ("私が経験したことを覚えて", "", True, "過去体験"),

        # 正当なボット設定（許可）
        ("好物は10円パン", "", False, ""),
        ("口調はウル", "", False, ""),
        ("モチーフ動物は狼", "", False, ""),
        ("キャラクター設定として覚えて", "", False, ""),
        ("語尾はだウル", "", False, ""),
        ("性格は元気", "", False, ""),
        ("一人称はボク", "", False, ""),
        ("ソウルくんの好物は10円パン", "", False, ""),
    ])
    def test_personal_information_detection(self, message, value, is_personal, reason_contains):
        """個人情報検出の正確性"""
        result_is_personal, result_reason = is_personal_information(message, value)
        assert result_is_personal == is_personal, f"Message: {message}"
        if is_personal:
            assert reason_contains in result_reason, f"Reason should contain '{reason_contains}', got: {result_reason}"


class TestPersonalInformationPatterns:
    """個人情報パターンの網羅テスト"""

    def test_personal_statement_patterns_block(self):
        """個人発言パターンがブロックされる"""
        test_cases = [
            "社長は努力が大事と言っていた",
            "マネージャーの方針として覚えて",
            "リーダーが話した内容",
            "鈴木さんは優秀だ",
            "佐藤様のご意見",
            "彼女は頑張っている",
            "あの人が言うには",
        ]
        for msg in test_cases:
            is_personal, _ = is_personal_information(msg)
            assert is_personal is True, f"Should block: {msg}"

    def test_family_patterns_block(self):
        """家族情報パターンがブロックされる"""
        test_cases = [
            "父の教え",
            "母は優しかった",
            "妻の好物はカレー",
            "夫は仕事人間",
            "息子の将来",
            "娘の夢",
            "兄は医者",
            "姉のアドバイス",
            "弟の性格",
            "妹は元気",
            "祖父の思い出",
            "おばあちゃんの話",
            "パパの仕事",
            "ママの手料理",
            "親戚の集まり",
        ]
        for msg in test_cases:
            is_personal, _ = is_personal_information(msg)
            assert is_personal is True, f"Should block: {msg}"

    def test_personal_thought_patterns_block(self):
        """個人思想パターンがブロックされる"""
        test_cases = [
            "私の人生軸",
            "俺の価値観",
            "僕の信念",
            "自分の夢",
            "わたしの目標",
            "田中さんの人生軸",
            "山田くんの価値観",
            "ライフビジョン",
            "生き方として覚えて",
        ]
        for msg in test_cases:
            is_personal, _ = is_personal_information(msg)
            assert is_personal is True, f"Should block: {msg}"

    def test_personal_experience_patterns_block(self):
        """個人体験パターンがブロックされる"""
        test_cases = [
            "昔は苦労した",
            "以前の経験",
            "若い頃に学んだこと",
            "学生時代、頑張った",
            "子供の頃、楽しかった",
            "経験したことを覚えて",
            "体験したことを記憶して",
            "思い出を保存して",
            "私が体験したこと",
        ]
        for msg in test_cases:
            is_personal, _ = is_personal_information(msg)
            assert is_personal is True, f"Should block: {msg}"

    def test_valid_bot_persona_not_blocked(self):
        """正当なボット設定はブロックされない"""
        valid_settings = [
            "好物は10円パン",
            "口調はウル",
            "モチーフ動物は狼",
            "語尾はだウル",
            "性格は明るい",
            "一人称はボク",
            "特技はプログラミング",
            "苦手は早起き",
            "キャラクターは狼",
            "ソウルくんの好物は10円パン",
            "ソウルくんの口調はウル",
        ]
        for msg in valid_settings:
            is_personal, reason = is_personal_information(msg)
            assert is_personal is False, f"Should NOT block: {msg} (reason: {reason})"


class TestSaveWithPersonalInfoGuard:
    """個人情報ガード付き保存のテスト（モック使用）"""

    def test_redirect_response_format(self):
        """リダイレクト時のレスポンス形式"""
        from lib.bot_persona_memory import REDIRECT_MESSAGE

        # テンプレートが正しく置換されることを確認
        formatted = REDIRECT_MESSAGE.format(
            reason="特定の個人の発言・意見",
            user_name="テストユーザー"
        )
        assert "個人的な情報" in formatted
        assert "特定の個人の発言・意見" in formatted
        assert "テストユーザー" in formatted
        assert "長期記憶" in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
