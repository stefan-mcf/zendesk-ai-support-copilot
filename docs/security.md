# Security model

## Response boundary

There is no endpoint that publishes a customer reply. A generated draft is private, and `review_required` is true for every route.

## Engineering escalation

The only provider write path is the private engineering handoff. It requires:

- handoffs enabled in environment configuration;
- separate Zendesk sidebar and Jira callback tokens;
- a positive Zendesk ticket ID in the exact allowlist;
- an `escalate` suggestion for the same case;
- a human approval request;
- an atomic handoff claim before dispatch.

The Zendesk action is limited to a private note and escalation tag. Jira completion is accepted through a protected callback and is idempotent.

## Sensitive content

The policy layer detects credentials, authentication tokens, government identifiers, payment card patterns and contact details. Blocked cases receive no generated draft.

## Authentication and secrets

Local development can run without authentication on loopback interfaces. Production rejects development auth and requires bearer or ALB OIDC configuration plus a database connection.

Secrets are supplied at runtime. The repository contains placeholders only; tenant IDs, service keys, tokens and provider receipts are not committed.

## Data boundary

The included evaluation data is synthetic. Production use requires an approved knowledge collection, retention policy, access review and tenant-specific threat assessment.
