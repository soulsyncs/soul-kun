"""
gmail_client.py - Gmail API クライアント

Gmail watch() + Pub/Sub 連携で届いた通知をもとに
新着メールを取得する。

【前提条件】
  - Cloud Run サービスアカウントに以下の権限が必要:
    * Gmail API（Domain-wide delegation で対象メールボックスへのアクセス）
    * または gmail.readonly スコープの OAuth2 認証
  - Secret Manager に "gmail-service-account-json" を保存済み
"""
import base64
import json
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

# Google API が利用可能な場合のみ import
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    logger.warning("google-api-python-client が未インストール。Gmail連携は無効。")


class GmailClient:
    """
    Gmail API クライアント。
    サービスアカウント + Domain-wide delegation を使用する。
    """

    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

    def __init__(self, impersonated_email: str):
        """
        Args:
            impersonated_email: 監視するGmailアドレス
                                 (e.g., "recruit@soulsyncs.jp")
        """
        self.email = impersonated_email
        self._service = None

        if not GOOGLE_API_AVAILABLE:
            raise RuntimeError(
                "google-api-python-client が未インストールです。"
                "requirements.txt を確認してください。"
            )

    def _get_service(self):
        """Gmail API サービスを初期化（遅延初期化）"""
        if self._service is not None:
            return self._service

        # Secret Manager からサービスアカウントキーを取得
        try:
            from lib.secrets import get_secret_cached
            sa_json = get_secret_cached("gmail-service-account-json")
            sa_info = json.loads(sa_json)
        except Exception as e:
            logger.error(f"サービスアカウントキー取得失敗: {e}")
            raise

        creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=self.SCOPES,
        )
        # Domain-wide delegation で指定メールボックスに成り代わる
        delegated_creds = creds.with_subject(self.email)

        self._service = build("gmail", "v1", credentials=delegated_creds)
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
            # history API で新着メッセージIDを取得
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

        Args:
            message_id: Gmail メッセージID

        Returns:
            生のメールバイト列、取得失敗時は None
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

        Args:
            topic_name: Pub/Sub トピック名
                         (e.g., "projects/my-project/topics/gmail-job-inquiry")

        Returns:
            watch() の結果 {"historyId": "xxx", "expiration": "xxx"}
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
