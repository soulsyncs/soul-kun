"""
目標設定対話フロー - メインクラス

GoalSettingDialogue クラスおよびヘルパー関数を提供。
"""

from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional, Dict, Any, List, Tuple
from uuid import uuid4
from sqlalchemy import text
import json
import logging
import re
import httpx

from .constants import (
    OPENROUTER_API_KEY,
    LLM_MODEL,
    LLM_TIMEOUT,
    LONG_RESPONSE_THRESHOLD,
    FRUSTRATION_PATTERNS,
    CONFIRMATION_PATTERNS,
    TEMPLATES,
    PATTERN_KEYWORDS,
    LENGTH_THRESHOLDS,
    STEP_EXPECTED_KEYWORDS,
    STEPS,
    STEP_ORDER,
    MAX_RETRY_COUNT,
)
from .detectors import (
    _wants_restart,
    _has_but_connector,
    _has_feedback_request,
    _has_doubt_or_anxiety,
    _is_pure_confirmation,
    _infer_fulfilled_phases,
    _get_next_unfulfilled_step,
)

logger = logging.getLogger(__name__)


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

        # Phase 2.5 + B Memory統合
        self.enriched_context = None
        self.pattern_analyzer = None

    def _get_user_info(self, conn) -> bool:
        """ユーザー情報を取得（v10.29.8: 文字列変換対応）"""
        result = conn.execute(
            text("""
                SELECT id, organization_id, name FROM users
                WHERE chatwork_account_id = :account_id
                LIMIT 1
            """),
            {"account_id": str(self.account_id)}
        ).fetchone()

        if not result:
            return False

        self.user_id = str(result[0])
        self.org_id = str(result[1]) if result[1] else None
        self.user_name = result[2] or "ユーザー"
        return True

    def _detect_frustration(self, message: str) -> bool:
        """ユーザーの不満を検出（「答えたじゃん」等）"""
        message_lower = message.lower()
        for pattern in FRUSTRATION_PATTERNS:
            if pattern in message_lower:
                return True
        return False

    def _extract_themes_from_message(self, message: str) -> Optional[str]:
        """
        v10.40.3: メッセージからテーマ・領域を抽出

        「SNS発信とAI開発と組織化」のような複数テーマを
        「SNS発信、AI開発、組織化」の形式で返す。

        Args:
            message: ユーザーメッセージ

        Returns:
            抽出されたテーマ（カンマ区切り）またはNone
        """
        # 「〜と〜と〜」パターンを検出
        import re

        # パターン1: 「AとBとC」形式
        pattern1 = r'([^。、]+?)と([^。、]+?)と([^。、]+?)(?:に|を|の|で|は|が)'
        match = re.search(pattern1, message)
        if match:
            return f"{match.group(1).strip()}、{match.group(2).strip()}、{match.group(3).strip()}"

        # パターン2: 「A・B・C」形式
        pattern2 = r'([^。、]+?)・([^。、]+?)・([^。、]+?)(?:に|を|の|で|は|が)'
        match = re.search(pattern2, message)
        if match:
            return f"{match.group(1).strip()}、{match.group(2).strip()}、{match.group(3).strip()}"

        # パターン3: 「A、B、C」形式
        pattern3 = r'([^。]+?)、([^。]+?)、([^。]+?)(?:に|を|の|で|は|が)'
        match = re.search(pattern3, message)
        if match:
            return f"{match.group(1).strip()}、{match.group(2).strip()}、{match.group(3).strip()}"

        # パターン4: 「AとB」形式（2つ）
        pattern4 = r'([^。、]+?)と([^。、]+?)(?:に|を|の|で|は|が)'
        match = re.search(pattern4, message)
        if match:
            return f"{match.group(1).strip()}、{match.group(2).strip()}"

        # テーマっぽいキーワードがあれば抽出
        theme_keywords = [
            "発信", "開発", "組織", "営業", "マーケ", "採用",
            "教育", "研修", "企画", "設計", "分析", "改善",
        ]
        found_themes = []
        for kw in theme_keywords:
            if kw in message:
                # キーワードを含む文節を抽出
                idx = message.find(kw)
                start = max(0, idx - 5)
                end = min(len(message), idx + len(kw) + 5)
                snippet = message[start:end].strip()
                # 重複チェック
                if snippet not in found_themes and len(snippet) < 20:
                    found_themes.append(snippet)

        if found_themes:
            return "、".join(found_themes[:3])  # 最大3つ

        return None

    def _analyze_long_response_with_llm(self, message: str, session: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        長文の回答をLLMで解析してWHY/WHAT/HOWを抽出

        Returns:
            {"why": "...", "what": "...", "how": "..."} or None
        """
        if len(message) < LONG_RESPONSE_THRESHOLD:
            return None

        if not OPENROUTER_API_KEY:
            logger.warning("OPENROUTER_API_KEY未設定のためLLM解析をスキップ")
            return None

        # 既に回答済みの部分を考慮
        existing_why = session.get("why_answer", "")
        existing_what = session.get("what_answer", "")
        existing_how = session.get("how_answer", "")

        prompt = f"""以下のユーザーの回答から、目標設定の3要素を抽出してください。

【ユーザーの回答】
{message}

【既に回答済みの内容】
- WHY（なぜ・動機）: {existing_why or '未回答'}
- WHAT（何を・目標）: {existing_what or '未回答'}
- HOW（どうやって・行動）: {existing_how or '未回答'}

【抽出ルール】
1. WHY: なぜその目標を達成したいのか（動機、ビジョン、想い）
2. WHAT: 具体的に何を達成したいのか（数値目標、成果、ゴール）
3. HOW: どんな行動で達成するのか（具体的なアクション、習慣）

【出力形式】JSON形式で出力してください。該当する内容がない場合は空文字を設定してください。
{{"why": "抽出した内容", "what": "抽出した内容", "how": "抽出した内容"}}"""

        try:
            with httpx.Client(timeout=LLM_TIMEOUT) as client:
                response = client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": LLM_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                    }
                )
                response.raise_for_status()
                result = response.json()
                content = result["choices"][0]["message"]["content"]

                # JSONを抽出
                json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
                if json_match:
                    extracted = json.loads(json_match.group())
                    logger.info("LLM解析結果: %s", extracted)
                    return extracted

        except Exception as e:
            logger.error("LLM解析エラー: %s", e)

        return None

    def _generate_understanding_response(self, extracted: Dict[str, str], session: Dict[str, Any]) -> str:
        """抽出した内容を元に、理解を示す応答を生成"""
        why = extracted.get("why", "") or session.get("why_answer", "")
        what = extracted.get("what", "") or session.get("what_answer", "")
        how = extracted.get("how", "") or session.get("how_answer", "")

        response = f"""🐺 {self.user_name}さん、熱い想いを聞かせてくれてありがとうウル！

ソウルくんなりに整理してみたウル：

━━━━━━━━━━━━━━━━━━
🔥 【WHY - {self.user_name}さんの想い】
{why if why else '（まだ聞けていないウル）'}

🎯 【WHAT - 目指すゴール】
{what if what else '（まだ聞けていないウル）'}

💪 【HOW - 具体的な行動】
{how if how else '（まだ聞けていないウル）'}
━━━━━━━━━━━━━━━━━━

"""

        # 足りない部分を確認
        missing = []
        if not why:
            missing.append("WHY（なぜそれを目指すのか）")
        if not what:
            missing.append("WHAT（具体的な数値目標）")
        if not how:
            missing.append("HOW（毎日・毎週の行動）")

        if missing:
            response += f"もう少し教えてほしいのは：\n"
            for m in missing:
                response += f"  ❓ {m}\n"
            response += f"\nこの部分を教えてくれたら、目標として登録できるウル🐺✨"
        else:
            response += "この理解で合ってるかな？\n\n「OK」と言ってくれたら目標として登録するウル！\n修正があれば教えてウル🐺✨"

        return response

    def _generate_quality_check_response(
        self,
        session: Dict[str, Any],
        user_message: str,
        pattern_type: str
    ) -> str:
        """
        v10.40.2: 導きの対話（目標の質チェック）応答を生成

        設計書に基づき、心理的安全性を確保しつつ目標の質を高める質問を生成。
        - WHY: 内発的動機（誰が喜ぶ/どんな自分でいたい/何を大事にしたい）
        - WHAT: 測定可能（数字/期限/定義が曖昧なら具体化）
        - HOW: 行動（頻度/量/最初の一歩/今週やること）
        - 障害: 想定される障害と対策を1つだけ問う

        NG厳守: ジャッジではなく改善、詰問禁止
        """
        why = session.get("why_answer", "")
        what = session.get("what_answer", "")
        how = session.get("how_answer", "")

        # 目標の質を評価し、質問を生成
        quality_issues = []
        quality_questions = []

        # WHYの評価：内発的動機が見えるか
        if why:
            # 外発的動機のパターン
            external_patterns = ["言われた", "やらなきゃ", "しなければ", "義務", "命令", "指示"]
            is_external = any(p in why for p in external_patterns)
            # 内発的動機のパターン
            internal_patterns = ["したい", "なりたい", "実現", "大切", "大事", "喜ぶ", "幸せ"]
            has_internal = any(p in why for p in internal_patterns)

            if is_external and not has_internal:
                quality_issues.append("WHYに外発的動機が見える")
                quality_questions.append(
                    "💭 この目標を達成したら、誰が喜ぶウル？そして{user_name}さん自身はどんな気持ちになるウル？"
                )
            elif not has_internal and len(why) < 30:
                quality_issues.append("WHYが短い・内発的動機が薄い")
                quality_questions.append(
                    "💭 もう少し聞かせてウル。この目標を通じて、どんな自分になりたいウル？"
                )

        # WHATの評価：測定可能か
        if what:
            # 数値・期限のパターン
            has_number = any(c.isdigit() for c in what)
            date_patterns = ["月", "日", "週", "年", "まで", "期限", "締切"]
            has_date = any(p in what for p in date_patterns)

            if not has_number and not has_date:
                quality_issues.append("WHATに数値・期限がない")
                if len(quality_questions) < 2:
                    quality_questions.append(
                        "🎯 いつまでに、どのくらい達成できたら「やった！」と言えるウル？"
                    )

        # HOWの評価：具体的な行動か
        if how:
            action_patterns = ["毎日", "毎週", "回", "時間", "分", "件"]
            has_frequency = any(p in how for p in action_patterns)

            if not has_frequency:
                quality_issues.append("HOWに頻度・量がない")
                if len(quality_questions) < 2:
                    quality_questions.append(
                        "💪 最初の一歩として、今週は何をするウル？具体的に決めておくと動きやすいウル"
                    )

        # 障害の質問（質問が1つ以下の場合のみ）
        if len(quality_questions) < 2:
            quality_questions.append(
                "🤔 この目標を達成する上で、一番の壁になりそうなことは何ウル？"
            )

        # 質問を最大2つに制限
        quality_questions = quality_questions[:2]

        # 心理的安全性を確保したフィードバック
        if pattern_type == "feedback_request":
            quality_feedback = f"""確認してくれてありがとうウル🐺
目標設定に「正解」はないウル。大切なのは{self.user_name}さん自身が「これでいく！」と思えること。

ただ、達成確率を上げるために、ソウルくんからいくつか確認させてウル。"""
        else:  # doubt_anxiety
            quality_feedback = f"""迷いがあるの、すごくわかるウル🐺
目標って、最初から完璧じゃなくていいウル。走りながら調整していけばOK。

でもせっかくなので、もう少しだけ一緒に考えさせてウル。"""

        # 質問テキストを生成
        questions_text = ""
        for i, q in enumerate(quality_questions, 1):
            questions_text += f"❓ 質問{i}: {q.format(user_name=self.user_name)}\n"

        response = TEMPLATES["quality_check"].format(
            user_name=self.user_name,
            quality_feedback=quality_feedback,
            quality_questions=questions_text.strip()
        )

        return response

    def _get_active_session(self, conn) -> Optional[Dict[str, Any]]:
        """
        アクティブなセッションを取得（v1.8: brain_conversation_states使用）

        brain_conversation_states から state_type='goal_setting' のセッションを検索。
        user_id は ChatWork account_id を使用。
        """
        result = conn.execute(
            text("""
                SELECT id, state_step, state_data, created_at, expires_at
                FROM brain_conversation_states
                WHERE user_id = :account_id
                  AND organization_id = :org_id
                  AND room_id = :room_id
                  AND state_type = 'goal_setting'
                  AND expires_at > CURRENT_TIMESTAMP
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {
                "account_id": self.account_id,
                "org_id": self.org_id,
                "room_id": self.room_id
            }
        ).fetchone()

        if not result:
            return None

        # state_data から WHY/WHAT/HOW 回答を取得
        state_data = result[2] or {}

        return {
            "id": str(result[0]),
            "current_step": result[1] or "why",
            "why_answer": state_data.get("why_answer"),
            "what_answer": state_data.get("what_answer"),
            "how_answer": state_data.get("how_answer"),
            "started_at": result[3],
            "expires_at": result[4]
        }

    def _create_session(self, conn) -> str:
        """
        新規セッションを作成（v1.8: brain_conversation_states使用）

        v10.19.4: セッションは最初から 'why' ステップで作成する。
        'intro' は論理的なステップとしては存在せず、イントロメッセージ送信後は
        すぐに WHY ステップに入る。これにより、ユーザーの最初の返信が
        必ず WHY 回答として処理される。

        v1.8: brain_conversation_states に状態を作成。
        user_id には ChatWork account_id を使用。
        """
        # v10.40.4: UPSERT修正 - 既存セッションの回答を保護
        # INSERT時のみ state_step='why', state_data='{}' を設定
        # UPDATE時は expires_at と updated_at のみ更新（回答を上書きしない）
        result = conn.execute(
            text("""
                INSERT INTO brain_conversation_states (
                    organization_id, room_id, user_id,
                    state_type, state_step, state_data,
                    expires_at, timeout_minutes,
                    created_at, updated_at
                ) VALUES (
                    :org_id, :room_id, :account_id,
                    'goal_setting', 'why', '{}',
                    CURRENT_TIMESTAMP + INTERVAL '24 hours', 1440,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                ON CONFLICT (organization_id, room_id, user_id)
                DO UPDATE SET
                    expires_at = CURRENT_TIMESTAMP + INTERVAL '24 hours',
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            """),
            {
                "org_id": self.org_id,
                "room_id": self.room_id,
                "account_id": self.account_id
            }
        )
        row = result.fetchone()
        session_id = str(row[0]) if row else str(uuid4())
        conn.commit()
        return session_id

    def _clear_session(self, conn, session_id: str) -> None:
        """
        セッションをクリア（v10.40.3: リスタート用）

        明示的なリスタート要求時に使用。
        brain_conversation_states から削除してセッションを終了。
        """
        conn.execute(
            text("""
                DELETE FROM brain_conversation_states
                WHERE id = :session_id
            """),
            {"session_id": session_id}
        )
        conn.commit()
        logger.info("Session cleared: %s", session_id)

    def _update_session(self, conn, session_id: str,
                       current_step: str = None,
                       why_answer: str = None,
                       what_answer: str = None,
                       how_answer: str = None,
                       status: str = None,
                       goal_id: str = None) -> None:
        """
        セッションを更新（v1.8: brain_conversation_states使用）

        state_data JSONBに WHY/WHAT/HOW 回答を格納。
        status='completed' の場合は状態をクリア（DELETEではなくstate_type更新）。
        """
        # まず現在のstate_dataを取得
        current = conn.execute(
            text("""
                SELECT state_data FROM brain_conversation_states
                WHERE id = :session_id
            """),
            {"session_id": session_id}
        ).fetchone()

        current_data = (current[0] if current and current[0] else {}) or {}

        # state_dataを更新
        if why_answer is not None:
            current_data["why_answer"] = why_answer
        if what_answer is not None:
            current_data["what_answer"] = what_answer
        if how_answer is not None:
            current_data["how_answer"] = how_answer
        if goal_id is not None:
            current_data["goal_id"] = goal_id

        # 更新クエリを構築
        updates = ["updated_at = CURRENT_TIMESTAMP"]
        params = {"session_id": session_id, "state_data": json.dumps(current_data)}

        # v10.40.7: status='completed' の場合は state_step を NULL に設定するため、
        # current_step の設定をスキップ（二重設定によるSQL文法エラー防止）
        if status == "completed":
            updates.append("state_type = 'normal'")
            updates.append("state_step = NULL")
            current_data["completed_at"] = datetime.utcnow().isoformat()
            params["state_data"] = json.dumps(current_data)
        elif current_step is not None:
            updates.append("state_step = :current_step")
            params["current_step"] = current_step

        updates.append("state_data = CAST(:state_data AS jsonb)")

        # タイムアウト延長
        updates.append("expires_at = CURRENT_TIMESTAMP + INTERVAL '24 hours'")

        conn.execute(
            text(f"UPDATE brain_conversation_states SET {', '.join(updates)} WHERE id = :session_id"),
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
        """
        対話ログを記録（v1.8: brain_dialogue_logs使用）

        全対話フローのログを統一管理するbrain_dialogue_logsに記録。
        chatwork_account_id を使用。
        """
        log_id = str(uuid4())
        conn.execute(
            text("""
                INSERT INTO brain_dialogue_logs (
                    id, organization_id, chatwork_account_id, room_id,
                    state_type, state_step, step_attempt,
                    user_message, ai_response,
                    detected_pattern, evaluation_result, feedback_given, result
                ) VALUES (
                    :id, :org_id, :account_id, :room_id,
                    'goal_setting', :step, :step_attempt,
                    :user_message, :ai_response,
                    :detected_pattern, :evaluation_result, :feedback_given, :result
                )
            """),
            {
                "id": log_id,
                "org_id": self.org_id,
                "account_id": self.account_id,
                "room_id": self.room_id,
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
        """
        現在のステップの試行回数を取得（v1.8: brain_dialogue_logs使用）

        chatwork_account_idとroom_idで検索。session_idは使用しない。
        """
        result = conn.execute(
            text("""
                SELECT COUNT(*) FROM brain_dialogue_logs
                WHERE chatwork_account_id = :account_id
                  AND room_id = :room_id
                  AND organization_id = :org_id
                  AND state_type = 'goal_setting'
                  AND state_step = :step
                  AND created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
            """),
            {
                "account_id": self.account_id,
                "room_id": self.room_id,
                "org_id": self.org_id,
                "step": step
            }
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
        logger.info("GoalSettingDialogue.start_or_continue: room_id=%s, account_id=%s", self.room_id, self.account_id)

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

            # Phase 2.5 + B Memory統合: コンテキストをロード
            self._load_memory_context(conn)

            # アクティブなセッションを確認
            session = self._get_active_session(conn)

            # v10.40.3: 明示的リスタート要求のチェック
            # 既存セッションがあっても、「やり直したい」等の場合はリセット
            if session is not None and user_message and _wants_restart(user_message):
                logger.info("Restart requested: clearing existing session %s", session['id'])
                self._clear_session(conn, session["id"])
                session = None  # 新規セッション開始へ

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

        logger.debug("Processing step: %s, attempt: %s", current_step, step_attempt)

        if not user_message:
            # メッセージがない場合は現在の質問を再表示
            return self._get_current_question(session)

        # v10.22.1: 終了コマンドのチェック（最優先）
        for exit_keyword in PATTERN_KEYWORDS["exit"]:
            if exit_keyword in user_message:
                logger.debug("Exit keyword detected: %s", exit_keyword)
                response = TEMPLATES["exit"].format(user_name=self.user_name)
                self._log_interaction(
                    conn, session_id, current_step,
                    user_message, response,
                    detected_pattern="exit",
                    result="abandoned",  # DB constraint: accepted, retry, abandoned
                    step_attempt=step_attempt
                )
                # セッションを終了（DB constraint: in_progress, completed, abandoned）
                self._update_session(conn, session_id, current_step=current_step, status="abandoned")
                return {
                    "success": True,
                    "message": response,
                    "session_id": session_id,
                    "step": current_step,
                    "pattern": "exit"
                }

        # =====================================================
        # v10.31.5: 確認ステップの処理（LLM抽出後）
        # =====================================================
        if current_step == "confirm":
            logger.debug("確認ステップ: ユーザー応答受信（%d文字）", len(user_message))

            # OKパターンをチェック（v10.40.1: 純粋な確認のみ受け付ける）
            # 「合ってるけど、フィードバックして」のような否定接続やFB要求は確認とみなさない
            is_confirmed = _is_pure_confirmation(user_message)

            if is_confirmed:
                logger.info("確認OK - 目標を登録します")
                # セッションから保存済みの回答を取得
                why_answer = session.get("why_answer", "")
                what_answer = session.get("what_answer", "")
                how_answer = session.get("how_answer", "")

                # 目標登録
                goal_id = self._register_goal(conn, session)
                self._update_session(
                    conn, session_id,
                    current_step="complete",
                    status="completed",
                    goal_id=goal_id
                )

                response = TEMPLATES["complete"].format(
                    user_name=self.user_name,
                    why_answer=why_answer,
                    what_answer=what_answer,
                    how_answer=how_answer
                )

                self._log_interaction(
                    conn, session_id, "confirm",
                    user_message, response,
                    detected_pattern="confirmed",
                    result="accepted",
                    step_attempt=step_attempt
                )

                # Phase 2.5 + B Memory統合: セッション完了時の学習
                self._update_session_stats_on_complete(conn, session)

                return {
                    "success": True,
                    "message": response,
                    "session_id": session_id,
                    "step": "complete",
                    "pattern": "confirmed"
                }
            else:
                # v10.40.2: フィードバック要求/迷い・不安の場合は「導きの対話」へ
                is_feedback_request = _has_feedback_request(user_message)
                is_doubt_anxiety = _has_doubt_or_anxiety(user_message)

                if is_feedback_request or is_doubt_anxiety:
                    # 導きの対話（目標の質チェック）
                    pattern_type = "feedback_request" if is_feedback_request else "doubt_anxiety"
                    logger.debug("導きの対話へ: %s", pattern_type)

                    response = self._generate_quality_check_response(
                        session, user_message, pattern_type
                    )

                    self._log_interaction(
                        conn, session_id, "confirm",
                        user_message, response,
                        detected_pattern=pattern_type,
                        result="quality_check",
                        step_attempt=step_attempt
                    )

                    return {
                        "success": True,
                        "message": response,
                        "session_id": session_id,
                        "step": "confirm",
                        "pattern": pattern_type
                    }

                # =====================================================
                # v10.40.6: confirm無限ループ完全防止パッチ
                # =====================================================
                # ルール:
                # - 長文 かつ LLM抽出成功 かつ 有効な修正あり → 要約更新
                # - それ以外は全て → 導きの対話へフォールバック
                # - 「同じ要約を再表示」は絶対にしない
                # =====================================================

                logger.debug("入力を分析中...")

                # 長文の場合のみLLMで修正解析を試みる
                if len(user_message) >= LONG_RESPONSE_THRESHOLD:
                    extracted = self._analyze_long_response_with_llm(user_message, session)

                    # 有効な修正が抽出できた場合のみ要約を更新
                    has_valid_updates = (
                        extracted and
                        (extracted.get("why") or extracted.get("what") or extracted.get("how"))
                    )

                    if has_valid_updates:
                        # 修正内容を更新
                        updates = {}
                        if extracted.get("why"):
                            updates["why_answer"] = extracted["why"]
                            session["why_answer"] = extracted["why"]
                        if extracted.get("what"):
                            updates["what_answer"] = extracted["what"]
                            session["what_answer"] = extracted["what"]
                        if extracted.get("how"):
                            updates["how_answer"] = extracted["how"]
                            session["how_answer"] = extracted["how"]

                        self._update_session(conn, session_id, **updates)

                        # 修正後の内容で再確認
                        response = self._generate_understanding_response(
                            {"why": session.get("why_answer", ""),
                             "what": session.get("what_answer", ""),
                             "how": session.get("how_answer", "")},
                            session
                        )

                        self._log_interaction(
                            conn, session_id, "confirm",
                            user_message, response,
                            detected_pattern="modification_request",
                            result="retry",
                            step_attempt=step_attempt
                        )

                        return {
                            "success": True,
                            "message": response,
                            "session_id": session_id,
                            "step": "confirm",
                            "pattern": "modification_request"
                        }

                # =====================================================
                # フォールバック: 導きの対話（無限ループ防止の安全パッチ）
                # =====================================================
                # ここに到達するケース:
                # - 短文だった（LLM解析スキップ）
                # - LLM解析が失敗した（None返却）
                # - LLM解析は成功したが有効な修正が抽出できなかった
                #
                # 重要: 同じ要約を再表示せず、目標の質を確認する対話へ
                # =====================================================
                logger.debug("導きの対話へフォールバック（無限ループ防止）")
                response = self._generate_quality_check_response(
                    session, user_message, "clarification_needed"
                )

                self._log_interaction(
                    conn, session_id, "confirm",
                    user_message, response,
                    detected_pattern="clarification_fallback",
                    result="quality_check",
                    step_attempt=step_attempt
                )

                return {
                    "success": True,
                    "message": response,
                    "session_id": session_id,
                    "step": "confirm",
                    "pattern": "clarification_fallback"
                }

        # =====================================================
        # v10.31.5: 不満検出（「答えたじゃん」等）
        # =====================================================
        if self._detect_frustration(user_message):
            logger.info("不満を検出（%d文字）", len(user_message))
            # 今までの回答を要約して確認
            extracted = {
                "why": session.get("why_answer", ""),
                "what": session.get("what_answer", ""),
                "how": session.get("how_answer", "")
            }
            response = f"""🙏 ごめんなさいウル！ちゃんと聞けてなかったウル...

{self.user_name}さんが教えてくれた内容をもう一度整理させてウル：

━━━━━━━━━━━━━━━━━━
🔥 【WHY】{extracted['why'][:100] if extracted['why'] else '（まだ聞けていないウル）'}
🎯 【WHAT】{extracted['what'][:100] if extracted['what'] else '（まだ聞けていないウル）'}
💪 【HOW】{extracted['how'][:100] if extracted['how'] else '（まだ聞けていないウル）'}
━━━━━━━━━━━━━━━━━━

さっきの内容で足りない部分があれば、もう一度教えてほしいウル。
この理解で合ってたら「OK」と言ってウル🐺✨"""

            self._log_interaction(
                conn, session_id, current_step,
                user_message, response,
                detected_pattern="frustration_detected",
                result="retry",
                step_attempt=step_attempt
            )
            return {
                "success": True,
                "message": response,
                "session_id": session_id,
                "step": current_step,
                "pattern": "frustration_detected"
            }

        # =====================================================
        # v10.31.5: 長文の場合はLLMで解析してWHY/WHAT/HOWを抽出
        # =====================================================
        if len(user_message) >= LONG_RESPONSE_THRESHOLD:
            logger.debug("長文を検出（%d文字）- LLM解析を実行", len(user_message))
            extracted = self._analyze_long_response_with_llm(user_message, session)

            if extracted:
                # 抽出した内容をセッションに保存
                updates = {}
                if extracted.get("why") and not session.get("why_answer"):
                    updates["why_answer"] = extracted["why"]
                    session["why_answer"] = extracted["why"]
                if extracted.get("what") and not session.get("what_answer"):
                    updates["what_answer"] = extracted["what"]
                    session["what_answer"] = extracted["what"]
                if extracted.get("how") and not session.get("how_answer"):
                    updates["how_answer"] = extracted["how"]
                    session["how_answer"] = extracted["how"]

                if updates:
                    # セッションを更新
                    self._update_session(conn, session_id, **updates)

                # すべて揃ったか確認
                has_why = bool(session.get("why_answer"))
                has_what = bool(session.get("what_answer"))
                has_how = bool(session.get("how_answer"))

                if has_why and has_what and has_how:
                    # すべて揃ったら確認画面へ
                    response = self._generate_understanding_response(extracted, session)
                    # v10.31.5: current_stepを'confirm'に更新
                    self._update_session(conn, session_id, current_step="confirm")

                    self._log_interaction(
                        conn, session_id, "llm_analysis",
                        user_message, response,
                        detected_pattern="llm_extracted_all",
                        result="retry",  # DB constraint: accepted, retry, abandoned
                        step_attempt=step_attempt
                    )
                    return {
                        "success": True,
                        "message": response,
                        "session_id": session_id,
                        "step": "confirm",
                        "pattern": "llm_extracted_all"
                    }
                else:
                    # 足りない部分がある場合は、理解を示しつつ足りない部分を聞く
                    response = self._generate_understanding_response(extracted, session)

                    # 次のステップを決定
                    if not has_why:
                        next_step = "why"
                    elif not has_what:
                        next_step = "what"
                    else:
                        next_step = "how"

                    self._update_session(conn, session_id, current_step=next_step)

                    self._log_interaction(
                        conn, session_id, "llm_analysis",
                        user_message, response,
                        detected_pattern="llm_extracted_partial",
                        result="retry",  # DB constraint: accepted, retry, abandoned
                        step_attempt=step_attempt
                    )
                    return {
                        "success": True,
                        "message": response,
                        "session_id": session_id,
                        "step": next_step,
                        "pattern": "llm_extracted_partial"
                    }

        # v1.7: コンテキスト情報を構築
        context = {
            "retry_count": step_attempt - 1,  # 0-indexed
            "why_answer": session.get("why_answer"),
            "what_answer": session.get("what_answer"),
            "session_id": session_id,
        }

        # パターン検出（v1.7: コンテキスト付き）
        pattern, evaluation = self._detect_pattern(user_message, current_step, context)
        logger.debug("Detected pattern: %s, evaluation: %s", pattern, evaluation)

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

            # Phase 2.5 + B Memory統合: パターンから学習
            specificity_score = evaluation.get("specificity_score", 0.0) if evaluation else 0.0
            self._learn_from_interaction(
                conn, session, current_step, pattern,
                was_accepted=False,
                retry_count=step_attempt,
                specificity_score=specificity_score
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
        """
        回答を受け入れて次のステップへ進む

        v10.40.3: フェーズ自動判定
        ユーザーの回答から複数フェーズの情報を検出し、
        既に充足しているフェーズはスキップする。
        """
        session_id = session["id"]

        # v10.40.3: フェーズ自動判定
        fulfilled = _infer_fulfilled_phases(user_message)
        logger.debug("フェーズ判定: %s", fulfilled)

        # 回答を保存（現在のステップ + 追加で検出されたフェーズ）
        if current_step == "why":
            # WHY回答を保存
            session["why_answer"] = user_message

            # v10.40.3: WHAT/HOW情報も含まれていれば抽出
            updates = {"why_answer": user_message}
            if fulfilled.get("what"):
                # WHATレベルの情報（テーマ・目標）が含まれている
                logger.debug("WHAT情報も検出: テーマ・領域を含む")
                # テーマを抽出してセッションに保存（次の質問で使う）
                session["detected_themes"] = user_message

            # 次のステップを決定
            next_step = _get_next_unfulfilled_step(fulfilled, current_step, session)

            if next_step == "what" and fulfilled.get("what"):
                # テーマは分かっているが具体的な数値がない場合
                # スマート質問を使用
                themes = self._extract_themes_from_message(user_message)
                if themes:
                    response = TEMPLATES["smart_what_with_themes"].format(
                        user_name=self.user_name,
                        themes=themes,
                        theme_example=themes.split("、")[0] if "、" in themes else themes
                    )
                else:
                    feedback = f"「{user_message[:30]}...」という想いを持っているんだね！"
                    response = TEMPLATES["why_to_what"].format(
                        user_name=self.user_name,
                        feedback=feedback
                    )
            elif next_step == "how":
                # WHATもスキップしてHOWへ
                feedback = f"「{user_message[:30]}...」を目指すんだね！"
                response = TEMPLATES["what_to_how"].format(
                    user_name=self.user_name,
                    feedback=feedback
                )
            elif next_step == "confirm":
                # 全て揃った（稀なケース）
                response = self._generate_understanding_response(
                    {"why": user_message, "what": "", "how": ""},
                    session
                )
            else:
                feedback = f"「{user_message[:30]}...」という想いを持っているんだね！"
                response = TEMPLATES["why_to_what"].format(
                    user_name=self.user_name,
                    feedback=feedback
                )

            self._update_session(conn, session_id, current_step=next_step, **updates)

        elif current_step == "what":
            session["what_answer"] = user_message
            updates = {"what_answer": user_message}

            # 次のステップを決定
            next_step = _get_next_unfulfilled_step(fulfilled, current_step, session)

            if next_step == "how" and fulfilled.get("how"):
                # HOW情報も含まれている場合はconfirmへ
                next_step = "confirm"
                response = self._generate_understanding_response(
                    {"why": session.get("why_answer", ""),
                     "what": user_message,
                     "how": ""},
                    session
                )
            else:
                feedback = f"「{user_message[:30]}...」を目指すんだね！"
                response = TEMPLATES["what_to_how"].format(
                    user_name=self.user_name,
                    feedback=feedback
                )

            self._update_session(conn, session_id, current_step=next_step, **updates)

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

            # Phase 2.5 + B Memory統合: セッション完了時の学習
            self._update_session_stats_on_complete(conn, session)
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

        # Phase 2.5 + B Memory統合: OKパターンから学習
        specificity_score = evaluation.get("specificity_score", 0.0) if evaluation else 0.0
        self._learn_from_interaction(
            conn, session, current_step, pattern,
            was_accepted=True,
            retry_count=step_attempt,
            specificity_score=specificity_score
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
            response = TEMPLATES[pattern].format(
                user_name=self.user_name,
                user_answer=user_answer,
                what_answer=what_answer[:50]
            )
            # Phase 2.5 + B Memory統合: パーソナライズ
            return self._personalize_feedback(response, pattern, step, step_attempt)

        # デフォルトのフィードバック
        response = TEMPLATES["ng_abstract"].format(
            user_name=self.user_name,
            user_answer=user_answer
        )
        # Phase 2.5 + B Memory統合: パーソナライズ
        return self._personalize_feedback(response, pattern, step, step_attempt)

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

    # =====================================================
    # Phase 2.5 + B Memory統合メソッド
    # =====================================================

    def _load_memory_context(self, conn) -> None:
        """Memory Frameworkからコンテキストをロード"""
        if not self.user_id or not self.org_id:
            return

        try:
            # GoalSettingContextEnricherをlazy load
            # v10.31.4: 相対インポートに変更（googleapiclient警告修正）
            from ..memory.goal_integration import GoalSettingContextEnricher

            enricher = GoalSettingContextEnricher(conn, self.org_id)
            # 同期版として呼び出し（asyncioがない環境向け）
            self.enriched_context = self._get_sync_context(enricher)

            # パターン分析器を初期化
            from .analysis import GoalSettingUserPatternAnalyzer
            self.pattern_analyzer = GoalSettingUserPatternAnalyzer(conn, self.org_id)

        except ImportError:
            # Memory Frameworkが利用不可の場合はスキップ
            logger.warning("Memory Framework not available, skipping context enrichment")
        except Exception as e:
            logger.error("Memoryコンテキストロードエラー（続行）: %s", e)

    def _get_sync_context(self, enricher) -> Dict[str, Any]:
        """同期的にコンテキストを取得（asyncioなし環境向け）"""
        try:
            # goal_setting_user_patternsから直接取得
            context = {
                "conversation_summary": {},
                "user_preferences": {},
                "goal_patterns": enricher._get_goal_pattern_context(self.user_id),
                "recommendations": {}
            }
            context["recommendations"] = enricher._generate_recommendations(context)
            return context
        except Exception as e:
            logger.error("Sync context error: %s", e)
            return enricher._empty_context()

    def _personalize_feedback(
        self,
        base_response: str,
        pattern: str,
        step: str,
        step_attempt: int
    ) -> str:
        """フィードバックをパーソナライズ"""
        if not self.enriched_context:
            return base_response

        context = self.enriched_context
        goal_patterns = context.get("goal_patterns", {})
        recommendations = context.get("recommendations", {})

        # 過去の成功パターンを参照
        if goal_patterns.get("completion_rate", 0) >= 70:
            # 完了率が高いユーザーには励ましを強化
            if step_attempt == 1:
                base_response = base_response.replace(
                    "🐺",
                    "🐺✨（{name}さん、いつも具体的に答えてくれてありがとうウル！）".format(
                        name=self.user_name
                    ),
                    1  # 最初の1つだけ置換
                )

        # 感情傾向を考慮
        prefs = context.get("user_preferences", {})
        emotion_trend = prefs.get("emotion_trend", {})
        if emotion_trend:
            trend_direction = emotion_trend.get("trend_direction")
            if trend_direction == "declining":
                # 感情が下降傾向の場合は励ましを強化
                base_response = base_response.replace("🐺", "🐺💙")

        # フォーカスエリアをヒントとして追加（リトライ時）
        focus_areas = recommendations.get("focus_areas", [])
        if step_attempt >= 2 and focus_areas:
            hint = focus_areas[0]
            if "具体的" in hint or "数値" in hint:
                base_response += f"\n\n💡 ヒント: {hint}"

        return base_response

    def _learn_from_interaction(
        self,
        conn,
        session: Dict[str, Any],
        step: str,
        pattern: str,
        was_accepted: bool,
        retry_count: int,
        specificity_score: float = 0.0
    ) -> None:
        """目標設定対話から学習してパターンを更新"""
        if not self.pattern_analyzer:
            return

        try:
            self.pattern_analyzer.update_user_pattern(
                user_id=self.user_id,
                session_id=session.get("id", ""),
                step=step,
                pattern=pattern,
                was_accepted=was_accepted,
                retry_count=retry_count,
                specificity_score=specificity_score
            )
        except Exception as e:
            logger.error("学習エラー（続行）: %s", e)

    def _update_session_stats_on_complete(self, conn, session: Dict[str, Any]) -> None:
        """セッション完了時に統計を更新"""
        if not self.pattern_analyzer:
            return

        try:
            # セッション内のリトライ回数を計算
            total_retry = self._get_total_retry_count(conn, session["id"])

            self.pattern_analyzer.update_session_stats(
                user_id=self.user_id,
                completed=True,
                total_retry_count=total_retry
            )

            # B2 ユーザー嗜好に目標設定使用を記録
            self._update_preference_on_complete(conn, session)

        except Exception as e:
            logger.error("セッション統計更新エラー（続行）: %s", e)

    def _get_total_retry_count(self, conn, session_id: str) -> int:
        """
        セッション内の総リトライ回数を取得（v1.8: brain_dialogue_logs使用）

        chatwork_account_idとroom_idで24時間以内のリトライを検索。
        """
        try:
            result = conn.execute(
                text("""
                    SELECT COUNT(*) FROM brain_dialogue_logs
                    WHERE chatwork_account_id = :account_id
                      AND room_id = :room_id
                      AND organization_id = :org_id
                      AND state_type = 'goal_setting'
                      AND result = 'retry'
                      AND created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
                """),
                {
                    "account_id": self.account_id,
                    "room_id": self.room_id,
                    "org_id": self.org_id
                }
            ).fetchone()
            return result[0] if result else 0
        except Exception:
            return 0

    def _update_preference_on_complete(self, conn, session: Dict[str, Any]) -> None:
        """セッション完了時にB2嗜好を更新"""
        try:
            # v10.31.4: 相対インポートに変更（googleapiclient警告修正）
            from ..memory.user_preference import UserPreference
            from uuid import UUID

            pref_service = UserPreference(conn, UUID(self.org_id))

            # 目標設定機能の使用を記録
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # 同期的に保存（Cloud Functions環境向け）
            conn.execute(
                text("""
                    INSERT INTO user_preferences (
                        organization_id, user_id, preference_type, preference_key,
                        preference_value, learned_from, confidence
                    ) VALUES (
                        :org_id, :user_id, 'feature_usage', 'goal_setting',
                        :pref_value, 'auto', 0.5
                    )
                    ON CONFLICT (organization_id, user_id, preference_type, preference_key)
                    DO UPDATE SET
                        preference_value = :pref_value,
                        sample_count = user_preferences.sample_count + 1,
                        confidence = LEAST(user_preferences.confidence + 0.1, 0.95),
                        updated_at = CURRENT_TIMESTAMP
                """),
                {
                    "org_id": self.org_id,
                    "user_id": self.user_id,
                    "pref_value": json.dumps({
                        "last_completed": datetime.now().isoformat(),
                        "session_id": session.get("id")
                    })
                }
            )
            conn.commit()

        except ImportError:
            pass
        except Exception as e:
            logger.error("嗜好更新エラー（続行）: %s", e)


def has_active_goal_session(pool, room_id: str, account_id: str) -> bool:
    """
    アクティブな目標設定セッションが存在するかチェック（v1.8: brain_conversation_states使用）

    chatwork-webhook から呼び出して、通常のAI応答をバイパスするかどうか判定する。
    user_id として chatwork_account_id を直接使用。
    """
    with pool.connect() as conn:
        # ユーザー情報を取得（org_idの取得のみ）
        user_result = conn.execute(
            text("""
                SELECT organization_id FROM users
                WHERE chatwork_account_id = :account_id
                LIMIT 1
            """),
            {"account_id": str(account_id)}
        ).fetchone()

        if not user_result:
            return False

        org_id = str(user_result[0]) if user_result[0] else None

        if not org_id:
            return False

        # brain_conversation_statesでアクティブなセッションをチェック
        result = conn.execute(
            text("""
                SELECT COUNT(*) FROM brain_conversation_states
                WHERE user_id = :account_id
                  AND organization_id = :org_id
                  AND room_id = :room_id
                  AND state_type = 'goal_setting'
                  AND expires_at > CURRENT_TIMESTAMP
            """),
            {
                "account_id": str(account_id),
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
