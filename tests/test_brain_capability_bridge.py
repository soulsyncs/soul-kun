# tests/test_brain_capability_bridge.py
"""
CapabilityBridge のテスト

脳と機能モジュール（capabilities）の橋渡し層のテスト。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from lib.brain.capability_bridge import (
    CapabilityBridge,
    create_capability_bridge,
    GENERATION_CAPABILITIES,
    DEFAULT_FEATURE_FLAGS,
)
from lib.brain.models import HandlerResult


# ============================================================
# フィクスチャ
# ============================================================

@pytest.fixture
def mock_pool():
    """モックDBプール"""
    return MagicMock()


@pytest.fixture
def bridge(mock_pool):
    """CapabilityBridgeインスタンス"""
    return create_capability_bridge(
        pool=mock_pool,
        org_id="org_test",
        feature_flags={
            "ENABLE_IMAGE_PROCESSING": True,
            "ENABLE_PDF_PROCESSING": True,
            "ENABLE_URL_PROCESSING": True,
            "ENABLE_DOCUMENT_GENERATION": True,
            "ENABLE_IMAGE_GENERATION": True,
        },
    )


@pytest.fixture
def disabled_bridge(mock_pool):
    """全機能無効のCapabilityBridge"""
    return create_capability_bridge(
        pool=mock_pool,
        org_id="org_test",
        feature_flags={
            "ENABLE_IMAGE_PROCESSING": False,
            "ENABLE_PDF_PROCESSING": False,
            "ENABLE_URL_PROCESSING": False,
            "ENABLE_DOCUMENT_GENERATION": False,
            "ENABLE_IMAGE_GENERATION": False,
        },
    )


# ============================================================
# 初期化テスト
# ============================================================

class TestCapabilityBridgeInit:
    """CapabilityBridge初期化のテスト"""

    def test_create_with_defaults(self, mock_pool):
        """デフォルト設定で作成できる"""
        bridge = create_capability_bridge(
            pool=mock_pool,
            org_id="org_test",
        )
        assert bridge is not None
        assert bridge.org_id == "org_test"

    def test_create_with_custom_flags(self, mock_pool):
        """カスタムフラグで作成できる"""
        bridge = create_capability_bridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={"ENABLE_VIDEO_GENERATION": True},
        )
        assert bridge.feature_flags.get("ENABLE_VIDEO_GENERATION") is True

    def test_default_flags_merged(self, mock_pool):
        """デフォルトフラグがマージされる"""
        bridge = create_capability_bridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={"CUSTOM_FLAG": True},
        )
        # デフォルトフラグも存在する
        assert "ENABLE_IMAGE_PROCESSING" in bridge.feature_flags
        # カスタムフラグも存在する
        assert bridge.feature_flags.get("CUSTOM_FLAG") is True


# ============================================================
# マルチモーダル前処理テスト
# ============================================================

class TestMultimodalPreprocessing:
    """マルチモーダル前処理のテスト"""

    @pytest.mark.asyncio
    async def test_no_attachments_returns_original(self, bridge):
        """添付ファイルがない場合は元のメッセージを返す"""
        message, context = await bridge.preprocess_message(
            message="こんにちは",
            attachments=[],
            room_id="123",
            user_id="456",
        )
        assert message == "こんにちは"
        assert context is None

    @pytest.mark.asyncio
    async def test_disabled_returns_original(self, disabled_bridge):
        """機能無効の場合は元のメッセージを返す"""
        message, context = await disabled_bridge.preprocess_message(
            message="この画像を見て",
            attachments=[{"data": b"fake_image", "filename": "test.png"}],
            room_id="123",
            user_id="456",
        )
        assert message == "この画像を見て"
        assert context is None

    def test_contains_urls_true(self, bridge):
        """URLを含むテキストを検出できる"""
        assert bridge._contains_urls("https://example.com を見て") is True

    def test_contains_urls_false(self, bridge):
        """URLを含まないテキストを検出できる"""
        assert bridge._contains_urls("こんにちは") is False

    def test_is_multimodal_enabled(self, bridge):
        """マルチモーダル有効判定"""
        assert bridge._is_multimodal_enabled() is True

    def test_is_multimodal_disabled(self, disabled_bridge):
        """マルチモーダル無効判定"""
        assert disabled_bridge._is_multimodal_enabled() is False


# ============================================================
# ハンドラー取得テスト
# ============================================================

class TestCapabilityHandlers:
    """生成機能ハンドラーのテスト"""

    def test_get_handlers_enabled(self, bridge):
        """有効な機能のハンドラーを取得できる"""
        handlers = bridge.get_capability_handlers()
        assert "generate_document" in handlers
        assert "generate_image" in handlers
        assert callable(handlers["generate_document"])
        assert callable(handlers["generate_image"])

    def test_get_handlers_disabled(self, disabled_bridge):
        """無効な機能のハンドラーは取得されない"""
        handlers = disabled_bridge.get_capability_handlers()
        assert "generate_document" not in handlers
        assert "generate_image" not in handlers

    def test_handler_aliases(self, bridge):
        """ハンドラーのエイリアスが登録される"""
        handlers = bridge.get_capability_handlers()
        # generate_document と create_document は同じハンドラー
        assert "create_document" in handlers
        assert handlers["generate_document"] == handlers["create_document"]


# ============================================================
# 文書生成ハンドラーテスト
# ============================================================

class TestDocumentGenerationHandler:
    """文書生成ハンドラーのテスト"""

    @pytest.mark.asyncio
    async def test_missing_topic(self, bridge):
        """トピックがない場合はエラー"""
        result = await bridge._handle_document_generation(
            room_id="123",
            account_id="456",
            sender_name="テスト",
            params={},
        )
        assert result.success is False
        assert "教えてほしい" in result.message

    @pytest.mark.asyncio
    async def test_import_error_handled(self, bridge):
        """インポートエラーが適切にハンドリングされる"""
        with patch.dict("sys.modules", {"lib.capabilities.generation": None}):
            result = await bridge._handle_document_generation(
                room_id="123",
                account_id="456",
                sender_name="テスト",
                params={"topic": "テストレポート"},
            )
            # ImportErrorでもクラッシュしない
            assert isinstance(result, HandlerResult)


# ============================================================
# 画像生成ハンドラーテスト
# ============================================================

class TestImageGenerationHandler:
    """画像生成ハンドラーのテスト"""

    @pytest.mark.asyncio
    async def test_missing_prompt(self, bridge):
        """プロンプトがない場合はエラー"""
        result = await bridge._handle_image_generation(
            room_id="123",
            account_id="456",
            sender_name="テスト",
            params={},
        )
        assert result.success is False
        assert "教えてほしい" in result.message


# ============================================================
# 動画生成ハンドラーテスト
# ============================================================

class TestVideoGenerationHandler:
    """動画生成ハンドラーのテスト"""

    @pytest.mark.asyncio
    async def test_missing_prompt(self, bridge):
        """プロンプトがない場合はエラー"""
        result = await bridge._handle_video_generation(
            room_id="123",
            account_id="456",
            sender_name="テスト",
            params={},
        )
        assert result.success is False
        assert "教えてほしい" in result.message


# ============================================================
# GENERATION_CAPABILITIES テスト
# ============================================================

class TestGenerationCapabilities:
    """GENERATION_CAPABILITIES定義のテスト"""

    def test_document_generation_defined(self):
        """文書生成が定義されている"""
        assert "generate_document" in GENERATION_CAPABILITIES
        cap = GENERATION_CAPABILITIES["generate_document"]
        assert cap["name"] == "generate_document"
        assert "keywords" in cap
        assert "parameters" in cap
        assert cap["requires_confirmation"] is True

    def test_image_generation_defined(self):
        """画像生成が定義されている"""
        assert "generate_image" in GENERATION_CAPABILITIES
        cap = GENERATION_CAPABILITIES["generate_image"]
        assert cap["name"] == "generate_image"
        assert "keywords" in cap

    def test_video_generation_defined(self):
        """動画生成が定義されている"""
        assert "generate_video" in GENERATION_CAPABILITIES

    def test_feedback_generation_defined(self):
        """フィードバック生成が定義されている"""
        assert "generate_feedback" in GENERATION_CAPABILITIES


# ============================================================
# DEFAULT_FEATURE_FLAGS テスト
# ============================================================

class TestDefaultFeatureFlags:
    """DEFAULT_FEATURE_FLAGS定義のテスト"""

    def test_multimodal_flags_exist(self):
        """マルチモーダルフラグが存在する"""
        assert "ENABLE_IMAGE_PROCESSING" in DEFAULT_FEATURE_FLAGS
        assert "ENABLE_PDF_PROCESSING" in DEFAULT_FEATURE_FLAGS
        assert "ENABLE_URL_PROCESSING" in DEFAULT_FEATURE_FLAGS

    def test_generation_flags_exist(self):
        """生成フラグが存在する"""
        assert "ENABLE_DOCUMENT_GENERATION" in DEFAULT_FEATURE_FLAGS
        assert "ENABLE_IMAGE_GENERATION" in DEFAULT_FEATURE_FLAGS
        assert "ENABLE_VIDEO_GENERATION" in DEFAULT_FEATURE_FLAGS

    def test_feedback_flag_exists(self):
        """フィードバックフラグが存在する"""
        assert "ENABLE_CEO_FEEDBACK" in DEFAULT_FEATURE_FLAGS

    def test_video_generation_disabled_by_default(self):
        """動画生成はデフォルト無効"""
        assert DEFAULT_FEATURE_FLAGS["ENABLE_VIDEO_GENERATION"] is False


# ============================================================
# ダウンロードヘルパーテスト
# ============================================================

class TestDownloadHelper:
    """ダウンロードヘルパーのテスト"""

    @pytest.mark.asyncio
    async def test_empty_attachments(self, bridge):
        """空の添付ファイルリスト"""
        result = await bridge._download_attachments([], None)
        assert result == []

    @pytest.mark.asyncio
    async def test_data_already_present(self, bridge):
        """dataが既にある場合はそのまま返す"""
        attachments = [{"data": b"test", "filename": "test.txt"}]
        result = await bridge._download_attachments(attachments, None)
        assert len(result) == 1
        assert result[0]["data"] == b"test"

    @pytest.mark.asyncio
    async def test_download_with_func(self, bridge):
        """ダウンロード関数が呼ばれる"""
        async def mock_download(file_id):
            return b"downloaded_content"

        attachments = [{"file_id": "123", "filename": "test.txt"}]
        result = await bridge._download_attachments(attachments, mock_download)
        assert len(result) == 1
        assert result[0]["data"] == b"downloaded_content"

    @pytest.mark.asyncio
    async def test_download_error_handled(self, bridge):
        """ダウンロードエラーが適切にハンドリングされる"""
        async def mock_download_error(file_id):
            raise Exception("Download failed")

        attachments = [{"file_id": "123", "filename": "test.txt"}]
        result = await bridge._download_attachments(attachments, mock_download_error)
        # エラーでもクラッシュせず、空リストが返る
        assert result == []


# ============================================================
# v10.39.0: 新規追加機能のテスト（G3/G4）
# ============================================================

class TestDeepResearchCapability:
    """ディープリサーチ機能のテスト"""

    def test_deep_research_defined(self):
        """ディープリサーチが定義されている"""
        assert "deep_research" in GENERATION_CAPABILITIES
        cap = GENERATION_CAPABILITIES["deep_research"]
        assert cap["name"] == "deep_research"
        assert "調査" in cap["keywords"]
        assert "query" in cap["parameters"]
        assert "depth" in cap["parameters"]

    def test_deep_research_flag_exists(self):
        """ディープリサーチフラグが存在する"""
        assert "ENABLE_DEEP_RESEARCH" in DEFAULT_FEATURE_FLAGS
        assert DEFAULT_FEATURE_FLAGS["ENABLE_DEEP_RESEARCH"] is True

    @pytest.mark.asyncio
    async def test_missing_query(self, mock_pool):
        """クエリがない場合はエラー"""
        bridge = create_capability_bridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={"ENABLE_DEEP_RESEARCH": True},
        )
        result = await bridge._handle_deep_research(
            room_id="123",
            account_id="456",
            sender_name="テスト",
            params={},
        )
        assert result.success is False
        assert "教えてほしい" in result.message


class TestGoogleSheetsCapability:
    """Google Sheets機能のテスト"""

    def test_read_spreadsheet_defined(self):
        """スプレッドシート読み込みが定義されている"""
        assert "read_spreadsheet" in GENERATION_CAPABILITIES
        cap = GENERATION_CAPABILITIES["read_spreadsheet"]
        assert "spreadsheet_id" in cap["parameters"]

    def test_write_spreadsheet_defined(self):
        """スプレッドシート書き込みが定義されている"""
        assert "write_spreadsheet" in GENERATION_CAPABILITIES
        cap = GENERATION_CAPABILITIES["write_spreadsheet"]
        assert "data" in cap["parameters"]
        assert cap["requires_confirmation"] is True

    def test_create_spreadsheet_defined(self):
        """スプレッドシート作成が定義されている"""
        assert "create_spreadsheet" in GENERATION_CAPABILITIES

    def test_google_sheets_flag_exists(self):
        """Google Sheetsフラグが存在する"""
        assert "ENABLE_GOOGLE_SHEETS" in DEFAULT_FEATURE_FLAGS
        assert DEFAULT_FEATURE_FLAGS["ENABLE_GOOGLE_SHEETS"] is True

    @pytest.mark.asyncio
    async def test_missing_spreadsheet_id(self, mock_pool):
        """スプレッドシートIDがない場合はエラー"""
        bridge = create_capability_bridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={"ENABLE_GOOGLE_SHEETS": True},
        )
        result = await bridge._handle_read_spreadsheet(
            room_id="123",
            account_id="456",
            sender_name="テスト",
            params={},
        )
        assert result.success is False
        assert "ID" in result.message


class TestGoogleSlidesCapability:
    """Google Slides機能のテスト"""

    def test_read_presentation_defined(self):
        """プレゼンテーション読み込みが定義されている"""
        assert "read_presentation" in GENERATION_CAPABILITIES
        cap = GENERATION_CAPABILITIES["read_presentation"]
        assert "presentation_id" in cap["parameters"]

    def test_create_presentation_defined(self):
        """プレゼンテーション作成が定義されている"""
        assert "create_presentation" in GENERATION_CAPABILITIES
        cap = GENERATION_CAPABILITIES["create_presentation"]
        assert "title" in cap["parameters"]

    def test_google_slides_flag_exists(self):
        """Google Slidesフラグが存在する"""
        assert "ENABLE_GOOGLE_SLIDES" in DEFAULT_FEATURE_FLAGS
        assert DEFAULT_FEATURE_FLAGS["ENABLE_GOOGLE_SLIDES"] is True

    @pytest.mark.asyncio
    async def test_missing_presentation_id(self, mock_pool):
        """プレゼンテーションIDがない場合はエラー"""
        bridge = create_capability_bridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={"ENABLE_GOOGLE_SLIDES": True},
        )
        result = await bridge._handle_read_presentation(
            room_id="123",
            account_id="456",
            sender_name="テスト",
            params={},
        )
        assert result.success is False
        assert "ID" in result.message


class TestNewHandlersRegistration:
    """新ハンドラーの登録テスト"""

    def test_research_handlers_registered(self, mock_pool):
        """リサーチハンドラーが登録される"""
        bridge = create_capability_bridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={"ENABLE_DEEP_RESEARCH": True},
        )
        handlers = bridge.get_capability_handlers()
        assert "deep_research" in handlers
        assert "research" in handlers
        assert "investigate" in handlers

    def test_sheets_handlers_registered(self, mock_pool):
        """Sheetsハンドラーが登録される"""
        bridge = create_capability_bridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={"ENABLE_GOOGLE_SHEETS": True},
        )
        handlers = bridge.get_capability_handlers()
        assert "read_spreadsheet" in handlers
        assert "write_spreadsheet" in handlers
        assert "create_spreadsheet" in handlers

    def test_slides_handlers_registered(self, mock_pool):
        """Slidesハンドラーが登録される"""
        bridge = create_capability_bridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={"ENABLE_GOOGLE_SLIDES": True},
        )
        handlers = bridge.get_capability_handlers()
        assert "read_presentation" in handlers
        assert "create_presentation" in handlers

    def test_handlers_not_registered_when_disabled(self, mock_pool):
        """無効化時はハンドラーが登録されない"""
        bridge = create_capability_bridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={
                "ENABLE_DEEP_RESEARCH": False,
                "ENABLE_GOOGLE_SHEETS": False,
                "ENABLE_GOOGLE_SLIDES": False,
            },
        )
        handlers = bridge.get_capability_handlers()
        assert "deep_research" not in handlers
        assert "read_spreadsheet" not in handlers
        assert "read_presentation" not in handlers
