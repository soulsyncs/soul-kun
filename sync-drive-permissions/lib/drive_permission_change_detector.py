"""
Google Drive 権限変更検知・アラートサービス

大量の権限変更を検知して、自動停止・アラート送信する機能。

使用例:
    from lib.drive_permission_change_detector import (
        ChangeDetector,
        ChangeDetectionConfig,
    )

    config = ChangeDetectionConfig(
        max_changes_per_folder=50,
        max_total_changes=200,
        alert_room_id="405315911",
    )

    detector = ChangeDetector(config)

    # 変更をチェック
    if detector.should_stop(changes_count=100, folder_name="全社共有"):
        alert = detector.create_alert(...)
        await detector.send_alert(alert)

Phase E: Google Drive 自動権限管理機能
Created: 2026-01-26
"""

import os
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

from lib.chatwork import ChatworkClient


logger = logging.getLogger(__name__)


# ================================================================
# 定数
# ================================================================

# デフォルトのアラート送信先（管理部チャット）
DEFAULT_ALERT_ROOM_ID = os.getenv('SOULKUN_ADMIN_ROOM_ID', '405315911')

# デフォルトの閾値
DEFAULT_MAX_CHANGES_PER_FOLDER = 50
DEFAULT_MAX_TOTAL_CHANGES = 200
DEFAULT_MAX_REMOVALS_PER_FOLDER = 20

# 緊急停止フラグ（環境変数で制御）
EMERGENCY_STOP_FLAG = 'DRIVE_PERMISSION_SYNC_EMERGENCY_STOP'


class AlertLevel(str, Enum):
    """アラートレベル"""
    INFO = "info"           # 情報（閾値の50%超過）
    WARNING = "warning"     # 警告（閾値の75%超過）
    CRITICAL = "critical"   # 重大（閾値超過・自動停止）
    EMERGENCY = "emergency" # 緊急（手動介入必要）


class ChangeType(str, Enum):
    """変更種別"""
    ADD = "add"
    REMOVE = "remove"
    UPDATE = "update"


# ================================================================
# データクラス
# ================================================================

@dataclass
class ChangeDetectionConfig:
    """
    変更検知の設定

    Attributes:
        max_changes_per_folder: 1フォルダあたりの最大変更数
        max_total_changes: 全体の最大変更数
        max_removals_per_folder: 1フォルダあたりの最大削除数
        warning_threshold_ratio: 警告を出す閾値（閾値の何%で警告）
        alert_room_id: アラート送信先のChatworkルームID
        stop_on_threshold: 閾値超過時に自動停止するか
        dry_run_on_emergency: 緊急時に強制的にdry_runにするか
        protected_folders: 保護するフォルダID（より慎重に処理）
    """
    max_changes_per_folder: int = DEFAULT_MAX_CHANGES_PER_FOLDER
    max_total_changes: int = DEFAULT_MAX_TOTAL_CHANGES
    max_removals_per_folder: int = DEFAULT_MAX_REMOVALS_PER_FOLDER
    warning_threshold_ratio: float = 0.75  # 75%で警告
    alert_room_id: str = DEFAULT_ALERT_ROOM_ID
    stop_on_threshold: bool = True
    dry_run_on_emergency: bool = True
    protected_folders: List[str] = field(default_factory=list)


@dataclass
class ChangeAlert:
    """
    変更アラート

    Attributes:
        level: アラートレベル
        folder_id: 対象フォルダID
        folder_name: 対象フォルダ名
        changes_count: 変更数
        additions: 追加数
        removals: 削除数
        updates: 更新数
        threshold: 閾値
        message: アラートメッセージ
        should_stop: 停止すべきか
        created_at: 作成日時
    """
    level: AlertLevel
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    changes_count: int = 0
    additions: int = 0
    removals: int = 0
    updates: int = 0
    threshold: int = 0
    message: str = ""
    should_stop: bool = False
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_chatwork_message(self) -> str:
        """Chatwork用のメッセージを生成"""
        emoji = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.CRITICAL: "🚨",
            AlertLevel.EMERGENCY: "🆘",
        }.get(self.level, "📢")

        title = {
            AlertLevel.INFO: "情報",
            AlertLevel.WARNING: "警告",
            AlertLevel.CRITICAL: "重大",
            AlertLevel.EMERGENCY: "緊急",
        }.get(self.level, "通知")

        lines = [
            f"{emoji} [Google Drive権限同期] {title}",
            "",
            self.message,
            "",
        ]

        if self.folder_name:
            lines.append(f"📁 フォルダ: {self.folder_name}")

        lines.extend([
            f"📊 変更数: {self.changes_count}件（追加:{self.additions} 削除:{self.removals} 更新:{self.updates}）",
            f"📏 閾値: {self.threshold}件",
        ])

        if self.should_stop:
            lines.extend([
                "",
                "⛔ 同期処理を自動停止しました。",
                "手動での確認が必要です。",
            ])

        lines.extend([
            "",
            f"⏰ {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
        ])

        return "\n".join(lines)


