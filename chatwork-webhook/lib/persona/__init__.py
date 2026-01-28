"""
v10.43.0: Persona Layer
Company Persona (B) + Add-on (C) を組み合わせた人格レイヤー

v10.46.0: Persona観測ログ追加
- log_persona_path: 全経路でPersonaの状態をログ出力
"""
from typing import Optional

from .company_base import get_company_persona
from .addon_manager import get_user_addon


def log_persona_path(
    path: str,
    injected: bool,
    addon: bool,
    account_id: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """
    v10.46.0: Persona観測ログを出力

    全主要経路でPersonaの状態を統一フォーマットでログ出力し、
    経路ごとの挙動を追えるようにする。

    Args:
        path: コードパス名（例: "get_ai_response", "goal_registration"）
        injected: Personaプロンプトが注入されたかどうか
        addon: Add-onが適用されたかどうか
        account_id: ユーザーのChatWork account_id
        extra: 追加情報（任意）

    出力例:
        🎭 persona_path=get_ai_response injected=yes addon=yes account=12345
        🎭 persona_path=goal_registration injected=no addon=no account=12345 (direct_response)
    """
    injected_str = "yes" if injected else "no"
    addon_str = "yes" if addon else "no"
    account_str = account_id or "unknown"
    extra_str = f" ({extra})" if extra else ""

    print(f"🎭 persona_path={path} injected={injected_str} addon={addon_str} account={account_str}{extra_str}")


def build_persona_prompt(
    pool,
    org_id: str,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
) -> str:
    """
    Company Persona + Add-on を結合して人格プロンプトを構築

    Args:
        pool: DB接続プール
        org_id: 組織ID
        user_id: ユーザーID（ChatWork account_id）。Noneの場合Add-onスキップ
        user_name: ユーザー名（Add-on表示用）

    Returns:
        結合された人格プロンプト文字列
    """
    lines = []

    # Company Persona (B)
    company_persona = get_company_persona()
    lines.append("【ソウルくんの行動指針】")
    lines.append(company_persona)

    # Add-on (C) - user_idがある場合のみ取得
    if user_id:
        addon = get_user_addon(pool, org_id, user_id)
        if addon:
            display_name = user_name or "この方"
            lines.append("")
            lines.append(f"【追加指針：{display_name}向け】")
            lines.append(addon)

    return "\n".join(lines)


__all__ = ["build_persona_prompt", "get_company_persona", "get_user_addon", "log_persona_path"]
