# tests/test_capability_bridge.py
"""
CapabilityBridge (lib/brain/capability_bridge.py) のユニットテスト

テスト対象:
- CapabilityBridge の初期化
- Feature Flags による制御
- preprocess_message（マルチモーダル前処理）
- get_capability_handlers（ハンドラー登録）
- 各生成ハンドラー（ドキュメント/画像/動画/フィードバック/リサーチ/Sheets/Slides/Connection）
- create_capability_bridge ファクトリ関数
- UUID変換ヘルパー
- エラーハンドリング（ImportError / Exception）
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from uuid import UUID

from lib.brain.capability_bridge import (
    CapabilityBridge,
    create_capability_bridge,
    DEFAULT_FEATURE_FLAGS,
    GENERATION_CAPABILITIES,
    MAX_ATTACHMENTS_PER_MESSAGE,
    MAX_URLS_PER_MESSAGE,
)
from lib.brain.models import HandlerResult


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_pool():
    """データベース接続プールのモック"""
    pool = Mock()
    conn = MagicMock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=False)
    pool.connect.return_value = conn
    return pool


@pytest.fixture
def org_id():
    """テスト用組織ID"""
    return "org_test"


@pytest.fixture
def bridge(mock_pool, org_id):
    """デフォルト設定のCapabilityBridgeインスタンス"""
    return CapabilityBridge(pool=mock_pool, org_id=org_id)


@pytest.fixture
def all_disabled_bridge(mock_pool, org_id):
    """全機能無効のCapabilityBridge"""
    flags = {k: False for k in DEFAULT_FEATURE_FLAGS}
    return CapabilityBridge(pool=mock_pool, org_id=org_id, feature_flags=flags)


@pytest.fixture
def all_enabled_bridge(mock_pool, org_id):
    """全機能有効のCapabilityBridge"""
    flags = {k: True for k in DEFAULT_FEATURE_FLAGS}
    return CapabilityBridge(pool=mock_pool, org_id=org_id, feature_flags=flags)


@pytest.fixture
def handler_kwargs():
    """ハンドラー呼び出しに必要な共通引数"""
    return {
        "room_id": "123456",
        "account_id": "7890",
        "sender_name": "テストユーザー",
    }


# =============================================================================
# 初期化テスト
# =============================================================================


class TestInit:
    """CapabilityBridge 初期化のテスト"""

    def test_basic_initialization(self, mock_pool, org_id):
        """基本的な初期化が成功する"""
        bridge = CapabilityBridge(pool=mock_pool, org_id=org_id)
        assert bridge.pool is mock_pool
        assert bridge.org_id == org_id
        assert bridge.llm_caller is None

    def test_default_feature_flags(self, bridge):
        """デフォルトFeature Flagsが正しく設定される"""
        assert bridge.feature_flags["ENABLE_IMAGE_PROCESSING"] is True
        assert bridge.feature_flags["ENABLE_PDF_PROCESSING"] is True
        assert bridge.feature_flags["ENABLE_URL_PROCESSING"] is True
        assert bridge.feature_flags["ENABLE_AUDIO_PROCESSING"] is False
        assert bridge.feature_flags["ENABLE_VIDEO_PROCESSING"] is False
        assert bridge.feature_flags["ENABLE_VIDEO_GENERATION"] is False

    def test_custom_feature_flags_override(self, mock_pool, org_id):
        """カスタムFeature Flagsでデフォルトを上書きできる"""
        custom_flags = {
            "ENABLE_IMAGE_PROCESSING": False,
            "ENABLE_VIDEO_GENERATION": True,
        }
        bridge = CapabilityBridge(
            pool=mock_pool, org_id=org_id, feature_flags=custom_flags
        )
        assert bridge.feature_flags["ENABLE_IMAGE_PROCESSING"] is False
        assert bridge.feature_flags["ENABLE_VIDEO_GENERATION"] is True
        # 上書きしていないフラグはデフォルトのまま
        assert bridge.feature_flags["ENABLE_PDF_PROCESSING"] is True

    def test_llm_caller_is_stored(self, mock_pool, org_id):
        """llm_callerが保存される"""
        caller = Mock()
        bridge = CapabilityBridge(
            pool=mock_pool, org_id=org_id, llm_caller=caller
        )
        assert bridge.llm_caller is caller

    def test_llm_caller_is_none_by_default(self, bridge):
        """llm_callerのデフォルトはNone"""
        assert bridge.llm_caller is None


# =============================================================================
# UUID変換ヘルパー テスト（capabilities.generation モジュール関数）
# =============================================================================


class TestSafeParseUuid:
    """_safe_parse_uuid ヘルパー関数のテスト（capabilities/generation.py）"""

    def test_none_returns_none(self):
        """Noneを渡すとNoneが返る"""
        from lib.brain.capabilities.generation import _safe_parse_uuid
        assert _safe_parse_uuid(None) is None

    def test_empty_string_returns_none(self):
        """空文字列はNoneが返る"""
        from lib.brain.capabilities.generation import _safe_parse_uuid
        assert _safe_parse_uuid("") is None

    def test_valid_uuid_string(self):
        """有効なUUID文字列は正しく変換される"""
        from lib.brain.capabilities.generation import _safe_parse_uuid
        uuid_str = "12345678-1234-5678-1234-567812345678"
        result = _safe_parse_uuid(uuid_str)
        assert isinstance(result, UUID)
        assert str(result) == uuid_str

    def test_non_uuid_string_returns_uuid5(self):
        """UUID形式でない文字列はuuid5で変換される"""
        from lib.brain.capabilities.generation import _safe_parse_uuid
        result = _safe_parse_uuid("chatwork_12345")
        assert isinstance(result, UUID)
        # 決定論的：同じ入力なら同じ結果
        result2 = _safe_parse_uuid("chatwork_12345")
        assert result == result2

    def test_numeric_string_returns_uuid5(self):
        """数値文字列（ChatWorkアカウントIDなど）もUUID5で変換される"""
        from lib.brain.capabilities.generation import _safe_parse_uuid
        result = _safe_parse_uuid("10909425")
        assert isinstance(result, UUID)


class TestParseOrgUuid:
    """_parse_org_uuid ヘルパー関数のテスト（capabilities/generation.py）"""

    def test_valid_uuid_org_id(self):
        """UUID形式のorg_idはそのまま変換される"""
        from lib.brain.capabilities.generation import _parse_org_uuid
        uuid_str = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
        result = _parse_org_uuid(uuid_str)
        assert isinstance(result, UUID)
        assert str(result) == uuid_str

    def test_non_uuid_org_id(self):
        """UUID形式でないorg_idはuuid5で変換される"""
        from lib.brain.capabilities.generation import _parse_org_uuid
        result = _parse_org_uuid("non-uuid-org")
        assert isinstance(result, UUID)

    def test_uuid_object_org_id(self):
        """UUID型のorg_idがそのまま返される"""
        from lib.brain.capabilities.generation import _parse_org_uuid
        uuid_obj = UUID("5f98365f-e7c5-4f48-9918-7fe9aabae5df")
        result = _parse_org_uuid(uuid_obj)
        assert result == uuid_obj

    def test_deterministic_conversion(self):
        """同じorg_idは常に同じUUIDに変換される"""
        from lib.brain.capabilities.generation import _parse_org_uuid
        result1 = _parse_org_uuid("test-org-id")
        result2 = _parse_org_uuid("test-org-id")
        assert result1 == result2


# =============================================================================
# _is_multimodal_enabled テスト
# =============================================================================


class TestIsMultimodalEnabled:
    """マルチモーダル有効判定のテスト"""

    def test_enabled_when_image_processing_on(self, mock_pool, org_id):
        """IMAGE_PROCESSINGがONなら有効"""
        bridge = CapabilityBridge(
            pool=mock_pool,
            org_id=org_id,
            feature_flags={"ENABLE_IMAGE_PROCESSING": True},
        )
        assert bridge._is_multimodal_enabled() is True

    def test_enabled_when_pdf_processing_on(self, mock_pool, org_id):
        """PDF_PROCESSINGがONなら有効"""
        bridge = CapabilityBridge(
            pool=mock_pool,
            org_id=org_id,
            feature_flags={
                "ENABLE_IMAGE_PROCESSING": False,
                "ENABLE_PDF_PROCESSING": True,
                "ENABLE_URL_PROCESSING": False,
                "ENABLE_AUDIO_PROCESSING": False,
            },
        )
        assert bridge._is_multimodal_enabled() is True

    def test_disabled_when_all_off(self, mock_pool, org_id):
        """全てOFFなら無効"""
        bridge = CapabilityBridge(
            pool=mock_pool,
            org_id=org_id,
            feature_flags={
                "ENABLE_IMAGE_PROCESSING": False,
                "ENABLE_PDF_PROCESSING": False,
                "ENABLE_URL_PROCESSING": False,
                "ENABLE_AUDIO_PROCESSING": False,
            },
        )
        assert bridge._is_multimodal_enabled() is False


# =============================================================================
# _contains_urls テスト
# =============================================================================


class TestContainsUrls:
    """URL検出テスト"""

    def test_detects_http_url(self, bridge):
        """http:// URLを検出"""
        assert bridge._contains_urls("http://example.com にアクセス") is True

    def test_detects_https_url(self, bridge):
        """https:// URLを検出"""
        assert bridge._contains_urls("https://example.com/page?q=1") is True

    def test_no_url(self, bridge):
        """URLがない場合はFalse"""
        assert bridge._contains_urls("普通のテキストです") is False

    def test_empty_string(self, bridge):
        """空文字列はFalse"""
        assert bridge._contains_urls("") is False


