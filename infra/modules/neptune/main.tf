# Optional Amazon Neptune Serverless cluster for the supplier graph (cloud mapping of the local
# networkx graph). The pipeline writes Gremlin bulk-load CSVs to s3://<curated>/neptune/; the
# loader role below lets Neptune read them. Disabled by default (enable_neptune = false in the
# root module) because even a minimal serverless cluster costs money while idle.
resource "aws_neptune_subnet_group" "this" {
  name       = "${var.name_prefix}-graph"
  subnet_ids = var.subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-graph"
  description = "Neptune: Gremlin/HTTPS from the allowed security groups only"
  vpc_id      = var.vpc_id
  tags        = var.tags
}

resource "aws_vpc_security_group_ingress_rule" "gremlin" {
  for_each                     = toset(var.allowed_security_group_ids)
  security_group_id            = aws_security_group.this.id
  description                  = "Gremlin/openCypher over TLS from an allowed client security group"
  ip_protocol                  = "tcp"
  from_port                    = 8182
  to_port                      = 8182
  referenced_security_group_id = each.value
}

data "aws_iam_policy_document" "loader_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "loader" {
  name               = "${var.name_prefix}-neptune-loader"
  assume_role_policy = data.aws_iam_policy_document.loader_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "loader" {
  statement {
    sid       = "ReadBulkLoadFiles"
    actions   = ["s3:GetObject"]
    resources = ["${var.curated_bucket_arn}/neptune/*"]
  }
  statement {
    sid       = "ListBulkLoadPrefix"
    actions   = ["s3:ListBucket"]
    resources = [var.curated_bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["neptune/*"]
    }
  }
  statement {
    sid       = "DecryptBulkLoadFiles"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "loader" {
  name   = "read-bulk-load"
  role   = aws_iam_role.loader.id
  policy = data.aws_iam_policy_document.loader.json
}

resource "aws_neptune_cluster_parameter_group" "this" {
  name        = "${var.name_prefix}-graph"
  family      = "neptune1.4"
  description = "Audit logging on"
  parameter {
    name  = "neptune_enable_audit_log"
    value = "1"
  }
  tags = var.tags
}

resource "aws_neptune_cluster" "this" {
  cluster_identifier                   = "${var.name_prefix}-graph"
  engine                               = "neptune"
  engine_version                       = var.engine_version
  neptune_subnet_group_name            = aws_neptune_subnet_group.this.name
  vpc_security_group_ids               = [aws_security_group.this.id]
  neptune_cluster_parameter_group_name = aws_neptune_cluster_parameter_group.this.name
  iam_roles                            = [aws_iam_role.loader.arn]
  iam_database_authentication_enabled  = true
  storage_encrypted                    = true
  kms_key_arn                          = var.kms_key_arn
  backup_retention_period              = 7
  preferred_backup_window              = "03:00-04:00"
  deletion_protection                  = var.deletion_protection
  skip_final_snapshot                  = !var.deletion_protection
  final_snapshot_identifier            = "${var.name_prefix}-graph-final"
  copy_tags_to_snapshot                = true
  enable_cloudwatch_logs_exports       = ["audit"]
  apply_immediately                    = true

  serverless_v2_scaling_configuration {
    min_capacity = var.min_ncu
    max_capacity = var.max_ncu
  }

  tags = var.tags
}

resource "aws_neptune_cluster_instance" "this" {
  identifier                   = "${var.name_prefix}-graph-1"
  cluster_identifier           = aws_neptune_cluster.this.id
  instance_class               = "db.serverless"
  auto_minor_version_upgrade   = true
  neptune_subnet_group_name    = aws_neptune_subnet_group.this.name
  publicly_accessible          = false
  preferred_maintenance_window = "sun:04:00-sun:05:00"
  tags                         = var.tags
}
