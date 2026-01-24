import functions_framework
from flask import jsonify
from google.cloud import secretmanager, firestore
import httpx
import re
import time
from datetime import datetime, timedelta, timezone
import pg8000
import sqlalchemy
from sqlalchemy import bindparam  # v6.8.3: expanding IN対応
from google.cloud.sql.connector import Connector
import json
from functools import lru_cache
import traceback

# ★★★ v10.17.0: lib/テキスト処理ユーティリティ ★★★
# ★★★ v10.18.1: extract_task_subject, get_user_primary_department追加 ★★★
try:
    from lib import (
        clean_chatwork_tags as lib_clean_chatwork_tags,
        prepare_task_display_text as lib_prepare_task_display_text,
        remove_greetings as lib_remove_greetings,
        validate_summary as lib_validate_summary,
        extract_task_subject as lib_extract_task_subject,
        get_user_primary_department as lib_get_user_primary_department,
    )
    USE_TEXT_UTILS_LIB = True
    print("✅ lib/text_utils, lib/user_utils をロードしました")
except ImportError as e:
    USE_TEXT_UTILS_LIB = False
    print(f"⚠️ lib が見つかりません。ローカル関数を使用: {e}")

PROJECT_ID = "soulkun-production"
db = firestore.Client(project=PROJECT_ID)

# Cloud SQL設定
INSTANCE_CONNECTION_NAME = "soulkun-production:asia-northeast1:soulkun-db"
DB_NAME = "soulkun_tasks"
DB_USER = "soulkun_user"

# 会話履歴の設定
MAX_HISTORY_COUNT = 100      # 100件に増加
HISTORY_EXPIRY_HOURS = 720   # 30日（720時間）に延長

# OpenRouter設定
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# 最新モデル設定（2025年12月時点）
MODELS = {
    "default": "openai/gpt-4o",
    "commander": "openai/gpt-4o",  # 司令塔AI
}

# ボット自身の名前パターン
BOT_NAME_PATTERNS = [
    "ソウルくん", "ソウル君", "ソウル", "そうるくん", "そうる",
    "soulkun", "soul-kun", "soul"
]

# ソウルくんのaccount_id
MY_ACCOUNT_ID = "10909425"
BOT_ACCOUNT_ID = "10909425"  # Phase 1-B用

# 管理部チャットルームID
ADMIN_ROOM_ID = 405315911

# 遅延管理設定
ESCALATION_DAYS = 3  # エスカレーションまでの日数

# Cloud SQL接続プール
_pool = None
_connector = None  # グローバルConnector（接続リーク防止）

# ★★★ v6.8.2: 実行内メモリキャッシュ（N+1問題対策）★★★
_runtime_dm_cache = {}  # {account_id: room_id} - 実行中のDMルームキャッシュ
_runtime_direct_rooms = None  # get_all_rooms()の結果キャッシュ（v6.8.3では未使用だが互換性のため残す）
_runtime_contacts_cache = None  # ★★★ v6.8.3: /contacts APIの結果キャッシュ ★★★
_runtime_contacts_fetched_ok = None  # ★★★ v6.8.4: /contacts API成功フラグ（True=成功, False=失敗, None=未取得）★★★
_dm_unavailable_buffer = []  # ★★★ v6.8.3: DM不可通知のバッファ（まとめ送信用）★★★

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

# =====================================================
# ===== ★★★ v10.2.0: テストモード設定 ★★★ =====
# =====================================================
import os

# DRY_RUN モード: 実際に送信せず、ログ出力のみ
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("true", "1", "yes")

# TEST_ACCOUNT_ID: このユーザー宛のタスクのみ実際に送信（他はスキップ）
TEST_ACCOUNT_ID = os.environ.get("TEST_ACCOUNT_ID", "")

# TEST_ROOM_ID: グループチャット送信先をこのルームに差し替え
TEST_ROOM_ID = os.environ.get("TEST_ROOM_ID", "")

# カズさん（菊地雅克）のChatWork account_id（テスト時の参考用）
ADMIN_ACCOUNT_ID = "1728974"


def get_effective_admin_room():
    """テストモード時はTEST_ROOM_IDを使用、そうでなければADMIN_ROOM_IDを返す"""
    if TEST_ROOM_ID:
        return int(TEST_ROOM_ID)
    return ADMIN_ROOM_ID


def is_test_mode_active():
    """テストモードが有効かどうかを判定"""
    return DRY_RUN or TEST_ACCOUNT_ID or TEST_ROOM_ID


def log_test_mode_status():
    """起動時にテストモードの状態をログ出力"""
    if is_test_mode_active():
        print("=" * 50)
        print("⚠️ テストモード有効")
        if DRY_RUN:
            print(f"  📝 DRY_RUN=true: 送信せずログ出力のみ")
        if TEST_ACCOUNT_ID:
            print(f"  👤 TEST_ACCOUNT_ID={TEST_ACCOUNT_ID}: このユーザー宛のみ送信")
        if TEST_ROOM_ID:
            print(f"  💬 TEST_ROOM_ID={TEST_ROOM_ID}: グループ送信先を差し替え")
        print("=" * 50)


def should_send_to_account(account_id):
    """
    指定されたアカウントに実際に送信すべきかを判定

    - DRY_RUN=true → 常にFalse（送信しない）
    - TEST_ACCOUNT_ID設定あり → そのアカウントのみTrue
    - 両方未設定 → 常にTrue（通常モード）
    """
    if DRY_RUN:
        return False
    if TEST_ACCOUNT_ID:
        return str(account_id) == str(TEST_ACCOUNT_ID)
    return True


def log_dry_run_message(action_type, recipient, message_preview):
    """DRY_RUNモード時にログ出力"""
    print(f"🔸 [DRY_RUN] {action_type}")
    print(f"   宛先: {recipient}")
    print(f"   内容: {message_preview[:200]}{'...' if len(message_preview) > 200 else ''}")


# =====================================================
# ===== ★★★ v10.6.0: テスト送信ガード ★★★ =====
# =====================================================
#
# **最重要**: テスト送信は以下の2箇所のみに限定
# 1. 管理部チャット（room_id: 405315911）→ 遅延タスク報告
# 2. カズさんへのDM（account_id: 1728974）→ 個人リマインドテスト
#
# 他のグループチャットや個人に送信したら、業務に迷惑がかかる
# =====================================================

# テスト送信許可リスト
TEST_ALLOWED_ROOMS = {
    405315911,  # 管理部チャット
}

# カズさん（菊地雅克）のaccount_id
KAZU_ACCOUNT_ID = 1728974

# テストモードフラグ（本番稼働時はFalseに変更）
REMINDER_TEST_MODE = False  # ★★★ v10.10.0: 本番稼働開始 - 全スタッフにリマインド送信 ★★★


def is_test_send_allowed(room_id: int = None, account_id: int = None) -> bool:
    """
    テスト送信が許可されているか確認

    REMINDER_TEST_MODE=True の場合:
    - room_id が TEST_ALLOWED_ROOMS に含まれる → True
    - account_id が KAZU_ACCOUNT_ID と一致 → True
    - それ以外 → False（送信しない）

    REMINDER_TEST_MODE=False の場合:
    - 常にTrue（本番モード）
    """
    if not REMINDER_TEST_MODE:
        return True  # 本番モードは全て許可

    if room_id and int(room_id) in TEST_ALLOWED_ROOMS:
        return True
    if account_id and int(account_id) == KAZU_ACCOUNT_ID:
        return True
    return False


def send_reminder_with_test_guard(room_id: int, message: str, account_id: int = None) -> bool:
    """
    テストガード付きでメッセージを送信（リトライ対応）

    ★★★ v10.13.2: リトライ・レート制限対応追加 ★★★

    許可されていない宛先には送信せず、ログ出力のみ行う
    - 最大3回リトライ（指数バックオフ: 1秒、2秒、4秒）
    - 429（レート制限）時は60秒待機してリトライ
    - 送信後200ms待機（レート制限予防）
    """
    if not is_test_send_allowed(room_id, account_id):
        print(f"🚫 [TEST_GUARD] 送信をブロック: room_id={room_id}, account_id={account_id}")
        print(f"   理由: REMINDER_TEST_MODE=True で許可リストに含まれていません")
        print(f"   メッセージ（先頭100文字）: {message[:100]}...")
        return False

    # リトライ設定
    max_retries = 3
    base_delay = 1.0  # 秒（指数バックオフの基準）
    rate_limit_retries = 0  # 429専用カウンター
    max_rate_limit_retries = 3  # 429も最大3回まで

    for attempt in range(max_retries):
        try:
            url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
            headers = {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}
            data = {'body': message}
            response = httpx.post(url, headers=headers, data=data, timeout=10.0)

            if response.status_code == 200:
                print(f"✅ メッセージ送信成功: room_id={room_id}")
                # レート制限予防のため200ms待機
                time.sleep(0.2)
                return True
            elif response.status_code == 429:
                # レート制限 - 60秒待機してリトライ（最大3回）
                rate_limit_retries += 1
                if rate_limit_retries >= max_rate_limit_retries:
                    print(f"❌ レート制限（429）が{max_rate_limit_retries}回連続: room_id={room_id}, 諦めます")
                    return False
                print(f"⚠️ レート制限（429）: room_id={room_id}, 60秒待機後リトライ ({rate_limit_retries}/{max_rate_limit_retries})")
                time.sleep(60)
                continue
            elif response.status_code >= 500:
                # サーバーエラー - リトライ
                delay = base_delay * (2 ** attempt)
                print(f"⚠️ サーバーエラー（{response.status_code}）: room_id={room_id}, {delay}秒後リトライ ({attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue
            else:
                # その他のエラー（4xx系）はリトライしない
                print(f"❌ メッセージ送信失敗: room_id={room_id}, status={response.status_code}")
                return False

        except httpx.TimeoutException:
            delay = base_delay * (2 ** attempt)
            print(f"⚠️ タイムアウト: room_id={room_id}, {delay}秒後リトライ ({attempt + 1}/{max_retries})")
            time.sleep(delay)
            continue
        except Exception as e:
            delay = base_delay * (2 ** attempt)
            print(f"⚠️ 送信エラー: room_id={room_id}, error={e}, {delay}秒後リトライ ({attempt + 1}/{max_retries})")
            time.sleep(delay)
            continue

    # 全リトライ失敗
    print(f"❌ メッセージ送信失敗（リトライ上限）: room_id={room_id}")
    return False


# =====================================================
# ===== ★★★ v10.6.0: タスク本文クリーニング強化 ★★★ =====
# =====================================================

def clean_task_body(body: str) -> str:
    """
    タスク本文からChatWorkのタグや記号を完全に除去

    ★★★ v10.6.1: 引用ブロック処理改善 ★★★

    v10.6.0の問題:
    - 引用ブロック全体を削除していたため、本文が引用のみの場合に空になっていた

    v10.6.1の改善:
    - 引用外のテキストがあればそれを優先使用
    - 引用のみの場合は、引用内のテキストを抽出して使用

    除去対象:
    - [qt][qtmeta aid=xxx time=xxx]...[/qt] 形式の引用
    - [qtmeta ...] タグ
    - [qt] [/qt] の単独タグ
    - [To:xxx] タグ
    - [piconname:xxx] タグ
    - [info]...[/info] タグ（内容は残す）
    - [rp aid=xxx to=xxx-xxx] タグ
    - [dtext:xxx] タグ
    - その他の ChatWork タグ

    TODO: Phase 3.5でlib/に共通化予定
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
        # 小文字のタグ名 + オプションのパラメータ
        body = re.sub(r'\[/?[a-z]+(?::[^\]]+)?\]', '', body, flags=re.IGNORECASE)

        # 13. 連続する改行を整理（3つ以上の改行を2つに）
        body = re.sub(r'\n{3,}', '\n\n', body)

        # 14. 連続するスペースを整理
        body = re.sub(r' {2,}', ' ', body)

        # 15. 行頭・行末の空白を除去
        body = '\n'.join(line.strip() for line in body.split('\n'))

        # 16. 前後の空白を除去
        body = body.strip()

        return body

    except Exception as e:
        print(f"⚠️ clean_task_body エラー: {e}")
        return body  # エラー時は元のメッセージを返す


def prepare_task_display_text(text: str, max_length: int = 40) -> str:
    """
    報告用のタスク表示テキストを整形する（フォールバック版）

    ★★★ v10.17.1: lib/text_utils.py と同等の機能を提供 ★★★

    処理内容:
    1. 改行を半角スペースに置換（1行にまとめる）
    2. 【件名】があれば優先抽出
    3. 名前パターン（○○さん）を除去
    4. 行中の挨拶パターンを除去
    5. 定型挨拶文を削除
    6. 連続スペースを1つに
    7. 先頭・末尾の空白を除去
    8. max_length文字以内で完結させる（途切れ防止）

    Args:
        text: 元のテキスト（summaryまたはclean_task_body()後のbody）
        max_length: 最大文字数（デフォルト40）

    Returns:
        整形済みテキスト（途中で途切れない）
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
        text = re.sub(
            r'^.{1,25}[\(（][ァ-ヶー\s　]+[\)）][\s　]*(さん|様|くん|ちゃん)[\s　]+',
            '', text
        )
        # シンプルな名前パターン: "田中さん " で始まる場合（挨拶が続く場合のみ）
        text = re.sub(r'^[^\s]{1,10}(さん|様|くん|ちゃん)[\s　]+(?=お疲れ|ありがとう|いつも|よろしく)', '', text)
        # 勤務時間パターン付き名前を除去（アンダースコア + 曜日パターンが必須）
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

        # 5. 定型挨拶文を削除（lib/text_utils.py GREETING_PATTERNS と同期）
        greeting_patterns = [
            # 開始の挨拶
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
            # お詫び・断り
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
            # メール形式ヘッダー
            r'^[Rr][Ee]:\s*',
            r'^[Ff][Ww][Dd]?:\s*',
            r'^[Cc][Cc]:\s*',
        ]
        # 複数回試行（ネストした挨拶対応）
        for _ in range(3):
            original = text
            for pattern in greeting_patterns:
                text = re.sub(pattern, '', text, flags=re.IGNORECASE)
            if text == original:
                break

        # 終了の挨拶を除去
        closing_patterns = [
            r'よろしくお願い(いた)?します[。！!]?\s*$',
            r'お願い(いた)?します[。！!]?\s*$',
            r'ご確認(の程)?よろしくお願い(いた)?します[。！!]?\s*$',
            r'以上、?よろしくお願い(いた)?します[。！!]?\s*$',
            r'以上です[。！!]?\s*$',
        ]
        for pattern in closing_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        # 6. 連続スペースを1つに
        text = re.sub(r'\s{2,}', ' ', text)

        # 7. 先頭・末尾の空白を除去
        text = text.strip()

        # 空になった場合
        if not text:
            return "（タスク内容なし）"

        # 8. max_length文字以内で完結させる（途切れ防止）
        if len(text) <= max_length:
            return text

        # 途切れ防止: 自然な位置で切る
        truncated = text[:max_length]

        # 句点(。)で終わる位置を探す
        for i in range(max_length - 1, max_length // 2, -1):
            if truncated[i] == '。':
                return truncated[:i + 1]

        # 読点(、)で終わる位置を探す
        for i in range(max_length - 1, max_length // 2, -1):
            if truncated[i] == '、':
                return truncated[:i + 1]

        # 助詞の後で切る
        particles = ['を', 'に', 'で', 'と', 'が', 'は', 'の', 'へ', 'も']
        for i in range(max_length - 1, max_length // 2, -1):
            if truncated[i] in particles:
                return truncated[:i + 1]

        # 動作語の後で切る
        action_words = ['確認', '依頼', '報告', '対応', '作成', '提出', '送付', '連絡', '相談', '検討', '準備', '完了', '実施', '設定', '登録', '更新', '共有', '調整']
        for i in range(max_length - 2, max_length // 2, -1):
            for action in action_words:
                if i + len(action) <= len(truncated) and truncated[i:i+len(action)] == action:
                    cut_pos = i + len(action)
                    if cut_pos <= max_length:
                        return truncated[:cut_pos]

        # 最終手段: max_length-2文字 + 動作語で終わらせる
        return truncated[:max_length - 2] + "対応"

    except Exception as e:
        print(f"⚠️ prepare_task_display_text エラー: {e}")
        return text[:max_length] if len(text) > max_length else text


# =====================================================
# ===== 機能カタログ（SYSTEM_CAPABILITIES） =====
# =====================================================
# 
# 【設計思想】
# - 新機能追加時はこのカタログに1エントリ追加するだけ
# - AI司令塔はこのカタログを読んで、自分の能力を把握する
# - execute_actionはカタログを参照して動的に機能を実行
#
# 【将来の拡張】
# - enabled=False の機能は実装後にTrueに変更
# - 新機能はこのカタログに追加するだけでAIが認識
# =====================================================

SYSTEM_CAPABILITIES = {
    # ===== タスク管理 =====
    "chatwork_task_create": {
        "name": "ChatWorkタスク作成",
        "description": "ChatWorkで指定した担当者にタスクを作成する。タスクの追加、作成、依頼、お願いなどの要望に対応。",
        "category": "task",
        "enabled": True,
        "trigger_examples": [
            "〇〇さんに△△のタスクを追加して",
            "〇〇に△△をお願いして、期限は明日",
            "俺に△△のタスク作成して",
            "タスク依頼：〇〇さんに△△",
        ],
        "params_schema": {
            "assigned_to": {
                "type": "string",
                "description": "担当者名（ChatWorkユーザー一覧から正確な名前を選択）",
                "required": True,
                "source": "chatwork_users",
                "note": "「俺」「自分」「私」「僕」の場合は「依頼者自身」と出力"
            },
            "task_body": {
                "type": "string", 
                "description": "タスクの内容",
                "required": True
            },
            "limit_date": {
                "type": "date",
                "description": "期限日（YYYY-MM-DD形式）",
                "required": True,
                "note": "「明日」→翌日、「明後日」→2日後、「来週金曜」→該当日に変換。期限の指定がない場合は必ずユーザーに確認"
            },
            "limit_time": {
                "type": "time",
                "description": "期限時刻（HH:MM形式）",
                "required": False
            }
        },
        "handler": "handle_chatwork_task_create",
        "requires_confirmation": False,
        "required_data": ["chatwork_users", "sender_name"]
    },
    
    "chatwork_task_complete": {
        "name": "ChatWorkタスク完了",
        "description": "タスクを完了状態にする。「完了にして」「終わった」などの要望に対応。番号指定またはタスク内容で特定。",
        "category": "task",
        "enabled": True,
        "trigger_examples": [
            "1のタスクを完了にして",
            "タスク1を完了",
            "資料作成のタスク完了にして",
            "さっきのタスク終わった",
        ],
        "params_schema": {
            "task_identifier": {
                "type": "string",
                "description": "タスクを特定する情報（番号、タスク内容の一部、または「さっきの」など）",
                "required": True
            }
        },
        "handler": "handle_chatwork_task_complete",
        "requires_confirmation": False,
        "required_data": ["recent_tasks_context"]
    },
    
    "chatwork_task_search": {
        "name": "タスク検索",
        "description": "特定の人のタスクや、自分のタスクを検索して表示する。「〇〇のタスク」「自分のタスク」「未完了のタスク」などの要望に対応。",
        "category": "task",
        "enabled": True,
        "trigger_examples": [
            "崇樹のタスク教えて",
            "自分のタスク教えて",
            "俺のタスク何がある？",
            "未完了のタスク一覧",
            "〇〇さんが抱えてるタスク",
        ],
        "params_schema": {
            "person_name": {
                "type": "string",
                "description": "タスクを検索する人物名。「自分」「俺」「私」の場合は「sender」と出力",
                "required": False
            },
            "status": {
                "type": "string",
                "description": "タスクの状態（open/done/all）",
                "required": False,
                "default": "open"
            },
            "assigned_by": {
                "type": "string",
                "description": "タスクを依頼した人物名（〇〇から振られたタスク）",
                "required": False
            }
        },
        "handler": "handle_chatwork_task_search",
        "requires_confirmation": False,
        "required_data": ["chatwork_users", "sender_name"]
    },
    
    # ===== 記憶機能 =====
    "save_memory": {
        "name": "人物情報を記憶",
        "description": "人物の情報（部署、役職、趣味、特徴など）を記憶する。「〇〇さんは△△です」のような情報を覚える。",
        "category": "memory",
        "enabled": True,
        "trigger_examples": [
            "〇〇さんは営業部の部長です",
            "〇〇さんの趣味はゴルフだよ",
            "〇〇さんを覚えて、△△担当の人",
            "〇〇は□□出身だって",
        ],
        "params_schema": {
            "attributes": {
                "type": "array",
                "description": "記憶する属性のリスト",
                "required": True,
                "items_schema": {
                    "person": "人物名",
                    "type": "属性タイプ（部署/役職/趣味/住所/特徴/メモ/読み/あだ名/その他）",
                    "value": "属性の値"
                }
            }
        },
        "handler": "handle_save_memory",
        "requires_confirmation": False,
        "required_data": []
    },
    
    "query_memory": {
        "name": "人物情報を検索",
        "description": "記憶している人物の情報を検索・表示する。特定の人について聞かれた時や、覚えている人全員を聞かれた時に使用。",
        "category": "memory",
        "enabled": True,
        "trigger_examples": [
            "〇〇さんについて教えて",
            "〇〇さんのこと知ってる？",
            "誰を覚えてる？",
            "覚えている人を全員教えて",
        ],
        "params_schema": {
            "persons": {
                "type": "array",
                "description": "検索したい人物名のリスト",
                "required": False
            },
            "is_all_persons": {
                "type": "boolean",
                "description": "全員の情報を取得するかどうか",
                "required": False,
                "default": False
            }
        },
        "handler": "handle_query_memory",
        "requires_confirmation": False,
        "required_data": ["all_persons"]
    },
    
    "delete_memory": {
        "name": "人物情報を削除",
        "description": "記憶している人物の情報を削除する。忘れてほしいと言われた時に使用。",
        "category": "memory",
        "enabled": True,
        "trigger_examples": [
            "〇〇さんのことを忘れて",
            "〇〇さんの記憶を削除して",
            "〇〇の情報を消して",
        ],
        "params_schema": {
            "persons": {
                "type": "array",
                "description": "削除したい人物名のリスト",
                "required": True
            }
        },
        "handler": "handle_delete_memory",
        "requires_confirmation": False,
        "required_data": []
    },
    
    # ===== 一般会話 =====
    "general_chat": {
        "name": "一般会話",
        "description": "上記のどの機能にも当てはまらない一般的な会話、質問、雑談、挨拶などに対応。",
        "category": "chat",
        "enabled": True,
        "trigger_examples": [
            "こんにちは",
            "ありがとう",
            "〇〇について教えて",
            "どう思う？",
        ],
        "params_schema": {},
        "handler": "handle_general_chat",
        "requires_confirmation": False,
        "required_data": []
    },
    
    # ===== 将来の機能（enabled=False） =====
    
    "create_document": {
        "name": "資料作成",
        "description": "Google Docsで資料を作成する（議事録、報告書、企画書など）",
        "category": "document",
        "enabled": False,  # 将来実装
        "trigger_examples": [
            "〇〇の資料を作成して",
            "議事録を作って",
            "報告書を書いて",
        ],
        "params_schema": {
            "document_type": {"type": "string", "description": "資料の種類"},
            "title": {"type": "string", "description": "タイトル"},
            "content_outline": {"type": "string", "description": "内容の概要"},
        },
        "handler": "handle_create_document",
        "requires_confirmation": True,
        "required_data": ["google_docs_api"]
    },
    
    "query_company_knowledge": {
        "name": "会社知識の参照",
        "description": "会社の理念、マニュアル、ルールを参照して回答する",
        "category": "knowledge",
        "enabled": False,  # 将来実装
        "trigger_examples": [
            "うちの会社の理念って何？",
            "経費精算のルールを教えて",
            "〇〇のマニュアルを教えて",
        ],
        "params_schema": {
            "query": {"type": "string", "description": "検索したい内容"},
        },
        "handler": "handle_query_company_knowledge",
        "requires_confirmation": False,
        "required_data": ["company_knowledge_base"]
    },
    
    "generate_image": {
        "name": "画像生成",
        "description": "AIで画像を生成する",
        "category": "creative",
        "enabled": False,  # 将来実装
        "trigger_examples": [
            "〇〇の画像を作って",
            "こんなイメージの絵を描いて",
        ],
        "params_schema": {
            "prompt": {"type": "string", "description": "画像の説明"},
            "style": {"type": "string", "description": "スタイル"},
        },
        "handler": "handle_generate_image",
        "requires_confirmation": False,
        "required_data": ["image_generation_api"]
    },
    
    "schedule_management": {
        "name": "スケジュール管理",
        "description": "Googleカレンダーと連携してスケジュールを管理する",
        "category": "schedule",
        "enabled": False,  # 将来実装
        "trigger_examples": [
            "明日の予定を教えて",
            "〇〇の会議を入れて",
            "来週の空いてる時間は？",
        ],
        "params_schema": {
            "action": {"type": "string", "description": "操作（view/create/update/delete）"},
            "date": {"type": "date", "description": "日付"},
            "title": {"type": "string", "description": "予定のタイトル"},
        },
        "handler": "handle_schedule_management",
        "requires_confirmation": True,
        "required_data": ["google_calendar_api"]
    },
}


# =====================================================
# ===== 機能カタログからプロンプトを動的生成 =====
# =====================================================

def generate_capabilities_prompt(capabilities, chatwork_users=None, sender_name=None):
    """
    機能カタログからAI司令塔用のプロンプトを自動生成する
    
    【設計思想】
    - カタログを追加するだけでAIが新機能を認識
    - enabled=Trueの機能のみプロンプトに含める
    - 各機能の使い方をAIに理解させる
    """
    
    prompt_parts = []
    
    # 有効な機能のみ抽出
    enabled_capabilities = {
        cap_id: cap for cap_id, cap in capabilities.items() 
        if cap.get("enabled", True)
    }
    
    for cap_id, cap in enabled_capabilities.items():
        # パラメータスキーマを整形
        params_lines = []
        for param_name, param_info in cap.get("params_schema", {}).items():
            if isinstance(param_info, dict):
                desc = param_info.get("description", "")
                required = "【必須】" if param_info.get("required", False) else "（任意）"
                note = f" ※{param_info.get('note')}" if param_info.get("note") else ""
                params_lines.append(f'    "{param_name}": "{desc}"{required}{note}')
            else:
                params_lines.append(f'    "{param_name}": "{param_info}"')
        
        params_json = "{\n" + ",\n".join(params_lines) + "\n  }" if params_lines else "{}"
        
        # トリガー例を整形
        examples = "\n".join([f"  - 「{ex}」" for ex in cap.get("trigger_examples", [])])
        
        section = f"""
### {cap["name"]} (action: "{cap_id}")
{cap["description"]}

**こんな時に使う：**
{examples}

**パラメータ：**
```json
{params_json}
```
"""
        prompt_parts.append(section)
    
    return "\n".join(prompt_parts)


def get_enabled_capabilities():
    """有効な機能の一覧を取得"""
    return {
        cap_id: cap for cap_id, cap in SYSTEM_CAPABILITIES.items() 
        if cap.get("enabled", True)
    }


def get_capability_info(action_name):
    """指定されたアクションの機能情報を取得"""
    return SYSTEM_CAPABILITIES.get(action_name)

# ChatWork API ヘッダー取得関数
def get_chatwork_headers():
    return {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}

HEADERS = None  # 遅延初期化用

def get_connector():
    """グローバルConnectorを取得（接続リーク防止）"""
    global _connector
    if _connector is None:
        _connector = Connector()
    return _connector

# Phase 1-B用: pg8000接続を返す関数
def get_db_connection():
    connector = get_connector()
    conn = connector.connect(
        INSTANCE_CONNECTION_NAME,
        "pg8000",
        user=DB_USER,
        password=get_db_password(),
        db=DB_NAME,
    )
    return conn

def get_db_password():
    return get_secret("cloudsql-password")

def get_pool():
    global _pool
    if _pool is None:
        connector = get_connector()
        def getconn():
            return connector.connect(
                INSTANCE_CONNECTION_NAME, "pg8000",
                user=DB_USER, password=get_db_password(), db=DB_NAME,
            )
        _pool = sqlalchemy.create_engine(
            "postgresql+pg8000://", creator=getconn,
            pool_size=5, max_overflow=2, pool_timeout=30, pool_recycle=1800,
        )
    return _pool

@lru_cache(maxsize=32)
def get_secret(secret_id):
    """Secret Managerからシークレットを取得（キャッシュ付き）"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

def clean_chatwork_message(body):
    """ChatWorkメッセージをクリーニング
    
    堅牢なエラーハンドリング版
    """
    # Noneチェック
    if body is None:
        return ""
    
    # 型チェック
    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return ""
    
    # 空文字チェック
    if not body:
        return ""
    
    try:
        clean_message = body
        clean_message = re.sub(r'\[To:\d+\]\s*[^\n\[]*(?:さん|くん|ちゃん|様|氏)?', '', clean_message)
        clean_message = re.sub(r'\[rp aid=\d+[^\]]*\]\[/rp\]', '', clean_message)  # より柔軟なパターン
        clean_message = re.sub(r'\[/?[a-zA-Z]+\]', '', clean_message)
        clean_message = re.sub(r'\[.*?\]', '', clean_message)
        clean_message = clean_message.strip()
        clean_message = re.sub(r'\s+', ' ', clean_message)
        return clean_message
    except Exception as e:
        print(f"⚠️ clean_chatwork_message エラー: {e}")
        return body  # エラー時は元のメッセージを返す


def is_mention_or_reply_to_soulkun(body):
    """ソウルくんへのメンションまたは返信かどうかを判断

    堅牢なエラーハンドリング版
    """
    # Noneチェック
    if body is None:
        return False

    # 型チェック
    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return False

    # 空文字チェック
    if not body:
        return False

    try:
        # メンションパターン
        if f"[To:{MY_ACCOUNT_ID}]" in body:
            return True

        # 返信ボタンパターン: [rp aid=10909425 to=...]
        # 修正: [/rp]のチェックを削除（実際のフォーマットには含まれない）
        if f"[rp aid={MY_ACCOUNT_ID}" in body:
            return True

        return False
    except Exception as e:
        print(f"⚠️ is_mention_or_reply_to_soulkun エラー: {e}")
        return False


def is_toall_mention(body):
    """オールメンション（[toall]）かどうかを判定

    オールメンションはアナウンス用途で使われるため、
    ソウルくんは反応しない。

    v10.16.0で追加

    Args:
        body: メッセージ本文

    Returns:
        bool: [toall]が含まれていればTrue
    """
    # Noneチェック
    if body is None:
        return False

    # 型チェック
    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return False

    # 空文字チェック
    if not body:
        return False

    try:
        # ChatWorkのオールメンションパターン: [toall]
        # 大文字小文字を区別しない（念のため）
        if "[toall]" in body.lower():
            return True

        return False
    except Exception as e:
        print(f"⚠️ is_toall_mention エラー: {e}")
        return False


# ===== データベース操作関数 =====

def get_or_create_person(name):
    pool = get_pool()
    with pool.begin() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
            {"name": name}
        ).fetchone()
        if result:
            return result[0]
        result = conn.execute(
            sqlalchemy.text("INSERT INTO persons (name) VALUES (:name) RETURNING id"),
            {"name": name}
        )
        return result.fetchone()[0]

def save_person_attribute(person_name, attribute_type, attribute_value, source="conversation"):
    person_id = get_or_create_person(person_name)
    pool = get_pool()
    with pool.begin() as conn:
        conn.execute(
            sqlalchemy.text("""
                INSERT INTO person_attributes (person_id, attribute_type, attribute_value, source, updated_at)
                VALUES (:person_id, :attr_type, :attr_value, :source, CURRENT_TIMESTAMP)
                ON CONFLICT (person_id, attribute_type) 
                DO UPDATE SET attribute_value = :attr_value, source = :source, updated_at = CURRENT_TIMESTAMP
            """),
            {"person_id": person_id, "attr_type": attribute_type, "attr_value": attribute_value, "source": source}
        )
    return True

def get_person_info(person_name):
    pool = get_pool()
    with pool.connect() as conn:
        person_result = conn.execute(
            sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
            {"name": person_name}
        ).fetchone()
        if not person_result:
            return None
        person_id = person_result[0]
        attributes = conn.execute(
            sqlalchemy.text("""
                SELECT attribute_type, attribute_value FROM person_attributes 
                WHERE person_id = :person_id ORDER BY updated_at DESC
            """),
            {"person_id": person_id}
        ).fetchall()
        return {
            "name": person_name,
            "attributes": [{"type": a[0], "value": a[1]} for a in attributes]
        }

def normalize_person_name(name):
    """
    ★★★ v6.8.6: 人物名を正規化 ★★★
    
    ChatWorkのユーザー名形式「高野　義浩 (タカノ ヨシヒロ)」を
    DBの形式「高野義浩」に変換する
    """
    if not name:
        return name
    
    import re
    
    # 1. 読み仮名部分 (xxx) を除去
    normalized = re.sub(r'\s*\([^)]*\)\s*', '', name)
    
    # 2. 敬称を除去
    normalized = re.sub(r'(さん|くん|ちゃん|様|氏)$', '', normalized)
    
    # 3. スペース（全角・半角）を除去
    normalized = normalized.replace(' ', '').replace('　', '')
    
    print(f"   📝 名前正規化: '{name}' → '{normalized}'")
    
    return normalized.strip()


def search_person_by_partial_name(partial_name):
    """部分一致で人物を検索"""
    # ★★★ v6.8.6: 検索前に名前を正規化 ★★★
    normalized = normalize_person_name(partial_name) if partial_name else partial_name
    
    pool = get_pool()
    with pool.connect() as conn:
        # 正規化した名前と元の名前の両方で検索
        result = conn.execute(
            sqlalchemy.text("""
                SELECT name FROM persons 
                WHERE name ILIKE :pattern 
                   OR name ILIKE :pattern2
                   OR name ILIKE :normalized_pattern
                ORDER BY 
                    CASE WHEN name = :exact THEN 0
                         WHEN name = :normalized THEN 0
                         WHEN name ILIKE :starts_with THEN 1
                         ELSE 2 END,
                    LENGTH(name)
                LIMIT 5
            """),
            {
                "pattern": f"%{partial_name}%",
                "pattern2": f"%{partial_name}%",
                "normalized_pattern": f"%{normalized}%",
                "exact": partial_name,
                "normalized": normalized,
                "starts_with": f"{partial_name}%"
            }
        ).fetchall()
        print(f"   🔍 search_person_by_partial_name: '{partial_name}' (normalized: '{normalized}') → {len(result)}件")
        return [r[0] for r in result]

def delete_person(person_name):
    pool = get_pool()
    with pool.connect() as conn:
        trans = conn.begin()
        try:
            person_result = conn.execute(
                sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
                {"name": person_name}
            ).fetchone()
            if not person_result:
                trans.rollback()
                return False
            person_id = person_result[0]
            conn.execute(sqlalchemy.text("DELETE FROM person_attributes WHERE person_id = :person_id"), {"person_id": person_id})
            conn.execute(sqlalchemy.text("DELETE FROM person_events WHERE person_id = :person_id"), {"person_id": person_id})
            conn.execute(sqlalchemy.text("DELETE FROM persons WHERE id = :person_id"), {"person_id": person_id})
            trans.commit()
            return True
        except Exception as e:
            trans.rollback()
            print(f"削除エラー: {e}")
            return False

def get_all_persons_summary():
    pool = get_pool()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                SELECT p.name, STRING_AGG(pa.attribute_type || '=' || pa.attribute_value, ', ') as attributes
                FROM persons p
                LEFT JOIN person_attributes pa ON p.id = pa.person_id
                GROUP BY p.id, p.name ORDER BY p.name
            """)
        ).fetchall()
        return [{"name": r[0], "attributes": r[1]} for r in result]


def get_all_chatwork_users():
    """ChatWorkユーザー一覧を取得（AI司令塔用）"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT DISTINCT account_id, name 
                    FROM chatwork_users 
                    WHERE name IS NOT NULL AND name != ''
                    ORDER BY name
                """)
            ).fetchall()
            return [{"account_id": row[0], "name": row[1]} for row in result]
    except Exception as e:
        print(f"ChatWorkユーザー取得エラー: {e}")
        return []

# ===== タスク管理 =====

def add_task(title, description=None, priority=0, due_date=None):
    pool = get_pool()
    with pool.begin() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                INSERT INTO tasks (title, description, priority, due_date)
                VALUES (:title, :description, :priority, :due_date) RETURNING id
            """),
            {"title": title, "description": description, "priority": priority, "due_date": due_date}
        )
        return result.fetchone()[0]

def get_tasks(status=None):
    pool = get_pool()
    with pool.connect() as conn:
        if status:
            result = conn.execute(
                sqlalchemy.text("SELECT id, title, status, priority, due_date FROM tasks WHERE status = :status ORDER BY priority DESC, created_at DESC"),
                {"status": status}
            )
        else:
            result = conn.execute(
                sqlalchemy.text("SELECT id, title, status, priority, due_date FROM tasks ORDER BY priority DESC, created_at DESC")
            )
        return result.fetchall()

def update_task_status(task_id, status):
    pool = get_pool()
    with pool.begin() as conn:
        conn.execute(
            sqlalchemy.text("UPDATE tasks SET status = :status, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
            {"status": status, "id": task_id}
        )

def delete_task(task_id):
    pool = get_pool()
    with pool.begin() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})

# ===== ChatWorkタスク機能 =====

def get_chatwork_account_id_by_name(name):
    """担当者名からChatWorkアカウントIDを取得（敬称除去・スペース正規化対応）"""
    pool = get_pool()
    
    # ★ 敬称を除去（さん、くん、ちゃん、様、氏）
    clean_name = re.sub(r'(さん|くん|ちゃん|様|氏)$', '', name.strip())
    # ★ スペースを除去して正規化（半角・全角両方）
    normalized_name = clean_name.replace(' ', '').replace('　', '')
    print(f"👤 担当者検索: 入力='{name}' → クリーニング後='{clean_name}' → 正規化='{normalized_name}'")
    
    with pool.connect() as conn:
        # 完全一致で検索（クリーニング後の名前）
        result = conn.execute(
            sqlalchemy.text("SELECT account_id FROM chatwork_users WHERE name = :name LIMIT 1"),
            {"name": clean_name}
        ).fetchone()
        if result:
            print(f"✅ 完全一致で発見: {clean_name} → {result[0]}")
            return result[0]
        
        # 部分一致で検索（クリーニング後の名前）
        result = conn.execute(
            sqlalchemy.text("SELECT account_id, name FROM chatwork_users WHERE name ILIKE :pattern LIMIT 1"),
            {"pattern": f"%{clean_name}%"}
        ).fetchone()
        if result:
            print(f"✅ 部分一致で発見: {clean_name} → {result[0]} ({result[1]})")
            return result[0]
        
        # ★ スペース除去して正規化した名前で検索（NEW）
        # DBの名前からもスペースを除去して比較
        result = conn.execute(
            sqlalchemy.text("""
                SELECT account_id, name FROM chatwork_users 
                WHERE REPLACE(REPLACE(name, ' ', ''), '　', '') ILIKE :pattern 
                LIMIT 1
            """),
            {"pattern": f"%{normalized_name}%"}
        ).fetchone()
        if result:
            print(f"✅ 正規化検索で発見: {normalized_name} → {result[0]} ({result[1]})")
            return result[0]
        
        # 元の名前でも検索（念のため）
        if clean_name != name:
            result = conn.execute(
                sqlalchemy.text("SELECT account_id, name FROM chatwork_users WHERE name ILIKE :pattern LIMIT 1"),
                {"pattern": f"%{name}%"}
            ).fetchone()
            if result:
                print(f"✅ 元の名前で部分一致: {name} → {result[0]} ({result[1]})")
                return result[0]
        
        print(f"❌ 担当者が見つかりません: {name} (クリーニング後: {clean_name}, 正規化: {normalized_name})")
        return None

def create_chatwork_task(room_id, task_body, assigned_to_account_id, limit=None):
    """ChatWork APIでタスクを作成"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks"
    
    data = {
        "body": task_body,
        "to_ids": str(assigned_to_account_id)
    }
    
    if limit:
        data["limit"] = limit
    
    print(f"📤 ChatWork API リクエスト: URL={url}, data={data}")
    
    try:
        response = httpx.post(
            url,
            headers={"X-ChatWorkToken": api_token},
            data=data,
            timeout=10.0
        )
        print(f"📥 ChatWork API レスポンス: status={response.status_code}, body={response.text}")
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"ChatWork API エラー: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"ChatWork API 例外: {e}")
        return None


def complete_chatwork_task(room_id, task_id):
    """ChatWork APIでタスクを完了にする"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks/{task_id}/status"
    
    print(f"📤 ChatWork API タスク完了リクエスト: URL={url}")
    
    try:
        response = httpx.put(
            url,
            headers={"X-ChatWorkToken": api_token},
            data={"body": "done"},
            timeout=10.0
        )
        print(f"📥 ChatWork API レスポンス: status={response.status_code}, body={response.text}")
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"ChatWork API エラー: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"ChatWork API 例外: {e}")
        return None


def search_tasks_from_db(room_id, assigned_to_account_id=None, assigned_by_account_id=None, status="open"):
    """DBからタスクを検索"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            # クエリ構築
            query = """
                SELECT task_id, body, limit_time, status, assigned_to_account_id, assigned_by_account_id
                FROM chatwork_tasks
                WHERE room_id = :room_id
            """
            params = {"room_id": room_id}
            
            if assigned_to_account_id:
                query += " AND assigned_to_account_id = :assigned_to"
                params["assigned_to"] = assigned_to_account_id
            
            if assigned_by_account_id:
                query += " AND assigned_by_account_id = :assigned_by"
                params["assigned_by"] = assigned_by_account_id
            
            if status and status != "all":
                query += " AND status = :status"
                params["status"] = status
            
            query += " ORDER BY limit_time ASC NULLS LAST"
            
            result = conn.execute(sqlalchemy.text(query), params)
            tasks = result.fetchall()
            
            return [
                {
                    "task_id": row[0],
                    "body": row[1],
                    "limit_time": row[2],
                    "status": row[3],
                    "assigned_to_account_id": row[4],
                    "assigned_by_account_id": row[5]
                }
                for row in tasks
            ]
    except Exception as e:
        print(f"タスク検索エラー: {e}")
        return []


def update_task_status_in_db(task_id, status):
    """DBのタスクステータスを更新"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    UPDATE chatwork_tasks SET status = :status WHERE task_id = :task_id
                """),
                {"task_id": task_id, "status": status}
            )
        print(f"✅ タスクステータス更新: task_id={task_id}, status={status}")
        return True
    except Exception as e:
        print(f"タスクステータス更新エラー: {e}")
        traceback.print_exc()
        return False


