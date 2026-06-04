# --- ECS Service Instantiations ---
# Each service uses the reusable ecs/service module

module "service_llm_gateway" {
  source = "./modules/ecs"

  project            = var.project
  environment        = var.environment
  service_name       = "llm-gateway"
  cluster_arn        = module.ecs.cluster_arn
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  ecr_repository_url = module.ecr.repository_urls["llm-gateway"]
  image_tag          = var.service_image_tags["llm-gateway"]
  container_port     = 4000
  cpu                = var.ecs_services["llm-gateway"].cpu
  memory             = var.ecs_services["llm-gateway"].memory
  desired_count      = var.ecs_services["llm-gateway"].desired_count
  min_count          = var.ecs_services["llm-gateway"].min_count
  max_count          = var.ecs_services["llm-gateway"].max_count
  target_group_arn   = module.alb.target_group_arns["llm-gateway"]
  discovery_namespace_id = module.discovery.namespace_id
  aws_region         = var.aws_region

  environment_variables = [
    { name = "SERVICE_NAME", value = "llm-gateway" },
    { name = "ENVIRONMENT", value = var.environment },
    { name = "REDIS_HOST", value = module.redis.primary_endpoint },
    { name = "REDIS_PORT", value = tostring(module.redis.port) },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = module.storage.bucket_name },
    { name = "MEMORY_SERVICE_URL", value = "http://memory-service.${var.project}.local:5000" },
  ]

  secrets = [
    { name = "DATABASE_URL", valueFrom = module.secrets.secret_arns["database-url"] },
  ]

  secret_arns = [module.secrets.secret_arns["database-url"]]

  task_policy_statements = [
    {
      sid       = "BedrockInvoke"
      actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      resources = [
        "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-*",
        "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-*",
      ]
      conditions = []
    },
  ]

  create_service = true
}

module "service_memory_service" {
  source = "./modules/ecs"

  project            = var.project
  environment        = var.environment
  service_name       = "memory-service"
  cluster_arn        = module.ecs.cluster_arn
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  ecr_repository_url = module.ecr.repository_urls["memory-service"]
  image_tag          = var.service_image_tags["memory-service"]
  container_port     = 5000
  cpu                = var.ecs_services["memory-service"].cpu
  memory             = var.ecs_services["memory-service"].memory
  desired_count      = var.ecs_services["memory-service"].desired_count
  min_count          = var.ecs_services["memory-service"].min_count
  max_count          = var.ecs_services["memory-service"].max_count
  target_group_arn   = module.alb.target_group_arns["memory-service"]
  discovery_namespace_id = module.discovery.namespace_id
  aws_region         = var.aws_region

  environment_variables = [
    { name = "SERVICE_NAME", value = "memory-service" },
    { name = "ENVIRONMENT", value = var.environment },
    { name = "REDIS_HOST", value = module.redis.primary_endpoint },
    { name = "REDIS_PORT", value = tostring(module.redis.port) },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = module.storage.bucket_name },
  ]

  secrets = [
    { name = "DATABASE_URL", valueFrom = module.secrets.secret_arns["database-url"] },
  ]

  secret_arns = [module.secrets.secret_arns["database-url"]]

  # memory-service has no extra AWS API permissions (DB access via network only)
  task_policy_statements = []

  create_service = true
}

module "service_agent_eval" {
  source = "./modules/ecs"

  project            = var.project
  environment        = var.environment
  service_name       = "agent-eval"
  cluster_arn        = module.ecs.cluster_arn
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  ecr_repository_url = module.ecr.repository_urls["agent-eval"]
  image_tag          = var.service_image_tags["agent-eval"]
  container_port     = 8080
  cpu                = var.ecs_services["agent-eval"].cpu
  memory             = var.ecs_services["agent-eval"].memory
  desired_count      = var.ecs_services["agent-eval"].desired_count
  min_count          = var.ecs_services["agent-eval"].min_count
  max_count          = var.ecs_services["agent-eval"].max_count
  target_group_arn   = module.alb.target_group_arns["agent-eval"]
  discovery_namespace_id = module.discovery.namespace_id
  aws_region         = var.aws_region

