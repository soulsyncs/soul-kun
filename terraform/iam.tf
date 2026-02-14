################################################################################
# IAM — サービスアカウントと権限
################################################################################

# Cloud Functions 実行用サービスアカウント
resource "google_service_account" "cloud_functions" {
  account_id   = "cloud-functions-sa"
  display_name = "Cloud Functions Service Account"
  description  = "Service account for all Cloud Functions"
}

# Cloud Scheduler 呼び出し用サービスアカウント
resource "google_service_account" "scheduler_invoker" {
  account_id   = "scheduler-invoker"
  display_name = "Cloud Scheduler Invoker"
  description  = "Service account for Cloud Scheduler to invoke Cloud Functions"
}

# Scheduler → Cloud Functions (Cloud Run) 呼び出し権限
# プロジェクトレベルではなく、Scheduler対象の関数のみに限定（最小権限の原則）
locals {
  # CF Gen2 functions invoked by Cloud Scheduler（cloud_functions.tf の functions マップのキー）
  scheduler_target_functions = [
    "supabase_sync",
    "pattern-detection",
    "personalization-detection",
    "weekly-report",
    "goal-daily-check",
    "goal-daily-reminder",
    "goal-morning-feedback",
    "goal-consecutive-unanswered",
    # 2026-02-14 Cloud Run移行で追加
    "bottleneck-detection",
    "brain-daily-aggregation",
    "check-reply-messages",
    "cleanup-old-data",
    "db-backup-export",
    "remind-tasks",
    "report-generator",
    "sync-room-members",
    "sync-chatwork-tasks",
    "sync_drive_permissions",
  ]

  # 非CF Gen2 Cloud Run services invoked by Cloud Scheduler
  # Docker-based (proactive-monitor) + 純 Cloud Run (daily-reminder, weekly-summary, weekly-summary-manager)
  scheduler_target_cloud_run_services = [
    "proactive-monitor",
    "daily-reminder",
    "weekly-summary",
    "weekly-summary-manager",
  ]
}

# CF Gen2 functions → scheduler-invoker IAM
resource "google_cloud_run_service_iam_member" "scheduler_invoker" {
  for_each = toset(local.scheduler_target_functions)

  service  = google_cloudfunctions2_function.functions[each.value].service_config[0].service
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

# 非CF Cloud Run services → scheduler-invoker IAM
resource "google_cloud_run_service_iam_member" "scheduler_invoker_cloud_run" {
  for_each = toset(local.scheduler_target_cloud_run_services)

  service  = each.value
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

# Cloud Functions SA → Cloud SQL クライアント
resource "google_project_iam_member" "cf_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_functions.email}"
}

# Cloud Functions SA → GCS オブジェクト管理（会議録音読み書き）
resource "google_storage_bucket_iam_member" "cf_recordings_admin" {
  bucket = google_storage_bucket.meeting_recordings.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloud_functions.email}"
}

# Cloud Functions SA → ログ書き込み
resource "google_project_iam_member" "cf_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cloud_functions.email}"
}
