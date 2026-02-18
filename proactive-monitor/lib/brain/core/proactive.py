# lib/brain/core/proactive.py
"""
SoulkunBrain 能動的メッセージ生成

CLAUDE.md鉄則1b準拠: 能動的出力も脳が生成。
generate_proactive_message と関連する判断・生成メソッドを含む。

v11.2.0: Guardian安全チェックを追加（P1修正）
能動的メッセージ生成後、送信前にセキュリティNGパターンと
機密情報漏洩チェックを実施してCLAUDE.md §1「全出力は脳を通る」を実現。
"""

import logging
import re
from typing import Optional, Dict, Any, List

from lib.brain.guardian_layer import SECURITY_NG_PATTERNS

logger = logging.getLogger(__name__)


def _check_proactive_message_safety(message: str) -> Optional[str]:
    """
    能動的メッセージの安全チェック（Guardian Layerに準拠）

    Guardian Layerのセキュリティチェック（優先度2）をProactiveメッセージに適用。
    通常の会話は `guardian_layer.check()` を通るが、Proactiveメッセージは
    従来それを経由していなかった（P1問題）。このチェックで補完する。

    Returns:
        str: ブロック理由（Noneなら安全）
    """
    for pattern in SECURITY_NG_PATTERNS:
        if re.search(pattern, message):
            return f"セキュリティNGパターンが検出されました（パターン: {pattern[:30]}...）"
    return None


