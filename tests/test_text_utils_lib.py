"""
lib/text_utils.py のユニットテスト

v10.17.0: prepare_task_display_text() 追加対応
v10.17.1: 件名抽出・名前除去・行中挨拶除去のテスト追加

テスト対象:
1. prepare_task_display_text() - 新規追加関数
2. clean_chatwork_tags() - 既存関数
3. remove_greetings() - 既存関数
4. validate_summary() - 既存関数

実行方法:
    pytest tests/test_text_utils_lib.py -v
    # または
    PYTHONPATH=. python -m pytest tests/test_text_utils_lib.py -v
"""

import pytest
import sys
import os
import importlib.util

# プロジェクトルートを取得
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# lib/text_utils.pyを直接読み込む（lib/__init__.pyを経由しない）
# これによりCI環境でsqlalchemy等の依存関係がなくてもテスト可能
text_utils_path = os.path.join(project_root, 'lib', 'text_utils.py')
spec = importlib.util.spec_from_file_location("text_utils", text_utils_path)
text_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(text_utils)

# モジュールから関数を取得
prepare_task_display_text = text_utils.prepare_task_display_text
clean_chatwork_tags = text_utils.clean_chatwork_tags
remove_greetings = text_utils.remove_greetings
validate_summary = text_utils.validate_summary
is_greeting_only = text_utils.is_greeting_only


class TestPrepareTaskDisplayText:
    """prepare_task_display_text() のテスト"""

    def test_empty_input_returns_default(self):
        """空入力の場合はデフォルトメッセージを返す"""
        assert prepare_task_display_text("") == "（タスク内容なし）"
        assert prepare_task_display_text(None) == "（タスク内容なし）"

    def test_short_text_unchanged(self):
        """短いテキストはそのまま返す"""
        text = "経費精算書の提出"
        result = prepare_task_display_text(text, max_length=40)
        assert result == text

    def test_truncation_at_period(self):
        """句点で切れる"""
        text = "経費精算書を提出してください。追加の資料も必要です。確認お願いします。"
        result = prepare_task_display_text(text, max_length=25)
        assert result.endswith("。")
        assert len(result) <= 25

    def test_truncation_at_comma(self):
        """読点で切れる"""
        text = "経費精算書を提出し、追加の資料も送付してください"
        result = prepare_task_display_text(text, max_length=15)
        assert len(result) <= 15

    def test_truncation_no_particle_ending(self):
        """v10.25.5: 助詞で終わらない（「〇〇を」「〇〇に」は意味が通じない）"""
        text = "経費精算書を確認して提出する必要があります"
        result = prepare_task_display_text(text, max_length=20)
        assert len(result) <= 20
        # 助詞（を、に、で、と、が、は、の、へ、も）で終わらないことを確認
        particles = ['を', 'に', 'で', 'と', 'が', 'は', 'の', 'へ', 'も']
        assert not any(result.endswith(p) for p in particles), f"結果が助詞で終わっている: {result}"

    def test_no_ellipsis(self):
        """途切れインジケータ（...）が出ない"""
        text = "とても長いタスクの説明文がここに入ります。"
        result = prepare_task_display_text(text, max_length=15)
        assert "..." not in result
        assert "…" not in result

    def test_greeting_removal(self):
        """挨拶が除去される"""
        text = "お疲れ様です！経費精算書を提出してください。"
        result = prepare_task_display_text(text)
        assert "お疲れ" not in result
        assert "経費精算" in result

    def test_newline_handling(self):
        """改行がスペースに置換される"""
        text = "経費精算書を\n提出してください"
        result = prepare_task_display_text(text)
        assert "\n" not in result

    def test_real_world_case_1(self):
        """実例1: メンション後の本文"""
        text = "どなたに伺うのが最適なのかわからなかったため、複数のメンションで失礼します。"
        result = prepare_task_display_text(text, max_length=40)
        assert len(result) <= 40
        # 意味のある位置で切れている
        assert not result.endswith("わか")  # 単語の途中で切れない

    def test_real_world_case_2(self):
        """実例2: 有料職業紹介の例"""
        text = "有料職業紹介の申請を行っていたのですが、本日無事に受付されました！（決算書の"
        result = prepare_task_display_text(text, max_length=40)
        assert len(result) <= 40
        assert not result.endswith("（")  # 括弧の途中で切れない

    def test_fallback_with_action_word(self):
        """最終手段: 動作語で終わる"""
        text = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほ"  # 句読点なし
        result = prepare_task_display_text(text, max_length=20)
        assert len(result) <= 20