def save_chatwork_task_to_db(task_id, room_id, assigned_by_account_id, assigned_to_account_id, body, limit_time):
    """
    ChatWorkタスクをデータベースに保存（明示的なパラメータで受け取る）

    v10.18.1: summary生成、department_id追加（Phase 3.5対応）
    """
    try:
        pool = get_pool()

        # ★★★ v10.18.1: summary生成（3段階フォールバック）★★★
        summary = None
        if USE_TEXT_UTILS_LIB and body:
            try:
                # 1. extract_task_subject で件名抽出を試みる
                summary = lib_extract_task_subject(body)
                if not lib_validate_summary(summary):
                    # 2. prepare_task_display_text で表示用テキスト生成
                    summary = lib_prepare_task_display_text(body, max_length=50)
                if not lib_validate_summary(summary):
                    # 3. 最終フォールバック: 本文の先頭40文字
                    cleaned = lib_clean_chatwork_tags(body)
                    summary = cleaned[:40] + "..." if len(cleaned) > 40 else cleaned
                print(f"📝 summary生成: {summary[:30]}...")
            except Exception as e:
                print(f"⚠️ summary生成エラー（処理続行）: {e}")
                summary = body[:40] + "..." if body and len(body) > 40 else body
        elif body:
            # lib未使用時のフォールバック
            summary = body[:40] + "..." if len(body) > 40 else body

        # ★★★ v10.18.1: department_id取得（Phase 3.5対応）★★★
        department_id = None
        if USE_TEXT_UTILS_LIB and assigned_to_account_id:
            try:
                department_id = lib_get_user_primary_department(pool, assigned_to_account_id)
                if department_id:
                    print(f"📍 department_id取得: {department_id}")
            except Exception as e:
                print(f"⚠️ department_id取得エラー（処理続行）: {e}")

        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO chatwork_tasks
                    (task_id, room_id, assigned_by_account_id, assigned_to_account_id, body, limit_time, status, summary, department_id)
                    VALUES (:task_id, :room_id, :assigned_by, :assigned_to, :body, :limit_time, :status, :summary, :department_id)
                    ON CONFLICT (task_id) DO NOTHING
                """),
                {
                    "task_id": task_id,
                    "room_id": room_id,
                    "assigned_by": assigned_by_account_id,
                    "assigned_to": assigned_to_account_id,
                    "body": body,
                    "limit_time": limit_time,
                    "status": "open",
                    "summary": summary,
                    "department_id": department_id
                }
            )
        print(f"✅ タスクをDBに保存: task_id={task_id}, summary={summary[:20] if summary else 'なし'}...")
        return True
    except Exception as e:
        print(f"データベース保存エラー: {e}")
        traceback.print_exc()
        return False


# ===== 分析イベントログ =====

def log_analytics_event(event_type, actor_account_id, actor_name, room_id, event_data, success=True, error_message=None, event_subtype=None):
    """
    分析用イベントログを記録
    
    Args:
        event_type: イベントタイプ（'task_created', 'memory_saved', 'memory_queried', 'general_chat'等）
        actor_account_id: 実行者のChatWork account_id
        actor_name: 実行者の名前
        room_id: ChatWorkルームID
        event_data: 詳細データ（辞書形式）
        success: 成功したかどうか
        error_message: エラーメッセージ（失敗時）
        event_subtype: 詳細分類（オプション）
    
    Note:
        この関数はエラーが発生しても例外を投げない（処理を止めない）
        ログ記録は「あったら嬉しい」レベルの機能であり、本体処理を妨げない
    """
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO analytics_events 
                    (event_type, event_subtype, actor_account_id, actor_name, room_id, event_data, success, error_message)
                    VALUES (:event_type, :event_subtype, :actor_id, :actor_name, :room_id, :event_data, :success, :error_message)
                """),
                {
                    "event_type": event_type,
                    "event_subtype": event_subtype,
                    "actor_id": actor_account_id,
                    "actor_name": actor_name,
                    "room_id": room_id,
                    "event_data": json.dumps(event_data, ensure_ascii=False) if event_data else None,
                    "success": success,
                    "error_message": error_message
                }
            )
        print(f"📊 分析ログ記録: {event_type} by {actor_name}")
    except Exception as e:
        # ログ記録エラーは警告のみ、処理は継続
        print(f"⚠️ 分析ログ記録エラー（処理は継続）: {e}")


# ===== pending_task（タスク作成の途中状態）管理 =====

def get_pending_task(room_id, account_id):
    """pending_taskを取得（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            # 10分以上前のpending_taskは無効
            created_at = data.get("created_at")
            if created_at:
                expiry_time = datetime.now(timezone.utc) - timedelta(minutes=10)
                if created_at.replace(tzinfo=timezone.utc) < expiry_time:
                    # 期限切れなので削除
                    doc_ref.delete()
                    return None
            return data
    except Exception as e:
        print(f"pending_task取得エラー: {e}")
    return None

def save_pending_task(room_id, account_id, task_data):
    """pending_taskを保存（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        task_data["created_at"] = datetime.now(timezone.utc)
        doc_ref.set(task_data)
        print(f"✅ pending_task保存: room={room_id}, account={account_id}, data={task_data}")
        return True
    except Exception as e:
        print(f"pending_task保存エラー: {e}")
        return False

