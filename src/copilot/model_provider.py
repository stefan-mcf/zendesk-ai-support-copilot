import re
from typing import Any, Protocol

import boto3
from botocore.config import Config

from copilot.domain import Citation, SupportCase
from copilot.guardrails import redact_text


class DraftProvider(Protocol):
    name: str

    def draft(self, case: SupportCase, citations: list[Citation]) -> str:
        """Return a private support draft grounded only in supplied citations."""


class DraftProviderError(RuntimeError):
    """Safe provider failure that must route to human review."""


class DeterministicDraftProvider:
    name = "deterministic-grounded-v1"

    def draft(self, case: SupportCase, citations: list[Citation]) -> str:
        if not citations:
            raise ValueError("citations are required for a grounded draft")
        top = citations[0]
        safe_subject = redact_text(case.subject)
        evidence = top.excerpt.split(".")[0].strip()
        return (
            f"Thanks for reporting “{safe_subject}”. "
            f"Based on the approved guidance, {evidence.lower()}. "
            f"If that does not resolve the issue, I’ll route it for human review. "
            f"[{top.document_id}]"
        )


class BedrockDraftProvider:
    name = "aws-bedrock-openai-gpt-oss"

    def __init__(
        self,
        region: str,
        model_id: str,
        max_output_tokens: int,
        timeout_seconds: int = 30,
        client: Any | None = None,
    ) -> None:
        self.region = region
        self.model_id = model_id
        self.max_output_tokens = max_output_tokens
        self.client = client or boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(
                connect_timeout=5,
                read_timeout=timeout_seconds,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    def draft(self, case: SupportCase, citations: list[Citation]) -> str:
        if not citations:
            raise DraftProviderError("citations are required for a grounded draft")
        prompt = _bedrock_prompt(case, citations)
        try:
            response = self.client.converse(
                modelId=self.model_id,
                system=[
                    {
                        "text": (
                            "You draft private internal customer-support notes. "
                            "Use only the supplied approved evidence. Never invent an ETA, "
                            "refund, action, policy, or diagnosis. Keep the note under 90 words, "
                            "state when human review is needed, and include at least one supplied "
                            "citation marker exactly as written. Return only the draft."
                        )
                    }
                ],
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={
                    "maxTokens": self.max_output_tokens,
                    "temperature": 0,
                },
                additionalModelRequestFields={"reasoning_effort": "low"},
            )
        except Exception as error:
            raise DraftProviderError("hosted model request failed") from error
        output = response.get("output", {}).get("message", {}).get("content", [])
        text = "\n".join(
            str(block["text"]).strip()
            for block in output
            if isinstance(block, dict) and str(block.get("text", "")).strip()
        ).strip()
        if not text:
            raise DraftProviderError("hosted model returned no usable text")
        allowed_markers = {f"[{citation.document_id}]" for citation in citations}
        if not any(marker in text for marker in allowed_markers):
            raise DraftProviderError("hosted model output omitted an approved citation")
        actual_markers = {f"[{value}]" for value in re.findall(r"\[([A-Za-z0-9_-]+)\]", text)}
        if not actual_markers.issubset(allowed_markers):
            raise DraftProviderError("hosted model output included an unapproved citation")
        return redact_text(text)


def _bedrock_prompt(case: SupportCase, citations: list[Citation]) -> str:
    evidence = "\n".join(
        (f"- [{citation.document_id}] {citation.title}: {redact_text(citation.excerpt)}")
        for citation in citations
    )
    return (
        "CASE\n"
        f"Subject: {redact_text(case.subject)}\n"
        f"Details: {redact_text(case.body)}\n\n"
        "APPROVED EVIDENCE\n"
        f"{evidence}\n\n"
        "Write a proposed private internal note for a support agent to review."
    )
