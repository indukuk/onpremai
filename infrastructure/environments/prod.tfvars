environment        = "prod"
aws_region         = "us-east-1"
vpc_cidr           = "10.0.0.0/16"
availability_zones = ["us-east-1a", "us-east-1b", "us-east-1c"]
single_nat_gateway = false

# RDS - production sizing, Multi-AZ
rds_instance_class    = "db.r6g.xlarge"
rds_allocated_storage = 100
rds_multi_az          = true

# Redis - 3-node cluster with automatic failover
redis_node_type          = "cache.r6g.large"
redis_num_cache_clusters = 3

# ECS services - production sizing
ecs_services = {
  llm-gateway = {
    cpu           = 1024
    memory        = 2048
    desired_count = 3
    min_count     = 2
    max_count     = 10
    port          = 4000
  }
  memory-service = {
    cpu           = 512
    memory        = 1024
    desired_count = 2
    min_count     = 2
    max_count     = 6
    port          = 5000
  }
  agent-eval = {
    cpu           = 2048
    memory        = 4096
    desired_count = 2
    min_count     = 1
    max_count     = 8
    port          = 8080
  }
  compliance-assistant = {
    cpu           = 1024
    memory        = 2048
    desired_count = 2
    min_count     = 2
    max_count     = 8
    port          = 8080
  }
  preprocessor = {
    cpu           = 1024
    memory        = 2048
    desired_count = 1
    min_count     = 1
    max_count     = 4
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
    max_count     = 4
    port          = 6000
  }
}

service_image_tags = {
  "llm-gateway"          = "latest"
  "memory-service"       = "latest"
  "agent-eval"           = "latest"
  "compliance-assistant" = "latest"
  "preprocessor"         = "latest"
  "observer"             = "latest"
  "sandbox-service"      = "latest"
}

# Update these with actual domain values before production deploy
domain_name     = ""
certificate_arn = ""

cognito_callback_urls = ["https://app.example.com/callback"]
cognito_logout_urls   = ["https://app.example.com/logout"]
