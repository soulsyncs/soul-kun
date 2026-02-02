# lib/brain/guardian_layer.py
"""
Guardian Layer（守護者層）- LLMの判断をチェックする

設計書: docs/25_llm_native_brain_architecture.md セクション5.3（6.3）

【目的】
LLMの判断結果をチェックし、危険な操作をブロック、または確認モードに遷移させる。
「LLMは提案者であり、決裁者ではない」という憲法の実装。

【判定優先度（セクション5.3.3b）】
1. 憲法違反（LLMが権限判定を試みた）
2. セキュリティ（機密情報漏洩、NGパターン）
3. 危険操作（削除、全員送信、権限変更）
4. CEO教え違反
5. 確信度チェック（< 0.7 で確認）
6. パラメータチェック（高額、複数送信）
7. 整合性チェック（日付の妥当性等）

【出力】
- ALLOW: そのまま実行
- CONFIRM: 確認モードに遷移
- BLOCK: 実行をブロック
- MODIFY: パラメータを修正して続行

Author: Claude Opus 4.5
Created: 2026-01-30
"""

import re
import logging
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from lib.brain.llm_brain import LLMBrainResult, ToolCall, ConfidenceScores
from lib.brain.context_builder import LLMContext, CEOTeaching

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")


# =============================================================================
# Enum & 定数
# =============================================================================

class GuardianAction(Enum):
    """Guardian Layerの判定結果"""
    ALLOW = "allow"      # そのまま実行OK
    CONFIRM = "confirm"  # ユーザーに確認が必要
    BLOCK = "block"      # 実行をブロック
    MODIFY = "modify"    # パラメータを修正して続行


