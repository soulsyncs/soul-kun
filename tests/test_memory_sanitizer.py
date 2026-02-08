# tests/test_memory_sanitizer.py
"""
メモリ可視化・PIIマスキングのユニットテスト

Phase 1-C: メモリ可視化UXのテスト
"""

import pytest
from unittest.mock import Mock, MagicMock

from lib.brain.memory_sanitizer import (
    mask_pii,
    get_category_label,
    SanitizedMemory,
    MemoryViewResult,
    MemoryViewer,
    CATEGORY_LABELS,
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
def viewer(mock_pool):
    """MemoryViewerインスタンス"""
    return MemoryViewer(pool=mock_pool, org_id="org_test")


# =============================================================================
# PIIマスキングテスト
# =============================================================================


class TestMaskPII:
    """PIIマスキングのテスト"""

    def test_mask_phone_with_hyphens(self):
        """ハイフン付き電話番号のマスキング"""
        result, masked = mask_pii("連絡先は090-1234-5678です")
        assert "[PHONE]" in result
        assert "090-1234-5678" not in result
        assert masked is True

    def test_mask_phone_without_hyphens(self):
        """ハイフンなし電話番号のマスキング"""
        result, masked = mask_pii("電話09012345678")
        assert "[PHONE]" in result
        assert masked is True

    def test_mask_email(self):
        """メールアドレスのマスキング"""
        result, masked = mask_pii("メールはtanaka@example.com")
        assert "[EMAIL]" in result
        assert "tanaka@example.com" not in result
        assert masked is True

    def test_mask_password(self):
        """パスワードのマスキング"""
        result, masked = mask_pii("パスワード: secret123")
        assert "[PASSWORD]" in result
        assert "secret123" not in result
        assert masked is True

    def test_mask_api_key(self):
        """APIキーのマスキング"""
        result, masked = mask_pii("APIキー: sk-xxxx")
        assert "[API_KEY]" in result
        assert masked is True

    def test_mask_salary(self):
        """給与情報のマスキング"""
        result, masked = mask_pii("給与 500000")
        assert "[SALARY]" in result
        assert masked is True

    def test_no_masking_normal_text(self):
        """通常テキストはマスキングなし"""
        text = "田中さんは営業部の部長です"
        result, masked = mask_pii(text)
        assert result == text
        assert masked is False

    def test_empty_string(self):
        """空文字列"""
        result, masked = mask_pii("")
        assert result == ""
        assert masked is False

    def test_multiple_pii_types(self):
        """複数種類のPIIを同時マスキング"""
        text = "連絡先: 090-1234-5678, メール: test@example.com"
        result, masked = mask_pii(text)
        assert "[PHONE]" in result
        assert "[EMAIL]" in result
        assert masked is True


# =============================================================================
# カテゴリラベルテスト
# =============================================================================


class TestCategoryLabel:
    """カテゴリ表示名のテスト"""

    def test_known_categories(self):
        """既知カテゴリは日本語名を返す"""
        assert get_category_label("fact") == "事実"
        assert get_category_label("preference") == "好み・設定"
        assert get_category_label("commitment") == "約束・コミットメント"
        assert get_category_label("decision") == "決定事項"

    def test_unknown_category(self):
        """未知カテゴリはそのまま返す"""
        assert get_category_label("unknown_cat") == "unknown_cat"


# =============================================================================
# データクラステスト
# =============================================================================


class TestDataClasses:
    """データクラスのテスト"""

    def test_sanitized_memory_to_dict(self):
        """SanitizedMemoryのシリアライズ"""
        mem = SanitizedMemory(
            id="1",
            category="fact",
            category_label="事実",
            title="田中さん",
            content="営業部長",
            confidence=0.9,
            source="auto_flush",
        )
        d = mem.to_dict()
        assert d["category"] == "fact"
        assert d["title"] == "田中さん"

    def test_memory_view_result_to_dict(self):
        """MemoryViewResultのシリアライズ"""
        result = MemoryViewResult(
            memories=[
                SanitizedMemory(id="1", category="fact", category_label="事実",
                                title="T", content="C"),
            ],
            total_count=1,
            masked_count=0,
        )
        d = result.to_dict()
        assert d["total_count"] == 1
        assert len(d["memories"]) == 1

    def test_display_text_empty(self):
        """空の場合のテキスト表示"""
        result = MemoryViewResult()
        assert "覚えている情報はありません" in result.to_display_text()

    def test_display_text_with_items(self):
        """記憶ありの場合のテキスト表示"""
        result = MemoryViewResult(
            memories=[
                SanitizedMemory(id="1", category="fact", category_label="事実",
                                title="田中さん", content="営業部長"),
                SanitizedMemory(id="2", category="preference", category_label="好み・設定",
                                title="報告スタイル", content="簡潔に"),
            ],
            total_count=2,
        )
        text = result.to_display_text()
        assert "2件" in text
        assert "[事実]" in text
        assert "[好み・設定]" in text
        assert "田中さん" in text


# =============================================================================
# メモリ閲覧テスト
# =============================================================================


class TestMemoryViewer:
    """メモリ閲覧のテスト"""

    def test_get_user_memories_preferences(self, viewer, mock_pool):
        """user_preferencesからの記憶取得"""
        conn = mock_pool.connect.return_value
        # preferences結果
        pref_result = MagicMock()
        pref_result.fetchall.return_value = [
            ("11111111-1111-1111-1111-111111111111", "communication", "報告スタイル", "簡潔に", 0.8, "auto_flush"),
        ]
        # knowledge結果（空）
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = []
        conn.execute.side_effect = [pref_result, knowledge_result]

        result = viewer.get_user_memories("user123")
        assert result.total_count == 1
        assert result.memories[0].category == "communication"
        assert result.memories[0].content == "簡潔に"

    def test_get_user_memories_knowledge(self, viewer, mock_pool):
        """soulkun_knowledgeからの記憶取得"""
        conn = mock_pool.connect.return_value
        pref_result = MagicMock()
        pref_result.fetchall.return_value = []
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = [
            ("1", "fact", "田中さん", "営業部長"),
        ]
        conn.execute.side_effect = [pref_result, knowledge_result]

        result = viewer.get_user_memories("user123")
        assert result.total_count == 1
        assert result.memories[0].title == "田中さん"
        assert result.memories[0].source == "auto_flush"

    def test_get_user_memories_with_pii_masking(self, viewer, mock_pool):
        """PII含有記憶のマスキング"""
        conn = mock_pool.connect.return_value
        pref_result = MagicMock()
        pref_result.fetchall.return_value = [
            ("11111111-1111-1111-1111-111111111111", "fact", "連絡先", "090-1234-5678", 0.9, "auto_flush"),
        ]
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = []
        conn.execute.side_effect = [pref_result, knowledge_result]

        result = viewer.get_user_memories("user123")
        assert result.total_count == 1
        assert result.masked_count == 1
        assert "[PHONE]" in result.memories[0].content
        assert "090-1234-5678" not in result.memories[0].content

    def test_get_user_memories_db_error(self, viewer, mock_pool):
        """DBエラー時は空結果"""
        conn = mock_pool.connect.return_value
        conn.execute.side_effect = Exception("DB error")

        result = viewer.get_user_memories("user123")
        assert result.total_count == 0

    def test_get_user_memories_category_filter(self, viewer, mock_pool):
        """カテゴリフィルタ"""
        conn = mock_pool.connect.return_value
        pref_result = MagicMock()
        pref_result.fetchall.return_value = [
            ("11111111-1111-1111-1111-111111111111", "communication", "スタイル", "簡潔", 0.7, "auto_flush"),
        ]
        knowledge_result = MagicMock()
        knowledge_result.fetchall.return_value = []
        conn.execute.side_effect = [pref_result, knowledge_result]

        result = viewer.get_user_memories("user123", category="communication")
        assert result.total_count == 1


# =============================================================================
# メモリ削除テスト
# =============================================================================


class TestMemoryDelete:
    """メモリ削除のテスト"""

    def test_delete_preference_success(self, viewer, mock_pool):
        """user_preference削除成功"""
        conn = mock_pool.connect.return_value
        delete_result = MagicMock()
        delete_result.rowcount = 1
        conn.execute.return_value = delete_result

        success = viewer.delete_user_memory("11111111-1111-1111-1111-111111111111", "user123", "preference")
        assert success is True
        conn.commit.assert_called_once()

    def test_delete_preference_not_found(self, viewer, mock_pool):
        """存在しないUUIDの記憶は削除失敗"""
        conn = mock_pool.connect.return_value
        delete_result = MagicMock()
        delete_result.rowcount = 0
        conn.execute.return_value = delete_result

        # 有効なUUID形式だがDBに存在しない
        success = viewer.delete_user_memory(
            "00000000-0000-0000-0000-000000000000", "user123", "preference"
        )
        assert success is False

    def test_delete_preference_invalid_uuid(self, viewer, mock_pool):
        """UUID形式でないmemory_idは即座にFalse"""
        success = viewer.delete_user_memory("not-a-uuid", "user123", "preference")
        assert success is False
        mock_pool.connect.return_value.execute.assert_not_called()

    def test_delete_knowledge_invalid_integer(self, viewer, mock_pool):
        """整数でないmemory_idは即座にFalse"""
        success = viewer.delete_user_memory("abc", "user123", "knowledge")
        assert success is False
        mock_pool.connect.return_value.execute.assert_not_called()

    def test_delete_knowledge_success(self, viewer, mock_pool):
        """soulkun_knowledge削除成功"""
        conn = mock_pool.connect.return_value
        delete_result = MagicMock()
        delete_result.rowcount = 1
        conn.execute.return_value = delete_result

        success = viewer.delete_user_memory("1", "user123", "knowledge")
        assert success is True

    def test_delete_unknown_type(self, viewer, mock_pool):
        """不明なmemory_type"""
        success = viewer.delete_user_memory("1", "user123", "unknown")
        assert success is False

    def test_delete_db_error(self, viewer, mock_pool):
        """DBエラー時はFalse"""
        conn = mock_pool.connect.return_value
        conn.execute.side_effect = Exception("DB error")

        success = viewer.delete_user_memory("1", "user123", "preference")
        assert success is False

    def test_delete_other_user_blocked(self, viewer, mock_pool):
        """他ユーザーの記憶は削除不可（所有者チェック）"""
        conn = mock_pool.connect.return_value
        delete_result = MagicMock()
        delete_result.rowcount = 0  # WHERE句で所有者不一致→0件
        conn.execute.return_value = delete_result

        success = viewer.delete_user_memory("11111111-1111-1111-1111-111111111111", "other_user", "preference")
        assert success is False
