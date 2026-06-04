variable "project" {
  description = "Project name used for resource naming"
  type        = string
  default     = "onpremai"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "single_nat_gateway" {
  description = "Use a single NAT gateway (true for dev, false for prod)"
  type        = bool
  default     = true
}

variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t4g.medium"
}

variable "rds_allocated_storage" {
  description = "RDS allocated storage in GB"
  type        = number
  default     = 50
}

variable "rds_multi_az" {
  description = "Enable Multi-AZ for RDS"
  type        = bool
  default     = false
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type"
  type        = string
  default     = "cache.t4g.medium"
}

variable "redis_num_cache_clusters" {
  description = "Number of Redis cache clusters"
  type        = number
  default     = 1
}

variable "domain_name" {
  description = "Domain name for the application (used for ALB and Cognito)"
  type        = string
  default     = ""
}

variable "certificate_arn" {
  description = "ACM certificate ARN for HTTPS (leave empty to use HTTP only)"
  type        = string
  default     = ""
}

variable "ecs_services" {
  description = "Map of ECS service configurations"
  type = map(object({
    cpu           = number
    memory        = number
    desired_count = number
    min_count     = number
    max_count     = number
    port          = number
  }))
  default = {
    llm-gateway = {
      cpu           = 1024
      memory        = 2048
      desired_count = 1
      min_count     = 1
      max_count     = 4
      port          = 4000
    }
    memory-service = {
      cpu           = 512
      memory        = 1024
      desired_count = 1
      min_count     = 1
      max_count     = 4
      port          = 5000
    }
    agent-eval = {
      cpu           = 2048
      memory        = 4096
      desired_count = 1
      min_count     = 1
      max_count     = 4
      port          = 8080
    }
    compliance-assistant = {
      cpu           = 1024
      memory        = 2048
      desired_count = 1
      min_count     = 1
      max_count     = 4
      port          = 8080
    }
    preprocessor = {
      cpu           = 1024
      memory        = 2048
      desired_count = 1
      min_count     = 1
      max_count     = 2
      port          = 7000
    }
    observer = {
      cpu           = 512
      memory        = 1024
      desired_count = 1
      min_count     = 1
      max_count     = 2
      port          = 6000
    }
    sandbox-service = {
      cpu           = 2048
      memory        = 4096
      desired_count = 1
      min_count     = 1
      max_count     = 2
      port          = 6000
    }
  }
}

variable "service_image_tags" {
  description = "Map of service name to Docker image tag"
  type        = map(string)
  default = {
    "llm-gateway"          = "latest"
    "memory-service"       = "latest"
    "agent-eval"           = "latest"
    "compliance-assistant" = "latest"
    "preprocessor"         = "latest"
    "observer"             = "latest"
    "sandbox-service"      = "latest"
  }
}

variable "cognito_callback_urls" {
  description = "Cognito OAuth callback URLs"
  type        = list(string)
  default     = ["http://localhost:3000/callback"]
}

variable "cognito_logout_urls" {
  description = "Cognito OAuth logout URLs"
  type        = list(string)
  default     = ["http://localhost:3000/logout"]
}