@dataclass
class DetectionResult:
    """
    検知結果

    Attributes:
        should_stop: 停止すべきか
        alerts: 発生したアラートのリスト
        total_changes: 累計変更数
        folders_processed: 処理済みフォルダ数
        emergency_stop: 緊急停止が有効か
    """
    should_stop: bool = False
    alerts: List[ChangeAlert] = field(default_factory=list)
    total_changes: int = 0
    folders_processed: int = 0
    emergency_stop: bool = False


# ================================================================
# Change Detector
# ================================================================

class ChangeDetector:
    """
    権限変更検知クラス

    大量の変更を検知し、閾値を超えた場合にアラートを送信して
    自動停止するかどうかを判断する。
    """

    def __init__(
        self,
        config: Optional[ChangeDetectionConfig] = None,
        chatwork_client: Optional[ChatworkClient] = None,
    ):
        """
        Args:
            config: 検知設定
            chatwork_client: Chatworkクライアント（省略時は自動生成）
        """
        self.config = config or ChangeDetectionConfig()
        self._chatwork = chatwork_client
        self._result = DetectionResult()
        self._folder_changes: Dict[str, Dict[str, int]] = {}

    @property
    def chatwork(self) -> ChatworkClient:
        """Chatworkクライアントを取得（遅延初期化）"""
        if self._chatwork is None:
            self._chatwork = ChatworkClient()
        return self._chatwork

    def reset(self):
        """検知状態をリセット"""
        self._result = DetectionResult()
        self._folder_changes = {}

    # ================================================================
    # 緊急停止チェック
    # ================================================================

    def is_emergency_stop_enabled(self) -> bool:
        """緊急停止が有効かチェック"""
        return os.getenv(EMERGENCY_STOP_FLAG, 'false').lower() == 'true'

    def check_emergency_stop(self) -> bool:
        """
        緊急停止をチェックし、必要ならアラートを発行

        Returns:
            緊急停止が必要な場合True
        """
        if self.is_emergency_stop_enabled():
            self._result.emergency_stop = True
            self._result.should_stop = True

            alert = ChangeAlert(
                level=AlertLevel.EMERGENCY,
                message="緊急停止フラグが有効です。全ての同期処理を中止します。",
                should_stop=True,
                threshold=0,
            )
            self._result.alerts.append(alert)
            logger.critical("Emergency stop flag is enabled!")
            return True

        return False

    # ================================================================
    # 変更チェック
    # ================================================================

    def check_folder_changes(
        self,
        folder_id: str,
        folder_name: str,
        additions: int = 0,
        removals: int = 0,
        updates: int = 0,
    ) -> Optional[ChangeAlert]:
        """
        フォルダ単位の変更をチェック

        Args:
            folder_id: フォルダID
            folder_name: フォルダ名
            additions: 追加数
            removals: 削除数
            updates: 更新数

        Returns:
            アラート（閾値を超えた場合）
        """
        total = additions + removals + updates

        # フォルダごとの変更を記録
        self._folder_changes[folder_id] = {
            'name': folder_name,
            'additions': additions,
            'removals': removals,
            'updates': updates,
            'total': total,
        }

        # 累計を更新
        self._result.total_changes += total
        self._result.folders_processed += 1

        alert = None

        # 削除数のチェック（権限削除は特に慎重に）
        if removals > self.config.max_removals_per_folder:
            alert = ChangeAlert(
                level=AlertLevel.CRITICAL,
                folder_id=folder_id,
                folder_name=folder_name,
                changes_count=total,
                additions=additions,
                removals=removals,
                updates=updates,
                threshold=self.config.max_removals_per_folder,
                message=f"フォルダ「{folder_name}」で大量の権限削除を検出しました",
                should_stop=self.config.stop_on_threshold,
            )

        # 変更数のチェック
        elif total > self.config.max_changes_per_folder:
            alert = ChangeAlert(
                level=AlertLevel.CRITICAL,
                folder_id=folder_id,
                folder_name=folder_name,
                changes_count=total,
                additions=additions,
                removals=removals,
                updates=updates,
                threshold=self.config.max_changes_per_folder,
                message=f"フォルダ「{folder_name}」で大量の変更を検出しました",
                should_stop=self.config.stop_on_threshold,
            )

        # 警告レベルのチェック
        elif total > self.config.max_changes_per_folder * self.config.warning_threshold_ratio:
            alert = ChangeAlert(
                level=AlertLevel.WARNING,
                folder_id=folder_id,
                folder_name=folder_name,
                changes_count=total,
                additions=additions,
                removals=removals,
                updates=updates,
                threshold=self.config.max_changes_per_folder,
                message=f"フォルダ「{folder_name}」の変更数が警告レベルに達しています",
                should_stop=False,
            )

        # 保護フォルダのチェック
        if folder_id in self.config.protected_folders:
            if total > 0 and (alert is None or alert.level != AlertLevel.CRITICAL):
                alert = ChangeAlert(
                    level=AlertLevel.WARNING,
                    folder_id=folder_id,
                    folder_name=folder_name,
                    changes_count=total,
                    additions=additions,
                    removals=removals,
                    updates=updates,
                    threshold=self.config.max_changes_per_folder,
                    message=f"保護フォルダ「{folder_name}」で変更を検出しました",
                    should_stop=False,
                )

        if alert:
            self._result.alerts.append(alert)
            if alert.should_stop:
                self._result.should_stop = True

        return alert

    def check_total_changes(self) -> Optional[ChangeAlert]:
        """
        全体の変更数をチェック

        Returns:
            アラート（閾値を超えた場合）
        """
        if self._result.total_changes > self.config.max_total_changes:
            alert = ChangeAlert(
                level=AlertLevel.CRITICAL,
                changes_count=self._result.total_changes,
                threshold=self.config.max_total_changes,
                message=f"全体の変更数が閾値を超えました（{self._result.total_changes}件）",
                should_stop=self.config.stop_on_threshold,
            )
            self._result.alerts.append(alert)
            self._result.should_stop = True
            return alert

        elif self._result.total_changes > self.config.max_total_changes * self.config.warning_threshold_ratio:
            alert = ChangeAlert(
                level=AlertLevel.WARNING,
                changes_count=self._result.total_changes,
                threshold=self.config.max_total_changes,
                message=f"全体の変更数が警告レベルに達しています（{self._result.total_changes}件）",
                should_stop=False,
            )
            self._result.alerts.append(alert)
            return alert

        return None

    # ================================================================
    # 結果取得
    # ================================================================

    def should_stop(self) -> bool:
        """停止すべきかどうかを返す"""
        return self._result.should_stop or self._result.emergency_stop

    def get_result(self) -> DetectionResult:
        """検知結果を取得"""
        return self._result

    def get_critical_alerts(self) -> List[ChangeAlert]:
        """CRITICAL以上のアラートを取得"""
        return [
            a for a in self._result.alerts
            if a.level in (AlertLevel.CRITICAL, AlertLevel.EMERGENCY)
        ]

    # ================================================================
    # アラート送信
    # ================================================================

    def send_alert(self, alert: ChangeAlert) -> bool:
        """
        アラートをChatworkに送信

        Args:
            alert: 送信するアラート

        Returns:
            送信成功ならTrue
        """
        try:
            message = alert.to_chatwork_message()
            room_id = int(self.config.alert_room_id)

            result = self.chatwork.send_message(
                room_id=room_id,
                message=message
            )

            logger.info(
                f"Alert sent to Chatwork room {room_id}: "
                f"level={alert.level.value}, message_id={result.get('message_id')}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            return False

    def send_all_critical_alerts(self) -> int:
        """
        全てのCRITICAL以上のアラートを送信

        Returns:
            送信成功したアラート数
        """
        sent = 0
        for alert in self.get_critical_alerts():
            if self.send_alert(alert):
                sent += 1
        return sent

    def send_summary_alert(
        self,
        dry_run: bool = False,
        additional_message: str = "",
    ) -> bool:
        """
        サマリーアラートを送信

        Args:
            dry_run: dry_runモードかどうか
            additional_message: 追加メッセージ

        Returns:
            送信成功ならTrue
        """
        result = self._result

        # アラートがない場合は送信しない
        if not result.alerts and not result.should_stop:
            return True

        mode = "[DRY RUN] " if dry_run else ""
        level = AlertLevel.CRITICAL if result.should_stop else AlertLevel.WARNING

        lines = [
            f"📋 {mode}Google Drive権限同期 サマリーレポート",
            "",
            f"処理フォルダ数: {result.folders_processed}",
            f"累計変更数: {result.total_changes}",
            f"発生アラート数: {len(result.alerts)}",
        ]

        # 停止した場合
        if result.should_stop:
            lines.extend([
                "",
                "⛔ 同期処理を停止しました",
            ])
            if result.emergency_stop:
                lines.append("  → 緊急停止フラグによる停止")
            else:
                lines.append("  → 閾値超過による自動停止")

        # フォルダ別の変更数
        if self._folder_changes:
            lines.extend(["", "📁 フォルダ別変更数:"])
            for folder_id, changes in sorted(
                self._folder_changes.items(),
                key=lambda x: x[1]['total'],
                reverse=True
            )[:10]:  # 上位10件
                lines.append(
                    f"  - {changes['name']}: {changes['total']}件 "
                    f"(+{changes['additions']} -{changes['removals']} ~{changes['updates']})"
                )

        # 追加メッセージ
        if additional_message:
            lines.extend(["", additional_message])

        lines.extend([
            "",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ])

        alert = ChangeAlert(
            level=level,
            changes_count=result.total_changes,
            message="\n".join(lines),
            should_stop=result.should_stop,
        )

        return self.send_alert(alert)


# ================================================================
# ユーティリティ関数
# ================================================================

def create_detector_from_env() -> ChangeDetector:
    """
    環境変数から検知器を作成

    環境変数:
        DRIVE_SYNC_MAX_CHANGES_PER_FOLDER: フォルダあたり最大変更数
        DRIVE_SYNC_MAX_TOTAL_CHANGES: 全体の最大変更数
        DRIVE_SYNC_MAX_REMOVALS_PER_FOLDER: フォルダあたり最大削除数
        DRIVE_SYNC_ALERT_ROOM_ID: アラート送信先ルームID
        DRIVE_SYNC_STOP_ON_THRESHOLD: 閾値超過時に停止するか
        DRIVE_SYNC_PROTECTED_FOLDERS: 保護フォルダID（カンマ区切り）

    Returns:
        ChangeDetector
    """
    config = ChangeDetectionConfig(
        max_changes_per_folder=int(os.getenv(
            'DRIVE_SYNC_MAX_CHANGES_PER_FOLDER',
            DEFAULT_MAX_CHANGES_PER_FOLDER
        )),
        max_total_changes=int(os.getenv(
            'DRIVE_SYNC_MAX_TOTAL_CHANGES',
            DEFAULT_MAX_TOTAL_CHANGES
        )),
        max_removals_per_folder=int(os.getenv(
            'DRIVE_SYNC_MAX_REMOVALS_PER_FOLDER',
            DEFAULT_MAX_REMOVALS_PER_FOLDER
        )),
        alert_room_id=os.getenv(
            'DRIVE_SYNC_ALERT_ROOM_ID',
            DEFAULT_ALERT_ROOM_ID
        ),
        stop_on_threshold=os.getenv(
            'DRIVE_SYNC_STOP_ON_THRESHOLD',
            'true'
        ).lower() == 'true',
        protected_folders=[
            f.strip() for f in
            os.getenv('DRIVE_SYNC_PROTECTED_FOLDERS', '').split(',')
            if f.strip()
        ],
    )

    return ChangeDetector(config)


# ================================================================
# エクスポート
# ================================================================

__all__ = [
    'ChangeDetector',
    'ChangeDetectionConfig',
    'ChangeAlert',
    'DetectionResult',
    'AlertLevel',
    'ChangeType',
    'create_detector_from_env',
    'EMERGENCY_STOP_FLAG',
    'DEFAULT_ALERT_ROOM_ID',
    'DEFAULT_MAX_CHANGES_PER_FOLDER',
    'DEFAULT_MAX_TOTAL_CHANGES',
    'DEFAULT_MAX_REMOVALS_PER_FOLDER',
]
