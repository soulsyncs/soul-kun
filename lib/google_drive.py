"""
Google Drive 連携モジュール

Googleドライブからファイルを取得し、ソウルくんのナレッジDBに反映するための
ライブラリを提供します。

使用例:
    from lib.google_drive import GoogleDriveClient

    client = GoogleDriveClient()
    changes = await client.get_changes(page_token)
    for change in changes:
        file_content = await client.download_file(change.file_id)

設計ドキュメント:
    docs/06_phase3_google_drive_integration.md
"""

import os
import io
import asyncio
from typing import Optional, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
import logging

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

from lib.config import get_settings

# 動的部署マッピング（オプショナル）
# DB接続がない場合は静的マッピングにフォールバック
try:
    from lib.department_mapping import (
        DepartmentMappingService,
        resolve_legacy_department_id,
        LEGACY_DEPARTMENT_ID_TO_NAME,
    )
    DEPARTMENT_MAPPING_AVAILABLE = True
except ImportError:
    DEPARTMENT_MAPPING_AVAILABLE = False
    DepartmentMappingService = None


logger = logging.getLogger(__name__)


# ================================================================
# データクラス定義
# ================================================================

@dataclass
class DriveFile:
    """Googleドライブのファイル情報"""
    id: str
    name: str
    mime_type: str
    size: Optional[int]
    modified_time: Optional[datetime]
    created_time: Optional[datetime]
    parents: list[str]
    web_view_link: Optional[str]
    trashed: bool = False

    # 処理用の追加情報
    folder_path: list[str] = field(default_factory=list)

    @property
    def file_extension(self) -> str:
        """ファイル拡張子を取得"""
        if '.' in self.name:
            return self.name.rsplit('.', 1)[-1].lower()
        return ''

    @property
    def is_supported_type(self) -> bool:
        """サポートされているファイル形式かどうか"""
        supported_extensions = {
            'pdf', 'docx', 'doc', 'txt', 'md',
            'html', 'htm', 'xlsx', 'xls', 'pptx', 'ppt'
        }
        return self.file_extension in supported_extensions


@dataclass
class DriveChange:
    """Googleドライブの変更情報"""
    file_id: str
    removed: bool
    file: Optional[DriveFile]
    change_type: str  # 'added', 'modified', 'removed'
    time: Optional[datetime]


@dataclass
class SyncResult:
    """同期結果"""
    files_checked: int = 0
    files_added: int = 0
    files_updated: int = 0
    files_deleted: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    new_page_token: Optional[str] = None
    failed_files: list = field(default_factory=list)


# ================================================================
# 設定
# ================================================================

# サポートするファイル形式
SUPPORTED_MIME_TYPES = {
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
    'application/msword',  # .doc
    'text/plain',
    'text/markdown',
    'text/html',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # .xlsx
    'application/vnd.ms-excel',  # .xls
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # .pptx
    'application/vnd.ms-powerpoint',  # .ppt
}

# 除外するファイル名パターン
EXCLUDE_PATTERNS = [
    lambda name: name.startswith('.'),      # 隠しファイル
    lambda name: name.startswith('~$'),     # Office一時ファイル
    lambda name: name.endswith('.tmp'),     # 一時ファイル
    lambda name: name.endswith('.bak'),     # バックアップファイル
]

# 最大ファイルサイズ（バイト）
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


# ================================================================
# Google Drive クライアント
# ================================================================

