import asyncio
import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import BaseModel

CLI_ENV_ALLOWLIST = {
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TMPDIR",
    "XDG_CONFIG_HOME",
    "ZENDESK_BASE_URL",
    "ZENDESK_CLIENT_ID",
    "ZENDESK_CLIENT_SECRET",
    "ZENDESK_SCOPE",
    "ZENDESK_SUBDOMAIN",
}
RUNTIME_CONFIG_PATH = Path("/tmp/copilot-zendesk-cli-config.json")
TRIGGER_TAG_READBACK_ERROR = (
    "write completed but readback failed: provider field tags does not match the approved payload"
)


class ZendeskStatus(BaseModel):
    state: str
    subdomain: str
    role: str
    verified: bool
    secret_source: str


class ControlledTicketReadback(BaseModel):
    state: str = "live_controlled_ticket_verified"
    subdomain: str
    ticket_id: str
    status: str
    priority: str | None
    ticket_type: str | None
    tags: list[str]
    private_comment_count: int
    total_comment_count: int
    created_at: str | None
    updated_at: str | None


class ZendeskDispatchReceipt(BaseModel):
    state: str
    command: str
    provider_id: str
    provider_status: int
    readback_passed: bool


class ZendeskCLIAdapter:
    """Bounded subprocess adapter to the commissioned Zendesk CLI boundary."""

    def __init__(
        self,
        binary: Path,
        config_path: Path = RUNTIME_CONFIG_PATH,
    ) -> None:
        self.binary = binary
        self.config_path = config_path

    async def status(self) -> ZendeskStatus:
        payload = await self._run("auth", "status", "--live", "--json")
        return ZendeskStatus(
            state=str(payload["state"]),
            subdomain=str(payload["config"]["subdomain"]),
            role=str(payload["identity"]["user"]["role"]),
            verified=bool(payload["identity"]["user"]["verified"]),
            secret_source=str(payload["config"]["secret_source"]),
        )

    async def inventory(self, page_size: int = 25) -> dict[str, Any]:
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        tickets, articles, webhooks = await asyncio.gather(
            self._run("tickets", "list", "--page-size", str(page_size), "--json"),
            self._run(
                "help-center",
                "articles-list",
                "--page-size",
                str(page_size),
                "--json",
            ),
            self._run("webhooks", "list", "--page-size", str(page_size), "--json"),
        )
        return {
            "state": "live_read_only_inventory",
            "tickets": _count(tickets, "tickets"),
            "articles": _count(articles, "articles"),
            "webhooks": _count(webhooks, "webhooks"),
            "content_policy": "provider content remains redacted at CLI boundary",
        }

    async def controlled_ticket(
        self,
        ticket_id: str,
        *,
        expected_tags: set[str],
        minimum_private_comments: int,
    ) -> ControlledTicketReadback:
        if not ticket_id.isdigit() or int(ticket_id) < 1:
            raise ValueError("ticket_id must be a positive integer")
        ticket_payload, comments_payload = await asyncio.gather(
            self._run("tickets", "get", ticket_id, "--json"),
            self._run(
                "tickets",
                "comments",
                ticket_id,
                "--page-size",
                "100",
                "--json",
            ),
        )
        if ticket_payload.get("subdomain") != comments_payload.get(
            "subdomain",
            ticket_payload.get("subdomain"),
        ):
            raise RuntimeError("Zendesk readback subdomain mismatch")
        ticket_data = ticket_payload.get("data", {})
        ticket = ticket_data.get("ticket", {}) if isinstance(ticket_data, dict) else {}
        if str(ticket.get("id")) != ticket_id:
            raise RuntimeError("Zendesk readback returned the wrong controlled ticket")
        raw_tags = ticket.get("tags", [])
        tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else []
        if not expected_tags.issubset(tags):
            raise RuntimeError("Zendesk readback omitted expected controlled tags")
        comments_data = comments_payload.get("data", {})
        comments = comments_data.get("comments", []) if isinstance(comments_data, dict) else []
        safe_comments = [item for item in comments if isinstance(item, dict)]
        private_count = sum(item.get("public") is False for item in safe_comments)
        if private_count < minimum_private_comments:
            raise RuntimeError("Zendesk readback omitted the required private comment")
        return ControlledTicketReadback(
            subdomain=str(ticket_payload.get("subdomain", "")),
            ticket_id=ticket_id,
            status=str(ticket.get("status", "")),
            priority=str(ticket["priority"]) if ticket.get("priority") is not None else None,
            ticket_type=str(ticket["type"]) if ticket.get("type") is not None else None,
            tags=sorted(tags),
            private_comment_count=private_count,
            total_comment_count=len(safe_comments),
            created_at=(
                str(ticket["created_at"]) if ticket.get("created_at") is not None else None
            ),
            updated_at=(
                str(ticket["updated_at"]) if ticket.get("updated_at") is not None else None
            ),
        )

    async def approve_engineering_escalation(
        self,
        ticket_id: str,
        *,
        handoff_id: str,
        escalation_tag: str,
    ) -> ZendeskDispatchReceipt:
        if not ticket_id.isdigit() or int(ticket_id) < 1:
            raise ValueError("ticket_id must be a positive integer")
        if not escalation_tag or any(character.isspace() for character in escalation_tag):
            raise ValueError("escalation_tag must be a non-empty Zendesk tag")

        current = await self.controlled_ticket(
            ticket_id,
            expected_tags=set(),
            minimum_private_comments=0,
        )
        if not current.updated_at:
            raise RuntimeError("Zendesk ticket readback omitted updated_at")

        tags = sorted(set(current.tags) | {escalation_tag})
        payload = {
            "ticket": {
                "tags": tags,
                "comment": {
                    "body": (
                        "Engineering escalation approved in Support Copilot. "
                        f"Correlation: {handoff_id}. "
                        "No customer-facing reply was sent."
                    ),
                    "public": False,
                },
                "safe_update": True,
                "updated_stamp": current.updated_at,
            }
        }

        with tempfile.TemporaryDirectory(prefix="copilot-handoff-") as directory:
            root = Path(directory)
            payload_path = root / "payload.json"
            approval_path = root / "approval.json"
            receipt_path = root / "receipt.json"
            payload_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            payload_path.chmod(0o600)

            plan = await self._run(
                "tickets",
                "update",
                ticket_id,
                "--payload",
                str(payload_path),
                "--json",
                allowed_write=("tickets", "update"),
            )
            approval = plan.get("approval_manifest_template")
            if not isinstance(approval, dict):
                raise RuntimeError("Zendesk CLI dry-run omitted its approval manifest")
            if not (
                plan.get("state") == "dry_run"
                and approval.get("command") == "tickets update"
                and approval.get("target") == ticket_id
                and approval.get("owner_approved") is False
            ):
                raise RuntimeError("Zendesk CLI returned an unexpected write plan")

            approval["owner_approved"] = True
            approval_path.write_text(
                json.dumps(approval, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            approval_path.chmod(0o600)

            try:
                result = await self._run(
                    "tickets",
                    "update",
                    ticket_id,
                    "--payload",
                    str(payload_path),
                    "--execute",
                    "--confirm-subdomain",
                    str(approval["subdomain"]),
                    "--approval-manifest",
                    str(approval_path),
                    "--receipt",
                    str(receipt_path),
                    "--json",
                    allowed_write=("tickets", "update"),
                )
            except RuntimeError as error:
                if TRIGGER_TAG_READBACK_ERROR not in str(error):
                    raise
                verified = await self.controlled_ticket(
                    ticket_id,
                    expected_tags={escalation_tag},
                    minimum_private_comments=current.private_comment_count + 1,
                )
                if verified.updated_at == current.updated_at:
                    raise RuntimeError(
                        "Zendesk trigger readback did not observe a new provider update"
                    ) from error
                return ZendeskDispatchReceipt(
                    state="completed_after_trigger_readback",
                    command="tickets update",
                    provider_id=ticket_id,
                    provider_status=200,
                    readback_passed=True,
                )
            return ZendeskDispatchReceipt.model_validate(result)

    async def _run(
        self,
        *args: str,
        allowed_write: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        allowed = {
            ("auth", "status"),
            ("tickets", "list"),
            ("tickets", "get"),
            ("tickets", "comments"),
            ("help-center", "articles-list"),
            ("webhooks", "list"),
        }
        command = tuple(args[:2])
        if command not in allowed and command != allowed_write:
            raise ValueError("Zendesk adapter command is outside the read-only allowlist")
        subprocess_environment = {
            key: value for key, value in os.environ.items() if key in CLI_ENV_ALLOWLIST
        }
        process = await asyncio.create_subprocess_exec(
            str(self.binary),
            "--config",
            str(self.config_path),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=subprocess_environment,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=40)
        except (TimeoutError, asyncio.CancelledError) as error:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise RuntimeError("Zendesk read-only command timed out") from error
        if process.returncode != 0:
            message = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"Zendesk CLI command failed: {message[:240]}")
        value = json.loads(stdout)
        if not isinstance(value, dict):
            raise RuntimeError("Zendesk CLI returned a non-object response")
        return value


def _count(payload: dict[str, Any], key: str) -> int:
    data = payload.get("data", {})
    records = data.get(key, []) if isinstance(data, dict) else []
    return len(records) if isinstance(records, list) else 0
