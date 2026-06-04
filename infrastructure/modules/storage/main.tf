variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "cors_allowed_origins" {
  description = "Allowed origins for S3 CORS configuration"
  type        = list(string)
  default     = ["https://app.onpremai.com"]
}

locals {
  name_prefix = "${var.project}-${var.environment}"
  bucket_name = "${var.project}-${var.environment}-artifacts"
}

# --- S3 Bucket ---
resource "aws_s3_bucket" "artifacts" {
  bucket = local.bucket_name

  tags = {
    Name = local.bucket_name
  }
}

# --- Versioning ---
resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

# --- Encryption ---
resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

# --- Block Public Access ---
resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- Lifecycle Rules ---
resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "transition-to-ia"
    status = "Enabled"

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 365
      storage_class = "GLACIER"
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "abort-multipart"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# --- CORS Configuration (for direct uploads) ---
resource "aws_s3_bucket_cors_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST"]
    allowed_origins = var.cors_allowed_origins
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

# --- Tenant-Scoped IAM Policy ---
data "aws_iam_policy_document" "tenant_scoped_s3" {
  statement {
    sid    = "TenantScopedAccess"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]

    resources = [
      "${aws_s3_bucket.artifacts.arn}/$${aws:PrincipalTag/tenant_id}/*",
    ]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["$${aws:PrincipalTag/tenant_id}/*"]
    }
  }

  statement {
    sid    = "TenantScopedList"
    effect = "Allow"

    actions = [
      "s3:ListBucket",
    ]

    resources = [
      aws_s3_bucket.artifacts.arn,
    ]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["$${aws:PrincipalTag/tenant_id}/*"]
    }
  }
}

resource "aws_iam_policy" "tenant_scoped_s3" {
  name   = "${local.name_prefix}-tenant-scoped-s3"
  policy = data.aws_iam_policy_document.tenant_scoped_s3.json

  tags = {
    Name = "${local.name_prefix}-tenant-scoped-s3-policy"
  }
}

# --- Outputs ---
output "bucket_name" {
  value = aws_s3_bucket.artifacts.id
}

output "bucket_arn" {
  value = aws_s3_bucket.artifacts.arn
}

output "tenant_policy_arn" {
  value = aws_iam_policy.tenant_scoped_s3.arn
}
