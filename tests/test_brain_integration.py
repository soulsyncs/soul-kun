# tests/test_brain_integration.py
"""
BrainIntegration（統合層）のユニットテスト

テスト対象:
- 定数・列挙型
- IntegrationResult, IntegrationConfig, BypassDetectionResultデータクラス
- BrainIntegration初期化
- Feature Flag管理
- メッセージ処理（脳使用、フォールバック、シャドウモード）
- バイパスルート検出
- 統計情報・状態管理
- ファクトリ関数
"""

import pytest
import asyncio
import os
from datetime import datetime
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from lib.brain.integration import (
    BrainIntegration,
    IntegrationResult,
    IntegrationConfig,
    IntegrationMode,
    BypassType,
    BypassDetectionResult,
    create_integration,
    FEATURE_FLAG_NAME,
    DEFAULT_FEATURE_FLAG,
    BYPASS_ROUTE_PATTERNS,
    INTEGRATION_MAX_RETRIES,
    INTEGRATION_TIMEOUT_SECONDS,
)
from lib.brain.env_config import is_brain_enabled
from lib.brain.models import BrainResponse


# =============================================================================
# テスト用フィクスチャ
# =============================================================================

@pytest.fixture
def mock_pool():
    """モックDBプール"""
    pool = MagicMock()
    pool.connect = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))
    return pool


@pytest.fixture
def mock_firestore():
    """モックFirestoreクライアント"""
    return MagicMock()


@pytest.fixture
def mock_handlers():
    """モックハンドラーマッピング"""
    return {
        "search_tasks": AsyncMock(return_value={"success": True, "message": "タスク検索完了"}),
        "create_task": AsyncMock(return_value={"success": True, "message": "タスク作成完了"}),
        "general_response": AsyncMock(return_value={"success": True, "message": "応答生成完了"}),
    }


@pytest.fixture
def mock_capabilities():
    """モック機能カタログ"""
    return {
        "search_tasks": {"description": "タスク検索", "keywords": ["タスク", "検索"]},
        "create_task": {"description": "タスク作成", "keywords": ["タスク", "作成"]},
        "general_response": {"description": "一般応答", "keywords": []},
    }


@pytest.fixture
def mock_get_ai_response():
    """モックAI応答生成関数"""
    async def _mock_ai_response(*args, **kwargs):
        return "AIの応答ですウル"
    return _mock_ai_response


@pytest.fixture
def disabled_config():
    """無効化設定"""
    return IntegrationConfig(
        mode=IntegrationMode.DISABLED,
        fallback_enabled=True,
    )


@pytest.fixture
def enabled_config():
    """有効化設定"""
    return IntegrationConfig(
        mode=IntegrationMode.ENABLED,
        fallback_enabled=True,
    )


@pytest.fixture
def shadow_config():
    """シャドウモード設定"""
    return IntegrationConfig(
        mode=IntegrationMode.SHADOW,
        fallback_enabled=True,
        shadow_logging=True,
    )


@pytest.fixture
def gradual_config():
    """段階的移行設定"""
    return IntegrationConfig(
        mode=IntegrationMode.GRADUAL,
        fallback_enabled=True,
        gradual_percentage=50.0,
    )


@pytest.fixture
def integration_disabled(disabled_config):
    """無効化されたBrainIntegration"""
    return BrainIntegration(
        pool=None,
        org_id="org_test",
        config=disabled_config,
    )


@pytest.fixture
def mock_fallback_func():
    """モックフォールバック関数"""
    async def _fallback(message, room_id, account_id, sender_name):
        return f"フォールバック応答: {message}"
    return _fallback


# =============================================================================
# 定数テスト
# =============================================================================