class TestCleanChatworkTags:
    """clean_chatwork_tags() のテスト"""

    def test_remove_to_tag(self):
        """[To:xxx]タグが除去される"""
        text = "[To:12345]菊地さん お疲れ様です"
        result = clean_chatwork_tags(text)
        assert "[To:" not in result

    def test_remove_qt_tag(self):
        """[qt]...[/qt]タグが除去される"""
        text = "[qt][qtmeta aid=123 time=1234567890]引用内容[/qt]本文"
        result = clean_chatwork_tags(text)
        assert "[qt]" not in result
        assert "[/qt]" not in result

    def test_preserve_content(self):
        """[info]タグは除去するが内容は残す"""
        text = "[info]重要なお知らせ[/info]"
        result = clean_chatwork_tags(text)
        assert "[info]" not in result
        assert "重要なお知らせ" in result


class TestRemoveGreetings:
    """remove_greetings() のテスト"""

    def test_remove_otsukare(self):
        """「お疲れ様です」が除去される"""
        text = "お疲れ様です！経費精算書を提出してください。"
        result = remove_greetings(text)
        assert "お疲れ" not in result
        assert "経費精算" in result

    def test_remove_osewa(self):
        """「いつもお世話になっております」が除去される"""
        text = "いつもお世話になっております。資料を送付します。"
        result = remove_greetings(text)
        assert "お世話" not in result
        assert "資料" in result

    def test_remove_yoroshiku(self):
        """「よろしくお願いします」が除去される"""
        text = "資料を確認してください。よろしくお願いします。"
        result = remove_greetings(text)
        assert "よろしく" not in result
        assert "資料を確認" in result


class TestValidateSummary:
    """validate_summary() のテスト"""

    def test_valid_summary(self):
        """有効な要約"""
        assert validate_summary("経費精算書の提出依頼", "長い本文...") is True

    def test_invalid_greeting_only(self):
        """挨拶のみは無効"""
        assert validate_summary("お疲れ様です！", "長い本文...") is False

    def test_invalid_too_short(self):
        """短すぎるのは無効（元本文が長い場合）"""
        assert validate_summary("資料", "とても長い本文がここに入ります" * 10) is False

    def test_invalid_truncated(self):
        """途中で途切れているのは無効"""
        assert validate_summary("経費精算書を...", "長い本文...") is False

    def test_invalid_mid_sentence_ending_no(self):
        """v10.25.1: 「の」で終わる途中切れは無効"""
        # 元本文が50文字以上必要
        original = "お疲れ様です。決算書の提出をお願いします。期限は今週金曜日までです。確認よろしくお願いいたします。"
        assert validate_summary("決算書の", original) is False

    def test_invalid_mid_sentence_ending_wo(self):
        """v10.25.1: 「を」で終わる途中切れは無効"""
        # 元本文が50文字以上必要
        original = "お疲れ様です。こちらの資料を確認してください。よろしくお願いします。何卒よろしくお願いいたします。以上です。"
        assert len(original) > 50  # 確認用
        assert validate_summary("こちらの資料を", original) is False

    def test_invalid_mid_sentence_ending_ni(self):
        """v10.25.1: 「に」で終わる途中切れは無効"""
        # 元本文が50文字以上必要
        original = "お手隙でこちらのマスター内の総務のドライブにアップロードしてください。よろしくお願いいたします。以上です。"
        assert len(original) > 50  # 確認用
        assert validate_summary("お手隙でこちらのマスター内の総務のドライブに", original) is False

    def test_valid_summary_ending_with_particle_but_complete(self):
        """v10.25.1: 助詞で終わるが完結している場合は有効"""
        # 「について」で終わるが、元本文にこのテキストが含まれていない
        original = "経費精算について相談したいです。よろしくお願いいたします。何卒よろしくお願いします。"
        assert validate_summary("経費精算について相談依頼", original) is True

    def test_valid_summary_short_original(self):
        """v10.25.1: 元本文が短い場合は助詞チェックしない"""
        # is_greeting_onlyは5文字以下を挨拶扱いするので、6文字以上のサマリーを使用
        original = "経費精算書の提出依頼です"  # 11文字（50未満）
        assert validate_summary("経費精算書の提出依頼", original) is True

    def test_invalid_ends_with_comma(self):
        """v10.27.1: 読点「、」で終わる場合は無効"""
        assert validate_summary("こちら後ほど内容の再確認をしたいとのことでしたので、", "長い本文...") is False

    def test_invalid_starts_with_ohayou(self):
        """v10.27.1: 「おはよう」で始まる場合は無効"""
        assert validate_summary("おはようウル！", "長い本文...") is False

    def test_invalid_starts_with_konnichiwa(self):
        """v10.27.1: 「こんにちは」で始まる場合は無効"""
        assert validate_summary("こんにちはウル！", "長い本文...") is False

    def test_invalid_symbol_with_incomplete_sentence(self):
        """v10.27.1: 記号で始まり助詞で終わる場合は無効"""
        assert validate_summary("●こちら後ほど内容の再確認をしたいとのことでしたので、", "長い本文...") is False
        assert validate_summary("■資料を", "長い本文...") is False
        assert validate_summary("◆確認事項について", "長い本文...") is True  # 「について」は有効な終わり


