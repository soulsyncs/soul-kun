"""
管理者設定モジュール（Phase A）

組織ごとの管理者設定（ADMIN_ACCOUNT_ID, ADMIN_ROOM_ID等）を
データベースから取得し、キャッシュ付きで提供する。

背景:
    - 10+ファイルにハードコードされていた管理者設定を一元管理
    - Phase 4（マルチテナント）対応の基盤
    - 将来的に複数組織をサポート可能に

使用例:
    from lib.admin_config import get_admin_config, AdminConfig

    # 組織IDを指定して取得
    config = get_admin_config("5f98365f-e7c5-4f48-9918-7fe9aabae5df")
    print(config.admin_account_id)  # "1728974"
    print(config.admin_room_id)     # "405315911"

    # デフォルト組織（ソウルシンクス）を取得
    config = get_admin_config()
    print(config.is_admin("1728974"))  # True

    # 権限チェック
    if config.is_authorized_room("405315911"):
        # 管理部からのリクエストとして処理
        pass

キャッシュ:
    - TTL: 1時間（環境変数 ADMIN_CONFIG_CACHE_TTL_SECONDS で変更可能）
    - キャッシュクリア: clear_admin_config_cache() を呼び出し
    - テスト時は clear_admin_config_cache() でリセット可能

フォールバック:
    - DB接続エラー時はハードコードされたデフォルト値を返す
    - これにより既存の動作との後方互換性を維持
"""

import os
import time
import threading
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Set

from sqlalchemy import text

logger = logging.getLogger(__name__)


# =============================================================================
# 定数: フォールバック値（後方互換性のため）
# =============================================================================
# DB接続エラー時に使用するデフォルト値
# これらは元々ハードコードされていた値

DEFAULT_ORG_ID = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"  # ソウルシンクス
DEFAULT_ADMIN_ACCOUNT_ID = "1728974"  # カズさん
DEFAULT_ADMIN_ROOM_ID = "405315911"   # 管理部
DEFAULT_ADMIN_DM_ROOM_ID = "217825794"  # カズさんへのDM
DEFAULT_BOT_ACCOUNT_ID = "7399137"    # ソウルくん

# キャッシュTTL（秒）- 環境変数で上書き可能
CACHE_TTL_SECONDS = int(os.getenv("ADMIN_CONFIG_CACHE_TTL_SECONDS", "3600"))  # 1時間


# =============================================================================
# データクラス: AdminConfig
# =============================================================================

@dataclass(frozen=True)
class AdminConfig:
    """
    組織の管理者設定

    frozen=True で不変オブジェクトとし、スレッドセーフを保証。
    キャッシュに保存されるため、不変であることが重要。

    Attributes:
        organization_id: 組織ID（UUID文字列）
        admin_account_id: 管理者のChatWork account_id
        admin_name: 管理者の名前（表示用）
        admin_room_id: 管理部グループチャットのroom_id
        admin_room_name: 管理部ルームの名前（表示用）
        admin_dm_room_id: 管理者へのDMルームID（オプション）
        authorized_room_ids: 認可されたルームID集合
        bot_account_id: ボットのaccount_id
        is_active: 有効フラグ
    """
    organization_id: str
    admin_account_id: str
    admin_name: Optional[str] = None
    admin_room_id: str = DEFAULT_ADMIN_ROOM_ID
    admin_room_name: Optional[str] = None
    admin_dm_room_id: Optional[str] = None
    authorized_room_ids: frozenset = field(default_factory=frozenset)
    bot_account_id: str = DEFAULT_BOT_ACCOUNT_ID
    is_active: bool = True

    def is_admin(self, account_id: str) -> bool:
        """
        指定されたaccount_idが管理者かどうかを判定

        Args:
            account_id: ChatWork account_id（文字列または数値）

        Returns:
            True: 管理者である
            False: 管理者でない
        """
        return str(account_id) == str(self.admin_account_id)

    def is_authorized_room(self, room_id: str) -> bool:
        """
        指定されたroom_idが認可されたルームかどうかを判定

        管理部ルームまたはauthorized_room_idsに含まれていればTrue

        Args:
            room_id: ChatWork room_id（文字列または数値）

        Returns:
            True: 認可されたルームである
            False: 認可されていない
        """
        room_id_str = str(room_id)
        room_id_int = int(room_id) if room_id_str.isdigit() else None

        # 管理部ルームならOK
        if room_id_str == str(self.admin_room_id):
            return True

        # 認可ルームリストに含まれていればOK
        if room_id_int and room_id_int in self.authorized_room_ids:
            return True

        return False

    def is_bot(self, account_id: str) -> bool:
        """
        指定されたaccount_idがボット自身かどうかを判定

        Args:
            account_id: ChatWork account_id

        Returns:
            True: ボット自身
            False: ボットではない
        """
        return str(account_id) == str(self.bot_account_id)

    def get_admin_mention(self) -> str:
        """
        管理者へのメンション文字列を生成

        Returns:
            "[To:1728974]" 形式のメンション文字列
        """
        return f"[To:{self.admin_account_id}]"

    def get_admin_mention_with_name(self) -> str:
        """
        管理者へのメンション文字列を名前付きで生成

        Returns:
            "[To:1728974] 菊地さん" 形式のメンション文字列
        """
        if self.admin_name:
            # 姓のみを使用（"菊地雅克" -> "菊地さん"）
            family_name = self.admin_name.split()[0] if ' ' in self.admin_name else self.admin_name[:2]
            return f"[To:{self.admin_account_id}] {family_name}さん"
        return self.get_admin_mention()


