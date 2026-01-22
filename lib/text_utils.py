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

__version__ = "1.0.0"

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
    r'よろしくお願い(いた)?します[。！!]?\s*$',
    r'よろしくお願い(いた)?致します[。！!]?\s*$',
    r'お願い(いた)?します[。！!]?\s*$',
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
GREETING_STARTS = ['お疲れ', 'いつも', 'お世話', '夜分', 'お忙し']

# 途切れインジケータ（バリデーション用）
TRUNCATION_INDICATORS = ['…', '...', '。。', '、、']


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
    if len(summary) < 8 and len(original_body) > 50:
        return False

    # 3. 明らかに途切れている場合はNG
    if any(summary.endswith(ind) for ind in TRUNCATION_INDICATORS):
        return False

    # 4. 挨拶で始まる場合はNG
    if any(summary.startswith(g) for g in GREETING_STARTS):
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

    if len(summary) < 8 and len(original_body) > 50:
        return False, "too_short"

    if any(summary.endswith(ind) for ind in TRUNCATION_INDICATORS):
        return False, "truncated"

    if any(summary.startswith(g) for g in GREETING_STARTS):
        return False, "starts_with_greeting"

    return True, None


# =====================================================
# エクスポート
# =====================================================
__all__ = [
    # パターン定義
    "GREETING_PATTERNS",
    "CLOSING_PATTERNS",
    "GREETING_STARTS",
    "TRUNCATION_INDICATORS",
    # 関数
    "remove_greetings",
    "extract_task_subject",
    "is_greeting_only",
    "validate_summary",
    "clean_chatwork_tags",
    "validate_and_get_reason",
]
