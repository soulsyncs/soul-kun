# lib/brain/emergency_stop.py
"""
緊急停止チェッカー（Emergency Stop Checker） — Step 0-3: 安全の土台

ソウルくんのTool実行を即座に停止できる「非常ブレーキ」。
guardian_checkの最初で呼ばれ、停止中なら即ブロックする。

【設計原則】
- TTLキャッシュ（5秒）でDB負荷を軽減
- 停止/解除は常に可能（停止中でもdeactivateできる）
- Level 5+認証必須（API側で制御）
- 非同期I/O対応（asyncio.to_thread経由）

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import logging
import time
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


class EmergencyStopChecker:
    """
    緊急停止チェッカー

    DBのemergency_stopテーブルを参照し、停止中かどうかを判定する。
    TTLキャッシュ（5秒）で毎回のDB呼び出しを回避。
    """

    def __init__(self, pool, org_id: str, cache_ttl_seconds: int = 5):
        """
        Args:
            pool: データベース接続プール
            org_id: 組織ID
            cache_ttl_seconds: キャッシュのTTL（秒）
        """
        self.pool = pool
        self.org_id = org_id
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached_is_stopped: Optional[bool] = None
        self._cache_timestamp: float = 0.0

    def is_stopped(self) -> bool:
        """
        緊急停止中かどうかを判定する。

        TTLキャッシュを使い、cache_ttl_seconds以内なら
        キャッシュされた値を返す。

        Returns:
            True: 停止中（Tool実行をブロックすべき）
            False: 通常稼働中
        """
        now = time.time()
        if (
            self._cached_is_stopped is not None
            and (now - self._cache_timestamp) < self.cache_ttl_seconds
        ):
            return self._cached_is_stopped

        try:
            with self.pool.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                    {"org_id": self.org_id},
                )
                result = conn.execute(
                    text("""
                        SELECT is_active
                        FROM emergency_stop
                        WHERE organization_id = :org_id
                        LIMIT 1
                    """),
                    {"org_id": self.org_id},
                )
                row = result.fetchone()
                is_stopped = bool(row[0]) if row else False

            self._cached_is_stopped = is_stopped
            self._cache_timestamp = now
            return is_stopped

        except Exception as e:
            logger.error(
                "EmergencyStopChecker: DB check failed: %s", e, exc_info=True
            )
            # DB障害時は安全側（停止しない）に倒す
            # ※停止側に倒すとDB障害で全機能停止してしまうため
            return False

    def activate(self, user_id: str, reason: str = "") -> bool:
        """
        緊急停止を有効化する。

        Args:
            user_id: 操作者のユーザーID
            reason: 停止理由

        Returns:
            True: 成功
            False: 失敗
        """
        try:
            with self.pool.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                    {"org_id": self.org_id},
                )
                conn.execute(
                    text("""
                        INSERT INTO emergency_stop (organization_id, is_active, activated_by, reason, activated_at, updated_at)
                        VALUES (:org_id, TRUE, :user_id, :reason, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON CONFLICT (organization_id)
                        DO UPDATE SET
                            is_active = TRUE,
                            activated_by = :user_id,
                            reason = :reason,
                            activated_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                    """),
                    {"org_id": self.org_id, "user_id": user_id, "reason": reason},
                )
                conn.commit()

            # キャッシュを即座に更新
            self._cached_is_stopped = True
            self._cache_timestamp = time.time()

            logger.warning(
                "EMERGENCY STOP ACTIVATED: org=%s by=%s reason=%s",
                self.org_id, user_id, reason,
            )
            return True

        except Exception as e:
            logger.error(
                "EmergencyStopChecker: activate failed: %s", e, exc_info=True
            )
            return False

    def deactivate(self, user_id: str) -> bool:
        """
        緊急停止を解除する。

        Args:
            user_id: 操作者のユーザーID

        Returns:
            True: 成功
            False: 失敗
        """
        try:
            with self.pool.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                    {"org_id": self.org_id},
                )
                conn.execute(
                    text("""
                        UPDATE emergency_stop
                        SET is_active = FALSE,
                            deactivated_by = :user_id,
                            deactivated_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE organization_id = :org_id
                    """),
                    {"org_id": self.org_id, "user_id": user_id},
                )
                conn.commit()

            # キャッシュを即座に更新
            self._cached_is_stopped = False
            self._cache_timestamp = time.time()

            logger.warning(
                "EMERGENCY STOP DEACTIVATED: org=%s by=%s",
                self.org_id, user_id,
            )
            return True

        except Exception as e:
            logger.error(
                "EmergencyStopChecker: deactivate failed: %s", e, exc_info=True
            )
            return False

    def get_status(self) -> dict:
        """
        緊急停止の状態詳細を取得する。

        Returns:
            dict: is_active, activated_by, reason, activated_at等
        """
        try:
            with self.pool.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                    {"org_id": self.org_id},
                )
                result = conn.execute(
                    text("""
                        SELECT is_active, activated_by, deactivated_by,
                               reason, activated_at, deactivated_at
                        FROM emergency_stop
                        WHERE organization_id = :org_id
                        LIMIT 1
                    """),
                    {"org_id": self.org_id},
                )
                row = result.fetchone()

            if not row:
                return {"is_active": False}

            return {
                "is_active": bool(row[0]),
                "activated_by": row[1],
                "deactivated_by": row[2],
                "reason": row[3],
                "activated_at": row[4].isoformat() if row[4] else None,
                "deactivated_at": row[5].isoformat() if row[5] else None,
            }

        except Exception as e:
            logger.error(
                "EmergencyStopChecker: get_status failed: %s", e, exc_info=True
            )
            return {"is_active": False, "error": str(e)}

    def invalidate_cache(self):
        """キャッシュを無効化する（テスト用）"""
        self._cached_is_stopped = None
        self._cache_timestamp = 0.0
