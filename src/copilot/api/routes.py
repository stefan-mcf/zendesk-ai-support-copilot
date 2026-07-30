import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field

from copilot.api.dependencies import (
    DatasetDep,
    HandoffDep,
    ServiceDep,
    SettingsDep,
    StoreDep,
    ZendeskDep,
    require_auth,
    require_jira_callback_token,
    require_sidebar_token,
)
from copilot.config import Settings
from copilot.domain import (
    AuditEvent,
    EngineeringHandoff,
    EvaluationReport,
    Suggestion,
    SupportCase,
)
from copilot.evaluation import evaluate
from copilot.fixtures import dataset_sha256, support_cases
from copilot.handoff import (
    HandoffConflictError,
    HandoffDisabledError,
    HandoffDispatchError,
    HandoffNotFoundError,
    HandoffPolicyError,
)
from copilot.zendesk_ingestion import load_controlled_ingestion

router = APIRouter()
protected = APIRouter(dependencies=[Depends(require_auth)])
sidebar = APIRouter(
    prefix="/sidebar",
    dependencies=[Depends(require_sidebar_token)],
    tags=["zendesk-sidebar"],
)


class HandoffApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve"]
    actor_id: str = Field(min_length=1, max_length=120)


class SidebarSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20_000)


class JiraCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zendesk_ticket_id: str = Field(pattern=r"^[1-9][0-9]*$")
    jira_issue_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]*-[1-9][0-9]*$")


