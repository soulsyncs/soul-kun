"""
Phase 2.5: 目標達成支援 - 通知サービス

★★★ v10.17.1: テストガード機能追加 ★★★
- GOAL_TEST_MODE環境変数でテストモードを有効化
- テスト時は許可されたルームIDのみに送信（管理部チャット、カズさんDM等）
- 全スケジュール関数にテストガードチェックを追加

このモジュールは以下の通知機能を提供します:
- 17:00 進捗確認 (goal_daily_check)
- 18:00 未回答リマインド (goal_daily_reminder)
- 08:00 個人フィードバック (goal_morning_feedback)
- 08:00 チームサマリー (goal_team_summary)

使用例:
    from lib.goal_notification import (
        send_daily_check_to_user,
        send_daily_reminder_to_user,
        send_morning_feedback_to_user,
        send_team_summary_to_leader,
        scheduled_daily_check,
        scheduled_daily_reminder,
        scheduled_morning_feedback,
    )
"""

import os
import re
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import pytz

# 日本時間
JST = pytz.timezone('Asia/Tokyo')

logger = logging.getLogger(__name__)


# =====================================================
# ===== ★★★ v10.17.1: テストガード設定 ★★★ =====
# =====================================================
#
# **最重要**: テスト送信は以下のみに限定すること
# 1. 管理部チャット（room_id: 405315911）→ チームサマリー等
# 2. カズさん（菊地雅克）へのDM → 個人通知テスト
#
# 他のグループチャットや個人に送信したら、業務に迷惑がかかる
# =====================================================

# テストモードフラグ（本番稼働時はFalseに変更）
# 環境変数 GOAL_TEST_MODE=true で有効化
GOAL_TEST_MODE = os.environ.get("GOAL_TEST_MODE", "").lower() in ("true", "1", "yes")

# カズさん（菊地雅克）のChatWork account_id
KAZU_CHATWORK_ACCOUNT_ID = "1728974"

# テスト送信許可リスト: ChatWork room_id
# - 管理部チャット: 405315911
# - カズさんとのDMルームは GOAL_TEST_ROOM_IDS 環境変数で追加設定
GOAL_TEST_ALLOWED_ROOM_IDS = {
    405315911,  # 管理部チャット
}

# 環境変数からテスト許可ルームIDを追加
# 例: GOAL_TEST_ROOM_IDS="123456,789012" で複数指定可能
_test_room_ids_env = os.environ.get("GOAL_TEST_ROOM_IDS", "")
if _test_room_ids_env:
    for _room_id in _test_room_ids_env.split(","):
        try:
            GOAL_TEST_ALLOWED_ROOM_IDS.add(int(_room_id.strip()))
        except ValueError:
            pass


def is_goal_test_send_allowed(chatwork_room_id: str) -> bool:
    """
    目標通知のテスト送信が許可されているか確認

    GOAL_TEST_MODE=True の場合:
    - chatwork_room_id が GOAL_TEST_ALLOWED_ROOM_IDS に含まれる → True
    - それ以外 → False（送信しない）

    GOAL_TEST_MODE=False の場合:
    - 常にTrue（本番モード）

    Args:
        chatwork_room_id: ChatWork ルームID

    Returns:
        送信許可かどうか
    """
    if not GOAL_TEST_MODE:
        return True  # 本番モードは全て許可

    try:
        room_id_int = int(chatwork_room_id)
        return room_id_int in GOAL_TEST_ALLOWED_ROOM_IDS
    except (ValueError, TypeError):
        return False


def log_goal_test_mode_status():
    """起動時にテストモードの状態をログ出力"""
    if GOAL_TEST_MODE:
        logger.warning("=" * 50)
        logger.warning("⚠️ GOAL_TEST_MODE 有効")
        logger.warning(f"   許可ルームID: {GOAL_TEST_ALLOWED_ROOM_IDS}")
        logger.warning(f"   上記以外への送信はブロックされます")
        logger.warning("=" * 50)
    else:
        logger.info("📢 GOAL_TEST_MODE=False: 本番モード（全ユーザーに送信）")


# =====================================================
# 通知タイプ定義
# =====================================================

class GoalNotificationType(str, Enum):
    """目標関連の通知タイプ"""
    DAILY_CHECK = "goal_daily_check"          # 17:00 進捗確認
    DAILY_REMINDER = "goal_daily_reminder"    # 18:00 未回答リマインド
    MORNING_FEEDBACK = "goal_morning_feedback"  # 08:00 個人フィードバック
    TEAM_SUMMARY = "goal_team_summary"        # 08:00 チームサマリー


# =====================================================
# エラーサニタイズ
# =====================================================

def sanitize_error(e: Exception) -> str:
    """
    エラーメッセージから機密情報を除去

    除去対象:
    - ファイルパス（/Users/xxx, /home/xxx など）
    - API キー・トークン
    - ユーザーID（UUID）
    - メールアドレス
    - 内部ホスト名・IP
    """
    error_str = str(e)

    # 1. ファイルパスを除去
    error_str = re.sub(r'/[^\s]+', '[PATH]', error_str)

    # 2. UUIDを除去
    error_str = re.sub(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        '[UUID]',
        error_str,
        flags=re.IGNORECASE
    )

    # 3. メールアドレスを除去
    error_str = re.sub(r'[\w.+-]+@[\w.-]+\.\w+', '[EMAIL]', error_str)

    # 4. APIキー・トークン風の文字列を除去
    error_str = re.sub(
        r'(key|token|secret|password)[\s]*[=:][\s]*[^\s]+',
        r'\1=[REDACTED]',
        error_str,
        flags=re.IGNORECASE
    )

    # 5. IPアドレスを除去
    error_str = re.sub(
        r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        '[IP]',
        error_str
    )

    # 6. ポート番号を除去 (IPの後の:port)
    error_str = re.sub(r'\[IP\]:(\d+)', '[IP]:[PORT]', error_str)

    # 7. 長すぎる場合は切り詰め
    if len(error_str) > 500:
        error_str = error_str[:500] + '...[TRUNCATED]'

    return error_str


# =====================================================
# メッセージビルダー
# =====================================================

def build_daily_check_message(user_name: str, goals: List[Dict]) -> str:
    """
    17:00 進捗確認メッセージを生成

    Args:
        user_name: ユーザー表示名
        goals: アクティブな目標リスト

    Returns:
        ChatWork送信用メッセージ
    """
    message = f"{user_name}さん、お疲れ様ウル🐺\n\n"
    message += "今日の振り返りをしようウル！\n\n"

    for i, goal in enumerate(goals, 1):
        title = goal.get('title', '目標')
        target_value = goal.get('target_value')
        current_value = goal.get('current_value', 0)
        unit = goal.get('unit', '')
        goal_type = goal.get('goal_type', 'numeric')

        if goal_type == 'numeric' and target_value:
            # 達成率を計算
            if target_value > 0:
                achievement_rate = (current_value / target_value) * 100
            else:
                achievement_rate = 0

            # 数値のフォーマット
            if unit == '円':
                target_display = _format_currency(target_value)
                current_display = _format_currency(current_value)
            else:
                target_display = f"{target_value:,.0f}"
                current_display = f"{current_value:,.0f}"

            message += f"【{title}】\n"
            message += f"├ 目標: {target_display}{unit}\n"
            message += f"├ 現在: {current_display}{unit}（達成率{achievement_rate:.0f}%）\n"
            message += f"└ 今日の実績は？（数字を入力してね）\n\n"

        elif goal_type == 'deadline':
            deadline = goal.get('deadline')
            if deadline:
                deadline_str = deadline.strftime('%m/%d') if hasattr(deadline, 'strftime') else str(deadline)
                message += f"【{title}】期限: {deadline_str}\n"
                message += f"└ 今日の進捗は？\n\n"

        elif goal_type == 'action':
            message += f"【{title}】\n"
            message += f"└ 今日はできたウル？\n\n"

    message += "【今日の選択】\n"
    message += "目標に向けて、今日どんな行動を選んだウル？\n\n"
    message += "返信で教えてほしいウル✨"

    return message


def build_daily_reminder_message(user_name: str) -> str:
    """
    18:00 未回答リマインドメッセージを生成

    Args:
        user_name: ユーザー表示名

    Returns:
        ChatWork送信用メッセージ
    """
    return f"""{user_name}さん、まだ今日の振り返りができてないウル🐺

17時に送った進捗確認、見てくれたウル？

忙しい1日だったかもしれないけど、
1分だけ時間をもらえると嬉しいウル✨

【今日の振り返り】
・目標に向けて、今日どんな行動を選んだウル？
・数字があれば、今日の実績も教えてほしいウル！

返信で教えてくれると、明日の朝フィードバックするウル💪"""


