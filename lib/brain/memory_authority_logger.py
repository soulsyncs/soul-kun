# lib/brain/memory_authority_logger.py
"""
Memory Authority 観測モードロガー

v10.43.1: P4 SOFT_CONFLICT観測用ログ保存

【役割】
P4 MemoryAuthorityがSOFT_CONFLICTを検出した全ケースをログ保存し、
将来の精度改善のためのデータを蓄積する。

【ログ内容】
- action: 実行しようとしたアクション
- detected_memory_reference: 検出された記憶参照
- conflict_reason: 矛盾理由
- user_response: ユーザーの応答（OK/修正）

【設計方針】
- 非同期で保存（実行速度に影響を与えない）
- JSON形式で保存（後から分析可能）
- 判定ロジックは変更しない（観測のみ）
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# ログデータ型定義
# =============================================================================


@dataclass
class SoftConflictLog:
    """
    SOFT_CONFLICT検出ログ

    Attributes:
        timestamp: 検出時刻（ISO 8601形式）
        action: 実行しようとしたアクション名
        detected_memory_reference: 検出された記憶の抜粋
        conflict_reason: 矛盾と判定された理由
        user_response: ユーザーの応答（"ok", "modify", None）
        room_id: ChatWorkルームID
        account_id: ユーザーアカウントID
        organization_id: 組織ID
        message_excerpt: 元メッセージの抜粋（先頭100文字）
        conflict_details: 詳細な矛盾情報
        confidence: 判定の確信度
    """
    timestamp: str
    action: str
    detected_memory_reference: str
    conflict_reason: str
    user_response: Optional[str] = None
    room_id: str = ""
    account_id: str = ""
    organization_id: str = ""
    message_excerpt: str = ""
    conflict_details: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    log_id: str = ""

    def __post_init__(self):
        if not self.log_id:
            # ユニークなログIDを生成
            self.log_id = f"sc_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return asdict(self)


# =============================================================================
# ロガークラス
# =============================================================================


class MemoryAuthorityLogger:
    """
    Memory Authority 観測モードロガー

    SOFT_CONFLICT検出を非同期でJSONファイルに保存する。
    """

    DEFAULT_LOG_DIR = "logs/memory_authority"
    DEFAULT_LOG_FILE = "soft_conflicts.jsonl"

    def __init__(
        self,
        log_dir: Optional[str] = None,
        log_file: Optional[str] = None,
        enabled: bool = True,
    ):
        """
        Args:
            log_dir: ログ保存ディレクトリ
            log_file: ログファイル名
            enabled: ロギングが有効か（Feature Flag連携用）
        """
        self.log_dir = Path(log_dir or self.DEFAULT_LOG_DIR)
        self.log_file = log_file or self.DEFAULT_LOG_FILE
        self.enabled = enabled
        self._pending_logs: Dict[str, SoftConflictLog] = {}

        # ログディレクトリを作成
        if self.enabled:
            try:
                self.log_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(f"Failed to create log directory: {e}")
                self.enabled = False

        logger.debug(
            f"MemoryAuthorityLogger initialized: "
            f"enabled={self.enabled}, log_dir={self.log_dir}"
        )

    @property
    def log_path(self) -> Path:
        """ログファイルのフルパス"""
        return self.log_dir / self.log_file

    def log_soft_conflict(
        self,
        action: str,
        detected_memory_reference: str,
        conflict_reason: str,
        room_id: str = "",
        account_id: str = "",
        organization_id: str = "",
        message_excerpt: str = "",
        conflict_details: Optional[List[Dict[str, Any]]] = None,
        confidence: float = 0.0,
    ) -> str:
        """
        SOFT_CONFLICT検出をログに記録（同期版）

        Args:
            action: 実行しようとしたアクション名
            detected_memory_reference: 検出された記憶の抜粋
            conflict_reason: 矛盾と判定された理由
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            organization_id: 組織ID
            message_excerpt: 元メッセージの抜粋
            conflict_details: 詳細な矛盾情報
            confidence: 判定の確信度

        Returns:
            str: ログID（後でuser_responseを更新するため）
        """
        if not self.enabled:
            return ""

        log_entry = SoftConflictLog(
            timestamp=datetime.now().isoformat(),
            action=action,
            detected_memory_reference=detected_memory_reference[:200],
            conflict_reason=conflict_reason,
            room_id=room_id,
            account_id=account_id,
            organization_id=organization_id,
            message_excerpt=message_excerpt[:100] if message_excerpt else "",
            conflict_details=conflict_details or [],
            confidence=confidence,
        )

        # ペンディングログに保存（user_response待ち）
        self._pending_logs[log_entry.log_id] = log_entry

        logger.info(
            f"[MemoryAuthorityLogger] SOFT_CONFLICT logged: "
            f"log_id={log_entry.log_id}, action={action}"
        )

        return log_entry.log_id

    async def log_soft_conflict_async(
        self,
        action: str,
        detected_memory_reference: str,
        conflict_reason: str,
        room_id: str = "",
        account_id: str = "",
        organization_id: str = "",
        message_excerpt: str = "",
        conflict_details: Optional[List[Dict[str, Any]]] = None,
        confidence: float = 0.0,
    ) -> str:
        """
        SOFT_CONFLICT検出をログに記録（非同期版）

        非同期で実行し、メイン処理をブロックしない。
        """
        if not self.enabled:
            return ""

        # 非同期でログ記録（メイン処理をブロックしない）
        loop = asyncio.get_event_loop()
        log_id = await loop.run_in_executor(
            None,
            lambda: self.log_soft_conflict(
                action=action,
                detected_memory_reference=detected_memory_reference,
                conflict_reason=conflict_reason,
                room_id=room_id,
                account_id=account_id,
                organization_id=organization_id,
                message_excerpt=message_excerpt,
                conflict_details=conflict_details,
                confidence=confidence,
            )
        )
        return log_id

    def update_user_response(
        self,
        log_id: str,
        user_response: str,
    ) -> bool:
        """
        ユーザーの応答を更新してログを確定保存

        Args:
            log_id: ログID
            user_response: ユーザーの応答（"ok", "modify", "cancel"）

        Returns:
            bool: 更新成功したか
        """
        if not self.enabled:
            return False

        if log_id not in self._pending_logs:
            logger.warning(f"Log ID not found in pending: {log_id}")
            return False

        log_entry = self._pending_logs.pop(log_id)
        log_entry.user_response = user_response

        # ファイルに保存
        try:
            self._write_log(log_entry)
            logger.info(
                f"[MemoryAuthorityLogger] User response saved: "
                f"log_id={log_id}, response={user_response}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to write log: {e}")
            # 失敗したらペンディングに戻す
            self._pending_logs[log_id] = log_entry
            return False

    async def update_user_response_async(
        self,
        log_id: str,
        user_response: str,
    ) -> bool:
        """
        ユーザーの応答を非同期で更新
        """
        if not self.enabled:
            return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.update_user_response(log_id, user_response)
        )

    def flush_pending(self, default_response: str = "timeout") -> int:
        """
        ペンディングログを全て確定保存

        ユーザー応答がタイムアウトした場合等に使用。

        Args:
            default_response: デフォルトの応答

        Returns:
            int: 保存したログ数
        """
        if not self.enabled:
            return 0

        count = 0
        for log_id in list(self._pending_logs.keys()):
            if self.update_user_response(log_id, default_response):
                count += 1

        return count

    def _write_log(self, log_entry: SoftConflictLog) -> None:
        """
        ログをJSONLファイルに追記

        Args:
            log_entry: ログエントリ
        """
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                json_line = json.dumps(log_entry.to_dict(), ensure_ascii=False)
                f.write(json_line + "\n")
        except Exception as e:
            logger.error(f"Failed to write log to {self.log_path}: {e}")
            raise

    def read_logs(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        action_filter: Optional[str] = None,
        response_filter: Optional[str] = None,
        limit: int = 1000,
    ) -> List[SoftConflictLog]:
        """
        ログを読み込み（分析用）

        Args:
            start_date: 開始日（ISO形式）
            end_date: 終了日（ISO形式）
            action_filter: アクション名でフィルタ
            response_filter: ユーザー応答でフィルタ
            limit: 最大件数

        Returns:
            List[SoftConflictLog]: ログエントリのリスト
        """
        if not self.log_path.exists():
            return []

        logs = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue

                    try:
                        data = json.loads(line)
                        log_entry = SoftConflictLog(**data)

                        # フィルタリング
                        if start_date and log_entry.timestamp < start_date:
                            continue
                        if end_date and log_entry.timestamp > end_date:
                            continue
                        if action_filter and log_entry.action != action_filter:
                            continue
                        if response_filter and log_entry.user_response != response_filter:
                            continue

                        logs.append(log_entry)

                        if len(logs) >= limit:
                            break
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Failed to parse log line: {e}")
                        continue

        except Exception as e:
            logger.error(f"Failed to read logs from {self.log_path}: {e}")

        return logs

    def get_statistics(self) -> Dict[str, Any]:
        """
        ログ統計を取得（分析用）

        Returns:
            Dict[str, Any]: 統計情報
        """
        logs = self.read_logs(limit=10000)

        if not logs:
            return {
                "total_count": 0,
                "response_distribution": {},
                "action_distribution": {},
                "avg_confidence": 0.0,
            }

        # 応答分布
        response_dist: Dict[str, int] = {}
        for log in logs:
            resp = log.user_response or "pending"
            response_dist[resp] = response_dist.get(resp, 0) + 1

        # アクション分布
        action_dist: Dict[str, int] = {}
        for log in logs:
            action_dist[log.action] = action_dist.get(log.action, 0) + 1

        # 平均確信度
        confidences = [log.confidence for log in logs if log.confidence > 0]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return {
            "total_count": len(logs),
            "response_distribution": response_dist,
            "action_distribution": action_dist,
            "avg_confidence": round(avg_confidence, 3),
            "pending_count": len(self._pending_logs),
        }


# =============================================================================
# シングルトンインスタンス & ファクトリー関数
# =============================================================================


_logger_instance: Optional[MemoryAuthorityLogger] = None


def get_memory_authority_logger(
    log_dir: Optional[str] = None,
    log_file: Optional[str] = None,
    enabled: bool = True,
) -> MemoryAuthorityLogger:
    """
    MemoryAuthorityLoggerのシングルトンインスタンスを取得

    Args:
        log_dir: ログ保存ディレクトリ（初回のみ有効）
        log_file: ログファイル名（初回のみ有効）
        enabled: ロギングが有効か（初回のみ有効）

    Returns:
        MemoryAuthorityLogger: ロガーインスタンス
    """
    global _logger_instance

    if _logger_instance is None:
        _logger_instance = MemoryAuthorityLogger(
            log_dir=log_dir,
            log_file=log_file,
            enabled=enabled,
        )

    return _logger_instance


def create_memory_authority_logger(
    log_dir: Optional[str] = None,
    log_file: Optional[str] = None,
    enabled: bool = True,
) -> MemoryAuthorityLogger:
    """
    新しいMemoryAuthorityLoggerインスタンスを作成

    シングルトンを使わずに新しいインスタンスが必要な場合に使用。

    Args:
        log_dir: ログ保存ディレクトリ
        log_file: ログファイル名
        enabled: ロギングが有効か

    Returns:
        MemoryAuthorityLogger: 新しいロガーインスタンス
    """
    return MemoryAuthorityLogger(
        log_dir=log_dir,
        log_file=log_file,
        enabled=enabled,
    )
