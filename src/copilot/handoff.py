import uuid
from typing import Literal, Protocol

import structlog

from copilot.config import Settings
from copilot.domain import AuditEvent, EngineeringHandoff, SupportCase, utc_now
from copilot.storage import Store
from copilot.zendesk_adapter import ZendeskDispatchReceipt


class HandoffDisabledError(RuntimeError):
    pass


class HandoffPolicyError(ValueError):
    pass


class HandoffNotFoundError(LookupError):
    pass


class HandoffConflictError(RuntimeError):
    pass


class HandoffDispatchError(RuntimeError):
    pass


class EscalationWriter(Protocol):
    async def approve_engineering_escalation(
        self,
        ticket_id: str,
        *,
        handoff_id: str,
        escalation_tag: str,
    ) -> ZendeskDispatchReceipt: ...


class EngineeringHandoffService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        writer: EscalationWriter,
    ) -> None:
        self.settings = settings
        self.store = store
        self.writer = writer

    async def approve(
        self,
        case_id: str,
        *,
        approved_by: str,
        approval_source: Literal["copilot_web", "zendesk_sidebar"],
        request_id: str,
    ) -> EngineeringHandoff:
        if not self.settings.handoff_enabled:
            raise HandoffDisabledError("Engineering handoffs are not enabled.")

        case = await self.store.get_case(case_id)
        if case is None:
            raise HandoffNotFoundError("Case not found.")
        ticket_id = _provider_ticket_id(case)
        if ticket_id not in self.settings.zendesk_handoff_allowed_ticket_ids:
            raise HandoffPolicyError("Zendesk ticket is outside the configured handoff scope.")

        suggestion = await self.store.get_suggestion(case_id)
        if suggestion is None:
            raise HandoffPolicyError("Generate and review a suggestion before escalation.")
        if suggestion.route != "escalate" or not suggestion.review_required:
            raise HandoffPolicyError(
                "Only a reviewed engineering-escalation decision can be approved."
            )

        now = utc_now()
        handoff = EngineeringHandoff(
            id=f"handoff_{uuid.uuid4().hex}",
            case_id=case_id,
            provider_ticket_id=ticket_id,
            status="approved",
            approved_by=approved_by,
            approval_source=approval_source,
            created_at=now,
            updated_at=now,
        )
        if not await self.store.claim_handoff(handoff):
            existing = await self.store.get_handoff(case_id)
            if existing is not None and existing.status in {"approved", "dispatched", "completed"}:
                return existing
            raise HandoffConflictError(
                "The previous dispatch failed and requires operator reconciliation."
            )
        await self._audit(
            handoff,
            request_id=request_id,
            outcome="human_approved",
            event_type="handoff.engineering_approved",
        )

        try:
            receipt = await self.writer.approve_engineering_escalation(
                ticket_id,
                handoff_id=handoff.id,
                escalation_tag=self.settings.zendesk_escalation_tag,
            )
        except Exception as error:
            failure_detail = f"{type(error).__name__}: {str(error)[:160]}"
            failed = handoff.model_copy(
                update={
                    "status": "failed",
                    "failure_code": "zendesk_dispatch_failed",
                    "updated_at": utc_now(),
                }
            )
            transitioned = await self.store.transition_handoff(
                failed,
                expected_statuses=frozenset({"approved"}),
            )
            if transitioned is None:
                current = await self.store.get_handoff(case_id)
                if current is not None and current.status == "completed":
                    return current
                raise HandoffConflictError(
                    "Handoff state changed while the Zendesk dispatch was being reconciled."
                ) from error
            await self._audit(
                transitioned,
                request_id=request_id,
                outcome="failed",
                event_type="handoff.zendesk_dispatch",
                failure_detail=failure_detail,
            )
            raise HandoffDispatchError("Zendesk escalation dispatch failed.") from error

        dispatched = handoff.model_copy(
            update={
                "status": "dispatched",
                "zendesk_receipt_state": receipt.state,
                "updated_at": utc_now(),
            }
        )
        transitioned = await self.store.transition_handoff(
            dispatched,
            expected_statuses=frozenset({"approved"}),
        )
        if transitioned is None:
            current = await self.store.get_handoff(case_id)
            if current is not None and current.status == "completed":
                return current
            if current is not None and current.status == "dispatched":
                return current
            raise HandoffConflictError(
                "Handoff state changed before the Zendesk dispatch could be recorded."
            )
        await self._audit(
            transitioned,
            request_id=request_id,
            outcome="verified_and_dispatched",
            event_type="handoff.zendesk_dispatch",
        )
        return transitioned

    async def complete_from_jira(
        self,
        *,
        provider_ticket_id: str,
        jira_issue_key: str,
        request_id: str,
    ) -> EngineeringHandoff:
        expected_prefix = f"{self.settings.jira_project_key}-"
        if not (
            provider_ticket_id.isdigit()
            and jira_issue_key.startswith(expected_prefix)
            and jira_issue_key.removeprefix(expected_prefix).isdigit()
        ):
            raise HandoffPolicyError("Jira callback identifiers are outside the configured scope.")

        case_id = f"ZD-{provider_ticket_id}"
        for _ in range(3):
            handoff = await self.store.get_handoff(case_id)
            if handoff is None:
                raise HandoffNotFoundError("No approved handoff matches this Zendesk ticket.")
            if handoff.status == "failed":
                raise HandoffConflictError("A failed handoff cannot be completed by callback.")
            if handoff.status == "completed":
                if handoff.jira_issue_key == jira_issue_key:
                    return handoff
                raise HandoffConflictError("This handoff already has a different Jira issue.")

            completed = handoff.model_copy(
                update={
                    "status": "completed",
                    "jira_issue_key": jira_issue_key,
                    "jira_issue_url": (
                        f"{self.settings.jira_site_url.rstrip('/')}/browse/{jira_issue_key}"
                    ),
                    "failure_code": None,
                    "updated_at": utc_now(),
                }
            )
            transitioned = await self.store.transition_handoff(
                completed,
                expected_statuses=frozenset({handoff.status}),
            )
            if transitioned is not None:
                await self._audit(
                    transitioned,
                    request_id=request_id,
                    outcome="jira_issue_verified",
                    event_type="handoff.jira_completed",
                )
                return transitioned
        raise HandoffConflictError("Handoff state changed repeatedly during Jira callback.")

    async def _audit(
        self,
        handoff: EngineeringHandoff,
        *,
        request_id: str,
        outcome: str,
        event_type: str,
        failure_detail: str | None = None,
    ) -> None:
        metadata = {
            "handoff_id": handoff.id,
            "provider_ticket_id": handoff.provider_ticket_id,
            "handoff_status": handoff.status,
            "approval_source": handoff.approval_source,
            "jira_issue_key": handoff.jira_issue_key,
        }
        if failure_detail is not None:
            metadata["failure_detail"] = failure_detail
        await self.store.append_audit(
            AuditEvent(
                id=str(uuid.uuid4()),
                event_type=event_type,
                subject_id=handoff.case_id,
                request_id=request_id,
                outcome=outcome,
                policy_version="support-safety-v1",
                metadata=metadata,
            )
        )
        structlog.get_logger().info(
            "handoff_transition",
            request_id=request_id,
            case_id=handoff.case_id,
            handoff_id=handoff.id,
            provider_ticket_id=handoff.provider_ticket_id,
            handoff_status=handoff.status,
            event_type=event_type,
            outcome=outcome,
            jira_issue_key=handoff.jira_issue_key,
            failure_detail=failure_detail,
        )


def _provider_ticket_id(case: SupportCase) -> str:
    if case.source not in {"zendesk_live_controlled", "zendesk_sidebar"}:
        raise HandoffPolicyError("Engineering handoff requires a Zendesk-backed case.")
    source_ref = case.source_ref or ""
    marker = ":ticket:"
    if marker not in source_ref:
        raise HandoffPolicyError("Zendesk case source reference is invalid.")
    ticket_id = source_ref.rsplit(marker, maxsplit=1)[1]
    if not ticket_id.isdigit() or case.id != f"ZD-{ticket_id}":
        raise HandoffPolicyError("Zendesk case identity does not match its provider ticket.")
    return ticket_id