# =============================================================================
# _download_attachments テスト
# =============================================================================


class TestDownloadAttachments:
    """添付ファイルダウンロードテスト"""

    @pytest.mark.asyncio
    async def test_empty_attachments(self, bridge):
        """空の添付ファイルリストは空リストを返す"""
        result = await bridge._download_attachments([], None)
        assert result == []

    @pytest.mark.asyncio
    async def test_data_attachments_pass_through(self, bridge):
        """dataキーがある添付ファイルはそのまま通す"""
        attachments = [
            {"data": b"image_bytes", "filename": "test.png"},
            {"data": b"pdf_bytes", "filename": "test.pdf"},
        ]
        result = await bridge._download_attachments(attachments, None)
        assert len(result) == 2
        assert result[0]["data"] == b"image_bytes"
        assert result[1]["filename"] == "test.pdf"

    @pytest.mark.asyncio
    async def test_file_id_download(self, bridge):
        """file_idの添付ファイルはdownload_funcで取得"""
        download_func = AsyncMock(return_value=b"downloaded_data")
        attachments = [
            {"file_id": "f123", "filename": "doc.pdf", "mime_type": "application/pdf"},
        ]
        result = await bridge._download_attachments(attachments, download_func)
        assert len(result) == 1
        assert result[0]["data"] == b"downloaded_data"
        assert result[0]["filename"] == "doc.pdf"
        assert result[0]["mime_type"] == "application/pdf"
        download_func.assert_awaited_once_with("f123")

    @pytest.mark.asyncio
    async def test_file_id_without_download_func(self, bridge):
        """download_funcがない場合、file_idの添付はスキップ"""
        attachments = [{"file_id": "f123", "filename": "doc.pdf"}]
        result = await bridge._download_attachments(attachments, None)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_download_error_skips_attachment(self, bridge):
        """ダウンロードエラー時はその添付をスキップ"""
        download_func = AsyncMock(side_effect=Exception("Download failed"))
        attachments = [
            {"file_id": "f123", "filename": "doc.pdf"},
            {"data": b"direct_data", "filename": "inline.png"},
        ]
        result = await bridge._download_attachments(attachments, download_func)
        # エラーの添付はスキップされ、直接dataの添付のみ含まれる
        assert len(result) == 1
        assert result[0]["filename"] == "inline.png"

    @pytest.mark.asyncio
    async def test_max_attachments_limit(self, bridge):
        """MAX_ATTACHMENTS_PER_MESSAGE を超える添付は切り捨て"""
        attachments = [
            {"data": b"data", "filename": f"file_{i}.png"}
            for i in range(MAX_ATTACHMENTS_PER_MESSAGE + 3)
        ]
        result = await bridge._download_attachments(attachments, None)
        assert len(result) == MAX_ATTACHMENTS_PER_MESSAGE

    @pytest.mark.asyncio
    async def test_mixed_attachments(self, bridge):
        """data形式とfile_id形式が混在"""
        download_func = AsyncMock(return_value=b"downloaded")
        attachments = [
            {"data": b"inline", "filename": "a.png"},
            {"file_id": "f1", "filename": "b.pdf"},
        ]
        result = await bridge._download_attachments(attachments, download_func)
        assert len(result) == 2
        assert result[0]["data"] == b"inline"
        assert result[1]["data"] == b"downloaded"


# =============================================================================
# preprocess_message テスト
# =============================================================================


