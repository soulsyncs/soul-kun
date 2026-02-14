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
  scheduler_target_functions = [
    "supabase_sync",
    "pattern-detection",
    "personalization-detection",
    "weekly-report",
    "goal-daily-check",
    "goal-daily-reminder",
    "goal-morning-feedback",
    "goal-consecutive-unanswered",
  ]
}

resource "google_cloud_run_service_iam_member" "scheduler_invoker" {
  for_each = toset(local.scheduler_target_functions)

  service  = google_cloudfunctions2_function.functions[each.value].service_config[0].service
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
