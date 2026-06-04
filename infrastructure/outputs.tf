output "alb_dns_name" {
  description = "ALB DNS name for accessing services"
  value       = module.alb.alb_dns_name
}

output "alb_url" {
  description = "Full ALB URL"
  value       = "http://${module.alb.alb_dns_name}"
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint"
  value       = module.rds.endpoint
  sensitive   = true
}

output "rds_port" {
  description = "RDS PostgreSQL port"
  value       = module.rds.port
}

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = module.redis.primary_endpoint
  sensitive   = true
}

output "redis_port" {
  description = "ElastiCache Redis port"
  value       = module.redis.port
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  value       = module.auth.user_pool_id
}

output "cognito_client_id" {
  description = "Cognito App Client ID"
  value       = module.auth.client_id
}

output "cognito_domain" {
  description = "Cognito hosted UI domain"
  value       = module.auth.cognito_domain
}

output "ecr_repository_urls" {
  description = "Map of service name to ECR repository URL"
  value       = module.ecr.repository_urls
}

output "s3_bucket_name" {
  description = "S3 bucket for compliance artifacts"
  value       = module.storage.bucket_name
}

output "service_discovery_namespace" {
  description = "Cloud Map namespace for service discovery"
  value       = module.discovery.namespace_name
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.networking.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = module.networking.private_subnet_ids
}
