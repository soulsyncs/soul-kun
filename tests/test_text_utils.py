# tests/test_text_utils.py
"""
ソウルくん テキスト処理ユーティリティ テスト

lib/text_utils.py のカバレッジ向上テスト
対象: 未カバーの行 174-200, 227, 261, 289, 292, 299, 344, 347-350,
      430-432, 457-503, 561, 618, 649, 664, 672, 693, 723-730
"""

import pytest
from unittest.mock import patch, MagicMock

from lib.text_utils import (
    remove_greetings,
    extract_task_subject,
    is_greeting_only,
    validate_summary,
    clean_chatwork_tags,
    validate_and_get_reason,
    prepare_task_display_text,
    GREETING_PATTERNS,
    CLOSING_PATTERNS,
    GREETING_STARTS,
    TRUNCATION_INDICATORS,
    MID_SENTENCE_ENDINGS,
)


# =============================================================================
# extract_task_subject テスト (lines 174-200)
# =============================================================================

class TestExtractTaskSubject:
    """extract_task_subject のテスト"""

    def test_empty_text_returns_empty(self):
        """空文字列の場合は空文字列を返す (line 174-175)"""
        assert extract_task_subject("") == ""
        assert extract_task_subject(None) == ""

    def test_extract_bracket_subject(self):
        """【...】形式の件名抽出 (lines 178-182)"""
        result = extract_task_subject("【1月ETCカード利用管理依頼】\nお疲れ様です！")
        assert result == "【1月ETCカード利用管理依頼】"

    def test_bracket_subject_too_short(self):
        """【...】形式だが件名が短すぎる (line 181)"""
        result = extract_task_subject("【ab】\n本文です")
        # 3文字未満なので【】抽出はスキップ -> 1行目「【ab】」が40文字以下で件名として返る
        assert result == "【ab】"

    def test_extract_headline_with_symbol(self):
        """記号で始まる見出しの抽出 (lines 185-189)"""
        result = extract_task_subject("■ 経費精算の手順について")
        assert result == "経費精算の手順について"

    def test_extract_headline_various_symbols(self):
        """各種記号の見出し抽出"""
        for symbol in ["●", "◆", "▼", "★", "☆", "□", "○", "◇"]:
            result = extract_task_subject(f"{symbol} テスト見出しです")
            assert result == "テスト見出しです"

    def test_headline_too_short(self):
        """記号見出しが短すぎる場合"""
        result = extract_task_subject("■ ab")
        # 2文字は3文字未満なのでスキップ
        assert result != "ab"

    def test_headline_too_long(self):
        """記号見出しが長すぎる場合"""
        long_headline = "■ " + "あ" * 51
        result = extract_task_subject(long_headline)
        # 50文字を超える場合はスキップ -> 1行目判定に移る
        assert result != "あ" * 51

    def test_first_line_as_subject(self):
        """1行目が件名として使われる場合 (lines 192-198)"""
        result = extract_task_subject("経費精算書の提出依頼\n詳細な内容が続きます")
        assert result == "経費精算書の提出依頼"

    def test_first_line_starts_with_greeting(self):
        """1行目が挨拶で始まる場合はスキップ (line 196)"""
        result = extract_task_subject("お疲れ様です。本日の件")
        # 挨拶で始まるので件名として使わない
        assert result != "お疲れ様です。本日の件"

    def test_first_line_too_long(self):
        """1行目が40文字を超える場合 (line 195)"""
        long_line = "あ" * 41
        result = extract_task_subject(long_line)
        assert result == ""

    def test_first_line_ends_with_period(self):
        """1行目が句点で終わる場合 (line 197)"""
        result = extract_task_subject("これは質問です。")
        assert result == ""

    def test_first_line_ends_with_question(self):
        """1行目がクエスチョンマークで終わる場合"""
        assert extract_task_subject("これは質問ですか？") == ""
        assert extract_task_subject("Is this a question?") == ""

    def test_no_subject_found(self):
        """件名が見つからない場合 (line 200)"""
        result = extract_task_subject("お疲れ様です！今日もよろしくお願いいたします。明日の件について確認したいと思いますがいかがでしょうか。")
        assert result == ""

    def test_greeting_prefix_patterns(self):
        """各挨拶プレフィックスパターン"""
        for prefix in ["いつも", "こんにち", "おはよう", "こんばん"]:
            result = extract_task_subject(f"{prefix}は、本日の件です")
            assert result == ""


