"""
シークレット管理モジュール

GCP Secret Manager からシークレットを取得します。
キャッシュ機能により、同じシークレットへの繰り返しアクセスを最適化。

ローカル開発時は環境変数から取得することも可能。

使用例:
    from lib.secrets import get_secret, get_secret_cached

    # 毎回取得（最新値が必要な場合）
    api_key = get_secret("chatwork-api-key")

    # キャッシュ付き（パフォーマンス優先）
    api_key = get_secret_cached("chatwork-api-key")

ローカル開発:
    DB_HOST が設定されている場合、環境変数から取得
    例: soulkun-db-password → SOULKUN_DB_PASSWORD

Phase 4対応:
    - テナント別シークレット対応準備（{tenant_id}-{secret_name}）
    - Cloud Run 100インスタンス対応のキャッシュ設計
"""

import os
from functools import lru_cache
from typing import Optional
import threading

from lib.config import get_settings

# スレッドセーフなシークレットマネージャークライアント
_client = None
_client_lock = threading.Lock()


def _get_client():
    """
    Secret Manager クライアントを取得（シングルトン）

    スレッドセーフな実装で、Cloud Run の複数リクエスト処理に対応。
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from google.cloud import secretmanager
                _client = secretmanager.SecretManagerServiceClient()
    return _client


def _secret_to_env_var(secret_id: str) -> str:
    """
    シークレット名を環境変数名に変換

    例: soulkun-db-password → SOULKUN_DB_PASSWORD
    """
    return secret_id.upper().replace("-", "_")


def get_secret(
    secret_id: str,
    version: str = "latest",
    project_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """
    シークレットを取得

    ローカル開発時（DB_HOSTが設定されている場合）は環境変数から取得。
    本番環境では Secret Manager から取得。

    Args:
        secret_id: シークレット名（例: "chatwork-api-key"）
        version: バージョン（デフォルト: "latest"）
        project_id: プロジェクトID（デフォルト: 設定から取得）
        tenant_id: テナントID（Phase 4: テナント別シークレット用）

    Returns:
        シークレットの値

    Raises:
        google.api_core.exceptions.NotFound: シークレットが存在しない場合
        google.api_core.exceptions.PermissionDenied: 権限がない場合
        ValueError: ローカル開発時に環境変数が設定されていない場合

    使用例:
        # 基本的な使用
        api_key = get_secret("chatwork-api-key")

        # テナント別シークレット（Phase 4）
        tenant_api_key = get_secret("api-key", tenant_id="org_customer1")
        # → "org_customer1-api-key" を取得
    """
    settings = get_settings()

    # Phase 4: テナント別シークレット対応
    if tenant_id:
        secret_id = f"{tenant_id}-{secret_id}"

    # ローカル開発時は環境変数から取得
    if settings.DB_HOST:
        env_var = _secret_to_env_var(secret_id)
        value = os.getenv(env_var)
        if value:
            return value
        # 環境変数がなければフォールバック
        # DB パスワードの場合は必須なのでエラー
        if "password" in secret_id.lower():
            raise ValueError(
                f"Local dev: Set {env_var} environment variable"
            )

    # 本番環境では Secret Manager から取得
    project = project_id or settings.PROJECT_ID
    client = _get_client()
    name = f"projects/{project}/secrets/{secret_id}/versions/{version}"

    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


@lru_cache(maxsize=32)
def get_secret_cached(
    secret_id: str,
    version: str = "latest",
    project_id: Optional[str] = None,
) -> str:
    """
    キャッシュ付きでシークレットを取得

    lru_cache により、同じシークレットへの繰り返しアクセスを最適化。
    ただし、アプリケーション再起動まで値は更新されない点に注意。

    Args:
        secret_id: シークレット名
        version: バージョン
        project_id: プロジェクトID

    Returns:
        シークレットの値

    注意:
        - シークレットをローテーションした場合、アプリ再起動が必要
        - 頻繁に変更されるシークレットには get_secret() を使用
    """
    return get_secret(secret_id, version, project_id)


def clear_secret_cache() -> None:
    """
    シークレットキャッシュをクリア

    シークレットをローテーションした後に呼び出す。
    """
    get_secret_cached.cache_clear()


# 既存コードとの互換性のためのエイリアス
# main.py の get_secret() と同じシグネチャ
def get_secret_compat(secret_name: str) -> str:
    """
    既存コード互換の get_secret

    main.py からの移行時にそのまま置き換え可能。
    """
    return get_secret_cached(secret_name)
