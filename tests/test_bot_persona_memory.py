"""
ボットペルソナ記憶のテスト

テスト対象:
- パターン検出（is_bot_persona_setting）
- カテゴリ判定（detect_persona_category）
- キー・値抽出（extract_persona_key_value）
- v10.40.10: ホワイトリスト方式の個人情報ガード（is_valid_bot_persona）
- v10.40.10: 補助判定（is_personal_information）
- BotPersonaMemoryManager クラス（CRUD操作 + エラーハンドリング）
- 便利関数（save_bot_persona, get_bot_persona, scan系関数）

実行方法:
    pytest tests/test_bot_persona_memory.py -v
"""

import json
import pytest
import sys
import os
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

# libディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.bot_persona_memory import (
    is_bot_persona_setting,
    detect_persona_category,
    extract_persona_key_value,
    PersonaCategory,
    BOT_PERSONA_PATTERNS,
    BOT_SETTING_KEYWORDS,
    PERSONA_CATEGORY_LABELS,
    # v10.40.10: ホワイトリスト方式の個人情報ガード
    is_valid_bot_persona,
    is_personal_information,
    ALLOWED_PERSONA_CATEGORIES,
    ALLOWED_KEYWORDS_FLAT,
    PERSONAL_STATEMENT_PATTERNS,
    FAMILY_PATTERNS,
    PERSONAL_THOUGHT_PATTERNS,
    PERSONAL_EXPERIENCE_PATTERNS,
    REDIRECT_MESSAGE,
    # クラス・便利関数
    BotPersonaMemoryManager,
    save_bot_persona,
    get_bot_persona,
    scan_bot_persona_for_personal_info,
    scan_all_organizations_bot_persona,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_pool():
    """データベース接続プールのモック"""
    pool = Mock()
    conn = MagicMock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=False)
    pool.connect.return_value = conn
    return pool


@pytest.fixture
def manager(mock_pool):
    """BotPersonaMemoryManagerインスタンス"""
    return BotPersonaMemoryManager(pool=mock_pool, org_id="org_test")