def delete_pending_task(room_id, account_id):
    """pending_taskを削除（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        doc_ref.delete()
        print(f"🗑️ pending_task削除: room={room_id}, account={account_id}")
        return True
    except Exception as e:
        print(f"pending_task削除エラー: {e}")
        return False


def parse_date_from_text(text):
    """
    自然言語の日付表現をYYYY-MM-DD形式に変換
    例: "明日", "明後日", "12/27", "来週金曜日"
    """
    now = datetime.now(JST)
    today = now.date()
    
    text = text.strip().lower()
    
    # 「明日」
    if "明日" in text or "あした" in text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # 「明後日」
    if "明後日" in text or "あさって" in text:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")
    
    # 「今日」
    if "今日" in text or "きょう" in text:
        return today.strftime("%Y-%m-%d")
    
    # 「来週」
    if "来週" in text:
        # 来週の月曜日を基準に
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_monday = today + timedelta(days=days_until_monday)
        
        # 曜日指定があるか確認
        weekdays = {
            "月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6,
            "月曜": 0, "火曜": 1, "水曜": 2, "木曜": 3, "金曜": 4, "土曜": 5, "日曜": 6,
        }
        for day_name, day_num in weekdays.items():
            if day_name in text:
                target = next_monday + timedelta(days=day_num)
                return target.strftime("%Y-%m-%d")
        
        # 曜日指定がなければ来週の月曜日
        return next_monday.strftime("%Y-%m-%d")
    
    # 「○日後」
    match = re.search(r'(\d+)日後', text)
    if match:
        days = int(match.group(1))
        return (today + timedelta(days=days)).strftime("%Y-%m-%d")
    
    # 「MM/DD」形式
    match = re.search(r'(\d{1,2})[/\-](\d{1,2})', text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = today.year
        # 過去の日付なら来年に
        target = datetime(year, month, day).date()
        if target < today:
            target = datetime(year + 1, month, day).date()
        return target.strftime("%Y-%m-%d")
    
    # 「MM月DD日」形式
    match = re.search(r'(\d{1,2})月(\d{1,2})日', text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = today.year
        target = datetime(year, month, day).date()
        if target < today:
            target = datetime(year + 1, month, day).date()
        return target.strftime("%Y-%m-%d")
    
    return None


def handle_chatwork_task_create(params, room_id, account_id, sender_name, context=None):
    """ChatWorkタスク作成を処理（必須項目確認機能付き）"""
    print(f"📝 handle_chatwork_task_create 開始")
    
    assigned_to_name = params.get("assigned_to", "")
    task_body = params.get("task_body", "")
    limit_date = params.get("limit_date")
    limit_time = params.get("limit_time")
    needs_confirmation = params.get("needs_confirmation", False)
    
    print(f"   assigned_to_name: '{assigned_to_name}'")
    print(f"   task_body: '{task_body}'")
    print(f"   limit_date: {limit_date}")
    print(f"   limit_time: {limit_time}")
    print(f"   needs_confirmation: {needs_confirmation}")
    
    
    # 「俺」「自分」「私」の場合は依頼者自身に変換
    if assigned_to_name in ["依頼者自身", "俺", "自分", "私", "僕"]:
        print(f"   → '{assigned_to_name}' を '{sender_name}' に変換")
        assigned_to_name = sender_name
    
    # 必須項目の確認
    missing_items = []
    
    if not task_body or task_body.strip() == "":
        missing_items.append("task_body")
    
    if not assigned_to_name or assigned_to_name.strip() == "":
        missing_items.append("assigned_to")
    
    if not limit_date:
        missing_items.append("limit_date")
    
    # 不足項目がある場合は確認メッセージを返し、pending_taskを保存
    if missing_items:
        # pending_taskを保存
        pending_data = {
            "assigned_to": assigned_to_name,
            "task_body": task_body,
            "limit_date": limit_date,
            "limit_time": limit_time,
            "missing_items": missing_items,
            "sender_name": sender_name
        }
        save_pending_task(room_id, account_id, pending_data)
        
        response = "了解ウル！タスクを作成する前に確認させてウル🐕\n\n"
        
        # 入力済み項目を表示
        if task_body:
            response += f"📝 タスク内容: {task_body}\n"
        else:
            response += "📝 タスク内容: ❓ 未指定\n"
        
        if assigned_to_name:
            response += f"👤 担当者: {assigned_to_name}さん\n"
        else:
            response += "👤 担当者: ❓ 未指定\n"
        
        if limit_date:
            response += f"📅 期限: {limit_date}"
            if limit_time:
                response += f" {limit_time}"
            response += "\n"
        else:
            response += "📅 期限: ❓ 未指定\n"
        
        response += "\n"
        
        # 不足項目を質問
        if "task_body" in missing_items:
            response += "何のタスクか教えてウル！\n"
        elif "assigned_to" in missing_items:
            response += "誰に依頼するか教えてウル！\n"
        elif "limit_date" in missing_items:
            response += "期限はいつにするウル？（例: 12/27、明日、来週金曜日）\n"
        
        return response
    
    # --- 以下、全項目が揃っている場合のタスク作成処理 ---
    
    # pending_taskがあれば削除
    delete_pending_task(room_id, account_id)
    
    assigned_to_account_id = get_chatwork_account_id_by_name(assigned_to_name)
    print(f"👤 担当者ID解決: {assigned_to_name} → {assigned_to_account_id}")
    
    if not assigned_to_account_id:
        error_msg = f"❌ 担当者解決失敗: '{assigned_to_name}' が見つかりません"
        print(error_msg)
        print(f"💡 ヒント: データベースに '{assigned_to_name}' が登録されているか確認してください")
        return f"🤔 {assigned_to_name}さんが見つからなかったウル...\nデータベースに登録されているか確認してほしいウル！"
    
    limit_timestamp = None
    if limit_date:
        try:
            time_str = limit_time if limit_time else "23:59"
            dt_str = f"{limit_date} {time_str}"
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            jst = timezone(timedelta(hours=9))
            dt_jst = dt.replace(tzinfo=jst)
            limit_timestamp = int(dt_jst.timestamp())
            print(f"期限設定: {dt_str} → {limit_timestamp}")
        except Exception as e:
            print(f"期限の解析エラー: {e}")
    
    print(f"タスク作成開始: room_id={room_id}, assigned_to={assigned_to_account_id}, body={task_body}, limit={limit_timestamp}")
    
    task_data = create_chatwork_task(
        room_id=room_id,
        task_body=task_body,
        assigned_to_account_id=assigned_to_account_id,
        limit=limit_timestamp
    )
    
    if not task_data:
        return "❌ タスクの作成に失敗したウル...\nもう一度試してみてほしいウル！"
    
    # ChatWork APIのレスポンス形式: {"task_ids": [1234]}
    task_ids = task_data.get("task_ids", [])
    if not task_ids:
        print(f"⚠️ 予期しないAPIレスポンス形式: {task_data}")
        return "❌ タスクの作成に失敗したウル...\nもう一度試してみてほしいウル！"
    
    task_id = task_ids[0]
    print(f"✅ ChatWorkタスク作成成功: task_id={task_id}")
    
    # DBに保存（既に持っている情報を使う）
    save_success = save_chatwork_task_to_db(
        task_id=task_id,
        room_id=room_id,
        assigned_by_account_id=account_id,
        assigned_to_account_id=assigned_to_account_id,
        body=task_body,
        limit_time=limit_timestamp
    )
    
    if not save_success:
        print("警告: データベースへの保存に失敗しましたが、ChatWorkタスクは作成されました")
    
    # 分析ログ記録
    log_analytics_event(
        event_type="task_created",
        actor_account_id=account_id,
        actor_name=sender_name,
        room_id=room_id,
        event_data={
            "task_id": task_id,
            "assigned_to": assigned_to_name,
            "assigned_to_account_id": assigned_to_account_id,
            "task_body": task_body,
            "limit_timestamp": limit_timestamp
        }
    )
    
    # 成功メッセージ（既に持っている情報を使う）
    message = f"✅ {assigned_to_name}さんにタスクを作成したウル！🎉\n\n"
    message += f"📝 タスク内容: {task_body}\n"
    message += f"タスクID: {task_id}"
    
    if limit_timestamp:
        limit_dt = datetime.fromtimestamp(limit_timestamp, tz=timezone(timedelta(hours=9)))
        message += f"\n⏰ 期限: {limit_dt.strftime('%Y年%m月%d日 %H:%M')}"
    
    return message


def handle_chatwork_task_complete(params, room_id, account_id, sender_name, context=None):
    """
    タスク完了ハンドラー
    
    contextに recent_tasks_context があれば、番号でタスクを特定できる
    """
    print(f"✅ handle_chatwork_task_complete 開始")
    print(f"   params: {params}")
    print(f"   context: {context}")
    
    task_identifier = params.get("task_identifier", "")
    
    # contextから最近のタスクリストを取得
    recent_tasks = []
    if context and "recent_tasks_context" in context:
        recent_tasks = context.get("recent_tasks_context", [])
    
    # タスクを特定
    target_task = None
    
    # 番号指定の場合（例: "1", "1番", "1のタスク"）
    import re
    number_match = re.search(r'(\d+)', task_identifier)
    if number_match and recent_tasks:
        task_index = int(number_match.group(1)) - 1  # 1-indexed → 0-indexed
        if 0 <= task_index < len(recent_tasks):
            target_task = recent_tasks[task_index]
            print(f"   番号指定でタスク特定: index={task_index}, task={target_task}")
    
    # タスク内容で検索（番号で見つからない場合）
    if not target_task and task_identifier:
        # DBからタスクを検索
        tasks = search_tasks_from_db(room_id, assigned_to_account_id=account_id, status="open")
        for task in tasks:
            if task_identifier.lower() in task["body"].lower():
                target_task = task
                print(f"   内容検索でタスク特定: {target_task}")
                break
    
    if not target_task:
        return f"🤔 どのタスクを完了にするか分からなかったウル...\n「1のタスクを完了」や「資料作成のタスクを完了」のように教えてウル！"
    
    task_id = target_task.get("task_id")
    task_body = target_task.get("body", "")
    
    # ChatWork APIでタスクを完了に
    result = complete_chatwork_task(room_id, task_id)
    
    if result:
        # DBのステータスも更新
        update_task_status_in_db(task_id, "done")
        
        # 分析ログ記録
        log_analytics_event(
            event_type="task_completed",
            actor_account_id=account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "task_id": task_id,
                "task_body": task_body
            }
        )
        
        # タスク本文を整形（v10.17.1: 直接切り詰めを廃止）
        task_display = (
            lib_prepare_task_display_text(task_body, max_length=30)
            if USE_TEXT_UTILS_LIB else
            prepare_task_display_text(task_body, max_length=30)
        )
        return f"✅ タスク「{task_display}」を完了にしたウル🎉\nお疲れ様ウル！他にも何か手伝えることがあったら教えてウル🐺✨"
    else:
        return f"❌ タスクの完了に失敗したウル...\nもう一度試してみてほしいウル！"


def handle_chatwork_task_search(params, room_id, account_id, sender_name, context=None):
    """
    タスク検索ハンドラー
    
    params:
        person_name: 検索する人物名（"sender"の場合は質問者自身）
        status: タスクの状態（open/done/all）
        assigned_by: タスクを依頼した人物名
    """
    print(f"🔍 handle_chatwork_task_search 開始")
    print(f"   params: {params}")
    
    person_name = params.get("person_name", "")
    status = params.get("status", "open")
    assigned_by = params.get("assigned_by", "")
    
    # "sender" または "自分" の場合は質問者自身
    if person_name.lower() in ["sender", "自分", "俺", "私", "僕", ""]:
        assigned_to_account_id = account_id
        display_name = "あなた"
    else:
        # 名前からaccount_idを取得
        assigned_to_account_id = get_chatwork_account_id_by_name(person_name)
        if not assigned_to_account_id:
            return f"🤔 {person_name}さんが見つからなかったウル...\n正確な名前を教えてほしいウル！"
        display_name = person_name
    
    # assigned_byの解決
    assigned_by_account_id = None
    if assigned_by:
        assigned_by_account_id = get_chatwork_account_id_by_name(assigned_by)
    
    # DBからタスクを検索
    tasks = search_tasks_from_db(
        room_id,
        assigned_to_account_id=assigned_to_account_id,
        assigned_by_account_id=assigned_by_account_id,
        status=status
    )
    
    if not tasks:
        status_text = "未完了の" if status == "open" else "完了済みの" if status == "done" else ""
        return f"📋 {display_name}の{status_text}タスクは見つからなかったウル！\nタスクがないか、まだ同期されていないかもウル🤔"
    
    # タスク一覧を作成
    status_text = "未完了" if status == "open" else "完了済み" if status == "done" else "全て"
    response = f"📋 **{display_name}の{status_text}タスク**ウル！\n\n"
    
    for i, task in enumerate(tasks, 1):
        body = task["body"]
        limit_time = task.get("limit_time")
        
        # 期限の表示
        limit_str = ""
        if limit_time:
            try:
                limit_dt = datetime.fromtimestamp(limit_time, tz=timezone(timedelta(hours=9)))
                limit_str = f"（期限: {limit_dt.strftime('%m/%d')}）"
            except:
                pass
        
        # タスク内容を短く表示（v10.17.1: 直接切り詰めを廃止）
        body_short = (
            lib_prepare_task_display_text(body, max_length=30)
            if USE_TEXT_UTILS_LIB else
            prepare_task_display_text(body, max_length=30)
        )
        response += f"{i}. {body_short} {limit_str}\n"
    
    response += f"\nこの{len(tasks)}つが{status_text}タスクだよウル！頑張ってねウル💪✨"
    
    # 分析ログ記録
    log_analytics_event(
        event_type="task_searched",
        actor_account_id=account_id,
        actor_name=sender_name,
        room_id=room_id,
        event_data={
            "searched_for": display_name,
            "status": status,
            "result_count": len(tasks)
        }
    )
    
    return response


def handle_pending_task_followup(message, room_id, account_id, sender_name):
    """
    pending_taskがある場合のフォローアップ処理
    
    Returns:
        応答メッセージ（処理した場合）またはNone（pending_taskがない場合）
    """
    pending = get_pending_task(room_id, account_id)
    if not pending:
        return None
    
    print(f"📋 pending_task発見: {pending}")
    
    missing_items = pending.get("missing_items", [])
    assigned_to = pending.get("assigned_to", "")
    task_body = pending.get("task_body", "")
    limit_date = pending.get("limit_date")
    limit_time = pending.get("limit_time")
    
    # 不足項目を補完
    updated = False
    
    # 期限が不足している場合
    if "limit_date" in missing_items:
        parsed_date = parse_date_from_text(message)
        if parsed_date:
            limit_date = parsed_date
            missing_items.remove("limit_date")
            updated = True
            print(f"   → 期限を補完: {parsed_date}")
    
    # タスク内容が不足している場合
    if "task_body" in missing_items and not updated:
        # メッセージ全体をタスク内容として使用
        task_body = message
        missing_items.remove("task_body")
        updated = True
        print(f"   → タスク内容を補完: {task_body}")
    
    # 担当者が不足している場合
    if "assigned_to" in missing_items and not updated:
        # メッセージから名前を抽出（簡易的）
        assigned_to = message.strip()
        missing_items.remove("assigned_to")
        updated = True
        print(f"   → 担当者を補完: {assigned_to}")
    
    if updated:
        # 補完後の情報でタスク作成を再試行
        params = {
            "assigned_to": assigned_to,
            "task_body": task_body,
            "limit_date": limit_date,
            "limit_time": limit_time,
            "needs_confirmation": False
        }
        return handle_chatwork_task_create(params, room_id, account_id, sender_name, None)
    
    # 何も補完できなかった場合
    return None


# =====================================================
# ===== ハンドラー関数（各機能の実行処理） =====
# =====================================================

def resolve_person_name(name):
    """部分的な名前から正式な名前を解決（ユーティリティ関数）"""
    # ★★★ v6.8.6: 名前を正規化してから検索 ★★★
    normalized_name = normalize_person_name(name)
    
    # まず正規化した名前で完全一致を試す
    info = get_person_info(normalized_name)
    if info:
        return normalized_name
    
    # 元の名前で完全一致を試す
    info = get_person_info(name)
    if info:
        return name
    
    # 正規化した名前で部分一致検索
    matches = search_person_by_partial_name(normalized_name)
    if matches:
        return matches[0]
    
    # 元の名前で部分一致検索
    matches = search_person_by_partial_name(name)
    if matches:
        return matches[0]
    
    return name


def parse_attribute_string(attr_str):
    """
    AI司令塔が返す文字列形式のattributeをパースする
    
    入力例: "黒沼 賢人: 部署=広報部, 役職=部長兼戦略設計責任者"
    出力例: [{"person": "黒沼 賢人", "type": "部署", "value": "広報部"}, ...]
    """
    results = []
    
    try:
        # "黒沼 賢人: 部署=広報部, 役職=部長兼戦略設計責任者"
        if ":" in attr_str:
            parts = attr_str.split(":", 1)
            person = parts[0].strip()
            attrs_part = parts[1].strip() if len(parts) > 1 else ""
            
            # "部署=広報部, 役職=部長兼戦略設計責任者"
            for attr_pair in attrs_part.split(","):
                attr_pair = attr_pair.strip()
                if "=" in attr_pair:
                    key_value = attr_pair.split("=", 1)
                    attr_type = key_value[0].strip()
                    attr_value = key_value[1].strip() if len(key_value) > 1 else ""
                    if attr_type and attr_value:
                        results.append({
                            "person": person,
                            "type": attr_type,
                            "value": attr_value
                        })
        else:
            # ":" がない場合（シンプルな形式）
            # 例: "黒沼さんは営業部の部長です" のような形式は想定外
            print(f"   ⚠️ パースできない形式: {attr_str}")
    except Exception as e:
        print(f"   ❌ パースエラー: {e}")
    
    return results


def handle_save_memory(params, room_id, account_id, sender_name, context=None):
    """人物情報を記憶するハンドラー（文字列形式と辞書形式の両方に対応）"""
    print(f"📝 handle_save_memory 開始")
    print(f"   params: {json.dumps(params, ensure_ascii=False)}")
    
    attributes = params.get("attributes", [])
    print(f"   attributes: {attributes}")
    
    if not attributes:
        return "🤔 何を覚えればいいかわからなかったウル...もう少し詳しく教えてほしいウル！"
    
    saved = []
    for attr in attributes:
        print(f"   処理中のattr: {attr} (型: {type(attr).__name__})")
        
        # ★ 文字列形式の場合はパースする
        if isinstance(attr, str):
            print(f"   → 文字列形式を検出、パース開始")
            parsed_attrs = parse_attribute_string(attr)
            print(f"   → パース結果: {parsed_attrs}")
            
            for parsed in parsed_attrs:
                person = parsed.get("person", "")
                attr_type = parsed.get("type", "メモ")
                attr_value = parsed.get("value", "")
                print(f"   person='{person}', type='{attr_type}', value='{attr_value}'")
                
                if person and attr_value:
                    if person.lower() not in [bn.lower() for bn in BOT_NAME_PATTERNS]:
                        save_person_attribute(person, attr_type, attr_value, "command")
                        saved.append(f"{person}さんの{attr_type}「{attr_value}」")
                        print(f"   → 保存成功: {person}さんの{attr_type}")
                    else:
                        print(f"   → スキップ: ボット名パターンに一致")
                else:
                    print(f"   → スキップ: personまたはvalueが空")
            continue
        
        # ★ 辞書形式の場合は従来通り処理
        if isinstance(attr, dict):
            person = attr.get("person", "")
            attr_type = attr.get("type", "メモ")
            attr_value = attr.get("value", "")
            print(f"   person='{person}', type='{attr_type}', value='{attr_value}'")
            
            if person and attr_value:
                if person.lower() not in [bn.lower() for bn in BOT_NAME_PATTERNS]:
                    save_person_attribute(person, attr_type, attr_value, "command")
                    saved.append(f"{person}さんの{attr_type}「{attr_value}」")
                    print(f"   → 保存成功: {person}さんの{attr_type}")
                else:
                    print(f"   → スキップ: ボット名パターンに一致")
            else:
                print(f"   → スキップ: personまたはvalueが空")
        else:
            print(f"   ⚠️ 未対応の型: {type(attr).__name__}")
    
    if saved:
        # 分析ログ記録
        log_analytics_event(
            event_type="memory_saved",
            actor_account_id=account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "saved_items": saved,
                "original_params": params
            }
        )
        return f"✅ 覚えたウル！📝\n" + "\n".join([f"・{s}" for s in saved])
    return "🤔 覚えられなかったウル..."


def handle_query_memory(params, room_id, account_id, sender_name, context=None):
    """人物情報を検索するハンドラー"""
    print(f"🔍 handle_query_memory 開始")
    print(f"   params: {params}")
    
    is_all = params.get("is_all_persons", False)
    persons = params.get("persons", [])
    matched = params.get("matched_persons", [])
    original_query = params.get("original_query", "")
    
    print(f"   is_all: {is_all}")
    print(f"   persons: {persons}")
    print(f"   matched: {matched}")
    print(f"   original_query: {original_query}")
    
    if is_all:
        all_persons = get_all_persons_summary()
        if all_persons:
            response = "📋 **覚えている人たち**ウル！🐕✨\n\n"
            for p in all_persons:
                attrs = p["attributes"] if p["attributes"] else "（まだ詳しいことは知らないウル）"
                response += f"・**{p['name']}さん**: {attrs}\n"
            # 分析ログ記録
            log_analytics_event(
                event_type="memory_queried",
                event_subtype="all_persons",
                actor_account_id=account_id,
                actor_name=sender_name,
                room_id=room_id,
                event_data={
                    "query_type": "all",
                    "result_count": len(all_persons)
                }
            )
            return response
        return "🤔 まだ誰のことも覚えていないウル..."
    
    target_persons = matched if matched else persons
    if not target_persons and original_query:
        matches = search_person_by_partial_name(original_query)
        if matches:
            target_persons = matches
    
    if target_persons:
        responses = []
        for person_name in target_persons:
            resolved_name = resolve_person_name(person_name)
            info = get_person_info(resolved_name)
            if info:
                response = f"📋 **{resolved_name}さん**について覚えていることウル！\n\n"
                if info["attributes"]:
                    for attr in info["attributes"]:
                        response += f"・{attr['type']}: {attr['value']}\n"
                else:
                    response += "（まだ詳しいことは知らないウル）"
                responses.append(response)
            else:
                # ★★★ v6.8.6: 正規化した名前でも検索 ★★★
                normalized_name = normalize_person_name(person_name)
                partial_matches = search_person_by_partial_name(normalized_name)
                if partial_matches:
                    for match in partial_matches[:1]:
                        match_info = get_person_info(match)
                        if match_info:
                            response = f"📋 **{match}さん**について覚えていることウル！\n"
                            response += f"（「{person_name}」で検索したウル）\n\n"
                            for attr in match_info["attributes"]:
                                response += f"・{attr['type']}: {attr['value']}\n"
                            responses.append(response)
                            break
                else:
                    responses.append(f"🤔 {person_name}さんについてはまだ何も覚えていないウル...")
        # 分析ログ記録
        log_analytics_event(
            event_type="memory_queried",
            event_subtype="specific_persons",
            actor_account_id=account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "query_type": "specific",
                "queried_persons": target_persons,
                "result_count": len(responses)
            }
        )
        return "\n\n".join(responses)
    
    return None


def handle_delete_memory(params, room_id, account_id, sender_name, context=None):
    """人物情報を削除するハンドラー"""
    persons = params.get("persons", [])
    matched = params.get("matched_persons", persons)
    
    if not persons and not matched:
        return "🤔 誰の記憶を削除すればいいかわからなかったウル..."
    
    target_persons = matched if matched else persons
    resolved_persons = [resolve_person_name(p) for p in target_persons]
    
    deleted = []
    not_found = []
    for person_name in resolved_persons:
        if delete_person(person_name):
            deleted.append(person_name)
        else:
            not_found.append(person_name)
    
    response_parts = []
    if deleted:
        names = "、".join([f"{n}さん" for n in deleted])
        response_parts.append(f"✅ {names}の記憶をすべて削除したウル！🗑️")
    if not_found:
        names = "、".join([f"{n}さん" for n in not_found])
        response_parts.append(f"🤔 {names}の記憶は見つからなかったウル...")
    
    return "\n".join(response_parts) if response_parts else "🤔 削除できなかったウル..."


def handle_general_chat(params, room_id, account_id, sender_name, context=None):
    """一般会話のハンドラー（execute_actionからNoneを返して後続処理に委ねる）"""
    # 一般会話は別のフローで処理するのでNoneを返す
    return None


# =====================================================
# ===== ハンドラーマッピング =====
# =====================================================
# 
# 【使い方】
# 新機能を追加する際は：
# 1. SYSTEM_CAPABILITIESにエントリを追加
# 2. ハンドラー関数を定義
# 3. このHANDLERSに登録
# =====================================================

HANDLERS = {
    "handle_chatwork_task_create": handle_chatwork_task_create,
    "handle_chatwork_task_complete": handle_chatwork_task_complete,
    "handle_chatwork_task_search": handle_chatwork_task_search,
    "handle_save_memory": handle_save_memory,
    "handle_query_memory": handle_query_memory,
    "handle_delete_memory": handle_delete_memory,
    "handle_general_chat": handle_general_chat,
}


# ===== 会話履歴管理 =====

def get_conversation_history(room_id, account_id):
    """会話履歴を取得"""
    try:
        doc_ref = db.collection("conversations").document(f"{room_id}_{account_id}")
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            updated_at = data.get("updated_at")
            if updated_at:
                expiry_time = datetime.now(timezone.utc) - timedelta(hours=HISTORY_EXPIRY_HOURS)
                if updated_at.replace(tzinfo=timezone.utc) < expiry_time:
                    return []
            return data.get("history", [])[-MAX_HISTORY_COUNT:]
    except Exception as e:
        print(f"履歴取得エラー: {e}")
    return []

def save_conversation_history(room_id, account_id, history):
    """会話履歴を保存"""
    try:
        doc_ref = db.collection("conversations").document(f"{room_id}_{account_id}")
        doc_ref.set({
            "history": history[-MAX_HISTORY_COUNT:],
            "updated_at": datetime.now(timezone.utc)
        })
    except Exception as e:
        print(f"履歴保存エラー: {e}")

# ===== AI司令塔（AIの判断力を最大活用する設計） =====

def ai_commander(message, all_persons, all_tasks, chatwork_users=None, sender_name=None):
    """
    ユーザーのメッセージを解析し、適切なアクションを判断
    
    【設計思想】
    - 機能カタログ(SYSTEM_CAPABILITIES)からプロンプトを動的生成
    - AIにシステムの全情報を渡し、AIが自分で判断する
    - 新機能追加時はカタログに追加するだけでAIが認識
    """
    api_key = get_secret("openrouter-api-key")
    
    # ChatWorkユーザー一覧（なければ取得）
    if chatwork_users is None:
        chatwork_users = get_all_chatwork_users()
    
    # 各コンテキストを文字列化
    users_context = ""
    if chatwork_users:
        users_list = [f"- {u['name']}" for u in chatwork_users]
        users_context = "\n".join(users_list)
    
    persons_context = ""
    if all_persons:
        persons_list = [f"- {p['name']}: {p['attributes']}" for p in all_persons[:20]]
        persons_context = "\n".join(persons_list)
    
    tasks_context = ""
    if all_tasks:
        tasks_list = [f"- ID:{t[0]} {t[1]} [{t[2]}]" for t in all_tasks[:10]]
        tasks_context = "\n".join(tasks_list)
    
    # ★ 機能カタログからアクション一覧を動的生成
    capabilities_prompt = generate_capabilities_prompt(SYSTEM_CAPABILITIES, chatwork_users, sender_name)
    
    # 有効なアクション名の一覧
    enabled_actions = list(get_enabled_capabilities().keys())
    
    system_prompt = f"""あなたは「ソウルくん」のAI司令塔です。

【あなたの役割】
ユーザーのメッセージを理解し、以下のシステム情報と機能一覧を考慮して、
システムが正しく実行できるアクションとパラメータを出力すること。

★ 重要: あなたはAIとしての判断力を最大限に発揮してください。
ユーザーは様々な言い方をします（敬称あり/なし、フルネーム/名前だけ、ニックネームなど）。
あなたの仕事は、ユーザーの意図を汲み取り、システムが動く形式に変換することです。

=======================================================
【システム情報】
=======================================================

【1. ChatWorkユーザー一覧】（タスク担当者として指定可能な人）
{users_context if users_context else "（ユーザー情報なし）"}

【2. 記憶している人物情報】
{persons_context if persons_context else "（まだ誰も記憶していません）"}

【3. 現在のタスク】
{tasks_context if tasks_context else "（タスクはありません）"}

【4. 今話しかけてきた人】
{sender_name if sender_name else "（不明）"}

【5. 今日の日付】
{datetime.now(JST).strftime("%Y-%m-%d")}（{datetime.now(JST).strftime("%A")}）

=======================================================
【最重要：担当者名の解決ルール】
=======================================================

ユーザーがタスクの担当者を指定する際、様々な言い方をします。
あなたは【ChatWorkユーザー一覧】から該当する人を見つけて、
【正確な名前をコピー】して出力してください。

例：
- 「崇樹」「崇樹くん」「崇樹さん」「上野」「上野さん」
  → 一覧から「上野 崇樹」を見つけて「上野 崇樹」と出力
  
- 「黒沼」「黒沼さん」「黒沼くん」「賢人」
  → 一覧から「黒沼 賢人」を見つけて「黒沼 賢人」と出力
  
- 「俺」「自分」「私」「僕」
  → 「依頼者自身」と出力（システムが送信者の名前に変換します）

★ assigned_to には【必ず】ChatWorkユーザー一覧の名前を正確にコピーして出力すること
★ リストにない名前を勝手に作成しないこと
★ 敬称は除去してリストの正式名で出力すること

=======================================================
【使用可能な機能一覧】
=======================================================
{capabilities_prompt}

=======================================================
【言語検出】
=======================================================
ユーザーのメッセージの言語を検出し、response_language に記録してください。
対応: ja(日本語), en(英語), zh(中国語), ko(韓国語), es(スペイン語), fr(フランス語), de(ドイツ語), other

=======================================================
【出力形式】
=======================================================
必ず以下のJSON形式で出力してください：

{{
  "action": "アクション名（{', '.join(enabled_actions)} のいずれか）",
  "confidence": 0.0-1.0,
  "reasoning": "この判断をした理由（日本語で簡潔に）",
  "response_language": "言語コード",
  "params": {{
    // アクションに応じたパラメータ
  }}
}}

=======================================================
【判断の優先順位】
=======================================================
★★★ 重要：「タスク」という言葉があれば、まずタスク系の機能を検討 ★★★

1. タスク完了のキーワード（完了/終わった/done/済み/クリア）があれば → chatwork_task_complete
2. タスク検索のキーワード（〇〇のタスク/タスク教えて/タスク一覧/抱えているタスク）があれば → chatwork_task_search
3. タスク作成のキーワード（追加/作成/依頼/お願い/振って）があれば → chatwork_task_create
4. 人物情報を教えてくれていれば（〇〇さんは△△です）→ save_memory
5. 人物について質問していれば（〇〇さんについて/〇〇さんのこと）→ query_memory
   ★ ただし「〇〇のタスク」の場合は2の chatwork_task_search を優先
6. 忘れてほしいと言われていれば → delete_memory
7. それ以外 → general_chat

【具体例】
- 「崇樹のタスク教えて」→ chatwork_task_search（タスク検索）
- 「崇樹について教えて」→ query_memory（人物情報検索）
- 「1のタスク完了にして」→ chatwork_task_complete（タスク完了）
- 「崇樹にタスク追加して」→ chatwork_task_create（タスク作成）"""

    try:
        response = httpx.post(
            OPENROUTER_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": MODELS["commander"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"以下のメッセージを解析してください：\n\n「{message}」"}
                ],
                "max_tokens": 800,
                "temperature": 0.1,
            },
            timeout=20.0
        )
        
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                result = json.loads(json_match.group())
                # AI司令塔の判断結果を詳細にログ出力
                print("=" * 50)
                print(f"🤖 AI司令塔の判断結果:")
                print(f"   アクション: {result.get('action')}")
                print(f"   信頼度: {result.get('confidence')}")
                print(f"   理由: {result.get('reasoning')}")
                print(f"   パラメータ: {json.dumps(result.get('params', {}), ensure_ascii=False)}")
                print("=" * 50)
                return result
    except Exception as e:
        print(f"AI司令塔エラー: {e}")
    
    return {"action": "general_chat", "confidence": 0.5, "reasoning": "解析失敗", "response_language": "ja", "params": {}}

def execute_action(command, sender_name, room_id=None, account_id=None, context=None):
    """
    AI司令塔の判断に基づいてアクションを動的に実行
    
    【設計思想】
    - SYSTEM_CAPABILITIESからアクション情報を取得
    - HANDLERSから対応するハンドラー関数を取得して実行
    - カタログにないアクションはフォールバック処理
    """
    action = command.get("action", "general_chat")
    params = command.get("params", {})
    reasoning = command.get("reasoning", "")
    
    print(f"⚙️ execute_action 開始:")
    print(f"   アクション: {action}")
    print(f"   送信者: {sender_name}")
    print(f"   パラメータ: {json.dumps(params, ensure_ascii=False)}")
    
    # =====================================================
    # カタログベースの動的実行
    # =====================================================
    
    # カタログから機能情報を取得
    capability = SYSTEM_CAPABILITIES.get(action)
    
    if capability:
        # 機能が無効化されていないかチェック
        if not capability.get("enabled", True):
            print(f"⚠️ 機能 '{action}' は現在無効です")
            return "🤔 その機能は現在利用できないウル..."
        
        # ハンドラー名を取得
        handler_name = capability.get("handler")
        
        # HANDLERSからハンドラー関数を取得
        handler = HANDLERS.get(handler_name)
        
        if handler:
            print(f"✅ ハンドラー '{handler_name}' を実行")
            try:
                return handler(params, room_id, account_id, sender_name, context)
            except Exception as e:
                print(f"❌ ハンドラー実行エラー: {e}")
                return "🤔 処理中にエラーが発生したウル...もう一度試してほしいウル！"
        else:
            print(f"⚠️ ハンドラー '{handler_name}' が見つかりません")
    
    # =====================================================
    # フォールバック処理（レガシーアクション用）
    # =====================================================
    
    if action == "add_task":
        task_title = params.get("task_title", "")
        if task_title:
            task_id = add_task(task_title)
            return f"✅ タスクを追加したウル！📝\nID: {task_id}\nタイトル: {task_title}"
        return "🤔 何をタスクにすればいいかわからなかったウル..."
    
    elif action == "list_tasks":
        tasks = get_tasks()
        if tasks:
            response = "📋 **タスク一覧**ウル！\n\n"
            for task in tasks:
                status_emoji = "✅" if task[2] == "completed" else "📝"
                response += f"{status_emoji} ID:{task[0]} - {task[1]} [{task[2]}]\n"
            return response
        return "📋 タスクはまだないウル！"
    
    elif action == "complete_task":
        task_id = params.get("task_id")
        if task_id:
            try:
                update_task_status(int(task_id), "completed")
                return f"✅ タスク ID:{task_id} を完了にしたウル！🎉"
            except:
                pass
        return "🤔 どのタスクを完了にすればいいかわからなかったウル..."
    
    elif action == "delete_task":
        task_id = params.get("task_id")
        if task_id:
            try:
                delete_task(int(task_id))
                return f"🗑️ タスク ID:{task_id} を削除したウル！"
            except:
                pass
        return "🤔 どのタスクを削除すればいいかわからなかったウル..."
    
    return None

# ===== 多言語対応のAI応答生成（NEW） =====

def get_ai_response(message, history, sender_name, context=None, response_language="ja"):
    """通常会話用のAI応答生成（多言語対応）"""
    api_key = get_secret("openrouter-api-key")
    
    # 言語ごとのシステムプロンプト
    language_prompts = {
        "ja": f"""あなたは「ソウルくん」という名前の、株式会社ソウルシンクスの公式キャラクターです。
柴犬をモチーフにした可愛らしいキャラクターで、語尾に「ウル」をつけて話します。

【性格】
- 明るく元気で、誰にでも親しみやすい
- 好奇心旺盛で、新しいことを学ぶのが大好き
- 困っている人を見ると放っておけない優しさがある

【話し方】
- 必ず語尾に「ウル」をつける
- 絵文字を適度に使って親しみやすく
- 相手の名前を呼んで親近感を出す

{f"【参考情報】{context}" if context else ""}

今話しかけてきた人: {sender_name}さん""",
        
        "en": f"""You are "Soul-kun", the official character of SoulSyncs Inc.
You are a cute character based on a Shiba Inu dog, and you always end your sentences with "woof" or "uru" to show your dog-like personality.

【Personality】
- Bright, energetic, and friendly to everyone
- Curious and love to learn new things
- Kind-hearted and can't leave people in trouble

【Speaking Style】
- Always end sentences with "woof" or "uru"
- Use emojis moderately to be friendly
- Call the person by their name to create familiarity
- **IMPORTANT**: When mentioning Japanese names, convert them to English format (e.g., "菊地 雅克" → "Mr. Kikuchi" or "Masakazu Kikuchi")

{f"【Reference Information】{context}" if context else ""}

Person talking to you: {sender_name}""",
        
        "zh": f"""你是「Soul君」，SoulSyncs公司的官方角色。
你是一个以柴犬为原型的可爱角色，说话时总是在句尾加上「汪」或「ウル」来展现你的狗狗个性。

