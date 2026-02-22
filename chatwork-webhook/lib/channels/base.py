# lib/channels/base.py
"""
チャネルアダプター基底クラス

プラットフォーム固有のメッセージング機能を統一インターフェースに抽象化する。
将来Slack/LINE等を追加する際、このインターフェースを実装するだけで対応できる。

【設計原則】
- CLAUDE.md 2-1: 全入力は脳を通る → アダプターは入力の正規化のみ担当
- CLAUDE.md 2-1b: 能動的出力も脳が生成 → アダプターは送信のみ担当
- 脳バイパス禁止: アダプターはメッセージの判断をしない

Author: Claude Code
Created: 2026-02-07
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


# =============================================================================
# データクラス
# =============================================================================


@dataclass
class ChannelMessage:
    """
    プラットフォーム非依存のメッセージ構造体

    各チャネルアダプターのparse_webhook()がこの型に変換する。
    main.pyはこの型のみを扱い、プラットフォーム固有の詳細を知らない。
    """
    platform: str               # "chatwork", "slack", "line"
    room_id: str                # チャットルームID
    sender_id: str              # 送信者のアカウントID
    sender_name: str            # 送信者の表示名（取得できない場合は"ゲスト"）
    body: str                   # クリーニング済みメッセージ本文
    raw_body: str               # 元のメッセージ本文（タグ付き）
    message_id: str = ""        # メッセージID
    is_bot_addressed: bool = False  # ボット宛かどうか
    is_broadcast: bool = False  # 全体宛（toall等）かどうか
    is_from_bot: bool = False   # ボット自身のメッセージかどうか
    event_type: str = ""        # プラットフォーム固有のイベントタイプ
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def should_process(self) -> bool:
        """このメッセージを処理すべきかどうか"""
        if self.is_from_bot:
            return False
        if self.is_broadcast:
            return False
        if not self.is_bot_addressed:
            return False
        if not self.body:
            return False
        return True

    @property
    def skip_reason(self) -> str:
        """処理をスキップする理由（デバッグ用）"""
        if self.is_from_bot:
            return "own_message"
        if self.is_broadcast:
            return "broadcast"
        if not self.is_bot_addressed:
            return "not_addressed"
        if not self.body:
            return "empty_message"
        return ""


@dataclass
class SendResult:
    """メッセージ送信結果"""
    success: bool
    message_id: str = ""
    error: str = ""


# =============================================================================
# 抽象基底クラス
# =============================================================================


class ChannelAdapter(ABC):
    """
    チャネルアダプター抽象基底クラス

    各プラットフォーム（ChatWork, Slack, LINE等）はこのクラスを継承し、
    プラットフォーム固有のロジックを実装する。

    main.pyはこのインターフェースのみを使い、プラットフォームの詳細を知らない。
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """プラットフォーム名を返す（例: "chatwork"）"""
        ...

    @abstractmethod
    def parse_webhook(self, request_data: Dict[str, Any]) -> Optional[ChannelMessage]:
        """
        Webhookリクエストデータを統一メッセージ型に変換

        Args:
            request_data: Webhookのリクエストボディ（JSON）

        Returns:
            ChannelMessage（パース成功時）、None（無効なリクエスト時）
        """
        ...

    @abstractmethod
    def send_message(
        self,
        room_id: str,
        message: str,
        reply_to: Optional[str] = None,
        **kwargs: Any,
    ) -> SendResult:
        """
        メッセージを送信

        Args:
            room_id: 送信先ルームID
            message: メッセージ本文
            reply_to: 返信先のアカウントID（省略可）
            **kwargs: プラットフォーム固有の追加パラメータ（例: message_thread_id）

        Returns:
            SendResult
        """
        ...

    @abstractmethod
    def get_sender_name(self, room_id: str, sender_id: str) -> str:
        """
        送信者の表示名を取得

        Args:
            room_id: ルームID
            sender_id: アカウントID

        Returns:
            表示名（取得失敗時は"ゲスト"）
        """
        ...

    def clean_message(self, raw_body: str) -> str:
        """
        プラットフォーム固有のタグ等を除去してクリーンなテキストを返す

        デフォルト実装はそのまま返す。サブクラスでオーバーライドする。

        Args:
            raw_body: 元のメッセージ本文

        Returns:
            クリーニング済みメッセージ
        """
        return raw_body.strip() if raw_body else ""

    def is_addressed_to_bot(self, raw_body: str) -> bool:
        """
        メッセージがボット宛かどうかを判定

        デフォルト実装はTrue。サブクラスでオーバーライドする。

        Args:
            raw_body: 元のメッセージ本文

        Returns:
            ボット宛かどうか
        """
        return True


# =============================================================================
# MessageEnvelope — チャネル統一メッセージスキーマ（TASK-13）
# =============================================================================


@dataclass
class MessageEnvelope:
    """
    チャネル統一メッセージエンベロープ

    Brain が受け取る全チャネル共通の入力フォーマット。
    ChatWork, LINE, iPhone, 音声対話 等どのチャネルからの入力も
    この形式に変換してから Brain に渡す。

    【将来の新チャネル追加手順】
    1. ChannelAdapter のサブクラスを作成（例: LineAdapter）
    2. parse_webhook() で ChannelMessage を生成
    3. MessageEnvelope.from_channel_message(msg, org_id) で変換
    4. brain.process_envelope(envelope) に渡す

    設計書: CLAUDE.md §6（ソウルくんの役割）、§2（Truth順位）
    """

    # --- 必須フィールド ---
    message: str       # クリーニング済みメッセージ本文（Brain に渡す）
    room_id: str       # チャネルルームID（プラットフォーム非依存形式）
    account_id: str    # 送信者アカウントID
    sender_name: str   # 送信者表示名

    # --- チャネルメタデータ ---
    channel: str = "chatwork"
    """入力チャネル種別。将来の値: "chatwork" | "line" | "iphone" | "voice" | "telegram" """

    organization_id: str = ""
    """テナントID（CLAUDE.md 鉄則#1: 全クエリに必須）"""

    # --- デバッグ・拡張用 ---
    raw: Optional["ChannelMessage"] = None
    """元の ChannelMessage（デバッグ・プラットフォーム固有処理用）"""

    @classmethod
    def from_channel_message(
        cls,
        msg: "ChannelMessage",
        organization_id: str = "",
    ) -> "MessageEnvelope":
        """
        ChannelMessage から MessageEnvelope を生成するファクトリメソッド

        各チャネルアダプターの parse_webhook() が返す ChannelMessage を
        Brain が扱える統一形式に変換する。

        Args:
            msg: ChannelAdapter.parse_webhook() が返した ChannelMessage
            organization_id: テナントID（鉄則#1）

        Returns:
            MessageEnvelope（brain.process_envelope() に渡す）

        Example:
            # ChatWork Adapter の場合
            msg = chatwork_adapter.parse_webhook(request_data)
            if msg and msg.should_process:
                envelope = MessageEnvelope.from_channel_message(msg, org_id)
                response = await brain.process_envelope(envelope)
        """
        return cls(
            message=msg.body,
            room_id=msg.room_id,
            account_id=msg.sender_id,
            sender_name=msg.sender_name,
            channel=msg.platform,
            organization_id=organization_id,
            raw=msg,
        )