# =============================================================================
# キャッシュ
# =============================================================================

@dataclass
class _CacheEntry:
    """キャッシュエントリ"""
    config: AdminConfig
    expires_at: float


# グローバルキャッシュ（スレッドセーフ）
_cache: dict[str, _CacheEntry] = {}
_cache_lock = threading.Lock()


def _is_cache_valid(entry: _CacheEntry) -> bool:
    """キャッシュエントリが有効かどうかを判定"""
    return time.time() < entry.expires_at


# =============================================================================
# メイン関数
# =============================================================================

def get_admin_config(org_id: Optional[str] = None) -> AdminConfig:
    """
    組織の管理者設定を取得

    DBから設定を取得し、キャッシュに保存する。
    DB接続エラー時はフォールバック値を返す。

    Args:
        org_id: 組織ID（UUID文字列）。Noneの場合はデフォルト組織。

    Returns:
        AdminConfig: 管理者設定

    Example:
        # デフォルト組織（ソウルシンクス）
        config = get_admin_config()

        # 特定の組織
        config = get_admin_config("5f98365f-e7c5-4f48-9918-7fe9aabae5df")

    Note:
        - キャッシュTTLは1時間（ADMIN_CONFIG_CACHE_TTL_SECONDS環境変数で変更可能）
        - DB接続エラー時はログを出力してフォールバック値を返す
        - フォールバック値はキャッシュされない（次回は再度DB取得を試みる）
    """
    # デフォルト組織ID
    if org_id is None:
        org_id = DEFAULT_ORG_ID

    # キャッシュ確認
    with _cache_lock:
        if org_id in _cache and _is_cache_valid(_cache[org_id]):
            logger.debug(f"AdminConfig cache hit: org_id={org_id}")
            return _cache[org_id].config

    # DBから取得を試みる
    try:
        config = _fetch_from_db(org_id)
        if config:
            # キャッシュに保存
            with _cache_lock:
                _cache[org_id] = _CacheEntry(
                    config=config,
                    expires_at=time.time() + CACHE_TTL_SECONDS
                )
            logger.debug(f"AdminConfig fetched from DB: org_id={org_id}")
            return config
    except Exception as e:
        logger.warning(
            f"Failed to fetch AdminConfig from DB, using fallback: "
            f"org_id={org_id}, error={e}"
        )

    # フォールバック: デフォルト値を返す（キャッシュしない）
    logger.info(f"Using fallback AdminConfig: org_id={org_id}")
    return _get_fallback_config(org_id)