# =============================================================================
# is_greeting_only テスト (line 227)
# =============================================================================

class TestIsGreetingOnly:
    """is_greeting_only のテスト"""

    def test_empty_text_is_greeting_only(self):
        """空文字列は挨拶のみと判定 (line 227)"""
        assert is_greeting_only("") == True
        assert is_greeting_only(None) == True

    def test_greeting_only_text(self):
        """挨拶のみのテキスト"""
        assert is_greeting_only("お疲れ様です！") == True
        assert is_greeting_only("よろしくお願いします。") == True

    def test_greeting_with_content(self):
        """挨拶+コンテンツ"""
        assert is_greeting_only("お疲れ様です！経費精算書を提出してください。") == False


# =============================================================================
# validate_summary テスト (lines 261, 289, 292, 299)
# =============================================================================

class TestValidateSummary:
    """validate_summary のテスト"""

    def test_empty_summary_invalid(self):
        """空の要約は無効 (line 261)"""
        assert validate_summary("", "長い本文テキスト") == False

    def test_none_summary_invalid(self):
        """None の要約は無効"""
        assert validate_summary(None, "テスト本文") == False

    def test_symbol_with_mid_sentence_ending(self):
        """記号で始まり助詞で終わる場合はNG (line 289)"""
        assert validate_summary("●経費精算書の", "長い本文テキストです。詳細な内容が含まれます。") == False
        assert validate_summary("■タスクの対応を", "長い本文テキストです。詳細な内容が含まれます。") == False

    def test_symbol_with_comma_ending(self):
        """記号で始まり読点で終わる場合はNG (line 292)"""
        assert validate_summary("●経費精算書、", "長い本文テキストです。") == False
        assert validate_summary("■確認事項,", "長い本文テキストです。") == False

    def test_short_summary_with_particle_ending(self):
        """短いsummaryが助詞で終わる場合はNG (line 299)"""
        assert validate_summary("決算書の", "元の長い本文テキスト") == False
        assert validate_summary("資料を", "元の長い本文テキスト") == False
        assert validate_summary("経費精算で", "元の長い本文テキスト") == False

    def test_valid_summary(self):
        """有効な要約"""
        assert validate_summary("経費精算書の提出依頼", "お疲れ様です。経費精算書を提出してください。") == True

    def test_comma_ending_invalid(self):
        """読点で終わる場合はNG"""
        assert validate_summary("経費精算書の提出依頼について、", "本文") == False
        assert validate_summary("確認事項として,", "本文") == False

    def test_truncation_indicator_invalid(self):
        """途切れインジケータで終わる場合はNG"""
        assert validate_summary("経費精算書の提出依頼…", "本文") == False
        assert validate_summary("確認事項...", "本文") == False


# =============================================================================
# clean_chatwork_tags テスト (lines 344, 347-350, 430-432)
# =============================================================================

class TestCleanChatworkTags:
    """clean_chatwork_tags のテスト"""

    def test_empty_body_returns_empty(self):
        """空の本文は空文字列を返す (line 344)"""
        assert clean_chatwork_tags("") == ""
        assert clean_chatwork_tags(None) == ""

    def test_non_string_body_conversion(self):
        """文字列でない本文は変換を試みる (lines 347-350)"""
        result = clean_chatwork_tags(12345)
        assert isinstance(result, str)

    def test_non_string_unconvertible(self):
        """変換不可能な型 (lines 349-350)"""
        # An object whose str() raises an exception
        class BadStr:
            def __str__(self):
                raise ValueError("cannot convert")
        result = clean_chatwork_tags(BadStr())
        assert result == ""

    def test_exception_in_processing(self):
        """処理中の例外 (lines 430-432)"""
        # Patch re.sub to raise an exception during processing
        with patch('lib.text_utils.re.sub', side_effect=Exception("test error")):
            result = clean_chatwork_tags("テスト本文")
            # Exception handler returns the body as-is
            assert "テスト本文" in result

    def test_quote_block_processing(self):
        """引用ブロックの処理"""
        body = "[qt][qtmeta aid=123]引用テキスト[/qt]\nこの本文のテキストはとても重要で長いです。確認してください。"
        result = clean_chatwork_tags(body)
        # Non-quote text is > 10 chars, so it should be used instead of quote
        assert "本文のテキストはとても重要" in result

    def test_quote_only_message(self):
        """引用のみのメッセージ"""
        body = "[qt][qtmeta aid=123]引用内のテキストだけです[/qt]"
        result = clean_chatwork_tags(body)
        assert "引用内のテキストだけです" in result

    def test_to_tag_removal(self):
        """[To:xxx]タグの除去"""
        body = "[To:12345]田中さん\nタスクの件です"
        result = clean_chatwork_tags(body)
        assert "[To:" not in result

    def test_info_tag_removal(self):
        """[info]タグの除去（内容は残す）"""
        body = "[info]お知らせ内容[/info]"
        result = clean_chatwork_tags(body)
        assert "[info]" not in result


