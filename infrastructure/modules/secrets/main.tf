variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "rds_endpoint" {
  type = string
}

locals {
  name_prefix = "${var.project}-${var.environment}"
}

# --- Database URL Secret ---
resource "aws_secretsmanager_secret" "database_url" {
  name        = "${local.name_prefix}/database-url"
  description = "PostgreSQL connection string for ${var.project} ${var.environment}"

  recovery_window_in_days = var.environment == "prod" ? 30 : 7

  tags = {
    Name = "${local.name_prefix}-database-url"
  }
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id

  # Placeholder - actual value set during deploy or via rotation
  secret_string = jsonencode({
    host     = split(":", var.rds_endpoint)[0]
    port     = 5432
    dbname   = "onpremai"
    username = "onpremai_admin"
    password = "REPLACE_ME_DURING_DEPLOY"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# --- LLM API Keys Secret ---
resource "aws_secretsmanager_secret" "llm_api_keys" {
  name        = "${local.name_prefix}/llm-api-keys"
  description = "API keys for LLM providers (Bedrock, OpenAI fallback)"

  recovery_window_in_days = var.environment == "prod" ? 30 : 7

  tags = {
    Name = "${local.name_prefix}-llm-api-keys"
  }
}

resource "aws_secretsmanager_secret_version" "llm_api_keys" {
  secret_id = aws_secretsmanager_secret.llm_api_keys.id

  secret_string = jsonencode({
    bedrock_enabled = true
    openai_api_key  = "REPLACE_ME"
    anthropic_api_key = "REPLACE_ME"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# --- Service-to-Service Auth Keys ---
resource "aws_secretsmanager_secret" "s2s_keys" {
  name        = "${local.name_prefix}/s2s-auth-keys"
  description = "HMAC keys for service-to-service authentication"

  recovery_window_in_days = var.environment == "prod" ? 30 : 7

  tags = {
    Name = "${local.name_prefix}-s2s-keys"
  }
}

resource "aws_secretsmanager_secret_version" "s2s_keys" {
  secret_id = aws_secretsmanager_secret.s2s_keys.id

  secret_string = jsonencode({
    llm_gateway_key          = "REPLACE_ME"
    memory_service_key       = "REPLACE_ME"
    agent_eval_key           = "REPLACE_ME"
    compliance_assistant_key = "REPLACE_ME"
    preprocessor_key         = "REPLACE_ME"
    observer_key             = "REPLACE_ME"
    sandbox_service_key      = "REPLACE_ME"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# --- Redis Auth Token ---
resource "aws_secretsmanager_secret" "redis_auth" {
  name        = "${local.name_prefix}/redis-auth-token"
  description = "Redis AUTH token for transit encryption"

  recovery_window_in_days = var.environment == "prod" ? 30 : 7

  tags = {
    Name = "${local.name_prefix}-redis-auth"
  }
}

resource "aws_secretsmanager_secret_version" "redis_auth" {
  secret_id = aws_secretsmanager_secret.redis_auth.id

  secret_string = jsonencode({
    auth_token = "REPLACE_ME_WITH_SECURE_TOKEN"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# --- Rotation Configuration for Database Secret ---
resource "aws_secretsmanager_secret_rotation" "database_url" {
  count = var.environment == "prod" ? 1 : 0

  secret_id           = aws_secretsmanager_secret.database_url.id
  rotation_lambda_arn = aws_lambda_function.secret_rotation[0].arn

  rotation_rules {
    automatically_after_days = 30
  }
}

# --- Rotation Lambda (prod only) ---
resource "aws_lambda_function" "secret_rotation" {
  count = var.environment == "prod" ? 1 : 0

  function_name = "${local.name_prefix}-secret-rotation"
  runtime       = "python3.12"
  handler       = "index.handler"
  timeout       = 30
  memory_size   = 128

  # Placeholder - actual code deployed separately
  filename = data.archive_file.rotation_placeholder[0].output_path
  source_code_hash = data.archive_file.rotation_placeholder[0].output_base64sha256

  role = aws_iam_role.rotation_lambda[0].arn

  environment {
    variables = {
      SECRETS_MANAGER_ENDPOINT = ""
    }
  }

  tags = {
    Name = "${local.name_prefix}-secret-rotation"
  }
}

data "archive_file" "rotation_placeholder" {
  count       = var.environment == "prod" ? 1 : 0
  type        = "zip"
  output_path = "${path.module}/rotation_placeholder.zip"

  source {
    content  = "def handler(event, context): pass"
    filename = "index.py"
  }
}

resource "aws_iam_role" "rotation_lambda" {
  count = var.environment == "prod" ? 1 : 0
  name  = "${local.name_prefix}-secret-rotation-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "rotation_lambda" {
  count = var.environment == "prod" ? 1 : 0
  name  = "${local.name_prefix}-secret-rotation-policy"
  role  = aws_iam_role.rotation_lambda[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:DescribeSecret",
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:UpdateSecretVersionStage",
        ]
        Resource = aws_secretsmanager_secret.database_url.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
    ]
  })
}

resource "aws_lambda_permission" "rotation" {
  count         = var.environment == "prod" ? 1 : 0
  statement_id  = "AllowSecretsManagerInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.secret_rotation[0].function_name
  principal     = "secretsmanager.amazonaws.com"
}

# --- Outputs ---
output "secret_arns" {
  value = {
    "database-url"  = aws_secretsmanager_secret.database_url.arn
    "llm-api-keys"  = aws_secretsmanager_secret.llm_api_keys.arn
    "s2s-auth-keys" = aws_secretsmanager_secret.s2s_keys.arn
    "redis-auth"    = aws_secretsmanager_secret.redis_auth.arn
  }
}

output "database_url_secret_arn" {
  value = aws_secretsmanager_secret.database_url.arn
}
