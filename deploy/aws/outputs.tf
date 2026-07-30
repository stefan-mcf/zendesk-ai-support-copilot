output "application_url" {
  description = "Certificate-valid application URL for the configured DNS hostname."
  value       = "https://${var.application_domain}"
}

output "load_balancer_dns_name" {
  description = "Raw load balancer DNS target for the external application DNS record."
  value       = aws_lb.app.dns_name
}

output "load_balancer_arn" {
  value = aws_lb.app.arn
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.app.name
}

output "migration_task_definition_arn" {
  description = "One-off task definition that alone receives the RDS master credential."
  value       = aws_ecs_task_definition.migration.arn
}

output "migration_run_configuration" {
  description = "Inputs for an approved one-off ECS migration task run."
  value = {
    cluster_id         = aws_ecs_cluster.app.id
    task_definition    = aws_ecs_task_definition.migration.arn
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.tasks.id]
    assign_public_ip   = var.assign_public_ip
  }
}

output "database_endpoint" {
  value     = aws_db_instance.database.endpoint
  sensitive = true
}

output "deployment_identity" {
  value = {
    account_id = data.aws_caller_identity.current.account_id
    region     = var.aws_region
    project    = local.name
  }
}
