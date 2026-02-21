"""
renk_os_client.py - Re:nk OS データ取得クライアント

ソウルくんから Re:nk OS（スタッフ管理システム）のデータを
読み取り専用で取得するクライアント。

主な用途:
- 現在の案件一覧・人員状況を取得する
- 採用充足率を確認して採否判断に使う
- 不足ポジションを特定して採用優先度を判断する

使い方:
    from lib.renk_os_client import RenkOsClient

    client = RenkOsClient()
    summary = client.get_staffing_summary()
    if client.is_hiring_needed():
        projects = client.get_understaffed_projects()
"""

import logging
from typing import Optional

import httpx

from lib.secrets import get_secret_cached

logger = logging.getLogger(__name__)

# Re:nk OS Edge Function のエンドポイント
RENK_OS_API_URL = (
    "https://bfzsdtlyxqxllawnxnlh.supabase.co/functions/v1/renk-os-data-api"
)

# APIキーの Secret Manager キー名
RENK_OS_API_KEY_SECRET = "RENK_OS_API_KEY"

# タイムアウト秒数
REQUEST_TIMEOUT_SECONDS = 10


class RenkOsClient:
    """
    Re:nk OS のデータを取得するクライアント。

    APIキーは Google Cloud Secret Manager から自動取得する。
    エラー時はログを出して None を返す（呼び出し元を止めない設計）。
    """

    def _get_headers(self) -> dict:
        """APIキーを含むリクエストヘッダーを返す"""
        api_key = get_secret_cached(RENK_OS_API_KEY_SECRET)
        if not api_key:
            raise ValueError(
                f"Secret Manager に {RENK_OS_API_KEY_SECRET} が見つかりません"
            )
        return {
            "x-api-key": api_key,
            "Content-Type": "application/json",
        }

    def get_staffing_summary(self) -> Optional[dict]:
        """
        Re:nk OS から現在の人員状況サマリーを取得する。

        戻り値の例:
        {
            "summary": {
                "total_active_projects": 5,
                "understaffed_projects": 2,
                "available_staff_count": 3,
                "overall_fill_rate": 80
            },
            "projects": [
                {
                    "project_name": "〇〇株式会社 事務",
                    "client_name": "〇〇株式会社",
                    "required_count": 3,
                    "assigned_count": 2,
                    "is_understaffed": True
                }
            ]
        }

        取得失敗時は None を返す。
        """
        try:
            headers = self._get_headers()
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = client.post(RENK_OS_API_URL, headers=headers)
                response.raise_for_status()
                data = response.json()
                logger.info(
                    "Re:nk OS データ取得成功: 案件数=%s",
                    data.get("summary", {}).get("total_active_projects", "?"),
                )
                return data
        except httpx.HTTPStatusError as e:
            logger.error(
                "Re:nk OS API エラー: status=%s",
                e.response.status_code,
            )
            return None
        except httpx.TimeoutException:
            logger.error("Re:nk OS API タイムアウト（%s秒）", REQUEST_TIMEOUT_SECONDS)
            return None
        except Exception as e:
            logger.error("Re:nk OS データ取得中に予期しないエラー: %s", e)
            return None

    def get_understaffed_projects(self) -> list[dict]:
        """
        人員が不足している案件の一覧を返す。

        戻り値の例:
        [
            {
                "project_name": "〇〇株式会社 事務",
                "client_name": "〇〇株式会社",
                "required_count": 3,
                "assigned_count": 2,
                "is_understaffed": True
            }
        ]

        取得失敗時は空リストを返す。
        """
        data = self.get_staffing_summary()
        if not data:
            return []
        projects = data.get("projects", [])
        return [p for p in projects if p.get("is_understaffed", False)]

    def is_hiring_needed(self) -> bool:
        """
        現在採用が必要かどうかを返す（True=採用が必要）。

        人員不足の案件が1件以上あれば True を返す。
        データ取得失敗時は安全側に倒して True を返す。
        """
        data = self.get_staffing_summary()
        if not data:
            # 取得できない場合は「採用必要」として扱う（見逃し防止）
            logger.warning("Re:nk OS データ未取得のため is_hiring_needed=True を返します")
            return True
        understaffed = data.get("summary", {}).get("understaffed_projects", 0)
        return understaffed > 0

    def get_fill_rate(self) -> Optional[float]:
        """
        全体の採用充足率（%）を返す。

        例: 80.0 → 全案件の80%が充足済み
        取得失敗時は None を返す。
        """
        data = self.get_staffing_summary()
        if not data:
            return None
        return data.get("summary", {}).get("overall_fill_rate")
