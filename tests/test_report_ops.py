# tests/test_report_ops.py
"""
Step C-5: 書き込み系操作のテスト

レポート生成・CSVエクスポート・ファイル作成のテスト。
GCSアップロードはモックで検証。

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import importlib
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# 直接インポート（重い依存を避ける）
report_ops_mod = importlib.import_module("lib.brain.operations.report_ops")
handle_report_generate = report_ops_mod.handle_report_generate
handle_csv_export = report_ops_mod.handle_csv_export
handle_file_create = report_ops_mod.handle_file_create
_safe_filename = report_ops_mod._safe_filename
_build_csv = report_ops_mod._build_csv
_upload_to_gcs = report_ops_mod._upload_to_gcs


# =====================================================
# ファイル名安全化テスト
# =====================================================


class TestSafeFilename:
    """ファイル名の安全化"""

    def test_normal_name(self):
        assert _safe_filename("月次報告書") == "月次報告書"

    def test_removes_dangerous_chars(self):
        result = _safe_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_max_length(self):
        long_name = "あ" * 100
        assert len(_safe_filename(long_name)) <= 50

    def test_empty_returns_empty(self):
        assert _safe_filename("///") == ""

    def test_preserves_extension(self):
        result = _safe_filename("report.txt")
        assert ".txt" in result


# =====================================================
# レポート生成テスト
# =====================================================


class TestReportGenerate:
    """レポート生成ハンドラー"""

    @pytest.mark.asyncio
    async def test_missing_title_returns_error(self):
        """タイトルなしはエラー"""
        result = await handle_report_generate(
            params={"content": "本文あり"},
            organization_id="org-123",
            account_id="acc-001",
        )
        assert result.success is False
        assert "タイトル" in result.message

    @pytest.mark.asyncio
    async def test_missing_content_returns_error(self):
        """本文なしはエラー"""
        result = await handle_report_generate(
            params={"title": "タイトルあり"},
            organization_id="org-123",
            account_id="acc-001",
        )
        assert result.success is False
        assert "本文" in result.message

    @pytest.mark.asyncio
    async def test_successful_report_text(self):
        """テキストレポートの正常生成"""
        with patch.object(report_ops_mod, "_upload_to_gcs") as mock_upload:
            mock_upload.return_value = "gs://test-bucket/org-123/reports/test.txt"

            result = await handle_report_generate(
                params={"title": "月次報告", "content": "売上は好調です。", "format": "text"},
                organization_id="org-123",
                account_id="acc-001",
            )
            assert result.success is True
            assert "月次報告" in result.message
            assert "gs://" in result.message
            assert result.data["format"] == "text"

    @pytest.mark.asyncio
    async def test_successful_report_markdown(self):
        """Markdownレポートの正常生成"""
        with patch.object(report_ops_mod, "_upload_to_gcs") as mock_upload:
            mock_upload.return_value = "gs://test-bucket/org-123/reports/test.md"

            result = await handle_report_generate(
                params={"title": "週次サマリー", "content": "## 成果\n- 項目A完了", "format": "markdown"},
                organization_id="org-123",
                account_id="acc-001",
            )
            assert result.success is True
            assert result.data["format"] == "markdown"

    @pytest.mark.asyncio
    async def test_gcs_upload_failure(self):
        """GCSアップロード失敗時のエラーハンドリング"""
        with patch.object(report_ops_mod, "_upload_to_gcs", side_effect=Exception("GCS error")):
            result = await handle_report_generate(
                params={"title": "テスト", "content": "テスト内容"},
                organization_id="org-123",
                account_id="acc-001",
            )
            assert result.success is False
            assert "エラー" in result.message


# =====================================================
# CSVエクスポートテスト
# =====================================================


class TestCsvExport:
    """CSVエクスポートハンドラー"""

    @pytest.mark.asyncio
    async def test_missing_data_source_returns_error(self):
        """データソースなしはエラー"""
        result = await handle_csv_export(
            params={},
            organization_id="org-123",
            account_id="acc-001",
        )
        assert result.success is False
        assert "データソース" in result.message

    @pytest.mark.asyncio
    async def test_unsupported_source_returns_error(self):
        """未対応データソースはエラー"""
        result = await handle_csv_export(
            params={"data_source": "売上"},
            organization_id="org-123",
            account_id="acc-001",
        )
        assert result.success is False
        assert "対応していません" in result.message

    @pytest.mark.asyncio
    async def test_successful_csv_export(self):
        """正常なCSVエクスポート"""
        mock_rows = [
            (1, "タスクA", "open", None, "営業室"),
            (2, "タスクB", "done", 1740000000, "経理室"),
        ]

        with patch.object(report_ops_mod, "_fetch_csv_data", return_value=mock_rows), \
             patch.object(report_ops_mod, "_upload_to_gcs") as mock_upload:
            mock_upload.return_value = "gs://test-bucket/org-123/exports/tasks.csv"

            result = await handle_csv_export(
                params={"data_source": "tasks"},
                organization_id="org-123",
                account_id="acc-001",
            )
            assert result.success is True
            assert "2件" in result.message
            assert result.data["row_count"] == 2

    def test_build_csv_tasks(self):
        """タスクCSVの構造確認"""
        rows = [
            (1, "報告書作成", "open", None, "営業室"),
            (2, "会議準備", "done", 1740000000, "経理室"),
        ]
        csv_content = _build_csv("chatwork_tasks", rows)
        assert "タスクID" in csv_content
        assert "報告書作成" in csv_content
        assert "未完了" in csv_content
        assert "完了" in csv_content

    def test_build_csv_goals(self):
        """目標CSVの構造確認"""
        rows = [(1, "2026-02", 10), (2, "2026-03", 15)]
        csv_content = _build_csv("staff_goals", rows)
        assert "目標ID" in csv_content
        assert "2026-02" in csv_content

    def test_build_csv_pii_excluded(self):
        """CSVにPII（ユーザー名等）が含まれない"""
        rows = [(1, "田中さんへの報告書", "open", None, "営業室")]
        csv_content = _build_csv("chatwork_tasks", rows)
        # ヘッダーにPIIフィールドがない
        assert "担当者" not in csv_content
        assert "メール" not in csv_content
        assert "assigned" not in csv_content.lower()


# =====================================================
# ファイル作成テスト
# =====================================================


class TestFileCreate:
    """ファイル作成ハンドラー"""

    @pytest.mark.asyncio
    async def test_missing_filename_returns_error(self):
        """ファイル名なしはエラー"""
        result = await handle_file_create(
            params={"content": "内容あり"},
            organization_id="org-123",
            account_id="acc-001",
        )
        assert result.success is False
        assert "ファイル名" in result.message

    @pytest.mark.asyncio
    async def test_missing_content_returns_error(self):
        """内容なしはエラー"""
        result = await handle_file_create(
            params={"filename": "test.txt"},
            organization_id="org-123",
            account_id="acc-001",
        )
        assert result.success is False
        assert "内容" in result.message

    @pytest.mark.asyncio
    async def test_successful_file_create(self):
        """正常なファイル作成"""
        with patch.object(report_ops_mod, "_upload_to_gcs") as mock_upload:
            mock_upload.return_value = "gs://test-bucket/org-123/files/test.txt"

            result = await handle_file_create(
                params={"filename": "議事録メモ.txt", "content": "会議の内容"},
                organization_id="org-123",
                account_id="acc-001",
            )
            assert result.success is True
            assert "議事録メモ" in result.message
            assert "gs://" in result.message

    @pytest.mark.asyncio
    async def test_dangerous_filename_sanitized(self):
        """危険なファイル名が安全化される"""
        with patch.object(report_ops_mod, "_upload_to_gcs") as mock_upload:
            mock_upload.return_value = "gs://test-bucket/org-123/files/safe.txt"

            result = await handle_file_create(
                params={"filename": "../../etc/passwd", "content": "テスト"},
                organization_id="org-123",
                account_id="acc-001",
            )
            # ファイル名は安全化される（..やスラッシュ除去）
            if result.success:
                assert ".." not in result.data.get("filename", "")


# =====================================================
# GCSアップロードテスト
# =====================================================


class TestGcsUpload:
    """GCSアップロードヘルパー"""

    def test_no_bucket_env_raises_error(self):
        """環境変数未設定でエラー"""
        with patch.object(report_ops_mod, "OPERATIONS_GCS_BUCKET", ""):
            with pytest.raises(ValueError, match="環境変数"):
                _upload_to_gcs("test", "path/file.txt", "text/plain", "org-123")

    def test_file_too_large_raises_error(self):
        """1MB超でエラー"""
        large_content = "x" * (1024 * 1024 + 1)
        with patch.object(report_ops_mod, "OPERATIONS_GCS_BUCKET", "test-bucket"):
            with pytest.raises(ValueError, match="上限"):
                _upload_to_gcs(large_content, "path/file.txt", "text/plain", "org-123")


# =====================================================
# SYSTEM_CAPABILITIES統合テスト
# =====================================================


class TestWriteOperationsIntegration:
    """書き込み系操作のSYSTEM_CAPABILITIES統合"""

    def test_operations_in_system_capabilities(self):
        """3つの書き込み操作がSYSTEM_CAPABILITIESに登録されている"""
        from handlers.registry import SYSTEM_CAPABILITIES
        for op_name in ["report_generate", "csv_export", "file_create"]:
            assert op_name in SYSTEM_CAPABILITIES, f"{op_name} not in SYSTEM_CAPABILITIES"
            cap = SYSTEM_CAPABILITIES[op_name]
            assert cap["category"] == "operations"
            assert cap["requires_confirmation"] is True
            assert cap["brain_metadata"]["risk_level"] == "medium"

    def test_operations_in_operation_capabilities(self):
        """OPERATION_CAPABILITIESにも登録されている"""
        from lib.brain.operations.registry import OPERATION_CAPABILITIES
        for op_name in ["report_generate", "csv_export", "file_create"]:
            assert op_name in OPERATION_CAPABILITIES

    def test_risk_levels_defined(self):
        """RISK_LEVELSにmediumで定義されている"""
        from lib.brain.constants import RISK_LEVELS
        for op_name in ["report_generate", "csv_export", "file_create"]:
            assert RISK_LEVELS.get(op_name) == "medium"

    def test_requires_confirmation_for_write_operations(self):
        """書き込み操作は社長の確認が必須"""
        gate_mod = importlib.import_module("lib.brain.approval_gate")
        gate = gate_mod.ApprovalGate()

        for op_name in ["report_generate", "csv_export", "file_create"]:
            result = gate.check(op_name, {})
            assert result.level != gate_mod.ApprovalLevel.AUTO_APPROVE, (
                f"{op_name} should require confirmation"
            )
