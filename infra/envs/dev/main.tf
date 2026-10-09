# apple-supply-chain-aws: the cloud mapping of the local pipeline.
#
#   EventBridge Scheduler (weekly) -> Step Functions -> 9 Lambda functions (one container image)
#   -> S3 raw zone -> Iceberg tables in the Glue Data Catalog (curated bucket) -> dbt marts
#   -> graph outputs + Neptune bulk-load files -> (optional) Neptune Serverless.
#
# This configuration is validated in CI (fmt, validate, tflint, checkov) but never applied
# from CI. Nothing here has been deployed by the author; see README "Cloud mapping".
data "aws_caller_identity" "current" {}

locals {
  name_prefix = "asc-${var.environment}"
  tags = {
    project     = "apple-supply-chain-aws"
    environment = var.environment
    managed_by  = "terraform"
    repository  = var.github_repository
  }
  image_uri = "${module.ecr.repository_url}:${var.image_tag}"

  common_env = {
    ASC_STORE            = "s3"
    ASC_CATALOG          = "glue"
    ASC_NAMESPACE_PREFIX = "asc_"
    ASC_RAW_BUCKET       = module.lake.bucket_names["raw"]
    ASC_CURATED_BUCKET   = module.lake.bucket_names["curated"]
    ASC_WAREHOUSE        = "s3://${module.lake.bucket_names["curated"]}/warehouse"
    ASC_DATA_DIR         = "/tmp/asc"
    ASC_LOG_FORMAT       = "json"
    ASC_DBT_DIR          = "/var/task/dbt"
    SEC_USER_AGENT       = var.sec_user_agent
  }

  # placeholder in state_machine.asl.json -> function settings
  functions = {
    extract_sec_edgar_arn           = { handler = "extract_sec_edgar", memory = 1024, storage = 512, data = "raw_write" }
    extract_apple_supplier_list_arn = { handler = "extract_apple_supplier_list", memory = 1024, storage = 512, data = "raw_write" }
    extract_un_comtrade_arn         = { handler = "extract_un_comtrade", memory = 512, storage = 512, data = "raw_write" }
    extract_us_census_arn           = { handler = "extract_us_census", memory = 512, storage = 512, data = "raw_write" }
    build_silver_arn                = { handler = "build_silver", memory = 3008, storage = 2048, data = "silver_write" }
    check_silver_arn                = { handler = "check_silver", memory = 2048, storage = 1024, data = "lake_read" }
    build_marts_arn                 = { handler = "build_marts", memory = 3008, storage = 4096, data = "gold_write" }
    build_graph_arn                 = { handler = "build_graph", memory = 2048, storage = 2048, data = "gold_write" }
    check_gold_arn                  = { handler = "check_gold", memory = 2048, storage = 2048, data = "lake_read" }
  }

  raw_arn     = module.lake.bucket_arns["raw"]
  curated_arn = module.lake.bucket_arns["curated"]
  glue_prefix = "arn:aws:glue:${var.region}:${data.aws_caller_identity.current.account_id}"
}

module "kms" {
  source      = "../../modules/kms"
  name_prefix = local.name_prefix
  tags        = local.tags
}

module "lake" {
  source        = "../../modules/s3_lake"
  name_prefix   = local.name_prefix
  bucket_suffix = data.aws_caller_identity.current.account_id
  account_id    = data.aws_caller_identity.current.account_id
  kms_key_arn   = module.kms.key_arn
  force_destroy = var.force_destroy
  tags          = local.tags
}

module "ecr" {
  source       = "../../modules/ecr"
  name_prefix  = local.name_prefix
  kms_key_arn  = module.kms.key_arn
  force_delete = var.force_destroy
  tags         = local.tags
}

module "analytics" {
  source                = "../../modules/analytics"
  name_prefix           = local.name_prefix
  curated_bucket        = module.lake.bucket_names["curated"]
  athena_results_bucket = module.lake.bucket_names["athena"]
  kms_key_arn           = module.kms.key_arn
  force_destroy         = var.force_destroy
  tags                  = local.tags
}

