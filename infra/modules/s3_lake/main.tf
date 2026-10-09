# The lake buckets: raw (immutable landing zone), curated (Iceberg warehouse + Neptune
# bulk-load files) and athena (query results). All are private, versioned, SSE-KMS encrypted,
# TLS-only, access-logged and lifecycle-managed.
locals {
  buckets = {
    raw     = { name = "${var.name_prefix}-raw-${var.bucket_suffix}", results = false }
    curated = { name = "${var.name_prefix}-curated-${var.bucket_suffix}", results = false }
    athena  = { name = "${var.name_prefix}-athena-results-${var.bucket_suffix}", results = true }
  }
}

# ------------------------------------------------------------------ access logs
resource "aws_s3_bucket" "logs" {
  #checkov:skip=CKV_AWS_18:This is the access-log target bucket; logging it to itself would loop.
  #checkov:skip=CKV_AWS_144:Single-region portfolio deployment; replicating access logs would double their storage cost.
  #checkov:skip=CKV_AWS_145:S3 server access logging does not support SSE-KMS target buckets, so SSE-S3 (AES256) is used.
  #checkov:skip=CKV2_AWS_62:No event-driven processing of access logs.
  bucket        = "${var.name_prefix}-access-logs-${var.bucket_suffix}"
  force_destroy = var.force_destroy
  tags          = merge(var.tags, { "asc:bucket-role" = "access-logs" })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "logs" {
  bucket = aws_s3_bucket.logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    id     = "expire-access-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = var.log_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "logs" {
  statement {
    sid       = "S3ServerAccessLogs"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.logs.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.logs.arn, "${aws_s3_bucket.logs.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "logs" {
  bucket = aws_s3_bucket.logs.id
  policy = data.aws_iam_policy_document.logs.json
}

# ------------------------------------------------------------------ data buckets
resource "aws_s3_bucket" "this" {
  #checkov:skip=CKV_AWS_144:Single-region portfolio deployment; every raw object can be re-downloaded from the public sources, so replication is not worth the cost.
  #checkov:skip=CKV2_AWS_62:Processing is orchestrated by the scheduled state machine, not by S3 event notifications.
  for_each      = local.buckets
  bucket        = each.value.name
  force_destroy = var.force_destroy
  tags          = merge(var.tags, { "asc:bucket-role" = each.key })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = local.buckets
  bucket                  = aws_s3_bucket.this[each.key].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_logging" "this" {
  for_each      = local.buckets
  bucket        = aws_s3_bucket.this[each.key].id
  target_bucket = aws_s3_bucket.logs.id
  target_prefix = "s3/${each.key}/"
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id

  rule {
    id     = "housekeeping"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  dynamic "rule" {
    for_each = each.value.results ? [1] : []
    content {
      id     = "expire-query-results"
      status = "Enabled"
      filter {}
      expiration {
        days = var.athena_results_days
      }
      abort_incomplete_multipart_upload {
        days_after_initiation = 7
      }
    }
  }

  dynamic "rule" {
    for_each = each.key == "raw" ? [1] : []
    content {
      id     = "raw-to-infrequent-access"
      status = "Enabled"
      filter {}
      transition {
        days          = 30
        storage_class = "STANDARD_IA"
      }
      abort_incomplete_multipart_upload {
        days_after_initiation = 7
      }
    }
  }
}

data "aws_iam_policy_document" "tls_only" {
  for_each = local.buckets
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.this[each.key].arn, "${aws_s3_bucket.this[each.key].arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id
  policy   = data.aws_iam_policy_document.tls_only[each.key].json
}
