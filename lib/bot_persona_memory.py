"""
ボットペルソナ記憶管理

ソウルくんのキャラ設定・好み・性格などを管理。
全ユーザー共通で参照される設定（例：好物=10円パン、モチーフ動物=狼）

# =====================================================
# ⚠️ 重要: bot_persona_memory の用途制限
# =====================================================
# bot_persona_memory は「会社の公式人格」のみ保存可
# 個人の思想・記憶は絶対に保存してはいけない
#
# 保存可能な例:
#   - ソウルくんの好物 = 10円パン
#   - ソウルくんの口調 = ウル
#   - ソウルくんのモチーフ動物 = 狼
#
# 保存禁止（user_long_term_memory へ振り分け）:
#   - 「社長は〜と言っていた」などの個人発言
#   - 特定の個人の人生軸・価値観
#   - 家族情報
#   - 個人の過去体験・信念
# =====================================================

Author: Claude Code
Created: 2026-01-28
Version: 1.2.1 (v10.40.11: 保存結果に基づく返信修正・デバッグログ追加)
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import text

logger = logging.getLogger(__name__)


# =====================================================
# 定数
# =====================================================

# ボットペルソナのカテゴリ
class PersonaCategory:
    CHARACTER = "character"      # キャラ設定（名前、モチーフなど）
    PERSONALITY = "personality"  # 性格（明るい、元気など）
    PREFERENCE = "preference"    # 好み（好物、趣味など）


# ボットペルソナを示すキーワードパターン
BOT_PERSONA_PATTERNS = [
    # ソウルくん自身への設定
    r"(ソウルくん|そうるくん|soul.?kun)の",
    r"(君|きみ|お前|おまえ)の(好物|好み|性格|名前|口調)",
    r"(好物|好み|性格|名前|口調)は",  # 主語がない場合もボット設定と推定

    # キャラ設定キーワード
    r"キャラ(設定|クター)",
    r"モチーフ(動物)?",
    r"語尾(は|を)",
    r"口調(は|を)",
]

# ボット設定のキーワードリスト
BOT_SETTING_KEYWORDS = [
    "好物", "好み", "モチーフ", "口調", "語尾", "性格", "キャラ",
    "名前", "呼び方", "一人称", "趣味", "特技", "苦手",
]

# カテゴリの日本語ラベル
PERSONA_CATEGORY_LABELS = {
    PersonaCategory.CHARACTER: "キャラ設定",
    PersonaCategory.PERSONALITY: "性格",
    PersonaCategory.PREFERENCE: "好み・趣味",
}


# =====================================================
# v10.40.10: ホワイトリスト方式の個人情報ガード
# =====================================================
# bot_persona_memory に保存可能なのは「ソウルくん自身の設定」のみ
# それ以外の"人間に関する情報"は全て user_long_term_memory へ振り分け

# =====================================================
# ホワイトリスト: ソウルくんの設定として許可するカテゴリ
# =====================================================
# これらに該当し、かつソウルくんを主語とする場合のみ保存許可

# ソウルくんの主語パターン
SOULKUN_SUBJECT_PATTERNS = [
    r"^(ソウルくん|そうるくん|soul.?kun)(の|は|が)",  # 文頭でソウルくんが主語
    r"(君|きみ|お前|おまえ)(の|は|が)",  # 二人称でソウルくんを指す場合
]

# 許可する設定カテゴリ（ホワイトリスト）
ALLOWED_PERSONA_CATEGORIES = {
    # 性格・人格
    "personality": [
        "性格", "人格", "キャラ", "キャラクター",
        "明るい", "元気", "冷静", "ツンデレ", "優しい", "真面目",
    ],
    # 話し方・口調
    "speech": [
        "口調", "語尾", "話し方", "敬語", "タメ口", "一人称",
        "言い回し", "しゃべり方",
    ],
    # 好み・趣味
    "preference": [
        "好物", "好み", "好き", "嫌い", "苦手", "趣味", "特技",
    ],
    # キャラ設定・世界観
    "character": [
        "名前", "呼び方", "モチーフ", "設定", "背景", "ロール",
        "キャラ背景", "世界観",
    ],
}

# 許可キーワードのフラットリスト（検索用）
ALLOWED_KEYWORDS_FLAT = []
for category_keywords in ALLOWED_PERSONA_CATEGORIES.values():
    ALLOWED_KEYWORDS_FLAT.extend(category_keywords)


# =====================================================
# ブラックリスト: 人間情報として拒否するパターン（補助判定）
# =====================================================
# ⚠️ 以下のパターンに該当する内容はbot_persona_memoryに保存禁止
# user_long_term_memory(scope='PRIVATE')へ自動振り分け

# 個人発言パターン（「〜さんは〜と言っていた」「社長が〜」など）
PERSONAL_STATEMENT_PATTERNS = [
    r"(社長|部長|課長|マネージャー|リーダー)(は|が|の)",  # 役職者の発言
    r"[ぁ-んァ-ン一-龥]{2,}(さん|様|くん|君|氏)(は|が|の)",  # 人名の発言
    r"(あの人|この人|その人|彼|彼女)(は|が|の)",  # 代名詞での個人参照
    r"(と言っていた|って言ってた|が言うには|曰く)",  # 引用表現
    r"(の発言|の言葉|が話した|に聞いた)",  # 発言参照
]

# 家族情報パターン
FAMILY_PATTERNS = [
    r"(父|母|両親|妻|夫|嫁|旦那|子供|息子|娘|兄|姉|弟|妹|祖父|祖母|おじいちゃん|おばあちゃん)(は|が|の|を)",
    r"(家族|親戚|身内)(は|が|の|を)",
    r"(パパ|ママ|お父さん|お母さん)(は|が|の|を)",
]

# 個人の人生軸・思想パターン
PERSONAL_THOUGHT_PATTERNS = [
    r"(私|俺|僕|自分|わたし|おれ|ぼく)の(人生|軸|価値観|信念|夢|目標)",
    r"(田中|山田|佐藤|鈴木|高橋|伊藤|渡辺|中村|小林|加藤|吉田|山本)[ぁ-んァ-ン一-龥]*(さん|様|くん|君|氏)?(の|は)(人生|軸|価値観|信念)",
    r"[ぁ-んァ-ン一-龥]{2,}(さん|様|くん|君)の(人生|軸|価値観|信念|夢)",
    r"(人生軸|ライフビジョン|生き方)",  # ソウルくんの設定としては不適切
]

# 個人の過去体験パターン
PERSONAL_EXPERIENCE_PATTERNS = [
    r"(昔|過去に|若い頃|学生時代|子供の頃)(は|に|の|、)",
    r"以前(は|に|の|、)",  # 「以前」を単独でマッチ
    r"(経験した|体験した|思い出|トラウマ)",
    r"(私|俺|僕|自分)が(経験|体験|遭遇)した",
    r"(の経験|の体験)",  # 「以前の経験」などにマッチ
]

# 全ての個人情報パターンを統合
ALL_PERSONAL_INFO_PATTERNS = (
    PERSONAL_STATEMENT_PATTERNS +
    FAMILY_PATTERNS +
    PERSONAL_THOUGHT_PATTERNS +
    PERSONAL_EXPERIENCE_PATTERNS
)

# 個人情報検出時のリダイレクト先メッセージ
REDIRECT_MESSAGE = """⚠️ これは個人的な情報なので、あなた専用の長期記憶として保存したウル！