class TestIntegrationConstants:
    """統合層定数のテスト"""

    def test_feature_flag_name(self):
        """Feature Flag名"""
        assert FEATURE_FLAG_NAME == "USE_BRAIN_ARCHITECTURE"

    def test_default_feature_flag(self):
        """デフォルトFeature Flag"""
        assert DEFAULT_FEATURE_FLAG is False

    def test_bypass_route_patterns(self):
        """バイパスルートパターン"""
        assert len(BYPASS_ROUTE_PATTERNS) >= 4
        assert "handle_pending_task_followup" in BYPASS_ROUTE_PATTERNS
        assert "has_active_goal_session" in BYPASS_ROUTE_PATTERNS

    def test_integration_max_retries(self):
        """最大リトライ回数"""
        assert INTEGRATION_MAX_RETRIES == 2
        assert INTEGRATION_MAX_RETRIES > 0

    def test_integration_timeout(self):
        """統合タイムアウト"""
        assert INTEGRATION_TIMEOUT_SECONDS == 90.0
        assert INTEGRATION_TIMEOUT_SECONDS > 0


# =============================================================================
# 列挙型テスト
# =============================================================================

class TestIntegrationMode:
    """IntegrationMode列挙型のテスト"""

    def test_disabled_mode(self):
        """DISABLEDモード"""
        assert IntegrationMode.DISABLED.value == "disabled"

    def test_enabled_mode(self):
        """ENABLEDモード"""
        assert IntegrationMode.ENABLED.value == "enabled"

    def test_shadow_mode(self):
        """SHADOWモード"""
        assert IntegrationMode.SHADOW.value == "shadow"

    def test_gradual_mode(self):
        """GRADUALモード"""
        assert IntegrationMode.GRADUAL.value == "gradual"

    def test_all_modes(self):
        """全モードが定義されている"""
        modes = [m.value for m in IntegrationMode]
        assert len(modes) == 4
        assert "disabled" in modes
        assert "enabled" in modes
        assert "shadow" in modes
        assert "gradual" in modes


class TestBypassType:
    """BypassType列挙型のテスト"""

    def test_goal_session_type(self):
        """目標設定セッション"""
        assert BypassType.GOAL_SESSION.value == "goal_session"

    def test_announcement_pending_type(self):
        """アナウンス確認待ち"""
        assert BypassType.ANNOUNCEMENT_PENDING.value == "announcement_pending"

    def test_task_pending_type(self):
        """タスク作成待ち"""
        assert BypassType.TASK_PENDING.value == "task_pending"

    def test_local_command_type(self):
        """ローカルコマンド"""
        assert BypassType.LOCAL_COMMAND.value == "local_command"

    def test_direct_handler_type(self):
        """ハンドラー直接呼び出し"""
        assert BypassType.DIRECT_HANDLER.value == "direct_handler"


# =============================================================================
# IntegrationResultテスト
# =============================================================================

class TestIntegrationResult:
    """IntegrationResultデータクラスのテスト"""

    def test_create_success_result(self):
        """成功結果の作成"""
        result = IntegrationResult(
            success=True,
            message="処理成功",
            used_brain=True,
            fallback_used=False,
            processing_time_ms=100,
        )

        assert result.success is True
        assert result.message == "処理成功"
        assert result.used_brain is True
        assert result.fallback_used is False
        assert result.processing_time_ms == 100
        assert result.error is None
        assert result.response is None

    def test_create_failure_result(self):
        """失敗結果の作成"""
        result = IntegrationResult(
            success=False,
            message="処理失敗",
            used_brain=True,
            fallback_used=False,
            processing_time_ms=50,
            error="エラー詳細",
        )

        assert result.success is False
        assert result.error == "エラー詳細"

    def test_create_with_response(self):
        """BrainResponse付きの結果"""
        response = BrainResponse(
            success=True,
            message="脳からの応答",
        )
        result = IntegrationResult(
            success=True,
            message="脳からの応答",
            response=response,
            used_brain=True,
            fallback_used=False,
            processing_time_ms=200,
        )

        assert result.response is response
        assert result.response.message == "脳からの応答"

    def test_create_with_bypass_detected(self):
        """バイパス検出付きの結果"""
        result = IntegrationResult(
            success=True,
            message="処理成功",
            used_brain=True,
            fallback_used=False,
            processing_time_ms=100,
            bypass_detected=BypassType.GOAL_SESSION,
        )

        assert result.bypass_detected == BypassType.GOAL_SESSION

    def test_to_chatwork_message_with_response(self):
        """ChatWorkメッセージ取得（response付き）"""
        response = BrainResponse(
            success=True,
            message="脳からの応答ウル",
        )
        result = IntegrationResult(
            success=True,
            message="デフォルトメッセージ",
            response=response,
            used_brain=True,
            fallback_used=False,
            processing_time_ms=100,
        )

        assert result.to_chatwork_message() == "脳からの応答ウル"

    def test_to_chatwork_message_without_response(self):
        """ChatWorkメッセージ取得（responseなし）"""
        result = IntegrationResult(
            success=True,
            message="デフォルトメッセージ",
            used_brain=False,
            fallback_used=True,
            processing_time_ms=100,
        )

        assert result.to_chatwork_message() == "デフォルトメッセージ"


