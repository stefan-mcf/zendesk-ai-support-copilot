import hashlib
import json
from pathlib import Path

import pytest

from copilot.zendesk_ingestion import load_controlled_ingestion


def write_fixture_manifest(root: Path, *, public: bool = False) -> Path:
    payload = {
        "ticket": {
            "subject": "Controlled support case",
            "comment": {"body": "Synthetic case body.", "public": public},
            "tags": ["controlled_synthetic", "no_customer_data"],
        }
    }
    payload_path = root / "payload.json"
    payload_bytes = (json.dumps(payload) + "\n").encode()
    payload_path.write_bytes(payload_bytes)
    digest = hashlib.sha256(payload_bytes).hexdigest()
    receipt = {
        "schema_version": "1.0.0",
        "state": "completed",
        "command": "tickets create",
        "subdomain": "example",
        "target": "new",
        "payload_sha256": digest,
        "provider_id": "4",
        "provider_status": 201,
        "readback_passed": True,
        "recorded_at": "2026-07-28T22:22:08Z",
    }
    (root / "receipt.json").write_text(json.dumps(receipt))
    manifest = {
        "schema_version": "1.0.0",
        "classification": "controlled_synthetic",
        "subdomain": "example",
        "ticket_id": "4",
        "payload_sha256": digest,
        "payload_file": "payload.json",
        "receipt_file": "receipt.json",
        "expected_tags": ["controlled_synthetic", "no_customer_data"],
        "minimum_private_comments": 1,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path


def test_controlled_ingestion_requires_exact_completed_receipt(tmp_path: Path) -> None:
    controlled = load_controlled_ingestion(write_fixture_manifest(tmp_path))

    assert controlled.case.id == "ZD-4"
    assert controlled.case.source == "zendesk_live_controlled"
    assert controlled.case.source_ref == "example:ticket:4"
    assert controlled.case.subject == "Controlled support case"
    assert controlled.payload_sha256


def test_controlled_ingestion_rejects_public_comment(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="private"):
        load_controlled_ingestion(write_fixture_manifest(tmp_path, public=True))


def test_controlled_ingestion_rejects_payload_hash_drift(tmp_path: Path) -> None:
    manifest_path = write_fixture_manifest(tmp_path)
    (tmp_path / "payload.json").write_text("{}")

    with pytest.raises(ValueError, match="SHA-256"):
        load_controlled_ingestion(manifest_path)
