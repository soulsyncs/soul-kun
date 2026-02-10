"""
構造化ログモジュール

Cloud Logging と連携した構造化ログを提供。
テナントID、リクエストIDを自動で含める。

使用例:
    from lib.logging import get_logger

    logger = get_logger(__name__)
    logger.info("User logged in", user_id="user_123")
    logger.error("Database error", error=str(e), query="SELECT ...")

出力例（JSON形式）:
    {
        "severity": "INFO",
        "message": "User logged in",
        "user_id": "user_123",
        "tenant_id": "org_soulsyncs",
        "timestamp": "2026-01-17T10:00:00Z"
    }

Phase 4対応:
    - テナントIDの自動付与
    - 監査ログとの連携
    - Cloud Logging フォーマット対応
"""

import logging
import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional, cast
from functools import lru_cache

from lib.config import get_settings
from lib.tenant import get_current_tenant


class StructuredFormatter(logging.Formatter):
    """
    Cloud Logging 互換の構造化ログフォーマッター

    JSON形式でログを出力し、Cloud Logging で自動パース可能。
    """

    SEVERITY_MAP = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def format(self, record: logging.LogRecord) -> str:
        """ログレコードをJSON形式にフォーマット"""

        # 基本フィールド
        log_entry: Dict[str, Any] = {
            "severity": self.SEVERITY_MAP.get(record.levelno, "DEFAULT"),
            "message": record.getMessage(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "logger": record.name,
        }

        # テナントID（自動付与）
        tenant_id = get_current_tenant()
        if tenant_id:
            log_entry["tenant_id"] = tenant_id

        # 追加フィールド（extra で渡されたもの）
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)

        # 例外情報
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # ソース情報
        log_entry["source"] = {
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName,
        }

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class StructuredLogger(logging.Logger):
    """
    構造化ログ対応のカスタムロガー

    追加のキーワード引数をログエントリに含める。
    """

    def _log_with_extra(
        self,
        level: int,
        msg: str,
        args: tuple,
        exc_info: Any = None,
        **kwargs: Any
    ) -> None:
        """追加フィールド付きでログを記録"""

        # extra_fields として追加データを渡す
        extra = {"extra_fields": kwargs}
        super()._log(level, msg, args, exc_info=exc_info, extra=extra)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        if self.isEnabledFor(logging.DEBUG):
            self._log_with_extra(logging.DEBUG, msg, args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        if self.isEnabledFor(logging.INFO):
            self._log_with_extra(logging.INFO, msg, args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        if self.isEnabledFor(logging.WARNING):
            self._log_with_extra(logging.WARNING, msg, args, **kwargs)

    def error(self, msg: str, *args: Any, exc_info: Any = None, **kwargs: Any) -> None:  # type: ignore[override]
        if self.isEnabledFor(logging.ERROR):
            self._log_with_extra(
                logging.ERROR, msg, args, exc_info=exc_info, **kwargs
            )

    def critical(self, msg: str, *args: Any, exc_info: Any = None, **kwargs: Any) -> None:  # type: ignore[override]
        if self.isEnabledFor(logging.CRITICAL):
            self._log_with_extra(
                logging.CRITICAL, msg, args, exc_info=exc_info, **kwargs
            )

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        """例外情報付きでエラーログを記録"""
        self.error(msg, *args, exc_info=True, **kwargs)


# カスタムロガークラスを登録
logging.setLoggerClass(StructuredLogger)


@lru_cache(maxsize=32)
def get_logger(name: str) -> StructuredLogger:
    """
    構造化ロガーを取得

    Args:
        name: ロガー名（通常は __name__）

    Returns:
        StructuredLogger インスタンス

    使用例:
        logger = get_logger(__name__)
        logger.info("Processing started", task_id="task_123")
    """
    settings = get_settings()

    logger = logging.getLogger(name)

    # 既にハンドラーが設定されている場合はスキップ
    if logger.handlers:
        return cast(StructuredLogger, logger)

    # ログレベル設定
    level = logging.DEBUG if settings.DEBUG else logging.INFO
    logger.setLevel(level)

    # ハンドラー設定
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    # Cloud Run/Functions では構造化フォーマット
    # ローカル開発では読みやすいフォーマット
    if settings.is_cloud_run() or settings.is_cloud_functions():
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        ))

    logger.addHandler(handler)

    # 親ロガーへの伝播を防止
    logger.propagate = False

    return cast(StructuredLogger, logger)


# =============================================================================
# 便利関数
# =============================================================================

def log_api_request(
    logger: StructuredLogger,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    **extra
):
    """
    APIリクエストをログに記録

    使用例:
        log_api_request(
            logger,
            method="POST",
            path="/api/v1/tasks",
            status_code=201,
            duration_ms=45.2,
            user_id="user_123"
        )
    """
    logger.info(
        f"{method} {path} -> {status_code}",
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
        **extra
    )


def log_db_query(
    logger: StructuredLogger,
    query: str,
    duration_ms: float,
    rows_affected: Optional[int] = None,
    **extra
):
    """
    DBクエリをログに記録

    使用例:
        log_db_query(
            logger,
            query="SELECT * FROM tasks WHERE ...",
            duration_ms=12.5,
            rows_affected=42
        )
    """
    logger.debug(
        "DB Query executed",
        query=query[:200],  # クエリは200文字まで
        duration_ms=duration_ms,
        rows_affected=rows_affected,
        **extra
    )


def log_external_api_call(
    logger: StructuredLogger,
    service: str,
    method: str,
    endpoint: str,
    status_code: int,
    duration_ms: float,
    **extra
):
    """
    外部APIコールをログに記録

    使用例:
        log_external_api_call(
            logger,
            service="chatwork",
            method="POST",
            endpoint="/rooms/123/messages",
            status_code=200,
            duration_ms=320.5
        )
    """
    logger.info(
        f"External API: {service} {method} {endpoint} -> {status_code}",
        service=service,
        method=method,
        endpoint=endpoint,
        status_code=status_code,
        duration_ms=duration_ms,
        **extra
    )


# =============================================================================
# 監査ログ（Phase 4準備）
# =============================================================================

def log_audit_event(
    logger: StructuredLogger,
    action: str,
    resource_type: str,
    resource_id: str,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
):
    """
    監査イベントをログに記録

    Phase 4 で audit_logs テーブルと連携予定。

    使用例:
        log_audit_event(
            logger,
            action="view",
            resource_type="document",
            resource_id="doc_123",
            user_id="user_456",
            details={"classification": "confidential"}
        )
    """
    logger.info(
        f"Audit: {action} {resource_type}/{resource_id}",
        audit=True,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        details=details or {},
    )
