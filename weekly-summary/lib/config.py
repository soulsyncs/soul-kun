"""
設定管理モジュール

環境変数とデフォルト値を一元管理します。
Phase 4のマルチテナント対応を見据えた設計。

使用例:
    from lib.config import get_settings

    settings = get_settings()
    print(settings.PROJECT_ID)
    print(settings.DB_NAME)
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    """
    アプリケーション設定

    frozen=True で不変オブジェクトとし、スレッドセーフを保証。
    Cloud Run 100インスタンス対応。
    """

    # GCP プロジェクト
    PROJECT_ID: str = field(default_factory=lambda: os.getenv(
        "PROJECT_ID", "soulkun-production"
    ))

    # Cloud SQL 設定
    INSTANCE_CONNECTION_NAME: str = field(default_factory=lambda: os.getenv(
        "INSTANCE_CONNECTION_NAME",
        "soulkun-production:asia-northeast1:soulkun-db"
    ))
    DB_NAME: str = field(default_factory=lambda: os.getenv(
        "DB_NAME", "soulkun_tasks"
    ))
    DB_USER: str = field(default_factory=lambda: os.getenv(
        "DB_USER", "soulkun_user"
    ))
    DB_HOST: Optional[str] = field(default_factory=lambda: os.getenv(
        "DB_HOST", None  # Cloud Run以外での直接接続用
    ))
    DB_PORT: int = field(default_factory=lambda: int(os.getenv(
        "DB_PORT", "5432"
    )))

    # コネクションプール設定（Phase 4: 100インスタンス対応）
    # 各インスタンスが5接続 × 100インスタンス = 500接続
    # Cloud SQL の max_connections=1000 に対して余裕を持たせる
    DB_POOL_SIZE: int = field(default_factory=lambda: int(os.getenv(
        "DB_POOL_SIZE", "5"
    )))
    DB_MAX_OVERFLOW: int = field(default_factory=lambda: int(os.getenv(
        "DB_MAX_OVERFLOW", "2"
    )))
    DB_POOL_TIMEOUT: int = field(default_factory=lambda: int(os.getenv(
        "DB_POOL_TIMEOUT", "30"
    )))
    DB_POOL_RECYCLE: int = field(default_factory=lambda: int(os.getenv(
        "DB_POOL_RECYCLE", "1800"  # 30分でリサイクル
    )))

    # OpenRouter API（AI応答）
    # ★ v10.12.0: Gemini 3 Flashに統一
    OPENROUTER_API_URL: str = field(default_factory=lambda: os.getenv(
        "OPENROUTER_API_URL",
        "https://openrouter.ai/api/v1/chat/completions"
    ))
    DEFAULT_AI_MODEL: str = field(default_factory=lambda: os.getenv(
        "DEFAULT_AI_MODEL", "google/gemini-3-flash-preview"
    ))
    COMMANDER_AI_MODEL: str = field(default_factory=lambda: os.getenv(
        "COMMANDER_AI_MODEL", "google/gemini-3-flash-preview"
    ))

    # Chatwork 設定
    CHATWORK_API_URL: str = "https://api.chatwork.com/v2"
    CHATWORK_API_RATE_LIMIT: int = field(default_factory=lambda: int(os.getenv(
        "CHATWORK_API_RATE_LIMIT", "100"  # 5分あたり
    )))
    MY_ACCOUNT_ID: str = field(default_factory=lambda: os.getenv(
        "MY_ACCOUNT_ID", "10909425"  # ソウルくんのアカウントID
    ))
    BOT_ACCOUNT_ID: str = field(default_factory=lambda: os.getenv(
        "BOT_ACCOUNT_ID", "10909425"
    ))

    # 会話履歴設定
    MAX_HISTORY_COUNT: int = field(default_factory=lambda: int(os.getenv(
        "MAX_HISTORY_COUNT", "100"
    )))
    HISTORY_EXPIRY_HOURS: int = field(default_factory=lambda: int(os.getenv(
        "HISTORY_EXPIRY_HOURS", "720"  # 30日
    )))

    # Redis キャッシュ設定（Phase 4準備）
    REDIS_HOST: Optional[str] = field(default_factory=lambda: os.getenv(
        "REDIS_HOST", None
    ))
    REDIS_PORT: int = field(default_factory=lambda: int(os.getenv(
        "REDIS_PORT", "6379"
    )))
    REDIS_TTL_SECONDS: int = field(default_factory=lambda: int(os.getenv(
        "REDIS_TTL_SECONDS", "300"  # 5分
    )))

    # Pinecone 設定（Phase 3 ナレッジ検索）
    PINECONE_INDEX_NAME: str = field(default_factory=lambda: os.getenv(
        "PINECONE_INDEX_NAME", "soulkun-knowledge"
    ))

    # Phase 3.5 組織階層連携フラグ
    # TRUE: 部署ベースのアクセス制御を有効化（departments テーブル必須）
    # FALSE: 機密区分（classification）のみでアクセス制御（Phase 3 単独運用）
    ENABLE_DEPARTMENT_ACCESS_CONTROL: bool = field(default_factory=lambda: os.getenv(
        "ENABLE_DEPARTMENT_ACCESS_CONTROL", "false"
    ).lower() == "true")

    # ナレッジ検索設定
    KNOWLEDGE_SEARCH_TOP_K: int = field(default_factory=lambda: int(os.getenv(
        "KNOWLEDGE_SEARCH_TOP_K", "5"
    )))
    KNOWLEDGE_SEARCH_SCORE_THRESHOLD: float = field(default_factory=lambda: float(os.getenv(
        "KNOWLEDGE_SEARCH_SCORE_THRESHOLD", "0.7"
    )))
    KNOWLEDGE_REFUSE_ON_LOW_SCORE: bool = field(default_factory=lambda: os.getenv(
        "KNOWLEDGE_REFUSE_ON_LOW_SCORE", "true"
    ).lower() == "true")

    # 環境識別
    ENVIRONMENT: str = field(default_factory=lambda: os.getenv(
        "ENVIRONMENT", "development"
    ))
    DEBUG: bool = field(default_factory=lambda: os.getenv(
        "DEBUG", "true"
    ).lower() == "true")

    # CORS設定（ローカル開発用）
    @property
    def CORS_ORIGINS(self) -> list:
        # ローカル開発時は複数のオリジンを許可
        default_origins = "http://localhost:3000,http://localhost:8080,http://localhost:5500,http://127.0.0.1:5500,null"
        origins = os.getenv("CORS_ORIGINS", default_origins)
        return [o.strip() for o in origins.split(",")]

    # API バージョン（Phase 4: v2 対応準備）
    API_VERSION: str = field(default_factory=lambda: os.getenv(
        "API_VERSION", "v1"
    ))

    # タイムゾーン
    TIMEZONE: str = "Asia/Tokyo"

    def is_production(self) -> bool:
        """本番環境かどうか"""
        return self.ENVIRONMENT == "production"

    def is_cloud_run(self) -> bool:
        """Cloud Run上で動作しているかどうか"""
        return os.getenv("K_SERVICE") is not None

    def is_cloud_functions(self) -> bool:
        """Cloud Functions上で動作しているかどうか"""
        return os.getenv("FUNCTION_NAME") is not None

    def get_db_connection_string(self) -> str:
        """
        DB接続文字列を取得

        Cloud Run/Functions では Cloud SQL Connector を使用するため、
        この文字列は直接接続時のみ使用。
        """
        if self.DB_HOST:
            return f"postgresql://{self.DB_USER}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        return ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    設定を取得（シングルトン）

    lru_cache によりアプリケーション全体で1つのインスタンスを共有。
    """
    return Settings()


# 便利なエイリアス
settings = get_settings()
