import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from copilot.domain import SupportCase


class ControlledZendeskManifest(BaseModel):
    schema_version: Literal["1.0.0"]
    classification: Literal["controlled_synthetic"]
    subdomain: str
    ticket_id: str
    payload_sha256: str
    payload_file: str
    receipt_file: str
    expected_tags: list[str]
    minimum_private_comments: int = Field(ge=1, le=10)

    @field_validator("payload_file", "receipt_file")
    @classmethod
    def require_local_filename(cls, value: str) -> str:
        if Path(value).name != value or value in {".", ".."}:
            raise ValueError("controlled ingestion files must be local filenames")
        return value


class ControlledZendeskIngestion(BaseModel):
    manifest: ControlledZendeskManifest
    case: SupportCase
    payload_sha256: str


def load_controlled_ingestion(path: Path) -> ControlledZendeskIngestion:
    manifest = ControlledZendeskManifest.model_validate_json(path.read_text())
    root = path.resolve().parent
    payload_path = root / manifest.payload_file
    receipt_path = root / manifest.receipt_file
    payload_bytes = payload_path.read_bytes()
    digest = hashlib.sha256(payload_bytes).hexdigest()
    if digest != manifest.payload_sha256:
        raise ValueError("controlled Zendesk payload SHA-256 mismatch")
    payload = json.loads(payload_bytes)
    receipt = json.loads(receipt_path.read_text())
    if not (
        receipt.get("schema_version") == "1.0.0"
        and receipt.get("state") == "completed"
        and receipt.get("command") == "tickets create"
        and receipt.get("subdomain") == manifest.subdomain
        and receipt.get("target") == "new"
        and str(receipt.get("provider_id")) == manifest.ticket_id
        and receipt.get("provider_status") == 201
        and receipt.get("readback_passed") is True
        and receipt.get("payload_sha256") == digest
    ):
        raise ValueError("controlled Zendesk receipt is incomplete or does not match")
    ticket = payload.get("ticket", {})
    comment = ticket.get("comment", {}) if isinstance(ticket, dict) else {}
    if not isinstance(comment, dict) or comment.get("public") is not False:
        raise ValueError("controlled Zendesk source comment must be private")
    subject = ticket.get("subject")
    body = comment.get("body")
    tags = ticket.get("tags")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("controlled Zendesk payload requires a subject")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("controlled Zendesk payload requires a private comment body")
    if not isinstance(tags, list) or not set(manifest.expected_tags).issubset(
        str(tag) for tag in tags
    ):
        raise ValueError("controlled Zendesk payload tags do not match the manifest")
    return ControlledZendeskIngestion(
        manifest=manifest,
        case=SupportCase(
            id=f"ZD-{manifest.ticket_id}",
            subject=subject,
            body=body,
            source="zendesk_live_controlled",
            source_ref=f"{manifest.subdomain}:ticket:{manifest.ticket_id}",
        ),
        payload_sha256=digest,
    )
