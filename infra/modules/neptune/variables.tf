variable "name_prefix" {
  description = "Prefix for resource names, e.g. asc-dev."
  type        = string
}

variable "vpc_id" {
  description = "VPC for the Neptune cluster."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs (at least two AZs)."
  type        = list(string)
}

variable "allowed_security_group_ids" {
  description = "Security groups allowed to reach Neptune on 8182."
  type        = list(string)
  default     = []
}

variable "curated_bucket_arn" {
  description = "Curated bucket ARN holding neptune/ bulk-load files."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key for storage encryption."
  type        = string
}

variable "engine_version" {
  description = "Neptune engine version."
  type        = string
  default     = "1.4.5.1"
}

variable "min_ncu" {
  description = "Minimum Neptune capacity units (serverless)."
  type        = number
  default     = 1
}

variable "max_ncu" {
  description = "Maximum Neptune capacity units (serverless; cost guardrail)."
  type        = number
  default     = 2.5
}

variable "deletion_protection" {
  description = "Protect the cluster from deletion."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