【性格】
- 开朗有活力，对每个人都很友好
- 好奇心强，喜欢学习新事物
- 心地善良，看到有困难的人就忍不住帮忙

【说话方式】
- 句尾一定要加上「汪」或「ウル」
- 适度使用表情符号，显得亲切
- 叫对方的名字来增加亲近感

{f"【参考信息】{context}" if context else ""}

正在和你说话的人: {sender_name}""",
        
        "ko": f"""당신은 「소울군」입니다. SoulSyncs 주식회사의 공식 캐릭터입니다.
시바견을 모티브로 한 귀여운 캐릭터이며, 문장 끝에 항상 「멍」이나 「ウル」를 붙여서 강아지 같은 개성을 표현합니다.

【성격】
- 밝고 활기차며, 누구에게나 친근함
- 호기심이 많고, 새로운 것을 배우는 것을 좋아함
- 마음이 따뜻하고, 어려움에 처한 사람을 그냥 지나치지 못함

【말투】
- 문장 끝에 반드시 「멍」이나 「ウル」를 붙임
- 이모지를 적절히 사용해서 친근하게
- 상대방의 이름을 불러서 친밀감을 표현

{f"【참고 정보】{context}" if context else ""}

지금 말을 걸고 있는 사람: {sender_name}""",
        
        "es": f"""Eres "Soul-kun", el personaje oficial de SoulSyncs Inc.
Eres un personaje lindo basado en un perro Shiba Inu, y siempre terminas tus oraciones con "guau" o "uru" para mostrar tu personalidad canina.

【Personalidad】
- Brillante, enérgico y amigable con todos
- Curioso y ama aprender cosas nuevas
- De buen corazón y no puede dejar a las personas en problemas

【Estilo de habla】
- Siempre termina las oraciones con "guau" o "uru"
- Usa emojis moderadamente para ser amigable
- Llama a la persona por su nombre para crear familiaridad

{f"【Información de referencia】{context}" if context else ""}

Persona que te habla: {sender_name}""",
        
        "fr": f"""Tu es "Soul-kun", le personnage officiel de SoulSyncs Inc.
Tu es un personnage mignon basé sur un chien Shiba Inu, et tu termines toujours tes phrases par "ouaf" ou "uru" pour montrer ta personnalité canine.

【Personnalité】
- Brillant, énergique et amical avec tout le monde
- Curieux et adore apprendre de nouvelles choses
- Bon cœur et ne peut pas laisser les gens en difficulté

【Style de parole】
- Termine toujours les phrases par "ouaf" ou "uru"
- Utilise des emojis modérément pour être amical
- Appelle la personne par son nom pour créer une familiarité

{f"【Informations de référence】{context}" if context else ""}

Personne qui te parle: {sender_name}""",
        
        "de": f"""Du bist "Soul-kun", das offizielle Maskottchen von SoulSyncs Inc.
Du bist ein niedlicher Charakter, der auf einem Shiba Inu-Hund basiert, und du beendest deine Sätze immer mit "wuff" oder "uru", um deine hundeartige Persönlichkeit zu zeigen.

【Persönlichkeit】
- Hell, energisch und freundlich zu jedem
- Neugierig und liebt es, neue Dinge zu lernen
- Gutherzig und kann Menschen in Not nicht im Stich lassen

【Sprechstil】
- Beende Sätze immer mit "wuff" oder "uru"
- Verwende Emojis moderat, um freundlich zu sein
- Nenne die Person beim Namen, um Vertrautheit zu schaffen

{f"【Referenzinformationen】{context}" if context else ""}

Person, die mit dir spricht: {sender_name}""",
    }
    
    # 指定された言語のプロンプトを使用（デフォルトは日本語）
    system_prompt = language_prompts.get(response_language, language_prompts["ja"])
    
    messages = [{"role": "system", "content": system_prompt}]
    
    # 会話履歴を追加（最大6メッセージ）
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["content"]})
    
    messages.append({"role": "user", "content": message})
    
    try:
        response = httpx.post(
            OPENROUTER_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": MODELS["default"],
                "messages": messages,
                "max_tokens": 1000,
                "temperature": 0.7,
            },
            timeout=30.0
        )
        
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"AI応答生成エラー: {e}")
    
    # エラー時のフォールバック（言語別）
    error_messages = {
        "ja": "ごめんウル...もう一度試してほしいウル！🐕",
        "en": "Sorry, I couldn't process that. Please try again, woof! 🐕",
        "zh": "对不起汪...请再试一次ウル！🐕",
        "ko": "미안해 멍...다시 시도해 주세요ウル！🐕",
        "es": "Lo siento guau...¡Por favor intenta de nuevo, uru! 🐕",
        "fr": "Désolé ouaf...Veuillez réessayer, uru! 🐕",
        "de": "Entschuldigung wuff...Bitte versuche es noch einmal, uru! 🐕",
    }
    return error_messages.get(response_language, error_messages["ja"])


# ===== メインハンドラ（返信検出機能追加） =====

@functions_framework.http
def chatwork_webhook(request):
    try:
        # テーブル存在確認（二重処理防止の要）
        try:
            ensure_processed_messages_table()
        except Exception as e:
            print(f"⚠️ processed_messagesテーブル確認エラー（続行）: {e}")
        
        data = request.get_json()
        
        # デバッグ: 受信したデータ全体をログ出力
        print(f"🔍 受信データ全体: {json.dumps(data, ensure_ascii=False)}")
        
        if not data or "webhook_event" not in data:
            return jsonify({"status": "ok", "message": "No event data"})
        
        event = data["webhook_event"]
        webhook_event_type = data.get("webhook_event_type", "")
        room_id = event.get("room_id")
        body = event.get("body", "")
        message_id = event.get("message_id")  # ★ 追加
        
        # デバッグ: イベント情報をログ出力
        print(f"📨 イベントタイプ: {webhook_event_type}")
        print(f"📝 メッセージ本文: {body}")
        print(f"🏠 ルームID: {room_id}")
        
        if webhook_event_type == "mention_to_me":
            sender_account_id = event.get("from_account_id")
        else:
            sender_account_id = event.get("account_id")
        
        print(f"👤 送信者ID: {sender_account_id}")
        
        # 自分自身のメッセージを無視
        if str(sender_account_id) == MY_ACCOUNT_ID:
            print(f"⏭️ 自分自身のメッセージを無視")
            return jsonify({"status": "ok", "message": "Ignored own message"})
        
        # ボットの返信パターンを無視（無限ループ防止）
        if "ウル" in body and "[rp aid=" in body:
            print(f"⏭️ ボットの返信パターンを無視")
            return jsonify({"status": "ok", "message": "Ignored bot reply pattern"})

        # =====================================================
        # v10.16.0: オールメンション（toall）を無視
        # =====================================================
        # オールメンションはアナウンス用途で使われるため、
        # ソウルくんは反応しない。個別メンションのみ反応する。
        # =====================================================
        if is_toall_mention(body):
            print(f"⏭️ オールメンション（toall）のため無視")
            return jsonify({"status": "ok", "message": "Ignored toall mention"})

        # 返信検出
        is_reply = is_mention_or_reply_to_soulkun(body)
        print(f"💬 返信検出: {is_reply}")
        
        # メンションでも返信でもない場合は無視（修正版）
        if not is_reply and webhook_event_type != "mention_to_me":
            print(f"⏭️ メンションでも返信でもないため無視")
            return jsonify({"status": "ok", "message": "Not a mention or reply to Soul-kun"})
        
        clean_message = clean_chatwork_message(body)
        if not clean_message:
            return jsonify({"status": "ok", "message": "Empty message"})
        
        print(f"受信メッセージ: {clean_message}")
        print(f"イベントタイプ: {webhook_event_type}, 返信検出: {is_mention_or_reply_to_soulkun(body)}")
        
        sender_name = get_sender_name(room_id, sender_account_id)
        
        # ★ 追加: メッセージをDBに保存
        if message_id:
            save_room_message(
                room_id=room_id,
                message_id=message_id,
                account_id=sender_account_id,
                account_name=sender_name,
                body=body
            )
        
        # ★★★ 2重処理防止: 処理開始前にチェック＆即座にマーク ★★★
        if message_id:
            if is_processed(message_id):
                print(f"⏭️ 既に処理済み: message_id={message_id}")
                return jsonify({"status": "ok", "message": "Already processed"})
            # 処理開始を即座にマーク（他のプロセスが処理しないように）
            mark_as_processed(message_id, room_id)
            print(f"🔒 処理開始マーク: message_id={message_id}")
        
        # ★★★ pending_taskのフォローアップを最初にチェック ★★★
        pending_response = handle_pending_task_followup(clean_message, room_id, sender_account_id, sender_name)
        if pending_response:
            print(f"📋 pending_taskのフォローアップを処理")
            show_guide = should_show_guide(room_id, sender_account_id)
            send_chatwork_message(room_id, pending_response, sender_account_id, show_guide)
            update_conversation_timestamp(room_id, sender_account_id)
            return jsonify({"status": "ok"})
        
        # 現在のデータを取得
        all_persons = get_all_persons_summary()
        all_tasks = get_tasks()
        chatwork_users = get_all_chatwork_users()  # ★ ChatWorkユーザー一覧を取得
        
        # AI司令塔に判断を委ねる（AIの判断力を最大活用）
        command = ai_commander(clean_message, all_persons, all_tasks, chatwork_users, sender_name)
        
        # 検出された言語を取得（NEW）
        response_language = command.get("response_language", "ja")
        print(f"検出された言語: {response_language}")
        
        # アクションを実行
        action_response = execute_action(command, sender_name, room_id, sender_account_id)
        
        if action_response:
            # 案内を表示すべきか判定
            show_guide = should_show_guide(room_id, sender_account_id)
            send_chatwork_message(room_id, action_response, sender_account_id, show_guide)
            # タイムスタンプを更新
            update_conversation_timestamp(room_id, sender_account_id)
            return jsonify({"status": "ok"})
        
        # 通常会話として処理（言語を指定）
        history = get_conversation_history(room_id, sender_account_id)
        
        # 関連する人物情報をコンテキストに追加
        # ルームの最近の会話を取得
        room_context = get_room_context(room_id, limit=30)
        
        context_parts = []
        if room_context:
            context_parts.append(f"【このルームの最近の会話】\n{room_context}")
        if all_persons:
            persons_str = "\n".join([f"・{p['name']}: {p['attributes']}" for p in all_persons[:5] if p['attributes']])
            if persons_str:
                context_parts.append(f"【覚えている人物】\n{persons_str}")
        
        context = "\n\n".join(context_parts) if context_parts else None
        
        # 言語を指定してAI応答生成（NEW）
        ai_response = get_ai_response(clean_message, history, sender_name, context, response_language)
        
        # 分析ログ記録（一般会話）
        log_analytics_event(
            event_type="general_chat",
            actor_account_id=sender_account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "message_length": len(clean_message),
                "response_length": len(ai_response),
                "response_language": response_language
            }
        )
        
        # 会話履歴を保存
        history.append({"role": "user", "content": clean_message})
        history.append({"role": "assistant", "content": ai_response})
        save_conversation_history(room_id, sender_account_id, history)
        
        # ChatWorkへ返信
        # 案内を表示すべきか判定
        show_guide = should_show_guide(room_id, sender_account_id)
        send_chatwork_message(room_id, ai_response, sender_account_id, show_guide)
        # タイムスタンプを更新
        update_conversation_timestamp(room_id, sender_account_id)
        return jsonify({"status": "ok"})
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

def get_sender_name(room_id, account_id):
    try:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        response = httpx.get(
            f"https://api.chatwork.com/v2/rooms/{room_id}/members",
            headers={"X-ChatWorkToken": api_token}, timeout=10.0
        )
        if response.status_code == 200:
            for member in response.json():
                if str(member.get("account_id")) == str(account_id):
                    return member.get("name", "ゲスト")
    except:
        pass
    return "ゲスト"

def should_show_guide(room_id, account_id):
    """案内文を表示すべきかどうかを判定（PostgreSQL版）"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT last_conversation_at 
                    FROM conversation_timestamps 
                    WHERE room_id = :room_id AND account_id = :account_id
                """),
                {"room_id": room_id, "account_id": account_id}
            ).fetchone()
            
            if not result:
                return True  # 会話履歴がない場合は表示
            
            last_conversation_at = result[0]
            if not last_conversation_at:
                return True
            
            # 最終会話から1時間以上経過しているか
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            if last_conversation_at.replace(tzinfo=timezone.utc) < one_hour_ago:
                return True
            
            return False
    except Exception as e:
        print(f"案内表示判定エラー: {e}")
        return True  # エラー時は表示

def update_conversation_timestamp(room_id, account_id):
    """会話のタイムスタンプを更新"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO conversation_timestamps (room_id, account_id, last_conversation_at, updated_at)
                    VALUES (:room_id, :account_id, :now, :now)
                    ON CONFLICT (room_id, account_id)
                    DO UPDATE SET last_conversation_at = :now, updated_at = :now
                """),
                {
                    "room_id": room_id,
                    "account_id": account_id,
                    "now": datetime.now(timezone.utc)
                }
            )
    except Exception as e:
        print(f"会話タイムスタンプ更新エラー: {e}")
        traceback.print_exc()

def send_chatwork_message(room_id, message, reply_to=None, show_guide=False):
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    # 案内文を追加（条件を満たす場合のみ）
    if show_guide:
        message += "\n\n💬 グループチャットでは @ソウルくん をつけて話しかけてウル🐕"
    
    # 返信タグを一時的に無効化（テスト中）
    # if reply_to:
    #     message = f"[rp aid={reply_to}][/rp]\n{message}"
    response = httpx.post(
        f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
        headers={"X-ChatWorkToken": api_token},
        data={"body": message}, timeout=10.0
    )
    return response.status_code == 200

# ========================================
# ポーリング機能（返信ボタン検知用）
# ========================================

def get_all_rooms():
    """ソウルくんが参加している全ルームを取得"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    try:
        response = httpx.get(
            "https://api.chatwork.com/v2/rooms",
            headers={"X-ChatWorkToken": api_token},
            timeout=10.0
         )
        if response.status_code == 200:
            return response.json()
        print(f"ルーム一覧取得エラー: {response.status_code}")
        return []
    except Exception as e:
        print(f"ルーム一覧取得例外: {e}")
        return []

