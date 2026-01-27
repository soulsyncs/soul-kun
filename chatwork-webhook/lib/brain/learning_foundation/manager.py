"""
Phase 2E: 学習基盤 - 学習管理層

設計書: docs/18_phase2e_learning_foundation.md v1.1.0
セクション: 6. 学習の管理（一覧・削除・修正）

ユーザーが学習を管理するためのインターフェースを提供する。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.engine import Connection

from .constants import (
    AuthorityLevel,
    AUTHORITY_PRIORITY,
    LearningCategory,
    LearningScope,
    DELETE_LEARNING_KEYWORDS,
    LIST_LEARNING_KEYWORDS,
    SUCCESS_MESSAGES,
    ERROR_MESSAGES,
    MAX_LEARNINGS_PER_CATEGORY_DISPLAY,
)
from .models import (
    ConversationContext,
    Learning,
)
from .repository import LearningRepository


class LearningManager:
    """学習管理クラス

    学習の一覧表示、削除、修正などの管理機能を提供する。

    設計書セクション6に準拠。
    """

    def __init__(
        self,
        organization_id: str,
        repository: Optional[LearningRepository] = None,
    ):
        """初期化

        Args:
            organization_id: 組織ID
            repository: リポジトリ（指定しない場合は自動生成）
        """
        self.organization_id = organization_id
        self.repository = repository or LearningRepository(organization_id)

    # ========================================================================
    # コマンド検出
    # ========================================================================

    def is_list_command(self, message: str) -> bool:
        """学習一覧コマンドかどうか判定

        Args:
            message: メッセージ

        Returns:
            一覧コマンドかどうか
        """
        message_lower = message.lower().strip()
        for keyword in LIST_LEARNING_KEYWORDS:
            if keyword in message_lower:
                return True
        return False

    def is_delete_command(self, message: str) -> bool:
        """学習削除コマンドかどうか判定

        Args:
            message: メッセージ

        Returns:
            削除コマンドかどうか
        """
        message_lower = message.lower().strip()
        for keyword in DELETE_LEARNING_KEYWORDS:
            if keyword in message_lower:
                return True
        return False

    # ========================================================================
    # 一覧表示
    # ========================================================================

    def list_all(
        self,
        conn: Connection,
        user_id: Optional[str] = None,
        include_inactive: bool = False,
    ) -> Dict[str, List[Learning]]:
        """全学習をカテゴリ別に一覧表示

        Args:
            conn: DB接続
            user_id: ユーザーID（指定時はそのユーザーが教えたものに限定）
            include_inactive: 無効なものも含めるか

        Returns:
            カテゴリ別の学習辞書
        """
        result: Dict[str, List[Learning]] = {}

        for category in LearningCategory:
            learnings = self.repository.find_by_category(
                conn=conn,
                category=category.value,
                active_only=not include_inactive,
                limit=MAX_LEARNINGS_PER_CATEGORY_DISPLAY,
            )

            # ユーザーフィルタ
            if user_id:
                learnings = [
                    l for l in learnings
                    if l.taught_by_account_id == user_id
                ]

            if learnings:
                result[category.value] = learnings

        return result

    def list_by_category(
        self,
        conn: Connection,
        category: str,
        user_id: Optional[str] = None,
        include_inactive: bool = False,
        limit: int = MAX_LEARNINGS_PER_CATEGORY_DISPLAY,
    ) -> List[Learning]:
        """カテゴリ別に学習を一覧表示

        Args:
            conn: DB接続
            category: カテゴリ
            user_id: ユーザーID
            include_inactive: 無効なものも含めるか
            limit: 最大取得件数

        Returns:
            学習のリスト
        """
        learnings = self.repository.find_by_category(
            conn=conn,
            category=category,
            active_only=not include_inactive,
            limit=limit,
        )

        if user_id:
            learnings = [
                l for l in learnings
                if l.taught_by_account_id == user_id
            ]

        return learnings

    def list_by_user(
        self,
        conn: Connection,
        user_id: str,
        include_inactive: bool = False,
    ) -> List[Learning]:
        """ユーザーが教えた学習を一覧表示

        Args:
            conn: DB接続
            user_id: ユーザーID
            include_inactive: 無効なものも含めるか

        Returns:
            学習のリスト
        """
        return self.repository.find_by_user(
            conn=conn,
            user_id=user_id,
            active_only=not include_inactive,
        )

    def format_list_response(
        self,
        learnings_by_category: Dict[str, List[Learning]],
    ) -> str:
        """一覧表示用のレスポンスをフォーマット

        Args:
            learnings_by_category: カテゴリ別の学習辞書

        Returns:
            フォーマットされたレスポンス
        """
        if not learnings_by_category:
            return "まだ何も覚えていないウル🐺"

        lines = ["覚えていることの一覧だウル🐺\n"]

        category_names = {
            "alias": "【別名・略称】",
            "preference": "【好み・やり方】",
            "fact": "【事実・情報】",
            "rule": "【ルール・決まり】",
            "correction": "【間違いの修正】",
            "context": "【文脈・背景】",
            "relationship": "【人間関係】",
            "procedure": "【手順・やり方】",
        }

        for category, learnings in learnings_by_category.items():
            category_name = category_names.get(category, f"【{category}】")
            lines.append(category_name)

            for learning in learnings:
                description = learning.learned_content.get("description", "")
                taught_by = learning.taught_by_name or "不明"

                # 権限レベルの表示
                authority_mark = ""
                if learning.authority_level == AuthorityLevel.CEO.value:
                    authority_mark = "（CEO）"
                elif learning.authority_level == AuthorityLevel.MANAGER.value:
                    authority_mark = "（管理者）"

                lines.append(
                    f"  • {description}{authority_mark}（{taught_by}さんが教えてくれた）"
                )

            lines.append("")  # 空行

        return "\n".join(lines)

    # ========================================================================
    # 削除
    # ========================================================================

    def delete(
        self,
        conn: Connection,
        learning_id: str,
        requester_account_id: str,
        requester_authority: str = AuthorityLevel.USER.value,
    ) -> Tuple[bool, str]:
        """学習を削除

        Args:
            conn: DB接続
            learning_id: 学習ID
            requester_account_id: 削除要求者のアカウントID
            requester_authority: 削除要求者の権限レベル

        Returns:
            (成功したか, メッセージ) のタプル
        """
        # 学習を取得
        learning = self.repository.find_by_id(conn, learning_id)
        if learning is None:
            return False, ERROR_MESSAGES["not_found"]

        # 権限チェック
        if not self._can_delete(learning, requester_account_id, requester_authority):
            return False, "この学習を削除する権限がありませんウル🐺"

        # CEO教えは削除不可
        if learning.authority_level == AuthorityLevel.CEO.value:
            return False, "CEO教えは削除できませんウル🐺 管理者に相談してくださいウル"

        # 削除（論理削除）
        success = self.repository.delete(conn, learning_id, hard_delete=False)
        if not success:
            return False, ERROR_MESSAGES["delete_failed"]

        # 成功メッセージ
        description = learning.learned_content.get("description", "")
        message = SUCCESS_MESSAGES["deleted"].format(description=description)
        return True, message

    def delete_by_description(
        self,
        conn: Connection,
        description_query: str,
        requester_account_id: str,
        requester_authority: str = AuthorityLevel.USER.value,
    ) -> Tuple[bool, str, Optional[Learning]]:
        """説明文で学習を検索して削除

        「〇〇を忘れて」のようなコマンドで使用する。

        Args:
            conn: DB接続
            description_query: 検索クエリ（説明文の一部）
            requester_account_id: 削除要求者のアカウントID
            requester_authority: 削除要求者の権限レベル

        Returns:
            (成功したか, メッセージ, 削除された学習) のタプル
        """
        # 全学習から検索
        learnings, _ = self.repository.find_all(conn, active_only=True)

        # 説明文でフィルタ
        query_lower = description_query.lower()
        matches = []
        for learning in learnings:
            description = learning.learned_content.get("description", "")
            if query_lower in description.lower():
                matches.append(learning)

        if not matches:
            return False, ERROR_MESSAGES["not_found"], None

        if len(matches) > 1:
            # 複数マッチした場合は絞り込みを求める
            match_descriptions = [
                m.learned_content.get("description", "")
                for m in matches
            ]
            return (
                False,
                f"複数の学習が見つかったウル🐺 もう少し具体的に教えてくれるウル？\n"
                + "\n".join(f"  • {d}" for d in match_descriptions[:5]),
                None,
            )

        # 1件のみの場合は削除
        learning = matches[0]
        success, message = self.delete(
            conn, learning.id, requester_account_id, requester_authority
        )
        return success, message, learning if success else None

    def _can_delete(
        self,
        learning: Learning,
        requester_account_id: str,
        requester_authority: str,
    ) -> bool:
        """削除権限があるか判定

        Args:
            learning: 学習
            requester_account_id: 削除要求者のアカウントID
            requester_authority: 削除要求者の権限レベル

        Returns:
            削除権限があるかどうか
        """
        # 自分が教えた学習は削除可能
        if learning.taught_by_account_id == requester_account_id:
            return True

        # 権限レベルが同等以上なら削除可能
        requester_priority = AUTHORITY_PRIORITY.get(requester_authority, 99)
        learning_priority = AUTHORITY_PRIORITY.get(learning.authority_level, 99)
        if requester_priority <= learning_priority:
            return True

        return False

    # ========================================================================
    # 修正
    # ========================================================================

    def update_content(
        self,
        conn: Connection,
        learning_id: str,
        new_content: Dict[str, Any],
        requester_account_id: str,
        requester_authority: str = AuthorityLevel.USER.value,
    ) -> Tuple[bool, str]:
        """学習内容を修正

        Args:
            conn: DB接続
            learning_id: 学習ID
            new_content: 新しい内容
            requester_account_id: 修正要求者のアカウントID
            requester_authority: 修正要求者の権限レベル

        Returns:
            (成功したか, メッセージ) のタプル
        """
        # 学習を取得
        learning = self.repository.find_by_id(conn, learning_id)
        if learning is None:
            return False, ERROR_MESSAGES["not_found"]

        # 権限チェック
        if not self._can_modify(learning, requester_account_id, requester_authority):
            return False, "この学習を修正する権限がありませんウル🐺"

        # CEO教えの修正は管理者権限が必要
        if (
            learning.authority_level == AuthorityLevel.CEO.value and
            requester_authority not in [AuthorityLevel.CEO.value, AuthorityLevel.MANAGER.value]
        ):
            return False, "CEO教えを修正するには管理者権限が必要ですウル🐺"

        # 内容を更新（実際にはsupersedes関係を作成）
        # 新しい学習を作成し、古い学習を置き換え
        new_learning = Learning(
            id="",  # 新規生成
            organization_id=self.organization_id,
            category=learning.category,
            trigger_type=learning.trigger_type,
            trigger_value=learning.trigger_value,
            learned_content=new_content,
            learned_content_version=learning.learned_content_version + 1,
            scope=learning.scope,
            scope_target_id=learning.scope_target_id,
            authority_level=requester_authority,  # 修正者の権限レベル
            valid_from=datetime.now(),
            valid_until=learning.valid_until,
            taught_by_account_id=requester_account_id,
            taught_by_name=None,  # 後で設定
            taught_in_room_id=learning.taught_in_room_id,
            source_message=f"修正: {learning.id}",
            source_context=None,
            detection_pattern=None,
            detection_confidence=1.0,  # 明示的な修正なので確信度は最高
            classification=learning.classification,
            supersedes_id=learning.id,
        )

        from uuid import uuid4
        new_learning.id = str(uuid4())

        # 新しい学習を保存
        new_id = self.repository.save(conn, new_learning)

        # 置き換え関係を設定
        self.repository.update_supersedes(conn, new_id, learning.id)

        # 成功メッセージ
        new_description = new_content.get("description", "")
        message = SUCCESS_MESSAGES["updated"].format(new_description=new_description)
        return True, message

    def _can_modify(
        self,
        learning: Learning,
        requester_account_id: str,
        requester_authority: str,
    ) -> bool:
        """修正権限があるか判定

        Args:
            learning: 学習
            requester_account_id: 修正要求者のアカウントID
            requester_authority: 修正要求者の権限レベル

        Returns:
            修正権限があるかどうか
        """
        # 自分が教えた学習は修正可能
        if learning.taught_by_account_id == requester_account_id:
            return True

        # 権限レベルが同等以上なら修正可能
        requester_priority = AUTHORITY_PRIORITY.get(requester_authority, 99)
        learning_priority = AUTHORITY_PRIORITY.get(learning.authority_level, 99)
        if requester_priority <= learning_priority:
            return True

        return False

    # ========================================================================
    # 統計・分析
    # ========================================================================

    def get_statistics(
        self,
        conn: Connection,
    ) -> Dict[str, Any]:
        """学習の統計情報を取得

        Args:
            conn: DB接続

        Returns:
            統計情報の辞書
        """
        learnings, total_count = self.repository.find_all(
            conn, active_only=True
        )

        # カテゴリ別カウント
        category_counts: Dict[str, int] = {}
        for category in LearningCategory:
            category_counts[category.value] = 0

        for learning in learnings:
            if learning.category in category_counts:
                category_counts[learning.category] += 1

        # 権限レベル別カウント
        authority_counts: Dict[str, int] = {}
        for authority in AuthorityLevel:
            authority_counts[authority.value] = 0

        for learning in learnings:
            if learning.authority_level in authority_counts:
                authority_counts[learning.authority_level] += 1

        # スコープ別カウント
        scope_counts: Dict[str, int] = {}
        for scope in LearningScope:
            scope_counts[scope.value] = 0

        for learning in learnings:
            if learning.scope in scope_counts:
                scope_counts[learning.scope] += 1

        # 適用回数の統計
        apply_counts = [l.apply_count for l in learnings]
        total_applies = sum(apply_counts)
        avg_applies = total_applies / len(learnings) if learnings else 0

        # フィードバックの統計
        positive_feedback = sum(l.positive_feedback_count for l in learnings)
        negative_feedback = sum(l.negative_feedback_count for l in learnings)

        return {
            "total_count": total_count,
            "by_category": category_counts,
            "by_authority": authority_counts,
            "by_scope": scope_counts,
            "total_applies": total_applies,
            "avg_applies": round(avg_applies, 2),
            "positive_feedback": positive_feedback,
            "negative_feedback": negative_feedback,
            "feedback_ratio": (
                round(positive_feedback / (positive_feedback + negative_feedback), 2)
                if positive_feedback + negative_feedback > 0
                else 0
            ),
        }

    def format_statistics_response(
        self,
        statistics: Dict[str, Any],
    ) -> str:
        """統計情報をフォーマット

        Args:
            statistics: get_statistics()の結果

        Returns:
            フォーマットされたレスポンス
        """
        lines = ["📊 学習の統計だウル🐺\n"]

        lines.append(f"📚 覚えていること: {statistics['total_count']}件")
        lines.append(f"🔄 適用回数: {statistics['total_applies']}回（平均{statistics['avg_applies']}回/件）")
        lines.append(f"👍 ポジティブフィードバック: {statistics['positive_feedback']}件")
        lines.append(f"👎 ネガティブフィードバック: {statistics['negative_feedback']}件")
        if statistics['feedback_ratio'] > 0:
            lines.append(f"📈 フィードバック良好率: {statistics['feedback_ratio'] * 100:.0f}%")

        lines.append("\n【カテゴリ別】")
        category_names = {
            "alias": "別名",
            "preference": "好み",
            "fact": "事実",
            "rule": "ルール",
            "correction": "修正",
            "context": "文脈",
            "relationship": "関係",
            "procedure": "手順",
        }
        for category, count in statistics["by_category"].items():
            if count > 0:
                name = category_names.get(category, category)
                lines.append(f"  • {name}: {count}件")

        lines.append("\n【権限レベル別】")
        authority_names = {
            "ceo": "CEO教え",
            "manager": "管理者",
            "user": "一般",
            "system": "システム",
        }
        for authority, count in statistics["by_authority"].items():
            if count > 0:
                name = authority_names.get(authority, authority)
                lines.append(f"  • {name}: {count}件")

        return "\n".join(lines)


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_manager(
    organization_id: str,
    repository: Optional[LearningRepository] = None,
) -> LearningManager:
    """学習管理器を作成

    Args:
        organization_id: 組織ID
        repository: リポジトリ

    Returns:
        LearningManager インスタンス
    """
    return LearningManager(organization_id, repository)
