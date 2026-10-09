variable "name_prefix" {
  description = "Prefix for resource names, e.g. asc-dev."
  type        = string
}

variable "curated_bucket" {
  description = "Curated bucket holding the Iceberg warehouse."
  type        = string
}

variable "athena_results_bucket" {
  description = "Bucket for Athena query results."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key for catalog and query-result encryption."
  type        = string
}

variable "bytes_scanned_cutoff" {
  description = "Per-query scan limit in bytes (cost guardrail). Default 1 GiB."
  type        = number
  default     = 1073741824
}

variable "manage_catalog_encryption" {
  description = "Set the account-level Glue Data Catalog encryption (one per account/region)."
  type        = bool
  default     = true
}

variable "force_destroy" {
  description = "Allow destroying the workgroup with saved queries (dev only)."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
