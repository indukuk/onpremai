environment        = "dev"
aws_region         = "us-east-1"
vpc_cidr           = "10.0.0.0/16"
availability_zones = ["us-east-1a"]
single_nat_gateway = true

# RDS - small instance, single AZ
rds_instance_class    = "db.t4g.medium"
rds_allocated_storage = 20
rds_multi_az          = false

# Redis - single node
redis_node_type          = "cache.t4g.micro"
redis_num_cache_clusters = 1

# ECS services - minimal sizing
ecs_services = {
  llm-gateway = {
    cpu           = 512
    memory        = 1024
    desired_count = 1
    min_count     = 1
    max_count     = 2
    port          = 4000
  }
  memory-service = {
    cpu           = 256
    memory        = 512
    desired_count = 1
    min_count     = 1
    max_count     = 2
    port          = 5000
  }
  agent-eval = {
    cpu           = 1024
    memory        = 2048
    desired_count = 1
    min_count     = 1
    max_count     = 2
    port          = 8080
  }
  compliance-assistant = {
    cpu           = 512
    memory        = 1024
    desired_count = 1
    min_count     = 1
    max_count     = 2
    port          = 8080
  }
  preprocessor = {
    cpu           = 512
    memory        = 1024
    desired_count = 1
    min_count     = 1
    max_count     = 2
    port          = 7000
  }
  observer = {
    cpu           = 256
    memory        = 512
    desired_count = 1
    min_count     = 1
    max_count     = 1
    port          = 6000
  }
  sandbox-service = {
    cpu           = 1024
    memory        = 2048
    desired_count = 1
    min_count     = 1
    max_count     = 2
    port          = 6000
  }
}

service_image_tags = {
  "llm-gateway"          = "dev"
  "memory-service"       = "dev"
  "agent-eval"           = "dev"
  "compliance-assistant" = "dev"
  "preprocessor"         = "dev"
  "observer"             = "dev"
  "sandbox-service"      = "dev"
}

cognito_callback_urls = ["http://localhost:3000/callback"]
cognito_logout_urls   = ["http://localhost:3000/logout"]
