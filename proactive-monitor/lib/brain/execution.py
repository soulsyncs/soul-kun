# lib/brain/execution.py
"""
ソウルくんの脳 - 実行層（Execution Layer）

判断層からの指令に基づいて各ハンドラーを呼び出し、結果を統合する層です。

設計思想:
- ハンドラーは「実行するだけ」で判断ロジックを持たない
- 結果は脳に戻り、脳が最終的なレスポンスを生成
- エラーハンドリングも脳の責務

設計書: docs/13_brain_architecture.md セクション8
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from lib.brain.models import (
    BrainContext,
    DecisionResult,
    HandlerResult,
)
from lib.brain.exceptions import (
    BrainError,
    ExecutionError,
    HandlerTimeoutError,
    HandlerNotFoundError,
    ParameterValidationError,
)
from lib.brain.constants import (
    EXECUTION_TIMEOUT_SECONDS,
    MAX_RETRY_COUNT,
    ERROR_MESSAGE,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 実行層の定数
# =============================================================================

# 個別ハンドラーのタイムアウト（秒）
HANDLER_TIMEOUT_SECONDS: int = 30

# リトライ可能なエラータイプ
RETRYABLE_ERRORS: set = {
    "ConnectionError",
    "TimeoutError",
    "HTTPError",
    "APIError",
}

# リトライ間隔（秒）
RETRY_DELAY_SECONDS: float = 1.0

# リトライ時の指数バックオフ係数
RETRY_BACKOFF_FACTOR: float = 2.0


# =============================================================================
# エラーメッセージテンプレート
# =============================================================================

ERROR_MESSAGES: Dict[str, str] = {
    "parameter_missing": "「{param}」を教えてほしいウル🐺",
    "parameter_invalid": "「{param}」の形式が違うみたいウル🐺 もう一回教えてほしいウル",
    "handler_not_found": "その機能はまだ使えないウル🐺 ごめんウル",
    "handler_timeout": "ちょっと時間がかかっているウル🐺 もう少し待ってほしいウル",
    "handler_error": "エラーが起きたウル🐺 もう一回試してみてほしいウル",
    "permission_denied": "この操作は権限がないウル🐺 管理者に確認してほしいウル",
    "retry_in_progress": "リトライ中ウル...もう少し待ってほしいウル🐺",
    "max_retries_exceeded": "何回やってもうまくいかないウル🐺 時間を置いて試してほしいウル",
    "unexpected_error": ERROR_MESSAGE,
}


# =============================================================================
# 先読み提案テンプレート
# =============================================================================

SUGGESTION_TEMPLATES: Dict[str, List[str]] = {
    "chatwork_task_create": [
        "このタスクにリマインドを設定しようか？",
        "他にも追加するタスクはある？",
    ],
    "chatwork_task_search": [
        "タスクの詳細を見る？",
        "完了にするタスクはある？",
    ],
    "chatwork_task_complete": [
        "他にも完了にするタスクはある？",
        "次のタスクを確認する？",
    ],
    "goal_registration": [  # v10.29.6: SYSTEM_CAPABILITIESと名前を統一
        "目標について質問がある？",
    ],
    "learn_knowledge": [
        "他にも覚えておいてほしいことはある？",
    ],
    "query_knowledge": [
        "もっと詳しく知りたい？",
        "関連する情報も見る？",
    ],
    "announcement_create": [
        "リマインドを設定する？",
        "他のルームにもアナウンスする？",
    ],
}


# =============================================================================
# パラメータ必須定義
# =============================================================================

REQUIRED_PARAMETERS: Dict[str, List[str]] = {
    "chatwork_task_create": ["body"],
    "chatwork_task_complete": ["task_id"],
    "chatwork_task_search": [],  # オプションのみ
    "learn_knowledge": ["content"],
    "forget_knowledge": ["keyword"],
    "announcement_create": ["message", "target_room"],
    "send_reminder": ["task_id"],
}

# パラメータ型定義
PARAMETER_TYPES: Dict[str, Dict[str, type]] = {
    "chatwork_task_create": {
        "body": str,
        "assignee_ids": list,
        "limit_time": (int, str),
    },
    "chatwork_task_complete": {
        "task_id": (int, str),
    },
    "announcement_create": {
        "message": str,
        "target_room": str,
        "schedule_time": str,
    },
}


# =============================================================================
# ExecutionResult データクラス
# =============================================================================

@dataclass
class ExecutionResult:
    """
    実行層の結果（HandlerResultを拡張）
    """

    # 基本結果
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None

    # エラー情報
    error_code: Optional[str] = None
    error_details: Optional[str] = None

    # 実行メタデータ
    action: str = ""
    handler_name: str = ""
    execution_time_ms: int = 0
    retry_count: int = 0

    # 次のアクション
    next_action: Optional[str] = None
    next_params: Optional[Dict[str, Any]] = None

    # 状態更新
    update_state: Optional[Dict[str, Any]] = None

    # 先読み提案
    suggestions: List[str] = field(default_factory=list)

    # 監査ログ用
    audit_action: Optional[str] = None
    audit_resource_type: Optional[str] = None
    audit_resource_id: Optional[str] = None

    def to_handler_result(self) -> HandlerResult:
        """HandlerResultに変換"""
        return HandlerResult(
            success=self.success,
            message=self.message,
            data=self.data,
            error_code=self.error_code,
            error_details=self.error_details,
            next_action=self.next_action,
            next_params=self.next_params,
            update_state=self.update_state,
            suggestions=self.suggestions,
        )


# =============================================================================
# BrainExecution クラス
# =============================================================================

class BrainExecution:
    """
    ソウルくんの脳 - 実行層

    判断層からの指令に基づいて各ハンドラーを呼び出し、結果を統合します。

    5ステップ実行フロー:
    1. ハンドラー取得（HANDLERSマッピングから）
    2. パラメータ検証（必須チェック、型検証）
    3. ハンドラー実行（try-except、タイムアウト）
    4. 結果の統合（成功/失敗、監査ログ）
    5. 状態更新（会話履歴、記憶、状態遷移）

    Attributes:
        handlers: アクション名 → ハンドラー関数のマッピング
        get_ai_response_func: 汎用AI応答生成関数
        org_id: 組織ID（監査ログ用）
        enable_suggestions: 先読み提案を有効にするか
        enable_retry: リトライを有効にするか
    """

    def __init__(
        self,
        handlers: Optional[Dict[str, Callable]] = None,
        get_ai_response_func: Optional[Callable] = None,
        org_id: str = "",
        enable_suggestions: bool = True,
        enable_retry: bool = True,
    ):
        """
        実行層を初期化

        Args:
            handlers: アクション名 → ハンドラー関数のマッピング
            get_ai_response_func: 汎用AI応答生成関数
            org_id: 組織ID（監査ログ用）
            enable_suggestions: 先読み提案を有効にするか
            enable_retry: リトライを有効にするか
        """
        self.handlers = handlers or {}
        self.get_ai_response = get_ai_response_func
        self.org_id = org_id
        self.enable_suggestions = enable_suggestions
        self.enable_retry = enable_retry

        logger.debug(
            f"BrainExecution initialized: "
            f"handlers={len(self.handlers)}, "
            f"enable_suggestions={enable_suggestions}, "
            f"enable_retry={enable_retry}"
        )

    # =========================================================================
    # メインの実行メソッド
    # =========================================================================

    async def execute(
        self,
        decision: DecisionResult,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> ExecutionResult:
        """
        判断結果を実行

        5ステップ実行フロー:
        1. ハンドラー取得
        2. パラメータ検証
        3. ハンドラー実行
        4. 結果の統合
        5. 状態更新・提案生成

        Args:
            decision: 判断層からの結果
            context: 現在のコンテキスト
            room_id: ChatWorkルームID
            account_id: ユーザーのアカウントID
            sender_name: 送信者名

        Returns:
            ExecutionResult: 実行結果
        """
        start_time = time.time()
        action = decision.action
        params = decision.params

        logger.info(
            f"Executing action: {action}, "
            f"params_count={len(params)}, "
            f"room_id={room_id}"
        )

        try:
            # Step 1: ハンドラー取得
            handler = self._get_handler(action)

            if handler is None:
                # ハンドラーがない場合は汎用応答
                return await self._handle_no_handler(
                    action, context, start_time
                )

            # Step 2: パラメータ検証
            validation_error = self._validate_parameters(action, params)
            if validation_error:
                return self._create_parameter_error_result(
                    action, validation_error, start_time
                )

            # Step 3: ハンドラー実行（リトライあり）
            result = await self._execute_with_retry(
                handler=handler,
                action=action,
                params=params,
                room_id=room_id,
                account_id=account_id,
                sender_name=sender_name,
                context=context,
            )

            # Step 4: 結果の統合
            execution_result = self._integrate_result(
                result=result,
                action=action,
                start_time=start_time,
            )

            # Step 5: 先読み提案生成
            if self.enable_suggestions and execution_result.success:
                execution_result.suggestions = self._generate_suggestions(
                    action, execution_result, context
                )

            return execution_result

        except HandlerTimeoutError as e:
            logger.error(f"Handler timeout: {action}, {e}")
            return ExecutionResult(
                success=False,
                message=ERROR_MESSAGES["handler_timeout"],
                action=action,
                error_code="TIMEOUT",
                error_details=str(e),
                execution_time_ms=self._elapsed_ms(start_time),
            )

        except ParameterValidationError as e:
            logger.warning(f"Parameter validation failed: {action}, {e}")
            return ExecutionResult(
                success=False,
                message=str(e),
                action=action,
                error_code="PARAMETER_ERROR",
                error_details=str(e),
                execution_time_ms=self._elapsed_ms(start_time),
            )

        except Exception as e:
            logger.error(f"Unexpected execution error: {action}, {e}")
            return ExecutionResult(
                success=False,
                message=ERROR_MESSAGES["unexpected_error"],
                action=action,
                error_code="UNEXPECTED_ERROR",
                error_details=str(e),
                execution_time_ms=self._elapsed_ms(start_time),
            )

    # =========================================================================
    # Step 1: ハンドラー取得
    # =========================================================================

    def _get_handler(self, action: str) -> Optional[Callable]:
        """
        アクションに対応するハンドラーを取得

        Args:
            action: アクション名

        Returns:
            ハンドラー関数、または None
        """
        handler = self.handlers.get(action)

        if handler is None:
            logger.debug(f"No handler found for action: {action}")
            # 類似アクションを探す（タイポ対応）
            similar = self._find_similar_handler(action)
            if similar:
                logger.info(f"Found similar handler: {similar} for {action}")

        return handler

    def _find_similar_handler(self, action: str) -> Optional[str]:
        """
        類似のハンドラーを探す（タイポ対応）

        Args:
            action: アクション名

        Returns:
            類似のアクション名、または None
        """
        # 簡単な類似度計算（共通部分文字列）
        for known_action in self.handlers.keys():
            # 完全一致（大文字小文字無視）
            if action.lower() == known_action.lower():
                return known_action

            # 部分一致
            if action.lower() in known_action.lower():
                return known_action
            if known_action.lower() in action.lower():
                return known_action

        return None

    async def _handle_no_handler(
        self,
        action: str,
        context: BrainContext,
        start_time: float,
    ) -> ExecutionResult:
        """
        ハンドラーがない場合の処理

        汎用AI応答を生成するか、デフォルトメッセージを返す

        Args:
            action: アクション名
            context: コンテキスト
            start_time: 開始時刻

        Returns:
            ExecutionResult
        """
        logger.warning(f"No handler for action: {action}")

        # 汎用AI応答を生成
        if self.get_ai_response:
            try:
                recent_conv = (
                    context.recent_conversation[-5:]
                    if context.recent_conversation
                    else []
                )
                response = self.get_ai_response(
                    recent_conv,
                    context.to_prompt_context(),
                )
                return ExecutionResult(
                    success=True,
                    message=response,
                    action=action,
                    handler_name="ai_response",
                    execution_time_ms=self._elapsed_ms(start_time),
                )
            except Exception as e:
                logger.error(f"Error generating AI response: {e}")

        # デフォルトメッセージ
        return ExecutionResult(
            success=True,
            message="了解ウル！🐺",
            action=action,
            handler_name="default",
            execution_time_ms=self._elapsed_ms(start_time),
        )

    # =========================================================================
    # Step 2: パラメータ検証
    # =========================================================================

    def _validate_parameters(
        self,
        action: str,
        params: Dict[str, Any],
    ) -> Optional[str]:
        """
        パラメータを検証

        Args:
            action: アクション名
            params: パラメータ

        Returns:
            エラーメッセージ、または None（検証OK）
        """
        # 必須パラメータのチェック
        required = REQUIRED_PARAMETERS.get(action, [])
        for param_name in required:
            if param_name not in params or params[param_name] is None:
                return ERROR_MESSAGES["parameter_missing"].format(
                    param=self._get_param_display_name(param_name)
                )

            # 空文字列チェック
            if isinstance(params[param_name], str) and not params[param_name].strip():
                return ERROR_MESSAGES["parameter_missing"].format(
                    param=self._get_param_display_name(param_name)
                )

        # 型のチェック
        type_defs = PARAMETER_TYPES.get(action, {})
        for param_name, expected_type in type_defs.items():
            if param_name in params and params[param_name] is not None:
                value = params[param_name]

                # タプルの場合は複数型を許容
                if isinstance(expected_type, tuple):
                    if not isinstance(value, expected_type):
                        return ERROR_MESSAGES["parameter_invalid"].format(
                            param=self._get_param_display_name(param_name)
                        )
                else:
                    if not isinstance(value, expected_type):
                        return ERROR_MESSAGES["parameter_invalid"].format(
                            param=self._get_param_display_name(param_name)
                        )

        return None

    def _get_param_display_name(self, param_name: str) -> str:
        """
        パラメータの表示名を取得

        Args:
            param_name: パラメータ名（英語）

        Returns:
            表示名（日本語）
        """
        display_names = {
            "body": "タスクの内容",
            "task_id": "タスクID",
            "content": "覚えてほしい内容",
            "keyword": "キーワード",
            "message": "メッセージ",
            "target_room": "送信先",
            "assignee_ids": "担当者",
            "limit_time": "期限",
            "schedule_time": "送信時刻",
        }
        return display_names.get(param_name, param_name)

    def _create_parameter_error_result(
        self,
        action: str,
        error_message: str,
        start_time: float,
    ) -> ExecutionResult:
        """
        パラメータエラーの結果を作成

        Args:
            action: アクション名
            error_message: エラーメッセージ
            start_time: 開始時刻

        Returns:
            ExecutionResult
        """
        return ExecutionResult(
            success=False,
            message=error_message,
            action=action,
            error_code="PARAMETER_ERROR",
            error_details=error_message,
            execution_time_ms=self._elapsed_ms(start_time),
            # 確認モードに遷移
            update_state={
                "state_type": "confirmation",
                "reason": "parameter_missing",
            },
        )

    # =========================================================================
    # Step 3: ハンドラー実行
    # =========================================================================

    async def _execute_with_retry(
        self,
        handler: Callable,
        action: str,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: BrainContext,
    ) -> HandlerResult:
        """
        リトライ付きでハンドラーを実行

        Args:
            handler: ハンドラー関数
            action: アクション名
            params: パラメータ
            room_id: ルームID
            account_id: アカウントID
            sender_name: 送信者名
            context: コンテキスト

        Returns:
            HandlerResult

        Raises:
            HandlerTimeoutError: タイムアウト時
        """
        last_error: Optional[Exception] = None
        retry_count = 0

        max_retries = MAX_RETRY_COUNT if self.enable_retry else 1

        for attempt in range(max_retries):
            try:
                # タイムアウト付きで実行
                result = await asyncio.wait_for(
                    self._call_handler(
                        handler=handler,
                        params=params,
                        room_id=room_id,
                        account_id=account_id,
                        sender_name=sender_name,
                        context=context,
                    ),
                    timeout=HANDLER_TIMEOUT_SECONDS,
                )

                # 成功
                if result.success:
                    return result

                # ハンドラー自体のエラー（リトライしない）
                if result.error_code and result.error_code not in RETRYABLE_ERRORS:
                    return result

                # リトライ可能なエラー
                last_error = Exception(result.error_details or "Unknown error")
                retry_count = attempt + 1

            except asyncio.TimeoutError:
                logger.warning(
                    f"Handler timeout (attempt {attempt + 1}/{max_retries}): {action}"
                )
                last_error = asyncio.TimeoutError(
                    f"Handler {action} timed out after {HANDLER_TIMEOUT_SECONDS}s"
                )
                retry_count = attempt + 1

            except Exception as e:
                error_type = type(e).__name__
                logger.warning(
                    f"Handler error (attempt {attempt + 1}/{max_retries}): "
                    f"{action}, {error_type}: {e}"
                )

                # リトライ可能かチェック
                if error_type not in RETRYABLE_ERRORS and not self.enable_retry:
                    raise

                last_error = e
                retry_count = attempt + 1

            # リトライ待機（指数バックオフ）
            if attempt < max_retries - 1:
                delay = RETRY_DELAY_SECONDS * (RETRY_BACKOFF_FACTOR ** attempt)
                logger.info(f"Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

        # 最大リトライ回数を超えた
        if isinstance(last_error, asyncio.TimeoutError):
            raise HandlerTimeoutError(
                message=str(last_error),
                action=action,
                timeout_seconds=HANDLER_TIMEOUT_SECONDS,
            )

        # その他のエラー
        return HandlerResult(
            success=False,
            message=ERROR_MESSAGES["max_retries_exceeded"],
            error_code="MAX_RETRIES_EXCEEDED",
            error_details=str(last_error) if last_error else "Unknown error",
        )

    async def _call_handler(
        self,
        handler: Callable,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: BrainContext,
    ) -> HandlerResult:
        """
        ハンドラーを呼び出す

        同期/非同期の両方に対応

        Args:
            handler: ハンドラー関数
            params: パラメータ
            room_id: ルームID
            account_id: アカウントID
            sender_name: 送信者名
            context: コンテキスト

        Returns:
            HandlerResult
        """
        # ハンドラーが非同期関数かどうかを判定
        if asyncio.iscoroutinefunction(handler):
            result = await handler(
                params=params,
                room_id=room_id,
                account_id=account_id,
                sender_name=sender_name,
                context=context,
            )
        else:
            # 同期関数の場合はスレッドプールで実行
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: handler(
                    params=params,
                    room_id=room_id,
                    account_id=account_id,
                    sender_name=sender_name,
                    context=context,
                ),
            )

        # 結果をHandlerResultに変換
        return self._normalize_result(result)

    def _normalize_result(self, result: Any) -> HandlerResult:
        """
        ハンドラーの結果をHandlerResultに正規化

        Args:
            result: ハンドラーの戻り値

        Returns:
            HandlerResult
        """
        if isinstance(result, HandlerResult):
            return result

        if isinstance(result, str):
            return HandlerResult(success=True, message=result)

        if isinstance(result, dict):
            return HandlerResult(
                success=result.get("success", True),
                message=result.get("message", "完了ウル🐺"),
                data=result,
                error_code=result.get("error_code"),
                error_details=result.get("error_details"),
                next_action=result.get("next_action"),
                next_params=result.get("next_params"),
                update_state=result.get("update_state"),
                suggestions=result.get("suggestions", []),
            )

        if result is None:
            return HandlerResult(success=True, message="完了ウル🐺")

        # その他
        return HandlerResult(success=True, message=str(result))

    # =========================================================================
    # Step 4: 結果の統合
    # =========================================================================

    def _integrate_result(
        self,
        result: HandlerResult,
        action: str,
        start_time: float,
    ) -> ExecutionResult:
        """
        ハンドラーの結果を統合

        Args:
            result: ハンドラーの結果
            action: アクション名
            start_time: 開始時刻

        Returns:
            ExecutionResult
        """
        execution_result = ExecutionResult(
            success=result.success,
            message=result.message,
            data=result.data,
            error_code=result.error_code,
            error_details=result.error_details,
            action=action,
            handler_name=action,
            execution_time_ms=self._elapsed_ms(start_time),
            next_action=result.next_action,
            next_params=result.next_params,
            update_state=result.update_state,
            suggestions=result.suggestions or [],
        )

        # 監査ログ用の情報を設定
        if result.data:
            execution_result.audit_action = action
            execution_result.audit_resource_type = self._get_resource_type(action)
            execution_result.audit_resource_id = result.data.get("id") or result.data.get("task_id")

        return execution_result

    def _get_resource_type(self, action: str) -> str:
        """
        アクションからリソースタイプを取得

        Args:
            action: アクション名

        Returns:
            リソースタイプ
        """
        resource_map = {
            "chatwork_task_create": "task",
            "chatwork_task_complete": "task",
            "chatwork_task_search": "task",
            "learn_knowledge": "knowledge",
            "forget_knowledge": "knowledge",
            "query_knowledge": "knowledge",
            "save_memory": "memory",
            "goal_registration": "goal",  # v10.29.6: SYSTEM_CAPABILITIESと名前を統一
            "goal_progress_report": "goal",
            "announcement_create": "announcement",
        }
        return resource_map.get(action, "unknown")

    # =========================================================================
    # Step 5: 先読み提案生成
    # =========================================================================

    def _generate_suggestions(
        self,
        action: str,
        result: ExecutionResult,
        context: BrainContext,
    ) -> List[str]:
        """
        実行結果に基づいて先読み提案を生成

        Args:
            action: 実行したアクション
            result: 実行結果
            context: コンテキスト

        Returns:
            提案のリスト（最大3件）
        """
        suggestions: List[str] = []

        # アクション固有の提案
        templates = SUGGESTION_TEMPLATES.get(action, [])
        suggestions.extend(templates)

        # コンテキストに基づく動的提案
        suggestions.extend(
            self._generate_context_suggestions(action, result, context)
        )

        # 重複を除去して最大3件
        unique_suggestions = list(dict.fromkeys(suggestions))
        return unique_suggestions[:3]

    def _generate_context_suggestions(
        self,
        action: str,
        result: ExecutionResult,
        context: BrainContext,
    ) -> List[str]:
        """
        コンテキストに基づいて動的に提案を生成

        Args:
            action: アクション
            result: 結果
            context: コンテキスト

        Returns:
            提案リスト
        """
        suggestions = []

        # タスク検索後、期限超過タスクがある場合
        if action == "chatwork_task_search" and result.data:
            overdue_count = result.data.get("overdue_count", 0)
            if overdue_count > 0:
                suggestions.append("期限超過のタスクがあるけど、対応する？")

        # タスク作成後、類似タスクがある場合
        if action == "chatwork_task_create" and context.recent_tasks:
            if len(context.recent_tasks) > 3:
                suggestions.append("最近タスクが増えてるけど、優先順位を確認する？")

        # 目標関連
        if action.startswith("goal_") and context.active_goals:
            if len(context.active_goals) > 1:
                suggestions.append("他の目標の進捗も確認する？")

        return suggestions

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def _elapsed_ms(self, start_time: float) -> int:
        """経過時間をミリ秒で返す"""
        return int((time.time() - start_time) * 1000)

    def add_handler(self, action: str, handler: Callable) -> None:
        """
        ハンドラーを追加

        Args:
            action: アクション名
            handler: ハンドラー関数
        """
        self.handlers[action] = handler
        logger.debug(f"Handler added: {action}")

    def remove_handler(self, action: str) -> bool:
        """
        ハンドラーを削除

        Args:
            action: アクション名

        Returns:
            削除できたか
        """
        if action in self.handlers:
            del self.handlers[action]
            logger.debug(f"Handler removed: {action}")
            return True
        return False

    def get_available_actions(self) -> List[str]:
        """
        利用可能なアクションのリストを取得

        Returns:
            アクション名のリスト
        """
        return list(self.handlers.keys())


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_execution(
    handlers: Optional[Dict[str, Callable]] = None,
    get_ai_response_func: Optional[Callable] = None,
    org_id: str = "",
    enable_suggestions: bool = True,
    enable_retry: bool = True,
) -> BrainExecution:
    """
    BrainExecutionインスタンスを作成

    Args:
        handlers: ハンドラーマッピング
        get_ai_response_func: AI応答生成関数
        org_id: 組織ID
        enable_suggestions: 先読み提案を有効にするか
        enable_retry: リトライを有効にするか

    Returns:
        BrainExecution
    """
    return BrainExecution(
        handlers=handlers,
        get_ai_response_func=get_ai_response_func,
        org_id=org_id,
        enable_suggestions=enable_suggestions,
        enable_retry=enable_retry,
    )