class GoogleDriveClient:
    """
    Google Drive API クライアント

    使用例:
        client = GoogleDriveClient()

        # ページトークンを取得（初回）
        token = await client.get_start_page_token()

        # 変更を取得
        changes, new_token = await client.get_changes(token)
        for change in changes:
            print(f"{change.change_type}: {change.file.name}")

        # ファイルをダウンロード
        content = await client.download_file(file_id)
    """

    def __init__(
        self,
        service_account_file: Optional[str] = None,
        service_account_info: Optional[dict] = None,
    ):
        """
        Args:
            service_account_file: サービスアカウントJSONファイルのパス
            service_account_info: サービスアカウント情報の辞書（Secret Manager等から取得時）
        """
        self.settings = get_settings()

        # 認証情報の取得
        if service_account_info:
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
        elif service_account_file:
            credentials = service_account.Credentials.from_service_account_file(
                service_account_file,
                scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
        else:
            # 環境変数からパスを取得
            sa_path = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
            if sa_path:
                credentials = service_account.Credentials.from_service_account_file(
                    sa_path,
                    scopes=['https://www.googleapis.com/auth/drive.readonly']
                )
            else:
                # Application Default Credentials を使用
                from google.auth import default
                credentials, _ = default(
                    scopes=['https://www.googleapis.com/auth/drive.readonly']
                )

        self.service = build('drive', 'v3', credentials=credentials)

        # フォルダIDキャッシュ（パフォーマンス向上）
        self._folder_cache: dict[str, dict] = {}

    # ================================================================
    # ページトークン操作
    # ================================================================

    async def get_start_page_token(self) -> str:
        """
        初期ページトークンを取得

        初回同期時に呼び出し、以降はこのトークン以降の変更を取得。
        """
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.service.changes().getStartPageToken().execute()
        )
        return response.get('startPageToken')

    # ================================================================
    # 変更取得
    # ================================================================

    async def get_changes(
        self,
        page_token: str,
        root_folder_id: Optional[str] = None,
    ) -> tuple[list[DriveChange], str]:
        """
        前回のページトークン以降の変更を取得

        Args:
            page_token: 前回の同期時のページトークン
            root_folder_id: 監視対象のルートフォルダID（指定時はその配下のみ）

        Returns:
            (変更リスト, 新しいページトークン)
        """
        loop = asyncio.get_event_loop()
        changes: list[DriveChange] = []
        current_token = page_token

        while True:
            response = await loop.run_in_executor(
                None,
                lambda token=current_token: self.service.changes().list(
                    pageToken=token,
                    includeRemoved=True,
                    includeItemsFromAllDrives=False,
                    supportsAllDrives=False,
                    fields='nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,size,modifiedTime,createdTime,parents,webViewLink,trashed))'
                ).execute()
            )

            for change_data in response.get('changes', []):
                file_id = change_data.get('fileId')
                removed = change_data.get('removed', False)
                file_data = change_data.get('file')

                # ファイル情報の変換
                drive_file = None
                if file_data:
                    drive_file = self._parse_file(file_data)

                # 変更タイプの判定
                if removed or (drive_file and drive_file.trashed):
                    change_type = 'removed'
                else:
                    # ファイルが存在するかどうかで判定（単純化）
                    change_type = 'modified'  # 新規か更新かはDB側で判定

                change = DriveChange(
                    file_id=file_id,
                    removed=removed,
                    file=drive_file,
                    change_type=change_type,
                    time=datetime.now()
                )

                # ルートフォルダでフィルタ
                if root_folder_id and drive_file:
                    if not await self._is_in_folder(drive_file, root_folder_id):
                        continue

                changes.append(change)

            # 次のページがあるか確認
            if 'nextPageToken' in response:
                current_token = response['nextPageToken']
            else:
                # 全ページを取得完了
                new_page_token = response.get('newStartPageToken', current_token)
                return changes, new_page_token

    async def _is_in_folder(
        self,
        file: DriveFile,
        root_folder_id: str
    ) -> bool:
        """ファイルが指定フォルダの配下にあるかチェック"""
        if not file.parents:
            return False

        # 親フォルダを再帰的にチェック
        checked = set()
        to_check = list(file.parents)

        while to_check:
            folder_id = to_check.pop()

            if folder_id in checked:
                continue
            checked.add(folder_id)

            if folder_id == root_folder_id:
                return True

            # 親フォルダを取得
            folder_info = await self._get_folder_info(folder_id)
            if folder_info and folder_info.get('parents'):
                to_check.extend(folder_info['parents'])

        return False

    # ================================================================
    # フォルダ操作
    # ================================================================

    async def get_folder_path(self, file: DriveFile) -> list[str]:
        """
        ファイルのフォルダパスを取得

        例: ["ソウルくん用フォルダ", "社員限定", "業務マニュアル"]
        """
        if not file.parents:
            return []

        path = []
        current_id = file.parents[0]  # 最初の親フォルダ

        while current_id:
            folder_info = await self._get_folder_info(current_id)
            if not folder_info:
                break

            path.insert(0, folder_info['name'])

            # 親フォルダがあれば続行
            parents = folder_info.get('parents', [])
            current_id = parents[0] if parents else None

        return path

    async def _get_folder_info(self, folder_id: str) -> Optional[dict]:
        """フォルダ情報を取得（キャッシュ付き）"""
        if folder_id in self._folder_cache:
            return self._folder_cache[folder_id]

        try:
            loop = asyncio.get_event_loop()
            folder = await loop.run_in_executor(
                None,
                lambda: self.service.files().get(
                    fileId=folder_id,
                    fields='id,name,parents'
                ).execute()
            )
            self._folder_cache[folder_id] = folder
            return folder
        except HttpError as e:
            if e.resp.status == 404:
                return None
            raise

    # ================================================================
    # ファイル操作
    # ================================================================

    async def get_file(self, file_id: str) -> Optional[DriveFile]:
        """ファイル情報を取得"""
        try:
            loop = asyncio.get_event_loop()
            file_data = await loop.run_in_executor(
                None,
                lambda: self.service.files().get(
                    fileId=file_id,
                    fields='id,name,mimeType,size,modifiedTime,createdTime,parents,webViewLink,trashed'
                ).execute()
            )
            return self._parse_file(file_data)
        except HttpError as e:
            if e.resp.status == 404:
                return None
            raise

    async def download_file(self, file_id: str) -> bytes:
        """
        ファイルをダウンロード

        Args:
            file_id: GoogleドライブのファイルID

        Returns:
            ファイルのバイナリデータ

        Raises:
            ValueError: ファイルサイズが大きすぎる場合
            HttpError: API エラー
        """
        loop = asyncio.get_event_loop()

        # ファイル情報を取得してサイズをチェック
        file_info = await self.get_file(file_id)
        if file_info and file_info.size and file_info.size > MAX_FILE_SIZE:
            raise ValueError(
                f"ファイルサイズが大きすぎます: {file_info.size} bytes "
                f"(最大: {MAX_FILE_SIZE} bytes)"
            )

        # ダウンロード
        request = self.service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()

        downloader = MediaIoBaseDownload(buffer, request)
        done = False

        while not done:
            status, done = await loop.run_in_executor(
                None,
                downloader.next_chunk
            )
            if status:
                logger.debug(f"Download progress: {int(status.progress() * 100)}%")

        return buffer.getvalue()

    async def list_files_in_folder(
        self,
        folder_id: str,
        recursive: bool = False
    ) -> AsyncIterator[DriveFile]:
        """
        フォルダ内のファイルを一覧取得

        Args:
            folder_id: フォルダID
            recursive: サブフォルダも含めるか

        Yields:
            DriveFile オブジェクト
        """
        loop = asyncio.get_event_loop()
        page_token = None

        while True:
            response = await loop.run_in_executor(
                None,
                lambda token=page_token: self.service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    pageSize=100,
                    pageToken=token,
                    fields='nextPageToken,files(id,name,mimeType,size,modifiedTime,createdTime,parents,webViewLink,trashed)'
                ).execute()
            )

            for file_data in response.get('files', []):
                file = self._parse_file(file_data)

                # フォルダの場合、再帰的に処理
                if file.mime_type == 'application/vnd.google-apps.folder':
                    if recursive:
                        async for sub_file in self.list_files_in_folder(
                            file.id, recursive=True
                        ):
                            yield sub_file
                else:
                    yield file

            page_token = response.get('nextPageToken')
            if not page_token:
                break

    # ================================================================
    # ユーティリティ
    # ================================================================

    def _parse_file(self, file_data: dict) -> DriveFile:
        """APIレスポンスをDriveFileオブジェクトに変換"""
        modified_time = None
        if file_data.get('modifiedTime'):
            modified_time = datetime.fromisoformat(
                file_data['modifiedTime'].replace('Z', '+00:00')
            )

        created_time = None
        if file_data.get('createdTime'):
            created_time = datetime.fromisoformat(
                file_data['createdTime'].replace('Z', '+00:00')
            )

        return DriveFile(
            id=file_data['id'],
            name=file_data['name'],
            mime_type=file_data.get('mimeType', ''),
            size=int(file_data['size']) if file_data.get('size') else None,
            modified_time=modified_time,
            created_time=created_time,
            parents=file_data.get('parents', []),
            web_view_link=file_data.get('webViewLink'),
            trashed=file_data.get('trashed', False),
        )

    def should_skip_file(self, file: DriveFile) -> tuple[bool, Optional[str]]:
        """
        ファイルをスキップすべきかチェック

        Returns:
            (スキップすべきか, 理由)
        """
        # 除外パターンチェック
        for pattern in EXCLUDE_PATTERNS:
            if pattern(file.name):
                return True, f"除外パターンに一致: {file.name}"

        # MIMEタイプチェック
        if file.mime_type not in SUPPORTED_MIME_TYPES:
            # Google Docs形式は将来対応
            if file.mime_type.startswith('application/vnd.google-apps'):
                return True, f"Google Docs形式は未対応: {file.mime_type}"
            return True, f"サポートされていないファイル形式: {file.mime_type}"

        # ファイルサイズチェック
        if file.size and file.size > MAX_FILE_SIZE:
            return True, f"ファイルサイズ超過: {file.size} bytes"

        return False, None

    def clear_cache(self):
        """キャッシュをクリア"""
        self._folder_cache.clear()


