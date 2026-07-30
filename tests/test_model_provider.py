from typing import Any

import pytest

from copilot.domain import Citation, SupportCase
from copilot.model_provider import BedrockDraftProvider, DraftProviderError


class FakeBedrockClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.request: dict[str, Any] | None = None

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.request = kwargs
        return {
            "output": {
                "message": {
                    "content": [
                        {"reasoningContent": {"reasoningText": {"text": "hidden"}}},
                        {"text": self.text},
                    ]
                }
            }
        }


def citation() -> Citation:
    return Citation(
        document_id="A1",
        chunk_id="A1:0",
        title="Password reset",
        score=0.9,
        excerpt="Use the verified password reset link and never request a password.",
    )


def test_bedrock_provider_returns_only_grounded_text() -> None:
    client = FakeBedrockClient(
        "Please use the verified password reset link. A human should review this note. [A1]"
    )
    provider = BedrockDraftProvider(
        region="ap-southeast-2",
        model_id="openai.gpt-oss-20b-1:0",
        max_output_tokens=180,
        client=client,
    )

    draft = provider.draft(
        SupportCase(
            id="S1",
            subject="Password reset for person@example.com",
            body="Please help.",
        ),
        [citation()],
    )

    assert draft.endswith("[A1]")
    assert "hidden" not in draft
    assert client.request is not None
    prompt = client.request["messages"][0]["content"][0]["text"]
    assert "person@example.com" not in prompt
    assert "[EMAIL REDACTED]" in prompt
    assert client.request["inferenceConfig"]["maxTokens"] == 180
    assert client.request["inferenceConfig"]["temperature"] == 0
    assert client.request["additionalModelRequestFields"] == {"reasoning_effort": "low"}


def test_bedrock_provider_rejects_output_without_allowed_citation() -> None:
    provider = BedrockDraftProvider(
        region="ap-southeast-2",
        model_id="openai.gpt-oss-20b-1:0",
        max_output_tokens=180,
        client=FakeBedrockClient("Try the reset link."),
    )

    with pytest.raises(DraftProviderError, match="approved citation"):
        provider.draft(
            SupportCase(id="S1", subject="Password reset", body="Please help."),
            [citation()],
        )


def test_bedrock_provider_rejects_unknown_citation_marker() -> None:
    provider = BedrockDraftProvider(
        region="ap-southeast-2",
        model_id="openai.gpt-oss-20b-1:0",
        max_output_tokens=180,
        client=FakeBedrockClient("Use the reset link. [A1] [UNAPPROVED]"),
    )

    with pytest.raises(DraftProviderError, match="unapproved citation"):
        provider.draft(
            SupportCase(id="S1", subject="Password reset", body="Please help."),
            [citation()],
        )


def test_bedrock_provider_rejects_blank_model_output() -> None:
    provider = BedrockDraftProvider(
        region="ap-southeast-2",
        model_id="openai.gpt-oss-20b-1:0",
        max_output_tokens=180,
        client=FakeBedrockClient(""),
    )

    with pytest.raises(DraftProviderError, match="no usable text"):
        provider.draft(
            SupportCase(id="S1", subject="Password reset", body="Please help."),
            [citation()],
        )