class TestPreprocessMessage:
    """メッセージ前処理テスト"""

    @pytest.mark.asyncio
    async def test_early_return_when_multimodal_disabled(self, mock_pool, org_id):
        """マルチモーダル無効時は元のメッセージをそのまま返す"""
        bridge = CapabilityBridge(
            pool=mock_pool,
            org_id=org_id,
            feature_flags={
                "ENABLE_IMAGE_PROCESSING": False,
                "ENABLE_PDF_PROCESSING": False,
                "ENABLE_URL_PROCESSING": False,
                "ENABLE_AUDIO_PROCESSING": False,
            },
        )
        msg = "テストメッセージ"
        result_msg, context = await bridge.preprocess_message(
            message=msg, attachments=[], room_id="123", user_id="456"
        )
        assert result_msg == msg
        assert context is None

    @pytest.mark.asyncio
    async def test_early_return_no_attachments_no_urls(self, bridge):
        """添付ファイルなし＋URLなしの場合は早期リターン"""
        msg = "普通のメッセージ"
        result_msg, context = await bridge.preprocess_message(
            message=msg, attachments=[], room_id="123", user_id="456"
        )
        assert result_msg == msg
        assert context is None

    @pytest.mark.asyncio
    async def test_import_error_returns_original(self, bridge):
        """multimodal モジュールがインポートできない場合は元メッセージを返す"""
        with patch(
            "lib.brain.capability_bridge.CapabilityBridge._is_multimodal_enabled",
            return_value=True,
        ):
            with patch(
                "lib.brain.capability_bridge.CapabilityBridge._contains_urls",
                return_value=True,
            ):
                # Force ImportError by setting module to None in sys.modules
                with patch.dict(
                    "sys.modules",
                    {"lib.capabilities.multimodal.brain_integration": None},
                ):
                    msg = "https://example.com を見て"
                    result_msg, context = await bridge.preprocess_message(
                        message=msg, attachments=[], room_id="123", user_id="456"
                    )
                    assert result_msg == msg
                    assert context is None

    @pytest.mark.asyncio
    async def test_exception_returns_original(self, bridge):
        """処理中の例外時は元メッセージを返す"""
        with patch(
            "lib.brain.capability_bridge.CapabilityBridge._is_multimodal_enabled",
            return_value=True,
        ):
            msg = "テスト"
            attachments = [{"data": b"data", "filename": "test.png"}]

            # should_process_as_multimodal で例外を発生させる
            mock_module = MagicMock()
            mock_module.should_process_as_multimodal.side_effect = RuntimeError("boom")
            with patch.dict(
                "sys.modules",
                {"lib.capabilities.multimodal.brain_integration": mock_module},
            ):
                result_msg, context = await bridge.preprocess_message(
                    message=msg,
                    attachments=attachments,
                    room_id="123",
                    user_id="456",
                )
                assert result_msg == msg
                assert context is None

    @pytest.mark.asyncio
    async def test_successful_multimodal_processing(self, bridge):
        """マルチモーダル処理が成功するケース"""
        mock_enriched = MagicMock()
        mock_enriched.get_full_context.return_value = "拡張されたメッセージ"
        mock_context = MagicMock()
        mock_context.successful_count = 1

        mock_module = MagicMock()
        mock_module.should_process_as_multimodal.return_value = True
        mock_module.process_message_with_multimodal = AsyncMock(
            return_value=(mock_enriched, mock_context)
        )

        with patch(
            "lib.brain.capability_bridge.CapabilityBridge._is_multimodal_enabled",
            return_value=True,
        ):
            with patch.dict(
                "sys.modules",
                {"lib.capabilities.multimodal.brain_integration": mock_module},
            ):
                msg = "この画像を確認して"
                attachments = [{"data": b"image_bytes", "filename": "img.png"}]
                result_msg, context = await bridge.preprocess_message(
                    message=msg,
                    attachments=attachments,
                    room_id="123",
                    user_id="456",
                )
                assert result_msg == "拡張されたメッセージ"
                assert context is mock_context

    @pytest.mark.asyncio
    async def test_should_not_process_returns_original(self, bridge):
        """should_process_as_multimodalがFalseの場合は元メッセージ"""
        mock_module = MagicMock()
        mock_module.should_process_as_multimodal.return_value = False

        with patch(
            "lib.brain.capability_bridge.CapabilityBridge._is_multimodal_enabled",
            return_value=True,
        ):
            with patch.dict(
                "sys.modules",
                {"lib.capabilities.multimodal.brain_integration": mock_module},
            ):
                msg = "テスト"
                attachments = [{"data": b"data", "filename": "test.txt"}]
                result_msg, context = await bridge.preprocess_message(
                    message=msg,
                    attachments=attachments,
                    room_id="123",
                    user_id="456",
                )
                assert result_msg == msg
                assert context is None


# =============================================================================
# get_capability_handlers テスト
# =============================================================================


class TestGetCapabilityHandlers:
    """ハンドラー登録テスト"""

    def test_default_flags_registered_handlers(self, bridge):
        """デフォルトフラグで期待されるハンドラーが登録される"""
        handlers = bridge.get_capability_handlers()
        # Document generation (enabled by default)
        assert "generate_document" in handlers
        assert "generate_report" in handlers
        assert "create_document" in handlers
        # Image generation (enabled by default)
        assert "generate_image" in handlers
        assert "create_image" in handlers
        # CEO Feedback (enabled by default)
        assert "generate_feedback" in handlers
        assert "ceo_feedback" in handlers
        # Deep Research (enabled by default)
        assert "deep_research" in handlers
        assert "research" in handlers
        assert "investigate" in handlers
        # Google Sheets (enabled by default)
        assert "read_spreadsheet" in handlers
        assert "write_spreadsheet" in handlers
        assert "create_spreadsheet" in handlers
        # Google Slides (enabled by default)
        assert "read_presentation" in handlers
        assert "create_presentation" in handlers
        # Connection Query (always enabled)
        assert "connection_query" in handlers

    def test_video_handler_not_registered_by_default(self, bridge):
        """動画生成ハンドラーはデフォルトでは登録されない"""
        handlers = bridge.get_capability_handlers()
        assert "generate_video" not in handlers
        assert "create_video" not in handlers

    def test_all_disabled_only_connection_query(self, all_disabled_bridge):
        """全機能無効でもconnection_queryは登録される"""
        handlers = all_disabled_bridge.get_capability_handlers()
        assert "connection_query" in handlers
        # その他は登録されない
        assert "generate_document" not in handlers
        assert "generate_image" not in handlers
        assert "generate_feedback" not in handlers
        assert "deep_research" not in handlers

    def test_all_enabled_includes_video(self, all_enabled_bridge):
        """全機能有効なら動画生成も含まれる"""
        handlers = all_enabled_bridge.get_capability_handlers()
        assert "generate_video" in handlers
        assert "create_video" in handlers

    def test_handlers_are_callable(self, bridge):
        """全てのハンドラーがcallableである"""
        handlers = bridge.get_capability_handlers()
        for name, handler in handlers.items():
            assert callable(handler), f"Handler '{name}' is not callable"

    def test_selective_flag_control(self, mock_pool, org_id):
        """個別のフラグでハンドラーを制御できる"""
        bridge = CapabilityBridge(
            pool=mock_pool,
            org_id=org_id,
            feature_flags={
                "ENABLE_DOCUMENT_GENERATION": False,
                "ENABLE_IMAGE_GENERATION": True,
                "ENABLE_CEO_FEEDBACK": False,
                "ENABLE_DEEP_RESEARCH": False,
                "ENABLE_GOOGLE_SHEETS": False,
                "ENABLE_GOOGLE_SLIDES": False,
            },
        )
        handlers = bridge.get_capability_handlers()
        assert "generate_document" not in handlers
        assert "generate_image" in handlers
        assert "generate_feedback" not in handlers
        assert "deep_research" not in handlers
        assert "read_spreadsheet" not in handlers
        assert "read_presentation" not in handlers
        assert "connection_query" in handlers


# =============================================================================
# _handle_document_generation テスト
# =============================================================================