@router.get("/healthz", tags=["operations"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", tags=["operations"])
async def readyz(
    settings: SettingsDep,
    service: ServiceDep,
    store: StoreDep,
) -> dict[str, Any]:
    cases = await store.list_cases()
    return {
        "status": "ready" if cases else "degraded",
        "environment": settings.environment,
        "case_count": len(cases),
        "runtime_provider": service.provider.name,
    }


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@protected.get("/cases", response_model=list[SupportCase], tags=["cases"])
async def list_cases(store: StoreDep) -> list[SupportCase]:
    return await store.list_cases()


@protected.get("/cases/{case_id}", response_model=SupportCase, tags=["cases"])
async def get_case(case_id: str, store: StoreDep) -> SupportCase:
    case = await store.get_case(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


@protected.post(
    "/cases/{case_id}/suggestions",
    response_model=Suggestion,
    tags=["suggestions"],
)
async def create_suggestion(
    case_id: str,
    request: Request,
    service: ServiceDep,
    store: StoreDep,
) -> Suggestion:
    case = await store.get_case(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return await service.suggest(case, request_id=request.state.request_id)


@protected.get(
    "/cases/{case_id}/suggestions/latest",
    response_model=Suggestion,
    tags=["suggestions"],
)
async def latest_suggestion(case_id: str, store: StoreDep) -> Suggestion:
    suggestion = await store.get_suggestion(case_id)
    if suggestion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suggestion not generated")
    return suggestion


@protected.get(
    "/cases/{case_id}/audit",
    response_model=list[AuditEvent],
    tags=["audit"],
)
async def case_audit(case_id: str, store: StoreDep) -> list[AuditEvent]:
    return await store.list_audit(case_id)


@protected.get(
    "/cases/{case_id}/handoffs/engineering",
    response_model=EngineeringHandoff,
    tags=["handoffs"],
)
async def get_engineering_handoff(case_id: str, store: StoreDep) -> EngineeringHandoff:
    handoff = await store.get_handoff(case_id)
    if handoff is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Engineering handoff not found")
    return handoff


@protected.post(
    "/cases/{case_id}/handoffs/engineering",
    response_model=EngineeringHandoff,
    tags=["handoffs"],
)
async def approve_engineering_handoff(
    case_id: str,
    payload: HandoffApprovalRequest,
    request: Request,
    handoffs: HandoffDep,
) -> EngineeringHandoff:
    actor = request.headers.get("x-amzn-oidc-identity") or payload.actor_id
    try:
        return await handoffs.approve(
            case_id,
            approved_by=actor,
            approval_source="copilot_web",
            request_id=request.state.request_id,
        )
    except (
        HandoffConflictError,
        HandoffDisabledError,
        HandoffDispatchError,
        HandoffNotFoundError,
        HandoffPolicyError,
    ) as error:
        raise _handoff_http_error(error) from error


@protected.post("/evaluations/golden", response_model=EvaluationReport, tags=["evaluation"])
async def golden_evaluation(dataset: DatasetDep, service: ServiceDep) -> EvaluationReport:
    return await evaluate(dataset, service)


@protected.post("/ingestion/fixtures/reset", tags=["ingestion"])
async def reset_fixtures(
    settings: SettingsDep,
    dataset: DatasetDep,
    store: StoreDep,
) -> dict[str, Any]:
    if settings.environment == "production":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Fixture reset is disabled in production.",
        )
    await store.replace_seed(dataset.articles, support_cases(dataset))
    return {
        "state": "fixture_seeded",
        "dataset_id": dataset.dataset_id,
        "dataset_sha256": dataset_sha256(settings.dataset_path),
        "article_count": len(dataset.articles),
        "case_count": len(dataset.cases),
    }


@protected.post("/ingestion/zendesk/controlled", tags=["ingestion"])
async def ingest_controlled_zendesk_ticket(
    request: Request,
    settings: SettingsDep,
    adapter: ZendeskDep,
    store: StoreDep,
) -> dict[str, Any]:
    if settings.zendesk_controlled_manifest_path is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Controlled Zendesk ingestion is not configured.",
        )
    controlled = load_controlled_ingestion(settings.zendesk_controlled_manifest_path)
    manifest = controlled.manifest
    readback = await adapter.controlled_ticket(
        manifest.ticket_id,
        expected_tags=set(manifest.expected_tags),
        minimum_private_comments=manifest.minimum_private_comments,
    )
    if readback.subdomain != manifest.subdomain:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Controlled Zendesk readback did not match the approved subdomain.",
        )
    case_payload = controlled.case.model_dump(mode="json")
    if readback.created_at:
        case_payload["created_at"] = readback.created_at
    case = SupportCase.model_validate(case_payload)
    await store.upsert_case(case)
    await store.append_audit(
        AuditEvent(
            id=str(uuid.uuid4()),
            event_type="ingestion.zendesk_controlled",
            subject_id=case.id,
            request_id=request.state.request_id,
            outcome="verified_and_ingested",
            policy_version="support-safety-v1",
            metadata={
                "subdomain": readback.subdomain,
                "provider_ticket_id": readback.ticket_id,
                "private_comment_count": readback.private_comment_count,
                "payload_sha256": controlled.payload_sha256,
            },
        )
    )
    return {
        "state": "live_controlled_ticket_ingested",
        "case_id": case.id,
        "source": case.source,
        "source_ref": case.source_ref,
        "provider_readback": readback.model_dump(),
        "payload_sha256": controlled.payload_sha256,
        "human_review_required": True,
    }


@protected.get("/integrations/zendesk/status", tags=["integrations"])
async def zendesk_status(adapter: ZendeskDep) -> dict[str, Any]:
    return (await adapter.status()).model_dump()


@protected.get("/integrations/zendesk/inventory", tags=["integrations"])
async def zendesk_inventory(
    adapter: ZendeskDep,
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    return await adapter.inventory(page_size=page_size)


@sidebar.get("/tickets/{ticket_id}")
async def sidebar_ticket_state(
    ticket_id: str,
    settings: SettingsDep,
    store: StoreDep,
) -> dict[str, Any]:
    if not ticket_id.isdigit() or int(ticket_id) < 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid Zendesk ticket ID")
    _require_allowed_zendesk_ticket(ticket_id, settings)
    case_id = f"ZD-{ticket_id}"
    case = await store.get_case(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket has not been analysed")
    return {
        "case": case.model_dump(mode="json"),
        "suggestion": (
            suggestion.model_dump(mode="json")
            if (suggestion := await store.get_suggestion(case_id))
            else None
        ),
        "handoff": (
            handoff.model_dump(mode="json")
            if (handoff := await store.get_handoff(case_id))
            else None
        ),
    }


@sidebar.post("/tickets/{ticket_id}/suggestions")
async def sidebar_ticket_suggestion(
    ticket_id: str,
    payload: SidebarSuggestionRequest,
    request: Request,
    settings: SettingsDep,
    service: ServiceDep,
    store: StoreDep,
) -> dict[str, Any]:
    if not ticket_id.isdigit() or int(ticket_id) < 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid Zendesk ticket ID")
    _require_allowed_zendesk_ticket(ticket_id, settings)
    case = SupportCase(
        id=f"ZD-{ticket_id}",
        subject=payload.subject,
        body=payload.body,
        source="zendesk_sidebar",
        source_ref=f"{settings.zendesk_subdomain}:ticket:{ticket_id}",
    )
    await store.upsert_case(case)
    suggestion = await service.suggest(case, request_id=request.state.request_id)
    return {
        "case": case.model_dump(mode="json"),
        "suggestion": suggestion.model_dump(mode="json"),
        "handoff": (
            handoff.model_dump(mode="json")
            if (handoff := await store.get_handoff(case.id))
            else None
        ),
    }


@sidebar.post(
    "/tickets/{ticket_id}/handoffs/engineering",
    response_model=EngineeringHandoff,
)
async def sidebar_approve_engineering_handoff(
    ticket_id: str,
    payload: HandoffApprovalRequest,
    request: Request,
    settings: SettingsDep,
    handoffs: HandoffDep,
) -> EngineeringHandoff:
    if not ticket_id.isdigit() or int(ticket_id) < 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid Zendesk ticket ID")
    _require_allowed_zendesk_ticket(ticket_id, settings)
    try:
        return await handoffs.approve(
            f"ZD-{ticket_id}",
            approved_by=payload.actor_id,
            approval_source="zendesk_sidebar",
            request_id=request.state.request_id,
        )
    except (
        HandoffConflictError,
        HandoffDisabledError,
        HandoffDispatchError,
        HandoffNotFoundError,
        HandoffPolicyError,
    ) as error:
        raise _handoff_http_error(error) from error


@router.post(
    "/integrations/jira/callback",
    response_model=EngineeringHandoff,
    dependencies=[Depends(require_jira_callback_token)],
    tags=["integrations"],
)
async def jira_handoff_callback(
    payload: JiraCallbackRequest,
    request: Request,
    handoffs: HandoffDep,
) -> EngineeringHandoff:
    try:
        return await handoffs.complete_from_jira(
            provider_ticket_id=payload.zendesk_ticket_id,
            jira_issue_key=payload.jira_issue_key,
            request_id=request.state.request_id,
        )
    except (HandoffConflictError, HandoffNotFoundError, HandoffPolicyError) as error:
        raise _handoff_http_error(error) from error


def _handoff_http_error(error: Exception) -> HTTPException:
    if isinstance(error, HandoffDisabledError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error))
    if isinstance(error, HandoffNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(error))
    if isinstance(error, HandoffDispatchError):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, str(error))
    return HTTPException(status.HTTP_409_CONFLICT, str(error))


def _require_allowed_zendesk_ticket(ticket_id: str, settings: Settings) -> None:
    if ticket_id not in settings.zendesk_handoff_allowed_ticket_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Zendesk ticket is outside the configured handoff scope.",
        )


router.include_router(sidebar)
router.include_router(protected)