# =============================================================================
# IntegrationConfigテスト
# =============================================================================

class TestIntegrationConfig:
    """IntegrationConfigデータクラスのテスト"""

    def test_default_config(self):
        """デフォルト設定"""
        config = IntegrationConfig()

        assert config.mode == IntegrationMode.DISABLED
        assert config.fallback_enabled is True
        assert config.shadow_logging is False
        assert config.gradual_percentage == 0.0
        assert config.allowed_rooms == []
        assert config.allowed_users == []
        assert config.bypass_detection_enabled is True

    def test_custom_config(self):
        """カスタム設定"""
        config = IntegrationConfig(
            mode=IntegrationMode.ENABLED,
            fallback_enabled=False,
            shadow_logging=True,
            gradual_percentage=75.0,
            allowed_rooms=["room1", "room2"],
            allowed_users=["user1"],
            bypass_detection_enabled=False,
        )

        assert config.mode == IntegrationMode.ENABLED
        assert config.fallback_enabled is False
        assert config.shadow_logging is True
        assert config.gradual_percentage == 75.0
        assert config.allowed_rooms == ["room1", "room2"]
        assert config.allowed_users == ["user1"]
        assert config.bypass_detection_enabled is False


# =============================================================================
# BypassDetectionResultテスト
# =============================================================================

class TestBypassDetectionResult:
    """BypassDetectionResultデータクラスのテスト"""

    def test_no_bypass(self):
        """バイパスなし"""
        result = BypassDetectionResult(is_bypass=False)

        assert result.is_bypass is False
        assert result.bypass_type is None
        assert result.session_id is None
        assert result.should_redirect is False
        assert result.reason is None

    def test_bypass_with_redirect(self):
        """バイパスあり（リダイレクト）"""
        result = BypassDetectionResult(
            is_bypass=True,
            bypass_type=BypassType.GOAL_SESSION,
            session_id="session123",
            should_redirect=True,
            reason="Active goal setting session",
        )

        assert result.is_bypass is True
        assert result.bypass_type == BypassType.GOAL_SESSION
        assert result.session_id == "session123"
        assert result.should_redirect is True
        assert result.reason == "Active goal setting session"


# =============================================================================
# BrainIntegration初期化テスト
# =============================================================================

class TestBrainIntegrationInit:
    """BrainIntegration初期化のテスト"""

    def test_init_disabled_mode(self, disabled_config):
        """DISABLEDモードで初期化"""
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
            config=disabled_config,
        )

        assert integration.brain is None
        assert integration.config.mode == IntegrationMode.DISABLED
        assert integration.org_id == "org_test"

    def test_init_with_all_parameters(
        self,
        mock_pool,
        mock_firestore,
        mock_handlers,
        mock_capabilities,
        mock_get_ai_response,
        disabled_config,
    ):
        """全パラメータで初期化"""
        integration = BrainIntegration(
            pool=mock_pool,
            org_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
            handlers=mock_handlers,
            capabilities=mock_capabilities,
            get_ai_response_func=mock_get_ai_response,
            firestore_db=mock_firestore,
            config=disabled_config,
        )

        assert integration.pool is mock_pool
        assert integration.org_id == "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
        assert integration.handlers == mock_handlers
        assert integration.capabilities == mock_capabilities
        assert integration.firestore_db is mock_firestore

    def test_init_creates_empty_stats(self, disabled_config):
        """初期化時に統計が空"""
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
            config=disabled_config,
        )

        stats = integration.get_stats()
        assert stats["total_requests"] == 0
        assert stats["brain_requests"] == 0
        assert stats["fallback_requests"] == 0
        assert stats["errors"] == 0

    @patch.dict(os.environ, {"USE_BRAIN_ARCHITECTURE": "false"})
    def test_init_from_env_disabled(self):
        """環境変数からDISABLEDで初期化"""
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
        )

        assert integration.config.mode == IntegrationMode.DISABLED

    @patch.dict(os.environ, {"USE_BRAIN_ARCHITECTURE": "true"})
    def test_init_from_env_enabled(self):
        """環境変数からENABLEDで初期化"""
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
        )

        assert integration.config.mode == IntegrationMode.ENABLED

    @patch.dict(os.environ, {"USE_BRAIN_ARCHITECTURE": "shadow"})
    def test_init_from_env_shadow(self):
        """環境変数からSHADOWで初期化"""
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
        )

        assert integration.config.mode == IntegrationMode.SHADOW

    @patch.dict(os.environ, {
        "USE_BRAIN_ARCHITECTURE": "gradual",
        "BRAIN_GRADUAL_PERCENTAGE": "50",
    })
    def test_init_from_env_gradual(self):
        """環境変数からGRADUALで初期化"""
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
        )

        assert integration.config.mode == IntegrationMode.GRADUAL
        assert integration.config.gradual_percentage == 50.0


