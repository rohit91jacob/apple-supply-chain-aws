# GitHub Actions -> AWS with OIDC federation (no static keys). The role can only be assumed
# from this repository's `aws-dev` environment, and it can only: push the pipeline image to
# its ECR repository, point the pipeline Lambdas at a new image, and start the state machine.
# Infrastructure changes (terraform apply) stay a manual, reviewed step.

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  tags           = var.tags
}

locals {
  provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.existing_oidc_provider_arn
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${var.github_environment}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${var.name_prefix}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.assume.json
  max_session_duration = 3600
  tags                 = var.tags
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # GetAuthorizationToken has no resource-level permissions
  }
  statement {
    sid = "PushPipelineImage"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [var.ecr_repository_arn]
  }
  statement {
    sid       = "UpdatePipelineFunctions"
    actions   = ["lambda:UpdateFunctionCode", "lambda:GetFunction", "lambda:GetFunctionConfiguration"]
    resources = var.function_arns
  }
  statement {
    sid       = "RunPipeline"
    actions   = ["states:StartExecution", "states:DescribeExecution"]
    resources = [var.state_machine_arn, "${replace(var.state_machine_arn, ":stateMachine:", ":execution:")}:*"]
  }
  statement {
    sid       = "EncryptImageLayers"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "deploy" {
  #checkov:skip=CKV_AWS_290:Only ecr:GetAuthorizationToken uses Resource "*" (the API has no resource-level permissions); every write action is scoped to named resources.
  #checkov:skip=CKV_AWS_355:Same - the single "*" statement is the read-only ECR token call.
  name   = "deploy-image"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