class TestIsGreetingOnly:
    """is_greeting_only() のテスト"""

    def test_greeting_only_true(self):
        """挨拶のみの場合はTrue"""
        assert is_greeting_only("お疲れ様です！") is True
        assert is_greeting_only("いつもお世話になっております。") is True

    def test_greeting_only_false(self):
        """内容がある場合はFalse"""
        assert is_greeting_only("お疲れ様です！経費精算書を提出してください。") is False


# =====================================================
# v10.17.1: 追加テスト（件名抽出・名前除去・行中挨拶除去）
# =====================================================

class TestPrepareTaskDisplayTextSubjectExtraction:
    """prepare_task_display_text() - 件名抽出機能のテスト（v10.17.1追加）"""

    def test_subject_extraction_basic(self):
        """基本的な件名抽出"""
        text = "【経費精算依頼】お疲れ様です！書類を提出してください。"
        result = prepare_task_display_text(text, max_length=40)
        assert result == "【経費精算依頼】"

    def test_subject_extraction_with_checkbox(self):
        """チェックボックス記号付き件名"""
        text = "【□2月未来合宿のご案内・駐車場利用について】 お疲れ様です！ 一人ひとりの"
        result = prepare_task_display_text(text, max_length=40)
        assert "□" not in result  # チェックボックスが除去される
        assert "2月未来合宿" in result
        assert "お疲れ" not in result  # 本文部分は含まれない

    def test_subject_extraction_various_checkboxes(self):
        """各種チェックボックス記号"""
        checkboxes = ["□", "■", "☐", "☑", "✓", "✔"]
        for cb in checkboxes:
            text = f"【{cb}タスク件名テスト】本文"
            result = prepare_task_display_text(text, max_length=40)
            assert cb not in result
            assert "タスク件名テスト" in result

    def test_subject_too_short_fallback(self):
        """件名が短すぎる場合は本文を使用"""
        text = "【OK】これは長い本文です。"
        result = prepare_task_display_text(text, max_length=40)
        # 件名が5文字未満なので本文を使用
        assert "本文" in result or "【OK】" in result

    def test_subject_extraction_long_subject(self):
        """長い件名は切り詰める"""
        text = "【この件名はとても長くて四十文字を超えてしまう件名です】本文"
        result = prepare_task_display_text(text, max_length=40)
        assert len(result) <= 40
        assert result.startswith("【")
        assert result.endswith("】")


class TestPrepareTaskDisplayTextNameRemoval:
    """prepare_task_display_text() - 名前除去機能のテスト（v10.17.1追加）"""

    def test_name_with_reading_removal(self):
        """読み仮名付き名前の除去"""
        text = "月宮 絵莉香（ツキミヤ エリカ）さん ありがとうございます！ フォームの"
        result = prepare_task_display_text(text, max_length=40)
        assert "月宮" not in result
        assert "ツキミヤ" not in result
        assert "フォーム" in result

    def test_name_with_work_schedule_removal(self):
        """勤務時間パターン付き名前の除去"""
        text = "平賀　しおり _ 月火木金9：30～13：30（変動あり）さん いつも丁寧にありがとう"
        result = prepare_task_display_text(text, max_length=40)
        assert "平賀" not in result
        # v10.25.5: 「いつも丁寧に」だけで終わると「に」が助詞削除される
        # 「いつも丁寧」が含まれていることを確認
        assert "いつも丁寧" in result

    def test_name_in_content_preserved(self):
        """本文中の名前は保持"""
        text = "市川さんの忌引き休暇対応を検討する。"
        result = prepare_task_display_text(text, max_length=40)
        assert "市川さん" in result
        assert "忌引き休暇" in result

    def test_name_in_bullet_point_preserved(self):
        """箇条書き内の名前は保持"""
        text = "・池本さん：営業文"
        result = prepare_task_display_text(text, max_length=40)
        assert "池本さん" in result
        assert "営業文" in result

    def test_simple_name_pattern(self):
        """シンプルな名前パターン（本文が続く場合）"""
        text = "田中さん 資料を確認してください"
        result = prepare_task_display_text(text, max_length=40)
        # この場合は「資料を確認してください」が残るべき
        assert "資料" in result or "田中さん" in result


