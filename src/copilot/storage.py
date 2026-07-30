import asyncio
from collections.abc import Iterable
from typing import Protocol

from copilot.domain import (
    AuditEvent,
    EngineeringHandoff,
    KnowledgeDocument,
    Suggestion,
    SupportCase,
)


class Store(Protocol):
    async def seed(
        self,
        documents: Iterable[KnowledgeDocument],
        cases: Iterable[SupportCase],
    ) -> None: ...

    async def replace_seed(
        self,
        documents: Iterable[KnowledgeDocument],
        cases: Iterable[SupportCase],
    ) -> None: ...

    async def list_cases(self) -> list[SupportCase]: ...

    async def get_case(self, case_id: str) -> SupportCase | None: ...

    async def upsert_case(self, case: SupportCase) -> None: ...

    async def save_suggestion(self, suggestion: Suggestion) -> None: ...

    async def get_suggestion(self, case_id: str) -> Suggestion | None: ...

    async def save_handoff(self, handoff: EngineeringHandoff) -> None: ...

    async def claim_handoff(self, handoff: EngineeringHandoff) -> bool: ...

    async def transition_handoff(
        self,
        handoff: EngineeringHandoff,
        *,
        expected_statuses: frozenset[str],
    ) -> EngineeringHandoff | None: ...

    async def get_handoff(self, case_id: str) -> EngineeringHandoff | None: ...

    async def append_audit(self, event: AuditEvent) -> None: ...

    async def list_audit(self, case_id: str) -> list[AuditEvent]: ...


class MemoryStore:
    def __init__(self) -> None:
        self.documents: dict[str, KnowledgeDocument] = {}
        self.cases: dict[str, SupportCase] = {}
        self.suggestions: dict[str, Suggestion] = {}
        self.handoffs: dict[str, EngineeringHandoff] = {}
        self._handoff_claim_lock = asyncio.Lock()
        self.audit: list[AuditEvent] = []

    async def seed(
        self,
        documents: Iterable[KnowledgeDocument],
        cases: Iterable[SupportCase],
    ) -> None:
        if not self.cases:
            await self.replace_seed(documents, cases)

    async def replace_seed(
        self,
        documents: Iterable[KnowledgeDocument],
        cases: Iterable[SupportCase],
    ) -> None:
        self.documents = {document.id: document for document in documents}
        self.cases = {case.id: case for case in cases}
        self.suggestions = {}
        self.handoffs = {}
        self.audit = []

    async def list_cases(self) -> list[SupportCase]:
        return sorted(self.cases.values(), key=lambda case: case.id)

    async def get_case(self, case_id: str) -> SupportCase | None:
        return self.cases.get(case_id)

    async def upsert_case(self, case: SupportCase) -> None:
        self.cases[case.id] = case

    async def save_suggestion(self, suggestion: Suggestion) -> None:
        self.suggestions[suggestion.case_id] = suggestion

    async def get_suggestion(self, case_id: str) -> Suggestion | None:
        return self.suggestions.get(case_id)

    async def save_handoff(self, handoff: EngineeringHandoff) -> None:
        self.handoffs[handoff.case_id] = handoff

    async def claim_handoff(self, handoff: EngineeringHandoff) -> bool:
        async with self._handoff_claim_lock:
            if handoff.case_id in self.handoffs:
                return False
            self.handoffs[handoff.case_id] = handoff
            return True

    async def transition_handoff(
        self,
        handoff: EngineeringHandoff,
        *,
        expected_statuses: frozenset[str],
    ) -> EngineeringHandoff | None:
        async with self._handoff_claim_lock:
            current = self.handoffs.get(handoff.case_id)
            if current is None or current.status not in expected_statuses:
                return None
            self.handoffs[handoff.case_id] = handoff
            return handoff

    async def get_handoff(self, case_id: str) -> EngineeringHandoff | None:
        return self.handoffs.get(case_id)

    async def append_audit(self, event: AuditEvent) -> None:
        self.audit.append(event)

    async def list_audit(self, case_id: str) -> list[AuditEvent]:
        return [event for event in self.audit if event.subject_id == case_id]