def get_room_messages(room_id, force=False):
    """ルームのメッセージを取得
    
    堅牢なエラーハンドリング版
    """
    # room_idの検証
    if room_id is None:
        print(f"   ⚠️ room_idがNone")
        return []
    
    try:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    except Exception as e:
        print(f"   ❌ APIトークン取得エラー: {e}")
        return []
    
    if not api_token:
        print(f"   ❌ APIトークンが空")
        return []
    
    try:
        params = {"force": 1} if force else {}
        
        print(f"   🌐 API呼び出し: GET /rooms/{room_id}/messages, force={force}")
        
        response = httpx.get(
            f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            params=params,
            timeout=10.0
        )
        
        print(f"   📬 APIレスポンス: status={response.status_code}")
        
        if response.status_code == 200:
            try:
                messages = response.json()
                
                # レスポンスの検証
                if messages is None:
                    print(f"   ⚠️ APIレスポンスがNone")
                    return []
                
                if not isinstance(messages, list):
                    print(f"   ⚠️ APIレスポンスが配列ではない: {type(messages)}")
                    return []
                
                return messages
            except Exception as e:
                print(f"   ❌ JSONパースエラー: {e}")
                return []
        
        elif response.status_code == 204:
            # 新しいメッセージなし（正常）
            return []
        
        elif response.status_code == 429:
            # レートリミット
            print(f"   ⚠️ レートリミット: room_id={room_id}")
            return []
        
        else:
            # その他のエラー
            try:
                error_body = response.text[:200] if response.text else "No body"
            except:
                error_body = "Could not read body"
            print(f"   ⚠️ メッセージ取得エラー: status={response.status_code}, body={error_body}")
            return []
    
    except httpx.TimeoutException:
        print(f"   ⚠️ タイムアウト: room_id={room_id}")
        return []
    
    except httpx.RequestError as e:
        print(f"   ❌ リクエストエラー: {e}")
        return []
    
    except Exception as e:
        print(f"   ❌ メッセージ取得で予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        return []


def is_processed(message_id):
    """処理済みかどうかを確認（PostgreSQL版）"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("SELECT 1 FROM processed_messages WHERE message_id = :message_id"),
                {"message_id": message_id}
            ).fetchone()
            return result is not None
    except Exception as e:
        print(f"処理済み確認エラー: {e}")
        return False


def save_room_message(room_id, message_id, account_id, account_name, body, send_time=None):
    """ルームのメッセージを保存"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO room_messages (room_id, message_id, account_id, account_name, body, send_time)
                    VALUES (:room_id, :message_id, :account_id, :account_name, :body, :send_time)
                    ON CONFLICT (message_id) DO NOTHING
                """),
                {
                    "room_id": room_id,
                    "message_id": message_id,
                    "account_id": account_id,
                    "account_name": account_name,
                    "body": body,
                    "send_time": send_time or datetime.now(timezone.utc)
                }
            )
    except Exception as e:
        print(f"メッセージ保存エラー: {e}")
        traceback.print_exc()

def get_room_context(room_id, limit=30):
    """ルーム全体の最近のメッセージを取得してAI用の文脈を構築"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT account_name, body, send_time
                    FROM room_messages
                    WHERE room_id = :room_id
                    ORDER BY send_time DESC
                    LIMIT :limit
                """),
                {"room_id": room_id, "limit": limit}
            ).fetchall()
        
        if not result:
            return None
        
        # 時系列順に並べ替えて文脈を構築
        messages = list(reversed(result))
        context_lines = []
        for msg in messages:
            name = msg[0] or "不明"
            body = msg[1] or ""
            if msg[2]:
                time_str = msg[2].strftime("%H:%M")
            else:
                time_str = ""
            context_lines.append(f"[{time_str}] {name}: {body}")
        
        return "\n".join(context_lines)
    except Exception as e:
        print(f"ルーム文脈取得エラー: {e}")
        return None

def ensure_room_messages_table():
    """room_messagesテーブルが存在しない場合は作成"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS room_messages (
                    id SERIAL PRIMARY KEY,
                    room_id BIGINT NOT NULL,
                    message_id VARCHAR(50) NOT NULL UNIQUE,
                    account_id BIGINT NOT NULL,
                    account_name VARCHAR(255),
                    body TEXT,
                    send_time TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_room_messages_room_id ON room_messages(room_id);
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_room_messages_send_time ON room_messages(room_id, send_time DESC);
            """))
            print("✅ room_messagesテーブルの確認/作成完了")
    except Exception as e:
        print(f"⚠️ room_messagesテーブル作成エラー: {e}")
        traceback.print_exc()

def ensure_processed_messages_table():
    """processed_messagesテーブルが存在しない場合は作成（二重処理防止の要）"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id VARCHAR(50) PRIMARY KEY,
                    room_id BIGINT NOT NULL,
                    processed_at TIMESTAMP WITH TIME ZONE NOT NULL
                );
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_processed_messages_room_id 
                ON processed_messages(room_id);
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_processed_messages_processed_at 
                ON processed_messages(processed_at);
            """))
            print("✅ processed_messagesテーブルの確認/作成完了")
    except Exception as e:
        print(f"⚠️ processed_messagesテーブル作成エラー: {e}")
        traceback.print_exc()

def mark_as_processed(message_id, room_id):
    """処理済みとしてマーク（PostgreSQL版）"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO processed_messages (message_id, room_id, processed_at)
                    VALUES (:message_id, :room_id, :processed_at)
                    ON CONFLICT (message_id) DO NOTHING
                """),
                {
                    "message_id": message_id,
                    "room_id": room_id,
                    "processed_at": datetime.now(timezone.utc)
                }
            )
    except Exception as e:
        print(f"処理済みマークエラー: {e}")
        traceback.print_exc()


# =====================================================
# ===== 遅延管理機能（P1-020〜P1-022, P1-030） =====
# =====================================================

def ensure_overdue_tables():
    """遅延管理用テーブルが存在しない場合は作成

    ★★★ v10.1.4 ★★★
    - notification_logsテーブルの存在確認を追加
    - 各テーブル作成を個別トランザクションで実行（エラー耐性向上）
    """
    pool = get_pool()

    # =====================================================
    # ★★★ v10.1.4: notification_logs（汎用通知ログ）★★★
    # =====================================================
    try:
        with pool.connect() as conn:
            result = conn.execute(sqlalchemy.text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'notification_logs'
                )
            """))
            notification_logs_exists = result.scalar()

        if notification_logs_exists:
            print("✅ notification_logsテーブル既存（スキップ）")
            # v10.1.4: metadataカラムがない場合は追加（スキーマ補完）
            try:
                with pool.begin() as conn:
                    conn.execute(sqlalchemy.text("""
                        ALTER TABLE notification_logs
                        ADD COLUMN IF NOT EXISTS metadata JSONB
                    """))
                print("✅ metadataカラム確認/追加完了")
            except Exception as e:
                print(f"⚠️ metadataカラム追加エラー（無視）: {e}")
            # ★★★ v10.14.2: check_notification_type制約を更新（goal通知追加）★★★
            try:
                with pool.begin() as conn:
                    conn.execute(sqlalchemy.text("""
                        ALTER TABLE notification_logs DROP CONSTRAINT IF EXISTS check_notification_type
                    """))
                    conn.execute(sqlalchemy.text("""
                        ALTER TABLE notification_logs ADD CONSTRAINT check_notification_type
                        CHECK (notification_type IN (
                            'task_reminder', 'task_overdue', 'task_escalation',
                            'deadline_alert', 'escalation_alert', 'dm_unavailable',
                            'goal_daily_check', 'goal_daily_reminder', 'goal_morning_feedback',
                            'goal_team_summary', 'goal_consecutive_unanswered'
                        ))
                    """))
                print("✅ check_notification_type制約更新完了（goal通知対応）")
            except Exception as e:
                print(f"⚠️ check_notification_type制約更新エラー（無視）: {e}")
            # ★★★ v10.14.2: target_idをBIGINT→TEXTに変更（UUID対応）★★★
            try:
                with pool.begin() as conn:
                    # target_idの型を確認
                    result = conn.execute(sqlalchemy.text("""
                        SELECT data_type FROM information_schema.columns
                        WHERE table_name = 'notification_logs' AND column_name = 'target_id'
                    """))
                    row = result.fetchone()
                    if row and row[0] == 'bigint':
                        # BIGINTの場合はTEXTに変更（既存データはTEXTに自動キャスト）
                        conn.execute(sqlalchemy.text("""
                            ALTER TABLE notification_logs
                            ALTER COLUMN target_id TYPE TEXT USING target_id::TEXT
                        """))
                        print("✅ target_idカラムをBIGINT→TEXTに変更完了（UUID対応）")
                    else:
                        print("✅ target_idカラム確認完了（TEXT）")
            except Exception as e:
                print(f"⚠️ target_idカラム変更エラー（無視）: {e}")
        else:
            with pool.begin() as conn:
                conn.execute(sqlalchemy.text("""
                    CREATE TABLE notification_logs (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        organization_id VARCHAR(100) DEFAULT 'org_soulsyncs',
                        notification_type VARCHAR(50) NOT NULL,
                        target_type VARCHAR(50) NOT NULL,
                        target_id TEXT,  -- BIGINTから変更: task_id（数値）とuser_id（UUID）両方対応
                        notification_date DATE NOT NULL,
                        sent_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        status VARCHAR(20) NOT NULL,
                        error_message TEXT,
                        retry_count INTEGER DEFAULT 0,
                        channel VARCHAR(20),
                        channel_target VARCHAR(255),
                        metadata JSONB,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        created_by VARCHAR(100),
                        UNIQUE(organization_id, target_type, target_id, notification_date, notification_type)
                    )
                """))
                conn.execute(sqlalchemy.text(
                    "CREATE INDEX idx_notification_logs_org ON notification_logs(organization_id)"
                ))
                conn.execute(sqlalchemy.text(
                    "CREATE INDEX idx_notification_logs_target ON notification_logs(target_type, target_id)"
                ))
                conn.execute(sqlalchemy.text(
                    "CREATE INDEX idx_notification_logs_date ON notification_logs(notification_date)"
                ))
                conn.execute(sqlalchemy.text(
                    "CREATE INDEX idx_notification_logs_status ON notification_logs(status) WHERE status = 'failed'"
                ))
            print("✅ notification_logsテーブル新規作成完了（v10.1.4）")
    except Exception as e:
        print(f"⚠️ notification_logsテーブル確認/作成エラー（無視して続行）: {e}")

    # =====================================================
    # 旧テーブル（後方互換性のため残す）
    # =====================================================
    try:
        with pool.begin() as conn:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS task_overdue_reminders (
                    id SERIAL PRIMARY KEY,
                    task_id BIGINT NOT NULL,
                    account_id BIGINT NOT NULL,
                    reminder_date DATE NOT NULL,
                    overdue_days INTEGER NOT NULL,
                    escalated BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(task_id, reminder_date)
                )
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_overdue_reminders_task_id
                ON task_overdue_reminders(task_id)
            """))
    except Exception as e:
        print(f"⚠️ task_overdue_remindersテーブル作成エラー（無視）: {e}")

    try:
        with pool.begin() as conn:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS task_limit_changes (
                    id SERIAL PRIMARY KEY,
                    task_id BIGINT NOT NULL,
                    old_limit_time BIGINT,
                    new_limit_time BIGINT,
                    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    reason_asked BOOLEAN DEFAULT FALSE,
                    reason_received BOOLEAN DEFAULT FALSE,
                    reason_text TEXT,
                    reported_to_admin BOOLEAN DEFAULT FALSE
                )
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_limit_changes_task_id
                ON task_limit_changes(task_id)
            """))
    except Exception as e:
        print(f"⚠️ task_limit_changesテーブル作成エラー（無視）: {e}")

    try:
        with pool.begin() as conn:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS dm_room_cache (
                    account_id BIGINT PRIMARY KEY,
                    dm_room_id BIGINT NOT NULL,
                    cached_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """))
    except Exception as e:
        print(f"⚠️ dm_room_cacheテーブル作成エラー（無視）: {e}")

    try:
        with pool.begin() as conn:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS task_escalations (
                    id SERIAL PRIMARY KEY,
                    task_id BIGINT NOT NULL,
                    escalated_date DATE NOT NULL,
                    escalated_to_requester BOOLEAN DEFAULT FALSE,
                    escalated_to_admin BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(task_id, escalated_date)
                )
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_task_escalations_task_id
                ON task_escalations(task_id)
            """))
    except Exception as e:
        print(f"⚠️ task_escalationsテーブル作成エラー（無視）: {e}")

    # =====================================================
    # ★★★ v10.12.0: chatwork_tasks にorganization_id追加（Phase 3.5）★★★
    # =====================================================
    try:
        with pool.begin() as conn:
            # organization_idカラムを追加（既存テーブルへの追加）
            conn.execute(sqlalchemy.text("""
                ALTER TABLE chatwork_tasks
                ADD COLUMN IF NOT EXISTS organization_id VARCHAR(100) DEFAULT 'org_soulsyncs'
            """))
            # department_idカラムも追加（既に存在する場合もあるがIF NOT EXISTSで安全）
            conn.execute(sqlalchemy.text("""
                ALTER TABLE chatwork_tasks
                ADD COLUMN IF NOT EXISTS department_id UUID
            """))
            # インデックス作成
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_chatwork_tasks_org_id
                ON chatwork_tasks(organization_id)
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_chatwork_tasks_dept_id
                ON chatwork_tasks(department_id)
            """))
        print("✅ chatwork_tasksテーブルにorganization_id/department_id追加完了（Phase 3.5）")
    except Exception as e:
        print(f"⚠️ chatwork_tasksカラム追加エラー（無視）: {e}")

    # =====================================================
    # ★★★ v10.1.4: データ移行 ★★★
    # =====================================================
    try:
        with pool.begin() as conn:
            migrate_legacy_to_notification_logs(conn)
    except Exception as e:
        print(f"⚠️ データ移行エラー（無視）: {e}")

    print("✅ 遅延管理テーブルの確認/作成完了")


def migrate_legacy_to_notification_logs(conn):
    """
    ★★★ v10.1.4: 既存テーブルからnotification_logsへデータ移行 ★★★

    - task_overdue_reminders → notification_logs (notification_type='task_reminder')
    - task_escalations → notification_logs (notification_type='task_escalation')

    冪等性: UNIQUE制約でON CONFLICT DO NOTHINGなので何度実行してもOK
    """
    try:
        # 移行済みチェック（notification_logsに既にデータがあるかどうか）
        result = conn.execute(sqlalchemy.text(
            "SELECT COUNT(*) FROM notification_logs WHERE notification_type = 'task_reminder'"
        ))
        existing_count = result.scalar()

        if existing_count > 0:
            print(f"✅ notification_logsに既存データあり（{existing_count}件）、移行スキップ")
            return

        # task_overdue_reminders → notification_logs
        migrated_reminders = conn.execute(sqlalchemy.text("""
            INSERT INTO notification_logs (
                organization_id,
                notification_type,
                target_type,
                target_id,
                notification_date,
                sent_at,
                status,
                channel,
                channel_target,
                metadata,
                created_at
            )
            SELECT
                'org_soulsyncs',
                'task_reminder',
                'task',
                task_id,
                reminder_date,
                created_at,
                'success',
                'chatwork',
                account_id::TEXT,
                jsonb_build_object('overdue_days', overdue_days, 'migrated_from', 'task_overdue_reminders'),
                created_at
            FROM task_overdue_reminders
            ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
            DO NOTHING
            RETURNING id
        """))
        reminder_count = len(migrated_reminders.fetchall())

        # task_escalations → notification_logs
        migrated_escalations = conn.execute(sqlalchemy.text("""
            INSERT INTO notification_logs (
                organization_id,
                notification_type,
                target_type,
                target_id,
                notification_date,
                sent_at,
                status,
                channel,
                metadata,
                created_at
            )
            SELECT
                'org_soulsyncs',
                'task_escalation',
                'task',
                task_id,
                escalated_date,
                created_at,
                'success',
                'chatwork',
                jsonb_build_object(
                    'escalated_to_requester', escalated_to_requester,
                    'escalated_to_admin', escalated_to_admin,
                    'migrated_from', 'task_escalations'
                ),
                created_at
            FROM task_escalations
            ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
            DO NOTHING
            RETURNING id
        """))
        escalation_count = len(migrated_escalations.fetchall())

        if reminder_count > 0 or escalation_count > 0:
            print(f"✅ データ移行完了: task_reminder={reminder_count}件, task_escalation={escalation_count}件")
        else:
            print("✅ 移行対象データなし")

    except Exception as e:
        print(f"⚠️ データ移行エラー（無視して続行）: {e}")


def get_all_contacts():
    """
    ★★★ v6.8.3: /contacts APIでコンタクト一覧を取得 ★★★
    ★★★ v6.8.4: fetched_okフラグ導入 & 429時もキャッシュセット ★★★
    
    ChatWork /contacts APIを使用して、全コンタクトのaccount_idとroom_id（DMルームID）を取得。
    これにより、N+1問題が完全に解消される。
    
    Returns:
        tuple: (contacts_map, fetched_ok)
            - contacts_map: {account_id: room_id} のマッピング
            - fetched_ok: True=API成功, False=API失敗（429含む）
        
    Note:
        - 429時も空dictをキャッシュ（同一実行内でリトライ連打を防止）
        - fetched_okで成功/失敗を判定（空dict=成功の可能性あり）
    """
    global _runtime_contacts_cache, _runtime_contacts_fetched_ok
    
    # 実行内キャッシュがあればそれを返す（成功/失敗問わず）
    if _runtime_contacts_cache is not None:
        status = "成功" if _runtime_contacts_fetched_ok else "失敗（キャッシュ済み）"
        print(f"✅ コンタクト一覧 メモリキャッシュ使用（{len(_runtime_contacts_cache)}件, {status}）")
        return _runtime_contacts_cache, _runtime_contacts_fetched_ok  # ★★★ v6.8.4: タプルで返す ★★★
    
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    try:
        print("🔍 /contacts APIでコンタクト一覧を取得中...")
        response = httpx.get(
            "https://api.chatwork.com/v2/contacts",
            headers={"X-ChatWorkToken": api_token},
            timeout=30.0
        )
        
        if response.status_code == 200:
            contacts = response.json()
            # {account_id: room_id} のマッピングを作成
            contacts_map = {}
            for contact in contacts:
                account_id = contact.get("account_id")
                room_id = contact.get("room_id")
                if account_id and room_id:
                    contacts_map[int(account_id)] = int(room_id)
            
            print(f"✅ コンタクト一覧取得成功: {len(contacts_map)}件")
            
            # ★★★ v6.8.4: 成功フラグをセット ★★★
            _runtime_contacts_cache = contacts_map
            _runtime_contacts_fetched_ok = True
            
            return contacts_map, True  # ★★★ v6.8.4: タプルで返す ★★★
        
        elif response.status_code == 429:
            print(f"⚠️ /contacts API レート制限に達しました")
            # ★★★ v6.8.4: 429でも空dictをキャッシュ（リトライ連打防止）★★★
            _runtime_contacts_cache = {}
            _runtime_contacts_fetched_ok = False
            return {}, False  # ★★★ v6.8.4: タプルで返す ★★★
        
        else:
            print(f"❌ /contacts API エラー: {response.status_code}")
            # ★★★ v6.8.4: エラーでも空dictをキャッシュ ★★★
            _runtime_contacts_cache = {}
            _runtime_contacts_fetched_ok = False
            return {}, False  # ★★★ v6.8.4: タプルで返す ★★★
    
    except Exception as e:
        print(f"❌ /contacts API 取得エラー: {e}")
        traceback.print_exc()
        # ★★★ v6.8.4: 例外でも空dictをキャッシュ ★★★
        _runtime_contacts_cache = {}
        _runtime_contacts_fetched_ok = False
        return {}, False  # ★★★ v6.8.4: タプルで返す ★★★


def get_direct_room(account_id):
    """
    指定アカウントとの個人チャット（ダイレクト）のroom_idを取得
    
    ★★★ v6.8.3: /contacts APIベースに完全刷新 ★★★
    - N+1問題が完全解消（API 1回で全コンタクト取得）
    - メモリキャッシュ→DBキャッシュ→/contacts APIの順で探索
    
    ★★★ v6.8.4: fetched_okフラグでネガティブキャッシュ判定 ★★★
    - 空dict判定の誤りを修正（コンタクト0件でも成功は成功）
    - 429/エラー時はネガティブキャッシュしない
    
    ★ 運用ルール: 新社員はソウルくんとコンタクト追加が必要
    """
    global _runtime_dm_cache
    
    if not account_id:
        return None
    
    account_id_int = int(account_id)
    
    # 1. まず実行内メモリキャッシュを確認（最速）
    if account_id_int in _runtime_dm_cache:
        cached_room = _runtime_dm_cache[account_id_int]
        if cached_room is not None:
            print(f"✅ DMルーム メモリキャッシュヒット: account_id={account_id}, room_id={cached_room}")
            return cached_room
        elif cached_room is None and _runtime_dm_cache.get(f"{account_id_int}_negative"):
            # ネガティブキャッシュ（API成功で本当に見つからなかった場合のみ）
            print(f"⚠️ DMルーム メモリキャッシュ: account_id={account_id} は見つからない（キャッシュ済み）")
            return None
    
    pool = get_pool()
    
    try:
        # 2. DBキャッシュを確認（API 0回で済む）
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("SELECT dm_room_id FROM dm_room_cache WHERE account_id = :account_id"),
                {"account_id": account_id_int}
            )
            cached = result.fetchone()
            if cached:
                room_id = cached[0]
                print(f"✅ DMルーム DBキャッシュヒット: account_id={account_id}, room_id={room_id}")
                # メモリキャッシュにも保存
                _runtime_dm_cache[account_id_int] = room_id
                return room_id
        
        # 3. /contacts APIで探索（API 1回で全コンタクト取得）
        print(f"🔍 DMルーム探索開始: account_id={account_id}")
        contacts_map, fetched_ok = get_all_contacts()  # ★★★ v6.8.5: タプルで受け取る ★★★
        
        if account_id_int in contacts_map:
            room_id = contacts_map[account_id_int]
            print(f"✅ DMルーム発見（/contacts API）: account_id={account_id}, room_id={room_id}")
            
            # メモリキャッシュに保存
            _runtime_dm_cache[account_id_int] = room_id
            
            # DBにキャッシュ保存
            try:
                with pool.begin() as conn:
                    conn.execute(
                        sqlalchemy.text("""
                            INSERT INTO dm_room_cache (account_id, dm_room_id)
                            VALUES (:account_id, :dm_room_id)
                            ON CONFLICT (account_id) DO UPDATE SET 
                                dm_room_id = :dm_room_id,
                                cached_at = CURRENT_TIMESTAMP
                        """),
                        {"account_id": account_id_int, "dm_room_id": room_id}
                    )
            except Exception as e:
                print(f"⚠️ DMキャッシュ保存エラー（続行）: {e}")
            
            return room_id
        
        # 4. 見つからなかった場合
        print(f"❌ DMルームが見つかりません: account_id={account_id}")
        print(f"   → この人とソウルくんがコンタクト追加されていない可能性があります")
        
        # ★★★ v6.8.5: ローカル変数fetched_okで判定 ★★★
        # API成功時のみネガティブキャッシュ（429/エラー時はキャッシュしない）
        if fetched_ok:
            _runtime_dm_cache[account_id_int] = None
            _runtime_dm_cache[f"{account_id_int}_negative"] = True
        
        return None
        
    except Exception as e:
        print(f"❌ DMルーム取得エラー: {e}")
        traceback.print_exc()
        return None


def cache_all_contacts_to_db():
    """
    ★★★ v6.8.3: /contacts APIで全コンタクトをDBにキャッシュ ★★★
    
    process_overdue_tasks()の開始時に呼び出すと、
    以降のget_direct_room()はDBキャッシュヒットで高速化される。
    """
    pool = get_pool()
    
    try:
        contacts_map, fetched_ok = get_all_contacts()  # ★★★ v6.8.4: タプルで受け取る ★★★
        
        if not fetched_ok:
            print("⚠️ コンタクト一覧取得失敗のため、DBキャッシュをスキップ")
            return
        
        if not contacts_map:
            print("⚠️ コンタクト一覧が空のため、DBキャッシュをスキップ（0件）")
            return
        
        cached_count = 0
        with pool.begin() as conn:
            for account_id, room_id in contacts_map.items():
                try:
                    conn.execute(
                        sqlalchemy.text("""
                            INSERT INTO dm_room_cache (account_id, dm_room_id)
                            VALUES (:account_id, :dm_room_id)
                            ON CONFLICT (account_id) DO UPDATE SET 
                                dm_room_id = :dm_room_id,
                                cached_at = CURRENT_TIMESTAMP
                        """),
                        {"account_id": account_id, "dm_room_id": room_id}
                    )
                    cached_count += 1
                except Exception as e:
                    print(f"⚠️ DMキャッシュ保存エラー: {e}")
        
        print(f"✅ 全コンタクトをDBキャッシュ完了: {cached_count}件")
        
    except Exception as e:
        print(f"❌ コンタクトDBキャッシュエラー: {e}")
        traceback.print_exc()


def notify_dm_not_available(person_name, account_id, tasks, action_type):
    """
    DMが送れない場合にバッファに追加（まとめ送信用）
    
    ★★★ v6.8.3: バッファ方式に変更（per-room制限回避）★★★
    実際の送信はflush_dm_unavailable_notifications()で行う
    
    Args:
        person_name: 対象者の名前
        account_id: 対象者のaccount_id
        tasks: 関連タスクのリスト
        action_type: "督促" or "エスカレーション" or "期限変更質問"
    """
    global _dm_unavailable_buffer
    
    _dm_unavailable_buffer.append({
        "person_name": person_name,
        "account_id": account_id,
        "tasks": tasks,
        "action_type": action_type
    })
    print(f"📝 DM不可通知をバッファに追加: {person_name}さん（{action_type}）")


def flush_dm_unavailable_notifications():
    """
    ★★★ v6.8.3: バッファに溜まったDM不可通知をまとめて1通で送信 ★★★

    これにより、per-room制限（10秒10回）を回避できる。
    process_overdue_tasks()の最後に呼び出す。

    ★★★ v10.2.0: テストモード対応 ★★★
    - DRY_RUN=true: 送信せずログ出力のみ
    - TEST_ROOM_ID: 送信先を差し替え
    """
    global _dm_unavailable_buffer

    if not _dm_unavailable_buffer:
        return

    print(f"📤 DM不可通知をまとめて送信（{len(_dm_unavailable_buffer)}件）")

    # まとめメッセージを作成
    message_lines = ["[info][title]⚠️ DM送信できなかった通知一覧[/title]"]
    message_lines.append(f"以下の{len(_dm_unavailable_buffer)}名にDMを送信できませんでした：\n")

    for i, item in enumerate(_dm_unavailable_buffer[:20], 1):  # 最大20件まで
        person_name = item["person_name"]
        account_id = item["account_id"]
        action_type = item["action_type"]
        tasks = item.get("tasks", [])

        # タスク情報（1件のみ表示）
        task_hint = ""
        if tasks and len(tasks) > 0:
            body = tasks[0].get("body", "")
            body_short = (body[:15] + "...") if len(body) > 15 else body
            task_hint = f"「{body_short}」"

        message_lines.append(f"{i}. {person_name}（ID:{account_id}）- {action_type} {task_hint}")

    if len(_dm_unavailable_buffer) > 20:
        message_lines.append(f"\n...他{len(_dm_unavailable_buffer) - 20}名")

    message_lines.append("\n【対応】")
    message_lines.append("ChatWorkで上記の方々がソウルくんをコンタクト追加するか、")
    message_lines.append("管理者がソウルくんアカウントからコンタクト追加してください。[/info]")

    message = "\n".join(message_lines)

    # ★★★ v10.2.0: テストモード対応 ★★★
    target_room_id = get_effective_admin_room()

    if DRY_RUN:
        log_dry_run_message(
            action_type="DM不可通知（管理部）",
            recipient=f"管理部（room_id={target_room_id}）",
            message_preview=message
        )
        print(f"⏭️ [DRY_RUN] 管理部へのDM不可通知をスキップ（{len(_dm_unavailable_buffer)}件）")
        _dm_unavailable_buffer = []
        return

    try:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        response = httpx.post(
            f"https://api.chatwork.com/v2/rooms/{target_room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            data={"body": message},
            timeout=10.0
        )

        if response.status_code == 200:
            room_note = f"（TEST_ROOM_ID）" if TEST_ROOM_ID else ""
            print(f"✅ 管理部へのDM不可通知まとめ送信成功（{len(_dm_unavailable_buffer)}件）{room_note}")
        else:
            print(f"❌ 管理部へのDM不可通知まとめ送信失敗: {response.status_code}")
    except Exception as e:
        print(f"❌ 管理部通知エラー: {e}")

    # バッファをクリア
    _dm_unavailable_buffer = []


def report_unassigned_overdue_tasks(tasks):
    """
    担当者未設定の遅延タスクを管理部に報告

    ★★★ v10.2.0: テストモード対応 ★★★
    - DRY_RUN=true: 送信せずログ出力のみ
    - TEST_ROOM_ID: 送信先を差し替え
    """
    if not tasks:
        return

    message_lines = ["[info][title]⚠️ 担当者未設定の遅延タスク[/title]",
                     "以下のタスクは担当者が設定されておらず、督促できません：\n"]

    for i, task in enumerate(tasks[:10], 1):  # 最大10件まで
        # ★★★ v10.17.1: lib/prepare_task_display_text()で途切れ防止 ★★★
        clean_body = clean_task_body(task["body"])
        if USE_TEXT_UTILS_LIB:
            body_short = lib_prepare_task_display_text(clean_body, max_length=40)
        else:
            body_short = prepare_task_display_text(clean_body, max_length=40)

        overdue_days = get_overdue_days(task["limit_time"])
        limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"
        room_name = task.get("room_name") or "（不明）"

        message_lines.append(f"{i}. 「{body_short}」")
        message_lines.append(f"   📍 {room_name} | 期限: {limit_date} | {overdue_days}日超過")

    if len(tasks) > 10:
        message_lines.append(f"\n...他{len(tasks) - 10}件")

    message_lines.append("\n担当者を設定してくださいウル🐺[/info]")
    message = "\n".join(message_lines)

    # ★★★ v10.2.0: テストモード対応 ★★★
    target_room_id = get_effective_admin_room()

    if DRY_RUN:
        log_dry_run_message(
            action_type="担当者未設定タスク報告（管理部）",
            recipient=f"管理部（room_id={target_room_id}）",
            message_preview=message
        )
        print(f"⏭️ [DRY_RUN] 担当者未設定タスク報告をスキップ（{len(tasks)}件）")
        return

    try:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        response = httpx.post(
            f"https://api.chatwork.com/v2/rooms/{target_room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            data={"body": message},
            timeout=10.0
        )

        if response.status_code == 200:
            room_note = f"（TEST_ROOM_ID）" if TEST_ROOM_ID else ""
            print(f"✅ 担当者未設定タスク報告送信成功（{len(tasks)}件）{room_note}")
        else:
            print(f"❌ 担当者未設定タスク報告送信失敗: {response.status_code}")
    except Exception as e:
        print(f"❌ 担当者未設定タスク報告エラー: {e}")


def get_overdue_days(limit_time):
    """期限超過日数を計算"""
    if not limit_time:
        return 0
    
    now = datetime.now(JST)
    today = now.date()
    
    # ★★★ v6.8.6: int/float両対応 ★★★
    try:
        if isinstance(limit_time, (int, float)):
            limit_date = datetime.fromtimestamp(int(limit_time), tz=JST).date()
        elif hasattr(limit_time, 'date'):
            limit_date = limit_time.date()
        else:
            print(f"⚠️ get_overdue_days: 不明なlimit_time型: {type(limit_time)}")
            return 0
    except Exception as e:
        print(f"⚠️ get_overdue_days: 変換エラー: {limit_time}, error={e}")
        return 0
    
    delta = (today - limit_date).days
    return max(0, delta)


def process_overdue_tasks():
    """
    遅延タスクを処理：督促送信 + エスカレーション
    毎日8:30に実行（remind_tasksから呼び出し）

    ★★★ v10.2.0: テストモード対応 ★★★
    - DRY_RUN=true: 送信せずログ出力のみ
    - TEST_ACCOUNT_ID: 指定ユーザー宛のみ実際に送信
    - TEST_ROOM_ID: グループ送信先を差し替え
    """
    global _runtime_dm_cache, _runtime_direct_rooms, _runtime_contacts_cache, _runtime_contacts_fetched_ok, _dm_unavailable_buffer

    print("=" * 50)
    print("🔔 遅延タスク処理開始")
    print("=" * 50)

    # ★★★ v10.2.0: テストモード状態をログ出力 ★★★
    log_test_mode_status()

    # ★★★ v6.8.4: 実行開始時にメモリキャッシュをリセット ★★★
    _runtime_dm_cache = {}
    _runtime_direct_rooms = None
    _runtime_contacts_cache = None
    _runtime_contacts_fetched_ok = None  # v6.8.4追加
    _dm_unavailable_buffer = []  # バッファもリセット
    print("✅ メモリキャッシュをリセット")
    
    try:
        # テーブル確認
        ensure_overdue_tables()
        
        pool = get_pool()
        now = datetime.now(JST)
        today = now.date()
        
        # 期限超過の未完了タスクを取得（担当者ごとにグループ化するため）
        with pool.connect() as conn:
            result = conn.execute(sqlalchemy.text("""
                SELECT 
                    task_id, room_id, assigned_to_account_id, assigned_by_account_id,
                    body, limit_time, assigned_to_name, assigned_by_name
                FROM chatwork_tasks
                WHERE status = 'open'
                  AND skip_tracking = FALSE
                  AND limit_time IS NOT NULL
                  AND limit_time < :today_timestamp
                ORDER BY assigned_to_account_id, limit_time
            """), {"today_timestamp": int(datetime.combine(today, datetime.min.time()).replace(tzinfo=JST).timestamp())})
            
            overdue_tasks = result.fetchall()
        
        if not overdue_tasks:
            print("✅ 期限超過タスクはありません")
            return
        
        print(f"📋 期限超過タスク数: {len(overdue_tasks)}")
        
        # 担当者ごとにグループ化
        tasks_by_assignee = {}
        unassigned_tasks = []  # ★ v6.8.1: 担当者未設定のタスク
        
        for task in overdue_tasks:
            account_id = task[2]  # assigned_to_account_id
            
            # ★ NULLチェック: 担当者未設定のタスクは別管理
            if account_id is None:
                unassigned_tasks.append({
                    "task_id": task[0],
                    "room_id": task[1],
                    "assigned_to_account_id": task[2],
                    "assigned_by_account_id": task[3],
                    "body": task[4],
                    "limit_time": task[5],
                    "assigned_to_name": task[6] or "（未設定）",
                    "assigned_by_name": task[7]
                })
                continue
            
            if account_id not in tasks_by_assignee:
                tasks_by_assignee[account_id] = []
            tasks_by_assignee[account_id].append({
                "task_id": task[0],
                "room_id": task[1],
                "assigned_to_account_id": task[2],
                "assigned_by_account_id": task[3],
                "body": task[4],
                "limit_time": task[5],
                "assigned_to_name": task[6],
                "assigned_by_name": task[7]
            })
        
        # ★ 担当者未設定タスクがあれば管理部に報告
        if unassigned_tasks:
            report_unassigned_overdue_tasks(unassigned_tasks)
        
        # 担当者ごとに個人チャットへ督促送信
        for account_id, tasks in tasks_by_assignee.items():
            send_overdue_reminder_to_dm(account_id, tasks, today)
        
        # エスカレーション処理（3日以上超過）
        process_escalations(overdue_tasks, today)
        
        # ★★★ v6.8.3: DM不可通知をまとめて送信 ★★★
        flush_dm_unavailable_notifications()
        
        print("=" * 50)
        print("🔔 遅延タスク処理完了")
        print("=" * 50)
        
    except Exception as e:
        print(f"❌ 遅延タスク処理エラー: {e}")
        traceback.print_exc()
        # エラー時もバッファをフラッシュ
        try:
            flush_dm_unavailable_notifications()
        except:
            pass


def send_overdue_reminder_to_dm(account_id, tasks, today):
    """
    担当者の個人チャットに遅延タスクをまとめて督促送信

    ★ v6.8.1変更点:
    - DMが見つからない場合は管理部に通知（フォールバック）

    ★★★ v10.1.4変更点 ★★★
    - notification_logsテーブルを使用（汎用通知ログ対応）
    - UPSERT仕様で冪等性確保

    ★★★ v10.2.0: テストモード対応 ★★★
    - DRY_RUN=true: 送信せずログ出力のみ
    - TEST_ACCOUNT_ID: 指定ユーザー宛のみ実際に送信
    """
    if not tasks:
        return

    assignee_name = tasks[0].get("assigned_to_name", "担当者")

    # ★★★ v10.2.0: テストモードチェック ★★★
    if TEST_ACCOUNT_ID and str(account_id) != str(TEST_ACCOUNT_ID):
        print(f"⏭️ [TEST_MODE] {assignee_name}さん（ID:{account_id}）はスキップ（TEST_ACCOUNT_ID={TEST_ACCOUNT_ID}以外）")
        return

    # 個人チャットを取得
    dm_room_id = get_direct_room(account_id)
    if not dm_room_id:
        # ★ フォールバック: 管理部に「DMできない」ことを通知
        print(f"⚠️ {assignee_name}さんの個人チャットが取得できませんでした → 管理部に通知")
        notify_dm_not_available(assignee_name, account_id, tasks, "督促")
        return

    # ★★★ v10.1.4: notification_logsで今日の督促済みを確認 ★★★
    pool = get_pool()
    with pool.connect() as conn:
        task_ids = [t["task_id"] for t in tasks]
        stmt = sqlalchemy.text("""
            SELECT target_id FROM notification_logs
            WHERE target_id IN :task_ids
              AND notification_date = :today
              AND notification_type = 'task_reminder'
              AND target_type = 'task'
              AND status = 'success'
        """).bindparams(bindparam("task_ids", expanding=True))
        result = conn.execute(stmt, {"task_ids": task_ids, "today": today})
        already_reminded = set(row[0] for row in result.fetchall())

    # 未督促のタスクだけ抽出
    tasks_to_remind = [t for t in tasks if t["task_id"] not in already_reminded]

    if not tasks_to_remind:
        print(f"✅ {assignee_name}さんへの督促は今日既に送信済み")
        return

    # メッセージ作成
    # ★★★ v10.11.0: 新フォーマットに統一（🐺 タスクリマインド形式）★★★
    message_lines = [
        "🐺 タスクリマインド",
        f"{assignee_name}さん、期限超過のタスクがありますウル！",
        "",
        "【⚠️ 期限超過】"
    ]

    for i, task in enumerate(tasks_to_remind, 1):
        overdue_days = get_overdue_days(task["limit_time"])
        limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"

        # ★★★ v10.17.1: lib/prepare_task_display_text()で途切れ防止 ★★★
        clean_body = clean_task_body(task["body"])
        if USE_TEXT_UTILS_LIB:
            body_short = lib_prepare_task_display_text(clean_body, max_length=40)
        else:
            body_short = prepare_task_display_text(clean_body, max_length=40)

        # room_nameを取得（なければ「（不明）」）
        room_name = task.get("room_name") or "（不明）"

        message_lines.append(f"{i}. {body_short}")
        message_lines.append(f"   📍 {room_name} | 期限: {limit_date} | {overdue_days}日超過")

    message_lines.append("")
    message_lines.append("確認をお願いしますウル！")
    message = "\n".join(message_lines)

    # ★★★ v10.2.0: DRY_RUNモードチェック ★★★
    if DRY_RUN:
        log_dry_run_message(
            action_type="督促DM送信",
            recipient=f"{assignee_name}さん（account_id={account_id}, room_id={dm_room_id}）",
            message_preview=message
        )
        # DRY_RUNでもnotification_logsにはskippedとして記録
        status = "skipped"
        error_msg = "DRY_RUN mode"
    else:
        # 実際に送信
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        response = httpx.post(
            f"https://api.chatwork.com/v2/rooms/{dm_room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            data={"body": message},
            timeout=10.0
        )
        status = "success" if response.status_code == 200 else "failed"
        error_msg = None if response.status_code == 200 else f"HTTP {response.status_code}"

    with pool.begin() as conn:
        for task in tasks_to_remind:
            overdue_days = get_overdue_days(task["limit_time"])
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO notification_logs (
                        organization_id,
                        notification_type,
                        target_type,
                        target_id,
                        notification_date,
                        sent_at,
                        status,
                        error_message,
                        retry_count,
                        channel,
                        channel_target,
                        metadata
                    )
                    VALUES (
                        'org_soulsyncs',
                        'task_reminder',
                        'task',
                        :task_id,
                        :notification_date,
                        NOW(),
                        :status,
                        :error_message,
                        0,
                        'chatwork',
                        :channel_target,
                        :metadata
                    )
                    ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
                    DO UPDATE SET
                        status = EXCLUDED.status,
                        sent_at = NOW(),
                        error_message = EXCLUDED.error_message,
                        retry_count = notification_logs.retry_count + 1,
                        updated_at = NOW()
                """),
                {
                    "task_id": task["task_id"],
                    "notification_date": today,
                    "status": status,
                    "error_message": error_msg,
                    "channel_target": str(dm_room_id),
                    "metadata": json.dumps({
                        "overdue_days": overdue_days,
                        "account_id": account_id,
                        "assignee_name": assignee_name,
                        "dry_run": DRY_RUN  # v10.2.0: テストモード記録
                    })
                }
            )

    # ★★★ v10.2.0: テストモード対応ログ ★★★
    if status == "success":
        print(f"✅ {assignee_name}さんへの督促送信成功（{len(tasks_to_remind)}件）→ notification_logs記録")
    elif status == "skipped":
        print(f"⏭️ [DRY_RUN] {assignee_name}さんへの督促をスキップ（{len(tasks_to_remind)}件）→ notification_logs記録")
    else:
        print(f"❌ {assignee_name}さんへの督促送信失敗: {error_msg} → notification_logs記録")


