import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram

from copilot.api.routes import router
from copilot.config import Settings, get_settings
from copilot.database import PostgresStore
from copilot.fixtures import load_dataset, support_cases
from copilot.handoff import EngineeringHandoffService
from copilot.model_provider import BedrockDraftProvider, DeterministicDraftProvider, DraftProvider
from copilot.retrieval import HybridRetriever
from copilot.service import CopilotService
from copilot.storage import MemoryStore, Store
from copilot.zendesk_adapter import ZendeskCLIAdapter

REQUESTS = Counter(
    "copilot_http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "copilot_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


def build_store(settings: Settings) -> Store:
    if settings.resolved_database_url:
        return PostgresStore.from_url(settings.resolved_database_url)
    return MemoryStore()


def build_provider(settings: Settings) -> DraftProvider:
    if settings.model_provider == "bedrock":
        return BedrockDraftProvider(
            region=settings.aws_region or "",
            model_id=settings.bedrock_model_id,
            max_output_tokens=settings.model_max_output_tokens,
            timeout_seconds=settings.model_timeout_seconds,
        )
    return DeterministicDraftProvider()


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    configure_logging(config.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        dataset = load_dataset(config.dataset_path)
        store = build_store(config)
        await store.seed(dataset.articles, support_cases(dataset))
        app.state.settings = config
        app.state.dataset = dataset
        app.state.store = store
        app.state.service = CopilotService(
            config,
            store,
            HybridRetriever(dataset.articles),
            build_provider(config),
        )
        app.state.zendesk = ZendeskCLIAdapter(config.zendesk_cli_path)
        app.state.handoffs = EngineeringHandoffService(
            config,
            store,
            app.state.zendesk,
        )
        yield

    app = FastAPI(
        title="SM Systems AI Support Copilot",
        version="0.1.0",
        description=(
            "Grounded suggestions with citations, guardrails, evaluation, and human review."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:8080"],
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Copilot-App-Token",
            "X-Copilot-Callback-Token",
            "X-Request-ID",
        ],
    )

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = str(getattr(route, "path", "unmatched"))
        duration = time.perf_counter() - start
        REQUESTS.labels(request.method, path, response.status_code).inc()
        LATENCY.labels(request.method, path).observe(duration)
        response.headers["X-Request-ID"] = request_id
        structlog.get_logger().info(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=path,
            status=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )
        return response

    app.include_router(router, prefix="/v1")
    return app


app = create_app()
