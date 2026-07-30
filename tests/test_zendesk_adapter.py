import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from copilot.zendesk_adapter import ControlledTicketReadback, ZendeskCLIAdapter, _count


async def test_read_only_allowlist_rejects_mutating_command() -> None:
    adapter = ZendeskCLIAdapter(Path("/nonexistent/zendesk-cli"))

    with pytest.raises(ValueError, match="read-only allowlist"):
        await adapter._run("tickets", "update", "--id", "1")


async def test_timeout_kills_and_reaps_cli_process(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeProcess:
        returncode: int | None = None
        killed = False
        waited = False

        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.Future()
            return b"", b""

        def kill(self) -> None:
            self.killed = True

        async def wait(self) -> int:
            self.waited = True
            self.returncode = -9
            return self.returncode

    process = FakeProcess()

    async def create_subprocess(*args: Any, **kwargs: Any) -> FakeProcess:
        return process

    async def time_out(awaitable: Any, timeout: float) -> Any:
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess)
    monkeypatch.setattr(asyncio, "wait_for", time_out)
    adapter = ZendeskCLIAdapter(Path("/synthetic/zendesk-cli"))

    with pytest.raises(RuntimeError, match="timed out"):
        await adapter._run("tickets", "list", "--page-size", "1", "--json")

    assert process.killed is True
    assert process.waited is True


async def test_subprocess_receives_only_allowlisted_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"{}", b""

    captured_environment: dict[str, str] = {}
    captured_command: tuple[str, ...] = ()

    async def create_subprocess(*args: Any, **kwargs: Any) -> FakeProcess:
        nonlocal captured_command
        captured_command = tuple(str(arg) for arg in args)
        captured_environment.update(kwargs["env"])
        return FakeProcess()

    monkeypatch.setenv("HOME", "/synthetic/home")
    monkeypatch.setenv("PATH", "/synthetic/bin")
    monkeypatch.setenv("ZENDESK_CLIENT_ID", "allowed-zendesk-client")
    monkeypatch.setenv("COPILOT_DATABASE_PASSWORD", "must-not-cross-boundary")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-cross-boundary")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess)

    adapter = ZendeskCLIAdapter(Path("/synthetic/zendesk-cli"))
    await adapter._run("tickets", "list", "--page-size", "1", "--json")

    assert captured_environment["HOME"] == "/synthetic/home"
    assert captured_environment["ZENDESK_CLIENT_ID"] == "allowed-zendesk-client"
    assert "COPILOT_DATABASE_PASSWORD" not in captured_environment
    assert "AWS_SECRET_ACCESS_KEY" not in captured_environment
    assert captured_command[:3] == (
        "/synthetic/zendesk-cli",
        "--config",
        "/tmp/copilot-zendesk-cli-config.json",
    )


def test_inventory_count_handles_expected_and_malformed_payloads() -> None:
    assert _count({"data": {"tickets": [{}, {}]}}, "tickets") == 2
    assert _count({"data": "redacted"}, "tickets") == 0


async def test_controlled_ticket_readback_returns_only_safe_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = ZendeskCLIAdapter(Path("/synthetic/zendesk-cli"))

    async def run(*args: str) -> dict[str, Any]:
        if args[:2] == ("tickets", "get"):
            return {
                "state": "live_readback_passed",
                "subdomain": "example",
                "data": {
                    "ticket": {
                        "id": 4,
                        "status": "open",
                        "priority": "normal",
                        "type": "question",
                        "tags": ["controlled_synthetic", "no_customer_data"],
                        "created_at": "2026-07-28T22:20:32Z",
                        "updated_at": "2026-07-28T22:20:32Z",
                        "subject": "[REDACTED]",
                        "requester_id": 123,
                    }
                },
            }
        return {
            "state": "live_readback_passed",
            "subdomain": "example",
            "data": {
                "comments": [
                    {"id": 1, "body": "[REDACTED]", "public": False},
                    {"id": 2, "body": "[REDACTED]", "public": True},
                ]
            },
        }

    monkeypatch.setattr(adapter, "_run", run)
    readback = await adapter.controlled_ticket(
        "4",
        expected_tags={"controlled_synthetic", "no_customer_data"},
        minimum_private_comments=1,
    )

    assert readback.ticket_id == "4"
    assert readback.private_comment_count == 1
    assert readback.total_comment_count == 2
    assert "requester_id" not in readback.model_dump()


async def test_controlled_ticket_readback_rejects_wrong_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = ZendeskCLIAdapter(Path("/synthetic/zendesk-cli"))

    async def run(*args: str) -> dict[str, Any]:
        if args[:2] == ("tickets", "get"):
            return {
                "state": "live_readback_passed",
                "subdomain": "example",
                "data": {"ticket": {"id": 4, "tags": ["unexpected"], "status": "open"}},
            }
        return {"data": {"comments": [{"public": False}]}}

    monkeypatch.setattr(adapter, "_run", run)

    with pytest.raises(RuntimeError, match="expected controlled tags"):
        await adapter.controlled_ticket(
            "4",
            expected_tags={"controlled_synthetic"},
            minimum_private_comments=1,
        )