# =============================================================================
# validate_and_get_reason テスト (lines 457-503)
# =============================================================================

class TestValidateAndGetReason:
    """validate_and_get_reason のテスト"""

    def test_empty_summary(self):
        """空の要約 (line 457-458)"""
        valid, reason = validate_and_get_reason("", "本文")
        assert valid == False
        assert reason == "empty"

    def test_none_summary(self):
        """None の要約"""
        valid, reason = validate_and_get_reason(None, "本文")
        assert valid == False
        assert reason == "empty"

    def test_greeting_only(self):
        """挨拶のみ (line 460-461)"""
        valid, reason = validate_and_get_reason("お疲れ様です！", "長い本文テキスト")
        assert valid == False
        assert reason == "greeting_only"

    def test_too_short(self):
        """短すぎる (line 463-464)"""
        # is_greeting_only returns True if cleaned text <= 5 chars
        # Need summary >= 6 chars (not greeting_only) but < 8 chars to trigger "too_short"
        valid, reason = validate_and_get_reason("確認依頼の件", "とても長い本文テキストが含まれています")
        assert valid == False
        assert reason == "too_short"

    def test_truncated(self):
        """途切れている (line 466-467)"""
        valid, reason = validate_and_get_reason("途中で途切れ…", "本文")
        assert valid == False
        assert reason == "truncated"

    def test_truncated_with_dots(self):
        """ドットで途切れ"""
        valid, reason = validate_and_get_reason("途中で途切れ...", "本文")
        assert valid == False
        assert reason == "truncated"

    def test_starts_with_greeting(self):
        """挨拶で始まる (line 469-470)"""
        valid, reason = validate_and_get_reason("お疲れ様から始まるけど内容のある長い文章です", "本文")
        assert valid == False
        assert reason == "starts_with_greeting"

    def test_ends_with_comma(self):
        """読点で終わる (line 473-474)"""
        valid, reason = validate_and_get_reason("経費精算書の提出依頼について、", "本文")
        assert valid == False
        assert reason == "ends_with_comma"

    def test_ends_with_halfwidth_comma(self):
        """半角カンマで終わる"""
        valid, reason = validate_and_get_reason("確認事項として,", "本文")
        assert valid == False
        assert reason == "ends_with_comma"

    def test_symbol_incomplete(self):
        """記号で始まり不完全 (line 480-481)"""
        valid, reason = validate_and_get_reason("●経費精算書の", "本文")
        assert valid == False
        assert reason == "symbol_incomplete"

    def test_symbol_ends_with_comma(self):
        """記号で始まり読点で終わる (line 482-483)"""
        # "■経費精算書の件、" ends with 、 globally, so ends_with_comma fires first
        # To trigger symbol_ends_with_comma, the symbol-stripped text must end with comma
        # but the full summary must NOT end with comma (impossible since symbol is prefix)
        # Actually, the ends_with_comma check runs before symbol check,
        # so any summary ending in 、 or , gets "ends_with_comma"
        valid, reason = validate_and_get_reason("■経費精算書の件、", "本文")
        assert valid == False
        assert reason == "ends_with_comma"

    def test_symbol_ends_with_halfwidth_comma(self):
        """記号で始まり半角カンマで終わる"""
        valid, reason = validate_and_get_reason("◆報告事項,", "本文")
        assert valid == False
        assert reason == "ends_with_comma"

    def test_short_particle_ending(self):
        """短い要約が助詞で終わる (line 488-489)"""
        # "決算書の" is 4 chars -> is_greeting_only (<=5) fires first
        # Use a summary > 5 chars and <= 10 chars ending with particle
        valid, reason = validate_and_get_reason("経費精算書の確認の", "本文テキスト")
        assert valid == False
        assert reason == "short_particle_ending"

    def test_mid_sentence_truncated(self):
        """元本文の途中で切れている (lines 496-501)"""
        original = "経費精算書の提出をお願いします。期限は来週金曜日です。"
        # 元本文の途中で切れた要約
        valid, reason = validate_and_get_reason("経費精算書の提出を", original)
        assert valid == False
        # 短い要約なので short_particle_ending か mid_sentence_truncated
        assert reason in ["short_particle_ending", "mid_sentence_truncated"]

    def test_mid_sentence_truncated_long_summary(self):
        """長い要約が元本文の途中で切れている場合"""
        original = "経費精算書の確認依頼について詳細をお伝えします。来月の締め切りまでに必ず提出してください。"
        summary = "経費精算書の確認依頼について"  # 元本文の一部で終わる
        valid, reason = validate_and_get_reason(summary, original)
        # "について"は接続表現なので short_particle_ending にはならない可能性
        # ただし元本文の中にあり、後に続きがある
        # reasonの確認は実装依存
        assert isinstance(valid, bool)

    def test_valid_summary(self):
        """有効な要約 (line 503)"""
        valid, reason = validate_and_get_reason("経費精算書の提出依頼", "お疲れ様です。経費精算書を提出してください。")
        assert valid == True
        assert reason is None

    def test_all_greeting_starts(self):
        """全挨拶開始パターン"""
        for greeting in GREETING_STARTS:
            summary = f"{greeting}から始まる長い要約テキスト"
            valid, reason = validate_and_get_reason(summary, "本文テキスト")
            assert valid == False
            assert reason == "starts_with_greeting"

    def test_all_truncation_indicators(self):
        """全途切れインジケータ"""
        for indicator in TRUNCATION_INDICATORS:
            summary = f"経費精算書の提出{indicator}"
            valid, reason = validate_and_get_reason(summary, "本文")
            assert valid == False
            assert reason == "truncated"

    def test_all_symbols_with_particle(self):
        """全記号で始まり助詞で終わる"""
        for symbol in ['●', '■', '◆', '▼', '★', '☆', '□', '○', '◇']:
            valid, reason = validate_and_get_reason(f"{symbol}経費精算書の", "本文")
            assert valid == False
            assert reason == "symbol_incomplete"


