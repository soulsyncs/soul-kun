################################################################################
# Variables
################################################################################

variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "soulkun-production"
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "asia-northeast1"
}

# Cloud SQL
variable "db_instance_name" {
  description = "Cloud SQL instance name"
  type        = string
  default     = "soulkun-db"
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "soulkun_tasks"
}

variable "db_user" {
  description = "Database user"
  type        = string
  default     = "soulkun_user"
}

variable "db_tier" {
  description = "Cloud SQL machine type"
  type        = string
  default     = "db-custom-1-3840"
}

variable "db_disk_size" {
  description = "Cloud SQL disk size in GB"
  type        = number
  default     = 10
}

# Cloud Functions common
variable "functions_runtime" {
  description = "Cloud Functions runtime"
  type        = string
  default     = "python311"
}

# Environment
variable "cors_origins" {
  description = "Allowed CORS origins"
  type        = string
  default     = "https://org-chart.soulsyncs.jp,https://soulsyncs.jp,http://localhost:3000,http://localhost:8080"
}

# Organization IDs
variable "supabase_org_id" {
  description = "Supabase organization ID (users table)"
  type        = string
  default     = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
}

variable "cloudsql_org_id" {
  description = "Cloud SQL organization ID (org_chart)"
  type        = string
  default     = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
}

# Supabase
variable "supabase_url" {
  description = "Supabase project URL"
  type        = string
  default     = "https://adzxpeboaoiojepcxlyc.supabase.co"
}

# GCS
variable "meeting_recordings_bucket" {
  description = "GCS bucket for meeting recordings"
  type        = string
  default     = "soulkun-meeting-recordings"
}

variable "terraform_state_bucket" {
  description = "GCS bucket for Terraform state"
  type        = string
  default     = "soulkun-terraform-state"
}

# ChatWork
variable "chatwork_dm_room_id" {
  description = "ChatWork DM room ID"
  type        = string
  default     = "417892193"
}

# Google Drive
variable "root_folder_id" {
  description = "Root Google Drive folder ID for knowledge base"
  type        = string
  default     = "1Bw03U0rmjnkAYeFQDEFB75EsouNaOysp"
}

# Pinecone
variable "pinecone_index_name" {
  description = "Pinecone vector index name"
  type        = string
  default     = "soulkun-knowledge"
}
