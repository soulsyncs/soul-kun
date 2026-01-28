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


class TestV10410PatternExpansion:
    """v10.41.0: パターン拡張のテスト"""

    @pytest.mark.parametrize("message,expected", [
        # 「人生軸」（「の」無し）でも検出される
        ("人生軸として覚えて", True),
        ("人生軸を保存", True),
        ("これが俺の人生軸だ", True),

        # 「人生の軸」（「の」あり）も引き続き検出
        ("人生の軸として覚えて", True),
        ("人生のWHYを覚えて", True),

        # プロフィール保存要求
        ("プロフィールに保存して", True),
        ("プロフィールへ記憶して", True),

        # 長期記憶保存要求
        ("長期記憶に保存して", True),
        ("長期記憶として覚えて", True),

        # WHY保存要求
        ("WHYを長期で覚えて", True),
        ("ワイを覚えて", True),

        # 目標との区別
        ("目標じゃなくて人生軸", True),
        ("これは目標ではない、軸だ", True),
    ])
    def test_expanded_patterns(self, message, expected):
        """v10.41.0 拡張パターンの検出"""
        result = is_long_term_memory_request(message)
        assert result == expected, f"Message: {message}, Expected: {expected}, Got: {result}"

    def test_goal_setting_confirm_redirect_scenario(self):
        """目標設定confirm中の長期記憶要求シナリオ"""
        # このメッセージはgoal_setting confirm stepで検出される
        message = "これは目標じゃなくて、人生軸として覚えて。プロフィールのメモリに保存して"

        # パターン検出
        assert is_long_term_memory_request(message) is True

        # タイプ判定（人生の軸/WHY）
        memory_type = detect_memory_type(message)
        assert memory_type == MemoryType.LIFE_WHY

    def test_ok_but_feedback_not_long_term_memory(self):
        """「OK、合ってるけどフィードバックして」は長期記憶ではない"""
        message = "OK、合ってるけどフィードバックして"

        # これは長期記憶要求ではない
        assert is_long_term_memory_request(message) is False

    def test_short_message_not_long_term_memory(self):
        """短文（例：うーん）は長期記憶ではない"""
        messages = ["うーん", "微妙", "OK", "はい", "いいよ"]

        for msg in messages:
            assert is_long_term_memory_request(msg) is False, f"Should not detect: {msg}"


class TestGoalSettingIntegration:
    """goal_setting.pyとの統合テスト"""

    def test_goal_setting_imports_long_term_memory(self):
        """goal_setting.pyがlong_term_memory検出関数をインポートできる"""
        try:
            # goal_setting.pyのインポートを確認
            import lib.goal_setting as gs

            # is_long_term_memory_requestが利用可能か確認
            assert hasattr(gs, 'is_long_term_memory_request') or \
                   'is_long_term_memory_request' in dir(gs), \
                   "is_long_term_memory_request should be available in goal_setting"
        except ImportError as e:
            # インポートエラーの場合はスキップ
            pytest.skip(f"goal_setting import not available: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