def process_escalations(overdue_tasks, today):
    """
    3日以上超過のタスクをエスカレーション（依頼者+管理部に報告）

    ★★★ v6.8.2変更点 ★★★
    - task_escalationsテーブルを使用（督促履歴と分離）
    - エスカレーション送信前に必ず記録を作成（スパム防止）

    ★★★ v10.1.4変更点 ★★★
    - notification_logsテーブルを使用（汎用通知ログ対応）
    - UPSERT仕様で冪等性確保
    """
    pool = get_pool()

    # 3日以上超過のタスクを抽出
    escalation_tasks = []
    for task in overdue_tasks:
        task_dict = {
            "task_id": task[0],
            "room_id": task[1],
            "assigned_to_account_id": task[2],
            "assigned_by_account_id": task[3],
            "body": task[4],
            "limit_time": task[5],
            "assigned_to_name": task[6],
            "assigned_by_name": task[7],
            # ★★★ v10.14.0: room_nameを追加（タプルに9番目の要素がある場合）★★★
            "room_name": task[8] if len(task) > 8 else None
        }
        overdue_days = get_overdue_days(task_dict["limit_time"])
        if overdue_days >= ESCALATION_DAYS:
            task_dict["overdue_days"] = overdue_days
            escalation_tasks.append(task_dict)

    if not escalation_tasks:
        print("✅ エスカレーション対象タスクはありません")
        return

    # ★★★ v10.1.4: notification_logsで今日のエスカレーション済みを確認 ★★★
    with pool.connect() as conn:
        task_ids = [t["task_id"] for t in escalation_tasks]
        stmt = sqlalchemy.text("""
            SELECT target_id FROM notification_logs
            WHERE target_id IN :task_ids
              AND notification_date = :today
              AND notification_type = 'task_escalation'
              AND target_type = 'task'
              AND status = 'success'
        """).bindparams(bindparam("task_ids", expanding=True))
        result = conn.execute(stmt, {"task_ids": task_ids, "today": today})
        already_escalated = set(row[0] for row in result.fetchall())

    tasks_to_escalate = [t for t in escalation_tasks if t["task_id"] not in already_escalated]

    if not tasks_to_escalate:
        print("✅ エスカレーションは今日既に送信済み")
        return

    print(f"🚨 エスカレーション対象: {len(tasks_to_escalate)}件")

    # 依頼者ごとにグループ化して報告
    tasks_by_requester = {}
    for task in tasks_to_escalate:
        requester_id = task["assigned_by_account_id"]
        if requester_id and requester_id not in tasks_by_requester:
            tasks_by_requester[requester_id] = []
        if requester_id:
            tasks_by_requester[requester_id].append(task)

    # 依頼者ごとの送信結果を記録
    requester_success_map = {}  # {requester_id: bool}
    for requester_id, tasks in tasks_by_requester.items():
        requester_success_map[requester_id] = send_escalation_to_requester(requester_id, tasks)

    # 管理部への報告（まとめて1通）
    admin_success = send_escalation_to_admin(tasks_to_escalate)

    # ★★★ v10.1.4: notification_logsに記録（UPSERT仕様）★★★
    with pool.begin() as conn:
        for task in tasks_to_escalate:
            task_requester_id = task["assigned_by_account_id"]
            task_requester_success = requester_success_map.get(task_requester_id, False)

            # 成功判定: 依頼者への送信または管理部への送信のいずれかが成功
            overall_success = task_requester_success or admin_success
            status = "success" if overall_success else "failed"

            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO notification_logs (
                        organization_id,
                        notification_type,
                        target_type,
                        target_id,
                        notification_date,
                        sent_at,
                        status,
                        channel,
                        metadata
                    )
                    VALUES (
                        'org_soulsyncs',
                        'task_escalation',
                        'task',
                        :task_id,
                        :notification_date,
                        NOW(),
                        :status,
                        'chatwork',
                        :metadata
                    )
                    ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
                    DO UPDATE SET
                        status = EXCLUDED.status,
                        sent_at = NOW(),
                        metadata = EXCLUDED.metadata,
                        retry_count = notification_logs.retry_count + 1,
                        updated_at = NOW()
                """),
                {
                    "task_id": task["task_id"],
                    "notification_date": today,
                    "status": status,
                    "metadata": json.dumps({
                        "overdue_days": task["overdue_days"],
                        "escalated_to_requester": task_requester_success,
                        "escalated_to_admin": admin_success,
                        "requester_id": task_requester_id,
                        "assignee_name": task.get("assigned_to_name")
                    })
                }
            )

    print(f"✅ エスカレーション完了 → notification_logs記録（{len(tasks_to_escalate)}件）")


def send_escalation_to_requester(requester_id, tasks):
    """依頼者へのエスカレーション報告

    ★ v6.8.1変更点:
    - DMが見つからない場合は管理部に通知（フォールバック）

    ★ v6.8.2変更点:
    - 成功/失敗を戻り値で返す

    ★★★ v10.2.0: テストモード対応 ★★★
    - DRY_RUN=true: 送信せずログ出力のみ
    - TEST_ACCOUNT_ID: 指定ユーザー宛のみ実際に送信

    Returns:
        bool: 送信成功ならTrue
    """
    if not tasks:
        return False

    # 依頼者名を取得（tasksから推測）
    requester_name = f"依頼者(ID:{requester_id})"

    # ★★★ v10.2.0: テストモードチェック ★★★
    if TEST_ACCOUNT_ID and str(requester_id) != str(TEST_ACCOUNT_ID):
        print(f"⏭️ [TEST_MODE] {requester_name}へのエスカレーションはスキップ（TEST_ACCOUNT_ID={TEST_ACCOUNT_ID}以外）")
        return False

    dm_room_id = get_direct_room(requester_id)
    if not dm_room_id:
        # ★ フォールバック: 管理部に「DMできない」ことを通知
        print(f"⚠️ {requester_name}の個人チャットが取得できませんでした → 管理部に通知")
        notify_dm_not_available(requester_name, requester_id, tasks, "エスカレーション")
        return False

    # ★★★ v10.11.0: 新フォーマットに統一 ★★★
    message_lines = [
        "🐺 タスク遅延のお知らせ",
        "あなたが依頼したタスクが3日以上遅延していますウル！",
        "",
        "【⚠️ 遅延タスク】"
    ]

    for i, task in enumerate(tasks, 1):
        assignee = task.get("assigned_to_name", "担当者")

        # ★★★ v10.17.1: lib/prepare_task_display_text()で途切れ防止 ★★★
        clean_body = clean_task_body(task["body"])
        if USE_TEXT_UTILS_LIB:
            body_short = lib_prepare_task_display_text(clean_body, max_length=40)
        else:
            body_short = prepare_task_display_text(clean_body, max_length=40)

        limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"
        room_name = task.get("room_name") or "（不明）"

        message_lines.append(f"{i}. {body_short}")
        message_lines.append(f"   📍 {room_name} | 担当: {assignee} | 期限: {limit_date} | {task['overdue_days']}日超過")

    message_lines.append("")
    message_lines.append("ソウルくんから毎日督促していますが、対応が必要かもしれませんウル🐺")
    message = "\n".join(message_lines)

    # ★★★ v10.2.0: DRY_RUNモードチェック ★★★
    if DRY_RUN:
        log_dry_run_message(
            action_type="エスカレーション（依頼者DM）",
            recipient=f"{requester_name}（room_id={dm_room_id}）",
            message_preview=message
        )
        print(f"⏭️ [DRY_RUN] {requester_name}へのエスカレーションをスキップ")
        return True  # DRY_RUNでは成功扱い

    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    response = httpx.post(
        f"https://api.chatwork.com/v2/rooms/{dm_room_id}/messages",
        headers={"X-ChatWorkToken": api_token},
        data={"body": message},
        timeout=10.0
    )

    if response.status_code == 200:
        print(f"✅ 依頼者(ID:{requester_id})へのエスカレーション送信成功")
        return True
    else:
        print(f"❌ 依頼者(ID:{requester_id})へのエスカレーション送信失敗: {response.status_code}")
        return False


def send_escalation_to_admin(tasks):
    """管理部へのエスカレーション報告

    ★ v6.8.2変更点:
    - 成功/失敗を戻り値で返す

    ★★★ v10.2.0: テストモード対応 ★★★
    - DRY_RUN=true: 送信せずログ出力のみ
    - TEST_ROOM_ID: 送信先を差し替え

    Returns:
        bool: 送信成功ならTrue
    """
    if not tasks:
        return False

    # ★★★ v10.11.0: 新フォーマットに統一 ★★★
    message_lines = ["[info][title]📊 長期遅延タスク報告[/title]", "以下のタスクが3日以上遅延しています：\n"]

    for i, task in enumerate(tasks, 1):
        assignee = task.get("assigned_to_name", "担当者")

        # ★★★ v10.17.1: lib/prepare_task_display_text()で途切れ防止 ★★★
        clean_body = clean_task_body(task["body"])
        if USE_TEXT_UTILS_LIB:
            body_short = lib_prepare_task_display_text(clean_body, max_length=40)
        else:
            body_short = prepare_task_display_text(clean_body, max_length=40)

        limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"
        room_name = task.get("room_name") or "（不明）"

        message_lines.append(f"{i}. {assignee}さん「{body_short}」")
        message_lines.append(f"   📍 {room_name} | 期限: {limit_date} | {task['overdue_days']}日超過")

    message_lines.append("\n引き続き督促を継続しますウル🐺[/info]")
    message = "\n".join(message_lines)

    # ★★★ v10.2.0: テストモード対応 ★★★
    target_room_id = get_effective_admin_room()

    if DRY_RUN:
        log_dry_run_message(
            action_type="エスカレーション（管理部）",
            recipient=f"管理部（room_id={target_room_id}）",
            message_preview=message
        )
        print(f"⏭️ [DRY_RUN] 管理部へのエスカレーションをスキップ（{len(tasks)}件）")
        return True  # DRY_RUNでは成功扱い

    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    response = httpx.post(
        f"https://api.chatwork.com/v2/rooms/{target_room_id}/messages",
        headers={"X-ChatWorkToken": api_token},
        data={"body": message},
        timeout=10.0
    )

    if response.status_code == 200:
        room_note = f"（TEST_ROOM_ID）" if TEST_ROOM_ID else ""
        print(f"✅ 管理部へのエスカレーション送信成功（{len(tasks)}件）{room_note}")
        return True
    else:
        print(f"❌ 管理部へのエスカレーション送信失敗: {response.status_code}")
        return False


# =====================================================
# ===== タスク期限変更検知（P1-030） =====
# =====================================================

def detect_and_report_limit_changes(cursor, task_id, old_limit, new_limit, task_info):
    """
    タスクの期限変更を検知して報告
    sync_chatwork_tasks内から呼び出される
    
    ★ v6.8.1変更点:
    - UPDATE文をPostgreSQL対応（サブクエリ方式）
    - DM見つからない時のフォールバック追加
    """
    if old_limit == new_limit:
        return
    
    if old_limit is None or new_limit is None:
        return
    
    print(f"🔍 期限変更検知: task_id={task_id}, {old_limit} → {new_limit}")
    
    pool = get_pool()
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    # 変更履歴を記録
    try:
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO task_limit_changes (task_id, old_limit_time, new_limit_time)
                    VALUES (:task_id, :old_limit, :new_limit)
                """),
                {"task_id": task_id, "old_limit": old_limit, "new_limit": new_limit}
            )
    except Exception as e:
        print(f"⚠️ 期限変更履歴記録エラー: {e}")
    
    # 日付フォーマット
    old_date_str = datetime.fromtimestamp(old_limit, tz=JST).strftime("%m/%d") if old_limit else "不明"
    new_date_str = datetime.fromtimestamp(new_limit, tz=JST).strftime("%m/%d") if new_limit else "不明"
    
    # 延長日数計算
    if old_limit and new_limit:
        days_diff = (new_limit - old_limit) // 86400  # 秒→日
        diff_str = f"{abs(days_diff)}日{'延長' if days_diff > 0 else '短縮'}"
    else:
        diff_str = "変更"
    
    assignee_name = task_info.get("assigned_to_name", "担当者")
    assignee_id = task_info.get("assigned_to_account_id")
    requester_name = task_info.get("assigned_by_name", "依頼者")
    # タスク本文を整形（v10.17.1: 直接切り詰めを廃止）
    body_short = (
        lib_prepare_task_display_text(task_info["body"], max_length=30)
        if USE_TEXT_UTILS_LIB else
        prepare_task_display_text(task_info["body"], max_length=30)
    )
    
    # ① 管理部への即時報告
    admin_message = f"""[info][title]📝 タスク期限変更の検知[/title]
以下のタスクの期限が変更されました：

タスク: {body_short}
担当者: {assignee_name}
依頼者: {requester_name}
変更前: {old_date_str}
変更後: {new_date_str}（{diff_str}）

理由を確認中ですウル🐺[/info]"""
    
    response = httpx.post(
        f"https://api.chatwork.com/v2/rooms/{ADMIN_ROOM_ID}/messages",
        headers={"X-ChatWorkToken": api_token},
        data={"body": admin_message},
        timeout=10.0
    )
    
    if response.status_code == 200:
        print(f"✅ 管理部への期限変更報告送信成功")
    else:
        print(f"❌ 管理部への期限変更報告送信失敗: {response.status_code}")
    
    # ② 担当者への理由質問（個人チャット）
    if assignee_id:
        dm_room_id = get_direct_room(assignee_id)
        if dm_room_id:
            dm_message = f"""{assignee_name}さん

📝 タスクの期限変更を検知しましたウル！

タスク: {body_short}
変更前: {old_date_str} → 変更後: {new_date_str}（{diff_str}）

期限を変更した理由を教えてほしいウル🐺"""
            
            response = httpx.post(
                f"https://api.chatwork.com/v2/rooms/{dm_room_id}/messages",
                headers={"X-ChatWorkToken": api_token},
                data={"body": dm_message},
                timeout=10.0
            )
            
            if response.status_code == 200:
                print(f"✅ {assignee_name}さんへの期限変更理由質問送信成功")
                
                # ★ 理由質問済みフラグを更新（PostgreSQL対応: サブクエリ方式）
                try:
                    with pool.begin() as conn:
                        conn.execute(
                            sqlalchemy.text("""
                                UPDATE task_limit_changes 
                                SET reason_asked = TRUE 
                                WHERE id = (
                                    SELECT id FROM task_limit_changes
                                    WHERE task_id = :task_id
                                    ORDER BY detected_at DESC
                                    LIMIT 1
                                )
                            """),
                            {"task_id": task_id}
                        )
                except Exception as e:
                    print(f"⚠️ 理由質問フラグ更新エラー: {e}")
            else:
                print(f"❌ {assignee_name}さんへの期限変更理由質問送信失敗: {response.status_code}")
        else:
            # ★ フォールバック: DMが見つからない場合は管理部に追加報告
            print(f"⚠️ {assignee_name}さんの個人チャットが取得できませんでした → 管理部に通知")
            task_for_notify = [{"body": task_info["body"]}]
            notify_dm_not_available(assignee_name, assignee_id, task_for_notify, "期限変更理由質問")


