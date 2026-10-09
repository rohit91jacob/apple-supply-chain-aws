output "cluster_endpoint" {
  description = "Neptune writer endpoint."
  value       = aws_neptune_cluster.this.endpoint
}

output "loader_role_arn" {
  description = "IAM role Neptune assumes for bulk loads from S3."
  value       = aws_iam_role.loader.arn
}