# ================================================================
# フォルダ→権限マッピング
# ================================================================

@dataclass
class FolderMappingConfig:
    """フォルダマッピング設定"""

    # 機密区分マッピング
    CLASSIFICATION_MAP: dict[str, str] = field(default_factory=lambda: {
        # 日本語
        "全社共有": "public",
        "社員限定": "internal",
        "役員限定": "restricted",
        "部署別": "confidential",
        # 英語（バックアップ）
        "public": "public",
        "internal": "internal",
        "restricted": "restricted",
        "confidential": "confidential",
    })

    # カテゴリマッピング
    CATEGORY_MAP: dict[str, str] = field(default_factory=lambda: {
        # カテゴリA: 理念・哲学
        "mvv": "A", "理念": "A", "ミッション": "A", "ビジョン": "A",
        "バリュー": "A", "会社紹介": "A", "会社概要": "A", "沿革": "A", "経営": "A",
        # カテゴリB: 業務マニュアル
        "マニュアル": "B", "手順書": "B", "ガイド": "B", "手引き": "B", "規定": "B",
        # カテゴリC: 就業規則
        "就業規則": "C", "人事": "C", "勤怠": "C", "給与": "C", "福利厚生": "C",
        # カテゴリD: テンプレート
        "テンプレート": "D", "ひな形": "D", "フォーマット": "D", "書式": "D",
        # カテゴリE: 顧客情報
        "顧客": "E", "クライアント": "E", "取引先": "E",
        # カテゴリF: サービス情報
        "サービス": "F", "料金": "F", "プラン": "F", "製品": "F",
    })

    # 部署IDマッピング（Phase 3.5連携後はDBから動的取得）
    DEPARTMENT_MAP: dict[str, str] = field(default_factory=lambda: {
        "営業部": "dept_sales",
        "総務部": "dept_admin",
        "開発部": "dept_dev",
        "人事部": "dept_hr",
        "経理部": "dept_finance",
        "マーケティング部": "dept_marketing",
    })


