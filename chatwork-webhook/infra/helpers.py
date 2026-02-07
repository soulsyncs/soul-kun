"""infra/helpers.py - 共通ユーティリティ関数

Phase 11-1d: main.pyから抽出された純粋なユーティリティ関数。
300行制限（ダンプ場にしない）。

依存: infra/db.py (get_pool), lib/admin_config (is_admin判定)
"""

import re
from datetime import datetime, timezone, timedelta
import sqlalchemy
import traceback

from infra.db import get_pool

# 管理者判定
try:
    from lib.admin_config import (
        get_admin_config,
        is_admin_account,
        DEFAULT_ORG_ID as ADMIN_CONFIG_DEFAULT_ORG_ID,
    )
    USE_ADMIN_CONFIG = True
except ImportError:
    USE_ADMIN_CONFIG = False

# フォールバック用管理者設定
if USE_ADMIN_CONFIG:
    _admin_config = get_admin_config()
    ADMIN_ACCOUNT_ID = _admin_config.admin_account_id
else:
    ADMIN_ACCOUNT_ID = "1728974"


# ローカルコマンドパターン
LOCAL_COMMAND_PATTERNS = [
    (r'^承認\s*(\d+)$', 'approve_proposal_by_id'),
    (r'^却下\s*(\d+)$', 'reject_proposal_by_id'),
    (r'^承認待ち(一覧)?$', 'list_pending_proposals'),
    (r'^(提案|ていあん)(一覧|リスト)$', 'list_pending_proposals'),
    (r'^未通知(提案)?(一覧)?$', 'list_unnotified_proposals'),
    (r'^通知失敗(一覧)?$', 'list_unnotified_proposals'),
    (r'^再通知\s*(\d+)$', 'retry_notification'),
    (r'^再送\s*(\d+)$', 'retry_notification'),
    (r'^設定[：:]\s*(.+?)\s*[=＝]\s*(.+)$', 'learn_knowledge_formatted'),
    (r'^設定[：:]\s*(.+)$', 'learn_knowledge_simple'),
    (r'^覚えて[：:]\s*(.+)$', 'learn_knowledge_simple'),
    (r'^忘れて[：:]\s*(.+)$', 'forget_knowledge'),
    (r'^設定削除[：:]\s*(.+)$', 'forget_knowledge'),
    (r'^何覚えてる[？?]?$', 'list_knowledge'),
    (r'^設定(一覧|リスト)$', 'list_knowledge'),
    (r'^学習(済み)?(知識|内容)(一覧)?$', 'list_knowledge'),
]



def match_local_command(message: str):
    """
    ローカルで処理可能なコマンドかどうかを判定
    
    Returns:
        (action, groups) - マッチした場合
        (None, None) - マッチしない場合
    """
    message = message.strip()
    for pattern, action in LOCAL_COMMAND_PATTERNS:
        match = re.match(pattern, message)
        if match:
            return action, match.groups()
    return None, None

def is_admin(account_id):
    """
    管理者（カズさん）かどうかを判定

    v10.30.1: lib/admin_config.py を使用（DB取得、キャッシュ付き）
    フォールバック時は従来のハードコード比較を使用
    """
    if USE_ADMIN_CONFIG:
        return is_admin_account(str(account_id))
    return str(account_id) == str(ADMIN_ACCOUNT_ID)

def _fallback_truncate_text(text: str, max_length: int = 40) -> str:
    """
    フォールバック用の切り詰め処理（自然な位置で切る）

    prepare_task_display_text()が使えない場合の最終手段。
    句点、読点、助詞の後ろで切ることで、途中で途切れる感を軽減。

    Args:
        text: 切り詰める文字列
        max_length: 最大文字数

    Returns:
        切り詰めた文字列
    """
    if not text:
        return "（タスク内容なし）"

    if len(text) <= max_length:
        return text

    truncated = text[:max_length]

    # 句点、読点、助詞の後ろで切る
    for sep in ["。", "、", "を", "に", "で", "が", "は", "の"]:
        pos = truncated.rfind(sep)
        if pos > max_length // 2:
            return truncated[:pos + 1] + "..."

    return truncated + "..."

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
    # v10.40.3: コメントアウトされていた旧コードを削除
    task_id = task.get('task_id', 'unknown')
    print(f"📝 [v10.15.0] 完了通知スキップ: task_id={task_id} (管理部への日次報告に集約)")
    return

def should_show_guide(room_id, account_id):
    """案内文を表示すべきかどうかを判定（PostgreSQL版）"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            # DMルームの場合は案内を表示しない
            dm_check = conn.execute(
                sqlalchemy.text("""
                    SELECT 1 FROM dm_room_cache
                    WHERE dm_room_id = :room_id
                    LIMIT 1
                """),
                {"room_id": room_id}
            ).fetchone()

            if dm_check:
                return False  # DMルームでは案内不要

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
