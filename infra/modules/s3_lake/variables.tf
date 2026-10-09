variable "name_prefix" {
  description = "Prefix for resource names, e.g. asc-dev."
  type        = string
}

variable "bucket_suffix" {
  description = "Globally unique suffix for bucket names (e.g. the account ID)."
  type        = string
}

variable "account_id" {
  description = "AWS account ID that owns the buckets (used in the access-log bucket policy)."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key used for SSE-KMS on the data buckets."
  type        = string
}

variable "force_destroy" {
  description = "Allow destroying non-empty buckets (dev only)."
  type        = bool
  default     = false
}

variable "noncurrent_version_days" {
  description = "Days to keep noncurrent object versions."
  type        = number
  default     = 90
}

variable "athena_results_days" {
  description = "Days to keep Athena query results."
  type        = number
  default     = 7
}

variable "log_retention_days" {
  description = "Days to keep S3 server access logs."
  type        = number
  default     = 365
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
