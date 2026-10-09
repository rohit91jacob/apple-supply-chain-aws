output "state_machine_arn" {
  description = "Step Functions state machine ARN."
  value       = aws_sfn_state_machine.this.arn
}

output "alerts_topic_arn" {
  description = "SNS topic receiving pipeline failure alerts."
  value       = aws_sns_topic.alerts.arn
}

output "schedule_name" {
  description = "Name of the weekly EventBridge schedule."
  value       = aws_scheduler_schedule.weekly.name
}