class FolderMapper:
    """
    フォルダパスから権限情報を決定するクラス

    使用例（静的マッピング）:
        mapper = FolderMapper("5f98365f-e7c5-4f48-9918-7fe9aabae5df")

        path = ["ソウルくん用フォルダ", "社員限定", "業務マニュアル"]
        permissions = mapper.map_folder_to_permissions(path)
        # → {"classification": "internal", "category": "B", "department_id": None}

    使用例（動的マッピング - Phase 3.5 DB連携）:
        mapper = FolderMapper(
            "5f98365f-e7c5-4f48-9918-7fe9aabae5df",
            db_pool=db_pool,
            use_dynamic_departments=True
        )

        path = ["ソウルくん用フォルダ", "部署別", "営業部"]
        permissions = mapper.map_folder_to_permissions(path)
        # → {"classification": "confidential", "category": "B", "department_id": "550e8400-..."}
    """

    DEFAULT_CLASSIFICATION = "internal"
    DEFAULT_CATEGORY = "B"
    DEFAULT_DEPARTMENT_ID = None

    def __init__(
        self,
        organization_id: str,
        config: Optional[FolderMappingConfig] = None,
        db_pool=None,
        use_dynamic_departments: bool = True
    ):
        """
        FolderMapper を初期化

        Args:
            organization_id: 組織ID
            config: フォルダマッピング設定（静的マッピング用）
            db_pool: SQLAlchemy Engine または Connection Pool（動的マッピング用）
            use_dynamic_departments: 動的部署マッピングを使用するか

        動的マッピングの条件:
        - use_dynamic_departments=True
        - db_pool が指定されている
        - DepartmentMappingService が利用可能
        """
        self.organization_id = organization_id
        self.config = config or FolderMappingConfig()

        # 動的部署マッピングサービス
        self._dept_service: Optional[DepartmentMappingService] = None

        if (
            use_dynamic_departments
            and db_pool is not None
            and DEPARTMENT_MAPPING_AVAILABLE
        ):
            try:
                self._dept_service = DepartmentMappingService(
                    db_pool=db_pool,
                    organization_id=organization_id
                )
                logger.info(
                    f"FolderMapper: Dynamic department mapping enabled "
                    f"for organization {organization_id}"
                )
            except Exception as e:
                logger.warning(
                    f"FolderMapper: Failed to initialize DepartmentMappingService, "
                    f"falling back to static mapping: {e}"
                )
                self._dept_service = None
        elif use_dynamic_departments and db_pool is None:
            logger.debug(
                f"FolderMapper: db_pool not provided, using static department mapping"
            )
        elif use_dynamic_departments and not DEPARTMENT_MAPPING_AVAILABLE:
            logger.debug(
                f"FolderMapper: DepartmentMappingService not available, "
                f"using static department mapping"
            )

    def determine_classification(self, folder_path: list[str]) -> str:
        """
        フォルダパスから機密区分を決定

        決定ロジック:
        1. フォルダパスを上から順にチェック
        2. CLASSIFICATION_MAP に一致するフォルダ名があれば、その値を返す
        3. 一致するものがなければデフォルト値（internal）を返す
        """
        for folder_name in folder_path:
            folder_name_lower = folder_name.lower()
            for key, classification in self.config.CLASSIFICATION_MAP.items():
                if key.lower() == folder_name_lower:
                    return classification
        return self.DEFAULT_CLASSIFICATION

    def determine_category(self, folder_path: list[str]) -> str:
        """
        フォルダパスからカテゴリを決定

        決定ロジック:
        1. フォルダパスを上から順にチェック
        2. CATEGORY_MAP のキーワードがフォルダ名に含まれていれば、その値を返す
        3. 一致するものがなければデフォルト値（B）を返す
        """
        for folder_name in folder_path:
            folder_name_lower = folder_name.lower()
            for keyword, category in self.config.CATEGORY_MAP.items():
                if keyword.lower() in folder_name_lower:
                    return category
        return self.DEFAULT_CATEGORY

    def determine_department_id(self, folder_path: list[str]) -> Optional[str]:
        """
        フォルダパスから部署IDを決定

        決定ロジック:
        1. classification が "confidential" でない場合は None を返す
        2. 動的マッピング（DB）が有効な場合、部署名から UUID を取得
        3. 静的マッピング（DEPARTMENT_MAP）をフォールバックとして使用
        4. 一致するものがなければ None を返す

        Returns:
            部署ID（動的マッピング時はUUID、静的マッピング時はテキスト形式）
            見つからない場合はNone
        """
        classification = self.determine_classification(folder_path)
        if classification != "confidential":
            return self.DEFAULT_DEPARTMENT_ID

        for folder_name in folder_path:
            folder_name_normalized = folder_name.strip()

            # 動的マッピング（DB）を優先
            if self._dept_service is not None:
                dept_id = self._dept_service.get_department_id(folder_name_normalized)
                if dept_id is not None:
                    logger.debug(
                        f"Department ID resolved dynamically: "
                        f"'{folder_name_normalized}' -> {dept_id}"
                    )
                    return dept_id

            # 静的マッピング（フォールバック）
            if folder_name_normalized in self.config.DEPARTMENT_MAP:
                legacy_id = self.config.DEPARTMENT_MAP[folder_name_normalized]

                # 動的マッピングが有効な場合、レガシーIDをUUIDに変換
                if self._dept_service is not None:
                    uuid_id = self._resolve_legacy_department_id(legacy_id)
                    if uuid_id is not None:
                        logger.debug(
                            f"Legacy department ID converted: "
                            f"'{legacy_id}' -> {uuid_id}"
                        )
                        return uuid_id

                # 動的マッピングが無効な場合、レガシーIDをそのまま返す
                logger.debug(
                    f"Department ID resolved statically: "
                    f"'{folder_name_normalized}' -> {legacy_id}"
                )
                return legacy_id

        return self.DEFAULT_DEPARTMENT_ID

    def _resolve_legacy_department_id(self, legacy_id: str) -> Optional[str]:
        """
        レガシー形式（"dept_sales"）の部署IDをUUIDに変換

        Args:
            legacy_id: レガシー形式の部署ID（例: "dept_sales"）

        Returns:
            UUID形式の部署ID、変換できない場合はNone

        注意:
        - 後方互換性のための一時的な機能
        - Phase 4以降に削除予定
        """
        if self._dept_service is None:
            return None

        if not DEPARTMENT_MAPPING_AVAILABLE:
            return None

        try:
            return resolve_legacy_department_id(self._dept_service, legacy_id)
        except Exception as e:
            logger.warning(
                f"Failed to resolve legacy department ID '{legacy_id}': {e}"
            )
            return None

    def is_dynamic_mapping_enabled(self) -> bool:
        """動的部署マッピングが有効かチェック"""
        return self._dept_service is not None

    def get_all_departments(self) -> dict[str, str]:
        """
        全部署マッピングを取得

        Returns:
            動的マッピング有効時: DBから取得した部署名→UUID辞書
            動的マッピング無効時: 静的マッピング（DEPARTMENT_MAP）
        """
        if self._dept_service is not None:
            return self._dept_service.get_all_departments()
        return self.config.DEPARTMENT_MAP.copy()

    def map_folder_to_permissions(self, folder_path: list[str]) -> dict:
        """
        フォルダパスから全ての権限情報を取得

        Returns:
            {
                "classification": "internal",
                "category": "B",
                "department_id": None
            }
        """
        return {
            "classification": self.determine_classification(folder_path),
            "category": self.determine_category(folder_path),
            "department_id": self.determine_department_id(folder_path)
        }


# ================================================================
# エクスポート
# ================================================================

__all__ = [
    'GoogleDriveClient',
    'DriveFile',
    'DriveChange',
    'SyncResult',
    'FolderMapper',
    'FolderMappingConfig',
    'SUPPORTED_MIME_TYPES',
    'MAX_FILE_SIZE',
    'DEPARTMENT_MAPPING_AVAILABLE',
]
