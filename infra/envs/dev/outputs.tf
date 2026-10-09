output "buckets" {
  description = "Lake bucket names (raw, curated, athena)."
  value       = module.lake.bucket_names
}

output "ecr_repository_url" {
  description = "Push the pipeline image here (docker/lambda.Dockerfile)."
  value       = module.ecr.repository_url
}

output "state_machine_arn" {
  description = "Step Functions state machine ARN."
  value       = module.pipeline.state_machine_arn
}

output "athena_workgroup" {
  description = "Athena workgroup for dbt-athena (DBT_TARGET=athena)."
  value       = module.analytics.athena_workgroup
}

output "glue_databases" {
  description = "Glue databases for the Iceberg layers."
  value       = module.analytics.glue_databases
}

output "github_deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN repository variable to enable deploy.yml."
  value       = module.github_oidc.deploy_role_arn
}

output "neptune_endpoint" {
  description = "Neptune writer endpoint (null unless enable_neptune = true)."
  value       = var.enable_neptune ? module.neptune[0].cluster_endpoint : null
}