class TestHandleDocumentGeneration:
    """文書生成ハンドラーテスト"""

    @pytest.mark.asyncio
    async def test_empty_topic_returns_failure(self, bridge, handler_kwargs):
        """トピックが空の場合は失敗"""
        result = await bridge._handle_document_generation(
            **handler_kwargs, params={"topic": ""}
        )
        assert isinstance(result, HandlerResult)
        assert result.success is False
        assert "教えてほしい" in result.message

    @pytest.mark.asyncio
    async def test_import_error_returns_failure(self, bridge, handler_kwargs):
        """generation モジュール未インストール時は失敗"""
        with patch.dict("sys.modules", {
            "lib.capabilities.generation": None,
            "lib.capabilities.generation.models": None,
            "lib.capabilities.generation.constants": None,
        }):
            result = await bridge._handle_document_generation(
                **handler_kwargs, params={"topic": "月次レポート"}
            )
            assert isinstance(result, HandlerResult)
            assert result.success is False
            assert "利用できない" in result.message

    @pytest.mark.asyncio
    async def test_successful_generation(self, bridge, handler_kwargs):
        """文書生成が成功するケース"""
        mock_doc_result = MagicMock()
        mock_doc_result.document_url = "https://docs.google.com/document/d/abc123"
        mock_doc_result.document_id = "abc123"

        mock_gen_result = MagicMock()
        mock_gen_result.success = True
        mock_gen_result.document_result = mock_doc_result

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=mock_gen_result)

        mock_gen_module = MagicMock()
        mock_gen_module.DocumentGenerator.return_value = mock_generator

        mock_models = MagicMock()
        mock_constants = MagicMock()

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
            "lib.capabilities.generation.models": mock_models,
            "lib.capabilities.generation.constants": mock_constants,
        }):
            result = await bridge._handle_document_generation(
                **handler_kwargs,
                params={
                    "topic": "月次レポート",
                    "document_type": "report",
                    "output_format": "google_docs",
                },
            )
            assert result.success is True
            assert "作成した" in result.message
            assert result.data["document_url"] == "https://docs.google.com/document/d/abc123"

    @pytest.mark.asyncio
    async def test_generation_failure(self, bridge, handler_kwargs):
        """文書生成が失敗するケース"""
        mock_gen_result = MagicMock()
        mock_gen_result.success = False
        mock_gen_result.error_message = "API quota exceeded"

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=mock_gen_result)

        mock_gen_module = MagicMock()
        mock_gen_module.DocumentGenerator.return_value = mock_generator

        mock_models = MagicMock()
        mock_constants = MagicMock()

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
            "lib.capabilities.generation.models": mock_models,
            "lib.capabilities.generation.constants": mock_constants,
        }):
            result = await bridge._handle_document_generation(
                **handler_kwargs,
                params={"topic": "レポート"},
            )
            assert result.success is False
            assert "失敗" in result.message

    @pytest.mark.asyncio
    async def test_exception_returns_error(self, bridge, handler_kwargs):
        """予期しない例外は安全にエラー返却"""
        mock_gen_module = MagicMock()
        mock_gen_module.DocumentGenerator.side_effect = RuntimeError("unexpected")
        mock_models = MagicMock()
        mock_constants = MagicMock()

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
            "lib.capabilities.generation.models": mock_models,
            "lib.capabilities.generation.constants": mock_constants,
        }):
            result = await bridge._handle_document_generation(
                **handler_kwargs,
                params={"topic": "テスト"},
            )
            assert result.success is False
            assert "エラー" in result.message

    @pytest.mark.asyncio
    async def test_outline_appended_to_instruction(self, bridge, handler_kwargs):
        """アウトラインがある場合、instructionに追加される"""
        mock_gen_result = MagicMock()
        mock_gen_result.success = True
        mock_gen_result.document_result = MagicMock(
            document_url="https://example.com", document_id="id1"
        )

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=mock_gen_result)

        mock_gen_module = MagicMock()
        mock_gen_module.DocumentGenerator.return_value = mock_generator
        mock_models = MagicMock()
        mock_constants = MagicMock()

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
            "lib.capabilities.generation.models": mock_models,
            "lib.capabilities.generation.constants": mock_constants,
        }):
            result = await bridge._handle_document_generation(
                **handler_kwargs,
                params={
                    "topic": "提案書",
                    "outline": "1. 概要\n2. 課題\n3. 提案",
                },
            )
            assert result.success is True
            # DocumentRequestに渡されたinstructionにアウトラインが含まれる
            call_args = mock_models.DocumentRequest.call_args
            instruction = call_args.kwargs.get("instruction", "")
            assert "アウトライン" in instruction


# =============================================================================
# _handle_image_generation テスト
# =============================================================================


class TestHandleImageGeneration:
    """画像生成ハンドラーテスト"""

    @pytest.mark.asyncio
    async def test_empty_prompt_returns_failure(self, bridge, handler_kwargs):
        """プロンプトが空の場合は失敗"""
        result = await bridge._handle_image_generation(
            **handler_kwargs, params={"prompt": ""}
        )
        assert result.success is False
        assert "教えてほしい" in result.message

    @pytest.mark.asyncio
    async def test_import_error_returns_failure(self, bridge, handler_kwargs):
        """画像生成モジュール未インストール時"""
        with patch.dict("sys.modules", {
            "lib.capabilities.generation": None,
            "lib.capabilities.generation.models": None,
            "lib.capabilities.generation.constants": None,
        }):
            result = await bridge._handle_image_generation(
                **handler_kwargs, params={"prompt": "犬の絵"}
            )
            assert result.success is False
            assert "利用できない" in result.message

    @pytest.mark.asyncio
    async def test_successful_image_generation(self, bridge, handler_kwargs):
        """画像生成が成功するケース"""
        mock_img_result = MagicMock()
        mock_img_result.image_url = "https://example.com/image.png"

        mock_gen_result = MagicMock()
        mock_gen_result.success = True
        mock_gen_result.image_result = mock_img_result

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=mock_gen_result)

        mock_gen_module = MagicMock()
        mock_gen_module.ImageGenerator.return_value = mock_generator
        mock_models = MagicMock()
        mock_constants = MagicMock()

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
            "lib.capabilities.generation.models": mock_models,
            "lib.capabilities.generation.constants": mock_constants,
        }):
            result = await bridge._handle_image_generation(
                **handler_kwargs,
                params={"prompt": "犬の絵", "style": "vivid", "size": "1024x1024"},
            )
            assert result.success is True
            assert "作成した" in result.message
            assert result.data["image_url"] == "https://example.com/image.png"

    @pytest.mark.asyncio
    async def test_image_generation_failure(self, bridge, handler_kwargs):
        """画像生成が失敗するケース"""
        mock_gen_result = MagicMock()
        mock_gen_result.success = False
        mock_gen_result.error_message = "Content policy violation"

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=mock_gen_result)

        mock_gen_module = MagicMock()
        mock_gen_module.ImageGenerator.return_value = mock_generator
        mock_models = MagicMock()
        mock_constants = MagicMock()

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
            "lib.capabilities.generation.models": mock_models,
            "lib.capabilities.generation.constants": mock_constants,
        }):
            result = await bridge._handle_image_generation(
                **handler_kwargs,
                params={"prompt": "テスト画像"},
            )
            assert result.success is False
            assert "失敗" in result.message

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, bridge, handler_kwargs):
        """予期しない例外のハンドリング"""
        mock_gen_module = MagicMock()
        mock_gen_module.ImageGenerator.side_effect = RuntimeError("oops")
        mock_models = MagicMock()
        mock_constants = MagicMock()

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
            "lib.capabilities.generation.models": mock_models,
            "lib.capabilities.generation.constants": mock_constants,
        }):
            result = await bridge._handle_image_generation(
                **handler_kwargs,
                params={"prompt": "テスト"},
            )
            assert result.success is False
            assert "エラー" in result.message


# =============================================================================
# _handle_video_generation テスト
# =============================================================================


