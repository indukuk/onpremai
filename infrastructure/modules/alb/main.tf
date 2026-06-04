variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "certificate_arn" {
  description = "ACM certificate ARN for HTTPS (leave empty for HTTP-only)"
  type        = string
  default     = ""
}

locals {
  name_prefix = "${var.project}-${var.environment}"
  use_https   = var.certificate_arn != ""

  # Service path routing configuration
  services = {
    llm-gateway = {
      port         = 4000
      path_pattern = "/api/llm/*"
      priority     = 100
      health_path  = "/health"
    }
    memory-service = {
      port         = 5000
      path_pattern = "/api/memory/*"
      priority     = 200
      health_path  = "/health"
    }
    agent-eval = {
      port         = 8080
      path_pattern = "/api/eval/*"
      priority     = 300
      health_path  = "/health"
    }
    compliance-assistant = {
      port         = 8080
      path_pattern = "/api/assistant/*"
      priority     = 400
      health_path  = "/health"
    }
    preprocessor = {
      port         = 7000
      path_pattern = "/api/preprocessor/*"
      priority     = 500
      health_path  = "/health"
    }
    observer = {
      port         = 6000
      path_pattern = "/api/observer/*"
      priority     = 600
      health_path  = "/health"
    }
    sandbox-service = {
      port         = 6000
      path_pattern = "/api/sandbox/*"
      priority     = 700
      health_path  = "/health"
    }
  }
}

# --- ALB Security Group ---
resource "aws_security_group" "alb" {
  name   = "${local.name_prefix}-alb"
  vpc_id = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-alb-sg"
  }
}

# --- Application Load Balancer ---
resource "aws_lb" "main" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = var.environment == "prod"

  access_logs {
    bucket  = ""
    enabled = false
  }

  tags = {
    Name = "${local.name_prefix}-alb"
  }
}

# --- HTTP Listener ---
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = local.use_https ? "redirect" : "fixed-response"

    dynamic "redirect" {
      for_each = local.use_https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    dynamic "fixed_response" {
      for_each = local.use_https ? [] : [1]
      content {
        content_type = "application/json"
        message_body = "{\"status\":\"healthy\",\"service\":\"onpremai\"}"
        status_code  = "200"
      }
    }
  }
}

# --- HTTPS Listener (only when certificate is provided) ---
resource "aws_lb_listener" "https" {
  count = local.use_https ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"status\":\"healthy\",\"service\":\"onpremai\"}"
      status_code  = "200"
    }
  }
}

# --- Target Groups (one per service) ---
resource "aws_lb_target_group" "services" {
  for_each = local.services

  name        = "${local.name_prefix}-${each.key}"
  port        = each.value.port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    path                = each.value.health_path
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = {
    Name    = "${local.name_prefix}-${each.key}-tg"
    Service = each.key
  }
}

# --- Listener Rules (path-based routing) ---
resource "aws_lb_listener_rule" "services" {
  for_each = local.services

  listener_arn = local.use_https ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn
  priority     = each.value.priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.services[each.key].arn
  }

  condition {
    path_pattern {
      values = [each.value.path_pattern]
    }
  }
}

# --- Outputs ---
output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "alb_arn" {
  value = aws_lb.main.arn
}

output "alb_zone_id" {
  value = aws_lb.main.zone_id
}

output "security_group_id" {
  value = aws_security_group.alb.id
}

output "target_group_arns" {
  value = { for k, v in aws_lb_target_group.services : k => v.arn }
}

output "listener_arn" {
  value = local.use_https ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn
}
