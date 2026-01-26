"""
Soul-kun テキスト処理ユーティリティ

★★★ v10.14.1: lib/共通化 ★★★

このモジュールは以下を提供します:
- remove_greetings: 日本語挨拶・定型文の除去
- extract_task_subject: タスク件名の抽出
- is_greeting_only: 挨拶のみかどうかの判定
- validate_summary: 要約品質の検証
- clean_chatwork_tags: ChatWorkタグの除去

使用例（Flask/Cloud Functions）:
    from lib.text_utils import remove_greetings, validate_summary

使用例（FastAPI）:
    from lib.text_utils import remove_greetings, validate_summary

対応Phase:
- Phase 1-B: タスクリマインド（sync-chatwork-tasks, remind-tasks）
- Phase 3: ナレッジ検索（ドキュメント前処理）
- Phase 4: BPaaS（マルチテナント対応済み）
"""

import re
from typing import Tuple, Optional

__version__ = "1.2.0"  # v10.17.1: 件名抽出・名前除去・行中挨拶除去を追加

# =====================================================
# 挨拶パターン定義
# =====================================================
# 日本語ビジネスメール・チャットで使われる挨拶を網羅
# 除去対象として使用
# =====================================================

GREETING_PATTERNS = [
    # ====================
    # 開始の挨拶
    # ====================
    r'^お疲れ様です[。！!]?\s*',
    r'^お疲れさまです[。！!]?\s*',
    r'^おつかれさまです[。！!]?\s*',
    r'^お疲れ様でした[。！!]?\s*',
    r'^いつもお世話になっております[。！!]?\s*',
    r'^いつもお世話になります[。！!]?\s*',
    r'^お世話になっております[。！!]?\s*',
    r'^お世話になります[。！!]?\s*',
    r'^こんにちは[。！!]?\s*',
    r'^おはようございます[。！!]?\s*',
    r'^こんばんは[。！!]?\s*',

    # ====================
    # お詫び・断り
    # ====================
    r'^夜分に申し訳ございません[。！!]?\s*',
    r'^夜分遅くに失礼いたします[。！!]?\s*',
    r'^夜分遅くに失礼します[。！!]?\s*',
    r'^お忙しいところ恐れ入りますが[、,]?\s*',
    r'^お忙しいところ申し訳ございませんが[、,]?\s*',
    r'^お忙しいところ恐縮ですが[、,]?\s*',
    r'^突然のご連絡失礼いたします[。！!]?\s*',
    r'^突然のご連絡失礼します[。！!]?\s*',
    r'^ご連絡が遅くなり申し訳ございません[。！!]?\s*',
    r'^ご連絡遅くなりまして申し訳ございません[。！!]?\s*',
    r'^大変遅くなってしまい申し訳[ございませんありません。！!]*\s*',

    # ====================
    # メール形式ヘッダー
    # ====================
    r'^[Rr][Ee]:\s*',
    r'^[Ff][Ww][Dd]?:\s*',
    r'^[Cc][Cc]:\s*',
]

CLOSING_PATTERNS = [
    # ====================
    # 終了の挨拶
    # ====================
    # v10.25.4: 「をお願いします」「にお願いします」等は依頼内容なので残す
    # 「よろしくお願いします」「何卒お願いします」等の定型句のみ削除
    r'よろしくお願い(いた)?します[。！!]?\s*$',
    r'よろしくお願い(いた)?致します[。！!]?\s*$',
    # r'お願い(いた)?します[。！!]?\s*$',  # v10.25.4: 削除（「〇〇をお願いします」を壊す）
    r'ご確認(の程)?よろしくお願い(いた)?します[。！!]?\s*$',
    r'ご対応(の程)?よろしくお願い(いた)?します[。！!]?\s*$',
    r'ご検討(の程)?よろしくお願い(いた)?します[。！!]?\s*$',
    r'何卒よろしくお願い(いた)?します[。！!]?\s*$',
    r'以上、?よろしくお願い(いた)?します[。！!]?\s*$',
    r'以上です[。！!]?\s*$',
    r'以上となります[。！!]?\s*$',
    r'引き続きよろしくお願い(いた)?します[。！!]?\s*$',
]