def build_morning_feedback_message(
    user_name: str,
    goals: List[Dict],
    progress_data: Dict[str, Dict],
    ai_feedback: Optional[str] = None
) -> str:
    """
    08:00 個人フィードバックメッセージを生成

    Args:
        user_name: ユーザー表示名
        goals: 目標リスト
        progress_data: 目標IDをキーとした進捗データ
        ai_feedback: AIが生成したフィードバック（オプション）

    Returns:
        ChatWork送信用メッセージ
    """
    message = f"{user_name}さん、おはようウル🐺\n\n"
    message += "【昨日の振り返り】\n"

    for goal in goals:
        goal_id = str(goal.get('id', ''))
        title = goal.get('title', '目標')
        target_value = goal.get('target_value')
        current_value = goal.get('current_value', 0)
        unit = goal.get('unit', '')
        goal_type = goal.get('goal_type', 'numeric')

        # 昨日の進捗を取得
        yesterday_progress = progress_data.get(goal_id, {})
        yesterday_value = yesterday_progress.get('value', 0) or 0

        if goal_type == 'numeric' and target_value:
            # 達成率を計算
            if target_value > 0:
                achievement_rate = (current_value / target_value) * 100
                # 前日比を計算
                prev_value = current_value - yesterday_value
                if prev_value > 0 and target_value > 0:
                    prev_rate = (prev_value / target_value) * 100
                    rate_diff = achievement_rate - prev_rate
                else:
                    rate_diff = 0
            else:
                achievement_rate = 0
                rate_diff = 0

            # 数値のフォーマット
            if unit == '円':
                yesterday_display = _format_currency(yesterday_value)
                current_display = _format_currency(current_value)
                target_display = _format_currency(target_value)
                remaining = target_value - current_value
                remaining_display = _format_currency(remaining) if remaining > 0 else "0"
            else:
                yesterday_display = f"{yesterday_value:,.0f}"
                current_display = f"{current_value:,.0f}"
                target_display = f"{target_value:,.0f}"
                remaining = target_value - current_value
                remaining_display = f"{remaining:,.0f}" if remaining > 0 else "0"

            message += f"{title}：+{yesterday_display}{unit}\n"
            message += f"月累計：{current_display}{unit} / {target_display}{unit}（達成率{achievement_rate:.0f}%）\n"

            if rate_diff > 0:
                message += f"前日比：+{rate_diff:.0f}%アップ！いい感じウル✨\n"
            elif rate_diff < 0:
                message += f"前日比：{rate_diff:.0f}%...でも大丈夫ウル💪\n"

            message += "\n"

        elif goal_type == 'deadline':
            daily_note = yesterday_progress.get('daily_note', '')
            if daily_note:
                message += f"{title}：{daily_note}\n\n"

        elif goal_type == 'action':
            daily_note = yesterday_progress.get('daily_note', '')
            if daily_note:
                message += f"{title}：{daily_note}\n\n"

    # 今日への問い
    message += "【今日への問い】\n"

    # メイン目標（最初の数値目標）から残りを計算
    main_goal = None
    for goal in goals:
        if goal.get('goal_type') == 'numeric' and goal.get('target_value'):
            main_goal = goal
            break

    if main_goal:
        target_value = main_goal.get('target_value', 0)
        current_value = main_goal.get('current_value', 0)
        unit = main_goal.get('unit', '')
        remaining = target_value - current_value

        if remaining > 0:
            if unit == '円':
                remaining_display = _format_currency(remaining)
            else:
                remaining_display = f"{remaining:,.0f}"
            message += f"あと{remaining_display}{unit}、今月中に何があれば達成できそうウル？\n\n"
        else:
            message += "目標達成おめでとうウル！次の挑戦は何にするウル？🎉\n\n"
    else:
        message += "今日はどんな1日にしたいウル？\n\n"

    # ソウルシンクスの行動指針をランダムに選択（将来的にはローテーション）
    action_principles = [
        "「理想の未来のために何をすべきか考え、行動する」",
        "「挑戦を楽しみ、その楽しさを伝える」",
        "「自分が源。自ら考え、自ら動く」",
        '「目の前の人の"その先"まで想う」',
        "「相手以上に相手の未来を信じる」",
        "「価値を生み出し、プロとして期待を超える」",
        "「事実と向き合い、未来を創る」",
        "「目の前のことに魂を込める」",
    ]

    # 日付をシードにして行動指針を選択（1日同じ指針が表示される）
    today = datetime.now(JST).date()  # CLAUDE.md: サーバーはUTCなのでJSTで日付取得
    principle_index = (today.year * 366 + today.timetuple().tm_yday) % len(action_principles)
    message += f"ソウルシンクスの行動指針\n{action_principles[principle_index]}\n\n"

    message += f"{user_name}さんなら絶対できるって、ソウルくんは信じてるウル💪🐺"

    return message


def build_team_summary_message(
    leader_name: str,
    department_name: str,
    team_members: List[Dict],
    summary_date: date
) -> str:
    """
    08:00 チームサマリーメッセージを生成

    Args:
        leader_name: リーダー表示名
        department_name: 部署名
        team_members: チームメンバーの進捗データリスト
        summary_date: サマリー対象日

    Returns:
        ChatWork送信用メッセージ
    """
    message = f"{leader_name}さん、おはようウル🐺\n\n"
    message += f"【チーム進捗サマリー】{summary_date.strftime('%m/%d')}時点\n\n"

    # 目標タイプごとにグループ化
    goals_by_type = {}
    total_target = Decimal(0)
    total_current = Decimal(0)

    for member in team_members:
        member_name = member.get('user_name', '不明')
        goals = member.get('goals', [])

        for goal in goals:
            goal_title = goal.get('title', '目標')
            goal_type = goal.get('goal_type', 'numeric')
            target_value = Decimal(str(goal.get('target_value', 0) or 0))
            current_value = Decimal(str(goal.get('current_value', 0) or 0))
            unit = goal.get('unit', '')

            # 達成率を計算
            if target_value > 0:
                achievement_rate = float(current_value / target_value * 100)
            else:
                achievement_rate = 0

            # ステータスアイコン
            if achievement_rate >= 70:
                status_icon = "📈 順調"
            elif achievement_rate >= 50:
                status_icon = "➡️ 進行中"
            else:
                status_icon = "⚠️ 要フォロー"

            # 目標タイプでグループ化
            type_key = goal_title if goal_type == 'numeric' else goal_type
            if type_key not in goals_by_type:
                goals_by_type[type_key] = {
                    'members': [],
                    'total_target': Decimal(0),
                    'total_current': Decimal(0),
                    'unit': unit,
                }

            goals_by_type[type_key]['members'].append({
                'name': member_name,
                'target': target_value,
                'current': current_value,
                'rate': achievement_rate,
                'status': status_icon,
            })

            if goal_type == 'numeric':
                goals_by_type[type_key]['total_target'] += target_value
                goals_by_type[type_key]['total_current'] += current_value
                total_target += target_value
                total_current += current_value

    # 各目標タイプごとに出力
    for goal_title, data in goals_by_type.items():
        message += f"■ {goal_title}\n"
        unit = data.get('unit', '')

        for m in data['members']:
            if unit == '円':
                current_display = _format_currency(m['current'])
                target_display = _format_currency(m['target'])
            else:
                current_display = f"{m['current']:,.0f}"
                target_display = f"{m['target']:,.0f}"

            message += f"・{m['name']}：{current_display}/{target_display}{unit}（{m['rate']:.0f}%）{m['status']}\n"

        # チーム合計
        type_total_target = data.get('total_target', Decimal(0))
        type_total_current = data.get('total_current', Decimal(0))
        if type_total_target > 0:
            type_total_rate = float(type_total_current / type_total_target * 100)
            if unit == '円':
                total_current_display = _format_currency(type_total_current)
                total_target_display = _format_currency(type_total_target)
            else:
                total_current_display = f"{type_total_current:,.0f}"
                total_target_display = f"{type_total_target:,.0f}"

            message += f"\n■ チーム合計\n"
            message += f"{total_current_display} / {total_target_display}{unit}（{type_total_rate:.0f}%）\n"

        message += "\n"

    # 気になるポイント（要フォローの人を抽出）
    needs_followup = []
    for goal_title, data in goals_by_type.items():
        for m in data['members']:
            if m['rate'] < 50:
                needs_followup.append(m['name'])

    if needs_followup:
        unique_names = list(set(needs_followup))
        message += "【気になるポイント】\n"
        for name in unique_names[:3]:  # 最大3人まで表示
            message += f"{name}さんの進捗が少し遅れ気味ウル。\n"
        message += "声かけを検討してみてほしいウル🐺\n\n"

    message += "今日もチームで頑張ろうウル💪"

    return message


def _format_currency(value: Any) -> str:
    """金額を「万円」形式でフォーマット"""
    try:
        num = float(value)
        if num >= 10000:
            return f"{num / 10000:.0f}万"
        else:
            return f"{num:,.0f}"
    except (ValueError, TypeError):
        return str(value)


# =====================================================
# 通知送信関数
# =====================================================

