"""
ユーザー長期記憶（プロフィール）のテスト

テスト対象:
- パターン検出（is_long_term_memory_request）
- 記憶タイプ判定（detect_memory_type）
- 内容抽出（extract_memory_content）
- v10.40.9: MemoryScope、アクセス制御

実行方法:
    pytest tests/test_long_term_memory.py -v
"""

import pytest
import sys
import os
from unittest.mock import MagicMock

# libディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.long_term_memory import (
    is_long_term_memory_request,
    detect_memory_type,
    extract_memory_content,
    MemoryType,
    MemoryScope,  # v10.40.9
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


class TestMemoryScope:
    """v10.40.9: メモリスコープのテスト"""

    def test_scope_constants(self):
        """スコープ定数が正しく定義されている"""
        assert MemoryScope.PRIVATE == "PRIVATE"
        assert MemoryScope.ORG_SHARED == "ORG_SHARED"

    def test_default_scope_is_private(self):
        """デフォルトスコープがPRIVATEである"""
        # save_long_term_memoryのデフォルト引数を確認
        from lib.long_term_memory import save_long_term_memory
        import inspect
        sig = inspect.signature(save_long_term_memory)
        scope_param = sig.parameters.get("scope")
        assert scope_param is not None
        assert scope_param.default == MemoryScope.PRIVATE


class TestBotPersonaDetection:
    """v10.40.9: ボットペルソナ検出のテスト"""

    @pytest.fixture
    def bot_persona_available(self):
        """bot_persona_memoryが利用可能かどうか"""
        try:
            from lib.bot_persona_memory import is_bot_persona_setting
            return True
        except ImportError:
            pytest.skip("bot_persona_memory not available")

    @pytest.mark.parametrize("message,expected", [
        # ボットペルソナ設定
        ("好物は10円パン", True),
        ("ソウルくんの口調はウル", True),
        ("モチーフ動物は狼", True),
        ("キャラ設定：性格は明るい", True),

        # ボット設定ではない（人物情報）
        ("田中さんの好物はラーメン", False),
        ("山田さんは営業部です", False),

        # ボット設定ではない（長期記憶）
        ("人生の軸として覚えて", False),
        ("俺の価値観は挑戦", False),
    ])
    def test_bot_persona_detection(self, message, expected, bot_persona_available):
        """ボットペルソナ設定の検出"""
        from lib.bot_persona_memory import is_bot_persona_setting
        result = is_bot_persona_setting(message)
        assert result == expected, f"Message: {message}"


class TestSecurityAccessControl:
    """v10.40.9: セキュリティ・アクセス制御のテスト"""

    def test_private_scope_blocks_other_users(self):
        """PRIVATEスコープは他ユーザーからアクセスできない"""
        # これはDBを使用するため、統合テストとして実装
        # ユニットテストレベルでは、get_all_for_requester()のロジックを確認
        pass  # 統合テストで実装

    def test_org_shared_allows_same_org_users(self):
        """ORG_SHAREDは同一組織のユーザーがアクセスできる"""
        # これはDBを使用するため、統合テストとして実装
        pass  # 統合テストで実装

    def test_memory_separation_intent(self):
        """メモリ分離の意図確認（ボットvs ユーザー）"""
        from lib.long_term_memory import is_long_term_memory_request

        # ユーザーの人生軸 → user_long_term_memory
        user_memory_messages = [
            "俺の軸として覚えて",
            "人生のWHYを登録",
            "価値観として記憶",
        ]
        for msg in user_memory_messages:
            assert is_long_term_memory_request(msg) is True, f"Should be user memory: {msg}"

        # ボット設定 → bot_persona_memory（長期記憶ではない）
        bot_setting_messages = [
            "好物は10円パン",
            "モチーフは狼",
        ]
        for msg in bot_setting_messages:
            assert is_long_term_memory_request(msg) is False, f"Should NOT be user memory: {msg}"


