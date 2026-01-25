"""
メモリ管理ハンドラー

main.pyから分割された会話履歴・Memory Framework関連の機能を提供する。

分割元: chatwork-webhook/main.py
分割日: 2026-01-25
バージョン: v10.24.3
"""

import asyncio
import traceback
import sqlalchemy
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Callable


class MemoryHandler:
    """
    会話履歴とMemory Frameworkの管理を行うハンドラークラス

    外部依存を注入することで、main.pyとの疎結合を実現。
    """

    def __init__(
        self,
        firestore_db: Any,
        get_pool: Callable,
        get_secret: Callable,
        max_history_count: int = 100,
        history_expiry_hours: int = 720,
        use_memory_framework: bool = False,
        memory_summary_trigger_count: int = 10,
        memory_default_org_id: str = None,
        conversation_summary_class: type = None,
        conversation_search_class: type = None
    ):
        """
        Args:
            firestore_db: Firestoreクライアント
            get_pool: DB接続プールを取得する関数
            get_secret: Secret Managerから秘密情報を取得する関数
            max_history_count: 保持する会話履歴の最大数
            history_expiry_hours: 会話履歴の有効期限（時間）
            use_memory_framework: Memory Frameworkを使用するか
            memory_summary_trigger_count: サマリー生成のトリガーとなる会話数
            memory_default_org_id: デフォルトの組織ID
            conversation_summary_class: ConversationSummaryクラス（Memory Framework）
            conversation_search_class: ConversationSearchクラス（Memory Framework）
        """
        self.firestore_db = firestore_db
        self.get_pool = get_pool
        self.get_secret = get_secret
        self.max_history_count = max_history_count
        self.history_expiry_hours = history_expiry_hours
        self.use_memory_framework = use_memory_framework
        self.memory_summary_trigger_count = memory_summary_trigger_count
        self.memory_default_org_id = memory_default_org_id
        self.ConversationSummary = conversation_summary_class
        self.ConversationSearch = conversation_search_class

    def get_conversation_history(self, room_id: str, account_id: str) -> List[Dict]:
        """
        会話履歴を取得

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーのアカウントID

        Returns:
            会話履歴のリスト
        """
        try:
            doc_ref = self.firestore_db.collection("conversations").document(f"{room_id}_{account_id}")
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                updated_at = data.get("updated_at")
                if updated_at:
                    expiry_time = datetime.now(timezone.utc) - timedelta(hours=self.history_expiry_hours)
                    if updated_at.replace(tzinfo=timezone.utc) < expiry_time:
                        return []
                return data.get("history", [])[-self.max_history_count:]
        except Exception as e:
            print(f"履歴取得エラー: {e}")
        return []

    def save_conversation_history(self, room_id: str, account_id: str, history: List[Dict]) -> None:
        """
        会話履歴を保存

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーのアカウントID
            history: 保存する会話履歴
        """
        try:
            doc_ref = self.firestore_db.collection("conversations").document(f"{room_id}_{account_id}")
            doc_ref.set({
                "history": history[-self.max_history_count:],
                "updated_at": datetime.now(timezone.utc)
            })
        except Exception as e:
            print(f"履歴保存エラー: {e}")

    def process_memory_after_conversation(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        user_message: str,
        ai_response: str,
        history: List[Dict]
    ) -> None:
        """
        会話完了後にMemory Framework処理を実行

        B1: 会話サマリー - 会話が10件以上溜まったらサマリーを生成
        B2: ユーザー嗜好 - 会話パターンからユーザーの好みを学習
        B4: 会話検索 - 会話をインデックス化（検索可能に）

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーのChatWorkアカウントID
            sender_name: 送信者名
            user_message: ユーザーのメッセージ
            ai_response: AIの応答
            history: 会話履歴

        Note:
            - エラーが発生しても会話処理には影響を与えない
            - 会話数が閾値未満の場合は何もしない（負荷軽減）
        """
        if not self.use_memory_framework:
            return

        if not self.ConversationSummary or not self.ConversationSearch:
            print("⚠️ Memory Frameworkクラスが未設定")
            return

        try:
            print(f"🧠 Memory Framework処理開始 (room={room_id}, account={account_id})")

            # 会話数が閾値未満なら何もしない
            if len(history) < self.memory_summary_trigger_count:
                print(f"   会話数 {len(history)} < 閾値 {self.memory_summary_trigger_count}, スキップ")
                return

            # ユーザー情報を取得
            pool = self.get_pool()
            with pool.connect() as conn:
                # account_idからuser_idとorganization_idを取得
                result = conn.execute(
                    sqlalchemy.text("""
                        SELECT id, organization_id FROM users
                        WHERE chatwork_account_id = :account_id
                        LIMIT 1
                    """),
                    {"account_id": str(account_id)}
                ).fetchone()

                if not result:
                    print(f"   ⚠️ ユーザー未登録: account_id={account_id}")
                    return

                user_id = result[0]
                org_id = result[1]

                if not org_id:
                    print(f"   ⚠️ organization_id未設定: user_id={user_id}")
                    org_id = self.memory_default_org_id

                print(f"   ユーザー特定: user_id={user_id}, org_id={org_id}")

                # OpenRouter APIキーを取得
                openrouter_api_key = self.get_secret("openrouter-api-key")

                # B1: 会話サマリー生成
                self._process_conversation_summary(
                    conn, org_id, user_id, room_id, history, openrouter_api_key
                )

                # B4: 会話検索インデックス
                self._process_conversation_search(
                    conn, org_id, user_id, room_id, user_message, ai_response
                )

            print(f"🧠 Memory Framework処理完了")

        except Exception as e:
            # Memory処理のエラーは会話に影響を与えない
            print(f"⚠️ Memory Framework処理エラー（続行）: {e}")
            traceback.print_exc()

    def _process_conversation_summary(
        self,
        conn: Any,
        org_id: str,
        user_id: str,
        room_id: str,
        history: List[Dict],
        openrouter_api_key: str
    ) -> None:
        """B1: 会話サマリー生成"""
        try:
            summary_service = self.ConversationSummary(
                conn=conn,
                org_id=org_id,
                openrouter_api_key=openrouter_api_key
            )

            # 会話履歴をMemory Frameworkの形式に変換
            conversation_history = []
            for msg in history:
                conversation_history.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                    "timestamp": datetime.now(timezone.utc)
                })

            # 非同期関数を同期的に実行
            result = asyncio.run(
                summary_service.generate_and_save(
                    user_id=user_id,
                    conversation_history=conversation_history,
                    room_id=str(room_id)
                )
            )

            if result.success:
                print(f"   ✅ B1 会話サマリー生成完了: {result.message}")
            else:
                print(f"   ⏭️ B1 会話サマリー: {result.message}")

        except Exception as e:
            print(f"   ⚠️ B1 会話サマリーエラー（続行）: {e}")

    def _process_conversation_search(
        self,
        conn: Any,
        org_id: str,
        user_id: str,
        room_id: str,
        user_message: str,
        ai_response: str
    ) -> None:
        """B4: 会話検索インデックス"""
        try:
            search_service = self.ConversationSearch(
                conn=conn,
                org_id=org_id
            )

            # ユーザーメッセージをインデックス化
            result = asyncio.run(
                search_service.save(
                    user_id=user_id,
                    message_text=user_message,
                    message_type="user",
                    message_time=datetime.now(timezone.utc),
                    room_id=str(room_id)
                )
            )

            # AIレスポンスもインデックス化
            if result.success:
                asyncio.run(
                    search_service.save(
                        user_id=user_id,
                        message_text=ai_response,
                        message_type="assistant",
                        message_time=datetime.now(timezone.utc),
                        room_id=str(room_id)
                    )
                )

            if result.success:
                print(f"   ✅ B4 会話インデックス完了")
            else:
                print(f"   ⏭️ B4 会話インデックス: {result.message}")

        except Exception as e:
            print(f"   ⚠️ B4 会話インデックスエラー（続行）: {e}")

    def clear_conversation_history(self, room_id: str, account_id: str) -> bool:
        """
        会話履歴をクリア

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーのアカウントID

        Returns:
            成功時True
        """
        try:
            doc_ref = self.firestore_db.collection("conversations").document(f"{room_id}_{account_id}")
            doc_ref.delete()
            return True
        except Exception as e:
            print(f"履歴クリアエラー: {e}")
            return False