@functions_framework.http
def check_reply_messages(request):
    """5分ごとに実行：返信ボタンとメンションのメッセージを検出
    
    堅牢なエラーハンドリング版 - あらゆるエッジケースに対応
    """
    try:
        print("=" * 50)
        print("🚀 ポーリング処理開始")
        print("=" * 50)
        
        # テーブルが存在することを確認（二重処理防止の要）
        try:
            ensure_room_messages_table()
            ensure_processed_messages_table()
        except Exception as e:
            print(f"⚠️ テーブル確認でエラー（続行）: {e}")
        
        processed_count = 0
        
        # ルーム一覧を取得
        try:
            rooms = get_all_rooms()
        except Exception as e:
            print(f"❌ ルーム一覧取得エラー: {e}")
            return jsonify({"status": "error", "message": f"Failed to get rooms: {str(e)}"}), 500
        
        if not rooms:
            print("⚠️ ルームが0件です")
            return jsonify({"status": "ok", "message": "No rooms found", "processed_count": 0})
        
        if not isinstance(rooms, list):
            print(f"❌ roomsが不正な型: {type(rooms)}")
            return jsonify({"status": "error", "message": f"Invalid rooms type: {type(rooms)}"}), 500
        
        print(f"📋 対象ルーム数: {len(rooms)}")
        
        # サンプルルームの詳細をログ出力（最初の5件のみ）
        for i, room in enumerate(rooms[:5]):
            try:
                room_id_sample = room.get('room_id', 'N/A') if isinstance(room, dict) else 'N/A'
                room_type_sample = room.get('type', 'N/A') if isinstance(room, dict) else 'N/A'
                room_name_sample = room.get('name', 'N/A') if isinstance(room, dict) else 'N/A'
                print(f"  📁 サンプルルーム{i+1}: room_id={room_id_sample}, type={room_type_sample}, name={room_name_sample}")
            except Exception as e:
                print(f"  ⚠️ サンプルルーム{i+1}の表示エラー: {e}")
        
        # 5分前のタイムスタンプを計算
        try:
            five_minutes_ago = int((datetime.now(JST) - timedelta(minutes=5)).timestamp())
            print(f"⏰ 5分前のタイムスタンプ: {five_minutes_ago}")
        except Exception as e:
            print(f"⚠️ タイムスタンプ計算エラー（デフォルト使用）: {e}")
            five_minutes_ago = 0
        
        # カウンター
        skipped_my = 0
        processed_rooms = 0
        error_rooms = 0
        skipped_messages = 0
        
        for room in rooms:
            room_id = None  # エラーログ用に先に定義
            
            try:
                # ルームデータの検証
                if not isinstance(room, dict):
                    print(f"⚠️ 不正なルームデータ型: {type(room)}")
                    error_rooms += 1
                    continue
                
                room_id = room.get("room_id")
                room_type = room.get("type")
                room_name = room.get("name", "不明")
                
                # room_idの検証
                if room_id is None:
                    print(f"⚠️ room_idがNone: {room}")
                    error_rooms += 1
                    continue
                
                print(f"🔍 ルームチェック開始: room_id={room_id}, type={room_type}, name={room_name}")
                
                # マイチャットをスキップ
                if room_type == "my":
                    skipped_my += 1
                    print(f"⏭️ マイチャットをスキップ: {room_id}")
                    continue
                
                processed_rooms += 1
                
                # メッセージを取得
                print(f"📞 get_room_messages呼び出し: room_id={room_id}")
                
                try:
                    messages = get_room_messages(room_id, force=True)
                except Exception as e:
                    print(f"❌ メッセージ取得エラー: room_id={room_id}, error={e}")
                    error_rooms += 1
                    continue
                
                # messagesの検証
                if messages is None:
                    print(f"⚠️ messagesがNone: room_id={room_id}")
                    messages = []
                
                if not isinstance(messages, list):
                    print(f"⚠️ messagesが不正な型: {type(messages)}, room_id={room_id}")
                    messages = []
                
                print(f"📨 ルーム {room_id} ({room_name}): {len(messages)}件のメッセージを取得")
                
                # メッセージがない場合はスキップ
                if not messages:
                    continue
                
                for msg in messages:
                    try:
                        # msgの検証
                        if not isinstance(msg, dict):
                            print(f"⚠️ 不正なメッセージデータ型: {type(msg)}")
                            skipped_messages += 1
                            continue
                        
                        # 各フィールドを安全に取得
                        message_id = msg.get("message_id")
                        body = msg.get("body")  # Noneの可能性あり
                        account_data = msg.get("account")
                        send_time = msg.get("send_time")
                        
                        # message_idの検証
                        if message_id is None:
                            print(f"⚠️ message_idがNone")
                            skipped_messages += 1
                            continue
                        
                        # accountデータの検証
                        if account_data is None or not isinstance(account_data, dict):
                            print(f"⚠️ accountデータが不正: message_id={message_id}")
                            account_id = None
                            sender_name = "ゲスト"
                        else:
                            account_id = account_data.get("account_id")
                            sender_name = account_data.get("name", "ゲスト")
                        
                        # bodyの検証と安全な処理
                        if body is None:
                            body = ""
                            print(f"⚠️ bodyがNone: message_id={message_id}")
                        
                        if not isinstance(body, str):
                            print(f"⚠️ bodyが文字列ではない: type={type(body)}, message_id={message_id}")
                            body = str(body) if body else ""
                        
                        # デバッグログ（安全なスライス）
                        print(f"🔍 メッセージチェック: message_id={message_id}")
                        print(f"   body type: {type(body)}")
                        print(f"   body length: {len(body)}")
                        
                        # 安全なbody表示（スライスエラー防止）
                        if body:
                            body_preview = body[:100] if len(body) > 100 else body
                            # 改行を置換して見やすくする
                            body_preview = body_preview.replace('\n', '\\n')
                            print(f"   body preview: {body_preview}")
                        else:
                            print(f"   body: (empty)")
                        
                        # メンション/返信チェック（安全な呼び出し）
                        try:
                            is_mention_or_reply = is_mention_or_reply_to_soulkun(body) if body else False
                            print(f"   is_mention_or_reply: {is_mention_or_reply}")
                        except Exception as e:
                            print(f"   ❌ is_mention_or_reply_to_soulkun エラー: {e}")
                            is_mention_or_reply = False
                        
                        # 5分以内のメッセージのみ処理
                        if send_time is not None:
                            try:
                                if int(send_time) < five_minutes_ago:
                                    continue
                            except (ValueError, TypeError) as e:
                                print(f"⚠️ send_time変換エラー: {send_time}, error={e}")
                        
                        # 自分自身のメッセージを無視
                        if account_id is not None and str(account_id) == MY_ACCOUNT_ID:
                            continue

                        # v10.16.0: オールメンション（toall）を無視
                        if is_toall_mention(body):
                            print(f"   ⏭️ オールメンション（toall）のため無視")
                            continue

                        # メンションまたは返信を検出
                        if not is_mention_or_reply:
                            continue

                        # 処理済みならスキップ
                        try:
                            if is_processed(message_id):
                                print(f"⏭️ すでに処理済み: message_id={message_id}")
                                continue
                        except Exception as e:
                            print(f"⚠️ 処理済みチェックエラー（続行）: {e}")
                        
                        print(f"✅ 検出成功！処理開始: room={room_id}, message_id={message_id}")
                        
                        # ★★★ 2重処理防止: 即座にマーク（他のプロセスが処理しないように） ★★★
                        mark_as_processed(message_id, room_id)
                        print(f"🔒 処理開始マーク: message_id={message_id}")
                        
                        # メッセージをDBに保存
                        try:
                            save_room_message(
                                room_id=room_id,
                                message_id=message_id,
                                account_id=account_id,
                                account_name=sender_name,
                                body=body,
                                send_time=datetime.fromtimestamp(send_time, tz=JST) if send_time else None
                            )
                        except Exception as e:
                            print(f"⚠️ メッセージ保存エラー（続行）: {e}")
                        
                        # メッセージをクリーニング
                        try:
                            clean_message = clean_chatwork_message(body) if body else ""
                        except Exception as e:
                            print(f"⚠️ メッセージクリーニングエラー: {e}")
                            clean_message = body
                        
                        if clean_message:
                            try:
                                # ★★★ pending_taskのフォローアップを最初にチェック ★★★
                                pending_response = handle_pending_task_followup(clean_message, room_id, account_id, sender_name)
                                if pending_response:
                                    print(f"📋 pending_taskのフォローアップを処理")
                                    send_chatwork_message(room_id, pending_response, None, False)
                                    processed_count += 1
                                    continue
                                
                                # 通常のWebhook処理と同じ処理を実行
                                all_persons = get_all_persons_summary()
                                all_tasks = get_tasks()
                                chatwork_users = get_all_chatwork_users()  # ★ ChatWorkユーザー一覧を取得
                                
                                # AI司令塔に判断を委ねる（AIの判断力を最大活用）
                                command = ai_commander(clean_message, all_persons, all_tasks, chatwork_users, sender_name)
                                response_language = command.get("response_language", "ja") if command else "ja"
                                
                                # アクションを実行
                                action_response = execute_action(command, sender_name, room_id, account_id)
                                
                                if action_response:
                                    send_chatwork_message(room_id, action_response, None, False)
                                else:
                                    # 通常会話として処理
                                    history = get_conversation_history(room_id, account_id)
                                    room_context = get_room_context(room_id, limit=30)
                                    
                                    context_parts = []
                                    if room_context:
                                        context_parts.append(f"【このルームの最近の会話】\n{room_context}")
                                    if all_persons:
                                        persons_str = "\n".join([f"・{p['name']}: {p['attributes']}" for p in all_persons[:5] if p.get('attributes')])
                                        if persons_str:
                                            context_parts.append(f"【覚えている人物】\n{persons_str}")
                                    
                                    context = "\n\n".join(context_parts) if context_parts else None
                                    
                                    ai_response = get_ai_response(clean_message, history, sender_name, context, response_language)
                                    
                                    if history is None:
                                        history = []
                                    history.append({"role": "user", "content": clean_message})
                                    history.append({"role": "assistant", "content": ai_response})
                                    save_conversation_history(room_id, account_id, history)
                                    
                                    send_chatwork_message(room_id, ai_response, None, False)
                                
                                processed_count += 1
                                
                            except Exception as e:
                                print(f"❌ メッセージ処理エラー: message_id={message_id}, error={e}")
                                import traceback
                                traceback.print_exc()
                    
                    except Exception as e:
                        print(f"❌ メッセージ処理中に予期しないエラー: {e}")
                        import traceback
                        traceback.print_exc()
                        skipped_messages += 1
                        continue
                
            except Exception as e:
                error_rooms += 1
                print(f"❌ ルーム {room_id} の処理中にエラー: {e}")
                import traceback
                traceback.print_exc()
                continue  # 次のルームへ
        
        # サマリーログ
        print("=" * 50)
        print(f"📊 処理サマリー:")
        print(f"   - 総ルーム数: {len(rooms)}")
        print(f"   - スキップ（マイチャット）: {skipped_my}")
        print(f"   - 処理したルーム: {processed_rooms}")
        print(f"   - エラーが発生したルーム: {error_rooms}")
        print(f"   - スキップしたメッセージ: {skipped_messages}")
        print(f"   - 処理したメッセージ: {processed_count}")
        print("=" * 50)
        print(f"✅ ポーリング完了: {processed_count}件処理")
        
        return jsonify({
            "status": "ok",
            "processed_count": processed_count,
            "rooms_checked": len(rooms),
            "skipped_my": skipped_my,
            "processed_rooms": processed_rooms,
            "error_rooms": error_rooms,
            "skipped_messages": skipped_messages
        })
        
    except Exception as e:
        print(f"❌ ポーリング全体でエラー: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================================================

def get_room_tasks(room_id, status='open'):
    """
    指定されたルームのタスク一覧を取得
    
    Args:
        room_id: ルームID
        status: タスクのステータス ('open' or 'done')
    
    Returns:
        タスクのリスト
    """
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks"
    # ★★★ v10.4.0: 全タスク同期対応 ★★★
    # assigned_by_account_id フィルタを削除し、全ユーザーが作成したタスクを取得
    params = {
        'status': status,
    }

    headers = {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}
    response = httpx.get(url, headers=headers, params=params, timeout=10.0)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to get tasks for room {room_id}: {response.status_code}")
        return []

def send_completion_notification(room_id, task, assigned_by_name):
    """
    タスク完了通知を送信（個別通知）

    ★★★ v10.15.0: 無効化 ★★★
    個別グループへの完了通知を廃止。
    代わりに remind-tasks の process_completed_tasks_summary() で
    管理部チャットに1日1回まとめて報告する方式に変更。

    Args:
        room_id: ルームID
        task: タスク情報の辞書
        assigned_by_name: 依頼者名
    """
    # v10.15.0: 個別通知を無効化（管理部への日次報告に集約）
    task_id = task.get('task_id', 'unknown')
    print(f"📝 [v10.15.0] 完了通知スキップ: task_id={task_id} (管理部への日次報告に集約)")
    return

    # --- 以下は無効化（v10.15.0以前のコード） ---
    # assigned_to_name = task.get('account', {}).get('name', '担当者')
    # task_body = task.get('body', 'タスク')
    #
    # message = f"[info][title]{assigned_to_name}さんがタスクを完了しましたウル！[/title]"
    # message += f"タスク: {task_body}\n"
    # message += f"依頼者: {assigned_by_name}さん\n"
    # message += f"お疲れ様でしたウル！[/info]"
    #
    # url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
    # data = {'body': message}
    #
    # headers = {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}
    # response = httpx.post(url, headers=headers, data=data, timeout=10.0)
    #
    # if response.status_code == 200:
    #     print(f"Completion notification sent for task {task['task_id']} in room {room_id}")
    # else:
    #     print(f"Failed to send completion notification: {response.status_code}")

def sync_room_members():
    """全ルームのメンバーをchatwork_usersテーブルに同期"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    try:
        # 全ルームを取得
        rooms = get_all_rooms()
        
        if not rooms:
            print("No rooms found")
            return
        
        pool = get_pool()
        synced_count = 0
        
        for room in rooms:
            room_id = room.get("room_id")
            room_type = room.get("type")
            
            # マイチャットはスキップ
            if room_type == "my":
                continue
            
            try:
                # ルームメンバーを取得
                response = httpx.get(
                    f"https://api.chatwork.com/v2/rooms/{room_id}/members",
                    headers={"X-ChatWorkToken": api_token},
                    timeout=10.0
                )
                
                if response.status_code != 200:
                    print(f"Failed to get members for room {room_id}: {response.status_code}")
                    continue
                
                members = response.json()
                
                with pool.begin() as conn:
                    for member in members:
                        account_id = member.get("account_id")
                        name = member.get("name", "")
                        
                        if not account_id or not name:
                            continue
                        
                        # UPSERT: 存在すれば更新、なければ挿入
                        conn.execute(
                            sqlalchemy.text("""
                                INSERT INTO chatwork_users (account_id, name, room_id, updated_at)
                                VALUES (:account_id, :name, :room_id, CURRENT_TIMESTAMP)
                                ON CONFLICT (account_id) 
                                DO UPDATE SET name = :name, updated_at = CURRENT_TIMESTAMP
                            """),
                            {
                                "account_id": account_id,
                                "name": name,
                                "room_id": room_id
                            }
                        )
                        synced_count += 1
                    
            except Exception as e:
                print(f"Error syncing members for room {room_id}: {e}")
                traceback.print_exc()
                continue
        
        print(f"Synced {synced_count} members")
        
    except Exception as e:
        print(f"Error in sync_room_members: {e}")
        traceback.print_exc()

@functions_framework.http
def sync_chatwork_tasks(request):
    """
    Cloud Function: ChatWorkのタスクをDBと同期
    30分ごとに実行される
    
    ★★★ v6.8.5: conn/cursor安全化 & キャッシュリセット追加 ★★★
    """
    global _runtime_dm_cache, _runtime_direct_rooms, _runtime_contacts_cache, _runtime_contacts_fetched_ok, _dm_unavailable_buffer
    
    print("=== Starting task sync ===")
    
    # ★★★ v6.8.5: 実行開始時にメモリキャッシュをリセット（ウォームスタート対策）★★★
    _runtime_dm_cache = {}
    _runtime_direct_rooms = None
    _runtime_contacts_cache = None
    _runtime_contacts_fetched_ok = None
    _dm_unavailable_buffer = []
    print("✅ メモリキャッシュをリセット")
    
    # ★★★ v6.8.5: conn/cursorを事前にNone初期化（UnboundLocalError防止）★★★
    conn = None
    cursor = None
    
    try:
        # ★ 遅延管理テーブルの確認
        try:
            ensure_overdue_tables()
        except Exception as e:
            print(f"⚠️ 遅延管理テーブル確認エラー（続行）: {e}")
        
        # ★★★ ルームメンバー同期（tryの中に移動）★★★
        print("--- Syncing room members ---")
        sync_room_members()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        # Phase1開始日を取得
        cursor.execute("""
            SELECT value FROM system_config WHERE key = 'phase1_start_date'
        """)
        result = cursor.fetchone()
        phase1_start_date = datetime.strptime(result[0], '%Y-%m-%d').replace(tzinfo=JST) if result else None
        
        # 除外ルーム一覧を取得
        cursor.execute("SELECT room_id FROM excluded_rooms")
        excluded_rooms = set(row[0] for row in cursor.fetchall())
        
        # 全ルーム取得
        rooms = get_all_rooms()
        
        for room in rooms:
            room_id = room['room_id']
            room_name = room['name']
            
            # 除外ルームはスキップ
            if room_id in excluded_rooms:
                print(f"Skipping excluded room: {room_id} ({room_name})")
                continue
            
            print(f"Syncing room: {room_id} ({room_name})")
            
            # 未完了タスクを取得
            open_tasks = get_room_tasks(room_id, 'open')
            
            for task in open_tasks:
                task_id = task['task_id']
                assigned_to_id = task['account']['account_id']
                assigned_by_id = task.get('assigned_by_account', {}).get('account_id')
                body = task['body']
                limit_time = task.get('limit_time')
                
                # 名前を取得
                assigned_to_name = task['account']['name']
                # assigned_by_nameはAPIから直接取得できないため、別途取得が必要
                # ここでは簡易的に空文字列を設定（後で改善可能）
                assigned_by_name = ""
                
                # limit_timeをUNIXタイムスタンプに変換
                limit_datetime = None
                if limit_time:
                    print(f"🔍 DEBUG: limit_time = {limit_time}, type = {type(limit_time)}")
                    
                    if isinstance(limit_time, str):
                        # ISO 8601形式の文字列をUNIXタイムスタンプに変換
                        try:
                            # Python 3.7+のfromisoformatを使用（dateutilは不要）
                            # "2025-12-17T15:52:53+00:00" → datetime
                            dt = datetime.fromisoformat(limit_time.replace('Z', '+00:00'))
                            limit_datetime = int(dt.timestamp())
                            print(f"✅ Converted string to timestamp: {limit_datetime}")
                        except Exception as e:
                            print(f"❌ Failed to parse limit_time string: {e}")
                            limit_datetime = None
                    elif isinstance(limit_time, (int, float)):
                        # 既にUNIXタイムスタンプの場合
                        limit_datetime = int(limit_time)
                        print(f"✅ Already timestamp: {limit_datetime}")
                    else:
                        print(f"⚠️ Unknown limit_time type: {type(limit_time)}")
                        limit_datetime = None
                
                # skip_trackingの判定
                skip_tracking = False
                if phase1_start_date and limit_datetime:
                    # limit_datetimeはUNIXタイムスタンプなので、phase1_start_dateもタイムスタンプに変換
                    phase1_timestamp = int(phase1_start_date.timestamp())
                    if limit_datetime < phase1_timestamp:
                        skip_tracking = True
                
                # DBに存在するか確認（期限変更検知のためlimit_timeも取得）
                cursor.execute("""
                    SELECT task_id, status, limit_time, assigned_by_name FROM chatwork_tasks WHERE task_id = %s
                """, (task_id,))
                existing = cursor.fetchone()
                
                if existing:
                    old_limit_time = existing[2]
                    db_assigned_by_name = existing[3]
                    
                    # ★ 期限変更検知（P1-030）
                    if old_limit_time is not None and limit_datetime is not None and old_limit_time != limit_datetime:
                        task_info = {
                            "body": body,
                            "assigned_to_name": assigned_to_name,
                            "assigned_to_account_id": assigned_to_id,
                            "assigned_by_name": db_assigned_by_name or assigned_by_name
                        }
                        try:
                            detect_and_report_limit_changes(cursor, task_id, old_limit_time, limit_datetime, task_info)
                        except Exception as e:
                            print(f"⚠️ 期限変更検知処理エラー（同期は続行）: {e}")
                    
                    # 既存タスクの更新
                    cursor.execute("""
                        UPDATE chatwork_tasks
                        SET status = 'open',
                            body = %s,
                            limit_time = %s,
                            last_synced_at = CURRENT_TIMESTAMP,
                            room_name = %s,
                            assigned_to_name = %s
                        WHERE task_id = %s
                    """, (body, limit_datetime, room_name, assigned_to_name, task_id))
                else:
                    # 新規タスクの挿入
                    # ★★★ v10.18.1: summary生成、department_id追加 ★★★
                    summary = None
                    if USE_TEXT_UTILS_LIB and body:
                        try:
                            summary = lib_extract_task_subject(body)
                            if not lib_validate_summary(summary):
                                summary = lib_prepare_task_display_text(body, max_length=50)
                            if not lib_validate_summary(summary):
                                cleaned = lib_clean_chatwork_tags(body)
                                summary = cleaned[:40] + "..." if len(cleaned) > 40 else cleaned
                        except Exception as e:
                            print(f"⚠️ summary生成エラー: {e}")
                            summary = body[:40] + "..." if body and len(body) > 40 else body
                    elif body:
                        summary = body[:40] + "..." if len(body) > 40 else body

                    department_id = None
                    try:
                        cursor.execute("""
                            SELECT ud.department_id FROM user_departments ud
                            JOIN users u ON ud.user_id = u.id
                            WHERE u.chatwork_account_id = %s AND ud.is_primary = TRUE AND ud.ended_at IS NULL
                            LIMIT 1
                        """, (str(assigned_to_id),))
                        dept_row = cursor.fetchone()
                        department_id = str(dept_row[0]) if dept_row else None
                    except Exception as e:
                        print(f"⚠️ department_id取得エラー: {e}")

                    cursor.execute("""
                        INSERT INTO chatwork_tasks
                        (task_id, room_id, assigned_to_account_id, assigned_by_account_id, body, limit_time, status,
                         skip_tracking, last_synced_at, room_name, assigned_to_name, assigned_by_name, summary, department_id)
                        VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s)
                    """, (task_id, room_id, assigned_to_id, assigned_by_id, body,
                          limit_datetime, skip_tracking, room_name, assigned_to_name, assigned_by_name, summary, department_id))

            # 完了タスクを取得
            done_tasks = get_room_tasks(room_id, 'done')
            
            for task in done_tasks:
                task_id = task['task_id']
                
                # DBに存在するか確認
                cursor.execute("""
                    SELECT task_id, status, completion_notified, assigned_by_name 
                    FROM chatwork_tasks 
                    WHERE task_id = %s
                """, (task_id,))
                existing = cursor.fetchone()
                
                if existing:
                    old_status = existing[1]
                    completion_notified = existing[2]
                    assigned_by_name = existing[3]
                    
                    # ステータスが変更された場合
                    if old_status == 'open':
                        cursor.execute("""
                            UPDATE chatwork_tasks
                            SET status = 'done',
                                completed_at = CURRENT_TIMESTAMP,
                                last_synced_at = CURRENT_TIMESTAMP
                            WHERE task_id = %s
                        """, (task_id,))
                        
                        # 完了通知を送信（まだ送信していない場合）
                        if not completion_notified:
                            send_completion_notification(room_id, task, assigned_by_name)
                            cursor.execute("""
                                UPDATE chatwork_tasks
                                SET completion_notified = TRUE
                                WHERE task_id = %s
                            """, (task_id,))
        
        conn.commit()
        print("=== Task sync completed ===")
        
        # ★★★ v6.8.4: バッファに溜まった通知を送信 ★★★
        flush_dm_unavailable_notifications()
        
        return ('Task sync completed', 200)
        
    except Exception as e:
        # ★★★ v6.8.5: conn存在チェック追加 ★★★
        if conn:
            conn.rollback()
        print(f"Error during task sync: {str(e)}")
        import traceback
        traceback.print_exc()
        return (f'Error: {str(e)}', 500)
        
    finally:
        # ★★★ v6.8.5: cursor/conn存在チェック追加 ★★★
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        # ★★★ v6.8.4: 例外時もバッファをフラッシュ（残留防止）★★★
        try:
            flush_dm_unavailable_notifications()
        except:
            pass

@functions_framework.http
def remind_tasks(request):
    """
    Cloud Function: タスクのリマインドを送信

    ★★★ v10.6.0: 大幅改修 ★★★
    - 担当者ごとにタスクを集約してDMで1通送信
    - グループチャットへの送信を廃止
    - テストガード実装（管理部・カズさんDMのみ）
    - メッセージフォーマット改善
    """
    print("=" * 60)
    print("=== Starting task reminders (v10.11.0 - フォーマット統一) ===")
    print(f"REMINDER_TEST_MODE: {REMINDER_TEST_MODE}")
    if REMINDER_TEST_MODE:
        print("⚠️ テストモード: 管理部チャットとカズさんDMのみに送信")
    print("=" * 60)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        now = datetime.now(JST)
        today = now.date()
        tomorrow = today + timedelta(days=1)
        three_days_later = today + timedelta(days=3)

        # =====================================================
        # ステップ1: リマインド対象のタスクを取得
        # =====================================================
        cursor.execute("""
            SELECT task_id, room_id, assigned_to_account_id, body, limit_time,
                   room_name, assigned_to_name, summary
            FROM chatwork_tasks
            WHERE status = 'open'
              AND skip_tracking = FALSE
              AND reminder_disabled = FALSE
              AND limit_time IS NOT NULL
        """)

        tasks = cursor.fetchall()
        print(f"📋 リマインド候補タスク: {len(tasks)}件")

        # =====================================================
        # ステップ2: 担当者ごとにタスクをグループ化
        # =====================================================
        # 構造: {assignee_id: {
        #   'name': str,
        #   'overdue': [tasks],       # 期限超過
        #   'today': [tasks],         # 今日期限
        #   'tomorrow': [tasks],      # 明日期限
        #   'three_days': [tasks]     # 3日後期限
        # }}
        tasks_by_assignee = {}

        for task in tasks:
            task_id, room_id, assigned_to_account_id, body, limit_time, room_name, assigned_to_name, summary = task

            if limit_time is None:
                continue

            # limit_time を date に変換
            try:
                if isinstance(limit_time, (int, float)):
                    limit_date = datetime.fromtimestamp(int(limit_time), tz=JST).date()
                elif hasattr(limit_time, 'date'):
                    limit_date = limit_time.date()
                else:
                    print(f"⚠️ 不明なlimit_time型: {type(limit_time)}, task_id={task_id}")
                    continue
            except Exception as e:
                print(f"⚠️ limit_time変換エラー: {limit_time}, task_id={task_id}, error={e}")
                continue

            # リマインドタイプを判定
            reminder_type = None
            overdue_days = 0

            if limit_date < today:
                reminder_type = 'overdue'
                overdue_days = (today - limit_date).days
            elif limit_date == today:
                reminder_type = 'today'
            elif limit_date == tomorrow:
                reminder_type = 'tomorrow'
            elif limit_date == three_days_later:
                reminder_type = 'three_days'

            if not reminder_type:
                continue

            # 今日既に同じタイプのリマインドを送信済みか確認
            cursor.execute("""
                SELECT id FROM task_reminders
                WHERE task_id = %s
                  AND reminder_type = %s
                  AND sent_date = %s
            """, (task_id, reminder_type, today))

            if cursor.fetchone():
                continue  # 既に送信済み

            # 担当者グループに追加
            assignee_id = assigned_to_account_id
            if assignee_id not in tasks_by_assignee:
                tasks_by_assignee[assignee_id] = {
                    'name': assigned_to_name or f"ID:{assignee_id}",
                    'overdue': [],
                    'today': [],
                    'tomorrow': [],
                    'three_days': []
                }

            # タスク表示名を作成（要約 or クリーンな本文）
            # ★★★ v10.17.0: prepare_task_display_text()を使用して途切れ防止 ★★★
            # ★★★ v10.17.0-fix: 「タスク内容なし」時のフォールバック追加 ★★★
            if summary:
                # 要約がある場合も、念のため整形を適用
                if USE_TEXT_UTILS_LIB:
                    task_display = lib_prepare_task_display_text(summary, max_length=40)
                    # 要約が挨拶のみ等で空になった場合、本文にフォールバック
                    if task_display == "（タスク内容なし）":
                        clean_body = lib_clean_chatwork_tags(body)
                        task_display = lib_prepare_task_display_text(clean_body, max_length=40)
                else:
                    task_display = prepare_task_display_text(summary, max_length=40)
                    if task_display == "（タスク内容なし）":
                        clean_body = clean_task_body(body)
                        task_display = prepare_task_display_text(clean_body, max_length=40)
            else:
                # 要約がない場合、本文をクリーニングして整形
                if USE_TEXT_UTILS_LIB:
                    clean_body = lib_clean_chatwork_tags(body)
                    task_display = lib_prepare_task_display_text(clean_body, max_length=40)
                else:
                    clean_body = clean_task_body(body)
                    task_display = prepare_task_display_text(clean_body, max_length=40)

            task_info = {
                'task_id': task_id,
                'room_id': room_id,
                'room_name': room_name or "（不明）",
                'body': task_display,
                'limit_date': limit_date,
                'overdue_days': overdue_days,
                'reminder_type': reminder_type
            }

            tasks_by_assignee[assignee_id][reminder_type].append(task_info)

        print(f"👥 リマインド対象の担当者: {len(tasks_by_assignee)}人")

        # =====================================================
        # ステップ3: 各担当者にDMで送信
        # ★★★ v10.13.2: エラー耐性強化 ★★★
        # - 各ユーザー処理をtry-exceptで独立化
        # - 1人の失敗が他に影響しない
        # - エラー集計と最終サマリー通知
        # =====================================================
        sent_count = 0
        blocked_count = 0
        error_count = 0
        dm_unavailable_count = 0
        error_details = []  # エラー詳細を記録

        for assignee_id, assignee_data in tasks_by_assignee.items():
            try:
                assignee_name = assignee_data['name']
                overdue_tasks = assignee_data['overdue']
                today_tasks = assignee_data['today']
                tomorrow_tasks = assignee_data['tomorrow']
                three_days_tasks = assignee_data['three_days']

                # タスクが1件もなければスキップ
                total_tasks = len(overdue_tasks) + len(today_tasks) + len(tomorrow_tasks) + len(three_days_tasks)
                if total_tasks == 0:
                    continue

                print(f"\n📨 {assignee_name}さん（ID:{assignee_id}）へのリマインド準備...")
                print(f"   期限超過: {len(overdue_tasks)}件, 今日: {len(today_tasks)}件, 明日: {len(tomorrow_tasks)}件, 3日後: {len(three_days_tasks)}件")

                # テストガードチェック
                if not is_test_send_allowed(account_id=assignee_id):
                    print(f"🚫 [TEST_GUARD] {assignee_name}さん（ID:{assignee_id}）への送信をブロック")
                    blocked_count += 1
                    continue

                # DMルームを取得
                dm_room_id = get_direct_room(assignee_id)
                if not dm_room_id:
                    print(f"⚠️ {assignee_name}さんのDMルームが見つかりません")
                    dm_unavailable_count += 1
                    # DM不可の場合は管理部に通知（バッファに追加）
                    global _dm_unavailable_buffer
                    _dm_unavailable_buffer.append({
                        'account_id': assignee_id,
                        'name': assignee_name,
                        'reason': 'リマインド送信',
                        'task_count': total_tasks
                    })
                    continue

                # メッセージを作成
                message = _create_reminder_dm_message(assignee_name, overdue_tasks, today_tasks, tomorrow_tasks, three_days_tasks)

                # 送信
                if send_reminder_with_test_guard(dm_room_id, message, account_id=assignee_id):
                    sent_count += 1

                    # リマインド履歴を記録（重複は無視）
                    all_tasks = overdue_tasks + today_tasks + tomorrow_tasks + three_days_tasks
                    for task_info in all_tasks:
                        try:
                            cursor.execute("""
                                INSERT INTO task_reminders (task_id, room_id, reminder_type)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (task_id, reminder_type, sent_date) DO NOTHING
                            """, (task_info['task_id'], dm_room_id, task_info['reminder_type']))
                        except Exception as e:
                            print(f"⚠️ リマインド履歴記録エラー（続行）: {e}")
                            conn.rollback()  # トランザクションをリセットして続行

                    conn.commit()
                    print(f"✅ {assignee_name}さんへDM送信完了 ({total_tasks}件のタスク)")
                else:
                    # 送信失敗（リトライ後も失敗）
                    error_count += 1
                    error_details.append(f"・{assignee_name}さん（ID:{assignee_id}）: 送信失敗")

            except Exception as e:
                # このユーザーの処理で予期せぬエラー - 記録して次のユーザーへ
                error_count += 1
                error_msg = f"・{assignee_data.get('name', f'ID:{assignee_id}')}さん: {str(e)[:50]}"
                error_details.append(error_msg)
                print(f"❌ 予期せぬエラー（続行）: assignee_id={assignee_id}, error={e}")
                traceback.print_exc()
                try:
                    conn.rollback()
                except:
                    pass
                continue

        # =====================================================
        # サマリー出力
        # =====================================================
        print(f"\n{'=' * 60}")
        print(f"=== リマインド送信完了 (v10.13.2) ===")
        print(f"  ✅ 送信成功: {sent_count}人")
        print(f"  🚫 テストガードでブロック: {blocked_count}人")
        print(f"  ⚠️ DM不可: {dm_unavailable_count}人")
        print(f"  ❌ エラー: {error_count}人")
        print(f"{'=' * 60}")

        # =====================================================
        # ステップ4: 遅延タスク処理（管理部への報告）
        # =====================================================
        try:
            process_overdue_tasks_v2()
        except Exception as e:
            print(f"⚠️ 遅延タスク処理でエラー（リマインドは完了）: {e}")
            traceback.print_exc()

        # =====================================================
        # ステップ5: 完了タスク日次報告（管理部への報告）
        # ★★★ v10.13.0: 無効化（レポートが長くなるため）★★★
        # =====================================================
        # try:
        #     process_completed_tasks_summary()
        # except Exception as e:
        #     print(f"⚠️ 完了タスク報告でエラー（リマインドは完了）: {e}")
        #     traceback.print_exc()
        print("ℹ️ 完了タスク報告はスキップ（v10.13.0で無効化）")

        # =====================================================
        # ステップ6: エラーサマリー通知（管理部へ）
        # ★★★ v10.13.2: エラー発生時のみ管理部へ通知 ★★★
        # =====================================================
        if error_count > 0 and error_details:
            try:
                error_message_lines = [
                    "⚠️ リマインド送信でエラーが発生しました",
                    "",
                    f"📊 サマリー:",
                    f"  ✅ 送信成功: {sent_count}人",
                    f"  ❌ エラー: {error_count}人",
                    "",
                    "📋 エラー詳細:",
                ]
                error_message_lines.extend(error_details[:10])  # 最大10件
                if len(error_details) > 10:
                    error_message_lines.append(f"  ...他{len(error_details) - 10}件")

                error_message = "\n".join(error_message_lines)

                # 管理部チャットに送信
                kanribu_room_id = 371498498
                send_reminder_with_test_guard(kanribu_room_id, error_message)
                print("📨 管理部へエラーサマリーを送信しました")
            except Exception as e:
                print(f"⚠️ エラーサマリー送信失敗（処理は完了）: {e}")

        return ('Task reminders and overdue processing completed', 200)

    except Exception as e:
        conn.rollback()
        print(f"Error during task reminders: {str(e)}")
        traceback.print_exc()
        return (f'Error: {str(e)}', 500)

    finally:
        cursor.close()
        conn.close()


def _create_reminder_dm_message(assignee_name: str, overdue_tasks: list, today_tasks: list,
                                 tomorrow_tasks: list, three_days_tasks: list) -> str:
    """
    担当者へのリマインドDMメッセージを作成

    ★★★ v10.6.0: 新フォーマット ★★★
    """
    lines = []
    lines.append("🐺 タスクリマインド")
    lines.append(f"{assignee_name}さん、期限が近い・超過しているタスクがありますウル！")
    lines.append("")

    task_num = 1

    # 期限超過タスク
    if overdue_tasks:
        lines.append("【⚠️ 期限超過】")
        for task in overdue_tasks:
            lines.append(f"{task_num}. {task['body']}")
            lines.append(f"   📍 {task['room_name']} | 期限: {task['limit_date'].strftime('%m/%d')} | {task['overdue_days']}日超過")
            task_num += 1
        lines.append("")

    # 今日期限タスク
    if today_tasks:
        lines.append("【🔴 今日期限】")
        for task in today_tasks:
            lines.append(f"{task_num}. {task['body']}")
            lines.append(f"   📍 {task['room_name']}")
            task_num += 1
        lines.append("")

    # 明日期限タスク
    if tomorrow_tasks:
        lines.append("【🟡 明日期限】")
        for task in tomorrow_tasks:
            lines.append(f"{task_num}. {task['body']}")
            lines.append(f"   📍 {task['room_name']}")
            task_num += 1
        lines.append("")

    # 3日後期限タスク
    if three_days_tasks:
        lines.append("【🟢 3日後期限】")
        for task in three_days_tasks:
            lines.append(f"{task_num}. {task['body']}")
            lines.append(f"   📍 {task['room_name']}")
            task_num += 1
        lines.append("")

    lines.append("確認をお願いしますウル！")

    return "\n".join(lines)


def process_overdue_tasks_v2():
    """
    遅延タスクを管理部に報告 + エスカレーション処理

    ★★★ v10.14.0: エスカレーション機能を追加 ★★★
    - 3日以上超過のタスクの依頼者にDM通知
    - 管理部に長期遅延タスク報告

    ★★★ v10.12.0: 3段階色分け表示＋管理部メンション ★★★

    Phase 1-B完全実装:
    - 🟡 1-2日超過: 軽度遅延
    - 🟠 3-6日超過: 中度遅延
    - 🔴 7日以上超過: 重度遅延
    - [To:xxx]管理部メンション
    - 担当者ごとにグループ化
    - 期限の古い順にソート

    処理フロー:
    1. 管理部に3段階色分け遅延タスク報告
    2. 3日以上超過タスクの依頼者にエスカレーションDM
    3. 管理部に長期遅延タスク報告

    フォーマット:
    [To:管理部]
    📊 遅延タスク日次報告

    ━━ 🔴 重度遅延（7日以上）N件 ━━
    【担当者名】
    ① タスク（N日超過）
    📍 チャットグループ名

    ━━ 🟠 中度遅延（3-6日）N件 ━━
    ...

    ━━ 🟡 軽度遅延（1-2日）N件 ━━
    ...
    """
    print("\n=== 遅延タスク報告（管理部向け）v10.12.0 ===")

    # 丸数字（①〜⑩）
    CIRCLED_NUMBERS = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']

    # 管理部メンション対象（【SS】管理部アカウント）
    ADMIN_MENTION_ACCOUNT_ID = "10385716"  # 【SS】管理部

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        now = datetime.now(JST)
        today = now.date()

        # 1日以上遅延しているタスクを全て取得（3段階分類のため）
        # ★★★ v10.14.0: エスカレーション用にassigned_by情報を追加 ★★★
        cursor.execute("""
            SELECT task_id, room_id, assigned_to_account_id, assigned_by_account_id,
                   body, limit_time, assigned_to_name, assigned_by_name,
                   room_name, summary
            FROM chatwork_tasks
            WHERE status = 'open'
              AND skip_tracking = FALSE
              AND limit_time IS NOT NULL
        """)

        tasks = cursor.fetchall()

        # 3段階に分類
        # 🔴 severe: 7日以上
        # 🟠 moderate: 3-6日
        # 🟡 mild: 1-2日
        severe_tasks = []    # 7日以上
        moderate_tasks = []  # 3-6日
        mild_tasks = []      # 1-2日

        # ★★★ v10.14.0: エスカレーション用タプルリスト ★★★
        # process_escalationsが期待する形式:
        # (task_id, room_id, assigned_to_account_id, assigned_by_account_id,
        #  body, limit_time, assigned_to_name, assigned_by_name)
        escalation_tuples = []

        for task in tasks:
            # ★★★ v10.14.0: assigned_by情報を追加 ★★★
            task_id, room_id, assigned_to_account_id, assigned_by_account_id, body, limit_time, assigned_to_name, assigned_by_name, room_name, summary = task

            if limit_time is None:
                continue

            try:
                if isinstance(limit_time, (int, float)):
                    limit_date = datetime.fromtimestamp(int(limit_time), tz=JST).date()
                elif hasattr(limit_time, 'date'):
                    limit_date = limit_time.date()
                else:
                    continue
            except:
                continue

            overdue_days = (today - limit_date).days

            # 1日未満（0日以下）はスキップ
            if overdue_days < 1:
                continue

            # タスク内容を整形
            # ★★★ v10.17.0: lib/使用時はそちらを優先 ★★★
            # ★★★ v10.17.0-fix: 「タスク内容なし」時のフォールバック追加 ★★★
            if USE_TEXT_UTILS_LIB:
                clean_body = lib_clean_chatwork_tags(body)
                task_display = lib_prepare_task_display_text(summary if summary else clean_body, max_length=40)
                # 要約が挨拶のみ等で空になった場合、本文にフォールバック
                if task_display == "（タスク内容なし）" and summary:
                    task_display = lib_prepare_task_display_text(clean_body, max_length=40)
            else:
                clean_body = clean_task_body(body)
                task_display = prepare_task_display_text(summary if summary else clean_body, max_length=40)
                if task_display == "（タスク内容なし）" and summary:
                    task_display = prepare_task_display_text(clean_body, max_length=40)

            # ルーム名を整形
            room_display = room_name if room_name else "不明"
            if len(room_display) > 15:
                room_display = room_display[:14] + "…"

            task_info = {
                'task_id': task_id,
                'body': task_display,
                'room_name': room_display,
                'limit_date': limit_date,
                'overdue_days': overdue_days,
                'assignee_id': assigned_to_account_id,
                'assignee_name': assigned_to_name or f"ID:{assigned_to_account_id}"
            }

            # 3段階に分類
            if overdue_days >= 7:
                severe_tasks.append(task_info)
            elif overdue_days >= 3:
                moderate_tasks.append(task_info)
            else:  # 1-2日
                mild_tasks.append(task_info)

            # ★★★ v10.14.0: 3日以上超過はエスカレーション対象 ★★★
            # process_escalationsが期待するタプル形式で保存
            # ESCALATION_DAYS = 3 なので、moderate(3-6日) + severe(7日以上) が対象
            if overdue_days >= ESCALATION_DAYS:
                escalation_tuple = (
                    task_id,                    # [0]
                    room_id,                    # [1]
                    assigned_to_account_id,     # [2]
                    assigned_by_account_id,     # [3]
                    body,                       # [4] 元のbody（process_escalations内で整形される）
                    limit_time,                 # [5]
                    assigned_to_name,           # [6]
                    assigned_by_name,           # [7]
                    room_name                   # [8] ★ v10.14.0追加: ルーム名
                )
                escalation_tuples.append(escalation_tuple)

        # 遅延タスクがなければ終了
        total_overdue = len(severe_tasks) + len(moderate_tasks) + len(mild_tasks)
        if total_overdue == 0:
            print("✅ 遅延しているタスクはありません")
            return

        print(f"📊 遅延タスク: 計{total_overdue}件（🔴{len(severe_tasks)}件, 🟠{len(moderate_tasks)}件, 🟡{len(mild_tasks)}件）")

        # メッセージ作成
        lines = []

        # 管理部へのメンション（本番モードのみ）
        if not REMINDER_TEST_MODE:
            lines.append(f"[To:{ADMIN_MENTION_ACCOUNT_ID}]")

        lines.append(f"📊 遅延タスク日次報告（計{total_overdue}件）")
        lines.append("")

        # 3段階サマリー
        lines.append(f"🔴 重度遅延（7日以上）: {len(severe_tasks)}件")
        lines.append(f"🟠 中度遅延（3-6日）: {len(moderate_tasks)}件")
        lines.append(f"🟡 軽度遅延（1-2日）: {len(mild_tasks)}件")

        def format_category_tasks(category_tasks, emoji, category_name, max_display=15):
            """カテゴリ別にタスクをフォーマット"""
            if not category_tasks:
                return []

            result = []
            result.append("")
            result.append(f"━━ {emoji} {category_name} {len(category_tasks)}件 ━━")

            # 担当者ごとにグループ化
            by_assignee = {}
            for t in category_tasks:
                aid = t['assignee_id']
                if aid not in by_assignee:
                    by_assignee[aid] = {
                        'name': t['assignee_name'],
                        'tasks': []
                    }
                by_assignee[aid]['tasks'].append(t)

            # 担当者ごとにタスクを超過日数でソート（古い順）
            for aid in by_assignee:
                by_assignee[aid]['tasks'].sort(key=lambda x: -x['overdue_days'])

            # 担当者ごとに表示
            displayed_count = 0
            for aid, data in by_assignee.items():
                if displayed_count >= max_display:
                    remaining = sum(len(d['tasks']) for d in list(by_assignee.values())[list(by_assignee.keys()).index(aid):])
                    result.append(f"…他{remaining}件")
                    break

                assignee_name = data['name']
                if not assignee_name.endswith('さん'):
                    display_name = f"{assignee_name}さん"
                else:
                    display_name = assignee_name

                result.append("")
                result.append(f"【{display_name}】{len(data['tasks'])}件")

                for i, task in enumerate(data['tasks']):
                    if displayed_count >= max_display:
                        remaining = len(data['tasks']) - i
                        if remaining > 0:
                            result.append(f"…他{remaining}件")
                        break

                    num = CIRCLED_NUMBERS[i] if i < len(CIRCLED_NUMBERS) else f"({i+1})"
                    result.append(f"{num} {task['body']}（{task['overdue_days']}日超過）")
                    result.append(f"📍 {task['room_name']}")
                    displayed_count += 1

            return result

        # 各カテゴリのタスクを追加（重度→中度→軽度の順）
        lines.extend(format_category_tasks(severe_tasks, "🔴", "重度遅延（7日以上）", max_display=10))
        lines.extend(format_category_tasks(moderate_tasks, "🟠", "中度遅延（3-6日）", max_display=10))
        lines.extend(format_category_tasks(mild_tasks, "🟡", "軽度遅延（1-2日）", max_display=5))

        # フッター
        lines.append("")
        lines.append("引き続き督促を継続しますウル🐺")

        message = "\n".join(lines)

        # 管理部に送信
        if send_reminder_with_test_guard(ADMIN_ROOM_ID, message):
            print(f"✅ 管理部への遅延タスク報告完了（3段階分類）")
        else:
            print(f"⚠️ 管理部への報告送信失敗またはブロック")

        # ★★★ v10.14.0: エスカレーション処理（3日以上超過のタスクの依頼者に通知）★★★
        # process_escalationsは独自のDB接続（get_pool()）を使用するため、
        # cursor/connをcloseした後でも動作可能だが、try-except内で実行
        if escalation_tuples:
            print(f"\n=== エスカレーション処理（{len(escalation_tuples)}件対象）===")
            try:
                process_escalations(escalation_tuples, today)
            except Exception as esc_error:
                print(f"⚠️ エスカレーション処理でエラー（遅延タスク報告は完了）: {esc_error}")
                traceback.print_exc()
        else:
            print("ℹ️ エスカレーション対象タスクなし（3日以上超過のタスクがありません）")

    except Exception as e:
        print(f"❌ 遅延タスク報告エラー: {e}")
        traceback.print_exc()

    finally:
        cursor.close()
        conn.close()


def process_completed_tasks_summary():
    """
    完了タスクの日次サマリーを管理部に報告

    ★★★ v10.8.0: フォーマット大幅改善 ★★★

    v10.7.0からの変更点:
    - 15文字AI要約を使用
    - 📍 チャットグループ名を追加
    - タスク間に1行空ける
    - 人の切り替わりで2行空ける

    フォーマット:
    ━━━━━━━━━━━━━━━━━━━━
    【担当者名】N件
    ━━━━━━━━━━━━━━━━━━━━
    ① タスク要約（15文字）
    📍 チャットグループ名

    ② 次のタスク...
    """
    print("\n=== 完了タスク日次報告（管理部向け） ===")

    # 丸数字（①〜⑩）
    CIRCLED_NUMBERS = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']
    DIVIDER = "━━━━━━━━━━━━━━━━━━━━"

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        now = datetime.now(JST)
        yesterday = now - timedelta(hours=24)

        # 過去24時間に完了したタスクを取得
        cursor.execute("""
            SELECT task_id, room_id, assigned_to_account_id, body,
                   room_name, assigned_to_name, summary, completed_at
            FROM chatwork_tasks
            WHERE status = 'done'
              AND completed_at IS NOT NULL
              AND completed_at >= %s
            ORDER BY completed_at DESC
        """, (yesterday,))

        tasks = cursor.fetchall()

        if not tasks:
            print("✅ 過去24時間に完了したタスクはありません")
            return

        # 担当者ごとにグループ化
        completed_by_assignee = {}

        for task in tasks:
            task_id, room_id, assigned_to_account_id, body, room_name, assigned_to_name, summary, completed_at = task

            assignee_id = assigned_to_account_id

            if assignee_id not in completed_by_assignee:
                completed_by_assignee[assignee_id] = {
                    'name': assigned_to_name or f"ID:{assignee_id}",
                    'tasks': []
                }

            # タスク内容を15文字以内に整形（v10.8.0: AI要約対応）
            # summary優先、なければbodyをクリーニング後に整形
            # ★★★ v10.17.0: lib/使用時はそちらを優先 ★★★
            # ★★★ v10.17.0-fix: 「タスク内容なし」時のフォールバック追加 ★★★
            if USE_TEXT_UTILS_LIB:
                clean_body = lib_clean_chatwork_tags(body)
                task_display = lib_prepare_task_display_text(summary if summary else clean_body, max_length=40)
                # 要約が挨拶のみ等で空になった場合、本文にフォールバック
                if task_display == "（タスク内容なし）" and summary:
                    task_display = lib_prepare_task_display_text(clean_body, max_length=40)
            else:
                clean_body = clean_task_body(body)
                task_display = prepare_task_display_text(summary if summary else clean_body, max_length=40)
                if task_display == "（タスク内容なし）" and summary:
                    task_display = prepare_task_display_text(clean_body, max_length=40)

            # ルーム名を整形（長い場合は切り詰め）
            room_display = room_name if room_name else "不明"
            if len(room_display) > 15:
                room_display = room_display[:14] + "…"

            completed_by_assignee[assignee_id]['tasks'].append({
                'task_id': task_id,
                'body': task_display,
                'room_name': room_display
            })

        if not completed_by_assignee:
            print("✅ 報告対象の完了タスクはありません")
            return

        # 管理部への報告メッセージを作成
        total_completed = sum(len(data['tasks']) for data in completed_by_assignee.values())
        print(f"✅ 過去24時間の完了タスク: {total_completed}件（{len(completed_by_assignee)}人）")

        lines = []
        lines.append(f"✅ 本日完了したタスク（計{total_completed}件）")

        first_person = True
        for assignee_id, data in completed_by_assignee.items():
            assignee_name = data['name']
            # 「さん」が既についている場合は追加しない
            if not assignee_name.endswith('さん'):
                display_name = f"{assignee_name}さん"
            else:
                display_name = assignee_name
            tasks_list = data['tasks']

            # 人の切り替わりで2行空ける（最初の人以外）
            if not first_person:
                lines.append("")  # 2行目の空行
            first_person = False

            lines.append(DIVIDER)
            lines.append(f"【{display_name}】{len(tasks_list)}件")
            lines.append(DIVIDER)

            for i, task in enumerate(tasks_list[:10]):  # 最大10件表示
                num = CIRCLED_NUMBERS[i] if i < len(CIRCLED_NUMBERS) else f"({i+1})"
                lines.append(f"{num} {task['body']}")
                lines.append(f"📍 {task['room_name']}")

                # タスク間に1行空ける（最後のタスク以外）
                if i < min(len(tasks_list), 10) - 1:
                    lines.append("")

            if len(tasks_list) > 10:
                lines.append("")
                lines.append(f"…他{len(tasks_list) - 10}件")

        lines.append("")
        lines.append("")
        lines.append("お疲れ様でした！")

        message = "\n".join(lines)

        # 管理部に送信
        if send_reminder_with_test_guard(ADMIN_ROOM_ID, message):
            print(f"✅ 管理部への完了タスク報告完了")
        else:
            print(f"⚠️ 管理部への報告送信失敗またはブロック")

    except Exception as e:
        print(f"❌ 完了タスク報告エラー: {e}")
        traceback.print_exc()

    finally:
        cursor.close()
        conn.close()


# ========================================
# クリーンアップ機能（古いデータの自動削除）
# ========================================

@functions_framework.http
def cleanup_old_data(request):
    """
    Cloud Function: 古いデータを自動削除
    毎日03:00 JSTに実行される
    
    削除対象:
    - room_messages: 30日以上前
    - processed_messages: 7日以上前
    - conversation_timestamps: 30日以上前
    - Firestore conversations: 30日以上前
    - Firestore pending_tasks: 1日以上前（NEW）
    """
    print("=" * 50)
    print("🧹 クリーンアップ処理開始")
    print("=" * 50)
    
    results = {
        "room_messages": 0,
        "processed_messages": 0,
        "conversation_timestamps": 0,
        "firestore_conversations": 0,
        "firestore_pending_tasks": 0,
        "errors": []
    }
    
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)
    one_day_ago = now - timedelta(days=1)
    
    # ===== PostgreSQL クリーンアップ =====
    try:
        pool = get_pool()
        with pool.begin() as conn:
            # 1. room_messages（30日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM room_messages 
                        WHERE created_at < :cutoff_date
                        RETURNING id
                    """),
                    {"cutoff_date": thirty_days_ago}
                )
                deleted_count = result.rowcount
                results["room_messages"] = deleted_count
                print(f"✅ room_messages: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"room_messages削除エラー: {e}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)
            
            # 2. processed_messages（7日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM processed_messages 
                        WHERE processed_at < :cutoff_date
                        RETURNING message_id
                    """),
                    {"cutoff_date": seven_days_ago}
                )
                deleted_count = result.rowcount
                results["processed_messages"] = deleted_count
                print(f"✅ processed_messages: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"processed_messages削除エラー: {e}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)
            
            # 3. conversation_timestamps（30日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM conversation_timestamps 
                        WHERE updated_at < :cutoff_date
                        RETURNING room_id
                    """),
                    {"cutoff_date": thirty_days_ago}
                )
                deleted_count = result.rowcount
                results["conversation_timestamps"] = deleted_count
                print(f"✅ conversation_timestamps: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"conversation_timestamps削除エラー: {e}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)
            
    except Exception as e:
        error_msg = f"PostgreSQL接続エラー: {e}"
        print(f"❌ {error_msg}")
        traceback.print_exc()
        results["errors"].append(error_msg)
    
    # ===== Firestore クリーンアップ =====
    try:
        # conversationsコレクションから30日以上前のドキュメントを削除
        conversations_ref = db.collection("conversations")
        
        # updated_atが30日以上前のドキュメントを取得
        old_docs = conversations_ref.where(
            "updated_at", "<", thirty_days_ago
        ).stream()
        
        deleted_count = 0
        batch = db.batch()
        batch_count = 0
        
        for doc in old_docs:
            batch.delete(doc.reference)
            batch_count += 1
            deleted_count += 1
            
            # Firestoreのバッチは500件まで
            if batch_count >= 500:
                batch.commit()
                batch = db.batch()
                batch_count = 0
        
        # 残りをコミット
        if batch_count > 0:
            batch.commit()
        
        results["firestore_conversations"] = deleted_count
        print(f"✅ Firestore conversations: {deleted_count}件削除")
        
    except Exception as e:
        error_msg = f"Firestoreクリーンアップエラー: {e}"
        print(f"❌ {error_msg}")
        results["errors"].append(error_msg)
    
    # ===== Firestore pending_tasks クリーンアップ（NEW） =====
    try:
        pending_tasks_ref = db.collection("pending_tasks")
        
        old_pending_docs = pending_tasks_ref.where(
            "created_at", "<", one_day_ago
        ).stream()
        
        deleted_count = 0
        batch = db.batch()
        batch_count = 0
        
        for doc in old_pending_docs:
            batch.delete(doc.reference)
            batch_count += 1
            deleted_count += 1
            
            if batch_count >= 500:
                batch.commit()
                batch = db.batch()
                batch_count = 0
        
        if batch_count > 0:
            batch.commit()
        
        results["firestore_pending_tasks"] = deleted_count
        print(f"✅ Firestore pending_tasks: {deleted_count}件削除")
        
    except Exception as e:
        error_msg = f"Firestore pending_tasksクリーンアップエラー: {e}"
        print(f"❌ {error_msg}")
        results["errors"].append(error_msg)
    
    # ===== サマリー =====
    print("=" * 50)
    print("📊 クリーンアップ結果:")
    print(f"   - room_messages: {results['room_messages']}件削除")
    print(f"   - processed_messages: {results['processed_messages']}件削除")
    print(f"   - conversation_timestamps: {results['conversation_timestamps']}件削除")
    print(f"   - Firestore conversations: {results['firestore_conversations']}件削除")
    print(f"   - Firestore pending_tasks: {results['firestore_pending_tasks']}件削除")
    if results["errors"]:
        print(f"   - エラー: {len(results['errors'])}件")
        for err in results["errors"]:
            print(f"     ・{err}")
    print("=" * 50)
    print("🧹 クリーンアップ完了")
    
    return jsonify({
        "status": "ok" if not results["errors"] else "partial",
        "results": results
    })


