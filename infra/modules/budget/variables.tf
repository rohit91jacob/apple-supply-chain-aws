variable "name_prefix" {
  description = "Prefix for resource names, e.g. asc-dev."
  type        = string
}

variable "monthly_limit_usd" {
  description = "Monthly budget in USD."
  type        = number
  default     = 10
}

variable "project_tag" {
  description = "Value of the 'project' cost-allocation tag to scope the budget."
  type        = string
}

variable "sns_topic_arn" {
  description = "SNS topic for budget alerts."
  type        = string
}

variable "alert_email" {
  description = "Optional email for budget alerts."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
