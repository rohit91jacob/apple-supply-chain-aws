variable "name_prefix" {
  description = "Prefix for resource names, e.g. asc-dev."
  type        = string
}

variable "github_repository" {
  description = "owner/name of the GitHub repository allowed to assume the role."
  type        = string
}

variable "github_environment" {
  description = "GitHub environment whose jobs may assume the role."
  type        = string
  default     = "aws-dev"
}

variable "create_oidc_provider" {
  description = "Create the GitHub OIDC provider (only one per account)."
  type        = bool
  default     = true
}

variable "existing_oidc_provider_arn" {
  description = "ARN of an existing GitHub OIDC provider when create_oidc_provider = false."
  type        = string
  default     = ""
}

variable "ecr_repository_arn" {
  description = "ECR repository the workflow pushes to."
  type        = string
}

variable "function_arns" {
  description = "Pipeline Lambda ARNs the workflow may repoint at a new image."
  type        = list(string)
}

variable "state_machine_arn" {
  description = "State machine the workflow may start."
  type        = string
}

variable "kms_key_arn" {
  description = "Project KMS key (ECR encryption)."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
