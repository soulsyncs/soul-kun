"""
コスト管理

コスト計算、閾値判定、月次サマリー更新を担当

設計書: docs/20_next_generation_capabilities.md セクション4.4
10の鉄則:
- #1: 全クエリにorganization_idフィルタ
- #9: SQLインジェクション対策（パラメータ化クエリ）
"""

from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Tuple, Dict, Any
from enum import Enum
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .constants import (
    Tier,
    BudgetStatus,
    CostThreshold,
    MonthlyBudget,
    BUDGET_STATUS_THRESHOLDS,
    DEFAULT_USD_TO_JPY_RATE,
    TOKENS_PER_CHAR_JP,
    DEFAULT_OUTPUT_TOKENS_ESTIMATE,
)
from .registry import ModelInfo

logger = logging.getLogger(__name__)


# =============================================================================
# データモデル
# =============================================================================

class CostAction(str, Enum):
    """コストアクション（相談判定結果）"""
    AUTO_EXECUTE = "auto_execute"        # 自動実行（通知なし）
    EXECUTE_WITH_REPORT = "execute_with_report"  # 実行後報告
    ASK_BEFORE = "ask_before"            # 事前確認
    SHOW_ALTERNATIVES = "show_alternatives"  # 代替案提示
    BLOCK = "block"                      # ブロック（予算超過）


@dataclass
class CostEstimate:
    """コスト推定結果"""
    input_tokens: int
    output_tokens: int
    cost_jpy: Decimal
    model_id: str


@dataclass
class CostCheckResult:
    """コストチェック結果"""
    estimated_cost_jpy: Decimal
    daily_cost_jpy: Decimal
    monthly_cost_jpy: Decimal
    budget_remaining_jpy: Decimal
    budget_status: BudgetStatus
    action: CostAction
    message: Optional[str] = None
    alternative_model: Optional[ModelInfo] = None


@dataclass
class OrganizationSettings:
    """組織設定"""
    organization_id: str
    monthly_budget_jpy: Decimal
    cost_threshold_warning: Decimal
    cost_threshold_caution: Decimal
    cost_threshold_limit: Decimal
    default_tier: str
    enable_premium_tier: bool
    enable_auto_downgrade: bool
    enable_fallback: bool
    max_fallback_attempts: int
    usd_to_jpy_rate: Decimal


# =============================================================================
# コストマネージャー
# =============================================================================

