# lib/meetings/consent_manager.py
"""
Phase C MVP0: 録音同意管理

会議録音の事前同意を管理する。
ChatWorkメッセージの生成のみ行い、送信はBrainに委譲（Brain bypass防止）。
同意撤回時はカスケード削除で即時データ消去（Codex Fix #3）。

設計根拠:
- docs/07_phase_c_meetings.md: Consent Framework
- CLAUDE.md §1: 全出力はBrainを通る
- PDPA: 同意撤回権への対応

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import text

logger = logging.getLogger(__name__)


class ConsentManager:
    """会議録音の同意管理"""

    def __init__(self, pool, organization_id: str):
        if not organization_id or not organization_id.strip():
            raise ValueError("organization_id is required")
        self.pool = pool
        self.organization_id = organization_id

    def record_consent(
        self,
        meeting_id: str,
        user_id: str,
        consent_type: str,
        consent_method: str = "chatwork_message",
    ) -> bool:
        """
        同意を記録する。

        Args:
            meeting_id: 会議ID
            user_id: ChatWorkアカウントID
            consent_type: 'granted', 'withdrawn', 'opted_out'
            consent_method: 'chatwork_message', 'api', 'implicit'

        Returns:
            True: 記録成功
        """
        if consent_type not in ("granted", "withdrawn", "opted_out"):
            raise ValueError(f"Invalid consent_type: {consent_type}")

        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO meeting_consent_logs (
                        id, organization_id, meeting_id,
                        user_id, consent_type, consent_method,
                        created_at
                    ) VALUES (
                        :id, :org_id, :meeting_id,
                        :user_id, :consent_type, :method,
                        :now
                    )
                """),
                {
                    "id": str(uuid4()),
                    "org_id": self.organization_id,
                    "meeting_id": meeting_id,
                    "user_id": user_id,
                    "consent_type": consent_type,
                    "method": consent_method,
                    "now": datetime.now(timezone.utc),
                },
            )
            conn.commit()

        logger.info(
            "Consent recorded: meeting=%s, user=%s, type=%s",
            meeting_id, user_id, consent_type,
        )
        return True

    def check_all_consented(
        self, meeting_id: str, required_user_ids: List[str]
    ) -> Tuple[bool, List[str]]:
        """
        全員が同意済みか確認する。
        後から撤回した場合はgrantedとみなさない（最新状態で判定）。

        Returns:
            (all_consented, missing_user_ids)
        """
        if not required_user_ids:
            return (True, [])

        with self.pool.connect() as conn:
            # 各ユーザーの最新の同意状態のみを取得
            result = conn.execute(
                text("""
                    SELECT DISTINCT ON (user_id) user_id, consent_type
                    FROM meeting_consent_logs
                    WHERE organization_id = :org_id
                      AND meeting_id = :meeting_id
                    ORDER BY user_id, created_at DESC
                """),
                {"org_id": self.organization_id, "meeting_id": meeting_id},
            )
            latest = {row[0]: row[1] for row in result.fetchall()}

        # 最新状態がgrantedのユーザーのみ有効
        consented = {uid for uid, ctype in latest.items() if ctype == "granted"}
        missing = [uid for uid in required_user_ids if uid not in consented]
        return (len(missing) == 0, missing)

    def has_withdrawal(self, meeting_id: str) -> bool:
        """同意撤回がある場合はTrueを返す"""
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT 1
                    FROM meeting_consent_logs
                    WHERE organization_id = :org_id
                      AND meeting_id = :meeting_id
                      AND consent_type = 'withdrawn'
                    LIMIT 1
                """),
                {"org_id": self.organization_id, "meeting_id": meeting_id},
            )
            return result.fetchone() is not None

    def get_consent_status(self, meeting_id: str) -> Dict[str, Any]:
        """会議の同意状況を取得する"""
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT user_id, consent_type, created_at
                    FROM meeting_consent_logs
                    WHERE organization_id = :org_id
                      AND meeting_id = :meeting_id
                    ORDER BY created_at DESC
                """),
                {"org_id": self.organization_id, "meeting_id": meeting_id},
            )
            rows = result.mappings().fetchall()

        # 各ユーザーの最新の同意状態を集約
        latest_by_user: Dict[str, str] = {}
        for row in rows:
            uid = row["user_id"]
            if uid not in latest_by_user:
                latest_by_user[uid] = row["consent_type"]

        granted = [u for u, t in latest_by_user.items() if t == "granted"]
        withdrawn = [u for u, t in latest_by_user.items() if t == "withdrawn"]
        opted_out = [u for u, t in latest_by_user.items() if t == "opted_out"]

        return {
            "meeting_id": meeting_id,
            "granted": granted,
            "withdrawn": withdrawn,
            "opted_out": opted_out,
            "total_responses": len(latest_by_user),
        }

    @staticmethod
    def build_consent_request_message(
        meeting_title: Optional[str] = None,
        meeting_id: Optional[str] = None,
    ) -> str:
        """
        同意依頼メッセージを生成する（送信はBrainが行う）。

        Returns:
            ChatWork用メッセージテキスト
        """
        title = meeting_title or "会議"
        lines = [
            f"「{title}」の録音・文字起こしを開始します。",
            "",
            "参加者の同意が必要です。",
            "- 同意する場合: 「同意」と返信",
            "- 拒否する場合: 「拒否」と返信",
            "",
            "同意後も「同意撤回」でデータを即時削除できます。",
        ]
        return "\n".join(lines)