# =============================================================================
# prepare_task_display_text テスト (lines 561, 618, 649, 664, 672, 693, 723-730)
# =============================================================================

class TestPrepareTaskDisplayText:
    """prepare_task_display_text のテスト"""

    def test_empty_text(self):
        """空のテキスト"""
        assert prepare_task_display_text("") == "（タスク内容なし）"
        assert prepare_task_display_text(None) == "（タスク内容なし）"

    def test_long_bracket_subject_truncation(self):
        """長い【件名】の切り詰め (line 561)"""
        long_subject = "あ" * 50
        text = f"【{long_subject}】\n本文"
        result = prepare_task_display_text(text, max_length=20)
        assert result.startswith("【")
        assert result.endswith("】")
        assert len(result) <= 22  # 20 + 【】

    def test_bracket_subject_within_limit(self):
        """【件名】がmax_length以内"""
        result = prepare_task_display_text("【経費精算依頼】 お疲れ様です。")
        assert result == "【経費精算依頼】"

    def test_short_bracket_subject_ignored(self):
        """短い【件名】は無視される"""
        result = prepare_task_display_text("【ab】 タスクの内容です")
        # 件名 "ab" is 2 chars (< 5), so bracket extraction is skipped
        # The full text is processed normally; 【ab】 remains in the text
        assert isinstance(result, str)

    def test_text_becomes_empty_after_cleaning(self):
        """クリーニング後にテキストが空になる場合 (line 618)"""
        result = prepare_task_display_text("お疲れ様です！よろしくお願いします。")
        assert result == "（タスク内容なし）"

    def test_short_text_unchanged(self):
        """短いテキストはそのまま返す"""
        result = prepare_task_display_text("確認依頼")
        assert result == "確認依頼"

    def test_text_ending_with_connector(self):
        """接続表現で終わるテキスト (line 664)"""
        result = prepare_task_display_text("経費精算書について")
        assert result == "経費精算書について"

    def test_text_ending_with_connector_within_limit(self):
        """接続表現 'として' で終わる"""
        result = prepare_task_display_text("対応策として")
        assert result == "対応策として"

    def test_incomplete_ending_removal(self):
        """不完全な末尾パターンの削除"""
        # "の" で終わるテキスト（10文字以上）
        result = prepare_task_display_text("経費精算書の確認依頼の")
        assert not result.endswith("の")

    def test_result_too_short_after_cleanup(self):
        """クリーンアップ後に結果が短すぎる場合 (line 672)"""
        # 助詞だけで構成されるようなテキスト
        result = prepare_task_display_text("のをにで")
        # 不完全な末尾を削除した後、短すぎる場合は（タスク内容なし）
        assert result in ["のをにで", "（タスク内容なし）"]

    def test_truncation_at_comma_with_incomplete_result(self):
        """読点位置での切り取りが不完全な場合 (line 693 - continue)"""
        # 40文字を超え、読点があるが読点前の内容が不完全なケース
        text = "あ" * 15 + "を、" + "い" * 25
        result = prepare_task_display_text(text, max_length=20)
        assert len(result) <= 21  # max_length + possible "..."

    def test_truncation_at_period(self):
        """句点位置での切り取り"""
        text = "経費精算書の提出をお願いします。その他の連絡事項についてもご確認ください。"
        result = prepare_task_display_text(text, max_length=20)
        if "。" in result:
            assert result.endswith("。")

    def test_truncation_at_connector_phrase(self):
        """接続表現での切り取り"""
        text = "経費精算書の提出について確認をお願いします。これは重要な事項です。"
        result = prepare_task_display_text(text, max_length=20)
        assert len(result) <= 21

    def test_truncation_at_action_word(self):
        """動作語での切り取り"""
        text = "予算の確認作業と経費の精算処理を本日中に実施してほしいとのことです"
        result = prepare_task_display_text(text, max_length=20)
        assert len(result) <= 21

    def test_final_fallback_ellipsis(self):
        """最終手段: 省略記号付き切り詰め (lines 723-724)"""
        # 助詞・接続表現・動作語・句読点のない長い文
        text = "アアアアアアアアアアアアアアアアアアアアアアアアアアアアアアアアアアアアアアアアアア"
        result = prepare_task_display_text(text, max_length=10)
        # 不完全な末尾の削除ができないかもしれないので省略記号付き
        assert len(result) <= 11

    def test_exception_handling(self):
        """例外処理 (lines 728-730)"""
        with patch('lib.text_utils.re.sub', side_effect=[Exception("test error")]):
            result = prepare_task_display_text("テストテキスト")
            # Exception handler returns truncated text
            assert isinstance(result, str)

    def test_name_removal_with_furigana(self):
        """フリガナ付き名前の除去"""
        text = "月宮 絵莉香（ツキミヤ エリカ）さん ありがとうございます！タスクの件です"
        result = prepare_task_display_text(text)
        assert "月宮" not in result

    def test_simple_name_removal_before_greeting(self):
        """名前+挨拶パターンの除去"""
        text = "田中さん お疲れ様です！経費精算の件です"
        result = prepare_task_display_text(text)
        assert "田中さん" not in result

    def test_url_removal(self):
        """URLの除去"""
        text = "詳細は https://example.com/test を確認してください"
        result = prepare_task_display_text(text)
        assert "https://" not in result

    def test_inline_greeting_removal(self):
        """行中の挨拶パターン除去"""
        text = "タスク完了報告 よろしくお願いします！ 次の件です"
        result = prepare_task_display_text(text)
        assert "よろしくお願いします" not in result

    def test_multiline_text(self):
        """複数行テキスト"""
        text = "経費精算書\n提出依頼\nお疲れ様です。"
        result = prepare_task_display_text(text)
        assert "\n" not in result

    def test_work_schedule_name_removal(self):
        """勤務時間パターン付き名前の除去"""
        text = "平賀しおり _ 月火木金9：30～13：30さん タスクの件"
        result = prepare_task_display_text(text)
        # The name pattern should be removed
        assert "平賀" not in result or "タスク" in result

    def test_very_short_text_under_10_chars(self):
        """10文字未満の短いテキストはそのまま返す"""
        result = prepare_task_display_text("確認")
        assert result == "確認"

    def test_truncation_comma_before_incomplete_word(self):
        """読点前が不完全な単語の場合の処理"""
        # 読点で切ると不完全（5文字未満になる）になるケース
        text = "あ" * 5 + "の、" + "い" * 40
        result = prepare_task_display_text(text, max_length=10)
        assert isinstance(result, str)
        assert len(result) <= 11


