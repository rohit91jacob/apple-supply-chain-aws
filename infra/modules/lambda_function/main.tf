# One pipeline Lambda: container image, its own least-privilege role, an encrypted log group,
# an encrypted dead-letter queue, X-Ray tracing and a concurrency cap.
data "aws_partition" "current" {}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = var.tags
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.function_name}-dlq"
  kms_master_key_id         = var.kms_key_arn
  message_retention_seconds = 1209600
  tags                      = var.tags
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name                 = var.function_name
  assume_role_policy   = data.aws_iam_policy_document.assume.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = var.tags
}

data "aws_iam_policy_document" "base" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }
  statement {
    sid       = "DeadLetterQueue"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
  statement {
    sid       = "UseProjectKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "base" {
  name   = "base"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.base.json
}

resource "aws_iam_role_policy" "extra" {
  count  = var.policy_json == null ? 0 : 1
  name   = "data-access"
  role   = aws_iam_role.this.id
  policy = var.policy_json
}

# X-Ray's PutTraceSegments cannot be scoped to a resource; the AWS managed policy grants
# exactly the trace-write actions.
resource "aws_iam_role_policy_attachment" "xray" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_lambda_function" "this" {
  #checkov:skip=CKV_AWS_117:Extractors call public internet APIs (SEC, UN Comtrade, apple.com); a VPC would need a NAT gateway (~USD 32/month) for no security gain on public data.
  #checkov:skip=CKV_AWS_272:Code signing applies to zip packages only; this is a container-image function (image scanned on push to an immutable-tag ECR repository).
  function_name                  = var.function_name
  description                    = var.description
  role                           = aws_iam_role.this.arn
  package_type                   = "Image"
  image_uri                      = var.image_uri
  architectures                  = ["arm64"]
  memory_size                    = var.memory_mb
  timeout                        = var.timeout_seconds
  reserved_concurrent_executions = var.reserved_concurrency
  kms_key_arn                    = var.kms_key_arn

  ephemeral_storage {
    size = var.ephemeral_storage_mb
  }

  image_config {
    command = [var.handler]
  }

  environment {
    variables = var.environment
  }

  tracing_config {
    mode = "Active"
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.this.name
  }

  tags = var.tags

  depends_on = [aws_iam_role_policy.base, aws_cloudwatch_log_group.this]
}
