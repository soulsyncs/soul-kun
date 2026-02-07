"""services/proposal_actions.py - 提案管理アクションハンドラー

Phase 11-5b: main.pyから抽出された提案承認・却下・一覧のアクションハンドラー。

依存: infra/db.py (get_pool, get_secret), services/person_org.py
"""

from infra.db import get_pool, get_secret
from infra.helpers import is_admin
from services.person_org import save_person_attribute

from handlers.proposal_handler import ProposalHandler as _NewProposalHandler

# 管理者設定
try:
    from lib.admin_config import get_admin_config
    _admin_config = get_admin_config()
    ADMIN_ACCOUNT_ID = _admin_config.admin_account_id
    ADMIN_ROOM_ID = int(_admin_config.admin_room_id)
except ImportError:
    ADMIN_ACCOUNT_ID = "1728974"
    ADMIN_ROOM_ID = 405315911

_proposal_handler = None



def _get_proposal_handler():
    """ProposalHandlerのシングルトンインスタンスを取得"""
    global _proposal_handler
    if _proposal_handler is None:
        _proposal_handler = _NewProposalHandler(
            get_pool=get_pool,
            get_secret=get_secret,
            admin_room_id=str(ADMIN_ROOM_ID),
            admin_account_id=ADMIN_ACCOUNT_ID,
            is_admin=is_admin,
            save_person_attribute=save_person_attribute  # v10.25.0: 人物情報提案対応
        )
    return _proposal_handler

def create_proposal(proposed_by_account_id: str, proposed_by_name: str,
                   proposed_in_room_id: str, category: str, key: str,
                   value: str, message_id: str = None):
    """
    知識の提案を作成

    v10.24.2: handlers/proposal_handler.py に移動済み
    """
    return _get_proposal_handler().create_proposal(
        proposed_by_account_id, proposed_by_name, proposed_in_room_id,
        category, key, value, message_id
    )

def get_pending_proposals():
    """
    承認待ちの提案を取得（古い順FIFO）

    v10.24.2: handlers/proposal_handler.py に移動済み
    """
    return _get_proposal_handler().get_pending_proposals()

def get_unnotified_proposals():
    """
    通知失敗した提案を取得

    v10.24.2: handlers/proposal_handler.py に移動済み
    """
    return _get_proposal_handler().get_unnotified_proposals()

def retry_proposal_notification(proposal_id: int):
    """
    提案の通知を再送

    v10.24.2: handlers/proposal_handler.py に移動済み
    """
    return _get_proposal_handler().retry_proposal_notification(proposal_id)

def report_proposal_to_admin(proposal_id: int, proposer_name: str, key: str, value: str, category: str = None):
    """
    提案を管理部に報告
    v6.9.1: ID表示、admin_notifiedフラグ更新
    v10.25.0: category='memory'の場合は人物情報用メッセージ

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    return _get_proposal_handler().report_proposal_to_admin(proposal_id, proposer_name, key, value, category)

def handle_proposal_decision(params, room_id, account_id, sender_name, context=None):
    """
    提案の承認/却下を処理するハンドラー（AI司令塔経由）
    - 管理者のみ有効
    - 管理部ルームでの発言のみ対応
    v6.9.1: ID指定方式を推奨（handle_proposal_by_idを使用）

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    return _get_proposal_handler().handle_proposal_decision(params, room_id, account_id, sender_name, context)

def handle_proposal_by_id(proposal_id: int, decision: str, account_id: str, sender_name: str, room_id: str):
    """
    ID指定で提案を承認/却下（v6.9.1追加）
    ローカルコマンド「承認 123」「却下 123」用

    v10.24.2: handlers/proposal_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    return _get_proposal_handler().handle_proposal_by_id(proposal_id, decision, account_id, sender_name, room_id)

def handle_list_pending_proposals(room_id: str, account_id: str):
    """
    承認待ち提案の一覧を表示（v6.9.1追加）
    ローカルコマンド「承認待ち一覧」用
    """
    # 管理部ルームかチェック
    if str(room_id) != str(ADMIN_ROOM_ID):
        return "🤔 承認待ち一覧は管理部ルームで確認してウル！"
    
    proposals = get_pending_proposals()
    
    if not proposals:
        return "✨ 承認待ちの提案は今ないウル！スッキリ！🐺"
    
    lines = [f"📋 **承認待ちの提案一覧**（{len(proposals)}件）ウル！🐺\n"]
    
    for p in proposals:
        created = p["created_at"].strftime("%m/%d %H:%M") if p.get("created_at") else "不明"
        lines.append(f"・**ID={p['id']}** 「{p['key']}: {p['value']}」")
        lines.append(f"  └ 提案者: {p['proposed_by_name']}さん（{created}）")
    
    lines.append("\n---")
    lines.append("「承認 ID番号」または「却下 ID番号」で処理できるウル！")
    lines.append("例：「承認 1」「却下 2」")
    
    return "\n".join(lines)

def handle_list_unnotified_proposals(room_id: str, account_id: str):
    """
    通知失敗した提案の一覧を表示（v6.9.2追加）
    管理者のみ閲覧可能
    """
    # 管理者判定
    if not is_admin(account_id):
        return "🙏 未通知提案の確認は菊地さんだけができるウル！"
    
    proposals = get_unnotified_proposals()
    
    if not proposals:
        return "✨ 通知失敗した提案はないウル！全部ちゃんと届いてるウル！🐺"
    
    lines = [f"⚠️ **通知失敗した提案一覧**（{len(proposals)}件）ウル！🐺\n"]
    
    for p in proposals:
        created = p["created_at"].strftime("%m/%d %H:%M") if p.get("created_at") else "不明"
        lines.append(f"・**ID={p['id']}** 「{p['key']}: {p['value']}」")
        lines.append(f"  └ 提案者: {p['proposed_by_name']}さん（{created}）")
    
    lines.append("\n---")
    lines.append("「再通知 ID番号」で再送できるウル！")
    lines.append("例：「再通知 1」「再送 2」")
    
    return "\n".join(lines)

def handle_retry_notification(proposal_id: int, room_id: str, account_id: str):
    """
    提案の通知を再送（v6.9.2追加）
    管理者のみ実行可能
    """
    # 管理者判定
    if not is_admin(account_id):
        return "🙏 再通知は菊地さんだけができるウル！"
    
    success, message = retry_proposal_notification(proposal_id)
    
    if success:
        return f"✅ 再通知したウル！🐺\n\n{message}\n管理部に届いたはずウル！"
    else:
        return f"😢 再通知に失敗したウル...\n\n{message}"
