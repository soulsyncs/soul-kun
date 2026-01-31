# lib/brain/observability.py
"""
ソウルくんの脳 - 観測機能（Observability Layer）

v10.46.0: 脳の判断過程を統一的にログ出力し、Cloud Logging + 将来的な永続化に対応。

設計原則:
- 全ての観測ログは脳を通して出力される（機能が個別にログを出さない）
- 将来的には brain_decision_logs テーブルへの記録も可能な構造
- コンテキストの種類が増えても同じインターフェースで対応可能

設計書: docs/25_llm_native_brain_architecture.md（LLM常駐型脳アーキテクチャ）
鉄則3: 脳が判断し、機能は実行するだけ
鉄則4: 機能拡張しても脳の構造は変わらない

【対応するコンテキスト】
- persona: Company Persona + Add-on
- mvv: 組織論的行動指針
- ceo_teaching: CEOの教え（Phase 2D）
- ng_pattern: NGパターン検出
- basic_need: 基本欲求分析
- intent: 意図判定
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# 観測対象のコンテキストタイプ
# =============================================================================

class ContextType(str, Enum):
    """
    脳が適用するコンテキストの種類

    新しいコンテキストタイプを追加する場合は、ここに追加するだけで
    既存のログインターフェースがそのまま使える。
    """
    # 人格・応答スタイル
    PERSONA = "persona"              # Company Persona + Add-on
    MVV = "mvv"                      # 組織論的行動指針

    # 判断・ガイダンス
    CEO_TEACHING = "ceo_teaching"    # CEOの教え（Phase 2D）
    NG_PATTERN = "ng_pattern"        # NGパターン検出
    BASIC_NEED = "basic_need"        # 基本欲求分析

    # 意図・ルーティング
    INTENT = "intent"                # 意図判定
    ROUTE = "route"                  # ルーティング決定


# =============================================================================
# 観測ログのデータ構造
# =============================================================================

@dataclass
class ObservabilityLog:
    """
    観測ログのデータ構造

    Cloud Loggingへの出力と、将来的なbrain_decision_logsへの永続化に対応。
    """
    # 必須フィールド
    context_type: ContextType        # コンテキストの種類
    path: str                        # コードパス（例: "get_ai_response", "goal_registration"）
    applied: bool                    # 適用されたか
    account_id: str                  # ユーザーアカウントID

    # オプションフィールド
    org_id: Optional[str] = None     # 組織ID
    details: Optional[Dict[str, Any]] = None  # 追加情報
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # メタデータ（将来拡張用）
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_log_string(self) -> str:
        """Cloud Logging用の文字列を生成"""
        emoji = self._get_emoji()
        applied_str = "yes" if self.applied else "no"
        details_str = f" ({self.details})" if self.details else ""

        return f"{emoji} ctx={self.context_type.value} path={self.path} applied={applied_str} account={self.account_id}{details_str}"

    def _get_emoji(self) -> str:
        """コンテキストタイプに応じた絵文字を返す"""
        emoji_map = {
            ContextType.PERSONA: "🎭",
            ContextType.MVV: "🏢",
            ContextType.CEO_TEACHING: "👑",
            ContextType.NG_PATTERN: "🚫",
            ContextType.BASIC_NEED: "💡",
            ContextType.INTENT: "🧠",
            ContextType.ROUTE: "🔀",
        }
        return emoji_map.get(self.context_type, "📊")

    def to_dict(self) -> Dict[str, Any]:
        """永続化用の辞書を生成"""
        return {
            "context_type": self.context_type.value,
            "path": self.path,
            "applied": self.applied,
            "account_id": self.account_id,
            "org_id": self.org_id,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


# =============================================================================
# BrainObservability クラス
# =============================================================================

class BrainObservability:
    """
    脳の観測機能

    全ての観測ログはこのクラスを通して出力される。
    機能が個別にprint()やlogger.info()を呼ぶのではなく、
    脳が統一的に観測を管理する。

    Usage:
        observability = BrainObservability(org_id="org_soulsyncs")

        # コンテキスト適用のログ
        observability.log_context(
            context_type=ContextType.PERSONA,
            path="get_ai_response",
            applied=True,
            account_id="12345",
            details={"addon": True},
        )

        # 意図判定のログ
        observability.log_intent(
            intent="goal_registration",
            route="goal_handler",
            confidence=0.85,
            account_id="12345",
        )
    """

    def __init__(
        self,
        org_id: str = "",
        enable_cloud_logging: bool = True,
        enable_persistence: bool = False,  # 将来的にTrue
    ):
        """
        観測機能を初期化

        Args:
            org_id: 組織ID
            enable_cloud_logging: Cloud Loggingへの出力を有効にするか
            enable_persistence: DBへの永続化を有効にするか（将来対応）
        """
        self.org_id = org_id
        self.enable_cloud_logging = enable_cloud_logging
        self.enable_persistence = enable_persistence

        # ログバッファ（バッチ永続化用）
        self._log_buffer: List[ObservabilityLog] = []

        logger.debug(
            f"BrainObservability initialized: "
            f"org_id={org_id}, "
            f"cloud_logging={enable_cloud_logging}, "
            f"persistence={enable_persistence}"
        )

    # =========================================================================
    # コンテキスト適用ログ
    # =========================================================================

    def log_context(
        self,
        context_type: ContextType,
        path: str,
        applied: bool,
        account_id: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        コンテキスト適用のログを出力

        Args:
            context_type: コンテキストの種類（PERSONA, MVV, CEO_TEACHING等）
            path: コードパス（例: "get_ai_response", "goal_registration"）
            applied: 適用されたか
            account_id: ユーザーアカウントID
            details: 追加情報（任意）
        """
        log_entry = ObservabilityLog(
            context_type=context_type,
            path=path,
            applied=applied,
            account_id=account_id,
            org_id=self.org_id,
            details=details,
        )

        self._output_log(log_entry)

    # =========================================================================
    # 特化メソッド（便利メソッド）
    # =========================================================================

    def log_persona(
        self,
        path: str,
        injected: bool,
        addon: bool,
        account_id: str,
    ) -> None:
        """
        Persona適用のログを出力（便利メソッド）

        Args:
            path: コードパス
            injected: Personaが注入されたか
            addon: Add-onが適用されたか
            account_id: アカウントID
        """
        self.log_context(
            context_type=ContextType.PERSONA,
            path=path,
            applied=injected,
            account_id=account_id,
            details={"addon": addon} if injected else None,
        )

    def log_intent(
        self,
        intent: str,
        route: str,
        confidence: float,
        account_id: str,
        raw_message: Optional[str] = None,
    ) -> None:
        """
        意図判定のログを出力

        Args:
            intent: 判定された意図
            route: ルーティング先
            confidence: 確信度
            account_id: アカウントID
            raw_message: 元のメッセージ（先頭40文字まで）
        """
        text_preview = (raw_message[:40].replace('\n', ' ')) if raw_message else ""

        self.log_context(
            context_type=ContextType.INTENT,
            path=route,
            applied=True,
            account_id=account_id,
            details={
                "intent": intent,
                "confidence": round(confidence, 2),
                "text": text_preview,
            },
        )

    def log_execution(
        self,
        action: str,
        success: bool,
        account_id: str,
        execution_time_ms: int,
        error_code: Optional[str] = None,
    ) -> None:
        """
        実行結果のログを出力

        Args:
            action: 実行したアクション
            success: 成功したか
            account_id: アカウントID
            execution_time_ms: 実行時間（ミリ秒）
            error_code: エラーコード（失敗時）
        """
        details = {
            "success": success,
            "time_ms": execution_time_ms,
        }
        if error_code:
            details["error"] = error_code

        self.log_context(
            context_type=ContextType.ROUTE,
            path=action,
            applied=success,
            account_id=account_id,
            details=details,
        )

    # =========================================================================
    # 内部メソッド
    # =========================================================================

    def _output_log(self, log_entry: ObservabilityLog) -> None:
        """
        ログを出力

        Args:
            log_entry: ログエントリ
        """
        # Cloud Loggingへの出力（logger.infoを使用して構造化ログ対応）
        if self.enable_cloud_logging:
            logger.info(log_entry.to_log_string())

        # バッファに追加（永続化用）
        if self.enable_persistence:
            # メモリリーク防止: 最大1000件でバッファ制限
            MAX_BUFFER_SIZE = 1000
            if len(self._log_buffer) >= MAX_BUFFER_SIZE:
                self._log_buffer.pop(0)  # 最古のログを削除

            self._log_buffer.append(log_entry)

            # バッファが一定サイズに達したらフラッシュ
            if len(self._log_buffer) >= 100:
                self._flush_logs()

    def _flush_logs(self) -> None:
        """
        バッファのログをDBに永続化

        TODO(Phase 4): brain_decision_logs テーブルへの記録
        """
        if not self._log_buffer:
            return

        # TODO: DBへの永続化処理
        # await db.execute(
        #     "INSERT INTO brain_decision_logs ...",
        #     [log.to_dict() for log in self._log_buffer]
        # )

        logger.debug(f"Flushing {len(self._log_buffer)} logs to DB (not implemented)")
        self._log_buffer.clear()


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_observability(
    org_id: str = "",
    enable_cloud_logging: bool = True,
    enable_persistence: bool = False,
) -> BrainObservability:
    """
    BrainObservabilityインスタンスを作成

    Args:
        org_id: 組織ID
        enable_cloud_logging: Cloud Loggingへの出力を有効にするか
        enable_persistence: DBへの永続化を有効にするか

    Returns:
        BrainObservability
    """
    return BrainObservability(
        org_id=org_id,
        enable_cloud_logging=enable_cloud_logging,
        enable_persistence=enable_persistence,
    )


