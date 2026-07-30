data "aws_caller_identity" "current" {}

locals {
  name = "${var.project_name}-${var.environment}"
  tags = {
    Project       = var.project_name
    Environment   = var.environment
    ManagedBy     = "terraform"
    DataBoundary  = "synthetic-default"
    ProviderWrite = "human-approved-scoped"
  }
}

resource "aws_security_group" "alb" {
  name_prefix = "${local.name}-alb-"
  description = "Public TLS ingress for Support Copilot"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP redirect"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "tasks" {
  name_prefix = "${local.name}-tasks-"
  description = "Only the application load balancer can reach ECS tasks"
  vpc_id      = var.vpc_id

  ingress {
    description     = "API from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    description     = "Web from ALB"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "database" {
  name_prefix = "${local.name}-database-"
  description = "PostgreSQL ingress from Copilot tasks only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from ECS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }
}

resource "aws_db_subnet_group" "database" {
  name       = "${local.name}-database"
  subnet_ids = var.private_subnet_ids
}

resource "aws_db_instance" "database" {
  identifier                   = local.name
  engine                       = "postgres"
  engine_version               = "16"
  instance_class               = var.database_instance_class
  allocated_storage            = 20
  max_allocated_storage        = 100
  storage_type                 = "gp3"
  storage_encrypted            = true
  db_name                      = "copilot"
  username                     = "copilot_admin"
  manage_master_user_password  = true
  port                         = 5432
  db_subnet_group_name         = aws_db_subnet_group.database.name
  vpc_security_group_ids       = [aws_security_group.database.id]
  publicly_accessible          = false
  multi_az                     = var.database_multi_az
  backup_retention_period      = 7
  deletion_protection          = var.database_deletion_protection
  auto_minor_version_upgrade   = true
  performance_insights_enabled = true
  monitoring_interval          = 0
  skip_final_snapshot          = false
  final_snapshot_identifier    = "${local.name}-final"
  enabled_cloudwatch_logs_exports = [
    "postgresql",
    "upgrade",
  ]
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}/api"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "web" {
  name              = "/ecs/${local.name}/web"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "migration" {
  name              = "/ecs/${local.name}/migration"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "app" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_iam_role" "execution" {
  name = "${local.name}-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "app_database_secret" {
  name = "read-runtime-secrets"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        var.database_app_secret_arn,
        var.zendesk_secret_arn,
        var.integration_secret_arn,
      ]
    }]
  })
}

resource "aws_iam_role" "web_execution" {
  name = "${local.name}-web-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "web_execution" {
  role       = aws_iam_role.web_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "migration_execution" {
  name = "${local.name}-migration-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "migration_execution" {
  role       = aws_iam_role.migration_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "migration_database_secrets" {
  name = "read-migration-database-secrets"
  role = aws_iam_role.migration_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_db_instance.database.master_user_secret[0].secret_arn,
        var.database_app_secret_arn,
      ]
    }]
  })
}

resource "aws_iam_role" "task" {
  name = "${local.name}-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role" "api_task" {
  name = "${local.name}-api-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "task_bedrock" {
  name = "invoke-approved-bedrock-model"
  role = aws_iam_role.api_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "bedrock:InvokeModel",
      ]
      Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}"
    }]
  })
}

resource "aws_lb" "app" {
  name                       = substr(local.name, 0, 32)
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = var.public_subnet_ids
  drop_invalid_header_fields = true
  enable_deletion_protection = var.database_deletion_protection
}

