variable "function_name" {
  description = "Lambda function name (also used for its role, log group and DLQ)."
  type        = string
}

variable "description" {
  description = "Human-readable description."
  type        = string
  default     = ""
}

variable "image_uri" {
  description = "Container image URI (ECR) with tag or digest."
  type        = string
}

variable "handler" {
  description = "Python handler inside the image, e.g. apple_supply_chain.lambdas.handlers.extract_sec_edgar."
  type        = string
}

variable "memory_mb" {
  description = "Memory size in MB."
  type        = number
  default     = 1024
}

variable "timeout_seconds" {
  description = "Function timeout in seconds."
  type        = number
  default     = 900
}

variable "ephemeral_storage_mb" {
  description = "Size of /tmp in MB (DuckDB warehouse and dbt artifacts)."
  type        = number
  default     = 1024
}

variable "reserved_concurrency" {
  description = "Reserved concurrency (also a cost guardrail)."
  type        = number
  default     = 2
}

variable "environment" {
  description = "Environment variables (ASC_* settings). No secrets."
  type        = map(string)
  default     = {}
}

variable "policy_json" {
  description = "Least-privilege data-access policy for this function, or null."
  type        = string
  default     = null
}

variable "kms_key_arn" {
  description = "KMS key for logs, DLQ and environment variables."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention."
  type        = number
  default     = 365
}

variable "permissions_boundary_arn" {
  description = "Optional IAM permissions boundary for the function role."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
