"""
Drive Permission Change Detector テスト

Phase E: Google Drive 自動権限管理機能
"""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from lib.drive_permission_change_detector import (
    ChangeDetector,
    ChangeDetectionConfig,
    ChangeAlert,
    DetectionResult,
    AlertLevel,
    ChangeType,
    create_detector_from_env,
    EMERGENCY_STOP_FLAG,
    DEFAULT_ALERT_ROOM_ID,
    DEFAULT_MAX_CHANGES_PER_FOLDER,
    DEFAULT_MAX_TOTAL_CHANGES,
    DEFAULT_MAX_REMOVALS_PER_FOLDER,
)


# ================================================================
# Constants Tests
# ================================================================

class TestConstants:
    """定数のテスト"""

    def test_default_values(self):
        """デフォルト値の確認"""
        assert DEFAULT_MAX_CHANGES_PER_FOLDER == 50
        assert DEFAULT_MAX_TOTAL_CHANGES == 200
        assert DEFAULT_MAX_REMOVALS_PER_FOLDER == 20
        assert DEFAULT_ALERT_ROOM_ID == '405315911'

    def test_alert_levels(self):
        """アラートレベルの値"""
        assert AlertLevel.INFO.value == "info"
        assert AlertLevel.WARNING.value == "warning"
        assert AlertLevel.CRITICAL.value == "critical"
        assert AlertLevel.EMERGENCY.value == "emergency"

    def test_change_types(self):
        """変更種別の値"""
        assert ChangeType.ADD.value == "add"
        assert ChangeType.REMOVE.value == "remove"
        assert ChangeType.UPDATE.value == "update"


# ================================================================
# ChangeDetectionConfig Tests
# ================================================================

class TestChangeDetectionConfig:
    """ChangeDetectionConfigのテスト"""

    def test_default_config(self):
        """デフォルト設定"""
        config = ChangeDetectionConfig()

        assert config.max_changes_per_folder == DEFAULT_MAX_CHANGES_PER_FOLDER
        assert config.max_total_changes == DEFAULT_MAX_TOTAL_CHANGES
        assert config.max_removals_per_folder == DEFAULT_MAX_REMOVALS_PER_FOLDER
        assert config.warning_threshold_ratio == 0.75
        assert config.alert_room_id == DEFAULT_ALERT_ROOM_ID
        assert config.stop_on_threshold is True
        assert config.dry_run_on_emergency is True
        assert config.protected_folders == []

    def test_custom_config(self):
        """カスタム設定"""
        config = ChangeDetectionConfig(
            max_changes_per_folder=100,
            max_total_changes=500,
            max_removals_per_folder=30,
            warning_threshold_ratio=0.5,
            alert_room_id="123456",
            stop_on_threshold=False,
            protected_folders=["folder1", "folder2"],
        )

        assert config.max_changes_per_folder == 100
        assert config.max_total_changes == 500
        assert config.max_removals_per_folder == 30
        assert config.warning_threshold_ratio == 0.5
        assert config.alert_room_id == "123456"
        assert config.stop_on_threshold is False
        assert config.protected_folders == ["folder1", "folder2"]


# ================================================================
# ChangeAlert Tests
# ================================================================

class TestChangeAlert:
    """ChangeAlertのテスト"""

    def test_alert_creation(self):
        """アラート作成"""
        alert = ChangeAlert(
            level=AlertLevel.CRITICAL,
            folder_id="folder1",
            folder_name="全社共有",
            changes_count=100,
            additions=50,
            removals=30,
            updates=20,
            threshold=50,
            message="大量変更を検出",
            should_stop=True,
        )

        assert alert.level == AlertLevel.CRITICAL
        assert alert.folder_name == "全社共有"
        assert alert.changes_count == 100
        assert alert.should_stop is True
        assert alert.created_at is not None

    def test_to_chatwork_message_critical(self):
        """Chatworkメッセージ生成（CRITICAL）"""
        alert = ChangeAlert(
            level=AlertLevel.CRITICAL,
            folder_name="全社共有",
            changes_count=100,
            additions=50,
            removals=30,
            updates=20,
            threshold=50,
            message="大量変更を検出しました",
            should_stop=True,
        )

        message = alert.to_chatwork_message()

        assert "🚨" in message
        assert "重大" in message
        assert "全社共有" in message
        assert "100件" in message
        assert "追加:50" in message
        assert "削除:30" in message
        assert "更新:20" in message
        assert "閾値: 50件" in message
        assert "自動停止" in message

    def test_to_chatwork_message_warning(self):
        """Chatworkメッセージ生成（WARNING）"""
        alert = ChangeAlert(
            level=AlertLevel.WARNING,
            folder_name="営業部",
            changes_count=40,
            additions=30,
            removals=5,
            updates=5,
            threshold=50,
            message="警告レベルに達しています",
            should_stop=False,
        )

        message = alert.to_chatwork_message()

        assert "⚠️" in message
        assert "警告" in message
        assert "営業部" in message
        assert "自動停止" not in message

    def test_to_chatwork_message_emergency(self):
        """Chatworkメッセージ生成（EMERGENCY）"""
        alert = ChangeAlert(
            level=AlertLevel.EMERGENCY,
            message="緊急停止フラグが有効です",
            should_stop=True,
            threshold=0,
        )

        message = alert.to_chatwork_message()

        assert "🆘" in message
        assert "緊急" in message


