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
from flask import Flask, request as flask_request, jsonify
import logging
import os
from datetime import datetime

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数
# Cloud Run用 Flask アプリケーション
app = Flask(__name__)

USE_PROACTIVE_MONITOR = os.environ.get("USE_PROACTIVE_MONITOR", "false").lower() == "true"
PROACTIVE_DRY_RUN = os.environ.get("PROACTIVE_DRY_RUN", "true").lower() == "true"
USE_BRAIN_FOR_PROACTIVE = os.environ.get("USE_BRAIN_FOR_PROACTIVE", "true").lower() == "true"


def get_sync_pool():
    """同期データベース接続プールを取得

    ProactiveMonitor / BrainMemoryAccess / SoulkunBrain は全て
    pool.connect() を sync で使用するため、sync Engine が必要。
    AsyncEngine を渡すと _get_active_users 等で TypeError になる。
    """
    try:
        from lib.db import get_db_pool
        return get_db_pool()
    except Exception as e:
        logger.error(f"Failed to get sync DB pool: {e}")
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

        # 組織IDを取得（環境変数 > デフォルト値）
        org_id = os.environ.get(
            "SOULKUN_ORG_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
        )

        # 記憶層を作成
        memory_access = BrainMemoryAccess(pool=pool, org_id=org_id)

        # 脳を作成（最小限の設定）
        brain = SoulkunBrain(
            pool=pool,
            org_id=org_id,
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

        org_id = os.environ.get("SOULKUN_ORG_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df")
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

        org_id = os.environ.get("SOULKUN_ORG_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df")
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


async def _try_cost_budget_alert(pool) -> str:
    """
    月次予算アラート（JST 9:00台に実行）

    今月のAIコストが予算の80%または100%を超えていたら、ChatWorkに通知する。
    重複防止: alert_80pct_sent_at / alert_100pct_sent_at が記録済みなら再送しない。
    翌月は新しいレコードが作られるため、自動的にリセットされる。
    """
    from datetime import timezone, timedelta
    jst_now = datetime.now(timezone(timedelta(hours=9)))

    if jst_now.hour != 9:
        return "skipped_not_9am"

    try:
        from sqlalchemy import text as sa_text

        org_id = os.environ.get("SOULKUN_ORG_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df")
        alert_room_id = os.environ.get("ALERT_ROOM_ID", "")
        if not alert_room_id:
            logger.warning("[CostAlert] ALERT_ROOM_ID not set, skipping")
            return "skipped_no_room"

        year_month = jst_now.strftime("%Y-%m")

        def _query():
            with pool.connect() as conn:
                result = conn.execute(
                    sa_text("""
                        SELECT total_cost_jpy, budget_jpy,
                               alert_80pct_sent_at, alert_100pct_sent_at
                        FROM ai_monthly_cost_summary
                        WHERE organization_id = :org_id
                          AND year_month = :year_month
                        LIMIT 1
                    """),
                    {"org_id": org_id, "year_month": year_month},
                )
                return result.fetchone()

        row = await asyncio.to_thread(_query)
        if row is None:
            return "skipped_no_data"

        total_cost = float(row[0] or 0)
        budget = float(row[1]) if row[1] is not None else None
        alert_80pct_sent_at = row[2]
        alert_100pct_sent_at = row[3]

        if budget is None or budget <= 0:
            return "skipped_no_budget"

        usage_pct = total_cost / budget * 100

        if usage_pct < 80:
            logger.info(
                "[CostAlert] Usage %.1f%% — below threshold, no alert", usage_pct
            )
            return "ok"

        # 送信が必要なアラートを判定（重複防止）
        send_80 = usage_pct >= 80 and alert_80pct_sent_at is None
        send_100 = usage_pct >= 100 and alert_100pct_sent_at is None

        if not send_80 and not send_100:
            logger.info(
                "[CostAlert] Usage %.1f%% — alerts already sent this month, skipping",
                usage_pct,
            )
            return "already_sent"

        time_str = jst_now.strftime("%Y-%m-%d %H:%M JST")
        sent_any = False

        # 80%アラート（予算警告）— 100%未満の場合のみ送信（100%超過時は下の重大アラートで対応）
        if send_80 and usage_pct < 100:
            message = (
                f"[info][title]⚠️ 予算警告 — 今月のAIコスト[/title]"
                f"使用率: {usage_pct:.1f}%\n"
                f"今月のコスト: ¥{total_cost:,.0f}\n"
                f"月間予算: ¥{budget:,.0f}\n"
                f"対象月: {year_month}\n"
                f"検知時刻: {time_str}[/info]"
            )
            await send_chatwork_message(alert_room_id, message)

            def _update_80():
                with pool.connect() as conn:
                    conn.execute(
                        sa_text("""
                            UPDATE ai_monthly_cost_summary
                               SET alert_80pct_sent_at = NOW()
                             WHERE organization_id = :org_id
                               AND year_month = :year_month
                        """),
                        {"org_id": org_id, "year_month": year_month},
                    )
                    conn.commit()

            await asyncio.to_thread(_update_80)
            logger.info(
                "[CostAlert] 80%% alert sent: %.1f%% (¥%,.0f / ¥%,.0f)",
                usage_pct, total_cost, budget,
            )
            sent_any = True

        # 100%アラート（予算超過）
        if send_100:
            message = (
                f"[info][title]🚨 予算超過 — 今月のAIコスト[/title]"
                f"使用率: {usage_pct:.1f}%\n"
                f"今月のコスト: ¥{total_cost:,.0f}\n"
                f"月間予算: ¥{budget:,.0f}\n"
                f"対象月: {year_month}\n"
                f"検知時刻: {time_str}[/info]"
            )
            await send_chatwork_message(alert_room_id, message)

            def _update_100():
                with pool.connect() as conn:
                    conn.execute(
                        sa_text("""
                            UPDATE ai_monthly_cost_summary
                               SET alert_80pct_sent_at = COALESCE(alert_80pct_sent_at, NOW()),
                                   alert_100pct_sent_at = NOW()
                             WHERE organization_id = :org_id
                               AND year_month = :year_month
                        """),
                        {"org_id": org_id, "year_month": year_month},
                    )
                    conn.commit()

            await asyncio.to_thread(_update_100)
            logger.info(
                "[CostAlert] 100%% alert sent: %.1f%% (¥%,.0f / ¥%,.0f)",
                usage_pct, total_cost, budget,
            )
            sent_any = True

        return "sent" if sent_any else "already_sent"

    except Exception as e:
        logger.warning("[CostAlert] Failed (non-critical): %s", type(e).__name__)
        return "error"


async def run_proactive_monitor():
    """能動的モニタリングを実行"""
    from lib.brain.proactive import create_proactive_monitor

    pool = get_sync_pool()
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

    # Phase 2-D: 月次予算アラート（JST 9:00台のみ）
    cost_alert_result = await _try_cost_budget_alert(pool)

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
        "cost_alert": cost_alert_result,
        "outcome_learning": outcome_batch_result,
        "users_checked": total_users,
        "triggers_found": total_triggers,
        "actions_taken": total_actions,
        "successful_actions": successful_actions,
    }

    logger.info(f"[ProactiveMonitor] Complete: {summary}")
    return summary


@app.route("/", methods=["POST", "GET"])
def proactive_monitor():
    """
    Cloud Run エントリーポイント

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
            "message": type(e).__name__,
        }, 500


# Cloud Schedulerからの呼び出し用（Pub/Sub push subscription経由）
@app.route("/scheduled", methods=["POST"])
def proactive_monitor_scheduled():
    """
    Cloud Scheduler からの Pub/Sub push subscription 用

    Cloud Run では Cloud Event ではなく HTTP POST で受け取る
    """
    logger.info("[ProactiveMonitor] Scheduled trigger received")

    # Feature Flag チェック
    if not USE_PROACTIVE_MONITOR:
        logger.info("[ProactiveMonitor] Feature flag is disabled, skipping")
        return jsonify({"status": "skipped"}), 200

    try:
        # 非同期処理を実行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(run_proactive_monitor())
        loop.close()

        logger.info(f"[ProactiveMonitor] Scheduled execution complete: {result}")
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"[ProactiveMonitor] Scheduled execution error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": type(e).__name__}), 500
