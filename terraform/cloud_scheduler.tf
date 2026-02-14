################################################################################
# Cloud Scheduler — 定期実行ジョブ
#
# 2026-02-14: 全27ジョブをTF管理下に。
# CF Gen2-backed と 純Cloud Run-backed で分割。
# lifecycle ignore_changes で既存設定を保護。
################################################################################

# ============================================================
# CF Gen2-backed Scheduler Jobs（cloud_functions.tf の functions マップを参照）
# ============================================================

locals {
  scheduler_cf_jobs = {
    # --- パターン検知系 ---
    pattern-detection-hourly = {
      description = "Phase 2 A1: パターン検知（毎時実行）"
      schedule    = "15 * * * *"
      function    = "pattern-detection"
      path        = ""
      http_method = "POST"
      body        = jsonencode({ hours_back = 1 })
    }

    daily-insight-notification = {
      description = "毎朝8:00にカズさんへインサイト通知"
      schedule    = "0 8 * * *"
      function    = "pattern-detection"
      path        = "/daily-insight"
      http_method = "POST"
      body        = jsonencode({ dry_run = false })
    }

    emotion-detection-daily = {
      description = "Phase 2 A4: 感情変化検出（毎日10:00）"
      schedule    = "0 10 * * *"
      function    = "pattern-detection"
      path        = "/emotion-detection"
      http_method = "POST"
      body        = jsonencode({ dry_run = false })
    }

    personalization-detection-daily = {
      description = "Phase 2 A2: 属人化検出（毎日実行）"
      schedule    = "0 6 * * *"
      function    = "personalization-detection"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    bottleneck-detection-daily = {
      description = "毎日8:00 JSTにボトルネック検出を実行"
      schedule    = "0 8 * * *"
      function    = "bottleneck-detection"
      path        = ""
      http_method = "POST"
      body        = jsonencode({ dry_run = false })
    }

    weekly-report-monday = {
      description = "Phase 2 A1: 週次レポート（毎週月曜9:00）→ 菊地さんDMのみ"
      schedule    = "0 9 * * 1"
      function    = "weekly-report"
      path        = ""
      http_method = "POST"
      body        = jsonencode({ room_id = var.chatwork_dm_room_id })
    }

    # --- レポート生成系 ---
    weekly-report-generation = {
      description = "週報下書き自動生成（毎週金曜17:00）"
      schedule    = "0 17 * * 5"
      function    = "report-generator"
      path        = "/weekly-report"
      http_method = "POST"
      body        = jsonencode({ dry_run = false })
    }

    daily-report-generation = {
      description = "日報下書き自動生成（毎日18:00）"
      schedule    = "0 18 * * *"
      function    = "report-generator"
      path        = "/daily-report"
      http_method = "POST"
      body        = jsonencode({ dry_run = false })
    }

    # --- 目標管理系 ---
    goal-daily-check-job = {
      description = "Phase 2.5: 17時目標進捗確認"
      schedule    = "0 17 * * *"
      function    = "goal-daily-check"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    goal-daily-reminder-job = {
      description = "Phase 2.5: 18時未回答リマインド"
      schedule    = "0 18 * * *"
      function    = "goal-daily-reminder"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    goal-morning-feedback-job = {
      description = "Phase 2.5: 8時朝フィードバック"
      schedule    = "0 8 * * *"
      function    = "goal-morning-feedback"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    goal-consecutive-unanswered-job = {
      description = "Phase 2.5: 9時連続未回答チェック"
      schedule    = "0 9 * * *"
      function    = "goal-consecutive-unanswered"
      path        = ""
      http_method = "POST"
      body        = jsonencode({ consecutive_days = 3 })
    }

    # --- 同期系 ---
    supabase-sync-daily = {
      description = "Daily Supabase to Cloud SQL sync"
      schedule    = "0 6 * * *"
      function    = "supabase_sync"
      path        = ""
      http_method = "POST"
      body        = jsonencode({ dry_run = false })
    }

    sync-chatwork-tasks-job = {
      description = "Sync ChatWork tasks every hour"
      schedule    = "0 * * * *"
      function    = "sync-chatwork-tasks"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    sync-done-tasks-job = {
      description = "Sync done tasks every 4 hours"
      schedule    = "0 */4 * * *"
      function    = "sync-chatwork-tasks"
      path        = "/?include_done=true"
      http_method = "POST"
      body        = ""
    }

    sync-room-members-job = {
      description = "Sync room members weekly (Monday 8:00)"
      schedule    = "0 8 * * 1"
      function    = "sync-room-members"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    sync-drive-permissions-daily = {
      description = "Google Drive permissions daily sync"
      schedule    = "0 2 * * *"
      function    = "sync_drive_permissions"
      path        = ""
      http_method = "POST"
      body        = jsonencode({ dry_run = false, remove_unlisted = false, create_snapshot = true })
    }

    # --- タスクリマインド・返信チェック系 ---
    remind-tasks-job = {
      description = "Send task reminders daily at 8:30 AM JST"
      schedule    = "30 8 * * *"
      function    = "remind-tasks"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    check-reply-messages-job = {
      description = "Check and process reply messages"
      schedule    = "*/5 * * * *"
      function    = "check-reply-messages"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    # --- メンテナンス系 ---
    cleanup-old-data-job = {
      description = "Cleanup old data daily at 3:00 AM"
      schedule    = "0 3 * * *"
      function    = "cleanup-old-data"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    db-backup-monthly = {
      description = "Monthly database backup export"
      schedule    = "0 3 1 * *"
      function    = "db-backup-export"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    # --- Brain系 ---
    brain-daily-aggregation = {
      description = "Brain Observability: 日次メトリクス集計 (毎日0:30 JST)"
      schedule    = "30 0 * * *"
      function    = "brain-daily-aggregation"
      path        = ""
      http_method = "POST"
      body        = ""
    }
  }
}

resource "google_cloud_scheduler_job" "cf_jobs" {
  for_each = local.scheduler_cf_jobs

  name        = each.key
  description = each.value.description
  schedule    = each.value.schedule
  time_zone   = "Asia/Tokyo"
  region      = var.region

  retry_config {
    retry_count          = 3
    min_backoff_duration = "10s"
    max_backoff_duration = "300s"
    max_doublings        = 3
  }

  http_target {
    http_method = each.value.http_method
    uri         = "${google_cloudfunctions2_function.functions[each.value.function].service_config[0].uri}${each.value.path}"
    body        = each.value.body != "" ? base64encode(each.value.body) : null

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  lifecycle {
    ignore_changes = [
      http_target,
      retry_config,
      attempt_deadline,
      schedule,
      description,
    ]
  }
}

# ============================================================
# 純 Cloud Run-backed Scheduler Jobs（CF Gen2 ではない）
# ============================================================

data "google_cloud_run_service" "scheduler_cr_targets" {
  for_each = toset(["proactive-monitor", "daily-reminder", "weekly-summary", "weekly-summary-manager"])

  name     = each.value
  location = var.region
}

locals {
  scheduler_cr_jobs = {
    proactive-monitor-hourly = {
      description = "Phase 2K: 能動的モニタリング（毎時実行）"
      schedule    = "30 * * * *"
      service     = "proactive-monitor"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    daily-reminder-job = {
      description = "Send daily progress reminders at 18:00 JST"
      schedule    = "0 18 * * *"
      service     = "daily-reminder"
      path        = ""
      http_method = "POST"
      body        = ""
    }

    weekly-summary-job = {
      description = "Send weekly summary every Friday 18:00 JST"
      schedule    = "0 18 * * 5"
      service     = "weekly-summary"
      path        = ""
      http_method = "GET"
      body        = ""
    }

    weekly-summary-manager-job = {
      description = "毎週金曜18:05に管理者向け週次サマリーを送信"
      schedule    = "5 18 * * 5"
      service     = "weekly-summary-manager"
      path        = ""
      http_method = "GET"
      body        = ""
    }
  }
}

resource "google_cloud_scheduler_job" "cr_jobs" {
  for_each = local.scheduler_cr_jobs

  name        = each.key
  description = each.value.description
  schedule    = each.value.schedule
  time_zone   = "Asia/Tokyo"
  region      = var.region

  retry_config {
    retry_count          = 3
    min_backoff_duration = "10s"
    max_backoff_duration = "300s"
    max_doublings        = 3
  }

  http_target {
    http_method = each.value.http_method
    uri         = "${data.google_cloud_run_service.scheduler_cr_targets[each.value.service].status[0].url}${each.value.path}"
    body        = each.value.body != "" ? base64encode(each.value.body) : null

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  lifecycle {
    ignore_changes = [
      http_target,
      retry_config,
      attempt_deadline,
      schedule,
      description,
    ]
  }
}

# NOTE: soulkun-task-polling は PAUSED 状態。TF管理外とする。