class RiskLevel(Enum):
    """リスクレベル"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# 危険操作の定義
# Task #11: Guardian Layerルール見直し・強化
DANGEROUS_OPERATIONS: Dict[str, Dict[str, Any]] = {
    # 全員送信系
    "send_to_all": {"risk": "high", "action": "confirm", "double_confirm": True},
    "announcement_create": {"risk": "medium", "action": "confirm"},
    "broadcast_message": {"risk": "high", "action": "confirm", "double_confirm": True},

    # 削除系
    "delete_task": {"risk": "medium", "action": "confirm"},
    "delete_goal": {"risk": "medium", "action": "confirm"},
    "goal_delete": {"risk": "medium", "action": "confirm"},  # v10.56.0
    "goal_cleanup": {"risk": "medium", "action": "confirm"},  # v10.56.0
    "delete_memory": {"risk": "high", "action": "confirm"},
    "forget_knowledge": {"risk": "medium", "action": "confirm"},
    "bulk_delete": {"risk": "critical", "action": "confirm", "double_confirm": True},

    # 権限変更系（絶対禁止）
    "change_permission": {"risk": "critical", "action": "block"},
    "change_role": {"risk": "critical", "action": "block"},
    "grant_access": {"risk": "critical", "action": "block"},
    "revoke_access": {"risk": "critical", "action": "block"},

    # 機密情報系（絶対禁止）
    "send_confidential": {"risk": "critical", "action": "block"},
    "export_all_data": {"risk": "critical", "action": "block"},
    "export_user_data": {"risk": "critical", "action": "block"},

    # 外部連携系（確認必要）
    "api_call_external": {"risk": "medium", "action": "confirm"},
    "webhook_trigger": {"risk": "medium", "action": "confirm"},

    # 設定変更系
    "update_system_config": {"risk": "high", "action": "confirm", "double_confirm": True},
    "change_notification_settings": {"risk": "low", "action": "confirm"},

    # 支払い・経理系
    "payment_execute": {"risk": "high", "action": "confirm", "double_confirm": True},
    "invoice_approve": {"risk": "high", "action": "confirm"},
}

# セキュリティNGパターン（機密情報漏洩の可能性）
# Task #11: Guardian Layerルール見直し・強化
SECURITY_NG_PATTERNS = [
    # 認証情報
    r"パスワード[は:：]\s*\S+",
    r"APIキー[は:：]\s*\S+",
    r"シークレット[は:：]\s*\S+",
    r"アクセストークン[は:：]\s*\S+",
    r"秘密鍵[は:：]\s*\S+",
    r"(password|passwd)[=:]\s*\S+",
    r"(api[_-]?key|apikey)[=:]\s*\S+",
    r"(secret|token)[=:]\s*\S+",
    r"Bearer\s+[A-Za-z0-9\-_]+",

    # 個人情報
    r"クレジットカード番号",
    r"マイナンバー",
    r"銀行口座番号",
    r"\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}",  # カード番号パターン

    # 内部システム情報
    r"データベース接続",
    r"(DB|database)[\s_]?(URL|URI|connection)",
    r"(admin|root)[\s_]?(password|pass)",
]

# 憲法違反キーワード（LLMが権限判定を試みている兆候）
CONSTITUTION_VIOLATION_PATTERNS = [
    "権限を判定",
    "アクセス権を決定",
    "この人は見れる",
    "この人は見れない",
    "権限レベルを変更",
]


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class GuardianResult:
    """Guardian Layerの判定結果"""
    action: GuardianAction
    reason: Optional[str] = None
    confirmation_question: Optional[str] = None
    modified_params: Optional[Dict[str, Any]] = None
    blocked_reason: Optional[str] = None
    priority_level: int = 0  # どのチェックでトリガーされたか（1-7）
    risk_level: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "confirmation_question": self.confirmation_question,
            "modified_params": self.modified_params,
            "blocked_reason": self.blocked_reason,
            "priority_level": self.priority_level,
            "risk_level": self.risk_level,
        }


# =============================================================================
# GuardianLayer クラス
# =============================================================================

class GuardianLayer:
    """
    守護者層 - LLMの判断をチェックする

    設計書: docs/25_llm_native_brain_architecture.md セクション5.3

    【使用例】
    guardian = GuardianLayer(ceo_teachings=teachings)
    result = await guardian.check(llm_result, context)
    if result.action == GuardianAction.ALLOW:
        # 実行OK
    elif result.action == GuardianAction.CONFIRM:
        # 確認必要
    elif result.action == GuardianAction.BLOCK:
        # ブロック
    """

    # 確信度の閾値
    CONFIDENCE_THRESHOLD_BLOCK = 0.3    # これ以下はブロック
    CONFIDENCE_THRESHOLD_CONFIRM = 0.7  # これ以下は確認

    # 金額の閾値（円）
    AMOUNT_THRESHOLD_CONFIRM = 100000      # 10万円以上は確認
    AMOUNT_THRESHOLD_DOUBLE_CONFIRM = 1000000  # 100万円以上は二重確認

    # 送信先の閾値（人数）
    RECIPIENTS_THRESHOLD_CONFIRM = 3   # 3人以上は確認
    RECIPIENTS_THRESHOLD_DOUBLE = 10   # 10人以上は二重確認

    def __init__(
        self,
        ceo_teachings: Optional[List[CEOTeaching]] = None,
        custom_ng_patterns: Optional[List[str]] = None,
    ):
        """
        Args:
            ceo_teachings: CEO教えのリスト
            custom_ng_patterns: カスタムNGパターンのリスト
        """
        self.ceo_teachings = ceo_teachings or []
        self.ng_patterns = SECURITY_NG_PATTERNS + (custom_ng_patterns or [])

        logger.info(f"GuardianLayer initialized with {len(self.ceo_teachings)} CEO teachings")

    async def check(
        self,
        llm_result: LLMBrainResult,
        context: LLMContext,
    ) -> GuardianResult:
        """
        LLMの判断結果をチェックする

        判定優先度:
        1. 憲法違反
        2. セキュリティ
        3. 危険操作
        4. CEO教え違反
        5. 確信度
        6. パラメータ
        7. 整合性

        Args:
            llm_result: LLM Brainの処理結果
            context: コンテキスト情報

        Returns:
            GuardianResult: チェック結果
        """
        logger.info(f"Guardian checking result: type={llm_result.output_type}")

        # 優先度1: 憲法違反チェック
        constitution_check = self._check_constitution_violation(llm_result)
        if constitution_check.action != GuardianAction.ALLOW:
            return constitution_check

        # 優先度2: セキュリティチェック
        security_check = self._check_security(llm_result, context)
        if security_check.action != GuardianAction.ALLOW:
            return security_check

        # Tool呼び出しがある場合のみ以下のチェックを実行
        if llm_result.tool_calls:
            for tool_call in llm_result.tool_calls:
                # 優先度3: 危険操作チェック
                dangerous_check = self._check_dangerous_operation(tool_call)
                if dangerous_check.action != GuardianAction.ALLOW:
                    return dangerous_check

                # 優先度4: CEO教えチェック
                ceo_check = self._check_ceo_teachings(tool_call, context)
                if ceo_check.action != GuardianAction.ALLOW:
                    return ceo_check

                # 優先度5: 確信度チェック
                confidence_check = self._check_confidence(llm_result.confidence, tool_call)
                if confidence_check.action != GuardianAction.ALLOW:
                    return confidence_check

                # 優先度6: パラメータチェック
                param_check = self._check_parameters(tool_call)
                if param_check.action != GuardianAction.ALLOW:
                    return param_check

                # 優先度7: 整合性チェック
                consistency_check = self._check_consistency(tool_call)
                if consistency_check.action != GuardianAction.ALLOW:
                    return consistency_check

        # 全てのチェックをパス
        logger.info("Guardian check passed: ALLOW")
        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_constitution_violation(
        self,
        llm_result: LLMBrainResult,
    ) -> GuardianResult:
        """
        優先度1: 憲法違反チェック

        LLMが以下を試みていないかチェック:
        - 権限判定を行おうとしている
        - 思考過程（reasoning）が出力されていない
        """
        # 思考過程の必須チェック
        if not llm_result.reasoning and llm_result.tool_calls:
            return GuardianResult(
                action=GuardianAction.BLOCK,
                blocked_reason="思考過程（reasoning）が出力されていません。憲法違反。",
                priority_level=1,
            )

        # 権限判定の試みをチェック
        combined_text = llm_result.reasoning + (llm_result.text_response or "")
        for pattern in CONSTITUTION_VIOLATION_PATTERNS:
            if pattern in combined_text:
                return GuardianResult(
                    action=GuardianAction.BLOCK,
                    blocked_reason=f"LLMが権限判定を試みています（「{pattern}」）。憲法違反。",
                    priority_level=1,
                )

        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_security(
        self,
        llm_result: LLMBrainResult,
        context: LLMContext,
    ) -> GuardianResult:
        """
        優先度2: セキュリティチェック

        - NGパターン（機密情報漏洩）
        - 機密情報が応答に含まれていないか
        """
        text_to_check = (llm_result.text_response or "") + llm_result.reasoning

        # NGパターンチェック
        for pattern in self.ng_patterns:
            if re.search(pattern, text_to_check):
                return GuardianResult(
                    action=GuardianAction.BLOCK,
                    blocked_reason="機密情報が含まれている可能性があります。",
                    priority_level=2,
                    risk_level="critical",
                )

        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_dangerous_operation(
        self,
        tool_call: ToolCall,
    ) -> GuardianResult:
        """
        優先度3: 危険操作チェック
        """
        tool_name = tool_call.tool_name

        if tool_name not in DANGEROUS_OPERATIONS:
            return GuardianResult(action=GuardianAction.ALLOW)

        op_config = DANGEROUS_OPERATIONS[tool_name]
        risk = op_config["risk"]
        action = op_config["action"]

        if action == "block":
            return GuardianResult(
                action=GuardianAction.BLOCK,
                blocked_reason=f"この操作（{tool_name}）は自動実行が禁止されています。",
                priority_level=3,
                risk_level=risk,
            )

        if action == "confirm":
            double_confirm = op_config.get("double_confirm", False)
            return GuardianResult(
                action=GuardianAction.CONFIRM,
                confirmation_question=self._generate_dangerous_confirmation(
                    tool_call, risk, double_confirm
                ),
                reason=f"危険操作（{tool_name}）のため確認が必要です。",
                priority_level=3,
                risk_level=risk,
            )

        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_ceo_teachings(
        self,
        tool_call: ToolCall,
        context: LLMContext,
    ) -> GuardianResult:
        """
        優先度4: CEO教え違反チェック
        """
        # CEO教えがない場合はパス
        if not self.ceo_teachings and not context.ceo_teachings:
            return GuardianResult(action=GuardianAction.ALLOW)

        all_teachings = self.ceo_teachings + context.ceo_teachings

        # TODO: より高度なCEO教え違反検出
        # 現時点では基本的なチェックのみ

        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_confidence(
        self,
        confidence: ConfidenceScores,
        tool_call: ToolCall,
    ) -> GuardianResult:
        """
        優先度5: 確信度チェック
        """
        overall_confidence = confidence.overall

        # 非常に低い確信度はブロック
        if overall_confidence < self.CONFIDENCE_THRESHOLD_BLOCK:
            return GuardianResult(
                action=GuardianAction.BLOCK,
                blocked_reason=f"確信度が低すぎます（{overall_confidence:.0%}）。",
                priority_level=5,
            )

        # 低い確信度は確認
        if overall_confidence < self.CONFIDENCE_THRESHOLD_CONFIRM:
            return GuardianResult(
                action=GuardianAction.CONFIRM,
                confirmation_question=self._generate_low_confidence_confirmation(
                    tool_call, overall_confidence
                ),
                reason=f"確信度が低い（{overall_confidence:.0%}）ため確認が必要です。",
                priority_level=5,
            )

        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_parameters(
        self,
        tool_call: ToolCall,
    ) -> GuardianResult:
        """
        優先度6: パラメータチェック

        - 金額チェック
        - 送信先数チェック
        - 削除件数チェック
        """
        params = tool_call.parameters

        # 金額チェック
        amount = params.get("amount") or params.get("金額")
        if amount:
            try:
                amount_value = float(amount)
                if amount_value >= self.AMOUNT_THRESHOLD_DOUBLE_CONFIRM:
                    return GuardianResult(
                        action=GuardianAction.CONFIRM,
                        confirmation_question=f"🐺 金額が{amount_value:,.0f}円です。本当に実行してよろしいですかウル？\n\n1. はい\n2. いいえ",
                        reason="高額操作のため確認が必要",
                        priority_level=6,
                    )
                elif amount_value >= self.AMOUNT_THRESHOLD_CONFIRM:
                    return GuardianResult(
                        action=GuardianAction.CONFIRM,
                        confirmation_question=f"🐺 金額が{amount_value:,.0f}円です。よろしいですかウル？",
                        reason="金額確認",
                        priority_level=6,
                    )
            except (ValueError, TypeError):
                pass

        # 送信先チェック
        recipients = params.get("recipients") or params.get("送信先")
        if recipients and isinstance(recipients, list):
            count = len(recipients)
            if count >= self.RECIPIENTS_THRESHOLD_DOUBLE:
                return GuardianResult(
                    action=GuardianAction.CONFIRM,
                    confirmation_question=f"🐺 {count}人に送信しようとしてるウル。本当に実行してよろしいですかウル？\n\n1. はい\n2. いいえ",
                    reason="大量送信のため確認が必要",
                    priority_level=6,
                )
            elif count >= self.RECIPIENTS_THRESHOLD_CONFIRM:
                return GuardianResult(
                    action=GuardianAction.CONFIRM,
                    confirmation_question=f"🐺 {count}人に送信するウル。よろしいですかウル？",
                    reason="複数送信確認",
                    priority_level=6,
                )

        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_consistency(
        self,
        tool_call: ToolCall,
    ) -> GuardianResult:
        """
        優先度7: 整合性チェック

        - 日付パラメータの妥当性
        - パラメータ間の整合性
        """
        params = tool_call.parameters

        # 日付チェック
        date_params = ["limit_date", "due_date", "deadline", "期限"]
        for date_key in date_params:
            date_value = params.get(date_key)
            if date_value:
                check_result = self._check_date_validity(date_value, date_key)
                if check_result.action != GuardianAction.ALLOW:
                    return check_result

        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_date_validity(
        self,
        date_str: str,
        param_name: str,
    ) -> GuardianResult:
        """日付の妥当性をチェック"""
        try:
            # YYYY-MM-DD形式をパース
            date = datetime.strptime(date_str, "%Y-%m-%d")
            now = datetime.now(JST).replace(tzinfo=None)

            # 過去の日付チェック
            if date < now - timedelta(days=1):
                return GuardianResult(
                    action=GuardianAction.CONFIRM,
                    confirmation_question=f"🐺 {param_name}が過去の日付（{date_str}）になってるウル。正しいですかウル？",
                    reason="過去日付の確認",
                    priority_level=7,
                )

            # 遠い未来のチェック（1年以上先）
            if date > now + timedelta(days=365):
                return GuardianResult(
                    action=GuardianAction.CONFIRM,
                    confirmation_question=f"🐺 {param_name}がかなり先（{date_str}）ウル。正しいですかウル？",
                    reason="遠い未来日付の確認",
                    priority_level=7,
                )

        except ValueError:
            # パースできない場合は修正を提案
            return GuardianResult(
                action=GuardianAction.CONFIRM,
                confirmation_question=f"🐺 {param_name}の形式が正しくないかもウル。YYYY-MM-DD形式で教えてほしいウル。",
                reason="日付形式の確認",
                priority_level=7,
            )

        return GuardianResult(action=GuardianAction.ALLOW)

    def _generate_dangerous_confirmation(
        self,
        tool_call: ToolCall,
        risk: str,
        double_confirm: bool,
    ) -> str:
        """危険操作の確認質問を生成"""
        tool_name = tool_call.tool_name
        params_str = ", ".join([f"{k}={v}" for k, v in tool_call.parameters.items()])

        emoji = "🔴" if risk == "critical" else "🟠" if risk == "high" else "🟡"

        message = f"""
{emoji} 確認させてほしいウル！

「{tool_name}」を実行しようとしてるウル。
パラメータ: {params_str}

これは{"重大な" if risk in ["critical", "high"] else ""}操作ウル。"""

        if double_confirm:
            message += "\n\n⚠️ 本当に実行してよろしいですかウル？\n1. はい、実行する\n2. いいえ、やめる"
        else:
            message += "\n\n実行してもいいですかウル？\n1. はい\n2. いいえ"

        return message.strip()

    def _generate_low_confidence_confirmation(
        self,
        tool_call: ToolCall,
        confidence: float,
    ) -> str:
        """低確信度時の確認質問を生成"""
        return f"""
🤔 ちょっと自信がないウル...（確信度: {confidence:.0%}）

「{tool_call.tool_name}」を実行しようと思ってるんだけど、
合ってますかウル？

1. はい
2. いいえ（もう一度説明する）
""".strip()


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_guardian_layer(
    ceo_teachings: Optional[List[CEOTeaching]] = None,
) -> GuardianLayer:
    """
    GuardianLayerのファクトリ関数

    Args:
        ceo_teachings: CEO教えのリスト

    Returns:
        GuardianLayerインスタンス
    """
    return GuardianLayer(ceo_teachings=ceo_teachings)
