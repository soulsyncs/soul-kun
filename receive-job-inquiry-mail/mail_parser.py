"""
mail_parser.py - 求人問い合わせメール解析モジュール

各求人媒体から届くメールを解析して、ChatWork投稿用の情報を抽出する。
対応媒体: Indeed / Wantedly / LinkedIn / doda / Green / MyNavi / Rikunabi / 直接問い合わせ
"""
import re
import base64
import email
from email.header import decode_header
from dataclasses import dataclass
from typing import Optional


# =============================================================================
# データ構造
# =============================================================================

@dataclass
class JobInquiry:
    """解析済みの求人問い合わせ"""
    platform: str           # 求人媒体名（"Indeed" / "Wantedly" 等）
    platform_emoji: str     # 絵文字アイコン
    applicant_name: str     # 応募者名
    job_title: str          # 応募職種
    message_preview: str    # メッセージ冒頭100文字
    raw_subject: str        # 元のメール件名
    sender_email: str       # 送信元メールアドレス
    apply_id: Optional[str] # 応募ID（媒体が付与する場合）


# =============================================================================
# 求人媒体の検出パターン
# =============================================================================

PLATFORM_PATTERNS = [
    {
        "name": "Indeed",
        "emoji": "🔵",
        "sender_patterns": [
            r"@indeed\.com",
            r"@email\.indeed\.com",
            r"@jobs\.indeed\.com",
        ],
        "subject_patterns": [
            r"Indeed",
            r"インディード",
        ],
    },
    {
        "name": "Wantedly",
        "emoji": "🟣",
        "sender_patterns": [
            r"@wantedly\.com",
            r"@mail\.wantedly\.com",
        ],
        "subject_patterns": [
            r"Wantedly",
            r"ウォンテッドリー",
        ],
    },
    {
        "name": "LinkedIn",
        "emoji": "🔷",
        "sender_patterns": [
            r"@linkedin\.com",
            r"@e\.linkedin\.com",
        ],
        "subject_patterns": [
            r"LinkedIn",
            r"リンクトイン",
        ],
    },
    {
        "name": "doda",
        "emoji": "🟠",
        "sender_patterns": [
            r"@doda\.jp",
            r"@persol-group\.co\.jp",
            r"@persol\.co\.jp",
        ],
        "subject_patterns": [
            r"doda",
            r"ドーダ",
        ],
    },
    {
        "name": "Green",
        "emoji": "🟢",
        "sender_patterns": [
            r"@green-japan\.com",
            r"@athenainc\.co\.jp",
        ],
        "subject_patterns": [
            r"Green",
        ],
    },
    {
        "name": "マイナビ転職",
        "emoji": "🔴",
        "sender_patterns": [
            r"@mynavi\.jp",
            r"@tenshoku\.mynavi\.jp",
        ],
        "subject_patterns": [
            r"マイナビ転職",
            r"MyNavi",
        ],
    },
    {
        "name": "リクナビNEXT",
        "emoji": "🟡",
        "sender_patterns": [
            r"@rikunabi\.com",
            r"@next\.rikunabi\.com",
        ],
        "subject_patterns": [
            r"リクナビ",
            r"Rikunabi",
        ],
    },
]

# 求人問い合わせと判定するキーワード（件名・本文に含まれる場合）
JOB_INQUIRY_KEYWORDS = [
    "応募", "エントリー", "申し込み", "志望",
    "application", "apply", "applicant",
    "気になる", "話を聞きたい", "興味があります",
    "候補者", "求職者", "転職希望",
    "resume", "職歴",
]


# =============================================================================
# ユーティリティ関数
# =============================================================================

