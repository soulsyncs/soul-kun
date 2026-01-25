"""
KnowledgeHandler のテスト

テスト対象: chatwork-webhook/handlers/knowledge_handler.py
"""

import pytest
import sys
from unittest.mock import MagicMock, patch
from datetime import datetime

# テスト対象のモジュールをインポート
sys.path.insert(0, "chatwork-webhook")
from handlers.knowledge_handler import (
    KnowledgeHandler,
    KNOWLEDGE_KEYWORDS,
    QUERY_EXPANSION_MAP,
    KNOWLEDGE_LIMIT,
    KNOWLEDGE_VALUE_MAX_LENGTH,
)


# =====================================================
# テスト用ヘルパー
# =====================================================

def create_mock_pool():
    """モックプールを作成するヘルパー"""
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
    mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_pool.begin.return_value.__exit__ = MagicMock(return_value=None)
    return mock_pool, mock_conn


def create_handler(mock_pool=None, **kwargs):
    """テスト用のハンドラーを作成"""
    if mock_pool is None:
        mock_pool, _ = create_mock_pool()

    defaults = {
        "get_pool": lambda: mock_pool,
        "get_secret": MagicMock(return_value="test-api-key"),
        "is_admin_func": MagicMock(return_value=False),
        "create_proposal_func": MagicMock(return_value=1),
        "report_proposal_to_admin_func": MagicMock(return_value=True),
        "is_mvv_question_func": MagicMock(return_value=False),
        "get_full_mvv_info_func": MagicMock(return_value="MVV情報"),
        "call_openrouter_api_func": MagicMock(return_value="テスト回答ウル！"),
        "phase3_knowledge_config": {
            "enabled": True,
            "api_url": "https://test-api.example.com/search",
            "timeout": 30,
            "organization_id": "org_test",
            "similarity_threshold": 0.5,
            "keyword_weight": 0.4,
            "vector_weight": 0.6,
        },
        "default_model": "test-model",
        "admin_account_id": "1728974",
        "openrouter_api_url": "https://openrouter.test/api",
    }
    defaults.update(kwargs)
    return KnowledgeHandler(**defaults)


# =====================================================
# 定数のテスト
# =====================================================

class TestConstants:
    """定数のテスト"""

    def test_knowledge_keywords_not_empty(self):
        """KNOWLEDGE_KEYWORDSが空でないことを確認"""
        assert len(KNOWLEDGE_KEYWORDS) > 0

    def test_knowledge_keywords_contains_vacation_terms(self):
        """休暇関連のキーワードが含まれていることを確認"""
        assert "有給休暇" in KNOWLEDGE_KEYWORDS
        assert "有給" in KNOWLEDGE_KEYWORDS
        assert "年休" in KNOWLEDGE_KEYWORDS

    def test_query_expansion_map_not_empty(self):
        """QUERY_EXPANSION_MAPが空でないことを確認"""
        assert len(QUERY_EXPANSION_MAP) > 0

    def test_query_expansion_map_contains_vacation(self):
        """有給関連の拡張マップが含まれていることを確認"""
        assert "有給休暇" in QUERY_EXPANSION_MAP
        assert "有給" in QUERY_EXPANSION_MAP

    def test_knowledge_limit_is_positive(self):
        """KNOWLEDGE_LIMITが正の値であることを確認"""
        assert KNOWLEDGE_LIMIT > 0
        assert KNOWLEDGE_LIMIT == 50

    def test_knowledge_value_max_length_is_positive(self):
        """KNOWLEDGE_VALUE_MAX_LENGTHが正の値であることを確認"""
        assert KNOWLEDGE_VALUE_MAX_LENGTH > 0
        assert KNOWLEDGE_VALUE_MAX_LENGTH == 200


# =====================================================
# 初期化のテスト
# =====================================================

