################################################################################
# Cloud Scheduler — 定期実行ジョブ
################################################################################

locals {
  scheduler_jobs = {
    supabase-sync-daily = {
      description = "Daily Supabase to Cloud SQL sync"
      schedule    = "0 6 * * *" # 毎日 06:00 JST
      function    = "supabase_sync"
      http_method = "POST"
      body        = ""
    }

    pattern-detection-hourly = {
      description = "Hourly pattern detection analysis"
      schedule    = "15 * * * *" # 毎時 :15
      function    = "pattern-detection"
      http_method = "POST"
      body        = ""
    }

    personalization-detection-daily = {
      description = "Daily personalization detection"
      schedule    = "0 6 * * *" # 毎日 06:00 JST
      function    = "personalization-detection"
      http_method = "POST"
      body        = ""
    }

    weekly-report-monday = {
      description = "Weekly report generation (Monday 9:00 JST)"
      schedule    = "0 9 * * 1" # 月曜 09:00 JST
      function    = "weekly-report"
      http_method = "POST"
      body        = jsonencode({ room_id = var.chatwork_dm_room_id })
    }

    goal-daily-check = {
      description = "Daily goal progress check"
      schedule    = "0 21 * * *" # 毎日 21:00 JST
      function    = "goal-daily-check"
      http_method = "POST"
      body        = ""
    }

    goal-daily-reminder = {
      description = "Daily goal reminder"
      schedule    = "0 9 * * *" # 毎日 09:00 JST
      function    = "goal-daily-reminder"
      http_method = "POST"
      body        = ""
    }

    goal-morning-feedback = {
      description = "Morning goal feedback"
      schedule    = "30 8 * * *" # 毎日 08:30 JST
      function    = "goal-morning-feedback"
      http_method = "POST"
      body        = ""
    }

    goal-consecutive-unanswered = {
      description = "Alert for consecutive unanswered goals"
      schedule    = "0 18 * * *" # 毎日 18:00 JST
      function    = "goal-consecutive-unanswered"
      http_method = "POST"
      body        = ""
    }
  }
}

resource "google_cloud_scheduler_job" "jobs" {
  for_each = local.scheduler_jobs

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
    uri         = google_cloudfunctions2_function.functions[each.value.function].service_config[0].uri
    body        = each.value.body != "" ? base64encode(each.value.body) : null

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }
}
