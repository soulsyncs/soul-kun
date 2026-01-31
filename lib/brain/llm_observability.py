# lib/brain/llm_observability.py
"""
LLM Brain 専用 Observability Layer

設計書: docs/25_llm_native_brain_architecture.md セクション15

【目的】
LLM Brain の全判断過程を記録し、以下を実現する:
- 本番モニタリング（応答時間、エラー率、コスト）
- パフォーマンス分析
- ユーザーフィードバック収集
- 障害時のデバッグ

【記録する情報】
- 入力メッセージ（先頭200文字、プライバシー保護）
- LLMの思考過程（Chain-of-Thought）
- 選択されたTool・パラメータ
- Guardian/AuthGateの判定結果
- 実行結果
- コスト情報

【10の鉄則】
- #1 全テーブルにorganization_id → 全ログにorg_idを付与
- #3 監査ログ記録 → confidentialとして記録
- #9 SQLパラメータ化 → プリペアドステートメント使用

Author: Claude Opus 4.5
Created: 2026-01-31
"""

from __future__ import annotations

import os
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from lib.brain.llm_brain import LLMBrainResult, ToolCall, ConfidenceScores
    from lib.brain.guardian_layer import GuardianResult

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================

# コスト計算用（GPT-5.2 via OpenRouter、2026-01時点）
# 参照: https://openrouter.ai/openai/gpt-5.2
COST_PER_1M_INPUT_TOKENS_USD = 1.75   # $1.75/M input tokens
COST_PER_1M_OUTPUT_TOKENS_USD = 14.0  # $14.00/M output tokens
USD_TO_JPY = 154  # 為替レート（概算）

# 環境
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
VERSION = os.getenv("SOULKUN_VERSION", "10.53.5")


# =============================================================================
# Enum
# =============================================================================

class LLMLogType(str, Enum):
    """LLM Brain ログタイプ"""
    LLM_PROCESS = "llm_process"           # LLM処理全体
    GUARDIAN_CHECK = "guardian_check"     # Guardian判定
    AUTH_GATE_CHECK = "auth_gate_check"   # Authorization Gate判定
    TOOL_EXECUTION = "tool_execution"     # Tool実行
    CONFIRMATION = "confirmation"          # 確認フロー
    ERROR = "error"                        # エラー