def send_daily_check_to_user(
    conn,
    user_id: str,
    org_id: str,
    user_name: str,
    chatwork_room_id: str,
    goals: List[Dict],
    send_message_func,
    dry_run: bool = False
) -> Tuple[str, Optional[str]]:
    """
    17:00 進捗確認を送信（ユーザー単位で集約、冪等性保証）

    Args:
        conn: データベース接続
        user_id: ユーザーID (UUID)
        org_id: 組織ID (UUID)
        user_name: ユーザー表示名
        chatwork_room_id: ChatWork ルームID
        goals: アクティブな目標リスト
        send_message_func: メッセージ送信関数
        dry_run: ドライランモード

    Returns:
        Tuple[status, error_message]
    """
    import sqlalchemy

    today = datetime.now(JST).date()  # CLAUDE.md: サーバーはUTCなのでJSTで日付取得
    notification_type = GoalNotificationType.DAILY_CHECK.value

    # dry_run: DBに記録せず早期リターン（同日の本番実行をブロックしない）
    if dry_run:
        logger.info(f"[DRY_RUN] 17時進捗確認: {user_name}さん")
        return ('skipped', 'dry_run')

    # =====================================================
    # CLAUDE.md鉄則#10: トランザクション内でAPI呼び出しをしない
    # 競合対策: INSERT ... ON CONFLICT DO UPDATE で排他制御
    # - 新規: INSERT pending
    # - 既存でfailed: UPDATE to pending（リトライ許可）
    # - 既存でpending: 10分以上古い場合のみリトライ許可（クラッシュ対策）
    # - 既存でsuccess: RETURNING なし（スキップ）
    # =====================================================

    # Phase 1: pending挿入またはfailed/stale-pendingの再試行
    result = conn.execute(sqlalchemy.text("""
        INSERT INTO notification_logs (
            organization_id, notification_type, target_type, target_id,
            notification_date, status, channel, channel_target
        )
        VALUES (:org_id, :notification_type, 'user', :user_id, :today, 'pending', 'chatwork', :room_id)
        ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
        DO UPDATE SET
            status = 'pending',
            error_message = NULL,
            updated_at = NOW()
        WHERE notification_logs.status = 'failed'
           OR (notification_logs.status = 'pending' AND notification_logs.updated_at < NOW() - INTERVAL '10 minutes')
        RETURNING id
    """), {
        'org_id': org_id,
        'notification_type': notification_type,
        'user_id': user_id,
        'today': today,
        'room_id': chatwork_room_id,
    })
    inserted = result.fetchone()
    conn.commit()  # DBロック解放

    # RETURNINGがない = 既にsuccessで送信済み、またはpendingで処理中
    if not inserted:
        logger.info(f"既に送信済みまたは処理中: user={user_id} / {notification_type}")
        return ('skipped', 'already_sent_or_processing')

    # Phase 2: メッセージ生成 + API呼び出し（DB接続を保持しない）
    message = build_daily_check_message(user_name, goals)

    status = 'pending'
    error_message = None

    try:
        send_message_func(chatwork_room_id, message)
        status = 'success'
    except Exception as e:
        status = 'failed'
        error_message = sanitize_error(e)
        logger.error(f"17時進捗確認送信エラー: user={user_id}, error={error_message}")

    # Phase 3: 最終ステータス更新
    conn.execute(sqlalchemy.text("""
        UPDATE notification_logs
        SET status = :status,
            error_message = :error_message,
            retry_count = retry_count + 1,
            updated_at = NOW()
        WHERE organization_id = CAST(:org_id AS TEXT)
          AND target_type = 'user'
          AND target_id = CAST(:user_id AS TEXT)
          AND notification_date = :today
          AND notification_type = :notification_type
    """), {
        'org_id': org_id,
        'notification_type': notification_type,
        'user_id': user_id,
        'today': today,
        'status': status,
        'error_message': error_message,
    })
    conn.commit()

    return (status, error_message)


def send_daily_reminder_to_user(
    conn,
    user_id: str,
    org_id: str,
    user_name: str,
    chatwork_room_id: str,
    send_message_func,
    dry_run: bool = False
) -> Tuple[str, Optional[str]]:
    """
    18:00 未回答リマインドを送信（受信者単位で冪等性保証）

    17時の進捗確認に未回答の人に対してのみ送信。

    Args:
        conn: データベース接続
        user_id: ユーザーID (UUID)
        org_id: 組織ID (UUID)
        user_name: ユーザー表示名
        chatwork_room_id: ChatWork ルームID
        send_message_func: メッセージ送信関数
        dry_run: ドライランモード

    Returns:
        Tuple[status, error_message]
    """
    import sqlalchemy

    today = datetime.now(JST).date()  # CLAUDE.md: サーバーはUTCなのでJSTで日付取得
    notification_type = GoalNotificationType.DAILY_REMINDER.value

    # dry_run: DBに記録せず早期リターン（同日の本番実行をブロックしない）
    if dry_run:
        logger.info(f"[DRY_RUN] 18時未回答リマインド: {user_name}さん")
        return ('skipped', 'dry_run')

    # =====================================================
    # CLAUDE.md鉄則#10: トランザクション内でAPI呼び出しをしない
    # 競合対策: INSERT ... ON CONFLICT DO UPDATE で排他制御
    # =====================================================

    # Phase 1a: 17時の進捗確認に回答済みか確認（ビジネスロジック）
    result = conn.execute(sqlalchemy.text("""
        SELECT id FROM goal_progress gp
        JOIN goals g ON gp.goal_id = g.id AND gp.organization_id = g.organization_id
        WHERE g.user_id = CAST(:user_id AS UUID)
          AND g.organization_id = CAST(:org_id AS UUID)
          AND gp.organization_id = CAST(:org_id AS UUID)
          AND gp.progress_date = :today
    """), {
        'user_id': user_id,
        'org_id': org_id,
        'today': today,
    })
    progress_today = result.fetchone()

    if progress_today:
        logger.info(f"既に回答済み: user={user_id}")
        return ('skipped', 'already_answered')

    # Phase 1b: pending挿入またはfailed/stale-pendingの再試行
    result = conn.execute(sqlalchemy.text("""
        INSERT INTO notification_logs (
            organization_id, notification_type, target_type, target_id,
            notification_date, status, channel, channel_target
        )
        VALUES (:org_id, :notification_type, 'user', :user_id, :today, 'pending', 'chatwork', :room_id)
        ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
        DO UPDATE SET
            status = 'pending',
            error_message = NULL,
            updated_at = NOW()
        WHERE notification_logs.status = 'failed'
           OR (notification_logs.status = 'pending' AND notification_logs.updated_at < NOW() - INTERVAL '10 minutes')
        RETURNING id
    """), {
        'org_id': org_id,
        'notification_type': notification_type,
        'user_id': user_id,
        'today': today,
        'room_id': chatwork_room_id,
    })
    inserted = result.fetchone()
    conn.commit()  # DBロック解放

    # RETURNINGがない = 既にsuccessで送信済み、またはpendingで処理中
    if not inserted:
        logger.info(f"既に送信済みまたは処理中: user={user_id} / {notification_type}")
        return ('skipped', 'already_sent_or_processing')

    # Phase 2: メッセージ生成 + API呼び出し（DB接続を保持しない）
    message = build_daily_reminder_message(user_name)

    status = 'pending'
    error_message = None

    try:
        send_message_func(chatwork_room_id, message)
        status = 'success'
    except Exception as e:
        status = 'failed'
        error_message = sanitize_error(e)
        logger.error(f"18時リマインド送信エラー: user={user_id}, error={error_message}")

    # Phase 3: 最終ステータス更新
    conn.execute(sqlalchemy.text("""
        UPDATE notification_logs
        SET status = :status,
            error_message = :error_message,
            retry_count = retry_count + 1,
            updated_at = NOW()
        WHERE organization_id = CAST(:org_id AS TEXT)
          AND target_type = 'user'
          AND target_id = CAST(:user_id AS TEXT)
          AND notification_date = :today
          AND notification_type = :notification_type
    """), {
        'org_id': org_id,
        'notification_type': notification_type,
        'user_id': user_id,
        'today': today,
        'status': status,
        'error_message': error_message,
    })
    conn.commit()

    return (status, error_message)


