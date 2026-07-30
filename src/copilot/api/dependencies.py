import secrets
from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request, status

from copilot.auth import AuthenticationError, verify_alb_claims
from copilot.config import Settings
from copilot.fixtures import FixtureDataset
from copilot.handoff import EngineeringHandoffService
from copilot.service import CopilotService
from copilot.storage import Store
from copilot.zendesk_adapter import ZendeskCLIAdapter


def settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def store(request: Request) -> Store:
    return cast(Store, request.app.state.store)


def service(request: Request) -> CopilotService:
    return cast(CopilotService, request.app.state.service)


def dataset(request: Request) -> FixtureDataset:
    return cast(FixtureDataset, request.app.state.dataset)


def zendesk(request: Request) -> ZendeskCLIAdapter:
    return cast(ZendeskCLIAdapter, request.app.state.zendesk)


def handoffs(request: Request) -> EngineeringHandoffService:
    return cast(EngineeringHandoffService, request.app.state.handoffs)


async def require_auth(
    config: Annotated[Settings, Depends(settings)],
    authorization: Annotated[str | None, Header()] = None,
    alb_data: Annotated[str | None, Header(alias="x-amzn-oidc-data")] = None,
    alb_identity: Annotated[str | None, Header(alias="x-amzn-oidc-identity")] = None,
) -> None:
    if config.auth_mode == "development":
        return
    if config.auth_mode == "bearer":
        expected = f"Bearer {config.api_key}"
        if authorization is not None and secrets.compare_digest(authorization, expected):
            return
    elif config.auth_mode == "alb_oidc" and alb_data and alb_identity:
        try:
            await verify_alb_claims(alb_data, alb_identity, config)
            return
        except AuthenticationError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid authentication is required.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from error
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_sidebar_token(
    config: Annotated[Settings, Depends(settings)],
    supplied: Annotated[str | None, Header(alias="x-copilot-app-token")] = None,
) -> None:
    if (
        config.handoff_enabled
        and config.zendesk_sidebar_token
        and supplied is not None
        and secrets.compare_digest(supplied, config.zendesk_sidebar_token)
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid Zendesk sidebar authentication is required.",
    )


async def require_jira_callback_token(
    config: Annotated[Settings, Depends(settings)],
    supplied: Annotated[str | None, Header(alias="x-copilot-callback-token")] = None,
) -> None:
    if (
        config.handoff_enabled
        and config.jira_callback_token
        and supplied is not None
        and secrets.compare_digest(supplied, config.jira_callback_token)
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid Jira callback authentication is required.",
    )


SettingsDep = Annotated[Settings, Depends(settings)]
StoreDep = Annotated[Store, Depends(store)]
ServiceDep = Annotated[CopilotService, Depends(service)]
DatasetDep = Annotated[FixtureDataset, Depends(dataset)]
ZendeskDep = Annotated[ZendeskCLIAdapter, Depends(zendesk)]
HandoffDep = Annotated[EngineeringHandoffService, Depends(handoffs)]
