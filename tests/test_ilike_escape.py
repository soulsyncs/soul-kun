"""
tests/test_ilike_escape.py - ILIKE Escape境界条件テスト

Codexプレプッシュレビュー指摘対応:
- escape_ilike() の特殊文字エスケープをテスト
- search_person_by_partial_name の特殊文字入力テスト
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
# escape_ilike 単体テスト
# ================================================================


class TestEscapeIlike:
    """escape_ilike関数の境界条件テスト"""

    def test_escape_percent(self):
        """'%' がエスケープされる"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("100%達成")
        assert result == "100\\%達成"

    def test_escape_underscore(self):
        """'_' がエスケープされる"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("user_name")
        assert result == "user\\_name"

    def test_escape_backslash(self):
        """'\\' がエスケープされる"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("path\\to\\file")
        assert result == "path\\\\to\\\\file"

    def test_escape_combined_special_chars(self):
        """複数の特殊文字が同時にエスケープされる"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("100%_test\\data")
        assert result == "100\\%\\_test\\\\data"

    def test_escape_empty_string(self):
        """空文字列はそのまま返る"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("")
        assert result == ""

    def test_escape_no_special_chars(self):
        """特殊文字を含まない文字列はそのまま返る"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("田中太郎")
        assert result == "田中太郎"

    def test_escape_only_percent(self):
        """'%'のみの文字列"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("%")
        assert result == "\\%"

    def test_escape_only_underscore(self):
        """'_'のみの文字列"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("_")
        assert result == "\\_"

    def test_escape_only_backslash(self):
        """'\\'のみの文字列"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("\\")
        assert result == "\\\\"

    def test_escape_multiple_percents(self):
        """連続する'%'がすべてエスケープされる"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("%%")
        assert result == "\\%\\%"

    def test_escape_multiple_underscores(self):
        """連続する'_'がすべてエスケープされる"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("__init__")
        assert result == "\\_\\_init\\_\\_"

    def test_escape_backslash_before_percent(self):
        """'\\%' のエスケープ順序が正しい（\\が先にエスケープされる）"""
        from lib.brain.hybrid_search import escape_ilike

        # 入力: \%
        # step1: \ → \\ → 結果: \\%
        # step2: % → \% → 結果: \\\%
        result = escape_ilike("\\%")
        assert result == "\\\\\\%"

    def test_escape_backslash_before_underscore(self):
        """'\\_' のエスケープ順序が正しい"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("\\_")
        assert result == "\\\\\\_"

    def test_escape_japanese_with_special_chars(self):
        """日本語 + 特殊文字の混合"""
        from lib.brain.hybrid_search import escape_ilike

        result = escape_ilike("売上100%以上_2026年")
        assert result == "売上100\\%以上\\_2026年"


# ================================================================
# search_person_by_partial_name 特殊文字テスト
# ================================================================


class TestSearchPersonByPartialNameSpecialChars:
    """search_person_by_partial_name の特殊文字入力テスト"""

    def _make_service(self, mock_pool):
        """PersonServiceを生成するヘルパー"""
        from lib.person_service import PersonService

        return PersonService(
            get_pool=lambda: mock_pool,
            organization_id="org-test",
        )

    def test_search_with_percent_char(self):
        """'%'を含む検索語がILIKEインジェクションを起こさない"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        service = self._make_service(mock_pool)
        result = service.search_person_by_partial_name("100%")

        assert result == []

        # executeが呼ばれた引数を検証
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]  # 第2引数がパラメータdict

        # '%'がエスケープされていることを確認
        assert "\\%" in params["pattern"]
        assert params["pattern"] == "%100\\%%"

    def test_search_with_underscore_char(self):
        """'_'を含む検索語がILIKEインジェクションを起こさない"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        service = self._make_service(mock_pool)
        result = service.search_person_by_partial_name("user_name")

        assert result == []

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]

        # '_'がエスケープされていることを確認
        assert "\\_" in params["pattern"]
        assert params["pattern"] == "%user\\_name%"

    def test_search_with_backslash_char(self):
        """'\\'を含む検索語がエスケープされる"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        service = self._make_service(mock_pool)
        result = service.search_person_by_partial_name("test\\data")

        assert result == []

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]

        # '\\'がエスケープされていることを確認
        assert "\\\\" in params["pattern"]

    def test_search_with_combined_special_chars(self):
        """複合特殊文字の検索が安全に処理される"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        service = self._make_service(mock_pool)
        result = service.search_person_by_partial_name("%_\\")

        assert result == []

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]

        # すべての特殊文字がエスケープされていること
        assert params["pattern"] == "%\\%\\_\\\\%"

    def test_search_results_returned_correctly(self):
        """特殊文字検索でもDB結果が正しく返される"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("田中太郎",), ("田中花子",)]
        mock_conn.execute.return_value = mock_result

        service = self._make_service(mock_pool)
        result = service.search_person_by_partial_name("田中%")

        assert result == ["田中太郎", "田中花子"]

    def test_search_org_id_always_passed(self):
        """特殊文字検索でもorganization_idフィルタが必ず付与される"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        service = self._make_service(mock_pool)
        service.search_person_by_partial_name("100%達成")

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]

        # org_idが正しく渡されている
        assert params["org_id"] == "org-test"
