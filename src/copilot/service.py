import asyncio
import uuid

import structlog

from copilot.config import Settings
from copilot.domain import AuditEvent, RiskFinding, Suggestion, SupportCase
from copilot.guardrails import inspect_case
from copilot.model_provider import (
    DeterministicDraftProvider,
    DraftProvider,
    DraftProviderError,
)
from copilot.retrieval import HybridRetriever
from copilot.storage import Store


class CopilotService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        retriever: HybridRetriever,
        provider: DraftProvider | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.retriever = retriever
        self.provider = provider or DeterministicDraftProvider()

    def preview(self, case: SupportCase) -> Suggestion:
        citations = self.retriever.search(
            f"{case.subject} {case.body}",
            limit=self.settings.retrieval_limit,
        )
        findings = inspect_case(case)
        confidence = citations[0].score if citations else 0.0
        blocking = any(finding.blocks_draft for finding in findings)
        escalation = any(
            finding.code in {"financial_review", "incident", "unsupported_eta"}
            for finding in findings
        )
        if blocking:
            route = "block"
            draft = None
        elif not citations or confidence < self.settings.confidence_threshold:
            route = "escalate"
            draft = None
            findings.append(
                RiskFinding(
                    code="low_confidence",
                    severity="high",
                    message="No sufficiently grounded knowledge was found.",
                )
            )
        elif escalation:
            route = "escalate"
            draft = None
        else:
            route = "draft"
            try:
                draft = self.provider.draft(case, citations)
            except DraftProviderError:
                route = "escalate"
                draft = None
                findings.append(
                    RiskFinding(
                        code="model_unavailable",
                        severity="high",
                        message="The hosted model did not return a safely grounded draft.",
                    )
                )
        return Suggestion(
            case_id=case.id,
            route=route,
            draft=draft,
            confidence=round(confidence, 4),
            citations=citations,
            risks=findings,
        )

    async def suggest(self, case: SupportCase, request_id: str) -> Suggestion:
        suggestion = await asyncio.to_thread(self.preview, case)
        await self.store.save_suggestion(suggestion)
        await self.store.append_audit(
            AuditEvent(
                id=str(uuid.uuid4()),
                event_type="suggestion.generated",
                subject_id=case.id,
                request_id=request_id,
                outcome=suggestion.route,
                policy_version=suggestion.policy_version,
                metadata={
                    "confidence": suggestion.confidence,
                    "citation_count": len(suggestion.citations),
                    "provider": self.provider.name,
                },
            )
        )
        risk_codes = sorted(risk.code for risk in suggestion.risks)
        structlog.get_logger().info(
            "suggestion_generated",
            request_id=request_id,
            case_id=case.id,
            route=suggestion.route,
            provider=self.provider.name,
            citation_count=len(suggestion.citations),
            risk_codes=risk_codes,
            model_failure="model_unavailable" in risk_codes,
        )
        return suggestion
