# Glue Data Catalog (Iceberg tables are registered by pyiceberg's GlueCatalog at runtime and by
# dbt-athena for the marts) and an Athena workgroup with enforced encryption and a per-query
# scan limit as a cost guardrail.
locals {
  databases = {
    silver       = "Conformed Iceberg tables written by the BuildSilver Lambda"
    gold         = "Gold Iceberg tables (marts exported by BuildMarts, graph outputs)"
    staging      = "dbt staging views (Athena target)"
    intermediate = "dbt intermediate views (Athena target)"
    marts        = "dbt marts as Iceberg tables (Athena target)"
  }
}

resource "aws_glue_catalog_database" "this" {
  for_each     = local.databases
  name         = "asc_${each.key}"
  description  = each.value
  location_uri = "s3://${var.curated_bucket}/warehouse/${each.key}"
  tags         = var.tags
}

resource "aws_glue_data_catalog_encryption_settings" "this" {
  count = var.manage_catalog_encryption ? 1 : 0
  data_catalog_encryption_settings {
    connection_password_encryption {
      return_connection_password_encrypted = true
      aws_kms_key_id                       = var.kms_key_arn
    }
    encryption_at_rest {
      catalog_encryption_mode = "SSE-KMS"
      sse_aws_kms_key_id      = var.kms_key_arn
    }
  }
}

resource "aws_athena_workgroup" "this" {
  name          = "${var.name_prefix}-analytics"
  description   = "dbt-athena and ad-hoc queries over the Iceberg lake"
  force_destroy = var.force_destroy

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.bytes_scanned_cutoff

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    result_configuration {
      output_location = "s3://${var.athena_results_bucket}/results/"
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = var.kms_key_arn
      }
    }
  }

  tags = var.tags
}