class TestHandleVideoGeneration:
    """動画生成ハンドラーテスト"""

    @pytest.mark.asyncio
    async def test_empty_prompt_returns_failure(self, bridge, handler_kwargs):
        """プロンプトが空の場合は失敗"""
        result = await bridge._handle_video_generation(
            **handler_kwargs, params={"prompt": ""}
        )
        assert result.success is False
        assert "教えてほしい" in result.message

    @pytest.mark.asyncio
    async def test_import_error_returns_failure(self, bridge, handler_kwargs):
        """動画生成モジュール未インストール時"""
        with patch.dict("sys.modules", {
            "lib.capabilities.generation": None,
            "lib.capabilities.generation.models": None,
            "lib.capabilities.generation.constants": None,
        }):
            result = await bridge._handle_video_generation(
                **handler_kwargs, params={"prompt": "猫が走る動画"}
            )
            assert result.success is False
            assert "利用できない" in result.message

    @pytest.mark.asyncio
    async def test_successful_video_generation(self, bridge, handler_kwargs):
        """動画生成が成功するケース"""
        mock_vid_result = MagicMock()
        mock_vid_result.video_url = "https://example.com/video.mp4"

        mock_gen_result = MagicMock()
        mock_gen_result.success = True
        mock_gen_result.video_result = mock_vid_result

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=mock_gen_result)

        mock_gen_module = MagicMock()
        mock_gen_module.VideoGenerator.return_value = mock_generator
        mock_models = MagicMock()
        mock_constants = MagicMock()

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
            "lib.capabilities.generation.models": mock_models,
            "lib.capabilities.generation.constants": mock_constants,
        }):
            result = await bridge._handle_video_generation(
                **handler_kwargs,
                params={"prompt": "猫が走る動画", "duration": 5},
            )
            assert result.success is True
            assert "作成した" in result.message
            assert result.data["video_url"] == "https://example.com/video.mp4"

    @pytest.mark.asyncio
    async def test_video_generation_failure(self, bridge, handler_kwargs):
        """動画生成が失敗するケース"""
        mock_gen_result = MagicMock()
        mock_gen_result.success = False
        mock_gen_result.error_message = "GPU unavailable"

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=mock_gen_result)

        mock_gen_module = MagicMock()
        mock_gen_module.VideoGenerator.return_value = mock_generator
        mock_models = MagicMock()
        mock_constants = MagicMock()

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
            "lib.capabilities.generation.models": mock_models,
            "lib.capabilities.generation.constants": mock_constants,
        }):
            result = await bridge._handle_video_generation(
                **handler_kwargs,
                params={"prompt": "テスト"},
            )
            assert result.success is False
            assert "失敗" in result.message


# =============================================================================
# _handle_feedback_generation テスト
# =============================================================================


class TestHandleFeedbackGeneration:
    """CEOフィードバック生成ハンドラーテスト"""

    @pytest.mark.asyncio
    async def test_import_error_returns_failure(self, bridge, handler_kwargs):
        """feedback モジュール未インストール時"""
        with patch.dict("sys.modules", {
            "lib.capabilities.feedback": None,
            "lib.capabilities.feedback.ceo_feedback_engine": None,
        }):
            result = await bridge._handle_feedback_generation(
                **handler_kwargs, params={}
            )
            assert result.success is False
            assert "利用できない" in result.message

    @pytest.mark.asyncio
    async def test_successful_feedback(self, bridge, handler_kwargs):
        """フィードバック生成が成功するケース"""
        mock_feedback = MagicMock()
        mock_feedback.summary = "良い仕事をしています"
        mock_feedback.feedback_id = "fb_001"

        mock_engine = MagicMock()
        mock_engine.analyze_on_demand = AsyncMock(
            return_value=(mock_feedback, None)
        )

        mock_settings_class = MagicMock()
        mock_engine_class = MagicMock(return_value=mock_engine)

        mock_feedback_module = MagicMock()
        mock_feedback_module.CEOFeedbackEngine = mock_engine_class

        mock_ceo_module = MagicMock()
        mock_ceo_module.CEOFeedbackSettings = mock_settings_class

        # pool.connect() をコンテキストマネージャとして動かす
        mock_conn = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        bridge.pool.connect.return_value = mock_conn

        with patch.dict("sys.modules", {
            "lib.capabilities.feedback": mock_feedback_module,
            "lib.capabilities.feedback.ceo_feedback_engine": mock_ceo_module,
        }):
            result = await bridge._handle_feedback_generation(
                **handler_kwargs,
                params={"period": "week"},
            )
            assert result.success is True
            assert "良い仕事をしています" in result.message

    @pytest.mark.asyncio
    async def test_feedback_with_none_account_id(self, bridge):
        """account_idとtarget_user_idが両方None/空の場合"""
        # _safe_parse_uuid は空文字でNoneを返すがaccount_idが空でないと通常起こらない
        # account_idが空でない場合のテスト
        result = await bridge._handle_feedback_generation(
            room_id="123",
            account_id="",
            sender_name="テスト",
            params={"target_user_id": ""},
        )
        # ImportError か None チェックに引っかかるはず
        assert result.success is False

    @pytest.mark.asyncio
    async def test_feedback_exception(self, bridge, handler_kwargs):
        """フィードバック生成中の例外"""
        mock_feedback_module = MagicMock()
        mock_feedback_module.CEOFeedbackEngine.side_effect = RuntimeError("DB down")

        mock_ceo_module = MagicMock()

        mock_conn = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        bridge.pool.connect.return_value = mock_conn

        with patch.dict("sys.modules", {
            "lib.capabilities.feedback": mock_feedback_module,
            "lib.capabilities.feedback.ceo_feedback_engine": mock_ceo_module,
        }):
            result = await bridge._handle_feedback_generation(
                **handler_kwargs,
                params={},
            )
            assert result.success is False
            assert "エラー" in result.message


# =============================================================================
# _handle_deep_research テスト
# =============================================================================


class TestHandleDeepResearch:
    """ディープリサーチハンドラーテスト"""

    @pytest.mark.asyncio
    async def test_empty_query_returns_failure(self, bridge, handler_kwargs):
        """クエリが空の場合は失敗"""
        result = await bridge._handle_deep_research(
            **handler_kwargs, params={"query": ""}
        )
        assert result.success is False
        assert "教えてほしい" in result.message

    @pytest.mark.asyncio
    async def test_import_error_returns_failure(self, bridge, handler_kwargs):
        """リサーチモジュール未インストール時"""
        with patch.dict("sys.modules", {
            "lib.capabilities.generation": None,
        }):
            result = await bridge._handle_deep_research(
                **handler_kwargs, params={"query": "AI市場調査"}
            )
            assert result.success is False
            assert "利用できない" in result.message

    @pytest.mark.asyncio
    async def test_successful_research(self, bridge, handler_kwargs):
        """リサーチが成功するケース"""
        mock_research_result = MagicMock()
        mock_research_result.executive_summary = "AI市場は急成長中"
        mock_research_result.key_findings = ["発見1", "発見2", "発見3"]
        mock_research_result.document_url = "https://docs.google.com/document/d/xyz"
        mock_research_result.sources_count = 15
        mock_research_result.actual_cost_jpy = 50.0

        mock_gen_result = MagicMock()
        mock_gen_result.success = True
        mock_gen_result.research_result = mock_research_result

        mock_engine = MagicMock()
        mock_engine.generate = AsyncMock(return_value=mock_gen_result)

        mock_gen_module = MagicMock()
        mock_gen_module.ResearchEngine.return_value = mock_engine

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_deep_research(
                **handler_kwargs,
                params={
                    "query": "AI市場調査",
                    "depth": "deep",
                    "research_type": "market",
                },
            )
            assert result.success is True
            assert "完了" in result.message
            assert "AI市場は急成長中" in result.message
            assert result.data["document_url"] == "https://docs.google.com/document/d/xyz"
            assert result.data["sources_count"] == 15
            assert result.data["cost_jpy"] == 50.0

    @pytest.mark.asyncio
    async def test_research_failure(self, bridge, handler_kwargs):
        """リサーチが失敗するケース"""
        mock_gen_result = MagicMock()
        mock_gen_result.success = False
        mock_gen_result.research_result = None

        mock_engine = MagicMock()
        mock_engine.generate = AsyncMock(return_value=mock_gen_result)

        mock_gen_module = MagicMock()
        mock_gen_module.ResearchEngine.return_value = mock_engine

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_deep_research(
                **handler_kwargs,
                params={"query": "テスト調査"},
            )
            assert result.success is False
            assert "失敗" in result.message

    @pytest.mark.asyncio
    async def test_research_exception(self, bridge, handler_kwargs):
        """リサーチ中の例外"""
        mock_gen_module = MagicMock()
        mock_gen_module.ResearchEngine.side_effect = RuntimeError("API error")

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_deep_research(
                **handler_kwargs,
                params={"query": "テスト"},
            )
            assert result.success is False
            assert "エラー" in result.message