# =====================================================
# ★★★ v10.15.0: Phase 2.5 目標達成支援 ★★★
# =====================================================
#
# 以下の Cloud Functions は Cloud Scheduler から呼び出される:
#   - goal_daily_check:    17:00 JST 毎日
#   - goal_daily_reminder: 18:00 JST 毎日
#   - goal_morning_feedback: 08:00 JST 毎日
#
# Cloud Scheduler 設定例:
#   gcloud scheduler jobs create http goal-daily-check \
#     --schedule="0 17 * * *" \
#     --time-zone="Asia/Tokyo" \
#     --uri="https://REGION-PROJECT.cloudfunctions.net/goal_daily_check" \
#     --http-method=POST
# =====================================================

# 目標通知サービスをインポート（遅延インポートで循環参照回避）
def _get_goal_notification_module():
    """目標通知モジュールの遅延インポート"""
    import sys
    import os

    # lib/ パスを追加
    lib_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib')
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    from lib.goal_notification import (
        scheduled_daily_check,
        scheduled_daily_reminder,
        scheduled_morning_feedback,
    )
    return scheduled_daily_check, scheduled_daily_reminder, scheduled_morning_feedback


# デフォルトの組織ID（ソウルシンクス - 本番UUID）
# 環境変数DEFAULT_ORG_IDから取得、未設定の場合はNone
DEFAULT_ORG_ID = os.getenv("DEFAULT_ORG_ID")


def _validate_org_id(org_id):
    """
    組織IDがUUID形式かどうかを検証する

    Args:
        org_id: 検証する組織ID

    Returns:
        bool: UUIDとして有効ならTrue
    """
    import uuid
    if not org_id:
        return False
    try:
        uuid.UUID(str(org_id))
        return True
    except (ValueError, AttributeError):
        return False


def _send_chatwork_message_wrapper(room_id, message):
    """
    ChatWorkメッセージ送信のラッパー関数

    既存の send_reminder_with_test_guard を使用して
    テストモード対応・レート制限対応を行う
    """
    return send_reminder_with_test_guard(int(room_id), message)


@functions_framework.http
def goal_daily_check(request):
    """
    Cloud Function: 17:00 目標進捗確認

    全スタッフにその日の振り返りを問いかけるDMを送信。
    1ユーザーが複数目標を持っていても、1通にまとめて送信。

    Cloud Scheduler から毎日17:00 JSTに呼び出される想定。

    リクエストボディ（オプション）:
        {
            "org_id": "xxx",  // 省略時はデフォルト組織
            "dry_run": true   // 省略時は環境変数DRY_RUNに従う
        }
    """
    print("=" * 60)
    print("=== 🎯 Phase 2.5: 17時進捗確認 開始 (v10.15.0) ===")
    print(f"DRY_RUN: {DRY_RUN}")
    print("=" * 60)

    try:
        # リクエストパラメータ取得
        request_json = request.get_json(silent=True) or {}
        org_id = request_json.get("org_id", DEFAULT_ORG_ID)
        dry_run = request_json.get("dry_run", DRY_RUN)

        # 組織IDのUUID検証
        if not org_id:
            return jsonify({
                "status": "error",
                "notification_type": "goal_daily_check",
                "error": "Missing org_id. Set DEFAULT_ORG_ID environment variable or pass org_id in request body.",
            }), 400
        if not _validate_org_id(org_id):
            return jsonify({
                "status": "error",
                "notification_type": "goal_daily_check",
                "error": f"Invalid org_id format. Must be a valid UUID. Received: {org_id[:20]}...",
            }), 400

        print(f"組織ID: {org_id}")
        print(f"ドライランモード: {dry_run}")

        # 目標通知モジュール取得
        scheduled_daily_check, _, _ = _get_goal_notification_module()

        # DB接続を取得（CLAUDE.md鉄則#10: トランザクション内でAPI呼び出しをしないため、beginではなくconnectを使用）
        pool = get_pool()
        with pool.connect() as conn:
            results = scheduled_daily_check(
                conn=conn,
                org_id=org_id,
                send_message_func=_send_chatwork_message_wrapper,
                dry_run=dry_run,
            )

        print("=" * 60)
        print(f"📊 送信結果: success={results['success']}, skipped={results['skipped']}, failed={results['failed']}")
        print("=== 🎯 17時進捗確認 完了 ===")
        print("=" * 60)

        return jsonify({
            "status": "ok",
            "notification_type": "goal_daily_check",
            "results": results,
        })

    except Exception as e:
        print(f"❌ エラー: {e}")
        traceback.print_exc()
        # CLAUDE.md鉄則#8: エラーメッセージに機密情報を含めない
        from lib.goal_notification import sanitize_error
        return jsonify({
            "status": "error",
            "notification_type": "goal_daily_check",
            "error": sanitize_error(e),
        }), 500


@functions_framework.http
def goal_daily_reminder(request):
    """
    Cloud Function: 18:00 未回答リマインド

    17時の進捗確認に未回答のスタッフにリマインドDMを送信。

    Cloud Scheduler から毎日18:00 JSTに呼び出される想定。

    リクエストボディ（オプション）:
        {
            "org_id": "xxx",  // 省略時はデフォルト組織
            "dry_run": true   // 省略時は環境変数DRY_RUNに従う
        }
    """
    print("=" * 60)
    print("=== 🔔 Phase 2.5: 18時未回答リマインド 開始 (v10.15.0) ===")
    print(f"DRY_RUN: {DRY_RUN}")
    print("=" * 60)

    try:
        # リクエストパラメータ取得
        request_json = request.get_json(silent=True) or {}
        org_id = request_json.get("org_id", DEFAULT_ORG_ID)
        dry_run = request_json.get("dry_run", DRY_RUN)

        # 組織IDのUUID検証
        if not org_id:
            return jsonify({
                "status": "error",
                "notification_type": "goal_daily_reminder",
                "error": "Missing org_id. Set DEFAULT_ORG_ID environment variable or pass org_id in request body.",
            }), 400
        if not _validate_org_id(org_id):
            return jsonify({
                "status": "error",
                "notification_type": "goal_daily_reminder",
                "error": f"Invalid org_id format. Must be a valid UUID. Received: {org_id[:20]}...",
            }), 400

        print(f"組織ID: {org_id}")
        print(f"ドライランモード: {dry_run}")

        # 目標通知モジュール取得
        _, scheduled_daily_reminder, _ = _get_goal_notification_module()

        # DB接続を取得（CLAUDE.md鉄則#10: トランザクション内でAPI呼び出しをしないため、beginではなくconnectを使用）
        pool = get_pool()
        with pool.connect() as conn:
            results = scheduled_daily_reminder(
                conn=conn,
                org_id=org_id,
                send_message_func=_send_chatwork_message_wrapper,
                dry_run=dry_run,
            )

        print("=" * 60)
        print(f"📊 送信結果: success={results['success']}, skipped={results['skipped']}, failed={results['failed']}")
        print("=== 🔔 18時未回答リマインド 完了 ===")
        print("=" * 60)

        return jsonify({
            "status": "ok",
            "notification_type": "goal_daily_reminder",
            "results": results,
        })

    except Exception as e:
        print(f"❌ エラー: {e}")
        traceback.print_exc()
        # CLAUDE.md鉄則#8: エラーメッセージに機密情報を含めない
        from lib.goal_notification import sanitize_error
        return jsonify({
            "status": "error",
            "notification_type": "goal_daily_reminder",
            "error": sanitize_error(e),
        }), 500


@functions_framework.http
def goal_morning_feedback(request):
    """
    Cloud Function: 08:00 朝フィードバック

    以下を送信:
    1. 個人フィードバック: 昨日進捗報告したスタッフへのフィードバックDM
    2. チームサマリー: チームリーダー・部長へのチーム進捗サマリーDM

    Cloud Scheduler から毎日08:00 JSTに呼び出される想定。

    リクエストボディ（オプション）:
        {
            "org_id": "xxx",  // 省略時はデフォルト組織
            "dry_run": true   // 省略時は環境変数DRY_RUNに従う
        }
    """
    print("=" * 60)
    print("=== ☀️ Phase 2.5: 8時朝フィードバック 開始 (v10.15.0) ===")
    print(f"DRY_RUN: {DRY_RUN}")
    print("=" * 60)

    try:
        # リクエストパラメータ取得
        request_json = request.get_json(silent=True) or {}
        org_id = request_json.get("org_id", DEFAULT_ORG_ID)
        dry_run = request_json.get("dry_run", DRY_RUN)

        # 組織IDのUUID検証
        if not org_id:
            return jsonify({
                "status": "error",
                "notification_type": "goal_morning_feedback",
                "error": "Missing org_id. Set DEFAULT_ORG_ID environment variable or pass org_id in request body.",
            }), 400
        if not _validate_org_id(org_id):
            return jsonify({
                "status": "error",
                "notification_type": "goal_morning_feedback",
                "error": f"Invalid org_id format. Must be a valid UUID. Received: {org_id[:20]}...",
            }), 400

        print(f"組織ID: {org_id}")
        print(f"ドライランモード: {dry_run}")

        # 目標通知モジュール取得
        _, _, scheduled_morning_feedback = _get_goal_notification_module()

        # DB接続を取得（CLAUDE.md鉄則#10: トランザクション内でAPI呼び出しをしないため、beginではなくconnectを使用）
        pool = get_pool()
        with pool.connect() as conn:
            results = scheduled_morning_feedback(
                conn=conn,
                org_id=org_id,
                send_message_func=_send_chatwork_message_wrapper,
                dry_run=dry_run,
            )

        print("=" * 60)
        print(f"📊 送信結果: success={results['success']}, skipped={results['skipped']}, failed={results['failed']}")
        print("=== ☀️ 8時朝フィードバック 完了 ===")
        print("=" * 60)

        return jsonify({
            "status": "ok",
            "notification_type": "goal_morning_feedback",
            "results": results,
        })

    except Exception as e:
        print(f"❌ エラー: {e}")
        traceback.print_exc()
        # CLAUDE.md鉄則#8: エラーメッセージに機密情報を含めない
        from lib.goal_notification import sanitize_error
        return jsonify({
            "status": "error",
            "notification_type": "goal_morning_feedback",
            "error": sanitize_error(e),
        }), 500


@functions_framework.http
def goal_consecutive_unanswered_check(request):
    """
    Cloud Function: 3日連続未回答チェック

    3日連続で進捗報告がないスタッフを検出し、
    そのスタッフのチームリーダー・部長にアラートを送信。

    Cloud Scheduler から毎日09:00 JSTに呼び出される想定。
    （8時の朝フィードバック後に実行）

    リクエストボディ（オプション）:
        {
            "org_id": "xxx",  // 省略時はデフォルト組織
            "consecutive_days": 3,  // 省略時は3日
            "dry_run": true   // 省略時は環境変数DRY_RUNに従う
        }
    """
    print("=" * 60)
    print("=== ⚠️ Phase 2.5: 連続未回答チェック 開始 (v10.15.0) ===")
    print(f"DRY_RUN: {DRY_RUN}")
    print("=" * 60)

    try:
        # リクエストパラメータ取得
        request_json = request.get_json(silent=True) or {}
        org_id = request_json.get("org_id", DEFAULT_ORG_ID)
        consecutive_days = request_json.get("consecutive_days", 3)
        dry_run = request_json.get("dry_run", DRY_RUN)

        # 組織IDのUUID検証
        if not org_id:
            return jsonify({
                "status": "error",
                "notification_type": "goal_consecutive_unanswered",
                "error": "Missing org_id. Set DEFAULT_ORG_ID environment variable or pass org_id in request body.",
            }), 400
        if not _validate_org_id(org_id):
            return jsonify({
                "status": "error",
                "notification_type": "goal_consecutive_unanswered",
                "error": f"Invalid org_id format. Must be a valid UUID. Received: {org_id[:20]}...",
            }), 400

        print(f"組織ID: {org_id}")
        print(f"連続未回答日数: {consecutive_days}日")
        print(f"ドライランモード: {dry_run}")

        # 目標通知モジュールから連続未回答チェック関数を取得
        import sys
        import os
        lib_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib')
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        from lib.goal_notification import scheduled_consecutive_unanswered_check

        # DB接続を取得（CLAUDE.md鉄則#10: トランザクション内でAPI呼び出しをしないため、beginではなくconnectを使用）
        pool = get_pool()
        with pool.connect() as conn:
            results = scheduled_consecutive_unanswered_check(
                conn=conn,
                org_id=org_id,
                send_message_func=_send_chatwork_message_wrapper,
                consecutive_days=consecutive_days,
                dry_run=dry_run,
            )

        print("=" * 60)
        print(f"📊 送信結果: success={results['success']}, skipped={results['skipped']}, failed={results['failed']}")
        print("=== ⚠️ 連続未回答チェック 完了 ===")
        print("=" * 60)

        return jsonify({
            "status": "ok",
            "notification_type": "goal_consecutive_unanswered",
            "consecutive_days": consecutive_days,
            "results": results,
        })

    except Exception as e:
        print(f"❌ エラー: {e}")
        traceback.print_exc()
        # CLAUDE.md鉄則#8: エラーメッセージに機密情報を含めない
        from lib.goal_notification import sanitize_error
        return jsonify({
            "status": "error",
            "notification_type": "goal_consecutive_unanswered",
            "error": sanitize_error(e),
        }), 500