# 挨拶開始パターン（バリデーション用）
# v10.27.1: おはよう、こんにち、こんばんを追加
GREETING_STARTS = ['お疲れ', 'いつも', 'お世話', '夜分', 'お忙し', 'おはよう', 'こんにち', 'こんばん']

# 途切れインジケータ（バリデーション用）
TRUNCATION_INDICATORS = ['…', '...', '。。', '、、']

# v10.25.1: 文中で切れている可能性を示す末尾パターン（助詞・接続詞で終わる）
MID_SENTENCE_ENDINGS = ['の', 'を', 'に', 'で', 'が', 'は', 'と', 'も', 'へ', 'から', 'まで', 'より', 'けど', 'ので', 'ため', 'って', 'という']


def remove_greetings(text: str) -> str:
    """
    テキストから日本語の挨拶・定型文を除去する

    ★★★ v10.14.0: 新規追加 ★★★
    ★★★ v10.14.1: lib/共通化 ★★★

    除去対象:
    - 開始の挨拶: お疲れ様です、いつもお世話になっております、等
    - お詫び・断り: 夜分に申し訳ございません、お忙しいところ恐れ入りますが、等
    - メール形式: Re:, Fw:, CC:
    - 終了の挨拶: よろしくお願いします、以上です、等

    Args:
        text: 元のテキスト

    Returns:
        挨拶を除去したテキスト

    Example:
        >>> remove_greetings("お疲れ様です！経費精算書を提出してください。")
        "経費精算書を提出してください。"
    """
    if not text:
        return ""

    result = text

    # 開始の挨拶を除去（複数回試行 - ネストした挨拶対応）
    for _ in range(3):
        original = result
        for pattern in GREETING_PATTERNS:
            result = re.sub(pattern, '', result, flags=re.MULTILINE | re.IGNORECASE)
        if result == original:
            break

    # 終了の挨拶を除去
    for pattern in CLOSING_PATTERNS:
        result = re.sub(pattern, '', result, flags=re.MULTILINE | re.IGNORECASE)

    # 行頭の空白・改行を整理
    result = result.strip()

    return result


def extract_task_subject(text: str) -> str:
    """
    テキストからタスクの件名/タイトルを抽出する

    ★★★ v10.14.0: 新規追加 ★★★
    ★★★ v10.14.1: lib/共通化 ★★★

    優先順位:
    1. 【...】 形式の件名（日本語ビジネス標準）
    2. ■/●/◆ で始まる見出し
    3. 1行目が短くて件名っぽい場合

    Args:
        text: 元のテキスト

    Returns:
        件名（見つからない場合は空文字列）

    Example:
        >>> extract_task_subject("【1月ETCカード利用管理依頼】\\nお疲れ様です！")
        "【1月ETCカード利用管理依頼】"
    """
    if not text:
        return ""

    # 1. 【...】 形式の件名を抽出
    subject_match = re.search(r'【([^】]+)】', text)
    if subject_match:
        subject = subject_match.group(1).strip()
        if len(subject) >= 3:  # 意味のある長さ
            return f"【{subject}】"

    # 2. ■/●/◆/▼/★ で始まる見出しを抽出
    headline_match = re.search(r'^[■●◆▼★☆□○◇]\s*(.+?)(?:\n|$)', text, re.MULTILINE)
    if headline_match:
        headline = headline_match.group(1).strip()
        if 3 <= len(headline) <= 50:  # 適切な長さ
            return headline

    # 3. 1行目が短い場合は件名として扱う
    first_line = text.split('\n')[0].strip()
    # 挨拶で始まらず、40文字以下で、句点やクエスチョンで終わらない
    if (first_line and
        len(first_line) <= 40 and
        not re.match(r'^(お疲れ|いつも|こんにち|おはよう|こんばん)', first_line) and
        not first_line.endswith(('。', '？', '?'))):
        return first_line

    return ""


