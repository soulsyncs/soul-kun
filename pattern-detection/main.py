"""
Phase 2 A1/A2/A3/A4: パターン検知・属人化検出・ボトルネック検出・感情変化検出 Cloud Function

このCloud Functionは、ソウルくんへの質問とタスクを分析し、
頻出パターン、属人化リスク、ボトルネック、感情変化を検出してインサイトを生成します。

実行タイミング:
- A1 パターン検知: 毎時実行（バッチ処理）
- A2 属人化検出: 毎日 08:00 JST
- A3 ボトルネック検出: 毎日 08:00 JST
- A4 感情変化検出: 毎日 10:00 JST

エンドポイント:
- POST /pattern-detection
  - hours_back: 分析対象期間（デフォルト: 1時間）
  - dry_run: true の場合、DBに書き込まない
- POST /personalization-detection
  - dry_run: true の場合、DBに書き込まない
- POST /bottleneck-detection
  - dry_run: true の場合、DBに書き込まない
- POST /emotion-detection
  - dry_run: true の場合、DBに書き込まない
- POST /weekly-report
  - room_id: 送信先ChatWorkルームID

設計書:
- docs/06_phase2_a1_pattern_detection.md
- docs/07_phase2_a2_personalization_detection.md
- docs/08_phase2_a3_bottleneck_detection.md
- docs/09_phase2_a4_emotion_detection.md

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-23
Updated: 2026-01-24 (A2/A3/A4追加)
Updated: 2026-01-26 (Phase D: 接続設定集約)
Version: 1.4
"""

import functions_framework
from flask import jsonify, Request
import json
import traceback
from datetime import datetime, timedelta, timezone
from uuid import UUID
import os

import pg8000
import sqlalchemy
from sqlalchemy import text

# =====================================================
# Phase D: 接続設定集約（v10.31.1）
# =====================================================
# ハードコードされていたDB接続設定をlib/に集約
# - INSTANCE_CONNECTION_NAME -> lib/config.py
# - DB_NAME, DB_USER -> lib/config.py
# - get_db_pool() -> lib/db.py
# - get_secret() -> lib/secrets.py
# =====================================================
from lib.db import get_db_pool as _lib_get_db_pool
from lib.secrets import get_secret_cached as get_secret
from lib.config import get_settings


def get_db_pool():
    """Cloud SQL接続プールを取得"""
    return _lib_get_db_pool()

# =====================================================
# 設定（フォールバック時以外は lib/config.py を使用）
# =====================================================

# ソウルシンクスの組織ID
DEFAULT_ORG_ID = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"

# ソウルくんのaccount_id
BOT_ACCOUNT_ID = "10909425"

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

# テストモード設定
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("true", "1", "yes")
TEST_MODE = os.environ.get("TEST_MODE", "").lower() in ("true", "1", "yes")


# =====================================================
# メッセージ取得
# =====================================================

def get_recent_questions(conn, org_id: str, hours_back: int = 1) -> list[dict]:
    """
    直近のソウルくん宛メッセージ（質問）を取得

    条件:
    - 指定期間内のメッセージ
    - ソウルくんへのメンション含む
    - ボット自身のメッセージは除外
    - パターン分析済みでないもの

    Args:
        conn: データベース接続
        org_id: 組織ID
        hours_back: 取得期間（時間）

    Returns:
        質問のリスト
    """
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    # room_messages テーブルから質問を取得
    # ソウルくんへのメンションを含むメッセージを対象とする
    result = conn.execute(text("""
        SELECT
            rm.message_id,
            rm.room_id,
            rm.account_id,
            rm.account_name,
            rm.body,
            rm.send_time,
            u.id as user_id,
            ud.department_id
        FROM room_messages rm
        LEFT JOIN users u ON u.chatwork_account_id = rm.account_id::text
            AND u.organization_id = :org_id
        LEFT JOIN user_departments ud ON ud.user_id = u.id
            AND ud.is_primary = true
        WHERE rm.send_time >= :cutoff_time
          AND rm.account_id != :bot_account_id
          AND (
              rm.body LIKE '%[To:10909425]%'
              OR rm.body LIKE '%ソウルくん%'
              OR rm.body LIKE '%そうるくん%'
          )
          AND NOT EXISTS (
              SELECT 1 FROM question_patterns qp
              WHERE qp.organization_id = :org_id
                AND qp.sample_questions @> ARRAY[rm.body]
          )
        ORDER BY rm.send_time ASC
        LIMIT 100
    """), {
        "org_id": org_id,
        "cutoff_time": cutoff_time,
        "bot_account_id": BOT_ACCOUNT_ID,
    })

    questions = []
    for row in result:
        questions.append({
            "message_id": row[0],
            "room_id": row[1],
            "account_id": str(row[2]),
            "account_name": row[3],
            "body": row[4],
            "send_time": row[5],
            "user_id": str(row[6]) if row[6] else None,
            "department_id": str(row[7]) if row[7] else None,
        })

    return questions