# ================================================================
# DetectionResult Tests
# ================================================================

class TestDetectionResult:
    """DetectionResultのテスト"""

    def test_default_result(self):
        """デフォルト結果"""
        result = DetectionResult()

        assert result.should_stop is False
        assert result.alerts == []
        assert result.total_changes == 0
        assert result.folders_processed == 0
        assert result.emergency_stop is False

    def test_result_with_data(self):
        """データ付き結果"""
        alert = ChangeAlert(
            level=AlertLevel.CRITICAL,
            message="テスト",
            should_stop=True,
        )

        result = DetectionResult(
            should_stop=True,
            alerts=[alert],
            total_changes=100,
            folders_processed=5,
            emergency_stop=False,
        )

        assert result.should_stop is True
        assert len(result.alerts) == 1
        assert result.total_changes == 100


# ================================================================
# ChangeDetector Tests
# ================================================================

class TestChangeDetector:
    """ChangeDetectorのテスト"""

    @pytest.fixture
    def mock_chatwork(self):
        """モックChatworkクライアント"""
        mock = Mock()
        mock.send_message.return_value = {"message_id": "12345"}
        return mock

    @pytest.fixture
    def detector(self, mock_chatwork):
        """テスト用検知器"""
        config = ChangeDetectionConfig(
            max_changes_per_folder=50,
            max_total_changes=200,
            max_removals_per_folder=20,
        )
        return ChangeDetector(config=config, chatwork_client=mock_chatwork)

    def test_init(self):
        """初期化"""
        detector = ChangeDetector()
        assert detector.config is not None
        assert detector._result is not None
        assert detector._folder_changes == {}

    def test_reset(self, detector):
        """リセット"""
        detector._result.total_changes = 100
        detector._folder_changes["test"] = {"total": 10}

        detector.reset()

        assert detector._result.total_changes == 0
        assert detector._folder_changes == {}

    # ================================================================
    # 緊急停止テスト
    # ================================================================

    def test_emergency_stop_disabled(self, detector):
        """緊急停止が無効"""
        with patch.dict(os.environ, {EMERGENCY_STOP_FLAG: 'false'}):
            assert detector.is_emergency_stop_enabled() is False
            assert detector.check_emergency_stop() is False

    def test_emergency_stop_enabled(self, detector):
        """緊急停止が有効"""
        with patch.dict(os.environ, {EMERGENCY_STOP_FLAG: 'true'}):
            assert detector.is_emergency_stop_enabled() is True
            assert detector.check_emergency_stop() is True
            assert detector.should_stop() is True
            assert detector._result.emergency_stop is True

    # ================================================================
    # フォルダ変更チェックテスト
    # ================================================================

    def test_check_folder_changes_under_threshold(self, detector):
        """閾値以下の変更"""
        alert = detector.check_folder_changes(
            folder_id="folder1",
            folder_name="全社共有",
            additions=10,
            removals=5,
            updates=5,
        )

        assert alert is None
        assert detector.should_stop() is False
        assert detector._result.total_changes == 20

    def test_check_folder_changes_over_threshold(self, detector):
        """閾値超過の変更"""
        alert = detector.check_folder_changes(
            folder_id="folder1",
            folder_name="全社共有",
            additions=40,
            removals=10,
            updates=10,
        )

        assert alert is not None
        assert alert.level == AlertLevel.CRITICAL
        assert alert.should_stop is True
        assert detector.should_stop() is True

    def test_check_folder_changes_warning_level(self, detector):
        """警告レベルの変更（75%超過）"""
        alert = detector.check_folder_changes(
            folder_id="folder1",
            folder_name="全社共有",
            additions=30,
            removals=5,
            updates=5,
        )

        assert alert is not None
        assert alert.level == AlertLevel.WARNING
        assert alert.should_stop is False
        assert detector.should_stop() is False

    def test_check_folder_changes_over_removal_threshold(self, detector):
        """削除数の閾値超過"""
        alert = detector.check_folder_changes(
            folder_id="folder1",
            folder_name="全社共有",
            additions=5,
            removals=25,  # max_removals_per_folder=20
            updates=0,
        )

        assert alert is not None
        assert alert.level == AlertLevel.CRITICAL
        assert "削除" in alert.message
        assert detector.should_stop() is True

    def test_check_folder_changes_protected_folder(self, detector):
        """保護フォルダの変更"""
        detector.config.protected_folders = ["folder1"]

        alert = detector.check_folder_changes(
            folder_id="folder1",
            folder_name="重要フォルダ",
            additions=5,
            removals=0,
            updates=0,
        )

        assert alert is not None
        assert alert.level == AlertLevel.WARNING
        assert "保護フォルダ" in alert.message

    # ================================================================
    # 全体変更チェックテスト
    # ================================================================

    def test_check_total_changes_under_threshold(self, detector):
        """全体変更が閾値以下"""
        detector._result.total_changes = 100

        alert = detector.check_total_changes()

        assert alert is None
        assert detector.should_stop() is False

    def test_check_total_changes_over_threshold(self, detector):
        """全体変更が閾値超過"""
        detector._result.total_changes = 250  # max_total_changes=200

        alert = detector.check_total_changes()

        assert alert is not None
        assert alert.level == AlertLevel.CRITICAL
        assert detector.should_stop() is True

    def test_check_total_changes_warning_level(self, detector):
        """全体変更が警告レベル"""
        detector._result.total_changes = 160  # 200 * 0.75 = 150超

        alert = detector.check_total_changes()

        assert alert is not None
        assert alert.level == AlertLevel.WARNING
        assert detector.should_stop() is False

    # ================================================================
    # 結果取得テスト
    # ================================================================

    def test_get_result(self, detector):
        """結果取得"""
        detector.check_folder_changes(
            folder_id="folder1",
            folder_name="Test",
            additions=100,
            removals=0,
            updates=0,
        )

        result = detector.get_result()

        assert result.total_changes == 100
        assert result.folders_processed == 1
        assert len(result.alerts) == 1

    def test_get_critical_alerts(self, detector):
        """CRITICALアラート取得"""
        # 警告レベル
        detector.check_folder_changes(
            folder_id="folder1",
            folder_name="Folder1",
            additions=40,
            removals=0,
            updates=0,
        )
        # クリティカルレベル
        detector.check_folder_changes(
            folder_id="folder2",
            folder_name="Folder2",
            additions=60,
            removals=0,
            updates=0,
        )

        critical_alerts = detector.get_critical_alerts()

        assert len(critical_alerts) == 1
        assert critical_alerts[0].level == AlertLevel.CRITICAL

    # ================================================================
    # アラート送信テスト
    # ================================================================

    def test_send_alert_success(self, detector, mock_chatwork):
        """アラート送信成功"""
        alert = ChangeAlert(
            level=AlertLevel.CRITICAL,
            message="テストアラート",
            should_stop=True,
        )

        result = detector.send_alert(alert)

        assert result is True
        mock_chatwork.send_message.assert_called_once()

    def test_send_alert_failure(self, detector, mock_chatwork):
        """アラート送信失敗"""
        mock_chatwork.send_message.side_effect = Exception("API Error")

        alert = ChangeAlert(
            level=AlertLevel.CRITICAL,
            message="テストアラート",
            should_stop=True,
        )

        result = detector.send_alert(alert)

        assert result is False

    def test_send_all_critical_alerts(self, detector, mock_chatwork):
        """全CRITICALアラート送信"""
        # 複数のアラートを生成
        detector.check_folder_changes(
            folder_id="folder1",
            folder_name="Folder1",
            additions=100,
            removals=0,
            updates=0,
        )
        detector.check_folder_changes(
            folder_id="folder2",
            folder_name="Folder2",
            additions=100,
            removals=0,
            updates=0,
        )

        sent = detector.send_all_critical_alerts()

        assert sent == 2
        assert mock_chatwork.send_message.call_count == 2

    def test_send_summary_alert(self, detector, mock_chatwork):
        """サマリーアラート送信"""
        detector.check_folder_changes(
            folder_id="folder1",
            folder_name="Folder1",
            additions=100,
            removals=0,
            updates=0,
        )

        result = detector.send_summary_alert(dry_run=True)

        assert result is True
        call_args = mock_chatwork.send_message.call_args
        message = call_args[1]['message']
        assert "DRY RUN" in message
        assert "サマリー" in message

    def test_send_summary_alert_no_alerts(self, detector, mock_chatwork):
        """アラートなしでサマリー送信"""
        result = detector.send_summary_alert()

        assert result is True
        mock_chatwork.send_message.assert_not_called()


