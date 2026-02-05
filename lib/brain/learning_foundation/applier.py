"""
Phase 2E: 学習基盤 - 学習適用層

設計書: docs/18_phase2e_learning_foundation.md v1.1.0
セクション: 5. 学習の適用

適用可能な学習を検索し、応答に反映する。
"""

import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.engine import Connection

from .constants import (
    AuthorityLevel,
    AUTHORITY_PRIORITY,
    LearningCategory,
    LearningScope,
    TriggerType,
    MENTION_TEMPLATES,
    SUCCESS_MESSAGES,
)
from .models import (
    AppliedLearning,
    ConversationContext,
    Learning,
    LearningLog,
)
from .repository import LearningRepository


class LearningApplier:
    """学習適用クラス

    入力メッセージに対して適用可能な学習を検索し、
    応答生成に反映する。

    設計書セクション5に準拠。
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

    def find_applicable(
        self,
        conn: Connection,
        message: str,
        context: Optional[ConversationContext] = None,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
    ) -> List[Learning]:
        """適用可能な学習を検索

        設計書セクション5.2に従い、以下の優先順位で検索:
        1. CEO教え（authority_level = 'ceo'）
        2. マネージャー教え（authority_level = 'manager'）
        3. ユーザー教え（authority_level = 'user'）
        4. システム学習（authority_level = 'system'）

        Args:
            conn: DB接続
            message: 入力メッセージ
            context: 会話コンテキスト
            user_id: ユーザーID
            room_id: ルームID

        Returns:
            適用可能な学習のリスト（優先度順）
        """
        # コンテキストからuser_id, room_idを補完
        if context:
            user_id = user_id or context.user_id
            room_id = room_id or context.room_id

        # リポジトリから検索
        learnings = self.repository.find_applicable(
            conn=conn,
            message=message,
            user_id=user_id,
            room_id=room_id,
        )

        # カテゴリ別に最適なものを選択
        return self._select_best_learnings(learnings, message)

    def apply(
        self,
        conn: Connection,
        learning: Learning,
        message: str,
        context: Optional[ConversationContext] = None,
        room_id: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> AppliedLearning:
        """学習を適用

        Args:
            conn: DB接続
            learning: 適用する学習
            message: トリガーメッセージ
            context: 会話コンテキスト
            room_id: ルームID
            account_id: アカウントID

        Returns:
            適用結果
        """
        # コンテキストから補完
        if context:
            room_id = room_id or context.room_id
            account_id = account_id or context.user_id

        # 適用回数をインクリメント
        if not learning.id:
            raise ValueError("learning.id is required for apply operation")
        learning_id = learning.id
        self.repository.increment_apply_count(conn, learning_id)

        # ログを記録
        log = LearningLog(
            id=str(uuid4()),
            organization_id=self.organization_id,
            learning_id=learning_id,
            applied_at=datetime.now(),
            applied_in_room_id=room_id,
            applied_for_account_id=account_id,
            trigger_message=message,
            was_successful=True,
            result_description="applied",
        )
        self.repository.save_log(conn, log)

        # 適用結果を生成
        modification = self._generate_modification(learning, message)
        return AppliedLearning(
            learning=learning,
            application_type=learning.category or "unknown",
            before_value=message,
            after_value=modification,
        )

    def apply_all(
        self,
        conn: Connection,
        learnings: List[Learning],
        message: str,
        context: Optional[ConversationContext] = None,
        room_id: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> List[AppliedLearning]:
        """複数の学習を適用

        Args:
            conn: DB接続
            learnings: 適用する学習のリスト
            message: トリガーメッセージ
            context: 会話コンテキスト
            room_id: ルームID
            account_id: アカウントID

        Returns:
            適用結果のリスト
        """
        results = []
        for learning in learnings:
            result = self.apply(
                conn=conn,
                learning=learning,
                message=message,
                context=context,
                room_id=room_id,
                account_id=account_id,
            )
            results.append(result)
        return results

    def build_context_additions(
        self,
        applied_learnings: List[AppliedLearning],
    ) -> Dict[str, Any]:
        """適用した学習からコンテキスト追加情報を構築

        LLMプロンプトに追加する情報を生成する。

        Args:
            applied_learnings: 適用された学習のリスト

        Returns:
            コンテキスト追加情報の辞書
        """
        additions: Dict[str, List[str]] = {
            "aliases": [],        # 別名マッピング
            "preferences": [],    # ユーザー嗜好
            "facts": [],          # 事実情報
            "rules": [],          # ルール
            "corrections": [],    # 修正ルール
            "contexts": [],       # 文脈情報
            "relationships": [],  # 人間関係
            "procedures": [],     # 手順
        }

        for applied in applied_learnings:
            learning = applied.learning
            content = learning.learned_content
            category = learning.category

            if category == LearningCategory.ALIAS.value:
                additions["aliases"].append({
                    "from": content.get("from", ""),
                    "to": content.get("to", ""),
                    "description": content.get("description", ""),
                    "taught_by": learning.taught_by_name,
                })

            elif category == LearningCategory.PREFERENCE.value:
                additions["preferences"].append({
                    "subject": content.get("subject", ""),
                    "preference": content.get("preference", ""),
                    "priority": content.get("priority", "medium"),
                    "description": content.get("description", ""),
                })

            elif category == LearningCategory.FACT.value:
                additions["facts"].append({
                    "subject": content.get("subject", ""),
                    "value": content.get("value", ""),
                    "description": content.get("description", ""),
                    "source": content.get("source", ""),
                })

            elif category == LearningCategory.RULE.value:
                additions["rules"].append({
                    "condition": content.get("condition", ""),
                    "action": content.get("action", ""),
                    "priority": content.get("priority", "medium"),
                    "is_prohibition": content.get("is_prohibition", False),
                    "description": content.get("description", ""),
                    "authority": learning.authority_level,
                })

            elif category == LearningCategory.CORRECTION.value:
                additions["corrections"].append({
                    "wrong_pattern": content.get("wrong_pattern", ""),
                    "correct_pattern": content.get("correct_pattern", ""),
                    "reason": content.get("reason", ""),
                    "description": content.get("description", ""),
                })

            elif category == LearningCategory.CONTEXT.value:
                additions["contexts"].append({
                    "subject": content.get("subject", ""),
                    "context": content.get("context", ""),
                    "implications": content.get("implications", []),
                    "description": content.get("description", ""),
                })

            elif category == LearningCategory.RELATIONSHIP.value:
                additions["relationships"].append({
                    "person1": content.get("person1", ""),
                    "person2": content.get("person2", ""),
                    "relationship": content.get("relationship", ""),
                    "description": content.get("description", ""),
                })

            elif category == LearningCategory.PROCEDURE.value:
                additions["procedures"].append({
                    "task": content.get("task", ""),
                    "steps": content.get("steps", []),
                    "description": content.get("description", ""),
                })

        return additions

    def build_prompt_instructions(
        self,
        context_additions: Dict[str, Any],
    ) -> str:
        """プロンプト用の指示文を生成

        Args:
            context_additions: build_context_additions()の結果

        Returns:
            プロンプトに追加する指示文
        """
        instructions = []

        # 別名
        if context_additions.get("aliases"):
            aliases_text = []
            for alias in context_additions["aliases"]:
                aliases_text.append(
                    f"- 「{alias['from']}」は「{alias['to']}」のこと"
                    + (f"（{alias['taught_by']}さんが教えてくれた）" if alias.get("taught_by") else "")
                )
            instructions.append(
                "【覚えている別名】\n" + "\n".join(aliases_text)
            )

        # ユーザー嗜好
        if context_additions.get("preferences"):
            prefs_text = []
            for pref in context_additions["preferences"]:
                prefs_text.append(f"- {pref['description']}")
            instructions.append(
                "【ユーザーの好み】\n" + "\n".join(prefs_text)
            )

        # 事実
        if context_additions.get("facts"):
            facts_text = []
            for fact in context_additions["facts"]:
                facts_text.append(f"- {fact['description']}")
            instructions.append(
                "【覚えている事実】\n" + "\n".join(facts_text)
            )

        # ルール
        if context_additions.get("rules"):
            rules_text = []
            for rule in context_additions["rules"]:
                priority_mark = "【重要】" if rule.get("priority") == "high" else ""
                authority_mark = "（CEO教え）" if rule.get("authority") == "ceo" else ""
                rules_text.append(
                    f"- {priority_mark}{rule['description']}{authority_mark}"
                )
            instructions.append(
                "【守るべきルール】\n" + "\n".join(rules_text)
            )

        # 修正
        if context_additions.get("corrections"):
            corrections_text = []
            for corr in context_additions["corrections"]:
                corrections_text.append(f"- {corr['description']}")
            instructions.append(
                "【修正すべきパターン】\n" + "\n".join(corrections_text)
            )

        # 文脈
        if context_additions.get("contexts"):
            contexts_text = []
            for ctx in context_additions["contexts"]:
                contexts_text.append(f"- {ctx['description']}")
            instructions.append(
                "【現在の文脈】\n" + "\n".join(contexts_text)
            )

        # 関係
        if context_additions.get("relationships"):
            rels_text = []
            for rel in context_additions["relationships"]:
                rels_text.append(f"- {rel['description']}")
            instructions.append(
                "【人間関係】\n" + "\n".join(rels_text)
            )

        # 手順
        if context_additions.get("procedures"):
            procs_text = []
            for proc in context_additions["procedures"]:
                procs_text.append(f"- {proc['description']}")
            instructions.append(
                "【覚えている手順】\n" + "\n".join(procs_text)
            )

        if not instructions:
            return ""

        return "\n\n".join(instructions)

    def record_feedback(
        self,
        conn: Connection,
        learning_id: str,
        is_positive: bool,
        log_id: Optional[str] = None,
    ) -> bool:
        """フィードバックを記録

        Args:
            conn: DB接続
            learning_id: 学習ID
            is_positive: ポジティブフィードバックかどうか
            log_id: ログID（指定時はログにも記録）

        Returns:
            成功したかどうか
        """
        # 学習のフィードバックカウントを更新
        success = self.repository.update_feedback_count(
            conn, learning_id, is_positive
        )

        # ログにもフィードバックを記録
        if log_id:
            feedback = "positive" if is_positive else "negative"
            self.repository.update_log_feedback(conn, log_id, feedback)

        return success

    # ========================================================================
    # プライベートメソッド
    # ========================================================================

    def _select_best_learnings(
        self,
        learnings: List[Learning],
        message: str,
    ) -> List[Learning]:
        """カテゴリ別に最適な学習を選択

        同じカテゴリ・トリガーで複数の学習がある場合、
        権限レベルが高いものを優先する。

        Args:
            learnings: 学習のリスト
            message: メッセージ

        Returns:
            選択された学習のリスト
        """
        # カテゴリとトリガーでグループ化
        groups: Dict[str, List[Learning]] = {}
        for learning in learnings:
            key = f"{learning.category}:{learning.trigger_value}"
            if key not in groups:
                groups[key] = []
            groups[key].append(learning)

        # 各グループから最優先のものを選択
        selected = []
        for group in groups.values():
            # 権限レベル順にソート
            sorted_group = sorted(
                group,
                key=lambda l: AUTHORITY_PRIORITY.get(l.authority_level, 99)
            )
            # 最優先のものを選択
            selected.append(sorted_group[0])

        return selected

    def _generate_modification(
        self,
        learning: Learning,
        message: str,
    ) -> Optional[str]:
        """学習に基づく修正を生成

        Args:
            learning: 学習
            message: 元のメッセージ

        Returns:
            修正された文字列（修正不要な場合はNone）
        """
        category = learning.category
        content = learning.learned_content

        # 別名の場合：置換を適用
        if category == LearningCategory.ALIAS.value:
            from_value = str(content.get("from", ""))
            to_value = str(content.get("to", ""))
            if from_value and from_value.lower() in message.lower():
                # 大文字小文字を保持した置換
                pattern = re.compile(re.escape(from_value), re.IGNORECASE)
                return pattern.sub(to_value, message)

        # 修正の場合：パターン置換
        if category == LearningCategory.CORRECTION.value:
            wrong_pattern = str(content.get("wrong_pattern", ""))
            correct_pattern = str(content.get("correct_pattern", ""))
            if wrong_pattern and wrong_pattern.lower() in message.lower():
                pattern = re.compile(re.escape(wrong_pattern), re.IGNORECASE)
                return pattern.sub(correct_pattern, message)

        return None

    def _generate_mention_text(
        self,
        learning: Learning,
    ) -> Optional[str]:
        """学習適用時の言及テキストを生成

        設計書セクション5.3に従い、初回使用時は
        「〇〇さん（△△さんが『□□』と呼んでいる方）」
        のように言及する。

        Args:
            learning: 学習

        Returns:
            言及テキスト（言及不要な場合はNone）
        """
        category = learning.category
        content = learning.learned_content

        # 別名の初回使用時
        if category == LearningCategory.ALIAS.value:
            # 初回かどうかの判定（applied_count == 1 の場合）
            if learning.applied_count <= 1:
                template = MENTION_TEMPLATES.get("alias_first_use", "")
                if template:
                    return template.format(
                        resolved_name=content.get("to", ""),
                        teacher_name=learning.taught_by_name or "誰か",
                        alias=content.get("from", ""),
                    )

        # ルール適用時
        if category == LearningCategory.RULE.value:
            template = MENTION_TEMPLATES.get("rule_applied", "")
            if template:
                return template.format(
                    rule_description=content.get("description", ""),
                    action=content.get("action", ""),
                )

        return None


class LearningApplierWithCeoCheck(LearningApplier):
    """CEO教えチェック付き学習適用クラス

    Phase 2D連携：CEO教えとの整合性をチェックする。
    """

    def __init__(
        self,
        organization_id: str,
        repository: Optional[LearningRepository] = None,
        ceo_teachings_fetcher: Optional[Callable[[Connection], List[Learning]]] = None,
    ):
        """初期化

        Args:
            organization_id: 組織ID
            repository: リポジトリ
            ceo_teachings_fetcher: CEO教え取得関数
        """
        super().__init__(organization_id, repository)
        self.ceo_teachings_fetcher = ceo_teachings_fetcher

    def find_applicable_with_ceo_check(
        self,
        conn: Connection,
        message: str,
        context: Optional[ConversationContext] = None,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
    ) -> Tuple[List[Learning], List[Learning]]:
        """CEO教えを優先して適用可能な学習を検索

        Args:
            conn: DB接続
            message: 入力メッセージ
            context: 会話コンテキスト
            user_id: ユーザーID
            room_id: ルームID

        Returns:
            (適用可能な学習, CEO教え) のタプル
        """
        # 通常の検索
        learnings = self.find_applicable(
            conn=conn,
            message=message,
            context=context,
            user_id=user_id,
            room_id=room_id,
        )

        # CEO教えを分離
        ceo_learnings = [
            l for l in learnings
            if l.authority_level == AuthorityLevel.CEO.value
        ]
        non_ceo_learnings = [
            l for l in learnings
            if l.authority_level != AuthorityLevel.CEO.value
        ]

        # CEO教えと矛盾する学習を除外
        if ceo_learnings:
            non_ceo_learnings = self._filter_conflicting_with_ceo(
                ceo_learnings, non_ceo_learnings
            )

        return non_ceo_learnings + ceo_learnings, ceo_learnings

    def _filter_conflicting_with_ceo(
        self,
        ceo_learnings: List[Learning],
        other_learnings: List[Learning],
    ) -> List[Learning]:
        """CEO教えと矛盾する学習を除外

        Args:
            ceo_learnings: CEO教え
            other_learnings: その他の学習

        Returns:
            矛盾しない学習のリスト
        """
        filtered = []
        for learning in other_learnings:
            is_conflicting = False
            for ceo in ceo_learnings:
                if self._is_conflicting(learning, ceo):
                    is_conflicting = True
                    break
            if not is_conflicting:
                filtered.append(learning)
        return filtered

    def _is_conflicting(
        self,
        learning1: Learning,
        learning2: Learning,
    ) -> bool:
        """2つの学習が矛盾するか判定

        Args:
            learning1: 学習1
            learning2: 学習2

        Returns:
            矛盾するかどうか
        """
        # 同じカテゴリ・トリガーで内容が異なる場合は矛盾
        if (
            learning1.category == learning2.category and
            learning1.trigger_value == learning2.trigger_value
        ):
            content1 = learning1.learned_content
            content2 = learning2.learned_content

            # カテゴリ別の矛盾判定
            if learning1.category == LearningCategory.ALIAS.value:
                # 同じfromで異なるto
                if (
                    content1.get("from") == content2.get("from") and
                    content1.get("to") != content2.get("to")
                ):
                    return True

            elif learning1.category == LearningCategory.RULE.value:
                # 同じconditionで異なるaction
                if (
                    content1.get("condition") == content2.get("condition") and
                    content1.get("action") != content2.get("action")
                ):
                    return True

            elif learning1.category == LearningCategory.FACT.value:
                # 同じsubjectで異なるvalue
                if (
                    content1.get("subject") == content2.get("subject") and
                    content1.get("value") != content2.get("value")
                ):
                    return True

        return False


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_applier(
    organization_id: str,
    repository: Optional[LearningRepository] = None,
) -> LearningApplier:
    """学習適用器を作成

    Args:
        organization_id: 組織ID
        repository: リポジトリ

    Returns:
        LearningApplier インスタンス
    """
    return LearningApplier(organization_id, repository)


def create_applier_with_ceo_check(
    organization_id: str,
    repository: Optional[LearningRepository] = None,
    ceo_teachings_fetcher: Optional[Callable[[Connection], List[Learning]]] = None,
) -> LearningApplierWithCeoCheck:
    """CEO教えチェック付き学習適用器を作成

    Args:
        organization_id: 組織ID
        repository: リポジトリ
        ceo_teachings_fetcher: CEO教え取得関数

    Returns:
        LearningApplierWithCeoCheck インスタンス
    """
    return LearningApplierWithCeoCheck(
        organization_id, repository, ceo_teachings_fetcher
    )