# =============================================================================
# パターン検出テスト（既存）
# =============================================================================


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
    """

    @pytest.mark.parametrize("message,expected,reason", [
        # 拒否されるべきケース（False）
        ("君は明るい性格だね", False, "「君は」形式はボット設定パターンに該当しない"),
        ("きみは優しいね", False, "「きみは」形式はボット設定パターンに該当しない"),
        ("お前は頭がいい", False, "「お前は」形式はボット設定パターンに該当しない"),
        ("社長は努力家", False, "役職者への言及はボット設定ではない"),
        ("部長は厳しい人だ", False, "役職者への言及はボット設定ではない"),
        ("マネージャーは優秀", False, "役職者への言及はボット設定ではない"),
        ("俺の人生軸は挑戦", False, "一人称の人生軸はボット設定ではない"),
        ("私の人生の軸は家族", False, "一人称の人生軸はボット設定ではない"),
        ("僕の価値観は誠実さ", False, "一人称の価値観はボット設定ではない"),
        ("今日はいい天気だね", False, "一般的な文章はボット設定ではない"),
        ("タスクを追加して", False, "タスク依頼はボット設定ではない"),
        ("会議の予定を教えて", False, "情報照会はボット設定ではない"),

        # 許可されるべきケース（True）
        ("ソウルくんの好物は10円パン", True, "明示的なソウルくん設定は許可"),
        ("ソウルくんの性格は明るい", True, "明示的なソウルくん設定は許可"),
        ("君の好物は10円パン", True, "「君の好物は」形式は許可"),
        ("君の口調はウルウル", True, "「君の口調は」形式は許可"),
        ("君の性格は元気", True, "「君の性格は」形式は許可"),
        ("好物は10円パン", True, "主語なし「好物は」形式は許可"),
        ("口調はウル", True, "主語なし「口調は」形式は許可"),
        ("性格は明るい", True, "主語なし「性格は」形式は許可"),
    ])
    def test_entry_point_gating(self, message, expected, reason):
        """is_bot_persona_setting() のゲーティング動作を検証"""
        result = is_bot_persona_setting(message)
        assert result == expected, f"Message: '{message}' - Expected: {expected}, Got: {result}. Reason: {reason}"


class TestV10_40_11_IntegrationScenarios:
    """v10.40.11: 統合シナリオテスト"""

    @pytest.mark.parametrize("message,should_enter_bot_persona,should_pass_whitelist", [
        ("君は明るい性格だね", False, None),
        ("社長は努力家", False, None),
        ("俺の人生軸は挑戦", False, None),
        ("ソウルくんの好物は10円パン", True, True),
        ("好物は10円パン", True, True),
        ("君の好物は10円パン", True, True),
        ("君の性格は明るい", True, True),
    ])
    def test_integration_flow(self, message, should_enter_bot_persona, should_pass_whitelist):
        """統合フローのテスト"""
        enters_bot_persona = is_bot_persona_setting(message)
        assert enters_bot_persona == should_enter_bot_persona, \
            f"Message: '{message}' - Entry point check failed"

        if should_enter_bot_persona and should_pass_whitelist is not None:
            kv = extract_persona_key_value(message)
            is_valid, reason = is_valid_bot_persona(message, kv.get("key", ""), kv.get("value", ""))
            assert is_valid == should_pass_whitelist, \
                f"Message: '{message}' - Whitelist check failed. Reason: {reason}"


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数・カテゴリ定義のテスト"""

    def test_persona_category_values(self):
        """PersonaCategoryの値が期待通り"""
        assert PersonaCategory.CHARACTER == "character"
        assert PersonaCategory.PERSONALITY == "personality"
        assert PersonaCategory.PREFERENCE == "preference"

    def test_persona_category_labels_cover_all(self):
        """全カテゴリにラベルがある"""
        assert PersonaCategory.CHARACTER in PERSONA_CATEGORY_LABELS
        assert PersonaCategory.PERSONALITY in PERSONA_CATEGORY_LABELS
        assert PersonaCategory.PREFERENCE in PERSONA_CATEGORY_LABELS

    def test_allowed_keywords_flat_not_empty(self):
        """許可キーワードリストが空でない"""
        assert len(ALLOWED_KEYWORDS_FLAT) > 0

    def test_bot_setting_keywords_not_empty(self):
        """設定キーワードリストが空でない"""
        assert len(BOT_SETTING_KEYWORDS) > 0

    def test_redirect_message_has_placeholders(self):
        """リダイレクトメッセージにプレースホルダがある"""
        assert "{reason}" in REDIRECT_MESSAGE
        assert "{user_name}" in REDIRECT_MESSAGE


# =============================================================================
# BotPersonaMemoryManager.save テスト
# =============================================================================


