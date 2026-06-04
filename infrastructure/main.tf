locals {
  name_prefix = "${var.project}-${var.environment}"
}

# --- Networking ---
module "networking" {
  source = "./modules/networking"

  project            = var.project
  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  single_nat_gateway = var.single_nat_gateway
}

# --- ECR Repositories ---
module "ecr" {
  source = "./modules/ecr"

  project     = var.project
  environment = var.environment
  services    = keys(var.ecs_services)
}

# --- ECS Cluster ---
module "ecs" {
  source = "./modules/ecs"

  project               = var.project
  environment           = var.environment
  vpc_id                = module.networking.vpc_id
  alb_security_group_id = module.alb.security_group_id
}

# --- RDS PostgreSQL + pgvector ---
module "rds" {
  source = "./modules/rds"

  project            = var.project
  environment        = var.environment
  vpc_id             = module.networking.vpc_id
  database_subnet_ids = module.networking.database_subnet_ids
  instance_class     = var.rds_instance_class
  allocated_storage  = var.rds_allocated_storage
  multi_az           = var.rds_multi_az
  allowed_security_group_ids = [module.ecs.service_security_group_id]
}

# --- ElastiCache Redis ---
module "redis" {
  source = "./modules/redis"

  project              = var.project
  environment          = var.environment
  vpc_id               = module.networking.vpc_id
  private_subnet_ids   = module.networking.private_subnet_ids
  num_cache_clusters   = var.redis_num_cache_clusters
  node_type            = var.redis_node_type
  allowed_security_group_ids = [module.ecs.service_security_group_id]
}

# --- S3 Storage ---
module "storage" {
  source = "./modules/storage"

  project     = var.project
  environment = var.environment
}

# --- Cognito Auth ---
module "auth" {
  source = "./modules/auth"

  project            = var.project
  environment        = var.environment
  callback_urls      = var.cognito_callback_urls
  logout_urls        = var.cognito_logout_urls
}

# --- Secrets Manager ---
module "secrets" {
  source = "./modules/secrets"

  project     = var.project
  environment = var.environment
  rds_endpoint = module.rds.endpoint
}

# --- ALB ---
module "alb" {
  source = "./modules/alb"

  project            = var.project
  environment        = var.environment
  vpc_id             = module.networking.vpc_id
  public_subnet_ids  = module.networking.public_subnet_ids
  certificate_arn    = var.certificate_arn
}

# --- Service Discovery (Cloud Map) ---
module "discovery" {
  source = "./modules/discovery"

  project     = var.project
  environment = var.environment
  vpc_id      = module.networking.vpc_id
}
