################################################################################
# Cloud Functions Gen2 — ファンクション定義
#
# NOTE: chatwork-webhook と proactive-monitor は Cloud Run v2 (Docker) に移行済み。
# Cloud Build パイプラインが管理するため、ここには含めない。
#
# 残りの Cloud Functions は環境変数を gcloud CLI / deploy scripts で管理。
# Terraform は「存在」のみ管理し、ランタイム設定は lifecycle ignore_changes で保護。
#
# 3AI合議結果 (2026-02-14):
# - Codex: Option A (state rm for Docker services)
# - Gemini: Option C+B hybrid (ignore_changes + phased alignment)
# - Claude: Option A+C hybrid (state rm + ignore_changes)
# → 全員一致: chatwork-webhook/proactive-monitor を除外 + ignore_changes
################################################################################

locals {
  # 全ファンクション共通の環境変数（ドキュメント目的。実際の値は deploy scripts が管理）
  common_env_vars = {
    CORS_ORIGINS               = var.cors_origins
    INSTANCE_CONNECTION_NAME   = "${var.project_id}:${var.region}:${var.db_instance_name}"
    DB_NAME                    = var.db_name
    DB_USER                    = var.db_user
    PROJECT_ID                 = var.project_id
    ENVIRONMENT                = "production"
    DEBUG                      = "false"
    USE_BRAIN_ARCHITECTURE     = "true"
    LOG_EXECUTION_ID           = "true"
    ENABLE_SYSTEM_PROMPT_V2    = "true"
  }

  # ファンクション定義マップ（chatwork-webhook, proactive-monitor は除外）
  functions = {
    watch_google_drive = {
      description          = "Google Drive monitoring and knowledge indexing"
      entry_point          = "watch_google_drive"
      source_dir           = "watch-google-drive"
      memory               = "1Gi"
      timeout              = 540
      max_instances        = 3
      min_instances        = 0
      allow_unauthenticated = false
      extra_env = {
        ORGANIZATION_ID    = var.cloudsql_org_id
        ROOT_FOLDER_ID     = var.root_folder_id
        CHUNK_SIZE         = "1000"
        CHUNK_OVERLAP      = "200"
        PINECONE_INDEX_NAME = var.pinecone_index_name
      }
      secrets = {
        GOOGLE_AI_API_KEY = "GOOGLE_AI_API_KEY"
        PINECONE_API_KEY  = "PINECONE_API_KEY"
        DB_PASSWORD       = "cloudsql-password"
      }
    }

    supabase_sync = {
      description          = "Supabase to Cloud SQL data sync"
      entry_point          = "supabase_sync"
      source_dir           = "supabase-sync"
      memory               = "256Mi"
      timeout              = 120
      max_instances        = 1
      min_instances        = 0
      allow_unauthenticated = false
      extra_env = {
        SUPABASE_URL   = var.supabase_url
        SOULKUN_ORG_ID = var.supabase_org_id
        CLOUDSQL_ORG_ID = var.cloudsql_org_id
      }
      secrets = {
        SUPABASE_ANON_KEY = "SUPABASE_ANON_KEY"
        DB_PASSWORD       = "cloudsql-password"
      }
    }

    pattern-detection = {
      description          = "LangGraph pattern detection analysis"
      entry_point          = "pattern_detection"
      source_dir           = "pattern-detection"
      memory               = "512Mi"
      timeout              = 300
      max_instances        = 3
      min_instances        = 0
      allow_unauthenticated = false
      extra_env = {
        DRY_RUN   = "false"
        TEST_MODE = "false"
      }
      secrets = {
        GOOGLE_AI_API_KEY = "GOOGLE_AI_API_KEY"
        PINECONE_API_KEY  = "PINECONE_API_KEY"
        DB_PASSWORD       = "cloudsql-password"
      }
    }

    personalization-detection = {
      description          = "Personalization pattern detection"
      entry_point          = "personalization_detection"
      source_dir           = "pattern-detection"
      memory               = "512Mi"
      timeout              = 300
      max_instances        = 3
      min_instances        = 0
      allow_unauthenticated = false
      extra_env = {
        DRY_RUN   = "false"
        TEST_MODE = "false"
      }
      secrets = {
        GOOGLE_AI_API_KEY = "GOOGLE_AI_API_KEY"
        DB_PASSWORD       = "cloudsql-password"
      }
    }

    weekly-report = {
      description          = "Weekly report generation and delivery"
      entry_point          = "weekly_report"
      source_dir           = "pattern-detection"
      memory               = "512Mi"
      timeout              = 300
      max_instances        = 1
      min_instances        = 0
      allow_unauthenticated = false
      extra_env = {
        DRY_RUN   = "false"
        TEST_MODE = "false"
      }
      secrets = {
        OPENROUTER_API_KEY = "openrouter-api-key"
        DB_PASSWORD        = "cloudsql-password"
      }
    }

    sync_drive_permissions = {
      description          = "Google Drive permissions sync"
      entry_point          = "sync_drive_permissions"
      source_dir           = "sync-drive-permissions"
      memory               = "512Mi"
      timeout              = 540
      max_instances        = 1
      min_instances        = 0
      allow_unauthenticated = false
      extra_env = {}
      secrets = {
        GOOGLE_SERVICE_ACCOUNT_JSON = "GOOGLE_SERVICE_ACCOUNT_JSON"
        DB_PASSWORD                 = "cloudsql-password"
      }
    }

    sync-chatwork-tasks = {
      description          = "ChatWork task sync to Cloud SQL"
      entry_point          = "sync_chatwork_tasks"
      source_dir           = "sync-chatwork-tasks"
      memory               = "512Mi"
      timeout              = 540
      max_instances        = 1
      min_instances        = 0
      allow_unauthenticated = false
      extra_env = {}
      secrets = {
        SOULKUN_CHATWORK_TOKEN = "SOULKUN_CHATWORK_TOKEN"
        ANTHROPIC_API_KEY      = "ANTHROPIC_API_KEY"
        DB_PASSWORD            = "cloudsql-password"
      }
    }

    goal-daily-check = {
      description          = "Daily goal progress check"
      entry_point          = "goal_daily_check"
      source_dir           = "remind-tasks"
      memory               = "512Mi"
      timeout              = 540
      max_instances        = 1
      min_instances        = 0
      allow_unauthenticated = false
      extra_env = {}
      secrets = {
        CHATWORK_API_TOKEN     = "chatwork-api-key"
        SOULKUN_CHATWORK_TOKEN = "SOULKUN_CHATWORK_TOKEN"
        OPENROUTER_API_KEY     = "openrouter-api-key"
        DB_PASSWORD            = "cloudsql-password"
      }
    }

    goal-daily-reminder = {
      description          = "Daily goal reminder notification"
      entry_point          = "goal_daily_reminder"
      source_dir           = "remind-tasks"
      memory               = "512Mi"
      timeout              = 540
      max_instances        = 1
      min_instances        = 0
      allow_unauthenticated = false
      extra_env = {}
      secrets = {
        CHATWORK_API_TOKEN     = "chatwork-api-key"
        SOULKUN_CHATWORK_TOKEN = "SOULKUN_CHATWORK_TOKEN"
        OPENROUTER_API_KEY     = "openrouter-api-key"
        DB_PASSWORD            = "cloudsql-password"
      }
    }

    goal-morning-feedback = {
      description          = "Morning goal feedback"
      entry_point          = "goal_morning_feedback"
      source_dir           = "remind-tasks"
      memory               = "512Mi"
      timeout              = 540
      max_instances        = 1
      min_instances        = 0
      allow_unauthenticated = false
      extra_env = {}
      secrets = {
        CHATWORK_API_TOKEN     = "chatwork-api-key"
        SOULKUN_CHATWORK_TOKEN = "SOULKUN_CHATWORK_TOKEN"
        OPENROUTER_API_KEY     = "openrouter-api-key"
        DB_PASSWORD            = "cloudsql-password"
      }
    }

    goal-consecutive-unanswered = {
      description          = "Consecutive unanswered goal alerts"
      entry_point          = "goal_consecutive_unanswered_check"
      source_dir           = "remind-tasks"
      memory               = "512Mi"
      timeout              = 540
      max_instances        = 1
      min_instances        = 0
      allow_unauthenticated = false
      extra_env = {}
      secrets = {
        CHATWORK_API_TOKEN     = "chatwork-api-key"
        SOULKUN_CHATWORK_TOKEN = "SOULKUN_CHATWORK_TOKEN"
        OPENROUTER_API_KEY     = "openrouter-api-key"
        DB_PASSWORD            = "cloudsql-password"
      }
    }
  }
}