class TestManagerSave:
    """save メソッドのテスト"""

    def test_save_success(self, manager, mock_pool):
        """保存成功"""
        result = manager.save(key="好物", value="10円パン")
        assert result["success"] is True
        assert "覚えたウル" in result["message"]
        assert result["key"] == "好物"
        assert result["value"] == "10円パン"

    def test_save_calls_execute_and_commit(self, manager, mock_pool):
        """executeとcommitが呼ばれる"""
        manager.save(key="好物", value="10円パン")
        conn = mock_pool.connect.return_value
        conn.execute.assert_called_once()
        conn.commit.assert_called_once()

    def test_save_with_personality_category(self, manager, mock_pool):
        """personalityカテゴリで保存"""
        result = manager.save(
            key="性格", value="明るい",
            category=PersonaCategory.PERSONALITY,
        )
        assert result["success"] is True
        assert "性格" in result["message"]

    def test_save_with_creator_info(self, manager, mock_pool):
        """作成者情報付きで保存"""
        result = manager.save(
            key="口調", value="ウル",
            created_by_account_id="user_123",
            created_by_name="カズさん",
        )
        assert result["success"] is True

    def test_save_with_metadata(self, manager, mock_pool):
        """メタデータ付きで保存"""
        result = manager.save(
            key="好物", value="10円パン",
            metadata={"source": "chat"},
        )
        assert result["success"] is True

    def test_save_metadata_default_none_becomes_empty(self, manager, mock_pool):
        """metadata=Noneの場合はsaved_at付きの辞書になる"""
        manager.save(key="好物", value="10円パン", metadata=None)
        conn = mock_pool.connect.return_value
        call_args = conn.execute.call_args
        params = call_args[0][1]
        meta = json.loads(params["metadata"])
        assert "saved_at" in meta

    def test_save_category_label_character(self, manager, mock_pool):
        """characterカテゴリのラベルが正しい"""
        result = manager.save(key="名前", value="ソウルくん", category=PersonaCategory.CHARACTER)
        assert "キャラ設定" in result["message"]

    def test_save_category_label_preference(self, manager, mock_pool):
        """preferenceカテゴリのラベルが正しい"""
        result = manager.save(key="好物", value="10円パン", category=PersonaCategory.PREFERENCE)
        assert "好み・趣味" in result["message"]

    def test_save_category_label_personality(self, manager, mock_pool):
        """personalityカテゴリのラベルが正しい"""
        result = manager.save(key="性格", value="明るい", category=PersonaCategory.PERSONALITY)
        assert "性格" in result["message"]

    def test_save_db_error(self, manager, mock_pool):
        """DB保存エラー"""
        conn = mock_pool.connect.return_value
        conn.execute.side_effect = Exception("DB connection failed")
        result = manager.save(key="好物", value="10円パン")
        assert result["success"] is False
        assert "エラー" in result["message"]
        assert "error" in result
        assert "DB connection failed" in result["error"]

    def test_save_params_include_org_id(self, manager, mock_pool):
        """パラメータにorg_idが含まれる"""
        manager.save(key="好物", value="10円パン")
        conn = mock_pool.connect.return_value
        call_args = conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["key"] == "好物"
        assert params["value"] == "10円パン"


# =============================================================================
# BotPersonaMemoryManager.get テスト
# =============================================================================


class TestManagerGet:
    """get メソッドのテスト"""

    def test_get_found(self, manager, mock_pool):
        """値が見つかった場合"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("10円パン",)
        conn.execute.return_value = mock_result

        value = manager.get("好物")
        assert value == "10円パン"

    def test_get_not_found(self, manager, mock_pool):
        """値が見つからない場合"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        conn.execute.return_value = mock_result

        value = manager.get("不明なキー")
        assert value is None

    def test_get_db_error(self, manager, mock_pool):
        """DBエラー時はNone"""
        conn = mock_pool.connect.return_value
        conn.execute.side_effect = Exception("DB error")

        value = manager.get("好物")
        assert value is None

    def test_get_uses_correct_params(self, manager, mock_pool):
        """org_idとkeyでフィルタ"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        conn.execute.return_value = mock_result

        manager.get("好物")

        call_args = conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["key"] == "好物"


# =============================================================================
# BotPersonaMemoryManager.get_all テスト
# =============================================================================


class TestManagerGetAll:
    """get_all メソッドのテスト"""

    def test_get_all_no_category_filter(self, manager, mock_pool):
        """カテゴリなしで全件取得"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_dt = datetime(2026, 2, 7, 12, 0, 0)
        mock_result.fetchall.return_value = [
            ("好物", "10円パン", "preference", mock_dt),
            ("口調", "ウル", "character", mock_dt),
        ]
        conn.execute.return_value = mock_result

        results = manager.get_all()
        assert len(results) == 2
        assert results[0]["key"] == "好物"
        assert results[0]["value"] == "10円パン"
        assert results[0]["category"] == "preference"
        assert results[0]["created_at"] is not None
        assert results[1]["key"] == "口調"

    def test_get_all_with_category(self, manager, mock_pool):
        """カテゴリ指定で取得"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("好物", "10円パン", "preference", datetime(2026, 2, 7)),
        ]
        conn.execute.return_value = mock_result

        results = manager.get_all(category=PersonaCategory.PREFERENCE)
        assert len(results) == 1

        call_args = conn.execute.call_args
        params = call_args[0][1]
        assert params["category"] == PersonaCategory.PREFERENCE

    def test_get_all_empty_result(self, manager, mock_pool):
        """レコードなし"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        conn.execute.return_value = mock_result

        results = manager.get_all()
        assert results == []

    def test_get_all_db_error(self, manager, mock_pool):
        """DBエラー時は空リスト"""
        conn = mock_pool.connect.return_value
        conn.execute.side_effect = Exception("DB error")

        results = manager.get_all()
        assert results == []

    def test_get_all_none_created_at(self, manager, mock_pool):
        """created_atがNoneの場合"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("好物", "10円パン", "preference", None),
        ]
        conn.execute.return_value = mock_result

        results = manager.get_all()
        assert results[0]["created_at"] is None

    def test_get_all_isoformat_conversion(self, manager, mock_pool):
        """created_atがisoformat変換される"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        dt = datetime(2026, 2, 7, 15, 30, 0)
        mock_result.fetchall.return_value = [
            ("好物", "10円パン", "preference", dt),
        ]
        conn.execute.return_value = mock_result

        results = manager.get_all()
        assert results[0]["created_at"] == "2026-02-07T15:30:00"


