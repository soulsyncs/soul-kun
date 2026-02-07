# tests/test_daily_log.py
"""
日次ログ生成のユニットテスト

Phase 2-B: 活動の透明性
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import date, datetime, timezone, timedelta

from lib.brain.daily_log import (
    DailyActivity,
    DailyLogGenerator,
    JST,
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
def generator(mock_pool):
    """DailyLogGeneratorインスタンス"""
    return DailyLogGenerator(pool=mock_pool, org_id="org_test")


@pytest.fixture
def mock_metrics():
    """AggregatedMetricsのモック"""
    metrics = Mock()
    metrics.avg_response_time_ms = 1500.5
    metrics.error_rate = 0.02
    metrics.estimated_cost_yen = 150.0
    metrics.guardian_allow_count = 50
    metrics.guardian_confirm_count = 5
    metrics.guardian_block_count = 2
    metrics.output_types = {"general_conversation": 30, "chatwork_task_create": 15, "query_knowledge": 5}
    return metrics


# =============================================================================
# DailyActivity テスト
# =============================================================================


class TestDailyActivity:
    """DailyActivityデータクラスのテスト"""

    def test_to_dict(self):
        """辞書変換"""
        activity = DailyActivity(
            target_date=date(2026, 2, 6),
            org_id="org_test",
            total_conversations=10,
            unique_users=5,
            new_preferences=3,
        )
        d = activity.to_dict()
        assert d["target_date"] == "2026-02-06"
        assert d["conversations"]["total"] == 10
        assert d["conversations"]["unique_users"] == 5
        assert d["memory"]["new_preferences"] == 3

    def test_display_text_empty(self):
        """活動なしの場合のテキスト"""
        activity = DailyActivity(
            target_date=date(2026, 2, 6),
            org_id="org_test",
        )
        text = activity.to_display_text()
        assert "2026/02/06" in text
        assert "会話数: 0件" in text

    def test_display_text_with_activity(self):
        """活動ありの場合のテキスト"""
        activity = DailyActivity(
            target_date=date(2026, 2, 6),
            org_id="org_test",
            total_conversations=25,
            unique_users=8,
            action_counts={"general_conversation": 15, "chatwork_task_create": 10},
            new_preferences=3,
            new_knowledge=2,
            new_learnings=1,
            avg_response_time_ms=1200.0,
            error_rate=0.01,
            total_cost_yen=200.0,
            guardian_allow=45,
            guardian_confirm=3,
            guardian_block=1,
        )
        text = activity.to_display_text()

        assert "25件" in text
        assert "8人" in text
        assert "general_conversation" in text
        assert "chatwork_task_create" in text
        assert "好み・設定: 3件" in text
        assert "ナレッジ: 2件" in text
        assert "脳の学習: 1件" in text
        assert "1200ms" in text
        assert "1.0%" in text
        assert "200円" in text
        assert "許可: 45件" in text
        assert "確認: 3件" in text
        assert "ブロック: 1件" in text

    def test_display_text_no_memory_section_when_zero(self):
        """メモリ活動0件の場合、記憶セクションは表示しない"""
        activity = DailyActivity(
            target_date=date(2026, 2, 6),
            org_id="org_test",
            total_conversations=5,
        )
        text = activity.to_display_text()
        assert "記憶・学習:" not in text

    def test_display_text_no_guardian_confirm_when_zero(self):
        """Guardian確認0件の場合、確認行は表示しない"""
        activity = DailyActivity(
            target_date=date(2026, 2, 6),
            org_id="org_test",
            guardian_allow=10,
        )
        text = activity.to_display_text()
        assert "許可: 10件" in text
        assert "確認:" not in text
        assert "ブロック:" not in text

    def test_display_text_actions_sorted_by_count(self):
        """アクションはカウント降順でソート"""
        activity = DailyActivity(
            target_date=date(2026, 2, 6),
            org_id="org_test",
            action_counts={"a": 5, "b": 20, "c": 10},
        )
        text = activity.to_display_text()
        # b(20) が a(5) より先に出る
        pos_b = text.index("b: 20件")
        pos_a = text.index("a: 5件")
        assert pos_b < pos_a


# =============================================================================
# DailyLogGenerator.generate テスト
# =============================================================================


class TestGenerate:
    """日次ログ生成のテスト"""

    def test_default_date_is_yesterday(self, generator, mock_pool):
        """デフォルトは前日（JST）"""
        conn = mock_pool.connect.return_value
        # 3つのクエリに対する結果
        conv_result = MagicMock()
        conv_result.fetchone.return_value = (0, 0)
        pref_result = MagicMock()
        pref_result.fetchone.return_value = (0,)
        knowledge_result = MagicMock()
        knowledge_result.fetchone.return_value = (0,)
        learning_result = MagicMock()
        learning_result.fetchone.return_value = (0,)
        conn.execute.side_effect = [conv_result, pref_result, knowledge_result, learning_result]

        activity = generator.generate()

        now_jst = datetime.now(JST)
        expected_date = (now_jst - timedelta(days=1)).date()
        assert activity.target_date == expected_date

    def test_specific_date(self, generator, mock_pool):
        """指定日で生成"""
        conn = mock_pool.connect.return_value
        conv_result = MagicMock()
        conv_result.fetchone.return_value = (15, 7)
        pref_result = MagicMock()
        pref_result.fetchone.return_value = (3,)
        knowledge_result = MagicMock()
        knowledge_result.fetchone.return_value = (2,)
        learning_result = MagicMock()
        learning_result.fetchone.return_value = (1,)
        conn.execute.side_effect = [conv_result, pref_result, knowledge_result, learning_result]

        activity = generator.generate(target_date=date(2026, 2, 6))

        assert activity.target_date == date(2026, 2, 6)
        assert activity.total_conversations == 15
        assert activity.unique_users == 7
        assert activity.new_preferences == 3
        assert activity.new_knowledge == 2
        assert activity.new_learnings == 1

    def test_with_metrics(self, generator, mock_pool, mock_metrics):
        """AggregatedMetrics統合"""
        conn = mock_pool.connect.return_value
        conv_result = MagicMock()
        conv_result.fetchone.return_value = (10, 5)
        pref_result = MagicMock()
        pref_result.fetchone.return_value = (0,)
        knowledge_result = MagicMock()
        knowledge_result.fetchone.return_value = (0,)
        learning_result = MagicMock()
        learning_result.fetchone.return_value = (0,)
        conn.execute.side_effect = [conv_result, pref_result, knowledge_result, learning_result]

        activity = generator.generate(
            target_date=date(2026, 2, 6),
            metrics=mock_metrics,
        )

        assert activity.avg_response_time_ms == 1500.5
        assert activity.error_rate == 0.02
        assert activity.total_cost_yen == 150.0
        assert activity.guardian_allow == 50
        assert activity.guardian_confirm == 5
        assert activity.guardian_block == 2
        assert activity.action_counts["general_conversation"] == 30

    def test_db_error_graceful(self, generator, mock_pool):
        """DBエラー時はデフォルト値で生成"""
        conn = mock_pool.connect.return_value
        conn.execute.side_effect = Exception("DB error")

        activity = generator.generate(target_date=date(2026, 2, 6))

        assert activity.total_conversations == 0
        assert activity.unique_users == 0
        assert activity.new_preferences == 0

    def test_null_db_results(self, generator, mock_pool):
        """DB結果がNoneの場合"""
        conn = mock_pool.connect.return_value
        conv_result = MagicMock()
        conv_result.fetchone.return_value = (None, None)
        pref_result = MagicMock()
        pref_result.fetchone.return_value = (None,)
        knowledge_result = MagicMock()
        knowledge_result.fetchone.return_value = (None,)
        learning_result = MagicMock()
        learning_result.fetchone.return_value = (None,)
        conn.execute.side_effect = [conv_result, pref_result, knowledge_result, learning_result]

        activity = generator.generate(target_date=date(2026, 2, 6))

        assert activity.total_conversations == 0
        assert activity.unique_users == 0
        assert activity.new_preferences == 0


# =============================================================================
# メトリクス統合テスト
# =============================================================================


class TestMergeMetrics:
    """メトリクス統合のテスト"""

    def test_merge_all_fields(self, generator, mock_metrics):
        """全フィールドが正しく統合される"""
        activity = DailyActivity(
            target_date=date(2026, 2, 6),
            org_id="org_test",
        )
        generator._merge_metrics(activity, mock_metrics)

        assert activity.avg_response_time_ms == 1500.5
        assert activity.error_rate == 0.02
        assert activity.total_cost_yen == 150.0
        assert activity.guardian_allow == 50
        assert activity.action_counts["general_conversation"] == 30

    def test_merge_metrics_error_graceful(self, generator):
        """不正なmetricsオブジェクトでもエラーにならない"""
        activity = DailyActivity(
            target_date=date(2026, 2, 6),
            org_id="org_test",
        )
        bad_metrics = Mock()
        bad_metrics.avg_response_time_ms = property(lambda _: 1 / 0)  # will raise
        del bad_metrics.avg_response_time_ms  # force AttributeError

        generator._merge_metrics(activity, bad_metrics)
        # エラーでもクラッシュしない
        assert activity.avg_response_time_ms == 0.0

    def test_merge_without_output_types(self, generator):
        """output_typesがないmetricsの場合"""
        activity = DailyActivity(
            target_date=date(2026, 2, 6),
            org_id="org_test",
        )
        metrics = Mock(spec=[])  # 属性なし
        metrics.avg_response_time_ms = 1000.0
        metrics.error_rate = 0.0
        metrics.estimated_cost_yen = 50.0
        metrics.guardian_allow_count = 10
        metrics.guardian_confirm_count = 0
        metrics.guardian_block_count = 0

        generator._merge_metrics(activity, metrics)
        assert activity.action_counts == {}  # output_typesがないので空


# =============================================================================
# org_idエスケープテスト
# =============================================================================


class TestOrgIdEscaping:
    """soulkun_knowledgeクエリのorg_idエスケープ"""

    def test_org_id_with_special_chars(self, mock_pool):
        """特殊文字を含むorg_idが正しくエスケープされる"""
        generator = DailyLogGenerator(pool=mock_pool, org_id="org_100%")
        conn = mock_pool.connect.return_value

        conv_result = MagicMock()
        conv_result.fetchone.return_value = (0, 0)
        pref_result = MagicMock()
        pref_result.fetchone.return_value = (0,)
        knowledge_result = MagicMock()
        knowledge_result.fetchone.return_value = (0,)
        learning_result = MagicMock()
        learning_result.fetchone.return_value = (0,)
        conn.execute.side_effect = [conv_result, pref_result, knowledge_result, learning_result]

        activity = generator.generate(target_date=date(2026, 2, 6))

        # knowledgeクエリ（3番目のexecute呼び出し）のパラメータを確認
        calls = conn.execute.call_args_list
        knowledge_call = calls[2]
        params = knowledge_call[0][1]
        # %がエスケープされている
        assert "\\%" in params["key_prefix"]


# =============================================================================
# org_idバリデーションテスト
# =============================================================================


class TestOrgIdValidation:
    """org_id入力バリデーション（CRITICAL-2修正）"""

    def test_empty_org_id_raises(self, mock_pool):
        """空文字列のorg_idはValueError"""
        with pytest.raises(ValueError, match="non-empty string"):
            DailyLogGenerator(pool=mock_pool, org_id="")

    def test_none_org_id_raises(self, mock_pool):
        """Noneのorg_idはValueError"""
        with pytest.raises(ValueError, match="non-empty string"):
            DailyLogGenerator(pool=mock_pool, org_id=None)