def send_morning_feedback_to_user(
    conn,
    user_id: str,
    org_id: str,
    user_name: str,
    chatwork_room_id: str,
    goals: List[Dict],
    progress_data: Dict[str, Dict],
    send_message_func,
    dry_run: bool = False
) -> Tuple[str, Optional[str]]:
    """
    08:00 個人フィードバックを送信

    Args:
        conn: データベース接続
        user_id: ユーザーID (UUID)
        org_id: 組織ID (UUID)
        user_name: ユーザー表示名
        chatwork_room_id: ChatWork ルームID
        goals: 目標リスト
        progress_data: 昨日の進捗データ
        send_message_func: メッセージ送信関数
        dry_run: ドライランモード

    Returns:
        Tuple[status, error_message]
    """
    import sqlalchemy

    today = datetime.now(JST).date()  # CLAUDE.md: サーバーはUTCなのでJSTで日付取得
    notification_type = GoalNotificationType.MORNING_FEEDBACK.value

    # dry_run: DBに記録せず早期リターン（同日の本番実行をブロックしない）
    if dry_run:
        logger.info(f"[DRY_RUN] 8時フィードバック: {user_name}さん")
        return ('skipped', 'dry_run')

    # =====================================================
    # CLAUDE.md鉄則#10: トランザクション内でAPI呼び出しをしない
    # 競合対策: INSERT ... ON CONFLICT DO UPDATE で排他制御
    # =====================================================

    # Phase 1: pending挿入またはfailed/stale-pendingの再試行
    result = conn.execute(sqlalchemy.text("""
        INSERT INTO notification_logs (
            organization_id, notification_type, target_type, target_id,
            notification_date, status, channel, channel_target
        )
        VALUES (:org_id, :notification_type, 'user', :user_id, :today, 'pending', 'chatwork', :room_id)
        ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
        DO UPDATE SET
            status = 'pending',
            error_message = NULL,
            updated_at = NOW()
        WHERE notification_logs.status = 'failed'
           OR (notification_logs.status = 'pending' AND notification_logs.updated_at < NOW() - INTERVAL '10 minutes')
        RETURNING id
    """), {
        'org_id': org_id,
        'notification_type': notification_type,
        'user_id': user_id,
        'today': today,
        'room_id': chatwork_room_id,
    })
    inserted = result.fetchone()
    conn.commit()  # DBロック解放

    # RETURNINGがない = 既にsuccessで送信済み、またはpendingで処理中
    if not inserted:
        logger.info(f"既に送信済みまたは処理中: user={user_id} / {notification_type}")
        return ('skipped', 'already_sent_or_processing')

    # Phase 2: メッセージ生成 + API呼び出し（DB接続を保持しない）
    message = build_morning_feedback_message(user_name, goals, progress_data)

    status = 'pending'
    error_message = None

    try:
        send_message_func(chatwork_room_id, message)
        status = 'success'
    except Exception as e:
        status = 'failed'
        error_message = sanitize_error(e)
        logger.error(f"8時フィードバック送信エラー: user={user_id}, error={error_message}")

    # Phase 3: 最終ステータス更新
    conn.execute(sqlalchemy.text("""
        UPDATE notification_logs
        SET status = :status,
            error_message = :error_message,
            retry_count = retry_count + 1,
            updated_at = NOW()
        WHERE organization_id = CAST(:org_id AS TEXT)
          AND target_type = 'user'
          AND target_id = CAST(:user_id AS TEXT)
          AND notification_date = :today
          AND notification_type = :notification_type
    """), {
        'org_id': org_id,
        'notification_type': notification_type,
        'user_id': user_id,
        'today': today,
        'status': status,
        'error_message': error_message,
    })
    conn.commit()

    return (status, error_message)


def send_team_summary_to_leader(
    conn,
    recipient_id: str,
    org_id: str,
    leader_name: str,
    department_id: str,
    department_name: str,
    chatwork_room_id: str,
    team_members: List[Dict],
    send_message_func,
    dry_run: bool = False
) -> Tuple[str, Optional[str]]:
    """
    08:00 チームサマリーを送信（受信者単位で冪等性保証）

    Args:
        conn: データベース接続
        recipient_id: 受信者ユーザーID (UUID)
        org_id: 組織ID (UUID)
        leader_name: リーダー表示名
        department_id: 部署ID (UUID)
        department_name: 部署名
        chatwork_room_id: ChatWork ルームID
        team_members: チームメンバーの進捗データリスト
        send_message_func: メッセージ送信関数
        dry_run: ドライランモード

    Returns:
        Tuple[status, error_message]
    """
    import sqlalchemy
    import json

    today = datetime.now(JST).date()  # CLAUDE.md: サーバーはUTCなのでJSTで日付取得
    yesterday = today - timedelta(days=1)
    notification_type = GoalNotificationType.TEAM_SUMMARY.value

    # dry_run: DBに記録せず早期リターン（同日の本番実行をブロックしない）
    if dry_run:
        logger.info(f"[DRY_RUN] チームサマリー: {leader_name}さん（{department_name}）")
        return ('skipped', 'dry_run')

    # =====================================================
    # CLAUDE.md鉄則#10: トランザクション内でAPI呼び出しをしない
    # 競合対策: INSERT ... ON CONFLICT DO UPDATE で排他制御
    # =====================================================

    # Phase 1: pending挿入またはfailed/stale-pendingの再試行
    metadata_json = json.dumps({"department_id": department_id, "department_name": department_name})
    result = conn.execute(sqlalchemy.text("""
        INSERT INTO notification_logs (
            organization_id, notification_type, target_type, target_id,
            notification_date, status, channel, channel_target, metadata
        )
        VALUES (:org_id, :notification_type, 'user', :recipient_id, :today, 'pending', 'chatwork', :room_id, :metadata::jsonb)
        ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
        DO UPDATE SET
            status = 'pending',
            error_message = NULL,
            updated_at = NOW()
        WHERE notification_logs.status = 'failed'
           OR (notification_logs.status = 'pending' AND notification_logs.updated_at < NOW() - INTERVAL '10 minutes')
        RETURNING id
    """), {
        'org_id': org_id,
        'notification_type': notification_type,
        'recipient_id': recipient_id,
        'today': today,
        'room_id': chatwork_room_id,
        'metadata': metadata_json,
    })
    inserted = result.fetchone()
    conn.commit()  # DBロック解放

    # RETURNINGがない = 既にsuccessで送信済み、またはpendingで処理中
    if not inserted:
        logger.info(f"既に送信済みまたは処理中: recipient={recipient_id} / {notification_type}")
        return ('skipped', 'already_sent_or_processing')

    # Phase 2: メッセージ生成 + API呼び出し（DB接続を保持しない）
    message = build_team_summary_message(leader_name, department_name, team_members, yesterday)

    status = 'pending'
    error_message = None

    try:
        send_message_func(chatwork_room_id, message)
        status = 'success'
    except Exception as e:
        status = 'failed'
        error_message = sanitize_error(e)
        logger.error(f"チームサマリー送信エラー: recipient={recipient_id}, error={error_message}")

    # Phase 3: 最終ステータス更新
    conn.execute(sqlalchemy.text("""
        UPDATE notification_logs
        SET status = :status,
            error_message = :error_message,
            retry_count = retry_count + 1,
            updated_at = NOW()
        WHERE organization_id = CAST(:org_id AS TEXT)
          AND target_type = 'user'
          AND target_id = CAST(:recipient_id AS TEXT)
          AND notification_date = :today
          AND notification_type = :notification_type
    """), {
        'org_id': org_id,
        'notification_type': notification_type,
        'recipient_id': recipient_id,
        'today': today,
        'status': status,
        'error_message': error_message,
    })

    # =====================================================
    # CLAUDE.md鉄則#3: confidential以上の操作では監査ログを記録
    # チームサマリーは他ユーザーの目標データを閲覧する機密操作
    # =====================================================
    if status == 'success' and team_members:
        viewed_user_ids = [m.get('user_id') for m in team_members if m.get('user_id')]
        audit_details = json.dumps({
            "action": "view_team_goals",
            "department_id": department_id,
            "department_name": department_name,
            "viewed_user_count": len(team_members),
            "viewed_user_ids": viewed_user_ids[:10],
        }, ensure_ascii=False)

        try:
            conn.execute(sqlalchemy.text("""
                INSERT INTO audit_logs (
                    organization_id, user_id, action, resource_type,
                    resource_id, classification, details, created_at
                ) VALUES (
                    :org_id, :user_id, 'read', 'goal_progress',
                    :resource_id, 'confidential',
                    :details::jsonb, CURRENT_TIMESTAMP
                )
            """), {
                'org_id': org_id,
                'user_id': recipient_id,
                'resource_id': f"team_summary_{department_id}_{today}",
                'details': audit_details,
            })
        except Exception as audit_error:
            logger.warning(f"監査ログ記録エラー（non-blocking）: {audit_error}")

    conn.commit()

    return (status, error_message)


# =====================================================
# スケジュール関数（Cloud Scheduler から呼び出し）
# =====================================================

