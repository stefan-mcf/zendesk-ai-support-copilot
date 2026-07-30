import asyncio
from pathlib import Path

import pytest

from copilot.config import Settings
from copilot.domain import EngineeringHandoff, Suggestion, SupportCase
from copilot.handoff import (
    EngineeringHandoffService,
    HandoffConflictError,
    HandoffPolicyError,
)
from copilot.storage import MemoryStore
from copilot.zendesk_adapter import ZendeskDispatchReceipt


class RecordingWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def approve_engineering_escalation(
        self,
        ticket_id: str,
        *,
        handoff_id: str,
        escalation_tag: str,
    ) -> ZendeskDispatchReceipt:
        self.calls.append((ticket_id, handoff_id, escalation_tag))
        return ZendeskDispatchReceipt(
            state="completed",
            command="tickets update",
            provider_id=ticket_id,
            provider_status=200,
            readback_passed=True,
        )


def enabled_settings() -> Settings:
    return Settings(
        environment="test",
        handoff_enabled=True,
        zendesk_sidebar_token="sidebar-token",
        jira_callback_token="callback-token",
        zendesk_handoff_allowed_ticket_ids={"41"},
        dataset_path=Path("unused.json"),
    )


async def escalated_service() -> tuple[
    EngineeringHandoffService,
    MemoryStore,
    RecordingWriter,
]:
    store = MemoryStore()
    case = SupportCase(
        id="ZD-41",
        subject="Widespread service incident",
        body="Every team member reports an outage.",
        source="zendesk_sidebar",
        source_ref="example:ticket:41",
    )
    await store.upsert_case(case)
    await store.save_suggestion(
        Suggestion(
            case_id=case.id,
            route="escalate",
            draft=None,
            confidence=0.7,
            citations=[],
            risks=[],
        )
    )
    writer = RecordingWriter()
    return EngineeringHandoffService(enabled_settings(), store, writer), store, writer


async def test_human_approval_dispatches_once_and_callback_completes() -> None:
    service, store, writer = await escalated_service()

    dispatched = await service.approve(
        "ZD-41",
        approved_by="agent-7",
        approval_source="zendesk_sidebar",
        request_id="request-1",
    )
    duplicate = await service.approve(
        "ZD-41",
        approved_by="agent-7",
        approval_source="zendesk_sidebar",
        request_id="request-2",
    )
    completed = await service.complete_from_jira(
        provider_ticket_id="41",
        jira_issue_key="SUP-12",
        request_id="request-3",
    )
    replay = await service.complete_from_jira(
        provider_ticket_id="41",
        jira_issue_key="SUP-12",
        request_id="request-4",
    )

    assert dispatched.status == "dispatched"
    assert duplicate.id == dispatched.id
    assert len(writer.calls) == 1
    assert completed.status == "completed"
    assert completed.jira_issue_key == "SUP-12"
    assert completed.jira_issue_url == "https://example.atlassian.net/browse/SUP-12"
    assert replay == completed
    assert [event.outcome for event in await store.list_audit("ZD-41")] == [
        "human_approved",
        "verified_and_dispatched",
        "jira_issue_verified",
    ]


async def test_concurrent_approvals_claim_once_before_provider_write() -> None:
    class BlockingWriter(RecordingWriter):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def approve_engineering_escalation(
            self,
            ticket_id: str,
            *,
            handoff_id: str,
            escalation_tag: str,
        ) -> ZendeskDispatchReceipt:
            self.calls.append((ticket_id, handoff_id, escalation_tag))
            self.started.set()
            await self.release.wait()
            return ZendeskDispatchReceipt(
                state="completed",
                command="tickets update",
                provider_id=ticket_id,
                provider_status=200,
                readback_passed=True,
            )

    service, store, _ = await escalated_service()
    writer = BlockingWriter()
    service = EngineeringHandoffService(enabled_settings(), store, writer)

    first = asyncio.create_task(
        service.approve(
            "ZD-41",
            approved_by="agent-7",
            approval_source="zendesk_sidebar",
            request_id="request-1",
        )
    )
    await writer.started.wait()
    duplicate = await service.approve(
        "ZD-41",
        approved_by="agent-7",
        approval_source="zendesk_sidebar",
        request_id="request-2",
    )
    writer.release.set()
    dispatched = await first

    assert duplicate.id == dispatched.id
    assert duplicate.status == "approved"
    assert dispatched.status == "dispatched"
    assert len(writer.calls) == 1


async def test_fast_jira_callback_cannot_be_overwritten_by_dispatch_transition() -> None:
    class DispatchBarrierStore(MemoryStore):
        def __init__(self) -> None:
            super().__init__()
            self.dispatch_started = asyncio.Event()
            self.release_dispatch = asyncio.Event()

        async def transition_handoff(
            self,
            handoff: EngineeringHandoff,
            *,
            expected_statuses: frozenset[str],
        ) -> EngineeringHandoff | None:
            if handoff.status == "dispatched":
                self.dispatch_started.set()
                await self.release_dispatch.wait()
            return await super().transition_handoff(
                handoff,
                expected_statuses=expected_statuses,
            )

    _, seeded_store, writer = await escalated_service()
    store = DispatchBarrierStore()
    case = await seeded_store.get_case("ZD-41")
    suggestion = await seeded_store.get_suggestion("ZD-41")
    assert case is not None
    assert suggestion is not None
    await store.upsert_case(case)
    await store.save_suggestion(suggestion)
    service = EngineeringHandoffService(enabled_settings(), store, writer)

    approval = asyncio.create_task(
        service.approve(
            "ZD-41",
            approved_by="agent-7",
            approval_source="zendesk_sidebar",
            request_id="request-1",
        )
    )
    await store.dispatch_started.wait()
    callback = await service.complete_from_jira(
        provider_ticket_id="41",
        jira_issue_key="SUP-12",
        request_id="request-2",
    )
    store.release_dispatch.set()
    approval_result = await approval

    assert callback.status == "completed"
    assert approval_result == callback
    assert await store.get_handoff("ZD-41") == callback


async def test_handoff_rejects_non_escalation_and_mismatched_callback() -> None:
    service, store, writer = await escalated_service()
    await store.save_suggestion(
        Suggestion(
            case_id="ZD-41",
            route="draft",
            draft="Review this draft.",
            confidence=0.8,
            citations=[],
            risks=[],
        )
    )

    with pytest.raises(HandoffPolicyError):
        await service.approve(
            "ZD-41",
            approved_by="agent-7",
            approval_source="zendesk_sidebar",
            request_id="request-1",
        )

    assert writer.calls == []

    await store.save_suggestion(
        Suggestion(
            case_id="ZD-41",
            route="escalate",
            draft=None,
            confidence=0.7,
            citations=[],
            risks=[],
        )
    )
    await service.approve(
        "ZD-41",
        approved_by="agent-7",
        approval_source="zendesk_sidebar",
        request_id="request-2",
    )
    await service.complete_from_jira(
        provider_ticket_id="41",
        jira_issue_key="SUP-12",
        request_id="request-3",
    )
    with pytest.raises(HandoffConflictError):
        await service.complete_from_jira(
            provider_ticket_id="41",
            jira_issue_key="SUP-13",
            request_id="request-4",
        )
