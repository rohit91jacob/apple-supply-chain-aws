variable "region" {
  description = "AWS region."
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Environment name (part of every resource name)."
  type        = string
  default     = "dev"
}

variable "image_tag" {
  description = "Tag of the pipeline image in ECR (pushed by .github/workflows/deploy.yml)."
  type        = string
  default     = "bootstrap"
}

variable "sec_user_agent" {
  description = "Descriptive User-Agent for SEC EDGAR requests: \"Name contact@example.com\"."
  type        = string
  default     = "apple-supply-chain-aws admin@example.com"
}

variable "census_key_ssm_parameter" {
  description = "Optional SSM SecureString name holding a US Census API key (empty = source skipped)."
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget in USD."
  type        = number
  default     = 10
}

variable "alert_email" {
  description = "Optional email for pipeline-failure and budget alerts."
  type        = string
  default     = ""
}

variable "schedule_enabled" {
  description = "Enable the weekly pipeline schedule."
  type        = bool
  default     = true
}

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to deploy via OIDC."
  type        = string
  default     = "rohit91jacob/apple-supply-chain-aws"
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC provider (set false if the account already has one)."
  type        = bool
  default     = true
}

variable "existing_github_oidc_provider_arn" {
  description = "Existing GitHub OIDC provider ARN when create_github_oidc_provider = false."
  type        = string
  default     = ""
}

variable "enable_neptune" {
  description = "Create the optional Neptune Serverless graph cluster (incurs idle cost)."
  type        = bool
  default     = false
}

variable "neptune_vpc_id" {
  description = "VPC for Neptune (required when enable_neptune = true)."
  type        = string
  default     = ""
}

variable "neptune_subnet_ids" {
  description = "Private subnets for Neptune (required when enable_neptune = true)."
  type        = list(string)
  default     = []
}

variable "force_destroy" {
  description = "Allow destroying non-empty buckets / repositories (dev only)."
  type        = bool
  default     = false
}