def scheduled_daily_check(conn, org_id: str, send_message_func, dry_run: bool = False) -> Dict[str, int]:
    """
    17:00 進捗確認の一括送信

    Args:
        conn: データベース接続
        org_id: 組織ID (UUID)
        send_message_func: メッセージ送信関数
        dry_run: ドライランモード

    Returns:
        送信結果のサマリー
    """
    import sqlalchemy

    logger.info(f"=== 17時進捗確認 開始 (org={org_id}) ===")
    log_goal_test_mode_status()  # テストモード状態をログ出力

    results = {'success': 0, 'skipped': 0, 'failed': 0, 'blocked': 0}

    # アクティブな目標を持つユーザーを取得（テナント分離: users, goalsの両方でorg_idフィルタ）
    result = conn.execute(sqlalchemy.text("""
        SELECT DISTINCT
            u.id AS user_id,
            u.name AS user_name,
            u.chatwork_room_id
        FROM users u
        JOIN goals g ON g.user_id = u.id AND g.organization_id = CAST(:org_id AS UUID)
        WHERE u.organization_id = CAST(:org_id AS TEXT)
          AND g.organization_id = CAST(:org_id AS UUID)
          AND g.status = 'active'
          AND u.chatwork_room_id IS NOT NULL
    """), {'org_id': org_id})

    users = result.fetchall()
    logger.info(f"対象ユーザー: {len(users)}名")

    for user in users:
        user_id = str(user[0])
        user_name = user[1]
        chatwork_room_id = user[2]

        # ★★★ テストガード: 許可されていないルームへの送信をブロック ★★★
        if not is_goal_test_send_allowed(chatwork_room_id):
            logger.info(f"🚫 [TEST_GUARD] 送信をブロック: {user_name}さん (room_id={chatwork_room_id})")
            results['blocked'] = results.get('blocked', 0) + 1
            continue

        # ユーザーのアクティブな目標を取得
        goals_result = conn.execute(sqlalchemy.text("""
            SELECT id, title, goal_type, target_value, current_value, unit, deadline
            FROM goals
            WHERE user_id = CAST(:user_id AS UUID)
              AND organization_id = CAST(:org_id AS UUID)
              AND status = 'active'
            ORDER BY created_at
        """), {'user_id': user_id, 'org_id': org_id})

        goals = []
        for g in goals_result.fetchall():
            goals.append({
                'id': str(g[0]),
                'title': g[1],
                'goal_type': g[2],
                'target_value': float(g[3]) if g[3] else None,
                'current_value': float(g[4]) if g[4] else 0,
                'unit': g[5],
                'deadline': g[6],
            })

        if not goals:
            logger.info(f"目標なし: {user_name}さん")
            continue

        # 送信
        status, error = send_daily_check_to_user(
            conn=conn,
            user_id=user_id,
            org_id=org_id,
            user_name=user_name,
            chatwork_room_id=chatwork_room_id,
            goals=goals,
            send_message_func=send_message_func,
            dry_run=dry_run,
        )

        results[status] = results.get(status, 0) + 1

    logger.info(f"=== 17時進捗確認 完了: success={results['success']}, skipped={results['skipped']}, failed={results['failed']}, blocked={results.get('blocked', 0)} ===")
    return results


def scheduled_daily_reminder(conn, org_id: str, send_message_func, dry_run: bool = False) -> Dict[str, int]:
    """
    18:00 未回答リマインドの一括送信

    Args:
        conn: データベース接続
        org_id: 組織ID (UUID)
        send_message_func: メッセージ送信関数
        dry_run: ドライランモード

    Returns:
        送信結果のサマリー
    """
    import sqlalchemy

    logger.info(f"=== 18時未回答リマインド 開始 (org={org_id}) ===")
    log_goal_test_mode_status()  # テストモード状態をログ出力

    results = {'success': 0, 'skipped': 0, 'failed': 0, 'blocked': 0}

    # アクティブな目標を持つユーザーを取得（テナント分離: users, goalsの両方でorg_idフィルタ）
    result = conn.execute(sqlalchemy.text("""
        SELECT DISTINCT
            u.id AS user_id,
            u.name AS user_name,
            u.chatwork_room_id
        FROM users u
        JOIN goals g ON g.user_id = u.id AND g.organization_id = CAST(:org_id AS UUID)
        WHERE u.organization_id = CAST(:org_id AS TEXT)
          AND g.organization_id = CAST(:org_id AS UUID)
          AND g.status = 'active'
          AND u.chatwork_room_id IS NOT NULL
    """), {'org_id': org_id})

    users = result.fetchall()
    logger.info(f"対象ユーザー: {len(users)}名")

    for user in users:
        user_id = str(user[0])
        user_name = user[1]
        chatwork_room_id = user[2]

        # ★★★ テストガード: 許可されていないルームへの送信をブロック ★★★
        if not is_goal_test_send_allowed(chatwork_room_id):
            logger.info(f"🚫 [TEST_GUARD] 送信をブロック: {user_name}さん (room_id={chatwork_room_id})")
            results['blocked'] = results.get('blocked', 0) + 1
            continue

        # 送信
        status, error = send_daily_reminder_to_user(
            conn=conn,
            user_id=user_id,
            org_id=org_id,
            user_name=user_name,
            chatwork_room_id=chatwork_room_id,
            send_message_func=send_message_func,
            dry_run=dry_run,
        )

        results[status] = results.get(status, 0) + 1

    logger.info(f"=== 18時未回答リマインド 完了: success={results['success']}, skipped={results['skipped']}, failed={results['failed']}, blocked={results.get('blocked', 0)} ===")
    return results


def scheduled_morning_feedback(conn, org_id: str, send_message_func, dry_run: bool = False) -> Dict[str, int]:
    """
    08:00 朝フィードバックの一括送信（個人フィードバック + チームサマリー）

    Args:
        conn: データベース接続
        org_id: 組織ID (UUID)
        send_message_func: メッセージ送信関数
        dry_run: ドライランモード

    Returns:
        送信結果のサマリー
    """
    import sqlalchemy

    logger.info(f"=== 8時朝フィードバック 開始 (org={org_id}) ===")
    log_goal_test_mode_status()  # テストモード状態をログ出力

    results = {'success': 0, 'skipped': 0, 'failed': 0, 'blocked': 0}
    today = datetime.now(JST).date()  # CLAUDE.md: サーバーはUTCなのでJSTで日付取得
    yesterday = today - timedelta(days=1)

    # =====================================================
    # 1. 個人フィードバック
    # =====================================================

    # 昨日進捗報告をしたユーザーを取得
    # テナント分離: users, goals, goal_progressの全てでorg_idフィルタ
    result = conn.execute(sqlalchemy.text("""
        SELECT DISTINCT
            u.id AS user_id,
            u.name AS user_name,
            u.chatwork_room_id
        FROM users u
        JOIN goal_progress gp ON gp.organization_id = CAST(:org_id AS UUID)
        JOIN goals g ON gp.goal_id = g.id AND g.user_id = u.id AND g.organization_id = CAST(:org_id AS UUID)
        WHERE u.organization_id = CAST(:org_id AS TEXT)
          AND g.organization_id = CAST(:org_id AS UUID)
          AND gp.organization_id = CAST(:org_id AS UUID)
          AND gp.progress_date = :yesterday
          AND u.chatwork_room_id IS NOT NULL
    """), {'org_id': org_id, 'yesterday': yesterday})

    users = result.fetchall()
    logger.info(f"個人フィードバック対象: {len(users)}名")

    for user in users:
        user_id = str(user[0])
        user_name = user[1]
        chatwork_room_id = user[2]

        # ★★★ テストガード: 許可されていないルームへの送信をブロック ★★★
        if not is_goal_test_send_allowed(chatwork_room_id):
            logger.info(f"🚫 [TEST_GUARD] 送信をブロック: {user_name}さん (room_id={chatwork_room_id})")
            results['blocked'] = results.get('blocked', 0) + 1
            continue

        # ユーザーの目標を取得
        goals_result = conn.execute(sqlalchemy.text("""
            SELECT id, title, goal_type, target_value, current_value, unit, deadline
            FROM goals
            WHERE user_id = CAST(:user_id AS UUID)
              AND organization_id = CAST(:org_id AS UUID)
              AND status = 'active'
            ORDER BY created_at
        """), {'user_id': user_id, 'org_id': org_id})

        goals = []
        for g in goals_result.fetchall():
            goals.append({
                'id': str(g[0]),
                'title': g[1],
                'goal_type': g[2],
                'target_value': float(g[3]) if g[3] else None,
                'current_value': float(g[4]) if g[4] else 0,
                'unit': g[5],
                'deadline': g[6],
            })

        # 昨日の進捗データを取得
        # テナント分離: goals, goal_progressの両方でorg_idフィルタ
        progress_result = conn.execute(sqlalchemy.text("""
            SELECT gp.goal_id, gp.value, gp.cumulative_value, gp.daily_note, gp.daily_choice
            FROM goal_progress gp
            JOIN goals g ON gp.goal_id = g.id AND gp.organization_id = g.organization_id
            WHERE g.user_id = CAST(:user_id AS UUID)
              AND g.organization_id = CAST(:org_id AS UUID)
              AND gp.organization_id = CAST(:org_id AS UUID)
              AND gp.progress_date = :yesterday
        """), {'user_id': user_id, 'org_id': org_id, 'yesterday': yesterday})

        progress_data = {}
        for p in progress_result.fetchall():
            progress_data[str(p[0])] = {
                'value': float(p[1]) if p[1] else 0,
                'cumulative_value': float(p[2]) if p[2] else 0,
                'daily_note': p[3],
                'daily_choice': p[4],
            }

        # 送信
        status, error = send_morning_feedback_to_user(
            conn=conn,
            user_id=user_id,
            org_id=org_id,
            user_name=user_name,
            chatwork_room_id=chatwork_room_id,
            goals=goals,
            progress_data=progress_data,
            send_message_func=send_message_func,
            dry_run=dry_run,
        )

        results[status] = results.get(status, 0) + 1

    # =====================================================
    # 2. チームサマリー（チームリーダー・部長向け）
    # =====================================================

    # サマリー受信者（チームリーダー・部長）を取得
    # テナント分離: users, user_departments, departmentsでorg_idフィルタ
    # 注: rolesはシステム共通マスタテーブル（organization_idなし）のため除外
    result = conn.execute(sqlalchemy.text("""
        SELECT DISTINCT
            u.id AS user_id,
            u.name AS user_name,
            u.chatwork_room_id,
            d.id AS department_id,
            d.name AS department_name
        FROM users u
        JOIN user_departments ud ON ud.user_id = u.id
        JOIN departments d ON ud.department_id = d.id AND d.organization_id = CAST(:org_id AS TEXT)
        JOIN roles r ON ud.role_id = r.id
        WHERE u.organization_id = CAST(:org_id AS TEXT)
          
          AND d.organization_id = CAST(:org_id AS TEXT)
          AND r.name IN ('チームリーダー', '部長', '経営', '代表')
          AND u.chatwork_room_id IS NOT NULL
    """), {'org_id': org_id})

    leaders = result.fetchall()
    logger.info(f"チームサマリー対象リーダー: {len(leaders)}名")

    for leader in leaders:
        leader_id = str(leader[0])
        leader_name = leader[1]
        chatwork_room_id = leader[2]
        department_id = str(leader[3])
        department_name = leader[4]

        # ★★★ テストガード: 許可されていないルームへの送信をブロック ★★★
        if not is_goal_test_send_allowed(chatwork_room_id):
            logger.info(f"🚫 [TEST_GUARD] チームサマリー送信をブロック: {leader_name}さん (room_id={chatwork_room_id})")
            results['blocked'] = results.get('blocked', 0) + 1
            continue

        # 部署メンバーの進捗を取得（テナント分離: 全テーブルでorg_idフィルタ）
        members_result = conn.execute(sqlalchemy.text("""
            SELECT
                u.id AS user_id,
                u.name AS user_name,
                g.id AS goal_id,
                g.title,
                g.goal_type,
                g.target_value,
                g.current_value,
                g.unit
            FROM users u
            JOIN user_departments ud ON ud.user_id = u.id
            JOIN goals g ON g.user_id = u.id AND g.organization_id = CAST(:org_id AS UUID)
            WHERE u.organization_id = CAST(:org_id AS TEXT)
              
              AND ud.department_id = CAST(:department_id AS UUID)
              AND g.organization_id = CAST(:org_id AS UUID)
              AND g.status = 'active'
            ORDER BY u.name, g.created_at
        """), {'department_id': department_id, 'org_id': org_id})

        # メンバーデータを整形
        team_members = {}
        for m in members_result.fetchall():
            member_id = str(m[0])
            if member_id not in team_members:
                team_members[member_id] = {
                    'user_id': member_id,
                    'user_name': m[1],
                    'goals': [],
                }
            team_members[member_id]['goals'].append({
                'id': str(m[2]),
                'title': m[3],
                'goal_type': m[4],
                'target_value': float(m[5]) if m[5] else None,
                'current_value': float(m[6]) if m[6] else 0,
                'unit': m[7],
            })

        team_members_list = list(team_members.values())

        if not team_members_list:
            logger.info(f"チームメンバーなし: {leader_name}さん（{department_name}）")
            continue

        # 送信
        status, error = send_team_summary_to_leader(
            conn=conn,
            recipient_id=leader_id,
            org_id=org_id,
            leader_name=leader_name,
            department_id=department_id,
            department_name=department_name,
            chatwork_room_id=chatwork_room_id,
            team_members=team_members_list,
            send_message_func=send_message_func,
            dry_run=dry_run,
        )

        results[status] = results.get(status, 0) + 1

    logger.info(f"=== 8時朝フィードバック 完了: success={results['success']}, skipped={results['skipped']}, failed={results['failed']}, blocked={results.get('blocked', 0)} ===")
    return results