class ConfirmationStatus(str, Enum):
    """確認フローのステータス"""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class LLMBrainLog:
    """
    LLM Brain ログエントリ

    brain_observability_logs テーブルに対応するデータ構造。
    """
    # ========================================
    # 識別情報
    # ========================================
    organization_id: str
    user_id: str
    room_id: Optional[str] = None
    session_id: Optional[str] = None

    # ========================================
    # リクエスト情報
    # ========================================
    message_preview: Optional[str] = None
    message_hash: Optional[str] = None

    # ========================================
    # LLM Brain 判断情報
    # ========================================
    detected_intent: Optional[str] = None
    output_type: str = "text_response"
    reasoning: Optional[str] = None

    # Tool情報
    tool_name: Optional[str] = None
    tool_parameters: Optional[Dict[str, Any]] = None
    tool_count: int = 0

    # 確信度
    confidence_overall: Optional[float] = None
    confidence_intent: Optional[float] = None
    confidence_parameters: Optional[float] = None

    # ========================================
    # Guardian Layer 判定情報
    # ========================================
    guardian_action: Optional[str] = None
    guardian_reason: Optional[str] = None
    guardian_risk_level: Optional[str] = None
    guardian_check_type: Optional[str] = None

    # ========================================
    # Authorization Gate 判定情報
    # ========================================
    auth_gate_action: Optional[str] = None
    auth_gate_reason: Optional[str] = None

    # ========================================
    # 実行結果
    # ========================================
    execution_success: Optional[bool] = None
    execution_error_code: Optional[str] = None
    execution_error_message: Optional[str] = None
    execution_result_summary: Optional[str] = None

    # ========================================
    # パフォーマンス・コスト情報
    # ========================================
    model_used: Optional[str] = None
    api_provider: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    llm_response_time_ms: Optional[int] = None
    guardian_check_time_ms: Optional[int] = None
    total_response_time_ms: Optional[int] = None
    estimated_cost_yen: Optional[Decimal] = None

    # ========================================
    # 確認フロー情報
    # ========================================
    needs_confirmation: bool = False
    confirmation_question: Optional[str] = None
    confirmation_status: Optional[str] = None

    # ========================================
    # メタデータ
    # ========================================
    environment: str = field(default_factory=lambda: ENVIRONMENT)
    version: str = field(default_factory=lambda: VERSION)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def calculate_cost(self) -> Decimal:
        """
        コストを計算（円）

        GPT-5.2の料金:
        - 入力: $1.75/1M tokens
        - 出力: $14.00/1M tokens
        """
        input_cost_usd = (self.input_tokens / 1_000_000) * COST_PER_1M_INPUT_TOKENS_USD
        output_cost_usd = (self.output_tokens / 1_000_000) * COST_PER_1M_OUTPUT_TOKENS_USD
        total_usd = input_cost_usd + output_cost_usd
        total_yen = Decimal(str(total_usd)) * Decimal(str(USD_TO_JPY))
        return round(total_yen, 4)

    def to_dict(self) -> Dict[str, Any]:
        """DB挿入用の辞書を生成"""
        # コストを計算
        if self.estimated_cost_yen is None:
            self.estimated_cost_yen = self.calculate_cost()

        return {
            "organization_id": self.organization_id,
            "user_id": self.user_id,
            "room_id": self.room_id,
            "session_id": self.session_id,
            "message_preview": self.message_preview,
            "message_hash": self.message_hash,
            "detected_intent": self.detected_intent,
            "output_type": self.output_type,
            "reasoning": self.reasoning,
            "tool_name": self.tool_name,
            "tool_parameters": self.tool_parameters,
            "tool_count": self.tool_count,
            "confidence_overall": self.confidence_overall,
            "confidence_intent": self.confidence_intent,
            "confidence_parameters": self.confidence_parameters,
            "guardian_action": self.guardian_action,
            "guardian_reason": self.guardian_reason,
            "guardian_risk_level": self.guardian_risk_level,
            "guardian_check_type": self.guardian_check_type,
            "auth_gate_action": self.auth_gate_action,
            "auth_gate_reason": self.auth_gate_reason,
            "execution_success": self.execution_success,
            "execution_error_code": self.execution_error_code,
            "execution_error_message": self.execution_error_message,
            "execution_result_summary": self.execution_result_summary,
            "model_used": self.model_used,
            "api_provider": self.api_provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "llm_response_time_ms": self.llm_response_time_ms,
            "guardian_check_time_ms": self.guardian_check_time_ms,
            "total_response_time_ms": self.total_response_time_ms,
            "estimated_cost_yen": float(self.estimated_cost_yen) if self.estimated_cost_yen else None,
            "needs_confirmation": self.needs_confirmation,
            "confirmation_question": self.confirmation_question,
            "confirmation_status": self.confirmation_status,
            "environment": self.environment,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
        }

    def to_log_string(self) -> str:
        """Cloud Logging用の構造化ログ文字列"""
        parts = [
            f"🧠 LLM Brain Log",
            f"user={self.user_id}",
            f"type={self.output_type}",
        ]

        if self.tool_name:
            parts.append(f"tool={self.tool_name}")

        if self.confidence_overall is not None:
            parts.append(f"conf={self.confidence_overall:.2f}")

        if self.guardian_action:
            parts.append(f"guardian={self.guardian_action}")

        if self.execution_success is not None:
            status = "ok" if self.execution_success else "error"
            parts.append(f"exec={status}")

        if self.total_response_time_ms:
            parts.append(f"time={self.total_response_time_ms}ms")

        if self.estimated_cost_yen:
            parts.append(f"cost=¥{self.estimated_cost_yen:.2f}")

        return " ".join(parts)


# =============================================================================
# LLMBrainObservability クラス
# =============================================================================