class ProactiveMixin:
    """SoulkunBrain能動的メッセージ生成関連メソッドを提供するMixin"""

    # =========================================================================
    # 能動的メッセージ生成（CLAUDE.md鉄則1b準拠）
    # =========================================================================

    async def generate_proactive_message(
        self,
        trigger_type: str,
        trigger_details: Dict[str, Any],
        user_id: str,
        organization_id: str,
        room_id: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> "ProactiveMessageResult":
        """
        能動的メッセージを生成する（脳経由）

        CLAUDE.md鉄則1b: 能動的出力も脳が生成
        システムが自発的に送るメッセージも脳が判断・生成する。

        【処理フロー】
        1. 記憶層: ユーザーのコンテキスト取得
           - 過去の会話履歴
           - ユーザーの好み・性格
           - 最近の感情傾向

        2. 理解層: トリガー状況の理解
           - なぜこのトリガーが発火したか
           - ユーザーにとってどういう状況か

        3. 判断層: 送信判断
           - 今このタイミングで送るべきか
           - どのようなトーンで送るべきか

        4. 生成層: メッセージ生成
           - ユーザーの好みに合わせた言葉遣い
           - 状況に応じた内容
           - ソウルくんらしい表現

        Args:
            trigger_type: トリガータイプ（goal_abandoned, task_overload等）
            trigger_details: トリガーの詳細情報
            user_id: ユーザーID
            organization_id: 組織ID
            room_id: ChatWorkルームID（オプション）
            account_id: ChatWorkアカウントID（オプション）

        Returns:
            ProactiveMessageResult: 生成結果
        """
        from lib.brain.models import ProactiveMessageResult, ProactiveMessageTone

        try:
            logger.info(
                f"🧠 Brain generating proactive message: "
                f"trigger={trigger_type}, user={user_id}"
            )

            # 1. 記憶層: ユーザーのコンテキスト取得
            context_used: Dict[str, Any] = {}

            # ユーザー情報を取得
            user_info = None
            try:
                if self.memory_access:
                    # users.id(UUID)とpersons.id(integer)は別体系のため、
                    # 全員取得して名前ありの最初の人物を使用
                    user_info_list = await self.memory_access.get_person_info(limit=10)
                    if user_info_list:
                        for person in user_info_list:
                            if hasattr(person, 'name') and person.name:
                                user_info = person
                                context_used["user_name"] = person.name
                                context_used["user_department"] = getattr(person, 'department', '')
                                break
            except Exception as e:
                logger.warning(f"Failed to get user info: {type(e).__name__}")

            # 最近の会話履歴を取得
            # v10.54.4: get_conversation_historyは未実装のため、get_recent_conversationを使用
            recent_conversations = []
            try:
                if self.memory_access and room_id:
                    all_conversations = await self.memory_access.get_recent_conversation(
                        room_id=room_id,
                        user_id=user_id,
                    )
                    recent_conversations = all_conversations[:5]  # 最大5件に制限
                    context_used["recent_conversations_count"] = len(recent_conversations)
            except Exception as e:
                logger.warning(f"Failed to get conversation history: {type(e).__name__}")

            # 2. 理解層: トリガー状況の理解
            trigger_context = self._understand_trigger_context(
                trigger_type=trigger_type,
                trigger_details=trigger_details,
                user_info=user_info,
            )
            context_used["trigger_context"] = trigger_context

            # 3. 判断層: 送信判断
            should_send, send_reason, tone = self._decide_proactive_action(
                trigger_type=trigger_type,
                trigger_details=trigger_details,
                recent_conversations=recent_conversations,
                user_info=user_info,
            )

            if not should_send:
                logger.info(f"🧠 Brain decided not to send: {send_reason}")
                return ProactiveMessageResult(
                    should_send=False,
                    reason=send_reason,
                    confidence=0.8,
                    context_used=context_used,
                )

            # 4. 生成層: メッセージ生成
            message = await self._generate_proactive_message_content(
                trigger_type=trigger_type,
                trigger_details=trigger_details,
                tone=tone,
                user_info=user_info,
                recent_conversations=recent_conversations,
            )

            # 5. Guardian安全チェック（P1修正: v11.2.0）
            # CLAUDE.md §1「全出力は脳を通る」— 能動的メッセージも送信前にセキュリティ検証
            block_reason = _check_proactive_message_safety(message)
            if block_reason:
                logger.warning(
                    f"[Proactive][Guardian] Message blocked by safety check: {block_reason}"
                )
                return ProactiveMessageResult(
                    should_send=False,
                    reason=f"Guardian安全チェックによりブロック: {block_reason}",
                    confidence=0.0,
                )

            logger.info(f"🧠 Brain generated proactive message (Guardian: PASS)")

            return ProactiveMessageResult(
                should_send=True,
                message=message,
                reason=send_reason,
                confidence=0.85,
                tone=tone,
                context_used=context_used,
            )

        except Exception as e:
            logger.error(f"Error generating proactive message: {type(e).__name__}")
            return ProactiveMessageResult(
                should_send=False,
                reason=f"Error: {type(e).__name__}",
                confidence=0.0,
                debug_info={"error": type(e).__name__},
            )

    def _understand_trigger_context(
        self,
        trigger_type: str,
        trigger_details: Dict[str, Any],
        user_info: Optional[Any] = None,
    ) -> str:
        """トリガーの状況を理解する"""
        trigger_contexts = {
            "goal_abandoned": "目標が{days}日間更新されていない。進捗確認が必要。",
            "task_overload": "タスクが{count}件溜まっている。サポートが必要かもしれない。",
            "emotion_decline": "ネガティブな感情が続いている。気遣いが必要。",
            "goal_achieved": "目標を達成した。お祝いと次のステップへの励まし。",
            "task_completed_streak": "タスクを{count}件連続で完了。励ましと称賛。",
            "long_absence": "{days}日間活動がない。久しぶりの声かけ。",
        }

        template = trigger_contexts.get(trigger_type, "状況を確認する必要がある。")
        try:
            return template.format(**trigger_details)
        except KeyError:
            return template

    def _decide_proactive_action(
        self,
        trigger_type: str,
        trigger_details: Dict[str, Any],
        recent_conversations: List[Any],
        user_info: Optional[Any] = None,
    ) -> tuple:
        """送信判断を行う"""
        from lib.brain.models import ProactiveMessageTone

        # トリガータイプごとのデフォルト設定
        trigger_configs = {
            "goal_abandoned": (True, "目標進捗の確認", ProactiveMessageTone.SUPPORTIVE),
            "task_overload": (True, "タスク過多のサポート", ProactiveMessageTone.SUPPORTIVE),
            "emotion_decline": (True, "感情的なサポート", ProactiveMessageTone.CONCERNED),
            "goal_achieved": (True, "目標達成のお祝い", ProactiveMessageTone.CELEBRATORY),
            "task_completed_streak": (True, "連続完了の称賛", ProactiveMessageTone.ENCOURAGING),
            "long_absence": (True, "久しぶりの挨拶", ProactiveMessageTone.FRIENDLY),
        }

        config = trigger_configs.get(
            trigger_type,
            (True, "一般的なフォローアップ", ProactiveMessageTone.FRIENDLY)
        )

        # 最近の会話がネガティブな場合は慎重に
        if recent_conversations:
            # TODO Phase 2N-Advanced: 会話内容のセンチメント分析で判断を調整
            pass

        return config

    async def _generate_proactive_message_content(
        self,
        trigger_type: str,
        trigger_details: Dict[str, Any],
        tone: "ProactiveMessageTone",
        user_info: Optional[Any] = None,
        recent_conversations: Optional[List[Any]] = None,
    ) -> str:
        """メッセージ内容を生成する"""
        from lib.brain.models import ProactiveMessageTone

        # ユーザー名を取得
        user_name = ""
        if user_info and hasattr(user_info, "name"):
            user_name = f"{user_info.name}さん、"

        # トリガータイプごとのメッセージテンプレート
        # ソウルくんのキャラクター（語尾「ウル」、絵文字🐺）を維持
        message_templates = {
            "goal_abandoned": {
                ProactiveMessageTone.SUPPORTIVE: [
                    f"{user_name}目標の進捗はどうですかウル？🐺 何か手伝えることがあれば言ってくださいね",
                    f"{user_name}目標について、最近どんな感じですかウル？🐺 一緒に確認してみましょうか",
                ],
                ProactiveMessageTone.FRIENDLY: [
                    f"{user_name}目標のこと、ちょっと気になってましたウル🐺 調子はどうですか？",
                ],
            },
            "task_overload": {
                ProactiveMessageTone.SUPPORTIVE: [
                    f"{user_name}タスクがたくさんあるみたいですねウル🐺 優先順位を一緒に整理しましょうか？",
                    f"{user_name}お仕事が忙しそうですねウル🐺 何かお手伝いできることはありますか？",
                ],
            },
            "emotion_decline": {
                ProactiveMessageTone.CONCERNED: [
                    f"{user_name}最近どうですかウル？🐺 何か気になることがあれば聞きますよ",
                    f"{user_name}少し心配してましたウル🐺 大丈夫ですか？無理しないでくださいね",
                ],
            },
            "goal_achieved": {
                ProactiveMessageTone.CELEBRATORY: [
                    f"{user_name}おめでとうございますウル！🎉🐺 目標達成、すごいですね！次はどんなことに挑戦しますか？",
                    f"{user_name}やりましたねウル！🎉🐺 素晴らしい成果です！この調子で頑張りましょう！",
                ],
            },
            "task_completed_streak": {
                ProactiveMessageTone.ENCOURAGING: [
                    f"{user_name}タスクをどんどん片付けてますねウル！🎉🐺 すごい調子です！",
                    f"{user_name}いい感じでタスクが進んでますねウル！✨🐺 この調子です！",
                ],
            },
            "long_absence": {
                ProactiveMessageTone.FRIENDLY: [
                    f"{user_name}お久しぶりですウル！🐺 最近どうしてましたか？",
                    f"{user_name}しばらくでしたねウル！🐺 元気にしてましたか？",
                ],
            },
        }

        # テンプレートを取得
        templates = message_templates.get(trigger_type, {})
        tone_templates = templates.get(tone, templates.get(ProactiveMessageTone.FRIENDLY, []))

        if not tone_templates:
            # フォールバック
            return f"{user_name}何かお手伝いできることはありますかウル？🐺"

        # ランダムに選択
        import random
        template = random.choice(tone_templates)

        # プレースホルダを置換
        try:
            return template.format(**trigger_details)
        except KeyError:
            return template
