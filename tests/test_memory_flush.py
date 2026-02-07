# tests/test_memory_flush.py
"""
自動メモリフラッシュのユニットテスト

Phase 1-A: OpenClawから学んだ「Auto Memory Flush」のsoul-kun実装テスト
"""

import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from lib.brain.memory_flush import (
    AutoMemoryFlusher,
    ExtractedMemory,
    FlushResult,
    FLUSH_TRIGGER_COUNT,
    MIN_FLUSH_CONFIDENCE,
    MAX_FLUSH_ITEMS,
    contains_pii,
)


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
def mock_ai_client():
    """AIクライアントのモック"""
    client = AsyncMock()
    return client


@pytest.fixture
def flusher(mock_pool):
    """AutoMemoryFlusherインスタンス（AIクライアントなし）"""
    return AutoMemoryFlusher(
        pool=mock_pool,
        org_id="org_test",
    )


@pytest.fixture
def flusher_with_ai(mock_pool, mock_ai_client):
    """AutoMemoryFlusherインスタンス（AIクライアントあり）"""
    return AutoMemoryFlusher(
        pool=mock_pool,
        org_id="org_test",
        ai_client=mock_ai_client,
    )


@pytest.fixture
def sample_conversation():
    """テスト用会話履歴"""
    return [
        {"role": "user", "content": "田中さんって営業部の部長だよね？覚えておいて"},
        {"role": "assistant", "content": "はい、田中さんが営業部の部長であることを記憶しました。"},
        {"role": "user", "content": "僕は簡潔な報告が好きだから、長い文章は避けてね"},
        {"role": "assistant", "content": "了解しました。簡潔な報告を心がけます。"},
        {"role": "user", "content": "金曜日までに企画書を提出するよ"},
        {"role": "assistant", "content": "金曜日の企画書提出、承知しました。"},
        {"role": "user", "content": "来月から在宅勤務を週3日にすることに決めた"},
        {"role": "assistant", "content": "在宅勤務週3日への変更、承知しました。"},
    ]


# =============================================================================
# should_flush テスト
# =============================================================================


class TestShouldFlush:
    """フラッシュ判定のテスト"""

    def test_below_threshold_returns_false(self, flusher):
        """閾値未満はフラッシュ不要"""
        assert flusher.should_flush(FLUSH_TRIGGER_COUNT - 1) is False

    def test_at_threshold_returns_true(self, flusher):
        """閾値到達でフラッシュ必要"""
        assert flusher.should_flush(FLUSH_TRIGGER_COUNT) is True

    def test_above_threshold_returns_true(self, flusher):
        """閾値超過でもフラッシュ必要"""
        assert flusher.should_flush(FLUSH_TRIGGER_COUNT + 5) is True

    def test_zero_returns_false(self, flusher):
        """0件はフラッシュ不要"""
        assert flusher.should_flush(0) is False


# =============================================================================
# ルールベース抽出テスト
# =============================================================================


class TestRuleBasedExtraction:
    """ルールベース抽出のテスト"""

    def test_extract_explicit_remember_request(self, flusher):
        """「覚えて」パターンの抽出"""
        history = [
            {"role": "user", "content": "田中さんは営業部長だよ、覚えて"},
        ]
        result = flusher._rule_based_extraction(history)
        assert len(result) >= 1
        assert result[0].category == "fact"
        assert result[0].confidence == 0.9

    def test_extract_preference_pattern(self, flusher):
        """好み/嫌いパターンの抽出"""
        history = [
            {"role": "user", "content": "コーヒーが好きです"},
        ]
        result = flusher._rule_based_extraction(history)
        assert len(result) >= 1
        assert result[0].category == "preference"

    def test_extract_commitment_pattern(self, flusher):
        """コミットメントパターンの抽出"""
        history = [
            {"role": "user", "content": "金曜日までに資料を出します"},
        ]
        result = flusher._rule_based_extraction(history)
        assert len(result) >= 1
        assert result[0].category == "commitment"

    def test_skip_assistant_messages(self, flusher):
        """アシスタントのメッセージは抽出しない"""
        history = [
            {"role": "assistant", "content": "覚えておきますね"},
        ]
        result = flusher._rule_based_extraction(history)
        assert len(result) == 0

    def test_skip_greeting(self, flusher):
        """挨拶は抽出しない"""
        history = [
            {"role": "user", "content": "おはようございます"},
        ]
        result = flusher._rule_based_extraction(history)
        assert len(result) == 0

    def test_empty_history(self, flusher):
        """空の会話履歴"""
        result = flusher._rule_based_extraction([])
        assert len(result) == 0