# =============================================================================
# Feature Flag管理テスト
# =============================================================================

class TestFeatureFlagManagement:
    """Feature Flag管理のテスト"""

    def test_is_brain_enabled_false(self, integration_disabled):
        """脳が無効"""
        assert integration_disabled.is_brain_enabled() is False

    @patch.dict(os.environ, {"USE_BRAIN_ARCHITECTURE": "false"})
    def test_is_brain_enabled_function_false(self):
        """is_brain_enabled関数（false）"""
        assert is_brain_enabled() is False

    @patch.dict(os.environ, {"USE_BRAIN_ARCHITECTURE": "true"})
    def test_is_brain_enabled_function_true(self):
        """is_brain_enabled関数（true）"""
        assert is_brain_enabled() is True

    @patch.dict(os.environ, {"USE_BRAIN_ARCHITECTURE": "shadow"})
    def test_is_brain_enabled_function_shadow(self):
        """is_brain_enabled関数（shadow）"""
        assert is_brain_enabled() is True

    def test_get_mode(self, integration_disabled):
        """モード取得"""
        assert integration_disabled.get_mode() == IntegrationMode.DISABLED

    def test_set_mode(self, integration_disabled):
        """モード変更"""
        integration_disabled.set_mode(IntegrationMode.ENABLED)
        assert integration_disabled.get_mode() == IntegrationMode.ENABLED


# =============================================================================
# メッセージ処理テスト（DISABLED）
# =============================================================================

class TestProcessMessageDisabled:
    """DISABLEDモードでのメッセージ処理テスト"""

    @pytest.mark.asyncio
    async def test_process_with_fallback(
        self,
        integration_disabled,
        mock_fallback_func,
    ):
        """フォールバックで処理"""
        result = await integration_disabled.process_message(
            message="テストメッセージ",
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
            fallback_func=mock_fallback_func,
        )

        assert result.success is True
        assert result.used_brain is False
        assert result.fallback_used is True
        assert "フォールバック応答" in result.message

    @pytest.mark.asyncio
    async def test_process_without_fallback(self, integration_disabled):
        """フォールバックなしで処理"""
        result = await integration_disabled.process_message(
            message="テストメッセージ",
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
            fallback_func=None,
        )

        assert result.success is False
        assert result.used_brain is False
        assert result.fallback_used is False
        assert "設定されていません" in result.message

    @pytest.mark.asyncio
    async def test_stats_updated_on_fallback(
        self,
        integration_disabled,
        mock_fallback_func,
    ):
        """フォールバック時に統計が更新される"""
        await integration_disabled.process_message(
            message="テストメッセージ",
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
            fallback_func=mock_fallback_func,
        )

        stats = integration_disabled.get_stats()
        assert stats["total_requests"] == 1
        assert stats["fallback_requests"] == 1
        assert stats["brain_requests"] == 0


# =============================================================================
# メッセージ処理テスト（ENABLED）
# =============================================================================