class LLMBrainObservability:
    """
    LLM Brain 専用 Observability

    Usage:
        obs = LLMBrainObservability(pool=db_pool, org_id="org_xxx")

        # LLM処理結果をログ
        log = obs.log_llm_process(
            user_id="12345",
            message="タスク追加して",
            result=llm_brain_result,
            response_time_ms=1500,
        )

        # Guardian判定をログ
        obs.log_guardian_check(
            log_entry=log,
            guardian_result=guardian_result,
            check_time_ms=50,
        )

        # DBに保存
        await obs.save(log)
    """

    def __init__(
        self,
        pool=None,
        org_id: str = "",
        enable_cloud_logging: bool = True,
        enable_persistence: bool = True,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール（asyncpg）
            org_id: 組織ID
            enable_cloud_logging: Cloud Loggingへの出力を有効にするか
            enable_persistence: DBへの永続化を有効にするか
        """
        self.pool = pool
        self.org_id = org_id
        self.enable_cloud_logging = enable_cloud_logging
        self.enable_persistence = enable_persistence

        # バッファ（バッチ挿入用）
        self._buffer: List[LLMBrainLog] = []
        self._buffer_max_size = 100

        logger.debug(
            f"LLMBrainObservability initialized: "
            f"org_id={org_id}, persistence={enable_persistence}"
        )

    # =========================================================================
    # ログ作成メソッド
    # =========================================================================

    def create_log(
        self,
        user_id: str,
        room_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
    ) -> LLMBrainLog:
        """
        新しいログエントリを作成

        Args:
            user_id: ユーザーID
            room_id: ルームID
            session_id: セッションID
            message: 入力メッセージ

        Returns:
            LLMBrainLog
        """
        log = LLMBrainLog(
            organization_id=self.org_id,
            user_id=user_id,
            room_id=room_id,
            session_id=session_id,
        )

        if message:
            # メッセージのプレビュー（先頭200文字、プライバシー保護）
            log.message_preview = message[:200].replace('\n', ' ')
            # ハッシュ（重複検出用）
            log.message_hash = hashlib.sha256(message.encode()).hexdigest()

        return log

    def log_llm_process(
        self,
        user_id: str,
        message: str,
        result: "LLMBrainResult",
        response_time_ms: int,
        room_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> LLMBrainLog:
        """
        LLM処理結果をログ

        Args:
            user_id: ユーザーID
            message: 入力メッセージ
            result: LLMBrainResult
            response_time_ms: LLM応答時間（ミリ秒）
            room_id: ルームID
            session_id: セッションID

        Returns:
            LLMBrainLog
        """
        log = self.create_log(user_id, room_id, session_id, message)

        # LLM Brain結果を設定
        log.output_type = result.output_type
        log.reasoning = result.reasoning
        log.model_used = result.model_used
        log.api_provider = result.api_provider
        log.input_tokens = result.input_tokens
        log.output_tokens = result.output_tokens
        log.llm_response_time_ms = response_time_ms

        # 確信度
        if result.confidence:
            log.confidence_overall = result.confidence.overall
            log.confidence_intent = result.confidence.intent
            log.confidence_parameters = result.confidence.parameters

        # Tool情報
        if result.tool_calls:
            log.tool_count = len(result.tool_calls)
            if result.tool_calls:
                first_tool = result.tool_calls[0]
                log.tool_name = first_tool.tool_name
                log.tool_parameters = first_tool.parameters

        # 確認情報
        log.needs_confirmation = result.needs_confirmation
        log.confirmation_question = result.confirmation_question
        if result.needs_confirmation:
            log.confirmation_status = ConfirmationStatus.PENDING.value

        # コスト計算
        log.estimated_cost_yen = log.calculate_cost()

        # Cloud Loggingに出力
        if self.enable_cloud_logging:
            logger.info(log.to_log_string())

        return log

    def log_guardian_check(
        self,
        log_entry: LLMBrainLog,
        guardian_result: "GuardianResult",
        check_time_ms: int,
    ) -> LLMBrainLog:
        """
        Guardian Layer判定結果をログに追加

        Args:
            log_entry: 既存のログエントリ
            guardian_result: GuardianResult
            check_time_ms: Guardian判定時間（ミリ秒）

        Returns:
            更新されたLLMBrainLog
        """
        log_entry.guardian_action = guardian_result.action.value
        log_entry.guardian_reason = guardian_result.reason
        log_entry.guardian_check_time_ms = check_time_ms

        if hasattr(guardian_result, 'risk_level') and guardian_result.risk_level:
            log_entry.guardian_risk_level = guardian_result.risk_level.value

        if hasattr(guardian_result, 'check_type') and guardian_result.check_type:
            log_entry.guardian_check_type = guardian_result.check_type

        # 総応答時間を更新
        if log_entry.llm_response_time_ms:
            log_entry.total_response_time_ms = (
                log_entry.llm_response_time_ms + check_time_ms
            )

        return log_entry

    def log_execution_result(
        self,
        log_entry: LLMBrainLog,
        success: bool,
        result_summary: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        execution_time_ms: Optional[int] = None,
    ) -> LLMBrainLog:
        """
        実行結果をログに追加

        Args:
            log_entry: 既存のログエントリ
            success: 成功したか
            result_summary: 結果概要
            error_code: エラーコード
            error_message: エラーメッセージ
            execution_time_ms: 実行時間（ミリ秒）

        Returns:
            更新されたLLMBrainLog
        """
        log_entry.execution_success = success
        log_entry.execution_result_summary = result_summary[:500] if result_summary else None
        log_entry.execution_error_code = error_code
        log_entry.execution_error_message = error_message[:500] if error_message else None

        # 総応答時間を更新
        if execution_time_ms and log_entry.total_response_time_ms:
            log_entry.total_response_time_ms += execution_time_ms

        return log_entry

    def log_confirmation_response(
        self,
        log_entry: LLMBrainLog,
        status: ConfirmationStatus,
    ) -> LLMBrainLog:
        """
        確認応答をログに追加

        Args:
            log_entry: 既存のログエントリ
            status: 確認ステータス

        Returns:
            更新されたLLMBrainLog
        """
        log_entry.confirmation_status = status.value
        return log_entry

    # =========================================================================
    # 永続化メソッド
    # =========================================================================

    async def save(self, log_entry: LLMBrainLog) -> Optional[str]:
        """
        ログをDBに保存

        Args:
            log_entry: ログエントリ

        Returns:
            保存されたログのID、またはNone
        """
        if not self.enable_persistence or not self.pool:
            logger.debug("Persistence disabled or no pool, skipping save")
            return None

        try:
            data = log_entry.to_dict()

            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(
                    """
                    INSERT INTO brain_observability_logs (
                        organization_id, user_id, room_id, session_id,
                        message_preview, message_hash,
                        detected_intent, output_type, reasoning,
                        tool_name, tool_parameters, tool_count,
                        confidence_overall, confidence_intent, confidence_parameters,
                        guardian_action, guardian_reason, guardian_risk_level, guardian_check_type,
                        auth_gate_action, auth_gate_reason,
                        execution_success, execution_error_code, execution_error_message, execution_result_summary,
                        model_used, api_provider, input_tokens, output_tokens,
                        llm_response_time_ms, guardian_check_time_ms, total_response_time_ms,
                        estimated_cost_yen,
                        needs_confirmation, confirmation_question, confirmation_status,
                        environment, version
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                        $21, $22, $23, $24, $25, $26, $27, $28, $29, $30,
                        $31, $32, $33, $34, $35, $36, $37, $38
                    )
                    RETURNING id
                    """,
                    data["organization_id"],
                    data["user_id"],
                    data["room_id"],
                    data["session_id"],
                    data["message_preview"],
                    data["message_hash"],
                    data["detected_intent"],
                    data["output_type"],
                    data["reasoning"],
                    data["tool_name"],
                    data["tool_parameters"],
                    data["tool_count"],
                    data["confidence_overall"],
                    data["confidence_intent"],
                    data["confidence_parameters"],
                    data["guardian_action"],
                    data["guardian_reason"],
                    data["guardian_risk_level"],
                    data["guardian_check_type"],
                    data["auth_gate_action"],
                    data["auth_gate_reason"],
                    data["execution_success"],
                    data["execution_error_code"],
                    data["execution_error_message"],
                    data["execution_result_summary"],
                    data["model_used"],
                    data["api_provider"],
                    data["input_tokens"],
                    data["output_tokens"],
                    data["llm_response_time_ms"],
                    data["guardian_check_time_ms"],
                    data["total_response_time_ms"],
                    data["estimated_cost_yen"],
                    data["needs_confirmation"],
                    data["confirmation_question"],
                    data["confirmation_status"],
                    data["environment"],
                    data["version"],
                )

                log_id = str(result["id"]) if result else None
                logger.debug(f"Saved LLM Brain log: {log_id}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to save LLM Brain log: {e}")
            return None

    async def save_batch(self, logs: List[LLMBrainLog]) -> int:
        """
        複数のログを一括保存

        Args:
            logs: ログエントリのリスト

        Returns:
            保存された件数
        """
        if not self.enable_persistence or not self.pool or not logs:
            return 0

        saved_count = 0
        for log in logs:
            if await self.save(log):
                saved_count += 1

        return saved_count

    def add_to_buffer(self, log_entry: LLMBrainLog) -> None:
        """
        バッファにログを追加（バッチ挿入用）

        Args:
            log_entry: ログエントリ
        """
        self._buffer.append(log_entry)

        if len(self._buffer) >= self._buffer_max_size:
            # バッファがいっぱいになったら非同期で保存をトリガー
            # 実際のアプリケーションでは asyncio.create_task() を使用
            logger.warning(
                f"Buffer full ({len(self._buffer)} logs), "
                "consider calling flush_buffer()"
            )

    async def flush_buffer(self) -> int:
        """
        バッファのログを一括保存

        Returns:
            保存された件数
        """
        if not self._buffer:
            return 0

        logs = self._buffer.copy()
        self._buffer.clear()

        return await self.save_batch(logs)


# =============================================================================
# ユーザーフィードバック
# =============================================================================

@dataclass
class UserFeedback:
    """ユーザーフィードバック"""
    organization_id: str
    log_id: Optional[str]
    user_id: str
    rating: Optional[int] = None  # 1-5
    is_helpful: Optional[bool] = None
    feedback_type: Optional[str] = None
    comment: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


async def save_user_feedback(
    pool,
    feedback: UserFeedback,
) -> Optional[str]:
    """
    ユーザーフィードバックを保存

    Args:
        pool: データベース接続プール
        feedback: フィードバック

    Returns:
        保存されたフィードバックのID
    """
    try:
        async with pool.acquire() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO brain_user_feedback (
                    organization_id, log_id, user_id,
                    rating, is_helpful, feedback_type, comment
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                feedback.organization_id,
                feedback.log_id,
                feedback.user_id,
                feedback.rating,
                feedback.is_helpful,
                feedback.feedback_type,
                feedback.comment,
            )
            return str(result["id"]) if result else None
    except Exception as e:
        logger.error(f"Failed to save user feedback: {e}")
        return None


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_llm_observability(
    pool=None,
    org_id: str = "",
    enable_cloud_logging: bool = True,
    enable_persistence: bool = True,
) -> LLMBrainObservability:
    """
    LLMBrainObservabilityインスタンスを作成

    Args:
        pool: データベース接続プール
        org_id: 組織ID
        enable_cloud_logging: Cloud Loggingへの出力を有効にするか
        enable_persistence: DBへの永続化を有効にするか

    Returns:
        LLMBrainObservability
    """
    return LLMBrainObservability(
        pool=pool,
        org_id=org_id,
        enable_cloud_logging=enable_cloud_logging,
        enable_persistence=enable_persistence,
    )


# =============================================================================
# グローバルインスタンス
# =============================================================================

_default_llm_observability: Optional[LLMBrainObservability] = None


def get_llm_observability(
    pool=None,
    org_id: str = "",
) -> LLMBrainObservability:
    """
    LLMBrainObservabilityのインスタンスを取得

    Args:
        pool: データベース接続プール
        org_id: 組織ID

    Returns:
        LLMBrainObservability
    """
    global _default_llm_observability

    if _default_llm_observability is None:
        _default_llm_observability = create_llm_observability(
            pool=pool,
            org_id=org_id,
        )

    return _default_llm_observability
