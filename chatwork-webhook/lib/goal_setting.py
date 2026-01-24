"""
目標設定対話フロー管理モジュール（Phase 2.5 v1.7）

アチーブメント社・選択理論に基づく目標設定対話を管理。
WHY → WHAT → HOW の順で一問一答形式で目標を設定する。

v1.7 変更点:
- 臨機応変な対応（Adaptive Response Enhancement）
  - 質問検出（？で終わる、「どうしたらいい」等）
  - 困惑検出（全ステップで「わからない」「難しい」等）
  - 極端に短い回答の検出（<5文字、5-10文字）
  - 具体性スコアリングの強化
  - コンテキスト認識（前回答の参照、リトライ回数に応じた対応）
  - 新規テンプレート追加

使用例:
    from lib.goal_setting import GoalSettingDialogue

    dialogue = GoalSettingDialogue(pool, room_id, account_id)
    response = dialogue.process_message(user_message)
"""

from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple
from uuid import uuid4
from sqlalchemy import text
import json
import re


# =====================================================
# 定数定義
# =====================================================

# セッションステップ
STEPS = {
    "intro": "導入",
    "why": "WHY（内発的動機）",
    "what": "WHAT（結果目標）",
    "how": "HOW（行動目標）",
    "complete": "完了"
}

# ステップ遷移
STEP_ORDER = ["intro", "why", "what", "how", "complete"]

# 最大リトライ回数（同じステップでの再質問上限）
MAX_RETRY_COUNT = 3


# =====================================================
# 対話テンプレート
# =====================================================