# =====================================================
# 3日連続未回答通知
# =====================================================

def build_consecutive_unanswered_alert_message(
    leader_name: str,
    unanswered_members: List[Dict],
    consecutive_days: int = 3
) -> str:
    """
    3日連続未回答者のアラートメッセージを生成

    Args:
        leader_name: リーダー表示名
        unanswered_members: 未回答メンバーリスト
        consecutive_days: 連続未回答日数

    Returns:
        ChatWork送信用メッセージ
    """
    message = f"{leader_name}さん、お知らせウル🐺\n\n"
    message += f"【{consecutive_days}日連続未回答のメンバー】\n\n"

    for member in unanswered_members:
        member_name = member.get('user_name', '不明')
        last_response_date = member.get('last_response_date')

        if last_response_date:
            last_date_str = last_response_date.strftime('%m/%d') if hasattr(last_response_date, 'strftime') else str(last_response_date)
            message += f"・{member_name}さん（最終回答: {last_date_str}）\n"
        else:
            message += f"・{member_name}さん（回答履歴なし）\n"

    message += "\n忙しいのかもしれないけど、\n"
    message += "声かけを検討してほしいウル🐺\n\n"
    message += "「何か困ってることはない？」\n"
    message += "「目標の進め方で相談があれば聞くよ」\n"
    message += "みたいな感じで話しかけてみてほしいウル✨\n\n"
    message += "ソウルくんは、みんなが目標に向かって\n"
    message += "一緒に頑張れることを願ってるウル💪"

    return message


def check_consecutive_unanswered_users(
    conn,
    org_id: str,
    consecutive_days: int = 3
) -> List[Dict]:
    """
    連続未回答ユーザーを検出

    Args:
        conn: データベース接続
        org_id: 組織ID
        consecutive_days: 連続未回答日数の閾値

    Returns:
        未回答ユーザーリスト（リーダー情報付き）
    """
    import sqlalchemy

    today = datetime.now(JST).date()  # CLAUDE.md: サーバーはUTCなのでJSTで日付取得
    check_start_date = today - timedelta(days=consecutive_days)

    # アクティブな目標を持つユーザーで、指定日数以内に進捗報告がないユーザーを取得
    # テナント分離: users, goals, user_departments, departments, goal_progressの全てでorg_idフィルタ
    result = conn.execute(sqlalchemy.text("""
        WITH users_with_goals AS (
            SELECT DISTINCT
                u.id AS user_id,
                u.name AS user_name,
                u.chatwork_room_id,
                ud.department_id,
                d.name AS department_name
            FROM users u
            JOIN goals g ON g.user_id = u.id AND g.organization_id = CAST(:org_id AS UUID)
            LEFT JOIN user_departments ud ON ud.user_id = u.id
            LEFT JOIN departments d ON ud.department_id = d.id AND d.organization_id = CAST(:org_id AS TEXT)
            WHERE u.organization_id = CAST(:org_id AS TEXT)
              AND g.organization_id = CAST(:org_id AS UUID)
              AND g.status = 'active'
              AND u.chatwork_room_id IS NOT NULL
        ),
        last_progress AS (
            SELECT
                g.user_id,
                MAX(gp.progress_date) AS last_response_date
            FROM goal_progress gp
            JOIN goals g ON gp.goal_id = g.id AND gp.organization_id = g.organization_id
            WHERE g.organization_id = CAST(:org_id AS UUID)
              AND gp.organization_id = CAST(:org_id AS UUID)
            GROUP BY g.user_id
        )
        SELECT
            uwg.user_id,
            uwg.user_name,
            uwg.chatwork_room_id,
            uwg.department_id,
            uwg.department_name,
            lp.last_response_date
        FROM users_with_goals uwg
        LEFT JOIN last_progress lp ON lp.user_id = uwg.user_id
        WHERE lp.last_response_date IS NULL
           OR lp.last_response_date <= :check_start_date
        ORDER BY uwg.department_name, uwg.user_name
    """), {
        'org_id': org_id,
        'check_start_date': check_start_date,
    })

    unanswered_users = []
    for row in result.fetchall():
        unanswered_users.append({
            'user_id': str(row[0]),
            'user_name': row[1],
            'chatwork_room_id': row[2],
            'department_id': str(row[3]) if row[3] else None,
            'department_name': row[4],
            'last_response_date': row[5],
        })

    return unanswered_users


