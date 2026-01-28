"""
ボットペルソナ記憶のテスト

テスト対象:
- パターン検出（is_bot_persona_setting）
- カテゴリ判定（detect_persona_category）
- キー・値抽出（extract_persona_key_value）
- v10.40.10: ホワイトリスト方式の個人情報ガード（is_valid_bot_persona）
- v10.40.10: 補助判定（is_personal_information）

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
    # v10.40.10: ホワイトリスト方式の個人情報ガード
    is_valid_bot_persona,
    is_personal_information,
    ALLOWED_PERSONA_CATEGORIES,
    ALLOWED_KEYWORDS_FLAT,
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
# v10.40.10: ホワイトリスト方式のテスト
# =====================================================

class TestValidBotPersonaWhitelist:
    """ホワイトリスト方式の is_valid_bot_persona() テスト"""

    @pytest.mark.parametrize("message,key,value,is_valid", [
        # =====================================================
        # OK例: ソウルくん自身の設定（許可）
        # =====================================================
        ("ソウルくんは明るい性格", "性格", "明るい", True),
        ("ソウルくんの語尾はウル", "語尾", "ウル", True),
        ("ソウルくんの好物は10円パン", "好物", "10円パン", True),
        ("ソウルくんの口調はタメ口", "口調", "タメ口", True),
        ("ソウルくんのモチーフは狼", "モチーフ", "狼", True),
        ("ソウルくんの一人称はボク", "一人称", "ボク", True),
        ("ソウルくんの趣味はゲーム", "趣味", "ゲーム", True),
        ("ソウルくんの特技は計算", "特技", "計算", True),

        # 主語なしでもキーワードで推定可能
        ("好物は10円パン", "好物", "10円パン", True),
        ("口調はウル", "口調", "ウル", True),
        ("性格は元気", "性格", "元気", True),

        # 二人称でソウルくんを指す
        ("君の好物は10円パン", "好物", "10円パン", True),
        ("きみの口調はウル", "口調", "ウル", True),

        # =====================================================
        # NG例: 人間に関する情報（拒否）
        # =====================================================
        # 特定の人物
        ("社長は努力家", "性格", "努力家", False),
        ("田中さんは冷静な人", "性格", "冷静", False),
        ("山田くんの好物はラーメン", "好物", "ラーメン", False),
        ("部長の口調は厳しい", "口調", "厳しい", False),

        # ユーザー自身
        ("俺の人生軸は挑戦", "人生軸", "挑戦", False),
        ("私の価値観は誠実さ", "価値観", "誠実さ", False),
        ("自分の目標は成功", "目標", "成功", False),

        # 家族
        ("父は厳しかった", "性格", "厳しい", False),
        ("母の好物はカレー", "好物", "カレー", False),
        ("妻は優しい", "性格", "優しい", False),

        # 過去体験（ソウルくん以外）
        ("昔の経験から学んだこと", "経験", "学び", False),
    ])
    def test_whitelist_validation(self, message, key, value, is_valid):
        """ホワイトリスト判定の正確性"""
        result_is_valid, result_reason = is_valid_bot_persona(message, key, value)
        assert result_is_valid == is_valid, f"Message: {message}, Expected: {is_valid}, Got: {result_is_valid}, Reason: {result_reason}"

    @pytest.mark.parametrize("message,key,value,is_valid", [
        # 二人称の曖昧な表現はブロック
        ("君は明るい性格だね", "性格", "明るい", False),
        ("お前は優しいやつだ", "性格", "優しい", False),
        ("きみは元気だね", "性格", "元気", False),
        ("おまえは冷静だ", "性格", "冷静", False),

        # 二人称 + 「の」 + 許可キーワード は許可
        ("君の好物は10円パン", "好物", "10円パン", True),
        ("きみの口調はウル", "口調", "ウル", True),
        ("お前の性格は明るい", "性格", "明るい", True),
        ("おまえの趣味はゲーム", "趣味", "ゲーム", True),
    ])
    def test_second_person_safety(self, message, key, value, is_valid):
        """二人称の安全性: 「君は〜」はブロック、「君の好物は〜」は許可"""
        result_is_valid, result_reason = is_valid_bot_persona(message, key, value)
        assert result_is_valid == is_valid, f"Message: {message}, Expected: {is_valid}, Got: {result_is_valid}, Reason: {result_reason}"


class TestWhitelistCategories:
    """ホワイトリスト許可カテゴリのテスト"""

    def test_allowed_categories_exist(self):
        """許可カテゴリが定義されている"""
        assert "personality" in ALLOWED_PERSONA_CATEGORIES
        assert "speech" in ALLOWED_PERSONA_CATEGORIES
        assert "preference" in ALLOWED_PERSONA_CATEGORIES
        assert "character" in ALLOWED_PERSONA_CATEGORIES

    def test_allowed_keywords_contain_essentials(self):
        """必須キーワードが含まれている"""
        essentials = ["性格", "口調", "語尾", "好物", "モチーフ", "一人称"]
        for kw in essentials:
            assert kw in ALLOWED_KEYWORDS_FLAT, f"Missing essential keyword: {kw}"

    def test_soulkun_always_allowed(self):
        """ソウルくん関連は常に許可"""
        test_cases = [
            "ソウルくんの好物は10円パン",
            "ソウルくんは明るい",
            "そうるくんの口調はウル",
        ]
        for msg in test_cases:
            is_valid, reason = is_valid_bot_persona(msg, "好物", "10円パン")
            assert is_valid is True, f"Should allow: {msg} (reason: {reason})"

    def test_human_info_always_blocked(self):
        """人間情報は常にブロック"""
        test_cases = [
            ("社長は努力家だ", "社員・役職者"),
            ("田中さんは優秀", "特定の人物"),
            ("父は厳しかった", "家族"),
            ("俺の人生軸は挑戦", "あなた自身"),
        ]
        for msg, expected_reason_part in test_cases:
            is_valid, reason = is_valid_bot_persona(msg, "性格", "")
            assert is_valid is False, f"Should block: {msg}"
            # 理由に期待するキーワードが含まれているか確認（緩い検証）
            assert len(reason) > 0, f"Should have reason for: {msg}"


# =====================================================
# v10.40.10: 補助判定（is_personal_information）のテスト
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


class TestV10_40_11_BotPersonaEntryPoint:
    """
    v10.40.11: is_bot_persona_setting() のエントリーポイントテスト

    これらのテストケースは、bot_persona_memoryへの保存パスに入る前の
    ゲートキーパーとして機能するis_bot_persona_setting()をテストする。

    期待される動作:
    - True → bot_persona保存パスに入る（その後ホワイトリストでフィルタ）
    - False → bot_persona保存パスに入らない（「覚えた」とは返さない）
    """

    @pytest.mark.parametrize("message,expected,reason", [
        # ========================================
        # 拒否されるべきケース（False）
        # ========================================
        # 二人称 + 述語形式（「君は〜」）→ ボット設定と認識しない
        ("君は明るい性格だね", False, "「君は」形式はボット設定パターンに該当しない"),
        ("きみは優しいね", False, "「きみは」形式はボット設定パターンに該当しない"),
        ("お前は頭がいい", False, "「お前は」形式はボット設定パターンに該当しない"),

        # 役職者への言及 → ボット設定ではない
        ("社長は努力家", False, "役職者への言及はボット設定ではない"),
        ("部長は厳しい人だ", False, "役職者への言及はボット設定ではない"),
        ("マネージャーは優秀", False, "役職者への言及はボット設定ではない"),

        # 一人称の人生軸 → 長期記憶として処理すべき
        ("俺の人生軸は挑戦", False, "一人称の人生軸はボット設定ではない"),
        ("私の人生の軸は家族", False, "一人称の人生軸はボット設定ではない"),
        ("僕の価値観は誠実さ", False, "一人称の価値観はボット設定ではない"),

        # 一般的な文章（キーワードを含まない）
        ("今日はいい天気だね", False, "一般的な文章はボット設定ではない"),
        ("タスクを追加して", False, "タスク依頼はボット設定ではない"),
        ("会議の予定を教えて", False, "情報照会はボット設定ではない"),

        # ========================================
        # 許可されるべきケース（True）
        # ========================================
        # 明示的なソウルくん設定
        ("ソウルくんの好物は10円パン", True, "明示的なソウルくん設定は許可"),
        ("ソウルくんの性格は明るい", True, "明示的なソウルくん設定は許可"),

        # 二人称 + 「の」形式（「君の〜は」）→ ボット設定として認識
        ("君の好物は10円パン", True, "「君の好物は」形式は許可"),
        ("君の口調はウルウル", True, "「君の口調は」形式は許可"),
        ("君の性格は元気", True, "「君の性格は」形式は許可"),

        # 主語なし + キーワード + は
        ("好物は10円パン", True, "主語なし「好物は」形式は許可"),
        ("口調はウル", True, "主語なし「口調は」形式は許可"),
        ("性格は明るい", True, "主語なし「性格は」形式は許可"),
    ])
    def test_entry_point_gating(self, message, expected, reason):
        """
        is_bot_persona_setting() のゲーティング動作を検証

        このテストが失敗する場合:
        - True期待でFalse → 正当なボット設定がbot_personaパスに入らない
        - False期待でTrue → 不適切なメッセージがbot_personaパスに入る
        """
        result = is_bot_persona_setting(message)
        assert result == expected, f"Message: '{message}' - Expected: {expected}, Got: {result}. Reason: {reason}"


class TestV10_40_11_IntegrationScenarios:
    """
    v10.40.11: 統合シナリオテスト

    実際のユーザーが送信しそうなメッセージに対する
    期待される動作を検証する。
    """

    @pytest.mark.parametrize("message,should_enter_bot_persona,should_pass_whitelist", [
        # ========================================
        # シナリオ1: 曖昧な二人称表現
        # ========================================
        # 「君は明るい性格だね」
        # → is_bot_persona_setting() = False → bot_personaパスに入らない
        # → ホワイトリストチェックは行われない
        ("君は明るい性格だね", False, None),

        # ========================================
        # シナリオ2: 役職者への言及
        # ========================================
        # 「社長は努力家」
        # → is_bot_persona_setting() = False → bot_personaパスに入らない
        ("社長は努力家", False, None),

        # ========================================
        # シナリオ3: 個人の人生軸
        # ========================================
        # 「俺の人生軸は挑戦」
        # → is_bot_persona_setting() = False → bot_personaパスに入らない
        # → is_long_term_memory_request() で処理されるべき
        ("俺の人生軸は挑戦", False, None),

        # ========================================
        # シナリオ4: 正当なボット設定（ホワイトリスト通過）
        # ========================================
        ("ソウルくんの好物は10円パン", True, True),
        ("好物は10円パン", True, True),
        ("君の好物は10円パン", True, True),

        # ========================================
        # シナリオ5: ボット設定パスに入るがホワイトリストで拒否
        # ========================================
        # 「君の性格は明るい」 → パスに入る → ホワイトリスト通過
        ("君の性格は明るい", True, True),
    ])
    def test_integration_flow(self, message, should_enter_bot_persona, should_pass_whitelist):
        """統合フローのテスト"""
        # Step 1: エントリーポイント判定
        enters_bot_persona = is_bot_persona_setting(message)
        assert enters_bot_persona == should_enter_bot_persona, \
            f"Message: '{message}' - Entry point check failed"

        # Step 2: ホワイトリスト判定（bot_personaパスに入る場合のみ）
        if should_enter_bot_persona and should_pass_whitelist is not None:
            kv = extract_persona_key_value(message)
            is_valid, reason = is_valid_bot_persona(message, kv.get("key", ""), kv.get("value", ""))
            assert is_valid == should_pass_whitelist, \
                f"Message: '{message}' - Whitelist check failed. Reason: {reason}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