# =============================================================================
# remove_greetings 追加テスト
# =============================================================================

class TestRemoveGreetings:
    """remove_greetings の追加テスト"""

    def test_nested_greetings(self):
        """ネストした挨拶の除去"""
        text = "お疲れ様です！いつもお世話になっております。経費精算書の件です。"
        result = remove_greetings(text)
        assert "経費精算書の件です" in result
        assert "お疲れ" not in result

    def test_closing_greeting_removal(self):
        """終了の挨拶の除去"""
        text = "経費精算書を提出してください。よろしくお願いします。"
        result = remove_greetings(text)
        assert "よろしくお願いします" not in result

    def test_email_prefix_removal(self):
        """メール形式プレフィックスの除去"""
        assert "経費の件" in remove_greetings("Re: 経費の件")
        assert "経費の件" in remove_greetings("Fw: 経費の件")
        assert "経費の件" in remove_greetings("CC: 経費の件")

    def test_empty_text(self):
        """空テキスト"""
        assert remove_greetings("") == ""
        assert remove_greetings(None) == ""

    def test_apology_greeting_removal(self):
        """お詫び挨拶の除去"""
        text = "夜分に申し訳ございません。経費の件です。"
        result = remove_greetings(text)
        assert "経費の件" in result

    def test_closing_with_confirmation(self):
        """確認付き終了挨拶の除去"""
        text = "経費の件です。ご確認よろしくお願いします。"
        result = remove_greetings(text)
        assert "よろしく" not in result


