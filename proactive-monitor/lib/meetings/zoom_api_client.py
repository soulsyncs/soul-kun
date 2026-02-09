# lib/meetings/zoom_api_client.py
"""
Zoom Server-to-Server OAuth2 APIクライアント

Zoom built-in transcription (VTT) の取得を担当。
OAuth2トークンはインメモリキャッシュ（TTL 55分、実際は1時間有効）。

設計根拠:
- CLAUDE.md §3-2 #6: 同期HTTPはasyncio.to_thread()でラップ（呼び出し側）
- CLAUDE.md §3-2 #8: エラーメッセージにPIIを含めない
- CLAUDE.md §3-2 #16: APIキー等はSecret Manager経由

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 55 * 60  # 55分（実際は1時間有効、5分マージン）
# Zoom公式エンドポイント（環境変数でオーバーライド可能、テスト/プロキシ用）
ZOOM_OAUTH_URL = os.environ.get("ZOOM_OAUTH_URL", "https://zoom.us/oauth/token")
ZOOM_API_BASE = os.environ.get("ZOOM_API_BASE", "https://api.zoom.us/v2")


@dataclass
class ZoomToken:
    """Cached OAuth2 access token."""

    access_token: str
    expires_at: float


class ZoomAPIClient:
    """
    Zoom Server-to-Server OAuth2 APIクライアント。

    責務:
    - OAuth2トークン取得・キャッシュ・自動リフレッシュ
    - Recording一覧取得
    - VTTファイルダウンロード

    非責務（Brain側が担当）:
    - ChatWork投稿判断
    - PII除去（ZoomBrainInterfaceが担当）
    """

    def __init__(
        self,
        account_id: str,
        client_id: str,
        client_secret: str,
        timeout: float = 30.0,
    ):
        if not account_id or not client_id or not client_secret:
            raise ValueError(
                "Zoom credentials (account_id, client_id, client_secret) are all required"
            )
        self._account_id = account_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout
        self._token: Optional[ZoomToken] = None

    def _get_token(self) -> str:
        """Get valid access token, refreshing if expired."""
        now = time.time()
        if self._token and now < self._token.expires_at:
            return self._token.access_token

        response = httpx.post(
            ZOOM_OAUTH_URL,
            params={
                "grant_type": "account_credentials",
                "account_id": self._account_id,
            },
            auth=(self._client_id, self._client_secret),
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()
        self._token = ZoomToken(
            access_token=data["access_token"],
            expires_at=now + TOKEN_TTL_SECONDS,
        )
        logger.info("Zoom OAuth token refreshed")
        return self._token.access_token

    def _api_get(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make authenticated GET request to Zoom API."""
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{ZOOM_API_BASE}{path}"

        response = httpx.get(
            url, headers=headers, params=params, timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()

    def list_recordings(
        self,
        user_id: str = "me",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        page_size: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        List cloud recordings for a user.

        Args:
            user_id: Zoom user ID or email (default "me")
            from_date: YYYY-MM-DD start date
            to_date: YYYY-MM-DD end date
            page_size: Results per page (max 300)

        Returns:
            List of meeting recording objects
        """
        params: Dict[str, Any] = {"page_size": min(page_size, 300)}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        data = self._api_get(f"/users/{user_id}/recordings", params=params)
        return data.get("meetings", [])

    def get_meeting_recordings(self, meeting_id: str) -> Dict[str, Any]:
        """Get recording details for a specific meeting."""
        return self._api_get(f"/meetings/{meeting_id}/recordings")

    def download_transcript(self, download_url: str) -> str:
        """
        Download VTT transcript file from Zoom.

        Zoom download URLs require access_token as query param.

        Args:
            download_url: The download_url from recording file object

        Returns:
            VTT file content as string
        """
        token = self._get_token()
        separator = "&" if "?" in download_url else "?"
        url_with_token = f"{download_url}{separator}access_token={token}"

        response = httpx.get(url_with_token, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
        return response.text

    def find_transcript_url(
        self, recording_data: Dict[str, Any]
    ) -> Optional[str]:
        """
        Find the VTT transcript download URL from recording data.

        Zoom recording_files has file_type="TRANSCRIPT" for VTT files.

        Returns:
            Download URL string, or None if no transcript available
        """
        for file_info in recording_data.get("recording_files", []):
            if file_info.get("file_type") == "TRANSCRIPT":
                return file_info.get("download_url")
        return None


def create_zoom_client_from_secrets() -> ZoomAPIClient:
    """
    Create ZoomAPIClient using GCP Secret Manager credentials.

    Secret names:
    - zoom-account-id
    - zoom-client-id
    - zoom-client-secret

    Falls back to environment variables for local development:
    - ZOOM_ACCOUNT_ID
    - ZOOM_CLIENT_ID
    - ZOOM_CLIENT_SECRET
    """
    from lib.secrets import get_secret_cached

    account_id = get_secret_cached("zoom-account-id")
    client_id = get_secret_cached("zoom-client-id")
    client_secret = get_secret_cached("zoom-client-secret")

    return ZoomAPIClient(
        account_id=account_id,
        client_id=client_id,
        client_secret=client_secret,
    )