# =============================================================================
# グローバルインスタンス（シングルトン）
# =============================================================================

# デフォルトの観測機能インスタンス
# 複数の組織をまたいで使用する場合は、組織ごとにインスタンスを作成
_default_observability: Optional[BrainObservability] = None


def get_observability(org_id: str = "") -> BrainObservability:
    """
    観測機能のインスタンスを取得

    Args:
        org_id: 組織ID

    Returns:
        BrainObservability
    """
    global _default_observability

    if _default_observability is None:
        _default_observability = create_observability(org_id=org_id)

    return _default_observability


def log_persona_path(
    path: str,
    injected: bool,
    addon: bool,
    account_id: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """
    Persona観測ログを出力（後方互換性のための関数）

    この関数は lib/persona/__init__.py からの移行用。
    新規コードでは BrainObservability.log_persona() を直接使用してください。

    Args:
        path: コードパス名
        injected: Personaプロンプトが注入されたかどうか
        addon: Add-onが適用されたかどうか
        account_id: ユーザーのChatWork account_id
        extra: 追加情報（任意）
    """
    observability = get_observability()

    details = {"addon": addon}
    if extra:
        details["extra"] = extra

    observability.log_context(
        context_type=ContextType.PERSONA,
        path=path,
        applied=injected,
        account_id=account_id or "unknown",
        details=details,
    )
