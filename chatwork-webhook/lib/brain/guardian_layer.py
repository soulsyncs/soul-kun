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
8. 操作系チェック（Step C-4: レジストリ・パラメータ長・パス安全性・レート・クォータ）

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
import time
from collections import defaultdict, deque
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Deque, Tuple
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

        # Phase 2E: 学習済みルール（LearningLoopから注入）
        self._learned_rules: List[Dict[str, str]] = []

        # Step C-4: 操作系レートリミッター（インメモリ、インスタンス単位）
        # key: account_id, value: 呼び出しタイムスタンプのdeque
        self._op_call_timestamps: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=100))
        # key: (account_id, date_str), value: {"read": count, "write": count}
        self._op_daily_counts: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(
            lambda: {"read": 0, "write": 0}
        )

        logger.info(f"GuardianLayer initialized with {len(self.ceo_teachings)} CEO teachings")

    def set_learned_rules(self, rules: List[Dict[str, str]]) -> None:
        """LearningLoopから学習済みルールを注入"""
        self._learned_rules = rules

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

                # API制約チェック（ChatWork APIが対応していない機能をブロック）
                api_limit_check = self._check_api_limitation(tool_call)
                if api_limit_check.action != GuardianAction.ALLOW:
                    return api_limit_check

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

                # 優先度8: 操作系チェック（Step C-4）
                op_check = self._check_operation_safety(tool_call, context)
                if op_check.action != GuardianAction.ALLOW:
                    return op_check

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
        # Note: OpenAI API はtool calling時にcontent=nullを返すのが仕様。
        # パーサー側でフォールバックreasoningを生成するが、
        # 万一それも失敗した場合はBLOCKではなくWARNINGに留める。
        if not llm_result.reasoning and llm_result.tool_calls:
            logger.warning(
                "Tool calling with empty reasoning "
                "(tools: %s). Allowing with warning.",
                [tc.tool_name for tc in llm_result.tool_calls],
            )
            # BLOCKせずにALLOWする（パーサーのフォールバックが本来の防御線）

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

    def _check_api_limitation(
        self,
        tool_call: ToolCall,
    ) -> GuardianResult:
        """
        ChatWork API制約チェック

        api_limitationフラグが立っているCapabilityは
        ChatWork APIが対応していないためBLOCKする。
        """
        tool_name = tool_call.tool_name
        try:
            from handlers.registry import SYSTEM_CAPABILITIES
            cap = SYSTEM_CAPABILITIES.get(tool_name, {})
            if cap.get("api_limitation"):
                limitation_msg = cap.get("limitation_message", "この機能")
                return GuardianResult(
                    action=GuardianAction.BLOCK,
                    blocked_reason=f"{limitation_msg}はChatWork APIに対応機能がないため、ソウルくんでは対応できないウル🐺",
                    priority_level=3,
                    risk_level="medium",
                )
        except ImportError:
            pass
        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_ceo_teachings(
        self,
        tool_call: ToolCall,
        context: LLMContext,
    ) -> GuardianResult:
        """
        優先度4: CEO教え違反チェック + Phase 2E学習済みルール
        """
        # CEO教えチェック
        if not self.ceo_teachings and not context.ceo_teachings:
            pass  # CEO教えなし — 学習済みルールのみチェック
        else:
            all_teachings = self.ceo_teachings + context.ceo_teachings
            # Phase 2D-3: CEO教え違反検出
            # ツール呼び出しのテキスト表現を構築（キーワードマッチ用）
            tool_text_parts: List[str] = [
                tool_call.tool_name if tool_call else "",
                tool_call.reasoning if tool_call else "",
            ]
            if tool_call:
                for v in tool_call.parameters.values():
                    if isinstance(v, str):
                        tool_text_parts.append(v)
                    elif not isinstance(v, (bool, int, float)):
                        tool_text_parts.append(str(v))
            tool_text = " ".join(filter(None, tool_text_parts)).lower()

            # 優先度の高い教えから順にチェック
            sorted_teachings = sorted(
                all_teachings, key=lambda t: -(t.priority or 0)
            )
            for teaching in sorted_teachings:
                if not teaching.content:
                    continue

                # 教えのコンテンツから照合語を抽出
                # 日本語助詞・句読点で分割してキーワードを抽出（2文字以上）
                candidate_words = [
                    w for w in re.split(
                        r'[はをがにのでともからまでよりなどへ\s、。！？・…]',
                        teaching.content,
                    )
                    if len(w) >= 2
                ]
                if not candidate_words:
                    continue

                matched = [w for w in candidate_words if w in tool_text]
                if not matched:
                    continue

                stmt_preview = teaching.content[:50]
                kw_str = "、".join(matched[:3])

                # 優先度 >= 8: BLOCK（重要な禁止事項）
                if (teaching.priority or 0) >= 8:
                    logger.warning(
                        f"[guardian:ceo] BLOCK: matched={matched}, "
                        f"priority={teaching.priority}, category={teaching.category}"
                    )
                    return GuardianResult(
                        action=GuardianAction.BLOCK,
                        reason=f"CEO教え違反の可能性: {stmt_preview}",
                        blocked_reason=(
                            f"CEOの教え「{stmt_preview}」に反する操作が検出されました。"
                            f"（検出語: {kw_str}）"
                        ),
                        priority_level=4,
                    )

                # 優先度 >= 4: CONFIRM（確認が必要な事項）
                if (teaching.priority or 0) >= 4:
                    logger.info(
                        f"[guardian:ceo] CONFIRM: matched={matched}, "
                        f"priority={teaching.priority}, category={teaching.category}"
                    )
                    return GuardianResult(
                        action=GuardianAction.CONFIRM,
                        reason=f"CEO教え照合: {stmt_preview}",
                        confirmation_question=(
                            f"CEOの教え「{stmt_preview}」に関連する操作です。"
                            f"この操作を実行してよいですか？（検出語: {kw_str}）"
                        ),
                        priority_level=4,
                    )
            # 低優先度の一致 or 一致なし → スルー

        # Phase 2E: 学習済みルールをチェック
        tool_name = tool_call.tool_name if tool_call else ""
        for rule in self._learned_rules:
            condition = rule.get("condition", "")
            if not condition:
                continue
            # ルール条件がツール名に一致するか確認
            if condition.lower() in tool_name.lower():
                rule_action = rule.get("action", "confirm")
                if rule_action == "block":
                    return GuardianResult(
                        action=GuardianAction.BLOCK,
                        reason=f"学習済みルール: {rule.get('description', condition)}",
                        priority_level=4,
                    )
                elif rule_action == "confirm":
                    return GuardianResult(
                        action=GuardianAction.CONFIRM,
                        confirmation_question=f"学習済みルールに基づく確認: {rule.get('description', condition)}",
                        reason=f"学習済みルール: {rule.get('description', condition)}",
                        priority_level=4,
                    )

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

    # =========================================================================
    # Step C-4: 操作系チェック（優先度8）
    # =========================================================================

    def _is_operation_tool(self, tool_name: str) -> bool:
        """操作系ツール（category="operations" かつ enabled）かどうかを判定"""
        try:
            from handlers.registry import SYSTEM_CAPABILITIES
            cap = SYSTEM_CAPABILITIES.get(tool_name)
            return (cap is not None
                    and cap.get("category") == "operations"
                    and cap.get("enabled", True))
        except ImportError:
            return False

    def _check_operation_safety(
        self,
        tool_call: ToolCall,
        context: LLMContext,
    ) -> GuardianResult:
        """
        優先度8: 操作系の安全性チェック（Step C-4）

        操作系ツール（category="operations"）にのみ適用。
        5つのチェックを順番に実行する:
        1. レジストリ登録チェック
        2. パラメータ長チェック
        3. パス安全性チェック
        4. 連続実行チェック（レートリミット）
        5. 日次クォータチェック
        """
        tool_name = tool_call.tool_name

        # 操作系ツールでなければスキップ
        if not self._is_operation_tool(tool_name):
            return GuardianResult(action=GuardianAction.ALLOW)

        # 8-1: レジストリ登録チェック
        registry_check = self._check_operation_registry(tool_name)
        if registry_check.action != GuardianAction.ALLOW:
            return registry_check

        # 8-2: パラメータ長チェック
        param_len_check = self._check_operation_param_length(tool_call)
        if param_len_check.action != GuardianAction.ALLOW:
            return param_len_check

        # 8-3: パス安全性チェック
        path_check = self._check_operation_path_safety(tool_call)
        if path_check.action != GuardianAction.ALLOW:
            return path_check

        # 8-4: 連続実行チェック
        account_id = getattr(context, "account_id", None) or "unknown"
        rate_check = self._check_operation_rate_limit(tool_name, account_id)
        if rate_check.action != GuardianAction.ALLOW:
            return rate_check

        # 8-5: 日次クォータチェック
        quota_check = self._check_operation_daily_quota(tool_name, account_id)
        if quota_check.action != GuardianAction.ALLOW:
            return quota_check

        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_operation_registry(self, tool_name: str) -> GuardianResult:
        """8-1: 操作がレジストリに登録されているか

        operations/registry の _registry と、handlers/registry の
        SYSTEM_CAPABILITIES の両方をチェックする。
        どちらかに登録されていれば許可。
        """
        try:
            from lib.brain.operations.registry import is_registered
            if is_registered(tool_name):
                return GuardianResult(action=GuardianAction.ALLOW)
        except ImportError:
            pass

        # _registry が空でも、SYSTEM_CAPABILITIES に category=operations として
        # 登録・有効化されているツールは正規ツールとして許可する
        try:
            from handlers.registry import SYSTEM_CAPABILITIES
            cap = SYSTEM_CAPABILITIES.get(tool_name)
            if (cap is not None
                    and cap.get("category") == "operations"
                    and cap.get("enabled", True)):
                return GuardianResult(action=GuardianAction.ALLOW)
        except ImportError:
            pass

        logger.warning(
            "Guardian: unregistered operation blocked: %s", tool_name
        )
        return GuardianResult(
            action=GuardianAction.BLOCK,
            blocked_reason=f"操作「{tool_name}」はレジストリに登録されていません。",
            priority_level=8,
            risk_level="critical",
        )

    def _check_operation_param_length(self, tool_call: ToolCall) -> GuardianResult:
        """8-2: パラメータが異常に長くないか（200文字超）"""
        for key, value in tool_call.parameters.items():
            if isinstance(value, str) and len(value) > 200:
                logger.warning(
                    "Guardian: operation param too long: %s=%d chars",
                    key, len(value),
                )
                return GuardianResult(
                    action=GuardianAction.CONFIRM,
                    confirmation_question=(
                        f"🐺 パラメータ「{key}」が{len(value)}文字と長いウル。"
                        f"正しいですかウル？"
                    ),
                    reason=f"パラメータ長超過: {key}={len(value)}文字",
                    priority_level=8,
                )
        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_operation_path_safety(self, tool_call: ToolCall) -> GuardianResult:
        """8-3: パラメータにパストラバーサルや絶対パスがないか"""
        path_keys = ("path", "file_path", "data_source", "file")
        for key in path_keys:
            value = tool_call.parameters.get(key)
            if not isinstance(value, str):
                continue
            if ".." in value:
                return GuardianResult(
                    action=GuardianAction.BLOCK,
                    blocked_reason=f"パラメータ「{key}」に不正なパスパターン（..）が含まれています。",
                    priority_level=8,
                    risk_level="critical",
                )
            if value.startswith("/"):
                return GuardianResult(
                    action=GuardianAction.BLOCK,
                    blocked_reason=f"パラメータ「{key}」に絶対パスが指定されています。",
                    priority_level=8,
                    risk_level="critical",
                )
        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_operation_rate_limit(self, tool_name: str, account_id: str) -> GuardianResult:
        """8-4: 連続実行チェック（>5回/分 or >3回/10秒でブロック）"""
        from lib.brain.operations.registry import (
            OPERATION_RATE_LIMIT_PER_MINUTE,
            OPERATION_BURST_LIMIT_PER_10SEC,
        )

        now = time.time()
        timestamps = self._op_call_timestamps[account_id]

        # バースト検出（10秒以内のコール数）
        recent_10s = sum(1 for t in timestamps if now - t < 10)
        if recent_10s >= OPERATION_BURST_LIMIT_PER_10SEC:
            logger.warning(
                "Guardian: operation burst limit hit: %s (%d/10s)",
                account_id, recent_10s,
            )
            return GuardianResult(
                action=GuardianAction.BLOCK,
                blocked_reason=f"操作の連続実行が多すぎます（10秒以内に{recent_10s}回）。少し待ってからお試しください。",
                priority_level=8,
                risk_level="high",
            )

        # 分間レート制限
        recent_1m = sum(1 for t in timestamps if now - t < 60)
        if recent_1m >= OPERATION_RATE_LIMIT_PER_MINUTE:
            logger.warning(
                "Guardian: operation rate limit hit: %s (%d/min)",
                account_id, recent_1m,
            )
            return GuardianResult(
                action=GuardianAction.BLOCK,
                blocked_reason=f"操作の実行回数制限を超えました（1分以内に{recent_1m}回）。少し待ってからお試しください。",
                priority_level=8,
                risk_level="high",
            )

        # タイムスタンプを記録
        timestamps.append(now)
        return GuardianResult(action=GuardianAction.ALLOW)

    def _check_operation_daily_quota(self, tool_name: str, account_id: str) -> GuardianResult:
        """8-5: 日次クォータチェック（読み取り50回/日、書き込み20回/日）"""
        from lib.brain.operations.registry import (
            OPERATION_DAILY_QUOTA_READ,
            OPERATION_DAILY_QUOTA_WRITE,
        )
        from lib.brain.constants import RISK_LEVELS

        today_str = date.today().isoformat()
        key = (account_id, today_str)
        counts = self._op_daily_counts[key]

        # risk_levelから読み取り/書き込みを判定
        risk = RISK_LEVELS.get(tool_name, "medium")
        if risk in ("medium", "high", "critical"):
            op_type = "write"
            quota = OPERATION_DAILY_QUOTA_WRITE
        else:
            op_type = "read"
            quota = OPERATION_DAILY_QUOTA_READ

        if counts[op_type] >= quota:
            logger.warning(
                "Guardian: daily quota exceeded: %s %s=%d/%d",
                account_id, op_type, counts[op_type], quota,
            )
            return GuardianResult(
                action=GuardianAction.BLOCK,
                blocked_reason=f"本日の{op_type}操作の上限（{quota}回）に達しました。明日以降にお試しください。",
                priority_level=8,
                risk_level="high",
            )

        counts[op_type] += 1
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
