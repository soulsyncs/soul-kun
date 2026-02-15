"""
tests/test_cost_report.py

Task D: コスト日次レポートのテスト
"""

import importlib
import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


# ============================================================
# モジュールロード
# ============================================================

def _load_cost_report_module():
    """cost-report/main.py をロード"""
    _MOCK_NAMES = [
        "google.cloud", "google.cloud.firestore",
        "functions_framework",
        "lib.db", "lib.secrets", "lib.config", "lib.chatwork", "lib",
    ]

    saved = {name: sys.modules.pop(name) for name in _MOCK_NAMES if name in sys.modules}

    try:
        for mod_name in _MOCK_NAMES:
            sys.modules[mod_name] = MagicMock()

        mock_ff = MagicMock()
        mock_ff.http = lambda fn: fn
        sys.modules["functions_framework"] = mock_ff

        cost_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "cost-report"
        )
        spec = importlib.util.spec_from_file_location(
            "cost_report_main", os.path.join(cost_dir, "main.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for name in _MOCK_NAMES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


_cost_mod = _load_cost_report_module()


class _FakeResponse:
    def __init__(self, data):
        self._data = data
    def get_json(self):
        return self._data


# ============================================================
# テスト
# ============================================================

class TestGetDailyReportData:
    def test_returns_daily_data(self):
        mock_conn = MagicMock()

        # 日次集計
        daily_row = MagicMock()
        daily_row.__getitem__ = lambda self, i: [150.5, 42, 10000, 5000, 2][i]

        # モデル別
        model_row = MagicMock()
        model_row.__getitem__ = lambda self, i: ["gpt-5.2", 30, 120.0][i]

        mock_conn.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=daily_row)),
            MagicMock(fetchall=MagicMock(return_value=[model_row])),
        ]

        result = _cost_mod._get_daily_report_data(mock_conn, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        assert result["total_cost"] == 150.5
        assert result["total_requests"] == 42
        assert result["error_count"] == 2
        assert len(result["models"]) == 1
        assert result["models"][0]["name"] == "gpt-5.2"

    def test_handles_empty_data(self):
        mock_conn = MagicMock()

        empty_row = MagicMock()
        empty_row.__getitem__ = lambda self, i: [0, 0, 0, 0, 0][i]

        mock_conn.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=empty_row)),
            MagicMock(fetchall=MagicMock(return_value=[])),
        ]

        result = _cost_mod._get_daily_report_data(mock_conn, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        assert result["total_cost"] == 0
        assert result["total_requests"] == 0
        assert result["error_rate"] == 0
        assert result["models"] == []


class TestGetMonthlySummary:
    def test_returns_monthly_summary(self):
        mock_conn = MagicMock()

        row = MagicMock()
        row.__getitem__ = lambda self, i: [3500.0, 200, 50000, 25000, 10000.0, 6500.0][i]

        mock_conn.execute.return_value = MagicMock(
            fetchone=MagicMock(return_value=row)
        )

        result = _cost_mod._get_monthly_summary(mock_conn, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        assert result["total_cost"] == 3500.0
        assert result["total_requests"] == 200
        assert result["budget"] == 10000.0
        assert result["budget_remaining"] == 6500.0

    def test_handles_no_summary(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value = MagicMock(
            fetchone=MagicMock(return_value=None)
        )

        result = _cost_mod._get_monthly_summary(mock_conn, "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        assert result["total_cost"] == 0
        assert result["total_requests"] == 0


class TestFormatDailyReport:
    def test_format_includes_all_sections(self):
        daily = {
            "date": "2026-02-09",
            "total_cost": 250.0,
            "total_requests": 100,
            "total_input_tokens": 20000,
            "total_output_tokens": 10000,
            "error_count": 3,
            "error_rate": 3.0,
            "models": [
                {"name": "gpt-5.2", "requests": 80, "cost": 200.0},
                {"name": "gemini-3-flash", "requests": 20, "cost": 50.0},
            ],
        }
        monthly = {
            "year_month": "2026-02",
            "total_cost": 5000.0,
            "total_requests": 2000,
            "budget": 10000.0,
            "budget_remaining": 5000.0,
        }

        result = _cost_mod._format_daily_report(daily, monthly)

        assert "[info]" in result
        assert "250" in result
        assert "gpt-5.2" in result
        assert "累計コスト" in result
        assert "予算残" in result

    def test_no_budget_hides_budget_line(self):
        daily = {
            "date": "2026-02-09",
            "total_cost": 0,
            "total_requests": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "error_count": 0,
            "error_rate": 0,
            "models": [],
        }
        monthly = {
            "year_month": "2026-02",
            "total_cost": 0,
            "total_requests": 0,
            "budget": 0,
            "budget_remaining": 0,
        }

        result = _cost_mod._format_daily_report(daily, monthly)

        assert "予算残" not in result


class TestCostReportFunction:
    def test_sends_report_to_chatwork(self):
        mock_conn = MagicMock()

        daily_row = MagicMock()
        daily_row.__getitem__ = lambda self, i: [100.0, 10, 5000, 2500, 0][i]

        mock_conn.execute.side_effect = [
            MagicMock(),  # set_config for RLS
            MagicMock(fetchone=MagicMock(return_value=daily_row)),
            MagicMock(fetchall=MagicMock(return_value=[])),
            MagicMock(fetchone=MagicMock(return_value=None)),
        ]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_conn

        mock_client = MagicMock()

        with patch.object(_cost_mod, "get_db_pool", return_value=mock_pool), \
             patch.object(_cost_mod, "ChatworkClient", return_value=mock_client), \
             patch.object(_cost_mod, "jsonify", side_effect=lambda d: _FakeResponse(d)):

            resp = _cost_mod.cost_report(MagicMock())
            data = resp.get_json()

        assert data["status"] == "ok"
        mock_client.send_message.assert_called_once()
        msg = mock_client.send_message.call_args[1]["message"]
        assert "コストレポート" in msg

    def test_error_returns_500(self):
        with patch.object(_cost_mod, "get_db_pool", side_effect=RuntimeError("no pool")), \
             patch.object(_cost_mod, "jsonify", side_effect=lambda d: _FakeResponse(d)):

            result = _cost_mod.cost_report(MagicMock())

        # Returns tuple (response, status_code) on error
        resp, status = result
        assert status == 500
        assert resp.get_json()["status"] == "error"
