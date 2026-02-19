# cost-report/main.py
"""
コスト日次/週次レポート Cloud Function

Cloud Scheduler から毎日 09:00 JST に呼び出し。
菊池さんDMにレポートを送信。
"""

import functions_framework
import logging
import os
from datetime import datetime, timedelta, timezone
from flask import jsonify

import sqlalchemy
from sqlalchemy import text

from lib.db import get_db_pool
from lib.secrets import get_secret_cached
from lib.chatwork import ChatworkClient

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 送信先
ALERT_ROOM_ID = os.environ.get("ALERT_ROOM_ID", "417892193")

# 組織ID（UUID形式 — ai_usage_logs.organization_id は UUID型）
DEFAULT_ORG_ID = os.environ.get(
    "ORGANIZATION_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
)


def _get_daily_report_data(conn, org_id: str) -> dict:
    """日次レポートデータを取得"""
    today = datetime.now(JST).strftime("%Y-%m-%d")

    # 日次コスト・リクエスト数・トークン
    row = conn.execute(
        text("""
            SELECT
                COALESCE(SUM(cost_jpy), 0) AS total_cost,
                COUNT(*) AS total_requests,
                COALESCE(SUM(input_tokens), 0) AS total_input_tokens,
                COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
                COUNT(*) FILTER (WHERE success = FALSE) AS error_count
            FROM ai_usage_logs
            WHERE organization_id = :org_id::uuid
              AND created_at >= :today::date
              AND created_at < :today::date + INTERVAL '1 day'
        """),
        {"org_id": org_id, "today": today},
    ).fetchone()

    total_cost = float(row[0]) if row else 0
    total_requests = int(row[1]) if row else 0
    total_input_tokens = int(row[2]) if row else 0
    total_output_tokens = int(row[3]) if row else 0
    error_count = int(row[4]) if row else 0

    # モデル別内訳
    model_rows = conn.execute(
        text("""
            SELECT
                model_id,
                COUNT(*) AS requests,
                COALESCE(SUM(cost_jpy), 0) AS cost
            FROM ai_usage_logs
            WHERE organization_id = :org_id::uuid
              AND created_at >= :today::date
              AND created_at < :today::date + INTERVAL '1 day'
            GROUP BY model_id
            ORDER BY cost DESC
            LIMIT 5
        """),
        {"org_id": org_id, "today": today},
    ).fetchall()

    models = []
    for mr in model_rows:
        models.append({
            "name": mr[0] or "unknown",
            "requests": int(mr[1]),
            "cost": float(mr[2]),
        })

    error_rate = (error_count / total_requests * 100) if total_requests > 0 else 0

    return {
        "date": today,
        "total_cost": total_cost,
        "total_requests": total_requests,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "error_count": error_count,
        "error_rate": error_rate,
        "models": models,
    }


def _get_monthly_summary(conn, org_id: str) -> dict:
    """当月サマリーを取得"""
    year_month = datetime.now(JST).strftime("%Y-%m")

    row = conn.execute(
        text("""
            SELECT
                total_cost_jpy,
                total_requests,
                total_input_tokens,
                total_output_tokens,
                budget_jpy,
                budget_remaining_jpy
            FROM ai_monthly_cost_summary
            WHERE organization_id = :org_id::uuid
              AND year_month = :year_month
        """),
        {"org_id": org_id, "year_month": year_month},
    ).fetchone()

    if row:
        return {
            "year_month": year_month,
            "total_cost": float(row[0] or 0),
            "total_requests": int(row[1] or 0),
            "budget": float(row[4] or 0),
            "budget_remaining": float(row[5] or 0),
        }
    return {
        "year_month": year_month,
        "total_cost": 0,
        "total_requests": 0,
        "budget": 0,
        "budget_remaining": 0,
    }


def _format_daily_report(data: dict, monthly: dict) -> str:
    """日次レポートをChatWork Info記法でフォーマット"""
    lines = []
    lines.append(f"[info][title]AI コストレポート ({data['date']})[/title]")
    lines.append(f"本日のコスト: {data['total_cost']:,.0f}円")
    lines.append(f"API呼出数: {data['total_requests']:,}回")
    lines.append(f"トークン: 入力 {data['total_input_tokens']:,} / 出力 {data['total_output_tokens']:,}")
    lines.append(f"エラー率: {data['error_rate']:.1f}% ({data['error_count']}件)")
    lines.append("")

    if data["models"]:
        lines.append("--- モデル別内訳 ---")
        for m in data["models"]:
            lines.append(f"  {m['name']}: {m['cost']:,.0f}円 ({m['requests']}回)")
        lines.append("")

    lines.append("--- 当月累計 ---")
    lines.append(f"累計コスト: {monthly['total_cost']:,.0f}円")
    lines.append(f"累計リクエスト: {monthly['total_requests']:,}回")
    if monthly["budget"] > 0:
        lines.append(f"予算残: {monthly['budget_remaining']:,.0f}円 / {monthly['budget']:,.0f}円")

    lines.append("[/info]")
    return "\n".join(lines)


@functions_framework.http
def cost_report(request):
    """
    Cloud Function: コストレポート送信
    Cloud Scheduler から毎日 09:00 JST に呼び出し
    """
    logger.info("Cost report function triggered")

    try:
        pool = get_db_pool()
        org_id = DEFAULT_ORG_ID

        with pool.connect() as conn:
            # RLSセッション変数を設定
            conn.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                {"org_id": org_id},
            )
            daily = _get_daily_report_data(conn, org_id)
            monthly = _get_monthly_summary(conn, org_id)

        message = _format_daily_report(daily, monthly)

        # ChatWork DM送信
        client = ChatworkClient()
        client.send_message(
            room_id=int(ALERT_ROOM_ID),
            message=message,
        )
        logger.info("Cost report sent to room %s", ALERT_ROOM_ID)

        return jsonify({"status": "ok", "daily": daily, "monthly": monthly})

    except Exception as e:
        logger.error("Cost report failed: %s", type(e).__name__)
        return jsonify({"status": "error", "error": type(e).__name__}), 500