# =====================================================
# パターン検知処理
# =====================================================

def analyze_questions(conn, org_id: str, questions: list[dict], dry_run: bool = False) -> dict:
    """
    質問リストをパターン分析

    Args:
        conn: データベース接続
        org_id: 組織ID
        questions: 質問リスト
        dry_run: True の場合、DBに書き込まない

    Returns:
        分析結果のサマリー
    """
    from lib.detection.pattern_detector import PatternDetector
    from lib.detection.constants import DetectionParameters

    org_uuid = UUID(org_id)

    # 結果サマリー
    results = {
        "total_questions": len(questions),
        "analyzed": 0,
        "patterns_updated": 0,
        "patterns_created": 0,
        "insights_created": 0,
        "errors": [],
    }

    if dry_run:
        print(f"🧪 DRY RUN モード: DBへの書き込みはスキップされます")

    # 検出器を初期化
    detector = PatternDetector(
        conn=conn,
        org_id=org_uuid,
        pattern_threshold=DetectionParameters.PATTERN_THRESHOLD,
        pattern_window_days=DetectionParameters.PATTERN_WINDOW_DAYS,
    )

    for q in questions:
        try:
            # ユーザーIDがない場合はスキップ
            if not q.get("user_id"):
                print(f"⚠️ ユーザーID不明のためスキップ: account_id={q['account_id']}")
                results["errors"].append({
                    "message_id": q["message_id"],
                    "error": "User ID not found",
                })
                continue

            user_id = UUID(q["user_id"])
            department_id = UUID(q["department_id"]) if q.get("department_id") else None

            # 質問テキストを抽出（メンション部分を除去）
            question_text = extract_question_text(q["body"])

            if not question_text or len(question_text) < 5:
                print(f"⚠️ 質問テキストが短すぎるためスキップ: {question_text[:50] if question_text else '(empty)'}")
                continue

            print(f"📝 分析中: {question_text[:50]}...")

            if not dry_run:
                # パターン検出を実行（同期的に呼び出し）
                import asyncio
                result = asyncio.run(
                    detector.detect(
                        question=question_text,
                        user_id=user_id,
                        department_id=department_id,
                    )
                )

                results["analyzed"] += 1

                if result.success:
                    if result.insight_created:
                        results["insights_created"] += 1
                        print(f"  ✅ インサイト作成: {result.insight_id}")
                    else:
                        results["patterns_updated"] += 1
                        print(f"  ✅ パターン更新: detected_count={result.detected_count}")
                else:
                    results["errors"].append({
                        "message_id": q["message_id"],
                        "error": result.error_message,
                    })
                    print(f"  ❌ エラー: {result.error_message}")
            else:
                results["analyzed"] += 1
                print(f"  🧪 DRY RUN: 分析スキップ")

        except Exception as e:
            error_msg = f"分析エラー: {str(e)}"
            print(f"  ❌ {error_msg}")
            results["errors"].append({
                "message_id": q.get("message_id"),
                "error": error_msg,
                "traceback": traceback.format_exc(),
            })

    return results


