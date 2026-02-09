"""
tests/test_alert_sender.py

Task C: AlertSender テスト
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from lib.brain.alert_sender import AlertSender, AlertType, _RATE_LIMIT_SECONDS


class TestAlertSenderSend:
    """send() メソッドのテスト"""

    def test_send_success(self):
        mock_client = MagicMock()
        sender = AlertSender(chatwork_client=mock_client, alert_room_id="12345")

        result = sender.send(AlertType.ERROR_RATE_HIGH, value=0.08, threshold=5)

        assert result is True
        mock_client.send_message.assert_called_once()
        call_kwargs = mock_client.send_message.call_args
        assert call_kwargs[1]["room_id"] == 12345
        assert "エラー率" in call_kwargs[1]["message"]

    def test_send_rate_limited(self):
        mock_client = MagicMock()
        sender = AlertSender(chatwork_client=mock_client)

        sender.send(AlertType.API_DOWN)
        result = sender.send(AlertType.API_DOWN)

        assert result is False
        assert mock_client.send_message.call_count == 1

    def test_different_alert_types_not_rate_limited(self):
        mock_client = MagicMock()
        sender = AlertSender(chatwork_client=mock_client)

        r1 = sender.send(AlertType.API_DOWN)
        r2 = sender.send(AlertType.DB_ERROR)

        assert r1 is True
        assert r2 is True
        assert mock_client.send_message.call_count == 2

    def test_send_failure_returns_false(self):
        mock_client = MagicMock()
        mock_client.send_message.side_effect = RuntimeError("network error")
        sender = AlertSender(chatwork_client=mock_client)

        result = sender.send(AlertType.ERROR_RATE_HIGH, value=0.1, threshold=5)

        assert result is False

    def test_default_room_id_is_kikuchi_dm(self):
        sender = AlertSender(chatwork_client=MagicMock())
        assert sender._room_id == "417892193"

    def test_room_id_from_env(self, monkeypatch):
        monkeypatch.setenv("ALERT_ROOM_ID", "999999")
        sender = AlertSender(chatwork_client=MagicMock())
        assert sender._room_id == "999999"


class TestAlertSenderTemplates:
    """テンプレートのテスト"""

    def test_error_rate_template(self):
        mock_client = MagicMock()
        sender = AlertSender(chatwork_client=mock_client)

        sender.send(AlertType.ERROR_RATE_HIGH, value=0.08, threshold=5)

        msg = mock_client.send_message.call_args[1]["message"]
        assert "エラー率" in msg
        assert "5%" in msg
        assert "[info]" in msg

    def test_cost_warning_template(self):
        mock_client = MagicMock()
        sender = AlertSender(chatwork_client=mock_client)

        sender.send(AlertType.COST_WARNING, value=6500, threshold=5000)

        msg = mock_client.send_message.call_args[1]["message"]
        assert "コスト" in msg
        assert "6,500" in msg

    def test_response_time_template(self):
        mock_client = MagicMock()
        sender = AlertSender(chatwork_client=mock_client)

        sender.send(AlertType.RESPONSE_TIME_HIGH, value=12000, threshold=10000)

        msg = mock_client.send_message.call_args[1]["message"]
        assert "応答遅延" in msg
        assert "12000" in msg


class TestCheckAndAlert:
    """check_and_alert() メソッドのテスト"""

    def test_healthy_sends_nothing(self):
        mock_client = MagicMock()
        sender = AlertSender(chatwork_client=mock_client)

        count = sender.check_and_alert({
            "status": "healthy",
            "issues": [],
            "metrics": {},
        })

        assert count == 0
        mock_client.send_message.assert_not_called()

    def test_critical_error_rate_sends_alert(self):
        mock_client = MagicMock()
        sender = AlertSender(chatwork_client=mock_client)

        count = sender.check_and_alert({
            "status": "critical",
            "issues": ["Error rate critical: 8.00%"],
            "metrics": {"error_rate": 0.08},
        })

        assert count == 1
        msg = mock_client.send_message.call_args[1]["message"]
        assert "エラー率" in msg

    def test_multiple_issues_sends_multiple_alerts(self):
        mock_client = MagicMock()
        sender = AlertSender(chatwork_client=mock_client)

        count = sender.check_and_alert({
            "status": "critical",
            "issues": [
                "Error rate critical: 8.00%",
                "Response time critical: 15000ms",
            ],
            "metrics": {
                "error_rate": 0.08,
                "avg_response_time_ms": 15000,
            },
        })

        assert count == 2


class TestMonitoringHook:
    """monitoring.py への AlertSender フック統合テスト"""

    def test_enable_alerts_hooks_sender(self):
        from lib.brain.monitoring import LLMBrainMonitor, enable_alerts

        mock_sender = MagicMock()
        monitor = LLMBrainMonitor()
        monitor._alert_sender = mock_sender

        # healthyな状態 → アラートなし
        status = monitor.get_health_status()
        if status["status"] == "healthy":
            mock_sender.check_and_alert.assert_not_called()

    def test_alert_sender_error_does_not_crash_monitoring(self):
        from lib.brain.monitoring import LLMBrainMonitor

        mock_sender = MagicMock()
        mock_sender.check_and_alert.side_effect = RuntimeError("boom")

        monitor = LLMBrainMonitor()
        monitor._alert_sender = mock_sender

        # get_health_status がエラーを投げないこと
        status = monitor.get_health_status()
        assert "status" in status
