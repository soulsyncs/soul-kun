# tests/test_monthly_cost_alert.py
"""
P5: 月次AIコスト予算アラート — _try_cost_budget_alert の単体テスト

テスト対象: proactive-monitor/main.py の _try_cost_budget_alert()

カバー範囲:
- 使用率 < 80% -> "ok"
- 使用率 = 85%、未送信 -> "sent"（80%アラート送信）
- 使用率 = 85%、80%送信済み -> "already_sent"（重複防止）
- 使用率 = 105%、未送信 -> "sent"（100%アラート送信）
- 使用率 = 105%、80%送信済み・100%未送信 -> "sent"（100%アラートのみ）
- 使用率 = 105%、両方送信済み -> "already_sent"
- データなし -> "skipped_no_data"
- 予算未設定 -> "skipped_no_budget"
- 9時以外 -> "skipped_not_9am"
- ALERT_ROOM_ID未設定 -> "skipped_no_room"
"""

import asyncio
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _import_try_cost_budget_alert():
    """proactive-monitor/main.py から _try_cost_budget_alert を import する。
    Flask アプリの起動を避けるため、必要な依存をスタブしてから import する。
    """
    # Flask スタブ
    if "flask" not in sys.modules:
        flask_mod = types.ModuleType("flask")
        flask_mod.Flask = MagicMock(return_value=MagicMock())
        flask_mod.request = MagicMock()
        flask_mod.jsonify = MagicMock(side_effect=lambda x: x)
        sys.modules["flask"] = flask_mod

    # lib スタブ（proactive-monitor/lib/ が存在しない環境用）
    for stub_mod in ["lib", "lib.db", "lib.chatwork", "lib.brain",
                     "lib.brain.core", "lib.brain.proactive",
                     "lib.brain.daily_log", "lib.brain.outcome_learning",
                     "lib.brain.memory_access"]:
        if stub_mod not in sys.modules:
            sys.modules[stub_mod] = types.ModuleType(stub_mod)

    import importlib.util
    main_path = os.path.join(
        os.path.dirname(__file__), "..", "proactive-monitor", "main.py"
    )
    spec = importlib.util.spec_from_file_location("proactive_main", main_path)
    mod = importlib.util.module_from_spec(spec)
    # sys.modules に登録してから exec することで patch("proactive_main.X") が機能する
    sys.modules["proactive_main"] = mod
    spec.loader.exec_module(mod)
    return mod._try_cost_budget_alert


def _make_row(total_cost_jpy, budget_jpy, sent_80=None, sent_100=None):
    """DB行モックを作成するヘルパー（row[0]～row[3]でアクセス）"""
    row = MagicMock()
    row.__getitem__ = lambda self, i: [
        total_cost_jpy, budget_jpy, sent_80, sent_100
    ][i]
    return row


