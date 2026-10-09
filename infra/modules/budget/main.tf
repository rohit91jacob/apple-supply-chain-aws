# Cost guardrail: a monthly budget scoped to this project's cost-allocation tag, alerting at
# 50% / 80% actual and 100% forecast spend to SNS (and optionally email).
resource "aws_budgets_budget" "monthly" {
  name         = "${var.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = format("%.2f", var.monthly_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = [format("user:project$%s", var.project_tag)] # TagKeyValue uses "$" as separator
  }

  dynamic "notification" {
    for_each = { actual50 = ["ACTUAL", 50], actual80 = ["ACTUAL", 80], forecast100 = ["FORECASTED", 100] }
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value[1]
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value[0]
      subscriber_sns_topic_arns  = [var.sns_topic_arn]
      subscriber_email_addresses = var.alert_email == "" ? [] : [var.alert_email]
    }
  }

  tags = var.tags
}