# =============================================================================
# _handle_read_spreadsheet テスト
# =============================================================================


class TestHandleReadSpreadsheet:
    """スプレッドシート読み込みハンドラーテスト"""

    @pytest.mark.asyncio
    async def test_empty_spreadsheet_id_returns_failure(self, bridge, handler_kwargs):
        """スプレッドシートIDが空の場合は失敗"""
        result = await bridge._handle_read_spreadsheet(
            **handler_kwargs, params={"spreadsheet_id": ""}
        )
        assert result.success is False
        assert "ID" in result.message

    @pytest.mark.asyncio
    async def test_import_error_returns_failure(self, bridge, handler_kwargs):
        """SheetsモジュールのImportError"""
        with patch.dict("sys.modules", {
            "lib.capabilities.generation": None,
        }):
            result = await bridge._handle_read_spreadsheet(
                **handler_kwargs,
                params={"spreadsheet_id": "abc123", "range": "Sheet1!A1:D10"},
            )
            assert result.success is False
            assert "利用できない" in result.message

    @pytest.mark.asyncio
    async def test_successful_read(self, bridge, handler_kwargs):
        """スプレッドシート読み込み成功"""
        mock_client = MagicMock()
        mock_client.read_sheet = AsyncMock(
            return_value=[["A", "B"], ["1", "2"]]
        )
        mock_client.to_markdown_table.return_value = "| A | B |\n|---|---|\n| 1 | 2 |"

        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSheetsClient.return_value = mock_client

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_read_spreadsheet(
                **handler_kwargs,
                params={"spreadsheet_id": "abc123", "range": "Sheet1!A1:D10"},
            )
            assert result.success is True
            assert result.data["rows"] == 2

    @pytest.mark.asyncio
    async def test_empty_data_read(self, bridge, handler_kwargs):
        """スプレッドシートが空の場合"""
        mock_client = MagicMock()
        mock_client.read_sheet = AsyncMock(return_value=[])

        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSheetsClient.return_value = mock_client

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_read_spreadsheet(
                **handler_kwargs,
                params={"spreadsheet_id": "abc123"},
            )
            assert result.success is True
            assert result.data["rows"] == 0

    @pytest.mark.asyncio
    async def test_read_exception(self, bridge, handler_kwargs):
        """読み込み中の例外"""
        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSheetsClient.side_effect = RuntimeError("API error")

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_read_spreadsheet(
                **handler_kwargs,
                params={"spreadsheet_id": "abc123"},
            )
            assert result.success is False
            assert "失敗" in result.message


# =============================================================================
# _handle_write_spreadsheet テスト
# =============================================================================


class TestHandleWriteSpreadsheet:
    """スプレッドシート書き込みハンドラーテスト"""

    @pytest.mark.asyncio
    async def test_empty_spreadsheet_id(self, bridge, handler_kwargs):
        """スプレッドシートIDが空の場合は失敗"""
        result = await bridge._handle_write_spreadsheet(
            **handler_kwargs,
            params={"spreadsheet_id": "", "data": [["a"]]},
        )
        assert result.success is False
        assert "ID" in result.message

    @pytest.mark.asyncio
    async def test_empty_data(self, bridge, handler_kwargs):
        """データが空の場合は失敗"""
        result = await bridge._handle_write_spreadsheet(
            **handler_kwargs,
            params={"spreadsheet_id": "abc123", "data": []},
        )
        assert result.success is False
        assert "データ" in result.message

    @pytest.mark.asyncio
    async def test_import_error(self, bridge, handler_kwargs):
        """SheetsモジュールのImportError"""
        with patch.dict("sys.modules", {
            "lib.capabilities.generation": None,
        }):
            result = await bridge._handle_write_spreadsheet(
                **handler_kwargs,
                params={"spreadsheet_id": "abc", "data": [["x"]]},
            )
            assert result.success is False
            assert "利用できない" in result.message

    @pytest.mark.asyncio
    async def test_successful_write(self, bridge, handler_kwargs):
        """スプレッドシート書き込み成功"""
        mock_client = MagicMock()
        mock_client.write_sheet = AsyncMock(
            return_value={"updatedCells": 6}
        )

        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSheetsClient.return_value = mock_client

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_write_spreadsheet(
                **handler_kwargs,
                params={
                    "spreadsheet_id": "abc123",
                    "range": "Sheet1!A1",
                    "data": [["a", "b"], ["c", "d"]],
                },
            )
            assert result.success is True
            assert "6" in result.message

    @pytest.mark.asyncio
    async def test_write_exception(self, bridge, handler_kwargs):
        """書き込み中の例外"""
        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSheetsClient.side_effect = RuntimeError("quota")

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_write_spreadsheet(
                **handler_kwargs,
                params={"spreadsheet_id": "x", "data": [["y"]]},
            )
            assert result.success is False
            assert "失敗" in result.message


# =============================================================================
# _handle_create_spreadsheet テスト
# =============================================================================


class TestHandleCreateSpreadsheet:
    """スプレッドシート作成ハンドラーテスト"""

    @pytest.mark.asyncio
    async def test_import_error(self, bridge, handler_kwargs):
        """SheetsモジュールのImportError"""
        with patch.dict("sys.modules", {
            "lib.capabilities.generation": None,
        }):
            result = await bridge._handle_create_spreadsheet(
                **handler_kwargs, params={}
            )
            assert result.success is False
            assert "利用できない" in result.message

    @pytest.mark.asyncio
    async def test_successful_create(self, bridge, handler_kwargs):
        """スプレッドシート作成成功"""
        mock_client = MagicMock()
        mock_client.create_spreadsheet = AsyncMock(
            return_value={"spreadsheet_id": "new_sheet_id"}
        )

        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSheetsClient.return_value = mock_client

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_create_spreadsheet(
                **handler_kwargs,
                params={"title": "売上データ", "sheets": ["月次", "年次"]},
            )
            assert result.success is True
            assert "作成した" in result.message
            assert result.data["spreadsheet_id"] == "new_sheet_id"
            assert "docs.google.com/spreadsheets" in result.data["url"]

    @pytest.mark.asyncio
    async def test_create_exception(self, bridge, handler_kwargs):
        """作成中の例外"""
        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSheetsClient.side_effect = RuntimeError("fail")

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_create_spreadsheet(
                **handler_kwargs, params={}
            )
            assert result.success is False
            assert "失敗" in result.message


# =============================================================================
# _handle_read_presentation テスト
# =============================================================================


