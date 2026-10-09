variable "name_prefix" {
  description = "Prefix for resource names, e.g. asc-dev."
  type        = string
}

variable "definition_path" {
  description = "Path to the ASL definition (src/apple_supply_chain/orchestration/state_machine.asl.json)."
  type        = string
}

variable "function_arns" {
  description = "Map of ASL placeholder (e.g. build_silver_arn) to Lambda function ARN."
  type        = map(string)
}

variable "kms_key_arn" {
  description = "KMS key for logs, SNS, the scheduler and state machine data."
  type        = string
}

variable "schedule_expression" {
  description = "EventBridge Scheduler expression (UTC)."
  type        = string
  default     = "cron(0 6 ? * MON *)"
}

variable "schedule_enabled" {
  description = "Whether the weekly schedule is enabled."
  type        = bool
  default     = true
}

variable "alert_email" {
  description = "Optional email address subscribed to failure alerts."
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for state machine logs."
  type        = number
  default     = 365
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
