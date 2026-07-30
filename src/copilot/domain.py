from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    body: str
    locale: str = "en-au"
    source: str = "fixture"
    source_ref: str | None = None


class KnowledgeChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    document_id: str
    title: str
    text: str
    position: int
    tokens: list[str]
    vector: list[float]


class SupportCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    subject: str
    body: str
    source: str = "fixture"
    source_ref: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    score: float = Field(ge=0, le=1)
    excerpt: str


class RiskFinding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str
    blocks_draft: bool = False


class Suggestion(BaseModel):
    schema_version: str = "1.0.0"
    case_id: str
    route: Literal["draft", "escalate", "block"]
    draft: str | None
    confidence: float = Field(ge=0, le=1)
    citations: list[Citation]
    risks: list[RiskFinding]
    review_required: bool = True
    policy_version: str = "support-safety-v1"
    generated_at: datetime = Field(default_factory=utc_now)


class EngineeringHandoff(BaseModel):
    schema_version: str = "1.0.0"
    id: str
    case_id: str
    provider_ticket_id: str
    status: Literal["approved", "dispatched", "completed", "failed"]
    approved_by: str
    approval_source: Literal["copilot_web", "zendesk_sidebar"]
    zendesk_receipt_state: str | None = None
    jira_issue_key: str | None = None
    jira_issue_url: str | None = None
    failure_code: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GoldenCase(BaseModel):
    id: str
    subject: str
    body: str
    expected_article_ids: list[str]
    expected_route: Literal["draft", "escalate", "block"]
    risk_tags: list[str]


class EvaluationItem(BaseModel):
    case_id: str
    expected_route: str
    actual_route: str
    route_correct: bool
    expected_article_ids: list[str]
    retrieved_article_ids: list[str]
    citation_recall: float
    expected_risk_tags: list[str]
    risks: list[str]
    risk_recall: float
    draft_present: bool
    citation_markers_valid: bool
    sensitive_data_leak: bool
    review_required: bool
    latency_ms: float


class EvaluationReport(BaseModel):
    schema_version: str = "1.0.0"
    dataset_id: str
    provider: str
    total: int
    route_accuracy: float
    citation_recall: float
    risk_recall: float
    unsafe_draft_rate: float
    grounded_draft_rate: float
    review_gate_rate: float
    sensitive_data_leak_rate: float
    latency_ms_p50: float
    latency_ms_p95: float
    route_counts: dict[str, int]
    passed: bool
    thresholds: dict[str, float]
    items: list[EvaluationItem]
    generated_at: datetime = Field(default_factory=utc_now)


class AuditEvent(BaseModel):
    id: str
    event_type: str
    subject_id: str
    request_id: str
    outcome: str
    policy_version: str
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
