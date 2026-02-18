################################################################################
# Cloud Run サービス定義
#
# 対象サービス:
#   - chatwork-webhook  : チャットワークからのメッセージを受け取るサービス
#   - proactive-monitor : 定期的にタスクやメッセージをチェックするサービス
#
# 注意:
#   - コンテナイメージの更新は Cloud Build パイプラインが担当
#   - Terraform は「サービスの存在とリソース設定」のみ管理
#   - 環境変数・シークレットは Cloud Build の --update-env-vars で管理
#   - lifecycle ignore_changes で自動デプロイの設定を保護
#
# 3AI合議 (P18, 2026-02-19):
#   - Claude:  Cloud Build との役割分担を明確化（Terraform=インフラ定義、Cloud Build=デプロイ）
#   - Gemini:  ignore_changes でデプロイ設定を保護することを推奨
#   - Codex:   初期イメージはlatestを使用し、以降はCloud Buildに委ねる方式を推奨
################################################################################

# ============================================================
# Artifact Registry（Dockerイメージの保存場所）
# ============================================================
resource "google_artifact_registry_repository" "cloud_run" {
  location      = var.region
  repository_id = "cloud-run"
  description   = "Cloud Run コンテナイメージ保存場所"
  format        = "DOCKER"

  lifecycle {
    prevent_destroy = true
  }
}

# ============================================================
# chatwork-webhook サービス
# チャットワークからのメッセージを受け取る「玄関口」
# ============================================================
resource "google_cloud_run_v2_service" "chatwork_webhook" {
  name     = "chatwork-webhook"
  location = var.region

  template {
    service_account = google_service_account.cloud_run_sa.email

    scaling {
      min_instance_count = 1   # 常時1台以上起動（応答速度確保）
      max_instance_count = 10  # 最大10台まで自動拡張
    }

    containers {
      # イメージはCloud Buildが更新するため、初期値のみここで定義
      image = "${var.region}-docker.pkg.dev/${var.project_id}/cloud-run/chatwork-webhook:latest"

      resources {
        limits = {
          memory = "1024Mi"  # メモリ上限 1GB
          cpu    = "1000m"   # CPU上限 1コア
        }
      }

      # タイムアウト設定（9分）
      # 注意: 環境変数・シークレットはCloud Buildで管理するため、ここには書かない
    }

    timeout = "540s"
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    # Cloud Buildが管理する設定はTerraformで変更しない
    # （Terraform=「存在」の管理、Cloud Build=デプロイ詳細の管理）
    ignore_changes = [
      template[0].containers[0].image,           # イメージはCloud Buildが更新
      template[0].containers[0].env,             # 環境変数はCloud Buildの--update-env-varsで管理
      template[0].containers[0].volume_mounts,   # ボリューム設定
      template[0].volumes,                       # ボリューム定義
      template[0].containers[0].resources,       # CPU/メモリはCloud Buildの--memory/--cpuで管理
      template[0].scaling,                       # スケーリングはCloud Buildの--min/--max-instancesで管理
      template[0].timeout,                       # タイムアウトはCloud Buildの--timeoutで管理
    ]
    prevent_destroy = true
  }
}

# chatwork-webhookを外部（チャットワーク）から呼べるようにする
resource "google_cloud_run_v2_service_iam_member" "chatwork_webhook_public" {
  location = google_cloud_run_v2_service.chatwork_webhook.location
  name     = google_cloud_run_v2_service.chatwork_webhook.name
  role     = "roles/run.invoker"
  member   = "allUsers"  # チャットワークからの呼び出しを許可（HMAC検証済み）
}

# ============================================================
# proactive-monitor サービス
# 定期的にタスクや会議をチェックする「監視役」
# ============================================================
resource "google_cloud_run_v2_service" "proactive_monitor" {
  name     = "proactive-monitor"
  location = var.region

  template {
    service_account = google_service_account.cloud_run_sa.email

    scaling {
      min_instance_count = 0  # 使わないときはゼロ台（コスト節約）
      max_instance_count = 5  # 最大5台まで拡張
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/cloud-run/proactive-monitor:latest"

      resources {
        limits = {
          memory = "512Mi"  # メモリ上限 512MB
          cpu    = "1000m"  # CPU上限 1コア
        }
      }
    }

    timeout = "540s"
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    # Cloud Buildが管理する設定はTerraformで変更しない
    ignore_changes = [
      template[0].containers[0].image,
      template[0].containers[0].env,
      template[0].containers[0].volume_mounts,
      template[0].volumes,
      template[0].containers[0].resources,
      template[0].scaling,
      template[0].timeout,
    ]
    prevent_destroy = true
  }
}

# proactive-monitorは内部からのみ呼び出し可能（セキュリティ上、外部公開しない）
resource "google_cloud_run_v2_service_iam_member" "proactive_monitor_invoker" {
  location = google_cloud_run_v2_service.proactive_monitor.location
  name     = google_cloud_run_v2_service.proactive_monitor.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}
