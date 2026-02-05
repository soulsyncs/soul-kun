"""
Phase 2E: 学習基盤 - 矛盾検出層

設計書: docs/18_phase2e_learning_foundation.md v1.1.0
セクション: 4.3 矛盾検出

新規学習が既存学習と矛盾しないかチェックする。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.engine import Connection

from .constants import (
    AuthorityLevel,
    AUTHORITY_PRIORITY,
    ConflictResolutionStrategy,
    ConflictType,
    LearningCategory,
    CEO_CONFLICT_MESSAGE_TEMPLATE,
    ERROR_MESSAGES,
)
from .models import (
    ConflictInfo,
    Learning,
    Resolution,
)
from .repository import LearningRepository


class ConflictDetector:
    """矛盾検出クラス

    新規学習と既存学習の矛盾を検出し、
    解決策を提案する。

    設計書セクション4.3に準拠。
    """

    def __init__(
        self,
        organization_id: str,
        repository: Optional[LearningRepository] = None,
    ):
        """初期化

        Args:
            organization_id: 組織ID
            repository: リポジトリ
        """
        self.organization_id = organization_id
        self.repository = repository or LearningRepository(organization_id)

    def detect_conflicts(
        self,
        conn: Connection,
        new_learning: Learning,
    ) -> List[ConflictInfo]:
        """新規学習と既存学習の矛盾を検出

        Args:
            conn: DB接続
            new_learning: 新規学習

        Returns:
            検出された矛盾のリスト
        """
        conflicts = []

        # 同じトリガーを持つ既存学習を検索
        existing_learnings = self.repository.find_by_trigger(
            conn=conn,
            trigger_type=new_learning.trigger_type,
            trigger_value=new_learning.trigger_value,
            category=new_learning.category,
        )

        for existing in existing_learnings:
            # 同じ学習はスキップ
            if existing.id == new_learning.id:
                continue

            # 矛盾を検出
            conflict_type = self._detect_conflict_type(new_learning, existing)
            if conflict_type:
                conflicts.append(ConflictInfo(
                    conflict_type=conflict_type,
                    existing_learning=existing,
                    new_learning=new_learning,
                    description=self._describe_conflict(
                        conflict_type, new_learning, existing
                    ),
                    suggested_resolution=self._suggest_resolution(
                        conflict_type, new_learning, existing
                    ),
                ))

        # CEO教えとの矛盾を別途チェック
        ceo_conflicts = self._detect_ceo_conflicts(conn, new_learning)
        conflicts.extend(ceo_conflicts)

        return conflicts

    def has_ceo_conflict(
        self,
        conn: Connection,
        new_learning: Learning,
    ) -> Tuple[bool, Optional[Learning]]:
        """CEO教えとの矛盾があるかチェック

        Args:
            conn: DB接続
            new_learning: 新規学習

        Returns:
            (矛盾があるか, 矛盾するCEO教え) のタプル
        """
        # 新規がCEO教えの場合はチェック不要
        if new_learning.authority_level == AuthorityLevel.CEO.value:
            return False, None

        # CEO教えを検索
        ceo_learnings = self._find_ceo_learnings(
            conn, new_learning.category, new_learning.trigger_value
        )

        for ceo_learning in ceo_learnings:
            if self._is_conflicting_content(new_learning, ceo_learning):
                return True, ceo_learning

        return False, None

    def resolve_conflict(
        self,
        conn: Connection,
        conflict: ConflictInfo,
        strategy: ConflictResolutionStrategy,
        user_choice: Optional[str] = None,
    ) -> Resolution:
        """矛盾を解決

        Args:
            conn: DB接続
            conflict: 矛盾情報
            strategy: 解決戦略
            user_choice: ユーザーの選択（CONFIRM_USERの場合）

        Returns:
            解決結果
        """
        new_learning = conflict.new_learning
        existing_learning = conflict.existing_learning

        if conflict.conflict_type == ConflictType.CEO_CONFLICT.value:
            # CEO教えとの矛盾は拒否
            return Resolution(
                action="reject",
                kept_learning=existing_learning,
                removed_learning=new_learning,
                message=self._format_ceo_conflict_message(existing_learning),
            )

        if strategy == ConflictResolutionStrategy.NEWER_WINS:
            # 新しい学習を優先
            if not new_learning.id or not existing_learning.id:
                raise ValueError("Learning IDs are required for supersede operation")
            self.repository.update_supersedes(
                conn, new_learning.id, existing_learning.id
            )
            return Resolution(
                action="supersede",
                kept_learning=new_learning,
                removed_learning=existing_learning,
                message=f"『{existing_learning.learned_content.get('description', '')}』を"
                        f"『{new_learning.learned_content.get('description', '')}』に更新したウル🐺",
            )

        if strategy == ConflictResolutionStrategy.HIGHER_AUTHORITY:
            # 権限が高い方を優先
            new_priority = AUTHORITY_PRIORITY.get(new_learning.authority_level, 99)
            existing_priority = AUTHORITY_PRIORITY.get(existing_learning.authority_level, 99)

            if new_priority < existing_priority:
                # 新しい方が権限が高い
                if not new_learning.id or not existing_learning.id:
                    raise ValueError("Learning IDs are required for supersede operation")
                self.repository.update_supersedes(
                    conn, new_learning.id, existing_learning.id
                )
                return Resolution(
                    action="supersede",
                    kept_learning=new_learning,
                    removed_learning=existing_learning,
                    message=f"より権限の高い教えを優先して更新したウル🐺",
                )
            else:
                # 既存の方が権限が高い（または同等）
                return Resolution(
                    action="reject",
                    kept_learning=existing_learning,
                    removed_learning=new_learning,
                    message=f"既に『{existing_learning.learned_content.get('description', '')}』として"
                            f"覚えているウル🐺",
                )

        if strategy == ConflictResolutionStrategy.CONFIRM_USER:
            # ユーザーに確認
            if user_choice == "new":
                if not new_learning.id or not existing_learning.id:
                    raise ValueError("Learning IDs are required for supersede operation")
                self.repository.update_supersedes(
                    conn, new_learning.id, existing_learning.id
                )
                return Resolution(
                    action="supersede",
                    kept_learning=new_learning,
                    removed_learning=existing_learning,
                    message=f"了解ウル！『{new_learning.learned_content.get('description', '')}』に"
                            f"更新したウル🐺",
                )
            elif user_choice == "existing":
                return Resolution(
                    action="reject",
                    kept_learning=existing_learning,
                    removed_learning=new_learning,
                    message=f"了解ウル！『{existing_learning.learned_content.get('description', '')}』を"
                            f"維持するウル🐺",
                )
            else:
                # 確認待ち
                return Resolution(
                    action="pending",
                    message=self._format_confirmation_message(conflict),
                )

        # デフォルト：拒否
        return Resolution(
            action="reject",
            kept_learning=existing_learning,
            removed_learning=new_learning,
            message="矛盾が解決できませんでしたウル🐺",
        )

    def get_resolution_strategy(
        self,
        conflict: ConflictInfo,
    ) -> ConflictResolutionStrategy:
        """矛盾に対する解決戦略を決定

        Args:
            conflict: 矛盾情報

        Returns:
            解決戦略
        """
        conflict_type = conflict.conflict_type

        # CEO教えとの矛盾は常に拒否（戦略で解決しない）
        if conflict_type == ConflictType.CEO_CONFLICT.value:
            return ConflictResolutionStrategy.HIGHER_AUTHORITY

        # 同じカテゴリ・トリガーでの内容不一致
        if conflict_type == ConflictType.CONTENT_MISMATCH.value:
            # 権限レベルが異なる場合は権限優先
            new_auth = conflict.new_learning.authority_level
            existing_auth = conflict.existing_learning.authority_level
            if new_auth != existing_auth:
                return ConflictResolutionStrategy.HIGHER_AUTHORITY
            # 同じ権限レベルの場合はユーザー確認
            return ConflictResolutionStrategy.CONFIRM_USER

        # ルールの矛盾
        if conflict_type == ConflictType.RULE_CONFLICT.value:
            # ルールの矛盾は常にユーザー確認
            return ConflictResolutionStrategy.CONFIRM_USER

        # デフォルト：新しい方を優先
        return ConflictResolutionStrategy.NEWER_WINS

    # ========================================================================
    # プライベートメソッド
    # ========================================================================

    def _detect_conflict_type(
        self,
        new_learning: Learning,
        existing_learning: Learning,
    ) -> Optional[str]:
        """矛盾タイプを検出

        Args:
            new_learning: 新規学習
            existing_learning: 既存学習

        Returns:
            矛盾タイプ（矛盾なしの場合はNone）
        """
        # カテゴリが異なる場合は矛盾なし
        if new_learning.category != existing_learning.category:
            return None

        # 内容を比較
        if self._is_conflicting_content(new_learning, existing_learning):
            if new_learning.category == LearningCategory.RULE.value:
                return ConflictType.RULE_CONFLICT.value
            return ConflictType.CONTENT_MISMATCH.value

        return None

    def _is_conflicting_content(
        self,
        learning1: Learning,
        learning2: Learning,
    ) -> bool:
        """内容が矛盾するか判定

        Args:
            learning1: 学習1
            learning2: 学習2

        Returns:
            矛盾するかどうか
        """
        content1 = learning1.learned_content
        content2 = learning2.learned_content
        category = learning1.category

        # カテゴリ別の矛盾判定
        if category == LearningCategory.ALIAS.value:
            # 別名：同じfromで異なるto
            if content1.get("from") == content2.get("from"):
                return content1.get("to") != content2.get("to")

        elif category == LearningCategory.RULE.value:
            # ルール：同じconditionで異なるaction
            if content1.get("condition") == content2.get("condition"):
                return content1.get("action") != content2.get("action")

        elif category == LearningCategory.FACT.value:
            # 事実：同じsubjectで異なるvalue
            if content1.get("subject") == content2.get("subject"):
                return content1.get("value") != content2.get("value")

        elif category == LearningCategory.PREFERENCE.value:
            # 好み：同じsubjectで異なるpreference
            if content1.get("subject") == content2.get("subject"):
                return content1.get("preference") != content2.get("preference")

        elif category == LearningCategory.CORRECTION.value:
            # 修正：同じwrong_patternで異なるcorrect_pattern
            if content1.get("wrong_pattern") == content2.get("wrong_pattern"):
                return content1.get("correct_pattern") != content2.get("correct_pattern")

        elif category == LearningCategory.PROCEDURE.value:
            # 手順：同じtaskで異なるsteps
            if content1.get("task") == content2.get("task"):
                return content1.get("steps") != content2.get("steps")

        return False

    def _detect_ceo_conflicts(
        self,
        conn: Connection,
        new_learning: Learning,
    ) -> List[ConflictInfo]:
        """CEO教えとの矛盾を検出

        Args:
            conn: DB接続
            new_learning: 新規学習

        Returns:
            検出された矛盾のリスト
        """
        conflicts: List[ConflictInfo] = []

        # 新規がCEO教えの場合はチェック不要
        if new_learning.authority_level == AuthorityLevel.CEO.value:
            return conflicts

        # CEO教えを検索
        ceo_learnings = self._find_ceo_learnings(
            conn, new_learning.category, new_learning.trigger_value
        )

        for ceo_learning in ceo_learnings:
            if self._is_conflicting_content(new_learning, ceo_learning):
                conflicts.append(ConflictInfo(
                    conflict_type=ConflictType.CEO_CONFLICT.value,
                    existing_learning=ceo_learning,
                    new_learning=new_learning,
                    description=f"CEO教え『{ceo_learning.learned_content.get('description', '')}』と矛盾",
                    suggested_resolution=ConflictResolutionStrategy.HIGHER_AUTHORITY.value,
                ))

        return conflicts

    def _find_ceo_learnings(
        self,
        conn: Connection,
        category: str,
        trigger_value: str,
    ) -> List[Learning]:
        """CEO教えを検索

        Args:
            conn: DB接続
            category: カテゴリ
            trigger_value: トリガー値

        Returns:
            CEO教えのリスト
        """
        all_learnings = self.repository.find_by_category(
            conn=conn,
            category=category,
            active_only=True,
        )

        return [
            l for l in all_learnings
            if l.authority_level == AuthorityLevel.CEO.value
        ]

    def _describe_conflict(
        self,
        conflict_type: str,
        new_learning: Learning,
        existing_learning: Learning,
    ) -> str:
        """矛盾の説明文を生成

        Args:
            conflict_type: 矛盾タイプ
            new_learning: 新規学習
            existing_learning: 既存学習

        Returns:
            説明文
        """
        new_desc = new_learning.learned_content.get("description", "")
        existing_desc = existing_learning.learned_content.get("description", "")

        if conflict_type == ConflictType.CEO_CONFLICT.value:
            return f"CEO教え『{existing_desc}』と新しい教え『{new_desc}』が矛盾しています"

        if conflict_type == ConflictType.RULE_CONFLICT.value:
            return f"ルール『{existing_desc}』と新しいルール『{new_desc}』が矛盾しています"

        return f"『{existing_desc}』と『{new_desc}』が矛盾しています"

    def _suggest_resolution(
        self,
        conflict_type: str,
        new_learning: Learning,
        existing_learning: Learning,
    ) -> str:
        """解決策を提案

        Args:
            conflict_type: 矛盾タイプ
            new_learning: 新規学習
            existing_learning: 既存学習

        Returns:
            解決策の提案
        """
        if conflict_type == ConflictType.CEO_CONFLICT.value:
            return ConflictResolutionStrategy.HIGHER_AUTHORITY.value

        new_priority = AUTHORITY_PRIORITY.get(new_learning.authority_level, 99)
        existing_priority = AUTHORITY_PRIORITY.get(existing_learning.authority_level, 99)

        if new_priority != existing_priority:
            return ConflictResolutionStrategy.HIGHER_AUTHORITY.value

        return ConflictResolutionStrategy.CONFIRM_USER.value

    def _format_ceo_conflict_message(
        self,
        ceo_learning: Learning,
    ) -> str:
        """CEO教え矛盾時のメッセージをフォーマット

        Args:
            ceo_learning: 矛盾するCEO教え

        Returns:
            フォーマットされたメッセージ
        """
        ceo_teaching = ceo_learning.learned_content.get("description", "")
        return CEO_CONFLICT_MESSAGE_TEMPLATE.format(ceo_teaching=ceo_teaching)

    def _format_confirmation_message(
        self,
        conflict: ConflictInfo,
    ) -> str:
        """確認メッセージをフォーマット

        Args:
            conflict: 矛盾情報

        Returns:
            フォーマットされたメッセージ
        """
        existing_desc = conflict.existing_learning.learned_content.get("description", "")
        new_desc = conflict.new_learning.learned_content.get("description", "")

        return (
            f"ちょっと待ってウル🐺\n\n"
            f"既に『{existing_desc}』として覚えているウル。\n"
            f"『{new_desc}』に更新していいウル？\n\n"
            f"・「更新して」→ 新しい内容に変更\n"
            f"・「そのままで」→ 既存の内容を維持"
        )


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_conflict_detector(
    organization_id: str,
    repository: Optional[LearningRepository] = None,
) -> ConflictDetector:
    """矛盾検出器を作成

    Args:
        organization_id: 組織ID
        repository: リポジトリ

    Returns:
        ConflictDetector インスタンス
    """
    return ConflictDetector(organization_id, repository)