def is_greeting_only(text: str) -> bool:
    """
    テキストが挨拶のみかどうかを判定する

    ★★★ v10.14.0: 新規追加 ★★★
    ★★★ v10.14.1: lib/共通化 ★★★

    判定基準:
    - 挨拶を除去した後に実質的なコンテンツがない
    - または残りが非常に短い（5文字以下）

    Args:
        text: チェックするテキスト

    Returns:
        True: 挨拶のみ、False: 実質的なコンテンツあり

    Example:
        >>> is_greeting_only("お疲れ様です！")
        True
        >>> is_greeting_only("お疲れ様です！経費精算書を提出してください。")
        False
    """
    if not text:
        return True

    cleaned = remove_greetings(text)
    # 空か、非常に短い場合は挨拶のみと判定
    return len(cleaned.strip()) <= 5


def validate_summary(summary: str, original_body: str) -> bool:
    """
    要約の品質を検証する

    ★★★ v10.14.0: 新規追加 ★★★
    ★★★ v10.14.1: lib/共通化 ★★★

    検証項目:
    1. 挨拶だけではないか
    2. 途中で途切れていないか
    3. 最小限の情報量があるか
    4. 挨拶で始まっていないか

    Args:
        summary: 生成された要約
        original_body: 元の本文

    Returns:
        True: 有効な要約、False: 無効（再生成が必要）

    Example:
        >>> validate_summary("経費精算書の提出依頼", "お疲れ様です。経費精算書を提出してください。")
        True
        >>> validate_summary("お疲れ様です！夜分に申し訳ございません。", "長い本文...")
        False
    """
    if not summary:
        return False

    # 1. 挨拶だけの場合はNG
    if is_greeting_only(summary):
        return False

    # 2. 非常に短い場合はNG（ただし元の本文も短い場合はOK）
    if len(summary) < 8 and len(original_body) > 15:
        return False

    # 3. 明らかに途切れている場合はNG
    if any(summary.endswith(ind) for ind in TRUNCATION_INDICATORS):
        return False

    # 4. 挨拶で始まる場合はNG
    if any(summary.startswith(g) for g in GREETING_STARTS):
        return False

    # 4.5 v10.27.1: 読点「、」「,」で終わる場合はNG（途中で切れている）
    if summary.endswith('、') or summary.endswith(','):
        return False

    # 4.6 v10.27.1: 記号「●」「■」等で始まり、不完全な文の場合はNG
    if summary.startswith(('●', '■', '◆', '▼', '★', '☆', '□', '○', '◇')):
        # 記号を除いた部分が助詞で終わる場合は無効
        summary_without_symbol = summary[1:].strip()
        for ending in MID_SENTENCE_ENDINGS:
            if summary_without_symbol.endswith(ending):
                return False
        # 読点で終わる場合も無効
        if summary_without_symbol.endswith('、') or summary_without_symbol.endswith(','):
            return False

    # 5. v10.25.3: 短いsummaryが助詞で終わる場合は常に無効
    #    例: "決算書の"(4文字), "資料を"(3文字) → 明らかに途切れている
    if len(summary) <= 10:
        for ending in MID_SENTENCE_ENDINGS:
            if summary.endswith(ending):
                return False

    # 6. 長いsummaryでも、元本文の途中で切れている場合は無効
    if len(original_body) > 15:
        for ending in MID_SENTENCE_ENDINGS:
            if summary.endswith(ending):
                # 要約テキストが元本文の一部かどうかをチェック
                summary_stripped = summary.rstrip(ending)
                if summary_stripped and summary_stripped in original_body:
                    # 元本文で要約の後にまだテキストが続いているかチェック
                    pos = original_body.find(summary_stripped)
                    if pos >= 0:
                        after_summary = original_body[pos + len(summary_stripped):]
                        # 要約の後に意味のあるテキスト（5文字以上）があれば途切れと判定
                        if len(after_summary.strip()) > 5:
                            return False

    return True