def send_consecutive_unanswered_alert_to_leader(
    conn,
    leader_id: str,
    org_id: str,
    leader_name: str,
    chatwork_room_id: str,
    unanswered_members: List[Dict],
    consecutive_days: int,
    send_message_func,
    dry_run: bool = False
) -> Tuple[str, Optional[str]]:
    """
    3日連続未回答アラートをリーダーに送信

    Args:
        conn: データベース接続
        leader_id: リーダーユーザーID
        org_id: 組織ID
        leader_name: リーダー表示名
        chatwork_room_id: ChatWork ルームID
        unanswered_members: 未回答メンバーリスト
        consecutive_days: 連続未回答日数
        send_message_func: メッセージ送信関数
        dry_run: ドライランモード

    Returns:
        Tuple[status, error_message]
    """
    import sqlalchemy
    import json

    today = datetime.now(JST).date()  # CLAUDE.md: サーバーはUTCなのでJSTで日付取得
    notification_type = "goal_consecutive_unanswered"

    # dry_run: DBに記録せず早期リターン（同日の本番実行をブロックしない）
    if dry_run:
        logger.info(f"[DRY_RUN] 連続未回答アラート: {leader_name}さん（{len(unanswered_members)}名）")
        return ('skipped', 'dry_run')

    # =====================================================
    # CLAUDE.md鉄則#10: トランザクション内でAPI呼び出しをしない
    # 競合対策: INSERT ... ON CONFLICT DO UPDATE で排他制御
    # =====================================================

    # Phase 1: pending挿入またはfailed/stale-pendingの再試行
    member_ids = [m['user_id'] for m in unanswered_members]
    metadata_json = json.dumps({
        "consecutive_days": consecutive_days,
        "member_count": len(unanswered_members),
        "member_ids": member_ids
    })
    result = conn.execute(sqlalchemy.text("""
        INSERT INTO notification_logs (
            organization_id, notification_type, target_type, target_id,
            notification_date, status, channel, channel_target, metadata
        )
        VALUES (:org_id, :notification_type, 'user', :leader_id, :today, 'pending', 'chatwork', :room_id, :metadata::jsonb)
        ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
        DO UPDATE SET
            status = 'pending',
            error_message = NULL,
            updated_at = NOW()
        WHERE notification_logs.status = 'failed'
           OR (notification_logs.status = 'pending' AND notification_logs.updated_at < NOW() - INTERVAL '10 minutes')
        RETURNING id
    """), {
        'org_id': org_id,
        'notification_type': notification_type,
        'leader_id': leader_id,
        'today': today,
        'room_id': chatwork_room_id,
        'metadata': metadata_json,
    })
    inserted = result.fetchone()
    conn.commit()  # DBロック解放

    # RETURNINGがない = 既にsuccessで送信済み、またはpendingで処理中
    if not inserted:
        logger.info(f"既に送信済みまたは処理中: leader={leader_id} / {notification_type}")
        return ('skipped', 'already_sent_or_processing')

    # Phase 2: メッセージ生成 + API呼び出し（DB接続を保持しない）
    message = build_consecutive_unanswered_alert_message(
        leader_name, unanswered_members, consecutive_days
    )

    status = 'pending'
    error_message = None

    try:
        send_message_func(chatwork_room_id, message)
        status = 'success'
    except Exception as e:
        status = 'failed'
        error_message = sanitize_error(e)
        logger.error(f"連続未回答アラート送信エラー: leader={leader_id}, error={error_message}")

    # Phase 3: 最終ステータス更新
    conn.execute(sqlalchemy.text("""
        UPDATE notification_logs
        SET status = :status,
            error_message = :error_message,
            retry_count = retry_count + 1,
            updated_at = NOW()
        WHERE organization_id = CAST(:org_id AS TEXT)
          AND target_type = 'user'
          AND target_id = CAST(:leader_id AS TEXT)
          AND notification_date = :today
          AND notification_type = :notification_type
    """), {
        'org_id': org_id,
        'notification_type': notification_type,
        'leader_id': leader_id,
        'today': today,
        'status': status,
        'error_message': error_message,
    })

    # =====================================================
    # CLAUDE.md鉄則#3: confidential以上の操作では監査ログを記録
    # 連続未回答アラートは他ユーザーの回答状況を閲覧する機密操作
    # =====================================================
    if status == 'success' and unanswered_members:
        viewed_user_ids = [m.get('user_id') for m in unanswered_members if m.get('user_id')]
        audit_details = json.dumps({
            "action": "view_consecutive_unanswered",
            "consecutive_days": consecutive_days,
            "viewed_user_count": len(unanswered_members),
            "viewed_user_ids": viewed_user_ids[:10],
        }, ensure_ascii=False)

        try:
            conn.execute(sqlalchemy.text("""
                INSERT INTO audit_logs (
                    organization_id, user_id, action, resource_type,
                    resource_id, classification, details, created_at
                ) VALUES (
                    :org_id, :user_id, 'read', 'goal_progress',
                    :resource_id, 'confidential',
                    :details::jsonb, CURRENT_TIMESTAMP
                )
            """), {
                'org_id': org_id,
                'user_id': leader_id,
                'resource_id': f"unanswered_alert_{consecutive_days}days_{today}",
                'details': audit_details,
            })
        except Exception as audit_error:
            logger.warning(f"監査ログ記録エラー（non-blocking）: {audit_error}")

    conn.commit()

    return (status, error_message)