class TestHandleReadPresentation:
    """プレゼンテーション読み込みハンドラーテスト"""

    @pytest.mark.asyncio
    async def test_empty_presentation_id(self, bridge, handler_kwargs):
        """プレゼンテーションIDが空の場合は失敗"""
        result = await bridge._handle_read_presentation(
            **handler_kwargs, params={"presentation_id": ""}
        )
        assert result.success is False
        assert "ID" in result.message

    @pytest.mark.asyncio
    async def test_import_error(self, bridge, handler_kwargs):
        """SlidesモジュールのImportError"""
        with patch.dict("sys.modules", {
            "lib.capabilities.generation": None,
        }):
            result = await bridge._handle_read_presentation(
                **handler_kwargs, params={"presentation_id": "pres123"}
            )
            assert result.success is False
            assert "利用できない" in result.message

    @pytest.mark.asyncio
    async def test_successful_read(self, bridge, handler_kwargs):
        """プレゼンテーション読み込み成功"""
        mock_client = MagicMock()
        mock_client.get_presentation_info = AsyncMock(
            return_value={"title": "営業企画", "slides_count": 10}
        )
        mock_client.get_presentation_content = AsyncMock(
            return_value=[{"slide_number": 1, "text": "内容"}]
        )
        mock_client.to_markdown.return_value = "# スライド1\n内容"

        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSlidesClient.return_value = mock_client

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_read_presentation(
                **handler_kwargs,
                params={"presentation_id": "pres123"},
            )
            assert result.success is True
            assert "営業企画" in result.message
            assert result.data["slides_count"] == 10

    @pytest.mark.asyncio
    async def test_read_presentation_exception(self, bridge, handler_kwargs):
        """読み込み中の例外"""
        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSlidesClient.side_effect = RuntimeError("auth error")

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_read_presentation(
                **handler_kwargs,
                params={"presentation_id": "pres123"},
            )
            assert result.success is False
            assert "失敗" in result.message


# =============================================================================
# _handle_create_presentation テスト
# =============================================================================


class TestHandleCreatePresentation:
    """プレゼンテーション作成ハンドラーテスト"""

    @pytest.mark.asyncio
    async def test_import_error(self, bridge, handler_kwargs):
        """SlidesモジュールのImportError"""
        with patch.dict("sys.modules", {
            "lib.capabilities.generation": None,
        }):
            result = await bridge._handle_create_presentation(
                **handler_kwargs, params={}
            )
            assert result.success is False
            assert "利用できない" in result.message

    @pytest.mark.asyncio
    async def test_successful_create_empty_slides(self, bridge, handler_kwargs):
        """スライドなしでプレゼンテーション作成成功"""
        mock_client = MagicMock()
        mock_client.create_presentation = AsyncMock(
            return_value={"presentationId": "new_pres_id"}
        )

        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSlidesClient.return_value = mock_client

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_create_presentation(
                **handler_kwargs,
                params={"title": "テスト発表"},
            )
            assert result.success is True
            assert "作成した" in result.message
            assert result.data["presentation_id"] == "new_pres_id"
            assert "docs.google.com/presentation" in result.data["url"]

    @pytest.mark.asyncio
    async def test_successful_create_with_slides(self, bridge, handler_kwargs):
        """スライド付きでプレゼンテーション作成成功"""
        mock_client = MagicMock()
        mock_client.create_presentation = AsyncMock(
            return_value={"presentationId": "new_pres_id"}
        )
        mock_client.add_slide = AsyncMock()

        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSlidesClient.return_value = mock_client

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_create_presentation(
                **handler_kwargs,
                params={
                    "title": "テスト発表",
                    "slides": [
                        {"title": "スライド1", "body": "内容1"},
                        {"title": "スライド2", "body": "内容2"},
                    ],
                },
            )
            assert result.success is True
            assert mock_client.add_slide.await_count == 2

    @pytest.mark.asyncio
    async def test_empty_slide_skipped(self, bridge, handler_kwargs):
        """title/bodyが両方空のスライドはスキップ"""
        mock_client = MagicMock()
        mock_client.create_presentation = AsyncMock(
            return_value={"presentationId": "pid"}
        )
        mock_client.add_slide = AsyncMock()

        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSlidesClient.return_value = mock_client

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_create_presentation(
                **handler_kwargs,
                params={
                    "title": "テスト",
                    "slides": [
                        {"title": "", "body": ""},
                        {"title": "有効なスライド", "body": "内容"},
                    ],
                },
            )
            assert result.success is True
            # 空のスライドはスキップされ、1回だけadd_slideが呼ばれる
            assert mock_client.add_slide.await_count == 1

    @pytest.mark.asyncio
    async def test_create_presentation_exception(self, bridge, handler_kwargs):
        """作成中の例外"""
        mock_gen_module = MagicMock()
        mock_gen_module.GoogleSlidesClient.side_effect = RuntimeError("error")

        with patch.dict("sys.modules", {
            "lib.capabilities.generation": mock_gen_module,
        }):
            result = await bridge._handle_create_presentation(
                **handler_kwargs, params={}
            )
            assert result.success is False
            assert "失敗" in result.message


# =============================================================================
# _handle_connection_query テスト
# =============================================================================


class TestHandleConnectionQuery:
    """接続クエリハンドラーテスト"""

    @pytest.mark.asyncio
    async def test_import_error(self, bridge, handler_kwargs):
        """connection モジュール未インストール時"""
        with patch.dict("sys.modules", {
            "lib.connection_service": None,
            "lib.connection_logger": None,
            "lib.chatwork": None,
        }):
            result = await bridge._handle_connection_query(
                **handler_kwargs, params={}
            )
            assert result.success is False
            assert "利用できない" in result.message

    @pytest.mark.asyncio
    async def test_successful_query_allowed(self, bridge, handler_kwargs):
        """接続クエリが成功(許可)するケース"""
        mock_query_result = MagicMock()
        mock_query_result.allowed = True
        mock_query_result.total_count = 5
        mock_query_result.truncated = False
        mock_query_result.message = "接続先一覧ウル"

        mock_service = MagicMock()
        mock_service.query_connections.return_value = mock_query_result

        mock_conn_logger = MagicMock()

        mock_conn_service_module = MagicMock()
        mock_conn_service_module.ConnectionService.return_value = mock_service

        mock_conn_logger_module = MagicMock()
        mock_conn_logger_module.get_connection_logger.return_value = mock_conn_logger

        mock_chatwork_module = MagicMock()

        with patch.dict("sys.modules", {
            "lib.connection_service": mock_conn_service_module,
            "lib.connection_logger": mock_conn_logger_module,
            "lib.chatwork": mock_chatwork_module,
        }):
            result = await bridge._handle_connection_query(
                **handler_kwargs, params={}
            )
            assert result.success is True
            assert result.data["allowed"] is True
            assert result.data["total_count"] == 5
            # ログが呼ばれた
            mock_conn_logger.log_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_not_allowed(self, bridge, handler_kwargs):
        """接続クエリが非許可の場合"""
        mock_query_result = MagicMock()
        mock_query_result.allowed = False
        mock_query_result.total_count = 0
        mock_query_result.truncated = False
        mock_query_result.message = "権限がありません"

        mock_service = MagicMock()
        mock_service.query_connections.return_value = mock_query_result

        mock_conn_logger = MagicMock()

        mock_conn_service_module = MagicMock()
        mock_conn_service_module.ConnectionService.return_value = mock_service

        mock_conn_logger_module = MagicMock()
        mock_conn_logger_module.get_connection_logger.return_value = mock_conn_logger

        mock_chatwork_module = MagicMock()

        with patch.dict("sys.modules", {
            "lib.connection_service": mock_conn_service_module,
            "lib.connection_logger": mock_conn_logger_module,
            "lib.chatwork": mock_chatwork_module,
        }):
            result = await bridge._handle_connection_query(
                **handler_kwargs, params={}
            )
            assert result.success is True
            # 非許可時はdataが空
            assert result.data == {}

    @pytest.mark.asyncio
    async def test_connection_query_exception(self, bridge, handler_kwargs):
        """接続クエリ中の例外"""
        mock_conn_service_module = MagicMock()
        mock_conn_service_module.ConnectionService.side_effect = RuntimeError("error")

        mock_conn_logger_module = MagicMock()
        mock_chatwork_module = MagicMock()

        with patch.dict("sys.modules", {
            "lib.connection_service": mock_conn_service_module,
            "lib.connection_logger": mock_conn_logger_module,
            "lib.chatwork": mock_chatwork_module,
        }):
            result = await bridge._handle_connection_query(
                **handler_kwargs, params={}
            )
            assert result.success is False
            assert "失敗" in result.message