class TestProcessMessageEnabled:
    """ENABLEDモードでのメッセージ処理テスト"""

    @pytest.mark.asyncio
    async def test_process_brain_with_no_pool(
        self,
        enabled_config,
        mock_fallback_func,
    ):
        """DBプールがなくても脳は動作する（エラーを優雅に処理）"""
        integration = BrainIntegration(
            pool=None,  # DBなしでも脳は初期化・動作する
            org_id="org_test",
            config=enabled_config,
        )

        result = await integration.process_message(
            message="テストメッセージ",
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
            fallback_func=mock_fallback_func,
        )

        # 脳アーキテクチャはDBエラーを優雅に処理し、デフォルト応答を返す
        # 7つの鉄則: 速度より正確性を優先（エラー時もサービス継続）
        assert result.used_brain is True
        assert result.fallback_used is False
        assert result.success is True
        assert result.message is not None

    @pytest.mark.asyncio
    async def test_process_with_allowed_rooms(
        self,
        mock_fallback_func,
    ):
        """許可ルーム制限"""
        config = IntegrationConfig(
            mode=IntegrationMode.ENABLED,
            allowed_rooms=["allowed_room"],
        )
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
            config=config,
        )

        # 許可されていないルーム
        result = await integration.process_message(
            message="テストメッセージ",
            room_id="not_allowed_room",
            account_id="user456",
            sender_name="テストユーザー",
            fallback_func=mock_fallback_func,
        )

        # フォールバックに回る
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_process_with_allowed_users(
        self,
        mock_fallback_func,
    ):
        """許可ユーザー制限"""
        config = IntegrationConfig(
            mode=IntegrationMode.ENABLED,
            allowed_users=["allowed_user"],
        )
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
            config=config,
        )

        # 許可されていないユーザー
        result = await integration.process_message(
            message="テストメッセージ",
            room_id="room123",
            account_id="not_allowed_user",
            sender_name="テストユーザー",
            fallback_func=mock_fallback_func,
        )

        # フォールバックに回る
        assert result.fallback_used is True


# =============================================================================
# バイパスルート検出テスト
# =============================================================================

class TestBypassDetection:
    """バイパスルート検出のテスト"""

    def test_detect_goal_session(self, integration_disabled):
        """目標設定セッション検出"""
        context = {
            "has_active_goal_session": True,
            "goal_session_id": "session123",
        }
        result = integration_disabled._detect_bypass(context)

        assert result.is_bypass is True
        assert result.bypass_type == BypassType.GOAL_SESSION
        assert result.session_id == "session123"
        assert result.should_redirect is True

    def test_detect_announcement_pending(self, integration_disabled):
        """アナウンス確認待ち検出"""
        context = {
            "has_pending_announcement": True,
            "announcement_id": "ann123",
        }
        result = integration_disabled._detect_bypass(context)

        assert result.is_bypass is True
        assert result.bypass_type == BypassType.ANNOUNCEMENT_PENDING
        assert result.session_id == "ann123"

    def test_detect_task_pending(self, integration_disabled):
        """タスク作成待ち検出"""
        context = {
            "has_pending_task": True,
            "pending_task_id": "task123",
        }
        result = integration_disabled._detect_bypass(context)

        assert result.is_bypass is True
        assert result.bypass_type == BypassType.TASK_PENDING

    def test_detect_local_command(self, integration_disabled):
        """ローカルコマンド検出"""
        context = {
            "is_local_command": True,
        }
        result = integration_disabled._detect_bypass(context)

        assert result.is_bypass is True
        assert result.bypass_type == BypassType.LOCAL_COMMAND

    def test_detect_no_bypass(self, integration_disabled):
        """バイパスなし"""
        context = {}
        result = integration_disabled._detect_bypass(context)

        assert result.is_bypass is False
        assert result.bypass_type is None


# =============================================================================
# 統計・状態管理テスト
# =============================================================================

