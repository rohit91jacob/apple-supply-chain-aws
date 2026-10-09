output "glue_databases" {
  description = "Glue database names keyed by layer."
  value       = { for k, d in aws_glue_catalog_database.this : k => d.name }
}

output "athena_workgroup" {
  description = "Athena workgroup name."
  value       = aws_athena_workgroup.this.name
}
