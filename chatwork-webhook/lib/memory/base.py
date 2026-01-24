"""
Phase 2 B: 記憶基盤 基底クラス

このモジュールは、記憶機能の基底クラスを定義します。
全ての記憶機能（B1〜B4）はこのクラスを継承します。

Author: Claude Code
Created: 2026-01-24
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from uuid import UUID
from datetime import datetime
import logging
import re
import json
import httpx

from lib.memory.constants import MemoryParameters
from lib.memory.exceptions import ValidationError, LLMError


# ================================================================
# ロガー設定
# ================================================================

logger = logging.getLogger(__name__)


# ================================================================
# データクラス
# ================================================================

@dataclass
class MemoryResult:
    """記憶操作の結果を表すデータクラス"""

    success: bool
    memory_id: Optional[UUID] = None
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        result = {
            "success": self.success,
            "message": self.message,
        }
        if self.memory_id:
            result["memory_id"] = str(self.memory_id)
        if self.data:
            result["data"] = self.data
        if self.error:
            result["error"] = self.error
        return result


# ================================================================
# 基底クラス
# ================================================================

class BaseMemory(ABC):
    """
    記憶機能の基底クラス

    全ての記憶機能（B1〜B4）はこのクラスを継承し、
    以下のメソッドを実装する:
    - save(): データを保存
    - retrieve(): データを取得
    """

    def __init__(
        self,
        conn,
        org_id: UUID,
        memory_type: str = "",
        openrouter_api_key: Optional[str] = None,
        model: str = "google/gemini-3-flash-preview"
    ):
        """
        初期化

        Args:
            conn: データベース接続
            org_id: 組織ID
            memory_type: 記憶タイプ（b1_summary, b2_preference, etc.）
            openrouter_api_key: OpenRouter APIキー
            model: 使用するLLMモデル
        """
        self.conn = conn
        self.org_id = org_id
        self.memory_type = memory_type
        self.openrouter_api_key = openrouter_api_key
        self.model = model

        # OpenRouter API URL
        self.openrouter_api_url = "https://openrouter.ai/api/v1/chat/completions"

    # ================================================================
    # 抽象メソッド（サブクラスで実装必須）
    # ================================================================

    @abstractmethod
    async def save(self, **kwargs) -> MemoryResult:
        """
        データを保存

        Returns:
            MemoryResult: 保存結果
        """
        pass

    @abstractmethod
    async def retrieve(self, **kwargs) -> List[Dict[str, Any]]:
        """
        データを取得

        Returns:
            List[Dict]: 取得したデータのリスト
        """
        pass

    # ================================================================
    # 共通ユーティリティメソッド
    # ================================================================

    def validate_uuid(self, value: Any, field_name: str = "id") -> UUID:
        """
        UUIDのバリデーション

        Args:
            value: バリデーション対象
            field_name: フィールド名（エラーメッセージ用）

        Returns:
            UUID: バリデーション済みのUUID

        Raises:
            ValidationError: 無効なUUIDの場合
        """
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                raise ValidationError(
                    message=f"Invalid UUID format for {field_name}: {value}",
                    field=field_name
                )
        raise ValidationError(
            message=f"Expected UUID for {field_name}, got {type(value).__name__}",
            field=field_name
        )

    def truncate_text(
        self,
        text: str,
        max_length: int,
        suffix: str = "..."
    ) -> str:
        """
        テキストを切り詰める

        Args:
            text: 対象テキスト
            max_length: 最大文字数
            suffix: 切り詰め時の接尾辞

        Returns:
            str: 切り詰められたテキスト
        """
        if len(text) <= max_length:
            return text
        return text[:max_length - len(suffix)] + suffix

    def extract_json_from_response(self, response_text: str) -> Dict[str, Any]:
        """
        LLMレスポンスからJSONを抽出

        Args:
            response_text: LLMのレスポンステキスト

        Returns:
            Dict: 抽出されたJSON

        Raises:
            ValueError: JSON抽出に失敗した場合
        """
        # コードブロック内のJSONを探す
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 直接JSONを探す
        json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # ネストしたJSONを探す
        try:
            # 最初の { から最後の } まで
            start = response_text.find('{')
            end = response_text.rfind('}')
            if start != -1 and end != -1 and end > start:
                return json.loads(response_text[start:end + 1])
        except json.JSONDecodeError:
            pass

        raise ValueError(f"Failed to extract JSON from response: {response_text[:200]}")

    async def call_llm(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1000
    ) -> str:
        """
        LLM APIを呼び出す

        Args:
            prompt: プロンプト
            temperature: 温度パラメータ
            max_tokens: 最大トークン数

        Returns:
            str: LLMのレスポンス

        Raises:
            LLMError: API呼び出しに失敗した場合
        """
        if not self.openrouter_api_key:
            raise LLMError(
                message="OpenRouter API key is not set",
                model=self.model
            )

        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://soulkun.soulsyncs.co.jp",
            "X-Title": "Soulkun Memory Framework"
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.openrouter_api_url,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

                if "choices" in result and len(result["choices"]) > 0:
                    return result["choices"][0]["message"]["content"]
                else:
                    raise LLMError(
                        message="No response from LLM",
                        model=self.model
                    )

        except httpx.HTTPError as e:
            raise LLMError(
                message=f"HTTP error calling LLM: {str(e)}",
                model=self.model
            )
        except Exception as e:
            raise LLMError(
                message=f"Error calling LLM: {str(e)}",
                model=self.model
            )

    def _log_operation(
        self,
        operation: str,
        user_id: Optional[UUID] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        操作をログに記録

        Args:
            operation: 操作名
            user_id: ユーザーID
            details: 詳細情報
        """
        log_data = {
            "memory_type": self.memory_type,
            "operation": operation,
            "org_id": str(self.org_id),
        }
        if user_id:
            log_data["user_id"] = str(user_id)
        if details:
            log_data.update(details)

        logger.info(f"Memory operation: {operation}", extra=log_data)

    def _sanitize_for_log(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ログ出力用にデータをサニタイズ

        機密情報を含む可能性のあるフィールドをマスク

        Args:
            data: サニタイズ対象のデータ

        Returns:
            Dict: サニタイズされたデータ
        """
        sensitive_fields = ["message_text", "summary_text", "answer", "question"]
        sanitized = {}

        for key, value in data.items():
            if key in sensitive_fields and isinstance(value, str):
                sanitized[key] = self.truncate_text(value, 50, "[...]")
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_for_log(value)
            else:
                sanitized[key] = value

        return sanitized