async def test_engineering_escalation_write_is_private_gated_and_exact() -> None:
    class RecordingAdapter(ZendeskCLIAdapter):
        def __init__(self) -> None:
            super().__init__(Path("/synthetic/zendesk-cli"))
            self.payload: dict[str, Any] | None = None
            self.approval: dict[str, Any] | None = None
            self.write_calls = 0

        async def controlled_ticket(
            self,
            ticket_id: str,
            *,
            expected_tags: set[str],
            minimum_private_comments: int,
        ) -> ControlledTicketReadback:
            assert ticket_id == "41"
            assert expected_tags == set()
            assert minimum_private_comments == 0
            return ControlledTicketReadback(
                subdomain="example",
                ticket_id=ticket_id,
                status="open",
                priority="high",
                ticket_type="problem",
                tags=["ai_copilot_enabled"],
                private_comment_count=1,
                total_comment_count=1,
                created_at="2026-07-29T00:00:00Z",
                updated_at="2026-07-29T00:05:00Z",
            )

        async def _run(
            self,
            *args: str,
            allowed_write: tuple[str, str] | None = None,
        ) -> dict[str, Any]:
            assert allowed_write == ("tickets", "update")
            payload_path = Path(args[args.index("--payload") + 1])
            self.payload = json.loads(payload_path.read_text())
            if "--execute" not in args:
                return {
                    "state": "dry_run",
                    "approval_manifest_template": {
                        "schema_version": "1.0.0",
                        "command": "tickets update",
                        "subdomain": "example",
                        "target": "41",
                        "payload_sha256": "digest",
                        "owner_approved": False,
                    },
                }
            self.write_calls += 1
            approval_path = Path(args[args.index("--approval-manifest") + 1])
            self.approval = json.loads(approval_path.read_text())
            return {
                "state": "completed",
                "command": "tickets update",
                "provider_id": "41",
                "provider_status": 200,
                "readback_passed": True,
            }

    adapter = RecordingAdapter()

    receipt = await adapter.approve_engineering_escalation(
        "41",
        handoff_id="handoff_abc",
        escalation_tag="engineering_escalation_approved",
    )

    assert receipt.readback_passed is True
    assert adapter.write_calls == 1
    assert adapter.payload is not None
    assert adapter.payload["ticket"]["comment"]["public"] is False
    assert adapter.payload["ticket"]["safe_update"] is True
    assert adapter.payload["ticket"]["updated_stamp"] == "2026-07-29T00:05:00Z"
    assert set(adapter.payload["ticket"]["tags"]) == {
        "ai_copilot_enabled",
        "engineering_escalation_approved",
    }
    assert adapter.approval is not None
    assert adapter.approval["owner_approved"] is True


async def test_engineering_escalation_accepts_verified_trigger_tag_race() -> None:
    class TriggerRaceAdapter(ZendeskCLIAdapter):
        def __init__(self) -> None:
            super().__init__(Path("/synthetic/zendesk-cli"))
            self.readbacks = 0

        async def controlled_ticket(
            self,
            ticket_id: str,
            *,
            expected_tags: set[str],
            minimum_private_comments: int,
        ) -> ControlledTicketReadback:
            self.readbacks += 1
            if self.readbacks == 1:
                assert expected_tags == set()
                assert minimum_private_comments == 0
                tags = ["ai_copilot_enabled"]
                private_comments = 1
                updated_at = "2026-07-29T00:05:00Z"
            else:
                assert expected_tags == {"engineering_escalation_approved"}
                assert minimum_private_comments == 2
                tags = [
                    "ai_copilot_enabled",
                    "engineering_escalation_approved",
                    "engineering_escalation_sent",
                ]
                private_comments = 2
                updated_at = "2026-07-29T00:06:00Z"
            return ControlledTicketReadback(
                subdomain="example",
                ticket_id=ticket_id,
                status="open",
                priority="high",
                ticket_type="problem",
                tags=tags,
                private_comment_count=private_comments,
                total_comment_count=private_comments,
                created_at="2026-07-29T00:00:00Z",
                updated_at=updated_at,
            )

        async def _run(
            self,
            *args: str,
            allowed_write: tuple[str, str] | None = None,
        ) -> dict[str, Any]:
            assert allowed_write == ("tickets", "update")
            if "--execute" not in args:
                return {
                    "state": "dry_run",
                    "approval_manifest_template": {
                        "schema_version": "1.0.0",
                        "command": "tickets update",
                        "subdomain": "example",
                        "target": "41",
                        "payload_sha256": "digest",
                        "owner_approved": False,
                    },
                }
            raise RuntimeError(
                "Zendesk CLI command failed: write completed but readback failed: "
                "provider field tags does not match the approved payload"
            )

    adapter = TriggerRaceAdapter()

    receipt = await adapter.approve_engineering_escalation(
        "41",
        handoff_id="handoff_abc",
        escalation_tag="engineering_escalation_approved",
    )

    assert receipt.state == "completed_after_trigger_readback"
    assert receipt.readback_passed is True
    assert adapter.readbacks == 2