class TestV10_40_12_PatternExtension:
    """
    v10.40.12: 人生軸・価値観検知パターン拡張のテスト

    追加されたパターン:
    - 「人生軸は」（「の」なしでも検出）
    - 一人称 + 軸/価値観/信条
    - 「大事にしているのは」「大切にしていることは」
    """

    @pytest.mark.parametrize("message,expected,reason", [
        # ========================================
        # 検出されるべきケース（True）
        # ========================================
        # 人生軸パターン（v10.40.12で強化）
        ("俺の人生軸は挑戦", True, "一人称 + 人生軸"),
        ("私の人生軸は家族", True, "一人称 + 人生軸"),
        ("僕の人生軸は成長", True, "一人称 + 人生軸"),
        ("人生軸は挑戦", True, "人生軸（「の」なし）"),
        ("人生の軸は成長", True, "人生の軸"),
        ("自分の軸は誠実さ", True, "自分の軸"),
        ("俺の軸は挑戦", True, "一人称 + 軸"),
        ("私の軸は家族", True, "一人称 + 軸"),

        # 価値観パターン（v10.40.12で強化）
        ("俺の価値観は誠実さ", True, "一人称 + 価値観"),
        ("私の価値観は家族第一", True, "一人称 + 価値観"),
        ("価値観は正直であること", True, "価値観は"),

        # 信条パターン（v10.40.12で強化）
        ("俺の信条は全力投球", True, "一人称 + 信条"),
        ("私の信条は諦めないこと", True, "一人称 + 信条"),
        ("信条は常に前向き", True, "信条は"),
        ("俺の信念は挑戦", True, "一人称 + 信念"),
        ("私の信念は誠実さ", True, "一人称 + 信念"),

        # 大切にしている表現（v10.40.12で追加）
        ("大事にしているのは家族", True, "大事にしているのは"),
        ("大切にしていることは信頼", True, "大切にしていることは"),
        ("大切にしているものは時間", True, "大切にしているものは"),
        ("大事にしていることは挑戦", True, "大事にしていることは"),

        # ========================================
        # 検出されないべきケース（False）
        # ========================================
        # 一般的な文章
        ("今日はいい天気だね", False, "一般的な文章"),
        ("タスクを追加して", False, "タスク依頼"),
        ("会議の予定を教えて", False, "情報照会"),

        # ソウルくん設定（bot_personaに行くべき）
        ("ソウルくんの性格は優しい", False, "ボット設定"),
        ("好物は10円パン", False, "ボット設定"),
        ("口調はウル", False, "ボット設定"),

        # 人物情報（person_attributesに行くべき）
        ("田中さんは営業部", False, "人物情報"),
        ("山田くんの好物はラーメン", False, "人物情報"),
    ])
    def test_v10_40_12_pattern_detection(self, message, expected, reason):
        """v10.40.12のパターン拡張テスト"""
        result = is_long_term_memory_request(message)
        assert result == expected, f"Message: '{message}' - Expected: {expected}, Got: {result}. Reason: {reason}"