# ================================================================
# create_detector_from_env Tests
# ================================================================

class TestCreateDetectorFromEnv:
    """create_detector_from_envのテスト"""

    def test_default_env(self):
        """デフォルト環境変数"""
        with patch.dict(os.environ, {}, clear=True):
            detector = create_detector_from_env()

            assert detector.config.max_changes_per_folder == DEFAULT_MAX_CHANGES_PER_FOLDER
            assert detector.config.max_total_changes == DEFAULT_MAX_TOTAL_CHANGES

    def test_custom_env(self):
        """カスタム環境変数"""
        env = {
            'DRIVE_SYNC_MAX_CHANGES_PER_FOLDER': '100',
            'DRIVE_SYNC_MAX_TOTAL_CHANGES': '500',
            'DRIVE_SYNC_MAX_REMOVALS_PER_FOLDER': '30',
            'DRIVE_SYNC_ALERT_ROOM_ID': '123456',
            'DRIVE_SYNC_STOP_ON_THRESHOLD': 'false',
            'DRIVE_SYNC_PROTECTED_FOLDERS': 'folder1,folder2,folder3',
        }

        with patch.dict(os.environ, env):
            detector = create_detector_from_env()

            assert detector.config.max_changes_per_folder == 100
            assert detector.config.max_total_changes == 500
            assert detector.config.max_removals_per_folder == 30
            assert detector.config.alert_room_id == '123456'
            assert detector.config.stop_on_threshold is False
            assert detector.config.protected_folders == ['folder1', 'folder2', 'folder3']