TEMPLATES = {
    # 導入（アジェンダ提示 + WHYへ）
    "intro": """🎯 目標設定を始めるウル！

ソウルくんと一緒に、{user_name}さんの目標を整理していこうウル🐺

📋 これから3つの質問をするウル：
1️⃣ WHY - なぜその目標を達成したいのか
2️⃣ WHAT - 具体的に何を達成したいのか
3️⃣ HOW - どんな行動で達成するのか

それでは最初の質問ウル！

━━━━━━━━━━━━━━━━━━
❓ 【WHY】この先、仕事を通じてどんな自分になりたいですか？
━━━━━━━━━━━━━━━━━━

「〇〇な存在になりたい」「△△を実現したい」など、
{user_name}さんの想いを自由に教えてウル🐺✨""",

    # WHY完了 → WHAT質問
    "why_to_what": """💡 なるほどウル！

{feedback}

━━━━━━━━━━━━━━━━━━
❓ 【WHAT】その想いを実現するために、具体的にどんな成果を出したいですか？
━━━━━━━━━━━━━━━━━━

数字や期限を入れてくれると、進捗が追いやすくなるウル🐺
例：「今月の粗利300万円達成」「月末までにプロジェクト完了」""",

    # WHAT完了 → HOW質問
    "what_to_how": """👍 素晴らしい目標ウル！

{feedback}

━━━━━━━━━━━━━━━━━━
❓ 【HOW】その目標を達成するために、毎日・毎週どんな行動をしますか？
━━━━━━━━━━━━━━━━━━

「毎日〇〇をする」「週に△回□□をする」など、
具体的なアクションを教えてウル🐺""",

    # HOW完了 → 目標登録
    "complete": """🎉 目標設定完了ウル！

{user_name}さんの目標をまとめたウル🐺

━━━━━━━━━━━━━━━━━━
📌 WHY（なりたい姿）
{why_answer}

🎯 WHAT（結果目標）
{what_answer}

💪 HOW（行動目標）
{how_answer}
━━━━━━━━━━━━━━━━━━

✅ 目標を登録したウル！

{user_name}さんなら絶対達成できるって、ソウルくんは信じてるウル💪🐺
毎日17時に進捗を聞くから、一緒に頑張っていこうウル✨""",

    # NG応答: 抽象的すぎる
    "ng_abstract": """🤔 もう少し具体的に教えてほしいウル！

「{user_answer}」という気持ちはとてもわかるウル🐺

でも、もう少し詳しく教えてくれると嬉しいウル！

例えば...
- いつまでに？
- どのくらい？
- 何を？

もう一度、具体的に教えてウル🐺✨""",

    # NG応答: 転職・副業志向
    "ng_career": """💭 いろんな可能性を考えているんだね！

{user_name}さんがキャリアについて真剣に考えているのは素晴らしいウル🐺

ところで、もし今の会社で「これが実現できたら最高だな」って思うことはあるかな？

会社の中で達成したいこと、成し遂げたいことを教えてほしいウル🐺✨""",

    # NG応答: 他責思考
    "ng_other_blame": """😊 大変な状況なんだね...

{user_name}さんの気持ち、よくわかるウル🐺
環境や周りの人に影響を受けることってあるよね。

でもね、ソウルくんは{user_name}さんの可能性を信じてるウル！

「自分でコントロールできること」で、変えていきたいことはあるかな？
{user_name}さん自身が行動できることを教えてほしいウル🐺✨""",

    # NG応答: 目標がない
    "ng_no_goal": """🌟 目標がないって感じること、あるよね！

でもね、{user_name}さんにも必ず「こうなったらいいな」って思うことがあるはずウル🐺

小さなことでも大丈夫ウル！
- 「もう少し〇〇ができるようになりたい」
- 「△△な仕事がしてみたい」
- 「□□を達成してみたい」

どんな小さなことでもいいから、教えてほしいウル🐺✨""",

    # NG応答: 目標が高すぎる
    "ng_too_high": """🚀 大きな目標を持ってるんだね！

{user_name}さんの志の高さ、素晴らしいウル🐺

ただ、まずは「最初の一歩」を考えてみない？

その大きな目標に向かって、今月達成できそうなマイルストーンは何かな？
小さな成功を積み重ねていこうウル🐺✨""",

    # NG応答: 結果目標と繋がらない
    "ng_not_connected": """🔗 ちょっと確認させてウル！

さっき教えてくれた結果目標は「{what_answer}」だったよね？

今の行動目標「{user_answer}」が、どう結果につながるか教えてほしいウル🐺

もし別の行動のほうが結果に直結しそうなら、それを教えてほしいウル✨""",

    # NG応答: メンタルヘルス懸念
    "ng_mental_health": """💙 {user_name}さん、大丈夫...？

ちょっと辛そうに見えるウル🐺

もし今しんどい状態なら、無理に目標を立てなくてもいいウル。
まずは自分の心と体を大事にしてほしいウル。

もしよかったら、上司や人事の人に相談してみてもいいかもウル。
ソウルくんはいつでも{user_name}さんの味方ウル🐺💙

目標設定は、元気な時にまたやろうウル✨""",

    # NG応答: プライベート目標のみ
    "ng_private_only": """🏃 素敵な目標ウル！

「{user_answer}」、プライベートを充実させるのは大事ウル🐺

ところで、お仕事の方でも何か達成したいことはあるかな？

プライベートと仕事、両方充実させていけたら最高ウル！
仕事での目標も教えてほしいウル🐺✨""",

    # =====================================================
    # v1.7 新規: ヘルプ・質問対応テンプレート
    # =====================================================

    # 質問への回答: WHYステップ
    "help_question_why": """📝 良い質問ウル！説明するね！

【WHY】は「どんな自分になりたいか」を聞いているウル🐺

例えばこんな感じ：
• 「チームを引っ張れるリーダーになりたい」
• 「お客様から指名される営業になりたい」
• 「後輩に頼られる先輩になりたい」
• 「この分野の第一人者として認められたい」

仕事を通じて、{user_name}さんがどんな姿を目指しているか、
自由に教えてほしいウル🐺✨""",

    # 質問への回答: WHATステップ
    "help_question_what": """📝 良い質問ウル！説明するね！

【WHAT】は「具体的に何を達成したいか」を聞いているウル🐺

例えばこんな感じ：
• 「今月の売上を300万円達成する」
• 「今月中に新規顧客を5件獲得する」
• 「月末までにプロジェクトを完了させる」
• 「今週中に提案書を3本作成する」

**数字や期限**を入れてくれると、進捗が追いやすくなるウル！
{user_name}さんが達成したい成果を教えてほしいウル🐺✨""",

    # 質問への回答: HOWステップ
    "help_question_how": """📝 良い質問ウル！説明するね！

【HOW】は「毎日・毎週どんな行動をするか」を聞いているウル🐺

例えばこんな感じ：
• 「毎日30分、見込み客にアプローチの電話をする」
• 「週に3回、お客様訪問をする」
• 「毎朝10分、業界ニュースをチェックする」
• 「毎日退勤前に翌日のタスクを整理する」

目標達成のために、{user_name}さんが**習慣にしたい行動**を教えてほしいウル🐺✨""",

    # 困惑・迷い: WHYステップ
    "help_confused_why": """🤔 迷っちゃうよね、わかるウル！

{user_name}さん、急に「どんな自分になりたい？」って聞かれても、
すぐに答えが出ないこともあるウル🐺

こんな風に考えてみてほしいウル：

1. **最近「やった！」と思えた瞬間**は何かな？
2. **「こうなれたらいいな」**と憧れる先輩や同僚はいるかな？
3. **1年後の自分**がどうなっていたら嬉しいかな？

小さなことでも大丈夫ウル！
{user_name}さんの気持ちを教えてほしいウル🐺✨""",

    # 困惑・迷い: WHATステップ
    "help_confused_what": """🤔 具体的な数字って、難しいよね！

{user_name}さん、大丈夫ウル！一緒に考えようウル🐺

さっき「{why_summary}」って教えてくれたよね。

その想いを叶えるために、今月やれそうなことを考えてみようウル：

• **数で測れること**: 〇件、〇人、〇回など
• **期限で測れること**: 〇日までに完了、〇月末までに提出など
• **達成度で測れること**: 〇%達成、〇点以上など

どれかピンとくるものはあるかな？🐺✨""",

    # 困惑・迷い: HOWステップ
    "help_confused_how": """🤔 行動目標、迷うよね！

{user_name}さん、一緒に考えようウル🐺

目標は「{what_summary}」だったよね。

これを達成するために、**毎日または毎週できる小さな行動**を考えてみようウル：

• **毎日5分でもできること**は何かな？
• **週に1回は必ずやること**は何かな？
• **習慣にしたいこと**は何かな？

大きな行動じゃなくて、**続けられる小さな行動**でOKウル🐺✨""",

    # 極端に短い回答
    "too_short": """🤔 もう少し詳しく教えてほしいウル！

「{user_answer}」だけだと、ソウルくんには{user_name}さんの気持ちが
よくわからないウル🐺

{step_guidance}

{user_name}さんの考えを、もう少し詳しく教えてほしいウル🐺✨""",

    # リトライ2回目用（少し優しいトーン）
    "retry_gentle": """😊 大丈夫、ゆっくり考えようウル！

{user_name}さん、焦らなくていいウル🐺

{step_hint}

どんな小さなことでもいいから、{user_name}さんの言葉で教えてほしいウル🐺✨""",

    # リトライ3回目用（受け入れ準備）
    "retry_accepting": """👍 {user_name}さんの気持ち、受け取ったウル！

「{user_answer}」という想い、大事にしようウル🐺

これでいいなら、このまま次に進もうウル！
もし変えたい場合は、もう一度教えてほしいウル🐺✨""",
}