class TestBotPersonaVsLongTermMemorySeparation:
    """
    bot_persona_memory と user_long_term_memory の完全分離テスト

    v10.40.12: 両者は完全に別ルートで処理される
    """

    def test_user_life_axis_goes_to_long_term(self):
        """ユーザーの人生軸は長期記憶として検出される"""
        user_axis_messages = [
            "俺の人生軸は挑戦",
            "私の価値観は誠実さ",
            "大事にしているのは家族",
            "信条は諦めないこと",
            "僕の軸は成長",
        ]
        for msg in user_axis_messages:
            result = is_long_term_memory_request(msg)
            assert result == True, f"Should be detected as long-term memory: {msg}"

    def test_bot_persona_not_detected_as_long_term(self):
        """ボット設定は長期記憶として検出されない"""
        from lib.bot_persona_memory import is_bot_persona_setting

        bot_persona_messages = [
            "ソウルくんの性格は優しい",
            "ソウルくんの好物は10円パン",
            "好物は10円パン",
            "口調はウル",
            "語尾はだウル",
            "モチーフ動物は狼",
        ]
        for msg in bot_persona_messages:
            # bot_personaとして検出される
            assert is_bot_persona_setting(msg) == True, f"Should be bot_persona: {msg}"
            # 長期記憶としては検出されない
            assert is_long_term_memory_request(msg) == False, f"Should NOT be long-term: {msg}"

    def test_soulkun_personality_goes_to_bot_persona(self):
        """「ソウルくんの性格は優しい」はbot_persona_memoryに保存される"""
        from lib.bot_persona_memory import is_bot_persona_setting

        message = "ソウルくんの性格は優しい"

        # bot_personaとして検出される
        assert is_bot_persona_setting(message) == True

        # 長期記憶としては検出されない
        assert is_long_term_memory_request(message) == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestLongTermMemoryManager:
    """LongTermMemoryManagerのユニットテスト"""

    def _mock_pool_with_rows(self, rows):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
        return mock_pool, mock_conn

    def test_save_success_returns_message_and_metadata(self, monkeypatch):
        from lib import long_term_memory as ltm
        monkeypatch.setattr(ltm, "_ensure_long_term_table", lambda pool: None)

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        manager = ltm.LongTermMemoryManager(
            pool=mock_pool,
            org_id="11111111-1111-1111-1111-111111111111",
            user_id="22222222-2222-2222-2222-222222222222",
            user_name="カズ"
        )

        result = manager.save("挑戦し続ける", memory_type=ltm.MemoryType.VALUES, scope=ltm.MemoryScope.ORG_SHARED)

        assert result["success"] is True
        assert result["memory_type"] == ltm.MemoryType.VALUES
        assert result["scope"] == ltm.MemoryScope.ORG_SHARED
        assert "カズ" in result["message"]
        assert "挑戦し続ける" in result["message"]

    def test_get_all_for_requester_owner_returns_rows(self):
        from lib import long_term_memory as ltm
        rows = [
            ("id1", ltm.MemoryType.LIFE_WHY, "content", {}, None, None, ltm.MemoryScope.PRIVATE)
        ]
        mock_pool, _ = self._mock_pool_with_rows(rows)
        manager = ltm.LongTermMemoryManager(
            pool=mock_pool,
            org_id="org",
            user_id="owner",
            user_name="あなた"
        )

        result = manager.get_all_for_requester(requester_user_id="owner")
        assert len(result) == 1
        assert result[0]["memory_type"] == ltm.MemoryType.LIFE_WHY

    def test_get_all_for_requester_non_owner_filters_scope(self):
        from lib import long_term_memory as ltm
        rows = [
            ("id2", ltm.MemoryType.VALUES, "content", {}, None, None, ltm.MemoryScope.ORG_SHARED)
        ]
        mock_pool, _ = self._mock_pool_with_rows(rows)
        manager = ltm.LongTermMemoryManager(
            pool=mock_pool,
            org_id="org",
            user_id="owner",
            user_name="あなた"
        )

        result = manager.get_all_for_requester(requester_user_id="other")
        assert len(result) == 1
        assert result[0]["scope"] == ltm.MemoryScope.ORG_SHARED

    def test_format_for_display_with_scope(self, monkeypatch):
        from lib import long_term_memory as ltm

        manager = ltm.LongTermMemoryManager(
            pool=MagicMock(),
            org_id="org",
            user_id="user",
            user_name="あなた"
        )

        monkeypatch.setattr(manager, "get_all", lambda: [
            {
                "memory_type": ltm.MemoryType.VALUES,
                "content": "挑戦",
                "scope": ltm.MemoryScope.ORG_SHARED,
            }
        ])

        output = manager.format_for_display(show_scope=True)
        assert "【価値観】" in output
        assert "[共有]" in output
        assert "挑戦" in output
