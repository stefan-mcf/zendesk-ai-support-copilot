from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COPILOT_",
        env_file=".env",
        extra="ignore",
    )

    environment: str = "development"
    service_name: str = "sm-support-copilot"
    auth_mode: Literal["development", "bearer", "alb_oidc"] = "development"
    model_provider: Literal["deterministic", "bedrock"] = "deterministic"
    bedrock_model_id: str = "openai.gpt-oss-20b-1:0"
    model_max_output_tokens: int = Field(default=240, ge=64, le=300)
    model_timeout_seconds: int = Field(default=30, ge=5, le=60)
    api_key: str | None = None
    aws_region: str | None = None
    alb_arn: str | None = None
    alb_client_id: str | None = None
    database_url: str | None = None
    database_host: str | None = None
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "copilot"
    database_user: str | None = None
    database_password: str | None = None
    dataset_path: Path = Path("data/support-cases.json")
    zendesk_controlled_manifest_path: Path | None = None
    zendesk_subdomain: str = "example"
    handoff_enabled: bool = False
    zendesk_sidebar_token: str | None = None
    jira_callback_token: str | None = None
    zendesk_handoff_allowed_ticket_ids: frozenset[str] = frozenset()
    zendesk_escalation_tag: str = "engineering_escalation_approved"
    jira_project_key: str = "SUP"
    jira_site_url: str = "https://example.atlassian.net"
    retrieval_limit: int = Field(default=3, ge=1, le=10)
    confidence_threshold: float = Field(default=0.18, ge=0, le=1)
    zendesk_cli_path: Path = Path("zendesk-cli")
    log_level: str = "INFO"

    @model_validator(mode="after")
    def require_production_security(self) -> "Settings":
        if self.environment == "production" and self.auth_mode == "development":
            raise ValueError("COPILOT_AUTH_MODE must be bearer or alb_oidc in production")
        if self.auth_mode == "bearer" and not self.api_key:
            raise ValueError("COPILOT_API_KEY is required for bearer authentication")
        if self.auth_mode == "alb_oidc" and not all(
            [self.aws_region, self.alb_arn, self.alb_client_id]
        ):
            raise ValueError(
                "COPILOT_AWS_REGION, COPILOT_ALB_ARN, and COPILOT_ALB_CLIENT_ID "
                "are required for ALB OIDC"
            )
        if self.model_provider == "bedrock" and not self.aws_region:
            raise ValueError("COPILOT_AWS_REGION is required for the Bedrock model provider")
        if self.environment == "production" and not self.resolved_database_url:
            raise ValueError(
                "COPILOT_DATABASE_URL or database connection components are required in production"
            )
        if self.handoff_enabled:
            if not all([self.zendesk_sidebar_token, self.jira_callback_token]):
                raise ValueError(
                    "COPILOT_ZENDESK_SIDEBAR_TOKEN and COPILOT_JIRA_CALLBACK_TOKEN "
                    "are required when engineering handoffs are enabled"
                )
            if not self.zendesk_handoff_allowed_ticket_ids:
                raise ValueError(
                    "COPILOT_ZENDESK_HANDOFF_ALLOWED_TICKET_IDS must contain at least "
                    "one ticket when engineering handoffs are enabled"
                )
            if any(
                not ticket_id.isdigit() or int(ticket_id) < 1
                for ticket_id in self.zendesk_handoff_allowed_ticket_ids
            ):
                raise ValueError(
                    "COPILOT_ZENDESK_HANDOFF_ALLOWED_TICKET_IDS must contain only "
                    "positive Zendesk ticket IDs"
                )
        return self

    @property
    def resolved_database_url(self) -> str | None:
        if self.database_url:
            return self.database_url
        if not all(
            [
                self.database_host,
                self.database_user,
                self.database_password,
                self.database_name,
            ]
        ):
            return None
        user = quote_plus(self.database_user or "")
        password = quote_plus(self.database_password or "")
        return (
            f"postgresql+asyncpg://{user}:{password}@{self.database_host}:"
            f"{self.database_port}/{self.database_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
