# tests/test_zoom_webhook_verify.py
"""
Zoom Webhook署名検証のテスト

Author: Claude Opus 4.6
Created: 2026-02-13
"""

import hashlib
import hmac
import time

import pytest

from lib.meetings.zoom_webhook_verify import (
    MAX_TIMESTAMP_AGE_SECONDS,
    generate_zoom_url_validation_response,
    verify_zoom_webhook_signature,
)


class TestVerifyZoomWebhookSignature:
    """署名検証テスト"""

    SECRET = "test-webhook-secret-token"
    BODY = b'{"event":"recording.completed","payload":{}}'

    @pytest.fixture(autouse=True)
    def _set_timestamp(self):
        """テスト実行時に動的にタイムスタンプを生成（タイムアウト防止）"""
        self.TIMESTAMP = str(int(time.time()))

    def _make_signature(self, body: bytes, timestamp: str, secret: str) -> str:
        """テスト用に正しい署名を生成"""
        message = f"v0:{timestamp}:{body.decode('utf-8')}"
        sig = hmac.new(
            secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"v0={sig}"

    def test_valid_signature(self):
        sig = self._make_signature(self.BODY, self.TIMESTAMP, self.SECRET)
        assert verify_zoom_webhook_signature(
            self.BODY, self.TIMESTAMP, sig, self.SECRET
        ) is True

    def test_invalid_signature(self):
        assert verify_zoom_webhook_signature(
            self.BODY, self.TIMESTAMP, "v0=invalid_hex", self.SECRET
        ) is False

    def test_wrong_secret(self):
        sig = self._make_signature(self.BODY, self.TIMESTAMP, "wrong-secret")
        assert verify_zoom_webhook_signature(
            self.BODY, self.TIMESTAMP, sig, self.SECRET
        ) is False

    def test_tampered_body(self):
        sig = self._make_signature(self.BODY, self.TIMESTAMP, self.SECRET)
        tampered = b'{"event":"recording.completed","payload":{"hacked":true}}'
        assert verify_zoom_webhook_signature(
            tampered, self.TIMESTAMP, sig, self.SECRET
        ) is False

    def test_expired_timestamp(self):
        old_ts = str(int(time.time()) - MAX_TIMESTAMP_AGE_SECONDS - 10)
        sig = self._make_signature(self.BODY, old_ts, self.SECRET)
        assert verify_zoom_webhook_signature(
            self.BODY, old_ts, sig, self.SECRET
        ) is False

    def test_future_timestamp(self):
        future_ts = str(int(time.time()) + MAX_TIMESTAMP_AGE_SECONDS + 10)
        sig = self._make_signature(self.BODY, future_ts, self.SECRET)
        assert verify_zoom_webhook_signature(
            self.BODY, future_ts, sig, self.SECRET
        ) is False

    def test_missing_body(self):
        assert verify_zoom_webhook_signature(
            b"", self.TIMESTAMP, "v0=abc", self.SECRET
        ) is False

    def test_missing_timestamp(self):
        assert verify_zoom_webhook_signature(
            self.BODY, "", "v0=abc", self.SECRET
        ) is False

    def test_missing_signature(self):
        assert verify_zoom_webhook_signature(
            self.BODY, self.TIMESTAMP, "", self.SECRET
        ) is False

    def test_missing_secret(self):
        assert verify_zoom_webhook_signature(
            self.BODY, self.TIMESTAMP, "v0=abc", ""
        ) is False

    def test_non_numeric_timestamp(self):
        assert verify_zoom_webhook_signature(
            self.BODY, "not-a-number", "v0=abc", self.SECRET
        ) is False

    def test_timestamp_within_window(self):
        """境界値: ちょうど制限内のタイムスタンプ"""
        edge_ts = str(int(time.time()) - MAX_TIMESTAMP_AGE_SECONDS + 5)
        sig = self._make_signature(self.BODY, edge_ts, self.SECRET)
        assert verify_zoom_webhook_signature(
            self.BODY, edge_ts, sig, self.SECRET
        ) is True


class TestGenerateUrlValidationResponse:
    """URL validation チャレンジ応答テスト"""

    def test_response_structure(self):
        result = generate_zoom_url_validation_response("test-token", "secret")
        assert "plainToken" in result
        assert "encryptedToken" in result

    def test_plain_token_returned(self):
        result = generate_zoom_url_validation_response("my-plain-token", "secret")
        assert result["plainToken"] == "my-plain-token"

    def test_encrypted_token_is_hmac(self):
        secret = "my-secret"
        token = "my-token"
        result = generate_zoom_url_validation_response(token, secret)
        expected = hmac.new(
            secret.encode("utf-8"),
            token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        assert result["encryptedToken"] == expected

    def test_different_secrets_produce_different_tokens(self):
        r1 = generate_zoom_url_validation_response("token", "secret1")
        r2 = generate_zoom_url_validation_response("token", "secret2")
        assert r1["encryptedToken"] != r2["encryptedToken"]
