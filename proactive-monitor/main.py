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

【CLAUDE.md鉄則1b準拠】
v1.1.0: 脳経由でメッセージ生成するように改修
- ProactiveMonitorは脳にメッセージ生成を依頼
- 脳が記憶を参照し、状況を理解し、適切なメッセージを生成

Author: Claude Opus 4.5
Created: 2026-01-27
Updated: 2026-01-29 (脳統合)
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
USE_BRAIN_FOR_PROACTIVE = os.environ.get("USE_BRAIN_FOR_PROACTIVE", "true").lower() == "true"


async def get_async_pool():
    """非同期データベース接続プールを取得"""
    try:
        from lib.db import get_async_db_pool
        return await get_async_db_pool()
    except Exception as e:
        logger.error(f"Failed to get async DB pool: {e}")
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


async def create_brain_for_proactive(pool):
    """
    Proactive Monitor用の脳を作成

    CLAUDE.md鉄則1b準拠: 能動的出力も脳が生成
    脳はメッセージ生成に必要な最小限の機能を持つ
    """
    if not USE_BRAIN_FOR_PROACTIVE:
        logger.warning(
            "[ProactiveMonitor] USE_BRAIN_FOR_PROACTIVE is disabled. "
            "Using fallback templates (CLAUDE.md violation)."
        )
        return None

    try:
        from lib.brain.core import SoulkunBrain
        from lib.brain.memory_access import BrainMemoryAccess

        # 記憶層を作成
        memory_access = BrainMemoryAccess(pool=pool)

        # 脳を作成（最小限の設定）
        brain = SoulkunBrain(
            pool=pool,
            org_id=None,  # 全組織対象
            handlers={},  # Proactiveではハンドラー不要
            capabilities={},  # Proactiveではcapabilities不要
            get_ai_response_func=None,  # メッセージ生成にはLLM不要（テンプレートベース）
            firestore_db=None,
        )

        # 記憶層を設定
        brain.memory_access = memory_access

        logger.info("[ProactiveMonitor] Brain created for proactive message generation")
        return brain

    except Exception as e:
        logger.warning(
            f"[ProactiveMonitor] Failed to create brain: {e}. "
            "Using fallback templates."
        )
        return None


async def _try_generate_daily_log(pool) -> str:
    """
    日次レポートを生成（JST 9:00台の最初の1回のみ実行）

    Phase 2-B: 毎朝、前日の活動サマリーを生成してログに記録する。
    CLAUDE.md鉄則1b: 脳の活動記録の透明性向上。

    Note: DailyLogGeneratorは同期poolを使用するため、
    get_db_pool()で同期版コネクションプールを取得する。
    """
    from datetime import timezone, timedelta
    jst_now = datetime.now(timezone(timedelta(hours=9)))

    if jst_now.hour != 9:
        return "skipped_not_9am"

    try:
        from lib.brain.daily_log import DailyLogGenerator
        from lib.db import get_db_pool

        org_id = os.environ.get("SOULKUN_ORG_ID", "soulsyncs")
        sync_pool = get_db_pool()  # 同期プール（DailyLogGeneratorは同期DB操作）
        generator = DailyLogGenerator(pool=sync_pool, org_id=org_id)
        activity = await asyncio.to_thread(generator.generate)  # 同期処理をスレッドで実行
        logger.info(
            f"[DailyLog] Generated: {activity.target_date} "
            f"conversations={activity.total_conversations} "
            f"users={activity.unique_users}"
        )
        return "generated"
    except Exception as e:
        logger.warning(f"[DailyLog] Generation failed (non-critical): {e}")
        return "error"


async def _try_outcome_learning_batch() -> dict:
    """
    Phase 2F: 結果からの学習 — バッチ処理

    未検出アウトカムの検知 + パターン抽出 + 自動昇格を行う。
    毎回の定期実行で呼び出される。エラー時はログのみで続行。

    Note: DailyLogGeneratorと同様、同期DBプールを使用する。
    """
    try:
        from lib.brain.outcome_learning import create_outcome_learning
        from lib.db import get_db_pool

        org_id = os.environ.get("SOULKUN_ORG_ID", "soulsyncs")
        outcome_learning = create_outcome_learning(org_id)
        sync_pool = get_db_pool()

        def _sync_batch():
            with sync_pool.connect() as conn:
                # 1. 未検出アウトカムの処理
                processed = outcome_learning.process_pending_outcomes(conn)

                # 2. パターン抽出（30日分）
                patterns = outcome_learning.extract_patterns(conn, days=30, save=True)

                # 3. 昇格可能パターンの自動昇格
                promotable = outcome_learning.find_promotable_patterns(conn)
                promoted_count = 0
                for p in promotable:
                    learning_id = outcome_learning.promote_pattern_to_learning(conn, p.id)
                    if learning_id:
                        promoted_count += 1

                return {
                    "processed_outcomes": processed,
                    "patterns_extracted": len(patterns),
                    "patterns_promoted": promoted_count,
                }

        result = await asyncio.to_thread(_sync_batch)
        logger.info("[OutcomeLearning] Batch complete: %s", result)
        return result
    except Exception as e:
        logger.warning("[OutcomeLearning] Batch failed: %s", type(e).__name__)
        return {"error": type(e).__name__}


async def run_proactive_monitor():
    """能動的モニタリングを実行"""
    from lib.brain.proactive import create_proactive_monitor

    pool = await get_async_pool()
    if not pool:
        logger.error("[ProactiveMonitor] No database pool available")
        return {"status": "error", "message": "No database pool"}

    # CLAUDE.md鉄則1b: 脳を作成してメッセージ生成に使用
    brain = await create_brain_for_proactive(pool)

    # モニター作成（脳経由でメッセージ生成）
    monitor = create_proactive_monitor(
        pool=pool,
        send_message_func=send_chatwork_message,
        dry_run=PROACTIVE_DRY_RUN,
        brain=brain,  # CLAUDE.md鉄則1b準拠
    )

    # 実行
    logger.info(f"[ProactiveMonitor] Starting check (dry_run={PROACTIVE_DRY_RUN})")
    results = await monitor.check_and_act()

    # Phase 2-B: 日次レポート生成（JST 9:00台のみ）
    daily_log_result = await _try_generate_daily_log(pool)

    # Phase 2F: 結果からの学習 — バッチ処理
    outcome_batch_result = await _try_outcome_learning_batch()

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
        "brain_used": brain is not None,  # CLAUDE.md鉄則1b準拠状況
        "daily_log": daily_log_result,
        "outcome_learning": outcome_batch_result,
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
