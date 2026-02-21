"""
gmail_client.py - Gmail API クライアント

Gmail watch() + Pub/Sub 連携で届いた通知をもとに
新着メールを取得する。

【認証方式】
  通常のGmailアカウント（Google Workspace なし）対応。
  OAuth2 リフレッシュトークンを Secret Manager に保存して使用する。
  ※ リフレッシュトークンは初回セットアップ時に1回だけ取得（setup.md参照）

【Secret Manager に保存するシークレット】
  - gmail-oauth-refresh-token  : リフレッシュトークン
  - gmail-oauth-client-id      : OAuthクライアントID
  - gmail-oauth-client-secret  : OAuthクライアントシークレット
"""
import base64
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Google API が利用可能な場合のみ import
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    logger.warning("google-api-python-client が未インストール。Gmail連携は無効。")


class GmailClient:
    """
    Gmail API クライアント（OAuth2 リフレッシュトークン認証）。
    通常のGmailアカウント（Google Workspace 不要）で動作する。
    """

    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
    TOKEN_URI = "https://oauth2.googleapis.com/token"

    def __init__(self, email: str):
        """
        Args:
            email: 監視するGmailアドレス（e.g., "master.soulsyncs@gmail.com"）
        """
        self.email = email
        self._service = None

        if not GOOGLE_API_AVAILABLE:
            raise RuntimeError(
                "google-api-python-client が未インストールです。"
                "requirements.txt を確認してください。"
            )

    def _get_credentials(self) -> Credentials:
        """
        Secret Manager から OAuth2 認証情報を取得する。
        リフレッシュトークンを使ってアクセストークンを自動更新する。
        """
        from lib.secrets import get_secret_cached

        refresh_token = get_secret_cached("gmail-oauth-refresh-token")
        client_id = get_secret_cached("gmail-oauth-client-id")
        client_secret = get_secret_cached("gmail-oauth-client-secret")

        creds = Credentials(
            token=None,  # アクセストークンは自動取得
            refresh_token=refresh_token,
            token_uri=self.TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=self.SCOPES,
        )

        # アクセストークンを取得（リフレッシュトークンから自動生成）
        if not creds.valid:
            creds.refresh(Request())

        return creds

    def _get_service(self):
        """Gmail API サービスを初期化（遅延初期化）"""
        if self._service is not None:
            return self._service

        try:
            creds = self._get_credentials()
        except Exception as e:
            logger.error(f"Gmail OAuth2認証失敗: {e}")
            raise

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def get_new_messages_since(self, history_id: str) -> List[bytes]:
        """
        指定された historyId 以降の新着メールを取得して
        生のバイト列（RFC 2822形式）のリストを返す。

        Args:
            history_id: Gmail watch() が通知してきた historyId

        Returns:
            各メールの生バイト列のリスト
        """
        service = self._get_service()

        try:
            history_response = service.users().history().list(
                userId="me",
                startHistoryId=history_id,
                historyTypes=["messageAdded"],
            ).execute()
        except HttpError as e:
            if e.resp.status == 404:
                # historyId が古すぎる場合（Gmail は7日間しか保持しない）
                logger.warning(f"historyId {history_id} が無効です（古すぎる可能性）")
                return []
            raise

        histories = history_response.get("history", [])
        if not histories:
            return []

        # ページネーション対応（nextPageToken があれば全ページ取得）
        all_histories = list(histories)
        while "nextPageToken" in history_response:
            history_response = service.users().history().list(
                userId="me",
                startHistoryId=history_id,
                historyTypes=["messageAdded"],
                pageToken=history_response["nextPageToken"],
            ).execute()
            all_histories.extend(history_response.get("history", []))

        # 重複排除
        message_ids = set()
        for history in all_histories:
            for added in history.get("messagesAdded", []):
                message_ids.add(added["message"]["id"])

        # 各メールを取得
        raw_messages = []
        for msg_id in message_ids:
            try:
                raw_bytes = self._fetch_raw_message(msg_id)
                if raw_bytes:
                    raw_messages.append(raw_bytes)
            except Exception as e:
                logger.error(f"メッセージ取得失敗 id={msg_id}: {e}")
                continue

        logger.info(f"{len(raw_messages)} 件の新着メールを取得")
        return raw_messages

    def _fetch_raw_message(self, message_id: str) -> Optional[bytes]:
        """
        指定IDのメールを RFC 2822 形式のバイト列で取得する。
        """
        service = self._get_service()

        response = service.users().messages().get(
            userId="me",
            id=message_id,
            format="raw",
        ).execute()

        raw = response.get("raw")
        if not raw:
            return None

        # Gmail API は base64url エンコードで返す（パディングを正確に計算）
        padding = (4 - len(raw) % 4) % 4
        return base64.urlsafe_b64decode(raw + "=" * padding)

    def setup_watch(self, topic_name: str) -> dict:
        """
        Gmail watch() を設定する（初回セットアップ時のみ実行）。
        Gmail は7日ごとに再設定が必要（Cloud Scheduler で自動化推奨）。
        """
        service = self._get_service()

        response = service.users().watch(
            userId="me",
            body={
                "labelIds": ["INBOX"],
                "topicName": topic_name,
            },
        ).execute()

        logger.info(
            f"Gmail watch設定完了: historyId={response.get('historyId')}, "
            f"expiration={response.get('expiration')}"
        )
        return response

    def stop_watch(self) -> None:
        """Gmail watch() を停止する（主にテスト用）"""
        service = self._get_service()
        service.users().stop(userId="me").execute()
        logger.info("Gmail watch停止")
