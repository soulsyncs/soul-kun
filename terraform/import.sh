#!/usr/bin/env bash
set -euo pipefail
################################################################################
# Terraform Import Script
# 既存の GCP リソースを Terraform state にインポートする
#
# 使い方:
#   1. terraform init を実行済みであること
#   2. bash import.sh
#
# NOTE: 各コマンドは冪等ではない（既にインポート済みならスキップ）
################################################################################

PROJECT="soulkun-production"
REGION="asia-northeast1"

echo "=== Terraform Import: soul-kun infrastructure ==="
echo "Project: ${PROJECT}"
echo "Region: ${REGION}"
echo ""

import_resource() {
  local addr="$1"
  local id="$2"
  echo "Importing: ${addr}"
  if terraform state show "${addr}" &>/dev/null; then
    echo "  -> Already imported, skipping"
  else
    terraform import "${addr}" "${id}" || echo "  -> FAILED (manual check required)"
  fi
  echo ""
}

# Cloud SQL
import_resource "google_sql_database_instance.main" \
  "projects/${PROJECT}/instances/soulkun-db"

import_resource "google_sql_database.main" \
  "projects/${PROJECT}/instances/soulkun-db/databases/soulkun_tasks"

import_resource "google_sql_user.main" \
  "${PROJECT}/soulkun-db/soulkun_user"

# GCS Buckets
import_resource "google_storage_bucket.meeting_recordings" \
  "soulkun-meeting-recordings"

import_resource "google_storage_bucket.terraform_state" \
  "soulkun-terraform-state"

# Service Accounts
import_resource "google_service_account.cloud_functions" \
  "projects/${PROJECT}/serviceAccounts/cloud-functions-sa@${PROJECT}.iam.gserviceaccount.com"

import_resource "google_service_account.scheduler_invoker" \
  "projects/${PROJECT}/serviceAccounts/scheduler-invoker@${PROJECT}.iam.gserviceaccount.com"

# Cloud Functions (Gen2)
# format: "terraform_key:gcp_name" (同じ場合はキーのみ)
FUNCTIONS=(
  "chatwork-webhook"
  "proactive-monitor"
  "watch_google_drive"
  "supabase_sync"
  "pattern-detection"
  "personalization-detection"
  "weekly-report"
  "sync_drive_permissions"
  "sync-chatwork-tasks"
  "goal-daily-check"
  "goal-daily-reminder"
  "goal-morning-feedback"
  "goal-consecutive-unanswered"
)

for fn in "${FUNCTIONS[@]}"; do
  # Terraform キー名がそのまま GCP 関数名になる（name = each.key）
  import_resource "google_cloudfunctions2_function.functions[\"${fn}\"]" \
    "projects/${PROJECT}/locations/${REGION}/functions/${fn}"
done

# Secret Manager
SECRETS=(
  chatwork-api-key
  openrouter-api-key
  cloudsql-password
  GOOGLE_AI_API_KEY
  PINECONE_API_KEY
  SUPABASE_ANON_KEY
  SUPABASE_SERVICE_ROLE_KEY
  ANTHROPIC_API_KEY
  SOULKUN_CHATWORK_TOKEN
  GOOGLE_SERVICE_ACCOUNT_JSON
  zoom-client-id
  zoom-client-secret
  zoom-account-id
)

for secret in "${SECRETS[@]}"; do
  import_resource "google_secret_manager_secret.secrets[\"${secret}\"]" \
    "projects/${PROJECT}/secrets/${secret}"
done

# Cloud Scheduler Jobs
JOBS=(
  supabase-sync-daily
  pattern-detection-hourly
  personalization-detection-daily
  weekly-report-monday
  goal-daily-check
  goal-daily-reminder
  goal-morning-feedback
  goal-consecutive-unanswered
)

for job in "${JOBS[@]}"; do
  import_resource "google_cloud_scheduler_job.jobs[\"${job}\"]" \
    "projects/${PROJECT}/locations/${REGION}/jobs/${job}"
done

echo "=== Import complete ==="
echo "Run 'terraform plan' to check for drift."