class TestTryCostBudgetAlert(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.func = _import_try_cost_budget_alert()
        self.pool = MagicMock()

    # -------- 時刻・設定チェック --------

    @patch.dict(os.environ, {"ALERT_ROOM_ID": "12345"})
    async def test_skipped_not_9am(self):
        with patch("proactive_main.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 10
            mock_now.strftime.return_value = "2026-02"
            mock_dt.now.return_value = mock_now
            result = await self.func(self.pool)
        self.assertEqual(result, "skipped_not_9am")

    @patch.dict(os.environ, {"ALERT_ROOM_ID": ""})
    async def test_skipped_no_room(self):
        with patch("proactive_main.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_now.strftime.return_value = "2026-02"
            mock_dt.now.return_value = mock_now
            result = await self.func(self.pool)
        self.assertEqual(result, "skipped_no_room")

    # -------- データなし・予算なし --------

    @patch.dict(os.environ, {"ALERT_ROOM_ID": "12345"})
    async def test_skipped_no_data(self):
        with patch("proactive_main.datetime") as mock_dt, \
             patch("proactive_main.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_now.strftime.return_value = "2026-02"
            mock_dt.now.return_value = mock_now
            mock_thread.return_value = None  # fetchone() -> None
            result = await self.func(self.pool)
        self.assertEqual(result, "skipped_no_data")

    @patch.dict(os.environ, {"ALERT_ROOM_ID": "12345"})
    async def test_skipped_no_budget(self):
        row = _make_row(5000, None)
        with patch("proactive_main.datetime") as mock_dt, \
             patch("proactive_main.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_now.strftime.return_value = "2026-02"
            mock_dt.now.return_value = mock_now
            mock_thread.return_value = row
            result = await self.func(self.pool)
        self.assertEqual(result, "skipped_no_budget")

    # -------- 使用率 < 80% --------

    @patch.dict(os.environ, {"ALERT_ROOM_ID": "12345"})
    async def test_below_threshold_ok(self):
        row = _make_row(7900, 10000)  # 79%
        with patch("proactive_main.datetime") as mock_dt, \
             patch("proactive_main.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_now.strftime.return_value = "2026-02"
            mock_dt.now.return_value = mock_now
            mock_thread.return_value = row
            result = await self.func(self.pool)
        self.assertEqual(result, "ok")

    # -------- 80% アラート --------

    @patch.dict(os.environ, {"ALERT_ROOM_ID": "12345"})
    async def test_80pct_alert_sent_when_no_previous_alert(self):
        # 使用率 85%、未送信 -> "sent"（80%アラート送信）
        row = _make_row(8500, 10000, sent_80=None, sent_100=None)  # 85%
        call_count = 0

        async def fake_to_thread(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return row  # _query
            return None  # _update_80

        with patch("proactive_main.datetime") as mock_dt, \
             patch("proactive_main.asyncio.to_thread", side_effect=fake_to_thread), \
             patch("proactive_main.send_chatwork_message", new_callable=AsyncMock) as mock_send:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_now.strftime.return_value = "2026-02"
            mock_dt.now.return_value = mock_now
            result = await self.func(self.pool)

        self.assertEqual(result, "sent")
        mock_send.assert_awaited_once()
        args = mock_send.call_args[0]
        self.assertIn("\u26a0\ufe0f \u4e88\u7b97\u8b66\u544a", args[1])  # ⚠️ 予算警告

    @patch.dict(os.environ, {"ALERT_ROOM_ID": "12345"})
    async def test_80pct_alert_skipped_when_already_sent(self):
        # 使用率 85%、80%送信済み -> "already_sent"（重複防止）
        from datetime import datetime as dt
        sent_time = dt(2026, 2, 5, 9, 0, 0)
        row = _make_row(8500, 10000, sent_80=sent_time, sent_100=None)

        with patch("proactive_main.datetime") as mock_dt, \
             patch("proactive_main.asyncio.to_thread", new_callable=AsyncMock) as mock_thread, \
             patch("proactive_main.send_chatwork_message", new_callable=AsyncMock) as mock_send:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_now.strftime.return_value = "2026-02"
            mock_dt.now.return_value = mock_now
            mock_thread.return_value = row
            result = await self.func(self.pool)

        self.assertEqual(result, "already_sent")
        mock_send.assert_not_awaited()

    # -------- 100% アラート --------

    @patch.dict(os.environ, {"ALERT_ROOM_ID": "12345"})
    async def test_100pct_alert_sent_when_no_previous_alert(self):
        # 使用率 105%、未送信 -> "sent"（100%アラート送信）
        row = _make_row(10500, 10000, sent_80=None, sent_100=None)  # 105%
        call_count = 0

        async def fake_to_thread(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return row  # _query
            return None  # _update_100

        with patch("proactive_main.datetime") as mock_dt, \
             patch("proactive_main.asyncio.to_thread", side_effect=fake_to_thread), \
             patch("proactive_main.send_chatwork_message", new_callable=AsyncMock) as mock_send:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_now.strftime.return_value = "2026-02"
            mock_dt.now.return_value = mock_now
            result = await self.func(self.pool)

        self.assertEqual(result, "sent")
        mock_send.assert_awaited_once()
        args = mock_send.call_args[0]
        self.assertIn("\U0001f6a8 \u4e88\u7b97\u8d85\u904e", args[1])  # 🚨 予算超過

    @patch.dict(os.environ, {"ALERT_ROOM_ID": "12345"})
    async def test_100pct_alert_sent_when_80pct_already_sent(self):
        # 使用率 105%、80%送信済み・100%未送信 -> "sent"（100%アラートのみ）
        from datetime import datetime as dt
        sent_time = dt(2026, 2, 5, 9, 0, 0)
        row = _make_row(10500, 10000, sent_80=sent_time, sent_100=None)
        call_count = 0

        async def fake_to_thread(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return row
            return None

        with patch("proactive_main.datetime") as mock_dt, \
             patch("proactive_main.asyncio.to_thread", side_effect=fake_to_thread), \
             patch("proactive_main.send_chatwork_message", new_callable=AsyncMock) as mock_send:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_now.strftime.return_value = "2026-02"
            mock_dt.now.return_value = mock_now
            result = await self.func(self.pool)

        self.assertEqual(result, "sent")
        mock_send.assert_awaited_once()
        args = mock_send.call_args[0]
        self.assertIn("\U0001f6a8 \u4e88\u7b97\u8d85\u904e", args[1])  # 🚨 予算超過

    @patch.dict(os.environ, {"ALERT_ROOM_ID": "12345"})
    async def test_both_alerts_skipped_when_already_sent(self):
        # 使用率 105%、80%・100%両方送信済み -> "already_sent"
        from datetime import datetime as dt
        sent_time = dt(2026, 2, 5, 9, 0, 0)
        row = _make_row(10500, 10000, sent_80=sent_time, sent_100=sent_time)

        with patch("proactive_main.datetime") as mock_dt, \
             patch("proactive_main.asyncio.to_thread", new_callable=AsyncMock) as mock_thread, \
             patch("proactive_main.send_chatwork_message", new_callable=AsyncMock) as mock_send:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_now.strftime.return_value = "2026-02"
            mock_dt.now.return_value = mock_now
            mock_thread.return_value = row
            result = await self.func(self.pool)

        self.assertEqual(result, "already_sent")
        mock_send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
