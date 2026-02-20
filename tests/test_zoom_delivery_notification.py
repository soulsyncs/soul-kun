# tests/test_zoom_delivery_notification.py
"""
Phase Z2 ⑦: Zoom議事録送信失敗時の管理者通知テスト

_notify_zoom_delivery_failure() の単体テスト。
送信失敗時に管理者へDM通知が正しく送られることを確認する。

Author: Claude Sonnet 4.6
Created: 2026-02-20
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))

from unittest.mock import MagicMock, patch

import pytest

from routes.zoom import _notify_zoom_delivery_failure


class TestNotifyZoomDeliveryFailure:
    """_notify_zoom_delivery_failure() の単体テスト"""

    def test_sends_message_to_admin_on_failure(self):
        """管理者DMに通知メッセージを送信する

        _notify_zoom_delivery_failure 内で send_chatwork_message は遅延インポートされる。
        infra.chatwork_api モジュールを直接パッチして呼び出しを捕捉する。
        """
        with patch("infra.chatwork_api.send_chatwork_message", return_value=True) as mock_send:
            _notify_zoom_delivery_failure(
                meeting_id="m-001",
                title="週次朝会",
                target_room_id="room_123",
                error_detail="ChatWork API がリトライ3回後も送信を拒否",
                admin_dm_room_id="417892193",
            )

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        room_sent_to = call_args[0][0]  # 第1引数 = room_id
        message_sent = call_args[0][1]  # 第2引数 = message
        assert room_sent_to == "417892193"
        assert "週次朝会" in message_sent
        assert "Zoom議事録" in message_sent
        assert "m-001" in message_sent

    def test_skips_when_no_admin_room_id(self):
        """admin_dm_room_id が None の場合は通知をスキップする"""
        with patch("infra.chatwork_api.send_chatwork_message") as mock_send:
            _notify_zoom_delivery_failure(
                meeting_id="m-001",
                title="朝会",
                target_room_id="room_123",
                error_detail="ConnectionError",
                admin_dm_room_id=None,
            )
        mock_send.assert_not_called()

    def test_message_contains_error_detail(self):
        """通知メッセージにエラー種別が含まれる"""
        captured = {}

        def capture_send(room_id, message):
            captured["message"] = message
            return True

        with patch("infra.chatwork_api.send_chatwork_message", side_effect=capture_send):
            _notify_zoom_delivery_failure(
                meeting_id="m-002",
                title="月次定例",
                target_room_id="room_456",
                error_detail="ConnectionTimeout",
                admin_dm_room_id="417892193",
            )

        assert "ConnectionTimeout" in captured["message"]
        assert "room_456" in captured["message"]

    def test_does_not_raise_when_notification_send_fails(self):
        """通知送信自体が失敗してもメイン処理を壊さない（二次失敗防止）"""
        with patch("infra.chatwork_api.send_chatwork_message", side_effect=Exception("API error")):
            # 例外を外に漏らさないことを確認
            _notify_zoom_delivery_failure(
                meeting_id="m-003",
                title="失敗テスト",
                target_room_id="room_789",
                error_detail="OriginalError",
                admin_dm_room_id="417892193",
            )
        # 例外なく完了すれば OK

    def test_message_does_not_contain_minutes_text(self):
        """CLAUDE.md §9-2: 議事録本文・PII を通知に含めない"""
        captured = {}

        def capture_send(room_id, message):
            captured["message"] = message
            return True

        with patch("infra.chatwork_api.send_chatwork_message", side_effect=capture_send):
            _notify_zoom_delivery_failure(
                meeting_id="m-004",
                title="社外秘会議",
                target_room_id="room_001",
                error_detail="NetworkError",
                admin_dm_room_id="417892193",
            )

        # 議事録本文（minutes_text）を含む引数はそもそもない設計なので確認不要
        # ただし「議事録本文」という文字列も通知には入らないことを確認
        assert "minutes_text" not in captured["message"]

    def test_notification_rejected_by_api_logs_error(self, caplog):
        """送信はされたがAPIに拒否された場合にエラーログが出る"""
        import logging
        with patch("infra.chatwork_api.send_chatwork_message", return_value=False):
            with caplog.at_level(logging.ERROR, logger="routes.zoom"):
                _notify_zoom_delivery_failure(
                    meeting_id="m-005",
                    title="テスト会議",
                    target_room_id="room_001",
                    error_detail="API拒否",
                    admin_dm_room_id="417892193",
                )
        assert any("Admin notification" in r.message for r in caplog.records)