  environment_variables = [
    { name = "SERVICE_NAME", value = "agent-eval" },
    { name = "ENVIRONMENT", value = var.environment },
    { name = "LLM_GATEWAY_URL", value = "http://llm-gateway.${var.project}.local:4000" },
    { name = "MEMORY_SERVICE_URL", value = "http://memory-service.${var.project}.local:5000" },
    { name = "SANDBOX_SERVICE_URL", value = "http://sandbox-service.${var.project}.local:6000" },
    { name = "REDIS_HOST", value = module.redis.primary_endpoint },
    { name = "REDIS_PORT", value = tostring(module.redis.port) },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = module.storage.bucket_name },
  ]

  secrets = [
    { name = "DATABASE_URL", valueFrom = module.secrets.secret_arns["database-url"] },
  ]

  secret_arns = [module.secrets.secret_arns["database-url"]]

  task_policy_statements = [
    {
      sid       = "S3ReadOnly"
      actions   = ["s3:GetObject", "s3:ListBucket"]
      resources = [
        module.storage.bucket_arn,
        "${module.storage.bucket_arn}/*",
      ]
      conditions = []
    },
  ]

  additional_policy_arns = [module.storage.tenant_policy_arn]

  create_service = true
}

module "service_compliance_assistant" {
  source = "./modules/ecs"

  project            = var.project
  environment        = var.environment
  service_name       = "compliance-assistant"
  cluster_arn        = module.ecs.cluster_arn
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  ecr_repository_url = module.ecr.repository_urls["compliance-assistant"]
  image_tag          = var.service_image_tags["compliance-assistant"]
  container_port     = 8080
  cpu                = var.ecs_services["compliance-assistant"].cpu
  memory             = var.ecs_services["compliance-assistant"].memory
  desired_count      = var.ecs_services["compliance-assistant"].desired_count
  min_count          = var.ecs_services["compliance-assistant"].min_count
  max_count          = var.ecs_services["compliance-assistant"].max_count
  target_group_arn   = module.alb.target_group_arns["compliance-assistant"]
  discovery_namespace_id = module.discovery.namespace_id
  aws_region         = var.aws_region

  environment_variables = [
    { name = "SERVICE_NAME", value = "compliance-assistant" },
    { name = "ENVIRONMENT", value = var.environment },
    { name = "LLM_GATEWAY_URL", value = "http://llm-gateway.${var.project}.local:4000" },
    { name = "MEMORY_SERVICE_URL", value = "http://memory-service.${var.project}.local:5000" },
    { name = "REDIS_HOST", value = module.redis.primary_endpoint },
    { name = "REDIS_PORT", value = tostring(module.redis.port) },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = module.storage.bucket_name },
  ]

  secrets = [
    { name = "DATABASE_URL", valueFrom = module.secrets.secret_arns["database-url"] },
  ]

  secret_arns = [module.secrets.secret_arns["database-url"]]

  # compliance-assistant has no extra AWS API permissions
  task_policy_statements = []

  create_service = true
}

module "service_preprocessor" {
  source = "./modules/ecs"

  project            = var.project
  environment        = var.environment
  service_name       = "preprocessor"
  cluster_arn        = module.ecs.cluster_arn
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  ecr_repository_url = module.ecr.repository_urls["preprocessor"]
  image_tag          = var.service_image_tags["preprocessor"]
  container_port     = 7000
  cpu                = var.ecs_services["preprocessor"].cpu
  memory             = var.ecs_services["preprocessor"].memory
  desired_count      = var.ecs_services["preprocessor"].desired_count
  min_count          = var.ecs_services["preprocessor"].min_count
  max_count          = var.ecs_services["preprocessor"].max_count
  target_group_arn   = module.alb.target_group_arns["preprocessor"]
  discovery_namespace_id = module.discovery.namespace_id
  aws_region         = var.aws_region