class TestKnowledgeHandlerInit:
    """初期化のテスト"""

    def test_init_with_all_params(self):
        """全パラメータで初期化できることを確認"""
        handler = create_handler()
        assert handler is not None
        assert handler.get_pool is not None
        assert handler.get_secret is not None

    def test_init_with_minimal_params(self):
        """最小パラメータで初期化できることを確認"""
        mock_pool, _ = create_mock_pool()
        handler = KnowledgeHandler(get_pool=lambda: mock_pool)
        assert handler is not None
        assert handler.get_pool is not None

    def test_init_sets_default_model(self):
        """デフォルトモデルが設定されることを確認"""
        mock_pool, _ = create_mock_pool()
        handler = KnowledgeHandler(get_pool=lambda: mock_pool)
        assert handler.default_model == "google/gemini-3-flash-preview"

    def test_init_sets_custom_model(self):
        """カスタムモデルが設定されることを確認"""
        handler = create_handler(default_model="custom-model")
        assert handler.default_model == "custom-model"


# =====================================================
# キーワード抽出のテスト
# =====================================================

class TestExtractKeywords:
    """キーワード抽出のテスト"""

    def test_extract_keywords_single(self):
        """単一キーワードの抽出"""
        keywords = KnowledgeHandler.extract_keywords("有給休暇について教えて")
        assert "有給休暇" in keywords

    def test_extract_keywords_multiple(self):
        """複数キーワードの抽出"""
        keywords = KnowledgeHandler.extract_keywords("有給休暇とボーナスについて")
        assert "有給休暇" in keywords
        assert "ボーナス" in keywords

    def test_extract_keywords_short_form_expansion(self):
        """短縮形の展開"""
        keywords = KnowledgeHandler.extract_keywords("有給について")
        assert "有給" in keywords
        assert "有給休暇" in keywords
        assert "年次有給休暇" in keywords

    def test_extract_keywords_empty_query(self):
        """空のクエリ"""
        keywords = KnowledgeHandler.extract_keywords("")
        assert keywords == []

    def test_extract_keywords_no_match(self):
        """マッチなし"""
        keywords = KnowledgeHandler.extract_keywords("今日の天気は？")
        assert keywords == []


# =====================================================
# クエリ拡張のテスト
# =====================================================

class TestExpandQuery:
    """クエリ拡張のテスト"""

    def test_expand_query_with_keyword(self):
        """キーワードがある場合の拡張"""
        expanded = KnowledgeHandler.expand_query("有給について", ["有給"])
        assert "年次有給休暇" in expanded
        assert "付与日数" in expanded

    def test_expand_query_without_keyword(self):
        """キーワードがない場合は元のクエリを返す"""
        expanded = KnowledgeHandler.expand_query("今日の天気", [])
        assert expanded == "今日の天気"

    def test_expand_query_unknown_keyword(self):
        """未知のキーワードの場合は元のクエリを返す"""
        expanded = KnowledgeHandler.expand_query("テストについて", ["テスト"])
        assert expanded == "テストについて"


# =====================================================
# キーワードスコア計算のテスト
# =====================================================

class TestCalculateKeywordScore:
    """キーワードスコア計算のテスト"""

    def test_calculate_keyword_score_single_match(self):
        """単一マッチのスコア"""
        score = KnowledgeHandler.calculate_keyword_score("有給休暇は10日です", ["有給休暇"])
        assert score == 0.25

    def test_calculate_keyword_score_multiple_match(self):
        """複数回マッチのスコア"""
        score = KnowledgeHandler.calculate_keyword_score(
            "有給休暇は入社後に付与される有給休暇です", ["有給休暇"]
        )
        assert score == 0.5  # 2回マッチ

    def test_calculate_keyword_score_max_cap(self):
        """スコアの上限"""
        score = KnowledgeHandler.calculate_keyword_score(
            "有給有給有給有給有給", ["有給"]
        )
        # 最大3回までカウント、最大スコアは1.0
        assert score <= 1.0

    def test_calculate_keyword_score_empty_content(self):
        """空のコンテンツ"""
        score = KnowledgeHandler.calculate_keyword_score("", ["有給"])
        assert score == 0.0

    def test_calculate_keyword_score_empty_keywords(self):
        """空のキーワード"""
        score = KnowledgeHandler.calculate_keyword_score("有給休暇は10日です", [])
        assert score == 0.0