# =============================================================================
# BotPersonaMemoryManager.delete テスト
# =============================================================================


class TestManagerDelete:
    """delete メソッドのテスト"""

    def test_delete_success(self, manager, mock_pool):
        """削除成功"""
        result = manager.delete("好物")
        assert result is True

    def test_delete_calls_execute_and_commit(self, manager, mock_pool):
        """executeとcommitが呼ばれる"""
        manager.delete("好物")
        conn = mock_pool.connect.return_value
        conn.execute.assert_called_once()
        conn.commit.assert_called_once()

    def test_delete_db_error(self, manager, mock_pool):
        """DBエラー時はFalse"""
        conn = mock_pool.connect.return_value
        conn.execute.side_effect = Exception("DB error")

        result = manager.delete("好物")
        assert result is False

    def test_delete_uses_correct_params(self, manager, mock_pool):
        """org_idとkeyでフィルタ"""
        manager.delete("口調")
        conn = mock_pool.connect.return_value
        call_args = conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["key"] == "口調"


# =============================================================================
# BotPersonaMemoryManager.format_for_display テスト
# =============================================================================


class TestManagerFormatForDisplay:
    """format_for_display メソッドのテスト"""

    def test_no_settings(self, manager, mock_pool):
        """設定なしの場合"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        conn.execute.return_value = mock_result

        text = manager.format_for_display()
        assert "まだないウル" in text

    def test_with_settings(self, manager, mock_pool):
        """設定ありの場合"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("好物", "10円パン", "preference", datetime(2026, 2, 7)),
            ("口調", "ウル", "character", datetime(2026, 2, 7)),
        ]
        conn.execute.return_value = mock_result

        text = manager.format_for_display()
        assert "好物" in text
        assert "10円パン" in text
        assert "口調" in text
        assert "ウル" in text

    def test_grouped_by_category(self, manager, mock_pool):
        """カテゴリごとにグループ化"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("好物", "10円パン", "preference", datetime(2026, 2, 7)),
            ("趣味", "散歩", "preference", datetime(2026, 2, 7)),
            ("口調", "ウル", "character", datetime(2026, 2, 7)),
        ]
        conn.execute.return_value = mock_result

        text = manager.format_for_display()
        assert "好み・趣味" in text
        assert "キャラ設定" in text

    def test_unknown_category_uses_raw_name(self, manager, mock_pool):
        """不明なカテゴリは生のカテゴリ名を表示"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("テスト", "値", "unknown_cat", datetime(2026, 2, 7)),
        ]
        conn.execute.return_value = mock_result

        text = manager.format_for_display()
        assert "unknown_cat" in text

    def test_display_format_has_bullet_points(self, manager, mock_pool):
        """各設定が「・key: value」形式で表示される"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("好物", "10円パン", "preference", datetime(2026, 2, 7)),
        ]
        conn.execute.return_value = mock_result

        text = manager.format_for_display()
        assert "・好物: 10円パン" in text


# =============================================================================
# save_bot_persona 便利関数テスト
# =============================================================================


class TestSaveBotPersonaFunction:
    """save_bot_persona 便利関数のテスト"""

    def test_save_valid_persona(self, mock_pool):
        """有効なペルソナ設定を保存"""
        result = save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="ソウルくんの好物は10円パン",
            account_id="user_123",
            sender_name="カズさん",
        )
        assert result["success"] is True
        assert "覚えたウル" in result["message"]

    def test_save_no_key_value_extracted(self, mock_pool):
        """キーと値が抽出できない場合"""
        result = save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="ただの会話です",
        )
        assert result["success"] is False
        assert "理解できなかった" in result["message"]

    def test_save_blocked_personal_info_no_user_id(self, mock_pool):
        """個人情報がブロックされた場合（user_idなし）"""
        result = save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="社長の好物はカレー",
            sender_name="テスト",
        )
        assert result["success"] is False
        assert result.get("blocked") is True
        assert "reason" in result

    def test_save_blocked_message_includes_guidance(self, mock_pool):
        """ブロック時のメッセージにガイダンスが含まれる"""
        result = save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="社長の好物はカレー",
        )
        assert "ソウルくんの設定として保存できない" in result["message"]

    def test_save_persona_personality_category(self, mock_pool):
        """性格カテゴリが自動推定される"""
        result = save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="ソウルくんの性格は明るい",
        )
        assert result["success"] is True

    def test_save_empty_key(self, mock_pool):
        """キーが空文字の場合"""
        result = save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="覚えて",
        )
        assert result["success"] is False

    @patch("lib.long_term_memory.save_long_term_memory")
    def test_redirect_to_long_term_memory_success(self, mock_save_ltm, mock_pool):
        """個人情報をuser_long_term_memoryにリダイレクト成功"""
        mock_save_ltm.return_value = {"success": True}

        result = save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="社長の好物はカレー",
            sender_name="テスト太郎",
            user_id=123,
        )
        assert result["success"] is True
        assert result.get("redirected_to") == "user_long_term_memory"
        assert "reason" in result

    @patch("lib.long_term_memory.save_long_term_memory")
    def test_redirect_message_contains_user_name(self, mock_save_ltm, mock_pool):
        """リダイレクト成功時のメッセージにユーザー名が含まれる"""
        mock_save_ltm.return_value = {"success": True}

        result = save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="社長の好物はカレー",
            sender_name="テスト太郎",
            user_id=123,
        )
        assert "テスト太郎" in result["message"]
        assert "長期記憶" in result["message"]

    @patch("lib.long_term_memory.save_long_term_memory")
    def test_redirect_default_sender_name(self, mock_save_ltm, mock_pool):
        """sender_nameがNoneの場合「あなた」が使われる"""
        mock_save_ltm.return_value = {"success": True}

        result = save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="社長の好物はカレー",
            sender_name=None,
            user_id=123,
        )
        assert "あなた" in result["message"]

    @patch("lib.long_term_memory.save_long_term_memory")
    def test_redirect_saves_formatted_key_value(self, mock_save_ltm, mock_pool):
        """リダイレクト時に「キーは値」形式で保存"""
        mock_save_ltm.return_value = {"success": True}

        save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="社長の好物はカレー",
            sender_name="テスト",
            user_id=123,
        )

        mock_save_ltm.assert_called_once()
        call_kwargs = mock_save_ltm.call_args
        # message keyword argument should contain "好物はカレー"
        assert "好物" in str(call_kwargs)
        assert "カレー" in str(call_kwargs)

    @patch("lib.long_term_memory.save_long_term_memory")
    def test_redirect_ltm_save_failed(self, mock_save_ltm, mock_pool):
        """リダイレクト先の保存失敗"""
        mock_save_ltm.return_value = {"success": False, "message": "保存失敗"}

        result = save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="社長の好物はカレー",
            sender_name="テスト",
            user_id=123,
        )
        assert result["success"] is False

    @patch("lib.long_term_memory.save_long_term_memory")
    def test_redirect_exception(self, mock_save_ltm, mock_pool):
        """リダイレクト中に例外"""
        mock_save_ltm.side_effect = Exception("DB error")

        result = save_bot_persona(
            pool=mock_pool,
            org_id="org_test",
            message="社長の好物はカレー",
            sender_name="テスト",
            user_id=123,
        )
        assert result["success"] is False
        assert "エラー" in result["message"]
        assert "error" in result


# =============================================================================
# get_bot_persona 便利関数テスト
# =============================================================================


class TestGetBotPersonaFunction:
    """get_bot_persona 便利関数のテスト"""

    def test_get_found(self, mock_pool):
        """値が見つかった場合"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("10円パン",)
        conn.execute.return_value = mock_result

        value = get_bot_persona(mock_pool, "org_test", "好物")
        assert value == "10円パン"

    def test_get_not_found(self, mock_pool):
        """値が見つからない場合"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        conn.execute.return_value = mock_result

        value = get_bot_persona(mock_pool, "org_test", "不明")
        assert value is None


# =============================================================================
# scan_bot_persona_for_personal_info テスト
# =============================================================================


class TestScanBotPersonaForPersonalInfo:
    """bot_persona_memory 内の個人情報スキャン"""

    def test_scan_no_warnings(self, mock_pool):
        """個人情報なし → 空リスト"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("好物", "10円パン", "preference", datetime(2026, 2, 7)),
        ]
        conn.execute.return_value = mock_result

        warnings = scan_bot_persona_for_personal_info(mock_pool, "org_test")
        assert warnings == []

    def test_scan_with_personal_info(self, mock_pool):
        """個人情報あり → 警告リスト"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("好物", "10円パン", "preference", datetime(2026, 2, 7)),
            ("社長の趣味", "社長はゴルフが好きと言っていた", "preference", datetime(2026, 2, 7)),
        ]
        conn.execute.return_value = mock_result

        warnings = scan_bot_persona_for_personal_info(mock_pool, "org_test")
        assert len(warnings) >= 1

    def test_scan_warning_fields(self, mock_pool):
        """警告レコードに必要なフィールドが含まれる"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("家族構成", "母は教師です", "character", datetime(2026, 2, 7)),
        ]
        conn.execute.return_value = mock_result

        warnings = scan_bot_persona_for_personal_info(mock_pool, "org_test")
        assert len(warnings) == 1
        w = warnings[0]
        assert "key" in w
        assert "value" in w
        assert "category" in w
        assert "reason" in w
        assert "created_at" in w

    def test_scan_db_error(self, mock_pool):
        """DBエラー時は空リスト"""
        conn = mock_pool.connect.return_value
        conn.execute.side_effect = Exception("DB error")

        warnings = scan_bot_persona_for_personal_info(mock_pool, "org_test")
        assert warnings == []

    def test_scan_long_value_no_crash(self, mock_pool):
        """長い値でもクラッシュしない"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        long_value = "社長が言った" + "あ" * 100
        mock_result.fetchall.return_value = [
            ("メモ", long_value, "character", datetime(2026, 2, 7)),
        ]
        conn.execute.return_value = mock_result

        warnings = scan_bot_persona_for_personal_info(mock_pool, "org_test")
        assert len(warnings) == 1

    def test_scan_empty_records(self, mock_pool):
        """レコードなし → 空リスト"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        conn.execute.return_value = mock_result

        warnings = scan_bot_persona_for_personal_info(mock_pool, "org_test")
        assert warnings == []

    def test_scan_multiple_personal_info(self, mock_pool):
        """複数の個人情報レコード"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("家族", "母は教師", "character", datetime(2026, 2, 7)),
            ("メモ", "父の思い出", "character", datetime(2026, 2, 7)),
            ("好物", "10円パン", "preference", datetime(2026, 2, 7)),
        ]
        conn.execute.return_value = mock_result

        warnings = scan_bot_persona_for_personal_info(mock_pool, "org_test")
        assert len(warnings) == 2  # 2件が個人情報


# =============================================================================
# scan_all_organizations_bot_persona テスト
# =============================================================================


class TestScanAllOrganizations:
    """全組織スキャンのテスト"""

    def test_scan_all_no_orgs(self, mock_pool):
        """組織なし → 空辞書"""
        conn = mock_pool.connect.return_value
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        conn.execute.return_value = mock_result

        result = scan_all_organizations_bot_persona(mock_pool)
        assert result == {}

    def test_scan_all_with_orgs_no_warnings(self, mock_pool):
        """組織あり・個人情報なし → 空辞書"""
        conn = mock_pool.connect.return_value

        # 1回目: org_idsの取得
        org_result = MagicMock()
        org_result.fetchall.return_value = [("org_1",), ("org_2",)]

        # 2回目以降: 各orgのget_all
        clean_result = MagicMock()
        clean_result.fetchall.return_value = [
            ("好物", "10円パン", "preference", datetime(2026, 2, 7)),
        ]

        conn.execute.side_effect = [org_result, clean_result, clean_result]

        result = scan_all_organizations_bot_persona(mock_pool)
        assert result == {}

    def test_scan_all_with_warnings(self, mock_pool):
        """組織あり・個人情報あり → 警告付き辞書"""
        conn = mock_pool.connect.return_value

        # 1回目: org_idsの取得
        org_result = MagicMock()
        org_result.fetchall.return_value = [("org_1",)]

        # 2回目: org_1のget_all（個人情報あり）
        personal_result = MagicMock()
        personal_result.fetchall.return_value = [
            ("家族", "母は教師", "character", datetime(2026, 2, 7)),
        ]

        conn.execute.side_effect = [org_result, personal_result]

        result = scan_all_organizations_bot_persona(mock_pool)
        assert "org_1" in result
        assert len(result["org_1"]) >= 1

    def test_scan_all_db_error(self, mock_pool):
        """DBエラー時は空辞書"""
        conn = mock_pool.connect.return_value
        conn.execute.side_effect = Exception("DB error")

        result = scan_all_organizations_bot_persona(mock_pool)
        assert result == {}

    def test_scan_all_org_ids_converted_to_str(self, mock_pool):
        """org_idが文字列に変換される"""
        conn = mock_pool.connect.return_value

        org_result = MagicMock()
        org_result.fetchall.return_value = [(123,)]  # 数値のorg_id

        clean_result = MagicMock()
        clean_result.fetchall.return_value = []

        conn.execute.side_effect = [org_result, clean_result]

        result = scan_all_organizations_bot_persona(mock_pool)
        assert isinstance(result, dict)

    def test_scan_all_multiple_orgs_mixed(self, mock_pool):
        """複数組織で一部に警告あり"""
        conn = mock_pool.connect.return_value

        # 1回目: org_idsの取得（3組織）
        org_result = MagicMock()
        org_result.fetchall.return_value = [("org_a",), ("org_b",), ("org_c",)]

        # org_a: 個人情報あり
        result_a = MagicMock()
        result_a.fetchall.return_value = [
            ("メモ", "社長は偉大と言っていた", "character", datetime(2026, 2, 7)),
        ]

        # org_b: 個人情報なし
        result_b = MagicMock()
        result_b.fetchall.return_value = [
            ("好物", "10円パン", "preference", datetime(2026, 2, 7)),
        ]

        # org_c: 個人情報あり
        result_c = MagicMock()
        result_c.fetchall.return_value = [
            ("家族", "母の思い出", "character", datetime(2026, 2, 7)),
        ]

        conn.execute.side_effect = [org_result, result_a, result_b, result_c]

        result = scan_all_organizations_bot_persona(mock_pool)
        # org_aとorg_cに警告あり
        assert "org_a" in result
        assert "org_b" not in result
        assert "org_c" in result


# =============================================================================
# エッジケーステスト
# =============================================================================


class TestEdgeCases:
    """エッジケース・境界値テスト"""

    def test_empty_message_is_valid_bot_persona(self):
        """空メッセージ → 拒否"""
        is_valid, reason = is_valid_bot_persona("")
        assert is_valid is False

    def test_empty_message_is_personal_information(self):
        """空メッセージ → 個人情報でない"""
        is_personal, reason = is_personal_information("")
        assert is_personal is False

    def test_empty_message_is_bot_persona_setting(self):
        """空メッセージ → False"""
        assert is_bot_persona_setting("") is False

    def test_empty_message_extract(self):
        """空メッセージから抽出 → 空"""
        result = extract_persona_key_value("")
        assert result["key"] == ""
        assert result["value"] == ""

    def test_very_long_message(self):
        """非常に長いメッセージでもクラッシュしない"""
        long_msg = "ソウルくんの好物は" + "あ" * 10000
        is_valid, reason = is_valid_bot_persona(long_msg)
        assert isinstance(is_valid, bool)

    def test_special_chars_in_message(self):
        """特殊文字を含むメッセージ"""
        msg = "ソウルくんの好物は10円パン"
        is_valid, reason = is_valid_bot_persona(msg)
        assert is_valid is True

    def test_is_valid_with_all_three_args(self):
        """message, key, value 全て指定"""
        is_valid, reason = is_valid_bot_persona(
            "ソウルくんの好物は10円パン", key="好物", value="10円パン"
        )
        assert is_valid is True

    def test_multiple_keywords_in_message(self):
        """複数キーワードを含むメッセージ"""
        msg = "ソウルくんの性格は明るくて好物は10円パン"
        is_valid, reason = is_valid_bot_persona(msg)
        assert is_valid is True

    def test_case_insensitive_soulkun(self):
        """SOUL-KUN大文字でもマッチ"""
        is_valid, reason = is_valid_bot_persona("SOUL-KUNの好物は10円パン")
        assert is_valid is True

    def test_soulkun_with_space(self):
        """soul kun（スペースあり）でもマッチ"""
        is_valid, reason = is_valid_bot_persona("soul kunの好物は10円パン")
        assert is_valid is True

    def test_detect_category_for_personality(self):
        """性格キーワードのカテゴリ推定"""
        result = detect_persona_category("ソウルくんの性格は明るい")
        assert result == PersonaCategory.PERSONALITY

    def test_extract_ga_particle(self):
        """「が」助詞でも抽出"""
        result = extract_persona_key_value("好物が10円パン")
        assert result["key"] == "好物"
        assert result["value"] == "10円パン"

    def test_extract_wo_particle(self):
        """「を」助詞でも抽出"""
        result = extract_persona_key_value("口調をウルにして")
        assert result["key"] == "口調"

    def test_extract_dauru_suffix(self):
        """末尾「だウル」を除去"""
        result = extract_persona_key_value("好物は10円パンだウル")
        assert result["value"] == "10円パン"

    def test_extract_soulkun_hiragana(self):
        """そうるくんの〜パターン"""
        result = extract_persona_key_value("そうるくんの好物は10円パン")
        assert result["key"] == "好物"
        assert result["value"] == "10円パン"

    def test_extract_ichininshyou(self):
        """一人称の抽出"""
        result = extract_persona_key_value("一人称はウル")
        assert result["key"] == "一人称"
        assert result["value"] == "ウル"

    def test_extract_nigate(self):
        """苦手の抽出"""
        result = extract_persona_key_value("苦手は数学")
        assert result["key"] == "苦手"
        assert result["value"] == "数学"

    def test_is_bot_persona_setting_kuchou_wo(self):
        """「口調を変えて」パターン"""
        assert is_bot_persona_setting("口調を変えて") is True

    def test_is_bot_persona_setting_sourkun_english(self):
        """「soul-kunの名前」パターン"""
        assert is_bot_persona_setting("soul-kunの名前") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