# =============================================================================
# LLM応答パーステスト
# =============================================================================


class TestParseExtractionResponse:
    """LLM応答のパーステスト"""

    def test_parse_valid_json(self, flusher):
        """正しいJSON応答のパース"""
        response = json.dumps([
            {"category": "fact", "content": "田中さんは部長", "subject": "田中さん", "confidence": 0.9},
        ])
        result = flusher._parse_extraction_response(response)
        assert len(result) == 1
        assert result[0].category == "fact"
        assert result[0].content == "田中さんは部長"
        assert result[0].confidence == 0.9

    def test_parse_markdown_code_block(self, flusher):
        """マークダウンコードブロック内のJSONパース"""
        response = '```json\n[{"category": "preference", "content": "簡潔が好き", "subject": "ユーザー", "confidence": 0.8}]\n```'
        result = flusher._parse_extraction_response(response)
        assert len(result) == 1
        assert result[0].category == "preference"

    def test_parse_empty_array(self, flusher):
        """空配列の応答"""
        result = flusher._parse_extraction_response("[]")
        assert len(result) == 0

    def test_parse_invalid_json(self, flusher):
        """不正なJSON応答"""
        result = flusher._parse_extraction_response("invalid json")
        assert len(result) == 0

    def test_parse_invalid_category(self, flusher):
        """無効なカテゴリは無視"""
        response = json.dumps([
            {"category": "invalid_category", "content": "test", "subject": "test", "confidence": 0.9},
        ])
        result = flusher._parse_extraction_response(response)
        assert len(result) == 0

    def test_parse_non_array(self, flusher):
        """配列でない応答"""
        result = flusher._parse_extraction_response('{"category": "fact"}')
        assert len(result) == 0


# =============================================================================
# フラッシュ実行テスト
# =============================================================================


class TestFlush:
    """フラッシュ実行のテスト"""

    @pytest.mark.asyncio
    async def test_flush_empty_history(self, flusher):
        """空の会話履歴ではフラッシュしない"""
        result = await flusher.flush([], "user123", "room456")
        assert result.flushed_count == 0
        assert result.success

    @pytest.mark.asyncio
    async def test_flush_with_rule_based(self, flusher, sample_conversation):
        """ルールベース抽出でフラッシュ実行"""
        result = await flusher.flush(sample_conversation, "user123", "room456")
        assert result.flushed_count > 0
        assert len(result.extracted_items) > 0

    @pytest.mark.asyncio
    async def test_flush_with_ai_client(self, flusher_with_ai, mock_ai_client, sample_conversation):
        """AIクライアント使用時のフラッシュ"""
        mock_ai_client.generate.return_value = json.dumps([
            {"category": "fact", "content": "田中さんは営業部長", "subject": "田中さん", "confidence": 0.9},
            {"category": "preference", "content": "簡潔な報告を好む", "subject": "ユーザー", "confidence": 0.85},
        ])
        result = await flusher_with_ai.flush(sample_conversation, "user123", "room456")
        assert result.flushed_count == 2
        mock_ai_client.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_filters_low_confidence(self, flusher_with_ai, mock_ai_client):
        """低確信度のアイテムはスキップ"""
        mock_ai_client.generate.return_value = json.dumps([
            {"category": "fact", "content": "高確信度", "subject": "test", "confidence": 0.9},
            {"category": "fact", "content": "低確信度", "subject": "test", "confidence": 0.3},
        ])
        history = [{"role": "user", "content": "テスト"}]
        result = await flusher_with_ai.flush(history, "user123", "room456")
        assert result.flushed_count == 1
        assert result.skipped_count == 1

    @pytest.mark.asyncio
    async def test_flush_ai_failure_falls_back(self, flusher_with_ai, mock_ai_client):
        """AIクライアント失敗時はルールベースにフォールバック"""
        mock_ai_client.generate.side_effect = Exception("API Error")
        history = [
            {"role": "user", "content": "これを覚えておいて"},
        ]
        result = await flusher_with_ai.flush(history, "user123", "room456")
        # ルールベースで「覚えて」パターンを検出
        assert result.flushed_count >= 1

    @pytest.mark.asyncio
    async def test_flush_respects_max_items(self, flusher_with_ai, mock_ai_client):
        """最大件数を超えない"""
        items = [
            {"category": "fact", "content": f"item{i}", "subject": f"s{i}", "confidence": 0.9}
            for i in range(MAX_FLUSH_ITEMS + 5)
        ]
        mock_ai_client.generate.return_value = json.dumps(items)
        history = [{"role": "user", "content": "テスト"}]
        result = await flusher_with_ai.flush(history, "user123", "room456")
        assert result.flushed_count <= MAX_FLUSH_ITEMS


