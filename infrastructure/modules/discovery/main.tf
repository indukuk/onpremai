variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

locals {
  name_prefix    = "${var.project}-${var.environment}"
  namespace_name = "${var.project}.local"
}

# --- Cloud Map Private DNS Namespace ---
resource "aws_service_discovery_private_dns_namespace" "main" {
  name = local.namespace_name
  vpc  = var.vpc_id

  description = "Service discovery namespace for ${var.project} ${var.environment}"

  tags = {
    Name = "${local.name_prefix}-discovery"
  }
}

# --- Outputs ---
output "namespace_id" {
  value = aws_service_discovery_private_dns_namespace.main.id
}

output "namespace_arn" {
  value = aws_service_discovery_private_dns_namespace.main.arn
}

output "namespace_name" {
  value = aws_service_discovery_private_dns_namespace.main.name
}

output "hosted_zone_id" {
  value = aws_service_discovery_private_dns_namespace.main.hosted_zone
}
