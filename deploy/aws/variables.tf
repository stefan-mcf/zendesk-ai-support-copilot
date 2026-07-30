variable "aws_region" {
  description = "AWS region for the deployment."
  type        = string
  default     = "ap-southeast-2"
}

variable "project_name" {
  description = "Short resource-name prefix."
  type        = string
  default     = "sm-support-copilot"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "production"
}

variable "vpc_id" {
  description = "Existing VPC ID."
  type        = string
}

variable "public_subnet_ids" {
  description = "At least two public subnet IDs for the load balancer."
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_ids) >= 2
    error_message = "Provide at least two public subnets."
  }
}

variable "private_subnet_ids" {
  description = "At least two task/database subnet IDs. Public task subnets require assign_public_ip=true."
  type        = list(string)

  validation {
    condition     = length(var.private_subnet_ids) >= 2
    error_message = "Provide at least two private subnets."
  }
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the HTTPS listener."
  type        = string
}

variable "application_domain" {
  description = "DNS hostname covered by the ACM certificate and routed to the load balancer."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9.-]+$", var.application_domain))
    error_message = "application_domain must be a hostname without a scheme or path."
  }
}

variable "cognito_user_pool_arn" {
  description = "Cognito user pool ARN used by ALB authentication."
  type        = string
}

variable "cognito_user_pool_client_id" {
  description = "Cognito app client ID configured for ALB authentication."
  type        = string
}

variable "cognito_user_pool_domain" {
  description = "Cognito user-pool domain prefix or custom domain."
  type        = string
}

variable "api_image_uri" {
  description = "Immutable API image URI, preferably pinned by digest."
  type        = string
}

variable "web_image_uri" {
  description = "Immutable web image URI, preferably pinned by digest."
  type        = string
}

variable "database_app_secret_arn" {
  description = "Secrets Manager ARN for JSON keys username/password of the least-privilege app role."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:secretsmanager:", var.database_app_secret_arn))
    error_message = "database_app_secret_arn must be a Secrets Manager ARN."
  }
}

variable "zendesk_secret_arn" {
  description = "Secrets Manager ARN for JSON keys client_id/client_secret used by the read-only runtime token."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:secretsmanager:", var.zendesk_secret_arn))
    error_message = "zendesk_secret_arn must be a Secrets Manager ARN."
  }
}

variable "integration_secret_arn" {
  description = "Secrets Manager ARN for the Zendesk sidebar and Jira callback tokens."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:secretsmanager:", var.integration_secret_arn))
    error_message = "integration_secret_arn must be a Secrets Manager ARN."
  }
}

variable "zendesk_subdomain" {
  type    = string
  default = "example"
}

variable "zendesk_handoff_allowed_ticket_ids" {
  description = "Exact Zendesk ticket IDs allowed to use the production engineering-handoff write path."
  type        = set(string)

  validation {
    condition = length(var.zendesk_handoff_allowed_ticket_ids) > 0 && alltrue([
      for ticket_id in var.zendesk_handoff_allowed_ticket_ids :
      can(regex("^[1-9][0-9]*$", ticket_id))
    ])
    error_message = "Provide at least one positive Zendesk ticket ID for the handoff allowlist."
  }
}

variable "jira_project_key" {
  type    = string
  default = "SUP"
}

variable "jira_site_url" {
  type    = string
  default = "https://example.atlassian.net"
}

variable "bedrock_model_id" {
  type    = string
  default = "openai.gpt-oss-20b-1:0"
}

variable "assign_public_ip" {
  description = "Assign public IPs to tasks when using public subnets without NAT."
  type        = bool
  default     = false
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "web_desired_count" {
  type    = number
  default = 2
}

variable "database_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "database_multi_az" {
  type    = bool
  default = false
}

variable "database_deletion_protection" {
  type    = bool
  default = true
}

variable "alert_email" {
  description = "Optional email endpoint for CloudWatch alarms."
  type        = string
  default     = null
}