resource "aws_lb_target_group" "api" {
  name                 = substr("${local.name}-api", 0, 32)
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = "/v1/healthz"
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_target_group" "web" {
  name                 = substr("${local.name}-web", 0, 32)
  port                 = 8080
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = "/healthz"
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.app.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type  = "authenticate-cognito"
    order = 1

    authenticate_cognito {
      user_pool_arn              = var.cognito_user_pool_arn
      user_pool_client_id        = var.cognito_user_pool_client_id
      user_pool_domain           = var.cognito_user_pool_domain
      on_unauthenticated_request = "authenticate"
    }
  }

  default_action {
    type             = "forward"
    order            = 2
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 100

  action {
    type  = "authenticate-cognito"
    order = 1

    authenticate_cognito {
      user_pool_arn              = var.cognito_user_pool_arn
      user_pool_client_id        = var.cognito_user_pool_client_id
      user_pool_domain           = var.cognito_user_pool_domain
      on_unauthenticated_request = "authenticate"
    }
  }

  action {
    type             = "forward"
    order            = 2
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/v1/*"]
    }
  }
}

resource "aws_lb_listener_rule" "provider_integrations" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 80

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = [
        "/v1/sidebar/*",
        "/v1/integrations/jira/callback",
      ]
    }
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  container_definitions = jsonencode([
    {
      name                   = "init-api-tmp"
      image                  = var.api_image_uri
      essential              = false
      user                   = "0"
      readonlyRootFilesystem = true
      entryPoint             = ["/bin/sh", "-c"]
      command                = ["chown 10001:10001 /tmp && chmod 0700 /tmp"]
      mountPoints = [{
        sourceVolume  = "api-tmp"
        containerPath = "/tmp"
        readOnly      = false
      }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "init-api-tmp"
        }
      }
    },
    {
      name                   = "api"
      image                  = var.api_image_uri
      essential              = true
      readonlyRootFilesystem = true
      dependsOn = [{
        containerName = "init-api-tmp"
        condition     = "SUCCESS"
      }]
      portMappings = [{
        containerPort = 8000
        protocol      = "tcp"
      }]
      environment = [
        { name = "COPILOT_ENVIRONMENT", value = "production" },
        { name = "COPILOT_AUTH_MODE", value = "alb_oidc" },
        { name = "COPILOT_MODEL_PROVIDER", value = "bedrock" },
        { name = "COPILOT_BEDROCK_MODEL_ID", value = var.bedrock_model_id },
        { name = "COPILOT_MODEL_MAX_OUTPUT_TOKENS", value = "300" },
        { name = "COPILOT_MODEL_TIMEOUT_SECONDS", value = "30" },
        { name = "COPILOT_AWS_REGION", value = var.aws_region },
        { name = "COPILOT_ALB_ARN", value = aws_lb.app.arn },
        { name = "COPILOT_ALB_CLIENT_ID", value = var.cognito_user_pool_client_id },
        { name = "COPILOT_DATABASE_HOST", value = aws_db_instance.database.address },
        { name = "COPILOT_DATABASE_PORT", value = tostring(aws_db_instance.database.port) },
        { name = "COPILOT_DATABASE_NAME", value = aws_db_instance.database.db_name },
        { name = "COPILOT_RUN_MIGRATIONS", value = "false" },
        { name = "COPILOT_ZENDESK_CLI_PATH", value = "/usr/local/bin/zendesk-cli" },
        { name = "COPILOT_ZENDESK_SUBDOMAIN", value = var.zendesk_subdomain },
        { name = "COPILOT_HANDOFF_ENABLED", value = "true" },
        { name = "COPILOT_ZENDESK_HANDOFF_ALLOWED_TICKET_IDS", value = jsonencode(var.zendesk_handoff_allowed_ticket_ids) },
        { name = "COPILOT_ZENDESK_ESCALATION_TAG", value = "engineering_escalation_approved" },
        { name = "COPILOT_JIRA_PROJECT_KEY", value = var.jira_project_key },
        { name = "COPILOT_JIRA_SITE_URL", value = var.jira_site_url },
        { name = "ZENDESK_SUBDOMAIN", value = var.zendesk_subdomain },
        { name = "ZENDESK_SCOPE", value = "hc:read organizations:read tickets:read tickets:write users:read webhooks:read" },
        {
          name  = "COPILOT_DATASET_PATH"
          value = "data/support-cases.json"
        }
      ]
      secrets = [
        {
          name      = "COPILOT_DATABASE_USER"
          valueFrom = "${var.database_app_secret_arn}:username::"
        },
        {
          name      = "COPILOT_DATABASE_PASSWORD"
          valueFrom = "${var.database_app_secret_arn}:password::"
        },
        {
          name      = "ZENDESK_CLIENT_ID"
          valueFrom = "${var.zendesk_secret_arn}:client_id::"
        },
        {
          name      = "ZENDESK_CLIENT_SECRET"
          valueFrom = "${var.zendesk_secret_arn}:client_secret::"
        },
        {
          name      = "COPILOT_ZENDESK_SIDEBAR_TOKEN"
          valueFrom = "${var.integration_secret_arn}:zendesk_sidebar_token::"
        },
        {
          name      = "COPILOT_JIRA_CALLBACK_TOKEN"
          valueFrom = "${var.integration_secret_arn}:jira_callback_token::"
        },
      ]
      mountPoints = [{
        sourceVolume  = "api-tmp"
        containerPath = "/tmp"
        readOnly      = false
      }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }
      healthCheck = {
        command = [
          "CMD-SHELL",
          "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/healthz', timeout=2)\"",
        ]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    },
  ])

  volume {
    name = "api-tmp"
  }
}

resource "aws_ecs_task_definition" "migration" {
  family                   = "${local.name}-migration"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.migration_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name                   = "migration"
    image                  = var.api_image_uri
    essential              = true
    readonlyRootFilesystem = true
    entryPoint             = ["/app/.venv/bin/python"]
    command                = ["/app/scripts/run-production-migrations.py"]
    environment = [
      { name = "COPILOT_DATABASE_HOST", value = aws_db_instance.database.address },
      { name = "COPILOT_DATABASE_PORT", value = tostring(aws_db_instance.database.port) },
      { name = "COPILOT_DATABASE_NAME", value = aws_db_instance.database.db_name },
      { name = "COPILOT_DATABASE_USER", value = aws_db_instance.database.username },
    ]
    secrets = [
      {
        name      = "COPILOT_DATABASE_PASSWORD"
        valueFrom = "${aws_db_instance.database.master_user_secret[0].secret_arn}:password::"
      },
      {
        name      = "COPILOT_DATABASE_APP_USER"
        valueFrom = "${var.database_app_secret_arn}:username::"
      },
      {
        name      = "COPILOT_DATABASE_APP_PASSWORD"
        valueFrom = "${var.database_app_secret_arn}:password::"
      },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.migration.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "migration"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${local.name}-web"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.web_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  volume {
    name = "nginx-cache"
  }

  volume {
    name = "nginx-run"
  }

  volume {
    name = "nginx-tmp"
  }

  container_definitions = jsonencode([{
    name                   = "web"
    image                  = var.web_image_uri
    essential              = true
    readonlyRootFilesystem = true
    portMappings = [{
      containerPort = 8080
      protocol      = "tcp"
    }]
    mountPoints = [
      {
        sourceVolume  = "nginx-cache"
        containerPath = "/var/cache/nginx"
        readOnly      = false
      },
      {
        sourceVolume  = "nginx-run"
        containerPath = "/var/run"
        readOnly      = false
      },
      {
        sourceVolume  = "nginx-tmp"
        containerPath = "/tmp"
        readOnly      = false
      },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.web.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "web"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.app.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = var.assign_public_ip
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [
    aws_lb_listener_rule.api,
    aws_lb_listener_rule.provider_integrations,
  ]
}

resource "aws_ecs_service" "web" {
  name            = "web"
  cluster         = aws_ecs_cluster.app.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = var.web_desired_count
  launch_type     = "FARGATE"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = var.assign_public_ip
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 8080
  }

  depends_on = [aws_lb_listener.https]
}

resource "aws_appautoscaling_target" "api" {
  max_capacity       = 6
  min_capacity       = var.api_desired_count
  resource_id        = "service/${aws_ecs_cluster.app.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${local.name}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 65
    scale_in_cooldown  = 120
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
