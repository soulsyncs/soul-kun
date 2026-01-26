"""
部署マッピングサービス - DB連携版

組織図システム（Phase 3.5）の departments テーブルから部署名→部署ID(UUID)の
マッピングを動的に取得するサービス。

特徴:
- DBから部署マスタを取得してキャッシュ
- TTL付きキャッシュ（デフォルト5分）
- フォールバック設計（DB接続失敗時は空辞書）
- organization_idでテナント分離

使用例:
    from lib.department_mapping import DepartmentMappingService

    service = DepartmentMappingService(
        db_pool=pool,
        organization_id="org_soulsyncs"
    )

    # 部署名からUUIDを取得
    dept_id = service.get_department_id("営業部")
    # → "550e8400-e29b-41d4-a716-446655440000"

設計原則:
- 10の鉄則 #1: organization_id フィルタ必須
- 10の鉄則 #6: キャッシュTTL設定（5分）
- 10の鉄則 #9: SQLインジェクション対策（パラメータ化クエリ）

バージョン: v1.0.0
作成日: 2026-01-26
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


class DepartmentMappingService:
    """
    部署名からUUID形式の部署IDを動的に解決するサービス

    Attributes:
        db_pool: SQLAlchemy Engine または Connection Pool
        organization_id: 組織ID（テキストまたはUUID形式）
        cache_ttl_seconds: キャッシュの有効期限（秒）
    """

    DEFAULT_CACHE_TTL_SECONDS = 300  # 5分

    def __init__(
        self,
        db_pool,
        organization_id: str,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    ):
        """
        DepartmentMappingService を初期化

        Args:
            db_pool: SQLAlchemy Engine または Connection Pool
            organization_id: 組織ID（"org_soulsyncs" または UUID文字列）
            cache_ttl_seconds: キャッシュの有効期限（秒）、デフォルト300秒（5分）
        """
        self.db_pool = db_pool
        self.organization_id = organization_id
        self.cache_ttl_seconds = cache_ttl_seconds

        # キャッシュ
        self._cache: dict[str, str] = {}  # 部署名 → UUID
        self._cache_timestamp: Optional[datetime] = None

        # organization_id の UUID 解決結果をキャッシュ
        self._org_uuid: Optional[str] = None

    def _resolve_organization_uuid(self) -> Optional[str]:
        """
        organization_id（テキスト形式）をUUIDに解決

        Returns:
            UUID文字列、解決できない場合はNone

        処理フロー:
        1. キャッシュ済みなら返す
        2. すでにUUID形式ならそのまま返す
        3. DBから organizations テーブルを検索して UUID を取得
        """
        # キャッシュ済みなら返す
        if self._org_uuid:
            return self._org_uuid

        # すでにUUID形式かチェック
        try:
            uuid.UUID(self.organization_id)
            self._org_uuid = self.organization_id
            return self._org_uuid
        except ValueError:
            pass

        # DBから取得
        try:
            with self.db_pool.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT id
                        FROM organizations
                        WHERE organization_id = :org_id
                    """),
                    {"org_id": self.organization_id}
                )
                row = result.fetchone()
                if row:
                    self._org_uuid = str(row[0])
                    logger.debug(
                        f"Organization UUID resolved: {self.organization_id} -> {self._org_uuid}"
                    )
                    return self._org_uuid
                else:
                    logger.warning(
                        f"Organization not found in DB: {self.organization_id}"
                    )
                    return None
        except Exception as e:
            logger.error(
                f"Failed to resolve organization UUID: {self.organization_id}, error: {e}"
            )
            return None

    def _is_cache_valid(self) -> bool:
        """
        キャッシュが有効かチェック

        Returns:
            有効ならTrue、無効（期限切れまたは未初期化）ならFalse
        """
        if not self._cache_timestamp:
            return False

        elapsed = (datetime.now() - self._cache_timestamp).total_seconds()
        return elapsed < self.cache_ttl_seconds

    def _refresh_cache(self) -> None:
        """
        DBから部署マッピングを取得してキャッシュを更新

        処理フロー:
        1. organization_id を UUID に解決
        2. departments テーブルから有効な部署を取得
        3. 部署名 → UUID のマッピングを構築
        4. 正規化版（空白除去、小文字）も追加

        エラー時:
        - 空のキャッシュを設定（フォールバック用）
        - エラーログを出力
        """
        org_uuid = self._resolve_organization_uuid()

        if not org_uuid:
            logger.warning(
                f"Cannot refresh department cache: organization not found ({self.organization_id})"
            )
            self._cache = {}
            self._cache_timestamp = datetime.now()
            return

        try:
            with self.db_pool.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT id, name
                        FROM departments
                        WHERE organization_id = :org_id::uuid
                          AND is_active = TRUE
                        ORDER BY name
                    """),
                    {"org_id": org_uuid}
                )
                rows = result.fetchall()

                # 部署名 → UUID のマッピングを構築
                self._cache = {}
                for row in rows:
                    dept_id = str(row[0])
                    dept_name = row[1]

                    # 完全一致用（元の名前）
                    self._cache[dept_name] = dept_id

                    # 正規化版も追加（空白除去、小文字）
                    # これにより「営業部」と「 営業部 」と「営業部」（全角スペース）が同じIDにマッチ
                    normalized = self._normalize_name(dept_name)
                    if normalized != dept_name:
                        self._cache[normalized] = dept_id

                self._cache_timestamp = datetime.now()

                logger.info(
                    f"Department mapping cache refreshed: {len(rows)} departments "
                    f"for organization {self.organization_id}"
                )

        except Exception as e:
            logger.error(
                f"Failed to refresh department mapping cache: {e}"
            )
            # エラー時は空のキャッシュを設定（フォールバック用）
            self._cache = {}
            self._cache_timestamp = datetime.now()

    def _normalize_name(self, name: str) -> str:
        """
        部署名を正規化

        Args:
            name: 元の部署名

        Returns:
            正規化された部署名（空白除去、小文字変換）
        """
        # 全角スペースを半角に変換
        normalized = name.replace('\u3000', ' ')
        # 前後の空白を除去
        normalized = normalized.strip()
        # 小文字に変換
        normalized = normalized.lower()
        return normalized

    def get_department_id(self, folder_name: str) -> Optional[str]:
        """
        フォルダ名から部署ID(UUID)を取得

        Args:
            folder_name: フォルダ名（例: "営業部"）

        Returns:
            部署ID(UUID文字列)、見つからない場合はNone

        処理フロー:
        1. キャッシュが無効なら更新
        2. 完全一致でマッチング
        3. 正規化版でマッチング
        4. 見つからなければNone
        """
        # キャッシュを更新（必要な場合）
        if not self._is_cache_valid():
            self._refresh_cache()

        # 完全一致を試行
        if folder_name in self._cache:
            return self._cache[folder_name]

        # 正規化版で試行
        normalized = self._normalize_name(folder_name)
        if normalized in self._cache:
            return self._cache[normalized]

        logger.debug(
            f"Department not found for folder name: '{folder_name}' "
            f"(normalized: '{normalized}')"
        )
        return None

    def get_all_departments(self) -> dict[str, str]:
        """
        全部署マッピングを取得

        Returns:
            部署名 → UUID のマッピング辞書のコピー

        用途:
        - デバッグ
        - 管理画面での一覧表示
        """
        if not self._is_cache_valid():
            self._refresh_cache()

        # コピーを返す（元のキャッシュを変更されないように）
        return self._cache.copy()

    def get_department_name(self, dept_id: str) -> Optional[str]:
        """
        部署ID(UUID)から部署名を取得（逆引き）

        Args:
            dept_id: 部署ID(UUID文字列)

        Returns:
            部署名、見つからない場合はNone
        """
        if not self._is_cache_valid():
            self._refresh_cache()

        # 逆引き（値からキーを探す）
        for name, uid in self._cache.items():
            if uid == dept_id:
                # 正規化版ではなく元の名前を返す（大文字/小文字が保持された方）
                if name == self._normalize_name(name):
                    continue  # 正規化版はスキップ
                return name

        return None

    def clear_cache(self) -> None:
        """
        キャッシュを強制クリア

        用途:
        - テスト
        - 管理画面からの手動リフレッシュ
        """
        self._cache = {}
        self._cache_timestamp = None
        logger.info(
            f"Department mapping cache cleared for organization {self.organization_id}"
        )

    def is_valid_department(self, folder_name: str) -> bool:
        """
        フォルダ名が有効な部署名かチェック

        Args:
            folder_name: フォルダ名

        Returns:
            有効な部署名ならTrue
        """
        return self.get_department_id(folder_name) is not None


# レガシー部署ID（テキスト形式）から部署名へのマッピング
# 後方互換性のために使用（Phase 4以降に削除予定）
LEGACY_DEPARTMENT_ID_TO_NAME = {
    "dept_sales": "営業部",
    "dept_admin": "総務部",
    "dept_dev": "開発部",
    "dept_hr": "人事部",
    "dept_finance": "経理部",
    "dept_marketing": "マーケティング部",
}


def resolve_legacy_department_id(
    service: DepartmentMappingService,
    legacy_id: str
) -> Optional[str]:
    """
    レガシー形式（"dept_sales"）の部署IDをUUIDに変換

    Args:
        service: DepartmentMappingService インスタンス
        legacy_id: レガシー形式の部署ID（例: "dept_sales"）

    Returns:
        UUID形式の部署ID、変換できない場合はNone

    注意:
    - 後方互換性のための一時的な機能
    - Phase 4以降に削除予定
    """
    if legacy_id in LEGACY_DEPARTMENT_ID_TO_NAME:
        dept_name = LEGACY_DEPARTMENT_ID_TO_NAME[legacy_id]
        return service.get_department_id(dept_name)

    return None
