################################################################################
# Cloud Storage — GCS バケット
################################################################################

# 会議録音・トランスクリプト保存用バケット
resource "google_storage_bucket" "meeting_recordings" {
  name          = var.meeting_recordings_bucket
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = 90 # 90日後に自動削除
    }
    action {
      type = "Delete"
    }
  }

  versioning {
    enabled = false
  }
}

# Terraform state バケット
resource "google_storage_bucket" "terraform_state" {
  name          = var.terraform_state_bucket
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true

  versioning {
    enabled = true # state ファイルのバージョニングは必須
  }
}