def scheduled_consecutive_unanswered_check(
    conn,
    org_id: str,
    send_message_func,
    consecutive_days: int = 3,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    3日連続未回答チェックの一括実行

    Args:
        conn: データベース接続
        org_id: 組織ID
        send_message_func: メッセージ送信関数
        consecutive_days: 連続未回答日数の閾値
        dry_run: ドライランモード

    Returns:
        送信結果のサマリー
    """
    import sqlalchemy

    logger.info(f"=== {consecutive_days}日連続未回答チェック 開始 (org={org_id}) ===")
    log_goal_test_mode_status()  # テストモード状態をログ出力

    results = {'success': 0, 'skipped': 0, 'failed': 0, 'blocked': 0}

    # 連続未回答ユーザーを取得
    unanswered_users = check_consecutive_unanswered_users(conn, org_id, consecutive_days)

    if not unanswered_users:
        logger.info("連続未回答ユーザーなし")
        return results

    logger.info(f"連続未回答ユーザー: {len(unanswered_users)}名")

    # 部署ごとにグループ化
    by_department = {}
    for user in unanswered_users:
        dept_id = user.get('department_id') or 'no_department'
        if dept_id not in by_department:
            by_department[dept_id] = {
                'department_name': user.get('department_name') or '部署なし',
                'members': [],
            }
        by_department[dept_id]['members'].append(user)

    # 各部署のリーダーに通知
    for dept_id, dept_data in by_department.items():
        if dept_id == 'no_department':
            # 部署なしの場合は管理者に通知（後で実装）
            continue

        # 部署のリーダーを取得
        # テナント分離: users, user_departmentsでorg_idフィルタ
        # 注: rolesはシステム共通マスタテーブル（organization_idなし）のため除外
        leaders_result = conn.execute(sqlalchemy.text("""
            SELECT
                u.id AS user_id,
                u.name AS user_name,
                u.chatwork_room_id
            FROM users u
            JOIN user_departments ud ON ud.user_id = u.id
            JOIN roles r ON ud.role_id = r.id
            WHERE ud.department_id = CAST(:department_id AS UUID)
              AND u.organization_id = CAST(:org_id AS TEXT)
              
              AND r.name IN ('チームリーダー', '部長', '経営', '代表')
              AND u.chatwork_room_id IS NOT NULL
        """), {'department_id': dept_id, 'org_id': org_id})

        leaders = leaders_result.fetchall()

        if not leaders:
            logger.info(f"部署 {dept_data['department_name']} にリーダーなし")
            continue

        for leader in leaders:
            leader_id = str(leader[0])
            leader_name = leader[1]
            chatwork_room_id = leader[2]

            # ★★★ テストガード: 許可されていないルームへの送信をブロック ★★★
            if not is_goal_test_send_allowed(chatwork_room_id):
                logger.info(f"🚫 [TEST_GUARD] 連続未回答アラート送信をブロック: {leader_name}さん (room_id={chatwork_room_id})")
                results['blocked'] = results.get('blocked', 0) + 1
                continue

            # 自分自身は除外
            members_to_notify = [
                m for m in dept_data['members']
                if m['user_id'] != leader_id
            ]

            if not members_to_notify:
                continue

            status, error = send_consecutive_unanswered_alert_to_leader(
                conn=conn,
                leader_id=leader_id,
                org_id=org_id,
                leader_name=leader_name,
                chatwork_room_id=chatwork_room_id,
                unanswered_members=members_to_notify,
                consecutive_days=consecutive_days,
                send_message_func=send_message_func,
                dry_run=dry_run,
            )

            results[status] = results.get(status, 0) + 1

    logger.info(f"=== {consecutive_days}日連続未回答チェック 完了: success={results['success']}, skipped={results['skipped']}, failed={results['failed']}, blocked={results.get('blocked', 0)} ===")
    return results


# =====================================================
# アクセス権限チェック
# =====================================================

def can_view_goal(
    conn,
    viewer_user_id: str,
    goal_user_id: str,
    org_id: str
) -> bool:
    """
    目標の閲覧権限をチェック

    権限レベル（rolesテーブルのlevelカラム）に基づく階層アクセス制御:
    - Level 5-6 (代表/CFO/管理部): 組織全員の目標
    - Level 4 (部長/取締役): 自部署＋配下全部署の目標
    - Level 3 (課長/リーダー): 自部署＋直下部署の目標
    - Level 1-2 (社員/業務委託): 自分の目標のみ

    Args:
        conn: データベース接続
        viewer_user_id: 閲覧者ユーザーID
        goal_user_id: 目標所有者ユーザーID
        org_id: 組織ID

    Returns:
        閲覧可能かどうか
    """
    import sqlalchemy

    # 自分の目標は常にOK
    if viewer_user_id == goal_user_id:
        return True

    # 閲覧者の全ての役職・部署を取得し、最大権限レベルを使用
    # テナント分離: users, user_departments, departmentsでorg_idフィルタ
    # 注: rolesはシステム共通マスタテーブル（organization_idなし）のため除外
    result = conn.execute(sqlalchemy.text("""
        SELECT
            r.level AS role_level,
            ud.department_id,
            d.path AS dept_path
        FROM users u
        JOIN user_departments ud ON ud.user_id = u.id
        JOIN roles r ON ud.role_id = r.id
        JOIN departments d ON d.id = ud.department_id AND d.organization_id = CAST(:org_id AS TEXT)
        WHERE u.id = CAST(:viewer_id AS UUID)
          AND u.organization_id = CAST(:org_id AS TEXT)
          
    """), {'viewer_id': viewer_user_id, 'org_id': org_id})

    viewer_roles = result.fetchall()

    if not viewer_roles:
        return False

    # 最大権限レベルと、そのレベルに対応する部署情報を取得
    max_level = max(row[0] for row in viewer_roles)
    max_level_depts = [(row[1], row[2]) for row in viewer_roles if row[0] == max_level]

    # Level 5-6: 組織全員の目標を閲覧可能
    if max_level >= 5:
        return True

    # 目標所有者の部署情報を取得（テナント分離: org_idフィルタ）
    result = conn.execute(sqlalchemy.text("""
        SELECT
            ud.department_id,
            d.path AS dept_path
        FROM user_departments ud
        JOIN departments d ON d.id = ud.department_id AND d.organization_id = CAST(:org_id AS TEXT)
        WHERE ud.user_id = CAST(:goal_user_id AS UUID)
    """), {'goal_user_id': goal_user_id, 'org_id': org_id})

    goal_user_depts = result.fetchall()

    if not goal_user_depts:
        return False

    # Level 4 (部長/取締役): 自部署＋配下全部署の目標を閲覧可能
    if max_level == 4:
        for viewer_dept_id, viewer_dept_path in max_level_depts:
            for goal_dept_id, goal_dept_path in goal_user_depts:
                result = conn.execute(sqlalchemy.text("""
                    SELECT 1 WHERE :goal_path::ltree <@ :viewer_path::ltree
                """), {'goal_path': goal_dept_path, 'viewer_path': viewer_dept_path})
                if result.fetchone() is not None:
                    return True
        return False

    # Level 3 (課長/リーダー): 自部署＋直下部署の目標を閲覧可能
    if max_level == 3:
        viewer_dept_ids = [str(dept_id) for dept_id, _ in max_level_depts]
        for goal_dept_id, _ in goal_user_depts:
            if str(goal_dept_id) in viewer_dept_ids:
                return True
            result = conn.execute(sqlalchemy.text("""
                SELECT 1 FROM departments
                WHERE id = CAST(:goal_dept_id AS UUID)
                  AND parent_department_id = ANY(:viewer_dept_ids::uuid[])
                  AND organization_id = CAST(:org_id AS TEXT)
            """), {'goal_dept_id': goal_dept_id, 'viewer_dept_ids': viewer_dept_ids, 'org_id': org_id})
            if result.fetchone() is not None:
                return True
        return False

    # Level 1-2 (社員/業務委託): 自分の目標のみ
    return False


def get_viewable_user_ids(
    conn,
    viewer_user_id: str,
    org_id: str
) -> List[str]:
    """
    閲覧可能なユーザーIDリストを取得

    権限レベル（rolesテーブルのlevelカラム）に基づく階層アクセス制御:
    - Level 5-6 (代表/CFO/管理部): 組織全員
    - Level 4 (部長/取締役): 自部署＋配下全部署のメンバー
    - Level 3 (課長/リーダー): 自部署＋直下部署のメンバー
    - Level 1-2 (社員/業務委託): 自分のみ

    Args:
        conn: データベース接続
        viewer_user_id: 閲覧者ユーザーID
        org_id: 組織ID

    Returns:
        閲覧可能なユーザーIDリスト
    """
    import sqlalchemy

    # 閲覧者の全ての役職・部署を取得し、最大権限レベルを使用
    # テナント分離: users, user_departments, departmentsでorg_idフィルタ
    # 注: rolesはシステム共通マスタテーブル（organization_idなし）のため除外
    result = conn.execute(sqlalchemy.text("""
        SELECT
            r.level AS role_level,
            ud.department_id,
            d.path AS dept_path
        FROM users u
        JOIN user_departments ud ON ud.user_id = u.id
        JOIN roles r ON ud.role_id = r.id
        JOIN departments d ON d.id = ud.department_id AND d.organization_id = CAST(:org_id AS TEXT)
        WHERE u.id = CAST(:viewer_id AS UUID)
          AND u.organization_id = CAST(:org_id AS TEXT)
          
    """), {'viewer_id': viewer_user_id, 'org_id': org_id})

    viewer_roles = result.fetchall()

    if not viewer_roles:
        return [viewer_user_id]  # 自分のみ

    # 最大権限レベルと、そのレベルに対応する部署情報を取得
    max_level = max(row[0] for row in viewer_roles)
    max_level_depts = [(row[1], row[2]) for row in viewer_roles if row[0] == max_level]

    # Level 5-6: 組織全員
    if max_level >= 5:
        result = conn.execute(sqlalchemy.text("""
            SELECT id FROM users
            WHERE organization_id = CAST(:org_id AS TEXT)
        """), {'org_id': org_id})
        return [str(row[0]) for row in result.fetchall()]

    # Level 4 (部長/取締役): 自部署＋配下全部署のメンバー
    if max_level == 4:
        viewer_dept_paths = [str(dept_path) for _, dept_path in max_level_depts]
        result = conn.execute(sqlalchemy.text("""
            SELECT DISTINCT u.id
            FROM users u
            JOIN user_departments ud ON ud.user_id = u.id
            JOIN departments d ON d.id = ud.department_id AND d.organization_id = CAST(:org_id AS TEXT)
            WHERE u.organization_id = CAST(:org_id AS TEXT)
              
              AND EXISTS (
                  SELECT 1 FROM unnest(:viewer_paths::ltree[]) AS vp
                  WHERE d.path <@ vp
              )
        """), {'org_id': org_id, 'viewer_paths': viewer_dept_paths})
        return [str(row[0]) for row in result.fetchall()]

    # Level 3 (課長/リーダー): 自部署＋直下部署のメンバー
    if max_level == 3:
        viewer_dept_ids = [str(dept_id) for dept_id, _ in max_level_depts]
        result = conn.execute(sqlalchemy.text("""
            SELECT DISTINCT u.id
            FROM users u
            JOIN user_departments ud ON ud.user_id = u.id
            JOIN departments d ON d.id = ud.department_id AND d.organization_id = CAST(:org_id AS TEXT)
            WHERE u.organization_id = CAST(:org_id AS TEXT)
              
              AND (
                  ud.department_id = ANY(:viewer_dept_ids::uuid[])
                  OR
                  d.parent_department_id = ANY(:viewer_dept_ids::uuid[])
              )
        """), {'org_id': org_id, 'viewer_dept_ids': viewer_dept_ids})
        return [str(row[0]) for row in result.fetchall()]

    # Level 1-2 (社員/業務委託): 自分のみ
    return [viewer_user_id]


# =====================================================
# エクスポート
# =====================================================

__all__ = [
    # テストガード（v10.17.1追加）
    'GOAL_TEST_MODE',
    'GOAL_TEST_ALLOWED_ROOM_IDS',
    'KAZU_CHATWORK_ACCOUNT_ID',
    'is_goal_test_send_allowed',
    'log_goal_test_mode_status',
    # 通知タイプ
    'GoalNotificationType',
    # エラーサニタイズ
    'sanitize_error',
    # メッセージビルダー
    'build_daily_check_message',
    'build_daily_reminder_message',
    'build_morning_feedback_message',
    'build_team_summary_message',
    'build_consecutive_unanswered_alert_message',
    # 通知送信関数
    'send_daily_check_to_user',
    'send_daily_reminder_to_user',
    'send_morning_feedback_to_user',
    'send_team_summary_to_leader',
    'send_consecutive_unanswered_alert_to_leader',
    # スケジュール関数
    'scheduled_daily_check',
    'scheduled_daily_reminder',
    'scheduled_morning_feedback',
    'scheduled_consecutive_unanswered_check',
    # 連続未回答チェック
    'check_consecutive_unanswered_users',
    # アクセス権限
    'can_view_goal',
    'get_viewable_user_ids',
]