# ================================================================
# Integration Tests
# ================================================================

class TestIntegration:
    """統合テスト"""

    def test_full_flow_under_threshold(self):
        """閾値以下のフルフロー"""
        config = ChangeDetectionConfig(
            max_changes_per_folder=50,
            max_total_changes=200,
        )
        mock_chatwork = Mock()
        detector = ChangeDetector(config=config, chatwork_client=mock_chatwork)

        # 緊急停止チェック
        assert detector.check_emergency_stop() is False

        # 複数フォルダをチェック
        for i in range(5):
            detector.check_folder_changes(
                folder_id=f"folder{i}",
                folder_name=f"Folder{i}",
                additions=10,
                removals=0,
                updates=0,
            )

        # 全体チェック
        detector.check_total_changes()

        # 結果確認
        result = detector.get_result()
        assert result.should_stop is False
        assert result.total_changes == 50
        assert result.folders_processed == 5

    def test_full_flow_over_threshold(self):
        """閾値超過のフルフロー"""
        config = ChangeDetectionConfig(
            max_changes_per_folder=50,
            max_total_changes=200,
        )
        mock_chatwork = Mock()
        mock_chatwork.send_message.return_value = {"message_id": "12345"}
        detector = ChangeDetector(config=config, chatwork_client=mock_chatwork)

        # 大量変更を発生させる
        detector.check_folder_changes(
            folder_id="folder1",
            folder_name="全社共有",
            additions=100,
            removals=0,
            updates=0,
        )

        # 結果確認
        assert detector.should_stop() is True

        # アラート送信
        sent = detector.send_all_critical_alerts()
        assert sent == 1

        # サマリー送信
        detector.send_summary_alert(dry_run=True)
        assert mock_chatwork.send_message.call_count == 2