【保存先】あなたの長期記憶（プライベート）
【理由】{reason}

ソウルくんのキャラ設定ではなく、{user_name}さん個人の大切な情報として覚えておくウル🐺"""


# =====================================================
# 判定関数
# =====================================================

def is_valid_bot_persona(message: str, key: str = "", value: str = "") -> tuple:
    """
    v10.40.10: ホワイトリスト方式でボットペルソナとして有効か判定

    bot_persona_memory に保存可能なのは以下の条件を両方満たす場合のみ:
    1. ソウルくん自身を主語としている（または主語なしでボット設定と推定可能）
    2. 許可されたカテゴリ（性格/話し方/好み/キャラ設定）に該当する

    それ以外の"人間に関する情報"は全て保存拒否。

    Args:
        message: ユーザーメッセージ全体
        key: 抽出されたキー（例：好物、口調）
        value: 抽出された値（例：10円パン、ウル）

    Returns:
        tuple: (is_valid: bool, reason: str)
            - is_valid: True なら保存許可
            - reason: 拒否理由（is_valid=False の場合）
    """
    check_text = message

    # =====================================================
    # STEP 1: ソウルくんが主語かどうか確認
    # =====================================================
    is_soulkun_subject = False

    # 明示的に「ソウルくん」が主語
    if re.search(r"(ソウルくん|そうるくん|soul.?kun)", check_text, re.IGNORECASE):
        is_soulkun_subject = True

    # 二人称 + 「の」 + 許可キーワード の形のみ許可
    # 例：「君の好物は」「きみの口調は」
    # 注意：「君は明るい」などの曖昧な表現は許可しない
    for keyword in ALLOWED_KEYWORDS_FLAT:
        pattern = rf"(君|きみ|お前|おまえ)の{re.escape(keyword)}(は|が|を)?"
        if re.search(pattern, check_text):
            is_soulkun_subject = True
            break

    # 主語なしで許可キーワードで始まる（「好物は〜」→ソウルくんの設定と推定）
    if key and key in ALLOWED_KEYWORDS_FLAT:
        if re.search(r"^" + re.escape(key) + r"(は|を|が)", check_text):
            is_soulkun_subject = True

    # =====================================================
    # STEP 2: 他の人物が主語でないか確認（ソウルくん以外）
    # =====================================================
    # 人名 + 敬称 + 助詞 のパターン（「田中さんの〜」「社長は〜」など）
    if re.search(r"[ぁ-んァ-ン一-龥]{2,}(さん|様|くん|君|氏)(の|は|が)", check_text):
        # ソウルくんは除外
        if not re.search(r"(ソウルくん|そうるくん)", check_text, re.IGNORECASE):
            return (False, "特定の人物に関する情報はソウルくんの設定ではありません")

    # 役職者パターン
    if re.search(r"(社長|部長|課長|マネージャー|リーダー|上司|同僚|後輩)(の|は|が)", check_text):
        return (False, "社員・役職者に関する情報はソウルくんの設定ではありません")

    # 一人称パターン（ユーザー自身の情報）
    if re.search(r"(私|俺|僕|自分|わたし|おれ|ぼく)(の|は|が)(人生|軸|価値観|信念|夢|目標|経験)", check_text):
        return (False, "あなた自身の情報はソウルくんの設定ではありません")

    # 家族パターン
    if re.search(r"(父|母|両親|妻|夫|子供|息子|娘|兄|姉|弟|妹|家族)(の|は|が|を)", check_text):
        return (False, "家族に関する情報はソウルくんの設定ではありません")

    # =====================================================
    # STEP 3: 許可カテゴリに該当するか確認
    # =====================================================
    is_allowed_category = False

    # キーが許可キーワードに含まれている
    if key and key in ALLOWED_KEYWORDS_FLAT:
        is_allowed_category = True

    # メッセージ内に許可キーワードが含まれている
    for keyword in ALLOWED_KEYWORDS_FLAT:
        if keyword in check_text:
            is_allowed_category = True
            break

    # =====================================================
    # STEP 4: 最終判定
    # =====================================================
    if is_soulkun_subject and is_allowed_category:
        return (True, "")

    # ソウルくんが主語だが許可カテゴリでない
    if is_soulkun_subject and not is_allowed_category:
        return (False, "この内容はソウルくんの設定カテゴリに該当しません")

    # 許可カテゴリだがソウルくんが主語でない
    if not is_soulkun_subject and is_allowed_category:
        return (False, "誰の設定か明確でないため保存できません。「ソウルくんの〜」と指定してください")

    # どちらでもない
    return (False, "この内容はソウルくんの設定として認識できません")


def is_personal_information(message: str, value: str = "") -> tuple:
    """
    v10.40.10: メッセージまたは値が個人情報かどうかを判定

    bot_persona_memory への保存を拒否すべき内容かを判定する。
    該当した場合は user_long_term_memory へ振り分ける。

    Args:
        message: ユーザーメッセージ全体
        value: 抽出された値（オプション）

    Returns:
        tuple: (is_personal: bool, reason: str)
            - is_personal: True なら個人情報、保存拒否
            - reason: 拒否理由（リダイレクト時に表示）
    """
    check_text = f"{message} {value}"

    # =====================================================
    # 例外: ソウルくん関連は常に許可（ボット設定として正当）
    # =====================================================
    if re.search(r"(ソウルくん|そうるくん|soul.?kun)", check_text, re.IGNORECASE):
        return (False, "")

    # =====================================================
    # 個人情報パターンチェック（順序重要）
    # =====================================================

    # 1. 家族情報パターンチェック（優先度高い）
    for pattern in FAMILY_PATTERNS:
        if re.search(pattern, check_text, re.IGNORECASE):
            return (True, "家族に関する情報")

    # 2. 個人の人生軸・思想パターンチェック
    for pattern in PERSONAL_THOUGHT_PATTERNS:
        if re.search(pattern, check_text, re.IGNORECASE):
            return (True, "個人の人生軸・価値観")

    # 3. 個人の過去体験パターンチェック
    for pattern in PERSONAL_EXPERIENCE_PATTERNS:
        if re.search(pattern, check_text, re.IGNORECASE):
            return (True, "個人の過去体験・思い出")

    # 4. 個人発言パターンチェック（最後：広範囲にマッチするため）
    for pattern in PERSONAL_STATEMENT_PATTERNS:
        if re.search(pattern, check_text, re.IGNORECASE):
            return (True, "特定の個人の発言・意見")

    return (False, "")


def is_bot_persona_setting(message: str) -> bool:
    """
    メッセージがボットペルソナ設定かどうかを判定

    Args:
        message: ユーザーメッセージ

    Returns:
        True: ボットペルソナ設定
        False: それ以外
    """
    message_lower = message.lower()

    # 「ソウルくんの〜」は明示的にボット設定
    if re.search(r"(ソウルくん|そうるくん|soul.?kun)の", message_lower, re.IGNORECASE):
        return True

    # 「〜さんの好物」「〜様の趣味」は人物情報なので除外（ソウルくん以外の人名）
    # 注意: ソウルくんは上で処理済みなので、ここに来るのはソウルくん以外
    if re.search(r"[ぁ-んァ-ン一-龥](さん|様|くん|君)の(好物|好み|性格|名前|趣味|特技)", message_lower):
        return False

    # パターンマッチ
    for pattern in BOT_PERSONA_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return True

    # キーワードマッチ（「〜は〜」形式）
    for keyword in BOT_SETTING_KEYWORDS:
        if keyword in message_lower:
            # 「好物は〜」形式はボット設定（主語がない=ソウルくんの設定と推定）
            if re.search(r"^" + keyword + r"(は|を|が)", message_lower):
                return True
            # 文頭でなくても、直前に人名がなければボット設定
            if re.search(keyword + r"(は|を|が)", message_lower):
                # 人名が直前にあるかチェック（ソウルくん以外）
                if not re.search(r"[ぁ-んァ-ン一-龥](さん|様|くん|君)の" + keyword, message_lower):
                    return True

    return False


def detect_persona_category(message: str) -> str:
    """
    メッセージからペルソナカテゴリを推定

    Args:
        message: ユーザーメッセージ

    Returns:
        カテゴリ（デフォルト: character）
    """
    message_lower = message.lower()

    # 性格
    if any(kw in message_lower for kw in ["性格", "明るい", "元気", "真面目"]):
        return PersonaCategory.PERSONALITY

    # 好み
    if any(kw in message_lower for kw in ["好物", "好み", "趣味", "好き"]):
        return PersonaCategory.PREFERENCE

    # デフォルト: キャラ設定
    return PersonaCategory.CHARACTER


def extract_persona_key_value(message: str) -> Dict[str, str]:
    """
    メッセージからキーと値を抽出

    例：「好物は10円パン」→ {"key": "好物", "value": "10円パン"}
    例：「ソウルくんの口調はウル」→ {"key": "口調", "value": "ウル"}
    例：「口調はウル」→ {"key": "口調", "value": "ウル"}

    Args:
        message: ユーザーメッセージ

    Returns:
        {"key": str, "value": str}
    """
    result = {"key": "", "value": ""}

    # 「〜は〜」形式を検出（末尾の「だよ」「です」などを考慮）
    match = re.search(
        r"(好物|好み|性格|名前|口調|語尾|モチーフ|キャラ|一人称|趣味|特技|苦手)(は|を|が)(.+?)(?:だよ|です|だウル)?$",
        message
    )
    if match:
        result["key"] = match.group(1)
        result["value"] = match.group(3).strip()
        # 末尾の「だよ」「です」などをさらに除去（念のため）
        result["value"] = re.sub(r"(だよ|です|だウル)$", "", result["value"]).strip()
        return result

    # 「ソウルくんの〜は〜」形式
    match = re.search(
        r"(ソウルくん|そうるくん|soul.?kun)の(.+?)(は|を|が)(.+?)(?:だよ|です|だウル)?$",
        message,
        re.IGNORECASE
    )
    if match:
        result["key"] = match.group(2).strip()
        result["value"] = match.group(4).strip()
        result["value"] = re.sub(r"(だよ|です|だウル)$", "", result["value"]).strip()
        return result

    return result


# =====================================================
# 保存・取得クラス
# =====================================================

class BotPersonaMemoryManager:
    """
    ボットペルソナ記憶の保存・取得を管理

    組織ごとにボット設定を持つ（将来的にマルチテナント対応）
    """

    def __init__(self, pool, org_id: str):
        """
        初期化

        Args:
            pool: DB接続プール
            org_id: 組織ID
        """
        self.pool = pool
        self.org_id = org_id

    def save(
        self,
        key: str,
        value: str,
        category: str = PersonaCategory.CHARACTER,
        created_by_account_id: str = None,
        created_by_name: str = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        ボットペルソナ設定を保存（UPSERT）

        Args:
            key: 設定キー（例：好物）
            value: 設定値（例：10円パン）
            category: カテゴリ
            created_by_account_id: 作成者アカウントID
            created_by_name: 作成者名
            metadata: 追加メタデータ

        Returns:
            保存結果
        """
        try:
            metadata = metadata or {}
            metadata["saved_at"] = datetime.utcnow().isoformat()

            with self.pool.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO bot_persona_memory (
                            organization_id, key, value, category,
                            created_by_account_id, created_by_name, metadata
                        ) VALUES (
                            :org_id, :key, :value, :category,
                            :created_by_account_id, :created_by_name, CAST(:metadata AS jsonb)
                        )
                        ON CONFLICT (organization_id, key)
                        DO UPDATE SET
                            value = :value,
                            category = :category,
                            metadata = bot_persona_memory.metadata || CAST(:metadata AS jsonb),
                            updated_at = CURRENT_TIMESTAMP
                    """),
                    {
                        "org_id": self.org_id,
                        "key": key,
                        "value": value,
                        "category": category,
                        "created_by_account_id": created_by_account_id,
                        "created_by_name": created_by_name,
                        "metadata": json.dumps(metadata),
                    }
                )
                conn.commit()

            logger.info(f"Bot persona saved: {key} = {value}")

            category_label = PERSONA_CATEGORY_LABELS.get(category, "設定")
            return {
                "success": True,
                "message": f"覚えたウル！\n\n【{category_label}】\n・{key}: {value}",
                "key": key,
                "value": value,
            }

        except Exception as e:
            logger.error(f"Bot persona save error: {e}")
            return {
                "success": False,
                "message": f"設定の保存中にエラーが発生したウル: {str(e)}",
                "error": str(e),
            }

    def get(self, key: str) -> Optional[str]:
        """
        特定のキーの値を取得

        Args:
            key: 設定キー

        Returns:
            値（なければNone）
        """
        try:
            with self.pool.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT value FROM bot_persona_memory
                        WHERE organization_id = :org_id AND key = :key
                    """),
                    {"org_id": self.org_id, "key": key}
                ).fetchone()

                if result:
                    return result[0]
                return None

        except Exception as e:
            logger.error(f"Bot persona get error: {e}")
            return None

    def get_all(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        全設定を取得

        Args:
            category: 絞り込むカテゴリ（省略時は全て）

        Returns:
            設定リスト
        """
        try:
            with self.pool.connect() as conn:
                if category:
                    result = conn.execute(
                        text("""
                            SELECT key, value, category, created_at
                            FROM bot_persona_memory
                            WHERE organization_id = :org_id AND category = :category
                            ORDER BY key
                        """),
                        {"org_id": self.org_id, "category": category}
                    ).fetchall()
                else:
                    result = conn.execute(
                        text("""
                            SELECT key, value, category, created_at
                            FROM bot_persona_memory
                            WHERE organization_id = :org_id
                            ORDER BY category, key
                        """),
                        {"org_id": self.org_id}
                    ).fetchall()

                return [
                    {
                        "key": row[0],
                        "value": row[1],
                        "category": row[2],
                        "created_at": row[3].isoformat() if row[3] else None,
                    }
                    for row in result
                ]

        except Exception as e:
            logger.error(f"Bot persona get_all error: {e}")
            return []

    def delete(self, key: str) -> bool:
        """
        設定を削除

        Args:
            key: 設定キー

        Returns:
            成功時True
        """
        try:
            with self.pool.connect() as conn:
                conn.execute(
                    text("""
                        DELETE FROM bot_persona_memory
                        WHERE organization_id = :org_id AND key = :key
                    """),
                    {"org_id": self.org_id, "key": key}
                )
                conn.commit()
            logger.info(f"Bot persona deleted: {key}")
            return True

        except Exception as e:
            logger.error(f"Bot persona delete error: {e}")
            return False

    def format_for_display(self) -> str:
        """
        全設定を表示用にフォーマット

        Returns:
            表示用テキスト
        """
        settings = self.get_all()
        if not settings:
            return "ソウルくんの設定はまだないウル"

        lines = []

        # カテゴリごとにグループ化
        by_category = {}
        for s in settings:
            cat = s["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(f"・{s['key']}: {s['value']}")

        for cat, items in by_category.items():
            cat_label = PERSONA_CATEGORY_LABELS.get(cat, cat)
            lines.append(f"\n【{cat_label}】")
            lines.extend(items)

        return "\n".join(lines)


# =====================================================
# 便利関数
# =====================================================

def save_bot_persona(
    pool,
    org_id: str,
    message: str,
    account_id: str = None,
    sender_name: str = None,
    user_id: int = None
) -> Dict[str, Any]:
    """
    メッセージからボットペルソナ設定を保存

    v10.40.10: ホワイトリスト方式の個人情報ガード
    - is_valid_bot_persona() で最終判定（ソウルくん自身の設定のみ許可）
    - それ以外は全て user_long_term_memory へ自動振り分け

    Args:
        pool: DB接続プール
        org_id: 組織ID
        message: ユーザーメッセージ
        account_id: 作成者アカウントID
        sender_name: 作成者名
        user_id: ユーザーID（個人情報振り分け時に必要）

    Returns:
        保存結果
    """
    # キーと値を抽出
    kv = extract_persona_key_value(message)
    if not kv["key"] or not kv["value"]:
        return {
            "success": False,
            "message": "設定内容を理解できなかったウル...「好物は〇〇」のように教えてほしいウル！",
        }

    # v10.40.10: ホワイトリスト方式の判定（最終判定）
    is_valid, reason = is_valid_bot_persona(message, kv["key"], kv["value"])

    if not is_valid:
        logger.warning(
            f"🚫 ホワイトリスト判定で拒否 - bot_persona_memory保存不可: "
            f"key={kv['key']}, reason={reason}, sender={sender_name}"
        )

        # 補助判定: is_personal_information() でより詳細な理由を取得（ログ用）
        is_personal, personal_reason = is_personal_information(message, kv["value"])
        if is_personal:
            logger.info(f"   補助判定: 個人情報として検出 ({personal_reason})")

        # user_long_term_memory へリダイレクト
        if user_id is not None:
            try:
                # long_term_memory モジュールをインポート
                try:
                    from lib.long_term_memory import save_long_term_memory, MemoryScope
                except ImportError:
                    from long_term_memory import save_long_term_memory, MemoryScope

                # 個人の長期記憶として保存
                result = save_long_term_memory(
                    pool=pool,
                    org_id=org_id,
                    user_id=user_id,
                    user_name=sender_name or "あなた",
                    message=f"{kv['key']}は{kv['value']}",
                    scope=MemoryScope.PRIVATE
                )

                if result["success"]:
                    return {
                        "success": True,
                        "message": REDIRECT_MESSAGE.format(
                            reason=reason,
                            user_name=sender_name or "あなた"
                        ),
                        "redirected_to": "user_long_term_memory",
                        "reason": reason,
                    }
                else:
                    return result

            except Exception as e:
                logger.error(f"❌ 長期記憶へのリダイレクト失敗: {e}")
                return {
                    "success": False,
                    "message": f"保存中にエラーが発生したウル: {str(e)}",
                    "error": str(e),
                }
        else:
            # user_id がない場合は保存拒否のみ
            return {
                "success": False,
                "message": (
                    f"⚠️ この内容はソウルくんの設定として保存できないウル。\n"
                    f"【理由】{reason}\n\n"
                    "ソウルくんの設定は「ソウルくんの好物は〜」のように指定してほしいウル！\n"
                    "個人的な情報は「人生軸として覚えて」と伝えてくれたら保存するウル！"
                ),
                "blocked": True,
                "reason": reason,
            }

    # カテゴリを推定
    category = detect_persona_category(message)

    # 保存
    manager = BotPersonaMemoryManager(pool, org_id)
    return manager.save(
        key=kv["key"],
        value=kv["value"],
        category=category,
        created_by_account_id=account_id,
        created_by_name=sender_name
    )


def get_bot_persona(pool, org_id: str, key: str) -> Optional[str]:
    """
    ボットペルソナ設定を取得

    Args:
        pool: DB接続プール
        org_id: 組織ID
        key: 設定キー

    Returns:
        値（なければNone）
    """
    manager = BotPersonaMemoryManager(pool, org_id)
    return manager.get(key)


# =====================================================
# v10.40.10: 起動時安全確認
# =====================================================

def scan_bot_persona_for_personal_info(pool, org_id: str) -> List[Dict[str, Any]]:
    """
    v10.40.10: bot_persona_memory 内の個人情報をスキャン

    起動時に呼び出し、個人情報を含む可能性があるレコードを
    WARNING ログで報告する。削除は行わない（手動確認用）。

    Args:
        pool: DB接続プール
        org_id: 組織ID

    Returns:
        警告対象のレコードリスト
    """
    warnings = []

    try:
        manager = BotPersonaMemoryManager(pool, org_id)
        all_records = manager.get_all()

        for record in all_records:
            key = record.get("key", "")
            value = record.get("value", "")

            # 個人情報チェック
            is_personal, reason = is_personal_information(key, value)

            if is_personal:
                warning_record = {
                    "key": key,
                    "value": value,
                    "category": record.get("category"),
                    "reason": reason,
                    "created_at": record.get("created_at"),
                }
                warnings.append(warning_record)

                logger.warning(
                    f"⚠️ [bot_persona_memory安全確認] 個人情報の可能性あり:\n"
                    f"   key: {key}\n"
                    f"   value: {value[:50]}{'...' if len(value) > 50 else ''}\n"
                    f"   reason: {reason}\n"
                    f"   ※手動確認してください（自動削除はしません）"
                )

        if warnings:
            logger.warning(
                f"⚠️ [bot_persona_memory安全確認] "
                f"org_id={org_id} で {len(warnings)} 件の警告があります"
            )
        else:
            logger.info(
                f"✅ [bot_persona_memory安全確認] "
                f"org_id={org_id} は問題なし"
            )

        return warnings

    except Exception as e:
        logger.error(f"❌ bot_persona_memory スキャンエラー: {e}")
        return []


def scan_all_organizations_bot_persona(pool) -> Dict[str, List[Dict[str, Any]]]:
    """
    v10.40.10: 全組織の bot_persona_memory をスキャン

    起動時に全組織の bot_persona_memory をスキャンし、
    個人情報を含む可能性があるレコードを報告する。

    Args:
        pool: DB接続プール

    Returns:
        組織IDをキーとした警告レコードの辞書
    """
    all_warnings = {}

    try:
        with pool.connect() as conn:
            # 全組織IDを取得
            result = conn.execute(
                text("SELECT DISTINCT organization_id FROM bot_persona_memory")
            ).fetchall()

            org_ids = [str(row[0]) for row in result]

        logger.info(f"🔍 [bot_persona_memory安全確認] {len(org_ids)} 組織をスキャン開始")

        for org_id in org_ids:
            warnings = scan_bot_persona_for_personal_info(pool, org_id)
            if warnings:
                all_warnings[org_id] = warnings

        total_warnings = sum(len(w) for w in all_warnings.values())
        if total_warnings > 0:
            logger.warning(
                f"⚠️ [bot_persona_memory安全確認] "
                f"合計 {total_warnings} 件の警告（{len(all_warnings)} 組織）"
            )
        else:
            logger.info("✅ [bot_persona_memory安全確認] 全組織で問題なし")

        return all_warnings

    except Exception as e:
        logger.error(f"❌ 全組織スキャンエラー: {e}")
        return {}
