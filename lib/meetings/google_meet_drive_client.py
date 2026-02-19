# lib/meetings/google_meet_drive_client.py
"""
Google Meet 録画ダウンロードクライアント

Google Meet の録画は自動的に Google Drive に保存される。
このクライアントは Drive API を使って録画ファイルを検索・ダウンロードする。

OAuth認証:
  - google_calendar と同じ OAuth トークンを再利用（同一 Google アカウント）
  - 必要スコープ: https://www.googleapis.com/auth/drive.readonly

Google Meetの録画ファイル特性:
  - MIMEタイプ: video/mp4
  - 名前パターン: "<会議名> (YYYY-MM-DD at HH:MM GMT).mp4"
  - 保存先: Google Drive / "Meet Recordings" フォルダ
  - 議事録テキスト: "Meet Recordings" 内に .docx/.txt として保存される場合あり

CLAUDE.md準拠:
  - §3-2 #8: エラーメッセージにPIIを含めない（メールアドレスをマスク）
  - §3-2 #11: リソースリーク防止（httpxは外部で管理）
  - §3-2 #16: APIキー等はSecret Manager経由（OAuth トークンはDBから取得）

Author: Claude Sonnet 4.6
Created: 2026-02-19
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Google Meet録画のMIMEタイプ
MEET_RECORDING_MIME_TYPE = "video/mp4"
MEET_TRANSCRIPT_MIME_TYPES = (
    "application/vnd.google-apps.document",  # Google Docs (自動文字起こし)
    "text/plain",
)

# 録画名のパターン（Googleが生成するフォルダ名）
MEET_RECORDINGS_FOLDER_NAME = "Meet Recordings"

# ダウンロードサイズ上限（Whisper API最大25MB）
MAX_DOWNLOAD_BYTES = 24 * 1024 * 1024  # 24MB（マージン込み）

# デフォルト検索日数
DEFAULT_SEARCH_DAYS = 2

# Drive API v3 エンドポイント（テスト用オーバーライド可）
DRIVE_API_BASE = os.environ.get("GOOGLE_DRIVE_API_BASE", "https://www.googleapis.com/drive/v3")


@dataclass
class MeetRecordingFile:
    """Google Meet録画ファイル情報"""

    file_id: str
    name: str
    mime_type: str
    size_bytes: Optional[int]
    created_time: Optional[datetime]
    web_view_link: Optional[str] = None
    parents: List[str] = field(default_factory=list)

    @property
    def is_video(self) -> bool:
        return self.mime_type == MEET_RECORDING_MIME_TYPE

    @property
    def estimated_duration_minutes(self) -> Optional[float]:
        """ファイルサイズから会議時間を推定（目安: 1分≒5MB）"""
        if self.size_bytes is None:
            return None
        return round(self.size_bytes / (5 * 1024 * 1024), 1)


class GoogleMeetDriveClient:
    """
    Google Meet録画をGoogle Driveから取得するクライアント。

    責務:
    - Drive APIを使って "Meet Recordings" フォルダ内の録画を検索
    - 録画ファイルのバイナリをダウンロード（Whisper入力用）
    - 自動生成された議事録テキスト（Docs）を取得

    非責務（Brain側が担当）:
    - 文字起こし処理（AudioProcessorが担当）
    - 議事録生成（MeetingMinutesGeneratorが担当）
    - ChatWork投稿判断
    """

    def __init__(
        self,
        oauth_access_token: Optional[str] = None,
        oauth_refresh_token: Optional[str] = None,
        oauth_client_id: Optional[str] = None,
        oauth_client_secret: Optional[str] = None,
        service_account_info: Optional[dict] = None,
        service_account_file: Optional[str] = None,
    ):
        self._oauth_access_token = oauth_access_token
        self._oauth_refresh_token = oauth_refresh_token
        self._oauth_client_id = oauth_client_id
        self._oauth_client_secret = oauth_client_secret
        self._sa_info = service_account_info
        self._sa_file = service_account_file
        self._service = None

    def _get_service(self):
        """Lazy-init Drive API service。OAuthトークンを優先して使用。"""
        if self._service is not None:
            return self._service

        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/drive.readonly"]

        # 優先1: OAuthトークン（管理画面から接続したユーザートークン）
        if self._oauth_access_token:
            from google.oauth2.credentials import Credentials as OAuthCredentials

            credentials = OAuthCredentials(
                token=self._oauth_access_token,
                refresh_token=self._oauth_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self._oauth_client_id,
                client_secret=self._oauth_client_secret,
                scopes=scopes,
            )
            self._service = build("drive", "v3", credentials=credentials)
            return self._service

        # 優先2: サービスアカウント情報（辞書）
        if self._sa_info:
            from google.oauth2 import service_account as sa_module
            credentials = sa_module.Credentials.from_service_account_info(
                self._sa_info, scopes=scopes
            )
            self._service = build("drive", "v3", credentials=credentials)
            return self._service

        # 優先3: サービスアカウントファイル
        sa_path = self._sa_file or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if sa_path:
            from google.oauth2 import service_account as sa_module
            credentials = sa_module.Credentials.from_service_account_file(
                sa_path, scopes=scopes
            )
            self._service = build("drive", "v3", credentials=credentials)
            return self._service

        # 優先4: Application Default Credentials
        from google.auth import default
        credentials, _ = default(scopes=scopes)
        self._service = build("drive", "v3", credentials=credentials)
        return self._service

    def _find_meet_recordings_folder_id(self) -> Optional[str]:
        """'Meet Recordings' フォルダのIDを取得する。"""
        service = self._get_service()
        query = (
            f"name='{MEET_RECORDINGS_FOLDER_NAME}' "
            "and mimeType='application/vnd.google-apps.folder' "
            "and trashed=false"
        )
        results = (
            service.files()
            .list(q=query, fields="files(id, name)", pageSize=1)
            .execute()
        )
        files = results.get("files", [])
        if files:
            folder_id = files[0]["id"]
            logger.debug("Found Meet Recordings folder: id=%s", folder_id)
            return folder_id
        logger.info("Meet Recordings folder not found in Drive")
        return None

    def find_recent_recordings(
        self,
        days_back: int = DEFAULT_SEARCH_DAYS,
        max_results: int = 20,
        folder_id: Optional[str] = None,
    ) -> List[MeetRecordingFile]:
        """
        最近のGoogle Meet録画ファイルを検索する。

        Args:
            days_back: 何日前まで検索するか（デフォルト: 2日）
            max_results: 最大取得件数
            folder_id: 検索対象フォルダID（省略時は "Meet Recordings" を自動探索）

        Returns:
            MeetRecordingFile のリスト（新しい順）
        """
        service = self._get_service()

        # フォルダIDの解決
        target_folder_id = folder_id or self._find_meet_recordings_folder_id()

        # 検索クエリの構築
        since = (
            datetime.now(timezone.utc) - timedelta(days=days_back)
        ).strftime("%Y-%m-%dT%H:%M:%S")

        query_parts = [
            f"mimeType='{MEET_RECORDING_MIME_TYPE}'",
            "trashed=false",
            f"createdTime>='{since}'",
        ]
        if target_folder_id:
            query_parts.append(f"'{target_folder_id}' in parents")

        query = " and ".join(query_parts)

        fields = (
            "files(id,name,mimeType,size,createdTime,webViewLink,parents)"
        )
        results = (
            service.files()
            .list(
                q=query,
                fields=fields,
                orderBy="createdTime desc",
                pageSize=max_results,
            )
            .execute()
        )

        recordings = []
        for f in results.get("files", []):
            created = None
            raw_created = f.get("createdTime")
            if raw_created:
                try:
                    created = datetime.fromisoformat(
                        raw_created.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            size_bytes = None
            raw_size = f.get("size")
            if raw_size:
                try:
                    size_bytes = int(raw_size)
                except ValueError:
                    pass

            recordings.append(
                MeetRecordingFile(
                    file_id=f["id"],
                    name=f.get("name", ""),
                    mime_type=f.get("mimeType", ""),
                    size_bytes=size_bytes,
                    created_time=created,
                    web_view_link=f.get("webViewLink"),
                    parents=f.get("parents", []),
                )
            )

        logger.info(
            "Found %d Meet recordings in the last %d days",
            len(recordings),
            days_back,
        )
        return recordings

    def download_recording_bytes(
        self,
        file_id: str,
        max_bytes: int = MAX_DOWNLOAD_BYTES,
    ) -> bytes:
        """
        録画ファイルをバイト列としてダウンロードする。

        Whisper APIの25MB制限に合わせて max_bytes でカット。

        Args:
            file_id: Google Drive ファイルID
            max_bytes: ダウンロード上限バイト数

        Returns:
            音声/動画バイト列
        """
        from googleapiclient.http import MediaIoBaseDownload
        import io

        service = self._get_service()
        request = service.files().get_media(fileId=file_id)

        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request, chunksize=4 * 1024 * 1024)

        done = False
        downloaded = 0
        while not done:
            status, done = downloader.next_chunk()
            downloaded = buf.tell()
            logger.debug("Download progress: %.0f%%", (status.progress() * 100))
            if downloaded >= max_bytes:
                logger.warning(
                    "Recording truncated at %d bytes (max_bytes=%d)",
                    downloaded,
                    max_bytes,
                )
                break

        data = buf.getvalue()
        logger.info("Downloaded %d bytes for file_id=[REDACTED]", len(data))
        return data

    def get_auto_transcript(self, file_id: str) -> Optional[str]:
        """
        Google Meetが自動生成した議事録テキスト（.docx形式）を取得する。

        NOTE: 自動文字起こし機能はGoogle Workspace有料プランで有効。
        有効でない場合はNoneを返す（Whisper文字起こしにフォールバック）。

        Args:
            file_id: 録画ファイルのGoogle Drive ID

        Returns:
            テキスト内容、または None（利用不可の場合）
        """
        service = self._get_service()

        # 録画と同じフォルダ内の .docx ファイルを探す
        try:
            file_meta = (
                service.files()
                .get(fileId=file_id, fields="parents,name")
                .execute()
            )
        except Exception as e:
            logger.debug("Failed to get file metadata: %s", type(e).__name__)
            return None

        parents = file_meta.get("parents", [])
        if not parents:
            return None

        recording_name = file_meta.get("name", "")
        # "〇〇 (2026-02-19 at 10:00 GMT).mp4" → "〇〇 (2026-02-19 at 10:00 GMT)"
        base_name = recording_name.rsplit(".", 1)[0] if "." in recording_name else recording_name

        # 同フォルダ内の Docs（自動議事録）を検索
        for parent_id in parents[:1]:
            query = (
                f"'{parent_id}' in parents "
                "and mimeType='application/vnd.google-apps.document' "
                "and trashed=false"
            )
            results = (
                service.files()
                .list(q=query, fields="files(id, name)", pageSize=5)
                .execute()
            )
            for doc in results.get("files", []):
                # 同じ会議名から生成されたドキュメントを特定
                doc_name = doc.get("name", "")
                if base_name[:20] in doc_name:  # 前方20文字でマッチング
                    try:
                        content = (
                            service.files()
                            .export(fileId=doc["id"], mimeType="text/plain")
                            .execute()
                        )
                        if isinstance(content, bytes):
                            text = content.decode("utf-8", errors="replace")
                        else:
                            text = str(content)
                        logger.info(
                            "Found auto-transcript for recording, %d chars",
                            len(text),
                        )
                        return text
                    except Exception as e:
                        logger.debug(
                            "Auto-transcript export failed: %s", type(e).__name__
                        )
        return None


def create_meet_drive_client_from_db(
    pool,
    organization_id: str,
) -> Optional[GoogleMeetDriveClient]:
    """
    DBに保存されたOAuthトークンからGoogleMeetDriveClientを生成する。

    google_calendar と同じOAuthトークンを再利用する。
    Google Driveへのアクセスには drive.readonly スコープが必要。

    Args:
        pool: SQLAlchemyのconnection pool
        organization_id: 組織ID

    Returns:
        GoogleMeetDriveClient or None
    """
    try:
        from sqlalchemy import text as sa_text

        with pool.connect() as conn:
            conn.execute(
                sa_text(
                    "SELECT set_config('app.current_organization_id', :org_id, true)"
                ),
                {"org_id": organization_id},
            )
            row = conn.execute(
                sa_text("""
                    SELECT access_token, refresh_token
                    FROM google_oauth_tokens
                    WHERE organization_id = :org_id
                      AND service_name = 'google_calendar'
                      AND is_active = TRUE
                    LIMIT 1
                """),
                {"org_id": organization_id},
            ).fetchone()

        if row:
            access_token = row[0]
            refresh_token = row[1]

            # 暗号化されている場合は復号
            encryption_key = os.getenv("GOOGLE_OAUTH_ENCRYPTION_KEY", "")
            if encryption_key:
                try:
                    from cryptography.fernet import Fernet
                    f = Fernet(encryption_key.encode())
                    access_token = f.decrypt(access_token.encode()).decode()
                    refresh_token = f.decrypt(refresh_token.encode()).decode()
                except Exception as e:
                    logger.warning(
                        "Google OAuth token decryption failed, using raw token: %s",
                        type(e).__name__,
                    )

            return GoogleMeetDriveClient(
                oauth_access_token=access_token,
                oauth_refresh_token=refresh_token,
                oauth_client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""),
                oauth_client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            )

    except Exception as e:
        logger.warning(
            "Failed to load OAuth token from DB for Google Meet Drive: %s",
            type(e).__name__,
        )

    # フォールバック: 環境変数ベース（サービスアカウント or ADC）
    sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if sa_file:
        logger.info("Using service account for Google Meet Drive client")
        return GoogleMeetDriveClient(service_account_file=sa_file)

    logger.warning("No credentials available for Google Meet Drive client")
    return None