# =====================================================
# パターン検出キーワード
# =====================================================

PATTERN_KEYWORDS = {
    "ng_abstract": [
        "成長", "頑張る", "良くなりたい", "向上", "スキルアップ",
        "もっと", "いい感じ", "いろいろ", "なんとなく", "とりあえず"
    ],
    "ng_career": [
        "転職", "副業", "市場価値", "どこでも通用", "独立",
        "フリーランス", "起業", "他社", "辞め", "退職"
    ],
    "ng_other_blame": [
        "上司が", "会社が", "環境が", "せいで", "のせい",
        "評価してくれない", "わかってくれない", "認めてくれない",
        "教えてくれない", "やらせてくれない"
    ],
    "ng_no_goal": [
        "特にない", "今のまま", "考えてない",
        "ないです", "ありません", "思いつかない"
    ],
    "ng_mental_health": [
        "疲れた", "しんどい", "辛い", "やる気が出ない", "限界",
        "無理", "死にたい", "辞めたい", "消えたい", "もう嫌",
        "つらい", "きつい", "病んで", "鬱", "うつ"
    ],
    "ng_private_only": [
        "ダイエット", "趣味", "旅行", "痩せたい", "筋トレ",
        "資格", "プライベート", "休み", "休暇"
    ],
    # v1.7 新規: 質問・ヘルプ要求パターン
    "help_question": [
        "どうしたらいい", "どうすれば", "何を書けば", "どんなこと",
        "どういう", "どのような", "何を言えば", "何を答えれば",
        "例えば", "具体的には", "教えて"
    ],
    # v1.7 新規: 困惑・迷いパターン（全ステップ共通）
    "help_confused": [
        "わからない", "わかりません", "難しい", "迷う", "悩む",
        "考え中", "思いつかない", "ピンとこない", "イメージできない"
    ],
}

# v1.7 新規: 極端に短い回答の閾値
LENGTH_THRESHOLDS = {
    "extremely_short": 5,   # 5文字未満は極端に短い
    "very_short": 10,       # 10文字未満は非常に短い
    "short": 20,            # 20文字未満は短い
    "adequate": 30,         # 30文字以上は適切
}

# v1.7 新規: ステップ別の期待キーワード
STEP_EXPECTED_KEYWORDS = {
    "why": {
        "positive": ["なりたい", "したい", "目指", "実現", "達成", "貢献"],
        "numeric": False,
        "deadline": False,
    },
    "what": {
        "positive": ["達成", "完了", "獲得", "増やす", "減らす", "改善"],
        "numeric": True,   # 数値目標が望ましい
        "deadline": True,  # 期限が望ましい
    },
    "how": {
        "positive": ["する", "やる", "行う", "実施", "毎日", "毎週", "週に", "日に"],
        "numeric": False,
        "deadline": False,
    },
}