class TestPrepareTaskDisplayTextInlineGreetingRemoval:
    """prepare_task_display_text() - 行中挨拶除去機能のテスト（v10.17.1追加）"""

    def test_inline_greeting_after_subject(self):
        """件名の後の挨拶を除去"""
        text = "件名について お疲れ様です！ 確認をお願いします"
        result = prepare_task_display_text(text, max_length=40)
        assert "お疲れ" not in result

    def test_inline_arigatou_removal(self):
        """行中の「ありがとうございます」を除去"""
        text = "名前さん ありがとうございます！ フォームの件"
        result = prepare_task_display_text(text, max_length=40)
        # 名前が除去された後、ありがとうございますも除去される
        assert "ありがとう" not in result or "フォーム" in result

    def test_greeting_at_start_removal(self):
        """行頭の挨拶除去（既存機能との整合性）"""
        text = "お疲れ様です！経費精算書を提出してください。"
        result = prepare_task_display_text(text, max_length=40)
        assert "お疲れ" not in result
        assert "経費精算" in result


class TestPrepareTaskDisplayTextFalsePositivePrevention:
    """prepare_task_display_text() - 誤検出防止テスト（v10.17.1追加）"""

    def test_joseikin_not_removed(self):
        """「助成金」の「金」が曜日として誤認識されない"""
        text = "助成金対象となるよう研修内容を修正する。"
        result = prepare_task_display_text(text, max_length=40)
        assert "助成金" in result
        assert result == text  # 変更なし

    def test_kinmu_not_removed(self):
        """「勤務」の「金」が曜日として誤認識されない"""
        text = "勤務時間の確認をお願いします。"
        result = prepare_task_display_text(text, max_length=40)
        assert "勤務" in result

    def test_preserve_content_with_kanji_kin(self):
        """「金」を含む一般的な単語が保持される"""
        test_cases = [
            "金曜日に会議があります。",  # これは曜日だが文脈上保持
            "料金の確認をお願いします。",
            "現金精算の処理をしてください。",
            "賃金計算を行ってください。",
        ]
        for text in test_cases:
            result = prepare_task_display_text(text, max_length=40)
            assert "金" in result  # 「金」を含む単語が保持される


class TestPrepareTaskDisplayTextRealWorldCases:
    """prepare_task_display_text() - 本番環境で発生した実例テスト（v10.17.1追加）"""

    def test_real_case_mirai_gasshuku(self):
        """実例: 未来合宿案内"""
        text = "【□2月未来合宿のご案内・駐車場利用について】 お疲れ様です！ 一人ひとりの"
        result = prepare_task_display_text(text, max_length=40)
        assert "□" not in result
        assert "2月未来合宿" in result
        assert len(result) <= 40

    def test_real_case_tsukimiya(self):
        """実例: 月宮さんパターン"""
        text = "月宮 絵莉香（ツキミヤ エリカ）さん ありがとうございます！ フォームの"
        result = prepare_task_display_text(text, max_length=40)
        assert "フォーム" in result
        assert len(result) <= 40

    def test_real_case_hiraga(self):
        """実例: 平賀さん勤務時間パターン"""
        text = "平賀　しおり _ 月火木金9：30～13：30（変動あり）さん いつも丁寧に"
        result = prepare_task_display_text(text, max_length=40)
        assert "平賀" not in result
        assert len(result) <= 40

    def test_real_case_joseikin(self):
        """実例: 助成金（誤除去されない）"""
        text = "助成金対象となるよう研修内容を修正する。"
        result = prepare_task_display_text(text, max_length=40)
        assert result == text

    def test_real_case_ichikawa(self):
        """実例: 市川さんの忌引き（本文中の名前は保持）"""
        text = "市川さんの忌引き休暇対応を検討する。"
        result = prepare_task_display_text(text, max_length=40)
        assert result == text

    def test_real_case_ikemoto(self):
        """実例: 池本さん箇条書き（保持）"""
        text = "・池本さん：営業文"
        result = prepare_task_display_text(text, max_length=40)
        assert result == text

    def test_real_case_form_and_sheet(self):
        """実例: シンプルな内容"""
        text = "フォームおよび管理シート"
        result = prepare_task_display_text(text, max_length=40)
        assert result == text