def _fetch_from_db(org_id: str) -> Optional[AdminConfig]:
    """
    DBから管理者設定を取得

    Args:
        org_id: 組織ID

    Returns:
        AdminConfig: 取得成功時
        None: 該当データなし
    """
    # 遅延インポート（循環参照回避）
    # v10.31.4: 相対インポートに変更（googleapiclient警告修正）
    from .db import get_db_pool

    pool = get_db_pool()
    with pool.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    organization_id,
                    admin_account_id,
                    admin_name,
                    admin_room_id,
                    admin_room_name,
                    admin_dm_room_id,
                    authorized_room_ids,
                    bot_account_id,
                    is_active
                FROM organization_admin_configs
                WHERE organization_id = :org_id
                  AND is_active = TRUE
            """),
            {"org_id": org_id}
        ).fetchone()

    if result is None:
        logger.warning(f"No AdminConfig found in DB: org_id={org_id}")
        return None

    # authorized_room_idsはPostgreSQLのBIGINT配列として返される
    authorized_rooms = result[6] if result[6] else []
    authorized_room_ids = frozenset(authorized_rooms)

    return AdminConfig(
        organization_id=str(result[0]),
        admin_account_id=str(result[1]),
        admin_name=result[2],
        admin_room_id=str(result[3]),
        admin_room_name=result[4],
        admin_dm_room_id=str(result[5]) if result[5] else None,
        authorized_room_ids=authorized_room_ids,
        bot_account_id=str(result[7]) if result[7] else DEFAULT_BOT_ACCOUNT_ID,
        is_active=result[8]
    )


def _get_fallback_config(org_id: str) -> AdminConfig:
    """
    フォールバック用のデフォルト設定を返す

    Args:
        org_id: 組織ID

    Returns:
        AdminConfig: デフォルト値を使用した設定
    """
    return AdminConfig(
        organization_id=org_id,
        admin_account_id=DEFAULT_ADMIN_ACCOUNT_ID,
        admin_name="菊地雅克",
        admin_room_id=DEFAULT_ADMIN_ROOM_ID,
        admin_room_name="管理部",
        admin_dm_room_id=DEFAULT_ADMIN_DM_ROOM_ID,
        authorized_room_ids=frozenset([int(DEFAULT_ADMIN_ROOM_ID)]),
        bot_account_id=DEFAULT_BOT_ACCOUNT_ID,
        is_active=True
    )


# =============================================================================
# ユーティリティ関数
# =============================================================================

def clear_admin_config_cache(org_id: Optional[str] = None) -> None:
    """
    管理者設定キャッシュをクリア

    テスト時や設定変更後に使用。

    Args:
        org_id: 特定の組織のみクリアする場合に指定。
                Noneの場合は全キャッシュをクリア。
    """
    with _cache_lock:
        if org_id:
            _cache.pop(org_id, None)
            logger.info(f"AdminConfig cache cleared: org_id={org_id}")
        else:
            _cache.clear()
            logger.info("AdminConfig cache cleared: all entries")


def get_admin_config_by_room(room_id: str) -> Optional[AdminConfig]:
    """
    ルームIDから組織の管理者設定を取得

    指定されたroom_idが管理部ルームまたは認可ルームとして登録されている
    組織の設定を返す。

    Args:
        room_id: ChatWork room_id

    Returns:
        AdminConfig: 該当する組織が見つかった場合
        None: 該当なし

    Note:
        この関数は現在、全組織をスキャンするため、
        組織数が多くなった場合はパフォーマンス最適化が必要。
    """
    # 遅延インポート（循環参照回避）
    # v10.31.4: 相対インポートに変更（googleapiclient警告修正）
    from .db import get_db_pool

    room_id_str = str(room_id)
    room_id_int = int(room_id) if room_id_str.isdigit() else None

    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT organization_id
                    FROM organization_admin_configs
                    WHERE is_active = TRUE
                      AND (
                          admin_room_id = :room_id_str
                          OR :room_id_int = ANY(authorized_room_ids)
                      )
                    LIMIT 1
                """),
                {"room_id_str": room_id_str, "room_id_int": room_id_int}
            ).fetchone()

        if result:
            return get_admin_config(str(result[0]))

    except Exception as e:
        logger.warning(f"Failed to get AdminConfig by room: room_id={room_id}, error={e}")

    return None


def is_admin_account(account_id: str, org_id: Optional[str] = None) -> bool:
    """
    指定されたaccount_idが管理者かどうかを判定（ショートカット関数）

    Args:
        account_id: ChatWork account_id
        org_id: 組織ID（省略時はデフォルト組織）

    Returns:
        True: 管理者である
        False: 管理者でない
    """
    config = get_admin_config(org_id)
    return config.is_admin(account_id)


def get_admin_room_id(org_id: Optional[str] = None) -> str:
    """
    管理部ルームIDを取得（ショートカット関数）

    Args:
        org_id: 組織ID（省略時はデフォルト組織）

    Returns:
        管理部ルームID（文字列）
    """
    config = get_admin_config(org_id)
    return config.admin_room_id


def get_admin_account_id(org_id: Optional[str] = None) -> str:
    """
    管理者account_idを取得（ショートカット関数）

    Args:
        org_id: 組織ID（省略時はデフォルト組織）

    Returns:
        管理者account_id（文字列）
    """
    config = get_admin_config(org_id)
    return config.admin_account_id


# =============================================================================
# 後方互換性のためのエイリアス
# =============================================================================
# 既存コードからの移行を容易にするため

# 定数として参照していた箇所用
ADMIN_ACCOUNT_ID = DEFAULT_ADMIN_ACCOUNT_ID
ADMIN_ROOM_ID = DEFAULT_ADMIN_ROOM_ID
KAZU_CHATWORK_ACCOUNT_ID = DEFAULT_ADMIN_ACCOUNT_ID
KAZU_ACCOUNT_ID = int(DEFAULT_ADMIN_ACCOUNT_ID)
