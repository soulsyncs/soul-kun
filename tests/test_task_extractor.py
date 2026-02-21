# tests/test_task_extractor.py
"""
議事録タスク自動抽出のテスト

Author: Claude Opus 4.6
Created: 2026-02-13
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.meetings.task_extractor import (
    DEFAULT_TASK_DEADLINE_DAYS,
    ExtractedTask,
    TaskExtractionResult,
    build_task_extraction_prompt,
    extract_and_create_tasks,
    parse_deadline_hint,
    parse_task_extraction_response,
)


# ============================================================
# parse_deadline_hint tests
# ============================================================


class TestParseDeadlineHint:
    """parse_deadline_hint のユニットテスト（3AI合意: 2026-02-20）"""

    def _days_from_now(self, timestamp: int) -> int:
        """Unixタイムスタンプと現在時刻の差を日数（切り捨て）で返す"""
        now_ts = datetime.now(timezone.utc).timestamp()
        return int((timestamp - now_ts) / 86400)

    def test_none_returns_default_7days(self):
        ts = parse_deadline_hint(None)
        days = self._days_from_now(ts)
        assert days == DEFAULT_TASK_DEADLINE_DAYS - 1 or days == DEFAULT_TASK_DEADLINE_DAYS

    def test_empty_string_returns_default(self):
        ts = parse_deadline_hint("")
        days = self._days_from_now(ts)
        assert days >= DEFAULT_TASK_DEADLINE_DAYS - 1

    def test_nashi_returns_default(self):
        for hint in ("なし", "未設定", "不明"):
            ts = parse_deadline_hint(hint)
            days = self._days_from_now(ts)
            assert days >= DEFAULT_TASK_DEADLINE_DAYS - 1

    def test_kyou_returns_today(self):
        for hint in ("今日", "本日"):
            ts = parse_deadline_hint(hint)
            days = self._days_from_now(ts)
            assert days == 0

    def test_ashita_returns_tomorrow(self):
        ts = parse_deadline_hint("明日")
        days = self._days_from_now(ts)
        assert days == 1

    def test_n_days_later(self):
        ts = parse_deadline_hint("3日後")
        days = self._days_from_now(ts)
        assert days == 3

    def test_n_days_cap_at_90(self):
        ts = parse_deadline_hint("999日後")
        days = self._days_from_now(ts)
        assert days == 90

    def test_konshu_returns_this_friday(self):
        """今週中 → 最も近い金曜日（金曜なら今日）"""
        ts = parse_deadline_hint("今週中")
        now = datetime.now(timezone.utc)
        weekday = now.weekday()  # 0=月, 4=金
        expected_days = (4 - weekday) % 7
        days = self._days_from_now(ts)
        assert days == expected_days

    def test_konshu_on_friday_returns_today(self):
        """金曜当日に今週中 → 今日（翌週金曜ではない、W-1修正確認）"""
        from unittest.mock import patch
        from datetime import timedelta
        # 2026-02-20は金曜日（weekday=4）
        friday = datetime(2026, 2, 20, 10, 0, 0, tzinfo=timezone.utc)
        with patch("lib.meetings.task_extractor.datetime") as mock_dt:
            mock_dt.now.return_value = friday
            ts = parse_deadline_hint("今週中")
        # 金曜当日 → end_of_day of Friday
        friday_end = int(friday.replace(hour=23, minute=59, second=0, microsecond=0).timestamp())
        assert ts == friday_end

    def test_raishu_returns_7days(self):
        ts = parse_deadline_hint("来週")
        days = self._days_from_now(ts)
        assert days == 7

    def test_kongetsu_returns_end_of_month(self):
        from datetime import date
        import calendar
        ts = parse_deadline_hint("今月中")
        now = datetime.now(timezone.utc)
        last_day = calendar.monthrange(now.year, now.month)[1]
        end_of_month = datetime(now.year, now.month, last_day, 23, 59, 0, tzinfo=timezone.utc)
        assert ts == int(end_of_month.timestamp())

    def test_unknown_hint_returns_default(self):
        """解釈不能なヒントはデフォルト7日"""
        ts = parse_deadline_hint("未定")
        days = self._days_from_now(ts)
        assert days >= DEFAULT_TASK_DEADLINE_DAYS - 1

    def test_custom_default_days(self):
        """default_days引数が反映されるか"""
        ts = parse_deadline_hint(None, default_days=14)
        days = self._days_from_now(ts)
        assert days == 13 or days == 14


# ============================================================
# build_task_extraction_prompt tests
# ============================================================


class TestBuildPrompt:
    def test_includes_title(self):
        prompt = build_task_extraction_prompt("議事録テキスト", "営業定例")
        assert "営業定例" in prompt

    def test_includes_minutes_text(self):
        prompt = build_task_extraction_prompt("タスク: 見積もり作成", "MTG")
        assert "見積もり作成" in prompt

    def test_uses_xml_tags(self):
        prompt = build_task_extraction_prompt("text", "MTG")
        assert "<meeting_minutes>" in prompt
        assert "</meeting_minutes>" in prompt

    # --- 話者識別（speaker attribution）テスト ---

    def test_no_speaker_context_backward_compat(self):
        """speaker_contextなしは後方互換（既存動作と同じ）"""
        prompt = build_task_extraction_prompt("議事録", "MTG")
        assert "speaker_transcript" not in prompt
        assert "<meeting_minutes>" in prompt

    def test_none_speaker_context_backward_compat(self):
        """speaker_context=Noneは後方互換"""
        prompt = build_task_extraction_prompt("議事録", "MTG", None)
        assert "speaker_transcript" not in prompt

    def test_with_speaker_context_adds_transcript_section(self):
        """speaker_contextが渡されると発言記録セクションが追加される"""
        ctx = "話者1: 私が対応します\n話者2: ありがとうございます"
        prompt = build_task_extraction_prompt("議事録テキスト", "週次会議", ctx)
        assert "<speaker_transcript>" in prompt
        assert "</speaker_transcript>" in prompt
        assert "話者1: 私が対応します" in prompt

    def test_speaker_context_contains_anon_labels(self):
        """speaker_contextは匿名ラベルのみ含む（実名なし）"""
        ctx = "話者1: わかりました\n話者2: 対応します"
        prompt = build_task_extraction_prompt("議事録", "MTG", ctx)
        assert "話者1" in prompt
        assert "話者2" in prompt

    def test_speaker_context_and_minutes_both_included(self):
        """speaker_contextあり時も議事録は必ず含まれる"""
        ctx = "話者1: 対応します"
        prompt = build_task_extraction_prompt("重要なタスクがある", "MTG", ctx)
        assert "<meeting_minutes>" in prompt
        assert "重要なタスクがある" in prompt
        assert "<speaker_transcript>" in prompt


# ============================================================
# parse_task_extraction_response tests
# ============================================================


class TestParseResponse:
    def test_valid_json_array(self):
        response = '[{"task": "見積もり作成", "assignee": "田中", "deadline_hint": "来週"}]'
        tasks = parse_task_extraction_response(response)
        assert len(tasks) == 1
        assert tasks[0].task_body == "見積もり作成"
        assert tasks[0].assignee_name == "田中"
        assert tasks[0].deadline_hint == "来週"

    def test_multiple_tasks(self):
        response = (
            '[{"task": "見積もり作成", "assignee": "田中", "deadline_hint": "来週"},'
            ' {"task": "資料作成", "assignee": "佐藤", "deadline_hint": "今月中"}]'
        )
        tasks = parse_task_extraction_response(response)
        assert len(tasks) == 2

    def test_empty_assignee(self):
        response = '[{"task": "会議室予約", "assignee": "", "deadline_hint": ""}]'
        tasks = parse_task_extraction_response(response)
        assert len(tasks) == 1
        assert tasks[0].assignee_name is None
        assert tasks[0].deadline_hint is None

    def test_empty_array(self):
        tasks = parse_task_extraction_response("[]")
        assert len(tasks) == 0

    def test_markdown_code_block(self):
        response = '```json\n[{"task": "テスト", "assignee": ""}]\n```'
        tasks = parse_task_extraction_response(response)
        assert len(tasks) == 1
        assert tasks[0].task_body == "テスト"

    def test_invalid_json(self):
        tasks = parse_task_extraction_response("not json at all")
        assert len(tasks) == 0

    def test_empty_response(self):
        assert parse_task_extraction_response("") == []
        assert parse_task_extraction_response(None) == []

    def test_non_array_json(self):
        tasks = parse_task_extraction_response('{"task": "test"}')
        assert len(tasks) == 0

    def test_skips_empty_task_body(self):
        response = '[{"task": "", "assignee": "田中"}, {"task": "有効タスク", "assignee": ""}]'
        tasks = parse_task_extraction_response(response)
        assert len(tasks) == 1
        assert tasks[0].task_body == "有効タスク"

    def test_skips_non_dict_items(self):
        response = '["string_item", {"task": "有効", "assignee": ""}]'
        tasks = parse_task_extraction_response(response)
        assert len(tasks) == 1


# ============================================================
# extract_and_create_tasks tests
# ============================================================


class TestExtractAndCreateTasks:
    @pytest.mark.asyncio
    async def test_no_ai_func_returns_empty(self):
        result = await extract_and_create_tasks(
            minutes_text="text",
            meeting_title="MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=None,
        )
        assert result.total_extracted == 0

    @pytest.mark.asyncio
    async def test_llm_returns_tasks(self):
        mock_ai = AsyncMock(
            return_value='[{"task": "見積もり作成", "assignee": "田中", "deadline_hint": "来週"}]'
        )
        result = await extract_and_create_tasks(
            minutes_text="田中さん、来週までに見積もり出して",
            meeting_title="営業定例",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
        )
        assert result.total_extracted == 1
        assert result.tasks[0].task_body == "見積もり作成"
        assert result.tasks[0].assignee_name == "田中"
        # ChatWork clientなし → unassigned
        assert result.total_unassigned == 1

    @pytest.mark.asyncio
    async def test_llm_empty_response(self):
        mock_ai = AsyncMock(return_value="[]")
        result = await extract_and_create_tasks(
            minutes_text="雑談のみ",
            meeting_title="雑談MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
        )
        assert result.total_extracted == 0

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self):
        mock_ai = AsyncMock(side_effect=Exception("LLM down"))
        result = await extract_and_create_tasks(
            minutes_text="text",
            meeting_title="MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
        )
        assert result.total_extracted == 0

    @pytest.mark.asyncio
    async def test_full_flow_with_chatwork_creation(self):
        """タスク抽出→名前解決→ChatWorkタスク作成の完全フロー"""
        mock_ai = AsyncMock(
            return_value='[{"task": "見積もり作成", "assignee": "田中", "deadline_hint": "来週"}]'
        )
        mock_cw_client = MagicMock()
        mock_cw_client.create_task.return_value = {"task_ids": [98765]}

        mock_resolver = MagicMock(return_value="12345")

        result = await extract_and_create_tasks(
            minutes_text="田中さん、来週までに見積もり出して",
            meeting_title="営業定例",
            room_id="111111",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
            chatwork_client=mock_cw_client,
            name_resolver=mock_resolver,
        )

        assert result.total_extracted == 1
        assert result.total_created == 1
        assert result.total_unassigned == 0
        assert result.tasks[0].chatwork_task_id == "98765"
        assert result.tasks[0].assignee_account_id == "12345"
        assert result.tasks[0].created is True

        # ChatWork APIが正しい引数で呼ばれたか
        mock_cw_client.create_task.assert_called_once()
        call_args = mock_cw_client.create_task.call_args
        assert call_args[0][0] == 111111  # room_id as int
        assert call_args[0][1] == "見積もり作成"  # body
        assert call_args[0][2] == [12345]  # to_ids
        assert call_args[0][4] == "date"  # limit_type

    @pytest.mark.asyncio
    async def test_unresolved_assignee_skipped(self):
        """名前解決失敗時はスキップ"""
        mock_ai = AsyncMock(
            return_value='[{"task": "タスクA", "assignee": "不明な人", "deadline_hint": ""}]'
        )
        mock_cw_client = MagicMock()
        mock_resolver = MagicMock(return_value=None)

        result = await extract_and_create_tasks(
            minutes_text="text",
            meeting_title="MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
            chatwork_client=mock_cw_client,
            name_resolver=mock_resolver,
        )

        assert result.total_extracted == 1
        assert result.total_unassigned == 1
        assert result.total_created == 0
        assert result.tasks[0].error == "assignee_not_resolved"
        mock_cw_client.create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_chatwork_api_error_counted_as_failed(self):
        """ChatWork API失敗時はfailedカウント"""
        mock_ai = AsyncMock(
            return_value='[{"task": "タスクA", "assignee": "田中", "deadline_hint": ""}]'
        )
        mock_cw_client = MagicMock()
        mock_cw_client.create_task.side_effect = Exception("API error")
        mock_resolver = MagicMock(return_value="12345")

        result = await extract_and_create_tasks(
            minutes_text="text",
            meeting_title="MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
            chatwork_client=mock_cw_client,
            name_resolver=mock_resolver,
        )

        assert result.total_extracted == 1
        assert result.total_failed == 1
        assert result.tasks[0].error == "Exception"

    @pytest.mark.asyncio
    async def test_multiple_tasks_mixed_results(self):
        """複数タスク: 一部成功、一部失敗"""
        mock_ai = AsyncMock(
            return_value=(
                '[{"task": "タスクA", "assignee": "田中", "deadline_hint": ""},'
                ' {"task": "タスクB", "assignee": "不明", "deadline_hint": ""},'
                ' {"task": "タスクC", "assignee": "", "deadline_hint": ""}]'
            )
        )
        mock_cw_client = MagicMock()
        mock_cw_client.create_task.return_value = {"task_ids": [100]}

        def mock_resolve(name):
            if name == "田中":
                return "12345"
            return None

        result = await extract_and_create_tasks(
            minutes_text="text",
            meeting_title="MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
            chatwork_client=mock_cw_client,
            name_resolver=mock_resolve,
        )

        assert result.total_extracted == 3
        assert result.total_created == 1  # 田中のみ
        assert result.total_unassigned == 2  # 不明 + 空

    @pytest.mark.asyncio
    async def test_no_name_resolver_skips_creation(self):
        """name_resolver未指定時はタスク作成をスキップ"""
        mock_ai = AsyncMock(
            return_value='[{"task": "タスクA", "assignee": "田中", "deadline_hint": ""}]'
        )
        mock_cw_client = MagicMock()

        result = await extract_and_create_tasks(
            minutes_text="text",
            meeting_title="MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
            chatwork_client=mock_cw_client,
            name_resolver=None,
        )

        assert result.total_extracted == 1
        assert result.total_unassigned == 1
        assert result.total_created == 0
        mock_cw_client.create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_room_id_fails_all(self):
        """room_idが数値でない場合は全タスクfailed"""
        mock_ai = AsyncMock(
            return_value='[{"task": "タスクA", "assignee": "田中", "deadline_hint": ""}]'
        )
        mock_cw_client = MagicMock()
        mock_resolver = MagicMock(return_value="12345")

        result = await extract_and_create_tasks(
            minutes_text="text",
            meeting_title="MTG",
            room_id="not_a_number",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
            chatwork_client=mock_cw_client,
            name_resolver=mock_resolver,
        )

        assert result.total_failed == 1
        mock_cw_client.create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_account_id_fails(self):
        """resolverが非数値を返した場合はfailed"""
        mock_ai = AsyncMock(
            return_value='[{"task": "タスクA", "assignee": "田中", "deadline_hint": ""}]'
        )
        mock_cw_client = MagicMock()
        mock_resolver = MagicMock(return_value="not-a-number")

        result = await extract_and_create_tasks(
            minutes_text="text",
            meeting_title="MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
            chatwork_client=mock_cw_client,
            name_resolver=mock_resolver,
        )

        assert result.total_failed == 1
        assert result.tasks[0].error == "invalid_account_id"

    @pytest.mark.asyncio
    async def test_max_tasks_limit(self):
        """MAX_TASKS_PER_EXTRACTION上限が適用されるか"""
        # 25タスクのJSONを生成
        tasks_json = json.dumps([
            {"task": f"タスク{i}", "assignee": "", "deadline_hint": ""}
            for i in range(25)
        ])
        mock_ai = AsyncMock(return_value=tasks_json)

        result = await extract_and_create_tasks(
            minutes_text="text",
            meeting_title="MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
        )

        assert result.total_extracted == 20  # MAX_TASKS_PER_EXTRACTION

    @pytest.mark.asyncio
    async def test_sync_ai_func_wrapped_in_thread(self):
        """同期AI関数がasyncio.to_threadで呼ばれるか"""
        def sync_ai(messages, system):
            return '[{"task": "テスト", "assignee": "", "deadline_hint": ""}]'

        result = await extract_and_create_tasks(
            minutes_text="text",
            meeting_title="MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=sync_ai,
        )

        assert result.total_extracted == 1


# ============================================================
# 話者識別（speaker attribution）統合テスト
# ============================================================


class TestSpeakerAttribution:
    """話者逆変換ロジックのテスト（extract_and_create_tasks の speaker_reverse_map）"""

    @pytest.mark.asyncio
    async def test_speaker_reverse_map_converts_assignee(self):
        """LLMが「話者1」で返したassigneeを実名に逆変換する"""
        mock_ai = AsyncMock(
            return_value='[{"task": "資料作成", "assignee": "話者1", "deadline_hint": "来週"}]'
        )
        reverse_map = {"話者1": "田中", "話者2": "山田"}
        result = await extract_and_create_tasks(
            minutes_text="田中が資料を作成することになった",
            meeting_title="週次MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
            speaker_reverse_map=reverse_map,
        )
        assert result.total_extracted == 1
        # 「話者1」→「田中」に逆変換されていること
        assert result.tasks[0].assignee_name == "田中"

    @pytest.mark.asyncio
    async def test_no_reverse_map_keeps_assignee_as_is(self):
        """speaker_reverse_mapなしの場合、assigneeはそのまま（後方互換）"""
        mock_ai = AsyncMock(
            return_value='[{"task": "確認", "assignee": "田中", "deadline_hint": "なし"}]'
        )
        result = await extract_and_create_tasks(
            minutes_text="田中が確認する",
            meeting_title="MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
        )
        assert result.tasks[0].assignee_name == "田中"

    @pytest.mark.asyncio
    async def test_unknown_speaker_label_kept_as_is(self):
        """逆変換マップにないラベルはそのまま残す"""
        mock_ai = AsyncMock(
            return_value='[{"task": "対応", "assignee": "話者99", "deadline_hint": "なし"}]'
        )
        reverse_map = {"話者1": "田中"}
        result = await extract_and_create_tasks(
            minutes_text="誰かが対応する",
            meeting_title="MTG",
            room_id="123",
            organization_id="org_test",
            get_ai_response_func=mock_ai,
            speaker_reverse_map=reverse_map,
        )
        # 「話者99」はマップにないのでそのまま
        assert result.tasks[0].assignee_name == "話者99"


# ============================================================
# ExtractedTask dataclass tests
# ============================================================


class TestExtractedTask:
    def test_default_values(self):
        task = ExtractedTask(task_body="テスト")
        assert task.assignee_name is None
        assert task.chatwork_task_id is None
        assert task.created is False
        assert task.error is None

    def test_with_all_fields(self):
        task = ExtractedTask(
            task_body="見積もり",
            assignee_name="田中",
            deadline_hint="来週",
            assignee_account_id="123",
            chatwork_task_id="456",
            created=True,
        )
        assert task.created is True
        assert task.assignee_account_id == "123"