class GoalSettingDialogue:
    """
    目標設定対話フロー管理クラス

    一問一答形式で目標設定をガイドする。
    WHY → WHAT → HOW の順で質問し、AI評価を行う。
    """

    def __init__(self, pool, room_id: str, account_id: str):
        """
        初期化

        Args:
            pool: SQLAlchemy コネクションプール
            room_id: ChatWorkルームID
            account_id: ChatWorkアカウントID
        """
        self.pool = pool
        self.room_id = str(room_id)
        self.account_id = str(account_id)
        self.user_id = None
        self.org_id = None
        self.user_name = None
        self.session = None

    def _get_user_info(self, conn) -> bool:
        """ユーザー情報を取得"""
        result = conn.execute(
            text("""
                SELECT id, organization_id, name FROM users
                WHERE chatwork_account_id = :account_id
                LIMIT 1
            """),
            {"account_id": self.account_id}
        ).fetchone()

        if not result:
            return False

        self.user_id = str(result[0])
        self.org_id = str(result[1]) if result[1] else None
        self.user_name = result[2] or "ユーザー"
        return True

    def _get_active_session(self, conn) -> Optional[Dict[str, Any]]:
        """
        アクティブなセッションを取得

        24時間以内の未完了セッションを検索。
        """
        result = conn.execute(
            text("""
                SELECT id, current_step, why_answer, what_answer, how_answer,
                       started_at, expires_at
                FROM goal_setting_sessions
                WHERE user_id = :user_id
                  AND organization_id = :org_id
                  AND chatwork_room_id = :room_id
                  AND status = 'in_progress'
                  AND expires_at > CURRENT_TIMESTAMP
                ORDER BY started_at DESC
                LIMIT 1
            """),
            {
                "user_id": self.user_id,
                "org_id": self.org_id,
                "room_id": self.room_id
            }
        ).fetchone()

        if not result:
            return None

        return {
            "id": str(result[0]),
            "current_step": result[1],
            "why_answer": result[2],
            "what_answer": result[3],
            "how_answer": result[4],
            "started_at": result[5],
            "expires_at": result[6]
        }

    def _create_session(self, conn) -> str:
        """
        新規セッションを作成

        v10.19.4: セッションは最初から 'why' ステップで作成する。
        'intro' は論理的なステップとしては存在せず、イントロメッセージ送信後は
        すぐに WHY ステップに入る。これにより、ユーザーの最初の返信が
        必ず WHY 回答として処理される。
        """
        session_id = str(uuid4())
        conn.execute(
            text("""
                INSERT INTO goal_setting_sessions (
                    id, organization_id, user_id, chatwork_room_id,
                    status, current_step, started_at, expires_at
                ) VALUES (
                    :id, :org_id, :user_id, :room_id,
                    'in_progress', 'why', CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP + INTERVAL '24 hours'
                )
            """),
            {
                "id": session_id,
                "org_id": self.org_id,
                "user_id": self.user_id,
                "room_id": self.room_id
            }
        )
        conn.commit()
        return session_id

    def _update_session(self, conn, session_id: str,
                       current_step: str,
                       why_answer: str = None,
                       what_answer: str = None,
                       how_answer: str = None,
                       status: str = None,
                       goal_id: str = None) -> None:
        """セッションを更新"""
        updates = ["updated_at = CURRENT_TIMESTAMP", "last_activity_at = CURRENT_TIMESTAMP"]
        params = {"session_id": session_id}

        updates.append("current_step = :current_step")
        params["current_step"] = current_step

        if why_answer is not None:
            updates.append("why_answer = :why_answer")
            params["why_answer"] = why_answer

        if what_answer is not None:
            updates.append("what_answer = :what_answer")
            params["what_answer"] = what_answer

        if how_answer is not None:
            updates.append("how_answer = :how_answer")
            params["how_answer"] = how_answer

        if status is not None:
            updates.append("status = :status")
            params["status"] = status
            if status == "completed":
                updates.append("completed_at = CURRENT_TIMESTAMP")

        if goal_id is not None:
            updates.append("goal_id = :goal_id")
            params["goal_id"] = goal_id

        conn.execute(
            text(f"UPDATE goal_setting_sessions SET {', '.join(updates)} WHERE id = :session_id"),
            params
        )
        conn.commit()

    def _log_interaction(self, conn, session_id: str, step: str,
                        user_message: str, ai_response: str,
                        detected_pattern: str = None,
                        evaluation_result: dict = None,
                        feedback_given: bool = False,
                        result: str = None,
                        step_attempt: int = 1) -> None:
        """対話ログを記録"""
        log_id = str(uuid4())
        conn.execute(
            text("""
                INSERT INTO goal_setting_logs (
                    id, organization_id, session_id, user_id,
                    step, step_attempt, user_message, ai_response,
                    detected_pattern, evaluation_result, feedback_given, result
                ) VALUES (
                    :id, :org_id, :session_id, :user_id,
                    :step, :step_attempt, :user_message, :ai_response,
                    :detected_pattern, :evaluation_result, :feedback_given, :result
                )
            """),
            {
                "id": log_id,
                "org_id": self.org_id,
                "session_id": session_id,
                "user_id": self.user_id,
                "step": step,
                "step_attempt": step_attempt,
                "user_message": user_message,
                "ai_response": ai_response,
                "detected_pattern": detected_pattern,
                "evaluation_result": json.dumps(evaluation_result) if evaluation_result else None,
                "feedback_given": feedback_given,
                "result": result
            }
        )
        conn.commit()

    def _get_step_attempt_count(self, conn, session_id: str, step: str) -> int:
        """現在のステップの試行回数を取得"""
        result = conn.execute(
            text("""
                SELECT COUNT(*) FROM goal_setting_logs
                WHERE session_id = :session_id
                  AND organization_id = :org_id
                  AND step = :step
            """),
            {"session_id": session_id, "org_id": self.org_id, "step": step}
        ).fetchone()
        return (result[0] or 0) + 1

    def _detect_pattern(self, message: str, step: str,
                        context: Dict[str, Any] = None) -> Tuple[str, Dict[str, Any]]:
        """
        パターンを検出（v1.7 拡張版）

        キーワードベースの検出 + 文脈考慮。
        将来的にはAI評価との併用を予定。

        Args:
            message: ユーザーのメッセージ
            step: 現在のステップ ('why', 'what', 'how')
            context: コンテキスト情報（セッションデータ、リトライ回数など）

        Returns:
            (pattern_code, evaluation_result)
        """
        context = context or {}
        message_lower = message.lower()
        message_length = len(message.strip())

        evaluation = {
            "detected_keywords": [],
            "specificity_score": 0.0,
            "issues": [],
            "message_length": message_length,
            "is_question": False,
            "is_confused": False,
            "retry_count": context.get("retry_count", 0),
        }

        # =====================================================
        # Phase 1: 優先度最高のパターン検出
        # =====================================================

        # 1-1. メンタルヘルス懸念は最優先でチェック
        for keyword in PATTERN_KEYWORDS["ng_mental_health"]:
            if keyword in message:
                evaluation["detected_keywords"].append(keyword)
                evaluation["issues"].append("mental_health_concern")
                return "ng_mental_health", evaluation

        # =====================================================
        # Phase 2: v1.7新規 - 質問・ヘルプ要求の検出
        # =====================================================

        # 2-1. 質問形式の検出（？で終わる）
        if message.strip().endswith("？") or message.strip().endswith("?"):
            evaluation["is_question"] = True
            evaluation["issues"].append("question_detected")
            # 質問キーワードもチェック
            for keyword in PATTERN_KEYWORDS["help_question"]:
                if keyword in message:
                    evaluation["detected_keywords"].append(keyword)
            return f"help_question_{step}", evaluation

        # 2-2. ヘルプ要求パターンの検出
        for keyword in PATTERN_KEYWORDS["help_question"]:
            if keyword in message:
                evaluation["detected_keywords"].append(keyword)
                evaluation["is_question"] = True

        if evaluation["is_question"]:
            evaluation["issues"].append("help_request")
            return f"help_question_{step}", evaluation

        # 2-3. 困惑・迷いパターンの検出（全ステップ共通）
        for keyword in PATTERN_KEYWORDS["help_confused"]:
            if keyword in message:
                evaluation["detected_keywords"].append(keyword)
                evaluation["is_confused"] = True

        if evaluation["is_confused"]:
            evaluation["issues"].append("confused")
            return f"help_confused_{step}", evaluation

        # =====================================================
        # Phase 3: 既存パターン検出（優先度順） - 長さチェックより先に実行
        # =====================================================

        # 各パターンをチェック（重要なパターンは短いメッセージでも検出する）
        for pattern, keywords in PATTERN_KEYWORDS.items():
            if pattern in ["ng_mental_health", "help_question", "help_confused"]:
                continue  # 既にチェック済み

            for keyword in keywords:
                if keyword in message:
                    evaluation["detected_keywords"].append(keyword)

        # 検出されたパターンを判定
        if evaluation["detected_keywords"]:
            detected_patterns = []
            for pattern, keywords in PATTERN_KEYWORDS.items():
                if pattern in ["help_question", "help_confused"]:
                    continue
                if any(kw in evaluation["detected_keywords"] for kw in keywords):
                    detected_patterns.append(pattern)

            evaluation["issues"].extend(detected_patterns)

            # 優先度順に返す（重要なパターンを先に）
            # 1. 転職・副業志向（WHYステップのみ）
            if step == "why" and "ng_career" in detected_patterns:
                return "ng_career", evaluation
            # 2. 他責思考
            if "ng_other_blame" in detected_patterns:
                return "ng_other_blame", evaluation
            # 3. 目標がない（WHYステップのみ - 「わからない」はhelp_confusedで処理）
            if step == "why" and "ng_no_goal" in detected_patterns:
                return "ng_no_goal", evaluation
            # 4. プライベート目標のみ（WHY/WHATステップ）
            if step in ["why", "what"] and "ng_private_only" in detected_patterns:
                return "ng_private_only", evaluation
            # 5. 抽象的すぎる（ただし極端に短い場合はtoo_shortを優先）
            if "ng_abstract" in detected_patterns:
                if message_length >= LENGTH_THRESHOLDS["very_short"]:
                    return "ng_abstract", evaluation

        # =====================================================
        # Phase 4: v1.7新規 - 極端に短い回答の検出
        # ※ 重要なパターン検出の後に実行
        # =====================================================

        if message_length < LENGTH_THRESHOLDS["extremely_short"]:
            # 5文字未満は極端に短い
            evaluation["issues"].append("extremely_short")
            evaluation["specificity_score"] = 0.1
            return "too_short", evaluation

        if message_length < LENGTH_THRESHOLDS["very_short"]:
            # 5-10文字は非常に短い
            evaluation["issues"].append("very_short")
            evaluation["specificity_score"] = 0.2
            return "too_short", evaluation

        # =====================================================
        # Phase 5: v1.7強化 - 具体性スコアリング
        # =====================================================

        specificity_score = self._calculate_specificity_score(message, step)
        evaluation["specificity_score"] = specificity_score

        # ステップ別の具体性チェック
        if step == "what":
            # WHATは数値目標が望ましい
            has_numbers = bool(re.search(r'\d+', message))
            has_deadline = self._has_deadline_expression(message)

            if not has_numbers and message_length < LENGTH_THRESHOLDS["short"]:
                evaluation["issues"].append("too_abstract")
                evaluation["issues"].append("no_numeric_target")
                return "ng_abstract", evaluation

        elif step == "how":
            # HOWは具体的な行動が望ましい
            has_action = self._has_action_expression(message)

            if not has_action and message_length < LENGTH_THRESHOLDS["short"]:
                evaluation["issues"].append("too_abstract")
                evaluation["issues"].append("no_action_verb")
                return "ng_abstract", evaluation

        # =====================================================
        # Phase 6: 問題なし
        # =====================================================
        return "ok", evaluation

    def _calculate_specificity_score(self, message: str, step: str) -> float:
        """
        具体性スコアを計算（v1.7新規）

        0.0 〜 1.0 のスコアを返す。

        計算要素:
        - 文字数（長いほど高い、上限あり）
        - 数値表現の有無
        - 期限表現の有無
        - 行動動詞の有無（HOWステップ）
        - ステップ別期待キーワードの有無
        """
        score = 0.0
        message_length = len(message.strip())

        # 1. 文字数スコア（最大0.3）
        if message_length >= LENGTH_THRESHOLDS["adequate"]:
            score += 0.3
        elif message_length >= LENGTH_THRESHOLDS["short"]:
            score += 0.2
        elif message_length >= LENGTH_THRESHOLDS["very_short"]:
            score += 0.1

        # 2. 数値表現スコア（最大0.2）
        if bool(re.search(r'\d+', message)):
            score += 0.2

        # 3. 期限表現スコア（最大0.2）
        if self._has_deadline_expression(message):
            score += 0.2

        # 4. ステップ別期待キーワードスコア（最大0.2）
        if step in STEP_EXPECTED_KEYWORDS:
            expected = STEP_EXPECTED_KEYWORDS[step]
            if any(kw in message for kw in expected["positive"]):
                score += 0.2

        # 5. 行動動詞スコア（HOWステップのみ、最大0.1）
        if step == "how" and self._has_action_expression(message):
            score += 0.1

        return min(score, 1.0)

    def _has_deadline_expression(self, message: str) -> bool:
        """期限表現があるかチェック（v1.7新規）"""
        deadline_patterns = [
            r'\d+月', r'\d+日', r'\d+週',  # 数字+単位
            r'今月', r'来月', r'今週', r'来週',  # 相対期限
            r'月末', r'週末', r'年末', r'期末',  # 期限表現
            r'まで', r'期限', r'締め切り', r'締切',  # 期限キーワード
            r'〜までに', r'～までに',  # パターン
        ]
        return any(re.search(pattern, message) for pattern in deadline_patterns)

    def _has_action_expression(self, message: str) -> bool:
        """行動表現があるかチェック（v1.7新規）"""
        action_patterns = [
            r'する', r'やる', r'行う', r'実施',
            r'毎日', r'毎週', r'毎朝', r'毎晩',
            r'週に\d+', r'日に\d+', r'月に\d+',
            r'\d+回', r'\d+件', r'\d+分',
            r'続ける', r'習慣', r'ルーティン',
        ]
        return any(re.search(pattern, message) for pattern in action_patterns)

    def _register_goal(self, conn, session: Dict[str, Any]) -> str:
        """
        目標をgoalsテーブルに登録

        Returns:
            goal_id
        """
        goal_id = str(uuid4())
        today = date.today()

        # 月末を計算
        if today.month == 12:
            period_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            period_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)

        # WHAT回答から目標タイトルを抽出（最初の50文字）
        what_answer = session.get("what_answer", "")
        goal_title = what_answer[:50] if len(what_answer) > 50 else what_answer

        # 数値目標かどうかを判定
        numbers = re.findall(r'[\d,]+(?:万|億|千)?(?:円|件|個|回|%)?', what_answer)
        target_value = None
        unit = None
        goal_type = "action"  # デフォルトは行動目標

        if numbers:
            # 最初の数値を抽出
            num_str = numbers[0]
            # 単位を抽出
            unit_match = re.search(r'(円|件|個|回|%|万|億)$', num_str)
            if unit_match:
                unit = unit_match.group(1)
                num_str = num_str[:-len(unit)]

            # 数値を変換
            try:
                num_str = num_str.replace(",", "")
                target_value = float(num_str)
                if "万" in (unit or ""):
                    target_value *= 10000
                    unit = "円"
                elif "億" in (unit or ""):
                    target_value *= 100000000
                    unit = "円"
                goal_type = "numeric"
            except ValueError:
                pass

        conn.execute(
            text("""
                INSERT INTO goals (
                    id, organization_id, user_id, goal_level, title, description,
                    goal_type, target_value, current_value, unit, deadline,
                    period_type, period_start, period_end, status, classification,
                    created_by, updated_by, created_at, updated_at
                ) VALUES (
                    :id, :org_id, :user_id, 'individual', :title, :description,
                    :goal_type, :target_value, 0, :unit, NULL,
                    'monthly', :period_start, :period_end, 'active', 'internal',
                    :user_id, :user_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """),
            {
                "id": goal_id,
                "org_id": self.org_id,
                "user_id": self.user_id,
                "title": goal_title,
                "description": f"WHY: {session.get('why_answer', '')}\nWHAT: {what_answer}\nHOW: {session.get('how_answer', '')}",
                "goal_type": goal_type,
                "target_value": target_value,
                "unit": unit,
                "period_start": today.replace(day=1),
                "period_end": period_end
            }
        )
        conn.commit()
        return goal_id

    def start_or_continue(self, user_message: str = None) -> Dict[str, Any]:
        """
        目標設定対話を開始または継続

        Args:
            user_message: ユーザーのメッセージ（継続時のみ）

        Returns:
            {"success": bool, "message": str, "session_id": str, "step": str}
        """
        print(f"🎯 GoalSettingDialogue.start_or_continue: room_id={self.room_id}, account_id={self.account_id}")

        with self.pool.connect() as conn:
            # ユーザー情報を取得
            if not self._get_user_info(conn):
                return {
                    "success": False,
                    "message": "🤔 まだソウルくんに登録されていないみたいウル！\n\n管理者に連絡して、ユーザー登録をお願いしてウル🐺"
                }

            if not self.org_id:
                return {
                    "success": False,
                    "message": "🤔 組織情報が設定されていないみたいウル！\n\n管理者に連絡して、組織設定をお願いしてウル🐺"
                }

            # アクティブなセッションを確認
            session = self._get_active_session(conn)

            if session is None:
                # 新規セッション開始（v10.19.4: セッションは最初から 'why' で作成）
                session_id = self._create_session(conn)

                # 導入メッセージを返す（WHY質問を含む）
                intro_message = TEMPLATES["intro"].format(user_name=self.user_name)

                # ログを記録（履歴目的で 'intro' として記録）
                self._log_interaction(
                    conn, session_id, "intro",
                    user_message or "目標を設定したい",
                    intro_message,
                    detected_pattern="ok",
                    result="accepted",
                    step_attempt=1
                )

                # v10.19.4: _update_session() 呼び出しを削除
                # セッションは最初から 'why' で作成されているため、
                # ユーザーの次の返信は WHY 回答として処理される

                return {
                    "success": True,
                    "message": intro_message,
                    "session_id": session_id,
                    "step": "why"  # v10.19.4: intro から why に変更
                }

            # 既存セッションを継続
            return self._process_step(conn, session, user_message)

    def _process_step(self, conn, session: Dict[str, Any], user_message: str) -> Dict[str, Any]:
        """
        現在のステップを処理（v1.7拡張）
        """
        session_id = session["id"]
        current_step = session["current_step"]
        step_attempt = self._get_step_attempt_count(conn, session_id, current_step)

        print(f"   Processing step: {current_step}, attempt: {step_attempt}")

        if not user_message:
            # メッセージがない場合は現在の質問を再表示
            return self._get_current_question(session)

        # v1.7: コンテキスト情報を構築
        context = {
            "retry_count": step_attempt - 1,  # 0-indexed
            "why_answer": session.get("why_answer"),
            "what_answer": session.get("what_answer"),
            "session_id": session_id,
        }

        # パターン検出（v1.7: コンテキスト付き）
        pattern, evaluation = self._detect_pattern(user_message, current_step, context)
        print(f"   Detected pattern: {pattern}, evaluation: {evaluation}")

        # メンタルヘルス懸念の場合は特別処理
        if pattern == "ng_mental_health":
            response = TEMPLATES["ng_mental_health"].format(user_name=self.user_name)
            self._log_interaction(
                conn, session_id, current_step,
                user_message, response,
                detected_pattern=pattern,
                evaluation_result=evaluation,
                feedback_given=True,
                result="abandoned",
                step_attempt=step_attempt
            )
            # セッションを中断
            self._update_session(conn, session_id, current_step=current_step, status="abandoned")
            return {
                "success": True,
                "message": response,
                "session_id": session_id,
                "step": current_step,
                "pattern": pattern
            }

        # NGパターンの場合
        if pattern != "ok":
            # v1.7: help_question/help_confused はリトライ上限に含めない
            is_help_request = pattern.startswith("help_question_") or pattern.startswith("help_confused_")

            # リトライ上限チェック（ヘルプ要求は除く）
            if not is_help_request and step_attempt >= MAX_RETRY_COUNT:
                # 上限に達したら受け入れて次へ進む
                return self._accept_and_proceed(conn, session, user_message, current_step,
                                               pattern, evaluation, step_attempt)

            # フィードバックを返す（v1.7: step, step_attempt追加）
            response = self._get_feedback_response(
                pattern, user_message, session,
                step=current_step,
                step_attempt=step_attempt
            )
            self._log_interaction(
                conn, session_id, current_step,
                user_message, response,
                detected_pattern=pattern,
                evaluation_result=evaluation,
                feedback_given=True,
                result="retry",
                step_attempt=step_attempt
            )
            return {
                "success": True,
                "message": response,
                "session_id": session_id,
                "step": current_step,
                "pattern": pattern
            }

        # OK: 次のステップへ進む
        return self._accept_and_proceed(conn, session, user_message, current_step,
                                       pattern, evaluation, step_attempt)

    def _accept_and_proceed(self, conn, session: Dict[str, Any], user_message: str,
                           current_step: str, pattern: str, evaluation: dict,
                           step_attempt: int) -> Dict[str, Any]:
        """回答を受け入れて次のステップへ進む"""
        session_id = session["id"]

        # 回答を保存
        if current_step == "why":
            self._update_session(conn, session_id, current_step="what", why_answer=user_message)
            next_step = "what"
            feedback = f"「{user_message[:30]}...」という想いを持っているんだね！"
            response = TEMPLATES["why_to_what"].format(
                user_name=self.user_name,
                feedback=feedback
            )
        elif current_step == "what":
            self._update_session(conn, session_id, current_step="how", what_answer=user_message)
            next_step = "how"
            feedback = f"「{user_message[:30]}...」を目指すんだね！"
            response = TEMPLATES["what_to_how"].format(
                user_name=self.user_name,
                feedback=feedback
            )
        elif current_step == "how":
            # 目標登録
            session["why_answer"] = session.get("why_answer", "")
            session["what_answer"] = session.get("what_answer", "")
            session["how_answer"] = user_message

            goal_id = self._register_goal(conn, session)
            self._update_session(
                conn, session_id,
                current_step="complete",
                how_answer=user_message,
                status="completed",
                goal_id=goal_id
            )
            next_step = "complete"
            response = TEMPLATES["complete"].format(
                user_name=self.user_name,
                why_answer=session.get("why_answer", ""),
                what_answer=session.get("what_answer", ""),
                how_answer=user_message
            )
        else:
            # intro ステップはここには来ない（start_or_continue で処理）
            return {
                "success": False,
                "message": "不明なエラーが発生したウル..."
            }

        # ログを記録
        self._log_interaction(
            conn, session_id, current_step,
            user_message, response,
            detected_pattern=pattern,
            evaluation_result=evaluation,
            feedback_given=False,
            result="accepted",
            step_attempt=step_attempt
        )

        return {
            "success": True,
            "message": response,
            "session_id": session_id,
            "step": next_step,
            "pattern": pattern
        }

    def _get_feedback_response(self, pattern: str, user_message: str,
                               session: Dict[str, Any],
                               step: str = None,
                               step_attempt: int = 1) -> str:
        """
        パターンに応じたフィードバックを返す（v1.7拡張）

        Args:
            pattern: 検出されたパターン
            user_message: ユーザーのメッセージ
            session: セッション情報
            step: 現在のステップ
            step_attempt: 試行回数
        """
        # Noneチェック
        why_answer = session.get("why_answer") or ""
        what_answer = session.get("what_answer") or ""
        user_answer = user_message[:50] if user_message else ""

        # v1.7: WHY/WHAT回答のサマリー（help_confused用）
        why_summary = why_answer[:30] + "..." if len(why_answer) > 30 else why_answer
        what_summary = what_answer[:30] + "..." if len(what_answer) > 30 else what_answer

        # v1.7: ステップ別のガイダンス（too_short用）
        step_guidance = self._get_step_guidance(step)
        step_hint = self._get_step_hint(step)

        # =====================================================
        # v1.7: 新しいテンプレートの処理
        # =====================================================

        # 質問対応テンプレート
        if pattern == "help_question_why" and "help_question_why" in TEMPLATES:
            return TEMPLATES["help_question_why"].format(user_name=self.user_name)

        if pattern == "help_question_what" and "help_question_what" in TEMPLATES:
            return TEMPLATES["help_question_what"].format(user_name=self.user_name)

        if pattern == "help_question_how" and "help_question_how" in TEMPLATES:
            return TEMPLATES["help_question_how"].format(user_name=self.user_name)

        # 困惑対応テンプレート
        if pattern == "help_confused_why" and "help_confused_why" in TEMPLATES:
            return TEMPLATES["help_confused_why"].format(user_name=self.user_name)

        if pattern == "help_confused_what" and "help_confused_what" in TEMPLATES:
            return TEMPLATES["help_confused_what"].format(
                user_name=self.user_name,
                why_summary=why_summary
            )

        if pattern == "help_confused_how" and "help_confused_how" in TEMPLATES:
            return TEMPLATES["help_confused_how"].format(
                user_name=self.user_name,
                what_summary=what_summary
            )

        # 極端に短い回答
        if pattern == "too_short" and "too_short" in TEMPLATES:
            return TEMPLATES["too_short"].format(
                user_name=self.user_name,
                user_answer=user_answer,
                step_guidance=step_guidance
            )

        # v1.7: リトライ回数に応じたトーン変更
        if step_attempt >= 3 and "retry_accepting" in TEMPLATES:
            # 3回目以降は受け入れ準備
            return TEMPLATES["retry_accepting"].format(
                user_name=self.user_name,
                user_answer=user_answer
            )

        if step_attempt == 2 and "retry_gentle" in TEMPLATES:
            # 2回目は優しいトーン
            return TEMPLATES["retry_gentle"].format(
                user_name=self.user_name,
                step_hint=step_hint
            )

        # =====================================================
        # 既存テンプレートの処理
        # =====================================================
        if pattern in TEMPLATES:
            return TEMPLATES[pattern].format(
                user_name=self.user_name,
                user_answer=user_answer,
                what_answer=what_answer[:50]
            )

        # デフォルトのフィードバック
        return TEMPLATES["ng_abstract"].format(
            user_name=self.user_name,
            user_answer=user_answer
        )

    def _get_step_guidance(self, step: str) -> str:
        """ステップ別のガイダンスを返す（v1.7新規）"""
        guidance = {
            "why": "仕事を通じて、どんな自分になりたいか教えてほしいウル🐺",
            "what": "具体的に何を達成したいか、数字や期限を入れて教えてほしいウル🐺",
            "how": "毎日・毎週どんな行動をするか教えてほしいウル🐺",
        }
        return guidance.get(step, "もう少し詳しく教えてほしいウル🐺")

    def _get_step_hint(self, step: str) -> str:
        """ステップ別のヒントを返す（v1.7新規）"""
        hints = {
            "why": """例えば...
• 「チームに貢献できる人になりたい」
• 「お客様に喜んでもらえる仕事がしたい」
• 「成長して新しいことにチャレンジしたい」""",
            "what": """例えば...
• 「今月の売上を〇〇円にしたい」
• 「新規顧客を〇件獲得したい」
• 「〇月までにプロジェクトを完了させたい」""",
            "how": """例えば...
• 「毎日〇〇をする」
• 「週に〇回△△をする」
• 「毎朝/毎晩〇〇を続ける」""",
        }
        return hints.get(step, "具体的に教えてほしいウル🐺")

    def _get_current_question(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """現在のステップの質問を返す"""
        current_step = session["current_step"]

        if current_step == "why":
            return {
                "success": True,
                "message": "❓ 【WHY】この先、仕事を通じてどんな自分になりたいですか？\n\n" +
                          f"{self.user_name}さんの想いを教えてウル🐺✨",
                "session_id": session["id"],
                "step": current_step
            }
        elif current_step == "what":
            return {
                "success": True,
                "message": "❓ 【WHAT】具体的にどんな成果を出したいですか？\n\n" +
                          "数字や期限を入れてくれると嬉しいウル🐺",
                "session_id": session["id"],
                "step": current_step
            }
        elif current_step == "how":
            return {
                "success": True,
                "message": "❓ 【HOW】目標達成のために、どんな行動をしますか？\n\n" +
                          "「毎日〇〇をする」など具体的に教えてウル🐺",
                "session_id": session["id"],
                "step": current_step
            }
        else:
            return {
                "success": True,
                "message": "目標設定が完了しているウル！\n新しい目標を設定するなら「目標を設定したい」と言ってウル🐺",
                "session_id": session["id"],
                "step": current_step
            }


def has_active_goal_session(pool, room_id: str, account_id: str) -> bool:
    """
    アクティブな目標設定セッションが存在するかチェック

    chatwork-webhook から呼び出して、通常のAI応答をバイパスするかどうか判定する。
    """
    with pool.connect() as conn:
        # ユーザー情報を取得
        user_result = conn.execute(
            text("""
                SELECT id, organization_id FROM users
                WHERE chatwork_account_id = :account_id
                LIMIT 1
            """),
            {"account_id": str(account_id)}
        ).fetchone()

        if not user_result:
            return False

        user_id = str(user_result[0])
        org_id = str(user_result[1]) if user_result[1] else None

        if not org_id:
            return False

        # アクティブなセッションをチェック
        result = conn.execute(
            text("""
                SELECT COUNT(*) FROM goal_setting_sessions
                WHERE user_id = :user_id
                  AND organization_id = :org_id
                  AND chatwork_room_id = :room_id
                  AND status = 'in_progress'
                  AND expires_at > CURRENT_TIMESTAMP
            """),
            {
                "user_id": user_id,
                "org_id": org_id,
                "room_id": str(room_id)
            }
        ).fetchone()

        return result and result[0] > 0


def process_goal_setting_message(pool, room_id: str, account_id: str,
                                  message: str) -> Dict[str, Any]:
    """
    目標設定対話を処理

    アクティブなセッションがある場合はそのセッションを継続、
    なければ新規セッションを開始。
    """
    dialogue = GoalSettingDialogue(pool, room_id, account_id)
    return dialogue.start_or_continue(message)
