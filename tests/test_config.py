import pytest
from pydantic import ValidationError

from copilot.config import Settings


def test_production_requires_api_key_and_database() -> None:
    with pytest.raises(ValidationError, match="COPILOT_AUTH_MODE"):
        Settings(environment="production")


def test_production_accepts_explicit_security_configuration() -> None:
    settings = Settings(
        environment="production",
        auth_mode="bearer",
        api_key="test-only-secret",
        database_url="postgresql+asyncpg://copilot:copilot@database/copilot",
    )

    assert settings.environment == "production"


def test_bedrock_provider_requires_region() -> None:
    with pytest.raises(ValidationError, match="COPILOT_AWS_REGION"):
        Settings(environment="test", model_provider="bedrock")


def test_bedrock_provider_accepts_bounded_configuration() -> None:
    settings = Settings(
        environment="test",
        model_provider="bedrock",
        aws_region="ap-southeast-2",
        model_max_output_tokens=300,
    )

    assert settings.bedrock_model_id == "openai.gpt-oss-20b-1:0"
    assert settings.model_max_output_tokens == 300


def test_handoff_requires_a_positive_ticket_allowlist() -> None:
    with pytest.raises(ValidationError, match="HANDOFF_ALLOWED_TICKET_IDS"):
        Settings(
            environment="test",
            handoff_enabled=True,
            zendesk_sidebar_token="sidebar-token",
            jira_callback_token="callback-token",
        )
    with pytest.raises(ValidationError, match="positive Zendesk ticket IDs"):
        Settings(
            environment="test",
            handoff_enabled=True,
            zendesk_sidebar_token="sidebar-token",
            jira_callback_token="callback-token",
            zendesk_handoff_allowed_ticket_ids={"0"},
        )

    settings = Settings(
        environment="test",
        handoff_enabled=True,
        zendesk_sidebar_token="sidebar-token",
        jira_callback_token="callback-token",
        zendesk_handoff_allowed_ticket_ids={"6"},
    )
    assert settings.zendesk_handoff_allowed_ticket_ids == frozenset({"6"})
