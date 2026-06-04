variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "service_name" {
  type    = string
  default = ""
}

variable "cluster_arn" {
  type    = string
  default = ""
}

variable "vpc_id" {
  type    = string
  default = ""
}

variable "private_subnet_ids" {
  type    = list(string)
  default = []
}

variable "ecr_repository_url" {
  type    = string
  default = ""
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "container_port" {
  type    = number
  default = 8080
}

variable "cpu" {
  type    = number
  default = 512
}

variable "memory" {
  type    = number
  default = 1024
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "min_count" {
  type    = number
  default = 1
}

variable "max_count" {
  type    = number
  default = 4
}

variable "target_group_arn" {
  type    = string
  default = ""
}

variable "discovery_namespace_id" {
  type    = string
  default = ""
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment_variables" {
  type = list(object({
    name  = string
    value = string
  }))
  default = []
}

variable "secrets" {
  type = list(object({
    name      = string
    valueFrom = string
  }))
  default = []
}

variable "create_service" {
  type    = bool
  default = false
}

variable "alb_security_group_id" {
  description = "Security group ID of the ALB, used to restrict ECS ingress to ALB traffic only"
  type        = string
  default     = ""
}

variable "task_policy_statements" {
  description = "List of additional IAM policy statements for this service's task role"
  type = list(object({
    sid       = string
    actions   = list(string)
    resources = list(string)
    conditions = optional(list(object({
      test     = string
      variable = string
      values   = list(string)
    })), [])
  }))
  default = []
}

variable "secret_arns" {
  description = "List of Secrets Manager ARNs this service can read at startup"
  type        = list(string)
  default     = []
}

variable "additional_policy_arns" {
  description = "Additional IAM policy ARNs to attach to the task role"
  type        = list(string)
  default     = []
}

locals {
  name_prefix = "${var.project}-${var.environment}"
}

# --- ECS Cluster (only created when this is used as cluster module) ---
resource "aws_ecs_cluster" "main" {
  count = var.create_service ? 0 : 1
  name  = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${local.name_prefix}-cluster"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  count        = var.create_service ? 0 : 1
  cluster_name = aws_ecs_cluster.main[0].name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 1
    capacity_provider = "FARGATE"
  }

  default_capacity_provider_strategy {
    weight            = 3
    capacity_provider = "FARGATE_SPOT"
  }
}

# --- Security Group for ECS Services (shared, created only for cluster) ---
resource "aws_security_group" "ecs_services" {
  count  = var.create_service ? 0 : 1
  name   = "${local.name_prefix}-ecs-services"
  vpc_id = var.vpc_id

  # Allow all traffic between services in the same SG (inter-service communication)
  ingress {
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    self        = true
    description = "Inter-service communication"
  }

  # Allow ALB health checks and traffic (restricted to ALB security group)
  ingress {
    from_port       = 0
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [var.alb_security_group_id]
    description     = "ALB to services"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-ecs-services-sg"
  }
}

# --- Cluster Outputs ---
output "cluster_arn" {
  value = var.create_service ? "" : aws_ecs_cluster.main[0].arn
}

output "cluster_name" {
  value = var.create_service ? "" : aws_ecs_cluster.main[0].name
}

output "service_security_group_id" {
  value = var.create_service ? "" : aws_security_group.ecs_services[0].id
}
