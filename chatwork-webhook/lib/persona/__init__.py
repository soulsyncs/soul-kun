"""
v10.43.0: Persona Layer
Company Persona (B) + Add-on (C) を組み合わせた人格レイヤー
"""
from typing import Optional

from .company_base import get_company_persona
from .addon_manager import get_user_addon


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


__all__ = ["build_persona_prompt", "get_company_persona", "get_user_addon"]