# Cloud Functions Gen2 を for_each で生成
resource "google_cloudfunctions2_function" "functions" {
  for_each = local.functions

  name        = each.key
  location    = var.region
  description = each.value.description

  build_config {
    runtime     = var.functions_runtime
    entry_point = each.value.entry_point

    source {
      storage_source {
        bucket = "gcf-v2-sources-${data.google_project.current.number}-${var.region}"
        object = "placeholder" # CI/CD がデプロイ時に上書き
      }
    }
  }

  service_config {
    available_memory   = each.value.memory
    timeout_seconds    = each.value.timeout
    max_instance_count = each.value.max_instances
    min_instance_count = each.value.min_instances

    environment_variables = merge(local.common_env_vars, each.value.extra_env)

    dynamic "secret_environment_variables" {
      for_each = each.value.secrets
      content {
        key        = secret_environment_variables.key
        project_id = var.project_id
        secret     = secret_environment_variables.value
        version    = "latest"
      }
    }

    # Cloud SQL 接続（Cloud SQL Connector 経由）
    service_account_email = google_service_account.cloud_functions.email
  }

  lifecycle {
    # ソースコードは CI/CD が管理。Terraform で上書きしない。
    # 環境変数・シークレット・リソース設定は deploy scripts が管理。
    # Terraform はリソースの「存在」のみ管理する。（3AI合議 2026-02-14）
    ignore_changes = [
      build_config[0].source,
      service_config[0].environment_variables,
      service_config[0].secret_environment_variables,
      service_config[0].available_memory,
      service_config[0].max_instance_count,
      service_config[0].min_instance_count,
      service_config[0].service_account_email,
      service_config[0].all_traffic_on_latest_revision,
    ]
  }
}

# NOTE: chatwork-webhook の公開アクセス（allUsers）は Cloud Build / gcloud で管理。
# chatwork-webhook は Terraform 管理外のため、ここでは定義しない。

data "google_project" "current" {}
