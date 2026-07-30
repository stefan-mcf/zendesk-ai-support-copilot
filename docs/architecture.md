# Architecture

## Request path

1. An authenticated operator or private Zendesk app submits a support case.
2. The API normalises the case and retrieves the highest-scoring approved articles.
3. The selected model provider returns a bounded response.
4. Policy checks classify the case as `draft`, `escalate` or `block`.
5. The suggestion, citations, risk findings and request ID are stored.
6. The interface presents the result for human review.

## Services

| Service | Responsibility |
| --- | --- |
| FastAPI | Versioned routes, authentication, suggestions, evaluation and metrics |
| PostgreSQL | Cases, suggestions, handoffs and append-only audit events |
| pgvector | Knowledge embeddings and similarity search |
| React console | Review queue, case inspection and release-gate evaluation |
| Zendesk app | Ticket context, private analysis and approval action |
| Jira callback | Verified issue key and final handoff transition |

## Model providers

`DeterministicDraftProvider` makes local and CI evaluation reproducible. `BedrockDraftProvider` supplies the hosted inference path with request timeout and output-token limits.

Provider selection does not change the policy layer. Retrieval, route gates, citations, audit and human-review requirements stay within the application.

## Persistence

Alembic manages the database schema. The production application uses a non-admin database role. The handoff transition uses compare-and-set state changes so concurrent approvals and callbacks cannot create two outbound actions or move a completed handoff backward.

## AWS topology

The Terraform configuration defines:

- HTTPS Application Load Balancer with Cognito authentication;
- separate ECS Fargate API and web services;
- private PostgreSQL RDS with deletion protection;
- Secrets Manager references for database and provider credentials;
- CloudWatch logs, dashboard and alarms;
- deployment circuit breaker and bounded target deregistration.

