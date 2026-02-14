################################################################################
# Outputs
################################################################################

output "cloud_sql_connection_name" {
  description = "Cloud SQL instance connection name"
  value       = google_sql_database_instance.main.connection_name
}

output "cloud_sql_ip" {
  description = "Cloud SQL public IP"
  value       = google_sql_database_instance.main.public_ip_address
}

output "function_urls" {
  description = "Cloud Functions HTTP trigger URLs"
  value = {
    for name, fn in google_cloudfunctions2_function.functions :
    name => fn.service_config[0].uri
  }
}

output "meeting_recordings_bucket" {
  description = "GCS bucket for meeting recordings"
  value       = google_storage_bucket.meeting_recordings.url
}

output "cloud_functions_sa_email" {
  description = "Cloud Functions service account email"
  value       = google_service_account.cloud_functions.email
}

output "scheduler_invoker_sa_email" {
  description = "Scheduler invoker service account email"
  value       = google_service_account.scheduler_invoker.email
}
