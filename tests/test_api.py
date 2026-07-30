from pathlib import Path

from fastapi.testclient import TestClient

from copilot.api.main import create_app
from copilot.config import Settings
from copilot.handoff import EngineeringHandoffService
from copilot.zendesk_adapter import ControlledTicketReadback, ZendeskDispatchReceipt


def test_health_and_case_workflow(client: TestClient) -> None:
    health = client.get("/v1/healthz")
    ready = client.get("/v1/readyz")
    cases = client.get("/v1/cases")
    suggestion = client.post("/v1/cases/S1/suggestions")
    latest = client.get("/v1/cases/S1/suggestions/latest")
    audit = client.get("/v1/cases/S1/audit")

    assert health.json() == {"status": "ok"}
    assert ready.json()["case_count"] == 40
    assert len(cases.json()) == 40
    assert suggestion.json()["route"] == "draft"
    assert latest.json() == suggestion.json()
    assert audit.json()[0]["outcome"] == "draft"
    assert health.headers["X-Request-ID"]


def test_blocked_case_never_has_draft(client: TestClient) -> None:
    response = client.post("/v1/cases/S5/suggestions")

    assert response.status_code == 200
    assert response.json()["route"] == "block"
    assert response.json()["draft"] is None


def test_fixture_reset_reports_dataset_identity(client: TestClient) -> None:
    response = client.post("/v1/ingestion/fixtures/reset")

    assert response.status_code == 200
    assert response.json()["dataset_id"] == "sm-support-copilot-seed-v2"
    assert len(response.json()["dataset_sha256"]) == 64


def test_missing_case_is_not_found(client: TestClient) -> None:
    response = client.get("/v1/cases/missing")

    assert response.status_code == 404


def test_zendesk_inventory_rejects_invalid_page_size(client: TestClient) -> None:
    response = client.get("/v1/integrations/zendesk/inventory?page_size=0")

    assert response.status_code == 422


def test_controlled_zendesk_ingestion_persists_verified_case() -> None:
    class FakeZendesk:
        async def controlled_ticket(
            self,
            ticket_id: str,
            *,
            expected_tags: set[str],
            minimum_private_comments: int,
        ) -> ControlledTicketReadback:
            assert ticket_id == "4"
            assert "controlled_synthetic" in expected_tags
            assert minimum_private_comments == 1
            return ControlledTicketReadback(
                subdomain="example",
                ticket_id="4",
                status="open",
                priority="normal",
                ticket_type="question",
                tags=sorted(expected_tags),
                private_comment_count=1,
                total_comment_count=1,
                created_at="2026-07-28T22:20:32Z",
                updated_at="2026-07-28T22:20:32Z",
            )

    root = Path(__file__).resolve().parents[1]
    settings = Settings(
        environment="test",
        dataset_path=root / "data/support-cases.json",
        zendesk_controlled_manifest_path=root / "tests/fixtures/zendesk/ingestion-manifest.json",
    )
    app = create_app(settings)
    with TestClient(app) as controlled_client:
        app.state.zendesk = FakeZendesk()
        response = controlled_client.post("/v1/ingestion/zendesk/controlled")
        case = controlled_client.get("/v1/cases/ZD-4")
        audit = controlled_client.get("/v1/cases/ZD-4/audit")

    assert response.status_code == 200
    assert response.json()["state"] == "live_controlled_ticket_ingested"
    assert response.json()["provider_readback"]["private_comment_count"] == 1
    assert case.json()["source"] == "zendesk_live_controlled"
    assert audit.json()[0]["event_type"] == "ingestion.zendesk_controlled"


def test_sidebar_to_jira_handoff_requires_tokens_and_closes_loop() -> None:
    class FakeWriter:
        async def approve_engineering_escalation(
            self,
            ticket_id: str,
            *,
            handoff_id: str,
            escalation_tag: str,
        ) -> ZendeskDispatchReceipt:
            assert ticket_id == "41"
            assert handoff_id.startswith("handoff_")
            assert escalation_tag == "engineering_escalation_approved"
            return ZendeskDispatchReceipt(
                state="completed",
                command="tickets update",
                provider_id=ticket_id,
                provider_status=200,
                readback_passed=True,
            )

    root = Path(__file__).resolve().parents[1]
    settings = Settings(
        environment="test",
        dataset_path=root / "data/support-cases.json",
        handoff_enabled=True,
        zendesk_sidebar_token="sidebar-token",
        jira_callback_token="callback-token",
        zendesk_handoff_allowed_ticket_ids={"41"},
    )
    app = create_app(settings)
    with TestClient(app) as integration_client:
        app.state.handoffs = EngineeringHandoffService(
            settings,
            app.state.store,
            FakeWriter(),
        )
        unauthenticated = integration_client.post(
            "/v1/sidebar/tickets/41/suggestions",
            json={
                "subject": "Widespread service incident",
                "body": "Every team member reports an outage.",
            },
        )
        suggestion = integration_client.post(
            "/v1/sidebar/tickets/41/suggestions",
            headers={"X-Copilot-App-Token": "sidebar-token"},
            json={
                "subject": "Widespread service incident",
                "body": "Every team member reports an outage.",
            },
        )
        disallowed = integration_client.post(
            "/v1/sidebar/tickets/42/suggestions",
            headers={"X-Copilot-App-Token": "sidebar-token"},
            json={
                "subject": "Widespread service incident",
                "body": "Every team member reports an outage.",
            },
        )
        approved = integration_client.post(
            "/v1/sidebar/tickets/41/handoffs/engineering",
            headers={"X-Copilot-App-Token": "sidebar-token"},
            json={"decision": "approve", "actor_id": "agent-7"},
        )
        unauthenticated_callback = integration_client.post(
            "/v1/integrations/jira/callback",
            json={"zendesk_ticket_id": "41", "jira_issue_key": "SUP-12"},
        )
        completed = integration_client.post(
            "/v1/integrations/jira/callback",
            headers={"X-Copilot-Callback-Token": "callback-token"},
            json={"zendesk_ticket_id": "41", "jira_issue_key": "SUP-12"},
        )

    assert unauthenticated.status_code == 401
    assert suggestion.status_code == 200
    assert disallowed.status_code == 403
    assert suggestion.json()["suggestion"]["route"] == "escalate"
    assert approved.json()["status"] == "dispatched"
    assert unauthenticated_callback.status_code == 401
    assert completed.json()["status"] == "completed"
    assert completed.json()["jira_issue_key"] == "SUP-12"
