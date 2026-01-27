# proactive-monitor/main.py
"""
Phase 2K: 能動的モニタリング Cloud Function

ソウルくんが自分から声をかける機能。
Cloud Schedulerから定期実行される。

トリガー条件:
1. 目標放置: 7日間更新なし
2. タスク山積み: 5件以上遅延
3. 感情変化: ネガティブ継続3日
4. 質問放置: 24時間未回答
5. 目標達成: お祝いメッセージ
6. 長期不在: 14日以上

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import asyncio
import functions_framework
import logging
import os
from datetime import datetime

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数
USE_PROACTIVE_MONITOR = os.environ.get("USE_PROACTIVE_MONITOR", "false").lower() == "true"
PROACTIVE_DRY_RUN = os.environ.get("PROACTIVE_DRY_RUN", "true").lower() == "true"


def get_db_pool():
    """データベース接続プールを取得"""
    try:
        from lib.db import get_async_pool
        return get_async_pool()
    except Exception as e:
        logger.error(f"Failed to get DB pool: {e}")
        return None


async def send_chatwork_message(room_id: str, message: str) -> bool:
    """ChatWorkにメッセージを送信"""
    try:
        from lib.chatwork import send_message
        result = send_message(room_id, message)
        return result is not None
    except Exception as e:
        logger.error(f"Failed to send ChatWork message: {e}")
        return False


async def run_proactive_monitor():
    """能動的モニタリングを実行"""
    from lib.brain.proactive import create_proactive_monitor

    pool = get_db_pool()
    if not pool:
        logger.error("[ProactiveMonitor] No database pool available")
        return {"status": "error", "message": "No database pool"}

    # モニター作成
    monitor = create_proactive_monitor(
        pool=pool,
        send_message_func=send_chatwork_message,
        dry_run=PROACTIVE_DRY_RUN,
    )

    # 実行
    logger.info(f"[ProactiveMonitor] Starting check (dry_run={PROACTIVE_DRY_RUN})")
    results = await monitor.check_and_act()

    # 統計
    total_users = len(results)
    total_triggers = sum(len(r.triggers_found) for r in results)
    total_actions = sum(len(r.actions_taken) for r in results)
    successful_actions = sum(
        len([a for a in r.actions_taken if a.success])
        for r in results
    )

    summary = {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "dry_run": PROACTIVE_DRY_RUN,
        "users_checked": total_users,
        "triggers_found": total_triggers,
        "actions_taken": total_actions,
        "successful_actions": successful_actions,
    }

    logger.info(f"[ProactiveMonitor] Complete: {summary}")
    return summary


@functions_framework.http
def proactive_monitor(request):
    """
    Cloud Function エントリーポイント

    HTTP トリガー（Cloud Schedulerから呼び出し）
    """
    logger.info("[ProactiveMonitor] Function triggered")

    # Feature Flag チェック
    if not USE_PROACTIVE_MONITOR:
        logger.info("[ProactiveMonitor] Feature flag is disabled, skipping")
        return {
            "status": "skipped",
            "reason": "USE_PROACTIVE_MONITOR is disabled",
        }, 200

    try:
        # 非同期処理を実行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(run_proactive_monitor())
        loop.close()

        return result, 200

    except Exception as e:
        logger.error(f"[ProactiveMonitor] Error: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
        }, 500


# Cloud Schedulerからの呼び出し用
@functions_framework.cloud_event
def proactive_monitor_scheduled(cloud_event):
    """
    Cloud Scheduler からの Pub/Sub トリガー用

    Pub/Sub メッセージを受け取って実行
    """
    import base64

    logger.info(f"[ProactiveMonitor] Scheduled trigger received: {cloud_event}")

    # Feature Flag チェック
    if not USE_PROACTIVE_MONITOR:
        logger.info("[ProactiveMonitor] Feature flag is disabled, skipping")
        return

    try:
        # 非同期処理を実行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(run_proactive_monitor())
        loop.close()

        logger.info(f"[ProactiveMonitor] Scheduled execution complete: {result}")

    except Exception as e:
        logger.error(f"[ProactiveMonitor] Scheduled execution error: {e}", exc_info=True)
        raise