# =====================================================
# 知識保存のテスト
# =====================================================

class TestSaveKnowledge:
    """知識保存のテスト"""

    def test_save_knowledge_success(self):
        """知識の保存成功"""
        mock_pool, mock_conn = create_mock_pool()
        handler = create_handler(mock_pool=mock_pool)

        result = handler.save_knowledge("rules", "test_key", "test_value", "admin123")
        assert result is True

    def test_save_knowledge_failure(self):
        """知識の保存失敗"""
        mock_pool, mock_conn = create_mock_pool()
        mock_pool.begin.return_value.__enter__.side_effect = Exception("DB error")
        handler = create_handler(mock_pool=mock_pool)

        result = handler.save_knowledge("rules", "test_key", "test_value")
        assert result is False


# =====================================================
# 知識削除のテスト
# =====================================================

class TestDeleteKnowledge:
    """知識削除のテスト"""

    def test_delete_knowledge_with_category(self):
        """カテゴリ指定での削除"""
        mock_pool, mock_conn = create_mock_pool()
        handler = create_handler(mock_pool=mock_pool)

        result = handler.delete_knowledge("rules", "test_key")
        assert result is True

    def test_delete_knowledge_without_category(self):
        """カテゴリ指定なしでの削除"""
        mock_pool, mock_conn = create_mock_pool()
        handler = create_handler(mock_pool=mock_pool)

        result = handler.delete_knowledge(None, "test_key")
        assert result is True

    def test_delete_knowledge_failure(self):
        """削除失敗"""
        mock_pool, mock_conn = create_mock_pool()
        mock_pool.begin.return_value.__enter__.side_effect = Exception("DB error")
        handler = create_handler(mock_pool=mock_pool)

        result = handler.delete_knowledge("rules", "test_key")
        assert result is False


# =====================================================
# 知識取得のテスト
# =====================================================

class TestGetAllKnowledge:
    """知識取得のテスト"""

    def test_get_all_knowledge_success(self):
        """知識の取得成功"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("rules", "test_key", "test_value", datetime.now()),
        ]
        mock_conn.execute.return_value = mock_result
        handler = create_handler(mock_pool=mock_pool)

        result = handler.get_all_knowledge()
        assert len(result) == 1
        assert result[0]["key"] == "test_key"

    def test_get_all_knowledge_with_limit(self):
        """制限付きの取得"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        handler = create_handler(mock_pool=mock_pool)

        handler.get_all_knowledge(limit=10)
        # SQLにLIMITが含まれていることを確認
        call_args = mock_conn.execute.call_args
        sql_text = str(call_args[0][0])
        assert "LIMIT" in sql_text

    def test_get_all_knowledge_failure(self):
        """取得失敗"""
        mock_pool, mock_conn = create_mock_pool()
        mock_conn.execute.side_effect = Exception("DB error")
        handler = create_handler(mock_pool=mock_pool)

        result = handler.get_all_knowledge()
        assert result == []


# =====================================================
# プロンプト用知識のテスト
# =====================================================