# ------------------------------------------------------------ least-privilege data access
data "aws_iam_policy_document" "raw_write" {
  statement {
    sid       = "ListRaw"
    actions   = ["s3:ListBucket"]
    resources = [local.raw_arn]
  }
  statement {
    sid       = "ReadWriteRawObjects"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${local.raw_arn}/*"]
  }
  dynamic "statement" {
    for_each = var.census_key_ssm_parameter == "" ? [] : [1]
    content {
      sid       = "ReadCensusKey"
      actions   = ["ssm:GetParameter"]
      resources = ["arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${trimprefix(var.census_key_ssm_parameter, "/")}"]
    }
  }
}

data "aws_iam_policy_document" "lake" {
  for_each = toset(["silver_write", "gold_write", "lake_read"])

  statement {
    sid       = "ListLake"
    actions   = ["s3:ListBucket"]
    resources = [local.raw_arn, local.curated_arn]
  }
  statement {
    sid       = "ReadLake"
    actions   = ["s3:GetObject"]
    resources = ["${local.raw_arn}/*", "${local.curated_arn}/*"]
  }
  dynamic "statement" {
    for_each = each.key == "lake_read" ? [] : [1]
    content {
      sid       = "WriteCurated"
      actions   = ["s3:PutObject", "s3:DeleteObject"]
      resources = ["${local.curated_arn}/warehouse/*", "${local.curated_arn}/neptune/*"]
    }
  }
  statement {
    sid       = "ReadCatalog"
    actions   = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables"]
    resources = ["${local.glue_prefix}:catalog", "${local.glue_prefix}:database/asc_*", "${local.glue_prefix}:table/asc_*/*"]
  }
  dynamic "statement" {
    for_each = each.key == "lake_read" ? [] : [1]
    content {
      sid       = "WriteCatalog"
      actions   = ["glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable", "glue:CreateDatabase"]
      resources = ["${local.glue_prefix}:catalog", "${local.glue_prefix}:database/asc_${each.key == "silver_write" ? "silver" : "gold"}", "${local.glue_prefix}:table/asc_${each.key == "silver_write" ? "silver" : "gold"}/*"]
    }
  }
}

module "functions" {
  source   = "../../modules/lambda_function"
  for_each = local.functions

  function_name        = "${local.name_prefix}-${replace(trimsuffix(each.key, "_arn"), "_", "-")}"
  description          = "apple-supply-chain-aws ${each.value.handler}"
  image_uri            = local.image_uri
  handler              = "apple_supply_chain.lambdas.handlers.${each.value.handler}"
  memory_mb            = each.value.memory
  ephemeral_storage_mb = each.value.storage
  timeout_seconds      = 900
  reserved_concurrency = 2
  kms_key_arn          = module.kms.key_arn
  environment = merge(
    local.common_env,
    each.key == "extract_us_census_arn" && var.census_key_ssm_parameter != "" ? { ASC_CENSUS_KEY_SSM_PARAMETER = var.census_key_ssm_parameter } : {}
  )
  policy_json = each.value.data == "raw_write" ? data.aws_iam_policy_document.raw_write.json : data.aws_iam_policy_document.lake[each.value.data].json
  tags        = local.tags
}

module "pipeline" {
  source           = "../../modules/pipeline"
  name_prefix      = local.name_prefix
  definition_path  = "${path.module}/../../../src/apple_supply_chain/orchestration/state_machine.asl.json"
  function_arns    = { for k, m in module.functions : k => m.function_arn }
  kms_key_arn      = module.kms.key_arn
  schedule_enabled = var.schedule_enabled
  alert_email      = var.alert_email
  tags             = local.tags
}

module "budget" {
  source            = "../../modules/budget"
  name_prefix       = local.name_prefix
  monthly_limit_usd = var.monthly_budget_usd
  project_tag       = local.tags.project
  sns_topic_arn     = module.pipeline.alerts_topic_arn
  alert_email       = var.alert_email
  tags              = local.tags
}

module "github_oidc" {
  source                     = "../../modules/github_oidc"
  name_prefix                = local.name_prefix
  github_repository          = var.github_repository
  create_oidc_provider       = var.create_github_oidc_provider
  existing_oidc_provider_arn = var.existing_github_oidc_provider_arn
  ecr_repository_arn         = module.ecr.repository_arn
  function_arns              = [for m in module.functions : m.function_arn]
  state_machine_arn          = module.pipeline.state_machine_arn
  kms_key_arn                = module.kms.key_arn
  tags                       = local.tags
}

module "neptune" {
  source             = "../../modules/neptune"
  count              = var.enable_neptune ? 1 : 0
  name_prefix        = local.name_prefix
  vpc_id             = var.neptune_vpc_id
  subnet_ids         = var.neptune_subnet_ids
  curated_bucket_arn = local.curated_arn
  kms_key_arn        = module.kms.key_arn
  tags               = local.tags
}
