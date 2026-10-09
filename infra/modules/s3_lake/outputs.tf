output "bucket_names" {
  description = "Bucket names keyed by role (raw, curated, athena)."
  value       = { for k, b in aws_s3_bucket.this : k => b.bucket }
}

output "bucket_arns" {
  description = "Bucket ARNs keyed by role (raw, curated, athena)."
  value       = { for k, b in aws_s3_bucket.this : k => b.arn }
}

output "access_log_bucket" {
  description = "Name of the S3 access-log bucket."
  value       = aws_s3_bucket.logs.bucket
}