def clean_chatwork_tags(body: str) -> str:
    """
    ChatWorkのタグや記号を完全に除去する（要約用）

    ★★★ v10.6.1: 引用ブロック処理改善 ★★★
    ★★★ v10.14.1: lib/共通化 ★★★

    除去対象:
    - [qt]...[/qt] 引用ブロック
    - [To:xxx] メンション
    - [info]...[/info] インフォブロック
    - [code]...[/code] コードブロック
    - その他ChatWorkタグ

    処理ロジック:
    - 引用外のテキストがあればそれを優先使用
    - 引用のみの場合は、引用内のテキストを抽出

    Args:
        body: ChatWorkメッセージ本文

    Returns:
        タグを除去したテキスト
    """
    if not body:
        return ""

    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return ""

    try:
        # =====================================================
        # 1. 引用ブロックの処理（v10.6.1改善）
        # =====================================================
        # まず引用外のテキストを抽出してみる
        non_quote_text = re.sub(r'\[qt\].*?\[/qt\]', '', body, flags=re.DOTALL)
        non_quote_text = non_quote_text.strip()

        # 引用外にテキストが十分あればそれを使用
        if non_quote_text and len(non_quote_text) > 10:
            body = non_quote_text
        else:
            # 引用のみ、または引用外のテキストが短い場合
            # → 引用内のテキストを抽出
            quote_matches = re.findall(
                r'\[qt\]\[qtmeta[^\]]*\](.*?)\[/qt\]',
                body,
                flags=re.DOTALL
            )
            if quote_matches:
                # 複数の引用がある場合は結合
                extracted_text = ' '.join(quote_matches)
                # 引用内テキストが空でなければ使用
                if extracted_text.strip():
                    body = extracted_text
            # 引用からも抽出できない場合は元のテキストを使用（タグ除去後）

        # 2. [qtmeta ...] タグを除去（残っている場合）
        body = re.sub(r'\[qtmeta[^\]]*\]', '', body)

        # 3. [qt] [/qt] の単独タグを除去
        body = re.sub(r'\[/?qt\]', '', body)

        # 4. [To:xxx] タグを除去（名前部分も含む）
        body = re.sub(r'\[To:\d+\]\s*[^\n\[]*(?:さん|くん|ちゃん|様|氏)?', '', body)
        body = re.sub(r'\[To:\d+\]', '', body)

        # 5. [piconname:xxx] タグを除去
        body = re.sub(r'\[piconname:\d+\]', '', body)

        # 6. [info]...[/info] タグを除去（内容は残す）
        body = re.sub(r'\[/?info\]', '', body)
        body = re.sub(r'\[/?title\]', '', body)

        # 7. [rp aid=xxx to=xxx-xxx] タグを除去
        body = re.sub(r'\[rp aid=\d+[^\]]*\]', '', body)
        body = re.sub(r'\[/rp\]', '', body)

        # 8. [dtext:xxx] タグを除去
        body = re.sub(r'\[dtext:[^\]]*\]', '', body)

        # 9. [preview ...] タグを除去
        body = re.sub(r'\[preview[^\]]*\]', '', body)
        body = re.sub(r'\[/preview\]', '', body)

        # 10. [code]...[/code] タグを除去（内容は残す）
        body = re.sub(r'\[/?code\]', '', body)

        # 11. [hr] タグを除去
        body = re.sub(r'\[hr\]', '', body)

        # 12. その他の [...] 形式のタグを慎重に除去
        body = re.sub(r'\[/?[a-z]+(?::[^\]]+)?\]', '', body, flags=re.IGNORECASE)

        # 13. 連続する改行を整理
        body = re.sub(r'\n{3,}', '\n\n', body)

        # 14. 連続するスペースを整理
        body = re.sub(r' {2,}', ' ', body)

        # 15. 前後の空白を除去
        body = body.strip()

        # 16. 挨拶・定型文を除去
        body = remove_greetings(body)

        return body

    except Exception as e:
        print(f"⚠️ clean_chatwork_tags エラー: {e}")
        return body


