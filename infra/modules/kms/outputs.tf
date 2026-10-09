output "key_arn" {
  description = "ARN of the project KMS key."
  value       = aws_kms_key.this.arn
}

output "key_id" {
  description = "ID of the project KMS key."
  value       = aws_kms_key.this.key_id
}
