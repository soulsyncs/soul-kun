################################################################################
# Cloud SQL — PostgreSQL instance, database, user
################################################################################

resource "google_sql_database_instance" "main" {
  name                = var.db_instance_name
  database_version    = "POSTGRES_15"
  region              = var.region
  deletion_protection = true

  settings {
    tier              = var.db_tier
    disk_size         = var.db_disk_size
    disk_autoresize   = true
    availability_type = "ZONAL"

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "03:00" # JST 12:00
      transaction_log_retention_days = 7

      backup_retention_settings {
        retained_backups = 365
      }
    }

    ip_configuration {
      ipv4_enabled = true
      # Cloud Functions は Cloud SQL Connector 経由で接続（IP不要）
    }

    database_flags {
      name  = "max_connections"
      value = "1000"
    }

    maintenance_window {
      day          = 7 # Sunday
      hour         = 4 # JST 13:00
      update_track = "stable"
    }
  }

  lifecycle {
    # disk_size は autoresize で動的に変化
    # ip_configuration は GCP Console / gcloud で管理（authorized_networks 等）
    # database_flags / maintenance_window は既に手動設定済み
    ignore_changes = [
      settings[0].disk_size,
      settings[0].ip_configuration,
      settings[0].database_flags,
      settings[0].maintenance_window,
    ]
  }
}

resource "google_sql_database" "main" {
  name     = var.db_name
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "main" {
  name     = var.db_user
  instance = google_sql_database_instance.main.name
  # password は Secret Manager で管理。import 時は ignore_changes で保護
  lifecycle {
    ignore_changes = [password]
  }
}