class TestGetKnowledgeForPrompt:
    """プロンプト用知識のテスト"""

    def test_get_knowledge_for_prompt_empty(self):
        """空の知識"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        handler = create_handler(mock_pool=mock_pool)

        result = handler.get_knowledge_for_prompt()
        assert result == ""

    def test_get_knowledge_for_prompt_with_data(self):
        """データがある場合"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("rules", "休暇日数", "10日", datetime.now()),
        ]
        mock_conn.execute.return_value = mock_result
        handler = create_handler(mock_pool=mock_pool)

        result = handler.get_knowledge_for_prompt()
        assert "学習済みの知識" in result
        assert "休暇日数" in result

    def test_get_knowledge_for_prompt_truncates_long_values(self):
        """長い値の切り詰め"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        long_value = "a" * 300
        mock_result.fetchall.return_value = [
            ("rules", "test", long_value, datetime.now()),
        ]
        mock_conn.execute.return_value = mock_result
        handler = create_handler(mock_pool=mock_pool)

        result = handler.get_knowledge_for_prompt()
        assert "..." in result


# =====================================================
# 旧システム検索のテスト
# =====================================================

class TestSearchLegacyKnowledge:
    """旧システム検索のテスト"""

    def test_search_legacy_knowledge_exact_match(self):
        """完全一致"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("rules", "有給休暇", "10日", datetime.now()),
        ]
        mock_conn.execute.return_value = mock_result
        handler = create_handler(mock_pool=mock_pool)

        result = handler.search_legacy_knowledge("有給休暇")
        assert result is not None
        assert result["source"] == "legacy"
        assert result["confidence"] == 1.0

    def test_search_legacy_knowledge_no_result(self):
        """結果なし"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        handler = create_handler(mock_pool=mock_pool)

        result = handler.search_legacy_knowledge("存在しないキー")
        assert result is None


# =====================================================
# ハンドラーのテスト - handle_learn_knowledge
# =====================================================

class TestHandleLearnKnowledge:
    """handle_learn_knowledgeのテスト"""

    def test_handle_learn_knowledge_empty_params(self):
        """空のパラメータ"""
        handler = create_handler()
        result = handler.handle_learn_knowledge(
            params={}, room_id="123", account_id="456",
            sender_name="テスト", context=None
        )
        assert "何を覚えればいいかわからなかった" in result

    def test_handle_learn_knowledge_admin_success(self):
        """管理者による学習成功"""
        mock_pool, mock_conn = create_mock_pool()
        handler = create_handler(
            mock_pool=mock_pool,
            is_admin_func=MagicMock(return_value=True)
        )

        result = handler.handle_learn_knowledge(
            params={"category": "rules", "key": "テスト", "value": "テスト値"},
            room_id="123", account_id="admin", sender_name="管理者", context=None
        )
        assert "覚えたウル" in result

    def test_handle_learn_knowledge_staff_proposal(self):
        """スタッフからの提案"""
        handler = create_handler(
            is_admin_func=MagicMock(return_value=False),
            create_proposal_func=MagicMock(return_value=1),
            report_proposal_to_admin_func=MagicMock(return_value=True)
        )

        result = handler.handle_learn_knowledge(
            params={"category": "rules", "key": "テスト", "value": "テスト値"},
            room_id="123", account_id="staff", sender_name="スタッフ", context=None
        )
        assert "提案ID: 1" in result
        # v10.25.0: 「菊地さんに確認」→「ソウルくんが確認」に変更
        assert "ソウルくんが会社として問題ないか確認" in result

    def test_handle_learn_knowledge_staff_notification_failed(self):
        """スタッフからの提案（通知失敗）"""
        handler = create_handler(
            is_admin_func=MagicMock(return_value=False),
            create_proposal_func=MagicMock(return_value=1),
            report_proposal_to_admin_func=MagicMock(return_value=False)
        )

        result = handler.handle_learn_knowledge(
            params={"category": "rules", "key": "テスト", "value": "テスト値"},
            room_id="123", account_id="staff", sender_name="スタッフ", context=None
        )
        assert "提案ID: 1" in result
        # v10.25.0: 通知失敗時もポジティブなメッセージに変更
        assert "ソウルくんが確認中" in result


# =====================================================
# ハンドラーのテスト - handle_forget_knowledge
# =====================================================

class TestHandleForgetKnowledge:
    """handle_forget_knowledgeのテスト"""

    def test_handle_forget_knowledge_empty_key(self):
        """空のキー"""
        handler = create_handler()
        result = handler.handle_forget_knowledge(
            params={}, room_id="123", account_id="456",
            sender_name="テスト", context=None
        )
        assert "何を忘れればいいかわからなかった" in result

    def test_handle_forget_knowledge_non_admin(self):
        """非管理者による削除試行"""
        handler = create_handler(is_admin_func=MagicMock(return_value=False))
        result = handler.handle_forget_knowledge(
            params={"key": "テスト"}, room_id="123", account_id="staff",
            sender_name="スタッフ", context=None
        )
        assert "菊地さんだけができる" in result

    def test_handle_forget_knowledge_admin_success(self):
        """管理者による削除成功"""
        mock_pool, mock_conn = create_mock_pool()
        handler = create_handler(
            mock_pool=mock_pool,
            is_admin_func=MagicMock(return_value=True)
        )

        result = handler.handle_forget_knowledge(
            params={"key": "テスト"}, room_id="123", account_id="admin",
            sender_name="管理者", context=None
        )
        assert "忘れたウル" in result


# =====================================================
# ハンドラーのテスト - handle_list_knowledge
# =====================================================

class TestHandleListKnowledge:
    """handle_list_knowledgeのテスト"""

    def test_handle_list_knowledge_empty(self):
        """空の知識リスト"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        handler = create_handler(mock_pool=mock_pool)

        result = handler.handle_list_knowledge(
            params={}, room_id="123", account_id="456",
            sender_name="テスト", context=None
        )
        assert "まだ何も覚えてない" in result

    def test_handle_list_knowledge_with_data(self):
        """データがある場合"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("rules", "テスト", "値", datetime.now()),
        ]
        mock_conn.execute.return_value = mock_result
        handler = create_handler(mock_pool=mock_pool)

        result = handler.handle_list_knowledge(
            params={}, room_id="123", account_id="456",
            sender_name="テスト", context=None
        )
        assert "覚えていること" in result
        assert "合計 1 件" in result


# =====================================================
# ハンドラーのテスト - handle_query_company_knowledge
# =====================================================

class TestHandleQueryCompanyKnowledge:
    """handle_query_company_knowledgeのテスト"""

    def test_handle_query_company_knowledge_empty_query(self):
        """空のクエリ"""
        handler = create_handler()
        result = handler.handle_query_company_knowledge(
            params={}, room_id="123", account_id="456",
            sender_name="テスト", context=None
        )
        assert "何を調べればいいか" in result

    def test_handle_query_company_knowledge_mvv_question(self):
        """MVV質問"""
        handler = create_handler(is_mvv_question_func=MagicMock(return_value=True))
        result = handler.handle_query_company_knowledge(
            params={"query": "ミッションは？"}, room_id="123", account_id="456",
            sender_name="テスト", context=None
        )
        assert "MVV" in result

    def test_handle_query_company_knowledge_no_results(self):
        """検索結果なし"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        handler = create_handler(
            mock_pool=mock_pool,
            is_mvv_question_func=MagicMock(return_value=False),
            phase3_knowledge_config={"enabled": False}  # Phase3無効
        )

        result = handler.handle_query_company_knowledge(
            params={"query": "存在しない情報"}, room_id="123", account_id="456",
            sender_name="テスト", context=None
        )
        assert "勉強中" in result

    def test_handle_query_company_knowledge_with_results(self):
        """検索結果あり"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("rules", "有給休暇", "10日", datetime.now()),
        ]
        mock_conn.execute.return_value = mock_result
        handler = create_handler(
            mock_pool=mock_pool,
            is_mvv_question_func=MagicMock(return_value=False),
            phase3_knowledge_config={"enabled": False},
            call_openrouter_api_func=MagicMock(return_value="有給は10日ウル！")
        )

        result = handler.handle_query_company_knowledge(
            params={"query": "有給休暇"}, room_id="123", account_id="456",
            sender_name="テスト", context=None
        )
        assert "10日" in result


# =====================================================
# ハンドラーのテスト - handle_local_learn_knowledge
# =====================================================

class TestHandleLocalLearnKnowledge:
    """handle_local_learn_knowledgeのテスト"""

    def test_handle_local_learn_knowledge_admin(self):
        """管理者によるローカル学習"""
        mock_pool, mock_conn = create_mock_pool()
        handler = create_handler(
            mock_pool=mock_pool,
            is_admin_func=MagicMock(return_value=True)
        )

        result = handler.handle_local_learn_knowledge(
            key="テストキー", value="テスト値",
            account_id="admin", sender_name="管理者", room_id="123"
        )
        assert "覚えたウル" in result

    def test_handle_local_learn_knowledge_staff(self):
        """スタッフによるローカル学習"""
        handler = create_handler(
            is_admin_func=MagicMock(return_value=False),
            create_proposal_func=MagicMock(return_value=1),
            report_proposal_to_admin_func=MagicMock(return_value=True)
        )

        result = handler.handle_local_learn_knowledge(
            key="テストキー", value="テスト値",
            account_id="staff", sender_name="スタッフ", room_id="123"
        )
        assert "提案ID: 1" in result

    def test_handle_local_learn_knowledge_category_detection_character(self):
        """キャラクターカテゴリの検出"""
        mock_pool, mock_conn = create_mock_pool()
        handler = create_handler(
            mock_pool=mock_pool,
            is_admin_func=MagicMock(return_value=True)
        )

        result = handler.handle_local_learn_knowledge(
            key="キャラ設定", value="テスト値",
            account_id="admin", sender_name="管理者", room_id="123"
        )
        assert "キャラ設定" in result

    def test_handle_local_learn_knowledge_category_detection_rules(self):
        """業務ルールカテゴリの検出"""
        mock_pool, mock_conn = create_mock_pool()
        handler = create_handler(
            mock_pool=mock_pool,
            is_admin_func=MagicMock(return_value=True)
        )

        result = handler.handle_local_learn_knowledge(
            key="業務ルール", value="テスト値",
            account_id="admin", sender_name="管理者", room_id="123"
        )
        assert "業務ルール" in result


# =====================================================
# format_phase3_results のテスト
# =====================================================

class TestFormatPhase3Results:
    """format_phase3_resultsのテスト"""

    def test_format_phase3_results_empty(self):
        """空の結果"""
        result = KnowledgeHandler.format_phase3_results([])
        assert result == ""

    def test_format_phase3_results_single(self):
        """単一の結果"""
        results = [
            {
                "content": "テストコンテンツ",
                "score": 0.85,
                "document": {
                    "title": "就業規則",
                    "file_name": "rules.pdf"
                },
                "page_number": 5
            }
        ]
        formatted = KnowledgeHandler.format_phase3_results(results)
        assert "参考情報 1" in formatted
        assert "テストコンテンツ" in formatted
        assert "就業規則" in formatted
        assert "p.5" in formatted

    def test_format_phase3_results_multiple(self):
        """複数の結果"""
        results = [
            {"content": "コンテンツ1", "score": 0.9, "document": {"title": "文書1"}},
            {"content": "コンテンツ2", "score": 0.8, "document": {"title": "文書2"}},
        ]
        formatted = KnowledgeHandler.format_phase3_results(results)
        assert "参考情報 1" in formatted
        assert "参考情報 2" in formatted


# =====================================================
# 統合ナレッジ検索のテスト
# =====================================================

class TestIntegratedKnowledgeSearch:
    """統合ナレッジ検索のテスト"""

    def test_integrated_search_legacy_high_confidence(self):
        """旧システム高信頼度"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("rules", "有給休暇", "10日", datetime.now()),
        ]
        mock_conn.execute.return_value = mock_result
        handler = create_handler(
            mock_pool=mock_pool,
            phase3_knowledge_config={"enabled": False}
        )

        result = handler.integrated_knowledge_search("有給休暇")
        assert result["source"] == "legacy"
        assert result["confidence"] >= 0.8

    def test_integrated_search_no_results(self):
        """結果なし"""
        mock_pool, mock_conn = create_mock_pool()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        handler = create_handler(
            mock_pool=mock_pool,
            phase3_knowledge_config={"enabled": False}
        )

        result = handler.integrated_knowledge_search("存在しない情報")
        assert result["source"] == "none"
        assert result["confidence"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