def decode_mime_header(header_value: str) -> str:
    """MIMEエンコードされたメールヘッダーを日本語等にデコードする"""
    if not header_value:
        return ""
    decoded_parts = decode_header(header_value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                result.append(part.decode("utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)


def extract_plain_text(msg: email.message.Message) -> str:
    """メールからプレーンテキスト本文を抽出する"""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(charset, errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
    return body.strip()


def detect_platform(sender_email: str, subject: str) -> dict:
    """送信元アドレスと件名から求人媒体を検出する"""
    for platform in PLATFORM_PATTERNS:
        # 送信元アドレスでマッチ
        for pattern in platform["sender_patterns"]:
            if re.search(pattern, sender_email, re.IGNORECASE):
                return platform
        # 件名でマッチ
        for pattern in platform["subject_patterns"]:
            if re.search(pattern, subject, re.IGNORECASE):
                return platform
    return {"name": "直接問い合わせ", "emoji": "📩"}


def is_job_inquiry(subject: str, body: str, platform_name: str) -> bool:
    """このメールが求人問い合わせかどうかを判定する"""
    # 既知の求人媒体からのメールは無条件で問い合わせと判定
    if platform_name != "直接問い合わせ":
        return True

    # 直接問い合わせの場合はキーワードで判定
    text = f"{subject} {body}".lower()
    for keyword in JOB_INQUIRY_KEYWORDS:
        if keyword.lower() in text:
            return True
    return False


def extract_applicant_name(subject: str, body: str, platform_name: str) -> str:
    """応募者名を本文から抽出する"""
    # Indeed パターン: "山田 太郎さんがあなたの求人に応募しました"
    indeed_match = re.search(r"^(.+?)さんが", subject)
    if indeed_match:
        return indeed_match.group(1).strip()

    # Wantedly パターン: "from 山田太郎" や "山田太郎さんが「気になる」"
    wantedly_match = re.search(r"(.+?)さんが「気になる」", subject)
    if wantedly_match:
        return wantedly_match.group(1).strip()

    # 本文から「氏名」「お名前」のパターン
    name_patterns = [
        r"氏名[：:]\s*(.+?)[\n\r]",
        r"お名前[：:]\s*(.+?)[\n\r]",
        r"名前[：:]\s*(.+?)[\n\r]",
        r"Name[：:]\s*(.+?)[\n\r]",
        r"Full Name[：:]\s*(.+?)[\n\r]",
    ]
    for pattern in name_patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return "（名前未取得）"


def extract_job_title(subject: str, body: str) -> str:
    """応募職種を件名または本文から抽出する"""
    # 件名パターン: "【○○】への応募" や "○○に応募しました"
    title_patterns = [
        r"【(.+?)】",
        r"「(.+?)」",
        r"『(.+?)』",
        r"(.+?)に応募",
        r"(.+?)への応募",
    ]
    for pattern in title_patterns:
        match = re.search(pattern, subject)
        if match:
            title = match.group(1).strip()
            if len(title) < 50:  # 長すぎる場合は除外
                return title

    # 本文から職種を抽出
    job_patterns = [
        r"職種[：:]\s*(.+?)[\n\r]",
        r"ポジション[：:]\s*(.+?)[\n\r]",
        r"Job Title[：:]\s*(.+?)[\n\r]",
    ]
    for pattern in job_patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return "（職種未取得）"


def extract_apply_id(subject: str, body: str) -> Optional[str]:
    """応募IDを抽出する"""
    id_patterns = [
        r"応募ID[：:]\s*([A-Za-z0-9\-]+)",
        r"Application ID[：:]\s*([A-Za-z0-9\-]+)",
        r"エントリーNo[．.：:]\s*([0-9]+)",
    ]
    for pattern in id_patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


# =============================================================================
# メイン解析関数
# =============================================================================

def parse_raw_email(raw_message_bytes: bytes) -> Optional[JobInquiry]:
    """
    生のメールバイト列を解析して JobInquiry を返す。
    求人問い合わせでない場合は None を返す。
    """
    msg = email.message_from_bytes(raw_message_bytes)

    sender = msg.get("From", "")
    subject = decode_mime_header(msg.get("Subject", ""))
    body = extract_plain_text(msg)

    # 送信元メールアドレスを抽出
    sender_match = re.search(r"<(.+?)>", sender)
    sender_email = sender_match.group(1) if sender_match else sender

    # 求人媒体を検出
    platform = detect_platform(sender_email, subject)
    platform_name = platform["name"]
    platform_emoji = platform["emoji"]

    # 求人問い合わせか判定
    if not is_job_inquiry(subject, body, platform_name):
        return None

    # 情報を抽出
    applicant_name = extract_applicant_name(subject, body, platform_name)
    job_title = extract_job_title(subject, body)
    apply_id = extract_apply_id(subject, body)

    # メッセージプレビュー（本文の先頭150文字）
    message_preview = body[:150].replace("\n", " ").strip()
    if len(body) > 150:
        message_preview += "..."

    return JobInquiry(
        platform=platform_name,
        platform_emoji=platform_emoji,
        applicant_name=applicant_name,
        job_title=job_title,
        message_preview=message_preview,
        raw_subject=subject,
        sender_email=sender_email,
        apply_id=apply_id,
    )


def format_chatwork_message(inquiry: JobInquiry) -> str:
    """ChatWork投稿用にメッセージをフォーマットする"""
    lines = [
        f"{inquiry.platform_emoji} 【求人応募通知】{inquiry.platform}",
        "",
        f"応募者: {inquiry.applicant_name}",
        f"職種: {inquiry.job_title}",
    ]
    if inquiry.apply_id:
        lines.append(f"応募ID: {inquiry.apply_id}")

    lines += [
        "",
        "【メッセージ冒頭】",
        inquiry.message_preview,
        "",
        f"件名: {inquiry.raw_subject}",
    ]
    return "\n".join(lines)
