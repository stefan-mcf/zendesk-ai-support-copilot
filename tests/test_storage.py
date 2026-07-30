from copilot.domain import EngineeringHandoff, KnowledgeDocument, Suggestion, SupportCase
from copilot.storage import MemoryStore


async def test_seed_is_idempotent_and_preserves_runtime_state() -> None:
    store = MemoryStore()
    documents = [KnowledgeDocument(id="A1", title="Fixture", body="Approved guidance.")]
    cases = [SupportCase(id="S1", subject="Fixture", body="Synthetic case.")]
    await store.seed(documents, cases)
    suggestion = Suggestion(
        case_id="S1",
        route="draft",
        draft="Approved guidance. [A1]",
        confidence=1,
        citations=[],
        risks=[],
    )
    await store.save_suggestion(suggestion)

    await store.seed(documents, cases)

    assert await store.get_suggestion("S1") == suggestion


async def test_upsert_case_adds_and_replaces_controlled_ingestion() -> None:
    store = MemoryStore()
    original = SupportCase(id="ZD-4", subject="Original", body="Synthetic case.")
    updated = SupportCase(id="ZD-4", subject="Updated", body="Synthetic case.")

    await store.upsert_case(original)
    await store.upsert_case(updated)

    assert await store.get_case("ZD-4") == updated


async def test_handoff_round_trip_is_keyed_by_case() -> None:
    store = MemoryStore()
    handoff = EngineeringHandoff(
        id="handoff_1",
        case_id="ZD-4",
        provider_ticket_id="4",
        status="approved",
        approved_by="agent-7",
        approval_source="zendesk_sidebar",
    )

    await store.save_handoff(handoff)

    assert await store.get_handoff("ZD-4") == handoff


async def test_handoff_claim_is_atomic_for_memory_store() -> None:
    store = MemoryStore()
    first = EngineeringHandoff(
        id="handoff_1",
        case_id="ZD-4",
        provider_ticket_id="4",
        status="approved",
        approved_by="agent-1",
        approval_source="zendesk_sidebar",
    )
    second = first.model_copy(update={"id": "handoff_2"})

    assert await store.claim_handoff(first) is True
    assert await store.claim_handoff(second) is False
    assert await store.get_handoff("ZD-4") == first

    completed = first.model_copy(
        update={
            "status": "completed",
            "jira_issue_key": "SUP-3",
        }
    )
    assert (
        await store.transition_handoff(
            completed,
            expected_statuses=frozenset({"dispatched"}),
        )
        is None
    )
    assert (
        await store.transition_handoff(
            completed,
            expected_statuses=frozenset({"approved"}),
        )
        == completed
    )
