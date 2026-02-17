"""
目標設定対話フロー - パターン検出ヘルパー関数

ユーザーの発話からリスタート要求、確認、フィードバック要求、
迷い・不安、フェーズ充足度などを検出するヘルパー関数群。
"""

import logging
from typing import Optional, Dict, Any

from .constants import (
    RESTART_PATTERNS,
    BUT_CONNECTOR_PATTERNS,
    FEEDBACK_REQUEST_PATTERNS,
    DOUBT_ANXIETY_PATTERNS,
    CONFIRMATION_PATTERNS,
    WHY_FULFILLED_PATTERNS,
    WHAT_FULFILLED_PATTERNS,
    HOW_FULFILLED_PATTERNS,
)

logger = logging.getLogger(__name__)


def _wants_restart(text: str) -> bool:
    """
    v10.40.3: 明示的なリスタート要求を検出

    「もう一度目標設定したい」「やり直したい」等の場合のみ、
    セッションをリセットして最初から開始する。

    Args:
        text: ユーザーメッセージ

    Returns:
        True: リスタート要求（セッションをリセット）
        False: リスタート要求ではない（セッション継続）
    """
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in RESTART_PATTERNS)


def _has_but_connector(text: str) -> bool:
    """
    v10.40.1: 否定接続（「けど」「だけど」等）を検出

    「合ってるけど」のような場合、confirmed=False にするためのガード。
    これは応急処置であり、将来的には brain/understanding.py に移行予定。

    Args:
        text: ユーザーメッセージ

    Returns:
        True: 否定接続が含まれる（確認として扱わない）
        False: 否定接続がない
    """
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in BUT_CONNECTOR_PATTERNS)


def _has_feedback_request(text: str) -> bool:
    """
    v10.40.1: フィードバック要求を検出

    「フィードバックして」「正しい？」等の場合、登録せずに導きの対話に入る。
    これは応急処置であり、将来的には brain/understanding.py に移行予定。

    Args:
        text: ユーザーメッセージ

    Returns:
        True: フィードバック要求が含まれる（登録しない）
        False: フィードバック要求がない
    """
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in FEEDBACK_REQUEST_PATTERNS)


def _has_doubt_or_anxiety(text: str) -> bool:
    """
    v10.40.2: 迷い・不安を検出

    「不安」「自信ない」「違うかも」等の場合、導きの対話に入る。

    Args:
        text: ユーザーメッセージ

    Returns:
        True: 迷い・不安が含まれる（導きの対話へ）
        False: 迷い・不安がない
    """
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in DOUBT_ANXIETY_PATTERNS)


def _is_pure_confirmation(text: str) -> bool:
    """
    v10.40.1: 純粋な確認かどうかを判定

    confirmed = 肯定語あり AND 否定接続なし AND FB要求なし

    これにより「合ってるけど〜」「OKだけど教えて」等での誤登録を防止。

    Args:
        text: ユーザーメッセージ

    Returns:
        True: 純粋な確認（登録OK）
        False: 追加要求あり（登録しない）
    """
    text_lower = text.lower().strip()

    # 1. 肯定語チェック
    has_confirmation = any(
        pattern in text_lower for pattern in CONFIRMATION_PATTERNS
    )
    if not has_confirmation:
        return False

    # 2. 否定接続チェック（「けど」等があればNG）
    if _has_but_connector(text):
        logger.debug("否定接続検出: 確認として扱わない")
        return False

    # 3. フィードバック要求チェック
    if _has_feedback_request(text):
        logger.debug("フィードバック要求検出: 確認として扱わない")
        return False

    return True


# =============================================================================
# v10.40.3: フェーズ自動判定（Phase Auto-Inference）
# ユーザー発話からWHY/WHAT/HOWの充足度を推定し、既に充足したフェーズをスキップ
# =============================================================================


def _infer_fulfilled_phases(text: str) -> Dict[str, bool]:
    """
    v10.40.3: ユーザー発話からフェーズの充足度を推定

    WHY/WHAT/HOWそれぞれについて、ユーザーの発話に
    該当する情報が含まれているかを判定。

    Args:
        text: ユーザーメッセージ

    Returns:
        {"why": True/False, "what": True/False, "how": True/False}
    """
    text_lower = text.lower()

    return {
        "why": any(p in text_lower for p in WHY_FULFILLED_PATTERNS),
        "what": any(p in text_lower for p in WHAT_FULFILLED_PATTERNS),
        "how": any(p in text_lower for p in HOW_FULFILLED_PATTERNS),
    }


def _get_next_unfulfilled_step(
    fulfilled: Dict[str, bool],
    current_step: str,
    session: Dict[str, Any]
) -> Optional[str]:
    """
    v10.40.3: 次に質問すべきステップを判定

    既に充足しているステップはスキップし、未充足のステップを返す。
    セッションに既に回答がある場合もスキップ。

    Args:
        fulfilled: 各フェーズの充足状況
        current_step: 現在のステップ
        session: セッション情報

    Returns:
        次のステップ名（"why", "what", "how", "confirm"）
        全て充足済みなら "confirm"
    """
    steps = ["why", "what", "how"]

    for step in steps:
        # 既にセッションに回答がある場合はスキップ
        answer_key = f"{step}_answer"
        if session.get(answer_key):
            continue

        # 今回の発話で充足していない場合は、このステップを次に
        if not fulfilled.get(step, False):
            return step

    # 全て充足 → confirm へ
    return "confirm"
