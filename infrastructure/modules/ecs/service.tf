# --- Per-Service Resources (only created when create_service = true) ---

# Data source for account ID (used in execution role policy)
data "aws_caller_identity" "current" {}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "service" {
  count             = var.create_service ? 1 : 0
  name              = "/ecs/${local.name_prefix}/${var.service_name}"
  retention_in_days = var.environment == "prod" ? 90 : 14

  tags = {
    Name    = "${local.name_prefix}-${var.service_name}-logs"
    Service = var.service_name
  }
}

# IAM Role - Task Execution (pull images, write logs, read secrets)
resource "aws_iam_role" "execution" {
  count = var.create_service ? 1 : 0
  name  = "${local.name_prefix}-${var.service_name}-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = {
    Name    = "${local.name_prefix}-${var.service_name}-exec-role"
    Service = var.service_name
  }
}

resource "aws_iam_role_policy_attachment" "execution" {
  count      = var.create_service ? 1 : 0
  role       = aws_iam_role.execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_policy" "execution_secrets" {
  count = var.create_service ? 1 : 0
  name  = "${local.name_prefix}-${var.service_name}-exec-secrets"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "ssm:GetParameters",
      ]
      Resource = length(var.secret_arns) > 0 ? var.secret_arns : ["arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.project}/${var.environment}/*"]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution_secrets" {
  count      = var.create_service ? 1 : 0
  role       = aws_iam_role.execution[0].name
  policy_arn = aws_iam_policy.execution_secrets[0].arn
}

# IAM Role - Task Role (what the container can do)
resource "aws_iam_role" "task" {
  count = var.create_service ? 1 : 0
  name  = "${local.name_prefix}-${var.service_name}-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = {
    Name    = "${local.name_prefix}-${var.service_name}-task-role"
    Service = var.service_name
  }
}

resource "aws_iam_policy" "task" {
  count = var.create_service ? 1 : 0
  name  = "${local.name_prefix}-${var.service_name}-task-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Sid    = "CloudWatchLogs"
          Effect = "Allow"
          Action = [
            "logs:CreateLogStream",
            "logs:PutLogEvents",
          ]
          Resource = "*"
        }
      ],
      [
        for stmt in var.task_policy_statements : merge(
          {
            Sid      = stmt.sid
            Effect   = "Allow"
            Action   = stmt.actions
            Resource = stmt.resources
          },
          length(stmt.conditions) > 0 ? {
            Condition = {
              for cond in stmt.conditions : cond.test => {
                (cond.variable) = cond.values
              }
            }
          } : {}
        )
      ]
    )
  })
}

resource "aws_iam_role_policy_attachment" "task" {
  count      = var.create_service ? 1 : 0
  role       = aws_iam_role.task[0].name
  policy_arn = aws_iam_policy.task[0].arn
}

# Additional policy ARN attachments (e.g., tenant-scoped S3 policy)
resource "aws_iam_role_policy_attachment" "task_additional" {
  for_each   = var.create_service ? toset(var.additional_policy_arns) : toset([])
  role       = aws_iam_role.task[0].name
  policy_arn = each.value
}

# ECS Task Definition
resource "aws_ecs_task_definition" "service" {
  count                    = var.create_service ? 1 : 0
  family                   = "${local.name_prefix}-${var.service_name}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution[0].arn
  task_role_arn            = aws_iam_role.task[0].arn

  container_definitions = jsonencode([{
    name  = var.service_name
    image = "${var.ecr_repository_url}:${var.image_tag}"

    portMappings = [{
      containerPort = var.container_port
      protocol      = "tcp"
    }]

    environment = var.environment_variables
    secrets     = var.secrets

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.service[0].name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = var.service_name
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:${var.container_port}/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])

  tags = {
    Name    = "${local.name_prefix}-${var.service_name}-task"
    Service = var.service_name
  }
}

# Service Discovery (Cloud Map)
resource "aws_service_discovery_service" "service" {
  count = var.create_service ? 1 : 0
  name  = var.service_name

  dns_config {
    namespace_id = var.discovery_namespace_id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

# ECS Service
resource "aws_ecs_service" "service" {
  count           = var.create_service ? 1 : 0
  name            = var.service_name
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.service[0].arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [] # Uses the shared SG from cluster
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = var.service_name
    container_port   = var.container_port
  }

  service_registries {
    registry_arn = aws_service_discovery_service.service[0].arn
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_controller {
    type = "ECS"
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = {
    Name    = "${local.name_prefix}-${var.service_name}"
    Service = var.service_name
  }
}

# Auto Scaling Target
resource "aws_appautoscaling_target" "service" {
  count              = var.create_service ? 1 : 0
  max_capacity       = var.max_count
  min_capacity       = var.min_count
  resource_id        = "service/${split("/", var.cluster_arn)[1]}/${var.service_name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  depends_on = [aws_ecs_service.service]
}

# Auto Scaling Policy - CPU
resource "aws_appautoscaling_policy" "cpu" {
  count              = var.create_service ? 1 : 0
  name               = "${local.name_prefix}-${var.service_name}-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.service[0].resource_id
  scalable_dimension = aws_appautoscaling_target.service[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.service[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# Auto Scaling Policy - Memory
resource "aws_appautoscaling_policy" "memory" {
  count              = var.create_service ? 1 : 0
  name               = "${local.name_prefix}-${var.service_name}-memory"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.service[0].resource_id
  scalable_dimension = aws_appautoscaling_target.service[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.service[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    target_value       = 80.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# --- Service Outputs ---
output "service_name" {
  value = var.create_service ? aws_ecs_service.service[0].name : ""
}

output "task_definition_arn" {
  value = var.create_service ? aws_ecs_task_definition.service[0].arn : ""
}