class TestPrepareTaskDisplayTextV10172CodexFixes:
    """prepare_task_display_text() - v10.17.2 Codex指摘対応テスト"""

    def test_subject_preservation_tanaka_irai(self):
        """「田中さん への依頼内容」の主語を残す（Codex MEDIUM指摘対応）"""
        text = "田中さん への依頼内容をまとめる"
        result = prepare_task_display_text(text, max_length=40)
        assert "田中さん" in result  # 主語として残す
        assert "依頼内容" in result

    def test_department_in_parentheses_preserved(self):
        """「田中（経理部）さん への依頼」の括弧内が漢字なら除去しない"""
        text = "田中（経理部）さん への依頼内容"
        result = prepare_task_display_text(text, max_length=40)
        # 括弧内が漢字（部署名）なので除去されない
        assert "田中" in result
        assert "経理部" in result

    def test_reading_in_parentheses_removed(self):
        """「田中（タナカ）さん ありがとう」の括弧内がカタカナなら除去する"""
        text = "田中（タナカ）さん ありがとうございます！確認をお願いします"
        result = prepare_task_display_text(text, max_length=40)
        # 括弧内がカタカナ（読み仮名）なので除去される
        assert "田中" not in result
        assert "タナカ" not in result
        assert "確認" in result

    def test_preserve_shugo_customer_notification(self):
        """「顧客さん への連絡」のような主語を残す（Codex追加テスト案）"""
        text = "顧客さん への連絡事項を確認する"
        result = prepare_task_display_text(text, max_length=40)
        assert "顧客さん" in result  # 主語として残す
        assert "連絡事項" in result


class TestPrepareTaskDisplayTextV10256Improvements:
    """prepare_task_display_text() - v10.25.6 途切れ改善テスト"""

    def test_url_removal(self):
        """URLが除去される"""
        text = "お手隙でこちらのマスター内の総務のドライブに https://drive.google.com/drive/folders/xxx をお願いします"
        result = prepare_task_display_text(text, max_length=40)
        assert "https" not in result
        assert "drive.google" not in result
        assert "ドライブ" in result  # 内容は残る

    def test_verb_ending_shite_removed(self):
        """動詞活用「〜して」で終わらない"""
        text = "まさのりが12月からソウルシンクス初の医療職のセカンドキャリア先の販路を開拓してくれました"
        result = prepare_task_display_text(text, max_length=40)
        assert not result.endswith("して")
        assert "開拓" in result

    def test_verb_ending_shima_removed(self):
        """動詞活用「〜しま」で終わらない"""
        text = "組織図からのグループ作成について 組織時そのままの細かさですと複雑になってしまうかと思います"
        result = prepare_task_display_text(text, max_length=40)
        assert not result.endswith("しま")
        assert not result.endswith("なって")
        assert "について" in result

    def test_no_trailing_comma(self):
        """読点(、)で終わらない"""
        text = "【ご依頼】 ソウルくん、E-learning、社内システムの利用マニュアルを作成してください"
        result = prepare_task_display_text(text, max_length=40)
        assert not result.endswith("、")
        assert "E-learning" in result

    def test_connector_phrase_cut(self):
        """「について」等の接続表現の後で切る"""
        text = "ソウルくんのリマインドロジックへのフィードバックを反映させるという話について確認したいと思います"
        result = prepare_task_display_text(text, max_length=40)
        assert result.endswith("について")

    def test_action_word_cut(self):
        """動作語(開拓、完了等)の後で切る"""
        text = "こちらお待たせしています、未来合宿の原本動画のドライブ格納も完了しましたのでご連絡です"
        result = prepare_task_display_text(text, max_length=40)
        assert result.endswith("完了")

    def test_incomplete_ending_particles(self):
        """10文字以上のテキストで助詞・動詞活用で終わらない"""
        # 10文字未満はそのまま返す（ユーザー意図尊重）
        short_text = "販路を開拓して"  # 7文字
        result_short = prepare_task_display_text(short_text, max_length=40)
        assert result_short == "販路を開拓して"  # そのまま

        # 10文字以上は不完全な末尾を削除
        long_text = "新規案件の販路を開拓して"  # 12文字
        result_long = prepare_task_display_text(long_text, max_length=40)
        assert result_long == "新規案件の販路を開拓"
        assert not result_long.endswith("して")

    def test_url_after_particle_cleanup(self):
        """URL除去後の不自然なパターン「に を」が整形される"""
        text = "総務のドライブに https://example.com をお願いします"
        result = prepare_task_display_text(text, max_length=40)
        assert "に を" not in result  # 「に を」という不自然なパターンがない

    def test_period_break_still_works(self):
        """句点での切り詰めは従来通り動作"""
        text = "経費精算書を提出してください。よろしくお願いします。"
        result = prepare_task_display_text(text, max_length=40)
        assert result == "経費精算書を提出してください。"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