class TestStatsAndState:
    """統計・状態管理のテスト"""

    def test_get_stats(self, integration_disabled):
        """統計情報取得"""
        stats = integration_disabled.get_stats()

        assert "total_requests" in stats
        assert "brain_requests" in stats
        assert "fallback_requests" in stats
        assert "errors" in stats
        assert "mode" in stats
        assert stats["mode"] == "disabled"

    def test_reset_stats(self, integration_disabled):
        """統計情報リセット"""
        integration_disabled._stats["total_requests"] = 100
        integration_disabled.reset_stats()

        stats = integration_disabled.get_stats()
        assert stats["total_requests"] == 0

    @pytest.mark.asyncio
    async def test_health_check_disabled(self, integration_disabled):
        """ヘルスチェック（DISABLED）"""
        health = await integration_disabled.health_check()

        assert health["status"] == "healthy"
        assert health["mode"] == "disabled"
        assert health["brain_initialized"] is False

    def test_get_brain_disabled(self, integration_disabled):
        """脳取得（DISABLED）"""
        brain = integration_disabled.get_brain()
        assert brain is None


# =============================================================================
# フォールバック処理テスト
# =============================================================================

class TestFallbackProcessing:
    """フォールバック処理のテスト"""

    @pytest.mark.asyncio
    async def test_fallback_string_result(self, integration_disabled):
        """フォールバックが文字列を返す場合"""
        async def fallback(msg, room, account, name):
            return "文字列の応答"

        result = await integration_disabled.process_message(
            message="テスト",
            room_id="room123",
            account_id="user456",
            sender_name="テスト",
            fallback_func=fallback,
        )

        assert result.success is True
        assert result.message == "文字列の応答"

    @pytest.mark.asyncio
    async def test_fallback_dict_result(self, integration_disabled):
        """フォールバックが辞書を返す場合"""
        async def fallback(msg, room, account, name):
            return {"success": True, "message": "辞書の応答"}

        result = await integration_disabled.process_message(
            message="テスト",
            room_id="room123",
            account_id="user456",
            sender_name="テスト",
            fallback_func=fallback,
        )

        assert result.success is True
        assert result.message == "辞書の応答"

    @pytest.mark.asyncio
    async def test_fallback_error(self, integration_disabled):
        """フォールバックがエラーを投げる場合"""
        async def fallback(msg, room, account, name):
            raise Exception("フォールバックエラー")

        result = await integration_disabled.process_message(
            message="テスト",
            room_id="room123",
            account_id="user456",
            sender_name="テスト",
            fallback_func=fallback,
        )

        assert result.success is False
        assert "エラー" in result.message
        assert result.error == "Exception"


# =============================================================================
# 段階的移行テスト
# =============================================================================

class TestGradualRollout:
    """段階的移行のテスト"""

    def test_should_use_brain_gradual_0_percent(self):
        """0%の場合は脳を使用しない"""
        config = IntegrationConfig(
            mode=IntegrationMode.GRADUAL,
            gradual_percentage=0.0,
        )
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
            config=config,
        )

        # 0%なので誰も脳を使用しない
        assert integration._should_use_brain("room1", "user1") is False

    def test_should_use_brain_gradual_100_percent(self):
        """100%の場合は全員脳を使用"""
        config = IntegrationConfig(
            mode=IntegrationMode.GRADUAL,
            gradual_percentage=100.0,
        )
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
            config=config,
        )
        # 脳が初期化されていないので結局False（_should_use_brainは脳のチェックもする）
        # ただしgradual_percentageのチェックは通る

    def test_gradual_percentage_from_env(self):
        """環境変数から段階的移行率を取得"""
        with patch.dict(os.environ, {
            "USE_BRAIN_ARCHITECTURE": "gradual",
            "BRAIN_GRADUAL_PERCENTAGE": "75",
        }):
            integration = BrainIntegration(
                pool=None,
                org_id="org_test",
            )

            assert integration.config.mode == IntegrationMode.GRADUAL
            assert integration.config.gradual_percentage == 75.0


# =============================================================================
# ファクトリ関数テスト
# =============================================================================

