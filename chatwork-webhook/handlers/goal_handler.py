"""
目標達成支援ハンドラー

main.pyから分割された目標登録・進捗報告・確認の機能を提供する。

分割元: chatwork-webhook/main.py
分割日: 2026-01-25
バージョン: v10.24.6
v10.46.0: Persona観測ログ追加
"""

import traceback
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from typing import Optional, Dict, Any, Callable

from sqlalchemy import text

# v10.46.0: Persona観測ログ
try:
    from lib.persona import log_persona_path
except ImportError:
    # フォールバック用ダミー関数
    def log_persona_path(*args, **kwargs):
        pass


class GoalHandler:
    """
    目標達成支援ハンドラークラス

    外部依存を注入することで、main.pyとの疎結合を実現。
    """

    def __init__(
        self,
        get_pool: Callable,
        process_goal_setting_message_func: Callable = None,
        use_goal_setting_lib: bool = False
    ):
        """
        Args:
            get_pool: DB接続プールを取得する関数
            process_goal_setting_message_func: 目標設定対話処理関数（オプション）
            use_goal_setting_lib: 目標設定ライブラリを使用するかどうか
        """
        self.get_pool = get_pool
        self.process_goal_setting_message_func = process_goal_setting_message_func
        self.use_goal_setting_lib = use_goal_setting_lib

    def _format_number_range(self, numbers: list) -> str:
        """
        番号リストを読みやすい形式にフォーマット

        例: [2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] -> "2,3,6-15"
        """
        if not numbers:
            return ""

        sorted_nums = sorted(numbers)
        ranges = []
        start = sorted_nums[0]
        end = start

        for num in sorted_nums[1:]:
            if num == end + 1:
                end = num
            else:
                if start == end:
                    ranges.append(str(start))
                elif end == start + 1:
                    ranges.append(f"{start},{end}")
                else:
                    ranges.append(f"{start}-{end}")
                start = num
                end = num

        # 最後のレンジを追加
        if start == end:
            ranges.append(str(start))
        elif end == start + 1:
            ranges.append(f"{start},{end}")
        else:
            ranges.append(f"{start}-{end}")

        return ",".join(ranges)

    def _check_dialogue_completed(self, room_id: str, account_id: str) -> bool:
        """
        v10.40.1: 対話フロー完了確認（神経接続修理 - brain_conversation_statesのみ参照）

        brain_conversation_states で直近5分以内に目標設定対話が完了したかをチェック。
        完了時には state_data->completed_at が設定されている。

        Returns:
            True: 対話フロー完了済み（登録可能）
            False: 対話未完了（登録不可）
        """
        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                # ユーザーの organization_id を取得
                user_result = conn.execute(
                    text("""
                        SELECT organization_id FROM users
                        WHERE chatwork_account_id = :account_id
                        LIMIT 1
                    """),
                    {"account_id": str(account_id)}
                ).fetchone()

                if not user_result or not user_result[0]:
                    return False

                org_id = str(user_result[0])

                # brain_conversation_states で直近5分以内に完了したセッションをチェック
                # 完了時には state_type='normal' に変更され、state_data に completed_at が設定される
                result = conn.execute(
                    text("""
                        SELECT id, state_data
                        FROM brain_conversation_states
                        WHERE user_id = :account_id
                          AND organization_id = :org_id
                          AND room_id = :room_id
                          AND state_type = 'normal'
                          AND state_data->>'completed_at' IS NOT NULL
                          AND updated_at > NOW() - INTERVAL '5 minutes'
                        ORDER BY updated_at DESC
                        LIMIT 1
                    """),
                    {"account_id": str(account_id), "org_id": org_id, "room_id": str(room_id)}
                ).fetchone()

                return result is not None
        except Exception as e:
            print(f"⚠️ 対話完了確認エラー: {e}")
            return False

    def handle_goal_registration(
        self,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        目標登録ハンドラー（Phase 2.5 v1.6）

        v10.19.0: WHY→WHAT→HOW の一問一答形式の目標設定対話を開始。

        v10.40.0: 対話フロー必須化
        - LLMの直接判定による登録を禁止
        - 必ず WHY→WHAT→HOW 対話を経由しないと登録不可
        - 「導く存在」としてのソウルくんを実現

        アチーブメント社・選択理論に基づく目標設定支援。

        v10.46.0: Persona観測ログ追加
        """
        print(f"🎯 handle_goal_registration 開始: room_id={room_id}, account_id={account_id}")
        # v10.46.0: Persona観測ログ（goal_registrationは直接応答のためinjected=no）
        log_persona_path(
            path="goal_registration",
            injected=False,
            addon=False,
            account_id=account_id,
            extra="direct_response",
        )
        print(f"   params: {params}")

        try:
            # =====================================================
            # v10.40.0: 対話フロー必須ガード
            # =====================================================
            # 対話フローを経由せずに呼ばれた場合は、対話開始へ誘導
            # これにより「LLMが直接登録」を完全に防止

            # context から対話完了フラグを確認
            dialogue_completed = False
            if context:
                dialogue_completed = context.get("dialogue_completed", False)
                # brain_conversation_states から確認ステップ完了をチェック
                if not dialogue_completed:
                    dialogue_completed = context.get("from_goal_setting_dialogue", False)

            # DB から対話完了を確認（フラグがない場合）
            if not dialogue_completed:
                dialogue_completed = self._check_dialogue_completed(room_id, account_id)

            goal_title = params.get("goal_title", "")

            # 対話未完了の場合は必ず対話フローへ誘導
            if not dialogue_completed:
                print("   ⛔ 対話フロー未完了 → 対話開始へ誘導")

                if self.use_goal_setting_lib and self.process_goal_setting_message_func:
                    # 対話フローを開始
                    pool = self.get_pool()
                    original_message = context.get("original_message", "") if context else ""

                    # ユーザーの入力が長文の場合、「目標の素材」として扱う旨を伝える
                    if len(original_message) > 100:
                        intro_message = (
                            "🐺 素敵な目標への想いを聞かせてくれてありがとうウル！\n\n"
                            "ソウルくんは「正しい目標達成の技術」でサポートするウル✨\n"
                            "一緒に整理していこうウル！\n\n"
                        )
                        result = self.process_goal_setting_message_func(
                            pool, room_id, account_id,
                            "目標設定したい"  # 対話開始トリガー
                        )
                        if result.get("success") and result.get("message"):
                            result["message"] = intro_message + result["message"]
                        return result
                    else:
                        return self.process_goal_setting_message_func(
                            pool, room_id, account_id,
                            original_message or "目標設定したい"
                        )
                else:
                    return {
                        "success": False,
                        "message": (
                            "🐺 目標設定は対話形式で進めるウル！\n\n"
                            "まずは「目標設定したい」と言ってほしいウル✨\n"
                            "WHY・WHAT・HOWの3つの質問で、\n"
                            "あなたを正しい目標達成へ導くウル🐺"
                        )
                    }

            # =====================================================
            # 対話完了後の登録処理（ここに到達 = 対話完了済み）
            # =====================================================
            print(f"   ✅ 対話完了確認済み → 目標登録: {goal_title}")

            # パラメータ抽出（v10.46.0: 欠落していた抽出処理を追加）
            period_type = params.get("period_type", "monthly")
            goal_type = params.get("goal_type", "action")
            target_value = params.get("target_value")
            unit = params.get("unit", "")
            deadline = params.get("deadline")

            # 期間を計算
            today = date.today()
            if period_type == "weekly":
                period_start = today - timedelta(days=today.weekday())
                period_end = period_start + timedelta(days=6)
            elif period_type == "monthly":
                period_start = today.replace(day=1)
                if today.month == 12:
                    period_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    period_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
            elif period_type == "quarterly":
                quarter = (today.month - 1) // 3
                period_start = today.replace(month=quarter * 3 + 1, day=1)
                if quarter == 3:
                    period_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    period_end = today.replace(month=(quarter + 1) * 3 + 1, day=1) - timedelta(days=1)
            else:  # yearly
                period_start = today.replace(month=1, day=1)
                period_end = today.replace(month=12, day=31)

            # deadlineがある場合はそれを使用
            if deadline:
                try:
                    if isinstance(deadline, str):
                        period_end = datetime.strptime(deadline, "%Y-%m-%d").date()
                except:
                    pass

            # user_id を取得（account_id から users テーブルを検索）
            pool = self.get_pool()
            with pool.connect() as conn:
                # account_id から user_id と organization_id を取得
                user_result = conn.execute(
                    text("""
                        SELECT id, organization_id, name FROM users
                        WHERE chatwork_account_id = :account_id
                        LIMIT 1
                    """),
                    {"account_id": str(account_id)}
                ).fetchone()

                if not user_result:
                    # ユーザーが見つからない場合はエラー（登録誘導）
                    print(f"⚠️ ユーザーが見つかりません: account_id={account_id}")
                    return {
                        "success": False,
                        "message": "🤔 まだソウルくんに登録されていないみたいウル！\n\n管理者に連絡して、ユーザー登録をお願いしてウル🐺"
                    }

                user_id = str(user_result[0])
                org_id = user_result[1]
                user_name = user_result[2] or sender_name or "ユーザー"

                # organization_idがNULLの場合もエラー
                if not org_id:
                    print(f"⚠️ organization_idがNULL: user_id={user_id}")
                    return {
                        "success": False,
                        "message": "🤔 組織情報が設定されていないみたいウル！\n\n管理者に連絡して、組織設定をお願いしてウル🐺"
                    }
                org_id = str(org_id)

                # 目標を登録
                goal_id = str(uuid4())

                insert_query = text("""
                    INSERT INTO goals (
                        id, organization_id, user_id, goal_level, title, description,
                        goal_type, target_value, current_value, unit, deadline,
                        period_type, period_start, period_end, status, classification,
                        created_by, updated_by, created_at, updated_at
                    ) VALUES (
                        :id, :organization_id, :user_id, 'individual', :title, NULL,
                        :goal_type, :target_value, 0, :unit, :deadline,
                        :period_type, :period_start, :period_end, 'active', 'internal',
                        :user_id, :user_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                """)

                conn.execute(insert_query, {
                    "id": goal_id,
                    "organization_id": org_id,
                    "user_id": user_id,
                    "title": goal_title,
                    "goal_type": goal_type,
                    "target_value": float(target_value) if target_value else None,
                    "unit": unit,
                    "deadline": period_end if goal_type == "deadline" else None,
                    "period_type": period_type,
                    "period_start": period_start,
                    "period_end": period_end,
                })
                conn.commit()

                print(f"✅ 目標登録完了: goal_id={goal_id}, title={goal_title}, user_id={user_id}")

                # 応答メッセージを組み立て
                response = f"✅ 目標を登録したウル！🎯\n\n"
                response += f"📌 目標: {goal_title}\n"

                if goal_type == "numeric" and target_value:
                    formatted_value = f"{int(target_value):,}" if target_value == int(target_value) else f"{target_value:,.2f}"
                    response += f"🎯 目標値: {formatted_value}{unit or ''}\n"
                elif goal_type == "deadline":
                    response += f"⏰ 期限: {period_end.strftime('%Y年%m月%d日')}\n"
                elif goal_type == "action":
                    response += f"🔄 タイプ: 行動目標\n"

                response += f"📅 期間: {period_start.strftime('%m/%d')}〜{period_end.strftime('%m/%d')}\n"
                response += f"\n"
                response += f"{user_name}さんなら絶対達成できるって、ソウルくんは信じてるウル💪🐺\n"
                response += f"\n"
                response += f"毎日17時に進捗を聞くから、一緒に頑張っていこうウル✨"

                return {"success": True, "message": response}

        except Exception as e:
            print(f"❌ handle_goal_registration エラー: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": "❌ 目標の登録に失敗したウル...もう一度試してほしいウル🐺"
            }

    def handle_goal_progress_report(
        self,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        目標進捗報告ハンドラー（Phase 2.5）

        goal_progress テーブルに進捗を記録する。

        v10.46.0: Persona観測ログ追加
        """
        print(f"📊 handle_goal_progress_report 開始: room_id={room_id}, account_id={account_id}")
        print(f"   params: {params}")
        # v10.46.0: Persona観測ログ（goal_progress_reportは直接応答のためinjected=no）
        log_persona_path(
            path="goal_progress_report",
            injected=False,
            addon=False,
            account_id=account_id,
            extra="direct_response",
        )

        try:
            progress_value = params.get("progress_value")
            daily_note = params.get("daily_note", "")
            daily_choice = params.get("daily_choice", "")

            pool = self.get_pool()
            with pool.connect() as conn:
                # ユーザー情報を取得
                user_result = conn.execute(
                    text("""
                        SELECT id, organization_id, name FROM users
                        WHERE chatwork_account_id = :account_id
                        LIMIT 1
                    """),
                    {"account_id": str(account_id)}
                ).fetchone()

                if not user_result:
                    return {
                        "success": False,
                        "message": "🤔 まだ目標を登録していないみたいウル！\n「目標を設定したい」と言ってくれたら登録できるウル🐺"
                    }

                user_id = str(user_result[0])
                org_id = user_result[1]
                user_name = user_result[2] or sender_name or "ユーザー"

                # organization_idがNULLの場合はエラー
                if not org_id:
                    return {
                        "success": False,
                        "message": "🤔 組織情報が設定されていないみたいウル！\n\n管理者に連絡して、組織設定をお願いしてウル🐺"
                    }
                org_id = str(org_id)

                # アクティブな目標を取得
                goals_result = conn.execute(
                    text("""
                        SELECT id, title, goal_type, target_value, current_value, unit, period_end
                        FROM goals
                        WHERE user_id = :user_id AND organization_id = :organization_id
                          AND status = 'active'
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"user_id": user_id, "organization_id": org_id}
                ).fetchone()

                if not goals_result:
                    return {
                        "success": False,
                        "message": "🤔 アクティブな目標が見つからないウル！\n「目標を設定したい」と言ってくれたら登録できるウル🐺"
                    }

                goal_id = str(goals_result[0])
                goal_title = goals_result[1]
                goal_type = goals_result[2]
                target_value = Decimal(str(goals_result[3])) if goals_result[3] else None
                current_value = Decimal(str(goals_result[4])) if goals_result[4] else Decimal(0)
                unit = goals_result[5] or ""
                period_end = goals_result[6]

                today = date.today()

                # 累計値を計算
                cumulative_value = None
                if progress_value is not None and goal_type == "numeric":
                    progress_decimal = Decimal(str(progress_value))

                    # 既存の累計を取得
                    prev_result = conn.execute(
                        text("""
                            SELECT COALESCE(SUM(value), 0) as total
                            FROM goal_progress
                            WHERE goal_id = :goal_id AND organization_id = :organization_id
                              AND progress_date < :today
                        """),
                        {"goal_id": goal_id, "organization_id": org_id, "today": today}
                    ).fetchone()

                    prev_total = Decimal(str(prev_result[0])) if prev_result else Decimal(0)
                    cumulative_value = prev_total + progress_decimal

                # 進捗を記録（UPSERT）
                progress_id = str(uuid4())

                conn.execute(
                    text("""
                        INSERT INTO goal_progress (
                            id, goal_id, organization_id, progress_date, value,
                            cumulative_value, daily_note, daily_choice, classification,
                            created_by, updated_by, created_at, updated_at
                        ) VALUES (
                            :id, :goal_id, :organization_id, :progress_date, :value,
                            :cumulative_value, :daily_note, :daily_choice, 'internal',
                            :user_id, :user_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        ON CONFLICT (goal_id, progress_date)
                        DO UPDATE SET
                            value = EXCLUDED.value,
                            cumulative_value = EXCLUDED.cumulative_value,
                            daily_note = EXCLUDED.daily_note,
                            daily_choice = EXCLUDED.daily_choice,
                            updated_at = CURRENT_TIMESTAMP,
                            updated_by = EXCLUDED.created_by
                    """),
                    {
                        "id": progress_id,
                        "goal_id": goal_id,
                        "organization_id": org_id,
                        "progress_date": today,
                        "value": float(progress_value) if progress_value is not None else None,
                        "cumulative_value": float(cumulative_value) if cumulative_value is not None else None,
                        "daily_note": daily_note or None,
                        "daily_choice": daily_choice or None,
                        "user_id": user_id,
                    }
                )

                # 目標のcurrent_valueを更新
                if cumulative_value is not None:
                    conn.execute(
                        text("""
                            UPDATE goals
                            SET current_value = :cumulative_value, updated_at = CURRENT_TIMESTAMP
                            WHERE id = :goal_id AND organization_id = :organization_id
                        """),
                        {"goal_id": goal_id, "organization_id": org_id, "cumulative_value": float(cumulative_value)}
                    )

                conn.commit()

                print(f"✅ 進捗記録完了: goal_id={goal_id}, value={progress_value}, cumulative={cumulative_value}")

                # 応答メッセージを組み立て
                response = f"✅ 進捗を記録したウル！📊\n\n"
                response += f"📌 目標: {goal_title}\n"

                if goal_type == "numeric" and progress_value is not None and target_value:
                    formatted_today = f"{int(progress_value):,}" if progress_value == int(progress_value) else f"{progress_value:,.2f}"
                    formatted_cumulative = f"{int(cumulative_value):,}" if cumulative_value == int(cumulative_value) else f"{cumulative_value:,.2f}"
                    formatted_target = f"{int(target_value):,}" if target_value == int(target_value) else f"{target_value:,.2f}"

                    achievement_rate = float(cumulative_value / target_value * 100) if target_value else 0
                    remaining = target_value - cumulative_value

                    response += f"📈 今日の実績: +{formatted_today}{unit}\n"
                    response += f"📊 累計: {formatted_cumulative}{unit} / {formatted_target}{unit}\n"
                    response += f"🎯 達成率: {achievement_rate:.1f}%\n"

                    if achievement_rate >= 100:
                        response += f"\n🎉🎉🎉 目標達成おめでとうウル！！！ 🎉🎉🎉\n"
                        response += f"{user_name}さん、すごいウル！ソウルくんも嬉しいウル🐺✨"
                    elif achievement_rate >= 80:
                        response += f"\nあと{int(remaining):,}{unit}で達成ウル！もう少しウル💪🐺"
                    elif achievement_rate >= 50:
                        response += f"\n半分超えたウル！この調子で頑張ろうウル🐺✨"
                    else:
                        response += f"\nまだまだこれからウル！{user_name}さんなら絶対できるウル💪🐺"

                else:
                    if daily_note:
                        response += f"📝 報告: {daily_note}\n"
                    response += f"\n今日も頑張ったウル！{user_name}さん、素敵ウル🐺✨"

                # v10.56.0: 次の一手を提示（設計書5.7.1）
                # 注: これは「判断」ではなく「表示ルール」。設計書5.7で「必ず1つ提示する」と
                # 規定されており、達成率に応じた定型文を機械的に選択する。LLM判断は不要。
                response += "\n\n"
                response += "─────────────────\n"
                response += "💡 次の一手: "
                if goal_type == "numeric" and target_value:
                    if achievement_rate >= 100:
                        response += "次の目標を設定しようウル🎯"
                    elif achievement_rate >= 80:
                        response += "あと少し！今日もう1件アクションしようウル💪"
                    else:
                        response += "明日も同じペースで進めようウル📈"
                else:
                    response += "明日も報告してくれると嬉しいウル🐺"

                return {"success": True, "message": response, "next_action": "明日も進捗報告"}

        except Exception as e:
            print(f"❌ handle_goal_progress_report エラー: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": "❌ 進捗の記録に失敗したウル...もう一度試してほしいウル🐺"
            }

    def handle_goal_status_check(
        self,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        目標確認ハンドラー（Phase 2.5）

        現在の目標と進捗状況を返す。

        v10.46.0: Persona観測ログ追加
        """
        print(f"📋 handle_goal_status_check 開始: room_id={room_id}, account_id={account_id}")
        # v10.46.0: Persona観測ログ（goal_status_checkは直接応答のためinjected=no）
        log_persona_path(
            path="goal_status_check",
            injected=False,
            addon=False,
            account_id=account_id,
            extra="direct_response",
        )

        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                # ユーザー情報を取得
                user_result = conn.execute(
                    text("""
                        SELECT id, organization_id, name FROM users
                        WHERE chatwork_account_id = :account_id
                        LIMIT 1
                    """),
                    {"account_id": str(account_id)}
                ).fetchone()

                if not user_result:
                    return {
                        "success": False,
                        "message": "🤔 まだ目標を登録していないみたいウル！\n「目標を設定したい」と言ってくれたら登録できるウル🐺"
                    }

                user_id = str(user_result[0])
                org_id = user_result[1]
                user_name = user_result[2] or sender_name or "ユーザー"

                # organization_idがNULLの場合はエラー
                if not org_id:
                    return {
                        "success": False,
                        "message": "🤔 組織情報が設定されていないみたいウル！\n\n管理者に連絡して、組織設定をお願いしてウル🐺"
                    }
                org_id = str(org_id)

                # アクティブな目標を取得
                goals_result = conn.execute(
                    text("""
                        SELECT id, title, goal_type, target_value, current_value, unit,
                               period_start, period_end, status
                        FROM goals
                        WHERE user_id = :user_id AND organization_id = :organization_id
                          AND status = 'active'
                        ORDER BY created_at DESC
                    """),
                    {"user_id": user_id, "organization_id": org_id}
                ).fetchall()

                if not goals_result:
                    return {
                        "success": False,
                        "message": "🤔 まだ目標を登録していないみたいウル！\n「目標を設定したい」と言ってくれたら一緒に考えるウル🐺"
                    }

                today = date.today()

                # 応答メッセージを組み立て
                response = f"📋 {user_name}さんの目標状況ウル！\n\n"

                for i, goal in enumerate(goals_result, 1):
                    goal_id = str(goal[0])
                    goal_title = goal[1]
                    goal_type = goal[2]
                    target_value = Decimal(str(goal[3])) if goal[3] else None
                    current_value = Decimal(str(goal[4])) if goal[4] else Decimal(0)
                    unit = goal[5] or ""
                    period_start = goal[6]
                    period_end = goal[7]

                    response += f"【目標{i}】{goal_title}\n"

                    if goal_type == "numeric" and target_value:
                        achievement_rate = float(current_value / target_value * 100) if target_value else 0
                        formatted_current = f"{int(current_value):,}" if current_value == int(current_value) else f"{current_value:,.2f}"
                        formatted_target = f"{int(target_value):,}" if target_value == int(target_value) else f"{target_value:,.2f}"

                        response += f"  📊 進捗: {formatted_current}{unit} / {formatted_target}{unit}\n"
                        response += f"  🎯 達成率: {achievement_rate:.1f}%\n"

                        # 進捗バー
                        filled = int(achievement_rate / 10)
                        bar = "█" * filled + "░" * (10 - filled)
                        response += f"  [{bar}]\n"

                    elif goal_type == "deadline":
                        if period_end:
                            remaining_days = (period_end - today).days
                            if remaining_days < 0:
                                response += f"  ⏰ 期限: {period_end.strftime('%Y/%m/%d')} (期限切れ)\n"
                            elif remaining_days == 0:
                                response += f"  ⏰ 期限: 今日まで！\n"
                            else:
                                response += f"  ⏰ 期限: {period_end.strftime('%Y/%m/%d')} (あと{remaining_days}日)\n"

                    else:  # action
                        response += f"  📅 期間: {period_start.strftime('%m/%d')}〜{period_end.strftime('%m/%d')}\n"

                    response += "\n"

                response += f"✨ {len(goals_result)}個の目標を追いかけてるウル！{user_name}さん、頑張ってるウル🐺"

                # v10.56.0: 次の一手を提示
                response += "\n\n─────────────────\n"
                response += "💡 次の一手: 今日の進捗を報告しようウル📊"

            return {"success": True, "message": response, "next_action": "進捗を報告する"}

        except Exception as e:
            print(f"❌ handle_goal_status_check エラー: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": "❌ 目標の確認に失敗したウル...もう一度試してほしいウル🐺"
            }

    # v10.45.0: goal_review ハンドラー（既存目標の一覧・整理・削除・修正）
    def handle_goal_review(
        self,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        目標一覧・整理ハンドラー（v10.45.0）

        既存の目標一覧を表示する、または整理・削除・修正する。

        v10.46.0: Persona観測ログ追加
        """
        print(f"📋 handle_goal_review 開始: room_id={room_id}, account_id={account_id}")
        # v10.46.0: Persona観測ログ（goal_reviewは直接応答のためinjected=no）
        log_persona_path(
            path="goal_review",
            injected=False,
            addon=False,
            account_id=account_id,
            extra="direct_response",
        )

        action = params.get("action", "list")

        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                # ユーザー情報を取得
                user_result = conn.execute(
                    text("""
                        SELECT id, organization_id, name FROM users
                        WHERE chatwork_account_id = :account_id
                        LIMIT 1
                    """),
                    {"account_id": str(account_id)}
                ).fetchone()

                if not user_result:
                    return {
                        "success": False,
                        "message": "🤔 まだ目標を登録していないみたいウル！\n「新しく目標を作りたい」と言ってくれたら登録できるウル🐺"
                    }

                user_id = str(user_result[0])
                org_id = user_result[1]
                user_name = user_result[2] or sender_name or "ユーザー"

                if not org_id:
                    return {
                        "success": False,
                        "message": "🤔 組織情報が設定されていないみたいウル！\n\n管理者に連絡して、組織設定をお願いしてウル🐺"
                    }
                org_id = str(org_id)

                # 全目標を取得（active + completed + paused）
                goals_result = conn.execute(
                    text("""
                        SELECT id, title, goal_type, target_value, current_value, unit,
                               period_start, period_end, status, created_at
                        FROM goals
                        WHERE user_id = :user_id AND organization_id = :organization_id
                        ORDER BY created_at DESC
                        LIMIT 50
                    """),
                    {"user_id": user_id, "organization_id": org_id}
                ).fetchall()

                if not goals_result:
                    return {
                        "success": False,
                        "message": "🤔 まだ目標を登録していないみたいウル！\n「新しく目標を作りたい」と言ってくれたら一緒に考えるウル🐺"
                    }

                # 応答メッセージを組み立て
                active_count = sum(1 for g in goals_result if g[8] == 'active')
                completed_count = sum(1 for g in goals_result if g[8] == 'completed')
                paused_count = sum(1 for g in goals_result if g[8] == 'paused')

                response = f"📋 {user_name}さんの目標一覧ウル！\n\n"

                # 状態ごとに分類して表示
                if active_count > 0:
                    response += f"【アクティブ ({active_count}件)】\n"
                    for i, goal in enumerate([g for g in goals_result if g[8] == 'active'], 1):
                        goal_title = goal[1][:40]  # 長すぎる場合は省略
                        target_value = goal[3]
                        unit = goal[5] or ""
                        period_end = goal[7]

                        if target_value:
                            response += f"  {i}. {goal_title} ({target_value:,.0f}{unit})\n"
                        else:
                            response += f"  {i}. {goal_title}\n"

                        if period_end:
                            response += f"     📅 〜{period_end.strftime('%m/%d')}\n"
                    response += "\n"

                if completed_count > 0:
                    response += f"【完了済み ({completed_count}件)】\n"
                    for goal in [g for g in goals_result if g[8] == 'completed'][:5]:
                        response += f"  ✅ {goal[1][:30]}\n"
                    if completed_count > 5:
                        response += f"  ...他{completed_count - 5}件\n"
                    response += "\n"

                if paused_count > 0:
                    response += f"【一時停止 ({paused_count}件)】\n"
                    for goal in [g for g in goals_result if g[8] == 'paused'][:3]:
                        response += f"  ⏸️ {goal[1][:30]}\n"
                    response += "\n"

                # 整理のアドバイス
                total = len(goals_result)
                if total > 10:
                    response += f"💡 目標が{total}個あるウル！整理した方がいいかもウル🐺\n"
                    response += "「目標を削除したい」「目標を整理したい」と言ってくれたら手伝うウル！\n"
                elif active_count > 5:
                    response += f"💡 アクティブな目標が{active_count}個あるウル。優先順位をつけた方がいいかもウル🐺\n"

                # v10.56.0: 次の一手を提示（設計書5.7.3）
                # 注: これは「判断」ではなく「表示ルール」。設計書5.7で「必ず1つ提示する」と
                # 規定されており、状態に応じた定型文を機械的に選択する。LLM判断は不要。
                next_action = "進捗を報告する"  # デフォルト値
                response += "\n─────────────────\n"
                response += "💡 次の一手: "
                if active_count == 0:
                    response += "新しい目標を設定しようウル🎯"
                    next_action = "目標を設定する"
                elif total > 10:
                    response += "まずは目標を整理しようウル🧹"
                    next_action = "目標を整理する"
                else:
                    response += "一番大事な目標の進捗を報告しようウル📊"
                    next_action = "進捗を報告する"

            return {"success": True, "message": response, "next_action": next_action}

        except Exception as e:
            print(f"❌ handle_goal_review エラー: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": "❌ 目標一覧の取得に失敗したウル...もう一度試してほしいウル🐺"
            }

    # v10.45.0: goal_consult ハンドラー（目標の決め方・優先順位の相談）
    def handle_goal_consult(
        self,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        目標相談ハンドラー（v10.45.0）

        目標の決め方や優先順位について相談する。
        このハンドラーはgeneral_conversationにフォールバックし、LLMを使って相談に回答する。

        v10.46.0: Persona観測ログ追加
        """
        print(f"💬 handle_goal_consult 開始: room_id={room_id}, account_id={account_id}")
        # v10.46.0: Persona観測ログ（goal_consultはLLMフォールバックのためget_ai_responseで別途注入される）
        log_persona_path(
            path="goal_consult",
            injected=False,
            addon=False,
            account_id=account_id,
            extra="fallback_to_general",
        )

        consultation_topic = params.get("consultation_topic", "")

        # goal_consultはgeneral_conversationと同様にLLMで回答するが、
        # 目標設定に関するコンテキストを追加する
        # v10.56.0: 「次の一手」提示を必須化（設計書5.7.2）
        consult_context = f"""
【相談テーマ】目標設定・優先順位について

ユーザーが目標の決め方や優先順位について相談しています。
以下のポイントを踏まえて、アドバイスしてください：

1. 数字で判断できる場合は数字を使う（売上と利益の比較など）
2. 短期と長期のバランスを考慮する
3. 具体的なアクションを1つ提案する
4. 押し付けず、ユーザーの判断を尊重する

相談内容: {consultation_topic}

【必須】回答の最後に「次の一手」を必ず提示してください。
例:
─────────────────
💡 次の一手: 目標に直結する行動を1つ決めようウル。
"""

        # このハンドラーはLLMベースの回答を行うため、
        # general_conversationハンドラーにフォールバックする
        return {
            "success": True,
            "message": None,  # Noneを返すと、general_conversationにフォールバック
            "fallback_to_general": True,
            "additional_context": consult_context
        }

    # =========================================================================
    # v10.56.0: 目標削除・整理フロー
    # 設計書: docs/05_phase2-5_goal_achievement.md セクション5.6, 5.7
    # =========================================================================

    def handle_goal_delete(
        self,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        目標削除ハンドラー（v10.56.0）

        番号指定による削除フロー:
        1. 一覧表示 → 番号指定 → 確認 → 実行
        2. 重複一括削除も選択可能

        設計書: docs/05_phase2-5_goal_achievement.md セクション5.6.1
        """
        print(f"🗑️ handle_goal_delete 開始: room_id={room_id}, account_id={account_id}")
        log_persona_path(
            path="goal_delete",
            injected=False,
            addon=False,
            account_id=account_id,
            extra="direct_response",
        )

        # パラメータ取得
        goal_numbers = params.get("goal_numbers", [])  # 番号リスト: [1, 2, 3]
        exclude_numbers = params.get("exclude_numbers", [])  # 「X以外削除」用: [1, 4, 5]
        delete_duplicates = params.get("delete_duplicates", False)  # 重複一括削除
        confirmed = params.get("confirmed", False)  # 確認済みフラグ

        # v10.56.1: 「X以外削除」パターンの解析
        # 入力例: 「1,4,5以外削除」「1・4・5以外を全部消したい」
        original_message = context.get("original_message", "") if context else ""
        if original_message and not goal_numbers and not exclude_numbers:
            import re
            # 「X以外」パターンを検出
            exclude_pattern = r'([0-9０-９,、・\s]+)\s*以外'
            match = re.search(exclude_pattern, original_message)
            if match:
                # 全角→半角変換、区切り文字正規化
                nums_str = match.group(1)
                nums_str = nums_str.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
                nums_str = re.sub(r'[,、・\s]+', ',', nums_str)
                exclude_numbers = [int(n) for n in nums_str.split(',') if n.strip().isdigit()]
                print(f"   📋 「以外削除」検出: exclude_numbers={exclude_numbers}")

        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                # ユーザー情報を取得
                user_result = conn.execute(
                    text("""
                        SELECT id, organization_id, name FROM users
                        WHERE chatwork_account_id = :account_id
                        LIMIT 1
                    """),
                    {"account_id": str(account_id)}
                ).fetchone()

                if not user_result:
                    return {
                        "success": False,
                        "message": "🤔 まだ目標を登録していないみたいウル！"
                    }

                user_id = str(user_result[0])
                org_id = str(user_result[1]) if user_result[1] else None
                user_name = user_result[2] or sender_name or "ユーザー"

                if not org_id:
                    return {
                        "success": False,
                        "message": "🤔 組織情報が設定されていないみたいウル！"
                    }

                # アクティブな目標を取得
                goals_result = conn.execute(
                    text("""
                        SELECT id, title, target_value, unit, period_end
                        FROM goals
                        WHERE user_id = :user_id AND organization_id = :organization_id
                          AND status = 'active'
                        ORDER BY created_at DESC
                        LIMIT 50
                    """),
                    {"user_id": user_id, "organization_id": org_id}
                ).fetchall()

                if not goals_result:
                    return {
                        "success": False,
                        "message": "🤔 アクティブな目標がないウル！"
                    }

                # 目標のマッピング（番号 → ID）
                goal_map = {i + 1: {
                    "id": str(row[0]),
                    "title": row[1],
                    "target_value": row[2],
                    "unit": row[3] or "",
                    "period_end": row[4],
                } for i, row in enumerate(goals_result)}

                # =====================================================
                # v10.56.1: 「X以外削除」の処理
                # =====================================================
                if exclude_numbers:
                    # 全件 - exclude_numbers = 削除対象
                    all_numbers = set(goal_map.keys())
                    keep_numbers = set(exclude_numbers) & all_numbers  # 有効な残す番号
                    delete_numbers = all_numbers - keep_numbers
                    goal_numbers = sorted(list(delete_numbers))
                    print(f"   📋 「以外削除」計算: 残す={sorted(keep_numbers)}, 削除={goal_numbers}")

                    if not goal_numbers:
                        return {
                            "success": True,
                            "message": f"✨ {sorted(keep_numbers)} 以外に削除する目標はないウル！"
                        }

                    # 確認メッセージ（「X以外削除」用）
                    # v10.56.1: ユーザー要件に合わせたフォーマット
                    if not confirmed:
                        keep_str = ",".join(map(str, sorted(keep_numbers)))
                        delete_str = self._format_number_range(goal_numbers)

                        response = f"{keep_str}を残して{delete_str}を削除。実行していい？\n\n"
                        response += "【削除対象】\n"
                        for num in goal_numbers:
                            goal = goal_map[num]
                            response += f"  {num}. {goal['title'][:35]}\n"

                        return {
                            "success": True,
                            "message": response,
                            "awaiting_confirmation": "goal_delete",
                            "pending_data": {
                                "goal_ids": [goal_map[n]["id"] for n in goal_numbers],
                                "keep_numbers": sorted(keep_numbers),
                                "delete_numbers": goal_numbers,
                            },
                        }

                # =====================================================
                # フェーズ1: 一覧表示（番号が未指定の場合）
                # =====================================================
                if not goal_numbers and not delete_duplicates:
                    response = "🗑️ 削除する目標を番号で教えてほしいウル。\n"
                    response += "例: 1,3,5 または「1,4,5以外削除」\n"
                    response += "同じ内容の重複がある場合は『重複を全部削除』でもOKウル。\n\n"

                    response += "【アクティブな目標】\n"
                    for num, goal in goal_map.items():
                        title = goal["title"][:35]
                        if goal["target_value"]:
                            response += f"  {num}. {title} ({goal['target_value']:,.0f}{goal['unit']})\n"
                        else:
                            response += f"  {num}. {title}\n"
                        if goal["period_end"]:
                            response += f"     📅 〜{goal['period_end'].strftime('%m/%d')}\n"

                    return {
                        "success": True,
                        "message": response,
                        "awaiting_input": "goal_delete_numbers",  # 番号入力待ち
                    }

                # =====================================================
                # フェーズ2: 重複一括削除
                # =====================================================
                if delete_duplicates:
                    from lib.goal import get_duplicate_goals, cancel_goals

                    duplicates = get_duplicate_goals(pool, user_id, org_id)

                    if not duplicates:
                        return {
                            "success": True,
                            "message": "✨ 重複している目標はないウル！きれいに整理されてるウル🐺"
                        }

                    if not confirmed:
                        # 確認メッセージ
                        response = "🔍 以下の重複を整理するウル。\n\n"
                        for dup in duplicates:
                            response += f"【{dup['title'][:30]}】\n"
                            response += f"  {dup['count']}件の重複 → 最新1件を残して削除\n"

                        response += "\nOKなら『削除する』と返信してウル。"

                        return {
                            "success": True,
                            "message": response,
                            "awaiting_confirmation": "goal_delete_duplicates",
                            "pending_data": {"duplicates": duplicates},
                        }

                    # 確認済み: 重複を削除（最新1件を残す）
                    total_deleted = 0
                    for dup in duplicates:
                        # 最新1件（先頭）以外を削除
                        ids_to_delete = dup["goal_ids"][1:]  # 2件目以降
                        if ids_to_delete:
                            count, _ = cancel_goals(pool, ids_to_delete, org_id, user_id, "duplicate", user_id=user_id)
                            total_deleted += count

                    return {
                        "success": True,
                        "message": f"✅ 重複を整理したウル！{total_deleted}件削除したウル🐺",
                        "next_action": "目標の進捗を報告する"
                    }

                # =====================================================
                # フェーズ3: 番号指定削除
                # =====================================================
                # 確認済みの場合、contextからpending_dataを取得
                if confirmed:
                    pending_data = context.get("pending_data", {}) if context else {}
                    goal_ids = pending_data.get("goal_ids", [])

                    if not goal_ids and not goal_numbers:
                        return {
                            "success": False,
                            "message": "🤔 削除する目標を指定してほしいウル。"
                        }

                    # goal_idsがある場合はそれを使用、なければgoal_numbersから取得
                    if not goal_ids:
                        for num in goal_numbers:
                            num_int = int(num) if isinstance(num, str) else num
                            if num_int in goal_map:
                                goal_ids.append(goal_map[num_int]["id"])

                    from lib.goal import cancel_goals

                    count, titles = cancel_goals(pool, goal_ids, org_id, user_id, "user_request", user_id=user_id)

                    response = f"✅ 削除完了ウル！{count}件の目標を整理したウル🐺\n\n"
                    response += "💡 次の一手: 新しい目標を設定する or 進捗を報告する"

                    return {
                        "success": True,
                        "message": response,
                        "next_action": "目標を設定する or 進捗を報告する"
                    }

                # 対象目標を特定（確認前）
                target_goals = []
                invalid_numbers = []
                for num in goal_numbers:
                    # 文字列・数値どちらも対応
                    num_int = int(num) if isinstance(num, str) else num
                    if num_int in goal_map:
                        target_goals.append(goal_map[num_int])
                    else:
                        invalid_numbers.append(num)

                if invalid_numbers:
                    return {
                        "success": False,
                        "message": f"🤔 {invalid_numbers} は存在しない番号ウル。もう一度確認してウル🐺"
                    }

                if not target_goals:
                    return {
                        "success": False,
                        "message": "🤔 削除する目標を指定してほしいウル。"
                    }

                # 確認メッセージ
                response = "🗑️ 以下を削除するウル。間違いない？\n\n"
                for i, goal in enumerate(target_goals, 1):
                    response += f"  {i}. {goal['title'][:40]}\n"

                response += "\nOKなら『削除する』と返信してウル。"

                return {
                    "success": True,
                    "message": response,
                    "awaiting_confirmation": "goal_delete",
                    "pending_data": {"goal_ids": [g["id"] for g in target_goals]},
                }

        except Exception as e:
            print(f"❌ handle_goal_delete エラー: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": "❌ 目標の削除に失敗したウル...もう一度試してほしいウル🐺"
            }

    def handle_goal_cleanup(
        self,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        目標整理ハンドラー（v10.56.0）

        整理メニュー提示:
        A) 重複している目標をまとめて整理
        B) 期限切れをアーカイブ
        C) 未定/相談中/新規整理

        設計書: docs/05_phase2-5_goal_achievement.md セクション5.6.2
        """
        print(f"🧹 handle_goal_cleanup 開始: room_id={room_id}, account_id={account_id}")
        log_persona_path(
            path="goal_cleanup",
            injected=False,
            addon=False,
            account_id=account_id,
            extra="direct_response",
        )

        cleanup_type = params.get("cleanup_type")  # A, B, C
        confirmed = params.get("confirmed", False)

        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                # ユーザー情報を取得
                user_result = conn.execute(
                    text("""
                        SELECT id, organization_id, name FROM users
                        WHERE chatwork_account_id = :account_id
                        LIMIT 1
                    """),
                    {"account_id": str(account_id)}
                ).fetchone()

                if not user_result:
                    return {
                        "success": False,
                        "message": "🤔 まだ目標を登録していないみたいウル！"
                    }

                user_id = str(user_result[0])
                org_id = str(user_result[1]) if user_result[1] else None
                user_name = user_result[2] or sender_name or "ユーザー"

                if not org_id:
                    return {
                        "success": False,
                        "message": "🤔 組織情報が設定されていないみたいウル！"
                    }

            from lib.goal import get_duplicate_goals, get_expired_goals, get_pending_goals, cancel_goals

            # =====================================================
            # フェーズ1: 整理メニュー表示
            # =====================================================
            if not cleanup_type:
                # 各カテゴリの件数を取得
                duplicates = get_duplicate_goals(pool, user_id, org_id)
                expired = get_expired_goals(pool, user_id, org_id)
                pending = get_pending_goals(pool, user_id, org_id)

                dup_count = sum(d["count"] - 1 for d in duplicates)  # 重複分のみ
                exp_count = len(expired)
                pend_count = len(pending)

                response = "🧹 整理方法を選んでほしいウル。\n\n"

                if dup_count > 0:
                    response += f"A) 重複している目標をまとめて整理 ({dup_count}件)\n"
                else:
                    response += f"A) 重複している目標をまとめて整理 (なし ✨)\n"

                if exp_count > 0:
                    response += f"B) 期限切れをアーカイブ ({exp_count}件)\n"
                else:
                    response += f"B) 期限切れをアーカイブ (なし ✨)\n"

                if pend_count > 0:
                    response += f"C) 未定/相談中/新規の仮置きを整理 ({pend_count}件)\n"
                else:
                    response += f"C) 未定/相談中/新規の仮置きを整理 (なし ✨)\n"

                if dup_count == 0 and exp_count == 0 and pend_count == 0:
                    response += "\n✨ 目標はきれいに整理されてるウル！すごいウル🐺"
                else:
                    response += "\nA/B/C どれからやるウル？"

                return {
                    "success": True,
                    "message": response,
                    "awaiting_input": "goal_cleanup_type",
                }

            # =====================================================
            # フェーズ2A: 重複整理
            # =====================================================
            if cleanup_type.upper() == "A":
                duplicates = get_duplicate_goals(pool, user_id, org_id)

                if not duplicates:
                    return {
                        "success": True,
                        "message": "✨ 重複している目標はないウル！"
                    }

                if not confirmed:
                    response = "🔍 以下の重複を整理するウル。\n\n"
                    for dup in duplicates:
                        response += f"【{dup['title'][:30]}】\n"
                        response += f"  {dup['count']}件 → 最新1件を残して削除\n"
                    response += "\nOKなら『OK』と返信してウル。"

                    return {
                        "success": True,
                        "message": response,
                        "awaiting_confirmation": "goal_cleanup_duplicates",
                    }

                # 実行
                total_deleted = 0
                for dup in duplicates:
                    ids_to_delete = dup["goal_ids"][1:]
                    if ids_to_delete:
                        count, _ = cancel_goals(pool, ids_to_delete, org_id, user_id, "duplicate", user_id=user_id)
                        total_deleted += count

                return {
                    "success": True,
                    "message": f"✅ 重複を整理したウル！{total_deleted}件削除したウル🐺\n\n💡 次の一手: 整理した目標の進捗を報告しようウル",
                    "next_action": "進捗を報告する"
                }

            # =====================================================
            # フェーズ2B: 期限切れ整理
            # =====================================================
            if cleanup_type.upper() == "B":
                expired = get_expired_goals(pool, user_id, org_id)

                if not expired:
                    return {
                        "success": True,
                        "message": "✨ 期限切れの目標はないウル！"
                    }

                if not confirmed:
                    response = "📅 以下の期限切れ目標をアーカイブするウル。\n\n"
                    for exp in expired[:10]:
                        days = exp["days_overdue"]
                        response += f"• {exp['title'][:30]}\n"
                        response += f"  期限: {exp['period_end']} ({days}日超過)\n"
                    if len(expired) > 10:
                        response += f"...他{len(expired) - 10}件\n"
                    response += "\nOKなら『OK』と返信してウル。"

                    return {
                        "success": True,
                        "message": response,
                        "awaiting_confirmation": "goal_cleanup_expired",
                    }

                # 実行
                goal_ids = [e["id"] for e in expired]
                count, _ = cancel_goals(pool, goal_ids, org_id, user_id, "expired", user_id=user_id)

                return {
                    "success": True,
                    "message": f"✅ 期限切れを整理したウル！{count}件アーカイブしたウル🐺\n\n💡 次の一手: 新しい目標を設定しようウル",
                    "next_action": "目標を設定する"
                }

            # =====================================================
            # フェーズ2C: 未定/相談中/新規整理
            # =====================================================
            if cleanup_type.upper() == "C":
                pending = get_pending_goals(pool, user_id, org_id)

                if not pending:
                    return {
                        "success": True,
                        "message": "✨ 仮置きの目標はないウル！"
                    }

                # 未定/相談中は削除ではなく、一覧表示して選択を促す
                response = "📝 まだ進捗がない目標があるウル。\n\n"
                for i, p in enumerate(pending[:10], 1):
                    response += f"  {i}. {p['title'][:35]}\n"
                    if p["period_end"]:
                        response += f"     📅 〜{p['period_end']}\n"

                if len(pending) > 10:
                    response += f"...他{len(pending) - 10}件\n"

                response += "\n💡 次の一手:\n"
                response += "• 進捗を報告する: 『1番の進捗は〇〇』\n"
                response += "• 削除する: 『1,2を削除』\n"
                response += "• 相談する: 『1番について相談したい』"

                return {
                    "success": True,
                    "message": response,
                    "awaiting_input": "goal_pending_action",
                }

            return {
                "success": False,
                "message": "🤔 A/B/C のどれかを選んでほしいウル。"
            }

        except Exception as e:
            print(f"❌ handle_goal_cleanup エラー: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": "❌ 目標の整理に失敗したウル...もう一度試してほしいウル🐺"
            }