def validate_and_get_reason(summary: str, original_body: str) -> Tuple[bool, Optional[str]]:
    """
    要約の品質を検証し、無効な場合は理由を返す

    ★★★ v10.14.1: 監査ログ用に追加 ★★★

    Args:
        summary: 生成された要約
        original_body: 元の本文

    Returns:
        (is_valid, reason): 有効性と無効理由のタプル
            - 有効な場合: (True, None)
            - 無効な場合: (False, "reason_code")

    Reason codes:
        - "empty": 要約が空
        - "greeting_only": 挨拶のみ
        - "too_short": 短すぎる
        - "truncated": 途中で途切れている
        - "starts_with_greeting": 挨拶で始まる
    """
    if not summary:
        return False, "empty"

    if is_greeting_only(summary):
        return False, "greeting_only"

    if len(summary) < 8 and len(original_body) > 15:
        return False, "too_short"

    if any(summary.endswith(ind) for ind in TRUNCATION_INDICATORS):
        return False, "truncated"

    if any(summary.startswith(g) for g in GREETING_STARTS):
        return False, "starts_with_greeting"

    # v10.27.1: 読点で終わる場合は無効
    if summary.endswith('、') or summary.endswith(','):
        return False, "ends_with_comma"

    # v10.27.1: 記号で始まり不完全な文の場合は無効
    if summary.startswith(('●', '■', '◆', '▼', '★', '☆', '□', '○', '◇')):
        summary_without_symbol = summary[1:].strip()
        for ending in MID_SENTENCE_ENDINGS:
            if summary_without_symbol.endswith(ending):
                return False, "symbol_incomplete"
        if summary_without_symbol.endswith('、') or summary_without_symbol.endswith(','):
            return False, "symbol_ends_with_comma"

    # v10.25.3: 短いsummaryが助詞で終わる場合は常に無効
    if len(summary) <= 10:
        for ending in MID_SENTENCE_ENDINGS:
            if summary.endswith(ending):
                return False, "short_particle_ending"

    # 長いsummaryでも、元本文の途中で切れている場合は無効
    if len(original_body) > 15:
        for ending in MID_SENTENCE_ENDINGS:
            if summary.endswith(ending):
                summary_stripped = summary.rstrip(ending)
                if summary_stripped and summary_stripped in original_body:
                    pos = original_body.find(summary_stripped)
                    if pos >= 0:
                        after_summary = original_body[pos + len(summary_stripped):]
                        if len(after_summary.strip()) > 5:
                            return False, "mid_sentence_truncated"

    return True, None