def extract_question_text(body: str) -> str:
    """
    メッセージ本文から質問テキストを抽出

    - メンション部分を除去
    - 挨拶を除去
    - 前後の空白をトリム

    Args:
        body: メッセージ本文

    Returns:
        質問テキスト
    """
    import re

    # メンション部分を除去
    text = re.sub(r'\[To:\d+\][^\]]*\]?', '', body)
    text = re.sub(r'\[rp aid=\d+ to=\d+-\d+\]', '', text)
    text = re.sub(r'\[引用 aid=\d+.*?\].*?\[/引用\]', '', text, flags=re.DOTALL)

    # 挨拶パターンを除去
    greetings = [
        r'^(お疲れ様です|お疲れさまです|おつかれさまです)[。、！]?\s*',
        r'^(お世話になります|お世話になっております)[。、]?\s*',
        r'^(こんにちは|こんばんは|おはようございます)[。、！]?\s*',
        r'(よろしくお願いします|よろしくお願いいたします)[。！]*\s*$',
    ]

    for pattern in greetings:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # 余分な空白を正規化
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# =====================================================
# Cloud Function エントリポイント
# =====================================================

@functions_framework.http
def pattern_detection(request: Request):
    """
    パターン検知のメインエントリポイント（ルーター機能付き）

    パスベースルーティング:
    - /emotion-detection → emotion_detection()
    - /weekly-report → weekly_report()
    - その他 → A1パターン検知

    リクエストパラメータ:
    - hours_back: 分析対象期間（デフォルト: 1時間）
    - dry_run: true の場合、DBに書き込まない
    - org_id: 組織ID（デフォルト: ソウルシンクス）

    レスポンス:
    - success: 成功/失敗
    - results: 分析結果のサマリー
    - timestamp: 実行日時
    """
    # パスベースルーティング
    path = request.path or ""
    print(f"📍 リクエストパス: {path}")

    if path.endswith("/emotion-detection"):
        print("🔀 ルーティング: emotion_detection")
        return emotion_detection(request)
    elif path.endswith("/weekly-report"):
        print("🔀 ルーティング: weekly_report")
        return weekly_report(request)
    elif path.endswith("/daily-insight"):
        print("🔀 ルーティング: daily_insight_notification")
        return daily_insight_notification(request)

    # デフォルト: A1パターン検知
    start_time = datetime.now(timezone.utc)
    print(f"🚀 パターン検知開始: {start_time.isoformat()}")

    try:
        # リクエストパラメータを取得
        if request.is_json:
            data = request.get_json()
        else:
            data = {}

        hours_back = int(data.get("hours_back", 1))
        dry_run = data.get("dry_run", DRY_RUN)
        org_id = data.get("org_id", DEFAULT_ORG_ID)

        if isinstance(dry_run, str):
            dry_run = dry_run.lower() in ("true", "1", "yes")

        print(f"📋 パラメータ: hours_back={hours_back}, dry_run={dry_run}, org_id={org_id}")

        # データベース接続
        pool = get_db_pool()

        with pool.connect() as conn:
            try:
                # 直近の質問を取得
                questions = get_recent_questions(conn, org_id, hours_back)
                print(f"📥 取得した質問数: {len(questions)}")

                if not questions:
                    return jsonify({
                        "success": True,
                        "message": "分析対象の質問がありませんでした",
                        "results": {
                            "total_questions": 0,
                            "analyzed": 0,
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }), 200

                # パターン分析を実行
                results = analyze_questions(conn, org_id, questions, dry_run)

                # トランザクションをコミット（dry_runでない場合）
                if not dry_run:
                    conn.commit()
                    print(f"✅ トランザクションコミット完了")
            except Exception:
                conn.rollback()
                raise

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        print(f"🏁 パターン検知完了: {elapsed:.2f}秒")

        return jsonify({
            "success": True,
            "message": f"{results['analyzed']}件の質問を分析しました",
            "results": results,
            "elapsed_seconds": elapsed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except Exception as e:
        error_msg = f"パターン検知エラー: {str(e)}"
        print(f"❌ {error_msg}")
        print(traceback.format_exc())

        return jsonify({
            "success": False,
            "error": error_msg,
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 500


@functions_framework.http
def weekly_report(request: Request):
    """
    週次レポート生成・送信のエントリポイント

    毎週月曜日 9:00 JST に Cloud Scheduler から呼び出される

    リクエストパラメータ:
    - dry_run: true の場合、送信しない
    - org_id: 組織ID（デフォルト: ソウルシンクス）
    - room_id: 送信先ChatWorkルームID（デフォルト: 管理部）

    レスポンス:
    - success: 成功/失敗
    - report_id: 作成されたレポートID
    - sent: 送信完了かどうか
    """
    from lib.insights.weekly_report_service import WeeklyReportService

    start_time = datetime.now(timezone.utc)
    print(f"🚀 週次レポート生成開始: {start_time.isoformat()}")

    try:
        # リクエストパラメータを取得
        if request.is_json:
            data = request.get_json()
        else:
            data = {}

        dry_run = data.get("dry_run", DRY_RUN)
        org_id = data.get("org_id", DEFAULT_ORG_ID)
        room_id = int(data.get("room_id", 417892193))  # デフォルト: 菊地さんDM

        if isinstance(dry_run, str):
            dry_run = dry_run.lower() in ("true", "1", "yes")

        print(f"📋 パラメータ: dry_run={dry_run}, org_id={org_id}, room_id={room_id}")

        # データベース接続
        pool = get_db_pool()

        with pool.connect() as conn:
            try:
                org_uuid = UUID(org_id)

                # 週次レポートサービスを初期化
                service = WeeklyReportService(conn, org_uuid)

                # レポートを生成（asyncio対応）
                import asyncio
                report_id = asyncio.run(service.generate_weekly_report())

                if not report_id:
                    return jsonify({
                        "success": True,
                        "message": "今週のインサイトがないため、レポートは生成されませんでした",
                        "report_id": None,
                        "sent": False,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }), 200

                print(f"📄 レポート生成完了: {report_id}")

                # レポートを送信
                if not dry_run:
                    import requests as http_requests

                    # レポートを取得してChatWork形式にフォーマット
                    report_record = asyncio.run(service.get_report(report_id))
                    if report_record:
                        chatwork_message = service.format_for_chatwork(report_record)

                        # ChatWorkに送信
                        chatwork_token = get_secret("SOULKUN_CHATWORK_TOKEN")
                        response = http_requests.post(
                            f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
                            headers={"X-ChatWorkToken": chatwork_token},
                            data={"body": chatwork_message},
                            timeout=30
                        )

                        if response.status_code == 200:
                            message_id = response.json().get("message_id")
                            asyncio.run(service.mark_as_sent(
                                report_id=report_id,
                                sent_to=[],
                                sent_via="chatwork",
                                chatwork_room_id=room_id,
                                chatwork_message_id=str(message_id) if message_id else None,
                            ))
                            sent = True
                            print(f"✅ レポート送信完了: message_id={message_id}")
                        else:
                            asyncio.run(service.mark_as_failed(
                                report_id=report_id,
                                error_message=f"ChatWork API error: status={response.status_code}",
                            ))
                            sent = False
                            print(f"❌ ChatWork送信失敗: status={response.status_code}")
                    else:
                        sent = False
                        print(f"❌ レポートレコード取得失敗: {report_id}")

                    conn.commit()
                else:
                    sent = False
                    print(f"🧪 DRY RUN: レポート送信スキップ")
            except Exception:
                conn.rollback()
                raise

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        print(f"🏁 週次レポート完了: {elapsed:.2f}秒")

        return jsonify({
            "success": True,
            "message": "週次レポートを生成しました" + ("（送信済み）" if sent else "（未送信）"),
            "report_id": str(report_id),
            "sent": sent,
            "elapsed_seconds": elapsed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except Exception as e:
        error_msg = f"週次レポートエラー: {str(e)}"
        print(f"❌ {error_msg}")
        print(traceback.format_exc())

        return jsonify({
            "success": False,
            "error": error_msg,
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 500


@functions_framework.http
def personalization_detection(request: Request):
    """
    属人化検出のメインエントリポイント

    特定の人にしか回答できない状態を検出し、BCPリスクを可視化

    リクエストパラメータ:
    - dry_run: true の場合、DBに書き込まない
    - org_id: 組織ID（デフォルト: ソウルシンクス）

    レスポンス:
    - success: 成功/失敗
    - results: 検出結果のサマリー
    - timestamp: 実行日時
    """
    from lib.detection.personalization_detector import PersonalizationDetector

    start_time = datetime.now(timezone.utc)
    print(f"🚀 属人化検出開始: {start_time.isoformat()}")

    try:
        # リクエストパラメータを取得
        if request.is_json:
            data = request.get_json()
        else:
            data = {}

        dry_run = data.get("dry_run", DRY_RUN)
        org_id = data.get("org_id", DEFAULT_ORG_ID)

        if isinstance(dry_run, str):
            dry_run = dry_run.lower() in ("true", "1", "yes")

        print(f"📋 パラメータ: dry_run={dry_run}, org_id={org_id}")

        if dry_run:
            print(f"🧪 DRY RUN モード: DBへの書き込みはスキップされます")
            return jsonify({
                "success": True,
                "message": "DRY RUNモード - 属人化検出をスキップしました",
                "results": {"dry_run": True},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }), 200

        # データベース接続
        pool = get_db_pool()

        with pool.connect() as conn:
            org_uuid = UUID(org_id)

            # 属人化検出器を初期化
            detector = PersonalizationDetector(conn, org_uuid)

            # 検出を実行
            import asyncio
            try:
                result = asyncio.run(detector.detect())
                conn.commit()
                print(f"✅ トランザクションコミット完了")
            except Exception:
                conn.rollback()
                raise

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        print(f"🏁 属人化検出完了: {elapsed:.2f}秒")

        return jsonify({
            "success": result.success,
            "message": f"{result.detected_count}件のリスクを検出しました",
            "results": {
                "detected_count": result.detected_count,
                "insight_created": result.insight_created,
                "insight_id": str(result.insight_id) if result.insight_id else None,
                "details": result.details,
            },
            "elapsed_seconds": elapsed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except Exception as e:
        error_msg = f"属人化検出エラー: {str(e)}"
        print(f"❌ {error_msg}")
        print(traceback.format_exc())

        return jsonify({
            "success": False,
            "error": error_msg,
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 500


@functions_framework.http
def bottleneck_detection(request: Request):
    """
    ボトルネック検出のメインエントリポイント

    タスクの滞留・遅延・集中を検出し、業務改善ポイントを可視化

    検出するボトルネック:
    - 期限超過タスク（overdue_task）
    - 長期未完了タスク（stale_task）
    - タスク集中（task_concentration）

    リクエストパラメータ:
    - dry_run: true の場合、DBに書き込まない
    - org_id: 組織ID（デフォルト: ソウルシンクス）

    レスポンス:
    - success: 成功/失敗
    - results: 検出結果のサマリー
    - timestamp: 実行日時
    """
    from lib.detection.bottleneck_detector import BottleneckDetector

    start_time = datetime.now(timezone.utc)
    print(f"🚀 ボトルネック検出開始: {start_time.isoformat()}")

    try:
        # リクエストパラメータを取得
        if request.is_json:
            data = request.get_json()
        else:
            data = {}

        dry_run = data.get("dry_run", DRY_RUN)
        org_id = data.get("org_id", DEFAULT_ORG_ID)

        if isinstance(dry_run, str):
            dry_run = dry_run.lower() in ("true", "1", "yes")

        print(f"📋 パラメータ: dry_run={dry_run}, org_id={org_id}")

        if dry_run:
            print(f"🧪 DRY RUN モード: DBへの書き込みはスキップされます")
            return jsonify({
                "success": True,
                "message": "DRY RUNモード - ボトルネック検出をスキップしました",
                "results": {"dry_run": True},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }), 200

        # データベース接続
        pool = get_db_pool()

        with pool.connect() as conn:
            org_uuid = UUID(org_id)

            # ボトルネック検出器を初期化
            detector = BottleneckDetector(conn, org_uuid)

            # 検出を実行
            import asyncio
            try:
                result = asyncio.run(detector.detect())
                conn.commit()
                print(f"✅ トランザクションコミット完了")
            except Exception:
                conn.rollback()
                raise

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        print(f"🏁 ボトルネック検出完了: {elapsed:.2f}秒")

        return jsonify({
            "success": result.success,
            "message": f"{result.detected_count}件のボトルネックを検出しました",
            "results": {
                "detected_count": result.detected_count,
                "insight_created": result.insight_created,
                "insight_id": str(result.insight_id) if result.insight_id else None,
                "details": result.details,
            },
            "elapsed_seconds": elapsed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except Exception as e:
        error_msg = f"ボトルネック検出エラー: {str(e)}"
        print(f"❌ {error_msg}")
        print(traceback.format_exc())

        return jsonify({
            "success": False,
            "error": error_msg,
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 500


@functions_framework.http
def emotion_detection(request: Request):
    """
    感情変化検出のメインエントリポイント

    従業員のメッセージから感情変化を検出し、メンタルヘルスリスクを早期に可視化

    検出する感情変化:
    - 急激な感情悪化（sudden_drop）
    - 継続的なネガティブ（sustained_negative）
    - 感情の不安定さ（high_volatility）
    - 回復（recovery）

    プライバシー配慮:
    - 全データはCONFIDENTIAL分類
    - 管理者のみ通知（本人には直接通知しない）
    - メッセージ本文は保存しない（統計のみ）

    リクエストパラメータ:
    - dry_run: true の場合、DBに書き込まない
    - org_id: 組織ID（デフォルト: ソウルシンクス）

    レスポンス:
    - success: 成功/失敗
    - results: 検出結果のサマリー
    - timestamp: 実行日時
    """
    from lib.detection.emotion_detector import EmotionDetector

    start_time = datetime.now(timezone.utc)
    print(f"🚀 感情変化検出開始: {start_time.isoformat()}")

    try:
        # リクエストパラメータを取得
        if request.is_json:
            data = request.get_json()
        else:
            data = {}

        dry_run = data.get("dry_run", DRY_RUN)
        org_id = data.get("org_id", DEFAULT_ORG_ID)

        if isinstance(dry_run, str):
            dry_run = dry_run.lower() in ("true", "1", "yes")

        print(f"📋 パラメータ: dry_run={dry_run}, org_id={org_id}")

        if dry_run:
            print(f"🧪 DRY RUN モード: DBへの書き込みはスキップされます")
            return jsonify({
                "success": True,
                "message": "DRY RUNモード - 感情変化検出をスキップしました",
                "results": {"dry_run": True},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }), 200

        # データベース接続
        pool = get_db_pool()

        with pool.connect() as conn:
            org_uuid = UUID(org_id)

            # 感情変化検出器を初期化
            detector = EmotionDetector(conn, org_uuid)

            # 検出を実行
            import asyncio
            try:
                result = asyncio.run(detector.detect())
                conn.commit()
                print(f"✅ トランザクションコミット完了")
            except Exception:
                conn.rollback()
                raise

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        print(f"🏁 感情変化検出完了: {elapsed:.2f}秒")

        return jsonify({
            "success": result.success,
            "message": f"{result.detected_count}件の感情変化アラートを検出しました",
            "results": {
                "detected_count": result.detected_count,
                "insight_created": result.insight_created,
                "insight_id": str(result.insight_id) if result.insight_id else None,
                "details": result.details,
            },
            "elapsed_seconds": elapsed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except Exception as e:
        error_msg = f"感情変化検出エラー: {str(e)}"
        print(f"❌ {error_msg}")
        print(traceback.format_exc())

        return jsonify({
            "success": False,
            "error": error_msg,
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 500


# =====================================================
# 毎日のインサイト通知
# =====================================================

# カズさんへのDM用room_id
KAZUSAN_DM_ROOM_ID = 417892193


@functions_framework.http
def daily_insight_notification(request: Request):
    """
    毎日のインサイト通知をカズさんに送信

    毎朝 Cloud Scheduler から呼び出され、
    未対応のインサイト（問題）をChatWorkで通知する

    リクエストパラメータ:
    - dry_run: true の場合、送信しない
    - room_id: 送信先（デフォルト: カズさんDM）

    レスポンス:
    - success: 成功/失敗
    - insights_count: 通知したインサイト数
    - sent: 送信完了かどうか
    """
    import requests as http_requests

    start_time = datetime.now(timezone.utc)
    print(f"🚀 毎日インサイト通知開始: {start_time.isoformat()}")

    try:
        # リクエストパラメータを取得
        if request.is_json:
            data = request.get_json()
        else:
            data = {}

        dry_run = data.get("dry_run", DRY_RUN)
        room_id = int(data.get("room_id", KAZUSAN_DM_ROOM_ID))
        org_id = data.get("org_id", DEFAULT_ORG_ID)

        if isinstance(dry_run, str):
            dry_run = dry_run.lower() in ("true", "1", "yes")

        print(f"📋 パラメータ: dry_run={dry_run}, room_id={room_id}")

        # データベース接続
        pool = get_db_pool()

        with pool.connect() as conn:
            # 未対応インサイトを取得（importance順）
            result = conn.execute(text("""
                SELECT
                    id,
                    insight_type,
                    importance,
                    title,
                    description,
                    recommended_action,
                    created_at
                FROM soulkun_insights
                WHERE organization_id = :org_id
                  AND status = 'new'
                ORDER BY
                    CASE importance
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        WHEN 'low' THEN 4
                    END,
                    created_at DESC
                LIMIT 20
            """), {"org_id": org_id})

            insights = result.fetchall()
            total_count = len(insights)

            if total_count == 0:
                print("✅ 未対応インサイトはありません")
                return jsonify({
                    "success": True,
                    "message": "未対応のインサイトはありません",
                    "insights_count": 0,
                    "sent": False,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }), 200

            # 全件数を取得
            result = conn.execute(text("""
                SELECT COUNT(*) FROM soulkun_insights
                WHERE organization_id = :org_id AND status = 'new'
            """), {"org_id": org_id})
            all_count = result.fetchone()[0]

            # importance別集計
            result = conn.execute(text("""
                SELECT importance, COUNT(*)
                FROM soulkun_insights
                WHERE organization_id = :org_id AND status = 'new'
                GROUP BY importance
            """), {"org_id": org_id})
            importance_counts = {row[0]: row[1] for row in result.fetchall()}

            # メッセージを作成
            jst = timezone(timedelta(hours=9))
            today = datetime.now(jst).strftime("%m/%d")

            message = f"[info][title]📊 {today} 対応が必要な問題リスト[/title]"
            message += f"未対応: {all_count}件"

            if importance_counts.get('critical', 0) > 0:
                message += f" (🔴緊急: {importance_counts.get('critical', 0)}件)"
            if importance_counts.get('high', 0) > 0:
                message += f" (🟠重要: {importance_counts.get('high', 0)}件)"

            message += "\n\n"

            # インサイトをリスト化
            for i, insight in enumerate(insights[:10], 1):
                importance = insight[2]
                title = insight[3][:50]

                if importance == 'critical':
                    icon = "🔴"
                elif importance == 'high':
                    icon = "🟠"
                elif importance == 'medium':
                    icon = "🟡"
                else:
                    icon = "⚪"

                message += f"{icon} {title}\n"

            if all_count > 10:
                message += f"\n...他 {all_count - 10}件"

            message += "[/info]"

            print(f"📝 メッセージ作成完了: {len(message)}文字")

            # ChatWorkに送信（ソウルくんのトークンを使用）
            if not dry_run:
                chatwork_token = get_secret("SOULKUN_CHATWORK_TOKEN")

                response = http_requests.post(
                    f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
                    headers={"X-ChatWorkToken": chatwork_token},
                    data={"body": message},
                    timeout=30
                )

                if response.status_code == 200:
                    print(f"✅ ChatWork送信成功")
                    sent = True
                else:
                    print(f"❌ ChatWork送信失敗: {response.status_code} {response.text}")
                    sent = False
            else:
                print(f"🧪 DRY RUN: 送信スキップ")
                print(f"📝 メッセージ内容:\n{message}")
                sent = False

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        print(f"🏁 毎日インサイト通知完了: {elapsed:.2f}秒")

        return jsonify({
            "success": True,
            "message": f"{all_count}件のインサイトを通知しました" if sent else f"{all_count}件のインサイトがあります（未送信）",
            "insights_count": all_count,
            "sent": sent,
            "elapsed_seconds": elapsed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except Exception as e:
        error_msg = f"インサイト通知エラー: {str(e)}"
        print(f"❌ {error_msg}")
        print(traceback.format_exc())

        return jsonify({
            "success": False,
            "error": error_msg,
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 500
