# lib/brain/core/validators.py
"""
境界型検証ヘルパー（LLM出力・APIレスポンスの型崩れ検出）

SoulkunBrainクラスの外部で使用される、独立した検証関数群。
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _validate_llm_result_type(llm_result: Any, location: str) -> bool:
    """
    LLMBrainResultの型を検証する

    Args:
        llm_result: 検証対象のオブジェクト
        location: 検証箇所（ログ出力用）

    Returns:
        bool: 検証成功ならTrue

    Raises:
        TypeError: 型が不正な場合
    """
    from lib.brain.llm_brain import LLMBrainResult, ToolCall, ConfidenceScores

    if not isinstance(llm_result, LLMBrainResult):
        logger.error(
            f"[境界型検証エラー] {location}: "
            f"LLMBrainResult expected, got {type(llm_result).__name__}"
        )
        raise TypeError(
            f"LLMBrainResult expected at {location}, got {type(llm_result).__name__}"
        )

    # confidenceの型検証（オブジェクトか数値か）
    if llm_result.confidence is not None:
        if not isinstance(llm_result.confidence, ConfidenceScores):
            logger.warning(
                f"[境界型検証警告] {location}: "
                f"confidence is not ConfidenceScores: {type(llm_result.confidence).__name__}"
            )

    # tool_callsの型検証
    if llm_result.tool_calls is not None:
        if not isinstance(llm_result.tool_calls, list):
            logger.error(
                f"[境界型検証エラー] {location}: "
                f"tool_calls should be list, got {type(llm_result.tool_calls).__name__}"
            )
            raise TypeError(
                f"tool_calls should be list at {location}, got {type(llm_result.tool_calls).__name__}"
            )
        for i, tc in enumerate(llm_result.tool_calls):
            if not isinstance(tc, ToolCall):
                logger.error(
                    f"[境界型検証エラー] {location}: "
                    f"tool_calls[{i}] is not ToolCall: {type(tc).__name__}"
                )
                raise TypeError(
                    f"tool_calls[{i}] should be ToolCall at {location}, got {type(tc).__name__}"
                )

    return True


def _extract_confidence_value(raw_confidence: Any, location: str) -> float:
    """
    confidenceから数値を安全に抽出する

    LLMの出力やAPIレスポンスでconfidenceが以下の形式で来る可能性がある:
    - ConfidenceScoresオブジェクト（.overall属性を持つ）
    - 数値（int, float）
    - 辞書（{"overall": 0.8}）
    - None

    Args:
        raw_confidence: 生のconfidence値
        location: 抽出箇所（ログ出力用）

    Returns:
        float: 確信度（0.0〜1.0）
    """
    from lib.brain.llm_brain import ConfidenceScores

    if raw_confidence is None:
        logger.debug(f"[境界型検証] {location}: confidence is None, using default 0.0")
        return 0.0

    # ConfidenceScoresオブジェクト
    if isinstance(raw_confidence, ConfidenceScores):
        return float(raw_confidence.overall)

    # hasattr でoverall属性を持つオブジェクト（ダックタイピング）
    if hasattr(raw_confidence, 'overall'):
        overall = raw_confidence.overall
        if isinstance(overall, (int, float)):
            return float(overall)
        else:
            logger.warning(
                f"[境界型検証警告] {location}: "
                f"confidence.overall is not numeric: {type(overall).__name__}"
            )
            return 0.0

    # 数値
    if isinstance(raw_confidence, (int, float)):
        return float(raw_confidence)

    # 辞書
    if isinstance(raw_confidence, dict) and 'overall' in raw_confidence:
        overall = raw_confidence['overall']
        if isinstance(overall, (int, float)):
            return float(overall)
        else:
            logger.warning(
                f"[境界型検証警告] {location}: "
                f"confidence['overall'] is not numeric: {type(overall).__name__}"
            )
            return 0.0

    # 予期しない型
    logger.error(
        f"[境界型検証エラー] {location}: "
        f"unexpected confidence type: {type(raw_confidence).__name__}, value={raw_confidence}"
    )
    return 0.0


def _safe_confidence_to_dict(raw_confidence: Any, location: str) -> Dict[str, Any]:
    """
    confidenceを辞書形式に安全に変換する

    Args:
        raw_confidence: 生のconfidence値
        location: 変換箇所（ログ出力用）

    Returns:
        Dict: 確信度の辞書形式
    """
    from lib.brain.llm_brain import ConfidenceScores

    if raw_confidence is None:
        return {"overall": 0.0, "intent": 0.0, "parameters": 0.0}

    # ConfidenceScoresオブジェクト（to_dictメソッドを持つ）
    if isinstance(raw_confidence, ConfidenceScores):
        result: Dict[str, Any] = raw_confidence.to_dict()
        return result

    # to_dictメソッドを持つオブジェクト（ダックタイピング）
    if hasattr(raw_confidence, 'to_dict') and callable(raw_confidence.to_dict):
        try:
            duck_result: Dict[str, Any] = raw_confidence.to_dict()
            return duck_result
        except Exception as e:
            logger.warning(
                f"[境界型検証警告] {location}: "
                f"to_dict() failed: {type(e).__name__}"
            )
            return {"overall": _extract_confidence_value(raw_confidence, location)}

    # 数値
    if isinstance(raw_confidence, (int, float)):
        return {"overall": float(raw_confidence)}

    # 辞書（そのまま返す）
    if isinstance(raw_confidence, dict):
        return raw_confidence

    # 予期しない型
    logger.warning(
        f"[境界型検証警告] {location}: "
        f"unexpected confidence type for dict conversion: {type(raw_confidence).__name__}"
    )
    return {"overall": 0.0}