# =============================================================================
# データクラステスト
# =============================================================================


class TestDataClasses:
    """データクラスのテスト"""

    def test_extracted_memory_to_dict(self):
        """ExtractedMemoryのシリアライズ"""
        item = ExtractedMemory(
            category="fact",
            content="田中さんは部長",
            subject="田中さん",
            confidence=0.9,
        )
        d = item.to_dict()
        assert d["category"] == "fact"
        assert d["content"] == "田中さんは部長"
        assert d["confidence"] == 0.9

    def test_flush_result_success_no_errors(self):
        """エラーなしの場合はsuccess=True"""
        result = FlushResult(flushed_count=3, skipped_count=1)
        assert result.success is True

    def test_flush_result_failure_with_errors(self):
        """エラーありの場合はsuccess=False"""
        result = FlushResult(flushed_count=1, error_count=1, errors=["test error"])
        assert result.success is False

    def test_flush_result_to_dict(self):
        """FlushResultのシリアライズ"""
        result = FlushResult(flushed_count=2, skipped_count=1)
        d = result.to_dict()
        assert d["flushed_count"] == 2
        assert d["skipped_count"] == 1


# =============================================================================
# 会話フォーマットテスト
# =============================================================================


class TestFormatConversation:
    """会話フォーマットのテスト"""

    def test_format_user_and_assistant(self, flusher):
        """ユーザーとアシスタントの会話をフォーマット"""
        history = [
            {"role": "user", "content": "こんにちは"},
            {"role": "assistant", "content": "こんにちは！"},
        ]
        text = flusher._format_conversation(history)
        assert "ユーザー: こんにちは" in text
        assert "ソウルくん: こんにちは！" in text

    def test_format_empty_history(self, flusher):
        """空の会話履歴"""
        text = flusher._format_conversation([])
        assert text == ""


# =============================================================================
# PIIフィルタテスト（Codexレビュー指摘#1対応）
# =============================================================================


class TestPIIFilter:
    """PIIフィルタのテスト"""

    def test_detect_phone_number_with_hyphens(self):
        """ハイフン付き電話番号の検出"""
        assert contains_pii("連絡先は090-1234-5678です") is True

    def test_detect_phone_number_without_hyphens(self):
        """ハイフンなし電話番号の検出"""
        assert contains_pii("電話番号は09012345678") is True

    def test_detect_email(self):
        """メールアドレスの検出"""
        assert contains_pii("メールはtanaka@example.com") is True

    def test_detect_password(self):
        """パスワードの検出"""
        assert contains_pii("パスワード: abc123") is True
        assert contains_pii("password is secret123") is True

    def test_detect_api_key(self):
        """APIキーの検出"""
        assert contains_pii("APIキー: sk-xxxx") is True
        assert contains_pii("api_key=abcdef") is True

    def test_detect_salary(self):
        """給与情報の検出"""
        assert contains_pii("給与 500000") is True
        assert contains_pii("月額85万円") is True

    def test_no_pii_in_normal_text(self):
        """通常テキストはPIIなし"""
        assert contains_pii("田中さんは営業部の部長です") is False
        assert contains_pii("簡潔な報告を好む") is False
        assert contains_pii("金曜日までに提出する") is False

    def test_empty_string(self):
        """空文字列はPIIなし"""
        assert contains_pii("") is False