  environment_variables = [
    { name = "SERVICE_NAME", value = "preprocessor" },
    { name = "ENVIRONMENT", value = var.environment },
    { name = "LLM_GATEWAY_URL", value = "http://llm-gateway.${var.project}.local:4000" },
    { name = "MEMORY_SERVICE_URL", value = "http://memory-service.${var.project}.local:5000" },
    { name = "REDIS_HOST", value = module.redis.primary_endpoint },
    { name = "REDIS_PORT", value = tostring(module.redis.port) },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = module.storage.bucket_name },
    { name = "OCR_BACKEND", value = "textract" },
  ]

  secrets = [
    { name = "DATABASE_URL", valueFrom = module.secrets.secret_arns["database-url"] },
  ]

  secret_arns = [module.secrets.secret_arns["database-url"]]

  task_policy_statements = [
    {
      sid       = "S3ReadWrite"
      actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      resources = [
        module.storage.bucket_arn,
        "${module.storage.bucket_arn}/*",
      ]
      conditions = []
    },
    {
      sid       = "TextractAccess"
      actions   = ["textract:DetectDocumentText", "textract:AnalyzeDocument"]
      resources = ["*"]
      conditions = []
    },
  ]

  additional_policy_arns = [module.storage.tenant_policy_arn]

  create_service = true
}

module "service_observer" {
  source = "./modules/ecs"

  project            = var.project
  environment        = var.environment
  service_name       = "observer"
  cluster_arn        = module.ecs.cluster_arn
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  ecr_repository_url = module.ecr.repository_urls["observer"]
  image_tag          = var.service_image_tags["observer"]
  container_port     = 6000
  cpu                = var.ecs_services["observer"].cpu
  memory             = var.ecs_services["observer"].memory
  desired_count      = var.ecs_services["observer"].desired_count
  min_count          = var.ecs_services["observer"].min_count
  max_count          = var.ecs_services["observer"].max_count
  target_group_arn   = module.alb.target_group_arns["observer"]
  discovery_namespace_id = module.discovery.namespace_id
  aws_region         = var.aws_region

  environment_variables = [
    { name = "SERVICE_NAME", value = "observer" },
    { name = "ENVIRONMENT", value = var.environment },
    { name = "LLM_GATEWAY_URL", value = "http://llm-gateway.${var.project}.local:4000" },
    { name = "LLM_GATEWAY_ADMIN_URL", value = "http://llm-gateway.${var.project}.local:4001" },
    { name = "MEMORY_SERVICE_URL", value = "http://memory-service.${var.project}.local:5000" },
    { name = "REDIS_HOST", value = module.redis.primary_endpoint },
    { name = "REDIS_PORT", value = tostring(module.redis.port) },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = module.storage.bucket_name },
  ]

  secrets = [
    { name = "DATABASE_URL", valueFrom = module.secrets.secret_arns["database-url"] },
  ]

  secret_arns = [module.secrets.secret_arns["database-url"]]

  task_policy_statements = [
    {
      sid       = "CloudWatchLogsRead"
      actions   = ["logs:FilterLogEvents", "logs:GetLogEvents"]
      resources = ["*"]
      conditions = []
    },
  ]

  create_service = true
}

module "service_sandbox_service" {
  source = "./modules/ecs"

  project            = var.project
  environment        = var.environment
  service_name       = "sandbox-service"
  cluster_arn        = module.ecs.cluster_arn
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  ecr_repository_url = module.ecr.repository_urls["sandbox-service"]
  image_tag          = var.service_image_tags["sandbox-service"]
  container_port     = 6000
  cpu                = var.ecs_services["sandbox-service"].cpu
  memory             = var.ecs_services["sandbox-service"].memory
  desired_count      = var.ecs_services["sandbox-service"].desired_count
  min_count          = var.ecs_services["sandbox-service"].min_count
  max_count          = var.ecs_services["sandbox-service"].max_count
  target_group_arn   = module.alb.target_group_arns["sandbox-service"]
  discovery_namespace_id = module.discovery.namespace_id
  aws_region         = var.aws_region

  environment_variables = [
    { name = "SERVICE_NAME", value = "sandbox-service" },
    { name = "ENVIRONMENT", value = var.environment },
    { name = "REDIS_HOST", value = module.redis.primary_endpoint },
    { name = "REDIS_PORT", value = tostring(module.redis.port) },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = module.storage.bucket_name },
  ]

  secrets = [
    { name = "DATABASE_URL", valueFrom = module.secrets.secret_arns["database-url"] },
  ]

  secret_arns = [module.secrets.secret_arns["database-url"]]

  task_policy_statements = [
    {
      sid       = "S3ReadOnly"
      actions   = ["s3:GetObject"]
      resources = [
        "${module.storage.bucket_arn}/*",
      ]
      conditions = []
    },
  ]

  additional_policy_arns = [module.storage.tenant_policy_arn]

  create_service = true
}
