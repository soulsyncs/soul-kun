"""
モデル選択ロジック

タスクタイプとコンテキストから最適なモデルを選択する

設計書: docs/20_next_generation_capabilities.md セクション4.3
"""

from dataclasses import dataclass
from typing import Optional, List, Any
import logging
import re

from .constants import (
    Tier,
    TASK_TYPE_TIERS,
    DEFAULT_TIER,
    TIER_UPGRADE_KEYWORDS,
    TIER_DOWNGRADE_KEYWORDS,
)
from .registry import ModelRegistry, ModelInfo

logger = logging.getLogger(__name__)


# =============================================================================
# データモデル
# =============================================================================

@dataclass
class ModelSelection:
    """モデル選択結果"""
    model: ModelInfo
    tier: Tier
    reason: str
    tier_adjusted: bool = False
    adjustment_reason: Optional[str] = None


# =============================================================================
# モデルセレクター
# =============================================================================

class ModelSelector:
    """
    モデル選択ロジック

    タスクタイプ → キーワード調整 → コンテキスト調整 → 最終選択
    """

    def __init__(self, registry: ModelRegistry):
        """
        初期化

        Args:
            registry: モデルレジストリ
        """
        self._registry = registry

    def select(
        self,
        task_type: str,
        message: Optional[str] = None,
        tier_override: Optional[Tier] = None,
        context: Optional[Any] = None,
    ) -> ModelSelection:
        """
        最適なモデルを選択

        選択フロー:
        1. tier_overrideがあれば優先
        2. task_typeから基本ティアを決定
        3. messageのキーワードでティア調整
        4. contextで追加調整（将来拡張）
        5. 決定したティアからモデルを取得

        Args:
            task_type: タスクタイプ（e.g., "conversation", "ceo_learning"）
            message: ユーザーメッセージ（キーワード調整用）
            tier_override: ティア直接指定（指定時は調整スキップ）
            context: 追加コンテキスト（将来拡張用）

        Returns:
            ModelSelection: 選択結果
        """
        tier_adjusted = False
        adjustment_reason = None

        # Step 1: ティア直接指定
        if tier_override is not None:
            tier = tier_override
            reason = f"ティア直接指定: {tier.value}"
            logger.debug(f"Model selection: tier override to {tier.value}")

        else:
            # Step 2: タスクタイプから基本ティアを決定
            base_tier = self._get_base_tier(task_type)
            tier = base_tier
            reason = f"タスクタイプ '{task_type}' → {tier.value}"

            # Step 3: キーワードでティア調整
            if message:
                adjusted_tier, adjust_reason = self._adjust_by_keywords(tier, message)
                if adjusted_tier != tier:
                    tier_adjusted = True
                    adjustment_reason = adjust_reason
                    tier = adjusted_tier
                    reason = f"{reason}, キーワード調整 → {tier.value}"
                    logger.debug(f"Model selection: tier adjusted to {tier.value} ({adjust_reason})")

            # Step 4: コンテキストで追加調整（将来拡張）
            if context:
                adjusted_tier, adjust_reason = self._adjust_by_context(tier, context)
                if adjusted_tier != tier:
                    tier_adjusted = True
                    adjustment_reason = adjust_reason
                    tier = adjusted_tier
                    reason = f"{reason}, コンテキスト調整 → {tier.value}"

        # Step 5: モデルを取得
        model = self._get_model_for_tier(tier)

        if model is None:
            # フォールバック：下位ティアを試す
            model = self._get_fallback_model(tier)
            if model is None:
                raise RuntimeError(f"No available model for tier {tier.value}")
            reason = f"{reason}, フォールバック → {model.tier.value}"

        return ModelSelection(
            model=model,
            tier=tier,
            reason=reason,
            tier_adjusted=tier_adjusted,
            adjustment_reason=adjustment_reason,
        )

    # -------------------------------------------------------------------------
    # ティア判定
    # -------------------------------------------------------------------------

    def _get_base_tier(self, task_type: str) -> Tier:
        """
        タスクタイプから基本ティアを取得

        Args:
            task_type: タスクタイプ

        Returns:
            基本ティア
        """
        task_type_lower = task_type.lower()

        # 完全一致
        if task_type_lower in TASK_TYPE_TIERS:
            return TASK_TYPE_TIERS[task_type_lower]

        # 部分一致（タスクタイプにキーワードが含まれる場合）
        for key, tier in TASK_TYPE_TIERS.items():
            if key in task_type_lower:
                return tier

        # デフォルト
        return DEFAULT_TIER

    def _adjust_by_keywords(
        self,
        base_tier: Tier,
        message: str
    ) -> tuple[Tier, Optional[str]]:
        """
        メッセージのキーワードでティアを調整

        Args:
            base_tier: 基本ティア
            message: ユーザーメッセージ

        Returns:
            (調整後ティア, 調整理由)
        """
        message_lower = message.lower() if message else ""

        # アップグレードキーワードチェック
        for keyword in TIER_UPGRADE_KEYWORDS:
            if keyword in message_lower or keyword in message:
                if base_tier == Tier.ECONOMY:
                    return Tier.STANDARD, f"キーワード '{keyword}' でアップグレード"
                elif base_tier == Tier.STANDARD:
                    return Tier.PREMIUM, f"キーワード '{keyword}' でアップグレード"

        # ダウングレードキーワードチェック
        for keyword in TIER_DOWNGRADE_KEYWORDS:
            if keyword in message_lower or keyword in message:
                if base_tier == Tier.PREMIUM:
                    return Tier.STANDARD, f"キーワード '{keyword}' でダウングレード"
                elif base_tier == Tier.STANDARD:
                    return Tier.ECONOMY, f"キーワード '{keyword}' でダウングレード"

        return base_tier, None

    def _adjust_by_context(
        self,
        tier: Tier,
        context: Any
    ) -> tuple[Tier, Optional[str]]:
        """
        コンテキストでティアを調整（将来拡張）

        Args:
            tier: 現在のティア
            context: コンテキスト情報

        Returns:
            (調整後ティア, 調整理由)
        """
        # 将来的にはコンテキストからの調整を実装
        # - タスクの重要度
        # - 締切の近さ
        # - ユーザーの役職
        # - 過去の満足度
        return tier, None

    # -------------------------------------------------------------------------
    # モデル取得
    # -------------------------------------------------------------------------

    def _get_model_for_tier(self, tier: Tier) -> Optional[ModelInfo]:
        """
        ティアのデフォルトモデルを取得

        Args:
            tier: ティア

        Returns:
            モデル情報（見つからない場合はNone）
        """
        return self._registry.get_default_model_for_tier(tier)

    def _get_fallback_model(self, tier: Tier) -> Optional[ModelInfo]:
        """
        フォールバックモデルを取得

        指定ティアのモデルがない場合、下位ティアから取得

        Args:
            tier: 起点ティア

        Returns:
            フォールバックモデル（見つからない場合はNone）
        """
        # 下位ティアを順に試す
        if tier == Tier.PREMIUM:
            fallback_tiers = [Tier.STANDARD, Tier.ECONOMY]
        elif tier == Tier.STANDARD:
            fallback_tiers = [Tier.ECONOMY]
        else:
            fallback_tiers = []

        for fallback_tier in fallback_tiers:
            model = self._registry.get_default_model_for_tier(fallback_tier)
            if model is not None:
                logger.warning(
                    f"No model available for tier {tier.value}, "
                    f"using fallback tier {fallback_tier.value}"
                )
                return model

        return None

    # -------------------------------------------------------------------------
    # ユーティリティ
    # -------------------------------------------------------------------------

    def get_available_tiers(self) -> List[Tier]:
        """
        利用可能なティアを取得

        Returns:
            利用可能なティアのリスト
        """
        available = []
        for tier in Tier:
            models = self._registry.get_models_by_tier(tier)
            if models:
                available.append(tier)
        return available

    def explain_selection(
        self,
        task_type: str,
        message: Optional[str] = None,
    ) -> str:
        """
        モデル選択の理由を説明（デバッグ用）

        Args:
            task_type: タスクタイプ
            message: ユーザーメッセージ

        Returns:
            説明文
        """
        selection = self.select(task_type, message)

        lines = [
            f"[Model Selection Explanation]",
            f"Task Type: {task_type}",
            f"Message: {message[:50] if message else '(none)'}...",
            f"",
            f"Base Tier: {self._get_base_tier(task_type).value}",
            f"Final Tier: {selection.tier.value}",
            f"Tier Adjusted: {selection.tier_adjusted}",
            f"Adjustment Reason: {selection.adjustment_reason or '(none)'}",
            f"",
            f"Selected Model: {selection.model.display_name}",
            f"Model ID: {selection.model.model_id}",
            f"Provider: {selection.model.provider}",
            f"",
            f"Selection Reason: {selection.reason}",
        ]

        return "\n".join(lines)