class CostManager:
    """
    コスト管理

    - コスト推定・計算
    - 日次/月次コスト追跡
    - 閾値判定（4段階）
    - 月次サマリー更新
    """

    def __init__(self, pool: Engine, organization_id: str):
        """
        初期化

        Args:
            pool: SQLAlchemyのエンジン（DB接続プール）
            organization_id: 組織ID
        """
        self._pool = pool
        self._organization_id = organization_id
        self._settings_cache: Optional[OrganizationSettings] = None

    # -------------------------------------------------------------------------
    # 設定取得
    # -------------------------------------------------------------------------

    def get_settings(self, use_cache: bool = True) -> OrganizationSettings:
        """
        組織設定を取得

        Args:
            use_cache: キャッシュを使用するか

        Returns:
            組織設定
        """
        if use_cache and self._settings_cache is not None:
            return self._settings_cache

        query = text("""
            SELECT
                organization_id,
                monthly_budget_jpy,
                cost_threshold_warning,
                cost_threshold_caution,
                cost_threshold_limit,
                default_tier,
                enable_premium_tier,
                enable_auto_downgrade,
                enable_fallback,
                max_fallback_attempts,
                usd_to_jpy_rate
            FROM ai_organization_settings
            WHERE organization_id = CAST(:org_id AS uuid)
        """)

        try:
            with self._pool.connect() as conn:
                result = conn.execute(query, {"org_id": self._organization_id})
                row = result.fetchone()

                if row is None:
                    # デフォルト設定を返す
                    return self._get_default_settings()

                settings = OrganizationSettings(
                    organization_id=str(row[0]),
                    monthly_budget_jpy=Decimal(str(row[1])),
                    cost_threshold_warning=Decimal(str(row[2])),
                    cost_threshold_caution=Decimal(str(row[3])),
                    cost_threshold_limit=Decimal(str(row[4])),
                    default_tier=row[5],
                    enable_premium_tier=row[6],
                    enable_auto_downgrade=row[7],
                    enable_fallback=row[8],
                    max_fallback_attempts=row[9],
                    usd_to_jpy_rate=Decimal(str(row[10])),
                )

                self._settings_cache = settings
                return settings

        except Exception as e:
            logger.error(f"Failed to get organization settings: {type(e).__name__}")
            return self._get_default_settings()

    def _get_default_settings(self) -> OrganizationSettings:
        """デフォルト設定を取得"""
        return OrganizationSettings(
            organization_id=self._organization_id,
            monthly_budget_jpy=MonthlyBudget.DEFAULT_JPY,
            cost_threshold_warning=CostThreshold.NORMAL_MAX,
            cost_threshold_caution=CostThreshold.WARNING_MAX,
            cost_threshold_limit=CostThreshold.LIMIT,
            default_tier="standard",
            enable_premium_tier=True,
            enable_auto_downgrade=True,
            enable_fallback=True,
            max_fallback_attempts=3,
            usd_to_jpy_rate=DEFAULT_USD_TO_JPY_RATE,
        )

    # -------------------------------------------------------------------------
    # コスト推定
    # -------------------------------------------------------------------------

    def estimate_tokens(
        self,
        prompt: str,
        expected_output_tokens: Optional[int] = None
    ) -> Tuple[int, int]:
        """
        トークン数を推定

        Args:
            prompt: プロンプト文字列
            expected_output_tokens: 期待される出力トークン数（指定なしでデフォルト）

        Returns:
            (input_tokens, output_tokens)
        """
        # 日本語文字数からトークン数を推定
        input_tokens = int(len(prompt) * TOKENS_PER_CHAR_JP)
        output_tokens = expected_output_tokens or DEFAULT_OUTPUT_TOKENS_ESTIMATE

        return input_tokens, output_tokens

    def estimate_cost(
        self,
        model: ModelInfo,
        prompt: str,
        expected_output_tokens: Optional[int] = None
    ) -> CostEstimate:
        """
        コストを推定

        Args:
            model: モデル情報
            prompt: プロンプト文字列
            expected_output_tokens: 期待される出力トークン数

        Returns:
            コスト推定結果
        """
        settings = self.get_settings()
        input_tokens, output_tokens = self.estimate_tokens(prompt, expected_output_tokens)
        cost_jpy = model.calculate_cost_jpy(
            input_tokens,
            output_tokens,
            settings.usd_to_jpy_rate
        )

        return CostEstimate(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_jpy=cost_jpy,
            model_id=model.model_id,
        )

    def calculate_actual_cost(
        self,
        model: ModelInfo,
        input_tokens: int,
        output_tokens: int
    ) -> Decimal:
        """
        実際のコストを計算

        Args:
            model: モデル情報
            input_tokens: 入力トークン数
            output_tokens: 出力トークン数

        Returns:
            コスト（円）
        """
        settings = self.get_settings()
        return model.calculate_cost_jpy(
            input_tokens,
            output_tokens,
            settings.usd_to_jpy_rate
        )

    # -------------------------------------------------------------------------
    # コストチェック
    # -------------------------------------------------------------------------

    def check_cost(
        self,
        estimated_cost_jpy: Decimal,
        model: Optional[ModelInfo] = None
    ) -> CostCheckResult:
        """
        コストをチェックし、アクションを決定

        4段階の閾値判定:
        - normal (< 100円/日): 自動実行
        - warning (100-500円/日): 実行後報告
        - caution (500-2000円/日): 事前確認
        - limit (> 2000円/日): 代替案提示

        Args:
            estimated_cost_jpy: 推定コスト（円）
            model: モデル情報（代替案取得用）

        Returns:
            CostCheckResult
        """
        settings = self.get_settings()
        daily_cost = self._get_daily_cost()
        monthly_summary = self._get_monthly_summary()

        monthly_cost = monthly_summary.get("total_cost_jpy", Decimal("0"))
        budget_remaining = settings.monthly_budget_jpy - monthly_cost

        # 予算状態を判定
        budget_status = self._calculate_budget_status(
            budget_remaining,
            settings.monthly_budget_jpy
        )

        # 日次コストで閾値判定
        projected_daily_cost = daily_cost + estimated_cost_jpy

        # アクション決定
        if budget_status == BudgetStatus.LIMIT:
            action = CostAction.BLOCK
            message = f"月間予算を超過しています（残予算: ¥{budget_remaining:.0f}）"
        elif projected_daily_cost >= settings.cost_threshold_limit:
            action = CostAction.SHOW_ALTERNATIVES
            message = f"本日の利用コストが¥{projected_daily_cost:.0f}になります。代替案を検討してください。"
        elif projected_daily_cost >= settings.cost_threshold_caution:
            action = CostAction.ASK_BEFORE
            message = f"¥{estimated_cost_jpy:.0f}かかりそうウル。実行していい？"
        elif projected_daily_cost >= settings.cost_threshold_warning:
            action = CostAction.EXECUTE_WITH_REPORT
            message = f"完了ウル。コスト: ¥{estimated_cost_jpy:.0f}"
        else:
            action = CostAction.AUTO_EXECUTE
            message = None

        return CostCheckResult(
            estimated_cost_jpy=estimated_cost_jpy,
            daily_cost_jpy=daily_cost,
            monthly_cost_jpy=monthly_cost,
            budget_remaining_jpy=budget_remaining,
            budget_status=budget_status,
            action=action,
            message=message,
        )

    def _calculate_budget_status(
        self,
        budget_remaining: Decimal,
        total_budget: Decimal
    ) -> BudgetStatus:
        """予算状態を計算"""
        if total_budget <= 0:
            return BudgetStatus.NORMAL

        remaining_ratio = budget_remaining / total_budget

        if remaining_ratio <= BUDGET_STATUS_THRESHOLDS[BudgetStatus.LIMIT]:
            return BudgetStatus.LIMIT
        elif remaining_ratio <= BUDGET_STATUS_THRESHOLDS[BudgetStatus.CAUTION]:
            return BudgetStatus.CAUTION
        elif remaining_ratio <= BUDGET_STATUS_THRESHOLDS[BudgetStatus.WARNING]:
            return BudgetStatus.WARNING
        else:
            return BudgetStatus.NORMAL

    # -------------------------------------------------------------------------
    # 日次/月次コスト取得
    # -------------------------------------------------------------------------

    def _get_daily_cost(self) -> Decimal:
        """本日の累計コストを取得"""
        today = date.today().isoformat()

        query = text("""
            SELECT COALESCE(SUM(cost_jpy), 0)
            FROM ai_usage_logs
            WHERE organization_id = CAST(:org_id AS uuid)
              AND DATE(created_at) = :today
              AND success = TRUE
        """)

        try:
            with self._pool.connect() as conn:
                result = conn.execute(query, {
                    "org_id": self._organization_id,
                    "today": today,
                })
                row = result.fetchone()
                return Decimal(str(row[0])) if row else Decimal("0")

        except Exception as e:
            logger.error(f"Failed to get daily cost: {type(e).__name__}")
            return Decimal("0")

    def _get_monthly_summary(self) -> Dict[str, Any]:
        """当月のサマリーを取得"""
        year_month = datetime.now().strftime("%Y-%m")

        query = text("""
            SELECT
                total_cost_jpy,
                total_requests,
                total_input_tokens,
                total_output_tokens,
                budget_jpy,
                budget_remaining_jpy,
                budget_status
            FROM ai_monthly_cost_summary
            WHERE organization_id = CAST(:org_id AS uuid)
              AND year_month = :year_month
        """)

        try:
            with self._pool.connect() as conn:
                result = conn.execute(query, {
                    "org_id": self._organization_id,
                    "year_month": year_month,
                })
                row = result.fetchone()

                if row is None:
                    return {
                        "total_cost_jpy": Decimal("0"),
                        "total_requests": 0,
                        "total_input_tokens": 0,
                        "total_output_tokens": 0,
                        "budget_jpy": MonthlyBudget.DEFAULT_JPY,
                        "budget_remaining_jpy": MonthlyBudget.DEFAULT_JPY,
                        "budget_status": BudgetStatus.NORMAL.value,
                    }

                return {
                    "total_cost_jpy": Decimal(str(row[0])),
                    "total_requests": row[1],
                    "total_input_tokens": row[2],
                    "total_output_tokens": row[3],
                    "budget_jpy": Decimal(str(row[4])) if row[4] else MonthlyBudget.DEFAULT_JPY,
                    "budget_remaining_jpy": Decimal(str(row[5])) if row[5] else MonthlyBudget.DEFAULT_JPY,
                    "budget_status": row[6] or BudgetStatus.NORMAL.value,
                }

        except Exception as e:
            logger.error(f"Failed to get monthly summary: {type(e).__name__}")
            return {
                "total_cost_jpy": Decimal("0"),
                "total_requests": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "budget_jpy": MonthlyBudget.DEFAULT_JPY,
                "budget_remaining_jpy": MonthlyBudget.DEFAULT_JPY,
                "budget_status": BudgetStatus.NORMAL.value,
            }

    # -------------------------------------------------------------------------
    # 月次サマリー更新
    # -------------------------------------------------------------------------

    def update_monthly_summary(
        self,
        cost_jpy: Decimal,
        input_tokens: int,
        output_tokens: int,
        tier: Tier,
        was_fallback: bool = False,
        success: bool = True,
    ) -> None:
        """
        月次サマリーを更新（Upsert）

        Args:
            cost_jpy: コスト（円）
            input_tokens: 入力トークン数
            output_tokens: 出力トークン数
            tier: 使用ティア
            was_fallback: フォールバックだったか
            success: 成功したか
        """
        year_month = datetime.now().strftime("%Y-%m")
        settings = self.get_settings()

        # ティア別コストカラム名
        tier_cost_column = f"{tier.value}_cost_jpy"
        tier_requests_column = f"{tier.value}_requests"

        query = text(f"""
            INSERT INTO ai_monthly_cost_summary (
                organization_id,
                year_month,
                total_cost_jpy,
                total_requests,
                total_input_tokens,
                total_output_tokens,
                {tier_cost_column},
                {tier_requests_column},
                fallback_count,
                fallback_success_count,
                error_count,
                budget_jpy,
                budget_remaining_jpy,
                budget_status
            ) VALUES (
                CAST(:org_id AS uuid),
                :year_month,
                :cost_jpy,
                1,
                :input_tokens,
                :output_tokens,
                :cost_jpy,
                1,
                :fallback_count,
                :fallback_success_count,
                :error_count,
                :budget_jpy,
                :budget_remaining_jpy,
                :budget_status
            )
            ON CONFLICT (organization_id, year_month)
            DO UPDATE SET
                total_cost_jpy = ai_monthly_cost_summary.total_cost_jpy + EXCLUDED.total_cost_jpy,
                total_requests = ai_monthly_cost_summary.total_requests + 1,
                total_input_tokens = ai_monthly_cost_summary.total_input_tokens + EXCLUDED.total_input_tokens,
                total_output_tokens = ai_monthly_cost_summary.total_output_tokens + EXCLUDED.total_output_tokens,
                {tier_cost_column} = COALESCE(ai_monthly_cost_summary.{tier_cost_column}, 0) + EXCLUDED.{tier_cost_column},
                {tier_requests_column} = COALESCE(ai_monthly_cost_summary.{tier_requests_column}, 0) + 1,
                fallback_count = ai_monthly_cost_summary.fallback_count + EXCLUDED.fallback_count,
                fallback_success_count = ai_monthly_cost_summary.fallback_success_count + EXCLUDED.fallback_success_count,
                error_count = ai_monthly_cost_summary.error_count + EXCLUDED.error_count,
                budget_remaining_jpy = COALESCE(ai_monthly_cost_summary.budget_jpy, :budget_jpy) - (ai_monthly_cost_summary.total_cost_jpy + EXCLUDED.total_cost_jpy),
                updated_at = NOW()
        """)

        # 予算状態を計算
        monthly_summary = self._get_monthly_summary()
        new_total = monthly_summary["total_cost_jpy"] + cost_jpy
        budget_remaining = settings.monthly_budget_jpy - new_total
        budget_status = self._calculate_budget_status(
            budget_remaining,
            settings.monthly_budget_jpy
        )

        try:
            with self._pool.connect() as conn:
                conn.execute(query, {
                    "org_id": self._organization_id,
                    "year_month": year_month,
                    "cost_jpy": float(cost_jpy),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "fallback_count": 1 if was_fallback else 0,
                    "fallback_success_count": 1 if was_fallback and success else 0,
                    "error_count": 0 if success else 1,
                    "budget_jpy": float(settings.monthly_budget_jpy),
                    "budget_remaining_jpy": float(budget_remaining),
                    "budget_status": budget_status.value,
                })
                conn.commit()

        except Exception as e:
            logger.error(f"Failed to update monthly summary: {type(e).__name__}")
            raise

    # -------------------------------------------------------------------------
    # 設定の初期化/更新
    # -------------------------------------------------------------------------

    def ensure_settings_exist(self) -> None:
        """
        組織設定が存在することを保証（なければ作成）
        """
        query = text("""
            INSERT INTO ai_organization_settings (
                organization_id,
                monthly_budget_jpy,
                cost_threshold_warning,
                cost_threshold_caution,
                cost_threshold_limit,
                default_tier,
                enable_premium_tier,
                enable_auto_downgrade,
                enable_fallback,
                max_fallback_attempts,
                usd_to_jpy_rate
            ) VALUES (
                CAST(:org_id AS uuid),
                :monthly_budget_jpy,
                :cost_threshold_warning,
                :cost_threshold_caution,
                :cost_threshold_limit,
                :default_tier,
                :enable_premium_tier,
                :enable_auto_downgrade,
                :enable_fallback,
                :max_fallback_attempts,
                :usd_to_jpy_rate
            )
            ON CONFLICT (organization_id) DO NOTHING
        """)

        defaults = self._get_default_settings()

        try:
            with self._pool.connect() as conn:
                conn.execute(query, {
                    "org_id": self._organization_id,
                    "monthly_budget_jpy": float(defaults.monthly_budget_jpy),
                    "cost_threshold_warning": float(defaults.cost_threshold_warning),
                    "cost_threshold_caution": float(defaults.cost_threshold_caution),
                    "cost_threshold_limit": float(defaults.cost_threshold_limit),
                    "default_tier": defaults.default_tier,
                    "enable_premium_tier": defaults.enable_premium_tier,
                    "enable_auto_downgrade": defaults.enable_auto_downgrade,
                    "enable_fallback": defaults.enable_fallback,
                    "max_fallback_attempts": defaults.max_fallback_attempts,
                    "usd_to_jpy_rate": float(defaults.usd_to_jpy_rate),
                })
                conn.commit()

        except Exception as e:
            logger.error(f"Failed to ensure settings exist: {type(e).__name__}")