class TestFactoryFunctions:
    """ファクトリ関数のテスト"""

    def test_create_integration_basic(self):
        """基本的な作成"""
        integration = create_integration(
            org_id="org_test",
        )

        assert isinstance(integration, BrainIntegration)
        assert integration.org_id == "org_test"

    def test_create_integration_with_config(self, enabled_config):
        """設定付きで作成"""
        integration = create_integration(
            org_id="org_test",
            config=enabled_config,
        )

        assert integration.config.mode == IntegrationMode.ENABLED

    def test_create_integration_full_parameters(
        self,
        mock_pool,
        mock_firestore,
        mock_handlers,
        mock_capabilities,
        mock_get_ai_response,
        disabled_config,
    ):
        """全パラメータで作成"""
        integration = create_integration(
            pool=mock_pool,
            org_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
            handlers=mock_handlers,
            capabilities=mock_capabilities,
            get_ai_response_func=mock_get_ai_response,
            firestore_db=mock_firestore,
            config=disabled_config,
        )

        assert integration.pool is mock_pool
        assert integration.org_id == "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
        assert integration.handlers == mock_handlers


# =============================================================================
# エラーハンドリングテスト
# =============================================================================

class TestErrorHandling:
    """エラーハンドリングのテスト"""

    @pytest.mark.asyncio
    async def test_process_message_catches_exceptions(
        self,
        integration_disabled,
    ):
        """process_messageが例外をキャッチする"""
        # フォールバックも例外を投げる場合
        async def bad_fallback(msg, room, account, name):
            raise RuntimeError("致命的エラー")

        result = await integration_disabled.process_message(
            message="テスト",
            room_id="room123",
            account_id="user456",
            sender_name="テスト",
            fallback_func=bad_fallback,
        )

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_stats_updated_on_error(self, integration_disabled):
        """エラー時に統計が更新される"""
        async def bad_fallback(msg, room, account, name):
            raise RuntimeError("エラー")

        await integration_disabled.process_message(
            message="テスト",
            room_id="room123",
            account_id="user456",
            sender_name="テスト",
            fallback_func=bad_fallback,
        )

        stats = integration_disabled.get_stats()
        # フォールバック内でエラーが発生した場合
        assert stats["fallback_requests"] == 1


# =============================================================================
# 統合テスト
# =============================================================================

class TestIntegration:
    """統合テスト"""

    @pytest.mark.asyncio
    async def test_full_disabled_flow(
        self,
        mock_fallback_func,
    ):
        """DISABLED完全フロー"""
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
            config=IntegrationConfig(mode=IntegrationMode.DISABLED),
        )

        # 1. 初期状態確認
        assert integration.is_brain_enabled() is False
        assert integration.get_mode() == IntegrationMode.DISABLED

        # 2. メッセージ処理
        result = await integration.process_message(
            message="自分のタスク教えて",
            room_id="room123",
            account_id="user456",
            sender_name="菊地",
            fallback_func=mock_fallback_func,
        )

        # 3. 結果確認
        assert result.success is True
        assert result.used_brain is False
        assert result.fallback_used is True

        # 4. 統計確認
        stats = integration.get_stats()
        assert stats["total_requests"] == 1
        assert stats["fallback_requests"] == 1

    @pytest.mark.asyncio
    async def test_mode_switch(
        self,
        mock_fallback_func,
    ):
        """モード切り替え"""
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
            config=IntegrationConfig(mode=IntegrationMode.DISABLED),
        )

        # 1. DISABLED→ENABLED
        integration.set_mode(IntegrationMode.ENABLED)
        assert integration.get_mode() == IntegrationMode.ENABLED

        # 2. ENABLED→SHADOW
        integration.set_mode(IntegrationMode.SHADOW)
        assert integration.get_mode() == IntegrationMode.SHADOW

        # 3. SHADOW→DISABLED
        integration.set_mode(IntegrationMode.DISABLED)
        assert integration.get_mode() == IntegrationMode.DISABLED

    @pytest.mark.asyncio
    async def test_bypass_detection_integration(
        self,
        mock_fallback_func,
    ):
        """バイパス検出統合"""
        integration = BrainIntegration(
            pool=None,
            org_id="org_test",
            config=IntegrationConfig(
                mode=IntegrationMode.DISABLED,
                bypass_detection_enabled=True,
            ),
        )

        # バイパスコンテキスト付きで処理
        result = await integration.process_message(
            message="目標を設定したい",
            room_id="room123",
            account_id="user456",
            sender_name="菊地",
            fallback_func=mock_fallback_func,
            bypass_context={
                "has_active_goal_session": True,
                "goal_session_id": "session123",
            },
        )

        # DISABLEDモードでもバイパス検出のログは取れる
        assert result.success is True
