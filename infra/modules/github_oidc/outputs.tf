output "deploy_role_arn" {
  description = "Role ARN to store as the AWS_DEPLOY_ROLE_ARN repository variable."
  value       = aws_iam_role.deploy.arn
}