class TestPersistWithPII:
    """PII含有アイテムの永続化スキップテスト"""

    @pytest.mark.asyncio
    async def test_skip_item_with_pii_in_content(self, flusher_with_ai, mock_ai_client):
        """PII含有コンテンツは永続化しない"""
        mock_ai_client.generate.return_value = json.dumps([
            {"category": "fact", "content": "田中さんの電話は090-1234-5678", "subject": "田中さん", "confidence": 0.9},
            {"category": "fact", "content": "田中さんは部長", "subject": "田中さん", "confidence": 0.9},
        ])
        history = [{"role": "user", "content": "テスト"}]
        result = await flusher_with_ai.flush(history, "user123", "room456")
        # PII含有の1件はスキップされ、安全な1件のみ保存
        assert result.flushed_count == 1

    @pytest.mark.asyncio
    async def test_skip_item_with_pii_in_subject(self, flusher_with_ai, mock_ai_client):
        """PII含有サブジェクトは永続化しない"""
        mock_ai_client.generate.return_value = json.dumps([
            {"category": "fact", "content": "担当者の連絡先", "subject": "tanaka@example.com", "confidence": 0.9},
            {"category": "fact", "content": "田中さんは部長", "subject": "田中さん", "confidence": 0.9},
        ])
        history = [{"role": "user", "content": "テスト"}]
        result = await flusher_with_ai.flush(history, "user123", "room456")
        # subject内のPII1件はスキップ、安全な1件のみ保存
        assert result.flushed_count == 1
        assert result.skipped_count == 1


# =============================================================================
# デバウンステスト（Codexレビュー指摘H-1対応）
# =============================================================================


class TestAutoFlushDebounce:
    """_try_auto_flushのデバウンス機構テスト"""

    @pytest.fixture
    def memory_access(self, mock_pool):
        """BrainMemoryAccessインスタンス（flusher付き）"""
        from lib.brain.memory_access import BrainMemoryAccess
        flusher = AutoMemoryFlusher(pool=mock_pool, org_id="org_test")
        return BrainMemoryAccess(
            pool=mock_pool,
            org_id="org_test",
            memory_flusher=flusher,
        )

    @pytest.fixture
    def mock_context(self):
        """閾値超過のコンテキスト"""
        from lib.brain.memory_access import ConversationMessage
        msgs = [
            ConversationMessage(role="user", content=f"msg{i}")
            for i in range(FLUSH_TRIGGER_COUNT + 1)
        ]
        return {"recent_conversation": msgs}

    @pytest.mark.asyncio
    async def test_first_call_triggers_flush(self, memory_access, mock_context):
        """初回呼び出しではフラッシュがトリガーされる"""
        with patch("lib.brain.memory_access.asyncio.ensure_future") as mock_ensure:
            await memory_access._try_auto_flush(mock_context, "user1", "room1")
            mock_ensure.assert_called_once()

    @pytest.mark.asyncio
    async def test_second_call_within_debounce_skips(self, memory_access, mock_context):
        """デバウンス期間内の2回目はスキップされる"""
        with patch("lib.brain.memory_access.asyncio.ensure_future") as mock_ensure:
            await memory_access._try_auto_flush(mock_context, "user1", "room1")
            await memory_access._try_auto_flush(mock_context, "user1", "room1")
            # 1回のみ呼ばれる
            assert mock_ensure.call_count == 1

    @pytest.mark.asyncio
    async def test_different_room_triggers_separately(self, memory_access, mock_context):
        """別ルームは別々にフラッシュされる"""
        with patch("lib.brain.memory_access.asyncio.ensure_future") as mock_ensure:
            await memory_access._try_auto_flush(mock_context, "user1", "room1")
            await memory_access._try_auto_flush(mock_context, "user1", "room2")
            assert mock_ensure.call_count == 2

    @pytest.mark.asyncio
    async def test_after_debounce_period_triggers_again(self, memory_access, mock_context):
        """デバウンス期間後は再度フラッシュされる"""
        with patch("lib.brain.memory_access.asyncio.ensure_future") as mock_ensure:
            await memory_access._try_auto_flush(mock_context, "user1", "room1")
            # デバウンス期間を過去にずらす
            past = datetime.now(timezone.utc) - timedelta(seconds=301)
            memory_access._flush_last_run["user1:room1"] = past
            await memory_access._try_auto_flush(mock_context, "user1", "room1")
            assert mock_ensure.call_count == 2

    @pytest.mark.asyncio
    async def test_no_flusher_does_nothing(self, mock_pool, mock_context):
        """flusherなしでは何も起きない"""
        from lib.brain.memory_access import BrainMemoryAccess
        ma = BrainMemoryAccess(pool=mock_pool, org_id="org_test")
        with patch("lib.brain.memory_access.asyncio.ensure_future") as mock_ensure:
            await ma._try_auto_flush(mock_context, "user1", "room1")
            mock_ensure.assert_not_called()