def prepare_task_display_text(text: str, max_length: int = 40) -> str:
    """
    報告用のタスク表示テキストを整形する

    ★★★ v10.17.0: lib/共通化 ★★★
    ★★★ v10.17.1: 件名抽出・名前除去・行中挨拶除去を追加 ★★★

    処理内容:
    1. 改行を半角スペースに置換（1行にまとめる）
    2. 【件名】があれば優先抽出
    3. 名前パターン（○○さん）を除去
    4. 行中の挨拶パターンを除去
    5. 定型挨拶文を削除
    6. 連続スペースを1つに
    7. 先頭・末尾の空白を除去
    8. max_length文字以内で完結させる（途切れ防止）

    途切れ防止の優先順位:
    1. 句点(。)で終わる位置
    2. 読点(、)で終わる位置
    3. 助詞の後（を、に、で、と、が、は、の、へ、も）
    4. 動作語の後（確認、依頼、報告、対応、作成、提出、...）
    5. 最終手段: max_length-2文字 + 「対応」

    Args:
        text: 元のテキスト（summaryまたはclean_chatwork_tags()後のbody）
        max_length: 最大文字数（デフォルト40）

    Returns:
        整形済みテキスト（途中で途切れない）

    Example:
        >>> prepare_task_display_text("お疲れ様です！経費精算書を提出してください。よろしくお願いします。")
        "経費精算書を提出してください。"
        >>> prepare_task_display_text("【経費精算依頼】 お疲れ様です！...")
        "【経費精算依頼】"
    """
    if not text:
        return "（タスク内容なし）"

    try:
        # 1. 改行を半角スペースに置換（1行にまとめる）
        text = text.replace('\n', ' ').replace('\r', ' ')

        # 2. 【件名】があれば優先抽出（★v10.17.1追加）
        subject_match = re.search(r'【([^】]+)】', text)
        if subject_match:
            subject = subject_match.group(1).strip()
            # 件名が十分な長さで、チェックボックス記号を除去
            subject_clean = re.sub(r'^[□■☐☑✓✔]+\s*', '', subject)
            if len(subject_clean) >= 5:
                # 件名が十分な情報を持っている場合はそれを使用
                if len(subject_clean) <= max_length:
                    return f"【{subject_clean}】"
                else:
                    return f"【{subject_clean[:max_length-2]}】"

        # 3. 名前パターンを除去（★v10.17.1追加、★v10.17.2修正: 誤除去防止）
        # 「○○（読み仮名）さん」形式を除去（括弧内がカタカナの場合のみ）
        # 例: "月宮 絵莉香（ツキミヤ エリカ）さん ありがとうございます！" → 除去
        # 例: "田中（経理部）さん への依頼内容" → 除去しない（括弧内が漢字）
        text = re.sub(
            r'^.{1,25}[\(（][ァ-ヶー\s　]+[\)）][\s　]*(さん|様|くん|ちゃん)[\s　]+',
            '', text
        )
        # シンプルな名前パターン: "田中さん " で始まる場合（挨拶が続く場合のみ）
        # 「田中さん への依頼」のような主語は残す
        text = re.sub(r'^[^\s]{1,10}(さん|様|くん|ちゃん)[\s　]+(?=お疲れ|ありがとう|いつも|よろしく)', '', text)

        # v10.25.6: URLを除去（要約表示には不要、切れると見栄えが悪い）
        text = re.sub(r'https?://[^\s]+', '', text)
        # URL除去後の「に をお願い」等の不自然なパターンを整形
        text = re.sub(r'に\s+を', 'を', text)
        text = re.sub(r'で\s+を', 'を', text)
        text = re.sub(r'と\s+を', 'を', text)
        # 勤務時間パターン付き名前を除去（★v10.17.1修正: より厳密なパターン）
        # 例: "平賀　しおり _ 月火木金9：30～13：30（変動あり）さん"
        # アンダースコア + 曜日パターンが必須
        text = re.sub(
            r'^.{1,20}[\s　]*_[\s　]*[月火水木金土日]+[0-9：:～\-（）\(\)変動あり\s]+さん[\s　]*',
            '', text
        )

        # 4. 行中・行頭の挨拶パターンを除去（★v10.17.1追加）
        inline_greetings = [
            r'^お疲れ様です[。！!]?\s*',
            r'^お疲れさまです[。！!]?\s*',
            r'^ありがとうございます[。！!]?\s*',
            r'^いつもお世話になっております[。！!]?\s*',
            r'^よろしくお願いします[。！!]?\s*',
            r'^よろしくお願いいたします[。！!]?\s*',
            r'\s+お疲れ様です[。！!]?\s*',
            r'\s+お疲れさまです[。！!]?\s*',
            r'\s+いつもお世話になっております[。！!]?\s*',
            r'\s+ありがとうございます[。！!]?\s*',
            r'\s+よろしくお願いします[。！!]?\s*',
            r'\s+よろしくお願いいたします[。！!]?\s*',
        ]
        for pattern in inline_greetings:
            text = re.sub(pattern, ' ', text, flags=re.IGNORECASE)

        # 5. 定型挨拶文を削除（remove_greetings を使用）
        text = remove_greetings(text)

        # 6. 連続スペースを1つに
        text = re.sub(r'\s{2,}', ' ', text)

        # 7. 先頭・末尾の空白を除去
        text = text.strip()

        # 空になった場合
        if not text:
            return "（タスク内容なし）"

        # 8. max_length文字以内で完結させる（途切れ防止）
        # v10.25.6: 助詞・動詞活用形の末尾削除を強化

        # 有効な接続表現（これらは完全な終わり方として認められる）
        # 短いテキストからは削除しない、長いテキストでは切り取り位置として使う
        valid_connector_phrases = ['について', 'として', 'により', 'において', 'に対して', 'に関して']

        # 途切れを示す末尾パターン（助詞、動詞活用形）
        # これらで終わる場合は不完全なので削除する
        # 優先度順: 長いパターンから先にマッチさせる
        incomplete_endings = [
            # 動詞活用形（途中で切れやすいパターン）- 接続表現は除外
            'してい', 'している', 'しており', 'されて', 'されてい',
            'なって', 'なっており', 'なってい', 'であり', 'ですが',
            'ますが', 'ません', 'ました', 'でした',
            # 2文字の動詞・助動詞末尾（不完全な活用形）
            'して', 'した', 'する', 'され', 'なり', 'なっ', 'であ',
            'です', 'ます', 'ある', 'いる', 'おり', 'くれ', 'もら',
            'でき', 'やっ', 'きた', 'きて', 'かけ', 'すれ', 'あっ',
            'しま', 'いた', 'った', 'って', 'なか', 'ない',
            # 1文字の助詞・接続・記号
            'を', 'に', 'で', 'と', 'が', 'は', 'の', 'へ', 'も',
            'て', 'た', 'し', 'り', 'け', 'き', 'ち', 'み', 'つ',
            '、', ',',  # 読点で終わるのも不完全
        ]

        def _remove_incomplete_ending(s: str, min_length: int = 3) -> str:
            """末尾の不完全なパターンを削除"""
            if not s:
                return s
            changed = True
            while changed and len(s) > min_length:
                changed = False
                for ending in incomplete_endings:
                    if s.endswith(ending):
                        s = s[:-len(ending)]
                        changed = True
                        break
            return s

        if len(text) <= max_length:
            # 短いテキスト: 有効な接続表現で終わる場合はそのまま返す
            for connector in valid_connector_phrases:
                if text.endswith(connector):
                    return text
            # 非常に短いテキスト（10文字未満）はそのまま返す
            # （ユーザーが意図的に入力した可能性が高い）
            if len(text) < 10:
                return text
            # それ以外の不完全な末尾パターンは削除
            result = _remove_incomplete_ending(text, min_length=3)
            if not result or len(result) < 3:
                return "（タスク内容なし）"
            return result

        # 途切れ防止: 自然な位置で切る
        truncated = text[:max_length]

        # 句点(。)で終わる位置を探す
        for i in range(max_length - 1, max_length // 2, -1):
            if truncated[i] == '。':
                return truncated[:i + 1]

        # 読点(、)で終わる位置を探す（読点自体は含めない - 見栄え改善）
        for i in range(max_length - 1, max_length // 2, -1):
            if truncated[i] == '、':
                # 読点の直前まで（読点で終わると不完全に見える）
                result = truncated[:i]
                # 読点前の内容が不完全でないか確認
                result = _remove_incomplete_ending(result)
                if len(result) >= 5:
                    return result
                # 不完全な場合は次の候補を探す
                continue

        # 「について」「として」等の接続表現の後で切る
        for phrase in valid_connector_phrases:
            idx = truncated.rfind(phrase)
            if idx > max_length // 3:  # 文の後半にあれば採用
                return truncated[:idx + len(phrase)]

        # 動作語の後で切る
        action_words = [
            '確認', '依頼', '報告', '対応', '作成', '提出', '送付', '連絡',
            '相談', '検討', '準備', '完了', '実施', '設定', '登録', '更新',
            '共有', '調整', '開拓', '開始', '終了', '承認', '申請', '発注',
            '手配', '配信', '配布', '発送', '受領', '受付', '返信', '回答',
        ]
        for i in range(max_length - 2, max_length // 2, -1):
            for action in action_words:
                if i + len(action) <= len(truncated) and truncated[i:i+len(action)] == action:
                    cut_pos = i + len(action)
                    if cut_pos <= max_length:
                        return truncated[:cut_pos]

        # v10.25.6: 末尾の不完全なパターンを削除
        result = _remove_incomplete_ending(truncated)

        # 結果が十分な長さならそれを返す
        if len(result) >= 5:
            return result

        # 最終手段: 切り詰めて「…」を付ける（途中で切れていることを明示）
        if len(truncated) > 3:
            return truncated[:max_length-1] + "…"

        return truncated[:max_length] if truncated else "（タスク内容なし）"

    except Exception as e:
        print(f"⚠️ prepare_task_display_text エラー: {e}")
        return text[:max_length] if len(text) > max_length else text


# =====================================================
# エクスポート
# =====================================================
__all__ = [
    # パターン定義
    "GREETING_PATTERNS",
    "CLOSING_PATTERNS",
    "GREETING_STARTS",
    "TRUNCATION_INDICATORS",
    "MID_SENTENCE_ENDINGS",  # v10.25.1追加
    # 関数
    "remove_greetings",
    "extract_task_subject",
    "is_greeting_only",
    "validate_summary",
    "clean_chatwork_tags",
    "validate_and_get_reason",
    "prepare_task_display_text",  # v10.17.0追加
]
