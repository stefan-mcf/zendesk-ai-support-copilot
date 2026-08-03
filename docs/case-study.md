# Engineering case study

## Situation

Support teams can only use AI safely when the generated suggestion, its sources
and its uncertainty remain visible to the agent. Engineering escalation adds a
second problem: the transition from Zendesk to Jira must be approved,
deduplicated and confirmed back to the original ticket.

The objective was to build that complete path as one controlled system, then
verify it against a fixed evaluation set and one synthetic provider case.

## Ownership

SM Systems owned:

- workflow discovery and provider mutation boundaries;
- FastAPI domain and integration services;
- PostgreSQL and pgvector storage;
- retrieval, citation and guardrail behavior;
- React operator console and native Zendesk sidebar app;
- Zendesk and Jira integration contracts;
- fixed-case evaluation and release thresholds;
- AWS architecture, Terraform, authentication and observability;
- rollback, threat model, runbook and closeout verification.

## System design

The service ingests an approved Zendesk ticket, retrieves from eight approved
knowledge articles and asks AWS Bedrock for a bounded suggestion. Deterministic
policy then chooses `draft`, `escalate` or `block`.

Drafts require citations and remain private. Sensitive content, prompt
injection, incidents, unsupported restoration times, financial thresholds and
low-confidence retrieval can force escalation or blocking. Every route records
`review_required=true`.

An approved engineering escalation performs four controlled transitions:

1. atomically claim the outbound handoff;
2. write the approved private Zendesk state;
3. invoke the dedicated Jira Automation webhook;
4. accept the protected issue-key callback without overwriting a completed
   state.

## Failure found during commissioning

The first full provider run did not complete the Jira path. The inbound Jira
rule was configured around an existing issue even though the webhook was meant
to create the first work item. At the same time, the Zendesk trigger tag could
arrive before the CLI returned an exact tag readback.

The workflow failed closed: it did not send a public reply, did not create an
unbounded retry loop and did not create a duplicate Jira task.

The repair changed the Jira rule to accept business data without a pre-existing
issue. The Zendesk adapter gained a narrow fallback that still required the
approved tag, a new private comment and a changed provider timestamp. A
receipt-backed tag-only retrigger then completed the path without another note
or task.

## Commissioning result

The controlled case produced:

- one approved private note;
- two private Zendesk comments and zero public comments;
- one Jira task, `KAN-3`;
- one protected callback with HTTP 200;
- one matching issue in the duplicate query.

The fixed 40-case evaluation recorded 28 draft, 9 escalation and 3 block cases.
All defined route, citation, risk, grounding and review thresholds passed. The
596 ms p95 figure and percentage results apply only to the fixed synthetic set.

## Operational controls

The commissioned AWS deployment used Cognito, TLS at the Application Load
Balancer, non-root containers, read-only root filesystems, private encrypted
RDS, Secrets Manager, CloudWatch, immutable image digests and an ECS rollback
circuit breaker.

At closeout the two ECS services were healthy, seven alarms were in OK state
and the container scans contained no critical or high findings. The validation
suite contained 64 backend tests, 3 operator interaction tests and 2 Zendesk app
tests.

## Current state

The runtime was decommissioned on 2026-08-02 after controlled commissioning.
The former hostname is inactive. Historical logs, the Cognito user pool and an
encrypted manual recovery snapshot were retained.

## Claim boundary

This was an internal SM Systems implementation using controlled synthetic data.
It was not paid-client delivery, a customer deployment, real customer traffic,
autonomous public replying, general model accuracy or a measured commercial
outcome. Private credentials, tenant identifiers and provider receipts are not
included in this public repository.
