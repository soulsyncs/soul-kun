"""
Phase 2E: 学習基盤 - 権限レベル解決層

設計書: docs/18_phase2e_learning_foundation.md v1.1.0
セクション: 5.2 適用順序、4.3 矛盾検出

ユーザーの権限レベルを判定し、学習の優先順位を解決する。
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.engine import Connection

from .constants import (
    AuthorityLevel,
    AUTHORITY_PRIORITY,
    LearningCategory,
)
from .models import Learning


class AuthorityResolver:
    """権限レベル解決クラス

    ユーザーの権限レベルを判定し、
    学習の優先順位付けを行う。

    設計書セクション5.2に準拠。
    """

    def __init__(
        self,
        organization_id: str,
        ceo_account_ids: Optional[List[str]] = None,
        manager_account_ids: Optional[List[str]] = None,
        authority_fetcher: Optional[Callable[[Connection, str], str]] = None,
    ):
        """初期化

        Args:
            organization_id: 組織ID
            ceo_account_ids: CEOのアカウントIDリスト
            manager_account_ids: 管理者のアカウントIDリスト
            authority_fetcher: 権限レベル取得関数（DB連携用）
        """
        self.organization_id = organization_id
        self.ceo_account_ids = set(ceo_account_ids or [])
        self.manager_account_ids = set(manager_account_ids or [])
        self.authority_fetcher = authority_fetcher

    # ========================================================================
    # 権限レベル判定
    # ========================================================================

    def get_authority_level(
        self,
        conn: Optional[Connection],
        account_id: str,
    ) -> str:
        """アカウントIDから権限レベルを判定

        優先順位:
        1. CEOリストに含まれる → ceo
        2. 管理者リストに含まれる → manager
        3. authority_fetcherで取得 → 取得結果
        4. デフォルト → user

        Args:
            conn: DB接続（authority_fetcher使用時）
            account_id: アカウントID

        Returns:
            権限レベル
        """
        # CEOチェック
        if account_id in self.ceo_account_ids:
            return AuthorityLevel.CEO.value

        # 管理者チェック
        if account_id in self.manager_account_ids:
            return AuthorityLevel.MANAGER.value

        # DB連携
        if self.authority_fetcher and conn:
            try:
                fetched = self.authority_fetcher(conn, account_id)
                if fetched in [a.value for a in AuthorityLevel]:
                    return fetched
            except Exception:
                pass  # フォールバックへ

        # デフォルト
        return AuthorityLevel.USER.value

    def is_ceo(self, account_id: str) -> bool:
        """CEOかどうか判定

        Args:
            account_id: アカウントID

        Returns:
            CEOかどうか
        """
        return account_id in self.ceo_account_ids

    def is_manager(self, account_id: str) -> bool:
        """管理者かどうか判定

        Args:
            account_id: アカウントID

        Returns:
            管理者かどうか
        """
        return account_id in self.manager_account_ids

    def is_admin(self, account_id: str) -> bool:
        """管理権限があるか判定（CEO or 管理者）

        Args:
            account_id: アカウントID

        Returns:
            管理権限があるかどうか
        """
        return self.is_ceo(account_id) or self.is_manager(account_id)

    # ========================================================================
    # 権限比較
    # ========================================================================

    def compare_authority(
        self,
        authority1: str,
        authority2: str,
    ) -> int:
        """権限レベルを比較

        Args:
            authority1: 権限レベル1
            authority2: 権限レベル2

        Returns:
            -1: authority1 > authority2（1が高い）
             0: authority1 == authority2
             1: authority1 < authority2（2が高い）
        """
        priority1 = AUTHORITY_PRIORITY.get(authority1, 99)
        priority2 = AUTHORITY_PRIORITY.get(authority2, 99)

        if priority1 < priority2:
            return -1  # 1が高い
        elif priority1 > priority2:
            return 1  # 2が高い
        else:
            return 0  # 同等

    def is_higher_or_equal(
        self,
        authority: str,
        target_authority: str,
    ) -> bool:
        """権限レベルが指定以上か判定

        Args:
            authority: 判定対象の権限レベル
            target_authority: 基準となる権限レベル

        Returns:
            authority >= target_authority かどうか
        """
        return self.compare_authority(authority, target_authority) <= 0

    def is_higher(
        self,
        authority: str,
        target_authority: str,
    ) -> bool:
        """権限レベルが指定より高いか判定

        Args:
            authority: 判定対象の権限レベル
            target_authority: 基準となる権限レベル

        Returns:
            authority > target_authority かどうか
        """
        return self.compare_authority(authority, target_authority) < 0

    # ========================================================================
    # 学習の優先順位付け
    # ========================================================================

    def sort_by_authority(
        self,
        learnings: List[Learning],
        descending: bool = True,
    ) -> List[Learning]:
        """学習を権限レベル順にソート

        Args:
            learnings: 学習のリスト
            descending: 降順（高い権限が先）かどうか

        Returns:
            ソートされた学習のリスト
        """
        return sorted(
            learnings,
            key=lambda l: AUTHORITY_PRIORITY.get(l.authority_level, 99),
            reverse=not descending,  # priorityは小さいほど高い
        )

    def filter_by_authority(
        self,
        learnings: List[Learning],
        min_authority: Optional[str] = None,
        max_authority: Optional[str] = None,
    ) -> List[Learning]:
        """権限レベルでフィルタ

        Args:
            learnings: 学習のリスト
            min_authority: 最低権限レベル（これ以上のものを含む）
            max_authority: 最高権限レベル（これ以下のものを含む）

        Returns:
            フィルタされた学習のリスト
        """
        result = []
        for learning in learnings:
            include = True

            if min_authority:
                if not self.is_higher_or_equal(learning.authority_level, min_authority):
                    include = False

            if max_authority:
                if self.is_higher(learning.authority_level, max_authority):
                    include = False

            if include:
                result.append(learning)

        return result

    def get_highest_authority_learning(
        self,
        learnings: List[Learning],
    ) -> Optional[Learning]:
        """最も権限が高い学習を取得

        Args:
            learnings: 学習のリスト

        Returns:
            最も権限が高い学習（空の場合はNone）
        """
        if not learnings:
            return None

        sorted_learnings = self.sort_by_authority(learnings, descending=True)
        return sorted_learnings[0]

    def group_by_authority(
        self,
        learnings: List[Learning],
    ) -> Dict[str, List[Learning]]:
        """権限レベルでグループ化

        Args:
            learnings: 学習のリスト

        Returns:
            権限レベル別の学習辞書
        """
        groups: Dict[str, List[Learning]] = {}
        for authority in AuthorityLevel:
            groups[authority.value] = []

        for learning in learnings:
            if learning.authority_level in groups:
                groups[learning.authority_level].append(learning)

        return groups

    # ========================================================================
    # 権限に基づく操作可否判定
    # ========================================================================

    def can_teach(
        self,
        conn: Optional[Connection],
        account_id: str,
        category: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """教える権限があるか判定

        Args:
            conn: DB接続
            account_id: アカウントID
            category: カテゴリ（特定カテゴリのチェック）

        Returns:
            (教える権限があるか, 権限レベル) のタプル
        """
        authority = self.get_authority_level(conn, account_id)

        # 全員が教えることができる
        # （ただしCEO教えになるかどうかは権限レベルによる）
        return True, authority

    def can_modify(
        self,
        conn: Optional[Connection],
        account_id: str,
        learning: Learning,
    ) -> Tuple[bool, str]:
        """修正権限があるか判定

        Args:
            conn: DB接続
            account_id: アカウントID
            learning: 修正対象の学習

        Returns:
            (修正権限があるか, 理由) のタプル
        """
        authority = self.get_authority_level(conn, account_id)

        # 自分が教えた学習は修正可能
        if learning.taught_by_account_id == account_id:
            return True, "自分が教えた学習"

        # 権限が高い場合は修正可能
        if self.is_higher_or_equal(authority, learning.authority_level):
            return True, f"権限レベル({authority})が同等以上"

        # CEO教えは特別扱い
        if learning.authority_level == AuthorityLevel.CEO.value:
            if authority == AuthorityLevel.CEO.value:
                return True, "CEO権限"
            return False, "CEO教えはCEOのみ修正可能"

        return False, f"権限レベル({authority})が不足"

    def can_delete(
        self,
        conn: Optional[Connection],
        account_id: str,
        learning: Learning,
    ) -> Tuple[bool, str]:
        """削除権限があるか判定

        Args:
            conn: DB接続
            account_id: アカウントID
            learning: 削除対象の学習

        Returns:
            (削除権限があるか, 理由) のタプル
        """
        authority = self.get_authority_level(conn, account_id)

        # CEO教えは削除不可（アーカイブのみ）
        if learning.authority_level == AuthorityLevel.CEO.value:
            return False, "CEO教えは削除できません"

        # 自分が教えた学習は削除可能
        if learning.taught_by_account_id == account_id:
            return True, "自分が教えた学習"

        # 管理者以上は削除可能
        if self.is_admin(account_id):
            return True, "管理者権限"

        # 権限が高い場合は削除可能
        if self.is_higher(authority, learning.authority_level):
            return True, f"権限レベル({authority})が上"

        return False, f"権限レベル({authority})が不足"

    def can_view_all(
        self,
        conn: Optional[Connection],
        account_id: str,
    ) -> bool:
        """全学習を閲覧する権限があるか判定

        Args:
            conn: DB接続
            account_id: アカウントID

        Returns:
            全学習閲覧権限があるかどうか
        """
        # 管理者以上は全学習を閲覧可能
        return self.is_admin(account_id)

    # ========================================================================
    # 設定の更新
    # ========================================================================

    def add_ceo(self, account_id: str) -> None:
        """CEOリストに追加

        Args:
            account_id: アカウントID
        """
        self.ceo_account_ids.add(account_id)

    def remove_ceo(self, account_id: str) -> None:
        """CEOリストから削除

        Args:
            account_id: アカウントID
        """
        self.ceo_account_ids.discard(account_id)

    def add_manager(self, account_id: str) -> None:
        """管理者リストに追加

        Args:
            account_id: アカウントID
        """
        self.manager_account_ids.add(account_id)

    def remove_manager(self, account_id: str) -> None:
        """管理者リストから削除

        Args:
            account_id: アカウントID
        """
        self.manager_account_ids.discard(account_id)

    def set_authority_fetcher(
        self,
        fetcher: Callable[[Connection, str], str],
    ) -> None:
        """権限レベル取得関数を設定

        Args:
            fetcher: 権限レベル取得関数
        """
        self.authority_fetcher = fetcher


class AuthorityResolverWithDb(AuthorityResolver):
    """DB連携付き権限レベル解決クラス

    organization_admin_configsテーブルと連携して
    CEOや管理者を動的に判定する。
    """

    def __init__(
        self,
        organization_id: str,
        get_admin_config: Optional[Callable[[], Any]] = None,
    ):
        """初期化

        Args:
            organization_id: 組織ID
            get_admin_config: AdminConfig取得関数
        """
        super().__init__(organization_id)
        self.get_admin_config = get_admin_config
        self._config_loaded = False

    def _load_config(self) -> None:
        """設定をロード（遅延ロード）"""
        if self._config_loaded:
            return

        if self.get_admin_config:
            try:
                config = self.get_admin_config()
                if config:
                    # AdminConfigからCEOアカウントIDを取得
                    if hasattr(config, 'admin_account_id'):
                        self.ceo_account_ids.add(str(config.admin_account_id))
                    self._config_loaded = True
            except Exception:
                pass  # 失敗時は空のまま

    def get_authority_level(
        self,
        conn: Optional[Connection],
        account_id: str,
    ) -> str:
        """アカウントIDから権限レベルを判定（DB連携付き）

        Args:
            conn: DB接続
            account_id: アカウントID

        Returns:
            権限レベル
        """
        # 設定をロード
        self._load_config()

        # 親クラスの判定を使用
        return super().get_authority_level(conn, account_id)


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_authority_resolver(
    organization_id: str,
    ceo_account_ids: Optional[List[str]] = None,
    manager_account_ids: Optional[List[str]] = None,
    authority_fetcher: Optional[Callable[[Connection, str], str]] = None,
) -> AuthorityResolver:
    """権限レベル解決器を作成

    Args:
        organization_id: 組織ID
        ceo_account_ids: CEOのアカウントIDリスト
        manager_account_ids: 管理者のアカウントIDリスト
        authority_fetcher: 権限レベル取得関数

    Returns:
        AuthorityResolver インスタンス
    """
    return AuthorityResolver(
        organization_id,
        ceo_account_ids,
        manager_account_ids,
        authority_fetcher,
    )


def create_authority_resolver_with_db(
    organization_id: str,
    get_admin_config: Optional[Callable[[], Any]] = None,
) -> AuthorityResolverWithDb:
    """DB連携付き権限レベル解決器を作成

    Args:
        organization_id: 組織ID
        get_admin_config: AdminConfig取得関数

    Returns:
        AuthorityResolverWithDb インスタンス
    """
    return AuthorityResolverWithDb(organization_id, get_admin_config)
