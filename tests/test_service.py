from copilot.config import Settings
from copilot.domain import KnowledgeDocument, SupportCase
from copilot.model_provider import DraftProviderError
from copilot.retrieval import HybridRetriever
from copilot.service import CopilotService
from copilot.storage import MemoryStore


def test_escalated_risk_case_does_not_generate_draft() -> None:
    documents = [
        KnowledgeDocument(
            id="A1",
            title="Refund policy",
            body="Duplicate charges above AUD 100 require billing specialist review.",
        )
    ]
    service = CopilotService(
        Settings(environment="test", confidence_threshold=0),
        MemoryStore(),
        HybridRetriever(documents),
    )

    suggestion = service.preview(
        SupportCase(
            id="S1",
            subject="Duplicate charge",
            body="Please refund $240 for the duplicate charge.",
        )
    )

    assert suggestion.route == "escalate"
    assert suggestion.draft is None
    assert "financial_review" in {risk.code for risk in suggestion.risks}


def test_no_citations_escalate_even_with_zero_threshold() -> None:
    service = CopilotService(
        Settings(environment="test", confidence_threshold=0),
        MemoryStore(),
        HybridRetriever([]),
    )

    suggestion = service.preview(
        SupportCase(id="S1", subject="Unknown issue", body="No approved knowledge matches.")
    )

    assert suggestion.route == "escalate"
    assert suggestion.draft is None
    assert "low_confidence" in {risk.code for risk in suggestion.risks}


def test_credential_in_subject_blocks_draft_even_with_matching_guidance() -> None:
    service = CopilotService(
        Settings(environment="test", confidence_threshold=0),
        MemoryStore(),
        HybridRetriever(
            [
                KnowledgeDocument(
                    id="A1",
                    title="Password reset",
                    body="Use the approved password reset flow for account access issues.",
                )
            ]
        ),
    )

    suggestion = service.preview(
        SupportCase(
            id="S1",
            subject="My password is hunter2",
            body="I need help signing in.",
        )
    )

    assert suggestion.route == "block"
    assert suggestion.draft is None
    assert "credential_exposure" in {risk.code for risk in suggestion.risks}


def test_model_failure_escalates_without_leaking_provider_error() -> None:
    class UnavailableProvider:
        name = "unavailable-test-provider"

        def draft(self, case: SupportCase, citations: list[object]) -> str:
            raise DraftProviderError("private provider detail")

    service = CopilotService(
        Settings(environment="test", confidence_threshold=0),
        MemoryStore(),
        HybridRetriever(
            [
                KnowledgeDocument(
                    id="A1",
                    title="Password reset",
                    body="Use the approved password reset flow for account access issues.",
                )
            ]
        ),
        provider=UnavailableProvider(),  # type: ignore[arg-type]
    )

    suggestion = service.preview(
        SupportCase(id="S1", subject="Password reset", body="I need help signing in.")
    )

    assert suggestion.route == "escalate"
    assert suggestion.draft is None
    finding = next(risk for risk in suggestion.risks if risk.code == "model_unavailable")
    assert "private provider detail" not in finding.message
