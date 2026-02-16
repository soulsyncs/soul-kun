"""
tests/test_cleanup_brain_tables.py

Task B: brain テーブルクリーンアップのテスト
cleanup-old-data/main.py の cleanup_old_data() に追加した
6つのbrainテーブル削除処理のテスト
"""

import importlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ============================================================
# モジュールロード（1回だけ）
# ============================================================

def _load_cleanup_module():
    """cleanup-old-data/main.py をロード（sys.modules汚染を防止）"""
    _MOCK_NAMES = [
        "google.cloud", "google.cloud.firestore",
        "httpx",
        "lib.db", "lib.secrets", "lib.config", "lib",
    ]

    # ローカルに無いパッケージはモックする
    for pkg in ["pg8000", "sqlalchemy", "flask"]:
        try:
            __import__(pkg)
        except ImportError:
            _MOCK_NAMES.append(pkg)

    # 既存のモジュールを退避
    saved = {name: sys.modules.pop(name) for name in _MOCK_NAMES if name in sys.modules}

    try:
        for mod_name in _MOCK_NAMES:
            sys.modules[mod_name] = MagicMock()

        cleanup_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "cleanup-old-data"
        )
        spec = importlib.util.spec_from_file_location(
            "cleanup_old_data_main", os.path.join(cleanup_dir, "main.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        # モックを除去し、退避したものを復元
        for name in _MOCK_NAMES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


_cleanup_mod = _load_cleanup_module()


# ============================================================
# ヘルパー
# ============================================================

class _FakeResponse:
    """jsonify の戻り値を模倣"""

    def __init__(self, data):
        self._data = data

    def get_json(self):
        return self._data


def _make_mock_conn(rowcount_map=None):
    """モックコネクション生成"""
    if rowcount_map is None:
        rowcount_map = {}

    mock_conn = MagicMock()

    def _execute_side_effect(stmt, params=None):
        result = MagicMock()
        sql_str = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
        for table_name, count in rowcount_map.items():
            if table_name in sql_str:
                result.rowcount = count
                return result
        result.rowcount = 0
        return result

    mock_conn.execute = MagicMock(side_effect=_execute_side_effect)
    mock_conn.commit = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


def _run_cleanup(rowcount_map=None):
    """cleanup_old_data を実行して結果辞書を返す"""
    mock_conn = _make_mock_conn(rowcount_map or {})
    mock_pool = MagicMock()
    mock_pool.connect.return_value = mock_conn

    mock_db = MagicMock()
    mock_db.collection.return_value.where.return_value.stream.return_value = iter([])

    with patch.object(_cleanup_mod, "get_pool", return_value=mock_pool), \
         patch.object(_cleanup_mod, "db", mock_db), \
         patch.object(_cleanup_mod, "jsonify", side_effect=lambda d: _FakeResponse(d)):
        with _cleanup_mod.app.test_request_context(json={}):
            resp = _cleanup_mod.cleanup_old_data()
            return resp.get_json()


# ============================================================
# テスト
# ============================================================

class TestCleanupBrainDecisionLogs:
    def test_deletes_brain_decision_logs_90_days(self):
        data = _run_cleanup({"brain_decision_logs": 42})
        assert data["results"]["brain_decision_logs"] == 42


class TestCleanupBrainImprovementLogs:
    def test_deletes_brain_improvement_logs_180_days(self):
        data = _run_cleanup({"brain_improvement_logs": 15})
        assert data["results"]["brain_improvement_logs"] == 15


class TestCleanupBrainInteractions:
    def test_deletes_brain_interactions_90_days(self):
        data = _run_cleanup({"brain_interactions": 100})
        assert data["results"]["brain_interactions"] == 100


class TestCleanupAiUsageLogs:
    def test_deletes_ai_usage_logs_90_days(self):
        data = _run_cleanup({"ai_usage_logs": 500})
        assert data["results"]["ai_usage_logs"] == 500


class TestCleanupBrainOutcomeEvents:
    def test_deletes_brain_outcome_events_90_days(self):
        data = _run_cleanup({"brain_outcome_events": 77})
        assert data["results"]["brain_outcome_events"] == 77


class TestCleanupBrainOutcomePatterns:
    def test_deletes_brain_outcome_patterns_90_days(self):
        data = _run_cleanup({"brain_outcome_patterns": 33})
        assert data["results"]["brain_outcome_patterns"] == 33


class TestCleanupErrorHandling:
    def test_brain_table_error_does_not_block_others(self):
        """1つのbrainテーブル削除が失敗しても他は続行する"""
        mock_conn = MagicMock()

        def _execute_side_effect(stmt, params=None):
            sql_str = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
            if "brain_decision_logs" in sql_str:
                raise RuntimeError("simulated DB error")
            result = MagicMock()
            result.rowcount = 10
            return result

        mock_conn.execute = MagicMock(side_effect=_execute_side_effect)
        mock_conn.commit = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_conn

        mock_db = MagicMock()
        mock_db.collection.return_value.where.return_value.stream.return_value = iter([])

        with patch.object(_cleanup_mod, "get_pool", return_value=mock_pool), \
             patch.object(_cleanup_mod, "db", mock_db), \
             patch.object(_cleanup_mod, "jsonify", side_effect=lambda d: _FakeResponse(d)):
            with _cleanup_mod.app.test_request_context(json={}):
                resp = _cleanup_mod.cleanup_old_data()
                data = resp.get_json()

        assert data["status"] == "partial"
        assert data["results"]["brain_decision_logs"] == 0
        assert data["results"]["brain_interactions"] == 10

    def test_error_messages_use_type_name_not_str(self):
        """エラーメッセージに type(e).__name__ を使い、PII漏洩しないこと"""
        mock_conn = MagicMock()

        def _execute_side_effect(stmt, params=None):
            raise ValueError("secret connection string with password")

        mock_conn.execute = MagicMock(side_effect=_execute_side_effect)
        mock_conn.commit = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_conn

        mock_db = MagicMock()
        mock_db.collection.return_value.where.return_value.stream.return_value = iter([])

        with patch.object(_cleanup_mod, "get_pool", return_value=mock_pool), \
             patch.object(_cleanup_mod, "db", mock_db), \
             patch.object(_cleanup_mod, "jsonify", side_effect=lambda d: _FakeResponse(d)):
            with _cleanup_mod.app.test_request_context(json={}):
                resp = _cleanup_mod.cleanup_old_data()
                data = resp.get_json()

        for err in data["results"]["errors"]:
            assert "secret" not in err
            assert "password" not in err
            assert "ValueError" in err
