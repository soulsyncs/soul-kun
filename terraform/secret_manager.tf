################################################################################
# Secret Manager — シークレット定義
#
# NOTE: シークレットの「値」は Terraform で管理しない（セキュリティ上の理由）。
# ここではシークレットの「箱」のみ作成。値は gcloud CLI or Console で設定。
################################################################################

locals {
  secrets = [
    "chatwork-api-key",
    "openrouter-api-key",
    "cloudsql-password",
    "GOOGLE_AI_API_KEY",
    "PINECONE_API_KEY",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "ANTHROPIC_API_KEY",
    "SOULKUN_CHATWORK_TOKEN",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    # Zoom S2S OAuth
    "zoom-client-id",
    "zoom-client-secret",
    "zoom-account-id",
  ]
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = toset(local.secrets)
  secret_id = each.value

  replication {
    auto {}
  }
}

# Cloud Functions サービスアカウントにシークレット読み取り権限を付与
resource "google_secret_manager_secret_iam_member" "cf_access" {
  for_each  = toset(local.secrets)
  secret_id = google_secret_manager_secret.secrets[each.value].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_functions.email}"
}
