resource "aws_sns_topic" "alerts" {
  count = var.alert_email == null ? 0 : 1
  name  = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == null ? 0 : 1
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  alarm_actions = var.alert_email == null ? [] : [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name}-alb-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_ELB_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.app.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "api_cpu" {
  alarm_name          = "${local.name}-api-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  dimensions = {
    ClusterName = aws_ecs_cluster.app.name
    ServiceName = aws_ecs_service.api.name
  }
}

resource "aws_cloudwatch_metric_alarm" "database_storage" {
  alarm_name          = "${local.name}-database-low-storage"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 5368709120
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.database.identifier
  }
}

resource "aws_cloudwatch_log_metric_filter" "model_unavailable" {
  name           = "${local.name}-model-unavailable"
  pattern        = "{ $.event = \"suggestion_generated\" && $.model_failure = true }"
  log_group_name = aws_cloudwatch_log_group.api.name

  metric_transformation {
    name      = "ModelUnavailable"
    namespace = "SMSystems/SupportCopilot"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "model_unavailable" {
  alarm_name          = "${local.name}-model-unavailable"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ModelUnavailable"
  namespace           = "SMSystems/SupportCopilot"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_log_metric_filter" "handoff_failed" {
  name           = "${local.name}-handoff-failed"
  pattern        = "{ $.event = \"handoff_transition\" && $.outcome = \"failed\" }"
  log_group_name = aws_cloudwatch_log_group.api.name

  metric_transformation {
    name      = "HandoffFailed"
    namespace = "SMSystems/SupportCopilot"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "handoff_failed" {
  alarm_name          = "${local.name}-handoff-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "HandoffFailed"
  namespace           = "SMSystems/SupportCopilot"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "bedrock_client_errors" {
  alarm_name          = "${local.name}-bedrock-client-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "InvocationClientErrors"
  namespace           = "AWS/Bedrock"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  dimensions = {
    ModelId = var.bedrock_model_id
  }
}

resource "aws_cloudwatch_metric_alarm" "bedrock_server_errors" {
  alarm_name          = "${local.name}-bedrock-server-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "InvocationServerErrors"
  namespace           = "AWS/Bedrock"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  dimensions = {
    ModelId = var.bedrock_model_id
  }
}

resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${local.name}-operations"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ECS service health"
          region = var.aws_region
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.app.name, "ServiceName", aws_ecs_service.api.name],
            [".", "MemoryUtilization", ".", ".", ".", "."],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ALB responses"
          region = var.aws_region
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", aws_lb.app.arn_suffix],
            [".", "TargetResponseTime", ".", "."],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Bedrock model operations"
          region = var.aws_region
          metrics = [
            ["AWS/Bedrock", "Invocations", "ModelId", var.bedrock_model_id],
            [".", "InvocationClientErrors", ".", "."],
            [".", "InvocationServerErrors", ".", "."],
            ["SMSystems/SupportCopilot", "ModelUnavailable"],
            [".", "HandoffFailed"],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "PostgreSQL"
          region = var.aws_region
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.database.identifier],
            [".", "DatabaseConnections", ".", "."],
            [".", "FreeStorageSpace", ".", "."],
          ]
        }
      },
    ]
  })
}