# =============================================================================
# create_capability_bridge ファクトリ関数テスト
# =============================================================================


class TestCreateCapabilityBridge:
    """ファクトリ関数テスト"""

    def test_creates_bridge_with_defaults(self, mock_pool, org_id):
        """デフォルト引数でCapabilityBridgeを作成"""
        bridge = create_capability_bridge(pool=mock_pool, org_id=org_id)
        assert isinstance(bridge, CapabilityBridge)
        assert bridge.pool is mock_pool
        assert bridge.org_id == org_id
        assert bridge.llm_caller is None

    def test_creates_bridge_with_custom_flags(self, mock_pool, org_id):
        """カスタムフラグ付きで作成"""
        flags = {"ENABLE_VIDEO_GENERATION": True}
        bridge = create_capability_bridge(
            pool=mock_pool, org_id=org_id, feature_flags=flags
        )
        assert bridge.feature_flags["ENABLE_VIDEO_GENERATION"] is True

    def test_creates_bridge_with_llm_caller(self, mock_pool, org_id):
        """llm_caller付きで作成"""
        caller = Mock()
        bridge = create_capability_bridge(
            pool=mock_pool, org_id=org_id, llm_caller=caller
        )
        assert bridge.llm_caller is caller


# =============================================================================
# GENERATION_CAPABILITIES / DEFAULT_FEATURE_FLAGS 定数テスト
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_generation_capabilities_has_expected_keys(self):
        """GENERATION_CAPABILITIESが必要なキーを含む"""
        expected = [
            "generate_document",
            "generate_image",
            "generate_video",
            "generate_feedback",
            "deep_research",
            "read_spreadsheet",
            "write_spreadsheet",
            "create_spreadsheet",
            "read_presentation",
            "create_presentation",
        ]
        for key in expected:
            assert key in GENERATION_CAPABILITIES, f"Missing key: {key}"

    def test_each_capability_has_required_fields(self):
        """各capabilityが必須フィールドを持つ"""
        for name, cap in GENERATION_CAPABILITIES.items():
            assert "name" in cap, f"{name} missing 'name'"
            assert "description" in cap, f"{name} missing 'description'"
            assert "keywords" in cap, f"{name} missing 'keywords'"
            assert "parameters" in cap, f"{name} missing 'parameters'"
            assert "requires_confirmation" in cap, f"{name} missing 'requires_confirmation'"

    def test_default_feature_flags_keys(self):
        """DEFAULT_FEATURE_FLAGSが必要なキーを含む"""
        expected_keys = [
            "ENABLE_IMAGE_PROCESSING",
            "ENABLE_PDF_PROCESSING",
            "ENABLE_URL_PROCESSING",
            "ENABLE_AUDIO_PROCESSING",
            "ENABLE_VIDEO_PROCESSING",
            "ENABLE_DOCUMENT_GENERATION",
            "ENABLE_IMAGE_GENERATION",
            "ENABLE_VIDEO_GENERATION",
            "ENABLE_DEEP_RESEARCH",
            "ENABLE_GOOGLE_SHEETS",
            "ENABLE_GOOGLE_SLIDES",
            "ENABLE_CEO_FEEDBACK",
        ]
        for key in expected_keys:
            assert key in DEFAULT_FEATURE_FLAGS, f"Missing flag: {key}"

    def test_max_attachments_is_positive(self):
        """MAX_ATTACHMENTS_PER_MESSAGE が正の数"""
        assert MAX_ATTACHMENTS_PER_MESSAGE > 0

    def test_max_urls_is_positive(self):
        """MAX_URLS_PER_MESSAGE が正の数"""
        assert MAX_URLS_PER_MESSAGE > 0


class TestMeetingMinutesFeatureFlag:
    """ENABLE_MEETING_MINUTES フラグによるLLM関数注入テスト（Phase C MVP1）"""

    def test_flag_exists_in_defaults(self):
        """ENABLE_MEETING_MINUTES がデフォルトフラグに存在"""
        assert "ENABLE_MEETING_MINUTES" in DEFAULT_FEATURE_FLAGS
        assert DEFAULT_FEATURE_FLAGS["ENABLE_MEETING_MINUTES"] is False

    @pytest.mark.asyncio
    async def test_injects_llm_caller_when_flag_on(self, mock_pool):
        """フラグON + llm_caller設定時にget_ai_response_funcが注入される"""
        mock_llm = AsyncMock(return_value="議事録テキスト")
        bridge = CapabilityBridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={"ENABLE_MEETING_MINUTES": True},
            llm_caller=mock_llm,
        )

        mock_handler_result = HandlerResult(success=True, message="ok", data={})

        with patch("handlers.meeting_handler.handle_meeting_upload", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = mock_handler_result
            await bridge._handle_meeting_transcription(
                room_id="r1",
                account_id="a1",
                sender_name="test",
                params={"audio_data": b"fake"},
            )

            call_kwargs = mock_handler.call_args[1]
            assert "get_ai_response_func" in call_kwargs
            assert call_kwargs["get_ai_response_func"] is mock_llm
            assert call_kwargs.get("enable_minutes") is True

    @pytest.mark.asyncio
    async def test_no_injection_when_flag_off(self, mock_pool):
        """フラグOFF時はget_ai_response_funcが注入されない"""
        mock_llm = AsyncMock()
        bridge = CapabilityBridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={"ENABLE_MEETING_MINUTES": False},
            llm_caller=mock_llm,
        )

        mock_handler_result = HandlerResult(success=True, message="ok", data={})

        with patch("handlers.meeting_handler.handle_meeting_upload", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = mock_handler_result
            await bridge._handle_meeting_transcription(
                room_id="r1",
                account_id="a1",
                sender_name="test",
                params={"audio_data": b"fake"},
            )

            call_kwargs = mock_handler.call_args[1]
            assert "get_ai_response_func" not in call_kwargs
            assert "enable_minutes" not in call_kwargs

    @pytest.mark.asyncio
    async def test_no_injection_when_no_llm_caller(self, mock_pool):
        """llm_caller未設定時はフラグONでも注入されない"""
        bridge = CapabilityBridge(
            pool=mock_pool,
            org_id="org_test",
            feature_flags={"ENABLE_MEETING_MINUTES": True},
            llm_caller=None,
        )

        mock_handler_result = HandlerResult(success=True, message="ok", data={})

        with patch("handlers.meeting_handler.handle_meeting_upload", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = mock_handler_result
            await bridge._handle_meeting_transcription(
                room_id="r1",
                account_id="a1",
                sender_name="test",
                params={"audio_data": b"fake"},
            )

            call_kwargs = mock_handler.call_args[1]
            assert "get_ai_response_func" not in call_kwargs