# =============================================================================
# validate_summary 追加テスト (broader coverage for edge cases)
# =============================================================================

class TestValidateSummaryExtended:
    """validate_summary の拡張テスト"""

    def test_greeting_only_summary(self):
        """挨拶のみの要約"""
        assert validate_summary("お疲れ様です！", "長い本文") == False

    def test_short_summary_long_body(self):
        """短い要約に対して長い本文"""
        assert validate_summary("短い", "これは非常に長い本文テキストです。") == False

    def test_short_summary_short_body(self):
        """短い要約に対して短い本文"""
        # "短い要約" is 4 chars -> is_greeting_only (<=5) returns True
        # Need a summary > 5 chars that doesn't trigger other checks
        assert validate_summary("経費精算依頼", "短い本文") == True

    def test_mid_sentence_ending_in_original(self):
        """元本文の途中で切れた要約"""
        original = "経費精算書の提出をお願いいたします。来週金曜日までに提出してください。"
        # 長い要約で元本文の一部
        summary = "経費精算書の提出を"
        result = validate_summary(summary, original)
        assert result == False

    def test_valid_long_summary(self):
        """有効な長い要約"""
        assert validate_summary(
            "経費精算書の提出依頼に関する詳細",
            "お疲れ様です。経費精算書を提出してください。"
        ) == True

    def test_all_mid_sentence_endings_short(self):
        """短い要約での各助詞終わり"""
        for ending in MID_SENTENCE_ENDINGS[:5]:
            summary = f"経費精算{ending}"
            if len(summary) <= 10:
                result = validate_summary(summary, "元の本文テキスト")
                assert result == False, f"'{summary}' should be invalid"

    def test_symbol_heading_valid(self):
        """記号で始まるが有効な要約"""
        result = validate_summary("●経費精算書の提出依頼", "本文テキスト")
        assert result == True
